# -*- coding: utf-8 -*-
"""
The shell as something any add-on, macro or the AI can drive.

These are the Action API's `shell.*` actions.  They exist because the shell
is the one part of Titan that knows what the *system* looks like right now -
which windows are open, what is on the desktop, what the notification area
holds - and because a Titan Script that says

    shell.open_start_menu
    shell.activate_window title="Notepad"
    shell.open_desktop_item name="My documents"

should not have to replay keystrokes to get any of it.

Every action works whether or not the shell's own windows are up: the window
list and the desktop contents come from Windows, not from the taskbar, so
`list_windows` answers even with the desktop shell turned off.  The ones that
genuinely need the shell (opening its Start menu, focusing its taskbar) say
so plainly instead of doing nothing.
"""

import os

from src.platform_utils import IS_WINDOWS
from src.shell import win_shell
from src.titan_core.translation import _


def _shell(running_only=True):
    from src.shell.shell_manager import get_shell
    shell = get_shell()
    if shell is None or (running_only and not shell.is_running()):
        return None
    return shell


def _needs_shell():
    return _("The Titan shell is not running. Turn on \"Replace the desktop, "
             "taskbar and Start menu\" under Settings, Titan shell.")


def _no_windows():
    return _("The Titan shell only runs on Windows.")


# --------------------------------------------------------------------------- #
# The shell itself
# --------------------------------------------------------------------------- #
def shell_status(**_kwargs):
    """Is the shell up, and what is it showing?"""
    if not IS_WINDOWS:
        return _no_windows()
    shell = _shell(running_only=False)
    if shell is None or not shell.is_running():
        return _("The Titan shell is not running.")

    parts = [_("The Titan shell is running.")]
    if shell.desktop is not None:
        parts.append(_("Desktop: {count} icons").format(
            count=len(shell.desktop.items)))
    if shell.taskbar is not None:
        parts.append(_("Taskbar: {count} windows").format(
            count=len(shell.taskbar.windows())))
        parts.append(_("Clock: {time}").format(
            time=shell.taskbar.clock.get_text()))
        parts.append(_("The taskbar is at the {edge}.").format(
            edge=shell.taskbar.position_name()))
        if shell.taskbar.auto_hide():
            parts.append(_("It hides itself."))
    menu = shell.start_menu
    if menu is not None and menu.IsShown():
        parts.append(_("The Start menu is open."))
    return " ".join(parts)


def shell_start(**_kwargs):
    """Turn the desktop shell on now."""
    if not IS_WINDOWS:
        return _no_windows()
    from src.shell.shell_manager import start_shell, is_shell_running
    if is_shell_running():
        return _("The Titan shell is already running.")
    if start_shell(force=True):
        return _("The Titan shell is running.")
    from src.titan_core.actions.interaction import fails
    return fails(_("The Titan shell could not be started."))


def shell_stop(**_kwargs):
    """Take the shell down and give the screen back to Windows."""
    from src.shell.shell_manager import stop_shell
    if stop_shell():
        return _("The Titan shell has been stopped.")
    return _("The Titan shell was not running.")


def shell_refresh(**_kwargs):
    """Re-read the desktop, the window list and the notification area."""
    from src.shell.shell_manager import refresh_shell
    if refresh_shell():
        return _("The shell has been refreshed.")
    from src.titan_core.actions.interaction import fails
    return fails(_needs_shell())


# --------------------------------------------------------------------------- #
# The Start menu, the desktop and the taskbar
# --------------------------------------------------------------------------- #
def shell_open_start_menu(**_kwargs):
    shell = _shell()
    if shell is None:
        from src.titan_core.actions.interaction import fails
        return fails(_needs_shell())
    menu = shell.get_start_menu()
    if menu is None:
        from src.titan_core.actions.interaction import fails
        return fails(_("The Start menu could not be opened."))
    if not menu.IsShown():
        menu.show_menu()
    return _("The Start menu is open.")


