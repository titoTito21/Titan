"""tWeb's Titan actions - the browser, its tabs, its bookmarks and its history.

Live actions drive the open browser: which tabs are there, open this address,
go back, what am I looking at. Headless ones answer from the JSON the browser
keeps beside its settings, so "have I got a bookmark for that" costs nothing
and does not open a window.

Note the division of labour with the AI's own ``browser_*`` tools: those drive
a *separate* automation browser for filling in forms on the AI's behalf. These
drive the browser **the user has open**, which is the one they mean when they
say "open it in my browser".
"""

import json
import os
import platform
import sys

# Titan tells us where it is (a packaged add-on runs from an extraction
# cache, so '../../..' from this file would point nowhere near Titan). The
# relative guess is the fallback for running this module by hand.
_TITAN_ROOT = os.environ.get('TITAN_ROOT') or os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if _TITAN_ROOT not in sys.path:
    sys.path.insert(0, _TITAN_ROOT)

from src.titan_core.titan_actions import fails, needs

_frame = None


def _browser():
    if _frame is None:
        raise RuntimeError("the browser window is not open")
    return _frame


def _config_dir():
    system = platform.system()
    if system == 'Windows':
        base = os.getenv('APPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'Titosoft', 'Titan', 'appsettings')
    if system == 'Darwin':
        return os.path.join(os.path.expanduser('~'), 'Library',
                            'Application Support', 'Titosoft', 'Titan',
                            'appsettings')
    return os.path.join(os.path.expanduser('~'), '.config', 'Titosoft',
                        'Titan', 'appsettings')


def _read_json(filename):
    path = os.path.join(_config_dir(), filename)
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write_json(filename, items):
    directory = _config_dir()
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, filename), 'w', encoding='utf-8') as handle:
        json.dump(items, handle, ensure_ascii=False, indent=2)


def _normalise(url):
    text = str(url or '').strip()
    if not text:
        return ''
    if '://' not in text and not text.startswith('about:'):
        text = 'https://' + text
    return text


def _entry(item, *names):
    if isinstance(item, dict):
        for name in names:
            if item.get(name):
                return str(item[name])
    return ''


# --------------------------------------------------------------------------- #
# Headless: bookmarks and history
# --------------------------------------------------------------------------- #
def list_bookmarks():
    """List the user's bookmarks."""
    items = _read_json('tbrowser_bookmarks.json')
    if not items:
        return "There are no bookmarks."
    lines = []
    for index, item in enumerate(items, 1):
        title = _entry(item, 'title', 'name') or '(no title)'
        lines.append(f"{index}. {title} - {_entry(item, 'url')}")
    return f"{len(items)} bookmarks:\n" + "\n".join(lines)


def find_bookmark(query):
    """Find a bookmark by title or address."""
    words = [w for w in str(query or '').lower().split() if w]
    if not words:
        return "Say what to look for."
    hits = []
    for item in _read_json('tbrowser_bookmarks.json'):
        haystack = f"{_entry(item, 'title', 'name')} {_entry(item, 'url')}".lower()
        if all(word in haystack for word in words):
            hits.append(f"- {_entry(item, 'title', 'name') or '(no title)'} "
                        f"- {_entry(item, 'url')}")
    if not hits:
        return fails(f"No bookmark matches '{query}'.")
    return f"Bookmarks matching '{query}':\n" + "\n".join(hits)


def add_bookmark(url, title=''):
    """Save a bookmark."""
    address = _normalise(url)
    if not address:
        return "Give the address to bookmark."
    items = _read_json('tbrowser_bookmarks.json')
    for item in items:
        if _entry(item, 'url') == address:
            return f"{address} is already bookmarked."
    items.append({'url': address, 'title': (title or address).strip()})
    _write_json('tbrowser_bookmarks.json', items)
    return f"Bookmarked {title or address}."


def remove_bookmark(query):
    """Remove a bookmark."""
    wanted = str(query or '').strip().lower()
    if not wanted:
        return "Say which bookmark to remove."
    items = _read_json('tbrowser_bookmarks.json')
    keep = [item for item in items
            if wanted not in f"{_entry(item, 'title', 'name')} "
                             f"{_entry(item, 'url')}".lower()]
    removed = len(items) - len(keep)
    if not removed:
        return fails(f"No bookmark matches '{query}'.")
    if removed > 1:
        titles = [_entry(i, 'title', 'name') or _entry(i, 'url')
                  for i in items if i not in keep][:8]
        return needs('query', f"'{query}' matches {removed} bookmarks. Which "
                     f"one should be removed?", options=titles)
    _write_json('tbrowser_bookmarks.json', keep)
    return f"Removed the bookmark matching '{query}'."


