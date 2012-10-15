OpenTimestamps Server
=====================

Open-source distributed timestamping.

This is in a very early stage of development, but the basic functionality of
submitting digests, signing the digests with timestamps, and verifying
timestamps works. The server component also works and maintains a persistent
calendar, although I wouldn't run it on anything but a local network yet; the
server is still single threaded.


Example Usage
-------------

Start an otsd server first:

    ./otsd

The directory ~/.otsserver will be created to store the submitted timestamps.

Now submit a timestamp to the server:

    ./client/ots submit README.md

This creates a README.md.ots file.

Sign the digests on the server with GPG:

    ./client/ots sign <fingerprint>

where fingerprint is the fingerprint of a key that you can sign with. This need
to be the full fingerprint, not the short 8-character long key id.

Now complete the timestamp:

    ./client/ots complete README.md.ots

Verify it:

    ./client/ots verify README.md

You can see what is actually stored in the timestamp in human readable format too:

    ./client/ots jsondump README.md.ots

Hacking
-------

Requires Python 3 and python3-gnupg

This repository uses sub-modules for the opentimestamps-client:

    git submodule update --init --recursive

Symbolic links are provided to allow the Python module import path to work as
expected.  For technical reasons it would be difficult to call the server
library 'opentimestamps.server', so it's called 'otsserver' instead.


Unit tests
----------

python3 -m unittest discover
