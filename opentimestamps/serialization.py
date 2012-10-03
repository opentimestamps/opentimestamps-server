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

# Goal: we need to be able to extend JSON with type information, while at the
# same time being able to deterministicly create a binary serialization of the
# information going into the JSON.

# name.type.subtype : value with type being optional if default json
# interpretation is correct, subtype useful for lists. Lists with multiple
# types in them aren't supported.

import unicodedata
import binascii
import types

"""
{'Hash.Op': {
    'inputs.list.bytes':['AA','BB','CC'],
    'digest.bytes':'AA',
    'hash_algorithm.str':'sha256d',
    }
}
{'Verify.Op': {
    'inputs.list.bytes':['AA','BB','CC'],
    'digest.bytes':'AA',
    'timestamp.int': 12345,
    'notary_method.str': 'bitcoin-coinbase',
    'notary_identity.str': 'mainnet',
    'bitcoin_block_height.str':12345,
    'bitcoin_merkle_sides.str':12345,
    'bitcoin_merkle_leaves.list.bytes':['AA','BB','CC']
    }
}
{'Verify.Op': {
    'inputs.list.bytes':['AA','BB','CC'],
    'digest.bytes':'AA',
    'timestamp.int': 12345,
    'notary_method.str': 'ext-lookup',
    'notary_identity.str': 'http://foo.bar.com',
    }
}
"""

# Note that opcodes all have the highest bit unset. This is so they don't look
# like variable-length integers, hopefully causing a vint parser to quit
# earlier rather than later.
#
# 0x00 to 0x1F for opcodes is a good choice as they're all unprintable.
opcodes_by_name = {'null'      :b'\x00',
                   'bool'      :b'\x01',
                   'int'       :b'\x02',
                   'uint'      :b'\x03',
                   'str'       :b'\x04',
                   'bytes'     :b'\x05',
                   'dict'      :b'\x06',
                   'list'      :b'\x07',
                   'list_end'  :b'\x08',

                   'UnknownOp' :b'\x10',
                   'Hash'      :b'\x11',
                   'Verify'    :b'\x12',}

serializations_by_class = {}
serializations_by_name = {}

def register_serializable_type(cls):
    serializations_by_name[cls.type_name] = cls

    if cls.auto_serialize_and_deserialize:
        for c in cls.applicable_classes:
            assert c not in serializations_by_class
            serializations_by_class[c] = cls

    return cls

def binary_serialize(obj,accumulator=None):
    serialization_type = serializations_by_class[obj.__class__]
    return serialization_type.binary_serialize(obj,accumulator=accumulator)

def json_serialize(obj,subtype=None):
    serialization_type = serializations_by_class[obj.__class__]
    return serialization_type.json_serialize(obj)

def json_deserialize(python_obj,obj_type):
    serialization_type = serializations_by_name[obj_type]
    return serialization_type.json_deserialize(python_obj)

class SerializableType(object):
    type_name = None
    applicable_classes = None
    auto_serialize_and_deserialize = True
    subtypes_allowed = False

    @classmethod
    def _subtypes_allowed_check(cls,subtype):
        if subtype is not None and not cls.subtypes_allowed:
            raise TypeError(\
"Subtypes not supported by %r but got subtype %r" %
                            (cls,subtype))

    @classmethod
    def _json_serialize(cls,value,subtype=None):
        return value

    @classmethod
    def json_serialize(cls,value,subtype=None):
        cls._subtypes_allowed_check(subtype)
        return cls._json_serialize(value,subtype)

    @classmethod
    def json_deserialize(cls,python_value,subtype=None):
        cls._subtypes_allowed_check(subtype)
        return cls._json_deserialize(python_value,subtype)

    @classmethod
    def _json_deserialize(cls,python_value,subtype=None):
        cls._subtypes_allowed_check(subtype)
        return python_value

    @classmethod
    def binary_serialize(cls,value,accumulator=None,subtype=None):
        cls._subtypes_allowed_check(subtype)

        r = accumulator
        if r is None:
            r = []
       
        r.append(opcodes_by_name[cls.type_name])
        cls._binary_serialize(value,r,subtype=subtype)

        if accumulator is None:
            return b''.join(r)

    @classmethod
    def binary_deserialize(cls,fd,subtype=None):
        cls._subtypes_allowed_check()
        raise NotImplementedError 

    @classmethod
    def _isinstance_subtype_check(cls,value,subtype):
        if subtype is None:
            return True
        else:
            assert not cls.subtypes_allowed
            raise TypeError(\
"Type %r doesn't support subtypes but got subtype=%r in isinstance() check" %
                        (cls,subtype))

    @classmethod
    def isinstance(cls,value,subtype=None):
        for c in cls.applicable_classes:
            if isinstance(value,c):
                if cls._isinstance_subtype_check(value,subtype):
                    return True
        return False


