#!/usr/bin/env python3

import binascii
import concurrent.futures
import internetarchive
import os
import time
import sys

from datetime import datetime,date,timedelta

MAX_WORKERS = 200

TARGET_DIR = "per-date"

def get_sha1_hashes(item_ident):
    for i in range(10):
        try:
            print("get_sha1_hashes(%r)" % item_ident)
            ia = internetarchive.get_session()
            item = ia.get_item(item_ident)
            return [binascii.unhexlify(r['sha1']) for r in item.files if 'sha1' in r]

        except Exception as exp:
            print("failed at %r: %r" % (item_ident, exp))
            time.sleep(1)
    print("failed (gave up) at %r" % item_ident)
    return []

ia = internetarchive.get_session()

t = datetime.strptime(sys.argv[1], "%Y-%m-%d")
t_end = datetime.strptime(sys.argv[2], "%Y-%m-%d")

with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
    while t < t_end:
        try:
            print(t)
            print("addeddate:{:%Y-%m-%d}".format(t))

            item_idents = [r['identifier'] for r in ia.search_items("addeddate:{:%Y-%m-%d}".format(t))]

            results = pool.map(get_sha1_hashes, item_idents)

            per_date_dir = "{}/{:%Y}".format(TARGET_DIR, t)
            os.makedirs(per_date_dir, exist_ok=True)
            per_date_file = "{}/{:%Y-%m-%d}".format(per_date_dir, t)
            with open(per_date_file + ".pending", "wb") as f:
                for digests in results:
                    for digest in digests:
                        f.write(digest)
            os.rename(per_date_file + ".pending", per_date_file)
            print("done %s" % per_date_file)
        except Exception as exp:
            print(exp)
            time.sleep(10)
            continue

        t += timedelta(days=1)

# vim:syntax=python filetype=python
