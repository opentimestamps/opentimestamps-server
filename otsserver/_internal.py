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

"""Internal use only"""

import contextlib
import errno
import fcntl
import os
import sys

class FileAlreadyLockedError(Exception):
    pass

@contextlib.contextmanager
def lockf_manager(fd,operation,*args,block=True):
    """fcntl.lockf wrapped in a context manager

    Remember that file locking is per-process; attempting to lock the same file
    multiple times in a single process will succeed.

    fd - file-like with fileno() method
    block - If true, will block. Otherwise will raise FileAlreadyLockedError

    operation should not be LOCK_UN
    """
    assert operation is not fcntl.LOCK_UN
    try:
        if not block:
            operation |= fcntl.LOCK_NB
        fcntl.lockf(fd.fileno(),operation,*args)
    except IOError as err:
        # Need to check both for portability apparently.
        if err.errno == errno.EACCES or err.errno == errno.EAGAIN:
            raise FileAlreadyLockedError()
        else:
            raise err
    yield
    fcntl.lockf(fd.fileno(),fcntl.LOCK_UN,*args)

@contextlib.contextmanager
def shared_lockf(fd,*args,block=True):
    with lockf_manager(fd,fcntl.LOCK_SH,*args,block=block):
        yield

@contextlib.contextmanager
def exclusive_lockf(fd,*args,block=True):
    with lockf_manager(fd,fcntl.LOCK_EX,*args,block=block):
        yield
