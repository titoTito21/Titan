# -*- coding: utf-8 -*-
"""The Klango data files are Lua, and only Lua tables.

A `.lev`, a `.top`, a `kni.txt` written the long way - every one of them is a
single Lua assignment whose right-hand side is a table literal, with `--`
comments and trailing commas.  Klango itself embeds a whole Lua interpreter to
read them; Cling does not, and must not: these files come from wherever the
user got the application, and running them as a program would mean that a
level file can open a socket.  They are DATA, so they are parsed as data.

What is supported is exactly what the format uses: nested tables, `name =`
keys, `[1] =` keys, positional entries, numbers (including the negative and
the fractional), single- and double-quoted strings, `true`/`false`/`nil`, line
comments and long comments.  Anything else - a function, a concatenation, an
arithmetic expression - is a file this parser refuses rather than half-reads,
because a level silently missing its `hit_target` is a game that cannot be
finished and never says why.
"""


class LuaError(ValueError):
    """A file that is not the table literal Cling can read. Carries a line."""

    def __init__(self, message, line=0):
        super().__init__("line %d: %s" % (line, message) if line else message)
        self.line = line


_PUNCTUATION = '{}[]=,;'


class _Token(object):
    __slots__ = ('kind', 'value', 'line')

    def __init__(self, kind, value, line):
        self.kind = kind
        self.value = value
        self.line = line

    def __repr__(self):                                  # pragma: no cover
        return '<%s %r line %d>' % (self.kind, self.value, self.line)


def tokenise(text):
    """Turn a Klango data file into tokens, comments and whitespace gone."""
    tokens = []
    index = 0
    line = 1
    length = len(text)
    while index < length:
        char = text[index]

        if char == '\n':
            line += 1
            index += 1
            continue
        if char in ' \t\r\f\v':
            index += 1
            continue

        # Comments: `--` to the end of the line, or `--[[ ... ]]`.
        if text.startswith('--', index):
            if text.startswith('--[[', index):
                end = text.find(']]', index + 4)
                if end < 0:
                    raise LuaError("a long comment that is never closed", line)
                line += text.count('\n', index, end)
                index = end + 2
                continue
            end = text.find('\n', index)
            index = length if end < 0 else end
            continue

        if char in '"\'':
            value, index, line = _read_string(text, index, line)
            tokens.append(_Token('string', value, line))
            continue

        if char.isdigit() or (char in '+-' and index + 1 < length
                              and (text[index + 1].isdigit() or text[index + 1] == '.')) \
                or (char == '.' and index + 1 < length and text[index + 1].isdigit()):
            value, index = _read_number(text, index, line)
            tokens.append(_Token('number', value, line))
            continue

        if char.isalpha() or char == '_':
            start = index
            while index < length and (text[index].isalnum() or text[index] == '_'):
                index += 1
            tokens.append(_Token('name', text[start:index], line))
            continue

        if char in _PUNCTUATION:
            tokens.append(_Token(char, char, line))
            index += 1
            continue

        raise LuaError("%r is not something a Klango data file may contain" % char, line)

    tokens.append(_Token('eof', None, line))
    return tokens


def _read_string(text, index, line):
    quote = text[index]
    index += 1
    out = []
    escapes = {'n': '\n', 't': '\t', 'r': '\r', 'a': '\a', 'b': '\b',
               'f': '\f', 'v': '\v', '\\': '\\', '"': '"', "'": "'"}
    while True:
        if index >= len(text):
            raise LuaError("a string that is never closed", line)
        char = text[index]
        if char == quote:
            return ''.join(out), index + 1, line
        if char == '\n':
            raise LuaError("a string broken across two lines", line)
        if char == '\\':
            index += 1
            if index >= len(text):
                raise LuaError("a string that is never closed", line)
            following = text[index]
            out.append(escapes.get(following, following))
            index += 1
            continue
        out.append(char)
        index += 1


