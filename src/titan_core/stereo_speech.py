import math
import threading
import time
import tempfile
import os
import sys
import io
import subprocess
import platform
import queue as _queue
import importlib.util as _importlib_util
import accessible_output3.outputs.auto
from src.settings.settings import get_setting
from src.platform_utils import get_base_path as _get_base_path, IS_WINDOWS, IS_LINUX, IS_MACOS


# Windows-specific imports
SAPI_AVAILABLE = False
if IS_WINDOWS:
    try:
        import win32com.client
        SAPI_AVAILABLE = True
    except ImportError:
        print("Warning: win32com.client not available, SAPI TTS disabled")

try:
    from pydub import AudioSegment
    from pydub.playback import play
    try:
        from pydub.silence import detect_leading_silence as pydub_detect_leading_silence
        PYDUB_SILENCE_AVAILABLE = True
    except ImportError:
        PYDUB_SILENCE_AVAILABLE = False
    PYDUB_AVAILABLE = True
except ImportError:
    print("Warning: pydub not available, stereo effects will be limited")
    PYDUB_AVAILABLE = False
    PYDUB_SILENCE_AVAILABLE = False

# ---------------------------------------------------------------------------
# TitanTTS Engine Registry (loads ElevenLabs, Milena, and plugin engines)
# ---------------------------------------------------------------------------
_engine_registry = None

def _get_engine_registry():
    """Lazy-load the engine registry to avoid circular imports."""
    global _engine_registry
    if _engine_registry is None:
        try:
            from src.tts.engine_registry import get_engine_registry
            _engine_registry = get_engine_registry()
            print("[StereoSpeech] TitanTTS Engine Registry loaded")
        except Exception as e:
            print(f"[StereoSpeech] Engine Registry load error: {e}")
    return _engine_registry

# ---------------------------------------------------------------------------
# eSpeak DLL constants (from speak_lib.h)
import ctypes
import shutil
from ctypes import c_int, c_uint, c_void_p, c_char_p, c_ubyte, c_char, POINTER, Structure, CFUNCTYPE, c_short

AUDIO_OUTPUT_PLAYBACK = 0
AUDIO_OUTPUT_RETRIEVAL = 1
AUDIO_OUTPUT_SYNCHRONOUS = 2
espeakRATE = 1
espeakVOLUME = 2
espeakPITCH = 3
espeakCHARS_UTF8 = 1
espeakEVENT_SENTENCE = 1
espeakEVENT_WORD = 2
espeakEVENT_END = 3

# eSpeak callback type: int (*callback)(short *wav, int numsamples, espeak_EVENT *events)
t_espeak_callback = CFUNCTYPE(c_int, POINTER(c_short), c_int, c_void_p)


# eSpeak voice structure (from speak_lib.h)
class EspeakVoice(Structure):
    _fields_ = [
        ('name', c_char_p),        # voice name for display
        ('languages', c_void_p),   # priority byte + language code pairs
        ('identifier', c_char_p),  # file path within espeak-ng-data/voices
        ('gender', c_ubyte),       # 0=none, 1=male, 2=female
        ('age', c_ubyte),
        ('variant', c_ubyte),
        ('xx1', c_ubyte),
        ('spare1', c_int),
    ]


