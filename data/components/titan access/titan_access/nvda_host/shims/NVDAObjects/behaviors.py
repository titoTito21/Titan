# -*- coding: utf-8 -*-
from . import NVDAObject


class EditableText(NVDAObject):
    pass


class EditableTextWithoutAutoSelectDetection(EditableText):
    pass


class EditableTextWithAutoSelectDetection(EditableText):
    pass


class Terminal(NVDAObject):
    pass


class LiveText(NVDAObject):
    pass


class Dialog(NVDAObject):
    pass


class ProgressBar(NVDAObject):
    pass


class RowWithFakeNavigation(NVDAObject):
    pass


from .. import permissive as _permissive  # noqa: E402
_permissive(globals())