def _read_number(text, index, line):
    start = index
    length = len(text)
    if text[index] in '+-':
        index += 1
    if text.startswith(('0x', '0X'), index):
        index += 2
        while index < length and text[index] in '0123456789abcdefABCDEF':
            index += 1
        return int(text[start:index], 16), index
    seen_dot = False
    seen_exponent = False
    while index < length:
        char = text[index]
        if char.isdigit():
            index += 1
        elif char == '.' and not seen_dot and not seen_exponent:
            seen_dot = True
            index += 1
        elif char in 'eE' and not seen_exponent and index > start:
            seen_exponent = True
            index += 1
            if index < length and text[index] in '+-':
                index += 1
        else:
            break
    raw = text[start:index]
    try:
        return (float(raw) if (seen_dot or seen_exponent) else int(raw)), index
    except ValueError:
        raise LuaError("%r is not a number" % raw, line)


class _Parser(object):
    def __init__(self, tokens):
        self.tokens = tokens
        self.position = 0

    def peek(self):
        return self.tokens[self.position]

    def take(self, kind=None):
        token = self.tokens[self.position]
        if kind is not None and token.kind != kind:
            raise LuaError("expected %s, found %r" % (kind, token.value), token.line)
        self.position += 1
        return token

    def accept(self, kind):
        if self.tokens[self.position].kind == kind:
            self.position += 1
            return True
        return False

    # -------------------------------------------------------------- values
    def value(self):
        token = self.peek()
        if token.kind == '{':
            return self.table()
        if token.kind in ('string', 'number'):
            self.take()
            return token.value
        if token.kind == 'name':
            self.take()
            if token.value == 'true':
                return True
            if token.value == 'false':
                return False
            if token.value == 'nil':
                return None
            # A bare word used as a value is how these files spell an enum
            # ("topology = default"); keeping it as a string is what the
            # readers already expect of the quoted spelling.
            return token.value
        raise LuaError("expected a value, found %r" % (token.value,), token.line)

    def table(self):
        opening = self.take('{')
        out = {}
        position = 1
        while True:
            if self.accept('}'):
                return out
            token = self.peek()
            if token.kind == 'eof':
                raise LuaError("a table opened here is never closed", opening.line)

            if token.kind == '[':
                self.take('[')
                key = self.value()
                self.take(']')
                self.take('=')
                out[key] = self.value()
            elif token.kind == 'name' and self.tokens[self.position + 1].kind == '=':
                self.take('name')
                self.take('=')
                out[token.value] = self.value()
            else:
                out[position] = self.value()
                position += 1

            if not (self.accept(',') or self.accept(';')):
                self.take('}')
                return out


def parse_value(text):
    """Parse one table literal (or scalar) and return it."""
    parser = _Parser(tokenise(text))
    value = parser.value()
    if parser.peek().kind != 'eof':
        raise LuaError("more than one value in the file", parser.peek().line)
    return value


def parse_chunk(text):
    """Parse a file of `Name = <value>` assignments into a dict.

    Klango's own files hold exactly one (`Level = {...}`, `Topology = {...}`),
    but reading them all is what lets a skin put two in one file without Cling
    having to care which.
    """
    parser = _Parser(tokenise(text))
    out = {}
    while parser.peek().kind != 'eof':
        name = parser.take('name')
        parser.take('=')
        out[name.value] = parser.value()
        parser.accept(';')
    return out


def read_file(path, name=None):
    """Read a Klango data file; return the named assignment, or the only one.

    `name` is what the file is expected to hold (`Level`, `Topology`). It is
    matched case-insensitively, because the files in the wild are not
    consistent about it, and when the file holds exactly one assignment that
    one is returned whatever it is called - a level that spells its table
    `level` is still a level.
    """
    from . import textio
    text = textio.read(path)
    chunk = parse_chunk(text)
    if not chunk:
        raise LuaError("%s holds nothing" % path)
    if name:
        for key, value in chunk.items():
            if key.lower() == name.lower():
                return value
    if len(chunk) == 1:
        return next(iter(chunk.values()))
    raise LuaError("%s does not hold a %s" % (path, name or 'value'))


def as_list(table):
    """The positional part of a parsed table, in order, as a list."""
    if not isinstance(table, dict):
        return []
    out = []
    index = 1
    while index in table:
        out.append(table[index])
        index += 1
    return out
