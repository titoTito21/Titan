# -*- coding: utf-8 -*-
"""Every reader setting, under the REAL engine on Linux (WSLg or a desktop).

    python3 tests/check_titan_access_linux_settings.py

The suites prove that a setting is read and that the panel builds; what
"all the settings work on Linux too" needs is the engine really running
under GTK and AT-SPI while every entry of the schema is written through
the walked list's own path (`settings_walk.set_value`), read back, applied
(`engine.apply_settings`), and a handful of behaviours asked afterwards -
the type word gone when ElementType is off, punctuation spoken or not,
the mouse tracker started and stopped, a walked row without its kind -
and then every section's GTK panel filled with a changed value, saved and
read back out of the store. Runs on a FRESH home, never the user's own.
Prints every problem; exits 1 when there is one.
"""
import os
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')

# A home of its own: the store lives under ~/.config/titosoft/Titan here.
HOME = tempfile.mkdtemp(prefix='titan_access_linux_')
os.environ['HOME'] = HOME
os.environ['APPDATA'] = HOME
os.environ['XDG_CONFIG_HOME'] = os.path.join(HOME, '.config')
os.environ.setdefault('GDK_BACKEND', 'x11')
os.environ.setdefault('GTK_MODULES', 'gail:atk-bridge')
os.environ['NO_AT_BRIDGE'] = '0'
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
for path in (COMPONENT, TITAN):
    if path not in sys.path:
        sys.path.insert(0, path)

problems = []
said = []


def problem(text):
    problems.append(text)
    print('PROBLEM:', text, flush=True)


class RecordingSpeech:
    supports_pitch = True

    def __init__(self, settings=None):
        pass

    def speak(self, text, position=0.0, interrupt=True, pitch_offset=0, voice=None):
        said.append(str(text))

    speak_async = speak

    def speak_segments(self, segments, gap_ms=0):
        said.append(' | '.join(str(s[0]) for s in segments))

    def stop(self):
        pass

    is_speaking = False

    def apply_settings(self):
        said.append('<apply>')

    def set_rate(self, *a): pass
    def set_volume(self, *a): pass
    def set_pitch(self, *a): pass
    def set_engine(self, *a): pass
    def set_voice(self, *a): pass
    def current_rate(self): return 0
    def get_voices(self): return []
    def get_engines(self): return []
    def wait_until_done(self, *a, **k): return True
    def wait_for_queue(self, *a, **k): return True
    def pending_count(self): return 0


def _rows():
    """The walk's own entries: 6-tuples (section, key, label, kind, extra, default)."""
    from titan_access import settings_schema as schema
    for sid, _title, rows in schema.as_walk_schema():
        for row in rows:
            yield sid, row


def _values_for(entry, engine):
    from titan_access import settings_walk as walk
    section, key, _label, kind, extra, default = entry
    if (section, key) == ('General', 'Enabled'):
        return []                                  # the switch stops the engine
    if kind == 'bool':
        return [not bool(default), bool(default)]
    if kind == 'range':
        options = [v for v, _l in walk._options(entry, engine)]
        return [options[0], options[-1], int(default)] if options else []
    if kind in ('choice', 'scheme', 'braille_table'):
        return [v for v, _l in walk._options(entry, engine)]
    if kind in ('engines', 'voices'):
        now = walk.value_of(entry)
        return [now] if now else []
    if kind == 'text':
        return ['probe', str(default)]
    return []


def check_every_entry(engine):
    from titan_access import settings_walk as walk
    count = 0
    for sid, entry in _rows():
        section, key, _label, kind, _extra, _default = entry
        for value in _values_for(entry, engine):
            try:
                walk.set_value(entry, value, engine)
                back = walk.value_of(entry)
                if kind == 'bool' and bool(back) != bool(value):
                    problem('%s/%s: set %r, read back %r' % (section, key, value, back))
                elif kind == 'range' and int(back) != int(value):
                    problem('%s/%s: set %r, read back %r' % (section, key, value, back))
                elif kind not in ('bool', 'range') and str(back) != str(value):
                    problem('%s/%s: set %r, read back %r' % (section, key, value, back))
                engine.apply_settings('probe')
                count += 1
            except Exception as error:               # noqa: BLE001
                problem('%s/%s <- %r raised: %s' % (section, key, value, error))
    print('entries written and read back:', count, flush=True)


