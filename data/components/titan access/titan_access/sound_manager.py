# -*- coding: utf-8 -*-
"""UI sound output for Titan Access.

Python port of the C# ``ScreenReader.SoundManager``. Plays the OGG cue files
bundled in the component's ``sfx/`` folder (cursor moves, clicks, edges, window
changes, menu open/close, toggle keys, ...). Two differences from the C# version,
both required by the Titan port:

* The original embedded the OGGs as assembly resources; here they are plain
  files in ``sfx/`` and loaded through :mod:`pygame.mixer` (already a Titan
  dependency), with each decoded sound cached.
* Sounds are **always** stereo-positioned to the element's screen location
  (``pan`` -1..1), independent of the virtual-screen setting. The C#
  ``StereoPanningSampleProvider`` left/right gain formula is reproduced exactly;
  when Titan's OpenAL HRTF backend is available it is used instead for true
  azimuth + elevation positioning.

The global on/off flag and per-instance ``enabled`` flag mirror the C#
``GlobalSoundsEnabled`` static and the instance gate.

This module emits no user-facing text, so it needs no localization keys.
"""

import os
import threading

from titan_access.contracts import (
    pan_for_object, elevation_for_object,
    SND_SR_ON, SND_SR_OFF, SND_CURSOR, SND_CURSOR_STATIC, SND_SR_CURSOR_ITEM,
    SND_CLICK, SND_DOUBLE_TAP, SND_EDGE, SND_LIST_ITEM, SND_SYSTEM_ITEM,
    SND_CAN_INTERACT, SND_ERROR, SND_NOTIFICATION, SND_KEY_ON, SND_KEY_OFF,
    SND_WINDOW, SND_MENU, SND_MENU_CLOSE, SND_MENU_EXPANDED, SND_MENU_CLOSED,
    SND_ENTER_TCE, SND_LEAVE_TCE, SND_VSCREEN_ON, SND_VSCREEN_OFF,
    SND_ZOOM_IN, SND_ZOOM_OUT,
)

# pygame is a Titan dependency, but import defensively so the reader still loads
# (silently, soundless) on a box without an audio device / pygame.
try:
    import pygame
except Exception:  # pragma: no cover - audio optional
    pygame = None


def _clamp(value, low, high):
    return max(low, min(high, value))


