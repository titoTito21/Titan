# -*- coding: utf-8 -*-
"""NVDA's `extensionPoints`: Action, Filter, Decider, AccumulatingDecider
and Chain - handlers registered and notified, with weak references so an
add-on that goes away takes its handlers with it."""

import weakref


class _Handlers(object):
    def __init__(self):
        self._handlers = []

    def register(self, handler):
        try:
            ref = weakref.WeakMethod(handler)
        except TypeError:
            ref = (lambda handler=handler: handler)
        self._handlers.append(ref)

    def unregister(self, handler):
        self._handlers = [ref for ref in self._handlers
                          if ref() is not None and ref() != handler]
        return True

    def handlers(self):
        for ref in list(self._handlers):
            found = ref()
            if found is not None:
                yield found

    def __bool__(self):
        return any(True for _one in self.handlers())

    @staticmethod
    def _call(handler, **kwargs):
        try:
            return handler(**kwargs)
        except TypeError:
            import inspect
            try:
                names = inspect.signature(handler).parameters
            except (TypeError, ValueError):
                raise
            wanted = {key: value for key, value in kwargs.items()
                      if key in names}
            return handler(**wanted)


class Action(_Handlers):
    def notify(self, **kwargs):
        for handler in self.handlers():
            try:
                self._call(handler, **kwargs)
            except Exception:                        # noqa: BLE001
                from .logHandler import log
                log.exception('extension point handler failed')

    notifyOnce = notify


class Filter(_Handlers):
    def apply(self, value, **kwargs):
        for handler in self.handlers():
            try:
                value = self._call(handler, value=value, **kwargs)
            except Exception:                        # noqa: BLE001
                pass
        return value


class Decider(_Handlers):
    def decide(self, **kwargs):
        for handler in self.handlers():
            try:
                if not self._call(handler, **kwargs):
                    return False
            except Exception:                        # noqa: BLE001
                pass
        return True


class AccumulatingDecider(Decider):
    def __init__(self, defaultDecision=True):
        super().__init__()
        self.defaultDecision = defaultDecision

    def decide(self, **kwargs):
        for handler in self.handlers():
            try:
                if self._call(handler, **kwargs) != self.defaultDecision:
                    return not self.defaultDecision
            except Exception:                        # noqa: BLE001
                pass
        return self.defaultDecision


class Chain(_Handlers):
    def iter(self, **kwargs):
        for handler in self.handlers():
            try:
                yield from self._call(handler, **kwargs)
            except Exception:                        # noqa: BLE001
                pass


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
