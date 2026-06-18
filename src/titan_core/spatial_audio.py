"""
spatial_audio.py - OpenAL Soft HRTF backend for Titan 3D sound mode.

Provides virtual-surround (HRTF) playback of UI sounds and Titan TTS when the
user selects the "3d" sound mode. Wraps PyOpenAL's low-level ctypes bindings
(openal.al / openal.alc) directly so we can request HRTF on the context, which
the high-level wrapper does not expose.

Key facts:
  * HRTF only spatialises MONO sources. All audio fed here is downmixed to mono
    16-bit before buffering, otherwise OpenAL plays it flat (no spatialisation).
  * The listener sits at the origin facing -z (OpenAL default). Sources use
    AL_SOURCE_RELATIVE so positions are head-relative, with rolloff disabled so
    distance never attenuates gain.
  * Everything degrades gracefully: if OpenAL/PyOpenAL is unavailable or init
    fails, spatial_available() returns False and callers fall back to the
    regular pygame/stereo path.

Coordinate mapping (azimuth a in degrees, 0 = front, + = right;
elevation e in degrees, + = up):
    x =  cos(e) * sin(a)
    y =  sin(e)
    z = -cos(e) * cos(a)
"""

import math
import threading
import ctypes
import atexit

# ---------------------------------------------------------------------------
# OpenAL constants not exported by PyOpenAL
# ---------------------------------------------------------------------------
ALC_HRTF_SOFT = 0x1992
ALC_TRUE = 1
AL_ROLLOFF_FACTOR = 0x1021

# EFX (environmental reverb) constants
AL_EFFECT_TYPE = 0x8001
AL_EFFECT_REVERB = 0x0001
AL_REVERB_DENSITY = 0x0001
AL_REVERB_DIFFUSION = 0x0002
AL_REVERB_GAIN = 0x0003
AL_REVERB_GAINHF = 0x0004
AL_REVERB_DECAY_TIME = 0x0005
AL_REVERB_DECAY_HFRATIO = 0x0006
AL_REVERB_REFLECTIONS_GAIN = 0x0007
AL_REVERB_REFLECTIONS_DELAY = 0x0008
AL_REVERB_LATE_REVERB_GAIN = 0x0009
AL_REVERB_LATE_REVERB_DELAY = 0x000A
AL_EFFECTSLOT_EFFECT = 0x0001
AL_EFFECTSLOT_GAIN = 0x0002
AL_AUXILIARY_SEND_FILTER = 0x20006
AL_FILTER_NULL = 0

_al = None
_alc = None
_OPENAL_IMPORTED = False
try:
    import openal.al as _al
    import openal.alc as _alc
    _OPENAL_IMPORTED = True
except Exception as e:  # pragma: no cover - environment dependent
    print(f"[SpatialAudio] PyOpenAL not available: {e}")

# numpy for downmixing stereo -> mono (audioop was removed in Python 3.13+)
try:
    import numpy as _np
    _NUMPY_AVAILABLE = True
except Exception:
    _NUMPY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_device = None
_context = None
_init_tried = False
_init_ok = False

# Active (source_id, buffer_id) pairs awaiting playback completion / cleanup.
_active = []
# Decoded mono PCM cache for repeated UI sounds: path -> (pcm_bytes, sample_rate)
_pcm_cache = {}

# EFX reverb state
_efx = {}            # bound EFX function pointers
_efx_ok = False      # EFX extension loaded
_reverb_effect = None
_reverb_slot = None
_reverb_enabled = False
_reverb_loaded = False  # whether saved calibration was applied this session


def _init():
    """Lazily open the OpenAL device/context with HRTF enabled. Idempotent."""
    global _device, _context, _init_tried, _init_ok
    with _lock:
        if _init_tried:
            return _init_ok
        _init_tried = True
        if not _OPENAL_IMPORTED:
            return False
        try:
            _device = _alc.alcOpenDevice(None)
            if not _device:
                print("[SpatialAudio] alcOpenDevice failed")
                return False

            # Request HRTF via context attribute list: pairs + 0 terminator.
            attrs = (ctypes.c_long * 3)(ALC_HRTF_SOFT, ALC_TRUE, 0)
            _context = _alc.alcCreateContext(_device, attrs)
            if not _context:
                print("[SpatialAudio] alcCreateContext failed")
                _alc.alcCloseDevice(_device)
                _device = None
                return False

            _alc.alcMakeContextCurrent(_context)

            # Listener at origin, facing -z, up = +y (OpenAL default, set explicitly).
            _al.alListener3f(_al.AL_POSITION, 0.0, 0.0, 0.0)
            orient = (ctypes.c_float * 6)(0.0, 0.0, -1.0, 0.0, 1.0, 0.0)
            _al.alListenerfv(_al.AL_ORIENTATION, orient)

            _init_ok = True
            print("[SpatialAudio] OpenAL HRTF backend ready")
            return True
        except Exception as e:
            print(f"[SpatialAudio] Init error: {e}")
            return False


