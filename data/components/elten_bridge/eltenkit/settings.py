# -*- coding: utf-8 -*-
"""The Elten bridge's own settings.

Copyright (C) 2026 titosoft. Part of the Elten API bridge, licensed under the
GNU General Public License version 3 or later.

One preference so far: whether the bridge uses Titan's own (TCE) sounds. An
Elten application makes a sound for every interface event, and on this
desktop those should be Titan's - the theme the user chose - and a sound the
application asks for but did not ship should fall back to Titan's rather than
being silent. Somebody who would rather hear each application exactly as its
author shipped it turns this off, and then the bridge plays only the
application's own files.
"""

#: The setting key, in Titan's own settings store.
KEY = 'elten_bridge_tce_sounds'

#: Default: use Titan's sounds. This is a screen-reader desktop and a
#: consistent set of interface sounds is what a user expects.
DEFAULT = True


def use_titan_sounds():
    """Whether the bridge should use Titan's sounds. Never raises."""
    try:
        from src.settings.settings import get_setting
        value = get_setting(KEY, DEFAULT)
    except Exception:
        return DEFAULT
    if isinstance(value, str):
        return value.strip().lower() not in ('0', 'false', 'no', 'off', '')
    return bool(value)


def set_use_titan_sounds(value):
    try:
        from src.settings.settings import get_setting, save_settings, \
            load_settings
        settings = load_settings()
        settings[KEY] = bool(value)
        save_settings(settings)
        return True
    except Exception as error:
        print(f"[elten bridge] could not save the sound setting: {error}")
        return False
