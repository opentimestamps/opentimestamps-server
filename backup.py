#!/usr/bin/env python3
# Copyright (C) 2016 The OpenTimestamps developers
#
# This file is part of the OpenTimestamps Server.
#
# It is subject to the license terms in the LICENSE file found in the top-level
# directory of this distribution.
#
# No part of the OpenTimestamps Server, including this file, may be copied,
# modified, propagated, or distributed except according to the terms contained
# in the LICENSE file.

import os
import sys
import requests
import bitcoin.rpc
import leveldb

from urllib.parse import urlparse, urljoin

from bitcoin.core import b2x
from opentimestamps.core.notary import TimeAttestation, BitcoinBlockHeaderAttestation
from opentimestamps.core.op import Op
from opentimestamps.core.serialize import BytesDeserializationContext

from otsserver import backup

directory = os.path.expanduser("~/.otsd/backups")
os.makedirs(directory, exist_ok=True)

calendar = sys.argv[1]
if calendar is None or len(calendar) == 0:
    print("Calendar backup address is mandatory")
    exit(1)

parsed = urlparse(calendar)

current_dir = os.path.join(directory, parsed.netloc)
os.makedirs(current_dir, exist_ok=True)
db_dir = os.path.join(current_dir, "db")
os.makedirs(db_dir, exist_ok=True)
up_to = os.path.join(current_dir, "up_to")

try:
    with open(up_to, 'r') as up_to_fd:
        last_known = int(up_to_fd.read().strip())
except FileNotFoundError as exp:
    last_known = -1
print("Checking calendar " + str(calendar) + ", last_known commitment:" + str(last_known))
# TODO ask from up_to

db = leveldb.LevelDB(db_dir)

while True:
    backup_url = urljoin(calendar, "/experimental/backup/%d" % (last_known + 1))
    print(str(backup_url))
    try:
        r = requests.get(backup_url)
    except Exception as err:
        print("Exception asking " + str(backup_url) + " message " + str(err))
        break

    if r.status_code != 200:
        print("Status code not 200")
        break

    # print(r.raw.read(10))
    kv_map = backup.Backup.bytes_to_kv_map(r.content)
    # print(str(map))
    attestations = {}
    ops = {}
    print("kv_maps elements " + str(len(kv_map)))
    for key, value in kv_map.items():
        # print("--- key=" + b2x(key) + " value=" + b2x(value))
        ctx = BytesDeserializationContext(value)

        for _a in range(ctx.read_varuint()):
            attestation = TimeAttestation.deserialize(ctx)
            attestations[key] = attestation

        for _b in range(ctx.read_varuint()):
            op = Op.deserialize(ctx)
            ops[key] = op

    proxy = bitcoin.rpc.Proxy()

    # verify all bitcoin attestation are valid
    print("total attestations: " + str(len(attestations)))
    for key, attestation in attestations.items():
        if attestation.__class__ == BitcoinBlockHeaderAttestation:
            blockhash = proxy.getblockhash(attestation.height)
            block_header = proxy.getblockheader(blockhash)
            print("verifying " + b2x(key) + " " + str(block_header))
            try:  #  TODO temporary, remove
                attested_time = attestation.verify_against_blockheader(key, block_header)
            except:
                pass

    # verify all ops connects to an attestation
    print("total ops: " + str(len(ops)))
    for key, op in ops.items():

        # print("key " + b2x(key) + " op " + str(op))
        current_key = key
        current_op = op
        while True:
            next_key = current_op(current_key)
            # print("next_key " + b2x(next_key))
            if next_key in ops:
                current_key = next_key
                current_op = ops[next_key]
            else:
                break
        # print("maps to " + b2x(next_key))
        assert next_key in attestations
    print("done")

    # TODO check dir exist or create

    batch = leveldb.WriteBatch()
    for key, value in kv_map.items():
        batch.Put(key, value)
    db.Write(batch, sync=True)

    last_known = last_known+1
    try:
        with open(up_to, 'w') as up_to_fd:
            up_to_fd.write('%d\n' % last_known)
    except FileNotFoundError as exp:
        idx = 0




