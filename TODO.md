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


## Collaborative Bitcoin Timestamping

Currently each public calendar makes its own Bitcoin transactions; they should
work collaboratively, so that only one transaction is used for all calendars. A
simple way to do this would be to have a master calendar, that normally is the
only server making Bitcoin transactions, and then have the slave calendars
switch to making their own transactions if the master isn't responding.


### External Bitcoin Timestamping

An alternate approach would be for calendar servers to advertise merkle tips
that they want timestamped, and then accept Bitcoin timestamps provided by
anyone for those tips. Bitcoin timestamping functionality could then be done
external to the public calendars, and redundancy provided by having multiple
stampers with varying timeouts. Equally, this would allow anyone to help out
the public infrastructure by donating a timestamp transaction (which is also a
nice way to speed up confirmation!).

We would want to apply some fairly stringent standardness checks to externally
provided transactions though: the transaction data ends up in the timestamps,
allowing attackers to do things like embed signatures that set off
virus-checkers in the transactions they submit. Segwit will make this fairly
easy though, as we can force the tx to spend exactly one segwit input, which
very effectively constrains what can be in the scriptSig; the timestamp won't
contain any witness data.
