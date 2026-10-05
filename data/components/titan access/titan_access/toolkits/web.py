# -*- coding: utf-8 -*-
"""Chromium, Electron, CEF and Firefox: a web page's fields.

A browser answers UI Automation (and IAccessible2), and an `<input>`
reports ValuePattern - but setting a page's field through accessibility
does not fire the `input` events the page listens for, so a React or Vue
form keeps its old value and the user's text is lost on submit. A web
field is therefore written with the user's own keys, exactly as typing
would, and only READ through UI Automation.
"""

from .base import Toolkit


class Web(Toolkit):
    FRAMEWORKS = ('chromium', 'cef', 'electron', 'gecko', 'mshtml',
                  'sciter')
    NAME = 'Web'
    PLAN = ('keys',)
    READ = ('uia', 'msaa')
    NOTE = ('Browser fields are written with keys: a value set through '
            'accessibility fires no input event and a scripted page '
            'ignores it.')


TOOLKIT = Web()
