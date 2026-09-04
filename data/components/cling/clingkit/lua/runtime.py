# -*- coding: utf-8 -*-
"""The Lua values and the interpreter that walks the tree.

Small on purpose, and complete where completeness is what makes real code run:
closures with upvalues, multiple returns, varargs, metatables (`__index`,
`__newindex`, `__call`, `__tostring`, the arithmetic and comparison ones),
`pcall`/`error`, and the numeric and generic `for`.  Those are not luxuries -
they are how an application of this kind is written: a class is a table with
`__index`, an event handler is a closure, and a level that fails to load is a
`pcall` away from a game that carries on.

Two things are deliberately NOT here.  There are no coroutines: they would want
either threads or a rewritten interpreter, and an application that needs one can
be given one later without changing anything below.  And there is no `require`
of arbitrary files off the disk - a Cling application's Lua may load its own
modules, from its own directory, and nothing else, because the application
came from wherever the user found it.
"""

import math
import os
import sys

from .lexer import LuaSyntaxError
from .parser import parse


class LuaError(Exception):
    """`error()`, and everything the interpreter raises. Carries the value."""

    def __init__(self, value, level=1, where=''):
        #: What `pcall` hands back. It must survive being re-raised with a
        #: better message: `error("boom")` caught by `pcall` is "boom", not
        #: "boom (called at somewhere.lua:12)".
        self.value = value
        self.where = where
        message = tostring(value)
        super().__init__('%s (%s)' % (message, where) if where else message)


class _Break(Exception):
    pass


class _Return(Exception):
    def __init__(self, values):
        self.values = values


class LuaTable(object):
    """A Lua table: the array part and the hash part, and a metatable.

    The array part is kept as a dict keyed by integers rather than a list,
    because Lua tables are sparse and an application that writes `t[100] = x`
    into an empty table must not allocate a hundred slots.  `length` is Lua's
    own `#`: a border, found by walking up from 1.
    """

    __slots__ = ('hash', 'metatable')

    def __init__(self, array=None, hash_part=None):
        self.hash = {}
        self.metatable = None
        if array:
            for index, value in enumerate(array, start=1):
                if value is not None:
                    self.hash[index] = value
        if hash_part:
            for key, value in hash_part.items():
                if value is not None:
                    self.hash[normalise_key(key)] = value

    # -------------------------------------------------------- raw access
    def raw_get(self, key):
        return self.hash.get(normalise_key(key))

    def raw_set(self, key, value):
        key = normalise_key(key)
        if key is None:
            raise LuaError('table index is nil')
        if isinstance(key, float) and key != key:
            raise LuaError('table index is NaN')
        if value is None:
            self.hash.pop(key, None)
        else:
            self.hash[key] = value

    # -------------------------------------------------------------- Lua #
    def length(self):
        if 1 not in self.hash:
            return 0
        size = 1
        while size + 1 in self.hash:
            size += 1
        return size

    def array(self):
        out = []
        index = 1
        while index in self.hash:
            out.append(self.hash[index])
            index += 1
        return out

    def keys(self):
        return list(self.hash.keys())

    def __repr__(self):                                  # pragma: no cover
        return '<table %d>' % id(self)


def normalise_key(key):
    """`t[1]` and `t[1.0]` are the same slot in Lua; here too."""
    if isinstance(key, float) and not isinstance(key, bool):
        if key.is_integer():
            return int(key)
    return key


class LuaFunction(object):
    """A closure: its parameters, its body and the scope it was made in."""

    __slots__ = ('parameters', 'is_vararg', 'body', 'scope', 'name',
                 'interpreter', 'chunk')

    def __init__(self, parameters, is_vararg, body, scope, name, interpreter,
                 chunk=''):
        self.parameters = parameters
        self.is_vararg = is_vararg
        self.body = body
        self.scope = scope
        self.name = name or '?'
        self.interpreter = interpreter
        self.chunk = chunk or getattr(interpreter, 'chunk', '')

    def __call__(self, *arguments):
        return self.interpreter.call_function(self, list(arguments))

    def __repr__(self):                                  # pragma: no cover
        return '<function %s>' % self.name


