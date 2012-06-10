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
        return '%s:%s' % (self.algorithm,self.digest.encode("hex"))

    def __repr__(self):
        return "Hash(h='%s')" % str(self)

def _lockable_property(name,doc):
    underlying_name = '_' + name
    def getx(self):
        return getattr(self,underlying_name)
    def setx(self,value):
        if self.digest is None:
            setattr(self,underlying_name,value)
        else:
            if not isinstance(value,Hash) or value.digest != getattr(self,underlying_name).digest:
                raise TypeError("Changing property '%s' to '%r' would change the hash digest of %r" % (name,value,self))
            setattr(self,underlying_name,value)

    return property(getx,setx,None,doc)

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

    left = _lockable_property('left',None)
    right = _lockable_property('right',None)

    serialized_name = 'DagVertex'
    serialized_attributes = {'left':recursive_attr,
                             'right':recursive_attr}
    digest_serialized_attributes = ('left','right')

    def lock(self):
        """Lock the vertex, and calculate its digest.

        Example:
        >>> h1 = Hash.from_data('a')
        >>> h2 = Hash.from_data('b')
        >>> a = DagVertex(None,None)
        >>> a.digest is None
        True
        >>> a.left = h1; a.right = h2
        >>> a.lock()
        >>> a.left = None
        Traceback (most recent call last):
        TypeError: Changing property 'left' to 'None' would change the hash digest of Hash(h='sha256:e5a01fee14e0ed5c48714f22180f25ad8365b53f9779f79dc4a3d7e93963f94a')
        """
        assert(self.digest is None)
        Hash.__init__(self,
                Hash._calc_digest_from_data(self.left,self.right))

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
