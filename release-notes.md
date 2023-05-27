# OpenTimestamps Server Release Notes

## v0.7.0

* `python-bitcoinlib` >= 0.12.1 is now required; previously 0.12.0 was allowed.
* BREAKING CHANGE: `--btc-min-relay-feerate` is now denominated in sat/vB.
* Fixed fee calculation to properly take segwit discount into account.
* New `--btc-conf-target` option, to allow Bitcoin Core's fee estimation to be
  used for the first tx in a round.
* Balance now shows confirmed coins only to avoid confusion when there are
  unconfirmed transactions tying up coins.

## v0.6.0

* Now compatible with Bitcoin Core v24.0
* Improved stats display

Due to the removal of `getaccountaddress` a fixed donation address is now used.

## v0.5.0

* Increased max tx fee to account for current conditions
* Added QR code for donation address
* Added Lightning donations
* Added JSON format stats
* Improved stats display

## v0.4.0

* bech32 address support
* Better status page wording
* Various bugfixes

## v0.3.0

* Experimental calendar backup scheme

## v0.2.1

* More informative status page, with stats on latest txs, time between txs, and
  fees
* Better recovery for Bitcoin RPC failures
* Increased default minimum between txs to 1 hour
* Stricter conditions on what txs we add to the calendar

## v0.2.0

* Replaced `python-opentimestamps` subtree with proper dependency
* Removed pay-to-bare-pubkey hack for v0.16.0's segwit support
* Other bugfixes

## v0.1.1 & v0.1.2

FIXME: Forgot to write release notes!


## v0.1.0

First version with an actual version number.
