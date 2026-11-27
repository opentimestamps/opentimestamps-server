# Copyright (C) 2026 The OpenTimestamps developers
#
# This file is part of the OpenTimestamps Server.
#
# It is subject to the license terms in the LICENSE file found in the top-level
# directory of this distribution.
#
# No part of the OpenTimestamps Server, including this file, may be copied,
# modified, propagated, or distributed except according to the terms contained
# in the LICENSE file.

import hashlib
import http.client
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import bitcoin.rpc
from opentimestamps.core.notary import BitcoinBlockHeaderAttestation, PendingAttestation
from opentimestamps.core.op import OpAppend, OpReverse, OpSHA256
from opentimestamps.core.serialize import BytesSerializationContext

from otsserver.backup import AskBackup, Backup
from otsserver.calendar import PlyvelCalendar


def entry(attestations=(), ops=()):
    ctx = BytesSerializationContext()
    ctx.write_varuint(len(attestations))
    for attestation in attestations:
        attestation.serialize(ctx)
    ctx.write_varuint(len(ops))
    for op in ops:
        op.serialize(ctx)
    return ctx.getbytes()


class Retried(BaseException):
    """Raised by a patched time.sleep, to stop a loop that would ask again"""


class Test_AskBackup(unittest.TestCase):
    def import_chunk(self, kv_map, attested_key, proxy=None, content=None):
        """Import a chunk whose Bitcoin attestations are valid for attested_key

        content, if given, is served instead of kv_map. Returns the calendar, and
        the exception that ended the import, if any.
        """
        if content is None:
            content = Backup._Backup__kv_map_to_bytes(kv_map)
        response = mock.Mock(status_code=200, content=content)
        if proxy is None:
            proxy = mock.Mock()
            proxy.getblockcount.return_value = 100
            proxy.getblockheader.return_value = mock.Mock(hashMerkleRoot=attested_key, nTime=1)

        self.path = tempfile.TemporaryDirectory()
        self.addCleanup(self.path.cleanup)
        calendar = PlyvelCalendar(os.path.join(self.path.name, 'db'))
        # The loop ends when it cannot write its progress file
        backup = AskBackup(calendar, 'http://127.0.0.1:1', os.path.join(self.path.name, 'missing'), 'regtest')
        with mock.patch('otsserver.backup.requests.get', return_value=response), \
                mock.patch('bitcoin.rpc.Proxy', return_value=proxy):
            try:
                backup.loop()
            except (Retried, Exception) as err:
                return calendar, err
        return calendar, None

    def assert_refused(self, kv_map=None, content=None, attested_key=None):
        """The chunk is not stored and is asked for again, and the loop goes on"""
        with mock.patch('otsserver.backup.time.sleep', side_effect=Retried) as sleep:
            calendar, err = self.import_chunk(kv_map or {}, attested_key, content=content)

        self.assertIsInstance(err, Retried)
        sleep.assert_called_once()
        self.assertEqual(list(calendar.db.iterator()), [])

    def test_only_verified_entries_are_stored(self):
        attested = b'\x01' * 32
        kv_map = {attested: entry([BitcoinBlockHeaderAttestation(5)]),
                  b'\x02' * 32: entry(),
                  b'\x03' * 32: entry([PendingAttestation('https://calendar.invalid')])}

        with self.assertLogs(level='INFO') as logs:
            calendar, err = self.import_chunk(kv_map, attested)

        self.assertIsNone(err)
        self.assertIn(attested, calendar)
        self.assertNotIn(b'\x02' * 32, calendar)
        self.assertNotIn(b'\x03' * 32, calendar)
        # Every dropped key is logged
        self.assertTrue(any(('02' * 32) in line and 'no attestation and no op' in line for line in logs.output))
        self.assertTrue(any(('03' * 32) in line and 'unverified' in line for line in logs.output))

    def test_unverified_attestation_keeps_the_entry_out(self):
        start = b'\x07' * 32
        attested = hashlib.sha256(start).digest()
        kv_map = {start: entry([PendingAttestation('https://calendar.invalid')], [OpSHA256()]),
                  attested: entry([BitcoinBlockHeaderAttestation(5)])}

        calendar, err = self.import_chunk(kv_map, attested)

        self.assertIsNone(err)
        self.assertNotIn(start, calendar)
        self.assertIn(attested, calendar)

    def test_op_to_an_entry_with_an_unverified_attestation_is_dropped(self):
        start = b'\x08' * 32
        middle = hashlib.sha256(start).digest()
        attested = hashlib.sha256(middle).digest()
        kv_map = {start: entry(ops=[OpSHA256()]),
                  middle: entry([PendingAttestation('https://calendar.invalid')], [OpSHA256()]),
                  attested: entry([BitcoinBlockHeaderAttestation(5)])}

        calendar, err = self.import_chunk(kv_map, attested)

        self.assertIsNone(err)
        self.assertNotIn(start, calendar)
        self.assertNotIn(middle, calendar)
        self.assertIn(attested, calendar)

    def test_ops_that_lead_to_a_refuted_attestation_are_dropped(self):
        start = b'\x0e' * 32
        refuted = hashlib.sha256(start).digest()
        kv_map = {start: entry(ops=[OpSHA256()]),
                  refuted: entry([BitcoinBlockHeaderAttestation(6)])}
        proxy = mock.Mock()
        proxy.getblockcount.return_value = 100
        proxy.getblockheader.return_value = mock.Mock(hashMerkleRoot=b'\xff' * 32, nTime=1)

        with mock.patch('otsserver.backup.time.sleep') as sleep:
            calendar, err = self.import_chunk(kv_map, None, proxy)

        self.assertIsNone(err)
        sleep.assert_not_called()
        self.assertNotIn(start, calendar)
        self.assertNotIn(refuted, calendar)

    def test_key_with_ops_to_a_verified_and_a_refuted_key_is_dropped(self):
        start = b'\x0f' * 32
        good = hashlib.sha256(start).digest()
        refuted = start + b'\x00'
        kv_map = {start: entry(ops=[OpSHA256(), OpAppend(b'\x00')]),
                  good: entry([BitcoinBlockHeaderAttestation(5)]),
                  refuted: entry([BitcoinBlockHeaderAttestation(6)])}
        roots = {'block 5': good, 'block 6': b'\xff' * 32}
        proxy = mock.Mock()
        proxy.getblockcount.return_value = 100
        proxy.getblockhash.side_effect = lambda height: 'block %d' % height
        proxy.getblockheader.side_effect = lambda blockhash: mock.Mock(hashMerkleRoot=roots[blockhash], nTime=1)

        calendar, err = self.import_chunk(kv_map, None, proxy)

        self.assertIsNone(err)
        self.assertNotIn(start, calendar)
        self.assertNotIn(refuted, calendar)
        self.assertIn(good, calendar)

    def test_refuted_attestation_is_not_retried_or_stored(self):
        good = b'\x09' * 32
        refuted = b'\x0a' * 32
        kv_map = {good: entry([BitcoinBlockHeaderAttestation(5)]),
                  refuted: entry([BitcoinBlockHeaderAttestation(6)])}
        roots = {'block 5': good, 'block 6': b'\xff' * 32}

        with mock.patch('otsserver.backup.time.sleep') as sleep:
            proxy = mock.Mock()
            proxy.getblockcount.return_value = 100
            proxy.getblockhash.side_effect = lambda height: 'block %d' % height
            proxy.getblockheader.side_effect = lambda blockhash: mock.Mock(hashMerkleRoot=roots[blockhash], nTime=1)

            calendar, err = self.import_chunk(kv_map, None, proxy)

        self.assertIsNone(err)
        sleep.assert_not_called()
        self.assertIn(good, calendar)
        self.assertNotIn(refuted, calendar)

    def test_cached_header_that_no_longer_matches_is_asked_again(self):
        # Block 5 was replaced after its header was cached
        before = b'\x10' * 32
        after = b'\x11' * 32
        kv_map = {before: entry([BitcoinBlockHeaderAttestation(5)]),
                  after: entry([BitcoinBlockHeaderAttestation(5)])}
        proxy = mock.Mock()
        proxy.getblockcount.return_value = 100
        proxy.getblockheader.side_effect = [mock.Mock(hashMerkleRoot=before, nTime=1),
                                            mock.Mock(hashMerkleRoot=after, nTime=1)]

        with mock.patch('otsserver.backup.time.sleep') as sleep:
            calendar, err = self.import_chunk(kv_map, None, proxy)

        self.assertIsNone(err)
        sleep.assert_not_called()
        self.assertEqual(proxy.getblockheader.call_count, 2)
        self.assertIn(after, calendar)

    def test_node_that_is_behind_is_waited_for(self):
        first = b'\x0c' * 32
        second = b'\x0d' * 32
        kv_map = {first: entry([BitcoinBlockHeaderAttestation(5)]),
                  second: entry([BitcoinBlockHeaderAttestation(6)])}
        roots = {'block 5': first, 'block 6': second}
        known = [5]  # the node knows blocks up to this height

        def catch_up(_seconds):
            known[0] = 6

        def getblockhash(height):
            if height > known[0]:
                raise IndexError('Block height out of range')
            return 'block %d' % height

        proxy = mock.Mock()
        proxy.getblockcount.side_effect = lambda: known[0]
        proxy.getblockhash.side_effect = getblockhash
        proxy.getblockheader.side_effect = lambda blockhash: mock.Mock(hashMerkleRoot=roots[blockhash], nTime=1)

        with mock.patch('otsserver.backup.time.sleep', side_effect=catch_up) as sleep:
            calendar, err = self.import_chunk(kv_map, None, proxy)

        self.assertIsNone(err)
        self.assertEqual(sleep.call_count, 1)
        self.assertIn(first, calendar)
        self.assertIn(second, calendar)

    def test_node_that_does_not_know_the_block_yet_is_waited_for(self):
        attested = b'\x0e' * 32
        known = [5]

        def catch_up(_seconds):
            known[0] = 6

        def getblockhash(height):
            if height > known[0]:
                raise IndexError('Block height out of range')
            return 'block %d' % height

        proxy = mock.Mock()
        proxy.getblockcount.return_value = 100  # the count is ahead of the blocks it can serve
        proxy.getblockhash.side_effect = getblockhash
        proxy.getblockheader.return_value = mock.Mock(hashMerkleRoot=attested, nTime=1)

        with mock.patch('otsserver.backup.time.sleep', side_effect=catch_up) as sleep:
            calendar, err = self.import_chunk({attested: entry([BitcoinBlockHeaderAttestation(6)])}, None, proxy)

        self.assertIsNone(err)
        self.assertEqual(sleep.call_count, 1)
        self.assertIn(attested, calendar)

    def test_node_error_is_retried(self):
        attested = b'\x0b' * 32
        proxy = mock.Mock()
        proxy.getblockcount.return_value = 100
        proxy.getblockhash.side_effect = [ConnectionRefusedError('down'), 'block 5', 'block 5', 'block 5']
        proxy.getblockheader.side_effect = [http.client.RemoteDisconnected('gone'),
                                            bitcoin.rpc.JSONRPCError({'code': -28, 'message': 'warming up'}),
                                            mock.Mock(hashMerkleRoot=attested, nTime=1)]

        with mock.patch('otsserver.backup.time.sleep') as sleep:
            calendar, err = self.import_chunk({attested: entry([BitcoinBlockHeaderAttestation(5)])}, attested, proxy)

        self.assertIsNone(err)
        self.assertEqual(sleep.call_count, 3)
        self.assertIn(attested, calendar)

    def test_height_far_above_a_lagging_node_is_waited_for(self):
        # A node without peers knows neither the block nor its header: its lag is no refutation
        attested = b'\x12' * 32
        known = [990]

        def catch_up(_seconds):
            known[0] = 1010

        proxy = mock.Mock()
        proxy.getblockcount.side_effect = lambda: known[0]
        proxy.getblockheader.return_value = mock.Mock(hashMerkleRoot=attested, nTime=1)

        with mock.patch('otsserver.backup.time.sleep', side_effect=catch_up) as sleep:
            calendar, err = self.import_chunk({attested: entry([BitcoinBlockHeaderAttestation(1010)])}, None, proxy)

        self.assertIsNone(err)
        self.assertEqual(sleep.call_count, 1)
        self.assertIn(attested, calendar)

    def test_value_with_trailing_bytes_is_refused(self):
        attested = b'\x14' * 32
        self.assert_refused({attested: entry([BitcoinBlockHeaderAttestation(5)]) + b'\xff\xff'},
                            attested_key=attested)

    def test_empty_chunk_is_refused(self):
        self.assert_refused(content=b'')

    def test_truncated_chunk_is_refused(self):
        attested = b'\x15' * 32
        content = Backup._Backup__kv_map_to_bytes({attested: entry([BitcoinBlockHeaderAttestation(5)])})
        self.assert_refused(content=content[:-1], attested_key=attested)

    def test_malformed_chunk_is_refused(self):
        attested = b'\x16' * 32
        for name, kv_map, content in (
                ('value cut short', {attested: entry([BitcoinBlockHeaderAttestation(5)])[:-1]}, None),
                ('unknown op', {attested: b'\x00\x01\x42'}, None),
                ('op result too long', {attested: entry(ops=[OpAppend(b'\x00' * 4096)])}, None),
                ('key length too large to read', None, bytes.fromhex('c6f7f4add284a7cffdc171a7'))):
            with self.subTest(name):
                self.assert_refused(kv_map, content=content, attested_key=attested)

    def test_every_op_must_reach_an_attestation(self):
        start = b'\x04' * 32
        attested = hashlib.sha256(start).digest()
        kv_map = {start: entry(ops=[OpAppend(b'x'), OpSHA256()]),  # the first op leads nowhere
                  attested: entry([BitcoinBlockHeaderAttestation(5)])}

        self.assert_refused(kv_map, attested_key=attested)

    def test_paths_that_rejoin_are_checked_once(self):
        keys = [b'\x05' * 32]
        for _ in range(40):
            keys.append(hashlib.sha256(keys[-1]).digest())
        # Two ops lead from each key to the next one
        kv_map = {key: entry(ops=[OpSHA256(), OpSHA256()]) for key in keys[:-1]}
        kv_map[keys[-1]] = entry([BitcoinBlockHeaderAttestation(5)])

        start = time.monotonic()
        calendar, err = self.import_chunk(kv_map, keys[-1])

        self.assertLess(time.monotonic() - start, 5)
        self.assertIsNone(err)
        self.assertIn(keys[0], calendar)

    def test_long_chain_is_resolved_in_linear_time(self):
        # Served in chain order, ending at a dropped entry: a walk that decides one key per pass is quadratic
        keys = [b'\x17' * 32]
        for _ in range(8000):
            keys.append(hashlib.sha256(keys[-1]).digest())
        ctx = BytesSerializationContext()
        for key in keys:
            if key == keys[-1]:
                value = entry([PendingAttestation('https://calendar.invalid')])
            else:
                value = entry(ops=[OpSHA256()])
            ctx.write_varuint(len(key))
            ctx.write_bytes(key)
            ctx.write_varuint(len(value))
            ctx.write_bytes(value)

        start = time.monotonic()
        calendar, err = self.import_chunk(None, None, content=ctx.getbytes())

        self.assertLess(time.monotonic() - start, 1)
        self.assertIsNone(err)
        self.assertNotIn(keys[0], calendar)

    def test_cycle_of_ops_is_rejected(self):
        first = b'\x06' * 32
        second = first[::-1]
        kv_map = {first: entry(ops=[OpReverse()]), second: entry(ops=[OpReverse()])}

        start = time.monotonic()
        self.assert_refused(kv_map, attested_key=first)

        self.assertLess(time.monotonic() - start, 5)

    def test_cycle_of_ops_is_rejected_when_optimized(self):
        test = 'otsserver.tests.test_backup.Test_AskBackup.test_cycle_of_ops_is_rejected'
        env = dict(os.environ, PYTHONOPTIMIZE='1', PYTHONPATH=os.pathsep.join(sys.path))
        result = subprocess.run([sys.executable, '-m', 'unittest', test], env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
