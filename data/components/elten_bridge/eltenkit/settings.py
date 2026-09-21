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


# ---------------------------------------------------------------- widgets
# The applications started in the BACKGROUND for their main-tab widgets
# (Weather's forecast, for one): Elten runs every installed application's
# extensions whether or not it is open, and a widget the user has to open
# the application to see is not a widget. Kept as the applications' keys.
WIDGET_APPS_KEY = 'elten_bridge_widget_apps'


def widget_apps():
    """The keys of the applications to start in the background. Never
    raises."""
    try:
        from src.settings.settings import get_setting
        value = get_setting(WIDGET_APPS_KEY, [])
    except Exception:
        return []
    if isinstance(value, str):
        value = [part for part in value.split('|') if part]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item)]


def set_widget_apps(keys):
    try:
        from src.settings.settings import save_settings, load_settings
        settings = load_settings()
        settings[WIDGET_APPS_KEY] = [str(key) for key in keys]
        save_settings(settings)
        return True
    except Exception as error:
        print(f"[elten bridge] could not save the widget applications: {error}")
        return False
