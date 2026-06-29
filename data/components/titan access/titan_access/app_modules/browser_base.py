# -*- coding: utf-8 -*-
"""Shared base for web-browser application modules.

Inspired by NVDA's ``appModules/chromium.py`` / ``appModules/firefox.py`` (and
the ``IAccessible`` overlay that backs them). In NVDA the heavy lifting for web
pages lives in the *virtual buffer* / *browse mode* subsystem, not in the app
module; the per-browser module only smooths over a few quirks (loading/busy
documents, empty accessible names on links and graphics, decorative wrapper
panes). Titan already has that subsystem -- :mod:`titan_access.browse_mode`
engages automatically for any known browser process or web framework -- so these
modules deliberately stay thin and just:

* give the browser a friendly application name, and
* tidy individual focus announcements through :meth:`customize_object`
  (compose a name for a URL-only link, label the page document).

A concrete browser subclasses :class:`BrowserModule`, sets ``process_name`` and
overrides :attr:`app_name`. ``BrowserModule`` itself is never registered with the
manager (it has no ``process_name``).
"""

from titan_access.localization import L
from titan_access.app_modules.base import AppModuleBase
from titan_access.contracts import ROLE_LINK, ROLE_DOCUMENT


class BrowserModule(AppModuleBase):
    """Base behaviour shared by every browser module. Not registered directly."""

    #: Subclasses set the executable name (lower-case, no ``.exe``).
    process_name = ""

    @property
    def app_name(self):
        return L("browser.generic")

    # ------------------------------------------------------------------ #
    def customize_object(self, obj):
        if obj is None:
            return obj
        try:
            # A link whose accessible name is empty: fall back to its URL so it
            # is announced as something rather than a bare "link" (NVDA composes
            # link text the same way).
            if obj.role == ROLE_LINK and not (obj.name or "").strip():
                url = (obj.value or obj.parameter or "").strip()
                if url:
                    obj.name = url

            # The page viewport: mark it as a web document so the user knows the
            # focus is inside web content (browse mode announces its own
            # entry, but a bare document name like the tab title is ambiguous).
            elif obj.role == ROLE_DOCUMENT and not (obj.description or "").strip():
                obj.description = L("browse.webPage")
        except Exception:
            pass
        return obj
