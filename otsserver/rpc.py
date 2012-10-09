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

import logging

from opentimestamps import implementation_identifier as client_implementation_id
from opentimestamps.dag import *
from opentimestamps.serialization import *
from opentimestamps.notary import *

from .calendar import MultiNotaryCalendar
from . import implementation_identifier as server_implementation_id

# TODO: exceptions class.
#
# We also need standardized argument type tests.

class RpcInterface(object):
    """Implements the RPC interface

    Serialization/deserialization is not done here.
    """

    _rpc_major_version = 1
    _rpc_minor_version = 0

    _sourcecode_url = u'https://github.com/petertodd/opentimestamps-server.git'

    def __init__(self,data_dir):
        dag = Dag()
        self.calendar = MultiNotaryCalendar(dag=dag)


    def version(self):
        """Return version information"""
        return {'rpc_major':self._rpc_major_version,
                'rpc_minor':self._rpc_minor_version,
                'server_version':server_implementation_id,
                'client_version':client_implementation_id}

    def sourcecode(self):
        """Return the url to get sourcecode"""
        return self._sourcecode_url

    def help(self,*commands):
        """Get help"""
        if not len(commands):
            commands = self.__class__.__dict__.keys()

        r = []
        for cmd in commands:
            if not cmd.startswith('_'):
                doctext = self.__class__.__dict__[cmd].__doc__
                if doctext is None:
                    doctext = ''
                r.append((unicode(cmd),unicode(doctext)))
        return r

    def get_merkle_child(self,notary):
        if not isinstance(notary,Notary):
            raise StandardError('expected Notary, not %r' % notary.__class__)
        return self.calendar.get_merkle_child(notary)

    def add_verification(self,verify_op):
        if not isinstance(verify_op,Op):
            raise StandardError('expected Op, not %r' % verify_op.__class__)
        return self.calendar.add_verification(verify_op)

    def submit(self,op):
        if not isinstance(op,Op):
            raise StandardError('expected Op, not %r' % op.__class__)
        return self.calendar.submit(op)

    def path(self,source,dest):
        return self.calendar.dag.path(source,dest)


class JsonWrapper(object):
    """JSON serialization wrapper"""

    def __init__(self,rpc_instance):
        self.__rpc_instance = rpc_instance

    def _dispatch(self,method,json_params):
        try:
            fn = getattr(self.__rpc_instance,method)
        except AttributeError:
            raise AttributeError("Unknown RPC method '%s'" % method)

        params = json_deserialize(json_params)

        r = fn(*params)
        rj = json_serialize(r)
        logging.debug("RPC call: %r(%r) -> %r",method,json_params,rj)
        return rj
