# -*- coding: utf-8 -*-
"""Notices that the sound has somewhere else to go.

Windows hands a program's audio to whichever endpoint is the DEFAULT at the
moment the stream is opened, and that is the whole of the problem this module
exists for: SDL (under pygame) opens one stream when Titan starts and keeps it.
Unplug the headphones and Windows moves the default to the speakers - Titan's
stream stays pointed at an endpoint that is no longer there, so nothing is
heard; plug them back in and Titan is still on the stream it opened, so it does
not follow. For a program whose entire interface is spoken, "plays nothing" is
not a degraded experience, it is a program that has disappeared.

Nothing here touches audio. It watches the endpoints and says WHEN they
changed; :func:`src.titan_core.sound.reopen_audio` is what acts on it.

Two ways of noticing, and both are used:

* **The notification client** (``IMMNotificationClient``, through pycaw) is
  Windows telling us the moment it happens, so the switch is heard on the next
  sound rather than up to a poll away. It is registered from a thread of our
  own in the multi-threaded apartment, because a client registered in an STA
  is only called back from a message pump, and this thread has none.
* **A poll** every :data:`POLL_SECONDS` is the safety net, and it is what
  DECIDES. A notification only wakes the poll early: reading the endpoints
  costs about 0.9 ms, so being certain is cheaper than trusting a callback we
  cannot test on every machine.

What counts as a change is deliberately narrow - the default endpoint is a
different one, or the endpoint we were using is no longer active. A second
sound card appearing, or a monitor with speakers being switched on, changes
nothing about where Titan's sound is going, and re-opening the mixer for it
would cut whatever was being said mid-word.

Windows only. Everywhere else :func:`start` answers False and Titan behaves as
it always did (PulseAudio and CoreAudio both move a running stream themselves,
which is exactly what Windows does not do).
"""

import atexit
import threading
import time

from src.platform_utils import IS_WINDOWS

# How often the endpoints are read when nothing has woken us. A notification
# wakes the loop at once, so this is only the safety net for a machine where
# the callback never arrives.
POLL_SECONDS = 2.0

# How long to let the endpoints settle before acting. Plugging a jack in fires
# several notifications in a row (added, state changed, default changed) and
# Windows is still moving the default while the first of them arrives.
SETTLE_SECONDS = 0.8

_lock = threading.RLock()
_thread = None
_stop = threading.Event()
_wake = threading.Event()
_callback = None
_signature = None       # (default_id, frozenset(active ids)) as last seen
_client = None          # the registered IMMNotificationClient, if any
_enumerator = None


# --------------------------------------------------------------------------- #
# Reading the endpoints
# --------------------------------------------------------------------------- #
def _read_signature(enumerator=None):
    """(default playback id, frozenset of active playback ids), or None.

    None means the question could not be asked at all (no pycaw, no COM on
    this thread, no audio hardware) - which is not the same as "nothing has
    changed", and the caller must not treat it as a change either.
    """
    if not IS_WINDOWS:
        return None
    try:
        from pycaw.pycaw import AudioUtilities
        from pycaw.constants import DEVICE_STATE, EDataFlow, ERole

        enumerator = enumerator or AudioUtilities.GetDeviceEnumerator()
        try:
            default_id = enumerator.GetDefaultAudioEndpoint(
                EDataFlow.eRender.value, ERole.eMultimedia.value).GetId()
        except Exception:
            # No playback endpoint at all (every device unplugged). That is a
            # real state, and the id being empty is how it is recognised.
            default_id = ''
        collection = enumerator.EnumAudioEndpoints(EDataFlow.eRender.value,
                                                   DEVICE_STATE.ACTIVE.value)
        active = set()
        for index in range(collection.GetCount()):
            try:
                active.add(collection.Item(index).GetId())
            except Exception:
                continue
        return (default_id, frozenset(active))
    except Exception:
        return None


def default_playback_name():
    """The friendly name of the default playback device, for a log line."""
    if not IS_WINDOWS:
        return ''
    try:
        from pycaw.pycaw import AudioUtilities
        return str(AudioUtilities.GetSpeakers().FriendlyName or '')
    except Exception:
        return ''


def _is_change(previous, current):
    """Whether Titan's sound has to be moved.

    A different default endpoint, or the one we were using having gone away.
    Anything else - another device appearing, one we never used disappearing -
    is not about us, and re-opening the mixer for it would cut speech that is
    playing perfectly well.
    """
    if previous is None or current is None:
        return False
    old_default, _old_active = previous
    new_default, new_active = current
    if old_default != new_default:
        return True
    return bool(old_default) and old_default not in new_active


