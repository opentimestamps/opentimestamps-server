# Copyright (C) 2016-2017 The OpenTimestamps developers
#
# This file is part of the OpenTimestamps Server.
#
# It is subject to the license terms in the LICENSE file found in the top-level
# directory of this distribution.
#
# No part of the OpenTimestamps Server including this file, may be copied,
# modified, propagated, or distributed except according to the terms contained
# in the LICENSE file.

import collections
import logging
import threading
import time
import random
import bitcoin.rpc

from bitcoin.core import COIN, b2lx, b2x, x, lx, CTxIn, CTxOut, COutPoint, CTransaction, str_money_value
from bitcoin.core.script import CScript, OP_RETURN

from opentimestamps.bitcoin import cat_sha256d
from opentimestamps.core.notary import BitcoinBlockHeaderAttestation
from opentimestamps.core.op import OpPrepend, OpSHA256
from opentimestamps.core.timestamp import Timestamp, make_merkle_tree

from otsserver.calendar import Journal

KnownBlock = collections.namedtuple('KnownBlock', ['height', 'hash'])
TimestampTx = collections.namedtuple('TimestampTx', ['tx', 'tip_timestamp', 'commitment_timestamps'])
UnconfirmedTimestampTx = collections.namedtuple('TimestampTx', ['tx', 'tip_timestamp', 'n'])


def make_btc_block_merkle_tree(blk_txids):
    assert len(blk_txids) > 0

    digests = blk_txids
    while len(digests) > 1:
        # The famously broken Satoshi algorithm: if the # of digests at this
        # level is odd, double the last one.
        if len(digests) % 2:
            digests.append(digests[-1].msg)

        next_level = []
        for i in range(0, len(digests), 2):
            next_level.append(cat_sha256d(digests[i], digests[i + 1]))

        digests = next_level

    return digests[0]


def make_timestamp_from_block_tx(confirmed_tx, block, blockheight):

    commitment_tx = confirmed_tx.tx
    serialized_tx = commitment_tx.serialize(params={'include_witness': False})
    digest = confirmed_tx.tip_timestamp.msg

    try:
        i = serialized_tx.index(digest)
    except ValueError:
        assert False, "can't build a block_timestamp from my tx, this is not supposed to happen, exiting"

    prefix = serialized_tx[0:i]
    suffix = serialized_tx[i + len(digest):]

    digest_timestamp = Timestamp(digest)

    # Add the commitment ops necessary to go from the digest to the txid op
    prefix_stamp = digest_timestamp.ops.add(OpPrepend(prefix))
    txid_stamp = cat_sha256d(prefix_stamp, suffix)

    assert commitment_tx.GetTxid() == txid_stamp.msg

    # Create the txid list, with our commitment txid op in the appropriate
    # place
    block_txid_stamps = []
    for tx in block.vtx:
        if tx.GetTxid() != txid_stamp.msg:
            block_txid_stamps.append(Timestamp(tx.GetTxid()))
        else:
            block_txid_stamps.append(txid_stamp)

    # Build the merkle tree
    merkleroot_stamp = make_btc_block_merkle_tree(block_txid_stamps)
    assert merkleroot_stamp.msg == block.hashMerkleRoot

    attestation = BitcoinBlockHeaderAttestation(blockheight)
    merkleroot_stamp.attestations.add(attestation)

    return digest_timestamp


class OrderedSet(collections.OrderedDict):
    def add(self, item):
        self[item] = ()

    def remove(self, item):
        self.pop(item)

class KnownBlocks:
    """Maintain a list of known blocks"""

    def __init__(self):
        self.__blocks = []

    def __detect_reorgs(self, proxy):
        """Detect reorgs, rolling back if needed"""
        while self.__blocks:
            try:
                actual_blockhash = proxy.getblockhash(self.__blocks[-1].height)

                if actual_blockhash == self.__blocks[-1].hash:
                    break
            except IndexError:
                # rollback!
                pass

            logging.info("Reorg detected at height %d, rolling back block %s"
                         % (self.__blocks[-1].height, b2lx(self.__blocks[-1].hash)))
            self.__blocks.pop(-1)

    def update_from_proxy(self, proxy):
        """Update from an RPC proxy

        Returns a list of new block heights, hashes
        """
        r = []
        while not self.__blocks or proxy.getbestblockhash() != self.__blocks[-1].hash:
            self.__detect_reorgs(proxy)

            height = self.__blocks[-1].height + 1 if self.__blocks else proxy.getblockcount()

            try:
                hash = proxy.getblockhash(height)
            except IndexError:
                continue

            self.__blocks.append(KnownBlock(height, hash))
            r.append(self.__blocks[-1])

        return r

    def best_block_height(self):
        return self.__blocks[-1].height if self.__blocks else 0


