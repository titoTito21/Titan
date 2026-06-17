import gettext
import os
import sys
import locale
from src.settings import settings
from src.platform_utils import get_resource_path, get_user_resource_path


def _localedirs():
    """Return all locale roots to consult, in priority order (user first).

    Both the per-user overlay (`%APPDATA%/titosoft/Titan/languages/`) and the
    bundled `languages/` directory are returned so users can shadow individual
    `.mo` files without redistributing the full language pack.
    """
    user_dir = get_user_resource_path('languages')
    bundled_dir = os.path.join(get_resource_path(), 'languages')
    dirs = []
    if os.path.isdir(user_dir):
        dirs.append(user_dir)
    if os.path.isdir(bundled_dir) and (not dirs or os.path.abspath(bundled_dir) != os.path.abspath(dirs[0])):
        dirs.append(bundled_dir)
    return dirs


def _load_translation_for_domain(domain, lang_code):
    """Load the best gettext translation for (domain, lang_code).

    Walks each locale directory in priority order (user first) and returns the
    first translation that actually has a compiled .mo file. Falls back to a
    NullTranslations identity if none of the directories yields a real catalog.
    """
    for localedir in _localedirs():
        mo_path = os.path.join(localedir, lang_code, 'LC_MESSAGES', f'{domain}.mo')
        if os.path.isfile(mo_path):
            try:
                return gettext.translation(domain, localedir, languages=[lang_code], fallback=False)
            except (FileNotFoundError, OSError):
                continue
    # No real catalog found - return a NullTranslations so gettext returns
    # the original message unchanged.
    return gettext.NullTranslations()

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
    'network',       # Network/messengers (messenger_gui.py, telegram_gui.py, whatsapp_webview.py, etc.)
    'titannet',      # Titan-Net (titan_net.py, titan_net_gui.py)
    'eltenclient',   # EltenLink client (elten_client.py, elten_gui.py)
    'system',        # System (tce_system.py, system_monitor.py, updater.py)
    'controller',    # Controllers (controller_ui.py, controller_modes.py)
    'help',          # Help (help.py)
    'sound',         # Sound (sound.py)
    'accessibility', # Accessibility messages (messages.py)
    'classicstartmenu', # Classic Start Menu (classic_start_menu.py)
    'exit_dialog',   # Exit confirmation dialog (shutdown_question.py)
    'launchers',     # Launcher manager (launcher_manager.py)
    'macros',        # Macro Manager (data/components/macros/init.py)
    'window_switcher', # Window Switcher (src/ui/window_switcher.py)
    'interactive_games', # Interactive Games (network/interactive_games.py, interactive_game_session.py)
    'buffers_system', # Titan Buffer System (src/buffers/*.py)
]

# Store translation objects for each domain
_translations = {}

# Language code to display name mapping
LANGUAGE_NAMES = {
    'pl': 'Polski',
    'en': 'English',
    'de': 'Deutsch',
    'fr': 'Français',
    'es': 'Español',
    'it': 'Italiano',
    'ru': 'Русский',
    'uk': 'Українська',
    'cs': 'Čeština',
    'sk': 'Slovenčina',
}

def get_language_display_name(lang_code):
    """Returns the display name for a language code."""
    return LANGUAGE_NAMES.get(lang_code, lang_code)

def get_language_code_from_display_name(display_name):
    """Returns the language code for a display name."""
    for code, name in LANGUAGE_NAMES.items():
        if name == display_name:
            return code
    return display_name  # Return as-is if not found

def get_available_languages():
    """Scans every languages/ directory (bundled + user overlay) to find
    available language codes. A language is considered available if its folder
    exists in either location, since users may drop in extra languages or
    individual .mo files without touching the installation."""
    languages = set()
    for lang_dir in _localedirs():
        try:
            for d in os.listdir(lang_dir):
                if os.path.isdir(os.path.join(lang_dir, d)):
                    languages.add(d)
        except OSError:
            continue
    languages.add('en')  # Ensure English is always an option
    languages.add('pl')  # Ensure Polish is always an option
    return sorted(languages)

def get_available_languages_display():
    """Returns available languages as display names (e.g., 'Polski', 'English')."""
    lang_codes = get_available_languages()
    return [get_language_display_name(code) for code in lang_codes]

def get_system_language():
    """Detects the system language and returns appropriate language code."""
    try:
        # Try to get the system locale
        system_locale = locale.getdefaultlocale()[0]
        if system_locale:
            # Extract language code (e.g., 'pl' from 'pl_PL')
            lang_code = system_locale.split('_')[0].lower()

            # Check if this language is available
            available_languages = get_available_languages()

            # If system language is available, use it
            if lang_code in available_languages:
                return lang_code

            # If Polish, return 'pl'
            if lang_code == 'pl':
                return 'pl'

            # For any other language, fallback to English
            return 'en'
    except Exception as e:
        print(f"Error detecting system language: {e}")

    # Default fallback to English if detection fails
    return 'en'

def set_language(lang_code='pl'):
    """Sets up the translation objects for the given language code, looking up
    each domain's .mo across both the bundled `languages/` directory and the
    per-user overlay under `%APPDATA%/titosoft/Titan/languages/`. User .mo
    files win over bundled ones for the same domain/language."""
    global language_code, _translations
    # Ensure 'pl' is the default if the configured language is invalid
    if lang_code not in get_available_languages():
        lang_code = 'pl'

    language_code = lang_code  # Update the global variable

    # Load all translation domains using the overlay-aware loader
    _translations = {}
    for domain in TRANSLATION_DOMAINS:
        try:
            trans = _load_translation_for_domain(domain, lang_code)
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

# Initialize translations. Priority: LANG env var, then settings, then system language detection.
# The '_' function will be available globally in the modules that import it.
lang_from_env = os.environ.get('LANG')
if lang_from_env:
    # Extract the language code (e.g., 'pl' from 'pl_PL.UTF-8')
    initial_language = lang_from_env.split('.')[0].split('_')[0]
else:
    # Check if user has explicitly set a language preference
    saved_language = settings.get_setting('language', None)
    if saved_language:
        # Use saved preference
        initial_language = saved_language
    else:
        # No saved preference - detect system language IN MEMORY ONLY.
        # Do NOT persist it here: this module is imported during startup before
        # main.py checks whether the settings file exists to decide if this is a
        # first run (and whether to show the configuration wizard). Writing the
        # settings file here would create it prematurely and the first-run /
        # wizard detection would never trigger. The detected language is saved
        # later by main.py's first-run defaults block and by the wizard itself.
        initial_language = get_system_language()

_ = set_language(initial_language)

def get_translation_function():
    """Returns the current translation function."""
    global _
    return _