def search_history(query='', limit=30):
    """Look through the pages the user has visited."""
    items = _read_json('tbrowser_history.json')
    if not items:
        return "The history is empty."
    words = [w for w in str(query or '').lower().split() if w]
    hits = []
    for item in reversed(items):
        haystack = f"{_entry(item, 'title')} {_entry(item, 'url')}".lower()
        if not words or all(word in haystack for word in words):
            hits.append(f"- {_entry(item, 'title') or '(no title)'} "
                        f"- {_entry(item, 'url')}")
        if len(hits) >= max(1, min(int(limit or 30), 100)):
            break
    if not hits:
        return f"Nothing in the history matches '{query}'."
    header = (f"History matching '{query}':" if words
              else "Most recently visited:")
    return header + "\n" + "\n".join(hits)


# --------------------------------------------------------------------------- #
# Live: the open browser
# --------------------------------------------------------------------------- #
def current_page():
    """What the browser is showing."""
    frame = _browser()
    tab = frame.get_active_tab()
    if tab is None:
        return "The browser has no page open."
    return f"The browser is showing '{tab.get_title()}' at {tab.get_url()}."


def list_tabs():
    """List the browser's open tabs."""
    frame = _browser()
    if not frame.tabs:
        return "The browser has no tabs open."
    active = frame.get_active_tab()
    lines = []
    for index, tab in enumerate(frame.tabs, 1):
        mark = ' [active]' if tab is active else ''
        lines.append(f"{index}. {tab.get_title()} - {tab.get_url()}{mark}")
    return f"{len(frame.tabs)} tabs:\n" + "\n".join(lines)


def open_url(url, new_tab=True):
    """Open an address in the user's browser."""
    address = _normalise(url)
    if not address:
        return needs('url', "Which web address should the browser open?")
    frame = _browser()
    if new_tab or frame.get_active_tab() is None:
        frame.open_new_tab(address)
    else:
        frame.open_url_in_active_tab(address)
    frame.Raise()
    return f"Opened {address} in the browser."


def go_back():
    """Go back a page."""
    frame = _browser()
    tab = frame.get_active_tab()
    if tab is None:
        return "The browser has no page open."
    if not tab.can_go_back():
        return "There is nothing to go back to."
    tab.go_back()
    return "Went back a page."


def go_forward():
    """Go forward a page."""
    frame = _browser()
    tab = frame.get_active_tab()
    if tab is None:
        return "The browser has no page open."
    if not tab.can_go_forward():
        return "There is nothing to go forward to."
    tab.go_forward()
    return "Went forward a page."


def reload_page():
    """Reload the page."""
    frame = _browser()
    tab = frame.get_active_tab()
    if tab is None:
        return "The browser has no page open."
    tab.refresh()
    return "Reloading the page."


def bookmark_current():
    """Bookmark the page the browser is showing."""
    frame = _browser()
    tab = frame.get_active_tab()
    if tab is None:
        return "The browser has no page open."
    return add_bookmark(tab.get_url(), tab.get_title())


LIVE_HANDLERS = {
    'current_page': current_page,
    'list_tabs': list_tabs,
    'open_url': open_url,
    'go_back': go_back,
    'go_forward': go_forward,
    'reload_page': reload_page,
    'bookmark_current': bookmark_current,
    'list_bookmarks': list_bookmarks,
    'find_bookmark': find_bookmark,
    'add_bookmark': add_bookmark,
    'remove_bookmark': remove_bookmark,
    'search_history': search_history,
}

HEADLESS_HANDLERS = {
    'list_bookmarks': list_bookmarks,
    'find_bookmark': find_bookmark,
    'add_bookmark': add_bookmark,
    'remove_bookmark': remove_bookmark,
    'search_history': search_history,
}


def attach(frame):
    """Called by web.py once the window exists."""
    global _frame
    _frame = frame
    try:
        from src.titan_core.titan_actions import serve
    except Exception as e:
        print(f"[tWeb] Titan actions unavailable: {e}")
        return False
    return serve(LIVE_HANDLERS, id='tweb', label='Web Browser', kind='app')


if __name__ == '__main__':
    from src.titan_core.titan_actions import run_cli
    sys.exit(run_cli(HEADLESS_HANDLERS))
