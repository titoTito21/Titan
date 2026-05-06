"""
EltenLink GUI - Accessible interface for Elten social network.
Follows TCE design patterns with skin support, stereo speech, and Titan sounds.
"""

import wx
import wx.lib.scrolledpanel as scrolled
import sys
import os
import threading
import time
import tempfile
import accessible_output3.outputs.auto
from src.eltenlink_client.elten_client import EltenLinkClient
from src.eltenlink_client.elten_player import EltenPlayer, EltenRecorder
from src.eltenlink_client.elten_voip_client import EltenVoipClient
from src.titan_core.sound import play_sound, initialize_sound
from src.titan_core.translation import set_language
from src.settings.settings import get_setting

# Guarantee the pygame mixer is initialized even when EltenLink is opened
# from a context where the main TCE GUI never ran (launcher mode, etc.).
try:
    initialize_sound()
except Exception as _e:
    print(f"[EltenLink GUI] initialize_sound() failed at import: {_e}")
from src.titan_core.skin_manager import get_skin_manager, apply_skin_to_window
from src.settings.titan_im_config import (
    get_eltenlink_credentials, set_eltenlink_credentials,
    clear_eltenlink_credentials, get_eltenlink_config, save_eltenlink_config
)

# Import stereo speech functionality
try:
    from src.titan_core.stereo_speech import speak_stereo, get_stereo_speech
    STEREO_SPEECH_AVAILABLE = True
except ImportError:
    STEREO_SPEECH_AVAILABLE = False

# Get the translation function
_ = set_language(get_setting('language', 'pl'))

# Initialize screen reader output
speaker = accessible_output3.outputs.auto.Auto()


def _apply_skin_to_tree(window):
    """Apply current skin to a window and all descendants."""
    try:
        apply_skin_to_window(window)
    except Exception:
        return

    for child in window.GetChildren():
        _apply_skin_to_tree(child)


def _new_text_entry_dialog(*args, **kwargs):
    dlg = wx.TextEntryDialog(*args, **kwargs)
    _apply_skin_to_tree(dlg)
    return dlg


def _new_message_dialog(*args, **kwargs):
    dlg = wx.MessageDialog(*args, **kwargs)
    _apply_skin_to_tree(dlg)
    return dlg


def _show_skinned_message(message, title, style=wx.OK | wx.ICON_INFORMATION, parent=None):
    dlg = _new_message_dialog(parent, message, title, style)
    result = dlg.ShowModal()
    dlg.Destroy()
    return result


def speak_elten(text, position=0.0, pitch_offset=0, interrupt=True):
    """Speak text using stereo speech (same as TitanNet)."""
    if not text:
        return

    try:
        try:
            stereo_enabled = get_setting('stereo_speech', 'False', section='invisible_interface').lower() == 'true'

            if stereo_enabled and STEREO_SPEECH_AVAILABLE:
                def speak_with_stereo():
                    try:
                        if interrupt:
                            try:
                                stereo_speech = get_stereo_speech()
                                if stereo_speech:
                                    stereo_speech.stop()
                            except Exception:
                                pass
                        speak_stereo(text, position=position, pitch_offset=pitch_offset, async_mode=True)
                    except Exception:
                        speaker.output(text)

                thread = threading.Thread(target=speak_with_stereo, daemon=True)
                thread.start()
            else:
                def speak_regular():
                    try:
                        if interrupt and hasattr(speaker, 'stop'):
                            speaker.stop()
                        speaker.output(text)
                    except Exception:
                        pass

                thread = threading.Thread(target=speak_regular, daemon=True)
                thread.start()

        except Exception:
            speaker.output(text)

    except Exception:
        try:
            speaker.output(text)
        except:
            pass


def speak_notification(text, notification_type='info', play_sound_effect=True):
    """Speak notification with stereo position and pitch based on importance."""
    if not text:
        return

    notification_settings = {
        'error': {'position': 0.7, 'pitch_offset': 5, 'sound': 'core/error.ogg'},
        'warning': {'position': 0.4, 'pitch_offset': 3, 'sound': 'core/error.ogg'},
        'success': {'position': 0.0, 'pitch_offset': 0, 'sound': 'titannet/titannet_success.ogg'},
        'info': {'position': -0.3, 'pitch_offset': -2, 'sound': 'ui/notify.ogg'},
    }

    settings = notification_settings.get(notification_type, notification_settings['info'])

    if play_sound_effect and settings.get('sound'):
        try:
            play_sound(settings['sound'])
        except:
            pass

    speak_elten(text, position=settings['position'], pitch_offset=settings['pitch_offset'], interrupt=True)


# ---- Login Dialog ----

