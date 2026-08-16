# -*- coding: utf-8 -*-
"""
What a generated add-on is checked against: Titan itself.

The AI creation kit's failure mode is not bad code - the model writes valid
Python readily enough - it is **invention**: a function Titan never calls, a
module that does not exist, an argument nobody reads, an action no add-on
declares. All of it imports cleanly, none of it raises where the user can
see, and the add-on simply does nothing. So every generated file is read
here before it is saved, and every claim it makes is checked against the
running program:

- an ``import`` of anything under ``src.`` must name a module that is really
  there, and a name that module really has;
- an attribute read off such a module must be one it defines;
- an action called by name must be one the Action API really offers (for
  Titan's own providers, which are always installed);
- a manifest key or section must be one that kind's manager reads - learned
  from the add-ons of that kind that already work and from the kind's own
  guide, never from a table typed in here;
- the two kinds with a hook contract (shell add-ons, settings interfaces)
  are checked against their live hook tables and API classes.

Everything reported is phrased as an instruction, because it is fed straight
back to the model by the auto-fix loop: naming the thing it meant is what
turns a refusal into a correction.

Nothing here imports a generated file or a Titan module for its own sake -
the checks are all `ast`, so checking is safe even when the add-on it is
checking is not.
"""

import ast
import configparser
import json
import os
import re

from src import platform_utils

# A module under this prefix is Titan's own, and is the only kind of import
# this module has an opinion about.
_TITAN_PREFIX = 'src.'

# Attribute names every module has.
_ALWAYS = {'__name__', '__file__', '__doc__', '__dict__', '__loader__',
           '__spec__', '__package__', '__path__', '__builtins__'}

# Emoji, and only emoji: the pictograph blocks plus the variation selector
# that turns a symbol into one. Deliberately NOT the arrows (U+2190-21FF) or
# the technical symbols - Titan's own apps write "File -> Settings" with a
# real arrow, and refusing that would be a false alarm in the one place a
# false alarm costs most, an auto-fix round that removes correct text.
_EMOJI = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27bf\u2b00-\u2bff'
                    '\ufe0f\u2049\u203c]')

# Providers that are part of Titan itself, so an action named on one of them
# can be checked: an add-on the user has not installed cannot.
_BUILTIN_PROVIDERS = ('titan', 'settings', 'system', 'shell', 'desktop', 'ui',
                      'web', 'ocr', 'memory', 'im', 'titannet', 'elten',
                      'gamepad')

_module_cache = {}
_manifest_cache = {}
_actions_cache = {}


# --------------------------------------------------------------------------
# Reading Titan without importing it
# --------------------------------------------------------------------------
def _module_file(dotted):
    """The file `src.a.b` lives in, or None."""
    relative = dotted.split('.')
    candidates = [os.path.join(*relative) + '.py',
                  os.path.join(*relative, '__init__.py')]
    for candidate in candidates:
        found = platform_utils.get_resource_path(candidate)
        if found and os.path.isfile(found):
            return found
    return None


def _module_names(dotted):
    """Every name `from <dotted> import ...` could legally ask for.

    Read out of the module's own source with `ast` - importing it would run
    it, and this may be a Titan that is only half started. `None` means
    "cannot tell", and nothing is reported for such a module.
    """
    if dotted in _module_cache:
        return _module_cache[dotted]
    path = _module_file(dotted)
    if path is None:
        _module_cache[dotted] = None
        return None
    try:
        with open(path, encoding='utf-8', errors='replace') as handle:
            tree = ast.parse(handle.read(), filename=path)
    except (OSError, SyntaxError):
        _module_cache[dotted] = None
        return None
    names = set(_ALWAYS)
    dynamic = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target,
                                                            ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Global):
            # `global speaker` in a function is how half of Titan's modules
            # create an attribute; it is there at run time and nowhere in
            # the module's own body.
            names.update(node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == '*':
                    dynamic = True
                else:
                    names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Call):
            # A module that builds its own namespace cannot be judged by
            # what is written in it.
            function = node.func
            if isinstance(function, ast.Name) and function.id in ('globals',
                                                                  'setattr',
                                                                  'exec'):
                dynamic = True
    # Submodules of a package are importable names too.
    package_dir = os.path.dirname(_module_file(dotted) or '')
    if package_dir and os.path.basename(_module_file(dotted) or '') == \
            '__init__.py':
        try:
            for entry in os.listdir(package_dir):
                if entry.endswith('.py'):
                    names.add(entry[:-3])
                elif os.path.isdir(os.path.join(package_dir, entry)):
                    names.add(entry)
        except OSError:
            pass
    answer = None if dynamic else names
    _module_cache[dotted] = answer
    return answer


