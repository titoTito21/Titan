"""
sound_calibration.py - Room acoustics calibration for the 3D sound mode.

Plays a short broadband test burst through the speakers while recording the
room's response with the microphone, estimates the reverberation time (RT60)
from the decay tail (Schroeder backward integration), maps it to OpenAL EFX
reverb parameters, persists them under [sound], and applies them so 3D audio
and Titan TTS gain a room-appropriate echo.

Requires sounddevice (microphone) and numpy. Degrades to a clear failure when
no input device is available or the captured signal is too weak to analyse.
"""

import numpy as np

from src.settings.settings import set_setting


def _estimate_rt60(decay, fs):
    """Estimate RT60 (seconds) from a decay signal via Schroeder integration.

    Returns the RT60 estimate, or None if the decay is too weak/short to fit.
    """
    energy = decay.astype(np.float64) ** 2
    total = np.sum(energy)
    if total <= 1e-9:
        return None
    # Schroeder energy decay curve (backward cumulative integral), in dB.
    edc = np.cumsum(energy[::-1])[::-1]
    edc = edc / edc[0]
    edc_db = 10.0 * np.log10(np.maximum(edc, 1e-12))

    # Fit the slope over the -5 dB .. -25 dB region (T20), extrapolate to 60 dB.
    try:
        i_start = int(np.argmax(edc_db <= -5.0))
        i_end = int(np.argmax(edc_db <= -25.0))
    except Exception:
        return None
    if i_end <= i_start + 10:
        return None  # not enough usable decay range (low SNR / dead room)

    t = np.arange(i_start, i_end) / fs
    y = edc_db[i_start:i_end]
    slope = np.polyfit(t, y, 1)[0]  # dB per second (negative)
    if slope >= -1e-3:
        return None
    rt60 = -60.0 / slope
    if not np.isfinite(rt60) or rt60 <= 0.0:
        return None
    return float(rt60)


def measure_room():
    """Play a test burst, record the response, and return the estimated RT60.

    Returns the RT60 in seconds. Raises RuntimeError on any failure (no mic,
    silent capture, unanalysable decay).
    """
    try:
        import sounddevice as sd
    except Exception as e:
        raise RuntimeError(f"sounddevice unavailable: {e}")

    # Pick a samplerate the default devices support.
    try:
        fs = int(sd.query_devices(kind='output')['default_samplerate']) or 48000
    except Exception:
        fs = 48000

    rng = np.random.default_rng()
    burst = (rng.uniform(-1.0, 1.0, int(fs * 0.35)).astype(np.float32)) * 0.6
    tail = np.zeros(int(fs * 1.65), dtype=np.float32)
    signal = np.concatenate([burst, tail]).reshape(-1, 1)

    try:
        rec = sd.playrec(signal, samplerate=fs, channels=1, dtype='float32')
        sd.wait()
    except Exception as e:
        raise RuntimeError(f"playback/record failed: {e}")

    rec = np.asarray(rec).reshape(-1)
    if rec.size == 0 or float(np.max(np.abs(rec))) < 1e-4:
        raise RuntimeError("captured signal too weak (check microphone)")

    # Analyse the decay starting just after the burst ends.
    decay = rec[len(burst):]
    if decay.size < int(fs * 0.1):
        raise RuntimeError("recording too short")

    rt60 = _estimate_rt60(decay, fs)
    if rt60 is None:
        raise RuntimeError("could not estimate reverberation time")
    # Clamp to a sane room range.
    return max(0.15, min(4.0, rt60))


def _params_from_rt60(rt60):
    """Map an RT60 estimate to (decay_time, wet_gain) reverb parameters."""
    decay_time = max(0.2, min(3.0, rt60))
    # Larger/livelier rooms get a slightly wetter mix; keep it subtle.
    wet_gain = max(0.18, min(0.5, 0.18 + min(rt60, 2.0) * 0.14))
    return decay_time, wet_gain


def calibrate():
    """Measure the room, persist + apply the reverb, and return a result dict.

    Returns {'rt60', 'decay', 'gain'} on success. Raises RuntimeError on failure.
    """
    rt60 = measure_room()
    decay_time, wet_gain = _params_from_rt60(rt60)

    # Persist under [sound] so it is reapplied on future launches.
    set_setting('reverb_enabled', 'True', 'sound')
    set_setting('reverb_decay', f"{decay_time:.3f}", 'sound')
    set_setting('reverb_gain', f"{wet_gain:.3f}", 'sound')

    # Apply immediately to the running spatial backend.
    try:
        from src.titan_core import spatial_audio
        spatial_audio.apply_reverb(decay_time, wet_gain)
    except Exception as e:
        raise RuntimeError(f"failed to apply reverb: {e}")

    return {'rt60': rt60, 'decay': decay_time, 'gain': wet_gain}
