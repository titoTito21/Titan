# -*- coding: utf-8 -*-
"""GTK: AT-SPI on Linux, nothing on Windows.

On Linux every GTK widget is an ATK object and reaches the reader through
AT-SPI, where an entry implements `EditableText` and takes
`set_text_contents`. GTK 3 and 4 on Windows implement no Windows
accessibility API, so a GTK program there is written with the keys and
read as a picture.
"""

from .base import Toolkit


class Gtk(Toolkit):
    FRAMEWORKS = ('gtk',)
    NAME = 'GTK'
    PLAN = ('atspi', 'keys')
    READ = ('atspi',)
    NOTE = ('Linux: AT-SPI, EditableText.set_text_contents. Windows: GTK '
            'exposes nothing - keys, and the picture.')


TOOLKIT = Gtk()
