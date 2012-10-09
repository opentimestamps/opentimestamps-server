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

import time

from opentimestamps.dag import *

class CalendarError(StandardError):
    pass


class Calendar(object):
    """Link and timestamp collections of digests

    The calendar takes submitted digests and links them together with hash
    operations to create master digests to then be timestamped by notaries.
    """

    def submit(self,digests):
        """Submit one or more digests to the calendar.

        digests must be Op-subclass instances.

        Returns a list of Op's
        """
        raise NotImplementedError

    def path(self,sources,dests):
        """Find a path between sources and dests

        """
        raise NotImplementedError

class LinearCalendar(Calendar):
    """Hashes digests into a linear chain

    The most simple calendar possible.
    """

    def __init__(self,algorithm='sha256',dag=None):
        self.algorithm = algorithm
        self.dag = dag

        self.most_recent_digest = self.dag.add(Digest(digest=''))

    def submit(self,digests):
        r = []
        for digest in digests:
            if digest in self.dag:
                r.append(self.dag[digest])
            else:
                h = self.dag.add(Hash(inputs=(self.most_recent_digest,digest)))
                r.append(h)
                self.most_recent_digest = h
        return r

    def path(self,sources,dests):
        """Find a path between sources and dests

        """
        raise NotImplementedError



class MultiNotaryCalendar(Calendar):
    """Efficiently sign digests with multiple notaries

    See doc/design.md
    """

    all_submitted_ops = None
    known_notaries = None
    dag = None

    class __NotaryEntry:
        def __init__(self,**kwargs):
            self.last_digest_signed_idx = 0
            self.pending_signatures = {}
            self.__dict__.update(kwargs)

    class __PendingSignature:
        def __init__(self,**kwargs):
            self.created = time.time()
            self.__dict__.update(kwargs)

    def __init__(self,hash_algorithm='sha256',dag=None):
        assert(dag is not None)
        self.dag = dag
        self.hash_algorithm = hash_algorithm
        self.all_submitted_ops = []
        self.known_notaries = {}

        # start with at least one digest
        self.all_submitted_ops.append(Digest('Hello World!'))

    def get_merkle_child(self,notary):
        if not notary.canonicalized():
            raise CalendarError("get_merkle_child() expects a notary specification in canonical form")

        digests_to_sign = None

        try:
            notary_entry = self.known_notaries[notary]
        except KeyError:
            notary_entry = self.__NotaryEntry()
            self.known_notaries[notary] = notary_entry

        start_idx = notary_entry.last_digest_signed_idx
        end_idx = len(self.all_submitted_ops)

        digests_to_sign = self.all_submitted_ops[start_idx:end_idx]

        tree = build_merkle_tree(digests_to_sign,algorithm=self.hash_algorithm)

        merkle_child = tree[-1]

        notary_entry.pending_signatures[merkle_child.digest] = \
                self.__PendingSignature(last_digest_signed_idx=end_idx,
                                        tree=tree)

        return merkle_child


    def add_verification(self,verify_op):
        """Adds a Verify operation"""
        digest = verify_op.inputs[0]
        signature = verify_op.signature
        try:
            notary_entry = self.known_notaries[signature.notary]
        except KeyError:
            raise CalendarError("Notary unknown to us")

        try:
            pending_signature = notary_entry.pending_signatures[digest]
        except KeyError:
            raise CalendarError("Pending signature not found; notary probably has not called get_merkle_child() yet")

        self.dag.update(pending_signature.tree)
        self.dag.add(verify_op)

        notary_entry.last_digest_signed_idx = pending_signature.last_digest_signed_idx

        notary_entry.pending_signatures.pop(digest)

        # The verification itself needs to become part of the digests verified.
        # But rather than just do that, also include the input for that
        # verification, so that in the future it can be by-passed if it turns
        # out to be useless.
        self.submit(verify_op)
        self.submit(verify_op.inputs[0])


    def submit(self,op):
        self.all_submitted_ops.append(op)
        return ()
