# -*- coding: utf-8 -*-
"""Run something a moment from now, without making a thread for it.

The reader used to start a `threading.Timer` - a whole new thread - for
every container that took the focus, every arrow key in a virtual
machine's window and every Space on a check box, and it did so on its OWN
thread. Starting a thread waits until that thread has really started, and
on a busy machine that wait was measured in the reader's log at over four
seconds, twice, with the worker stuck in ``Thread.start()`` until the
supervisor said it had stopped answering. One scheduler thread, made once
and reused, costs a lock and a notify per job.

What runs here must be quick: a job is called on the scheduler's thread,
so anything that reads an element goes back to the reader's own thread
(`engine.post_to_worker`) - which is what every caller does.
"""

import heapq
import itertools
import threading
import time

try:
    from .log import log
except Exception:                                    # noqa: BLE001
    def log(message):
        print(message)

_lock = threading.Condition()
_jobs = []                       # (when, order, fn)
_order = itertools.count()
_thread = None


def _loop():
    while True:
        with _lock:
            while not _jobs:
                _lock.wait()
            when, _n, fn = _jobs[0]
            delay = when - time.monotonic()
            if delay > 0:
                _lock.wait(delay)
                continue
            heapq.heappop(_jobs)
        try:
            fn()
        except Exception as error:                   # noqa: BLE001
            log(f"[TitanAccess] a deferred job failed: {error}")


def call_later(delay, fn):
    """Call ``fn()`` in ``delay`` seconds on the one scheduler thread."""
    global _thread
    with _lock:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_loop, daemon=True,
                                       name='TitanAccessLater')
            _thread.start()
        heapq.heappush(_jobs, (time.monotonic() + max(0.0, float(delay)),
                               next(_order), fn))
        _lock.notify()


def pending():
    """How many jobs are waiting (for diagnostics and tests)."""
    with _lock:
        return len(_jobs)
