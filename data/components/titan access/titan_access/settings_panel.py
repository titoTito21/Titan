# -*- coding: utf-8 -*-
"""TCE settings category for Titan Access.

A 1:1 wxPython port of the C# ``ScreenReader.SettingsDialog`` rendered as a TCE
settings category (a scrollable ``wx.Panel``). Every option of the original
dialog is reproduced, grouped exactly the same way (Speech, General, Verbosity,
Navigation, Dial, Text editing). The panel is backed by the shared INI store
(:func:`titan_access.settings_store.get_settings`) so it reads and writes the
very same file the standalone C# reader uses.

Speech specifics
----------------
* **Speech system / Synthesizer / Voice** - the three levels of
  :mod:`titan_access.speech_systems`, the same ones the speech system dialog
  (Insert+Ctrl+S), the walked settings, the settings ring and the TPad offer
  (external NVDA add-on synthesizers included). Written through
  ``speech_systems.settings_for`` into ``Speech/OwnVoice``,
  ``Speech/Synthesizer``, ``Speech/Voice`` and
  ``Speech/SpeechDispatcherModule``.
* **Rate / Volume / Pitch** - numeric spinners passed straight through to the
  Titan engine.

The module imports cleanly with no GUI present (``import wx`` is guarded) and
all ``src.*`` imports are best-effort, keeping the screen reader independent of
Titan internals. :func:`register` no-ops when wxPython is unavailable.
"""

# --------------------------------------------------------------------------- #
# Optional GUI / engine imports (keep this module importable headless)
# --------------------------------------------------------------------------- #
import threading

try:
    import wx
    WX_AVAILABLE = True
except Exception:  # pragma: no cover - headless / no display
    wx = None
    WX_AVAILABLE = False

# Localization (falls back to returning the raw key).
try:
    from titan_access.localization import L
except Exception:  # pragma: no cover
    def L(key, *args):
        return key

# Settings store + enums.
try:
    from titan_access.settings_store import (
        get_settings,
        AnnouncementMode,
        ScreenReaderModifier,
        KeyboardEchoSetting,
        SEC_SPEECH,
        SEC_GENERAL,
        SEC_VERBOSITY,
        SEC_NAVIGATION,
        SEC_DIAL,
        SEC_TEXT_EDITING,
    )
    STORE_AVAILABLE = True
except Exception as _e:  # pragma: no cover
    STORE_AVAILABLE = False
    print(f"[TitanAccess] settings_panel: store unavailable: {_e}")


# Legacy synthesizer names (from the C# dialog) -> a Titan engine id, so an INI
# written by the original reader still selects a sensible engine here.
_SYNTH_ALIAS = {
    "onecore": "sapi5",
    "sapi5": "sapi5",
    "bestspeech": "espeak",
}


# --------------------------------------------------------------------------- #
# Titan TTS helpers (all best-effort; empty / no-op when Titan is absent)
# --------------------------------------------------------------------------- #
def _tce_speech():
    """Return the ``src.titan_core.tce_speech`` module, or ``None``."""
    try:
        from src.titan_core import tce_speech
        return tce_speech
    except Exception:
        return None


def _apply_live(store):
    """Notify the running reader that (non-speech) settings changed.

    Speech parameters are owned by Titan TTS, not the screen reader, so we do
    NOT push engine / voice / rate / pitch / volume here -- doing so would
    override the user's Titan TTS configuration. We only nudge the running
    reader to re-read its own (verbosity / navigation / ...) settings.
    """
    try:
        from titan_access.engine import TitanAccessEngine
        inst = TitanAccessEngine.instance
        if inst is None:
            return
        if hasattr(inst, 'apply_settings'):
            inst.apply_settings()
        elif getattr(inst, "speech", None) is not None:
            inst.speech.apply_settings()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Small UI builders (only used when wx is available)
