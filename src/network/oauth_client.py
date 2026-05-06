"""
OAuth client for TCE Launcher.

Uses the titan-net server as an OAuth broker for external providers
(Spotify, Allegro, ...). The server holds client_id/client_secret and
refresh_token; this client only ever sees a fresh access_token, scoped
to the logged-in titan-net user.

Typical usage from an app/component:

    from src.network.oauth_client import get_oauth_client

    oauth = get_oauth_client()              # uses the singleton TitanNetClient
    if not oauth.is_connected('spotify'):
        oauth.connect('spotify')            # opens browser, user authorizes
        # ... wait for WS event 'oauth_connected' or poll is_connected()
    token = oauth.get_access_token('spotify')
    # call Spotify API with Authorization: Bearer {token}

The desktop owns the machine, so passing the access_token to the
client is acceptable. Refresh tokens never leave the server.
"""

from __future__ import annotations

import logging
import threading
import time
import webbrowser
from typing import Optional, Dict

try:
    import requests
except ImportError:
    requests = None  # type: ignore

logger = logging.getLogger('TCEOAuth')


class OAuthClient:
    """OAuth broker client backed by the titan-net HTTP API."""

    def __init__(self, titan_client):
        """
        Args:
            titan_client: instance of TitanNetClient (used for http_url + auth).
                          Must already be logged in.
        """
        self._titan = titan_client
        self._lock = threading.Lock()
        # Tiny per-process cache so back-to-back API calls in one tick don't
        # hit the server every time. Token TTL on the server is the source of
        # truth - this is just to coalesce.
        self._cache: Dict[str, Dict] = {}
        self._cache_ttl = 30.0  # seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def connect(self, provider: str) -> bool:
        """
        Open the user's browser at the server's /oauth/{provider}/start.

        The server requires our session token, so we attach it as a query
        param the browser will send back; the start endpoint also accepts
        the standard Authorization header for API callers.
        """
        url = self._start_url(provider)
        if not url:
            return False
        try:
            webbrowser.open(url, new=2)
            logger.info(f"OAuth connect: opened browser for {provider}")
            return True
        except Exception as e:
            logger.error(f"OAuth connect failed for {provider}: {e}")
            return False

    def disconnect(self, provider: str) -> bool:
        """Forget tokens for this provider on the server."""
        if requests is None:
            return False
        try:
            r = requests.delete(
                f"{self._titan.http_url}/api/oauth/{provider}",
                headers=self._headers(),
                timeout=10,
                verify=self._verify_tls(),
            )
            self._cache.pop(provider, None)
            return r.ok
        except Exception as e:
            logger.error(f"OAuth disconnect failed for {provider}: {e}")
            return False

    def is_connected(self, provider: str) -> bool:
        """Lightweight 'is this provider linked?' check."""
        if requests is None:
            return False
        try:
            r = requests.get(
                f"{self._titan.http_url}/api/oauth/{provider}/status",
                headers=self._headers(),
                timeout=10,
                verify=self._verify_tls(),
            )
            if not r.ok:
                return False
            return bool(r.json().get('connected'))
        except Exception as e:
            logger.warning(f"OAuth status check failed for {provider}: {e}")
            return False

    def get_access_token(self, provider: str) -> Optional[str]:
        """
        Return a fresh access_token for the provider. Server auto-refreshes
        if expired. Returns None if not connected or refresh failed.
        """
        if requests is None:
            return None

        cached = self._cache.get(provider)
        if cached and (time.time() - cached['fetched_at']) < self._cache_ttl:
            return cached['access_token']

        with self._lock:
            # Double-check inside the lock
            cached = self._cache.get(provider)
            if cached and (time.time() - cached['fetched_at']) < self._cache_ttl:
                return cached['access_token']

            try:
                r = requests.get(
                    f"{self._titan.http_url}/api/oauth/{provider}/token",
                    headers=self._headers(),
                    timeout=15,
                    verify=self._verify_tls(),
                )
                if r.status_code == 401:
                    self._cache.pop(provider, None)
                    return None
                if not r.ok:
                    logger.warning(f"OAuth token fetch {provider}: HTTP {r.status_code}")
                    return None
                data = r.json()
                if not data.get('success'):
                    return None
                token = data.get('access_token')
                if token:
                    self._cache[provider] = {
                        'access_token': token,
                        'fetched_at': time.time(),
                    }
                return token
            except Exception as e:
                logger.error(f"OAuth token fetch failed for {provider}: {e}")
                return None

    def invalidate(self, provider: Optional[str] = None) -> None:
        """Drop the cache (useful if a provider returned 401 to your code)."""
        if provider is None:
            self._cache.clear()
        else:
            self._cache.pop(provider, None)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _start_url(self, provider: str) -> Optional[str]:
        """
        Build a URL the browser can hit. The server's /oauth/start needs the
        same Bearer auth as any API call; browsers can't easily send custom
        headers from a plain navigation, so we fall back to a session=...
        query parameter that the server also accepts.

        For simplicity we send the user there with the bearer encoded as a
        query param - the server accepts ?session= as an alternative to the
        Authorization header. (See handle_oauth_start.)
        """
        token = self._titan_session_token()
        if not token:
            logger.error("OAuth start: not logged in to titan-net")
            return None
        # The server reads the bearer from the Authorization header; for
        # browser flows we pass it on the URL and the server treats ?session=
        # as equivalent. If you'd rather not put the token on the URL, replace
        # this with a small local opener that does the GET with a header and
        # follows the resulting redirect in a webview.
        return (
            f"{self._titan.http_url}/oauth/{provider}/start"
            f"?session={token}"
        )

    def _titan_session_token(self) -> Optional[str]:
        getter = getattr(self._titan, '_get_auth_token', None)
        if not getter:
            return None
        try:
            return getter() or None
        except Exception:
            return None

    def _headers(self) -> Dict[str, str]:
        token = self._titan_session_token()
        return {'Authorization': f'Bearer {token}'} if token else {}

    def _verify_tls(self):
        # Mirror titan_net.py behavior - set to False for self-signed certs.
        return getattr(self._titan, 'verify_tls', True)


# ----------------------------------------------------------------------
# Singleton convenience - resolves the running TitanNetClient
# ----------------------------------------------------------------------
_singleton: Optional[OAuthClient] = None
_singleton_lock = threading.Lock()


def get_oauth_client(titan_client=None) -> Optional[OAuthClient]:
    """
    Return a process-wide OAuthClient. If titan_client is None, tries to
    locate the currently logged-in TitanNetClient instance.
    """
    global _singleton
    with _singleton_lock:
        if _singleton is not None and titan_client is None:
            return _singleton
        if titan_client is None:
            titan_client = _resolve_titan_client()
        if titan_client is None:
            return None
        _singleton = OAuthClient(titan_client)
        return _singleton


def _resolve_titan_client():
    """
    Best-effort lookup of the active TitanNetClient. Apps/components should
    pass their own reference instead of relying on this.
    """
    try:
        from src.network import titan_net
        for attr in ('client', 'titan_net_client', '_singleton', 'instance'):
            obj = getattr(titan_net, attr, None)
            if obj is not None and hasattr(obj, 'http_url'):
                return obj
    except ImportError:
        pass
    return None
