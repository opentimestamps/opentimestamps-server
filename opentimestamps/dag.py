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

import binascii
import Crypto.Hash.SHA256 as sha256
from opentimestamps.serialize import *

class HashCheckException(Exception):
    """Exception for a failed Hash.check()"""
    def __init__(self,msg,path,visited):
        self.visited = visited

        # Turn the linked list path into a list
        l = []
        p = path
        while p is not None:
            l.append(p[0])
            p = p[1]
        self.path = l

        super(HashCheckException,self).__init__(msg)

@register_serialized_class
class Hash(Serializable):
    """Create a Hash with a given digest.

    The digest can be specified directly, in binary:
    >>> Hash('\\x00'*32)
    Hash(h='sha256:0000000000000000000000000000000000000000000000000000000000000000')

    Or in human readable form:
    >>> Hash(h='0000000000000000000000000000000000000000000000000000000000000000')
    Hash(h='sha256:0000000000000000000000000000000000000000000000000000000000000000')

    You can also specify the algorithm: (only sha256 supported right now)
    >>> Hash(h='sha256:0000000000000000000000000000000000000000000000000000000000000000')
    Hash(h='sha256:0000000000000000000000000000000000000000000000000000000000000000')

    str(Hash()) returns the human readable form:
    >>> str(Hash('\\x00'*32))
    'sha256:0000000000000000000000000000000000000000000000000000000000000000'

    while the .digest is the actual binary digest:
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

    serialized_name = 'Hash'
    serialized_attributes = {'algorithm':str_attribute,
                             'digest':hex_attribute}
    digest_serialized_attributes = ('algorithm','digest')

    serialize_hooks = \
            {'digest':(lambda e: e.encode('hex'),binascii.unhexlify)}

    def digest_serialize(self):
        """As a special case, for Hash() objects just return their digest
        directly."""
        if self.__class__ == Hash:
            return self.digest
        else:
            return super(Hash,self).digest_serialize()

    def _check(self,n,path,visited):
        """Actual check() implementation.

        path - Linked-list appended to at each step, so the failing Hash object
               can be found. None for first level
        visited - Set of all previously visited Hashes. (for efficiency)
        """
        visited.add(self)
        if self.digest is None:
            raise HashCheckException('Digest is None',(self,path),visited)
        elif len(self.digest) != 32:
            raise HashCheckException('Digest is invalid',(self,path),visited)

    def check(self,n=-1):
        """Preform a consistency check between the digest and the data.

        Raises HashCheckException on failure.

        n - Number of levels of recursion to follow. -1 for infinite.

        >>> h = Hash('\\x00'*32)
        >>> h.check()
        >>> h.digest = None; h.check()
        Traceback (most recent call last):
        HashCheckException: Digest is None
        """
        self._check(n,None,set())

    def __cmp__(self,other):
        return cmp(self.digest,other.digest)

    def __hash__(self):
        return hash(self.digest)

    def __init__(self,*args,**kwargs):
        digest = None
        if len(args) == 0:
            if kwargs.keys() != ['h']:
                raise TypeError('Hash() got incorrect kwargs: %r' % kwargs)

            digest = kwargs['h']

            # algorithm specified?
            if ':' in digest:
                (self.algorithm,digest) = digest.split(':')
            digest = binascii.unhexlify(digest)

        elif len(args) == 1:
            digest = args[0]
        else:
            raise TypeError('Hash() called incorrectly. (args=%r,kwargs=%r)'%(args,kwargs))

        if self.algorithm != 'sha256':
            raise Exception('Unsupported hash algorithm %s',self.algorithm)
        if not isinstance(digest,str):
            # Note that this path only applies for directly specified digests,
            # not the human readable Hash(h='algo:digest') notation.
            raise Exception('Digest must be of type str, not %s' % type(digest))
        if len(digest) != 256/8:
            raise Exception('Digest is the wrong length. (%d, should be %d)'%(len(digest),256/8))

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
        Hash(h='sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
        >>> Hash.from_data('Hello World!')
        Hash(h='sha256:7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069')
        >>> Hash.from_data('Hello',' ','World!')
        Hash(h='sha256:7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069')
        """
        return Hash(Hash._calc_digest_from_data(*datas))

    def __str__(self):
        if self.digest is not None:
            return '%s:%s' % (self.algorithm,self.digest.encode("hex"))
        else:
            return '%s:None' % self.algorithm

    def __repr__(self):
        return "Hash(h='%s')" % str(self)

class SignatureVerificationError(Exception):
    pass

