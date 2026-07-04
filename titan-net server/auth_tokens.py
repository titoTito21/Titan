"""
Titan-Net signed authentication tokens.

Replaces the legacy, trivially forgeable HTTP token (base64("<id>:<username>"))
with an HMAC-SHA256 signed, role-bound, expiring token that the SERVER mints
(it holds the secret) and the client merely carries. Because the payload is
signed with the server secret and re-checked against the database on every
request, a client can neither forge another user's token nor claim a role
(moderator/admin) it does not have.

Token format (opaque to clients):
    tnt1.<b64url(payload_json)>.<b64url(hmac_sha256(secret, body))>
where payload_json = {"uid": int, "un": str, "role": str, "iat": int, "n": str}
and body is the exact "<prefix>.<b64url(payload_json)>" string that was signed.

Verification is constant-time and checks: prefix, signature, expiry, and shape.
The CALLER (http_server.verify_token) additionally re-loads the user and
confirms uid/username/role still match the database — so a stale or tampered
role is caught even if the signature were somehow valid.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Optional, Dict, Any

logger = logging.getLogger('titan-net.auth_tokens')

_PREFIX = "tnt1"
# Default lifetime: 30 days. Long enough that normal users rarely re-login,
# short enough that a leaked token eventually dies.
DEFAULT_TTL_SECONDS = 30 * 24 * 3600


def _secret() -> bytes:
    """The signing key. Uses Config.SECRET_KEY; falls back to DATABASE_KEY if
    SECRET_KEY was left at its insecure default, so tokens are never signed
    with a guessable key on a misconfigured box."""
    try:
        from config import Config
        key = (getattr(Config, 'SECRET_KEY', '') or '')
        if not key or key.startswith('change-this'):
            key = getattr(Config, 'DATABASE_KEY', '') or key
    except Exception:
        key = ''
    if not key:
        # Last-resort ephemeral key: tokens won't survive a restart, which is
        # strictly safer than signing with an empty/known key.
        key = _EPHEMERAL_KEY
    return key.encode('utf-8') if isinstance(key, str) else key


# Stable-per-process fallback key (only used if no configured secret exists).
_EPHEMERAL_KEY = secrets.token_urlsafe(48)


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def _b64u_dec(s: str) -> bytes:
    pad = '=' * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(body: str) -> str:
    mac = hmac.new(_secret(), body.encode('utf-8'), hashlib.sha256).digest()
    return _b64u(mac)


def mint(user_id: int, username: str, role: str = 'user',
         ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
    """Create a signed token for a user. ``role`` is bound into the token so a
    privileged session is cryptographically distinct from a normal one."""
    payload = {
        "uid": int(user_id),
        "un": str(username),
        "role": str(role or 'user'),
        "iat": int(time.time()),
        "ttl": int(ttl_seconds),
        "n": secrets.token_urlsafe(8),
    }
    body = _PREFIX + "." + _b64u(json.dumps(payload, separators=(',', ':')).encode('utf-8'))
    return body + "." + _sign(body)


def looks_like_signed(token: str) -> bool:
    """True if the token uses our signed format (vs a legacy base64 token)."""
    return isinstance(token, str) and token.startswith(_PREFIX + ".") and token.count(".") == 2


def verify(token: str) -> Optional[Dict[str, Any]]:
    """Validate signature + expiry. Returns the payload dict on success, else
    None. Does NOT hit the database — the caller re-checks uid/username/role."""
    try:
        if not looks_like_signed(token):
            return None
        prefix, body_b64, sig = token.split(".", 2)
        body = prefix + "." + body_b64
        expected = _sign(body)
        # Constant-time comparison to defeat timing oracles.
        if not hmac.compare_digest(expected, sig):
            return None
        payload = json.loads(_b64u_dec(body_b64).decode('utf-8'))
        iat = int(payload.get("iat", 0))
        ttl = int(payload.get("ttl", DEFAULT_TTL_SECONDS))
        if ttl <= 0:
            ttl = DEFAULT_TTL_SECONDS
        if time.time() > iat + ttl:
            return None
        if "uid" not in payload or "un" not in payload:
            return None
        payload.setdefault("role", "user")
        return payload
    except Exception:
        return None
