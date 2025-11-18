import gettext
import os
import settings

# Global variable to hold the current language code.
# This can be imported by other modules.
language_code = 'pl'

# Translation domains for modular translations
TRANSLATION_DOMAINS = [
    'gui',           # Main GUI (gui.py)
    'invisibleui',   # Invisible UI (invisibleui.py)
    'settings',      # Settings (settings.py, settingsgui.py)
    'menu',          # Menu system (menu.py)
    'main',          # Main program (main.py)
    'apps',          # Application manager (app_manager.py)
    'games',         # Game manager (game_manager.py)
    'components',    # Component manager (component_manager.py, componentmanagergui.py)
    'notifications', # Notifications (notifications.py, notificationcenter.py)
    'network',       # Network/messengers (messenger_gui.py, telegram_gui.py, teamtalk.py, etc.)
    'system',        # System (tce_system.py, system_monitor.py, updater.py)
    'controller',    # Controllers (controller_ui.py, controller_modes.py)
    'help',          # Help (help.py)
    'sound',         # Sound (sound.py)
]

# Store translation objects for each domain
_translations = {}

def get_available_languages():
    """Scans the 'languages' directory to find available language codes."""
    lang_dir = 'languages'
    if not os.path.isdir(lang_dir):
        return ['en']  # Default to English if languages dir doesn't exist

    languages = [d for d in os.listdir(lang_dir) if os.path.isdir(os.path.join(lang_dir, d))]
    if 'en' not in languages:
        languages.insert(0, 'en') # Ensure English is always an option
    if 'pl' not in languages:
        languages.insert(0, 'pl') # Ensure Polish is always an option
    return sorted(languages)

def set_language(lang_code='pl'):
    """Sets up the translation objects for the given language code."""
    global language_code, _translations
    # Ensure 'pl' is the default if the configured language is invalid
    if lang_code not in get_available_languages():
        lang_code = 'pl'

    language_code = lang_code  # Update the global variable
    localedir = os.path.abspath('languages')

    # Load all translation domains
    _translations = {}
    for domain in TRANSLATION_DOMAINS:
        try:
            trans = gettext.translation(domain, localedir, languages=[lang_code], fallback=True)
            _translations[domain] = trans.gettext
        except Exception:
            # If a domain doesn't exist, use NullTranslations (returns original string)
            _translations[domain] = lambda x: x

    # Return a wrapper function that tries all domains
    def multi_domain_gettext(message):
        """Try to translate from all domains, return first non-identity translation."""
        for domain in TRANSLATION_DOMAINS:
            translated = _translations[domain](message)
            if translated != message:
                return translated
        return message

    return multi_domain_gettext

# Initialize translations. Priority: LANG env var, then settings, then fallback to 'pl'.
# The '_' function will be available globally in the modules that import it.
lang_from_env = os.environ.get('LANG')
if lang_from_env:
    # Extract the language code (e.g., 'pl' from 'pl_PL.UTF-8')
    initial_language = lang_from_env.split('.')[0].split('_')[0]
else:
    initial_language = settings.get_setting('language', 'pl')

_ = set_language(initial_language)

def get_translation_function():
    """Returns the current translation function."""
    global _
    return _
