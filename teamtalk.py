# -*- coding: utf-8 -*-
import wx
import os
import json
import threading
import time
import traceback
from typing import Dict, List, Optional, Callable, Any
from translation import get_translation_function
from titan_im_config import load_titan_im_config, save_titan_im_config
from sound import play_sound, play_select_sound, play_focus_sound
import accessible_output3.outputs.auto

try:
    import sys
    import os
    
    # Add TeamTalk5 DLL directory to PATH for Windows
    if sys.platform == "win32":
        # Try multiple possible DLL locations for different deployment scenarios
        possible_dll_paths = [
            os.path.join(os.path.dirname(__file__), 'data', 'bin'),  # Development/directory deployment
            os.path.join(os.path.dirname(sys.executable), 'data', 'bin'),  # Compiled exe directory deployment
            os.path.join(os.getcwd(), 'data', 'bin'),  # Current working directory
            os.path.dirname(__file__),  # Same directory as script
            os.path.dirname(sys.executable)  # Same directory as executable
        ]
        
        dll_found = False
        for dll_path in possible_dll_paths:
            if os.path.exists(dll_path) and os.path.exists(os.path.join(dll_path, 'TeamTalk5.dll')):
                if (sys.version_info.major == 3 and sys.version_info.minor >= 8):
                    os.add_dll_directory(dll_path)
                else:
                    os.environ['PATH'] = dll_path + os.pathsep + os.environ.get('PATH', '')
                dll_found = True
                break
        
        if not dll_found:
            print("Warning: TeamTalk5.dll not found in any expected location")
    
    # Add tt5py directory to Python path - try multiple locations
    possible_tt5py_paths = [
        os.path.join(os.path.dirname(__file__), 'tt5py'),  # Development/directory deployment
        os.path.join(os.path.dirname(sys.executable), 'tt5py'),  # Compiled exe directory deployment
        os.path.join(os.getcwd(), 'tt5py'),  # Current working directory
    ]
    
    tt5py_found = False
    for teamtalk_path in possible_tt5py_paths:
        if os.path.exists(teamtalk_path) and os.path.exists(os.path.join(teamtalk_path, 'TeamTalk5.py')):
            if teamtalk_path not in sys.path:
                sys.path.insert(0, teamtalk_path)
            tt5py_found = True
            break
    
    if not tt5py_found:
        print("Warning: tt5py directory not found in any expected location")
    
    from TeamTalk5 import *
    from TeamTalk5 import TeamTalk, SoundSystem, TextMsgType, ttstr, TTMessage, ClientEvent
    TT5_AVAILABLE = True
except ImportError as e:
    TT5_AVAILABLE = False
    print(f"Warning: TeamTalk5 SDK not available: {e}. TeamTalk functionality disabled.")
except OSError as e:
    TT5_AVAILABLE = False
    print(f"Warning: TeamTalk5 DLL not found: {e}. TeamTalk functionality disabled.")

_ = get_translation_function()
speaker = accessible_output3.outputs.auto.Auto()

