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

# FIXME: how are we going to chain signatures?

class SignatureVertex(DagVertex):
    """A vertex with a signature attached. 

    
    """

    sig_blob = bytes

    def __init__(self,left,signature_digest,timestamp):
        super(self,Signature).__init__(left,signature_digest,order=timestamp)

    def verify(self):
        """Verify that a signature is valid.

        Of course, a raw Signature is always invalid...
        """
        return False

class SignatureType(object):
    pass

class Signature(Digest):
    """The signature itself.

    """

    def __init__(self,signed_digest):
        self.signed_digest = digest 
