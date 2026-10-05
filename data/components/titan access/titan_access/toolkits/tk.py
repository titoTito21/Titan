# -*- coding: utf-8 -*-
"""Tk (Tkinter, Tcl/Tk): nothing before 9.1, MSAA from 9.1.

Tk draws its own widgets - an `entry` is not an Edit window - and before
Tk 9.1 it exposed nothing to any accessibility API on Windows: a Tkinter
program is a window with no controls in it, read only as a picture. Tk
9.1 (released 29 September 2026, TIP 733) added screen reader support:
MSAA on Windows ("UI Automation ... offers no special benefit to Tk that
MSAA cannot address"), ATK on X11, NSAccessibility on macOS, with role,
name, description, value, state and action attributes and virtual
objects for listbox rows. So a field is read through MSAA where Tk 9.1
answers, and written with the user's keys in every Tk - TIP 733 defines
the value as something reported, not something a reader sets.

Sources: core.tcl-lang.org/tips TIP 733; tcl-lang.org "Tcl/Tk 9.1".
"""

from .base import Toolkit


class Tk(Toolkit):
    FRAMEWORKS = ('tk',)
    NAME = 'Tk'
    PLAN = ('keys',)
    READ = ('msaa', 'uia')
    NOTE = ('Tk draws its own widgets. Before 9.1 nothing is exposed (read '
            'it as a picture); Tk 9.1 speaks MSAA on Windows and ATK on '
            'Linux (TIP 733). Fields are written with the user\'s own keys.')


TOOLKIT = Tk()
