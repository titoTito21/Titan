# -*- coding: utf-8 -*-
"""The reader's own settings as a walked list (Insert+Ctrl+G).

The NVDA add-on walks TITAN's settings category first, then the controls,
with Enter doing the one obvious thing to each kind (`portable/titanWalk`).
This is the same shape over THIS reader's own store: the sections of the
Titan Access settings page - Speech, General, Verbosity, Navigation, Dial,
Reader, Sounds and switches, Braille, Text editing - and every switch in
each, read as "label: value" and changed in place. A tick box flips, a
choice opens its answers as a level with the one in force marked, a
number opens its values, a text asks for one.

**It needs no window.** The settings page in Titan's settings window
(`settings_panel.py`) is a wx page; a user whose reader is the only thing
telling them what is on the screen should not have to find it. This reads
and writes `settings_store` directly - the same INI the page writes - and
tells the running engine to apply what changed, so the two never disagree.

The schema below is written out of `settings_panel.py`'s builders, key for
key, and `tests/test_titan_access_reading.py` checks that every key the
page reads is here and nothing here is unknown to the page.
"""

import threading

from titan_access.localization import L
from titan_access.settings_store import (
    get_settings, AnnouncementMode, ScreenReaderModifier, KeyboardEchoSetting,
)

_LOCK = threading.RLock()
_counted = {'opened': 0, 'sections': 0, 'changed': 0}
#: The section being walked and its rows, so a level can be put back.
_open = {'section': '', 'rows': [], 'at': 0}


# --------------------------------------------------------------------------- #
# The schema: (ini section, key, label key, kind, extra, default)
# --------------------------------------------------------------------------- #
#: Read out of `settings_schema` - the one description of every setting -
#: in the shape this walker has always used. Kinds: bool, choice (extra =
#: callable or list answering [(value, label key)]), range (extra =
#: (minimum, maximum, step)), text, engines, voices, scheme, braille_table.
from titan_access import settings_schema as _schema

SCHEMA = _schema.as_walk_schema()

#: Which program's profile is being edited, or '' for the global settings.
_scope = {'program': ''}


def scope():
    return _scope['program']


def report():
    with _LOCK:
        return dict(_counted)


def forget():
    with _LOCK:
        _counted.update({'opened': 0, 'sections': 0, 'changed': 0})
        _open.update({'section': '', 'rows': [], 'at': 0})


# --------------------------------------------------------------------------- #
# Reading and writing one setting
# --------------------------------------------------------------------------- #
def _store():
    return get_settings()


def _options(entry, engine=None):
    """``[(value, label)]`` for a choice-like entry."""
    _section, _key, _label, kind, extra, _default = entry
    if kind == 'choice':
        rows = extra() if callable(extra) else (extra or [])
        return [(value, L(key)) for value, key in rows]
    if kind == 'range':
        low, high, step = extra
        return [(value, str(value)) for value in range(low, high + 1, step)]
    if kind == 'scheme':
        try:
            from .portable import speechSchemes
            return [(key, label) for key, label in speechSchemes.names()]
        except Exception:                            # noqa: BLE001
            return []
    if kind == 'engines':
        try:
            from . import settings_panel
            return [(str(one), str(one)) for one in settings_panel._engine_ids()]
        except Exception:                            # noqa: BLE001
            return []
    if kind == 'voices':
        pairs = []
        try:
            speech = getattr(engine, 'speech', None)
            voices = speech.get_voices() if speech is not None else []
        except Exception:                            # noqa: BLE001
            voices = []
        for one in voices or []:
            if isinstance(one, dict):
                shown = one.get("display_name") or one.get("name") \
                    or one.get("id") or str(one)
                pairs.append((str(one.get("id") or one.get("name") or shown),
                              str(shown)))
            else:
                pairs.append((str(one), str(one)))
        return pairs
    if kind == 'braille_table':
        rows = [('', L('settings.braille.autoTable'))]
        try:
            from . import braille
            rows.extend((name, label) for name, label in braille.tables_available())
        except Exception:                            # noqa: BLE001
            pass
        return rows
    return []


