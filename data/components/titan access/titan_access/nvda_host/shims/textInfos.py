# -*- coding: utf-8 -*-
"""NVDA's `textInfos`: the constants, and a TextInfo over an object's text
that answers what Titan Access can read of it."""

POSITION_FIRST = 'first'
POSITION_LAST = 'last'
POSITION_CARET = 'caret'
POSITION_SELECTION = 'selection'
POSITION_ALL = 'all'
UNIT_CHARACTER = 'character'
UNIT_WORD = 'word'
UNIT_LINE = 'line'
UNIT_SENTENCE = 'sentence'
UNIT_PARAGRAPH = 'paragraph'
UNIT_STORY = 'story'
UNIT_READINGCHUNK = 'readingChunk'


class TextInfo(object):
    def __init__(self, obj, position):
        self.obj = obj
        self.position = position
        self.text = str(getattr(obj, 'value', '') or
                        getattr(obj, 'name', '') or '')

    def copy(self):
        return TextInfo(self.obj, self.position)

    def expand(self, unit):
        pass

    def collapse(self, end=False):
        pass

    def move(self, unit, direction, endPoint=None):
        return 0

    def getTextWithFields(self, formatConfig=None):
        return [self.text]

    @property
    def isCollapsed(self):
        return not self.text


class OffsetsTextInfo(TextInfo):
    pass


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