def shell_close_start_menu(**_kwargs):
    shell = _shell()
    if shell is None:
        from src.titan_core.actions.interaction import fails
        return fails(_needs_shell())
    if shell.close_start_menu():
        return _("The Start menu is closed.")
    return _("The Start menu was not open.")


def shell_show_desktop(**_kwargs):
    """Minimise everything, or put it back."""
    shell = _shell()
    if shell is not None:
        shell.show_desktop()
        return _("The desktop is showing.")
    if not IS_WINDOWS:
        return _no_windows()
    win_shell.minimize_all()
    return _("Every window has been minimised.")


def shell_focus_taskbar(**_kwargs):
    shell = _shell()
    if shell is None:
        from src.titan_core.actions.interaction import fails
        return fails(_needs_shell())
    shell.focus_taskbar()
    return _("The keyboard is on the taskbar.")


def shell_focus_desktop(**_kwargs):
    shell = _shell()
    if shell is None:
        from src.titan_core.actions.interaction import fails
        return fails(_needs_shell())
    shell.focus_desktop()
    return _("The keyboard is on the desktop.")


def shell_get_time(**_kwargs):
    """What the taskbar clock says, date included."""
    import time
    return time.strftime('%H:%M, %A, %d %B %Y')


# --------------------------------------------------------------------------- #
# Windows
# --------------------------------------------------------------------------- #
def _match_window(title):
    """Find one open window by an exact or partial title."""
    wanted = str(title or '').strip().lower()
    windows = win_shell.list_windows()
    for window in windows:
        if window.title.lower() == wanted:
            return window
    matches = [w for w in windows if wanted and wanted in w.title.lower()]
    if len(matches) == 1:
        return matches[0]
    return matches or None


def shell_list_windows(**_kwargs):
    """Everything that has a taskbar button, and which one is active."""
    if not IS_WINDOWS:
        return _no_windows()
    windows = win_shell.list_windows()
    if not windows:
        return _("No windows are open.")
    lines = []
    for index, window in enumerate(windows, start=1):
        state = []
        if window.active:
            state.append(_("active"))
        if window.minimized:
            state.append(_("minimised"))
        suffix = " ({})".format(", ".join(state)) if state else ""
        lines.append("{}. {}{}".format(index, window.title, suffix))
    return "\n".join(lines)


def _window_command(title, action, done, missing):
    if not IS_WINDOWS:
        return _no_windows()
    from src.titan_core.actions.interaction import fails, needs
    if not title:
        return needs('title', _("Which window?"))
    match = _match_window(title)
    if match is None:
        return fails(missing.format(title=title))
    if isinstance(match, list):
        return needs('title', _("Which window did you mean?"),
                     options=[window.title for window in match])
    if action(match.hwnd):
        return done.format(title=match.title)
    return fails(_("Windows refused that."))


def shell_activate_window(title=None, **_kwargs):
    """Bring a window to the front by its title."""
    return _window_command(
        title, win_shell.activate_window,
        _("{title} is now in front."),
        _("There is no open window called {title}."))


def shell_minimize_window(title=None, **_kwargs):
    return _window_command(
        title, win_shell.minimize_window,
        _("{title} has been minimised."),
        _("There is no open window called {title}."))


def shell_close_window(title=None, **_kwargs):
    return _window_command(
        title, win_shell.close_window,
        _("{title} has been asked to close."),
        _("There is no open window called {title}."))


def shell_arrange_windows(how='cascade', **_kwargs):
    """Cascade or tile the open windows, as the taskbar menu does."""
    if not IS_WINDOWS:
        return _no_windows()
    how = str(how or 'cascade').strip().lower()
    arranger = {
        'cascade': win_shell.cascade_windows,
        'horizontal': win_shell.tile_windows_horizontally,
        'vertical': win_shell.tile_windows_vertically,
    }.get(how)
    if arranger is None:
        from src.titan_core.actions.interaction import needs
        return needs('how', _("How should the windows be arranged?"),
                     options=['cascade', 'horizontal', 'vertical'])
    shell = _shell()
    own = shell.own_hwnds() if shell else ()
    if arranger(own):
        return _("The windows have been arranged.")
    from src.titan_core.actions.interaction import fails
    return fails(_("There was nothing to arrange."))


