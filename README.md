OpenTimestamps Server
=====================

Open-source distributed timestamping.


Hacking
-------

Note that this repository has the opentimestamps-client repository as a
submodule. After checkout do the following:

    git submodule update --init

For your convenience a symbolic link is included to the client/opentimestamps
directory so that the Python module import path works as expected. For
technical reasons it would be difficult to call the server library
'opentimestamps.server', so it's called 'otsserver' instead.

Unit tests
----------

python -m unittest discover
