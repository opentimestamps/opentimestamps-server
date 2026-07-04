import urllib.parse

import bitcoin.rpc


def make_proxy(wallet=None, service_url=None, **kwargs):
    """Create a Bitcoin Core RPC proxy, optionally scoped to a wallet."""

    if service_url is not None:
        kwargs['service_url'] = service_url

    proxy = bitcoin.rpc.Proxy(**kwargs)

    if wallet is not None:
        wallet_path = "/wallet/" + urllib.parse.quote(wallet, safe="")

        # python-bitcoinlib reads cookie/config auth only when service_url is not
        # supplied. Adjusting the parsed URL keeps that behavior while directing
        # wallet RPCs to Bitcoin Core's wallet endpoint.
        url = proxy._BaseProxy__url
        url = url._replace(path=wallet_path)
        proxy._BaseProxy__url = url
        proxy._BaseProxy__service_url = urllib.parse.urlunparse(url)

    return proxy