class TeamTalkClient:
    def __init__(self):
        self.tt = None
        self.connected = False
        self.logged_in = False
        self.current_channel = None
        self.users = {}
        self.channels = {}
        self.voice_transmission = False
        self.push_to_talk_active = False
        self.audio_devices_initialized = False
        self.callbacks = {
            'message': [],
            'user_status': [],
            'channel_status': [],
            'connection': [],
            'voice_status': []
        }
        
        # Configuration
        self.config = self.load_config()
        
    def load_config(self) -> Dict[str, Any]:
        """Load TeamTalk configuration from Titan IM config"""
        config = load_titan_im_config()
        return config.get('teamtalk', {
            'server': {
                'host': 'localhost',
                'tcpport': 10333,
                'udpport': 10333,
                'encrypted': False
            },
            'user': {
                'nickname': 'TitanUser',
                'password': '',
                'remember_login': True
            },
            'audio': {
                'input_device': -1,
                'output_device': -1,
                'input_volume': 100,
                'output_volume': 100,
                'voice_activation': True,
                'voice_activation_level': 2000
            },
            'ui': {
                'auto_join_channel': True,
                'default_channel': '',
                'show_user_messages': True,
                'show_channel_messages': True
            }
        })
    
    def save_config(self):
        """Save TeamTalk configuration to Titan IM config"""
        full_config = load_titan_im_config()
        full_config['teamtalk'] = self.config
        save_titan_im_config(full_config)
    
    def add_callback(self, event_type: str, callback: Callable):
        """Add event callback"""
        if event_type in self.callbacks:
            self.callbacks[event_type].append(callback)
    
    def trigger_callback(self, event_type: str, *args):
        """Trigger callbacks for event type"""
        for callback in self.callbacks.get(event_type, []):
            try:
                callback(*args)
            except Exception as e:
                print(f"Callback error for {event_type}: {e}")
    
    def connect(self, host: str = None, tcp_port: int = None, udp_port: int = None, encrypted: bool = None) -> bool:
        """Connect to TeamTalk server"""
        if not TT5_AVAILABLE:
            self.trigger_callback('connection', False, _("TeamTalk SDK not available"))
            return False
        
        try:
            # Use provided parameters or config defaults
            host = host or self.config['server']['host']
            tcp_port = tcp_port or self.config['server']['tcpport']
            udp_port = udp_port or self.config['server']['udpport']
            encrypted = encrypted if encrypted is not None else self.config['server']['encrypted']
            
            self.tt = TeamTalk()
            
            # Set up event handling
            self._setup_event_handlers()
            
            # Connect to server
            result = self.tt.connect(host, tcp_port, udp_port, encrypted)
            
            if result > 0:
                # Wait for connection
                start_time = time.time()
                while not self.connected and (time.time() - start_time) < 10:  # 10 second timeout
                    self.process_events()
                    time.sleep(0.1)
                
                if self.connected:
                    self.trigger_callback('connection', True, _("Connected to TeamTalk server"))
                    return True
                else:
                    self.trigger_callback('connection', False, _("Connection timeout"))
                    return False
            else:
                self.trigger_callback('connection', False, _("Failed to connect to server"))
                return False
                
        except Exception as e:
            error_msg = _("Connection error: {}").format(str(e))
            self.trigger_callback('connection', False, error_msg)
            return False
    
    def login(self, nickname: str = None, password: str = None) -> bool:
        """Login to TeamTalk server"""
        if not self.tt or not self.connected:
            return False
        
        try:
            nickname = nickname or self.config['user']['nickname']
            password = password or self.config['user']['password']
            
            result = self.tt.doLogin(nickname, password)
            
            if result > 0:
                # Wait for login
                start_time = time.time()
                while not self.logged_in and (time.time() - start_time) < 5:
                    self.process_events()
                    time.sleep(0.1)
                
                if self.logged_in:
                    self.trigger_callback('connection', True, _("Logged in as {}").format(nickname))
                    return True
                else:
                    self.trigger_callback('connection', False, _("Login timeout"))
                    return False
            else:
                self.trigger_callback('connection', False, _("Login failed"))
                return False
                
        except Exception as e:
            error_msg = _("Login error: {}").format(str(e))
            self.trigger_callback('connection', False, error_msg)
            return False
    
    def disconnect(self):
        """Disconnect from TeamTalk server"""
        if self.tt:
            try:
                self.tt.disconnect()
                self.connected = False
                self.logged_in = False
                self.current_channel = None
                self.users.clear()
                self.channels.clear()
                self.trigger_callback('connection', True, _("Disconnected from server"))
            except Exception as e:
                print(f"Disconnect error: {e}")
    
    def join_channel(self, channel_id: int, password: str = "") -> bool:
        """Join a channel"""
        if not self.tt or not self.logged_in:
            return False
        
        try:
            result = self.tt.doJoinChannel(channel_id, password)
            if result > 0:
                self.current_channel = channel_id
                return True
            return False
        except Exception as e:
            print(f"Join channel error: {e}")
            return False
    
    def leave_channel(self) -> bool:
        """Leave current channel"""
        if not self.tt or not self.current_channel:
            return False
        
        try:
            result = self.tt.doLeaveChannel()
            if result > 0:
                self.current_channel = None
                return True
            return False
        except Exception as e:
            print(f"Leave channel error: {e}")
            return False
    
    def send_message(self, message: str, user_id: int = None) -> bool:
        """Send text message"""
        if not self.tt or not self.logged_in:
            return False
        
        try:
            if user_id:
                # Private message
                msg_type = TextMsgType.MSGTYPE_USER
                result = self.tt.doTextMessage(msg_type, user_id, message)
            else:
                # Channel message
                msg_type = TextMsgType.MSGTYPE_CHANNEL
                result = self.tt.doTextMessage(msg_type, 0, message)
            
            return result > 0
        except Exception as e:
            print(f"Send message error: {e}")
            return False
    
    def initialize_audio_devices(self) -> bool:
        """Initialize audio input/output devices"""
        if not self.tt or self.audio_devices_initialized:
            return self.audio_devices_initialized
        
        try:
            # Get default audio devices
            input_device = self.config.get('audio', {}).get('input_device', -1)
            output_device = self.config.get('audio', {}).get('output_device', -1)
            
            # Initialize sound system (WASAPI for Windows is recommended)
            sound_system = SoundSystem.SOUNDSYSTEM_WASAPI if sys.platform == "win32" else SoundSystem.SOUNDSYSTEM_ALSA
            
            if input_device == -1:
                input_device = self.tt.getDefaultSoundDevice(sound_system, True)  # True for input
            if output_device == -1:
                output_device = self.tt.getDefaultSoundDevice(sound_system, False)  # False for output
            
            # Initialize input device
            if input_device >= 0:
                result = self.tt.initSoundInputDevice(input_device)
                if result:
                    print(f"Audio input device {input_device} initialized successfully")
                else:
                    print(f"Failed to initialize audio input device {input_device}")
                    return False
            
            # Initialize output device
            if output_device >= 0:
                result = self.tt.initSoundOutputDevice(output_device)
                if result:
                    print(f"Audio output device {output_device} initialized successfully")
                else:
                    print(f"Failed to initialize audio output device {output_device}")
                    return False
            
            # Configure audio settings
            input_volume = self.config.get('audio', {}).get('input_volume', 100)
            output_volume = self.config.get('audio', {}).get('output_volume', 100)
            
            self.tt.setSoundInputGainLevel(input_volume)
            self.tt.setSoundOutputVolume(output_volume)
            
            # Configure voice activation if enabled
            if self.config.get('audio', {}).get('voice_activation', True):
                voice_level = self.config.get('audio', {}).get('voice_activation_level', 2000)
                self.tt.setVoiceActivationLevel(voice_level)
                self.tt.enableVoiceActivation(True)
            
            self.audio_devices_initialized = True
            self.trigger_callback('voice_status', 'audio_initialized', True)
            return True
            
        except Exception as e:
            print(f"Audio device initialization error: {e}")
            return False
    
    def start_voice_transmission(self) -> bool:
        """Start transmitting voice in current channel"""
        if not self.tt or not self.logged_in or not self.current_channel:
            return False
        
        if not self.audio_devices_initialized:
            if not self.initialize_audio_devices():
                return False
        
        try:
            # Enable voice transmission
            if self.config.get('audio', {}).get('voice_activation', True):
                # Voice activation mode
                result = self.tt.enableVoiceTransmission(True)
            else:
                # Push-to-talk mode
                result = self.tt.enableVoiceTransmission(True)
            
            if result:
                self.voice_transmission = True
                self.trigger_callback('voice_status', 'transmission_started', self.current_channel)
                play_sound("titannet/ring_out.ogg")  # Indicate voice transmission started
                return True
            return False
            
        except Exception as e:
            print(f"Voice transmission start error: {e}")
            return False
    
    def stop_voice_transmission(self) -> bool:
        """Stop transmitting voice"""
        if not self.tt or not self.voice_transmission:
            return False
        
        try:
            result = self.tt.enableVoiceTransmission(False)
            if result:
                self.voice_transmission = False
                self.trigger_callback('voice_status', 'transmission_stopped', self.current_channel)
                return True
            return False
            
        except Exception as e:
            print(f"Voice transmission stop error: {e}")
            return False
    
    def toggle_voice_transmission(self) -> bool:
        """Toggle voice transmission on/off"""
        if self.voice_transmission:
            return self.stop_voice_transmission()
        else:
            return self.start_voice_transmission()
    
    def set_push_to_talk(self, active: bool) -> bool:
        """Set push-to-talk state"""
        if not self.tt or not self.logged_in:
            return False
        
        if not self.audio_devices_initialized:
            if not self.initialize_audio_devices():
                return False
        
        try:
            if active and not self.push_to_talk_active:
                # Start push-to-talk
                result = self.tt.enableVoiceTransmission(True)
                if result:
                    self.push_to_talk_active = True
                    self.voice_transmission = True
                    play_sound("titannet/ring_out.ogg")
                    self.trigger_callback('voice_status', 'push_to_talk_start', self.current_channel)
                    return True
            elif not active and self.push_to_talk_active:
                # Stop push-to-talk
                result = self.tt.enableVoiceTransmission(False)
                if result:
                    self.push_to_talk_active = False
                    self.voice_transmission = False
                    self.trigger_callback('voice_status', 'push_to_talk_stop', self.current_channel)
                    return True
            return True
            
        except Exception as e:
            print(f"Push-to-talk error: {e}")
            return False
    
    def get_audio_devices(self) -> dict:
        """Get available audio input and output devices"""
        devices = {'input': [], 'output': []}
        
        if not TT5_AVAILABLE:
            return devices
        
        try:
            # Create temporary TT instance to query devices
            temp_tt = TeamTalk()
            
            # Get sound systems
            sound_system = SoundSystem.SOUNDSYSTEM_WASAPI if sys.platform == "win32" else SoundSystem.SOUNDSYSTEM_ALSA
            
            # Get input devices
            input_devices = temp_tt.getSoundDevices(sound_system, True)  # True for input
            for device in input_devices:
                devices['input'].append({
                    'id': device.nDeviceID,
                    'name': ttstr(device.szDeviceName),
                    'driver': ttstr(device.szDeviceID)
                })
            
            # Get output devices
            output_devices = temp_tt.getSoundDevices(sound_system, False)  # False for output
            for device in output_devices:
                devices['output'].append({
                    'id': device.nDeviceID,
                    'name': ttstr(device.szDeviceName),
                    'driver': ttstr(device.szDeviceID)
                })
            
            temp_tt.closeSoundDevice()
            del temp_tt
            
        except Exception as e:
            print(f"Get audio devices error: {e}")
        
        return devices
    
    def get_channels(self) -> Dict[int, Dict[str, Any]]:
        """Get available channels"""
        return self.channels.copy()
    
    def get_users(self) -> Dict[int, Dict[str, Any]]:
        """Get current users"""
        return self.users.copy()
    
    def get_channel_users(self, channel_id: int) -> List[Dict[str, Any]]:
        """Get users in specific channel"""
        return [user for user in self.users.values() if user.get('channel_id') == channel_id]
    
    def _setup_event_handlers(self):
        """Set up TeamTalk event handlers"""
        if not self.tt:
            return
        
        # Enable events we want to handle
        events = [
            ClientEvent.CLIENTEVENT_CON_SUCCESS,
            ClientEvent.CLIENTEVENT_CON_FAILED,
            ClientEvent.CLIENTEVENT_CON_LOST,
            ClientEvent.CLIENTEVENT_CMD_MYSELF_LOGGEDIN,
            ClientEvent.CLIENTEVENT_CMD_MYSELF_LOGGEDOUT,
            ClientEvent.CLIENTEVENT_CMD_USER_LOGGEDIN,
            ClientEvent.CLIENTEVENT_CMD_USER_LOGGEDOUT,
            ClientEvent.CLIENTEVENT_CMD_USER_UPDATE,
            ClientEvent.CLIENTEVENT_CMD_USER_JOINED,
            ClientEvent.CLIENTEVENT_CMD_USER_LEFT,
            ClientEvent.CLIENTEVENT_CMD_CHANNEL_NEW,
            ClientEvent.CLIENTEVENT_CMD_CHANNEL_UPDATE,
            ClientEvent.CLIENTEVENT_CMD_CHANNEL_REMOVE,
            ClientEvent.CLIENTEVENT_CMD_USER_TEXTMSG
        ]
        
        for event in events:
            self.tt.setClientEvent(event, True)
    
    def process_events(self):
        """Process TeamTalk events (should be called regularly)"""
        if not self.tt:
            return
        
        try:
            msg = self.tt.getMessage(0)
            if msg:
                self._handle_event(msg)
        except Exception as e:
            print(f"Event processing error: {e}")
    
    def _handle_event(self, msg):
        """Handle TeamTalk event"""
        try:
            if msg.nClientEvent == ClientEvent.CLIENTEVENT_CON_SUCCESS:
                self.connected = True
                
            elif msg.nClientEvent == ClientEvent.CLIENTEVENT_CON_FAILED:
                self.connected = False
                
            elif msg.nClientEvent == ClientEvent.CLIENTEVENT_CON_LOST:
                self.connected = False
                self.logged_in = False
                
            elif msg.nClientEvent == ClientEvent.CLIENTEVENT_CMD_MYSELF_LOGGEDIN:
                self.logged_in = True
                
            elif msg.nClientEvent == ClientEvent.CLIENTEVENT_CMD_MYSELF_LOGGEDOUT:
                self.logged_in = False
                
            elif msg.nClientEvent == ClientEvent.CLIENTEVENT_CMD_USER_LOGGEDIN:
                user = msg.user
                self.users[user.nUserID] = {
                    'id': user.nUserID,
                    'nickname': ttstr(user.szNickname),
                    'username': ttstr(user.szUsername),
                    'channel_id': user.nChannelID,
                    'status': user.nStatusMode
                }
                self.trigger_callback('user_status', user.nUserID, 'login')
                
            elif msg.nClientEvent == ClientEvent.CLIENTEVENT_CMD_USER_LOGGEDOUT:
                user_id = msg.user.nUserID
                if user_id in self.users:
                    del self.users[user_id]
                self.trigger_callback('user_status', user_id, 'logout')
                
            elif msg.nClientEvent == ClientEvent.CLIENTEVENT_CMD_USER_JOINED:
                user = msg.user
                if user.nUserID in self.users:
                    self.users[user.nUserID]['channel_id'] = user.nChannelID
                self.trigger_callback('user_status', user.nUserID, 'joined_channel')
                
            elif msg.nClientEvent == ClientEvent.CLIENTEVENT_CMD_USER_LEFT:
                user = msg.user
                if user.nUserID in self.users:
                    self.users[user.nUserID]['channel_id'] = 0
                self.trigger_callback('user_status', user.nUserID, 'left_channel')
                
            elif msg.nClientEvent == ClientEvent.CLIENTEVENT_CMD_CHANNEL_NEW:
                channel = msg.channel
                self.channels[channel.nChannelID] = {
                    'id': channel.nChannelID,
                    'parent_id': channel.nParentID,
                    'name': channel.szName,
                    'topic': channel.szTopic,
                    'password': channel.bPassword,
                    'max_users': channel.nMaxUsers
                }
                self.trigger_callback('channel_status', channel.nChannelID, 'new')
                
            elif msg.nClientEvent == ClientEvent.CLIENTEVENT_CMD_CHANNEL_REMOVE:
                channel_id = msg.channel.nChannelID
                if channel_id in self.channels:
                    del self.channels[channel_id]
                self.trigger_callback('channel_status', channel_id, 'removed')
                
            elif msg.nClientEvent == ClientEvent.CLIENTEVENT_CMD_USER_TEXTMSG:
                text_msg = msg.textmessage
                message_data = {
                    'type': text_msg.nMsgType,
                    'from_user_id': text_msg.nFromUserID,
                    'to_user_id': text_msg.nToUserID,
                    'channel_id': text_msg.nChannelID,
                    'content': text_msg.szMessage,
                    'timestamp': time.time()
                }
                
                # Add sender nickname if available
                if text_msg.nFromUserID in self.users:
                    message_data['from_nickname'] = self.users[text_msg.nFromUserID]['nickname']
                
                self.trigger_callback('message', message_data)
                
        except Exception as e:
            print(f"Event handling error: {e}")


