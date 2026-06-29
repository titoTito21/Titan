# -*- coding: utf-8 -*-
"""TCE application module.

TCE-specific reader behaviour lives here instead of in the core engine, so the
launcher is just another app module (and other apps can ship their own). The
manager treats the whole TCE process group -- the launcher process and anything
it spawns -- as one logical app keyed ``"tce"`` (see
``AppModuleManager._process_for_object`` + ``engine._pid_is_tce``), so moving
between TCE-launched windows does not fire a spurious enter/leave cue.

Behaviour (ported from the old ``engine._handle_tce_transition``):

* entering TCE  -> play the enter cue and say "Titan";
* leaving TCE   -> play the leave cue and, unless muted outside TCE, say the
  "unsupported application" message.

The very first focus of the session only establishes the baseline (no cue),
detected via ``engine._had_focus``.
"""

from titan_access.app_modules.base import AppModuleBase

try:
    from titan_access.localization import L
except Exception:  # pragma: no cover - localization always present in practice
    def L(key, *args):
        return key


class TCEModule(AppModuleBase):
    #: Synthetic process key the manager assigns to every TCE-group window.
    process_name = "tce"

    def __init__(self, engine):
        super().__init__(engine)
        self._inside = False        # currently focused inside the TCE group

    @property
    def app_name(self):
        return "Titan"

    # -- transitions ------------------------------------------------------- #
    def on_gain_focus(self, obj):
        # Called on every focus inside TCE; only the first one after entering
        # the group is a real "enter".
        if self._inside:
            return
        self._inside = True
        # Skip the cue when this is the session's very first focus (baseline).
        if not getattr(self.engine, "_had_focus", False):
            return
        self._play_enter()

    def on_lose_focus(self, obj):
        was_inside = self._inside
        self._inside = False
        super().on_lose_focus(obj)   # resets the base _activated flag
        if not was_inside:
            return
        if not getattr(self.engine, "_had_focus", False):
            return
        self._play_leave()

    # -- cues -------------------------------------------------------------- #
    def _play_enter(self):
        try:
            if self.engine.settings.tce_entry_sound and self.engine.sound is not None:
                try:
                    self.engine.sound.play_enter_tce()
                except Exception:
                    pass
            self.engine.speak("Titan", interrupt=False)
        except Exception as e:
            print(f"[TitanAccess] tce enter cue error: {e}")

    def _play_leave(self):
        try:
            if self.engine.settings.tce_entry_sound and self.engine.sound is not None:
                try:
                    self.engine.sound.play_leave_tce()
                except Exception:
                    pass
            if not self.engine.settings.mute_outside_tce:
                self.engine.speak(L("engine.unsupportedApp"), interrupt=False)
        except Exception as e:
            print(f"[TitanAccess] tce leave cue error: {e}")
