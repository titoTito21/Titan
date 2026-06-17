"""
Lazy, shared accessible_output3 speaker.

accessible_output3.outputs.auto.Auto() walks the entire current call stack via
inspect.getouterframes() while locating each output backend's library. Creating
it at IMPORT time - when the call stack is deep (nested imports) and hundreds of
modules are loaded - cost ~1.2s of Titan's startup (measured 2026-06; ~38% of
import time). The same Auto() created lazily from a shallow stack after startup
costs ~0.1s, and accessible_output3 caches loaded backends so further instances
are ~0.016s.

This module provides:
  - get_shared_speaker(): one Auto() for the whole app, created on first use.
  - LazySpeaker(): a drop-in replacement for `Auto()` at module scope. It defers
    construction to the first attribute access and forwards to the shared
    speaker, so existing `speaker.speak(...)` / `speaker.output(...)` call sites
    keep working unchanged.

If accessible_output3 cannot initialize at all, speech degrades to a no-op
rather than crashing - safer for an accessibility app than the previous
import-time construction (which would raise during import).
"""

import accessible_output3.outputs.auto

_shared = None


class _NullSpeaker:
    """No-op stand-in used only if accessible_output3 fails to initialize."""

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def get_shared_speaker():
    """Return the process-wide accessible_output3 speaker, created on first use."""
    global _shared
    if _shared is None:
        try:
            _shared = accessible_output3.outputs.auto.Auto()
        except Exception as e:
            print(f"[LazySpeaker] Could not initialize accessible_output3 Auto: {e}")
            _shared = _NullSpeaker()
    return _shared


class LazySpeaker:
    """Drop-in for accessible_output3.outputs.auto.Auto() that defers creation
    to first use and shares one underlying speaker across the app."""

    __slots__ = ()

    def __getattr__(self, name):
        return getattr(get_shared_speaker(), name)
