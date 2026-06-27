# -*- coding: utf-8 -*-
"""Application-specific modules for Titan Access.

Port of the C# ``ScreenReader/AppModules`` package (itself a port of NVDA's
``appModuleHandler``). Each module customises the reader's behaviour for one
application, keyed by its process name. :class:`~titan_access.app_modules.manager.AppModuleManager`
selects the active module from the foreground process and delegates focus events
to it.
"""

from titan_access.app_modules.base import AppModuleBase

__all__ = ["AppModuleBase"]
