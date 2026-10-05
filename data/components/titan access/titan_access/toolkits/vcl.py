# -*- coding: utf-8 -*-
"""Delphi and C++ Builder: VCL is native, FireMonkey is not.

VCL's TEdit, TMemo, TMaskEdit and TRichEdit are subclassed Edit and
RichEdit windows - class names `TEdit`, `TMemo` - and take `WM_SETTEXT`.
FireMonkey draws everything itself and implements little accessibility,
so an FMX field is written with the keys.
"""

from .base import Toolkit


class Vcl(Toolkit):
    FRAMEWORKS = ('vcl',)
    NAME = 'Delphi / C++ Builder'
    PLAN = ('win32', 'msaa', 'uia', 'keys')
    NOTE = ('VCL edits are subclassed Edit/RichEdit windows (TEdit, TMemo) '
            'and take WM_SETTEXT; FireMonkey draws its own and takes keys.')


TOOLKIT = Vcl()
