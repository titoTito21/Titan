# -*- coding: utf-8 -*-
"""
TCE Window Switcher - Bridge module for TCE applications and components.

Allows apps running inside TCE to:
1. Register their windows in the global switcher
2. Unregister their windows on close
3. Open the "Switch To" dialog (F2)

Usage in apps:
    try:
        from src.titan_core.tce_window_switcher import (
            register_window, unregister_window, show_window_switcher
        )
    except ImportError:
        register_window = None
        unregister_window = None
        show_window_switcher = None

    # Register your app window
    if register_window:
        register_window("My App", my_wx_frame, category='app')

    # Open Switch To dialog (e.g., on F2 key)
    if show_window_switcher:
        show_window_switcher(parent=my_wx_frame)

    # Unregister on close
    if unregister_window:
        unregister_window("My App")
"""

# Re-export everything from the core module
from src.ui.window_switcher import (
    register_window,
    unregister_window,
    get_registered_windows,
    show_window_switcher,
    clear_all,
)

__all__ = [
    'register_window',
    'unregister_window',
    'get_registered_windows',
    'show_window_switcher',
    'clear_all',
]
