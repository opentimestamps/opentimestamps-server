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

import errno
import fnmatch
import json
import logging
import os
import re
import struct
import urllib
import uuid

from opentimestamps._internal import BinaryHeader

from opentimestamps.dag import Op,Digest,Hash,Verify,OpMetadata
from opentimestamps.serialization import json_serialize,json_deserialize

class _MountainPeaksStore(BinaryHeader):
    header_magic_uuid = uuid.UUID('0060b50a-1b3b-11e2-9733-6f3bd8706b74')
    header_magic_text = b'OpenTimestamps  MountainPeaksStore'

    major_version = 1
    minor_version = 0

    header_struct_format = '16s 16p'
    header_field_names = ('peaks_uuid_bytes','hash_algorithm')

    header_length = 128

    def __init__(self,filename,peaks_uuid=None,hash_algorithm=None,create=False):
        if create:
            # Only create a peaks store if the file doesn't already exist.
            #
            # Sure we could do this without race conditions with
            # os.open(O_CREAT), but that's not as portable and our attacker is
            # the user's fat fingers...
            try:
                open(filename,'r').close()
                raise Exception('Can not create; file %s already exists' % filename)
            except IOError:
                with open(filename,'wb') as fd:
                    self._fd = fd
                    if peaks_uuid is None:
                        peaks_uuid = uuid.uuid4() # Random bytes method
                    self.peaks_uuid_bytes = peaks_uuid.bytes
                    self.hash_algorithm = bytes(hash_algorithm,'utf8')
                    self._write_header(self._fd)


        self._fd = open(filename,'rb+')
        self._read_header(self._fd)
        self.peaks_uuid = uuid.UUID(bytes=self.peaks_uuid_bytes)

        # FIXME: multi-algo support
        assert self.hash_algorithm == b'sha256'
        self.width = 32

        if peaks_uuid is not None and self.peaks_uuid != peaks_uuid:
            raise Exception(
                    'Expected to find UUID %s in MerkleMountainRangeDag peaks store, but got %s' %
                    (peaks_uuid,self.peaks_uuid))

    def __del__(self):
        try:
            self._fd.close()
        except:
            pass

    def __getitem__(self,idx):
        if idx < 0:
            idx = len(self) + idx

        if idx >= len(self) or idx < 0:
            raise IndexError('peaks index out of range; got %d; range 0 to %d inclusive'%(idx,len(self)-1))

        self._fd.seek(self.header_length + (idx * self.width))
        return self._fd.read(self.width)


    def __len__(self):
        self._fd.seek(0,2)
        # FIXME: check that rounding works when junk bytes have been added
        return (self._fd.tell() - self.header_length) // self.width

    def append(self,digest,sync=False):
        if not isinstance(digest,bytes):
            raise TypeError('digest must be bytes, not %s' % type(digest))
        if len(digest) != self.width:
            raise ValueError('digest must be an exact multiple of the peaks store width.')

        self._fd.seek(0,2)
        self._fd.write(digest)

        if sync:
            self._fd.flush()
            os.sync(self._fd.fileno())


