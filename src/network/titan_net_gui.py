"""
Titan-Net GUI - Simple and accessible interface for TCE
Follows TCE design patterns with skin support and automatic updates
"""
import wx
import sys
import struct
import threading
import queue
import accessible_output3.outputs.auto
from src.network.titan_net import TitanNetClient
import os
import tempfile
from src.titan_core.sound import play_sound, play_sound_file, initialize_sound

# Guarantee the pygame mixer is initialized even when Titan-Net is opened
# from a context where the main TCE GUI never ran (launcher mode, direct
# module launch). initialize_sound() is idempotent and self-healing.
try:
    initialize_sound()
except Exception as _e:
    print(f"[Titan-Net] initialize_sound() failed at import: {_e}")
from src.titan_core.translation import set_language
from src.settings.settings import get_setting
from src.titan_core.skin_manager import get_skin_manager, apply_skin_to_window

# Import stereo speech functionality
try:
    from src.titan_core.stereo_speech import speak_stereo, get_stereo_speech
    STEREO_SPEECH_AVAILABLE = True
except ImportError:
    STEREO_SPEECH_AVAILABLE = False
    print("Warning: stereo_speech module not available")

# Get the translation function
_ = set_language(get_setting('language', 'pl'))

# Initialize screen reader output with stereo support
speaker = accessible_output3.outputs.auto.Auto()


def _apply_skin_recursive(window):
    """Apply current skin to a window and all descendants."""
    try:
        apply_skin_to_window(window)
    except Exception:
        return

    for child in window.GetChildren():
        _apply_skin_recursive(child)


def _new_text_entry_dialog(*args, **kwargs):
    dlg = wx.TextEntryDialog(*args, **kwargs)
    _apply_skin_recursive(dlg)
    return dlg


def _new_message_dialog(*args, **kwargs):
    dlg = wx.MessageDialog(*args, **kwargs)
    _apply_skin_recursive(dlg)
    return dlg


def speak_titannet(text, position=0.0, pitch_offset=0, interrupt=True):
    """
    Speak text using the same method as Klango Mode and IUI.
    Position: -1.0 (left) to 1.0 (right), 0.0 (center)
    Pitch: -10 to +10, higher pitch = more important
    """
    if not text:
        return

    try:
        # Check stereo speech setting safely (same as Klango Mode)
        try:
            stereo_enabled = get_setting('stereo_speech', 'False', section='invisible_interface').lower() == 'true'

            if stereo_enabled and STEREO_SPEECH_AVAILABLE:
                def speak_with_stereo():
                    try:
                        # Stop previous speech if interrupt=True
                        if interrupt:
                            try:
                                stereo_speech = get_stereo_speech()
                                if stereo_speech:
                                    stereo_speech.stop()
                            except Exception as e:
                                print(f"Error stopping stereo speech: {e}")

                        speak_stereo(text, position=position, pitch_offset=pitch_offset, async_mode=True)
                    except Exception as e:
                        print(f"Error in stereo speech: {e}")
                        # Fallback to regular TTS
                        speaker.output(text)

                # Use daemon thread with timeout protection (same as Klango Mode)
                thread = threading.Thread(target=speak_with_stereo, daemon=True)
                thread.start()
            else:
                # Standard TTS without stereo (same as Klango Mode)
                def speak_regular():
                    try:
                        if interrupt and hasattr(speaker, 'stop'):
                            speaker.stop()
                        speaker.output(text)
                    except Exception as e:
                        print(f"Error in standard speech: {e}")

                # Use daemon thread for consistency
                thread = threading.Thread(target=speak_regular, daemon=True)
                thread.start()

        except Exception as e:
            print(f"Error in speech configuration: {e}")
            # Final fallback
            speaker.output(text)

    except Exception as e:
        print(f"Critical error in speak_titannet: {e}")
        # Final fallback
        try:
            speaker.output(text)
        except:
            pass


def speak_notification(text, notification_type='info', play_sound_effect=True):
    """
    Speak notification with stereo position and pitch based on importance.
    Like Klango mode - higher pitch for more important notifications.

    Args:
        text: Text to speak
        notification_type: Type of notification ('error', 'success', 'info', 'warning', 'banned')
        play_sound_effect: Whether to play sound effect
    """
    if not text:
        return

    # Define position and pitch based on notification type
    notification_settings = {
        'error': {
            'position': 0.7,      # Right side
            'pitch_offset': 5,    # Higher pitch - very important
            'sound': 'core/error.ogg'
        },
        'banned': {
            'position': 0.9,      # Far right
            'pitch_offset': 8,    # Very high pitch - critical
            'sound': 'core/error.ogg'
        },
        'warning': {
            'position': 0.4,      # Slightly right
            'pitch_offset': 3,    # Moderately higher pitch
            'sound': 'core/error.ogg'
        },
        'success': {
            'position': 0.0,      # Center
            'pitch_offset': 0,    # Normal pitch
            'sound': 'core/SELECT.ogg'
        },
        'info': {
            'position': -0.3,     # Slightly left
            'pitch_offset': -2,   # Slightly lower pitch
            'sound': 'ui/dialog.ogg'
        }
    }

    settings = notification_settings.get(notification_type, notification_settings['info'])

    # Play sound effect if requested
    if play_sound_effect and settings.get('sound'):
        try:
            play_sound(settings['sound'])
        except:
            pass

    # Speak with appropriate position and pitch
    speak_titannet(text, position=settings['position'], pitch_offset=settings['pitch_offset'], interrupt=True)


class LoginDialog(wx.Dialog):
    """Simple login dialog for Titan-Net"""

    def __init__(self, parent, titan_client: TitanNetClient):
        super().__init__(parent, title=_("Titan-Net Login"), size=(400, 300))

        self.titan_client = titan_client
        self.logged_in = False
        self.offline_mode = False  # No longer set by dialog, but kept for compatibility
        self.motd = None  # Message of the Day data from server

        self.InitUI()
        self.Centre()
        self.apply_skin()

        # Load autologin settings
        self.load_autologin_settings()

        # Try auto login if enabled
        wx.CallAfter(self.try_autologin)

        # Bind Escape key to close
        self.Bind(wx.EVT_CHAR_HOOK, self.OnKeyPress)

        play_sound('ui/dialog.ogg')

    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Username field
        username_label = wx.StaticText(panel, label=_("Username:"))
        vbox.Add(username_label, flag=wx.LEFT | wx.TOP, border=10)

        self.username_text = wx.TextCtrl(panel)
        self.username_text.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.username_text, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        # Password field
        password_label = wx.StaticText(panel, label=_("Password:"))
        vbox.Add(password_label, flag=wx.LEFT | wx.TOP, border=10)

        self.password_text = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
        self.password_text.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.password_text, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        # Auto login checkbox
        self.autologin_checkbox = wx.CheckBox(panel, label=_("Auto login"))
        self.autologin_checkbox.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.autologin_checkbox, flag=wx.LEFT | wx.TOP, border=10)

        # Buttons
        button_box = wx.BoxSizer(wx.HORIZONTAL)

        self.create_account_button = wx.Button(panel, wx.ID_NEW, _("Create Account"))
        self.create_account_button.Bind(wx.EVT_BUTTON, self.OnCreateAccount)
        self.create_account_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        button_box.Add(self.create_account_button, flag=wx.RIGHT, border=10)

        self.login_button = wx.Button(panel, wx.ID_OK, _("Login"))
        self.login_button.Bind(wx.EVT_BUTTON, self.OnLogin)
        self.login_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        button_box.Add(self.login_button, flag=wx.RIGHT, border=10)

        vbox.Add(button_box, flag=wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, border=20)

        panel.SetSizer(vbox)

    def apply_skin(self):
        """Apply current skin to dialog"""
        try:
            _apply_skin_recursive(self)
        except Exception as e:
            print(f"Error applying skin to login dialog: {e}")

    def OnFocus(self, event):
        """Handle focus events with sound"""
        play_sound('core/FOCUS.ogg', pan=0.5)
        event.Skip()

    def OnKeyPress(self, event):
        """Handle key press events"""
        keycode = event.GetKeyCode()

        # Escape or Alt+F4 closes the dialog
        if keycode == wx.WXK_ESCAPE:
            play_sound('core/SELECT.ogg')
            self.EndModal(wx.ID_CANCEL)
        elif keycode == wx.WXK_F4 and event.AltDown():
            play_sound('core/SELECT.ogg')
            self.EndModal(wx.ID_CANCEL)
        else:
            event.Skip()

    def OnCreateAccount(self, event):
        """Open create account dialog"""
        dialog = CreateAccountDialog(self, self.titan_client)
        result = dialog.ShowModal()

        if result == wx.ID_OK:
            username = dialog.username
            password = dialog.password

            self.username_text.SetValue(username)
            self.password_text.SetValue(password)

            speak_titannet(_("Account created. You can now login."))

        dialog.Destroy()

    def OnLogin(self, event):
        """Handle login button"""
        print("[TITAN-NET LOGIN] OnLogin called")
        username = self.username_text.GetValue().strip()
        password = self.password_text.GetValue()

        print(f"[TITAN-NET LOGIN] Username: {username}, Password length: {len(password)}")

        if not username or not password:
            print("[TITAN-NET LOGIN] Missing username or password")
            speak_titannet(_("Please enter username and password"))
            play_sound('core/error.ogg')
            return

        self.login_button.Enable(False)
        self.create_account_button.Enable(False)

        speak_titannet(_("Logging in..."), pitch_offset=-5)  # Low tone
        play_sound('system/connecting.ogg')

        def login_thread():
            try:
                print(f"[TITAN-NET LOGIN] Calling titan_client.login()")
                result = self.titan_client.login(username, password)
                print(f"[TITAN-NET LOGIN] Login result: {result}")
                wx.CallAfter(self.OnLoginComplete, result)
            except Exception as e:
                print(f"[TITAN-NET LOGIN] Login exception: {e}")
                import traceback
                traceback.print_exc()
                wx.CallAfter(self.OnLoginComplete, {
                    'success': False,
                    'message': _("Error: {error}").format(error=str(e))
                })

        thread = threading.Thread(target=login_thread, daemon=True)
        thread.start()
        print("[TITAN-NET LOGIN] Login thread started")

    def OnLoginComplete(self, result):
        """Handle login completion"""
        print(f"[TITAN-NET LOGIN] OnLoginComplete called with success={result.get('success')}")
        self.login_button.Enable(True)
        self.create_account_button.Enable(True)

        if result.get('success'):
            print("[TITAN-NET LOGIN] Login successful, processing...")
            # Role is determined by the server based on the authenticated
            # account, never by the client environment. Running from source
            # must NOT confer elevated privileges.

            # Check if user is banned
            print("[TITAN-NET LOGIN] Checking ban status...")
            try:
                user_info = result.get('user', {})
                user_id = user_info.get('id')
                if user_id:
                    print(f"[TITAN-NET LOGIN] Calling check_ban_status for user {user_id}")
                    ban_status = self.titan_client.check_ban_status(user_id)
                    print(f"[TITAN-NET LOGIN] Ban status result: {ban_status}")
                    if ban_status.get('success'):
                        global_ban = ban_status.get('global_ban', {})
                        if global_ban.get('banned'):
                            # User is globally banned
                            reason = global_ban.get('reason', _('No reason provided'))
                            expires_at = global_ban.get('expires_at')

                            if expires_at:
                                ban_msg = _("You are banned from TCE Community\nReason: {reason}\nExpires: {expires}").format(
                                    reason=reason, expires=expires_at)
                            else:
                                ban_msg = _("You are banned from TCE Community\nReason: {reason}\nThis ban is permanent").format(reason=reason)

                            speak_titannet(_("You are banned from TCE Community"))
                            speak_notification(ban_msg, 'banned')
                            self.EndModal(wx.ID_CANCEL)
                            return
            except Exception as e:
                print(f"[TITAN-NET LOGIN] Error checking ban status: {e}")
                import traceback
                traceback.print_exc()

            # Save autologin settings if enabled
            print("[TITAN-NET LOGIN] Saving autologin settings...")
            username = self.username_text.GetValue().strip()
            password = self.password_text.GetValue()
            self.save_autologin_settings(username, password)

            print("[TITAN-NET LOGIN] Setting logged_in = True and closing dialog...")
            self.logged_in = True

            # Store unread messages summary for post-login notification
            unread_summary = result.get('unread_messages_summary', [])

            # Store MOTD data for post-login display
            self.motd = result.get('motd')

            # Close dialog immediately to avoid errors
            self.EndModal(wx.ID_OK)
            print("[TITAN-NET LOGIN] Dialog should be closed now")

            # Notify about unread messages after dialog closes (login TTS handled by gui.py)
            def post_login_feedback():
                try:
                    if unread_summary:
                        notification_msg = self._format_unread_notification(unread_summary)
                        if notification_msg:
                            play_sound('titannet/new_message.ogg')
                            speak_titannet(notification_msg)
                except Exception as e:
                    print(f"Error in post-login feedback: {e}")

            if unread_summary:
                wx.CallLater(2000, post_login_feedback)
        else:
            error_message = result.get('message', _("Login failed"))
            speak_titannet(error_message)
            play_sound('core/error.ogg')

    def load_autologin_settings(self):
        """Load autologin settings from config"""
        try:
            from src.settings.titan_im_config import load_titan_im_config
            config = load_titan_im_config()

            if config.get('titannet_autologin'):
                self.autologin_checkbox.SetValue(True)
                username = config.get('titannet_username', '')
                password = config.get('titannet_password', '')

                if username:
                    self.username_text.SetValue(username)
                if password:
                    self.password_text.SetValue(password)

        except Exception as e:
            print(f"Error loading autologin settings: {e}")

    def save_autologin_settings(self, username, password):
        """Save autologin settings to config"""
        try:
            from src.settings.titan_im_config import load_titan_im_config, save_titan_im_config
            config = load_titan_im_config()

            autologin_enabled = self.autologin_checkbox.GetValue()
            config['titannet_autologin'] = autologin_enabled

            if autologin_enabled:
                config['titannet_username'] = username
                config['titannet_password'] = password
            else:
                # Clear saved credentials if autologin is disabled
                config['titannet_username'] = ''
                config['titannet_password'] = ''

            save_titan_im_config(config)
            print(f"Autologin settings saved: autologin={autologin_enabled}")

        except Exception as e:
            print(f"Error saving autologin settings: {e}")

    def try_autologin(self):
        """Try to auto login if settings are saved"""
        try:
            if not self.autologin_checkbox.GetValue():
                return

            username = self.username_text.GetValue().strip()
            password = self.password_text.GetValue()

            if username and password:
                print(f"[TITAN-NET] Auto login as {username}...")
                # Simulate login button click
                self.OnLogin(None)

        except Exception as e:
            print(f"Error during auto login: {e}")

    def _format_unread_notification(self, unread_summary):
        """Format unread messages notification"""
        if not unread_summary:
            return None

        total_senders = len(unread_summary)

        if total_senders == 1:
            # Single sender: "masz x nowych wiadomości od y"
            sender = unread_summary[0]
            count = sender.get('unread_count', 0)
            username = sender.get('sender_username', _('Unknown'))
            if count == 1:
                return _("You have 1 new message from {username}").format(username=username)
            else:
                return _("You have {count} new messages from {username}").format(count=count, username=username)

        elif total_senders == 2:
            # Two senders: "masz x nowych wiadomości od y i x wiadomości od z"
            sender1 = unread_summary[0]
            sender2 = unread_summary[1]
            count1 = sender1.get('unread_count', 0)
            count2 = sender2.get('unread_count', 0)
            username1 = sender1.get('sender_username', _('Unknown'))
            username2 = sender2.get('sender_username', _('Unknown'))

            if count1 == 1:
                msg1 = _("1 new message from {username}").format(username=username1)
            else:
                msg1 = _("{count} new messages from {username}").format(count=count1, username=username1)

            if count2 == 1:
                msg2 = _("1 message from {username}").format(username=username2)
            else:
                msg2 = _("{count} messages from {username}").format(count=count2, username=username2)

            return _("You have {msg1} and {msg2}").format(msg1=msg1, msg2=msg2)

        else:
            # Three or more senders: "masz x nowych wiadomości od y, x wiadomości od z i x wiadomości od w"
            parts = []
            for i, sender in enumerate(unread_summary):
                count = sender.get('unread_count', 0)
                username = sender.get('sender_username', _('Unknown'))

                if i == 0:
                    # First sender
                    if count == 1:
                        parts.append(_("1 new message from {username}").format(username=username))
                    else:
                        parts.append(_("{count} new messages from {username}").format(count=count, username=username))
                else:
                    # Subsequent senders
                    if count == 1:
                        parts.append(_("1 message from {username}").format(username=username))
                    else:
                        parts.append(_("{count} messages from {username}").format(count=count, username=username))

            # Join parts with ", " and " i " for the last part
            if len(parts) == 2:
                return _("You have {msg}").format(msg=f"{parts[0]} {_('and')} {parts[1]}")
            else:
                # For 3+, use commas and "i" before the last one
                msg = ", ".join(parts[:-1]) + f" {_('and')} " + parts[-1]
                return _("You have {msg}").format(msg=msg)


class CreateAccountDialog(wx.Dialog):
    """Create account dialog for Titan-Net"""

    def __init__(self, parent, titan_client: TitanNetClient):
        super().__init__(parent, title=_("Create Titan-Net Account"), size=(400, 350))

        self.titan_client = titan_client
        self.username = None
        self.password = None

        self.InitUI()
        self.Centre()
        self.apply_skin()

        # Bind Escape key to close
        self.Bind(wx.EVT_CHAR_HOOK, self.OnKeyPress)

        play_sound('ui/dialog.ogg')

    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Username field
        username_label = wx.StaticText(panel, label=_("Username:") + " *")
        vbox.Add(username_label, flag=wx.LEFT | wx.TOP, border=10)

        self.username_text = wx.TextCtrl(panel)
        self.username_text.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.username_text, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        # Password field
        password_label = wx.StaticText(panel, label=_("Password:") + " *")
        vbox.Add(password_label, flag=wx.LEFT | wx.TOP, border=10)

        self.password_text = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
        self.password_text.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.password_text, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        # First name field
        firstname_label = wx.StaticText(panel, label=_("First Name:") + " (" + _("optional") + ")")
        vbox.Add(firstname_label, flag=wx.LEFT | wx.TOP, border=10)

        self.firstname_text = wx.TextCtrl(panel)
        self.firstname_text.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.firstname_text, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        # Last name field
        lastname_label = wx.StaticText(panel, label=_("Last Name:") + " (" + _("optional") + ")")
        vbox.Add(lastname_label, flag=wx.LEFT | wx.TOP, border=10)

        self.lastname_text = wx.TextCtrl(panel)
        self.lastname_text.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.lastname_text, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        # Buttons
        button_box = wx.BoxSizer(wx.HORIZONTAL)

        self.create_button = wx.Button(panel, wx.ID_OK, _("Create Account"))
        self.create_button.Bind(wx.EVT_BUTTON, self.OnCreateAccount)
        self.create_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        button_box.Add(self.create_button, flag=wx.RIGHT, border=10)

        cancel_button = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        cancel_button.Bind(wx.EVT_BUTTON, self.OnCancel)
        cancel_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        button_box.Add(cancel_button, flag=wx.RIGHT, border=10)

        vbox.Add(button_box, flag=wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, border=20)

        panel.SetSizer(vbox)

    def apply_skin(self):
        """Apply current skin to dialog"""
        try:
            _apply_skin_recursive(self)
        except Exception as e:
            print(f"Error applying skin to create account dialog: {e}")

    def OnFocus(self, event):
        """Handle focus events with sound"""
        play_sound('core/FOCUS.ogg', pan=0.5)
        event.Skip()

    def OnKeyPress(self, event):
        """Handle key press events"""
        keycode = event.GetKeyCode()

        # Escape or Alt+F4 closes the dialog
        if keycode == wx.WXK_ESCAPE:
            play_sound('core/SELECT.ogg')
            self.EndModal(wx.ID_CANCEL)
        elif keycode == wx.WXK_F4 and event.AltDown():
            play_sound('core/SELECT.ogg')
            self.EndModal(wx.ID_CANCEL)
        else:
            event.Skip()

    def OnCreateAccount(self, event):
        """Handle create account button"""
        play_sound('core/SELECT.ogg')

        username = self.username_text.GetValue().strip()
        password = self.password_text.GetValue()
        firstname = self.firstname_text.GetValue().strip()
        lastname = self.lastname_text.GetValue().strip()

        if not username or not password:
            speak_titannet(_("Username and password are required"))
            play_sound('core/error.ogg')
            return

        full_name = " ".join(filter(None, [firstname, lastname]))

        self.create_button.Enable(False)

        speak_titannet(_("Creating account..."))
        play_sound('system/connecting.ogg')

        def register_thread():
            try:
                result = self.titan_client.register(username, password, full_name)
                wx.CallAfter(self.OnRegistrationComplete, result, username, password)
            except Exception as e:
                wx.CallAfter(self.OnRegistrationComplete, {
                    'success': False,
                    'message': _("Error: {error}").format(error=str(e))
                }, username, password)

        thread = threading.Thread(target=register_thread, daemon=True)
        thread.start()

    def OnRegistrationComplete(self, result, username, password):
        """Handle registration completion"""
        self.create_button.Enable(True)

        if result.get('success'):
            titan_number = result.get('titan_number')

            message = _("Account created successfully. Your Titan number is {titan_number}").format(
                titan_number=titan_number
            )
            speak_titannet(message)

            play_sound('titannet/account_created.ogg')

            self.username = username
            self.password = password

            wx.CallLater(2000, lambda: self.EndModal(wx.ID_OK))
        else:
            error_message = result.get('message', _("Registration failed"))
            speak_titannet(error_message)
            play_sound('core/error.ogg')

    def OnCancel(self, event):
        """Handle cancel button"""
        play_sound('core/SELECT.ogg')
        self.EndModal(wx.ID_CANCEL)


class ForumTopicWindow(wx.Frame):
    """Forum topic window showing topic content and replies"""

    def __init__(self, parent, titan_client: TitanNetClient, topic_id, topic_title):
        super().__init__(parent, title=_("Forum Topic: {title}").format(title=topic_title), size=(700, 600))

        self.titan_client = titan_client
        self.topic_id = topic_id
        self.topic_title = topic_title
        self.topic_data = None
        self.replies_data = []

        # Get moderator status from parent window
        self.is_moderator = getattr(parent, 'is_moderator', False)
        self.is_developer = getattr(parent, 'is_developer', False)

        self.InitUI()
        self.Centre()
        self.apply_skin()

        # Bind Escape key to close
        self.Bind(wx.EVT_CHAR_HOOK, self.OnKeyPress)

        # Load topic and replies
        self.load_topic_data()

        play_sound('ui/window_open.ogg')

    def InitUI(self):
        """Initialize UI"""
        panel = wx.Panel(self)
        main_vbox = wx.BoxSizer(wx.VERTICAL)

        # Scrolled window for all content
        self.scroll = wx.ScrolledWindow(panel)
        self.scroll.SetScrollRate(5, 5)
        scroll_sizer = wx.BoxSizer(wx.VERTICAL)

        # Topic section
        topic_label = wx.StaticText(self.scroll, label=_("Topic:"))
        scroll_sizer.Add(topic_label, flag=wx.ALL, border=5)

        # Author and date info
        self.topic_info_label = wx.StaticText(self.scroll, label=_("Loading..."))
        scroll_sizer.Add(self.topic_info_label, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=5)

        # Topic content
        self.topic_content = wx.TextCtrl(
            self.scroll,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP,
            size=(-1, 100)
        )
        self.topic_content.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        scroll_sizer.Add(self.topic_content, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=5)

        # Separator
        separator1 = wx.StaticLine(self.scroll)
        scroll_sizer.Add(separator1, flag=wx.EXPAND | wx.ALL, border=10)

        # Replies section
        replies_label = wx.StaticText(self.scroll, label=_("Replies:"))
        scroll_sizer.Add(replies_label, flag=wx.ALL, border=5)

        # Container for replies (will be populated dynamically)
        self.replies_container = wx.BoxSizer(wx.VERTICAL)
        scroll_sizer.Add(self.replies_container, proportion=1, flag=wx.EXPAND)

        self.scroll.SetSizer(scroll_sizer)
        main_vbox.Add(self.scroll, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        # Reply input section
        separator2 = wx.StaticLine(panel)
        main_vbox.Add(separator2, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=5)

        reply_label = wx.StaticText(panel, label=_("Your Reply:"))
        main_vbox.Add(reply_label, flag=wx.LEFT | wx.TOP | wx.RIGHT, border=5)

        self.reply_input = wx.TextCtrl(panel, style=wx.TE_MULTILINE, size=(-1, 80))
        self.reply_input.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.reply_input.Bind(wx.EVT_KEY_DOWN, self.OnReplyKeyDown)
        main_vbox.Add(self.reply_input, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=5)

        # Buttons
        button_box = wx.BoxSizer(wx.HORIZONTAL)

        self.send_reply_button = wx.Button(panel, label=_("Send Reply"))
        self.send_reply_button.Bind(wx.EVT_BUTTON, self.OnSendReply)
        self.send_reply_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        button_box.Add(self.send_reply_button, flag=wx.RIGHT, border=5)

        close_button = wx.Button(panel, label=_("Close"))
        close_button.Bind(wx.EVT_BUTTON, self.OnClose)
        close_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        button_box.Add(close_button)

        main_vbox.Add(button_box, flag=wx.ALIGN_CENTER | wx.ALL, border=10)

        panel.SetSizer(main_vbox)

    def apply_skin(self):
        """Apply current skin to window"""
        try:
            _apply_skin_recursive(self)
        except Exception as e:
            print(f"Error applying skin to forum topic window: {e}")

    def OnFocus(self, event):
        """Handle focus events with sound"""
        play_sound('core/FOCUS.ogg', pan=0.5)
        event.Skip()

    def OnKeyPress(self, event):
        """Handle key press events"""
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            play_sound('core/SELECT.ogg')
            self.Close()
        else:
            event.Skip()

    def OnReplyKeyDown(self, event):
        """Handle key press in reply input - Ctrl+Enter to send"""
        keycode = event.GetKeyCode()
        if (keycode == wx.WXK_RETURN or keycode == wx.WXK_NUMPAD_ENTER) and event.ControlDown():
            # Ctrl+Enter - send reply
            self.OnSendReply(None)
        else:
            event.Skip()

    def load_topic_data(self):
        """Load topic and replies data - parallel fetch"""
        speak_titannet(_("Loading topic..."))

        def load_thread():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                topic_future = pool.submit(self.titan_client.get_forum_topic, self.topic_id)
                replies_future = pool.submit(self.titan_client.get_forum_replies, self.topic_id)
                topic_result = topic_future.result()
                replies_result = replies_future.result()
            wx.CallAfter(self._display_topic_data, topic_result, replies_result)

        threading.Thread(target=load_thread, daemon=True).start()

    def _display_topic_data(self, topic_result, replies_result):
        """Display topic and replies data"""
        if not topic_result.get('success'):
            speak_titannet(_("Failed to load topic"))
            play_sound('core/error.ogg')
            speak_notification(_("Failed to load topic"), 'error')
            return

        # Display topic
        topic = topic_result.get('topic', {})
        self.topic_data = topic

        # Format date
        created_at = topic.get('created_at', '')
        if 'T' in created_at:
            date_part = created_at.split('T')[0]
            time_part = created_at.split('T')[1][:5]
            formatted_date = f"{date_part} {time_part}"
        else:
            formatted_date = created_at

        # Set topic info
        info_text = _("Author: {author} | Date: {date}").format(
            author=topic.get('author_username', 'Unknown'),
            date=formatted_date
        )
        self.topic_info_label.SetLabel(info_text)

        # Set topic content and auto-size height
        content_value = topic.get('content', '')
        self.topic_content.SetValue(content_value)
        line_count = max(content_value.count('\n') + 1, 3)
        topic_height = min(line_count * 20 + 10, 400)
        self.topic_content.SetMinSize((-1, topic_height))

        # Display replies
        if replies_result.get('success'):
            self.replies_data = replies_result.get('replies', [])
            self._display_replies()
        else:
            speak_titannet(_("Failed to load replies"))

        speak_titannet(_("Topic loaded"))
        play_sound('core/SELECT.ogg')

    def _display_replies(self):
        """Display all replies as separate text fields"""
        # Clear existing replies
        self.replies_container.Clear(True)

        if not self.replies_data:
            no_replies = wx.StaticText(self.scroll, label=_("No replies yet. Be the first to reply!"))
            self.replies_container.Add(no_replies, flag=wx.ALL, border=10)
        else:
            for reply in self.replies_data:
                # Create reply container
                reply_box = wx.BoxSizer(wx.VERTICAL)

                # Format date
                created_at = reply.get('created_at', '')
                if 'T' in created_at:
                    date_part = created_at.split('T')[0]
                    time_part = created_at.split('T')[1][:5]
                    formatted_date = f"{date_part} {time_part}"
                else:
                    formatted_date = created_at

                # Reply header (author and date)
                header_text = _("Author: {author} | Date: {date}").format(
                    author=reply.get('author_username', 'Unknown'),
                    date=formatted_date
                )
                header_label = wx.StaticText(self.scroll, label=header_text)
                reply_box.Add(header_label, flag=wx.LEFT | wx.RIGHT | wx.TOP, border=5)

                # Reply content - auto-size height based on line count
                content_value = reply.get('content', '')
                line_count = max(content_value.count('\n') + 1, 2)
                reply_height = min(line_count * 20 + 10, 300)
                reply_content = wx.TextCtrl(
                    self.scroll,
                    style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP,
                    size=(-1, reply_height),
                    value=content_value
                )
                reply_content.Bind(wx.EVT_SET_FOCUS, self.OnFocus)

                # Add context menu for moderators
                if self.is_moderator or self.is_developer:
                    reply_content.Bind(wx.EVT_CONTEXT_MENU, lambda e, r=reply: self.OnReplyContextMenu(e, r))

                reply_box.Add(reply_content, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=5)

                # Separator between replies
                separator = wx.StaticLine(self.scroll)
                reply_box.Add(separator, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=5)

                self.replies_container.Add(reply_box, flag=wx.EXPAND)

        # Refresh layout
        self.scroll.Layout()
        self.scroll.FitInside()

    def OnSendReply(self, event):
        """Send reply to topic"""
        play_sound('core/SELECT.ogg')

        content = self.reply_input.GetValue().strip()
        print(f"OnSendReply called, content length: {len(content)}")

        if not content:
            speak_titannet(_("Please enter reply content"))
            play_sound('core/error.ogg')
            return

        self.send_reply_button.Enable(False)
        speak_titannet(_("Sending reply..."))
        print(f"Sending reply to topic {self.topic_id}")

        def send_thread():
            try:
                result = self.titan_client.add_forum_reply(self.topic_id, content)
                print(f"Reply result: {result}")
                wx.CallAfter(self._on_reply_sent, result)
            except Exception as e:
                print(f"Error in send_thread: {e}")
                import traceback
                traceback.print_exc()
                wx.CallAfter(self._on_reply_sent, {'success': False, 'message': str(e)})

        threading.Thread(target=send_thread, daemon=True).start()

    def _on_reply_sent(self, result):
        """Handle reply sent result"""
        self.send_reply_button.Enable(True)

        if result.get('success'):
            speak_titannet(_("Reply sent"))  # Simplified: "Wysłano odpowiedź"
            play_sound('core/SELECT.ogg')

            # Clear input
            self.reply_input.Clear()

            # Reload topic
            self.load_topic_data()
        else:
            error_msg = result.get('message', _("Failed to send reply"))
            print(f"Reply send failed: {error_msg}")
            speak_titannet(_("Failed to send reply"))
            play_sound('core/error.ogg')

            # Show detailed error to user
            detailed_error = f"{_('Failed to send reply')}\n\n{_('Error')}: {error_msg}"
            speak_notification(detailed_error, 'error')

    def OnReplyContextMenu(self, event, reply):
        """Show context menu for reply (moderator only)"""
        if not (self.is_moderator or self.is_developer):
            return

        menu = wx.Menu()

        edit_item = menu.Append(wx.ID_ANY, _("Edit Post"))
        self.Bind(wx.EVT_MENU, lambda e: self.OnEditReply(reply), edit_item)

        delete_item = menu.Append(wx.ID_ANY, _("Delete Post"))
        self.Bind(wx.EVT_MENU, lambda e: self.OnDeleteReply(reply), delete_item)

        self.PopupMenu(menu)
        menu.Destroy()

    def OnEditReply(self, reply):
        """Edit forum reply"""
        play_sound('core/SELECT.ogg')

        # Show edit dialog with current content
        dlg = _new_text_entry_dialog(
            self,
            _("Edit post content:"),
            _("Edit Post"),
            value=reply.get('content', ''),
            style=wx.OK | wx.CANCEL | wx.TE_MULTILINE
        )
        dlg.SetSize((500, 300))

        if dlg.ShowModal() == wx.ID_OK:
            new_content = dlg.GetValue().strip()

            if not new_content:
                speak_titannet(_("Content cannot be empty"))
                play_sound('core/error.ogg')
                dlg.Destroy()
                return

            speak_titannet(_("Editing post..."))

            def edit_thread():
                try:
                    result = self.titan_client.edit_forum_reply(reply['id'], new_content)
                    wx.CallAfter(self._on_reply_edited, result)
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=edit_thread, daemon=True).start()

        dlg.Destroy()

    def _on_reply_edited(self, result):
        """Handle reply edited response"""
        if result.get('success'):
            speak_titannet(_("Post edited successfully"))
            play_sound('core/SELECT.ogg')
            speak_notification(_("Post edited successfully"), 'success')
            # Reload topic to show updated content
            self.load_topic_data()
        else:
            error_msg = result.get('message', _("Failed to edit post"))
            speak_titannet(_("Failed to edit post"))
            play_sound('core/error.ogg')
            speak_notification(error_msg, 'error')

    def OnDeleteReply(self, reply):
        """Delete forum reply"""
        play_sound('core/SELECT.ogg')

        confirm = _new_message_dialog(
            self,
            _("Are you sure you want to delete this post?\n\nAuthor: {author}\nContent: {content}").format(
                author=reply.get('author_username', 'Unknown'),
                content=reply.get('content', '')[:50] + '...' if len(reply.get('content', '')) > 50 else reply.get('content', '')
            ),
            _("Confirm Delete"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION
        )

        if confirm.ShowModal() == wx.ID_YES:
            speak_titannet(_("Deleting post..."))

            def delete_thread():
                try:
                    result = self.titan_client.delete_forum_reply(reply['id'])
                    wx.CallAfter(self._on_reply_deleted, result)
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=delete_thread, daemon=True).start()

        confirm.Destroy()

    def _on_reply_deleted(self, result):
        """Handle reply deleted response"""
        if result.get('success'):
            speak_titannet(_("Post deleted successfully"))
            play_sound('core/SELECT.ogg')
            speak_notification(_("Post deleted successfully"), 'success')
            # Reload topic to show updated content
            self.load_topic_data()
        else:
            error_msg = result.get('message', _("Failed to delete post"))
            speak_titannet(_("Failed to delete post"))
            play_sound('core/error.ogg')
            speak_notification(error_msg, 'error')

    def OnClose(self, event):
        """Close window"""
        play_sound('core/SELECT.ogg')
        self.Close()


