# Copyright (C) 2016 The OpenTimestamps developers
#
# This file is part of the OpenTimestamps Server.
#
# It is subject to the license terms in the LICENSE file found in the top-level
# directory of this distribution.
#
# No part of the OpenTimestamps Server including this file, may be copied,
# modified, propagated, or distributed except according to the terms contained
# in the LICENSE file.

import http.server
import os
import socketserver
import threading
import time

from opentimestamps.core.serialize import StreamSerializationContext

class RPCRequestHandler(http.server.BaseHTTPRequestHandler):
    MAX_COMMITMENT_MSG_LENGTH = 64
    """Largest message that can be POSTed for commitment"""

    NONCE_LENGTH = 16
    """Length of nonce added to submitted messages"""

    digest_queue = None

    def post_commitment(self):
        content_length = int(self.headers['Content-Length'])

        if content_length > self.MAX_COMMITMENT_MSG_LENGTH:
            self.send_response(400)
            self.send_header('Content-type','text/plain')
            self.end_headers()
            self.wfile.write(b'message too long')
            return


        msg = self.rfile.read(content_length)

        timestamp = self.aggregator.submit(msg)

        self.send_response(200)
        self.send_header('Content-type','text/html')
        self.end_headers()

        ctx = StreamSerializationContext(self.wfile)
        timestamp.serialize(ctx)

        from binascii import hexlify
        from opentimestamps.core.serialize import BytesSerializationContext
        ctx = BytesSerializationContext()
        timestamp.serialize(ctx)
        print(hexlify(ctx.getbytes()))



    def get_commitment(self):
        self.send_response(200)
        self.send_header('Content-type','text/html')
        self.end_headers()


    def do_POST(self):
        if self.path == '/commitment':
            self.post_commitment()

        else:
            self.send_response(404)
            self.send_header('Content-type','text/plain')
            self.end_headers()
            self.wfile.write(b'not found')

    def do_GET(self):
        if self.path.startswith('/commitment/'):
            self.get_commitment()

        else:
            self.send_response(404)
            self.send_header('Content-type','text/plain')
            self.end_headers()
            self.wfile.write(b'not found')


class StampServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    def __init__(self, server_address, aggregator):
        class rpc_request_handler(RPCRequestHandler):
            pass
        rpc_request_handler.aggregator = aggregator

        super().__init__(server_address, rpc_request_handler)

    def serve_forever(self):
        super().serve_forever()
