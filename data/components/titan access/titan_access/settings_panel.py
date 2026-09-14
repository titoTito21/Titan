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
        if inst is not None and getattr(inst, "speech", None) is not None:
            inst.speech.apply_settings()   # no-op for speech params by design
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
#: The sections, each a category of its own inside "Titan Access". The
#: main category holds the switch; every section is a child category
#: (`register_settings_category(..., parent=...)`), so the settings window
#: lists "Titan Access" and, indented under it, Speech, General, Verbosity,
#: Navigation, Dial, Reader, Sounds and Text editing - a category in a
#: category, which is what a page of eighty controls needed to become.
SECTIONS = ('speech', 'general', 'verbosity', 'navigation', 'dial',
            'reader', 'sounds', 'braille', 'textEditing')


def _section_title(which):
    return L({
        'speech': 'settings.section.speech',
        'general': 'settings.section.general',
        'verbosity': 'settings.section.verbosity',
        'navigation': 'settings.section.navigation',
        'dial': 'settings.section.dial',
        'reader': 'settings.section.reader',
        'sounds': 'settings.section.sounds',
        'braille': 'settings.section.braille',
        'textEditing': 'settings.section.textEditing',
    }[which])


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
    # ------------------- Enable screen reader (live) ------------------- #
    # Checking this turns the reader ON immediately; unchecking turns it OFF
    # immediately. The state is also persisted (General/Enabled) so the reader
    # auto-starts with the component next time.
    panel.chk_enabled = wx.CheckBox(scroller, label=L("settings.general.enable"))
    s.Add(panel.chk_enabled, 0, wx.ALL, 8)

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
    s.Add(wx.StaticText(scroller, label=L("settings.main.note")), 0, wx.ALL, 6)


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


def _build_general(panel, scroller, s):
    gen = _section(scroller, s, L("settings.section.general"))
    panel.chk_mute = _checkbox(scroller, gen, L("settings.general.muteOutsideTce"))
    panel.cmb_startup = _choice_row(scroller, gen,
                                    L("settings.general.startupAnnouncement"),
                                    _announce_labels())
    panel.chk_entry_sound = _checkbox(scroller, gen,
                                      L("settings.general.tceEntrySound"))
    panel.cmb_modifier = _choice_row(scroller, gen, L("settings.general.modifier"),
                                     [L("settings.modifier.insert"),
                                      L("settings.modifier.capsLock"),
                                      L("settings.modifier.insertAndCapsLock")])
    panel.txt_welcome = _text_row(scroller, gen, L("settings.general.welcomeMessage"))
    panel.chk_speak_hints = _checkbox(scroller, gen,
                                      L("settings.general.speakHints"))
    panel.chk_virtual_screen = _checkbox(scroller, gen,
                                         L("settings.general.virtualScreen"))


def _build_verbosity(panel, scroller, s):
    vb = _section(scroller, s, L("settings.section.verbosity"))
    panel.chk_basic = _checkbox(scroller, vb,
                                L("settings.verbosity.announceBasicControls"))
    panel.chk_block = _checkbox(scroller, vb,
                                L("settings.verbosity.announceBlockControls"))
    panel.chk_list_pos = _checkbox(scroller, vb,
                                   L("settings.verbosity.announceListPosition"))
    vb.Add(wx.StaticText(scroller, label=L("settings.verbosity.menuInfo")),
           0, wx.LEFT | wx.TOP, 6)
    panel.chk_menu_count = _checkbox(scroller, vb,
                                     L("settings.verbosity.menuItemCount"))
    panel.chk_menu_name = _checkbox(scroller, vb, L("settings.verbosity.menuName"))
    panel.chk_menu_sounds = _checkbox(scroller, vb,
                                      L("settings.verbosity.menuSounds"))
    vb.Add(wx.StaticText(scroller, label=L("settings.verbosity.elementInfo")),
           0, wx.LEFT | wx.TOP, 6)
    panel.chk_elem_name = _checkbox(scroller, vb,
                                    L("settings.verbosity.elementName"))
    panel.chk_elem_type = _checkbox(scroller, vb,
                                    L("settings.verbosity.elementType"))
    panel.chk_elem_state = _checkbox(scroller, vb,
                                     L("settings.verbosity.elementState"))
    panel.chk_elem_param = _checkbox(scroller, vb,
                                     L("settings.verbosity.elementParameter"))
    panel.cmb_toggle_keys = _choice_row(scroller, vb,
                                        L("settings.verbosity.toggleKeysMode"),
                                        _announce_labels())


