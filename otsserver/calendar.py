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
import threading
import time

from opentimestamps.core.timestamp import OpPrepend, OpAppend, OpSHA256, OpVerify
from opentimestamps.timestamp import make_merkle_tree, nonce_timestamp
from opentimestamps.core.notary import PendingAttestation
from opentimestamps.core.timestamp import Timestamp

from bitcoin.core import b2x

class Journal:
    """Append-only commitment storage

    The journal exists simply to make sure we never lose a commitment.
    """
    COMMITMENT_SIZE = 32 + 4

    def __init__(self, path):
        self.read_fd = open(path, "rb")

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
        os.fsync(self.append_fd.fileno())


class Calendar:
    def __init__(self, path):
        self.path = path
        self.journal = JournalWriter(path + '/journal')

    def submit(self, submitted_commitment):
        serialized_time = struct.pack('>L', int(time.time()))

        commitment = submitted_commitment.add_op(OpPrepend, serialized_time).timestamp
        commitment.add_op(OpVerify, PendingAttestation(b"fixme"))

        self.journal.submit(commitment.msg)

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
