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

from .calendar import MultiNotaryCalendar
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

    def __init__(self):
        self.calendar = MultiNotaryCalendar(dag=Dag())

    def __call__(self,environ,start_response):
        try:
            path = environ['PATH_INFO']
            print('path_info',path)
        except KeyError:
            path = environ['REQUEST_URI'].decode('utf-8').split('=', 1)[0]
            print('request_uri',environ['REQUEST_URI'])

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
            print(path,method,args,kwargs)

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

    def get_merkle_child(self,notary=None):
        if not isinstance(notary,Notary):
            raise Exception('expected Notary, not %r' % notary.__class__)
        return self.calendar.get_merkle_child(notary)

    def post_verification(self,verify_op=None):
        if not isinstance(verify_op,Op):
            raise Exception('expected Op, not %r' % verify_op.__class__)
        return self.calendar.add_verification(verify_op)

    def post_digest(self,op=None):
        if not isinstance(op,Op):
            raise Exception('expected Op, not %r' % op.__class__)
        return self.calendar.submit(op)

    def get_path(self,source,dest):
        return self.calendar.dag.path(source,dest)
