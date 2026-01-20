import math
import threading
import time
import tempfile
import os
import sys
import io
import subprocess
import platform
import accessible_output3.outputs.auto
from src.settings.settings import get_setting


def _get_base_path():
    """Get base path for resources, supporting PyInstaller and Nuitka."""
    # For both PyInstaller and Nuitka, use executable directory
    # (data directories are placed next to exe for backward compatibility)
    if hasattr(sys, '_MEIPASS') or getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        # Development mode - get project root (2 levels up from src/titan_core/)
        return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


# Platform detection
IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX = platform.system() == 'Linux'
IS_MACOS = platform.system() == 'Darwin'

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

# eSpeak DLL constants (from speak_lib.h)
import ctypes
from ctypes import c_int, c_uint, c_void_p, c_char_p, POINTER, Structure, CFUNCTYPE, c_short

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
        self._load_dll()

    def _load_dll(self):
        """Find and load the eSpeak NG DLL"""
        try:
            proj_root = _get_base_path()
            bundled_dir = os.path.join(proj_root, 'data', 'screen reader engines', 'espeak')

            dll_paths = [
                os.path.join(bundled_dir, 'libespeak-ng.dll'),
                os.path.join(bundled_dir, 'espeak-ng.dll'),
                'libespeak-ng.dll',
                'espeak-ng.dll',
            ]

            data_paths = [
                os.path.join(bundled_dir, 'espeak-ng-data'),
                bundled_dir,
            ]

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
                        try:
                            os.add_dll_directory(dll_dir)
                        except Exception:
                            pass
                        current_path = os.environ.get('PATH', '')
                        if dll_dir not in current_path:
                            os.environ['PATH'] = dll_dir + os.pathsep + current_path

                    self.dll = ctypes.CDLL(dll_path)
                    print(f"[eSpeak DLL] Loaded: {dll_path}")
                    self._setup_functions()
                    self._initialize()
                    return
                except Exception as e:
                    continue

            print("[eSpeak DLL] Could not load eSpeak NG DLL")
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
            self.dll.espeak_SetSynthCallback.argtypes = [t_espeak_callback]
            self.dll.espeak_SetSynthCallback.restype = None
            self.dll.espeak_Synchronize.argtypes = []
            self.dll.espeak_Synchronize.restype = c_int
        except Exception as e:
            print(f"[eSpeak DLL] Error setting up functions: {e}")

    def _initialize(self):
        """Initialize eSpeak engine"""
        if not self.dll:
            return False
        try:
            data_path_bytes = self.data_path.encode('utf-8') if self.data_path else None
            sample_rate = self.dll.espeak_Initialize(AUDIO_OUTPUT_PLAYBACK, 0, data_path_bytes, 0)
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
        if not self.initialized:
            return False
        try:
            with self._lock:
                if interrupt:
                    self.cancel()
                text_bytes = text.encode('utf-8')
                text_buffer = ctypes.create_string_buffer(text_bytes)
                result = self.dll.espeak_Synth(text_buffer, len(text_bytes) + 1, 0, 0, 0, espeakCHARS_UTF8, None, None)
                return result == 0
        except Exception as e:
            print(f"[eSpeak DLL] Speak error: {e}")
            return False

    def cancel(self):
        if self.initialized:
            try:
                self.dll.espeak_Cancel()
            except Exception:
                pass

    def is_playing(self):
        if not self.initialized:
            return False
        try:
            return self.dll.espeak_IsPlaying() != 0
        except Exception:
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

    def synthesize_to_memory(self, text, pitch_offset=0):
        """
        Synthesize text to memory buffer (WAV format) using eSpeak DLL callback.
        This is faster than subprocess and allows stereo positioning.

        Args:
            text (str): Text to synthesize
            pitch_offset (int): Pitch offset -10 to +10

        Returns:
            AudioSegment or None: Audio data in pydub format
        """
        if not self.initialized or not PYDUB_AVAILABLE:
            return None

        try:
            with self._lock:
                # Clear audio buffer
                self.audio_buffer = []

                # Create callback function that collects audio samples
                def audio_callback(wav, numsamples, events):
                    if numsamples > 0 and wav:
                        # Copy audio samples to buffer
                        samples = []
                        for i in range(numsamples):
                            samples.append(wav[i])
                        self.audio_buffer.extend(samples)
                    return 0  # Continue synthesis

                # Keep reference to callback to prevent garbage collection
                self.callback_fn = t_espeak_callback(audio_callback)

                # Set synthesis callback
                self.dll.espeak_SetSynthCallback(self.callback_fn)

                # Set pitch with offset
                original_pitch = self.pitch
                adjusted_pitch = int(50 + ((self.pitch - 50 + pitch_offset * 5)))
                adjusted_pitch = max(0, min(99, adjusted_pitch))
                self._set_parameter(espeakPITCH, adjusted_pitch)

                # Synthesize text
                text_bytes = text.encode('utf-8')
                text_buffer = ctypes.create_string_buffer(text_bytes)
                result = self.dll.espeak_Synth(text_buffer, len(text_bytes) + 1, 0, 0, 0, espeakCHARS_UTF8, None, None)

                # Wait for synthesis to complete
                self.dll.espeak_Synchronize()

                # Restore original pitch
                self._set_parameter(espeakPITCH, original_pitch)

                # Clear callback
                self.dll.espeak_SetSynthCallback(None)
                self.callback_fn = None

                if result != 0 or not self.audio_buffer:
                    print("[eSpeak DLL] Synthesis failed or no audio generated")
                    return None

                # Convert samples to bytes (16-bit signed PCM)
                import struct
                audio_bytes = struct.pack(f'{len(self.audio_buffer)}h', *self.audio_buffer)

                # Create WAV file in memory
                wav_buffer = io.BytesIO()

                # Write WAV header
                import wave
                with wave.open(wav_buffer, 'wb') as wav_file:
                    wav_file.setnchannels(1)  # Mono
                    wav_file.setsampwidth(2)  # 16-bit
                    wav_file.setframerate(self.sample_rate)
                    wav_file.writeframes(audio_bytes)

                # Load as AudioSegment
                wav_buffer.seek(0)
                audio = AudioSegment.from_wav(wav_buffer)
                print(f"[eSpeak DLL] Synthesized to memory: {len(audio)}ms, {len(self.audio_buffer)} samples")

                return audio

        except Exception as e:
            print(f"[eSpeak DLL] Error in synthesize_to_memory: {e}")
            import traceback
            traceback.print_exc()
            # Clean up
            try:
                if self.dll and self.callback_fn:
                    self.dll.espeak_SetSynthCallback(None)
                self.callback_fn = None
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

