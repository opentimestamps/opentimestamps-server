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

from opentimestamps import implementation_identifier as client_implementation_id
from opentimestamps.dag import *
from opentimestamps.serialization import *
from opentimestamps.notary import *

from . import implementation_identifier as server_implementation_id

# TODO: exceptions class.
#
# We also need standardized argument type tests.

from urllib.parse import parse_qs,unquote_plus

class WsgiInterface:
    """Implements a WSGI RESTful interface to an OpenTimestamps Server"""

    _rpc_major_version = 1
    _rpc_minor_version = 0

    _sourcecode_url = 'https://github.com/petertodd/opentimestamps-server.git'

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
            args = [json_deserialize(json.loads(unquote_plus(arg))) for arg in path[1:]]
            kwargs = {k:json_deserialize(json.loads(v)) for k,v in kwargs.items()}

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
                response_headers = [('Content-Type','application/json')]
                start_response('200 OK',response_headers)
                r = json.dumps(json_serialize(fn_ret),indent=4)
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

    def get_merkle_tip(self):
        """Return a list of operations that will create a merkle tip of the whole calendar.

        Sign the last operation in this list with your signature and return the
        list, and your new signature, to the server via the post_verification
        method.
        """
        return self.calendar.get_merkle_tip()

    def post_verification(self,ops=None):
        """Add a new verification.

        ops should be a list of operations comprising the verification. The
        server will determine if the operations can be incorporated into the
        calendar.
        """
        for op in ops:
            if not isinstance(op,Op):
                raise Exception('expected Op, not %r' % op.__class__)
        return self.calendar.add_verification(ops)

    def post_digest(self,op=None):
        """Add a digest to the calendar.

        Returns a list of operations that collectively form a path between the
        operation you submitted, and an operation in the calendar proper.

        The order of this list is undefined. If the submission is successful
        metadata for at least one operation will be set, with the server's
        canonical url. Potentially more than one returned operation will have
        metadata set.
        """
        if not isinstance(op,Op):
            raise Exception('expected Op, not %r' % op.__class__)
        return self.calendar.submit(op)

    def get_path(self,op=None,notary_spec=None):
        """Find a path between an operation and a signature from the specified notary.

        Returns a list of operations that form paths to one or more
        verification operation with a signature by the specified notary.

        The order of the list is undefined.
        """
        assert op is not None
        assert notary_spec is not None
        return self.calendar.path(op,notary_spec)
