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

"""getblock must survive Bitcoin Core closing an idle RPC connection.

Saving a confirmed tx with tens of thousands of commitments can take longer
than Bitcoin Core's rpcservertimeout (30s by default), which then closes the
keep-alive connection. The following getblock failed with
http.client.RemoteDisconnected, aborting __do_bitcoin() after the block had
already been added to known_blocks, so the block was never checked for our
pending txs.
"""

import http.client
import threading
import unittest
from unittest import mock

from otsserver.stamper import Stamper

BLOCK_HASH = b'\x03' * 32


def make_stamper():
    with mock.patch.object(Stamper, '_Stamper__loop', lambda self: None):
        stamper = Stamper(None, threading.Event(), conf_target=6, relay_feerate=1,
                          min_confirmations=6, min_tx_interval=0,
                          max_fee=100000, max_pending=100)
    stamper.thread.join()
    stamper.known_blocks = mock.Mock()
    stamper.known_blocks.update_from_proxy.return_value = [(101, BLOCK_HASH)]
    return stamper


def make_rpc_proxy():
    proxy = mock.Mock()
    proxy.getblock.return_value = mock.Mock(vtx=[])
    return proxy


class Test_getblock(unittest.TestCase):
    def test_remote_disconnected_is_retried(self):
        stamper = make_stamper()

        stale = make_rpc_proxy()
        stale.getblock.side_effect = http.client.RemoteDisconnected(
            'Remote end closed connection without response')
        fresh = make_rpc_proxy()

        with mock.patch('bitcoin.rpc.Proxy', side_effect=[stale, fresh]), \
             mock.patch('otsserver.stamper.time.sleep'):
            stamper._Stamper__do_bitcoin()

        stale.getblock.assert_called_once_with(BLOCK_HASH)
        fresh.getblock.assert_called_once_with(BLOCK_HASH)

    def test_reconnects_after_saving_confirmed_tx(self):
        stamper = make_stamper()
        stamper.txs_waiting_for_confirmation[101 - stamper.min_confirmations + 1] = mock.Mock()

        before_save = make_rpc_proxy()
        after_save = make_rpc_proxy()

        with mock.patch('bitcoin.rpc.Proxy', side_effect=[before_save, after_save]), \
             mock.patch.object(Stamper, '_Stamper__save_confirmed_timestamp_tx') as save:
            stamper._Stamper__do_bitcoin()

        save.assert_called_once()
        before_save.getblock.assert_not_called()
        after_save.getblock.assert_called_once_with(BLOCK_HASH)


if __name__ == "__main__":
    unittest.main()
