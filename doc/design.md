# The design of OpenTimestamps


## Terminology

In the source code the terminology we use is based on standard cryptographic
terminology. However there are some differences.


### Digest

The output of an operation. Traditionally this would be the output of a hash
function, however we define other operations.


### Notary

An entity that produces timestamps.


### Timestamp

A verifiable message, produced by a notary, stating that a particular digest
existed on, or before, a particular time.


### Operation

Something we do to one or more input digests, and/or operation arguments, to
produce a different digest. For any operation method, input digests, and
operation arguments there must be exactly one valid digest; ideal cryptographic
hash functions meet this requirement. However, for a given digest there may be
more than one operations that produce that digest.

We define three different types of operations:

* Digest - "Calculate" the digest from a fixed string. Digest operations have
           no input digests, and they have exactly one operation argument, the
           fixed string.

* Hash - Calculate the digest by appending one or more input digests, and
         hashing them with a cryptographic hash function. Hash operations have
         one operation argument, the hash algorithm to use.

* Verify - Take one input digest and append it with a timestamp. The result is
           the new digest, and the length of the result is the sum of the
           length of the input digest and the timestamp itself.

Note how while a digest operation may produce the same digest as a hash or
verify operation, provided that the hash functions used are collision free, and
there aren't any bugs in the code, a hash operation can never produce the same
digest as a verify operation and vice-versa.


## The Operations Directed Acyclic Graph (dag)

A set of operations defines a directed acyclic graph. This is an extension of
the concept of a hash tree, or merkle tree. A great example of a hash dag is
the Git revision control system. Note that because upper-case is annoying to
type, we refer to the lower-case dag, everywhere in the documentation and
source code.

An OpenTimestamps a dag really has *two* types of vertexes: digests and
operations. The edges in the graph are either multiple edges, from multiple
digests to one operation, or from an operation to a digest. However internally
we ignore that theoretical distinction, and say that the dag consists of only
one type of vertex: operations. If you try to add an operation to a dag that
happens to have the same digest as an existing operation the code will
determine which of the two operations is more useful. A digest operation is
always considered to be less useful than any other type of operation, because
it provides the least information on how the digest was computed.


## Timestamping

Our goal is to be able to prove that a particular digest existed on, or before,
a certain time. We assume the existance of one or more trusted notaries who
will make timestamps, however, those notaries are busy, and we have a very
large number of clients who need digests timestamped. We collect together
groups of submitted digests, say, "every digest submitted in the last 10
minutes", and create merkle trees resulting in a single digest. These trees can
be stored in a dag, with the parents of the tree being Digest operations,
connected together by a hiarchical set of Hash Operations, and resulting in a
single child operation. We can now send that digest to a trusted notary, and
they'll reply with a timestamp that proves that any of the submitted digests
existed on or before some time.

The clients now just have to store the path from their digest to the
timestamp(s), replacing un-needed operations with the value of the digest they
produced.

Note how while internally within the OpenTimestamps system the term "timestamp"
refers to a single digest that has been notarized, from the users point of view
their timestamp is really the minimal set of operations required to reproduce
the digest that was actually timestamped.


### Calendars: the basic idea

Suppose sometime in the future the integrity of the notaries came into
question? The resulting timestamps would be all useless, with no means to
recover. So instead we create a calendar, a series of merkle tree children that
themselves are hashed together in a chain. Now we can follow that chain and
find a timestamp signed by a notary that we still trust. We also have a
convenient "administration unit" of what data we should be archiving to enable
timestamps to be validated in the future; more on this later.


### Canonical notary specifications

Now for something a little more concrete. It would be useful to have some
standardized way to refer to what exactly we mean when we talk about a "notary"
The notary specification is modeled after URLs; the format is as follows:

    <notary method>:<notary identity>:<comment>

#### <notary method>

Preferred: [a-z][a-z0-9]+

Allowed: _*[a-z][a-z0-9\-\.\+]+

The technical method used by this notary, for instance 'pgp' is a PGP-signed
message. This part of the notary spec is designed to be easy to type and copy
and paste. Leading underscores are reserved for internal-use-only notary
methods. Names beginning with 'test' are also reserved to implement
testing-only notary methods.


#### <notary identity>

For a given notary method this must unambiguously identify the identity of the
notary. As an example for the pgp method the identity is the key fingerprint.
Every reasonable attempt should be made to ensure that the canonical identity
is easy to use on command lines. Ideally match the following, in order of
preference:

1. [a-z0-9\-]+

1. FIXME: more stuff here

1. stuff that's valid in urls

Allowed: FIXME: for now [a-za-z0-9]

Unicode is specifically disabled right now. Potentially punycode could be used,
and definitely NFC normalization. We need to keep in mind the security issues
of confusion.

Note that an empty notary identity is acceptable, and a good idea, if the
method by itself is unambiguous. For instance 'bitcoin', and the associated
'bitcoin:testnet'

FIXME: need to ban * so searching is easy?


#### Version 

Internally timestamps have a integer version attached to their notary
specification.

FIXME: a good way to specify this in the notary spec would be:
_version-n:<notary spec> Won't need this stuff for awhile though.



### Calendars: how they actually work 

Rather than create one continuous chain, we effectively create multiple chains,
one for each notary identity creating timestamps. Now we have the following:


* pool - Linked-list of new digests that haven't been timestamped.

* notary[notary_spec] - dict of every notary that has signed a timestamp in
                        this calendar. The value for each notary is the last
                        timestamp created by the notary, and a pointer to what
                        was the head of the pool when that timestamp was
                        created.

Now the algorithm to create a new timestamp is just:

1. Find every digest from our start of the pool list to the end.

2. Create a merkle tree.

3. Sign the child digest.

4. Reset our pool start to the end of the list.

Every digest is guaranteed to have the shortest possible path to the next
timestamp created by that notary. In addition, subsequent timestamps, by
different notaries, will wind up creating substantially similar merkle trees,
reusing most of the operations that create them.

If the pool gets too large it can be compressed, by making merkle trees out of
items in it, and storing the child digest instead.

To timestamp the timestamps a second, 'optional' pool can be created, whose
elements are also timestamped, but the existance of those elements doesn't
trigger a timestamp to be created.


### Scalability: a good problem to have

Once the number of digests becomes a problem, it's a simple matter to setup
additional feeder calendars/servers whose purpose is to create merkle trees of
all digests submitted in a particular time interval, say, 1 second. This is
also more convenient for clients, who can get back a digest that if not
timestamped already, will at least go in a permanent archive so they can get
their full timestamp later.

    32bytes/second * 1 year = 1gigabyte

    1gigabyte * $0.10/month * 1 year = $1.20


### Searching

TBD: My understanding is that computing dag transitive closures doesn't scale
in the general case, but this is a very particular type of dag. We can probably
do stuff like add an 'order' attribute to digests, such that parent.order <
child.order to help the searches. For now, flood-fill.


# Implementation details

See opentimestamps/dag.py for comments.
