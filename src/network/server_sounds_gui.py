# -*- coding: utf-8 -*-
"""
Server sounds manager - the moderator side of Titan-Net's sound registry.

Upload a sound once, then play it at one user, at everyone holding a role,
at a chat room, or at everybody online. The client half that receives and
caches those sounds is ``src/network/server_sounds.py``.

Keyboard-first and screen-reader-first, like the rest of Titan-Net: the list
is a plain listbox, every action is a button with a shortcut, and each
result is spoken.

All user-facing text is English and translated through gettext.
"""

from __future__ import annotations

import os
import threading
from typing import Dict, List, Optional

import wx

from src.titan_core.translation import set_language
from src.settings.settings import get_setting
from src.titan_core.sound import play_sound
from src.titan_core.skin_manager import apply_skin_to_window

from src.network.remote_ui import speak_notification, _show_skinned_message

_ = set_language(get_setting('language', 'pl'))

AUDIO_WILDCARD = ("Audio files (*.ogg;*.wav;*.mp3;*.opus;*.flac)|"
                  "*.ogg;*.wav;*.mp3;*.opus;*.flac")


class PlayTargetDialog(wx.Dialog):
    """Choose who hears a sound: everyone, one user, a role, or a room."""

    def __init__(self, parent, titan_client, sound_name: str):
        super().__init__(parent, title=_("Play '{name}'").format(name=sound_name),
                         size=(460, 380))
        self.titan_client = titan_client
        self.sound_name = sound_name
        self.target: Optional[Dict] = None
        self.announce_text: str = ''

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        vbox.Add(wx.StaticText(panel, label=_("Play to:")),
                 flag=wx.LEFT | wx.TOP, border=10)
        self.target_box = wx.RadioBox(
            panel, label="", majorDimension=1, style=wx.RA_SPECIFY_COLS,
            choices=[_("Everyone online"), _("One user"),
                     _("Everyone with a role"), _("A chat room")])
        self.target_box.Bind(wx.EVT_RADIOBOX, self._on_target_changed)
        vbox.Add(self.target_box, flag=wx.EXPAND | wx.ALL, border=10)

        self.detail_label = wx.StaticText(panel, label=_("Username:"))
        vbox.Add(self.detail_label, flag=wx.LEFT | wx.TOP, border=10)
        self.detail_ctrl = wx.TextCtrl(panel)
        vbox.Add(self.detail_ctrl, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        vbox.Add(wx.StaticText(panel, label=_("Spoken message (optional):")),
                 flag=wx.LEFT | wx.TOP, border=10)
        self.announce_ctrl = wx.TextCtrl(panel)
        vbox.Add(self.announce_ctrl, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        play_btn = wx.Button(panel, wx.ID_OK, label=_("Play"))
        play_btn.SetDefault()
        play_btn.Bind(wx.EVT_BUTTON, self._on_play)
        btn_box.Add(play_btn, flag=wx.ALL, border=5)
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, label=_("Cancel"))
        btn_box.Add(cancel_btn, flag=wx.ALL, border=5)
        vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=10)

        panel.SetSizer(vbox)
        self._on_target_changed(None)
        self.Centre()
        try:
            apply_skin_to_window(self)
        except Exception:
            pass

    def _on_target_changed(self, event):
        index = self.target_box.GetSelection()
        labels = {
            0: (_("Nothing else needed"), False),
            1: (_("Username:"), True),
            2: (_("Role (user, moderator, developer, admin):"), True),
            3: (_("Room id:"), True),
        }
        label, enabled = labels[index]
        self.detail_label.SetLabel(label)
        self.detail_ctrl.Enable(enabled)
        if not enabled:
            self.detail_ctrl.SetValue('')

    def _on_play(self, event):
        index = self.target_box.GetSelection()
        detail = self.detail_ctrl.GetValue().strip()

        if index == 0:
            self.target = {'type': 'all'}
        elif index == 1:
            if not detail:
                speak_notification(_("Enter a username"), 'error')
                self.detail_ctrl.SetFocus()
                return
            self.target = {'type': 'user', 'username': detail}
        elif index == 2:
            if not detail:
                speak_notification(_("Enter a role"), 'error')
                self.detail_ctrl.SetFocus()
                return
            self.target = {'type': 'role', 'role': detail.lower()}
        else:
            try:
                self.target = {'type': 'room', 'room_id': int(detail)}
            except ValueError:
                speak_notification(_("Room id must be a number"), 'error')
                self.detail_ctrl.SetFocus()
                return

        self.announce_text = self.announce_ctrl.GetValue().strip()
        self.EndModal(wx.ID_OK)


