# -*- coding: utf-8 -*-
"""NVDA's `scriptHandler`: the @script decorator and repeat counts."""

import time

_last = {'script': None, 'at': 0.0, 'count': 0}


def script(description='', category=None, gesture=None, gestures=None,
           canPropagate=False, bypassInputHelp=False, allowInSleepMode=False,
           resumeSayAllMode=None, speakOnDemand=False):
    def wrap(func):
        func.__doc__ = description or func.__doc__
        func.category = category
        found = list(gestures or ())
        if gesture:
            found.append(gesture)
        func.gestures = found
        func.canPropagate = canPropagate
        func.speakOnDemand = speakOnDemand
        return func
    return wrap


def _ran(func):
    now = time.time()
    if _last['script'] == func and now - _last['at'] < 0.5:
        _last['count'] += 1
    else:
        _last['count'] = 0
    _last['script'], _last['at'] = func, now


def getLastScriptRepeatCount():
    return _last['count']


def isScriptWaiting():
    return False


def executeScript(script, gesture):
    _ran(getattr(script, '__func__', script))
    return script(gesture)


def getCurrentScript():
    return _last['script']


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
