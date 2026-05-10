"""Configuration wizard for first-time TCE setup.

Runs automatically on the very first launch of Titan (when no settings file
exists yet) and can be relaunched on demand with `python main.py
--relaunch-config` for testing.

The wizard walks the user through six stages:

  I.   Welcome
  II.  Language selection (changing the language restarts the wizard at
       stage III so the new language takes effect).
  III. Skin and sound theme.
  IV.  Invisible UI.
  V.   Titan-Net.
  VI.  Additional settings (SAPI registration, environment options).

All UI text is translated through the existing gettext infrastructure
(domain: settings) and all navigation sounds match the Settings window:

* core/FOCUS.ogg          on EVT_SET_FOCUS
* core/SELECT.ogg         on listbox/button activation
* ui/switch_category.ogg  when moving between wizard stages
* ui/dialog.ogg           when a wizard frame opens
* ui/dialogclose.ogg      when a wizard frame closes
* ui/X.ogg                when a checkbox is toggled on
* system/volume.ogg       while dragging the volume slider

Skins are honoured: `apply_skin_to_window` is invoked on every panel and
the next-button icon is fetched from the current skin's `forward_icon`.
"""

import os
import subprocess
import sys
import threading

import wx

from src.settings.settings import (
    SETTINGS_FILE_PATH,
    load_settings,
    save_settings,
)
from src.titan_core.sound import (
    initialize_sound,
    play_sound,
    set_sound_theme_volume,
    set_theme,
    resource_path,
)
from src.titan_core.translation import (
    LANGUAGE_NAMES,
    get_available_languages,
    get_language_display_name,
    set_language,
)
from src.titan_core.skin_manager import (
    apply_skin_to_window,
    get_current_skin,
)

# Accessible output for stage-title announcements. Screen readers do not
# automatically announce a frame's new title when SetTitle is called on a
# live window, so we speak the title explicitly on every stage transition.
try:
    import accessible_output3.outputs.auto as _ao3_auto
    _speaker = _ao3_auto.Auto()
except Exception as _e:
    print(f"[ConfigWizard] accessible_output3 unavailable: {_e}")
    _speaker = None

_ = set_language(load_settings().get('general', {}).get('language', 'pl'))


SFX_DIR = resource_path('sfx')
SKINS_DIR = resource_path('skins')

# Stage identifiers
STAGE_WELCOME = 0
STAGE_LANGUAGE = 1
STAGE_SKIN_SOUND = 2
STAGE_INVISIBLE_UI = 3
STAGE_TITAN_NET = 4
STAGE_ADDITIONAL = 5


def _reload_translations():
    """Reload the global translation function for this module."""
    global _
    _ = set_language(load_settings().get('general', {}).get('language', 'pl'))


def _list_sound_themes():
    if not os.path.isdir(SFX_DIR):
        return ['default']
    themes = [d for d in os.listdir(SFX_DIR)
              if os.path.isdir(os.path.join(SFX_DIR, d))]
    return themes or ['default']


def _list_skins():
    skins = [_("Default")]
    if os.path.isdir(SKINS_DIR):
        skins.extend(d for d in os.listdir(SKINS_DIR)
                     if os.path.isdir(os.path.join(SKINS_DIR, d)))
    return skins


def _format_titan_ui_key(key_string):
    """Convert internal key id (e.g. 'grave') into a human-readable label.

    Mirrors SettingsFrame._format_titan_ui_key so the wizard speaks the
    same names users will see again in the Settings window.
    """
    if not key_string:
        return _("Not set")
    parts = [p.strip() for p in key_string.split('+') if p.strip()]
    names = {
        'ctrl': _("Ctrl"),
        'shift': _("Shift"),
        'alt': _("Alt"),
        'win': _("Win"),
        'cmd': _("Cmd"),
        'grave': _("Accent"),
        'space': _("Space"),
        'tab': _("Tab"),
        'enter': _("Enter"),
        'escape': _("Escape"),
        'backspace': _("Backspace"),
        'delete': _("Delete"),
        'insert': _("Insert"),
        'home': _("Home"),
        'end': _("End"),
        'pageup': _("Page Up"),
        'pagedown': _("Page Down"),
        'up': _("Up"),
        'down': _("Down"),
        'left': _("Left"),
        'right': _("Right"),
    }
    out = []
    for p in parts:
        if p in names:
            out.append(names[p])
        elif p.startswith('f') and p[1:].isdigit():
            out.append(p.upper())
        else:
            out.append(p)
    return '+'.join(out)


