"""
Titan-Net Server Configuration
"""

import os


class Config:
    """Server configuration"""

    # Server settings
    WEBSOCKET_HOST = os.getenv('WEBSOCKET_HOST', '0.0.0.0')
    WEBSOCKET_PORT = int(os.getenv('WEBSOCKET_PORT', 8001))

    HTTP_HOST = os.getenv('HTTP_HOST', '0.0.0.0')
    HTTP_PORT = int(os.getenv('HTTP_PORT', 8000))

    # Database settings
    DATABASE_PATH = os.getenv('DATABASE_PATH', 'database/titannet.db')

    # File upload settings
    UPLOAD_DIR = os.getenv('UPLOAD_DIR', 'uploads')
    MAX_UPLOAD_SIZE = int(os.getenv('MAX_UPLOAD_SIZE', 100 * 1024 * 1024))  # 100MB

    # Security settings
    SECRET_KEY = os.getenv('SECRET_KEY', 'change-this-in-production')

    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_DIR = os.getenv('LOG_DIR', 'logs')

    # Categories
    VALID_CATEGORIES = [
        'application',
        'component',
        'sound_theme',
        'game',
        'tce_package',
        'language_pack'
    ]

    @classmethod
    def validate(cls):
        """Validate configuration"""
        required_dirs = [cls.UPLOAD_DIR, cls.LOG_DIR, 'database']
        for directory in required_dirs:
            os.makedirs(directory, exist_ok=True)

        return True


# Validate config on import
Config.validate()
