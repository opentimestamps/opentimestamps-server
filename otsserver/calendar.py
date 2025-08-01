# Copyright (C) 2016 The OpenTimestamps developers
#
# This file is part of the OpenTimestamps Server.
#
# It is subject to the license terms in the LICENSE file found in the top-level
# directory of this distribution.
#
# No part of the OpenTimestamps Server including this file, may be copied,
# modified, propagated, or distributed except according to the terms contained
# in the LICENSE file.

import hashlib
import leveldb
import logging
import os
import queue
import struct
import sys
import threading
import time
import requests

from opentimestamps.core.notary import TimeAttestation, PendingAttestation, BitcoinBlockHeaderAttestation
from opentimestamps.core.op import Op, OpPrepend, OpAppend, OpSHA256
from opentimestamps.core.serialize import BytesDeserializationContext, BytesSerializationContext, StreamSerializationContext, StreamDeserializationContext, DeserializationError
from opentimestamps.core.timestamp import Timestamp, make_merkle_tree
from opentimestamps.timestamp import nonce_timestamp

from bitcoin.core import b2x, b2lx

# If you can make 64-bit hash collisions we'll let you add your junk to our
# calendar.
HMAC_SIZE = 8

def derive_key_for_idx(key, idx, bits=32):
    """Derive key for an index

    Uses a binary tree so that parts of the tree can be efficiently revealed
    later.
    """
    if not bits:
        return key
    else:
        key += b'\xff' if (idx >> bits-1) & 0b1 else b'\x00'
        hashed_key = hashlib.sha256(key).digest()
        return derive_key_for_idx(hashed_key, idx, bits - 1)

class Journal:
    """Append-only commitment storage

    The journal exists simply to make sure we never lose a commitment.
    """
    COMMITMENT_SIZE = 4 + 32 + HMAC_SIZE

    def __init__(self, path):
        self.read_fd = open(path, "rb")

    def __getitem__(self, idx):
        self.read_fd.seek(idx * self.COMMITMENT_SIZE)
        commitment = self.read_fd.read(self.COMMITMENT_SIZE)

        if len(commitment) == self.COMMITMENT_SIZE:
            # Strip off HMAC if not present
            if commitment[-HMAC_SIZE:] == b'\x00'*HMAC_SIZE:
                commitment = commitment[:-HMAC_SIZE]
            return commitment
        else:
            raise KeyError()


