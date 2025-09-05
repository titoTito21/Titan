import gettext
import os
import settings

# Global variable to hold the current language code.
# This can be imported by other modules.
language_code = 'pl'

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
    """Sets up the translation object for the given language code."""
    global language_code
    # Ensure 'pl' is the default if the configured language is invalid
    if lang_code not in get_available_languages():
        lang_code = 'pl'
    
    language_code = lang_code  # Update the global variable

    # The main domain for the application's texts
    domain = 'messages'
    localedir = os.path.abspath('languages')
    
    # Set up gettext
    translation = gettext.translation(domain, localedir, languages=[lang_code], fallback=True)
    translation.install()
    return translation.gettext

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
