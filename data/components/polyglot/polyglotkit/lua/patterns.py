# -*- coding: utf-8 -*-
"""Lua patterns, which are not regular expressions.

`string.find`, `match`, `gmatch` and `gsub` are how Lua code takes anything
apart, so an interpreter that had them "roughly" would run an application right
up to the line that parses its own save file.  This is Lua 5.1's matcher
(`lstrlib.c`) followed rule for rule: the `%a %d %s %w %x` classes and their
negations, sets with ranges and negation, the four quantifiers including the
lazy `-`, the `^` and `$` anchors, captures, position captures, `%b` for
balanced pairs, `%f` for frontiers and `%1`-`%9` back-references.

Positions are 1-based on the way in and out, because that is what the Lua side
of every one of these functions expects.
"""

MAXCAPTURES = 32
CAP_UNFINISHED = -1
CAP_POSITION = -2
L_ESC = '%'
SPECIALS = '^$*+?.([%-'


class PatternError(ValueError):
    pass


class _Match(object):
    __slots__ = ('source', 'pattern', 'level', 'capture_start', 'capture_len',
                 'depth')

    def __init__(self, source, pattern):
        self.source = source
        self.pattern = pattern
        self.level = 0
        self.capture_start = [0] * MAXCAPTURES
        self.capture_len = [0] * MAXCAPTURES
        self.depth = 0


def _class_match(char, class_char):
    lowered = class_char.lower()
    if lowered == 'a':
        result = char.isalpha()
    elif lowered == 'c':
        result = ord(char) < 32 or ord(char) == 127
    elif lowered == 'd':
        result = char.isdigit()
    elif lowered == 'l':
        result = char.islower()
    elif lowered == 'p':
        result = (33 <= ord(char) <= 47 or 58 <= ord(char) <= 64
                  or 91 <= ord(char) <= 96 or 123 <= ord(char) <= 126)
    elif lowered == 's':
        result = char in ' \t\n\r\f\v'
    elif lowered == 'u':
        result = char.isupper()
    elif lowered == 'w':
        result = char.isalnum()
    elif lowered == 'x':
        result = char in '0123456789abcdefABCDEF'
    elif lowered == 'z':
        result = char == '\0'
    else:
        return class_char == char
    return not result if class_char.isupper() else result


def _class_end(state, index):
    """One past the end of the single character class starting at `index`."""
    pattern = state.pattern
    size = len(pattern)
    if index >= size:
        raise PatternError('malformed pattern (ends with %)')
    char = pattern[index]
    index += 1
    if char == L_ESC:
        if index >= size:
            raise PatternError("malformed pattern (ends with '%')")
        return index + 1
    if char == '[':
        if index < size and pattern[index] == '^':
            index += 1
        # lstrlib.c's do-while: one character is always consumed, so `[]]` is
        # the set containing `]` rather than an empty one.
        while True:
            if index >= size:
                raise PatternError("malformed pattern (missing ']')")
            current = pattern[index]
            index += 1
            if current == L_ESC and index < size:
                index += 1
            if index < size and pattern[index] == ']':
                return index + 1
            if index >= size:
                raise PatternError("malformed pattern (missing ']')")
    return index


def _match_class_in_set(state, char, start, end):
    """`[...]` between `start` (just after '[') and `end` (the ']')."""
    pattern = state.pattern
    negate = False
    index = start + 1
    if index < len(pattern) and pattern[index] == '^':
        negate = True
        index += 1
    found = False
    while index < end:
        current = pattern[index]
        if current == L_ESC and index + 1 < end:
            index += 1
            if _class_match(char, pattern[index]):
                found = True
            index += 1
        elif index + 2 < end and pattern[index + 1] == '-':
            if pattern[index] <= char <= pattern[index + 2]:
                found = True
            index += 3
        else:
            if current == char:
                found = True
            index += 1
    return not found if negate else found


def _single_match(state, source_index, pattern_index, end_index):
    if source_index >= len(state.source):
        return False
    char = state.source[source_index]
    kind = state.pattern[pattern_index]
    if kind == '.':
        return True
    if kind == L_ESC:
        return _class_match(char, state.pattern[pattern_index + 1])
    if kind == '[':
        return _match_class_in_set(state, char, pattern_index, end_index - 1)
    return kind == char


