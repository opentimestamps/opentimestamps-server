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

import unittest

from opentimestamps.dag import *
from opentimestamps.notary import *

from ..calendar import *

class TestLinearCalendar(unittest.TestCase):
    def test_link_inputs_outputs(self):
        dag = Dag()
        cal = LinearCalendar(dag=dag)

        d1 = Digest('1')
        d2 = Digest('2')
        d3 = Digest('3')

        oldest_digest = cal.most_recent_digest

        h1 = cal.submit((d1,))[0]
        self.assertIn(h1,dag)
        self.assertIn(h1,dag.dependents[oldest_digest])

        h2 = cal.submit((d2,))[0]
        self.assertIn(h2,dag)
        self.assertIn(h2,dag.dependents[h1])

        h3 = cal.submit((d3,))[0]
        self.assertIn(h3,dag)
        self.assertIn(h3,dag.dependents[h2])



class TestMultiNotaryCalendar(unittest.TestCase):
    def test_signing(self):
        cal = MultiNotaryCalendar(dag=Dag())

        notary1 = TestNotary(identity='pass-1')
        notary2 = TestNotary(identity='pass-2')
        notary3 = TestNotary(identity='pass-3')

        digests = []
        def add_digests(n,accumulator=[0]):
            for i in range(0,n):
                accumulator[0] += 1
                h = Hash(inputs=(bytes(str(accumulator[0])),))
                digests.append(h)
                cal.submit(h)

        def check_for_path(source,dest):
            alleged_path = cal.dag.path(source,dest)

            # Check if another dag thinks the path is ok
            dag2 = Dag(alleged_path)
            path2 = dag2.path(source,dest)
            self.assertTrue(path2 is not None)

        def sign_and_check_all_paths(notary,stamp_time=[0]):
            stamp_time[0] += 1

            merkle_child = cal.get_merkle_child(notary)
            sig = notary.sign(merkle_child,stamp_time[0])
            verify_op = Verify(inputs=(merkle_child,),signature=sig)
            cal.add_verification(verify_op)

            # There should be a path from every single digest in the dag to our
            # new verification.
            for d in cal.dag:
                check_for_path(d,verify_op)

        add_digests(10)
        sign_and_check_all_paths(notary1)
        sign_and_check_all_paths(notary1)
        add_digests(9)
        sign_and_check_all_paths(notary2)
        sign_and_check_all_paths(notary2)
        add_digests(10)
        sign_and_check_all_paths(notary3)
        add_digests(11)
        sign_and_check_all_paths(notary1)
