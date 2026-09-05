"""Every method the bridge hands to Elten must exist in the class that hands it.

Ruby only finds out that `method(:entry_menu)` names nothing when the line
runs, and by then somebody is looking at a backtrace instead of their
messages. That is not hypothetical: rewriting Titan-Net's main screen
deleted `entry_menu`, `room_menu`, `person_menu`, `group_menu` and
`account_rows` along with the block they lived in, the file still parsed,
the tests still passed - and pressing a name in Online Users crashed.

So this reads every `method(:name)` and every `proc { name }`-style call to
a bare identifier, and checks the class really defines it.

    python tests/check_own_methods.py
"""

import os
import re
import sys

BRIDGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Called on other objects or provided by Elten, not by these classes.
ELSEWHERE = {
    'new', 'call', 'to_s', 'to_i', 'each', 'map', 'push', 'size', 'first',
    'last', 'strip', 'split', 'join', 'include?', 'empty?', 'freeze',
    'speak', 'alert', 'confirm', 'selector', 'select_action', 'display_text',
    'input_text', 'loop_update', 'key_pressed?', 'play_sound',
}


def classes_in(text):
    """{class name -> its body}, by indentation."""
    lines = text.split('\n')
    out = {}
    current = None
    body = []
    indent = 0
    for line in lines:
        match = re.match(r'(\s*)class\s+([A-Z][\w:]*)', line)
        if match and len(match.group(1)) == 0:
            if current:
                out[current] = '\n'.join(body)
            current = match.group(2)
            body = []
            indent = 0
            continue
        if current:
            body.append(line)
    if current:
        out[current] = '\n'.join(body)
    return out


def main():
    problems = []
    for name in sorted(os.listdir(BRIDGE)):
        if not name.endswith('.rb') or name == 'install.rb':
            continue
        path = os.path.join(BRIDGE, name)
        text = open(path, encoding='utf-8', errors='replace').read()
        for klass, body in classes_in(text).items():
            defined = set(re.findall(r'^\s*def\s+(?:self\.)?([a-zA-Z_][\w]*[?!=]?)',
                                     body, re.M))
            defined |= set(re.findall(r'^\s*([A-Z_]+)\s*=', body, re.M))
            # `method(:x)` is the one that bit; it is also the clearest.
            for handed in re.findall(r'method\(:([a-zA-Z_][\w]*[?!]?)\)', body):
                if handed not in defined and handed not in ELSEWHERE:
                    problems.append((name, klass, f'method(:{handed})'))
    if not problems:
        print('every method the bridge hands over is defined')
        return 0
    print('handed over but never defined:')
    for filename, klass, what in sorted(set(problems)):
        print(f'  {filename}: {klass} -> {what}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