def check_behaviours(engine):
    from titan_access import settings_walk as walk, settings_schema as schema
    from titan_access import accessible
    from titan_access.contracts import AccessibleObject
    from titan_access import symbols

    def entry(section, key):
        for _sid, row in _rows():
            if row[0] == section and row[1] == key:
                return row
        raise KeyError((section, key))

    def words(obj, **kw):
        return [seg[0] for seg in accessible.describe(obj, engine.settings, **kw)]

    button = AccessibleObject(name='Zapisz', role='button', states={'focusable'})
    walk.set_value(entry('Verbosity', 'ElementType'), True, engine)
    with_type = words(button)
    walk.set_value(entry('Verbosity', 'ElementType'), False, engine)
    without = words(button)
    if not (len(with_type) > len(without) and 'Zapisz' in without):
        problem('ElementType: on=%r off=%r' % (with_type, without))
    walk.set_value(entry('Navigation', 'AnnounceControlTypesNavigation'), True, engine)
    nav = words(button, for_navigation=True)
    if len(nav) <= len(without):
        problem('AnnounceControlTypesNavigation did not force the type: %r' % nav)
    walk.set_value(entry('Verbosity', 'ElementType'), True, engine)

    walk.set_value(entry('Verbosity', 'ElementName'), False, engine)
    if 'Zapisz' in words(button):
        problem('ElementName off still says the name')
    walk.set_value(entry('Verbosity', 'ElementName'), True, engine)

    walk.set_value(entry('Symbols', 'PunctuationLevel'), 'none', engine)
    none = symbols.text_for_speech('kot, pies!', engine.settings)
    walk.set_value(entry('Symbols', 'PunctuationLevel'), 'all', engine)
    every = symbols.text_for_speech('kot, pies!', engine.settings)
    if none == every:
        problem('PunctuationLevel none and all read alike: %r' % none)
    walk.set_value(entry('Symbols', 'PunctuationLevel'), 'some', engine)

    walk.set_value(entry('Symbols', 'NumbersAs'), 'digits', engine)
    digits = symbols.text_for_speech('1234', engine.settings)
    walk.set_value(entry('Symbols', 'NumbersAs'), 'whole', engine)
    whole = symbols.text_for_speech('1234', engine.settings)
    if digits == whole:
        problem('NumbersAs digits and whole read alike: %r' % digits)

    mouse = getattr(engine, 'mouse', None)
    if mouse is None:
        problem('the engine has no mouse tracker')
    else:
        walk.set_value(entry('Mouse', 'TrackMouse'), True, engine)
        on = bool(mouse.running)
        walk.set_value(entry('Mouse', 'TrackMouse'), False, engine)
        off = bool(mouse.running)
        if not (on and not off):
            problem('TrackMouse: running after on=%r, after off=%r' % (on, off))

    from titan_access.portable import palette
    row = {'label': 'Strona', 'role': 'page'}
    walk.set_value(entry('Reader', 'walkSayKind'), True, engine)
    with_kind = [p[0] for p in palette.parts_of(row, 0, 3)]
    walk.set_value(entry('Reader', 'walkSayKind'), False, engine)
    without_kind = [p[0] for p in palette.parts_of(row, 0, 3)]
    if not ('page' in with_kind and 'page' not in without_kind):
        problem('walkSayKind: on=%r off=%r' % (with_kind, without_kind))
    walk.set_value(entry('Reader', 'walkSayKind'), True, engine)
    walk.set_value(entry('Reader', 'walkSayPosition'), False, engine)
    no_place = [p[0] for p in palette.parts_of(row, 0, 3)]
    if any('3' in p for p in no_place):
        problem('walkSayPosition off still says the place: %r' % no_place)
    walk.set_value(entry('Reader', 'walkSayPosition'), True, engine)

    hints = entry('General', 'SpeakHints')
    walk.set_value(hints, False, engine)
    if walk.value_of(hints):
        problem('SpeakHints did not turn off')
    walk.set_value(hints, True, engine)
    print('behaviours checked', flush=True)