def _build_navigation(panel, scroller, s):
    nav = _section(scroller, s, L("settings.section.navigation"))
    panel.chk_adv_nav = _checkbox(scroller, nav,
                                  L("settings.navigation.advancedNavigation"))
    panel.chk_nav_types = _checkbox(scroller, nav,
                                    L("settings.navigation.announceControlTypes"))
    panel.chk_hierarchy = _checkbox(scroller, nav,
                                    L("settings.navigation.announceHierarchyLevel"))
    panel.cmb_window_bounds = _choice_row(scroller, nav,
                                          L("settings.navigation.windowBoundsMode"),
                                          _announce_labels())
    panel.chk_phonetic_dial = _checkbox(scroller, nav,
                                        L("settings.navigation.phoneticInDial"))


def _build_dial(panel, scroller, s):
    dial = _section(scroller, s, L("settings.section.dial"))
    panel.chk_dial_chars = _checkbox(scroller, dial, L("settings.dial.characters"))
    panel.chk_dial_words = _checkbox(scroller, dial, L("settings.dial.words"))
    panel.chk_dial_buttons = _checkbox(scroller, dial, L("settings.dial.buttons"))
    panel.chk_dial_headings = _checkbox(scroller, dial, L("settings.dial.headings"))
    panel.chk_dial_volume = _checkbox(scroller, dial, L("settings.dial.volume"))
    panel.chk_dial_speed = _checkbox(scroller, dial, L("settings.dial.speed"))
    panel.chk_dial_voice = _checkbox(scroller, dial, L("settings.dial.voice"))
    panel.chk_dial_synth = _checkbox(scroller, dial, L("settings.dial.synthesizer"))
    panel.chk_dial_places = _checkbox(scroller, dial,
                                      L("settings.dial.importantPlaces"))


def _build_reader(panel, scroller, s):
    rd = _section(scroller, s, L("settings.section.reader"))
    panel.chk_scan_mode = _checkbox(scroller, rd, L("settings.reader.scanMode"))
    rd.Add(wx.StaticText(scroller, label=L("settings.reader.scanModeInfo")),
           0, wx.LEFT | wx.BOTTOM, 6)
    panel.chk_ai_ocr = _checkbox(scroller, rd, L("settings.reader.useAiOcr"))
    panel.chk_ai_ocr_labels = _checkbox(scroller, rd,
                                        L("settings.reader.aiOcrLabels"))
    rd.Add(wx.StaticText(scroller, label=L("settings.reader.aiOcrInfo")),
           0, wx.LEFT | wx.BOTTOM, 6)
    panel.cmb_progress = _choice_row(scroller, rd,
                                     L("settings.reader.progressMode"),
                                     _announce_labels())
    rd.Add(wx.StaticText(scroller, label=L("settings.reader.progressInfo")),
           0, wx.LEFT | wx.BOTTOM, 6)


#: The shared switches (`portable/switchboard.py`) and their defaults.
SHARED_SWITCHES = (
    ("auditoryIcons", True), ("auditoryIconsEverywhere", False),
    ("soundScheme", True), ("dialogKinds", True), ("busyState", True),
    ("attentionState", True), ("liveStatusBars", True), ("monitors", True),
    ("surfaceReading", False), ("guestCursor", False), ("agentLink", False),
    ("windowsSemantics", True),
)


def _build_sounds(panel, scroller, s):
    # The switches of the modules this reader shares with the NVDA add-on:
    # they used to answer "on" here and could be changed from nowhere.
    rd = _section(scroller, s, L("settings.section.sounds"))
    panel.chk_reader = {}
    for key, _default in SHARED_SWITCHES:
        panel.chk_reader[key] = _checkbox(scroller, rd,
                                          L("settings.reader." + key))


