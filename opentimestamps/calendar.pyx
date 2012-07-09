# Calendar-specific functionality 
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

import time
from math import log
from random import random

from opentimestamps.dag import * 

cdef class Calendar:
    """Maintain a calendar.
    """

    # Seconds
    cdef public float round_interval

    cdef public list chain

    def __init__(self,round_interval=1.0):
        self.round_interval = float(round_interval)
        self.chain = [Digest('')]

    def update(self,digest_head):
        """Update the calendar.

        Returns the number of seconds before update() should be called again.
        """

        # Linear for now
        self.chain.append(DagVertex(self.chain[-1],digest_head)) 
