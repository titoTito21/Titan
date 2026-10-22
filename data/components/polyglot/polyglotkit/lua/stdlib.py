# -*- coding: utf-8 -*-
"""The standard library a Cling application's Lua may use.

Deliberately not all of Lua's: there is no `io`, no `os.execute`, no `loadfile`
and no `require` outside the application's own folder.  A Cling application is
a directory the user copied from somewhere, and the moment its Lua can open a
file of its choosing the subsystem has become a way of running arbitrary
programs on a blind user's machine.  Everything an application legitimately
needs - its own strings, its own tables, its own maths, its own modules, and
the whole Cling host - is here.
"""

import inspect
import math
import os
import random as _random
import time as _time

from . import patterns
from .runtime import (LuaError, LuaTable, is_true, tonumber, tostring,
                      type_name, normalise_key)


def build_globals(interpreter, allow_modules_from=''):
    """The `_G` a Cling application starts with."""
    globals_table = interpreter.globals

    def register(name, value):
        globals_table.raw_set(name, _lenient(value))

    register('_VERSION', 'Lua 5.1 (Cling)')
    register('tostring', lambda value=None: interpreter.tostring(value))
    register('tonumber', lambda value=None, base=None: tonumber(value, base))
    register('type', lambda value=None, *_rest: type_name(value))
    register('rawget', lambda table, key=None: _table(table).raw_get(key))
    register('rawset', _make_rawset())
    register('rawequal', lambda a=None, b=None: a is b or (
        not isinstance(a, LuaTable) and not isinstance(b, LuaTable) and a == b))
    register('rawlen', lambda value=None: len(value) if isinstance(value, str)
             else _table(value).length())
    register('print', _make_print(interpreter))
    register('assert', _make_assert())
    register('error', _make_error())
    register('pcall', _make_pcall(interpreter))
    register('xpcall', _make_xpcall(interpreter))
    register('select', _select)
    register('next', _next)
    register('pairs', _make_pairs(interpreter))
    register('ipairs', _ipairs)
    register('unpack', _unpack)
    register('setmetatable', _setmetatable)
    register('getmetatable', _getmetatable)
    register('collectgarbage', lambda *_args: 0)

    string_library = _tolerant(_string_library(interpreter))
    register('string', string_library)
    # `("x"):upper()` - a string's methods are found through a metatable whose
    # `__index` is the string library, exactly as Lua sets up.
    interpreter.string_metatable = string_library

    register('table', _tolerant(_table_library(interpreter)))
    register('math', _tolerant(_math_library()))
    register('os', _tolerant(_os_library()))
    register('cling_require', _make_require(interpreter, allow_modules_from))
    register('require', globals_table.raw_get('cling_require'))
    globals_table.raw_set('_G', globals_table)
    return globals_table


# ------------------------------------------------------------------ basics
def _table(value):
    if not isinstance(value, LuaTable):
        raise LuaError('table expected, got %s' % type_name(value))
    return value


def _make_rawset():
    def rawset(table, key=None, value=None):
        _table(table).raw_set(key, value)
        return table
    return rawset


def _make_print(interpreter):
    def lua_print(*values):
        print('\t'.join(interpreter.tostring(value) for value in values))
    return lua_print


def _make_assert():
    def lua_assert(value=None, message=None, *rest):
        if not is_true(value):
            raise LuaError(message if message is not None else 'assertion failed!')
        return [value, message] + list(rest) if rest or message is not None \
            else value
    return lua_assert


def _make_error():
    def lua_error(message=None, level=1):
        raise LuaError(message, level)
    return lua_error


def _make_pcall(interpreter):
    def pcall(function=None, *arguments):
        try:
            return [True] + list(interpreter.call_value(function,
                                                        list(arguments), 0))
        except LuaError as error:
            return [False, error.value]
        except (ZeroDivisionError, RecursionError) as error:
            return [False, str(error)]
    return pcall