# --------------------------------------------------------------------------- #
# Windows telling us, rather than us asking
# --------------------------------------------------------------------------- #
def _register_notifications(enumerator):
    """Register an IMMNotificationClient that just wakes the poll.

    Returns the client (to unregister later) or None. Everything it might
    raise is swallowed: the poll alone is already correct, this only makes it
    prompt.
    """
    try:
        from pycaw.callbacks import MMNotificationClient

        class _Waker(MMNotificationClient):
            def on_default_device_changed(self, flow, flow_id, role,
                                          role_id, default_device_id):
                _wake.set()

            def on_device_added(self, added_device_id):
                _wake.set()

            def on_device_removed(self, removed_device_id):
                _wake.set()

            def on_device_state_changed(self, device_id, new_state,
                                        new_state_id):
                _wake.set()

            def on_property_value_changed(self, device_id, property_struct,
                                          fmtid, pid):
                pass

        client = _Waker()
        enumerator.RegisterEndpointNotificationCallback(client)
        return client
    except Exception as e:
        print(f"[AudioDevices] Endpoint notifications unavailable: {e}")
        return None


# --------------------------------------------------------------------------- #
# The watching thread
# --------------------------------------------------------------------------- #
def _watch():
    global _signature, _client, _enumerator

    # The multi-threaded apartment, and it has to be asked for before anything
    # else COM happens on this thread: importing comtypes is itself a
    # CoInitializeEx (into an STA, since Titan does not set sys.coinit_flags),
    # and asking for a different apartment afterwards answers
    # RPC_E_CHANGED_MODE. start() imports it on the CALLING thread for exactly
    # that reason. An STA here is not fatal - the poll below works in either -
    # but Windows only calls a notification client registered in an STA from a
    # message pump, and this thread has none.
    import comtypes
    try:
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    except Exception as e:
        print(f"[AudioDevices] Watching from the thread's existing "
              f"apartment: {e}")

    try:
        from pycaw.pycaw import AudioUtilities
        _enumerator = AudioUtilities.GetDeviceEnumerator()
    except Exception as e:
        print(f"[AudioDevices] Cannot enumerate the audio devices: {e}")
        _enumerator = None

    if _enumerator is not None:
        _client = _register_notifications(_enumerator)

    _signature = _read_signature(_enumerator)

    while not _stop.is_set():
        woken = _wake.wait(POLL_SECONDS)
        _wake.clear()
        if _stop.is_set():
            break

        current = _read_signature(_enumerator)
        if not _is_change(_signature, current):
            if current is not None:
                _signature = current
            continue

        # Let Windows finish moving the default before we open anything: a
        # jack being plugged in fires several notifications and the endpoint
        # that is default halfway through is not the one that will be.
        if woken:
            deadline = time.monotonic() + SETTLE_SECONDS
            while time.monotonic() < deadline and not _stop.is_set():
                _wake.wait(0.15)
                _wake.clear()
            current = _read_signature(_enumerator) or current

        _signature = current
        if _stop.is_set():
            break

        callback = _callback
        if callback is None:
            continue
        try:
            callback(current[0] if current else '')
        except Exception as e:
            print(f"[AudioDevices] Device-change handler failed: {e}")

    # Unregister before the thread ends, or Windows keeps calling into a
    # callback whose Python object nothing is holding any more.
    try:
        if _client is not None and _enumerator is not None:
            _enumerator.UnregisterEndpointNotificationCallback(_client)
    except Exception:
        pass
    _client = None
    _enumerator = None
    try:
        import comtypes
        comtypes.CoUninitialize()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Public interface
# --------------------------------------------------------------------------- #
def start(on_change):
    """Start watching. ``on_change(device_id)`` is called on a thread of ours.

    Idempotent, and True only if something is really watching.
    """
    global _thread, _callback

    if not IS_WINDOWS:
        return False
    with _lock:
        _callback = on_change
        if _thread is not None and _thread.is_alive():
            return True
        try:
            # Imported HERE, on the calling thread, and not on the watcher's:
            # importing comtypes initialises COM for whichever thread does it,
            # into an STA, and the watcher needs the multi-threaded apartment
            # to be called back by Windows at all.
            import comtypes                          # noqa: F401
            from pycaw.pycaw import AudioUtilities   # noqa: F401
        except Exception as e:
            print(f"[AudioDevices] pycaw not available, "
                  f"the sound will not follow the device: {e}")
            return False
        _stop.clear()
        _wake.clear()
        _thread = threading.Thread(target=_watch, name='TitanAudioDevices',
                                   daemon=True)
        _thread.start()
        return True


def stop(timeout=2.0):
    """Stop watching (and unregister from Windows)."""
    global _thread, _callback
    with _lock:
        thread = _thread
        _thread = None
        _callback = None
    if thread is None:
        return
    _stop.set()
    _wake.set()
    try:
        thread.join(timeout)
    except Exception:
        pass


def is_watching():
    with _lock:
        return _thread is not None and _thread.is_alive()


def check_now():
    """Ask straight away instead of waiting for the next poll."""
    _wake.set()


atexit.register(stop, 0.5)