def _load_efx():
    """Bind the EFX functions we need via alGetProcAddress. Idempotent."""
    global _efx_ok
    if _efx_ok:
        return True
    if not _init_ok:
        return False
    try:
        if not _alc.alcIsExtensionPresent(_device, ctypes.c_char_p(b"ALC_EXT_EFX")):
            print("[SpatialAudio] EFX not present - reverb unavailable")
            return False

        def _bind(name, restype, argtypes):
            addr = _al.alGetProcAddress(name.encode("ascii"))
            if not addr:
                raise RuntimeError(f"alGetProcAddress({name}) failed")
            proto = ctypes.CFUNCTYPE(restype, *argtypes)
            return proto(addr)

        cu = ctypes.c_uint
        cul = ctypes.c_ulong
        cf = ctypes.c_float
        ci = ctypes.c_int
        pu = ctypes.POINTER(cu)
        _efx['alGenEffects'] = _bind('alGenEffects', None, [ci, pu])
        _efx['alDeleteEffects'] = _bind('alDeleteEffects', None, [ci, pu])
        _efx['alEffecti'] = _bind('alEffecti', None, [cu, ci, ci])
        _efx['alEffectf'] = _bind('alEffectf', None, [cu, ci, cf])
        _efx['alGenAuxiliaryEffectSlots'] = _bind('alGenAuxiliaryEffectSlots', None, [ci, pu])
        _efx['alDeleteAuxiliaryEffectSlots'] = _bind('alDeleteAuxiliaryEffectSlots', None, [ci, pu])
        _efx['alAuxiliaryEffectSloti'] = _bind('alAuxiliaryEffectSloti', None, [cu, ci, ci])
        _efx_ok = True
        print("[SpatialAudio] EFX reverb available")
        return True
    except Exception as e:
        print(f"[SpatialAudio] EFX load error: {e}")
        return False


def _ensure_reverb_objects():
    """Create the reverb effect + auxiliary effect slot once."""
    global _reverb_effect, _reverb_slot
    if not _load_efx():
        return False
    if _reverb_effect is not None and _reverb_slot is not None:
        return True
    try:
        eff = ctypes.c_uint(0)
        _efx['alGenEffects'](1, ctypes.byref(eff))
        _efx['alEffecti'](eff.value, AL_EFFECT_TYPE, AL_EFFECT_REVERB)
        slot = ctypes.c_uint(0)
        _efx['alGenAuxiliaryEffectSlots'](1, ctypes.byref(slot))
        _reverb_effect = eff.value
        _reverb_slot = slot.value
        return True
    except Exception as e:
        print(f"[SpatialAudio] reverb object creation error: {e}")
        return False


def reverb_supported():
    """True if EFX reverb can be used on this system."""
    return _init() and _load_efx()


def apply_reverb(decay_time, gain=0.32, hf_ratio=0.83, late_gain=1.26):
    """Configure and enable the environmental reverb (room echo).

    Args:
        decay_time (float): RT60-like decay in seconds (0.1..20).
        gain (float): Overall reverb wet level (0..1).
        hf_ratio (float): High-frequency decay ratio (0.1..2).
        late_gain (float): Late reverb gain multiplier (0..10).
    Returns True on success.
    """
    global _reverb_enabled
    if not _ensure_reverb_objects():
        return False
    with _lock:
        try:
            decay_time = max(0.1, min(20.0, float(decay_time)))
            gain = max(0.0, min(1.0, float(gain)))
            hf_ratio = max(0.1, min(2.0, float(hf_ratio)))
            late_gain = max(0.0, min(10.0, float(late_gain)))
            _efx['alEffectf'](_reverb_effect, AL_REVERB_DECAY_TIME, decay_time)
            _efx['alEffectf'](_reverb_effect, AL_REVERB_GAIN, gain)
            _efx['alEffectf'](_reverb_effect, AL_REVERB_DECAY_HFRATIO, hf_ratio)
            _efx['alEffectf'](_reverb_effect, AL_REVERB_LATE_REVERB_GAIN, late_gain)
            # Re-attach the effect so the slot picks up the new parameters.
            _efx['alAuxiliaryEffectSloti'](_reverb_slot, AL_EFFECTSLOT_EFFECT, _reverb_effect)
            _reverb_enabled = True
            return True
        except Exception as e:
            print(f"[SpatialAudio] apply_reverb error: {e}")
            return False


def clear_reverb():
    """Disable the reverb send for subsequently played sources."""
    global _reverb_enabled
    _reverb_enabled = False