def value_of(entry, store=None):
    """What the setting holds now, as the store keeps it - or, while a
    program's profile is being edited, what THAT profile says (the global
    value where the profile says nothing)."""
    store = store or _store()
    section, key, _label, kind, _extra, default = entry
    program = _scope['program']
    if program and key:
        try:
            from titan_access import profiles
            kept = profiles.get(program, section, key)
        except Exception:                            # noqa: BLE001
            kept = None
        if kept is not None:
            if kind == 'bool':
                return str(kept).strip().lower() in ('true', '1', 'yes', 'tak')
            if kind == 'range':
                try:
                    return int(kept)
                except (TypeError, ValueError):
                    return int(default)
            return str(kept)
    if kind == 'scheme':
        try:
            from .portable import speechSchemes
            return speechSchemes.active()
        except Exception:                            # noqa: BLE001
            return ''
    if (section, key) == ('General', 'Enabled'):
        # What the switch SAYS is whether the reader is running, not what
        # the file remembers: the hotkey and the page both write the file,
        # and a file that says "off" about a reader that is talking is a
        # row that lies.
        try:
            from titan_access.engine import is_running
            return bool(is_running())
        except Exception:                            # noqa: BLE001
            return store.get_bool(section, key, bool(default))
    if kind == 'bool':
        return store.get_bool(section, key, bool(default))
    if kind == 'range':
        return store.get_int(section, key, int(default))
    return str(store.get(section, key, default) or '')


def value_word(entry, value, engine=None):
    """The value as words: on/off, the option's label, the number."""
    kind = entry[3]
    if kind == 'bool':
        return L('walk.on') if value else L('walk.off')
    if kind in ('choice', 'scheme', 'engines', 'voices', 'braille_table'):
        for known, label in _options(entry, engine):
            if str(known) == str(value):
                return label
        return str(value or '') or L('walk.notSet')
    if kind == 'range':
        # Zero is a value - the pitch at 0, the rate at 0 - not "not set".
        return str(int(value)) if value is not None else L('walk.notSet')
    return str(value or '') or L('walk.notSet')


def set_value(entry, value, engine=None):
    """Write one setting and apply it to the running reader.

    While a program's profile is being edited the value goes into THAT
    profile and the file is left alone; the running reader is told only
    when that program is the one in front.
    """
    store = _store()
    section, key, _label, kind, _extra, _default = entry
    program = _scope['program']
    if program and key and (section, key) not in _schema.NEVER_IN_A_PROFILE:
        from titan_access import profiles
        if kind == 'bool':
            kept = 'true' if value else 'false'
        else:
            kept = str(value)
        profiles.override(program, section, key, kept)
        with _LOCK:
            _counted['changed'] += 1
        if profiles.active() == program:
            profiles.activate(program, force=True)
            _apply(engine, section)
        return
    if kind == 'scheme':
        from .portable import speechSchemes
        speechSchemes.use(str(value))
    elif kind == 'bool':
        store.set_bool(section, key, bool(value))
    elif kind == 'range':
        store.set_int(section, key, int(value))
    else:
        store.set(section, key, str(value))
    if kind != 'scheme':
        store.save()
    with _LOCK:
        _counted['changed'] += 1
    if (section, key) == ('General', 'Enabled'):
        _switch_reader(bool(value))
        return
    _apply(engine, section)


def _switch_reader(on):
    """Start or stop the reader for the Enabled row.

    Stopping is done a moment later on a thread of its own: Enter on the
    row arrives on the keyboard hook's decider thread, and stopping the
    engine from there joins the thread that must first UNINSTALL the hook
    the decider belongs to - which is two threads waiting for each other.
    Starting is cheap and safe from anywhere.
    """
    try:
        from titan_access.engine import TitanAccessEngine, get_engine
    except Exception as error:                       # noqa: BLE001
        print('[TitanAccess] settings walk: engine: %s' % error)
        return
    if on:
        try:
            get_engine().start()
        except Exception as error:                   # noqa: BLE001
            print('[TitanAccess] settings walk: start: %s' % error)
        return

    def stop():
        try:
            running = TitanAccessEngine.instance
            if running is not None:
                running.stop()
        except Exception as error:                   # noqa: BLE001
            print('[TitanAccess] settings walk: stop: %s' % error)
    threading.Timer(0.6, stop).start()