class MerkleMountainRangeSignatureStore:
    """Persistent signature storage that works well with MerkleMountainRangeDag

    Indexes the signatures first by their notary spec, and second by the peaks
    length to which they were applied.
    """

    # FIXME: how should we handle multiple signatures at the same height?

    def __init__(self,datadir,metadata_url,create=False):
        self.datadir = datadir
        self.metadata_url = metadata_url

    def _quote(self,nspec):
        """Quote notary specs so they can be used as filenames

        Forward and back slash replaced with % equivs. % also replaced.
        """
        return nspec.replace('%','%25').replace('/','%2F').replace('\\','%5C')

    def _unquote(self,nspec):
        return urllib.parse.unquote(nspec)

    def _open_signature_file(self,mode,*,op=None,notary_spec=None,peaks_len=None):
        """Open a signature file

        op       - Operation where the notary and peaks_len will be extracted from
        notary   - Specify notary explicitly
        peaks_len - Specify peaks_len explicitly
        """
        if not notary_spec:
            notary_spec = op.signature.notary

        if not peaks_len:
            peaks_len = op.metadata[self.metadata_url]._peaks_len

        return open(self.datadir + '/' + self._quote(str(notary_spec)) + '/' + str(peaks_len).zfill(6) + '.json',mode)


    def add(self,verify_op):
        """Add a verification operation to the store"""
        try:
            os.mkdir(self.datadir + '/' + str(verify_op.signature.notary))
        except OSError as err:
            if err.errno != errno.EEXIST:
                raise err

        with self._open_signature_file('w',op=verify_op) as fd:
            fd.write(json.dumps(json_serialize(verify_op),indent=4))

    def find(self,notary_spec,min_peaks_len,limit=25):
        """Find signatures after min_peaks_len matching a notary specification

        notary   - notary spec to limit search to
        peaks_len - minimum peaks_len
        limit    - max number to return

        Returns a list of matching signatures
        """
        r = []

        matching_notaries = [self._unquote(n) for n in os.listdir(self.datadir)]

        # Valid notary searches are either *:* foo:* or finally foo:bar
        if re.match('^\*:\*$',notary_spec) or \
           re.match('^_*[a-z][a-z0-9\-\.\+]+:\*$',notary_spec):
               matching_notaries = fnmatch.filter(matching_notaries,notary_spec)
        else:
            matching_notaries = [notary_spec]

        for notary_match in matching_notaries:
            if len(r) >= limit:
                break

            # Find the earliest signature
            notary_dir = self.datadir + '/' + self._quote(notary_match)

            sig_files = []
            try:
                sig_files = sorted(os.listdir(notary_dir))
            except OSError as err:
                if err.errno != errno.ENOENT:
                    raise err

            peaks_len = None
            for sig_file in sig_files:
                peaks_len = int(sig_file[:-5]) # strip off the .json
                if peaks_len >= min_peaks_len:
                    with self._open_signature_file('r',notary_spec=notary_match,peaks_len=peaks_len) as fd:
                        r.append(json_deserialize(json.load(fd)))
                        break
        return r



