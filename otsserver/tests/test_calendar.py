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

from ..calendar import *

class TestLinearCalendar(unittest.TestCase):
    def test_link_inputs_outputs(self):
        dag = MemoryDag()
        cal = LinearCalendar(dag=dag)

        d1 = Digest('1')
        d2 = Digest('2')
        d3 = Digest('3')

        oldest_digest = cal.most_recent_digest

        h1 = cal.submit((d1,))[0]
        self.assertIn(h1,dag)
        self.assertIn(h1,oldest_digest.dependents)

        h2 = cal.submit((d2,))[0]
        self.assertIn(h2,dag)
        self.assertIn(h2,h1.dependents)

        h3 = cal.submit((d3,))[0]
        self.assertIn(h3,dag)
        self.assertIn(h3,h2.dependents)