def check_panels(frame, engine):
    import wx
    from titan_access import settings_panel, settings_schema as schema
    from titan_access.settings_store import get_settings
    store = get_settings()
    changed = 0
    for sid, _title, rows in schema.SECTIONS:
        if sid == 'speech':
            continue
        try:
            panel = settings_panel.build_panel(frame, sid)
        except Exception as error:                   # noqa: BLE001
            problem('panel %s would not build: %s' % (sid, error))
            continue
        expected = {}
        for entry in rows:
            at = (entry.section, entry.key)
            if at == ('General', 'Enabled') or at not in panel.controls:
                continue
            _e, ctrl = panel.controls[at]
            try:
                if entry.kind == 'bool':
                    ctrl.SetValue(not ctrl.GetValue())
                    expected[at] = ('bool', ctrl.GetValue())
                elif entry.kind == 'range':
                    ctrl.SetValue(ctrl.GetMin())
                    expected[at] = ('int', ctrl.GetMin())
                elif entry.kind == 'choice':
                    values = [str(v) for v, _k in schema.options(entry)]
                    if len(values) > 1:
                        pick = (ctrl.GetSelection() + 1) % len(values)
                        ctrl.SetSelection(pick)
                        expected[at] = ('str', values[pick])
                elif entry.kind == 'text':
                    ctrl.SetValue('panel probe')
                    expected[at] = ('str', 'panel probe')
            except Exception as error:               # noqa: BLE001
                problem('panel %s/%s control: %s' % (sid, entry.key, error))
        try:
            settings_panel.save_panel(panel)
        except Exception as error:                   # noqa: BLE001
            problem('panel %s would not save: %s' % (sid, error))
        store = get_settings()
        for (section, key), (kind, value) in expected.items():
            if kind == 'bool':
                back = store.get_bool(section, key, None)
            elif kind == 'int':
                back = store.get_int(section, key, None)
            else:
                back = store.get(section, key, None)
            if kind == 'bool' and bool(back) != bool(value) or kind != 'bool' and str(back) != str(value):
                problem('panel %s: %s/%s saved %r, store has %r' % (sid, section, key, value, back))
            changed += 1
        panel.Destroy()
    print('panel controls changed, saved and read back:', changed, flush=True)


def main():
    import wx
    import titan_access.speech_adapter as speech
    import titan_access.keyboard_hook as hook
    speech.SpeechAdapter = RecordingSpeech
    hook.KeyboardHook.start = lambda self: self
    app = wx.App(False)
    frame = wx.Frame(None, title='Titan Access settings probe')
    panel = wx.Panel(frame)
    wx.Button(panel, label='Zapisz')
    frame.Show()
    from titan_access.engine import TitanAccessEngine
    engine = TitanAccessEngine()
    print('engine started:', engine.start(), 'platform:', sys.platform, flush=True)

    def run():
        try:
            check_every_entry(engine)
            check_behaviours(engine)
            check_panels(frame, engine)
            info = engine.diagnostics()
            print('diagnostics: running=%s provider=%s speech=%s' % (
                info.get('running'), info.get('has_provider'), info.get('has_speech')), flush=True)
            if not info.get('running'):
                problem('the engine stopped during the checks')
        except Exception:                            # noqa: BLE001
            problem('probe raised:\n' + traceback.format_exc())
        finally:
            try:
                engine.stop()
            except Exception as error:               # noqa: BLE001
                problem('engine.stop raised: %s' % error)
            wx.CallLater(200, app.ExitMainLoop)
    wx.CallLater(1500, run)
    app.MainLoop()
    print('said %d things; first: %r' % (len(said), said[:3]), flush=True)
    print('==== %s' % ('OK' if not problems else '%d PROBLEM(S)' % len(problems)), flush=True)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
