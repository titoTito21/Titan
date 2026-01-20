# -*- coding: utf-8 -*-
import wx
import threading
import time
from datetime import datetime
from src.network.messenger_client import messenger_client, connect_to_messenger, disconnect_from_messenger, send_message, get_conversations, is_connected
from src.titan_core.sound import play_sound
from src.titan_core.translation import set_language
from src.settings.settings import get_setting, load_settings
import configparser
import os

# Get translation function
_ = set_language(get_setting('language', 'pl'))

class TitanIMLoginDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Connect to Titan IM"), size=(450, 250))
        
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Info text
        info_text = wx.StaticText(panel, label=_(
            "Connect to Titan IM server for real-time messaging.\n"
            "If server is unavailable, will fallback to web mode."
        ))
        sizer.Add(info_text, 0, wx.ALL, 10)
        
        # Username input
        username_label = wx.StaticText(panel, label=_("Your username:"))
        sizer.Add(username_label, 0, wx.ALL, 5)
        
        self.username_ctrl = wx.TextCtrl(panel)
        self.username_ctrl.SetValue("TitanUser")
        sizer.Add(self.username_ctrl, 0, wx.EXPAND | wx.ALL, 5)
        
        # Server info
        server_label = wx.StaticText(panel, label=_("Server: localhost:8001 (WebSocket), localhost:8000 (HTTP)"))
        server_label.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
        sizer.Add(server_label, 0, wx.ALL, 5)
        
        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        connect_btn = wx.Button(panel, wx.ID_OK, _("Connect"))
        connect_btn.SetDefault()
        button_sizer.Add(connect_btn, 0, wx.ALL, 5)
        
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        button_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        
        sizer.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        
        panel.SetSizer(sizer)
        self.Centre()
        
        # Apply skin settings
        self.apply_skin_settings()
        
        # Focus on username field
        self.username_ctrl.SetFocus()
        self.username_ctrl.SelectAll()
    
    def apply_skin_settings(self):
        """Apply current skin settings to login dialog"""
        try:
            settings = load_settings()
            skin_name = settings.get('interface', {}).get('skin', 'default')
            
            skin_path = os.path.join(os.getcwd(), "skins", skin_name, "skin.ini")
            if os.path.exists(skin_path):
                config = configparser.ConfigParser()
                config.read(skin_path, encoding='utf-8')
                
                colors = dict(config.items('Colors')) if config.has_section('Colors') else {}
                fonts = dict(config.items('Fonts')) if config.has_section('Fonts') else {}
                
                if colors:
                    # Apply background colors
                    frame_bg = colors.get('frame_background_color', '#C0C0C0')
                    def hex_to_wx_colour(hex_color):
                        hex_color = hex_color.lstrip('#')
                        return wx.Colour(int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))
                    
                    self.SetBackgroundColour(hex_to_wx_colour(frame_bg))
                
                if fonts:
                    default_size = int(fonts.get('default_font_size', 9))
                    default_face = fonts.get('default_font_face', 'MS Sans Serif')
                    font = wx.Font(default_size, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, faceName=default_face)
                    self.SetFont(font)
                
                self.Refresh()
        except Exception as e:
            print(f"Error applying skin to login dialog: {e}")
    
    def get_username(self):
        return self.username_ctrl.GetValue().strip() or "TitanUser"

