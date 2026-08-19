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

    # Authentication tokens. The HTTP API uses HMAC-signed, role-bound tokens
    # (auth_tokens.py). LEGACY_TOKENS=1 temporarily also accepts the old
    # base64("id:username") tokens so already-deployed desktop clients keep
    # working during a rollout; set it to 0 to fully close the impersonation
    # hole once all clients issue signed tokens.
    LEGACY_TOKENS = os.getenv('LEGACY_TOKENS', '0') == '1'

    # When legacy tokens are accepted (LEGACY_TOKENS=1), bind them to a live
    # session: a forgeable base64("id:username") token is honoured ONLY while
    # that user is (or was, within a short grace) authenticated over WebSocket
    # from the SAME IP. This closes the impersonation hole for old compiled
    # clients (which self-mint legacy tokens but always hold a password-backed
    # WS session) with no client update. Set to 0 to fall back to the old
    # accept-any-legacy-token behaviour if it ever misfires. No effect when
    # LEGACY_TOKENS=0 (legacy tokens rejected outright).
    LEGACY_STRICT_SESSION = os.getenv('LEGACY_STRICT_SESSION', '1') == '1'

    # Local development flag. When LOCAL_MODE=1 (set only in the local .env),
    # the first registered user is automatically promoted to administrator.
    # Never enable this in production.
    LOCAL_MODE = os.getenv('LOCAL_MODE', '0') == '1'

    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_DIR = os.getenv('LOG_DIR', 'logs')

    # Cerberus AI (optional LLM security analyst, "Cerberus"). Uses Google
    # Gemini. Leave the key empty to keep it disabled; the behavioral risk
    # engine still runs without it.
    CERBERUS_AI_KEY = os.getenv('CERBERUS_AI_KEY', '') or os.getenv('GEMINI_API_KEY', '')
    # Default to the most capable Gemini model - this analyst runs on demand, so
    # depth matters more than latency.
    CERBERUS_AI_MODEL = os.getenv('CERBERUS_AI_MODEL', 'gemini-2.5-pro')

    # Blackwall: the recognition layer over Cerberus (behavioural
    # fingerprinting, campaign correlation, threat memory, adaptive posture)
    # plus, when a key is present, a deliberating AI that carries out its own
    # verdicts under guardrails. The recognition half needs no key at all.
    BLACKWALL_ENABLED = os.getenv('BLACKWALL_ENABLED', '1') == '1'
    # 0 = deliberate and report, never act on the model's verdicts. The
    # non-AI layers still ban, because they prove what they saw.
    BLACKWALL_AUTONOMOUS = os.getenv('BLACKWALL_AUTONOMOUS', '1') == '1'
    # Whether Blackwall answers an attacker in its own voice. Never said to a
    # user who merely failed to log in - only to a source that is provably
    # attacking (see blackwall.Blackwall._attack_grounds).
    BLACKWALL_SPEAKS = os.getenv('BLACKWALL_SPEAKS', '1') == '1'
    BLACKWALL_KEY = os.getenv('BLACKWALL_KEY', '') or CERBERUS_AI_KEY
    BLACKWALL_MODEL = os.getenv('BLACKWALL_MODEL', '') or CERBERUS_AI_MODEL


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
