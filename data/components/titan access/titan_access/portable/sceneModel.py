# -*- coding: utf-8 -*-
"""What a picture of a window IS, not only what words are in it.

The recogniser answers words and rectangles. That is enough to make a
drawn window navigable and it is not enough to make it understandable: a
menu bar, a list with columns, a status line and the entry the arrow keys
are on all arrive as the same flat run of text, and the reader can only
say them in the order they happened to be read.

This turns that run into a SCENE - the same job a browser's accessibility
tree does for a page, done from geometry because a game's menu and a
virtual machine's screen have no tree to ask.

**Everything here is worked out from what was measured, and marked as a
guess where it is one.** Nothing invents content: a piece's text is
exactly what came back. What is added is where the piece sits in the
window and what that position means - and the one thing a picture really
does say about meaning, which is what has been HIGHLIGHTED.

* **Rows and columns.** Pieces that start at the same x down many rows
  are a column, and a window with two or more of them is a table - so a
  row can be read as "name, size, date" rather than as one lump, which is
  what a file list inside a virtual machine looks like.
* **The bands.** The top strip of short pieces spread across the width is
  a menu bar; the bottom strip is a status line; a single centred piece
  at the very top is a title. Read off position, so they are the same in
  every language - the rule Titan's own shell already uses for the
  standard dialog controls.
* **The selection.** The highlighted pieces, which in a game's menu and a
  guest's file list ARE the interface.

It is deliberately portable: pieces in, dictionaries out, no NVDA, no
Titan, no picture. That is what lets both readers use it and what lets it
be tested without either.
"""

import threading

from . import i18n

_ = i18n.install(globals())

_LOCK = threading.RLock()

#: How near two pieces' left edges must be, as a fraction of the row
#: height, to count as the same column. A column is what makes a row
#: readable as cells; too tight and a table is never seen, too loose and
#: a paragraph becomes one.
COLUMN_NEAR = 1.2

#: How many rows must share a column before it is one. Two pieces that
#: happen to line up are a coincidence; four rows of them are a table.
COLUMN_ROWS = 3

#: The fraction of the window's height the top and bottom bands occupy.
#: A menu bar and a status line are both one row of text in a window many
#: rows tall.
BAND = 0.12

#: How much of the window's width the pieces of a band must cover before
#: it reads as a menu bar rather than as a heading that happens to be at
#: the top.
MENU_SPREAD = 0.35

_counted = {'scenes': 0, 'tables': 0, 'menus': 0, 'selected': 0}


def report():
    with _LOCK:
        return dict(_counted)


def forget():
    with _LOCK:
        for key in _counted:
            _counted[key] = 0


def _text(value):
    return str(value or '').strip()


def _piece(node):
    """One node, as a plain dictionary. Accepts a Node or a dict."""
    if isinstance(node, dict):
        got = dict(node)
        got.setdefault('text', '')
        return got
    return {'text': _text(getattr(node, 'text', '')),
            'left': int(getattr(node, 'left', 0) or 0),
            'top': int(getattr(node, 'top', 0) or 0),
            'width': int(getattr(node, 'width', 0) or 0),
            'height': int(getattr(node, 'height', 0) or 0),
            'selected': bool(getattr(node, 'selected', False)),
            'line': int(getattr(node, 'line', 0) or 0),
            'column': int(getattr(node, 'column', 0) or 0)}


def _bounds(pieces):
    """The rectangle everything sits in, which is the window as read."""
    if not pieces:
        return (0, 0, 0, 0)
    left = min(one['left'] for one in pieces)
    top = min(one['top'] for one in pieces)
    right = max(one['left'] + one['width'] for one in pieces)
    bottom = max(one['top'] + one['height'] for one in pieces)
    return (left, top, right - left, bottom - top)


def _rows_of(pieces):
    """The pieces grouped by the row they are on, top to bottom."""
    rows = {}
    for one in pieces:
        rows.setdefault(int(one.get('line', 0) or 0), []).append(one)
    ordered = []
    for key in sorted(rows):
        row = sorted(rows[key], key=lambda p: p['left'])
        ordered.append(row)
    return ordered


def columns_of(rows):
    """The x positions that repeat down the window. ``[]`` for none.

    A table is not declared anywhere in a picture; what says so is that
    the same left edge comes back row after row. Fewer than
    :data:`COLUMN_ROWS` of them is a coincidence rather than a table.
    """
    seen = []
    for row in rows:
        height = max([one['height'] for one in row] or [1])
        for one in row:
            left = one['left']
            for found in seen:
                if abs(found['left'] - left) <= COLUMN_NEAR * height:
                    found['rows'] += 1
                    found['left'] = min(found['left'], left)
                    break
            else:
                seen.append({'left': left, 'rows': 1})
    columns = sorted((one['left'] for one in seen if one['rows'] >= COLUMN_ROWS))
    return columns


