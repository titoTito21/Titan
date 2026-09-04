# -*- coding: utf-8 -*-
"""A Klango topology is a board with a place for every field, in sound.

`3x3.top` does not describe a picture: it gives every one of the nine fields a
position in front of the listener (`x` across, `y` away, `z` up) and a
frequency shift (`f`, in cents) that makes the rows tell each other apart even
in mono.  That is the whole of what makes a blind player able to aim - the
board is not drawn, it is *heard* - so Cling keeps those numbers and converts
them once, here, into the units Titan's own audio takes.

The conversion is deliberately in one place.  Titan says pan 0.0 (left) to 1.0
(right) in `sound.py`, -1 to 1 nearly everywhere else, and degrees of azimuth
in `spatial_audio`; a field that knows its own `pan` and `azimuth` cannot be
put through the wrong one by an engine that only meant to play a sound.
"""

import math
import os

from . import klango_lua

#: Beyond this the board is being read as a wall of sound rather than a place.
MAX_AZIMUTH = 80.0
#: How much of the far row's loudness is lost to distance.
DISTANCE_ATTENUATION = 0.45


class Field(object):
    """One place on the board, in every unit something might ask for it in."""

    __slots__ = ('index', 'column', 'row', 'layer', 'x', 'y', 'z', 'cents',
                 'pan', 'azimuth', 'elevation', 'gain')

    def __init__(self, index, column, row, layer, x, y, z, cents):
        self.index = index
        self.column = column
        self.row = row
        self.layer = layer
        self.x = x
        self.y = y
        self.z = z
        self.cents = cents
        self.pan = 0.0            # -1 (left) .. 1 (right)
        self.azimuth = 0.0        # degrees, negative is left
        self.elevation = 0.0      # degrees
        self.gain = 1.0

    @property
    def pan01(self):
        """The same place in `sound.py`'s units: 0.0 left, 0.5 centre, 1.0 right.

        Titan's mixer has always taken 0..1 while everything the user writes
        says -1..1, and handing one straight to the other is what put the
        shell's own sounds in the left speaker; a field converts itself so no
        engine has to remember.
        """
        return (self.pan + 1.0) / 2.0

    @property
    def semitones(self):
        """`f` as the pitch offset Titan's speech takes (-10..10)."""
        return max(-10.0, min(10.0, self.cents / 100.0))

    def __repr__(self):                                  # pragma: no cover
        return '<Field %d col %d row %d pan %.2f>' % (
            self.index, self.column, self.row, self.pan)


