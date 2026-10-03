# -*- coding: utf-8 -*-
"""The reader watched, and put back when it stops answering.

The worker thread is where the reader lives on Windows: the UIA focus
events, every announcement, every posted callable. When it dies or
stalls, nothing else in the process notices - `running` stays True, the
host's calls report success, the hotkey "turns off" a reader already gone.
That is what "minimising TCE hangs the reader" was, and the fix for THAT
line is not a fix for the next one.

So the supervisor pings the worker every `EVERY` seconds and waits
`PATIENCE` for the answer. A thread that has died is restarted at once;
one that is alive and silent gets its Python stack written to the log
(`log.stacks`), and after `SILENT_LIMIT` silent pings in a row the engine
is torn down and started again. The user hears that it happened. The
background worker and the speech pump are checked the same way, and the
keyboard hook's own counters are logged so a hook Windows dropped can be
seen from the log.

On Linux the reader lives on the main thread (`engine._posix_start`): a
silent worker there is a blocked Titan, which no thread of ours can
restart, so the supervisor only writes down what it sees.
"""

import sys
import threading
import time

from titan_access.log import log, stacks

_IS_WINDOWS = sys.platform.startswith('win')

EVERY = 3.0
PATIENCE = 4.0
SILENT_LIMIT = 3
HOOK_LOG_EVERY = 120.0


class Supervisor(object):

    def __init__(self, engine, every=EVERY, patience=PATIENCE,
                 silent_limit=SILENT_LIMIT, restart=None):
        self.engine = engine
        self.every = float(every)
        self.patience = float(patience)
        self.silent_limit = int(silent_limit)
        self._restart = restart or self._restart_engine
        self._stop = threading.Event()
        self._thread = None
        self.counts = {'pings': 0, 'answered': 0, 'silent': 0, 'restarts': 0,
                       'dead': 0, 'bg_restarted': 0}
        self._silent_run = 0
        self._last_hook_log = 0.0
        self.last_answer_s = None

    # ------------------------------------------------------------------ #
    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name='TitanAccessSupervisor',
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def report(self):
        found = dict(self.counts)
        found['last_answer_s'] = self.last_answer_s
        found['silent_run'] = self._silent_run
        return found

    # ------------------------------------------------------------------ #
    def _loop(self):
        while not self._stop.wait(self.every):
            try:
                self.check_once()
            except Exception as error:               # noqa: BLE001
                log('[TitanAccess] supervisor: %s', error)

    def check_once(self):
        """One round: the worker pinged, the helpers checked. Returns what
        was found: 'ok', 'silent', 'dead' or 'restarted'."""
        engine = self.engine
        if not getattr(engine, 'running', False):
            return 'stopped'
        worker = getattr(engine, '_thread', None)
        if _IS_WINDOWS and worker is not None and not worker.is_alive():
            self.counts['dead'] += 1
            log('[TitanAccess] supervisor: the worker thread is DEAD - restarting')
            return self._do_restart('dead')
        answered = self.ping()
        self.counts['pings'] += 1
        if answered:
            self.counts['answered'] += 1
            self._silent_run = 0
            self._check_helpers()
            self._log_hook()
            return 'ok'
        self.counts['silent'] += 1
        self._silent_run += 1
        log('[TitanAccess] supervisor: the worker did not answer in %.1fs '
            '(%d in a row)', self.patience, self._silent_run)
        try:
            names = [worker] if worker is not None else None
            log('[TitanAccess] supervisor: stacks:\n%s', stacks(names))
        except Exception:                            # noqa: BLE001
            pass
        if self._silent_run >= self.silent_limit:
            return self._do_restart('silent')
        return 'silent'

    def ping(self):
        done = threading.Event()
        t0 = time.time()
        try:
            self.engine.post_to_worker(done.set)
        except Exception as error:                   # noqa: BLE001
            log('[TitanAccess] supervisor: post failed: %s', error)
            return False
        ok = done.wait(self.patience)
        if ok:
            self.last_answer_s = round(time.time() - t0, 3)
        return ok

    def _check_helpers(self):
        engine = self.engine
        bg = getattr(engine, '_bg_thread', None)
        if getattr(engine, '_bg_alive', False) and bg is not None and not bg.is_alive():
            self.counts['bg_restarted'] += 1
            log('[TitanAccess] supervisor: the background worker died - restarting it')
            try:
                engine._bg_alive = False
                engine._start_bg_worker()
            except Exception as error:               # noqa: BLE001
                log('[TitanAccess] supervisor: bg restart: %s', error)

    def _log_hook(self):
        now = time.time()
        if now - self._last_hook_log < HOOK_LOG_EVERY:
            return
        self._last_hook_log = now
        keyboard = getattr(self.engine, 'keyboard', None)
        if keyboard is None or not hasattr(keyboard, 'native_status'):
            return
        try:
            found = keyboard.native_status()
        except Exception:                            # noqa: BLE001
            return
        if found.get('native'):
            log('[TitanAccess] hook: events %s late %s reinstalls %s longest %s ms',
                found.get('events'), found.get('late'), found.get('reinstalls'),
                found.get('longestWaitMs'))

    # ------------------------------------------------------------------ #
    def _do_restart(self, why):
        if not _IS_WINDOWS:
            log('[TitanAccess] supervisor: %s on the main thread - nothing to restart', why)
            return why
        self.counts['restarts'] += 1
        self._silent_run = 0
        try:
            self._restart(why)
        except Exception as error:                   # noqa: BLE001
            log('[TitanAccess] supervisor: restart failed: %s', error)
            return why
        return 'restarted'

    def _restart_engine(self, why):
        """Tear the engine down and start a fresh one in its place."""
        import ctypes
        from titan_access import engine as engine_module
        old = self.engine
        log('[TitanAccess] supervisor: restarting the reader (%s)', why)
        try:
            old.running = False
            if getattr(old, '_thread_id', 0):
                ctypes.windll.user32.PostThreadMessageW(old._thread_id, 0x0012, 0, 0)
            thread = getattr(old, '_thread', None)
            if thread is not None and thread.is_alive():
                thread.join(timeout=3.0)
            if thread is not None and thread.is_alive():
                # It will not leave: the subsystems are torn down from here
                # so the new engine does not hook twice.
                try:
                    old._teardown_subsystems()
                except Exception as error:           # noqa: BLE001
                    log('[TitanAccess] supervisor: teardown: %s', error)
        finally:
            engine_module.TitanAccessEngine.instance = None
        self.stop()
        fresh = engine_module.get_engine()
        fresh.start()
        try:
            from titan_access.localization import L
            fresh.speak(L('engine.restarted'))
        except Exception:                            # noqa: BLE001
            pass
        log('[TitanAccess] supervisor: the reader is back')
