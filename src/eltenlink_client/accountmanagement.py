"""
EltenLink Account Management - Separate dialog for managing Elten account.
Based on Ruby Elten Scene_Account and related scenes.
"""

import wx
import threading
import accessible_output3.outputs.auto
from src.titan_core.translation import set_language
from src.settings.settings import get_setting
from src.titan_core.sound import play_sound

try:
    from src.titan_core.skin_manager import apply_skin_to_window
except ImportError:
    apply_skin_to_window = None

try:
    from src.titan_core.stereo_speech import speak_stereo, get_stereo_speech
    STEREO_SPEECH_AVAILABLE = True
except ImportError:
    STEREO_SPEECH_AVAILABLE = False

_ = set_language(get_setting('language', 'pl'))
speaker = accessible_output3.outputs.auto.Auto()


def speak_am(text, position=0.0, pitch_offset=0, interrupt=True):
    """Speak text using stereo speech."""
    if not text:
        return
    try:
        stereo_enabled = get_setting('stereo_speech', 'False', section='invisible_interface').lower() == 'true'
        if stereo_enabled and STEREO_SPEECH_AVAILABLE:
            def do_speak():
                try:
                    if interrupt:
                        try:
                            ss = get_stereo_speech()
                            if ss:
                                ss.stop()
                        except Exception:
                            pass
                    speak_stereo(text, position=position, pitch_offset=pitch_offset, async_mode=True)
                except Exception:
                    speaker.output(text)
            threading.Thread(target=do_speak, daemon=True).start()
        else:
            def do_speak():
                try:
                    if interrupt and hasattr(speaker, 'stop'):
                        speaker.stop()
                    speaker.output(text)
                except Exception:
                    pass
            threading.Thread(target=do_speak, daemon=True).start()
    except Exception:
        try:
            speaker.output(text)
        except Exception:
            pass


def _bind_sounds_to_panel(panel):
    """Bind focus and checkbox sounds to all interactive controls in a panel, like settingsgui.py."""
    for child in panel.GetChildren():
        if isinstance(child, (wx.TextCtrl, wx.Button, wx.ListBox, wx.Choice, wx.Slider)):
            child.Bind(wx.EVT_SET_FOCUS, _on_focus)
        elif isinstance(child, wx.CheckBox):
            child.Bind(wx.EVT_SET_FOCUS, _on_focus)
            child.Bind(wx.EVT_CHECKBOX, _on_checkbox)
        elif isinstance(child, wx.ScrolledWindow):
            _bind_sounds_to_panel(child)


def _on_focus(event):
    """Play focus sound on any control, like settingsgui.py OnFocus."""
    play_sound('core/FOCUS.ogg')
    event.Skip()


def _on_checkbox(event):
    """Play checkbox sound, like settingsgui.py OnCheckBox."""
    if event.IsChecked():
        play_sound('ui/X.ogg')
    else:
        play_sound('core/FOCUS.ogg')
    event.Skip()


def speak_notification(text, notification_type='info'):
    """Speak notification with position and pitch."""
    if not text:
        return
    settings_map = {
        'error': (0.7, 5, 'core/error.ogg'),
        'warning': (0.4, 3, 'core/error.ogg'),
        'success': (0.0, 0, 'titannet/titannet_success.ogg'),
        'info': (-0.3, -2, 'ui/notify.ogg'),
    }
    pos, pitch, sound = settings_map.get(notification_type, settings_map['info'])
    try:
        play_sound(sound)
    except Exception:
        pass
    speak_am(text, position=pos, pitch_offset=pitch)