class Board(object):
    """The fields of one topology, addressable by index or by column and row."""

    def __init__(self, columns, rows, layers=1, fields=None, name=''):
        self.name = name
        self.columns = max(1, int(columns))
        self.rows = max(1, int(rows))
        self.layers = max(1, int(layers))
        self.fields = fields or []

    # ------------------------------------------------------------ building
    @classmethod
    def grid(cls, columns, rows, layers=1, name=''):
        """A board nobody described: an even grid in front of the listener.

        This is what a level with no `.top` file gets.  It is not a guess about
        the application's intent - it is the honest reading of "N fields in a
        row and M rows", spread across the stereo image the way the shipped
        topologies do.
        """
        board = cls(columns, rows, layers, name=name)
        index = 1
        for column in range(1, board.columns + 1):
            for row in range(1, board.rows + 1):
                for layer in range(1, board.layers + 1):
                    x = 0.0 if board.columns == 1 else \
                        -1.0 + 2.0 * (column - 1) / (board.columns - 1)
                    y = 0.25 + 0.75 * (row - 1) / max(1, board.rows - 1)
                    z = 0.0 if board.layers == 1 else \
                        (layer - 1) / float(board.layers - 1)
                    board.fields.append(
                        Field(index, column, row, layer, x, y, z,
                              -100.0 * (row - 1)))
                    index += 1
        board._place()
        return board

    @classmethod
    def from_table(cls, table, name=''):
        """A board from a parsed `Topology = { size = ..., coords = ... }`."""
        size = table.get('size') or {}
        columns = int(size.get('x', 0) or 0)
        rows = int(size.get('y', 0) or 0)
        layers = int(size.get('z', 1) or 1)
        coords = table.get('coords') or {}
        if not columns or not rows:
            columns = columns or len(coords) or 1
            rows = rows or len(coords.get(1) or {}) or 1
        board = cls(columns, rows, layers, name=name)
        index = 1
        for column in range(1, board.columns + 1):
            by_row = coords.get(column) or {}
            for row in range(1, board.rows + 1):
                by_layer = by_row.get(row) or {}
                for layer in range(1, board.layers + 1):
                    point = by_layer.get(layer)
                    if not isinstance(point, dict):
                        # A hole in somebody else's table is a field with no
                        # place, not a board that cannot be built: it is put
                        # where the even grid would have put it.
                        point = {'x': 0.0 if board.columns == 1 else
                                 -1.0 + 2.0 * (column - 1) / (board.columns - 1),
                                 'y': 0.25 + 0.75 * (row - 1) /
                                 max(1, board.rows - 1),
                                 'z': 0.0, 'f': -100.0 * (row - 1)}
                    board.fields.append(
                        Field(index, column, row, layer,
                              float(point.get('x', 0.0) or 0.0),
                              float(point.get('y', 0.0) or 0.0),
                              float(point.get('z', 0.0) or 0.0),
                              float(point.get('f', 0.0) or 0.0)))
                    index += 1
        board._place()
        return board

    @classmethod
    def from_file(cls, path):
        table = klango_lua.read_file(path, 'Topology')
        if not isinstance(table, dict):
            raise klango_lua.LuaError('%s does not hold a topology' % path)
        return cls.from_table(table, os.path.splitext(os.path.basename(path))[0])

    # ------------------------------------------------------------ geometry
    def _place(self):
        """Turn the topology's own numbers into Titan's units, once."""
        if not self.fields:
            return
        widest = max(abs(field.x) for field in self.fields) or 1.0
        nearest = min(field.y for field in self.fields)
        furthest = max(field.y for field in self.fields)
        depth = (furthest - nearest) or 1.0
        highest = max(abs(field.z) for field in self.fields)
        for field in self.fields:
            field.pan = max(-1.0, min(1.0, field.x / widest))
            field.azimuth = field.pan * MAX_AZIMUTH
            # `z` is height where a topology uses it; where every field is on
            # the ground (which is every topology Klango shipped) the rows are
            # lifted a little instead, so that "further away" is somewhere the
            # ear can put it rather than only quieter.
            if highest > 0.0001:
                field.elevation = 45.0 * (field.z / highest)
            else:
                field.elevation = 25.0 * ((field.y - nearest) / depth)
            field.gain = 1.0 - DISTANCE_ATTENUATION * ((field.y - nearest) / depth)

    # ------------------------------------------------------------- lookups
    def __len__(self):
        return len(self.fields)

    def __iter__(self):
        return iter(self.fields)

    def at(self, column, row, layer=1):
        for field in self.fields:
            if field.column == column and field.row == row and field.layer == layer:
                return field
        return None

    def by_index(self, index):
        if 1 <= index <= len(self.fields):
            return self.fields[index - 1]
        return None

    def step(self, field, columns=0, rows=0, layers=0, wrap=False):
        """The field one move away, or None when that is off the board.

        `wrap` is what the applications that let the player run round the edge
        ask for; without it walking into the wall returns None and the engine
        plays the border sound, which is what Klango's own boards do.
        """
        column = field.column + columns
        row = field.row + rows
        layer = field.layer + layers
        if wrap:
            column = (column - 1) % self.columns + 1
            row = (row - 1) % self.rows + 1
            layer = (layer - 1) % self.layers + 1
        if not (1 <= column <= self.columns and 1 <= row <= self.rows
                and 1 <= layer <= self.layers):
            return None
        return self.at(column, row, layer)


def load(skin, name, columns=0, rows=0):
    """The named topology from a skin, or an even grid when it has none."""
    if name:
        path = skin.topology_file(str(name))
        if path:
            try:
                return Board.from_file(path)
            except (klango_lua.LuaError, OSError):
                pass
    if columns and rows:
        return Board.grid(columns, rows, name=str(name or ''))
    # A count with no shape ("fields = 9") is squared off, which is what every
    # Klango board that gives one turns out to be.
    total = max(1, int(columns or rows or 1))
    side = int(math.sqrt(total))
    while side > 1 and total % side:
        side -= 1
    return Board.grid(max(1, total // max(1, side)), max(1, side),
                      name=str(name or ''))