def _titan_actions():
    """{provider id: {action names}} for Titan's own providers."""
    if _actions_cache:
        return _actions_cache
    try:
        from src.titan_core import actions
        for addon in actions.list_addons():
            names = set()
            for action in addon.get('actions', ()):
                names.add(action['name'] if isinstance(action, dict)
                          else str(action))
            _actions_cache[str(addon.get('id'))] = names
    except Exception:
        _actions_cache['__failed__'] = set()
    return _actions_cache


# --------------------------------------------------------------------------
# Little helpers shared by the checks
# --------------------------------------------------------------------------
def did_you_mean(name, candidates):
    import difflib
    close = difflib.get_close_matches(str(name), sorted(candidates), n=1,
                                      cutoff=0.72)
    return close[0] if close else None


def _suggestion(name, candidates, prefix=''):
    guess = did_you_mean(name, candidates)
    return f" - did you mean {prefix}{guess}?" if guess else ""


def python_files(files):
    """Every generated Python file, parsed. Unparsable ones are skipped -
    the syntax pass has already reported them."""
    for path, content in files.items():
        if not path.lower().endswith('.py'):
            continue
        try:
            yield path, ast.parse(content, filename=path)
        except SyntaxError:
            continue


# --------------------------------------------------------------------------
# 1. Imports of Titan's own modules
# --------------------------------------------------------------------------
def check_titan_imports(files):
    """`from src.x import y` must name a module and a name that exist."""
    problems = []
    for path, tree in python_files(files):
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not alias.name.startswith(_TITAN_PREFIX):
                        continue
                    if _module_file(alias.name) is None:
                        problems.append(
                            f"{path}: there is no module {alias.name} in "
                            f"Titan.")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                if node.level or not module.startswith(_TITAN_PREFIX):
                    continue
                names = _module_names(module)
                if _module_file(module) is None:
                    problems.append(
                        f"{path}: there is no module {module} in Titan.")
                    continue
                if names is None:
                    continue
                for alias in node.names:
                    if alias.name == '*' or alias.name in names:
                        continue
                    if _module_file(f"{module}.{alias.name}") is not None:
                        continue
                    problems.append(
                        f"{path}: {module} has no {alias.name}"
                        + (_suggestion(alias.name, names) or "."))
    return problems


# --------------------------------------------------------------------------
# 2. Attributes read off a Titan module
# --------------------------------------------------------------------------
def check_titan_attributes(files):
    """`sound.play_notification(...)` when `sound` is `src.titan_core.sound`."""
    problems = []
    for path, tree in python_files(files):
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(_TITAN_PREFIX) and alias.asname:
                        aliases[alias.asname] = alias.name
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                if node.level or not module.startswith(_TITAN_PREFIX):
                    continue
                for alias in node.names:
                    full = f"{module}.{alias.name}"
                    if _module_file(full) is not None:
                        aliases[alias.asname or alias.name] = full
        # A name that is assigned anywhere in the file is not reliably the
        # module any more - `actions = []` shadows `from ... import actions`,
        # and `actions.append(...)` is then a list, not a missing action.
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = getattr(node, 'targets', None) or [node.target]
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                targets = [node.target]
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                arguments = node.args
                for argument in (list(arguments.args)
                                 + list(getattr(arguments, 'posonlyargs', []))
                                 + list(arguments.kwonlyargs)):
                    aliases.pop(argument.arg, None)
            elif isinstance(node, ast.withitem) and node.optional_vars:
                targets = [node.optional_vars]
            for target in targets:
                if isinstance(target, ast.Name):
                    aliases.pop(target.id, None)
        if not aliases:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in aliases):
                continue
            module = aliases[node.value.id]
            names = _module_names(module)
            if names is None or node.attr in names:
                continue
            problems.append(
                f"{path}: {module} has no {node.attr}"
                + (_suggestion(node.attr, names) or "."))
    return problems


# --------------------------------------------------------------------------
# 3. Actions called by name
# --------------------------------------------------------------------------
_ACTION_CALLERS = ('run_action', 'run', 'call', 'call_sequence')


