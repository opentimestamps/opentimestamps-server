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

import os
import struct

from opentimestamps._internal import hexlify,unhexlify
from opentimestamps.crypto import sha256d,sha256
from opentimestamps.dag import Digest,Hash
from opentimestamps.notary.bitcoin import setup_rpc_proxy,serialize_block_header,BitcoinSignature
from opentimestamps.io import TimestampFile

from otsserver._internal import exclusive_lockf

import opentimestamps._bitcoinrpc as btcrpc

class BitcoinCalendar:
    """Manage a calendar linking digests to signatures

    The calendar is the middleware between the RPC interface and the actual
    storage of digests and signatures.
    """
    def __init__(self, datadir, metadata_url, context=None):
        self.context = context
        self.datadir = datadir
        self.metadata_url = metadata_url

    def submit(self, digest):
        """see rpc.post_digest"""
        ops = []
        with open(self.datadir + '/queue','a') as queue_fd:
            with exclusive_lockf(queue_fd):
                # Keep the digest to a standard size
                if len(digest) != 32:
                    ops.append(Hash(digest))
                else:
                    ops.append(Digest(digest))

                queue_fd.write(hexlify(ops[-1]) + '\n')
                queue_fd.flush()

        ops[-1].metadata[self.metadata_url] = {}
        return ops

    def digest2path(self, digest):
        """Convert a digest to a sharded path name

        Re-hashes for cryptography
        """
        digest = hexlify(sha256(digest + bytes(self.context.config['bitcoin-timestamper']['shard-nonce'],'utf8')))
        return '{}/complete/{}/{}'.format(self.datadir, digest[0:2], digest)

    def path(self, digest, notary_spec):
        """see rpc.get_path"""
        print(self.digest2path(digest))
        if os.path.exists(self.digest2path(digest)):
            ts = TimestampFile(in_fd=open(self.digest2path(digest), 'rb'))
            return (tuple(ts.dag), tuple(ts.signatures))
        else:
            return ((),())


def create_checkmultisig_tx(tx_in, m, value, pubkeys, proxy):
    assert 0 < m <= len(pubkeys) <= 16

    pubkeys = [unhexlify(pubkey) for pubkey in pubkeys]

    # Create a transaction with no outputs
    partial_tx = unhexlify(proxy.createrawtransaction(tx_in, {}))

    scriptSig = b''

    scriptSig += bytes([80 + m])

    for pubkey in pubkeys:
        scriptSig += bytes([len(pubkey)])
        scriptSig += pubkey

    scriptSig += bytes([80 + len(pubkeys)])
    scriptSig += b'\xae'

    return partial_tx[:-5] + b'\x01' + struct.pack('<Q',int(value*100000000)) + bytes([len(scriptSig)]) + scriptSig + partial_tx[-4:]


def find_digest_in_block(digest, block_hash, proxy):
    block = proxy.getblock(hexlify(block_hash))

    path = []

    tx_num = None
    tx_hash = None
    raw_tx = None
    for (i,tx_hash) in enumerate(block['tx']):
        tx_hash = unhexlify(tx_hash)
        try:
            raw_tx = unhexlify(proxy.getrawtransaction(hexlify(tx_hash)))
        except btcrpc.JSONRPCException as err:
            if err.error['code'] == -5:
                continue
            else:
                raise err
        if digest in raw_tx:
            # Split the raw_tx bytes up to create the Hash inputs. Keep in mind
            # that digest might be present in the transaction more than once.
            inputs = []
            raw_tx_left = raw_tx
            while raw_tx_left:
                j = raw_tx_left.find(digest)
                if j >= 0:
                    inputs.append(raw_tx_left[0:j])
                    inputs.append(digest)
                    raw_tx_left = raw_tx_left[j+len(digest):]
                else:
                    inputs.append(raw_tx_left)
                    raw_tx_left = ''
            path.append(Hash(*inputs, algorithm="sha256d"))
            tx_num = i
            break

    if tx_num is None:
        return None

    assert sha256d(raw_tx)[::-1] == tx_hash

    # Rebuild the merkle tree and in the process collect all the leaves
    # required to go from our tx to the root of he tree.
    #
    # This could probably be optimized, but whatever.
    next_leaf_num = tx_num
    hashes = [unhexlify(tx)[::-1] for tx in block['tx']]
    while len(hashes) > 1:
        # Bitcoin duplicates the last hash to make the length even.
        if len(hashes) % 2:
            hashes.append(hashes[-1])

        newhashes = []
        for i in range(0,len(hashes),2):
            newhashes.append(sha256d(hashes[i] + hashes[i+1]))

            if i == next_leaf_num:
                path.append(Hash(hashes[i],hashes[i+1], algorithm="sha256d"))
                next_leaf_num = len(newhashes)-1
            elif i+1 == next_leaf_num:
                path.append(Hash(hashes[i],hashes[i+1], algorithm="sha256d"))
                next_leaf_num = len(newhashes)-1
        hashes = newhashes

    # Finally add the block header itself.
    identity = 'mainnet'
    if proxy.getinfo()['testnet']:
        # FIXME: do we need some way to determine what version of testnet?
        identity = 'testnet'

    raw_block_header = serialize_block_header(block)
    assert hashes[0] == raw_block_header[36:68]
    path.append(
            Digest(raw_block_header[0:36], hashes[0], raw_block_header[68:],parents=(hashes[0],)))

    return (path, BitcoinSignature(digest=path[-1], identity=identity))
