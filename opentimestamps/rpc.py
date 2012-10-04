# RPC interface
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

from opentimestamps.dag import *
from opentimestamps.serialization import *

class RpcInterface(object):
    sourcecode_url = u'https://github.com/petertodd/opentimestamps'
    our_url = u'http://localhost:15175'

    def __init__(self,dag=None):
        if dag is None:
            self.dag = MemoryDag()

    def get_version(self):
        return u'0.1'

    def get_sourcecode_url(self):
        return self.sourcecode_url 

    def submit_digest(self,new_digest):
        new_digest = json_deserialize(new_digest)

        new_digest = Digest(digest=new_digest,dag=self.dag)
        external_verifier = Verify(inputs=(new_digest,),
                notary_method = u"ots-server",
                notary_identity = self.our_url)

        return json_serialize([new_digest,external_verifier])

    def find_paths_to_digests(self,
            start_digests,end_digests):
        return []

    def find_paths_to_verifications(self,
            starting_digests,
            notary_specifications):
        return []
