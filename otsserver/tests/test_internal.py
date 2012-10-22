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

import os
import signal
import sys
import tempfile
import time
import unittest
import uuid

from .._internal import \
    FileAlreadyLockedError,\
    lockf_manager,shared_lockf,exclusive_lockf,\
    AppendOnlyArchiveError,AppendOnlyArchiveCorruptionError,AppendOnlyArchiveRecordTooLongError,\
    AppendOnlyArchive


class test_lockf_manager(unittest.TestCase):
    def setUp(self):
        self.file = tempfile.NamedTemporaryFile(prefix='tmp_lockf_manager')
        self.file.write(b'a' * 10000)

    def tearDown(self):
        # deletes on close
        self.file.close()

    def test_exclusive_locking(self):
        pid = os.fork()
        with open(self.file.name,'ab') as f:
            if pid:
                # Wait until child has locked the file
                signal.signal(signal.SIGUSR1,lambda signum,frame:None)
                signal.pause()

            # whole lock
            with self.assertRaises(FileAlreadyLockedError):
                with exclusive_lockf(f,block=False):
                    if not pid:
                        # Tell parent we've locked the fail
                        os.kill(os.getppid(),signal.SIGUSR1)

                        # Wait until parent has tried locking the file
                        signal.signal(signal.SIGUSR2,lambda signum,frame:None)
                        signal.pause()
                        os._exit(0)

            # Tell child we're done
            os.kill(pid,signal.SIGUSR2)

    def test_shared_locking(self):
        pid = os.fork()
        if pid:
            with open(self.file.name,'wb') as f:
                # Wait until child has locked the file
                signal.signal(signal.SIGUSR1,lambda signum,frame:None)
                signal.pause()

                # Exclusive lock should fail
                with self.assertRaises(FileAlreadyLockedError):
                    with exclusive_lockf(f,block=False):
                        pass

                # Tell child we're done
                os.kill(pid,signal.SIGUSR2)

                # exclusive lock should now work
                with exclusive_lockf(f,block=True):
                    pass
        else:
            # Create another child who will also get a shared lock
            pid2 = os.fork()
            with open(self.file.name,'rb') as f:
                with shared_lockf(f,block=False):
                    if not pid2:
                        signal.signal(signal.SIGUSR1,lambda signum,frame:None)
                        signal.pause()

                        # Tell parent we've locked the fail
                        os.kill(os.getppid(),signal.SIGUSR1)
                    else:
                        os.kill(os.getppid(),signal.SIGUSR1)

                    # Wait until parent has tried locking the file
                    signal.signal(signal.SIGUSR2,lambda signum,frame:None)
                    signal.pause()
                    if pid2:
                        os.kill(pid2,signal.SIGUSR2)

                    time.sleep(0.1)
                    os._exit(0)

class SpamArchive(AppendOnlyArchive):
    header_magic_uuid = uuid.uuid4()
    header_magic_text = b'SpamArchive'
    major_version = 1
    minor_version = 0
    header_struct_format = 'L'
    header_field_names = ('nigerians',)
    header_length = 128

    def __init__(self,filename,nigerians=0,**kwargs):
        self.nigerians = nigerians
        super().__init__(filename,b'eggs',**kwargs)


class Test_AppendOnlyArchive(unittest.TestCase):
    def setUp(self):
        self.tmpfilename = tempfile.mktemp()

    def tearDown(self):
        os.unlink(self.tmpfilename)

    def test_noclobber(self):
        spamarc = SpamArchive(self.tmpfilename,create=True)
        with self.assertRaises(IOError):
            spamarc = SpamArchive(self.tmpfilename,create=True)

    def test_basics(self):
        spamarc = SpamArchive(self.tmpfilename,create=True,nigerians=42)

        spams = (b'career singles',b'get results now',b'meet someone special',b'fire your boss')
        idxs = [spamarc.add(spam) for spam in spams]

        for (spam,idx) in zip(spams,idxs):
            self.assertEqual(spamarc[idx],spam)

        spamarc = SpamArchive(self.tmpfilename,create=False)
        self.assertEqual(spamarc.nigerians,42)
        for (spam,idx) in zip(spams,idxs):
            self.assertEqual(spamarc[idx],spam)

    def test_locking(self):
        # FIXME
        spamarc = SpamArchive(self.tmpfilename,create=True)

    def test_corruption_handling(self):
        spamarc = SpamArchive(self.tmpfilename,create=True)

        spams = (b'you have won',b'amazing new discovery',b'doctor approved',b'privacy assured',b'venture capital')
        idxs = [spamarc.add(spam) for spam in spams]

        with open(self.tmpfilename,'rb+') as cfd:
            # corrupt delimiter
            cfd.seek(idxs[0],os.SEEK_SET)
            cfd.write(b'\xFF'*4)
            cfd.flush()

            with self.assertRaises(AppendOnlyArchiveCorruptionError):
                spamarc[idxs[0]]

            # corrupt crc32
            cfd.seek(idxs[1]+4+1,os.SEEK_SET)
            cfd.write(b'\xFF')
            cfd.flush()
            with self.assertRaises(AppendOnlyArchiveCorruptionError):
                spamarc[idxs[1]]

            # corrupt offset
            cfd.seek(idxs[2]+4+1+4,os.SEEK_SET)
            cfd.write(b'\xFF')
            cfd.flush()
            with self.assertRaises(AppendOnlyArchiveCorruptionError):
                spamarc[idxs[2]]

            # corrupt length
            cfd.seek(idxs[3]+4+1+4+8,os.SEEK_SET)
            cfd.write(b'\xFF')
            cfd.flush()
            with self.assertRaises(AppendOnlyArchiveCorruptionError):
                spamarc[idxs[3]]

            # corrupt data
            cfd.seek(idxs[4]+4+1+4+8+8,os.SEEK_SET)
            cfd.write(b'\xFF')
            cfd.flush()
            with self.assertRaises(AppendOnlyArchiveCorruptionError):
                spamarc[idxs[4]]
