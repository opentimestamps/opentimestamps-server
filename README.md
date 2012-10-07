OpenTimestamps Server
=====================

Open-source distributed timestamping.


Hacking
-------

This repository uses sub-modules for the opentimestamps-client and jsonrpclib:

    git submodule update --init

Symbolic links are provided to allow the Python module import path to work as
expected.  For technical reasons it would be difficult to call the server
library 'opentimestamps.server', so it's called 'otsserver' instead.


Unit tests
----------

python -m unittest discover
