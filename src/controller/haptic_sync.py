"""
Audio-synced haptics for TCE Launcher.

Drives the controller rumble motors from the amplitude envelope of whatever
sound is playing - similar to iPhone Core Haptics audio sync. Short UI blips
become quick taps; long sounds and music become sustained, modulated rumble.

A single background mixer thread combines every currently-playing "voice"
(taking the max of their instantaneous amplitudes), then pushes one motor level
to the active backend (XInput on Windows, pygame rumble elsewhere) at ~60 Hz.
When nothing is playing the thread idles on an event instead of busy-spinning.

The engine is intentionally defensive: if numpy/pygame are missing, or no
controller is present, every entry point becomes a silent no-op.
"""

import os
import threading
import time

# Reuse the XInput handle and platform flags already set up by the vibration
# module so we do not duplicate the ctypes plumbing.
from src.controller import controller_vibrations as _cv

try:
    import numpy as _np
    _NUMPY_OK = True
except Exception:
    _NUMPY_OK = False

# Envelope analysis parameters
_HOP_SECONDS = 0.012        # ~83 frames/sec - fine enough to feel "synced"
_TICK_SECONDS = 1.0 / 60.0  # motor update rate
_NOISE_GATE = 0.05          # below this normalized level -> no rumble
_GAIN = 2.6                 # maps per-hop peak (relative to int16 full-scale) to motor
_RELEASE_SECONDS = 0.09     # how fast rumble decays after a transient
_INT16_FULL = 32768.0

# Envelope cache keyed by (path, mtime); value = (envelope ndarray float32 [0..1], hop_seconds)
_env_cache = {}
_env_lock = threading.Lock()
_MAX_ENV_FRAMES = 30000  # ~6 minutes at the hop above; longer audio is truncated


