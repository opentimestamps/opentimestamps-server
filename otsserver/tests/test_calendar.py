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

import tempfile
import unittest

from bitcoin.core import *

from opentimestamps.core.timestamp import *

from otsserver.calendar import *

class Test_LevelDbCalendar(unittest.TestCase):
    def test_creation(self):
        with tempfile.TemporaryDirectory() as db_path:
            cal = LevelDbCalendar(db_path)

    def test_contains(self):
        with tempfile.TemporaryDirectory() as db_path:
            cal = LevelDbCalendar(db_path)

            t = Timestamp(b'foo')

            self.assertNotIn(b'foo', cal)
            cal.add(t)
            self.assertIn(b'foo', cal)

    def test_chain_timestamp(self):
        """Add/retrieve a timestamp with multiple operations"""
        with tempfile.TemporaryDirectory() as db_path:
            cal = LevelDbCalendar(db_path)

            t1 = Timestamp(b'foo')
            t2 = t1.ops.add(OpAppend(b'bar'))
            t3 = t2.ops.add(OpAppend(b'baz'))

            cal.add(t1)
            self.assertIn(b'foo', cal)
            self.assertIn(b'foobar', cal)
            self.assertIn(b'foobarbaz', cal)

            t1b = cal[b'foo']
            self.assertEqual(t1, t1b)

    def test_merkle_tree_timestamps(self):
        """Add/retrieve a merkle tree of timestamps"""
        with tempfile.TemporaryDirectory() as db_path:
            cal = LevelDbCalendar(db_path)

            roots = [Timestamp(bytes([i])) for i in range(256)]
            merkle_tip = make_merkle_tree(roots)

            for root in roots:
                cal.add(root)

                self.assertIn(merkle_tip.msg, cal)

            for root in roots:
                retrieved_root = cal[root.msg]
                self.assertEqual(root, retrieved_root)
