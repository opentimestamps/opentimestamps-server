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

import struct
from binascii import hexlify,unhexlify
import Crypto.Hash.SHA256

import pygraphviz


cdef enum digest_algorithm:
    NULL_HASH = 0
    SHA256 = 1
    RIPEMD160 = 2

digest_algorithm_name = {NULL_HASH:'null',
                         SHA256:'sha256',
                         RIPEMD160:'ripemd160'}

ctypedef unsigned long long order_t

cpdef _hash_data(bytes data,digest_algorithm algorithm = SHA256):
    """Low-level method to hash data using a given algorithm.
    
    >>> hexlify(_hash_data(''))
    'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
    >>> hexlify(_hash_data('Hello World!'))
    '7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069'
    """
    assert(algorithm == SHA256)
    h = Crypto.Hash.SHA256.new()
    h.update(data)
    return h.digest()

cpdef _Digest_from_data(bytes data,digest_algorithm algorithm = SHA256):
    """Low level method to create a Digest object from some data
    
    >>> _Digest_from_data('')
    Digest('sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
    >>> _Digest_from_data('Hello World!')
    Digest('sha256:7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069')
    """
    return Digest(_hash_data(data,algorithm=algorithm),algorithm=algorithm)

def Digest_from_data(cls,data,algorithm = SHA256):
    return cls(_hash_data(data,algorithm=algorithm),algorithm=algorithm)

cdef class Digest:
    """The digest produced by applying a hash function to data.

    Everything in a dag is a subclass of Digest, because everything has a
    digest value.
   
    For convenience you can create a null digest easily:
    >>> a = Digest(''); a
    Digest('')

    The algorithm for a null digest is null:
    >>> a.algorithm
    0

    You can create a Digest with a given digest value:
    >>> a = Digest('\\x00'*32); a
    Digest('sha256:0000000000000000000000000000000000000000000000000000000000000000')

    This time the algorithm is sha256:
    >>> a.algorithm
    1

    Specify the digest with the algorithm type and hex:
    >>> Digest('sha256:0000000000000000000000000000000000000000000000000000000000000000')
    Digest('sha256:0000000000000000000000000000000000000000000000000000000000000000')

    Digests can be compared:
    >>> a = Digest('\\x00'*32); b = Digest('\\xff'*32); c = Digest('\\x00'*32);
    >>> a == a
    True
    >>> a == b
    False
    >>> a != b
    True
    >>> a == c
    True

    Ordering also works, as though the digests themselves were compared as
    strings: (the algorithm is not part of the comparison)
    >>> a < b
    True
    >>> a > b
    False
    >>> a < a
    False
    >>> a <= a
    True
    >>> Digest('') < a
    True
    >>> Digest('') > a
    False

    Classmethod to create a Digest from some data.
    >>> Digest.from_data('Hello World!')
    Digest('sha256:7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069')
    """

    cdef readonly bytes digest
    cdef readonly digest_algorithm algorithm

    from_data = classmethod(Digest_from_data)

    def __init__(self,bytes digest,digest_algorithm algorithm = SHA256):
        if len(digest) == 0:
            algorithm = NULL_HASH
        elif digest[0:7] == 'sha256:' and len(digest) == 7 + 256/4:
            digest = unhexlify(digest[7:]) 
        elif len(digest) != 256/8:
            raise TypeError("Digest is wrong length for SHA256. (expected %d bytes, got %d byte(s))" % (256/8,len(digest)))

        # Leave some of the digest length space free for the binary format.
        assert(len(digest) <= 128)

        self.digest = digest
        self.algorithm = algorithm

    def __hash__(self):
        return hash(self.digest)

    def __richcmp__(self,other,op):
        if not isinstance(other,Digest):
            # Comparisons of dissimilar types in Python is bloody
            # complicated... so fuck it.
            return NotImplemented

        if op == 0: # <
            return self.digest < other.digest
        elif op == 1: # <=
            return self.digest <= other.digest
        elif op == 2: # ==
            return self.digest == other.digest
        elif op == 3: # !=
            return self.digest != other.digest
        elif op == 4: # >
            return self.digest > other.digest
        elif op == 5: # >=
            return self.digest >= other.digest
        else:
            assert(0)

    def abbv_str(self,context=6):
        """Abbreviated string representation.

        >>> Digest('\\xff'*32).abbv_str()
        'ffffff'
        """
        s = hexlify(self.digest)
        if len(s) > context:
            return s[0:context]
        else:
            return s

    def __str__(self):
        return hexlify(self.digest)

    def __repr__(self):
        if self.algorithm == NULL_HASH:
            return "Digest('')"
        else:
            return "Digest('%s:%s')" % \
                    (digest_algorithm_name[self.algorithm],hexlify(self.digest))

    cpdef calculate_digest(self):
        return _hash_data(self.get_digest_data(),self.algorithm)

    cpdef get_digest_data(self):
        raise NotImplementedError('Raw Digest objects do not have data.')

