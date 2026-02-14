# -*- coding: utf-8 -*-
import os
import platform
import json
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

def get_titan_im_config_dir():
    """Get the directory for Titan IM configuration files"""
    if platform.system() == 'Windows':
        config_dir = os.path.join(os.getenv('APPDATA'), 'titosoft', 'Titan')
    elif platform.system() == 'Linux':
        config_dir = os.path.expanduser('~/.config/titosoft/Titan')
    elif platform.system() == 'Darwin':  # macOS
        config_dir = os.path.expanduser('~/Library/Application Support/titosoft/Titan')
    else:
        raise NotImplementedError('Unsupported platform')
    
    os.makedirs(config_dir, exist_ok=True)
    return config_dir

def get_titan_im_config_path():
    """Get the path to Titan IM configuration file"""
    return os.path.join(get_titan_im_config_dir(), 'titan.IM')

def get_machine_salt():
    """Generate a machine-specific salt for encryption"""
    import hashlib
    
    # Create a machine-specific identifier
    machine_info = f"{platform.system()}{platform.node()}{platform.machine()}"
    
    # Create a consistent salt based on machine info
    salt = hashlib.sha256(machine_info.encode()).digest()[:16]
    return salt

def derive_key(password: str = None):
    """Derive encryption key from machine info and optional password"""
    if password is None:
        password = "TitanIM_Default_Key_2025"
    
    salt = get_machine_salt()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return key

def encrypt_data(data: dict, password: str = None) -> bytes:
    """Encrypt configuration data"""
    key = derive_key(password)
    fernet = Fernet(key)
    
    json_data = json.dumps(data, indent=2)
    encrypted_data = fernet.encrypt(json_data.encode())
    return encrypted_data

def decrypt_data(encrypted_data: bytes, password: str = None) -> dict:
    """Decrypt configuration data"""
    key = derive_key(password)
    fernet = Fernet(key)
    
    try:
        decrypted_data = fernet.decrypt(encrypted_data)
        return json.loads(decrypted_data.decode())
    except Exception as e:
        print(f"Failed to decrypt Titan IM config: {e}")
        return {}

def save_titan_im_config(config: dict, password: str = None):
    """Save Titan IM configuration to encrypted file"""
    try:
        config_path = get_titan_im_config_path()
        encrypted_data = encrypt_data(config, password)
        
        with open(config_path, 'wb') as f:
            f.write(encrypted_data)
        
        print(f"Titan IM config saved to: {config_path}")
        return True
    except Exception as e:
        print(f"Error saving Titan IM config: {e}")
        return False

def load_titan_im_config(password: str = None) -> dict:
    """Load Titan IM configuration from encrypted file"""
    config_path = get_titan_im_config_path()
    
    if not os.path.exists(config_path):
        return {}
    
    try:
        with open(config_path, 'rb') as f:
            encrypted_data = f.read()
        
        config = decrypt_data(encrypted_data, password)
        print(f"Titan IM config loaded from: {config_path}")
        return config
    except Exception as e:
        print(f"Error loading Titan IM config: {e}")
        return {}

def get_telegram_config() -> dict:
    """Get Telegram-specific configuration"""
    config = load_titan_im_config()
    return config.get('telegram', {})

def save_telegram_config(telegram_config: dict):
    """Save Telegram-specific configuration"""
    config = load_titan_im_config()
    config['telegram'] = telegram_config
    save_titan_im_config(config)

def set_telegram_credentials(api_id: int, api_hash: str, phone_number: str = None):
    """Save Telegram API credentials"""
    telegram_config = get_telegram_config()
    telegram_config.update({
        'api_id': api_id,
        'api_hash': api_hash,
        'last_phone': phone_number,
        'auto_connect': True
    })
    save_telegram_config(telegram_config)

def get_telegram_credentials() -> tuple:
    """Get saved Telegram API credentials"""
    telegram_config = get_telegram_config()
    return (
        telegram_config.get('api_id'),
        telegram_config.get('api_hash'),
        telegram_config.get('last_phone')
    )

