# Serialization
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

import binascii
import struct
import json
from collections import OrderedDict

serialized_classes = {}

def register_serialized_class(cls):
    """Decorator for Serializable subclasses.

    Adds the class to the master Serializable classes list so
    json_deserialize() can work.
    """
    serialized_classes[cls.serialized_name] = cls
    return cls

class SerializationHandler(object):
    def encode(self,value):
        return value
    def decode(self,value):
        return value
default_serialization_handler = SerializationHandler()

class RecursiveSerializationHandler(SerializationHandler):
    """Handler for attributes whose values are Serializable instances."""
    def encode(self,value):
        return value.json_serialize_to_dict()
    def decode(self,json_dict):
        return json_deserialize_from_dict(json_dict)
recursive_attr = RecursiveSerializationHandler()

class StrSerializationHandler(SerializationHandler):
    """Handler that forces non-unicode strings."""
    def encode(self,value):
        return value
    def decode(self,value):
        return value
str_attribute = StrSerializationHandler()

class HexSerializationHandler(SerializationHandler):
    """Encode binary data as hex."""
    def encode(self,value):
        return binascii.hexlify(value)
    def decode(self,value):
        return binascii.unhexlify(value)
hex_attribute = HexSerializationHandler()

class DigestSerializationHandler(object):
    def __init__(self,encoder=None):
        def encode(value):
            if isinstance(value,Serializable):
                value = value.digest_serialize()
            elif isinstance(value,str):
                pass
            else:
                raise Exception("Type %s not supported as a digest serialized value." % \
                    type(value))
            return value
        if encoder is None:
            encoder = encode
        self.encode = encoder

    def decode(self,value):
        raise Exception("You can't decode with a digest serialization handler.")
default_digest_serialization_handler = DigestSerializationHandler()

@register_serialized_class
class Serializable(object):
    """Serialization class.

    There are two important use-cases for serialization: the REST interface and
    digests. For the REST interface we use standard JSON serialization and
    deserialization, albeit with our own custom class instantiation system.
    Hash digests however require that the serialization be exactly the same
    every time, and in addition to that, the data in the hash digest is a
    subset of the data used by the JSON serialization. So this class supports
    both methods. Notably deserialization of the binary format is *not*
    supported.

    Note that deserialization of data from untrusted sources must be safe!



    The binary format is delibrately kept extremely simple:

    First a disambiguation header:

    (class) 0x00

    Followed by pairs of attribute name, attribute value:

    (key) 0x00 (big-endian uint32 len(value)) value

    Where value can either be a str, or a Serializable instance. (which
    is automatically serialized) Note that the names are sorted, with the
    sorted names of the base class first, then the sorted names of the next
    class and so on.


    As an exception, a subclass can overload digest_serialize() if another
    format makes more sense. Currently Hash() does this so the serialization of
    a hash is the hash digest itself.
    """

    # The name of the class.
    serialized_name = ''

    # Attributes that are serialized directly.
    #
    # If a dict is specified here, handlers consisting of SerializationHandler
    # instances and provide hooks for encoding and decoding. A None handler
    # does nothing.
    #
    # {'name':handler}
    serialized_attributes = ()

    # The subset of attributes that are serialized into the hash digest.
    #
    # Again, handler(s) can be specified.
    digest_serialized_attributes = ()

    def _walk_serialized_attributes(self,attr_attr,default_handler):
        # Multiple-inheritence isn't supported yet
        assert len(self.__class__.__bases__) == 1

        # Go-go recursion!
        def walk(cls):
            if issubclass(cls,Serializable):
                l = getattr(cls,attr_attr)
                if not isinstance(l,dict):
                    # Not a dict, turn into one with empty handlers
                    l2 = {}
                    for attr in l:
                        l2[attr] = None
                    l = l2
                r = walk(cls.__base__)

                # Base classes are over-ridden by derived classes.
                #
                # Also note how we always sort the attribute names
                for attr_name in sorted(l.keys()):
                    r[attr_name] = l[attr_name]
                return r
            else:
                # We're not in a Serializable class; we've probably reached the
                # base object class, so just return an empty dict to get the
                # process started.
                return OrderedDict()
        r = walk(self.__class__)

        # Give attributes default handlers if they weren't set already.
        for (attr,handler) in r.iteritems():
            if handler is None:
                r[attr] = default_handler
        return r

    def _get_all_serialized_attributes(self):
        return self._walk_serialized_attributes('serialized_attributes',default_serialization_handler)

    def _get_all_digest_serialized_attributes(self):
        return self._walk_serialized_attributes('digest_serialized_attributes',default_digest_serialization_handler)

    def json_serialize_to_dict(self):
        """Return an OrderedDict suitable for json.dump(s)"""
        d = OrderedDict()
        d['class'] = self.serialized_name

        for (attr,handler) in self._get_all_serialized_attributes().iteritems():
            value = getattr(self,attr)
            d[attr] = handler.encode(value)
        return d

    def json_serialize(self,indent=4):
        """Serialize into a json-formatted str"""
        return json.dumps(self.json_serialize_to_dict(),indent=indent)

    @classmethod
    def json_deserialize(cls,json_dict):
        r = cls.__new__(cls)
        serialized_attr_handlers = r._get_all_serialized_attributes()
        for attr,value in json_dict.iteritems():
            # JSON library usually gives us attribute names in unicode, bad!
            attr = str(attr)
            if attr == 'class':
                continue
            value = serialized_attr_handlers[attr].decode(value) 
            setattr(r,attr,value)
        return r

    def digest_serialize(self):
        r = [] 
        r.append(self.serialized_name)
        r.append('\x00')

        for (attribute,handler) in self._get_all_digest_serialized_attributes().iteritems():
            r.append(attribute)
            r.append('\x00')

            v = None
            try:
                v = getattr(self,attribute)
            except KeyError:
                raise KeyError("Attribute '%s' in digest_serialized_attributes list, yet missing in object %r" % \
                        (attribute,self))

            v = handler.encode(v)
            r.append(struct.pack('>l',len(v)))
            r.append(v)

        return ''.join(r)

    def serialize_to_hash(self):
        """Convenience function to return a Hash() created from the serialized data.

        >>> @register_serialized_class
        ... class test_serialize_to_hash(Serializable):
        ...     serialized_name = 'test_serialize_to_hash'
        ...     serialized_keys = ()
        >>> test_serialize_to_hash().serialize_to_hash()
        Hash(h='sha256:f7d3622f7d174338c975e09895be932580cab69fadb48ccc3971e9bafa9728ea')
        """
        import opentimestamps.dag
        return opentimestamps.dag.Hash.from_data(self.digest_serialize())


