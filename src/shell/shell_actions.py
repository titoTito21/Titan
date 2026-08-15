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
    """The desktop is always there, so this answers with the shell off too.

    Titan's own icons when Titan is drawing them, and Windows' own list view
    when it is not - the same rule Windows+D and Windows+M follow.
    """
    from src.shell.shell_manager import focus_desktop
    if focus_desktop():
        return _("The keyboard is on the desktop.")
    from src.titan_core.actions.interaction import fails
    return fails(_("The desktop could not be reached."))


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


def _find_desktop_entry(name):
    """One desktop item by name or by the number `list_desktop` gave.

    Returns (label, path), or a Question/Failure to hand straight back -
    every desktop action wants exactly this and none of them should guess
    which of two similarly named icons was meant.
    """
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
        return entries[index]
    lowered = wanted.lower()
    exact = [entry for entry in entries if entry[0].lower() == lowered]
    matches = exact or [entry for entry in entries
                        if lowered in entry[0].lower()]
    if not matches:
        return fails(_("There is nothing called {name} on the desktop.")
                     .format(name=wanted))
    if len(matches) > 1:
        return needs('name', _("Which one did you mean?"),
                     options=[entry[0] for entry in matches])
    return matches[0]


def _resolved(entry):
    """True when `_find_desktop_entry` found something rather than asking."""
    return isinstance(entry, tuple)


def shell_desktop_item_properties(name=None, **_kwargs):
    """Open Windows' own properties sheet for a desktop item.

    For a shortcut that sheet is where the target, the working folder and
    the shortcut key live, so this is how "what does this icon actually
    point at, and change it" is done without a mouse.
    """
    if not IS_WINDOWS:
        return _no_windows()
    entry = _find_desktop_entry(name)
    if not _resolved(entry):
        return entry
    label, path = entry
    from src.titan_core.actions.interaction import fails
    if win_shell.show_properties(path):
        return _("The properties of {name} are open.").format(name=label)
    return fails(_("The properties of {name} could not be opened.")
                 .format(name=label))


def shell_desktop_item_target(name=None, **_kwargs):
    """What a desktop shortcut points at."""
    if not IS_WINDOWS:
        return _no_windows()
    entry = _find_desktop_entry(name)
    if not _resolved(entry):
        return entry
    label, path = entry
    target = win_shell.shortcut_target(path)
    if target:
        return _("{name} points at {target}.").format(name=label,
                                                      target=target)
    return _("{name} is not a shortcut. It is {path}.").format(
        name=label, path=path)


def shell_open_item_location(name=None, **_kwargs):
    """Open the folder a desktop item is in - a shortcut's target folder."""
    if not IS_WINDOWS:
        return _no_windows()
    entry = _find_desktop_entry(name)
    if not _resolved(entry):
        return entry
    label, path = entry
    from src.titan_core.actions.interaction import fails
    if win_shell.reveal_in_explorer(path):
        return _("The folder holding {name} is open.").format(name=label)
    return fails(_("That folder could not be opened."))


def shell_rename_desktop_item(name=None, new_name=None, **_kwargs):
    """Rename something on the desktop, keeping the extension it had."""
    from src.titan_core.actions.interaction import fails, needs
    if not IS_WINDOWS:
        return _no_windows()
    entry = _find_desktop_entry(name)
    if not _resolved(entry):
        return entry
    if not new_name:
        return needs('new_name', _("What should it be called?"))
    label, path = entry
    extension = os.path.splitext(path)[1]
    target = os.path.join(os.path.dirname(path),
                          str(new_name).strip() + extension)
    if os.path.exists(target):
        return fails(_("There is already something called {name} there.")
                     .format(name=new_name))
    try:
        os.rename(path, target)
    except Exception as error:
        return fails(_("{name} could not be renamed: {error}")
                     .format(name=label, error=error))
    _refresh_desktop()
    return _("{name} is now called {new}.").format(name=label, new=new_name)


