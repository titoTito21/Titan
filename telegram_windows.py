# -*- coding: utf-8 -*-
"""
Dedicated windows for Telegram functionality:
- Private message windows
- Voice call windows
- User-specific interfaces
"""
import wx
import time
from datetime import datetime
import telegram_client
from sound import play_sound
from translation import set_language
from settings import get_setting

# Get translation function
_ = set_language(get_setting('language', 'pl'))

class TelegramPrivateMessageWindow(wx.Frame):
    """Private message window for specific user"""
    
    def __init__(self, parent, username):
        super().__init__(parent, title=f"{_('Wiadomości prywatne z')} {username}", size=(600, 450))
        
        self.parent_frame = parent
        self.username = username
        self.typing_timer = None
        
        self.setup_ui()
        self.Center()
        
        # Setup callbacks
        telegram_client.add_message_callback(self.on_message_received)
        
        # Load chat history
        telegram_client.get_chat_history(username)
        
        # Play popup sound when opening
        play_sound('popup.ogg')
        
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
    
    def on_key_press(self, event):
        """Handle keyboard shortcuts"""
        keycode = event.GetKeyCode()
        modifiers = event.GetModifiers()
        
        if keycode == wx.WXK_ESCAPE:
            self.Close()
        elif keycode == wx.WXK_RETURN and modifiers == wx.MOD_CONTROL:
            self.on_send_message(None)
        else:
            event.Skip()
    
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
    
    def append_message(self, sender, message, timestamp, is_own=False):
        """Add message to chat display"""
        if is_own:
            # Own message - right aligned
            color = wx.Colour(0, 120, 215)  # Blue
            prefix = ">>"
        else:
            # Other's message - left aligned
            color = wx.Colour(32, 32, 32)  # Dark gray
            prefix = "<<"
        
        # Format message
        formatted_msg = f"[{timestamp}] {prefix} {sender}: {message}\n"
        
        # Append with color
        self.chat_display.SetDefaultStyle(wx.TextAttr(color))
        self.chat_display.AppendText(formatted_msg)
        self.chat_display.SetInsertionPointEnd()
        self.chat_display.ShowPosition(self.chat_display.GetLastPosition())
    
    def on_message_received(self, message_data):
        """Handle incoming messages for this user"""
        msg_type = message_data.get('type')
        
        if msg_type == 'new_message':
            sender_username = message_data.get('sender_username')
            message = message_data.get('message')
            is_private = message_data.get('is_private', False)
            
            # Only show messages from our conversation partner
            if sender_username == self.username and is_private:
                timestamp = time.strftime('%H:%M')
                self.append_message(sender_username, message, timestamp, is_own=False)
                
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
                    
                    # Format timestamp
                    try:
                        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        time_str = dt.strftime('%H:%M')
                    except:
                        time_str = time.strftime('%H:%M')
                    
                    is_own = sender == telegram_client.get_user_data().get('username', '')
                    self.append_message(sender, content, time_str, is_own)
    
    def on_close(self, event):
        """Handle window close"""
        if self.typing_timer:
            self.typing_timer.Stop()
        
        # Stop typing indicator
        self.stop_typing_indicator()
        
        # Play close sound
        play_sound('popupclose.ogg')
        
        self.Destroy()


