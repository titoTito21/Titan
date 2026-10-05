# -*- coding: utf-8 -*-
from . import NVDAObject


class IAccessible(NVDAObject):
    pass


from .. import permissive as _permissive  # noqa: E402
_permissive(globals())
