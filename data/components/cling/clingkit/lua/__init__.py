# -*- coding: utf-8 -*-
"""Lua for Cling, carried by Cling.

Everything Lua-shaped a Cling application needs is inside this component -
`data/components/cling/cling/lua/` for the interpreter Cling writes itself, and
`data/components/cling/lib/` for a native one dropped in beside it.  Nothing is
taken from the system, from Titan, or from the user's Python: an accessible
desktop cannot ask somebody to install an interpreter before a game will start,
and a native binding pinned to one Python version would break the moment Titan
is frozen against another.

Two backends, and the choice is made once:

* **native** - `lupa`, if it imports.  It is looked for in the component's own
  `lib/` first, so a user who wants the speed of real Lua drops the wheel there
  and nothing else changes.  Real Lua 5.4, coroutines included.
* **built-in** - the interpreter in this package.  Pure Python, always
  present, and what everything is tested against.

Both are reached through `LuaRuntime`, so an application cannot tell which one
it got - and so a bug that only appears on one of them is a bug in Cling rather
than in the application.
"""

import os
import sys

from .runtime import Interpreter, LuaError, LuaTable, is_true, tostring, tonumber
from .lexer import LuaSyntaxError

#: Where a native interpreter may be dropped in. The component manager already
#: puts this on `sys.path` for a frozen Titan (`libs = lib`); for a source
#: checkout this module puts it there itself, so the two behave the same.
LIB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'lib'))

NATIVE = 'native'
BUILTIN = 'builtin'

_native = None
_native_checked = False


def _load_native():
    global _native, _native_checked
    if _native_checked:
        return _native
    _native_checked = True
    if os.path.isdir(LIB_DIR) and LIB_DIR not in sys.path:
        sys.path.insert(0, LIB_DIR)
    try:
        import lupa                                     # noqa: F401
        _native = lupa
    except Exception:
        _native = None
    return _native


def backend():
    """Which interpreter an application would get: 'native' or 'builtin'."""
    return NATIVE if _load_native() is not None else BUILTIN


def describe():
    """One sentence for the settings window and for `cling.status`."""
    if _load_native() is not None:
        return "Lua: native (lupa), from the component's own lib folder"
    return "Lua: Cling's own interpreter (no native library needed)"


class LuaRuntime(object):
    """One application's Lua: its globals, its modules, its running code."""

    def __init__(self, root='', prefer_native=True):
        self.root = root
        self.native = _load_native() if prefer_native else None
        self._lua = None
        self.interpreter = None
        if self.native is not None:
            try:
                self._lua = self.native.LuaRuntime(unpack_returned_tuples=True,
                                                   register_eval=False)
            except Exception:
                self.native = None
                self._lua = None
        if self._lua is None:
            from .stdlib import build_globals
            self.interpreter = Interpreter(LuaTable(), root)
            build_globals(self.interpreter, root)

    # ------------------------------------------------------------ globals
    def set_global(self, name, value):
        if self._lua is not None:
            self._lua.globals()[name] = value
            return
        self.interpreter.globals.raw_set(name, value)

    def get_global(self, name):
        if self._lua is not None:
            return self._lua.globals()[name]
        return self.interpreter.globals.raw_get(name)

    def table(self, mapping=None):
        """A table the Python side can hand to Lua, on either backend."""
        if self._lua is not None:
            return self._lua.table_from(mapping or {})
        table = LuaTable()
        for key, value in (mapping or {}).items():
            table.raw_set(key, value)
        return table

    # ------------------------------------------------------------- running
    def run(self, source, chunk='chunk'):
        if self._lua is not None:
            return self._lua.execute(source)
        return self.interpreter.run(source, chunk)

    def run_file(self, path):
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            source = handle.read()
        if source[:1] == '﻿':
            source = source[1:]
        return self.run(source, os.path.basename(path))

    def call(self, function, *arguments):
        """Call something Lua gave us, whichever backend made it."""
        if function is None:
            return None
        if self._lua is not None:
            return function(*arguments)
        values = self.interpreter.call_value(function, list(arguments), 0)
        if not values:
            return None
        return values[0] if len(values) == 1 else values

    def call_global(self, name, *arguments):
        function = self.get_global(name)
        if function is None:
            return None
        return self.call(function, *arguments)

    def has_global(self, name):
        return self.get_global(name) is not None


__all__ = ['LuaRuntime', 'LuaError', 'LuaSyntaxError', 'LuaTable', 'backend',
           'describe', 'is_true', 'tostring', 'tonumber', 'NATIVE', 'BUILTIN']
