"""
Titan-Net Server Configuration
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def _require(name):
    raise RuntimeError(
        f"{name} environment variable is required. Set it in /opt/titan-net/.env "
        f"(production) or titan-net server/.env (local) and reload the service."
    )


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
    MAX_UPLOAD_SIZE = int(os.getenv('MAX_UPLOAD_SIZE', 1024 * 1024 * 1024))  # 1GB

    # Security settings
    SECRET_KEY = os.getenv('SECRET_KEY', 'change-this-in-production')
    DATABASE_KEY = os.environ.get('DATABASE_KEY') or _require('DATABASE_KEY')

    # Local development flag. When LOCAL_MODE=1 (set only in the local .env),
    # the first registered user is automatically promoted to administrator.
    # Never enable this in production.
    LOCAL_MODE = os.getenv('LOCAL_MODE', '0') == '1'

    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_DIR = os.getenv('LOG_DIR', 'logs')

    # Mail (email verification, password recovery, user mailboxes).
    # Outbound mail is handed to a local Postfix relay by default; point
    # SMTP_* at an external relay to send without self-hosting Postfix.
    MAIL_ENABLED = os.getenv('MAIL_ENABLED', '0') == '1'
    MAIL_DOMAIN = os.getenv('MAIL_DOMAIN', 'titosofttitan.com')
    MAIL_FROM = os.getenv('MAIL_FROM', 'no-reply@titosofttitan.com')
    MAIL_FROM_NAME = os.getenv('MAIL_FROM_NAME', 'Titan-Net')
    MAIL_PUBLIC_URL = os.getenv('MAIL_PUBLIC_URL', 'https://titosofttitan.com')
    SMTP_HOST = os.getenv('SMTP_HOST', '127.0.0.1')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 25))
    SMTP_USER = os.getenv('SMTP_USER', '')
    SMTP_PASS = os.getenv('SMTP_PASS', '')
    SMTP_TLS = os.getenv('SMTP_TLS', '0') == '1'
    # Shared secret the Postfix delivery pipe (mail_delivery.py) presents to the
    # internal /api/mail/incoming endpoint. Inbound mail is ingested via the
    # running server so the SQLCipher DB is never opened by a second process.
    MAIL_INGEST_TOKEN = os.getenv('MAIL_INGEST_TOKEN', '')

    # OAuth proxy
    # Public base URL Spotify/Allegro will redirect back to. MUST be HTTPS for
    # Allegro and for Spotify production apps. Override via env var.
    OAUTH_PUBLIC_URL = os.getenv('OAUTH_PUBLIC_URL', 'http://localhost:8000')
    # Symmetric key used to encrypt access/refresh tokens at rest.
    # Generate once with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    OAUTH_KEY = os.getenv('TITAN_OAUTH_KEY')

    OAUTH_PROVIDERS = {
        'spotify': {
            'auth_url': 'https://accounts.spotify.com/authorize',
            'token_url': 'https://accounts.spotify.com/api/token',
            'client_id': os.getenv('SPOTIFY_CLIENT_ID', ''),
            'client_secret': os.getenv('SPOTIFY_CLIENT_SECRET', ''),
            # Common scopes - tweak per app needs
            'scope': os.getenv(
                'SPOTIFY_SCOPE',
                'user-read-private user-read-email user-read-playback-state '
                'user-modify-playback-state user-read-currently-playing '
                'playlist-read-private playlist-read-collaborative '
                'user-library-read streaming'
            ),
            # Spotify uses HTTP Basic auth on the token endpoint
            'token_auth_style': 'basic',
        },
        'allegro': {
            'auth_url': 'https://allegro.pl/auth/oauth/authorize',
            'token_url': 'https://allegro.pl/auth/oauth/token',
            'client_id': os.getenv('ALLEGRO_CLIENT_ID', ''),
            'client_secret': os.getenv('ALLEGRO_CLIENT_SECRET', ''),
            # Empty scope = default user scope. Add e.g. 'allegro:api:orders:read'.
            'scope': os.getenv('ALLEGRO_SCOPE', ''),
            'token_auth_style': 'basic',
        },
    }

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
