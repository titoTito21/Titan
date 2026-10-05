# -*- coding: utf-8 -*-
"""TA scripts: the user's own reader scripts, written in Titan Script.

A Titan Access script is a ``.tas`` file in the user's own folder
(``accessibility/scripts/`` beside every other store the reader keeps). It
is **Titan Script** - the language of Titan's macros, every statement of it,
every Titan action by name - with a few lines at the top that say WHEN the
reader runs it:

    when key "insert+j"                    the reader modifier and J
    when key "ctrl+shift+f12"              any key without the modifier
    when focus program="notepad" role="edit"
    when window program="explorer" title contains "Downloads"
    when reader starts

and with what it knows at that moment handed in as variables:
``{{name}}``, ``{{role}}``, ``{{value}}``, ``{{description}}`` of the
control in focus, ``{{window}}`` (its title), ``{{program}}`` (the process,
without ``.exe``) and ``{{key}}`` (what was pressed).

`say` in a TA script is the READER speaking - its voice, its queue - and
every Titan Access action is there to call (`titan_access.read_focused`,
`titan_access.say`, `titan_access.click_element`...) beside the rest of
Titan's. A script runs on a thread of its own, so a dialog it opens or a
`wait` it does never holds the reader.

The language itself is the Macro Manager's (`data/components/macros`),
reached in place rather than copied: one language, one checker, one set of
error messages, and a script that is valid as a macro is valid here.
"""

import importlib.util
import os
import re
import sys
import threading

_LOCK = threading.RLock()

EXTENSION = '.tas'

#: The reader's own triggers - the lines Titan Script itself does not know.
_TRIGGER = re.compile(r'^\s*when\s+(key|focus|window|reader)\b(.*)$',
                      re.IGNORECASE)
#: `for program "name"` - the script is about ONE program, the way a JAWS
#: script file is: its triggers and its rules apply only while that
#: program is in front.
_FOR = re.compile(r'^\s*for\s+program\s+"([^"]+)"\s*$', re.IGNORECASE)
#: `control <selectors> <change>` - what JAWS does with a window-class
#: reassignment, a label and a custom announcement: how one KIND of
#: control is read.
_CONTROL = re.compile(r'^\s*control\b(.*)$', re.IGNORECASE)
#: The changes a rule can make, after its selectors.
_CHANGE = re.compile(r'\b(as)\s+(\w+)|\b(name|describe|say)\s+"([^"]*)"'
                     r'|\b(silent)\b', re.IGNORECASE)
_ARG = re.compile(r'(\w+)\s*(contains)?\s*=?\s*"([^"]*)"', re.IGNORECASE)

_state = {'scripts': [], 'loaded_from': '', 'runs': 0, 'failed': 0,
          'last': '', 'errors': {}, 'engine': None, 'bound': []}


# --------------------------------------------------------------------------- #
# Where they live
# --------------------------------------------------------------------------- #
def folder():
    """``accessibility/scripts`` in the user's own data - made, with an
    example in it, the first time it is asked for."""
    try:
        from .portable import readerHome
        base = readerHome.folder()
    except Exception:                                # noqa: BLE001
        base = os.path.join(os.getenv('APPDATA') or os.path.expanduser('~'),
                            'titosoft', 'Titan', 'accessibility')
    where = os.path.join(base, 'scripts')
    if not os.path.isdir(where):
        try:
            os.makedirs(where, exist_ok=True)
            _write_example(where)
        except OSError:
            pass
    return where


EXAMPLE = '''# An example Titan Access script. Delete it, change it, copy it.
# Lines starting with "when" say when the reader runs the script; the rest
# is Titan Script - the language of Titan's macros.
when key "insert+shift+j"

if name is empty
    say "The control in focus has no name."
    stop
end
say "{{name}}, {{role}}, in {{program}}"
'''

README = '''Titan Access scripts
====================

Every .tas file in this folder is a reader script, written in Titan Script
(the language of Titan's macros - see the Macro Manager's Titan Script tab).

Put one or more trigger lines at the top:

    when key "insert+j"           with the reader modifier
    when key "ctrl+shift+f12"     any other key (the key is then the script's)
    when focus program="notepad" role="edit"
    when window program="explorer" title contains "Downloads"
    when reader starts

Variables: {{name}} {{role}} {{value}} {{description}} {{window}}
{{program}} {{key}}. "say" speaks in the reader's own voice.

Reload the scripts with the action titan_access.reload_scripts, or by
restarting the reader.
'''


