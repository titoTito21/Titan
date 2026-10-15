"""
BeSTspeech TTS Engine for TCE Launcher / Titan Stereo Speech
=============================================================
Windows-only multilingual TTS engine using BeSTspeech DLLs
(from LingvoSoft Talking Dictionary 2008).

Features:
- 12 languages with voice switching at runtime
- Full stereo positioning and pitch control (audio capture via IAT hooking)
- Speech interruption via bridge process termination
- Auto-compiling C# bridge (32-bit) from .NET Framework csc.exe
- Disk cache for instant replay of repeated phrases

Architecture:
  The BeSTspeech DLLs are 32-bit and use waveOut for audio playback.
  The C# bridge (bst_bridge.exe) hooks the waveOut IAT to capture PCM data
  silently, writes it to a temp WAV file, and returns the path.
  The engine loads the WAV as an AudioSegment for StereoSpeech integration.
"""

import ctypes as ct
import hashlib
import json
import os
import struct
import subprocess
import sys
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


# ---------------------------------------------------------------------------
# Language definitions
# ---------------------------------------------------------------------------

LANGUAGE_MAP = {
    'dll_eng.dll': ('en', 'English'),
    'dll_spa.dll': ('es', 'Spanish'),
    'dll_fre.dll': ('fr', 'French'),
    'dll_ger.dll': ('de', 'German'),
    'dll_ita.dll': ('it', 'Italian'),
    'dll_dut.dll': ('nl', 'Dutch'),
    'dll_gre.dll': ('el', 'Greek'),
    'dll_heb.dll': ('he', 'Hebrew'),
    'dll_jpn.dll': ('ja', 'Japanese'),
    'dll_pol.dll': ('pl', 'Polish'),
    'dll_por.dll': ('pt', 'Portuguese'),
    'dll_rus.dll': ('ru', 'Russian'),
}


def _get_engine_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _is_32bit_python():
    return struct.calcsize('P') * 8 == 32


# ---------------------------------------------------------------------------
# Auto-compile C# bridge
# ---------------------------------------------------------------------------

_CSC_PATH = os.path.join(
    os.environ.get('WINDIR', r'C:\Windows'),
    'Microsoft.NET', 'Framework', 'v4.0.30319', 'csc.exe'
)


def _ensure_bridge_exe(engine_dir):
    """Compile bst_bridge.exe from bst_bridge.cs if needed."""
    exe_path = os.path.join(engine_dir, 'bst_bridge.exe')
    cs_path = os.path.join(engine_dir, 'bst_bridge.cs')

    if os.path.exists(exe_path):
        if os.path.getmtime(cs_path) <= os.path.getmtime(exe_path):
            return exe_path

    if not os.path.exists(cs_path) or not os.path.exists(_CSC_PATH):
        return None

    print("[BeSTspeech] Compiling bst_bridge.exe...")
    try:
        result = subprocess.run(
            [_CSC_PATH, '-platform:x86', '-optimize', '-nologo',
             f'-out:{exe_path}', cs_path],
            capture_output=True, text=True, timeout=30, cwd=engine_dir,
        )
        if result.returncode == 0 and os.path.exists(exe_path):
            print("[BeSTspeech] Bridge compiled successfully")
            return exe_path
        else:
            print(f"[BeSTspeech] Compilation failed: {result.stderr}")
            return None
    except Exception as e:
        print(f"[BeSTspeech] Compilation error: {e}")
        return None


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _get_cache_dir():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    cache_dir = os.path.join(base, 'Titosoft', 'Titan', 'tts_cache', 'bestspeech')
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _cache_key(text, voice_id, rate):
    data = f"{text}\x00{voice_id}\x00{rate}".encode('utf-8')
    return hashlib.md5(data).hexdigest()


# ---------------------------------------------------------------------------
# Bridge backend (64-bit Python -> 32-bit C# exe)
# ---------------------------------------------------------------------------

