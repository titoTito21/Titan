"""Persistent ordering for the main GUI lists and the virtual tab bar.

User-defined positions (set via drag-and-drop in the main GUI) are stored in
a ``.index.TCG`` file inside the TCE config directory, next to
``bg5settings.ini``. The on-disk format is JSON::

    {
      "tab_bar": ["apps", "games", "network"],
      "lists": {
        "apps": ["app:files", "app:browser"],
        "games": ["game:Titan-Games/Snake", "game:Steam/12345"]
      }
    }

Consumers:
- The tab bar cards are reordered with Space (pick up / drop) + Left/Right.
- List items are reordered with Ctrl+Up / Ctrl+Down or by mouse drag.
"""
import json
import os
import threading

from src.settings.settings import get_settings_path

_lock = threading.RLock()
_cache = None


def get_index_path():
    """Absolute path to the ``.index.TCG`` order file in the config directory."""
    return os.path.join(os.path.dirname(get_settings_path()), '.index.TCG')


def _load():
    """Load (and memoise) the order file. Always returns a well-formed dict."""
    global _cache
    if _cache is not None:
        return _cache
    data = {'tab_bar': [], 'lists': {}}
    path = get_index_path()
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                tb = loaded.get('tab_bar')
                lists = loaded.get('lists')
                data['tab_bar'] = list(tb) if isinstance(tb, list) else []
                data['lists'] = dict(lists) if isinstance(lists, dict) else {}
    except Exception as e:
        print(f"[list_order] Failed to read {path}: {e}")
    _cache = data
    return _cache


def _save():
    """Write the cached order file back to disk atomically."""
    path = get_index_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(_load(), f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[list_order] Failed to write {path}: {e}")


def get_tab_bar_order():
    """Return the saved tab bar view-id order (list, possibly empty)."""
    with _lock:
        return list(_load().get('tab_bar', []))


def set_tab_bar_order(view_ids):
    """Persist the tab bar view-id order."""
    with _lock:
        _load()['tab_bar'] = list(view_ids)
        _save()


def get_list_order(list_id):
    """Return the saved item-key order for a list (e.g. 'apps', 'games')."""
    with _lock:
        return list(_load().get('lists', {}).get(list_id, []))


def set_list_order(list_id, keys):
    """Persist the item-key order for a list."""
    with _lock:
        _load().setdefault('lists', {})[list_id] = list(keys)
        _save()


def apply_order(saved_keys, items, key_func):
    """Return ``items`` reordered to match ``saved_keys``.

    Items whose key appears in ``saved_keys`` come first, in the saved order.
    Items not in ``saved_keys`` (newly installed apps, games, etc.) keep their
    original relative order and are appended at the end. The function is
    stable and has no side effects.
    """
    if not saved_keys:
        return list(items)
    index = {k: i for i, k in enumerate(saved_keys)}
    known = []
    unknown = []
    for it in items:
        if key_func(it) in index:
            known.append(it)
        else:
            unknown.append(it)
    known.sort(key=lambda it: index[key_func(it)])
    return known + unknown


# ----------------------------------------------------------------------
# Shared item keys + convenience reorderers
#
# All three front-ends (the wxPython GUI, the invisible UI, and Klango mode)
# build their lists from the same data, so they MUST key items identically
# for the saved positions to line up. Use these helpers everywhere.
# ----------------------------------------------------------------------

def app_key(app):
    """Persistence key for an application dict."""
    shortname = app.get('shortname')
    if shortname:
        return f"app:{shortname}"
    path = app.get('path')
    if path:
        return f"app:{os.path.basename(path)}"
    return f"app:{app.get('name', '')}"


def game_key(platform, game):
    """Persistence key for a game, scoped to its platform."""
    return f"game:{platform}/{game.get('name', '')}"


def text_key(text):
    """Persistence key for a plain-text list item (e.g. a Titan IM entry)."""
    return f"txt:{text}"


def order_apps(apps):
    """Return the application dicts reordered to match the saved 'apps' order."""
    return apply_order(get_list_order('apps'), apps, app_key)


def order_games(platform, games):
    """Return a platform's game dicts reordered to match the saved order."""
    return apply_order(get_list_order('games'), games,
                       lambda g: game_key(platform, g))


def order_texts(list_id, items, text_func=None):
    """Return plain-text-keyed items reordered to match the saved order.

    ``items`` may be a list of strings, or any objects from which
    ``text_func(item)`` returns the visible text used as the key.
    """
    tf = text_func or (lambda x: x)
    return apply_order(get_list_order(list_id), items,
                       lambda it: text_key(tf(it)))


def order_categories(categories, id_func):
    """Reorder category/tab objects by the saved tab bar order.

    ``id_func(category)`` returns the matching GUI view id, or None for
    categories that have no GUI tab bar equivalent (Widgets, Status Bar,
    Menu, ...). Only categories with a view id are reordered, and they are
    reshuffled among the slots they already occupy — categories with no view
    id stay pinned to their original positions.
    """
    saved = get_tab_bar_order()
    if not saved:
        return list(categories)
    movable_idx = [i for i, c in enumerate(categories) if id_func(c) is not None]
    movable = [categories[i] for i in movable_idx]
    reordered = apply_order(saved, movable, id_func)
    result = list(categories)
    for slot, cat in zip(movable_idx, reordered):
        result[slot] = cat
    return result
