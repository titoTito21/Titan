# -*- coding: utf-8 -*-
import wx
import threading
import time
from telegram_client import telegram_client, connect_to_server, disconnect_from_server, send_message, get_online_users, get_contacts, get_group_chats, is_connected
from sound import play_sound
from translation import set_language
from settings import get_setting

# Get translation function
_ = set_language(get_setting('language', 'pl'))

class TelegramLoginDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Connect to Telegram"), size=(500, 300))
        
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Info text
        info_text = wx.StaticText(panel, label=_(
            "To connect to Telegram, you need a bot token.\n"
            "Create a bot with @BotFather in Telegram and copy the token."
        ))
        sizer.Add(info_text, 0, wx.ALL, 10)
        
        # Bot token input
        token_label = wx.StaticText(panel, label=_("Bot token:"))
        sizer.Add(token_label, 0, wx.ALL, 5)
        
        self.token_ctrl = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
        sizer.Add(self.token_ctrl, 0, wx.EXPAND | wx.ALL, 5)
        
        # Optional group chat ID
        group_label = wx.StaticText(panel, label=_("Group chat ID (optional):"))
        sizer.Add(group_label, 0, wx.ALL, 5)
        
        self.group_ctrl = wx.TextCtrl(panel)
        self.group_ctrl.SetHint(_("Leave empty for private messages"))
        sizer.Add(self.group_ctrl, 0, wx.EXPAND | wx.ALL, 5)
        
        # Username
        username_label = wx.StaticText(panel, label=_("Your username in TCE:"))
        sizer.Add(username_label, 0, wx.ALL, 5)
        
        self.username_ctrl = wx.TextCtrl(panel)
        sizer.Add(self.username_ctrl, 0, wx.EXPAND | wx.ALL, 5)
        
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
        group_id = self.group_ctrl.GetValue().strip()
        return (
            self.token_ctrl.GetValue(),
            group_id if group_id else None,
            self.username_ctrl.GetValue() or "TCE User"
        )

