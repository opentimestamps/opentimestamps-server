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


Dedication
----------

I'd like to thank my father, Kevin Todd, for all the days I've spent with him
bagging peaks in the Canadian Rockies.
