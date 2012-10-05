OpenTimestamps Server
=====================

Open-source distributed timestamping.


Hacking
=======

This repository uses sub-modules for the opentimestamps-client and jsonrpclib:

    git submodule update --init

Symbolic links are provided to allow the Python module import path to work as
expected.  For technical reasons it would be difficult to call the server
library 'opentimestamps.server', so it's called 'otsserver' instead.


To run the unit tests:

    ./unittests

You can also restrict the unit tests to a particular directory:

    ./unittests otsserver

By default both the server and the client code are tested.