cdef class DagVertex(Digest):
    """The basic component of the DAG.

    >>> a = DagVertex(Digest(''),Digest('')); a
    DagVertex('3e2be1': '','',0)

    >>> b = DagVertex(a,a); b
    DagVertex('b249a4': '3e2be1','3e2be1',1)

    >>> a.children
    set([DagVertex('b249a4': '3e2be1','3e2be1',1)])
    """

    cdef readonly unsigned long long order
    cdef readonly Digest left
    cdef readonly Digest right

    cdef readonly set children

    cpdef get_digest_data(self):
        """Return the data used to compute the digest.

        >>> hexlify(DagVertex(Digest('\\xaa'*32),Digest('\\xbb'*32),order=1).get_digest_data())
        '0000000000000001012020aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaabbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
        """
        return struct.pack('>QBBB',
                    self.order, \
                    self.algorithm, \
                    len(self.left.digest), \
                    len(self.right.digest)) + \
                 self.left.digest + \
                 self.right.digest

    def __repr__(self):
        return 'DagVertex(%r: %r,%r,%d)' % (self.abbv_str(),
                                            self.left.abbv_str(),
                                            self.right.abbv_str(),
                                            self.order)

    def __init__(self,Digest left,Digest right,order_t order = 0,digest_algorithm algorithm = SHA256):
        self.left = left
        self.right = right
        self.children = set() 

        self.order = order
        if isinstance(self.left,DagVertex):
            self.order = max(self.order,self.left.order + 1)
            self.left.children.add(self)
        if isinstance(self.right,DagVertex):
            self.order = max(self.order,self.right.order + 1)
            self.right.children.add(self)

        self.algorithm = algorithm
        self.digest = self.calculate_digest()

    cpdef _all_parents(self,set s,long max_depth):
        if max_depth == 0:
            return s
        elif max_depth < 0:
            max_depth = 0

        if self.left not in s:
            s.add(self.left)
            if isinstance(self.left,DagVertex):
                self.left._all_parents(s,max_depth-1)

        if self.right not in s:
            s.add(self.right)
            if isinstance(self.right,DagVertex):
                self.right._all_parents(s,max_depth-1)

    def all_parents(self,max_depth=-1):
        """Returns the set of every parent (recursively) of this vertex.

        The set includes Digests
        >>> DagVertex(Digest(''),Digest('')).all_parents()
        set([Digest('')])

        >>> a = DagVertex(Digest(''),Digest(''),order=1)
        >>> b = DagVertex(Digest(''),Digest(''),order=2)
        >>> c = DagVertex(a,b); sorted(c.all_parents())
        [Digest(''), DagVertex('5aefda': '','',1), DagVertex('5febd0': '','',2)]
        >>> sorted(c.all_parents(max_depth=1))
        [DagVertex('5aefda': '','',1), DagVertex('5febd0': '','',2)]
        >>> sorted(c.all_parents(max_depth=0))
        []
        """
        s = set()
        self._all_parents(s,max_depth)
        return s

    cpdef _all_children(self,set s,long max_depth):
        if max_depth == 0:
            return s
        elif max_depth < 0:
            max_depth = 0

        for child in self.children:
            if child not in s:
                s.add(child)
                child._all_children(s,max_depth - 1)
    
    def all_children(self,max_depth=-1):
        """Returns the set of all children (recursively) of this vertex.

        Same logic as all_parents()

        >>> a = DagVertex(Digest(''),Digest(''),order=1)
        >>> b = DagVertex(Digest(''),Digest(''),order=2)
        >>> c = DagVertex(a,b); d = DagVertex(c,Digest(''))
        >>> sorted(d.all_children())
        []
        >>> sorted(a.all_children())
        [DagVertex('24d127': '5aefda','5febd0',3), DagVertex('612812': '24d127','',4)]
        >>> sorted(b.all_children(max_depth=1))
        [DagVertex('24d127': '5aefda','5febd0',3)]
        """
        s = set()
        self._all_children(s,max_depth)
        return s

def create_optimal_tree(digests):
    """Creates an optimal tree linking every digest in digests.

    Returns the top of the new tree. 


    An single digest is already optimal, so return just that digest.
    >>> create_optimal_tree([Digest('B'*32)])
    Digest('sha256:4242424242424242424242424242424242424242424242424242424242424242')

    >>> create_optimal_tree([Digest('A'*32),Digest('B'*32)])
    DagVertex('923b8e': '414141','424242',0)

    Odd number of items, A+B are hashed, then H(A+B)+C are hashed.
    >>> create_optimal_tree([Digest('A'*32),Digest('B'*32),Digest('C'*32)])
    DagVertex('9d982f': '923b8e','434343',1)
    """
    assert len(digests) > 0

    while len(digests) > 1:
        new_digests = []

        # Combine pairs of digests into vertices
        i = iter(digests)
        while True:
            left = right = None
            try:
                left = i.next()
                right = i.next()
            except StopIteration:
                if left is not None:
                    new_digests.append(left)
                assert(right is None)
                break
            else:
                new_digests.append(DagVertex(left,right))
        digests = new_digests

    return digests[0]


def dagvertexes_to_dot(vertexes,str_func=None):
    """"Produce a graph in dot format of set of DagVertexes
    
    Useful for debugging.

    >>> a = DagVertex(Digest(''),Digest(''),order=1); 
    >>> b = DagVertex(Digest(''),Digest(''),order=2); 
    >>> c = DagVertex(a,b);
    >>> print dagvertexes_to_dot((a,b,c)) # doctest: +SKIP
    strict graph {
        "5aefda" -- "24d127";
        "5febd0" -- "24d127";
    }
    <BLANKLINE>
    """
    if str_func is None:
        def s(x):
            o = ''
            if isinstance(x,DagVertex):
                o = ':' + str(x.order)
            return hexlify(x.digest)[0:6] + o
        str_func = s 
    graph = pygraphviz.AGraph() 

    for vertex in vertexes:
        if str_func(vertex):
            graph.add_node(str_func(vertex))

    for vertex in vertexes:
        if isinstance(vertex,DagVertex):
            if str_func(vertex.left):
                graph.add_edge(str_func(vertex.left),str_func(vertex))
            if str_func(vertex.right):
                graph.add_edge(str_func(vertex.right),str_func(vertex))

    return graph

