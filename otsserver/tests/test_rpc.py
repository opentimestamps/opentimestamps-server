from io import BytesIO
import os
import resource
import socket
import tempfile
import threading
import time
import types
from types import SimpleNamespace
import unittest
from unittest import mock
from unittest.mock import patch

from otsserver.rpc import DeadlineSocketIO, RPCRequestHandler, StampServer, is_recent_mined_transaction


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


class TestUnknownPath(unittest.TestCase):
    def test_qr_path_is_not_found(self):
        responses = []
        handler = object.__new__(TestRequestHandler)
        handler.send_response = lambda code, message=None: responses.append(code)
        handler.path = "/qr/abc"
        handler.wfile = BytesIO()

        handler.do_GET()

        self.assertEqual(responses, [404])


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


class Test_StampServer(unittest.TestCase):
    def start_server(self, aggregator=None):
        path = tempfile.TemporaryDirectory()
        self.addCleanup(path.cleanup)
        open(os.path.join(path.name, 'journal'), 'wb').close()

        server = StampServer(('127.0.0.1', 0), aggregator, types.SimpleNamespace(path=path.name),
                             None, None, None)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()

        def stop():
            server.shutdown()
            thread.join()
            server.server_close()
        self.addCleanup(stop)
        return server

    def test_default_timeout(self):
        self.assertTrue(RPCRequestHandler.timeout)

    def test_stalled_body_is_dropped(self):
        aggregator = mock.Mock()
        with mock.patch.object(RPCRequestHandler, 'timeout', 0.3):
            server = self.start_server(aggregator)
            with socket.create_connection(server.server_address, timeout=5) as sock:
                sock.sendall(b'POST /digest HTTP/1.0\r\nContent-Length: 32\r\n\r\nabcde')
                self.assertEqual(sock.recv(1024), b'')

        aggregator.submit.assert_not_called()

    def test_slow_dripping_connection_is_dropped(self):
        aggregator = mock.Mock()
        with mock.patch.object(RPCRequestHandler, 'deadline', 0.5):
            server = self.start_server(aggregator)
            with socket.create_connection(server.server_address, timeout=5) as sock:
                sock.sendall(b'POST /digest HTTP/1.0\r\nContent-Length: 32\r\n\r\n')
                start = time.monotonic()
                try:
                    while True:
                        time.sleep(0.1)
                        sock.sendall(b'a')
                except OSError:
                    pass
                self.assertLess(time.monotonic() - start, 3)

        aggregator.submit.assert_not_called()

    def test_workers_are_capped(self):
        lock = threading.Lock()
        running = [0, 0]  # current, most seen
        handle = RPCRequestHandler.handle

        def counting_handle(self):
            with lock:
                running[0] += 1
                running[1] = max(running)
            try:
                handle(self)
            finally:
                with lock:
                    running[0] -= 1

        with mock.patch.object(RPCRequestHandler, 'timeout', 0.2), \
                mock.patch.object(RPCRequestHandler, 'handle', counting_handle), \
                mock.patch.object(StampServer, 'MAX_WORKERS', 2, create=True):
            server = self.start_server()
            socks = [socket.create_connection(server.server_address, timeout=5) for _ in range(6)]
            for sock in socks:
                self.assertEqual(sock.recv(1024), b'')
                sock.close()

        self.assertLessEqual(running[1], 2)
        self.assertGreater(running[1], 0)

    def test_default_workers_follow_the_file_limit(self):
        def workers(soft):
            with mock.patch.object(resource, 'getrlimit', return_value=(soft, soft)):
                return StampServer.max_workers()

        self.assertEqual(workers(4096), 4096 - StampServer.RESERVED_FILES)
        self.assertEqual(workers(256), 128)
        self.assertEqual(workers(1), 1)
        self.assertEqual(workers(resource.RLIM_INFINITY), StampServer.FALLBACK_WORKERS)

        with mock.patch.object(StampServer, 'MAX_WORKERS', 7):
            self.assertEqual(StampServer.max_workers(), 7)

    def test_dropped_connection_is_not_reported(self):
        # A request line, a header or a body cut short by the timeout, or a
        # request line cut short by the deadline, is not an error
        for sent, patched in ((b'FOO /', 'deadline'),
                              (b'GET / HTTP/1.0\r\nX: ', 'timeout'),
                              (b'POST /digest HTTP/1.0\r\nContent-Length: 32\r\n\r\nab', 'timeout')):
            with self.subTest(sent=sent), mock.patch.object(RPCRequestHandler, patched, 0.3):
                server = self.start_server(mock.Mock())
                with mock.patch.object(server, 'handle_error') as handle_error, \
                        socket.create_connection(server.server_address, timeout=5) as sock:
                    sock.sendall(sent)
                    self.assertEqual(sock.recv(1024), b'')
                    time.sleep(0.2)
                handle_error.assert_not_called()

    def test_no_timer_thread_per_connection(self):
        server = self.start_server()
        before = threading.active_count()
        socks = [socket.create_connection(server.server_address, timeout=5) for _ in range(5)]
        time.sleep(0.5)
        try:
            self.assertEqual(threading.active_count() - before, len(socks))
        finally:
            for sock in socks:
                sock.close()

    def test_thread_start_failure_is_dropped_and_reported_once(self):
        server = self.start_server()
        with mock.patch.object(server, 'handle_error') as handle_error, \
                mock.patch.object(threading.Thread, 'start', side_effect=RuntimeError("can't start new thread")), \
                self.assertLogs(level='ERROR') as logs:
            for _ in range(5):
                with socket.create_connection(server.server_address, timeout=5) as sock:
                    self.assertEqual(sock.recv(1024), b'')

        handle_error.assert_not_called()
        self.assertEqual(len(logs.records), 1)
        # Every slot was given back
        for _ in range(server.max_workers()):
            self.assertTrue(server.worker_slots.acquire(blocking=False))

    def test_read_after_the_deadline_raises(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        right.sendall(b'data waiting')
        reader = DeadlineSocketIO(left, 30, time.monotonic() - 1)
        with self.assertRaises(socket.timeout):
            reader.readinto(bytearray(4))

    def test_body_cut_short_by_the_sender_is_not_submitted(self):
        aggregator = mock.Mock()
        server = self.start_server(aggregator)
        with socket.create_connection(server.server_address, timeout=5) as sock:
            sock.sendall(b'POST /digest HTTP/1.0\r\nContent-Length: 32\r\n\r\nabcde')
            sock.shutdown(socket.SHUT_WR)
            self.assertEqual(sock.recv(1024), b'')

        aggregator.submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
