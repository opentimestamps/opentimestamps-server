# OpenTimestamps Server TODO list

## Daemon Support

Currently there's no tooling provided for running the OpenTimestamps server as
a proper daemon service, with all the usual init integration and logging
functionality.


## HTTP Caching

Cache-control headers aren't currently set at all in REST responses. This is
needed for load-balancing via HTTPS caches.


## Mirroring

It should be possible to run a mirror calendar server that mirrors the contents
of another calendar server in real-time. A reasonable approach to doing this
would be to extend the append-only commitment journal to store commitment
operations and attestations in the calendar as well as the commitments; the
leveldb database that currently stores the calendar data would then be just an
index of that journal. A mirror would work by progressively downloading the
journal, and reconstructing the indexes locally.

Most of this functionality should actually be implemented in the
python-opentimestamps library: it's also useful for clients who don't want to
have to rely on the public calendars.


## Stand-alone Aggregation Servers

For load-balancing, it should be possible to run servers that only aggregate
digests for submission to a remote calendar, and don't store a calendar
locally. Equally, mirror servers should be able to aggregate digests for
submission to another calendar.


## Welcome Page

Currently visiting https://alice.btc.calendar.opentimestamps.org with a
web-browser gets an unfriendly 404 "not found" error.
