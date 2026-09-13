# -*- coding: utf-8 -*-
"""Titan Virtual Input Accessibility - MSAA for a window that has none.

A virtual machine's screen, a program written against a toolkit nobody
wired up, an installer that paints its own widgets: to Windows these are
one rectangle with nothing inside it. UI Automation answers nothing, MSAA
answers nothing, and the child-window tree is a single client area. There
is no accessibility to read because the program never exposed any.

**But there is a picture, and a picture has structure.** Windows' own
recogniser gives every word its rectangle; rectangles in a row are a line;
lines in a column are a block. That is enough to build the thing the
program did not: a tree of nodes with text, a place, and a role - which is
what MSAA would have given, arrived at from the other end.

Two things make this more than "read the screen aloud", and both were
asked for by somebody using a VM:

* **Plain text and HIGHLIGHTED text are different things**, and in a
  virtual machine the highlight is the whole interface: it is the menu
  entry the arrow keys are on, the selected file, the line the cursor is
  in. Nothing in the picture says so except the COLOURS, so the colours
  are what is read - a run of text whose background is markedly unlike the
  window's own is reported as selected, and a reader can then say "this
  one" rather than reciting the whole screen.
* **What CHANGED matters more than what is there.** A screen re-read from
  the top on every poll is a reader nobody can use. Nodes are matched
  against the last reading by text and place, so the answer to "what
  happened" is the handful of lines that are new.

**It costs nothing but Windows.** No AI, no request, no picture leaves the
machine - see :mod:`localOcr`. The AI is the fallback one layer up
(:mod:`surface`), for a window Windows itself cannot read, and it is the
fallback precisely because this one is free and instant.
"""

import threading

from . import i18n

_ = i18n.install(globals())

#: Two words are on the same LINE if their boxes overlap vertically by
#: more than this much of the shorter one. The recogniser already groups
#: words into lines, but a VM's console is a grid and its "lines" come
#: back split by wide gaps, so they are re-joined by geometry.
SAME_LINE = 0.5

#: A gap wider than this many times the text height means the words are
#: two things on one row rather than one sentence - a menu bar, a status
#: line, a table row. It is what turns a row of pixels into nodes.
COLUMN_GAP = 2.0

#: How different a background has to be from the window's own before a run
#: of text is called highlighted. 0..255 per channel, summed over three -
#: measured against a real terminal's inverse video, which is the whole
#: range, and against anti-aliasing, which is a few units.
HIGHLIGHT_DIFFERENCE = 90

ROLE_TEXT = 'text'
ROLE_HEADING = 'heading'
ROLE_ROW = 'row'
ROLE_SELECTED = 'selected'

_LOCK = threading.RLock()

#: The last tree per window, so "what changed" is answerable.
_last = {}

_counted = {'built': 0, 'nodes': 0, 'highlighted': 0, 'changes': 0}


def _text(value):
    return str(value or '').strip()