class TelegramVoiceCallWindow(wx.Frame):
    """Enhanced voice call window with better integration"""
    
    def __init__(self, parent, username, call_type):
        # Improved title formatting
        call_type_text = _("Połączenie wychodzące") if call_type == 'outgoing' else _("Połączenie przychodzące") 
        super().__init__(parent, title=f"{_('Rozmowa z')} {username}", size=(450, 320))
        
        self.parent_frame = parent
        self.username = username
        self.call_type = call_type
        self.call_connected = False
        self.call_timer = wx.Timer(self)
        self.call_start_time = None
        
        self.init_ui()
        self.Center()
        
        # Play popup sound when opening voice call window
        play_sound('popup.ogg')
        
        # Update call status every second
        self.Bind(wx.EVT_TIMER, self.update_call_timer, self.call_timer)
        self.call_timer.Start(1000)
        
        # Handle window close
        self.Bind(wx.EVT_CLOSE, self.on_close)
        
        # Auto-connect simulation for outgoing calls - REMOVED
        # Connection will be set when call is actually accepted via telegram_client events
        if call_type == 'outgoing':
            pass  # Wait for actual call acceptance from Telegram API
    
    def init_ui(self):
        """Initialize the UI"""
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # User info with avatar placeholder
        avatar_panel = wx.Panel(panel)
        avatar_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Large avatar placeholder
        avatar_label = wx.StaticText(avatar_panel, label="User")
        avatar_label.SetFont(wx.Font(48, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        avatar_sizer.Add(avatar_label, 0, wx.ALL | wx.CENTER, 10)
        
        # User info
        info_panel = wx.Panel(avatar_panel)
        info_sizer = wx.BoxSizer(wx.VERTICAL)
        
        user_label = wx.StaticText(info_panel, label=self.username)
        user_label.SetFont(wx.Font(18, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        info_sizer.Add(user_label, 0, wx.ALL, 5)
        
        call_type_text = _("Dzwonisz do") if self.call_type == 'outgoing' else _("Połączenie przychodzące od")
        call_info = wx.StaticText(info_panel, label=call_type_text)
        call_info.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
        info_sizer.Add(call_info, 0, wx.ALL, 2)
        
        info_panel.SetSizer(info_sizer)
        avatar_sizer.Add(info_panel, 1, wx.ALL | wx.CENTER, 10)
        
        avatar_panel.SetSizer(avatar_sizer)
        sizer.Add(avatar_panel, 0, wx.EXPAND | wx.ALL, 10)
        
        # Call status
        self.status_label = wx.StaticText(panel, label="[" + _("Łączenie...") + "]")
        self.status_label.SetFont(wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        sizer.Add(self.status_label, 0, wx.ALL | wx.CENTER, 10)
        
        # Call duration
        self.duration_label = wx.StaticText(panel, label="00:00")
        self.duration_label.SetFont(wx.Font(24, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        sizer.Add(self.duration_label, 0, wx.ALL | wx.CENTER, 10)
        
        # Control buttons
        button_panel = wx.Panel(panel)
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.mute_button = wx.Button(button_panel, label=_("Wycisz"), size=(100, 40))
        self.mute_button.Bind(wx.EVT_BUTTON, self.on_mute)
        button_sizer.Add(self.mute_button, 0, wx.ALL, 5)
        
        self.end_button = wx.Button(button_panel, label=_("Zakończ"), size=(120, 40))
        self.end_button.Bind(wx.EVT_BUTTON, self.on_end_call)
        self.end_button.SetBackgroundColour(wx.Colour(200, 50, 50))
        self.end_button.SetForegroundColour(wx.Colour(255, 255, 255))
        button_sizer.Add(self.end_button, 0, wx.ALL, 5)
        
        button_panel.SetSizer(button_sizer)
        sizer.Add(button_panel, 0, wx.CENTER | wx.ALL, 10)
        
        # Keyboard shortcuts info
        shortcuts_text = wx.StaticText(panel, 
                                     label=_("Skróty: Spacja=Wycisz/Włącz • Escape=Zakończ"))
        shortcuts_text.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
        shortcuts_text.SetForegroundColour(wx.Colour(128, 128, 128))
        sizer.Add(shortcuts_text, 0, wx.ALL | wx.CENTER, 10)
        
        panel.SetSizer(sizer)
        
        # Keyboard shortcuts
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_press)
    
    def on_key_press(self, event):
        """Handle keyboard shortcuts"""
        keycode = event.GetKeyCode()
        
        if keycode == wx.WXK_SPACE:
            self.on_mute(None)
        elif keycode == wx.WXK_ESCAPE:
            self.on_end_call(None)
        else:
            event.Skip()
    
    def set_call_connected(self):
        """Set call as connected"""
        if not self.call_connected:
            self.call_connected = True
            self.call_start_time = wx.DateTime.Now()
            self.status_label.SetLabel("[" + _("Połączono - rozmowa aktywna") + "]")
            
            # Play call success sound - indicates voice connection is established
            play_sound('titannet/callsuccess.ogg')
            
            # Focus the window
            self.Raise()
            self.SetFocus()
    
    def update_call_timer(self, event):
        """Update call duration display"""
        if self.call_connected and self.call_start_time:
            current_time = wx.DateTime.Now()
            duration = current_time - self.call_start_time
            
            total_seconds = duration.GetSeconds()
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            
            self.duration_label.SetLabel(f"{minutes:02d}:{seconds:02d}")
        elif not self.call_connected:
            # Show connecting status with animation
            import time
            dots = "." * ((int(time.time()) % 4) + 1)
            self.status_label.SetLabel("[" + _("Łączenie") + dots + "]")
    
    def on_mute(self, event):
        """Toggle microphone mute"""
        current_label = self.mute_button.GetLabel()
        if _("Wycisz") in current_label:  # Currently shows mute button
            self.mute_button.SetLabel(_("Włącz"))
            self.status_label.SetLabel("[" + _("Mikrofon wyciszony") + "]")
            play_sound('focus.ogg')
        else:  # Currently shows unmute button
            self.mute_button.SetLabel(_("Wycisz"))
            self.status_label.SetLabel("[" + _("Połączono - rozmowa aktywna") + "]")
            play_sound('select.ogg')
    
    def on_end_call(self, event):
        """End the call"""
        telegram_client.end_voice_call()
        self.Close()
    
    def on_close(self, event):
        """Handle window close"""
        self.call_timer.Stop()
        
        # End call if still active
        if telegram_client.is_call_active():
            telegram_client.end_voice_call()
        
        # Play close sound
        play_sound('popupclose.ogg')
        
        self.Destroy()


class TelegramGroupChatWindow(wx.Frame):
    """Group chat window for specific group"""
    
    def __init__(self, parent, group_name):
        super().__init__(parent, title=f"{_('Group chat')}: {group_name}", size=(600, 450))
        
        self.parent_frame = parent
        self.group_name = group_name
        self.typing_timer = None
        
        self.setup_ui()
        self.Center()
        
        # Setup callbacks
        telegram_client.add_message_callback(self.on_message_received)
        
        # Load group chat history
        telegram_client.get_group_chat_history(group_name)
        
        # Play popup sound when opening
        play_sound('popup.ogg')
        
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
    
    def on_key_press(self, event):
        """Handle keyboard shortcuts"""
        keycode = event.GetKeyCode()
        modifiers = event.GetModifiers()
        
        if keycode == wx.WXK_ESCAPE:
            self.Close()
        elif keycode == wx.WXK_RETURN and modifiers == wx.MOD_CONTROL:
            self.on_send_message(None)
        else:
            event.Skip()
    
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
    
    def append_message(self, sender, message, timestamp, is_own=False):
        """Add message to chat display"""
        if is_own:
            # Own message - right aligned
            color = wx.Colour(0, 120, 215)  # Blue
            prefix = ">>"
        else:
            # Other's message - left aligned
            color = wx.Colour(32, 32, 32)  # Dark gray
            prefix = "<<"
        
        # Format message
        formatted_msg = f"[{timestamp}] {prefix} {sender}: {message}\n"
        
        # Append with color
        self.chat_display.SetDefaultStyle(wx.TextAttr(color))
        self.chat_display.AppendText(formatted_msg)
        self.chat_display.SetInsertionPointEnd()
        self.chat_display.ShowPosition(self.chat_display.GetLastPosition())
    
    def on_message_received(self, message_data):
        """Handle incoming messages for this group"""
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
                    
                    # Format timestamp
                    try:
                        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        time_str = dt.strftime('%H:%M')
                    except:
                        time_str = time.strftime('%H:%M')
                    
                    is_own = sender == telegram_client.get_user_data().get('username', '')
                    self.append_message(sender, content, time_str, is_own)
    
    def on_close(self, event):
        """Handle window close"""
        if self.typing_timer:
            self.typing_timer.Stop()
        
        # Stop typing indicator
        self.stop_typing_indicator()
        
        # Play close sound
        play_sound('popupclose.ogg')
        
        self.Destroy()


def open_private_message_window(parent, username):
    """Open private message window for user"""
    window = TelegramPrivateMessageWindow(parent, username)
    window.Show()
    return window

def open_voice_call_window(parent, username, call_type='outgoing'):
    """Open voice call window for user"""
    window = TelegramVoiceCallWindow(parent, username, call_type)
    window.Show()
    return window

def open_group_chat_window(parent, group_name):
    """Open group chat window"""
    window = TelegramGroupChatWindow(parent, group_name)
    window.Show()
    return window