def _build_braille(panel, scroller, s):
    br = _section(scroller, s, L("settings.section.braille"))
    panel.chk_braille = _checkbox(scroller, br, L("settings.braille.enabled"))
    br.Add(wx.StaticText(scroller, label=L("settings.braille.info")),
           0, wx.LEFT | wx.BOTTOM, 6)
    try:
        from titan_access import braille
        tables = [L("settings.braille.autoTable")] + [
            label for _name, label in braille.tables_available()]
        panel._braille_tables = [''] + [
            name for name, _label in braille.tables_available()]
    except Exception:
        tables = [L("settings.braille.autoTable")]
        panel._braille_tables = ['']
    panel.cmb_braille_table = _choice_row(scroller, br,
                                          L("settings.braille.table"), tables)
    panel.chk_braille_viewer = _checkbox(scroller, br,
                                         L("settings.braille.viewer"))


def _build_text_editing(panel, scroller, s):
    te = _section(scroller, s, L("settings.section.textEditing"))
    panel.chk_phonetic = _checkbox(scroller, te,
                                   L("settings.textEditing.phoneticLetters"))
    panel.cmb_echo = _choice_row(scroller, te,
                                 L("settings.textEditing.keyboardEcho"),
                                 [L("settings.echo.none"),
                                  L("settings.echo.characters"),
                                  L("settings.echo.words"),
                                  L("settings.echo.charactersAndWords")])
    panel.chk_text_bounds = _checkbox(scroller, te,
                                      L("settings.textEditing.announceTextBounds"))


