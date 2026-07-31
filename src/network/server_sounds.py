# -*- coding: utf-8 -*-
"""
Server sounds - audio the Titan-Net server can play on this machine.

A moderator uploads a sound to the server once; the server can then play it
at a single user, at everybody holding a role, at a room, or at everyone
online. This module is the receiving half: it fetches the audio the first
time it is asked for, caches it by sha256, and plays it through the normal
TCE sound pipeline so volume, stereo and 3D settings all still apply.

Design notes
------------
* **Cached by content, not by name.** The server sends a sha256 with every
  play request. If the file is already on disk we play immediately and never
  touch the network, so a sound used constantly costs one download, ever.
* **The user stays in charge.** ``titannet_server_sounds`` (Settings ->
  Titan-Net) turns the whole thing off. It defaults to on, but somebody who
  does not want a remote server making noise can say so, and nothing here
  argues.
* **Downloads never block the GUI.** A cache miss is fetched on a worker
  thread; the sound simply arrives a moment later.
* **Bounded.** Oversized payloads are refused, a hash mismatch is discarded
  rather than played, and the cache prunes itself once it grows past
  ``CACHE_LIMIT_BYTES``.

All user-facing text is English and goes through gettext; debug prints do not.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from typing import Dict, Optional

from src.titan_core.translation import set_language
from src.settings.settings import get_setting

_ = set_language(get_setting('language', 'pl'))

# Refuse anything larger than the server's own upload ceiling, so a bad or
# hostile response cannot fill the disk.
MAX_SOUND_BYTES = 5 * 1024 * 1024
# Total cache budget. Well past this and the oldest files go.
CACHE_LIMIT_BYTES = 120 * 1024 * 1024

_cache_lock = threading.Lock()
_inflight: Dict[str, float] = {}   # sha256 -> when the download started


def is_enabled() -> bool:
    """Whether this machine accepts sounds pushed by the server.

    Lives with the rest of the Titan-Net preferences (Settings -> Titan-Net,
    "Allow sounds sent by the server"), falling back to the general settings
    file and finally to on.
    """
    try:
        from src.settings.titan_im_config import load_titan_im_config
        titannet = (load_titan_im_config() or {}).get('titannet_settings', {})
        if 'server_sounds_enabled' in titannet:
            return bool(titannet['server_sounds_enabled'])
    except Exception:
        pass
    try:
        value = get_setting('titannet_server_sounds', True)
    except Exception:
        return True
    if isinstance(value, str):
        return value.strip().lower() not in ('false', '0', 'no', 'off')
    return bool(value)


def get_cache_dir() -> str:
    """Where downloaded server sounds live (created on first use)."""
    try:
        from src.platform_utils import ensure_user_data_subdir
        return ensure_user_data_subdir('data', 'titan_net_server_sounds')
    except Exception:
        base = os.path.join(os.path.expanduser('~'), '.titan', 'titan_net_server_sounds')
        os.makedirs(base, exist_ok=True)
        return base


def _cache_path(sha256: str, mime: Optional[str] = None) -> str:
    # The extension only matters to the decoder, and pygame sniffs content
    # anyway - .snd keeps the cache tidy and unambiguous.
    safe = ''.join(c for c in (sha256 or '') if c.isalnum())[:64]
    return os.path.join(get_cache_dir(), f"{safe}.snd")


def _prune_cache():
    """Drop the least recently used files once the cache outgrows its budget."""
    try:
        directory = get_cache_dir()
        entries = []
        total = 0
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            stat = os.stat(path)
            total += stat.st_size
            entries.append((stat.st_atime, stat.st_size, path))
        if total <= CACHE_LIMIT_BYTES:
            return
        for _atime, size, path in sorted(entries):
            try:
                os.remove(path)
                total -= size
            except Exception:
                continue
            if total <= CACHE_LIMIT_BYTES:
                break
    except Exception as e:
        print(f"[Server sounds] cache prune failed: {e}")


def is_cached(sha256: str) -> bool:
    return bool(sha256) and os.path.isfile(_cache_path(sha256))


def _store(sha256: str, payload: bytes) -> Optional[str]:
    """Verify and write a downloaded sound. Returns the path, or None."""
    if not payload or len(payload) > MAX_SOUND_BYTES:
        print(f"[Server sounds] refused payload of {len(payload)} bytes")
        return None
    actual = hashlib.sha256(payload).hexdigest()
    if sha256 and actual != sha256:
        # Not necessarily an attack - more often a half-finished upload - but
        # either way this is not the audio the server meant to send.
        print(f"[Server sounds] hash mismatch: expected {sha256}, got {actual}")
        return None
    path = _cache_path(actual)
    try:
        temporary = path + '.part'
        with open(temporary, 'wb') as fh:
            fh.write(payload)
        os.replace(temporary, path)
    except Exception as e:
        print(f"[Server sounds] could not cache {actual}: {e}")
        return None
    _prune_cache()
    return path


def ensure_cached(titan_client, name: str, sha256: str) -> Optional[str]:
    """Return a local path for a server sound, downloading it if needed.

    Blocking - call it from a worker thread, which ``play`` already does.
    """
    if sha256 and is_cached(sha256):
        path = _cache_path(sha256)
        try:
            os.utime(path, None)   # keep it fresh for the LRU prune
        except Exception:
            pass
        return path
    if titan_client is None:
        return None

    result = titan_client.download_server_sound(name)
    if not result.get('success') or not result.get('bytes'):
        print(f"[Server sounds] download of '{name}' failed: "
              f"{result.get('error', 'no data')}")
        return None
    return _store(sha256 or result.get('sha256', ''), result['bytes'])


def play(titan_client, message: Dict) -> bool:
    """Handle a ``play_server_sound`` push from the server.

    Returns True when the sound was queued for playback. Downloads happen on
    a worker thread, so this returns immediately either way.
    """
    if not is_enabled():
        return False

    name = str(message.get('name') or '').strip()
    sha256 = str(message.get('sha256') or '').strip()
    if not name:
        return False

    try:
        volume = max(0.0, min(1.0, float(message.get('volume', 1.0))))
    except Exception:
        volume = 1.0
    announce = message.get('announce')

    # Collapse duplicate requests for a sound already on its way down.
    with _cache_lock:
        started = _inflight.get(sha256)
        if started and time.time() - started < 30 and not is_cached(sha256):
            return False
        if not is_cached(sha256):
            _inflight[sha256] = time.time()

    def _worker():
        try:
            path = ensure_cached(titan_client, name, sha256)
            if not path:
                return
            _play_file(path, volume)
            if announce:
                _speak(str(announce))
        finally:
            with _cache_lock:
                _inflight.pop(sha256, None)

    threading.Thread(target=_worker, daemon=True).start()
    return True


def _play_file(path: str, volume: float = 1.0):
    """Play a cached file through the TCE audio pipeline."""
    try:
        from src.titan_core.sound import play_sound_file
        if volume >= 0.999:
            play_sound_file(path)
            return
        # play_sound_file applies the user's theme volume; scale on top of it
        # by handing pygame its own channel when a quieter push is requested.
        try:
            import pygame
            if pygame.mixer.get_init() is None:
                play_sound_file(path)
                return
            sound = pygame.mixer.Sound(path)
            sound.set_volume(volume)
            sound.play()
        except Exception:
            play_sound_file(path)
    except Exception as e:
        print(f"[Server sounds] playback failed for {path}: {e}")


def _speak(text: str):
    try:
        from src.network.titan_net_gui import speak_notification
        speak_notification(text, 'info')
    except Exception:
        try:
            from src.titan_core.sound import speak
            speak(text)
        except Exception:
            pass


def clear_cache() -> int:
    """Delete every cached server sound. Returns how many files went."""
    removed = 0
    try:
        directory = get_cache_dir()
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                try:
                    os.remove(path)
                    removed += 1
                except Exception:
                    continue
    except Exception as e:
        print(f"[Server sounds] cache clear failed: {e}")
    return removed


def cache_size() -> int:
    """Total bytes currently cached."""
    total = 0
    try:
        directory = get_cache_dir()
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                total += os.path.getsize(path)
    except Exception:
        pass
    return total
