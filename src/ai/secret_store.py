"""At-rest encryption for small local secrets (e.g. AI provider API keys).

Secrets are stored inside the normal settings INI as a single-line string, so
the value must never contain a newline. ``encrypt_secret`` returns a tagged,
base64 string (``dpapi:...`` / ``fernet:...``); ``decrypt_secret`` reverses it
and, for back-compat, returns any UNTAGGED value unchanged (legacy plaintext
keys such as ``titannet_component_ai_key_*`` keep working).

Windows: DPAPI (``CryptProtectData``) ties the ciphertext to the current user
account with no key management. Other platforms fall back to Fernet with a
machine-derived key -- obfuscation grade, but keeps the key off plain sight.
"""

import base64
import hashlib
import platform

_DPAPI_TAG = 'dpapi:'
_FERNET_TAG = 'fernet:'

# Static application salt for the cross-platform fallback. This is NOT a secret
# (it ships in source); it only widens the machine-derived key. DPAPI is used on
# the primary (Windows) platform and needs none of this.
_APP_SALT = b'titan-ai-secret-store-v1'


def _machine_secret():
    """A stable, machine-bound byte string for the Fernet fallback key."""
    parts = [platform.node() or '', platform.system() or '']
    try:
        import uuid
        parts.append(str(uuid.getnode()))  # MAC-derived, stable per machine
    except Exception:
        pass
    try:
        # Linux machine-id is the most stable identifier when present.
        with open('/etc/machine-id', 'r', encoding='utf-8') as fh:
            parts.append(fh.read().strip())
    except Exception:
        pass
    return '|'.join(parts).encode('utf-8')


def _fernet():
    from cryptography.fernet import Fernet
    key = hashlib.pbkdf2_hmac('sha256', _machine_secret(), _APP_SALT, 200000)
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(plaintext):
    """Encrypt ``plaintext`` (str) into a tagged single-line string. Empty input
    returns an empty string. Never raises: on any failure the value is stored as
    plaintext so the feature keeps working (the setting is still non-obvious)."""
    if not plaintext:
        return ''
    data = plaintext.encode('utf-8')
    if platform.system() == 'Windows':
        try:
            import win32crypt
            blob = win32crypt.CryptProtectData(data, 'Titan AI key', None, None, None, 0)
            return _DPAPI_TAG + base64.b64encode(blob).decode('ascii')
        except Exception as e:
            print(f"[secret_store] DPAPI encrypt failed, falling back: {e}")
    try:
        token = _fernet().encrypt(data)
        return _FERNET_TAG + base64.b64encode(token).decode('ascii')
    except Exception as e:
        print(f"[secret_store] Fernet encrypt failed, storing plaintext: {e}")
        return plaintext


def decrypt_secret(stored):
    """Reverse ``encrypt_secret``. An UNTAGGED value is treated as legacy
    plaintext and returned unchanged. Returns '' for empty input and on any
    decryption failure (so a corrupt/foreign-machine value fails closed)."""
    if not stored:
        return ''
    try:
        if stored.startswith(_DPAPI_TAG):
            import win32crypt
            raw = base64.b64decode(stored[len(_DPAPI_TAG):])
            _desc, data = win32crypt.CryptUnprotectData(raw, None, None, None, 0)
            return data.decode('utf-8')
        if stored.startswith(_FERNET_TAG):
            raw = base64.b64decode(stored[len(_FERNET_TAG):])
            return _fernet().decrypt(raw).decode('utf-8')
    except Exception as e:
        print(f"[secret_store] decrypt failed: {e}")
        return ''
    # Untagged -> legacy plaintext (pre-encryption keys).
    return stored


def is_encrypted(stored):
    """True if ``stored`` is a tagged ciphertext (not legacy plaintext)."""
    return bool(stored) and (stored.startswith(_DPAPI_TAG) or stored.startswith(_FERNET_TAG))
