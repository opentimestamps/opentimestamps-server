#!/usr/bin/env python3
# Copyright (C) 2018 The OpenTimestamps developers
#
# This file is part of the OpenTimestamps Server.
#
# It is subject to the license terms in the LICENSE file found in the top-level
# directory of this distribution.
#
# No part of the OpenTimestamps Server, including this file, may be copied,
# modified, propagated, or distributed except according to the terms contained
# in the LICENSE file.

import argparse
import logging.handlers
import os
import sys
import otsserver.calendar
import otsserver.backup

parser = argparse.ArgumentParser(description="OpenTimestamps Backup Server")

parser.add_argument("-q", "--quiet", action="count", default=0,
                    help="Be more quiet.")
parser.add_argument("-v", "--verbose", action="count", default=0,
                    help="Be more verbose. Both -v and -q may be used multiple times.")
parser.add_argument("-p", "--path", type=str,
                    dest='base_path',
                    default='~/.otsd/backups',
                    help="Location of the calendar (default: '%(default)s')")

parser.add_argument('-c', '--calendar', metavar='calendar', action='append', type=str,
                    default=[], help='Add a calendar URL to the ones to backup.')

parser.add_argument("--debug-file", type=str,
                    dest='debug_file',
                    default='~/.otsd/backups/debug.log',
                    help="Location of the debug log")
parser.add_argument("--debug-file-max-size", type=int,
                    dest='debug_file_max_size',
                    default=10000000,
                    help="Max size of the debug log (default: %(default)d bytes) ")

parser.add_argument("--rpc-port", type=int,
                    default=14799,
                    help="RPC port (default: %(default)d)")
parser.add_argument("--rpc-address", type=str,
                    default='localhost',
                    help="RPC address (default: %(default)s)")

parser.add_argument('--btc-testnet', dest='btc_net', action='store_const',
                    const='testnet', default='mainnet',
                    help='Use Bitcoin testnet rather than mainnet')
parser.add_argument('--btc-regtest', dest='btc_net', action='store_const',
                    const='regtest',
                    help='Use Bitcoin regtest rather than mainnet')

args = parser.parse_args()
args.parser = parser

base_path = os.path.expanduser(args.base_path)
os.makedirs(base_path, exist_ok=True)
db_dir = base_path + '/db'
os.makedirs(db_dir, exist_ok=True)
print("db dir is %s" % db_dir)

debugfile = os.path.expanduser(args.debug_file)
handler = logging.handlers.RotatingFileHandler(filename=debugfile, maxBytes=args.debug_file_max_size)
fmt = logging.Formatter("%(asctime)-15s %(message)s")
handler.setFormatter(fmt)
logger = logging.getLogger('')
logger.addHandler(handler)
ch = logging.StreamHandler(sys.stdout)
logger.addHandler(ch)

args.verbosity = args.verbose - args.quiet

if args.verbosity == 0:
    logging.root.setLevel(logging.INFO)
elif args.verbosity > 0:
    logging.root.setLevel(logging.DEBUG)
elif args.verbosity == -1:
    logging.root.setLevel(logging.WARNING)
elif args.verbosity < -1:
    logging.root.setLevel(logging.ERROR)

db = otsserver.calendar.LevelDbCalendar(db_dir)
calendar = otsserver.backup.BackupCalendar(db)
server = otsserver.backup.BackupServer((args.rpc_address, args.rpc_port), calendar)

for calendar_url in args.calendar:
    print("Starting calendar checker for %s" % calendar_url)
    ask_thread = otsserver.backup.AskBackup(db, calendar_url, base_path, args.btc_net)
    ask_thread.start()

try:
    print("Starting at %s:%s" % (args.rpc_address, args.rpc_port))
    server.serve_forever()
except KeyboardInterrupt:
    sys.exit(0)

# vim:syntax=python filetype=python
