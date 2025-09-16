import pygame
import os
import sys
import platform
import subprocess
from threading import Lock
from settings import load_settings

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

# Global flag to track pygame mixer initialization
_mixer_initialized = False


def resource_path(relative_path):
    """Zwraca pełną ścieżkę do plików zasobów, obsługując PyInstaller."""
    try:
        base_path = sys._MEIPASS  # PyInstaller tworzy folder tymczasowy
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def get_sfx_directory():
    """Zwraca ścieżkę do katalogu z dźwiękami dla aktualnego motywu."""
    sfx_dir = resource_path(os.path.join('sfx', current_theme))
    if not os.path.exists(sfx_dir):
        print(f"SFX directory does not exist: {sfx_dir}")
    return sfx_dir


def get_available_audio_systems():
    """Zwraca listę dostępnych systemów audio dla danej platformy."""
    systems = []
    
    if platform.system() == "Windows":
        systems.append("Windows Audio (winmm)")
        try:
            import comtypes
            from pycaw.pycaw import AudioUtilities
            systems.append("Windows Audio (WASAPI)")
        except ImportError:
            pass
    elif platform.system() == "Linux":
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
    elif platform.system() == "Darwin":
        systems.append("macOS Core Audio")
    
    if not systems:
        systems.append("No audio system detected")
    
    return systems


def initialize_sound():
    """Inicjalizuje system dźwiękowy z bezpiecznym podwójnym sprawdzeniem."""
    global _mixer_initialized, background_channel, voice_message_channel
    
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
        
        # Safely get channels
        try:
            background_channel = pygame.mixer.Channel(1)
            voice_message_channel = pygame.mixer.Channel(2)
        except (pygame.error, IndexError) as e:
            print(f"Failed to get audio channels: {e}")
            # Try to get any available channels
            try:
                background_channel = pygame.mixer.find_channel()
                voice_message_channel = pygame.mixer.find_channel()
            except Exception:
                background_channel = None
                voice_message_channel = None
        
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
            
            # Find available channel
            try:
                channel = pygame.mixer.find_channel(True)
                if not channel:
                    print(f"No available audio channel for: {sound_file}")
                    return False
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
    play_sound('startup.ogg')

def play_connecting_sound():
    play_sound('connecting.ogg')


def play_focus_sound(pan=None):
    play_sound('focus.ogg', pan=pan)


def play_select_sound():
    play_sound('select.ogg')


def play_statusbar_sound():
    play_sound('statusbar.ogg')


def play_applist_sound():
    play_sound('applist.ogg')


def play_endoflist_sound():
    play_sound('endoflist.ogg')


def play_error_sound():
    play_sound('error.ogg')


def play_dialog_sound():
    play_sound('dialog.ogg')


def play_dialogclose_sound():
    play_sound('dialogclose.ogg')


def play_loop_sound():
    """Odtwarza dźwięk w pętli (np. tło muzyczne)."""
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
    if background_channel:
        background_channel.stop()


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

    if platform.system() == "Windows":
        try:
            import ctypes
            devices = ctypes.windll.winmm.waveOutSetVolume
            volume_int = int(system_volume * 0xFFFF)
            volume_value = (volume_int & 0xFFFF) | (volume_int << 16)
            devices(0, volume_value)
        except Exception as e:
            print(f"Failed to set system volume on Windows: {e}")
    elif platform.system() == "Linux":
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
    elif platform.system() == "Darwin":  # macOS
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
    
    if voice_message_channel and voice_message_channel.get_busy() and not voice_message_paused:
        voice_message_channel.pause()
        voice_message_paused = True
        voice_message_playing = False
        return True
    return False


def resume_voice_message():
    """Wznawia odtwarzanie wiadomości głosowej."""
    global voice_message_paused, voice_message_playing
    
    if voice_message_channel and voice_message_paused:
        voice_message_channel.unpause()
        voice_message_paused = False
        voice_message_playing = True
        return True
    return False


def stop_voice_message():
    """Zatrzymuje odtwarzanie wiadomości głosowej."""
    global voice_message_playing, voice_message_paused, current_voice_message
    
    if voice_message_channel:
        voice_message_channel.stop()
        voice_message_playing = False
        voice_message_paused = False
        current_voice_message = None
        return True
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
    return voice_message_playing and voice_message_channel and voice_message_channel.get_busy()


def is_voice_message_paused():
    """Sprawdza czy wiadomość głosowa jest wstrzymana."""
    return voice_message_paused


# Inicjalizacja dźwięku na starcie programu
initialize_sound()
