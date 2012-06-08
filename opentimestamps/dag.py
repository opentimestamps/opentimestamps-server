# The hash DAG
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

import Crypto.Hash.SHA256 as sha256

class Hash(object):
    """Create a Hash with a given digest.

    >>> Hash('\\x00'*32)
    Hash('\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00')
    >>> str(Hash('\\x00'*32))
    '0000000000000000000000000000000000000000000000000000000000000000'
    >>> Hash('\\x00'*32).digest
    '\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00'

    Hashes are compared as their digests as numbers.
    >>> Hash('\\x00'*32) == Hash('\\x00'*32)
    True
    >>> Hash('\\xff'*32) == Hash('\\x00'*32)
    False
    >>> Hash('\\xff'*32) > Hash('\\x00'*32)
    True
    >>> Hash('\\xff'*32) < Hash('\\x00'*32)
    False

    You can hash a hash! This returns the hash of the digest.
    >>> hash(Hash('\\x00'*32)) == hash(Hash('\\x00'*32))
    True
    """
    algorithm = 'sha256'
    digest = None

    def __cmp__(self,other):
        return cmp(self.digest,other.digest)

    def __hash__(self):
        return hash(self.digest)

    def __init__(self,digest):
        assert isinstance(digest,str)
        assert len(digest) == 256/8
        self.digest = digest

    @staticmethod
    def _calc_digest_from_data(*datas):
        h = sha256.new()
        for data in datas:
            if data is not None:
                if isinstance(data,Hash):
                    assert data.digest is not None
                    data = data.digest
                h.update(data)
        return h.digest()

    @classmethod
    def from_data(cls,*datas):
        """Create a Hash from existing data.

        >>> Hash.from_data('')
        Hash("\\xe3\\xb0\\xc4B\\x98\\xfc\\x1c\\x14\\x9a\\xfb\\xf4\\xc8\\x99o\\xb9$'\\xaeA\\xe4d\\x9b\\x93L\\xa4\\x95\\x99\\x1bxR\\xb8U")
        >>> Hash.from_data('Hello World!')
        Hash('\\x7f\\x83\\xb1e\\x7f\\xf1\\xfcS\\xb9-\\xc1\\x81H\\xa1\\xd6]\\xfc-K\\x1f\\xa3\\xd6w(J\\xdd\\xd2\\x00\\x12m\\x90i')
        >>> Hash.from_data('Hello',' ','World!')
        Hash('\\x7f\\x83\\xb1e\\x7f\\xf1\\xfcS\\xb9-\\xc1\\x81H\\xa1\\xd6]\\xfc-K\\x1f\\xa3\\xd6w(J\\xdd\\xd2\\x00\\x12m\\x90i')
        """
        return Hash(Hash._calc_digest_from_data(*datas))

    def __str__(self):
        return self.digest.encode("hex")

    def __repr__(self):
        return 'Hash(%s)'% repr(self.digest)

class HashVertex(Hash):
    """Basic component of the DAG

    The hash digest of a vertex is the hash of the concatination of the left
    and right parent digests.
    >>> str(HashVertex(Hash('A'*32),Hash('A'*32)))
    'd53eda7a637c99cc7fb566d96e9fa109bf15c478410a3f5eb4d4c4e26cd081f6'
    """
    left = None
    right = None

    def _lock(self):
        assert(self.digest is None)
        Hash.__init__(self,
                Hash._calc_digest_from_data(self.left,self.right))

    def __init__(self,left,right):
        self.left = left
        self.right = right
        self._lock()

def create_optimal_tree(hashes):
    """Creates an optimal tree linking every hash in hashes.

    Returns a tuple of new hashes created.

    An single hash is already optimal, so return nothing.
    >>> create_optimal_tree([Hash('A'*32)])
    ()

    >>> create_optimal_tree([Hash('A'*32),Hash('B'*32)])
    (Hash('\\x9e-\\x1fh\\xa3\\xf9\\x80Y\\xc3\\xc8\\xe6\\xf7}\\xe8c\\xbe\\x7fXe\\xc0\\xf5\\xf3\\x04\\xd7\\x85\\xc3E\\x83;G\\xf2I'),)

    Odd number of items, A+B are hashed, then H(A+B)+C are hashed.
    >>> create_optimal_tree([Hash('A'*32),Hash('B'*32),Hash('C'*32)])
    (Hash('\\x9e-\\x1fh\\xa3\\xf9\\x80Y\\xc3\\xc8\\xe6\\xf7}\\xe8c\\xbe\\x7fXe\\xc0\\xf5\\xf3\\x04\\xd7\\x85\\xc3E\\x83;G\\xf2I'), Hash('\\x1f\\xf42p\\xe80\\xbc|\\t\\xa5\\x10\\xbbdD!\\xcd\\n\\xcb\\xadd\\x95\\xa6\\xe63\\xb2\\xfc\\x0e\\x01\\xbdk\\x95\\x05'))
    """
    assert len(hashes) > 0
    if len(hashes) == 1:
        return ()


    i = iter(hashes)
    r = []
    left = None
    try:
        while True:
            left = None
            left = i.next()
            right = i.next()

            r.append(HashVertex(left,right))

    except StopIteration:
        if left is not None:
            # For an odd number of items we need to include the last item in
            # the list given to the next create_optimal_tree() call, however we
            # do not want that odd item included in the list we return.
            s = []
            s.extend(r)
            s.append(left)
            r.extend(create_optimal_tree(s))
            return tuple(r)

    # Normal logic for an even number of items.
    r.extend(create_optimal_tree(r))
    return tuple(r)

if __name__ == "__main__":
    import doctest
    doctest.testmod()
