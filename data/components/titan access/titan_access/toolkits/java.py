# -*- coding: utf-8 -*-
"""Java (AWT/Swing) and JavaFX: the Java Access Bridge.

Swing paints its own components, so Windows sees one window and the
accessibility comes through the Java Access Bridge (WindowsAccessBridge),
which has to be enabled (`jabswitch -enable`). `setTextContents` (Java 7u6
and later) replaces an editable text's contents; JavaFX answers UI
Automation instead.
"""

from .base import Toolkit


class Java(Toolkit):
    FRAMEWORKS = ('java',)
    NAME = 'Java'
    PLAN = ('jab', 'keys')
    READ = ('jab',)
    NOTE = ('Swing is reached through the Java Access Bridge (enable it with '
            'jabswitch -enable); setTextContents writes an editable text.')


class JavaFx(Toolkit):
    FRAMEWORKS = ('javafx',)
    NAME = 'JavaFX'
    PLAN = ('uia', 'keys')
    READ = ('uia',)
    NOTE = 'JavaFX is a UI Automation provider on Windows.'


TOOLKIT = Java()
TOOLKITS = (TOOLKIT, JavaFx())