class ESpeakDLL:
    """
    Direct eSpeak NG DLL wrapper for responsive TTS like NVDA
    Embedded in titan_core for direct use without external components
    """

    def __init__(self):
        self.dll = None
        self.initialized = False
        self.data_path = None
        self._lock = threading.Lock()
        self.rate = 175
        self.pitch = 50
        self.volume = 100
        self.voice = None
        self.sample_rate = 22050  # Will be set by espeak_Initialize
        # For audio retrieval mode
        self.audio_buffer = []
        self.callback_fn = None
        self._play_channel = None  # pygame channel for direct playback in RETRIEVAL mode
        self._load_dll()

    def _load_dll(self):
        """Find and load the eSpeak NG shared library (cross-platform)"""
        try:
            proj_root = _get_base_path()
            bundled_dir = os.path.join(proj_root, 'data', 'titantts engines', 'espeak')

            # Platform-specific library names
            if IS_WINDOWS:
                lib_names = ['libespeak-ng.dll', 'espeak-ng.dll']
            elif IS_MACOS:
                lib_names = ['libespeak-ng.dylib', 'libespeak-ng.1.dylib']
            else:  # Linux
                lib_names = ['libespeak-ng.so', 'libespeak-ng.so.1']

            # Build search paths: bundled first, then system locations
            dll_paths = []
            for name in lib_names:
                dll_paths.append(os.path.join(bundled_dir, name))

            # System library paths for Linux and macOS
            if IS_LINUX:
                system_lib_dirs = [
                    '/usr/lib',
                    '/usr/lib/x86_64-linux-gnu',
                    '/usr/lib/aarch64-linux-gnu',
                    '/usr/local/lib',
                ]
                for lib_dir in system_lib_dirs:
                    for name in lib_names:
                        dll_paths.append(os.path.join(lib_dir, name))
            elif IS_MACOS:
                system_lib_dirs = [
                    '/opt/homebrew/lib',
                    '/usr/local/lib',
                ]
                for lib_dir in system_lib_dirs:
                    for name in lib_names:
                        dll_paths.append(os.path.join(lib_dir, name))

            # Also try bare names (lets the OS search its own paths)
            dll_paths.extend(lib_names)

            data_paths = [
                os.path.join(bundled_dir, 'espeak-ng-data'),
                bundled_dir,
            ]
            # System espeak data paths
            if IS_LINUX:
                data_paths.append('/usr/share/espeak-ng-data')
                data_paths.append('/usr/lib/espeak-ng-data')
            elif IS_MACOS:
                data_paths.append('/opt/homebrew/share/espeak-ng-data')
                data_paths.append('/usr/local/share/espeak-ng-data')

            for path in data_paths:
                if os.path.isdir(path):
                    self.data_path = path
                    break

            for dll_path in dll_paths:
                try:
                    if os.path.isabs(dll_path) and not os.path.exists(dll_path):
                        continue

                    dll_dir = os.path.dirname(dll_path) if os.path.isabs(dll_path) else bundled_dir
                    if dll_dir and os.path.isdir(dll_dir):
                        # os.add_dll_directory is Windows-only
                        if IS_WINDOWS:
                            try:
                                os.add_dll_directory(dll_dir)
                            except Exception:
                                pass
                        current_path = os.environ.get('PATH', '') if IS_WINDOWS else os.environ.get('LD_LIBRARY_PATH', '')
                        if dll_dir not in current_path:
                            if IS_WINDOWS:
                                os.environ['PATH'] = dll_dir + os.pathsep + current_path
                            else:
                                os.environ['LD_LIBRARY_PATH'] = dll_dir + os.pathsep + current_path

                    self.dll = ctypes.CDLL(dll_path)
                    print(f"[eSpeak DLL] Loaded: {dll_path}")
                    self._setup_functions()
                    self._initialize()
                    return
                except Exception as e:
                    continue

            print("[eSpeak DLL] Could not load eSpeak NG library")
        except Exception as e:
            print(f"[eSpeak DLL] Error: {e}")

    def _setup_functions(self):
        """Setup DLL function prototypes"""
        if not self.dll:
            return
        try:
            self.dll.espeak_Initialize.argtypes = [c_int, c_int, c_char_p, c_int]
            self.dll.espeak_Initialize.restype = c_int
            self.dll.espeak_SetVoiceByName.argtypes = [c_char_p]
            self.dll.espeak_SetVoiceByName.restype = c_int
            self.dll.espeak_SetParameter.argtypes = [c_int, c_int, c_int]
            self.dll.espeak_SetParameter.restype = c_int
            self.dll.espeak_Synth.argtypes = [c_void_p, ctypes.c_size_t, c_uint, c_int, c_uint, c_uint, POINTER(c_uint), c_void_p]
            self.dll.espeak_Synth.restype = c_int
            self.dll.espeak_Cancel.argtypes = []
            self.dll.espeak_Cancel.restype = c_int
            self.dll.espeak_IsPlaying.argtypes = []
            self.dll.espeak_IsPlaying.restype = c_int
            # No argtypes for SetSynthCallback - allows passing None (NULL) to clear callback.
            # ctypes type-checking would reject None for CFUNCTYPE even though NULL is valid in C.
            self.dll.espeak_SetSynthCallback.restype = None
            self.dll.espeak_Synchronize.argtypes = []
            self.dll.espeak_Synchronize.restype = c_int

            # Voice enumeration
            self.dll.espeak_ListVoices.argtypes = [POINTER(EspeakVoice)]
            self.dll.espeak_ListVoices.restype = POINTER(POINTER(EspeakVoice))
        except Exception as e:
            print(f"[eSpeak DLL] Error setting up functions: {e}")

    def _initialize(self):
        """Initialize eSpeak engine in RETRIEVAL mode.
        RETRIEVAL mode: DLL calls our callback with audio data, no DirectSound/WASAPI/COM.
        We play audio ourselves via pygame - this avoids all COM re-initialization issues
        and lets us apply stereo panning and pitch for all calls without switching modes."""
        if not self.dll:
            return False
        try:
            data_path_bytes = self.data_path.encode('utf-8') if self.data_path else None
            sample_rate = self.dll.espeak_Initialize(AUDIO_OUTPUT_RETRIEVAL, 0, data_path_bytes, 0)
            if sample_rate < 0:
                return False
            self.sample_rate = sample_rate
            self.initialized = True
            self._set_parameter(espeakRATE, self.rate)
            self._set_parameter(espeakPITCH, self.pitch)
            self._set_parameter(espeakVOLUME, self.volume)
            return True
        except Exception as e:
            print(f"[eSpeak DLL] Init error: {e}")
            return False

    def _set_parameter(self, param, value):
        if self.initialized:
            try:
                self.dll.espeak_SetParameter(param, value, 0)
            except Exception:
                pass

    def is_available(self):
        return self.initialized

    def speak(self, text, interrupt=True):
        """Synthesize text and play via pygame (RETRIEVAL mode - no DirectSound/COM)."""
        if not self.initialized:
            return False
        try:
            with self._lock:
                if interrupt:
                    self.cancel()

                self.audio_buffer = []

                def audio_callback(wav, numsamples, events):
                    if numsamples > 0 and wav:
                        try:
                            addr = ctypes.cast(wav, c_void_p).value
                            arr = (c_short * numsamples).from_address(addr)
                            self.audio_buffer.extend(arr)
                        except Exception:
                            pass
                    return 0

                self.callback_fn = t_espeak_callback(audio_callback)
                self.dll.espeak_SetSynthCallback(self.callback_fn)

                text_bytes = text.encode('utf-8')
                text_buffer = ctypes.create_string_buffer(text_bytes)
                result = self.dll.espeak_Synth(
                    text_buffer, len(text_bytes) + 1, 0, 0, 0, espeakCHARS_UTF8, None, None
                )
                self.dll.espeak_Synchronize()
                self.dll.espeak_SetSynthCallback(None)
                self.callback_fn = None

                if result != 0 or not self.audio_buffer:
                    return False

                # Play collected audio via pygame (non-blocking)
                try:
                    import pygame
                    import struct
                    import wave as _wave

                    if not pygame.mixer.get_init():
                        pygame.mixer.pre_init(frequency=self.sample_rate, size=-16, channels=1, buffer=512)
                        pygame.mixer.init()

                    audio_bytes = struct.pack(f'{len(self.audio_buffer)}h', *self.audio_buffer)
                    wav_buf = io.BytesIO()
                    with _wave.open(wav_buf, 'wb') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(self.sample_rate)
                        wf.writeframes(audio_bytes)
                    wav_buf.seek(0)

                    sound = pygame.mixer.Sound(wav_buf)
                    # Use dedicated TTS channel so UI sounds never collide
                    try:
                        from src.titan_core.sound import get_tts_channel
                        channel = get_tts_channel()
                    except Exception:
                        channel = pygame.mixer.find_channel(True)
                    if channel:
                        channel.play(sound)
                        self._play_channel = channel
                except Exception as e:
                    print(f"[eSpeak DLL] pygame playback error: {e}")

                return True
        except Exception as e:
            print(f"[eSpeak DLL] Speak error: {e}")
            return False

    def cancel(self):
        """Stop synthesis (thread-safe) and stop any pygame channel playing DLL audio."""
        if self.initialized:
            try:
                self.dll.espeak_Cancel()
            except Exception:
                pass
        if self._play_channel:
            try:
                if self._play_channel.get_busy():
                    self._play_channel.stop()
            except Exception:
                pass
            self._play_channel = None

    def is_playing(self):
        """In RETRIEVAL mode, check our pygame channel (DLL has no internal playback)."""
        if self._play_channel:
            try:
                return self._play_channel.get_busy()
            except Exception:
                pass
        return False

    def set_rate(self, rate):
        self.rate = int(175 + (rate * 27.5))
        self.rate = max(80, min(450, self.rate))
        self._set_parameter(espeakRATE, self.rate)

    def set_pitch(self, pitch):
        self.pitch = int(50 + (pitch * 5))
        self.pitch = max(0, min(99, self.pitch))
        self._set_parameter(espeakPITCH, self.pitch)

    def set_volume(self, volume):
        self.volume = int((volume / 100.0) * 200)
        self.volume = max(0, min(200, self.volume))
        self._set_parameter(espeakVOLUME, self.volume)

    def set_voice(self, voice_name):
        if not self.initialized:
            return False
        try:
            voice_bytes = voice_name.encode('utf-8')
            result = self.dll.espeak_SetVoiceByName(voice_bytes)
            if result == 0:
                self.voice = voice_name
                return True
            return False
        except Exception:
            return False

    def _parse_voice_language(self, lang_ptr):
        """Parse the primary language code from eSpeak voice languages field."""
        if not lang_ptr:
            return ''
        try:
            # First byte is priority (1-10), then null-terminated language string
            priority = c_ubyte.from_address(lang_ptr).value
            if priority == 0:
                return ''
            lang_bytes = ctypes.string_at(lang_ptr + 1)
            return lang_bytes.decode('utf-8', errors='ignore')
        except Exception:
            return ''

    def list_voices(self):
        """
        List available eSpeak voices using DLL API (espeak_ListVoices).

        Returns:
            list: List of dicts with 'id', 'name', 'display_name', 'gender', 'identifier'
        """
        if not self.initialized:
            return []
        try:
            voices_ptr = self.dll.espeak_ListVoices(None)
            if not voices_ptr:
                return []

            voices = []
            i = 0
            while True:
                try:
                    vp = voices_ptr[i]
                    if not vp:
                        break
                    v = vp.contents
                except (ValueError, OSError):
                    break

                name = v.name.decode('utf-8', errors='ignore') if v.name else ''
                identifier = v.identifier.decode('utf-8', errors='ignore') if v.identifier else ''
                lang = self._parse_voice_language(v.languages)
                gender_code = v.gender
                gender = {1: 'Male', 2: 'Female'}.get(gender_code, '')

                # Skip voice variants (from !v/ directory) - they are added separately
                if identifier.startswith('!v/') or identifier.startswith('!v\\'):
                    i += 1
                    continue

                # Use language code as voice ID (what espeak_SetVoiceByName expects)
                voice_id = lang if lang else identifier.split('/')[-1] if '/' in identifier else name.lower()

                display_name = name.replace('_', ' ').replace('-', ' ')
                if gender:
                    display_name = f"{display_name} ({gender})"

                voices.append({
                    'id': voice_id,
                    'name': name,
                    'display_name': display_name,
                    'gender': gender,
                    'gender_code': gender_code,
                    'identifier': identifier,
                    'language': lang,
                })
                i += 1

            print(f"[eSpeak DLL] Listed {len(voices)} voices via DLL API")
            return voices
        except Exception as e:
            print(f"[eSpeak DLL] Error listing voices: {e}")
            return []

    def synthesize_to_memory(self, text, pitch_offset=0):
        """
        Synthesize text to AudioSegment using callback (RETRIEVAL mode - no re-initialization,
        no DirectSound/COM). Returns pydub AudioSegment for stereo panning by the caller.

        Args:
            text (str): Text to synthesize
            pitch_offset (int): Pitch offset -10 to +10

        Returns:
            AudioSegment or None
        """
        if not self.initialized or not PYDUB_AVAILABLE:
            return None

        try:
            with self._lock:
                self.audio_buffer = []

                # Apply pitch with offset
                adjusted_pitch = max(0, min(99, self.pitch + pitch_offset * 5))
                self._set_parameter(espeakPITCH, adjusted_pitch)

                def audio_callback(wav, numsamples, events):
                    if numsamples > 0 and wav:
                        try:
                            addr = ctypes.cast(wav, c_void_p).value
                            arr = (c_short * numsamples).from_address(addr)
                            self.audio_buffer.extend(arr)
                        except Exception:
                            pass
                    return 0

                self.callback_fn = t_espeak_callback(audio_callback)
                self.dll.espeak_SetSynthCallback(self.callback_fn)

                text_bytes = text.encode('utf-8')
                text_buffer = ctypes.create_string_buffer(text_bytes)
                result = self.dll.espeak_Synth(
                    text_buffer, len(text_bytes) + 1, 0, 0, 0, espeakCHARS_UTF8, None, None
                )
                self.dll.espeak_Synchronize()
                self.dll.espeak_SetSynthCallback(None)
                self.callback_fn = None

                # Restore original pitch
                self._set_parameter(espeakPITCH, self.pitch)

                if result != 0 or not self.audio_buffer:
                    return None

                import struct
                import wave as _wave
                audio_bytes = struct.pack(f'{len(self.audio_buffer)}h', *self.audio_buffer)
                wav_buffer = io.BytesIO()
                with _wave.open(wav_buffer, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(self.sample_rate)
                    wf.writeframes(audio_bytes)
                wav_buffer.seek(0)
                audio = AudioSegment.from_wav(wav_buffer)
                print(f"[eSpeak DLL] synthesize_to_memory: {len(audio)}ms audio")
                return audio

        except Exception as e:
            print(f"[eSpeak DLL] Error in synthesize_to_memory: {e}")
            try:
                if self.dll and self.callback_fn:
                    self.dll.espeak_SetSynthCallback(None)
                self.callback_fn = None
                self._set_parameter(espeakPITCH, self.pitch)
            except Exception:
                pass
            return None

# Global eSpeak DLL instance
_espeak_dll_instance = None


def get_espeak_dll():
    """Get global eSpeak DLL instance"""
    global _espeak_dll_instance
    if _espeak_dll_instance is None:
        _espeak_dll_instance = ESpeakDLL()
    return _espeak_dll_instance


def is_espeak_dll_available():
    """Check if eSpeak DLL is available"""
    try:
        dll = get_espeak_dll()
        return dll.is_available()
    except Exception:
        return False


# Check for eSpeak DLL availability
ESPEAK_DLL_AVAILABLE = False
project_root = _get_base_path()

try:
    ESPEAK_DLL_AVAILABLE = is_espeak_dll_available()
    if ESPEAK_DLL_AVAILABLE:
        print("[StereoSpeech] eSpeak DLL available (fast mode like NVDA)")
except Exception as e:
    print(f"[StereoSpeech] eSpeak DLL not available: {e}")

# Check for eSpeak executable (fallback if DLL not available)
ESPEAK_AVAILABLE = False
ESPEAK_PATH = None
ESPEAK_DATA_PATH = None

# First, try to find bundled eSpeak in data/titantts engines/espeak/
bundled_espeak_dir = os.path.join(project_root, 'data', 'titantts engines', 'espeak')
_bundled_exe_name = 'espeak-ng.exe' if IS_WINDOWS else 'espeak-ng'
bundled_espeak_exe = os.path.join(bundled_espeak_dir, _bundled_exe_name)
bundled_espeak_data = os.path.join(bundled_espeak_dir, 'espeak-ng-data')

if os.path.exists(bundled_espeak_exe):
    try:
        # Test bundled eSpeak
        result = subprocess.run([bundled_espeak_exe, '--version'],
                              capture_output=True,
                              timeout=2)
        if result.returncode == 0:
            ESPEAK_AVAILABLE = True
            ESPEAK_PATH = bundled_espeak_exe
            if os.path.exists(bundled_espeak_data):
                ESPEAK_DATA_PATH = bundled_espeak_data
            print(f"[StereoSpeech] Found bundled eSpeak exe: {bundled_espeak_exe}")
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
        print(f"[StereoSpeech] Bundled eSpeak test failed: {e}")

# If bundled eSpeak not found, try system eSpeak
if not ESPEAK_AVAILABLE:
    for espeak_cmd in ['espeak-ng', 'espeak']:
        try:
            result = subprocess.run([espeak_cmd, '--version'],
                                  capture_output=True,
                                  timeout=2)
            if result.returncode == 0:
                ESPEAK_AVAILABLE = True
                ESPEAK_PATH = espeak_cmd
                print(f"[StereoSpeech] Found system eSpeak: {espeak_cmd}")
                break
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            continue

# Platform-specific native TTS detection
# macOS: 'say' command (NSSpeechSynthesizer)
SAY_AVAILABLE = False
if IS_MACOS:
    SAY_AVAILABLE = shutil.which('say') is not None
    if SAY_AVAILABLE:
        print("[StereoSpeech] macOS 'say' TTS available")

# Linux: speech-dispatcher (spd-say)
SPD_AVAILABLE = False
SPD_PATH = None
if IS_LINUX:
    _spd_path = shutil.which('spd-say')
    if _spd_path:
        SPD_AVAILABLE = True
        SPD_PATH = _spd_path
        print(f"[StereoSpeech] Linux speech-dispatcher available: {_spd_path}")


def detect_leading_silence(sound, silence_threshold=-50.0, chunk_size=50):
    """
    Detect leading silence in an audio segment (from start).

    Args:
        sound: pydub.AudioSegment
        silence_threshold: Threshold in dB (default -50.0)
        chunk_size: Size of chunks to analyze in ms (default 50)

    Returns:
        int: Milliseconds of leading silence
    """
    if not sound or len(sound) == 0:
        return 0

    trim_ms = 0
    duration = len(sound)
    assert chunk_size > 0  # Avoid infinite loop

    while trim_ms < duration:
        chunk = sound[trim_ms:trim_ms+chunk_size]
        # Empty chunk or too short - reached the end
        if len(chunk) == 0:
            break
        try:
            # Check if chunk has sound above threshold
            if chunk.dBFS > silence_threshold:
                break
        except:
            # If dBFS calculation fails (e.g., empty/invalid chunk), stop here
            break
        trim_ms += chunk_size

    return min(trim_ms, duration)


def detect_trailing_silence(sound, silence_threshold=-50.0, chunk_size=50):
    """
    Detect trailing silence in an audio segment (from end) - FAST, no reverse!

    Args:
        sound: pydub.AudioSegment
        silence_threshold: Threshold in dB (default -50.0)
        chunk_size: Size of chunks to analyze in ms (default 50)

    Returns:
        int: Milliseconds of trailing silence
    """
    if not sound or len(sound) == 0:
        return 0

    duration = len(sound)
    trim_ms = 0
    assert chunk_size > 0  # Avoid infinite loop

    # Start from the end and work backwards
    pos = duration
    while pos > 0:
        start = max(0, pos - chunk_size)
        chunk = sound[start:pos]

        # Empty chunk - reached the beginning
        if len(chunk) == 0:
            break
        try:
            # Check if chunk has sound above threshold
            if chunk.dBFS > silence_threshold:
                break
        except:
            # If dBFS calculation fails, stop here
            break

        trim_ms += len(chunk)
        pos = start

    return min(trim_ms, duration)


def trim_silence(sound, silence_threshold=-50.0, chunk_size=50):
    """
    Trim leading and trailing silence from audio - FAST version without reverse().

    Args:
        sound: pydub.AudioSegment
        silence_threshold: Threshold in dB (default -50.0)
        chunk_size: Size of chunks to analyze in ms (default 50)

    Returns:
        pydub.AudioSegment: Trimmed audio, or original if trimming would result in empty audio
    """
    if not sound or len(sound) == 0:
        return sound

    duration = len(sound)

    # Skip trimming for very short audio (< 200ms) - no benefit
    if duration < 200:
        return sound

    try:
        # Use fast custom functions (no reverse!)
        start_trim = detect_leading_silence(sound, silence_threshold, chunk_size)
        end_trim = detect_trailing_silence(sound, silence_threshold, chunk_size)

        # Ensure we don't trim everything
        if start_trim + end_trim >= duration:
            # Audio is all silence or trimming would result in empty audio
            # Return original audio with minimal trim (just first 10ms)
            return sound[min(10, duration):]

        trimmed = sound[start_trim:duration-end_trim]

        # Ensure result is not empty
        if len(trimmed) == 0:
            return sound

        return trimmed

    except Exception as e:
        print(f"Warning: Error during silence trimming: {e}")
        return sound


class _SAPIWorker:
    """Dedicated thread for SAPI5 COM operations.

    All SAPI5 calls run on a single thread to avoid cross-thread COM apartment
    issues.  The worker owns its own SpVoice COM object created with proper
    CoInitializeEx, and processes commands from a queue.

    If direct COM fails (e.g. bitness mismatch between Python and voice
    engines), automatically falls back to a subprocess bridge using
    the opposite-bitness cscript.exe with a VBScript helper.
    """

    # Persistent VBScript helper: reads tab-delimited commands from stdin.
    # Commands: SPEAK, STOP, VOICE, RATE, VOLUME, GENFILE, QUIT
    # GENFILE responds with "DONE" on stdout when WAV is written.
    _VBS_PERSISTENT = r'''On Error Resume Next
Set voice = CreateObject("SAPI.SpVoice")
If Err.Number <> 0 Then
    WScript.StdOut.WriteLine "INIT_FAIL"
    WScript.Quit 1
End If
Err.Clear
WScript.StdOut.WriteLine "READY"
Do While Not WScript.StdIn.AtEndOfStream
    line = WScript.StdIn.ReadLine
    If Len(line) = 0 Then
        ' skip empty lines
    Else
        tabPos = InStr(line, vbTab)
        If tabPos > 0 Then
            cmd = Left(line, tabPos - 1)
            arg = Mid(line, tabPos + 1)
        Else
            cmd = line
            arg = ""
        End If
        Select Case cmd
            Case "SPEAK"
                voice.Speak arg, 3
            Case "STOP"
                voice.Speak "", 3
            Case "VOICE"
                Err.Clear
                Set token = CreateObject("SAPI.SpObjectToken")
                token.SetId arg
                Set voice.Voice = token
                If Err.Number <> 0 Then
                    WScript.StdOut.WriteLine "VOICE_ERR"
                    Err.Clear
                Else
                    WScript.StdOut.WriteLine "VOICE_OK"
                End If
            Case "RATE"
                voice.Rate = CInt(arg)
            Case "VOLUME"
                voice.Volume = CInt(arg)
            Case "GENFILE"
                ' arg format: text<TAB>filepath<TAB>pitch_offset
                parts = Split(arg, vbTab)
                gText = parts(0)
                gPath = parts(1)
                gPitch = 0
                If UBound(parts) >= 2 Then
                    If parts(2) <> "" And parts(2) <> "0" Then gPitch = CInt(parts(2))
                End If
                If gPitch <> 0 Then
                    gText = "<pitch absmiddle=""" & gPitch & """>" & gText & "</pitch>"
                End If
                Err.Clear
                Set stream = CreateObject("SAPI.SpFileStream")
                stream.Format.Type = 22
                stream.Open gPath, 3
                Set voice.AudioOutputStream = stream
                voice.Speak gText, 0
                stream.Close
                Set voice.AudioOutputStream = Nothing
                If Err.Number <> 0 Then
                    WScript.StdOut.WriteLine "GENFILE_ERR"
                    Err.Clear
                Else
                    WScript.StdOut.WriteLine "GENFILE_DONE"
                End If
            Case "QUIT"
                Exit Do
        End Select
    End If
Loop
'''

    # One-shot VBScript for bridge testing (used by _find_subprocess_bridge)
    _VBS_TEST = (
        'On Error Resume Next\n'
        'Set v = CreateObject("SAPI.SpVoice")\n'
        'If Err.Number = 0 Then\n'
        '  Set ms = CreateObject("SAPI.SpMemoryStream")\n'
        '  If Err.Number = 0 Then\n'
        '    Set v.AudioOutputStream = ms\n'
        '    v.Speak "test", 0\n'
        '    If Err.Number = 0 Then\n'
        '      WScript.Echo "OK"\n'
        '    Else\n'
        '      WScript.Echo "SPEAK_FAIL"\n'
        '    End If\n'
        '  Else\n'
        '    WScript.Echo "STREAM_FAIL"\n'
        '  End If\n'
        'Else\n'
        '  WScript.Echo "CREATE_FAIL"\n'
        'End If\n'
    )

    def __init__(self):
        self._cmd_queue = _queue.Queue()
        self._sapi = None
        self._ready = threading.Event()
        self._cancel = threading.Event()
        self._voice_id = None
        self._rate = 0
        self._volume = 100
        self._error_count = 0
        self._max_errors = 3
        # Subprocess bridge state
        self._use_subprocess = False
        self._subprocess_cscript = None
        self._subprocess_process = None
        self._vbs_path = None
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="SAPIWorker")
        self._thread.start()
        self._ready.wait(5.0)

    @property
    def available(self):
        return self._sapi is not None or self._use_subprocess

    # ---- voice validation ----

    def _test_voice(self, voice=None):
        """Test if a SAPI voice works by speaking to a memory stream.

        Args:
            voice: SAPI voice token to test, or None to test current voice.

        Returns:
            True if the voice can speak without errors.
        """
        original_output = None
        try:
            if voice is not None:
                self._sapi.Voice = voice
            mem_stream = win32com.client.Dispatch("SAPI.SpMemoryStream")
            original_output = self._sapi.AudioOutputStream
            self._sapi.AudioOutputStream = mem_stream
            self._sapi.Speak("test", 0)  # Synchronous speak to memory
            return True
        except Exception:
            return False
        finally:
            if original_output is not None:
                try:
                    self._sapi.AudioOutputStream = original_output
                except Exception:
                    pass

    def _find_working_voice(self):
        """Try the default voice first, then iterate all voices to find one that works.

        Returns:
            True if a working voice was found, False otherwise.
        """
        # Test current default voice first
        if self._test_voice():
            return True

        # Default voice failed - try all available voices
        try:
            voices = self._sapi.GetVoices()
            count = voices.Count
            print(f"[SAPIWorker] Default voice failed, trying {count} available voices...")
            for i in range(count):
                voice = voices.Item(i)
                try:
                    name = voice.GetDescription()
                except Exception:
                    name = f"voice {i}"
                if self._test_voice(voice):
                    print(f"[SAPIWorker] Found working voice: {name}")
                    self._voice_id = voice.Id
                    return True
                else:
                    print(f"[SAPIWorker] Voice not compatible: {name}")
        except Exception as e:
            print(f"[SAPIWorker] Error enumerating voices: {e}")

        return False

    # ---- subprocess bridge setup ----

    def _find_subprocess_bridge(self):
        """Find a working cscript.exe for cross-bitness SAPI subprocess bridge.

        Tries opposite-bitness cscript first (to reach voices invisible to
        the current Python process), then same-bitness as last resort.

        Returns:
            Path to working cscript.exe, or None.
        """
        import struct
        windir = os.environ.get('WINDIR', r'C:\Windows')
        python_bits = struct.calcsize('P') * 8

        if python_bits == 64:
            candidates = [
                os.path.join(windir, 'SysWOW64', 'cscript.exe'),   # 32-bit
                os.path.join(windir, 'System32', 'cscript.exe'),    # 64-bit
            ]
        else:
            candidates = [
                os.path.join(windir, 'Sysnative', 'cscript.exe'),  # 64-bit from WOW64
                os.path.join(windir, 'System32', 'cscript.exe'),   # native
            ]

        vbs_test = os.path.join(tempfile.gettempdir(), 'tce_sapi_test.vbs')
        try:
            with open(vbs_test, 'w', encoding='ascii', errors='replace') as f:
                f.write(self._VBS_TEST)
        except Exception as e:
            print(f"[SAPIWorker] Failed to create test VBS: {e}")
            return None

        for cscript in candidates:
            if not os.path.exists(cscript):
                continue
            try:
                result = subprocess.run(
                    [cscript, '//nologo', '//T:10', vbs_test],
                    capture_output=True, timeout=15,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
                stdout = result.stdout.decode('utf-8', errors='replace')
                if 'OK' in stdout:
                    print(f"[SAPIWorker] Subprocess bridge works: {cscript}")
                    try:
                        os.remove(vbs_test)
                    except Exception:
                        pass
                    return cscript
                else:
                    print(f"[SAPIWorker] Subprocess bridge test failed ({cscript}): {stdout.strip()}")
            except Exception as e:
                print(f"[SAPIWorker] Subprocess bridge error ({cscript}): {e}")

        try:
            os.remove(vbs_test)
        except Exception:
            pass
        return None

    def _start_persistent_bridge(self):
        """Start the persistent cscript subprocess and wait for READY signal.

        Returns:
            True if the subprocess started and is ready, False otherwise.
        """
        import locale
        encoding = locale.getpreferredencoding() or 'cp1250'
        vbs_path = os.path.join(tempfile.gettempdir(), 'tce_sapi_bridge.vbs')
        with open(vbs_path, 'w', encoding=encoding, errors='replace') as f:
            f.write(self._VBS_PERSISTENT)
        self._vbs_path = vbs_path

        try:
            self._subprocess_process = subprocess.Popen(
                [self._subprocess_cscript, '//nologo', vbs_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            # Wait for READY signal
            ready_line = self._subprocess_process.stdout.readline()
            ready_str = ready_line.decode('utf-8', errors='replace').strip()
            if ready_str == 'READY':
                print("[SAPIWorker] Persistent subprocess bridge ready")
                return True
            else:
                print(f"[SAPIWorker] Bridge init failed: {ready_str}")
                self._subprocess_stop()
                return False
        except Exception as e:
            print(f"[SAPIWorker] Failed to start persistent bridge: {e}")
            return False

    def _bridge_send(self, cmd):
        """Send a command to the persistent subprocess bridge.

        Uses the system's ANSI code page (e.g. cp1250 for Polish) for encoding,
        since VBScript's StdIn reads in the default ANSI encoding.
        """
        proc = self._subprocess_process
        if not proc or proc.poll() is not None:
            return
        try:
            import locale
            encoding = locale.getpreferredencoding() or 'cp1250'
            proc.stdin.write((cmd + '\n').encode(encoding, errors='replace'))
            proc.stdin.flush()
        except Exception as e:
            print(f"[SAPIWorker] Bridge send error: {e}")

    def _bridge_read_response(self, timeout=15.0):
        """Read a response line from the persistent subprocess bridge."""
        proc = self._subprocess_process
        if not proc or proc.poll() is not None:
            return None
        import locale
        encoding = locale.getpreferredencoding() or 'cp1250'
        # Use a thread to read with timeout
        result = [None]
        def _read():
            try:
                result[0] = proc.stdout.readline().decode(encoding, errors='replace').strip()
            except Exception:
                pass
        t = threading.Thread(target=_read, daemon=True)
        t.start()
        t.join(timeout=timeout)
        return result[0]

    # ---- worker loop ----

    def _run(self):
        import pythoncom
        try:
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        except Exception:
            pass

        try:
            self._sapi = win32com.client.Dispatch("SAPI.SpVoice")
        except Exception as e:
            print(f"[SAPIWorker] Failed to create SpVoice: {e}")
            # Direct COM failed entirely — try subprocess bridge
            if self._setup_subprocess_bridge():
                self._run_subprocess_loop()
            else:
                self._ready.set()
            return

        # Validate that SAPI can actually speak (catches bitness mismatches)
        if not self._find_working_voice():
            print("[SAPIWorker] No compatible voice via direct COM, trying subprocess bridge...")
            self._sapi = None
            if self._setup_subprocess_bridge():
                self._run_subprocess_loop()
            else:
                print("[SAPIWorker] No SAPI5 bridge available - SAPI disabled")
                self._ready.set()
            return

        self._ready.set()

        while True:
            try:
                cmd = self._cmd_queue.get()
                if cmd is None:
                    break
                self._process_cmd(cmd)
                self._error_count = 0
            except Exception as e:
                self._error_count += 1
                if self._error_count <= self._max_errors:
                    print(f"[SAPIWorker] Error ({self._error_count}/{self._max_errors}): {e}")
                if self._error_count >= self._max_errors:
                    print(f"[SAPIWorker] SAPI5 disabled after {self._error_count} consecutive errors")
                    self._sapi = None
                    break

    def _setup_subprocess_bridge(self):
        """Try to set up the subprocess bridge. Returns True on success."""
        cscript = self._find_subprocess_bridge()
        if not cscript:
            return False
        self._subprocess_cscript = cscript
        if not self._start_persistent_bridge():
            return False
        self._use_subprocess = True
        # Apply current voice/rate/volume to the bridge
        if self._voice_id:
            self._bridge_send(f"VOICE\t{self._voice_id}")
            self._bridge_read_response(timeout=5.0)
        if self._rate != 0:
            self._bridge_send(f"RATE\t{self._rate}")
        if self._volume != 100:
            self._bridge_send(f"VOLUME\t{self._volume}")
        print(f"[SAPIWorker] Using subprocess bridge: {cscript}")
        return True

    def _run_subprocess_loop(self):
        """Command loop for subprocess bridge mode."""
        self._ready.set()
        while True:
            try:
                cmd = self._cmd_queue.get()
                if cmd is None:
                    self._subprocess_stop()
                    break
                self._process_cmd_subprocess(cmd)
            except Exception as e:
                print(f"[SAPIWorker] Subprocess error: {e}")

    # ---- direct COM commands ----

    def _process_cmd(self, cmd):
        cmd_type = cmd[0]
        if cmd_type == 'speak':
            self._sapi.Speak(cmd[1], cmd[2])
        elif cmd_type == 'stop':
            self._sapi.Speak("", 3)  # SVSFlagsAsync | SVSFPurgeBeforeSpeak
        elif cmd_type == 'set_voice':
            try:
                token = win32com.client.Dispatch("SAPI.SpObjectToken")
                token.SetId(cmd[1])
                # Save previous voice in case the new one is incompatible
                prev_voice = self._sapi.Voice
                prev_id = self._voice_id
                self._sapi.Voice = token
                # Validate: test-speak to memory stream
                if self._test_voice():
                    self._voice_id = cmd[1]
                else:
                    # Voice engine incompatible (e.g. x86 voice on x64 Python)
                    # Try subprocess bridge for this voice
                    print(f"[SAPIWorker] Voice incompatible via direct COM, trying subprocess bridge...")
                    self._sapi.Voice = prev_voice
                    self._voice_id = prev_id
                    if not self._use_subprocess:
                        if self._setup_subprocess_bridge():
                            # Set the voice in the bridge subprocess
                            self._voice_id = cmd[1]
                            self._bridge_send(f"VOICE\t{cmd[1]}")
                            resp = self._bridge_read_response(timeout=5.0)
                            if resp != 'VOICE_OK':
                                print(f"[SAPIWorker] Bridge voice set response: {resp}")
                            self._switch_to_subprocess()
                            return
                        else:
                            print(f"[SAPIWorker] set_voice failed: no bridge available, keeping previous voice")
                    else:
                        self._voice_id = cmd[1]
            except Exception as e:
                print(f"[SAPIWorker] set_voice error: {e}")
        elif cmd_type == 'set_rate':
            self._sapi.Rate = cmd[1]
            self._rate = cmd[1]
        elif cmd_type == 'set_volume':
            self._sapi.Volume = cmd[1]
            self._volume = cmd[1]
        elif cmd_type == 'sync':
            func, event, result = cmd[1], cmd[2], cmd[3]
            try:
                result['value'] = func(self._sapi)
            except Exception as e:
                result['error'] = e
            event.set()
        elif cmd_type == 'generate_file':
            text, temp_path, pitch_offset, event, result = (
                cmd[1], cmd[2], cmd[3], cmd[4], cmd[5])
            try:
                result['value'] = self._do_generate_file(
                    text, temp_path, pitch_offset)
            except Exception as e:
                result['error'] = e
            event.set()

    def _switch_to_subprocess(self):
        """Switch from direct COM to subprocess bridge mid-operation.

        Called from the command loop when a voice change requires
        cross-bitness support. Drains remaining commands through the
        subprocess loop.
        """
        self._sapi = None
        print("[SAPIWorker] Switched to subprocess bridge for cross-bitness voice")
        self._run_subprocess_loop()

    # ---- subprocess bridge commands ----

    def _process_cmd_subprocess(self, cmd):
        """Process commands using the persistent cscript subprocess bridge.

        The subprocess stays running, receiving commands via stdin.
        This eliminates process-creation latency.
        """
        cmd_type = cmd[0]
        if cmd_type == 'speak':
            # Replace tabs/newlines in text to avoid protocol issues
            text = cmd[1].replace('\t', ' ').replace('\n', ' ').replace('\r', '')
            self._bridge_send(f"SPEAK\t{text}")
        elif cmd_type == 'stop':
            self._bridge_send("STOP")
        elif cmd_type == 'set_voice':
            self._bridge_send(f"VOICE\t{cmd[1]}")
            resp = self._bridge_read_response(timeout=5.0)
            if resp == 'VOICE_OK':
                self._voice_id = cmd[1]
            else:
                print(f"[SAPIWorker] Subprocess set_voice failed: {resp}")
        elif cmd_type == 'set_rate':
            self._rate = cmd[1]
            self._bridge_send(f"RATE\t{cmd[1]}")
        elif cmd_type == 'set_volume':
            self._volume = cmd[1]
            self._bridge_send(f"VOLUME\t{cmd[1]}")
        elif cmd_type == 'sync':
            # sync not supported in subprocess mode
            _, event, result = cmd[1], cmd[2], cmd[3]
            result['error'] = RuntimeError("sync not supported in subprocess mode")
            event.set()
        elif cmd_type == 'generate_file':
            text, temp_path, pitch_offset, event, result = (
                cmd[1], cmd[2], cmd[3], cmd[4], cmd[5])
            try:
                result['value'] = self._do_generate_file_subprocess(
                    text, temp_path, pitch_offset)
            except Exception as e:
                result['error'] = e
            event.set()

    def _subprocess_stop(self):
        """Gracefully shut down the persistent cscript subprocess."""
        proc = self._subprocess_process
        if proc and proc.poll() is None:
            try:
                proc.stdin.write(b"QUIT\n")
                proc.stdin.flush()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        self._subprocess_process = None

    def _do_generate_file_subprocess(self, text, temp_path, pitch_offset):
        """Generate speech to WAV file via persistent subprocess bridge.

        Sends GENFILE command and waits for GENFILE_DONE response.
        Supports pitch offset for tone control via SSML.
        """
        text_clean = text.replace('\t', ' ').replace('\n', ' ').replace('\r', '')
        self._bridge_send(f"GENFILE\t{text_clean}\t{temp_path}\t{pitch_offset}")
        resp = self._bridge_read_response(timeout=15.0)
        if resp == 'GENFILE_DONE' and os.path.exists(temp_path) and os.path.getsize(temp_path) > 100:
            return temp_path
        if resp and resp != 'GENFILE_DONE':
            print(f"[SAPIWorker] generate_file subprocess response: {resp}")
        return None

    # ---- file generation (runs on worker thread) ----

    def _do_generate_file(self, text, temp_path, pitch_offset):
        """Generate SAPI5 speech to WAV file with cancellation support."""
        if pitch_offset != 0:
            pitch_value = max(-10, min(10, pitch_offset))
            ssml_text = f'<pitch absmiddle="{pitch_value}">{text}</pitch>'
        else:
            ssml_text = text

        file_stream = win32com.client.Dispatch("SAPI.SpFileStream")
        try:
            file_stream.Format.Type = 22  # SAFT22kHz16BitMono
        except Exception:
            pass

        file_stream.Open(temp_path, 3)  # SSFMCreateForWrite
        original_output = self._sapi.AudioOutputStream
        self._sapi.AudioOutputStream = file_stream

        try:
            self._cancel.clear()
            self._sapi.Speak(ssml_text, 1)  # SVSFlagsAsync
            # Poll for completion, checking cancel flag
            while not self._sapi.WaitUntilDone(50):
                if self._cancel.is_set():
                    self._sapi.Speak("", 3)  # purge
                    return None
        finally:
            try:
                file_stream.Close()
            except Exception:
                pass
            try:
                self._sapi.AudioOutputStream = original_output
            except Exception:
                pass

        if os.path.exists(temp_path) and os.path.getsize(temp_path) > 100:
            return temp_path
        return None

    # ---- public API (called from any thread) ----

    def speak(self, text, flags=3):
        """Non-blocking async speak.  Clears pending speak commands first."""
        if not self.available:
            return
        self._clear_pending()
        self._cancel.clear()
        self._cmd_queue.put(('speak', text, flags))

    def stop(self):
        """Stop current and pending speech immediately."""
        if not self.available:
            return
        self._cancel.set()
        self._clear_pending()
        self._cmd_queue.put(('stop',))

    def set_voice(self, voice_id):
        self._cmd_queue.put(('set_voice', voice_id))

    def set_rate(self, rate):
        self._cmd_queue.put(('set_rate', rate))

    def set_volume(self, volume):
        self._cmd_queue.put(('set_volume', volume))

    def generate_to_file(self, text, temp_path, pitch_offset=0, timeout=15.0):
        """Generate speech to WAV file (blocking).  Returns path or None."""
        if not self.available:
            return None
        event = threading.Event()
        result = {}
        self._cmd_queue.put((
            'generate_file', text, temp_path, pitch_offset, event, result))
        if not event.wait(timeout):
            self._cancel.set()
            return None
        if 'error' in result:
            print(f"[SAPIWorker] File generation error: {result['error']}")
            return None
        return result.get('value')

    def call_sync(self, func, timeout=10.0):
        """Run func(sapi) on the worker thread and wait for result."""
        event = threading.Event()
        result = {}
        self._cmd_queue.put(('sync', func, event, result))
        if not event.wait(timeout):
            return None
        if 'error' in result:
            raise result['error']
        return result.get('value')

    def _clear_pending(self):
        """Remove pending speak/stop commands from queue (keep others)."""
        keep = []
        while True:
            try:
                cmd = self._cmd_queue.get_nowait()
                if cmd[0] not in ('speak', 'stop'):
                    keep.append(cmd)
            except _queue.Empty:
                break
        for cmd in keep:
            self._cmd_queue.put(cmd)


class StereoSpeech:
    """
    Klasa do stereo pozycjonowania mowy SAPI5 z kontrolą wysokości głosu.

    Funkcje:
    - Automatyczne odcinanie ciszy na początku i końcu audio (jak NVDA) - ZAWSZE aktywne
    - Opcjonalne pozycjonowanie głosu w przestrzeni stereo (kontrolowane przez ustawienia)
    - Kontrola wysokości głosu (pitch offset)
    - Używa dedykowanego kanału pygame dla TTS, nie blokując dźwięków UI

    Trimming ciszy jest zawsze aktywny, niezależnie od ustawienia stereo_speech.
    Stereo positioning jest opcjonalny i kontrolowany przez ustawienie 'stereo_speech'.
    """

    def __init__(self):
        self.sapi = None
        self.current_voice = None
        self._sapi_voice_cache = None
        self.default_rate = 0
        self.default_volume = 100
        self.default_pitch = 0
        self.is_speaking = False
        self.speech_lock = threading.Lock()
        self.current_tts_channel = None

        # eSpeak DLL instance
        self.espeak_dll = None
        if ESPEAK_DLL_AVAILABLE:
            try:
                self.espeak_dll = get_espeak_dll()
                print("[StereoSpeech] eSpeak DLL initialized (fast mode)")
            except Exception as e:
                print(f"[StereoSpeech] Error initializing eSpeak DLL: {e}")

        # eSpeak EXE subprocess (interruptible generation)
        self._espeak_process = None

        # Sequence counter for speak_async deduplication
        self._speak_seq = 0

        # eSpeak parameters (shared by espeak_dll and espeak subprocess)
        self.espeak_rate = 175  # Words per minute (default)
        self.espeak_pitch = 50  # Pitch 0-99 (default: 50)
        self.espeak_volume = 100  # Volume 0-200 (default: 100)
        self.espeak_voice = None  # Voice identifier

        # Platform-specific native TTS parameters
        self.say_voice = None     # macOS say voice name
        self.say_rate = 175       # macOS say rate (WPM)
        self.spd_voice = None     # Linux spd-say voice name
        self.spd_rate = 0         # Linux spd-say rate (-100 to 100)
        self._native_process = None  # Running native TTS subprocess

        # Fallback speaker (accessible_output3)
        self.fallback_speaker = accessible_output3.outputs.auto.Auto()

        # TitanTTS Engine Registry - provides ElevenLabs, Milena, and plugin engines
        self._registry = _get_engine_registry()

        # Legacy references for backward compatibility
        self.elevenlabs = None
        self.milena = None
        self._milena_process = None
        if self._registry:
            el = self._registry.get_titantts_engine('elevenlabs')
            if el:
                self.elevenlabs = el
                print("[StereoSpeech] ElevenLabs engine instance ready (via registry)")
            mil = self._registry.get_titantts_engine('milena')
            if mil:
                self.milena = mil
                print("[StereoSpeech] Milena engine instance ready (via registry)")

        # Platform-specific engine selection
        # Prefer eSpeak DLL (fastest), then eSpeak exe, then platform native
        if ESPEAK_DLL_AVAILABLE:
            self.engine = 'espeak_dll'
        elif ESPEAK_AVAILABLE:
            self.engine = 'espeak'
        elif IS_WINDOWS:
            self.engine = 'sapi5'
        elif IS_MACOS and SAY_AVAILABLE:
            self.engine = 'say'
        elif IS_LINUX and SPD_AVAILABLE:
            self.engine = 'spd'
        else:
            # No TTS engine found — will rely on fallback_speaker (accessible_output3)
            self.engine = 'none'

        # Initialize SAPI5 on Windows
        self._sapi_worker = None
        if IS_WINDOWS:
            try:
                self._init_sapi()
            except Exception as e:
                print(f"[StereoSpeech] SAPI5 init error: {e}")
                self.sapi = None
            # Create dedicated SAPI worker thread (avoids COM apartment issues)
            if SAPI_AVAILABLE:
                try:
                    self._sapi_worker = _SAPIWorker()
                    if self._sapi_worker.available:
                        print("[StereoSpeech] SAPI5 worker thread ready")
                    else:
                        print("[StereoSpeech] SAPI5 worker failed to init")
                        self._sapi_worker = None
                except Exception as e:
                    print(f"[StereoSpeech] SAPI5 worker error: {e}")
                    self._sapi_worker = None

        # Register platform engines in registry
        if self._registry:
            self._registry.register_platform_engine('espeak', 'eSpeak NG',
                                                     ESPEAK_AVAILABLE or ESPEAK_DLL_AVAILABLE)
            if IS_WINDOWS:
                self._registry.register_platform_engine('sapi5', 'SAPI5',
                                                         self.sapi is not None)
            if IS_MACOS:
                self._registry.register_platform_engine('say', 'macOS Speech',
                                                         SAY_AVAILABLE)
            if IS_LINUX:
                self._registry.register_platform_engine('spd', 'Speech Dispatcher',
                                                         SPD_AVAILABLE)

        # Load saved user settings (engine, rate, volume, engine configs)
        self._load_saved_settings()

    def _load_saved_settings(self):
        """Load saved stereo speech settings from bg5settings.ini at startup."""
        try:
            from src.settings.settings import load_settings
            settings = load_settings()
            stereo_settings = settings.get('stereo_speech', {})

            # 1. Engine
            engine = stereo_settings.get('engine', '')
            if engine:
                self.set_engine(engine)

            # 2. Engine-specific configs (API keys, model, etc.)
            for key, value in stereo_settings.items():
                if key.startswith('engine.'):
                    parts = key.split('.', 2)
                    if len(parts) == 3:
                        self.set_engine_config(parts[1], parts[2], value)

            # 3. Rate (-10 to +10)
            try:
                rate = int(stereo_settings.get('rate', '0'))
                if rate != 0:
                    self.set_rate(rate)
            except (ValueError, TypeError):
                pass

            # 4. Volume (0-100)
            try:
                volume = int(stereo_settings.get('volume', '100'))
                if volume != 100:
                    self.set_volume(volume)
            except (ValueError, TypeError):
                pass

            # 5. Voice
            voice_id = stereo_settings.get('voice', '')
            if voice_id:
                try:
                    voices = self.get_available_voices()
                    for i, v in enumerate(voices):
                        vid = v.get('id', v) if isinstance(v, dict) else v
                        if vid == voice_id or str(v) == voice_id:
                            self.set_voice(i)
                            break
                except Exception:
                    pass

            print(f"[StereoSpeech] Loaded saved settings: engine={self.engine}, rate={stereo_settings.get('rate', '0')}")
        except Exception as e:
            print(f"[StereoSpeech] Could not load saved settings: {e}")

    def __del__(self):
        """Cleanup COM objects on destruction safely."""
        try:
            # Stop any ongoing speech first
            if hasattr(self, 'is_speaking') and self.is_speaking:
                self.stop()
            
            # Clean up COM objects safely
            if hasattr(self, 'sapi') and self.sapi is not None:
                try:
                    # Reset audio output to default before cleanup
                    if hasattr(self.sapi, 'AudioOutputStream'):
                        self.sapi.AudioOutputStream = None
                except (AttributeError, OSError):
                    pass
                
                # Release COM object
                try:
                    del self.sapi
                except (AttributeError, OSError):
                    pass
                finally:
                    self.sapi = None
            
            # Don't call CoUninitialize in destructor - can cause crashes
            # COM will cleanup automatically when process ends
        except Exception:
            pass  # Prevent any exceptions during cleanup
    
    def _init_sapi(self):
        """Inicjalizuje SAPI5 voice object safely."""
        try:
            import pythoncom
            
            # Initialize COM with apartment threading
            try:
                pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
            except pythoncom.com_error as e:
                # COM might already be initialized
                if e.hresult != -2147417850:  # RPC_E_CHANGED_MODE
                    raise
            
            # Create SAPI voice object
            self.sapi = win32com.client.Dispatch("SAPI.SpVoice")
            if self.sapi:
                # Save default settings safely
                try:
                    self.default_rate = self.sapi.Rate
                    self.default_volume = self.sapi.Volume
                    self.current_voice = self.sapi.Voice
                except (AttributeError, OSError) as e:
                    print(f"Warning: Could not read SAPI default settings: {e}")
                    self.default_rate = 0
                    self.default_volume = 100
                    
        except Exception as e:
            print(f"[StereoSpeech] SAPI5 init error: {e}")
            self.sapi = None
            # Don't call CoUninitialize on errors - can cause crashes
    
    def is_stereo_enabled(self):
        """Sprawdza czy stereo speech jest włączone w ustawieniach."""
        return get_setting('stereo_speech', 'False', 'invisible_interface').lower() in ['true', '1']

    def get_silence_threshold(self):
        """Get silence threshold from settings in dB (default -50.0)"""
        try:
            threshold = float(get_setting('silence_threshold', '-50.0', 'invisible_interface'))
            # Clamp to reasonable range
            return max(-80.0, min(-20.0, threshold))
        except (ValueError, TypeError):
            return -50.0

    def _generate_espeak_dll_to_memory(self, text, pitch_offset=0):
        """
        Generate TTS using bundled eSpeak executable (optimized, faster than standard subprocess).
        Uses Popen so the process can be killed by stop() if interrupted.

        Args:
            text (str): Text to speak
            pitch_offset (int): Pitch offset -10 to +10

        Returns:
            AudioSegment or None
        """
        if not PYDUB_AVAILABLE:
            return None

        # Check if bundled espeak is available
        if not ESPEAK_AVAILABLE or not ESPEAK_PATH:
            return None

        try:
            # Build optimized eSpeak command for speed
            cmd = [ESPEAK_PATH]

            # Add data path for bundled eSpeak
            if ESPEAK_DATA_PATH:
                cmd.extend(['--path', ESPEAK_DATA_PATH])

            # Calculate pitch with offset
            if hasattr(self, 'espeak_pitch'):
                pitch = self.espeak_pitch + (pitch_offset * 5)
            else:
                pitch = 50 + (pitch_offset * 5)
            pitch = max(0, min(99, pitch))

            # Add parameters
            if hasattr(self, 'espeak_rate'):
                cmd.extend(['-s', str(self.espeak_rate)])
            if hasattr(self, 'espeak_volume'):
                cmd.extend(['-a', str(self.espeak_volume)])
            cmd.extend(['-p', str(pitch)])

            # Voice
            if hasattr(self, 'espeak_voice') and self.espeak_voice:
                cmd.extend(['-v', self.espeak_voice])

            # Output to stdout as WAV
            cmd.append('--stdout')

            # Text as argument (faster than stdin for short text)
            cmd.append(text)

            # Use Popen so we can kill it if stop() is called
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                self._espeak_process = proc

                try:
                    stdout, _ = proc.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
                    print("[StereoSpeech] eSpeak timeout")
                    return None
                finally:
                    if self._espeak_process is proc:
                        self._espeak_process = None

                if proc.returncode != 0 or not stdout or len(stdout) < 100:
                    return None

                audio = AudioSegment.from_wav(io.BytesIO(stdout))
                print(f"[StereoSpeech] eSpeak fast: {len(audio)}ms")
                return audio

            except Exception as e:
                print(f"[StereoSpeech] eSpeak exec error: {e}")
                return None

        except Exception as e:
            print(f"[StereoSpeech] Error in espeak_dll_to_memory: {e}")
            return None


    def _generate_espeak_to_memory(self, text, pitch_offset=0):
        """
        Generuje TTS bezpośrednio do pamięci używając eSpeak (szybkie, bez pliku).

        Args:
            text (str): Tekst do wypowiedzenia
            pitch_offset (int): Przesunięcie wysokości głosu -10 do +10

        Returns:
            AudioSegment: Audio segment lub None w przypadku błędu
        """
        if not ESPEAK_AVAILABLE or not PYDUB_AVAILABLE:
            return None

        try:
            # Build eSpeak command
            cmd = [ESPEAK_PATH]

            # Add data path if bundled eSpeak
            if ESPEAK_DATA_PATH:
                cmd.extend(['--path', ESPEAK_DATA_PATH])

            # Calculate pitch with offset
            pitch = self.espeak_pitch + (pitch_offset * 5)  # Map -10..10 to -50..50
            pitch = max(0, min(99, pitch))

            # Add parameters
            cmd.extend(['-s', str(self.espeak_rate)])  # Speed (wpm)
            cmd.extend(['-p', str(pitch)])  # Pitch
            cmd.extend(['-a', str(self.espeak_volume)])  # Amplitude/volume

            # Add voice if specified
            if self.espeak_voice:
                cmd.extend(['-v', self.espeak_voice])

            # Output to stdout as WAV
            cmd.append('--stdout')

            # Use stdin for text to properly handle UTF-8 encoding
            cmd.append('--stdin')

            # Run eSpeak with piped output (tracked so stop() can kill it)
            process = None
            try:
                process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    encoding=None  # Binary mode for stdout
                )
                self._espeak_process = process

                # Send text through stdin with proper UTF-8 encoding
                # Add a period and space at the end to prevent eSpeak from cutting last letter
                text_with_padding = text.rstrip() + ". "
                text_bytes = text_with_padding.encode('utf-8')

                # Get WAV data from stdout
                try:
                    wav_data, _ = process.communicate(input=text_bytes, timeout=10)
                except subprocess.TimeoutExpired:
                    print("[StereoSpeech] eSpeak TTS timeout")
                    if process:
                        try:
                            process.kill()
                            process.wait(timeout=1)
                        except Exception:
                            pass
                    return None
                except Exception as e:
                    print(f"[StereoSpeech] eSpeak communicate error: {e}")
                    if process:
                        try:
                            process.kill()
                        except Exception:
                            pass
                    return None

                # Check if we got data
                if not wav_data or len(wav_data) < 100:
                    print("[StereoSpeech] eSpeak did not generate audio data")
                    return None

                # Load audio from memory using pydub
                try:
                    audio = AudioSegment.from_wav(io.BytesIO(wav_data))
                    print(f"[StereoSpeech] eSpeak audio generated in memory: {len(audio)}ms")
                    return audio
                except Exception as e:
                    print(f"[StereoSpeech] Error loading WAV data: {e}")
                    return None

            except FileNotFoundError:
                print("[StereoSpeech] eSpeak executable not found")
                return None
            except Exception as e:
                print(f"[StereoSpeech] Error launching eSpeak: {e}")
                if process:
                    try:
                        process.kill()
                    except Exception:
                        pass
                return None
            finally:
                if self._espeak_process is process:
                    self._espeak_process = None

        except Exception as e:
            print(f"[StereoSpeech] Error generating eSpeak TTS to memory: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _generate_tts_to_file(self, text, pitch_offset=0):
        """
        Generuje TTS do pliku tymczasowego używając SAPI5.
        Thread-safe version with proper COM handling.
        
        Args:
            text (str): Tekst do wypowiedzenia
            pitch_offset (int): Przesunięcie wysokości głosu -10 do +10
            
        Returns:
            str: Ścieżka do pliku tymczasowego lub None w przypadku błędu
        """
        if not self.sapi:
            return None
            
        try:
            # Inicjalizuj COM dla tego wątku z retry logic
            import pythoncom
            retry_count = 0
            max_retries = 3
            
            while retry_count < max_retries:
                try:
                    # Use apartment threading to avoid COM issues
                    pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
                    break
                except pythoncom.com_error as e:
                    # Handle already initialized COM
                    if e.hresult == -2147417850:  # RPC_E_CHANGED_MODE
                        break  # COM already initialized with different threading model
                    retry_count += 1
                    if retry_count >= max_retries:
                        print(f"Failed to initialize COM after {max_retries} retries: {e}")
                        return None
                    time.sleep(0.05)
                except Exception as e:
                    retry_count += 1
                    if retry_count >= max_retries:
                        print(f"Failed to initialize COM after {max_retries} retries: {e}")
                        return None
                    time.sleep(0.05)
            # Utwórz plik tymczasowy z pełną ścieżką
            temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            temp_path = os.path.abspath(temp_file.name)
            temp_file.close()
            
            # Przygotuj tekst z kontrolą wysokości głosu używając SSML
            if pitch_offset != 0:
                # SAPI5 obsługuje SSML markup dla kontroli głosu
                pitch_value = max(-10, min(10, pitch_offset))
                # Użyj prosty SSML dla kontroli pitch
                ssml_text = f'<pitch absmiddle="{pitch_value}">{text}</pitch>'
            else:
                ssml_text = text
            
            # Utwórz nowy SpFileStream object
            file_stream = win32com.client.Dispatch("SAPI.SpFileStream")
            
            # Ustaw format audio (16-bit, 22kHz, mono - stabilny format)
            # 22 = SAFT22kHz16BitMono
            try:
                file_stream.Format.Type = 22
            except:
                pass  # Jeśli nie można ustawić formatu, użyj domyślnego
            
            # Otwórz plik do zapisu (3 = SSFMCreateForWrite)
            file_stream.Open(temp_path, 3)
            
            # Zapisz oryginalny output stream
            original_output = self.sapi.AudioOutputStream
            
            # Ustaw output na plik
            self.sapi.AudioOutputStream = file_stream
            
            # Wypowiedz tekst safely
            try:
                self.sapi.Speak(ssml_text, 0)  # 0 = synchronous
                
                # Poczekaj aż skończy z timeout
                if not self.sapi.WaitUntilDone(10000):  # Max 10 sekund
                    print("Warning: SAPI TTS timeout")
                    
            except Exception as e:
                print(f"Error during SAPI speak: {e}")
            finally:
                # Always clean up properly
                try:
                    file_stream.Close()
                except Exception as e:
                    print(f"Error closing file stream: {e}")
                try:
                    self.sapi.AudioOutputStream = original_output
                except Exception as e:
                    print(f"Error restoring audio output: {e}")
            
            # Sprawdź czy plik został utworzony i ma zawartość
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 100:  # Minimum 100 bajtów
                print(f"TTS plik utworzony: {temp_path}, rozmiar: {os.path.getsize(temp_path)} bajtów")
                return temp_path
            else:
                print(f"Plik TTS nie został utworzony prawidłowo: {temp_path}")
                return None
            
        except Exception as e:
            print(f"[StereoSpeech] Error generating TTS to file: {e}")
            import traceback
            traceback.print_exc()
            # Usuń plik tymczasowy w przypadku błędu
            if 'temp_path' in locals() and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass
            return None

    def _generate_say_to_memory(self, text, pitch_offset=0):
        """
        Generate TTS using macOS 'say' command to memory (via temp file).

        Args:
            text (str): Text to speak
            pitch_offset (int): Not used (macOS say doesn't support pitch)

        Returns:
            AudioSegment or None
        """
        if not SAY_AVAILABLE or not PYDUB_AVAILABLE:
            return None
        try:
            temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            temp_path = temp_file.name
            temp_file.close()

            cmd = ['say']
            if self.say_voice:
                cmd.extend(['-v', self.say_voice])
            cmd.extend(['-r', str(self.say_rate)])
            cmd.extend(['-o', temp_path, '--data-format=LEI16@22050'])
            cmd.append(text)

            result = subprocess.run(cmd, capture_output=True, timeout=10, check=False)
            if result.returncode != 0 or not os.path.exists(temp_path):
                return None

            audio = AudioSegment.from_wav(temp_path)
            return audio
        except Exception as e:
            print(f"[StereoSpeech] macOS say error: {e}")
            return None
        finally:
            if 'temp_path' in locals() and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass

    def _generate_elevenlabs_to_memory(self, text, pitch_offset=0):
        """
        Generate TTS via ElevenLabs API with disk caching.

        Normalises punctuation, checks cache, calls API on miss,
        then applies pitch offset via pydub frame-rate trick.

        Args:
            text (str):         Text to synthesize.
            pitch_offset (int): Semitone shift -10..+10.

        Returns:
            pydub.AudioSegment or None
        """
        if not ELEVENLABS_AVAILABLE or not self.elevenlabs:
            return None
        if not PYDUB_AVAILABLE:
            return None
        try:
            audio = self.elevenlabs.generate(text, pitch_offset)
            if audio is not None:
                print(f"[StereoSpeech] ElevenLabs: {len(audio)} ms audio ready")
            return audio
        except Exception as e:
            print(f"[StereoSpeech] ElevenLabs generation error: {e}")
            return None

    def _generate_milena_to_memory(self, text, pitch_offset=0):
        """
        Generate TTS via Milena engine (milena4w.exe) with disk caching.

        Args:
            text (str):         Text to synthesize.
            pitch_offset (int): Semitone shift -10..+10.

        Returns:
            pydub.AudioSegment or None
        """
        if not MILENA_AVAILABLE or not self.milena:
            return None
        if not PYDUB_AVAILABLE:
            return None
        try:
            audio = self.milena.generate(text, pitch_offset)
            if audio is not None:
                print(f"[StereoSpeech] Milena: {len(audio)} ms audio ready")
            return audio
        except Exception as e:
            print(f"[StereoSpeech] Milena generation error: {e}")
            return None

    def set_elevenlabs_api_key(self, api_key):
        """Set ElevenLabs API key on the engine instance. (Backward compat)"""
        self.set_engine_config('elevenlabs', 'api_key', api_key)

    def set_elevenlabs_voice_id(self, voice_id):
        """Set ElevenLabs voice ID on the engine instance. (Backward compat)"""
        if self.elevenlabs:
            self.elevenlabs.set_voice_id(voice_id)

    def set_engine_config(self, engine_id, key, value):
        """
        Set a configuration value on a TitanTTS engine.

        Args:
            engine_id (str): Engine identifier (e.g. 'elevenlabs')
            key (str): Config key (e.g. 'api_key')
            value: Value to set
        """
        registry = _get_engine_registry()
        if registry:
            engine = registry.get_titantts_engine(engine_id)
            if engine and hasattr(engine, 'configure'):
                engine.configure(key, value)

    def get_engine_config(self, engine_id, key, default=None):
        """
        Get a configuration value from a TitanTTS engine.

        Args:
            engine_id (str): Engine identifier
            key (str): Config key
            default: Default value if not set

        Returns:
            The config value, or default
        """
        registry = _get_engine_registry()
        if registry:
            engine = registry.get_titantts_engine(engine_id)
            if engine and hasattr(engine, 'get_config'):
                return engine.get_config(key, default)
        return default

    def _speak_native_say(self, text):
        """Direct speech using macOS 'say' command (no stereo)."""
        if not SAY_AVAILABLE:
            return False
        try:
            # Kill previous say process
            if self._native_process and self._native_process.poll() is None:
                self._native_process.kill()

            cmd = ['say']
            if self.say_voice:
                cmd.extend(['-v', self.say_voice])
            cmd.extend(['-r', str(self.say_rate)])
            cmd.append(text)
            self._native_process = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return True
        except Exception as e:
            print(f"[StereoSpeech] macOS say direct error: {e}")
            return False

    def _speak_native_spd(self, text, pitch_offset=0):
        """Direct speech using Linux spd-say command (no stereo, supports pitch via -p)."""
        if not SPD_AVAILABLE:
            return False
        try:
            # Kill previous spd-say process
            if self._native_process and self._native_process.poll() is None:
                self._native_process.kill()

            cmd = [SPD_PATH]
            if self.spd_voice:
                cmd.extend(['-y', self.spd_voice])
            if self.spd_rate != 0:
                cmd.extend(['-r', str(self.spd_rate)])
            if pitch_offset != 0:
                # spd-say -p accepts -100..100; map pitch_offset (-10..10) proportionally
                spd_pitch = max(-100, min(100, pitch_offset * 10))
                cmd.extend(['-p', str(spd_pitch)])
            cmd.append(text)
            self._native_process = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return True
        except Exception as e:
            print(f"[StereoSpeech] spd-say direct error: {e}")
            return False

    def speak(self, text, position=0.0, pitch_offset=0, use_fallback=True, _seq=None):
        """
        Speaks text with optional stereo positioning and pitch control.

        Always trims leading/trailing silence (like NVDA).
        Stereo positioning is optional (controlled by 'stereo_speech' setting).

        Args:
            text (str): Text to speak
            position (float): Stereo position from -1.0 (left) to 1.0 (right)
            pitch_offset (int): Pitch offset -10 to +10
            use_fallback (bool): Whether to use fallback if engine fails
            _seq (int|None): Sequence number from speak_async for freshness check
        """
        if not text:
            return

        # Add timeout protection for the lock to prevent hangs
        lock_acquired = False
        try:
            lock_acquired = self.speech_lock.acquire(timeout=2.0)
            if not lock_acquired:
                print("Warning: Could not acquire speech lock, using fallback")
                if use_fallback:
                    self.fallback_speaker.speak(text)
                return

            # Check if a newer message superseded this one while waiting for the lock
            if _seq is not None and _seq != self._speak_seq:
                return

            self.stop()
            self.is_speaking = True

            try:
                # Fast direct speech path: center position, no pitch change, no stereo needed
                if (position == 0.0 or not self.is_stereo_enabled()) and pitch_offset == 0:
                    if self.engine == 'espeak_dll' and self.espeak_dll:
                        try:
                            self.espeak_dll.speak(text, interrupt=True)
                            return  # Async - don't wait
                        except Exception as e:
                            print(f"[StereoSpeech] eSpeak DLL error: {e}")
                    elif self.engine == 'say':
                        if self._speak_native_say(text):
                            return
                    elif self.engine == 'spd':
                        if self._speak_native_spd(text):
                            return
                    elif self.engine == 'sapi5' and self._sapi_worker:
                        try:
                            self._sapi_worker.speak(text, 3)
                            return
                        except Exception as e:
                            print(f"[StereoSpeech] SAPI5 direct error: {e}")

                # Check if pydub is available for audio processing (needed for stereo/trim)
                if not PYDUB_AVAILABLE:
                    # No pydub - try direct speech methods (pitch_offset lost for engines
                    # that can't synthesize to memory, except spd which supports -p)
                    if self.engine == 'espeak_dll' and self.espeak_dll:
                        self.espeak_dll.speak(text, interrupt=True)
                        return
                    if self.engine == 'say' and self._speak_native_say(text):
                        return
                    if self.engine == 'spd' and self._speak_native_spd(text, pitch_offset):
                        return
                    if use_fallback:
                        self.fallback_speaker.speak(text)
                    return

                # Generate TTS audio for stereo/trim processing
                audio = None
                temp_file = None

                if self.engine in ('espeak_dll', 'espeak'):
                    # Release lock during eSpeak generation (subprocess ~100-300ms)
                    # so newer messages aren't blocked waiting for the lock
                    if lock_acquired:
                        self.speech_lock.release()
                        lock_acquired = False

                    # Prefer EXE subprocess (fast, no re-initialization)
                    if ESPEAK_AVAILABLE:
                        audio = self._generate_espeak_dll_to_memory(text, pitch_offset)
                    if not audio and ESPEAK_AVAILABLE:
                        audio = self._generate_espeak_to_memory(text, pitch_offset)
                    # DLL-only fallback: re-init in RETRIEVAL mode (no double-playback)
                    if not audio and self.espeak_dll:
                        audio = self.espeak_dll.synthesize_to_memory(text, pitch_offset)

                    # Check if a newer message arrived during generation
                    if _seq is not None and _seq != self._speak_seq:
                        return

                    # Re-acquire lock for playback
                    lock_acquired = self.speech_lock.acquire(timeout=2.0)
                    if not lock_acquired:
                        if use_fallback:
                            self.fallback_speaker.speak(text)
                        return

                    # Check freshness again after lock acquisition
                    if _seq is not None and _seq != self._speak_seq:
                        return

                    self.stop()  # Stop any playback that started while unlocked
                    self.is_speaking = True

                    if not audio:
                        # All generation failed: DLL direct speak (no stereo/pitch)
                        if self.espeak_dll:
                            self.espeak_dll.speak(text, interrupt=True)
                        elif use_fallback:
                            self.fallback_speaker.speak(text)
                        return
                elif self.engine == 'spd':
                    # spd-say cannot generate WAV for stereo processing;
                    # use direct speech with pitch support (no stereo possible)
                    self._speak_native_spd(text, pitch_offset)
                    return
                elif self.engine == 'sapi5' and self._sapi_worker:
                    # Release lock during SAPI5 generation (can take 200-500ms)
                    if lock_acquired:
                        self.speech_lock.release()
                        lock_acquired = False

                    # Generate via worker thread (proper COM apartment)
                    temp_wav = tempfile.NamedTemporaryFile(
                        suffix='.wav', delete=False)
                    temp_wav_path = os.path.abspath(temp_wav.name)
                    temp_wav.close()
                    temp_file = self._sapi_worker.generate_to_file(
                        text, temp_wav_path, pitch_offset)
                    if not temp_file and os.path.exists(temp_wav_path):
                        try:
                            os.unlink(temp_wav_path)
                        except Exception:
                            pass

                    # Check if a newer message arrived during generation
                    if _seq is not None and _seq != self._speak_seq:
                        if temp_file:
                            try:
                                os.unlink(temp_file)
                            except Exception:
                                pass
                        return

                    # Re-acquire lock for playback
                    lock_acquired = self.speech_lock.acquire(timeout=2.0)
                    if not lock_acquired:
                        if temp_file:
                            try:
                                os.unlink(temp_file)
                            except Exception:
                                pass
                        # Try direct SAPI5 before ao3 fallback (prevents double speech)
                        try:
                            self._sapi_worker.speak(text, 3)
                        except Exception:
                            if use_fallback:
                                self.fallback_speaker.speak(text)
                        return

                    # Check freshness again after lock acquisition
                    if _seq is not None and _seq != self._speak_seq:
                        if temp_file:
                            try:
                                os.unlink(temp_file)
                            except Exception:
                                pass
                        return

                    self.stop()
                    self.is_speaking = True

                    if not temp_file:
                        # Generation failed - use direct SAPI5 (not ao3 - prevents double speech)
                        try:
                            self._sapi_worker.speak(text, 3)
                        except Exception:
                            if use_fallback:
                                self.fallback_speaker.speak(text)
                        return
                    audio = AudioSegment.from_wav(temp_file)
                elif self.engine == 'say':
                    audio = self._generate_say_to_memory(text, pitch_offset)
                    if not self.is_speaking:
                        return  # Interrupted during generation
                    if not audio:
                        self._speak_native_say(text)
                        return
                else:
                    # Generic TitanTTS engine dispatch (registry engines)
                    registry = _get_engine_registry()
                    tts_engine = registry.get_titantts_engine(self.engine) if registry else None
                    if tts_engine and tts_engine.is_available():
                        # Release lock during slow generation (API/subprocess)
                        if getattr(tts_engine, 'needs_lock_release', False):
                            if lock_acquired:
                                self.speech_lock.release()
                                lock_acquired = False

                        try:
                            audio = tts_engine.generate(text, pitch_offset)
                        except Exception as e:
                            print(f"[StereoSpeech] {tts_engine.engine_name} generation error: {e}")
                            audio = None

                        if getattr(tts_engine, 'needs_lock_release', False):
                            # Check if a newer message arrived during generation
                            if _seq is not None and _seq != self._speak_seq:
                                return

                            # Re-acquire lock for playback
                            lock_acquired = self.speech_lock.acquire(timeout=2.0)
                            if not lock_acquired:
                                if use_fallback:
                                    self.fallback_speaker.speak(text)
                                return

                            # Double-check freshness after lock acquisition
                            if _seq is not None and _seq != self._speak_seq:
                                return

                            self.stop()
                            self.is_speaking = True

                        if not audio:
                            if use_fallback:
                                self.fallback_speaker.speak(text)
                            return
                    else:
                        if use_fallback:
                            self.fallback_speaker.speak(text)
                        return

                try:
                    # Trim silence (always active - improves responsiveness)
                    try:
                        silence_threshold = self.get_silence_threshold()
                        audio = trim_silence(audio, silence_threshold=silence_threshold)
                    except Exception as e:
                        print(f"Warning: Could not trim silence: {e}")

                    # Apply stereo panning if enabled
                    if position != 0.0 and self.is_stereo_enabled():
                        panned_audio = audio.pan(position)
                    else:
                        panned_audio = audio

                    # Export to memory buffer
                    try:
                        audio_buffer = io.BytesIO()
                        panned_audio.export(audio_buffer, format="wav")
                        audio_buffer.seek(0)
                    except Exception as e:
                        print(f"[StereoSpeech] Error exporting audio: {e}")
                        if use_fallback:
                            self.fallback_speaker.speak(text)
                        return

                    # Play via dedicated Titan TTS channel (channel 4)
                    try:
                        import pygame

                        if not pygame.mixer.get_init():
                            try:
                                pygame.mixer.pre_init(frequency=22050, size=-16, channels=2, buffer=1024)
                                pygame.mixer.init()
                            except Exception as e:
                                print(f"[StereoSpeech] Error initializing pygame mixer: {e}")
                                if use_fallback:
                                    self.fallback_speaker.speak(text)
                                return

                        # Always use dedicated TTS channel – never steals UI sound slots
                        tts_channel = None
                        try:
                            from src.titan_core.sound import get_tts_channel
                            tts_channel = get_tts_channel()
                        except Exception as _e:
                            print(f"[StereoSpeech] get_tts_channel failed: {_e}")
                        if tts_channel is None:
                            # Fallback: find any free channel (should rarely happen)
                            tts_channel = pygame.mixer.find_channel()
                        if not tts_channel:
                            if use_fallback:
                                self.fallback_speaker.speak(text)
                            return

                        try:
                            sound = pygame.mixer.Sound(audio_buffer)
                            tts_channel.play(sound)
                            self.current_tts_channel = tts_channel

                            # Release lock while playing so a new message can interrupt
                            if lock_acquired:
                                self.speech_lock.release()
                                lock_acquired = False

                            while tts_channel.get_busy():
                                if not self.is_speaking:
                                    tts_channel.stop()
                                    break
                                time.sleep(0.05)

                            self.current_tts_channel = None
                        except Exception as e:
                            print(f"[StereoSpeech] Error playing sound: {e}")
                            if use_fallback:
                                self.fallback_speaker.speak(text)
                            return

                    except ImportError:
                        if use_fallback:
                            self.fallback_speaker.speak(text)
                        return

                finally:
                    if temp_file:
                        try:
                            os.unlink(temp_file)
                        except:
                            pass
                
            except Exception as e:
                print(f"[StereoSpeech] Error during stereo speech: {e}")
                # Fallback do standardowego TTS
                if use_fallback:
                    self.fallback_speaker.speak(text)
            finally:
                self.is_speaking = False
        finally:
            # Always release the lock if it was acquired
            if lock_acquired:
                self.speech_lock.release()
    
    def speak_async(self, text, position=0.0, pitch_offset=0, use_fallback=True):
        """
        Wypowiada tekst asynchronicznie z pozycjonowaniem stereo.
        Używa licznika sekwencji, żeby stare wiadomości czekające na lock były pomijane.

        Args:
            text (str): Tekst do wypowiedzenia
            position (float): Pozycja stereo od -1.0 (lewo) do 1.0 (prawo)
            pitch_offset (int): Przesunięcie wysokości głosu -10 do +10
            use_fallback (bool): Czy użyć fallback jeśli SAPI5 nie działa
        """
        self._speak_seq += 1
        my_seq = self._speak_seq

        # Signal current speech to stop immediately (without waiting for the lock):
        # sets is_speaking=False, kills EXE subprocess, cancels DLL, stops pygame channel.
        # This unblocks any thread stuck in communicate() or espeak_Synchronize().
        self.stop()

        def speak_thread():
            # If a newer message arrived while we were waiting, skip this one
            if my_seq != self._speak_seq:
                return
            self.speak(text, position, pitch_offset, use_fallback, _seq=my_seq)

        thread = threading.Thread(target=speak_thread)
        thread.daemon = True
        thread.start()
    
    def stop(self):
        """Stops current TTS speech safely."""
        try:
            self.is_speaking = False

            # Stop eSpeak DLL (always cancel - synthesis may be in progress even if not "playing")
            if hasattr(self, 'espeak_dll') and self.espeak_dll:
                try:
                    self.espeak_dll.cancel()
                except Exception as e:
                    print(f"[StereoSpeech] Error stopping eSpeak DLL: {e}")

            # Stop current TTS pygame channel
            if hasattr(self, 'current_tts_channel') and self.current_tts_channel:
                try:
                    if self.current_tts_channel.get_busy():
                        self.current_tts_channel.stop()
                except (AttributeError, Exception) as e:
                    print(f"[StereoSpeech] Error stopping TTS channel: {e}")
                finally:
                    self.current_tts_channel = None

            # Stop SAPI5 via worker thread (proper COM apartment)
            if IS_WINDOWS and hasattr(self, '_sapi_worker') and self._sapi_worker:
                try:
                    self._sapi_worker.stop()
                except Exception as e:
                    print(f"[StereoSpeech] Error stopping SAPI: {e}")

            # Stop eSpeak EXE generation subprocess (if running)
            if hasattr(self, '_espeak_process') and self._espeak_process:
                try:
                    if self._espeak_process.poll() is None:
                        self._espeak_process.kill()
                except Exception:
                    pass
                self._espeak_process = None

            # Stop TitanTTS engine (Milena, plugin engines, etc.)
            registry = _get_engine_registry()
            if registry:
                tts_engine = registry.get_titantts_engine(self.engine) if hasattr(self, 'engine') else None
                if tts_engine and hasattr(tts_engine, 'stop'):
                    try:
                        tts_engine.stop()
                    except Exception:
                        pass

            # Stop native TTS subprocess (macOS say / Linux spd-say)
            if hasattr(self, '_native_process') and self._native_process:
                try:
                    if self._native_process.poll() is None:
                        self._native_process.kill()
                except Exception:
                    pass
                self._native_process = None

        except Exception as e:
            print(f"[StereoSpeech] Error stopping speech: {e}")
    
    def set_engine(self, engine):
        """
        Sets the TTS engine.

        Args:
            engine (str): Engine type ('espeak', 'sapi5', 'say', 'spd')
        """
        if engine == 'espeak':
            if ESPEAK_DLL_AVAILABLE:
                self.engine = 'espeak_dll'
                print("[StereoSpeech] Switched to eSpeak DLL engine (fast mode)")
            elif ESPEAK_AVAILABLE:
                self.engine = 'espeak'
                print("[StereoSpeech] Switched to eSpeak subprocess engine")
            else:
                print("[StereoSpeech] eSpeak not available")
        elif engine == 'sapi5' and IS_WINDOWS and self.sapi:
            self.engine = 'sapi5'
            print("[StereoSpeech] Switched to SAPI5 engine")
        elif engine == 'say' and IS_MACOS and SAY_AVAILABLE:
            self.engine = 'say'
            print("[StereoSpeech] Switched to macOS Speech engine")
        elif engine == 'spd' and IS_LINUX and SPD_AVAILABLE:
            self.engine = 'spd'
            print("[StereoSpeech] Switched to Speech Dispatcher engine")
        else:
            # Check TitanTTS engine registry for custom/plugin engines
            registry = _get_engine_registry()
            if registry and registry.is_titantts_engine(engine):
                tts_engine = registry.get_titantts_engine(engine)
                if tts_engine:
                    self.engine = engine
                    print(f"[StereoSpeech] Switched to TitanTTS engine: {tts_engine.engine_name}")
                else:
                    print(f"[StereoSpeech] TitanTTS engine '{engine}' not available")
            else:
                print(f"[StereoSpeech] Engine '{engine}' not available on this platform")

    def get_engine(self):
        """
        Returns current TTS engine.

        Returns:
            str: Current engine ('sapi5', 'espeak', 'espeak_dll', 'say', 'spd')
        """
        return self.engine

    def get_available_engines(self):
        """
        Returns list of available TTS engines (platform-dependent).

        TitanTTS engines are always listed (they have config UIs in settings),
        platform engines only when available on this platform.

        Returns:
            list: List of engine identifiers, TitanTTS first then platform
        """
        registry = _get_engine_registry()
        if registry:
            # TitanTTS engines always shown (user can configure them in settings)
            titantts = [e.engine_id for e in registry.get_all_engines()
                        if e.engine_category == 'titantts']
            # Platform engines only when available
            platform = [e.engine_id for e in registry.get_all_engines()
                        if e.engine_category == 'platform' and e.is_available()]
            return titantts + platform

        # Fallback if registry not available
        engines = []
        if ESPEAK_AVAILABLE or ESPEAK_DLL_AVAILABLE:
            engines.append('espeak')
        if IS_WINDOWS and self.sapi:
            engines.append('sapi5')
        if IS_MACOS and SAY_AVAILABLE:
            engines.append('say')
        if IS_LINUX and SPD_AVAILABLE:
            engines.append('spd')
        return engines

    def set_rate(self, rate):
        """
        Sets speech rate.

        Args:
            rate (int): Rate from -10 to +10
        """
        try:
            if self.engine == 'sapi5' and self.sapi:
                clamped_rate = max(-10, min(10, rate))
                self.sapi.Rate = clamped_rate
                if self._sapi_worker:
                    self._sapi_worker.set_rate(clamped_rate)
            elif self.engine in ('espeak', 'espeak_dll'):
                # Map -10..10 to 80..450 wpm
                self.espeak_rate = int(175 + (rate * 27.5))
                self.espeak_rate = max(80, min(450, self.espeak_rate))
                # Sync to DLL instance
                if self.espeak_dll:
                    self.espeak_dll.set_rate(rate)
            elif self.engine == 'say':
                # macOS say: map -10..10 to 90..500 wpm
                self.say_rate = int(175 + (rate * 30))
                self.say_rate = max(90, min(500, self.say_rate))
            elif self.engine == 'spd':
                # spd-say: map -10..10 to -100..100
                self.spd_rate = max(-100, min(100, rate * 10))
            else:
                # Delegate to TitanTTS engine via registry
                registry = _get_engine_registry()
                if registry:
                    tts_engine = registry.get_titantts_engine(self.engine)
                    if tts_engine and hasattr(tts_engine, 'set_rate'):
                        tts_engine.set_rate(rate)
        except Exception as e:
            print(f"[StereoSpeech] Error setting rate: {e}")

    def set_volume(self, volume):
        """
        Sets speech volume.

        Args:
            volume (int): Volume from 0 to 100
        """
        try:
            if self.engine == 'sapi5' and self.sapi:
                clamped_vol = max(0, min(100, volume))
                self.sapi.Volume = clamped_vol
                self.default_volume = self.sapi.Volume
                if self._sapi_worker:
                    self._sapi_worker.set_volume(clamped_vol)
            elif self.engine in ('espeak', 'espeak_dll'):
                # Map 0-100 to 0-200 for eSpeak
                self.espeak_volume = int((volume / 100.0) * 200)
                self.espeak_volume = max(0, min(200, self.espeak_volume))
                # Sync to DLL instance
                if self.espeak_dll:
                    self.espeak_dll.set_volume(volume)
            elif self.engine in ('say', 'spd'):
                # Native engines use 0-100 directly
                pass  # Volume controlled at system level
            else:
                # Delegate to TitanTTS engine via registry
                registry = _get_engine_registry()
                if registry:
                    tts_engine = registry.get_titantts_engine(self.engine)
                    if tts_engine and hasattr(tts_engine, 'set_volume'):
                        tts_engine.set_volume(max(0, min(100, volume)))
        except Exception as e:
            print(f"[StereoSpeech] Error setting volume: {e}")

    def set_pitch(self, pitch):
        """
        Sets voice pitch.

        Args:
            pitch (int): Pitch from -10 to 10
        """
        try:
            if self.engine in ('espeak', 'espeak_dll'):
                # Map -10..10 to 0..99
                self.espeak_pitch = int(50 + (pitch * 5))
                self.espeak_pitch = max(0, min(99, self.espeak_pitch))
                # Sync to DLL instance
                if self.espeak_dll:
                    self.espeak_dll.set_pitch(pitch)
        except Exception as e:
            print(f"[StereoSpeech] Error setting pitch: {e}")

    def _get_espeak_voices_from_dll(self):
        """Get eSpeak voices using DLL API (espeak_ListVoices)."""
        if not self.espeak_dll:
            return []
        try:
            raw_voices = self.espeak_dll.list_voices()
            if not raw_voices:
                return []

            voices = []
            for v in raw_voices:
                voice_id = v.get('language') or v.get('id', '')
                if not voice_id:
                    continue
                display_name = v.get('display_name', voice_id)
                voices.append({
                    'id': voice_id,
                    'display_name': display_name
                })
            return voices
        except Exception as e:
            print(f"[StereoSpeech] DLL voice enumeration error: {e}")
            return []

    def _get_espeak_voices_from_exe(self):
        """Get eSpeak voices using executable (espeak-ng --voices)."""
        if not ESPEAK_AVAILABLE or not ESPEAK_PATH:
            return []
        try:
            cmd = [ESPEAK_PATH]
            if ESPEAK_DATA_PATH:
                cmd.extend(['--path', ESPEAK_DATA_PATH])
            cmd.append('--voices')

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                timeout=5
            )

            if result.returncode != 0:
                return []

            voices = []
            for line in result.stdout.strip().split('\n')[1:]:  # Skip header
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 4:
                    language_code = parts[1]
                    age_gender = parts[2]
                    voice_name = parts[3]

                    gender = 'M'
                    if '/' in age_gender:
                        gender = age_gender.split('/')[-1]

                    display_name = voice_name.replace('_', ' ').replace('-', ' ').title()
                    gender_str = {'M': 'Male', 'F': 'Female'}.get(gender, gender)
                    full_display = f"{display_name} ({gender_str})"

                    voices.append({
                        'id': language_code,
                        'display_name': full_display
                    })
            return voices
        except Exception as e:
            print(f"[StereoSpeech] Exe voice enumeration error: {e}")
            return []

    def _add_espeak_voice_variants(self, voices):
        """Add voice variants (m1-m7, f1-f4) for popular languages."""
        LANGUAGES_WITH_VARIANTS = ['en', 'pl', 'de', 'fr', 'es', 'it', 'pt', 'ru', 'cs']

        base_voices = {}
        for voice in voices:
            lang_code = voice['id'].split('-')[0]
            if lang_code not in base_voices:
                base_voices[lang_code] = voice

        variant_voices = []
        for lang_code, base_voice in base_voices.items():
            if lang_code in LANGUAGES_WITH_VARIANTS:
                base_name = base_voice['display_name'].split('(')[0].strip()
                # Male variants m1-m7
                for i in range(1, 8):
                    variant_voices.append({
                        'id': f"{lang_code}+m{i}",
                        'display_name': f"{base_name} (m{i}, Male variant {i})"
                    })
                # Female variants f1-f4
                for i in range(1, 5):
                    variant_voices.append({
                        'id': f"{lang_code}+f{i}",
                        'display_name': f"{base_name} (f{i}, Female variant {i})"
                    })
        return variant_voices

    def get_espeak_voices(self):
        """
        Get available eSpeak voices. Tries DLL first, falls back to executable.

        Returns:
            list: List of voice dicts with 'id' and 'display_name'
        """
        try:
            if not ESPEAK_AVAILABLE and not ESPEAK_DLL_AVAILABLE:
                return []

            # Try DLL voice enumeration first (fastest, no subprocess)
            voices = self._get_espeak_voices_from_dll()

            # Fall back to executable if DLL didn't work
            if not voices:
                voices = self._get_espeak_voices_from_exe()

            if not voices:
                return []

            # Add variants for popular languages
            variant_voices = self._add_espeak_voice_variants(voices)
            all_voices = voices + variant_voices
            all_voices.sort(key=lambda v: v['display_name'])
            return all_voices

        except Exception as e:
            print(f"[StereoSpeech] Error getting eSpeak voices: {e}")
            return []

    def get_say_voices(self):
        """
        Get available macOS 'say' voices.

        Returns:
            list: List of voice dicts with 'id' and 'display_name'
        """
        if not SAY_AVAILABLE:
            return []
        try:
            result = subprocess.run(
                ['say', '-v', '?'],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                timeout=5
            )
            if result.returncode != 0:
                return []

            voices = []
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                # Format: "VoiceName  lang_CODE  # description"
                # VoiceName can contain spaces, so split on multiple spaces
                parts = line.split('#', 1)
                voice_part = parts[0].strip()
                # Split voice name from language code
                tokens = voice_part.split()
                if len(tokens) >= 2:
                    lang_code = tokens[-1]
                    voice_name = ' '.join(tokens[:-1])
                    voices.append({
                        'id': voice_name,
                        'display_name': f"{voice_name} ({lang_code})"
                    })
            return voices
        except Exception as e:
            print(f"[StereoSpeech] Error getting macOS voices: {e}")
            return []

    def get_spd_voices(self):
        """
        Get available Linux speech-dispatcher voices.

        Returns:
            list: List of voice dicts with 'id' and 'display_name'
        """
        if not SPD_AVAILABLE:
            return []
        try:
            result = subprocess.run(
                [SPD_PATH, '-L'],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                timeout=5
            )
            if result.returncode != 0:
                return []

            voices = []
            for line in result.stdout.strip().split('\n'):
                line = line.strip()
                if not line:
                    continue
                # Format varies: "VOICE_NAME  LANGUAGE" or just "VOICE_NAME"
                parts = line.split()
                if parts:
                    voice_name = parts[0]
                    lang = parts[1] if len(parts) > 1 else ''
                    display = f"{voice_name} ({lang})" if lang else voice_name
                    voices.append({
                        'id': voice_name,
                        'display_name': display
                    })
            return voices
        except Exception as e:
            print(f"[StereoSpeech] Error getting spd-say voices: {e}")
            return []

    def _get_all_sapi_voices(self):
        """Get ALL SAPI5 voices including 32-bit voices on 64-bit Windows.

        Uses SpObjectTokenCategory to enumerate voices from both:
        - HKLM\\SOFTWARE\\Microsoft\\Speech\\Voices (native bitness)
        - HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\Speech\\Voices (32-bit on 64-bit)

        Returns:
            list: List of dicts with 'token', 'name', 'id', and optional 'is_32bit'
        """
        voices = []
        seen_ids = set()

        # Native voices (already returned by GetVoices)
        try:
            tokens = self.sapi.GetVoices()
            for i in range(tokens.Count):
                token = tokens.Item(i)
                voice_id = token.Id
                voices.append({'token': token, 'name': token.GetDescription(), 'id': voice_id})
                seen_ids.add(voice_id)
        except Exception as e:
            print(f"[StereoSpeech] Error enumerating native SAPI voices: {e}")

        # 32-bit voices via registry (WOW6432Node) - only on 64-bit Python
        if sys.maxsize > 2**32:
            try:
                import winreg
                wow_path = r"SOFTWARE\WOW6432Node\Microsoft\Speech\Voices\Tokens"
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, wow_path) as key:
                    i = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            token_path = f"HKEY_LOCAL_MACHINE\\{wow_path}\\{subkey_name}"

                            # Create SpObjectToken pointing to WOW6432Node voice
                            token = win32com.client.Dispatch("SAPI.SpObjectToken")
                            token.SetId(token_path)
                            voice_id = token.Id

                            if voice_id not in seen_ids:
                                name = token.GetDescription()
                                voices.append({'token': token, 'name': name, 'id': voice_id, 'is_32bit': True})
                                seen_ids.add(voice_id)
                            i += 1
                        except OSError:
                            break
            except Exception as e:
                print(f"[StereoSpeech] Note: Could not enumerate 32-bit voices: {e}")

        # Cache for set_voice()
        self._sapi_voice_cache = voices
        return voices

    def get_available_voices(self):
        """
        Returns list of available voices for the current engine.

        Returns:
            list: Voice names (SAPI5/say/spd) or voice dicts (eSpeak)
        """
        try:
            if self.engine == 'sapi5' and self.sapi:
                all_voices = self._get_all_sapi_voices()
                result = []
                for v in all_voices:
                    name = v['name']
                    if v.get('is_32bit'):
                        name += " (32-bit)"
                    result.append(name)
                return result
            elif self.engine in ('espeak', 'espeak_dll'):
                return self.get_espeak_voices()
            elif self.engine == 'say':
                return self.get_say_voices()
            elif self.engine == 'spd':
                return self.get_spd_voices()
            else:
                # Delegate to TitanTTS engine via registry
                registry = _get_engine_registry()
                if registry:
                    tts_engine = registry.get_titantts_engine(self.engine)
                    if tts_engine:
                        return tts_engine.get_voices()
                return []
        except Exception as e:
            print(f"[StereoSpeech] Error getting voices: {e}")
            return []

    def set_voice(self, voice_index):
        """
        Sets voice for the current engine.

        Args:
            voice_index (int): Voice index from the available voices list
        """
        try:
            if self.engine == 'sapi5' and self.sapi:
                # Use cached voice list from _get_all_sapi_voices (includes 32-bit)
                voices = getattr(self, '_sapi_voice_cache', None)
                if not voices:
                    voices = self._get_all_sapi_voices()
                if 0 <= voice_index < len(voices):
                    voice_entry = voices[voice_index]
                    self.sapi.Voice = voice_entry['token']
                    self.current_voice = self.sapi.Voice
                    # Sync voice to worker thread by token ID
                    if self._sapi_worker:
                        self._sapi_worker.set_voice(voice_entry['id'])
                    print(f"[StereoSpeech] SAPI5 voice set to: {voice_entry['name']}")
            elif self.engine in ('espeak', 'espeak_dll'):
                voices = self.get_espeak_voices()
                if 0 <= voice_index < len(voices):
                    voice_info = voices[voice_index]
                    self.espeak_voice = voice_info['id']
                    # Sync to DLL instance
                    if self.espeak_dll:
                        self.espeak_dll.set_voice(voice_info['id'])
                    print(f"[StereoSpeech] eSpeak voice set to: {voice_info['display_name']}")
            elif self.engine == 'say':
                voices = self.get_say_voices()
                if 0 <= voice_index < len(voices):
                    self.say_voice = voices[voice_index]['id']
                    print(f"[StereoSpeech] macOS voice set to: {voices[voice_index]['display_name']}")
            elif self.engine == 'spd':
                voices = self.get_spd_voices()
                if 0 <= voice_index < len(voices):
                    self.spd_voice = voices[voice_index]['id']
                    print(f"[StereoSpeech] spd-say voice set to: {voices[voice_index]['display_name']}")
            else:
                # Delegate to TitanTTS engine via registry
                registry = _get_engine_registry()
                if registry:
                    tts_engine = registry.get_titantts_engine(self.engine)
                    if tts_engine:
                        voices = tts_engine.get_voices()
                        if 0 <= voice_index < len(voices):
                            tts_engine.set_voice(voices[voice_index]['id'])
                            print(f"[StereoSpeech] {tts_engine.engine_name} voice set to: {voices[voice_index]['display_name']}")
        except Exception as e:
            print(f"[StereoSpeech] Error setting voice: {e}")


# Globalna instancja dla łatwego użycia
_stereo_speech_instance = None

def get_stereo_speech():
    """Zwraca globalną instancję StereoSpeech bezpiecznie."""
    global _stereo_speech_instance
    try:
        if _stereo_speech_instance is None:
            _stereo_speech_instance = StereoSpeech()
        return _stereo_speech_instance
    except Exception as e:
        print(f"Error getting stereo speech instance: {e}")
        return None

def speak_stereo(text, position=0.0, pitch_offset=0, async_mode=False):
    """
    Funkcja pomocnicza do szybkiego użycia stereo speech.

    ZAWSZE odcina ciszę na początku i końcu audio (jak NVDA).
    Stereo positioning wymaga włączonego ustawienia 'stereo_speech'.

    Args:
        text (str): Tekst do wypowiedzenia
        position (float): Pozycja stereo od -1.0 (lewo) do 1.0 (prawo) - wymaga włączonego stereo_speech
        pitch_offset (int): Przesunięcie wysokości głosu -10 do +10
        async_mode (bool): Czy mówić asynchronicznie
    """
    stereo_speech = get_stereo_speech()
    
    if async_mode:
        stereo_speech.speak_async(text, position, pitch_offset)
    else:
        stereo_speech.speak(text, position, pitch_offset)

def stop_stereo_speech():
    """Zatrzymuje aktualną stereo mowę."""
    stereo_speech = get_stereo_speech()
    stereo_speech.stop()


# Przykłady użycia
if __name__ == "__main__":
    # Test stereo speech
    stereo = StereoSpeech()
    
    print("Test stereo speech:")
    print("Lewy kanał...")
    stereo.speak("To jest test lewego kanału", position=-1.0, pitch_offset=-3)
    
    time.sleep(1)
    
    print("Środek...")
    stereo.speak("To jest test środka", position=0.0, pitch_offset=0)
    
    time.sleep(1)
    
    print("Prawy kanał...")
    stereo.speak("To jest test prawego kanału", position=1.0, pitch_offset=3)
    
    print("Test zakończony.")