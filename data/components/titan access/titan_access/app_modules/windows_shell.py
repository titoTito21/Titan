# -*- coding: utf-8 -*-
"""Windows' own shell surfaces: the Start menu, Search, the notification
centre, the emoji panel, the lock screen, sign-in and the UAC prompt.

In the spirit of NVDA's ``searchui``, ``searchhost``, ``lockapp`` and
``logonui`` app modules: each of these is a window with no title a user
would recognise (``Windows.UI.Core.CoreWindow``, ``XamlExplorerHost``),
and the one thing a reader can add is to say WHERE the user has arrived,
once, before the first control is read. Everything inside them is WinUI
and reads through UI Automation as it is.

The Alt+Tab switcher is explorer's own window and is handled in
:mod:`titan_access.app_modules.explorer`.
"""

from titan_access.localization import L
from titan_access.app_modules.base import AppModuleBase


class ShellHostModule(AppModuleBase):
    """The Start menu, Search, Action Centre and the emoji panel."""

    process_names = {
        "startmenuexperiencehost", "searchhost", "searchui", "searchapp",
        "shellexperiencehost", "textinputhost",
    }
    process_name = "startmenuexperiencehost"

    #: What each process IS, in the user's own words.
    _PLACES = {
        "startmenuexperiencehost": "shell.startMenu",
        "searchhost": "shell.search",
        "searchui": "shell.search",
        "searchapp": "shell.search",
        "shellexperiencehost": "shell.notifications",
        "textinputhost": "shell.emojiPanel",
    }

    def __init__(self, engine):
        super().__init__(engine)
        self._where = ""

    @property
    def app_name(self):
        return L(self._PLACES.get(self._where, "shell.startMenu"))

    def note_process(self, process_name):
        """The manager registers one instance for several executables;
        remember which one is in front so the welcome names it."""
        self._where = (process_name or "").lower()

    def on_gain_focus(self, obj):
        # The process is resolved by the manager; the object carries its
        # process id, and the manager tells us the name through
        # ``current_process`` when it switches.
        try:
            manager = getattr(self.engine, "app_modules", None)
            current = getattr(manager, "_current_process", "") if manager else ""
            if current in self._PLACES:
                self._where = current
        except Exception:
            pass
        self._announce_welcome_once(self.app_name)

    def customize_object(self, obj):
        if obj is None:
            return obj
        # A search suggestion is a list item whose name is the whole
        # suggestion; Windows sometimes repeats it in the description.
        try:
            if (obj.role == "listitem" and obj.description
                    and obj.description.strip() == (obj.name or "").strip()):
                obj.description = ""
        except Exception:
            pass
        return obj


class LogonModule(AppModuleBase):
    """The lock screen, the sign-in screen, a credential prompt, UAC."""

    process_names = {"lockapp", "logonui", "credentialuibroker",
                     "consent", "credentialuihost"}
    process_name = "logonui"

    _PLACES = {
        "lockapp": "logon.lockScreen",
        "logonui": "logon.signIn",
        "credentialuibroker": "logon.credentials",
        "credentialuihost": "logon.credentials",
        "consent": "logon.uac",
    }

    def __init__(self, engine):
        super().__init__(engine)
        self._where = ""

    @property
    def app_name(self):
        return L(self._PLACES.get(self._where, "logon.signIn"))

    def on_gain_focus(self, obj):
        try:
            manager = getattr(self.engine, "app_modules", None)
            current = getattr(manager, "_current_process", "") if manager else ""
            if current in self._PLACES:
                self._where = current
        except Exception:
            pass
        self._announce_welcome_once(self.app_name)

    def customize_object(self, obj):
        if obj is None:
            return obj
        # The PIN / password field on the sign-in screen is a password
        # edit with no name of its own on some builds; say what it is.
        try:
            if obj.role == "password" and not (obj.name or "").strip():
                obj.name = L("logon.passwordField")
        except Exception:
            pass
        return obj