def _make_xpcall(interpreter):
    def xpcall(function=None, handler=None, *arguments):
        try:
            return [True] + list(interpreter.call_value(function,
                                                        list(arguments), 0))
        except LuaError as error:
            handled = interpreter.call_value(handler, [error.value], 0)
            return [False] + list(handled)
    return xpcall


def _select(selector=None, *values):
    if selector == '#':
        return len(values)
    index = int(tonumber(selector) or 0)
    if index < 0:
        index = len(values) + index + 1
    if index < 1:
        raise LuaError("bad argument #1 to 'select' (index out of range)")
    return list(values[index - 1:])


def _next(table=None, key=None):
    table = _table(table)
    keys = table.keys()
    if key is None:
        if not keys:
            return None
        first = keys[0]
        return [first, table.hash[first]]
    key = normalise_key(key)
    try:
        position = keys.index(key)
    except ValueError:
        return None
    if position + 1 >= len(keys):
        return None
    following = keys[position + 1]
    return [following, table.hash[following]]


def _make_pairs(interpreter):
    def pairs(table=None):
        if isinstance(table, LuaTable) and table.metatable is not None:
            handler = table.metatable.raw_get('__pairs')
            if handler is not None:
                return interpreter.call_value(handler, [table], 0)
        # A snapshot iterator: Lua forbids adding keys during a traversal, and
        # a game that does it anyway should not take the interpreter down.
        items = list(_table(table).hash.items())
        position = [0]

        def iterator(*_ignored):
            if position[0] >= len(items):
                return None
            key, value = items[position[0]]
            position[0] += 1
            return [key, value]

        return [iterator, table, None]
    return pairs


def _ipairs(table=None):
    target = _table(table)

    def iterator(_state=None, control=None):
        index = int(tonumber(control) or 0) + 1
        value = target.raw_get(index)
        if value is None:
            return None
        return [index, value]

    return [iterator, table, 0]


def _unpack(table=None, start=None, stop=None):
    target = _table(table)
    first = int(tonumber(start) or 1)
    last = int(tonumber(stop)) if stop is not None else target.length()
    return [target.raw_get(index) for index in range(first, last + 1)]


def _setmetatable(table=None, meta=None):
    target = _table(table)
    if meta is not None and not isinstance(meta, LuaTable):
        raise LuaError('nil or table expected')
    target.metatable = meta
    return target


def _getmetatable(table=None):
    if isinstance(table, LuaTable) and table.metatable is not None:
        guard = table.metatable.raw_get('__metatable')
        return guard if guard is not None else table.metatable
    return None


# ------------------------------------------------------------------ string
def _string_library(interpreter):
    library = LuaTable()

    def _text(value):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return tostring(value)
        if not isinstance(value, str):
            raise LuaError('string expected, got %s' % type_name(value))
        return value

    def _range(text, start, stop):
        length = len(text)
        first = int(tonumber(start) if start is not None else 1)
        last = int(tonumber(stop) if stop is not None else -1)
        if first < 0:
            first = max(length + first + 1, 1)
        elif first == 0:
            first = 1
        if last < 0:
            last = length + last + 1
        elif last > length:
            last = length
        return first, last

    library.raw_set('len', lambda text=None: len(_text(text)))
    library.raw_set('sub', lambda text=None, start=None, stop=None: (
        lambda first, last: _text(text)[first - 1:last] if first <= last else ''
    )(*_range(_text(text), start, stop)))
    library.raw_set('upper', lambda text=None: _text(text).upper())
    library.raw_set('lower', lambda text=None: _text(text).lower())
    library.raw_set('rep', lambda text=None, count=None, separator=None: (
        (separator or '').join([_text(text)] * max(0, int(tonumber(count) or 0)))))
    library.raw_set('reverse', lambda text=None: _text(text)[::-1])
    library.raw_set('byte', _make_byte(_text, _range))
    library.raw_set('char', lambda *codes: ''.join(
        chr(int(tonumber(code) or 0)) for code in codes))
    library.raw_set('format', _make_format(interpreter, _text))

    def find(text=None, pattern=None, init=1, plain=None):
        found = patterns.find(_text(text), _text(pattern),
                              tonumber(init) or 1, is_true(plain))
        if found is None:
            return None
        start, stop, captures = found
        return [start, stop] + list(captures)

    def match(text=None, pattern=None, init=1):
        found = patterns.match(_text(text), _text(pattern), tonumber(init) or 1)
        return list(found) if found is not None else None

    def gmatch(text=None, pattern=None):
        generator = patterns.gmatch(_text(text), _text(pattern))

        def iterator(*_ignored):
            try:
                return list(next(generator))
            except StopIteration:
                return None

        return iterator

    def gsub(text=None, pattern=None, replacement=None, limit=None):
        if isinstance(replacement, LuaTable):
            target = replacement
        elif callable(replacement) and not isinstance(replacement, str):
            def target(*captures):
                return interpreter.call_value(replacement, list(captures), 0)
        else:
            target = _text(replacement)
        count_limit = int(tonumber(limit)) if limit is not None else None
        result, count = patterns.gsub(_text(text), _text(pattern), target,
                                      count_limit)
        return [result, count]

    library.raw_set('find', find)
    library.raw_set('match', match)
    library.raw_set('gmatch', gmatch)
    library.raw_set('gfind', gmatch)
    library.raw_set('gsub', gsub)
    return library


