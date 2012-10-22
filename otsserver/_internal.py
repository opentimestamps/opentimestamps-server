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

import binascii
import contextlib
import ctypes
import errno
import fcntl
import os
import struct
import sys

from opentimestamps._internal import BinaryHeader

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



class AppendOnlyArchiveError(Exception):
    pass

class AppendOnlyArchiveCorruptionError(AppendOnlyArchiveError):
    """A record has become corrupt"""
    pass

class AppendOnlyArchiveRecordTooLongError(AppendOnlyArchiveError):
    """A record is too long

    Note that a too long record is only checked on add(), __getitem__()
    raises a CorruptionError instead.
    """
    pass


class AppendOnlyArchive(BinaryHeader):
    """Append-only data storage

    Records of any length can be added and retrieved, but not deleted. Locking
    is used to enable multiple simultaneous readers and writers.
    """

    def __init__(self,filename,crc32_seed,create=False,max_record_length=2**20):
        """Open or create an AppendOnlyArchive"""
        self.__crc32_seed = crc32_seed
        self.__max_record_length = max_record_length
        self.__filename = filename

        if create:
            if os.path.exists(self.__filename):
                raise IOError("Can't create archive: {} already exists".format(self.__filename))
            with open(self.__filename,'wb+') as fd:
                self._write_header(fd)

        with open(self.__filename,'rb') as fd:
            self._read_header(fd)


    def __escape_bytes(self,data):
        return data.replace(self.__record_delimiter,
                            self.__record_delimiter + b'\x00')

    def __unescape_bytes(self,data):
        return data.replace(self.__record_delimiter + b'\x00',
                            self.__record_delimiter)

    __record_delimiter = b'\xff\x9c\x2a\x77'
    class _RecordHeader(ctypes.BigEndianStructure):
        _pack_ = 1
        _fields_ = [('delimiter_pad',ctypes.c_char),
                    ('crc32',ctypes.c_uint32),
                    ('offset',ctypes.c_uint64),
                    ('length',ctypes.c_uint64)]

        delimiter_pad = b'\xff'

        def _calc_crc32(self,data):
            oldcrc32 = self.crc32
            self.crc32 = 0
            try:
                r = binascii.crc32(bytearray(self))
            finally:
                self.crc32 = oldcrc32
            r = binascii.crc32(data,r)
            return r

        def check_crc32(self,data):
            calcuated_crc32 = self._calc_crc32(data)
            return calcuated_crc32 == self.crc32

        def set_crc32(self,data):
            self.crc32 = self._calc_crc32(data)

        def __init__(self,offset,data):
            super().__init__()
            self.offset = offset
            self.length = len(data)
            self.set_crc32(data)



    # for unit testing
    __add_pre_lock_hook = lambda self:None
    __add_post_lock_hook = lambda self:None
    def add(self,data):
        """Add a record to the archive

        data must be bytes.

        Returns an integer offset which can be used to retrieve the data in the
        future. The data will be fsynced to disk before return.
        """
        if not isinstance(data,bytes):
            raise TypeError('data must be bytes; got {!s}'.format(data.__class__.__name__))
        if len(data) > self.__max_record_length:
            raise AppendOnlyArchiveRecordTooLongError(\
                    'Record too long; got {} but maximum allowed is {}'\
                            .format(len(data),self.__max_record_length))

        with open(self.__filename,'ab') as fd:
            # Lock the *end* of the signatures file for writing. This will prevent
            # others from appending to it, while still allowing the rest to be read
            # from.
            self.__add_pre_lock_hook()
            with exclusive_lockf(fd,0,0,os.SEEK_CUR):
                self.__add_post_lock_hook()

                # Note writes to the file by other processes between the
                # opening of the file and us attempting to lock the file do
                # *not* update what f.tell() think's is our position, even
                # though the file, opened in append-only mode, still
                # (correctly) writes bytes to the end of the file.
                fd.seek(0,os.SEEK_END)

                data = self.__escape_bytes(data)
                record_header = self._RecordHeader(fd.tell(),data)

                fd.write(self.__record_delimiter)
                fd.write(memoryview(record_header))
                fd.write(data)

                fd.flush()
                os.fsync(fd.fileno())

                return record_header.offset


    # for unit testing
    __getitem_pre_lock_hook = lambda self:None
    __getitem_post_lock_hdr_hook = lambda self:None
    __getitem_post_lock_data_hook = lambda self:None
    def __fd_getitem(self,fd,offset):
        # Lock the delimiter and header first as we don't yet know how long
        # the record is.
        self.__getitem_pre_lock_hook()
        fd.seek(offset,os.SEEK_SET)
        with shared_lockf(fd,len(self.__record_delimiter) + ctypes.sizeof(self._RecordHeader),0,os.SEEK_CUR):

            self.__getitem_post_lock_hdr_hook()

            # Check for the expected delimiter
            delim_bytes = fd.read(len(self.__record_delimiter))
            if not delim_bytes == self.__record_delimiter:
                raise AppendOnlyArchiveCorruptionError(\
                        'Corrupt record at offset {} from archive {}: '\
                        'delimiter not found'\
                            .format(offset,self.__filename))

            # Get the header
            record_header = self._RecordHeader.from_buffer_copy(fd.read(ctypes.sizeof(self._RecordHeader)))
            if record_header.length > self.__max_record_length:
                raise AppendOnlyArchiveCorruptionError(\
                        'Corrupt record at offset {} from archive {}: '\
                        'got length {}, expected no more than {}'\
                            .format(offset,self.__filename,
                                    record_header.length,self.__max_record_length))

            elif record_header.offset != offset:
                raise AppendOnlyArchiveCorruptionError(\
                        'Corrupt record at offset {} from archive {}: '\
                        'recorded offset, {}, does not match expected'\
                        .format(offset,self.__filename,record_header.offset))

            # Now that the data length is known we can lock the data as
            # well. Two part is ok since the archive is purely append only,
            # so the header can't change.
            with shared_lockf(fd,record_header.length,0,os.SEEK_CUR):
                self.__getitem_post_lock_data_hook()

                data = fd.read(record_header.length)
                if not record_header.check_crc32(data):
                    raise AppendOnlyArchiveCorruptionError(\
                            'Corrupt record at offset {} from archive {}: crc32 failed'\
                            .format(offset,self.__filename))
                    raise AppendOnlyArchiveChecksumError()

                return self.__unescape_bytes(data)


    def __getitem__(self,offset):
        """Get a record

        offset - An offset returned by add()

        Returns (digest,signature)
        """
        with open(self.__filename,'rb') as fd:
            return self.__fd_getitem(fd,offset)


    def iter_records(self,starting_offset=None):
        """Iterate the records in the archive

        Intended for use when you do *not* know what offset some (or all) of
        the records are at.

        starting_offset - Offset to being the iteration at.
        """
        raise NotImplemented()
