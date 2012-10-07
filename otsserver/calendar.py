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

from opentimestamps.dag import *

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