_BUILDERS = {
    'speech': _build_speech, 'general': _build_general,
    'verbosity': _build_verbosity, 'navigation': _build_navigation,
    'dial': _build_dial, 'reader': _build_reader, 'sounds': _build_sounds,
    'braille': _build_braille, 'textEditing': _build_text_editing,
}


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

    for key, box in getattr(panel, "chk_reader", {}).items():
        default = dict(SHARED_SWITCHES).get(key, True)
        box.SetValue(st.get_bool("Reader", key, default))

    if getattr(panel, 'cmb_scheme', None) is not None:
        try:
            from titan_access.portable import speechSchemes as _ss
            keys = getattr(panel, '_scheme_keys', [])
            active = _ss.active()
            if active in keys:
                panel.cmb_scheme.SetSelection(keys.index(active))
        except Exception:
            pass

    if _has(panel, 'chk_braille'):
        panel.chk_braille.SetValue(st.get_bool("Braille", "Enabled", False))
        panel.chk_braille_viewer.SetValue(
            st.get_bool("Braille", "Viewer", True))
        chosen = str(st.get("Braille", "Table", "") or "")
        tables = getattr(panel, '_braille_tables', [''])
        panel.cmb_braille_table.SetSelection(
            tables.index(chosen) if chosen in tables else 0)

    if _has(panel, 'chk_mute'):
        panel.chk_mute.SetValue(st.mute_outside_tce)
        panel.cmb_startup.SetSelection(
            _enum_index(list(AnnouncementMode.ALL), st.startup_announcement, 3))
        panel.chk_entry_sound.SetValue(st.tce_entry_sound)
        panel.cmb_modifier.SetSelection(
            _enum_index(list(ScreenReaderModifier.ALL), st.modifier, 2))
        panel.txt_welcome.SetValue(st.welcome_message)
        panel.chk_speak_hints.SetValue(st.speak_hints)
        panel.chk_virtual_screen.SetValue(st.virtual_screen)

    if _has(panel, 'chk_basic'):
        panel.chk_basic.SetValue(st.get_bool(SEC_VERBOSITY, "AnnounceBasicControls", True))
        panel.chk_block.SetValue(st.get_bool(SEC_VERBOSITY, "AnnounceBlockControls", True))
        panel.chk_list_pos.SetValue(st.get_bool(SEC_VERBOSITY, "AnnounceListPosition", True))
        panel.chk_menu_count.SetValue(st.get_bool(SEC_VERBOSITY, "MenuItemCount", True))
        panel.chk_menu_name.SetValue(st.get_bool(SEC_VERBOSITY, "MenuName", True))
        panel.chk_menu_sounds.SetValue(st.get_bool(SEC_VERBOSITY, "MenuSounds", True))
        panel.chk_elem_name.SetValue(st.get_bool(SEC_VERBOSITY, "ElementName", True))
        panel.chk_elem_type.SetValue(st.get_bool(SEC_VERBOSITY, "ElementType", True))
        panel.chk_elem_state.SetValue(st.get_bool(SEC_VERBOSITY, "ElementState", True))
        panel.chk_elem_param.SetValue(st.get_bool(SEC_VERBOSITY, "ElementParameter", True))
        panel.cmb_toggle_keys.SetSelection(_enum_index(
            list(AnnouncementMode.ALL),
            AnnouncementMode.normalize(st.get(SEC_VERBOSITY, "ToggleKeysMode")), 3))

    if _has(panel, 'chk_adv_nav'):
        panel.chk_adv_nav.SetValue(st.get_bool(SEC_NAVIGATION, "AdvancedNavigation", False))
        panel.chk_nav_types.SetValue(
            st.get_bool(SEC_NAVIGATION, "AnnounceControlTypesNavigation", True))
        panel.chk_hierarchy.SetValue(
            st.get_bool(SEC_NAVIGATION, "AnnounceHierarchyLevel", True))
        panel.cmb_window_bounds.SetSelection(_enum_index(
            list(AnnouncementMode.ALL),
            AnnouncementMode.normalize(st.get(SEC_NAVIGATION, "WindowBoundsMode")), 3))
        panel.chk_phonetic_dial.SetValue(st.get_bool(SEC_NAVIGATION, "PhoneticInDial", True))

    if _has(panel, 'chk_dial_chars'):
        panel.chk_dial_chars.SetValue(st.get_bool(SEC_DIAL, "DialCharacters", True))
        panel.chk_dial_words.SetValue(st.get_bool(SEC_DIAL, "DialWords", True))
        panel.chk_dial_buttons.SetValue(st.get_bool(SEC_DIAL, "DialButtons", True))
        panel.chk_dial_headings.SetValue(st.get_bool(SEC_DIAL, "DialHeadings", True))
        panel.chk_dial_volume.SetValue(st.get_bool(SEC_DIAL, "DialVolume", True))
        panel.chk_dial_speed.SetValue(st.get_bool(SEC_DIAL, "DialSpeed", True))
        panel.chk_dial_voice.SetValue(st.get_bool(SEC_DIAL, "DialVoice", True))
        panel.chk_dial_synth.SetValue(st.get_bool(SEC_DIAL, "DialSynthesizer", True))
        panel.chk_dial_places.SetValue(st.get_bool(SEC_DIAL, "DialImportantPlaces", True))

    if _has(panel, 'chk_scan_mode'):
        panel.chk_scan_mode.SetValue(st.scan_mode)
        panel.chk_ai_ocr.SetValue(st.ai_ocr)
        panel.chk_ai_ocr_labels.SetValue(st.ai_ocr_labels)
        panel.cmb_progress.SetSelection(
            _enum_index(list(AnnouncementMode.ALL), st.progress_mode, 3))

    if _has(panel, 'chk_phonetic'):
        panel.chk_phonetic.SetValue(st.phonetic_letters)
        panel.cmb_echo.SetSelection(
            _enum_index(list(KeyboardEchoSetting.ALL), st.keyboard_echo, 3))
        panel.chk_text_bounds.SetValue(st.announce_text_bounds)


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

    for key, box in getattr(panel, "chk_reader", {}).items():
        st.set_bool("Reader", key, box.GetValue())

    if _has(panel, 'chk_mute'):
        st.mute_outside_tce = panel.chk_mute.GetValue()
        st.startup_announcement = AnnouncementMode.ALL[
            max(0, panel.cmb_startup.GetSelection())]
        st.tce_entry_sound = panel.chk_entry_sound.GetValue()
        st.modifier = ScreenReaderModifier.ALL[
            max(0, panel.cmb_modifier.GetSelection())]
        st.welcome_message = panel.txt_welcome.GetValue()
        st.speak_hints = panel.chk_speak_hints.GetValue()
        st.virtual_screen = panel.chk_virtual_screen.GetValue()

    if _has(panel, 'chk_basic'):
        st.set_bool(SEC_VERBOSITY, "AnnounceBasicControls", panel.chk_basic.GetValue())
        st.set_bool(SEC_VERBOSITY, "AnnounceBlockControls", panel.chk_block.GetValue())
        st.set_bool(SEC_VERBOSITY, "AnnounceListPosition", panel.chk_list_pos.GetValue())
        st.set_bool(SEC_VERBOSITY, "MenuItemCount", panel.chk_menu_count.GetValue())
        st.set_bool(SEC_VERBOSITY, "MenuName", panel.chk_menu_name.GetValue())
        st.set_bool(SEC_VERBOSITY, "MenuSounds", panel.chk_menu_sounds.GetValue())
        st.set_bool(SEC_VERBOSITY, "ElementName", panel.chk_elem_name.GetValue())
        st.set_bool(SEC_VERBOSITY, "ElementType", panel.chk_elem_type.GetValue())
        st.set_bool(SEC_VERBOSITY, "ElementState", panel.chk_elem_state.GetValue())
        st.set_bool(SEC_VERBOSITY, "ElementParameter", panel.chk_elem_param.GetValue())
        st.set(SEC_VERBOSITY, "ToggleKeysMode",
               AnnouncementMode.ALL[max(0, panel.cmb_toggle_keys.GetSelection())])

    if _has(panel, 'chk_adv_nav'):
        st.set_bool(SEC_NAVIGATION, "AdvancedNavigation", panel.chk_adv_nav.GetValue())
        st.set_bool(SEC_NAVIGATION, "AnnounceControlTypesNavigation",
                    panel.chk_nav_types.GetValue())
        st.set_bool(SEC_NAVIGATION, "AnnounceHierarchyLevel", panel.chk_hierarchy.GetValue())
        st.set(SEC_NAVIGATION, "WindowBoundsMode",
               AnnouncementMode.ALL[max(0, panel.cmb_window_bounds.GetSelection())])
        st.set_bool(SEC_NAVIGATION, "PhoneticInDial", panel.chk_phonetic_dial.GetValue())

    if _has(panel, 'chk_dial_chars'):
        st.set_bool(SEC_DIAL, "DialCharacters", panel.chk_dial_chars.GetValue())
        st.set_bool(SEC_DIAL, "DialWords", panel.chk_dial_words.GetValue())
        st.set_bool(SEC_DIAL, "DialButtons", panel.chk_dial_buttons.GetValue())
        st.set_bool(SEC_DIAL, "DialHeadings", panel.chk_dial_headings.GetValue())
        st.set_bool(SEC_DIAL, "DialVolume", panel.chk_dial_volume.GetValue())
        st.set_bool(SEC_DIAL, "DialSpeed", panel.chk_dial_speed.GetValue())
        st.set_bool(SEC_DIAL, "DialVoice", panel.chk_dial_voice.GetValue())
        st.set_bool(SEC_DIAL, "DialSynthesizer", panel.chk_dial_synth.GetValue())
        st.set_bool(SEC_DIAL, "DialImportantPlaces", panel.chk_dial_places.GetValue())

    if _has(panel, 'chk_scan_mode'):
        st.scan_mode = panel.chk_scan_mode.GetValue()
        st.ai_ocr = panel.chk_ai_ocr.GetValue()
        st.ai_ocr_labels = panel.chk_ai_ocr_labels.GetValue()
        st.progress_mode = AnnouncementMode.ALL[
            max(0, panel.cmb_progress.GetSelection())]

    if _has(panel, 'chk_phonetic'):
        st.phonetic_letters = panel.chk_phonetic.GetValue()
        st.keyboard_echo = KeyboardEchoSetting.ALL[max(0, panel.cmb_echo.GetSelection())]
        st.announce_text_bounds = panel.chk_text_bounds.GetValue()

    if getattr(panel, 'cmb_scheme', None) is not None:
        try:
            from titan_access.portable import speechSchemes as _ss
            keys = getattr(panel, '_scheme_keys', [])
            at = panel.cmb_scheme.GetSelection()
            if 0 <= at < len(keys):
                _ss.use(keys[at])
        except Exception:
            pass

    if _has(panel, 'chk_braille'):
        st.set_bool("Braille", "Enabled", panel.chk_braille.GetValue())
        st.set_bool("Braille", "Viewer", panel.chk_braille_viewer.GetValue())
        tables = getattr(panel, '_braille_tables', [''])
        at = panel.cmb_braille_table.GetSelection()
        st.set("Braille", "Table", tables[at] if 0 <= at < len(tables) else "")

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