@register_serializable_type
class NullType(SerializableType):
    type_name = 'null'
    applicable_classes = (None.__class__,)

    @classmethod
    def _binary_serialize(cls,value,r,subtype=None):
        # binary_serialize() has already inserted the opcode byte, which is
        # enough to mark a null by itself as there is only one null value. 
        pass

@register_serializable_type
class BoolType(SerializableType):
    type_name = 'bool'
    applicable_classes = (bool,)

    @classmethod
    def _binary_serialize(cls,value,r,subtype=None):
        # so this is inefficient, whatever, you can compress it later
        if value:
            r.append(b'\xff')
        else:
            r.append(b'\x00')

    @classmethod
    def _binary_deserialize(cls,fd,subtype=None):
        v = fd.read(1) 
        if v == b'\xff':
            return True
        elif v == b'\x00':
            return False
        else:
            raise ValueError('Bool opcode given unknown value code 0x%X' % ord(v))

@register_serializable_type
class IntType(SerializableType):
    type_name = 'int'
    applicable_classes = (int,long)

    @classmethod
    def _binary_serialize(cls,value,r,subtype=None):
        # zig-zag encode
        if value >= 0:
            value = value << 1
        else:
            value = (value << 1) ^ (~0)

        while value >= 0b10000000:
            r.append(chr((value & 0b01111111) | 0b10000000))
            value = value >> 7
        r.append(chr((value & 0b01111111) | 0b00000000))

@register_serializable_type
class UIntType(SerializableType):
    type_name = 'uint'
    applicable_classes = (int,long)
    auto_serialize_and_deserialize = False

    @classmethod
    def _binary_serialize(cls,value,r,subtype=None):
        while value >= 0b10000000:
            r.append(chr((value & 0b01111111) | 0b10000000))
            value = value >> 7
        r.append(chr((value & 0b01111111) | 0b00000000))

@register_serializable_type
class StrType(SerializableType):
    type_name = 'str'
    applicable_classes = (unicode,)

    @classmethod
    def _json_serialize(cls,value,subtype=None):
        # NFC normalization is shortest. We don't care about legacy characters;
        # we just want strings to always normalize to the exact same bytes so
        # that we can get consistent digests.
        return unicodedata.normalize('NFC',value)

    @classmethod
    def _binary_serialize(cls,value,r,subtype=None):
        value = StrType.json_serialize(value)
        value_utf8 = value.encode('utf8')

        if b'\x00' in value_utf8:
            raise ValueError('Unicode strings with null characters can not be serialized')

        r.append(value_utf8)
        r.append(b'\x00')

@register_serializable_type
class BytesType(SerializableType):
    type_name = 'bytes'
    applicable_classes = (bytes,)

    @classmethod
    def _json_serialize(cls,value,subtype=None):
        return binascii.hexlify(value)

    @classmethod
    def _json_deserialize(cls,value,subtype=None):
        return binascii.unhexlify(value)

    @classmethod
    def _binary_serialize(cls,value,r,subtype=None):
        UIntType._binary_serialize(len(value),r)
        r.append(value)