def _make_byte(_text, _range):
    def byte(text=None, start=None, stop=None):
        content = _text(text)
        first, last = _range(content, start if start is not None else 1,
                             stop if stop is not None else start
                             if start is not None else 1)
        return [ord(char) for char in content[first - 1:last]]
    return byte


def _make_format(interpreter, _text):
    def lua_format(template=None, *values):
        template = _text(template)
        out = []
        index = 0
        argument = 0
        while index < len(template):
            char = template[index]
            if char != '%':
                out.append(char)
                index += 1
                continue
            index += 1
            if index < len(template) and template[index] == '%':
                out.append('%')
                index += 1
                continue
            specification = '%'
            while index < len(template) and template[index] in '-+ #0':
                specification += template[index]
                index += 1
            while index < len(template) and template[index].isdigit():
                specification += template[index]
                index += 1
            if index < len(template) and template[index] == '.':
                specification += '.'
                index += 1
                while index < len(template) and template[index].isdigit():
                    specification += template[index]
                    index += 1
            if index >= len(template):
                raise LuaError("invalid format string to 'format'")
            conversion = template[index]
            index += 1
            value = values[argument] if argument < len(values) else None
            argument += 1
            if conversion in 'di':
                out.append((specification + 'd') % int(tonumber(value) or 0))
            elif conversion == 'u':
                out.append((specification + 'd') % abs(int(tonumber(value) or 0)))
            elif conversion in 'feEgG':
                out.append((specification + conversion)
                           % float(tonumber(value) or 0.0))
            elif conversion in 'xXo':
                out.append((specification + conversion)
                           % int(tonumber(value) or 0))
            elif conversion == 'c':
                out.append(chr(int(tonumber(value) or 0)))
            elif conversion == 's':
                out.append((specification + 's') % interpreter.tostring(value))
            elif conversion == 'q':
                out.append('"%s"' % interpreter.tostring(value)
                           .replace('\\', '\\\\').replace('"', '\\"')
                           .replace('\n', '\\n'))
            else:
                raise LuaError("invalid option '%%%s' to 'format'" % conversion)
        return ''.join(out)
    return lua_format


