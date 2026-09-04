# -*- coding: utf-8 -*-
"""LPeg for Cling, because seven of Klango's own modules parse with it.

`llib_string`, `llib_datatypes`, `llib_files_trans`, `llib_files_playlists`,
`llib_kdocsrchtml`, `llib_kdocurl` and `llib_math` all begin with
`require("lpeg")`, and none of them defines a single function until it has
built its patterns - so without lpeg the platform library stops loading before
it has given an application anything at all.  It is a C library in Klango; here
it is Python, and it is reached through exactly the same Lua expressions,
because the operators are metamethods:

    local Number = lpeg.C(lpeg.P"-"^-1 * lpeg.R("09")^1) * Space

`*` is a sequence, `+` an ordered choice, `-` a difference, `^n` a repetition
(negative n meaning "at most"), `/` a capture applied to a function, a string,
a table or a number.  A pattern is a Lua table carrying its compiled self and
sharing one metatable, which is what makes those operators work.

**Captures are a tree, not a list.**  That is not a flourish: `Ca` (the
accumulator capture that Klango's expression parser is written with) has to
feed each function capture the value the previous one produced, so the
functions cannot be applied while matching - what the match produces is a tree,
and the values come out of walking it afterwards.
"""

from ..lua.runtime import LuaTable, is_true, tostring

MAXDEPTH = 220


class Pattern(object):
    """A compiled pattern: a kind and whatever that kind needs."""

    __slots__ = ('kind', 'a', 'b', 'value')

    def __init__(self, kind, a=None, b=None, value=None):
        self.kind = kind
        self.a = a
        self.b = b
        self.value = value

    def __repr__(self):                                  # pragma: no cover
        return '<pattern %s>' % self.kind


# --------------------------------------------------------------- capturing
class Capture(object):
    """A node of the capture tree the matcher builds."""

    __slots__ = ('kind', 'value', 'children', 'text')

    def __init__(self, kind, value=None, children=None, text=''):
        self.kind = kind          # value / table / apply / subst / fold / acc
        self.value = value
        self.children = children or []
        self.text = text