class ServerSoundsDialog(wx.Dialog):
    """List, upload, preview, play and delete the server's sounds."""

    def __init__(self, parent, titan_client):
        super().__init__(parent, title=_("Server Sounds"), size=(680, 520),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.titan_client = titan_client
        self.sounds: List[Dict] = []

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        vbox.Add(wx.StaticText(panel, label=_("Sounds on this server:")),
                 flag=wx.LEFT | wx.TOP, border=10)
        self.listbox = wx.ListBox(panel)
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._on_play())
        vbox.Add(self.listbox, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in ((_("Play at..."), self._on_play),
                               (_("Preview here"), self._on_preview),
                               (_("Upload"), self._on_upload),
                               (_("Delete"), self._on_delete),
                               (_("Refresh"), lambda: self._refresh())):
            button = wx.Button(panel, label=label)
            button.Bind(wx.EVT_BUTTON, lambda e, h=handler: h())
            btn_box.Add(button, flag=wx.ALL, border=5)
        close_btn = wx.Button(panel, wx.ID_CLOSE, label=_("Close"))
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        btn_box.Add(close_btn, flag=wx.ALL, border=5)
        vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=10)

        panel.SetSizer(vbox)
        self.Centre()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        try:
            apply_skin_to_window(self)
        except Exception:
            pass
        try:
            play_sound('ui/dialog.ogg')
        except Exception:
            pass
        self._refresh()

    # --- data -----------------------------------------------------------

    def _refresh(self, announce: bool = False):
        def _fetch():
            result = self.titan_client.list_server_sounds()
            wx.CallAfter(self._apply, result, announce)

        threading.Thread(target=_fetch, daemon=True).start()

    def _apply(self, result: Dict, announce: bool):
        if not result.get('success'):
            speak_notification(result.get('error') or _("Could not load sounds"), 'error')
            return
        self.sounds = result.get('sounds', [])
        self.listbox.Clear()
        for sound in self.sounds:
            size_kb = max(1, int(sound.get('size', 0) / 1024))
            description = sound.get('description') or ''
            label = _("{name} - {size} KB").format(name=sound['name'], size=size_kb)
            if description:
                label = f"{label} - {description}"
            self.listbox.Append(label)
        if self.sounds:
            self.listbox.SetSelection(0)
        if announce:
            speak_notification(
                _("{n} sounds").format(n=len(self.sounds)), 'success')

    def _selected(self) -> Optional[Dict]:
        index = self.listbox.GetSelection()
        if index == wx.NOT_FOUND or index >= len(self.sounds):
            speak_notification(_("Select a sound first"), 'error')
            return None
        return self.sounds[index]

    # --- actions --------------------------------------------------------

    def _on_key(self, event: wx.KeyEvent):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CLOSE)
            return
        if event.GetKeyCode() == wx.WXK_DELETE and self.FindFocus() is self.listbox:
            self._on_delete()
            return
        event.Skip()

    def _on_play(self):
        sound = self._selected()
        if not sound:
            return
        with PlayTargetDialog(self, self.titan_client, sound['name']) as dlg:
            if dlg.ShowModal() != wx.ID_OK or not dlg.target:
                return
            target = dlg.target
            announce = dlg.announce_text

        name = sound['name']

        def _send():
            result = self.titan_client.trigger_server_sound(
                name, target, announce=announce or None)
            wx.CallAfter(self._on_play_result, result)

        threading.Thread(target=_send, daemon=True).start()

    def _on_play_result(self, result: Dict):
        if not result.get('success'):
            speak_notification(result.get('error') or _("Could not play the sound"), 'error')
            return
        speak_notification(
            _("Played to {n} listeners").format(n=result.get('played_to', 0)), 'success')

    def _on_preview(self):
        """Play the sound on this machine only, without touching anyone else."""
        sound = self._selected()
        if not sound:
            return
        name, digest = sound['name'], sound.get('sha256', '')

        def _fetch():
            try:
                from src.network import server_sounds
                path = server_sounds.ensure_cached(self.titan_client, name, digest)
            except Exception as e:
                print(f"[Server sounds] preview failed: {e}")
                path = None
            if not path:
                wx.CallAfter(speak_notification,
                             _("Could not download that sound"), 'error')
                return
            try:
                from src.titan_core.sound import play_sound_file
                play_sound_file(path)
            except Exception as e:
                print(f"[Server sounds] preview playback failed: {e}")

        threading.Thread(target=_fetch, daemon=True).start()

    def _on_upload(self):
        with wx.FileDialog(self, _("Choose a sound file"), wildcard=AUDIO_WILDCARD,
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as file_dlg:
            if file_dlg.ShowModal() != wx.ID_OK:
                return
            path = file_dlg.GetPath()

        default_name = os.path.splitext(os.path.basename(path))[0].lower()
        with wx.TextEntryDialog(self, _("Name for this sound:"),
                                _("Upload sound"), default_name) as name_dlg:
            if name_dlg.ShowModal() != wx.ID_OK:
                return
            name = name_dlg.GetValue().strip().lower()
        if not name:
            speak_notification(_("A name is required"), 'error')
            return

        with wx.TextEntryDialog(self, _("Description (optional):"),
                                _("Upload sound")) as desc_dlg:
            description = desc_dlg.GetValue().strip() if desc_dlg.ShowModal() == wx.ID_OK else ''

        def _send():
            result = self.titan_client.upload_server_sound(name, path, description or None)
            wx.CallAfter(self._on_upload_result, result, name)

        speak_notification(_("Uploading..."), 'info')
        threading.Thread(target=_send, daemon=True).start()

    def _on_upload_result(self, result: Dict, name: str):
        if not result.get('success'):
            reason = result.get('error') or _("Upload failed")
            speak_notification(reason, 'error')
            _show_skinned_message(reason, _("Upload sound"), wx.OK | wx.ICON_ERROR, self)
            return
        speak_notification(_("Uploaded: {name}").format(name=name), 'success')
        self._refresh()

    def _on_delete(self):
        sound = self._selected()
        if not sound:
            return
        name = sound['name']
        confirmed = _show_skinned_message(
            _("Delete the sound '{name}'? This cannot be undone.").format(name=name),
            _("Delete sound"), wx.YES_NO | wx.ICON_WARNING, self)
        # ShowModal() returns wx.ID_YES, never wx.YES.
        if confirmed != wx.ID_YES:
            return

        def _send():
            result = self.titan_client.delete_server_sound(name)
            wx.CallAfter(self._on_delete_result, result, name)

        threading.Thread(target=_send, daemon=True).start()

    def _on_delete_result(self, result: Dict, name: str):
        if not result.get('success'):
            reason = result.get('error') or _("Could not delete the sound")
            speak_notification(reason, 'error')
            _show_skinned_message(reason, _("Delete sound"), wx.OK | wx.ICON_ERROR, self)
            return
        speak_notification(_("Deleted: {name}").format(name=name), 'success')
        self._refresh()
