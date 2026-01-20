"""
Titan-Net GUI - Full WebSocket Client
Complete messaging interface with private messages, chat rooms, and online users
"""
import wx
import threading
import accessible_output3.outputs.auto
from src.network.titan_net import TitanNetClient
from src.titan_core.sound import play_sound
from src.titan_core.translation import set_language
from src.settings.settings import get_setting
from src.titan_core.stereo_speech import get_stereo_speech

# Get the translation function
_ = set_language(get_setting('language', 'pl'))

speaker = accessible_output3.outputs.auto.Auto()
stereo_speech = get_stereo_speech()


class LoginDialog(wx.Dialog):
    """Login dialog for Titan-Net"""

    def __init__(self, parent, titan_client: TitanNetClient):
        super().__init__(parent, title=_("Titan-Net Login"), size=(400, 300))

        self.titan_client = titan_client
        self.logged_in = False
        self.offline_mode = False

        self.InitUI()
        self.Centre()

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

        # Offline mode checkbox
        self.offline_checkbox = wx.CheckBox(panel, label=_("I don't use Titan-Net"))
        self.offline_checkbox.Bind(wx.EVT_CHECKBOX, self.OnOfflineToggle)
        self.offline_checkbox.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.offline_checkbox, flag=wx.LEFT | wx.TOP, border=10)

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

        self.offline_button = wx.Button(panel, wx.ID_CANCEL, _("Continue in Offline Mode"))
        self.offline_button.Bind(wx.EVT_BUTTON, self.OnOfflineMode)
        self.offline_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.offline_button.Hide()
        button_box.Add(self.offline_button, flag=wx.RIGHT, border=10)

        vbox.Add(button_box, flag=wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, border=20)

        panel.SetSizer(vbox)

    def OnFocus(self, event):
        """Handle focus events with sound"""
        play_sound('core/FOCUS.ogg', position=0.5)
        event.Skip()

    def OnOfflineToggle(self, event):
        """Toggle offline mode UI"""
        is_offline = self.offline_checkbox.GetValue()

        if is_offline:
            self.username_text.Enable(False)
            self.password_text.Enable(False)
            self.create_account_button.Hide()
            self.login_button.Hide()
            self.offline_button.Show()
        else:
            self.username_text.Enable(True)
            self.password_text.Enable(True)
            self.create_account_button.Show()
            self.login_button.Show()
            self.offline_button.Hide()

        self.Layout()
        play_sound('core/SELECT.ogg')

    def OnCreateAccount(self, event):
        """Open create account dialog"""
        play_sound('core/SELECT.ogg')

        dialog = CreateAccountDialog(self, self.titan_client)
        result = dialog.ShowModal()

        if result == wx.ID_OK:
            username = dialog.username
            password = dialog.password

            self.username_text.SetValue(username)
            self.password_text.SetValue(password)

            stereo_speech.speak(_("Account created. You can now login."), position=0.5)

        dialog.Destroy()

    def OnLogin(self, event):
        """Handle login button"""
        play_sound('core/SELECT.ogg')

        username = self.username_text.GetValue().strip()
        password = self.password_text.GetValue()

        if not username or not password:
            stereo_speech.speak(_("Please enter username and password"), position=0.5)
            play_sound('core/error.ogg')
            return

        self.login_button.Enable(False)
        self.create_account_button.Enable(False)

        stereo_speech.speak(_("Connecting to Titan-Net..."), position=0.5)
        play_sound('system/connecting.ogg')

        def login_thread():
            try:
                result = self.titan_client.login(username, password)
                wx.CallAfter(self.OnLoginComplete, result)
            except Exception as e:
                wx.CallAfter(self.OnLoginComplete, {
                    'success': False,
                    'message': f"Error: {str(e)}"
                })

        thread = threading.Thread(target=login_thread, daemon=True)
        thread.start()

    def OnLoginComplete(self, result):
        """Handle login completion"""
        self.login_button.Enable(True)
        self.create_account_button.Enable(True)

        if result.get('success'):
            stereo_speech.speak(_("Login successful"), position=0.5)
            play_sound('system/user_online.ogg')

            username = self.titan_client.username
            if username:
                login_message = _("Logged in as: {username}").format(username=username)
                stereo_speech.speak(login_message, position=0.5)

            self.logged_in = True
            self.EndModal(wx.ID_OK)
        else:
            error_message = result.get('message', _("Login failed"))
            stereo_speech.speak(error_message, position=0.5)
            play_sound('core/error.ogg')

    def OnOfflineMode(self, event):
        """Continue in offline mode"""
        play_sound('core/SELECT.ogg')
        stereo_speech.speak(_("Continuing in offline mode"), position=0.5)

        self.offline_mode = True
        self.EndModal(wx.ID_OK)