def _get_tx_fee(tx, proxy):
    """Calculate tx fee

    Assumes inputs are confirmed
    """
    value_in = 0
    for txin in tx.vin:
        try:
            r = proxy.gettxout(txin.prevout, False)
        except IndexError:
            return None
        value_in += r['txout'].nValue

    value_out = sum(txout.nValue for txout in tx.vout)
    return value_in - value_out

# not using proxy.listunspent() because it tries to convert bech32 address as base58
def listunspent(proxy, minconf=0, maxconf=999999):
    r = proxy._call('listunspent', minconf, maxconf)

    r2 = []
    for unspent in r:
        unspent['outpoint'] = COutPoint(lx(unspent['txid']), unspent['vout'])
        del unspent['txid']
        del unspent['vout']
        unspent['scriptPubKey'] = CScript(x(unspent['scriptPubKey']))
        unspent['amount'] = int(unspent['amount'] * COIN)
        r2.append(unspent)
    return r2

def find_unspent(proxy):
    def sort_filter_unspent(unspent):
        # https://github.com/bitcoin/bitcoin/blob/master/src/policy/policy.cpp
        DUST = 0.00000546 * COIN
        return sorted(filter(lambda x: x['amount'] > DUST and x['spendable'], unspent),
                      key=lambda x: x['amount'])

    unspent = sort_filter_unspent(listunspent(proxy, 1))

    if len(unspent):
        return unspent
    else:
        logging.info("Couldn't find a confirmed output, trying unconfirmed")

        # Try again with the unconfirmed transactions
        unconfirmed_unspent = sort_filter_unspent(listunspent(proxy, 0, 1))

        confirmed_unspent = []
        for unspent_txout in unconfirmed_unspent:
            txid = unspent_txout['outpoint'].hash
            tx = proxy.getrawtransaction(txid)
            for txin in tx.vin:
                try:
                    confirmed_outpoint = proxy.gettxout(txin.prevout, includemempool=False)

                    # make sure this txout is from a wallet transaction, which
                    # means we can spend it
                    proxy.gettransaction(txin.prevout.hash)

                    # All our txs will have a single input, with opt-in RBF set
                    prevout_tx = proxy.getrawtransaction(txin.prevout.hash)
                    if len(prevout_tx.vin) != 1 or prevout_tx.vin[0].nSequence != 0xfffffffd:
                        continue
                except IndexError:
                    continue

                confirmed_unspent.append({'outpoint': txin.prevout,
                                          'amount': confirmed_outpoint['txout'].nValue})

        return sorted(confirmed_unspent, key=lambda x: x['amount'])