def load_reverb_from_settings():
    """Apply persisted reverb calibration from [sound], if enabled."""
    try:
        from src.settings.settings import get_setting
        if get_setting('reverb_enabled', 'False', 'sound').lower() not in ('true', '1'):
            return False
        decay = float(get_setting('reverb_decay', '0.6', 'sound'))
        gain = float(get_setting('reverb_gain', '0.32', 'sound'))
        return apply_reverb(decay, gain)
    except Exception as e:
        print(f"[SpatialAudio] load_reverb_from_settings error: {e}")
        return False


def spatial_available():
    """True if the OpenAL HRTF backend is usable (initialises on first call)."""
    global _reverb_loaded
    if _init():
        # Apply any saved room calibration once, the first time the backend is up.
        if not _reverb_loaded:
            _reverb_loaded = True
            load_reverb_from_settings()
        return True
    return False


# ---------------------------------------------------------------------------
# Coordinate / parameter helpers (shared conversion conventions)
# ---------------------------------------------------------------------------
def pan_to_azimuth(pan):
    """UI pan (0.0=left .. 0.5=center .. 1.0=right) -> azimuth degrees (-90..90)."""
    try:
        pan = max(0.0, min(1.0, float(pan)))
    except (TypeError, ValueError):
        return 0.0
    return (pan - 0.5) * 180.0


def position_to_azimuth(position):
    """Speech position (-1.0=left .. 0.0=center .. 1.0=right) -> azimuth (-90..90)."""
    try:
        position = max(-1.0, min(1.0, float(position)))
    except (TypeError, ValueError):
        return 0.0
    return position * 90.0


