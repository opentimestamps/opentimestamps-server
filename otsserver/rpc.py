# Copyright (C) 2016-2017 The OpenTimestamps developers
#
# This file is part of the OpenTimestamps Server.
#
# It is subject to the license terms in the LICENSE file found in the top-level
# directory of this distribution.
#
# No part of the OpenTimestamps Server including this file, may be copied,
# modified, propagated, or distributed except according to the terms contained
# in the LICENSE file.

import binascii
import http.server
import qrcode
import socketserver
import time
import pystache
import datetime
import base64
import simplejson
from functools import reduce
from io import BytesIO

import bitcoin.core
from bitcoin.core import b2lx, b2x, str_money_value

from otsserver.backup import Backup
import otsserver
from opentimestamps.core.serialize import StreamSerializationContext

from otsserver.calendar import Journal
renderer = pystache.Renderer()


def get_qr(data):
    img = qrcode.make(data)
    buf = BytesIO()
    img.save(buf)
    return base64.b64encode(buf.getvalue())


class RPCRequestHandler(http.server.BaseHTTPRequestHandler):
    MAX_DIGEST_LENGTH = 64
    """Largest digest that can be POSTed for timestamping"""

    digest_queue = None

    def post_digest(self):
        content_length = self.headers['Content-Length']

        # Might be missing or otherwise invalid
        try:
            content_length = int(content_length)
        except TypeError:
            self.send_response(400)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'invalid Content-Length')
            return

        if content_length > self.MAX_DIGEST_LENGTH:
            self.send_response(400)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'digest too long')
            return

        digest = self.rfile.read(content_length)

        timestamp = self.aggregator.submit(digest)

        self.send_response(200)
        self.send_header('Content-type', 'application/octet-stream')
        self.end_headers()

        ctx = StreamSerializationContext(self.wfile)
        timestamp.serialize(ctx)

    def get_tip(self):
        try:
            msg = self.calendar.stamper.unconfirmed_txs[-1].tip_timestamp.msg
        except:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            return

        if msg is not None:
            self.send_response(200)
            self.send_header('Content-type', 'application/octet-stream')
            self.send_header('Cache-Control', 'public, max-age=10')
            self.end_headers()
            self.wfile.write(msg)
        else:
            self.send_response(204)
            self.send_header('Cache-Control', 'public, max-age=10')
            self.end_headers()

    def get_backup(self):
        chunk = self.path[len('/experimental/backup/'):]
        try:
            chunk = int(chunk)
            result = self.backup[chunk]
        except:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.send_header('Cache-Control', 'public, max-age=60')
            self.end_headers()
            return

        assert result is not None
        self.send_response(200)
        self.send_header('Content-type', 'application/octet-stream')
        self.send_header('Cache-Control', 'public, max-age=31536000')
        self.end_headers()
        self.wfile.write(result)

    def get_timestamp(self):
        commitment = self.path[len('/timestamp/'):]

        try:
            commitment = binascii.unhexlify(commitment)
        except binascii.Error:
            self.send_response(400)
            self.send_header('Content-type', 'text/plain')
            self.send_header('Cache-Control', 'public, max-age=31536000') # this will never not be an error!
            self.end_headers()
            self.wfile.write(b'commitment must be hex-encoded bytes')
            return

        try:
            timestamp = self.calendar[commitment]
        except KeyError:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')

            # Pending?
            reason = self.calendar.stamper.is_pending(commitment)
            if reason:
                reason = reason.encode()

                # The commitment is pending, so its status will change soonish
                # as blocks are found.
                self.send_header('Cache-Control', 'public, max-age=60')

            else:
                # The commitment isn't in this calendar at all. Clients only
                # get specific commitments from servers, so in the current
                # implementation there's no reason why this response would ever
                # change.
                #
                # FIXME: unfortunately, this isn't actually true, as the
                # stamper may return `Not Found` for a commitment that was just
                # added, as commitments aren't actually added directly to the
                # pending data structure, but rather, added to the journal and
                # only then added to pending. So for now, set a reasonably
                # short cache control header.
                #
                # See https://github.com/opentimestamps/opentimestamps-server/issues/10
                # for more info.
                self.send_header('Cache-Control', 'public, max-age=60')
                reason = b'Not found'

            self.end_headers()
            self.wfile.write(reason)
            return

        self.send_response(200)

        # Since only Bitcoin attestations are currently made, once a commitment
        # is timestamped by Bitcoin this response will never change.
        self.send_header('Cache-Control', 'public, max-age=31536000')

        self.send_header('Content-type', 'application/octet-stream')
        self.end_headers()

        timestamp.serialize(StreamSerializationContext(self.wfile))

    def do_POST(self):
        if self.path == '/digest':
            self.post_digest()

        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')

            # a 404 is only going to become not a 404 if the server is upgraded
            self.send_header('Cache-Control', 'public, max-age=3600')

            self.end_headers()
            self.wfile.write(b'not found')

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')

            # Humans are likely to be refreshing this, so keep it up-to-date
            # Changed to 5 seconds, otherwise cache was never hit
            self.send_header('Cache-Control', 'public, max-age=5')

            self.end_headers()

            try:
                proxy = bitcoin.rpc.Proxy()
            except Exception as err:
                return

            # minconf=1 will underestimate the balance when timestamp txs are
            # pending. But this at least avoids confusion if an unconfirmed
            # transaction has been made in the wallet, tying up coins. Eg if a
            # tx has been made to combine dust UTXOs.
            str_wallet_balance = str_money_value(proxy.getbalance(minconf=1))

            transactions = proxy._call("listtransactions", "*", 1000)
            # We want only the confirmed txs containing an OP_RETURN, from most to least recent
            transactions = list(filter(lambda x: x["confirmations"] > 0 and x["amount"] == 0, transactions))
            a_week_ago = (datetime.date.today() - datetime.timedelta(days=7)).timetuple()
            a_week_ago_posix = time.mktime(a_week_ago)
            transactions_in_last_week = list(filter(lambda x: x["time"] > a_week_ago_posix, transactions))
            fees_in_last_week = reduce(lambda a, b: a-b["fee"], transactions_in_last_week, 0)
            try:
                time_between_transactions = str(round(168 / len(transactions_in_last_week), 2)) # in hours based on 168 hours in a week
                time_between_transactions += " hours"
            except ZeroDivisionError:
                time_between_transactions = "N/A"
            transactions.sort(key=lambda x: x["confirmations"])

            lightning_invoice = None
            lightning_invoice_qr = None
            if self.lightning_invoice_file is not None:
                try:
                    with open(self.lightning_invoice_file, 'r') as file:
                        lightning_invoice = file.read().strip()
                        lightning_invoice_qr = get_qr(lightning_invoice.upper())
                except FileNotFoundError:
                    pass

            address = str(self.donation_addr)
            homepage_template = """<html>
<head>
    <title>OpenTimestamps Calendar Server</title>
    <link rel="icon" type="image/x-icon" href="data:image/x-icon;base64,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">
</head>
<body style="word-break: break-word;">
<p>This is an <a href="https://opentimestamps.org">OpenTimestamps</a> <a href="https://github.com/opentimestamps/opentimestamps-server">Calendar Server</a> (v{{ version }})</p>

<p>
Pending commitments: {{ pending_commitments }}</br>
Transactions waiting for confirmation: {{ txs_waiting_for_confirmation }}</br>
Most recent unconfirmed timestamp tx: <a href="{{ explorer_url }}/tx/{{ most_recent_tx }}">{{ most_recent_tx }}</a> ({{ prior_versions }} prior versions)</br>
Most recent merkle tree tip: {{ tip }}</br>
Best-block: <a href="{{ explorer_url }}/block/{{ best_block }}">{{ best_block }}</a>, height {{ block_height }}</br>
</br>
Wallet balance: {{ balance }} BTC (confirmed)</br>
</p>

<hr>

<p>
You can donate to the wallet by sending funds to:</br>
<img src="data:image/png;base64, {{ address_qr }}" width="250" /></br>
<span><a href="{{ explorer_url }}/address/{{ address }}">{{ address }}</a></span>
</p>

<hr>

{{ #lightning_invoice }}
<p>
You can also donate with Lightning:</br>
<img src="data:image/png;base64, {{ lightning_invoice_qr }}" width="400"/></br>
<span><a href="lightning:{{ lightning_invoice }}">{{ lightning_invoice }}</a></span>
</p>
<hr>
{{ /lightning_invoice }}
<p>
Average time between transactions in the last week: {{ time_between_transactions }} </br>
Fees used in the last week: {{ fees_in_last_week }} BTC</br>
</p>

<p>
Latest mined transactions (confirmations): </br>
</br>
<tt>
{{#transactions}}
    <a href="{{ explorer_url }}/tx/{{txid}}">{{txid}}</a> {{fee}} ({{confirmations}})</br>
{{/transactions}}
</tt>
</p>

</body>
</html>"""

            stats = { 'version': otsserver.__version__,
              'pending_commitments': len(self.calendar.stamper.pending_commitments),
              'txs_waiting_for_confirmation':len(self.calendar.stamper.txs_waiting_for_confirmation),
              'most_recent_tx': b2lx(self.calendar.stamper.unconfirmed_txs[-1].tx.GetTxid()) if self.calendar.stamper.unconfirmed_txs else 'None',
              'prior_versions': max(0, len(self.calendar.stamper.unconfirmed_txs) - 1),
              'tip': b2x(self.calendar.stamper.unconfirmed_txs[-1].tip_timestamp.msg) if self.calendar.stamper.unconfirmed_txs else 'None',
              'best_block': bitcoin.core.b2lx(proxy.getbestblockhash()),
              'block_height': proxy.getblockcount(),
              'balance': str_wallet_balance,
              'address': address,
              'address_qr': get_qr(address),
              'transactions': transactions[:288],
              'time_between_transactions': time_between_transactions,
              'fees_in_last_week': fees_in_last_week,
              'lightning_invoice': lightning_invoice,
              'lightning_invoice_qr': lightning_invoice_qr,
              'explorer_url': self.explorer_url,
            }
            if self.headers['Accept'] == "application/json":
                self.wfile.write(str.encode(simplejson.dumps(stats, use_decimal=True, indent=4 * ' ')))
            else:
                welcome_page = renderer.render(homepage_template, stats)
                self.wfile.write(str.encode(welcome_page))

        elif self.path.startswith('/timestamp/'):
            self.get_timestamp()
        elif self.path.startswith('/qr/'):
            self.get_qr()
        elif self.path == '/tip':
            self.get_tip()
        elif self.path.startswith('/experimental/backup/'):
            self.get_backup()
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')

            # a 404 is only going to become not a 404 if the server is upgraded
            self.send_header('Cache-Control', 'public, max-age=3600')

            self.end_headers()
            self.wfile.write(b'Not found')


class StampServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    def __init__(self, server_address, aggregator, calendar, lightning_invoice_file, donation_addr, explorer_url):

        class rpc_request_handler(RPCRequestHandler):
            pass
        rpc_request_handler.aggregator = aggregator
        rpc_request_handler.calendar = calendar
        rpc_request_handler.lightning_invoice_file = lightning_invoice_file
        rpc_request_handler.donation_addr = donation_addr
        rpc_request_handler.explorer_url = explorer_url

        journal = Journal(calendar.path + '/journal')
        rpc_request_handler.backup = Backup(journal, calendar, calendar.path + '/backup_cache')

        super().__init__(server_address, rpc_request_handler)

    def serve_forever(self):
        super().serve_forever()

