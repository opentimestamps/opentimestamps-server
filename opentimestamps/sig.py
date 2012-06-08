# Signatures
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

from opentimestamps.dag import HashVertex

class SignedVertex(HashVertex):
    # The earliest time the signer knows that the vertex existed
    timestamp = None

    def __init__(self):
        # don't use directly
        assert False

    def verify(self):
        return false

class GPGSignedVertex(SignedVertex):
    self.gpg_fingerprint = None
    self.gpg_signature = None

    def __init__(self,left):
        self.left = left

        self.right = Hash(left,"magic signature")
        self.lock()

    def verify(self):
        if self.right.digest == Hash(self.left,"magic signature").digest:
            return True
        else:
            return False

if __name__ == "__main__":
    import doctest
    doctest.testmod()
