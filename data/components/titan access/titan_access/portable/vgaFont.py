# -*- coding: utf-8 -*-
"""The real VGA glyphs, read out of the font Windows itself ships.

A guest in a text mode is not a picture of words - it is 80 by 25 CELLS, each
one of 256 fixed shapes, and every one of those shapes has been the same
since 1987. So such a screen can be read EXACTLY, by comparing each cell with
the glyph it is: no model, no request to anybody's provider, no guessing, and
the words come back with the colour they were drawn in, which is what says
which row an installer has highlighted.

What that needs is the glyph table, and there are two wrong ways to get it.
Writing 4096 bytes of font into a source file is four thousand chances to be
wrong about somebody else's screen; asking the guest is impossible, since the
VGA font lives in the emulated adapter's memory and not in the guest's RAM
(measured: guest physical 0xB8000 in a running machine's `.vmem` is a hole of
zeros, because the VGA aperture is device memory).

The right way is that **Windows already has the font**:
`%WINDIR%\\Fonts\\dosapp.fon` is the Terminal font, and inside it are real
FNT resources - 4x6, 5x12, 6x8, 7x12, 10x18 and 12x16 on this machine - each
a full 256-glyph CP437 set. It is parsed here, which is a documented format
from 1990 and about thirty lines.
"""

import os
import struct
import threading

#: Where the DOS application fonts are. `dosapp.fon` is the one with the
#: whole CP437 set at several sizes; the code-page variants beside it
#: (`app852.fon` and its kind) are the same shape for another alphabet.
FONTS = (
    os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts', 'dosapp.fon'),
    os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts', 'vgaoem.fon'),
)

#: A glyph is looked for at these sizes, in this order: the cell a text mode
#: really uses is 9x16 or 8x16 on a VGA, and the fonts Windows ships are
#: 12x16 and 8x8 - so what matters is that the size asked for is THERE, and
#: the caller says which size the screen it is looking at has.
_LOCK = threading.RLock()
_kept = {}
_state = {'files': 0, 'sizes': (), 'why': ''}


def report():
    # Asked rather than remembered: read live, this answered `sizes: []` on a
    # machine with seven of them, because nothing had looked yet - which is
    # the same fault as a capture that reports "not found" for "never asked".
    # Reading the file is a few milliseconds and the answer is kept.
    try:
        sizes()
    except Exception:                                # noqa: BLE001
        pass
    with _LOCK:
        found = dict(_state)
    found['kept'] = sorted('%dx%d' % key for key in _kept if _kept[key])
    return found


def _resources(raw):
    """Every FNT resource in a `.fon`, as ``(offset, width, height)``.

    A `.fon` is a 16-bit executable and the fonts are resources inside it;
    rather than walking the NE resource table - which is four more things to
    be wrong about - an FNT is recognised by its own header: a version of
    0x0200 or 0x0300 followed by a length that fits in the file.
    """
    found = []
    for at in range(0, max(0, len(raw) - 120)):
        version, size = struct.unpack_from('<HI', raw, at)
        if version not in (0x0200, 0x0300):
            continue
        if size < 100 or at + size > len(raw):
            continue
        width, height = struct.unpack_from('<HH', raw, at + 86)
        if not (1 <= width <= 32 and 1 <= height <= 64):
            continue
        first, last = raw[at + 95], raw[at + 96]
        if last <= first:
            continue
        found.append((at, width, height))
    return found


def _table(raw, at, width, height):
    """One resource as 256 glyphs of ``height`` rows, MSB leftmost.

    A fixed-pitch FNT stores a glyph COLUMN by column - one byte per eight
    pixels across, all of that column's rows together - which is the shape a
    VGA wants and the opposite of what a reader expects.
    """
    first, last = raw[at + 95], raw[at + 96]
    bits_at, = struct.unpack_from('<I', raw, at + 113)
    columns = (width + 7) // 8
    stride = columns
    table = bytearray(256 * height * stride)
    for code in range(256):
        if not (first <= code <= last):
            continue
        start = at + bits_at + (code - first) * columns * height
        if start + columns * height > len(raw):
            continue
        for y in range(height):
            value = 0
            for column in range(columns):
                value = (value << 8) | raw[start + column * height + y]
            value >>= columns * 8 - width          # left aligned in `width`
            value <<= stride * 8 - width           # and again in the bytes
            for byte in range(stride):
                table[(code * height + y) * stride + byte] = (
                    value >> (8 * (stride - 1 - byte))) & 0xFF
    return bytes(table)


def _has_letters(table, width, height):
    """Whether the ordinary letters really have ink in them."""
    if not table:
        return False
    stride = (width + 7) // 8
    for letter in b'AWmo':
        drawn = 0
        for y in range(height):
            at = (letter * height + y) * stride
            for byte in range(stride):
                if at + byte < len(table):
                    drawn += bin(table[at + byte]).count('1')
        if drawn < 8:
            return False
    return True


def sizes():
    """Every cell size this machine has a REAL glyph table for.

    Only the ones `table()` will really answer: a size listed here and
    refused there is the worst kind of answer, and this file has sizes whose
    only resource parses to 256 empty glyphs.
    """
    found = []
    for where in FONTS:
        try:
            with open(where, 'rb') as handle:
                raw = handle.read()
        except Exception:                            # noqa: BLE001
            continue
        for at, width, height in _resources(raw):
            if (width, height) in found:
                continue
            if _has_letters(_table(raw, at, width, height), width, height):
                found.append((width, height))
    with _LOCK:
        _state['sizes'] = tuple(found)
    return found


def table(width, height):
    """The 256-glyph table for that cell size, or None. Read once."""
    key = (int(width), int(height))
    with _LOCK:
        if key in _kept:
            return _kept[key]
    files = 0
    for where in FONTS:
        try:
            with open(where, 'rb') as handle:
                raw = handle.read()
        except Exception:                            # noqa: BLE001
            continue
        files += 1
        for at, wide, tall in _resources(raw):
            if (wide, tall) != key:
                continue
            found = _table(raw, at, wide, tall)
            # **A table with no ink in it is not a table.** A `.fon` holds
            # more than one thing that looks like an FNT header at the size
            # asked for - the first match in this file parses to 256 empty
            # glyphs - and a blank font reads every screen as a screen of
            # spaces, which is the one answer this tier must never give. So
            # the parse is checked against what it is for: the letters have
            # to have something drawn in them.
            if not _has_letters(found, wide, tall):
                continue
            with _LOCK:
                _kept[key] = found
                _state['files'] = files
                _state['why'] = ''
            return found
    with _LOCK:
        _state['files'] = files
        _state['why'] = ('no %d by %d glyphs in %s'
                         % (key[0], key[1],
                            ', '.join(os.path.basename(one) for one in FONTS)))
        _kept[key] = None
    return None


def forget():
    """For the tests."""
    with _LOCK:
        _kept.clear()
        _state.update({'files': 0, 'sizes': (), 'why': ''})
