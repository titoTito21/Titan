import pygame
import os
import sys
import shutil

current_theme = 'default'
background_channel = None

def get_sfx_directory():
    if sys.platform == 'win32':
        sfx_dir = os.path.join(os.getenv('APPDATA'), 'Titosoft', 'Titan', 'SFX')
    elif sys.platform == 'darwin':  # macOS
        sfx_dir = os.path.join(os.path.expanduser('~'), '.titosoft', 'titan', 'sfx')
    else:  # Assume Linux
        sfx_dir = os.path.join(os.path.expanduser('~'), '.titosoft', 'titan', 'sfx')

    if not os.path.exists(sfx_dir):
        os.makedirs(sfx_dir)
        # Skopiuj domyślne pliki dźwiękowe do katalogu SFX
        copy_default_sounds(sfx_dir)
    return sfx_dir

def copy_default_sounds(sfx_dir):
    default_sfx_dir = resource_path('sfx')
    if os.path.exists(default_sfx_dir):
        for root, _, files in os.walk(default_sfx_dir):
            for file in files:
                if file == '.DS_Store':  # Ignore .DS_Store files
                    continue
                src_file = os.path.join(root, file)
                rel_dir = os.path.relpath(root, default_sfx_dir)
                dest_dir = os.path.join(sfx_dir, rel_dir)
                if not os.path.exists(dest_dir):
                    os.makedirs(dest_dir)
                shutil.copy(src_file, dest_dir)

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def initialize_sound():
    pygame.mixer.init()
    global background_channel
    background_channel = pygame.mixer.Channel(1)

def play_sound(sound_file):
    theme_path = os.path.join(get_sfx_directory(), current_theme, sound_file)
    if os.path.exists(theme_path):
        try:
            pygame.mixer.Channel(0).play(pygame.mixer.Sound(theme_path))
        except pygame.error as e:
            print(f"Nie udało się odtworzyć dźwięku: {theme_path}, {e}")
    else:
        print(f"Dźwięk {theme_path} nie istnieje, pomijanie.")

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
    loop_path = os.path.join(get_sfx_directory(), current_theme, 'loop.ogg')
    if os.path.exists(loop_path):
        try:
            background_channel.play(pygame.mixer.Sound(loop_path), loops=-1)
        except pygame.error as e:
            print(f"Nie udało się odtworzyć dźwięku tła: {loop_path}, {e}")
    else:
        print(f"Dźwięk tła {loop_path} nie istnieje, pomijanie.")

def stop_loop_sound():
    if background_channel:
        background_channel.stop()

def set_theme(theme):
    global current_theme
    current_theme = theme
    stop_loop_sound()  # Stop the previous loop sound if any
    play_loop_sound()  # Play the new loop sound if it exists

# Inicjalizacja dźwięku przy starcie
initialize_sound()
