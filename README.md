# OpenTimestamps Calendar Server

This package provides aggregation, Bitcoin timestamping, and remote calendar
services for OpenTimestamps clients. You don't need to run a server to use the
OpenTimestamps protocol - public servers exist that are free to use. That said,
running a server locally can be useful for developers of OpenTimestamps
protocol clients, particularly with a local Bitcoin node running in regtest
mode.


## Requirements

python-bitcoinlib v0.6.1
leveldb


## Unit tests

python3 -m unittest discover -v
