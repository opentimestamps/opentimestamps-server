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
    magic_uuid = uuid.UUID('4662fc5c-0d26-11e2-97e4-6f3bd8706b74')
    magic_str = unicode(magic_uuid)
    magic_bytes = unicode(magic_uuid)

    version = "0.1"
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

    def create_json_serialized_timestamp(self):
        header = [self.magic_str,
                  self.ascii_name_and_version,
                  self.algorithms]

        digests = []

        return header + digests

    def create_binary_serialized_timestamp(self):
        header = [self.magic_bytes,
                  self.version_major,self.version_minor,
                  self.algorithms]

        digests = []

        return header + digests
