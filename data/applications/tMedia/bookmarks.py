# -*- coding: utf-8 -*-
"""Persistent playback bookmarks for TMedia.

Two things are stored per media item, in one JSON file next to tMedia's
media.ini (``%APPDATA%/Titosoft/Titan/appsettings/media_bookmarks.json``):

* the **resume point** - written automatically while something plays, so a
  three hour film or an audiobook picked up tomorrow continues exactly where
  it was left instead of starting from zero;
* any number of **named bookmarks** the user drops by hand (Ctrl+B in the
  player), so several places in the same long recording can be returned to.

A media item is a single file/stream OR a whole audiobook folder; both are
identified by ``media_key()`` and a bookmark carries a *track index* as well
as a position, which is what makes a bookmark inside a multi-file audiobook
meaningful ("disc 2, chapter 4, 12 minutes in").

The file is deliberately plain JSON and independent of the app being open:
Titan's AI tools read it directly (src/ai/titan_tools.py) to tell the user
what they can resume.
"""

import json
import os
import threading
import time
import uuid
from urllib.parse import urlparse
from urllib.request import url2pathname

import common

BOOKMARKS_FILENAME = 'media_bookmarks.json'

# How many media items are remembered before the oldest ones are dropped.
MAX_ENTRIES = 400

# A resume point is only worth keeping past this position...
RESUME_MIN_POSITION_MS = 15000
# ...and, for a single file, only when the file is long enough to be worth
# resuming at all (a three minute song should always start from the top).
RESUME_MIN_LENGTH_MS = 180000
# Finishing this close to the end counts as "played to the end": the resume
# point is cleared so the item starts from the beginning next time.
RESUME_END_MARGIN_MS = 30000


def media_key(url):
    """Stable identity for a file, stream or folder URL.

    Local paths and ``file://`` URIs collapse onto the same key (and are
    case-folded, since Windows paths are case-insensitive), so the same
    audiobook reached from the Media Library tree, from a bookmark and from
    the AI agent is one item, not three."""
    u = (url or '').strip()
    if not u:
        return ''
    if u.lower().startswith('file://'):
        try:
            u = url2pathname(urlparse(u).path)
        except Exception:
            pass
    elif '://' in u:
        return u.rstrip('/')
    return os.path.normcase(os.path.normpath(u)).rstrip('\\/')