class Machine(object):
    """Matching, and turning the capture tree into values."""

    def __init__(self, interpreter, grammar=None):
        self.interpreter = interpreter
        #: A stack, because a grammar can contain another one and `V(name)`
        #: means the rule of the grammar it is written in.
        self.grammars = [grammar or {}]
        self.depth = 0

    # ------------------------------------------------------------ matching
    def match(self, pattern, subject, index, captures):
        """Return the index after `pattern`, or None. Appends capture nodes."""
        self.depth += 1
        if self.depth > MAXDEPTH:
            self.depth -= 1
            raise RuntimeError('pattern too complex')
        try:
            return self._match(pattern, subject, index, captures)
        finally:
            self.depth -= 1

    def _match(self, pattern, subject, index, captures):
        kind = pattern.kind

        if kind == 'any':                       # P(n)
            count = pattern.value
            if count >= 0:
                return index + count if index + count <= len(subject) else None
            return index if len(subject) - index < -count else None
        if kind == 'true':
            return index
        if kind == 'false':
            return None
        if kind == 'lit':                       # P("text")
            text = pattern.value
            return index + len(text) if subject.startswith(text, index) else None
        if kind == 'set':                       # S("abc")
            return index + 1 if index < len(subject) \
                and subject[index] in pattern.value else None
        if kind == 'range':                     # R("09", "az")
            if index >= len(subject):
                return None
            char = subject[index]
            for low, high in pattern.value:
                if low <= char <= high:
                    return index + 1
            return None

        if kind == 'seq':
            middle = self.match(pattern.a, subject, index, captures)
            if middle is None:
                return None
            return self.match(pattern.b, subject, middle, captures)
        if kind == 'ord':
            saved = len(captures)
            found = self.match(pattern.a, subject, index, captures)
            if found is not None:
                return found
            del captures[saved:]
            return self.match(pattern.b, subject, index, captures)
        if kind == 'diff':                      # a - b
            saved = len(captures)
            if self.match(pattern.b, subject, index, []) is not None:
                return None
            del captures[saved:]
            return self.match(pattern.a, subject, index, captures)
        if kind == 'not':                       # -a
            return index if self.match(pattern.a, subject, index, []) is None \
                else None
        if kind == 'and':                       # #a
            return index if self.match(pattern.a, subject, index, []) is not None \
                else None

        if kind == 'rep':
            count = pattern.value
            position = index
            done = 0
            if count >= 0:
                while True:
                    saved = len(captures)
                    found = self.match(pattern.a, subject, position, captures)
                    if found is None or found == position:
                        del captures[saved:]
                        break
                    position = found
                    done += 1
                return position if done >= count else None
            for _ in range(-count):
                saved = len(captures)
                found = self.match(pattern.a, subject, position, captures)
                if found is None:
                    del captures[saved:]
                    break
                position = found
            return position

        if kind == 'grammar':
            self.grammars.append(pattern.value)
            try:
                return self.match(pattern.a, subject, index, captures)
            finally:
                self.grammars.pop()
        if kind == 'var':                       # V(name)
            rule = self.grammars[-1].get(_key(pattern.value))
            if rule is None:
                raise RuntimeError("no rule '%s' in the grammar"
                                   % tostring(pattern.value))
            return self.match(rule, subject, index, captures)

        # ---------------------------------------------------------- captures
        if kind in ('cap', 'ctab', 'csubst', 'capply', 'cfold', 'cacc', 'cgroup'):
            inner = []
            found = self.match(pattern.a, subject, index, inner)
            if found is None:
                return None
            text = subject[index:found]
            if kind == 'cap':
                captures.append(Capture('value', text if not inner else None,
                                        inner, text))
            elif kind == 'ctab':
                captures.append(Capture('table', None, inner, text))
            elif kind == 'csubst':
                captures.append(Capture('subst', None, inner, text))
            elif kind == 'capply':
                captures.append(Capture('apply', pattern.b, inner, text))
            elif kind == 'cfold':
                captures.append(Capture('fold', pattern.b, inner, text))
            elif kind == 'cgroup':
                captures.append(Capture('table', None, inner, text))
            else:
                captures.append(Capture('acc', None, inner, text))
            return found
        if kind == 'cconst':                    # Cc(v)
            captures.append(Capture('value', pattern.value))
            return index
        if kind == 'cpos':                      # Cp()
            captures.append(Capture('value', index + 1))
            return index

        raise RuntimeError('unknown pattern %r' % kind)

    # ------------------------------------------------------------- values
    def values(self, nodes):
        """Walk the capture tree and produce the list of captured values."""
        out = []
        for node in nodes:
            out.extend(self._value(node))
        return out

    def _value(self, node):
        if node.kind == 'value':
            if node.value is not None or not node.children:
                return [node.value if node.value is not None else node.text]
            inner = self.values(node.children)
            return inner if inner else [node.text]
        if node.kind == 'table':
            table = LuaTable()
            for position, value in enumerate(self.values(node.children), start=1):
                table.raw_set(position, value)
            return [table]
        if node.kind == 'subst':
            inner = self.values(node.children)
            return [''.join(tostring(value) for value in inner) or node.text]
        if node.kind == 'apply':
            return self._apply(node.value, self.values(node.children), node.text)
        if node.kind == 'fold':
            values = self.values(node.children)
            if not values:
                return []
            accumulator = values[0]
            for value in values[1:]:
                accumulator = self._call(node.value, [accumulator, value])
            return [accumulator]
        if node.kind == 'acc':
            return self._accumulate(node.children)
        return []

    def _accumulate(self, children):
        """`Ca` - each function capture is handed what the last one produced.

        This is why the tree exists: the functions inside an accumulator cannot
        be applied while matching, because none of them knows its first
        argument until the one before it has finished.
        """
        accumulator = None
        started = False
        for child in children:
            if child.kind == 'apply' and started:
                arguments = [accumulator] + self.values(child.children)
                produced = self._apply(child.value, arguments, child.text,
                                       already=True)
                accumulator = produced[0] if produced else accumulator
                continue
            for value in self._value(child):
                if not started:
                    accumulator = value
                    started = True
                else:
                    accumulator = value
        return [accumulator] if started else []

    def _apply(self, target, arguments, text, already=False):
        """`patt / x` - a function, a string, a table or a capture number."""
        if isinstance(target, (int, float)) and not isinstance(target, bool):
            index = int(target)
            return [arguments[index - 1]] if 0 < index <= len(arguments) else []
        if isinstance(target, str):
            out = []
            position = 0
            while position < len(target):
                char = target[position]
                if char == '%' and position + 1 < len(target):
                    digit = target[position + 1]
                    if digit == '0':
                        out.append(text)
                        position += 2
                        continue
                    if digit.isdigit():
                        slot = int(digit) - 1
                        out.append(tostring(arguments[slot])
                                   if slot < len(arguments) else '')
                        position += 2
                        continue
                out.append(char)
                position += 1
            return [''.join(out)]
        if isinstance(target, LuaTable):
            key = arguments[0] if arguments else text
            value = target.raw_get(key)
            return [value] if value is not None else []
        produced = self._call(target, arguments if arguments else [text])
        return [] if produced is None else [produced]

    def _call(self, function, arguments):
        values = self.interpreter.call_value(function, list(arguments), 0)
        if isinstance(values, list):
            return values[0] if values else None
        return values


