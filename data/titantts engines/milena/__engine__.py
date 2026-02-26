"""
Milena TTS Engine for TCE Launcher / Titan Stereo Speech
=========================================================
Windows-only Polish TTS engine using milena4w.exe (MBROLA backend).

Features:
- Local synthesis via milena4w.exe subprocess (no network latency)
- Disk cache (MD5-keyed WAV files) for instant replay on repeated messages
- Pitch offset via pydub frame-rate trick (same as ElevenLabs engine)
- Configurable rate and volume
- No voice selection (built-in Polish voice)
"""

import io
import os
import sys
import hashlib
import subprocess
import tempfile
import threading
import time

try:
    from src.tts.base_engine import TitanTTSEngine
except ImportError:
    import abc
    class TitanTTSEngine(abc.ABC):
        engine_id = ''
        engine_name = ''
        engine_category = 'platform'
        needs_lock_release = False
        @abc.abstractmethod
        def is_available(self): ...
        @abc.abstractmethod
        def generate(self, text, pitch_offset=0): ...
        @abc.abstractmethod
        def get_voices(self): ...
        @abc.abstractmethod
        def set_voice(self, voice_id): ...
        def set_rate(self, rate): pass
        def set_volume(self, volume): pass
        def stop(self): pass
        def clear_cache(self): pass
        @classmethod
        def get_config_fields(cls): return []
        def configure(self, key, value): pass
        def get_config(self, key, default=None): return default

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    print("[Milena] 'pydub' not installed - run: pip install pydub")


