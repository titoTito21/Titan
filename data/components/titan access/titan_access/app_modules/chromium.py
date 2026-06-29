# -*- coding: utf-8 -*-
"""Chromium-family browser modules (Chrome / Edge / generic Chromium).

Port in spirit of NVDA's ``appModules/chromium.py``: one module serves the whole
Blink/Chromium family because they share the same accessibility surface
(``Chrome_RenderWidgetHostHWND`` content window, UIA ``chrome`` framework id).
Edge is Chromium too, so :class:`EdgeModule` only changes the friendly name.

All the web-page reading lives in :mod:`titan_access.browse_mode`, which engages
automatically for these processes; these classes just supply a friendly app name
and inherit :class:`BrowserModule`'s announcement tidying.
"""

from titan_access.localization import L
from titan_access.app_modules.browser_base import BrowserModule


class ChromiumModule(BrowserModule):
    process_name = "chrome"

    @property
    def app_name(self):
        return L("browser.chrome")


class EdgeModule(ChromiumModule):
    process_name = "msedge"

    @property
    def app_name(self):
        return L("browser.edge")