class BookmarkStore:
    """The JSON file, loaded once and written after every change."""

    def __init__(self, path=None):
        self.path = path or os.path.join(os.path.dirname(common.CONFIG_PATH),
                                         BOOKMARKS_FILENAME)
        self._lock = threading.RLock()
        self._items = {}
        self.load()

    # ------------------------------------------------------------------ #
    # Storage
    # ------------------------------------------------------------------ #
    def load(self):
        with self._lock:
            self._items = {}
            if not os.path.exists(self.path):
                return
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as e:
                print(f"[tMedia] could not read bookmarks: {e}")
                return
            items = data.get('items') if isinstance(data, dict) else None
            if isinstance(items, dict):
                self._items = {k: v for k, v in items.items() if isinstance(v, dict)}

    def save(self):
        with self._lock:
            self._prune()
            payload = {'version': 1, 'items': self._items}
            tmp = self.path + '.tmp'
            try:
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(payload, f, ensure_ascii=False, indent=1)
                os.replace(tmp, self.path)
            except Exception as e:
                print(f"[tMedia] could not save bookmarks: {e}")
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except Exception:
                    pass

    def _prune(self):
        """Keep the file small: drop the oldest items, sparing anything the
        user bookmarked by hand for as long as possible."""
        if len(self._items) <= MAX_ENTRIES:
            return
        ordered = sorted(self._items.items(),
                         key=lambda kv: (bool(kv[1].get('bookmarks')),
                                         kv[1].get('updated', 0)))
        for key, _entry in ordered[:len(self._items) - MAX_ENTRIES]:
            self._items.pop(key, None)

    # ------------------------------------------------------------------ #
    # Reading
    # ------------------------------------------------------------------ #
    def entries(self):
        """Every remembered item, most recently played first."""
        with self._lock:
            return sorted((dict(e, key=k) for k, e in self._items.items()),
                          key=lambda e: e.get('updated', 0), reverse=True)

    def get_entry(self, url):
        with self._lock:
            entry = self._items.get(media_key(url))
            return dict(entry) if entry else None

    def get_resume(self, url):
        """``{'track': int, 'position': ms, ...}`` or None."""
        entry = self.get_entry(url)
        resume = entry.get('resume') if entry else None
        if not resume or not resume.get('position'):
            return None
        return resume

    def get_bookmarks(self, url):
        entry = self.get_entry(url)
        return list(entry.get('bookmarks') or []) if entry else []

    # ------------------------------------------------------------------ #
    # Writing
    # ------------------------------------------------------------------ #
    def _ensure(self, url, title=None, kind=None, tracks=None):
        key = media_key(url)
        if not key:
            return None
        entry = self._items.setdefault(key, {})
        entry.setdefault('url', url)
        entry.setdefault('bookmarks', [])
        if title:
            entry['title'] = title
        if kind:
            entry['kind'] = kind
        # The track list is only rewritten when it is new or has changed size,
        # so the routine every-few-seconds resume write stays cheap.
        if tracks and (len(tracks) != len(entry.get('tracks') or [])):
            entry['tracks'] = [{'url': t.get('url', ''), 'title': t.get('title', '')}
                               for t in tracks]
        entry['updated'] = time.time()
        return entry

    def set_resume(self, url, position, track=0, track_title='', length=0,
                   title=None, kind=None, tracks=None):
        with self._lock:
            entry = self._ensure(url, title, kind, tracks)
            if entry is None:
                return
            entry['resume'] = {
                'track': int(track or 0),
                'position': int(max(0, position)),
                'track_title': track_title or '',
                'length': int(length or 0),
                'saved': time.time(),
            }
            self.save()

    def clear_resume(self, url):
        with self._lock:
            entry = self._items.get(media_key(url))
            if not entry or not entry.get('resume'):
                return
            entry.pop('resume', None)
            entry['updated'] = time.time()
            if not entry.get('bookmarks'):
                self._items.pop(media_key(url), None)
            self.save()

    def add_bookmark(self, url, name, position, track=0, track_title='',
                     title=None, kind=None, tracks=None):
        with self._lock:
            entry = self._ensure(url, title, kind, tracks)
            if entry is None:
                return None
            bookmark = {
                'id': uuid.uuid4().hex[:12],
                'name': name or '',
                'track': int(track or 0),
                'position': int(max(0, position)),
                'track_title': track_title or '',
                'created': time.time(),
            }
            entry['bookmarks'].append(bookmark)
            entry['bookmarks'].sort(key=lambda b: (b.get('track', 0),
                                                   b.get('position', 0)))
            self.save()
            return bookmark

    def remove_bookmark(self, url, bookmark_id):
        with self._lock:
            key = media_key(url)
            entry = self._items.get(key)
            if not entry:
                return False
            before = len(entry.get('bookmarks') or [])
            entry['bookmarks'] = [b for b in entry.get('bookmarks') or []
                                  if b.get('id') != bookmark_id]
            if len(entry['bookmarks']) == before:
                return False
            entry['updated'] = time.time()
            if not entry['bookmarks'] and not entry.get('resume'):
                self._items.pop(key, None)
            self.save()
            return True

    def rename_bookmark(self, url, bookmark_id, name):
        with self._lock:
            entry = self._items.get(media_key(url))
            if not entry:
                return False
            for b in entry.get('bookmarks') or []:
                if b.get('id') == bookmark_id:
                    b['name'] = name or b.get('name', '')
                    entry['updated'] = time.time()
                    self.save()
                    return True
            return False

    def forget(self, url):
        with self._lock:
            if self._items.pop(media_key(url), None) is None:
                return False
            self.save()
            return True


_store = None


def get_store():
    """The process-wide store (the player, the bookmarks view and the
    catalog all write to the same file)."""
    global _store
    if _store is None:
        _store = BookmarkStore()
    return _store


def should_keep_resume(position, length, kind):
    """Is this position worth remembering? Audiobooks always are - they are
    listened to in sittings - while a single file has to be long enough, and
    anything played (nearly) to the end is forgotten so it restarts."""
    if position is None or position < 0:
        return False
    if length and position > max(0, length - RESUME_END_MARGIN_MS):
        return False
    if kind == 'audiobook':
        return position >= 1000
    if not length or length < RESUME_MIN_LENGTH_MS:
        return False
    return position >= RESUME_MIN_POSITION_MS
