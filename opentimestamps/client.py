# Client related code.
#
# Copyright (C) 2012 Peter Todd <pete@petertodd.org>
#
# This file is part of OpenTimestamps.
#
# OpenTimestamps is free software; you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by the
# Free Software Foundation; either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more
# details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import uuid
import json

from .serialization import *
from .dag import *

class TimestampFile(object):
    # uuid should have bytes that are obviously not ascii, to ensure file is
    # *always* considered binary. check that file command thinks format is
    # unknown binary
    magic_uuid = uuid.UUID('4662fc5c-0d26-11e2-97e4-6f3bd8706b74')
    magic_str = unicode(magic_uuid)
    magic_bytes = unicode(magic_uuid)

    # update major if things will break, update minor if the change should be
    # backwards compat
    #
    # probably ok to update minor each type we add a new op, or even new op
    # arguments. Don't need to update for new notary types.
    version = "0.1" # lets set this to 1 when we publish version 0.1
    version_major = 0
    version_minor = 1
    ascii_name_and_version = u"OpenTimestamps JSON Timestamp v%s" % version

    algorithms = ('sha256d',)

    dag = None

    def __init__(self,in_fd=None,out_fd=None,dag=None):
        if dag is None:
            self.dag = MemoryDag()

        if in_fd is not None:
            # read from the file
            pass

    def create_binary_header(self):
        # File format:
        #
        # <UUID bytes> <uint8 major> <uint8 minor>
        # <payload>
        # <crc32 of all previous bytes>
        #
        # putting the crc32 at the end makes life easier, as we can calculate
        # it as we read the file
        #
        # Do this as a straight struct-packed header, so we're not depending on
        # the serialization format in any way what-so-ever
        #
        # v0.1 payload, serialized in the binary format:
        #
        # options - {'algorithms':[u'sha256d',], <- algorithms to apply to the data
        #            'msg_crc32':12345} <- data crc32 is calculated and compared to this
        #
        # ops - [op1,op2,etc]
        #
        # combine the above into a list:
        #
        # [options,ops]
        #
        # if we need to change the format, we can create another timestamp file
        # class and use it depending on what header version is found. Since
        # options is a dict, for the most part we shouldn't need to do this,
        # other than for compressing things further.
        #
        # Possible major version changes: zlib compression? digest compression?
        #
        # that said, lets stick with zlib, supported everywhere, almost as good
        # as we can get, other than we should eventually avoid storing the
        # itermediate computed digests at all. add this for our first verson,
        # 1.0
        #
        # re: error catching, lets define a 'digest_crc32' Op argument that
        # we use for storage, which takes the calculated digest, does a crc32,
        # and compares. This works even for digests that aren't cryptographic,
        # like Verify
        #
        # basically when the stamp is created we can decide how many crc32's we
        # want left in there
        #
        # figure out what exact crc version python's crc32 is and document, but
        # best to use something as standard as possible
        packed_version = struct.pack('%B%B',self.major_version,self.minor_version)
        return self.magic_bytes

    # FIXME: no such thing as json serialized, just json output for debugging
    #
    # change this stuff to ASCII armored and clearsigned
    def create_json_serialized_timestamp(self):
        header = [self.magic_str,
                  self.ascii_name_and_version,
                  self.crc32, # crc32 of data to be timestamped, as integer
                  self.algorithms]

        digests = []

        return header + digests

    def create_binary_serialized_timestamp(self):
        header = [self.magic_bytes,
                  self.version_major,self.version_minor,
                  self.crc32,
                  self.algorithms]

        digests = []

        return header + digests
