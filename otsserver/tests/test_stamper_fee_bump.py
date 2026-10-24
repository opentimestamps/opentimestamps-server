# Copyright (C) 2026 The OpenTimestamps developers
#
# This file is part of the OpenTimestamps Server.
#
# It is subject to the license terms in the LICENSE file found in the top-level
# directory of this distribution.
#
# No part of the OpenTimestamps Server including this file, may be copied,
# modified, propagated, or distributed except according to the terms contained
# in the LICENSE file.

import threading
import unittest
from unittest import mock

import bitcoin.rpc
from bitcoin.core import COIN, COutPoint, CTransaction, CTxIn, CTxOut, lx
from bitcoin.core.script import CScript, OP_RETURN
from opentimestamps.core.timestamp import Timestamp

from otsserver.stamper import Stamper, UnconfirmedTimestampTx


class Test_Stamper(unittest.TestCase):
    def test_feerate_bump_is_bounded(self):
        """A replacement that is always rejected stops at max_fee"""
        input_value = 400
        prev_tx = CTransaction(
            [CTxIn(COutPoint(lx('00' * 32), 0), nSequence=0xfffffffe)],
            [CTxOut(input_value, CScript([b'\x00' * 20])),
             CTxOut(0, CScript([OP_RETURN, b'\x00' * 32]))])

        with mock.patch.object(Stamper, '_Stamper__loop', lambda self: None):
            stamper = Stamper(None, threading.Event(), conf_target=6, relay_feerate=1,
                              min_confirmations=6, min_tx_interval=0,
                              max_fee=COIN, max_pending=100)
        stamper.thread.join()

        stamper.pending_commitments.add(b'\x01' * 32)
        stamper.unconfirmed_txs.append(UnconfirmedTimestampTx(prev_tx, Timestamp(b'\x02' * 32), 1))
        stamper.known_blocks = mock.Mock()
        stamper.known_blocks.update_from_proxy.return_value = [(101, b'\x03' * 32)]

        proxy = mock.Mock()
        proxy.getblockcount.return_value = 100
        proxy.gettxout.return_value = {'txout': CTxOut(input_value, CScript())}
        proxy.signrawtransactionwithwallet.side_effect = lambda tx: {'complete': True, 'tx': tx}
        proxy.sendrawtransaction.side_effect = bitcoin.rpc.JSONRPCError(
            {'code': -26, 'message': 'insufficient fee'})
        proxy.getblock.return_value = mock.Mock(vtx=[])

        with mock.patch('bitcoin.rpc.Proxy', return_value=proxy):
            stamper._Stamper__do_bitcoin()

        self.assertLess(proxy.sendrawtransaction.call_count, 100)
