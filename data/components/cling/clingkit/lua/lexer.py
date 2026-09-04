# -*- coding: utf-8 -*-
"""Lua, tokenised.

Cling carries its own Lua because the alternative is worse in both directions:
a system-wide interpreter that a user of an accessible desktop should not have
to install, or a native binding whose wheel has to match the exact Python that
Titan happens to be frozen against.  Everything Lua-shaped in Cling lives
inside the Cling component - this lexer, the parser beside it and the
interpreter under them - so an application that ships `main.lua` runs on a
machine with no Lua anywhere on it.

Lua 5.1's lexical rules, which is what applications of this kind are written
against: long strings and long comments with any number of `=` in the
brackets, decimal and hexadecimal numbers, and `--` to the end of the line.
"""


class LuaSyntaxError(SyntaxError):
    """A source file that is not Lua. Carries the line it went wrong on."""

    def __init__(self, message, line=0, chunk=''):
        prefix = '%s:%d: ' % (chunk or 'chunk', line) if line else ''
        super().__init__(prefix + message)
        self.line = line


KEYWORDS = frozenset("""
and break do else elseif end false for function if in local nil not or
repeat return then true until while
""".split())

#: Longest first, so `...` is never read as `..` and `==` never as `=`.
SYMBOLS = ('...', '..', '==', '~=', '<=', '>=', '::',
           '+', '-', '*', '/', '%', '^', '#', '<', '>', '=',
           '(', ')', '{', '}', '[', ']', ';', ':', ',', '.')

_ESCAPES = {'a': '\a', 'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r',
            't': '\t', 'v': '\v', '\\': '\\', '"': '"', "'": "'", '\n': '\n'}


class Token(object):
    __slots__ = ('kind', 'value', 'line')

    def __init__(self, kind, value, line):
        self.kind = kind          # name / number / string / keyword / symbol / eof
        self.value = value
        self.line = line

    def __repr__(self):                                  # pragma: no cover
        return '<%s %r@%d>' % (self.kind, self.value, self.line)


def tokenise(source, chunk='chunk'):
    tokens = []
    index = 0
    line = 1
    length = len(source)

    def fail(message):
        raise LuaSyntaxError(message, line, chunk)

    if source.startswith('#'):                       # a shebang line is skipped
        end = source.find('\n')
        index = length if end < 0 else end

    while index < length:
        char = source[index]

        if char == '\n':
            line += 1
            index += 1
            continue
        if char in ' \t\r\f\v':
            index += 1
            continue

        if source.startswith('--', index):
            index += 2
            level = _long_bracket_level(source, index)
            if level is not None:
                text, index, line = _read_long(source, index, level, line, fail)
                continue
            end = source.find('\n', index)
            index = length if end < 0 else end
            continue

        level = _long_bracket_level(source, index)
        if level is not None:
            start_line = line
            text, index, line = _read_long(source, index, level, line, fail)
            tokens.append(Token('string', text, start_line))
            continue

        if char in '"\'':
            start_line = line
            text, index, line = _read_string(source, index, line, fail)
            tokens.append(Token('string', text, start_line))
            continue

        if char.isdigit() or (char == '.' and index + 1 < length
                              and source[index + 1].isdigit()):
            value, index = _read_number(source, index, fail)
            tokens.append(Token('number', value, line))
            continue

        if char.isalpha() or char == '_':
            start = index
            while index < length and (source[index].isalnum() or source[index] == '_'):
                index += 1
            word = source[start:index]
            tokens.append(Token('keyword' if word in KEYWORDS else 'name',
                                word, line))
            continue

        for symbol in SYMBOLS:
            if source.startswith(symbol, index):
                tokens.append(Token('symbol', symbol, line))
                index += len(symbol)
                break
        else:
            fail('unexpected character %r' % char)

    tokens.append(Token('eof', None, line))
    return tokens


def _long_bracket_level(source, index):
    """`[[` is level 0, `[==[` is level 2; None when this is not one."""
    if index >= len(source) or source[index] != '[':
        return None
    probe = index + 1
    level = 0
    while probe < len(source) and source[probe] == '=':
        level += 1
        probe += 1
    if probe < len(source) and source[probe] == '[':
        return level
    return None


def _read_long(source, index, level, line, fail):
    opening = '[' + '=' * level + '['
    closing = ']' + '=' * level + ']'
    index += len(opening)
    if source.startswith('\n', index):               # a leading newline is dropped
        index += 1
        line += 1
    end = source.find(closing, index)
    if end < 0:
        fail('unfinished long string or comment')
    text = source[index:end]
    line += text.count('\n')
    return text, end + len(closing), line


def _read_string(source, index, line, fail):
    quote = source[index]
    index += 1
    out = []
    length = len(source)
    while True:
        if index >= length:
            fail('unfinished string')
        char = source[index]
        if char == quote:
            return ''.join(out), index + 1, line
        if char == '\n':
            fail('unfinished string')
        if char != '\\':
            out.append(char)
            index += 1
            continue
        index += 1
        if index >= length:
            fail('unfinished string')
        following = source[index]
        if following == '\n':
            out.append('\n')
            line += 1
            index += 1
        elif following.isdigit():
            digits = ''
            while index < length and source[index].isdigit() and len(digits) < 3:
                digits += source[index]
                index += 1
            out.append(chr(int(digits) & 0xFF))
        elif following == 'x':
            index += 1
            digits = ''
            while index < length and len(digits) < 2 \
                    and source[index] in '0123456789abcdefABCDEF':
                digits += source[index]
                index += 1
            out.append(chr(int(digits or '0', 16)))
        else:
            out.append(_ESCAPES.get(following, following))
            index += 1


def _read_number(source, index, fail):
    length = len(source)
    start = index
    if source.startswith(('0x', '0X'), index):
        index += 2
        while index < length and source[index] in '0123456789abcdefABCDEF':
            index += 1
        try:
            return int(source[start + 2:index], 16), index
        except ValueError:
            fail('malformed number')
    seen_dot = seen_exponent = False
    while index < length:
        char = source[index]
        if char.isdigit():
            index += 1
        elif char == '.' and not seen_dot and not seen_exponent:
            seen_dot = True
            index += 1
        elif char in 'eE' and not seen_exponent:
            seen_exponent = True
            index += 1
            if index < length and source[index] in '+-':
                index += 1
        else:
            break
    raw = source[start:index]
    try:
        return (float(raw) if (seen_dot or seen_exponent) else int(raw)), index
    except ValueError:
        fail('malformed number %r' % raw)