# ------------------------------------------------------------------- table
def _table_library(interpreter):
    library = LuaTable()

    def insert(table=None, first=None, second=None):
        target = _table(table)
        if second is None:
            target.raw_set(target.length() + 1, first)
            return None
        position = int(tonumber(first) or 0)
        size = target.length()
        if position < 1 or position > size + 1:
            raise LuaError("bad argument #2 to 'insert' (position out of bounds)")
        for index in range(size, position - 1, -1):
            target.raw_set(index + 1, target.raw_get(index))
        target.raw_set(position, second)
        return None

    def remove(table=None, position=None):
        target = _table(table)
        size = target.length()
        if size == 0:
            return None
        index = size if position is None else int(tonumber(position) or 0)
        if index < 1 or index > size:
            return None
        value = target.raw_get(index)
        for step in range(index, size):
            target.raw_set(step, target.raw_get(step + 1))
        target.raw_set(size, None)
        return value

    def concat(table=None, separator='', start=None, stop=None):
        target = _table(table)
        first = int(tonumber(start) or 1)
        last = int(tonumber(stop)) if stop is not None else target.length()
        pieces = []
        for index in range(first, last + 1):
            value = target.raw_get(index)
            if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                raise LuaError("invalid value at index %d in table for 'concat'"
                               % index)
            pieces.append(tostring(value))
        return (separator if isinstance(separator, str) else
                tostring(separator)).join(pieces)

    def sort(table=None, comparator=None):
        target = _table(table)
        values = target.array()
        if comparator is None:
            import functools

            def compare(left, right):
                return -1 if interpreter.compare('<', left, right, 0) else (
                    1 if interpreter.compare('<', right, left, 0) else 0)
            values.sort(key=functools.cmp_to_key(compare))
        else:
            import functools

            def compare(left, right):
                if is_true(_one(interpreter.call_value(comparator,
                                                       [left, right], 0))):
                    return -1
                if is_true(_one(interpreter.call_value(comparator,
                                                       [right, left], 0))):
                    return 1
                return 0
            values.sort(key=functools.cmp_to_key(compare))
        for index, value in enumerate(values, start=1):
            target.raw_set(index, value)
        return None

    def foreach(table=None, function=None):
        """Lua 5.1's `table.foreach`. Deprecated in Lua, and used all over
        Klango's library, which is what makes it worth having."""
        target = _table(table)
        for key in list(target.hash.keys()):
            produced = _one(interpreter.call_value(
                function, [key, target.raw_get(key)], 0))
            if produced is not None:
                return produced
        return None

    def foreachi(table=None, function=None):
        target = _table(table)
        for index, value in enumerate(target.array(), start=1):
            produced = _one(interpreter.call_value(function, [index, value], 0))
            if produced is not None:
                return produced
        return None

    library.raw_set('foreach', foreach)
    library.raw_set('foreachi', foreachi)
    library.raw_set('insert', insert)
    library.raw_set('remove', remove)
    library.raw_set('concat', concat)
    library.raw_set('sort', sort)
    library.raw_set('unpack', _unpack)
    library.raw_set('getn', lambda table=None: _table(table).length())
    return library


def _one(values):
    if isinstance(values, list):
        return values[0] if values else None
    return values