class MessengerChatWindow(wx.Frame):
    def __init__(self, parent, username="Messenger User"):
        super().__init__(parent, title=f"Messenger - {username}", size=(800, 600))
        
        self.username = username
        self.current_chat = None
        self.conversations = []
        
        # Setup GUI
        self.setup_ui()
        
        # Setup callbacks
        messenger_client.add_message_callback(self.on_message_received)
        messenger_client.add_status_callback(self.on_status_change)
        
        self.Centre()
        
        # Update conversations list
        self.load_conversations()
        
        # Auto-refresh timer
        self.update_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.refresh_conversations, self.update_timer)
        self.update_timer.Start(10000)  # Update every 10 seconds
        
        # Bind close event
        self.Bind(wx.EVT_CLOSE, self.on_close)
    
    def setup_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Left panel - Conversations list (similar to Telegram)
        left_panel = wx.Panel(panel)
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Search box
        search_label = wx.StaticText(left_panel, label=_("Search conversations:"))
        left_sizer.Add(search_label, 0, wx.ALL, 5)
        
        self.search_ctrl = wx.TextCtrl(left_panel)
        self.search_ctrl.Bind(wx.EVT_TEXT, self.on_search)
        left_sizer.Add(self.search_ctrl, 0, wx.EXPAND | wx.ALL, 5)
        
        # Conversations list
        conversations_label = wx.StaticText(left_panel, label=_("Conversations:"))
        left_sizer.Add(conversations_label, 0, wx.ALL, 5)
        
        self.conversations_list = wx.ListCtrl(left_panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.conversations_list.AppendColumn(_("Name"), width=150)
        self.conversations_list.AppendColumn(_("Last Message"), width=200)
        self.conversations_list.AppendColumn(_("Time"), width=80)
        self.conversations_list.AppendColumn(_("Unread"), width=60)
        
        self.conversations_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_conversation_select)
        self.conversations_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_conversation_highlight)
        self.conversations_list.Bind(wx.EVT_CHAR_HOOK, self.on_conversations_key)
        left_sizer.Add(self.conversations_list, 1, wx.EXPAND | wx.ALL, 5)
        
        # Connection status
        self.status_label = wx.StaticText(left_panel, label=_("Status: Disconnected"))
        left_sizer.Add(self.status_label, 0, wx.ALL, 5)
        
        left_panel.SetSizer(left_sizer)
        main_sizer.Add(left_panel, 1, wx.EXPAND | wx.ALL, 5)
        
        # Right panel - Chat area
        right_panel = wx.Panel(panel)
        right_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Chat header
        self.chat_header = wx.StaticText(right_panel, label=_("Select a conversation to start chatting"))
        right_sizer.Add(self.chat_header, 0, wx.ALL, 5)
        
        # Messages area
        self.messages_area = wx.TextCtrl(right_panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.messages_area.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        right_sizer.Add(self.messages_area, 1, wx.EXPAND | wx.ALL, 5)
        
        # Message input area
        input_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.message_input = wx.TextCtrl(right_panel, style=wx.TE_PROCESS_ENTER)
        self.message_input.Bind(wx.EVT_TEXT_ENTER, self.on_send_message)
        self.message_input.Enable(False)  # Disabled until chat is selected
        input_sizer.Add(self.message_input, 1, wx.EXPAND | wx.ALL, 5)
        
        self.send_button = wx.Button(right_panel, label=_("Send"))
        self.send_button.Bind(wx.EVT_BUTTON, self.on_send_message)
        self.send_button.Enable(False)  # Disabled until chat is selected
        input_sizer.Add(self.send_button, 0, wx.ALL, 5)
        
        right_sizer.Add(input_sizer, 0, wx.EXPAND)
        
        right_panel.SetSizer(right_sizer)
        main_sizer.Add(right_panel, 2, wx.EXPAND | wx.ALL, 5)
        
        panel.SetSizer(main_sizer)
        
        # Menu bar
        self.create_menu_bar()
    
    def create_menu_bar(self):
        menubar = wx.MenuBar()
        
        # File menu
        file_menu = wx.Menu()
        connect_item = file_menu.Append(wx.ID_ANY, _("Connect to Messenger\tCtrl+N"))
        disconnect_item = file_menu.Append(wx.ID_ANY, _("Disconnect\tCtrl+D"))
        file_menu.AppendSeparator()
        refresh_item = file_menu.Append(wx.ID_ANY, _("Refresh Conversations\tF5"))
        file_menu.AppendSeparator()
        close_item = file_menu.Append(wx.ID_EXIT, _("Close\tCtrl+Q"))
        
        self.Bind(wx.EVT_MENU, self.on_connect, connect_item)
        self.Bind(wx.EVT_MENU, self.on_disconnect, disconnect_item)
        self.Bind(wx.EVT_MENU, self.refresh_conversations, refresh_item)
        self.Bind(wx.EVT_MENU, self.on_close, close_item)
        
        menubar.Append(file_menu, _("File"))
        
        # View menu
        view_menu = wx.Menu()
        open_web_item = view_menu.Append(wx.ID_ANY, _("Open Messenger Web\tCtrl+W"))
        self.Bind(wx.EVT_MENU, self.on_open_web, open_web_item)
        
        menubar.Append(view_menu, _("View"))
        
        self.SetMenuBar(menubar)
        
        # Apply skin settings after UI is created
        self.apply_skin_settings()
    
    def load_skin_data(self, skin_name):
        """Load skin data from skin configuration file"""
        try:
            skin_path = os.path.join(os.getcwd(), "skins", skin_name, "skin.ini")
            if not os.path.exists(skin_path):
                print(f"WARNING: Skin file not found: {skin_path}")
                return {}
            
            config = configparser.ConfigParser()
            config.read(skin_path, encoding='utf-8')
            
            skin_data = {}
            for section_name in config.sections():
                skin_data[section_name] = dict(config.items(section_name))
            
            return skin_data
        except Exception as e:
            print(f"Error loading skin {skin_name}: {e}")
            return {}
    
    def apply_skin_settings(self):
        """Apply current skin settings to messenger window"""
        try:
            settings = load_settings()
            skin_name = settings.get('interface', {}).get('skin', 'default')
            
            skin_data = self.load_skin_data(skin_name)
            if skin_data:
                self.apply_skin(skin_data)
        except Exception as e:
            print(f"Error applying skin to messenger: {e}")
    
    def apply_skin(self, skin_data):
        """Apply skin data to messenger window components"""
        try:
            colors = skin_data.get('Colors', {})
            fonts = skin_data.get('Fonts', {})
            
            if colors:
                # Apply background colors
                frame_bg = colors.get('frame_background_color', '#C0C0C0')
                panel_bg = colors.get('panel_background_color', '#C0C0C0')
                listbox_bg = colors.get('listbox_background_color', '#FFFFFF')
                text_color = colors.get('text_color', '#000000')
                
                # Convert hex colors to wx.Colour
                def hex_to_wx_colour(hex_color):
                    hex_color = hex_color.lstrip('#')
                    return wx.Colour(int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))
                
                # Apply colors to window components
                if hasattr(self, 'conversations_list'):
                    self.conversations_list.SetBackgroundColour(hex_to_wx_colour(listbox_bg))
                    self.conversations_list.Refresh()
                
                if hasattr(self, 'chat_display'):
                    self.chat_display.SetBackgroundColour(hex_to_wx_colour(listbox_bg))
                    self.chat_display.Refresh()
            
            if fonts:
                # Apply font settings
                default_size = int(fonts.get('default_font_size', 9))
                default_face = fonts.get('default_font_face', 'MS Sans Serif')
                
                font = wx.Font(default_size, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, faceName=default_face)
                
                # Apply to various components
                if hasattr(self, 'conversations_list'):
                    self.conversations_list.SetFont(font)
                if hasattr(self, 'chat_display'):
                    self.chat_display.SetFont(font)
                if hasattr(self, 'message_input'):
                    self.message_input.SetFont(font)
            
            # Refresh the window to apply changes
            self.Refresh()
            
        except Exception as e:
            print(f"Error applying messenger skin: {e}")
    
    def load_conversations(self):
        """Load conversations from messenger client"""
        if not is_connected():
            self.status_label.SetLabel(_("Status: Disconnected"))
            return
        
        self.conversations = get_conversations()
        self.refresh_conversations_list()
        self.status_label.SetLabel(_("Status: Connected (Web Mode)"))
    
    def refresh_conversations_list(self):
        """Refresh the conversations list display"""
        self.conversations_list.DeleteAllItems()
        
        search_term = self.search_ctrl.GetValue().lower()
        
        for i, conv in enumerate(self.conversations):
            # Filter by search term
            if search_term and search_term not in conv['name'].lower():
                continue
            
            # Add to list
            index = self.conversations_list.InsertItem(i, conv['name'])
            self.conversations_list.SetItem(index, 1, conv['last_message'][:50] + "..." if len(conv['last_message']) > 50 else conv['last_message'])
            self.conversations_list.SetItem(index, 2, conv['timestamp'])
            self.conversations_list.SetItem(index, 3, str(conv['unread']) if conv['unread'] > 0 else "")
            
            # Store conversation data
            self.conversations_list.SetItemData(index, i)
            
            # Highlight unread conversations
            if conv['unread'] > 0:
                self.conversations_list.SetItemTextColour(index, wx.Colour(0, 0, 255))
    
    def refresh_conversations(self, event=None):
        """Refresh conversations from server"""
        if is_connected():
            self.load_conversations()
    
    def on_search(self, event):
        """Handle search input"""
        self.refresh_conversations_list()
    
    def on_conversation_highlight(self, event):
        """Handle conversation highlight (single click)"""
        selected = event.GetIndex()
        if selected >= 0:
            conv_index = self.conversations_list.GetItemData(selected)
            if conv_index < len(self.conversations):
                conv = self.conversations[conv_index]
                self.chat_header.SetLabel(f"{conv['name']} - {_('Click to open chat')}")
    
    def on_conversation_select(self, event):
        """Handle conversation selection (double click)"""
        selected = event.GetIndex()
        if selected >= 0:
            conv_index = self.conversations_list.GetItemData(selected)
            if conv_index < len(self.conversations):
                self.current_chat = self.conversations[conv_index]
                self.open_chat()
    
    def open_chat(self):
        """Open selected chat"""
        if not self.current_chat:
            return
        
        self.chat_header.SetLabel(f"{_('Chat with')}: {self.current_chat['name']}")
        self.message_input.Enable(True)
        self.send_button.Enable(True)
        self.message_input.SetFocus()
        
        # Load chat history
        self.load_chat_history()
        
        # Mark as read
        messenger_client.mark_conversation_read(self.current_chat['id'])
        
        # Play sound
        play_sound('titannet/chat_opened.ogg')
        
        # Mark as read (visual)
        for i in range(self.conversations_list.GetItemCount()):
            if self.conversations_list.GetItemData(i) == self.conversations.index(self.current_chat):
                self.conversations_list.SetItemTextColour(i, wx.Colour(0, 0, 0))
                self.conversations_list.SetItem(i, 3, "")  # Clear unread count
                break
    
    def load_chat_history(self):
        """Load and display chat history"""
        if not self.current_chat:
            return
        
        history = messenger_client.get_message_history(self.current_chat['id'])
        
        # Clear messages area
        self.messages_area.SetValue("")
        
        if not history:
            self.messages_area.AppendText(_("Chat opened with {}\nNo previous messages.\n\n").format(self.current_chat['name']))
        else:
            self.messages_area.AppendText(_("Chat with {}\n").format(self.current_chat['name']))
            self.messages_area.AppendText("="*50 + "\n\n")
            
            for msg in history:
                sender = msg['sender']
                if msg['is_outgoing']:
                    self.messages_area.AppendText(f"[{msg['timestamp']}] Ty: {msg['message']}\n")
                else:
                    self.messages_area.AppendText(f"[{msg['timestamp']}] {sender}: {msg['message']}\n")
            
            self.messages_area.AppendText("\n" + "="*50 + "\n")
    
    def on_send_message(self, event):
        """Handle send message"""
        if not self.current_chat:
            wx.MessageBox(_("Please select a conversation first"), _("No Chat Selected"), wx.OK | wx.ICON_WARNING)
            return
        
        message = self.message_input.GetValue().strip()
        if not message:
            return
        
        # Send message
        success = send_message(self.current_chat['name'], message)
        
        if success:
            # Add to messages area
            timestamp = datetime.now().strftime("%H:%M")
            self.messages_area.AppendText(f"[{timestamp}] Ty: {message}\n")
            self.message_input.SetValue("")
            play_sound('titannet/message_sent.ogg')
            
            # Refresh conversations to show updated last message
            self.refresh_conversations()
        else:
            wx.MessageBox(_("Failed to send message"), _("Send Error"), wx.OK | wx.ICON_ERROR)
    
    def on_message_received(self, sender, message, conversation_id=None):
        """Handle received message"""
        timestamp = datetime.now().strftime("%H:%M")
        
        # Add to current chat if it's the active conversation
        if self.current_chat and (sender == self.current_chat['name'] or conversation_id == self.current_chat['id']):
            self.messages_area.AppendText(f"[{timestamp}] {sender}: {message}\n")
        
        # Play notification sound
        play_sound('titannet/titannet-notification.ogg')
        
        # Refresh conversations to update last message
        self.refresh_conversations()
    
    def on_status_change(self, status, data):
        """Handle status change"""
        if status == 'titan_connection':
            self.status_label.SetLabel(_("Status: Connected (Titan IM)"))
            self.load_conversations()
        elif status == 'web_connection':
            self.status_label.SetLabel(_("Status: Connected (Web Mode)"))
            self.load_conversations()
        elif status == 'disconnected':
            self.status_label.SetLabel(_("Status: Disconnected"))
            self.conversations_list.DeleteAllItems()
            self.current_chat = None
            self.message_input.Enable(False)
            self.send_button.Enable(False)
    
    def on_connect(self, event):
        """Handle connect menu item"""
        if is_connected():
            wx.MessageBox(_("Already connected to Messenger"), _("Connection Status"), wx.OK | wx.ICON_INFORMATION)
            return
        
        # Show login dialog
        dialog = TitanIMLoginDialog(self)
        if dialog.ShowModal() == wx.ID_OK:
            username = dialog.get_username()
            
            # Try to connect to Titan IM
            success = connect_to_messenger(username)
            if success:
                platform = messenger_client.user_data.get('platform', 'Unknown')
                wx.MessageBox(_("Connected to {}").format(platform), _("Connected"), wx.OK | wx.ICON_INFORMATION)
            else:
                wx.MessageBox(_("Failed to connect"), _("Connection Error"), wx.OK | wx.ICON_ERROR)
        
        dialog.Destroy()
    
    def on_disconnect(self, event):
        """Handle disconnect menu item"""
        if not is_connected():
            wx.MessageBox(_("Not connected to Messenger"), _("Connection Status"), wx.OK | wx.ICON_INFORMATION)
            return
        
        disconnect_from_messenger()
        wx.MessageBox(_("Disconnected from Messenger"), _("Disconnected"), wx.OK | wx.ICON_INFORMATION)
    
    def on_open_web(self, event):
        """Handle open web menu item"""
        messenger_client.open_messenger_web()
    
    def on_close(self, event):
        """Handle window close"""
        if hasattr(self, 'update_timer') and self.update_timer.IsRunning():
            self.update_timer.Stop()
        
        self.Destroy()

class MessengerApp(wx.App):
    def OnInit(self):
        # Auto-connect to messenger (opens web browser)
        connect_to_messenger()
        
        # Create and show main window
        frame = MessengerChatWindow(None)
        frame.Show()
        
        return True

def run_messenger_gui():
    """Run the messenger GUI application"""
    app = MessengerApp()
    app.MainLoop()

if __name__ == '__main__':
    run_messenger_gui()