class _BSTBridge:
    """Manages persistent bst_bridge.exe subprocess with audio capture."""

    def __init__(self, exe_path, engine_dir):
        self._exe_path = exe_path
        self._engine_dir = engine_dir
        self._proc = None
        self._lock = threading.Lock()

    def start(self):
        if self._proc and self._proc.poll() is None:
            return True
        try:
            self._proc = subprocess.Popen(
                [self._exe_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=self._engine_dir,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
            )
            # Register the bridge so Titan kills it on close/crash rather than
            # leaving an orphaned process behind.
            try:
                from src.titan_core.process_tracker import track_process
                track_process(self._proc)
            except Exception:
                pass
            resp = self._read_response(timeout=10)
            if resp and resp.get('ready'):
                print("[BeSTspeech] Bridge started")
                return True
            self.kill()
            return False
        except Exception as e:
            print(f"[BeSTspeech] Bridge start error: {e}")
            self._proc = None
            return False

    def kill(self):
        """Force-kill the bridge (used for speech interruption)."""
        if self._proc:
            try:
                self._proc.kill()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=2)
            except Exception:
                pass
        self._proc = None

    def quit(self):
        """Graceful shutdown."""
        if self._proc and self._proc.poll() is None:
            try:
                self._send_command({"cmd": "quit"})
            except Exception:
                pass
            try:
                self._proc.wait(timeout=3)
            except Exception:
                self.kill()
        self._proc = None

    def is_running(self):
        return self._proc is not None and self._proc.poll() is None

    def _send_command(self, cmd):
        if not self.is_running():
            return None
        try:
            data = json.dumps(cmd, ensure_ascii=False) + '\n'
            self._proc.stdin.write(data.encode('utf-8'))
            self._proc.stdin.flush()
            return self._read_response(timeout=30)
        except Exception as e:
            print(f"[BeSTspeech] Bridge command error: {e}")
            return None

    def _read_response(self, timeout=30):
        if not self.is_running():
            return None
        result = [None]
        def _read():
            try:
                line = self._proc.stdout.readline()
                if line:
                    result[0] = json.loads(line.decode('utf-8').strip())
            except Exception:
                pass
        t = threading.Thread(target=_read, daemon=True)
        t.start()
        t.join(timeout=timeout)
        return result[0]

    def init_dll(self, dll_path):
        with self._lock:
            resp = self._send_command({"cmd": "init", "dll": dll_path})
            return resp is not None and resp.get('ok', False)

    def say_capture(self, text):
        """Speak text and capture audio. Returns WAV file path or None."""
        with self._lock:
            resp = self._send_command({"cmd": "say", "text": text})
            if resp and resp.get('ok') and resp.get('wav'):
                return resp['wav']
            return None

    def switch_dll(self, dll_path):
        with self._lock:
            resp = self._send_command({"cmd": "switch", "dll": dll_path})
            return resp is not None and resp.get('ok', False)


# ---------------------------------------------------------------------------
# Direct backend (32-bit Python only)
# ---------------------------------------------------------------------------

