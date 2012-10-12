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

import uuid
import struct
import os

from opentimestamps._internal import BinaryHeader

from opentimestamps.dag import *
from opentimestamps.serialization import *

class _MerkleTipsStore(BinaryHeader):
    header_magic_uuid = uuid.UUID('00c5f8f8-1355-11e2-afce-6f3bd8706b74')
    header_magic_text = 'OpenTimestamps  MerkleTipsStore'

    major_version = 0
    minor_version = 0

    header_struct_format = '16s 16p'
    header_field_names = ('tips_uuid_bytes','algorithm')

    header_length = 128

    def __init__(self,filename,tips_uuid=None,algorithm=None,create=False):
        if create:
            # Only create a tips store if the file doesn't already exist.
            #
            # Sure we could do this without race conditions with
            # os.open(O_CREAT), but that's not as portable and our attacker is
            # the user's fat fingers...
            try:
                open(filename,'r')
                raise StandardError('Can not create; file %s already exists' % filename)
            except IOError:
                with open(filename,'wb') as fd:
                    self._fd = fd
                    if tips_uuid is None:
                        tips_uuid = uuid.uuid4() # Random bytes method
                    self.tips_uuid_bytes = tips_uuid.bytes
                    self.algorithm = algorithm
                    self._write_header(self._fd)


        self._fd = open(filename,'rb+')
        self._read_header(self._fd)
        self.tips_uuid = uuid.UUID(bytes=self.tips_uuid_bytes)

        # FIXME: multi-algo support
        assert self.algorithm == 'sha256'
        self.width = 32

        if tips_uuid is not None and self.tips_uuid != tips_uuid:
            raise StandardError(
                    'Expected to find UUID %s in MerkleDag tips store, but got %s' %
                    (tips_uuid,self.tips_uuid))

    def __del__(self):
        try:
            self._fd.close()
        except:
            pass

    def __getitem__(self,idx):
        if idx < 0:
            idx = len(self) + idx

        if idx >= len(self) or idx < 0:
            raise IndexError('tips index out of range %d %d'%(idx,len(self)))

        self._fd.seek(self.header_length + (idx * self.width))
        return self._fd.read(self.width)


    def __len__(self):
        self._fd.seek(0,2)
        return (self._fd.tell() - self.header_length) / self.width

    def append(self,digest,sync=False):
        if not (isinstance(digest,bytes) or isinstance(digest,buffer)):
            raise TypeError('digest must be either bytes or buffer, not %s' % type(digest))
        if len(digest) != self.width:
            raise ValueError('digest must be an exact multiple of the tips store width.')

        self._fd.seek(0,2)
        self._fd.write(digest)

        if sync:
            self._fd.flush()
            os.sync(self._fd.fileno())


class MerkleDag(object):
    """Dag for building merkle trees

    Essentially we keep multiple trees stored with the standard linear
    breadth-first method, with the largest tree starting at index 0. This array
    is called 'tips', and has the interesting property that any member of that
    array is the tip of a tree, although usually not a very tall tree.

    Every time a digest is added to the end of the tips we see if that digest
    allows us to create a larger tree. Lets define the height of the tree, h,
    as representing a tree with 2^h total roots. Thus as we add digests, the
    heights of the array grows as follows:

    0
    00
    001 <- indexed 0 and 1 are hashed to form index 3
    0010
    0010012 <- another tree, which lead to the two subtrees being merged (height 2)
    00100120
    0010012001 <- now we have two trees, one of height 2, one of height 1

    Now when we sign the tree, we just take the tips of every subtree, hash
    them together in a merkle tree, and sign that. That hash can be
    deterministicly calculated just by knowing the length of the tips array
    when the signature was created. Similarly because every signature is
    applied to every digest submitted before the signature was created, if the
    client knows the index of their digest, searching for signatures just
    becomes a fast binary search in a per-method list of signatures, sorted by
    tips length. Fast!

    This is also good for efficiently mirroring calendars from one server to
    another. Lets suppose you know the set of top tips for the calendar you'd
    like to mirror, and want to know if you can get that calendar from another
    server. Simply ask the server for the highest tip, if they have it, great!
    Ask them for the next tallest tip and so forth. Now lets say they don't
    have one of the tips you want. Ask them for the the older parent of the tip
    they don't have. If they have it, great! Otherwise, ask them for the next
    older parent. Essentially each unsuccessful request splits the search space
    in half - binary search for merkle forests.

    If the server's calendar is now divergent compared to yours you'll still
    get the part before the divergency happened.

    Merging divergent calendars together again is possible as well. Essentially
    the divergent tips needed to be added back with a rule ordering the adds by
    height and digest value; highest sub-trees first, then lowest valued
    digests first. Getting tips for recreating the trees signatures were signed
    over is then a matter of keeping sorted lists of subtrees by height, so you
    can efficiently grab the tips required. Kinda complex; this can be
    implemented later. The important thing is that searches are still fairly
    efficient, because we can still efficiently store what signatures were
    applied to what digests based on the largest tip of a tree that they were
    applied too.
    """
    def __init__(self,datadir,algorithm='sha256',create=False):
        if create:
            self.uuid = uuid.uuid4()
            self.tips_filename = datadir + '/tips.dat'
            self.tips = _MerkleTipsStore(
                            self.tips_filename,
                            algorithm=algorithm,
                            tips_uuid=self.uuid,
                            create=True)

        # FIXME: how are we going to handle metadata that really should be in
        # ascii form? should have datadir + '/options' or something

        self.tips_filename = datadir + '/tips.dat'
        self.tips = _MerkleTipsStore(
                        self.tips_filename,
                        algorithm=algorithm,
                        create=False)


    # Height means at that index the digest represents 2**h digests. Thus
    # height for submitted is 0

    def get_subtree_tips(self):
        """Return the tips of the subtrees, smallest to largest"""

        # Like height_at_idx basically biggest possible tip downwards
        r = []
        idx = 0
        while True:
            for h in reversed(range(0,64)):
                if idx + 2**h <= len(self.tips):
                    idx += 2**h
                    break
            if idx >= len(self.tips):
                break
            r.append(self.tips[idx-1])
        return tuple(reversed(r))

    @staticmethod
    def height_at_idx(idx):
        """Find the height of the subtree at a given tips index"""

        # Basically convert idx to the count of items left in the tree. Then
        # take away successively smaller trees, from the largest possible to
        # the smallest, and keep track of what height the last tree taken away
        # was. Height being defined as the tree with 2**(h+1)-1 *total* digests.
        last_h = None
        count = idx + 1
        while count > 0:
            for h in reversed(range(0,64)):
                assert h >= 0
                if 2**(h+1)-1 <= count:
                    last_h = h
                    count -= 2**(h+1)-1
                    break
        return last_h

    def __getitem__(self,idx):
        h = self.height_at_idx(idx)
        if h == 0:
            return Digest(digest=self.tips[idx])
        else:
            return Hash(inputs=(
                            self.tips[idx-1],
                            self.tips[idx-2**self.height_at_idx(idx)]))

    def add(self,new_digest_op):
        """Add a digest"""
        assert self.height_at_idx(len(self.tips))==0

        self.tips.append(new_digest_op.digest)

        # Build up the trees
        while self.height_at_idx(len(self.tips)) != 0:
            # Index of the hash that will be added
            idx = len(self.tips)
            h = Hash(inputs=(
                        self.tips[idx-1],
                        self.tips[idx-2**self.height_at_idx(idx)]),
                     hints_idx=idx)
            self.tips.append(h.digest)
