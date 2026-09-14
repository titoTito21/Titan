# -*- coding: utf-8 -*-
"""What a control MEANS, for Titan's applications and for the rest of Windows.

The NVDA add-on has `semantics.py`: a row of a report-mode list read with
its columns beside its name, a word for what the row IS taken from the
column a reader module names, and the window's title said once when it has
changed under a focus that never moved (the file manager titles its window
with the folder it is showing). That module is written against NVDA's own
objects and was never vendored; this is the same three answers written
against this reader's objects - the `nvda_shape.Adapted` wrapper the
shared modules already read - so a row of tNotes, of Explorer's details
view and of Task Manager sounds the same in both readers.

Everything here is asked on the focus path, so each answer is one small
walk (a row's own cells, a window's title) and none of it is a search.
The Windows-wide half is behind the `windowsSemantics` switch; the Titan
half is always on, because those are Titan's own applications and the
reader modules for them ship with this component.
"""

import threading

from titan_access.localization import L

_LOCK = threading.RLock()
#: The last title said, per top-level window.
_titles = {}
_counted = {'rows': 0, 'places': 0}

#: A row is read with at most this many columns after its name.
MAX_COLUMNS = 8
#: A cell longer than this is a paragraph, not a cell.
CELL_LIMIT = 120
#: Roles whose children are the CELLS of a row.
ROW_ROLES = ('listitem', 'row', 'griditem')


def report():
    with _LOCK:
        return dict(_counted)


def forget():
    with _LOCK:
        _titles.clear()
        _counted.update({'rows': 0, 'places': 0})


def _text(value):
    return str(value or '').strip()


def windows_wanted():
    """The Windows-wide layer's switch (on unless the user turned it off)."""
    try:
        from .portable import switchboard
        return bool(switchboard.read('windowsSemantics', True))
    except Exception:                                # noqa: BLE001
        return True


# --------------------------------------------------------------------------- #
# The columns of a row
# --------------------------------------------------------------------------- #
def _headers_of(parent):
    if parent is None:
        return []
    try:
        from .portable.readerModules import schema
        return [_text(one) for one in schema.headers_of(parent)]
    except Exception:                                # noqa: BLE001
        return []


def cells_of(adapted):
    """``[(header, cell)]`` for a row, or ``[]`` when it has no cells.

    The cells are the row's own children with a name (UI Automation gives
    a details-view row its cells as Text children, and Titan's wx lists
    are SysListView32 controls that answer the same way); the headers are
    the list's, read once per parent by the reader-module schema.
    """
    if adapted is None:
        return []
    try:
        role = _text(getattr(getattr(adapted, 'role', None), 'name', '')).lower()
    except Exception:                                # noqa: BLE001
        role = ''
    if role not in ROW_ROLES:
        return []
    try:
        children = list(adapted.children or [])
    except Exception:                                # noqa: BLE001
        return []
    cells = []
    for child in children[:MAX_COLUMNS + 1]:
        try:
            child_role = _text(getattr(getattr(child, 'role', None), 'name',
                                       '')).lower()
        except Exception:                            # noqa: BLE001
            child_role = ''
        if child_role in ('image', 'graphic', 'checkbox', 'button'):
            continue
        name = _text(getattr(child, 'name', ''))
        value = _text(getattr(child, 'value', ''))
        # Explorer's details view: a cell is an edit NAMED for its column
        # ("Date modified") whose VALUE is the content. A Win32 list's
        # cell is a text whose name is the content and whose column is in
        # the header control.
        if value and value != name:
            cells.append((name, value[:CELL_LIMIT]))
        elif child_role in ('edit', 'editabletext') and not value:
            # A column with nothing in it (a folder's size): its heading
            # alone would be read as a word about nothing.
            continue
        else:
            cells.append(('', name[:CELL_LIMIT]))
    if len(cells) <= 1:
        return []
    headers = _headers_of(getattr(adapted, 'parent', None))
    out = []
    for index, (header, cell) in enumerate(cells):
        if not header and index < len(headers):
            header = headers[index]
        out.append((header, cell))
    return out