def shell_delete_desktop_item(name=None, **_kwargs):
    """Send a desktop item to the Recycle Bin."""
    if not IS_WINDOWS:
        return _no_windows()
    entry = _find_desktop_entry(name)
    if not _resolved(entry):
        return entry
    label, path = entry
    from src.titan_core.actions.interaction import fails
    if win_shell.recycle([path], confirm=False):
        _refresh_desktop()
        return _("{name} is in the Recycle Bin.").format(name=label)
    return fails(_("{name} could not be deleted.").format(name=label))


def shell_create_desktop_shortcut(target=None, name=None, **_kwargs):
    """Put a shortcut to a program or a folder on the desktop."""
    from src.titan_core.actions.interaction import fails, needs
    if not IS_WINDOWS:
        return _no_windows()
    if not target:
        return needs('target', _("What should the shortcut point at? Give "
                                 "the full path of the program or folder."))
    target = os.path.expandvars(os.path.expanduser(str(target).strip('"')))
    if not os.path.exists(target):
        return fails(_("There is nothing at {path}.").format(path=target))
    folders = win_shell.desktop_folders()
    if not folders:
        return fails(_("The desktop folder could not be found."))
    path = win_shell.create_shortcut(target, folders[0], name=name)
    if not path:
        return fails(_("The shortcut could not be created."))
    _refresh_desktop()
    return _("{name} is on the desktop.").format(
        name=win_shell.file_display_name(path))


def _refresh_desktop():
    """Show a change on a desktop that is on the screen right now."""
    shell = _shell()
    desktop = getattr(shell, 'desktop', None)
    if desktop is not None:
        try:
            import wx
            wx.CallAfter(desktop.refresh)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Programs: what the Start menu can find, and starting one
# --------------------------------------------------------------------------- #
def _program_index():
    """Everything the Start menu offers: Titan's add-ons and Windows'."""
    entries = []
    try:
        from src.titan_core.app_manager import get_applications
        for app in get_applications() or []:
            label = app.get('name') or app.get('shortname') or ''
            if label:
                entries.append((label, _("Titan application"), app))
    except Exception:
        pass
    try:
        from src.titan_core.game_manager import get_games
        for game in get_games() or []:
            label = game.get('name') or game.get('shortname') or ''
            if label:
                entries.append((label, _("Titan game"), game))
    except Exception:
        pass
    for label, folder, path in _windows_programs():
        entries.append((label, folder, {'path': path}))
    return entries


def _start_menu_folders():
    """The two Programs folders Windows keeps: this user's and everybody's."""
    folders = []
    for base in (os.environ.get('APPDATA', ''),
                 os.environ.get('PROGRAMDATA', '')):
        if not base:
            continue
        path = os.path.join(base, 'Microsoft', 'Windows', 'Start Menu',
                            'Programs')
        if os.path.isdir(path):
            folders.append(path)
    return folders


def _windows_programs():
    """Every shortcut in the Windows Start Menu: (name, folder, path).

    Read straight off the disk rather than through the Start menu window,
    because an action must answer with no window open - the classic menu's
    own reader is a method on a `wx.Frame`.
    """
    found, seen = [], set()
    for root in _start_menu_folders():
        for directory, _subdirs, names in os.walk(root):
            where = os.path.basename(directory)
            if os.path.normcase(directory) == os.path.normcase(root):
                where = _("Programs")
            for name in names:
                if not name.lower().endswith(('.lnk', '.url', '.exe')):
                    continue
                path = os.path.join(directory, name)
                label = win_shell.file_display_name(path) or                     os.path.splitext(name)[0]
                key = label.lower()
                if key in seen:
                    continue
                seen.add(key)
                found.append((label, where, path))
    return found