class TeamTalkWindow(wx.Frame):
    def __init__(self, parent, component_manager=None):
        super().__init__(parent, title=_("TeamTalk"), size=(800, 600))
        self.parent = parent
        self.component_manager = component_manager
        self.client = TeamTalkClient()
        
        # Set up UI
        self.setup_ui()
        self.setup_events()
        self.setup_callbacks()
        
        # Start event processing timer
        self.event_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_timer)
        self.event_timer.Start(100)  # Process events every 100ms
        
        self.Centre()
        
    def setup_ui(self):
        """Set up user interface"""
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Connection panel
        connection_box = wx.StaticBox(panel, label=_("Connection"))
        connection_sizer = wx.StaticBoxSizer(connection_box, wx.HORIZONTAL)
        
        self.connect_btn = wx.Button(panel, label=_("Connect"))
        self.disconnect_btn = wx.Button(panel, label=_("Disconnect"))
        self.disconnect_btn.Enable(False)
        
        # Voice control buttons
        self.ptt_btn = wx.Button(panel, label=_("Push to Talk (Hold Space)"))
        self.ptt_btn.Enable(False)
        self.voice_toggle_btn = wx.Button(panel, label=_("Voice Transmission"))
        self.voice_toggle_btn.Enable(False)
        
        connection_sizer.Add(self.connect_btn, 0, wx.ALL, 5)
        connection_sizer.Add(self.disconnect_btn, 0, wx.ALL, 5)
        connection_sizer.Add(self.ptt_btn, 0, wx.ALL, 5)
        connection_sizer.Add(self.voice_toggle_btn, 0, wx.ALL, 5)
        
        # Channel panel
        channel_box = wx.StaticBox(panel, label=_("Channels"))
        channel_sizer = wx.StaticBoxSizer(channel_box, wx.VERTICAL)
        
        self.channel_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.channel_list.AppendColumn(_("Channel"), width=200)
        self.channel_list.AppendColumn(_("Users"), width=80)
        self.channel_list.AppendColumn(_("Topic"), width=300)
        
        channel_sizer.Add(self.channel_list, 1, wx.EXPAND | wx.ALL, 5)
        
        # Users panel
        users_box = wx.StaticBox(panel, label=_("Users"))
        users_sizer = wx.StaticBoxSizer(users_box, wx.VERTICAL)
        
        self.users_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.users_list.AppendColumn(_("Nickname"), width=150)
        self.users_list.AppendColumn(_("Status"), width=100)
        
        users_sizer.Add(self.users_list, 1, wx.EXPAND | wx.ALL, 5)
        
        # Message panel
        message_box = wx.StaticBox(panel, label=_("Messages"))
        message_sizer = wx.StaticBoxSizer(message_box, wx.VERTICAL)
        
        self.message_log = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.message_input = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        
        message_sizer.Add(self.message_log, 1, wx.EXPAND | wx.ALL, 5)
        message_sizer.Add(self.message_input, 0, wx.EXPAND | wx.ALL, 5)
        
        # Layout
        top_sizer = wx.BoxSizer(wx.HORIZONTAL)
        top_sizer.Add(channel_sizer, 1, wx.EXPAND | wx.ALL, 5)
        top_sizer.Add(users_sizer, 1, wx.EXPAND | wx.ALL, 5)
        
        main_sizer.Add(connection_sizer, 0, wx.EXPAND | wx.ALL, 5)
        main_sizer.Add(top_sizer, 1, wx.EXPAND)
        main_sizer.Add(message_sizer, 1, wx.EXPAND | wx.ALL, 5)
        
        panel.SetSizer(main_sizer)
    
    def setup_events(self):
        """Set up event handlers"""
        self.Bind(wx.EVT_BUTTON, self.on_connect, self.connect_btn)
        self.Bind(wx.EVT_BUTTON, self.on_disconnect, self.disconnect_btn)
        self.Bind(wx.EVT_BUTTON, self.on_voice_toggle, self.voice_toggle_btn)
        self.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_channel_activate, self.channel_list)
        self.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_user_activate, self.users_list)
        self.Bind(wx.EVT_TEXT_ENTER, self.on_message_send, self.message_input)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        
        # Push-to-talk button events
        self.ptt_btn.Bind(wx.EVT_LEFT_DOWN, self.on_ptt_down)
        self.ptt_btn.Bind(wx.EVT_LEFT_UP, self.on_ptt_up)
        
        # Global key events for push-to-talk (Space key)
        self.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
        self.Bind(wx.EVT_KEY_UP, self.on_key_up)
        
        # Keyboard shortcuts
        self.channel_list.Bind(wx.EVT_KEY_DOWN, self.on_channel_key)
        self.users_list.Bind(wx.EVT_KEY_DOWN, self.on_user_key)
        
        # Focus sounds for navigation
        self.channel_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_channel_focus)
        self.users_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_user_focus)
    
    def setup_callbacks(self):
        """Set up TeamTalk client callbacks"""
        self.client.add_callback('connection', self.on_connection_event)
        self.client.add_callback('message', self.on_message_event)
        self.client.add_callback('user_status', self.on_user_status_event)
        self.client.add_callback('channel_status', self.on_channel_status_event)
        self.client.add_callback('voice_status', self.on_voice_status_event)
    
    def on_timer(self, event):
        """Timer event for processing TeamTalk events"""
        self.client.process_events()
    
    def on_connect(self, event):
        """Connect to TeamTalk server"""
        # TODO: Show connection dialog for server settings
        success = self.client.connect()
        if success:
            success = self.client.login()
            if success:
                self.connect_btn.Enable(False)
                self.disconnect_btn.Enable(True)
                self.ptt_btn.Enable(True)
                self.voice_toggle_btn.Enable(True)
                self.update_channels()
                # Initialize audio devices after connection
                self.client.initialize_audio_devices()
                play_sound("titannet/titannet_success.ogg")
                speaker.output(_("Connected to TeamTalk server"))
    
    def on_disconnect(self, event):
        """Disconnect from TeamTalk server"""
        self.client.disconnect()
        self.connect_btn.Enable(True)
        self.disconnect_btn.Enable(False)
        self.ptt_btn.Enable(False)
        self.voice_toggle_btn.Enable(False)
        self.clear_lists()
        play_sound("titannet/bye.ogg")
        speaker.output(_("Disconnected from TeamTalk server"))
    
    def on_channel_activate(self, event):
        """Join selected channel"""
        selected = self.channel_list.GetFirstSelected()
        if selected != -1:
            channel_id = self.channel_list.GetItemData(selected)
            self.join_channel(channel_id)
    
    def on_channel_key(self, event):
        """Handle channel list keyboard events"""
        key_code = event.GetKeyCode()
        
        if key_code == wx.WXK_RETURN:
            # Enter - join channel
            selected = self.channel_list.GetFirstSelected()
            if selected != -1:
                channel_id = self.channel_list.GetItemData(selected)
                self.join_channel(channel_id)
        elif key_code == wx.WXK_BACK:
            # Backspace - leave current channel
            if self.client.current_channel:
                self.leave_channel()
        else:
            event.Skip()
    
    def on_user_activate(self, event):
        """Send private message to selected user"""
        selected = self.users_list.GetFirstSelected()
        if selected != -1:
            user_id = self.users_list.GetItemData(selected)
            self.start_private_message(user_id)
    
    def on_user_key(self, event):
        """Handle users list keyboard events"""
        key_code = event.GetKeyCode()
        
        if key_code == wx.WXK_RETURN:
            # Enter - send private message
            selected = self.users_list.GetFirstSelected()
            if selected != -1:
                user_id = self.users_list.GetItemData(selected)
                self.start_private_message(user_id)
        else:
            event.Skip()
    
    def on_channel_focus(self, event):
        """Handle channel list focus/selection"""
        play_focus_sound()
        event.Skip()
    
    def on_user_focus(self, event):
        """Handle user list focus/selection"""
        play_focus_sound()
        event.Skip()
    
    def on_message_send(self, event):
        """Send message"""
        message = self.message_input.GetValue().strip()
        if message:
            success = self.client.send_message(message)
            if success:
                play_sound("titannet/message_send.ogg")
                self.message_input.SetValue("")
                # Add to message log
                nickname = self.client.config.get('user', {}).get('nickname', 'Me')
                self.add_message_to_log(f"{nickname}: {message}")
    
    def on_connection_event(self, success, message):
        """Handle connection events"""
        wx.CallAfter(self.add_message_to_log, f"[{_('System')}] {message}")
        
        # Play appropriate sound for success/failure
        if not success and ("error" in message.lower() or "failed" in message.lower() or "timeout" in message.lower()):
            play_sound("titannet/file_error.ogg")
        
        if success and self.client.logged_in:
            wx.CallAfter(self.update_channels)
            wx.CallAfter(self.update_users)
    
    def on_message_event(self, message_data):
        """Handle incoming messages"""
        def update_ui():
            msg_type = message_data['type']
            content = message_data['content']
            from_nickname = message_data.get('from_nickname', f"User {message_data['from_user_id']}")
            
            if msg_type == TextMsgType.MSGTYPE_CHANNEL:
                # Channel message
                self.add_message_to_log(f"[{_('Channel')}] {from_nickname}: {content}")
                play_sound("titannet/new_message.ogg")  # Use titannet sound theme
                if self.client.config.get('ui', {}).get('show_channel_messages', True):
                    speaker.output(f"{from_nickname}: {content}")
            elif msg_type == TextMsgType.MSGTYPE_USER:
                # Private message
                self.add_message_to_log(f"[{_('Private')}] {from_nickname}: {content}")
                play_sound("titannet/chat_message.ogg")  # Use titannet sound theme
                if self.client.config.get('ui', {}).get('show_user_messages', True):
                    speaker.output(f"{_('Private message from')} {from_nickname}: {content}")
        
        wx.CallAfter(update_ui)
    
    def on_user_status_event(self, user_id, status):
        """Handle user status changes"""
        wx.CallAfter(self.update_users)
        
        if user_id in self.client.users:
            user = self.client.users[user_id]
            nickname = user['nickname']
            
            if status == 'login':
                play_sound("titannet/new_status.ogg")
                wx.CallAfter(self.add_message_to_log, f"[{_('System')}] {nickname} {_('joined the server')}")
            elif status == 'logout':
                play_sound("titannet/bye.ogg")
                wx.CallAfter(self.add_message_to_log, f"[{_('System')}] {nickname} {_('left the server')}")
            elif status == 'joined_channel':
                play_sound("titannet/new_chat.ogg")
                wx.CallAfter(self.add_message_to_log, f"[{_('System')}] {nickname} {_('joined the channel')}")
            elif status == 'left_channel':
                play_sound("titannet/bye.ogg")
                wx.CallAfter(self.add_message_to_log, f"[{_('System')}] {nickname} {_('left the channel')}")
    
    def on_channel_status_event(self, channel_id, status):
        """Handle channel status changes"""
        wx.CallAfter(self.update_channels)
    
    def join_channel(self, channel_id):
        """Join a channel"""
        success = self.client.join_channel(channel_id)
        if success:
            channel_name = self.client.channels.get(channel_id, {}).get('name', str(channel_id))
            self.add_message_to_log(f"[{_('System')}] {_('Joined channel')}: {channel_name}")
            play_sound("titannet/callsuccess.ogg")
            speaker.output(f"{_('Joined channel')} {channel_name}")
            self.update_users()
    
    def leave_channel(self):
        """Leave current channel"""
        if self.client.current_channel:
            channel_name = self.client.channels.get(self.client.current_channel, {}).get('name', str(self.client.current_channel))
            success = self.client.leave_channel()
            if success:
                self.add_message_to_log(f"[{_('System')}] {_('Left channel')}: {channel_name}")
                play_sound("titannet/bye.ogg")
                speaker.output(f"{_('Left channel')} {channel_name}")
                self.update_users()
    
    def start_private_message(self, user_id):
        """Start private message dialog"""
        user = self.client.users.get(user_id)
        if not user:
            return
        
        nickname = user['nickname']
        
        # Simple message input dialog
        dlg = wx.TextEntryDialog(self, 
                                f"{_('Send private message to')} {nickname}:",
                                _("Private Message"))
        
        if dlg.ShowModal() == wx.ID_OK:
            message = dlg.GetValue().strip()
            if message:
                success = self.client.send_message(message, user_id)
                if success:
                    self.add_message_to_log(f"[{_('Private')} -> {nickname}] {message}")
        
        dlg.Destroy()
    
    def update_channels(self):
        """Update channels list"""
        self.channel_list.DeleteAllItems()
        
        channels = self.client.get_channels()
        for channel_id, channel in channels.items():
            # Count users in channel
            user_count = len(self.client.get_channel_users(channel_id))
            
            index = self.channel_list.InsertItem(0, channel['name'])
            self.channel_list.SetItem(index, 1, str(user_count))
            self.channel_list.SetItem(index, 2, channel.get('topic', ''))
            self.channel_list.SetItemData(index, channel_id)
            
            # Highlight current channel
            if channel_id == self.client.current_channel:
                self.channel_list.SetItemBackgroundColour(index, wx.Colour(200, 255, 200))
    
    def update_users(self):
        """Update users list"""
        self.users_list.DeleteAllItems()
        
        if self.client.current_channel:
            # Show users in current channel
            users = self.client.get_channel_users(self.client.current_channel)
        else:
            # Show all users
            users = list(self.client.get_users().values())
        
        for user in users:
            index = self.users_list.InsertItem(0, user['nickname'])
            self.users_list.SetItem(index, 1, _("Online"))  # TODO: Real status
            self.users_list.SetItemData(index, user['id'])
    
    def clear_lists(self):
        """Clear all lists"""
        self.channel_list.DeleteAllItems()
        self.users_list.DeleteAllItems()
        self.message_log.SetValue("")
    
    def add_message_to_log(self, message):
        """Add message to message log"""
        timestamp = time.strftime("%H:%M:%S")
        self.message_log.AppendText(f"[{timestamp}] {message}\n")
    
    def on_voice_toggle(self, event):
        """Toggle voice transmission"""
        if self.client.current_channel:
            success = self.client.toggle_voice_transmission()
            if success:
                if self.client.voice_transmission:
                    self.voice_toggle_btn.SetLabel(_("Stop Voice"))
                    speaker.output(_("Voice transmission started"))
                else:
                    self.voice_toggle_btn.SetLabel(_("Voice Transmission"))
                    speaker.output(_("Voice transmission stopped"))
        else:
            wx.MessageBox(_("Please join a channel first"), _("Information"), wx.OK | wx.ICON_INFORMATION)
    
    def on_ptt_down(self, event):
        """Push-to-talk button pressed"""
        if self.client.current_channel:
            self.client.set_push_to_talk(True)
    
    def on_ptt_up(self, event):
        """Push-to-talk button released"""
        self.client.set_push_to_talk(False)
    
    def on_key_down(self, event):
        """Handle key press events for push-to-talk"""
        key_code = event.GetKeyCode()
        
        if key_code == wx.WXK_SPACE and self.client.current_channel:
            # Space key for push-to-talk
            if not self.client.push_to_talk_active:
                self.client.set_push_to_talk(True)
                self.ptt_btn.SetLabel(_("Talking... (Release Space)"))
        
        event.Skip()
    
    def on_key_up(self, event):
        """Handle key release events for push-to-talk"""
        key_code = event.GetKeyCode()
        
        if key_code == wx.WXK_SPACE:
            # Release space key
            if self.client.push_to_talk_active:
                self.client.set_push_to_talk(False)
                self.ptt_btn.SetLabel(_("Push to Talk (Hold Space)"))
        
        event.Skip()
    
    def on_voice_status_event(self, status_type, data):
        """Handle voice status events"""
        def update_ui():
            if status_type == 'audio_initialized':
                self.add_message_to_log(f"[{_('System')}] Audio devices initialized")
            elif status_type == 'transmission_started':
                self.add_message_to_log(f"[{_('System')}] Voice transmission started in channel")
                play_sound("titannet/ring_out.ogg")  # Sound from titannet directory
            elif status_type == 'transmission_stopped':
                self.add_message_to_log(f"[{_('System')}] Voice transmission stopped")
            elif status_type == 'push_to_talk_start':
                self.add_message_to_log(f"[{_('System')}] Push-to-talk activated")
                play_sound("titannet/ring_out.ogg")  # Sound from titannet directory
            elif status_type == 'push_to_talk_stop':
                self.add_message_to_log(f"[{_('System')}] Push-to-talk deactivated")
        
        wx.CallAfter(update_ui)
    
    def on_close(self, event):
        """Handle window close"""
        if self.client.connected:
            self.client.disconnect()
        
        if hasattr(self, 'event_timer'):
            self.event_timer.Stop()
        
        self.Destroy()


