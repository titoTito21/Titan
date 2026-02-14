# -*- coding: utf-8 -*-
import wx
import threading
import time
import accessible_output3.outputs.auto
from src.network.telegram_client import (
    telegram_client, connect_to_server, disconnect_from_server, send_message,
    get_online_users, get_contacts, get_group_chats, get_chat_history,
    get_group_chat_history, is_connected, get_user_data,
    start_voice_call, is_call_active, is_voice_calls_available
)
from src.titan_core.sound import play_sound
from src.titan_core.translation import set_language
from src.settings.settings import get_setting

try:
    from src.titan_core.stereo_speech import speak_stereo, get_stereo_speech
    STEREO_SPEECH_AVAILABLE = True
except ImportError:
    STEREO_SPEECH_AVAILABLE = False

# Get translation function
_ = set_language(get_setting('language', 'pl'))
_speaker = accessible_output3.outputs.auto.Auto()


def speak_telegram(text, position=0.0, pitch_offset=0, interrupt=True):
    """Speak text using stereo speech / ao3 for Telegram notifications."""
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
                    _speaker.output(text)
            threading.Thread(target=do_speak, daemon=True).start()
        else:
            def do_speak():
                try:
                    if interrupt and hasattr(_speaker, 'stop'):
                        _speaker.stop()
                    _speaker.output(text)
                except Exception:
                    pass
            threading.Thread(target=do_speak, daemon=True).start()
    except Exception:
        try:
            _speaker.output(text)
        except Exception:
            pass

class TelegramLoginDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Connect to Telegram"), size=(400, 250))

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Info text
        info_text = wx.StaticText(panel, label=_(
            "To connect to Telegram, enter your phone number.\n"
            "You will receive a verification code by SMS."
        ))
        sizer.Add(info_text, 0, wx.ALL, 10)

        # Phone number input
        phone_label = wx.StaticText(panel, label=_("Phone number (with country code, e.g. +48123456789):"))
        sizer.Add(phone_label, 0, wx.ALL, 5)

        self.phone_ctrl = wx.TextCtrl(panel)
        # Try to get last used phone number
        try:
            from src.network.telegram_client import get_last_phone_number
            last_phone = get_last_phone_number()
            if last_phone:
                self.phone_ctrl.SetValue(last_phone)
        except:
            pass
        sizer.Add(self.phone_ctrl, 0, wx.EXPAND | wx.ALL, 5)

        # 2FA password (optional)
        password_label = wx.StaticText(panel, label=_("2FA Password (optional, leave empty if not set):"))
        sizer.Add(password_label, 0, wx.ALL, 5)

        self.password_ctrl = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
        sizer.Add(self.password_ctrl, 0, wx.EXPAND | wx.ALL, 5)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        login_btn = wx.Button(panel, wx.ID_OK, _("Connect"))
        button_sizer.Add(login_btn, 0, wx.ALL, 5)

        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        button_sizer.Add(cancel_btn, 0, wx.ALL, 5)

        sizer.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        panel.SetSizer(sizer)
        self.Centre()

    def get_credentials(self):
        password = self.password_ctrl.GetValue().strip()
        return (
            self.phone_ctrl.GetValue().strip(),
            password if password else None
        )

