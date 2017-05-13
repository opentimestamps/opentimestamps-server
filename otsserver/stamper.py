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
import os
import queue
import struct
import threading
import time

import bitcoin.rpc

from bitcoin.core import b2lx, b2x, CTxIn, CTxOut, CTransaction, str_money_value
from bitcoin.core.script import CScript, OP_RETURN, OP_CHECKSIG

from opentimestamps.bitcoin import make_timestamp_from_block
from opentimestamps.core.notary import PendingAttestation
from opentimestamps.core.serialize import StreamSerializationContext, StreamDeserializationContext
from opentimestamps.core.op import OpPrepend, OpAppend, OpSHA256
from opentimestamps.core.timestamp import Timestamp, make_merkle_tree
from opentimestamps.timestamp import nonce_timestamp

from otsserver.calendar import Journal

KnownBlock = collections.namedtuple('KnownBlock', ['height', 'hash'])
TimestampTx = collections.namedtuple('TimestampTx', ['tx', 'tip_timestamp', 'commitment_timestamps'])

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

            logging.info("Reorg detected at height %d, rolling back block %s" % (self.__blocks[-1].height, b2lx(self.__blocks[-1].hash)))
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

def find_unspent(proxy):
    unspent = sorted(proxy.listunspent(1),
                     key=lambda x: x['amount'] if x['spendable'] else 0)

    if len(unspent):
        return unspent

    else:
        logging.info("Couldn't find a confirmed output, trying unconfirmed")

        # Try again with the unconfirmed transactions
        unconfirmed_unspent = sorted(proxy.listunspent(0, 1),
                         key=lambda x: x['amount'] if x['spendable'] else 0)

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

                confirmed_unspent.append({'outpoint':txin.prevout,
                                          'amount':confirmed_outpoint['txout'].nValue})

        return sorted(confirmed_unspent, key=lambda x: x['amount'])

