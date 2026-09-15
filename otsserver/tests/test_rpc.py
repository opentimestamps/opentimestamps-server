from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from otsserver.rpc import RPCRequestHandler, is_recent_mined_transaction


class FakeBitcoinProxy:
    def __init__(self, transactions):
        self.transactions = transactions

    def getbalance(self, minconf):
        return 0

    def _call(self, method, account, count):
        return self.transactions

    def getbestblockhash(self):
        return bytes(32)

    def getblockcount(self):
        return 100


class TestRequestHandler(RPCRequestHandler):
    def send_response(self, code, message=None):
        pass

    def send_header(self, keyword, value):
        pass

    def end_headers(self):
        pass


class TestTransactionStatus(unittest.TestCase):
    def render_status_page(self, confirmations, max_age_blocks):
        transactions = [
            {
                "amount": 0,
                "confirmations": confirmation_count,
                "fee": -0.000001,
                "time": 0,
                "txid": str(confirmation_count),
            }
            for confirmation_count in confirmations
        ]
        handler = object.__new__(TestRequestHandler)
        handler.path = "/"
        handler.headers = {"Accept": "text/html"}
        handler.wfile = BytesIO()
        handler.btc_wallet = None
        handler.btc_rpc_url = None
        handler.calendar = SimpleNamespace(
            stamper=SimpleNamespace(
                pending_commitments=[],
                txs_waiting_for_confirmation=[],
                unconfirmed_txs=[],
            )
        )
        handler.lightning_invoice_file = None
        handler.donation_addr = "donation address"
        handler.explorer_url = "https://example.com"
        handler.max_mined_tx_age_blocks = max_age_blocks

        with (
            patch("otsserver.rpc.make_proxy", return_value=FakeBitcoinProxy(transactions)),
            patch("otsserver.rpc.get_qr", return_value=b"qr"),
        ):
            handler.do_GET()

        return handler.wfile.getvalue().decode()

    def test_current_tip_transaction_is_zero_blocks_old(self):
        self.assertTrue(is_recent_mined_transaction([{"confirmations": 1}], 0))

    def test_transaction_at_maximum_age_is_recent(self):
        self.assertTrue(is_recent_mined_transaction([{"confirmations": 11}], 10))

    def test_transaction_older_than_maximum_age_is_stale(self):
        self.assertFalse(is_recent_mined_transaction([{"confirmations": 12}], 10))

    def test_uses_most_recent_transaction(self):
        transactions = [{"confirmations": 20}, {"confirmations": 5}]

        self.assertTrue(is_recent_mined_transaction(transactions, 4))

    def test_no_transactions_is_not_recent(self):
        self.assertFalse(is_recent_mined_transaction([], 10))

    def test_disabled_status_is_not_recent(self):
        self.assertFalse(is_recent_mined_transaction([{"confirmations": 1}], None))

    def test_status_page_contains_marker_when_recent(self):
        page = self.render_status_page([11], 10)

        self.assertIn("Timestamp transaction status: OK", page)

    def test_status_page_omits_marker_when_stale(self):
        page = self.render_status_page([12], 10)

        self.assertNotIn("Timestamp transaction status: OK", page)

    def test_status_page_omits_status_when_disabled(self):
        page = self.render_status_page([12], None)

        self.assertNotIn("Timestamp transaction status: OK", page)


if __name__ == "__main__":
    unittest.main()