def _rule_for(adapted, module, headers):
    """The module's list rule as ``{kind_column index, noun, quiet}``."""
    kind_at = None
    noun = ''
    quiet = set()
    if module is not None:
        try:
            found = module.list_rule(adapted, None, headers)
        except Exception:                            # noqa: BLE001
            found = None
        if found:
            wanted = found.get('kind_column')
            if isinstance(wanted, int):
                kind_at = wanted
            elif wanted:
                lowered = [one.lower() for one in headers]
                if str(wanted).lower() in lowered:
                    kind_at = lowered.index(str(wanted).lower())
            noun = _text(found.get('noun'))
            quiet = {str(one).lower() for one in (found.get('quiet') or ())}
    return kind_at, noun, quiet


def row_parts(adapted, module=None, name='', pitches=(0, -4, 0)):
    """The columns of a row as ``[(text, pitch)]`` to say AFTER the name.

    The kind - the application's own word for what the row is, out of the
    column the module names - a little lower, then every other column as
    "header: cell", because a bare date in the middle of a row is a number
    nobody can place. The first cell is the row's name and is not
    repeated. ``[]`` when the row has no cells.
    """
    cells = cells_of(adapted)
    if not cells:
        return []
    name_pitch, kind_pitch, detail_pitch = pitches
    headers = [header for header, _cell in cells]
    kind_at, noun, quiet = _rule_for(adapted, module, headers)
    parts = []
    kind = ''
    if isinstance(kind_at, int) and 0 <= kind_at < len(cells):
        kind = cells[kind_at][1]
    if not kind and noun:
        kind = noun
    if kind:
        parts.append((kind, kind_pitch))
    first = _text(name) or cells[0][1]
    for index, (header, cell) in enumerate(cells):
        if index == kind_at:
            continue
        if index == 0 or cell == first:
            continue
        if header and header.lower() in quiet:
            continue
        parts.append(('%s: %s' % (header, cell) if header else cell,
                      detail_pitch))
    with _LOCK:
        _counted['rows'] += 1
    return parts


# --------------------------------------------------------------------------- #
# Where the user now IS
# --------------------------------------------------------------------------- #
def _top_title(adapted):
    """The top-level window's name, or ''."""
    try:
        top = adapted
        for _step in range(12):
            parent = getattr(top, 'parent', None)
            if parent is None:
                break
            top = parent
        title = _text(getattr(top, 'name', ''))
        if title:
            return title
    except Exception:                                # noqa: BLE001
        pass
    try:
        return _text(getattr(adapted, 'windowText', ''))
    except Exception:                                # noqa: BLE001
        return ''


def place_change(adapted, module=None, hwnd=0):
    """The window's title, when the module says it is a place and it has
    changed since it was last said. '' otherwise.

    Read off the window handle rather than the tree: the focused control
    is a row, and twelve parents up a list is a walk; the top-level
    window's text is one call.
    """
    if adapted is None or module is None:
        return ''
    if not bool(getattr(module, 'title_is_a_place', False)):
        return ''
    title = ''
    root = 0
    try:
        import ctypes
        user32 = ctypes.windll.user32
        root = int(user32.GetAncestor(int(hwnd or 0), 2) or 0) if hwnd else 0
        if root:
            buffer = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(root, buffer, 512)
            title = _text(buffer.value)
    except Exception:                                # noqa: BLE001
        title = ''
    if not title:
        title = _top_title(adapted)
    if not title:
        return ''
    key = root or _text(getattr(module, 'id', ''))
    with _LOCK:
        if _titles.get(key) == title:
            return ''
        _titles[key] = title
        _counted['places'] += 1
    return title


def region_word(adapted, module=None):
    """A name for a pane the program never named, from the module."""
    if adapted is None or module is None:
        return ''
    try:
        role = _text(getattr(getattr(adapted, 'role', None), 'name', ''))
        return _text(module.region_word(adapted, role, ''))
    except Exception:                                # noqa: BLE001
        return ''


def describe():
    """A line for diagnostics."""
    with _LOCK:
        return L('semantics.report', _counted['rows'], _counted['places'])