def _column_of(piece, columns):
    """Which column a piece belongs to, or -1."""
    if not columns:
        return -1
    height = max(1, piece['height'])
    for index, left in enumerate(columns):
        if abs(piece['left'] - left) <= COLUMN_NEAR * height:
            return index
    # To the left of the first column is still the first cell: a row whose
    # first cell is indented is a row, not a row with no name.
    for index in range(len(columns) - 1, -1, -1):
        if piece['left'] >= columns[index]:
            return index
    return 0


def _is_menu_bar(row, whole):
    """Whether that row reads as a menu bar.

    Position and SHAPE, never the words: "File Edit View" is English, and
    the same bar in Polish is "Plik Edycja Widok". What is the same in
    every language is several short pieces spread across the top of the
    window.
    """
    if len(row) < 3:
        return False
    left, top, width, height = whole
    if height and (row[0]['top'] - top) > BAND * height:
        return False
    covered = (row[-1]['left'] + row[-1]['width']) - row[0]['left']
    if width and covered < MENU_SPREAD * width:
        return False
    longest = max(len(_text(one['text'])) for one in row)
    return longest <= 24


def _is_status(row, whole):
    """The bottom band: a status line, which is news rather than a control."""
    left, top, width, height = whole
    if not height:
        return False
    bottom = row[0]['top'] + max(one['height'] for one in row)
    return (top + height - bottom) <= BAND * height


def scene(nodes, whole=None):
    """The structure of one reading. Never raises.

    ``{'rows': [...], 'columns': [...], 'menu': [...], 'status': [...],
    'title': '', 'selected': [...], 'rect': (l, t, w, h)}`` where a row is
    ``{'cells': [piece...], 'kind': '...', 'selected': bool}`` and every
    piece carries the ``kind`` worked out for it.
    """
    try:
        pieces = [_piece(one) for one in (nodes or [])]
        pieces = [one for one in pieces if _text(one.get('text'))]
    except Exception:                                # noqa: BLE001
        pieces = []
    if not pieces:
        return {'rows': [], 'columns': [], 'menu': [], 'status': [],
                'title': '', 'selected': [], 'rect': (0, 0, 0, 0)}
    rect = whole or _bounds(pieces)
    rows = _rows_of(pieces)
    columns = columns_of(rows)
    made = []
    menu = []
    status = []
    title = ''
    for index, row in enumerate(rows):
        kind = 'row'
        if index == 0 and _is_menu_bar(row, rect):
            kind = 'menubar'
            menu = row
        elif index == len(rows) - 1 and len(rows) > 2 \
                and _is_status(row, rect):
            kind = 'status'
            status = row
        elif len(columns) >= 2 and len(row) >= 2:
            kind = 'cells'
        elif index == 0 and len(row) == 1:
            kind = 'title'
            title = _text(row[0]['text'])
        for piece in row:
            piece['kind'] = _kind_of(piece, kind, columns)
            piece['cell'] = _column_of(piece, columns) if kind == 'cells' \
                else -1
        made.append({'cells': row, 'kind': kind,
                     'selected': any(one.get('selected') for one in row),
                     'top': row[0]['top']})
    chosen = [one for one in pieces if one.get('selected')]
    with _LOCK:
        _counted['scenes'] += 1
        _counted['tables'] += 1 if len(columns) >= 2 else 0
        _counted['menus'] += 1 if menu else 0
        _counted['selected'] += len(chosen)
    return {'rows': made, 'columns': columns, 'menu': menu,
            'status': status, 'title': title, 'selected': chosen,
            'rect': rect}


def _kind_of(piece, row_kind, columns):
    """What one piece is, as far as a picture can say.

    Marked honestly: these are the only four a rectangle and a position
    can support. Anything finer - which of these is a button, what a
    picture shows - is what the model tier is for, and inventing it here
    would be a guess wearing a fact's clothes.
    """
    if piece.get('selected'):
        return 'selected'
    if row_kind == 'menubar':
        return 'menu'
    if row_kind == 'status':
        return 'status'
    if row_kind == 'title':
        return 'title'
    if row_kind == 'cells':
        return 'cell'
    return 'text'


def said_kind(kind):
    """The word for a kind, in the user's own language."""
    return {
        # Translators: what a piece of a recognised window is.
        'menu': _('menu'),
        'status': _('status'),
        'title': _('title'),
        'cell': _('cell'),
        'selected': _('selected'),
    }.get(str(kind or ''), '')


def everything(found):
    """The whole scene as lines somebody can read, in reading order.

    What "show me everything" means: the window as it is laid out, with
    the cells of a row together and the bands named - rather than the run
    of text the recogniser happened to return.
    """
    lines = []
    for row in found.get('rows') or []:
        words = ' '.join(_text(one['text']) for one in row['cells'])
        if not words:
            continue
        name = said_kind(row['kind'] if row['kind'] in
                         ('menubar', 'status', 'title') else '')
        if row['kind'] == 'menubar':
            name = said_kind('menu')
        if row['kind'] == 'status':
            name = said_kind('status')
        if row['kind'] == 'title':
            name = said_kind('title')
        lines.append('%s: %s' % (name, words) if name else words)
    return lines
