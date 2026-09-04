# -*- coding: utf-8 -*-
"""The Lua environment Klango's library expects to find already there.

`llib.lua` does not start from bare Lua: its first statements install a package
loader, cut `string.dump` out, and require `slnunicode` and `json`. So before it
can run at all, the interpreter has to look like the one Klango shipped - a
`package` table with `loaders`, a `debug` table, a `require` that finds the
library's own modules, and `utf8`.

`utf8` is the one that matters most and costs the least: Klango bound Lua 5.1 to
`slnunicode` because Lua strings are bytes and its applications are in every
language there is. Cling's Lua strings are already Python strings, which are
already text, so `utf8` is the ordinary string library under another name -
`utf8.format('%s moles', 'krety')` does the right thing because it never had a
byte problem to solve.
"""


def install(runtime, loader, log=None):
    """Make a runtime look like the one Klango's library was written against."""
    give = runtime.set_global
    get = runtime.get_global
    table = runtime.table

    # ---------------------------------------------------------- packages
    package = table({})
    # Real Lua ships four searchers, and `llib.lua` inserts its own AT
    # POSITION 2 - into an empty table that is an error, not a no-op, so the
    # library stops before it has defined a single `k_` function.
    loaders = table({})
    for slot in range(1, 5):
        _set(loaders, slot, (lambda *_a: None))
    loaded = table({})
    _set(package, 'loaders', loaders)
    _set(package, 'loaded', loaded)
    _set(package, 'path', '')
    _set(package, 'cpath', '')
    give('package', package)

    #: Modules Klango gets from C and Cling gets from Python. A name that is
    #: neither one of these nor a file in the library is reported, not faked:
    #: an application that thinks it has a module it has not got fails later
    #: and further away.
    builtin = {'slnunicode': lambda: _unicode_module(runtime),
               'json': lambda: _json_module(runtime),
               'lpeg': lambda: _lpeg_module(runtime),
               # Windows COM. Klango automates other programs with it;
               # a Cling application has no business doing that.
               'luacom': lambda: table({})}

    def require(name=None, *_rest):
        wanted = str(name or '')
        already = loaded.raw_get(wanted) if hasattr(loaded, 'raw_get') \
            else loaded[wanted]
        if already is not None:
            return already
        maker = builtin.get(wanted)
        if maker is not None:
            module = maker()
            _set(loaded, wanted, module)
            return module
        if loader is not None and loader(wanted.replace('.', '/')):
            value = get(wanted) or True
            _set(loaded, wanted, value)
            return value
        if log is not None:
            log("require: '%s' is not a module Cling has" % wanted)
        _set(loaded, wanted, True)
        return True

    give('require', require)

    # ------------------------------------------------------------- debug
    # `llib.lua` keeps only setfenv and getfenv and throws the rest away.
    # Cling's interpreter has no environments to swap, so these answer in the
    # only way that is not a lie: the function itself, unchanged.
    debug = table({})
    _set(debug, 'setfenv', lambda fn=None, _env=None, *_r: fn)
    _set(debug, 'getfenv', lambda _fn=None, *_r: get('_G'))
    _set(debug, 'traceback', lambda message=None, *_r: str(message or ''))
    give('debug', debug)

    # Lua 5.1's `module()` sets the caller's environment to a new table, and
    # Cling's interpreter has no environments to set. Klango's JSON is the only
    # thing that uses it and Cling supplies its own JSON instead, so this exists
    # to keep a file that calls it from stopping the load - not to pretend the
    # module system is there.
    if get('module') is None:
        give('module', lambda *_a, **_k: None)

    # -------------------------------------------------------------- utf8
    unicode_module = _unicode_module(runtime)
    give('unicode', unicode_module)
    utf8 = unicode_module.raw_get('utf8') if hasattr(unicode_module, 'raw_get') \
        else unicode_module['utf8']
    give('utf8', utf8)

    if get('k_SetEngineVoice') is None:
        give('k_SetEngineVoice', (lambda *_a, **_k: None))

    # Klango's own tracing, which every file calls and nothing here needs.
    for name in ('pr', 'tpr', 'ppr', '_DBG', '_DBG0', '_DBGM', '_DBGE',
                 '_DBGW', '_DBGI', 'dbg', 'trace'):
        if get(name) is None:
            give(name, (lambda *_a, **_k: None))
    return package


def _lpeg_module(runtime):
    """`lpeg` - Cling's own, because Klango's is a C library.

    Seven of the platform library's modules build their patterns at load time,
    so without this the library stops before it has defined anything.
    """
    from . import lpeg
    return lpeg.build(runtime)


def _json_module(runtime):
    """`json` - Cling's own, rather than Klango's.

    Klango's JSON is built on `lpeg`, a C library; writing lpeg would be a
    parser generator's worth of work to arrive at a JSON reader Python already
    has. So the module is supplied whole, and what crosses the boundary is
    converted: a Lua table with keys 1..n becomes an array, anything else an
    object, which is the same rule every Lua JSON library uses.
    """
    import json as _json
    from ..lua.runtime import LuaTable

    table = runtime.table

    def to_python(value, depth=0):
        if depth > 40 or not isinstance(value, LuaTable):
            return value
        keys = value.keys()
        length = value.length()
        if length and len(keys) == length:
            return [to_python(value.raw_get(i + 1), depth + 1)
                    for i in range(length)]
        return {str(key): to_python(value.raw_get(key), depth + 1)
                for key in keys}

    def to_lua(value, depth=0):
        if depth > 40:
            return None
        if isinstance(value, dict):
            out = LuaTable()
            for key, item in value.items():
                out.raw_set(key, to_lua(item, depth + 1))
            return out
        if isinstance(value, (list, tuple)):
            out = LuaTable()
            for index, item in enumerate(value, start=1):
                out.raw_set(index, to_lua(item, depth + 1))
            return out
        return value

    def encode(value=None, *_rest):
        try:
            return _json.dumps(to_python(value), ensure_ascii=False)
        except (TypeError, ValueError):
            return 'null'

    def decode(text=None, *_rest):
        try:
            return to_lua(_json.loads(str(text or '')))
        except (TypeError, ValueError):
            return None

    module = table({})
    _set(module, 'encode', encode)
    _set(module, 'decode', decode)
    _set(module, 'null', None)
    return module


def _unicode_module(runtime):
    """`unicode.utf8` - the string library, which is already text-safe here."""
    table = runtime.table
    strings = runtime.get_global('string')
    module = table({})
    _set(module, 'utf8', strings)
    _set(module, 'ascii', strings)
    return module


def _set(table_value, key, value):
    if hasattr(table_value, 'raw_set'):
        table_value.raw_set(key, value)
    else:
        table_value[key] = value