class SoundManager(object):
    """Sound backend implementing :class:`titan_access.contracts.SoundLike`.

    Port of the C# ``SoundManager``: fire-and-forget overlapping playback of the
    bundled OGG cues, always panned to the element position.
    """

    #: Global mute switch (port of C# ``SoundManager.GlobalSoundsEnabled``).
    #: Set ``SoundManager.GlobalSoundsEnabled = False`` to silence every instance.
    GlobalSoundsEnabled = True

    def __init__(self, sfx_dir):
        #: Directory holding the component's ``*.ogg`` cue files.
        self.sfx_dir = sfx_dir
        #: Per-instance gate (the C# ``_globalSoundsEnabled`` field).
        self.enabled = True

        self._lock = threading.RLock()
        self._cache = {}            # filename -> pygame Sound
        self._pitch_cache = {}      # (filename, pitch_bucket) -> pygame Sound
        self._active_channels = []  # channels we have played on (for stop_all)
        self._mixer_ok = False

        self._ensure_mixer()

    # ------------------------------------------------------------------ #
    # Mixer / loading
    # ------------------------------------------------------------------ #
    def _ensure_mixer(self):
        """Initialise audio defensively, reusing Titan's mixer when present.

        Never raises: a missing audio device just leaves the manager silent.
        """
        if pygame is None:
            self._mixer_ok = False
            return False
        # Prefer Titan's own initialisation (sets up its channel layout too).
        try:
            from src.titan_core import sound as titan_sound
            if titan_sound.initialize_sound():
                self._mixer_ok = pygame.mixer.get_init() is not None
                if self._mixer_ok:
                    return True
        except Exception:
            pass
        # Standalone: bring the mixer up ourselves if nobody else has.
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.pre_init(frequency=44100, size=-16, channels=2,
                                      buffer=512)
                pygame.mixer.init()
            self._mixer_ok = pygame.mixer.get_init() is not None
        except Exception as e:  # pragma: no cover
            print(f"[TitanAccess] mixer init failed: {e}")
            self._mixer_ok = False
        return self._mixer_ok

    def _resolve(self, name):
        """Return the absolute path of a cue file, or None if it is missing."""
        if not name:
            return None
        path = name if os.path.isabs(name) else os.path.join(self.sfx_dir, name)
        return path if os.path.exists(path) else None

    def _load(self, name):
        """Load and cache the pygame Sound for ``name`` (None on failure)."""
        with self._lock:
            snd = self._cache.get(name)
            if snd is not None:
                return snd
            path = self._resolve(name)
            if path is None:
                print(f"[TitanAccess] missing sound: {name}")
                return None
            try:
                snd = pygame.mixer.Sound(path)
                self._cache[name] = snd
                return snd
            except Exception as e:  # pragma: no cover
                print(f"[TitanAccess] failed to load sound {path}: {e}")
                return None

    # ------------------------------------------------------------------ #
    # Core playback
    # ------------------------------------------------------------------ #
    def play(self, name, pan=0.0, elevation=0.0, gain=1.0, pitch=1.0):
        """Play cue ``name`` stereo-panned to ``pan`` (-1 left .. 1 right).

        ``elevation`` (-1 bottom .. 1 top) is only used by the optional HRTF
        backend. ``gain`` scales volume (0..1). ``pitch`` (1.0 = normal) is an
        internal extension used by :meth:`play_list_item`; it is applied only
        when numpy is available, otherwise the cue plays at normal pitch.
        Respects both :attr:`enabled` and :attr:`GlobalSoundsEnabled`.
        """
        if not SoundManager.GlobalSoundsEnabled or not self.enabled:
            return
        if not self._mixer_ok and not self._ensure_mixer():
            return

        pan = _clamp(float(pan), -1.0, 1.0)
        gain = _clamp(float(gain), 0.0, 1.0)

        path = self._resolve(name)
        if path is None:
            print(f"[TitanAccess] missing sound: {name}")
            return

        # 1) Prefer Titan's OpenAL HRTF backend for true azimuth + elevation.
        #    Its pan convention is 0.0 (left) .. 1.0 (right), so convert.
        if abs(pitch - 1.0) <= 0.01:
            try:
                from src.titan_core.sound import _try_spatial_play
                titan_pan = (pan + 1.0) / 2.0
                if _try_spatial_play(path, titan_pan, elevation, gain):
                    return
            except Exception:
                pass  # fall through to pygame stereo panning

        # 2) pygame stereo panning (C# StereoPanningSampleProvider gain formula).
        snd = self._maybe_pitched(name, pitch)
        if snd is None:
            return
        try:
            left = min(1.0, 1.0 - pan) * gain
            right = min(1.0, 1.0 + pan) * gain
            with self._lock:
                channel = pygame.mixer.find_channel()  # non-stealing, allow overlap
                if channel is None:
                    return
                channel.set_volume(_clamp(left, 0.0, 1.0), _clamp(right, 0.0, 1.0))
                channel.play(snd)
                self._active_channels.append(channel)
                # Trim the bookkeeping list of finished channels.
                self._active_channels = [c for c in self._active_channels
                                         if c is channel or c.get_busy()]
        except Exception as e:  # pragma: no cover
            print(f"[TitanAccess] failed to play {name}: {e}")

    def play_positioned(self, name, obj):
        """Play ``name`` panned to ``obj``'s screen position.

        Pan and elevation come from :func:`contracts.pan_for_object` /
        :func:`contracts.elevation_for_object`. Sounds are always positioned,
        regardless of the virtual-screen setting.
        """
        pan = pan_for_object(obj)
        elevation = elevation_for_object(obj)
        self.play(name, pan=pan, elevation=elevation)

    def stop_all(self):
        """Stop every cue this manager started (leaves other channels alone)."""
        with self._lock:
            for channel in self._active_channels:
                try:
                    channel.stop()
                except Exception:
                    pass
            self._active_channels = []

    # Compatibility alias for the C# ``Stop`` / disposable pattern.
    def stop(self):
        self.stop_all()

    def dispose(self):
        self.stop_all()
        with self._lock:
            self._cache.clear()
            self._pitch_cache.clear()

    # ------------------------------------------------------------------ #
    # Optional pitch shifting (for list-item position cue)
    # ------------------------------------------------------------------ #
    def _maybe_pitched(self, name, pitch):
        """Return a (cached) pitch-shifted Sound, or the original at pitch 1.0.

        Pitch shifting resamples via numpy when available (port of the C#
        ``PitchShiftingSampleProvider``); without numpy the cue plays normally.
        """
        if abs(pitch - 1.0) <= 0.01:
            return self._load(name)
        bucket = round(_clamp(pitch, 0.5, 2.0), 2)
        key = (name, bucket)
        with self._lock:
            cached = self._pitch_cache.get(key)
            if cached is not None:
                return cached
        base = self._load(name)
        if base is None:
            return None
        try:
            import numpy as np
            samples = pygame.sndarray.array(base)
            # Linear-interpolation resample: >1 pitch => shorter => higher tone.
            n = samples.shape[0]
            new_len = max(1, int(n / bucket))
            src_idx = np.arange(new_len) * bucket
            base_idx = np.clip(src_idx.astype(np.int64), 0, n - 1)
            if samples.ndim == 1:
                shifted = samples[base_idx]
            else:
                shifted = samples[base_idx, :]
            shifted = np.ascontiguousarray(shifted.astype(samples.dtype))
            snd = pygame.sndarray.make_sound(shifted)
            with self._lock:
                self._pitch_cache[key] = snd
            return snd
        except Exception:
            # numpy / sndarray unavailable — fall back to normal pitch.
            return base

    # ------------------------------------------------------------------ #
    # Named convenience helpers (mirror the C# Play* methods) — thin wrappers
    # ------------------------------------------------------------------ #
    def play_sr_on(self, pan=0.0, elevation=0.0):
        self.play(SND_SR_ON, pan, elevation)

    def play_sr_off(self, pan=0.0, elevation=0.0):
        self.play(SND_SR_OFF, pan, elevation)

    def play_cursor(self, pan=0.0, elevation=0.0):
        self.play(SND_CURSOR, pan, elevation)

    def play_cursor_static(self, pan=0.0, elevation=0.0):
        self.play(SND_CURSOR_STATIC, pan, elevation)

    def play_dial_item(self, pan=0.0, elevation=0.0):
        self.play(SND_SR_CURSOR_ITEM, pan, elevation)

    def play_clicked(self, pan=0.0, elevation=0.0):
        self.play(SND_CLICK, pan, elevation)

    def play_double_tap(self, pan=0.0, elevation=0.0):
        self.play(SND_DOUBLE_TAP, pan, elevation)

    def play_edge(self, pan=0.0, elevation=0.0):
        self.play(SND_EDGE, pan, elevation)

    def play_list_item(self, position=0.0, pan=0.0, elevation=0.0):
        """Play the list-item cue, pitched by vertical ``position``.

        ``position``: 0.0 = top (higher pitch) .. 1.0 = bottom (lower pitch),
        mapped to pitch 1.5 .. 0.7 exactly like the C# ``PlayListItem``.
        """
        pitch = 1.5 - (_clamp(float(position), 0.0, 1.0) * 0.8)
        self.play(SND_LIST_ITEM, pan, elevation, pitch=pitch)

    def play_system_item(self, pan=0.0, elevation=0.0):
        self.play(SND_SYSTEM_ITEM, pan, elevation)

    def play_can_interact(self, pan=0.0, elevation=0.0):
        self.play(SND_CAN_INTERACT, pan, elevation)

    def play_error(self, pan=0.0, elevation=0.0):
        self.play(SND_ERROR, pan, elevation)

    def play_notification(self, pan=0.0, elevation=0.0):
        self.play(SND_NOTIFICATION, pan, elevation)

    def play_key_on(self, pan=0.0, elevation=0.0):
        self.play(SND_KEY_ON, pan, elevation)

    def play_key_off(self, pan=0.0, elevation=0.0):
        self.play(SND_KEY_OFF, pan, elevation)

    def play_window(self, pan=0.0, elevation=0.0):
        self.play(SND_WINDOW, pan, elevation)

    def play_menu(self, pan=0.0, elevation=0.0):
        self.play(SND_MENU, pan, elevation)

    def play_menu_close(self, pan=0.0, elevation=0.0):
        self.play(SND_MENU_CLOSE, pan, elevation)

    def play_menu_expanded(self, pan=0.0, elevation=0.0):
        self.play(SND_MENU_EXPANDED, pan, elevation)

    def play_menu_closed(self, pan=0.0, elevation=0.0):
        self.play(SND_MENU_CLOSED, pan, elevation)

    def play_enter_tce(self, pan=0.0, elevation=0.0):
        self.play(SND_ENTER_TCE, pan, elevation)

    def play_leave_tce(self, pan=0.0, elevation=0.0):
        self.play(SND_LEAVE_TCE, pan, elevation)

    def play_vscreen_on(self, pan=0.0, elevation=0.0):
        self.play(SND_VSCREEN_ON, pan, elevation)

    def play_vscreen_off(self, pan=0.0, elevation=0.0):
        self.play(SND_VSCREEN_OFF, pan, elevation)

    def play_zoom_in(self, pan=0.0, elevation=0.0):
        self.play(SND_ZOOM_IN, pan, elevation)

    def play_zoom_out(self, pan=0.0, elevation=0.0):
        self.play(SND_ZOOM_OUT, pan, elevation)


# --------------------------------------------------------------------------- #
# Module factory
# --------------------------------------------------------------------------- #
def get_sound(sfx_dir):
    """Build a :class:`SoundManager` for the given ``sfx`` directory."""
    return SoundManager(sfx_dir)
