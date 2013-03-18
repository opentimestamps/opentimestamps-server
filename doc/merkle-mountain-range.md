Merkle Mountain Ranges
----------------------

As digests are accumulated we hash them into trees, building up the largest
perfect binary trees possible as we go. At least one tree will always exist,
with 2^k digests at the base, and 2^(k+1)-1 total elements. If the total number
of digests doesn't divide up into one perfect tree, more than one tree will
exist. This data structure we call a Merkle Mountain Range, for obvious
reasons, and one obscure reason:

       /\
      /  \
     /\  /\  /\
    /\/\/\/\/\/\/\

Since the trees are strictly append only, we can easily build, and store them,
on disk in the standard breadth first tree storage. In this array we can define
a height for each digest, and that height is equal to log2(n) where n is the
number of digests in the base of the tree. The following shows the contents of
that array as it is progressively extended with new digests:

    0
    00
    001 <- indexes 0 and 1 are hashed to form index 3
    0010
    0010012 <- another tree, which leads to the two subtrees being merged (height 2)
    00100120
    0010012001 <- now we have two trees, one of height 2, one of height 1

Now we have two trees, or mountains, and the result looks like the following:

     /\
    /\/\/\

This range has six digests at the base. Another eight digests, or fourteen in
total, would result in the first mountain range, shown above. Next we need to
create a single digest linked to every mountain in the range, and in turn every
digest submitted:

          /\
         /  \
        /    \
       /\     \
      /  \    /\
     /\  /\  /\ \
    /\/\/\/\/\/\/\

We've created a list of the peaks of each mountain, and in turn created a
merkle tree from that. For obscure reasons this operation is referred to as
bagging the peaks. A notary can now create a signature verifying the resulting
digest. The process can be completely deterministic, producing the exact same
digest every time provided you have every base digest and their order. By
knowing the number of digests in a given mountain range you can always
efficiently reproduce the peak enclosing the mountain whole range at that point
in time. At the same time every signature will always sign every digest in the
mountain range, and like any merkle tree the path lengths from any digest to
that signature scale by log2(n) Thus determining what signatures are reachable
from a given digest is just a matter of finding out how many digests are were
in the mountain range in total when the digest was added, and looking for
signatures added to the range at that width or larger. The storage cost for all
the intermediate hashes is n-1, and signatures don't even need to store the bag
of peaks they signed.


Divergence
----------

EDIT: none of the following is likely to be implemented, it's just not worth it
compared to simply keeping one archive per server, but the algorithm ideas are
kinda neat.

Suppose we want have multiple servers accepting, and creating signatures for, a
single archive. If we instead order the full list of digests submitted in some
way, such as numerically, we find that eventually all servers will come to
agreement provided they all have the same list of digests. Also, sub-lists of
digests, even if the full list isn't available, are also sorted the same way.
Thus sub-trees created from parts of the known list will be identical!

You can efficiently build up trees iteratively in this way. For each new digest
put it in the right order, then build up the new appropriate tree. For a random
order you'll find that at height 0, on average one hash pair is broken, thus
that incures a requirement to store an additional digest. For height 1, again
an additional. The height of the tree is proportional to log2(n), thus the
total storage requirement for all the trees built in this fashion is n*log2(n)

Having multiple servers build these trees iteratively doesn't change the result
significantly essentially because if they're fairly "up-to-date" with each
other, the vast majority of the tree will be the same. Still, I haven't thought
about this carefully.

From a theoretical perspective this is great, but from a practical point of
view needing 10 to 30 times more storage isn't exactly very good. The other
problem is that essentially your tree now has a "rectangular" shape, so finding
what signatures are available for what digests becomes tricky again.

If you can find an ordering where "chunks" of additional digests are unlikely
to "break up" existing trees you can get around that problem, modulo the fact
that a malicious server can break up your ordering. (although some degree of
trust probably exists) Time itself doesn't work, because the general case has
multiple servers accepting digests with very similar times. You can just pick a
random number, usually known as a UUID, to identify each server, but
essentially you've just pushed the n*log(n) scaling up a level. You also have
the same problems with signature lookup. This still might be a reasonable
solution, but no sense rushing to implement it.


Dedication
----------

I'd like to thank my father, Kevin Todd, for all the days I've spent with him
bagging peaks in the Canadian Rockies.