# -------------------------------------------------------------------- math
def _math_library():
    library = LuaTable()
    generator = _random.Random()

    def number(value, default=0.0):
        converted = tonumber(value)
        return default if converted is None else converted

    library.raw_set('pi', math.pi)
    library.raw_set('huge', float('inf'))
    library.raw_set('abs', lambda value=None: abs(number(value)))
    library.raw_set('ceil', lambda value=None: int(math.ceil(number(value))))
    library.raw_set('floor', lambda value=None: int(math.floor(number(value))))
    library.raw_set('sqrt', lambda value=None: math.sqrt(max(0.0, number(value))))
    library.raw_set('sin', lambda value=None: math.sin(number(value)))
    library.raw_set('cos', lambda value=None: math.cos(number(value)))
    library.raw_set('tan', lambda value=None: math.tan(number(value)))
    library.raw_set('asin', lambda value=None: math.asin(number(value)))
    library.raw_set('acos', lambda value=None: math.acos(number(value)))
    library.raw_set('atan', lambda value=None: math.atan(number(value)))
    library.raw_set('exp', lambda value=None: math.exp(number(value)))
    library.raw_set('log', lambda value=None, base=None: (
        math.log(number(value)) if base is None
        else math.log(number(value), number(base, 10.0))))
    library.raw_set('log10', lambda value=None: math.log10(number(value)))
    library.raw_set('pow', lambda a=None, b=None: number(a) ** number(b))
    library.raw_set('fmod', lambda a=None, b=None: math.fmod(number(a), number(b)))
    library.raw_set('modf', lambda value=None: list(
        reversed([float(part) for part in math.modf(number(value))])))
    library.raw_set('max', lambda *values: max(number(value) for value in values))
    library.raw_set('min', lambda *values: min(number(value) for value in values))
    library.raw_set('randomseed', lambda seed=None: generator.seed(
        int(number(seed, 0))))

    def random(first=None, second=None):
        if first is None:
            return generator.random()
        low = 1 if second is None else int(number(first, 1))
        high = int(number(first, 1)) if second is None else int(number(second, 1))
        if low > high:
            raise LuaError("bad argument to 'random' (interval is empty)")
        return generator.randint(low, high)

    library.raw_set('random', random)
    # The rest of Lua 5.1's math library. Klango's own expression evaluator
    # copies every one of these into its function table, so a missing one is
    # not a missing feature - it is a nil where a function was expected.
    library.raw_set('rad', lambda value=None: math.radians(number(value)))
    library.raw_set('deg', lambda value=None: math.degrees(number(value)))
    library.raw_set('sinh', lambda value=None: math.sinh(number(value)))
    library.raw_set('cosh', lambda value=None: math.cosh(number(value)))
    library.raw_set('tanh', lambda value=None: math.tanh(number(value)))
    library.raw_set('atan2', lambda a=None, b=None: math.atan2(number(a),
                                                               number(b, 1.0)))
    library.raw_set('frexp', lambda value=None: list(math.frexp(number(value))))
    library.raw_set('ldexp', lambda a=None, b=None: math.ldexp(
        number(a), int(number(b))))
    library.raw_set('mininteger', -(2 ** 63))
    library.raw_set('maxinteger', 2 ** 63 - 1)
    return library


# ---------------------------------------------------------------------- os
def _os_library():
    library = LuaTable()

    def os_time(pieces=None, *_rest):
        """`os.time()` now, or the moment a table describes."""
        if not isinstance(pieces, LuaTable):
            return int(_time.time())
        def field(name, default):
            value = pieces.raw_get(name)
            return int(tonumber(value)) if value is not None else default
        try:
            return int(_time.mktime((
                field('year', 1970), field('month', 1), field('day', 1),
                field('hour', 12), field('min', 0), field('sec', 0),
                0, 0, field('isdst', -1))))
        except (ValueError, OverflowError):
            return int(_time.time())

    def os_date(fmt=None, when=None, *_rest):
        """`os.date` - and `"*t"` answers a TABLE, which is the whole point.

        Lua's `os.date("*t")` gives `{year=, month=, day=, hour=, min=,
        sec=, wday=, yday=, isdst=}`, and code reads the fields straight off
        it: Shopping with Klango builds its request timestamp that way and
        stopped with "attempt to compare nil with number" when this answered
        a string to every question.
        """
        wanted = str(fmt or '%c')
        moment = tonumber(when) if when is not None else None
        universal = wanted.startswith('!')
        if universal:
            wanted = wanted[1:]
        parts = (_time.gmtime(moment) if universal
                 else _time.localtime(moment))
        if wanted.startswith('*t'):
            out = LuaTable()
            for name, value in (('year', parts.tm_year), ('month', parts.tm_mon),
                                ('day', parts.tm_mday), ('hour', parts.tm_hour),
                                ('min', parts.tm_min), ('sec', parts.tm_sec),
                                ('wday', parts.tm_wday % 7 + 1),
                                ('yday', parts.tm_yday)):
                out.raw_set(name, value)
            out.raw_set('isdst', bool(parts.tm_isdst > 0))
            return out
        return _time.strftime(wanted, parts)

    library.raw_set('time', os_time)
    library.raw_set('clock', lambda *_a: _time.process_time())
    library.raw_set('date', os_date)
    library.raw_set('difftime', lambda a=None, b=0: float(
        (tonumber(a) or 0) - (tonumber(b) or 0)))
    library.raw_set('getenv', lambda name=None: None)
    return library


