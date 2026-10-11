# -*- coding: utf-8 -*-
"""Inside TCE only Titan Access speaks; outside it, only NVDA.

Titan Access has a setting, "Mute outside TCE": with it on, Titan's own
reader keeps quiet - and lets go of the keyboard - whenever the window in
front is not Titan's, so the system's screen reader reads the rest of the
machine as it always has. That is half of the arrangement. The other half
is NVDA keeping quiet INSIDE TCE, or every control there is read twice, in
two voices, by two readers that interrupt each other.

NVDA already has exactly the thing for a program that speaks for itself:
**sleep mode** (NVDA+shift+s), per application. A sleeping application
gets no events from NVDA and its keys pass straight through. So this asks
Titan Access (`titan_access.reader_policy`) whether it is reading TCE
alone and which processes TCE is, and puts NVDA to sleep in exactly those
- and wakes them again the moment Titan Access stops, the setting is
turned off, or Titan goes away.

- **Only what this put to sleep is ever woken.** An application the user
  put to sleep themselves is left as it is, and one the user WOKE with
  NVDA+shift+s while Titan Access was reading it is not put back to sleep
  for as long as that process lives: the user has answered.
- **NVDA's own process is never TCE**, even when Titan started NVDA (it is
  then a child of Titan's and would be in the list).
- Asked on a thread, every :data:`POLL_SECONDS`; the appModules are
  touched on NVDA's main thread, through its queue.
"""

import json
import os
import threading
import time

from . import compat

#: How often Titan Access is asked. A bridge call is a pipe round trip.
POLL_SECONDS = 1.5

_LOCK = threading.Lock()
#: pid -> the appModule this put to sleep.
_slept = {}
#: pids whose sleep the user took back; not touched again.
_woken_by_user = set()
_state = {'reads_alone': False, 'pids': frozenset(), 'asked': 0.0,
          'why': 'not asked yet', 'slept': 0, 'woken': 0}
_stop = threading.Event()
_thread = None


def _app_modules():
    try:
        import appModuleHandler
        return appModuleHandler
    except Exception:                                # noqa: BLE001
        return None


def _parse(text):
    """The policy out of the action's answer, or None."""
    try:
        found = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(found, dict):
        return None
    pids = set()
    for pid in found.get('tce_pids') or []:
        try:
            pids.add(int(pid))
        except (TypeError, ValueError):
            continue
    pids.discard(os.getpid())
    return {'reads_alone': bool(found.get('reads_tce_alone')),
            'pids': frozenset(pids)}


def wanted_pids(policy):
    if not policy or not policy.get('reads_alone'):
        return frozenset()
    return policy['pids']


def apply(policy, modules=None):
    """Sleep in the TCE processes and wake what is no longer one. On NVDA's
    main thread (or a test's). ``modules`` is `appModuleHandler`."""
    modules = modules if modules is not None else _app_modules()
    wanted = wanted_pids(policy)
    with _LOCK:
        _state['reads_alone'] = bool(policy and policy.get('reads_alone'))
        _state['pids'] = wanted
        for pid in list(_slept):
            module = _slept[pid]
            if pid in wanted and getattr(module, 'sleepMode', False):
                continue
            del _slept[pid]
            if pid in wanted:
                # Awake while still TCE: the user woke it. Theirs now.
                _woken_by_user.add(pid)
                continue
            try:
                if getattr(module, 'sleepMode', False):
                    module.sleepMode = False
                    _state['woken'] += 1
            except Exception:                        # noqa: BLE001
                pass
        _woken_by_user.intersection_update(wanted)
        if modules is None:
            return len(_slept)
        for pid in wanted:
            if pid in _slept or pid in _woken_by_user:
                continue
            try:
                module = modules.getAppModuleFromProcessID(pid)
            except Exception:                        # noqa: BLE001
                continue
            if module is None or getattr(module, 'sleepMode', False):
                # Asleep already, by the user's own hand: not ours.
                continue
            try:
                module.sleepMode = True
                _slept[pid] = module
                _state['slept'] += 1
            except Exception:                        # noqa: BLE001
                continue
        return len(_slept)


def covers(obj):
    """Whether ``obj`` is in a process Titan Access is reading alone - for
    the first event of a window that appeared between two polls."""
    try:
        pid = int(getattr(obj, 'processID', 0) or 0)
    except (TypeError, ValueError):
        return False
    with _LOCK:
        return bool(pid) and pid in _state['pids'] and \
            pid not in _woken_by_user


def sleep_now(obj):
    """Put ``obj``'s application to sleep at once (on the main thread,
    from an event). True when it is asleep afterwards."""
    if not covers(obj):
        return False
    module = getattr(obj, 'appModule', None)
    if module is None:
        return False
    try:
        if not module.sleepMode:
            module.sleepMode = True
            with _LOCK:
                _slept[int(obj.processID)] = module
                _state['slept'] += 1
        return True
    except Exception:                                # noqa: BLE001
        return False


def wake_all():
    return apply({'reads_alone': False, 'pids': frozenset()})


def _on_main(function, *args):
    queue = compat.queueHandler
    if queue is None:
        function(*args)
        return
    try:
        queue.queueFunction(queue.eventQueue, function, *args)
    except Exception:                                # noqa: BLE001
        pass


def ask():
    """Titan Access's policy now, or None when it cannot be asked."""
    try:
        from .link import LINK
        if not LINK.connected():
            with _LOCK:
                _state['why'] = 'Titan is not connected'
            return None
        ok, text = LINK.run_action('titan_access', 'reader_policy',
                                   timeout=4.0)
    except Exception as error:                       # noqa: BLE001
        with _LOCK:
            _state['why'] = 'asking raised: %s' % error
        return None
    if not ok:
        with _LOCK:
            _state['why'] = 'Titan Access did not answer: %s' % text
        return None
    policy = _parse(text)
    with _LOCK:
        _state['asked'] = time.time()
        _state['why'] = '' if policy is not None else 'an answer nobody can read'
    return policy


def _loop():
    while not _stop.wait(POLL_SECONDS):
        policy = ask()
        if policy is None:
            policy = {'reads_alone': False, 'pids': frozenset()}
        with _LOCK:
            idle = not wanted_pids(policy) and not _slept and \
                not _state['pids']
        if not idle:
            # Idempotent and cheap: a loaded appModule is a dict lookup.
            _on_main(apply, policy)


def start():
    global _thread
    _stop.clear()
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_loop, name='TitanTceSleep',
                                   daemon=True)
        _thread.start()
    return True


def stop():
    """Stop asking and wake everything this put to sleep."""
    _stop.set()
    try:
        wake_all()
    except Exception:                                # noqa: BLE001
        pass


def report():
    with _LOCK:
        return {'reads_alone': _state['reads_alone'],
                'pids': sorted(_state['pids']), 'asleep': sorted(_slept),
                'woken_by_user': sorted(_woken_by_user),
                'slept': _state['slept'], 'woken': _state['woken'],
                'why': _state['why'], 'asked': _state['asked']}
