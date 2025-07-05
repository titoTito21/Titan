import gettext
import os
import settings

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

def set_language(language_code='pl'):
    """Sets up the translation object for the given language code."""
    # Ensure 'pl' is the default if the configured language is invalid
    if language_code not in get_available_languages():
        language_code = 'pl'
    
    # The main domain for the application's texts
    domain = 'messages'
    localedir = os.path.abspath('languages')
    
    # Set up gettext
    translation = gettext.translation(domain, localedir, languages=[language_code], fallback=True)
    translation.install()
    return translation.gettext

# Initialize translations with the language from settings
# The '_' function will be available globally in the modules that import it
_ = set_language(settings.get_setting('language', 'pl'))