def _write_example(where):
    for name, text in (('example' + EXTENSION, EXAMPLE),
                       ('README.txt', README)):
        path = os.path.join(where, name)
        if not os.path.exists(path):
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(text)


# --------------------------------------------------------------------------- #
# The language - the Macro Manager's
# --------------------------------------------------------------------------- #
def _macros():
    """The Macro Manager's module, already loaded or loaded from its file."""
    for name in ('macros', 'data.components.macros'):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, 'run_tcs_text'):
            return module
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(os.path.dirname(here), 'macros', 'init.py')
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location('macros', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['macros'] = module
    try:
        spec.loader.exec_module(module)
    except Exception:                                # noqa: BLE001
        sys.modules.pop('macros', None)
        return None
    return module


# --------------------------------------------------------------------------- #
# Reading a script
# --------------------------------------------------------------------------- #
def parse(text):
    """``(triggers, body, problems)``. The reader's trigger lines are taken
    out - replaced by blank lines, so Titan Script's line numbers stay the
    file's own - and everything else is Titan Script."""
    triggers, problems, lines = [], [], []
    rules, program = [], ''
    for number, raw in enumerate(str(text or '').splitlines(), start=1):
        scoped = _FOR.match(raw)
        if scoped:
            program = scoped.group(1).strip().lower()
            if program.endswith('.exe'):
                program = program[:-4]
            lines.append('')
            continue
        ruled = _CONTROL.match(raw)
        if ruled:
            lines.append('')
            rule, why = _rule(number, ruled.group(1))
            if rule is None:
                problems.append(why)
            else:
                rules.append(rule)
            continue
        found = _TRIGGER.match(raw)
        if not found:
            lines.append(raw)
            continue
        lines.append('')
        kind, rest = found.group(1).lower(), found.group(2).strip()
        trigger = {'kind': kind, 'line': number}
        if kind == 'key':
            spec = re.match(r'"([^"]+)"', rest)
            if not spec:
                problems.append('line %d: "when key" wants a key in quotes, '
                                'like when key "insert+j"' % number)
                continue
            trigger['spec'] = spec.group(1).strip().lower()
        elif kind == 'reader':
            if not rest.lower().startswith('start'):
                problems.append('line %d: the reader trigger is '
                                '"when reader starts"' % number)
                continue
        else:
            conditions = []
            for name, contains, value in _ARG.findall(rest):
                conditions.append((name.lower(), bool(contains),
                                   value.strip().lower()))
            trigger['conditions'] = conditions
        triggers.append(trigger)
    for one in triggers + rules:
        one['program'] = program
    PARSED_RULES[0] = rules
    return triggers, '\n'.join(lines), problems


#: The rules of the script `parse` read last (a side door, so `parse`'s
#: three answers stay what every caller already unpacks).
PARSED_RULES = [[]]

#: The role keys a rule may give a control (`as list`) - the reader's own.
def _known_roles():
    try:
        from titan_access import nvda_shape
        return set(nvda_shape.ROLE_NAMES)
    except Exception:                                # noqa: BLE001
        return set()


def _rule(number, rest):
    """``(rule, why)`` for the text after `control`."""
    changes = list(_CHANGE.finditer(rest))
    if not changes:
        return None, ('line %d: a control rule says what to change - '
                      'as <role>, name "...", describe "...", say "..." or '
                      'silent' % number)
    selectors_text = rest[:changes[0].start()]
    selectors = [(name.lower(), bool(contains), value.strip().lower())
                 for name, contains, value in _ARG.findall(selectors_text)]
    if not selectors:
        return None, ('line %d: a control rule says WHICH controls - '
                      'class="...", id="...", name="..." or role="..."'
                      % number)
    rule = {'line': number, 'selectors': selectors}
    for change in changes:
        if change.group(1):
            role = change.group(2).lower()
            if _known_roles() and role not in _known_roles():
                return None, ('line %d: "%s" is not a role the reader knows '
                              '(%s)' % (number, role,
                                        ', '.join(sorted(_known_roles()))))
            rule['as'] = role
        elif change.group(3):
            rule[change.group(3).lower()] = change.group(4)
        elif change.group(5):
            rule['silent'] = True
    return rule, ''


def check(text):
    """Every problem in a script: its triggers, and Titan Script's own
    check of the rest."""
    triggers, body, problems = parse(text)
    if not triggers and not PARSED_RULES[0]:
        problems.append('the script has no "when" line and no control rule, '
                        'so the reader never uses it')
    macros = _macros()
    if macros is not None:
        try:
            problems.extend(macros.check_tcs(body))
        except Exception as error:                   # noqa: BLE001
            problems.append('Titan Script could not check it: %s' % error)
    else:
        problems.append('Titan Script is not here: the Macro Manager '
                        'component is missing')
    return problems


def load():
    """Read every script in the folder. ``[script]``, each a dict with its
    name, path, triggers, body and problems."""
    where = folder()
    found = []
    try:
        names = sorted(os.listdir(where))
    except OSError:
        names = []
    for name in names:
        if not name.lower().endswith(EXTENSION):
            continue
        path = os.path.join(where, name)
        try:
            with open(path, 'r', encoding='utf-8-sig') as handle:
                text = handle.read()
        except OSError as error:
            found.append({'name': name, 'path': path, 'triggers': [],
                          'body': '', 'problems': [str(error)]})
            continue
        triggers, body, problems = parse(text)
        found.append({'name': name[:-len(EXTENSION)], 'path': path,
                      'triggers': triggers, 'body': body,
                      'rules': list(PARSED_RULES[0]),
                      'problems': problems, 'dir': where})
    with _LOCK:
        _state['scripts'] = found
        _state['loaded_from'] = where
    return found


def scripts():
    with _LOCK:
        return list(_state['scripts'])


# --------------------------------------------------------------------------- #
# Running one
# --------------------------------------------------------------------------- #
def _context(engine, obj=None, key=''):
    """What a script is told about the moment it runs."""
    if obj is None and engine is not None:
        obj = getattr(engine, 'current_object', None)
    found = {'name': '', 'role': '', 'value': '', 'description': '',
             'window': '', 'program': '', 'key': str(key or ''),
             'class': '', 'id': ''}
    if obj is not None:
        found['name'] = str(getattr(obj, 'name', '') or '')
        found['value'] = str(getattr(obj, 'value', '') or '')
        found['description'] = str(getattr(obj, 'description', '') or '')
        role = getattr(obj, 'role', '')
        try:
            from titan_access import localization
            found['role'] = localization.role_label(str(role)) or str(role)
        except Exception:                            # noqa: BLE001
            found['role'] = str(role or '')
        found['role_key'] = str(role or '')
        found['class'] = str(getattr(obj, 'class_name', '') or '')
        found['id'] = str(getattr(obj, 'automation_id', '') or '')
    found['window'], found['program'] = _window_and_program()
    return found


def _window_and_program():
    try:
        from .portable import readerApi
        window = readerApi.foreground()
        title = str(getattr(window, 'name', '') or '')
        program = str(getattr(getattr(window, 'appModule', None), 'appName',
                              '') or '')
    except Exception:                                # noqa: BLE001
        title, program = '', ''
    if not program:
        program = _foreground_process()
    return title, program


def _foreground_process():
    if not sys.platform.startswith('win'):
        return ''
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(user32.GetForegroundWindow(),
                                        ctypes.byref(pid))
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return ''
        try:
            size = wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(1024)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer,
                                                   ctypes.byref(size)):
                name = os.path.basename(buffer.value)
                return name[:-4] if name.lower().endswith('.exe') else name
        finally:
            kernel32.CloseHandle(handle)
    except Exception:                                # noqa: BLE001
        pass
    return ''


