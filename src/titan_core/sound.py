import pygame
import os
import sys
import platform
import subprocess
import atexit
from threading import Lock
from src.settings.settings import load_settings
from src.platform_utils import get_resource_path as _platform_resource_path, IS_WINDOWS, IS_LINUX, IS_MACOS

# Prevent COM cleanup warnings during shutdown
_com_objects = []

def _cleanup_com():
    """Cleanup COM objects before Python finalizes"""
    if hasattr(sys, 'is_finalizing') and sys.is_finalizing():
        return
    global _com_objects
    _com_objects.clear()

atexit.register(_cleanup_com)

# ---------------------------------------------------------------------------
# Channel layout (pygame.mixer channels)
# ---------------------------------------------------------------------------
#  0   – free for find_channel() UI sounds (default pygame slot)
#  1   – background_channel   (background music loop)
#  2   – voice_message_channel (voice messages / recordings)
#  3   – ai_tts_channel        (AI chat TTS)
#  4   – tts_speech_channel    (Titan TTS: eSpeak / SAPI5 / ElevenLabs / say)
#  5–15 – free for UI sounds (find_channel won't steal 1-4)
# ---------------------------------------------------------------------------
TTS_CHANNEL_ID = 4          # Dedicated channel for Titan TTS speech
_TOTAL_CHANNELS = 16        # Total channels to allocate

# Inicjalizacja zmiennych globalnych
current_theme = 'default'
background_channel = None
lock = Lock()  # Synchronizacja odtwarzania dźwięków
sound_theme_volume = 1.0  # Domyślna głośność tematu dźwiękowego
system_volume = 1.0  # Domyślna głośność systemu

# System wiadomości głosowych
voice_message_channel = None
current_voice_message = None
voice_message_playing = False
voice_message_paused = False

# AI TTS channel
ai_tts_channel = None

# Dedicated Titan TTS speech channel (eSpeak, SAPI5, ElevenLabs, etc.)
tts_speech_channel = None

# Global flag to track pygame mixer initialization
_mixer_initialized = False


def resource_path(relative_path):
    """Zwraca pełną ścieżkę do plików zasobów, obsługując PyInstaller i Nuitka."""
    return _platform_resource_path(relative_path)


def get_sfx_directory():
    """Zwraca ścieżkę do katalogu z dźwiękami dla aktualnego motywu."""
    sfx_dir = resource_path(os.path.join('sfx', current_theme))
    if not os.path.exists(sfx_dir):
        print(f"SFX directory does not exist: {sfx_dir}")
    return sfx_dir


