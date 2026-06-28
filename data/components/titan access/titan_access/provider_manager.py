# -*- coding: utf-8 -*-
"""Accessibility provider manager for Titan Access.

Python port of the C# ``Accessibility/AccessibilityProviderManager.cs``,
generalised toward how NVDA chooses an API per object: **UI Automation is the
primary backend**, and **MSAA is the automatic fallback** for windows where UIA
exposes nothing useful (legacy Win32 apps). The two run side by side and feed a
single focus stream to the engine; duplicates (the same control surfaced by both
APIs at nearly the same moment) are collapsed so the user hears one announcement.

Selection is automatic and per-focus, like NVDA — there is no manual switch:

* UIA focus events are emitted immediately (primary).
* MSAA focus/foreground events are debounced briefly; if an equivalent UIA
  announcement was just emitted for the same control, the MSAA one is dropped.
  When UIA stayed silent (it could not see the control), the MSAA event passes
  through, so the legacy window is still read.

The manager exposes the same surface the engine used on the bare UIA provider
(``add_focus_listener`` / ``start`` / ``stop`` / ``get_focused_object`` /
``element_to_object`` / ``object_from_*``) so it is a drop-in replacement.
"""

import threading
import time
from typing import List, Optional

from titan_access.contracts import AccessibleObject, FocusCallback

# Window within which an MSAA event is treated as a duplicate of a UIA one.
_DEDUP_WINDOW = 0.35
# Delay before an MSAA event is emitted, giving the (faster, richer) UIA event a
# chance to arrive first and claim the focus change.
_MSAA_DEBOUNCE = 0.12
# If UIA emitted a focus event within this many seconds, MSAA stays completely
# silent: UIA owns this app and an MSAA snapshot (native=None) must never replace
# the live current object. MSAA only speaks for genuinely UIA-less windows.
_UIA_QUIET = 0.6


class ProviderManager:
    """Coordinates the UIA (primary) and MSAA (fallback) providers."""

    def __init__(self):
        self._listeners: List[FocusCallback] = []
        self._lock = threading.RLock()

        # Dedup state: identity + time of the last emitted announcement.
        self._last_key = None
        self._last_time = 0.0
        # Time of the last UIA focus event (any), used to keep MSAA silent while
        # UIA is actively reporting an app.
        self._last_uia_time = 0.0

        # Build the providers defensively; either may be unavailable.
        self.uia = self._make_uia()
        self.msaa = self._make_msaa()

    # ------------------------------------------------------------------ #
    def _make_uia(self):
        try:
            from titan_access.uia_focus import UIAProvider
            p = UIAProvider()
            p.add_focus_listener(self._on_uia)
            return p
        except Exception as e:
            print(f"[TitanAccess] provider_manager: UIA unavailable: {e}")
            return None

    def _make_msaa(self):
        # Allow disabling the MSAA fallback entirely (General/EnableMSAA).
        try:
            from titan_access.settings_store import get_settings
            if not get_settings().get_bool("General", "EnableMSAA", True):
                return None
        except Exception:
            pass
        try:
            from titan_access.msaa_focus import MSAAProvider
            p = MSAAProvider()
            if not getattr(p, "available", False):
                return None
            p.add_focus_listener(self._on_msaa)
            return p
        except Exception as e:
            print(f"[TitanAccess] provider_manager: MSAA unavailable: {e}")
            return None

    # ------------------------------------------------------------------ #
    # Provider surface (drop-in for the bare UIA provider)
    # ------------------------------------------------------------------ #
    def add_focus_listener(self, callback: FocusCallback) -> None:
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def start(self) -> bool:
        ok = False
        if self.uia is not None:
            try:
                ok = bool(self.uia.start()) or ok
            except Exception as e:
                print(f"[TitanAccess] provider_manager: UIA start error: {e}")
        if self.msaa is not None:
            try:
                started = self.msaa.start()
                ok = ok or bool(started)
            except Exception as e:
                print(f"[TitanAccess] provider_manager: MSAA start error: {e}")
        return ok

    def stop(self) -> None:
        for p in (self.uia, self.msaa):
            if p is not None:
                try:
                    p.stop()
                except Exception:
                    pass

    def get_focused_object(self) -> Optional[AccessibleObject]:
        # Prefer UIA; fall back to MSAA when UIA has nothing.
        if self.uia is not None:
            try:
                obj = self.uia.get_focused_object()
                if obj is not None and (obj.name or obj.role not in ("pane", "unknown")):
                    return obj
            except Exception:
                pass
        if self.msaa is not None:
            try:
                return self.msaa.get_focused_object()
            except Exception:
                pass
        return None

    def element_to_object(self, element):
        # Element -> snapshot is a UIA concept (object navigation passes UIA
        # Controls); MSAA navigation is not element-based.
        if self.uia is not None and hasattr(self.uia, "element_to_object"):
            return self.uia.element_to_object(element)
        return None

    def object_from_point(self, x, y):
        if self.uia is not None and hasattr(self.uia, "object_from_point"):
            obj = self.uia.object_from_point(x, y)
            if obj is not None:
                return obj
        if self.msaa is not None and hasattr(self.msaa, "object_from_point"):
            return self.msaa.object_from_point(x, y)
        return None

    def object_from_handle(self, hwnd):
        if self.uia is not None and hasattr(self.uia, "object_from_handle"):
            return self.uia.object_from_handle(hwnd)
        return None

    # ------------------------------------------------------------------ #
    # Focus routing + dedup
    # ------------------------------------------------------------------ #
    def _on_uia(self, obj: AccessibleObject) -> None:
        # UIA is primary: emit at once, recording identity so a near-simultaneous
        # MSAA duplicate is suppressed, and stamping the UIA-active time so MSAA
        # stays silent for this app.
        with self._lock:
            self._last_uia_time = time.time()
        if self._claim(obj):
            self._emit(obj)

    def _on_msaa(self, obj: AccessibleObject) -> None:
        # Debounce, then emit only if UIA has been silent (this is a genuinely
        # UIA-less window). Never let an MSAA snapshot (native=None) replace a
        # live UIA object, which would break caret / object / browse navigation.
        def _do():
            time.sleep(_MSAA_DEBOUNCE)
            with self._lock:
                uia_recent = (time.time() - self._last_uia_time) < _UIA_QUIET
            if uia_recent:
                return
            if self._claim(obj):
                self._emit(obj)
        threading.Thread(target=_do, daemon=True).start()

    def _claim(self, obj) -> bool:
        """Return True if *obj* is a fresh announcement (not a cross-API dup)."""
        key = (obj.name or "", obj.role, obj.bounds)
        now = time.time()
        with self._lock:
            if self._last_key == key and (now - self._last_time) < _DEDUP_WINDOW:
                self._last_time = now
                return False
            self._last_key = key
            self._last_time = now
        return True

    def _emit(self, obj) -> None:
        for cb in list(self._listeners):
            try:
                cb(obj)
            except Exception as e:
                print(f"[TitanAccess] provider_manager: listener error: {e}")


def get_provider_manager() -> ProviderManager:
    return ProviderManager()
