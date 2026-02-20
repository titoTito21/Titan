# -*- coding: utf-8 -*-
"""
Dedicated windows for Telegram functionality:
- Private message windows
- Voice call windows
- User-specific interfaces
"""
import wx
import time
import threading
from datetime import datetime
from src.network import telegram_client
from src.titan_core.sound import play_sound, play_voice_message, toggle_voice_message, is_voice_message_playing, is_voice_message_paused
from src.titan_core.translation import set_language
from src.settings.settings import get_setting
import re

try:
    import accessible_output3.outputs.auto
    _tg_speaker = accessible_output3.outputs.auto.Auto()
except Exception:
    _tg_speaker = None

try:
    from src.titan_core.stereo_speech import speak_stereo, get_stereo_speech
    _TG_STEREO_AVAILABLE = True
except ImportError:
    _TG_STEREO_AVAILABLE = False

# Get translation function
_ = set_language(get_setting('language', 'pl'))


def _speak_tg(text, position=0.0, pitch_offset=0, interrupt=False):
    """Speak text via stereo speech / ao3 for Telegram chat notifications."""
    if not text or not _tg_speaker:
        return
    try:
        stereo_enabled = get_setting('stereo_speech', 'False', section='invisible_interface').lower() == 'true'
        if stereo_enabled and _TG_STEREO_AVAILABLE:
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
                    _tg_speaker.output(text)
            threading.Thread(target=do_speak, daemon=True).start()
        else:
            def do_speak():
                try:
                    _tg_speaker.output(text)
                except Exception:
                    pass
            threading.Thread(target=do_speak, daemon=True).start()
    except Exception:
        pass

