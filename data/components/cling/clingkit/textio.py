# -*- coding: utf-8 -*-
"""Reading somebody else's text files, in whatever they were written in.

Most of Klango is UTF-8 and Cling read all of it that way. Most is not all:
**11 of the platform library's 104 Lua files are Windows-1250**, the Polish
code page Klango was written on, and so are texts inside applications.
Reading one of those as UTF-8 with `errors='replace'` puts U+FFFD where every
Polish letter was - which in a comment is invisible, in a string literal is a
word with holes in it that the synthesiser then reads out, and in
`p_radiopresets.lua` is a character the lexer refuses outright, so the module
does not load at all.

So a file is decoded as UTF-8 if it is UTF-8, and as the code page it was
written in if it is not. `latin-1` is last and cannot fail, so there is no
such thing here as a file that cannot be read - only one that is read
imperfectly, which is a far better answer than one that stops an application.
"""

#: In order. UTF-8 first because most of Klango is; `cp1250` next because
#: that is what the rest of it is; `cp1252` for a Western-European
#: application; `latin-1` last because it decodes any byte at all and so
#: guarantees an answer.
ENCODINGS = ('utf-8', 'cp1250', 'cp1252', 'latin-1')

#: What a UTF-8 byte-order mark looks like once decoded.
BOM = '\ufeff'


def decode(raw):
    """Bytes as text, in the first encoding that really fits them.

    Line endings are made `\n` on the way through. That is not tidiness:
    `llib_s4tb.lua` ends its 1961 lines with a bare `\r` and nothing else -
    Mac line endings, in a file from 2008 - and a lexer that treats `\r` as
    whitespace lets the first `--` comment swallow the whole file. It loaded
    without a word of complaint and defined nothing, so the widget it holds
    was missing from every application that started.
    """
    if isinstance(raw, str):
        return _lines(raw)
    if not isinstance(raw, (bytes, bytearray)):
        return ''
    for encoding in ENCODINGS:
        try:
            return _lines(bytes(raw).decode(encoding))
        except (UnicodeDecodeError, LookupError):
            continue
    return _lines(bytes(raw).decode('utf-8', 'replace'))


def _lines(text):
    return text.lstrip(BOM).replace('\r\n', '\n').replace('\r', '\n')


def read(path):
    """One file as text, or '' when it is not there."""
    try:
        with open(path, 'rb') as handle:
            return decode(handle.read())
    except OSError:
        return ''


def read_or_none(path):
    """One file as text, or None - for callers that tell the two apart."""
    try:
        with open(path, 'rb') as handle:
            return decode(handle.read())
    except OSError:
        return None