def _apply(engine, section):
    """Tell the running reader - the WHOLE of it.

    This told the speech alone, so a setting whose subsystem has to be
    told - the mouse tracker, whose thread runs only while its switch is
    on - took effect from the settings panel (`settings_panel._apply_live`
    asks `engine.apply_settings`) and never from the walked list or the
    ring: Insert+Ctrl+G, "track the mouse: on", and nothing followed the
    pointer, on Windows and on Linux alike. Found by the Linux settings
    probe (`tests/check_titan_access_linux_settings.py`)."""
    if engine is None:
        return
    try:
        engine.settings = _store()
    except Exception:                                # noqa: BLE001
        pass
    apply_all = getattr(engine, 'apply_settings', None)
    if callable(apply_all):
        try:
            apply_all('walk:%s' % section)
            return
        except Exception as error:                   # noqa: BLE001
            print('[TitanAccess] settings walk: apply: %s' % error)
    speech = getattr(engine, 'speech', None)
    if speech is not None and hasattr(speech, 'apply_settings'):
        try:
            speech.apply_settings()
        except Exception as error:                   # noqa: BLE001
            print('[TitanAccess] settings walk: apply: %s' % error)


# --------------------------------------------------------------------------- #
# The walk
# --------------------------------------------------------------------------- #
def _kind_word(kind):
    return L({
        'bool': 'walk.kind.checkBox', 'choice': 'walk.kind.choice',
        'range': 'walk.kind.number', 'text': 'walk.kind.field',
    }.get(kind, 'walk.kind.choice'))


def _row_label(entry, engine=None):
    label = L(entry[2]).strip().rstrip(':').strip()
    said = '%s: %s' % (label, value_word(entry, value_of(entry), engine))
    program = _scope['program']
    if program and entry[1]:
        try:
            from titan_access import profiles
            if profiles.get(program, entry[0], entry[1]) is not None:
                # Translators: marks a setting a program's profile overrides.
                said = '%s (%s)' % (said, L('walk.inThisProgram'))
        except Exception:                            # noqa: BLE001
            pass
    return said


def _help_of(entry):
    """One sentence about a setting, or '' where none is written."""
    found = _schema.find(entry[0], entry[1]) if entry[1] else None
    if found is None and entry[0] == '__scheme__':
        found = _schema.find('__scheme__', '')
    if found is None:
        return ''
    text = L(found.help)
    return '' if text == found.help else text


def open_it(engine=None, program=None, at=0):
    """The sections, as a list. ``(ok, said)``.

    ``program`` names a profile to edit instead of the global settings:
    the same sections, every row then written into that program's
    profile. The program in front is offered as a row of the global
    list, so "make it so in THIS program" is one Enter away.
    """
    from .portable import palette
    with _LOCK:
        _scope['program'] = str(program or '')
    rows = []
    for sid, title, _entries in SCHEMA:
        rows.append({'label': L(title), 'role': L('walk.kind.category'),
                     'icon': 'open-object',
                     'run': (lambda which=sid: open_section(engine, which))})
    if program:
        rows.append({
            # Translators: a row that deletes a program's settings profile.
            'label': L('walk.removeProfile'), 'role': '',
            'run': (lambda: _remove_profile(engine, program))})
        title = L('walk.profileTitle', program)
        back = (lambda: open_it(engine))
    else:
        title = L('walk.title')
        back = None
        try:
            from titan_access import profiles
            here = profiles.program_in_front()
            if here:
                rows.append({
                    # Translators: a row that opens a program's own profile.
                    'label': L('walk.forThisProgram', here),
                    'role': '', 'icon': 'open-object',
                    'run': (lambda which=here: open_it(engine, which))})
            for known in profiles.programs():
                if known != here:
                    rows.append({'label': L('walk.profileOf', known),
                                 'role': '', 'icon': 'open-object',
                                 'run': (lambda which=known:
                                         open_it(engine, which))})
        except Exception as error:                   # noqa: BLE001
            print('[TitanAccess] settings walk: profiles: %s' % error)
    with _LOCK:
        _counted['opened'] += 1
    return palette.show(rows, title, back=back, at=at)