# ----------------------------------------------------------------- require
def _inside(root, candidate):
    """Is `candidate` really under `root`?

    `commonpath` raises rather than answering when the two are on different
    drives, and a path that escaped so far that it landed on another drive is
    exactly the one that must be refused - so the exception is an answer of
    'no', not something to let through.
    """
    try:
        return os.path.commonpath([root, candidate]) == root
    except ValueError:
        return False


def _make_require(interpreter, allow_modules_from):
    """`require 'thing'` - a `.lua` beside the application, and nothing else.

    The path is resolved and then checked to still be inside the application's
    own directory, so `require '../../../secrets'` is refused rather than
    resolved: the name comes from a file the user was handed, not from Titan.
    """
    loaded = {}

    def require(name=None):
        if not allow_modules_from:
            raise LuaError("this application may not load modules")
        if not isinstance(name, str) or not name:
            raise LuaError("bad argument #1 to 'require'")
        if name in loaded:
            return loaded[name]
        relative = name.replace('.', os.sep) + '.lua'
        candidate = os.path.abspath(os.path.join(allow_modules_from, relative))
        root = os.path.abspath(allow_modules_from)
        if not _inside(root, candidate):
            raise LuaError("module '%s' is outside the application" % name)
        if not os.path.isfile(candidate):
            raise LuaError("module '%s' not found" % name)
        with open(candidate, 'r', encoding='utf-8', errors='replace') as handle:
            source = handle.read()
        from .parser import parse
        from .runtime import Scope, _Return
        tree = parse(source, os.path.basename(candidate))
        scope = Scope()
        scope.set_local('...', [name])
        try:
            interpreter.execute_block(tree, scope)
            value = True
        except _Return as returned:
            value = returned.values[0] if returned.values else True
        loaded[name] = value
        return value

    return require


# --------------------------------------------------- surplus arguments
#: Cached: which functions take how many arguments. Working it out is
#: `inspect`, which is far too slow to do on every call from Lua.
_ARITY = {}


def _lenient(function):
    """A library function that ignores arguments it was not expecting.

    Lua's own library is written in C and reads only the arguments it wants;
    everything after them is discarded. That is not a detail an application
    can be asked to respect, because Lua EXPANDS a multi-value call in the
    last argument position: `string.lower(name:gsub("_", "-"))` passes the
    replaced string *and the number of replacements*, which is ordinary Lua
    and which every one of Cling's fixed-arity natives refused. It stopped
    ktrans dead on its fourth screen.
    """
    if not callable(function) or isinstance(function, LuaTable):
        return function
    limit = _ARITY.get(function, _MISSING_ARITY)
    if limit is _MISSING_ARITY:
        limit = _arity_of(function)
        try:
            _ARITY[function] = limit
        except TypeError:                       # not hashable; work it out again
            pass
    if limit is None:
        return function

    def call(*arguments):
        if len(arguments) > limit:
            arguments = arguments[:limit]
        return function(*arguments)

    call.__name__ = getattr(function, '__name__', 'lua')
    return call


_MISSING_ARITY = object()


def _arity_of(function):
    """How many positional arguments a function takes, or None for any number."""
    try:
        spec = inspect.getfullargspec(function)
    except TypeError:
        return None                             # a builtin; leave it alone
    if spec.varargs is not None:
        return None
    count = len(spec.args)
    if inspect.ismethod(function):
        count -= 1
    return count


def _tolerant(library):
    """The same library, every function in it lenient about surplus arguments."""
    for key in list(library.keys()):
        library.raw_set(key, _lenient(library.raw_get(key)))
    return library