# --------------------------------------------------------------------------- #
# The desktop's contents
# --------------------------------------------------------------------------- #
def _desktop_entries():
    entries = []
    seen = set()
    for folder in win_shell.desktop_folders():
        try:
            names = sorted(os.listdir(folder), key=str.lower)
        except Exception:
            continue
        for name in names:
            if name.lower() in ('desktop.ini', 'thumbs.db'):
                continue
            path = os.path.join(folder, name)
            label = win_shell.file_display_name(path)
            if label.lower() in seen:
                continue
            seen.add(label.lower())
            entries.append((label, path))
    return entries


def shell_list_desktop(**_kwargs):
    """What is on the desktop."""
    entries = _desktop_entries()
    if not entries:
        return _("The desktop is empty.")
    return "\n".join("{}. {}".format(index, label)
                     for index, (label, _path) in enumerate(entries, start=1))


def shell_open_desktop_item(name=None, **_kwargs):
    """Open a desktop icon by its name, or by the number the list gave."""
    from src.titan_core.actions.interaction import fails, needs
    if not name:
        return needs('name', _("Which item on the desktop?"))
    entries = _desktop_entries()
    wanted = str(name).strip()

    if wanted.isdigit():
        index = int(wanted) - 1
        if not (0 <= index < len(entries)):
            return fails(_("There is no item number {number} on the "
                           "desktop.").format(number=wanted))
        label, path = entries[index]
    else:
        lowered = wanted.lower()
        exact = [entry for entry in entries if entry[0].lower() == lowered]
        partial = exact or [entry for entry in entries
                            if lowered in entry[0].lower()]
        if not partial:
            return fails(_("There is nothing called {name} on the "
                           "desktop.").format(name=wanted))
        if len(partial) > 1:
            return needs('name', _("Which one did you mean?"),
                         options=[entry[0] for entry in partial])
        label, path = partial[0]

    if win_shell.open_path(path):
        return _("{name} has been opened.").format(name=label)
    return fails(_("{name} could not be opened.").format(name=label))


# --------------------------------------------------------------------------- #
# The notification area
# --------------------------------------------------------------------------- #
def shell_list_tray(**_kwargs):
    """The notification area, named - it is Windows' least readable corner."""
    if not IS_WINDOWS:
        return _no_windows()
    try:
        from src.system.system_tray_list import get_tray_icons
        icons = get_tray_icons() or []
    except Exception as error:
        from src.titan_core.actions.interaction import fails
        return fails(_("The notification area could not be read: {error}")
                     .format(error=error))
    if not icons:
        return _("The notification area is empty.")
    return "\n".join(
        "{}. {}".format(index, getattr(icon, 'tooltip', '')
                        or getattr(icon, 'text', '') or _("Unnamed"))
        for index, icon in enumerate(icons, start=1))


