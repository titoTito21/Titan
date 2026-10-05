# -*- coding: utf-8 -*-
"""NVDA's `baseObject`: an object whose ``_get_x`` / ``_set_x`` methods
are the property ``x`` - which is how every NVDA synthesizer, object and
plugin is written - and `ScriptableObject`, whose ``script_*`` methods
are bound to gestures."""


import abc


class _AutoPropertyType(abc.ABCMeta):
    def __init__(cls, name, bases, namespace):
        super().__init__(name, bases, namespace)
        props = set()
        for key in namespace:
            for prefix in ('_get_', '_set_'):
                if key.startswith(prefix):
                    props.add(key[len(prefix):])
        for prop in props:
            getter = getattr(cls, '_get_' + prop, None)
            setter = getattr(cls, '_set_' + prop, None)
            if isinstance(namespace.get(prop), property):
                continue

            def make(prop=prop):
                def fget(self):
                    found = getattr(type(self), '_get_' + prop, None)
                    if found is None:
                        raise AttributeError(prop)
                    return found(self)

                def fset(self, value):
                    found = getattr(type(self), '_set_' + prop, None)
                    if found is None:
                        raise AttributeError("can't set " + prop)
                    found(self, value)
                return property(fget, fset if setter or
                                any(hasattr(base, '_set_' + prop)
                                    for base in cls.__mro__) else None)
            if getter is not None or setter is not None:
                setattr(cls, prop, make())


class AutoPropertyObject(metaclass=_AutoPropertyType):
    cachePropertiesByDefault = False

    def invalidateCache(self):
        pass

    @classmethod
    def invalidateCaches(cls):
        pass


class ScriptableType(_AutoPropertyType):
    def __init__(cls, name, bases, namespace):
        super().__init__(name, bases, namespace)
        gestures = {}
        for base in reversed(cls.__mro__[1:]):
            gestures.update(getattr(base, '_ScriptableObject__gestures', {})
                            or {})
        own = namespace.get('_%s__gestures' % name) or {}
        gestures.update(own)
        for key, value in namespace.items():
            for gesture in getattr(value, 'gestures', None) or ():
                if key.startswith('script_'):
                    gestures[gesture] = key[len('script_'):]
        cls._ScriptableObject__gestures = gestures


class ScriptableObject(AutoPropertyObject, metaclass=ScriptableType):
    def __init__(self):
        self._gestureMap = {}
        for gesture, script in (getattr(type(self),
                                        '_ScriptableObject__gestures', {})
                                or {}).items():
            self.bindGesture(gesture, script)

    def bindGesture(self, gestureIdentifier, scriptName):
        if not hasattr(self, '_gestureMap'):
            self._gestureMap = {}
        self._gestureMap[str(gestureIdentifier).lower()] = scriptName

    def bindGestures(self, gestureMap):
        for gesture, script in (gestureMap or {}).items():
            self.bindGesture(gesture, script)

    def removeGestureBinding(self, gestureIdentifier):
        getattr(self, '_gestureMap', {}).pop(str(gestureIdentifier).lower(),
                                             None)

    def clearGestureBindings(self):
        self._gestureMap = {}

    def getScript(self, gesture):
        for identifier in getattr(gesture, 'normalizedIdentifiers', ()):
            name = getattr(self, '_gestureMap', {}).get(identifier)
            if name:
                return getattr(self, 'script_' + name, None)
        return None


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