# First, try to find bundled eSpeak in data/screen reader engines/espeak/
bundled_espeak_dir = os.path.join(project_root, 'data', 'screen reader engines', 'espeak')
bundled_espeak_exe = os.path.join(bundled_espeak_dir, 'espeak-ng.exe')
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
        self.default_rate = 0
        self.default_volume = 100
        self.default_pitch = 0
        self.is_speaking = False
        self.speech_lock = threading.Lock()
        self.current_tts_channel = None  # Aktualny kanał TTS

        # Speech engine selection - prefer eSpeak DLL for fast speech like NVDA
        if ESPEAK_DLL_AVAILABLE:
            self.engine = 'espeak_dll'  # Fastest - uses DLL directly like NVDA
        elif ESPEAK_AVAILABLE:
            self.engine = 'espeak'  # Subprocess fallback
        else:
            self.engine = 'sapi5'  # SAPI5 fallback

        # eSpeak DLL instance
        self.espeak_dll = None
        if ESPEAK_DLL_AVAILABLE:
            try:
                self.espeak_dll = get_espeak_dll()
                print("[StereoSpeech] eSpeak DLL initialized (fast mode)")
            except Exception as e:
                print(f"[StereoSpeech] Error initializing eSpeak DLL: {e}")

        # eSpeak parameters
        self.espeak_rate = 175  # Words per minute (default)
        self.espeak_pitch = 50  # Pitch 0-99 (default: 50)
        self.espeak_volume = 100  # Volume 0-200 (default: 100)
        self.espeak_voice = None  # Voice identifier

        # Fallback dla przypadków gdy SAPI5 nie jest dostępne
        self.fallback_speaker = accessible_output3.outputs.auto.Auto()

        try:
            self._init_sapi()
        except Exception as e:
            print(f"Błąd inicjalizacji SAPI5: {e}")
            self.sapi = None
    
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
            print(f"Błąd inicjalizacji SAPI5: {e}")
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
        Generate TTS using bundled eSpeak executable (optimized, faster than standard subprocess)

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

            # Calculate pitch
            if hasattr(self, 'espeak_pitch'):
                pitch = self.espeak_pitch + (pitch_offset * 5)
            else:
                pitch = 50 + (pitch_offset * 5)
            pitch = max(0, min(99, pitch))

            # Add parameters (optimized for speed - minimal flags)
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

            # Run with minimal overhead
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=3,  # Shorter timeout for responsiveness
                    check=False
                )

                if result.returncode != 0 or not result.stdout or len(result.stdout) < 100:
                    return None

                # Load directly from bytes
                audio = AudioSegment.from_wav(io.BytesIO(result.stdout))
                print(f"[StereoSpeech] eSpeak fast: {len(audio)}ms")
                return audio

            except subprocess.TimeoutExpired:
                print("[StereoSpeech] eSpeak timeout")
                return None
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

            # Run eSpeak with piped output
            process = None
            try:
                process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    encoding=None  # Binary mode for stdout
                )

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
            print(f"Błąd podczas generowania TTS do pliku: {e}")
            import traceback
            traceback.print_exc()
            # Usuń plik tymczasowy w przypadku błędu
            if 'temp_path' in locals() and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass
            return None

    def speak(self, text, position=0.0, pitch_offset=0, use_fallback=True):
        """
        Wypowiada tekst z pozycjonowaniem stereo i kontrolą wysokości.

        ZAWSZE odcina ciszę na początku i końcu audio (jak NVDA), niezależnie od ustawień.
        Stereo positioning jest opcjonalny i kontrolowany przez ustawienie 'stereo_speech'.

        Args:
            text (str): Tekst do wypowiedzenia
            position (float): Pozycja stereo od -1.0 (lewo) do 1.0 (prawo) - wymaga włączonego stereo_speech
            pitch_offset (int): Przesunięcie wysokości głosu -10 do +10
            use_fallback (bool): Czy użyć fallback jeśli SAPI5 nie działa
        """
        if not text:
            return

        # Add timeout protection for the lock to prevent hangs
        lock_acquired = False
        try:
            # Try to acquire lock with timeout
            lock_acquired = self.speech_lock.acquire(timeout=2.0)
            if not lock_acquired:
                print("Warning: Could not acquire speech lock, using fallback")
                if use_fallback:
                    self.fallback_speaker.speak(text)
                return

            # Zatrzymaj poprzednią mowę przed rozpoczęciem nowej
            self.stop()

            self.is_speaking = True

            try:
                # eSpeak DLL - fast direct speech (like NVDA) when no stereo needed
                if self.engine == 'espeak_dll' and self.espeak_dll:
                    # For simple speech without stereo positioning, use DLL directly
                    # This is the fastest method - no file I/O, no pydub processing
                    if position == 0.0 or not self.is_stereo_enabled():
                        try:
                            self.espeak_dll.speak(text, interrupt=True)
                            # Don't wait for speech to finish - async like NVDA
                            return
                        except Exception as e:
                            print(f"[StereoSpeech] eSpeak DLL error: {e}")
                            # Fall through to other methods

                # Check if pydub is available for audio processing
                if not PYDUB_AVAILABLE:
                    # No pydub - try eSpeak DLL direct if available
                    if self.engine == 'espeak_dll' and self.espeak_dll:
                        self.espeak_dll.speak(text, interrupt=True)
                        return
                    # Otherwise use fallback
                    if use_fallback:
                        self.fallback_speaker.speak(text)
                    return

                # Generate TTS audio based on selected engine
                audio = None
                temp_file = None

                if self.engine == 'espeak_dll':
                    # eSpeak DLL with stereo positioning needed
                    # Use DLL callback to generate WAV in memory (FASTEST - no subprocess, no file I/O!)
                    if position != 0.0:
                        # Try DLL callback-based synthesis first (fastest method)
                        try:
                            if self.espeak_dll:
                                audio = self.espeak_dll.synthesize_to_memory(text, pitch_offset)
                            else:
                                audio = None

                            # Fallback to subprocess espeak if DLL method fails
                            if not audio and ESPEAK_AVAILABLE:
                                print("[StereoSpeech] DLL synthesis failed, falling back to subprocess espeak")
                                audio = self._generate_espeak_to_memory(text, pitch_offset)

                            if not audio:
                                # Final fallback: DLL direct speech (no stereo)
                                if self.espeak_dll:
                                    self.espeak_dll.speak(text, interrupt=True)
                                elif use_fallback:
                                    self.fallback_speaker.speak(text)
                                return
                        except Exception as e:
                            print(f"[StereoSpeech] eSpeak DLL synthesis error: {e}")
                            # Fallback to DLL direct speech
                            if self.espeak_dll:
                                try:
                                    self.espeak_dll.speak(text, interrupt=True)
                                except Exception:
                                    if use_fallback:
                                        self.fallback_speaker.speak(text)
                            elif use_fallback:
                                self.fallback_speaker.speak(text)
                            return
                    else:
                        # No stereo needed, use DLL directly (already handled above at line 766-777)
                        # This path shouldn't be reached, but add safety
                        if self.espeak_dll:
                            try:
                                self.espeak_dll.speak(text, interrupt=True)
                            except Exception as e:
                                print(f"[StereoSpeech] eSpeak DLL error: {e}")
                                if use_fallback:
                                    self.fallback_speaker.speak(text)
                        elif use_fallback:
                            self.fallback_speaker.speak(text)
                        return
                elif self.engine == 'espeak' and ESPEAK_AVAILABLE:
                    # eSpeak: use fast in-memory generation (no file I/O)
                    audio = self._generate_espeak_to_memory(text, pitch_offset)
                    if not audio:
                        # Fallback if memory generation fails
                        if use_fallback:
                            self.fallback_speaker.speak(text)
                        return
                elif self.engine == 'sapi5' and self.sapi:
                    # SAPI5: use file-based generation (required by SAPI)
                    temp_file = self._generate_tts_to_file(text, pitch_offset)
                    if not temp_file:
                        if use_fallback:
                            self.fallback_speaker.speak(text)
                        return
                    # Load audio from file
                    audio = AudioSegment.from_wav(temp_file)
                else:
                    # Engine not available, use fallback
                    if use_fallback:
                        self.fallback_speaker.speak(text)
                    return

                try:
                    # Odetnij ciszę na początku i końcu (improves responsiveness)
                    # SAPI5 often adds 100ms+ of leading silence
                    # Optimized: no reverse, larger chunks (50ms), skips short audio
                    try:
                        silence_threshold = self.get_silence_threshold()
                        audio = trim_silence(audio, silence_threshold=silence_threshold)
                        print(f"TTS audio trimmed successfully (engine: {self.engine}, threshold: {silence_threshold} dB)")
                    except Exception as e:
                        print(f"Warning: Could not trim silence: {e}")
                        # Continue with original audio if trimming fails

                    # Zastosuj pozycjonowanie stereo używając pydub (opcjonalnie)
                    # Stereo positioning można wyłączyć w ustawieniach, ale trimming zawsze działa
                    if position != 0.0 and self.is_stereo_enabled():
                        # Pozycja od -1.0 (lewo) do 1.0 (prawo)
                        # pydub.pan() przyjmuje wartości od -1.0 do 1.0
                        panned_audio = audio.pan(position)
                    else:
                        panned_audio = audio

                    # Eksportuj przetworzone audio do pamięci (bez pliku tymczasowego)
                    try:
                        audio_buffer = io.BytesIO()
                        panned_audio.export(audio_buffer, format="wav")
                        audio_buffer.seek(0)  # Przewiń na początek
                    except Exception as e:
                        print(f"[StereoSpeech] Error exporting audio to buffer: {e}")
                        if use_fallback:
                            self.fallback_speaker.speak(text)
                        return

                    # Użyj drugi kanał pygame dla TTS (responsywny)
                    try:
                        import pygame

                        # Sprawdź czy główny mixer jest zainicjalizowany
                        if not pygame.mixer.get_init():
                            try:
                                pygame.mixer.pre_init(frequency=22050, size=-16, channels=2, buffer=1024)
                                pygame.mixer.init()
                            except Exception as e:
                                print(f"[StereoSpeech] Error initializing pygame mixer: {e}")
                                if use_fallback:
                                    self.fallback_speaker.speak(text)
                                return

                        # Znajdź wolny kanał dla TTS (nie channel 0 używany przez UI)
                        tts_channel = None
                        try:
                            for channel_id in range(1, pygame.mixer.get_num_channels()):  # Pomiń kanał 0
                                channel = pygame.mixer.Channel(channel_id)
                                if not channel.get_busy():
                                    tts_channel = channel
                                    break

                            if not tts_channel:
                                # Jeśli wszystkie kanały zajęte, zwiększ liczbę kanałów
                                pygame.mixer.set_num_channels(pygame.mixer.get_num_channels() + 1)
                                tts_channel = pygame.mixer.Channel(pygame.mixer.get_num_channels() - 1)
                        except Exception as e:
                            print(f"[StereoSpeech] Error finding TTS channel: {e}")
                            if use_fallback:
                                self.fallback_speaker.speak(text)
                            return

                        # Odtwórz TTS w dedykowanym kanale bezpośrednio z pamięci
                        try:
                            sound = pygame.mixer.Sound(audio_buffer)
                            tts_channel.play(sound)

                            # Zapamiętaj aktualny kanał TTS
                            self.current_tts_channel = tts_channel

                            # Poczekaj na zakończenie TTS (responsywnie)
                            while tts_channel.get_busy():
                                time.sleep(0.05)  # Krótkie sprawdzanie co 50ms

                            # Wyczyść kanał po zakończeniu
                            self.current_tts_channel = None
                        except Exception as e:
                            print(f"[StereoSpeech] Error playing sound: {e}")
                            if use_fallback:
                                self.fallback_speaker.speak(text)
                            return

                    except ImportError:
                        print("[StereoSpeech] pygame not available")
                        if use_fallback:
                            self.fallback_speaker.speak(text)
                        return
                    except Exception as e:
                        print(f"[StereoSpeech] pygame error: {e}")
                        if use_fallback:
                            self.fallback_speaker.speak(text)
                        return
                    
                finally:
                    # Usuń plik tymczasowy (tylko dla SAPI5, eSpeak nie tworzy pliku)
                    if temp_file:
                        try:
                            os.unlink(temp_file)
                        except:
                            pass
                
            except Exception as e:
                print(f"Błąd podczas mówienia stereo: {e}")
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
        
        Args:
            text (str): Tekst do wypowiedzenia
            position (float): Pozycja stereo od -1.0 (lewo) do 1.0 (prawo)
            pitch_offset (int): Przesunięcie wysokości głosu -10 do +10
            use_fallback (bool): Czy użyć fallback jeśli SAPI5 nie działa
        """
        def speak_thread():
            # Wywołaj synchroniczną metodę speak w osobnym wątku
            self.speak(text, position, pitch_offset, use_fallback)
        
        thread = threading.Thread(target=speak_thread)
        thread.daemon = True
        thread.start()
    
    def stop(self):
        """Zatrzymuje aktualną mowę TTS bezpiecznie."""
        try:
            # Set flag to stop speech
            self.is_speaking = False

            # Stop eSpeak DLL if it's speaking
            if hasattr(self, 'espeak_dll') and self.espeak_dll:
                try:
                    if self.espeak_dll.is_playing():
                        self.espeak_dll.cancel()
                except Exception as e:
                    print(f"[StereoSpeech] Error stopping eSpeak DLL: {e}")

            # Stop current TTS channel (not entire mixer!)
            if hasattr(self, 'current_tts_channel') and self.current_tts_channel:
                try:
                    if self.current_tts_channel.get_busy():
                        self.current_tts_channel.stop()
                except (AttributeError, Exception) as e:
                    print(f"[StereoSpeech] Error stopping TTS channel: {e}")
                finally:
                    self.current_tts_channel = None

            # Stop SAPI if it's speaking
            if hasattr(self, 'sapi') and self.sapi:
                try:
                    # SAPI doesn't have a direct stop method, but we can speak empty text
                    self.sapi.Speak("", 1)  # 1 = asynchronous, empty string stops current speech
                except (AttributeError, OSError) as e:
                    print(f"[StereoSpeech] Error stopping SAPI speech: {e}")

        except Exception as e:
            print(f"[StereoSpeech] Błąd podczas zatrzymywania mowy TTS: {e}")
    
    def set_engine(self, engine):
        """
        Sets the TTS engine.

        Args:
            engine (str): Engine type ('sapi5' or 'espeak')
        """
        if engine == 'espeak' and ESPEAK_AVAILABLE:
            self.engine = 'espeak'
            print("[StereoSpeech] Switched to eSpeak engine")
        elif engine == 'sapi5' and self.sapi:
            self.engine = 'sapi5'
            print("[StereoSpeech] Switched to SAPI5 engine")
        else:
            print(f"[StereoSpeech] Engine {engine} not available")

    def get_engine(self):
        """
        Returns current TTS engine.

        Returns:
            str: Current engine ('sapi5' or 'espeak')
        """
        return self.engine

    def get_available_engines(self):
        """
        Returns list of available TTS engines.

        Returns:
            list: List of available engines
        """
        engines = []
        if self.sapi:
            engines.append('sapi5')
        if ESPEAK_AVAILABLE:
            engines.append('espeak')
        return engines

    def set_rate(self, rate):
        """
        Ustawia szybkość mówienia.

        Args:
            rate (int): Szybkość od -10 do +10
        """
        try:
            if self.engine == 'sapi5' and self.sapi:
                self.sapi.Rate = max(-10, min(10, rate))
            elif self.engine == 'espeak':
                # Map -10..10 to 80..450 wpm
                self.espeak_rate = int(175 + (rate * 27.5))
                self.espeak_rate = max(80, min(450, self.espeak_rate))
        except Exception as e:
            print(f"Błąd ustawiania szybkości mowy: {e}")

    def set_volume(self, volume):
        """
        Ustawia głośność mowy.

        Args:
            volume (int): Głośność od 0 do 100
        """
        try:
            if self.engine == 'sapi5' and self.sapi:
                self.sapi.Volume = max(0, min(100, volume))
                self.default_volume = self.sapi.Volume
            elif self.engine == 'espeak':
                # Map 0-100 to 0-200 for eSpeak
                self.espeak_volume = int((volume / 100.0) * 200)
                self.espeak_volume = max(0, min(200, self.espeak_volume))
        except Exception as e:
            print(f"Błąd ustawiania głośności mowy: {e}")

    def set_pitch(self, pitch):
        """
        Sets voice pitch (eSpeak only).

        Args:
            pitch (int): Pitch from -10 to 10
        """
        if self.engine == 'espeak':
            # Map -10..10 to 0..99
            self.espeak_pitch = int(50 + (pitch * 5))
            self.espeak_pitch = max(0, min(99, self.espeak_pitch))

    def get_espeak_voices(self):
        """
        Get available eSpeak voices.

        Returns:
            list: List of voice dicts with 'id' and 'display_name'
        """
        try:
            if not ESPEAK_AVAILABLE:
                return []

            # Build command
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

            if result.returncode == 0:
                voices = []

                # Parse eSpeak voice list
                for line in result.stdout.strip().split('\n')[1:]:  # Skip header
                    if not line.strip():
                        continue

                    parts = line.split()
                    if len(parts) >= 4:
                        language_code = parts[1]
                        age_gender = parts[2]
                        voice_name = parts[3]

                        # Extract gender
                        gender = 'M'
                        if '/' in age_gender:
                            gender = age_gender.split('/')[-1]

                        # Create display name
                        display_name = voice_name.replace('_', ' ').replace('-', ' ').title()
                        gender_str = {'M': 'Male', 'F': 'Female'}.get(gender, gender)
                        full_display = f"{display_name} ({gender_str})"

                        voices.append({
                            'id': language_code,
                            'display_name': full_display
                        })

                # Add voice variants for popular languages
                LANGUAGES_WITH_VARIANTS = ['en', 'pl', 'de', 'fr', 'es', 'it', 'pt', 'ru', 'cs']

                base_voices = {}
                for voice in voices:
                    lang_code = voice['id'].split('-')[0]
                    if lang_code not in base_voices:
                        base_voices[lang_code] = voice

                # Add variants
                variant_voices = []
                for lang_code, base_voice in base_voices.items():
                    if lang_code in LANGUAGES_WITH_VARIANTS:
                        # Male variants m1-m7
                        for i in range(1, 8):
                            variant_voices.append({
                                'id': f"{lang_code}+m{i}",
                                'display_name': f"{base_voice['display_name'].split('(')[0].strip()} (m{i}, Male variant {i})"
                            })

                        # Female variants f1-f4
                        for i in range(1, 5):
                            variant_voices.append({
                                'id': f"{lang_code}+f{i}",
                                'display_name': f"{base_voice['display_name'].split('(')[0].strip()} (f{i}, Female variant {i})"
                            })

                all_voices = voices + variant_voices
                all_voices.sort(key=lambda v: v['display_name'])

                return all_voices

            return []

        except Exception as e:
            print(f"[StereoSpeech] Error getting eSpeak voices: {e}")
            return []

    def get_available_voices(self):
        """
        Zwraca listę dostępnych głosów dla aktualnego silnika.

        Returns:
            list: Lista nazw dostępnych głosów (dla SAPI5) lub lista dict (dla eSpeak)
        """
        try:
            if self.engine == 'sapi5' and self.sapi:
                voices = []
                voice_tokens = self.sapi.GetVoices()

                for i in range(voice_tokens.Count):
                    voice = voice_tokens.Item(i)
                    voices.append(voice.GetDescription())

                return voices
            elif self.engine == 'espeak':
                return self.get_espeak_voices()
            else:
                return []
        except Exception as e:
            print(f"Błąd pobierania listy głosów: {e}")
            return []

    def set_voice(self, voice_index):
        """
        Ustawia głos dla aktualnego silnika.

        Args:
            voice_index (int): Indeks głosu z listy dostępnych głosów
        """
        try:
            if self.engine == 'sapi5' and self.sapi:
                voice_tokens = self.sapi.GetVoices()
                if 0 <= voice_index < voice_tokens.Count:
                    self.sapi.Voice = voice_tokens.Item(voice_index)
                    self.current_voice = self.sapi.Voice
            elif self.engine == 'espeak':
                voices = self.get_espeak_voices()
                if 0 <= voice_index < len(voices):
                    voice_info = voices[voice_index]
                    self.espeak_voice = voice_info['id']
                    print(f"[StereoSpeech] eSpeak voice set to: {voice_info['display_name']}")
        except Exception as e:
            print(f"Błąd ustawiania głosu: {e}")


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