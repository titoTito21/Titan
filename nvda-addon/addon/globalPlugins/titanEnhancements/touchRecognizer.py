# -*- coding: utf-8 -*-
"""Taps, double taps, flicks and hovers out of raw contacts - for a reader
that has no NVDA tracker underneath it.

:mod:`trackpad` reads the pad and, in NVDA, hands every contact to NVDA's
own `touchTracker`, whose recogniser turns them into the gestures NVDA's
scripts are written for. Titan Access has no such tracker, so the same
contacts went in and nothing came out: the pad could be switched on and
did nothing. This is the other end for that reader - a small recogniser
that speaks the same vocabulary (``tap``, ``double_tap``, ``flickleft``,
``2finger_flickup``, ``hover``), so :mod:`touchWalk` and everything
written against NVDA's names works unchanged.

The rules are NVDA's own, in round numbers: a touch that moved less than
:data:`TAP_MAX` pixels and lasted under :data:`TAP_TIME` is a tap, two of
them inside :data:`DOUBLE_TIME` a double tap (the first is held back that
long, which is what makes a double tap possible at all); a touch that
moved more than :data:`FLICK_MIN` and lasted under :data:`FLICK_TIME` is a
flick along its dominant axis; one finger that is down and moving is a
hover, said at most every :data:`HOVER_EVERY` seconds; and the finger
count of a gesture is the MOST fingers that were down during it, so a
three-finger flick whose fingers lift one by one is still three.
"""

import threading
import time

TAP_MAX = 25
TAP_TIME = 0.45
DOUBLE_TIME = 0.35
FLICK_MIN = 50
FLICK_TIME = 0.7
HOVER_EVERY = 0.04
HOVER_MOVE = 6

_LOCK = threading.RLock()
_state = {'down': {}, 'start': None, 'fingers': 0, 'last_tap': 0.0,
          'pending': None, 'hovered_at': 0.0, 'hovered': None,
          'emitted': 0, 'last': ''}

#: Where a recognised gesture goes: ``listener(action, x, y)``. Set by
#: whoever drives this reader; None means recognised and dropped.
listener = None


def report():
    with _LOCK:
        return {'emitted': _state['emitted'], 'last': _state['last'],
                'fingers_down': len(_state['down'])}


def forget():
    with _LOCK:
        pending = _state.get('pending')
        _state.update({'down': {}, 'start': None, 'fingers': 0,
                       'last_tap': 0.0, 'pending': None, 'hovered_at': 0.0,
                       'hovered': None, 'emitted': 0, 'last': ''})
    if pending is not None:
        try:
            pending.cancel()
        except Exception:                            # noqa: BLE001
            pass


def _emit(action, x, y):
    with _LOCK:
        _state['emitted'] += 1
        _state['last'] = action
        found = listener
    if callable(found):
        try:
            found(action, int(x), int(y))
        except Exception:                            # noqa: BLE001
            pass


def _named(action, fingers):
    return action if fingers <= 1 else '%dfinger_%s' % (fingers, action)


def feed(contacts, now=None):
    """One report's worth of ``(identifier, x, y, down)``.

    A finger that was down and is not in this report has lifted (the pad
    stops mentioning it rather than announcing its end).
    """
    now = time.time() if now is None else float(now)
    seen = set()
    with _LOCK:
        down = _state['down']
        for identifier, x, y, is_down in contacts:
            seen.add(identifier)
            if is_down:
                if identifier not in down:
                    down[identifier] = {'x0': x, 'y0': y, 'x': x, 'y': y,
                                        't0': now}
                    if _state['start'] is None:
                        _state['start'] = now
                        _state['fingers'] = 0
                else:
                    down[identifier]['x'] = x
                    down[identifier]['y'] = y
            else:
                down.pop(identifier, None)
        for gone in [one for one in down if one not in seen]:
            down.pop(gone, None)
        _state['fingers'] = max(_state['fingers'], len(down))
        if len(down) == 1 and _state['fingers'] == 1:
            only = next(iter(down.values()))
            _hover(only, now)
        if not down and _state['start'] is not None:
            # Everything has lifted: decide what the touch was.
            fingers = _state['fingers'] or 1
            first = _state.get('first')
            started = _state['start']
            _state['start'] = None
            _state['fingers'] = 0
            _state['hovered'] = None
            if first is None:
                return
            _state['first'] = None
            _decide(first, fingers, now - started, now)
            return
        if down and _state.get('first') is None:
            _state['first'] = dict(next(iter(down.values())))
        elif down:
            # Keep the first finger's latest position for the flick.
            for one in down.values():
                if (one['x0'], one['y0']) == (_state['first']['x0'],
                                              _state['first']['y0']):
                    _state['first']['x'] = one['x']
                    _state['first']['y'] = one['y']


def _hover(finger, now):
    """One finger, down and moving: say what is under it, not too often."""
    x, y = finger['x'], finger['y']
    last = _state.get('hovered')
    if last is not None and abs(last[0] - x) < HOVER_MOVE \
            and abs(last[1] - y) < HOVER_MOVE:
        return
    if now - _state['hovered_at'] < HOVER_EVERY:
        return
    if abs(finger['x0'] - x) < HOVER_MOVE and abs(finger['y0'] - y) < HOVER_MOVE:
        return                                        # not moved yet: a tap?
    _state['hovered'] = (x, y)
    _state['hovered_at'] = now
    _emit('hover', x, y)


def _decide(first, fingers, lasted, now):
    dx = first['x'] - first['x0']
    dy = first['y'] - first['y0']
    moved = max(abs(dx), abs(dy))
    if moved < TAP_MAX and lasted < TAP_TIME:
        _tap(fingers, first['x0'], first['y0'], now)
        return
    if moved >= FLICK_MIN and lasted < FLICK_TIME:
        if abs(dx) >= abs(dy):
            action = 'flickright' if dx > 0 else 'flickleft'
        else:
            action = 'flickdown' if dy > 0 else 'flickup'
        _emit(_named(action, fingers), first['x0'], first['y0'])


def _tap(fingers, x, y, now):
    pending = _state.get('pending')
    if pending is not None and now - _state['last_tap'] <= DOUBLE_TIME \
            and _state.get('pending_fingers') == fingers:
        try:
            pending.cancel()
        except Exception:                            # noqa: BLE001
            pass
        _state['pending'] = None
        _state['last_tap'] = 0.0
        _emit(_named('double_tap', fingers), x, y)
        return
    _state['last_tap'] = now
    _state['pending_fingers'] = fingers
    _state['tap_at'] = (x, y)

    def single():
        with _LOCK:
            if _state.get('pending') is not timer:
                return
            _state['pending'] = None
        _emit(_named('tap', fingers), x, y)
    timer = threading.Timer(DOUBLE_TIME, single)
    timer.daemon = True
    _state['pending'] = timer
    timer.start()


def settle():
    """For a test: fire the tap that is waiting, without waiting."""
    with _LOCK:
        timer = _state.get('pending')
        fingers = _state.get('pending_fingers', 1)
        _state['pending'] = None
    if timer is None:
        return False
    try:
        timer.cancel()
    except Exception:                                # noqa: BLE001
        pass
    x, y = _state.get('tap_at', (0, 0))
    _emit(_named('tap', fingers), x, y)
    return True