def _reader_voice(engine):
    """`say` for a TA script: the reader's own voice."""
    def speak(text, interrupt=False, wait=False, position=None, pitch=None):
        if engine is None:
            raise RuntimeError('no reader')
        engine.speak(str(text), interrupt=bool(interrupt))
    return speak


def run(script, obj=None, key='', engine=None, wait=False):
    """Run one script on a thread of its own. ``(started, why)``."""
    engine = engine or _state.get('engine')
    macros = _macros()
    if macros is None:
        return False, 'Titan Script is not here'
    if script.get('problems'):
        return False, '; '.join(script['problems'])
    variables = _context(engine, obj, key)

    def work():
        try:
            ok, transcript = macros.run_tcs_text(
                script.get('body', ''), announce=True,
                base_dir=script.get('dir', ''),
                title=script.get('name', ''), variables=variables,
                speak=_reader_voice(engine))
        except Exception as error:                   # noqa: BLE001
            ok, transcript = False, ['%s: %s' % (type(error).__name__, error)]
        with _LOCK:
            _state['runs'] += 1
            _state['last'] = script.get('name', '')
            if not ok:
                _state['failed'] += 1
                _state['errors'][script.get('name', '')] = \
                    '; '.join(str(one) for one in transcript[-3:])

    thread = threading.Thread(target=work, daemon=True,
                              name='TitanAccessScript')
    thread.start()
    if wait:
        thread.join(30)
    return True, ''


