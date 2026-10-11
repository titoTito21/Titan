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
#: (minimum, maximum, step)), text, speech_system, synthesizer, voices,
#: scheme, braille_table.
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
    if kind == 'variants':
        from . import speech_systems
        _system, synth, voice = speech_systems.current(_speech_view())
        try:
            return speech_systems.variants(synth, voice) if synth else []
        except Exception:                            # noqa: BLE001
            return []
    if kind in _schema.SPEECH_LEVELS:
        # **The same three levels as the speech system dialog**: the
        # systems this machine has, the synthesizers of the CHOSEN system,
        # the voices of the CHOSEN synthesizer - external (NVDA add-on)
        # synthesizers among them. The walk used to offer Titan's flat
        # engine list and the voices of whatever engine was speaking.
        from . import speech_systems
        system, synth, _voice = speech_systems.current(_speech_view())
        try:
            if kind == 'speech_system':
                return speech_systems.systems()
            if kind == 'synthesizer':
                return speech_systems.synthesizers(system)
            return speech_systems.voices(synth) if synth else []
        except Exception:                            # noqa: BLE001
            return []
    if kind == 'braille_table':
        rows = [('', L('settings.braille.autoTable'))]
        try:
            from . import braille
            rows.extend((name, label) for name, label in braille.tables_available())
        except Exception:                            # noqa: BLE001
            pass
        return rows
    return []


class _SpeechView(object):
    """The Speech settings as they are in force while walking: a program's
    profile over the store when a profile is being edited."""

    def __init__(self, store, program):
        self.store = store
        self.program = program

    def _kept(self, section, key):
        if not self.program:
            return None
        try:
            from titan_access import profiles
            return profiles.get(self.program, section, key)
        except Exception:                            # noqa: BLE001
            return None

    def get(self, section, key, default=None):
        kept = self._kept(section, key)
        return kept if kept is not None else self.store.get(section, key,
                                                            default)

    def get_bool(self, section, key, default=False):
        kept = self._kept(section, key)
        if kept is not None:
            return str(kept).strip().lower() in ('true', '1', 'yes', 'tak')
        return self.store.get_bool(section, key, default)


def _speech_view(store=None):
    return _SpeechView(store or _store(), _scope['program'])


def _set_speech(entry, value, engine):
    """One of the three speech levels chosen: the other two follow (a new
    system takes its first synthesizer, a new synthesizer its first
    voice), written as `speech_systems.settings_for` says - into the
    program's profile while one is being edited."""
    from . import speech_systems
    kind = entry[3]
    system, synth, voice = speech_systems.current(_speech_view())
    variant = speech_systems.current_variant(_speech_view())
    value = str(value or '')
    if kind == 'variants':
        variant = value
    elif kind == 'speech_system':
        system, synth, voice = value, speech_systems.first_synth(value), ''
    elif kind == 'synthesizer':
        synth, voice = value, ''
    else:
        voice = value
    if kind != 'variants':
        variant = ''
    wanted = speech_systems.settings_for(system, synth, voice, variant)
    program = _scope['program']
    store = _store()
    if program:
        from titan_access import profiles
        for (section, key), kept in wanted.items():
            if isinstance(kept, bool):
                kept = 'true' if kept else 'false'
            profiles.override(program, section, key, str(kept))
        with _LOCK:
            _counted['changed'] += 1
        if profiles.active() == program:
            profiles.activate(program, force=True)
            _apply(engine, 'speech')
        return
    for (section, key), kept in wanted.items():
        if isinstance(kept, bool):
            store.set_bool(section, key, kept)
        else:
            store.set(section, key, str(kept))
    store.save()
    with _LOCK:
        _counted['changed'] += 1
    _apply(engine, 'speech')