class Stamper:
    """Timestamping bot"""

    @staticmethod
    def __create_new_timestamp_tx_template(outpoint, txout_value, change_scriptPubKey):
        """Create a new timestamp transaction template

        The transaction created will have one input and two outputs, with the
        timestamp output set to an invalid dummy.

        The fee is set to zero, but nSequence is set to opt-in to transaction
        replacement, so you can find an appropriate fee iteratively.
        """

        return CTransaction([CTxIn(outpoint, nSequence=0xfffffffd)],
                            [CTxOut(txout_value, change_scriptPubKey),
                             CTxOut(-1, CScript())])

    @staticmethod
    def __update_timestamp_tx(old_tx, new_commitment, new_min_block_height, relay_feerate):
        """Update an existing timestamp transaction

        Returns the old transaction with a new commitment, and with the fee
        bumped appropriately.
        """
        delta_fee = int(len(old_tx.serialize()) * relay_feerate)

        old_change_txout = old_tx.vout[0]

        assert old_change_txout.nValue - delta_fee > relay_feerate * 3  # FIXME: handle running out of money!

        return CTransaction(old_tx.vin,
                            [CTxOut(old_change_txout.nValue - delta_fee, old_change_txout.scriptPubKey),
                             CTxOut(0, CScript([OP_RETURN, new_commitment]))],
                            nLockTime=new_min_block_height)

    def __save_confirmed_timestamp_tx(self, confirmed_tx):
        """Save a fully confirmed timestamp to disk"""
        self.calendar.add_commitment_timestamps(confirmed_tx.commitment_timestamps)
        logging.info("tx %s fully confirmed, %d timestamps added to calendar" %
                     (b2lx(confirmed_tx.tx.GetTxid()),
                      len(confirmed_tx.commitment_timestamps)))

    def __pending_to_merkle_tree(self, n):
            # Update the most recent timestamp transaction with new commitments
            commitment_timestamps = [Timestamp(commitment) for commitment in tuple(self.pending_commitments)[0:n]]

            # Remember that commitment_timestamps contains raw commitments,
            # which are longer than necessary, so we sha256 them before passing
            # them to make_merkle_tree, which concatenates whatever it gets (or
            # for the matter, returns what it gets if there's only one item for
            # the tree!)
            commitment_digest_timestamps = [stamp.ops.add(OpSHA256()) for stamp in commitment_timestamps]

            logging.debug("Making merkle tree")
            tip_timestamp = make_merkle_tree(commitment_digest_timestamps)
            logging.debug("Done making merkle tree")

            return tip_timestamp, commitment_timestamps

    def __do_bitcoin(self):
        """Do Bitcoin-related maintenance"""

        # FIXME: we shouldn't have to create a new proxy each time, but with
        # current python-bitcoinlib and the RPC implementation it seems that
        # the proxy connection can timeout w/o recovering properly.
        proxy = bitcoin.rpc.Proxy()

        new_blocks = self.known_blocks.update_from_proxy(proxy)

        # code after this if it's executed only when we have new blocks, it simplify reasoning at the cost of not
        # having a broadcasted tx immediately after we have a new cycle (the calendar wait the next block)
        if not new_blocks:
            return

        for (block_height, block_hash) in new_blocks:
            logging.info("New block %s at height %d" % (b2lx(block_hash), block_height))

            # Save commitments to disk that have reached min_confirmations
            confirmed_tx = self.txs_waiting_for_confirmation.pop(block_height - self.min_confirmations + 1, None)
            if confirmed_tx is not None:
                self.__save_confirmed_timestamp_tx(confirmed_tx)

            # If there already are txs waiting for confirmation at this
            # block_height, there was a reorg and those pending commitments now
            # need to be added back to the pool
            reorged_tx = self.txs_waiting_for_confirmation.pop(block_height, None)
            if reorged_tx is not None:
                # FIXME: the reorged transaction might get mined in another
                # block, so just adding the commitments for it back to the pool
                # isn't ideal, but it is safe
                logging.info('tx %s at height %d removed by reorg, adding %d commitments back to pending'
                             % (b2lx(reorged_tx.tx.GetTxid()), block_height, len(reorged_tx.commitment_timestamps)))
                for reorged_commitment_timestamp in reorged_tx.commitment_timestamps:
                    self.pending_commitments.add(reorged_commitment_timestamp.msg)

            # Check if this block contains any of the pending transactions
            block = None
            while block is None:
                try:
                    block = proxy.getblock(block_hash)
                except KeyError:
                    # Must have been a reorg or something, return
                    logging.error("Failed to get block")
                    return
                except BrokenPipeError:
                    logging.error("BrokenPipeError to get block")
                    time.sleep(5)
                    proxy = bitcoin.rpc.Proxy()

            # the following is an optimization, by pre computing the tx_id we rapidly check if our unconfirmed tx
            # is in the block
            block_txids = set(tx.GetTxid() for tx in block.vtx)

            # Check all potential pending txs against this block.
            # iterating in reverse order to prioritize most recent digest which commits to a bigger merkle tree
            for unconfirmed_tx in self.unconfirmed_txs[::-1]:

                if unconfirmed_tx.tx.GetTxid() not in block_txids:
                    continue

                confirmed_tx = unconfirmed_tx  # Success! Found tx
                block_timestamp = make_timestamp_from_block_tx(confirmed_tx, block, block_height)

                logging.info("Found commitment %s in tx %s"
                             % (b2x(confirmed_tx.tip_timestamp.msg), b2lx(confirmed_tx.tx.GetTxid())))
                # Success!
                (tip_timestamp, commitment_timestamps) = self.__pending_to_merkle_tree(confirmed_tx.n)
                mined_tx = TimestampTx(confirmed_tx.tx, tip_timestamp, commitment_timestamps)
                assert tip_timestamp.msg == unconfirmed_tx.tip_timestamp.msg

                mined_tx.tip_timestamp.merge(block_timestamp)

                logging.debug("Removing %d commitments from pending" % (unconfirmed_tx.n))
                for commitment in tuple(self.pending_commitments)[0:unconfirmed_tx.n]:
                    self.pending_commitments.remove(commitment)

                assert self.min_confirmations > 1
                logging.info("Success! %d commitments timestamped, now waiting for %d more confirmations" %
                             (len(mined_tx.commitment_timestamps), self.min_confirmations - 1))

                # Add pending_tx to the list of timestamp transactions that
                # have been mined, and are waiting for confirmations.
                self.txs_waiting_for_confirmation[block_height] = mined_tx

                # Erase all unconfirmed txs, as they all conflict with each other
                self.unconfirmed_txs.clear()

                # Finally, schedule a new timestamp transaction.
                #
                # To help desync calendars, this time is randomized.
                self.next_timestamp_tx = time.time() + (self.min_tx_interval * random.uniform(1, 2))

                break

        time_to_next_tx = self.next_timestamp_tx - time.time()
        if time_to_next_tx > 0:
            # Minimum interval between transactions hasn't been reached, so do nothing
            logging.debug("Waiting %ds before next tx" % time_to_next_tx)
            return

        if not self.pending_commitments:
            logging.debug("No pending commitments, no tx needed")
            return

        if self.unconfirmed_txs:
            (prev_tx, prev_tip_timestamp, prev_commitment_timestamps) = self.unconfirmed_txs[-1]
        else:  # first tx of a new cycle
            # Find the biggest unspent output that's confirmed
            unspent = find_unspent(proxy)

            if not len(unspent):
                logging.error("Can't timestamp; no spendable outputs")
                return

            change_addr = proxy._call("getnewaddress", "", "bech32")
            change_addr_info = proxy._call("getaddressinfo", change_addr)
            change_addr_script = x(change_addr_info['scriptPubKey'])

            prev_tx = self.__create_new_timestamp_tx_template(unspent[-1]['outpoint'], unspent[-1]['amount'],
                                                              change_addr_script)

            logging.debug('New timestamp tx, spending output %r, value %s' % (unspent[-1]['outpoint'],
                                                                              str_money_value(unspent[-1]['amount'])))

        (tip_timestamp, commitment_timestamps) = self.__pending_to_merkle_tree(len(self.pending_commitments))
        logging.debug("New tip is %s" % b2x(tip_timestamp.msg))
        # make_merkle_tree() seems to take long enough on really big adds
        # that the proxy dies
        proxy = bitcoin.rpc.Proxy()

        sent_tx = None
        relay_feerate = self.relay_feerate
        while sent_tx is None:
            unsigned_tx = self.__update_timestamp_tx(prev_tx, tip_timestamp.msg,
                                                     proxy.getblockcount(), relay_feerate)

            fee = _get_tx_fee(unsigned_tx, proxy)
            if fee is None:
                logging.debug("Can't determine txfee of transaction; skipping")
                return
            if fee > self.max_fee:
                logging.error("Maximum txfee reached!")
                return

            r = proxy.signrawtransactionwithwallet(unsigned_tx)
            if not r['complete']:
                logging.error("Failed to sign transaction! r = %r" % r)
                return
            signed_tx = r['tx']

            try:
                proxy.sendrawtransaction(signed_tx)
            except bitcoin.rpc.JSONRPCError as err:
                if err.error['code'] == -26:
                    logging.debug("Err: %r" % err.error)
                    # Insufficient priority - basically means we didn't
                    # pay enough, so try again with a higher feerate
                    relay_feerate *= 2
                    continue

                else:
                    raise err  # something else, fail!

            sent_tx = signed_tx

        if self.unconfirmed_txs:
            logging.info("Sent timestamp tx %s, replacing %s; %d total commitments; %d prior tx versions" %
                         (b2lx(sent_tx.GetTxid()), b2lx(prev_tx.GetTxid()), len(commitment_timestamps),
                          len(self.unconfirmed_txs)))
        else:
            logging.info("Sent timestamp tx %s; %d total commitments" % (b2lx(sent_tx.GetTxid()),
                                                                         len(commitment_timestamps)))

        self.unconfirmed_txs.append(UnconfirmedTimestampTx(sent_tx, tip_timestamp, len(commitment_timestamps)))

    def __loop(self):
        logging.info("Starting stamper loop")

        journal = Journal(self.calendar.path + '/journal')

        try:
            with open(self.calendar.path + '/journal.known-good', 'r') as known_good_fd:
                idx = int(known_good_fd.read().strip())
        except FileNotFoundError as exp:
            idx = 0

        while not self.exit_event.is_set():
            # Get all pending commitments
            while len(self.pending_commitments) < self.max_pending:
                try:
                    commitment = journal[idx]
                except KeyError:
                    break

                # Is this commitment already stamped?
                if commitment not in self.calendar:
                    self.pending_commitments.add(commitment)
                    if idx % 1000 == 0:
                        logging.debug('Added %s (idx %d) to pending commitments; %d total'
                                      % (b2x(commitment), idx, len(self.pending_commitments)))
                else:
                    if idx % 10000 == 0:
                        logging.debug('Commitment at idx %d already stamped' % idx)

                idx += 1

            self.journal_cursor = idx

            try:
                self.__do_bitcoin()
            except bitcoin.rpc.InWarmupError as warmuperr:
                logging.info("Bitcoincore is warming up: %r" % warmuperr)
                time.sleep(5)
            except ValueError as err:
                # If not caused by misconfiguration this error in bitcoinlib
                # usually occurs when bitcoincore is not started
                if str(err).startswith('Cookie file unusable'):
                    logging.error("Proxy Authentication Error: Is bitcoincore running?: %r" % err)
                    time.sleep(5)
                else:
                    logging.error("__do_bitcoin() failed: %r" % exp, exc_info=True)
            except Exception as exp:
                # !@#$ Python.
                #
                # Just logging errors like this is garbage, but we don't really
                # know all the ways that __do_bitcoin() will raise an exception
                # so easiest just to ignore and continue onwards.
                #
                # Mainly Bitcoin Core has been hanging up on our RPC
                # connection, and python-bitcoinlib doesn't have great handling
                # of that. In our case we should be safe to just retry as
                # __do_bitcoin() is fairly self-contained.
                logging.error("__do_bitcoin() failed: %r" % exp, exc_info=True)

            self.exit_event.wait(1)

    def is_pending(self, commitment):
        """Return whether or not a commitment is waiting to be stamped

        Returns False if not, or str reason if it is
        """
        if commitment in self.pending_commitments:
            return "Pending confirmation in Bitcoin blockchain"

        else:
            journal = Journal(self.calendar.path + '/journal')
            idx = self.journal_cursor
            while idx is not None:
                # cursor is None when stamper loop never executed once
                try:
                    recent_commitment = journal[idx]
                except KeyError:
                    break
                if recent_commitment == commitment:
                    return "Pending confirmation in Bitcoin blockchain"
                idx += 1

            for height, ttx in self.txs_waiting_for_confirmation.items():
               for commitment_timestamp in ttx.commitment_timestamps:
                    if commitment == commitment_timestamp.msg:
                        return "Timestamped by transaction %s; waiting for %d confirmations"\
                               % (b2lx(ttx.tx.GetTxid()), self.min_confirmations-1)

        return False

    def __init__(self, calendar, exit_event, relay_feerate, min_confirmations, min_tx_interval, max_fee, max_pending):
        self.calendar = calendar
        self.exit_event = exit_event

        self.relay_feerate = relay_feerate
        self.min_confirmations = min_confirmations
        assert self.min_confirmations > 1
        self.min_tx_interval = min_tx_interval
        self.max_fee = max_fee
        self.max_pending = max_pending

        self.known_blocks = KnownBlocks()
        self.unconfirmed_txs = []

        self.pending_commitments = OrderedSet()
        self.txs_waiting_for_confirmation = {}

        self.next_timestamp_tx = time.time()
        self.journal_cursor = None

        self.thread = threading.Thread(target=self.__loop)
        self.thread.start()