def _match_balance(state, source_index, pattern_index):
    pattern = state.pattern
    if pattern_index + 1 >= len(pattern):
        raise PatternError("missing arguments to '%b'")
    source = state.source
    if source_index >= len(source) or source[source_index] != pattern[pattern_index]:
        return -1
    opening = pattern[pattern_index]
    closing = pattern[pattern_index + 1]
    count = 1
    index = source_index + 1
    while index < len(source):
        char = source[index]
        if char == closing:
            count -= 1
            if count == 0:
                return index + 1
        elif char == opening:
            count += 1
        index += 1
    return -1


def _capture_to_close(state):
    level = state.level - 1
    while level >= 0:
        if state.capture_len[level] == CAP_UNFINISHED:
            return level
        level -= 1
    raise PatternError('invalid pattern capture')


def _match(state, source_index, pattern_index):
    state.depth += 1
    if state.depth > 220:
        state.depth -= 1
        raise PatternError('pattern too complex')
    try:
        pattern = state.pattern
        source = state.source
        while True:
            if pattern_index >= len(pattern):
                return source_index
            current = pattern[pattern_index]

            if current == '(':
                if pattern_index + 1 < len(pattern) \
                        and pattern[pattern_index + 1] == ')':
                    return _start_capture(state, source_index,
                                          pattern_index + 2, CAP_POSITION)
                return _start_capture(state, source_index, pattern_index + 1,
                                      CAP_UNFINISHED)
            if current == ')':
                return _end_capture(state, source_index, pattern_index + 1)
            if current == '$' and pattern_index + 1 == len(pattern):
                return source_index if source_index == len(source) else -1
            if current == L_ESC and pattern_index + 1 < len(pattern):
                following = pattern[pattern_index + 1]
                if following == 'b':
                    ending = _match_balance(state, source_index, pattern_index + 2)
                    if ending < 0:
                        return -1
                    source_index = ending
                    pattern_index += 4
                    continue
                if following == 'f':
                    pattern_index += 2
                    if pattern_index >= len(pattern) or pattern[pattern_index] != '[':
                        raise PatternError("missing '[' after '%f' in pattern")
                    ending = _class_end(state, pattern_index)
                    previous = '\0' if source_index == 0 else source[source_index - 1]
                    current_char = source[source_index] \
                        if source_index < len(source) else '\0'
                    if (not _match_class_in_set(state, previous, pattern_index,
                                                ending - 1)) and \
                            _match_class_in_set(state, current_char,
                                                pattern_index, ending - 1):
                        pattern_index = ending
                        continue
                    return -1
                if following.isdigit():
                    result = _match_capture(state, source_index, int(following))
                    if result < 0:
                        return -1
                    source_index = result
                    pattern_index += 2
                    continue

            ending = _class_end(state, pattern_index)
            has_more = _single_match(state, source_index, pattern_index, ending)
            suffix = pattern[ending] if ending < len(pattern) else ''

            if suffix == '?':
                if has_more:
                    result = _match(state, source_index + 1, ending + 1)
                    if result != -1:
                        return result
                pattern_index = ending + 1
                continue
            if suffix == '+':
                return _max_expand(state, source_index + 1, pattern_index,
                                   ending) if has_more else -1
            if suffix == '*':
                return _max_expand(state, source_index, pattern_index, ending)
            if suffix == '-':
                return _min_expand(state, source_index, pattern_index, ending)
            if not has_more:
                return -1
            source_index += 1
            pattern_index = ending
    finally:
        state.depth -= 1


def _max_expand(state, source_index, pattern_index, ending):
    count = 0
    while _single_match(state, source_index + count, pattern_index, ending):
        count += 1
    while count >= 0:
        result = _match(state, source_index + count, ending + 1)
        if result != -1:
            return result
        count -= 1
    return -1


def _min_expand(state, source_index, pattern_index, ending):
    while True:
        result = _match(state, source_index, ending + 1)
        if result != -1:
            return result
        if _single_match(state, source_index, pattern_index, ending):
            source_index += 1
        else:
            return -1


def _start_capture(state, source_index, pattern_index, what):
    level = state.level
    if level >= MAXCAPTURES:
        raise PatternError('too many captures')
    state.capture_start[level] = source_index
    state.capture_len[level] = what
    state.level = level + 1
    result = _match(state, source_index, pattern_index)
    if result == -1:
        state.level -= 1
    return result


