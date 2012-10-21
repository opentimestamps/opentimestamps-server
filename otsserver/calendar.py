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

import binascii
import logging
import os
import time
import uuid

import otsserver
import opentimestamps

from opentimestamps.dag import Digest,Hash,Verify,OpMetadata
from .dag import MerkleMountainRangeDag,MerkleMountainRangeSignatureStore



class CalendarError(Exception):
    pass

class Calendar(object):
    """Manage a calendar linking digests to signatures

    The calendar is the middleware between the RPC interface and the actual
    storage of digests and signatures.
    """

    def merkle_tip(self):
        """see rpc.get_merkle_tip"""
        raise NotImplementedError

    def submit_verification(self,ops):
        """see rpc.post_verification"""
        raise NotImplementedError

    def submit(self,digest):
        """see rpc.post_digest"""
        raise NotImplementedError

    def path(self,sources,dests):
        """see rpc.get_path"""
        raise NotImplementedError

class MerkleCalendar(Calendar):
    """Calendar implemented on top of a MerkleMountainRangeDag"""

    signatures = None
    dag = None

    def __init__(self,
            server_url=None,
            hash_algorithm='sha256',
            datadir=None,
            create=False):

        assert server_url is not None
        self.server_url = server_url
        self.hash_algorithm = hash_algorithm

        assert datadir is not None
        self.datadir = datadir
        self.dagdir = datadir + '/dag'
        self.signaturesdir = datadir + '/signatures'

        self.calendar_uuid = None
        if create:
            os.mkdir(self.datadir)
            os.mkdir(self.dagdir)
            os.mkdir(self.signaturesdir)

            self.calendar_uuid = uuid.uuid4()
            with open(self.datadir + '/uuid','w') as fd:
                fd.write(str(self.calendar_uuid) + '\n')
        else:
            with open(self.datadir + '/uuid','r') as fd:
                self.calendar_uuid = (
                    uuid.UUID(fd.read().strip()))


        def metadata_constructor(**kwargs):
            return OpMetadata(uuid=self.calendar_uuid.bytes,**kwargs)
        self._metadata_constructor = metadata_constructor

        self.dag = MerkleMountainRangeDag(
                       metadata_url=self.server_url,
                       datadir=self.dagdir,
                       hash_algorithm=hash_algorithm,
                       metadata_constructor=metadata_constructor,
                       create=create)

        if not len(self.dag):
            # Always have at least one digest so signing works from the start.
            #
            # Might as well timestamp our implementation first!
            h = Hash(algorithm=hash_algorithm,
                     inputs=(bytes(otsserver.implementation_identifier,'utf8'),
                             bytes(opentimestamps.implementation_identifier,'utf8')))
            self.dag.add(h)

        self.signatures = MerkleMountainRangeSignatureStore(datadir=self.signaturesdir,metadata_url=self.server_url)


    def get_merkle_tip(self):
        return self.dag.get_merkle_tip()

    def add_verification(self,ops):
        """Adds a verification"""
        verify_op = ops[-1]
        tips_len = ops[-2].metadata[self.server_url]._tips_len
        tip_ops = self.dag.get_merkle_tip(tips_len=tips_len)

        # Make sure the verification input really is the tip we expected it to be
        if tip_ops[-1].digest == verify_op.inputs[0]:
            logging.info(\
'Received GOOD signature {} on digest {} at tips len {}'\
.format(verify_op.signature,binascii.hexlify(verify_op.inputs[0]),tips_len))

            verify_op.metadata[self.server_url] = self._metadata_constructor(_tips_len=tips_len)
            self.signatures.add(verify_op)


    def submit(self,op):
        # Don't let users submit ops directly to the calendar, hash them with
        # some garbage first. If we don't do this we're effectively letting
        # people put arbitrary junk in other clients signatures.
        junk_bytes = os.urandom(32)
        hash_op = Hash(inputs=(op,junk_bytes))
        return [self.dag.add(hash_op)]

    def path(self,digest_op,notary_spec):
        try:
            min_tips_len = digest_op.metadata[self.server_url]._idx + 1
        except KeyError:
            return []
        except AttributeError:
            return []

        r = []

        matching_verify_ops = self.signatures.find(notary_spec,min_tips_len)

        for verify_op in matching_verify_ops:
            path = self.dag.path(digest_op,verify_op)
            r.extend(path)
            r.append(verify_op)

        if r:
            return r
        else:
            return None