def json_deserialize_from_dict(json_dict):
    """Deserialize a dict, returning Serializable objects."""
    if not 'class' in json_dict.keys():
        raise ValueError("Can't deserialize: badly formed JSON string; missing 'class' property.")
    if not json_dict['class'] in serialized_classes:
        raise TypeError("Unknown serialized class '%s'" % json_dict['class'])

    return serialized_classes[json_dict['class']].json_deserialize(json_dict)

def json_deserialize(s):
    """Deserialize a string, returning Serializable objects.

    Simple example:
    >>> @register_serialized_class
    ... class test_simple_deserialize(Serializable):
    ...     serialized_name = 'test_simple_deserialize'
    ...     serialized_attributes = ('b','a')
    ...     def __init__(self):
    ...         self.a = 1
    ...         self.b = 2
    ...     def __repr__(self):
    ...         return '%s(%r)' % (self.__class__.__name__,sorted(self.__dict__.items()))
    >>> json_deserialize(test_simple_deserialize().json_serialize())
    test_simple_deserialize([('a', 1), ('b', 2)])

    More complex example, subclassed and recursive
    >>> @register_serialized_class
    ... class test_simple_deserialize2(test_simple_deserialize):
    ...     serialized_name = 'test_simple_deserialize2'
    ...     serialized_attributes = {'c':recursive_attr}
    ...     def __init__(self):
    ...         super(test_simple_deserialize2,self).__init__()
    ...         self.c = test_simple_deserialize()
    >>> json_deserialize(test_simple_deserialize2().json_serialize())
    test_simple_deserialize2([('a', 1), ('b', 2), ('c', test_simple_deserialize([('a', 1), ('b', 2)]))])
    """
    return json_deserialize_from_dict(json.loads(s))


class _TestSerializable(Serializable):
    """Test of Serializable

    >>> _TestSerializable().digest_serialize()
    '_TestSerializable\\x00a\\x00\\x00\\x00\\x00\\x01ab\\x00\\x00\\x00\\x00\\x02bbc\\x00\\x00\\x00\\x00\\x03ccc'

    >>> a = _TestSerializable(); a.a = _TestSerializable(); a.digest_serialize()
    '_TestSerializable\\x00a\\x00\\x00\\x00\\x00*_TestSerializable\\x00a\\x00\\x00\\x00\\x00\\x01ab\\x00\\x00\\x00\\x00\\x02bbc\\x00\\x00\\x00\\x00\\x03cccb\\x00\\x00\\x00\\x00\\x02bbc\\x00\\x00\\x00\\x00\\x03ccc'

    Only str and Serializable values can be serialized.
    >>> a = _TestSerializable(); a.a = None; a.digest_serialize()
    Traceback (most recent call last):
    Exception: Type <type 'NoneType'> not supported as a digest serialized value.
    """
    serialized_name = '_TestSerializable'
    serialized_attributes = ('a','c','b')
    digest_serialized_attributes = ('a','c','b')
    a = 'a'
    b = 'bb'
    c = 'ccc'

if __name__ == "__main__":
    import doctest
    doctest.testmod()