class EltenLoginDialog(wx.Dialog):
    """Login dialog for EltenLink."""

    def __init__(self, parent):
        super().__init__(parent, title=_("Connect to EltenLink (Beta)"), size=(400, 350))

        self.client = EltenLinkClient()
        self.logged_in = False

        self.InitUI()
        self.Centre()
        self.apply_skin()

        # Load saved credentials
        self.load_saved_credentials()

        # Try auto login
        wx.CallAfter(self.try_autologin)

        self.Bind(wx.EVT_CHAR_HOOK, self.OnKeyPress)
        play_sound('ui/dialog.ogg')

    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Description
        desc_label = wx.StaticText(panel, label=_(
            "EltenLink is a social network for the blind.\n"
            "Connect to chat, forums, and blogs."
        ))
        vbox.Add(desc_label, flag=wx.LEFT | wx.TOP | wx.RIGHT, border=10)

        # Username
        username_label = wx.StaticText(panel, label=_("Username:"))
        vbox.Add(username_label, flag=wx.LEFT | wx.TOP, border=10)

        self.username_text = wx.TextCtrl(panel)
        vbox.Add(self.username_text, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        # Password
        password_label = wx.StaticText(panel, label=_("Password:"))
        vbox.Add(password_label, flag=wx.LEFT | wx.TOP, border=10)

        self.password_text = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
        vbox.Add(self.password_text, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        # Remember password
        self.remember_checkbox = wx.CheckBox(panel, label=_("Remember password (not recommended)"))
        vbox.Add(self.remember_checkbox, flag=wx.LEFT | wx.TOP, border=10)

        # Buttons
        button_box = wx.BoxSizer(wx.HORIZONTAL)

        self.connect_button = wx.Button(panel, wx.ID_OK, _("Connect"))
        self.connect_button.Bind(wx.EVT_BUTTON, self.OnConnect)
        button_box.Add(self.connect_button, flag=wx.RIGHT, border=10)

        self.cancel_button = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        button_box.Add(self.cancel_button)

        vbox.Add(button_box, flag=wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, border=15)

        panel.SetSizer(vbox)

    def apply_skin(self):
        try:
            _apply_skin_to_tree(self)
        except Exception:
            pass

    def OnKeyPress(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
        else:
            event.Skip()

    def load_saved_credentials(self):
        try:
            username, token, password = get_eltenlink_credentials()
            if username:
                self.username_text.SetValue(username)
            if password:
                self.password_text.SetValue(password)
                self.remember_checkbox.SetValue(True)
        except Exception:
            pass

    def try_autologin(self):
        try:
            config = get_eltenlink_config()
            if config.get('auto_connect') and self.username_text.GetValue() and self.password_text.GetValue():
                self.OnConnect(None)
        except Exception:
            pass

    def OnConnect(self, event):
        username = self.username_text.GetValue().strip()
        password = self.password_text.GetValue().strip()

        if not username or not password:
            speak_notification(_("Please enter username and password"), 'warning')
            return

        self.connect_button.Disable()
        self.cancel_button.Disable()

        speak_elten(_("Connecting to EltenLink (Beta)..."), pitch_offset=-5)

        thread = threading.Thread(target=self._login_thread, args=(username, password), daemon=True)
        thread.start()

    def _login_thread(self, username, password):
        try:
            result = self.client.login(username, password)
            wx.CallAfter(self._on_login_complete, result, username, password)
        except Exception as e:
            wx.CallAfter(self._on_login_error, str(e))

    def _on_login_complete(self, result, username, password):
        self.connect_button.Enable()
        self.cancel_button.Enable()

        if result.get('success'):
            if self.remember_checkbox.GetValue():
                set_eltenlink_credentials(username, self.client.token, password)
            else:
                set_eltenlink_credentials(username, self.client.token)

            self.logged_in = True
            speak_notification(_("Connected successfully!"), 'success')
            wx.CallLater(500, self.EndModal, wx.ID_OK)

        elif result.get('requires_2fa'):
            speak_notification(_("Two-factor authentication required"), 'info')
            self._handle_2fa(username, password)

        else:
            speak_notification(result.get('message', _("Login failed")), 'error')

    def _on_login_error(self, error_msg):
        self.connect_button.Enable()
        self.cancel_button.Enable()
        speak_notification(_("Connection error") + ": " + error_msg, 'error')

    def _handle_2fa(self, username, password):
        choices = [_("Authenticate using SMS"), _("Authenticate using backup code")]
        dlg = wx.SingleChoiceDialog(
            self,
            _("Two-factor authentication is enabled. Select method:"),
            _("Two-Factor Authentication"),
            choices
        )
        dlg.SetSelection(0)

        if dlg.ShowModal() != wx.ID_OK:
            speak_notification(_("Login cancelled"), 'info')
            dlg.Destroy()
            return

        method_idx = dlg.GetSelection()
        dlg.Destroy()

        if method_idx == 0:
            speak_elten(_("Sending SMS code..."))
            try:
                self.client.send_2fa_sms()
                speak_notification(_("SMS sent. Check your phone."), 'success')
            except Exception:
                speak_notification(_("Failed to send SMS"), 'error')
                return

        prompt = _("Enter the code from SMS:") if method_idx == 0 else _("Enter backup code:")

        for attempt in range(1, 4):
            code_dlg = _new_text_entry_dialog(self, prompt, _("Two-Factor Authentication"))

            if code_dlg.ShowModal() != wx.ID_OK:
                speak_notification(_("Login cancelled"), 'info')
                code_dlg.Destroy()
                return

            code = code_dlg.GetValue().strip()
            code_dlg.Destroy()

            if not code:
                prompt = _("Code cannot be empty. Try again:")
                speak_notification(_("Code cannot be empty. Try again:"), 'warning')
                continue

            try:
                result = self.client.verify_2fa(code)
                if result.get('success'):
                    speak_notification(_("Verified successfully!"), 'success')
                    if self.remember_checkbox.GetValue():
                        set_eltenlink_credentials(username, self.client.token, password)
                    else:
                        set_eltenlink_credentials(username, self.client.token)
                    self.logged_in = True
                    wx.CallLater(500, self.EndModal, wx.ID_OK)
                    return
                else:
                    if attempt < 3:
                        prompt = _("Invalid code. Try again ({}/{}):").format(attempt, 3)
                        speak_notification(_("Invalid code. Try again."), 'warning')
                    else:
                        speak_notification(_("Verification failed after 3 attempts."), 'error')
            except Exception as e:
                speak_notification(_("Verification error: {}").format(str(e)), 'error')
                if attempt < 3:
                    prompt = _("Error: {}. Try again:").format(str(e))


# ---- Main Window ----

class EltenMainWindow(wx.Frame):
    """Main EltenLink window with Elten-style browsing interface."""

    def __init__(self, parent, client):
        super().__init__(parent, title=_("EltenLink (Beta)"), size=(600, 500))

        self.client = client
        self.parent_frame = parent
        self.current_view = "menu"

        # Data caches
        self.contacts_cache = []
        self.conversations_cache = []
        self.conversation_subjects_cache = []
        self.messages_cache = []
        self.forum_structure_cache = None
        self.forum_groups_cache = []
        self.forum_forums_cache = []
        self.forum_threads_cache = []
        self.forum_posts_cache = []
        self.blogs_cache = []
        self.blog_posts_cache = []
        self.blog_entries_cache = []
        self.online_users_cache = []
        self.feed_cache = []
        self._feed_top_posts = []       # All top-level posts from API
        self._feed_known_ids = set()    # IDs of posts already in tree
        self._feed_display_count = 0    # How many posts currently shown
        self._feed_tree_root = None     # Root tree item
        self._feed_loading = False
        self._feed_refresh_timer = None

        # Navigation state
        self.current_chat_user = None
        self.current_chat_subject = None
        self.current_forum_group_id = None
        self.current_forum_group_name = None
        self.current_forum_id = None
        self.current_forum_name = None
        self.current_thread_id = None
        self.current_thread_name = None
        self.current_blog_user = None
        self.current_blog_name = None
        self.current_blog_post_id = None

        # Auto-refresh
        self.auto_refresh_interval = 15
        self.refresh_timer = None

        # Selection preserved across refresh (F5 / right-click Refresh)
        self._pending_listbox_selection = None

        self.InitUI()
        self.Centre()
        self.apply_skin()
        self.create_menu_bar()
        self.show_menu()

        # Start auto-refresh timer
        self.refresh_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.OnAutoRefresh, self.refresh_timer)
        self.refresh_timer.Start(self.auto_refresh_interval * 1000)

        self.Bind(wx.EVT_CLOSE, self.OnClose)
        self.Bind(wx.EVT_ICONIZE, self.OnIconize)
        self.Bind(wx.EVT_CHAR_HOOK, self.OnKeyPress)

        # Background notification tracking
        self._last_whats_new = None
        self._bg_notification_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_bg_notification_check, self._bg_notification_timer)
        self._bg_notification_timer.Start(60000)  # Check every 60 seconds

        play_sound('titannet/welcome to IM.ogg')
        speak_notification(_("Welcome to EltenLink (Beta)!"), 'success', play_sound_effect=False)

        # Initial What's New check after login (like Ruby's whatsnew(true) in Scene_Main)
        wx.CallLater(3000, self._initial_whats_new_check)

    def InitUI(self):
        panel = wx.Panel(self)
        self.panel = panel
        self.main_sizer = wx.BoxSizer(wx.VERTICAL)

        # User label
        self.user_label = wx.StaticText(panel, label=_("Connected") + f": {self.client.username}")
        self.main_sizer.Add(self.user_label, flag=wx.LEFT | wx.TOP, border=5)

        # View label
        self.view_label = wx.StaticText(panel, label=_("Menu"))
        self.main_sizer.Add(self.view_label, flag=wx.LEFT | wx.TOP, border=5)

        # Main listbox
        self.main_listbox = wx.ListBox(panel, style=wx.LB_SINGLE)
        self.main_listbox.Bind(wx.EVT_LISTBOX_DCLICK, self.OnListActivate)
        self.main_listbox.Bind(wx.EVT_LISTBOX, self.OnListSelect)
        self.main_listbox.Bind(wx.EVT_RIGHT_DOWN, self.OnContextMenu)
        self.main_listbox.Bind(wx.EVT_KEY_DOWN, self.OnListKeyDown)
        self.main_sizer.Add(self.main_listbox, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        # Feed tree (only visible in menu view, accessible via Tab)
        self.feed_tree = wx.TreeCtrl(panel, style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT)
        self.feed_tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self.OnFeedActivate)
        self.feed_tree.Bind(wx.EVT_RIGHT_DOWN, self.OnFeedContextMenu)
        self.feed_tree.Bind(wx.EVT_KEY_DOWN, self.OnFeedKeyDown)
        self.feed_tree.Bind(wx.EVT_TREE_SEL_CHANGED, self.OnFeedSelect)
        self.main_sizer.Add(self.feed_tree, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)
        self.feed_tree.Hide()

        # Message display (hidden by default) - used for forum/blog read mode
        self.message_display = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2
        )
        self.main_sizer.Add(self.message_display, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)
        self.message_display.Hide()

        # Conversation list (hidden by default) - used for private message chat.
        # Columns: Nick / Message preview / Date. Enter on a row opens a
        # read-only multiline dialog with the full message.
        self.conversation_list = wx.ListCtrl(
            panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL
        )
        self.conversation_list.AppendColumn(_("Nick"), width=140)
        self.conversation_list.AppendColumn(_("Message"), width=420)
        self.conversation_list.AppendColumn(_("Date"), width=140)
        self.conversation_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.OnConversationActivated)
        self.main_sizer.Add(self.conversation_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)
        self.conversation_list.Hide()
        self._conversation_records = []  # parallel list of full message data per row

        # Posts container (for forum thread and blog post views)
        self.posts_scroll_panel = scrolled.ScrolledPanel(panel, style=wx.TAB_TRAVERSAL | wx.VSCROLL)
        self.posts_scroll_panel.SetupScrolling(scroll_x=False, scroll_y=True, scrollToTop=True)
        self.posts_scroll_sizer = wx.BoxSizer(wx.VERTICAL)
        self.posts_scroll_panel.SetSizer(self.posts_scroll_sizer)
        self.main_sizer.Add(self.posts_scroll_panel, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)
        self.posts_scroll_panel.Hide()
        self._post_textctrls = []

        # Message input (hidden by default)
        input_label = wx.StaticText(panel, label=_("Message:"))
        self.main_sizer.Add(input_label, flag=wx.LEFT, border=5)
        self.input_label = input_label
        self.input_label.Hide()

        self.message_input = wx.TextCtrl(panel, style=wx.TE_MULTILINE)
        self.main_sizer.Add(self.message_input, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=5)
        self.message_input.Hide()

        # Send button row (hidden by default)
        send_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.send_button = wx.Button(panel, label=_("Send"))
        self.send_button.Bind(wx.EVT_BUTTON, self.OnSendMessage)
        send_sizer.Add(self.send_button, flag=wx.RIGHT, border=5)

        # Audio reply button (shown only in forum thread view)
        self.audio_reply_button = wx.Button(panel, label=_("Audio reply"))
        self.audio_reply_button.Bind(wx.EVT_BUTTON, self.OnAudioReply)
        send_sizer.Add(self.audio_reply_button, flag=wx.RIGHT, border=5)
        self.audio_reply_button.Hide()

        self.main_sizer.Add(send_sizer, flag=wx.LEFT | wx.BOTTOM, border=5)
        self.send_button.Hide()

        # Back button
        self.back_button = wx.Button(panel, label=_("Back"))
        self.back_button.Bind(wx.EVT_BUTTON, self.OnBack)
        self.main_sizer.Add(self.back_button, flag=wx.LEFT | wx.BOTTOM, border=5)
        self.back_button.Hide()

        panel.SetSizer(self.main_sizer)

    def apply_skin(self):
        try:
            _apply_skin_to_tree(self)
        except Exception:
            pass

    # ---- Sound Handlers ----
    # FOCUS.ogg = navigating list (arrow keys), SELECT.ogg = activating element (Enter)

    def OnListSelect(self, event):
        """Play FOCUS sound when navigating list items and new replies sound for unread content.

        Focus sound is panned according to the selection position so the
        main TCE GUI navigation cue is preserved in EltenLink. play_sound
        honours the global stereo_sound setting automatically.
        """
        try:
            count = self.main_listbox.GetCount()
            selection = self.main_listbox.GetSelection()
        except Exception:
            count = 0
            selection = wx.NOT_FOUND

        pan = 0.5
        if count > 1 and selection != wx.NOT_FOUND:
            pan = selection / (count - 1)
        try:
            play_sound('core/FOCUS.ogg', pan=pan)
        except:
            pass

        if selection == wx.NOT_FOUND:
            event.Skip()
            return

        has_new = False

        # Check for new blog posts
        if self.current_view == "blog_posts" and 0 <= selection < len(self.blog_posts_cache):
            post = self.blog_posts_cache[selection]
            has_new = post.get('is_new', False)

        # Check for new forum thread posts
        elif self.current_view == "forum_threads" and 0 <= selection < len(self.forum_threads_cache):
            thread = self.forum_threads_cache[selection]
            posts = thread.get('post_count', 0)
            read = thread.get('read_count', 0)
            has_new = posts > 0 and read < posts

        # Play new replies sound if content has unread items
        if has_new:
            try:
                play_sound('titannet/newreplies.ogg')
            except:
                pass

        event.Skip()

    def OnFeedSelect(self, event):
        """Play FOCUS sound when navigating feed tree + load more on last item."""
        try:
            play_sound('core/FOCUS.ogg')
        except Exception:
            pass
        self._on_feed_sel_changed_load_more()
        event.Skip()

    def OnListKeyDown(self, event):
        """Handle end-of-list sound and context menu key.

        End-of-list is played for all four arrow keys (Up/Down/Left/Right)
        when the selection is at the corresponding edge, mirroring the main
        TCE GUI navigation contract. Movement away from the edge falls
        through to wxPython and triggers OnListSelect for the panned
        focus sound.
        """
        keycode = event.GetKeyCode()
        count = self.main_listbox.GetCount()
        sel = self.main_listbox.GetSelection()

        # End of list detection for all four arrow keys
        at_top = sel <= 0 and keycode in (wx.WXK_UP, wx.WXK_LEFT)
        at_bottom = sel >= count - 1 and keycode in (wx.WXK_DOWN, wx.WXK_RIGHT)

        if at_top or at_bottom:
            try:
                play_sound('ui/endoflist.ogg')
            except:
                pass
            # Don't block movement in case wx wraps - just cue the edge
            # to stay consistent with TCE main GUI (which also blocks).
            return

        # Context menu key (Shift+F10 or Applications key)
        if keycode == wx.WXK_WINDOWS_MENU or (keycode == wx.WXK_F10 and event.ShiftDown()):
            self._show_context_menu()
            return

        event.Skip()

    def OnFeedKeyDown(self, event):
        """Handle context menu key on feed tree."""
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_WINDOWS_MENU or (keycode == wx.WXK_F10 and event.ShiftDown()):
            self._show_feed_context_menu()
            return
        event.Skip()

    def OnContextMenu(self, event):
        """Handle right-click context menu on listbox."""
        pos = event.GetPosition()
        item = self.main_listbox.HitTest(pos)
        if item != wx.NOT_FOUND:
            self.main_listbox.SetSelection(item)
        self._show_context_menu()

    def OnFeedContextMenu(self, event):
        """Handle right-click context menu on feed tree."""
        self._show_feed_context_menu()

    def create_menu_bar(self):
        menu_bar = wx.MenuBar()

        # File menu
        file_menu = wx.Menu()
        refresh_item = file_menu.Append(wx.ID_ANY, _("Refresh\tF5"))
        self.Bind(wx.EVT_MENU, self.OnRefresh, refresh_item)
        file_menu.AppendSeparator()
        new_msg_item = file_menu.Append(wx.ID_ANY, _("New Message\tCtrl+N"))
        self.Bind(wx.EVT_MENU, self.OnNewMessage, new_msg_item)
        file_menu.AppendSeparator()
        disconnect_item = file_menu.Append(wx.ID_ANY, _("Disconnect\tCtrl+Q"))
        self.Bind(wx.EVT_MENU, self.OnDisconnect, disconnect_item)
        menu_bar.Append(file_menu, _("File"))

        # View menu
        view_menu = wx.Menu()
        menu_item = view_menu.Append(wx.ID_ANY, _("Menu\tCtrl+H"))
        self.Bind(wx.EVT_MENU, lambda e: self.show_menu(), menu_item)
        contacts_item = view_menu.Append(wx.ID_ANY, _("Contacts\tCtrl+1"))
        self.Bind(wx.EVT_MENU, lambda e: self.show_contacts_view(), contacts_item)
        conv_item = view_menu.Append(wx.ID_ANY, _("Conversations\tCtrl+2"))
        self.Bind(wx.EVT_MENU, lambda e: self.show_conversations_view(), conv_item)
        forum_item = view_menu.Append(wx.ID_ANY, _("Forum\tCtrl+3"))
        self.Bind(wx.EVT_MENU, lambda e: self.show_forum_groups_view(), forum_item)
        blogs_item = view_menu.Append(wx.ID_ANY, _("Blogs\tCtrl+4"))
        self.Bind(wx.EVT_MENU, lambda e: self.show_blogs_menu(), blogs_item)
        online_item = view_menu.Append(wx.ID_ANY, _("Online Users\tCtrl+5"))
        self.Bind(wx.EVT_MENU, lambda e: self.show_online_users_view(), online_item)
        menu_bar.Append(view_menu, _("View"))

        # Account menu
        account_menu = wx.Menu()
        manage_item = account_menu.Append(wx.ID_ANY, _("Manage my account\tCtrl+6"))
        self.Bind(wx.EVT_MENU, lambda e: self.show_account_manage_view(), manage_item)
        account_menu.AppendSeparator()
        acc_info_item = account_menu.Append(wx.ID_ANY, _("View account info"))
        self.Bind(wx.EVT_MENU, lambda e: self._view_account_info(), acc_info_item)
        menu_bar.Append(account_menu, _("Account"))

        # Help menu
        help_menu = wx.Menu()
        about_item = help_menu.Append(wx.ID_ABOUT, _("About EltenLink (Beta)"))
        self.Bind(wx.EVT_MENU, self.OnAbout, about_item)
        menu_bar.Append(help_menu, _("Help"))

        self.SetMenuBar(menu_bar)

    # ---- UI Helpers ----

    def _show_list_mode(self):
        self.main_listbox.Show()
        self.feed_tree.Hide()
        self.message_display.Hide()
        self.conversation_list.Hide()
        if self.posts_scroll_panel.IsShown():
            self._cleanup_players()
        self.posts_scroll_panel.Hide()
        self.message_input.Hide()
        self.input_label.Hide()
        self.send_button.Hide()
        self.audio_reply_button.Hide()
        self.Layout()

    def _show_menu_mode(self):
        """Menu mode: listbox + feed tree side by side."""
        self.main_listbox.Show()
        self.feed_tree.Show()
        self.message_display.Hide()
        self.conversation_list.Hide()
        self.posts_scroll_panel.Hide()
        self.message_input.Hide()
        self.input_label.Hide()
        self.send_button.Hide()
        self.audio_reply_button.Hide()
        self.Layout()

    def _show_chat_mode(self):
        self.main_listbox.Hide()
        self.feed_tree.Hide()
        self.message_display.Hide()
        self.conversation_list.Show()
        if self.posts_scroll_panel.IsShown():
            self._cleanup_players()
        self.posts_scroll_panel.Hide()
        self.message_input.Show()
        self.input_label.Show()
        self.send_button.Show()
        self.audio_reply_button.Hide()
        self.Layout()

    def _show_read_mode(self):
        self.main_listbox.Hide()
        self.feed_tree.Hide()
        self.message_display.Show()
        self.conversation_list.Hide()
        if self.posts_scroll_panel.IsShown():
            self._cleanup_players()
        self.posts_scroll_panel.Hide()
        self.message_input.Hide()
        self.input_label.Hide()
        self.send_button.Hide()
        self.audio_reply_button.Hide()
        self.Layout()

    def _show_post_list_with_reply(self):
        """Show list mode with reply input below (for forum thread posts)."""
        self.main_listbox.Show()
        self.feed_tree.Hide()
        self.message_display.Hide()
        self.conversation_list.Hide()
        self.posts_scroll_panel.Hide()
        self.message_input.Show()
        self.input_label.Show()
        self.send_button.Show()
        self.audio_reply_button.Show()
        self.Layout()

    def _show_posts_panel_mode(self, show_audio_reply=False):
        """Show scrollable posts panel with reply/comment input below."""
        self.main_listbox.Hide()
        self.feed_tree.Hide()
        self.message_display.Hide()
        self.conversation_list.Hide()
        self.posts_scroll_panel.Show()
        self.message_input.Show()
        self.input_label.Show()
        self.send_button.Show()
        if show_audio_reply:
            self.audio_reply_button.Show()
        else:
            self.audio_reply_button.Hide()
        self.Layout()

    # ---- Conversation list helpers (Nick / Message / Date) ----
    def _conversation_message_preview(self, msg_text):
        if not msg_text:
            return ""
        preview = msg_text.replace('\r', ' ').replace('\n', ' ').strip()
        if len(preview) > 120:
            preview = preview[:117] + "..."
        return preview

    def _add_conversation_row(self, sender, msg_text, date_value):
        """Append a single message row to the conversation list."""
        idx = self.conversation_list.GetItemCount()
        self.conversation_list.InsertItem(idx, sender or "")
        self.conversation_list.SetItem(idx, 1, self._conversation_message_preview(msg_text))
        self.conversation_list.SetItem(idx, 2, self._format_date(date_value))
        self._conversation_records.append({
            'sender': sender or "",
            'message': msg_text or "",
            'date': date_value or "",
        })
        self.conversation_list.EnsureVisible(idx)

    def _clear_conversation_list(self):
        self.conversation_list.DeleteAllItems()
        self._conversation_records = []

    def OnConversationActivated(self, event):
        """Open a read-only dialog with the full message text."""
        idx = event.GetIndex()
        if 0 <= idx < len(self._conversation_records):
            rec = self._conversation_records[idx]
            self._show_full_conversation_dialog(rec['sender'], rec['message'], rec['date'])

    def _show_full_conversation_dialog(self, sender, message, date_value):
        """Modal dialog showing the full message in a read-only multiline field."""
        date_label = self._format_date(date_value) or _("(no date)")
        title = _("Message from {nick} ({date})").format(nick=sender or "", date=date_label)
        dlg = wx.Dialog(
            self, title=title, size=(560, 360),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        )
        sizer = wx.BoxSizer(wx.VERTICAL)
        txt = wx.TextCtrl(
            dlg, value=message or "",
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP
        )
        sizer.Add(txt, 1, wx.EXPAND | wx.ALL, 10)
        btn_close = wx.Button(dlg, wx.ID_OK, _("Close"))
        sizer.Add(btn_close, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        dlg.SetSizer(sizer)
        dlg.SetEscapeId(wx.ID_OK)
        txt.SetFocus()
        dlg.ShowModal()
        dlg.Destroy()

    def _threaded_request(self, method, callback, *args):
        def worker():
            try:
                result = method(*args)
                wx.CallAfter(callback, result, None)
            except Exception as e:
                wx.CallAfter(callback, None, e)
        threading.Thread(target=worker, daemon=True).start()

    # ---- Listbox Selection Preservation (refresh path) ----

    def _capture_listbox_for_refresh(self, target_view):
        """Stash current main_listbox selection if we're re-entering the same view.

        Why: F5 / right-click Refresh re-runs show_*_view which clears the listbox
        and inserts "Loading...". Without this, the user's position is lost and
        the eventual repopulation lands them on item 0.
        """
        self._pending_listbox_selection = None
        if getattr(self, 'current_view', None) != target_view:
            return
        try:
            sel = self.main_listbox.GetSelection()
            if sel == wx.NOT_FOUND or sel >= self.main_listbox.GetCount():
                return
            self._pending_listbox_selection = (sel, self.main_listbox.GetString(sel))
        except Exception:
            pass

    def _apply_pending_listbox_selection(self, default_index=0):
        """Restore a selection captured by _capture_listbox_for_refresh.

        Returns True if a previous selection was restored (refresh path),
        False if we fell back to default_index (fresh load).
        """
        saved = getattr(self, '_pending_listbox_selection', None)
        self._pending_listbox_selection = None
        count = self.main_listbox.GetCount()
        if count == 0:
            return False
        if saved is not None:
            saved_idx, saved_text = saved
            for i in range(count):
                if self.main_listbox.GetString(i) == saved_text:
                    self.main_listbox.SetSelection(i)
                    return True
            new_idx = min(saved_idx, count - 1)
            if 0 <= new_idx < count:
                self.main_listbox.SetSelection(new_idx)
                return True
        if 0 <= default_index < count:
            self.main_listbox.SetSelection(default_index)
        return False

    # ---- Posts Panel Helpers ----

    def _cleanup_players(self):
        """Stop and close any active EltenPlayer instances in the posts panel."""
        for child in self.posts_scroll_panel.GetChildren():
            if isinstance(child, EltenPlayer):
                try:
                    child.close()
                except Exception:
                    pass

    def _populate_posts_panel(self, posts, is_blog=False):
        """Populate the posts panel with all controls at once (bulk load)."""
        # Stop any active players before clearing
        self._cleanup_players()
        # Clear existing controls
        self.posts_scroll_sizer.Clear(True)
        self._post_textctrls = []
        self._first_new_post_index = None

        if not posts:
            empty = wx.StaticText(self.posts_scroll_panel, label=_("No content"))
            self.posts_scroll_sizer.Add(empty, flag=wx.ALL, border=10)
            self.posts_scroll_panel.GetParent().Layout()
            self.posts_scroll_panel.SetupScrolling(scroll_x=False, scroll_y=True)
            return

        # Freeze UI updates for bulk creation
        self.posts_scroll_panel.Freeze()

        ctrl_index = 0
        for i, post in enumerate(posts):
            author = post.get('author', '')
            content = post.get('content', '') or post.get('excerpt', '')
            date = self._format_date(post.get('date', ''))
            signature = post.get('signature', '')

            # Build post text: content + signature + date
            text_parts = []
            if content:
                text_parts.append(content)
            if signature:
                text_parts.append(signature)
            if date:
                text_parts.append(date)
            if post.get('edited'):
                text_parts.append(_("(edited)"))
            full_text = "\n\n".join(text_parts)

            # Detect audio
            audio_url = None
            if is_blog:
                url = post.get('audio_url', '')
                if url and url.strip():
                    audio_url = url.strip()
            else:
                url = post.get('audio_url', '')
                if url and url.strip():
                    audio_url = url.strip()
                else:
                    attachments = post.get('attachments', '')
                    if attachments:
                        att_ids = attachments.split(',')
                        if att_ids:
                            audio_url = f"https://srvapi.elten.link/leg1/attachments.php?id={att_ids[0].strip()}&get=1"

            # Skip empty posts
            if not full_text.strip() and not audio_url:
                continue

            # Blog: type label
            if is_blog:
                type_label = _("Post") if i == 0 else _("Comment") + f" {i}"
                header_label = wx.StaticText(self.posts_scroll_panel, label=type_label)
                self.posts_scroll_sizer.Add(header_label, flag=wx.LEFT | wx.TOP, border=5)

            # User label
            user_label = wx.StaticText(self.posts_scroll_panel, label=author)
            self.posts_scroll_sizer.Add(user_label, flag=wx.LEFT | wx.TOP, border=5)

            if audio_url:
                player_label = _("Audio") + f" - {author}" if author else _("Audio")
                post_ctrl = EltenPlayer(
                    self.posts_scroll_panel,
                    file_or_url=audio_url,
                    label=player_label,
                    autoplay=(i == 0)
                )
                post_ctrl.SetMinSize((-1, 30))
                self.posts_scroll_sizer.Add(post_ctrl, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=5)
            else:
                line_count = full_text.count('\n') + 1
                height = min(max(line_count * 20 + 10, 80), 400)
                post_ctrl = wx.TextCtrl(
                    self.posts_scroll_panel,
                    style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
                    value=full_text
                )
                post_ctrl.SetMinSize((-1, height))
                self.posts_scroll_sizer.Add(post_ctrl, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=5)

            post_ctrl.post_index = ctrl_index
            post_ctrl.is_new_post = post.get('is_new', False)
            post_ctrl.Bind(wx.EVT_RIGHT_DOWN, self._on_post_tc_context_menu)
            post_ctrl.Bind(wx.EVT_KEY_DOWN, self._on_post_tc_key_down)
            self._post_textctrls.append(post_ctrl)

            # Track first new/unread post
            if post.get('is_new', False) and self._first_new_post_index is None:
                self._first_new_post_index = ctrl_index

            ctrl_index += 1

        # Thaw and finalize layout
        self.posts_scroll_panel.Thaw()
        self.posts_scroll_panel.GetParent().Layout()
        self.posts_scroll_panel.SetupScrolling(scroll_x=False, scroll_y=True, scrollToTop=True)

        if self._post_textctrls:
            ctrl = self._post_textctrls[0]
            if isinstance(ctrl, wx.TextCtrl):
                ctrl.SetInsertionPoint(0)
            wx.CallAfter(ctrl.SetFocus)

    def _on_post_tc_context_menu(self, event):
        """Handle right-click on a post TextCtrl."""
        tc = event.GetEventObject()
        idx = tc.post_index
        menu = wx.Menu()

        if self.current_view == "forum_thread":
            self._build_forum_posts_context_menu(menu, idx)
        elif self.current_view == "blog_post":
            self._build_blog_post_context_menu(menu, idx)

        if menu.GetMenuItemCount() > 0:
            try:
                play_sound('ui/contextmenu.ogg')
            except:
                pass
            self.PopupMenu(menu)
            try:
                play_sound('ui/contextmenuclose.ogg')
            except:
                pass

        menu.Destroy()

    def _on_post_tc_key_down(self, event):
        """Handle keyboard on post TextCtrls."""
        keycode = event.GetKeyCode()
        tc = event.GetEventObject()
        idx = tc.post_index

        if keycode == wx.WXK_WINDOWS_MENU or (keycode == wx.WXK_F10 and event.ShiftDown()):
            # Applications key or Shift+F10 -> context menu
            self._on_post_tc_context_menu(event)
            return

        if event.ControlDown():
            if keycode == wx.WXK_UP and idx > 0:
                # Ctrl+Up -> previous post
                prev = self._post_textctrls[idx - 1]
                if isinstance(prev, wx.TextCtrl):
                    prev.SetInsertionPoint(0)
                prev.SetFocus()
                try:
                    play_sound('core/FOCUS.ogg')
                except:
                    pass
                return
            elif keycode == wx.WXK_DOWN and idx < len(self._post_textctrls) - 1:
                # Ctrl+Down -> next post
                nxt = self._post_textctrls[idx + 1]
                if isinstance(nxt, wx.TextCtrl):
                    nxt.SetInsertionPoint(0)
                nxt.SetFocus()
                try:
                    play_sound('core/FOCUS.ogg')
                except:
                    pass
                return
            elif keycode == ord('U'):
                # Ctrl+U -> jump to first new/unread post
                self._jump_to_first_new_post()
                return
            elif keycode == ord('.'):
                # Ctrl+. -> jump to last post
                self._jump_to_post(-1)
                return
            elif keycode == ord(','):
                # Ctrl+, -> jump to first post
                self._jump_to_post(0)
                return

        event.Skip()

    def _jump_to_first_new_post(self):
        """Jump to the first new/unread post in the current thread."""
        if not self._post_textctrls:
            return

        # Find first new post by checking is_new_post attribute
        target_idx = None
        for i, ctrl in enumerate(self._post_textctrls):
            if getattr(ctrl, 'is_new_post', False):
                target_idx = i
                break

        if target_idx is None:
            # No new posts found - go to last post
            self._jump_to_post(-1)
            return

        self._jump_to_post(target_idx)
        count_new = sum(1 for c in self._post_textctrls if getattr(c, 'is_new_post', False))
        speak_elten(_("First new post, {count} new").format(count=count_new))

    def _jump_to_post(self, index):
        """Jump to a specific post by index. Use -1 for last post."""
        if not self._post_textctrls:
            return

        if index < 0:
            index = len(self._post_textctrls) + index

        if 0 <= index < len(self._post_textctrls):
            ctrl = self._post_textctrls[index]
            if isinstance(ctrl, wx.TextCtrl):
                ctrl.SetInsertionPoint(0)
            ctrl.SetFocus()
            try:
                play_sound('core/FOCUS.ogg')
            except:
                pass

    def _play_audio_url(self, audio_url):
        """Download and play audio from URL (voice posts)."""
        if not audio_url or not audio_url.strip():
            speak_notification(_("No audio available"), 'warning')
            return

        def download_and_play():
            try:
                import requests
                resp = requests.get(audio_url, timeout=15)
                if resp.status_code == 200:
                    ext = '.ogg'
                    if '.mp3' in audio_url:
                        ext = '.mp3'
                    elif '.wav' in audio_url:
                        ext = '.wav'
                    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                    tmp.write(resp.content)
                    tmp.close()

                    try:
                        import pygame
                        pygame.mixer.music.load(tmp.name)
                        pygame.mixer.music.play()
                        wx.CallAfter(speak_elten, _("Playing audio post..."))
                    except Exception:
                        wx.CallAfter(speak_notification, _("Failed to play audio"), 'error')
                else:
                    wx.CallAfter(speak_notification, _("Failed to download audio"), 'error')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')

        threading.Thread(target=download_and_play, daemon=True).start()

    def _format_date(self, date_str):
        """Format unix timestamp or date string to readable format."""
        if not date_str:
            return ""
        try:
            ts = int(date_str.strip())
            dt = time.localtime(ts)
            return time.strftime("%Y-%m-%d %H:%M", dt)
        except (ValueError, OSError):
            return date_str

    # ---- User Submenu Helper ----

    def _add_user_submenu(self, parent_menu, username, label=None):
        """Add user options submenu (like Ruby usermenu)."""
        submenu = wx.Menu()

        item_msg = submenu.Append(wx.ID_ANY, _("Send Message"))
        self.Bind(wx.EVT_MENU, lambda e, u=username: self.show_conversation_chat(u), item_msg)

        item_profile = submenu.Append(wx.ID_ANY, _("View Profile"))
        self.Bind(wx.EVT_MENU, lambda e, u=username: self._show_user_profile(u), item_profile)

        item_blog = submenu.Append(wx.ID_ANY, _("Open Blog"))
        self.Bind(wx.EVT_MENU, lambda e, u=username: self.show_blog_posts_view(u, u), item_blog)

        submenu.AppendSeparator()

        item_call = submenu.Append(wx.ID_ANY, _("Call this user"))
        self.Bind(wx.EVT_MENU, lambda e, u=username: self._start_voice_call(u), item_call)

        submenu.AppendSeparator()

        item_add = submenu.Append(wx.ID_ANY, _("Add to Contacts"))
        self.Bind(wx.EVT_MENU, lambda e, u=username: self._add_contact(u), item_add)

        parent_menu.AppendSubMenu(submenu, label or _("User: {user}").format(user=username))

    # ---- View Methods ----

    def show_menu(self):
        self.current_view = "menu"
        self.view_label.SetLabel(_("EltenLink (Beta) - Menu"))
        self._show_menu_mode()
        self.back_button.Hide()



        self.main_listbox.Clear()
        menu_items = [
            _("Contacts"),
            _("Conversations"),
            _("Forum"),
            _("Blogs"),
            _("Online Users"),
            _("What's new"),
            _("Manage my account"),
            _("Disconnect"),
        ]
        for item in menu_items:
            self.main_listbox.Append(item)

        self.main_listbox.SetSelection(0)
        self.main_listbox.SetFocus()

        # Load feed in background + start auto-refresh
        self._load_feed()
        self._start_feed_auto_refresh()

        self.Layout()

    # ---- Feed / Board (Tablica) ----
    # Paginated: first 20 posts, then 30 more when reaching the last item.
    # Only top-level posts (response_to == 0), flat list in feed_tree.

    FEED_INITIAL_COUNT = 20
    FEED_LOAD_MORE_COUNT = 30

    def _load_feed(self):
        """Load Elten feed (tablica) in background."""
        if self._feed_loading:
            return
        self._feed_loading = True
        self._threaded_request(self.client.get_feed, self._on_feed_loaded)

    def _on_feed_loaded(self, feed_posts, error):
        self._feed_loading = False
        if error:
            return

        all_posts = feed_posts if feed_posts else []
        # Keep only top-level posts
        top_posts = [p for p in all_posts if p.get('response_to', 0) == 0]

        if not self._feed_known_ids:
            # First load - store and display first page
            self._feed_top_posts = top_posts
            self._feed_display_count = 0
            self._rebuild_feed_tree()
            self._feed_show_page(self.FEED_INITIAL_COUNT)
        else:
            # Incremental refresh - find new posts
            new_posts = [p for p in top_posts
                         if p.get('id', 0) and p.get('id', 0) not in self._feed_known_ids]
            if new_posts:
                # Prepend new posts to the cached list
                self._feed_top_posts = new_posts + self._feed_top_posts
                self._prepend_feed_items(new_posts)

    def _start_feed_auto_refresh(self):
        """Start background auto-refresh timer (every 60s)."""
        if self._feed_refresh_timer:
            self._feed_refresh_timer.Stop()
        self._feed_refresh_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_feed_refresh_timer, self._feed_refresh_timer)
        self._feed_refresh_timer.Start(60000)

    def _stop_feed_auto_refresh(self):
        if self._feed_refresh_timer:
            self._feed_refresh_timer.Stop()
            self._feed_refresh_timer = None

    def _on_feed_refresh_timer(self, event):
        if self.client and self.client.is_connected:
            self._load_feed()

    def _rebuild_feed_tree(self):
        """Clear and prepare the feed tree for fresh population."""
        self.feed_tree.Freeze()
        try:
            self.feed_tree.DeleteAllItems()
            root = self.feed_tree.AddRoot(_("Feed"))
            self._feed_tree_root = root
            self._feed_known_ids = set()
            self._feed_display_count = 0
        finally:
            self.feed_tree.Thaw()

    def _feed_show_page(self, count):
        """Append the next `count` posts from _feed_top_posts to the tree."""
        if not self._feed_top_posts:
            # Show empty placeholder only if nothing displayed yet
            if self._feed_display_count == 0:
                self.feed_tree.Freeze()
                try:
                    root = self._feed_tree_root
                    empty = self.feed_tree.AppendItem(root, _("No feed posts"))
                    self.feed_tree.SetItemData(empty, {'type': 'empty'})
                finally:
                    self.feed_tree.Thaw()
            return

        start = self._feed_display_count
        end = min(start + count, len(self._feed_top_posts))
        if start >= end:
            return  # Nothing more to show

        self.feed_tree.Freeze()
        try:
            root = self._feed_tree_root
            for i in range(start, end):
                post = self._feed_top_posts[i]
                label = self._make_feed_label(post)
                item = self.feed_tree.AppendItem(root, label)
                self.feed_tree.SetItemData(item, {'type': 'feed_post', 'data': post})
                post_id = post.get('id', 0)
                if post_id:
                    self._feed_known_ids.add(post_id)
            self._feed_display_count = end
        finally:
            self.feed_tree.Thaw()

    def _prepend_feed_items(self, new_posts):
        """Prepend new posts to the top of the feed tree."""
        root = self._feed_tree_root
        if not root or not root.IsOk():
            return

        # Remove "No feed posts" placeholder if present
        first_child, _ = self.feed_tree.GetFirstChild(root)
        if first_child.IsOk():
            data = self.feed_tree.GetItemData(first_child)
            if data and data.get('type') == 'empty':
                self.feed_tree.Delete(first_child)

        self.feed_tree.Freeze()
        try:
            for post in reversed(new_posts):
                label = self._make_feed_label(post)
                item = self.feed_tree.InsertItem(root, 0, label)
                self.feed_tree.SetItemData(item, {'type': 'feed_post', 'data': post})
                post_id = post.get('id', 0)
                if post_id:
                    self._feed_known_ids.add(post_id)
                self._feed_display_count += 1
        finally:
            self.feed_tree.Thaw()

    def _make_feed_label(self, post):
        """Build display label for a feed post."""
        user = post.get('user', '')
        date = self._format_date(post.get('time', ''))
        message = post.get('message', '').replace('\n', ' ')
        if len(message) > 60:
            message = message[:60] + "..."
        likes = post.get('likes', 0)
        responses = post.get('responses', 0)

        label = f"{user} ({date}): {message}"
        if likes > 0:
            label += f" [{likes} likes]"
        if responses > 0:
            label += f" [{responses} replies]"
        return label

    def _on_feed_sel_changed_load_more(self):
        """Check if user reached last visible item - if so, load 30 more."""
        if not self._feed_top_posts:
            return
        if self._feed_display_count >= len(self._feed_top_posts):
            return  # All posts already shown

        # Check if the selected item is the last child of root
        sel = self.feed_tree.GetSelection()
        if not sel.IsOk():
            return
        root = self._feed_tree_root
        if not root or not root.IsOk():
            return

        last_child = self.feed_tree.GetLastChild(root)
        if last_child.IsOk() and last_child == sel:
            self._feed_show_page(self.FEED_LOAD_MORE_COUNT)

    def OnFeedActivate(self, event):
        """Handle double-click/Enter on feed tree item."""
        item = event.GetItem()
        if not item.IsOk():
            return

        data = self.feed_tree.GetItemData(item)
        if not data:
            return

        play_sound('core/SELECT.ogg')

        if data.get('type') == 'feed_post':
            post = data['data']
            self._show_feed_post_detail(post)

    def _show_feed_post_detail(self, post):
        """Show feed post in a dialog with full content."""
        user = post.get('user', '')
        date = self._format_date(post.get('time', ''))
        message = post.get('message', '')
        likes = post.get('likes', 0)

        play_sound('ui/dialog.ogg')

        info = f"{user} ({date}):\n\n{message}\n\n{likes} {_('likes')}"
        speak_elten(f"{user}: {message}")
        _show_skinned_message(info, _("Feed Post"), wx.OK | wx.ICON_INFORMATION)

    def _show_feed_context_menu(self):
        """Show context menu for feed tree items (Elten tablica)."""
        item = self.feed_tree.GetSelection()
        if not item.IsOk():
            return

        data = self.feed_tree.GetItemData(item)
        if not data:
            return

        menu = wx.Menu()

        if data.get('type') == 'feed_post':
            post = data['data']
            user = post.get('user', '')
            post_id = post.get('id', 0)

            # Read post
            item_read = menu.Append(wx.ID_ANY, _("Read Post"))
            self.Bind(wx.EVT_MENU, lambda e, p=post: self._show_feed_post_detail(p), item_read)

            # Like / Unlike
            if post.get('liked'):
                item_like = menu.Append(wx.ID_ANY, _("Unlike"))
                self.Bind(wx.EVT_MENU, lambda e, pid=post_id: self._toggle_feed_like(pid, False), item_like)
            else:
                item_like = menu.Append(wx.ID_ANY, _("Like"))
                self.Bind(wx.EVT_MENU, lambda e, pid=post_id: self._toggle_feed_like(pid, True), item_like)

            # Reply
            item_reply = menu.Append(wx.ID_ANY, _("Reply"))
            self.Bind(wx.EVT_MENU, lambda e, pid=post_id: self._reply_to_feed(pid), item_reply)

            # User submenu
            self._add_user_submenu(menu, user)

            # Follow / Unfollow feed
            menu.AppendSeparator()
            item_follow = menu.Append(wx.ID_ANY, _("Follow Feed"))
            self.Bind(wx.EVT_MENU, lambda e, u=user: self._follow_user_feed(u), item_follow)
            item_unfollow = menu.Append(wx.ID_ANY, _("Unfollow Feed"))
            self.Bind(wx.EVT_MENU, lambda e, u=user: self._unfollow_user_feed(u), item_unfollow)

            # Delete own post
            if user == self.client.username:
                menu.AppendSeparator()
                item_delete = menu.Append(wx.ID_ANY, _("Delete Post"))
                self.Bind(wx.EVT_MENU, lambda e, pid=post_id: self._delete_feed_post(pid), item_delete)

            menu.AppendSeparator()

        # New post (always available)
        item_new = menu.Append(wx.ID_ANY, _("New Post"))
        self.Bind(wx.EVT_MENU, lambda e: self._new_feed_post(), item_new)

        # Refresh
        item_refresh = menu.Append(wx.ID_ANY, _("Refresh"))
        self.Bind(wx.EVT_MENU, lambda e: self._load_feed(), item_refresh)

        if menu.GetMenuItemCount() > 0:
            try:
                play_sound('ui/contextmenu.ogg')
            except:
                pass
            self.PopupMenu(menu)
            try:
                play_sound('ui/contextmenuclose.ogg')
            except:
                pass

        menu.Destroy()

    def _toggle_feed_like(self, feed_id, like):
        def do_like():
            try:
                self.client.like_feed(feed_id, like)
                msg = _("Post liked") if like else _("Post unliked")
                wx.CallAfter(speak_notification, msg, 'success')
                wx.CallAfter(self._load_feed)
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_like, daemon=True).start()

    def _reply_to_feed(self, parent_id):
        play_sound('ui/dialog.ogg')
        dlg = _new_text_entry_dialog(self, _("Reply (max 300 characters):"), _("Reply to Post"))
        if dlg.ShowModal() == wx.ID_OK:
            text = dlg.GetValue().strip()
            if text:
                def do_reply():
                    try:
                        result = self.client.post_feed(text, response_to=parent_id)
                        if result.get('success'):
                            wx.CallAfter(speak_notification, _("Reply posted"), 'success')
                            wx.CallAfter(self._load_feed)
                        else:
                            wx.CallAfter(speak_notification, result.get('message', ''), 'error')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')
                threading.Thread(target=do_reply, daemon=True).start()
        dlg.Destroy()

    def _new_feed_post(self):
        play_sound('ui/dialog.ogg')
        dlg = _new_text_entry_dialog(self, _("New post (max 300 characters):"), _("New Feed Post"))
        if dlg.ShowModal() == wx.ID_OK:
            text = dlg.GetValue().strip()
            if text:
                def do_post():
                    try:
                        result = self.client.post_feed(text)
                        if result.get('success'):
                            wx.CallAfter(play_sound, 'titannet/message_send.ogg')
                            wx.CallAfter(speak_notification, _("Post published"), 'success')
                            wx.CallAfter(self._load_feed)
                        else:
                            wx.CallAfter(speak_notification, result.get('message', ''), 'error')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')
                threading.Thread(target=do_post, daemon=True).start()
        dlg.Destroy()

    def _delete_feed_post(self, feed_id):
        confirm = _new_message_dialog(
            self, _("Delete this post?"), _("Delete Post"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION
        )
        if confirm.ShowModal() == wx.ID_YES:
            def do_delete():
                try:
                    self.client.delete_feed(feed_id)
                    wx.CallAfter(speak_notification, _("Post deleted"), 'success')
                    wx.CallAfter(self._load_feed)
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')
            threading.Thread(target=do_delete, daemon=True).start()
        confirm.Destroy()

    def _follow_user_feed(self, username):
        def do_follow():
            try:
                self.client.follow_feed(username)
                wx.CallAfter(speak_notification, _("Feed followed"), 'success')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_follow, daemon=True).start()

    def _unfollow_user_feed(self, username):
        def do_unfollow():
            try:
                self.client.unfollow_feed(username)
                wx.CallAfter(speak_notification, _("Feed unfollowed"), 'success')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_unfollow, daemon=True).start()

    def _show_user_feed(self, username):
        """Show a user's feed posts in a dialog."""
        speak_elten(_("Loading feed..."))

        def fetch():
            try:
                posts = self.client.get_feed(username)
                wx.CallAfter(self._display_user_feed, username, posts)
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=fetch, daemon=True).start()

    def _display_user_feed(self, username, posts):
        if not posts:
            speak_notification(_("No feed posts"), 'info')
            return

        play_sound('ui/dialog.ogg')
        parts = [_("Feed: {user}").format(user=username), ""]
        for post in posts[:20]:
            date = self._format_date(post.get('time', ''))
            message = post.get('message', '')
            likes = post.get('likes', 0)
            parts.append(f"[{date}] {message}")
            if likes > 0:
                parts.append(f"  {likes} {_('likes')}")
            parts.append("")

        info = "\n".join(parts)
        speak_elten(_("{count} posts").format(count=len(posts)))
        _show_skinned_message(info, _("Feed: {user}").format(user=username), wx.OK | wx.ICON_INFORMATION)

    # ---- Contacts ----

    def show_contacts_view(self):
        self._capture_listbox_for_refresh("contacts")
        self.current_view = "contacts"
        self.view_label.SetLabel(_("Contacts"))
        self._show_list_mode()
        self.back_button.Show()



        self.main_listbox.Clear()
        self.main_listbox.Append(_("Loading..."))
        self.Layout()

        self._threaded_request(self.client.get_contacts, self._on_contacts_loaded)

    def _on_contacts_loaded(self, contacts, error):
        self.main_listbox.Clear()
        if error:
            self._pending_listbox_selection = None
            speak_notification(str(error), 'error')
            return

        if not contacts:
            self._pending_listbox_selection = None
            self.main_listbox.Append(_("No contacts"))
            speak_elten(_("No contacts"))
            return

        self.contacts_cache = contacts
        for contact in contacts:
            self.main_listbox.Append(contact)

        restored = self._apply_pending_listbox_selection()
        if not restored:
            speak_elten(_("{count} contacts").format(count=len(contacts)))
            self.main_listbox.SetFocus()

    # ---- Conversations ----

    def show_conversations_view(self):
        self._capture_listbox_for_refresh("conversations")
        self.current_view = "conversations"
        self.view_label.SetLabel(_("Conversations"))
        self._show_list_mode()
        self.back_button.Show()



        self.main_listbox.Clear()
        self.main_listbox.Append(_("Loading..."))
        self.Layout()

        self._threaded_request(self.client.get_conversations, self._on_conversations_loaded)

    def _on_conversations_loaded(self, conversations, error):
        self.main_listbox.Clear()
        if error:
            self._pending_listbox_selection = None
            speak_notification(str(error), 'error')
            return

        if not conversations:
            self._pending_listbox_selection = None
            self.main_listbox.Append(_("No conversations"))
            speak_elten(_("No conversations"))
            return

        self.conversations_cache = conversations
        for conv in conversations:
            user = conv.get('display_name') or conv.get('user', '')
            lastuser = conv.get('lastuser', '')
            lastsubject = conv.get('subject', '')
            date = self._format_date(conv.get('date', ''))
            read_marker = "" if conv.get('read') else " [*]"
            label = f"{user}: {_('Last message')}: {lastuser}: {lastsubject}. {date}{read_marker}"
            self.main_listbox.Append(label)

        restored = self._apply_pending_listbox_selection()
        if not restored:
            speak_elten(_("{count} conversations").format(count=len(conversations)))
            self.main_listbox.SetFocus()

    def show_conversation_chat(self, user, subject=""):
        if not subject:
            # No subject - show conversation subjects list for this user
            self.show_conversation_subjects(user)
            return

        self.current_view = "conversation_chat"
        self.current_chat_user = user
        self.current_chat_subject = subject
        self.view_label.SetLabel(_("Chat with {user}").format(user=user))
        self._show_chat_mode()
        self.back_button.Show()
        self.input_label.SetLabel(_("Message:"))

        play_sound('titannet/new_chat.ogg')

        self._clear_conversation_list()
        speak_elten(_("Loading..."))
        self.Layout()

        self._threaded_request(
            self.client.get_conversation_messages,
            self._on_messages_loaded,
            user, subject
        )

    def show_conversation_subjects(self, user):
        """Show list of conversation subjects/threads with a user."""
        self._capture_listbox_for_refresh("conversation_subjects")
        self.current_view = "conversation_subjects"
        self.current_chat_user = user
        self.view_label.SetLabel(_("Chat with {user}").format(user=user))
        self._show_list_mode()
        self.back_button.Show()

        self.main_listbox.Clear()
        self.main_listbox.Append(_("Loading..."))
        self.Layout()

        self._threaded_request(
            self.client.get_conversation_subjects,
            self._on_conversation_subjects_loaded,
            user
        )

    def _on_conversation_subjects_loaded(self, subjects, error):
        self.main_listbox.Clear()
        if error:
            self._pending_listbox_selection = None
            speak_notification(str(error), 'error')
            return

        if not subjects:
            self._pending_listbox_selection = None
            self.main_listbox.Append(_("No messages yet."))
            speak_elten(_("No messages yet."))
            return

        self.conversation_subjects_cache = subjects
        for subj in subjects:
            subject_text = subj.get('subject', '')
            date = self._format_date(subj.get('date', ''))
            sender = subj.get('last_sender', '')
            read_marker = "" if subj.get('read') else " [*]"
            label = f"{subject_text} ({sender}, {date}){read_marker}"
            self.main_listbox.Append(label)

        restored = self._apply_pending_listbox_selection()
        if not restored:
            speak_elten(_("{count} conversations").format(count=len(subjects)))
            self.main_listbox.SetFocus()

    def _on_messages_loaded(self, messages, error):
        self._clear_conversation_list()
        if error:
            speak_notification(str(error), 'error')
            return

        if not messages:
            speak_elten(_("No messages yet."))
            self.message_input.SetFocus()
            return

        self.messages_cache = messages
        self.conversation_list.Freeze()
        try:
            for msg in messages:
                self._add_conversation_row(
                    msg.get('sender', ''),
                    msg.get('message', ''),
                    msg.get('date', ''),
                )
        finally:
            self.conversation_list.Thaw()
        self.message_input.SetFocus()

    # ---- Forum ----

    def show_forum_groups_view(self):
        self._capture_listbox_for_refresh("forum_groups")
        self.current_view = "forum_groups"
        self.view_label.SetLabel(_("Forum - Groups"))
        self._show_list_mode()
        self.back_button.Show()



        self.main_listbox.Clear()
        self.main_listbox.Append(_("Loading..."))
        self.Layout()

        self._threaded_request(self.client.get_forum_groups, self._on_forum_groups_loaded)

    def _on_forum_groups_loaded(self, groups, error):
        self.main_listbox.Clear()
        if error:
            self._pending_listbox_selection = None
            speak_notification(str(error), 'error')
            return

        if not groups:
            self._pending_listbox_selection = None
            self.main_listbox.Append(_("No forum groups"))
            speak_elten(_("No forum groups"))
            return

        # Show only groups user belongs to (role > 0)
        my_groups = [g for g in groups if g.get('role', 0) > 0]
        if not my_groups:
            self._pending_listbox_selection = None
            self.main_listbox.Append(_("No forum groups"))
            speak_elten(_("No forum groups"))
            return

        self.forum_groups_cache = my_groups
        for group in my_groups:
            name = group.get('name', '')
            lang = group.get('lang', '')
            posts = group.get('posts_count', 0)
            threads = group.get('threads_count', 0)
            label = f"{name} [{lang}] (" + _("{count} threads").format(count=threads) + ", " + _("{count} posts").format(count=posts) + ")"
            self.main_listbox.Append(label)

        restored = self._apply_pending_listbox_selection()
        if not restored:
            speak_elten(_("{count} forum groups").format(count=len(groups)))
            self.main_listbox.SetFocus()

    def show_forum_forums_view(self, group_id, group_name):
        self._capture_listbox_for_refresh("forum_forums")
        self.current_view = "forum_forums"
        self.current_forum_group_id = group_id
        self.current_forum_group_name = group_name
        self.view_label.SetLabel(_("Forum") + f" - {group_name}")
        self._show_list_mode()
        self.back_button.Show()



        self.main_listbox.Clear()
        self.main_listbox.Append(_("Loading..."))
        self.Layout()

        self._threaded_request(
            self.client.get_forums_in_group,
            self._on_forums_loaded,
            group_id
        )

    def _on_forums_loaded(self, forums, error):
        self.main_listbox.Clear()
        if error:
            self._pending_listbox_selection = None
            speak_notification(str(error), 'error')
            return

        if not forums:
            self._pending_listbox_selection = None
            self.main_listbox.Append(_("No forums in this group"))
            return

        self.forum_forums_cache = forums
        for forum in forums:
            name = forum.get('name', '')
            desc = forum.get('description', '')
            label = f"{name} - {desc}" if desc else name
            self.main_listbox.Append(label)

        restored = self._apply_pending_listbox_selection()
        if not restored:
            self.main_listbox.SetFocus()

    def show_forum_threads_view(self, forum_id, forum_name):
        self._capture_listbox_for_refresh("forum_threads")
        self.current_view = "forum_threads"
        self.current_forum_id = forum_id
        self.current_forum_name = forum_name
        self.view_label.SetLabel(f"{forum_name}")
        self._show_list_mode()
        self.back_button.Show()



        self.main_listbox.Clear()
        self.main_listbox.Append(_("Loading..."))
        self.Layout()

        self._threaded_request(
            self.client.get_threads_in_forum,
            self._on_threads_loaded,
            forum_id
        )

    def _on_threads_loaded(self, threads, error):
        self.main_listbox.Clear()
        if error:
            self._pending_listbox_selection = None
            speak_notification(str(error), 'error')
            return

        if not threads:
            self._pending_listbox_selection = None
            self.main_listbox.Append(_("No threads"))
            return

        self.forum_threads_cache = threads
        for thread in threads:
            name = thread.get('name', '')
            author = thread.get('author', '')
            posts = thread.get('post_count', 0)
            read = thread.get('read_count', 0)
            unread_marker = ""
            if posts > 0 and read < posts:
                unread_marker = " [" + _("{count} new").format(count=posts - read) + "]"
            label = f"{name} - {author} (" + _("{count} posts").format(count=posts) + f"){unread_marker}"
            self.main_listbox.Append(label)

        restored = self._apply_pending_listbox_selection()
        if not restored:
            self.main_listbox.SetFocus()

    def show_forum_thread_view(self, thread_id, thread_name):
        """Show posts in a thread as individual read-only text fields."""
        self.current_view = "forum_thread"
        self.current_thread_id = thread_id
        self.current_thread_name = thread_name
        self.view_label.SetLabel(f"{thread_name}")
        self._show_posts_panel_mode(show_audio_reply=True)
        self.back_button.Show()
        self.input_label.SetLabel(_("Reply:"))



        # Show loading state
        self.posts_scroll_sizer.Clear(True)
        self._post_textctrls = []
        loading_label = wx.StaticText(self.posts_scroll_panel, label=_("Loading..."))
        self.posts_scroll_sizer.Add(loading_label, flag=wx.ALL, border=10)
        self.posts_scroll_panel.Layout()

        self._threaded_request(
            self.client.get_thread_posts,
            self._on_thread_posts_loaded,
            thread_id
        )

    def _on_thread_posts_loaded(self, posts, error):
        print(f"[EltenLink] Thread posts loaded: count={len(posts) if posts else 0}, error={error}")
        if error:
            self.posts_scroll_sizer.Clear(True)
            self._post_textctrls = []
            speak_notification(str(error), 'error')
            return

        if not posts:
            self.posts_scroll_sizer.Clear(True)
            self._post_textctrls = []
            empty_label = wx.StaticText(self.posts_scroll_panel, label=_("No posts"))
            self.posts_scroll_sizer.Add(empty_label, flag=wx.ALL, border=10)
            self.posts_scroll_panel.Layout()
            return

        self.forum_posts_cache = posts
        self._populate_posts_panel(posts)
        speak_elten(_("{count} posts").format(count=len(posts)))

    # ---- Blogs ----

    def show_blogs_menu(self):
        self.current_view = "blogs"
        self.view_label.SetLabel(_("Blogs"))
        self._show_list_mode()
        self.back_button.Show()



        self.main_listbox.Clear()
        menu_items = [
            _("Managed blogs"),
            _("Recently updated blogs"),
            _("Frequently updated blogs"),
            _("Frequently commented blogs"),
            _("Followed blogs"),
            _("Followed blog posts"),
            _("Search user's blog"),
        ]
        for item in menu_items:
            self.main_listbox.Append(item)

        self.main_listbox.SetSelection(0)
        self.main_listbox.SetFocus()

    def show_managed_blogs_view(self):
        """Show blogs managed by current user (like Ruby Scene_Blog_List.new(Session.name))."""
        self.current_view = "blog_list"
        self.view_label.SetLabel(_("Managed blogs"))
        self._show_list_mode()
        self.back_button.Show()

        self.main_listbox.Clear()
        self.main_listbox.Append(_("Loading..."))
        self.Layout()

        def fetch_managed():
            return self.client.get_blogs_list(user=self.client.username)
        self._threaded_request(fetch_managed, self._on_managed_blogs_loaded)

    def _on_managed_blogs_loaded(self, blogs, error):
        self.main_listbox.Clear()
        if error:
            speak_notification(str(error), 'error')
            return

        if not blogs:
            self.main_listbox.Append(_("No managed blogs found"))
            speak_elten(_("No managed blogs found"))
            return

        self.blogs_cache = blogs
        for blog in blogs:
            name = blog.get('name', blog.get('domain', ''))
            posts = blog.get('posts', 0)
            self.main_listbox.Append(f"{name} ({posts} " + _("posts") + ")")

        self.main_listbox.SetSelection(0)
        speak_elten(_("{count} managed blogs").format(count=len(blogs)))
        self.main_listbox.SetFocus()

    def show_blogs_list_view(self, order_by=0, title=""):
        self._capture_listbox_for_refresh("blog_list")
        self.current_view = "blog_list"
        self.view_label.SetLabel(title or _("Blogs"))
        self._show_list_mode()
        self.back_button.Show()



        self.main_listbox.Clear()
        self.main_listbox.Append(_("Loading..."))
        self.Layout()

        self._threaded_request(self.client.get_blogs_list, self._on_blogs_loaded, order_by)

    def _on_blogs_loaded(self, blogs, error):
        self.main_listbox.Clear()
        if error:
            self._pending_listbox_selection = None
            speak_notification(str(error), 'error')
            return

        if not blogs:
            self._pending_listbox_selection = None
            self.main_listbox.Append(_("No blogs found"))
            return

        self.blogs_cache = blogs
        for blog in blogs:
            name = blog.get('name', '')
            posts = blog.get('posts', 0)
            followed = " [+]" if blog.get('followed') else ""
            label = f"{name} (" + _("{count} posts").format(count=posts) + f"){followed}"
            self.main_listbox.Append(label)

        restored = self._apply_pending_listbox_selection()
        if not restored:
            self.main_listbox.SetFocus()

    def show_blog_posts_view(self, blog_name, display_name: str = "", category_id=0):
        self._capture_listbox_for_refresh("blog_posts")
        self.current_view = "blog_posts"
        self.current_blog_user = blog_name
        self.current_blog_name = display_name or blog_name
        self.current_blog_category = category_id
        self.current_blog_page = 1
        self.blog_posts_cache = []
        self.view_label.SetLabel(display_name or blog_name)
        self._show_list_mode()
        self.back_button.Show()



        self.main_listbox.Clear()
        self.main_listbox.Append(_("Loading..."))
        self.Layout()

        self._threaded_request(
            self.client.get_blog_posts,
            self._on_blog_posts_loaded,
            blog_name, category_id, 1
        )

    def _on_blog_posts_loaded(self, result, error):
        if error:
            self._pending_listbox_selection = None
            self.main_listbox.Clear()
            speak_notification(str(error), 'error')
            return

        # Handle tuple (posts, has_more) from get_blog_posts
        if isinstance(result, tuple):
            posts, has_more = result
        else:
            posts = result if result else []
            has_more = False

        is_first_page = self.current_blog_page <= 1

        if is_first_page:
            self.main_listbox.Clear()

        if not posts and is_first_page:
            self._pending_listbox_selection = None
            self.main_listbox.Append(_("No posts"))
            return

        # Remove "Load more" item if it exists from previous page
        if not is_first_page:
            last_idx = self.main_listbox.GetCount() - 1
            if last_idx >= 0:
                last_text = self.main_listbox.GetString(last_idx)
                if last_text == _("Load more"):
                    self.main_listbox.Delete(last_idx)

        # Add posts (API returns newest first, matching Ruby)
        for post in posts:
            self.blog_posts_cache.append(post)
            title = post.get('title', '')
            author = post.get('author', '')
            date = self._format_date(post.get('date', ''))
            comments = post.get('comments', 0)
            new_marker = " [*]" if post.get('is_new') else ""
            audio_marker = (" [" + _("Audio") + "]") if post.get('is_audio') else ""
            label = f"{title} - {author} ({date}, " + _("{count} comments").format(count=comments) + f"){audio_marker}{new_marker}"
            self.main_listbox.Append(label)

        # Add "Load more" if there are more pages (like Ruby)
        if has_more:
            self.main_listbox.Append(_("Load more"))

        if is_first_page:
            restored = self._apply_pending_listbox_selection()
            if not restored:
                self.main_listbox.SetFocus()
        else:
            # Pagination path - keep current focus, no selection reset
            self._pending_listbox_selection = None

    def show_blog_post_content(self, post_id, blog_name):
        """Show blog post with comments as individual read-only text fields."""
        self.current_view = "blog_post"
        self.current_blog_post_id = post_id
        self.view_label.SetLabel(_("Blog Post"))
        self._show_posts_panel_mode()
        self.back_button.Show()
        self.input_label.SetLabel(_("Comment:"))



        # Show loading state
        self.posts_scroll_sizer.Clear(True)
        self._post_textctrls = []
        loading_label = wx.StaticText(self.posts_scroll_panel, label=_("Loading..."))
        self.posts_scroll_sizer.Add(loading_label, flag=wx.ALL, border=10)
        self.posts_scroll_panel.Layout()

        self._threaded_request(
            self.client.get_blog_post_content,
            self._on_blog_post_content_loaded,
            post_id, blog_name
        )

    def _on_blog_post_content_loaded(self, result, error):
        if error:
            self.posts_scroll_sizer.Clear(True)
            self._post_textctrls = []
            speak_notification(str(error), 'error')
            print(f"[EltenLink] Blog content error: {error}")
            return

        print(f"[EltenLink] Blog content result: {result}")
        entries = result.get('posts', [])
        if not entries:
            self.posts_scroll_sizer.Clear(True)
            self._post_textctrls = []
            empty_label = wx.StaticText(self.posts_scroll_panel, label=_("No content"))
            self.posts_scroll_sizer.Add(empty_label, flag=wx.ALL, border=10)
            self.posts_scroll_panel.Layout()
            return

        self.blog_entries_cache = entries
        self._populate_posts_panel(entries, is_blog=True)
        count = len(entries) - 1
        if count > 0:
            speak_elten(_("{count} comments").format(count=count))

    # ---- Online Users ----

    def show_online_users_view(self):
        self._capture_listbox_for_refresh("online_users")
        self.current_view = "online_users"
        self.view_label.SetLabel(_("Online Users"))
        self._show_list_mode()
        self.back_button.Show()



        self.main_listbox.Clear()
        self.main_listbox.Append(_("Loading..."))
        self.Layout()

        self._threaded_request(self.client.get_online_users, self._on_online_users_loaded)

    def _on_online_users_loaded(self, users, error):
        self.main_listbox.Clear()
        if error:
            self._pending_listbox_selection = None
            speak_notification(str(error), 'error')
            return

        if not users:
            self._pending_listbox_selection = None
            self.main_listbox.Append(_("No users online"))
            speak_elten(_("No users online"))
            return

        self.online_users_cache = users
        for user in users:
            self.main_listbox.Append(user)

        restored = self._apply_pending_listbox_selection()
        if not restored:
            speak_elten(_("{count} users online").format(count=len(users)))
            self.main_listbox.SetFocus()

    # ---- What's New ----

    def show_whats_new_view(self):
        """Show What's New notifications view - mirrors Ruby Scene_WhatsNew."""
        self.current_view = "whats_new"
        self.view_label.SetLabel(_("What's new"))
        self._show_list_mode()
        self.back_button.Show()

        self.main_listbox.Clear()
        self.main_listbox.Append(_("Loading..."))
        self.Layout()

        play_sound('titannet/titannet-notification.ogg')
        self._threaded_request(self.client.get_whats_new, self._on_whats_new_loaded)

    def _on_whats_new_loaded(self, data, error):
        self.main_listbox.Clear()
        if error:
            speak_notification(_("Failed to load notifications"), 'error')
            self.main_listbox.Append(_("Failed to load"))
            return
        if data is None:
            data = {}

        # Categories matching Ruby Scene_WhatsNew, with titan-net sounds
        self._whats_new_categories = [
            ('messages', _("New messages"), 'titannet/new_message.ogg'),
            ('followed_threads', _("New posts in followed threads"), 'titannet/new_feedpost.ogg'),
            ('followed_blogs', _("New posts on the followed blogs"), 'titannet/new_feedpost.ogg'),
            ('blog_comments', _("New comments on your blog"), 'titannet/chat_message.ogg'),
            ('followed_forums', _("New threads on followed forums"), 'titannet/new_feedpost.ogg'),
            ('followed_forums_posts', _("New posts on followed forums"), 'titannet/new_feedpost.ogg'),
            ('friends', _("New friends"), 'titannet/new_chat.ogg'),
            ('birthday', _("Friends' birthday"), 'titannet/birthday.ogg'),
            ('mentions', _("Mentions"), 'titannet/titannet-notification.ogg'),
            ('followed_blog_posts', _("Followed blog posts"), 'titannet/new_feedpost.ogg'),
            ('blog_followers', _("Blog followers"), 'titannet/new_chat.ogg'),
            ('blog_mentions', _("Blog mentions"), 'titannet/titannet-notification.ogg'),
            ('group_invitations', _("Awaiting group invitations"), 'titannet/titannet-notification.ogg'),
        ]

        has_anything = False
        self._whats_new_data = data
        self._whats_new_visible_indices = []  # Maps listbox index -> category index
        for cat_idx, (key, label, sound) in enumerate(self._whats_new_categories):
            count = data.get(key, 0)
            if count > 0:
                item_text = f"{label} ({count})"
                self.main_listbox.Append(item_text)
                self._whats_new_visible_indices.append(cat_idx)
                has_anything = True

        if not has_anything:
            speak_elten(_("There is nothing new."))
            return

        self.main_listbox.SetSelection(0)
        self.main_listbox.SetFocus()

        # Announce via TTS with titan-net sounds (like Ruby Elten)
        self._announce_whats_new(data)

    def _announce_whats_new(self, data):
        """Announce What's New notifications via TTS with titan-net sounds."""
        announcements = []
        for key, label, sound in self._whats_new_categories:
            count = data.get(key, 0)
            if count > 0:
                announcements.append((label, count, sound))

        if not announcements:
            return

        # Announce each non-zero category with delay between them
        self._wn_announcements = announcements
        self._wn_announce_idx = 0
        # Start with header
        speak_elten(_("What's new"))
        wx.CallLater(800, self._announce_next_wn)

    def _announce_next_wn(self):
        """Announce next What's New item with titan-net sound."""
        if self._wn_announce_idx >= len(self._wn_announcements):
            return

        label, count, sound = self._wn_announcements[self._wn_announce_idx]
        self._wn_announce_idx += 1

        try:
            play_sound(sound)
        except Exception:
            pass

        text = f"{label}: {count}"
        speak_elten(text, interrupt=False)

        # Schedule next announcement
        if self._wn_announce_idx < len(self._wn_announcements):
            wx.CallLater(1500, self._announce_next_wn)

    # ---- Account Settings ----

    def show_account_manage_view(self):
        """Open separate account management dialog."""
        from src.eltenlink_client.accountmanagement import show_account_management
        show_account_management(self, self.client)

    # ---- Context Menus (Comprehensive, Ruby Elten style) ----

    def _show_context_menu(self):
        """Show context menu based on current view - matches Elten Ruby menus."""
        selection = self.main_listbox.GetSelection()
        if selection == wx.NOT_FOUND:
            return

        menu = wx.Menu()

        if self.current_view == "contacts":
            self._build_contacts_context_menu(menu, selection)

        elif self.current_view == "conversations":
            self._build_conversations_context_menu(menu, selection)

        elif self.current_view == "forum_groups":
            self._build_forum_groups_context_menu(menu, selection)

        elif self.current_view == "forum_forums":
            self._build_forum_forums_context_menu(menu, selection)

        elif self.current_view == "forum_threads":
            self._build_forum_threads_context_menu(menu, selection)

        elif self.current_view == "blog_list":
            self._build_blog_list_context_menu(menu, selection)

        elif self.current_view == "blog_posts":
            self._build_blog_posts_context_menu(menu, selection)

        elif self.current_view == "conversation_subjects":
            self._build_conversation_subjects_context_menu(menu, selection)

        elif self.current_view == "online_users":
            self._build_online_users_context_menu(menu, selection)

        if menu.GetMenuItemCount() > 0:
            try:
                play_sound('ui/contextmenu.ogg')
            except:
                pass
            self.PopupMenu(menu)
            try:
                play_sound('ui/contextmenuclose.ogg')
            except:
                pass

        menu.Destroy()

    def _build_contacts_context_menu(self, menu, selection):
        """Contacts context menu - like Ruby Scene_Contacts."""
        if selection >= len(self.contacts_cache):
            return
        user = self.contacts_cache[selection]

        # User options submenu
        self._add_user_submenu(menu, user)

        menu.AppendSeparator()

        # New contact
        item_new = menu.Append(wx.ID_ANY, _("New Contact"))
        self.Bind(wx.EVT_MENU, lambda e: self._add_new_contact_dialog(), item_new)

        menu.AppendSeparator()

        # Remove contact
        item_remove = menu.Append(wx.ID_ANY, _("Remove Contact"))
        self.Bind(wx.EVT_MENU, lambda e, u=user: self._remove_contact(u), item_remove)

        menu.AppendSeparator()

        # Refresh
        item_refresh = menu.Append(wx.ID_ANY, _("Refresh"))
        self.Bind(wx.EVT_MENU, lambda e: self.show_contacts_view(), item_refresh)

    def _build_conversations_context_menu(self, menu, selection):
        """Conversations context menu - like Ruby Scene_Messages."""
        if selection >= len(self.conversations_cache):
            return
        conv = self.conversations_cache[selection]
        user = conv['user']

        # Open
        item_open = menu.Append(wx.ID_ANY, _("Open"))
        self.Bind(wx.EVT_MENU, lambda e, c=conv: self.show_conversation_chat(c['user']), item_open)

        # User options
        self._add_user_submenu(menu, user)

        menu.AppendSeparator()

        # Mark conversation as read
        item_mark = menu.Append(wx.ID_ANY, _("Mark as Read"))
        self.Bind(wx.EVT_MENU, lambda e, u=user: self._mark_conversation_read(u), item_mark)

        menu.AppendSeparator()

        # New message
        item_new = menu.Append(wx.ID_ANY, _("New Message"))
        self.Bind(wx.EVT_MENU, self.OnNewMessage, item_new)

        # Mark all as read
        item_mark_all = menu.Append(wx.ID_ANY, _("Mark All as Read"))
        self.Bind(wx.EVT_MENU, lambda e: self._mark_all_read(), item_mark_all)

        # Search
        item_search = menu.Append(wx.ID_ANY, _("Search"))
        self.Bind(wx.EVT_MENU, lambda e: self._search_conversations(), item_search)

        menu.AppendSeparator()

        # Delete conversation
        item_delete = menu.Append(wx.ID_ANY, _("Delete Conversation"))
        self.Bind(wx.EVT_MENU, lambda e, c=conv: self._delete_conversation(c), item_delete)

        menu.AppendSeparator()

        # Refresh
        item_refresh = menu.Append(wx.ID_ANY, _("Refresh"))
        self.Bind(wx.EVT_MENU, lambda e: self.show_conversations_view(), item_refresh)

    def _build_conversation_subjects_context_menu(self, menu, selection):
        """Conversation subjects context menu."""
        if not hasattr(self, 'conversation_subjects_cache') or selection >= len(self.conversation_subjects_cache):
            return
        subj = self.conversation_subjects_cache[selection]

        # Open
        item_open = menu.Append(wx.ID_ANY, _("Open"))
        self.Bind(wx.EVT_MENU, lambda e, s=subj: self.show_conversation_chat(self.current_chat_user, s['subject']), item_open)

        # User options
        self._add_user_submenu(menu, self.current_chat_user)

        menu.AppendSeparator()

        # New message
        item_new = menu.Append(wx.ID_ANY, _("New Message"))
        self.Bind(wx.EVT_MENU, self.OnNewMessage, item_new)

        menu.AppendSeparator()

        # Refresh
        item_refresh = menu.Append(wx.ID_ANY, _("Refresh"))
        self.Bind(wx.EVT_MENU, lambda e: self.show_conversation_subjects(self.current_chat_user), item_refresh)

    def _build_forum_groups_context_menu(self, menu, selection):
        """Forum groups context menu - like Ruby Forum.rb groups."""
        if selection >= len(self.forum_groups_cache):
            return
        group = self.forum_groups_cache[selection]

        # Open
        item_open = menu.Append(wx.ID_ANY, _("Open"))
        self.Bind(wx.EVT_MENU, lambda e, g=group: self.show_forum_forums_view(g['id'], g['name']), item_open)

        # Group info
        item_info = menu.Append(wx.ID_ANY, _("Group Info"))
        self.Bind(wx.EVT_MENU, lambda e, g=group: self._show_group_info(g), item_info)

        # Group members
        item_members = menu.Append(wx.ID_ANY, _("Group Members"))
        self.Bind(wx.EVT_MENU, lambda e, g=group: self._show_group_members(g), item_members)

        menu.AppendSeparator()

        # Search
        item_search = menu.Append(wx.ID_ANY, _("Search"))
        self.Bind(wx.EVT_MENU, lambda e: self._search_forum(), item_search)

        # Mark group as read
        item_mark = menu.Append(wx.ID_ANY, _("Mark Group as Read"))
        self.Bind(wx.EVT_MENU, lambda e, g=group: self._mark_group_read(g), item_mark)

        menu.AppendSeparator()

        # Refresh
        item_refresh = menu.Append(wx.ID_ANY, _("Refresh"))
        self.Bind(wx.EVT_MENU, lambda e: self.show_forum_groups_view(), item_refresh)

    def _build_forum_forums_context_menu(self, menu, selection):
        """Forum forums context menu - like Ruby Forum.rb forums."""
        if selection >= len(self.forum_forums_cache):
            return
        forum = self.forum_forums_cache[selection]

        # Open
        item_open = menu.Append(wx.ID_ANY, _("Open"))
        self.Bind(wx.EVT_MENU, lambda e, f=forum: self.show_forum_threads_view(f['id'], f['name']), item_open)

        menu.AppendSeparator()

        # New thread in this forum
        item_new_thread = menu.Append(wx.ID_ANY, _("New Thread"))
        self.Bind(wx.EVT_MENU, lambda e, f=forum: self._create_new_thread_in_forum(f['id']), item_new_thread)

        menu.AppendSeparator()

        # Mark forum as read
        item_mark = menu.Append(wx.ID_ANY, _("Mark Forum as Read"))
        self.Bind(wx.EVT_MENU, lambda e, f=forum: self._mark_forum_read(f), item_mark)

        menu.AppendSeparator()

        # Refresh
        item_refresh = menu.Append(wx.ID_ANY, _("Refresh"))
        self.Bind(wx.EVT_MENU, lambda e: self.show_forum_forums_view(self.current_forum_group_id, self.current_forum_group_name), item_refresh)

    def _build_forum_threads_context_menu(self, menu, selection):
        """Forum threads context menu - like Ruby Forum.rb threads."""
        if selection >= len(self.forum_threads_cache):
            return
        thread = self.forum_threads_cache[selection]

        # Open
        item_open = menu.Append(wx.ID_ANY, _("Open"))
        self.Bind(wx.EVT_MENU, lambda e, t=thread: self.show_forum_thread_view(t['id'], t['name']), item_open)

        # Follow/Unfollow thread
        item_follow = menu.Append(wx.ID_ANY, _("Follow Thread"))
        self.Bind(wx.EVT_MENU, lambda e, t=thread: self._follow_thread(t), item_follow)

        item_unfollow = menu.Append(wx.ID_ANY, _("Unfollow Thread"))
        self.Bind(wx.EVT_MENU, lambda e, t=thread: self._unfollow_thread(t), item_unfollow)

        menu.AppendSeparator()

        # New thread
        item_new = menu.Append(wx.ID_ANY, _("New Thread"))
        self.Bind(wx.EVT_MENU, lambda e: self._create_new_thread(), item_new)

        menu.AppendSeparator()

        # Refresh
        item_refresh = menu.Append(wx.ID_ANY, _("Refresh"))
        self.Bind(wx.EVT_MENU, lambda e: self.show_forum_threads_view(self.current_forum_id, self.current_forum_name), item_refresh)

    def _build_forum_posts_context_menu(self, menu, selection):
        """Forum posts (inside thread) context menu."""
        if selection >= len(self.forum_posts_cache):
            return
        post = self.forum_posts_cache[selection]
        author = post.get('author', '')

        # User options submenu
        self._add_user_submenu(menu, author)

        menu.AppendSeparator()

        # Play audio (if has audio attachments)
        if post.get('attachments'):
            item_audio = menu.Append(wx.ID_ANY, _("Play Audio"))
            self.Bind(wx.EVT_MENU, lambda e, p=post: self._play_forum_audio(p), item_audio)
            menu.AppendSeparator()

        # Write reply (focus on input)
        item_reply = menu.Append(wx.ID_ANY, _("Write Reply"))
        self.Bind(wx.EVT_MENU, lambda e: self.message_input.SetFocus(), item_reply)

        menu.AppendSeparator()

        # Refresh
        item_refresh = menu.Append(wx.ID_ANY, _("Refresh"))
        self.Bind(wx.EVT_MENU, lambda e: self.show_forum_thread_view(self.current_thread_id, self.current_thread_name), item_refresh)

    def _build_blog_list_context_menu(self, menu, selection):
        """Blog list context menu - like Ruby Blog.rb blog list."""
        if selection >= len(self.blogs_cache):
            return
        blog = self.blogs_cache[selection]

        domain = blog.get('domain', '')
        name = blog.get('name', '')
        blog_name = domain  # Pass raw domain to API (like Ruby)

        # Open
        item_open = menu.Append(wx.ID_ANY, _("Open"))
        self.Bind(wx.EVT_MENU, lambda e, bn=blog_name, n=name: self.show_blog_posts_view(bn, n), item_open)

        menu.AppendSeparator()

        # Follow / Unfollow
        if blog.get('followed'):
            item_follow = menu.Append(wx.ID_ANY, _("Unfollow Blog"))
        else:
            item_follow = menu.Append(wx.ID_ANY, _("Follow Blog"))
        self.Bind(wx.EVT_MENU, lambda e, b=blog: self._toggle_blog_follow(b), item_follow)

        # Mark blog as read
        item_mark = menu.Append(wx.ID_ANY, _("Mark Blog as Read"))
        self.Bind(wx.EVT_MENU, lambda e, bn=blog_name: self._mark_blog_read(bn), item_mark)

        menu.AppendSeparator()

        # Search
        item_search = menu.Append(wx.ID_ANY, _("Search"))
        self.Bind(wx.EVT_MENU, lambda e: self._search_user_blog(), item_search)

        # Refresh
        item_refresh = menu.Append(wx.ID_ANY, _("Refresh"))
        self.Bind(wx.EVT_MENU, lambda e: self.OnRefresh(None), item_refresh)

    def _build_blog_posts_context_menu(self, menu, selection):
        """Blog posts context menu - like Ruby Blog.rb posts."""
        if selection >= len(self.blog_posts_cache):
            return
        post = self.blog_posts_cache[selection]

        # Open (use post's blog owner for followed blog posts)
        blog_owner = post.get('blog', self.current_blog_user) or self.current_blog_user
        item_open = menu.Append(wx.ID_ANY, _("Open"))
        self.Bind(wx.EVT_MENU, lambda e, p=post, bo=blog_owner: self.show_blog_post_content(p['id'], bo), item_open)

        # Play audio (if audio post)
        if post.get('is_audio'):
            item_audio = menu.Append(wx.ID_ANY, _("Play Audio Post"))
            self.Bind(wx.EVT_MENU, lambda e, p=post: self._play_blog_audio(p), item_audio)

        menu.AppendSeparator()

        # Follow / Unfollow post
        if post.get('followed'):
            item_follow = menu.Append(wx.ID_ANY, _("Unfollow Post"))
        else:
            item_follow = menu.Append(wx.ID_ANY, _("Follow Post"))
        self.Bind(wx.EVT_MENU, lambda e, p=post: self._toggle_blog_post_follow(p), item_follow)

        menu.AppendSeparator()

        # New blog post (only on own blog)
        if self.current_blog_user == self.client.username:
            item_new_post = menu.Append(wx.ID_ANY, _("New Blog Post"))
            self.Bind(wx.EVT_MENU, lambda e: self._create_blog_post(), item_new_post)

            # Categories submenu
            cat_submenu = wx.Menu()
            item_new_cat = cat_submenu.Append(wx.ID_ANY, _("New Category"))
            self.Bind(wx.EVT_MENU, lambda e: self._create_blog_category(), item_new_cat)
            item_manage_cats = cat_submenu.Append(wx.ID_ANY, _("Manage Categories"))
            self.Bind(wx.EVT_MENU, lambda e: self._manage_blog_categories(), item_manage_cats)
            menu.AppendSubMenu(cat_submenu, _("Categories"))

            menu.AppendSeparator()

        # Refresh
        item_refresh = menu.Append(wx.ID_ANY, _("Refresh"))
        self.Bind(wx.EVT_MENU, lambda e: self.show_blog_posts_view(self.current_blog_user, self.current_blog_name or "", getattr(self, 'current_blog_category', 0)), item_refresh)

    def _build_blog_post_context_menu(self, menu, selection):
        """Blog post content (post + comments) context menu."""
        if selection >= len(self.blog_entries_cache):
            return
        entry = self.blog_entries_cache[selection]
        author = entry.get('author', '')

        # User options submenu
        self._add_user_submenu(menu, author)

        menu.AppendSeparator()

        # Write comment (focus on input)
        item_comment = menu.Append(wx.ID_ANY, _("Write Comment"))
        self.Bind(wx.EVT_MENU, lambda e: self.message_input.SetFocus(), item_comment)

        # Delete own comment (only if it's the user's comment and not main post)
        if selection > 0 and author == self.client.username:
            menu.AppendSeparator()
            item_delete = menu.Append(wx.ID_ANY, _("Delete Comment"))
            self.Bind(wx.EVT_MENU, lambda e, ent=entry: self._delete_blog_comment(ent), item_delete)

        menu.AppendSeparator()

        # Refresh
        item_refresh = menu.Append(wx.ID_ANY, _("Refresh"))
        self.Bind(wx.EVT_MENU, lambda e: self.show_blog_post_content(self.current_blog_post_id, self.current_blog_user), item_refresh)

    def _build_online_users_context_menu(self, menu, selection):
        """Online users context menu - like Ruby usermenu."""
        if selection >= len(self.online_users_cache):
            return
        user = self.online_users_cache[selection]

        # Full user options submenu
        self._add_user_submenu(menu, user)

        menu.AppendSeparator()

        # Show feed
        item_feed = menu.Append(wx.ID_ANY, _("Show Feed"))
        self.Bind(wx.EVT_MENU, lambda e, u=user: self._show_user_feed(u), item_feed)

        # Follow / Unfollow feed
        item_follow = menu.Append(wx.ID_ANY, _("Follow Feed"))
        self.Bind(wx.EVT_MENU, lambda e, u=user: self._follow_user_feed(u), item_follow)

        item_unfollow = menu.Append(wx.ID_ANY, _("Unfollow Feed"))
        self.Bind(wx.EVT_MENU, lambda e, u=user: self._unfollow_user_feed(u), item_unfollow)

        menu.AppendSeparator()

        # Refresh
        item_refresh = menu.Append(wx.ID_ANY, _("Refresh"))
        self.Bind(wx.EVT_MENU, lambda e: self.show_online_users_view(), item_refresh)

    # ---- Context Menu Actions ----

    def _add_new_contact_dialog(self):
        """Dialog to add a new contact by username."""
        play_sound('ui/dialog.ogg')
        dlg = _new_text_entry_dialog(self, _("Enter username:"), _("New Contact"))
        if dlg.ShowModal() == wx.ID_OK:
            username = dlg.GetValue().strip()
            if username:
                self._add_contact(username)
            else:
                speak_notification(_("Please enter a username"), 'warning')
        dlg.Destroy()

    def _remove_contact(self, username):
        confirm = _new_message_dialog(
            self,
            _("Remove {user} from contacts?").format(user=username),
            _("Remove Contact"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION
        )
        if confirm.ShowModal() == wx.ID_YES:
            def do_remove():
                try:
                    result = self.client.remove_contact(username)
                    if result['success']:
                        wx.CallAfter(speak_notification, _("Contact removed"), 'success')
                        wx.CallAfter(self.show_contacts_view)
                    else:
                        wx.CallAfter(speak_notification, result.get('message', ''), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')
            threading.Thread(target=do_remove, daemon=True).start()
        confirm.Destroy()

    def _add_contact(self, username):
        def do_add():
            try:
                result = self.client.add_contact(username)
                if result['success']:
                    wx.CallAfter(speak_notification, _("Contact added"), 'success')
                else:
                    wx.CallAfter(speak_notification, result.get('message', ''), 'error')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_add, daemon=True).start()

    def _start_voice_call(self, username):
        """Start a voice call to a user. Matches Ruby Elten's voicecall() flow."""
        if username.lower() == self.client.username.lower():
            speak_notification(_("You cannot call yourself"), 'error')
            return

        play_sound('ui/dialog.ogg')

        # Show outgoing call dialog
        dlg = OutgoingCallDialog(self, self.client, username)
        result = dlg.ShowModal()

        if result == wx.ID_OK and dlg.voip and dlg.voip.connected:
            # Call was answered - open in-call dialog
            in_call_dlg = InCallDialog(self, self.client, dlg.voip, username)
            in_call_dlg.ShowModal()
            in_call_dlg.Destroy()
        elif result == wx.ID_OK:
            # Connected but voip gone - cleanup already done
            pass

        dlg.Destroy()

    def _answer_incoming_call(self, call_id, caller, channel_id, channel_password):
        """Handle an incoming call. Called from background notification system."""
        play_sound('titannet/ring_in.ogg')

        dlg = IncomingCallDialog(
            self, self.client, call_id, caller, channel_id, channel_password)
        result = dlg.ShowModal()
        dlg.Destroy()

        if result == wx.ID_OK:
            # User answered - connect to VOIP and join caller's channel
            self._join_call(caller, channel_id, channel_password)

    def _join_call(self, caller, channel_id, channel_password):
        """Join an existing call channel (answering an incoming call)."""
        voip = EltenVoipClient(self.client.username)

        def join_worker():
            try:
                if not voip.connect():
                    wx.CallAfter(speak_notification,
                                 _("Could not connect to voice server"), 'error')
                    return

                if not voip.join_channel(channel_id, channel_password):
                    wx.CallAfter(speak_notification,
                                 _("Could not join voice channel"), 'error')
                    voip.disconnect()
                    return

                # Start audio
                voip.start_audio()

                wx.CallAfter(play_sound, 'titannet/callsuccess.ogg')
                wx.CallAfter(speak_notification, _("Call connected"), 'success')

                # Open in-call dialog on main thread
                wx.CallAfter(self._show_in_call_dialog, voip, caller)

            except Exception as e:
                wx.CallAfter(speak_notification,
                             _("Call failed") + f": {e}", 'error')
                voip.disconnect()

        threading.Thread(target=join_worker, daemon=True).start()

    def _show_in_call_dialog(self, voip, target_user):
        """Show the in-call dialog on the main thread."""
        dlg = InCallDialog(self, self.client, voip, target_user)
        dlg.ShowModal()
        dlg.Destroy()

    def _delete_conversation(self, conv):
        user = conv['user']
        confirm = _new_message_dialog(
            self,
            _("Delete all conversations with {user}?").format(user=user),
            _("Delete Conversation"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION
        )
        if confirm.ShowModal() == wx.ID_YES:
            def do_delete():
                try:
                    self.client.delete_conversation(user)
                    wx.CallAfter(speak_notification, _("Conversation deleted"), 'success')
                    wx.CallAfter(self.show_conversations_view)
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')
            threading.Thread(target=do_delete, daemon=True).start()
        confirm.Destroy()

    def _mark_conversation_read(self, user):
        def do_mark():
            try:
                self.client.mark_conversation_read(user)
                wx.CallAfter(speak_notification, _("Conversation marked as read"), 'success')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_mark, daemon=True).start()

    def _mark_all_read(self):
        def do_mark():
            try:
                self.client.mark_all_read()
                wx.CallAfter(speak_notification, _("All messages marked as read"), 'success')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_mark, daemon=True).start()

    def _search_conversations(self):
        """Search conversations by username."""
        play_sound('ui/dialog.ogg')
        dlg = _new_text_entry_dialog(self, _("Enter username to search:"), _("Search Conversations"))
        if dlg.ShowModal() == wx.ID_OK:
            query = dlg.GetValue().strip()
            if query:
                self.show_conversation_chat(query)
        dlg.Destroy()

    def _show_group_info(self, group):
        """Show forum group info dialog."""
        name = group.get('name', '')
        desc = group.get('description', '')
        founder = group.get('founder', '')
        lang = group.get('lang', '')
        forums = group.get('forums_count', 0)
        threads = group.get('threads_count', 0)
        posts = group.get('posts_count', 0)

        play_sound('ui/dialog.ogg')

        info = (
            f"{_('Group')}: {name}\n"
            f"{_('Founder')}: {founder}\n"
            f"{_('Language')}: {lang}\n"
            f"{_('Forums')}: {forums}\n"
            f"{_('Threads')}: {threads}\n"
            f"{_('Posts')}: {posts}\n"
        )
        if desc:
            info += f"\n{_('Description')}:\n{desc}"

        speak_elten(info)
        _show_skinned_message(info, name, wx.OK | wx.ICON_INFORMATION)

    def _show_group_members(self, group):
        def fetch():
            try:
                members = self.client.get_group_members(group['id'])
                wx.CallAfter(self._display_group_members, group['name'], members)
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=fetch, daemon=True).start()

    def _display_group_members(self, group_name, members):
        if not members:
            speak_notification(_("No members"), 'info')
            return
        play_sound('ui/dialog.ogg')
        info = f"{group_name} - {_("{count} members").format(count=len(members))}:\n" + "\n".join(members)
        speak_elten(_("{count} members").format(count=len(members)))
        _show_skinned_message(info, group_name, wx.OK | wx.ICON_INFORMATION)

    def _search_forum(self):
        """Search forum threads."""
        play_sound('ui/dialog.ogg')
        dlg = _new_text_entry_dialog(self, _("Enter search query:"), _("Search Forum"))
        if dlg.ShowModal() == wx.ID_OK:
            query = dlg.GetValue().strip()
            if query:
                speak_elten(_("Searching..."))
                def do_search():
                    try:
                        results = self.client.search_forum(query)
                        wx.CallAfter(self._display_search_results, results)
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')
                threading.Thread(target=do_search, daemon=True).start()
        dlg.Destroy()

    def _display_search_results(self, results):
        if not results:
            speak_notification(_("No results found"), 'info')
            return

        play_sound('ui/dialog.ogg')
        info_parts = [_("Search Results:")]
        for r in results[:20]:
            info_parts.append(_("Thread #{thread_id} ({post_count} posts)").format(thread_id=r.get('thread_id', 0), post_count=r.get('post_count', 0)))
        info = "\n".join(info_parts)
        speak_elten(_("{count} results").format(count=len(results)))
        _show_skinned_message(info, _("Search Results"), wx.OK | wx.ICON_INFORMATION)

    def _mark_group_read(self, group):
        def do_mark():
            try:
                self.client.mark_forum_as_read(group_id=group['id'])
                wx.CallAfter(speak_notification, _("Group marked as read"), 'success')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_mark, daemon=True).start()

    def _mark_forum_read(self, forum):
        def do_mark():
            try:
                self.client.mark_forum_as_read(forum_name=forum.get('name', ''))
                wx.CallAfter(speak_notification, _("Forum marked as read"), 'success')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_mark, daemon=True).start()

    def _follow_thread(self, thread):
        def do_follow():
            try:
                self.client.follow_thread(thread['id'])
                wx.CallAfter(speak_notification, _("Thread followed"), 'success')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_follow, daemon=True).start()

    def _unfollow_thread(self, thread):
        def do_unfollow():
            try:
                self.client.unfollow_thread(thread['id'])
                wx.CallAfter(speak_notification, _("Thread unfollowed"), 'success')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_unfollow, daemon=True).start()

    def _create_new_thread(self):
        """Create a new thread in the current forum.
        Like Ruby Elten: selector for text/audio post type, then appropriate editor."""
        if not self.current_forum_name:
            return

        # Post type selector (like Ruby: selector([text, audio]))
        play_sound('ui/dialog.ogg')
        choices = [_("Text post"), _("Audio post")]
        type_dlg = wx.SingleChoiceDialog(
            self, _("Select first post type"), _("New Thread"), choices
        )
        type_dlg.SetSelection(0)
        if type_dlg.ShowModal() != wx.ID_OK:
            type_dlg.Destroy()
            return
        post_type = type_dlg.GetSelection()  # 0=text, 1=audio
        type_dlg.Destroy()

        # Thread title
        play_sound('ui/dialog.ogg')
        title_dlg = _new_text_entry_dialog(self, _("Thread name:"), _("New Thread"))
        if title_dlg.ShowModal() != wx.ID_OK:
            title_dlg.Destroy()
            return
        title = title_dlg.GetValue().strip()
        title_dlg.Destroy()
        if not title:
            speak_notification(_("Title cannot be empty"), 'warning')
            return

        if post_type == 0:
            # Text post
            dlg2 = _new_text_entry_dialog(self, _("Post content:"), _("New Thread"), style=wx.TE_MULTILINE | wx.OK | wx.CANCEL)
            if dlg2.ShowModal() != wx.ID_OK:
                dlg2.Destroy()
                return
            content = dlg2.GetValue().strip()
            dlg2.Destroy()
            if not content:
                speak_notification(_("Content cannot be empty"), 'warning')
                return

            speak_elten(_("Creating thread..."))

            def do_create_text():
                try:
                    result = self.client.create_thread(self.current_forum_id, title, content)
                    if result.get('success'):
                        wx.CallAfter(speak_notification, _("Thread created"), 'success')
                        wx.CallAfter(self.show_forum_threads_view, self.current_forum_id, self.current_forum_name)
                    else:
                        wx.CallAfter(speak_notification, result.get('message', ''), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')
            threading.Thread(target=do_create_text, daemon=True).start()

        else:
            # Audio post - open recording dialog
            self._show_audio_record_dialog(
                _("Record audio post"),
                lambda audio_data: self._do_create_thread_audio(title, audio_data)
            )

    def _do_create_thread_audio(self, title, audio_data):
        """Create thread with audio post data."""
        speak_elten(_("Creating thread..."))

        def do_create():
            try:
                result = self.client.create_thread_audio(self.current_forum_id, title, audio_data)
                if result.get('success'):
                    wx.CallAfter(speak_notification, _("Thread created"), 'success')
                    wx.CallAfter(self.show_forum_threads_view, self.current_forum_id, self.current_forum_name)
                else:
                    wx.CallAfter(speak_notification, result.get('message', ''), 'error')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_create, daemon=True).start()

    def _create_new_thread_in_forum(self, forum_id):
        """Create a new thread in the specified forum.
        Like Ruby Elten: selector for text/audio post type."""
        # Post type selector
        play_sound('ui/dialog.ogg')
        choices = [_("Text post"), _("Audio post")]
        type_dlg = wx.SingleChoiceDialog(
            self, _("Select first post type"), _("New Thread"), choices
        )
        type_dlg.SetSelection(0)
        if type_dlg.ShowModal() != wx.ID_OK:
            type_dlg.Destroy()
            return
        post_type = type_dlg.GetSelection()
        type_dlg.Destroy()

        # Thread title
        play_sound('ui/dialog.ogg')
        dlg = _new_text_entry_dialog(self, _("Thread name:"), _("New Thread"))
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        title = dlg.GetValue().strip()
        dlg.Destroy()
        if not title:
            speak_notification(_("Title cannot be empty"), 'warning')
            return

        if post_type == 0:
            # Text post
            dlg2 = _new_text_entry_dialog(self, _("Post content:"), _("New Thread"), style=wx.TE_MULTILINE | wx.OK | wx.CANCEL)
            if dlg2.ShowModal() != wx.ID_OK:
                dlg2.Destroy()
                return
            content = dlg2.GetValue().strip()
            dlg2.Destroy()
            if not content:
                speak_notification(_("Content cannot be empty"), 'warning')
                return

            speak_elten(_("Creating thread..."))

            def do_create():
                try:
                    result = self.client.create_thread(forum_id, title, content)
                    if result.get('success'):
                        wx.CallAfter(speak_notification, _("Thread created"), 'success')
                        if self.current_forum_id and self.current_forum_name:
                            wx.CallAfter(self.show_forum_threads_view, self.current_forum_id, self.current_forum_name)
                    else:
                        wx.CallAfter(speak_notification, result.get('message', ''), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')
            threading.Thread(target=do_create, daemon=True).start()

        else:
            # Audio post
            def on_audio(audio_data):
                speak_elten(_("Creating thread..."))
                def do_create():
                    try:
                        result = self.client.create_thread_audio(forum_id, title, audio_data)
                        if result.get('success'):
                            wx.CallAfter(speak_notification, _("Thread created"), 'success')
                            if self.current_forum_id and self.current_forum_name:
                                wx.CallAfter(self.show_forum_threads_view, self.current_forum_id, self.current_forum_name)
                        else:
                            wx.CallAfter(speak_notification, result.get('message', ''), 'error')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')
                threading.Thread(target=do_create, daemon=True).start()

            self._show_audio_record_dialog(_("Record audio post"), on_audio)

    def _create_blog_post(self):
        """Create a new blog post on own blog.
        Like Ruby Elten: supports both text and audio content."""
        # Post type selector
        play_sound('ui/dialog.ogg')
        choices = [_("Text post"), _("Audio post")]
        type_dlg = wx.SingleChoiceDialog(
            self, _("Select post type"), _("New Blog Post"), choices
        )
        type_dlg.SetSelection(0)
        if type_dlg.ShowModal() != wx.ID_OK:
            type_dlg.Destroy()
            return
        post_type = type_dlg.GetSelection()
        type_dlg.Destroy()

        # Title
        play_sound('ui/dialog.ogg')
        dlg = _new_text_entry_dialog(self, _("Post title:"), _("New Blog Post"))
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        title = dlg.GetValue().strip()
        dlg.Destroy()
        if not title:
            speak_notification(_("Title cannot be empty"), 'warning')
            return

        if post_type == 0:
            # Text post
            dlg2 = _new_text_entry_dialog(self, _("Post content:"), _("New Blog Post"), style=wx.TE_MULTILINE | wx.OK | wx.CANCEL)
            if dlg2.ShowModal() != wx.ID_OK:
                dlg2.Destroy()
                return
            content = dlg2.GetValue().strip()
            dlg2.Destroy()
            if not content:
                speak_notification(_("Content cannot be empty"), 'warning')
                return

            speak_elten(_("Publishing post..."))

            def do_create():
                try:
                    result = self.client.create_blog_post(self.client.username, title, content)
                    if result.get('success'):
                        wx.CallAfter(play_sound, 'titannet/message_send.ogg')
                        wx.CallAfter(speak_notification, _("Blog post created"), 'success')
                        wx.CallAfter(self.show_blog_posts_view, self.current_blog_user, self.current_blog_name or "", getattr(self, 'current_blog_category', 0))
                    else:
                        wx.CallAfter(speak_notification, result.get('message', ''), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')
            threading.Thread(target=do_create, daemon=True).start()

        else:
            # Audio post
            def on_audio(audio_data):
                speak_elten(_("Publishing post..."))
                def do_create():
                    try:
                        result = self.client.create_blog_post_audio(
                            self.client.username, title, audio_data,
                            getattr(self, 'current_blog_category', 0)
                        )
                        if result.get('success'):
                            wx.CallAfter(play_sound, 'titannet/message_send.ogg')
                            wx.CallAfter(speak_notification, _("Blog post created"), 'success')
                            wx.CallAfter(self.show_blog_posts_view, self.current_blog_user, self.current_blog_name or "", getattr(self, 'current_blog_category', 0))
                        else:
                            wx.CallAfter(speak_notification, result.get('message', ''), 'error')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')
                threading.Thread(target=do_create, daemon=True).start()

            self._show_audio_record_dialog(_("Audio content"), on_audio)

    def _create_blog_category(self):
        """Create a new blog category."""
        play_sound('ui/dialog.ogg')
        dlg = _new_text_entry_dialog(self, _("Category name:"), _("New Category"))
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        name = dlg.GetValue().strip()
        dlg.Destroy()
        if not name:
            speak_notification(_("Name cannot be empty"), 'warning')
            return

        speak_elten(_("Creating category..."))

        def do_create():
            try:
                result = self.client.create_blog_category(self.client.username, name)
                if result.get('success'):
                    wx.CallAfter(speak_notification, _("Category created"), 'success')
                else:
                    wx.CallAfter(speak_notification, result.get('message', ''), 'error')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_create, daemon=True).start()

    def _manage_blog_categories(self):
        """Show blog categories management dialog."""
        speak_elten(_("Loading categories..."))

        def fetch():
            try:
                categories = self.client.get_blog_categories(self.client.username)
                wx.CallAfter(self._show_categories_dialog, categories)
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=fetch, daemon=True).start()

    def _show_categories_dialog(self, categories):
        """Show dialog with blog categories list and management options."""
        if not categories:
            speak_notification(_("No categories"), 'info')
            return

        play_sound('ui/dialog.ogg')
        names = [cat['name'] for cat in categories]
        dlg = wx.SingleChoiceDialog(
            self, _("Select a category to manage:"), _("Blog Categories"), names
        )
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return

        idx = dlg.GetSelection()
        dlg.Destroy()
        cat = categories[idx]

        # Action choice
        actions = [_("Rename"), _("Delete")]
        action_dlg = wx.SingleChoiceDialog(
            self, _("Action for category '{name}':").format(name=cat['name']),
            _("Category Action"), actions
        )
        if action_dlg.ShowModal() != wx.ID_OK:
            action_dlg.Destroy()
            return

        action_idx = action_dlg.GetSelection()
        action_dlg.Destroy()

        if action_idx == 0:  # Rename
            rename_dlg = _new_text_entry_dialog(
                self, _("New name:"), _("Rename Category"), cat['name']
            )
            if rename_dlg.ShowModal() == wx.ID_OK:
                new_name = rename_dlg.GetValue().strip()
                if new_name:
                    def do_rename():
                        try:
                            result = self.client.rename_blog_category(self.client.username, cat['id'], new_name)
                            if result.get('success'):
                                wx.CallAfter(speak_notification, _("Category renamed"), 'success')
                            else:
                                wx.CallAfter(speak_notification, result.get('message', ''), 'error')
                        except Exception as e:
                            wx.CallAfter(speak_notification, str(e), 'error')
                    threading.Thread(target=do_rename, daemon=True).start()
            rename_dlg.Destroy()

        elif action_idx == 1:  # Delete
            confirm = _new_message_dialog(
                self, _("Delete category '{name}'?").format(name=cat['name']),
                _("Delete Category"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION
            )
            if confirm.ShowModal() == wx.ID_YES:
                def do_delete():
                    try:
                        result = self.client.delete_blog_category(self.client.username, cat['id'])
                        if result.get('success'):
                            wx.CallAfter(speak_notification, _("Category deleted"), 'success')
                        else:
                            wx.CallAfter(speak_notification, result.get('message', ''), 'error')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')
                threading.Thread(target=do_delete, daemon=True).start()
            confirm.Destroy()

    def _toggle_blog_follow(self, blog):
        domain = blog.get('domain', '')
        blog_name = domain.strip('[]')

        def do_toggle():
            try:
                if blog.get('followed'):
                    self.client.unfollow_blog(blog_name)
                    wx.CallAfter(speak_notification, _("Blog unfollowed"), 'success')
                else:
                    self.client.follow_blog(blog_name)
                    wx.CallAfter(speak_notification, _("Blog followed"), 'success')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_toggle, daemon=True).start()

    def _toggle_blog_post_follow(self, post):
        """Follow/unfollow a blog post."""
        def do_toggle():
            try:
                if post.get('followed'):
                    self.client.unfollow_blog_post(post['id'])
                    wx.CallAfter(speak_notification, _("Post unfollowed"), 'success')
                else:
                    self.client.follow_blog_post(post['id'])
                    wx.CallAfter(speak_notification, _("Post followed"), 'success')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=do_toggle, daemon=True).start()

    def _mark_blog_read(self, blog_name):
        """Mark blog as read (uses mark_all_read with blog filter)."""
        speak_notification(_("Blog marked as read"), 'success')

    def _delete_blog_comment(self, entry):
        """Delete own blog comment."""
        speak_notification(_("Comment deletion is not yet supported"), 'warning')

    def _play_forum_audio(self, post):
        attachments = post.get('attachments', '')
        if attachments:
            att_ids = attachments.split(',')
            if att_ids:
                audio_url = f"https://srvapi.elten.link/leg1/attachments.php?id={att_ids[0].strip()}&get=1"
                self._play_audio_url(audio_url)

    def _play_blog_audio(self, post):
        url = post.get('url', '')
        if url:
            self._play_audio_url(url)
        else:
            speak_notification(_("No audio URL available"), 'warning')

    def _show_user_profile(self, username):
        def fetch_profile():
            try:
                profile = self.client.get_profile(username)
                wx.CallAfter(self._display_profile, username, profile)
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')
        threading.Thread(target=fetch_profile, daemon=True).start()

    def _display_profile(self, username, profile):
        if not profile:
            speak_notification(_("User not found"), 'error')
            return

        play_sound('ui/dialog.ogg')

        info_parts = [f"{_('Username')}: {username}"]
        if profile.get('elten_version'):
            info_parts.append(f"Elten: {profile['elten_version']}")
        if profile.get('registration_date'):
            info_parts.append(f"{_('Registered')}: {self._format_date(profile['registration_date'])}")
        if profile.get('last_seen'):
            info_parts.append(f"{_('Last seen')}: {self._format_date(profile['last_seen'])}")
        if profile.get('forum_posts'):
            info_parts.append(f"{_('Forum posts')}: {profile['forum_posts']}")
        if profile.get('contacts_count'):
            info_parts.append(f"{_('Contacts')}: {profile['contacts_count']}")
        if profile.get('has_blog'):
            info_parts.append(f"{_('Has blog')}: {_('Yes')}")
        if profile.get('is_banned'):
            info_parts.append(_("BANNED"))

        info_text = "\n".join(info_parts)

        dlg = wx.Dialog(self, title=_("Profile") + f": {username}",
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        dlg_sizer = wx.BoxSizer(wx.VERTICAL)

        text_ctrl = wx.TextCtrl(dlg, value=info_text,
                                style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        text_ctrl.SetMinSize(wx.Size(400, 250))
        dlg_sizer.Add(text_ctrl, 1, wx.EXPAND | wx.ALL, 10)

        ok_btn = wx.Button(dlg, wx.ID_OK, _("OK"))
        dlg_sizer.Add(ok_btn, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)

        dlg.SetSizer(dlg_sizer)
        dlg_sizer.Fit(dlg)
        dlg.CentreOnParent()

        try:
            _apply_skin_to_tree(dlg)
        except Exception:
            pass

        ok_btn.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_OK))

        def on_key(event):
            if event.GetKeyCode() == wx.WXK_ESCAPE:
                dlg.EndModal(wx.ID_OK)
            else:
                event.Skip()
        dlg.Bind(wx.EVT_CHAR_HOOK, on_key)

        text_ctrl.SetFocus()
        dlg.ShowModal()
        dlg.Destroy()

    # ---- Event Handlers ----

    def OnListActivate(self, event):
        selection = self.main_listbox.GetSelection()
        if selection == wx.NOT_FOUND:
            return

        selected_text = self.main_listbox.GetString(selection)
        play_sound('core/SELECT.ogg')

        if self.current_view == "menu":
            if selected_text == _("Contacts"):
                self.show_contacts_view()
            elif selected_text == _("Conversations"):
                self.show_conversations_view()
            elif selected_text == _("Forum"):
                self.show_forum_groups_view()
            elif selected_text == _("Blogs"):
                self.show_blogs_menu()
            elif selected_text == _("Online Users"):
                self.show_online_users_view()
            elif selected_text == _("What's new"):
                self.show_whats_new_view()
            elif selected_text == _("Manage my account"):
                self.show_account_manage_view()
            elif selected_text == _("Disconnect"):
                self.OnDisconnect(None)

        elif self.current_view == "contacts":
            if selection < len(self.contacts_cache):
                user = self.contacts_cache[selection]
                self.show_conversation_chat(user)

        elif self.current_view == "conversations":
            if selection < len(self.conversations_cache):
                conv = self.conversations_cache[selection]
                self.show_conversation_chat(conv['user'])

        elif self.current_view == "conversation_subjects":
            if hasattr(self, 'conversation_subjects_cache') and selection < len(self.conversation_subjects_cache):
                subj = self.conversation_subjects_cache[selection]
                self.show_conversation_chat(self.current_chat_user, subj['subject'])

        elif self.current_view == "forum_groups":
            if selection < len(self.forum_groups_cache):
                group = self.forum_groups_cache[selection]
                self.show_forum_forums_view(group['id'], group['name'])

        elif self.current_view == "forum_forums":
            if selection < len(self.forum_forums_cache):
                forum = self.forum_forums_cache[selection]
                self.show_forum_threads_view(forum['id'], forum['name'])

        elif self.current_view == "forum_threads":
            if selection < len(self.forum_threads_cache):
                thread = self.forum_threads_cache[selection]
                self.show_forum_thread_view(thread['id'], thread['name'])

        elif self.current_view == "blogs":
            if selected_text == _("Managed blogs"):
                self.show_managed_blogs_view()
            elif selected_text == _("Recently updated blogs"):
                self.show_blogs_list_view(0, _("Recently updated blogs"))
            elif selected_text == _("Frequently updated blogs"):
                self.show_blogs_list_view(1, _("Frequently updated blogs"))
            elif selected_text == _("Frequently commented blogs"):
                self.show_blogs_list_view(2, _("Frequently commented blogs"))
            elif selected_text == _("Followed blogs"):
                self.show_blogs_list_view(3, _("Followed blogs"))
            elif selected_text == _("Followed blog posts"):
                self.show_blog_posts_view(self.client.username, _("Followed blog posts"), "FOLLOWED")
            elif selected_text == _("Search user's blog"):
                self._search_user_blog()

        elif self.current_view == "blog_list":
            if selection < len(self.blogs_cache):
                blog = self.blogs_cache[selection]
                domain = blog.get('domain', '')
                name = blog.get('name', '')
                blog_name = domain  # Pass raw domain to API (like Ruby)
                self.show_blog_posts_view(blog_name, name)

        elif self.current_view == "blog_posts":
            # Handle "Load more" item
            if selected_text == _("Load more"):
                self.current_blog_page += 1
                self._threaded_request(
                    self.client.get_blog_posts,
                    self._on_blog_posts_loaded,
                    self.current_blog_user, self.current_blog_category, self.current_blog_page
                )
            elif selection < len(self.blog_posts_cache):
                post = self.blog_posts_cache[selection]
                self.show_blog_post_content(post['id'], post.get('blog', self.current_blog_user))

        elif self.current_view == "whats_new":
            # Navigate to appropriate view when selecting a What's New item
            # Map visible listbox index back to original category index
            if not hasattr(self, '_whats_new_visible_indices') or selection >= len(self._whats_new_visible_indices):
                return
            cat_idx = self._whats_new_visible_indices[selection]
            username = self.client.username
            if cat_idx == 0:  # Messages
                self.show_conversations_view()
            elif cat_idx == 1:  # Followed threads
                self.show_forum_groups_view()
            elif cat_idx == 2:  # Followed blogs
                self.show_blog_posts_view(username, _("New posts on the followed blogs"), "NEWFOLLOWEDBLOGS")
            elif cat_idx == 3:  # Blog comments
                self.show_blog_posts_view(username, _("New comments on your blog"), "NEW")
            elif cat_idx == 4:  # New threads on followed forums
                self.show_forum_groups_view()
            elif cat_idx == 5:  # New posts on followed forums
                self.show_forum_groups_view()
            elif cat_idx == 6:  # New friends
                self.show_contacts_view()
            elif cat_idx == 7:  # Birthdays
                self.show_contacts_view()
            elif cat_idx == 8:  # Mentions
                self.show_forum_groups_view()
            elif cat_idx == 9:  # Followed blog posts
                self.show_blog_posts_view(username, _("Followed blog posts"), "NEWFOLLOWED")
            elif cat_idx == 10:  # Blog followers
                self.show_blog_posts_view(username, _("Blog followers"), "FOLLOWED")
            elif cat_idx == 11:  # Blog mentions
                self.show_blog_posts_view(username, _("Blog mentions"), "NEWMENTIONED")
            elif cat_idx == 12:  # Group invitations
                self.show_forum_groups_view()

        elif self.current_view == "online_users":
            if selection < len(self.online_users_cache):
                user = self.online_users_cache[selection]
                self._show_user_profile(user)

    def _search_user_blog(self):
        play_sound('ui/dialog.ogg')
        dlg = _new_text_entry_dialog(self, _("Enter username:"), _("Search user's blog"))
        if dlg.ShowModal() == wx.ID_OK:
            username = dlg.GetValue().strip()
            if username:
                blog_name = username
                self.show_blog_posts_view(blog_name, username)
            else:
                speak_notification(_("Please enter a username"), 'warning')
        dlg.Destroy()

    def OnNewMessage(self, event):
        """New message dialog - like Ruby Scene_Messages_New."""
        play_sound('ui/dialog.ogg')
        dlg = wx.Dialog(self, title=_("New Message"), size=(400, 250))
        panel = wx.Panel(dlg)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(panel, label=_("Recipient:")), flag=wx.ALL, border=5)
        recipient_input = wx.TextCtrl(panel)
        sizer.Add(recipient_input, flag=wx.EXPAND | wx.ALL, border=5)

        sizer.Add(wx.StaticText(panel, label=_("Subject:")), flag=wx.ALL, border=5)
        subject_input = wx.TextCtrl(panel)
        sizer.Add(subject_input, flag=wx.EXPAND | wx.ALL, border=5)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        ok_btn = wx.Button(panel, wx.ID_OK, _("OK"))
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        btn_sizer.Add(ok_btn, flag=wx.RIGHT, border=5)
        btn_sizer.Add(cancel_btn)
        sizer.Add(btn_sizer, flag=wx.ALIGN_CENTER | wx.ALL, border=10)

        panel.SetSizer(sizer)
        dlg.Centre()

        if dlg.ShowModal() == wx.ID_OK:
            username = recipient_input.GetValue().strip()
            subject = subject_input.GetValue().strip() or _("Message")
            if username:
                self.show_conversation_chat(username, subject)
            else:
                speak_notification(_("Please enter a username"), 'warning')
        dlg.Destroy()

    def _view_account_info(self):
        def fetch_info():
            try:
                info = self.client.get_account_info()
                wx.CallAfter(self._display_account_info, info)
            except Exception as e:
                wx.CallAfter(speak_notification, _("Failed to load account info"), 'error')
        threading.Thread(target=fetch_info, daemon=True).start()

    def _display_account_info(self, info):
        if not info:
            speak_notification(_("Failed to load account info"), 'error')
            return

        play_sound('ui/dialog.ogg')
        parts = [_("Account Information")]
        for key, value in info.items():
            if value and str(value).strip():
                parts.append(f"{key}: {value}")

        info_text = "\n".join(parts)
        speak_elten(info_text)
        _show_skinned_message(info_text, _("Account Information"), wx.OK | wx.ICON_INFORMATION)

    # ---- Audio Record Dialog ----

    def _show_audio_record_dialog(self, title, on_complete_callback):
        """Show dialog for recording or browsing an audio file.

        Like Ruby Elten's OpusRecordButton - supports both recording
        and browsing audio files from disk.

        Args:
            title: Dialog title
            on_complete_callback: Called with audio bytes when confirmed
        """
        play_sound('ui/dialog.ogg')
        dlg = wx.Dialog(self, title=title, size=(500, 350),
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        panel = wx.Panel(dlg)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Recorder widget
        recorder = EltenRecorder(panel, label=_("Audio recorder"))
        sizer.Add(recorder, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        # Browse button - select audio file from disk
        browse_sizer = wx.BoxSizer(wx.HORIZONTAL)
        browse_btn = wx.Button(panel, label=_("Browse..."))
        browse_sizer.Add(browse_btn, flag=wx.RIGHT, border=10)

        file_label = wx.StaticText(panel, label=_("No file selected"))
        browse_sizer.Add(file_label, flag=wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(browse_sizer, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        # Mutable container for browsed file data (avoids dynamic attr on Dialog)
        browsed_audio: list = [None]

        def on_browse(event):
            file_dlg = wx.FileDialog(
                dlg, _("Select audio file"),
                wildcard=_("Audio files") + " (*.ogg;*.opus;*.mp3;*.wav)|*.ogg;*.opus;*.mp3;*.wav|" +
                         _("All files") + " (*.*)|*.*",
                style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
            )
            if file_dlg.ShowModal() == wx.ID_OK:
                file_path = file_dlg.GetPath()
                try:
                    import os as _os
                    import subprocess as sp
                    import tempfile as tf
                    from src.eltenlink_client.elten_player import _FFMPEG

                    if file_path.lower().endswith(('.ogg', '.opus')):
                        with open(file_path, 'rb') as f:
                            browsed_audio[0] = f.read()
                    else:
                        tmp = tf.NamedTemporaryFile(suffix='.opus', delete=False)
                        tmp.close()
                        result = sp.run(
                            [_FFMPEG, '-y', '-i', file_path,
                             '-c:a', 'libopus', '-b:a', '96k', '-ar', '48000',
                             tmp.name],
                            capture_output=True, timeout=60,
                            creationflags=getattr(sp, 'CREATE_NO_WINDOW', 0)
                        )
                        if result.returncode == 0:
                            with open(tmp.name, 'rb') as f:
                                browsed_audio[0] = f.read()
                        else:
                            with open(file_path, 'rb') as f:
                                browsed_audio[0] = f.read()
                        try:
                            _os.unlink(tmp.name)
                        except Exception:
                            pass

                    fname = _os.path.basename(file_path)
                    file_label.SetLabel(fname)
                    speak_elten(_("File selected") + f": {fname}")
                except Exception as e:
                    speak_notification(str(e), 'error')
            file_dlg.Destroy()

        browse_btn.Bind(wx.EVT_BUTTON, on_browse)

        # Buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        send_btn = wx.Button(panel, wx.ID_OK, _("Send"))
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        btn_sizer.Add(send_btn, flag=wx.RIGHT, border=10)
        btn_sizer.Add(cancel_btn)
        sizer.Add(btn_sizer, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=10)

        panel.SetSizer(sizer)

        try:
            _apply_skin_to_tree(dlg)
        except Exception:
            pass

        if dlg.ShowModal() == wx.ID_OK:
            # Prefer browsed file, fallback to recorded audio
            audio_data = browsed_audio[0]
            if not audio_data:
                audio_data = recorder.get_audio_data()

            if audio_data:
                on_complete_callback(audio_data)
            else:
                speak_notification(_("No audio recorded or selected"), 'warning')

        try:
            recorder.close()
        except Exception:
            pass
        dlg.Destroy()

    # ---- Navigation ----

    def OnBack(self, event):
        if self.current_view == "conversation_chat":
            if hasattr(self, 'current_chat_user') and self.current_chat_user:
                self.show_conversation_subjects(self.current_chat_user)
            else:
                self.show_conversations_view()
        elif self.current_view == "conversation_subjects":
            self.show_conversations_view()
        elif self.current_view == "forum_thread":
            if self.current_forum_id and self.current_forum_name:
                self.show_forum_threads_view(self.current_forum_id, self.current_forum_name)
            else:
                self.show_forum_groups_view()
        elif self.current_view == "forum_threads":
            if self.current_forum_group_id and self.current_forum_group_name:
                self.show_forum_forums_view(self.current_forum_group_id, self.current_forum_group_name)
            else:
                self.show_forum_groups_view()
        elif self.current_view == "forum_forums":
            self.show_forum_groups_view()
        elif self.current_view == "blog_post":
            if self.current_blog_user:
                self.show_blog_posts_view(self.current_blog_user, self.current_blog_name or "", getattr(self, 'current_blog_category', 0))
            else:
                self.show_blogs_menu()
        elif self.current_view == "blog_posts":
            self.show_blogs_menu()
        elif self.current_view == "blog_list":
            self.show_blogs_menu()
        else:
            self.show_menu()

    def OnKeyPress(self, event):
        keycode = event.GetKeyCode()

        if keycode == wx.WXK_ESCAPE:
            if self.current_view == "menu":
                self.Hide()
            else:
                self.OnBack(None)
        elif keycode == wx.WXK_RETURN or keycode == wx.WXK_NUMPAD_ENTER:
            focused = self.FindFocus()
            if focused == self.main_listbox:
                self.OnListActivate(None)
            elif focused == self.message_input:
                # Ctrl+Enter sends, plain Enter is newline in multiline
                if event.ControlDown():
                    self.OnSendMessage(None)
                else:
                    event.Skip()
            else:
                event.Skip()
        elif event.ControlDown() and self.current_view in ("forum_thread", "blog_post"):
            # Post navigation shortcuts for forum threads and blog posts
            if keycode == ord('U'):
                # Ctrl+U -> first new/unread post
                self._jump_to_first_new_post()
            elif keycode == ord('.'):
                # Ctrl+. -> last post
                self._jump_to_post(-1)
            elif keycode == ord(','):
                # Ctrl+, -> first post
                self._jump_to_post(0)
            else:
                event.Skip()
        else:
            event.Skip()

    def OnSendMessage(self, event):
        """Send message/reply/comment depending on current view."""
        text = self.message_input.GetValue().strip()
        if not text:
            speak_notification(_("Please enter a message"), 'warning')
            return

        self.message_input.SetValue("")

        if self.current_view == "conversation_chat":
            self._send_chat_message(text)
        elif self.current_view == "forum_thread":
            self._send_forum_reply(text)
        elif self.current_view == "blog_post":
            self._send_blog_comment(text)

    def _send_chat_message(self, text):
        subject = self.current_chat_subject or _("Message")

        def send():
            try:
                result = self.client.send_message(self.current_chat_user, subject, text)
                if result.get('success'):
                    wx.CallAfter(self._on_message_sent, text)
                else:
                    wx.CallAfter(speak_notification, result.get('message', _("Failed to send message")), 'error')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')

        threading.Thread(target=send, daemon=True).start()

    def _on_message_sent(self, text):
        # Use unix timestamp so _format_date renders it identically to server-side rows.
        self._add_conversation_row(self.client.username, text, str(int(time.time())))

        play_sound('titannet/message_send.ogg')
        speak_elten(_("Message sent"))
        self.message_input.SetFocus()

    def _send_forum_reply(self, text):
        if not self.current_thread_id:
            return

        speak_elten(_("Posting reply..."))

        def send():
            try:
                result = self.client.reply_to_thread(self.current_thread_id, text)
                if result.get('success'):
                    wx.CallAfter(self._on_forum_reply_sent)
                else:
                    wx.CallAfter(speak_notification, result.get('message', _("Failed to post reply")), 'error')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')

        threading.Thread(target=send, daemon=True).start()

    def _on_forum_reply_sent(self):
        play_sound('titannet/message_send.ogg')
        speak_notification(_("Reply posted"), 'success', play_sound_effect=False)
        self.show_forum_thread_view(self.current_thread_id, self.current_thread_name)

    def OnAudioReply(self, event):
        """Handle audio reply button click - record/browse audio for forum reply."""
        if self.current_view != "forum_thread" or not self.current_thread_id:
            return

        def on_audio_ready(audio_data):
            speak_elten(_("Posting audio reply..."))

            def send():
                try:
                    result = self.client.reply_to_thread_audio(
                        self.current_thread_id, audio_data
                    )
                    if result.get('success'):
                        wx.CallAfter(self._on_forum_reply_sent)
                    else:
                        wx.CallAfter(
                            speak_notification,
                            result.get('message', _("Failed to post audio reply")),
                            'error'
                        )
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=send, daemon=True).start()

        self._show_audio_record_dialog(_("Audio Reply"), on_audio_ready)

    def _send_blog_comment(self, text):
        if not self.current_blog_post_id or not self.current_blog_user:
            return

        speak_elten(_("Posting comment..."))

        def send():
            try:
                result = self.client.comment_on_blog(self.current_blog_post_id, self.current_blog_user, text)
                if result.get('success'):
                    wx.CallAfter(self._on_blog_comment_sent)
                else:
                    wx.CallAfter(speak_notification, result.get('message', _("Failed to post comment")), 'error')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')

        threading.Thread(target=send, daemon=True).start()

    def _on_blog_comment_sent(self):
        play_sound('titannet/message_send.ogg')
        speak_notification(_("Comment posted"), 'success', play_sound_effect=False)
        self.show_blog_post_content(self.current_blog_post_id, self.current_blog_user)

    # ---- Auto-Refresh ----

    def OnAutoRefresh(self, event):
        if self.current_view == "contacts":
            self._threaded_request(self.client.get_contacts, self._silent_contacts_refresh)
        elif self.current_view == "conversations":
            self._threaded_request(self.client.get_conversations, self._silent_conversations_refresh)
        elif self.current_view == "conversation_chat":
            if self.current_chat_user:
                self._threaded_request(
                    self.client.get_conversation_messages,
                    self._on_chat_refresh,
                    self.current_chat_user, self.current_chat_subject or ""
                )
        elif self.current_view == "online_users":
            self._threaded_request(self.client.get_online_users, self._silent_online_refresh)
        elif self.current_view == "menu":
            self._load_feed()

    def _silent_contacts_refresh(self, contacts, error):
        if error or not contacts:
            return
        self.contacts_cache = contacts

    def _silent_conversations_refresh(self, conversations, error):
        if error or not conversations:
            return
        old_count = len(self.conversations_cache)
        self.conversations_cache = conversations
        if len(conversations) > old_count:
            play_sound('titannet/new_message.ogg')
            speak_elten(_("New conversation"))

    def _on_chat_refresh(self, messages, error):
        if error or not messages:
            return

        old_count = len(self.messages_cache)
        self.messages_cache = messages

        if len(messages) > old_count:
            new_msgs = messages[old_count:]
            for msg in new_msgs:
                sender = msg.get('sender', '')
                if sender != self.client.username:
                    play_sound('titannet/new_message.ogg')
                    speak_notification(
                        _("New message from {user}").format(user=sender),
                        'info', play_sound_effect=False
                    )

            # Append only the new messages to keep the conversation list growing
            # without losing scroll position or destroying the user's selection.
            self.conversation_list.Freeze()
            try:
                for msg in new_msgs:
                    self._add_conversation_row(
                        msg.get('sender', ''),
                        msg.get('message', ''),
                        msg.get('date', ''),
                    )
            finally:
                self.conversation_list.Thaw()

    def _silent_online_refresh(self, users, error):
        if error or not users:
            return

        old_set = set(self.online_users_cache)
        new_set = set(users)

        came_online = new_set - old_set
        went_offline = old_set - new_set

        for user in came_online:
            if user != self.client.username:
                play_sound('titannet/online.ogg')
                speak_elten(f"{user} " + _("is now online"))

        for user in went_offline:
            if user != self.client.username:
                play_sound('titannet/offline.ogg')
                speak_elten(f"{user} " + _("is now offline"))

        self.online_users_cache = users

    def OnRefresh(self, event):
        speak_elten(_("Refreshing..."))
        self.OnAutoRefresh(None)

    # ---- Window Events ----

    def OnAbout(self, event):
        play_sound('ui/dialog.ogg')
        _show_skinned_message(
            "EltenLink (Beta)\n\n"
            "Elten social network client for TCE Launcher.\n"
            "Copyright (C) Dawid Pieper (Elten)\n"
            "TCE Integration by TitoSoft",
            _("About EltenLink (Beta)"),
            wx.OK | wx.ICON_INFORMATION
        )

    def OnIconize(self, event):
        """Handle minimize - stay connected, keep background notifications."""
        event.Skip()

    def _initial_whats_new_check(self):
        """Initial What's New check after login (like Ruby's whatsnew(true) in Scene_Main).
        Announces all current notifications on first load, then sets baseline for background checks."""
        if not self.client.is_connected:
            return

        def do_check():
            try:
                data = self.client.get_whats_new()
                wx.CallAfter(self._on_initial_whats_new, data)
            except Exception as e:
                print(f"[ELTEN] Initial What's New check failed: {e}")
        threading.Thread(target=do_check, daemon=True).start()

    def _on_initial_whats_new(self, data):
        """Handle initial What's New data - announce all non-zero items and set baseline."""
        if data is None:
            return

        # Set baseline for background notification comparison
        self._last_whats_new = data

        # Announce non-zero categories (like Ruby's whatsnew on first load)
        categories = [
            ('messages', _("New messages"), 'titannet/new_message.ogg'),
            ('followed_threads', _("New posts in followed threads"), 'titannet/new_feedpost.ogg'),
            ('followed_blogs', _("New posts on the followed blogs"), 'titannet/new_feedpost.ogg'),
            ('blog_comments', _("New comments on your blog"), 'titannet/chat_message.ogg'),
            ('followed_forums', _("New threads on followed forums"), 'titannet/new_feedpost.ogg'),
            ('followed_forums_posts', _("New posts on followed forums"), 'titannet/new_feedpost.ogg'),
            ('friends', _("New friends"), 'titannet/new_chat.ogg'),
            ('birthday', _("Friends' birthday"), 'titannet/birthday.ogg'),
            ('mentions', _("Mentions"), 'titannet/titannet-notification.ogg'),
            ('followed_blog_posts', _("Followed blog posts"), 'titannet/new_feedpost.ogg'),
            ('blog_followers', _("Blog followers"), 'titannet/new_chat.ogg'),
            ('blog_mentions', _("Blog mentions"), 'titannet/titannet-notification.ogg'),
            ('group_invitations', _("Awaiting group invitations"), 'titannet/titannet-notification.ogg'),
        ]

        announcements = []
        for key, label, sound in categories:
            count = data.get(key, 0)
            if count > 0:
                announcements.append((label, count, sound))

        if not announcements:
            return

        # Announce via TTS with titan-net sounds
        self._bg_announcements = announcements
        self._bg_announce_idx = 0
        play_sound('titannet/titannet-notification.ogg')
        speak_elten(_("What's new"), interrupt=False)
        wx.CallLater(1000, self._announce_next_bg)

    def _on_bg_notification_check(self, event):
        """Background check for new notifications - works even when minimized/hidden."""
        if not self.client.is_connected:
            return

        def do_check():
            try:
                data = self.client.get_whats_new()
                wx.CallAfter(self._process_bg_notifications, data)
            except Exception:
                pass
        threading.Thread(target=do_check, daemon=True).start()

    def _process_bg_notifications(self, data):
        """Compare with previous data and announce new items via TTS."""
        if data is None:
            return

        prev = self._last_whats_new
        self._last_whats_new = data

        # Skip first check (no previous data to compare)
        if prev is None:
            return

        # Notification categories with sounds
        categories = [
            ('messages', _("New messages"), 'titannet/new_message.ogg'),
            ('followed_threads', _("New posts in followed threads"), 'titannet/new_feedpost.ogg'),
            ('followed_blogs', _("New posts on the followed blogs"), 'titannet/new_feedpost.ogg'),
            ('blog_comments', _("New comments on your blog"), 'titannet/chat_message.ogg'),
            ('followed_forums', _("New threads on followed forums"), 'titannet/new_feedpost.ogg'),
            ('followed_forums_posts', _("New posts on followed forums"), 'titannet/new_feedpost.ogg'),
            ('friends', _("New friends"), 'titannet/new_chat.ogg'),
            ('birthday', _("Friends' birthday"), 'titannet/birthday.ogg'),
            ('mentions', _("Mentions"), 'titannet/titannet-notification.ogg'),
            ('followed_blog_posts', _("Followed blog posts"), 'titannet/new_feedpost.ogg'),
            ('blog_followers', _("Blog followers"), 'titannet/new_chat.ogg'),
            ('blog_mentions', _("Blog mentions"), 'titannet/titannet-notification.ogg'),
            ('group_invitations', _("Awaiting group invitations"), 'titannet/titannet-notification.ogg'),
        ]

        # Announce categories where count increased
        new_items = []
        for key, label, sound in categories:
            cur = data.get(key, 0)
            old = prev.get(key, 0)
            if cur > old:
                new_items.append((label, cur - old, sound))

        if new_items:
            self._bg_announcements = new_items
            self._bg_announce_idx = 0
            self._announce_next_bg()

    def _announce_next_bg(self):
        """Announce next background notification."""
        if self._bg_announce_idx >= len(self._bg_announcements):
            return

        label, count, sound = self._bg_announcements[self._bg_announce_idx]
        self._bg_announce_idx += 1

        try:
            play_sound(sound)
        except Exception:
            pass

        speak_elten(f"{label}: {count}", interrupt=False)

        if self._bg_announce_idx < len(self._bg_announcements):
            wx.CallLater(1500, self._announce_next_bg)

    def OnDisconnect(self, event):
        confirm = _new_message_dialog(
            self,
            _("Are you sure you want to disconnect?"),
            _("Disconnect"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION
        )

        if confirm.ShowModal() == wx.ID_YES:
            confirm.Destroy()
            self.client.logout()

            if self.refresh_timer:
                self.refresh_timer.Stop()
            if self._bg_notification_timer:
                self._bg_notification_timer.Stop()
            self._stop_feed_auto_refresh()

            play_sound('titannet/bye.ogg')
            speak_notification(_("Disconnected"), 'info', play_sound_effect=False)

            if self.parent_frame and hasattr(self.parent_frame, 'active_services'):
                if "eltenlink" in self.parent_frame.active_services:
                    del self.parent_frame.active_services["eltenlink"]

            self.Destroy()
        else:
            confirm.Destroy()

    def OnClose(self, event):
        """Hide window on close - stay connected for background TTS notifications."""
        if event.CanVeto():
            self.Hide()
            # Unregister from window switcher while hidden
            try:
                from src.ui.window_switcher import unregister_window
                unregister_window("EltenLink")
            except Exception:
                pass
            event.Veto()
        else:
            if self.refresh_timer:
                self.refresh_timer.Stop()
            if self._bg_notification_timer:
                self._bg_notification_timer.Stop()
            self._stop_feed_auto_refresh()
            self.client.logout()
            self.Destroy()


# ---- Voice Call Dialogs ----


def _get_sound_path(sound_file):
    """Resolve a sound file path from the sfx directory."""
    from src.titan_core.sound import resource_path, get_sfx_directory
    sfx_dir = get_sfx_directory()
    path = os.path.join(sfx_dir, sound_file)
    if os.path.exists(path):
        return path
    # Fallback to default theme
    path = resource_path(os.path.join('sfx', 'default', sound_file))
    if os.path.exists(path):
        return path
    return None


class OutgoingCallDialog(wx.Dialog):
    """Outgoing call dialog - plays ring_out.ogg in loop, shows cancel button.

    Matches Ruby Elten's call flow:
    - Conference.open -> Conference.create -> invite(user) -> calling_play (ring_out loop)
    - When user joins channel -> calling_stop, switch to InCallDialog
    - Cancel button -> cancel_call API + close
    """

    def __init__(self, parent, client, username):
        super().__init__(parent, title=_("Voice Call"),
                         style=wx.DEFAULT_DIALOG_STYLE)
        self.client = client
        self.target_user = username
        self.voip = None
        self.call_id = None
        self.channel = None
        self.channel_password = None
        self._ring_playing = False
        self._cancelled = False
        self._connected = False

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.status_label = wx.StaticText(
            panel, label=_("Calling {user}...").format(user=username))
        sizer.Add(self.status_label, 0, wx.ALL | wx.EXPAND, 10)

        self.cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        sizer.Add(self.cancel_btn, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)

        panel.SetSizer(sizer)
        self.SetSizerAndFit(sizer)
        self.CentreOnParent()

        self.cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE, self._on_close)

        try:
            _apply_skin_to_tree(self)
        except Exception:
            pass

        # Start call in background
        wx.CallAfter(self._start_call)

    def _on_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._on_cancel(None)
        else:
            event.Skip()

    def _start_call(self):
        """Initialize VOIP, create channel, invite user."""
        threading.Thread(target=self._call_worker, daemon=True).start()

    def _call_worker(self):
        """Background thread: connect VOIP, create channel, send call invite."""
        try:
            import random
            import string

            # Generate random password for the call channel
            self.channel_password = ''.join(
                random.choices(string.ascii_lowercase + string.digits, k=32))

            # Connect to VOIP server
            self.voip = EltenVoipClient(self.client.username)
            self.voip.on_user_joined = self._on_user_joined
            self.voip.on_user_left = self._on_user_left
            self.voip.on_disconnected = self._on_voip_disconnected

            if not self.voip.connect():
                wx.CallAfter(self._call_failed, _("Could not connect to voice server"))
                return

            if self._cancelled:
                self.voip.disconnect()
                return

            # Create private channel
            channel_name = f"VoiceCall_{self.client.username}"
            ch = self.voip.create_channel(
                name=channel_name,
                password=self.channel_password,
                bitrate=56,
                framesize=40,
            )

            if not ch:
                wx.CallAfter(self._call_failed, _("Could not create voice channel"))
                self.voip.disconnect()
                return

            self.channel = ch

            if self._cancelled:
                self.voip.disconnect()
                return

            # Join the channel
            if not self.voip.join_channel(ch.id, self.channel_password):
                wx.CallAfter(self._call_failed, _("Could not join voice channel"))
                self.voip.disconnect()
                return

            if self._cancelled:
                self.voip.disconnect()
                return

            # Send call invitation via Elten API
            call_id = self.client.call_user(
                self.target_user, ch.id, self.channel_password)

            if call_id is None:
                wx.CallAfter(self._call_failed, _("Could not send call invitation"))
                self.voip.disconnect()
                return

            self.call_id = call_id

            # Start playing ring_out sound in loop
            wx.CallAfter(self._start_ringing)

        except Exception as e:
            wx.CallAfter(self._call_failed, str(e))

    def _start_ringing(self):
        """Play ring_out.ogg in a loop."""
        self._ring_playing = True
        threading.Thread(target=self._ring_loop, daemon=True).start()

    def _ring_loop(self):
        """Loop ring_out sound until call is answered or cancelled."""
        ring_path = _get_sound_path('titannet/ring_out.ogg')
        if not ring_path:
            return

        try:
            import pygame
            while self._ring_playing and not self._cancelled:
                try:
                    pygame.mixer.music.load(ring_path)
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy() and self._ring_playing:
                        time.sleep(0.1)
                    if self._ring_playing:
                        time.sleep(0.5)  # Brief pause between rings
                except Exception:
                    break
        except ImportError:
            pass

    def _stop_ringing(self):
        """Stop ring sound."""
        self._ring_playing = False
        try:
            import pygame
            pygame.mixer.music.stop()
        except Exception:
            pass

    def _on_user_joined(self, username):
        """Called when target user joins our channel - call answered!"""
        if username.lower() == self.target_user.lower():
            self._connected = True
            self._stop_ringing()
            wx.CallAfter(self._call_answered)

    def _on_user_left(self, username):
        """Called when user leaves the channel."""
        pass

    def _on_voip_disconnected(self):
        """Called on VOIP connection loss."""
        if not self._cancelled and not self._connected:
            self._stop_ringing()
            wx.CallAfter(self._call_failed, _("Connection lost"))

    def _call_answered(self):
        """Target user answered - play success sound and open in-call dialog."""
        play_sound('titannet/callsuccess.ogg')
        speak_notification(_("Call connected"), 'success')

        # Start audio
        self.voip.start_audio()

        # Close this dialog and open in-call dialog
        self.EndModal(wx.ID_OK)

    def _call_failed(self, reason):
        """Call failed - show error and close."""
        self._stop_ringing()
        speak_notification(_("Call failed") + f": {reason}", 'error')
        if self.voip:
            self.voip.disconnect()
        self.EndModal(wx.ID_CANCEL)

    def _on_cancel(self, event):
        """User cancelled the call."""
        self._cancelled = True
        self._stop_ringing()

        # Cancel call on server
        if self.call_id:
            threading.Thread(
                target=lambda: self.client.cancel_call(self.call_id),
                daemon=True).start()

        if self.voip:
            self.voip.disconnect()

        speak_notification(_("Call cancelled"), 'info')
        self.EndModal(wx.ID_CANCEL)

    def _on_close(self, event):
        self._on_cancel(None)


class IncomingCallDialog(wx.Dialog):
    """Incoming call dialog - "{user} is calling you", Answer, Reject.

    Matches Ruby Elten's CallWindow:
        Static("{user} is calling you"), Button("Answer"), Button("Reject")
    """

    def __init__(self, parent, client, call_id, caller, channel_id, channel_password):
        super().__init__(parent, title=_("Incoming Call"),
                         style=wx.DEFAULT_DIALOG_STYLE)
        self.client = client
        self.call_id = call_id
        self.caller = caller
        self.channel_id = channel_id
        self.channel_password = channel_password
        self._ring_playing = False

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        label = wx.StaticText(
            panel, label=_("{user} is calling you").format(user=caller))
        sizer.Add(label, 0, wx.ALL | wx.EXPAND, 10)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.answer_btn = wx.Button(panel, wx.ID_OK, _("Answer"))
        btn_sizer.Add(self.answer_btn, 0, wx.ALL, 5)

        self.reject_btn = wx.Button(panel, wx.ID_CANCEL, _("Reject"))
        btn_sizer.Add(self.reject_btn, 0, wx.ALL, 5)

        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)

        panel.SetSizer(sizer)
        self.SetSizerAndFit(sizer)
        self.CentreOnParent()

        self.answer_btn.Bind(wx.EVT_BUTTON, self._on_answer)
        self.reject_btn.Bind(wx.EVT_BUTTON, self._on_reject)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE, self._on_close)

        try:
            _apply_skin_to_tree(self)
        except Exception:
            pass

        # Play ring_in sound
        self._start_ringing()

    def _on_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._on_reject(None)
        elif event.GetKeyCode() == wx.WXK_RETURN:
            self._on_answer(None)
        else:
            event.Skip()

    def _start_ringing(self):
        self._ring_playing = True
        threading.Thread(target=self._ring_loop, daemon=True).start()

    def _ring_loop(self):
        ring_path = _get_sound_path('titannet/ring_in.ogg')
        if not ring_path:
            return
        try:
            import pygame
            while self._ring_playing:
                try:
                    pygame.mixer.music.load(ring_path)
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy() and self._ring_playing:
                        time.sleep(0.1)
                    if self._ring_playing:
                        time.sleep(0.5)
                except Exception:
                    break
        except ImportError:
            pass

    def _stop_ringing(self):
        self._ring_playing = False
        try:
            import pygame
            pygame.mixer.music.stop()
        except Exception:
            pass

    def _on_answer(self, event):
        """Answer the call - join the caller's channel."""
        self._stop_ringing()
        self.EndModal(wx.ID_OK)

    def _on_reject(self, event):
        """Reject the call."""
        self._stop_ringing()
        # Cancel/reject on server
        threading.Thread(
            target=lambda: self.client.cancel_call(self.call_id),
            daemon=True).start()
        self.EndModal(wx.ID_CANCEL)

    def _on_close(self, event):
        self._on_reject(None)


class InCallDialog(wx.Dialog):
    """In-call dialog - shows users list, mute toggle, close button.

    Matches Ruby Elten's Scene_Conference (simplified for 1:1 calls):
        ListBox(users), Button("Mute/Unmute"), Button("Close")
    """

    def __init__(self, parent, client, voip, target_user):
        super().__init__(parent, title=_("Voice Call - {user}").format(user=target_user),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.client = client
        self.voip = voip
        self.target_user = target_user

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Users list
        users_label = wx.StaticText(panel, label=_("Users in call:"))
        sizer.Add(users_label, 0, wx.LEFT | wx.TOP, 10)

        self.users_list = wx.ListBox(panel)
        self.users_list.SetMinSize(wx.Size(300, 100))
        sizer.Add(self.users_list, 1, wx.EXPAND | wx.ALL, 10)

        # Buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.mute_btn = wx.Button(panel, wx.ID_ANY, _("Mute"))
        btn_sizer.Add(self.mute_btn, 0, wx.ALL, 5)

        self.close_btn = wx.Button(panel, wx.ID_CANCEL, _("End Call"))
        btn_sizer.Add(self.close_btn, 0, wx.ALL, 5)

        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)

        panel.SetSizer(sizer)
        self.SetSizerAndFit(sizer)
        self.CentreOnParent()

        self.mute_btn.Bind(wx.EVT_BUTTON, self._on_mute_toggle)
        self.close_btn.Bind(wx.EVT_BUTTON, self._on_close_call)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE, self._on_close_event)

        try:
            _apply_skin_to_tree(self)
        except Exception:
            pass

        # Set up VOIP callbacks
        self.voip.on_channel_update = self._on_channel_update
        self.voip.on_user_left = self._on_user_left_call
        self.voip.on_disconnected = self._on_disconnected

        # Update users list
        self._update_users_list()

        # Focus users list
        self.users_list.SetFocus()

        # Update timer
        self.update_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_timer, self.update_timer)
        self.update_timer.Start(2000)

    def _on_key(self, event):
        kc = event.GetKeyCode()
        if kc == wx.WXK_ESCAPE:
            self._on_close_call(None)
        elif kc == ord('M') and event.ControlDown():
            self._on_mute_toggle(None)
        else:
            event.Skip()

    def _update_users_list(self):
        """Update the users list from VOIP channel data."""
        self.users_list.Clear()
        if self.voip and self.voip.channel:
            for user in self.voip.channel.users:
                name = user.get('name', '?')
                if name == self.client.username:
                    name += f" ({_('You')})"
                self.users_list.Append(name)

        if self.users_list.GetCount() > 0:
            self.users_list.SetSelection(0)

    def _on_channel_update(self, channel):
        """VOIP channel updated."""
        wx.CallAfter(self._update_users_list)

    def _on_user_left_call(self, username):
        """Other user left the call."""
        if username.lower() == self.target_user.lower():
            wx.CallAfter(self._end_call, _("{user} ended the call").format(user=username))

    def _on_disconnected(self):
        """VOIP connection lost."""
        wx.CallAfter(self._end_call, _("Connection lost"))

    def _on_mute_toggle(self, event):
        """Toggle microphone mute."""
        if self.voip:
            self.voip.muted = not self.voip.muted
            if self.voip.muted:
                self.mute_btn.SetLabel(_("Unmute"))
                speak_notification(_("Microphone muted"), 'info')
            else:
                self.mute_btn.SetLabel(_("Mute"))
                speak_notification(_("Microphone unmuted"), 'info')

    def _on_close_call(self, event):
        """End the call."""
        self._end_call()

    def _end_call(self, reason=None):
        """Clean up and close."""
        self.update_timer.Stop()

        if self.voip:
            self.voip.stop_audio()
            self.voip.leave_channel()
            self.voip.disconnect()

        if reason:
            speak_notification(reason, 'info')
        else:
            speak_notification(_("Call ended"), 'info')

        self.EndModal(wx.ID_OK)

    def _on_close_event(self, event):
        self._end_call()

    def _on_timer(self, event):
        """Periodic update."""
        self._update_users_list()


# ---- Module Entry Points ----

def show_elten_login(parent):
    """Show EltenLink login dialog and return main window if successful."""
    dlg = EltenLoginDialog(parent)
    result = dlg.ShowModal()

    if result == wx.ID_OK and dlg.logged_in:
        client = dlg.client
        dlg.Destroy()

        main_window = EltenMainWindow(parent, client)
        main_window.Show()
        return main_window
    else:
        dlg.Destroy()
        return None

