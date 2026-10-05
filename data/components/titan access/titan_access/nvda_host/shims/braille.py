# -*- coding: utf-8 -*-
"""NVDA's `braille`: messages and the handler, to Titan Access's display."""


class _Handler(object):
    enabled = False
    displaySize = 0

    def message(self, text):
        try:
            from titan_access.engine import get_engine
            braille = getattr(get_engine(), 'braille', None)
            if braille is not None and hasattr(braille, 'message'):
                braille.message(str(text))
        except Exception:                            # noqa: BLE001
            pass

    def handleGainFocus(self, obj):
        pass

    def handleUpdate(self, obj):
        pass

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


handler = _Handler()


def getPropertiesBraille(**propertyValues):
    return ' '.join(str(value) for value in propertyValues.values() if value)


class BrailleDisplayDriver(object):
    name = ''
    description = ''
    numCells = 0

    @classmethod
    def check(cls):
        return False


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