class TelegramChatWindow(wx.Frame):
    def __init__(self, parent, username):
        super().__init__(parent, title=f"Telegram - {username}", size=(600, 500))

        self.username = username
        self.current_view = "menu"  # menu, contacts, groups
        self.contacts_cache = []
        self.groups_cache = []
        self.force_close = False  # Flag to force window close (on disconnect)

        # Setup GUI
        self.setup_ui()

        # Setup callbacks
        telegram_client.add_message_callback(self.on_message_received)
        telegram_client.add_status_callback(self.on_status_change)

        self.Centre()

        # Show main menu (will play welcome sound)
        self.show_main_menu(initial=True)

        # Update users list periodically
        self.update_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.update_users_periodically, self.update_timer)
        self.update_timer.Start(5000)  # Update every 5 seconds
    
    def setup_ui(self):
        """Setup UI - simple list interface like main TCE GUI"""
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Title label
        self.title_label = wx.StaticText(panel, label="Telegram")
        self.title_label.SetFont(wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        sizer.Add(self.title_label, 0, wx.ALL, 10)

        # Main list box
        self.main_list = wx.ListBox(panel, style=wx.LB_SINGLE | wx.WANTS_CHARS)
        self.main_list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_item_activated)
        self.main_list.Bind(wx.EVT_KEY_DOWN, self.on_key_press)
        self.main_list.Bind(wx.EVT_CHAR, self.on_char)
        self.main_list.Bind(wx.EVT_LISTBOX, self.on_list_selection)
        self.main_list.Bind(wx.EVT_RIGHT_DOWN, self.on_right_click)
        sizer.Add(self.main_list, 1, wx.EXPAND | wx.ALL, 10)

        panel.SetSizer(sizer)

        # Menu bar
        menubar = wx.MenuBar()

        # Telegram menu
        telegram_menu = wx.Menu()
        disconnect_item = telegram_menu.Append(wx.ID_ANY, _("Disconnect"), _("Disconnect from Telegram"))
        self.Bind(wx.EVT_MENU, self.on_disconnect, disconnect_item)

        menubar.Append(telegram_menu, "Telegram")
        self.SetMenuBar(menubar)

        # Status bar
        self.CreateStatusBar()
        self.SetStatusText(_("Connected to Telegram"))

        # Bind close event
        self.Bind(wx.EVT_CLOSE, self.on_close)

        # Bind iconize event to prevent disconnection on minimize
        self.Bind(wx.EVT_ICONIZE, self.on_iconize)

        self.main_list.SetFocus()
    
    def show_main_menu(self, initial=False):
        """Show main Telegram menu"""
        self.current_view = "menu"
        self.title_label.SetLabel("Telegram - Menu")
        self.main_list.Clear()

        self.main_list.Append(_("Contacts"))
        self.main_list.Append(_("Groups"))
        self.main_list.Append(_("Settings"))
        self.main_list.Append(_("Disconnect"))

        if self.main_list.GetCount() > 0:
            self.main_list.SetSelection(0)
            self.main_list.SetFocus()

        # Play welcome sound on initial load, popup close sound when returning from sub-menu
        if initial:
            play_sound('titannet/welcome to IM.ogg')
        else:
            play_sound('ui/popup.ogg')  # Popup close sound

    def show_contacts_view(self):
        """Show contacts list"""
        self.current_view = "contacts"
        self.title_label.SetLabel(_("Contacts"))
        self.main_list.Clear()

        # Refresh contacts
        contacts = get_contacts()
        self.contacts_cache = contacts

        for contact in contacts:
            if contact.get('username') != self.username:
                username = contact.get('username', 'Unknown')
                self.main_list.Append(username)

        self.main_list.Append(_("Back"))

        if self.main_list.GetCount() > 0:
            self.main_list.SetSelection(0)
            self.main_list.SetFocus()

        play_sound('ui/popup.ogg')

    def show_groups_view(self):
        """Show groups list"""
        self.current_view = "groups"
        self.title_label.SetLabel(_("Groups"))
        self.main_list.Clear()

        # Refresh groups
        groups = get_group_chats()
        self.groups_cache = groups

        for group in groups:
            group_name = group.get('name') or group.get('title', 'Unknown Group')
            self.main_list.Append(group_name)

        self.main_list.Append(_("Back"))

        if self.main_list.GetCount() > 0:
            self.main_list.SetSelection(0)
            self.main_list.SetFocus()

        play_sound('ui/popup.ogg')

    def on_list_selection(self, event):
        """Handle list selection change"""
        event.Skip()

    def on_right_click(self, event):
        """Handle right-click on list for context menu."""
        if self.current_view == "contacts":
            # Select item under cursor
            pos = event.GetPosition()
            item = self.main_list.HitTest(pos)
            if item != wx.NOT_FOUND:
                self.main_list.SetSelection(item)
            self.show_contact_context_menu()
        else:
            event.Skip()

    def on_char(self, event):
        """Handle character events"""
        keycode = event.GetKeyCode()
        print(f"[TELEGRAM GUI] CHAR event: {keycode}")

        # Try to handle Enter here too
        if keycode == wx.WXK_RETURN or keycode == 13:
            print("[TELEGRAM GUI] Enter in CHAR event - activating")
            selection = self.main_list.GetSelection()
            if selection != wx.NOT_FOUND:
                selected_text = self.main_list.GetString(selection)
                self.activate_item(selected_text)
            return  # Don't skip
        event.Skip()

    def on_key_press(self, event):
        """Handle key press events"""
        keycode = event.GetKeyCode()

        # Enter key - only handle actual Enter key, not Alt
        if (keycode == wx.WXK_RETURN or keycode == wx.WXK_NUMPAD_ENTER) and not event.AltDown():
            selection = self.main_list.GetSelection()
            if selection != wx.NOT_FOUND:
                selected_text = self.main_list.GetString(selection)
                self.activate_item(selected_text)
            return
        elif keycode == wx.WXK_ESCAPE or keycode == wx.WXK_BACK:
            if self.current_view != "menu":
                self.show_main_menu()
            else:
                self.Hide()
        elif keycode == ord('P') and event.ControlDown():
            # Ctrl+P = Voice call (only in contacts view)
            if self.current_view == "contacts":
                self.start_call_for_selected()
            return
        elif keycode == wx.WXK_WINDOWS_MENU or (keycode == wx.WXK_F10 and event.ShiftDown()):
            # Apps key or Shift+F10 = Context menu
            if self.current_view == "contacts":
                self.show_contact_context_menu()
            return
        elif keycode in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_LEFT, wx.WXK_RIGHT):
            # Navigation keys - check for edge and play appropriate sound
            selection = self.main_list.GetSelection()
            count = self.main_list.GetCount()

            # Check if at edge
            at_top = (selection == 0 or selection == wx.NOT_FOUND) and keycode in (wx.WXK_UP, wx.WXK_LEFT)
            at_bottom = (selection == count - 1) and keycode in (wx.WXK_DOWN, wx.WXK_RIGHT)

            if at_top or at_bottom:
                # At edge - play edge sound and don't move
                play_sound('ui/endoflist.ogg')
                return  # Don't skip - prevent movement
            else:
                # Not at edge - allow movement and play focus sound
                event.Skip()
                wx.CallAfter(self.play_focus_sound)
        elif keycode in (wx.WXK_HOME, wx.WXK_END, wx.WXK_PAGEUP, wx.WXK_PAGEDOWN):
            # Other navigation keys - play focus sound
            event.Skip()
            wx.CallAfter(self.play_focus_sound)
        else:
            event.Skip()

    def play_focus_sound(self):
        """Play focus sound when navigating"""
        play_sound('core/focus.ogg')

    def on_item_activated(self, event):
        """Handle item activation (double-click)"""
        selection = self.main_list.GetSelection()
        if selection == wx.NOT_FOUND:
            return

        selected_text = self.main_list.GetString(selection)
        self.activate_item(selected_text)

    def activate_item(self, selected_text):
        """Activate an item by text (used by both Enter and double-click)"""
        play_sound('core/SELECT.ogg')

        if self.current_view == "menu":
            # Main menu
            if selected_text == _("Contacts"):
                self.show_contacts_view()
            elif selected_text == _("Groups"):
                self.show_groups_view()
            elif selected_text == _("Settings"):
                wx.MessageBox(_("Settings - coming soon"), _("Information"), wx.OK | wx.ICON_INFORMATION)
            elif selected_text == _("Disconnect"):
                self.on_disconnect(None)

        elif self.current_view == "contacts":
            # Contacts list
            if selected_text == _("Back"):
                self.show_main_menu()
            else:
                # Open private message window
                self.open_private_message_window(selected_text)

        elif self.current_view == "groups":
            # Groups list
            if selected_text == _("Back"):
                self.show_main_menu()
            else:
                # Open group chat window
                self.open_group_chat_window(selected_text)

    def show_contact_context_menu(self):
        """Show context menu for selected contact with Message and Call options."""
        selection = self.main_list.GetSelection()
        if selection == wx.NOT_FOUND:
            return

        selected_text = self.main_list.GetString(selection)
        if selected_text == _("Back"):
            return

        menu = wx.Menu()
        msg_item = menu.Append(wx.ID_ANY, _("Message"))
        call_item = menu.Append(wx.ID_ANY, _("Voice Call") + " (Ctrl+P)")

        self.Bind(wx.EVT_MENU, lambda evt: self.open_private_message_window(selected_text), msg_item)
        self.Bind(wx.EVT_MENU, lambda evt: self.start_call_for_contact(selected_text), call_item)

        # Show at list position
        rect = self.main_list.GetRect()
        self.PopupMenu(menu, wx.Point(rect.x + 10, rect.y + (selection * 20) + 10))
        menu.Destroy()

    def start_call_for_selected(self):
        """Start voice call for the currently selected contact."""
        selection = self.main_list.GetSelection()
        if selection == wx.NOT_FOUND:
            return

        selected_text = self.main_list.GetString(selection)
        if selected_text == _("Back"):
            return

        self.start_call_for_contact(selected_text)

    def start_call_for_contact(self, username):
        """Start a voice call with the given contact."""
        if is_call_active():
            speak_telegram(_("Call already in progress"), position=0.7, pitch_offset=5)
            return

        if not is_voice_calls_available():
            speak_telegram(_("Voice calls not available - py-tgcalls required"), position=0.7, pitch_offset=5)
            wx.MessageBox(
                _("Voice calls require py-tgcalls.\nInstall with: pip install py-tgcalls"),
                _("Voice calls unavailable"),
                wx.OK | wx.ICON_INFORMATION
            )
            return

        play_sound('core/SELECT.ogg')
        speak_telegram(_("Calling {}...").format(username), position=0.0, pitch_offset=0)

        # Start the call
        start_voice_call(username)

        # Open voice call window
        from src.network import telegram_windows
        telegram_windows.open_voice_call_window(self, username, 'outgoing')

    def open_private_message_window(self, username):
        """Open private message window using telegram_windows"""
        try:
            from src.network import telegram_windows
            telegram_windows.open_private_message_window(self, username)
            # Sound is played in telegram_windows.TelegramPrivateMessageWindow.__init__
        except Exception as e:
            print(f"Error opening private message window: {e}")
            wx.MessageBox(
                _("Cannot open chat window.\nError: {error}").format(error=str(e)),
                _("Error"),
                wx.OK | wx.ICON_ERROR
            )

    def open_group_chat_window(self, group_name):
        """Open group chat window using telegram_windows"""
        try:
            from src.network import telegram_windows
            telegram_windows.open_group_chat_window(self, group_name)
            # Sound is played in telegram_windows.TelegramGroupChatWindow.__init__
        except Exception as e:
            print(f"Error opening group chat window: {e}")
            wx.MessageBox(
                _("Cannot open chat window.\nError: {error}").format(error=str(e)),
                _("Error"),
                wx.OK | wx.ICON_ERROR
            )

    def update_users_periodically(self, event):
        """Update contacts and groups caches periodically"""
        # Silently refresh caches in background
        try:
            self.contacts_cache = get_contacts()
            self.groups_cache = get_group_chats()
        except:
            pass

    def on_message_received(self, message_data):
        """Background TTS notifications with titan-net sounds - works even without chat windows open."""
        if not message_data:
            return

        msg_type = message_data.get('type')
        if msg_type != 'new_message':
            return

        sender = message_data.get('sender_username', '')
        message = message_data.get('message', '')
        is_group = message_data.get('is_group', False)
        group_name = message_data.get('group_name', '')

        if not sender or not message:
            return

        def do_notify():
            # Different titan-net sounds for private vs group
            if is_group:
                try:
                    play_sound('titannet/chat_message.ogg')
                except Exception:
                    pass
                text = f"{group_name} - {sender}: {message}"
            else:
                try:
                    play_sound('titannet/new_message.ogg')
                except Exception:
                    pass
                text = f"{sender}: {message}"

            if len(text) > 120:
                text = text[:120] + "..."
            speak_telegram(text, position=-0.3, pitch_offset=-2, interrupt=False)

        wx.CallAfter(do_notify)

    def on_status_change(self, status_type, data):
        """Handle status changes"""
        print(f"[TELEGRAM GUI] on_status_change: {status_type}")
        if status_type == 'connection_success':
            self.SetStatusText(_("Connected to Telegram"))
            print("[TELEGRAM GUI] Connection successful")
        elif status_type == 'dialogs_loaded':
            # Dialogs loaded - refresh caches
            print(f"[TELEGRAM GUI] Dialogs loaded callback received! {len(data)} dialogs")
            wx.CallAfter(self.update_users_periodically, None)
    
    def on_disconnect(self, event):
        """Disconnect from Telegram and close window"""
        print("[TELEGRAM GUI] User requested disconnect")
        # Set force_close flag to actually close the window
        self.force_close = True
        # Close the window
        self.Close()

    def on_iconize(self, event):
        """Handle window minimize/iconize - keep connection alive"""
        is_iconized = event.IsIconized()
        if is_iconized:
            print("[TELEGRAM GUI] Window minimized - staying connected")
        else:
            print("[TELEGRAM GUI] Window restored")

        # Always allow the event to proceed
        event.Skip()

    def on_close(self, event):
        """Handle window close - hide instead of close unless force_close is set"""
        try:
            # Check if user wants to force close (disconnect)
            if self.force_close:
                print("[TELEGRAM GUI] Force close - disconnecting")
                # Stop timer first
                if hasattr(self, 'update_timer') and self.update_timer:
                    try:
                        self.update_timer.Stop()
                    except:
                        pass

                # Disconnect from Telegram
                try:
                    disconnect_from_server()
                except Exception as e:
                    print(f"Error during disconnect: {e}")

                # Allow window to close
                event.Skip()
            else:
                # Just hide the window (minimize to background)
                print("[TELEGRAM GUI] Hiding window (staying connected)")
                self.Hide()
                # Veto the close event to prevent destruction
                if event.CanVeto():
                    event.Veto()

        except Exception as e:
            print(f"Error during window close: {e}")
            # Allow close to proceed if there's an error
            event.Skip()