def value_of(entry, store=None):
    """What the setting holds now, as the store keeps it - or, while a
    program's profile is being edited, what THAT profile says (the global
    value where the profile says nothing)."""
    store = store or _store()
    section, key, _label, kind, _extra, default = entry
    if kind == 'variants':
        from . import speech_systems
        return speech_systems.current_variant(_speech_view(store))
    if kind in _schema.SPEECH_LEVELS:
        from . import speech_systems
        now = speech_systems.current(_speech_view(store))
        return now[_schema.SPEECH_LEVELS.index(kind)]
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
        # The words the reader says for a REAL check box - the walked list
        # and the settings page must name one control the same way.
        from titan_access import localization
        return localization.state_label('checked' if value else 'unchecked')
    if kind == 'voices':
        # Naming the voice must not wait for the synthesizer to list its
        # voices (a Wine bridge is seconds): the list already known, else
        # the voice's own id, and the list is read for next time.
        from . import speech_systems
        _system, synth, _voice = speech_systems.current(_speech_view())
        rows = speech_systems.cached_voices(synth)
        if rows is None:
            speech_systems.prefetch_voices(synth)
            rows = []
        for known, label in rows:
            if str(known) == str(value):
                return label
        return str(value or '') or L('walk.notSet')
    if kind == 'variants':
        # Like the voice: named from what is already known, never by
        # waiting for the synthesizer.
        from . import speech_systems
        _system, synth, voice = speech_systems.current(_speech_view())
        for known, label in speech_systems.cached_variants(synth, voice) or []:
            if str(known) == str(value):
                return label
        return str(value or '') or L('settings.speech.variantDefault')
    if kind in ('choice', 'scheme', 'braille_table') + _schema.SPEECH_LEVELS:
        for known, label in _options(entry, engine):
            if str(known) == str(value):
                return label
        return str(value or '') or L('walk.notSet')
    if kind == 'hotkey':
        from . import hotkeys
        return hotkeys.spoken(value) or L('walk.notSet')
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
    if kind in _schema.SPEECH_LEVELS + ('variants',):
        _set_speech(entry, value, engine)
        return
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
    if kind == 'hotkey':
        from . import hotkeys
        hotkeys.changed()
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
    """What a setting IS, in the word the reader says for the real control
    the settings page builds for it: a `wx.CheckBox`, a `wx.Choice` (a
    combo box), a `wx.SpinCtrl`, a `wx.TextCtrl` (an edit field). Its own
    words ("field", "number") made the walked list name one control two
    ways."""
    from titan_access import localization
    return localization.role_label({
        'bool': 'checkbox', 'choice': 'combobox', 'braille_table': 'combobox',
        'scheme': 'combobox', 'speech_system': 'combobox',
        'synthesizer': 'combobox', 'voices': 'combobox',
        'variants': 'combobox',
        'range': 'spinner', 'text': 'edit',
    }.get(kind, 'combobox')) if kind != 'hotkey' else L('walk.kind.hotkey')


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
    if kind in ('choice', 'range', 'scheme', 'speech_system', 'synthesizer',
                'voices', 'variants',
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
    if kind == 'hotkey':
        return _press_shortcut(engine, sid, entry, row)
    return False, L('walk.setInWindow').format(what=L(entry[2]))


def _picked(engine, sid, entry, row, value):
    set_value(entry, value, engine)
    row['label'] = _row_label(entry, engine)
    # Back to the section, on the setting that was just answered: the row
    # is re-read holding the new value, so it IS the confirmation.
    return open_section(engine, sid, at=_index_of(sid, row))


def _press_shortcut(engine, sid, entry, row):
    """Enter on a hotkey field: the next combination pressed IS the
    answer, as in a hotkey field of Windows - taken by the reader's own
    keyboard hook, so it reaches no program and fires no shortcut. Escape
    leaves it as it was; a key with no Control, Alt or Windows is refused
    and the field goes on listening."""
    from . import hotkeys

    def say(text):
        try:
            if engine is not None:
                engine.speak(text, interrupt=True)
        except Exception:                            # noqa: BLE001
            pass

    def done(text):
        if text is None:
            say(L('walk.hotkey.unchanged'))
            return
        if not text:
            say(L('walk.hotkey.needsModifier'))
            return
        set_value(entry, text, engine)
        row['label'] = _row_label(entry, engine)
        say(row['label'])

    hotkeys.begin_capture(done)
    return True, L('walk.hotkey.press')


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