def _compute_envelope(sound_path):
    """Return (envelope[0..1], hop_seconds) for a sound file, or None on failure.

    The envelope is the per-hop RMS of the (mono-summed) samples, scaled relative
    to int16 full-scale so that loud sounds/music rumble harder than quiet blips.
    """
    if not _NUMPY_OK:
        return None
    try:
        mtime = os.path.getmtime(sound_path)
    except OSError:
        return None

    key = (sound_path, mtime)
    with _env_lock:
        cached = _env_cache.get(key)
    if cached is not None:
        return cached

    try:
        import pygame
        if pygame.mixer.get_init() is None:
            return None
        snd = pygame.mixer.Sound(sound_path)
        samples = pygame.sndarray.array(snd)  # int16, shape (n,) or (n, channels)
    except Exception:
        return None

    try:
        freq = pygame.mixer.get_init()[0] or 44100
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        samples = samples.astype(_np.float32)

        hop = max(1, int(freq * _HOP_SECONDS))
        n_frames = max(1, len(samples) // hop)
        if n_frames > _MAX_ENV_FRAMES:
            n_frames = _MAX_ENV_FRAMES
        usable = samples[:n_frames * hop].reshape(n_frames, hop)

        # Per-hop peak (punchier than RMS), scaled to motor range.
        peak = _np.max(_np.abs(usable), axis=1) / _INT16_FULL
        amp = _np.clip(peak * _GAIN, 0.0, 1.0)

        # Envelope follower: instant attack, exponential release, so transients
        # feel punchy and the rumble tails off smoothly instead of chattering.
        decay = float(_np.exp(-_HOP_SECONDS / _RELEASE_SECONDS))
        env = _np.empty_like(amp)
        prev = 0.0
        for i in range(len(amp)):
            prev = amp[i] if amp[i] >= prev else prev * decay
            env[i] = prev
        env[env < _NOISE_GATE] = 0.0
        env = env.astype(_np.float32)
    except Exception:
        return None

    result = (env, _HOP_SECONDS)
    with _env_lock:
        if len(_env_cache) > 256:
            _env_cache.clear()
        _env_cache[key] = result
    return result


class _HapticSyncEngine:
    def __init__(self):
        self._voices = []          # list of dicts: {env, hop, t0, gain}
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread = None
        self._running = False
        self._last_level = -1.0

    def _ensure_thread(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="HapticSync")
        self._thread.start()

    def add_voice(self, sound_path, gain=1.0):
        """Register a playing sound to drive the motors for its duration."""
        data = _compute_envelope(sound_path)
        if data is None:
            return
        env, hop = data
        if env is None or len(env) == 0 or float(env.max()) <= 0.0:
            return  # silent / gated -> nothing to feel
        with self._lock:
            self._voices.append({'env': env, 'hop': hop, 't0': time.time(), 'gain': gain})
            self._ensure_thread()
        self._wake.set()

    def _set_motors(self, level):
        """Push a single combined level [0..1] to the active rumble backend."""
        if abs(level - self._last_level) < 0.02 and level != 0.0:
            return  # avoid spamming identical states
        self._last_level = level

        # XInput (Windows) - most reliable for Xbox pads
        if _cv.XINPUT_AVAILABLE and _cv.IS_WINDOWS and _cv.xinput is not None:
            try:
                import ctypes
                speed = int(max(0.0, min(1.0, level)) * 65535)
                for cid in range(4):
                    vib = _cv.XINPUT_VIBRATION()
                    vib.wLeftMotorSpeed = speed
                    vib.wRightMotorSpeed = speed
                    _cv.xinput.XInputSetState(cid, ctypes.byref(vib))
                return
            except Exception:
                pass

        # pygame rumble fallback (macOS/Linux)
        try:
            import pygame
            if pygame.joystick.get_init():
                for i in range(pygame.joystick.get_count()):
                    try:
                        js = pygame.joystick.Joystick(i)
                        if not js.get_init():
                            js.init()
                        js.rumble(level, level, int(_TICK_SECONDS * 2000))
                    except Exception:
                        continue
        except Exception:
            pass

    def _run(self):
        idle_since = None
        while self._running:
            now = time.time()
            level = 0.0
            with self._lock:
                alive = []
                for v in self._voices:
                    idx = int((now - v['t0']) / v['hop'])
                    if 0 <= idx < len(v['env']):
                        level = max(level, float(v['env'][idx]) * v['gain'])
                        alive.append(v)
                    elif idx < 0:
                        alive.append(v)
                self._voices = alive
                has_voices = bool(self._voices)

            # Apply master enable + strength from the shared vibration controller
            vc = _cv.vibration_controller
            if not getattr(vc, 'vibration_enabled', True):
                level = 0.0
            level *= max(0.0, min(1.0, getattr(vc, 'vibration_strength', 0.8)))

            self._set_motors(level)

            if not has_voices and level <= 0.0:
                # Motors already zeroed above; sleep until a new voice wakes us.
                if idle_since is None:
                    idle_since = now
                self._wake.clear()
                self._wake.wait(timeout=0.5)
                if not self._voices and (time.time() - idle_since) > 5.0:
                    # Long idle - stop the thread; add_voice restarts it.
                    self._running = False
                    break
            else:
                idle_since = None
                time.sleep(_TICK_SECONDS)

        self._set_motors(0.0)

    def stop(self):
        self._running = False
        with self._lock:
            self._voices = []
        self._wake.set()
        self._set_motors(0.0)


_engine = _HapticSyncEngine()


def play_for_path(sound_path, volume=1.0):
    """Fire audio-synced haptics for a sound file, if sync mode is active.

    Safe to call on every sound: respects the master vibration enable and only
    runs when haptic_mode == 'sync'. Silent / missing files are ignored.
    """
    try:
        vc = _cv.vibration_controller
        if not getattr(vc, 'vibration_enabled', True):
            return
        if getattr(vc, 'haptic_mode', 'sync') != 'sync':
            return
        if not sound_path:
            return
        _engine.add_voice(sound_path, gain=max(0.0, min(1.0, volume)))
    except Exception:
        pass


def stop():
    """Stop all audio-synced haptics and zero the motors."""
    try:
        _engine.stop()
    except Exception:
        pass
