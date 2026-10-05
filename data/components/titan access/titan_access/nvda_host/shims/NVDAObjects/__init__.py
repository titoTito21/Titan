# -*- coding: utf-8 -*-
"""NVDA's `NVDAObjects`: the object classes an add-on subclasses or tests
with ``isinstance``. Titan Access's own objects (`nvda_shape.Adapted`)
are registered as virtual subclasses, so ``isinstance(obj, NVDAObject)``
is true of them."""

from ..baseObject import ScriptableObject


class NVDAObject(ScriptableObject):
    def __init__(self, *args, **kwargs):
        super().__init__()


def _register():
    try:
        from titan_access import nvda_shape
        NVDAObject.register(nvda_shape.Adapted)
    except Exception:                                # noqa: BLE001
        pass


_register()


from .. import permissive as _permissive  # noqa: E402
_permissive(globals())
