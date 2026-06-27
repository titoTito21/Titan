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
def build_panel(parent):
    """Build and return the Titan Access settings panel (a ``wx.Panel``)."""
    panel = wx.Panel(parent)
    outer = wx.BoxSizer(wx.VERTICAL)

    scroller = wx.ScrolledWindow(panel, style=wx.VSCROLL)
    scroller.SetScrollRate(0, 12)
    s = wx.BoxSizer(wx.VERTICAL)

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

    # ----------------------------- Speech ------------------------------ #
    # The screen reader does NOT carry its own speech settings. It speaks through
    # whatever engine / voice / rate / pitch / volume Titan TTS is configured
    # with (in Titan's own settings). We only show an informational note.
    sp = _section(scroller, s, L("settings.section.speech"))
    sp.Add(wx.StaticText(scroller, label=L("settings.speech.inheritNote")),
           0, wx.ALL, 6)

    # ----------------------------- General ----------------------------- #
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

    # ---------------------------- Verbosity ---------------------------- #
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

    # ---------------------------- Navigation --------------------------- #
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

    # ------------------------------- Dial ------------------------------ #
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

    # --------------------------- Text editing -------------------------- #
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

    scroller.SetSizer(s)
    outer.Add(scroller, 1, wx.EXPAND | wx.ALL, 4)
    panel.SetSizer(outer)
    return panel


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
def load_panel(panel):
    """Populate every control from the settings store."""
    if not STORE_AVAILABLE:
        return
    st = get_settings()

    # --- Enable screen reader (reflect the actual running state) ---
    try:
        from titan_access.engine import is_running
        panel.chk_enabled.SetValue(bool(is_running()))
    except Exception:
        panel.chk_enabled.SetValue(st.enabled)

    # --- Speech: nothing to load (inherited from Titan TTS) ---

    # --- General ---
    panel.chk_mute.SetValue(st.mute_outside_tce)
    panel.cmb_startup.SetSelection(
        _enum_index(list(AnnouncementMode.ALL), st.startup_announcement, 3))
    panel.chk_entry_sound.SetValue(st.tce_entry_sound)
    panel.cmb_modifier.SetSelection(
        _enum_index(list(ScreenReaderModifier.ALL), st.modifier, 2))
    panel.txt_welcome.SetValue(st.welcome_message)
    panel.chk_speak_hints.SetValue(st.speak_hints)
    panel.chk_virtual_screen.SetValue(st.virtual_screen)

    # --- Verbosity ---
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

    # --- Navigation ---
    panel.chk_adv_nav.SetValue(st.get_bool(SEC_NAVIGATION, "AdvancedNavigation", False))
    panel.chk_nav_types.SetValue(
        st.get_bool(SEC_NAVIGATION, "AnnounceControlTypesNavigation", True))
    panel.chk_hierarchy.SetValue(
        st.get_bool(SEC_NAVIGATION, "AnnounceHierarchyLevel", True))
    panel.cmb_window_bounds.SetSelection(_enum_index(
        list(AnnouncementMode.ALL),
        AnnouncementMode.normalize(st.get(SEC_NAVIGATION, "WindowBoundsMode")), 3))
    panel.chk_phonetic_dial.SetValue(st.get_bool(SEC_NAVIGATION, "PhoneticInDial", True))

    # --- Dial ---
    panel.chk_dial_chars.SetValue(st.get_bool(SEC_DIAL, "DialCharacters", True))
    panel.chk_dial_words.SetValue(st.get_bool(SEC_DIAL, "DialWords", True))
    panel.chk_dial_buttons.SetValue(st.get_bool(SEC_DIAL, "DialButtons", True))
    panel.chk_dial_headings.SetValue(st.get_bool(SEC_DIAL, "DialHeadings", True))
    panel.chk_dial_volume.SetValue(st.get_bool(SEC_DIAL, "DialVolume", True))
    panel.chk_dial_speed.SetValue(st.get_bool(SEC_DIAL, "DialSpeed", True))
    panel.chk_dial_voice.SetValue(st.get_bool(SEC_DIAL, "DialVoice", True))
    panel.chk_dial_synth.SetValue(st.get_bool(SEC_DIAL, "DialSynthesizer", True))
    panel.chk_dial_places.SetValue(st.get_bool(SEC_DIAL, "DialImportantPlaces", True))

    # --- Text editing ---
    panel.chk_phonetic.SetValue(st.phonetic_letters)
    panel.cmb_echo.SetSelection(
        _enum_index(list(KeyboardEchoSetting.ALL), st.keyboard_echo, 3))
    panel.chk_text_bounds.SetValue(st.announce_text_bounds)


