#!/usr/bin/env python3
import otsserver
from otsserver.calendar import Journal
from bitcoin.core import b2x
from opentimestamps.core.serialize import BytesSerializationContext, BytesDeserializationContext, TruncationError


def create_kv_map(ts, msg):
    for op, timestamp in ts.ops.items():
        ctx = BytesSerializationContext()
        op.serialize(ctx)
        # print("key:" + b2x(msg) + " value:" + str(op) + "-" + b2x(ctx.getbytes()))
        kv_map[msg] = ctx.getbytes()
        create_kv_map(timestamp, timestamp.msg)


def kv_map_to_bytes():
    ctx = BytesSerializationContext()
    for key, value in kv_map.items():
        ctx.write_varuint(len(key))
        ctx.write_bytes(key)
        ctx.write_varuint(len(value))
        ctx.write_bytes(value)

    return ctx.getbytes()


def bytes_to_kv_map(kv_bytes):
    ctx = BytesDeserializationContext(kv_bytes)
    new_kv_map = {}

    while True:
        try:
            key_len = ctx.read_varuint()
            key = ctx.read_bytes(key_len)
            value_len = ctx.read_varuint()
            value = ctx.read_bytes(value_len)
            new_kv_map[key] = value
        except TruncationError:
            break

    return new_kv_map


kv_map = {}
calendar_path = '/Users/casatta/calendar_backup/exported'
journal = Journal(calendar_path + '/journal')
calendar = otsserver.calendar.Calendar(calendar_path)
start = 5000000
end = 5000200
for i in range(start, end):
    try:
        current = journal[i]
        # print(str(i) +":"+b2x(journal[i]))
        current_el = calendar[current]
        # print("\t"+str(current_el))
        create_kv_map(current_el, current_el.msg)
    except KeyError:
        break
    if i % 10000 == 0:
        print(str(i) + ":" + b2x(journal[i]))

kv_bytes = kv_map_to_bytes()
# print("returning " + b2x(kv_bytes))
print("len " + str(len(kv_bytes)))

new_map = bytes_to_kv_map(kv_bytes)
# print(str(new_map))

assert len(kv_map) == len(new_map)
assert kv_map == new_map



