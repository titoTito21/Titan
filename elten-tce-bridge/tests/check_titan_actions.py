"""Every action the bridge asks Titan for must be one Titan really has.

This is the check the stand-in Titan cannot make. `fake_titan.py` answers
whatever it is asked, so a screen calling an action that does not exist
passes every test here and then tells the user

    'Cling' has no action 'list_apps'. It offers: ...

which is the message they reported. The authority is Titan's OWN registry -
`src.titan_core.actions.list_addons()` - plus the components' `TITAN_ACTIONS`
declarations, which are Python lists on a module the ComponentManager loads
at run time and are therefore read statically here rather than by starting
Titan.

    python tests/check_titan_actions.py
"""

import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.dirname(HERE)
TITAN = os.path.dirname(BRIDGE)
sys.path.insert(0, TITAN)

#: `TitanUI.ask(bus, "titan", "views", ...)`, `TitanUI.perform(...)`,
#: `bus.call("titan", "bridge", ...)` and `call_sync` - the four ways this
#: add-on names an action. Whitespace and newlines between the arguments,
#: because a call that wrapped is still a call.
CALL = re.compile(
    r'(?:TitanUI\.(?:ask|perform)\s*\(\s*[^,]+|'
    r'(?:@?\w+)\.call(?:_sync)?\s*\(\s*)'
    r',?\s*"([a-z_][\w]*)"\s*,\s*"([a-z_][\w]*)"')

#: A component's actions live on the module Titan loads, so they are read
#: out of the source rather than by importing it.
DECLARED = re.compile(r"['\"]name['\"]\s*:\s*['\"]([a-z_][\w]*)['\"]")


def bridge_calls():
    """{(addon, action): [files]} for everything the bridge asks for."""
    found = {}
    for name in sorted(os.listdir(BRIDGE)):
        if not name.endswith('.rb'):
            continue
        text = open(os.path.join(BRIDGE, name), encoding='utf-8',
                    errors='replace').read()
        for addon, action in CALL.findall(text):
            found.setdefault((addon, action), []).append(name)
    return found


def titan_actions():
    """{addon id: {action names}} as Titan itself answers it."""
    from src.titan_core import actions
    known = {}
    for addon in actions.list_addons():
        known[addon['id']] = set(addon.get('actions') or [])
    # The components declare theirs in Python, on the module the manager
    # loads - so an unstarted Titan lists only the three generic ones.
    components = os.path.join(TITAN, 'data', 'components')
    if os.path.isdir(components):
        for name in os.listdir(components):
            init = os.path.join(components, name, 'init.py')
            if not os.path.isfile(init):
                continue
            text = open(init, encoding='utf-8', errors='replace').read()
            if 'TITAN_ACTIONS' not in text:
                continue
            declared = set(DECLARED.findall(text))
            key = name.lower().replace(' ', '_')
            for candidate in (name, name.lower(), key):
                if candidate in known:
                    known[candidate] |= declared
                    break
            else:
                known[key] = declared
    return known


def main():
    known = titan_actions()
    problems = []
    for (addon, action), files in sorted(bridge_calls().items()):
        if addon not in known:
            problems.append("%s.%s - Titan has no add-on '%s' (%s)"
                            % (addon, action, addon, ', '.join(sorted(set(files)))))
            continue
        if action not in known[addon]:
            close = [name for name in sorted(known[addon])
                     if name.startswith(action[:4]) or action.startswith(name[:4])]
            problems.append("%s.%s - no such action%s (%s)"
                            % (addon, action,
                               '; did you mean %s?' % ', '.join(close) if close else '',
                               ', '.join(sorted(set(files)))))
    for line in problems:
        print(line)
    print('%d call%s checked, %d problem%s'
          % (len(bridge_calls()), '' if len(bridge_calls()) == 1 else 's',
             len(problems), '' if len(problems) == 1 else 's'))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