def shell_activate_tray_icon(name=None, **_kwargs):
    """Press a notification icon, by name or by number."""
    from src.titan_core.actions.interaction import fails, needs
    if not IS_WINDOWS:
        return _no_windows()
    if not name:
        return needs('name', _("Which notification icon?"))
    try:
        from src.system.system_tray_list import get_tray_icons
        icons = get_tray_icons() or []
    except Exception as error:
        return fails(_("The notification area could not be read: {error}")
                     .format(error=error))

    def label_of(icon):
        return (getattr(icon, 'tooltip', '') or getattr(icon, 'text', '') or '')

    wanted = str(name).strip()
    chosen = None
    if wanted.isdigit():
        index = int(wanted) - 1
        if 0 <= index < len(icons):
            chosen = icons[index]
    else:
        lowered = wanted.lower()
        matches = [icon for icon in icons if lowered in label_of(icon).lower()]
        if len(matches) == 1:
            chosen = matches[0]
        elif len(matches) > 1:
            return needs('name', _("Which one did you mean?"),
                         options=[label_of(icon) for icon in matches])
    if chosen is None:
        return fails(_("There is no notification icon called {name}.")
                     .format(name=wanted))
    try:
        chosen.left_click()
        return _("{name} has been activated.").format(name=label_of(chosen))
    except Exception as error:
        return fails(_("That icon could not be activated: {error}")
                     .format(error=error))


# --------------------------------------------------------------------------- #
# Settings of the shell itself
# --------------------------------------------------------------------------- #
_SETTINGS = {
    'desktop shell': 'desktop_shell',
    'desktop': 'show_desktop',
    'taskbar': 'show_taskbar',
    'notification area': 'show_tray',
    'wallpaper': 'show_wallpaper',
    'seconds': 'clock_seconds',
    'auto arrange': 'auto_arrange_icons',
    'focus cues': 'focus_cues',
    'hide the windows taskbar': 'hide_system_taskbar',
    'auto-hide the taskbar': 'taskbar_auto_hide',
    'lock the taskbar': 'taskbar_locked',
}


def shell_list_settings(**_kwargs):
    """What can be changed about the shell, in the words a user would use."""
    from src.shell.a11y import shell_setting
    defaults = {'desktop_shell': False, 'show_desktop': True,
                'show_taskbar': True, 'show_tray': True,
                'show_wallpaper': True, 'clock_seconds': False,
                'auto_arrange_icons': False, 'focus_cues': True,
                'hide_system_taskbar': True, 'taskbar_auto_hide': False,
                'taskbar_locked': True}
    lines = []
    for label, key in _SETTINGS.items():
        value = shell_setting(key, defaults.get(key, False))
        lines.append("{}: {}".format(label, _("on") if value else _("off")))
    return "\n".join(lines)


def shell_set_setting(name=None, value=None, **_kwargs):
    """Turn one of the shell's settings on or off."""
    from src.titan_core.actions.interaction import fails, needs
    if not name:
        return needs('name', _("Which setting?"),
                     options=sorted(_SETTINGS.keys()))
    if value is None:
        return needs('value', _("On or off?"), options=[_("on"), _("off")])

    lowered = str(name).strip().lower()
    key = _SETTINGS.get(lowered)
    if key is None:
        matches = [k for label, k in _SETTINGS.items() if lowered in label]
        if len(matches) != 1:
            return fails(_("There is no shell setting called {name}.")
                         .format(name=name))
        key = matches[0]

    truthy = str(value).strip().lower() in ('on', 'true', '1', 'yes',
                                            _("on").lower())
    from src.settings.settings import set_setting
    set_setting(key, str(truthy), 'titan_shell')

    from src.shell.shell_manager import apply_shell_settings
    try:
        apply_shell_settings()
    except Exception:
        pass
    # The bar's own two settings change what it is doing right now, not just
    # what it will do next time it starts.
    if key.startswith('taskbar_'):
        shell = _shell()
        taskbar = getattr(shell, 'taskbar', None)
        if taskbar is not None:
            try:
                taskbar._start_auto_hide()
            except Exception:
                pass
    return _("{name} is now {state}.").format(
        name=name, state=_("on") if truthy else _("off"))


