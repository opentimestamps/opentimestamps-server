# Copyright (C) 2018 The OpenTimestamps developers
#
# This file is part of the OpenTimestamps Server.
#
# It is subject to the license terms in the LICENSE file found in the top-level
# directory of this distribution.
#
# No part of the OpenTimestamps Server, including this file, may be copied,
# modified, propagated, or distributed except according to the terms contained
# in the LICENSE file.

from bitcoin.core import b2x
from opentimestamps.core.notary import TimeAttestation, BitcoinBlockHeaderAttestation, VerificationError
from opentimestamps.core.op import Op
from opentimestamps.core.serialize import BytesSerializationContext, BytesDeserializationContext, \
    DeserializationError, StreamSerializationContext
import bitcoin.rpc
import plyvel
import logging
import socketserver
import http.client
import http.server
import os
import threading
import binascii
import requests
from tempfile import NamedTemporaryFile
import time
from urllib.parse import urlparse, urljoin

PAGING = 1000  # Number of commitments per chunk
# Errors that mean the node can't be asked, as opposed to answering "no"
NODE_ERRORS = (OSError, http.client.HTTPException, bitcoin.rpc.JSONRPCError)

# Errors of a chunk that cannot be parsed or applied exactly
CHUNK_ERRORS = (DeserializationError, ValueError, OverflowError)

SLEEP_SECS = 60  # Once the backup is synced this is the polling interval to check for new chunks


class Backup:
    def __init__(self, journal, calendar, cache_path):
        self.journal = journal
        self.calendar = calendar
        self.cache_path = cache_path
        os.makedirs(cache_path, exist_ok=True)
        # One chunk is built at a time, so that concurrent requests for uncached chunks do not multiply the CPU load
        self.build_lock = threading.Lock()

    # Return the bytes of the chunk
    def __getitem__(self, chunk):

        # We use a disk cache, creating a chunk of 1000 commitments is a quite expensive operation of about 10s.
        # The server isn't blocked in the meantime but this could be used by an attacker to degrade calendar performance
        # Moreover is not recommended to set up an HTTP cache more than one year (see RFC 2616), thus, a disk cache is
        #  mandatory.
        cached_kv_bytes = self.read_disk_cache(chunk)
        if cached_kv_bytes is not None:
            return cached_kv_bytes

        with self.build_lock:
            # Another request may have built the chunk while this one waited
            cached_kv_bytes = self.read_disk_cache(chunk)
            if cached_kv_bytes is not None:
                return cached_kv_bytes

            backup_map = {}
            start = chunk*PAGING
            end = start+PAGING

            # Iterate in reverse to fail fast if this chunk is not complete, a chunk is considered complete if all
            # relative 1000 commitments are complete. Which means a tx with more of 6 confirmations timestamp them
            for i in range(start, end)[::-1]:
                try:
                    current = self.journal[i]
                    current_el = self.calendar[current]
                    self.__create_kv_map(current_el, current_el.msg, backup_map)
                except KeyError:
                    # according to https://docs.python.org/3/library/exceptions.html#IndexError IndexError is the more
                    # appropriate exception for this case
                    raise IndexError
                if i % 1000 == 0:
                    logging.debug("Got commitment " + str(i) + ":" + b2x(self.journal[i]))

            logging.debug("map len " + str(len(backup_map)) + " start:" + str(start) + " end:" + str(end))
            kv_bytes = self.__kv_map_to_bytes(backup_map)
            self.write_disk_cache(chunk, kv_bytes)

            return kv_bytes

    @staticmethod
    def bytes_to_kv_map(kv_bytes):
        """Parse a chunk

        Raises DeserializationError if the chunk ends inside an entry, and
        OverflowError if a length is too large to read.
        """
        ctx = BytesDeserializationContext(kv_bytes)
        new_kv_map = {}

        while ctx.fd.tell() < len(kv_bytes):
            key_len = ctx.read_varuint()
            key = ctx.read_bytes(key_len)
            value_len = ctx.read_varuint()
            value = ctx.read_bytes(value_len)
            new_kv_map[key] = value

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
        temp_file = NamedTemporaryFile(delete=False, dir=cache_path)
        temp_file.write(bytes)
        temp_file.close()
        os.rename(temp_file.name, cache_file)  # rename is atomic

