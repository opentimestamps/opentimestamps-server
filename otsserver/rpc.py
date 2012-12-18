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

import io
import json
import logging
import traceback

from opentimestamps._internal import hexlify,unhexlify

from opentimestamps import implementation_identifier as client_implementation_id
from opentimestamps.dag import Hash

from . import implementation_identifier as server_implementation_id

# TODO: exceptions class.
#
# We also need standardized argument type tests.

from urllib.parse import parse_qs,unquote_plus

class WsgiInterface:
    """Implements a WSGI RESTful interface to an OpenTimestamps Server"""

    _rpc_major_version = 1
    _rpc_minor_version = 0

    _sourcecode_url = 'https://github.com/opentimestamps/opentimestamps-server.git'

    def __init__(self,calendar=None):
        assert calendar is not None
        self.calendar = calendar

    def __call__(self,environ,start_response):
        try:
            path = environ['PATH_INFO']
        except KeyError:
            path = environ['REQUEST_URI'].decode('utf-8').split('=', 1)[0]

        method = environ['REQUEST_METHOD']

        path = path.split('/')[1:]

        def dispatch():
            fn_name = method.lower() + '_' + path[0]
            fn = getattr(self,fn_name,None)
            return fn

        kwargs = None
        if method == 'GET':
            kwargs = parse_qs(environ['QUERY_STRING'], keep_blank_values=True)
        elif method == 'POST':
            length = int(environ.get('CONTENT_LENGTH','0'))
            kwargs = parse_qs(environ['wsgi.input'].read(length).decode('utf-8'))
        else:
            raise Exception('unknown %s' % method)

        kwargs2 = {}
        for k,v in kwargs.items():
            assert k not in kwargs2
            assert len(v) == 1
            kwargs2[k] = unquote_plus(v[0])
        kwargs = kwargs2

        fn = dispatch()
        if fn is not None:
            args = path[1:]

            try:
                fn_ret = dispatch()(*args,**kwargs)
            except Exception as exp:
                tb_file = io.StringIO()
                traceback.print_exc(file=tb_file)

                response_headers = [('Content-Type','text/plain')]
                start_response('500 Internal Server Error',response_headers)

                tb_file.seek(0)
                r = tb_file.read()
                tb_file.close()
                return [bytes(r,'utf8')]
            else:
                response_headers = [('Content-Type','application/json; charset=utf-8')]
                start_response('200 OK',response_headers)
                r = json.dumps(fn_ret, indent=4)
                return [bytes(r,'utf8')]
        else:
            status = '404 NOT FOUND'
            response_headers = [('Content-Type','text/plain')]
            start_response(status,response_headers)
            r = [b'Not found']
            return r

    def get_test(self,*args,**kwargs):
        return [args,kwargs]

    def post_test(self,*args,**kwargs):
        return [args,kwargs]


    def get_version(self):
        """Return version information"""
        return {'rpc_major':self._rpc_major_version,
                'rpc_minor':self._rpc_minor_version,
                'server_version':server_implementation_id,
                'client_version':client_implementation_id}

    def get_sourcecode(self):
        """Return the url to get sourcecode"""
        return self._sourcecode_url

    def get_help(self,*commands):
        """Get help"""
        if not len(commands):
            commands = list(self.__class__.__dict__.keys())

        r = []
        for cmd in commands:
            if not cmd.startswith('_'):
                doctext = self.__class__.__dict__[cmd].__doc__
                if doctext is None:
                    doctext = ''
                r.append((str(cmd),str(doctext)))
        return r

    def post_digest(self, digest=None):
        """Add a digest to the calendar.

        Returns a list of operations that collectively form a path between the
        operation you submitted, and an operation in the calendar proper.

        The order of this list is undefined. If the submission is successful
        metadata for at least one operation will be set, with the server's
        canonical url. Potentially more than one returned operation will have
        metadata set.
        """
        digest = unhexlify(digest)
        ops = self.calendar.submit(digest)
        return [op.to_primitives() for op in ops]


    def get_path(self, digest, notary_spec):
        """Find a path between a digest and a signature from the specified notary."""
        digest = unhexlify(digest)
        (ops, sigs) = self.calendar.path(digest, notary_spec)

        ops = [op.to_primitives() for op in ops]
        sigs = [sig.to_primitives() for sig in sigs]
        return (ops,sigs)