def shell_taskbar_position(position=None, **_kwargs):
    """Move the taskbar to one edge of the screen or another."""
    from src.titan_core.actions.interaction import fails, needs
    choices = ['bottom', 'top', 'left', 'right']
    shell = _shell()
    taskbar = getattr(shell, 'taskbar', None)
    if taskbar is None:
        return fails(_needs_shell())
    if not position:
        return needs('position', _("Which edge of the screen?"),
                     options=choices)
    wanted = str(position).strip().lower()
    if wanted not in choices:
        return fails(_("The taskbar can be at the bottom, the top, the left "
                       "or the right."))
    if not taskbar.set_position(wanted):
        return fails(_("The taskbar is locked. Turn \"lock the taskbar\" off "
                       "first."))
    return _("The taskbar is now at the {edge}.").format(edge=wanted)


# --------------------------------------------------------------------------- #
# The declaration the Action API reads
# --------------------------------------------------------------------------- #
def get_shell_actions():
    """(name, summary, params, risk, callable) for every shell action."""
    string = {'type': 'string'}
    return (
        ('status', "Say whether the Titan shell is running and what it shows.",
         {}, 'auto', shell_status),
        ('start', "Start the Titan desktop, taskbar and Start menu.",
         {}, 'confirm', shell_start),
        ('stop', "Stop the Titan shell and give the screen back to Windows.",
         {}, 'confirm', shell_stop),
        ('refresh', "Re-read the desktop, the windows and the notification "
                    "area.", {}, 'auto', shell_refresh),
        ('open_start_menu', "Open the Start menu.", {}, 'auto',
         shell_open_start_menu),
        ('close_start_menu', "Close the Start menu.", {}, 'auto',
         shell_close_start_menu),
        ('show_desktop', "Minimise every window to show the desktop, or put "
                         "them back.", {}, 'auto', shell_show_desktop),
        ('focus_taskbar', "Put the keyboard on the taskbar.", {}, 'auto',
         shell_focus_taskbar),
        ('focus_desktop', "Put the keyboard on the desktop icons.", {},
         'auto', shell_focus_desktop),
        ('get_time', "What the taskbar clock says, with the date.", {},
         'auto', shell_get_time),
        ('list_windows', "List the open windows, saying which is active.",
         {}, 'auto', shell_list_windows),
        ('activate_window', "Bring an open window to the front.",
         {'title': dict(string, description="The window's title, whole or "
                        "part of it.", required=True)},
         'auto', shell_activate_window),
        ('minimize_window', "Minimise an open window.",
         {'title': dict(string, description="The window's title.",
                        required=True)},
         'auto', shell_minimize_window),
        ('close_window', "Ask an open window to close.",
         {'title': dict(string, description="The window's title.",
                        required=True)},
         'confirm', shell_close_window),
        ('arrange_windows', "Cascade or tile the open windows.",
         {'how': dict(string, description="cascade, horizontal or vertical.",
                      enum=['cascade', 'horizontal', 'vertical'])},
         'auto', shell_arrange_windows),
        ('list_desktop', "List what is on the desktop.", {}, 'auto',
         shell_list_desktop),
        ('open_desktop_item', "Open something on the desktop by name or "
                              "number.",
         {'name': dict(string, description="The icon's name, or the number "
                       "from list_desktop.", required=True)},
         'auto', shell_open_desktop_item),
        ('list_tray', "List the notification area icons by name.", {},
         'auto', shell_list_tray),
        ('activate_tray_icon', "Press a notification area icon.",
         {'name': dict(string, description="The icon's name, or its number.",
                       required=True)},
         'auto', shell_activate_tray_icon),
        ('taskbar_position', "Move the taskbar to the bottom, the top, the "
                             "left or the right of the screen.",
         {'position': dict(string, description="bottom, top, left or right.",
                           required=True)},
         'auto', shell_taskbar_position),
        ('list_settings', "List the shell's settings and their values.", {},
         'auto', shell_list_settings),
        ('set_setting', "Turn one of the shell's settings on or off.",
         {'name': dict(string, description="The setting, e.g. 'taskbar', "
                       "'wallpaper', 'desktop shell'.", required=True),
          'value': dict(string, description="on or off.", required=True)},
         'confirm', shell_set_setting),
    )
