"""tEdit's Titan actions - what Titan, its AI agent and its voice assistant can
ask the text editor to do.

Two halves, from one handler table each:

- ``attach(frame)`` is called by tedit.py once the editor window exists, and
  joins the Titan Action Bus. Everything that needs the open document ("save
  what I have open", "what does it say", "insert this") is answered by the
  running editor itself.
- ``run_cli`` answers the plain file operations without opening a window at
  all, so "write this to a file" costs nothing and does not disturb the user.

Handlers return a sentence, because the caller may be a screen reader or an AI
narrating what it just did.
"""

import os
import sys

# Titan's root is on the path for every application it launches.
# Titan tells us where it is (a packaged add-on runs from an extraction
# cache, so '../../..' from this file would point nowhere near Titan). The
# relative guess is the fallback for running this module by hand.
_TITAN_ROOT = os.environ.get('TITAN_ROOT') or os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if _TITAN_ROOT not in sys.path:
    sys.path.insert(0, _TITAN_ROOT)

from src.titan_core.titan_actions import fails, needs

_frame = None


def _editor():
    if _frame is None:
        raise RuntimeError("the editor window is not available")
    return _frame


# --------------------------------------------------------------------------- #
# Live: the open document
# --------------------------------------------------------------------------- #
def get_text():
    """Read the whole document that is open in the editor."""
    text = _editor().text_ctrl.GetValue()
    if not text.strip():
        return "The document is empty."
    return text


def set_text(text):
    """Replace the whole document with new text."""
    editor = _editor()
    editor.text_ctrl.SetValue(text or '')
    editor.text_ctrl.SetModified(True)
    return f"Replaced the document ({len(text or '')} characters). Not saved yet."


def insert_text(text):
    """Insert text at the cursor."""
    editor = _editor()
    editor.text_ctrl.WriteText(text or '')
    editor.text_ctrl.SetModified(True)
    return f"Inserted {len(text or '')} characters at the cursor."


def open_file(path):
    """Open a file in the editor."""
    if not os.path.isfile(path):
        return fails(f"There is no file at {path}.")
    editor = _editor()
    editor.LoadFile(path)
    editor.Raise()
    return f"Opened {os.path.basename(path)} in the text editor."


def save():
    """Save the open document to the file it came from."""
    editor = _editor()
    if not editor.current_file:
        return needs('path', "This document has never been saved. What should "
                     "it be called?")
    editor.SaveFile(editor.current_file)
    return f"Saved {os.path.basename(editor.current_file)}."


def save_as(path):
    """Save the open document under a new name."""
    editor = _editor()
    editor.SaveFile(path)
    editor.current_file = path
    return f"Saved the document as {path}."


def get_status():
    """What is open in the editor right now."""
    editor = _editor()
    control = editor.text_ctrl
    text = control.GetValue()
    name = (os.path.basename(editor.current_file) if editor.current_file
            else "an unsaved document")
    modified = " with unsaved changes" if control.IsModified() else ""
    line, _column = 0, 0
    try:
        _column, line = control.PositionToXY(control.GetInsertionPoint())[1:]
    except Exception:
        pass
    return (f"The text editor has {name}{modified} open: {len(text)} "
            f"characters, {text.count(chr(10)) + 1} lines, cursor on line "
            f"{line + 1}.")


def replace_text(find, replace='', all=True):
    """Replace text in the open document."""
    editor = _editor()
    control = editor.text_ctrl
    text = control.GetValue()
    if not find:
        return needs('find', "What text should be replaced?")
    count = text.count(find)
    if not count:
        return fails(f"'{find}' does not appear in the document.")
    if all:
        control.SetValue(text.replace(find, replace or ''))
    else:
        control.SetValue(text.replace(find, replace or '', 1))
        count = 1
    control.SetModified(True)
    return f"Replaced {count} occurrence(s) of '{find}'. Not saved yet."


# --------------------------------------------------------------------------- #
# Headless: plain files, no window
# --------------------------------------------------------------------------- #
def read_file(path):
    """Read a text file without opening the editor."""
    if not os.path.isfile(path):
        return fails(f"There is no file at {path}.")
    with open(path, 'r', encoding='utf-8', errors='replace') as handle:
        content = handle.read()
    if len(content) > 20000:
        return content[:20000] + f"\n... (truncated, {len(content)} characters total)"
    return content or "The file is empty."


def write_file(path, text):
    """Create or overwrite a text file."""
    folder = os.path.dirname(os.path.abspath(path))
    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(text or '')
    return f"Wrote {len(text or '')} characters to {path}."


def append_file(path, text):
    """Add text to the end of a file."""
    with open(path, 'a', encoding='utf-8') as handle:
        handle.write(text or '')
    return f"Appended {len(text or '')} characters to {path}."


# --------------------------------------------------------------------------- #
# Wiring
# --------------------------------------------------------------------------- #
LIVE_HANDLERS = {
    'get_text': get_text,
    'set_text': set_text,
    'insert_text': insert_text,
    'open_file': open_file,
    'save': save,
    'save_as': save_as,
    'get_status': get_status,
    'replace_text': replace_text,
    'read_file': read_file,
    'write_file': write_file,
    'append_file': append_file,
}

HEADLESS_HANDLERS = {
    'read_file': read_file,
    'write_file': write_file,
    'append_file': append_file,
}


def attach(frame):
    """Called by tedit.py once the window exists: from here on, Titan can drive
    the editor. Failing to join must never stop the editor from running."""
    global _frame
    _frame = frame
    try:
        from src.titan_core.titan_actions import serve
    except Exception as e:
        print(f"[tEdit] Titan actions unavailable: {e}")
        return False
    return serve(LIVE_HANDLERS, id='tedit', label='Text Editor', kind='app')


if __name__ == '__main__':
    from src.titan_core.titan_actions import run_cli
    sys.exit(run_cli(HEADLESS_HANDLERS))
