# OpenTimestamps Calendar Server

This package provides aggregation, Bitcoin timestamping, and remote calendar
services for OpenTimestamps clients. You don't need to run a server to use the
OpenTimestamps protocol - public servers exist that are free to use. That said,
running a server locally can be useful for developers of OpenTimestamps
protocol clients, particularly with a local Bitcoin node running in regtest
mode.


## Requirements

* python-bitcoinlib v0.7.0
* leveldb


## Installing

You will need a bitcoin node running on the same machine. You can safely use 
the testnet. You will need this in your bitcoin.conf:
```
# uncomment this for testnet
#testnet=1 
# uncomment this line to run a pruned node
# security will be the same, but won't be
# contributing as much to the bitcoin network
#prune=1024 
server=1
listen=1
rpcuser=CHANGETHIS
rpcpassword=CHANGETHIS
rpcserialversion=0 # ots doesn't support segwit yet
```

Clone the repo and install the requirements:

```
git clone https://github.com/opentimestamps/opentimestamps-server.git
pip3 install -r requirements.txt
```

Run it once to create the config directory.
```
./otsd
```

OTS will complain that you don't have an URI and/or a hmac key. To fix those, you need to define the public URI of your calendar server in ~/.otsd/calendar/uri .
Basically whatever is in that file is put into the URI field of pending attestations returned by that calendar server. So when a client goes to verify a timestamp created by that calendar, if the URI starts with http or https, it'll try to make a HTTP(S) connection to that server to fetch the rest of the timestamp proof.

E.g. the alice.btc.calendar.opentimestamps.org calendar server has https://alice.btc.calendar.opentimestamps.org in the ~/.otsd/calendar/uri file.

You will also need a hmac key:
``` 
dd if=/dev/random of=~/.otsd/calendar/hmac-key bs=32 count=1
```

By default your server will run on 127.0.0.1:14788 and you will need to reverse proxy. There is a reference config from 
a public server in contrib for nginx. You can also [do the same with apache](https://www.digitalocean.com/community/tutorials/how-to-use-apache-as-a-reverse-proxy-with-mod_proxy-on-ubuntu-16-04).

You can test your server with by doing:

```
ots stamp somefile -c=http://YOURURI/ -m=1

ots upgrade somefile.ots -c=http://YOURURI/
```

## Unit tests

python3 -m unittest discover -v