@register_serialized_class
class DagVertex(Hash):
    """Basic component of the DAG

    JSON serializable:
    >>> a = DagVertex(Hash.from_data('a'),Hash.from_data('b'),locked=True)
    >>> a.json_serialize(indent=None)
    '{"class": "DagVertex", "algorithm": "sha256", "digest": "e5a01fee14e0ed5c48714f22180f25ad8365b53f9779f79dc4a3d7e93963f94a", "left": {"class": "Hash", "algorithm": "sha256", "digest": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb"}, "right": {"class": "Hash", "algorithm": "sha256", "digest": "3e23e8160039594a33894f6564e1b1348bbd7a0088d42c4acb73eeaed59c009d"}}'

    Digest serializable:
    >>> a.digest_serialize()
    'DagVertex\\x00algorithm\\x00\\x00\\x00\\x00\\x06sha256digest\\x00\\x00\\x00\\x00 \\xe5\\xa0\\x1f\\xee\\x14\\xe0\\xed\\\\HqO"\\x18\\x0f%\\xad\\x83e\\xb5?\\x97y\\xf7\\x9d\\xc4\\xa3\\xd7\\xe99c\\xf9Jleft\\x00\\x00\\x00\\x00 \\xca\\x97\\x81\\x12\\xca\\x1b\\xbd\\xca\\xfa\\xc21\\xb3\\x9a#\\xdcM\\xa7\\x86\\xef\\xf8\\x14|Nr\\xb9\\x80w\\x85\\xaf\\xeeH\\xbbright\\x00\\x00\\x00\\x00 >#\\xe8\\x16\\x009YJ3\\x89Oed\\xe1\\xb14\\x8b\\xbdz\\x00\\x88\\xd4,J\\xcbs\\xee\\xae\\xd5\\x9c\\x00\\x9d'
    """

    left = None
    right = None

    serialized_name = 'DagVertex'
    serialized_attributes = {'left':recursive_attr,
                             'right':recursive_attr}
    digest_serialized_attributes = ('left','right')

    def _compute_digest(self):
        # FIXME: Ugly, should eventually refactor this to computing a digest
        # from data directly.
        return Hash.from_data(self.left,self.right).digest

    def lock(self):
        """Lock the vertex, and calculate its digest."""
        assert(self.digest is None)
        Hash.__init__(self,self._compute_digest())

    def _check(self,n,path,visited):
        """check() implementation.

        Basics:
        >>> h = DagVertex(None,None); h.check()
        Traceback (most recent call last):
        HashCheckException: Digest is None
        >>> h.left = Hash.from_data(''); h.right = Hash.from_data(''); h.lock(); h.check() 
        >>> h.left.digest = '\\x00' * 32; h.check()
        Traceback (most recent call last):
        HashCheckException: Digest does not match: stored '2dba5dbc339e7316aea2683faf839c1b7b1ee2313db792112588118df066aa35' != computed '1c9ecec90e28d2461650418635878a5c91e49f47586ecf75f2b0cbb94e897112'

        Recursion level:
        >>> h0 = DagVertex(h,Hash.from_data(''),locked=True); h0.check()
        Traceback (most recent call last):
        HashCheckException: Digest does not match: stored '2dba5dbc339e7316aea2683faf839c1b7b1ee2313db792112588118df066aa35' != computed '1c9ecec90e28d2461650418635878a5c91e49f47586ecf75f2b0cbb94e897112'
        >>> h0.check(0)

        Path is correctly calculated:
        >>> h1 = DagVertex(h0,h0.right,locked=True);
        >>> try:
        ...     h1.check()
        ... except HashCheckException as x:
        ...     x.path
        [Hash(h='sha256:2dba5dbc339e7316aea2683faf839c1b7b1ee2313db792112588118df066aa35'), Hash(h='sha256:a59e147aa340e4a9d990cbbbe737aee694d88ae674112f4d4f6d32187c70800f'), Hash(h='sha256:587cc92e4b03b90fd8bf56e182c3ee0e548797db42ccc8ddce92ecf0a656149b')]
        """
        super(DagVertex,self)._check(n,path,visited)

        if self.digest is None:
            raise HashCheckException('Digest is None',(self,path),visited)
        elif self.left is None:
            raise HashCheckException('left side is None',(self,path),visited)
        elif self.left is None:
            raise HashCheckException('right side is None',(self,path),visited)
        elif not self.digest == self._compute_digest():
            raise HashCheckException('Digest does not match: stored %r != computed %r' % \
                    (self.digest.encode('hex'),self._compute_digest().encode('hex')),
                    (self,path),visited)
        elif n != 0:
            if self.left not in visited:
                self.left._check(n - 1,(self,path),visited)
            if self.right not in visited:
                self.right._check(n - 1,(self,path),visited)

    def _pre_serialize_hook(self):
        if self.digest is None:
            raise ValueError("Can't serialize an unlocked DagVertex")

    def __init__(self,left,right,locked=False):
        self.digest = None
        self.left = left
        self.right = right
        if locked:
            self.lock()

    def check_signature(self):
        """Check if the signature of a vertex is valid.

        Fails on an unlocked vertex, as there is no digest. This returns a
        ValueError, as it indicates a bug in your code:
        >>> DagVertex(None,None).check_signature()
        Traceback (most recent call last):
        ValueError: DagVertex.check_signature() is not valid if the vertex is unlocked.

        Of course, trying to check the signature of a regular DagVertex fails
        anyway:
        >>> DagVertex(None,None,locked=True).check_signature()
        Traceback (most recent call last):
        SignatureVerificationError: DagVertex don't have signatures
        """
        if self.digest is None:
            raise ValueError("DagVertex.check_signature() is not valid if the vertex is unlocked.")
        raise SignatureVerificationError("%s don't have signatures" % self.__class__.__name__)

def create_optimal_tree(hashes):
    """Creates an optimal tree linking every hash in hashes.

    Returns a tuple of new hashes created.

    An single hash is already optimal, so return nothing.
    >>> create_optimal_tree([Hash('A'*32)])
    ()

    >>> create_optimal_tree([Hash('A'*32),Hash('B'*32)])
    (Hash(h='sha256:9e2d1f68a3f98059c3c8e6f77de863be7f5865c0f5f304d785c345833b47f249'),)

    Odd number of items, A+B are hashed, then H(A+B)+C are hashed.
    >>> create_optimal_tree([Hash('A'*32),Hash('B'*32),Hash('C'*32)])
    (Hash(h='sha256:9e2d1f68a3f98059c3c8e6f77de863be7f5865c0f5f304d785c345833b47f249'), Hash(h='sha256:1ff43270e830bc7c09a510bb644421cd0acbad6495a6e633b2fc0e01bd6b9505'))
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

            r.append(DagVertex(left,right,locked=True))

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
