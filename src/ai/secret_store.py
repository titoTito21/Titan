"""Where the AI's secret handling used to live.

At-rest encryption is not an AI feature - a TTS engine's API key and an add-on's
token deserve exactly the same protection - so the implementation now sits in
:mod:`src.titan_core.secret_store`. This module stays as its old name so
existing imports keep working.
"""

from src.titan_core.secret_store import (          # noqa: F401
    decrypt_secret, encrypt_secret, is_encrypted,
)

__all__ = ['encrypt_secret', 'decrypt_secret', 'is_encrypted']
