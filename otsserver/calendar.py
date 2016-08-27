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

import logging
import os
import queue
import struct
import sys
import threading
import time

from opentimestamps.core.timestamp import OpPrepend, OpAppend, OpSHA256, OpVerify
from opentimestamps.timestamp import make_merkle_tree, nonce_timestamp
from opentimestamps.core.notary import PendingAttestation, BitcoinBlockHeaderAttestation
from opentimestamps.core.timestamp import Timestamp
from opentimestamps.core.serialize import StreamSerializationContext, StreamDeserializationContext, DeserializationError

from bitcoin.core import b2x, b2lx

class Journal:
    """Append-only commitment storage

    The journal exists simply to make sure we never lose a commitment.
    """
    COMMITMENT_SIZE = 32 + 4

    def __init__(self, path):
        self.read_fd = open(path, "rb")

    def __getitem__(self, idx):
        self.read_fd.seek(idx * self.COMMITMENT_SIZE)
        commitment = self.read_fd.read(self.COMMITMENT_SIZE)

        if len(commitment) == self.COMMITMENT_SIZE:
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

        Returns only after the commitment is syncronized to disk.
        """
        if len(commitment) != self.COMMITMENT_SIZE:
            raise ValueError("Journal commitments must be exactly %d bytes long" % self.COMMITMENT_SIZE)

        assert (self.append_fd.tell() % self.COMMITMENT_SIZE) == 0
        self.append_fd.write(commitment)
        self.append_fd.flush()
        os.fdatasync(self.append_fd.fileno())


class Calendar:
    def __init__(self, path):
        path = os.path.normpath(path)
        os.makedirs(path, exist_ok=True)
        self.path = path
        self.journal = JournalWriter(path + '/journal')

        try:
            uri_path = self.path + '/uri'
            with open(uri_path, 'rb') as fd:
                self.uri = fd.read().strip()
        except FileNotFoundError as err:
            logging.error('Calendar URI not yet set; %r does not exist' % uri_path)
            sys.exit(1)

    def submit(self, submitted_commitment):
        serialized_time = struct.pack('>L', int(time.time()))

        commitment = submitted_commitment.add_op(OpPrepend, serialized_time).timestamp
        commitment.add_op(OpVerify, PendingAttestation(self.uri))

        self.journal.submit(commitment.msg)


    def __commitment_timestamps_path(self, commitment):
        """Return the path where timestamps are stored for a given commitment"""
        # four nesting levels
        return (self.path + '/timestamps/' +
                b2x(commitment[0:1]) + '/' +
                b2x(commitment[1:2]) + '/' +
                b2x(commitment[2:3]) + '/' +
                b2x(commitment[3:4]) + '/' +
                b2x(commitment))

    def __contains__(self, commitment):
        try:
            next(self[commitment])
        except KeyError:
            return False
        return True

    def __getitem__(self, commitment):
        """Get commitment timestamps(s)"""
        commitment_path = self.__commitment_timestamps_path(commitment)
        print(commitment_path)
        try:
            timestamps = os.listdir(commitment_path)
        except FileNotFoundError:
            raise KeyError("No such commitment")

        if not timestamps:
            # An empty directory should fail too
            raise KeyError("No such commitment")

        no_valid_timestamps = True
        for timestamp_filename in sorted(timestamps):
            timestamp_path = commitment_path + '/' + timestamp_filename
            with open(timestamp_path, 'rb') as timestamp_fd:
                ctx = StreamDeserializationContext(timestamp_fd)
                try:
                    timestamp = Timestamp.deserialize(ctx, commitment)
                except DeserializationError as err:
                    logging.error("Bad commitment timestamp %r, err %r" % (timestamp_path, err))
                    continue

                no_valid_timestamps = False
                yield timestamp
        if no_valid_timestamps:
            raise KeyError("No such commitment")

    def __commitment_verification_path(self, commitment, verify_op):
        """Return the path for a specific timestamp"""
        # assuming bitcoin timestamp...
        assert verify_op.attestation.__class__ == BitcoinBlockHeaderAttestation
        return (self.__commitment_timestamps_path(commitment) +
                '/btcblk-%07d-%s' % (verify_op.attestation.height, b2lx(verify_op.msg)))


    def add_commitment_timestamp(self, timestamp):
        """Add a timestamp for a commitment"""
        path = self.__commitment_timestamps_path(timestamp.msg)
        os.makedirs(path, exist_ok=True)

        for verify_op in timestamp.verifications():
            # FIXME: we shouldn't ever be asked to open a file that aleady
            # exists, but we should handle it anyway
            with open(self.__commitment_verification_path(timestamp.msg, verify_op), 'xb') as fd:
                ctx = StreamSerializationContext(fd)
                timestamp.serialize(ctx)

                fd.flush()
                os.fsync(fd.fileno())

class Aggregator:
    def __loop(self):
        logging.info("Starting aggregator loop")
        while True:
            time.sleep(self.commitment_interval)

            digests = []
            done_events = []
            last_commitment = time.time()
            while not self.digest_queue.empty():
                # This should never raise the Empty exception, as we should be
                # the only thread taking items off the queue
                (digest, done_event) = self.digest_queue.get_nowait()
                digests.append(digest)
                done_events.append(done_event)

            if not len(digests):
                continue

            digests_commitment = make_merkle_tree(digests)

            logging.info("Aggregated %d digests under committment %s" % (len(digests), b2x(digests_commitment.msg)))

            self.calendar.submit(digests_commitment)

            # Notify all requestors that the commitment is done
            for done_event in done_events:
                done_event.set()

    def __init__(self, calendar, commitment_interval=1):
        self.calendar = calendar
        self.commitment_interval = commitment_interval
        self.digest_queue = queue.Queue()
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
        # anything we store related to this committment can't be controlled by
        # them.
        done_event = threading.Event()
        self.digest_queue.put((nonce_timestamp(timestamp), done_event))

        done_event.wait()

        return timestamp
