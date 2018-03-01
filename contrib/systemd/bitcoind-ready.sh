#/bin/bash
until /usr/local/bin/bitcoin-cli getblockchaininfo
do
  /bin/sleep 3
done