def _end_capture(state, source_index, pattern_index):
    level = _capture_to_close(state)
    state.capture_len[level] = source_index - state.capture_start[level]
    result = _match(state, source_index, pattern_index)
    if result == -1:
        state.capture_len[level] = CAP_UNFINISHED
    return result


def _match_capture(state, source_index, index):
    index -= 1
    if index < 0 or index >= state.level \
            or state.capture_len[index] == CAP_UNFINISHED:
        raise PatternError('invalid capture index')
    length = state.capture_len[index]
    text = state.source[state.capture_start[index]:
                        state.capture_start[index] + length]
    if state.source.startswith(text, source_index):
        return source_index + length
    return -1


def _captures(state, start, end, whole_when_empty=True):
    if state.level == 0 and whole_when_empty:
        return [state.source[start:end]]
    out = []
    for index in range(state.level):
        if state.capture_len[index] == CAP_POSITION:
            out.append(state.capture_start[index] + 1)
        else:
            begin = state.capture_start[index]
            out.append(state.source[begin:begin + state.capture_len[index]])
    return out


def find(source, pattern, init=1, plain=False):
    """Lua's `string.find`. Returns (start, end, captures) 1-based, or None."""
    start = _init_index(init, len(source))
    if start > len(source):
        return None
    if plain:
        position = source.find(pattern, start)
        if position < 0:
            return None
        return position + 1, position + len(pattern), []
    anchored = pattern.startswith('^')
    state = _Match(source, pattern[1:] if anchored else pattern)
    index = start
    while True:
        state.level = 0
        state.depth = 0
        end = _match(state, index, 0)
        if end != -1:
            return index + 1, end, _captures(state, index, end,
                                             whole_when_empty=False)
        index += 1
        if anchored or index > len(source):
            return None


def match(source, pattern, init=1):
    """Lua's `string.match`: the captures, or the whole match, or None."""
    found = find(source, pattern, init)
    if found is None:
        return None
    start, end, captures = found
    return captures if captures else [source[start - 1:end]]


def gmatch(source, pattern):
    """Every match in turn, as `string.gmatch` yields them."""
    anchored = pattern.startswith('^')
    state = _Match(source, pattern[1:] if anchored else pattern)
    index = 0
    while index <= len(source):
        state.level = 0
        state.depth = 0
        end = _match(state, index, 0)
        if end != -1:
            captures = _captures(state, index, end, whole_when_empty=False)
            yield captures if captures else [source[index:end]]
            index = end + 1 if end == index else end
        else:
            index += 1
        if anchored:
            return


def gsub(source, pattern, replace, limit=None):
    """`string.gsub`. `replace` is a string, a table or a callable."""
    anchored = pattern.startswith('^')
    state = _Match(source, pattern[1:] if anchored else pattern)
    out = []
    index = 0
    count = 0
    while limit is None or count < limit:
        state.level = 0
        state.depth = 0
        end = _match(state, index, 0)
        if end != -1:
            count += 1
            captures = _captures(state, index, end)
            whole = source[index:end]
            out.append(_substitute(replace, whole, captures))
            if end > index:
                index = end
            else:
                if index < len(source):
                    out.append(source[index])
                index += 1
        else:
            if index < len(source):
                out.append(source[index])
            index += 1
        if index > len(source) or anchored:
            break
    out.append(source[index:])
    return ''.join(out), count


def _substitute(replace, whole, captures):
    if callable(replace):
        produced = replace(*captures)
        if isinstance(produced, (list, tuple)):
            produced = produced[0] if produced else None
        return whole if produced is None or produced is False else _text(produced)
    if hasattr(replace, 'raw_get'):
        produced = replace.raw_get(captures[0])
        return whole if produced is None or produced is False else _text(produced)
    text = _text(replace)
    out = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == L_ESC and index + 1 < len(text):
            following = text[index + 1]
            if following.isdigit():
                number = int(following)
                if number == 0:
                    out.append(whole)
                else:
                    out.append(_text(captures[number - 1])
                               if number <= len(captures) else '')
                index += 2
                continue
            out.append(following)
            index += 2
            continue
        out.append(char)
        index += 1
    return ''.join(out)


def _text(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return value if isinstance(value, str) else str(value)


def _init_index(init, length):
    try:
        init = int(init)
    except (TypeError, ValueError):
        init = 1
    if init < 0:
        init = max(length + init, 0)
    elif init > 0:
        init -= 1
    return init