def shell_search_programs(query=None, **_kwargs):
    """Search everything the Start menu can start, as its box does."""
    from src.titan_core.actions.interaction import needs
    if not query:
        return needs('query', _("What are you looking for?"))
    needle = str(query).strip().lower()
    found = [entry for entry in _program_index()
             if needle in entry[0].lower()]
    found.sort(key=lambda entry: (not entry[0].lower().startswith(needle),
                                  entry[0].lower()))
    if not found:
        return _("Nothing called {name} was found.").format(name=query)
    return "\n".join("{}. {} ({})".format(index, label, where)
                      for index, (label, where, _payload)
                      in enumerate(found[:30], start=1))


def shell_run_program(name=None, **_kwargs):
    """Start a program by its name, wherever the Start menu found it."""
    from src.titan_core.actions.interaction import fails, needs
    if not name:
        return needs('name', _("Which program?"))
    needle = str(name).strip().lower()
    entries = _program_index()
    exact = [entry for entry in entries if entry[0].lower() == needle]
    matches = exact or [entry for entry in entries
                        if needle in entry[0].lower()]
    if not matches:
        return fails(_("Nothing called {name} was found.").format(name=name))
    if len(matches) > 1:
        return needs('name', _("Which one did you mean?"),
                     options=[entry[0] for entry in matches[:10]])
    label, where, payload = matches[0]
    try:
        if where == _("Titan application"):
            from src.titan_core.app_manager import open_application
            open_application(payload)
        elif where == _("Titan game"):
            from src.titan_core.game_manager import open_game
            open_game(payload)
        else:
            path = payload.get('path') or payload.get('file') or ''
            if not path:
                return fails(_("{name} has nothing to run.").format(
                    name=label))
            win_shell.open_path(path)
        return _("{name} has been started.").format(name=label)
    except Exception as error:
        return fails(_("{name} could not be started: {error}")
                     .format(name=label, error=error))


# --------------------------------------------------------------------------- #
# The file browser
# --------------------------------------------------------------------------- #
def shell_open_explorer(path=None, **_kwargs):
    """Open the shell's file browser, at My Computer or at a folder.

    It does not need the desktop shell: the browser is an ordinary window,
    so "show me that folder" works whatever the system interface setting
    says.
    """
    from src.titan_core.actions.interaction import fails
    if not IS_WINDOWS:
        return _no_windows()
    where = None
    if path:
        where = os.path.expandvars(os.path.expanduser(str(path)))
        if not os.path.isdir(where):
            return fails(_("There is no folder called {name}.").format(
                name=path))
    try:
        import wx
        from src.shell.shell_manager import open_explorer
        wx.CallAfter(open_explorer, where)
    except Exception as error:
        return fails(_("The file browser could not be opened: {error}")
                     .format(error=error))
    if where:
        return _("The file browser is open at {name}.").format(name=where)
    return _("The file browser is open at My Computer.")


def shell_list_drives(**_kwargs):
    """The drives, with how big each is and how much of it is free."""
    if not IS_WINDOWS:
        return _no_windows()
    from src.shell.explorer import drive_name, drive_type_name, format_size
    drives = win_shell.list_drives()
    if not drives:
        return _("This computer has no drives Windows will report.")
    lines = []
    for drive in drives:
        lines.append("{}: {}, {} {}, {} {}".format(
            drive_name(drive), drive_type_name(drive.get('type')),
            format_size(drive.get('total')) or _("unknown"), _("in total"),
            format_size(drive.get('free')) or _("unknown"), _("free")))
    return "\n".join(lines)