# --------------------------------------------------------------------------- #
# A node
# --------------------------------------------------------------------------- #
class Node(object):
    """One thing on a window that exposes nothing.

    Deliberately the same shape as everything else this add-on navigates -
    text, a rectangle, a role, a state - so the cursor, the review and the
    announcements already written work on it unchanged.
    """

    __slots__ = ('text', 'left', 'top', 'width', 'height', 'role',
                 'selected', 'line', 'column')

    def __init__(self, text='', left=0, top=0, width=0, height=0,
                 role=ROLE_TEXT, selected=False, line=0, column=0):
        self.text = text
        self.left = int(left)
        self.top = int(top)
        self.width = int(width)
        self.height = int(height)
        self.role = role
        self.selected = bool(selected)
        self.line = int(line)
        self.column = int(column)

    @property
    def centre(self):
        return (self.left + self.width // 2, self.top + self.height // 2)

    def key(self):
        """What makes this node THAT node between two readings.

        The text and the row, not the exact pixels: a console scrolls by a
        line and a menu moves by a few pixels when it is redrawn, and a
        key that included the coordinates would call every node new.
        """
        return (self.text, self.line)

    def as_dict(self):
        return {'text': self.text, 'left': self.left, 'top': self.top,
                'width': self.width, 'height': self.height,
                'role': self.role, 'selected': self.selected,
                'line': self.line, 'column': self.column}

    def __repr__(self):                              # pragma: no cover
        return '<Node %r line=%d%s>' % (self.text, self.line,
                                        ' selected' if self.selected else '')


# --------------------------------------------------------------------------- #
# Building the tree
# --------------------------------------------------------------------------- #
def _rows(reading):
    """The reading's words, re-grouped into rows by where they really are.

    The recogniser groups words into lines already, and for a page of
    prose that is right. A virtual machine's screen is a GRID - a menu
    bar, a status line, a table - and there the recogniser's idea of a
    line and the screen's own row are not the same thing.
    """
    words = []
    for line in getattr(reading, 'lines', None) or []:
        for word in line or []:
            if not isinstance(word, dict):
                continue
            said = _text(word.get('text'))
            if said:
                words.append(word)
    words.sort(key=lambda w: (int(w.get('top') or 0), int(w.get('left') or 0)))
    rows = []
    for word in words:
        top = int(word.get('top') or 0)
        height = max(1, int(word.get('height') or 1))
        placed = False
        for row in rows:
            other_top = row['top']
            other_height = row['height']
            overlap = min(top + height, other_top + other_height) \
                - max(top, other_top)
            if overlap > SAME_LINE * min(height, other_height):
                row['words'].append(word)
                row['top'] = min(row['top'], top)
                row['height'] = max(row['height'], height)
                placed = True
                break
        if not placed:
            rows.append({'top': top, 'height': height, 'words': [word]})
    for row in rows:
        row['words'].sort(key=lambda w: int(w.get('left') or 0))
    rows.sort(key=lambda r: r['top'])
    return rows


def _split(row):
    """One row into the things that are really on it.

    A wide gap between two words is a boundary: "File Edit View" is three
    menus, not a sentence, and a status line is a handful of separate
    facts. Without this a VM's menu bar is one node nobody can move
    through.
    """
    words = row['words']
    if not words:
        return []
    height = max(1, row['height'])
    groups = [[words[0]]]
    for word in words[1:]:
        previous = groups[-1][-1]
        gap = int(word.get('left') or 0) - (int(previous.get('left') or 0)
                                            + int(previous.get('width') or 0))
        if gap > COLUMN_GAP * height:
            groups.append([word])
        else:
            groups[-1].append(word)
    made = []
    for group in groups:
        left = min(int(w.get('left') or 0) for w in group)
        top = min(int(w.get('top') or 0) for w in group)
        right = max(int(w.get('left') or 0) + int(w.get('width') or 0)
                    for w in group)
        bottom = max(int(w.get('top') or 0) + int(w.get('height') or 0)
                     for w in group)
        made.append({'text': ' '.join(_text(w.get('text')) for w in group),
                     'left': left, 'top': top,
                     'width': right - left, 'height': bottom - top})
    return made


def build(reading, highlights=None):
    """``[Node]`` for one reading. ``highlights`` is what looks selected.

    Never raises: it is on the path of a window that is already being read
    with difficulty, and an exception here would take away the only thing
    that window had.
    """
    nodes = []
    try:
        rows = _rows(reading)
    except Exception:                                # noqa: BLE001
        return nodes
    for index, row in enumerate(rows):
        try:
            pieces = _split(row)
        except Exception:                            # noqa: BLE001
            continue
        for column, piece in enumerate(pieces):
            selected = _inside(piece, highlights)
            nodes.append(Node(
                text=piece['text'], left=piece['left'], top=piece['top'],
                width=piece['width'], height=piece['height'],
                role=ROLE_SELECTED if selected else
                (ROLE_ROW if len(pieces) > 1 else ROLE_TEXT),
                selected=selected, line=index, column=column))
    with _LOCK:
        _counted['built'] += 1
        _counted['nodes'] += len(nodes)
        _counted['highlighted'] += sum(1 for n in nodes if n.selected)
    return nodes


def _inside(piece, highlights):
    """Whether this piece of text sits in one of the highlighted areas."""
    if not highlights:
        return False
    x = piece['left'] + piece['width'] // 2
    y = piece['top'] + piece['height'] // 2
    for left, top, width, height in highlights:
        if left <= x <= left + width and top <= y <= top + height:
            return True
    return False


# --------------------------------------------------------------------------- #
# What is highlighted
# --------------------------------------------------------------------------- #
def highlights(image, rows=None):
    """Where the background is markedly unlike the window's own.

    ``image`` is anything with ``getpixel`` and ``size`` - a PIL image is
    what the capture gives, and nothing here needs more than those two.

    **This is the whole of "what is selected" in a drawn window.** Nothing
    in a picture says which menu entry the arrows are on; the only thing
    that does is that its background is inverted. So the window's own
    background is taken as the commonest colour along the left edge - the
    margin, which is background nearly everywhere - and a row whose middle
    is far from it is reported.

    ``[]`` when it cannot be told, which is an honest answer and leaves
    every node plain rather than guessing at one.
    """
    try:
        width, height = image.size
    except Exception:                                # noqa: BLE001
        return []
    if width < 8 or height < 8:
        return []
    try:
        ground = _background(image, width, height)
    except Exception:                                # noqa: BLE001
        return []
    if ground is None:
        return []
    found = []
    step = max(1, height // 200)
    run = None
    for y in range(0, height, step):
        try:
            different = _row_differs(image, width, y, ground)
        except Exception:                            # noqa: BLE001
            different = False
        if different and run is None:
            run = y
        elif not different and run is not None:
            if y - run >= 4:                         # a line, not a speck
                found.append((0, run, width, y - run))
            run = None
    if run is not None and height - run >= 4:
        found.append((0, run, width, height - run))
    return found


def _background(image, width, height):
    """The window's own background: the commonest colour down its edges.

    The left margin rather than the whole picture, because the whole
    picture of a terminal is mostly text and the commonest colour there is
    still the background - but on a picture that is mostly one big
    highlighted panel it is not, and the margin is right in both.
    """
    seen = {}
    step = max(1, height // 100)
    for y in range(0, height, step):
        for x in (1, 2, width - 2, width - 3):
            if x < 0 or x >= width:
                continue
            try:
                pixel = image.getpixel((x, y))
            except Exception:                        # noqa: BLE001
                continue
            colour = _rgb(pixel)
            if colour is None:
                continue
            seen[colour] = seen.get(colour, 0) + 1
    if not seen:
        return None
    return max(seen.items(), key=lambda pair: pair[1])[0]


def _row_differs(image, width, y, ground):
    """Whether this row of pixels is on a different background.

    Sampled rather than walked: a dozen points across a row answers the
    question, and walking every pixel of a 2560-wide screen for every row
    is a second of somebody's reader.
    """
    unlike = 0
    looked = 0
    for index in range(12):
        x = int(width * (index + 0.5) / 12)
        if x >= width:
            continue
        try:
            colour = _rgb(image.getpixel((x, y)))
        except Exception:                            # noqa: BLE001
            continue
        if colour is None:
            continue
        looked += 1
        if _distance(colour, ground) > HIGHLIGHT_DIFFERENCE:
            unlike += 1
    if looked < 6:
        return False
    # Most of the row, not one dark letter on it.
    return unlike >= looked * 0.7


def _rgb(pixel):
    if isinstance(pixel, (tuple, list)) and len(pixel) >= 3:
        return (int(pixel[0]), int(pixel[1]), int(pixel[2]))
    if isinstance(pixel, int):
        return (pixel, pixel, pixel)
    return None


def _distance(one, other):
    return (abs(one[0] - other[0]) + abs(one[1] - other[1])
            + abs(one[2] - other[2]))


# --------------------------------------------------------------------------- #
# What changed
# --------------------------------------------------------------------------- #
def changed(hwnd, nodes):
    """``([new], [gone])`` against the last reading of this window.

    A screen re-read from the top on every poll is a reader nobody can
    use. What somebody watching a virtual machine wants is the line that
    has just appeared, which is this.
    """
    key = int(hwnd or 0)
    with _LOCK:
        before = _last.get(key) or []
        _last[key] = list(nodes)
        if len(_last) > 16:
            # A handle is reused as freely as any other.
            for gone_key in list(_last)[:-8]:
                if gone_key != key:
                    _last.pop(gone_key, None)
    was = {node.key() for node in before}
    now = {node.key() for node in nodes}
    new = [node for node in nodes if node.key() not in was]
    gone = [node for node in before if node.key() not in now]
    if new or gone:
        with _LOCK:
            _counted['changes'] += 1
    return new, gone


def forget(hwnd=0):
    with _LOCK:
        if hwnd:
            _last.pop(int(hwnd), None)
        else:
            _last.clear()
            for name in _counted:
                _counted[name] = 0


# --------------------------------------------------------------------------- #
# Saying it
# --------------------------------------------------------------------------- #
def describe(node):
    """``[(text, voice)]`` for one node, in this add-on's own classes."""
    if node is None:
        return []
    parts = [(node.text, 'name')]
    if node.selected:
        # Translators: said about a line of a drawn window that is
        # highlighted - the menu entry the arrows are on, the selected file.
        parts.append((_('selected'), 'state'))
    return parts


def line_of(nodes, index):
    """Everything on one row, joined - what a review cursor reads."""
    said = [node.text for node in nodes if node.line == index]
    return ' '.join(one for one in said if one)


def selected_in(nodes):
    """The nodes that look selected, which in a drawn window is the point."""
    return [node for node in nodes if node.selected]


def report():
    with _LOCK:
        found = dict(_counted)
    found['windows_remembered'] = len(_last)
    return found


# --------------------------------------------------------------------------- #
# What CHANGED, which on a screen with no accessibility is what a key did
# --------------------------------------------------------------------------- #
"""`highlights` above finds a whole ROW whose background is unlike the
window's own, which is what a menu and a list look like and is the wrong
question for a screen.

**Measured on a real Windows 95 guest**: the biggest run of "unlike the
background" on that desktop is the TASKBAR - a grey band across the
bottom of a teal screen - so arrowing between desktop icons was answered
"Start", every time, because the taskbar is the most highlighted-looking
thing there and it never moves.

A screen needs the other question: **what changed**. Pressing Down on a
desktop changes exactly two small places - the label that lost the
selection and the one that gained it - and nothing else. That is
independent of the theme, the language, the layout and of whether the
selection is drawn as an inverted background at all, which is what makes
it the right primary method for a guest, a game and an installer alike.

Pixels are read through the same `getpixel` everything else here uses, in
BLOCKS: a whole-picture comparison is a million reads in Python and this
runs on a keystroke. A block is sampled at nine points, which is enough
to notice a label being inverted and cheap enough to do on every key.
"""

#: How big a block is. Small enough that one icon's label is several
#: blocks and two neighbouring icons are not one, large enough that a
#: 640x480 screen is 1 200 blocks rather than 300 000 pixels.
BLOCK = 16

#: How far apart two block samples must be to count as changed. Below
#: this is the compression noise a virtual display puts on a still
#: picture.
BLOCK_DIFFERENCE = 12

#: Blocks nearer than this to one another belong to the same thing - a
#: label and the icon above it, a word and the word beside it.
JOIN = 2


def fingerprint(image, width=0, height=0, block=BLOCK):
    """The picture as ``{(bx, by): (red, green, blue)}``, one per block.

    Cheap on purpose: nine samples a block, which is 10 800 reads for a
    640x480 screen - a few milliseconds, on a key press.
    """
    try:
        if not width or not height:
            width, height = image.size
    except Exception:                                # noqa: BLE001
        return {}
    found = {}
    if width < block or height < block:
        return found
    step = max(1, block // 3)
    for top in range(0, height - block + 1, block):
        for left in range(0, width - block + 1, block):
            red = green = blue = count = 0
            for y in range(top, top + block, step):
                for x in range(left, left + block, step):
                    try:
                        pixel = image.getpixel((x, y))
                    except Exception:                # noqa: BLE001
                        continue
                    colour = _rgb(pixel)
                    if colour is None:
                        continue
                    red += colour[0]
                    green += colour[1]
                    blue += colour[2]
                    count += 1
            if count:
                found[(left // block, top // block)] = (
                    red // count, green // count, blue // count)
    return found


def changed_blocks(before, after, difference=BLOCK_DIFFERENCE):
    """Which blocks are not what they were. ``set()`` for none."""
    if not before or not after:
        return set()
    moved = set()
    for where, colour in after.items():
        was = before.get(where)
        if was is None:
            continue
        if _distance(was, colour) >= difference:
            moved.add(where)
    return moved


def regions_of(blocks, block=BLOCK, join=JOIN):
    """The changed blocks grouped into rectangles, biggest first.

    ``[(left, top, width, height, blocks)]`` in the PICTURE's own pixels.
    Grouped because a label that has just been selected is a dozen
    neighbouring blocks and saying each of them would be saying nothing.
    """
    if not blocks:
        return []
    left = set(blocks)
    found = []
    while left:
        seed = left.pop()
        group = [seed]
        edge = [seed]
        while edge:
            bx, by = edge.pop()
            for dx in range(-join, join + 1):
                for dy in range(-join, join + 1):
                    near = (bx + dx, by + dy)
                    if near in left:
                        left.discard(near)
                        group.append(near)
                        edge.append(near)
        xs = [one[0] for one in group]
        ys = [one[1] for one in group]
        found.append((min(xs) * block, min(ys) * block,
                      (max(xs) - min(xs) + 1) * block,
                      (max(ys) - min(ys) + 1) * block, len(group)))
    found.sort(key=lambda one: -one[4])
    return found


def unlikeness(fingerprint_now, region, ground, block=BLOCK):
    """How unlike the window's own background that region now is.

    **This is what tells the two changed places apart.** Moving a
    selection changes two things: the one that LOST it now looks like the
    background, and the one that GAINED it does not. So the answer to
    "what did the key move onto" is the changed region that is furthest
    from the background, not the biggest one.
    """
    if not fingerprint_now or ground is None:
        return 0
    left, top, width, height = region[0], region[1], region[2], region[3]
    worst = 0
    for by in range(top // block, (top + height) // block):
        for bx in range(left // block, (left + width) // block):
            colour = fingerprint_now.get((bx, by))
            if colour is None:
                continue
            worst = max(worst, _distance(colour, ground))
    return worst