def _remove_profile(engine, program):
    from titan_access import profiles
    profiles.remove(program)
    if profiles.active() == program:
        profiles.activate('', force=True)
        _apply(engine, '')
    # Translators: said when a program's profile has been removed.
    return _reopen_top(engine, L('walk.profileRemoved', program))


def _reopen_top(engine, said):
    open_it(engine)
    return True, said


def open_section(engine, sid, at=0):
    """One section: its settings as rows. ``(ok, said)``."""
    from .portable import palette
    for known, title, entries in SCHEMA:
        if known != sid:
            continue
        rows = []
        for entry in entries:
            row = {'label': _row_label(entry, engine),
                   'role': _kind_word(entry[3]), 'icon': 'form-field',
                   'help': _help_of(entry)}
            row['run'] = (lambda one=entry, where=row:
                          _change(engine, sid, one, where))
            rows.append(row)
        with _LOCK:
            _counted['sections'] += 1
            _open.update({'section': sid, 'rows': rows, 'at': at})
        program = _scope['program']
        return palette.show(rows, L(title),
                            back=lambda: open_it(engine, program or None),
                            at=at)
    return False, ''


def _index_of(sid, row):
    with _LOCK:
        rows = _open.get('rows') or []
    for index, one in enumerate(rows):
        if one is row:
            return index
    return 0


def _change(engine, sid, entry, row):
    """Enter on a setting: the one obvious thing for its kind."""
    from .portable import palette
    kind = entry[3]
    if kind == 'bool':
        wanted = not value_of(entry)
        set_value(entry, wanted, engine)
        row['label'] = _row_label(entry, engine)
        # Said in place: the level is not put up again, because that
        # would read the title on top of the answer.
        return True, row['label']
    if kind in ('choice', 'range', 'scheme', 'engines', 'voices',
                'braille_table'):
        options = _options(entry, engine)
        if not options:
            return False, L('walk.nothingToChoose')
        now = str(value_of(entry))
        at = 0
        made = []
        for index, (value, label) in enumerate(options):
            current = str(value) == now
            if current:
                at = index
            made.append({
                'label': ('%s, %s' % (label, L('walk.now'))) if current
                else label,
                'role': L('walk.kind.option'), 'icon': 'form-field',
                'run': (lambda picked=value: _picked(engine, sid, entry,
                                                     row, picked))})
        where = _index_of(sid, row)
        return palette.show(made, L(entry[2]),
                            back=lambda: open_section(engine, sid, at=where),
                            at=at)
    if kind == 'text':
        return _ask(engine, sid, entry, row)
    return False, L('walk.setInWindow').format(what=L(entry[2]))


def _picked(engine, sid, entry, row, value):
    set_value(entry, value, engine)
    row['label'] = _row_label(entry, engine)
    # Back to the section, on the setting that was just answered: the row
    # is re-read holding the new value, so it IS the confirmation.
    return open_section(engine, sid, at=_index_of(sid, row))


def _ask(engine, sid, entry, row):
    from .portable import dialogs, palette
    where = _index_of(sid, row)

    def answered(text):
        set_value(entry, str(text), engine)
        row['label'] = _row_label(entry, engine)
        open_section(engine, sid, at=where)

    if dialogs._gui() is None or dialogs._wx() is None:
        return False, L('walk.setInWindow').format(what=L(entry[2]))
    # The palette borrows the arrow keys; a text box opened over it
    # would have its own taken away.
    palette.stop()
    dialogs.ask_text(L(entry[2]), L('walk.title'), on_answer=answered,
                     default=str(value_of(entry) or ''),
                     on_cancel=lambda: open_section(engine, sid, at=where))
    return True, ''