class CreateAccountDialog(wx.Dialog):
    """Create account dialog for Titan-Net"""

    def __init__(self, parent, titan_client: TitanNetClient):
        super().__init__(parent, title=_("Create Titan-Net Account"), size=(400, 350))

        self.titan_client = titan_client
        self.username = None
        self.password = None

        self.InitUI()
        self.Centre()

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

    def OnFocus(self, event):
        """Handle focus events with sound"""
        play_sound('core/FOCUS.ogg', position=0.5)
        event.Skip()

    def OnCreateAccount(self, event):
        """Handle create account button"""
        play_sound('core/SELECT.ogg')

        username = self.username_text.GetValue().strip()
        password = self.password_text.GetValue()
        firstname = self.firstname_text.GetValue().strip()
        lastname = self.lastname_text.GetValue().strip()

        if not username or not password:
            stereo_speech.speak(_("Username and password are required"), position=0.5)
            play_sound('core/error.ogg')
            return

        full_name = " ".join(filter(None, [firstname, lastname]))

        self.create_button.Enable(False)

        stereo_speech.speak(_("Creating account..."), position=0.5)
        play_sound('system/connecting.ogg')

        def register_thread():
            try:
                result = self.titan_client.register(username, password, full_name)
                wx.CallAfter(self.OnRegistrationComplete, result, username, password)
            except Exception as e:
                wx.CallAfter(self.OnRegistrationComplete, {
                    'success': False,
                    'message': f"Error: {str(e)}"
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
            stereo_speech.speak(message, position=0.5)

            play_sound('titannet/account_created.ogg')

            self.username = username
            self.password = password

            wx.CallLater(2000, lambda: self.EndModal(wx.ID_OK))
        else:
            error_message = result.get('message', _("Registration failed"))
            stereo_speech.speak(error_message, position=0.5)
            play_sound('core/error.ogg')

    def OnCancel(self, event):
        """Handle cancel button"""
        play_sound('core/SELECT.ogg')
        self.EndModal(wx.ID_CANCEL)


class TitanNetMainWindow(wx.Frame):
    """Main Titan-Net messaging window"""

    def __init__(self, parent, titan_client: TitanNetClient):
        super().__init__(parent, title=_("Titan-Net"), size=(800, 600))

        self.titan_client = titan_client
        self.current_room = None
        self.current_private_user = None

        self.InitUI()
        self.Centre()

        # Setup callbacks
        self.setup_callbacks()

        # Load initial data
        wx.CallAfter(self.load_initial_data)

        play_sound('ui/window_open.ogg')

    def InitUI(self):
        """Initialize UI"""
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # User info at top
        user_info = _("Logged in as: {username} (#{titan_number})").format(
            username=self.titan_client.username,
            titan_number=self.titan_client.titan_number
        )
        self.user_label = wx.StaticText(panel, label=user_info)
        vbox.Add(self.user_label, flag=wx.ALL | wx.EXPAND, border=5)

        # Notebook for tabs
        self.notebook = wx.Notebook(panel)

        # Tab 1: Chat Rooms
        self.rooms_panel = self.create_rooms_panel()
        self.notebook.AddPage(self.rooms_panel, _("Chat Rooms"))

        # Tab 2: Private Messages
        self.pm_panel = self.create_private_messages_panel()
        self.notebook.AddPage(self.pm_panel, _("Private Messages"))

        # Tab 3: Online Users
        self.users_panel = self.create_users_panel()
        self.notebook.AddPage(self.users_panel, _("Online Users"))

        vbox.Add(self.notebook, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        # Disconnect button
        disconnect_btn = wx.Button(panel, label=_("Disconnect"))
        disconnect_btn.Bind(wx.EVT_BUTTON, self.OnDisconnect)
        vbox.Add(disconnect_btn, flag=wx.ALL | wx.ALIGN_CENTER, border=5)

        panel.SetSizer(vbox)

    def create_rooms_panel(self):
        """Create chat rooms panel"""
        panel = wx.Panel(self.notebook)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Rooms list
        rooms_label = wx.StaticText(panel, label=_("Available Rooms:"))
        vbox.Add(rooms_label, flag=wx.ALL, border=5)

        self.rooms_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.rooms_list.AppendColumn(_("Name"), width=200)
        self.rooms_list.AppendColumn(_("Type"), width=100)
        self.rooms_list.AppendColumn(_("Members"), width=80)
        self.rooms_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.OnRoomDoubleClick)
        vbox.Add(self.rooms_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        # Room buttons
        room_btn_box = wx.BoxSizer(wx.HORIZONTAL)

        create_room_btn = wx.Button(panel, label=_("Create Room"))
        create_room_btn.Bind(wx.EVT_BUTTON, self.OnCreateRoom)
        room_btn_box.Add(create_room_btn, flag=wx.RIGHT, border=5)

        join_room_btn = wx.Button(panel, label=_("Join Room"))
        join_room_btn.Bind(wx.EVT_BUTTON, self.OnJoinRoom)
        room_btn_box.Add(join_room_btn, flag=wx.RIGHT, border=5)

        refresh_rooms_btn = wx.Button(panel, label=_("Refresh"))
        refresh_rooms_btn.Bind(wx.EVT_BUTTON, self.OnRefreshRooms)
        room_btn_box.Add(refresh_rooms_btn, flag=wx.RIGHT, border=5)

        vbox.Add(room_btn_box, flag=wx.ALL | wx.ALIGN_CENTER, border=5)

        # Room chat area (hidden until room joined)
        self.room_chat_box = wx.BoxSizer(wx.VERTICAL)

        room_chat_label = wx.StaticText(panel, label=_("Room Chat:"))
        self.room_chat_box.Add(room_chat_label, flag=wx.ALL, border=5)

        self.room_messages = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
        self.room_chat_box.Add(self.room_messages, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        room_input_box = wx.BoxSizer(wx.HORIZONTAL)

        self.room_input = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.room_input.Bind(wx.EVT_TEXT_ENTER, self.OnSendRoomMessage)
        room_input_box.Add(self.room_input, proportion=1, flag=wx.RIGHT, border=5)

        send_room_btn = wx.Button(panel, label=_("Send"))
        send_room_btn.Bind(wx.EVT_BUTTON, self.OnSendRoomMessage)
        room_input_box.Add(send_room_btn)

        self.room_chat_box.Add(room_input_box, flag=wx.EXPAND | wx.ALL, border=5)

        leave_room_btn = wx.Button(panel, label=_("Leave Room"))
        leave_room_btn.Bind(wx.EVT_BUTTON, self.OnLeaveRoom)
        self.room_chat_box.Add(leave_room_btn, flag=wx.ALL | wx.ALIGN_CENTER, border=5)

        # Hide room chat initially
        self.room_chat_box.ShowItems(False)

        vbox.Add(self.room_chat_box, proportion=1, flag=wx.EXPAND)

        panel.SetSizer(vbox)
        return panel

    def create_private_messages_panel(self):
        """Create private messages panel"""
        panel = wx.Panel(self.notebook)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # User selection
        user_select_label = wx.StaticText(panel, label=_("Send message to:"))
        vbox.Add(user_select_label, flag=wx.ALL, border=5)

        user_box = wx.BoxSizer(wx.HORIZONTAL)

        self.pm_user_choice = wx.Choice(panel)
        user_box.Add(self.pm_user_choice, proportion=1, flag=wx.RIGHT, border=5)

        select_user_btn = wx.Button(panel, label=_("Select"))
        select_user_btn.Bind(wx.EVT_BUTTON, self.OnSelectPMUser)
        user_box.Add(select_user_btn)

        vbox.Add(user_box, flag=wx.EXPAND | wx.ALL, border=5)

        # Messages area
        pm_label = wx.StaticText(panel, label=_("Private Messages:"))
        vbox.Add(pm_label, flag=wx.ALL, border=5)

        self.pm_messages = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP)
        vbox.Add(self.pm_messages, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        # Input area
        pm_input_box = wx.BoxSizer(wx.HORIZONTAL)

        self.pm_input = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.pm_input.Bind(wx.EVT_TEXT_ENTER, self.OnSendPrivateMessage)
        pm_input_box.Add(self.pm_input, proportion=1, flag=wx.RIGHT, border=5)

        send_pm_btn = wx.Button(panel, label=_("Send"))
        send_pm_btn.Bind(wx.EVT_BUTTON, self.OnSendPrivateMessage)
        pm_input_box.Add(send_pm_btn)

        vbox.Add(pm_input_box, flag=wx.EXPAND | wx.ALL, border=5)

        panel.SetSizer(vbox)
        return panel

    def create_users_panel(self):
        """Create online users panel"""
        panel = wx.Panel(self.notebook)
        vbox = wx.BoxSizer(wx.VERTICAL)

        users_label = wx.StaticText(panel, label=_("Online Users:"))
        vbox.Add(users_label, flag=wx.ALL, border=5)

        self.users_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.users_list.AppendColumn(_("Username"), width=200)
        self.users_list.AppendColumn(_("Titan Number"), width=100)
        self.users_list.AppendColumn(_("Full Name"), width=200)
        self.users_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.OnUserDoubleClick)
        vbox.Add(self.users_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        # Buttons
        user_btn_box = wx.BoxSizer(wx.HORIZONTAL)

        message_user_btn = wx.Button(panel, label=_("Send Message"))
        message_user_btn.Bind(wx.EVT_BUTTON, self.OnMessageUser)
        user_btn_box.Add(message_user_btn, flag=wx.RIGHT, border=5)

        refresh_users_btn = wx.Button(panel, label=_("Refresh"))
        refresh_users_btn.Bind(wx.EVT_BUTTON, self.OnRefreshUsers)
        user_btn_box.Add(refresh_users_btn, flag=wx.RIGHT, border=5)

        vbox.Add(user_btn_box, flag=wx.ALL | wx.ALIGN_CENTER, border=5)

        panel.SetSizer(vbox)
        return panel

    def setup_callbacks(self):
        """Setup Titan-Net callbacks"""
        self.titan_client.on_room_message = self.on_room_message
        self.titan_client.on_message_received = self.on_private_message
        self.titan_client.on_user_online = self.on_user_online
        self.titan_client.on_user_offline = self.on_user_offline
        self.titan_client.on_room_created = self.on_room_created
        self.titan_client.on_room_deleted = self.on_room_deleted
        self.titan_client.on_user_joined_room = self.on_user_joined_room
        self.titan_client.on_user_left_room = self.on_user_left_room
        self.titan_client.on_account_created = self.on_account_created

    def load_initial_data(self):
        """Load rooms and users"""
        self.refresh_rooms()
        self.refresh_users()

    def refresh_rooms(self):
        """Refresh rooms list"""
        def _refresh():
            result = self.titan_client.get_rooms()
            wx.CallAfter(self._update_rooms_list, result)

        thread = threading.Thread(target=_refresh, daemon=True)
        thread.start()

    def _update_rooms_list(self, result):
        """Update rooms list in UI"""
        self.rooms_list.DeleteAllItems()

        if result.get('success'):
            rooms = result.get('rooms', [])
            for room in rooms:
                index = self.rooms_list.InsertItem(self.rooms_list.GetItemCount(), room['name'])
                self.rooms_list.SetItem(index, 1, room['room_type'])
                self.rooms_list.SetItem(index, 2, str(room['member_count']))
                self.rooms_list.SetItemData(index, room['id'])

    def refresh_users(self):
        """Refresh online users list"""
        def _refresh():
            result = self.titan_client.get_online_users()
            wx.CallAfter(self._update_users_list, result)

        thread = threading.Thread(target=_refresh, daemon=True)
        thread.start()

    def _update_users_list(self, result):
        """Update users list in UI"""
        self.users_list.DeleteAllItems()
        self.pm_user_choice.Clear()

        if result.get('success'):
            users = result.get('users', [])
            for user in users:
                # Don't show self
                if user['id'] == self.titan_client.user_id:
                    continue

                index = self.users_list.InsertItem(self.users_list.GetItemCount(), user['username'])
                self.users_list.SetItem(index, 1, str(user['titan_number']))
                self.users_list.SetItem(index, 2, user.get('full_name', ''))
                self.users_list.SetItemData(index, user['id'])

                # Add to PM choice
                self.pm_user_choice.Append(f"{user['username']} (#{user['titan_number']})", user['id'])

    def OnRefreshRooms(self, event):
        """Refresh rooms button"""
        play_sound('core/SELECT.ogg')
        self.refresh_rooms()

    def OnRefreshUsers(self, event):
        """Refresh users button"""
        play_sound('core/SELECT.ogg')
        self.refresh_users()

    def OnCreateRoom(self, event):
        """Create new room"""
        play_sound('core/SELECT.ogg')

        dlg = wx.TextEntryDialog(self, _("Enter room name:"), _("Create Room"))
        if dlg.ShowModal() == wx.ID_OK:
            room_name = dlg.GetValue().strip()
            if room_name:
                def _create():
                    result = self.titan_client.create_room(room_name)
                    wx.CallAfter(self._on_room_created, result)

                thread = threading.Thread(target=_create, daemon=True)
                thread.start()

        dlg.Destroy()

    def _on_room_created(self, result):
        """Handle room creation result"""
        if result.get('success'):
            stereo_speech.speak(_("Room created"), position=0.5)
            play_sound('titannet/room_created.ogg')
            self.refresh_rooms()
        else:
            stereo_speech.speak(result.get('message', _("Failed to create room")), position=0.5)
            play_sound('core/error.ogg')

    def OnJoinRoom(self, event):
        """Join selected room"""
        play_sound('core/SELECT.ogg')

        selected = self.rooms_list.GetFirstSelected()
        if selected == -1:
            stereo_speech.speak(_("Please select a room"), position=0.5)
            play_sound('core/error.ogg')
            return

        room_id = self.rooms_list.GetItemData(selected)
        room_name = self.rooms_list.GetItemText(selected)

        def _join():
            result = self.titan_client.join_room(room_id)
            wx.CallAfter(self._on_room_joined, result, room_id, room_name)

        thread = threading.Thread(target=_join, daemon=True)
        thread.start()

    def _on_room_joined(self, result, room_id, room_name):
        """Handle room join result"""
        if result.get('success'):
            self.current_room = room_id
            stereo_speech.speak(_("Joined room: {name}").format(name=room_name), position=0.5)
            play_sound('titannet/room_joined.ogg')

            # Show room chat
            self.room_chat_box.ShowItems(True)
            self.rooms_panel.Layout()

            # Load room messages
            def _load():
                msgs_result = self.titan_client.get_room_messages(room_id)
                wx.CallAfter(self._display_room_messages, msgs_result)

            thread = threading.Thread(target=_load, daemon=True)
            thread.start()
        else:
            stereo_speech.speak(result.get('message', _("Failed to join room")), position=0.5)
            play_sound('core/error.ogg')

    def _display_room_messages(self, result):
        """Display room messages"""
        if result.get('success'):
            messages = result.get('messages', [])
            self.room_messages.Clear()

            # Messages are in reverse order (newest first), so reverse them
            for msg in reversed(messages):
                timestamp = msg['sent_at'].split('T')[1][:5]  # Get HH:MM
                text = f"[{timestamp}] {msg['username']}: {msg['message']}\n"
                self.room_messages.AppendText(text)

    def OnLeaveRoom(self, event):
        """Leave current room"""
        play_sound('core/SELECT.ogg')

        if self.current_room:
            def _leave():
                result = self.titan_client.leave_room(self.current_room)
                wx.CallAfter(self._on_room_left, result)

            thread = threading.Thread(target=_leave, daemon=True)
            thread.start()

    def _on_room_left(self, result):
        """Handle room leave result"""
        self.current_room = None
        self.room_chat_box.ShowItems(False)
        self.room_messages.Clear()
        self.room_input.Clear()
        self.rooms_panel.Layout()

        stereo_speech.speak(_("Left room"), position=0.5)
        play_sound('titannet/room_left.ogg')

    def OnSendRoomMessage(self, event):
        """Send message to room"""
        if not self.current_room:
            return

        message = self.room_input.GetValue().strip()
        if not message:
            return

        play_sound('core/SELECT.ogg')

        def _send():
            result = self.titan_client.send_room_message(self.current_room, message)

        thread = threading.Thread(target=_send, daemon=True)
        thread.start()

        # Add own message to display
        timestamp = wx.DateTime.Now().Format("%H:%M")
        text = f"[{timestamp}] {self.titan_client.username}: {message}\n"
        self.room_messages.AppendText(text)

        self.room_input.Clear()

    def OnRoomDoubleClick(self, event):
        """Double click on room to join"""
        self.OnJoinRoom(event)

    def OnSelectPMUser(self, event):
        """Select user for private messages"""
        play_sound('core/SELECT.ogg')

        selection = self.pm_user_choice.GetSelection()
        if selection == wx.NOT_FOUND:
            stereo_speech.speak(_("Please select a user"), position=0.5)
            play_sound('core/error.ogg')
            return

        user_id = self.pm_user_choice.GetClientData(selection)
        self.current_private_user = user_id

        stereo_speech.speak(_("Loading messages..."), position=0.5)

        def _load():
            result = self.titan_client.get_private_messages(user_id)
            wx.CallAfter(self._display_private_messages, result)

        thread = threading.Thread(target=_load, daemon=True)
        thread.start()

    def _display_private_messages(self, result):
        """Display private messages"""
        if result.get('success'):
            messages = result.get('messages', [])
            self.pm_messages.Clear()

            for msg in reversed(messages):
                timestamp = msg['sent_at'].split('T')[1][:5]
                sender = msg['sender_username']
                text = f"[{timestamp}] {sender}: {msg['message']}\n"
                self.pm_messages.AppendText(text)

            stereo_speech.speak(_("Messages loaded"), position=0.5)

    def OnSendPrivateMessage(self, event):
        """Send private message"""
        if not self.current_private_user:
            stereo_speech.speak(_("Please select a user first"), position=0.5)
            play_sound('core/error.ogg')
            return

        message = self.pm_input.GetValue().strip()
        if not message:
            return

        play_sound('core/SELECT.ogg')

        def _send():
            result = self.titan_client.send_private_message(self.current_private_user, message)

        thread = threading.Thread(target=_send, daemon=True)
        thread.start()

        # Add own message to display
        timestamp = wx.DateTime.Now().Format("%H:%M")
        text = f"[{timestamp}] {self.titan_client.username}: {message}\n"
        self.pm_messages.AppendText(text)

        self.pm_input.Clear()

    def OnUserDoubleClick(self, event):
        """Double click on user to message"""
        selected = self.users_list.GetFirstSelected()
        if selected == -1:
            return

        user_id = self.users_list.GetItemData(selected)
        username = self.users_list.GetItemText(selected)

        # Switch to PM tab and select user
        self.notebook.SetSelection(1)  # PM tab

        # Find user in choice
        for i in range(self.pm_user_choice.GetCount()):
            if self.pm_user_choice.GetClientData(i) == user_id:
                self.pm_user_choice.SetSelection(i)
                self.OnSelectPMUser(None)
                break

    def OnMessageUser(self, event):
        """Message selected user"""
        self.OnUserDoubleClick(event)

    def OnDisconnect(self, event):
        """Disconnect from server"""
        play_sound('core/SELECT.ogg')

        self.titan_client.logout()
        self.Close()

    # Callbacks from TitanNetClient
    def on_room_message(self, message):
        """Handle incoming room message"""
        if message.get('room_id') == self.current_room:
            wx.CallAfter(self._append_room_message, message)

    def _append_room_message(self, message):
        """Append room message to display"""
        timestamp = message['sent_at'].split('T')[1][:5]
        text = f"[{timestamp}] {message['username']}: {message['message']}\n"
        self.room_messages.AppendText(text)

        play_sound('titannet/new_message.ogg')

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
        timestamp = message['sent_at'].split('T')[1][:5]
        text = f"[{timestamp}] {message['sender_username']}: {message['message']}\n"
        self.pm_messages.AppendText(text)

        play_sound('titannet/new_message.ogg')

    def _notify_new_pm(self, message):
        """Notify about new PM"""
        play_sound('titannet/new_message.ogg')
        stereo_speech.speak(_("New message from {user}").format(user=message['sender_username']), position=0.5)

    def on_user_online(self, username):
        """User came online"""
        wx.CallAfter(self.refresh_users)
        play_sound('system/user_online.ogg')

    def on_user_offline(self, username):
        """User went offline"""
        wx.CallAfter(self.refresh_users)
        play_sound('system/user_offline.ogg')

    def on_room_created(self, message):
        """New room created"""
        wx.CallAfter(self.refresh_rooms)

    def on_room_deleted(self, room_id):
        """Room deleted"""
        wx.CallAfter(self.refresh_rooms)
        if self.current_room == room_id:
            self._on_room_left({})

    def on_user_joined_room(self, message):
        """User joined room"""
        if message.get('room_id') == self.current_room:
            text = f"*** {message['username']} {_('joined the room')}\n"
            wx.CallAfter(self.room_messages.AppendText, text)

    def on_user_left_room(self, message):
        """User left room"""
        if message.get('room_id') == self.current_room:
            text = f"*** {message['username']} {_('left the room')}\n"
            wx.CallAfter(self.room_messages.AppendText, text)

    def on_account_created(self, username, titan_number):
        """New user registered - welcome message for other users"""
        # Only show for other users, not for the one who just created account
        welcome_message = _("Welcome user {username}, Titan ID: {titan_number}").format(
            username=username,
            titan_number=titan_number
        )
        wx.CallAfter(stereo_speech.speak, welcome_message, 0.5)
        wx.CallAfter(play_sound, 'titannet/account_created.ogg')
        wx.CallAfter(self.refresh_users)


def show_login_dialog(parent, titan_client: TitanNetClient):
    """
    Show login dialog

    Args:
        parent: Parent window
        titan_client: Titan-Net client instance

    Returns:
        Tuple of (success: bool, offline_mode: bool)
    """
    stereo_speech.speak(_("Checking Titan-Net connection..."), position=0.5)

    server_available = titan_client.check_server()

    if not server_available:
        stereo_speech.speak(_("Titan-Net server is not available. Would you like to continue in offline mode?"), position=0.5)
        play_sound('core/error.ogg')

        dlg = wx.MessageDialog(
            parent,
            _("Titan-Net server is not available.\nYou can continue in offline mode without messaging features."),
            _("Server Not Available"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING
        )

        result = dlg.ShowModal()
        dlg.Destroy()

        if result == wx.ID_YES:
            return (False, True)
        else:
            return (False, False)

    stereo_speech.speak(_("Server connected"), position=0.5)
    play_sound('system/user_online.ogg')

    dialog = LoginDialog(parent, titan_client)
    result = dialog.ShowModal()

    logged_in = dialog.logged_in
    offline_mode = dialog.offline_mode

    dialog.Destroy()

    if logged_in:
        return (True, False)
    elif offline_mode:
        return (False, True)
    else:
        return (False, False)


def show_titan_net_window(parent, titan_client: TitanNetClient):
    """
    Show main Titan-Net window

    Args:
        parent: Parent window
        titan_client: Titan-Net client instance (must be logged in)
    """
    if not titan_client.is_connected:
        wx.MessageBox(_("Not connected to Titan-Net"), _("Error"), wx.OK | wx.ICON_ERROR)
        return

    window = TitanNetMainWindow(parent, titan_client)
    window.Show()


if __name__ == "__main__":
    app = wx.App()

    client = TitanNetClient("localhost", 8001)

    success, offline = show_login_dialog(None, client)

    if success:
        show_titan_net_window(None, client)
        app.MainLoop()
    else:
        print("Login cancelled or offline mode selected")
