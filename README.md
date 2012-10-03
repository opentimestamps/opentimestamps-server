# OpenTimestamps

A hash-chain-based timestamping system.

# Requirements

* Python (>=2.7.0)
* PyCrypto (>=0.5)


Licensing cases:

Connect to a public server: no requirements

Run a private server: no requirements, no users

Run a public server: yes, provide source code

Integrate into a box: same as public, and of course your customers get a copy

Distribute closed source, using unmodifed library: no requirements

Distribute closed soruce, using modified library: provide modified source code


I want to provide a for-pay service, where my clients have to pay to connect.

Yes! You have to give them any modified code, but you are allowed to charge for
access.


http://civicrm.org/node/166

http://webodf.org/about/license.html - licensing exemption

http://www.mongodb.org/display/DOCS/Licensing - mongodb licensing page

http://www.gnu.org/licenses/gpl-faq.html#AGPLv3ServerAsUser


actual hash tree data should be public domain?


If some network client software is released under AGPLv3, does it have to be able to provide source to the servers it interacts with? (#AGPLv3ServerAsUser)
This should not be required in any typical server-client relationship. AGPLv3 requires a program to offer source code to “all users interacting with it remotely through a computer network.” In most server-client architectures, it simply wouldn't be reasonable to argue that the server operator is a “user” interacting with the client in any meaningful sense.

Consider HTTP as an example. All HTTP clients expect servers to provide certain functionality: they should send specified responses to well-formed requests. The reverse is not true: servers cannot assume that the client will do anything in particular with the data they send. The client may be a web browser, an RSS reader, a spider, a network monitoring tool, or some special-purpose program. The server can make absolutely no assumptions about what the client will do—so there's no meaningful way for the server operator to be considered a user of that software.


split into opentimestamps core stuff, and opentimestamps advanced dag

gpl3 with linking exemption for core, agpl3 for dag