def check_action_calls(files):
    """An action named on one of Titan's own providers must exist."""
    known = _titan_actions()
    if '__failed__' in known:
        return []
    problems = []
    for path, tree in python_files(files):
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = getattr(function, 'attr', None) or getattr(function, 'id',
                                                              None)
            if name not in _ACTION_CALLERS or len(node.args) < 2:
                continue
            provider, action = node.args[0], node.args[1]
            if not (isinstance(provider, ast.Constant)
                    and isinstance(action, ast.Constant)
                    and isinstance(provider.value, str)
                    and isinstance(action.value, str)):
                continue
            if provider.value not in _BUILTIN_PROVIDERS:
                continue          # an add-on the user may or may not have
            actions = known.get(provider.value)
            if not actions or action.value in actions:
                continue
            problems.append(
                f"{path}: {provider.value} has no action "
                f"'{action.value}'"
                + (_suggestion(action.value, actions)
                   or f" - it has: {', '.join(sorted(actions))}."))
    return problems


# --------------------------------------------------------------------------
# 4. The project's own rule about emoji
# --------------------------------------------------------------------------
def check_no_emoji(files):
    """Titan's user-facing text never contains one - a screen reader reads
    it out, in whatever words its own dictionary has.

    Only what is really text: the string literals of a Python file (a
    comment is for the author) and every line of a manifest or a catalogue,
    which are text from end to end.
    """
    problems = []
    for path, content in files.items():
        low = path.lower()
        found = None
        if low.endswith('.py'):
            try:
                tree = ast.parse(content, filename=path)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and \
                        isinstance(node.value, str) and \
                        _EMOJI.search(node.value):
                    found = getattr(node, 'lineno', None)
                    break
        elif low.endswith(('.json', '.tce', '.po', '.tcs', '.txt')):
            for number, line in enumerate(content.splitlines(), 1):
                if _EMOJI.search(line):
                    found = number
                    break
        if found is not None:
            problems.append(
                f"{path}: line {found} has an emoji in its text - Titan's "
                f"never does, because a screen reader reads it out.")
    return problems


# --------------------------------------------------------------------------
# 5. The manifest, learned from the add-ons that already work
# --------------------------------------------------------------------------
_UNIVERSAL_KEYS = {'name', 'description', 'author', 'version', 'status',
                   'libs'}


def _guide_manifest_keys(kind_id):
    """The keys the kind's own guide shows in an ini/json manifest block."""
    keys, sections = set(), set()
    try:
        from src.ai import creation_docs
        text = creation_docs.load_guide(kind_id)
    except Exception:
        text = ''
    if not text:
        return keys, sections
    fence = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('```'):
            fence = stripped[3:].strip().lower() or None
            continue
        if fence not in ('ini', 'json'):
            continue
        match = re.match(r'^\s*\[([^\]]+)\]\s*$', line)
        if match:
            sections.add(match.group(1).strip().lower())
            continue
        match = re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=', line)
        if match:
            keys.add(match.group(1).lower())
            continue
        match = re.match(r'^\s*"([A-Za-z_][A-Za-z0-9_]*)"\s*:', line)
        if match:
            keys.add(match.group(1).lower())
    return keys, sections