def norm_to_elevation(value):
    """Normalised vertical (-1.0=down .. 0.0=center .. 1.0=up) -> elevation deg (-60..60)."""
    try:
        value = max(-1.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
    return value * 60.0


def _angles_to_xyz(azimuth_deg, elevation_deg):
    a = math.radians(azimuth_deg)
    e = math.radians(elevation_deg)
    x = math.cos(e) * math.sin(a)
    y = math.sin(e)
    z = -math.cos(e) * math.cos(a)
    return x, y, z


# ---------------------------------------------------------------------------
# Cleanup of finished sources
# ---------------------------------------------------------------------------
def _reap(force=False):
    """Delete finished (or, if force, all) sources and their buffers."""
    if not _active:
        return
    state = ctypes.c_long(0)
    remaining = []
    for src, buf in _active:
        try:
            if force:
                _al.alSourceStop(src)
                done = True
            else:
                _al.alGetSourcei(src, _al.AL_SOURCE_STATE, ctypes.byref(state))
                done = state.value != _al.AL_PLAYING
            if done:
                _al.alDeleteSources(1, ctypes.byref(ctypes.c_uint(src)))
                _al.alDeleteBuffers(1, ctypes.byref(ctypes.c_uint(buf)))
            else:
                remaining.append((src, buf))
        except Exception:
            remaining.append((src, buf))
    _active[:] = remaining


# ---------------------------------------------------------------------------
# Downmix helpers
# ---------------------------------------------------------------------------
def _downmix_to_mono16(pcm_bytes, channels, sampwidth):
    """Return (mono_pcm_bytes, sampwidth=2). Requires 16-bit input for stereo."""
    if channels == 1 and sampwidth == 2:
        return pcm_bytes
    if not _NUMPY_AVAILABLE:
        # Best effort: only handle the common mono-16 case without numpy.
        return pcm_bytes if channels == 1 else None
    try:
        if sampwidth == 2:
            arr = _np.frombuffer(pcm_bytes, dtype=_np.int16)
        elif sampwidth == 1:
            arr = (_np.frombuffer(pcm_bytes, dtype=_np.uint8).astype(_np.int16) - 128) * 256
        else:
            arr = _np.frombuffer(pcm_bytes, dtype=_np.int16)
        if channels > 1:
            arr = arr.reshape(-1, channels).mean(axis=1)
        return arr.astype(_np.int16).tobytes()
    except Exception as e:
        print(f"[SpatialAudio] Downmix error: {e}")
        return None


# ---------------------------------------------------------------------------
# Public playback API
# ---------------------------------------------------------------------------
def play_pcm(pcm_bytes, sample_rate, channels, sampwidth,
             azimuth_deg=0.0, elevation_deg=0.0, gain=1.0):
    """Play raw PCM at a 3D position via HRTF (non-blocking).

    Audio is downmixed to mono 16-bit so OpenAL spatialises it. Returns the
    source id on success, or None on failure.
    """
    if not _init():
        return None
    if not pcm_bytes:
        return None
    mono = _downmix_to_mono16(pcm_bytes, channels, sampwidth)
    if not mono:
        return None
    with _lock:
        try:
            _reap()
            buf = ctypes.c_uint(0)
            _al.alGenBuffers(1, ctypes.byref(buf))
            _al.alBufferData(buf, _al.AL_FORMAT_MONO16, mono, len(mono), int(sample_rate))

            src = ctypes.c_uint(0)
            _al.alGenSources(1, ctypes.byref(src))
            _al.alSourcei(src, _al.AL_BUFFER, buf.value)
            _al.alSourcei(src, _al.AL_SOURCE_RELATIVE, _al.AL_TRUE)
            _al.alSourcef(src, AL_ROLLOFF_FACTOR, 0.0)
            _al.alSourcef(src, _al.AL_GAIN, max(0.0, float(gain)))

            x, y, z = _angles_to_xyz(azimuth_deg, elevation_deg)
            _al.alSource3f(src, _al.AL_POSITION, x, y, z)

            # Route through the room reverb (echo) when calibration is active.
            if _reverb_enabled and _reverb_slot is not None:
                try:
                    _al.alSource3i(src, AL_AUXILIARY_SEND_FILTER, _reverb_slot, 0, AL_FILTER_NULL)
                except Exception:
                    pass

            _al.alSourcePlay(src)
            _active.append((src.value, buf.value))
            return src.value
        except Exception as e:
            print(f"[SpatialAudio] play_pcm error: {e}")
            return None


def _decode_to_mono_pcm(path):
    """Decode an audio file to (mono16_pcm_bytes, sample_rate), cached by path.

    Uses pygame for decoding (handles .ogg/.wav natively, no ffmpeg needed) and
    reuses the running mixer's output format. The samples are downmixed to mono
    so OpenAL can spatialise them.
    """
    cached = _pcm_cache.get(path)
    if cached is not None:
        return cached
    try:
        import pygame
        if not pygame.mixer.get_init():
            try:
                pygame.mixer.init(frequency=22050, size=-16, channels=2)
            except Exception:
                pass
        init = pygame.mixer.get_init()
        if not init:
            return None
        freq, fmt, channels = init[0], init[1], init[2]
        sampwidth = abs(int(fmt)) // 8
        raw = pygame.mixer.Sound(path).get_raw()
        mono = _downmix_to_mono16(raw, channels, sampwidth)
        if not mono:
            return None
        result = (mono, freq)
        _pcm_cache[path] = result
        return result
    except Exception as e:
        print(f"[SpatialAudio] decode error for {path}: {e}")
        return None


def play_file(path, azimuth_deg=0.0, elevation_deg=0.0, gain=1.0):
    """Decode a sound file and play it at a 3D position via HRTF (non-blocking)."""
    if not _init():
        return None
    decoded = _decode_to_mono_pcm(path)
    if not decoded:
        return None
    pcm, rate = decoded
    return play_pcm(pcm, rate, 1, 2, azimuth_deg, elevation_deg, gain)


def is_playing(src_id):
    """True while the given source is still actively rendering (AL_PLAYING).

    Lets callers poll real playback completion instead of estimating it from a
    wall-clock duration (HRTF has start-up latency that a timer estimate clips).
    """
    if not _init_ok or src_id is None:
        return False
    with _lock:
        try:
            state = ctypes.c_long(0)
            _al.alGetSourcei(src_id, _al.AL_SOURCE_STATE, ctypes.byref(state))
            return state.value == _al.AL_PLAYING
        except Exception:
            return False


def stop_source(src_id):
    """Stop and free a single source returned by play_pcm/play_file."""
    if not _init() or src_id is None:
        return
    with _lock:
        try:
            _al.alSourceStop(ctypes.c_uint(src_id))
        except Exception:
            pass
        _reap()


def stop_all():
    """Stop and free all active sources."""
    if not _init_ok:
        return
    with _lock:
        _reap(force=True)


def _shutdown():
    """Release the OpenAL context and device at interpreter exit."""
    global _device, _context, _init_ok
    if not _init_ok:
        return
    with _lock:
        try:
            _reap(force=True)
            if _efx_ok:
                try:
                    if _reverb_slot is not None:
                        _efx['alDeleteAuxiliaryEffectSlots'](1, ctypes.byref(ctypes.c_uint(_reverb_slot)))
                    if _reverb_effect is not None:
                        _efx['alDeleteEffects'](1, ctypes.byref(ctypes.c_uint(_reverb_effect)))
                except Exception:
                    pass
            _alc.alcMakeContextCurrent(None)
            if _context:
                _alc.alcDestroyContext(_context)
            if _device:
                _alc.alcCloseDevice(_device)
        except Exception:
            pass
        _context = None
        _device = None
        _init_ok = False


atexit.register(_shutdown)
