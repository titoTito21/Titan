"""tNotes' Titan actions - reading and writing the user's notes.

Every action here is headless: a note lives in its own ``.tnote`` file under
``Documents/Titan/notes``, so answering "what does my shopping note say" or
"add milk to it" needs no window and does not disturb whatever the user is
doing. tNotes reloads its list whenever it is opened, so a note written here
appears there.

A ``.tnote`` is plain UTF-8: the first line is the title, the rest is the body,
and the file name is the title with anything awkward stripped out - which is
tNotes' own format, read here rather than reinvented.
"""

import os
import sys

# Titan tells us where it is (a packaged add-on runs from an extraction
# cache, so '../../..' from this file would point nowhere near Titan). The
# relative guess is the fallback for running this module by hand.
_TITAN_ROOT = os.environ.get('TITAN_ROOT') or os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if _TITAN_ROOT not in sys.path:
    sys.path.insert(0, _TITAN_ROOT)

from src.titan_core.titan_actions import fails, needs

_UNSAFE = '<>:"/\\|?*'


def _notes_dir():
    path = os.path.join(os.path.expanduser('~'), 'Documents', 'Titan', 'notes')
    os.makedirs(path, exist_ok=True)
    return path


def _safe_name(title):
    cleaned = ''.join(ch for ch in str(title or '') if ch not in _UNSAFE).strip()
    return cleaned or 'note'


def _walk():
    """(title, path) for every note, including ones in folders."""
    found = []
    for root, _dirs, files in os.walk(_notes_dir()):
        for name in sorted(files):
            if name.endswith('.tnote'):
                found.append((name[:-6], os.path.join(root, name)))
    return found


def _find(title):
    wanted = str(title or '').strip().lower()
    if not wanted:
        return None
    notes = _walk()
    for name, path in notes:
        if name.lower() == wanted:
            return path
    for name, path in notes:
        if wanted in name.lower():
            return path
    return None


def _read(path):
    with open(path, 'r', encoding='utf-8', errors='replace') as handle:
        text = handle.read()
    title, _sep, body = text.partition('\n')
    return title, body


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #
def list_notes():
    """List the user's notes."""
    notes = _walk()
    if not notes:
        return "There are no notes yet."
    root = _notes_dir()
    lines = []
    for name, path in notes:
        folder = os.path.relpath(os.path.dirname(path), root)
        where = '' if folder == '.' else f" (in {folder})"
        lines.append(f"- {name}{where}")
    return f"{len(notes)} notes:\n" + "\n".join(lines)


def read_note(title):
    """Read one note."""
    path = _find(title)
    if path is None:
        return fails(f"There is no note called '{title}'.")
    name, body = _read(path)
    return f"{name}\n\n{body.strip() or '(the note is empty)'}"


def search_notes(query):
    """Find notes containing some text."""
    words = [w for w in str(query or '').lower().split() if w]
    if not words:
        return "Say what to look for."
    hits = []
    for name, path in _walk():
        try:
            _title, body = _read(path)
        except OSError:
            continue
        haystack = f"{name}\n{body}".lower()
        if all(word in haystack for word in words):
            hits.append(name)
    if not hits:
        return f"No note contains '{query}'."
    return f"Notes containing '{query}':\n" + "\n".join(f"- {n}" for n in hits)


def create_note(title, text=''):
    """Create a note, or replace one that already has this title."""
    if not str(title).strip():
        return needs('title', "What should the note be called?")
    path = os.path.join(_notes_dir(), f"{_safe_name(title)}.tnote")
    existed = os.path.exists(path)
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(f"{title}\n{text or ''}")
    return (f"Replaced the note '{title}'." if existed
            else f"Created the note '{title}'.")


def append_note(title, text):
    """Add a line to a note, creating it if it does not exist yet."""
    path = _find(title)
    if path is None:
        return create_note(title, text)
    name, body = _read(path)
    body = body.rstrip('\n')
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(f"{name}\n{body}\n{text or ''}")
    return f"Added a line to the note '{name}'."


def delete_note(title):
    """Delete a note."""
    path = _find(title)
    if path is None:
        return fails(f"There is no note called '{title}'.")
    name = os.path.basename(path)[:-6]
    os.remove(path)
    return f"Deleted the note '{name}'."


HANDLERS = {
    'list_notes': list_notes,
    'read_note': read_note,
    'search_notes': search_notes,
    'create_note': create_note,
    'append_note': append_note,
    'delete_note': delete_note,
}


if __name__ == '__main__':
    from src.titan_core.titan_actions import run_cli
    sys.exit(run_cli(HANDLERS))
