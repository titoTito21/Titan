import os
import platform

def get_notifications_path():
    if platform.system() == 'Windows':
        return os.path.join(os.getenv('APPDATA'), 'titosoft', 'Titan', 'bg5notifications.tno')
    elif platform.system() == 'Linux':
        return os.path.expanduser('~/.config/titosoft/Titan/bg5notifications.tno')
    elif platform.system() == 'Darwin':  # macOS
        return os.path.expanduser('~/Library/Application Support/titosoft/Titan/bg5notifications.tno')
    else:
        raise NotImplementedError('Unsupported platform')

NOTIFICATIONS_FILE_PATH = get_notifications_path()

def create_notifications_file():
    os.makedirs(os.path.dirname(NOTIFICATIONS_FILE_PATH), exist_ok=True)
    with open(NOTIFICATIONS_FILE_PATH, 'w', encoding='utf-8') as file:
        file.write('')

def add_notification(date, time, appname, content):
    with open(NOTIFICATIONS_FILE_PATH, 'a', encoding='utf-8') as file:
        file.write(f'notification\n')
        file.write(f'date={date}\n')
        file.write(f'time={time}\n')
        file.write(f'appname={appname}\n')
        file.write(f'content={content}\n\n')
