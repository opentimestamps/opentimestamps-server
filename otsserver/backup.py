#!/usr/bin/env python3
import otsserver
from otsserver.calendar import Journal
from bitcoin.core import b2x
from opentimestamps.core.notary import TimeAttestation, BitcoinBlockHeaderAttestation
from opentimestamps.core.op import Op
from opentimestamps.core.serialize import BytesSerializationContext, BytesDeserializationContext, TruncationError, \
    StreamSerializationContext
import bitcoin.rpc
import leveldb
import logging
import socketserver
import http.server
import os
import threading
import binascii
import requests
import time
from urllib.parse import urlparse, urljoin

PAGING = 1000
SLEEP_SECS = 600


class Backup:
    def __init__(self, journal, calendar, cache_path):
        self.journal = journal
        self.calendar = calendar
        self.cache_path = cache_path
        os.makedirs(cache_path, exist_ok=True)

    def __getitem__(self, chunk):
        cached_kv_bytes = self.read_disk_cache(chunk)
        if cached_kv_bytes is not None:
            return cached_kv_bytes

        backup_map = {}
        start = chunk*PAGING
        end = start+PAGING
        for i in range(start, end)[::-1]:  # iterate in reverse to fail fast
            try:
                current = self.journal[i]
                # print(str(i) +":"+b2x(journal[i]))
                current_el = self.calendar[current]
                # print("\t"+str(current_el))
                self.__create_kv_map(current_el, current_el.msg, backup_map)
            except KeyError:
                raise IndexError
            if i % 100 == 0:
                logging.info(str(i) + ":" + b2x(self.journal[i]))

        logging.info("map len " + str(len(backup_map)) + " start:" + str(start) + " end:" + str(end))
        kv_bytes = self.__kv_map_to_bytes(backup_map)
        self.write_disk_cache(chunk, kv_bytes)

        return kv_bytes

    @staticmethod
    def bytes_to_kv_map(kv_bytes):
        ctx = BytesDeserializationContext(kv_bytes)
        new_kv_map = {}

        while True:
            try:
                key_len = ctx.read_varuint()
                key = ctx.read_bytes(key_len)
                value_len = ctx.read_varuint()
                value = ctx.read_bytes(value_len)
                new_kv_map[key] = value
            except TruncationError:
                break

        return new_kv_map

    @staticmethod
    def __create_kv_map(ts, msg, kv_map):
        ctx = BytesSerializationContext()

        ctx.write_varuint(len(ts.attestations))
        for attestation in ts.attestations:
            attestation.serialize(ctx)

        ctx.write_varuint(len(ts.ops))
        for op in ts.ops:
            op.serialize(ctx)

        kv_map[msg] = ctx.getbytes()

        for op, timestamp in ts.ops.items():
            Backup.__create_kv_map(timestamp, timestamp.msg, kv_map)

    @staticmethod
    def __kv_map_to_bytes(kv_map):
        ctx = BytesSerializationContext()
        for key, value in sorted(kv_map.items()):
            ctx.write_varuint(len(key))
            ctx.write_bytes(key)
            ctx.write_varuint(len(value))
            ctx.write_bytes(value)

        return ctx.getbytes()

    def read_disk_cache(self, chunk):
        chunk_str = "{0:0>6}".format(chunk)
        chunk_path = chunk_str[0:3]

        try:
            cache_file = self.cache_path + '/' + chunk_path + '/' + chunk_str
            with open(cache_file, 'rb') as fd:
                return fd.read()
        except FileNotFoundError as err:
            return None

    def write_disk_cache(self, chunk, bytes):
        chunk_str = "{0:0>6}".format(chunk)
        chunk_path = chunk_str[0:3]
        cache_path = self.cache_path + '/' + chunk_path
        os.makedirs(cache_path, exist_ok=True)
        cache_file = cache_path + '/' + chunk_str
        with open(cache_file, 'wb') as fd:
            fd.write(bytes)