def shell_list_folder(path=None, **_kwargs):
    """What is in a folder, the way the browser shows it."""
    from src.titan_core.actions.interaction import fails, needs
    from src.shell.explorer import (COMPUTER, format_size, list_location,
                                    type_name_of)
    if not path:
        return needs('path', _("Which folder?"))
    wanted = str(path).strip()
    if wanted.lower() in ('my computer', 'computer', COMPUTER):
        location = COMPUTER
    else:
        location = os.path.expandvars(os.path.expanduser(wanted))
        if not os.path.isdir(location):
            return fails(_("There is no folder called {name}.").format(
                name=path))
    try:
        entries = list_location(location)
    except Exception as error:
        return fails(_("That folder could not be read: {error}").format(
            error=error))
    if not entries:
        return _("That folder is empty.")
    lines = []
    for index, entry in enumerate(entries, start=1):
        size = format_size(entry.get('size') or entry.get('total'))
        lines.append("{}. {} - {}{}".format(
            index, entry['name'], type_name_of(entry),
            ", {}".format(size) if size else ''))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Turning things off
# --------------------------------------------------------------------------- #
def shell_power_options(**_kwargs):
    """What this machine will actually do: the Shut Down dialog's own list."""
    from src.shell.shutdown_dialog import shutdown_actions
    return "\n".join("{}: {}".format(identifier, label)
                      for identifier, label, _description
                      in shutdown_actions())


def shell_power(action=None, **_kwargs):
    """Log off, restart, sleep, shut the computer down - or close Titan.

    Nothing is offered that the machine has said it cannot do: sleep and
    hibernate appear only where Windows reports them, which is the same
    list the dialog shows.
    """
    from src.titan_core.actions.interaction import fails, needs
    from src.shell.shutdown_dialog import (perform_shutdown_action,
                                           shutdown_actions)
    choices = [identifier for identifier, _label, _desc in shutdown_actions()]
    if not action:
        return needs('action', _("What should the computer do?"),
                     options=choices)
    wanted = str(action).strip().lower().replace(' ', '_')
    if wanted not in choices:
        return fails(_("This computer can do: {list}.").format(
            list=", ".join(choices)))
    if perform_shutdown_action(wanted):
        return _("Done: {action}.").format(action=wanted)
    return fails(_("Windows refused that."))


def shell_focus_tray(**_kwargs):
    """Windows+B: put the keyboard in the notification area."""
    shell = _shell()
    if shell is None:
        from src.titan_core.actions.interaction import fails
        return fails(_needs_shell())
    shell.focus_tray()
    return _("The keyboard is in the notification area.")


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
    'shell sounds': 'shell_sounds',
    'hide the windows taskbar': 'hide_system_taskbar',
    'auto-hide the taskbar': 'taskbar_auto_hide',
    'lock the taskbar': 'taskbar_locked',
    'taskbar on top': 'taskbar_on_top',
    'quick launch': 'show_quick_launch',
    'clock': 'show_clock',
    'show desktop button': 'show_desktop_button',
}