def _find_milena_exe():
    """Find milena4w.exe relative to this engine's directory (m4win/)."""
    engine_dir = os.path.dirname(os.path.abspath(__file__))
    exe_path = os.path.join(engine_dir, 'm4win', 'milena4w.exe')
    if os.path.exists(exe_path):
        return exe_path
    return None


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _get_cache_dir():
    """Return platform-appropriate TTS cache directory and ensure it exists."""
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    cache_dir = os.path.join(base, 'Titosoft', 'Titan', 'tts_cache', 'milena')
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _cache_key(text, rate, volume):
    """MD5 of (text, rate, volume) -> hex filename."""
    data = f"{text}\x00{rate}\x00{volume}".encode('utf-8')
    return hashlib.md5(data).hexdigest()


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class MilenaEngine(TitanTTSEngine):
    """
    Milena (Windows) local TTS engine using milena4w.exe with MBROLA backend.

    Public API:
        generate(text, pitch_offset=0) -> AudioSegment | None
        set_rate(rate)       - milena rate 0.5..1.0 (lower = faster)
        set_volume(volume)   - 0..100
        is_available()       -> bool
        clear_cache()
    """

    engine_id = 'milena'
    engine_name = 'Milena'
    engine_category = 'titantts'
    needs_lock_release = True

    def __init__(self):
        self._exe_path = _find_milena_exe()
        self._exe_dir = os.path.dirname(self._exe_path) if self._exe_path else None
        self._lock = threading.Lock()

        # Milena parameters
        self._rate = 0.75       # 0.5..1.0 (duration multiplier; lower = faster)
        self._volume = 100      # 0..100
        self._base_pitch = 0.9  # milena -p parameter (0.5..2.0)
        self._contrast = 80     # milena -c parameter (0..100)

        # Current subprocess (so stop() can kill it)
        self._process = None

        if self._exe_path:
            print(f"[Milena] Found milena4w.exe: {self._exe_path}")
        else:
            print("[Milena] milena4w.exe not found in m4win/")

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_rate(self, rate):
        """Set speech rate (0.5..1.0, lower = faster). Default 0.75."""
        self._rate = max(0.5, min(1.0, float(rate)))

    def get_rate(self):
        return self._rate

    def set_volume(self, volume):
        """Set volume (0..100). Default 100."""
        self._volume = max(0, min(100, int(volume)))

    def get_volume(self):
        return self._volume

    def is_available(self):
        """True when milena4w.exe exists, pydub is available, and platform is Windows."""
        return (
            sys.platform == 'win32'
            and PYDUB_AVAILABLE
            and self._exe_path is not None
            and os.path.exists(self._exe_path)
        )

    def get_voices(self):
        """Milena has a single built-in Polish voice."""
        return []

    def set_voice(self, voice_id):
        """No-op: Milena has a single built-in voice."""
        pass

    # ------------------------------------------------------------------
    # Audio generation
    # ------------------------------------------------------------------

    def generate(self, text, pitch_offset=0):
        """
        Synthesize text to AudioSegment.

        Flow:
          1. Check disk cache -> return instantly on hit
          2. Write text to temp .txt file
          3. Run milena4w.exe -> temp .mp3 file
          4. Load MP3 with pydub, cache as WAV
          5. Apply pitch offset (frame-rate trick)

        Args:
            text (str):         Text to speak.
            pitch_offset (int): Semitone shift -10..+10.

        Returns:
            pydub.AudioSegment or None
        """
        if not self.is_available():
            return None

        text = text.strip()
        if not text:
            return None

        key = _cache_key(text, self._rate, self._volume)

        # --- cache lookup ---
        audio = self._load_from_cache(key)
        if audio is not None:
            print(f"[Milena] Cache hit: {text[:60]}")
        else:
            audio = self._synthesize(text)
            if audio is None:
                return None

            # Apply volume adjustment via pydub gain
            if self._volume != 100:
                import math
                if self._volume == 0:
                    # Silence
                    audio = audio - 120  # effectively silence
                else:
                    # Convert 0-100 to dB gain (-40..0)
                    gain_db = 20 * math.log10(self._volume / 100.0)
                    audio = audio + gain_db

            self._save_to_cache(key, audio)

        # --- post-processing: pitch (not cached) ---
        if pitch_offset != 0:
            audio = self._apply_pitch(audio, pitch_offset)

        return audio

    # ------------------------------------------------------------------
    # Private - synthesis via subprocess
    # ------------------------------------------------------------------

    def _synthesize(self, text):
        """
        Run milena4w.exe to synthesize text to MP3, then load as AudioSegment.

        Uses temp files for input (.txt) and output (.mp3).
        """
        txt_path = None
        mp3_path = None

        try:
            # Create temp input file (UTF-8 text)
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.txt', delete=False,
                encoding='utf-8', dir=self._exe_dir
            ) as f:
                f.write(text)
                txt_path = f.name

            # Output MP3 path (same name, .mp3 extension)
            mp3_path = txt_path.rsplit('.', 1)[0] + '.mp3'

            # Build milena4w command
            cmd = [
                self._exe_path,
                '-o',                           # allow overwrite
                '-r', str(self._rate),           # speech rate
                '-p', str(self._base_pitch),     # base pitch
                '-c', str(self._contrast),       # audio contrast
                '-b', '48',                      # bitrate (good quality)
                txt_path,                        # input
                mp3_path,                        # output
            ]

            t0 = time.time()
            print(f"[Milena] Synthesizing: {text[:60]}")

            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=self._exe_dir,
            )
            self._process = proc

            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                print("[Milena] Synthesis timeout")
                return None
            finally:
                if self._process is proc:
                    self._process = None

            # milena4w.exe always returns code 1 even on success,
            # so we check the output file instead of the return code

            # Check output file
            if not os.path.exists(mp3_path) or os.path.getsize(mp3_path) < 100:
                print("[Milena] Output MP3 file not generated or too small")
                return None

            # Load MP3 with pydub
            audio = AudioSegment.from_mp3(mp3_path)
            # Normalize to 22050 Hz stereo (consistent with other engines)
            audio = audio.set_frame_rate(22050).set_channels(2)
            elapsed = time.time() - t0
            print(f"[Milena] Generated {len(audio)} ms audio in {elapsed:.2f}s")
            return audio

        except Exception as e:
            print(f"[Milena] Synthesis error: {e}")
            return None
        finally:
            # Clean up temp files
            for path in (txt_path, mp3_path):
                if path and os.path.exists(path):
                    try:
                        os.unlink(path)
                    except Exception:
                        pass

    def stop(self):
        """Kill running milena4w.exe subprocess if any."""
        proc = self._process
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        self._process = None

    # ------------------------------------------------------------------
    # Private - disk cache
    # ------------------------------------------------------------------

    def _cache_path(self, key):
        return os.path.join(_get_cache_dir(), key + '.wav')

    def _load_from_cache(self, key):
        """Load and return AudioSegment from disk cache, or None."""
        try:
            path = self._cache_path(key)
            if os.path.exists(path):
                return AudioSegment.from_wav(path)
        except Exception as e:
            print(f"[Milena] Cache load error: {e}")
        return None

    def _save_to_cache(self, key, audio):
        """Persist AudioSegment to disk cache as WAV."""
        try:
            path = self._cache_path(key)
            audio.export(path, format='wav')
            print(f"[Milena] Cached to: {os.path.basename(path)}")
        except Exception as e:
            print(f"[Milena] Cache save error: {e}")

    # ------------------------------------------------------------------
    # Private - pitch shift
    # ------------------------------------------------------------------

    def _apply_pitch(self, audio, pitch_offset):
        """
        Shift pitch via frame-rate manipulation (tape-speed trick).

        Each offset unit = 1 semitone (factor = 2^(1/12)).
        Clamped to -4..+4 semitones to avoid quality degradation.
        """
        try:
            pitch_offset = max(-4, min(4, pitch_offset))
            if pitch_offset == 0:
                return audio
            factor = 2.0 ** (pitch_offset / 12.0)
            new_frame_rate = int(audio.frame_rate * factor)
            if new_frame_rate <= 0:
                return audio
            shifted = audio._spawn(
                audio.raw_data,
                overrides={"frame_rate": new_frame_rate},
            )
            return shifted.set_frame_rate(audio.frame_rate)
        except Exception as e:
            print(f"[Milena] Pitch apply error: {e}")
            return audio

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def clear_cache(self):
        """Delete all cached WAV files from the Milena cache directory."""
        try:
            cache_dir = _get_cache_dir()
            removed = 0
            for fname in os.listdir(cache_dir):
                if fname.endswith('.wav'):
                    os.remove(os.path.join(cache_dir, fname))
                    removed += 1
            print(f"[Milena] Cleared {removed} cached files")
        except Exception as e:
            print(f"[Milena] Error clearing cache: {e}")


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_instance = None
_instance_lock = threading.Lock()


def get_milena_engine():
    """Return (or create) the global MilenaEngine singleton."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = MilenaEngine()
    return _instance


# Plugin entry point (called by EngineRegistry)
get_engine = get_milena_engine
