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

from opentimestamps.core.op import OpPrepend, OpAppend, OpSHA256
from opentimestamps.op import make_merkle_tree
from opentimestamps.core.notary import PendingAttestation
from opentimestamps.core.timestamp import Timestamp

from bitcoin.core import b2x

class Calendar:
    def __init__(self, path):
        self.path = path

    def submit(self, commitment_op):
        serialized_time = struct.pack('>L', int(time.time()))
        commitment_op2 = OpPrepend(serialized_time, commitment_op)
        commitment_op.next_op = commitment_op2

        with open(self.path + '/pending/' + b2x(bytes(commitment_op2)),'xb') as fd:
            os.fsync(fd.fileno())

class Aggregator:
    NONCE_LENGTH = 16
    """Length of nonce added to submitted messages"""

    def __loop(self):
        logging.info("Starting aggregator loop")
        while True:
            time.sleep(self.commitment_interval)

            digest_ops = []
            done_events = []
            last_commitment = time.time()
            while not self.digest_queue.empty():
                # This should never raise the Empty exception, as we should be
                # the only thread taking items off the queue
                (digest_op, done_event) = self.digest_queue.get_nowait()
                digest_ops.append(digest_op)
                done_events.append(done_event)

            if not len(digest_ops):
                continue

            commitment_op = make_merkle_tree(digest_ops)

            logging.info("Aggregated %d digests under committment %s" % (len(digest_ops), b2x(bytes(commitment_op))))

            self.calendar.submit(commitment_op)

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
        # Add nonce to ensure requestor doesn't learn anything about other
        # messages being committed at the same time, as well as to ensure that
        # anything we store related to this committment can't be controlled by
        # them.
        nonced_msg_op = OpAppend(msg, os.urandom(self.NONCE_LENGTH))
        commit_op = OpSHA256(nonced_msg_op)
        nonced_msg_op.next_op = commit_op

        done_event = threading.Event()
        self.digest_queue.put((commit_op, done_event))

        done_event.wait()

        return Timestamp(nonced_msg_op, PendingAttestation(b"deadbeef"))
