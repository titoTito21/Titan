# -*- coding: utf-8 -*-
"""Mozilla Firefox application module.

Port in spirit of NVDA's ``appModules/firefox.py``. Gecko exposes web content
through IAccessible2 rather than the Chromium UIA surface, but Titan's browse
mode already detects Firefox (its ``MozillaWindowClass`` content window and the
``gecko`` framework id) and reads the page through the same virtual buffer, so
this module only supplies the friendly name and inherits the shared browser
announcement tidying from :class:`BrowserModule`.
"""

from titan_access.localization import L
from titan_access.app_modules.browser_base import BrowserModule


class FirefoxModule(BrowserModule):
    #: The Gecko family: the browsers built on Firefox, and Thunderbird,
    #: whose message list and message body read through the same
    #: IAccessible2 surface.
    process_names = {"firefox", "thunderbird", "librewolf", "waterfox",
                     "floorp", "zen", "palemoon", "seamonkey", "betterbird"}
    process_name = "firefox"

    @property
    def app_name(self):
        return L("browser.firefox")
