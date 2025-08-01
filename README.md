# OpenTimestamps Calendar Server

This package provides the `otsd` daemon, a calendar server which provides
aggregation, Bitcoin timestamping, and remote calendar services for
OpenTimestamps clients. You *do not* need to run a server to use the
OpenTimestamps protocol - public servers exist that are free to use. That said,
running a server locally can be useful for developers of OpenTimestamps
protocol clients, particularly with a local Bitcoin node running in regtest
mode.


## Installation

You'll need a local Bitcoin node (version 24.0 is known to work) with a wallet
with some funds in it; a pruned node is fine. While `otsd` is running the
wallet should not be used for other purposes, as currently the Bitcoin
timestamping functionality assumes that it has exclusive use of the wallet.

Install the requirements:

```
pip3 install -r requirements.txt
```

Create the calendar:
```
mkdir -p ~/.otsd/calendar/
echo "http://127.0.0.1:14788" > ~/.otsd/calendar/uri
echo "bitcoin donation address" > ~/.otsd/calendar/donation_addr
dd if=/dev/random of=~/.otsd/calendar/hmac-key bs=32 count=1
```

The URI determines what is put into the URI field of pending attestations
returned by this calendar server. For a server used for testing, the above is
fine; for production usage the URI should be set to a stable URL that
OpenTimestamps clients will be able to access indefinitely.

The donation address needs to be a valid Bitcoin address for the type of
network (mainnet, testnet, regtest) you're running otsd on. It's displayed on
the calendar info page.

The HMAC key should be kept secret. It's meant to allow for last-ditch calendar
recovery from untrusted sources, although only part of the functionality is
implemented. See the source code for more details!

To actually run the server, run the `otsd` program. Proper daemonization isn't
implemented yet, so `otsd` runs in the foreground. To run in testnet or
regtest, use the `--btc-testnet` or `--btc-regtest` options. The OpenTimestamps
protocol does *not* distinguish between mainnet, testnet, and regtest, so make
sure you don't mix them up!

To use your calendar server, tell your OpenTimestamps client to connect to it:
```
ots stamp -c http://127.0.0.1:14788 -m 1 FILE
```

OpenTimestamps clients have a whitelist of calendars they'll connect to
automatically; you'll need to manually add your new server to that whitelist to
use it when upgrading or verifying:

```
ots -l http://127.0.0.1:14788 upgrade FILE.ots
```

If your server is running on testnet or regtest, make sure to tell your client
what chain to use when verifying. For example, regtest:
```
ots --btc-regtest -l http://127.0.0.1:14788 upgrade FILE.ots
```

Tip: with regtest you can mine blocks on demand to make your timestamp confirm
with the `generate` RPC command. For example, to mine ten blocks instantly:

```
bitcoin-cli -generate 10
```

By default `otsd` binds to localhost; `otsd` is not designed to be exposed
directly to the public and requires a reverse proxy for production usage. An
example configuration for nginx is provided under `contrib/nginx`.

## Unit tests

```
python3 -m unittest discover -v
```



Problem Resolution with LevelDB in OpenTimestamps
## Context
During the setup of the OpenTimestamps server, compatibility issues arose between the leveldb
library and modern Python versions, which caused errors when initializing the LevelDB database.
## Problem
The error identified when trying to run the server was:
leveldb.LevelDBError: IO error: lock /home/<user>/.otsd/backups/db/LOCK: Resource temporarily
unavailable
Other versions of Python were also incompatible with the library.
## Applied Solution
It was determined that Python 3.7.12 is a stable version compatible with the leveldb library. Below
are the steps to correctly configure the environment.
### 1. Install the Correct Python Version
We used pyenv to install and activate the required Python version:
pyenv install 3.7.12
pyenv virtualenv 3.7.12 opentimestamps-env
pyenv activate opentimestamps-env
### 2. Reinstall Dependencies
With the virtual environment active, we installed the necessary dependencies for the
OpenTimestamps server:
pip install -r requirements.txt
pip install plyvel
### 3. Initialize the Server
With the environment set up, we started the server to confirm that the LevelDB database works
correctly:
python3 otsd-backup.py
If the server starts correctly and shows a message like the following, the issue is resolved:
db dir is /home/<user>/.otsd/backups/db
Starting at localhost:14799
## Verification
To verify that everything works properly, you can perform a test timestamping:
echo "OpenTimestamps Test" > test.txt
ots stamp -c http://127.0.0.1:14799 -m 1 test.txt
## Additional Notes
- Make sure you have the proper permissions for the LevelDB lock file:
 rm -f ~/.otsd/backups/db/LOCK
- If the problem persists, ensure no previous processes are occupying the required resources.
With this solution, the OpenTimestamps server should be operating correctly.


