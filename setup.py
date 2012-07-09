#!/usr/bin/python
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

import sys, os, getopt
from distutils.core import setup
from distutils.extension import Extension
from Cython.Distutils import build_ext

if sys.version_info[:2] < (2,7):
    print "Sorry, OpenTimestamps requires version 2.7 or later of python"
    sys.exit(1)

ext_modules = [
    Extension("opentimestamps.dag", 
         ["opentimestamps/dag.pyx",]),
    Extension("opentimestamps.calendar", 
         ["opentimestamps/calendar.pyx",]),
    ]

setup(
    name="opentimestamps",
    version='0.1',
    cmdclass = {"build_ext": build_ext},
    ext_modules = ext_modules,
    description="Distributed timestamping",
    author="Peter Todd",
    author_email="pete@petertodd.org",
    url="https://github.com/retep/opentimestamps",
    )
