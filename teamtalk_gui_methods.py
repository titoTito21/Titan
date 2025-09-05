# -*- coding: utf-8 -*-
"""
TeamTalk GUI integration methods for main GUI
"""
import wx
from translation import get_translation_function
from sound import play_sound, play_select_sound, play_focus_sound
import teamtalk
import accessible_output3.outputs.auto

_ = get_translation_function()
speaker = accessible_output3.outputs.auto.Auto()

class TeamTalkGUIIntegration:
    """Mixin class for TeamTalk integration in main GUI"""
    
    def show_teamtalk_window(self):
        """Show TeamTalk main window"""
        try:
            play_select_sound()
            if not hasattr(self, 'teamtalk_window') or not self.teamtalk_window:
                self.teamtalk_window = teamtalk.show_teamtalk_window(self, self.component_manager)
                if self.teamtalk_window:
                    # Set up callbacks for integration
                    self.setup_teamtalk_callbacks()
                    speaker.output(_("TeamTalk window opened"))
                    play_sound("uiopen.ogg")
                else:
                    wx.MessageBox(
                        _("Could not open TeamTalk window. Please check if TeamTalk5 SDK is installed."),
                        _("TeamTalk Error"),
                        wx.OK | wx.ICON_ERROR
                    )
            else:
                # Window already exists, bring to front
                self.teamtalk_window.Raise()
                self.teamtalk_window.SetFocus()
                speaker.output(_("TeamTalk window activated"))
                play_focus_sound()
                
        except Exception as e:
            print(f"Error opening TeamTalk window: {e}")
            wx.MessageBox(
                _("Error opening TeamTalk: {}").format(str(e)),
                _("Error"),
                wx.OK | wx.ICON_ERROR
            )
    
    def show_teamtalk_options(self):
        """Show TeamTalk options when connected"""
        self.app_listbox.Hide()
        self.game_listbox.Hide()
        self.users_listbox.Hide()
        self.chat_display.Hide()
        self.message_input.Hide()
        self.login_panel.Hide()
        
        self.network_listbox.Show()
        self.network_listbox.Clear()
        
        # Show TeamTalk specific options
        self.network_listbox.Append(_("Channels"))
        self.network_listbox.Append(_("Users"))
        self.network_listbox.Append(_("Settings"))
        self.network_listbox.Append(_("Disconnect"))
        self.network_listbox.Append(_("Back to main menu"))
        
        self.list_label.SetLabel(_("TeamTalk Options"))
        self.current_list = "teamtalk_options"
        play_sound("popup.ogg")
        self.Layout()
        
        if self.network_listbox.GetCount() > 0:
            self.network_listbox.SetFocus()
    
    def show_teamtalk_channels(self):
        """Show TeamTalk channels list"""
        self.app_listbox.Hide()
        self.game_listbox.Hide()
        self.network_listbox.Hide()
        self.chat_display.Hide()
        self.message_input.Hide()
        self.login_panel.Hide()
        
        self.users_listbox.Show()
        self.users_listbox.Clear()
        
        # Get channels from TeamTalk client
        if self.teamtalk_client:
            channels = self.teamtalk_client.get_channels()
            for channel_id, channel in channels.items():
                user_count = len(self.teamtalk_client.get_channel_users(channel_id))
                channel_text = f"{channel['name']} ({user_count} {_('users')})"
                if channel_id == self.teamtalk_client.current_channel:
                    channel_text += f" - {_('current')}"
                self.users_listbox.Append(channel_text)
        
        self.list_label.SetLabel(_("TeamTalk Channels"))
        self.current_list = "teamtalk_channels"
        play_sound("popup.ogg")
        self.Layout()
        
        if self.users_listbox.GetCount() > 0:
            self.users_listbox.SetFocus()
        else:
            self.users_listbox.Append(_("No channels available"))
    
    def show_teamtalk_users(self):
        """Show TeamTalk users list"""
        self.app_listbox.Hide()
        self.game_listbox.Hide()
        self.network_listbox.Hide()
        self.chat_display.Hide()
        self.message_input.Hide()
        self.login_panel.Hide()
        
        self.users_listbox.Show()
        self.users_listbox.Clear()
        
        # Get users from TeamTalk client
        if self.teamtalk_client:
            if self.teamtalk_client.current_channel:
                # Show users in current channel
                users = self.teamtalk_client.get_channel_users(self.teamtalk_client.current_channel)
                self.list_label.SetLabel(_("Users in Channel"))
            else:
                # Show all users
                users = list(self.teamtalk_client.get_users().values())
                self.list_label.SetLabel(_("All TeamTalk Users"))
            
            for user in users:
                user_text = user['nickname']
                if user['id'] == self.teamtalk_client.tt.getMyUserID() if self.teamtalk_client.tt else -1:
                    user_text += f" - {_('you')}"
                self.users_listbox.Append(user_text)
        
        self.current_list = "teamtalk_users"
        play_sound("popup.ogg")
        self.Layout()
        
        if self.users_listbox.GetCount() > 0:
            self.users_listbox.SetFocus()
        else:
            self.users_listbox.Append(_("No users available"))
    
    def show_teamtalk_settings(self):
        """Show TeamTalk settings dialog"""
        play_select_sound()
        
        # Create simple settings dialog
        dlg = wx.Dialog(self, title=_("TeamTalk Settings"))
        panel = wx.Panel(dlg)
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Get current configuration
        config = teamtalk.get_teamtalk_config()
        server_config = config.get('server', {})
        user_config = config.get('user', {})
        
        # Server settings
        server_box = wx.StaticBox(panel, label=_("Server Settings"))
        server_sizer = wx.StaticBoxSizer(server_box, wx.VERTICAL)
        
        # Host
        host_label = wx.StaticText(panel, label=_("Server Host:"))
        host_ctrl = wx.TextCtrl(panel, value=server_config.get('host', 'localhost'))
        server_sizer.Add(host_label, 0, wx.ALL, 5)
        server_sizer.Add(host_ctrl, 0, wx.EXPAND | wx.ALL, 5)
        
        # TCP Port
        tcp_label = wx.StaticText(panel, label=_("TCP Port:"))
        tcp_ctrl = wx.SpinCtrl(panel, value=str(server_config.get('tcpport', 10333)), min=1, max=65535)
        server_sizer.Add(tcp_label, 0, wx.ALL, 5)
        server_sizer.Add(tcp_ctrl, 0, wx.EXPAND | wx.ALL, 5)
        
        # UDP Port
        udp_label = wx.StaticText(panel, label=_("UDP Port:"))
        udp_ctrl = wx.SpinCtrl(panel, value=str(server_config.get('udpport', 10333)), min=1, max=65535)
        server_sizer.Add(udp_label, 0, wx.ALL, 5)
        server_sizer.Add(udp_ctrl, 0, wx.EXPAND | wx.ALL, 5)
        
        # Encrypted connection
        encrypt_cb = wx.CheckBox(panel, label=_("Use encrypted connection"))
        encrypt_cb.SetValue(server_config.get('encrypted', False))
        server_sizer.Add(encrypt_cb, 0, wx.ALL, 5)
        
        # User settings
        user_box = wx.StaticBox(panel, label=_("User Settings"))
        user_sizer = wx.StaticBoxSizer(user_box, wx.VERTICAL)
        
        # Nickname
        nick_label = wx.StaticText(panel, label=_("Nickname:"))
        nick_ctrl = wx.TextCtrl(panel, value=user_config.get('nickname', 'TitanUser'))
        user_sizer.Add(nick_label, 0, wx.ALL, 5)
        user_sizer.Add(nick_ctrl, 0, wx.EXPAND | wx.ALL, 5)
        
        # Password
        pass_label = wx.StaticText(panel, label=_("Password (optional):"))
        pass_ctrl = wx.TextCtrl(panel, value=user_config.get('password', ''), style=wx.TE_PASSWORD)
        user_sizer.Add(pass_label, 0, wx.ALL, 5)
        user_sizer.Add(pass_ctrl, 0, wx.EXPAND | wx.ALL, 5)
        
        # Buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        ok_btn = wx.Button(panel, wx.ID_OK, _("Save"))
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        btn_sizer.Add(ok_btn, 0, wx.ALL, 5)
        btn_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        
        # Layout
        sizer.Add(server_sizer, 0, wx.EXPAND | wx.ALL, 10)
        sizer.Add(user_sizer, 0, wx.EXPAND | wx.ALL, 10)
        sizer.Add(btn_sizer, 0, wx.CENTER | wx.ALL, 10)
        
        panel.SetSizer(sizer)
        dlg.SetSize((400, 500))
        dlg.Centre()
        
        # Show dialog
        result = dlg.ShowModal()
        if result == wx.ID_OK:
            # Save settings
            try:
                teamtalk.set_teamtalk_server(
                    host_ctrl.GetValue(),
                    tcp_ctrl.GetValue(),
                    udp_ctrl.GetValue(),
                    encrypt_cb.GetValue()
                )
                teamtalk.set_teamtalk_user(
                    nick_ctrl.GetValue(),
                    pass_ctrl.GetValue()
                )
                
                wx.MessageBox(
                    _("TeamTalk settings saved successfully."),
                    _("Settings Saved"),
                    wx.OK | wx.ICON_INFORMATION
                )
                play_sound("configuring.WAV")
                speaker.output(_("TeamTalk settings saved"))
                
            except Exception as e:
                wx.MessageBox(
                    _("Error saving TeamTalk settings: {}").format(str(e)),
                    _("Error"),
                    wx.OK | wx.ICON_ERROR
                )
        
        dlg.Destroy()
    
    def disconnect_from_teamtalk(self):
        """Disconnect from TeamTalk server"""
        play_select_sound()
        
        if self.teamtalk_client:
            try:
                self.teamtalk_client.disconnect()
                speaker.output(_("Disconnected from TeamTalk server"))
                play_sound("popupclose.ogg")
                
                # Remove from active services
                if "teamtalk" in self.active_services:
                    del self.active_services["teamtalk"]
                
                # Clear client reference
                self.teamtalk_client = None
                
                # Close TeamTalk window if open
                if self.teamtalk_window:
                    self.teamtalk_window.Close()
                    self.teamtalk_window = None
                
                # Return to network list
                self.show_network_list()
                
            except Exception as e:
                print(f"Error disconnecting from TeamTalk: {e}")
                wx.MessageBox(
                    _("Error disconnecting from TeamTalk: {}").format(str(e)),
                    _("Error"),
                    wx.OK | wx.ICON_ERROR
                )
        else:
            speaker.output(_("Not connected to TeamTalk"))
    
    def setup_teamtalk_callbacks(self):
        """Set up callbacks for TeamTalk integration"""
        if not self.teamtalk_window or not self.teamtalk_window.client:
            return
        
        client = self.teamtalk_window.client
        self.teamtalk_client = client
        
        # Add connection callback
        def on_teamtalk_connection(success, message):
            if success and client.logged_in:
                # Add to active services
                user_data = {
                    'nickname': client.config.get('user', {}).get('nickname', 'user'),
                    'server': client.config.get('server', {}).get('host', 'localhost')
                }
                self.active_services["teamtalk"] = {
                    'client': client,
                    'user_data': user_data
                }
                
                # Update network list
                wx.CallAfter(self.populate_network_list)
                
                # Play connection sound
                play_sound("titannet/titannet_success.ogg")
                wx.CallAfter(speaker.output, _("Connected to TeamTalk server"))
            elif not success:
                # Play error sound
                play_sound("error.ogg")
                wx.CallAfter(speaker.output, message)
        
        # Add message callback
        def on_teamtalk_message(message_data, msg_type="room"):
            if msg_type == "private":
                play_sound("titannet/new_message.ogg")
            else:
                play_sound("titannet/chat_message.ogg")
        
        # Add user status callback  
        def on_teamtalk_user_status(user_id, status):
            if status == 'login':
                play_sound("user_online.ogg")
            elif status == 'logout':
                play_sound("user_offline.ogg")
            elif status == 'joined_channel':
                play_sound("titannet/new_chat.ogg")
        
        # Register callbacks
        client.add_callback('connection', on_teamtalk_connection)
        client.add_callback('message', on_teamtalk_message)  
        client.add_callback('user_status', on_teamtalk_user_status)