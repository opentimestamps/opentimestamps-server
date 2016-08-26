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

class Calendar:
    def __init__(self, path):
        self.path = path

    def submit(self, commitment):
        serialized_time = struct.pack('>L', int(time.time()))

        final_timestamp = commitment.add_op(OpPrepend, serialized_time).timestamp
        final_timestamp.add_op(OpVerify, PendingAttestation(b"fixme"))

        with open(self.path + '/pending/' + b2x(bytes(final_timestamp.msg)),'xb') as fd:
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
