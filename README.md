OpenTimestamps Server
=====================

Open-source distributed timestamping.

Example Usage
-------------

Start an otsd server first:

    ./otsd

Now submit a timestamp to the server:

    ./client/ots submit README.md

This creates a README.md.ots file.

Sign the digests on the server with GPG:

    ./client/ots sign <fingerprint>

where fingerprint is the fingerprint of a key that you can sign with. If you
copy and paste a fingerprint from GPG it will have spaces; make sure it is in
quotes or remove the spaces.

Now complete the timestamp:

    ./client/ots complete <fingerprint> README.md.ots

Verify it:

    ./client/ots verify README.md

Hacking
-------

Tested with Python 3.2.3, python3-gnupg

This repository uses sub-modules for the opentimestamps-client and jsonrpclib:

    git submodule update --init --recursive

Symbolic links are provided to allow the Python module import path to work as
expected.  For technical reasons it would be difficult to call the server
library 'opentimestamps.server', so it's called 'otsserver' instead.


Unit tests
----------

python3 -m unittest discover
