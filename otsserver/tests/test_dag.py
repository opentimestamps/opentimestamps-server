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
from opentimestamps.serialization import *

from ..dag import *

class TestPersistentDag(unittest.TestCase):
    def test_link_inputs_outputs(self):
        dag = PersistentDag()

        self.assertEqual(dag.digests,{})

        # Basic insertion
        d1 = Digest(digest=b'd1',dag=dag)
        self.assertEqual(dag.digests[b'd1'],d1)

        h_not_in_dag = Hash(inputs=(d1,))
        self.assertEqual(dag.digests[b'd1'],d1)

        # does not change d1 dependencies
        self.assertEqual(len(d1.dependent_ops),0)

        # inserted a digest identical to h1
        d2 = Digest(digest=h_not_in_dag.digest,dag=dag)
        self.assertEqual(dag.digests[d2.digest],d2)

        # recreate as a more interesting object
        h_in_dag = Hash(inputs=(d1,),dag=dag)
        self.assertEqual(dag.digests[d2.digest],h_in_dag)

        # d1 now marks h_in_dag as a dependency
        self.assertIn(h_in_dag,d1.dependent_ops)

        h2 = Hash(inputs=(h_in_dag,d1),dag=dag)
        self.assertIn(h2,d1.dependent_ops)
        self.assertIn(h2,h_in_dag.dependent_ops)
