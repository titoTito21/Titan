# -*- coding: utf-8 -*-
"""Reading a serialised Lua table back, as data.

Klango writes its settings and saved games with `k_Serialize`, which produces
Lua's own table syntax, and reads them back with `k_Unserialize`. Klango can
afford to read one by running it - it has an interpreter and the file is its
own. Cling will not: the text came out of a file on disk that anything may have
edited since, and running it would mean a saved game can do whatever Lua can.

So it goes through the same parser Cling reads `.lev` and `.top` with, which
understands table literals and nothing else.
"""

from .. import klango_lua


def read(text, make_table):
    """A serialised Lua value as a Lua value again, or nil."""
    text = str(text or '').strip()
    if not text:
        return None
    try:
        value = klango_lua.parse_value(text)
    except klango_lua.LuaError:
        return None
    return _to_lua(value, make_table)


def _to_lua(value, make_table, depth=0):
    if depth > 30 or not isinstance(value, dict):
        return value
    table = make_table({})
    for key, item in value.items():
        table.raw_set(key, _to_lua(item, make_table, depth + 1))
    return table