def save_panel(panel):
    """Write every control back into the settings store and apply live."""
    if not STORE_AVAILABLE:
        return
    st = get_settings()

    # --- Speech: nothing to save (inherited from Titan TTS) ---

    # --- General ---
    st.enabled = panel.chk_enabled.GetValue()
    st.mute_outside_tce = panel.chk_mute.GetValue()
    st.startup_announcement = AnnouncementMode.ALL[
        max(0, panel.cmb_startup.GetSelection())]
    st.tce_entry_sound = panel.chk_entry_sound.GetValue()
    st.modifier = ScreenReaderModifier.ALL[
        max(0, panel.cmb_modifier.GetSelection())]
    st.welcome_message = panel.txt_welcome.GetValue()
    st.speak_hints = panel.chk_speak_hints.GetValue()
    st.virtual_screen = panel.chk_virtual_screen.GetValue()

    # --- Verbosity ---
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

    # --- Navigation ---
    st.set_bool(SEC_NAVIGATION, "AdvancedNavigation", panel.chk_adv_nav.GetValue())
    st.set_bool(SEC_NAVIGATION, "AnnounceControlTypesNavigation",
                panel.chk_nav_types.GetValue())
    st.set_bool(SEC_NAVIGATION, "AnnounceHierarchyLevel", panel.chk_hierarchy.GetValue())
    st.set(SEC_NAVIGATION, "WindowBoundsMode",
           AnnouncementMode.ALL[max(0, panel.cmb_window_bounds.GetSelection())])
    st.set_bool(SEC_NAVIGATION, "PhoneticInDial", panel.chk_phonetic_dial.GetValue())

    # --- Dial ---
    st.set_bool(SEC_DIAL, "DialCharacters", panel.chk_dial_chars.GetValue())
    st.set_bool(SEC_DIAL, "DialWords", panel.chk_dial_words.GetValue())
    st.set_bool(SEC_DIAL, "DialButtons", panel.chk_dial_buttons.GetValue())
    st.set_bool(SEC_DIAL, "DialHeadings", panel.chk_dial_headings.GetValue())
    st.set_bool(SEC_DIAL, "DialVolume", panel.chk_dial_volume.GetValue())
    st.set_bool(SEC_DIAL, "DialSpeed", panel.chk_dial_speed.GetValue())
    st.set_bool(SEC_DIAL, "DialVoice", panel.chk_dial_voice.GetValue())
    st.set_bool(SEC_DIAL, "DialSynthesizer", panel.chk_dial_synth.GetValue())
    st.set_bool(SEC_DIAL, "DialImportantPlaces", panel.chk_dial_places.GetValue())

    # --- Text editing ---
    st.phonetic_letters = panel.chk_phonetic.GetValue()
    st.keyboard_echo = KeyboardEchoSetting.ALL[max(0, panel.cmb_echo.GetSelection())]
    st.announce_text_bounds = panel.chk_text_bounds.GetValue()

    st.save()
    _apply_live(st)
    print("[TitanAccess] settings saved")


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
def register(component_manager):
    """Register the Titan Access settings category with TCE.

    No-ops if wxPython is unavailable so importing this module never fails on a
    headless host.
    """
    if not WX_AVAILABLE:
        print("[TitanAccess] settings_panel: wx unavailable, skipping registration")
        return
    try:
        component_manager.register_settings_category(
            L("settings.categoryName"),
            build_panel,
            save_panel,
            load_panel,
        )
    except Exception as e:  # pragma: no cover
        print(f"[TitanAccess] settings category registration failed: {e}")
