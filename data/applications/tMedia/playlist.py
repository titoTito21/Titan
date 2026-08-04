# -*- coding: utf-8 -*-
"""Turning a folder into a playlist - how TMedia plays an audiobook.

An audiobook here is simply a FOLDER of media files (very often split into
``CD 1`` / ``CD 2`` or one file per chapter). Instead of making the user open
part 1, then part 2, then part 3 by hand and lose their place every time, the
folder is listed once - recursively, in natural order, so ``9`` comes before
``10`` - and played as a single continuous item that the player advances
through on its own and that ``bookmarks.py`` remembers as one thing.

Both kinds of catalog TMedia browses are supported, because both are used as
book shelves: a local/Google Drive folder and an HTTP directory index (the
same listing MediaCatalog parses when the tree is expanded).
"""

import html
import os
import re
from pathlib import Path
from urllib.parse import unquote, quote, urljoin, urlparse
from urllib.request import url2pathname

import requests

MEDIA_FILE_EXTENSIONS = ('.mp3', '.wav', '.ogg', '.wma', '.flac', '.aac',
                         '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv',
                         '.webm', '.m4a', '.m4b', '.opus', '.oga', '.aiff',
                         '.aif', '.mka')

# Guard rails for a wrong turn (pointing this at a whole drive).
MAX_TRACKS = 2000
MAX_DEPTH = 4

_DIGITS = re.compile(r'(\d+)')


def natural_key(text):
    """Sort key where numbers compare as numbers: ``02 - chapter 9`` sorts
    before ``02 - chapter 10``, which plain alphabetical order gets wrong and
    an audiobook cannot survive."""
    return [int(part) if part.isdigit() else part.lower()
            for part in _DIGITS.split(text or '')]


def is_media_file(name):
    return (name or '').lower().endswith(MEDIA_FILE_EXTENSIONS)


def url_to_local_path(url):
    """Local filesystem path for a ``file://`` URI or a plain path; None for
    anything that lives on the network."""
    u = (url or '').strip()
    if not u:
        return None
    if u.lower().startswith('file://'):
        try:
            return url2pathname(urlparse(u).path)
        except Exception:
            return None
    if '://' in u:
        return None
    return u


def to_url(path):
    try:
        return Path(path).as_uri()
    except Exception:
        return path


def is_local_folder(url):
    path = url_to_local_path(url)
    return bool(path and os.path.isdir(path))


def looks_like_folder(url):
    """True when ``url`` addresses a folder rather than a playable item: a
    real directory locally, or a trailing-slash URL in an HTTP index."""
    u = (url or '').strip()
    if not u:
        return False
    if is_local_folder(u):
        return True
    if '://' in u and not u.lower().startswith('file://'):
        return u.endswith('/') and not is_media_file(u)
    return False


def folder_display_name(url):
    """A human name for the folder - what the audiobook is called."""
    path = url_to_local_path(url)
    if path:
        return os.path.basename(os.path.normpath(path)) or path
    parts = [p for p in urlparse(url or '').path.split('/') if p]
    return unquote(parts[-1]) if parts else (url or '')


def track_title(name, prefix=''):
    base = os.path.splitext(name)[0]
    return f"{prefix} / {base}" if prefix else base


# --------------------------------------------------------------------------- #
# Listing
# --------------------------------------------------------------------------- #
def list_folder_tracks(url, max_tracks=MAX_TRACKS, max_depth=MAX_DEPTH):
    """``[{'url': ..., 'title': ...}, ...]`` for every media file under
    ``url``, in the order a listener expects. Empty when the folder holds no
    media or cannot be read."""
    if is_local_folder(url):
        tracks = []
        _list_local(url_to_local_path(url), '', tracks, max_tracks, max_depth)
        return tracks
    if '://' in (url or ''):
        tracks = []
        _list_http(url, '', tracks, max_tracks, max_depth, set())
        return tracks
    return []


def _list_local(path, prefix, out, max_tracks, depth):
    if depth < 0 or len(out) >= max_tracks:
        return
    try:
        entries = list(os.scandir(path))
    except Exception as e:
        print(f"[tMedia] could not list {path}: {e}")
        return
    files = sorted((e for e in entries if e.is_file() and is_media_file(e.name)),
                   key=lambda e: natural_key(e.name))
    folders = sorted((e for e in entries if e.is_dir()),
                     key=lambda e: natural_key(e.name))
    for entry in files:
        if len(out) >= max_tracks:
            return
        out.append({'url': to_url(entry.path),
                    'title': track_title(entry.name, prefix)})
    for entry in folders:
        _list_local(entry.path,
                    f"{prefix} / {entry.name}" if prefix else entry.name,
                    out, max_tracks, depth - 1)


def _http_links(base_url):
    """(files, folders) parsed out of an HTTP directory index, mirroring
    MediaCatalog's tree listing so both reach the same items."""
    files, folders = [], []
    try:
        response = requests.get(base_url, timeout=15)
    except Exception as e:
        print(f"[tMedia] could not list {base_url}: {e}")
        return files, folders
    if response.status_code != 200:
        return files, folders
    for line in response.text.splitlines():
        if 'href="' not in line:
            continue
        start = line.find('href="') + len('href="')
        end = line.find('"', start)
        if end <= start:
            continue
        link = html.unescape(line[start:end])
        if not link or link.startswith('?') or link.startswith('#'):
            continue
        full_url = urljoin(base_url, quote(link, safe='%/'))
        # Never climb out of the folder that was asked for (parent links).
        if not full_url.startswith(base_url) or full_url == base_url:
            continue
        name = unquote(link).replace('%20', ' ').strip('/')
        if link.endswith('/'):
            folders.append((name, full_url))
        elif is_media_file(link):
            files.append((name, full_url))
    return files, folders


def _list_http(base_url, prefix, out, max_tracks, depth, seen):
    if depth < 0 or len(out) >= max_tracks:
        return
    if not base_url.endswith('/'):
        base_url += '/'
    if base_url in seen:
        return
    seen.add(base_url)
    files, folders = _http_links(base_url)
    for name, url in sorted(files, key=lambda item: natural_key(item[0])):
        if len(out) >= max_tracks:
            return
        out.append({'url': url, 'title': track_title(name, prefix)})
    for name, url in sorted(folders, key=lambda item: natural_key(item[0])):
        _list_http(url, f"{prefix} / {name}" if prefix else name,
                   out, max_tracks, depth - 1, seen)
