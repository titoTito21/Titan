# -*- coding: utf-8 -*-
"""The few lines of Python through which Titan finds an add-on in another
language.

Each kind's loader looks for one Python file - a Titan IM module's
``init.py``, a statusbar applet's ``main.py``, a TTS engine's
``__engine__.py`` - and skips a folder that has none. So beside the program
(``main.lua``, ``main.rb``...) Polyglot writes that file, and all it does is
hand the folder to ``adapters.bind``. It is written:

* when Polyglot starts (every add-on folder of every kind is looked at),
* when the examples are installed,
* by the ``polyglot.prepare_addons`` action and the window's button, which is
  what an author runs before packing an add-on.

A file that is not Polyglot's own is never touched: an add-on that has a
Python entry of its own is a Python add-on.
"""

import os

from . import runtimes

#: kind -> (data subdir, the Python file its loader looks for, manifest)
KINDS = {
    'im_module': ('titanIM_modules', 'init.py', '__im.TCE'),
    'widget': ('applets', 'init.py', 'applet.json'),
    'statusbar_applet': ('statusbar_applets', 'main.py', 'applet.json'),
    'launcher': ('launchers', 'init.py', '__launcher__.TCE'),
    'settings_interface': ('settings interfaces', 'init.py',
                           '__settings_ui__.TCE'),
    'shell_addon': ('shell addons', 'init.py', '__shell_addon__.TCE'),
    'gamepad_mode': ('gamepad/modes', 'mode.py', '__mode__.TCE'),
    'tts_engine': ('titantts engines', '__engine__.py', '__engine__.TCE'),
}

MARKER = '# Polyglot entry'

TEMPLATE = '''{marker} - written by Polyglot, do not edit.
# This {kind} is written in {language}: see {source}. Titan's loader looks
# for a Python file here, and this one hands the folder to Polyglot.
def _polyglot():
    import os, sys
    try:
        from src.platform_utils import discover_data_entries
        folder = discover_data_entries('components').get('polyglot')
    except Exception:
        folder = None
    if not folder:
        folder = os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
            'components', 'polyglot')
    if not os.path.isdir(os.path.join(folder, 'polyglotkit')):
        raise ImportError("{source} needs the Polyglot component, which "
                          "is not installed or is switched off.")
    if folder not in sys.path:
        sys.path.insert(0, folder)
    from polyglotkit import adapters
    return adapters


_polyglot().bind(globals(), {kind!r}, __file__, {source!r})
'''


def is_ours(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            return handle.read(len(MARKER)) == MARKER
    except OSError:
        return False


def source_of(folder, entry):
    """(path, runtime) of the add-on's program, or (None, None).

    ``main.<ext>`` first, then the entry's own name with another extension
    (``init.lua``, ``__engine__.rb``), then a manifest naming it with
    ``polyglot = file``.
    """
    base = os.path.splitext(entry)[0]
    candidates = []
    for stem in ('main', base, 'init'):
        for runtime in runtimes.all_runtimes():
            for ext in runtime.extensions:
                candidates.append((os.path.join(folder, stem + ext), runtime))
    for path, runtime in candidates:
        if os.path.isfile(path):
            return path, runtime
    named = _named_source(folder)
    if named:
        runtime = runtimes.for_file(named)
        if runtime is not None and os.path.isfile(named):
            return named, runtime
    return None, None


def _named_source(folder):
    for name in os.listdir(folder) if os.path.isdir(folder) else ():
        if not (name.endswith('.TCE') or name == 'applet.json'):
            continue
        path = os.path.join(folder, name)
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as handle:
                text = handle.read()
        except OSError:
            continue
        if name.endswith('.json'):
            import json
            try:
                value = json.loads(text).get('polyglot')
            except Exception:
                value = None
            if value:
                return os.path.join(folder, str(value))
            continue
        for line in text.splitlines():
            key, _sep, value = line.partition('=')
            if key.strip().lower() == 'polyglot' and value.strip():
                return os.path.join(folder, value.strip().strip('"'))
    return None


def stub_text(kind, source, runtime):
    return TEMPLATE.format(marker=MARKER, kind=kind,
                           language=runtime.name,
                           source=os.path.basename(source))


def ensure(kind, folder):
    """Write (or refresh) the folder's entry. Answers what happened:
    'written', 'current', 'python' (the add-on is Python), 'none' (nothing in
    a language Polyglot knows)."""
    subdir, entry, manifest = KINDS[kind]
    target = os.path.join(folder, entry)
    if not os.path.isfile(os.path.join(folder, manifest)):
        # Not an add-on of this kind at all (a TTS engine's helper folder,
        # a README): nothing is written into it.
        return 'none'
    if os.path.isfile(target) and not is_ours(target):
        return 'python'
    if kind == 'widget' and os.path.isfile(os.path.join(folder, 'main.py')) \
            and not is_ours(os.path.join(folder, 'main.py')):
        return 'python'
    source, runtime = source_of(folder, entry)
    if source is None:
        return 'none'
    text = stub_text(kind, source, runtime)
    try:
        with open(target, 'r', encoding='utf-8') as handle:
            if handle.read() == text:
                return 'current'
    except OSError:
        pass
    with open(target, 'w', encoding='utf-8') as handle:
        handle.write(text)
    _drop_stale_bytecode(target)
    return 'written'


def _drop_stale_bytecode(target):
    compiled = target + 'c'
    if os.path.isfile(compiled):
        try:
            os.remove(compiled)
        except OSError:
            pass


def folders(kind):
    """{name: folder} of every add-on of ``kind``, switched on or off."""
    subdir = KINDS[kind][0]
    try:
        from src.platform_utils import discover_data_entries
        try:
            return discover_data_entries(subdir, include_disabled=True)
        except TypeError:           # a Titan from before the Component Manager
            return discover_data_entries(subdir)
    except Exception:
        return {}


def ensure_all():
    """Every add-on of every kind. Answers {kind: [names written]}."""
    written = {}
    for kind in KINDS:
        for name, folder in folders(kind).items():
            if not os.path.isdir(folder):
                continue
            try:
                if ensure(kind, folder) == 'written':
                    written.setdefault(kind, []).append(name)
            except OSError as error:
                print('[polyglot] %s %s: %s' % (kind, name, error))
    return written


def foreign_addons():
    """[(kind, name, folder, source, runtime)] - every add-on of every kind
    written in another language."""
    found = []
    for kind, (subdir, entry, manifest) in KINDS.items():
        for name, folder in folders(kind).items():
            if not os.path.isdir(folder) or                     not os.path.isfile(os.path.join(folder, manifest)):
                continue
            target = os.path.join(folder, entry)
            if os.path.isfile(target) and not is_ours(target):
                continue
            source, runtime = source_of(folder, entry)
            if source is not None:
                found.append((kind, name, folder, source, runtime))
    return found
