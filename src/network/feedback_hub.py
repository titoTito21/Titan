"""
Titan-Net Feedback Hub
======================

Standalone GUI module that lets Titan-Net users submit feedback or ideas,
upvote each other's submissions, and lets moderators/administrators change
status (for feedback) or accept / reject (for ideas).

Architecture follows the main TCE GUI (``src.ui.gui.TitanApp``):
    - a single ListBox where row 0 is the virtual tab bar
      (``Feedback, 1 of 2`` / ``Ideas, 2 of 2``)
    - Left / Right on row 0 cycles tabs (feedback -> ideas)
    - Up / Down navigates entries; row 0 emits ``ui/tapbar.ogg``,
      tab cycle emits ``ui/switch_list.ogg``,
      attempting to cycle past the edge emits ``ui/endoftapbar.ogg``
    - Enter activates the focused entry (opens the detail dialog)

All notification messages and on-screen text are in English; translation
is handled by the ``network`` gettext domain (``_(...)``).
"""

from __future__ import annotations

import os
import threading
import sys
from datetime import datetime
from typing import Optional, Dict, List

import wx

from src.titan_core.translation import set_language
from src.settings.settings import get_setting
from src.titan_core.sound import (
    play_sound,
    initialize_sound,
    play_focus_sound,
    play_endoflist_sound,
)
from src.titan_core.skin_manager import apply_skin_to_window

# Pull translations from the network domain - same domain as titan_net_gui.
_ = set_language(get_setting('language', 'pl'))

# Speech / sound helpers from titan_net_gui. Resolved at *call* time (not at
# import time) so we are not bitten by circular-import edge cases when
# feedback_hub is loaded while titan_net_gui is still mid-import. A direct
# accessible_output3 fallback keeps the GUI usable even if titan_net_gui's
# speakers are unavailable.
try:
    import accessible_output3.outputs.auto as _ao_auto
    _local_speaker = _ao_auto.Auto()
except Exception as _e:  # pragma: no cover - some platforms / builds
    print(f"[Feedback Hub] accessible_output3 unavailable: {_e}")
    _local_speaker = None


def speak_titannet(text, position=0.0, pitch_offset=0, interrupt=True):
    """Speak via titan_net_gui's stereo helper, falling back to ao3 directly."""
    if not text:
        return
    try:
        from src.network import titan_net_gui  # late import - circular safe
        helper = getattr(titan_net_gui, 'speak_titannet', None)
        if helper is not None:
            helper(text, position=position, pitch_offset=pitch_offset, interrupt=interrupt)
            return
    except Exception as e:
        print(f"[Feedback Hub] speak_titannet helper failed: {e}")
    if _local_speaker is not None:
        try:
            _local_speaker.speak(str(text), interrupt=interrupt)
        except Exception as e:
            print(f"[Feedback Hub] ao3 speak failed: {e}")
    print(f"[Feedback Hub] {text}")


def speak_notification(text, notification_type='info', play_sound_effect=True):
    """Same panoramic notification surface as titan_net_gui.speak_notification."""
    if not text:
        return
    try:
        from src.network import titan_net_gui
        helper = getattr(titan_net_gui, 'speak_notification', None)
        if helper is not None:
            helper(text, notification_type=notification_type, play_sound_effect=play_sound_effect)
            return
    except Exception as e:
        print(f"[Feedback Hub] speak_notification helper failed: {e}")

    # Minimal fallback: pick a sound for the type and speak.
    if play_sound_effect:
        sound_map = {
            'error': 'core/error.ogg',
            'warning': 'core/error.ogg',
            'success': 'core/SELECT.ogg',
            'info': 'ui/dialog.ogg',
        }
        try:
            play_sound(sound_map.get(notification_type, 'ui/dialog.ogg'))
        except Exception:
            pass
    speak_titannet(text)


# Make sure the sound mixer is up even when Feedback Hub is launched in a
# context where the main TCE GUI never started (idempotent).
try:
    initialize_sound()
except Exception as _e:
    print(f"[Feedback Hub] initialize_sound() failed at import: {_e}")


def _show_skinned_message(message, caption, style=wx.OK | wx.ICON_INFORMATION, parent=None):
    dlg = wx.MessageDialog(parent, message, caption, style)
    try:
        apply_skin_to_window(dlg)
    except Exception:
        pass
    result = dlg.ShowModal()
    dlg.Destroy()
    return result


def _is_screen_reader_running() -> bool:
    """Mirror src.ui.gui._is_screen_reader_running for the Feedback Hub.

    Used to gate SR-only announcements (the "Tab bar" marker) — platform-TTS
    fallbacks like SAPI must not trigger that hint.
    """
    try:
        from src.ui.gui import _is_screen_reader_running as _gui_check
        return bool(_gui_check())
    except Exception:
        pass
    try:
        if _local_speaker is None:
            return False
        output = _local_speaker.get_first_available_output()
        if output is None:
            return False
        if output.is_system_output():
            return False
        is_active = getattr(output, 'is_active', None)
        if callable(is_active):
            return bool(is_active())
        return True
    except Exception:
        return False


def _announce_tab_bar() -> None:
    """Play the tab-bar earcon (always) and speak "Tab bar" (SR-only).

    Delegates to src.accessibility.messages so the "Tab bar" string lives in
    the accessibility translation domain — same contract as TitanApp.
    """
    try:
        from src.accessibility.messages import announce_tab_bar as _a
        _a()
        return
    except Exception as e:
        print(f"[Feedback Hub] announce_tab_bar import failed: {e}")
    try:
        play_sound('ui/tapbar.ogg')
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ITEM_TYPE_FEEDBACK = 'feedback'
ITEM_TYPE_IDEA = 'idea'

FEEDBACK_TABS = (
    (ITEM_TYPE_FEEDBACK, lambda: _("Feedback")),
    (ITEM_TYPE_IDEA,     lambda: _("Ideas")),
)