class TelegramPrivateMessageWindow(wx.Frame):
    """Private message window for specific user"""
    
    def __init__(self, parent, username):
        super().__init__(parent, title=f"{_('Wiadomości prywatne z')} {username}", size=(600, 450))
        
        self.parent_frame = parent
        self.username = username
        self.typing_timer = None
        self.current_voice_message_path = None
        self.current_selected_message = None
        
        self.setup_ui()
        self.Center()
        
        # Setup callbacks
        telegram_client.add_message_callback(self.on_message_received)
        
        # Load chat history
        telegram_client.get_chat_history(username)

        # Play popup sound when opening
        play_sound('ui/popup.ogg')

        # Play new chat sound
        play_sound('titannet/new_chat.ogg')
        
        # Handle window close
        self.Bind(wx.EVT_CLOSE, self.on_close)
    
    def setup_ui(self):
        """Setup the user interface"""
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Header with user info
        header_panel = wx.Panel(panel)
        header_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        user_icon = wx.StaticText(header_panel, label="User:")
        user_icon.SetFont(wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        header_sizer.Add(user_icon, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        
        user_info = wx.StaticText(header_panel, label=f"{self.username}")
        user_info.SetFont(wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        header_sizer.Add(user_info, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        
        # Status indicator
        self.status_label = wx.StaticText(header_panel, label="[" + _("Online") + "]")
        self.status_label.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
        header_sizer.Add(self.status_label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

        # Voice call button
        self.call_button = wx.Button(header_panel, label=_("Voice Call"), size=(100, 30))
        self.call_button.Bind(wx.EVT_BUTTON, self.on_voice_call)
        header_sizer.Add(self.call_button, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

        header_panel.SetSizer(header_sizer)
        sizer.Add(header_panel, 0, wx.EXPAND | wx.ALL, 5)
        
        # Separator
        line = wx.StaticLine(panel)
        sizer.Add(line, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
        
        # Chat display
        self.chat_display = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self.chat_display.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self.chat_display.SetBackgroundColour(wx.Colour(248, 249, 250))
        sizer.Add(self.chat_display, 1, wx.EXPAND | wx.ALL, 5)
        
        # Typing indicator
        self.typing_indicator = wx.StaticText(panel, label="")
        self.typing_indicator.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
        self.typing_indicator.SetForegroundColour(wx.Colour(128, 128, 128))
        sizer.Add(self.typing_indicator, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        
        # Message input area
        input_panel = wx.Panel(panel)
        input_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.message_input = wx.TextCtrl(input_panel, style=wx.TE_PROCESS_ENTER | wx.TE_MULTILINE)
        self.message_input.SetMaxSize((-1, 80))  # Limit height
        self.message_input.Bind(wx.EVT_TEXT_ENTER, self.on_send_message)
        self.message_input.Bind(wx.EVT_TEXT, self.on_text_change)
        input_sizer.Add(self.message_input, 1, wx.EXPAND | wx.ALL, 5)
        
        send_button = wx.Button(input_panel, label=_("Wyślij"))
        send_button.Bind(wx.EVT_BUTTON, self.on_send_message)
        send_button.SetDefault()
        input_sizer.Add(send_button, 0, wx.ALL | wx.ALIGN_BOTTOM, 5)
        
        input_panel.SetSizer(input_sizer)
        sizer.Add(input_panel, 0, wx.EXPAND)
        
        panel.SetSizer(sizer)
        
        # Set focus to message input
        self.message_input.SetFocus()
        
        # Keyboard shortcuts
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_press)
        
        # Mouse click on chat display to select message
        self.chat_display.Bind(wx.EVT_LEFT_UP, self.on_chat_click)
    
    def on_chat_click(self, event):
        """Handle click on chat display to select message with voice"""
        # Get clicked position
        pos = event.GetPosition()
        hit_test = self.chat_display.HitTest(pos)
        
        if hit_test[0] != wx.TE_HT_UNKNOWN:
            # Get the line at clicked position
            line_start = self.chat_display.XYToPosition(0, hit_test[1])
            line_end = line_start
            
            # Find end of line
            while line_end < self.chat_display.GetLastPosition():
                char = self.chat_display.GetRange(line_end, line_end + 1)
                if char == '\n':
                    break
                line_end += 1
            
            # Get the line text
            line_text = self.chat_display.GetRange(line_start, line_end)
            self.current_selected_message = line_text
            
            # Check if this line contains voice message indicator
            self.check_for_voice_message(line_text)
        
        event.Skip()
    
    def check_for_voice_message(self, message_text):
        """Check if message contains voice message and extract path"""
        # Look for voice message patterns like [Voice: path/to/file.ogg]
        voice_pattern = r'\[Voice:\s*([^\]]+)\]'
        match = re.search(voice_pattern, message_text)
        
        if match:
            voice_path = match.group(1).strip()
            self.current_voice_message_path = voice_path
            play_sound('titannet/voice_select.ogg')
        else:
            self.current_voice_message_path = None
    
    def on_key_press(self, event):
        """Handle keyboard shortcuts"""
        keycode = event.GetKeyCode()
        modifiers = event.GetModifiers()
        current_focus = self.FindFocus()
        
        if keycode == wx.WXK_ESCAPE:
            self.Close()
        elif keycode == wx.WXK_RETURN and modifiers == wx.MOD_CONTROL:
            self.on_send_message(None)
        elif keycode == wx.WXK_RETURN and modifiers == wx.MOD_NONE:
            # Enter on chat display - play/pause voice message if available
            if current_focus == self.chat_display:
                self.handle_voice_message_at_cursor()
                return
            else:
                event.Skip()
        elif keycode == wx.WXK_SPACE and modifiers == wx.MOD_NONE:
            # Space on chat display - same as Enter for voice messages
            if current_focus == self.chat_display:
                self.handle_voice_message_at_cursor()
                return
            else:
                event.Skip()
        else:
            event.Skip()
    
    def handle_voice_message_toggle(self):
        """Handle play/pause of voice messages"""
        if self.current_voice_message_path:
            success = toggle_voice_message()
            if success:
                if is_voice_message_playing():
                    play_sound('titannet/voice_play.ogg')
                elif is_voice_message_paused():
                    play_sound('titannet/voice_pause.ogg')
            else:
                # Try to start playing the voice message
                if play_voice_message(self.current_voice_message_path):
                    play_sound('titannet/voice_play.ogg')
                else:
                    play_sound('core/error.ogg')
    
    def handle_voice_message_at_cursor(self):
        """Handle voice message at current cursor position"""
        # Get current cursor position
        cursor_pos = self.chat_display.GetInsertionPoint()
        
        # Find the line containing the cursor
        line_start = cursor_pos
        line_end = cursor_pos
        
        # Find start of line
        while line_start > 0:
            char = self.chat_display.GetRange(line_start - 1, line_start)
            if char == '\n':
                break
            line_start -= 1
        
        # Find end of line
        while line_end < self.chat_display.GetLastPosition():
            char = self.chat_display.GetRange(line_end, line_end + 1)
            if char == '\n':
                break
            line_end += 1
        
        # Get the line text
        line_text = self.chat_display.GetRange(line_start, line_end)
        
        # Check if this line contains voice message
        self.check_for_voice_message(line_text)
        
        # If voice message found, toggle playback
        if self.current_voice_message_path:
            self.handle_voice_message_toggle()
        else:
            # No voice message on this line
            play_sound('error.ogg')
    
    def on_text_change(self, event):
        """Handle text change for typing indicator"""
        # TODO: Send typing indicator to other user
        # telegram_client.send_typing_indicator(self.username, True)
        
        # Reset typing timer
        if self.typing_timer:
            self.typing_timer.Stop()
        
        self.typing_timer = wx.CallLater(1000, self.stop_typing_indicator)
        event.Skip()
    
    def stop_typing_indicator(self):
        """Stop sending typing indicator"""
        # TODO: Send stop typing to other user
        # telegram_client.send_typing_indicator(self.username, False)
        pass
    
    def on_send_message(self, event):
        """Send private message"""
        message = self.message_input.GetValue().strip()
        if not message:
            return
        
        if telegram_client.send_message(self.username, message):
            # Display sent message
            timestamp = time.strftime('%H:%M')
            self.append_message("Ja", message, timestamp, is_own=True)
            self.message_input.Clear()
            self.message_input.SetFocus()
        else:
            play_sound('error.ogg')
            wx.MessageBox(_("Nie udało się wysłać wiadomości"), _("Błąd"), wx.OK | wx.ICON_ERROR)
    
    def append_message(self, sender, message, timestamp, is_own=False, voice_file=None):
        """Add message to chat display"""
        if is_own:
            # Own message - right aligned
            color = wx.Colour(0, 120, 215)  # Blue
            prefix = ">>"
        else:
            # Other's message - left aligned
            color = wx.Colour(32, 32, 32)  # Dark gray
            prefix = "<<"
        
        # Add voice message indicator
        message_content = message
        if voice_file:
            voice_indicator = f"[Voice: {voice_file}]"
            if message_content:
                message_content += f" {voice_indicator}"
            else:
                message_content = f"{_('Voice message')} {voice_indicator}"
        
        # Format message
        formatted_msg = f"[{timestamp}] {prefix} {sender}: {message_content}\n"
        
        # Append with color
        self.chat_display.SetDefaultStyle(wx.TextAttr(color))
        self.chat_display.AppendText(formatted_msg)
        self.chat_display.SetInsertionPointEnd()
        self.chat_display.ShowPosition(self.chat_display.GetLastPosition())
    
    def on_message_received(self, message_data):
        """Handle incoming messages for this user"""
        # Check if window is still valid
        if not self or not hasattr(self, 'chat_display') or not self.chat_display:
            return
            
        msg_type = message_data.get('type')
        
        if msg_type == 'new_message':
            sender_username = message_data.get('sender_username')
            message = message_data.get('message')
            is_private = message_data.get('is_private', False)
            
            # Only show messages from our conversation partner
            if sender_username == self.username and is_private:
                timestamp = time.strftime('%H:%M')
                self.append_message(sender_username, message, timestamp, is_own=False)

                # Titan-net sound + TTS notification
                play_sound('titannet/new_message.ogg')
                tts_text = f"{sender_username}: {message}"
                if len(tts_text) > 100:
                    tts_text = tts_text[:100] + "..."
                _speak_tg(tts_text, position=-0.3, pitch_offset=-2)

                # Update window title to show new message
                original_title = f"{_('Wiadomości prywatne z')} {self.username}"
                self.SetTitle(f"[NOWA] {self.username}")

                # Reset title after 3 seconds
                wx.CallLater(3000, lambda: self.SetTitle(original_title))

                # Bring window to front if not focused
                if not self.IsActive():
                    self.RequestUserAttention()
        
        elif msg_type == 'chat_history':
            with_user = message_data.get('with_user')
            messages = message_data.get('messages', [])
            
            if with_user == self.username:
                self.chat_display.Clear()
                self.chat_display.AppendText(f"=== {_('Historia rozmowy z')} {with_user} ===\n\n")
                
                for msg in messages:
                    sender = msg.get('sender_username', _('Unknown'))
                    content = msg.get('message', '')
                    timestamp = msg.get('timestamp', '')
                    voice_file = msg.get('voice_file', '')
                    
                    # Format timestamp
                    try:
                        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        time_str = dt.strftime('%H:%M')
                    except:
                        time_str = time.strftime('%H:%M')
                    
                    is_own = sender == telegram_client.get_user_data().get('username', '')
                    self.append_message(sender, content, time_str, is_own, voice_file)
    
    def on_voice_call(self, event):
        """Start voice call with this user"""
        if telegram_client.is_call_active():
            _speak_tg(_("Call already in progress"), position=0.7, pitch_offset=5)
            return

        if not telegram_client.is_voice_calls_available():
            _speak_tg(_("Voice calls not available"), position=0.7, pitch_offset=5)
            return

        # Start the call
        telegram_client.start_voice_call(self.username)

        # Open voice call window
        call_window = TelegramVoiceCallWindow(self, self.username, 'outgoing')
        call_window.Show()

    def on_close(self, event):
        """Handle window close"""
        if self.typing_timer:
            self.typing_timer.Stop()

        # Stop typing indicator
        self.stop_typing_indicator()

        # Play close sound
        play_sound('ui/popupclose.ogg')

        self.Destroy()


class TelegramVoiceCallWindow(wx.Frame):
    """Voice call window with state tracking and real mute control."""

    def __init__(self, parent, username, call_type, call_data=None):
        super().__init__(parent, title=f"{_('Voice call')}: {username}", size=(450, 350))

        self.parent_frame = parent
        self.username = username
        self.call_type = call_type  # 'outgoing', 'incoming', 'tce_incoming'
        self.call_data = call_data or {}
        self.call_connected = False
        self.is_muted = False
        self.call_timer = wx.Timer(self)
        self.call_start_time = None

        self.init_ui()
        self.Center()

        play_sound('ui/popup.ogg')

        # Register callback for call state changes
        telegram_client.add_call_callback(self.on_call_event)

        # Start status polling
        self.Bind(wx.EVT_TIMER, self.update_call_timer, self.call_timer)
        self.call_timer.Start(1000)

        # Check if call is already connected (outgoing TCE calls connect immediately)
        if telegram_client.is_call_active():
            status = telegram_client.get_call_status()
            if status.get('state') == 'connected':
                wx.CallLater(500, self.set_call_connected)

        self.Bind(wx.EVT_CLOSE, self.on_close)

    def init_ui(self):
        """Initialize the UI."""
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # User info
        user_label = wx.StaticText(panel, label=self.username)
        user_label.SetFont(wx.Font(18, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        sizer.Add(user_label, 0, wx.ALL | wx.CENTER, 10)

        # Call direction
        if self.call_type == 'outgoing':
            dir_text = _("Outgoing call")
        elif self.call_type == 'tce_incoming':
            dir_text = _("Incoming call")
        else:
            dir_text = _("Incoming call (native)")

        call_info = wx.StaticText(panel, label=dir_text)
        call_info.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
        sizer.Add(call_info, 0, wx.ALL | wx.CENTER, 5)

        # Call status
        self.status_label = wx.StaticText(panel, label="[" + _("Connecting...") + "]")
        self.status_label.SetFont(wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        sizer.Add(self.status_label, 0, wx.ALL | wx.CENTER, 10)

        # Duration
        self.duration_label = wx.StaticText(panel, label="00:00")
        self.duration_label.SetFont(wx.Font(24, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        sizer.Add(self.duration_label, 0, wx.ALL | wx.CENTER, 10)

        # Audio info
        has_audio = telegram_client.is_voice_calls_available()
        if has_audio:
            audio_text = _("Audio: group voice chat")
        else:
            audio_text = _("Audio: limited (py-tgcalls not installed)")

        audio_label = wx.StaticText(panel, label=audio_text)
        audio_label.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
        audio_label.SetForegroundColour(wx.Colour(100, 100, 100))
        sizer.Add(audio_label, 0, wx.ALL | wx.CENTER, 3)

        # Buttons
        button_panel = wx.Panel(panel)
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.mute_button = wx.Button(button_panel, label=_("Mute"), size=(120, 40))
        self.mute_button.Bind(wx.EVT_BUTTON, self.on_mute)
        button_sizer.Add(self.mute_button, 0, wx.ALL, 5)

        self.end_button = wx.Button(button_panel, label=_("End call"), size=(120, 40))
        self.end_button.Bind(wx.EVT_BUTTON, self.on_end_call)
        self.end_button.SetBackgroundColour(wx.Colour(200, 50, 50))
        self.end_button.SetForegroundColour(wx.Colour(255, 255, 255))
        button_sizer.Add(self.end_button, 0, wx.ALL, 5)

        button_panel.SetSizer(button_sizer)
        sizer.Add(button_panel, 0, wx.CENTER | wx.ALL, 10)

        # Shortcuts
        shortcuts = wx.StaticText(panel,
                                  label=_("Shortcuts: Space=Mute/Unmute, Escape=End call"))
        shortcuts.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
        shortcuts.SetForegroundColour(wx.Colour(128, 128, 128))
        sizer.Add(shortcuts, 0, wx.ALL | wx.CENTER, 5)

        panel.SetSizer(sizer)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_press)

    def on_key_press(self, event):
        """Handle keyboard shortcuts."""
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_SPACE:
            self.on_mute(None)
        elif keycode == wx.WXK_ESCAPE:
            self.on_end_call(None)
        else:
            event.Skip()

    def set_call_connected(self):
        """Mark call as connected."""
        if not self.call_connected:
            self.call_connected = True
            self.call_start_time = wx.DateTime.Now()
            self.status_label.SetLabel("[" + _("Connected - call active") + "]")
            _speak_tg(_("Call connected"), position=0.0, pitch_offset=0)
            self.Raise()
            self.SetFocus()

    def on_call_event(self, event_type, data):
        """Handle call state changes from voice client."""
        if event_type == 'state_changed':
            new_state = data.get('new_state', '')
            if new_state == 'connected':
                self.set_call_connected()
            elif new_state == 'idle':
                # Call ended remotely
                if self:
                    self.Close()
        elif event_type == 'call_ended':
            if self:
                self.Close()
        elif event_type == 'call_failed':
            error = data.get('error', _('Unknown error'))
            self.status_label.SetLabel(f"[{_('Error')}: {error}]")
            _speak_tg(f"{_('Call failed')}: {error}", position=0.7, pitch_offset=5)
        elif event_type == 'mute_changed':
            muted = data.get('muted', False)
            self.is_muted = muted
            if muted:
                self.mute_button.SetLabel(_("Unmute"))
                self.status_label.SetLabel("[" + _("Microphone muted") + "]")
            else:
                self.mute_button.SetLabel(_("Mute"))
                self.status_label.SetLabel("[" + _("Connected - call active") + "]")

    def update_call_timer(self, event):
        """Update call duration display."""
        if self.call_connected and self.call_start_time:
            duration = wx.DateTime.Now() - self.call_start_time
            total_seconds = duration.GetSeconds()
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            self.duration_label.SetLabel(f"{minutes:02d}:{seconds:02d}")
        elif not self.call_connected:
            dots = "." * ((int(time.time()) % 4) + 1)
            self.status_label.SetLabel("[" + _("Connecting") + dots + "]")

        # Check if call ended externally
        if not telegram_client.is_call_active() and self.call_connected:
            self.Close()

    def on_mute(self, event):
        """Toggle microphone mute via voice client."""
        telegram_client.toggle_mute()
        # UI update happens in on_call_event callback

    def on_end_call(self, event):
        """End the call."""
        telegram_client.end_voice_call()
        self.Close()

    def on_close(self, event):
        """Handle window close."""
        self.call_timer.Stop()

        if telegram_client.is_call_active():
            telegram_client.end_voice_call()

        play_sound('ui/popupclose.ogg')
        self.Destroy()


class TelegramGroupChatWindow(wx.Frame):
    """Group chat window for specific group"""
    
    def __init__(self, parent, group_name):
        super().__init__(parent, title=f"{_('Group chat')}: {group_name}", size=(600, 450))
        
        self.parent_frame = parent
        self.group_name = group_name
        self.typing_timer = None
        self.current_voice_message_path = None
        self.current_selected_message = None
        
        self.setup_ui()
        self.Center()
        
        # Setup callbacks
        telegram_client.add_message_callback(self.on_message_received)
        
        # Load group chat history
        telegram_client.get_group_chat_history(group_name)
        
        # Play popup sound when opening
        play_sound('ui/popup.ogg')
        
        # Play new chat sound
        play_sound('titannet/new_chat.ogg')
        
        # Handle window close
        self.Bind(wx.EVT_CLOSE, self.on_close)
    
    def setup_ui(self):
        """Setup the user interface"""
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Header with group info
        header_panel = wx.Panel(panel)
        header_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        group_icon = wx.StaticText(header_panel, label="Group:")
        group_icon.SetFont(wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        header_sizer.Add(group_icon, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        
        group_info = wx.StaticText(header_panel, label=f"{self.group_name}")
        group_info.SetFont(wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        header_sizer.Add(group_info, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        
        # Status indicator
        self.status_label = wx.StaticText(header_panel, label="[" + _("Active") + "]")
        self.status_label.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
        header_sizer.Add(self.status_label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        
        header_panel.SetSizer(header_sizer)
        sizer.Add(header_panel, 0, wx.EXPAND | wx.ALL, 5)
        
        # Separator
        line = wx.StaticLine(panel)
        sizer.Add(line, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
        
        # Chat display
        self.chat_display = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self.chat_display.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self.chat_display.SetBackgroundColour(wx.Colour(248, 249, 250))
        sizer.Add(self.chat_display, 1, wx.EXPAND | wx.ALL, 5)
        
        # Typing indicator
        self.typing_indicator = wx.StaticText(panel, label="")
        self.typing_indicator.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
        self.typing_indicator.SetForegroundColour(wx.Colour(128, 128, 128))
        sizer.Add(self.typing_indicator, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        
        # Message input area
        input_panel = wx.Panel(panel)
        input_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.message_input = wx.TextCtrl(input_panel, style=wx.TE_PROCESS_ENTER | wx.TE_MULTILINE)
        self.message_input.SetMaxSize((-1, 80))  # Limit height
        self.message_input.Bind(wx.EVT_TEXT_ENTER, self.on_send_message)
        self.message_input.Bind(wx.EVT_TEXT, self.on_text_change)
        input_sizer.Add(self.message_input, 1, wx.EXPAND | wx.ALL, 5)
        
        send_button = wx.Button(input_panel, label=_("Send"))
        send_button.Bind(wx.EVT_BUTTON, self.on_send_message)
        send_button.SetDefault()
        input_sizer.Add(send_button, 0, wx.ALL | wx.ALIGN_BOTTOM, 5)
        
        input_panel.SetSizer(input_sizer)
        sizer.Add(input_panel, 0, wx.EXPAND)
        
        panel.SetSizer(sizer)
        
        # Set focus to message input
        self.message_input.SetFocus()
        
        # Keyboard shortcuts
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_press)
        
        # Mouse click on chat display to select message
        self.chat_display.Bind(wx.EVT_LEFT_UP, self.on_chat_click)
    
    def on_chat_click(self, event):
        """Handle click on chat display to select message with voice"""
        # Get clicked position
        pos = event.GetPosition()
        hit_test = self.chat_display.HitTest(pos)
        
        if hit_test[0] != wx.TE_HT_UNKNOWN:
            # Get the line at clicked position
            line_start = self.chat_display.XYToPosition(0, hit_test[1])
            line_end = line_start
            
            # Find end of line
            while line_end < self.chat_display.GetLastPosition():
                char = self.chat_display.GetRange(line_end, line_end + 1)
                if char == '\n':
                    break
                line_end += 1
            
            # Get the line text
            line_text = self.chat_display.GetRange(line_start, line_end)
            self.current_selected_message = line_text
            
            # Check if this line contains voice message indicator
            self.check_for_voice_message(line_text)
        
        event.Skip()
    
    def check_for_voice_message(self, message_text):
        """Check if message contains voice message and extract path"""
        # Look for voice message patterns like [Voice: path/to/file.ogg]
        voice_pattern = r'\[Voice:\s*([^\]]+)\]'
        match = re.search(voice_pattern, message_text)
        
        if match:
            voice_path = match.group(1).strip()
            self.current_voice_message_path = voice_path
            play_sound('titannet/voice_select.ogg')
        else:
            self.current_voice_message_path = None
    
    def on_key_press(self, event):
        """Handle keyboard shortcuts"""
        keycode = event.GetKeyCode()
        modifiers = event.GetModifiers()
        current_focus = self.FindFocus()
        
        if keycode == wx.WXK_ESCAPE:
            self.Close()
        elif keycode == wx.WXK_RETURN and modifiers == wx.MOD_CONTROL:
            self.on_send_message(None)
        elif keycode == wx.WXK_RETURN and modifiers == wx.MOD_NONE:
            # Enter on chat display - play/pause voice message if available
            if current_focus == self.chat_display:
                self.handle_voice_message_at_cursor()
                return
            else:
                event.Skip()
        elif keycode == wx.WXK_SPACE and modifiers == wx.MOD_NONE:
            # Space on chat display - same as Enter for voice messages
            if current_focus == self.chat_display:
                self.handle_voice_message_at_cursor()
                return
            else:
                event.Skip()
        else:
            event.Skip()
    
    def handle_voice_message_toggle(self):
        """Handle play/pause of voice messages"""
        if self.current_voice_message_path:
            success = toggle_voice_message()
            if success:
                if is_voice_message_playing():
                    play_sound('titannet/voice_play.ogg')
                elif is_voice_message_paused():
                    play_sound('titannet/voice_pause.ogg')
            else:
                # Try to start playing the voice message
                if play_voice_message(self.current_voice_message_path):
                    play_sound('titannet/voice_play.ogg')
                else:
                    play_sound('core/error.ogg')
    
    def handle_voice_message_at_cursor(self):
        """Handle voice message at current cursor position"""
        # Get current cursor position
        cursor_pos = self.chat_display.GetInsertionPoint()
        
        # Find the line containing the cursor
        line_start = cursor_pos
        line_end = cursor_pos
        
        # Find start of line
        while line_start > 0:
            char = self.chat_display.GetRange(line_start - 1, line_start)
            if char == '\n':
                break
            line_start -= 1
        
        # Find end of line
        while line_end < self.chat_display.GetLastPosition():
            char = self.chat_display.GetRange(line_end, line_end + 1)
            if char == '\n':
                break
            line_end += 1
        
        # Get the line text
        line_text = self.chat_display.GetRange(line_start, line_end)
        
        # Check if this line contains voice message
        self.check_for_voice_message(line_text)
        
        # If voice message found, toggle playback
        if self.current_voice_message_path:
            self.handle_voice_message_toggle()
        else:
            # No voice message on this line
            play_sound('error.ogg')
    
    def on_text_change(self, event):
        """Handle text change for typing indicator"""
        # Reset typing timer
        if self.typing_timer:
            self.typing_timer.Stop()
        
        self.typing_timer = wx.CallLater(1000, self.stop_typing_indicator)
        event.Skip()
    
    def stop_typing_indicator(self):
        """Stop sending typing indicator"""
        pass
    
    def on_send_message(self, event):
        """Send group message"""
        message = self.message_input.GetValue().strip()
        if not message:
            return
        
        if telegram_client.send_group_message(self.group_name, message):
            # Display sent message
            timestamp = time.strftime('%H:%M')
            self.append_message(_("Me"), message, timestamp, is_own=True)
            self.message_input.Clear()
            self.message_input.SetFocus()
        else:
            play_sound('error.ogg')
            wx.MessageBox(_("Failed to send message"), _("Error"), wx.OK | wx.ICON_ERROR)
    
    def append_message(self, sender, message, timestamp, is_own=False, voice_file=None):
        """Add message to chat display"""
        if is_own:
            # Own message - right aligned
            color = wx.Colour(0, 120, 215)  # Blue
            prefix = ">>"
        else:
            # Other's message - left aligned
            color = wx.Colour(32, 32, 32)  # Dark gray
            prefix = "<<"
        
        # Add voice message indicator
        message_content = message
        if voice_file:
            voice_indicator = f"[Voice: {voice_file}]"
            if message_content:
                message_content += f" {voice_indicator}"
            else:
                message_content = f"{_('Voice message')} {voice_indicator}"
        
        # Format message
        formatted_msg = f"[{timestamp}] {prefix} {sender}: {message_content}\n"
        
        # Append with color
        self.chat_display.SetDefaultStyle(wx.TextAttr(color))
        self.chat_display.AppendText(formatted_msg)
        self.chat_display.SetInsertionPointEnd()
        self.chat_display.ShowPosition(self.chat_display.GetLastPosition())
    
    def on_message_received(self, message_data):
        """Handle incoming messages for this group"""
        # Check if window is still valid
        if not self or not hasattr(self, 'chat_display') or not self.chat_display:
            return
            
        msg_type = message_data.get('type')
        
        if msg_type == 'new_message':
            sender_username = message_data.get('sender_username')
            message = message_data.get('message')
            is_group = message_data.get('is_group', False)
            group_name = message_data.get('group_name', '')
            
            # Only show messages from our group conversation
            if is_group and group_name == self.group_name:
                timestamp = time.strftime('%H:%M')
                self.append_message(sender_username, message, timestamp, is_own=False)

                # Titan-net sound + TTS notification
                play_sound('titannet/chat_message.ogg')
                tts_text = f"{sender_username}: {message}"
                if len(tts_text) > 100:
                    tts_text = tts_text[:100] + "..."
                _speak_tg(tts_text, position=-0.3, pitch_offset=-2)

                # Update window title to show new message
                original_title = f"{_('Group chat')}: {self.group_name}"
                self.SetTitle(f"[NEW] {self.group_name}")

                # Reset title after 3 seconds
                wx.CallLater(3000, lambda: self.SetTitle(original_title))

                # Bring window to front if not focused
                if not self.IsActive():
                    self.RequestUserAttention()
        
        elif msg_type == 'group_chat_history':
            group_name = message_data.get('group_name')
            messages = message_data.get('messages', [])
            
            if group_name == self.group_name:
                self.chat_display.Clear()
                self.chat_display.AppendText(f"=== {_('Group chat history')}: {group_name} ===\n\n")
                
                for msg in messages:
                    sender = msg.get('sender_username', _('Unknown'))
                    content = msg.get('message', '')
                    timestamp = msg.get('timestamp', '')
                    voice_file = msg.get('voice_file', '')
                    
                    # Format timestamp
                    try:
                        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        time_str = dt.strftime('%H:%M')
                    except:
                        time_str = time.strftime('%H:%M')
                    
                    is_own = sender == telegram_client.get_user_data().get('username', '')
                    self.append_message(sender, content, time_str, is_own, voice_file)
    
    def on_close(self, event):
        """Handle window close"""
        if self.typing_timer:
            self.typing_timer.Stop()
        
        # Stop typing indicator
        self.stop_typing_indicator()
        
        # Play close sound
        play_sound('ui/popupclose.ogg')
        
        self.Destroy()


def open_private_message_window(parent, username):
    """Open private message window for user"""
    window = TelegramPrivateMessageWindow(parent, username)
    window.Show()
    return window

def open_voice_call_window(parent, username, call_type='outgoing', call_data=None):
    """Open voice call window for user"""
    window = TelegramVoiceCallWindow(parent, username, call_type, call_data)
    window.Show()
    return window

def open_group_chat_window(parent, group_name):
    """Open group chat window"""
    window = TelegramGroupChatWindow(parent, group_name)
    window.Show()
    return window


class IncomingCallDialog(wx.Dialog):
    """Dialog for incoming voice calls (both TCE group calls and native Telegram calls)."""

    def __init__(self, parent, caller_name, call_data=None):
        super().__init__(
            parent,
            title=_("Incoming call"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP | wx.FRAME_FLOAT_ON_PARENT,
            size=(400, 220)
        )

        self.caller_name = caller_name
        self.call_data = call_data or {}
        self.result = None

        # Determine call type
        self.is_tce_call = self.call_data.get('type') == 'tce_call'
        self.is_native_call = self.call_data.get('type') == 'native_call'

        self.setup_ui()
        self.Center()

        # Force to top
        self.SetWindowStyle(self.GetWindowStyle() | wx.STAY_ON_TOP)
        self.Raise()
        self.RequestUserAttention(wx.USER_ATTENTION_ERROR)

        import sys
        if sys.platform == 'win32':
            try:
                import ctypes
                hwnd = self.GetHandle()
                if hwnd:
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
                    ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)
            except Exception:
                pass

        # Ring timer
        self.ring_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.play_ring_sound, self.ring_timer)
        self.ring_timer.Start(3000)

        play_sound('titannet/ring_in.ogg')
        _speak_tg(f"{_('Incoming call from')} {caller_name}", position=0.0, pitch_offset=3, interrupt=True)

        self.Bind(wx.EVT_CLOSE, self.on_reject)

    def setup_ui(self):
        """Setup the dialog UI."""
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Header
        icon_panel = wx.Panel(panel)
        icon_panel.SetBackgroundColour(wx.Colour(45, 140, 240))
        icon_sizer = wx.BoxSizer(wx.VERTICAL)

        phone_icon = wx.StaticText(icon_panel, label=_("CALL"))
        phone_icon.SetFont(wx.Font(24, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        phone_icon.SetForegroundColour(wx.Colour(255, 255, 255))
        icon_sizer.Add(phone_icon, 0, wx.ALL | wx.CENTER, 10)

        icon_panel.SetSizer(icon_sizer)
        main_sizer.Add(icon_panel, 0, wx.EXPAND)

        # Caller info
        info_panel = wx.Panel(panel)
        info_sizer = wx.BoxSizer(wx.VERTICAL)

        incoming_text = wx.StaticText(info_panel, label=_("Incoming call from:"))
        incoming_text.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        info_sizer.Add(incoming_text, 0, wx.ALL | wx.CENTER, 5)

        caller_label = wx.StaticText(info_panel, label=self.caller_name)
        caller_label.SetFont(wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        info_sizer.Add(caller_label, 0, wx.ALL | wx.CENTER, 5)

        # Show call type info
        if self.is_tce_call:
            type_text = _("Voice chat call (full audio)")
        elif self.is_native_call:
            type_text = _("Telegram call (signaling only)")
        else:
            type_text = _("Voice call")

        type_label = wx.StaticText(info_panel, label=type_text)
        type_label.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
        type_label.SetForegroundColour(wx.Colour(100, 100, 100))
        info_sizer.Add(type_label, 0, wx.ALL | wx.CENTER, 2)

        info_panel.SetSizer(info_sizer)
        main_sizer.Add(info_panel, 1, wx.EXPAND | wx.ALL, 5)

        # Buttons
        button_panel = wx.Panel(panel)
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.reject_button = wx.Button(button_panel, wx.ID_CANCEL, label=_("Reject"))
        self.reject_button.SetBackgroundColour(wx.Colour(220, 50, 50))
        self.reject_button.SetForegroundColour(wx.Colour(255, 255, 255))
        self.reject_button.SetFont(wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self.reject_button.Bind(wx.EVT_BUTTON, self.on_reject)
        button_sizer.Add(self.reject_button, 1, wx.ALL | wx.EXPAND, 10)

        self.accept_button = wx.Button(button_panel, wx.ID_OK, label=_("Accept"))
        self.accept_button.SetBackgroundColour(wx.Colour(50, 200, 50))
        self.accept_button.SetForegroundColour(wx.Colour(255, 255, 255))
        self.accept_button.SetFont(wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        self.accept_button.Bind(wx.EVT_BUTTON, self.on_accept)
        button_sizer.Add(self.accept_button, 1, wx.ALL | wx.EXPAND, 10)

        button_panel.SetSizer(button_sizer)
        main_sizer.Add(button_panel, 0, wx.EXPAND)

        panel.SetSizer(main_sizer)

        self.accept_button.SetDefault()
        self.accept_button.SetFocus()

        # Keyboard: Enter=Accept, Escape=Reject
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_press)

    def on_key_press(self, event):
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_ESCAPE:
            self.on_reject(None)
        elif keycode == wx.WXK_RETURN:
            self.on_accept(None)
        else:
            event.Skip()

    def play_ring_sound(self, event):
        play_sound('titannet/ring_in.ogg')

    def on_accept(self, event):
        """Handle call accept."""
        self.ring_timer.Stop()
        self.result = 'accept'

        app = wx.GetApp()
        main_window = app.GetTopWindow() if app else None

        if self.is_tce_call:
            # TCE call: join the group voice chat
            group_id = self.call_data.get('group_id')
            if group_id:
                telegram_client.join_voice_call(group_id)

            # Open voice call window
            if main_window:
                call_window = TelegramVoiceCallWindow(
                    main_window, self.caller_name, 'tce_incoming', self.call_data
                )
                call_window.Show()

        elif self.is_native_call:
            # Native Telegram call: accept signaling
            telegram_client.answer_voice_call()

            # Open voice call window
            if main_window:
                call_window = TelegramVoiceCallWindow(
                    main_window, self.caller_name, 'incoming', self.call_data
                )
                call_window.Show()

        else:
            # Unknown type - try answering
            telegram_client.answer_voice_call()
            if main_window:
                call_window = TelegramVoiceCallWindow(
                    main_window, self.caller_name, 'incoming', self.call_data
                )
                call_window.Show()

        self.EndModal(wx.ID_OK)

    def on_reject(self, event):
        """Handle call reject."""
        self.ring_timer.Stop()
        self.result = 'reject'

        if self.is_native_call:
            telegram_client.end_voice_call()

        self.EndModal(wx.ID_CANCEL)

    def __del__(self):
        if hasattr(self, 'ring_timer') and self.ring_timer:
            self.ring_timer.Stop()


def show_incoming_call_dialog(parent, caller_name, call_data=None):
    """Show incoming call dialog and return result."""
    dialog = IncomingCallDialog(parent, caller_name, call_data)
    result = dialog.ShowModal()
    user_choice = dialog.result
    dialog.Destroy()
    return user_choice