def manifest_facts(kind):
    """What this kind's manifest really looks like.

    `{'keys', 'sections', 'sectionless', 'known'}` - learned from every
    installed add-on of the kind and from the kind's guide. `known` is False
    when nothing could be learned, and then nothing is reported: a check that
    does not know cannot refuse.
    """
    kind_id = kind.get('id') if isinstance(kind, dict) else str(kind)
    if kind_id in _manifest_cache:
        return _manifest_cache[kind_id]
    manifest = (kind.get('manifests') or (None,))[0] if isinstance(kind, dict) \
        else None
    facts = {'keys': set(), 'sections': set(), 'sectionless': False,
             'known': False, 'manifest': manifest}
    if not manifest or not kind.get('subdir'):
        _manifest_cache[kind_id] = facts
        return facts
    seen = sectionless = 0
    try:
        entries = platform_utils.discover_data_entries(kind['subdir'])
    except Exception:
        entries = {}
    for _name, path in entries.items():
        full = os.path.join(path, manifest)
        if not os.path.isfile(full):
            continue
        try:
            with open(full, encoding='utf-8', errors='replace') as handle:
                text = handle.read()
        except OSError:
            continue
        seen += 1
        if manifest.lower().endswith('.json'):
            try:
                facts['keys'] |= {str(key).lower()
                                  for key in json.loads(text)}
            except Exception:
                pass
            continue
        parser = configparser.ConfigParser()
        try:
            parser.read_string(text)
            for section in parser.sections():
                facts['sections'].add(section.lower())
                facts['keys'] |= {key.lower()
                                  for key in parser.options(section)}
        except Exception:
            sectionless += 1
            for line in text.splitlines():
                match = re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=', line)
                if match:
                    facts['keys'].add(match.group(1).lower())
    guide_keys, guide_sections = _guide_manifest_keys(kind_id)
    facts['keys'] |= guide_keys | _UNIVERSAL_KEYS
    facts['sections'] |= guide_sections
    facts['sectionless'] = bool(seen) and sectionless == seen
    facts['known'] = bool(seen) or bool(guide_keys)
    _manifest_cache[kind_id] = facts
    return facts


def check_manifest(kind, files):
    """The manifest must be shaped the way that kind's manager reads it."""
    if not isinstance(kind, dict):
        return []
    facts = manifest_facts(kind)
    manifest = facts['manifest']
    if not manifest or not facts['known']:
        return []
    content = None
    for path, text in files.items():
        if os.path.basename(path) == manifest:
            content = text
            break
    if content is None:
        return []                     # validate_files says this already
    problems = []
    if manifest.lower().endswith('.json'):
        try:
            data = json.loads(content)
        except Exception:
            return []                 # the JSON pass reports it
        if isinstance(data, dict):
            for key in data:
                if str(key).lower() in facts['keys']:
                    continue
                problems.append(
                    f"{manifest}: '{key}' is not a key Titan reads"
                    + (_suggestion(key, facts['keys'])
                       or f" - they are: {', '.join(sorted(facts['keys']))}."))
        return problems

    parser = configparser.ConfigParser()
    try:
        parser.read_string(content)
        parsed = True
    except Exception:
        parsed = False
    if facts['sectionless']:
        if parsed and parser.sections():
            problems.append(
                f"{manifest}: it is a plain list of key = value lines - "
                f"every {kind['label']} Titan has is written that way, with "
                f"no [section] heading.")
        keys = {match.group(1).lower() for match in
                (re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=', line)
                 for line in content.splitlines()) if match}
    else:
        if not parsed:
            problems.append(f"{manifest}: not a readable INI file.")
            return problems
        keys = set()
        for section in parser.sections():
            if facts['sections'] and section.lower() not in facts['sections']:
                guess = did_you_mean(section.lower(), facts['sections'])
                reads = ', '.join('[' + name + ']'
                                  for name in sorted(facts['sections']))
                problems.append(
                    f"{manifest}: [{section}] is not a section Titan reads"
                    + (f" - did you mean [{guess}]?" if guess
                       else f" - it reads: {reads}."))
            keys |= {key.lower() for key in parser.options(section)}
    for key in sorted(keys):
        base = re.sub(r'_[a-z]{2}$', '', key)
        if key in facts['keys'] or base in facts['keys']:
            continue
        problems.append(
            f"{manifest}: '{key}' is not a key Titan reads"
            + (_suggestion(key, facts['keys'])
               or f" - they are: {', '.join(sorted(facts['keys']))}."))
    return problems


# --------------------------------------------------------------------------
# What the kit calls
# --------------------------------------------------------------------------
def check_everything(files, kind=None):
    """Every check that applies, in the order a reader would want them."""
    problems = []
    for check in (check_titan_imports, check_titan_attributes,
                  check_action_calls, check_no_emoji):
        try:
            problems += check(files)
        except Exception as error:        # pragma: no cover - defensive
            print(f"[AI creation kit] {check.__name__} failed: {error}")
    if isinstance(kind, dict):
        try:
            problems += check_manifest(kind, files)
        except Exception as error:        # pragma: no cover - defensive
            print(f"[AI creation kit] manifest check failed: {error}")
    return problems


def forget_cached_facts():
    """For tests, and for a Titan whose add-ons changed while it ran."""
    _module_cache.clear()
    _manifest_cache.clear()
    _actions_cache.clear()
