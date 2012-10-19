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

from .._internal import FileAlreadyLockedError,lockf_manager,shared_lockf,exclusive_lockf

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