# The following is a shrunk version of the standard calendar http server, it only support the '/timestamp' endpoint
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

    def __init__(self, db, calendar_url, base_path, btc_net):
        self.db = db
        self.calendar_url = calendar_url
        calendar_url_parsed = urlparse(calendar_url)
        self.up_to_path = os.path.join(base_path, calendar_url_parsed.netloc)
        self.btc_net = btc_net

        super().__init__(target=self.loop)

    @staticmethod
    def parse_chunk(kv_bytes):
        """Parse a chunk and apply its ops

        Returns the key-value map, the attestations and the ops of each key, and the results of the ops. Raises one
        of CHUNK_ERRORS if the chunk is empty, does not parse exactly, or has an op that cannot be applied.
        """
        kv_map = Backup.bytes_to_kv_map(kv_bytes)
        if not kv_map:
            raise ValueError("empty chunk")
        attestations = {}
        ops = {}
        for key, value in kv_map.items():
            ctx = BytesDeserializationContext(value)

            for _a in range(ctx.read_varuint()):
                attestations.setdefault(key, []).append(TimeAttestation.deserialize(ctx))

            for _b in range(ctx.read_varuint()):
                ops.setdefault(key, []).append(Op.deserialize(ctx))

            if ctx.fd.read(1):
                raise DeserializationError("trailing bytes in the value of %s" % b2x(key))

        op_results = {key: [op(key) for op in key_ops] for key, key_ops in ops.items()}
        return kv_map, attestations, ops, op_results

    def loop(self):
        logging.info("Starting loop for %s" % self.calendar_url)

        try:
            logging.debug("Opening %s" % self.up_to_path)
            with open(self.up_to_path, 'r') as up_to_fd:
                last_known = int(up_to_fd.read().strip())
        except FileNotFoundError as exp:
            last_known = -1
        logging.info("Checking calendar " + str(self.calendar_url) + ", last_known commitment:" + str(last_known))

        if self.btc_net == 'testnet':
            bitcoin.SelectParams('testnet')
        elif self.btc_net == 'regtest':
            bitcoin.SelectParams('regtest')

        proxy = bitcoin.rpc.Proxy()
        block_headers = {}

        while True:
            start_time = time.time()
            backup_url = urljoin(self.calendar_url, "/experimental/backup/%d" % (last_known + 1))
            logging.debug("Asking " + str(backup_url))
            try:
                r = requests.get(backup_url)
            except Exception as err:
                logging.error("Exception asking %s error message %s, sleeping for %d seconds"
                              % (str(backup_url), str(err), SLEEP_SECS))
                time.sleep(SLEEP_SECS)
                continue

            if r.status_code != 200:
                logging.info("%s not found, sleeping for %d seconds" % (backup_url, SLEEP_SECS))
                time.sleep(SLEEP_SECS)
                continue

            try:
                kv_map, attestations, ops, op_results = self.parse_chunk(r.content)
            except CHUNK_ERRORS as err:
                # Chunks are imported in order: ask for this one again
                logging.error("Malformed chunk %s: %r, sleeping for %d seconds" % (backup_url, err, SLEEP_SECS))
                time.sleep(SLEEP_SECS)
                continue

            # Verify all bitcoin attestation are valid
            logging.debug("Total attestations: " + str(len(attestations)))
            verified = set()
            unverified = set()
            for key, key_attestations in attestations.items():
                for attestation in key_attestations:
                    if attestation.__class__ != BitcoinBlockHeaderAttestation:
                        # Cannot be verified here: the key is not stored
                        unverified.add(key)
                        break
                    refuted = False
                    while True:
                        try:
                            block_header = block_headers.get(attestation.height)
                            cached = block_header is not None
                            if not cached:
                                # A node that is still syncing does not know the block yet: wait for it
                                block_count = proxy.getblockcount()
                                if attestation.height > block_count:
                                    raise IndexError("height %d is above the block count %d"
                                                     % (attestation.height, block_count))
                                blockhash = proxy.getblockhash(attestation.height)
                                block_header = proxy.getblockheader(blockhash)
                                block_headers[attestation.height] = block_header
                            attested_time = attestation.verify_against_blockheader(key, block_header)
                            logging.debug("Verifying " + b2x(key) + " result " + str(attested_time))
                            break
                        except VerificationError as err:
                            block_headers.pop(attestation.height, None)
                            if cached:
                                # The cached header may be from before a reorg: ask the node again
                                continue
                            # The node has the block and it does not match: the key is not stored
                            logging.info("%s - bitcoin attestation of %s refuted, not stored" % (err, b2x(key)))
                            refuted = True
                            break
                        except (IndexError,) + NODE_ERRORS as err:
                            logging.info("%s - bitcoin node not ready or not reachable, sleeping..." % (err))
                            block_headers.pop(attestation.height, None)
                            time.sleep(SLEEP_SECS)
                            proxy = bitcoin.rpc.Proxy()
                    if refuted:
                        unverified.add(key)
                        break
                else:
                    verified.add(key)

            # verify all ops connects to an attestation
            logging.debug("Total ops: " + str(len(ops)))
            # A key is good when all its attestations are verified and either it has no op and at
            # least one attestation, or all its ops lead to good keys. A key is dropped when it is
            # unverified (refuted or not a Bitcoin attestation) or any of its ops leads to a dropped
            # key. A dropped key is not a malformed chunk: the rest is still stored.
            good = verified - ops.keys()
            dropped = set(unverified)
            # Decide each key once, as soon as the keys its ops lead to settle it, so that a long
            # chain costs time linear in its length
            waiting = {}  # key -> how many of its op results are not known to be good yet
            leading_to = {}  # op result -> the keys with an op that leads to it
            for key, results in op_results.items():
                if key not in dropped:
                    waiting[key] = len(results)
                    for result in results:
                        leading_to.setdefault(result, []).append(key)
            decided = list(good | dropped)
            while decided:
                result = decided.pop()
                for key in leading_to.get(result, ()):
                    if key in good or key in dropped:
                        continue
                    if result in dropped:
                        dropped.add(key)
                        decided.append(key)
                    else:
                        waiting[key] -= 1
                        if not waiting[key]:
                            good.add(key)
                            decided.append(key)
            for key in sorted(dropped):
                logging.info("Not storing %s from %s: unverified, or leads to an unverified entry"
                             % (b2x(key), backup_url))
            for key in sorted(kv_map.keys() - attestations.keys() - ops.keys()):
                logging.info("Not storing %s from %s: no attestation and no op" % (b2x(key), backup_url))
            leads_nowhere = [key for key in ops if key not in good and key not in dropped]
            if leads_nowhere:
                # Malformed or cyclic: ask for the chunk again rather than skip it, as chunks are imported in order
                logging.error("Op chain of %s does not reach a verified attestation, refusing chunk %s, "
                              "sleeping for %d seconds" % (b2x(leads_nowhere[0]), backup_url, SLEEP_SECS))
                time.sleep(SLEEP_SECS)
                continue

            # Only verified entries are stored
            with self.db.db.write_batch() as batch:
                for key, value in kv_map.items():
                    if key in good:
                        batch.put(key, value)

            last_known = last_known + 1
            try:
                with open(self.up_to_path, 'w') as up_to_fd:
                    up_to_fd.write('%d\n' % last_known)
            except FileNotFoundError as exp:
                logging.error(str(exp))
                break

            elapsed_time = time.time() - start_time
            logging.info("Took %ds for %s" % (elapsed_time, str(backup_url)))