class TelegramChatWindow(wx.Frame):
    def __init__(self, parent, username):
        super().__init__(parent, title=f"Telegram - {username}", size=(600, 500))
        
        self.username = username
        self.current_chat_user = None
        self.typing_timer = None
        
        # Setup GUI
        self.setup_ui()
        
        # Setup callbacks
        telegram_client.add_message_callback(self.on_message_received)
        telegram_client.add_status_callback(self.on_status_change)
        
        self.Centre()
        
        # Play welcome sound
        play_sound('titannet/welcome to IM.ogg')
        
        # Update users list periodically
        self.update_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.update_users_periodically, self.update_timer)
        self.update_timer.Start(5000)  # Update every 5 seconds
    
    def setup_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Left panel - Users list
        left_panel = wx.Panel(panel)
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        
        users_label = wx.StaticText(left_panel, label=_("Users in chat:"))
        left_sizer.Add(users_label, 0, wx.ALL, 5)
        
        self.users_list = wx.ListBox(left_panel)
        self.users_list.Bind(wx.EVT_LISTBOX, self.on_user_selected)
        left_sizer.Add(self.users_list, 1, wx.EXPAND | wx.ALL, 5)
        
        left_panel.SetSizer(left_sizer)
        main_sizer.Add(left_panel, 0, wx.EXPAND | wx.ALL, 5)
        
        # Right panel - Chat
        right_panel = wx.Panel(panel)
        right_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Chat display
        self.chat_display = wx.TextCtrl(right_panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.chat_display.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        right_sizer.Add(self.chat_display, 1, wx.EXPAND | wx.ALL, 5)
        
        # Status label
        self.status_label = wx.StaticText(right_panel, label=_("Connected to Telegram - select a user or chat generally"))
        right_sizer.Add(self.status_label, 0, wx.ALL, 5)
        
        # Message input
        input_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.message_input = wx.TextCtrl(right_panel, style=wx.TE_PROCESS_ENTER)
        self.message_input.Bind(wx.EVT_TEXT_ENTER, self.on_send_message)
        input_sizer.Add(self.message_input, 1, wx.EXPAND | wx.ALL, 5)
        
        send_btn = wx.Button(right_panel, label=_("Send"))
        send_btn.Bind(wx.EVT_BUTTON, self.on_send_message)
        input_sizer.Add(send_btn, 0, wx.ALL, 5)
        
        right_sizer.Add(input_sizer, 0, wx.EXPAND)
        
        right_panel.SetSizer(right_sizer)
        main_sizer.Add(right_panel, 1, wx.EXPAND | wx.ALL, 5)
        
        panel.SetSizer(main_sizer)
        
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
        
        self.message_input.SetFocus()
    
    def update_users_periodically(self, event):
        """Update users list periodically"""
        users = get_online_users()
        if users != [item for item in [self.users_list.GetString(i) for i in range(self.users_list.GetCount())]]:
            self.update_users_list(users)
    
    def update_users_list(self, users):
        """Update the chat users list"""
        self.users_list.Clear()
        for user in users:
            if user['username'] != self.username:  # Don't show self
                self.users_list.Append(user['username'])
    
    def on_user_selected(self, event):
        """Handle user selection"""
        selection = self.users_list.GetSelection()
        if selection != wx.NOT_FOUND:
            self.current_chat_user = self.users_list.GetString(selection)
            self.status_label.SetLabel(_("Private conversation with {}").format(self.current_chat_user))
            self.message_input.SetFocus()
            play_sound('titannet/new_chat.ogg')
        else:
            self.current_chat_user = None
            self.status_label.SetLabel(_("General chat"))
    
    def on_send_message(self, event):
        """Send message to current chat user or group"""
        message = self.message_input.GetValue().strip()
        if not message:
            return
        
        recipient = self.current_chat_user or "group"
        
        # Send message
        if send_message(recipient, message):
            # Display sent message
            timestamp = time.strftime('%H:%M:%S')
            if self.current_chat_user:
                self.chat_display.AppendText(f"[{timestamp}] {self.username} → {self.current_chat_user}: {message}\n")
            else:
                self.chat_display.AppendText(f"[{timestamp}] {self.username}: {message}\n")
            self.message_input.Clear()
        else:
            wx.MessageBox(_("Failed to send message"), _("Error"), wx.OK | wx.ICON_ERROR)
    
    def on_message_received(self, message_data):
        """Handle received message"""
        msg_type = message_data.get('type')
        
        if msg_type == 'new_message':
            sender_username = message_data.get('sender_username')
            message = message_data.get('message')
            timestamp = message_data.get('timestamp', '')
            is_private = message_data.get('is_private', False)
            
            # Format timestamp
            if timestamp:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    time_str = dt.strftime('%H:%M:%S')
                except:
                    time_str = time.strftime('%H:%M:%S')
            else:
                time_str = time.strftime('%H:%M:%S')
            
            # Display message
            if is_private and sender_username == self.current_chat_user:
                self.chat_display.AppendText(f"[{time_str}] {sender_username}: {message}\n")
            elif not is_private:
                self.chat_display.AppendText(f"[{time_str}] {sender_username}: {message}\n")
            
            self.chat_display.SetInsertionPointEnd()
        
        elif msg_type == 'message_sent':
            # Message confirmation - already handled in on_send_message
            pass
        
        elif msg_type == 'chat_history':
            # Not implemented for Telegram (handled automatically by Telegram)
            pass
    
    def on_status_change(self, status_type, data):
        """Handle status changes"""
        if status_type == 'connection_success':
            self.SetStatusText(_("Connected to Telegram"))
    
    def on_disconnect(self, event):
        """Disconnect from server"""
        # Use safe close method
        wx.CallAfter(self.Close)
    
    def on_close(self, event):
        """Handle window close safely"""
        try:
            # Stop timer first
            if hasattr(self, 'update_timer') and self.update_timer:
                try:
                    self.update_timer.Stop()
                except:
                    pass
            
            # Disconnect in background to avoid blocking close
            def safe_disconnect():
                try:
                    disconnect_from_server()
                except Exception as e:
                    print(f"Error during disconnect: {e}")
                
                # Ensure window destruction happens on main thread
                wx.CallAfter(self.Destroy)
            
            # Run disconnect in separate thread
            import threading
            disconnect_thread = threading.Thread(target=safe_disconnect, daemon=True)
            disconnect_thread.start()
            
        except Exception as e:
            print(f"Error during window close: {e}")
            # Force destroy if something goes wrong
            try:
                self.Destroy()
            except:
                pass

def show_telegram_login(parent=None):
    """Show Telegram login dialog"""
    login_dialog = TelegramLoginDialog(parent)
    
    if login_dialog.ShowModal() == wx.ID_OK:
        bot_token, group_chat_id, username = login_dialog.get_credentials()
        login_dialog.Destroy()
        
        if bot_token and username:
            # Connect to Telegram
            if connect_to_server(bot_token, group_chat_id, username):
                # Wait for connection
                max_wait = 30  # 3 seconds
                while max_wait > 0 and not is_connected():
                    time.sleep(0.1)
                    max_wait -= 1
                
                if is_connected():
                    # Show chat window
                    chat_window = TelegramChatWindow(parent, username)
                    chat_window.Show()
                    return chat_window
                else:
                    wx.MessageBox(_("Failed to connect to Telegram"), _("Connection error"), wx.OK | wx.ICON_ERROR)
            else:
                wx.MessageBox(_("Invalid bot token"), _("Error"), wx.OK | wx.ICON_ERROR)
    else:
        login_dialog.Destroy()
    
    return None