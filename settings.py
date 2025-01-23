import os
import platform

def get_settings_path():
    if platform.system() == 'Windows':
        return os.path.join(os.getenv('APPDATA'), 'titosoft', 'Titan', 'bg5settings.ini')
    elif platform.system() == 'Linux':
        return os.path.expanduser('~/.config/titosoft/Titan/bg5settings.ini')
    elif platform.system() == 'Darwin':  # macOS
        return os.path.expanduser('~/Library/Application Support/titosoft/Titan/bg5settings.ini')
    else:
        raise NotImplementedError('Unsupported platform')

SETTINGS_FILE_PATH = get_settings_path()

def load_settings():
    if not os.path.exists(SETTINGS_FILE_PATH):
        return {}

    settings = {}
    with open(SETTINGS_FILE_PATH, 'r', encoding='utf-8') as file:
        current_section = None
        for line in file:
            line = line.strip()
            if line.startswith('[') and line.endswith(']'):
                current_section = line[1:-1]
                settings[current_section] = {}
            elif '=' in line:
                key, value = line.split('=', 1)
                if current_section:
                    settings[current_section][key.strip()] = value.strip()
    return settings

def save_settings(settings):
    os.makedirs(os.path.dirname(SETTINGS_FILE_PATH), exist_ok=True)
    with open(SETTINGS_FILE_PATH, 'w', encoding='utf-8') as file:
        for section, values in settings.items():
            file.write(f'[{section}]\n')
            for key, value in values.items():
                file.write(f'{key}={value}\n')
            file.write('\n')
