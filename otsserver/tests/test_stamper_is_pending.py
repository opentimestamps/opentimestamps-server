# Copyright (C) 2026 The OpenTimestamps developers
#
# This file is part of the OpenTimestamps Server.
#
# It is subject to the license terms in the LICENSE file found in the top-level
# directory of this distribution.
#
# No part of the OpenTimestamps Server including this file, may be copied,
# modified, propagated, or distributed except according to the terms contained
# in the LICENSE file.

import os
import tempfile
import threading
import types
import unittest
from unittest import mock

from otsserver.calendar import Journal
from otsserver.stamper import Stamper


def entry(i):
    return i.to_bytes(4, 'big') + bytes(32) + b'\x01' * 8


class Test_is_pending(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.TemporaryDirectory()
        self.addCleanup(self.path.cleanup)
        self.journal_path = os.path.join(self.path.name, 'journal')
        open(self.journal_path, 'wb').close()
        with mock.patch.object(Stamper, '_Stamper__loop'):
            self.stamper = Stamper(types.SimpleNamespace(path=self.path.name), threading.Event(),
                                   conf_target=12, relay_feerate=1, min_confirmations=6,
                                   min_tx_interval=0, max_fee=1000000, max_pending=100)
        self.stamper.thread.join()

    def append(self, start, stop):
        with open(self.journal_path, 'ab') as fd:
            for i in range(start, stop):
                fd.write(entry(i))

    def test_journal_after_the_cursor_is_pending(self):
        self.append(0, 10)
        self.stamper.journal_cursor = 4

        self.assertTrue(self.stamper.is_pending(entry(7)))
        self.assertFalse(self.stamper.is_pending(entry(3)))
        self.assertFalse(self.stamper.is_pending(entry(10)))

        # Entries added later are found; entries the stamper loop has read are not
        self.append(10, 12)
        self.stamper.journal_cursor = 8
        self.assertTrue(self.stamper.is_pending(entry(11)))
        self.assertFalse(self.stamper.is_pending(entry(7)))
        self.assertTrue(self.stamper.is_pending(entry(8)))

        # The cursor passes everything read so far
        self.stamper.journal_cursor = 12
        self.assertFalse(self.stamper.is_pending(entry(11)))

    def test_unknown_commitment_does_not_read_the_whole_backlog_again(self):
        self.append(0, 1000)
        self.stamper.journal_cursor = 0
        self.assertFalse(self.stamper.is_pending(b'unknown'))

        reads = []
        getitem = Journal.__getitem__

        def counting_getitem(journal, idx):
            reads.append(idx)
            return getitem(journal, idx)

        with mock.patch.object(Journal, '__getitem__', counting_getitem):
            for _ in range(10):
                self.assertFalse(self.stamper.is_pending(b'unknown'))

        # One read per request, the one that finds the end of the journal
        self.assertEqual(len(reads), 10)