class Scope(object):
    """One block's names, with a link to the one that encloses it."""

    __slots__ = ('names', 'parent')

    def __init__(self, parent=None):
        self.names = {}
        self.parent = parent

    def lookup(self, name):
        scope = self
        while scope is not None:
            if name in scope.names:
                return scope
            scope = scope.parent
        return None

    def get(self, name):
        scope = self.lookup(name)
        return scope.names[name] if scope is not None else None

    def set_local(self, name, value):
        self.names[name] = value

    def set(self, name, value):
        scope = self.lookup(name)
        if scope is None:
            return False
        scope.names[name] = value
        return True


# --------------------------------------------------------------- coercion
def is_true(value):
    return not (value is None or value is False)


def tostring(value):
    if value is None:
        return 'nil'
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, LuaTable):
        return 'table: 0x%012x' % id(value)
    if callable(value):
        return 'function: 0x%012x' % id(value)
    return str(value)


def tonumber(value, base=None):
    if base not in (None, 10):
        try:
            return int(str(value).strip(), int(base))
        except (TypeError, ValueError):
            return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            if text[:2].lower() in ('0x', '-0', '+0') and 'x' in text.lower():
                return int(text, 16)
            if '.' in text or 'e' in text.lower():
                return float(text)
            return int(text)
        except ValueError:
            try:
                return float(text)
            except ValueError:
                return None
    return None


def type_name(value):
    if value is None:
        return 'nil'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, (int, float)):
        return 'number'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, LuaTable):
        return 'table'
    if callable(value):
        return 'function'
    return 'userdata'