class RPCRequestHandler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path.startswith('/timestamp/'):
            self.get_timestamp()
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')

            # a 404 is only going to become not a 404 if the server is upgraded
            self.send_header('Cache-Control', 'public, max-age=3600')

            self.end_headers()
            self.wfile.write(b'Not found')

    def get_timestamp(self):
        commitment = self.path[len('/timestamp/'):]

        try:
            commitment = binascii.unhexlify(commitment)
        except binascii.Error:
            self.send_response(400)
            self.send_header('Content-type', 'text/plain')
            self.send_header('Cache-Control', 'public, max-age=31536000') # this will never not be an error!
            self.end_headers()
            self.wfile.write(b'commitment must be hex-encoded bytes')
            return

        try:
            timestamp = self.calendar[commitment]
        except KeyError:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.send_header('Cache-Control', 'public, max-age=60')
            reason = b'Not found'

            self.end_headers()
            self.wfile.write(reason)
            return

        self.send_response(200)

        # Since only Bitcoin attestations are currently made, once a commitment
        # is timestamped by Bitcoin this response will never change.
        self.send_header('Cache-Control', 'public, max-age=3600')

        self.send_header('Content-type', 'application/octet-stream')
        self.end_headers()

        timestamp.serialize(StreamSerializationContext(self.wfile))


class BackupCalendar:
    def __init__(self, db):
        self.db = db

    def __contains__(self, commitment):
        return commitment in self.db

    def __getitem__(self, commitment):
        """Get commitment timestamps(s)"""
        return self.db[commitment]


class BackupServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    def __init__(self, server_address, calendar):
        class rpc_request_handler(RPCRequestHandler):
            pass
        rpc_request_handler.calendar = calendar

        super().__init__(server_address, rpc_request_handler)

    def serve_forever(self):
        super().serve_forever()


class AskBackup(threading.Thread):

    def __init__(self, db, calendar_url, base_path):
        self.db = db
        self.calendar_url = calendar_url
        calendar_url_parsed = urlparse(calendar_url)
        self.up_to_path = os.path.join(base_path, calendar_url_parsed.netloc)

        super().__init__(target=self.loop)

    def loop(self):
        print("Starting loop for %s" % self.calendar_url)

        try:
            with open(self.up_to_path, 'r') as up_to_fd:
                last_known = int(up_to_fd.read().strip())
        except FileNotFoundError as exp:
            last_known = -1
        print("Checking calendar " + str(self.calendar_url) + ", last_known commitment:" + str(last_known))

        while True:
            start_time = time.time()
            backup_url = urljoin(self.calendar_url, "/experimental/backup/%d" % (last_known + 1))
            print(str(backup_url))
            try:
                r = requests.get(backup_url)
            except Exception as err:
                print("Exception asking " + str(backup_url) + " message " + str(err))
                break

            if r.status_code == 404:
                print("%s not found, sleeping for %s seconds" % (backup_url, SLEEP_SECS) )
                time.sleep(SLEEP_SECS)
                continue

            # print(r.raw.read(10))
            kv_map = Backup.bytes_to_kv_map(r.content)
            # print(str(map))
            attestations = {}
            ops = {}
            print("kv_maps elements " + str(len(kv_map)))
            for key, value in kv_map.items():
                # print("--- key=" + b2x(key) + " value=" + b2x(value))
                ctx = BytesDeserializationContext(value)

                for _a in range(ctx.read_varuint()):
                    attestation = TimeAttestation.deserialize(ctx)
                    attestations[key] = attestation

                for _b in range(ctx.read_varuint()):
                    op = Op.deserialize(ctx)
                    ops[key] = op

            proxy = bitcoin.rpc.Proxy()

            # verify all bitcoin attestation are valid
            print("total attestations: " + str(len(attestations)))
            for key, attestation in attestations.items():
                if attestation.__class__ == BitcoinBlockHeaderAttestation:
                    blockhash = proxy.getblockhash(attestation.height)
                    block_header = proxy.getblockheader(blockhash)
                    attested_time = attestation.verify_against_blockheader(key, block_header)
                    print("verifying " + b2x(key) + " result " + str(attested_time))

            # verify all ops connects to an attestation
            print("total ops: " + str(len(ops)))
            for key, op in ops.items():

                # print("key " + b2x(key) + " op " + str(op))
                current_key = key
                current_op = op
                while True:
                    next_key = current_op(current_key)
                    # print("next_key " + b2x(next_key))
                    if next_key in ops:
                        current_key = next_key
                        current_op = ops[next_key]
                    else:
                        break
                # print("maps to " + b2x(next_key))
                assert next_key in attestations

            batch = leveldb.WriteBatch()
            for key, value in kv_map.items():
                batch.Put(key, value)
            self.db.db.Write(batch, sync=True)

            last_known = last_known + 1
            try:
                with open(self.up_to_path, 'w') as up_to_fd:
                    up_to_fd.write('%d\n' % last_known)
            except FileNotFoundError as exp:
                print(str(exp))
                break

            elapsed_time = time.time() - start_time
            print("Took %ds" % elapsed_time)