def clear_telegram_config():
    """Clear Telegram configuration"""
    config = load_titan_im_config()
    if 'telegram' in config:
        del config['telegram']
    save_titan_im_config(config)

# EltenLink configuration functions
def get_eltenlink_config() -> dict:
    """Get EltenLink-specific configuration"""
    config = load_titan_im_config()
    return config.get('eltenlink', {})

def save_eltenlink_config(eltenlink_config: dict):
    """Save EltenLink-specific configuration"""
    config = load_titan_im_config()
    config['eltenlink'] = eltenlink_config
    save_titan_im_config(config)

def set_eltenlink_username(username: str):
    """Save EltenLink last username"""
    eltenlink_config = get_eltenlink_config()
    eltenlink_config.update({
        'username': username,
        'last_username': username
    })
    save_eltenlink_config(eltenlink_config)

def get_eltenlink_username() -> str:
    """Get saved EltenLink username"""
    eltenlink_config = get_eltenlink_config()
    return eltenlink_config.get('last_username', '')

def set_eltenlink_credentials(username: str, token: str, password: str = None):
    """
    Save EltenLink credentials for auto-login.

    Args:
        username: EltenLink username
        token: Session token
        password: Optional password for automatic token refresh (encrypted)
    """
    eltenlink_config = get_eltenlink_config()
    eltenlink_config.update({
        'username': username,
        'last_username': username,
        'token': token,
        'auto_connect': True
    })

    # Save password if provided (for automatic token refresh)
    if password:
        eltenlink_config['password'] = password

    save_eltenlink_config(eltenlink_config)

def get_eltenlink_credentials() -> tuple:
    """
    Get saved EltenLink credentials (username, token, password).

    Returns:
        tuple: (username, token, password) - password may be None if not saved
    """
    eltenlink_config = get_eltenlink_config()
    return (
        eltenlink_config.get('username', ''),
        eltenlink_config.get('token', ''),
        eltenlink_config.get('password', None)  # Password for auto-refresh
    )

def clear_eltenlink_credentials():
    """Clear EltenLink saved credentials"""
    eltenlink_config = get_eltenlink_config()
    if 'token' in eltenlink_config:
        del eltenlink_config['token']
    eltenlink_config['auto_connect'] = False
    save_eltenlink_config(eltenlink_config)

def clear_eltenlink_config():
    """Clear EltenLink configuration"""
    config = load_titan_im_config()
    if 'eltenlink' in config:
        del config['eltenlink']
    save_titan_im_config(config)

# Default configuration structure
DEFAULT_CONFIG = {
    "telegram": {
        "api_id": None,
        "api_hash": None,
        "last_phone": None,
        "auto_connect": False,
        "notifications": {
            "sound_enabled": True,
            "tts_enabled": True,
            "show_preview": True
        },
        "ui": {
            "separate_chat_window": False,
            "minimize_to_tray": True
        }
    },
    "eltenlink": {
        "username": None,
        "last_username": None,
        "auto_connect": False,
        "remember_password": False,  # NOT recommended (security)
        "notifications": {
            "sound_enabled": True,
            "tts_enabled": True,
            "show_preview": True
        },
        "ui": {
            "auto_refresh_interval": 15,
            "show_online_status": True,
            "skin": "default"
        },
        "voice": {
            "vad_enabled": True,
            "vad_aggressiveness": 0,
            "self_monitor": False,
            "volume": 100
        },
        "blog": {
            "show_preview": True,
            "auto_load_comments": True
        },
        "forum": {
            "mark_read_on_open": True,
            "show_pinned_first": True
        }
    },
    "general": {
        "version": "1.0",
        "created": None,
        "last_updated": None
    }
}

def initialize_config():
    """Initialize configuration with default values if not exists"""
    if not os.path.exists(get_titan_im_config_path()):
        import datetime
        config = DEFAULT_CONFIG.copy()
        config['general']['created'] = datetime.datetime.now().isoformat()
        config['general']['last_updated'] = datetime.datetime.now().isoformat()
        save_titan_im_config(config)
        print("Initialized Titan IM configuration with default values")