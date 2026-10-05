# -*- coding: utf-8 -*-
from . import NVDAObject


class UIA(NVDAObject):
    pass


from .. import permissive as _permissive  # noqa: E402
_permissive(globals())
