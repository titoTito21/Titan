# -*- coding: utf-8 -*-
from . import NVDAObject


class Window(NVDAObject):
    def __new__(cls, windowHandle=None, **kwargs):
        from titan_access.portable import readerApi
        found = readerApi.window_object(windowHandle)
        return found if found is not None else super().__new__(cls)


from .. import permissive as _permissive  # noqa: E402
_permissive(globals())
