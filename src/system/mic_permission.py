# -*- coding: utf-8 -*-
"""
Microphone permission / availability checks (Windows)
====================================================

Windows never shows a consent prompt for a *desktop* (non-packaged) app, so
Titan cannot "ask" for the microphone the way a phone app does. What it CAN do
is read the Privacy setting that silently blocks capture and tell the user
exactly what to change - otherwise a voice call connects and transmits nothing,
which is indistinguishable from a broken call.

Two independent switches must both allow access:

  * ``ConsentStore\\microphone\\Value``            - the global "Microphone
    access" master switch.
  * ``ConsentStore\\microphone\\NonPackaged\\Value`` - the "Let desktop apps
    access your microphone" switch, which is the one that bites Titan.

Each holds ``"Allow"`` or ``"Deny"``. A missing value means the user never
changed the default, which is Allow.

All user-facing text is English and goes through the ``system`` gettext domain.
"""

from __future__ import annotations

import os
import sys
from typing import Optional, Tuple

from src.titan_core.translation import set_language
from src.settings.settings import get_setting

_ = set_language(get_setting('language', 'pl'))

_CONSENT_KEY = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"

# Reasons returned alongside the boolean so callers can log/report precisely.
REASON_ALLOWED = 'allowed'
REASON_GLOBAL_DENIED = 'global_denied'
REASON_DESKTOP_DENIED = 'desktop_denied'
REASON_NO_DEVICE = 'no_device'
REASON_UNKNOWN = 'unknown'


def _read_consent_value(subkey: str) -> Optional[str]:
    """Read a ConsentStore ``Value`` string, or None when it cannot be read."""
    if sys.platform != 'win32':
        return None
    try:
        import winreg
    except ImportError:
        return None

    path = _CONSENT_KEY if not subkey else _CONSENT_KEY + '\\' + subkey
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, path) as key:
                value, _type = winreg.QueryValueEx(key, 'Value')
                if isinstance(value, str) and value:
                    return value
        except OSError:
            continue
    return None


def microphone_privacy_state() -> Tuple[bool, str]:
    """Return ``(allowed, reason)`` for the Windows microphone Privacy switches.

    Non-Windows platforms always report allowed - they have no equivalent
    per-app switch that Titan can inspect.
    """
    if sys.platform != 'win32':
        return True, REASON_ALLOWED

    if (_read_consent_value('') or 'Allow') == 'Deny':
        return False, REASON_GLOBAL_DENIED
    if (_read_consent_value('NonPackaged') or 'Allow') == 'Deny':
        return False, REASON_DESKTOP_DENIED
    return True, REASON_ALLOWED


def microphone_device_available() -> Optional[bool]:
    """Return True/False when an input device could be enumerated, else None.

    None means "could not determine" (no audio backend installed) - callers
    must treat that as "do not block the call".
    """
    try:
        import sounddevice as sd
    except Exception:
        return None
    try:
        for dev in sd.query_devices():
            if int(dev.get('max_input_channels') or 0) > 0:
                return True
        return False
    except Exception:
        return None


def check_microphone() -> Tuple[bool, str]:
    """Full check: Privacy switches first, then whether any input device exists."""
    allowed, reason = microphone_privacy_state()
    if not allowed:
        return False, reason

    has_device = microphone_device_available()
    if has_device is False:
        return False, REASON_NO_DEVICE
    return True, REASON_ALLOWED


def explain(reason: str) -> str:
    """Localized, actionable explanation for a failed check."""
    if reason == REASON_GLOBAL_DENIED:
        return _("Microphone access is turned off for this computer. "
                 "Open Settings, Privacy and security, Microphone, and turn on "
                 "Microphone access.")
    if reason == REASON_DESKTOP_DENIED:
        return _("Windows is blocking desktop applications from using the "
                 "microphone. Open Settings, Privacy and security, Microphone, "
                 "and turn on Let desktop apps access your microphone.")
    if reason == REASON_NO_DEVICE:
        return _("No microphone was found. Connect a microphone or headset and "
                 "try again.")
    return _("The microphone is not available.")


def open_microphone_settings() -> bool:
    """Open the Windows microphone privacy page. Returns True when launched."""
    if sys.platform != 'win32':
        return False
    try:
        os.startfile('ms-settings:privacy-microphone')  # type: ignore[attr-defined]
        return True
    except Exception as e:
        print(f"[Mic permission] Could not open privacy settings: {e}")
        return False


def ensure_microphone_access(parent=None, announce=None) -> bool:
    """Check the microphone and, when blocked, tell the user how to fix it.

    Returns True when a call may proceed. When blocked, the user is offered the
    Windows privacy page; the call is still allowed to continue afterwards only
    if they fixed it (we re-check).

    ``announce`` is an optional ``callable(text, type)`` used for the
    screen-reader notification, so this module does not depend on any
    particular messenger's speech helper. GUI is only shown when we are on the
    wx main thread; from a worker thread the check is silent and just returns
    the boolean.
    """
    ok, reason = check_microphone()
    if ok:
        return True

    message = explain(reason)
    print(f"[Mic permission] blocked ({reason}): {message}")

    if announce is not None:
        try:
            announce(message, 'error')
        except Exception:
            pass

    try:
        import wx
    except Exception:
        return False

    app = wx.GetApp()
    if app is None or not wx.IsMainThread():
        # No GUI context - the caller already got the notification above.
        return False

    if sys.platform != 'win32':
        return False

    dlg = wx.MessageDialog(
        parent,
        message + "\n\n" + _("Do you want to open microphone settings now?"),
        _("Microphone blocked"),
        wx.YES_NO | wx.ICON_WARNING,
    )
    try:
        from src.titan_core.skin_manager import apply_skin_to_window
        apply_skin_to_window(dlg)
    except Exception:
        pass
    # MessageDialog.ShowModal() returns wx.ID_YES / wx.ID_NO - never wx.YES.
    result = dlg.ShowModal()
    dlg.Destroy()

    if result == wx.ID_YES:
        open_microphone_settings()

    # Re-check: the user may have flipped the switch while the dialog was up.
    ok_again, _reason_again = check_microphone()
    return ok_again
