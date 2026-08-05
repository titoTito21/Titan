"""At-rest encryption for small local secrets (API keys, tokens, passwords).

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


# --------------------------------------------------------------------------- #
# Which settings are secrets
# --------------------------------------------------------------------------- #
# Whole words, not substrings: 'hotkey' is not a key, and encrypting somebody's
# keyboard shortcut because its name ends in 'key' would lock them out of their
# own setting.
_SECRET_WORDS = frozenset({
    'apikey', 'token', 'secret', 'password', 'passwd', 'pwd',
    'credential', 'credentials', 'passphrase',
})

# 'key' on its own is genuinely ambiguous - 'api_key' is a secret, 'titan_ui_key'
# is which key on the keyboard opens the Titan interface. So a bare 'key' counts
# only next to a word that says which sense is meant, and never next to one that
# says the other.
_KEY_QUALIFIERS = frozenset({
    'api', 'access', 'private', 'auth', 'client', 'licence', 'license',
    'subscription', 'service', 'account', 'session', 'app', 'developer',
    'ai',
})
_KEY_DISQUALIFIERS = frozenset({
    'ui', 'hot', 'hotkey', 'shortcut', 'keyboard', 'press', 'bind', 'binding',
    'map', 'mapping', 'nav', 'menu', 'modifier', 'layout',
})

_WORD_RE = None


def looks_secret(name, field_type=''):
    """Whether a setting called ``name`` holds something confidential.

    Add-ons name their configuration fields themselves, so the only signals
    available are the name and the field's declared type. A declared password
    field is taken at its word; a name is read as whole words.
    """
    global _WORD_RE
    if str(field_type or '').strip().lower() in ('password', 'secret'):
        return True
    if _WORD_RE is None:
        import re
        _WORD_RE = re.compile(r'[a-z0-9]+')
    words = set(_WORD_RE.findall(str(name or '').lower()))
    if words & _SECRET_WORDS:
        return True
    if 'key' in words and not (words & _KEY_DISQUALIFIERS):
        return bool(words & _KEY_QUALIFIERS)
    return False


def store_value(name, plaintext, field_type=''):
    """The form a setting should be written to disk in: encrypted when it is a
    secret, unchanged when it is not."""
    if plaintext and looks_secret(name, field_type):
        return encrypt_secret(plaintext)
    return plaintext


def load_value(stored):
    """The usable value of something written by :func:`store_value`. A value
    that was never encrypted comes back unchanged."""
    return decrypt_secret(stored) if is_encrypted(stored) else stored


def describe_value(name, plaintext, field_type=''):
    """How a value may be shown - to the AI, in a log, in a transcript.

    A secret is never rendered, only counted. This is the single place that
    decides that, so a new caller cannot forget.
    """
    if not plaintext:
        return "(not set)"
    if looks_secret(name, field_type):
        return f"(set, {len(str(plaintext))} characters, kept encrypted)"
    return str(plaintext)