def _key(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


# --------------------------------------------------------- the Lua surface
def build(runtime):
    """The `lpeg` module, as Klango's library expects to `require` it."""
    interpreter = runtime.interpreter if runtime.interpreter is not None else None
    meta = LuaTable()

    def wrap(pattern):
        table = LuaTable()
        table.raw_set('__pattern', _Holder(pattern))
        table.metatable = meta
        return table

    def unwrap(value, what='pattern'):
        """Anything lpeg accepts where a pattern is wanted."""
        if isinstance(value, LuaTable):
            holder = value.raw_get('__pattern')
            if isinstance(holder, _Holder):
                return holder.pattern
            return _grammar(value, unwrap)
        if isinstance(value, str):
            return Pattern('lit', value=value)
        if isinstance(value, bool):
            return Pattern('true' if value else 'false')
        if isinstance(value, (int, float)):
            return Pattern('any', value=int(value))
        raise RuntimeError('%s expected' % what)

    # ------------------------------------------------------------ operators
    meta.raw_set('__mul', lambda a=None, b=None, *_r:
                 wrap(Pattern('seq', unwrap(a), unwrap(b))))
    meta.raw_set('__add', lambda a=None, b=None, *_r:
                 wrap(Pattern('ord', unwrap(a), unwrap(b))))
    meta.raw_set('__sub', lambda a=None, b=None, *_r:
                 wrap(Pattern('diff', unwrap(a), unwrap(b))))
    meta.raw_set('__unm', lambda a=None, *_r: wrap(Pattern('not', unwrap(a))))
    meta.raw_set('__len', lambda a=None, *_r: wrap(Pattern('and', unwrap(a))))
    meta.raw_set('__pow', lambda a=None, n=None, *_r:
                 wrap(Pattern('rep', unwrap(a), value=int(n or 0))))
    meta.raw_set('__div', lambda a=None, f=None, *_r:
                 wrap(Pattern('capply', unwrap(a), b=f)))
    meta.raw_set('__index', LuaTable())

    module = LuaTable()

    def P(value=None, *_rest):
        return wrap(unwrap(value))

    def S(text=None, *_rest):
        return wrap(Pattern('set', value=set(str(text or ''))))

    def R(*ranges):
        pairs = []
        for item in ranges:
            text = str(item or '')
            for position in range(0, len(text) - 1, 2):
                pairs.append((text[position], text[position + 1]))
        return wrap(Pattern('range', value=pairs))

    def V(name=None, *_rest):
        return wrap(Pattern('var', value=name))

    def match(pattern=None, subject=None, init=1, *_rest):
        compiled = unwrap(pattern)
        text = str(subject or '')
        start = int(init or 1)
        start = len(text) + start if start < 0 else max(0, start - 1)
        machine = Machine(interpreter)
        captures = []
        try:
            found = machine.match(compiled, text, start, captures)
        except RuntimeError:
            return None
        if found is None:
            return None
        values = machine.values(captures)
        return values if values else found + 1

    module.raw_set('P', P)
    module.raw_set('S', S)
    module.raw_set('R', R)
    module.raw_set('V', V)
    module.raw_set('C', lambda p=None, *_r: wrap(Pattern('cap', unwrap(p))))
    module.raw_set('Ct', lambda p=None, *_r: wrap(Pattern('ctab', unwrap(p))))
    module.raw_set('Cs', lambda p=None, *_r: wrap(Pattern('csubst', unwrap(p))))
    module.raw_set('Cc', lambda v=None, *_r: wrap(Pattern('cconst', value=v)))
    module.raw_set('Cp', lambda *_r: wrap(Pattern('cpos')))
    module.raw_set('Ca', lambda p=None, *_r: wrap(Pattern('cacc', unwrap(p))))
    module.raw_set('Cf', lambda p=None, f=None, *_r:
                   wrap(Pattern('cfold', unwrap(p), b=f)))
    module.raw_set('Cg', lambda p=None, _n=None, *_r:
                   wrap(Pattern('cgroup', unwrap(p))))
    module.raw_set('match', match)
    module.raw_set('type', lambda value=None, *_r: (
        'pattern' if isinstance(value, LuaTable)
        and isinstance(value.raw_get('__pattern'), _Holder) else None))
    module.raw_set('version', lambda *_r: '0.9 (Cling)')
    module.raw_set('locale', lambda *_r: LuaTable())
    meta.raw_set('__index', module)
    return module


class _Holder(object):
    """Keeps a compiled pattern inside a Lua table without it being a table."""

    __slots__ = ('pattern',)

    def __init__(self, pattern):
        self.pattern = pattern


def _grammar(table, unwrap):
    """`lpeg.P{ ... }` - a grammar, which carries its rules with it.

    Rule 1 is where it starts (or names the rule that does). The rules are
    compiled once and travel inside the pattern, so `V(name)` still finds them
    when the grammar has been handed on to something else.
    """
    rules = {}
    for key in table.keys():
        try:
            rules[_key(key)] = unwrap(table.raw_get(key))
        except RuntimeError:
            continue
    start = table.raw_get(1)
    if isinstance(start, str):
        start_pattern = rules.get(start)
    else:
        start_pattern = rules.get(1)
    if start_pattern is None:
        raise RuntimeError('a grammar with no first rule')
    return Pattern('grammar', start_pattern, value=rules)


