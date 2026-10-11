
import gettext
import os
import platform
import configparser

def get_settings_path():
    """Gets the path to the central bg5settings.ini file."""
    if platform.system() == 'Windows':
        return os.path.join(os.getenv('APPDATA'), 'titosoft', 'Titan', 'bg5settings.ini')
    elif platform.system() == 'Linux':
        return os.path.expanduser('~/.config/titosoft/Titan/bg5settings.ini')
    elif platform.system() == 'Darwin':  # macOS
        return os.path.expanduser('~/Library/Application Support/titosoft/Titan/bg5settings.ini')
    else:
        # Fallback for unknown systems, though might not be ideal
        return os.path.expanduser('~/titosoft/Titan/bg5settings.ini')

def get_titan_language():
    """Reads the language from the central Titan settings file."""
    settings_file = get_settings_path()
    if not os.path.exists(settings_file):
        return 'pl'  # Default to Polish

    config = configparser.ConfigParser()
    try:
        config.read(settings_file, encoding='utf-8')
        # .get() is safer than direct access, provides a fallback
        language = config.get('general', 'language', fallback='pl')
        return language
    except Exception:
        # In case of any error reading the file, default to Polish
        return 'pl'

def set_language(lang_code):
    """Sets up the translation object for the given language code."""
    domain = 'messages'
    # Assume the 'languages' directory is relative to this translation.py file
    localedir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'languages')
    
    # Ensure the language directory exists, otherwise gettext may fail
    if not os.path.isdir(localedir):
        # If there's no languages folder, just return a dummy translator
        return lambda s: s

    translation = gettext.translation(domain, localedir, languages=[lang_code], fallback=True)
    translation.install()
    return translation.gettext

# --- Initialization ---
# Determine the language from Titan's settings and set it up.
# The '_' function will be available for import in other modules.
initial_language = get_titan_language()
_ = set_language(initial_language)

# You can also provide a function to get the current code if needed elsewhere
def get_language_code():
    """Returns the currently set language code."""
    return initial_language
