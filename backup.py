#!/usr/bin/env python3
import otsserver
from otsserver.calendar import Journal
from bitcoin.core import b2x
from opentimestamps.core.serialize import BytesSerializationContext


def print_ts(ts, msg):
    for op, timestamp in ts.ops.items():
        ctx = BytesSerializationContext()
        op.serialize(ctx)
        # print("key:" + b2x(msg) + " value:" + str(op) + "-" + b2x(ctx.getbytes()))
        kv_map[msg] = ctx.getbytes()
        print_ts(timestamp, timestamp.msg)

kv_map = {}
calendar_path = '/Users/casatta/calendar_backup/exported'
journal = Journal(calendar_path + '/journal')
calendar = otsserver.calendar.Calendar(calendar_path)
i = 0
while True:
    try:
        current = journal[i]
        # print(str(i) +":"+b2x(journal[i]))
        current_el = calendar[current]
        # print("\t"+str(current_el))
        print_ts(current_el, current_el.msg)
    except KeyError:
        break
    i += 1
    if i % 10000 == 0:
        print(str(i) + ":" + b2x(journal[i]))