# Status keys must match Database.FEEDBACK_STATUSES / IDEA_STATUSES on the server.
FEEDBACK_STATUS_OPTIONS = (
    ('next_version',  lambda: _("In next version")),
    ('considering',   lambda: _("Under consideration")),
    ('reproducing',   lambda: _("Reproducing the problem")),
    ('resolved',      lambda: _("Resolved")),
    ('wont_fix',      lambda: _("Cannot be resolved")),
)

IDEA_STATUS_OPTIONS = (
    ('accepted', lambda: _("Accept idea")),
    ('rejected', lambda: _("Reject idea")),
)

PENDING_FEEDBACK_LABEL = lambda: _("Awaiting moderation")
PENDING_IDEA_LABEL = lambda: _("Waiting for consideration")

ATTACHMENT_MAX_BYTES = 12 * 1024 * 1024  # 12 MB
AUDIO_EXTENSIONS = {'.ogg', '.mp3', '.wav', '.m4a', '.flac', '.aac', '.opus'}
TEXT_EXTENSIONS = {
    '.txt', '.log', '.md', '.json', '.xml', '.csv', '.ini', '.cfg', '.yaml', '.yml',
    '.py', '.js', '.html', '.css',
}


def status_label(item_type: str, status_key: str) -> str:
    """Return the localized human label for a feedback/idea status."""
    if not status_key or status_key == 'pending':
        return PENDING_IDEA_LABEL() if item_type == ITEM_TYPE_IDEA else PENDING_FEEDBACK_LABEL()
    table = IDEA_STATUS_OPTIONS if item_type == ITEM_TYPE_IDEA else FEEDBACK_STATUS_OPTIONS
    for key, label_factory in table:
        if key == status_key:
            return label_factory()
    return status_key


# ---------------------------------------------------------------------------
# Dialog: New feedback / idea
# ---------------------------------------------------------------------------