def by_name(name):
    wanted = str(name or '').strip().lower()
    for script in scripts():
        if script['name'].lower() == wanted:
            return script
    return None


# --------------------------------------------------------------------------- #
# Triggers - asked by the engine
# --------------------------------------------------------------------------- #
def _matches(conditions, values):
    for name, contains, wanted in conditions:
        have = str(values.get(name, values.get(name + '_key', '')) or '')
        have = have.lower()
        if contains:
            if wanted not in have:
                return False
        elif have != wanted and not (name == 'role' and wanted
                                      == str(values.get('role_key', '')
                                             ).lower()):
            return False
    return True


def on_focus(obj, engine=None):
    """The focus moved: run every script whose `when focus` matches."""
    _on_event('focus', obj, engine)


def on_window(obj, engine=None):
    """The window in front changed: run every `when window` script."""
    _on_event('window', obj, engine)


def _on_event(kind, obj, engine):
    candidates = [(script, trigger) for script in scripts()
                  for trigger in script['triggers']
                  if trigger['kind'] == kind and not script['problems']]
    if not candidates:
        return
    engine = engine or _state.get('engine')
    values = _context(engine, obj)
    values['title'] = values['window']
    for script, trigger in candidates:
        if _in_program(trigger, values) and \
                _matches(trigger.get('conditions') or [], values):
            run(script, obj=obj, engine=engine)


def _in_program(one, values):
    wanted = one.get('program') or ''
    return not wanted or str(values.get('program', '')).lower() == wanted


def plain_key(name, ctrl, alt, shift, engine=None):
    """A key WITHOUT the reader modifier. True when a script took it."""
    pressed = _spec(name, ctrl, alt, shift, False)
    program = None
    for script in scripts():
        for trigger in script['triggers']:
            if trigger['kind'] == 'key' and not script['problems'] \
                    and _normalise(trigger['spec']) == pressed:
                if trigger.get('program'):
                    if program is None:
                        program = _foreground_process().lower()
                    if program != trigger['program']:
                        continue
                run(script, key=trigger['spec'], engine=engine)
                return True
    return False


def _normalise(spec):
    parts = [part.strip().lower() for part in str(spec or '').split('+')
             if part.strip()]
    aliases = {'control': 'ctrl', 'nvda': 'insert', 'ta': 'insert',
               'enter': 'return'}
    parts = [aliases.get(part, part) for part in parts]
    order = ('insert', 'ctrl', 'alt', 'shift')
    mods = [one for one in order if one in parts]
    base = [part for part in parts if part not in order]
    return '+'.join(mods + base)


def _spec(name, ctrl, alt, shift, insert):
    parts = []
    if insert:
        parts.append('insert')
    if ctrl:
        parts.append('ctrl')
    if alt:
        parts.append('alt')
    if shift:
        parts.append('shift')
    parts.append(str(name or '').lower())
    return _normalise('+'.join(parts))


