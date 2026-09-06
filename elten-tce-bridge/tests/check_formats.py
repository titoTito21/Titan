# -*- coding: utf-8 -*-
"""Every format specifier the bridge uses must be one RUBY has.

`%r` is Python's "write this the way it would be typed"; Ruby's is `%p`,
and Ruby answers `%r` with `ArgumentError: malformed format string` at the
moment the line RUNS - which a syntax check never reaches and a simulation
that never builds a screen never reaches either.

It cost a whole round: the line was a diagnostic added to find a reported
"malformed" error, so the note the rescue wrote was itself the fault. The
exception left the renderer, the console fell back to starting the
application in TCE, and what the user saw was a renderer that had stopped
rendering anything at all.

Only a literal used with the `%` OPERATOR is read - `strftime("%H:%M")` is
a different format language and its specifiers are none of this check's
business.
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.dirname(HERE)

#: What Ruby's `String#%` accepts (`sprintf`'s own table), plus `%%`, the
#: named forms `%<name>s` / `%{name}`, and `*` for a width taken from the
#: arguments.
RUBY = set('bBdiouxXeEfgGaAspc%<{')

#: A double-quoted literal used as the left side of the `%` operator.
FORMAT = re.compile(r'"((?:[^"\\]|\\.)*)"\s*%[\s\n]')
SPEC = re.compile(r'%[-+ 0#*\d.]*([A-Za-z%<{])')


def problems():
    out = []
    for name in sorted(os.listdir(BRIDGE)):
        if not name.endswith('.rb'):
            continue
        path = os.path.join(BRIDGE, name)
        text = io.open(path, encoding='utf-8').read()
        for match in FORMAT.finditer(text):
            line = text.count('\n', 0, match.start()) + 1
            for spec in SPEC.findall(match.group(1)):
                if spec not in RUBY:
                    out.append('%s:%d  %%%s is not a Ruby format specifier'
                               % (name, line, spec))
    return out


if __name__ == '__main__':
    found = problems()
    for line in found:
        print(line)
    print('%s' % ('every format specifier is one Ruby has'
                  if not found else '%d PROBLEM(S)' % len(found)))
    sys.exit(1 if found else 0)
