# -*- coding: utf-8 -*-
"""NVDA's `eventHandler`."""


def queueEvent(eventName, obj, **kwargs):
    from titan_access import nvda_host
    nvda_host.fire_event(eventName, obj)


def executeEvent(eventName, obj, **kwargs):
    from titan_access import nvda_host
    nvda_host.fire_event(eventName, obj)


def isPendingEvents(eventName=None, obj=None):
    return False


lastQueuedFocusObject = None


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
