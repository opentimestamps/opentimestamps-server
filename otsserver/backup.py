#!/usr/bin/env python3
import otsserver
from otsserver.calendar import Journal
from bitcoin.core import b2x
from opentimestamps.core.serialize import BytesSerializationContext, BytesDeserializationContext, TruncationError

import logging

PAGING = 1000


class Backup:
    def __init__(self, journal, calendar):
        self.journal = journal
        self.calendar = calendar

    def create_from(self, start):
        backup_map = {}
        for i in range(start, start+PAGING):
            try:
                current = self.journal[i]
                # print(str(i) +":"+b2x(journal[i]))
                current_el = self.calendar[current]
                # print("\t"+str(current_el))
                self.__create_kv_map(current_el, current_el.msg, backup_map)
            except KeyError:
                return None
            if i % 100 == 0:
                logging.info(str(i) + ":" + b2x(self.journal[i]))

        kv_bytes = self.__kv_map_to_bytes(backup_map)

        return kv_bytes

    @staticmethod
    def __bytes_to_kv_map(kv_bytes):
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


    @staticmethod
    def __create_kv_map(ts, msg, kv_map):
        ctx = BytesSerializationContext()

        ctx.write_varuint(len(ts.attestations))
        for attestation in ts.attestations:
            attestation.serialize(ctx)

        ctx.write_varuint(len(ts.ops))
        for op in ts.ops:
            op.serialize(ctx)

        kv_map[msg] = ctx.getbytes()

        for op, timestamp in ts.ops.items():
            Backup.__create_kv_map(timestamp, timestamp.msg, kv_map)

    @staticmethod
    def __kv_map_to_bytes(kv_map):
        ctx = BytesSerializationContext()
        for key, value in kv_map.items():
            ctx.write_varuint(len(key))
            ctx.write_bytes(key)
            ctx.write_varuint(len(value))
            ctx.write_bytes(value)

        return ctx.getbytes()
