import unittest

from otsserver.bitcoin_rpc import make_proxy


class TestBitcoinRpc(unittest.TestCase):
    def test_make_proxy_sets_wallet_path(self):
        proxy = make_proxy(wallet="otsd", service_url="http://user:pass@127.0.0.1:8332")

        self.assertEqual(proxy._BaseProxy__url.path, "/wallet/otsd")

    def test_make_proxy_url_encodes_wallet_name(self):
        proxy = make_proxy(wallet="wallet with/slash", service_url="http://user:pass@127.0.0.1:8332")

        self.assertEqual(proxy._BaseProxy__url.path, "/wallet/wallet%20with%2Fslash")

    def test_make_proxy_without_wallet_keeps_root_path(self):
        proxy = make_proxy(service_url="http://user:pass@127.0.0.1:8332")

        self.assertEqual(proxy._BaseProxy__url.path, "")


if __name__ == "__main__":
    unittest.main()
