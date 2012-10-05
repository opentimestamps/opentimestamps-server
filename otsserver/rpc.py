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

from opentimestamps.dag import *
from opentimestamps.serialization import *

class RpcInterface(object):
    """Implements the RPC interface

    Serialization/deserialization is not done here.
    """

    rpc_major_version = 1
    rpc_minor_version = 0

    sourcecode_url = u'https://github.com/petertodd/opentimestamps-server.git'


    def version(self):
        return (self.rpc_major_version,
                self.rpc_minor_version)

    def sourcecode(self):
        return self.sourcecode_url

    def help(self):
        return self.__class__.__dict__

    def submit(self,digests):
        if isinstance(digests,str):
            digests = (digests,)
        try:
            iter(digests)
        except TypeError:
            digests = (digests,)

        return digests

    def path(self,sources,dests):
        return None

class JsonWrapper(object):
    """JSON serialization wrapper"""

    def __init__(self,rpc_instance):
        self.__rpc_instance = rpc_instance

    def _dispatch(self,method,json_params):
        logging.debug("RPC call: %r %r",method,json_params)

        try:
            fn = getattr(self.__rpc_instance,method)
        except AttributeError:
            raise AttributeError("Unknown RPC method '%s'" % method)

        params = json_deserialize(json_params)

        r = fn(*params)

        return json_serialize(r)