class MerkleMountainRangeDag(object):
    """Dag for storing merkle mountain ranges 

    See docs/merkle_mountain_range.md
    """
    def __init__(self,
            datadir,
            hash_algorithm='sha256',
            metadata_url='',
            metadata_constructor=OpMetadata,
            dag_uuid=None,
            create=False):

        if create:
            if dag_uuid is None:
                dag_uuid = uuid.uuid4()
            self.uuid = dag_uuid
            self.peaks_filename = datadir + '/peaks.dat'
            self.peaks = _MountainPeaksStore(
                            self.peaks_filename,
                            hash_algorithm=hash_algorithm,
                            peaks_uuid=self.uuid,
                            create=True)

        # FIXME: how are we going to handle metadata that really should be in
        # ascii form? should have datadir + '/options' or something

        self.peaks_filename = datadir + '/peaks.dat'
        self.peaks = _MountainPeaksStore(
                        self.peaks_filename,
                        hash_algorithm=hash_algorithm,
                        create=False)

        self.metadata_url = metadata_url
        self.metadata_constructor = metadata_constructor

        def Hash_constructor(*args,**kwargs):
            return Hash(*args,algorithm=hash_algorithm,**kwargs)
        self._Hash = Hash_constructor


    # Height means at that index the digest represents 2**h digests. Thus
    # height for submitted is 0

    @staticmethod
    def get_mountain_peak_indexes(peaks_len):
        """Return the indexes of the peaks of the mountains, lowest to highest, for a peaks array of a given length.

        The lowest mountain will the the first element, the highest the last.
        """

        # Basically, start at the last index, and walk backwards, skipping over
        # how many elemenets would be in a tree of the height that the index
        # position has.
        r = []
        idx = peaks_len - 1
        while idx >= 0:
            r.append(idx)
            idx -= 2**(MerkleMountainRangeDag.height_at_idx(idx)+1)-1
        return r


    def _build_merkle_tree(self,parents,_accumulator=None):
        """Build a merkle tree, deterministicly

        parents - iterable of all the parents you want in the tree.

        Returns an iterable of all the intermediate digests created, and the
        final child, which will be at the end. If parents has exactly one item
        in it, that parent is the merkle tree child.
        """

        # This is a copy of opentimestamps.dag.build_merkle_tree, included here
        # because unlike that function this one has to happen deterministicly,
        # and we don't want changes there to impact what we're doing here.

        accumulator = _accumulator
        if accumulator is None:
            accumulator = []
            parents = iter(parents)

        next_level_starting_idx = len(accumulator)

        while True:
            try:
                p1 = next(parents)
            except StopIteration:
                # Even number of items, possibly zero.
                if len(accumulator) == 0 and _accumulator is None:
                    # We must have been called with nothing at all.
                    raise ValueError("No parent digests given to build a merkle tree from""")
                elif next_level_starting_idx < len(accumulator):
                    return self._build_merkle_tree(iter(accumulator[next_level_starting_idx:]),
                                                   _accumulator=accumulator)
                else:
                    return accumulator

            try:
                p2 = next(parents)
            except StopIteration:
                # We must have an odd number of elements at this level, or there
                # was only one parent.
                if len(accumulator) == 0 and _accumulator is None:
                    # Called with exactly one parent
                    return (p1,)
                elif next_level_starting_idx < len(accumulator):
                    accumulator.append(p1)
                    # Note how for an odd number of items we reverse the list. This
                    # switches the odd item out each time. If we didn't do this the
                    # odd item out on the first level would effectively rise to the
                    # top, and have an abnormally short path. This also makes the
                    # overall average path length slightly shorter by distributing
                    # unfairness.
                    return self._build_merkle_tree(iter(reversed(accumulator[next_level_starting_idx:])),
                                                   _accumulator=accumulator)
                else:
                    return accumulator

            h = self._Hash(inputs=(p1,p2))
            accumulator.append(h)


    def get_bagged_peaks(self,peaks_len=None):
        if not peaks_len:
            peaks_len = len(self.peaks)
        peaks = MerkleMountainRangeDag.get_mountain_peak_indexes(peaks_len)

        peaks = [self[peak] for peak in peaks]

        merkle_peak_ops = self._build_merkle_tree(peaks)

        metadata = self.metadata_constructor()
        metadata._peaks_len = peaks_len
        merkle_peak_ops[-1].metadata[self.metadata_url] = metadata

        return merkle_peak_ops


    @staticmethod
    def height_at_idx(idx):
        """Find the height of the mountain at a given peaks index"""

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

    @staticmethod
    def peak_child(idx):
        """Return the index of the child for a peak"""
        # Two possibilities, either we're next to the peak
        idx_height = MerkleMountainRangeDag.height_at_idx(idx)
        if idx_height+1 == MerkleMountainRangeDag.height_at_idx(idx+1):
            return idx+1
        else:
            # Or the peak is way off to the right
            return idx + 2**(idx_height+1)

    def __len__(self):
        return len(self.peaks)

    def __getitem__(self,idx):
        if isinstance(idx,int):
            h = self.height_at_idx(idx)
            if h == 0:
                return Digest(digest=self.peaks[idx])
            else:
                return self._Hash(inputs=(
                                          self.peaks[idx-1],
                                          self.peaks[idx-2**self.height_at_idx(idx)]))
        elif isinstance(idx,Op):
            # FIXME: Not terribly useful. Similarly could add support for when
            # the op has _peaks_len metadata.
            try:
                metadata = idx.metadata[self.metadata_url]
            except KeyError:
                raise IndexError("Can't find digest; no index metadata")
            else:
                return self.__getitem__(metadata._idx)
        else:
            raise IndexError("Can only index by peaks index or Op; got %r" % idx.__class__)


    def add(self,new_digest_op):
        """Add a digest"""
        assert self.height_at_idx(len(self.peaks))==0

        self.peaks.append(new_digest_op.digest)

        metadata = self.metadata_constructor()
        metadata._idx = len(self.peaks) - 1
        new_digest_op.metadata[self.metadata_url] = metadata

        # Build up the mountains
        while self.height_at_idx(len(self.peaks)) != 0:
            # Index of the hash that will be added
            idx = len(self.peaks)
            h = self._Hash(inputs=(self.peaks[idx-1],
                                   self.peaks[idx-2**self.height_at_idx(idx)]))

            self.peaks.append(h.digest)

        return new_digest_op


    def path(self,digest_op,verify_op):
        """Return the path from a digest_op to a verify_op

        The digest op must be a part of this dag.
        """
        r = []
        try:
            op_idx = digest_op.metadata[self.metadata_url]._idx
        except KeyError:
            return None
        except AttributeError:
            return None

        try:
            peaks_len = verify_op.metadata[self.metadata_url]._peaks_len
        except KeyError:
            return None
        except AttributeError:
            return None

        # Get the set of all peaks this verification was made over
        target_peaks = set(self.get_mountain_peak_indexes(peaks_len))

        # From the digest_op's index, climb the mountain until we intersect one
        # of the target peaks
        path = []
        while op_idx not in target_peaks:
            op_idx = self.peak_child(op_idx)
            path.append(self[op_idx])

        # Extend that path with the merkle tree of those peaks.
        path.extend(self.get_merkle_peak(peaks_len))

        # FIXME: we probably should prune that path; not all those ops are required.

        return path
