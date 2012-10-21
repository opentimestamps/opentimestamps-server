# Copyright (C) 2012 Peter Todd <pete@petertodd.org>
#
# This file is part of the OpenTimestamps Server.
#
# It is subject to the license terms in the LICENSE file found in the top-level
# directory of this distribution and at http://opentimestamps.org
#
# No part of the OpenTimestamps Server, including this file, may be copied,
# modified, propagated, or distributed except according to the terms contained
# in the LICENSE file.

import unittest

import tempfile
import os
import shutil
import hashlib
import uuid

from opentimestamps.dag import *
from opentimestamps.serialization import *

from ..dag import _MountainPeaksStore
from ..dag import *

class Test_MountainPeaksStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='tmpPeaksStore')

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test(self):
        # PeaksStore creation
        filename = self.temp_dir + '/peaks.dat'

        peaks = _MountainPeaksStore(filename,hash_algorithm='sha256',create=True)

        # Shouldn't be able to create twice
        with self.assertRaises(Exception):
            _MountainPeaksStore(filename,hash_algorithm='sha256',create=True)

        self.assertEqual(len(peaks),0)

        # Shouldn't be able to index yet
        with self.assertRaises(IndexError):
            peaks[0]
        with self.assertRaises(IndexError):
            peaks[1]
        with self.assertRaises(IndexError):
            peaks[-1]

        # Get how long the peaks file is.
        #
        # Peaks always seeks first, so this is safe.
        peaks._fd.seek(0,2)
        old_fd_tell = peaks._fd.tell()

        # can't add wrong width digest
        with self.assertRaises(ValueError):
            peaks.append(b'')
        with self.assertRaises(ValueError):
            peaks.append(b'a')
        with self.assertRaises(ValueError):
            peaks.append(b'a'*(peaks.width+1))

        # Both of these have lengths, but are of the wrong type.
        with self.assertRaises(TypeError):
            peaks.append(tuple(range(0,peaks.width)))
        with self.assertRaises(TypeError):
            peaks.append((1,2,3))

        with self.assertRaises(TypeError):
            peaks.append('*'*peaks.width)

        # None of the above should have modified the file
        peaks._fd.seek(0,2)
        self.assertEqual(old_fd_tell,peaks._fd.tell())

        def h(i):
            return bytes(str(i).rjust(peaks.width),'utf8')

        # add stuff
        n = 100
        for i in range(0,n):
            peaks.append(h(i))
            self.assertEqual(len(peaks),i+1)

        # verify before and after re-opening
        for j in (1,2):
            for i in range(0,n):
                self.assertEqual(h(i),peaks[i])
                self.assertEqual(h(n-i-1),peaks[-i-1])

            peaks = _MountainPeaksStore(filename)

        # re-open with different UUID fails
        with self.assertRaises(Exception):
            _MountainPeaksStore(filename,peaks_uuid=uuid.uuid4())


class TestMerkleMountainRangeDag(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='tmpMerkleMountainRangeDag')

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_height_at_idx(self):
        self.assertSequenceEqual(
                (0,0,1,0,0,1,2,0,0,1,0,0,1,2,3,0,0,1,0,0,1,2,0,0,1,0,0,1,2,3,4),
                [MerkleMountainRangeDag.height_at_idx(i) for i in range(0,31)])

    def test_get_mountain_peak_indexes(self):
        # 0,0,1,0,0,1,2,0,0,1,0,0,1,2,3,0,0,1,0,0,1,2,0,0,1,0,0,1,2,3,4
        self.assertSequenceEqual(
                MerkleMountainRangeDag.get_mountain_peak_indexes(1),
                (0,))
        self.assertSequenceEqual(
                MerkleMountainRangeDag.get_mountain_peak_indexes(2),
                (1,0))
        self.assertSequenceEqual(
                MerkleMountainRangeDag.get_mountain_peak_indexes(3),
                (2,))
        self.assertSequenceEqual(
                MerkleMountainRangeDag.get_mountain_peak_indexes(4),
                (3,2))
        self.assertSequenceEqual(
                MerkleMountainRangeDag.get_mountain_peak_indexes(5),
                (4,3,2))
        self.assertSequenceEqual(
                MerkleMountainRangeDag.get_mountain_peak_indexes(6),
                (5,2))
        self.assertSequenceEqual(
                MerkleMountainRangeDag.get_mountain_peak_indexes(7),
                (6,))
        self.assertSequenceEqual(
                MerkleMountainRangeDag.get_mountain_peak_indexes(30),
                (29,14))
        self.assertSequenceEqual(
                MerkleMountainRangeDag.get_mountain_peak_indexes(31),
                (30,))


    def test_peak_child(self):
        # 0,0,1,0,0,1,2,0,0,1,0,0,1,2,3,0,0,1,0,0,1,2,0,0,1,0,0,1,2,3,4
        self.assertEqual(MerkleMountainRangeDag.peak_child( 0), 2) # height 0, peak  0
        self.assertEqual(MerkleMountainRangeDag.peak_child( 1), 2) # height 0, peak  1
        self.assertEqual(MerkleMountainRangeDag.peak_child( 2), 6) # height 1, peak  0
        self.assertEqual(MerkleMountainRangeDag.peak_child( 3), 5) # height 0, peak  2
        self.assertEqual(MerkleMountainRangeDag.peak_child( 4), 5) # height 0, peak  3
        self.assertEqual(MerkleMountainRangeDag.peak_child( 5), 6) # height 1, peak  1
        self.assertEqual(MerkleMountainRangeDag.peak_child( 7), 9) # height 0, peak  4
        self.assertEqual(MerkleMountainRangeDag.peak_child( 8), 9) # height 0, peak  5
        self.assertEqual(MerkleMountainRangeDag.peak_child( 9),13) # height 1, peak  2
        self.assertEqual(MerkleMountainRangeDag.peak_child(14),30) # height 3, peak  0


    def test(self):
        dag = MerkleMountainRangeDag(self.temp_dir,create=True)
        dag = MerkleMountainRangeDag(self.temp_dir)

        digest_ops = []
        n = 2**8
        for i in range(0,n):
            digest_ops.append(Hash(inputs=(bytes(str(i),'utf8'),)))
            dag.add(digest_ops[-1])

        # Check that member of the tag has a route to the top

        pathdag = Dag()
        every_op = []
        for i in range(0,len(dag.peaks)):
            every_op.append(dag[i])
            pathdag.add(every_op[-1])

        for op in every_op:
            path = pathdag.path(op,every_op[-1])