def bind(engine):
    """Load the scripts and give the ones with the reader modifier their
    keys, in FRONT of the reader's own - a user's script is a deliberate
    choice to change what a key does. Fires `when reader starts`."""
    with _LOCK:
        _state['engine'] = engine
    gestures = getattr(engine, 'gestures', None)
    with _LOCK:
        for action_id in _state['bound']:
            try:
                gestures.unregister(action_id)
            except Exception:                        # noqa: BLE001
                pass
        _state['bound'] = []
    found = load()
    for script in found:
        if script['problems']:
            continue
        for trigger in script['triggers']:
            if trigger['kind'] != 'key':
                continue
            spec = _normalise(trigger['spec'])
            if not spec.startswith('insert+') or gestures is None:
                continue
            action_id = 'script:%s:%s' % (script['name'], spec)
            try:
                binding = gestures.register(
                    action_id, spec,
                    lambda one=script, key=spec, scope=trigger.get('program'):
                    _run_scoped(one, key, scope))
                gestures._bindings.remove(binding)
                gestures._bindings.insert(0, binding)
                binding.name = script['name']
                binding.description = 'Titan Access script'
                with _LOCK:
                    _state['bound'].append(action_id)
            except Exception:                        # noqa: BLE001
                continue
    for script in found:
        if any(trigger['kind'] == 'reader' for trigger in script['triggers']) \
                and not script['problems']:
            run(script, engine=engine)
    return found


def _run_scoped(script, key, program):
    """A modifier key of a program's script: that script's in that program,
    the reader's own everywhere else."""
    if program and _foreground_process().lower() != program:
        return _fall_through(key)
    return run(script, key=key)


def _fall_through(key):
    """The reader's own binding for a key a scoped script did not take."""
    engine = _state.get('engine')
    gestures = getattr(engine, 'gestures', None)
    if gestures is None:
        return False
    for binding in gestures._bindings:
        if binding.action_id.startswith('script:'):
            continue
        spec = _normalise(binding.key_spec if binding.insert or
                          'insert' in binding.key_spec.lower()
                          else 'insert+' + binding.key_spec)
        if spec == key:
            binding.handler()
            return True
    return False


# --------------------------------------------------------------------------- #
# Control rules - how one KIND of control is read (JAWS's reclassing,
# labels and custom announcements)
# --------------------------------------------------------------------------- #
def _rule_matches(rule, values):
    if not _in_program(rule, values):
        return False
    for name, contains, wanted in rule['selectors']:
        if name == 'role':
            have = str(values.get('role_key', '')).lower()
        else:
            have = str(values.get(name, '') or '').lower()
        if contains:
            if wanted not in have:
                return False
        elif have != wanted:
            return False
    return True


def adjust(obj):
    """``(obj, say)`` - the control as the user's rules say it is read.

    ``obj`` is a COPY with the role, name or description the rules gave it
    (the reader's own object is never changed); ``say`` is the user's own
    announcement for it - '' for none, None when a rule made it silent."""
    rules = [rule for script in scripts() for rule in script.get('rules', ())
             if not script['problems']]
    if not rules or obj is None:
        return obj, ''
    values = None
    say = ''
    changed = None
    for rule in rules:
        if values is None:
            values = _context(None, obj)
        if not _rule_matches(rule, values):
            continue
        if changed is None:
            try:
                import copy
                changed = copy.copy(obj)
            except Exception:                        # noqa: BLE001
                return obj, ''
        if rule.get('as'):
            changed.role = rule['as']
        if 'name' in rule:
            changed.name = _fill(rule['name'], values)
        if 'describe' in rule:
            changed.description = _fill(rule['describe'], values)
        if rule.get('silent'):
            say = None
        elif 'say' in rule:
            say = _fill(rule['say'], values)
        with _LOCK:
            _state['adjusted'] = _state.get('adjusted', 0) + 1
    return (changed if changed is not None else obj), say


def _fill(template, values):
    return re.sub(r'\{\{\s*(\w+)\s*\}\}',
                  lambda found: str(values.get(found.group(1), '')),
                  str(template or ''))


def report():
    with _LOCK:
        found = {key: value for key, value in _state.items()
                 if key not in ('engine', 'scripts')}
        found['scripts'] = [{'name': one['name'],
                             'triggers': [t['kind'] for t in one['triggers']],
                             'rules': len(one.get('rules', [])),
                             'problems': one['problems']}
                            for one in _state['scripts']]
    return found