class Stamper:
    """Timestamping bot"""

    def __create_new_timestamp_tx_template(self, outpoint, txout_value, change_scriptPubKey):
        """Create a new timestamp transaction template

        The transaction created will have one input and two outputs, with the
        timestamp output set to an invalid dummy.

        The fee is set to zero, but nSequence is set to opt-in to transaction
        replacement, so you can find an appropriate fee iteratively.
        """

        return CTransaction([CTxIn(outpoint, nSequence=0xfffffffd)],
                            [CTxOut(txout_value, change_scriptPubKey),
                             CTxOut(-1, CScript())])

    def __update_timestamp_tx(self, old_tx, new_commitment, new_min_block_height, relay_feerate):
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
                     (b2lx(confirmed_tx.tx.GetHash()),
                      len(confirmed_tx.commitment_timestamps)))

    def __do_bitcoin(self):
        """Do Bitcoin-related maintenance"""

        # FIXME: we shouldn't have to create a new proxy each time, but with
        # current python-bitcoinlib and the RPC implementation it seems that
        # the proxy connection can timeout w/o recovering properly.
        proxy = bitcoin.rpc.Proxy()

        new_blocks = self.known_blocks.update_from_proxy(proxy)

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
                logging.info('tx %s at height %d removed by reorg, adding %d commitments back to pending' % (b2lx(reorged_tx.tx.GetHash()), block_height, len(reorged_tx.commitment_timestamps)))
                for reorged_commitment_timestamp in reorged_tx.commitment_timestamps:
                    self.pending_commitments.add(reorged_commitment_timestamp.msg)

            # Check if this block contains any of the pending transactions

            try:
                block = proxy.getblock(block_hash)
            except KeyError:
                # Must have been a reorg or something, return
                logging.error("Failed to get block")
                return

            # Check all potential pending txs against this block.
            for tx in self.unconfirmed_txs:
                block_timestamp = make_timestamp_from_block(tx.tip_timestamp.msg, block, block_height)

                if block_timestamp is None:
                    continue

                # Success!
                tx.tip_timestamp.merge(block_timestamp)

                for commitment_timestamp in tx.commitment_timestamps:
                    self.pending_commitments.remove(commitment_timestamp.msg)
                    logging.debug("Removed commitment %s from pending" % b2x(commitment_timestamp.msg))

                assert self.min_confirmations > 1
                logging.info("Success! %d commitments timestamped, now waiting for %d more confirmations" %
                             (len(tx.commitment_timestamps), self.min_confirmations - 1))

                # Add pending_tx to the list of timestamp transactions that
                # have been mined, and are waiting for confirmations.
                self.txs_waiting_for_confirmation[block_height] = tx

                # Since all unconfirmed txs conflict with each other, we can clear the entire lot
                self.unconfirmed_txs.clear()

                # And finally, we can reset the last time a timestamp
                # transaction was mined to right now.
                self.last_timestamp_tx = time.time()


        time_to_next_tx = int(self.last_timestamp_tx + self.min_tx_interval - time.time())
        if time_to_next_tx > 0:
            # Minimum interval between transactions hasn't been reached, so do nothing
            logging.debug("Waiting %ds before next tx" % time_to_next_tx)
            return

        prev_tx = None
        if self.pending_commitments and not self.unconfirmed_txs:
            # Find the biggest unspent output that's confirmed
            unspent = find_unspent(proxy)

            if not len(unspent):
                logging.error("Can't timestamp; no spendable outputs")
                return

            # For the change scriptPubKey, we can save a few bytes by using
            # a pay-to-pubkey rather than the usual pay-to-pubkeyhash
            change_addr = proxy.getnewaddress()
            change_pubkey = proxy.validateaddress(change_addr)['pubkey']
            change_scriptPubKey = CScript([change_pubkey, OP_CHECKSIG])

            prev_tx = self.__create_new_timestamp_tx_template(unspent[-1]['outpoint'], unspent[-1]['amount'], change_scriptPubKey)

            logging.debug('New timestamp tx, spending output %r, value %s' % (unspent[-1]['outpoint'], str_money_value(unspent[-1]['amount'])))

        elif self.unconfirmed_txs:
            (prev_tx, prev_tip_timestamp, prev_commitment_timestamps) = self.unconfirmed_txs[-1]

        # Send the first transaction even if we don't have a new block
        if prev_tx and (new_blocks or not self.unconfirmed_txs):
            # Update the most recent timestamp transaction with new commitments
            commitment_timestamps = [Timestamp(commitment) for commitment in self.pending_commitments]

            # Remember that commitment_timestamps contains raw commitments,
            # which are longer than necessary, so we sha256 them before passing
            # them to make_merkle_tree, which concatenates whatever it gets (or
            # for the matter, returns what it gets if there's only one item for
            # the tree!)
            commitment_digest_timestamps = [stamp.ops.add(OpSHA256()) for stamp in commitment_timestamps]

            logging.debug("Making merkle tree")
            tip_timestamp = make_merkle_tree(commitment_digest_timestamps)
            logging.debug("Done making merkle tree")

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

                r = proxy.signrawtransaction(unsigned_tx)
                if not r['complete']:
                    logging.error("Failed to sign transaction! r = %r" % r)
                    return
                signed_tx = r['tx']

                try:
                    txid = proxy.sendrawtransaction(signed_tx)
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
                logging.info("Sent timestamp tx %s, replacing %s; %d total commitments" % (b2lx(sent_tx.GetHash()), b2lx(prev_tx.GetHash()), len(commitment_timestamps)))
            else:
                logging.info("Sent timestamp tx %s; %d total commitments" % (b2lx(sent_tx.GetHash()), len(commitment_timestamps)))

            self.unconfirmed_txs.append(TimestampTx(sent_tx, tip_timestamp, commitment_timestamps))

    def __loop(self):
        logging.info("Starting stamper loop")

        journal = Journal(self.calendar.path + '/journal')

        try:
            with open(self.calendar.path + '/journal.known-good', 'r') as known_good_fd:
                idx = int(known_good_fd.read().strip())
        except FileNotFoundError as exp:
            idx = 0

        while not self.exit_event.is_set():
            try:
                self.__do_bitcoin()
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
                logging.error("__do_bitcoin() failed: %r" % exp)

            try:
                commitment = journal[idx]
            except KeyError:
                self.exit_event.wait(1)
                continue

            # Is this commitment already stamped?
            if commitment in self.calendar:
                logging.debug('Commitment %s (idx %d) already stamped' % (b2x(commitment), idx))
                idx += 1
                continue

            elif len(self.pending_commitments) < self.max_pending:
                self.pending_commitments.add(commitment)
                logging.debug('Added %s (idx %d) to pending commitments; %d total' % (b2x(commitment), idx, len(self.pending_commitments)))

                idx += 1

            else:
                # Ensure we don't busy-loop
                time.sleep(1)

    def is_pending(self, commitment):
        """Return whether or not a commitment is waiting to be stamped

        Returns False if not, or str reason if it is
        """
        if commitment in self.pending_commitments:
            return "Pending confirmation in Bitcoin blockchain"

        else:
            for height, ttx in self.txs_waiting_for_confirmation.items():
               for commitment_timestamp in ttx.commitment_timestamps:
                    if commitment == commitment_timestamp.msg:
                        return "Timestamped by transaction %s; waiting for %d confirmations" % (b2lx(ttx.tx.GetHash()), self.min_confirmations)

            else:
                return False

    def __init__(self, calendar, exit_event, relay_feerate, min_confirmations, min_tx_interval, max_fee, max_pending):
        self.calendar = calendar
        self.exit_event = exit_event

        self.relay_feerate = relay_feerate
        self.min_confirmations = min_confirmations
        assert self.min_confirmations > 0
        self.min_tx_interval = min_tx_interval
        self.max_fee = max_fee
        self.max_pending = max_pending

        self.known_blocks = KnownBlocks()
        self.unconfirmed_txs = []
        self.pending_commitments = set()
        self.txs_waiting_for_confirmation = {}

        self.last_timestamp_tx = 0

        self.thread = threading.Thread(target=self.__loop)
        self.thread.start()
