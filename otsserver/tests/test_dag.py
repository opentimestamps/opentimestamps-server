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

from ..dag import _MerkleTipsStore
from ..dag import *

class Test_MerkleTipsStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='tmpTipsStore')

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test(self):
        # TipsStore creation
        filename = self.temp_dir + '/tips.dat'

        tips = _MerkleTipsStore(filename,algorithm='sha256',create=True)

        # Shouldn't be able to create twice
        with self.assertRaises(Exception):
            _MerkleTipsStore(filename,algorithm='sha256',create=True)

        self.assertEqual(len(tips),0)

        # Shouldn't be able to index yet
        with self.assertRaises(IndexError):
            tips[0]
        with self.assertRaises(IndexError):
            tips[1]
        with self.assertRaises(IndexError):
            tips[-1]

        # Get how long the tips file is.
        #
        # Tips always seeks first, so this is safe.
        tips._fd.seek(0,2)
        old_fd_tell = tips._fd.tell()

        # can't add wrong width digest
        with self.assertRaises(ValueError):
            tips.append(b'')
        with self.assertRaises(ValueError):
            tips.append(b'a')
        with self.assertRaises(ValueError):
            tips.append(b'a'*(tips.width+1))

        # Both of these have lengths, but are of the wrong type.
        with self.assertRaises(TypeError):
            tips.append(tuple(range(0,tips.width)))
        with self.assertRaises(TypeError):
            tips.append((1,2,3))

        with self.assertRaises(TypeError):
            tips.append('*'*tips.width)

        # None of the above should have modified the file
        tips._fd.seek(0,2)
        self.assertEqual(old_fd_tell,tips._fd.tell())

        def h(i):
            return bytes(str(i).rjust(tips.width),'utf8')

        # add stuff
        n = 100
        for i in range(0,n):
            tips.append(h(i))
            self.assertEqual(len(tips),i+1)

        # verify before and after re-opening
        for j in (1,2):
            for i in range(0,n):
                self.assertEqual(h(i),tips[i])
                self.assertEqual(h(n-i-1),tips[-i-1])

            tips = _MerkleTipsStore(filename)

        # re-open with different UUID fails
        with self.assertRaises(Exception):
            _MerkleTipsStore(filename,tips_uuid=uuid.uuid4())


class TestMerkleDag(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='tmpMerkleDag')

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_height_at_idx(self):
        self.assertSequenceEqual(
                (0,0,1,0,0,1,2,0,0,1,0,0,1,2,3,0,0,1,0,0,1,2,0,0,1,0,0,1,2,3,4),
                [MerkleDag.height_at_idx(i) for i in range(0,31)])


    def test(self):
        dag = MerkleDag(self.temp_dir,create=True)
        dag = MerkleDag(self.temp_dir)

        digest_ops = []
        n = 2**8
        for i in range(0,n):
            digest_ops.append(Hash(inputs=(bytes(str(i),'utf8'),)))
            dag.add(digest_ops[-1])

        # Check that member of the tag has a route to the top

        pathdag = Dag()
        every_op = []
        for i in range(0,len(dag.tips)):
            every_op.append(dag[i])
            pathdag.add(every_op[-1])

        for op in every_op:
            path = pathdag.path(op,every_op[-1])
