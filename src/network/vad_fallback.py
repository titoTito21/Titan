# -*- coding: utf-8 -*-
"""
Pure-Python Voice Activity Detection
====================================

``webrtcvad`` (and its ``webrtcvad-wheels`` fork) is a C extension that has no
wheels for current Python versions - the fork has been unmaintained since
September 2024, so on Python 3.14 there is nothing to install. Titan used to
respond by silently turning Voice Activation off and transmitting continuously,
which means every voice-room participant sits there with a permanently open
microphone: room noise, keyboard, TTS bleed, everything.

This module is the alternative: a VAD with no compiled dependency, exposing the
same surface Titan already used, so it drops straight into
:mod:`src.network.voice_capture`::

    vad = Vad(aggressiveness)          # 0..3, same meaning as webrtcvad
    vad.is_speech(pcm_bytes, sample_rate) -> bool

How it decides
--------------
Two cheap features per frame, both robust for 16-bit mono PCM:

* **Short-term energy (RMS)** compared against an adaptively tracked noise
  floor. The floor follows the quietest recent frames, so it survives a noisy
  room, a fan, or a hissy USB microphone without needing calibration.
* **Zero-crossing rate (ZCR)** to keep unvoiced consonants (s, f, sh) which
  carry little energy but cross zero often, and to reject the low-frequency
  rumble of desk bumps.

A short hangover keeps ``is_speech`` true across the natural gaps inside a word,
so the caller's own speech-start/stop counters behave like they did with
webrtcvad.

``numpy`` is used when present (it is a hard Titan dependency) and there is a
pure-``array`` fallback, so this module works even in a stripped environment.
"""

from __future__ import annotations

import math
from array import array
from typing import Optional

try:
    import numpy as _np
except Exception:  # pragma: no cover - numpy is a Titan dependency
    _np = None

# Frame sizes webrtcvad accepted, kept so callers can validate identically.
VALID_SAMPLE_RATES = (8000, 16000, 32000, 48000)
VALID_FRAME_MS = (10, 20, 30)

# Per-aggressiveness tuning. Higher = more eager to call something silence,
# matching webrtcvad's 0 (most tolerant) .. 3 (most aggressive) scale.
_PROFILES = {
    0: {'snr_db': 4.0,  'abs_floor': 120.0, 'hangover': 8},
    1: {'snr_db': 6.0,  'abs_floor': 160.0, 'hangover': 6},
    2: {'snr_db': 8.5,  'abs_floor': 220.0, 'hangover': 5},
    3: {'snr_db': 11.0, 'abs_floor': 300.0, 'hangover': 4},
}


def _frame_features(pcm_bytes: bytes):
    """Return ``(rms, zero_crossing_rate)`` for 16-bit little-endian mono PCM."""
    if len(pcm_bytes) < 4:
        return 0.0, 0.0

    # Odd trailing byte would break int16 framing.
    if len(pcm_bytes) % 2:
        pcm_bytes = pcm_bytes[:-1]

    if _np is not None:
        samples = _np.frombuffer(pcm_bytes, dtype='<i2').astype(_np.float32)
        if samples.size == 0:
            return 0.0, 0.0
        rms = float(_np.sqrt(_np.mean(samples * samples)))
        signs = _np.signbit(samples)
        crossings = int(_np.count_nonzero(signs[1:] != signs[:-1]))
        zcr = crossings / float(samples.size - 1) if samples.size > 1 else 0.0
        return rms, zcr

    samples = array('h')
    samples.frombytes(pcm_bytes)
    if not len(samples):
        return 0.0, 0.0
    total = 0.0
    crossings = 0
    previous_negative = samples[0] < 0
    for value in samples:
        total += float(value) * float(value)
        negative = value < 0
        if negative != previous_negative:
            crossings += 1
            previous_negative = negative
    rms = math.sqrt(total / len(samples))
    zcr = crossings / float(len(samples) - 1) if len(samples) > 1 else 0.0
    return rms, zcr


class Vad:
    """Energy + zero-crossing VAD with an adaptive noise floor.

    API-compatible with ``webrtcvad.Vad`` for the single call Titan makes.
    """

    def __init__(self, aggressiveness: int = 0):
        self.set_mode(aggressiveness)
        # Noise floor starts pessimistically low and rises to meet the room.
        self._noise_floor: Optional[float] = None
        self._hangover_left = 0
        self._frames_seen = 0

    # webrtcvad spells it set_mode(); keep the same name.
    def set_mode(self, aggressiveness: int) -> None:
        if aggressiveness not in _PROFILES:
            raise ValueError("aggressiveness must be 0, 1, 2 or 3")
        self.aggressiveness = int(aggressiveness)
        profile = _PROFILES[self.aggressiveness]
        self._snr_db = profile['snr_db']
        self._abs_floor = profile['abs_floor']
        self._hangover_frames = profile['hangover']

    def reset(self) -> None:
        """Forget the learned noise floor (use when the device changes)."""
        self._noise_floor = None
        self._hangover_left = 0
        self._frames_seen = 0

    @property
    def noise_floor(self) -> float:
        return float(self._noise_floor or 0.0)

    def is_speech(self, buf: bytes, sample_rate: int) -> bool:
        """Return True when the frame plausibly contains speech.

        ``sample_rate`` is validated the way webrtcvad validated it so a caller
        passing an unsupported rate fails loudly instead of silently mis-gating.
        """
        if sample_rate not in VALID_SAMPLE_RATES:
            raise ValueError(f"unsupported sample rate: {sample_rate}")

        rms, zcr = _frame_features(buf)
        self._frames_seen += 1

        if self._noise_floor is None:
            self._noise_floor = max(rms, 1.0)

        floor = max(self._noise_floor, 1.0)
        snr_db = 20.0 * math.log10(rms / floor) if rms > 0 else -60.0

        # Speech needs to stand above both the learned floor and an absolute
        # gate - the latter stops a dead-silent room (tiny floor) from turning
        # faint hiss into "speech".
        loud_enough = (snr_db >= self._snr_db) and (rms >= self._abs_floor)

        # Unvoiced consonants: quieter, but far more zero crossings than rumble.
        fricative = (
            zcr >= 0.18
            and rms >= self._abs_floor * 0.45
            and snr_db >= self._snr_db * 0.55
        )

        # Very low ZCR with high energy is a thump/handling noise, not voice.
        rumble = zcr < 0.015 and snr_db < self._snr_db * 2.0

        voiced = (loud_enough or fricative) and not rumble

        if voiced:
            self._hangover_left = self._hangover_frames
        else:
            # Track the floor only on non-speech frames so speech cannot drag
            # it upward. Rise slowly, fall quickly (adapts when noise stops).
            if rms < floor:
                self._noise_floor = floor + (rms - floor) * 0.35
            else:
                self._noise_floor = floor + (rms - floor) * 0.02

            if self._hangover_left > 0:
                self._hangover_left -= 1
                return True

        return bool(voiced)


def get_vad(aggressiveness: int = 0):
    """Return the best VAD available: real webrtcvad if importable, else ours.

    Returns ``(vad, backend_name)``. ``vad`` is never None - Titan should always
    be able to offer Voice Activation.
    """
    try:
        import webrtcvad as _webrtcvad
        vad = _webrtcvad.Vad(aggressiveness)
        # Prove the extension actually works before trusting it: a broken or
        # stubbed install raises here rather than mid-call.
        vad.is_speech(b'\x00\x00' * 160, 16000)
        return vad, 'webrtcvad'
    except Exception:
        pass
    return Vad(aggressiveness), 'builtin'