def shell_list_settings(**_kwargs):
    """What can be changed about the shell, in the words a user would use."""
    from src.shell.a11y import shell_setting
    defaults = {'desktop_shell': False, 'show_desktop': True,
                'show_taskbar': True, 'show_tray': True,
                'show_wallpaper': True, 'clock_seconds': False,
                'auto_arrange_icons': False, 'focus_cues': True,
                'shell_sounds': True,
                'hide_system_taskbar': True, 'taskbar_auto_hide': False,
                'taskbar_locked': True, 'taskbar_on_top': False,
                'show_quick_launch': True, 'show_clock': True,
                'show_desktop_button': True}
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
    if key.startswith('taskbar_') or key.startswith('show_'):
        shell = _shell()
        taskbar = getattr(shell, 'taskbar', None)
        if taskbar is not None:
            for method in ('_start_auto_hide', 'apply_always_on_top',
                           'refresh_quick_launch', '_layout_bar'):
                try:
                    getattr(taskbar, method)()
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
def shell_list_addons(**_kwargs):
    """What is installed in `data/shell addons/`, and what each one does."""
    try:
        from src.shell import addons
        described = addons.manager().describe()
    except Exception as error:
        return f"Could not read the shell add-ons: {error}"
    if not described:
        return ("No shell add-ons are installed. They go in "
                "data/shell addons/ and can add to the Start menu, the file "
                "browser, the taskbar and the desktop - or replace the Start "
                "menu or the file browser outright.")
    lines = ["Shell add-ons:"]
    for entry in described:
        state = "on" if entry['enabled'] else "off"
        line = f"- {entry['name']} ({entry['id']}): {state}"
        if entry['provides']:
            line += f", provides a {entry['provides'].replace('_', ' ')}"
        if entry['error']:
            line += f", broken: {entry['error']}"
        lines.append(line)
        if entry['description']:
            lines.append(f"  {entry['description']}")
    lines.append("Turn one on or off with <its id>.enable / .disable.")
    return "\n".join(lines)


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
        ('focus_tray', "Put the keyboard in the notification area.", {},
         'auto', shell_focus_tray),
        ('desktop_item_properties', "Open the Windows properties of a "
                                    "desktop item - for a shortcut, its "
                                    "target and shortcut key.",
         {'name': dict(string, description="The icon's name, or its number "
                       "from list_desktop.", required=True)},
         'auto', shell_desktop_item_properties),
        ('desktop_item_target', "Say what a desktop shortcut points at.",
         {'name': dict(string, description="The icon's name or number.",
                       required=True)},
         'auto', shell_desktop_item_target),
        ('open_item_location', "Open the folder a desktop item lives in.",
         {'name': dict(string, description="The icon's name or number.",
                       required=True)},
         'auto', shell_open_item_location),
        ('rename_desktop_item', "Rename something on the desktop.",
         {'name': dict(string, description="The icon's name or number.",
                       required=True),
          'new_name': dict(string, description="What it should be called.",
                           required=True)},
         'confirm', shell_rename_desktop_item),
        ('delete_desktop_item', "Send a desktop item to the Recycle Bin.",
         {'name': dict(string, description="The icon's name or number.",
                       required=True)},
         'confirm', shell_delete_desktop_item),
        ('create_desktop_shortcut', "Put a shortcut to a program or folder "
                                    "on the desktop.",
         {'target': dict(string, description="Full path of the program or "
                         "folder.", required=True),
          'name': dict(string, description="What to call it (optional).")},
         'confirm', shell_create_desktop_shortcut),
        ('search_programs', "Search everything the Start menu can start.",
         {'query': dict(string, description="Part of the program's name.",
                        required=True)},
         'auto', shell_search_programs),
        ('run_program', "Start a program by name, wherever the Start menu "
                        "found it.",
         {'name': dict(string, description="The program's name.",
                       required=True)},
         'confirm', shell_run_program),
        ('open_explorer', "Open the file browser - My Computer, or a "
                          "folder.",
         {'path': dict(string, description="The folder to show (optional).")},
         'auto', shell_open_explorer),
        ('list_drives', "List the drives, with their size and free space.",
         {}, 'auto', shell_list_drives),
        ('list_folder', "List what is in a folder, or in My Computer.",
         {'path': dict(string, description="The folder, or 'My Computer'.",
                       required=True)},
         'auto', shell_list_folder),
        ('power_options', "List what this computer will do: log off, "
                          "restart, sleep, shut down, or close Titan.", {},
         'auto', shell_power_options),
        ('power', "Log off, restart, sleep, shut the computer down, or turn "
                  "Titan off.",
         {'action': dict(string, description="logoff, shutdown, restart, "
                         "sleep, hibernate or exit_titan.", required=True)},
         'always_confirm', shell_power),
        ('list_addons', "List the shell add-ons installed: what each adds "
                        "to the shell, and whether it is on.", {}, 'auto',
         shell_list_addons),
        ('list_settings', "List the shell's settings and their values.", {},
         'auto', shell_list_settings),
        ('set_setting', "Turn one of the shell's settings on or off.",
         {'name': dict(string, description="The setting, e.g. 'taskbar', "
                       "'wallpaper', 'desktop shell'.", required=True),
          'value': dict(string, description="on or off.", required=True)},
         'confirm', shell_set_setting),
    )