class ConfigWizardFrame(wx.Frame):
    """Six-stage first-run configuration wizard."""

    WINDOW_SIZE = (640, 560)

    def __init__(self, start_stage=STAGE_WELCOME, on_finish=None):
        super().__init__(
            None,
            title=_("Welcome to Titan!"),
            size=self.WINDOW_SIZE,
            style=wx.DEFAULT_FRAME_STYLE & ~(wx.MAXIMIZE_BOX | wx.RESIZE_BORDER),
        )

        # Make sure the audio system is up so navigation sounds work even
        # when the wizard runs before main.py has called initialize_sound().
        try:
            initialize_sound()
        except Exception:
            pass

        self.on_finish = on_finish
        self.current_stage = start_stage

        # Persistent state across stages
        self.settings = load_settings()
        self.selected_language = self.settings.get('general', {}).get(
            'language', 'pl')
        self.titan_ui_key_value = self.settings.get('general', {}).get(
            'titan_ui_key', 'grave')

        # Slider debounce timer
        self._volume_timer = None

        self._build_ui()

        try:
            apply_skin_to_window(self)
        except Exception:
            pass

        # Open sound (matches the Settings dialog opening)
        play_sound('ui/dialog.ogg')

        self.Centre()
        self.Bind(wx.EVT_CLOSE, self._on_close_button)

        self._show_stage(self.current_stage, play_switch_sound=False)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        self.outer_panel = wx.Panel(self)
        self.outer_sizer = wx.BoxSizer(wx.VERTICAL)

        # Title (changes per stage)
        self.title_label = wx.StaticText(self.outer_panel, label="")
        title_font = self.title_label.GetFont()
        title_font.SetPointSize(title_font.GetPointSize() + 4)
        title_font.SetWeight(wx.FONTWEIGHT_BOLD)
        self.title_label.SetFont(title_font)
        self.outer_sizer.Add(self.title_label, 0, wx.ALL | wx.EXPAND, 12)

        # Stage container - one panel per stage, only one shown at a time
        self.stage_panel = wx.Panel(self.outer_panel)
        self.stage_sizer = wx.BoxSizer(wx.VERTICAL)
        self.stage_panel.SetSizer(self.stage_sizer)
        self.outer_sizer.Add(self.stage_panel, 1, wx.EXPAND | wx.ALL, 12)

        # Build all stage panels (kept hidden until shown)
        self.stage_panels = {
            STAGE_WELCOME: self._build_welcome_stage(),
            STAGE_LANGUAGE: self._build_language_stage(),
            STAGE_SKIN_SOUND: self._build_skin_sound_stage(),
            STAGE_INVISIBLE_UI: self._build_invisible_ui_stage(),
            STAGE_TITAN_NET: self._build_titan_net_stage(),
            STAGE_ADDITIONAL: self._build_additional_stage(),
        }
        for panel in self.stage_panels.values():
            self.stage_sizer.Add(panel, 1, wx.EXPAND)
            panel.Hide()

        # Bottom button row
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.back_button = wx.Button(self.outer_panel, label=_("Back"))
        self.back_button.Bind(wx.EVT_BUTTON, self._on_back)
        self.back_button.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        button_sizer.Add(self.back_button, 0, wx.RIGHT, 8)

        self.next_button = wx.Button(self.outer_panel, label=_("Next"))
        self.next_button.Bind(wx.EVT_BUTTON, self._on_next)
        self.next_button.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        # Try to set the next-button icon from the current skin (forward_icon)
        try:
            skin = get_current_skin()
            bmp = skin.get_icon('forward_icon', size=(16, 16))
            if bmp and bmp.IsOk():
                self.next_button.SetBitmap(bmp)
        except Exception:
            pass
        button_sizer.Add(self.next_button, 0, wx.RIGHT, 8)

        self.close_button = wx.Button(self.outer_panel, label=_("Close"))
        self.close_button.Bind(wx.EVT_BUTTON, self._on_close_button)
        self.close_button.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        # Optional close icon from skin
        try:
            skin = get_current_skin()
            bmp = skin.get_icon('close_icon', size=(16, 16))
            if bmp and bmp.IsOk():
                self.close_button.SetBitmap(bmp)
        except Exception:
            pass
        button_sizer.Add(self.close_button, 0)

        self.outer_sizer.Add(button_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 12)

        self.outer_panel.SetSizer(self.outer_sizer)

    def _make_intro_textctrl(self, parent, text, height=80):
        """Build a read-only multiline TextCtrl for stage intro text.

        wx.StaticText is not readable by NVDA/JAWS — using a multiline
        TE_READONLY TextCtrl gives users a focusable, navigable region they
        can read with arrow keys / browse mode.
        """
        ctrl = wx.TextCtrl(
            parent,
            value=text,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP
                  | wx.BORDER_NONE,
            size=(-1, height),
        )
        # Match panel background so it visually reads as a paragraph
        try:
            ctrl.SetBackgroundColour(parent.GetBackgroundColour())
        except Exception:
            pass
        ctrl.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        return ctrl

    # ---- Stage I: welcome ---------------------------------------------
    def _build_welcome_stage(self):
        panel = wx.Panel(self.stage_panel)
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.welcome_intro = self._make_intro_textctrl(
            panel,
            _(
                "This wizard will guide you through configuring TCE to your "
                "preferences. Press Next to continue, or Close to leave the "
                "wizard."
            ),
            height=120,
        )
        vbox.Add(self.welcome_intro, 1, wx.ALL | wx.EXPAND, 16)
        panel.SetSizer(vbox)
        return panel

    # ---- Stage II: language -------------------------------------------
    def _build_language_stage(self):
        panel = wx.Panel(self.stage_panel)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.language_intro_label = self._make_intro_textctrl(
            panel, "", height=80)
        vbox.Add(self.language_intro_label, 0, wx.ALL | wx.EXPAND, 10)

        list_label = wx.StaticText(panel, label=_("Available languages:"))
        vbox.Add(list_label, 0, wx.LEFT | wx.TOP, 10)

        self.language_listbox = wx.ListBox(panel)
        self.language_listbox.SetLabel(_("Available languages:"))
        self.language_listbox.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        self.language_listbox.Bind(wx.EVT_LISTBOX_DCLICK, self._on_select)
        self._language_codes = get_available_languages()
        for code in self._language_codes:
            self.language_listbox.Append(get_language_display_name(code))
        vbox.Add(self.language_listbox, 1, wx.EXPAND | wx.ALL, 10)

        panel.SetSizer(vbox)
        return panel

    # ---- Stage III: skin and sound theme ------------------------------
    def _build_skin_sound_stage(self):
        panel = wx.Panel(self.stage_panel)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.skin_intro = self._make_intro_textctrl(
            panel,
            _(
                "Titan supports skins and sound themes. Additional sound "
                "themes and skins can be downloaded from the application "
                "repository in titan-net or from other creators."
            ),
            height=70,
        )
        vbox.Add(self.skin_intro, 0, wx.ALL | wx.EXPAND, 10)

        skin_label = wx.StaticText(panel, label=_("Select interface skin:"))
        vbox.Add(skin_label, 0, wx.LEFT | wx.TOP, 10)
        self.skin_choice = wx.Choice(panel)
        self.skin_choice.SetLabel(_("Select interface skin:"))
        self.skin_choice.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        skins = _list_skins()
        self.skin_choice.AppendItems(skins)
        current_skin_name = self.settings.get('interface', {}).get(
            'skin', _("Default"))
        if self.skin_choice.FindString(current_skin_name) != wx.NOT_FOUND:
            self.skin_choice.SetStringSelection(current_skin_name)
        else:
            self.skin_choice.SetSelection(0)
        vbox.Add(self.skin_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        theme_label = wx.StaticText(panel, label=_("Select sound theme:"))
        vbox.Add(theme_label, 0, wx.LEFT | wx.TOP, 10)
        self.theme_choice = wx.Choice(panel)
        self.theme_choice.SetLabel(_("Select sound theme:"))
        self.theme_choice.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        self.theme_choice.Bind(wx.EVT_CHOICE, self._on_theme_changed)
        themes = _list_sound_themes()
        self.theme_choice.AppendItems(themes)
        current_theme = self.settings.get('sound', {}).get('theme', 'default')
        if self.theme_choice.FindString(current_theme) != wx.NOT_FOUND:
            self.theme_choice.SetStringSelection(current_theme)
        else:
            self.theme_choice.SetSelection(0)
        vbox.Add(self.theme_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        volume_label_text = _("Sound theme volume:")
        volume_label = wx.StaticText(panel, label=volume_label_text)
        vbox.Add(volume_label, 0, wx.LEFT | wx.TOP, 10)
        try:
            current_volume = int(self.settings.get('sound', {}).get(
                'theme_volume', '100'))
        except ValueError:
            current_volume = 100
        self.volume_slider = wx.Slider(
            panel, value=current_volume, minValue=0, maxValue=100,
            style=wx.SL_HORIZONTAL,
        )
        self.volume_slider.SetLabel(volume_label_text)
        self.volume_slider.Bind(wx.EVT_SLIDER, self._on_volume_changed)
        self.volume_slider.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        vbox.Add(self.volume_slider, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        panel.SetSizer(vbox)
        return panel

    # ---- Stage IV: invisible UI ---------------------------------------
    def _build_invisible_ui_stage(self):
        panel = wx.Panel(self.stage_panel)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.invisible_intro = self._make_intro_textctrl(
            panel,
            _(
                "Titan can also switch to an invisible interface so you do "
                "not have to keep a window open all the time. You can "
                "configure the invisible interface here."
            ),
            height=70,
        )
        vbox.Add(self.invisible_intro, 0, wx.ALL | wx.EXPAND, 10)

        self.titan_ui_key_btn = wx.Button(
            panel,
            label=_("Titan UI key: {}").format(
                _format_titan_ui_key(self.titan_ui_key_value)),
        )
        self.titan_ui_key_btn.Bind(wx.EVT_BUTTON, self._on_capture_titan_ui_key)
        self.titan_ui_key_btn.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        vbox.Add(self.titan_ui_key_btn, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        invisible = self.settings.get('invisible_interface', {})

        self.announce_index_cb = wx.CheckBox(
            panel, label=_("Announce item index"))
        self.announce_index_cb.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        self.announce_index_cb.Bind(wx.EVT_CHECKBOX, self._on_checkbox)
        self.announce_index_cb.SetValue(
            str(invisible.get('announce_index', 'True')).lower() in ('true', '1'))
        vbox.Add(self.announce_index_cb, 0, wx.LEFT | wx.TOP, 10)

        self.announce_widget_type_cb = wx.CheckBox(
            panel, label=_("Announce widget type"))
        self.announce_widget_type_cb.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        self.announce_widget_type_cb.Bind(wx.EVT_CHECKBOX, self._on_checkbox)
        self.announce_widget_type_cb.SetValue(
            str(invisible.get('announce_widget_type', 'True')).lower() in ('true', '1'))
        vbox.Add(self.announce_widget_type_cb, 0, wx.LEFT | wx.TOP, 10)

        self.announce_first_item_cb = wx.CheckBox(
            panel, label=_("Announce first item in category"))
        self.announce_first_item_cb.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        self.announce_first_item_cb.Bind(wx.EVT_CHECKBOX, self._on_checkbox)
        self.announce_first_item_cb.SetValue(
            str(invisible.get('announce_first_item', 'True')).lower() in ('true', '1'))
        vbox.Add(self.announce_first_item_cb, 0, wx.LEFT | wx.TOP, 10)

        panel.SetSizer(vbox)
        return panel

    # ---- Stage V: titan-net -------------------------------------------
    def _build_titan_net_stage(self):
        panel = wx.Panel(self.stage_panel)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.titannet_intro = self._make_intro_textctrl(
            panel,
            _(
                "Titan also includes the titan-net portal, which lets you "
                "communicate with other TCE users and download add-ons for "
                "TCE from a dedicated repository."
            ),
            height=70,
        )
        vbox.Add(self.titannet_intro, 0, wx.ALL | wx.EXPAND, 10)

        titan_net_settings = self.settings.get('titan_net', {})
        custom_server = bool(titan_net_settings.get('custom_server', '')
                             not in ('', 'False', 'false', '0'))
        # Heuristic: if no custom_server flag is stored, infer from a non
        # default host.
        if 'custom_server' not in titan_net_settings:
            custom_server = (titan_net_settings.get('server_host', '')
                             not in ('', 'titosofttitan.com'))

        self.custom_server_cb = wx.CheckBox(
            panel, label=_("I am using my own titan-net server"))
        self.custom_server_cb.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        self.custom_server_cb.Bind(wx.EVT_CHECKBOX, self._on_custom_server_toggle)
        self.custom_server_cb.SetValue(custom_server)
        vbox.Add(self.custom_server_cb, 0, wx.LEFT | wx.TOP, 10)

        # Server settings group (only enabled when custom server is checked)
        host_box = wx.BoxSizer(wx.HORIZONTAL)
        host_label = wx.StaticText(panel, label=_("Server host:"))
        host_box.Add(host_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.host_ctrl = wx.TextCtrl(
            panel, value=titan_net_settings.get('server_host', 'titosofttitan.com'))
        self.host_ctrl.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        host_box.Add(self.host_ctrl, 1, wx.EXPAND)
        vbox.Add(host_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        ws_box = wx.BoxSizer(wx.HORIZONTAL)
        ws_label = wx.StaticText(panel, label=_("WebSocket port:"))
        ws_box.Add(ws_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.ws_port_ctrl = wx.TextCtrl(
            panel, value=str(titan_net_settings.get('server_port', '8001')))
        self.ws_port_ctrl.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        ws_box.Add(self.ws_port_ctrl, 1, wx.EXPAND)
        vbox.Add(ws_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        http_box = wx.BoxSizer(wx.HORIZONTAL)
        http_label = wx.StaticText(panel, label=_("HTTP port:"))
        http_box.Add(http_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.http_port_ctrl = wx.TextCtrl(
            panel, value=str(titan_net_settings.get('http_port', '8000')))
        self.http_port_ctrl.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        http_box.Add(self.http_port_ctrl, 1, wx.EXPAND)
        vbox.Add(http_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self._custom_server_controls = (
            self.host_ctrl, self.ws_port_ctrl, self.http_port_ctrl)
        for ctrl in self._custom_server_controls:
            ctrl.Enable(custom_server)

        self.create_account_btn = wx.Button(
            panel, label=_("Create titan-net account"))
        self.create_account_btn.Bind(wx.EVT_BUTTON, self._on_create_account)
        self.create_account_btn.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        vbox.Add(self.create_account_btn, 0,
                 wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        panel.SetSizer(vbox)
        return panel

    # ---- Stage VI: additional settings --------------------------------
    def _build_additional_stage(self):
        panel = wx.Panel(self.stage_panel)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.additional_intro = self._make_intro_textctrl(
            panel,
            _(
                "On this step you can enable features that may affect the "
                "operating system."
            ),
            height=60,
        )
        vbox.Add(self.additional_intro, 0, wx.ALL | wx.EXPAND, 10)

        env_settings = self.settings.get('environment', {})

        self.register_sapi_cb = None
        if sys.platform == 'win32':
            self.register_sapi_cb = wx.CheckBox(
                panel, label=_("Register Titan TTS as SAPI5 voice"))
            self.register_sapi_cb.Bind(wx.EVT_SET_FOCUS, self._on_focus)
            self.register_sapi_cb.Bind(wx.EVT_CHECKBOX, self._on_checkbox)
            self.register_sapi_cb.SetValue(
                str(env_settings.get('register_titan_tts_sapi', 'False')).lower()
                in ('true', '1'))
            vbox.Add(self.register_sapi_cb, 0, wx.LEFT | wx.TOP, 10)

        # Copilot key remap (only on Windows when key detected)
        self.copilot_remap_cb = None
        self.copilot_key_choice = None
        if sys.platform == 'win32':
            try:
                from src.system.copilot_key import (
                    detect_copilot_key,
                    REPLACEMENT_KEYS,
                )
                if detect_copilot_key():
                    self.copilot_remap_cb = wx.CheckBox(
                        panel, label=_("Replace Copilot key"))
                    self.copilot_remap_cb.Bind(wx.EVT_SET_FOCUS, self._on_focus)
                    self.copilot_remap_cb.Bind(
                        wx.EVT_CHECKBOX, self._on_copilot_remap_toggle)
                    self.copilot_remap_cb.SetValue(
                        str(env_settings.get('copilot_remap', 'False')).lower()
                        in ('true', '1'))
                    vbox.Add(self.copilot_remap_cb, 0, wx.LEFT | wx.TOP, 10)

                    self.copilot_key_choice = wx.Choice(panel)
                    self.copilot_key_choice.SetLabel(_("Replacement key"))
                    self._copilot_replacement_keys = REPLACEMENT_KEYS
                    for _vk, name in REPLACEMENT_KEYS:
                        self.copilot_key_choice.Append(_(name))
                    try:
                        current_vk = int(env_settings.get(
                            'copilot_replacement_vk', REPLACEMENT_KEYS[0][0]))
                    except ValueError:
                        current_vk = REPLACEMENT_KEYS[0][0]
                    sel = next((i for i, (vk, _n) in enumerate(REPLACEMENT_KEYS)
                                if vk == current_vk), 0)
                    self.copilot_key_choice.SetSelection(sel)
                    self.copilot_key_choice.Bind(wx.EVT_SET_FOCUS, self._on_focus)
                    self.copilot_key_choice.Enable(self.copilot_remap_cb.GetValue())
                    vbox.Add(self.copilot_key_choice, 0,
                             wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
            except Exception as e:
                print(f"[ConfigWizard] Copilot key detection error: {e}")

        # The "Finish" button replaces "Next" only on this stage; we keep
        # the same button widget and just retitle it. Done in _show_stage.

        panel.SetSizer(vbox)
        return panel

    # ------------------------------------------------------------------
    # Stage navigation
    # ------------------------------------------------------------------
    def _show_stage(self, stage, play_switch_sound=True):
        # Hide all stages, show the requested one
        for st, panel in self.stage_panels.items():
            panel.Show(st == stage)

        self.current_stage = stage

        titles = {
            STAGE_WELCOME: _("Welcome to Titan!"),
            STAGE_LANGUAGE: _("Language selection"),
            STAGE_SKIN_SOUND: _("Skin and sound theme"),
            STAGE_INVISIBLE_UI: _("Invisible interface"),
            STAGE_TITAN_NET: _("Titan-net"),
            STAGE_ADDITIONAL: _("Additional settings"),
        }
        title = titles[stage]
        self.title_label.SetLabel(title)
        self.SetTitle(title)

        # Per-stage adjustments
        self.back_button.Enable(stage != STAGE_WELCOME)

        if stage == STAGE_LANGUAGE:
            self._refresh_language_intro()
            current_idx = (self._language_codes.index(self.selected_language)
                           if self.selected_language in self._language_codes
                           else 0)
            self.language_listbox.SetSelection(current_idx)

        if stage == STAGE_ADDITIONAL:
            self.next_button.SetLabel(_("Finish"))
        else:
            self.next_button.SetLabel(_("Next"))

        self.outer_panel.Layout()
        self.stage_panel.Layout()

        if play_switch_sound:
            play_sound('ui/switch_category.ogg')

        # Announce the stage title to the screen reader. SetTitle alone is
        # not enough — most screen readers ignore live title changes on the
        # currently focused frame.
        if _speaker is not None:
            try:
                _speaker.speak(title, interrupt=True)
            except TypeError:
                # Some accessible_output3 backends don't accept interrupt=
                try:
                    _speaker.speak(title)
                except Exception:
                    pass
            except Exception:
                pass

        # Focus the most relevant control on the new stage
        wx.CallAfter(self._focus_first_control, stage)

    def _focus_first_control(self, stage):
        # The intro TextCtrl is the first focused element on every stage so
        # screen reader users hear the stage explanation before reaching the
        # interactive controls.
        focus_targets = {
            STAGE_WELCOME: self.welcome_intro,
            STAGE_LANGUAGE: self.language_intro_label,
            STAGE_SKIN_SOUND: self.skin_intro,
            STAGE_INVISIBLE_UI: self.invisible_intro,
            STAGE_TITAN_NET: self.titannet_intro,
            STAGE_ADDITIONAL: self.additional_intro,
        }
        target = focus_targets.get(stage)
        if target is not None:
            try:
                target.SetFocus()
            except Exception:
                pass

    def _refresh_language_intro(self):
        current_lang = self.settings.get('general', {}).get('language', 'pl')
        display = LANGUAGE_NAMES.get(current_lang, current_lang)
        self.language_intro_label.SetValue(
            _("Titan is currently set to {language}. If this message is in "
              "the language you want to use TCE in, press Next.").format(
                  language=display))

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------
    def _on_back(self, event):
        if self.current_stage == STAGE_WELCOME:
            return
        play_sound('ui/switch_category.ogg')
        self._show_stage(self.current_stage - 1, play_switch_sound=False)

    def _on_next(self, event):
        # Save the data of the current stage before advancing
        if self.current_stage == STAGE_LANGUAGE:
            self._save_language_and_relaunch()
            return
        if self.current_stage == STAGE_SKIN_SOUND:
            self._save_skin_sound()
        elif self.current_stage == STAGE_INVISIBLE_UI:
            self._save_invisible_ui()
        elif self.current_stage == STAGE_TITAN_NET:
            self._save_titan_net()
        elif self.current_stage == STAGE_ADDITIONAL:
            self._save_additional()
            self._finish()
            return

        if self.current_stage < STAGE_ADDITIONAL:
            play_sound('ui/switch_category.ogg')
            self._show_stage(self.current_stage + 1, play_switch_sound=False)

    def _on_close_button(self, event):
        play_sound('ui/dialogclose.ogg')
        self.Hide()
        self.Destroy()
        # Quit the wx app the wizard owns so the program terminates after
        # the user closes the wizard. main.py treats that as "user did not
        # finish first run" and exits cleanly.
        if callable(self.on_finish):
            self.on_finish(False)
        else:
            try:
                wx.GetApp().ExitMainLoop()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Stage data persistence
    # ------------------------------------------------------------------
    def _save_language_and_relaunch(self):
        sel = self.language_listbox.GetSelection()
        if sel == wx.NOT_FOUND:
            sel = 0
        new_code = self._language_codes[sel]

        general = self.settings.setdefault('general', {})
        general['language'] = new_code
        save_settings(self.settings)

        # Set environment so the next set_language call picks the new lang
        os.environ['LANG'] = new_code
        os.environ['LANGUAGE'] = new_code
        try:
            _reload_translations()
        except Exception:
            pass

        play_sound('ui/dialogclose.ogg')
        self.Hide()
        self.Destroy()

        # Relaunch the program in --relaunch-config mode at stage III so
        # the new translation is loaded with a fresh interpreter.
        try:
            self._relaunch_at_skin_stage()
        except Exception as e:
            print(f"[ConfigWizard] Relaunch failed: {e}")
            # Fallback: run a fresh wizard in this process at stage III
            try:
                _reload_translations()
                wx.CallAfter(_run_inline_at_stage, STAGE_SKIN_SOUND,
                             self.on_finish)
            except Exception:
                pass

    def _relaunch_at_skin_stage(self):
        # Quit current wx loop so the new process can take over cleanly
        try:
            app = wx.GetApp()
            if app is not None:
                wx.CallAfter(app.ExitMainLoop)
        except Exception:
            pass

        if getattr(sys, 'frozen', False):
            # Frozen executable
            args = [sys.executable, '--relaunch-config',
                    '--config-stage', 'skin']
        else:
            # Source mode: re-run main.py with the same interpreter
            project_root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            main_py = os.path.join(project_root, 'main.py')
            args = [sys.executable, main_py, '--relaunch-config',
                    '--config-stage', 'skin']
        try:
            subprocess.Popen(args, cwd=os.path.dirname(args[0])
                             if os.path.dirname(args[0]) else None)
        except Exception as e:
            print(f"[ConfigWizard] Could not spawn replacement process: {e}")

    def _save_skin_sound(self):
        skin_name = self.skin_choice.GetStringSelection() or _("Default")
        theme_name = self.theme_choice.GetStringSelection() or 'default'
        try:
            volume = int(self.volume_slider.GetValue())
        except ValueError:
            volume = 100

        interface = self.settings.setdefault('interface', {})
        interface['skin'] = skin_name

        sound = self.settings.setdefault('sound', {})
        sound['theme'] = theme_name
        sound['theme_volume'] = str(volume)

        save_settings(self.settings)
        try:
            set_theme(theme_name)
            set_sound_theme_volume(volume)
        except Exception:
            pass

    def _save_invisible_ui(self):
        invisible = self.settings.setdefault('invisible_interface', {})
        invisible['announce_index'] = str(self.announce_index_cb.GetValue())
        invisible['announce_widget_type'] = str(
            self.announce_widget_type_cb.GetValue())
        invisible['announce_first_item'] = str(
            self.announce_first_item_cb.GetValue())

        general = self.settings.setdefault('general', {})
        general['titan_ui_key'] = self.titan_ui_key_value or 'grave'

        save_settings(self.settings)

    def _save_titan_net(self):
        custom = self.custom_server_cb.GetValue()
        host = (self.host_ctrl.GetValue().strip()
                if custom else 'titosofttitan.com')
        ws_port = (self.ws_port_ctrl.GetValue().strip()
                   if custom else '8001') or '8001'
        http_port = (self.http_port_ctrl.GetValue().strip()
                     if custom else '8000') or '8000'

        titan_net = self.settings.setdefault('titan_net', {})
        titan_net['custom_server'] = str(custom)
        titan_net['server_host'] = host
        titan_net['server_port'] = str(ws_port)
        titan_net['http_port'] = str(http_port)

        save_settings(self.settings)

    def _save_additional(self):
        env = self.settings.setdefault('environment', {})

        sapi_new = None
        sapi_old = str(env.get('register_titan_tts_sapi', 'False')).lower() in (
            'true', '1')
        if self.register_sapi_cb is not None:
            sapi_new = self.register_sapi_cb.GetValue()
            env['register_titan_tts_sapi'] = str(sapi_new)

        if self.copilot_remap_cb is not None:
            env['copilot_remap'] = str(self.copilot_remap_cb.GetValue())
            if self.copilot_key_choice is not None:
                idx = self.copilot_key_choice.GetSelection()
                if 0 <= idx < len(self._copilot_replacement_keys):
                    env['copilot_replacement_vk'] = str(
                        self._copilot_replacement_keys[idx][0])

        # Mark wizard as completed so we never run it again automatically
        general = self.settings.setdefault('general', {})
        general['config_wizard_done'] = 'True'

        save_settings(self.settings)

        # Apply SAPI registration immediately if it changed
        if (sapi_new is not None
                and sapi_new != sapi_old
                and sys.platform == 'win32'):
            try:
                from src.tts.sapi_registration import apply_sapi_registration
                apply_sapi_registration(sapi_new, interactive=True)
                try:
                    from src.tts import sapi_pipe_server
                    if sapi_new:
                        sapi_pipe_server.start()
                    else:
                        sapi_pipe_server.stop()
                except Exception as e:
                    print(f"[ConfigWizard] SAPI pipe toggle failed: {e}")
            except Exception as e:
                print(f"[ConfigWizard] SAPI registration apply failed: {e}")

    # ------------------------------------------------------------------
    # Misc handlers
    # ------------------------------------------------------------------
    def _on_focus(self, event):
        play_sound('core/FOCUS.ogg')
        event.Skip()

    def _on_select(self, event):
        play_sound('core/SELECT.ogg')
        event.Skip()

    def _on_checkbox(self, event):
        if event.IsChecked():
            play_sound('ui/X.ogg')
        else:
            play_sound('core/FOCUS.ogg')
        event.Skip()

    def _on_theme_changed(self, event):
        theme = self.theme_choice.GetStringSelection()
        try:
            set_theme(theme)
            initialize_sound()
        except Exception:
            pass
        event.Skip()

    def _on_volume_changed(self, event):
        try:
            volume = int(self.volume_slider.GetValue())
            set_sound_theme_volume(volume)
        except Exception:
            pass

        if self._volume_timer:
            self._volume_timer.cancel()
        self._volume_timer = threading.Timer(
            0.1, lambda: play_sound('system/volume.ogg'))
        self._volume_timer.start()
        event.Skip()

    def _on_custom_server_toggle(self, event):
        enabled = self.custom_server_cb.GetValue()
        for ctrl in self._custom_server_controls:
            ctrl.Enable(enabled)
        if event.IsChecked():
            play_sound('ui/X.ogg')
        else:
            play_sound('core/FOCUS.ogg')
        event.Skip()

    def _on_copilot_remap_toggle(self, event):
        if self.copilot_key_choice is not None:
            self.copilot_key_choice.Enable(self.copilot_remap_cb.GetValue())
        if event.IsChecked():
            play_sound('ui/X.ogg')
        else:
            play_sound('core/FOCUS.ogg')
        event.Skip()

    def _on_capture_titan_ui_key(self, event):
        # Reuse the Settings KeyCaptureDialog.
        try:
            from src.ui.settingsgui import KeyCaptureDialog
        except Exception as e:
            print(f"[ConfigWizard] Could not import KeyCaptureDialog: {e}")
            return
        dlg = KeyCaptureDialog(
            self, current_label=_format_titan_ui_key(self.titan_ui_key_value))
        try:
            apply_skin_to_window(dlg)
        except Exception:
            pass
        if dlg.ShowModal() == wx.ID_OK and dlg.captured_key:
            self.titan_ui_key_value = dlg.captured_key
            self.titan_ui_key_btn.SetLabel(
                _("Titan UI key: {}").format(
                    _format_titan_ui_key(self.titan_ui_key_value)))
            play_sound('ui/X.ogg')
        dlg.Destroy()

    def _on_create_account(self, event):
        # Save current titan-net settings before launching the dialog so the
        # client that comes up uses what the user just typed in.
        self._save_titan_net()
        try:
            from src.network.titan_net import TitanNetClient
            from src.network.titan_net_gui import CreateAccountDialog
        except Exception as e:
            print(f"[ConfigWizard] Could not import titan-net modules: {e}")
            wx.MessageBox(
                _("Titan-net is not available."),
                _("Error"), wx.OK | wx.ICON_ERROR, self)
            return

        host = (self.host_ctrl.GetValue().strip()
                if self.custom_server_cb.GetValue() else 'titosofttitan.com')
        try:
            ws_port = int((self.ws_port_ctrl.GetValue().strip()
                           if self.custom_server_cb.GetValue() else '8001')
                          or '8001')
            http_port = int((self.http_port_ctrl.GetValue().strip()
                             if self.custom_server_cb.GetValue() else '8000')
                            or '8000')
        except ValueError:
            ws_port, http_port = 8001, 8000

        client = TitanNetClient(
            server_host=host, server_port=ws_port, http_port=http_port)

        dlg = CreateAccountDialog(self, client)
        try:
            apply_skin_to_window(dlg)
        except Exception:
            pass
        dlg.ShowModal()
        dlg.Destroy()

    # ------------------------------------------------------------------
    # Finish
    # ------------------------------------------------------------------
    def _finish(self):
        # Show "congratulations" message before closing
        congrats = wx.MessageDialog(
            self,
            _("The configuration wizard is complete. You can now use Titan "
              "without restrictions."),
            _("Congratulations!"),
            wx.OK | wx.ICON_INFORMATION,
        )
        try:
            apply_skin_to_window(congrats)
        except Exception:
            pass
        congrats.ShowModal()
        congrats.Destroy()

        play_sound('ui/dialogclose.ogg')
        self.Hide()
        self.Destroy()
        if callable(self.on_finish):
            self.on_finish(True)
        else:
            try:
                wx.GetApp().ExitMainLoop()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

_STAGE_NAMES = {
    'welcome': STAGE_WELCOME,
    'language': STAGE_LANGUAGE,
    'skin': STAGE_SKIN_SOUND,
    'invisible': STAGE_INVISIBLE_UI,
    'titannet': STAGE_TITAN_NET,
    'additional': STAGE_ADDITIONAL,
}


def stage_id_from_name(name):
    """Translate a CLI stage name like 'skin' to the integer stage id."""
    return _STAGE_NAMES.get(name, STAGE_WELCOME)


def is_first_run():
    """Return True if the wizard should be shown automatically.

    The wizard runs only when the settings file does not exist yet (i.e.
    the very first launch of Titan). Existing installations - where the
    settings file is already there - are treated as already configured
    even if `general.config_wizard_done` was never written, because they
    pre-date the wizard.
    """
    return not os.path.exists(SETTINGS_FILE_PATH)


def run_wizard(start_stage=STAGE_WELCOME):
    """Run the wizard with its own wx.App.

    Returns True if the user completed the wizard, False if they closed it
    early.
    """
    completed = {'value': False}

    def on_finish(ok):
        completed['value'] = bool(ok)
        try:
            wx.GetApp().ExitMainLoop()
        except Exception:
            pass

    existing = wx.GetApp()
    if existing is None:
        app = wx.App(False)
    else:
        app = existing

    frame = ConfigWizardFrame(start_stage=start_stage, on_finish=on_finish)
    frame.Show()
    app.MainLoop()
    return completed['value']


def _run_inline_at_stage(stage, on_finish):
    """Spawn a new wizard frame in the running wx app (used as a fallback
    when the language-change relaunch can not start a new process)."""
    frame = ConfigWizardFrame(start_stage=stage, on_finish=on_finish)
    frame.Show()