# --------------------------------------------------------------------------- #
def _section(parent, sizer, title):
    """Create a labelled :class:`wx.StaticBoxSizer` and add it to ``sizer``."""
    box = wx.StaticBox(parent, label=title)
    box_sizer = wx.StaticBoxSizer(box, wx.VERTICAL)
    sizer.Add(box_sizer, 0, wx.EXPAND | wx.ALL, 6)
    return box_sizer


def _checkbox(parent, box_sizer, label):
    cb = wx.CheckBox(parent, label=label)
    box_sizer.Add(cb, 0, wx.ALL, 4)
    return cb


def _choice_row(parent, box_sizer, label, choices):
    """A labelled :class:`wx.Choice`. The StaticText keeps it screen-readable."""
    row = wx.BoxSizer(wx.HORIZONTAL)
    row.Add(wx.StaticText(parent, label=label), 0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    choice = wx.Choice(parent, choices=choices)
    row.Add(choice, 1, wx.ALIGN_CENTER_VERTICAL)
    box_sizer.Add(row, 0, wx.EXPAND | wx.ALL, 4)
    return choice


def _spin_row(parent, box_sizer, label, minimum, maximum):
    row = wx.BoxSizer(wx.HORIZONTAL)
    row.Add(wx.StaticText(parent, label=label), 0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    spin = wx.SpinCtrl(parent, min=minimum, max=maximum, initial=minimum)
    row.Add(spin, 0, wx.ALIGN_CENTER_VERTICAL)
    box_sizer.Add(row, 0, wx.EXPAND | wx.ALL, 4)
    return spin


def _text_row(parent, box_sizer, label):
    box_sizer.Add(wx.StaticText(parent, label=label), 0, wx.LEFT | wx.TOP, 4)
    txt = wx.TextCtrl(parent)
    box_sizer.Add(txt, 0, wx.EXPAND | wx.ALL, 4)
    return txt


def _hotkey_row(parent, box_sizer, label):
    """A hotkey field: the combination pressed in it is what it holds,
    as in Windows' own hotkey control - Tab and Shift+Tab still leave it,
    Backspace alone puts the default back."""
    box_sizer.Add(wx.StaticText(parent, label=label), 0, wx.LEFT | wx.TOP, 4)
    txt = wx.TextCtrl(parent, style=wx.TE_PROCESS_ENTER)
    txt._hotkey = ''

    def show(written):
        from titan_access import hotkeys
        txt._hotkey = hotkeys.normalize(written) or hotkeys.DEFAULT
        txt.ChangeValue(hotkeys.spoken(txt._hotkey))
        txt.SetInsertionPointEnd()

    def on_key(event):
        from titan_access import hotkeys
        code = event.GetKeyCode()
        mods = (event.ControlDown(), event.AltDown(), event.ShiftDown())
        if code in (wx.WXK_SHIFT, wx.WXK_CONTROL, wx.WXK_ALT,
                    wx.WXK_WINDOWS_LEFT, wx.WXK_WINDOWS_RIGHT,
                    wx.WXK_WINDOWS_MENU):
            return
        if code == wx.WXK_TAB and not mods[0] and not mods[1]:
            event.Skip()
            return
        if code == wx.WXK_BACK and not any(mods):
            show(hotkeys.DEFAULT)
            return
        written = hotkeys.from_event(code, *mods)
        if written:
            show(written)
        else:
            wx.Bell()

    def focus(on):
        def handler(event):
            from titan_access import hotkeys
            hotkeys.field_focused = on
            event.Skip()
        return handler

    txt.Bind(wx.EVT_KEY_DOWN, on_key)
    txt.Bind(wx.EVT_CHAR, lambda _evt: None)
    # The shortcut in force must not fire while it is being typed here.
    txt.Bind(wx.EVT_SET_FOCUS, focus(True))
    txt.Bind(wx.EVT_KILL_FOCUS, focus(False))
    txt.show_hotkey = show
    box_sizer.Add(txt, 0, wx.EXPAND | wx.ALL, 4)
    return txt


def _announce_labels():
    return [
        L("settings.announce.none"),
        L("settings.announce.sound"),
        L("settings.announce.speech"),
        L("settings.announce.speechAndSound"),
    ]


# --------------------------------------------------------------------------- #
# Panel construction
# --------------------------------------------------------------------------- #
#: The sections, each a category of its own inside "Titan Access", read
#: out of `settings_schema` - the one description of every setting. The
#: main category holds the note; every section is a child category
#: (`register_settings_category(..., parent=...)`).
try:
    from titan_access import settings_schema as _schema
    SECTIONS = tuple(sid for sid, _title, _rows in _schema.SECTIONS)
    _TITLES = {sid: title for sid, title, _rows in _schema.SECTIONS}
except Exception as _schema_error:  # pragma: no cover
    _schema = None
    SECTIONS = ('speech', 'general')
    _TITLES = {'speech': 'settings.section.speech',
               'general': 'settings.section.general'}
    print(f"[TitanAccess] settings_panel: schema unavailable: {_schema_error}")


def _section_title(which):
    return L(_TITLES.get(which, 'settings.section.' + which))


def build_panel(parent, section=None):
    """Build and return a Titan Access settings panel (a ``wx.Panel``).

    ``section`` is one of :data:`SECTIONS` for a child category, ``'main'``
    for the category that holds the switch, and None for everything on
    one page - which is what the panel was, and what a caller from before
    the categories still gets.
    """
    panel = wx.Panel(parent)
    panel.section = section
    outer = wx.BoxSizer(wx.VERTICAL)

    scroller = wx.ScrolledWindow(panel, style=wx.VSCROLL)
    scroller.SetScrollRate(0, 12)
    s = wx.BoxSizer(wx.VERTICAL)
    wanted = SECTIONS if section is None else (
        () if section == 'main' else (section,))
    show_main = section in (None, 'main')

    if show_main:
        _build_main(panel, scroller, s)
    for which in wanted:
        _BUILDERS[which](panel, scroller, s)

    scroller.SetSizer(s)
    outer.Add(scroller, 1, wx.EXPAND | wx.ALL, 4)
    panel.SetSizer(outer)
    return panel


def _build_main(panel, scroller, s):
    # The category that holds the sections says where they are. The
    # switch itself is the first control of General (`_build_enable`),
    # which is where a user looks for "turn the reader on".
    s.Add(wx.StaticText(scroller, label=L("settings.main.note")), 0, wx.ALL, 6)
    _build_profiles(panel, scroller, s)


def _build_enable(panel, scroller, box):
    # ------------------- Enable screen reader (live) ------------------- #
    # Checking this turns the reader ON immediately; unchecking turns it OFF
    # immediately. The state is also persisted (General/Enabled) so the reader
    # auto-starts with the component next time.
    panel.chk_enabled = _checkbox(scroller, box, L("settings.general.enable"))

    def _on_enable(_evt):
        want_on = panel.chk_enabled.GetValue()
        try:
            if want_on:
                from titan_access.engine import get_engine
                get_engine().start()
            else:
                from titan_access.engine import TitanAccessEngine
                if TitanAccessEngine.instance is not None:
                    TitanAccessEngine.instance.stop()
        except Exception as e:
            print(f"[TitanAccess] enable toggle error: {e}")
        # Persist immediately so the choice survives a restart.
        try:
            if STORE_AVAILABLE:
                st = get_settings()
                st.enabled = want_on
                st.save()
        except Exception:
            pass
    panel.chk_enabled.Bind(wx.EVT_CHECKBOX, _on_enable)


def _build_speech(panel, scroller, s):
    # ----------------------------- Speech ------------------------------ #
    # **The reader may have a voice of its own.** It speaks through Titan's
    # engine and voice unless this says otherwise; with its own voice on it
    # gets a private engine, and the engine, voice, rate, pitch and volume
    # below are the reader's and nobody else's.
    sp = _section(scroller, s, L("settings.section.speech"))
    # **The speech scheme** - how each kind of control is announced (which
    # parts, in what order, in which voice, with what sound and pause) -
    # chosen here so it is visible in the voice settings, not only in the
    # manager. The list and the active one come from the shared
    # `speechSchemes` both readers use.
    try:
        from titan_access.portable import speechSchemes as _ss
        panel._scheme_keys = [k for k, _l in _ss.names()]
        panel.cmb_scheme = _choice_row(
            scroller, sp, L("settings.speech.scheme"),
            [label for _k, label in _ss.names()])
    except Exception:
        panel._scheme_keys = []
        panel.cmb_scheme = None
    sp.Add(wx.StaticText(scroller, label=L("settings.speech.schemeInfo")),
           0, wx.LEFT | wx.BOTTOM, 6)
    sp.Add(wx.StaticText(scroller, label=L("settings.speech.inheritNote")),
           0, wx.ALL, 6)
    # **Speech system, synthesizer, voice** - the three levels of
    # `speech_systems`, exactly as the speech system dialog
    # (Insert+Ctrl+S), the walked settings and the TPad offer them. This
    # page used to show Titan's flat engine list and fill the voices by
    # SWITCHING the reader's own engine to the one being looked at, and
    # had no NVDA add-on synthesizers at all.
    from titan_access import speech_systems as _sys
    panel._systems = list(_sys.systems())
    panel.cmb_system = _choice_row(scroller, sp, L("settings.speech.system"),
                                   [label for _k, label in panel._systems])
    panel.cmb_synth = _choice_row(scroller, sp, L("settings.speech.engine"),
                                  [])
    panel._synth_ids = []
    panel.cmb_voice = _choice_row(scroller, sp, L("settings.speech.voice"), [])
    panel.voice_choice = panel.cmb_voice
    panel._voice_ids = []
    panel._voice_ticket = [0]
    # The fourth level, offered only where the synthesizer has variants
    # (Cerence: compact, embedded-pro, embedded-high).
    panel.cmb_variant = _choice_row(scroller, sp,
                                    L("settings.speech.variant"), [])
    panel._variant_ids = []
    panel._variant_ticket = [0]
    panel._keep_variant = ''
    panel.cmb_variant.Enable(False)
    panel.spn_rate = _spin_row(scroller, sp, L("settings.speech.rate"), -10, 10)
    panel.spn_pitch = _spin_row(scroller, sp, L("settings.speech.pitch"), -10, 10)
    panel.spn_volume = _spin_row(scroller, sp, L("settings.speech.volume"), 0, 100)

    def _system_chosen(_evt):
        _fill_synths(panel, keep='')

    def _synth_chosen(_evt):
        _fill_voices(panel, keep='')

    def _voice_chosen(_evt):
        _fill_variants(panel, keep='')
    for ctrl, key in ((panel.cmb_system, 'OwnVoice'),
                      (panel.cmb_synth, 'Synthesizer'),
                      (panel.cmb_voice, 'Voice'),
                      (panel.cmb_variant, 'Variant')):
        try:
            ctrl.SetToolTip(L('settings.help.Speech.%s' % key))
        except Exception:
            pass
    panel.cmb_system.Bind(wx.EVT_CHOICE, _system_chosen)
    panel.cmb_synth.Bind(wx.EVT_CHOICE, _synth_chosen)
    panel.cmb_voice.Bind(wx.EVT_CHOICE, _voice_chosen)


def _picked(choice, ids):
    at = choice.GetSelection()
    return ids[at] if 0 <= at < len(ids) else ''


def _chosen_system(panel):
    return _picked(panel.cmb_system, [k for k, _l in panel._systems])


def _chosen_synth(panel):
    return _picked(panel.cmb_synth, panel._synth_ids)


def _fill_synths(panel, keep=''):
    from titan_access import speech_systems as _sys
    rows = _sys.synthesizers(_chosen_system(panel))
    panel.cmb_synth.Clear()
    panel._synth_ids = [key for key, _label in rows]
    for _key, label in rows:
        panel.cmb_synth.Append(label)
    if keep in panel._synth_ids:
        panel.cmb_synth.SetSelection(panel._synth_ids.index(keep))
    elif panel._synth_ids:
        panel.cmb_synth.SetSelection(0)
    panel.cmb_synth.Enable(len(panel._synth_ids) > 1)
    _fill_voices(panel, keep=getattr(panel, '_keep_voice', '') or '')
    panel._keep_voice = ''


def _fill_voices(panel, keep=''):
    """The voices of the chosen synthesizer, read on a worker (SAPI is
    COM, a Wine bridge is a process) and put in on the GUI thread - the
    page never waits for them."""
    from titan_access import speech_systems as _sys
    synth = _chosen_synth(panel)
    panel._voice_ticket[0] += 1
    ticket = panel._voice_ticket[0]
    panel.cmb_voice.Clear()
    panel._voice_ids = []
    if not synth:
        panel.cmb_voice.Enable(False)
        _fill_variants(panel, keep='')
        return
    panel.cmb_voice.Append(L("settings.speech.loadingVoices"))
    panel.cmb_voice.SetSelection(0)

    def read():
        try:
            rows = _sys.voices(synth)
        except Exception as e:                       # noqa: BLE001
            print(f"[TitanAccess] voices of {synth}: {e}")
            rows = []

        def put():
            try:
                if ticket != panel._voice_ticket[0] or not panel:
                    return
                panel.cmb_voice.Clear()
                panel._voice_ids = [key for key, _label in rows]
                for _key, label in rows:
                    panel.cmb_voice.Append(label)
                if keep in panel._voice_ids:
                    panel.cmb_voice.SetSelection(panel._voice_ids.index(keep))
                elif panel._voice_ids:
                    panel.cmb_voice.SetSelection(0)
                panel.cmb_voice.Enable(bool(panel._voice_ids))
                _fill_variants(panel, keep=getattr(panel, '_keep_variant',
                                                   '') or '')
                panel._keep_variant = ''
            except RuntimeError:
                pass                                 # the page has gone
        wx.CallAfter(put)
    threading.Thread(target=read, name='TitanAccessVoices',
                     daemon=True).start()


def _fill_variants(panel, keep=''):
    """The variants of the chosen voice, on a worker like the voices.
    A synthesizer without variants leaves the row disabled and empty."""
    if getattr(panel, 'cmb_variant', None) is None:
        return
    from titan_access import speech_systems as _sys
    synth = _chosen_synth(panel)
    voice = _picked(panel.cmb_voice, panel._voice_ids)
    panel._variant_ticket[0] += 1
    ticket = panel._variant_ticket[0]
    panel.cmb_variant.Clear()
    panel._variant_ids = []
    if not _variants_possible(synth) or not voice:
        panel.cmb_variant.Enable(False)
        return

    def read():
        try:
            rows = _sys.variants(synth, voice)
        except Exception:                            # noqa: BLE001
            rows = []

        def put():
            try:
                if ticket != panel._variant_ticket[0] or not panel:
                    return
                panel.cmb_variant.Clear()
                panel._variant_ids = [key for key, _label in rows]
                for _key, label in rows:
                    panel.cmb_variant.Append(label)
                if keep in panel._variant_ids:
                    panel.cmb_variant.SetSelection(
                        panel._variant_ids.index(keep))
                elif panel._variant_ids:
                    panel.cmb_variant.SetSelection(0)
                panel.cmb_variant.Enable(bool(panel._variant_ids))
            except RuntimeError:
                pass
        wx.CallAfter(put)
    threading.Thread(target=read, name='TitanAccessVariants',
                     daemon=True).start()


def _build_generic(panel, scroller, s, sid):
    """One ui section of the schema, control by control.

    Every control is the real one for its kind - a tick box is a
    `wx.CheckBox`, a choice a `wx.Choice` behind a label, a number a
    `wx.SpinCtrl`, a text a `wx.TextCtrl` - and every one carries its
    help sentence as its tooltip and help text. What is built is written
    down in ``panel.controls`` so loading and saving need no list of
    attribute names, which is how a control used to be forgotten by one
    of the two.
    """
    rows = ()
    for known, _title, entries in (_schema.SECTIONS if _schema else ()):
        if known == sid:
            rows = entries
            break
    box = _section(scroller, s, _section_title(sid))
    if not hasattr(panel, 'controls'):
        panel.controls = {}
    for entry in rows:
        if (entry.section, entry.key) == ('General', 'Enabled'):
            _build_enable(panel, scroller, box)
            panel.controls[(entry.section, entry.key)] = (entry, panel.chk_enabled)
            continue
        label = L(entry.label)
        if entry.kind == 'bool':
            ctrl = _checkbox(scroller, box, label)
        elif entry.kind in ('choice', 'braille_table'):
            if entry.kind == 'braille_table':
                try:
                    from titan_access import braille
                    tables = braille.tables_available()
                except Exception:
                    tables = []
                panel._braille_tables = [''] + [name for name, _l in tables]
                names = [L("settings.braille.autoTable")] + [l for _n, l in tables]
            else:
                names = [L(key) for _value, key in _schema.options(entry)]
            ctrl = _choice_row(scroller, box, label, names)
        elif entry.kind == 'range':
            low, high, _step = entry.extra
            ctrl = _spin_row(scroller, box, label, low, high)
        elif entry.kind == 'text':
            ctrl = _text_row(scroller, box, label)
        elif entry.kind == 'hotkey':
            ctrl = _hotkey_row(scroller, box, label)
        else:
            continue
        help_text = L(entry.help)
        if help_text and help_text != entry.help:
            try:
                ctrl.SetToolTip(help_text)
                ctrl.SetHelpText(help_text)
            except Exception:
                pass
        panel.controls[(entry.section, entry.key)] = (entry, ctrl)


def _build_profiles(panel, scroller, s):
    """The per-program profiles that exist, and a way to drop one.

    A profile is EDITED in the walked settings (Insert+Ctrl+G, "Settings
    for this program only"), where the program in front is known; here
    it can be seen and removed.
    """
    try:
        from titan_access import profiles
        names = profiles.programs()
    except Exception:
        return
    box = _section(scroller, s, L("settings.profiles.title"))
    box.Add(wx.StaticText(scroller, label=L("settings.profiles.note")),
            0, wx.LEFT | wx.BOTTOM, 6)
    panel.lst_profiles = wx.ListBox(scroller, choices=names)
    panel.lst_profiles.SetName(L("settings.profiles.title"))
    box.Add(panel.lst_profiles, 0, wx.EXPAND | wx.ALL, 4)
    remove = wx.Button(scroller, label=L("settings.profiles.remove"))
    box.Add(remove, 0, wx.ALL, 4)

    def _remove(_evt):
        at = panel.lst_profiles.GetSelection()
        if at == wx.NOT_FOUND:
            return
        try:
            from titan_access import profiles
            profiles.remove(panel.lst_profiles.GetString(at))
        except Exception as e:
            print(f"[TitanAccess] profile remove: {e}")
            return
        panel.lst_profiles.Delete(at)
    remove.Bind(wx.EVT_BUTTON, _remove)


#: The shared switches (`portable/switchboard.py`) and their defaults -
#: kept as a table of their own because the switchboard and the tests
#: read it; the schema's "sounds" section is built from the same list.
SHARED_SWITCHES = (
    ("auditoryIcons", True), ("auditoryIconsEverywhere", False),
    ("soundScheme", True), ("dialogKinds", True), ("busyState", True),
    ("attentionState", True), ("liveStatusBars", True), ("monitors", True),
    ("surfaceReading", False), ("guestCursor", False), ("drawnApps", True),
    ("agentLink", False),
    ("windowsSemantics", True), ("speakShortcuts", True),
    ("uiaNotifications", True),
)


_BUILDERS = {sid: (lambda p, sc, sz, which=sid: _build_generic(p, sc, sz, which))
             for sid in SECTIONS}
_BUILDERS['speech'] = _build_speech


# --------------------------------------------------------------------------- #
# Enum <-> choice index helpers
# --------------------------------------------------------------------------- #
def _enum_index(all_values, current, default=0):
    try:
        return all_values.index(current)
    except (ValueError, AttributeError):
        return default


# --------------------------------------------------------------------------- #
# Load / Save
# --------------------------------------------------------------------------- #
def _has(panel, *names):
    return all(hasattr(panel, name) for name in names)


def load_panel(panel):
    """Populate every control the panel has from the settings store."""
    if not STORE_AVAILABLE:
        return
    st = get_settings()

    if _has(panel, 'chk_enabled'):
        try:
            from titan_access.engine import is_running
            panel.chk_enabled.SetValue(bool(is_running()))
        except Exception:
            panel.chk_enabled.SetValue(st.enabled)

    if _has(panel, 'cmb_system'):
        from titan_access import speech_systems as _sys
        system, synth, voice = _sys.current(st)
        keys = [k for k, _l in panel._systems]
        panel.cmb_system.SetSelection(keys.index(system) if system in keys
                                      else 0)
        panel._keep_voice = voice
        panel._keep_variant = _sys.current_variant(st)
        _fill_synths(panel, keep=synth)
        panel.spn_rate.SetValue(st.get_int(SEC_SPEECH, "Rate", 0))
        panel.spn_pitch.SetValue(st.get_int(SEC_SPEECH, "Pitch", 0))
        panel.spn_volume.SetValue(st.get_int(SEC_SPEECH, "Volume", 100))

    for (section, key), (entry, ctrl) in getattr(panel, 'controls', {}).items():
        try:
            if (section, key) == ('General', 'Enabled'):
                continue                           # set above, off the engine
            if entry.kind == 'bool':
                ctrl.SetValue(st.get_bool(section, key, bool(entry.default)))
            elif entry.kind == 'range':
                ctrl.SetValue(st.get_int(section, key, int(entry.default)))
            elif entry.kind == 'text':
                ctrl.SetValue(str(st.get(section, key, entry.default) or ''))
            elif entry.kind == 'hotkey':
                ctrl.show_hotkey(str(st.get(section, key, entry.default) or ''))
            elif entry.kind == 'braille_table':
                tables = getattr(panel, '_braille_tables', [''])
                chosen = str(st.get(section, key, '') or '')
                ctrl.SetSelection(tables.index(chosen) if chosen in tables else 0)
            elif entry.kind == 'choice':
                values = [str(v) for v, _k in _schema.options(entry)]
                now = str(st.get(section, key, entry.default) or '')
                ctrl.SetSelection(values.index(now) if now in values else 0)
        except Exception as e:
            print(f"[TitanAccess] settings load {section}/{key}: {e}")

    if getattr(panel, 'cmb_scheme', None) is not None:
        try:
            from titan_access.portable import speechSchemes as _ss
            keys = getattr(panel, '_scheme_keys', [])
            active = _ss.active()
            if active in keys:
                panel.cmb_scheme.SetSelection(keys.index(active))
        except Exception:
            pass


def save_panel(panel):
    """Write every control the panel has back into the store and apply live."""
    if not STORE_AVAILABLE:
        return
    st = get_settings()

    if _has(panel, 'chk_enabled'):
        st.enabled = panel.chk_enabled.GetValue()

    if _has(panel, 'cmb_system'):
        from titan_access import speech_systems as _sys
        system = _chosen_system(panel)
        synth = _chosen_synth(panel)
        voice = _picked(panel.cmb_voice, panel._voice_ids)
        if not panel._voice_ids:
            # The voices had not arrived: the voice already chosen stays.
            now = _sys.current(st)
            voice = now[2] if (now[0], now[1]) == (system, synth) else ''
        variant = _picked(panel.cmb_variant, panel._variant_ids) \
            if getattr(panel, 'cmb_variant', None) is not None else ''
        if not getattr(panel, '_variant_ids', None):
            now = _sys.current(st)
            variant = _sys.current_variant(st) \
                if now == (system, synth, voice) else ''
        for (section, key), value in _sys.settings_for(system, synth,
                                                        voice,
                                                        variant).items():
            if isinstance(value, bool):
                st.set_bool(section, key, value)
            else:
                st.set(section, key, value)
        st.set_int(SEC_SPEECH, "Rate", panel.spn_rate.GetValue())
        st.set_int(SEC_SPEECH, "Pitch", panel.spn_pitch.GetValue())
        st.set_int(SEC_SPEECH, "Volume", panel.spn_volume.GetValue())

    for (section, key), (entry, ctrl) in getattr(panel, 'controls', {}).items():
        try:
            if (section, key) == ('General', 'Enabled'):
                continue                           # written above
            if entry.kind == 'bool':
                st.set_bool(section, key, ctrl.GetValue())
            elif entry.kind == 'range':
                st.set_int(section, key, ctrl.GetValue())
            elif entry.kind == 'text':
                st.set(section, key, ctrl.GetValue())
            elif entry.kind == 'hotkey':
                from titan_access import hotkeys
                if st.get(section, key, entry.default) != ctrl._hotkey:
                    st.set(section, key, ctrl._hotkey)
            elif entry.kind == 'braille_table':
                tables = getattr(panel, '_braille_tables', [''])
                at = ctrl.GetSelection()
                st.set(section, key, tables[at] if 0 <= at < len(tables) else '')
            elif entry.kind == 'choice':
                values = [str(v) for v, _k in _schema.options(entry)]
                at = ctrl.GetSelection()
                if 0 <= at < len(values):
                    st.set(section, key, values[at])
        except Exception as e:
            print(f"[TitanAccess] settings save {section}/{key}: {e}")

    if getattr(panel, 'cmb_scheme', None) is not None:
        try:
            from titan_access.portable import speechSchemes as _ss
            keys = getattr(panel, '_scheme_keys', [])
            at = panel.cmb_scheme.GetSelection()
            if 0 <= at < len(keys):
                _ss.use(keys[at])
        except Exception:
            pass

    st.save()
    try:
        from titan_access import hotkeys
        hotkeys.changed()
    except Exception:
        pass
    _apply_live(st)
    print("[TitanAccess] settings saved")


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
def register(component_manager):
    """Register the Titan Access settings categories with TCE.

    One category for the reader, and a category inside it for every
    section - which is what the settings window shows as a category in a
    category. No-ops if wxPython is unavailable so importing this module
    never fails on a headless host.
    """
    if not WX_AVAILABLE:
        print("[TitanAccess] settings_panel: wx unavailable, skipping registration")
        return
    main = L("settings.categoryName")
    try:
        component_manager.register_settings_category(
            main, lambda parent: build_panel(parent, 'main'),
            save_panel, load_panel)
    except Exception as e:  # pragma: no cover
        print(f"[TitanAccess] settings category registration failed: {e}")
        return
    for which in SECTIONS:
        name = '%s: %s' % (main, _section_title(which))
        try:
            component_manager.register_settings_category(
                name, (lambda w: (lambda parent: build_panel(parent, w)))(which),
                save_panel, load_panel, parent=main)
        except TypeError:
            # A component manager from before categories could nest.
            component_manager.register_settings_category(
                name, (lambda w: (lambda parent: build_panel(parent, w)))(which),
                save_panel, load_panel)
        except Exception as e:  # pragma: no cover
            print(f"[TitanAccess] settings category {which} failed: {e}")


def _variants_possible(synth):
    """A synthesizer with a variant level: an NVDA add-on synthesizer
    (Cerence's compact / embedded-pro...) or eSpeak (its voices/!v)."""
    synth = str(synth or '')
    return synth.startswith('nvda:') or synth in ('espeak', 'espeak_dll')