class _BSTDirect:
    """Loads BeSTspeech DLL directly via ctypes (32-bit Python only).
    In direct mode, audio plays directly (no capture / no stereo)."""

    def __init__(self):
        self._lib = None
        self._lock = threading.Lock()

    def is_running(self):
        return self._lib is not None

    def init_dll(self, dll_path):
        with self._lock:
            self._deinit()
            try:
                self._lib = ct.CDLL(dll_path)
                self._lib.Init_TTS()
                return True
            except Exception as e:
                print(f"[BeSTspeech] Direct load error: {e}")
                self._lib = None
                return False

    def say_capture(self, text):
        """Direct mode: plays audio, returns None (no capture)."""
        with self._lock:
            if self._lib is None:
                return None
            try:
                self._lib.Say_TTS(ct.c_wchar_p(text))
                return "__direct__"
            except Exception as e:
                print(f"[BeSTspeech] Say error: {e}")
                return None

    def switch_dll(self, dll_path):
        return self.init_dll(dll_path)

    def kill(self):
        self._deinit()

    def quit(self):
        self._deinit()

    def _deinit(self):
        if self._lib is not None:
            try:
                self._lib.DeInit_TTS()
            except Exception:
                pass
            try:
                ct.windll.kernel32.FreeLibrary(ct.c_void_p(self._lib._handle))
            except Exception:
                pass
            self._lib = None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class BeSTspeechEngine(TitanTTSEngine):
    """
    BeSTspeech multilingual TTS engine.

    12 languages, full stereo/pitch support via audio capture,
    speech interruption via bridge process kill.
    """

    engine_id = 'bestspeech'
    engine_name = 'BeSTspeech'
    engine_category = 'titantts'
    needs_lock_release = True

    def __init__(self):
        self._engine_dir = _get_engine_dir()
        self._backend = None
        self._is_direct = _is_32bit_python()
        self._bridge_exe = None

        self._current_voice_id = 'en'
        self._current_dll = None
        self._rate = 0  # -10 (slowest) to +10 (fastest)

        self._available_voices = []
        self._dll_map = {}
        self._discover_voices()

        if not self._is_direct:
            self._bridge_exe = _ensure_bridge_exe(self._engine_dir)

        print(f"[BeSTspeech] Mode: {'direct (32-bit)' if self._is_direct else 'bridge (64-bit)'}")
        print(f"[BeSTspeech] Languages: {len(self._available_voices)}")

    def _discover_voices(self):
        self._available_voices = []
        self._dll_map = {}
        for dll_name, (lang_code, lang_name) in LANGUAGE_MAP.items():
            dll_path = os.path.join(self._engine_dir, dll_name)
            if os.path.exists(dll_path):
                self._available_voices.append({
                    'id': lang_code,
                    'display_name': f"BeSTspeech {lang_name}",
                })
                self._dll_map[lang_code] = dll_path

    def _ensure_backend(self):
        if self._backend and self._backend.is_running():
            return True

        if self._is_direct:
            self._backend = _BSTDirect()
        else:
            if not self._bridge_exe:
                return False
            self._backend = _BSTBridge(self._bridge_exe, self._engine_dir)
            if not self._backend.start():
                self._backend = None
                return False

        dll_path = self._dll_map.get(self._current_voice_id)
        if dll_path and self._backend.init_dll(dll_path):
            self._current_dll = dll_path
            return True

        print(f"[BeSTspeech] Failed to init DLL for {self._current_voice_id}")
        return False

    # ------------------------------------------------------------------
    # TitanTTSEngine interface
    # ------------------------------------------------------------------

    def is_available(self):
        if sys.platform != 'win32':
            return False
        if not self._available_voices:
            return False
        if not PYDUB_AVAILABLE:
            return False
        if self._is_direct:
            return True
        return self._bridge_exe is not None and os.path.exists(self._bridge_exe)

    def generate(self, text, pitch_offset=0):
        """
        Synthesize text to AudioSegment.

        Flow:
          1. Check disk cache -> instant on hit
          2. Send text to bridge (captures audio via IAT hooks)
          3. Load captured WAV as AudioSegment
          4. Cache as WAV, apply pitch offset
          5. Return AudioSegment for StereoSpeech (stereo positioning)

        Args:
            text:         Text to speak.
            pitch_offset: Semitone shift -10..+10.

        Returns:
            pydub.AudioSegment or None
        """
        if not self.is_available():
            return None

        text = text.strip()
        if not text:
            return None

        if not self._ensure_backend():
            return None

        key = _cache_key(text, self._current_voice_id, self._rate)

        # Cache lookup
        audio = self._load_from_cache(key)
        if audio is not None:
            print(f"[BeSTspeech] Cache hit: {text[:60]}")
        else:
            t0 = time.time()
            print(f"[BeSTspeech] Generating ({self._current_voice_id}): {text[:80]}")

            wav_path = self._backend.say_capture(text)

            if wav_path == "__direct__":
                # Direct mode (32-bit) - played directly, no AudioSegment
                return AudioSegment.silent(duration=50, frame_rate=22050)

            if not wav_path or not os.path.exists(wav_path):
                print("[BeSTspeech] Capture failed")
                return None

            try:
                audio = AudioSegment.from_wav(wav_path)
                # Normalize to full volume (BeSTspeech DLLs output very quiet audio)
                from pydub.effects import normalize
                audio = normalize(audio, headroom=0.5)
                # Apply rate change (time-stretch, no pitch change)
                if self._rate != 0:
                    audio = self._apply_rate(audio)
                audio = audio.set_frame_rate(22050).set_channels(2)
                elapsed = time.time() - t0
                print(f"[BeSTspeech] Generated {len(audio)} ms audio in {elapsed:.2f}s")
            except Exception as e:
                print(f"[BeSTspeech] WAV load error: {e}")
                return None
            finally:
                try:
                    os.unlink(wav_path)
                except Exception:
                    pass

            self._save_to_cache(key, audio)

        # Apply pitch offset
        if pitch_offset != 0:
            audio = self._apply_pitch(audio, pitch_offset)

        return audio

    def get_voices(self):
        return list(self._available_voices)

    def set_voice(self, voice_id):
        if voice_id == self._current_voice_id:
            return
        if voice_id not in self._dll_map:
            return

        self._current_voice_id = voice_id
        dll_path = self._dll_map[voice_id]

        if self._backend and self._backend.is_running():
            if self._backend.switch_dll(dll_path):
                self._current_dll = dll_path
                print(f"[BeSTspeech] Switched to: {voice_id}")

    def stop(self):
        """Interrupt speech by killing the bridge process."""
        if self._backend:
            self._backend.kill()
            self._backend = None

    def set_rate(self, rate):
        """Set speech rate. -10 (slowest) to +10 (fastest), 0 = default."""
        self._rate = max(-10, min(10, int(rate)))

    def set_volume(self, volume):
        pass  # Volume controlled via StereoSpeech

    # ------------------------------------------------------------------
    # Rate and Pitch
    # ------------------------------------------------------------------

    def _apply_rate(self, audio):
        """Change speech speed without changing pitch (time-stretch via ffmpeg atempo).

        Maps TCE rate (-10..+10) to playback speed:
          -10 -> 0.5x (half speed)
            0 -> 1.0x (normal)
          +10 -> 2.5x (2.5x speed)
        """
        try:
            if self._rate == 0:
                return audio
            if self._rate > 0:
                factor = 1.0 + (self._rate * 0.15)
            else:
                factor = 1.0 + (self._rate * 0.05)
            factor = max(0.5, min(3.0, factor))

            import tempfile
            in_path = None
            out_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                    in_path = f.name
                out_path = in_path + '.out.wav'

                audio.export(in_path, format='wav')

                # ffmpeg atempo supports 0.5..100.0
                ffmpeg = AudioSegment.converter
                result = subprocess.run(
                    [ffmpeg, '-y', '-i', in_path,
                     '-filter:a', f'atempo={factor}',
                     '-ar', str(audio.frame_rate),
                     out_path],
                    capture_output=True, timeout=30,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
                )
                if result.returncode == 0 and os.path.exists(out_path):
                    return AudioSegment.from_wav(out_path)
                else:
                    print(f"[BeSTspeech] atempo failed: {result.stderr[:200]}")
                    return audio
            finally:
                for p in (in_path, out_path):
                    if p:
                        try:
                            os.unlink(p)
                        except Exception:
                            pass
        except Exception as e:
            print(f"[BeSTspeech] Rate error: {e}")
            return audio

    def _apply_pitch(self, audio, pitch_offset):
        """Shift pitch via frame-rate trick (same as Milena engine)."""
        try:
            pitch_offset = max(-4, min(4, pitch_offset))
            if pitch_offset == 0:
                return audio
            factor = 2.0 ** (pitch_offset / 12.0)
            new_rate = int(audio.frame_rate * factor)
            if new_rate <= 0:
                return audio
            shifted = audio._spawn(audio.raw_data, overrides={"frame_rate": new_rate})
            return shifted.set_frame_rate(audio.frame_rate)
        except Exception as e:
            print(f"[BeSTspeech] Pitch error: {e}")
            return audio

    # ------------------------------------------------------------------
    # Disk cache
    # ------------------------------------------------------------------

    def _cache_path(self, key):
        return os.path.join(_get_cache_dir(), key + '.wav')

    def _load_from_cache(self, key):
        try:
            path = self._cache_path(key)
            if os.path.exists(path):
                return AudioSegment.from_wav(path)
        except Exception:
            pass
        return None

    def _save_to_cache(self, key, audio):
        try:
            path = self._cache_path(key)
            audio.export(path, format='wav')
        except Exception as e:
            print(f"[BeSTspeech] Cache save error: {e}")

    def clear_cache(self):
        try:
            cache_dir = _get_cache_dir()
            removed = 0
            for f in os.listdir(cache_dir):
                if f.endswith('.wav'):
                    os.remove(os.path.join(cache_dir, f))
                    removed += 1
            print(f"[BeSTspeech] Cleared {removed} cached files")
        except Exception as e:
            print(f"[BeSTspeech] Cache clear error: {e}")

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @classmethod
    def get_config_fields(cls):
        return [
            {
                'key': 'default_language',
                'label': 'Default language',
                'type': 'choice',
                'default': 'en',
                'options': [
                    ('en', 'English'), ('es', 'Spanish'), ('fr', 'French'),
                    ('de', 'German'), ('it', 'Italian'), ('nl', 'Dutch'),
                    ('el', 'Greek'), ('he', 'Hebrew'), ('ja', 'Japanese'),
                    ('pl', 'Polish'), ('pt', 'Portuguese'), ('ru', 'Russian'),
                ],
            },
        ]

    def configure(self, key, value):
        if key == 'default_language' and value in self._dll_map:
            self.set_voice(str(value))

    def get_config(self, key, default=None):
        if key == 'default_language':
            return self._current_voice_id
        return default

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def __del__(self):
        try:
            if self._backend:
                self._backend.quit()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Singleton & entry point
# ---------------------------------------------------------------------------

_instance = None
_instance_lock = threading.Lock()


def _get_engine():
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = BeSTspeechEngine()
    return _instance


get_engine = _get_engine