class Interpreter(object):
    """Runs a parsed chunk against a globals table."""

    #: A run that gets this far is a loop nobody is going to break; the whole
    #: point of the ceiling is that an application's own bug cannot take the
    #: desktop with it.
    MAX_STEPS = 40000000

    def __init__(self, globals_table=None, chunk_root=''):
        self.globals = globals_table if globals_table is not None else LuaTable()
        self.chunk_root = chunk_root
        self.steps = 0
        #: Which file the interpreter is inside. A Lua error that says only a
        #: line number is a line number in one of a hundred files, and finding
        #: which one by hand is most of the cost of running somebody else's
        #: code at all.
        self.chunk = chunk_root or 'chunk'
        #: The last line a call was made from. See `call_value`.
        self.line = 0
        self.string_metatable = None
        self.depth = 0
        self.max_depth = 190

    # ------------------------------------------------------------ entry
    def run(self, source, chunk='chunk', arguments=None):
        tree = parse(source, chunk)
        scope = Scope()
        scope.set_local('...', list(arguments or []))
        previous, self.chunk = self.chunk, chunk
        try:
            return self.execute_block(tree, scope)
        finally:
            self.chunk = previous

    def where(self, line):
        """`file:line` - what an error should say, so it can be found."""
        return '%s:%d' % (self.chunk, line) if line else self.chunk

    def run_file(self, path, arguments=None):
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            source = handle.read()
        if source[:1] == '﻿':
            source = source[1:]
        return self.run(source, os.path.basename(path), arguments)

    # -------------------------------------------------------- statements
    def execute_block(self, block, scope):
        for statement in block:
            self.steps += 1
            if self.steps > self.MAX_STEPS:
                raise LuaError('script ran too long and was stopped at %s'
                               % self.where(_line_of(statement) or self.line))
            kind = statement[0]
            handler = self._STATEMENTS.get(kind)
            if handler is None:
                raise LuaError('unknown statement %r' % kind)
            handler(self, statement, scope)
        return None

    def _statement_local(self, statement, scope):
        _kind, names, expressions = statement
        values = self.evaluate_list(expressions, scope, len(names))
        for index, name in enumerate(names):
            scope.set_local(name, values[index] if index < len(values) else None)

    def _statement_assign(self, statement, scope):
        _kind, targets, expressions, line = statement
        values = self.evaluate_list(expressions, scope, len(targets))
        for index, target in enumerate(targets):
            value = values[index] if index < len(values) else None
            if target[0] == 'name':
                if not scope.set(target[1], value):
                    self.globals.raw_set(target[1], value)
            else:
                container = self.evaluate(target[1], scope)
                key = self.evaluate(target[2], scope)
                self.set_index(container, key, value, line)

    def _statement_callstat(self, statement, scope):
        self.evaluate_multi(statement[1], scope)

    def _statement_do(self, statement, scope):
        self.execute_block(statement[1], Scope(scope))

    def _statement_while(self, statement, scope):
        _kind, condition, body = statement
        while is_true(self.evaluate(condition, scope)):
            self.steps += 1
            if self.steps > self.MAX_STEPS:
                raise LuaError('script ran too long and was stopped at %s'
                               % self.where(_line_of(statement) or self.line))
            try:
                self.execute_block(body, Scope(scope))
            except _Break:
                break

    def _statement_repeat(self, statement, scope):
        _kind, body, condition = statement
        while True:
            inner = Scope(scope)
            try:
                self.execute_block(body, inner)
            except _Break:
                break
            # `until` sees the block's own locals - that is Lua, and code that
            # writes `until done` where `done` is local to the block relies on
            # it.
            if is_true(self.evaluate(condition, inner)):
                break
            self.steps += 1
            if self.steps > self.MAX_STEPS:
                raise LuaError('script ran too long and was stopped at %s'
                               % self.where(_line_of(statement) or self.line))

    def _statement_if(self, statement, scope):
        _kind, arms, otherwise = statement
        for condition, body in arms:
            if is_true(self.evaluate(condition, scope)):
                self.execute_block(body, Scope(scope))
                return
        if otherwise is not None:
            self.execute_block(otherwise, Scope(scope))

    def _statement_fornum(self, statement, scope):
        _kind, name, start_expr, stop_expr, step_expr, body, line = statement
        start = self._for_number(self.evaluate(start_expr, scope), line)
        stop = self._for_number(self.evaluate(stop_expr, scope), line)
        step = 1 if step_expr is None else \
            self._for_number(self.evaluate(step_expr, scope), line)
        if step == 0:
            raise LuaError("'for' step is zero")
        current = start
        while (step > 0 and current <= stop) or (step < 0 and current >= stop):
            self.steps += 1
            if self.steps > self.MAX_STEPS:
                raise LuaError('script ran too long and was stopped at %s'
                               % self.where(_line_of(statement) or self.line))
            inner = Scope(scope)
            inner.set_local(name, current)
            try:
                self.execute_block(body, inner)
            except _Break:
                return
            current += step

    @staticmethod
    def _for_number(value, line):
        number = tonumber(value)
        if number is None:
            raise LuaError("'for' expects a number (line %d)" % line)
        return number

    def _statement_forin(self, statement, scope):
        _kind, names, expressions, body, line = statement
        values = self.evaluate_list(expressions, scope, 3)
        iterator = values[0] if values else None
        state = values[1] if len(values) > 1 else None
        control = values[2] if len(values) > 2 else None
        while True:
            self.steps += 1
            if self.steps > self.MAX_STEPS:
                raise LuaError('script ran too long and was stopped at %s'
                               % self.where(_line_of(statement) or self.line))
            produced = self.call_value(iterator, [state, control], line)
            first = produced[0] if produced else None
            if first is None:
                return
            control = first
            inner = Scope(scope)
            for index, name in enumerate(names):
                inner.set_local(name,
                                produced[index] if index < len(produced) else None)
            try:
                self.execute_block(body, inner)
            except _Break:
                return

    def _statement_localfunc(self, statement, scope):
        _kind, name, function_expression = statement
        scope.set_local(name, None)     # so the body can call itself
        scope.set_local(name, self.evaluate(function_expression, scope))

    def _statement_return(self, statement, scope):
        raise _Return(self.evaluate_list(statement[1], scope, -1))

    def _statement_break(self, _statement, _scope):
        raise _Break()

    _STATEMENTS = {}

    # ------------------------------------------------------- expressions
    def evaluate(self, node, scope):
        """One value. A multiple-value expression is truncated to its first."""
        kind = node[0]
        if kind == 'num' or kind == 'str':
            return node[1]
        if kind == 'name':
            found = scope.lookup(node[1])
            if found is not None:
                return found.names[node[1]]
            return self.index(self.globals, node[1], 0)
        if kind == 'nil':
            return None
        if kind == 'true':
            return True
        if kind == 'false':
            return False
        if kind == 'index':
            return self.index(self.evaluate(node[1], scope),
                              self.evaluate(node[2], scope),
                              node[3] if len(node) > 3 else 0)
        if kind == 'paren':
            return self.evaluate(node[1], scope)
        if kind == 'call' or kind == 'method':
            values = self.evaluate_multi(node, scope)
            return values[0] if values else None
        if kind == 'and':
            left = self.evaluate(node[1], scope)
            return self.evaluate(node[2], scope) if is_true(left) else left
        if kind == 'or':
            left = self.evaluate(node[1], scope)
            return left if is_true(left) else self.evaluate(node[2], scope)
        if kind == 'binop':
            return self.binary(node[1], self.evaluate(node[2], scope),
                               self.evaluate(node[3], scope), node[4])
        if kind == 'unop':
            return self.unary(node[1], self.evaluate(node[2], scope), node[3])
        if kind == 'func':
            return LuaFunction(node[1], node[2], node[3], scope, node[4], self,
                               self.chunk)
        if kind == 'table':
            return self.build_table(node, scope)
        if kind == 'vararg':
            values = scope.get('...') or []
            return values[0] if values else None
        raise LuaError('unknown expression %r' % kind)

    def evaluate_multi(self, node, scope):
        """Every value an expression produces, as a list."""
        kind = node[0]
        if kind == 'call':
            function = self.evaluate(node[1], scope)
            arguments = self.evaluate_list(node[2], scope, -1)
            return self.call_value(function, arguments, node[3],
                                   _name_of(node[1]))
        if kind == 'method':
            receiver = self.evaluate(node[1], scope)
            function = self.index(receiver, node[2], node[4])
            arguments = [receiver] + self.evaluate_list(node[3], scope, -1)
            return self.call_value(function, arguments, node[4], node[2])
        if kind == 'vararg':
            return list(scope.get('...') or [])
        return [self.evaluate(node, scope)]

    def evaluate_list(self, expressions, scope, wanted):
        """Lua's list rule: only the LAST expression spreads."""
        values = []
        for index, expression in enumerate(expressions):
            if index == len(expressions) - 1:
                values.extend(self.evaluate_multi(expression, scope))
            else:
                values.append(self.evaluate(expression, scope))
        if wanted >= 0:
            while len(values) < wanted:
                values.append(None)
        return values

    def build_table(self, node, scope):
        _kind, array, hash_part = node
        table = LuaTable()
        position = 1
        for index, expression in enumerate(array):
            if index == len(array) - 1:
                for value in self.evaluate_multi(expression, scope):
                    table.raw_set(position, value)
                    position += 1
            else:
                table.raw_set(position, self.evaluate(expression, scope))
                position += 1
        for key_expression, value_expression in hash_part:
            table.raw_set(self.evaluate(key_expression, scope),
                          self.evaluate(value_expression, scope))
        return table

    # ------------------------------------------------------------ access
    def index(self, container, key, line):
        if isinstance(container, LuaTable):
            value = container.raw_get(key)
            if value is not None:
                return value
            meta = container.metatable
            if meta is None:
                return None
            handler = meta.raw_get('__index')
            if handler is None:
                return None
            if isinstance(handler, LuaTable):
                return self.index(handler, key, line)
            return _first(self.call_value(handler, [container, key], line))
        if isinstance(container, str):
            library = self.string_metatable
            if library is not None:
                return library.raw_get(key)
            return None
        if container is None:
            raise LuaError('attempt to index a nil value at %s' % self.where(line))
        raise LuaError('attempt to index a %s value at %s'
                       % (type_name(container), self.where(line)))

    def set_index(self, container, key, value, line):
        if isinstance(container, LuaTable):
            if container.metatable is not None and container.raw_get(key) is None:
                handler = container.metatable.raw_get('__newindex')
                if handler is not None:
                    if isinstance(handler, LuaTable):
                        self.set_index(handler, key, value, line)
                        return
                    self.call_value(handler, [container, key, value], line)
                    return
            container.raw_set(key, value)
            return
        if container is None:
            raise LuaError('attempt to index a nil value at %s' % self.where(line))
        raise LuaError('attempt to index a %s value at %s'
                       % (type_name(container), self.where(line)))

    # ------------------------------------------------------------- calls
    def call_value(self, function, arguments, line=0, name=''):
        if line:
            # Where the program is, for an error that has no line of its own
            # - the step ceiling above all, which used to name a file and
            # leave the runaway to be found by hand.
            self.line = line
        if isinstance(function, LuaFunction):
            return self.call_function(function, arguments)
        if isinstance(function, LuaTable):
            meta = function.metatable
            handler = meta.raw_get('__call') if meta is not None else None
            if handler is not None:
                return self.call_value(handler, [function] + arguments, line)
        if callable(function):
            # A library function that refuses its arguments says what was
            # wrong but not where it was called from, and "table expected, got
            # nil" is unfindable without that.
            try:
                result = function(*arguments)
            except LuaError as error:
                # The message gains the place it was called from; the VALUE is
                # left exactly as it was, because that is what `pcall` returns.
                if error.where:
                    raise
                raise LuaError(error.value, where='called%s at %s'
                               % (" as '%s'" % name if name else '',
                                  self.where(line))) from None
            except TypeError as error:
                # A native handed the wrong number of arguments raises
                # Python's own error, which names a lambda inside a factory
                # function and NOT the Lua line that called it - the one
                # thing needed to find it. Real Lua ignores extra arguments,
                # so this is nearly always a native of Cling's own that has
                # not said `*rest`, and it must be findable.
                if 'positional argument' not in str(error):
                    raise
                raise LuaError('%s%s' % (
                    "'%s': " % name if name else '', error),
                    where='called at %s' % self.where(line)) from None
            if result is None:
                return []
            if isinstance(result, tuple):
                return list(result)
            if isinstance(result, list):
                return result
            return [result]
        raise LuaError("attempt to call a %s value%s at %s"
                       % (type_name(function),
                          " '%s'" % name if name else '', self.where(line)))

    def call_function(self, function, arguments):
        if self.depth >= self.max_depth:
            # Say WHICH function ran away. "stack overflow" on its own is the
            # least useful message a Lua host can produce.
            raise LuaError("stack overflow in '%s' (%s), %d frames deep"
                           % (function.name, function.chunk or '?',
                              self.depth))
        scope = Scope(function.scope)
        for index, parameter in enumerate(function.parameters):
            scope.set_local(parameter,
                            arguments[index] if index < len(arguments) else None)
        if function.is_vararg:
            extra = list(arguments[len(function.parameters):])
            scope.set_local('...', extra)
            # Lua 5.1 also gives a vararg function a local `arg` table holding
            # those values and their count. Klango's library reads `arg.n`
            # before it reads anything else, so a function without `arg` stops
            # at its first line - `k_SoundPrepare` is the one that shows it.
            table = LuaTable()
            for index, value in enumerate(extra, start=1):
                table.raw_set(index, value)
            table.raw_set('n', len(extra))
            scope.set_local('arg', table)
        else:
            scope.set_local('...', [])
        self.depth += 1
        previous, self.chunk = self.chunk, function.chunk or self.chunk
        try:
            self.execute_block(function.body, scope)
        except _Return as returned:
            return returned.values
        finally:
            self.depth -= 1
            self.chunk = previous
        return []

    # --------------------------------------------------------- operators
    def binary(self, operator, left, right, line):
        if operator == '..':
            if isinstance(left, (str, int, float)) and not isinstance(left, bool) \
                    and isinstance(right, (str, int, float)) \
                    and not isinstance(right, bool):
                return tostring(left) + tostring(right)
            result = self.metamethod('__concat', left, right, line)
            if result is not _NO_META:
                return result
            raise LuaError('attempt to concatenate a %s value at %s'
                           % (type_name(left if not isinstance(left, str)
                                        else right), self.where(line)))

        if operator in ('==', '~='):
            equal = self.equals(left, right, line)
            return equal if operator == '==' else not equal

        if operator in ('<', '<=', '>', '>='):
            return self.compare(operator, left, right, line)

        numbers = (tonumber(left), tonumber(right))
        if numbers[0] is None or numbers[1] is None:
            event = {'+': '__add', '-': '__sub', '*': '__mul', '/': '__div',
                     '%': '__mod', '^': '__pow'}[operator]
            result = self.metamethod(event, left, right, line)
            if result is not _NO_META:
                return result
            bad = left if numbers[0] is None else right
            raise LuaError('attempt to do arithmetic on a %s value at %s'
                           % (type_name(bad), self.where(line)))
        first, second = numbers
        try:
            if operator == '+':
                return first + second
            if operator == '-':
                return first - second
            if operator == '*':
                return first * second
            if operator == '/':
                return first / second
            if operator == '%':
                return first - math.floor(first / second) * second
            if operator == '^':
                return float(first) ** float(second)
        except ZeroDivisionError:
            if operator == '/':
                return float('inf') if first > 0 else (
                    float('-inf') if first < 0 else float('nan'))
            raise LuaError('attempt to perform n%%%%0 (line %d)' % line)
        raise LuaError('unknown operator %r' % operator)

    def unary(self, operator, value, line):
        if operator == 'not':
            return not is_true(value)
        if operator == '-':
            number = tonumber(value)
            if number is None:
                result = self.metamethod('__unm', value, value, line)
                if result is not _NO_META:
                    return result
                raise LuaError('attempt to negate a %s value at %s'
                               % (type_name(value), self.where(line)))
            return -number
        if operator == '#':
            if isinstance(value, str):
                return len(value)
            if isinstance(value, LuaTable):
                if value.metatable is not None:
                    handler = value.metatable.raw_get('__len')
                    if handler is not None:
                        return _first(self.call_value(handler, [value], line))
                return value.length()
            raise LuaError('attempt to get the length of a %s value at %s'
                           % (type_name(value), self.where(line)))
        raise LuaError('unknown unary operator %r' % operator)

    def equals(self, left, right, line):
        if left is right:
            return True
        if isinstance(left, bool) or isinstance(right, bool):
            return left is right
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left == right
        if type_name(left) != type_name(right):
            return False
        if isinstance(left, str):
            return left == right
        if isinstance(left, LuaTable) and isinstance(right, LuaTable):
            result = self.metamethod('__eq', left, right, line)
            return is_true(result) if result is not _NO_META else False
        return left == right

    def compare(self, operator, left, right, line):
        if operator in ('>', '>='):
            left, right = right, left
            operator = '<' if operator == '>' else '<='
        both_numbers = (isinstance(left, (int, float)) and not isinstance(left, bool)
                        and isinstance(right, (int, float))
                        and not isinstance(right, bool))
        if both_numbers or (isinstance(left, str) and isinstance(right, str)):
            return left < right if operator == '<' else left <= right
        event = '__lt' if operator == '<' else '__le'
        result = self.metamethod(event, left, right, line)
        if result is not _NO_META:
            return is_true(result)
        raise LuaError('attempt to compare %s with %s at %s'
                       % (type_name(left), type_name(right), self.where(line)))

    def metamethod(self, event, left, right, line):
        for value in (left, right):
            if isinstance(value, LuaTable) and value.metatable is not None:
                handler = value.metatable.raw_get(event)
                if handler is not None:
                    return _first(self.call_value(handler, [left, right], line))
        return _NO_META

    def tostring(self, value):
        if isinstance(value, LuaTable) and value.metatable is not None:
            handler = value.metatable.raw_get('__tostring')
            if handler is not None:
                return tostring(_first(self.call_value(handler, [value], 0)))
        return tostring(value)


_NO_META = object()


def _first(values):
    if isinstance(values, list):
        return values[0] if values else None
    return values


def _name_of(node):
    if node[0] == 'name':
        return node[1]
    if node[0] == 'index' and node[2][0] == 'str':
        return node[2][1]
    return ''


Interpreter._STATEMENTS = {
    'local': Interpreter._statement_local,
    'assign': Interpreter._statement_assign,
    'callstat': Interpreter._statement_callstat,
    'do': Interpreter._statement_do,
    'while': Interpreter._statement_while,
    'repeat': Interpreter._statement_repeat,
    'if': Interpreter._statement_if,
    'fornum': Interpreter._statement_fornum,
    'forin': Interpreter._statement_forin,
    'localfunc': Interpreter._statement_localfunc,
    'return': Interpreter._statement_return,
    'break': Interpreter._statement_break,
}


def _line_of(statement):
    """The line a statement is on, when it carries one.

    A ceiling reached with no location is a program that ran away somewhere
    in a hundred files - which is most of the cost of finding out where.
    """
    for piece in statement:
        if isinstance(piece, int) and piece > 0:
            return piece
    return 0