def show_teamtalk_window(parent=None, component_manager=None):
    """Show TeamTalk window"""
    if not TT5_AVAILABLE:
        wx.MessageBox(
            _("TeamTalk5 SDK is not installed. Please install TeamTalk5 SDK to use this feature."),
            _("TeamTalk Unavailable"),
            wx.OK | wx.ICON_WARNING
        )
        return None
    
    window = TeamTalkWindow(parent, component_manager)
    window.Show()
    return window


# Configuration functions for Titan IM integration
def get_teamtalk_config() -> dict:
    """Get TeamTalk-specific configuration"""
    config = load_titan_im_config()
    return config.get('teamtalk', {})

def save_teamtalk_config(teamtalk_config: dict):
    """Save TeamTalk-specific configuration"""
    config = load_titan_im_config()
    config['teamtalk'] = teamtalk_config
    save_titan_im_config(config)

def set_teamtalk_server(host: str, tcp_port: int = 10333, udp_port: int = 10333, encrypted: bool = False):
    """Save TeamTalk server settings"""
    teamtalk_config = get_teamtalk_config()
    if 'server' not in teamtalk_config:
        teamtalk_config['server'] = {}
    
    teamtalk_config['server'].update({
        'host': host,
        'tcpport': tcp_port,
        'udpport': udp_port,
        'encrypted': encrypted
    })
    save_teamtalk_config(teamtalk_config)

def set_teamtalk_user(nickname: str, password: str = "", remember_login: bool = True):
    """Save TeamTalk user settings"""
    teamtalk_config = get_teamtalk_config()
    if 'user' not in teamtalk_config:
        teamtalk_config['user'] = {}
    
    teamtalk_config['user'].update({
        'nickname': nickname,
        'password': password,
        'remember_login': remember_login
    })
    save_teamtalk_config(teamtalk_config)

def get_teamtalk_credentials() -> tuple:
    """Get saved TeamTalk credentials"""
    teamtalk_config = get_teamtalk_config()
    server_config = teamtalk_config.get('server', {})
    user_config = teamtalk_config.get('user', {})
    
    return (
        server_config.get('host', 'localhost'),
        server_config.get('tcpport', 10333),
        server_config.get('udpport', 10333),
        server_config.get('encrypted', False),
        user_config.get('nickname', 'TitanUser'),
        user_config.get('password', '')
    )

def clear_teamtalk_config():
    """Clear TeamTalk configuration"""
    config = load_titan_im_config()
    if 'teamtalk' in config:
        del config['teamtalk']
    save_titan_im_config(config)