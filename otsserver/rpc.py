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
from functools import reduce
from io import BytesIO

import bitcoin.core
from bitcoin.core import b2lx, b2x

from otsserver.backup import Backup
import otsserver
from opentimestamps.core.serialize import StreamSerializationContext

from otsserver.calendar import Journal
renderer = pystache.Renderer()

class RPCRequestHandler(http.server.BaseHTTPRequestHandler):
    MAX_DIGEST_LENGTH = 64
    """Largest digest that can be POSTed for timestamping"""

    digest_queue = None

    def post_digest(self):
        content_length = int(self.headers['Content-Length'])

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

    def get_qr(self):
        data = self.path[len('/qr/'):]
        img = qrcode.make(data)
        buf = BytesIO()
        img.save(buf)
        img_stream = buf.getvalue()
        self.send_response(200)
        self.send_header('Content-type', 'image/png')
        self.send_header('Cache-Control', 'public, max-age=10')
        self.end_headers()
        self.wfile.write(img_stream)

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
        self.send_header('Cache-Control', 'public, max-age=3600')

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
            self.send_header('Cache-Control', 'public, max-age=1')

            self.end_headers()

            proxy = bitcoin.rpc.Proxy()

            # FIXME: Unfortunately getbalance() doesn't return the right thing;
            # need to investigate further, but this seems to work.
            str_wallet_balance = str(proxy._call("getbalance"))

            transactions = proxy._call("listtransactions", "*", 1000)
            # We want only the confirmed txs containing an OP_RETURN, from most to least recent
            transactions = list(filter(lambda x: x["confirmations"] > 0 and x["amount"] == 0, transactions))
            a_week_ago = (datetime.date.today() - datetime.timedelta(days=7)).timetuple()
            a_week_ago_posix = time.mktime(a_week_ago)
            transactions_in_last_week = list(filter(lambda x: x["time"] > a_week_ago_posix, transactions))
            fees_in_last_week = reduce(lambda a,b: a-b["fee"], transactions_in_last_week, 0)
            try:
                time_between_transactions = str(round(168 / len(transactions_in_last_week), 2)) # in hours based on 168 hours in a week
                time_between_transactions += " hours"
            except ZeroDivisionError:
                time_between_transactions = "N/A"
            transactions.sort(key=lambda x: x["confirmations"])
            homepage_template = """<html>
<head>
    <title>OpenTimestamps Calendar Server</title>
</head>
<body style="word-break: break-word;">
<p>This is an <a href="https://opentimestamps.org">OpenTimestamps</a> <a href="https://github.com/opentimestamps/opentimestamps-server">Calendar Server</a> (v{{ version }})</p>

<p>
Pending commitments: {{ pending_commitments }}</br>
Transactions waiting for confirmation: {{ txs_waiting_for_confirmation }}</br>
Most recent unconfirmed timestamp tx: {{ most_recent_tx }} ({{ prior_versions }} prior versions)</br>
Most recent merkle tree tip: {{ tip }}</br>
Best-block: {{ best_block }}, height {{ block_height }}</br>
</br>
Wallet balance: {{ balance }} BTC</br>
</p>

<hr>

<p>
You can donate to the wallet by sending funds to:</br>
<img src="/qr/{{ address }}" width="250" /></br>
<span>{{ address }}</span>
</p>

<hr>

{{ #lightning_invoice }}
<p>
You can donate through lightning network with the following invoice:</br>
<img src="/qr/{{ lightning_invoice }}" width="400"/></br>
<span>{{ lightning_invoice }}</span>
</p>
<hr>
{{ /lightning_invoice }}
<p>
Average time between transactions in the last week: {{ time_between_transactions }} </br>
Fees used in the last week: {{ fees_in_last_week }} BTC</br>
</p>

<p>
Latest mined transactions (confirmations): </br>
{{#transactions}}
    {{txid}} ({{confirmations}})</br>
{{/transactions}}
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
              'address': proxy._call("getaccountaddress",""),
              'transactions': transactions[:10],
              'time_between_transactions': time_between_transactions,
              'fees_in_last_week': fees_in_last_week,
              'lightning_invoice': self.lightning_invoice,
            }
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
    def __init__(self, server_address, aggregator, calendar, lightning_invoice):
        class rpc_request_handler(RPCRequestHandler):
            pass
        rpc_request_handler.aggregator = aggregator
        rpc_request_handler.calendar = calendar
        rpc_request_handler.lightning_invoice = lightning_invoice

        journal = Journal(calendar.path + '/journal')
        rpc_request_handler.backup = Backup(journal, calendar, calendar.path + '/backup_cache')

        super().__init__(server_address, rpc_request_handler)

    def serve_forever(self):
        super().serve_forever()