class JournalWriter(Journal):
    """Writer for the journal"""
    def __init__(self, path):
        self.append_fd = open(path, "ab")

        # In case a previous write partially failed, seek to a multiple of the
        # commitment size
        logging.info("Opening journal for appending...")
        pos = self.append_fd.tell()

        if pos % self.COMMITMENT_SIZE:
            logging.error("Journal size not a multiple of commitment size; %d bytes excess; writing padding" % (pos % self.COMMITMENT_SIZE))
            self.append_fd.write(b'\x00'*(self.COMMITMENT_SIZE - (pos % self.COMMITMENT_SIZE)))

        logging.info("Journal has %d entries" % (self.append_fd.tell() // self.COMMITMENT_SIZE))

    def submit(self, commitment):
        """Add a new commitment to the journal

        Returns only after the commitment is synchronized to disk.
        """
        # Pad with null HMAC if necessary
        if len(commitment) == self.COMMITMENT_SIZE - HMAC_SIZE:
            commitment += b'\x00'*HMAC_SIZE

        elif len(commitment) != self.COMMITMENT_SIZE:
            raise ValueError("Journal commitments must be exactly %d bytes long" % self.COMMITMENT_SIZE)

        assert (self.append_fd.tell() % self.COMMITMENT_SIZE) == 0
        self.append_fd.write(commitment)
        self.append_fd.flush()
        os.fsync(self.append_fd.fileno())

class LevelDbCalendar:
    def __del__(self):
        del self.db
    def __init__(self, path):
        self.db = leveldb.LevelDB(path)

    def __contains__(self, msg):
        try:
            self.db.Get(msg)
            return True
        except KeyError:
            return False

    def __get_timestamp(self, msg):
        """Get a timestamp, non-recursively"""
        serialized_timestamp = self.db.Get(msg)
        ctx = BytesDeserializationContext(serialized_timestamp)

        timestamp = Timestamp(msg)

        for i in range(ctx.read_varuint()):
            attestation = TimeAttestation.deserialize(ctx)
            assert attestation not in timestamp.attestations
            timestamp.attestations.add(attestation)

        for i in range(ctx.read_varuint()):
            op = Op.deserialize(ctx)
            assert op not in timestamp.ops
            timestamp.ops.add(op)

        return timestamp

    def __put_timestamp(self, new_timestamp, batch, batch_cache):
        """Write a single timestamp, non-recursively"""
        ctx = BytesSerializationContext()

        ctx.write_varuint(len(new_timestamp.attestations))
        for attestation in new_timestamp.attestations:
            attestation.serialize(ctx)

        ctx.write_varuint(len(new_timestamp.ops))
        for op in new_timestamp.ops:
            op.serialize(ctx)

        batch.Put(new_timestamp.msg.encode('utf-8'), ctx.getbytes())
        batch_cache[new_timestamp.msg] = new_timestamp

    def __getitem__(self, msg):
        """Get the timestamp for a given message"""
        timestamp = self.__get_timestamp(msg)

        for op, op_stamp in timestamp.ops.items():
            timestamp.ops[op] = self[op_stamp.msg]

        return timestamp

    def __add_timestamp(self, new_timestamp, batch, batch_cache):
        existing_timestamp = None
        try:
            if new_timestamp.msg in batch_cache:
                existing_timestamp = batch_cache[new_timestamp.msg]
            else:
                existing_timestamp = self.__get_timestamp(new_timestamp.msg)

        except KeyError:
            existing_timestamp = Timestamp(new_timestamp.msg)

        else:
            if existing_timestamp == new_timestamp:
                # Note how because we didn't get the existing timestamp
                # recursively, the only way old and new can be identical is if all
                # the ops are verify operations.
                return

        # Update the existing timestamps attestations with those from the new
        # timestamp
        existing_timestamp.attestations.update(new_timestamp.attestations)

        for new_op, new_op_stamp in new_timestamp.ops.items():
            # Make sure the existing timestamp has this operation
            existing_timestamp.ops.add(new_op)

            # Add the results timestamp to the calendar
            self.__add_timestamp(new_op_stamp, batch, batch_cache)

        self.__put_timestamp(existing_timestamp, batch, batch_cache)

    def add_timestamps(self, new_timestamps):
        batch = leveldb.WriteBatch()
        batch_cache = {}

        last = time.time()
        n = 0
        for new_timestamp in new_timestamps:
            self.__add_timestamp(new_timestamp, batch, batch_cache)
            n += 1

            if n % 10000 == 0:
                now = time.time()
                logging.debug("Added %d timestamps to LevelDB; %f stamps/second" %
                              (n, 10000.0 / (now - last)))
                last = now
        del batch_cache

        self.db.Write(batch, sync=True)
        logging.debug("Done LevelDbCalendar.add_timestamps(), added %d timestamps total" % n)


class Calendar:
    def __init__(self, path, upstream=None, upstream_timeout=15):
        path = os.path.normpath(path)
        os.makedirs(path, exist_ok=True)
        self.path = path
        self.journal = JournalWriter(os.path.join(path, 'journal'))

        self.db = LevelDbCalendar(os.path.join(path, 'db'))

        self.upstream = upstream
        self.upstream_timeout = upstream_timeout

        try:
            uri_path = os.path.join(self.path, 'uri')
            with open(uri_path, 'r') as fd:
                self.uri = fd.read().strip()
        except FileNotFoundError:
            logging.error('Calendar URI not yet set; %r does not exist', uri_path)
            sys.exit(1)
        except Exception as e:
            logging.error('Error reading Calendar URI: %s', e)
            sys.exit(1)

        try:
            hmac_key_path = os.path.join(self.path, 'hmac-key')
            with open(hmac_key_path, 'rb') as fd:
                self.hmac_key = fd.read()
        except FileNotFoundError:
            logging.error('HMAC secret key not set; %r does not exist', hmac_key_path)
            sys.exit(1)
        except Exception as e:
            logging.error('Error reading HMAC secret key: %s', e)
            sys.exit(1)

    def submit(self, submitted_commitment):
        idx = int(time.time())
        serialized_idx = struct.pack('>L', idx)
        commitment = submitted_commitment.ops.add(OpPrepend(serialized_idx))

        per_idx_key = derive_key_for_idx(self.hmac_key, idx, bits=32)
        mac = hashlib.sha256(commitment.msg + per_idx_key).digest()[0:HMAC_SIZE]
        macced_commitment = commitment.ops.add(OpAppend(mac))

        macced_commitment.attestations.add(PendingAttestation(self.uri))
        self.journal.submit(macced_commitment.msg)

        # send server commitment to upstream
        if self.upstream:
            try:
                response = requests.post(
                    self.upstream,
                    data=macced_commitment.msg,
                    timeout=self.upstream_timeout
                )
                response.raise_for_status()
                logging.info(f"Commitment sent to upstream: {self.upstream}")
            except requests.RequestException as e:
                logging.error(f"Failed to send commitment to upstream: {e}")

class Aggregator:
    def __loop(self):
        logging.info("Starting aggregator loop")
        while not self.exit_event.wait(self.commitment_interval):
            digests = []
            done_events = []
            while not self.digest_queue.empty():
                # This should never raise the Empty exception, as we should be
                # the only thread taking items off the queue
                (digest, done_event) = self.digest_queue.get_nowait()
                digests.append(digest)
                done_events.append(done_event)

            if not digests:
                continue

            digests_commitment = make_merkle_tree(digests)
            logging.info("Aggregated %d digests under commitment %s" % (len(digests), b2x(digests_commitment.msg)))
            self.calendar.submit(digests_commitment)
# Notify all requestors that the commitment is done
            for done_event in done_events:
                done_event.set()

    def __init__(self, calendar, exit_event, commitment_interval=1):
        self.calendar = calendar
        self.commitment_interval = commitment_interval
        self.digest_queue = queue.Queue()
        self.exit_event = exit_event
        self.thread = threading.Thread(target=self.__loop)
        self.thread.start()

    def submit(self, msg):   
        """Submit message for aggregation

        Aggregator thread will aggregate the message along with all other
        messages, and return a Timestamp
        """  
        timestamp = Timestamp(msg)
        # Add nonce to ensure requestor doesn't learn anything about other
        # messages being committed at the same time, as well as to ensure that
        # anything we store related to this commitment can't be controlled by
        # them.
        done_event = threading.Event()
        self.digest_queue.put((nonce_timestamp(timestamp), done_event))
        done_event.wait()
        return timestamp
