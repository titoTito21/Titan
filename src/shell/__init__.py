# -*- coding: utf-8 -*-
"""
Titan Shell - the desktop, taskbar, notification area and Start menu that
replace the system interface while "Modify system interface" is enabled.

The visual target is Windows XP (Luna Blue), reproduced from the measured
values of the theme rather than approximated by eye; the interaction target
is Titan's own: every element is a real focusable window with a name, a role
and a spoken announcement, so the shell is usable with the keyboard alone.

Nothing here is imported at Titan startup - `shell_manager.start_shell()` is
what brings it up, and it is called only when the setting is on.
"""

from src.shell.shell_manager import (
    start_shell, stop_shell, is_shell_running, get_shell,
    toggle_start_menu, show_desktop, refresh_shell,
)

__all__ = [
    'start_shell', 'stop_shell', 'is_shell_running', 'get_shell',
    'toggle_start_menu', 'show_desktop', 'refresh_shell',
]
