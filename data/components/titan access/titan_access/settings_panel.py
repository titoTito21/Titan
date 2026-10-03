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
Titan Access speaks **only** through Titan's own TTS layer
(:mod:`src.titan_core.tce_speech`); the user's SAPI5 / OneCore synthesizers are
not ported. So instead of the C# synthesizer picker we expose:

* **Engine** - populated from :func:`tce_speech.get_available_engines`; the
  selection is stored under ``Speech/Synthesizer`` and applied with
  :func:`tce_speech.set_engine`.
* **Voice** - populated from :func:`tce_speech.get_available_voices`; stored
  under ``Speech/Voice``.
* **Rate / Volume / Pitch** - numeric spinners passed straight through to the
  Titan engine.

The module imports cleanly with no GUI present (``import wx`` is guarded) and
all ``src.*`` imports are best-effort, keeping the screen reader independent of
Titan internals. :func:`register` no-ops when wxPython is unavailable.
"""

# --------------------------------------------------------------------------- #
# Optional GUI / engine imports (keep this module importable headless)
# --------------------------------------------------------------------------- #
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


def _engine_ids():
    tts = _tce_speech()
    if tts is None:
        return []
    try:
        return list(tts.get_available_engines() or [])
    except Exception:
        return []


def _voice_entries():
    """Return the current engine's voices as ``(display, id)`` pairs."""
    tts = _tce_speech()
    if tts is None:
        return []
    try:
        voices = list(tts.get_available_voices() or [])
    except Exception:
        return []
    pairs = []
    for v in voices:
        if isinstance(v, dict):
            disp = v.get("display_name") or v.get("name") or v.get("id") or str(v)
            vid = v.get("id") or v.get("name") or disp
        else:
            disp = str(v)
            vid = str(v)
        pairs.append((disp, vid))
    return pairs


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
    panel.chk_own_voice = _checkbox(scroller, sp, L("settings.speech.ownVoice"))
    engines = _engine_ids()
    panel._engine_ids = list(engines)
    panel.cmb_engine = _choice_row(scroller, sp, L("settings.speech.engine"),
                                   [str(e) for e in engines] or [L("settings.speech.noEngine")])
    panel.cmb_voice = _choice_row(scroller, sp, L("settings.speech.voice"), [])
    panel.voice_choice = panel.cmb_voice
    panel._voice_ids = []
    panel.spn_rate = _spin_row(scroller, sp, L("settings.speech.rate"), -10, 10)
    panel.spn_pitch = _spin_row(scroller, sp, L("settings.speech.pitch"), -10, 10)
    panel.spn_volume = _spin_row(scroller, sp, L("settings.speech.volume"), 0, 100)

    def _engine_chosen(_evt):
        _populate_voices_for(panel, _chosen_engine(panel), keep='')
    panel.cmb_engine.Bind(wx.EVT_CHOICE, _engine_chosen)


def _chosen_engine(panel):
    at = panel.cmb_engine.GetSelection()
    ids = getattr(panel, '_engine_ids', [])
    return ids[at] if 0 <= at < len(ids) else ''


def _populate_voices_for(panel, engine_id, keep=''):
    """The voices of ONE engine, asked of the reader's private engine so the
    shared one (Titan's apps and games) is never switched to list them."""
    pairs = []
    try:
        tts = _tce_speech()
        engine = tts.get_private_reader_engine() if tts else None
        if engine is not None and engine_id:
            engine.set_engine(engine_id)
            for v in (engine.get_available_voices() or []):
                if isinstance(v, dict):
                    disp = v.get("display_name") or v.get("name") or v.get("id") or str(v)
                else:
                    disp = str(v)
                pairs.append((disp, disp))
    except Exception as e:
        print(f"[TitanAccess] voices of {engine_id}: {e}")
    panel.cmb_voice.Clear()
    panel._voice_ids = []
    for disp, vid in pairs:
        panel.cmb_voice.Append(disp)
        panel._voice_ids.append(vid)
    if keep and keep in panel._voice_ids:
        panel.cmb_voice.SetSelection(panel._voice_ids.index(keep))
    elif panel._voice_ids:
        panel.cmb_voice.SetSelection(0)


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
    ("surfaceReading", False), ("guestCursor", False), ("agentLink", False),
    ("windowsSemantics", True), ("speakShortcuts", True),
    ("uiaNotifications", True),
)


_BUILDERS = {sid: (lambda p, sc, sz, which=sid: _build_generic(p, sc, sz, which))
             for sid in SECTIONS}
_BUILDERS['speech'] = _build_speech


def _populate_voices(panel, keep):
    """(Re)fill the voice choice; try to keep selection ``keep`` (a voice id)."""
    pairs = _voice_entries()
    panel.voice_choice.Clear()
    panel._voice_ids = []
    for disp, vid in pairs:
        panel.voice_choice.Append(disp)
        panel._voice_ids.append(vid)
    if keep:
        for i, vid in enumerate(panel._voice_ids):
            if str(vid) == str(keep) or pairs[i][0] == keep:
                panel.voice_choice.SetSelection(i)
                return
    if panel._voice_ids:
        panel.voice_choice.SetSelection(0)


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

    if _has(panel, 'chk_own_voice'):
        panel.chk_own_voice.SetValue(st.get_bool(SEC_SPEECH, "OwnVoice", False))
        engine_id = str(st.get(SEC_SPEECH, "Synthesizer", "") or "")
        ids = getattr(panel, '_engine_ids', [])
        if engine_id in ids:
            panel.cmb_engine.SetSelection(ids.index(engine_id))
        elif ids:
            panel.cmb_engine.SetSelection(0)
        if panel.chk_own_voice.GetValue():
            _populate_voices_for(panel, engine_id or _chosen_engine(panel),
                                 keep=str(st.get(SEC_SPEECH, "Voice", "") or ""))
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

    if _has(panel, 'chk_own_voice'):
        st.set_bool(SEC_SPEECH, "OwnVoice", panel.chk_own_voice.GetValue())
        st.set(SEC_SPEECH, "Synthesizer", _chosen_engine(panel))
        at = panel.cmb_voice.GetSelection()
        ids = getattr(panel, '_voice_ids', [])
        st.set(SEC_SPEECH, "Voice", ids[at] if 0 <= at < len(ids) else "")
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