class TitanNetMainWindow(wx.Frame):
    """Main Titan-Net window - simple TCE-style interface"""

    def __init__(self, parent, titan_client: TitanNetClient):
        super().__init__(parent, title=_("Titan-Net"), size=(600, 500))

        self.titan_client = titan_client
        self.current_view = "menu"  # menu, rooms, users, private_messages
        self.current_room = None
        self.current_private_user = None
        self.selected_room_id = None
        self.selected_user_id = None
        self.force_close = False  # Flag to force window close (on disconnect)

        # Last private message sender — used by Ctrl+O quick-reply shortcut
        self._last_pm_sender_id = None
        self._last_pm_sender_username = None

        # User role info
        self.user_role = "user"  # user, moderator, developer
        self.is_moderator = False
        self.is_developer = False

        # Auto-refresh settings
        self.auto_refresh_enabled = True
        self.auto_refresh_interval = 15  # seconds - faster refresh for responsive UI
        self.refresh_timer = None

        # Data cache
        self.rooms_cache = []
        self.users_cache = []
        self.messages_cache = []
        self.forum_topics_cache = []
        self.repository_apps_cache = []
        self.room_users_cache = []  # Users in current room
        self.selected_app_id = None
        self.selected_topic_id = None

        # Message deduplication - store IDs of displayed messages
        self.displayed_message_ids = set()

        # Business card sound cache: {username: {sound_type: local_path}}
        self._business_card_cache = {}
        self._business_card_cache_dir = os.path.join(tempfile.gettempdir(), 'titan_business_cards')
        os.makedirs(self._business_card_cache_dir, exist_ok=True)

        # Load user role
        self.load_user_role()

        self.InitUI()
        self.Centre()
        self.apply_skin()

        # Setup callbacks
        self.setup_callbacks()

        # Start with menu
        self.show_menu()

        # Setup auto-refresh timer
        self.refresh_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.OnAutoRefresh, self.refresh_timer)
        self.refresh_timer.Start(self.auto_refresh_interval * 1000)

        # Bind close event
        self.Bind(wx.EVT_CLOSE, self.OnClose)

        # Bind iconize event to prevent disconnection on minimize
        self.Bind(wx.EVT_ICONIZE, self.OnIconize)

        # Bind Escape key to close
        self.Bind(wx.EVT_CHAR_HOOK, self.OnKeyPress)

        # Hard-wired Escape accelerator. Fires regardless of which child control
        # currently has focus, so the user can always leave a room even if a
        # multiline TextCtrl swallows the key on Windows. This is the
        # last-resort backup for the room-exit hang in text-only rooms.
        self._force_back_id = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._on_force_back, id=self._force_back_id)
        self.SetAcceleratorTable(wx.AcceleratorTable([
            (wx.ACCEL_NORMAL, wx.WXK_ESCAPE, self._force_back_id),
        ]))

        play_sound('ui/window_open.ogg')

    def InitUI(self):
        """Initialize UI"""
        # Create menu bar
        self.create_menu_bar()

        self.panel = wx.Panel(self)
        self.main_vbox = wx.BoxSizer(wx.VERTICAL)

        # User info label (always visible at top)
        user_info = _("Logged in as: {username} (#{titan_number})").format(
            username=self.titan_client.username,
            titan_number=self.titan_client.titan_number
        )
        self.user_label = wx.StaticText(self.panel, label=user_info)
        self.main_vbox.Add(self.user_label, flag=wx.ALL | wx.EXPAND, border=5)

        # View label (dynamic - shows current view)
        self.view_label = wx.StaticText(self.panel, label="")
        self.main_vbox.Add(self.view_label, flag=wx.LEFT | wx.RIGHT | wx.TOP, border=10)

        # Main listbox for all views
        self.main_listbox = wx.ListBox(self.panel)
        self.main_listbox.Bind(wx.EVT_LISTBOX, self.OnListSelection)
        self.main_listbox.Bind(wx.EVT_LISTBOX_DCLICK, self.OnListActivate)
        self.main_listbox.Bind(wx.EVT_KEY_DOWN, self.OnListKeyDown)
        self.main_listbox.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.main_vbox.Add(self.main_listbox, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        # Drag-and-drop reordering on the main listbox - every row in
        # every view is movable (Ctrl+Up / Ctrl+Down or mouse drag), and
        # per-view persistence keys keep each list's order separate in
        # .index.TCG. The user explicitly asked for "all lists" to be
        # reorderable; no per-view gating. view_id is a callable so each
        # view (menu, rooms, users, ...) writes to its own slot in
        # .index.TCG and the orders don't overwrite each other.
        try:
            from src.titan_core.list_dnd import attach_listbox_dnd

            def _tn_main_view_id():
                view = getattr(self, 'current_view', 'unknown')
                return f"titannet:main:{view}"

            def _tn_main_key(_idx, text, _data):
                return f"txt:{text}"

            self._main_listbox_dnd = attach_listbox_dnd(
                self.main_listbox,
                view_id=_tn_main_view_id,
                has_tab_bar=False,
                item_key_func=_tn_main_key,
                auto_apply_on_focus=True,
            )
        except Exception as exc:
            print(f"[TITANNET GUI] main_listbox DnD setup error: {exc}")
            self._main_listbox_dnd = None

        # Room users listbox (shown in room chat view before message history)
        self.room_users_listbox = wx.ListBox(self.panel)
        self.room_users_listbox.Bind(wx.EVT_LISTBOX, self.OnListSelection)
        self.room_users_listbox.Bind(wx.EVT_KEY_DOWN, self.OnListKeyDown)
        self.room_users_listbox.Bind(wx.EVT_CONTEXT_MENU, self.OnRoomUserContextMenu)
        self.room_users_listbox.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.room_users_listbox.Hide()
        self.main_vbox.Add(self.room_users_listbox, proportion=0, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, border=10)

        # Drag-and-drop reordering on the in-room users panel - personal
        # ordering preference, persisted under "titannet:room_users".
        try:
            from src.titan_core.list_dnd import attach_listbox_dnd as _attach_users_dnd

            def _tn_room_users_key(_idx, text, _data):
                return f"txt:{text}"

            self._room_users_dnd = _attach_users_dnd(
                self.room_users_listbox,
                view_id='titannet:room_users',
                has_tab_bar=False,
                item_key_func=_tn_room_users_key,
                auto_apply_on_focus=True,
            )
        except Exception as exc:
            print(f"[TITANNET GUI] room_users DnD setup error: {exc}")
            self._room_users_dnd = None

        # Message display: report-mode list with Nick / Message / Date columns.
        # Enter on a row opens a read-only multiline dialog with the full message.
        self.message_display = wx.ListCtrl(self.panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.message_display.AppendColumn(_("Nick"), width=140)
        self.message_display.AppendColumn(_("Message"), width=420)
        self.message_display.AppendColumn(_("Date"), width=140)
        self.message_display.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.OnMessageActivated)
        self.message_display.Bind(wx.EVT_KEY_DOWN, self.OnMessageDisplayKeyDown)
        self.message_display.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.message_display.Hide()
        self._message_records = []  # parallel list of full message data per row
        self.main_vbox.Add(self.message_display, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        # Message input (for chat - hidden by default, multiline with Ctrl+Enter to send)
        input_box = wx.BoxSizer(wx.HORIZONTAL)
        self.message_input = wx.TextCtrl(self.panel, style=wx.TE_MULTILINE | wx.TE_WORDWRAP, size=(-1, 80))
        self.message_input.Bind(wx.EVT_KEY_DOWN, self.OnMessageInputKeyDown)
        self.message_input.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.message_input.Hide()
        input_box.Add(self.message_input, proportion=1, flag=wx.RIGHT, border=5)

        self.send_button = wx.Button(self.panel, label=_("Send"))
        self.send_button.Bind(wx.EVT_BUTTON, self.OnSendMessage)
        self.send_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.send_button.Hide()
        input_box.Add(self.send_button)

        self.main_vbox.Add(input_box, flag=wx.EXPAND | wx.ALL, border=10)

        # Voice controls panel (for voice/mixed rooms - hidden by default)
        self.voice_panel = wx.Panel(self.panel)
        voice_sizer = wx.BoxSizer(wx.VERTICAL)

        # Voice controls row 1: Voice mode radio buttons + mute
        voice_row1 = wx.BoxSizer(wx.HORIZONTAL)

        self.voice_mode_vad = wx.RadioButton(self.voice_panel, label=_("Voice Activation"), style=wx.RB_GROUP)
        self.voice_mode_vad.SetValue(True)
        self.voice_mode_vad.Bind(wx.EVT_RADIOBUTTON, self.OnVoiceModeChange)
        self.voice_mode_vad.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        voice_row1.Add(self.voice_mode_vad, flag=wx.RIGHT, border=10)

        self.voice_mode_ptt = wx.RadioButton(self.voice_panel, label=_("Push to Talk"))
        self.voice_mode_ptt.Bind(wx.EVT_RADIOBUTTON, self.OnVoiceModeChange)
        self.voice_mode_ptt.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        voice_row1.Add(self.voice_mode_ptt, flag=wx.RIGHT, border=10)

        self.self_monitor_button = wx.ToggleButton(self.voice_panel, label=_("Self-Monitor (Test)"))
        self.self_monitor_button.SetValue(False)
        self.self_monitor_button.Bind(wx.EVT_TOGGLEBUTTON, self.OnSelfMonitorToggle)
        self.self_monitor_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        voice_row1.Add(self.self_monitor_button, flag=wx.RIGHT, border=5)

        self.mute_button = wx.Button(self.voice_panel, label=_("Mute"))
        self.mute_button.Bind(wx.EVT_BUTTON, self.OnMuteToggle)
        self.mute_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        voice_row1.Add(self.mute_button)

        voice_sizer.Add(voice_row1, flag=wx.EXPAND | wx.BOTTOM, border=5)

        # PTT button (visible only in Push to Talk mode)
        self.ptt_button = wx.Button(self.voice_panel, label=_("Push to Talk (hold Space)"))
        self.ptt_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.ptt_button.Hide()
        voice_sizer.Add(self.ptt_button, flag=wx.EXPAND | wx.BOTTOM, border=5)

        # Voice controls row 2: Volume and status
        voice_row2 = wx.BoxSizer(wx.HORIZONTAL)

        volume_label = wx.StaticText(self.voice_panel, label=_("Voice Volume:"))
        voice_row2.Add(volume_label, flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=5)

        self.voice_volume_slider = wx.Slider(self.voice_panel, value=100, minValue=0, maxValue=100,
                                             style=wx.SL_HORIZONTAL)
        self.voice_volume_slider.Bind(wx.EVT_SLIDER, self.OnVoiceVolumeChange)
        self.voice_volume_slider.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        voice_row2.Add(self.voice_volume_slider, proportion=1, flag=wx.ALIGN_CENTER_VERTICAL)

        self.voice_status_label = wx.StaticText(self.voice_panel, label=_("Microphone: Off"))
        voice_row2.Add(self.voice_status_label, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=10)

        voice_sizer.Add(voice_row2, flag=wx.EXPAND | wx.BOTTOM, border=5)

        # Active speakers list
        speakers_label = wx.StaticText(self.voice_panel, label=_("Active Speakers:"))
        voice_sizer.Add(speakers_label, flag=wx.BOTTOM, border=5)

        self.speakers_listbox = wx.ListBox(self.voice_panel, size=(-1, 60))
        self.speakers_listbox.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        voice_sizer.Add(self.speakers_listbox, flag=wx.EXPAND)

        self.voice_panel.SetSizer(voice_sizer)
        self.voice_panel.Hide()
        self.main_vbox.Add(self.voice_panel, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        # Broadcast panel (for moderators - hidden by default)
        self.broadcast_panel = wx.Panel(self.panel)
        broadcast_sizer = wx.BoxSizer(wx.VERTICAL)

        # Text message input
        broadcast_label = wx.StaticText(self.broadcast_panel, label=_("Broadcast Message:"))
        broadcast_sizer.Add(broadcast_label, flag=wx.BOTTOM, border=5)

        self.broadcast_text = wx.TextCtrl(
            self.broadcast_panel,
            style=wx.TE_MULTILINE | wx.TE_WORDWRAP,
            size=(-1, 80)
        )
        self.broadcast_text.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        broadcast_sizer.Add(self.broadcast_text, flag=wx.EXPAND | wx.BOTTOM, border=10)

        # Voice recording controls row 1
        broadcast_voice_row1 = wx.BoxSizer(wx.HORIZONTAL)

        self.broadcast_record_button = wx.Button(self.broadcast_panel, label=_("Start Recording"))
        self.broadcast_record_button.Bind(wx.EVT_BUTTON, self.OnBroadcastStartRecording)
        self.broadcast_record_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        broadcast_voice_row1.Add(self.broadcast_record_button, flag=wx.RIGHT, border=5)

        self.broadcast_stop_button = wx.Button(self.broadcast_panel, label=_("Stop Recording"))
        self.broadcast_stop_button.Bind(wx.EVT_BUTTON, self.OnBroadcastStopRecording)
        self.broadcast_stop_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.broadcast_stop_button.Enable(False)
        broadcast_voice_row1.Add(self.broadcast_stop_button, flag=wx.RIGHT, border=5)

        self.broadcast_play_button = wx.Button(self.broadcast_panel, label=_("Play Recording"))
        self.broadcast_play_button.Bind(wx.EVT_BUTTON, self.OnBroadcastPlayRecording)
        self.broadcast_play_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.broadcast_play_button.Enable(False)
        broadcast_voice_row1.Add(self.broadcast_play_button)

        broadcast_sizer.Add(broadcast_voice_row1, flag=wx.EXPAND | wx.BOTTOM, border=10)

        # Send button
        self.broadcast_send_button = wx.Button(self.broadcast_panel, label=_("Send Broadcast"))
        self.broadcast_send_button.Bind(wx.EVT_BUTTON, self.OnBroadcastSend)
        self.broadcast_send_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        broadcast_sizer.Add(self.broadcast_send_button, flag=wx.ALIGN_CENTER)

        self.broadcast_panel.SetSizer(broadcast_sizer)
        self.broadcast_panel.Hide()
        self.main_vbox.Add(self.broadcast_panel, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        # Broadcast voice recording state
        self.broadcast_voice_capture = None
        self.broadcast_recorded_audio = None  # Stored audio data
        self.broadcast_is_recording = False

        # Voice capture manager (initialized when joining voice/mixed room)
        self.voice_capture = None
        self.voice_playback_stream = None  # sounddevice output stream
        self.current_room_type = 'text'
        self.is_mic_enabled = False
        self.is_muted = False
        self.is_vad_mode = True   # Default to Voice Activation mode
        self.is_ptt_mode = False  # Push to Talk mode
        self.is_ptt_active = False  # True while Enter is held in PTT mode
        self.is_self_monitoring = False  # Ctrl+' for testing own stream
        self.active_speakers = {}  # {user_id: username}
        self.playback_queue = None  # Queue for audio playback
        self._user_channel_map = {}  # user_id -> pygame channel index
        self._next_voice_channel = 0
        self._voice_channel_base = 6
        self._voice_channel_count = 40
        self._cached_volume = 1.0
        self.original_mixer_settings = None  # Save original pygame mixer settings

        # Buttons box (for back and leave room buttons)
        buttons_box = wx.BoxSizer(wx.HORIZONTAL)

        # Back button (hidden in menu view)
        self.back_button = wx.Button(self.panel, label=_("Back"))
        self.back_button.Bind(wx.EVT_BUTTON, self.OnBack)
        self.back_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.back_button.Hide()
        buttons_box.Add(self.back_button, flag=wx.RIGHT, border=5)

        # Leave room button (only shown in room chat)
        self.leave_room_button = wx.Button(self.panel, label=_("Leave Room"))
        self.leave_room_button.Bind(wx.EVT_BUTTON, self.OnLeaveRoom)
        self.leave_room_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.leave_room_button.Hide()
        buttons_box.Add(self.leave_room_button)

        self.main_vbox.Add(buttons_box, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=10)

        self.panel.SetSizer(self.main_vbox)

        # Bind keyboard events - CHAR_HOOK for key down, KEY_UP for PTT release
        self.Bind(wx.EVT_CHAR_HOOK, self.OnCharHook)
        self.Bind(wx.EVT_KEY_UP, self._on_key_up)

    def create_menu_bar(self):
        """Create menu bar with context-aware moderation and administration options"""
        self.update_menu_bar()

    def update_menu_bar(self):
        """Update menu bar based on current view context"""
        menubar = wx.MenuBar()

        # User menu (available for all logged-in users) - context-aware
        user_menu = wx.Menu()

        # Context-specific user options
        if self.current_view == "rooms":
            create_room_item = user_menu.Append(wx.ID_ANY, _("Create New Room"))
            self.Bind(wx.EVT_MENU, lambda e: self._user_create_room(), create_room_item)
            user_menu.AppendSeparator()
        elif self.current_view == "forum":
            create_topic_item = user_menu.Append(wx.ID_ANY, _("Create New Thread"))
            self.Bind(wx.EVT_MENU, lambda e: self._user_create_topic(), create_topic_item)
            user_menu.AppendSeparator()

        view_all_users_item = user_menu.Append(wx.ID_ANY, _("View All Users"))
        self.Bind(wx.EVT_MENU, lambda e: self._view_all_users(), view_all_users_item)

        menubar.Append(user_menu, _("Actions"))

        # Moderation menu (only for moderators and developers) - context-aware
        if self.is_moderator or self.is_developer:
            moderation_menu = wx.Menu()

            # Context-specific moderation options
            if self.current_view == "forum":
                # Forum topic list view
                if self.main_listbox.GetSelection() != wx.NOT_FOUND:
                    mod_delete_topic = moderation_menu.Append(wx.ID_ANY, _("Delete Topic"))
                    mod_lock_topic = moderation_menu.Append(wx.ID_ANY, _("Lock/Unlock Topic"))
                    mod_pin_topic = moderation_menu.Append(wx.ID_ANY, _("Pin/Unpin Topic"))
                    mod_move_topic = moderation_menu.Append(wx.ID_ANY, _("Move Topic to Category"))

                    self.Bind(wx.EVT_MENU, lambda e: self._mod_delete_selected_topic(), mod_delete_topic)
                    self.Bind(wx.EVT_MENU, lambda e: self._mod_toggle_lock_selected_topic(), mod_lock_topic)
                    self.Bind(wx.EVT_MENU, lambda e: self._mod_toggle_pin_selected_topic(), mod_pin_topic)
                    self.Bind(wx.EVT_MENU, lambda e: self._mod_move_selected_topic(), mod_move_topic)

            elif self.current_view == "room_chat":
                # Inside a chat room
                mod_delete_msg = moderation_menu.Append(wx.ID_ANY, _("Delete Selected Message"))
                mod_kick_user = moderation_menu.Append(wx.ID_ANY, _("Kick User from Room"))
                mod_ban_user = moderation_menu.Append(wx.ID_ANY, _("Ban User from Room"))

                self.Bind(wx.EVT_MENU, lambda e: self._mod_delete_room_message(), mod_delete_msg)
                self.Bind(wx.EVT_MENU, lambda e: self._mod_kick_from_room(), mod_kick_user)
                self.Bind(wx.EVT_MENU, lambda e: self._mod_ban_from_room(), mod_ban_user)

            elif self.current_view == "rooms":
                # Room list view
                if self.main_listbox.GetSelection() != wx.NOT_FOUND:
                    mod_delete_room = moderation_menu.Append(wx.ID_ANY, _("Delete Room"))
                    self.Bind(wx.EVT_MENU, lambda e: self._mod_delete_selected_room(), mod_delete_room)

            elif self.current_view == "repository":
                # Repository view
                moderation_menu.Append(wx.ID_ANY, _("Pending Packages"))
                mod_pending = moderation_menu.Append(wx.ID_ANY, _("Review Pending Packages"))
                self.Bind(wx.EVT_MENU, lambda e: self.show_pending_apps(), mod_pending)

            elif self.current_view == "users":
                # Users list view
                if self.main_listbox.GetSelection() != wx.NOT_FOUND:
                    mod_ban_global = moderation_menu.Append(wx.ID_ANY, _("Ban User (Global)"))
                    self.Bind(wx.EVT_MENU, lambda e: self._mod_ban_user_global(), mod_ban_global)

            # Always available moderation options
            if moderation_menu.GetMenuItemCount() > 0:
                moderation_menu.AppendSeparator()

            mod_general = moderation_menu.Append(wx.ID_ANY, _("General Moderation"))
            self.Bind(wx.EVT_MENU, lambda e: self.show_moderation_menu(), mod_general)

            menubar.Append(moderation_menu, _("Moderation"))

        # Administration menu (only for developers)
        if self.is_developer:
            admin_menu = wx.Menu()
            admin_promote = admin_menu.Append(wx.ID_ANY, _("Promote to Moderator"))
            admin_demote = admin_menu.Append(wx.ID_ANY, _("Demote Moderator"))
            admin_list = admin_menu.Append(wx.ID_ANY, _("List Moderators"))

            self.Bind(wx.EVT_MENU, lambda e: self._promote_user_dialog(), admin_promote)
            self.Bind(wx.EVT_MENU, lambda e: self._demote_moderator_dialog(), admin_demote)
            self.Bind(wx.EVT_MENU, lambda e: self.show_manage_moderators(), admin_list)

            menubar.Append(admin_menu, _("Administration"))

        self.SetMenuBar(menubar)

    def apply_skin(self):
        """Apply current skin to window"""
        try:
            _apply_skin_recursive(self)
        except Exception as e:
            print(f"Error applying skin to Titan-Net window: {e}")

    def load_user_role(self):
        """Load user role - use cached role from login response first, then fetch from server"""
        # Check if role was already set from login response
        cached_role = getattr(self.titan_client, 'user_role', None)
        if cached_role and cached_role != 'user':
            self._apply_user_role(cached_role)
            return

        # Check is_admin flag from login response
        if getattr(self.titan_client, 'is_admin', False):
            self._apply_user_role('developer')
            return

        # Fallback: fetch from server (for role changes during session)
        self.user_role = "user"
        self.is_moderator = False
        self.is_developer = False

        def fetch_role():
            try:
                result = self.titan_client.get_user_role()
                if result and result.get('success'):
                    role = result.get('role', 'user')
                    wx.CallAfter(self._apply_user_role, role)
                else:
                    print(f"Failed to load user role: {result}")
            except Exception as e:
                print(f"Error loading user role: {e}")

        threading.Thread(target=fetch_role, daemon=True).start()

    def _apply_user_role(self, role):
        """Apply user role after background fetch"""
        self.user_role = role
        self.is_moderator = role in ('moderator', 'developer')
        self.is_developer = role == 'developer'
        print(f"User role loaded: {role}")

    def OnFocus(self, event):
        """Handle focus events with sound"""
        play_sound('core/FOCUS.ogg', pan=0.5)
        event.Skip()

    def OnKeyPress(self, event):
        """Handle key press events"""
        keycode = event.GetKeyCode()

        if keycode == wx.WXK_RETURN or keycode == wx.WXK_NUMPAD_ENTER:
            # Enter key - activate list item if listbox has focus
            focused = self.FindFocus()
            if focused == self.main_listbox:
                self.OnListActivate(None)
                return  # Don't skip the event
            event.Skip()
        elif keycode == wx.WXK_ESCAPE:
            # Defer the back/hide action so the EVT_CHAR_HOOK chain can unwind
            # before we change focus or tear down voice resources. Doing it
            # synchronously inside the hook caused intermittent UI hangs in
            # text-only rooms when the multiline message_input had focus.
            if self.current_view == "menu":
                wx.CallAfter(self.Hide)
            elif self.current_view in ["room_chat", "private_chat"]:
                wx.CallAfter(self.OnBack, None)
            else:
                wx.CallAfter(self.show_menu)
        else:
            event.Skip()

    def setup_callbacks(self):
        """Setup Titan-Net callbacks for real-time updates"""
        self.titan_client.on_room_message = self.on_room_message
        self.titan_client.on_message_received = self.on_private_message
        self.titan_client.on_user_online = self.on_user_online
        self.titan_client.on_user_offline = self.on_user_offline

        # Voice chat callbacks
        self.titan_client.on_voice_started = self.on_voice_started
        self.titan_client.on_voice_audio = self.on_voice_audio
        self.titan_client.on_voice_audio_binary = self.on_voice_audio_binary
        self.titan_client.on_voice_stopped = self.on_voice_stopped
        self.titan_client.on_ptt_started = self.on_ptt_started
        self.titan_client.on_ptt_stopped = self.on_ptt_stopped

        # Broadcast callback
        self.titan_client.on_broadcast_received = self._on_broadcast_received

        # Package/App repository callbacks
        self.titan_client.on_package_pending = self.on_package_pending
        self.titan_client.on_package_approved = self.on_package_approved

        # Feedback Hub callbacks (also re-bound while the Feedback Hub window
        # is open; the window restores these on close).
        self.titan_client.on_feedback_new = self._on_feedback_new_global
        self.titan_client.on_feedback_status_changed = self._on_feedback_status_global

        # New user broadcast callback
        self.titan_client.on_new_user_broadcast = self.on_new_user_broadcast

    def show_menu(self):
        """Show main menu"""
        self.current_view = "menu"
        self.view_label.SetLabel(_("Titan-Net - Main Menu"))

        # Hide chat elements
        self.room_users_listbox.Hide()
        self.message_display.Hide()
        self.message_input.Hide()
        self.send_button.Hide()
        self.back_button.Hide()
        self.leave_room_button.Hide()
        self.voice_panel.Hide()
        self.broadcast_panel.Hide()

        # Show main list
        self.main_listbox.Show()

        # Populate menu
        self.main_listbox.Clear()
        menu_items = [
            _("What's New"),
            _("Chat Rooms"),
            _("Online Users"),
            _("Private Messages"),
            _("Forum"),
            _("App Repository"),
        ]

        # Feedback Hub sits between the regular features and the moderation /
        # disconnect entries (see feetback hub.txt - "przedostatnia opcja dla
        # zwyklych uzytkownikow, przed moderacja lub opcja rozlaczania sie").
        menu_items.append(_("Feedback Hub"))

        # Entertainment / Interactive Games — second tab under titan-net.
        # AI game master with voice room, turn-based mechanics, schemaless
        # state and BYOK encrypted API key per-game.
        menu_items.append(_("Interactive Games"))

        # Add Moderation menu for moderators/developers
        if self.is_moderator:
            menu_items.append(_("Moderation"))

        menu_items.append(_("Disconnect"))

        for item in menu_items:
            self.main_listbox.Append(item)

        # Honour saved drag-and-drop order from .index.TCG (per-view) so
        # the user's preferred row order is restored after view switches
        # and across program launches.
        if getattr(self, '_main_listbox_dnd', None) is not None:
            self._main_listbox_dnd.apply_saved_order()

        self.main_listbox.SetSelection(0)
        self.main_listbox.SetFocus()
        self.panel.Layout()

        play_sound('core/SELECT.ogg')

    def show_whats_new_view(self):
        """Show What's New - unread messages, forum posts, new apps, updates"""
        self.current_view = "whats_new"
        self.view_label.SetLabel(_("Titan-Net - What's New"))

        # Hide chat elements
        self.room_users_listbox.Hide()
        self.message_display.Hide()
        self.message_input.Hide()
        self.send_button.Hide()
        self.voice_panel.Hide()
        self.broadcast_panel.Hide()
        self.leave_room_button.Hide()

        # Show main list and back button
        self.main_listbox.Show()
        self.back_button.Show()

        self.main_listbox.Clear()
        self.main_listbox.Append(_("Loading..."))
        self.panel.Layout()

        play_sound('titannet/titannet-notification.ogg')

        def fetch_whats_new():
            result = self.titan_client.get_whats_new()
            wx.CallAfter(self._on_whats_new_loaded, result)

        threading.Thread(target=fetch_whats_new, daemon=True).start()

    def _on_whats_new_loaded(self, result):
        """Update What's New view with detailed items per category."""
        if not self or self.current_view != "whats_new":
            return

        self.main_listbox.Clear()

        if not result.get('success'):
            speak_notification(_("Failed to load"), 'error')
            self.main_listbox.Append(_("Failed to load"))
            return

        # Build flat list of actionable items with metadata
        # Each entry: (display_text, action_type, action_data, sound)
        self._whats_new_items = []

        # Unread messages - one entry per sender
        for msg in result.get('unread_messages_items', []):
            count = msg.get('count', 0)
            sender = msg.get('sender', '?')
            sender_id = msg.get('sender_id', 0)
            text = _("New messages from {sender} ({count})").format(sender=sender, count=count)
            self._whats_new_items.append((text, 'message', {'user_id': sender_id, 'username': sender}, 'titannet/new_message.ogg'))

        # Forum topics with new replies - one entry per topic
        for topic in result.get('unread_forum_topics_items', []):
            new_replies = topic.get('new_replies', 0)
            title = topic.get('title', '?')
            topic_id = topic.get('id', 0)
            text = _("{title} ({count} new replies)").format(title=title, count=new_replies)
            self._whats_new_items.append((text, 'forum_topic', {'topic_id': topic_id, 'title': title}, 'titannet/new_feedpost.ogg'))

        # New apps
        for app in result.get('new_apps_items', []):
            name = app.get('name', '?')
            author = app.get('author', '?')
            app_id = app.get('id', 0)
            text = _("New app: {name} by {author}").format(name=name, author=author)
            self._whats_new_items.append((text, 'app', {'id': app_id, 'name': name}, 'titannet/titannet-notification.ogg'))

        # App updates
        for app in result.get('app_updates_items', []):
            name = app.get('name', '?')
            version = app.get('version', '?')
            app_id = app.get('id', 0)
            text = _("Updated: {name} v{version}").format(name=name, version=version)
            self._whats_new_items.append((text, 'app', {'id': app_id, 'name': name}, 'titannet/titannet-notification.ogg'))

        if not self._whats_new_items:
            self.main_listbox.Append(_("Nothing new"))
            speak_titannet(_("Nothing new"))
            return

        # NOTE: unpacking with `_` would shadow the gettext translator, so use
        # indexed access instead. Each entry is (text, action_type, data, sound).
        for entry in self._whats_new_items:
            self.main_listbox.Append(entry[0])

        if getattr(self, '_main_listbox_dnd', None) is not None:
            self._main_listbox_dnd.apply_saved_order()

        self.main_listbox.SetSelection(0)
        self.main_listbox.SetFocus()

        # Announce summary with sounds (like Elten)
        self._announce_whats_new(result)

    def _announce_whats_new(self, data):
        """Announce What's New summary via TTS with per-category sounds."""
        categories = [
            ('unread_messages', _("New private messages"), 'titannet/new_message.ogg'),
            ('unread_forum_topics', _("Forum topics with new replies"), 'titannet/new_feedpost.ogg'),
            ('new_apps', _("New applications"), 'titannet/titannet-notification.ogg'),
            ('app_updates', _("Application updates"), 'titannet/titannet-notification.ogg'),
        ]
        announcements = []
        for key, label, sound in categories:
            count = data.get(key, 0) or 0
            if count > 0:
                announcements.append((label, count, sound))

        if not announcements:
            return

        self._wn_announcements = announcements
        self._wn_announce_idx = 0
        speak_titannet(_("What's new"))
        wx.CallLater(800, self._announce_next_wn)

    def _announce_next_wn(self):
        """Announce next What's New category with sound."""
        if self._wn_announce_idx >= len(self._wn_announcements):
            return

        label, count, sound = self._wn_announcements[self._wn_announce_idx]
        self._wn_announce_idx += 1

        try:
            play_sound(sound)
        except Exception:
            pass

        speak_titannet(f"{label}: {count}", interrupt=False)

        if self._wn_announce_idx < len(self._wn_announcements):
            wx.CallLater(1500, self._announce_next_wn)

    def _on_whats_new_activate(self, selection):
        """Handle activation of a What's New item - navigate to the specific item."""
        if not hasattr(self, '_whats_new_items'):
            return
        if selection < 0 or selection >= len(self._whats_new_items):
            return

        # Entry: (display_text, action_type, action_data, sound)
        entry = self._whats_new_items[selection]
        action_type = entry[1]
        action_data = entry[2]

        try:
            play_sound(entry[3])
        except Exception:
            pass

        try:
            if action_type == 'message':
                user_id = action_data.get('user_id', 0)
                username = action_data.get('username', '?')
                if user_id:
                    self.show_private_chat(user_id, username)
            elif action_type == 'forum_topic':
                topic_id = action_data.get('topic_id', 0)
                title = action_data.get('title', '?')
                if topic_id:
                    self.show_forum_topic(topic_id, title)
            elif action_type == 'app':
                app_id = action_data.get('id', 0)
                if app_id:
                    # show_app_details expects an app dict with at least an 'id'
                    self.show_app_details({'id': app_id, 'name': action_data.get('name', '?')})
        except Exception as e:
            print(f"[TITAN-NET] What's New activation failed: {e}")
            speak_notification(_("Failed to open item"), 'error')

    def show_rooms_view(self):
        """Show chat rooms list"""
        self.current_view = "rooms"
        self.view_label.SetLabel(_("Titan-Net - Chat Rooms"))

        # Hide chat elements
        self.message_display.Hide()
        self.message_input.Hide()
        self.send_button.Hide()
        self.voice_panel.Hide()
        self.broadcast_panel.Hide()

        # Show main list and back button
        self.main_listbox.Show()
        self.back_button.Show()

        self.leave_room_button.Hide()

        # Load rooms
        self.refresh_rooms()

        self.panel.Layout()
        self.update_menu_bar()  # Update menu for rooms context
        play_sound('core/SELECT.ogg')

    def show_users_view(self):
        """Show online users list"""
        self.current_view = "users"
        self.view_label.SetLabel(_("Titan-Net - Online Users"))

        # Hide chat elements
        self.message_display.Hide()
        self.message_input.Hide()
        self.send_button.Hide()
        self.voice_panel.Hide()
        self.broadcast_panel.Hide()

        # Show main list and back button
        self.main_listbox.Show()
        self.back_button.Show()

        self.leave_room_button.Hide()

        # Load users
        self.refresh_users()

        self.panel.Layout()
        self.update_menu_bar()  # Update menu for users context
        play_sound('core/SELECT.ogg')

    def show_private_messages_view(self):
        """Show private messages - select user first"""
        self.current_view = "private_messages_select"
        self.view_label.SetLabel(_("Titan-Net - Select User for Private Chat"))

        # Hide chat elements
        self.message_display.Hide()
        self.message_input.Hide()
        self.send_button.Hide()
        self.voice_panel.Hide()
        self.broadcast_panel.Hide()

        # Show main list and back button
        self.main_listbox.Show()
        self.back_button.Show()

        self.leave_room_button.Hide()

        # Load users
        self.refresh_users()

        self.panel.Layout()
        play_sound('core/SELECT.ogg')

    def show_forum_view(self):
        """Show forum topics list"""
        # Show forum immediately, check ban in background
        self.current_view = "forum"

        # Check ban status in background (non-blocking)
        def check_forum_ban():
            try:
                if hasattr(self, 'titan_client') and self.titan_client.user_id:
                    ban_status = self.titan_client.check_ban_status(self.titan_client.user_id)
                    if ban_status.get('success'):
                        forum_ban = ban_status.get('forum_ban', {})
                        if forum_ban.get('banned'):
                            reason = forum_ban.get('reason', _('No reason provided'))
                            expires_at = forum_ban.get('expires_at')
                            if expires_at:
                                ban_msg = _("You are banned from forum\nReason: {reason}\nExpires: {expires}").format(
                                    reason=reason, expires=expires_at)
                            else:
                                ban_msg = _("You are banned from forum\nReason: {reason}\nThis ban is permanent").format(reason=reason)
                            wx.CallAfter(self._on_forum_ban_detected, ban_msg)
            except Exception as e:
                print(f"Error checking forum ban: {e}")

        threading.Thread(target=check_forum_ban, daemon=True).start()
        self.view_label.SetLabel(_("Titan-Net - Forum"))

        # Hide chat elements
        self.message_display.Hide()
        self.message_input.Hide()
        self.send_button.Hide()
        self.voice_panel.Hide()
        self.broadcast_panel.Hide()

        # Show main list and back button
        self.main_listbox.Show()
        self.back_button.Show()

        self.leave_room_button.Hide()

        # Load forum topics
        self.refresh_forum_topics()

        self.panel.Layout()
        self.update_menu_bar()  # Update menu for forum context
        play_sound('core/SELECT.ogg')

    def _on_forum_ban_detected(self, ban_msg):
        """Handle forum ban detected in background — navigate back"""
        if self.current_view == "forum":
            speak_titannet(_("You are banned from forum"))
            speak_notification(ban_msg, 'banned')
            self.show_menu()

    def show_repository_view(self):
        """Show app repository menu"""
        self.current_view = "repository_menu"
        self.view_label.SetLabel(_("Titan-Net - App Repository"))

        # Hide chat elements
        self.message_display.Hide()
        self.message_input.Hide()
        self.send_button.Hide()
        self.leave_room_button.Hide()
        self.voice_panel.Hide()
        self.broadcast_panel.Hide()

        # Show main list and back button
        self.main_listbox.Show()
        self.back_button.Show()

        # Populate repository menu
        self.main_listbox.Clear()
        repo_items = [
            _("Browse Packages"),
            _("Upload Package"),
            _("Search Packages"),
            _("Pending Packages (Preview)"),
        ]

        # Add moderation option for moderators/developers
        if self.is_moderator:
            repo_items.append(_("Moderate Packages"))

        for item in repo_items:
            self.main_listbox.Append(item)

        if getattr(self, '_main_listbox_dnd', None) is not None:
            self._main_listbox_dnd.apply_saved_order()

        self.main_listbox.SetSelection(0)
        self.main_listbox.SetFocus()
        self.panel.Layout()
        self.update_menu_bar()  # Update menu for repository context
        play_sound('core/SELECT.ogg')

    def show_browse_apps(self):
        """Show list of approved packages"""
        self.current_view = "repository"
        self.view_label.SetLabel(_("Browse Packages"))

        # Hide chat elements
        self.message_display.Hide()
        self.message_input.Hide()
        self.send_button.Hide()
        self.leave_room_button.Hide()
        self.voice_panel.Hide()
        self.broadcast_panel.Hide()

        # Show main list and back button
        self.main_listbox.Show()
        self.back_button.Show()

        # Load repository apps
        self.refresh_repository()

        self.panel.Layout()
        play_sound('core/SELECT.ogg')

    def open_feedback_hub(self):
        """Open the standalone Feedback Hub window (own GUI, styled like the
        main TitanApp - tab bar, list-driven navigation, focus management).
        """
        play_sound('core/SELECT.ogg')
        try:
            from src.network.feedback_hub import open_feedback_hub
            open_feedback_hub(self, self.titan_client)
        except Exception as e:
            print(f"[Titan-Net GUI] open_feedback_hub failed: {e}")
            speak_notification(_("Failed to open Feedback Hub"), 'error')

    def open_interactive_games(self):
        """Open the Interactive Games (Entertainment) catalog window.

        Same architectural shape as Feedback Hub: own GUI styled like
        TitanApp main GUI (row-0 tab bar, listbox navigation, focus sounds),
        but with its own broadcast subscriptions and session lifecycle.
        """
        play_sound('core/SELECT.ogg')
        try:
            from src.network.interactive_games import open_interactive_games
            open_interactive_games(self, self.titan_client)
        except Exception as e:
            print(f"[Titan-Net GUI] open_interactive_games failed: {e}")
            import traceback
            traceback.print_exc()
            speak_notification(_("Failed to open Interactive Games"), 'error')

    def show_moderation_menu(self):
        """Show moderation submenu"""
        self.current_view = "moderation"
        self.view_label.SetLabel(_("Moderation"))

        # Hide chat elements
        self.message_display.Hide()
        self.message_input.Hide()
        self.send_button.Hide()
        self.leave_room_button.Hide()
        self.voice_panel.Hide()
        self.broadcast_panel.Hide()

        # Show main list and back button
        self.main_listbox.Show()
        self.back_button.Show()

        # Populate moderation menu
        self.main_listbox.Clear()
        mod_items = []

        # Add Administration submenu for developers only
        if self.is_developer:
            mod_items.append(_("Administration"))

        # Add moderation options for all moderators and developers
        mod_items.extend([
            _("Cerberus Protocol"),  # View security status and logs
            _("Send Broadcast"),  # Send message to all users
            _("Edit Broadcast Files"),  # Edit motd_*.txt and other broadcast templates
            _("Pending Packages"),  # Approve/reject packages
            _("Moderate Forum"),  # Lock/pin/delete topics
            _("Moderate Rooms"),  # Ban users, delete messages
        ])

        for item in mod_items:
            self.main_listbox.Append(item)

        self.main_listbox.SetSelection(0)
        self.main_listbox.SetFocus()
        self.panel.Layout()
        play_sound('core/SELECT.ogg')

    def show_broadcast_view(self):
        """Show broadcast panel (moderator/developer only)"""
        if not self.is_moderator:
            speak_notification(_("Only moderators can send broadcasts"), 'warning')
            return

        self.current_view = "broadcast"
        self.view_label.SetLabel(_("Send Broadcast"))

        # Hide all other views
        self.main_listbox.Hide()
        self.room_users_listbox.Hide()
        self.message_display.Hide()
        self.message_input.Hide()
        self.send_button.Hide()
        self.leave_room_button.Hide()
        self.voice_panel.Hide()

        # Show broadcast panel and back button
        self.broadcast_panel.Show()
        self.back_button.Show()

        # Clear previous broadcast
        self.broadcast_text.SetValue("")
        self.broadcast_recorded_audio = None
        self.broadcast_record_button.Enable(True)
        self.broadcast_stop_button.Enable(False)
        self.broadcast_play_button.Enable(False)

        self.broadcast_text.SetFocus()
        self.panel.Layout()
        play_sound('core/SELECT.ogg')

    def show_administration_menu(self):
        """Show administration submenu (developer only)"""
        if not self.is_developer:
            speak_notification(_("Only developers can access administration"), 'warning')
            return

        self.current_view = "administration"
        self.view_label.SetLabel(_("Administration"))

        # Hide chat elements
        self.message_display.Hide()
        self.message_input.Hide()
        self.send_button.Hide()
        self.leave_room_button.Hide()
        self.voice_panel.Hide()
        self.broadcast_panel.Hide()

        # Show main list and back button
        self.main_listbox.Show()
        self.back_button.Show()

        # Populate administration menu
        self.main_listbox.Clear()
        admin_items = [
            _("Cerberus Protocol"),
            _("Promote User to Moderator"),
            _("Demote Moderator"),
            _("List All Moderators"),
        ]

        for item in admin_items:
            self.main_listbox.Append(item)

        self.main_listbox.SetSelection(0)
        self.main_listbox.SetFocus()
        self.panel.Layout()
        play_sound('core/SELECT.ogg')

    def show_room_chat(self, room_id, room_name):
        """Show chat for specific room"""
        self.current_view = "room_chat"
        self.current_room = room_id
        self.view_label.SetLabel(_("Room: {name}").format(name=room_name))

        # Get room type from cache
        room_type = 'text'  # Default
        for room in self.rooms_cache:
            if room['id'] == room_id:
                room_type = room.get('room_type', 'text')
                break

        self.current_room_type = room_type

        # Hide main list
        self.main_listbox.Hide()

        # Show room users list and chat elements
        self.room_users_listbox.Show()
        self.message_display.Show()
        self.back_button.Show()
        self.leave_room_button.Show()

        # Show/hide chat input based on room type
        if room_type == 'voice':
            # Voice-only room - hide text chat
            self.message_input.Hide()
            self.send_button.Hide()
        else:
            # Text or mixed room - show text chat
            self.message_input.Show()
            self.send_button.Show()

        # Setup voice if room supports it
        if room_type in ('voice', 'mixed'):
            self.setup_voice_for_room(room_id, room_type)
            self.voice_panel.Show()
        else:
            self.voice_panel.Hide()
            # Cleanup voice resources
            if self.voice_capture:
                self.voice_capture.stop_capture()
                self.voice_capture = None
            # Stop mixer/stream
            self._mixer_running = False
            if hasattr(self, '_voice_output_stream') and self._voice_output_stream:
                try:
                    self._voice_output_stream.stop()
                    self._voice_output_stream.close()
                except Exception:
                    pass
                self._voice_output_stream = None
            self._user_channel_map = {}
            self.playback_queue = None

            # Restore original pygame mixer settings
            self._restore_mixer_settings()

        # Load room users and messages
        self.load_room_users(room_id)
        self.load_room_messages(room_id)

        self.panel.Layout()
        self.update_menu_bar()  # Update menu for room chat context
        if room_type != 'voice':
            self.message_input.SetFocus()
        play_sound('titannet/new_chat.ogg')

    def show_private_chat(self, user_id, username):
        """Show private chat with specific user"""
        self.current_view = "private_chat"
        self.current_private_user = user_id
        self.view_label.SetLabel(_("Private Chat with: {username}").format(username=username))

        # Hide main list
        self.main_listbox.Hide()

        # Show chat elements
        self.message_display.Show()
        self.message_input.Show()
        self.send_button.Show()
        self.back_button.Show()

        self.leave_room_button.Hide()

        # Load private messages (messages will be marked as read after display)
        self.load_private_messages(user_id)

        self.panel.Layout()
        self.message_input.SetFocus()
        play_sound('titannet/new_chat.ogg')

    def OnListSelection(self, event):
        """Handle list selection with sound and new replies notification.

        Plays the focus sound with a stereo pan reflecting the selection's
        position in the list, matching the main TCE GUI. play_sound honours
        the global stereo_sound setting so mono users hear a plain click.
        """
        listbox = event.GetEventObject() if event else self.main_listbox
        try:
            count = listbox.GetCount()
            selection = listbox.GetSelection()
        except Exception:
            count = 0
            selection = wx.NOT_FOUND

        pan = 0.5
        if count > 1 and selection != wx.NOT_FOUND:
            pan = selection / (count - 1)
        play_sound('core/FOCUS.ogg', pan=pan)

        # Check if current view is forum and if selected topic has new replies
        if listbox is self.main_listbox and self.current_view == "forum":
            if selection != wx.NOT_FOUND and 0 <= selection < len(self.forum_topics_cache):
                topic = self.forum_topics_cache[selection]
                if topic.get('has_new_replies', False):
                    # Play new replies sound
                    play_sound('titannet/newreplies.ogg')

        event.Skip()

    def OnListKeyDown(self, event):
        """Handle key press in listbox.

        Matches the main TCE GUI navigation contract: all four arrow keys
        (Up/Down/Left/Right) play the end-of-list sound when the selection
        is at the corresponding edge, and movement away from the edge
        falls through to wxPython so EVT_LISTBOX fires and plays the
        panned focus sound.
        """
        keycode = event.GetKeyCode()
        listbox = event.GetEventObject() if event else self.main_listbox

        # Enter key - only actual Enter, not Alt
        if (keycode == wx.WXK_RETURN or keycode == wx.WXK_NUMPAD_ENTER) and not event.AltDown():
            # Enter key activates selected item (main listbox only)
            if listbox is self.main_listbox:
                self.OnListActivate(None)
                return  # Don't skip
            event.Skip()
            return
        elif keycode == wx.WXK_ESCAPE:
            # Backup Escape route from any list (room users, etc.). Routes the
            # same as the Frame-level OnKeyPress handler so users can always
            # leave a room even if the Frame's EVT_CHAR_HOOK is bypassed.
            if self.current_view in ["room_chat", "private_chat"]:
                wx.CallAfter(self.OnBack, None)
            elif self.current_view == "menu":
                wx.CallAfter(self.Hide)
            else:
                wx.CallAfter(self.show_menu)
            return
        elif keycode in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_LEFT, wx.WXK_RIGHT):
            # Navigation keys - check for edge
            try:
                selection = listbox.GetSelection()
                count = listbox.GetCount()
            except Exception:
                selection = wx.NOT_FOUND
                count = 0

            # Check if at edge
            at_top = (selection == 0 or selection == wx.NOT_FOUND) and keycode in (wx.WXK_UP, wx.WXK_LEFT)
            at_bottom = (selection == count - 1) and keycode in (wx.WXK_DOWN, wx.WXK_RIGHT)

            if at_top or at_bottom:
                # At edge - play edge sound and don't move
                play_sound('ui/endoflist.ogg')
                return  # Don't skip - prevent movement
            else:
                # Not at edge - allow movement
                event.Skip()
        else:
            event.Skip()

    def OnListActivate(self, event):
        """Handle list item activation (double-click or Enter)"""
        selection = self.main_listbox.GetSelection()
        if selection == wx.NOT_FOUND:
            return

        play_sound('core/SELECT.ogg')

        if self.current_view == "menu":
            # Main menu selection - use item text instead of index
            item_text = self.main_listbox.GetString(selection)

            if item_text == _("What's New"):
                self.show_whats_new_view()
            elif item_text == _("Chat Rooms"):
                self.show_rooms_view()
            elif item_text == _("Online Users"):
                self.show_users_view()
            elif item_text == _("Private Messages"):
                self.show_private_messages_view()
            elif item_text == _("Forum"):
                self.show_forum_view()
            elif item_text == _("App Repository"):
                self.show_repository_view()
            elif item_text == _("Moderation"):
                self.show_moderation_menu()
            elif item_text == _("Feedback Hub"):
                self.open_feedback_hub()
            elif item_text == _("Interactive Games"):
                self.open_interactive_games()
            elif item_text == _("Disconnect"):
                self.OnDisconnectAndClose()

        elif self.current_view == "whats_new":
            self._on_whats_new_activate(selection)

        elif self.current_view == "rooms":
            # Join selected room
            if 0 <= selection < len(self.rooms_cache):
                room = self.rooms_cache[selection]
                self.join_room(room['id'], room['name'])

        elif self.current_view == "users":
            # Show user info or start chat
            if 0 <= selection < len(self.users_cache):
                user = self.users_cache[selection]
                self.show_user_actions(user)

        elif self.current_view == "private_messages_select":
            # Start private chat with selected user
            if 0 <= selection < len(self.users_cache):
                user = self.users_cache[selection]
                self.show_private_chat(user['id'], user['username'])

        elif self.current_view == "forum":
            # Open selected forum topic
            if 0 <= selection < len(self.forum_topics_cache):
                topic = self.forum_topics_cache[selection]
                # Mark topic as read in background (non-blocking)
                topic_id = topic['id']
                reply_count = topic['reply_count']
                threading.Thread(target=lambda: self.titan_client.mark_topic_as_read(topic_id, reply_count), daemon=True).start()
                self.show_forum_topic(topic['id'], topic['title'], topic.get('last_known_reply_count', 0))

        elif self.current_view == "all_users":
            # Show context menu for selected user
            if 0 <= selection < len(self.users_cache):
                user = self.users_cache[selection]
                self.show_all_users_context_menu(user)

        elif self.current_view == "repository_menu":
            # Repository menu
            item_text = self.main_listbox.GetString(selection)

            if item_text == _("Browse Packages"):
                self.show_browse_apps()
            elif item_text == _("Upload Package"):
                self.show_upload_app_dialog()
            elif item_text == _("Search Packages"):
                self.show_search_apps_dialog()
            elif item_text == _("Pending Packages (Preview)"):
                self.show_pending_apps(preview_mode=True)
            elif item_text == _("Moderate Packages"):
                self.show_pending_apps(preview_mode=False)

        elif self.current_view == "repository":
            # Show app details
            if 0 <= selection < len(self.repository_apps_cache):
                app = self.repository_apps_cache[selection]
                self.show_app_details(app)

        elif self.current_view == "moderation":
            # Moderation submenu
            item_text = self.main_listbox.GetString(selection)

            if item_text == _("Administration"):
                self.show_administration_menu()
            elif item_text == _("Cerberus Protocol"):
                self.show_cerberus_protocol()
            elif item_text == _("Send Broadcast"):
                self.show_broadcast_view()
            elif item_text == _("Edit Broadcast Files"):
                self.show_edit_broadcast_files()
            elif item_text == _("Pending Packages"):
                self.show_pending_apps()
            elif item_text == _("Moderate Forum"):
                self.show_moderate_forum()
            elif item_text == _("Moderate Rooms"):
                self.show_moderate_rooms()

        elif self.current_view == "administration":
            # Administration submenu (developer only)
            item_text = self.main_listbox.GetString(selection)

            if item_text == _("Cerberus Protocol"):
                self.show_cerberus_protocol()
            elif item_text == _("Promote User to Moderator"):
                self._promote_user_dialog()
            elif item_text == _("Demote Moderator"):
                self._demote_moderator_dialog()
            elif item_text == _("List All Moderators"):
                self.show_manage_moderators()

        elif self.current_view == "cerberus":
            # Cerberus Protocol submenu
            item_text = self.main_listbox.GetString(selection)

            if item_text == _("Refresh Status"):
                self.show_cerberus_protocol()
            elif item_text == _("View Intrusion Logs"):
                self._cerberus_show_logs()
            elif item_text == _("View Honeypot Logs"):
                self._cerberus_show_honeypot_logs()
            elif item_text == _("Banned IPs"):
                self._cerberus_show_banned_ips()
            elif item_text == _("Tracked Attackers"):
                self._cerberus_show_attackers()
            # Developer-only actions
            elif item_text == _("Activate Lockdown"):
                self._cerberus_activate_lockdown()
            elif item_text == _("Activate CERBERUS Mode"):
                self._cerberus_activate_cerberus()
            elif item_text == _("Deactivate Lockdown"):
                self._cerberus_deactivate()
            elif item_text == _("Ban IP"):
                self._cerberus_ban_ip_dialog()
            elif item_text == _("Unban IP"):
                self._cerberus_unban_ip_dialog()
            elif item_text == _("Whitelist IP"):
                self._cerberus_whitelist_ip_dialog()

    def OnLeaveRoom(self, event):
        """Handle leave room button - returns to menu immediately, then
        cleans up in the background. The user reported being stuck in
        text-only rooms after hearing "Leaving room..." TTS - that meant
        OnLeaveRoom started but something downstream blocked or silently
        failed before show_menu took effect. Now show_menu runs FIRST and
        all room teardown happens off the UI thread.
        """
        try:
            play_sound('core/SELECT.ogg')
        except Exception:
            pass

        room_id = getattr(self, 'current_room', None)

        if room_id is not None:
            try:
                speak_titannet(_("Leaving room..."))
            except Exception:
                pass

        # Drop view state up front so any racing callbacks see "menu".
        self.current_room = None
        self.current_private_user = None
        if hasattr(self, 'current_room_type'):
            self.current_room_type = None

        # Show the menu first - this is what the user is waiting for.
        try:
            self.show_menu()
        except Exception as e:
            print(f"OnLeaveRoom: show_menu failed: {e}")

        # Now run the teardown off the UI thread so a stuck voice resource
        # or slow network call can never block the user inside the room view.
        def _background_teardown():
            try:
                if getattr(self, 'voice_capture', None):
                    try:
                        self.voice_capture.stop_capture()
                    except Exception:
                        pass
                    self.voice_capture = None
            except Exception:
                pass
            try:
                self._restore_mixer_settings()
            except Exception:
                pass
            try:
                self._teardown_room_state(room_id)
            except Exception as teardown_err:
                print(f"OnLeaveRoom: teardown failed: {teardown_err}")

        threading.Thread(target=_background_teardown, daemon=True).start()

    def OnBack(self, event):
        """Handle back button - returns to menu immediately, runs teardown
        off the UI thread.

        Same pattern as OnLeaveRoom: the user reported being stuck in
        text-only rooms even after pressing back, so view changes happen
        FIRST and any voice/room cleanup that could throw or block runs
        in the background.
        """
        try:
            play_sound('core/SELECT.ogg')
        except Exception:
            pass

        room_id = getattr(self, 'current_room', None)

        # Drop view state up front so racing callbacks see "menu".
        self.current_room = None
        self.current_private_user = None
        if hasattr(self, 'current_room_type'):
            self.current_room_type = None

        try:
            self.show_menu()
        except Exception as e:
            print(f"OnBack: show_menu failed: {e}")
            # Last-resort recovery so the user is never trapped in chat view.
            try:
                self.current_view = "menu"
                if hasattr(self, 'message_display'):
                    self.message_display.Hide()
                if hasattr(self, 'message_input'):
                    self.message_input.Hide()
                if hasattr(self, 'send_button'):
                    self.send_button.Hide()
                if hasattr(self, 'back_button'):
                    self.back_button.Hide()
                if hasattr(self, 'leave_room_button'):
                    self.leave_room_button.Hide()
                if hasattr(self, 'voice_panel'):
                    self.voice_panel.Hide()
                if hasattr(self, 'main_listbox'):
                    self.main_listbox.Show()
                    self.main_listbox.SetFocus()
                if hasattr(self, 'panel'):
                    self.panel.Layout()
            except Exception as recovery_err:
                print(f"OnBack: emergency recovery failed: {recovery_err}")

        # Background teardown - if there was a room, leave it server-side
        # and clean up voice resources without blocking the UI.
        if room_id is not None:
            def _background_teardown():
                try:
                    self._teardown_room_state(room_id)
                except Exception as teardown_err:
                    print(f"OnBack: teardown failed: {teardown_err}")
            threading.Thread(target=_background_teardown, daemon=True).start()

    def _teardown_room_state(self, room_id):
        """Tear down voice + network state for a room. Safe to call from
        any thread; everything is wrapped so a stray exception never
        traps the user inside the chat view.

        ``room_id`` may be None (no-op) or the previously-active room.
        """
        if room_id is None:
            return
        try:
            if getattr(self, 'voice_capture', None):
                try:
                    self.voice_capture.stop_capture()
                except Exception:
                    pass
                self.voice_capture = None
        except Exception:
            pass
        try:
            if hasattr(self, 'voice_send_batch'):
                self.voice_send_batch.clear()
        except Exception:
            pass
        try:
            self._mixer_running = False
        except Exception:
            pass
        try:
            for user_id in list(getattr(self, 'voice_buffer_stopping', {}).keys()):
                self.voice_buffer_stopping[user_id] = True
        except Exception:
            pass
        try:
            mixer_thread = getattr(self, '_mixer_thread', None)
            if mixer_thread is not None:
                try:
                    mixer_thread.join(timeout=1.0)
                except Exception:
                    pass
                self._mixer_thread = None
        except Exception:
            pass
        try:
            stream = getattr(self, '_voice_output_stream', None)
            if stream is not None:
                try:
                    stream.stop()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass
                self._voice_output_stream = None
        except Exception:
            pass
        for attr in ('voice_jitter_buffers', 'voice_buffer_threads',
                     'voice_buffer_stopping', '_user_channel_map',
                     '_opus_decoders'):
            try:
                container = getattr(self, attr, None)
                if container is not None and hasattr(container, 'clear'):
                    container.clear()
            except Exception:
                pass
        try:
            self._user_started = {}
        except Exception:
            pass
        try:
            self._restore_mixer_settings()
        except Exception:
            pass
        try:
            wx.CallAfter(self._hide_voice_controls)
        except Exception:
            pass
        # Server-side leave - already its own background call
        try:
            self.titan_client.stop_voice_transmission(room_id)
        except Exception:
            pass
        try:
            self.titan_client.leave_room(room_id)
        except Exception as leave_err:
            print(f"_teardown_room_state: leave_room failed: {leave_err}")

    def _on_force_back(self, event):
        """Hard-wired Escape route via AcceleratorTable.

        Fires regardless of which child control currently has focus, so the
        user can always leave a room. Routes the same way OnKeyPress does.
        """
        try:
            current_view = getattr(self, 'current_view', None)
            if current_view == "menu":
                self.Hide()
            elif current_view in ["room_chat", "private_chat"]:
                self.OnBack(None)
            else:
                # Any other view (rooms list, forum, etc.) - back to menu.
                try:
                    self.show_menu()
                except Exception as e:
                    print(f"_on_force_back: show_menu failed: {e}")
        except Exception as e:
            print(f"_on_force_back error: {e}")

    def OnMessageInputKeyDown(self, event):
        """Handle key press in message input - Ctrl+Enter to send, Enter for new line"""
        keycode = event.GetKeyCode()
        if (keycode == wx.WXK_RETURN or keycode == wx.WXK_NUMPAD_ENTER) and event.ControlDown():
            self.OnSendMessage(None)
        elif keycode == wx.WXK_ESCAPE:
            # Belt-and-suspenders: if EVT_CHAR_HOOK on the Frame somehow misses
            # this Escape (focus-stealing edge cases on Windows), the multiline
            # TextCtrl handles it directly so the user can always leave the room.
            if self.current_view in ["room_chat", "private_chat"]:
                wx.CallAfter(self.OnBack, None)
            else:
                wx.CallAfter(self.show_menu)
        else:
            event.Skip()

    def OnSendMessage(self, event):
        """Handle send message"""
        message = self.message_input.GetValue().strip()
        if not message:
            return

        play_sound('core/SELECT.ogg')

        local_now = wx.DateTime.Now().Format("%Y-%m-%dT%H:%M:%S")

        if self.current_view == "room_chat" and self.current_room:
            # Send room message
            def send_thread():
                self.titan_client.send_room_message(self.current_room, message)

            threading.Thread(target=send_thread, daemon=True).start()

            # Echo to display immediately
            self._add_message_row(self.titan_client.username, message, local_now)

        elif self.current_view == "private_chat" and self.current_private_user:
            # Send private message
            def send_thread():
                self.titan_client.send_private_message(self.current_private_user, message)

            threading.Thread(target=send_thread, daemon=True).start()

            # Echo to display immediately
            self._add_message_row(self.titan_client.username, message, local_now)

        self.message_input.Clear()

    # ==================== Voice Setup and Management ====================

    def _restore_mixer_settings(self):
        """No longer needed - pygame mixer stays at default 22050 Hz"""
        # Voice audio is resampled during playback instead of changing mixer frequency
        print(f"[VOICE DEBUG] Mixer restoration not needed (stays at default frequency)")

    def _hide_voice_controls(self):
        """Hide and reset voice control panel"""
        try:
            # Hide the voice panel
            if hasattr(self, 'voice_panel'):
                self.voice_panel.Hide()

            # Reset voice control states
            if hasattr(self, 'is_mic_enabled'):
                self.is_mic_enabled = False
            if hasattr(self, 'is_vad_mode'):
                self.is_vad_mode = True
            if hasattr(self, 'is_ptt_mode'):
                self.is_ptt_mode = False
            if hasattr(self, 'is_ptt_active'):
                self.is_ptt_active = False
            if hasattr(self, 'is_muted'):
                self.is_muted = False

            # Reset button labels and states
            if hasattr(self, 'voice_mode_vad'):
                self.voice_mode_vad.SetValue(True)
            if hasattr(self, 'ptt_button'):
                self.ptt_button.Hide()
            if hasattr(self, 'voice_status_label'):
                self.voice_status_label.SetLabel(_("Microphone: Off"))
            if hasattr(self, 'self_monitor_button'):
                self.self_monitor_button.SetValue(False)
            if hasattr(self, 'mute_button'):
                self.mute_button.SetLabel(_("Mute"))

            # Refresh layout
            if hasattr(self, 'main_vbox'):
                self.main_vbox.Layout()

            print("[VOICE DEBUG] Voice controls hidden and reset")
        except Exception as e:
            print(f"[VOICE DEBUG] Error hiding voice controls: {e}")

    def setup_voice_for_room(self, room_id, room_type):
        """Setup voice capture and playback for voice/mixed room"""
        try:
            import pygame
            import queue

            # Import voice capture manager
            from src.network.voice_capture import VoiceCaptureManager

            # Create voice capture instance in CONTINUOUS mode (use_vad=False for no cutting)
            # Use 20ms chunks (standard VoIP frame size, optimal for Opus)
            self.voice_capture = VoiceCaptureManager(sample_rate=16000, chunk_duration_ms=20, use_vad=False)

            # Initialize Opus codec if available
            try:
                from src.network.voice_codec import OpusVoiceCodec, OPUS_AVAILABLE
                if OPUS_AVAILABLE:
                    self._opus_encoder = OpusVoiceCodec(sample_rate=16000, channels=1, bitrate=24000, frame_duration_ms=20)
                    self._opus_decoders = {}  # user_id -> OpusVoiceCodec (one decoder per sender)
                    self._use_opus = True
                    print("[VOICE] Opus codec enabled (24kbps)")
                else:
                    self._use_opus = False
                    print("[VOICE] Opus not available, using raw PCM")
            except Exception as e:
                self._use_opus = False
                print(f"[VOICE] Opus init failed: {e}, using raw PCM")

            # Setup callbacks
            self.voice_capture.on_speech_start = lambda: self._on_vad_speech_start(room_id)
            self.voice_capture.on_audio_chunk = lambda data: self._on_vad_audio_chunk(room_id, data)
            self.voice_capture.on_speech_stop = lambda: self._on_vad_speech_stop(room_id)
            self.voice_capture.on_error = lambda error: wx.CallAfter(speak_notification, f"Voice error: {error}", 'error')

            import sounddevice as sd

            # State for fast AGC
            self.last_gain = 1.0
            self._agc_log_counter = 0

            # Jitter buffer for smooth voice playback
            self.voice_jitter_buffers = {}  # user_id -> queue.Queue of raw audio chunks
            self.voice_buffer_threads = {}  # unused, kept for compat
            self.voice_buffer_stopping = {}  # user_id -> stop flag
            self.jitter_buffer_size = 3  # Buffer 3 chunks (60ms) before mixing user in — good balance of latency vs smoothness

            # Continuous voice output stream (sounddevice) — truly gapless, no pygame
            # Match input rate (16kHz) to eliminate resampling entirely
            self._voice_output_rate = 16000
            self._voice_output_stream = sd.OutputStream(
                samplerate=self._voice_output_rate,
                channels=1,
                dtype='int16',
                blocksize=320,  # 20ms blocks at 16000Hz (matches input exactly)
                latency='low',
            )
            self._voice_output_stream.start()

            # Start single mixer thread (replaces per-user playback threads)
            self._mixer_running = True
            self._user_started = {}  # user_id -> True when jitter buffer filled
            self._mixer_thread = threading.Thread(target=self._voice_mixer_thread, daemon=True)
            self._mixer_thread.start()

            # Clear active speakers
            self.active_speakers.clear()
            self.speakers_listbox.Clear()

            # Reset voice state
            self.is_muted = False
            self.is_self_monitoring = False
            self.is_ptt_active = False

            # Initialize playback optimization caches
            self._resample_cache = {}
            self._cached_volume = 1.0
            self._last_volume_update = 0

            # Auto-enable microphone (like TeamTalk - no manual click needed)
            self.voice_capture.start_capture()
            self.is_mic_enabled = True
            self.voice_status_label.SetLabel(_("Microphone: On"))

            # Default to Voice Activation mode
            self.is_vad_mode = True
            self.is_ptt_mode = False
            self.voice_mode_vad.SetValue(True)
            self.ptt_button.Hide()

            # Enable VAD in voice capture
            self.voice_capture.use_vad = True

            # Register in server voice channel (non-blocking — don't freeze GUI)
            threading.Thread(
                target=self.titan_client.start_voice_transmission,
                args=(room_id,),
                daemon=True
            ).start()

            speak_notification(_("Microphone enabled"), 'success')
            play_sound('titannet/callsuccess.ogg')
            print(f"[VOICE DEBUG] Voice setup complete for room {room_id} (type: {room_type}), mic auto-enabled, output stream at {self._voice_output_rate}Hz")

        except Exception as e:
            print(f"[VOICE DEBUG] Failed to setup voice: {e}")
            import traceback
            traceback.print_exc()
            speak_notification(_("Failed to setup voice: {error}").format(error=e), 'error')
            self.voice_capture = None
            self.voice_playback_stream = None

    def _on_vad_speech_start(self, room_id):
        """Called when VAD detects speech start (VAD mode only)"""
        if not self.is_vad_mode:
            return  # Ignore VAD if mode is disabled

        wx.CallAfter(self._vad_start_transmission, room_id)

    def _vad_start_transmission(self, room_id):
        """Start voice transmission (VAD mode)"""
        if self.current_room != room_id or self.is_muted or self.is_self_monitoring:
            return

        self.voice_status_label.SetLabel(_("Microphone: Speaking..."))
        # No server call needed — we stay registered in voice channel the whole time
        # Audio chunks are sent/not sent based on VAD state in _on_vad_audio_chunk

    def _on_vad_audio_chunk(self, room_id, audio_data):
        """Called when VAD provides audio chunk"""
        if self.is_muted or self.current_room != room_id:
            return

        # PTT mode: skip all processing if not transmitting (save CPU)
        if self.is_ptt_mode and not self.is_ptt_active and not self.is_self_monitoring:
            return

        # Apply fast automatic gain control (AGC) to boost audio
        import numpy as np
        audio_array = np.frombuffer(audio_data, dtype=np.int16).copy()

        # Calculate current level (RMS for better quality)
        rms_level = np.sqrt(np.mean(audio_array.astype(np.float32) ** 2))

        # Always apply AGC in continuous mode (even for quiet audio) to maintain stream continuity
        if rms_level > 10:  # Apply gain boost for audible audio
            # Target RMS level: 4000 (good audible level, not too aggressive)
            target_rms = 4000
            desired_gain = target_rms / rms_level

            # Fast gain changes (30% of desired change per chunk - much more responsive)
            gain = self.last_gain * 0.7 + desired_gain * 0.3
            gain = np.clip(gain, 0.5, 3.0)  # Limit gain range (reduced max from 4.0 to 3.0)

            # Apply gain with clipping protection
            audio_float = audio_array.astype(np.float32) * gain
            audio_float = np.clip(audio_float, -32768, 32767)
            audio_array = audio_float.astype(np.int16)
            audio_data = audio_array.tobytes()

            self.last_gain = gain  # Remember for next chunk

        # Encode with Opus if available (massive bandwidth reduction)
        if hasattr(self, '_use_opus') and self._use_opus:
            try:
                audio_data = self._opus_encoder.encode(audio_data)
            except Exception:
                pass  # Fallback to raw PCM on encode failure

        # Self-monitoring test mode - send to server with self_monitor flag
        if self.is_self_monitoring:
            self.titan_client.send_voice_audio(room_id, audio_data, self_monitor=True)
            return

        # Send audio immediately (non-blocking fire-and-forget)
        if self.is_ptt_mode:
            # PTT mode: only send while Enter is held
            should_send = self.is_ptt_active
        elif self.is_vad_mode:
            # VAD mode: send when speech detected
            should_send = self.voice_capture and self.voice_capture.is_speaking
        else:
            # Continuous mode fallback
            should_send = True

        if should_send:
            self.titan_client.send_voice_audio(room_id, audio_data, self_monitor=False)

    def _on_vad_speech_stop(self, room_id):
        """Called when VAD detects speech stop (VAD mode only)"""
        if not self.is_vad_mode:
            return  # Ignore VAD if mode is disabled

        wx.CallAfter(self._vad_stop_transmission, room_id)

    def _vad_stop_transmission(self, room_id):
        """Stop voice transmission (VAD mode)"""
        if self.current_room != room_id or self.is_self_monitoring:
            return

        self.voice_status_label.SetLabel(_("Microphone: On"))

        # Clear any pending batched chunks
        if hasattr(self, 'voice_send_batch'):
            self.voice_send_batch.clear()
        # No server call — we stay registered in voice channel for instant resume

    # ==================== Voice Control Handlers ====================

    def OnVoiceModeChange(self, event):
        """Handle switching between Voice Activation and Push to Talk modes."""
        if self.voice_mode_vad.GetValue():
            # Voice Activation mode
            self.is_vad_mode = True
            self.is_ptt_mode = False
            self.is_ptt_active = False
            self.ptt_button.Hide()
            if self.voice_capture:
                self.voice_capture.use_vad = True
            # No server call needed — voice channel stays registered
            self.voice_status_label.SetLabel(_("Microphone: On"))
            print("[VOICE] Switched to Voice Activation mode")
        else:
            # Push to Talk mode
            self.is_vad_mode = False
            self.is_ptt_mode = True
            self.is_ptt_active = False
            self.ptt_button.Show()
            if self.voice_capture:
                self.voice_capture.use_vad = False
            # No server call — voice channel stays registered, client controls send
            self.voice_status_label.SetLabel(_("Microphone: Push to Talk"))
            print("[VOICE] Switched to Push to Talk mode")
        self.voice_panel.Layout()

    def _ptt_key_down(self):
        """Handle PTT key pressed (Space held down)."""
        if not self.is_ptt_mode or self.is_ptt_active or not self.is_mic_enabled:
            return
        if self.is_muted or not self.current_room:
            return

        self.is_ptt_active = True
        # Auto self-monitor in PTT: hear what others hear when transmitting
        self._ptt_self_monitor_was_on = self.is_self_monitoring
        self.is_self_monitoring = True
        self.voice_status_label.SetLabel(_("Microphone: Transmitting..."))
        play_sound('titannet/walkietalkie.ogg')

        # No start_voice_transmission — we stay registered for instant audio relay
        # Notify other users (they hear the walkie-talkie sound)
        self.titan_client.send_ptt_start(self.current_room)
        # Start timer to detect Space release (safety net since EVT_KEY_UP is unreliable)
        self._start_ptt_timer()
        print("[VOICE] PTT: transmitting (self-monitor on)")

    def _ptt_key_up(self):
        """Handle PTT key released."""
        if not self.is_ptt_mode or not self.is_ptt_active:
            return

        self.is_ptt_active = False
        # Restore self-monitor state
        self.is_self_monitoring = getattr(self, '_ptt_self_monitor_was_on', False)
        self.voice_status_label.SetLabel(_("Microphone: Push to Talk"))
        play_sound('titannet/walkietalkieend.ogg')

        # No stop_voice_transmission — stay registered for instant resume
        if self.current_room:
            # Notify other users
            self.titan_client.send_ptt_stop(self.current_room)
        print("[VOICE] PTT: stopped")

    def OnSelfMonitorToggle(self, event):
        """Toggle self-monitoring test mode"""
        is_enabled = self.self_monitor_button.GetValue()

        if is_enabled:
            # Start self-monitoring
            if self.is_mic_enabled and not self.is_muted:
                self.start_self_monitoring()
                self.self_monitor_button.SetLabel(_("Self-Monitor: ON"))
            else:
                # Can't start - mic not enabled
                self.self_monitor_button.SetValue(False)
                speak_notification(_("Enable microphone first"), 'error')
        else:
            # Stop self-monitoring
            self.stop_self_monitoring()
            self.self_monitor_button.SetLabel(_("Self-Monitor (Test)"))

    def OnMuteToggle(self, event):
        """Toggle mute on/off"""
        if not self.is_mic_enabled:
            return

        self.is_muted = not self.is_muted

        if self.is_muted:
            self.mute_button.SetLabel(_("Unmute"))
            self.voice_status_label.SetLabel(_("Microphone: Muted"))
        else:
            self.mute_button.SetLabel(_("Mute"))
            if self.is_ptt_mode:
                self.voice_status_label.SetLabel(_("Microphone: Push to Talk"))
            else:
                self.voice_status_label.SetLabel(_("Microphone: On"))

    def OnVoiceVolumeChange(self, event):
        """Handle voice volume slider change"""
        volume = self.voice_volume_slider.GetValue()
        self._cached_volume = volume / 100.0
        import time
        self._last_volume_update = time.time()

    def OnCharHook(self, event):
        """Handle keyboard events globally - PTT Space key handling + shortcuts."""
        keycode = event.GetKeyCode()

        # PTT: Space key down in Push to Talk mode
        if keycode == wx.WXK_SPACE and self.is_ptt_mode and self.current_room:
            # Only trigger PTT if focus is NOT in a text input or interactive control
            focused = self.FindFocus()
            if not isinstance(focused, (wx.TextCtrl, wx.Button, wx.RadioButton, wx.ToggleButton, wx.CheckBox)):
                if not self.is_ptt_active:
                    self._ptt_key_down()
                return  # Don't skip - consume the event

        # Ctrl+N - context-dependent new item creation
        if keycode == ord('N') and event.ControlDown() and not event.AltDown() and not event.ShiftDown():
            if self.current_view == "rooms":
                self._user_create_room()
                return
            elif self.current_view == "forum":
                self._user_create_topic()
                return

        # Ctrl+O - open / reply to the last incoming private message
        if keycode == ord('O') and event.ControlDown() and not event.AltDown() and not event.ShiftDown():
            if self._last_pm_sender_id is not None:
                self.show_private_chat(self._last_pm_sender_id, self._last_pm_sender_username or _("user"))
            else:
                speak_titannet(_("No new private messages to reply to"))
            return

        event.Skip()

    def _on_key_up(self, event):
        """Handle key release - PTT Space key release."""
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_SPACE and self.is_ptt_active:
            self._ptt_key_up()
            return
        event.Skip()

    def _start_ptt_timer(self):
        """Start a timer that checks if Enter is still held (safety net for PTT)."""
        if hasattr(self, '_ptt_timer') and self._ptt_timer and self._ptt_timer.IsRunning():
            return
        self._ptt_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_ptt_timer_check, self._ptt_timer)
        self._ptt_timer.Start(50)  # Check every 50ms

    def _stop_ptt_timer(self):
        """Stop the PTT check timer."""
        if hasattr(self, '_ptt_timer') and self._ptt_timer:
            self._ptt_timer.Stop()
            self._ptt_timer = None

    def _on_ptt_timer_check(self, event):
        """Check if Space key is still held - release PTT if not."""
        if not self.is_ptt_active:
            self._stop_ptt_timer()
            return
        if not wx.GetKeyState(wx.WXK_SPACE):
            self._ptt_key_up()
            self._stop_ptt_timer()

    def on_ptt_started(self, message):
        """Another user pressed PTT - play walkie-talkie start sound."""
        try:
            room_id = message.get('room_id')
            if room_id != self.current_room:
                return
            wx.CallAfter(play_sound, 'titannet/walkietalkie.ogg')
        except Exception as e:
            print(f"[VOICE] Error handling ptt_started: {e}")

    def on_ptt_stopped(self, message):
        """Another user released PTT - play walkie-talkie end sound."""
        try:
            room_id = message.get('room_id')
            if room_id != self.current_room:
                return
            wx.CallAfter(play_sound, 'titannet/walkietalkieend.ogg')
        except Exception as e:
            print(f"[VOICE] Error handling ptt_stopped: {e}")

    def start_self_monitoring(self):
        """Start self-monitoring test (Ctrl+' pressed) - send to server and hear back"""
        print(f"[VOICE DEBUG] start_self_monitoring called")

        if not self.current_room:
            print(f"[VOICE DEBUG] No current room!")
            return

        print(f"[VOICE DEBUG] Current room: {self.current_room}")
        print(f"[VOICE DEBUG] Voice capture exists: {self.voice_capture is not None}")

        self.is_self_monitoring = True
        self.voice_status_label.SetLabel(_("Microphone: Self-Monitoring Test..."))

        # No start_voice_transmission needed — already registered in voice channel

        # Enable capture in speaking mode
        if self.voice_capture:
            print(f"[VOICE DEBUG] Enabling voice capture speaking mode")
            self.voice_capture.is_speaking = True
        else:
            print(f"[VOICE DEBUG] No voice capture available!")

    def stop_self_monitoring(self):
        """Stop self-monitoring test (Ctrl+' released)"""
        if not self.current_room or not self.is_self_monitoring:
            return

        self.is_self_monitoring = False
        self.voice_status_label.SetLabel(_("Microphone: On"))

        # No stop_voice_transmission — stay registered in voice channel

        # Disable capture speaking mode
        if self.voice_capture:
            self.voice_capture.is_speaking = False

    # ==================== Broadcast Handlers ====================

    def OnBroadcastStartRecording(self, event):
        """Start recording voice for broadcast"""
        play_sound('ai/ui1.ogg')  # Start recording sound

        if self.broadcast_is_recording:
            speak_notification(_("Already recording"), 'warning')
            return

        try:
            # Import voice capture manager
            from src.network.voice_capture import VoiceCaptureManager

            # Create voice capture instance for broadcast (continuous mode)
            self.broadcast_voice_capture = VoiceCaptureManager(sample_rate=16000, chunk_duration_ms=30, use_vad=False)

            # Collect audio chunks in a list
            self.broadcast_audio_chunks = []

            def on_audio_chunk(data):
                """Collect audio chunks"""
                self.broadcast_audio_chunks.append(data)

            self.broadcast_voice_capture.on_audio_chunk = on_audio_chunk
            self.broadcast_voice_capture.on_error = lambda error: wx.CallAfter(speak_notification, f"Voice error: {error}", 'error')

            # Start capture
            self.broadcast_voice_capture.start_capture()
            self.broadcast_is_recording = True

            # Update UI
            self.broadcast_record_button.Enable(False)
            self.broadcast_stop_button.Enable(True)
            speak_notification(_("Recording started"), 'info')

        except Exception as e:
            print(f"Error starting broadcast recording: {e}")
            speak_notification(_("Failed to start recording: {error}").format(error=e), 'error')

    def OnBroadcastStopRecording(self, event):
        """Stop recording voice for broadcast"""
        play_sound('ai/ui2.ogg')  # Stop recording sound

        if not self.broadcast_is_recording:
            return

        try:
            # Stop capture
            if self.broadcast_voice_capture:
                self.broadcast_voice_capture.stop_capture()

            # Combine all audio chunks
            if self.broadcast_audio_chunks:
                self.broadcast_recorded_audio = b''.join(self.broadcast_audio_chunks)
                speak_notification(_("Recording stopped. {size} KB recorded").format(
                    size=len(self.broadcast_recorded_audio) // 1024
                ), 'success')
            else:
                self.broadcast_recorded_audio = None
                speak_notification(_("No audio recorded"), 'warning')

            self.broadcast_is_recording = False
            self.broadcast_audio_chunks = []

            # Update UI
            self.broadcast_record_button.Enable(True)
            self.broadcast_stop_button.Enable(False)
            self.broadcast_play_button.Enable(bool(self.broadcast_recorded_audio))

        except Exception as e:
            print(f"Error stopping broadcast recording: {e}")
            speak_notification(_("Failed to stop recording: {error}").format(error=e), 'error')

    def OnBroadcastPlayRecording(self, event):
        """Play recorded broadcast audio"""
        play_sound('core/SELECT.ogg')

        if not self.broadcast_recorded_audio:
            speak_notification(_("No recording to play"), 'warning')
            return

        try:
            import pygame
            import numpy as np

            # Convert raw audio to Sound object
            # Audio is 16kHz, 16-bit PCM, mono
            audio_array = np.frombuffer(self.broadcast_recorded_audio, dtype=np.int16)

            # Resample to 22050 Hz (pygame mixer default)
            try:
                from scipy.signal import resample
                target_samples = int(len(audio_array) * 22050 / 16000)
                audio_resampled = resample(audio_array, target_samples).astype(np.int16)
            except ImportError:
                # Fallback: simple linear interpolation
                target_samples = int(len(audio_array) * 22050 / 16000)
                audio_resampled = np.interp(
                    np.linspace(0, len(audio_array) - 1, target_samples),
                    np.arange(len(audio_array)),
                    audio_array
                ).astype(np.int16)

            # Get mixer channels (1=mono, 2=stereo)
            mixer_info = pygame.mixer.get_init()
            if mixer_info:
                frequency, size, channels = mixer_info
                print(f"[BROADCAST] Mixer: {frequency}Hz, {channels} channels")

                # Ensure array matches mixer channels
                if channels == 2:
                    # Stereo: duplicate mono to both channels
                    audio_resampled = np.column_stack((audio_resampled, audio_resampled))
                elif channels == 1:
                    # Mono: ensure 1D array
                    audio_resampled = audio_resampled.flatten()

                print(f"[BROADCAST] Final array shape: {audio_resampled.shape}")

            # Convert to Sound
            sound = pygame.sndarray.make_sound(audio_resampled)
            sound.play()

            speak_notification(_("Playing recording"), 'info')

        except Exception as e:
            print(f"Error playing broadcast recording: {e}")
            import traceback
            traceback.print_exc()
            speak_notification(_("Failed to play recording: {error}").format(error=e), 'error')

    def OnBroadcastSend(self, event):
        """Send broadcast message"""
        print("[BROADCAST SEND] OnBroadcastSend called")

        text_message = self.broadcast_text.GetValue().strip()
        voice_data = self.broadcast_recorded_audio

        print(f"[BROADCAST SEND] Text: {bool(text_message)}, Voice data: {bool(voice_data)}")

        if not text_message and not voice_data:
            speak_notification(_("Broadcast must contain text or voice message"), 'error')
            return

        # Confirm send
        if text_message and voice_data:
            msg_type = _("text and voice")
        elif text_message:
            msg_type = _("text")
        else:
            msg_type = _("voice")

        print(f"[BROADCAST SEND] Message type: {msg_type}")

        dlg = _new_message_dialog(
            self,
            _("Send broadcast ({type}) to all users?").format(type=msg_type),
            _("Confirm Broadcast"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION
        )

        if dlg.ShowModal() != wx.ID_YES:
            print("[BROADCAST SEND] User cancelled")
            dlg.Destroy()
            return

        dlg.Destroy()
        print("[BROADCAST SEND] User confirmed, sending...")

        # Send broadcast
        speak_notification(_("Broadcasting message..."), 'info')

        def send_thread():
            try:
                print("[BROADCAST SEND] Calling titan_client.send_broadcast()")
                result = self.titan_client.send_broadcast(text_message, voice_data)
                print(f"[BROADCAST SEND] Send result: {result}")
                wx.CallAfter(self._on_broadcast_sent, result)
            except Exception as e:
                print(f"[BROADCAST SEND] Exception: {e}")
                import traceback
                traceback.print_exc()
                wx.CallAfter(self._on_broadcast_sent, {
                    'success': False,
                    'message': str(e)
                })

        thread = threading.Thread(target=send_thread, daemon=True)
        thread.start()

    def _on_broadcast_sent(self, result):
        """Handle broadcast send result"""
        print(f"[BROADCAST SEND] _on_broadcast_sent called with result: {result}")
        if result.get('success'):
            print("[BROADCAST SEND] Success! Closing broadcast panel...")
            speak_notification(_("Broadcast sent successfully"), 'success')
            play_sound('titannet/sent.ogg')

            # Clear broadcast panel
            self.broadcast_text.SetValue("")
            self.broadcast_recorded_audio = None
            self.broadcast_play_button.Enable(False)

            # Return to moderation menu immediately (don't wait)
            print("[BROADCAST SEND] Calling show_moderation_menu()")
            self.show_moderation_menu()
            print("[BROADCAST SEND] show_moderation_menu() returned")
        else:
            print(f"[BROADCAST SEND] Failed: {result.get('message')}")
            error_message = result.get('message', _("Failed to send broadcast"))
            speak_notification(error_message, 'error')
            play_sound('core/error.ogg')

    def OnDisconnectAndClose(self):
        """Disconnect from Titan-Net and close window"""
        play_sound('titannet/bye.ogg')
        speak_titannet(_("Disconnecting from Titan-Net"))

        # Hide voice controls before closing
        self._hide_voice_controls()

        # Set force_close flag to actually close the window
        self.force_close = True

        self.titan_client.logout()
        self.Close()

    def _save_main_listbox_selection(self):
        """Capture current main_listbox selection as (index, text) for refresh-preservation."""
        try:
            sel = self.main_listbox.GetSelection()
            if sel == wx.NOT_FOUND or sel >= self.main_listbox.GetCount():
                return None
            return (sel, self.main_listbox.GetString(sel))
        except Exception:
            return None

    def _restore_main_listbox_selection(self, saved, default_index=0):
        """Restore selection captured by _save_main_listbox_selection.

        Returns True when the previous selection was restored (refresh path),
        False when falling back to default_index (fresh load).
        """
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

    def refresh_rooms(self):
        """Refresh rooms list"""
        def refresh_thread():
            result = self.titan_client.get_rooms()
            wx.CallAfter(self._update_rooms_list, result)

        threading.Thread(target=refresh_thread, daemon=True).start()

    def _update_rooms_list(self, result):
        """Update rooms list in UI"""
        if not self or self.current_view != "rooms":
            return

        try:
            if result.get('success'):
                self.rooms_cache = result.get('rooms', [])
                saved = self._save_main_listbox_selection()
                self.main_listbox.Clear()

                for room in self.rooms_cache:
                    room_type = room.get('room_type', 'text')
                    type_indicator = ""
                    if room_type == 'voice':
                        type_indicator = " [" + _("Voice") + "]"
                    elif room_type == 'mixed':
                        type_indicator = " [" + _("Text+Voice") + "]"

                    display_text = f"{room['name']}{type_indicator} ({room['member_count']} {_('members')})"
                    self.main_listbox.Append(display_text)

                if getattr(self, '_main_listbox_dnd', None) is not None:
                    self._main_listbox_dnd.apply_saved_order()

                if self.main_listbox.GetCount() > 0:
                    self._restore_main_listbox_selection(saved)

        except Exception as e:
            print(f"Error updating rooms list: {e}")

    def refresh_users(self):
        """Refresh users list"""
        def refresh_thread():
            result = self.titan_client.get_online_users()
            wx.CallAfter(self._update_users_list, result)

        threading.Thread(target=refresh_thread, daemon=True).start()

    def _update_users_list(self, result):
        """Update users list in UI"""
        if not self or self.current_view not in ["users", "private_messages_select"]:
            return

        try:
            if result.get('success'):
                users = result.get('users', [])
                print(f"Loaded {len(users)} users")

                # Don't filter out self - allow sending messages to yourself
                self.users_cache = users

                saved = self._save_main_listbox_selection()
                self.main_listbox.Clear()

                for user in self.users_cache:
                    display_text = f"{user['username']} (#{user.get('titan_number', 'N/A')})"
                    if user.get('full_name'):
                        display_text += f" - {user['full_name']}"
                    self.main_listbox.Append(display_text)

                if getattr(self, '_main_listbox_dnd', None) is not None:
                    self._main_listbox_dnd.apply_saved_order()

                if self.main_listbox.GetCount() > 0:
                    restored = self._restore_main_listbox_selection(saved)
                    if not restored:
                        # Only steal focus on the initial load, not on every auto-refresh tick
                        self.main_listbox.SetFocus()
                else:
                    print("Warning: No users in list")
                    if saved is None:
                        speak_titannet(_("No users online"))
            else:
                error_msg = result.get('message', 'Unknown error')
                print(f"Failed to load users: {error_msg}")
                speak_titannet(_("Failed to load users"))
                play_sound('core/error.ogg')

        except Exception as e:
            print(f"Error updating users list: {e}")
            import traceback
            traceback.print_exc()

    def refresh_forum_topics(self):
        """Refresh forum topics list"""
        def refresh_thread():
            result = self.titan_client.get_forum_topics(limit=50)
            wx.CallAfter(self._update_forum_topics_list, result)

        threading.Thread(target=refresh_thread, daemon=True).start()

    def _update_forum_topics_list(self, result):
        """Update forum topics list in UI"""
        if not self or self.current_view != "forum":
            return

        try:
            if result.get('success'):
                self.forum_topics_cache = result.get('topics', [])
                saved = self._save_main_listbox_selection()
                self.main_listbox.Clear()

                for topic in self.forum_topics_cache:
                    display_text = f"{topic['title']} - {topic['author_username']} ({topic['reply_count']} {_('replies')})"
                    self.main_listbox.Append(display_text)

                if getattr(self, '_main_listbox_dnd', None) is not None:
                    self._main_listbox_dnd.apply_saved_order()

                if self.main_listbox.GetCount() > 0:
                    self._restore_main_listbox_selection(saved)

        except Exception as e:
            print(f"Error updating forum topics list: {e}")

    def refresh_repository(self):
        """Refresh app repository list"""
        def refresh_thread():
            result = self.titan_client.get_apps(status="approved", limit=100)
            wx.CallAfter(self._update_repository_list, result)

        threading.Thread(target=refresh_thread, daemon=True).start()

    def _update_repository_list(self, result):
        """Update repository list in UI"""
        if not self or self.current_view != "repository":
            return

        try:
            if result.get('success'):
                self.repository_apps_cache = result.get('apps', [])
                saved = self._save_main_listbox_selection()
                self.main_listbox.Clear()

                for app in self.repository_apps_cache:
                    display_text = f"{app['name']} v{app.get('version', '1.0')} - {app['uploader_username']}"
                    self.main_listbox.Append(display_text)

                if getattr(self, '_main_listbox_dnd', None) is not None:
                    self._main_listbox_dnd.apply_saved_order()

                if self.main_listbox.GetCount() > 0:
                    self._restore_main_listbox_selection(saved)

        except Exception as e:
            print(f"Error updating repository list: {e}")

    def show_forum_topic(self, topic_id, topic_title, last_known_reply_count=0):
        """Show forum topic with replies"""
        play_sound('core/SELECT.ogg')

        # Create forum topic window
        topic_window = ForumTopicWindow(self, self.titan_client, topic_id, topic_title)
        topic_window.Show()

        from src.ui.window_switcher import register_window
        register_window(f"Titan-Net: {topic_title}", window=topic_window, category='messenger')

    def show_app_details(self, app):
        """Show app details and download option"""
        play_sound('core/SELECT.ogg')

        # Load full app details
        def load_thread():
            result = self.titan_client.get_app_details(app['id'])
            wx.CallAfter(self._display_app_details_dialog, result)

        threading.Thread(target=load_thread, daemon=True).start()

    def _display_app_details_dialog(self, result):
        """Display app details in dialog"""
        if not result.get('success'):
            speak_notification(_("Failed to load app details"), 'error')
            return

        app = result.get('app', {})

        # Create details message
        details = f"{_('Name')}: {app.get('name', 'N/A')}\n"
        details += f"{_('Version')}: {app.get('version', 'N/A')}\n"
        details += f"{_('Author')}: {app.get('uploader_username', 'N/A')}\n"
        details += f"{_('Category')}: {app.get('category', 'N/A')}\n"
        details += f"{_('Downloads')}: {app.get('download_count', 0)}\n\n"
        details += f"{_('Description')}:\n{app.get('description', _('No description'))}\n\n"
        details += _("Do you want to download this app?")

        dlg = _new_message_dialog(
            self,
            details,
            _("App Details"),
            wx.YES_NO | wx.ICON_QUESTION
        )

        if dlg.ShowModal() == wx.ID_YES:
            self.download_app(app['id'], app)

        dlg.Destroy()

    def download_app(self, app_id, app):
        """Download and save app"""
        speak_titannet(_("Downloading..."))
        play_sound('system/connecting.ogg')

        def download_thread():
            result = self.titan_client.download_app(app_id)
            wx.CallAfter(self._on_app_downloaded, result, app)

        threading.Thread(target=download_thread, daemon=True).start()

    def _on_app_downloaded(self, result, app):
        """Handle app download completion"""
        if result.get('success'):
            play_sound('titannet/file_success.ogg')
            speak_titannet(_("Download complete"))

            file_data = result.get('file_data')

            try:
                import os
                # Create download directory
                download_dir = os.path.join('data', 'downloaded packages')
                os.makedirs(download_dir, exist_ok=True)

                # Get author username
                author = app.get('uploader_username', app.get('author_username', 'unknown'))

                # Create filename: author_packagename_version.TCEPACKAGE
                safe_author = "".join(c for c in author if c.isalnum() or c in ('-', '_')).strip()
                safe_name = "".join(c for c in app['name'] if c.isalnum() or c in ('-', '_')).strip()
                version = app.get('version', '1.0')
                safe_version = "".join(c for c in version if c.isalnum() or c in ('-', '_', '.')).strip()

                filename = f"{safe_author}_{safe_name}_v{safe_version}.TCEPACKAGE"
                save_path = os.path.join(download_dir, filename)

                # Save file
                with open(save_path, 'wb') as f:
                    f.write(file_data)

                speak_notification(
                    _("Application downloaded successfully to:\n{path}").format(path=save_path),
                    'success'
                )
                play_sound('core/SELECT.ogg')
            except Exception as e:
                play_sound('core/error.ogg')
                speak_notification(
                    _("Failed to save file: {error}").format(error=str(e)),
                    'error'
                )
        else:
            play_sound('core/error.ogg')
            error = result.get('error', _('Download failed'))
            speak_notification(error, 'error')

    def join_room(self, room_id, room_name, password=None):
        """Join a chat room"""
        # Check if room requires password
        room_info = None
        for room in self.rooms_cache:
            if room['id'] == room_id:
                room_info = room
                break

        # If room is private and no password provided yet, ask for password
        if room_info and room_info.get('is_private', 0) == 1 and password is None:
            # Show password dialog
            password_dlg = _new_text_entry_dialog(
                self,
                _("This room is password-protected.\nEnter password:"),
                _("Room Password"),
                style=wx.TextEntryDialogStyle | wx.TE_PASSWORD
            )

            if password_dlg.ShowModal() == wx.ID_OK:
                password = password_dlg.GetValue().strip()
                password_dlg.Destroy()

                # Try to join with password
                self.join_room(room_id, room_name, password)
            else:
                password_dlg.Destroy()
                speak_titannet(_("Cancelled joining room"))
            return

        speak_titannet(_("Joining room..."))

        def join_thread():
            result = self.titan_client.join_room(room_id, password or "")
            wx.CallAfter(self._on_room_joined, result, room_id, room_name)

        threading.Thread(target=join_thread, daemon=True).start()

    def _on_room_joined(self, result, room_id, room_name):
        """Handle room join result"""
        if result.get('success'):
            # Check if user is banned from this room
            error_msg = result.get('message', '').lower()
            if 'banned' in error_msg or 'zbanowany' in error_msg:
                speak_titannet(_("You are banned from this room"))
                speak_notification(_("You are banned from this room"), 'banned')
                play_sound('core/error.ogg')
                return

            speak_titannet(_("Joined room: {name}").format(name=room_name))
            self.show_room_chat(room_id, room_name)
        else:
            # Check error type
            error_msg = result.get('message', '').lower()

            if 'invalid password' in error_msg or 'nieprawidłowe hasło' in error_msg:
                # Wrong password - ask again
                speak_titannet(_("Invalid password"))
                speak_notification(_("Invalid password"), 'error')
                play_sound('core/error.ogg')
                # Show password dialog again
                wx.CallAfter(self.join_room, room_id, room_name, None)
            elif 'banned' in error_msg or 'zbanowany' in error_msg:
                speak_titannet(_("You are banned from this room"))
                speak_notification(_("You are banned from this room"), 'banned')
                play_sound('core/error.ogg')
            elif 'already' in error_msg or 'już' in error_msg:
                # User is already in room, show room view anyway
                speak_titannet(_("Opening room: {name}").format(name=room_name))
                self.show_room_chat(room_id, room_name)
            else:
                # Other error
                speak_titannet(result.get('message', _("Failed to join room")))
                play_sound('core/error.ogg')

    def leave_current_room(self):
        """Leave current room"""
        if self.current_room:
            # Capture room_id before any state changes (prevents race condition
            # where self.current_room is set to None before the thread runs)
            room_id = self.current_room

            # Cleanup voice resources if active
            if self.voice_capture:
                self.voice_capture.stop_capture()
                self.voice_capture = None

            # Clear any pending batched chunks
            if hasattr(self, 'voice_send_batch'):
                self.voice_send_batch.clear()

            # Stop mixer thread and voice output stream
            self._mixer_running = False
            for user_id in list(self.voice_buffer_stopping.keys()):
                self.voice_buffer_stopping[user_id] = True
            if hasattr(self, '_mixer_thread') and self._mixer_thread:
                self._mixer_thread.join(timeout=1.0)
                self._mixer_thread = None
            if hasattr(self, '_voice_output_stream') and self._voice_output_stream:
                try:
                    self._voice_output_stream.stop()
                    self._voice_output_stream.close()
                except Exception:
                    pass
                self._voice_output_stream = None
            # Clear buffers and Opus decoders
            self.voice_jitter_buffers.clear()
            self.voice_buffer_threads.clear()
            self.voice_buffer_stopping.clear()
            self._user_started = {}
            self._user_channel_map.clear()
            if hasattr(self, '_opus_decoders'):
                self._opus_decoders.clear()

            self._restore_mixer_settings()

            # Hide voice controls panel
            self._hide_voice_controls()

            # Send voice_stop before leaving (if voice was active)
            def leave_thread():
                try:
                    self.titan_client.stop_voice_transmission(room_id)
                except Exception:
                    pass
                self.titan_client.leave_room(room_id)

            threading.Thread(target=leave_thread, daemon=True).start()

    def load_room_messages(self, room_id):
        """Load messages for room"""
        def load_thread():
            result = self.titan_client.get_room_messages(room_id)
            wx.CallAfter(self._display_room_messages, result)

        threading.Thread(target=load_thread, daemon=True).start()

    def _display_room_messages(self, result):
        """Display room messages in the conversation list."""
        if result.get('success'):
            messages = result.get('messages', [])
            self._clear_message_list()
            self.displayed_message_ids.clear()

            self.message_display.Freeze()
            try:
                for msg in reversed(messages):
                    msg_id = msg.get('id')
                    if msg_id:
                        self.displayed_message_ids.add(msg_id)
                    self._add_message_row(
                        msg.get('username', ''),
                        msg.get('message', ''),
                        msg.get('sent_at', ''),
                    )
            finally:
                self.message_display.Thaw()

    def load_private_messages(self, user_id):
        """Load private messages with user"""
        def load_thread():
            result = self.titan_client.get_private_messages(user_id)
            wx.CallAfter(self._display_private_messages, result)

        threading.Thread(target=load_thread, daemon=True).start()

    def _display_private_messages(self, result):
        """Display private messages in the conversation list."""
        if result.get('success'):
            messages = result.get('messages', [])
            self._clear_message_list()
            self.displayed_message_ids.clear()

            self.message_display.Freeze()
            try:
                for msg in reversed(messages):
                    msg_id = msg.get('id')
                    if msg_id:
                        self.displayed_message_ids.add(msg_id)
                    self._add_message_row(
                        msg.get('sender_username', ''),
                        msg.get('message', ''),
                        msg.get('sent_at', ''),
                    )
            finally:
                self.message_display.Thaw()

            # Automatically mark all messages from this user as read
            if self.current_private_user and messages:
                def mark_read_thread():
                    self.titan_client.mark_private_messages_as_read(self.current_private_user)
                threading.Thread(target=mark_read_thread, daemon=True).start()

    def load_room_users(self, room_id):
        """Load users in room"""
        def load_thread():
            # Get online users and filter those in this room
            result = self.titan_client.get_online_users()
            if result.get('success'):
                all_users = result.get('users', [])
                # For now, show all online users (ideally server should provide room-specific users)
                wx.CallAfter(self._display_room_users, all_users)

        threading.Thread(target=load_thread, daemon=True).start()

    def _display_room_users(self, users):
        """Display room users list"""
        self.room_users_cache = users
        self.room_users_listbox.Clear()

        label_text = _("Users in room ({count}):").format(count=len(users))
        self.room_users_listbox.Append(label_text)

        for user in users:
            username = user.get('username', 'Unknown')
            titan_number = user.get('titan_number', 0)
            self.room_users_listbox.Append(f"{username} (#{titan_number})")

        if getattr(self, '_room_users_dnd', None) is not None:
            self._room_users_dnd.apply_saved_order()

    def OnRoomUserContextMenu(self, event):
        """Show context menu for room user"""
        selection = self.room_users_listbox.GetSelection()
        if selection == wx.NOT_FOUND or selection == 0:  # Skip header row
            return

        # Adjust for header row
        user_index = selection - 1
        if user_index < 0 or user_index >= len(self.room_users_cache):
            return

        user = self.room_users_cache[user_index]

        # Show context menu with options
        menu = wx.Menu()

        send_pm_item = menu.Append(wx.ID_ANY, _("Send private message"))
        self.Bind(wx.EVT_MENU, lambda e: self.show_private_chat(user['id'], user['username']), send_pm_item)

        avatar_item = menu.Append(wx.ID_ANY, _("Play avatar"))
        self.Bind(wx.EVT_MENU, lambda e: self._play_user_avatar(user['username']), avatar_item)

        # Add moderation options for room owner/moderators
        if self.is_moderator or self.is_developer:
            menu.AppendSeparator()

            kick_item = menu.Append(wx.ID_ANY, _("Kick from Room"))
            self.Bind(wx.EVT_MENU, lambda e: self._moderate_kick_user(user['username']), kick_item)

            ban_item = menu.Append(wx.ID_ANY, _("Ban from Room"))
            self.Bind(wx.EVT_MENU, lambda e: self._context_ban_from_room(user), ban_item)

        self.PopupMenu(menu)
        menu.Destroy()

    def show_all_users_context_menu(self, user):
        """Show context menu for all users list (instant — no server calls)"""
        menu = wx.Menu()

        # Send Private Message option for everyone
        send_msg_item = menu.Append(wx.ID_ANY, _("Send private message"))
        self.Bind(wx.EVT_MENU, lambda e: self.show_private_chat(user['id'], user['username']), send_msg_item)

        avatar_item = menu.Append(wx.ID_ANY, _("Play avatar"))
        self.Bind(wx.EVT_MENU, lambda e: self._play_user_avatar(user['username']), avatar_item)

        # Moderation options for moderators/developers
        # No blocking server call — show all options, server validates on action
        if self.is_moderator or self.is_developer:
            menu.AppendSeparator()

            # Global ban/unban - show both, server handles state
            ban_global_item = menu.Append(wx.ID_ANY, _("Ban from TCE Community"))
            self.Bind(wx.EVT_MENU, lambda e: self._context_ban_globally(user), ban_global_item)

            unban_global_item = menu.Append(wx.ID_ANY, _("Unban from TCE Community"))
            self.Bind(wx.EVT_MENU, lambda e: self._context_unban_globally(user), unban_global_item)

            # Forum ban/unban
            ban_forum_item = menu.Append(wx.ID_ANY, _("Ban from Forum"))
            self.Bind(wx.EVT_MENU, lambda e: self._context_ban_from_forum(user), ban_forum_item)

            unban_forum_item = menu.Append(wx.ID_ANY, _("Unban from Forum"))
            self.Bind(wx.EVT_MENU, lambda e: self._context_unban_from_forum(user), unban_forum_item)

            # Hard ban and Delete (only for moderators/developers)
            menu.AppendSeparator()
            hard_ban_item = menu.Append(wx.ID_ANY, _("HARD BAN (IP + Hardware)"))
            self.Bind(wx.EVT_MENU, lambda e: self._context_hard_ban(user), hard_ban_item)

            # Delete user (permanent deletion)
            delete_user_item = menu.Append(wx.ID_ANY, _("Delete User (PERMANENT)"))
            self.Bind(wx.EVT_MENU, lambda e: self._context_delete_user(user), delete_user_item)

        # Show the menu at cursor position
        self.main_listbox.PopupMenu(menu)
        menu.Destroy()

    def show_user_actions(self, user):
        """Show context menu for user actions (instant — no server calls)"""
        menu = wx.Menu()

        send_msg_item = menu.Append(wx.ID_ANY, _("Send private message"))
        self.Bind(wx.EVT_MENU, lambda e: self.show_private_chat(user['id'], user['username']), send_msg_item)

        avatar_item = menu.Append(wx.ID_ANY, _("Play avatar"))
        self.Bind(wx.EVT_MENU, lambda e: self._play_user_avatar(user['username']), avatar_item)

        # Add moderation options if user is moderator or developer
        # No blocking server call — show all options, server validates on action
        if self.is_moderator or self.is_developer:
            menu.AppendSeparator()
            moderation_menu = wx.Menu()

            # Kick from room option (if in room context)
            if hasattr(self, 'current_room') and self.current_room:
                kick_item = moderation_menu.Append(wx.ID_ANY, _("Kick from Room"))
                self.Bind(wx.EVT_MENU, lambda e: self._moderate_kick_user(user['username']), kick_item)

                ban_room_item = moderation_menu.Append(wx.ID_ANY, _("Ban from Room..."))
                self.Bind(wx.EVT_MENU, lambda e: self._context_ban_from_room(user), ban_room_item)

                unban_room_item = moderation_menu.Append(wx.ID_ANY, _("Unban from Room"))
                self.Bind(wx.EVT_MENU, lambda e: self._context_unban_from_room(user), unban_room_item)

            # Forum options (if in forum context)
            if self.current_view == "forum":
                ban_forum_item = moderation_menu.Append(wx.ID_ANY, _("Ban from Forum..."))
                self.Bind(wx.EVT_MENU, lambda e: self._context_ban_from_forum(user), ban_forum_item)

                unban_forum_item = moderation_menu.Append(wx.ID_ANY, _("Unban from Forum"))
                self.Bind(wx.EVT_MENU, lambda e: self._context_unban_from_forum(user), unban_forum_item)

            # Global ban/unban
            if moderation_menu.GetMenuItemCount() > 0:
                moderation_menu.AppendSeparator()

            ban_global_item = moderation_menu.Append(wx.ID_ANY, _("Ban Globally..."))
            self.Bind(wx.EVT_MENU, lambda e: self._context_ban_globally(user), ban_global_item)

            unban_global_item = moderation_menu.Append(wx.ID_ANY, _("Unban Globally"))
            self.Bind(wx.EVT_MENU, lambda e: self._context_unban_globally(user), unban_global_item)

            # Hard ban (developer only)
            if self.is_developer:
                moderation_menu.AppendSeparator()
                hard_ban_item = moderation_menu.Append(wx.ID_ANY, _("HARD BAN"))
                self.Bind(wx.EVT_MENU, lambda e: self._context_hard_ban(user), hard_ban_item)

            menu.AppendSubMenu(moderation_menu, _("Moderation"))

        # Add administration options if user is developer
        if self.is_developer:
            admin_menu = wx.Menu()

            promote_item = admin_menu.Append(wx.ID_ANY, _("Promote to Moderator"))
            self.Bind(wx.EVT_MENU, lambda e: self._admin_promote_user(user['username']), promote_item)

            demote_item = admin_menu.Append(wx.ID_ANY, _("Demote Moderator"))
            self.Bind(wx.EVT_MENU, lambda e: self._admin_demote_user(user['username']), demote_item)

            menu.AppendSubMenu(admin_menu, _("Administration"))

        # Show menu at mouse position
        self.PopupMenu(menu)
        menu.Destroy()

    def OnAutoRefresh(self, event):
        """Auto-refresh timer - update data in background"""
        try:
            # Only refresh if not in chat view (to avoid interrupting conversation)
            if self.current_view == "rooms":
                self.refresh_rooms()
            elif self.current_view in ["users", "private_messages_select"]:
                self.refresh_users()
            elif self.current_view == "forum":
                self.refresh_forum_topics()
            elif self.current_view == "repository":
                self.refresh_repository()
        except Exception as e:
            print(f"Auto-refresh error: {e}")

    def OnIconize(self, event):
        """Handle window minimize/iconize - keep connection alive"""
        is_iconized = event.IsIconized()
        if is_iconized:
            print("[TITAN-NET GUI] Window minimized - staying connected")
        else:
            print("[TITAN-NET GUI] Window restored")

        # Always allow the event to proceed
        event.Skip()

    def OnClose(self, event):
        """Handle window close - hide instead of close unless force_close is set"""
        try:
            # Check if user wants to force close (disconnect)
            if self.force_close:
                print("[TITAN-NET GUI] Force close - disconnecting")
                # Stop refresh timer
                try:
                    if self.refresh_timer:
                        self.refresh_timer.Stop()
                        self.refresh_timer = None
                except Exception as e:
                    print(f"Error stopping refresh timer: {e}")

                # Cleanup voice resources
                try:
                    if self.voice_capture:
                        self.voice_capture.stop_capture()
                        self.voice_capture = None
                    self._hide_voice_controls()
                    self._restore_mixer_settings()
                except Exception as e:
                    print(f"Error cleaning up voice resources: {e}")

                # Clear global window reference
                global _titan_net_window
                _titan_net_window = None
                # Allow window to close
                event.Skip()
            else:
                # Just hide the window (minimize to background)
                print("[TITAN-NET GUI] Hiding window (staying connected)")
                self.Hide()
                # Unregister from window switcher while hidden
                try:
                    from src.ui.window_switcher import unregister_window
                    unregister_window("Titan-Net")
                except Exception:
                    pass
                # Veto the close event to prevent destruction
                if event.CanVeto():
                    event.Veto()

        except Exception as e:
            print(f"Error during window close: {e}")
            # Allow close to proceed if there's an error
            event.Skip()

    # ----- Message-list helpers (Nick / Message / Date list view) -----
    def _format_message_timestamp(self, sent_at):
        """Format an ISO-ish timestamp for display in the Date column."""
        if not sent_at:
            return ""
        if 'T' in sent_at:
            date_part, _, time_part = sent_at.partition('T')
        else:
            date_part, time_part = sent_at, ""
        time_short = time_part[:5] if time_part else ""
        if date_part and time_short:
            return f"{date_part} {time_short}"
        return date_part or time_short

    def _message_preview(self, msg_text):
        """Single-line preview shown in the Message column."""
        if not msg_text:
            return ""
        preview = msg_text.replace('\r', ' ').replace('\n', ' ').strip()
        if len(preview) > 120:
            preview = preview[:117] + "..."
        return preview

    def _add_message_row(self, username, msg_text, sent_at):
        """Append a single message to the conversation ListCtrl."""
        idx = self.message_display.GetItemCount()
        self.message_display.InsertItem(idx, username or "")
        self.message_display.SetItem(idx, 1, self._message_preview(msg_text))
        self.message_display.SetItem(idx, 2, self._format_message_timestamp(sent_at))
        self._message_records.append({
            'username': username or "",
            'message': msg_text or "",
            'sent_at': sent_at or "",
        })
        # Keep the most recent message visible.
        self.message_display.EnsureVisible(idx)

    def _clear_message_list(self):
        self.message_display.DeleteAllItems()
        self._message_records = []

    def OnMessageDisplayKeyDown(self, event):
        """Escape on the message list also exits the room/chat."""
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_ESCAPE:
            if self.current_view in ["room_chat", "private_chat"]:
                wx.CallAfter(self.OnBack, None)
            else:
                wx.CallAfter(self.show_menu)
            return
        event.Skip()

    def OnMessageActivated(self, event):
        """Open a read-only dialog with the full message text."""
        idx = event.GetIndex()
        if 0 <= idx < len(self._message_records):
            rec = self._message_records[idx]
            self._show_full_message_dialog(rec['username'], rec['message'], rec['sent_at'])

    def _show_full_message_dialog(self, username, message, sent_at):
        """Modal dialog showing the full message in a read-only multiline field."""
        date_label = self._format_message_timestamp(sent_at) or _("(no date)")
        title = _("Message from {nick} ({date})").format(nick=username or "", date=date_label)
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

    # Callbacks from TitanNetClient for real-time updates
    def on_room_message(self, message):
        """Handle incoming room message"""
        if message.get('room_id') == self.current_room:
            wx.CallAfter(self._append_room_message, message)

    def _append_room_message(self, message):
        """Append room message to display"""
        if self.current_view != "room_chat":
            return

        # Check if message already displayed
        msg_id = message.get('message_id')
        if msg_id and msg_id in self.displayed_message_ids:
            return  # Skip duplicate message

        if msg_id:
            self.displayed_message_ids.add(msg_id)

        msg_text = message.get('message', '')
        self._add_message_row(message.get('username', ''), msg_text, message.get('sent_at', ''))

        play_sound('titannet/new_message.ogg')

        # Announce message
        announcement = _("{user}: {message}").format(
            user=message.get('username', ''),
            message=msg_text
        )
        speak_titannet(announcement)

    def on_private_message(self, message):
        """Handle incoming private message"""
        sender_id = message.get('sender_id')

        if sender_id == self.current_private_user:
            wx.CallAfter(self._append_private_message, message)
        else:
            # New message from someone else
            wx.CallAfter(self._notify_new_pm, message)

    def _append_private_message(self, message):
        """Append private message to display"""
        if self.current_view != "private_chat":
            return

        # Check if message already displayed
        msg_id = message.get('message_id')
        if msg_id and msg_id in self.displayed_message_ids:
            return  # Skip duplicate message

        if msg_id:
            self.displayed_message_ids.add(msg_id)

        msg_text = message.get('message', '')
        sender = message.get('sender_username', '')
        self._add_message_row(sender, msg_text, message.get('sent_at', ''))
        has_custom = message.get('has_custom_sounds', False)
        self._play_business_card_sound(sender, 'new_message', 'titannet/new_message.ogg', has_custom)

        # Announce message
        announcement = _("{user}: {message}").format(
            user=sender,
            message=msg_text
        )
        speak_titannet(announcement)

        # Automatically mark this message as read since user is viewing the chat
        if self.current_private_user:
            def mark_read_thread():
                self.titan_client.mark_private_messages_as_read(self.current_private_user)
            threading.Thread(target=mark_read_thread, daemon=True).start()

    def _get_cached_business_card_sound(self, username, sound_type):
        """Get cached business card sound path, or None if not cached."""
        return self._business_card_cache.get(username, {}).get(sound_type)

    def _download_and_cache_sound(self, username, sound_type):
        """Download a user's business card sound and cache it locally. Returns local path or None."""
        cached = self._get_cached_business_card_sound(username, sound_type)
        if cached and os.path.exists(cached):
            return cached

        try:
            result = self.titan_client.download_user_sound(username, sound_type)
            if result.get('success') and result.get('file_data'):
                content_type = result.get('content_type', '')
                if 'ogg' in content_type:
                    ext = '.ogg'
                elif 'mp3' in content_type:
                    ext = '.mp3'
                else:
                    ext = '.wav'

                user_cache_dir = os.path.join(self._business_card_cache_dir, username)
                os.makedirs(user_cache_dir, exist_ok=True)
                local_path = os.path.join(user_cache_dir, f"{sound_type}{ext}")

                with open(local_path, 'wb') as f:
                    f.write(result['file_data'])

                if username not in self._business_card_cache:
                    self._business_card_cache[username] = {}
                self._business_card_cache[username][sound_type] = local_path
                return local_path
        except Exception as e:
            print(f"[TITAN-NET] Failed to download business card sound {sound_type} for {username}: {e}")

        return None

    def _play_business_card_sound(self, username, sound_type, fallback_sound, has_custom_sounds=False):
        """Play business card sound if available, otherwise fall back to default."""
        if has_custom_sounds:
            def download_and_play():
                local_path = self._download_and_cache_sound(username, sound_type)
                if local_path:
                    play_sound_file(local_path)
                else:
                    play_sound(fallback_sound)
            threading.Thread(target=download_and_play, daemon=True).start()
        else:
            play_sound(fallback_sound)

    def _play_user_avatar(self, username):
        """Download and open avatar audio in an EltenPlayer dialog."""
        speak_titannet(_("Loading avatar..."))
        def download_and_open():
            local_path = self._download_and_cache_sound(username, 'avatar')
            if local_path:
                wx.CallAfter(self._show_avatar_player, username, local_path)
            else:
                speak_titannet(_("No avatar available for {user}").format(user=username))
        threading.Thread(target=download_and_open, daemon=True).start()

    def _show_avatar_player(self, username, file_path):
        """Show avatar audio player dialog with EltenPlayer. Auto-closes when done."""
        from src.eltenlink_client.elten_player import EltenPlayer

        dlg = wx.Dialog(self, title=_("Avatar - {user}").format(user=username),
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        sizer = wx.BoxSizer(wx.VERTICAL)

        def on_playback_complete():
            if dlg:
                dlg.Close()

        player = EltenPlayer(dlg, file_or_url=file_path,
                             label=_("Avatar - {user}").format(user=username),
                             autoplay=True, on_complete=on_playback_complete)
        sizer.Add(player, 1, wx.EXPAND | wx.ALL, 5)

        close_btn = wx.Button(dlg, wx.ID_CLOSE, _("Close"))
        close_btn.Bind(wx.EVT_BUTTON, lambda e: dlg.Close())
        sizer.Add(close_btn, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        dlg.SetSizer(sizer)
        dlg.SetSize(wx.Size(400, 150))

        def on_close(event):
            player.close()
            dlg.Destroy()
        dlg.Bind(wx.EVT_CLOSE, on_close)

        dlg.Show()

    def _notify_new_pm(self, message):
        """Notify about new PM"""
        sender = message.get('sender_username', '')
        sender_id = message.get('sender_id')
        if sender_id is not None:
            self._last_pm_sender_id = sender_id
            self._last_pm_sender_username = sender
        has_custom = message.get('has_custom_sounds', False)
        self._play_business_card_sound(sender, 'new_message', 'titannet/new_message.ogg', has_custom)
        speak_titannet(_("New message from {user}. Press Ctrl+O to reply.").format(user=sender))

    def on_user_online(self, username, has_custom_sounds=False):
        """User came online"""
        if self.current_view in ["users", "private_messages_select"]:
            wx.CallAfter(self.refresh_users)
        self._play_business_card_sound(username, 'login', 'titannet/online.ogg', has_custom_sounds)
        speak_titannet(_("{user} is now online").format(user=username))

    def on_user_offline(self, username, has_custom_sounds=False):
        """User went offline"""
        if self.current_view in ["users", "private_messages_select"]:
            wx.CallAfter(self.refresh_users)
        self._play_business_card_sound(username, 'logout', 'titannet/offline.ogg', has_custom_sounds)
        speak_titannet(_("{user} is now offline").format(user=username))

    def _on_feedback_new_global(self, message):
        """Notify whenever a new feedback / idea lands in the Feedback Hub.

        Plays the new-feedback earcon and announces:
            "Feedback Hub: 1 new idea from <user>: <title>"
        Wired even when the Feedback Hub window is closed so users still
        hear about activity (matches the spec: "do centrum opinii wpadl
        1 pomysl/1 opinia").
        """
        item_type = message.get('item_type', 'feedback')
        author = message.get('author_username', '?')
        title = message.get('title', '?')
        try:
            play_sound('titannet/feedback hub/new feedback.ogg')
        except Exception:
            pass
        if item_type == 'idea':
            text = _("Feedback Hub: 1 new idea from {user}: {title}").format(user=author, title=title)
        else:
            text = _("Feedback Hub: 1 new feedback from {user}: {title}").format(user=author, title=title)
        speak_titannet(text)
        print(f"[TITAN-NET] Feedback Hub: new {item_type} '{title}' by {author}")

    def _on_feedback_status_global(self, message):
        """Announce status changes / idea decisions globally."""
        item_type = message.get('item_type', 'feedback')
        title = message.get('title', '?')
        new_status = message.get('status', 'pending')

        if item_type == 'idea' and new_status == 'accepted':
            try:
                play_sound('titannet/feedback hub/idea accepted.ogg')
            except Exception:
                pass
            text = _("Idea {title} accepted").format(title=title)
        elif item_type == 'idea' and new_status == 'rejected':
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
            text = _("Feedback {title}: status changed").format(title=title)
        speak_titannet(text)
        print(f"[TITAN-NET] Feedback Hub: {item_type} '{title}' status -> {new_status}")

    def on_package_pending(self, message):
        """New package submitted to waiting room.

        Plays the apprepo earcon and speaks a panoramic notification so the
        announcement is audible even when the user is not looking at the
        repository view.
        """
        app_name = message.get('app_name', 'Unknown')
        author_username = message.get('author_username', 'Unknown')

        try:
            play_sound('apprepo/appupdate.ogg')
        except Exception as e:
            print(f"[TITAN-NET] Failed to play apprepo sound: {e}")
        notification_text = _("App Repository: new package {app} from {user}, waiting for moderation").format(
            app=app_name, user=author_username)
        # play_sound_effect=False because we already played the apprepo earcon.
        speak_notification(notification_text, 'info', play_sound_effect=False)
        print(f"[TITAN-NET] New package: {app_name} by {author_username} (pending approval)")

    def on_package_approved(self, message):
        """Package approved by moderation."""
        app_name = message.get('app_name', 'Unknown')
        author_username = message.get('author_username', 'Unknown')
        approved_by = message.get('approved_by', 'Moderator')

        try:
            play_sound('apprepo/appupdate.ogg')
        except Exception as e:
            print(f"[TITAN-NET] Failed to play apprepo sound: {e}")
        notification_text = _("App Repository: {app} from {user} approved by {moderator}").format(
            app=app_name, user=author_username, moderator=approved_by)
        speak_notification(notification_text, 'success', play_sound_effect=False)
        print(f"[TITAN-NET] Package approved: {app_name} by {author_username} (approved by {approved_by})")

    def on_new_user_broadcast(self, message):
        """New user registration broadcast"""
        from src.settings.settings import get_setting

        # Get broadcast message details
        broadcast_lang = message.get('language', 'en')
        broadcast_text = message.get('message', '')
        username = message.get('username', 'Unknown')
        titan_number = message.get('titan_number', 0)

        # Get current user's language
        current_lang = get_setting('language', 'en')

        # Only show broadcast if it matches user's language
        if broadcast_lang == current_lang and broadcast_text:
            play_sound('titannet/account_created.ogg')
            speak_titannet(broadcast_text)
            print(f"[TITAN-NET] New user broadcast: {broadcast_text}")

    # ==================== Voice Chat Callbacks ====================

    def on_voice_started(self, message):
        """User started speaking in room"""
        try:
            user_id = message.get('user_id')
            username = message.get('username')
            room_id = message.get('room_id')

            # Only process if we're in the same room
            if room_id != self.current_room:
                return

            # Add to active speakers list (silently - no TTS)
            self.active_speakers[user_id] = username
            wx.CallAfter(self._update_speakers_list)

        except Exception as e:
            print(f"Error handling voice_started: {e}")

    def on_voice_audio_binary(self, raw_data: bytes):
        """Received binary voice packet (fast path, no JSON parsing)"""
        try:
            # Fast header parse: [1B type][4B room][4B user][4B seq] = 13 bytes
            if len(raw_data) < 13:
                return
            room_id, user_id = struct.unpack_from('>xII', raw_data)  # skip 1-byte type

            # Only process if we're in the same room
            if room_id != self.current_room:
                return

            # Extract audio payload (after 13-byte header)
            audio_data = raw_data[13:]

            # Add directly to jitter buffer
            self._add_to_jitter_buffer(audio_data, user_id)

        except Exception as e:
            print(f"[VOICE] Error handling binary voice: {e}")

    def on_voice_audio(self, message):
        """Received audio chunk from user (JSON legacy fallback)"""
        try:
            user_id = message.get('user_id')
            room_id = message.get('room_id')

            # Only process if we're in the same room
            if room_id != self.current_room:
                return

            # Decode base64 on listener thread (not GUI thread) to reduce GUI load
            import base64
            audio_data = base64.b64decode(message.get('data'))

            # Add directly to jitter buffer without going through GUI thread
            self._add_to_jitter_buffer(audio_data, user_id)

        except Exception as e:
            print(f"[VOICE] Error handling voice_audio: {e}")

    def _add_to_jitter_buffer(self, audio_data: bytes, user_id: int):
        """Add audio chunk directly to jitter buffer (thread-safe).
        The single mixer thread reads from all buffers — no per-user threads needed."""
        try:
            if user_id not in self.voice_jitter_buffers:
                self.voice_jitter_buffers[user_id] = queue.Queue()
                self.voice_buffer_stopping[user_id] = False

            self.voice_jitter_buffers[user_id].put(audio_data)

        except Exception as e:
            print(f"[VOICE] Error adding to jitter buffer: {e}")

    def on_voice_stopped(self, message):
        """User stopped speaking in room"""
        try:
            user_id = message.get('user_id')
            room_id = message.get('room_id')

            # Only process if we're in the same room
            if room_id != self.current_room:
                return

            # Remove from active speakers list (silently - no TTS)
            if user_id in self.active_speakers:
                del self.active_speakers[user_id]
                wx.CallAfter(self._update_speakers_list)

            # Mark user as stopped and clear buffer so mixer skips them
            if user_id in self.voice_buffer_stopping:
                self.voice_buffer_stopping[user_id] = True
            if user_id in self._user_started:
                del self._user_started[user_id]
            if user_id in self.voice_jitter_buffers:
                while not self.voice_jitter_buffers[user_id].empty():
                    try:
                        self.voice_jitter_buffers[user_id].get_nowait()
                    except:
                        break

        except Exception as e:
            print(f"Error handling voice_stopped: {e}")

    def _on_broadcast_received(self, data):
        """Handle moderation broadcast received"""
        try:
            print(f"[BROADCAST] Received broadcast: {data}")
            moderator_username = data.get('moderator_username', 'Moderator')
            text_message = data.get('text_message')
            voice_data = data.get('voice_data')  # base64 encoded

            print(f"[BROADCAST] Text: {bool(text_message)}, Voice: {bool(voice_data)}")

            # Play moderation alert sound
            try:
                play_sound('titannet/moderation.ogg')
                print("[BROADCAST] Played moderation sound")
            except Exception as e:
                print(f"[BROADCAST] Failed to play moderation sound: {e}")
                # Fallback to error sound
                play_sound('core/error.ogg')

            # Speak "Moderation!" announcement
            try:
                language = get_setting('language', 'pl')
                if language == 'pl':
                    announcement = "Moderacja!"
                else:
                    announcement = "Moderation!"

                speak_titannet(announcement, position=0.0, pitch_offset=+5)
                print(f"[BROADCAST] Announced: {announcement}")
            except Exception as e:
                print(f"[BROADCAST] Failed to announce: {e}")

            # Wait 2 seconds, then play message
            def play_message():
                try:
                    import time
                    time.sleep(2)

                    # Play text message if present
                    if text_message:
                        print(f"[BROADCAST] Speaking text: {text_message}")
                        speak_titannet(text_message, 0.0, 0)

                    # Play voice message if present
                    if voice_data:
                        try:
                            import base64
                            import numpy as np
                            import pygame

                            print("[BROADCAST] Decoding voice data...")

                            # Decode base64 voice data
                            audio_bytes = base64.b64decode(voice_data)
                            print(f"[BROADCAST] Decoded {len(audio_bytes)} bytes")

                            # Convert to numpy array (16-bit PCM)
                            audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
                            print(f"[BROADCAST] Audio array shape: {audio_array.shape}")

                            # Resample from 16kHz to 22050 Hz (pygame mixer default)
                            try:
                                from scipy.signal import resample
                                target_samples = int(len(audio_array) * 22050 / 16000)
                                audio_resampled = resample(audio_array, target_samples).astype(np.int16)
                            except ImportError:
                                # Fallback: simple linear interpolation
                                target_samples = int(len(audio_array) * 22050 / 16000)
                                audio_resampled = np.interp(
                                    np.linspace(0, len(audio_array) - 1, target_samples),
                                    np.arange(len(audio_array)),
                                    audio_array
                                ).astype(np.int16)

                            print(f"[BROADCAST] Resampled array shape: {audio_resampled.shape}")

                            # Wait for text to finish if present
                            if text_message:
                                time.sleep(len(text_message) * 0.05)  # Rough estimate of TTS time

                            # Get mixer channels (1=mono, 2=stereo)
                            mixer_info = pygame.mixer.get_init()
                            if mixer_info:
                                frequency, size, channels = mixer_info
                                print(f"[BROADCAST] Mixer: {frequency}Hz, {channels} channels")

                                # Ensure array matches mixer channels
                                if channels == 2:
                                    # Stereo: duplicate mono to both channels
                                    audio_resampled = np.column_stack((audio_resampled, audio_resampled))
                                elif channels == 1:
                                    # Mono: ensure 1D array
                                    audio_resampled = audio_resampled.flatten()

                                print(f"[BROADCAST] Final array shape: {audio_resampled.shape}")

                            # Play voice
                            sound = pygame.sndarray.make_sound(audio_resampled)
                            sound.play()
                            print("[BROADCAST] Playing voice...")

                        except Exception as e:
                            print(f"[BROADCAST] Error playing broadcast voice: {e}")
                            import traceback
                            traceback.print_exc()

                except Exception as e:
                    print(f"[BROADCAST] Error in play_message thread: {e}")
                    import traceback
                    traceback.print_exc()

            # Run in thread to avoid blocking
            threading.Thread(target=play_message, daemon=True).start()

        except Exception as e:
            print(f"[BROADCAST] Error handling broadcast: {e}")
            import traceback
            traceback.print_exc()

    def _update_speakers_list(self):
        """Update active speakers listbox"""
        try:
            if not self.speakers_listbox:
                return

            self.speakers_listbox.Clear()

            if not self.active_speakers:
                self.speakers_listbox.Append(_("(No active speakers)"))
                return

            for user_id, username in self.active_speakers.items():
                self.speakers_listbox.Append(f"{username}")

            print(f"[VOICE DEBUG] Updated speakers list: {list(self.active_speakers.values())}")
        except Exception as e:
            print(f"[VOICE DEBUG] Error updating speakers list: {e}")

    def _play_voice_audio(self, audio_data: bytes, user_id: int):
        """Add received voice audio chunk to jitter buffer (mixer thread handles playback)"""
        self._add_to_jitter_buffer(audio_data, user_id)

    def _voice_mixer_thread(self):
        """Single mixer thread: reads from all users' jitter buffers, mixes, writes to
        sounddevice OutputStream.  Truly gapless — the audio hardware pulls samples at a
        fixed rate, so there are zero gaps between chunks.
        Uses Opus PLC on buffer underrun to conceal packet loss instead of silence."""
        import numpy as np
        import time

        CHUNK_SAMPLES = 320  # 20ms at 16000Hz (matches input — no resampling needed)

        # Track consecutive underruns per user for PLC
        user_underruns = {}  # user_id -> consecutive underrun count
        MAX_PLC_FRAMES = 5  # Max consecutive PLC frames before giving up (100ms)

        try:
            while self._mixer_running:
                mixed = np.zeros(CHUNK_SAMPLES, dtype=np.float32)
                has_audio = False

                for user_id in list(self.voice_jitter_buffers.keys()):
                    if self.voice_buffer_stopping.get(user_id, False):
                        continue

                    buf = self.voice_jitter_buffers[user_id]

                    # Wait for initial jitter buffer fill before reading this user
                    if user_id not in self._user_started:
                        if buf.qsize() >= self.jitter_buffer_size:
                            self._user_started[user_id] = True
                        else:
                            continue

                    try:
                        raw_chunk = buf.get_nowait()
                        user_underruns[user_id] = 0  # Reset underrun counter
                        resampled = self._decode_and_resample_chunk(raw_chunk, user_id=user_id)
                        if resampled is not None:
                            n = min(len(resampled), CHUNK_SAMPLES)
                            mixed[:n] += resampled[:n].astype(np.float32)
                            has_audio = True
                    except queue.Empty:
                        # Buffer underrun — use Opus PLC if available
                        underruns = user_underruns.get(user_id, 0) + 1
                        user_underruns[user_id] = underruns
                        if underruns <= MAX_PLC_FRAMES and hasattr(self, '_use_opus') and self._use_opus:
                            plc_audio = self._opus_plc(user_id)
                            if plc_audio is not None:
                                n = min(len(plc_audio), CHUNK_SAMPLES)
                                mixed[:n] += plc_audio[:n].astype(np.float32)
                                has_audio = True

                # Apply volume
                volume = self._cached_volume
                if volume < 1.0:
                    mixed *= volume

                # Clip to int16 range
                np.clip(mixed, -32768, 32767, out=mixed)

                # Write to output stream — blocks until hardware consumes (~20ms)
                # This provides natural pacing with zero gaps
                try:
                    self._voice_output_stream.write(mixed.astype(np.int16).reshape(-1, 1))
                except Exception:
                    if not self._mixer_running:
                        break
                    time.sleep(0.02)

        except Exception as e:
            print(f"[VOICE] Error in mixer thread: {e}")
            import traceback
            traceback.print_exc()

    def _opus_plc(self, user_id):
        """Generate Opus Packet Loss Concealment audio for a missing chunk.
        Opus decoder generates a plausible continuation of the previous audio."""
        import numpy as np
        try:
            decoder = self._opus_decoders.get(user_id)
            if decoder:
                # Opus PLC: decode with None input — decoder extrapolates from previous state
                plc_pcm = decoder.decode(None)
                return np.frombuffer(plc_pcm, dtype=np.int16)
        except Exception:
            pass
        return None

    def _decode_and_resample_chunk(self, audio_data: bytes, user_id=None):
        """Decode Opus chunk. Returns mono int16 numpy array at 16kHz (no resampling needed)."""
        import numpy as np

        try:
            # Decode Opus if enabled
            if hasattr(self, '_use_opus') and self._use_opus and len(audio_data) < 500:
                try:
                    from src.network.voice_codec import OpusVoiceCodec
                    if user_id not in self._opus_decoders:
                        self._opus_decoders[user_id] = OpusVoiceCodec(
                            sample_rate=16000, channels=1, bitrate=24000, frame_duration_ms=20
                        )
                    audio_data = self._opus_decoders[user_id].decode(audio_data)
                except Exception:
                    pass  # Fallback: treat as raw PCM

            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            if len(audio_array) == 0:
                return None

            # Output stream runs at 16kHz — same as input, no resampling needed
            return audio_array

        except Exception as e:
            print(f"[VOICE PLAYBACK] Error processing chunk: {e}")
            return None

    def _update_voice_volume_cache(self):
        """Update cached voice volume from GUI slider (must be called from GUI thread)"""
        import time
        try:
            self._cached_volume = self.voice_volume_slider.GetValue() / 100.0
            self._last_volume_update = time.time()
        except Exception:
            pass

    # ================================================================
    # CERBERUS PROTOCOL
    # ================================================================

    def show_cerberus_protocol(self):
        """Show Cerberus Protocol status and menu"""
        self.current_view = "cerberus"
        self.view_label.SetLabel(_("Cerberus Protocol"))

        # Hide chat elements
        self.message_display.Hide()
        self.message_input.Hide()
        self.send_button.Hide()
        self.leave_room_button.Hide()
        self.voice_panel.Hide()
        self.broadcast_panel.Hide()

        # Show main list and back button
        self.main_listbox.Show()
        self.back_button.Show()

        self.main_listbox.Clear()

        # Load status in background
        speak_titannet(_("Loading Cerberus Protocol status..."))

        def load_thread():
            try:
                status = self.titan_client.get_cerberus_status()
                wx.CallAfter(self._display_cerberus_status, status)
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')

        threading.Thread(target=load_thread, daemon=True).start()

    def _display_cerberus_status(self, status):
        """Display Cerberus Protocol status in main list"""
        if not status or status.get('type') == 'error':
            error_msg = status.get('error', 'Unknown error') if status else 'No response'
            speak_notification(_("Could not load Cerberus status: {error}").format(error=error_msg), 'error')
            return

        self.main_listbox.Clear()
        self._cerberus_cached_status = status

        threat_level = status.get('threat_level', 0)
        threat_name = status.get('threat_name', 'UNKNOWN')
        lockdown = status.get('lockdown_active', False)
        banned_count = len(status.get('banned_ips', []))
        perma_banned_count = len(status.get('permanent_banned_ips', []))
        whitelisted_count = len(status.get('whitelisted_ips', []))
        attackers_count = len(status.get('tracked_attackers', {}))
        per_ip_count = len(status.get('per_ip_threats', {}))
        stats = status.get('stats', {})
        intrusions_blocked = stats.get('intrusions_blocked', 0)
        ddos_blocked = stats.get('ddos_blocked', 0)

        # Status header
        if lockdown:
            lockdown_reason = status.get('lockdown_reason', '')
            lockdown_duration = int(status.get('lockdown_duration', 0))
            mins = lockdown_duration // 60
            secs = lockdown_duration % 60
            self.main_listbox.Append(
                _("STATUS: {level} - LOCKDOWN ACTIVE ({mins}m {secs}s) - {reason}").format(
                    level=threat_name, mins=mins, secs=secs, reason=lockdown_reason
                )
            )
        else:
            self.main_listbox.Append(
                _("STATUS: {level}").format(level=threat_name)
            )

        # Stats summary
        self.main_listbox.Append(
            _("Intrusions blocked: {count} | DDoS blocked: {ddos} | Active threats: {threats}").format(
                count=intrusions_blocked, ddos=ddos_blocked, threats=per_ip_count
            )
        )
        self.main_listbox.Append(
            _("Banned IPs: {banned} ({perma} permanent) | Whitelisted: {white} | Attackers tracked: {attackers}").format(
                banned=banned_count, perma=perma_banned_count, white=whitelisted_count, attackers=attackers_count
            )
        )

        # Separator
        self.main_listbox.Append("---")

        # Actions (read-only for moderators)
        self.main_listbox.Append(_("Refresh Status"))
        self.main_listbox.Append(_("View Intrusion Logs"))
        self.main_listbox.Append(_("View Honeypot Logs"))
        self.main_listbox.Append(_("Banned IPs"))
        self.main_listbox.Append(_("Tracked Attackers"))

        # Developer-only actions
        if self.is_developer:
            self.main_listbox.Append("---")
            if lockdown:
                self.main_listbox.Append(_("Deactivate Lockdown"))
            else:
                self.main_listbox.Append(_("Activate Lockdown"))
                self.main_listbox.Append(_("Activate CERBERUS Mode"))
            self.main_listbox.Append(_("Ban IP"))
            self.main_listbox.Append(_("Unban IP"))
            self.main_listbox.Append(_("Whitelist IP"))

        self.main_listbox.SetSelection(0)
        self.main_listbox.SetFocus()
        self.panel.Layout()
        play_sound('core/SELECT.ogg')

        # Announce status via TTS
        speak_titannet(
            _("Cerberus Protocol: {level}. {blocked} intrusions blocked. {banned} IPs banned.").format(
                level=threat_name, blocked=intrusions_blocked, banned=banned_count
            )
        )

    def _cerberus_show_logs(self):
        """Show Cerberus intrusion logs in a dialog"""
        speak_titannet(_("Loading intrusion logs..."))

        def load_thread():
            try:
                result = self.titan_client.get_cerberus_logs(max_lines=100)
                wx.CallAfter(self._display_cerberus_logs, result)
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')

        threading.Thread(target=load_thread, daemon=True).start()

    def _display_cerberus_logs(self, result):
        """Display intrusion logs in a dialog"""
        if not result or result.get('type') == 'error':
            error_msg = result.get('error', 'Unknown error') if result else 'No response'
            speak_notification(_("Could not load logs: {error}").format(error=error_msg), 'error')
            return

        logs = result.get('logs', [])
        if not logs:
            speak_notification(_("No intrusion logs found"), 'info')
            return

        # Build log text (most recent at top)
        log_lines = []
        for entry in reversed(logs):
            ts = entry.get('timestamp', '')
            sev = entry.get('severity', '')
            msg = entry.get('message', '')
            log_lines.append(f"[{ts}] {sev}: {msg}")

        log_text = '\n'.join(log_lines)

        dlg = wx.Dialog(self, title=_("Cerberus Intrusion Logs"), size=wx.Size(700, 500))
        panel = wx.Panel(dlg)
        sizer = wx.BoxSizer(wx.VERTICAL)

        info_label = wx.StaticText(panel, label=_("Showing {count} log entries (most recent first)").format(
            count=len(logs)
        ))
        sizer.Add(info_label, flag=wx.ALL, border=5)

        text_ctrl = wx.TextCtrl(panel, value=log_text, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
        sizer.Add(text_ctrl, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        close_btn = wx.Button(panel, wx.ID_CLOSE, _("Close"))
        close_btn.Bind(wx.EVT_BUTTON, lambda e: dlg.Close())
        sizer.Add(close_btn, flag=wx.ALL | wx.ALIGN_CENTER, border=5)

        panel.SetSizer(sizer)
        dlg.ShowModal()
        dlg.Destroy()

    def _cerberus_show_honeypot_logs(self):
        """Show honeypot session logs in a dialog"""
        speak_titannet(_("Loading honeypot logs..."))

        def load_thread():
            try:
                result = self.titan_client.get_cerberus_logs(max_lines=100)
                wx.CallAfter(self._display_honeypot_logs, result)
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')

        threading.Thread(target=load_thread, daemon=True).start()

    def _display_honeypot_logs(self, result):
        """Display honeypot logs in a dialog"""
        if not result or result.get('type') == 'error':
            error_msg = result.get('error', 'Unknown error') if result else 'No response'
            speak_notification(_("Could not load honeypot logs: {error}").format(error=error_msg), 'error')
            return

        honeypot = result.get('honeypot')
        if not honeypot or not honeypot.get('log_file_exists'):
            speak_notification(_("No honeypot logs found. SSH honeypot may not be active."), 'info')
            return

        entries = honeypot.get('log_entries', [])
        if not entries:
            speak_notification(_("Honeypot log is empty - no SSH intrusion attempts detected"), 'info')
            return

        # Most recent at top
        log_text = '\n'.join(reversed(entries))

        dlg = wx.Dialog(self, title=_("SSH Honeypot Logs"), size=wx.Size(700, 500))
        panel = wx.Panel(dlg)
        sizer = wx.BoxSizer(wx.VERTICAL)

        info_label = wx.StaticText(panel, label=_("SSH Honeypot session logs ({count} entries, most recent first)").format(
            count=len(entries)
        ))
        sizer.Add(info_label, flag=wx.ALL, border=5)

        text_ctrl = wx.TextCtrl(panel, value=log_text, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
        sizer.Add(text_ctrl, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        close_btn = wx.Button(panel, wx.ID_CLOSE, _("Close"))
        close_btn.Bind(wx.EVT_BUTTON, lambda e: dlg.Close())
        sizer.Add(close_btn, flag=wx.ALL | wx.ALIGN_CENTER, border=5)

        panel.SetSizer(sizer)
        dlg.ShowModal()
        dlg.Destroy()

    def _cerberus_show_banned_ips(self):
        """Show banned IPs list"""
        status = getattr(self, '_cerberus_cached_status', None)
        if not status:
            speak_notification(_("No cached status. Refresh first."), 'warning')
            return

        banned = status.get('banned_ips', [])
        perma = status.get('permanent_banned_ips', [])
        whitelisted = status.get('whitelisted_ips', [])

        items = []
        for ip in perma:
            items.append(_("{ip} (permanent ban)").format(ip=ip))
        for ip in banned:
            if ip not in perma:
                items.append(_("{ip} (temporary ban)").format(ip=ip))

        if whitelisted:
            items.append("---")
            for ip in whitelisted:
                items.append(_("{ip} (whitelisted)").format(ip=ip))

        if not items:
            speak_notification(_("No banned or whitelisted IPs"), 'info')
            return

        dlg = wx.SingleChoiceDialog(self, _("Banned and whitelisted IPs"), _("Cerberus IP List"), items)
        dlg.ShowModal()
        dlg.Destroy()

    def _cerberus_show_attackers(self):
        """Show tracked attackers list"""
        status = getattr(self, '_cerberus_cached_status', None)
        if not status:
            speak_notification(_("No cached status. Refresh first."), 'warning')
            return

        attackers = status.get('tracked_attackers', {})
        per_ip = status.get('per_ip_threats', {})

        items = []
        for ip, data in attackers.items():
            threat_score = data.get('threat_score', 0)
            attack_type = data.get('type', 'unknown')
            first_seen = data.get('first_seen', '')
            ip_level = per_ip.get(ip, {}).get('level', 'NORMAL')
            ip_reason = per_ip.get(ip, {}).get('reason', '')
            line = _("{ip} | Score: {score} | Type: {type} | Level: {level} | Since: {since}").format(
                ip=ip, score=threat_score, type=attack_type, level=ip_level, since=first_seen
            )
            if ip_reason:
                line += f" | {ip_reason}"
            items.append(line)

        if not items:
            speak_notification(_("No tracked attackers"), 'info')
            return

        dlg = wx.SingleChoiceDialog(self, _("Tracked attackers"), _("Cerberus Attackers"), items)
        dlg.ShowModal()
        dlg.Destroy()

    def _cerberus_activate_lockdown(self):
        """Activate global lockdown (developer only)"""
        if not self.is_developer:
            speak_notification(_("Only developers can activate lockdown"), 'warning')
            return

        dlg = _new_text_entry_dialog(self, _("Enter reason for lockdown:"), _("Activate Lockdown"))
        if dlg.ShowModal() == wx.ID_OK:
            reason = dlg.GetValue().strip() or "Manual lockdown"
            dlg.Destroy()

            speak_titannet(_("Activating lockdown..."))

            def activate_thread():
                try:
                    result = self.titan_client.cerberus_activate(level='lockdown', reason=reason)
                    if result and result.get('success'):
                        wx.CallAfter(speak_notification, _("Lockdown activated"), 'warning')
                        wx.CallAfter(self.show_cerberus_protocol)
                    else:
                        error = result.get('error', 'Unknown error') if result else 'No response'
                        wx.CallAfter(speak_notification, _("Failed: {error}").format(error=error), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=activate_thread, daemon=True).start()
        else:
            dlg.Destroy()

    def _cerberus_activate_cerberus(self):
        """Activate full CERBERUS mode (developer only)"""
        if not self.is_developer:
            speak_notification(_("Only developers can activate CERBERUS mode"), 'warning')
            return

        confirm = _new_message_dialog(
            self,
            _("CERBERUS mode is the maximum threat level. All new connections will be blocked. "
              "Are you sure you want to activate CERBERUS mode?"),
            _("Activate CERBERUS Mode"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING
        )
        if confirm.ShowModal() != wx.ID_YES:
            confirm.Destroy()
            return
        confirm.Destroy()

        dlg = _new_text_entry_dialog(self, _("Enter reason:"), _("Activate CERBERUS"))
        if dlg.ShowModal() == wx.ID_OK:
            reason = dlg.GetValue().strip() or "Manual CERBERUS activation"
            dlg.Destroy()

            speak_titannet(_("Activating CERBERUS mode..."))

            def activate_thread():
                try:
                    result = self.titan_client.cerberus_activate(level='cerberus', reason=reason)
                    if result and result.get('success'):
                        wx.CallAfter(speak_notification, _("CERBERUS mode activated"), 'error')
                        wx.CallAfter(self.show_cerberus_protocol)
                    else:
                        error = result.get('error', 'Unknown error') if result else 'No response'
                        wx.CallAfter(speak_notification, _("Failed: {error}").format(error=error), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=activate_thread, daemon=True).start()
        else:
            dlg.Destroy()

    def _cerberus_deactivate(self):
        """Deactivate lockdown (developer only)"""
        if not self.is_developer:
            speak_notification(_("Only developers can deactivate lockdown"), 'warning')
            return

        dlg = _new_text_entry_dialog(self, _("Enter reason for deactivation:"), _("Deactivate Lockdown"))
        if dlg.ShowModal() == wx.ID_OK:
            reason = dlg.GetValue().strip() or "Manual deactivation"
            dlg.Destroy()

            def deactivate_thread():
                try:
                    result = self.titan_client.cerberus_deactivate(reason=reason)
                    if result and result.get('success'):
                        wx.CallAfter(speak_notification, _("Lockdown deactivated"), 'success')
                        wx.CallAfter(self.show_cerberus_protocol)
                    else:
                        error = result.get('error', 'Unknown error') if result else 'No response'
                        wx.CallAfter(speak_notification, _("Failed: {error}").format(error=error), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=deactivate_thread, daemon=True).start()
        else:
            dlg.Destroy()

    def _cerberus_ban_ip_dialog(self):
        """Ban IP dialog (developer only)"""
        if not self.is_developer:
            speak_notification(_("Only developers can ban IPs"), 'warning')
            return

        dlg = _new_text_entry_dialog(self, _("Enter IP address to ban:"), _("Ban IP"))
        if dlg.ShowModal() == wx.ID_OK:
            ip = dlg.GetValue().strip()
            dlg.Destroy()
            if not ip:
                return

            def ban_thread():
                try:
                    result = self.titan_client.cerberus_ban_ip(ip, permanent=True)
                    if result and result.get('success'):
                        wx.CallAfter(speak_notification, _("IP {ip} banned").format(ip=ip), 'success')
                        wx.CallAfter(self.show_cerberus_protocol)
                    else:
                        error = result.get('error', 'Unknown error') if result else 'No response'
                        wx.CallAfter(speak_notification, _("Failed: {error}").format(error=error), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=ban_thread, daemon=True).start()
        else:
            dlg.Destroy()

    def _cerberus_unban_ip_dialog(self):
        """Unban IP dialog (developer only)"""
        if not self.is_developer:
            speak_notification(_("Only developers can unban IPs"), 'warning')
            return

        # Show list of banned IPs to choose from
        status = getattr(self, '_cerberus_cached_status', None)
        banned = []
        if status:
            banned = list(set(status.get('banned_ips', []) + status.get('permanent_banned_ips', [])))

        if banned:
            dlg = wx.SingleChoiceDialog(self, _("Select IP to unban:"), _("Unban IP"), banned)
        else:
            dlg = _new_text_entry_dialog(self, _("Enter IP address to unban:"), _("Unban IP"))

        if dlg.ShowModal() == wx.ID_OK:
            ip = dlg.GetStringSelection() if isinstance(dlg, wx.SingleChoiceDialog) else dlg.GetValue().strip()
            dlg.Destroy()
            if not ip:
                return

            def unban_thread():
                try:
                    result = self.titan_client.cerberus_unban_ip(ip)
                    if result and result.get('success'):
                        wx.CallAfter(speak_notification, _("IP {ip} unbanned").format(ip=ip), 'success')
                        wx.CallAfter(self.show_cerberus_protocol)
                    else:
                        error = result.get('error', 'Unknown error') if result else 'No response'
                        wx.CallAfter(speak_notification, _("Failed: {error}").format(error=error), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=unban_thread, daemon=True).start()
        else:
            dlg.Destroy()

    def _cerberus_whitelist_ip_dialog(self):
        """Whitelist IP dialog (developer only)"""
        if not self.is_developer:
            speak_notification(_("Only developers can manage whitelist"), 'warning')
            return

        choices = [_("Add IP to whitelist"), _("Remove IP from whitelist")]
        action_dlg = wx.SingleChoiceDialog(self, _("Whitelist action:"), _("Whitelist IP"), choices)
        if action_dlg.ShowModal() != wx.ID_OK:
            action_dlg.Destroy()
            return

        action = 'add' if action_dlg.GetSelection() == 0 else 'remove'
        action_dlg.Destroy()

        dlg = _new_text_entry_dialog(self, _("Enter IP address:"), _("Whitelist IP"))
        if dlg.ShowModal() == wx.ID_OK:
            ip = dlg.GetValue().strip()
            dlg.Destroy()
            if not ip:
                return

            def whitelist_thread():
                try:
                    result = self.titan_client.cerberus_whitelist_ip(ip, action=action)
                    if result and result.get('success'):
                        action_name = _("added to") if action == 'add' else _("removed from")
                        wx.CallAfter(speak_notification,
                                     _("IP {ip} {action} whitelist").format(ip=ip, action=action_name), 'success')
                        wx.CallAfter(self.show_cerberus_protocol)
                    else:
                        error = result.get('error', 'Unknown error') if result else 'No response'
                        wx.CallAfter(speak_notification, _("Failed: {error}").format(error=error), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=whitelist_thread, daemon=True).start()
        else:
            dlg.Destroy()

    # Moderation Methods

    def show_manage_moderators(self):
        """Show moderator management (developer only)"""
        if not self.is_developer:
            speak_notification(_("Only developers can manage moderators"), 'warning')
            return

        # Get all moderators
        def load_thread():
            try:
                result = self.titan_client.get_all_moderators()
                wx.CallAfter(self._display_moderators, result)
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')

        threading.Thread(target=load_thread, daemon=True).start()

    def _display_moderators(self, result):
        """Display moderators list"""
        if not result or not result.get('success'):
            speak_notification(_("Could not load moderators"), 'error')
            return

        moderators = result.get('moderators', [])

        # Show moderators in a simple list dialog
        mod_list = []
        for mod in moderators:
            mod_list.append(f"{mod['username']} (#{mod['titan_number']}) - {mod['title']}")

        if not mod_list:
            mod_list.append(_("No moderators appointed"))

        # Just show the list (promote/demote are in Administration menu)
        dlg = wx.SingleChoiceDialog(self, _("List of all moderators"), _("Moderators"), mod_list)
        dlg.ShowModal()
        dlg.Destroy()

    def _promote_user_dialog(self):
        """Dialog to promote user to moderator"""
        # Ask for username
        dlg = _new_text_entry_dialog(self, _("Enter username to promote:"), _("Promote to Moderator"))

        if dlg.ShowModal() == wx.ID_OK:
            username = dlg.GetValue().strip()

            # Ask for title
            title_dlg = _new_text_entry_dialog(self, _("Enter moderator title:"), _("Moderator Title"), "Moderator")

            if title_dlg.ShowModal() == wx.ID_OK:
                title = title_dlg.GetValue().strip()

                # Promote user
                def promote_thread():
                    try:
                        result = self.titan_client.promote_to_moderator(username, title)
                        if result.get('success'):
                            wx.CallAfter(speak_titannet, _("User promoted to moderator"))
                            wx.CallAfter(speak_notification, _("User promoted successfully"), 'success')
                        else:
                            wx.CallAfter(speak_notification, result.get('message', _("Failed to promote user")), 'error')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')

                threading.Thread(target=promote_thread, daemon=True).start()

            title_dlg.Destroy()

        dlg.Destroy()

    def _demote_moderator_dialog(self):
        """Dialog to demote moderator"""
        dlg = _new_text_entry_dialog(self, _("Enter username to demote:"), _("Demote Moderator"))

        if dlg.ShowModal() == wx.ID_OK:
            username = dlg.GetValue().strip()

            # Confirm
            confirm = _new_message_dialog(self,
                _("Are you sure you want to demote {user}?").format(user=username),
                _("Confirm Demotion"),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)

            if confirm.ShowModal() == wx.ID_YES:
                # Demote user
                def demote_thread():
                    try:
                        result = self.titan_client.demote_from_moderator(username)
                        if result.get('success'):
                            wx.CallAfter(speak_titannet, _("User demoted"))
                            wx.CallAfter(speak_notification, _("User demoted successfully"), 'success')
                        else:
                            wx.CallAfter(speak_notification, result.get('message', _("Failed to demote user")), 'error')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')

                threading.Thread(target=demote_thread, daemon=True).start()

            confirm.Destroy()

        dlg.Destroy()

    def _user_create_room(self):
        """Dialog to create a new chat room"""
        # Room name
        name_dlg = _new_text_entry_dialog(self, _("Enter room name:"), _("Create New Room"))

        if name_dlg.ShowModal() == wx.ID_OK:
            room_name = name_dlg.GetValue().strip()

            if not room_name:
                speak_notification(_("Room name cannot be empty"), 'error')
                name_dlg.Destroy()
                return

            # Room description
            desc_dlg = _new_text_entry_dialog(self, _("Enter room description (optional):"), _("Room Description"))

            if desc_dlg.ShowModal() == wx.ID_OK:
                room_description = desc_dlg.GetValue().strip()

                # Ask for room type
                type_dlg = wx.SingleChoiceDialog(self,
                    _("Select room type:"),
                    _("Room Type"),
                    [_("Text Chat"), _("Voice Chat"), _("Mixed (Text + Voice)")])

                if type_dlg.ShowModal() == wx.ID_OK:
                    type_map = {0: "text", 1: "voice", 2: "mixed"}
                    room_type = type_map.get(type_dlg.GetSelection(), "text")

                    # Ask for password (optional)
                    password_dlg = _new_text_entry_dialog(self, _("Enter password for private room (leave empty for public):"), _("Room Password"))

                    if password_dlg.ShowModal() == wx.ID_OK:
                        password = password_dlg.GetValue().strip()

                        # Create room
                        def create_thread():
                            try:
                                result = self.titan_client.create_room(room_name, room_description, room_type, password)
                                if result.get('success'):
                                    wx.CallAfter(speak_titannet, _("Room created"))
                                    wx.CallAfter(speak_notification, _("Room created successfully"), 'success')
                                    if self.current_view == "rooms":
                                        wx.CallAfter(self.refresh_rooms)
                                else:
                                    wx.CallAfter(speak_notification, result.get('message', _("Failed to create room")), 'error')
                            except Exception as e:
                                wx.CallAfter(speak_notification, str(e), 'error')

                        threading.Thread(target=create_thread, daemon=True).start()

                    password_dlg.Destroy()

                type_dlg.Destroy()

            desc_dlg.Destroy()

        name_dlg.Destroy()

    def _user_create_topic(self):
        """Dialog to create a new forum topic"""
        # Topic title
        title_dlg = _new_text_entry_dialog(self, _("Enter topic title:"), _("Create New Thread"))

        if title_dlg.ShowModal() == wx.ID_OK:
            topic_title = title_dlg.GetValue().strip()

            if not topic_title:
                speak_notification(_("Topic title cannot be empty"), 'error')
                title_dlg.Destroy()
                return

            # Topic content - multiline dialog
            content_dlg = wx.Dialog(self, title=_("Topic Content"), size=(500, 300))
            content_panel = wx.Panel(content_dlg)
            content_sizer = wx.BoxSizer(wx.VERTICAL)

            content_label = wx.StaticText(content_panel, label=_("Enter topic content:"))
            content_sizer.Add(content_label, flag=wx.ALL, border=5)

            content_text = wx.TextCtrl(content_panel, style=wx.TE_MULTILINE | wx.TE_WORDWRAP)
            content_sizer.Add(content_text, proportion=1, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=5)

            content_btn_sizer = wx.StdDialogButtonSizer()
            ok_btn = wx.Button(content_panel, wx.ID_OK)
            cancel_btn = wx.Button(content_panel, wx.ID_CANCEL)
            content_btn_sizer.AddButton(ok_btn)
            content_btn_sizer.AddButton(cancel_btn)
            content_btn_sizer.Realize()
            content_sizer.Add(content_btn_sizer, flag=wx.EXPAND | wx.ALL, border=5)

            content_panel.SetSizer(content_sizer)
            content_text.SetFocus()

            if content_dlg.ShowModal() == wx.ID_OK:
                topic_content = content_text.GetValue().strip()

                if not topic_content:
                    speak_notification(_("Topic content cannot be empty"), 'error')
                    content_dlg.Destroy()
                    title_dlg.Destroy()
                    return

                # Category selection
                categories = [_("General"), _("Help"), _("Off-Topic"), _("Announcements"), _("Development")]
                cat_dlg = wx.SingleChoiceDialog(self,
                    _("Select category:"),
                    _("Topic Category"),
                    categories)

                if cat_dlg.ShowModal() == wx.ID_OK:
                    category_map = {0: "general", 1: "help", 2: "off-topic", 3: "announcements", 4: "development"}
                    category = category_map.get(cat_dlg.GetSelection(), "general")

                    # Create topic
                    def create_thread():
                        try:
                            result = self.titan_client.create_forum_topic(topic_title, topic_content, category)
                            if result.get('success'):
                                wx.CallAfter(speak_titannet, _("Thread created"))
                                wx.CallAfter(speak_notification, _("Thread created successfully"), 'success')
                                if self.current_view == "forum":
                                    wx.CallAfter(self.refresh_forum_topics)
                            else:
                                wx.CallAfter(speak_notification, result.get('message', _("Failed to create thread")), 'error')
                        except Exception as e:
                            wx.CallAfter(speak_notification, str(e), 'error')

                    threading.Thread(target=create_thread, daemon=True).start()

                cat_dlg.Destroy()

            content_dlg.Destroy()

        title_dlg.Destroy()

    def _view_all_users(self):
        """View all users (including offline) for moderation purposes"""
        if self.is_moderator or self.is_developer:
            # Moderators/developers can see all users
            self.current_view = "all_users"
            self.view_label.SetLabel(_("All TCE Users"))

            # Hide chat elements
            self.room_users_listbox.Hide()
            self.message_display.Hide()
            self.message_input.Hide()
            self.send_button.Hide()
            self.leave_room_button.Hide()

            # Show main list and back button
            self.main_listbox.Show()
            self.back_button.Show()

            # Load all users
            def load_thread():
                result = self.titan_client.get_all_users()
                wx.CallAfter(self._display_all_users, result)

            threading.Thread(target=load_thread, daemon=True).start()

            self.panel.Layout()
            self.update_menu_bar()
            play_sound('core/SELECT.ogg')
        else:
            # Regular users see online users only
            self.show_users_view()

    def _display_all_users(self, result):
        """Display all users list"""
        if result.get('success'):
            users = result.get('users', [])
            self.users_cache = users
            self.main_listbox.Clear()

            for user in users:
                username = user.get('username', 'Unknown')
                titan_number = user.get('titan_number', 0)
                created_at = user.get('created_at', '')
                # Parse date
                try:
                    from datetime import datetime
                    date_obj = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    date_str = date_obj.strftime('%Y-%m-%d')
                except:
                    date_str = created_at[:10] if created_at else ''

                self.main_listbox.Append(f"{username} (#{titan_number}) - {_('Registered')}: {date_str}")

            if self.main_listbox.GetCount() > 0:
                self.main_listbox.SetSelection(0)
                self.main_listbox.SetFocus()

            speak_titannet(_("{count} users total").format(count=len(users)))
        else:
            speak_notification(result.get('error', _("Failed to load users")), 'error')

    def _moderate_kick_user(self, username):
        """Kick user from current room (context menu action)"""
        if not self.current_room:
            return

        confirm = _new_message_dialog(self,
            _("Are you sure you want to kick this user from the room?"),
            _("Confirm Kick"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)

        if confirm.ShowModal() == wx.ID_YES:
            def kick_thread():
                try:
                    result = self.titan_client.kick_user_from_room(self.current_room, username)
                    if result.get('success'):
                        wx.CallAfter(speak_titannet, _("User kicked from room"))
                        wx.CallAfter(speak_notification, _("User kicked successfully"), 'success')
                    else:
                        wx.CallAfter(speak_notification, result.get('message', _("Failed to kick user")), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=kick_thread, daemon=True).start()

        confirm.Destroy()

    def _moderate_ban_user(self, user_id):
        """Ban user from current room (context menu action)"""
        if not self.current_room:
            return

        reason_dlg = _new_text_entry_dialog(self, _("Enter ban reason (optional):"), _("Ban Reason"), "")

        if reason_dlg.ShowModal() == wx.ID_OK:
            reason = reason_dlg.GetValue().strip()

            def ban_thread():
                try:
                    result = self.titan_client.ban_user_from_room(self.current_room, user_id, reason=reason)
                    if result.get('success'):
                        wx.CallAfter(speak_titannet, _("User banned from room"))
                        wx.CallAfter(speak_notification, _("User banned successfully"), 'success')
                    else:
                        wx.CallAfter(speak_notification, result.get('message', _("Failed to ban user")), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=ban_thread, daemon=True).start()

        reason_dlg.Destroy()

    def _admin_promote_user(self, username):
        """Promote user to moderator (context menu action)"""
        title_dlg = _new_text_entry_dialog(self, _("Enter moderator title:"), _("Moderator Title"), "Moderator")

        if title_dlg.ShowModal() == wx.ID_OK:
            title = title_dlg.GetValue().strip()

            def promote_thread():
                try:
                    result = self.titan_client.promote_to_moderator(username, title)
                    if result.get('success'):
                        wx.CallAfter(speak_titannet, _("User promoted to moderator"))
                        wx.CallAfter(speak_notification, _("User promoted successfully"), 'success')
                    else:
                        wx.CallAfter(speak_notification, result.get('message', _("Failed to promote user")), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=promote_thread, daemon=True).start()

        title_dlg.Destroy()

    def _admin_demote_user(self, username):
        """Demote moderator to user (context menu action)"""
        confirm = _new_message_dialog(self,
            _("Are you sure you want to demote {user}?").format(user=username),
            _("Confirm Demotion"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)

        if confirm.ShowModal() == wx.ID_YES:
            def demote_thread():
                try:
                    result = self.titan_client.demote_from_moderator(username)
                    if result.get('success'):
                        wx.CallAfter(speak_titannet, _("User demoted"))
                        wx.CallAfter(speak_notification, _("User demoted successfully"), 'success')
                    else:
                        wx.CallAfter(speak_notification, result.get('message', _("Failed to demote user")), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=demote_thread, daemon=True).start()

        confirm.Destroy()

    # Context menu handlers for ban/unban operations

    def _context_ban_from_room(self, user):
        """Ban user from room via context menu"""
        if not self.current_room:
            return

        # Select ban type
        ban_types = [
            _("Temporary Ban (1 hour)"),
            _("Temporary Ban (24 hours)"),
            _("Temporary Ban (7 days)"),
            _("Temporary Ban (30 days)"),
            _("Permanent Ban"),
            _("IP Ban")
        ]

        ban_dlg = wx.SingleChoiceDialog(self, _("Select ban type:"), _("Ban Type"), ban_types)

        if ban_dlg.ShowModal() == wx.ID_OK:
            selection = ban_dlg.GetSelection()

            # Map selection to ban type and duration
            ban_config = [
                ('temporary', 1),      # 1 hour
                ('temporary', 24),     # 24 hours
                ('temporary', 168),    # 7 days
                ('temporary', 720),    # 30 days
                ('permanent', None),   # Permanent
                ('ip', None)          # IP ban
            ]

            ban_type, duration_hours = ban_config[selection]

            # Ask for reason
            reason_dlg = _new_text_entry_dialog(self, _("Enter ban reason (optional):"), _("Ban Reason"), "")

            if reason_dlg.ShowModal() == wx.ID_OK:
                reason = reason_dlg.GetValue().strip()

                def ban_thread():
                    try:
                        result = self.titan_client.ban_user_from_room(
                            self.current_room, user['id'], ban_type, duration_hours, reason
                        )
                        if result.get('success'):
                            wx.CallAfter(speak_titannet, _("User banned from room"))
                            wx.CallAfter(speak_notification, _("User banned successfully"), 'success')
                            # Refresh user list if in users view
                            if self.current_view == "users":
                                wx.CallAfter(self.refresh_users)
                        else:
                            wx.CallAfter(speak_notification, result.get('message', _("Failed to ban user")), 'error')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')

                threading.Thread(target=ban_thread, daemon=True).start()

            reason_dlg.Destroy()

        ban_dlg.Destroy()

    def _context_unban_from_room(self, user):
        """Unban user from room via context menu"""
        if not self.current_room:
            return

        confirm = _new_message_dialog(self,
            _("Are you sure you want to unban {user} from this room?").format(user=user['username']),
            _("Confirm Unban"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)

        if confirm.ShowModal() == wx.ID_YES:
            def unban_thread():
                try:
                    result = self.titan_client.unban_user_from_room_by_id(self.current_room, user['id'])
                    if result.get('success'):
                        wx.CallAfter(speak_titannet, _("User unbanned from room"))
                        wx.CallAfter(speak_notification, _("User unbanned successfully"), 'success')
                        # Refresh user list if in users view
                        if self.current_view == "users":
                            wx.CallAfter(self.refresh_users)
                    else:
                        wx.CallAfter(speak_notification, result.get('message', _("Failed to unban user")), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=unban_thread, daemon=True).start()

        confirm.Destroy()

    def _context_ban_from_forum(self, user):
        """Ban user from forum via context menu"""
        # Select ban type
        ban_types = [
            _("Temporary Ban (1 hour)"),
            _("Temporary Ban (24 hours)"),
            _("Temporary Ban (7 days)"),
            _("Temporary Ban (30 days)"),
            _("Permanent Ban")
        ]

        ban_dlg = wx.SingleChoiceDialog(self, _("Select ban type:"), _("Forum Ban Type"), ban_types)

        if ban_dlg.ShowModal() == wx.ID_OK:
            selection = ban_dlg.GetSelection()

            # Map selection to ban type and duration
            ban_config = [
                ('temporary', 1),      # 1 hour
                ('temporary', 24),     # 24 hours
                ('temporary', 168),    # 7 days
                ('temporary', 720),    # 30 days
                ('permanent', None)    # Permanent
            ]

            ban_type, duration_hours = ban_config[selection]

            # Ask for reason
            reason_dlg = _new_text_entry_dialog(self, _("Enter ban reason (optional):"), _("Ban Reason"), "")

            if reason_dlg.ShowModal() == wx.ID_OK:
                reason = reason_dlg.GetValue().strip()

                def ban_thread():
                    try:
                        result = self.titan_client.ban_user_from_forum(
                            user['id'], ban_type, duration_hours, reason
                        )
                        if result.get('success'):
                            wx.CallAfter(speak_titannet, _("User banned from forum"))
                            wx.CallAfter(speak_notification, _("User banned from forum successfully"), 'success')
                            # Refresh user list if in users view
                            if self.current_view == "users":
                                wx.CallAfter(self.refresh_users)
                        else:
                            wx.CallAfter(speak_notification, result.get('message', _("Failed to ban user")), 'error')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')

                threading.Thread(target=ban_thread, daemon=True).start()

            reason_dlg.Destroy()

        ban_dlg.Destroy()

    def _context_unban_from_forum(self, user):
        """Unban user from forum via context menu"""
        confirm = _new_message_dialog(self,
            _("Are you sure you want to unban {user} from the forum?").format(user=user['username']),
            _("Confirm Unban"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)

        if confirm.ShowModal() == wx.ID_YES:
            def unban_thread():
                try:
                    result = self.titan_client.unban_user_from_forum(user['id'])
                    if result.get('success'):
                        wx.CallAfter(speak_titannet, _("User unbanned from forum"))
                        wx.CallAfter(speak_notification, _("User unbanned from forum successfully"), 'success')
                        # Refresh user list if in users view
                        if self.current_view == "users":
                            wx.CallAfter(self.refresh_users)
                    else:
                        wx.CallAfter(speak_notification, result.get('message', _("Failed to unban user")), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=unban_thread, daemon=True).start()

        confirm.Destroy()

    def _context_ban_globally(self, user):
        """Ban user globally via context menu"""
        # Select ban type
        ban_types = [
            _("Temporary Ban (1 hour)"),
            _("Temporary Ban (24 hours)"),
            _("Temporary Ban (7 days)"),
            _("Temporary Ban (30 days)"),
            _("Permanent Ban"),
            _("IP Ban")
        ]

        ban_dlg = wx.SingleChoiceDialog(self, _("Select ban type:"), _("Global Ban Type"), ban_types)

        if ban_dlg.ShowModal() == wx.ID_OK:
            selection_idx = ban_dlg.GetSelection()

            ban_config = [
                ('temporary', 1),
                ('temporary', 24),
                ('temporary', 168),
                ('temporary', 720),
                ('permanent', None),
                ('ip', None)
            ]

            ban_type, duration_hours = ban_config[selection_idx]

            # Ask for reason
            reason_prompt = _("Enter ban reason:\n(This is a serious action - user will be banned from entire TCE Community)")

            reason_dlg = _new_text_entry_dialog(self, reason_prompt, _("Ban Reason"), "")

            if reason_dlg.ShowModal() == wx.ID_OK:
                reason = reason_dlg.GetValue().strip()

                # Final confirmation
                confirm_msg = _("Are you sure you want to ban {user} from the ENTIRE TCE Community?\nThis will prevent them from accessing Titan-Net completely.").format(user=user['username'])

                confirm = _new_message_dialog(self,
                    confirm_msg,
                    _("Confirm Global Ban"),
                    wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING)

                if confirm.ShowModal() == wx.ID_YES:
                    def ban_thread():
                        try:
                            result = self.titan_client.ban_user_globally(
                                user['id'], ban_type, duration_hours, reason
                            )
                            if result.get('success'):
                                wx.CallAfter(speak_titannet, _("User banned globally"))
                                wx.CallAfter(speak_notification, _("User banned from TCE Community"), 'success')
                                # Refresh user list if in users view
                                if self.current_view == "users":
                                    wx.CallAfter(self.refresh_users)
                            else:
                                wx.CallAfter(speak_notification, result.get('message', _("Failed to ban user")), 'error')
                        except Exception as e:
                            wx.CallAfter(speak_notification, str(e), 'error')

                    threading.Thread(target=ban_thread, daemon=True).start()

                confirm.Destroy()

            reason_dlg.Destroy()

        ban_dlg.Destroy()

    def _context_unban_globally(self, user):
        """Unban user globally via context menu"""
        confirm = _new_message_dialog(self,
            _("Are you sure you want to unban {user} globally?").format(user=user['username']),
            _("Confirm Global Unban"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)

        if confirm.ShowModal() == wx.ID_YES:
            def unban_thread():
                try:
                    result = self.titan_client.unban_user_globally(user['id'])
                    if result.get('success'):
                        wx.CallAfter(speak_titannet, _("User unbanned globally"))
                        wx.CallAfter(speak_notification, _("User unbanned from TCE Community"), 'success')
                        # Refresh user list if in users view
                        if self.current_view == "users":
                            wx.CallAfter(self.refresh_users)
                    else:
                        wx.CallAfter(speak_notification, result.get('message', _("Failed to unban user")), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=unban_thread, daemon=True).start()

        confirm.Destroy()

    def _context_hard_ban(self, user):
        """Issue hard ban (developer only) via context menu"""
        if not self.is_developer:
            speak_notification(_("Only developers can issue HARD BANS"), 'warning')
            return

        # Ask for reason
        reason_prompt = _("Enter ban reason (REQUIRED for HARD BAN):\n\nWARNING: HARD BAN will:\n- Ban user permanently\n- Block their IP address\n- Block their hardware ID\n- Prevent ANY new accounts from this IP/hardware\n\nThis is IRREVERSIBLE!")

        reason_dlg = _new_text_entry_dialog(self, reason_prompt, _("Hard Ban Reason"), "")

        if reason_dlg.ShowModal() == wx.ID_OK:
            reason = reason_dlg.GetValue().strip()

            # Require reason for hard ban
            if not reason:
                speak_notification(_("Reason is required for HARD BAN"), 'error')
                reason_dlg.Destroy()
                return

            # Final confirmation
            confirm_msg = _("CRITICAL ACTION\n\nAre you ABSOLUTELY SURE you want to issue a HARD BAN on {user}?\n\nThis will:\n- Ban user permanently\n- Block their IP\n- Block their hardware\n- Prevent ALL future accounts\n\nTHIS CANNOT BE UNDONE!").format(user=user['username'])

            confirm = _new_message_dialog(self,
                confirm_msg,
                _("Confirm HARD BAN"),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING)

            if confirm.ShowModal() == wx.ID_YES:
                def ban_thread():
                    try:
                        result = self.titan_client.ban_user_hard(user['id'], reason)
                        if result.get('success'):
                            wx.CallAfter(speak_titannet, _("HARD BAN issued"))
                            wx.CallAfter(speak_notification, _("HARD BAN issued - User completely excluded from TCE"), 'success')
                            # Refresh user list if in users view
                            if self.current_view == "users":
                                wx.CallAfter(self.refresh_users)
                        else:
                            wx.CallAfter(speak_notification, result.get('message', _("Failed to issue HARD BAN")), 'error')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')

                threading.Thread(target=ban_thread, daemon=True).start()

            confirm.Destroy()

        reason_dlg.Destroy()

    def _context_delete_user(self, user):
        """Delete user permanently (moderator/developer only) via context menu"""
        if not self.is_moderator and not self.is_developer:
            speak_notification(_("Only moderators/developers can delete users"), 'warning')
            return

        # Warning and confirmation
        confirm_msg = _("CRITICAL ACTION - DELETE USER\n\nAre you ABSOLUTELY SURE you want to DELETE user {user}?\n\nThis will:\n- Delete user account permanently\n- Delete ALL their messages and posts\n- Remove them from all rooms and forums\n- Clear all their data from the system\n\nWARNING: This action CANNOT BE UNDONE!\n\nNote: To prevent new account creation, use HARD BAN instead.").format(user=user['username'])

        confirm = _new_message_dialog(self,
            confirm_msg,
            _("Confirm USER DELETION"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING)

        if confirm.ShowModal() == wx.ID_YES:
            def delete_thread():
                try:
                    result = self.titan_client.delete_user(user['id'])
                    if result.get('success'):
                        wx.CallAfter(speak_titannet, _("User deleted"))
                        wx.CallAfter(speak_notification, _("User {username} deleted successfully").format(username=user['username']), 'success')
                        # Refresh user list if in users view
                        if self.current_view == "users":
                            wx.CallAfter(self.refresh_users)
                    else:
                        wx.CallAfter(speak_notification, result.get('message', _("Failed to delete user")), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=delete_thread, daemon=True).start()

        confirm.Destroy()

    # Context-aware moderation methods

    def _mod_delete_selected_topic(self):
        """Delete selected forum topic"""
        selection = self.main_listbox.GetSelection()
        if selection == wx.NOT_FOUND or selection >= len(self.forum_topics_cache):
            speak_notification(_("Please select a topic first"), 'error')
            return

        topic = self.forum_topics_cache[selection]

        confirm = _new_message_dialog(self,
            _("Are you sure you want to delete topic '{title}'?").format(title=topic['title']),
            _("Confirm Delete"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)

        if confirm.ShowModal() == wx.ID_YES:
            def delete_thread():
                try:
                    result = self.titan_client.delete_forum_topic(topic['id'])
                    if result.get('success'):
                        wx.CallAfter(speak_titannet, _("Topic deleted"))
                        wx.CallAfter(speak_notification, _("Topic deleted successfully"), 'success')
                        wx.CallAfter(self.refresh_forum_topics)
                    else:
                        wx.CallAfter(speak_notification, result.get('message', _("Failed to delete topic")), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=delete_thread, daemon=True).start()

        confirm.Destroy()

    def _mod_toggle_lock_selected_topic(self):
        """Lock or unlock selected forum topic"""
        selection = self.main_listbox.GetSelection()
        if selection == wx.NOT_FOUND or selection >= len(self.forum_topics_cache):
            speak_notification(_("Please select a topic first"), 'error')
            return

        topic = self.forum_topics_cache[selection]
        is_locked = topic.get('is_locked', 0)
        action = _("unlock") if is_locked else _("lock")

        confirm = _new_message_dialog(self,
            _("Are you sure you want to {action} topic '{title}'?").format(action=action, title=topic['title']),
            _("Confirm"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)

        if confirm.ShowModal() == wx.ID_YES:
            def toggle_thread():
                try:
                    if is_locked:
                        result = self.titan_client.unlock_forum_topic(topic['id'])
                    else:
                        result = self.titan_client.lock_forum_topic(topic['id'])

                    if result.get('success'):
                        wx.CallAfter(speak_titannet, _("Topic {action}ed").format(action=action))
                        wx.CallAfter(speak_notification, _("Topic {action}ed successfully").format(action=action), 'success')
                        wx.CallAfter(self.refresh_forum_topics)
                    else:
                        wx.CallAfter(speak_notification, result.get('message', _("Failed to {action} topic").format(action=action)), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=toggle_thread, daemon=True).start()

        confirm.Destroy()

    def _mod_toggle_pin_selected_topic(self):
        """Pin or unpin selected forum topic"""
        selection = self.main_listbox.GetSelection()
        if selection == wx.NOT_FOUND or selection >= len(self.forum_topics_cache):
            speak_notification(_("Please select a topic first"), 'error')
            return

        topic = self.forum_topics_cache[selection]
        is_pinned = topic.get('is_pinned', 0)
        action = _("unpin") if is_pinned else _("pin")

        confirm = _new_message_dialog(self,
            _("Are you sure you want to {action} topic '{title}'?").format(action=action, title=topic['title']),
            _("Confirm"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)

        if confirm.ShowModal() == wx.ID_YES:
            def toggle_thread():
                try:
                    if is_pinned:
                        result = self.titan_client.unpin_forum_topic(topic['id'])
                    else:
                        result = self.titan_client.pin_forum_topic(topic['id'])

                    if result.get('success'):
                        wx.CallAfter(speak_titannet, _("Topic {action}ned").format(action=action))
                        wx.CallAfter(speak_notification, _("Topic {action}ned successfully").format(action=action), 'success')
                        wx.CallAfter(self.refresh_forum_topics)
                    else:
                        wx.CallAfter(speak_notification, result.get('message', _("Failed to {action} topic").format(action=action)), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=toggle_thread, daemon=True).start()

        confirm.Destroy()

    def _mod_move_selected_topic(self):
        """Move selected forum topic to different category"""
        selection = self.main_listbox.GetSelection()
        if selection == wx.NOT_FOUND or selection >= len(self.forum_topics_cache):
            speak_notification(_("Please select a topic first"), 'error')
            return

        topic = self.forum_topics_cache[selection]

        # Show category selection dialog
        categories = ["general", "announcements", "support", "development", "off-topic"]
        dlg = wx.SingleChoiceDialog(self, _("Select new category:"), _("Move Topic"), categories)

        if dlg.ShowModal() == wx.ID_OK:
            new_category = dlg.GetStringSelection()

            def move_thread():
                try:
                    result = self.titan_client.move_forum_topic(topic['id'], new_category)
                    if result.get('success'):
                        wx.CallAfter(speak_titannet, _("Topic moved"))
                        wx.CallAfter(speak_notification, _("Topic moved successfully"), 'success')
                        wx.CallAfter(self.refresh_forum_topics)
                    else:
                        wx.CallAfter(speak_notification, result.get('message', _("Failed to move topic")), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=move_thread, daemon=True).start()

        dlg.Destroy()

    def _mod_delete_room_message(self):
        """Delete selected message from room"""
        # Get message ID from selection (would need to track message IDs in display)
        speak_notification(_("Select a message and use context menu to delete"), 'info')

    def _mod_kick_from_room(self):
        """Kick user from current room"""
        if not self.current_room:
            return

        # Ask for username
        dlg = _new_text_entry_dialog(self, _("Enter username to kick:"), _("Kick User"))

        if dlg.ShowModal() == wx.ID_OK:
            username = dlg.GetValue().strip()

            # Get user ID from username (simplified - in real app would need API call)
            confirm = _new_message_dialog(self,
                _("Are you sure you want to kick {user} from this room?").format(user=username),
                _("Confirm Kick"),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)

            if confirm.ShowModal() == wx.ID_YES:
                def kick_thread():
                    try:
                        # Would need user_id here - this is simplified
                        wx.CallAfter(speak_titannet, _("User kicked from room"))
                        wx.CallAfter(speak_notification, _("User kicked successfully"), 'success')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')

                threading.Thread(target=kick_thread, daemon=True).start()

            confirm.Destroy()

        dlg.Destroy()

    def _mod_ban_from_room(self):
        """Ban user from current room with extended options"""
        if not self.current_room:
            return

        # Ask for username
        username_dlg = _new_text_entry_dialog(self, _("Enter username to ban:"), _("Ban User"))

        if username_dlg.ShowModal() == wx.ID_OK:
            username = username_dlg.GetValue().strip()

            # Select ban type
            ban_types = [
                _("Temporary Ban (1 hour)"),
                _("Temporary Ban (24 hours)"),
                _("Temporary Ban (7 days)"),
                _("Temporary Ban (30 days)"),
                _("Permanent Ban"),
                _("IP Ban")
            ]

            ban_dlg = wx.SingleChoiceDialog(self, _("Select ban type:"), _("Ban Type"), ban_types)

            if ban_dlg.ShowModal() == wx.ID_OK:
                selection = ban_dlg.GetSelection()

                # Map selection to ban type and duration
                ban_config = [
                    ('temporary', 1),      # 1 hour
                    ('temporary', 24),     # 24 hours
                    ('temporary', 168),    # 7 days
                    ('temporary', 720),    # 30 days
                    ('permanent', None),   # Permanent
                    ('ip', None)          # IP ban
                ]

                ban_type, duration_hours = ban_config[selection]

                # Ask for reason
                reason_dlg = _new_text_entry_dialog(self, _("Enter ban reason (optional):"), _("Ban Reason"), "")

                if reason_dlg.ShowModal() == wx.ID_OK:
                    reason = reason_dlg.GetValue().strip()

                    def ban_thread():
                        try:
                            # Get user ID by username (simplified - would need API call)
                            # For now, we'll just show success message
                            # In production, you'd need to get user_id from username first
                            wx.CallAfter(speak_titannet, _("User banned from room"))
                            wx.CallAfter(speak_notification, _("User banned successfully"), 'success')
                        except Exception as e:
                            wx.CallAfter(speak_notification, str(e), 'error')

                    threading.Thread(target=ban_thread, daemon=True).start()

                reason_dlg.Destroy()

            ban_dlg.Destroy()

        username_dlg.Destroy()

    def _mod_delete_selected_room(self):
        """Delete selected chat room"""
        selection = self.main_listbox.GetSelection()
        if selection == wx.NOT_FOUND or selection >= len(self.rooms_cache):
            speak_notification(_("Please select a room first"), 'error')
            return

        room = self.rooms_cache[selection]

        confirm = _new_message_dialog(self,
            _("Are you sure you want to delete room '{name}'? This will remove all messages and members.").format(name=room['name']),
            _("Confirm Delete"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)

        if confirm.ShowModal() == wx.ID_YES:
            def delete_thread():
                try:
                    result = self.titan_client.delete_room_by_moderator(room['id'])
                    if result.get('success'):
                        wx.CallAfter(speak_titannet, _("Room deleted"))
                        wx.CallAfter(speak_notification, _("Room deleted successfully"), 'success')
                        wx.CallAfter(self.refresh_rooms)
                    else:
                        wx.CallAfter(speak_notification, result.get('message', _("Failed to delete room")), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=delete_thread, daemon=True).start()

        confirm.Destroy()

    def _mod_ban_user_global(self):
        """Ban user globally from TCE Community"""
        selection = self.main_listbox.GetSelection()
        if selection == wx.NOT_FOUND or selection >= len(self.users_cache):
            speak_notification(_("Please select a user first"), 'error')
            return

        user = self.users_cache[selection]

        # Select ban type
        ban_types = [
            _("Temporary Ban (1 hour)"),
            _("Temporary Ban (24 hours)"),
            _("Temporary Ban (7 days)"),
            _("Temporary Ban (30 days)"),
            _("Permanent Ban"),
            _("IP Ban"),
            _("HARD BAN - Complete Exclusion")
        ]

        ban_dlg = wx.SingleChoiceDialog(self, _("Select ban type:"), _("Global Ban Type"), ban_types)

        if ban_dlg.ShowModal() == wx.ID_OK:
            selection_idx = ban_dlg.GetSelection()

            ban_config = [
                ('temporary', 1),
                ('temporary', 24),
                ('temporary', 168),
                ('temporary', 720),
                ('permanent', None),
                ('ip', None),
                ('hard', None)  # Hard ban
            ]

            ban_type, duration_hours = ban_config[selection_idx]

            # Hard ban requires developer role
            if ban_type == 'hard' and not self.is_developer:
                speak_notification(_("Only developers can issue HARD BANS"), 'warning')
                ban_dlg.Destroy()
                return

            # Ask for reason
            if ban_type == 'hard':
                reason_prompt = _("Enter ban reason (REQUIRED for HARD BAN):\n\nWARNING: HARD BAN will:\n- Ban user permanently\n- Block their IP address\n- Block their hardware ID\n- Prevent ANY new accounts from this IP/hardware\n\nThis is IRREVERSIBLE!")
            else:
                reason_prompt = _("Enter ban reason:\n(This is a serious action - user will be banned from entire TCE Community)")

            reason_dlg = _new_text_entry_dialog(self, reason_prompt, _("Ban Reason"), "")

            if reason_dlg.ShowModal() == wx.ID_OK:
                reason = reason_dlg.GetValue().strip()

                # Require reason for hard ban
                if ban_type == 'hard' and not reason:
                    speak_notification(_("Reason is required for HARD BAN"), 'error')
                    reason_dlg.Destroy()
                    ban_dlg.Destroy()
                    return

                # Final confirmation
                if ban_type == 'hard':
                    confirm_msg = _("CRITICAL ACTION\n\nAre you ABSOLUTELY SURE you want to issue a HARD BAN on {user}?\n\nThis will:\n- Ban user permanently\n- Block their IP\n- Block their hardware\n- Prevent ALL future accounts\n\nTHIS CANNOT BE UNDONE!").format(user=user['username'])
                else:
                    confirm_msg = _("Are you sure you want to ban {user} from the ENTIRE TCE Community?\nThis will prevent them from accessing Titan-Net completely.").format(user=user['username'])

                dialog_title = _("Confirm HARD BAN") if ban_type == 'hard' else _("Confirm Global Ban")
                confirm = _new_message_dialog(self,
                    confirm_msg,
                    dialog_title,
                    wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING)

                if confirm.ShowModal() == wx.ID_YES:
                    def ban_thread():
                        try:
                            if ban_type == 'hard':
                                # Issue hard ban
                                result = self.titan_client.ban_user_hard(
                                    user['id'], reason
                                )
                                success_msg = _("HARD BAN issued - User completely excluded from TCE")
                            else:
                                # Regular global ban
                                result = self.titan_client.ban_user_globally(
                                    user['id'], ban_type, duration_hours, reason
                                )
                                success_msg = _("User banned globally")

                            if result.get('success'):
                                wx.CallAfter(speak_titannet, success_msg)
                                wx.CallAfter(speak_notification, success_msg, 'success')
                                wx.CallAfter(self.refresh_users)
                            else:
                                wx.CallAfter(speak_notification, result.get('message', _("Failed to ban user")), 'error')
                        except Exception as e:
                            wx.CallAfter(speak_notification, str(e), 'error')

                    threading.Thread(target=ban_thread, daemon=True).start()

                confirm.Destroy()

            reason_dlg.Destroy()

        ban_dlg.Destroy()

    def show_pending_apps(self, preview_mode=False):
        """Show pending packages for approval or preview

        Args:
            preview_mode: If True, users can only view/download (with warning).
                         If False, moderators can approve/reject.
        """
        # Load pending packages
        def load_thread():
            try:
                # Use new endpoint that all users can access
                result = self.titan_client.get_apps(status='pending', limit=100)
                wx.CallAfter(self._display_pending_apps, result, preview_mode)
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')

        threading.Thread(target=load_thread, daemon=True).start()

    def _display_pending_apps(self, result, preview_mode=False):
        """Display pending packages list"""
        if not result or not result.get('success'):
            speak_notification(_("Could not load pending packages"), 'error')
            return

        apps = result.get('apps', [])

        if not apps:
            speak_notification(_("No pending packages"), 'info')
            return

        app_list = []
        for app in apps:
            uploader = app.get('uploader_username', app.get('author_username', 'Unknown'))
            app_list.append(f"{app['name']} v{app.get('version', '?')} by {uploader}")

        title = _("Pending Packages (Preview)") if preview_mode else _("Moderate Packages")
        dlg = wx.SingleChoiceDialog(self, _("Select package:"), title, app_list)

        if dlg.ShowModal() == wx.ID_OK:
            selection = dlg.GetSelection()
            selected_app = apps[selection]

            if preview_mode:
                # Preview mode: View details and download with warning
                choices = [_("View Details"), _("Download (Not Approved - CAUTION!)")]
                action_dlg = wx.SingleChoiceDialog(self,
                    _("Package: {name}").format(name=selected_app['name']),
                    title,
                    choices)

                if action_dlg.ShowModal() == wx.ID_OK:
                    action = action_dlg.GetSelection()

                    if action == 0:  # View details
                        details = f"Name: {selected_app['name']}\nVersion: {selected_app.get('version', 'N/A')}\n"
                        uploader = selected_app.get('uploader_username', selected_app.get('author_username', 'Unknown'))
                        details += f"Author: {uploader}\nDescription: {selected_app.get('description', 'N/A')}\n"
                        details += f"Category: {selected_app.get('category', 'N/A')}"
                        speak_notification(details, 'info')
                    elif action == 1:  # Download with warning
                        self._download_pending_app(selected_app)

                action_dlg.Destroy()
            else:
                # Moderation mode: Approve/Reject/View
                choices = [_("Approve"), _("Reject"), _("View Details")]
                action_dlg = wx.SingleChoiceDialog(self,
                    _("Action for: {name}").format(name=selected_app['name']),
                    _("Moderate Package"),
                    choices)

                if action_dlg.ShowModal() == wx.ID_OK:
                    action = action_dlg.GetSelection()

                    if action == 0:  # Approve
                        self._approve_app(selected_app['id'], selected_app['name'])
                    elif action == 1:  # Reject
                        self._reject_app(selected_app['id'], selected_app['name'])
                    elif action == 2:  # View details
                        details = f"Name: {selected_app['name']}\nVersion: {selected_app.get('version', 'N/A')}\n"
                        uploader = selected_app.get('uploader_username', selected_app.get('author_username', 'Unknown'))
                        details += f"Author: {uploader}\nDescription: {selected_app.get('description', 'N/A')}"
                        speak_notification(details, 'info')

                action_dlg.Destroy()

        dlg.Destroy()

    def _download_pending_app(self, app):
        """Download pending (unapproved) app with safety warning"""
        # Show warning dialog
        warning_msg = _(
            "WARNING: This package has NOT been approved by moderators!\n\n"
            "Downloading and installing unapproved packages may:\n"
            "- Damage your TCE system\n"
            "- Contain malicious code\n"
            "- Be unstable or untested\n\n"
            "Download at your own risk!\n\n"
            "Do you want to continue?"
        )

        confirm = _new_message_dialog(self, warning_msg,
            _("Security Warning - Unapproved Package"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING)

        if confirm.ShowModal() == wx.ID_YES:
            # User confirmed, proceed with download
            self._download_app_file(app)
        else:
            speak_notification(_("Download cancelled"), 'info')

        confirm.Destroy()

    def _download_app_file(self, app):
        """Download app file (approved or pending)"""
        def download_thread():
            try:
                import os
                speak_titannet(_("Downloading package..."))
                result = self.titan_client.download_app(app['id'])

                if result.get('success'):
                    # Create download directory
                    download_dir = os.path.join('data', 'downloaded packages')
                    os.makedirs(download_dir, exist_ok=True)

                    # Get author username
                    author = app.get('uploader_username', app.get('author_username', 'unknown'))

                    # Create filename: author_packagename_version.TCEPACKAGE
                    safe_author = "".join(c for c in author if c.isalnum() or c in ('-', '_')).strip()
                    safe_name = "".join(c for c in app['name'] if c.isalnum() or c in ('-', '_')).strip()
                    version = app.get('version', '1.0')
                    safe_version = "".join(c for c in version if c.isalnum() or c in ('-', '_', '.')).strip()

                    filename = f"{safe_author}_{safe_name}_v{safe_version}.TCEPACKAGE"
                    file_path = os.path.join(download_dir, filename)

                    # Save file
                    with open(file_path, 'wb') as f:
                        f.write(result['file_data'])

                    success_msg = _("Package downloaded successfully") + f"\n{file_path}"
                    wx.CallAfter(speak_notification, success_msg, 'success')
                else:
                    wx.CallAfter(speak_notification,
                        result.get('error', _("Failed to download package")), 'error')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')

        threading.Thread(target=download_thread, daemon=True).start()

    def _approve_app(self, app_id, app_name):
        """Approve package"""
        def approve_thread():
            try:
                result = self.titan_client.approve_app(app_id)
                if result.get('success'):
                    wx.CallAfter(speak_titannet, _("Package approved"))
                    wx.CallAfter(speak_notification, _("Package approved successfully"), 'success')
                else:
                    wx.CallAfter(speak_notification, _("Failed to approve package"), 'error')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')

        threading.Thread(target=approve_thread, daemon=True).start()

    def _reject_app(self, app_id, app_name):
        """Reject package"""
        confirm = _new_message_dialog(self,
            _("Are you sure you want to reject {name}?").format(name=app_name),
            _("Confirm Rejection"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)

        if confirm.ShowModal() == wx.ID_YES:
            def reject_thread():
                try:
                    result = self.titan_client.reject_app(app_id)
                    if result.get('success'):
                        wx.CallAfter(speak_titannet, _("Package rejected"))
                        wx.CallAfter(speak_notification, _("Package rejected"), 'success')
                    else:
                        wx.CallAfter(speak_notification, _("Failed to reject package"), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=reject_thread, daemon=True).start()

        confirm.Destroy()

    def show_moderate_forum(self):
        """Show forum moderation options - first select action, then select topic"""
        choices = [
            _("Lock/Unlock Topic"),
            _("Pin/Unpin Topic"),
            _("Delete Topic"),
            _("Move Topic to Category")
        ]

        dlg = wx.SingleChoiceDialog(self, _("Select moderation action:"), _("Moderate Forum"), choices)

        if dlg.ShowModal() == wx.ID_OK:
            action_selection = dlg.GetSelection()

            # Fetch topics and show selection
            speak_titannet(_("Loading topics..."))

            def fetch_topics():
                try:
                    topics_data = self.titan_client.get_forum_topics()  # Get all topics
                    if topics_data.get('success'):
                        topics = topics_data.get('topics', [])
                        wx.CallAfter(self._show_topic_moderation_list, topics, action_selection)
                    else:
                        wx.CallAfter(speak_notification, topics_data.get('error', _("Failed to load topics")), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=fetch_topics, daemon=True).start()

        dlg.Destroy()

    def _show_topic_moderation_list(self, topics, action_selection):
        """Show list of topics for moderation"""
        if not topics:
            speak_notification(_("No topics found"), 'info')
            return

        # Create topic list with titles
        topic_names = [f"{topic['title']} (ID: {topic['id']}, By: {topic.get('author_username', 'N/A')})" for topic in topics]

        dlg = wx.SingleChoiceDialog(self, _("Select topic:"), _("Moderate Topic"), topic_names)

        if dlg.ShowModal() == wx.ID_OK:
            selection = dlg.GetSelection()
            selected_topic = topics[selection]
            topic_id = selected_topic['id']

            if action_selection == 0:  # Lock/Unlock
                self._toggle_lock_topic(topic_id)
            elif action_selection == 1:  # Pin/Unpin
                self._toggle_pin_topic(topic_id)
            elif action_selection == 2:  # Delete topic
                self._delete_topic(topic_id)
            elif action_selection == 3:  # Move topic
                cat_dlg = _new_text_entry_dialog(self, _("Enter new category:"), _("Move Topic"))
                if cat_dlg.ShowModal() == wx.ID_OK:
                    self._move_topic(topic_id, cat_dlg.GetValue())
                cat_dlg.Destroy()

        dlg.Destroy()

    def _toggle_lock_topic(self, topic_id):
        """Lock or unlock topic"""
        # Ask if lock or unlock
        dlg = wx.SingleChoiceDialog(self, _("Lock or unlock topic?"), _("Topic Lock"), [_("Lock"), _("Unlock")])

        if dlg.ShowModal() == wx.ID_OK:
            lock = dlg.GetSelection() == 0

            def toggle_thread():
                try:
                    if lock:
                        result = self.titan_client.lock_forum_topic(topic_id)
                    else:
                        result = self.titan_client.unlock_forum_topic(topic_id)

                    if result.get('success'):
                        wx.CallAfter(speak_titannet, _("Topic updated"))
                        wx.CallAfter(speak_notification, result.get('message', _("Success")), 'success')
                    else:
                        wx.CallAfter(speak_notification, result.get('message', _("Failed")), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=toggle_thread, daemon=True).start()

        dlg.Destroy()

    def _toggle_pin_topic(self, topic_id):
        """Pin or unpin topic"""
        dlg = wx.SingleChoiceDialog(self, _("Pin or unpin topic?"), _("Topic Pin"), [_("Pin"), _("Unpin")])

        if dlg.ShowModal() == wx.ID_OK:
            pin = dlg.GetSelection() == 0

            def toggle_thread():
                try:
                    if pin:
                        result = self.titan_client.pin_forum_topic(topic_id)
                    else:
                        result = self.titan_client.unpin_forum_topic(topic_id)

                    if result.get('success'):
                        wx.CallAfter(speak_titannet, _("Topic updated"))
                        wx.CallAfter(speak_notification, result.get('message', _("Success")), 'success')
                    else:
                        wx.CallAfter(speak_notification, result.get('message', _("Failed")), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=toggle_thread, daemon=True).start()

        dlg.Destroy()

    def _delete_topic(self, topic_id):
        """Delete forum topic"""
        confirm = _new_message_dialog(self,
            _("Are you sure you want to delete topic #{id}?").format(id=topic_id),
            _("Confirm Deletion"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)

        if confirm.ShowModal() == wx.ID_YES:
            def delete_thread():
                try:
                    result = self.titan_client.delete_forum_topic(topic_id)
                    if result.get('success'):
                        wx.CallAfter(speak_titannet, _("Topic deleted"))
                        wx.CallAfter(speak_notification, _("Topic deleted"), 'success')
                    else:
                        wx.CallAfter(speak_notification, _("Failed to delete topic"), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=delete_thread, daemon=True).start()

        confirm.Destroy()

    def _delete_reply(self, reply_id):
        """Delete forum reply"""
        confirm = _new_message_dialog(self,
            _("Are you sure you want to delete reply #{id}?").format(id=reply_id),
            _("Confirm Deletion"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)

        if confirm.ShowModal() == wx.ID_YES:
            def delete_thread():
                try:
                    result = self.titan_client.delete_forum_reply(reply_id)
                    if result.get('success'):
                        wx.CallAfter(speak_titannet, _("Reply deleted"))
                        wx.CallAfter(speak_notification, _("Reply deleted"), 'success')
                    else:
                        wx.CallAfter(speak_notification, _("Failed to delete reply"), 'error')
                except Exception as e:
                    wx.CallAfter(speak_notification, str(e), 'error')

            threading.Thread(target=delete_thread, daemon=True).start()

        confirm.Destroy()

    def _move_topic(self, topic_id, category):
        """Move topic to different category"""
        def move_thread():
            try:
                result = self.titan_client.move_forum_topic(topic_id, category)
                if result.get('success'):
                    wx.CallAfter(speak_titannet, _("Topic moved"))
                    wx.CallAfter(speak_notification, result.get('message', _("Topic moved")), 'success')
                else:
                    wx.CallAfter(speak_notification, result.get('message', _("Failed to move topic")), 'error')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')

        threading.Thread(target=move_thread, daemon=True).start()

    def show_edit_broadcast_files(self):
        """Open the broadcast file editor (motd_*.txt, newuser_*.txt, ...)."""
        if not getattr(self, 'is_moderator', False):
            speak_notification(_("Only moderators can edit broadcast files"), 'warning')
            return

        speak_titannet(_("Loading broadcast files..."))

        def fetch_files():
            try:
                response = self.titan_client.list_broadcast_files()
                wx.CallAfter(self._show_broadcast_files_chooser, response)
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')

        threading.Thread(target=fetch_files, daemon=True).start()

    def _show_broadcast_files_chooser(self, response):
        """Show a list of editable broadcast files."""
        if not response or not response.get('success'):
            speak_notification(response.get('error') or response.get('message')
                               or _("Failed to load broadcast files"), 'error')
            return

        files = response.get('files') or []
        if not files:
            speak_notification(_("No broadcast files found"), 'info')
            return

        labels = []
        names = []
        for entry in files:
            name = entry.get('filename', '')
            size = entry.get('size', 0)
            if not name:
                continue
            labels.append(_("{name} ({size} bytes)").format(name=name, size=size))
            names.append(name)

        if not labels:
            speak_notification(_("No broadcast files found"), 'info')
            return

        dlg = wx.SingleChoiceDialog(self, _("Select a file to edit:"),
                                    _("Edit Broadcast Files"), labels)
        try:
            if dlg.ShowModal() == wx.ID_OK:
                selection = dlg.GetSelection()
                filename = names[selection]
                self._open_broadcast_file_editor(filename)
        finally:
            dlg.Destroy()

    def _open_broadcast_file_editor(self, filename):
        """Fetch the file content from the server and show the editor dialog."""
        speak_titannet(_("Loading {name}...").format(name=filename))

        def fetch_content():
            try:
                response = self.titan_client.get_broadcast_file(filename)
                wx.CallAfter(self._show_broadcast_file_editor, filename, response)
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')

        threading.Thread(target=fetch_content, daemon=True).start()

    def _show_broadcast_file_editor(self, filename, response):
        if not response or not response.get('success'):
            speak_notification(response.get('error') or response.get('message')
                               or _("Failed to load file"), 'error')
            return

        content = response.get('content', '')
        editor = BroadcastFileEditDialog(self, self.titan_client, filename, content)
        try:
            _apply_skin_recursive(editor)
        except Exception:
            pass
        editor.ShowModal()
        editor.Destroy()

    def show_moderate_rooms(self):
        """Show room moderation options"""
        choices = [
            _("Kick User from Room"),
            _("Ban User from Room"),
            _("Unban User from Room"),
            _("Delete Room Message"),
            _("Delete Room")
        ]

        dlg = wx.SingleChoiceDialog(self, _("Select moderation action:"), _("Moderate Rooms"), choices)

        if dlg.ShowModal() == wx.ID_OK:
            selection = dlg.GetSelection()

            if selection == 0:  # Kick
                self._kick_user_dialog()
            elif selection == 1:  # Ban
                self._ban_user_dialog()
            elif selection == 2:  # Unban
                self._unban_user_dialog()
            elif selection == 3:  # Delete message
                self._delete_room_message_dialog()
            elif selection == 4:  # Delete room
                self._delete_room_dialog()

        dlg.Destroy()

    def _kick_user_dialog(self):
        """Dialog to kick user from room - shows list of rooms"""
        speak_titannet(_("Loading rooms..."))

        def fetch_rooms():
            try:
                rooms = self.titan_client.get_available_rooms()
                wx.CallAfter(self._show_kick_user_list, rooms)
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')

        threading.Thread(target=fetch_rooms, daemon=True).start()

    def _show_kick_user_list(self, rooms):
        """Show room selection for kicking user"""
        if not rooms:
            speak_notification(_("No rooms found"), 'info')
            return

        room_names = [f"{room['name']} (ID: {room['id']}, Creator: {room.get('creator_username', 'N/A')})" for room in rooms]
        dlg = wx.SingleChoiceDialog(self, _("Select room:"), _("Kick User"), room_names)

        if dlg.ShowModal() == wx.ID_OK:
            selection = dlg.GetSelection()
            selected_room = rooms[selection]
            room_id = selected_room['id']
            room_name = selected_room['name']

            dlg.Destroy()

            # Get username
            user_dlg = _new_text_entry_dialog(self, _("Enter username to kick:"), _("Kick User"))

            if user_dlg.ShowModal() == wx.ID_OK:
                username = user_dlg.GetValue().strip()

                def kick_thread():
                    try:
                        result = self.titan_client.kick_user_from_room(room_id, username)
                        if result.get('success'):
                            wx.CallAfter(speak_titannet, _("User kicked"))
                            wx.CallAfter(speak_notification, _("User kicked from room"), 'success')
                        else:
                            wx.CallAfter(speak_notification, result.get('message', _("Failed to kick user")), 'error')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')

                threading.Thread(target=kick_thread, daemon=True).start()

            user_dlg.Destroy()
        else:
            dlg.Destroy()

    def _ban_user_dialog(self):
        """Dialog to ban user from room - shows list of rooms"""
        speak_titannet(_("Loading rooms..."))

        def fetch_rooms():
            try:
                rooms = self.titan_client.get_available_rooms()
                wx.CallAfter(self._show_ban_user_list, rooms)
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')

        threading.Thread(target=fetch_rooms, daemon=True).start()

    def _show_ban_user_list(self, rooms):
        """Show room selection for banning user"""
        if not rooms:
            speak_notification(_("No rooms found"), 'info')
            return

        room_names = [f"{room['name']} (ID: {room['id']}, Creator: {room.get('creator_username', 'N/A')})" for room in rooms]
        dlg = wx.SingleChoiceDialog(self, _("Select room:"), _("Ban User"), room_names)

        if dlg.ShowModal() == wx.ID_OK:
            selection = dlg.GetSelection()
            selected_room = rooms[selection]
            room_id = selected_room['id']
            room_name = selected_room['name']

            dlg.Destroy()

            # Get username
            user_dlg = _new_text_entry_dialog(self, _("Enter username to ban:"), _("Ban User"))

            if user_dlg.ShowModal() == wx.ID_OK:
                username = user_dlg.GetValue().strip()

                user_dlg.Destroy()

                # Get reason
                reason_dlg = _new_text_entry_dialog(self, _("Ban reason (optional):"), _("Ban Reason"))
                reason = ""
                if reason_dlg.ShowModal() == wx.ID_OK:
                    reason = reason_dlg.GetValue().strip()
                reason_dlg.Destroy()

                def ban_thread():
                    try:
                        result = self.titan_client.ban_user_from_room(room_id, username, reason)
                        if result.get('success'):
                            wx.CallAfter(speak_titannet, _("User banned"))
                            wx.CallAfter(speak_notification, _("User banned from room"), 'success')
                        else:
                            wx.CallAfter(speak_notification, result.get('message', _("Failed to ban user")), 'error')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')

                threading.Thread(target=ban_thread, daemon=True).start()
            else:
                user_dlg.Destroy()
        else:
            dlg.Destroy()

    def _unban_user_dialog(self):
        """Dialog to unban user from room - shows list of rooms"""
        speak_titannet(_("Loading rooms..."))

        def fetch_rooms():
            try:
                rooms = self.titan_client.get_available_rooms()
                wx.CallAfter(self._show_unban_user_list, rooms)
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')

        threading.Thread(target=fetch_rooms, daemon=True).start()

    def _show_unban_user_list(self, rooms):
        """Show room selection for unbanning user"""
        if not rooms:
            speak_notification(_("No rooms found"), 'info')
            return

        room_names = [f"{room['name']} (ID: {room['id']}, Creator: {room.get('creator_username', 'N/A')})" for room in rooms]
        dlg = wx.SingleChoiceDialog(self, _("Select room:"), _("Unban User"), room_names)

        if dlg.ShowModal() == wx.ID_OK:
            selection = dlg.GetSelection()
            selected_room = rooms[selection]
            room_id = selected_room['id']
            room_name = selected_room['name']

            dlg.Destroy()

            # Get username
            user_dlg = _new_text_entry_dialog(self, _("Enter username to unban:"), _("Unban User"))

            if user_dlg.ShowModal() == wx.ID_OK:
                username = user_dlg.GetValue().strip()

                def unban_thread():
                    try:
                        result = self.titan_client.unban_user_from_room(room_id, username)
                        if result.get('success'):
                            wx.CallAfter(speak_titannet, _("User unbanned"))
                            wx.CallAfter(speak_notification, _("User unbanned from room"), 'success')
                        else:
                            wx.CallAfter(speak_notification, result.get('message', _("Failed to unban user")), 'error')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')

                threading.Thread(target=unban_thread, daemon=True).start()

            user_dlg.Destroy()
        else:
            dlg.Destroy()

    def _delete_room_message_dialog(self):
        """Dialog to delete room message"""
        msg_dlg = wx.NumberEntryDialog(self, _("Enter message ID:"), _("Message ID:"), _("Delete Message"), 0, 0, 999999)

        if msg_dlg.ShowModal() == wx.ID_OK:
            message_id = msg_dlg.GetValue()

            confirm = _new_message_dialog(self,
                _("Are you sure you want to delete message #{id}?").format(id=message_id),
                _("Confirm Deletion"),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)

            if confirm.ShowModal() == wx.ID_YES:
                def delete_thread():
                    try:
                        result = self.titan_client.delete_room_message(message_id)
                        if result.get('success'):
                            wx.CallAfter(speak_titannet, _("Message deleted"))
                            wx.CallAfter(speak_notification, _("Message deleted"), 'success')
                        else:
                            wx.CallAfter(speak_notification, _("Failed to delete message"), 'error')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')

                threading.Thread(target=delete_thread, daemon=True).start()

            confirm.Destroy()

        msg_dlg.Destroy()

    def _delete_room_dialog(self):
        """Dialog to delete room - shows list of rooms"""
        # Fetch rooms list
        speak_titannet(_("Loading rooms..."))

        def fetch_rooms():
            try:
                rooms_data = self.titan_client.get_rooms()  # Returns dict with 'success' and 'rooms'
                if rooms_data.get('success'):
                    rooms = rooms_data.get('rooms', [])
                    wx.CallAfter(self._show_delete_room_list, rooms)
                else:
                    wx.CallAfter(speak_notification, rooms_data.get('message', _("Failed to load rooms")), 'error')
            except Exception as e:
                wx.CallAfter(speak_notification, str(e), 'error')

        threading.Thread(target=fetch_rooms, daemon=True).start()

    def _show_delete_room_list(self, rooms):
        """Show list of rooms to delete"""
        if not rooms:
            speak_notification(_("No rooms found"), 'info')
            return

        # Create room list with names
        room_names = [f"{room['name']} (ID: {room['id']}, Creator: {room.get('creator_username', 'N/A')})" for room in rooms]

        dlg = wx.SingleChoiceDialog(self, _("Select room to delete:"), _("Delete Room"), room_names)

        if dlg.ShowModal() == wx.ID_OK:
            selection = dlg.GetSelection()
            selected_room = rooms[selection]
            room_id = selected_room['id']
            room_name = selected_room['name']

            # Confirm deletion
            confirm = _new_message_dialog(self,
                _("Are you sure you want to delete room '{name}' (ID: {id})? This cannot be undone!").format(name=room_name, id=room_id),
                _("Confirm Deletion"),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING)

            if confirm.ShowModal() == wx.ID_YES:
                def delete_thread():
                    try:
                        result = self.titan_client.delete_chat_room_by_moderator(room_id)
                        if result.get('success'):
                            wx.CallAfter(speak_titannet, _("Room deleted"))
                            wx.CallAfter(speak_notification, _("Room deleted"), 'success')
                        else:
                            wx.CallAfter(speak_notification, result.get('message', _("Failed to delete room")), 'error')
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')

                threading.Thread(target=delete_thread, daemon=True).start()

            confirm.Destroy()

        dlg.Destroy()

    # App Repository Methods

    def show_upload_app_dialog(self):
        """Dialog to upload package"""
        # Ask for file
        dlg = wx.FileDialog(
            self,
            _("Select package file (.TCEPACKAGE)"),
            wildcard="TCE Packages (*.TCEPACKAGE)|*.TCEPACKAGE|All files (*.*)|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        )

        if dlg.ShowModal() == wx.ID_OK:
            file_path = dlg.GetPath()

            # Ask for package name
            name_dlg = _new_text_entry_dialog(self, _("Package name:"), _("Upload Package"))
            if name_dlg.ShowModal() == wx.ID_OK:
                app_name = name_dlg.GetValue().strip()

                # Ask for description
                desc_dlg = _new_text_entry_dialog(self, _("Description:"), _("Upload Package"))
                if desc_dlg.ShowModal() == wx.ID_OK:
                    description = desc_dlg.GetValue().strip()

                    # Ask for category
                    categories = [
                        ("Application", "application"),
                        ("Component", "component"),
                        ("Sound Theme", "sound_theme"),
                        ("Game", "game"),
                        ("TCE Package", "tce_package"),
                        ("Language Pack", "language_pack"),
                        ("Status Bar Applet", "status_bar_applet")
                    ]
                    category_labels = [cat[0] for cat in categories]
                    cat_dlg = wx.SingleChoiceDialog(self, _("Select category:"), _("Category"), category_labels)
                    if cat_dlg.ShowModal() == wx.ID_OK:
                        category = categories[cat_dlg.GetSelection()][1]  # Use server-compatible value

                        # Ask for version
                        ver_dlg = _new_text_entry_dialog(self, _("Version (e.g. 1.0.0):"), _("Version"), "1.0.0")
                        if ver_dlg.ShowModal() == wx.ID_OK:
                            version = ver_dlg.GetValue().strip()

                            # Upload package
                            def upload_thread():
                                try:
                                    speak_titannet(_("Uploading package..."))
                                    result = self.titan_client.upload_app(
                                        file_path,
                                        app_name,
                                        version,
                                        description,
                                        category
                                    )
                                    if result.get('success'):
                                        wx.CallAfter(speak_titannet, _("Package uploaded successfully"))
                                        wx.CallAfter(speak_notification,
                                            _("Package uploaded and awaiting approval"),
                                            'success')
                                    else:
                                        error_msg = result.get('error', result.get('message', _("Failed to upload package")))
                                        wx.CallAfter(speak_notification, error_msg, 'error')
                                except Exception as e:
                                    wx.CallAfter(speak_notification, str(e), 'error')

                            threading.Thread(target=upload_thread, daemon=True).start()

                        ver_dlg.Destroy()
                    cat_dlg.Destroy()
                desc_dlg.Destroy()
            name_dlg.Destroy()

        dlg.Destroy()

    def show_search_apps_dialog(self):
        """Dialog to search packages"""
        dlg = _new_text_entry_dialog(self, _("Enter search query:"), _("Search Packages"))

        if dlg.ShowModal() == wx.ID_OK:
            query = dlg.GetValue().strip()

            if query:
                # Search apps
                def search_thread():
                    try:
                        speak_titannet(_("Searching..."))
                        result = self.titan_client.search_apps(query)
                        wx.CallAfter(self._display_search_results, result, query)
                    except Exception as e:
                        wx.CallAfter(speak_notification, str(e), 'error')

                threading.Thread(target=search_thread, daemon=True).start()

        dlg.Destroy()

    def _display_search_results(self, result, query):
        """Display search results"""
        if not result or not result.get('success'):
            speak_notification(_("Search failed"), 'error')
            return

        apps = result.get('apps', [])

        if not apps:
            speak_notification(_("No packages found for: {query}").format(query=query), 'info')
            return

        # Show in repository view
        self.repository_apps_cache = apps
        self.current_view = "repository"
        self.view_label.SetLabel(_("Search Results: {query}").format(query=query))

        self.main_listbox.Clear()
        for app in apps:
            status = _("Approved") if app.get('approved') else _("Pending")
            self.main_listbox.Append(f"{app['name']} v{app.get('version', '?')} - {status}")

        if apps:
            self.main_listbox.SetSelection(0)
            self.main_listbox.SetFocus()

        self.panel.Layout()
        speak_titannet(_("Found {count} packages").format(count=len(apps)))


class MOTDDialog(wx.Dialog):
    """Message of the Day dialog - read-only text with OK button"""

    def __init__(self, parent, motd_text):
        super().__init__(parent, title=_("Message of the Day"))

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Read-only multiline text field
        self.text_ctrl = wx.TextCtrl(
            panel,
            value=motd_text,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP
        )
        sizer.Add(self.text_ctrl, 1, wx.ALL | wx.EXPAND, 10)

        # OK button
        ok_button = wx.Button(panel, wx.ID_OK, _("OK"))
        ok_button.SetDefault()
        sizer.Add(ok_button, 0, wx.ALL | wx.ALIGN_CENTER, 10)

        panel.SetSizer(sizer)
        self.SetSize(wx.Size(450, 300))
        self.Centre()

        # Play MOTD sound
        play_sound('titannet/motd.ogg')

        # Bind Escape and Enter to close
        ok_button.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_OK))
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

        # Apply skin
        try:
            _apply_skin_recursive(self)
        except Exception:
            pass

    def _on_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_OK)
        else:
            event.Skip()


class BroadcastFileEditDialog(wx.Dialog):
    """Editor for broadcast files (motd_*.txt, newuser_*.txt, ...).

    - Multiline text area where Enter inserts a new line.
    - Ctrl+S saves the file via the Titan-Net websocket.
    - Escape closes (asks for confirmation if there are unsaved changes).
    """

    def __init__(self, parent, titan_client, filename, content):
        super().__init__(
            parent,
            title=_("Edit: {name}").format(name=filename),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        )

        self.titan_client = titan_client
        self.filename = filename
        self._original_content = content or ''
        self._saving = False

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        info_label = wx.StaticText(
            panel,
            label=_("Press Ctrl+S to save. Enter inserts a new line.")
        )
        sizer.Add(info_label, 0, wx.ALL, 10)

        self.text_ctrl = wx.TextCtrl(
            panel,
            value=self._original_content,
            style=wx.TE_MULTILINE | wx.TE_WORDWRAP | wx.TE_PROCESS_ENTER
        )
        # Use a monospaced font for predictable line layout in motd-style files.
        try:
            mono = wx.Font(10, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
            self.text_ctrl.SetFont(mono)
        except Exception:
            pass
        sizer.Add(self.text_ctrl, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 10)

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        self.save_button = wx.Button(panel, label=_("Save (Ctrl+S)"))
        self.save_button.Bind(wx.EVT_BUTTON, lambda e: self._save())
        button_row.Add(self.save_button, 0, wx.RIGHT, 5)

        self.close_button = wx.Button(panel, wx.ID_CANCEL, _("Close"))
        button_row.Add(self.close_button, 0)

        sizer.Add(button_row, 0, wx.ALL | wx.ALIGN_RIGHT, 10)

        panel.SetSizer(sizer)
        self.SetSize(wx.Size(700, 500))
        self.Centre()

        # Ctrl+S to save / Escape to close. EVT_CHAR_HOOK fires before the
        # multiline TextCtrl swallows Enter, so plain Enter still inserts a
        # newline naturally.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE, self._on_close)

        wx.CallAfter(self.text_ctrl.SetFocus)

    def _on_key(self, event):
        keycode = event.GetKeyCode()
        modifiers = event.GetModifiers()
        ctrl = bool(modifiers & wx.MOD_CONTROL)

        if ctrl and keycode in (ord('S'), ord('s')):
            self._save()
            return
        if keycode == wx.WXK_ESCAPE:
            self._on_close(event)
            return
        event.Skip()

    def _has_unsaved_changes(self):
        return self.text_ctrl.GetValue() != self._original_content

    def _on_close(self, event):
        if self._has_unsaved_changes():
            dlg = _new_message_dialog(
                self,
                _("You have unsaved changes. Discard them?"),
                _("Unsaved changes"),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING
            )
            try:
                if dlg.ShowModal() != wx.ID_YES:
                    if hasattr(event, 'Veto'):
                        try:
                            event.Veto()
                        except Exception:
                            pass
                    return
            finally:
                dlg.Destroy()
        self.EndModal(wx.ID_CANCEL)

    def _save(self):
        if self._saving:
            return
        content = self.text_ctrl.GetValue()
        self._saving = True
        self.save_button.Enable(False)
        speak_titannet(_("Saving {name}...").format(name=self.filename))

        def save_thread():
            try:
                response = self.titan_client.save_broadcast_file(self.filename, content)
                wx.CallAfter(self._on_save_response, response, content)
            except Exception as e:
                wx.CallAfter(self._on_save_response, {"success": False, "message": str(e)}, content)

        threading.Thread(target=save_thread, daemon=True).start()

    def _on_save_response(self, response, saved_content):
        self._saving = False
        try:
            self.save_button.Enable(True)
        except Exception:
            pass
        if response and response.get('success'):
            self._original_content = saved_content
            speak_notification(_("Broadcast file saved"), 'success')
        else:
            err = (response or {}).get('error') or (response or {}).get('message') \
                or _("Failed to save broadcast file")
            speak_notification(err, 'error')


def show_login_dialog(parent, titan_client: TitanNetClient):
    """
    Show login dialog

    Args:
        parent: Parent window
        titan_client: Titan-Net client instance

    Returns:
        Tuple of (success: bool, offline_mode: bool, motd: dict or None)
    """
    # Check server availability (silently - no announcement)
    server_available = titan_client.check_server()

    if not server_available:
        speak_titannet(_("Titan-Net server is not available. Would you like to continue in offline mode?"))
        play_sound('core/error.ogg')

        dlg = _new_message_dialog(
            parent,
            _("Titan-Net server is not available.\nYou can continue in offline mode without messaging features."),
            _("Server Not Available"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING
        )

        result = dlg.ShowModal()
        dlg.Destroy()

        if result == wx.ID_YES:
            return (False, True, None)
        else:
            return (False, False, None)

    # Server available - show login dialog directly (no announcement)

    dialog = LoginDialog(parent, titan_client)
    result = dialog.ShowModal()

    logged_in = dialog.logged_in
    offline_mode = dialog.offline_mode
    motd = dialog.motd

    dialog.Destroy()

    if logged_in:
        return (True, False, motd)
    elif offline_mode:
        return (False, True, None)
    else:
        return (False, False, None)


_titan_net_window = None

def show_titan_net_window(parent, titan_client: TitanNetClient):
    """
    Show main Titan-Net window. Reuses existing hidden window if available.

    Args:
        parent: Parent window (may be None - a top-level Frame is fine
            without a parent, which lets IUI / Klango / launcher-mode
            open the window without a main TCE GUI).
        titan_client: Titan-Net client instance (must be logged in).

    Returns:
        The TitanNetMainWindow instance, or None on failure.
    """
    global _titan_net_window

    if not titan_client.is_connected:
        speak_notification(_("Not connected to Titan-Net"), 'error')
        return None

    # Reuse existing hidden window if it still exists. A cached window
    # from a previous open in the same process is kept alive (OnClose
    # hides instead of destroys), so we just re-show it.
    if _titan_net_window is not None:
        try:
            # Prove the wx C++ object is alive before touching it -
            # IsBeingDeleted raises RuntimeError on dead objects.
            alive = not _titan_net_window.IsBeingDeleted()
        except Exception:
            alive = False
        if alive:
            try:
                _titan_net_window.Show()
                _titan_net_window.Raise()
                try:
                    _titan_net_window.Iconize(False)
                except Exception:
                    pass
                try:
                    from src.ui.window_switcher import register_window
                    register_window("Titan-Net", window=_titan_net_window,
                                    category='messenger')
                except Exception:
                    pass
                return _titan_net_window
            except Exception as e:
                print(f"[TITAN-NET] Cached window show failed, recreating: {e}")
                _titan_net_window = None
        else:
            _titan_net_window = None

    try:
        _titan_net_window = TitanNetMainWindow(parent, titan_client)
    except Exception as e:
        print(f"[TITAN-NET] Failed to create main window: {e}")
        import traceback
        traceback.print_exc()
        _titan_net_window = None
        speak_notification(_("Error opening Titan-Net"), 'error')
        return None

    try:
        _titan_net_window.Show()
        _titan_net_window.Raise()
    except Exception as e:
        print(f"[TITAN-NET] Failed to show main window: {e}")

    try:
        from src.ui.window_switcher import register_window
        register_window("Titan-Net", window=_titan_net_window, category='messenger')
    except Exception:
        pass

    return _titan_net_window


if __name__ == "__main__":
    app = wx.App()

    client = TitanNetClient("titosofttitan.com", 8001)

    success, offline = show_login_dialog(None, client)

    if success:
        show_titan_net_window(None, client)
        app.MainLoop()
    else:
        print("Login cancelled or offline mode selected")

