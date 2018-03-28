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

PAGING = 1000  # Number of commitments per chunk
SLEEP_SECS = 60  # Once the backup is synced this is the polling interval to check for new chunks


class Backup:
    def __init__(self, journal, calendar, cache_path):
        self.journal = journal
        self.calendar = calendar
        self.cache_path = cache_path
        os.makedirs(cache_path, exist_ok=True)

    # Return the bytes of the chunk
    def __getitem__(self, chunk):

        # We use a disk cache, creating a chunk of 1000 commitments is a quite expensive operation of about 10s.
        # The server isn't blocked in the meantime but this could be used by an attacker to degrade calendar performance
        # Moreover is not recommended to set up an HTTP cache more than one year (see RFC 2616), thus, a disk cache is
        #  mandatory.
        cached_kv_bytes = self.read_disk_cache(chunk)
        if cached_kv_bytes is not None:
            return cached_kv_bytes

        backup_map = {}
        start = chunk*PAGING
        end = start+PAGING

        # Iterate in reverse to fail fast if this chunk is not complete, a chunk is considered complete if all relative
        # 1000 commitments are complete. Which means a tx with more of 6 confirmations timestamp them
        for i in range(start, end)[::-1]:
            try:
                current = self.journal[i]
                current_el = self.calendar[current]
                self.__create_kv_map(current_el, current_el.msg, backup_map)
            except KeyError:
                # according to https://docs.python.org/3/library/exceptions.html#IndexError IndexError is the more
                # appropriate exception for this case
                raise IndexError
            if i % 100 == 0:
                logging.debug("Got commitment " + str(i) + ":" + b2x(self.journal[i]))

        logging.debug("map len " + str(len(backup_map)) + " start:" + str(start) + " end:" + str(end))
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
        # Sorting the map elements to create chunks deterministically, but this is not mandatory for importing the chunk
        for key, value in sorted(kv_map.items()):
            ctx.write_varuint(len(key))
            ctx.write_bytes(key)
            ctx.write_varuint(len(value))
            ctx.write_bytes(value)

        return ctx.getbytes()

    def read_disk_cache(self, chunk):
        # For the disk cache we are using 6 digits file name which will support a total of 1 billion commitments,
        # because every chunk contain 1000 commitments. Supposing 1 commitment per second this could last for 32 years
        # which appear to be ok for this version
        chunk_str = "{0:0>6}".format(chunk)
        chunk_path = chunk_str[0:3]  # we create a path to avoid creating more than 1000 files per directory

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

# The following is a shrinked version of the standard calendar http server, it only support the '/timestamp' endpoint
# This way the backup server could serve request in place of the calendar serve which is backupping
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


# This is the thread responsible for asking the chunks to the running calendar and import them in the db.
# The main script allow to launch 1 thread of this for every calendar to backup, thus a backup server could
# theoretically serve timestamp in place of every calendar server which supports this incremental live backup mechanism
class AskBackup(threading.Thread):

    def __init__(self, db, calendar_url, base_path):
        self.db = db
        self.calendar_url = calendar_url
        calendar_url_parsed = urlparse(calendar_url)
        self.up_to_path = os.path.join(base_path, calendar_url_parsed.netloc)

        super().__init__(target=self.loop)

    def loop(self):
        logging.info("Starting loop for %s" % self.calendar_url)

        try:
            with open(self.up_to_path, 'r') as up_to_fd:
                last_known = int(up_to_fd.read().strip())
        except FileNotFoundError as exp:
            last_known = -1
        logging.info("Checking calendar " + str(self.calendar_url) + ", last_known commitment:" + str(last_known))

        while True:
            start_time = time.time()
            backup_url = urljoin(self.calendar_url, "/experimental/backup/%d" % (last_known + 1))
            logging.debug("Asking " + str(backup_url))
            try:
                r = requests.get(backup_url)
            except Exception as err:
                logging.error("Exception asking " + str(backup_url) + " message " + str(err))
                break

            if r.status_code == 404:
                logging.info("%s not found, sleeping for %s seconds" % (backup_url, SLEEP_SECS) )
                time.sleep(SLEEP_SECS)
                continue

            kv_map = Backup.bytes_to_kv_map(r.content)
            attestations = {}
            ops = {}
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

            # Verify all bitcoin attestation are valid
            logging.debug("Total attestations: " + str(len(attestations)))
            for key, attestation in attestations.items():
                if attestation.__class__ == BitcoinBlockHeaderAttestation:
                    blockhash = proxy.getblockhash(attestation.height)
                    block_header = proxy.getblockheader(blockhash)
                    # the following raise an exception and block computation if the attestation does not verify
                    attested_time = attestation.verify_against_blockheader(key, block_header)
                    logging.debug("Verifying " + b2x(key) + " result " + str(attested_time))

            # verify all ops connects to an attestation
            logging.debug("Total ops: " + str(len(ops)))
            for key, op in ops.items():
                current_key = key
                current_op = op
                while True:
                    next_key = current_op(current_key)
                    if next_key in ops:
                        current_key = next_key
                        current_op = ops[next_key]
                    else:
                        break
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
                logging.error(str(exp))
                break

            elapsed_time = time.time() - start_time
            logging.info("Took %ds for %s" % (elapsed_time, str(backup_url)))





