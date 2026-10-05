# -*- coding: utf-8 -*-
"""What draws its own pixels: consoles and game engines.

A console's input line belongs to the program reading stdin, and a game
(Unity, Godot, SDL) draws its fields onto a texture: neither has an
accessible field to write, so the keys are the only way, and the picture
the only way to read.
"""

from .base import Toolkit


class Drawn(Toolkit):
    FRAMEWORKS = ('console', 'unity', 'godot', 'sdl')
    NAME = 'Drawn'
    PLAN = ('keys',)
    READ = ()
    NOTE = 'Consoles and game engines: keys in, the picture out.'


TOOLKIT = Drawn()
