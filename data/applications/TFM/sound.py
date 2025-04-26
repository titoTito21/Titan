# TFM/sound.py
import pygame
import os
import sys
import shutil
import platform
import wx # Keep wx import in case it's needed elsewhere in sound, although not for paths now

current_theme = 'default'
background_channel = None

def get_sfx_directory():
    """
    Gets the SFX directory path relative to the application's resources.
    """
    # Directly use resource_path to find the sfx directory relative to the application
    sfx_dir = resource_path('sfx')
    # We no longer create user-specific directories or copy sounds here.
    # Sounds are expected to be in the 'sfx' folder alongside the executable/script.
    # print(f"Getting SFX directory from resources: {sfx_dir}") # Debugging
    return sfx_dir

# Removed _get_fallback_sfx_path as fallback is not needed for resources

# Removed copy_default_sounds as copying to user directory is not desired
# def copy_default_sounds(sfx_dir):
#    ...


def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
        # print(f"Using _MEIPASS for resource path: {base_path}") # Debugging PyInstaller path
    except Exception:
        # Fallback to current directory in development
        base_path = os.path.abspath(".")
        # print(f"Using current directory for resource path: {base_path}") # Debugging development path
    return os.path.join(base_path, relative_path)

def initialize_sound():
    """Initializes the pygame mixer."""
    try:
        if not pygame.mixer.get_init(): # Only initialize if not already initialized
            pygame.mixer.init()
            global background_channel
            background_channel = pygame.mixer.Channel(1)
            # print("Pygame mixer initialized.") # Debugging initialization
        # else:
            # print("Pygame mixer already initialized.") # Debugging
    except Exception as e:
        print(f"Error initializing pygame mixer: {e}")


def play_sound(sound_file):
    """Plays a sound file from the current theme's SFX directory."""
    if not sound_file:
        # print("No sound file specified.")
        return

    # Ensure mixer is initialized before attempting to play
    if not pygame.mixer.get_init():
        # print("Pygame mixer not initialized, cannot play sound.")
        return


    # Load sound directly from the sfx directory relative to the application
    theme_sound_path = os.path.join(get_sfx_directory(), current_theme, sound_file)
    if os.path.exists(theme_sound_path):
        try:
            # Play the sound on channel 0 (or another dedicated sound effects channel)
            pygame.mixer.Channel(0).play(pygame.mixer.Sound(theme_sound_path))
            # print(f"Playing sound: {theme_sound_path}") # Debugging sound playback
        except pygame.error as e:
            print(f"Nie udało się odtworzyć dźwięku {theme_sound_path}: {e}")
        except Exception as e:
             print(f"An unexpected error occurred while playing sound {theme_sound_path}: {e}")
    else:
        # print(f"Dźwięk {theme_sound_path} nie istnieje, pomijanie.")
        pass # Suppress message if sound file is missing


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

def play_delete_sound():
    play_sound('delete.ogg') # Added delete sound function

def play_loop_sound():
    """Plays the loop sound in the background channel."""
    loop_path = os.path.join(get_sfx_directory(), current_theme, 'loop.ogg')
    if os.path.exists(loop_path):
        try:
             if not pygame.mixer.get_init():
                # print("Pygame mixer not initialized, cannot play loop sound.")
                return

             if background_channel:
                # Stop any currently playing loop sound before starting a new one
                background_channel.stop()
                background_channel.play(pygame.mixer.Sound(loop_path), loops=-1)
                # print(f"Playing loop sound: {loop_path}") # Debugging loop playback
             else:
                 print("Background channel not available.")

        except pygame.error as e:
            print(f"Nie udało się odtworzyć dźwięku tła {loop_path}: {e}")
        except Exception as e:
             print(f"An unexpected error occurred while playing loop sound {loop_path}: {e}")
    else:
        # print(f"Dźwięk tła {loop_path} nie istnieje, pomijanie.")
        pass # Suppress message if sound file is missing


def stop_loop_sound():
    """Stops the background loop sound."""
    if background_channel and pygame.mixer.get_init():
        background_channel.stop()
        # print("Stopped loop sound.") # Debugging stop loop


def set_theme(theme):
    """Sets the current sound theme and updates the loop sound."""
    global current_theme
    if current_theme != theme: # Only change if the theme is different
        current_theme = theme
        # print(f"Sound theme set to: {current_theme}") # Debugging theme change
        stop_loop_sound()  # Stop the previous loop sound if any
        play_loop_sound()  # Play the new loop sound if it exists


# Initialize sound when the module is imported (or after wx.App is created in tfm.py)
# initialize_sound() # Moved to tfm.py