import pygame
import os
import sys
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

# Zainicjalizowanie miksera dźwięku
pygame.mixer.init()


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


def initialize_sound():
    """Inicjalizuje system dźwiękowy."""
    pygame.mixer.init()
    global background_channel, voice_message_channel
    background_channel = pygame.mixer.Channel(1)
    voice_message_channel = pygame.mixer.Channel(2)


def play_sound(sound_file, pan=None):
    """Odtwarza dźwięk z uwzględnieniem ustawionej głośności tematu dźwiękowego i panoramy."""
    settings = load_settings()
    stereo_enabled = settings.get('sound', {}).get('stereo_sound', 'False').lower() in ['true', '1']

    sfx_dir = get_sfx_directory()
    sound_path = os.path.join(sfx_dir, sound_file)

    if os.path.exists(sound_path):
        try:
            with lock:
                sound = pygame.mixer.Sound(sound_path)
                channel = pygame.mixer.find_channel(True)
                
                # Zastosuj panoramowanie tylko jeśli stereo jest włączone i podano konkretną wartość pan
                if stereo_enabled and pan is not None:
                    left_volume = 1.0 - pan
                    right_volume = pan
                    channel.set_volume(left_volume * sound_theme_volume, right_volume * sound_theme_volume)
                else:
                    # W przeciwnym razie odtwarzaj jako mono (wyśrodkowany)
                    channel.set_volume(sound_theme_volume)
                
                channel.play(sound)
        except pygame.error as e:
            print(f"Failed to play sound: {sound_path}, {e}")
    else:
        # Check for the sound in the default theme as a fallback
        sfx_dir = resource_path(os.path.join('sfx', 'default'))
        sound_path = os.path.join(sfx_dir, sound_file)
        if os.path.exists(sound_path):
            try:
                with lock:
                    sound = pygame.mixer.Sound(sound_path)
                    channel = pygame.mixer.find_channel(True)
                    
                    if stereo_enabled and pan is not None:
                        left_volume = 1.0 - pan
                        right_volume = pan
                        channel.set_volume(left_volume * sound_theme_volume, right_volume * sound_theme_volume)
                    else:
                        channel.set_volume(sound_theme_volume)
                    
                    channel.play(sound)
            except pygame.error as e:
                print(f"Failed to play sound from default theme: {sound_path}, {e}")



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
    """Ustawia głośność systemową (Windows)."""
    global system_volume
    system_volume = volume / 100.0  # Skala 0.0 - 1.0

    try:
        import ctypes
        devices = ctypes.windll.winmm.waveOutSetVolume
        volume_int = int(system_volume * 0xFFFF)
        volume_value = (volume_int & 0xFFFF) | (volume_int << 16)
        devices(0, volume_value)
    except Exception as e:
        print(f"Failed to set system volume: {e}")

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
