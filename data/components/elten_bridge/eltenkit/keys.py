# -*- coding: utf-8 -*-
"""The keyboard, in Elten's own words.

Copyright (C) 2026 titosoft. Part of the Elten API bridge, licensed under the
GNU General Public License version 3 or later; see `LICENSE` beside this
component.

Elten names a key `:key_left`, `:key_space`, `:key_escape` - and a letter as
itself, `:a`, `:w`, `:d`, which is how Purrposterous binds its second set of
movement keys (`hold: [:key_left, :a]`). Both spellings have to arrive as the
same thing, or half a game's controls do nothing.
"""

import wx

#: wx key code -> Elten's name for it.
NAMED = {
    wx.WXK_LEFT: 'key_left', wx.WXK_RIGHT: 'key_right',
    wx.WXK_UP: 'key_up', wx.WXK_DOWN: 'key_down',
    wx.WXK_RETURN: 'key_enter', wx.WXK_NUMPAD_ENTER: 'key_enter',
    wx.WXK_ESCAPE: 'key_escape', wx.WXK_SPACE: 'key_space',
    wx.WXK_TAB: 'key_tab', wx.WXK_BACK: 'key_backspace',
    wx.WXK_DELETE: 'key_delete', wx.WXK_INSERT: 'key_insert',
    wx.WXK_HOME: 'key_home', wx.WXK_END: 'key_end',
    wx.WXK_PAGEUP: 'key_pageup', wx.WXK_PAGEDOWN: 'key_pagedown',
    wx.WXK_SHIFT: 'key_shift', wx.WXK_CONTROL: 'key_control',
    wx.WXK_ALT: 'key_alt',
}

for _index in range(1, 13):
    NAMED[getattr(wx, 'WXK_F%d' % _index)] = 'key_f%d' % _index


def names_for(code):
    """Every name this key answers to.

    A letter is BOTH `key_a` and `a`, because Elten's applications write
    both and a game that binds one spelling must not lose the other.
    """
    named = NAMED.get(code)
    if named:
        return [named]
    if 65 <= code <= 90:                                   # A-Z
        letter = chr(code).lower()
        return ['key_%s' % letter, letter]
    if 48 <= code <= 57:                                   # 0-9
        digit = chr(code)
        return ['key_%s' % digit, digit]
    return []


def virtual_of(name):
    """Elten's name -> the wx code, for asking whether it is held now."""
    wanted = str(name or '').strip().lower()
    if not wanted:
        return None
    for code, named in NAMED.items():
        if named == wanted:
            return code
    if wanted.startswith('key_'):
        wanted = wanted[4:]
    if len(wanted) == 1 and (wanted.isalpha() or wanted.isdigit()):
        return ord(wanted.upper())
    try:
        return int(wanted)          # Elten's applications also use raw codes
    except ValueError:
        return None
