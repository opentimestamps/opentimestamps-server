# Copyright (C) 2026 The OpenTimestamps developers
#
# This file is part of the OpenTimestamps Server.
#
# It is subject to the license terms in the LICENSE file found in the top-level
# directory of this distribution.
#
# No part of the OpenTimestamps Server including this file, may be copied,
# modified, propagated, or distributed except according to the terms contained
# in the LICENSE file.

"""Regression test for the stamper loop's ValueError handling.

Upstream 779e42c (2019-09-12) added `except ValueError as err:` to __loop but
logged `% exp` in the else-branch -- a name bound only by the sibling
`except Exception as exp:` handler (and, misleadingly, by an earlier
`except FileNotFoundError as exp:` whose binding PEP 3110 auto-deletes at
block exit). Any non-cookie ValueError from __do_bitcoin() -- e.g.
binascii.Error from lx() on a malformed RPC result -- therefore raised
UnboundLocalError inside the handler, escaped __loop, and killed the
anchoring thread while the HTTP server kept accepting digests.

On the pre-fix code this test fails twice over: the thread dies (is_alive
False) and nothing reaches logging.error (assertLogs sees no ERROR record --
the UnboundLocalError goes to the threading excepthook, not the log).
"""

import os
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

from otsserver.stamper import Stamper


class Test_stamper_loop_survives_valueerror(unittest.TestCase):
    def test_non_cookie_valueerror_is_logged_and_loop_survives(self):
        with tempfile.TemporaryDirectory() as cal_path:
            # Empty journal: Journal.__getitem__ raises KeyError immediately,
            # so the loop reaches __do_bitcoin with no pending commitments.
            # journal.known-good is deliberately absent: the FileNotFoundError
            # handler binds (then auto-deletes) `exp`, exercising exactly the
            # unbound-local shape of the original bug.
            open(os.path.join(cal_path, 'journal'), 'wb').close()

            calendar = types.SimpleNamespace(path=cal_path)
            exit_event = threading.Event()
            boom = ValueError("boom: not a cookie error")

            with mock.patch.object(Stamper, '_Stamper__do_bitcoin',
                                   side_effect=boom):
                try:
                    with self.assertLogs(level='ERROR') as captured:
                        stamper = Stamper(calendar, exit_event,
                                          conf_target=12,
                                          relay_feerate=1,
                                          min_confirmations=6,
                                          min_tx_interval=0,
                                          max_fee=1000000,
                                          max_pending=100)
                        # __loop waits 1s between iterations; give it time to
                        # hit the poisoned __do_bitcoin at least twice.
                        time.sleep(2.5)
                        alive = stamper.thread.is_alive()
                finally:
                    exit_event.set()
                    stamper.thread.join(5)

            self.assertTrue(
                alive,
                "stamper thread died inside the ValueError handler")
            self.assertTrue(
                any("__do_bitcoin() failed" in line and "boom" in line
                    for line in captured.output),
                captured.output)


if __name__ == "__main__":
    unittest.main()
