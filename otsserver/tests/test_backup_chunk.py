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

import tempfile
import threading
import time
import unittest
from unittest import mock

from opentimestamps.core.timestamp import Timestamp

from otsserver.backup import Backup, PAGING


class FakeJournal:
    def __getitem__(self, i):
        return i.to_bytes(32, 'big')


class FakeCalendar:
    def __getitem__(self, commitment):
        return Timestamp(commitment)


class Test_BackupChunkBuild(unittest.TestCase):
    def test_concurrent_requests_build_the_chunk_once(self):
        with tempfile.TemporaryDirectory() as cache_path:
            backup = Backup(FakeJournal(), FakeCalendar(), cache_path)

            builds = []
            real = Backup._Backup__kv_map_to_bytes

            def slow(kv_map):
                builds.append(1)
                time.sleep(0.3)
                return real(kv_map)

            results = []
            threads = [threading.Thread(target=lambda: results.append(backup[0])) for _ in range(5)]
            with mock.patch.object(Backup, '_Backup__kv_map_to_bytes', staticmethod(slow)):
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

            self.assertEqual(len(builds), 1)
            self.assertEqual(len(results), 5)
            self.assertEqual(len(set(results)), 1)
            self.assertEqual(len(Backup.bytes_to_kv_map(results[0])), PAGING)

    def test_failed_build_releases_the_lock(self):
        with tempfile.TemporaryDirectory() as cache_path:
            class Short(FakeJournal):
                def __getitem__(self, i):
                    raise KeyError(i)

            backup = Backup(Short(), FakeCalendar(), cache_path)
            with self.assertRaises(IndexError):
                backup[0]
            self.assertTrue(backup.build_lock.acquire(blocking=False))
            backup.build_lock.release()