class NewFeedbackDialog(wx.Dialog):
    """Form for submitting a new feedback or idea entry.

    Fields:
        - Title (single line, required)
        - Category (Feedback or Idea)
        - Content (multi-line, required)
        - Attachment (optional, up to 12 MB - recording / screenshot / log)
    """

    def __init__(self, parent, default_type: str = ITEM_TYPE_FEEDBACK):
        super().__init__(parent, title=_("New feedback or idea"), size=(560, 520),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.attachment_path: Optional[str] = None
        self.attachment_data: Optional[bytes] = None
        self.attachment_name: Optional[str] = None
        self.result_payload: Optional[Dict] = None
        self._build(default_type)
        self.Centre()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        try:
            play_sound('ui/dialog.ogg')
        except Exception:
            pass

    def _build(self, default_type: str):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        title_label = wx.StaticText(panel, label=_("Title:"))
        vbox.Add(title_label, flag=wx.LEFT | wx.TOP, border=10)
        self.title_ctrl = wx.TextCtrl(panel)
        vbox.Add(self.title_ctrl, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        cat_label = wx.StaticText(panel, label=_("Category:"))
        vbox.Add(cat_label, flag=wx.LEFT | wx.TOP, border=10)
        choices = [_("Feedback"), _("Idea")]
        self.category_ctrl = wx.Choice(panel, choices=choices)
        self.category_ctrl.SetSelection(1 if default_type == ITEM_TYPE_IDEA else 0)
        vbox.Add(self.category_ctrl, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        content_label = wx.StaticText(panel, label=_("Content:"))
        vbox.Add(content_label, flag=wx.LEFT | wx.TOP, border=10)
        self.content_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER)
        vbox.Add(self.content_ctrl, proportion=1,
                 flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        # Attachment row
        att_box = wx.BoxSizer(wx.HORIZONTAL)
        self.attach_btn = wx.Button(panel, label=_("Attachment - recording / screenshot / log..."))
        self.attach_btn.Bind(wx.EVT_BUTTON, self._on_pick_attachment)
        att_box.Add(self.attach_btn, flag=wx.ALL, border=5)

        self.attach_label = wx.StaticText(panel, label=_("No attachment"))
        att_box.Add(self.attach_label, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=5)

        self.clear_btn = wx.Button(panel, label=_("Remove attachment"))
        self.clear_btn.Disable()
        self.clear_btn.Bind(wx.EVT_BUTTON, self._on_clear_attachment)
        att_box.Add(self.clear_btn, flag=wx.ALL, border=5)
        vbox.Add(att_box, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=5)

        # Action row
        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        self.send_btn = wx.Button(panel, label=_("Send feedback"))
        self.send_btn.Bind(wx.EVT_BUTTON, self._on_send)
        btn_box.Add(self.send_btn, flag=wx.ALL, border=5)
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, label=_("Cancel"))
        btn_box.Add(cancel_btn, flag=wx.ALL, border=5)
        vbox.Add(btn_box, flag=wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, border=5)

        panel.SetSizer(vbox)
        self.title_ctrl.SetFocus()

    def _on_key(self, event: wx.KeyEvent):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        event.Skip()

    def _on_pick_attachment(self, event):
        try:
            play_sound('core/SELECT.ogg')
        except Exception:
            pass

        wildcard = (
            _("Audio recordings") + " (*.ogg;*.mp3;*.wav)|*.ogg;*.mp3;*.wav|"
            + _("Images / screenshots") + " (*.png;*.jpg;*.jpeg;*.bmp)|*.png;*.jpg;*.jpeg;*.bmp|"
            + _("Log / text files") + " (*.txt;*.log)|*.txt;*.log|"
            + _("All files") + " (*.*)|*.*"
        )
        with wx.FileDialog(self, _("Select attachment"),
                           wildcard=wildcard,
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()

        try:
            size = os.path.getsize(path)
        except OSError as e:
            _show_skinned_message(_("Cannot read file: {error}").format(error=str(e)),
                          _("Attachment"), wx.OK | wx.ICON_ERROR)
            return

        if size > ATTACHMENT_MAX_BYTES:
            _show_skinned_message(_("Attachment is too large. Maximum size is 12 MB."),
                          _("Attachment"), wx.OK | wx.ICON_ERROR)
            return

        try:
            with open(path, 'rb') as fh:
                data = fh.read()
        except OSError as e:
            _show_skinned_message(_("Cannot read file: {error}").format(error=str(e)),
                          _("Attachment"), wx.OK | wx.ICON_ERROR)
            return

        self.attachment_path = path
        self.attachment_data = data
        self.attachment_name = os.path.basename(path)
        self.attach_label.SetLabel(_("Attached: {name} ({size} KB)").format(
            name=self.attachment_name, size=max(1, size // 1024)))
        self.clear_btn.Enable()
        speak_notification(_("Attachment selected: {name}").format(name=self.attachment_name),
                           'info')

    def _on_clear_attachment(self, event):
        self.attachment_path = None
        self.attachment_data = None
        self.attachment_name = None
        self.attach_label.SetLabel(_("No attachment"))
        self.clear_btn.Disable()
        speak_notification(_("Attachment removed"), 'info')

    def _on_send(self, event):
        title = self.title_ctrl.GetValue().strip()
        content = self.content_ctrl.GetValue().strip()
        if not title:
            speak_notification(_("Title is required"), 'error')
            self.title_ctrl.SetFocus()
            return
        if not content:
            speak_notification(_("Content is required"), 'error')
            self.content_ctrl.SetFocus()
            return

        item_type = ITEM_TYPE_IDEA if self.category_ctrl.GetSelection() == 1 else ITEM_TYPE_FEEDBACK
        self.result_payload = {
            'item_type': item_type,
            'title': title,
            'content': content,
            'attachment_data': self.attachment_data,
            'attachment_name': self.attachment_name,
        }
        self.EndModal(wx.ID_OK)


# ---------------------------------------------------------------------------
# Dialog: Detail view (upvote / change status / accept / reject / delete /
#                     view attachment)
# ---------------------------------------------------------------------------

class FeedbackDetailDialog(wx.Dialog):
    """Inspect, vote on, moderate or delete one feedback/idea entry.

    The dialog lazily refreshes the underlying record after every action so
    upvote counts and status labels stay in sync with what the server holds.
    """

    def __init__(self, parent, titan_client, feedback_id: int):
        super().__init__(parent, title=_("Feedback details"), size=(640, 560),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.titan_client = titan_client
        self.feedback_id = feedback_id
        self.item: Optional[Dict] = None
        self.deleted = False  # parent uses this to refresh the list

        self._build()
        self.Centre()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        try:
            play_sound('ui/dialog.ogg')
        except Exception:
            pass
        self._reload(initial=True)

    @property
    def is_moderator(self) -> bool:
        return bool(getattr(self.titan_client, 'is_admin', False)
                    or getattr(self.titan_client, 'user_role', 'user') in ('moderator', 'developer'))

    @property
    def is_author(self) -> bool:
        return bool(self.item and self.item.get('author_id') == getattr(self.titan_client, 'user_id', None))

    def _build(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        title_label = wx.StaticText(panel, label=_("Title:"))
        vbox.Add(title_label, flag=wx.LEFT | wx.TOP, border=10)
        self.title_ctrl = wx.TextCtrl(panel, style=wx.TE_READONLY)
        vbox.Add(self.title_ctrl, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        meta_label = wx.StaticText(panel, label=_("Author / status:"))
        vbox.Add(meta_label, flag=wx.LEFT | wx.TOP, border=10)
        self.meta_ctrl = wx.TextCtrl(panel, style=wx.TE_READONLY)
        vbox.Add(self.meta_ctrl, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        content_label = wx.StaticText(panel, label=_("Content:"))
        vbox.Add(content_label, flag=wx.LEFT | wx.TOP, border=10)
        self.content_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        vbox.Add(self.content_ctrl, proportion=1,
                 flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        # Attachment row (button is shown only when an attachment is present)
        self.attachment_btn = wx.Button(panel, label=_("Open attachment"))
        self.attachment_btn.Bind(wx.EVT_BUTTON, self._on_open_attachment)
        self.attachment_btn.Hide()
        vbox.Add(self.attachment_btn, flag=wx.LEFT | wx.RIGHT | wx.TOP, border=10)

        # Action row
        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        self.upvote_btn = wx.Button(panel, label=_("Upvote"))
        self.upvote_btn.Bind(wx.EVT_BUTTON, self._on_upvote)
        btn_box.Add(self.upvote_btn, flag=wx.ALL, border=5)

        # Moderation: change status (feedback) or consider idea (idea).
        # Same widget, the label and behaviour swap once the item loads.
        self.status_btn = wx.Button(panel, label=_("Change status"))
        self.status_btn.Bind(wx.EVT_BUTTON, self._on_status_button)
        self.status_btn.Hide()
        btn_box.Add(self.status_btn, flag=wx.ALL, border=5)

        self.delete_btn = wx.Button(panel, label=_("Delete"))
        self.delete_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        self.delete_btn.Hide()
        btn_box.Add(self.delete_btn, flag=wx.ALL, border=5)

        close_btn = wx.Button(panel, wx.ID_CLOSE, label=_("Close"))
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        btn_box.Add(close_btn, flag=wx.ALL, border=5)

        vbox.Add(btn_box, flag=wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, border=5)

        panel.SetSizer(vbox)
        self.SetEscapeId(wx.ID_CLOSE)

    def _on_key(self, event: wx.KeyEvent):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CLOSE)
            return
        event.Skip()

    def _reload(self, initial=False):
        def _fetch():
            result = self.titan_client.get_feedback(self.feedback_id)
            wx.CallAfter(self._apply_item, result, initial)

        threading.Thread(target=_fetch, daemon=True).start()

    def _apply_item(self, result: Dict, initial: bool):
        if not result.get('success'):
            speak_notification(result.get('error') or _("Failed to load feedback"), 'error')
            if initial:
                self.EndModal(wx.ID_CANCEL)
            return

        self.item = result.get('item') or {}
        item_type = self.item.get('item_type', ITEM_TYPE_FEEDBACK)

        self.SetTitle(_("Idea details") if item_type == ITEM_TYPE_IDEA else _("Feedback details"))
        self.title_ctrl.SetValue(self.item.get('title', ''))
        author = self.item.get('author_username', '?')
        upvote_count = int(self.item.get('upvote_count') or 0)
        meta_parts = [
            _("Author: {name}").format(name=author),
            _("Status: {status}").format(status=status_label(item_type, self.item.get('status', 'pending'))),
            _("Upvotes: {n}").format(n=upvote_count),
        ]
        self.meta_ctrl.SetValue(" | ".join(meta_parts))
        self.content_ctrl.SetValue(self.item.get('content', ''))

        # Attachment
        if self.item.get('attachment_path'):
            self.attachment_btn.SetLabel(self._attachment_button_label())
            self.attachment_btn.Show()
        else:
            self.attachment_btn.Hide()

        # Upvote button: hide for the author, label reflects whether the
        # viewer has already cast an upvote.
        if self.is_author:
            self.upvote_btn.Hide()
        else:
            self.upvote_btn.Show()
            if int(self.item.get('viewer_upvoted') or 0):
                self.upvote_btn.SetLabel(_("Remove upvote"))
            else:
                self.upvote_btn.SetLabel(_("Upvote"))

        # Moderation / author actions
        if self.is_moderator:
            if item_type == ITEM_TYPE_IDEA:
                self.status_btn.SetLabel(_("Consider idea"))
            else:
                self.status_btn.SetLabel(_("Change status"))
            self.status_btn.Show()
        else:
            self.status_btn.Hide()

        if self.is_moderator or self.is_author:
            self.delete_btn.Show()
        else:
            self.delete_btn.Hide()

        self.Layout()
        # We deliberately do NOT speak the title/author/status here on the
        # initial load — the screen reader reads the focused dialog field on
        # its own, so duplicating that as a TTS announcement is just noise.

    def _attachment_button_label(self) -> str:
        """Pick a button label that reflects what kind of file is attached."""
        name = (self.item or {}).get('attachment_name', '') or ''
        ext = os.path.splitext(name)[1].lower()
        if ext in AUDIO_EXTENSIONS:
            return _("Play recording ({name})").format(name=name)
        if ext in TEXT_EXTENSIONS:
            return _("Read logs ({name})").format(name=name)
        return _("Open attachment ({name})").format(name=name)

    # --- Action handlers ---------------------------------------------------

    def _on_upvote(self, event):
        if not self.item:
            return
        try:
            play_sound('core/SELECT.ogg')
        except Exception:
            pass

        feedback_id = self.feedback_id
        title = self.item.get('title', '')

        def _send():
            result = self.titan_client.upvote_feedback(feedback_id)
            wx.CallAfter(self._on_upvote_result, result, title)

        threading.Thread(target=_send, daemon=True).start()

    def _on_upvote_result(self, result: Dict, title: str):
        if not result.get('success'):
            speak_notification(result.get('error') or _("Failed to upvote"), 'error')
            return
        action = result.get('action')
        count = int(result.get('upvote_count') or 0)
        try:
            play_sound('titannet/feedback hub/upwote.ogg')
        except Exception:
            pass
        if action == 'added':
            speak_notification(_("{title}: upvoted, with {n} upvotes").format(title=title, n=count),
                               'success', play_sound_effect=False)
        else:
            speak_notification(_("{title}: upvote removed, with {n} upvotes").format(title=title, n=count),
                               'info', play_sound_effect=False)
        self._reload()

    def _on_status_button(self, event):
        if not self.item:
            return
        try:
            play_sound('core/SELECT.ogg')
        except Exception:
            pass
        item_type = self.item.get('item_type', ITEM_TYPE_FEEDBACK)
        options = IDEA_STATUS_OPTIONS if item_type == ITEM_TYPE_IDEA else FEEDBACK_STATUS_OPTIONS

        menu = wx.Menu()
        id_to_status: Dict[int, str] = {}
        for key, label_factory in options:
            mid = wx.NewIdRef()
            menu.Append(mid, label_factory())
            id_to_status[int(mid)] = key

        def _on_menu_select(evt):
            status_key = id_to_status.get(evt.GetId())
            if status_key:
                self._submit_status_change(status_key)

        self.Bind(wx.EVT_MENU, _on_menu_select)
        self.PopupMenu(menu)
        menu.Destroy()

    def _submit_status_change(self, status_key: str):
        if not self.item:
            return
        feedback_id = self.feedback_id

        def _send():
            result = self.titan_client.change_feedback_status(feedback_id, status_key)
            wx.CallAfter(self._on_status_result, result)

        threading.Thread(target=_send, daemon=True).start()

    def _on_status_result(self, result: Dict):
        if not result.get('success'):
            speak_notification(result.get('error') or _("Failed to change status"), 'error')
            return
        # The server-side broadcast plays the per-event sound on every client,
        # including this one - so we only refresh the dialog here.
        self._reload()

    def _on_delete(self, event):
        if not self.item:
            return
        title = self.item.get('title', '')
        confirm = _show_skinned_message(
            _("Delete '{title}'? This cannot be undone.").format(title=title),
            _("Delete feedback"),
            wx.YES_NO | wx.ICON_WARNING,
        )
        if confirm != wx.YES:
            return
        feedback_id = self.feedback_id

        def _send():
            result = self.titan_client.delete_feedback(feedback_id)
            wx.CallAfter(self._on_delete_result, result, title)

        threading.Thread(target=_send, daemon=True).start()

    def _on_delete_result(self, result: Dict, title: str):
        if not result.get('success'):
            speak_notification(result.get('error') or _("Failed to delete"), 'error')
            return
        self.deleted = True
        speak_notification(_("Deleted: {title}").format(title=title), 'success')
        self.EndModal(wx.ID_OK)

    def _on_open_attachment(self, event):
        if not self.item or not self.item.get('attachment_path'):
            return
        try:
            play_sound('core/SELECT.ogg')
        except Exception:
            pass

        feedback_id = self.feedback_id
        name = self.item.get('attachment_name') or 'attachment'

        def _fetch():
            result = self.titan_client.get_feedback_attachment(feedback_id)
            wx.CallAfter(self._on_attachment_loaded, result, name)

        threading.Thread(target=_fetch, daemon=True).start()

    def _on_attachment_loaded(self, result: Dict, name: str):
        if not result.get('success') or not result.get('bytes'):
            speak_notification(result.get('error') or _("Failed to load attachment"), 'error')
            return

        ext = os.path.splitext(name)[1].lower()
        # Logs / text: show inline so the user (and moderation) can read.
        if ext in TEXT_EXTENSIONS:
            try:
                text = result['bytes'].decode('utf-8', errors='replace')
            except Exception as e:
                speak_notification(str(e), 'error')
                return
            _AttachmentTextViewer(self, name, text).ShowModal()
            return

        # Audio / image / other: drop into a temp file and hand off to the OS.
        import tempfile
        fd, tmp_path = tempfile.mkstemp(suffix=ext or '')
        try:
            os.write(fd, result['bytes'])
        finally:
            os.close(fd)

        if ext in AUDIO_EXTENSIONS:
            try:
                from src.titan_core.sound import play_sound_file
                play_sound_file(tmp_path)
                speak_notification(_("Playing recording: {name}").format(name=name), 'info',
                                   play_sound_effect=False)
                return
            except Exception as e:
                print(f"[Feedback Hub] play_sound_file failed: {e}")

        # Final fallback - hand to the OS file association.
        try:
            if sys.platform == 'win32':
                os.startfile(tmp_path)  # type: ignore[attr-defined]
            elif sys.platform == 'darwin':
                import subprocess
                subprocess.Popen(['open', tmp_path])
            else:
                import subprocess
                subprocess.Popen(['xdg-open', tmp_path])
        except Exception as e:
            speak_notification(_("Cannot open attachment: {error}").format(error=str(e)), 'error')


class _AttachmentTextViewer(wx.Dialog):
    """Read-only viewer for text/log attachments."""

    def __init__(self, parent, name: str, text: str):
        super().__init__(parent, title=_("Attachment: {name}").format(name=name),
                         size=(700, 500),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        ctrl = wx.TextCtrl(panel, value=text,
                           style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
        vbox.Add(ctrl, proportion=1, flag=wx.EXPAND | wx.ALL, border=8)
        close = wx.Button(panel, wx.ID_CLOSE, label=_("Close"))
        close.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        vbox.Add(close, flag=wx.ALIGN_RIGHT | wx.ALL, border=6)
        panel.SetSizer(vbox)
        self.SetEscapeId(wx.ID_CLOSE)
        self.Centre()
        ctrl.SetFocus()


# ---------------------------------------------------------------------------
# Main Frame
# ---------------------------------------------------------------------------

class FeedbackHubFrame(wx.Frame):
    """Standalone Feedback Hub window.

    Layout mirrors the Titan main GUI:
        - top toolbar (New feedback / Refresh / Close)
        - virtual tab bar as row 0 of the listbox (Feedback / Ideas)
        - listbox of items, sorted by recency
        - status bar with focus / count info

    Sounds:
        - row 0 focus -> ``ui/tapbar.ogg``
        - tab cycle -> ``ui/switch_list.ogg``
        - cycle past edge -> ``ui/endoftapbar.ogg``
        - focus an upvoted entry -> ``titannet/feedback hub/upwote.ogg``
    """

    def __init__(self, parent, titan_client):
        super().__init__(parent, title=_("Feedback Hub"), size=(720, 540))
        self.titan_client = titan_client
        self.current_tab: str = ITEM_TYPE_FEEDBACK
        self.items_cache: List[Dict] = []
        self._last_focus_idx: int = -1

        self._build()
        self.Centre()
        self.Bind(wx.EVT_CLOSE, self._on_close)

        # Wire transient broadcast callbacks: when a remote event arrives we
        # refresh the list and announce the change.
        self._install_callbacks()

        # Opening earcon only — the screen reader reads the window title and
        # the focused listbox content, so don't double-announce. Use the
        # popup earcon (matches the popupclose.ogg we play on Escape).
        try:
            play_sound('ui/popup.ogg')
        except Exception:
            pass

        # Initial load
        wx.CallAfter(self._refresh_items, announce=False)

    # ---- Construction -----------------------------------------------------

    def _build(self):
        self.panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.view_label = wx.StaticText(self.panel, label=_("Feedback Hub"))
        sizer.Add(self.view_label, flag=wx.ALL, border=8)

        # Toolbar
        bar = wx.BoxSizer(wx.HORIZONTAL)
        self.new_btn = wx.Button(self.panel, label=_("New feedback"))
        self.new_btn.Bind(wx.EVT_BUTTON, self._on_new_feedback)
        bar.Add(self.new_btn, flag=wx.RIGHT, border=6)

        self.refresh_btn = wx.Button(self.panel, label=_("Refresh"))
        self.refresh_btn.Bind(wx.EVT_BUTTON, lambda e: self._refresh_items(announce=False))
        bar.Add(self.refresh_btn, flag=wx.RIGHT, border=6)

        self.close_btn = wx.Button(self.panel, label=_("Close"))
        self.close_btn.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        bar.Add(self.close_btn, flag=wx.RIGHT, border=6)
        sizer.Add(bar, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=8)

        # Listbox - row 0 is the virtual tab bar (marked with clientData
        # ``{'type': 'tab_bar'}`` exactly like ``src.ui.gui.TitanApp``).
        label = _("Feedback and ideas list:")
        sizer.Add(wx.StaticText(self.panel, label=label),
                  flag=wx.LEFT | wx.RIGHT | wx.TOP, border=8)
        self.listbox = wx.ListBox(self.panel, style=wx.LB_SINGLE)
        self.listbox.Bind(wx.EVT_LISTBOX, self._on_select)
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, self._on_activate)
        sizer.Add(self.listbox, proportion=1, flag=wx.EXPAND | wx.ALL, border=8)

        self.CreateStatusBar()
        self.panel.SetSizer(sizer)

        # EVT_CHAR_HOOK on the frame catches Enter / Escape / arrows BEFORE
        # any default-button or focus-rule swallows them — same approach as
        # ``TitanApp.on_key_down``. Without this, Enter on the listbox is
        # routinely eaten on Windows because no real default button exists.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key_hook)

        # Global keyboard shortcuts (accelerators send EVT_MENU to the frame
        # with the button's id, so bind the same handlers there).
        new_id = self.new_btn.GetId()
        refresh_id = self.refresh_btn.GetId()
        accel = wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('N'), new_id),
            (wx.ACCEL_NORMAL, wx.WXK_F5, refresh_id),
        ])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, self._on_new_feedback, id=new_id)
        self.Bind(wx.EVT_MENU, lambda e: self._refresh_items(announce=False), id=refresh_id)

    # ---- Callbacks --------------------------------------------------------

    def _install_callbacks(self):
        """Subscribe to Feedback Hub events broadcast by the server."""
        self._old_callbacks = {
            'feedback_new': getattr(self.titan_client, 'on_feedback_new', None),
            'feedback_upvoted': getattr(self.titan_client, 'on_feedback_upvoted', None),
            'feedback_status_changed': getattr(self.titan_client, 'on_feedback_status_changed', None),
            'feedback_deleted': getattr(self.titan_client, 'on_feedback_deleted', None),
        }
        self.titan_client.on_feedback_new = self._handle_remote_new
        self.titan_client.on_feedback_upvoted = self._handle_remote_upvote
        self.titan_client.on_feedback_status_changed = self._handle_remote_status
        self.titan_client.on_feedback_deleted = self._handle_remote_deleted

    def _restore_callbacks(self):
        if not hasattr(self, '_old_callbacks'):
            return
        for name, callback in self._old_callbacks.items():
            try:
                setattr(self.titan_client, f'on_{name}', callback)
            except Exception:
                pass

    def _handle_remote_new(self, message: Dict):
        item_type = message.get('item_type', ITEM_TYPE_FEEDBACK)
        author = message.get('author_username', '?')
        title = message.get('title', '?')
        try:
            play_sound('titannet/feedback hub/new feedback.ogg')
        except Exception:
            pass
        if item_type == ITEM_TYPE_IDEA:
            text = _("Feedback Hub: 1 new idea from {user}: {title}").format(user=author, title=title)
        else:
            text = _("Feedback Hub: 1 new feedback from {user}: {title}").format(user=author, title=title)
        speak_notification(text, 'info', play_sound_effect=False)
        wx.CallAfter(self._refresh_items, announce=False)

    def _handle_remote_upvote(self, message: Dict):
        title = message.get('title', '?')
        voter = message.get('voter_username', '?')
        try:
            play_sound('titannet/feedback hub/upwote.ogg')
        except Exception:
            pass
        if message.get('action') == 'added':
            text = _("{title} upvoted by {user}").format(title=title, user=voter)
        else:
            text = _("{title}: upvote removed by {user}").format(title=title, user=voter)
        speak_notification(text, 'info', play_sound_effect=False)
        wx.CallAfter(self._refresh_items, announce=False)

    def _handle_remote_status(self, message: Dict):
        item_type = message.get('item_type', ITEM_TYPE_FEEDBACK)
        title = message.get('title', '?')
        new_status = message.get('status', 'pending')
        if item_type == ITEM_TYPE_IDEA and new_status == 'accepted':
            try:
                play_sound('titannet/feedback hub/idea accepted.ogg')
            except Exception:
                pass
            text = _("Idea {title} accepted").format(title=title)
        elif item_type == ITEM_TYPE_IDEA and new_status == 'rejected':
            try:
                play_sound('titannet/feedback hub/idea denied.ogg')
            except Exception:
                pass
            text = _("Idea {title} rejected").format(title=title)
        else:
            try:
                play_sound('titannet/feedback hub/new feedback status.ogg')
            except Exception:
                pass
            text = _("{title}: status changed to {status}").format(
                title=title, status=status_label(item_type, new_status))
        speak_notification(text, 'info', play_sound_effect=False)
        wx.CallAfter(self._refresh_items, announce=False)

    def _handle_remote_deleted(self, message: Dict):
        wx.CallAfter(self._refresh_items, announce=False)

    # ---- List management --------------------------------------------------

    def _tab_index(self, key: str) -> int:
        for i, (tab_key, _label) in enumerate(FEEDBACK_TABS):
            if tab_key == key:
                return i
        return 0

    def _tab_bar_text(self) -> str:
        idx = self._tab_index(self.current_tab)
        label = FEEDBACK_TABS[idx][1]()
        return _("{}, {} of {}").format(label, idx + 1, len(FEEDBACK_TABS))

    def _is_tab_bar_row(self, idx: int) -> bool:
        """Row 0 is the virtual tab bar - identified by its clientData marker."""
        if idx != 0 or self.listbox.GetCount() == 0:
            return False
        try:
            data = self.listbox.GetClientData(0)
        except Exception:
            return False
        return isinstance(data, dict) and data.get('type') == 'tab_bar'

    def _format_row(self, item: Dict) -> str:
        title = item.get('title', '?')
        author = item.get('author_username', '?')
        upvotes = int(item.get('upvote_count') or 0)
        status = status_label(item.get('item_type', self.current_tab),
                              item.get('status', 'pending'))
        if upvotes:
            return _("{title} by {author}, {n} upvotes, status: {status}").format(
                title=title, author=author, n=upvotes, status=status)
        return _("{title} by {author}, status: {status}").format(
            title=title, author=author, status=status)

    def _refresh_items(self, announce: bool = False):
        item_type = self.current_tab

        def _fetch():
            result = self.titan_client.list_feedback(item_type=item_type)
            wx.CallAfter(self._apply_items, result, announce, item_type)

        threading.Thread(target=_fetch, daemon=True).start()

    def _apply_items(self, result: Dict, announce: bool, requested_type: str):
        if requested_type != self.current_tab:
            # User switched tabs while the request was in flight.
            return
        if not result.get('success'):
            speak_notification(result.get('error') or _("Failed to load feedback"), 'error')
            return

        self.items_cache = list(result.get('items') or [])
        self.listbox.Clear()
        # Row 0 is the virtual tab bar — marked with clientData so the screen
        # reader sees just the row text and the navigation logic can detect
        # row 0 as the tab bar (mirrors src.ui.gui.TitanApp).
        self.listbox.Append(self._tab_bar_text(), {'type': 'tab_bar'})
        for item in self.items_cache:
            self.listbox.Append(self._format_row(item), item)

        # Always land on the tab bar row after a refresh (initial open or
        # tab cycle via Left/Right/Ctrl+Tab) — same contract as TitanApp's
        # component views: switching never drops focus onto a real item.
        # That way Left/Right keeps cycling tabs without the user having to
        # arrow-up back to the tab bar after every switch.
        self.listbox.SetSelection(0)
        self.listbox.SetFocus()
        self._last_focus_idx = 0
        self._update_status_bar()

        # No "Tab bar" announcement on refresh — matches TitanApp._cycle_tab_bar:
        # tab cycle (Left/Right or Ctrl+Tab) speaks only the new row text
        # ("Pomysły, 2 z 2") via the screen reader's natural focus read.
        # We deliberately do NOT speak "{tab}: {n} entries" here — the screen
        # reader announces the focused row and the listbox role on focus,
        # which is the user-preferred behaviour. ``announce`` is kept as a
        # parameter so callers can still flag a real semantic change later.

    def _update_status_bar(self):
        label = FEEDBACK_TABS[self._tab_index(self.current_tab)][1]()
        self.SetStatusText(_("{tab}: {n} entries").format(tab=label, n=len(self.items_cache)))

    def _cycle_tab(self, direction: int):
        idx = self._tab_index(self.current_tab)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(FEEDBACK_TABS):
            try:
                play_sound('ui/endoftapbar.ogg')
            except Exception:
                pass
            return
        self.current_tab = FEEDBACK_TABS[new_idx][0]
        try:
            play_sound('ui/switch_list.ogg')
        except Exception:
            pass
        # _apply_items will land on row 0 of the new list. We deliberately do
        # NOT speak "Tab bar" or play ui/tapbar.ogg here — matches
        # TitanApp._cycle_tab_bar: the screen reader's natural focus read of
        # the new row text ("Pomysły, 2 z 2") is the only announcement on
        # tab cycle (Left/Right or Ctrl+Tab).
        self._refresh_items(announce=False)

    # ---- Event handlers ---------------------------------------------------

    def _emit_focus_feedback(self, idx: int) -> None:
        """Play the appropriate focus sound for row ``idx`` and (for the tab
        bar row) speak "Tab bar" via the accessibility helper.

        Mirrors the contract of TitanApp's listbox-view navigation:
            - row 0 (tab bar) -> ui/tapbar.ogg + SR-only "Tab bar"
            - regular row     -> stereo-panned core/FOCUS.ogg
            - rows with upvotes also fire titannet/feedback hub/upwote.ogg
              once per focus change so the user perceives "this entry has
              traction" without any extra TTS.
        """
        item_count = self.listbox.GetCount()
        if self._is_tab_bar_row(idx):
            _announce_tab_bar()
            self._last_focus_idx = idx
            return

        # Stereo pan: 0.0 (left) at the first real entry, 1.0 (right) at the
        # last. With only one real entry the pan stays centred.
        pan = 0.0
        real_count = max(0, item_count - 1)
        if real_count > 1:
            pan = (idx - 1) / (real_count - 1)
        try:
            play_focus_sound(pan=pan)
        except Exception:
            pass

        item_idx = idx - 1
        if 0 <= item_idx < len(self.items_cache):
            item = self.items_cache[item_idx]
            if int(item.get('upvote_count') or 0) > 0 and idx != self._last_focus_idx:
                try:
                    play_sound('titannet/feedback hub/upwote.ogg')
                except Exception:
                    pass
        self._last_focus_idx = idx

    def _on_select(self, event):
        # Mouse / programmatic selection. Keyboard navigation runs through
        # _on_key_hook below — wxListBox.SetSelection() does not fire
        # EVT_LISTBOX on Windows, so the two paths don't double up.
        idx = self.listbox.GetSelection()
        if idx < 0:
            return
        self._emit_focus_feedback(idx)

    def _on_key_hook(self, event: wx.KeyEvent):
        """Frame-level key handler — same contract as ``TitanApp.on_key_down``.

        - Enter activates the focused list item (skips the tab bar row).
        - Escape closes the Feedback Hub and returns to Titan-Net.
        - Left / Right on row 0 (tab bar) cycle Feedback / Ideas tabs.
        - Delete removes the selected entry (author / moderator only).
        - Everything else falls through so wxPython handles arrows and Tab.
        """
        keycode = event.GetKeyCode()
        modifiers = event.GetModifiers()
        focus = self.FindFocus()

        # Escape always returns to Titan-Net (close window).
        if keycode == wx.WXK_ESCAPE and modifiers == wx.MOD_NONE:
            try:
                play_sound('ui/popupclose.ogg')
            except Exception:
                pass
            self.Close()
            return

        # Ctrl+Tab / Ctrl+Shift+Tab cycle the tab bar (matches TitanApp).
        if keycode == wx.WXK_TAB and modifiers == wx.MOD_CONTROL:
            self._cycle_tab(+1)
            return
        if keycode == wx.WXK_TAB and modifiers == (wx.MOD_CONTROL | wx.MOD_SHIFT):
            self._cycle_tab(-1)
            return

        # All listbox-specific keys only fire when the listbox is focused —
        # otherwise text fields and buttons get to keep their normal Enter
        # / arrow behaviour.
        if focus is self.listbox:
            idx = self.listbox.GetSelection()
            item_count = self.listbox.GetCount()

            if keycode in (wx.WXK_LEFT, wx.WXK_RIGHT) and self._is_tab_bar_row(idx):
                self._cycle_tab(-1 if keycode == wx.WXK_LEFT else +1)
                return
            if keycode in (wx.WXK_LEFT, wx.WXK_RIGHT):
                # Left / Right is reserved for the tab bar — swallow on
                # regular rows so it doesn't move focus or selection.
                return
            if keycode in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and not event.AltDown():
                self._on_activate(event)
                return
            if keycode == wx.WXK_DELETE:
                self._delete_selected()
                return

            # Manual UP / DOWN / HOME / END so we can play the same stereo
            # focus sound + end-of-list earcon + "Tab bar" marker as the
            # main TitanApp listbox views (EVT_LISTBOX is unreliable for
            # programmatic SetSelection — Windows in particular doesn't fire
            # it). See gui.py on_listbox_key_down for the same pattern.
            new_idx = idx
            if keycode == wx.WXK_UP:
                new_idx = idx - 1
            elif keycode == wx.WXK_DOWN:
                new_idx = idx + 1
            elif keycode == wx.WXK_HOME:
                new_idx = 0
            elif keycode == wx.WXK_END:
                new_idx = item_count - 1
            else:
                event.Skip()
                return

            if 0 <= new_idx < item_count and new_idx != idx:
                self.listbox.SetSelection(new_idx)
                self._emit_focus_feedback(new_idx)
            else:
                try:
                    play_endoflist_sound()
                except Exception:
                    pass
            return

        event.Skip()

    def _on_activate(self, event):
        idx = self.listbox.GetSelection()
        if idx <= 0:
            return
        item_idx = idx - 1
        if not (0 <= item_idx < len(self.items_cache)):
            return
        item = self.items_cache[item_idx]
        feedback_id = int(item.get('id') or 0)
        if not feedback_id:
            return
        try:
            play_sound('core/SELECT.ogg')
        except Exception:
            pass
        dlg = FeedbackDetailDialog(self, self.titan_client, feedback_id)
        dlg.ShowModal()
        if dlg.deleted:
            self._refresh_items(announce=False)
        dlg.Destroy()

    def _delete_selected(self):
        idx = self.listbox.GetSelection()
        if idx <= 0:
            return
        item = self.items_cache[idx - 1]
        # Delete is permission-checked server-side; this is a quick shortcut
        # for the author / moderators.
        feedback_id = int(item.get('id') or 0)
        title = item.get('title', '?')
        confirm = _show_skinned_message(
            _("Delete '{title}'? This cannot be undone.").format(title=title),
            _("Delete feedback"),
            wx.YES_NO | wx.ICON_WARNING,
        )
        if confirm != wx.YES:
            return

        def _send():
            result = self.titan_client.delete_feedback(feedback_id)
            wx.CallAfter(self._on_delete_result, result, title)

        threading.Thread(target=_send, daemon=True).start()

    def _on_delete_result(self, result: Dict, title: str):
        if not result.get('success'):
            speak_notification(result.get('error') or _("Failed to delete"), 'error')
            return
        speak_notification(_("Deleted: {title}").format(title=title), 'success')
        self._refresh_items(announce=False)

    def _on_new_feedback(self, event):
        try:
            play_sound('core/SELECT.ogg')
        except Exception:
            pass
        default = self.current_tab
        with NewFeedbackDialog(self, default_type=default) as dlg:
            if dlg.ShowModal() != wx.ID_OK or not dlg.result_payload:
                return
            payload = dlg.result_payload

        # Submit on a thread so the UI stays responsive during the upload.
        def _send():
            result = self.titan_client.create_feedback(
                item_type=payload['item_type'],
                title=payload['title'],
                content=payload['content'],
                attachment_data=payload.get('attachment_data'),
                attachment_name=payload.get('attachment_name'),
            )
            wx.CallAfter(self._on_new_result, result, payload['item_type'])

        threading.Thread(target=_send, daemon=True).start()

    def _on_new_result(self, result: Dict, item_type: str):
        if not result.get('success'):
            speak_notification(result.get('error') or _("Failed to send feedback"), 'error')
            return
        # The server will broadcast a feedback_new event, which our callback
        # turns into the new-feedback earcon + announcement. We just refresh
        # the local view so the new entry shows up.
        if item_type != self.current_tab:
            self.current_tab = item_type
        self._refresh_items(announce=True)

    def _on_close(self, event):
        self._restore_callbacks()
        event.Skip()


# ---------------------------------------------------------------------------
# Convenience launcher
# ---------------------------------------------------------------------------

def open_feedback_hub(parent, titan_client) -> Optional[FeedbackHubFrame]:
    """Open the Feedback Hub window. Returns the frame for caller bookkeeping.

    Refuses to open when the client is not connected; emits a screen-reader
    notification in that case.
    """
    if not titan_client or not getattr(titan_client, 'is_connected', False):
        speak_notification(_("You must be connected to Titan-Net"), 'error')
        return None
    frame = FeedbackHubFrame(parent, titan_client)
    frame.Show()
    try:
        from src.ui.window_switcher import register_window
        register_window(_("Titan-Net: Feedback Hub"), window=frame, category='messenger')
    except Exception:
        # window_switcher is optional in some launcher modes
        pass
    return frame