def get_available_audio_systems():
    """Zwraca listę dostępnych systemów audio dla danej platformy."""
    systems = []

    if IS_WINDOWS:
        systems.append("Windows Audio (winmm)")
        try:
            import comtypes
            from pycaw.pycaw import AudioUtilities
            # Cache COM objects to prevent cleanup warnings
            global _com_objects
            try:
                devices = AudioUtilities.GetSpeakers()
                if devices:
                    _com_objects.append(devices)
            except Exception:
                pass
            systems.append("Windows Audio (WASAPI)")
        except ImportError:
            pass
    elif IS_LINUX:
        # Check for PulseAudio
        try:
            subprocess.run(["pactl", "info"], check=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            systems.append("PulseAudio")
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        # Check for ALSA
        try:
            subprocess.run(["amixer", "info"], check=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            systems.append("ALSA")
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    elif IS_MACOS:
        systems.append("macOS Core Audio")
    
    if not systems:
        systems.append("No audio system detected")
    
    return systems


def initialize_sound():
    """Inicjalizuje system dźwiękowy z bezpiecznym podwójnym sprawdzeniem."""
    global _mixer_initialized, background_channel, voice_message_channel, ai_tts_channel, tts_speech_channel

    if _mixer_initialized:
        print("Audio system already initialized")
        return True

    try:
        # Safe pygame mixer initialization
        if pygame.mixer.get_init() is None:
            try:
                pygame.mixer.pre_init(frequency=22050, size=-16, channels=2, buffer=512)
                pygame.mixer.init()
            except pygame.error as e:
                print(f"Failed to initialize pygame mixer: {e}")
                return False

        # Ensure we have enough channels for all reserved + free slots
        try:
            current_count = pygame.mixer.get_num_channels()
            if current_count < _TOTAL_CHANNELS:
                pygame.mixer.set_num_channels(_TOTAL_CHANNELS)
                print(f"[Sound] Channels expanded: {current_count} -> {_TOTAL_CHANNELS}")
        except pygame.error as e:
            print(f"[Sound] Could not set channel count: {e}")

        # Safely get reserved channels
        try:
            background_channel    = pygame.mixer.Channel(1)
            voice_message_channel = pygame.mixer.Channel(2)
            ai_tts_channel        = pygame.mixer.Channel(3)
            tts_speech_channel    = pygame.mixer.Channel(TTS_CHANNEL_ID)
        except (pygame.error, IndexError) as e:
            print(f"Failed to get audio channels: {e}")
            # Try to get any available channels
            try:
                background_channel = pygame.mixer.find_channel()
                voice_message_channel = pygame.mixer.find_channel()
                ai_tts_channel = pygame.mixer.find_channel()
                tts_speech_channel = pygame.mixer.find_channel()
            except Exception:
                background_channel = None
                voice_message_channel = None
                ai_tts_channel = None
                tts_speech_channel = None
        
        _mixer_initialized = True
        print(f"Audio system initialized on {platform.system()}")
        
        try:
            available_systems = get_available_audio_systems()
            print(f"Available audio systems: {', '.join(available_systems)}")
        except Exception as e:
            print(f"Could not get available audio systems: {e}")
        
        return True
        
    except Exception as e:
        print(f"Failed to initialize audio system: {e}")
        _mixer_initialized = False
        return False


def play_sound(sound_file, pan=None):
    """Odtwarza dźwięk z bezpiecznym sprawdzaniem inicjalizacji i obsługą błędów."""
    try:
        if not sound_file:
            return
        
        # Check if mixer is initialized
        if not _mixer_initialized or pygame.mixer.get_init() is None:
            if not initialize_sound():
                return  # Cannot initialize sound system
        
        try:
            settings = load_settings()
            stereo_enabled = settings.get('sound', {}).get('stereo_sound', 'False').lower() in ['true', '1']
        except Exception:
            stereo_enabled = False

        # Try to play from current theme first
        if _try_play_sound_from_path(sound_file, pan, stereo_enabled):
            return
            
        # Fallback to default theme
        _try_play_sound_from_path(sound_file, pan, stereo_enabled, use_default_theme=True)
            
    except Exception as e:
        print(f"Critical error in play_sound: {e}")


def _try_play_sound_from_path(sound_file, pan, stereo_enabled, use_default_theme=False):
    """Helper function to try playing sound from a specific theme path."""
    try:
        if use_default_theme:
            sfx_dir = resource_path(os.path.join('sfx', 'default'))
        else:
            sfx_dir = get_sfx_directory()
            
        sound_path = os.path.join(sfx_dir, sound_file)
        
        if not os.path.exists(sound_path):
            return False
            
        with lock:
            # Create sound object
            try:
                sound = pygame.mixer.Sound(sound_path)
            except (pygame.error, UnicodeDecodeError, OSError) as e:
                print(f"Failed to load sound file {sound_path}: {e}")
                return False
            
            # Find a free channel, but never steal reserved channels (1-4)
            try:
                channel = pygame.mixer.find_channel()  # non-stealing
                if not channel:
                    # All free channels busy – pick any non-reserved channel
                    for _cid in range(5, pygame.mixer.get_num_channels()):
                        _ch = pygame.mixer.Channel(_cid)
                        if not _ch.get_busy():
                            channel = _ch
                            break
                if not channel:
                    # As last resort use channel 5 (still avoid TTS channel 4)
                    channel = pygame.mixer.Channel(5)
            except (pygame.error, AttributeError) as e:
                print(f"Failed to find audio channel: {e}")
                return False
            
            # Validate pan value
            if pan is not None:
                try:
                    pan = max(0.0, min(1.0, float(pan)))
                except (ValueError, TypeError):
                    pan = None
            
            # Set volume and pan
            try:
                if stereo_enabled and pan is not None:
                    left_volume = max(0.0, min(1.0, (1.0 - pan) * sound_theme_volume))
                    right_volume = max(0.0, min(1.0, pan * sound_theme_volume))
                    channel.set_volume(left_volume, right_volume)
                else:
                    volume = max(0.0, min(1.0, sound_theme_volume))
                    channel.set_volume(volume)
            except (pygame.error, AttributeError) as e:
                print(f"Failed to set volume: {e}")
                # Continue anyway, sound might still play
            
            # Play the sound
            try:
                channel.play(sound)
                return True
            except (pygame.error, AttributeError) as e:
                print(f"Failed to play sound: {e}")
                return False
                
    except Exception as e:
        theme_type = "default" if use_default_theme else "current"
        print(f"Error playing sound from {theme_type} theme: {e}")
        return False



# Funkcje odtwarzania dźwięków
def play_startup_sound():
    play_sound('core/startup.ogg')

def play_connecting_sound():
    play_sound('system/connecting.ogg')


def play_focus_sound(pan=None):
    play_sound('core/FOCUS.ogg', pan=pan)


def play_select_sound():
    play_sound('core/SELECT.ogg')


def play_statusbar_sound():
    play_sound('ui/statusbar.ogg')


def play_applist_sound():
    play_sound('ui/applist.ogg')


def play_endoflist_sound():
    play_sound('ui/endoflist.ogg')


def play_error_sound():
    play_sound('core/error.ogg')


def play_dialog_sound():
    play_sound('ui/dialog.ogg')


def play_dialogclose_sound():
    play_sound('ui/dialogclose.ogg')


def play_loop_sound():
    """Odtwarza dźwięk w pętli (np. tło muzyczne)."""
    global background_channel

    # Check if mixer and channel are initialized
    if not _mixer_initialized or pygame.mixer.get_init() is None:
        print("Cannot play loop sound: audio system not initialized")
        return

    if background_channel is None:
        print("Cannot play loop sound: background channel not available")
        return

    sfx_dir = get_sfx_directory()
    loop_path = os.path.join(sfx_dir, 'loop.ogg')

    if os.path.exists(loop_path):
        try:
            sound = pygame.mixer.Sound(loop_path)
            sound.set_volume(sound_theme_volume)
            background_channel.play(sound, loops=-1)
        except pygame.error as e:
            print(f"Failed to play background sound: {loop_path}, {e}")
    else:
        print(f"Background sound {loop_path} does not exist, skipping.")


def stop_loop_sound():
    """Zatrzymuje odtwarzanie dźwięku w pętli."""
    global background_channel

    if not _mixer_initialized or pygame.mixer.get_init() is None:
        return

    if background_channel:
        try:
            background_channel.stop()
        except pygame.error as e:
            print(f"Error stopping loop sound: {e}")


def set_theme(theme):
    """Ustawia nowy motyw dźwiękowy i restartuje pętlę dźwięku, jeśli jest aktywna."""
    global current_theme
    current_theme = theme
    stop_loop_sound()
    # play_loop_sound()


def set_sound_theme_volume(volume):
    """Ustawia głośność tematu dźwiękowego."""
    global sound_theme_volume
    sound_theme_volume = volume / 100.0  # Skala 0.0 - 1.0
    print(f"Sound theme volume set to {sound_theme_volume}")


def set_system_volume(volume):
    """Ustawia głośność systemową (wieloplatformowo)."""
    global system_volume
    system_volume = volume / 100.0  # Skala 0.0 - 1.0

    if IS_WINDOWS:
        try:
            import ctypes
            devices = ctypes.windll.winmm.waveOutSetVolume
            volume_int = int(system_volume * 0xFFFF)
            volume_value = (volume_int & 0xFFFF) | (volume_int << 16)
            devices(0, volume_value)
        except Exception as e:
            print(f"Failed to set system volume on Windows: {e}")
    elif IS_LINUX:
        try:
            volume_percent = int(volume)
            # Try PulseAudio first
            try:
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{volume_percent}%"],
                              check=True, stderr=subprocess.DEVNULL)
            except (subprocess.CalledProcessError, FileNotFoundError):
                # Try ALSA as fallback
                try:
                    subprocess.run(["amixer", "set", "Master", f"{volume_percent}%"],
                                  check=True, stderr=subprocess.DEVNULL)
                except (subprocess.CalledProcessError, FileNotFoundError):
                    print("Failed to set system volume on Linux: Neither PulseAudio nor ALSA available")
        except Exception as e:
            print(f"Failed to set system volume on Linux: {e}")
    elif IS_MACOS:
        try:
            volume_percent = int(volume)
            subprocess.run(["osascript", "-e", f"set volume output volume {volume_percent}"],
                          check=True, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"Failed to set system volume on macOS: {e}")
    else:
        print(f"System volume control not supported on {platform.system()}")

    print(f"System volume set to {system_volume}")


def play_voice_message(file_path):
    """Odtwarza wiadomość głosową."""
    global voice_message_channel, current_voice_message, voice_message_playing, voice_message_paused

    if not _mixer_initialized or pygame.mixer.get_init() is None:
        print("Cannot play voice message: audio system not initialized")
        return False

    if voice_message_channel is None:
        print("Cannot play voice message: channel not available")
        return False

    if not os.path.exists(file_path):
        print(f"Voice message file not found: {file_path}")
        return False

    try:
        with lock:
            # Zatrzymaj poprzednią wiadomość jeśli gra
            if voice_message_channel and voice_message_channel.get_busy():
                voice_message_channel.stop()

            current_voice_message = pygame.mixer.Sound(file_path)
            current_voice_message.set_volume(sound_theme_volume)
            voice_message_channel.play(current_voice_message)
            voice_message_playing = True
            voice_message_paused = False

            return True
    except pygame.error as e:
        print(f"Failed to play voice message: {file_path}, {e}")
        return False


def pause_voice_message():
    """Wstrzymuje odtwarzanie wiadomości głosowej."""
    global voice_message_paused, voice_message_playing

    if not _mixer_initialized or voice_message_channel is None:
        return False

    if voice_message_channel and voice_message_channel.get_busy() and not voice_message_paused:
        try:
            voice_message_channel.pause()
            voice_message_paused = True
            voice_message_playing = False
            return True
        except pygame.error as e:
            print(f"Error pausing voice message: {e}")
    return False


def resume_voice_message():
    """Wznawia odtwarzanie wiadomości głosowej."""
    global voice_message_paused, voice_message_playing

    if not _mixer_initialized or voice_message_channel is None:
        return False

    if voice_message_channel and voice_message_paused:
        try:
            voice_message_channel.unpause()
            voice_message_paused = False
            voice_message_playing = True
            return True
        except pygame.error as e:
            print(f"Error resuming voice message: {e}")
    return False


def stop_voice_message():
    """Zatrzymuje odtwarzanie wiadomości głosowej."""
    global voice_message_playing, voice_message_paused, current_voice_message

    if not _mixer_initialized or voice_message_channel is None:
        return False

    if voice_message_channel:
        try:
            voice_message_channel.stop()
            voice_message_playing = False
            voice_message_paused = False
            current_voice_message = None
            return True
        except pygame.error as e:
            print(f"Error stopping voice message: {e}")
    return False


def toggle_voice_message():
    """Przełącza między odtwarzaniem a pauzą wiadomości głosowej."""
    if voice_message_playing:
        return pause_voice_message()
    elif voice_message_paused:
        return resume_voice_message()
    return False


def is_voice_message_playing():
    """Sprawdza czy wiadomość głosowa jest odtwarzana."""
    if not _mixer_initialized or voice_message_channel is None:
        return False
    try:
        return voice_message_playing and voice_message_channel and voice_message_channel.get_busy()
    except pygame.error:
        return False


def is_voice_message_paused():
    """Sprawdza czy wiadomość głosowa jest wstrzymana."""
    if not _mixer_initialized:
        return False
    return voice_message_paused


def play_ai_tts(audio_file_path, wait=False):
    """Odtwarza AI TTS audio na dedykowanym kanale."""
    global ai_tts_channel

    try:
        if not _mixer_initialized or pygame.mixer.get_init() is None:
            if not initialize_sound():
                print("[AI TTS] Cannot initialize sound system")
                return False

        if not ai_tts_channel:
            print("[AI TTS] AI TTS channel not available")
            return False

        # Stop current AI TTS if playing
        if ai_tts_channel.get_busy():
            ai_tts_channel.stop()

        # Load and play audio
        try:
            audio = pygame.mixer.Sound(audio_file_path)
            ai_tts_channel.set_volume(1.0)
            ai_tts_channel.play(audio)

            # Wait for playback to finish if requested
            if wait:
                while ai_tts_channel.get_busy():
                    pygame.time.wait(100)

            return True
        except pygame.error as e:
            print(f"[AI TTS] Error playing audio: {e}")
            return False

    except Exception as e:
        print(f"[AI TTS] Error in play_ai_tts: {e}")
        return False


def stop_ai_tts():
    """Zatrzymuje odtwarzanie AI TTS."""
    global ai_tts_channel

    try:
        if ai_tts_channel and ai_tts_channel.get_busy():
            ai_tts_channel.stop()
    except Exception as e:
        print(f"[AI TTS] Error stopping TTS: {e}")


def is_ai_tts_playing():
    """Sprawdza czy AI TTS jest odtwarzany."""
    global ai_tts_channel

    try:
        return ai_tts_channel and ai_tts_channel.get_busy()
    except Exception:
        return False


def get_tts_channel():
    """
    Return the dedicated Titan TTS pygame channel (channel 4).

    Initializes the sound system if needed.  Always returns a Channel object
    so callers can call .stop() / .play() / .get_busy() without None-checks.
    """
    global tts_speech_channel
    try:
        if not _mixer_initialized or pygame.mixer.get_init() is None:
            initialize_sound()
        if tts_speech_channel is None:
            # Ensure channel slot exists
            if pygame.mixer.get_num_channels() <= TTS_CHANNEL_ID:
                pygame.mixer.set_num_channels(TTS_CHANNEL_ID + 4)
            tts_speech_channel = pygame.mixer.Channel(TTS_CHANNEL_ID)
        return tts_speech_channel
    except Exception as e:
        print(f"[Sound] get_tts_channel error: {e}")
        return None


# Sound system will be initialized by main.py when needed
# DO NOT initialize at module level to avoid initialization order issues