def show_telegram_login(parent=None):
    """Show Telegram login dialog"""
    login_dialog = TelegramLoginDialog(parent)

    if login_dialog.ShowModal() == wx.ID_OK:
        phone_number, password = login_dialog.get_credentials()
        login_dialog.Destroy()

        if phone_number:
            print(f"[TELEGRAM GUI] Connecting with phone: {phone_number}")
            # Connect to Telegram
            if connect_to_server(phone_number, password):
                # Wait for connection (up to 30 seconds for verification code input)
                max_wait = 300  # 30 seconds
                while max_wait > 0 and not is_connected():
                    time.sleep(0.1)
                    max_wait -= 1

                if is_connected():
                    # Get user data
                    try:
                        from src.network.telegram_client import get_user_data
                        user_data = get_user_data()
                        username = user_data.get('username') or user_data.get('first_name', 'User')
                    except:
                        username = "Telegram User"

                    print(f"[TELEGRAM GUI] Connected as: {username}")
                    # Show chat window
                    chat_window = TelegramChatWindow(parent, username)
                    chat_window.Show()
                    return chat_window
                else:
                    wx.MessageBox(_("Failed to connect to Telegram. Check your phone number and try again."), _("Connection error"), wx.OK | wx.ICON_ERROR)
            else:
                wx.MessageBox(_("Failed to start connection. Please try again."), _("Error"), wx.OK | wx.ICON_ERROR)
    else:
        login_dialog.Destroy()

    return None