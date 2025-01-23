import pygame
import os
import sys
from threading import Lock

current_theme = 'default'
background_channel = None
lock = Lock()  # Dodany lock do synchronizacji odtwarzania

# Zainicjalizowanie miksera dźwięku
pygame.mixer.init()


def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS  # PyInstaller tworzy folder tymczasowy
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def get_sfx_directory():
    """Returns the path to the sfx directory within the application directory."""
    sfx_dir = resource_path(os.path.join('sfx', current_theme))
    if not os.path.exists(sfx_dir):
        print(f"SFX directory does not exist: {sfx_dir}")
    return sfx_dir


def initialize_sound():
    pygame.mixer.init()
    global background_channel
    background_channel = pygame.mixer.Channel(1)


def play_sound(sound_file):
    """Odtwarza dźwięk bez przerywania innych dźwięków."""
    sfx_dir = get_sfx_directory()
    sound_path = os.path.join(sfx_dir, sound_file)

    if os.path.exists(sound_path):
        try:
            with lock:
                sound = pygame.mixer.Sound(sound_path)
                pygame.mixer.find_channel(True).play(sound)  # Znajduje wolny kanał do odtworzenia dźwięku
        except pygame.error as e:
            print(f"Failed to play sound: {sound_path}, {e}")
    else:
        print(f"Sound {sound_path} does not exist, skipping.")


def play_startup_sound():
    play_sound('startup.ogg')


def play_focus_sound():
    play_sound('focus.ogg')


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
    sfx_dir = get_sfx_directory()
    loop_path = os.path.join(sfx_dir, 'loop.ogg')
    if os.path.exists(loop_path):
        try:
            background_channel.play(pygame.mixer.Sound(loop_path), loops=-1)
        except pygame.error as e:
            print(f"Failed to play background sound: {loop_path}, {e}")
    else:
        print(f"Background sound {loop_path} does not exist, skipping.")


def stop_loop_sound():
    if background_channel:
        background_channel.stop()


def set_theme(theme):
    global current_theme
    current_theme = theme
    stop_loop_sound()  # Zatrzymuje poprzedni dźwięk pętli
    play_loop_sound()  # Odtwarza nową ścieżkę dźwiękową jeśli istnieje


# Inicjalizacja dźwięku przy starcie programu
initialize_sound()