@register_serializable_type
class DictType(SerializableType):
    type_name = 'dict'
    applicable_classes = (dict,)

    @staticmethod
    def parse_keyname(kw_name):
        """Parse a key name
        
        Returns (key_name,key_type,key_subtype)
        """

        parts = kw_name.split(u'.',2)
        name = kw_type = kw_subtype = None
        try:
            name = parts[0]
        except IndexError:
            raise ValueError("Serialized dicts can't name empty names")

        try:
            kw_type = serializations_by_name[parts[1]]
        except IndexError:
            raise ValueError("No type specified for key name '%s'" % kw_name)
        except KeyError:
            raise ValueError("Unknown type '%s' in key name '%s'" % (parts[1],kw_name))

        try:
            kw_subtype = parts[2]
        except IndexError:
            pass

        return (name,kw_type,kw_subtype)

    @staticmethod
    def value_is_correct_type_for_name(value,name):
        """Determine if a value is of the correct type for its name"""
        value_name,value_type,value_subtype = DictType.parse_keyname(name)
        return value_type.isinstance(value,value_subtype)

    @staticmethod
    def __raise_if_value_is_not_correct_type(value,value_type,value_subtype,value_full_name):
        if not value_type.isinstance(value,value_subtype): 
            raise TypeError(\
                    "Value for keyword %r is not an instance of the type name, got %r instead"\
                    % (value_full_name,value.__class__))

    @classmethod
    def _json_serialize(cls,value,subtype=None):
        r = {}
        for (key_full_name,key_value) in value.items():
            key_name,key_type,key_subtype = DictType.parse_keyname(key_full_name)

            cls.__raise_if_value_is_not_correct_type(key_value,key_type,key_subtype,key_full_name)

            r[key_full_name] = key_type._json_serialize(key_value,key_subtype)
        return r

    @classmethod
    def _binary_serialize(cls,value,r,subtype=None):
        for key_full_name in sorted(value.keys()):
            key_name,key_type,key_subtype = DictType.parse_keyname(key_full_name)

            key_value = value[key_full_name]

            cls.__raise_if_value_is_not_correct_type(key_value,key_type,key_subtype,key_full_name)

            # Save the type name.
            StrType._binary_serialize(unicode(key_full_name),r)

            # Save the type value.
            #
            # Note that since we already know the type of serialization being
            # done from the name, we can skip the header byte.
            key_type._binary_serialize(value[key_full_name],r,subtype=key_subtype)

        # Mark the end of the dict with an empty name.
        StrType._binary_serialize(u'',r)

@register_serializable_type
class ListType(SerializableType):
    type_name = 'list'
    applicable_classes = (list,tuple)

    @classmethod
    def __parse_subtype(cls,subtype):
        subtype = subtype.split('.',1)
        if len(subtype) == 1:
            subtype.append(None)
        try:
            return (serializations_by_name[subtype[0]],subtype[1])
        except KeyError:
            raise TypeError("Invalid subtype '%s'" % subtype)

    @classmethod
    def _isinstance_subtype_check(cls,value,subtype):
        # lists always require a type
        if not subtype:
            return False

        (subtype_class,subsubtype) = ListType.__parse_subtype(subtype)
        for v in value:
            if not subtype_class.isinstance(v,subsubtype):
                return False
        return True

    @classmethod
    def __check_subtype_against_value(cls,value,subtype):
        # Re-use the above subtype specific check
        if not ListType._isinstance_subtype_check(value,subtype):
            # It'd be nice to say exactly what value failed, but that'd be
            # complex to do when multiple lists are nested.
            raise TypeError("Value in list doesn't match subtype")


    @classmethod
    def _json_serialize(cls,value,subtype=None):
        ListType.__check_subtype_against_value(value,subtype)

        (subtype_class,subsubtype) = ListType.__parse_subtype(subtype)

        r = []
        for v in value:
            r.append(subtype_class.json_serialize(v,subsubtype))
        return r

    @classmethod
    def _binary_serialize(cls,value,r,subtype=None):
        ListType.__check_subtype_against_value(value,subtype)

        (subtype_class,subsubtype) = ListType.__parse_subtype(subtype)

        for v in value:
            subtype_class._binary_serialize(v,r,subtype=subsubtype)
        r.append(opcodes_by_name['list_end'])