class AccountManagementDialog(wx.Dialog):
    """Full account management dialog - mirrors Ruby Scene_Account."""

    def __init__(self, parent, client):
        super().__init__(parent, title=_("Manage my account"), size=(600, 500),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.client = client
        self.config = {}
        self.config_loaded = False

        self._build_ui()
        self._load_config()

        if apply_skin_to_window:
            try:
                apply_skin_to_window(self)
            except Exception:
                pass

    def _build_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Category list
        self.category_label = wx.StaticText(panel, label=_("Category:"))
        main_sizer.Add(self.category_label, flag=wx.LEFT | wx.TOP, border=10)

        self.category_list = wx.ListBox(panel)
        categories = [
            _("Profile"),
            _("Visiting card"),
            _("Privacy"),
            _("Status and signature"),
            _("What's new notifications"),
            _("Account security"),
            _("Others"),
        ]
        for cat in categories:
            self.category_list.Append(cat)
        main_sizer.Add(self.category_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        # Buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.open_btn = wx.Button(panel, label=_("Open"))
        self.close_btn = wx.Button(panel, wx.ID_CANCEL, _("Close"))
        btn_sizer.Add(self.open_btn, flag=wx.RIGHT, border=10)
        btn_sizer.Add(self.close_btn)
        main_sizer.Add(btn_sizer, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=10)

        panel.SetSizer(main_sizer)

        self.category_list.SetSelection(0)
        self.category_list.SetFocus()

        # Sound bindings (like settingsgui.py)
        self.category_list.Bind(wx.EVT_SET_FOCUS, _on_focus)
        self.open_btn.Bind(wx.EVT_SET_FOCUS, _on_focus)
        self.close_btn.Bind(wx.EVT_SET_FOCUS, _on_focus)

        # Bindings
        self.open_btn.Bind(wx.EVT_BUTTON, self.OnOpen)
        self.category_list.Bind(wx.EVT_LISTBOX_DCLICK, self.OnOpen)
        self.category_list.Bind(wx.EVT_KEY_DOWN, self.OnKeyDown)

    def OnKeyDown(self, event):
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_RETURN or keycode == wx.WXK_NUMPAD_ENTER:
            self.OnOpen(None)
        elif keycode == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
        else:
            event.Skip()

    def _load_config(self):
        """Load account config in background."""
        def do_load():
            try:
                config = self.client.get_account_config()
                wx.CallAfter(self._on_config_loaded, config)
            except Exception:
                wx.CallAfter(self._on_config_loaded, {})
        threading.Thread(target=do_load, daemon=True).start()

    def _on_config_loaded(self, config):
        self.config = config or {}
        self.config_loaded = True

    def _save_config(self):
        """Save config to server."""
        config = dict(self.config)

        def do_save():
            try:
                result = self.client.save_account_config(config)
                if result:
                    wx.CallAfter(speak_notification, _("Settings saved"), 'success')
                else:
                    wx.CallAfter(speak_notification, _("Failed to save settings"), 'error')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_save, daemon=True).start()

    def OnOpen(self, event):
        sel = self.category_list.GetSelection()
        if sel == wx.NOT_FOUND:
            return

        play_sound('ui/switch_category.ogg')
        selected = self.category_list.GetString(sel)

        if not self.config_loaded:
            speak_notification(_("Loading settings, please wait..."), 'info')
            return

        if selected == _("Profile"):
            self._open_profile()
        elif selected == _("Visiting card"):
            self._open_visitingcard()
        elif selected == _("Privacy"):
            self._open_privacy()
        elif selected == _("Status and signature"):
            self._open_status()
        elif selected == _("What's new notifications"):
            self._open_whatsnew()
        elif selected == _("Account security"):
            self._open_security()
        elif selected == _("Others"):
            self._open_others()

    # ---- Profile ----

    def _open_profile(self):
        play_sound('ui/switch_category.ogg')
        dlg = wx.Dialog(self, title=_("Profile"), size=(400, 420))
        panel = wx.Panel(dlg)
        vbox = wx.BoxSizer(wx.VERTICAL)

        vbox.Add(wx.StaticText(panel, label=_("Full name:")), flag=wx.LEFT | wx.TOP, border=10)
        name_input = wx.TextCtrl(panel, value=self.config.get('fullname', ''))
        vbox.Add(name_input, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        vbox.Add(wx.StaticText(panel, label=_("Gender:")), flag=wx.LEFT | wx.TOP, border=10)
        gender_choice = wx.Choice(panel, choices=[_("Female"), _("Male")])
        try:
            gender_choice.SetSelection(int(self.config.get('gender', 0)))
        except (ValueError, TypeError):
            gender_choice.SetSelection(0)
        vbox.Add(gender_choice, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        vbox.Add(wx.StaticText(panel, label=_("Birth year:")), flag=wx.LEFT | wx.TOP, border=10)
        years = [_("Don't specify")] + [str(y) for y in range(1900, 2026)]
        year_choice = wx.Choice(panel, choices=years)
        try:
            cur_year = int(self.config.get('birthdateyear', 0))
            year_choice.SetSelection(years.index(str(cur_year)) if cur_year > 0 and str(cur_year) in years else 0)
        except (ValueError, TypeError):
            year_choice.SetSelection(0)
        vbox.Add(year_choice, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        vbox.Add(wx.StaticText(panel, label=_("Birth month:")), flag=wx.LEFT | wx.TOP, border=10)
        months = [_("January"), _("February"), _("March"), _("April"), _("May"), _("June"),
                  _("July"), _("August"), _("September"), _("October"), _("November"), _("December")]
        month_choice = wx.Choice(panel, choices=months)
        try:
            cur_month = int(self.config.get('birthdatemonth', 1))
            month_choice.SetSelection(max(0, min(11, cur_month - 1)))
        except (ValueError, TypeError):
            month_choice.SetSelection(0)
        vbox.Add(month_choice, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        vbox.Add(wx.StaticText(panel, label=_("Birth day:")), flag=wx.LEFT | wx.TOP, border=10)
        days = [str(d) for d in range(1, 32)]
        day_choice = wx.Choice(panel, choices=days)
        try:
            cur_day = int(self.config.get('birthdateday', 1))
            day_choice.SetSelection(max(0, min(30, cur_day - 1)))
        except (ValueError, TypeError):
            day_choice.SetSelection(0)
        vbox.Add(day_choice, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(panel, wx.ID_OK, _("Save"))
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        btn_box.Add(save_btn, flag=wx.RIGHT, border=10)
        btn_box.Add(cancel_btn)
        vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, border=15)

        panel.SetSizer(vbox)
        _bind_sounds_to_panel(panel)
        if apply_skin_to_window:
            try:
                apply_skin_to_window(dlg)
            except Exception:
                pass

        if dlg.ShowModal() == wx.ID_OK:
            self.config['fullname'] = name_input.GetValue()
            self.config['gender'] = str(gender_choice.GetSelection())
            yr_sel = year_choice.GetSelection()
            self.config['birthdateyear'] = str(0 if yr_sel == 0 else 1900 + yr_sel - 1)
            self.config['birthdatemonth'] = str(month_choice.GetSelection() + 1)
            self.config['birthdateday'] = str(day_choice.GetSelection() + 1)
            self._save_config()
        dlg.Destroy()

    # ---- Visiting Card ----

    def _open_visitingcard(self):
        play_sound('ui/switch_category.ogg')
        dlg = wx.Dialog(self, title=_("Visiting card"), size=(400, 300))
        panel = wx.Panel(dlg)
        vbox = wx.BoxSizer(wx.VERTICAL)

        vbox.Add(wx.StaticText(panel, label=_("Visiting card:")), flag=wx.LEFT | wx.TOP, border=10)
        card_input = wx.TextCtrl(panel, value=self.config.get('visitingcard', ''), style=wx.TE_MULTILINE)
        vbox.Add(card_input, proportion=1, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(panel, wx.ID_OK, _("Save"))
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        btn_box.Add(save_btn, flag=wx.RIGHT, border=10)
        btn_box.Add(cancel_btn)
        vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, border=15)

        panel.SetSizer(vbox)
        _bind_sounds_to_panel(panel)
        if apply_skin_to_window:
            try:
                apply_skin_to_window(dlg)
            except Exception:
                pass

        if dlg.ShowModal() == wx.ID_OK:
            self.config['visitingcard'] = card_input.GetValue()
            self._save_config()
        dlg.Destroy()

    # ---- Privacy ----

    def _open_privacy(self):
        play_sound('ui/switch_category.ogg')
        dlg = wx.Dialog(self, title=_("Privacy"), size=(500, 350))
        panel = wx.Panel(dlg)
        vbox = wx.BoxSizer(wx.VERTICAL)

        hide_cb = wx.CheckBox(panel, label=_("Hide my profile for strangers"))
        hide_cb.SetValue(int(self.config.get('publicprofile', 0)) != 0)
        vbox.Add(hide_cb, flag=wx.LEFT | wx.TOP, border=10)

        prevent_cb = wx.CheckBox(panel, label=_("Prevent banned users from writing me private messages"))
        prevent_cb.SetValue(int(self.config.get('preventbanned', 0)) != 0)
        vbox.Add(prevent_cb, flag=wx.LEFT | wx.TOP, border=10)

        vbox.Add(wx.StaticText(panel, label=_("Accept incoming voice calls:")), flag=wx.LEFT | wx.TOP, border=10)
        calls_choice = wx.Choice(panel, choices=[_("Never"), _("Only from my friends"), _("From all users")])
        try:
            calls_choice.SetSelection(min(2, int(self.config.get('calls', 0))))
        except (ValueError, TypeError):
            calls_choice.SetSelection(0)
        vbox.Add(calls_choice, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        vbox.AddSpacer(10)
        blacklist_btn = wx.Button(panel, label=_("Manage black list"))
        vbox.Add(blacklist_btn, flag=wx.LEFT, border=10)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(panel, wx.ID_OK, _("Save"))
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        btn_box.Add(save_btn, flag=wx.RIGHT, border=10)
        btn_box.Add(cancel_btn)
        vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, border=15)

        panel.SetSizer(vbox)
        _bind_sounds_to_panel(panel)
        if apply_skin_to_window:
            try:
                apply_skin_to_window(dlg)
            except Exception:
                pass

        blacklist_btn.Bind(wx.EVT_BUTTON, lambda e: self._open_blacklist(dlg))

        if dlg.ShowModal() == wx.ID_OK:
            self.config['publicprofile'] = str(1 if hide_cb.GetValue() else 0)
            self.config['preventbanned'] = str(1 if prevent_cb.GetValue() else 0)
            self.config['calls'] = str(calls_choice.GetSelection())
            self._save_config()
        dlg.Destroy()

    def _open_blacklist(self, parent):
        """Open blacklist management dialog."""
        play_sound('ui/switch_category.ogg')
        dlg = BlacklistDialog(parent, self.client)
        dlg.ShowModal()
        dlg.Destroy()

    # ---- Status and Signature ----

    def _open_status(self):
        play_sound('ui/switch_category.ogg')
        dlg = wx.Dialog(self, title=_("Status and signature"), size=(450, 350))
        panel = wx.Panel(dlg)
        vbox = wx.BoxSizer(wx.VERTICAL)

        vbox.Add(wx.StaticText(panel, label=_("Status displayed after your name on all lists of users:")),
                 flag=wx.LEFT | wx.TOP, border=10)
        status_input = wx.TextCtrl(panel, value=self.config.get('status', ''))
        vbox.Add(status_input, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        vbox.Add(wx.StaticText(panel, label=_("Signature placed below all your forum posts:")),
                 flag=wx.LEFT | wx.TOP, border=10)
        sig_input = wx.TextCtrl(panel, value=self.config.get('signature', ''))
        vbox.Add(sig_input, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        vbox.Add(wx.StaticText(panel, label=_("Greeting read after you log in to Elten:")),
                 flag=wx.LEFT | wx.TOP, border=10)
        greet_input = wx.TextCtrl(panel, value=self.config.get('greeting', ''))
        vbox.Add(greet_input, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(panel, wx.ID_OK, _("Save"))
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        btn_box.Add(save_btn, flag=wx.RIGHT, border=10)
        btn_box.Add(cancel_btn)
        vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, border=15)

        panel.SetSizer(vbox)
        _bind_sounds_to_panel(panel)
        if apply_skin_to_window:
            try:
                apply_skin_to_window(dlg)
            except Exception:
                pass

        if dlg.ShowModal() == wx.ID_OK:
            self.config['status'] = status_input.GetValue()
            self.config['signature'] = sig_input.GetValue()
            self.config['greeting'] = greet_input.GetValue()
            self._save_config()
        dlg.Destroy()

    # ---- What's New Notifications ----

    def _open_whatsnew(self):
        play_sound('ui/switch_category.ogg')
        dlg = wx.Dialog(self, title=_("What's new notifications"), size=(550, 500),
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        panel = wx.Panel(dlg)
        vbox = wx.BoxSizer(wx.VERTICAL)

        options = [_("Notice and show in what's new"), _("Notice only"), _("Ignore")]
        categories = [
            (_("New messages"), "wn_messages"),
            (_("New posts in followed threads"), "wn_followedthreads"),
            (_("New posts on the followed blogs"), "wn_followedblogs"),
            (_("New comments on your blog"), "wn_blogcomments"),
            (_("New threads on followed forums"), "wn_followedforums"),
            (_("New posts on followed forums"), "wn_followedforumsthreads"),
            (_("New friends"), "wn_friends"),
            (_("Friends' birthday"), "wn_birthday"),
            (_("Mentions"), "wn_mentions"),
            (_("Followed blog posts"), "wn_followedblogposts"),
            (_("Blog followers"), "wn_blogfollowers"),
            (_("Blog mentions"), "wn_blogmentions"),
            (_("Awaiting group invitations"), "wn_groupinvitations"),
        ]

        scroll = wx.ScrolledWindow(panel, style=wx.VSCROLL)
        scroll.SetScrollRate(0, 20)
        scroll_sizer = wx.BoxSizer(wx.VERTICAL)

        choices_list = []
        for label, key in categories:
            scroll_sizer.Add(wx.StaticText(scroll, label=label), flag=wx.LEFT | wx.TOP, border=5)
            choice = wx.Choice(scroll, choices=options)
            try:
                cur_val = int(self.config.get(key, 0))
            except (ValueError, TypeError):
                cur_val = 0
            choice.SetSelection(min(2, cur_val))
            scroll_sizer.Add(choice, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=5)
            choices_list.append((key, choice))

        scroll.SetSizer(scroll_sizer)
        vbox.Add(scroll, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(panel, wx.ID_OK, _("Save"))
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        btn_box.Add(save_btn, flag=wx.RIGHT, border=10)
        btn_box.Add(cancel_btn)
        vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, border=10)

        panel.SetSizer(vbox)
        _bind_sounds_to_panel(panel)
        if apply_skin_to_window:
            try:
                apply_skin_to_window(dlg)
            except Exception:
                pass

        if dlg.ShowModal() == wx.ID_OK:
            for key, choice in choices_list:
                self.config[key] = str(choice.GetSelection())
            self._save_config()
        dlg.Destroy()

    # ---- Account Security ----

    def _open_security(self):
        play_sound('ui/switch_category.ogg')
        dlg = wx.Dialog(self, title=_("Account security"), size=(450, 400))
        panel = wx.Panel(dlg)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.security_list = wx.ListBox(panel)
        items = [
            _("Change email"),
            _("Change password"),
            _("Manage Two-Factor Authentication"),
            _("Manage mail events-reporting"),
            _("Manage auto-login tokens"),
            _("Show last logins"),
        ]
        for item in items:
            self.security_list.Append(item)
        vbox.Add(self.security_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        open_btn = wx.Button(panel, label=_("Open"))
        close_btn = wx.Button(panel, wx.ID_CANCEL, _("Close"))
        btn_box.Add(open_btn, flag=wx.RIGHT, border=10)
        btn_box.Add(close_btn)
        vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=10)

        panel.SetSizer(vbox)
        _bind_sounds_to_panel(panel)
        if apply_skin_to_window:
            try:
                apply_skin_to_window(dlg)
            except Exception:
                pass

        self.security_list.SetSelection(0)
        self.security_list.SetFocus()

        def on_security_open(evt):
            sel = self.security_list.GetSelection()
            if sel == wx.NOT_FOUND:
                return
            play_sound('core/SELECT.ogg')
            text = self.security_list.GetString(sel)
            if text == _("Change email"):
                self._change_email(dlg)
            elif text == _("Change password"):
                self._change_password(dlg)
            elif text == _("Manage Two-Factor Authentication"):
                self._manage_2fa(dlg)
            elif text == _("Manage mail events-reporting"):
                self._manage_mail_events(dlg)
            elif text == _("Manage auto-login tokens"):
                self._manage_auto_logins(dlg)
            elif text == _("Show last logins"):
                self._show_last_logins(dlg)

        open_btn.Bind(wx.EVT_BUTTON, on_security_open)
        self.security_list.Bind(wx.EVT_LISTBOX_DCLICK, on_security_open)
        self.security_list.Bind(wx.EVT_KEY_DOWN, lambda e: on_security_open(e) if e.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) else e.Skip())

        dlg.ShowModal()
        dlg.Destroy()

    def _change_password(self, parent):
        play_sound('ui/switch_category.ogg')
        dlg = wx.Dialog(parent, title=_("Change password"), size=(350, 280))
        panel = wx.Panel(dlg)
        vbox = wx.BoxSizer(wx.VERTICAL)

        vbox.Add(wx.StaticText(panel, label=_("Current password:")), flag=wx.LEFT | wx.TOP, border=10)
        old_pass = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
        vbox.Add(old_pass, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        vbox.Add(wx.StaticText(panel, label=_("New password:")), flag=wx.LEFT | wx.TOP, border=10)
        new_pass = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
        vbox.Add(new_pass, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        vbox.Add(wx.StaticText(panel, label=_("Repeat new password:")), flag=wx.LEFT | wx.TOP, border=10)
        repeat_pass = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
        vbox.Add(repeat_pass, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        change_btn = wx.Button(panel, wx.ID_OK, _("Change"))
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        btn_box.Add(change_btn, flag=wx.RIGHT, border=10)
        btn_box.Add(cancel_btn)
        vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, border=15)

        panel.SetSizer(vbox)
        _bind_sounds_to_panel(panel)
        if apply_skin_to_window:
            try:
                apply_skin_to_window(dlg)
            except Exception:
                pass

        if dlg.ShowModal() == wx.ID_OK:
            old_val = old_pass.GetValue()
            new_val = new_pass.GetValue()
            repeat_val = repeat_pass.GetValue()

            if not old_val or not new_val or not repeat_val:
                speak_notification(_("Please fill all fields"), 'warning')
            elif new_val != repeat_val:
                speak_notification(_("New passwords don't match"), 'warning')
            elif len(new_val) < 6:
                speak_notification(_("Password must be at least 6 characters"), 'warning')
            else:
                def do_change():
                    try:
                        result = self.client.change_password(old_val, new_val)
                        if result['success']:
                            wx.CallAfter(speak_notification, _("Password changed successfully"), 'success')
                        else:
                            wx.CallAfter(speak_notification, result.get('message', _("Failed to change password")), 'error')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')
                threading.Thread(target=do_change, daemon=True).start()
        dlg.Destroy()

    def _change_email(self, parent):
        play_sound('ui/switch_category.ogg')
        dlg = wx.Dialog(parent, title=_("Change email"), size=(350, 220))
        panel = wx.Panel(dlg)
        vbox = wx.BoxSizer(wx.VERTICAL)

        vbox.Add(wx.StaticText(panel, label=_("New email:")), flag=wx.LEFT | wx.TOP, border=10)
        email_input = wx.TextCtrl(panel)
        vbox.Add(email_input, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        vbox.Add(wx.StaticText(panel, label=_("Current password:")), flag=wx.LEFT | wx.TOP, border=10)
        pass_input = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
        vbox.Add(pass_input, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        change_btn = wx.Button(panel, wx.ID_OK, _("Change"))
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        btn_box.Add(change_btn, flag=wx.RIGHT, border=10)
        btn_box.Add(cancel_btn)
        vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, border=15)

        panel.SetSizer(vbox)
        _bind_sounds_to_panel(panel)
        if apply_skin_to_window:
            try:
                apply_skin_to_window(dlg)
            except Exception:
                pass

        if dlg.ShowModal() == wx.ID_OK:
            email = email_input.GetValue().strip()
            password = pass_input.GetValue()

            if not email or not password:
                speak_notification(_("Please fill all fields"), 'warning')
            elif '@' not in email:
                speak_notification(_("Invalid email address"), 'warning')
            else:
                def do_change():
                    try:
                        result = self.client.change_email(email, password)
                        if result['success']:
                            wx.CallAfter(speak_notification, _("Email changed successfully"), 'success')
                        else:
                            wx.CallAfter(speak_notification, result.get('message', _("Failed to change email")), 'error')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')
                threading.Thread(target=do_change, daemon=True).start()
        dlg.Destroy()

    def _manage_2fa(self, parent):
        """Manage Two-Factor Authentication."""
        speak_notification(_("Checking Two-Factor Authentication status..."), 'info')

        def do_check():
            try:
                state = self.client.check_2fa_state()
                wx.CallAfter(self._show_2fa_dialog, parent, state)
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_check, daemon=True).start()

    def _show_2fa_dialog(self, parent, state):
        play_sound('ui/switch_category.ogg')
        is_enabled = state is not None and state != 0

        if is_enabled:
            # 2FA is enabled - offer to disable or generate backup codes
            dlg = wx.Dialog(parent, title=_("Two-Factor Authentication"), size=(400, 250))
            panel = wx.Panel(dlg)
            vbox = wx.BoxSizer(wx.VERTICAL)

            vbox.Add(wx.StaticText(panel, label=_("Two-Factor Authentication is enabled.")),
                     flag=wx.LEFT | wx.TOP, border=10)

            action_list = wx.ListBox(panel)
            action_list.Append(_("Disable Two-Factor Authentication"))
            action_list.Append(_("Generate backup codes"))
            vbox.Add(action_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

            btn_box = wx.BoxSizer(wx.HORIZONTAL)
            open_btn = wx.Button(panel, label=_("Open"))
            close_btn = wx.Button(panel, wx.ID_CANCEL, _("Close"))
            btn_box.Add(open_btn, flag=wx.RIGHT, border=10)
            btn_box.Add(close_btn)
            vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=10)

            panel.SetSizer(vbox)
            _bind_sounds_to_panel(panel)
            if apply_skin_to_window:
                try:
                    apply_skin_to_window(dlg)
                except Exception:
                    pass

            action_list.SetSelection(0)
            action_list.SetFocus()

            def on_action(evt):
                sel = action_list.GetSelection()
                if sel == 0:
                    self._disable_2fa(dlg)
                elif sel == 1:
                    self._generate_backup_codes(dlg)

            open_btn.Bind(wx.EVT_BUTTON, on_action)
            action_list.Bind(wx.EVT_LISTBOX_DCLICK, on_action)
            action_list.Bind(wx.EVT_KEY_DOWN, lambda e: on_action(e) if e.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) else e.Skip())

            dlg.ShowModal()
            dlg.Destroy()
        else:
            # 2FA is disabled - offer to enable
            dlg = wx.Dialog(parent, title=_("Enable Two-Factor Authentication"), size=(400, 280))
            panel = wx.Panel(dlg)
            vbox = wx.BoxSizer(wx.VERTICAL)

            vbox.Add(wx.StaticText(panel, label=_("Two-Factor Authentication is disabled.")),
                     flag=wx.LEFT | wx.TOP, border=10)
            vbox.Add(wx.StaticText(panel, label=_("Enter your phone number to enable (e.g. +48123456789):")),
                     flag=wx.LEFT | wx.TOP, border=10)
            phone_input = wx.TextCtrl(panel)
            vbox.Add(phone_input, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

            vbox.Add(wx.StaticText(panel, label=_("Current password:")), flag=wx.LEFT | wx.TOP, border=10)
            pass_input = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
            vbox.Add(pass_input, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

            btn_box = wx.BoxSizer(wx.HORIZONTAL)
            enable_btn = wx.Button(panel, wx.ID_OK, _("Enable"))
            cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
            btn_box.Add(enable_btn, flag=wx.RIGHT, border=10)
            btn_box.Add(cancel_btn)
            vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, border=15)

            panel.SetSizer(vbox)
            _bind_sounds_to_panel(panel)
            if apply_skin_to_window:
                try:
                    apply_skin_to_window(dlg)
                except Exception:
                    pass

            if dlg.ShowModal() == wx.ID_OK:
                phone = phone_input.GetValue().strip()
                password = pass_input.GetValue()
                if not phone or not password:
                    speak_notification(_("Please fill all fields"), 'warning')
                elif len(phone) < 11 or (not phone.startswith('+') and not phone.startswith('00')):
                    speak_notification(_("Invalid phone number. Must start with + or 00 and be at least 11 characters."), 'warning')
                else:
                    lang = get_setting('language', 'en')
                    def do_enable():
                        try:
                            result = self.client.enable_2fa(password, phone, lang)
                            if result['success']:
                                wx.CallAfter(speak_notification, result['message'], 'success')
                            else:
                                wx.CallAfter(speak_notification, result['message'], 'error')
                        except Exception as e:
                            wx.CallAfter(speak_notification, str(e), 'error')
                    threading.Thread(target=do_enable, daemon=True).start()
            dlg.Destroy()

    def _disable_2fa(self, parent):
        pwd = wx.GetPasswordFromUser(_("Enter your password to disable Two-Factor Authentication:"),
                                     _("Disable 2FA"), parent=parent)
        if not pwd:
            return

        def do_disable():
            try:
                result = self.client.disable_2fa(pwd)
                if result['success']:
                    wx.CallAfter(speak_notification, result['message'], 'success')
                else:
                    wx.CallAfter(speak_notification, result['message'], 'error')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_disable, daemon=True).start()

    def _generate_backup_codes(self, parent):
        pwd = wx.GetPasswordFromUser(_("Enter your password to generate backup codes:"),
                                     _("Backup Codes"), parent=parent)
        if not pwd:
            return

        def do_generate():
            try:
                codes = self.client.generate_backup_codes(pwd)
                if codes is None:
                    wx.CallAfter(speak_notification, _("Failed to generate backup codes"), 'error')
                else:
                    codes_text = "\n".join(codes)
                    wx.CallAfter(self._show_backup_codes, parent, codes_text)
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_generate, daemon=True).start()

    def _show_backup_codes(self, parent, codes_text):
        play_sound('ui/switch_category.ogg')
        dlg = wx.Dialog(parent, title=_("Backup Codes"), size=(350, 300))
        panel = wx.Panel(dlg)
        vbox = wx.BoxSizer(wx.VERTICAL)

        vbox.Add(wx.StaticText(panel, label=_("Save these backup codes in a safe place:")),
                 flag=wx.LEFT | wx.TOP, border=10)
        codes_display = wx.TextCtrl(panel, value=codes_text, style=wx.TE_MULTILINE | wx.TE_READONLY)
        vbox.Add(codes_display, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        close_btn = wx.Button(panel, wx.ID_OK, _("Close"))
        vbox.Add(close_btn, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=10)

        panel.SetSizer(vbox)
        _bind_sounds_to_panel(panel)
        if apply_skin_to_window:
            try:
                apply_skin_to_window(dlg)
            except Exception:
                pass

        speak_am(_("Backup codes generated. Save them in a safe place."))
        dlg.ShowModal()
        dlg.Destroy()

    def _manage_mail_events(self, parent):
        """Manage mail events reporting."""
        pwd = wx.GetPasswordFromUser(_("Enter your password:"), _("Mail Events"), parent=parent)
        if not pwd:
            return

        speak_notification(_("Checking mail events status..."), 'info')

        def do_check():
            try:
                status = self.client.check_mail_events(pwd)
                if status is None:
                    wx.CallAfter(speak_notification, _("Authentication error. Check your password."), 'error')
                else:
                    wx.CallAfter(self._show_mail_events_dialog, parent, pwd, status)
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_check, daemon=True).start()

    def _show_mail_events_dialog(self, parent, password, status):
        verified = status.get('verified', 0)
        enabled = status.get('enabled', 0)

        play_sound('ui/switch_category.ogg')

        if verified == 0:
            # Email not verified - offer to verify
            ret = wx.MessageBox(
                _("Mail events reporting requires email verification. Do you want to verify your email now?"),
                _("Mail Events"), wx.YES_NO | wx.ICON_QUESTION, parent)
            if ret == wx.YES:
                def do_verify():
                    try:
                        ok = self.client.send_mail_events_verification(password)
                        if ok:
                            wx.CallAfter(self._ask_verification_code, parent, password)
                        else:
                            wx.CallAfter(speak_notification, _("Failed to send verification code"), 'error')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')
                threading.Thread(target=do_verify, daemon=True).start()
        else:
            # Verified - show enable/disable option
            if enabled:
                msg = _("Mail events reporting is enabled.")
                action = _("Disable mail events reporting")
            else:
                msg = _("Mail events reporting is disabled.")
                action = _("Enable mail events reporting")

            dlg = wx.Dialog(parent, title=_("Mail Events"), size=(400, 200))
            panel = wx.Panel(dlg)
            vbox = wx.BoxSizer(wx.VERTICAL)

            vbox.Add(wx.StaticText(panel, label=msg), flag=wx.LEFT | wx.TOP, border=10)

            action_list = wx.ListBox(panel)
            action_list.Append(action)
            vbox.Add(action_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

            btn_box = wx.BoxSizer(wx.HORIZONTAL)
            open_btn = wx.Button(panel, label=_("Open"))
            close_btn = wx.Button(panel, wx.ID_CANCEL, _("Close"))
            btn_box.Add(open_btn, flag=wx.RIGHT, border=10)
            btn_box.Add(close_btn)
            vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=10)

            panel.SetSizer(vbox)
            _bind_sounds_to_panel(panel)
            if apply_skin_to_window:
                try:
                    apply_skin_to_window(dlg)
                except Exception:
                    pass

            action_list.SetSelection(0)
            action_list.SetFocus()

            def on_toggle(evt):
                new_enable = not enabled

                def do_toggle():
                    try:
                        ok = self.client.toggle_mail_events(password, new_enable)
                        if ok:
                            if new_enable:
                                wx.CallAfter(speak_notification, _("Mail events reporting enabled"), 'success')
                            else:
                                wx.CallAfter(speak_notification, _("Mail events reporting disabled"), 'success')
                        else:
                            wx.CallAfter(speak_notification, _("Failed to update mail events setting"), 'error')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')
                threading.Thread(target=do_toggle, daemon=True).start()
                dlg.EndModal(wx.ID_OK)

            open_btn.Bind(wx.EVT_BUTTON, on_toggle)
            action_list.Bind(wx.EVT_LISTBOX_DCLICK, on_toggle)

            dlg.ShowModal()
            dlg.Destroy()

    def _ask_verification_code(self, parent, password):
        code = wx.GetTextFromUser(
            _("The verification code has been sent to your email. Please enter it:"),
            _("Verify Email"), parent=parent)
        if not code:
            return

        def do_verify():
            try:
                ok = self.client.verify_mail_events_code(password, code)
                if ok:
                    wx.CallAfter(speak_notification, _("Email verified successfully"), 'success')
                else:
                    wx.CallAfter(speak_notification, _("Verification failed"), 'error')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_verify, daemon=True).start()

    def _manage_auto_logins(self, parent):
        """Manage auto-login tokens."""
        pwd = wx.GetPasswordFromUser(_("Enter your password:"), _("Auto-login Tokens"), parent=parent)
        if not pwd:
            return

        speak_notification(_("Loading auto-login tokens..."), 'info')

        def do_load():
            try:
                tokens = self.client.get_auto_logins(pwd)
                if tokens is None:
                    wx.CallAfter(speak_notification, _("Authentication error. Check your password."), 'error')
                else:
                    wx.CallAfter(self._show_auto_logins_dialog, parent, pwd, tokens)
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_load, daemon=True).start()

    def _show_auto_logins_dialog(self, parent, password, tokens):
        play_sound('ui/switch_category.ogg')
        dlg = wx.Dialog(parent, title=_("Auto-login Tokens"), size=(500, 350),
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        panel = wx.Panel(dlg)
        vbox = wx.BoxSizer(wx.VERTICAL)

        token_list = wx.ListBox(panel)
        if not tokens:
            token_list.Append(_("No auto-login tokens"))
        else:
            for t in reversed(tokens):
                token_list.Append(f"{t['generation']} - IP: {t['ip']} - {t['date']}")
        vbox.Add(token_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        logout_btn = wx.Button(panel, label=_("Log out all sessions"))
        close_btn = wx.Button(panel, wx.ID_CANCEL, _("Close"))
        btn_box.Add(logout_btn, flag=wx.RIGHT, border=10)
        btn_box.Add(close_btn)
        vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=10)

        panel.SetSizer(vbox)
        _bind_sounds_to_panel(panel)
        if apply_skin_to_window:
            try:
                apply_skin_to_window(dlg)
            except Exception:
                pass

        token_list.SetSelection(0)
        token_list.SetFocus()

        def on_logout(evt):
            ret = wx.MessageBox(
                _("Are you sure you want to remove all auto-login tokens and log out all sessions?"),
                _("Log out all sessions"), wx.YES_NO | wx.ICON_WARNING, dlg)
            if ret == wx.YES:
                def do_logout():
                    try:
                        ok = self.client.global_logout(password)
                        if ok:
                            wx.CallAfter(speak_notification, _("All sessions logged out"), 'success')
                        else:
                            wx.CallAfter(speak_notification, _("Failed to log out sessions"), 'error')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')
                threading.Thread(target=do_logout, daemon=True).start()
                dlg.EndModal(wx.ID_OK)

        logout_btn.Bind(wx.EVT_BUTTON, on_logout)

        dlg.ShowModal()
        dlg.Destroy()

    def _show_last_logins(self, parent):
        """Show last login history."""
        pwd = wx.GetPasswordFromUser(_("Enter your password:"), _("Last Logins"), parent=parent)
        if not pwd:
            return

        speak_notification(_("Loading login history..."), 'info')

        def do_load():
            try:
                logins = self.client.get_last_logins(pwd)
                if logins is None:
                    wx.CallAfter(speak_notification, _("Authentication error. Check your password."), 'error')
                else:
                    wx.CallAfter(self._show_last_logins_dialog, parent, logins)
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_load, daemon=True).start()

    def _show_last_logins_dialog(self, parent, logins):
        play_sound('ui/switch_category.ogg')
        dlg = wx.Dialog(parent, title=_("Last Logins"), size=(450, 350),
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        panel = wx.Panel(dlg)
        vbox = wx.BoxSizer(wx.VERTICAL)

        login_list = wx.ListBox(panel)
        if not logins:
            login_list.Append(_("No login history"))
        else:
            for lg in reversed(logins):
                login_list.Append(f"{lg['date']} - IP: {lg['ip']}")
        vbox.Add(login_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        close_btn = wx.Button(panel, wx.ID_CANCEL, _("Close"))
        vbox.Add(close_btn, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=10)

        panel.SetSizer(vbox)
        _bind_sounds_to_panel(panel)
        if apply_skin_to_window:
            try:
                apply_skin_to_window(dlg)
            except Exception:
                pass

        login_list.SetSelection(0)
        login_list.SetFocus()

        dlg.ShowModal()
        dlg.Destroy()

    # ---- Others ----

    def _open_others(self):
        play_sound('ui/switch_category.ogg')
        dlg = wx.Dialog(self, title=_("Others"), size=(400, 200))
        panel = wx.Panel(dlg)
        vbox = wx.BoxSizer(wx.VERTICAL)

        others_list = wx.ListBox(panel)
        others_list.Append(_("Archive this account"))
        vbox.Add(others_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        open_btn = wx.Button(panel, label=_("Open"))
        close_btn = wx.Button(panel, wx.ID_CANCEL, _("Close"))
        btn_box.Add(open_btn, flag=wx.RIGHT, border=10)
        btn_box.Add(close_btn)
        vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=10)

        panel.SetSizer(vbox)
        _bind_sounds_to_panel(panel)
        if apply_skin_to_window:
            try:
                apply_skin_to_window(dlg)
            except Exception:
                pass

        others_list.SetSelection(0)
        others_list.SetFocus()

        def on_open(evt):
            sel = others_list.GetSelection()
            if sel == 0:
                self._archive_account(dlg)

        open_btn.Bind(wx.EVT_BUTTON, on_open)
        others_list.Bind(wx.EVT_LISTBOX_DCLICK, on_open)
        others_list.Bind(wx.EVT_KEY_DOWN, lambda e: on_open(e) if e.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) else e.Skip())

        dlg.ShowModal()
        dlg.Destroy()

    def _archive_account(self, parent):
        """Archive account with warning."""
        play_sound('ui/switch_category.ogg')
        warning = _(
            "Archiving your account will have the following effects:\n"
            "- An indication that the account is archived will be placed next to all posts on the forum.\n"
            "- The account will not be displayed in the users lists.\n"
            "- The account will be removed from all contact lists.\n"
            "- Users will not be able to send private messages to this account.\n"
            "- The profile will be removed from the server.\n"
            "- You will be opted out of all groups and conversations.\n"
            "- All information about followed threads and pinned groups will be removed.\n\n"
            "The account will be automatically unarchived the next time you log in, "
            "but removed data will not be restored."
        )

        dlg = wx.Dialog(parent, title=_("Archive this account"), size=(500, 400))
        panel = wx.Panel(dlg)
        vbox = wx.BoxSizer(wx.VERTICAL)

        vbox.Add(wx.StaticText(panel, label=_("Information:")), flag=wx.LEFT | wx.TOP, border=10)
        info_text = wx.TextCtrl(panel, value=warning, style=wx.TE_MULTILINE | wx.TE_READONLY)
        vbox.Add(info_text, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        vbox.Add(wx.StaticText(panel, label=_("Enter your password to confirm:")), flag=wx.LEFT | wx.TOP, border=10)
        pass_input = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
        vbox.Add(pass_input, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        archive_btn = wx.Button(panel, wx.ID_OK, _("Archive"))
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        btn_box.Add(archive_btn, flag=wx.RIGHT, border=10)
        btn_box.Add(cancel_btn)
        vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, border=15)

        panel.SetSizer(vbox)
        _bind_sounds_to_panel(panel)
        if apply_skin_to_window:
            try:
                apply_skin_to_window(dlg)
            except Exception:
                pass

        if dlg.ShowModal() == wx.ID_OK:
            password = pass_input.GetValue()
            if not password:
                speak_notification(_("Please enter your password"), 'warning')
            else:
                ret = wx.MessageBox(
                    _("Are you sure you want to archive this account?"),
                    _("Confirm"), wx.YES_NO | wx.ICON_WARNING, parent)
                if ret == wx.YES:
                    def do_archive():
                        try:
                            result = self.client.archive_account(password)
                            if result['success']:
                                wx.CallAfter(speak_notification, result['message'], 'success')
                            else:
                                wx.CallAfter(speak_notification, result['message'], 'error')
                        except Exception as e:
                            wx.CallAfter(speak_notification, str(e), 'error')
                    threading.Thread(target=do_archive, daemon=True).start()
        dlg.Destroy()


class BlacklistDialog(wx.Dialog):
    """Blacklist management dialog."""

    def __init__(self, parent, client):
        super().__init__(parent, title=_("Black list"), size=(400, 350),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.client = client
        self.blacklist = []

        self._build_ui()
        self._load_blacklist()

        if apply_skin_to_window:
            try:
                apply_skin_to_window(self)
            except Exception:
                pass

    def _build_ui(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.user_list = wx.ListBox(panel)
        self.user_list.Append(_("Loading..."))
        vbox.Add(self.user_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.add_btn = wx.Button(panel, label=_("Add"))
        self.remove_btn = wx.Button(panel, label=_("Remove"))
        self.close_btn = wx.Button(panel, wx.ID_CANCEL, _("Close"))
        btn_sizer.Add(self.add_btn, flag=wx.RIGHT, border=5)
        btn_sizer.Add(self.remove_btn, flag=wx.RIGHT, border=5)
        btn_sizer.Add(self.close_btn)
        vbox.Add(btn_sizer, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=10)

        panel.SetSizer(vbox)
        _bind_sounds_to_panel(panel)

        self.add_btn.Bind(wx.EVT_BUTTON, self.OnAdd)
        self.remove_btn.Bind(wx.EVT_BUTTON, self.OnRemove)

    def _load_blacklist(self):
        def do_load():
            try:
                users = self.client.get_blacklist()
                wx.CallAfter(self._on_loaded, users)
            except Exception:
                wx.CallAfter(self._on_loaded, [])
        threading.Thread(target=do_load, daemon=True).start()

    def _on_loaded(self, users):
        self.blacklist = users or []
        self._refresh_list()

    def _refresh_list(self):
        self.user_list.Clear()
        if not self.blacklist:
            self.user_list.Append(_("Blacklist is empty"))
        else:
            for user in self.blacklist:
                self.user_list.Append(user)
        self.user_list.SetSelection(0)
        self.user_list.SetFocus()

    def OnAdd(self, event):
        username = wx.GetTextFromUser(
            _("Enter the username to add to the blacklist:"),
            _("Add to blacklist"), parent=self)
        if not username:
            return

        def do_add():
            try:
                result = self.client.add_to_blacklist(username)
                if result['success']:
                    wx.CallAfter(self._on_user_added, username, result['message'])
                else:
                    wx.CallAfter(speak_notification, result['message'], 'error')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_add, daemon=True).start()

    def _on_user_added(self, username, message):
        speak_notification(message, 'success')
        self.blacklist.append(username)
        self._refresh_list()

    def OnRemove(self, event):
        sel = self.user_list.GetSelection()
        if sel == wx.NOT_FOUND or not self.blacklist:
            return
        if sel >= len(self.blacklist):
            return

        user = self.blacklist[sel]
        ret = wx.MessageBox(
            _("Are you sure you want to remove {user} from the blacklist?").format(user=user),
            _("Remove from blacklist"), wx.YES_NO | wx.ICON_QUESTION, self)
        if ret != wx.YES:
            return

        def do_remove():
            try:
                result = self.client.remove_from_blacklist(user)
                if result['success']:
                    wx.CallAfter(self._on_user_removed, user, result['message'])
                else:
                    wx.CallAfter(speak_notification, result['message'], 'error')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_remove, daemon=True).start()

    def _on_user_removed(self, user, message):
        speak_notification(message, 'success')
        if user in self.blacklist:
            self.blacklist.remove(user)
        self._refresh_list()


def show_account_management(parent, client):
    """Open the account management dialog."""
    dlg = AccountManagementDialog(parent, client)
    dlg.ShowModal()
    dlg.Destroy()
