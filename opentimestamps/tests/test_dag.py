# vim: set fileencoding=utf8
# dag unit tests
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

# Goal: we need to be able to extend JSON with type information, while at the
# same time being able to deterministicly create a binary serialization of the
# information going into the JSON.

# name.type.subtype : value with type being optional if default json
# interpretation is correct, subtype useful for lists. Lists with multiple
# types in them aren't supported.

import unittest
import StringIO
import json

from ..dag import *
from ..serialization import *

def make_json_round_trip_tester(self):
    def r(value,expected_representation=None,new_value=None):
        # serialize to json-compat representation
        actual_representation = json_serialize(value)
        if expected_representation is not None:
            self.assertEqual(actual_representation,expected_representation)

        # take that representation and send it through a json parser
        post_json_representation = json.loads(json.dumps(actual_representation))

        # deserialize that and check if it's what we expect
        value2 = json_deserialize(post_json_representation)
        if new_value is not None:
            value = new_value 
        self.assertEqual(value,value2)
    return r

def make_binary_round_trip_tester(self):
    def r(value,expected_representation=None,new_value=None):
        # serialize to binary representation
        actual_representation = binary_serialize(value)

        if expected_representation is not None:
            self.assertEqual(actual_representation,expected_representation)

        # deserialize that and check if it's what we expect
        value2 = binary_deserialize(actual_representation)
        if new_value is not None:
            value = new_value 
        self.assertEqual(value,value2)
    return r

class TestOp(unittest.TestCase):
    def test_equality(self):
        a1 = Digest(digest=b'')
        a2 = Digest(digest=b'')
        b = Digest(digest=b'b')

        self.assertNotEqual(a1,object())

        self.assertEqual(a1,a2)
        self.assertNotEqual(a1,b)
        self.assertNotEqual(a2,b)

class TestDigestOp(unittest.TestCase):
    def test_json_serialization(self):
        r = make_json_round_trip_tester(self)

        d = Digest(digest=b'\xff\x00')
        r(d,{'Digest': {'inputs': [], 'digest': u'#ff00'}})

    def test_binary_serialization(self):
        r = make_binary_round_trip_tester(self)
        d = Digest(digest=b'\xff\x00')
        r(d,b'\x11\x06digest\x05\x02\xff\x00\x06inputs\x07\x08\x00')

class TestHashOp(unittest.TestCase):
    def test_json_serialization(self):
        r = make_json_round_trip_tester(self)

        a = Digest(digest=b'a')
        b = Digest(digest=b'b')
        h1 = Hash(inputs=(a,b))
        r(h1,{'Hash':
                {'inputs':[u'#61', u'#62'],
                 'algorithm':u'sha256d',
                 'digest':u'#a1ff8f1856b5e24e32e3882edd4a021f48f28a8b21854b77fdef25a97601aace'}})

    def test_binary_serialization(self):
        r = make_binary_round_trip_tester(self)
        a = Digest(digest=b'a')
        b = Digest(digest=b'b')
        h1 = Hash(inputs=(a,b))
        r(h1,b'\x12\talgorithm\x04\x07sha256d\x06digest\x05 \xa1\xff\x8f\x18V\xb5\xe2N2\xe3\x88.\xddJ\x02\x1fH\xf2\x8a\x8b!\x85Kw\xfd\xef%\xa9v\x01\xaa\xce\x06inputs\x07\x05\x01a\x05\x01b\x08\x00')

class TestVerifyOp(unittest.TestCase):
    def test_json_serialization(self):
        r = make_json_round_trip_tester(self)

        a = Digest(digest=b'a')
        b = Digest(digest=b'b')
        h1 = Hash(inputs=(a,b))
        v = Verify(inputs=(h1,),notary_method=u'foo')
        r(v)

    def test_binary_serialization(self):
        r = make_binary_round_trip_tester(self)
        a = Digest(digest=b'a')
        b = Digest(digest=b'b')
        h1 = Hash(inputs=(a,b))
        v = Verify(inputs=(h1,),notary_method='foo')
        r(v)

    def test_verify_digest_equality(self):
        # Basically create two Verify ops that should have the same digest.
        a = Digest(digest=b'a')
        b = Digest(digest=b'b')
        h1 = Hash(inputs=(a,b))
        v = Verify(inputs=(h1,),notary_method='foo')

        v2 = v
        a = Digest(digest=b'a')
        b = Digest(digest=b'b')
        h1 = Hash(inputs=(a,b))
        v = Verify(inputs=(h1,),notary_method='foo',timestamp=v2.timestamp)

        self.assertEqual(v,v2)

        # and a third one that shouldn't
        a = Digest(digest=b'a')
        b = Digest(digest=b'b')
        h1 = Hash(inputs=(a,b))
        v = Verify(inputs=(h1,),notary_method='foo',timestamp=v2.timestamp-1)

        self.assertNotEqual(v,v2)

        # FIXME: better testing of this would be good

class TestMemoryDag(unittest.TestCase):
    def test_link_inputs_outputs(self):
        dag = MemoryDag()

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
