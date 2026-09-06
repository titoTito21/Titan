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

#: **The helpers that name an action indirectly.** Several screens reach
#: Titan through one of their own - `rows("forums", "forums", {...})`,
#: `page("blocked", {}, ...)` - which end at `TitanUI.ask(@bus, "<addon>",
#: action, ...)` with the action in a VARIABLE, so the pattern above sees
#: nothing at all. Twenty-six calls were invisible to this check, which is
#: most of the Titan-Net screens.
#:
#: Which add-on a helper reaches is read out of the helper's own
#: definition, per file, rather than written down here: the same helper
#: name goes to `titannet` in one file, `macros` in another and `cling` in
#: a third, and a table would have said one of them and been wrong about
#: the rest.
HELPER = re.compile(
    r'def\s+(\w+)\(\s*(\w+)\s*,[^)]*\)\s*\n\s*'
    r'(?:\w+\s*=\s*)?TitanUI\.ask\(\s*@?\w+\s*,\s*"([a-z_]\w*)"\s*,\s*(\w+)')


def helpers_in(text):
    """{helper name: (add-on, which argument carries the arguments)}."""
    found = {}
    for match in HELPER.finditer(text):
        helper, first, addon, passed = match.groups()
        if passed != first:
            continue          # it passes something else as the action
        # The arguments are whatever comes after the action. `page(action,
        # args, header)` puts them next; `rows(action, key, args)` one
        # further along.
        names = _parameters(text, match.start())
        try:
            position = names.index(first) + 1
        except ValueError:
            position = 1
        found[helper] = (addon, position)
    return found


def _parameters(text, at):
    opened = text.index('(', at)
    closed = text.index(')', opened)
    return [one.strip().split('=')[0].strip()
            for one in text[opened + 1:closed].split(',') if one.strip()]


#: A key in a Ruby hash literal: `{"group_id" => id}`.
HASH_KEY = re.compile(r'"([a-z_][\w]*)"\s*=>')

#: A component's actions live on the module Titan loads, so they are read
#: out of the source rather than by importing it.
DECLARED = re.compile(r"['\"]name['\"]\s*:\s*['\"]([a-z_][\w]*)['\"]")


def literal_arguments(text, after, skip=0):
    """The keys of the hash literal a call passes, or None.

    None means "not written at the call site" - a variable, or a hash built
    somewhere else - and that is not something to complain about; it is
    something this check cannot see. Only a literal `{"a" => 1, "b" => 2}`
    is judged.
    """
    index = after
    # `rows("forums", "forums", {...})` - the hash is not the next
    # argument, so step over the ones in between.
    for _each in range(skip + 1):
        while index < len(text) and text[index] in ' \t\r\n':
            index += 1
        if index >= len(text) or text[index] != ',':
            return None
        index += 1
        if _each < skip:
            depth = 0
            while index < len(text):
                char = text[index]
                if char in '([{':
                    depth += 1
                elif char in ')]}':
                    if depth == 0:
                        return None
                    depth -= 1
                elif char == ',' and depth == 0:
                    break
                index += 1
    while index < len(text) and text[index] in ' \t\r\n':
        index += 1
    if index >= len(text) or text[index] != '{':
        return None
    # Only the keys of THIS hash. A nested one is somebody else's
    # argument - `{"request" => JSON.generate({"call" => ...})}` passes
    # `request` and nothing else - and counting its keys as ours is a
    # complaint about code that is right.
    depth, end, top = 0, index, []
    while end < len(text):
        char = text[end]
        if char == '{':
            depth += 1
            if depth == 1:
                start = end
        elif char == '}':
            depth -= 1
            if depth == 0:
                break
        elif depth == 1 and char == '"':
            match = HASH_KEY.match(text, end)
            if match:
                top.append(match.group(1))
        end += 1
    if depth:
        return None
    return set(top)


def bridge_calls():
    """{(addon, action): [(file, argument keys or None)]}."""
    found = {}
    for name in sorted(os.listdir(BRIDGE)):
        if not name.endswith('.rb'):
            continue
        text = open(os.path.join(BRIDGE, name), encoding='utf-8',
                    errors='replace').read()
        for match in CALL.finditer(text):
            addon, action = match.group(1), match.group(2)
            keys = literal_arguments(text, match.end())
            found.setdefault((addon, action), []).append((name, keys))
        helpers = helpers_in(text)
        if helpers:
            indirect = re.compile(r'\b(%s)\(\s*"([a-z_][\w]*)"'
                                  % '|'.join(sorted(helpers)))
            for match in indirect.finditer(text):
                helper, action = match.group(1), match.group(2)
                addon, position = helpers[helper]
                keys = literal_arguments(text, match.end(), skip=position - 1)
                found.setdefault((addon, action), []).append((name, keys))
    return found


def titan_parameters(addon_id, action):
    """{name: is it required} for one action, or None when nobody knows.

    Read off the live `ActionSpec`, so this is what the action really
    takes rather than a second list to keep in step.
    """
    try:
        from src.titan_core import actions
        found = actions.find_action(addon_id, action)
    except Exception:
        return None
    if not found:
        return None
    spec = found[1] if isinstance(found, tuple) else found
    params = getattr(spec, 'params', None)
    if not isinstance(params, dict):
        return None
    return {name: bool(detail.get('required'))
            for name, detail in params.items() if isinstance(detail, dict)}


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
    calls = bridge_calls()
    problems = []
    for (addon, action), sites in sorted(calls.items()):
        where = ', '.join(sorted({name for name, _keys in sites}))
        if addon not in known:
            problems.append("%s.%s - Titan has no add-on '%s' (%s)"
                            % (addon, action, addon, where))
            continue
        if action not in known[addon]:
            close = [name for name in sorted(known[addon])
                     if name.startswith(action[:4]) or action.startswith(name[:4])]
            problems.append("%s.%s - no such action%s (%s)"
                            % (addon, action,
                               '; did you mean %s?' % ', '.join(close) if close else '',
                               where))
            continue
        # **And the ARGUMENTS.** An action that exists, called with a name
        # it does not take, is not an error the user sees as one: a
        # required parameter that was not supplied becomes a QUESTION,
        # built from that parameter's own description, so passing `group`
        # to an action that wants `group_id` asked "this action needs group
        # id" and the screen never opened. Titan's two group actions
        # genuinely disagree about the name, which is how it happened.
        wanted = titan_parameters(addon, action)
        if wanted is None:
            continue
        for name, keys in sites:
            if keys is None:
                continue
            for key in sorted(keys - set(wanted)):
                close = [real for real in sorted(wanted)
                         if key in real or real in key]
                problems.append(
                    "%s.%s - passes '%s', which it does not take%s (%s)"
                    % (addon, action, key,
                       '; it wants %s' % ', '.join(close) if close else
                       '; it takes %s' % (', '.join(sorted(wanted)) or 'nothing'),
                       name))
            for required in sorted(name for name, is_it in wanted.items()
                                   if is_it):
                if required not in keys:
                    problems.append(
                        "%s.%s - never passes '%s', which it requires; "
                        "Titan will stop and ask for it (%s)"
                        % (addon, action, required, name))
    for line in problems:
        print(line)
    print('%d call%s checked, %d problem%s'
          % (len(calls), '' if len(calls) == 1 else 's',
             len(problems), '' if len(problems) == 1 else 's'))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
