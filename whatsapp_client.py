# -*- coding: utf-8 -*-
"""
WhatsApp Web Client for Titan IM
Integrates with TCE Launcher's multi-service messaging system
Provides Telegram-like interface for WhatsApp Web
"""
import asyncio
import json
import os
import pickle
import threading
import time
import wx
import requests
import websockets
from datetime import datetime
from sound import play_sound
from translation import set_language
from settings import get_setting
from titan_im_config import (
    initialize_config, load_titan_im_config, save_titan_im_config
)
import whatsapp_webview

# Initialize translation
_ = set_language(get_setting('language', 'pl'))

# Initialize configuration
initialize_config()

class WhatsAppClient:
    def __init__(self):
        self.is_connected = False
        self.message_callbacks = []
        self.status_callbacks = []
        self.typing_callbacks = []
        self.user_data = None
        self.conversations = {}
        self.current_conversation = None
        self.monitoring_thread = None
        self.websocket = None
        self.websocket_thread = None
        self.server_url = "ws://localhost:8001"
        self.http_url = "http://localhost:8000"
        
    def add_message_callback(self, callback):
        """Add callback for new messages"""
        self.message_callbacks.append(callback)
    
    def add_status_callback(self, callback):
        """Add callback for user status changes"""
        self.status_callbacks.append(callback)
    
    def add_typing_callback(self, callback):
        """Add callback for typing indicators"""
        self.typing_callbacks.append(callback)
    
    def open_whatsapp_web(self):
        """Open WhatsApp Web in WebView (integrated with Titan IM)"""
        try:
            # Use the existing WebView integration
            whatsapp_window = whatsapp_webview.show_whatsapp_webview(None)
            if whatsapp_window:
                return True
            else:
                # Fallback to browser
                import webbrowser
                webbrowser.open('https://web.whatsapp.com')
                return True
        except Exception as e:
            print(f"Błąd podczas otwierania WhatsApp Web: {e}")
            return False
    
    def start_connection(self, username="TitanUser", password=None):
        """Start connection to Titan IM server"""
        try:
            # First try to connect via HTTP to check if server is running
            response = requests.get(f"{self.http_url}/health", timeout=5)
            if response.status_code != 200:
                # Server not available, fall back to web mode
                return self._fallback_to_web_mode()
            
            # Connect via WebSocket
            self.username = username
            self.user_data = {'username': username, 'platform': 'Titan IM'}
            
            # Start WebSocket connection in background
            self.websocket_thread = threading.Thread(target=self._start_websocket, daemon=True)
            self.websocket_thread.start()
            
            # Give WebSocket time to connect
            time.sleep(1)
            
            if self.is_connected:
                wx.CallAfter(self._notify_titan_connection)
                return True
            else:
                # WebSocket failed, fall back to web mode
                return self._fallback_to_web_mode()
                
        except Exception as e:
            print(f"Failed to connect to Titan IM server: {e}")
            # Fall back to web mode
            return self._fallback_to_web_mode()
    
    def _fallback_to_web_mode(self):
        """Fall back to web browser mode"""
        try:
            success = self.open_whatsapp_web()
            if success:
                self.is_connected = True
                self.user_data = {'username': 'Web User', 'platform': 'WhatsApp Web'}
                wx.CallAfter(self._notify_web_connection)
                return True
            return False
        except Exception as e:
            print(f"Błąd podczas uruchamiania WhatsApp Web: {e}")
            return False
    
    async def _websocket_handler(self):
        """Handle WebSocket connection"""
        try:
            async with websockets.connect(self.server_url) as websocket:
                self.websocket = websocket
                self.is_connected = True
                
                # Send login message
                login_msg = {
                    "type": "login",
                    "username": self.username,
                    "timestamp": datetime.now().isoformat()
                }
                await websocket.send(json.dumps(login_msg))
                
                # Listen for messages
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        self._handle_websocket_message(data)
                    except json.JSONDecodeError:
                        print(f"Invalid JSON received: {message}")
                        
        except Exception as e:
            print(f"WebSocket connection error: {e}")
            self.is_connected = False
    
    def _start_websocket(self):
        """Start WebSocket connection in thread"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._websocket_handler())
        except Exception as e:
            print(f"WebSocket thread error: {e}")
            self.is_connected = False
    
    def _handle_websocket_message(self, data):
        """Handle incoming WebSocket message"""
        msg_type = data.get("type")
        
        if msg_type == "message":
            sender = data.get("sender")
            message = data.get("message")
            conversation_id = data.get("conversation_id")
            
            # Add to message history
            if not hasattr(self, '_message_history'):
                self._message_history = {}
            
            if conversation_id not in self._message_history:
                self._message_history[conversation_id] = []
            
            message_data = {
                'sender': sender,
                'message': message,
                'timestamp': datetime.now().strftime("%H:%M"),
                'is_outgoing': False
            }
            self._message_history[conversation_id].append(message_data)
            
            # Notify callbacks
            for callback in self.message_callbacks:
                try:
                    wx.CallAfter(callback, sender, message, conversation_id)
                except:
                    pass
                    
        elif msg_type == "user_status":
            # Handle user status changes
            for callback in self.status_callbacks:
                try:
                    wx.CallAfter(callback, "user_status", data)
                except:
                    pass
                    
        elif msg_type == "typing":
            # Handle typing indicators
            for callback in self.typing_callbacks:
                try:
                    wx.CallAfter(callback, data)
                except:
                    pass
    
    def send_message(self, conversation_name, message):
        """Send message via Titan IM WebSocket or fallback"""
        if not self.is_connected:
            return False
        
        # Find the conversation
        conv = self.get_conversation_by_name(conversation_name)
        if not conv:
            print(f"Conversation not found: {conversation_name}")
            return False
        
        # Store message locally
        if not hasattr(self, '_message_history'):
            self._message_history = {}
        
        if conv['id'] not in self._message_history:
            self._message_history[conv['id']] = []
        
        # Add message to history
        message_data = {
            'sender': 'You',
            'message': message,
            'timestamp': datetime.now().strftime("%H:%M"),
            'is_outgoing': True
        }
        self._message_history[conv['id']].append(message_data)
        
        # Update conversation last message
        conv['last_message'] = message[:50] + ("..." if len(message) > 50 else "")
        conv['timestamp'] = message_data['timestamp']
        
        # Try to send via WebSocket if available
        if self.websocket and self.user_data.get('platform') == 'Titan IM':
            try:
                msg_data = {
                    "type": "message",
                    "message": message,
                    "recipient": conversation_name,
                    "conversation_id": conv['id'],
                    "sender": self.username,
                    "timestamp": datetime.now().isoformat()
                }
                
                # Send via WebSocket in background
                threading.Thread(
                    target=self._send_websocket_message,
                    args=(msg_data,),
                    daemon=True
                ).start()
                
            except Exception as e:
                print(f"Failed to send via WebSocket: {e}")
                # Continue with fallback
        
        # If not using WebSocket or as fallback, simulate auto-reply
        if self.user_data.get('platform') != 'Titan IM':
            self._schedule_auto_reply(conv['id'], conversation_name)
        
        print(f"Message sent to {conversation_name}: {message}")
        return True
    
    def _send_websocket_message(self, msg_data):
        """Send message via WebSocket in background thread"""
        try:
            if self.websocket:
                # Need to run in async context
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.websocket.send(json.dumps(msg_data)))
        except Exception as e:
            print(f"WebSocket send error: {e}")
    
    def _schedule_auto_reply(self, conv_id, sender_name):
        """Schedule an automatic reply for demo purposes"""
        def auto_reply():
            time.sleep(2 + (hash(conv_id) % 3))  # 2-5 seconds delay
            
            # Generate a simple response
            responses = [
                _("Thanks for the message!"),
                _("OK, understood"),
                _("Sounds good"),
                _("Yes, I agree"),
                _("No problem"),
                _("Great!")
            ]
            reply = responses[hash(conv_id + str(time.time())) % len(responses)]
            
            # Add to message history
            if hasattr(self, '_message_history') and conv_id in self._message_history:
                reply_data = {
                    'sender': sender_name,
                    'message': reply,
                    'timestamp': datetime.now().strftime("%H:%M"),
                    'is_outgoing': False
                }
                self._message_history[conv_id].append(reply_data)
                
                # Update conversation
                for conv in self._cached_conversations:
                    if conv['id'] == conv_id:
                        conv['last_message'] = reply
                        conv['timestamp'] = reply_data['timestamp']
                        conv['unread'] = conv.get('unread', 0) + 1
                        break
                
                # Notify callbacks
                for callback in self.message_callbacks:
                    try:
                        wx.CallAfter(callback, sender_name, reply, conv_id)
                    except:
                        pass
        
        # Run in background thread
        thread = threading.Thread(target=auto_reply, daemon=True)
        thread.start()
    
    def get_conversations(self):
        """Get list of available conversations from Titan IM or fallback to mock"""
        if not self.is_connected:
            return []
        
        # If connected to Titan IM, try to fetch real conversations
        if self.user_data.get('platform') == 'Titan IM':
            try:
                return self._get_titan_conversations()
            except Exception as e:
                print(f"Failed to get Titan IM conversations: {e}")
                # Fall back to mock data
        
        # Check if we have cached conversations with updated messages
        if not hasattr(self, '_cached_conversations'):
            self._cached_conversations = self._load_default_conversations()
        
        # Update timestamps and potentially new messages
        current_time = datetime.now()
        for conv in self._cached_conversations:
            if conv['id'] == '1001' and current_time.minute % 5 == 0:
                # Simulate new message every 5 minutes
                conv['last_message'] = _("New message at {}").format(current_time.strftime("%H:%M"))
                conv['unread'] += 1
        
        return self._cached_conversations
    
    def _get_titan_conversations(self):
        """Get conversations from Titan IM server"""
        try:
            # Make HTTP request to get conversations
            response = requests.get(f"{self.http_url}/api/conversations", timeout=5)
            if response.status_code == 200:
                data = response.json()
                
                # Convert to our format
                conversations = []
                for conv_data in data.get('conversations', []):
                    conversations.append({
                        'id': str(conv_data.get('id', '')),
                        'title': conv_data.get('name', conv_data.get('title', 'Unknown')),
                        'name': conv_data.get('name', conv_data.get('title', 'Unknown')),
                        'is_user': conv_data.get('type') == 'private',
                        'is_group': conv_data.get('type') == 'group',
                        'last_message': conv_data.get('last_message', ''),
                        'timestamp': conv_data.get('timestamp', ''),
                        'unread': conv_data.get('unread_count', 0),
                        'type': 'titan_im'
                    })
                
                return conversations
            else:
                print(f"Failed to get conversations: HTTP {response.status_code}")
                return self._load_default_conversations()
                
        except Exception as e:
            print(f"Error getting Titan IM conversations: {e}")
            return self._load_default_conversations()
    
    def _load_default_conversations(self):
        """Load default conversations for demo"""
        return [
            {
                'id': '1001',
                'title': 'Anna Kowalska',
                'name': 'Anna Kowalska', 
                'is_user': True,
                'is_group': False,
                'last_message': _("Hi! How are you?"),
                'timestamp': '10:30',
                'unread': 2,
                'type': 'whatsapp'
            },
            {
                'id': '1002',
                'title': 'Jan Nowak',
                'name': 'Jan Nowak',
                'is_user': True,
                'is_group': False,
                'last_message': _("Are we meeting today?"),
                'timestamp': '09:15',
                'unread': 0,
                'type': 'whatsapp'
            },
            {
                'id': '2001', 
                'title': _("Work Group"),
                'name': _("Work Group"),
                'is_user': False,
                'is_group': True, 
                'last_message': _("Projects for tomorrow"),
                'timestamp': '08:45',
                'unread': 5,
                'type': 'whatsapp'
            },
            {
                'id': '1003',
                'title': 'Maria Wierzyńska',
                'name': 'Maria Wierzyńska',
                'is_user': True,
                'is_group': False,
                'last_message': _("Thanks for the help!"),
                'timestamp': _("yesterday"),
                'unread': 0,
                'type': 'whatsapp'
            },
            {
                'id': '1004',
                'title': 'Piotr Kowalczyk',
                'name': 'Piotr Kowalczyk',
                'is_user': True,
                'is_group': False,
                'last_message': _("Great, thanks!"),
                'timestamp': '14:22',
                'unread': 1,
                'type': 'whatsapp'
            },
            {
                'id': '2002', 
                'title': _("Work Friends"),
                'name': _("Work Friends"),
                'is_user': False,
                'is_group': True, 
                'last_message': _("Who's going for coffee?"),
                'timestamp': '13:15',
                'unread': 3,
                'type': 'whatsapp'
            }
        ]
    
    def get_message_history(self, conversation_id):
        """Get message history for a conversation"""
        if not hasattr(self, '_message_history'):
            self._message_history = {}
        
        return self._message_history.get(conversation_id, [])
    
    def mark_conversation_read(self, conversation_id):
        """Mark conversation as read"""
        for conv in self._cached_conversations:
            if conv['id'] == conversation_id:
                conv['unread'] = 0
                break
        
    def get_conversation_by_name(self, name):
        """Find conversation by name"""
        for conv in self.get_conversations():
            if conv['name'] == name or conv['title'] == name:
                return conv
        return None
    
    def _notify_titan_connection(self):
        """Notify about Titan IM connection"""
        print(_("Connected to Titan IM server"))
        
        # Use TTS to announce Titan IM connection
        try:
            import accessible_output3.outputs.auto
            speaker = accessible_output3.outputs.auto.Auto()
            speaker.speak(_("Connected to Titan IM"))
        except:
            pass
        
        # Play welcome sound
        play_sound('titannet/welcome to IM.ogg')
        
        for callback in self.status_callbacks:
            try:
                callback('titan_connection', self.user_data)
            except:
                pass
    
    def _notify_web_connection(self):
        """Notify about web connection"""
        print(_("Opened WhatsApp Web in web browser"))
        
        # Use TTS to announce web connection
        try:
            import accessible_output3.outputs.auto
            speaker = accessible_output3.outputs.auto.Auto()
            speaker.speak(_("Opened WhatsApp Web in web browser"))
        except:
            pass
        
        # Play welcome sound
        play_sound('titannet/welcome to IM.ogg')
        
        for callback in self.status_callbacks:
            try:
                callback('web_connection', self.user_data)
            except:
                pass
    
    def _notify_error(self, error_message):
        """Notify about errors"""
        play_sound('core/error.ogg')
        print(f"WhatsApp error: {error_message}")
        wx.MessageBox(error_message, _("WhatsApp Error"), wx.OK | wx.ICON_ERROR)
    
    def disconnect(self):
        """Disconnect from WhatsApp"""
        self.is_connected = False
        play_sound('titannet/bye.ogg')
        print(_("Disconnected from WhatsApp Web"))

# Global client instance
whatsapp_client = WhatsAppClient()

def connect_to_whatsapp(username="TitanUser"):
    """Connect to Titan IM or fallback to WhatsApp Web"""
    success = whatsapp_client.start_connection(username)
    return whatsapp_client if success else None

def disconnect_from_whatsapp():
    """Disconnect from WhatsApp Web"""
    whatsapp_client.disconnect()

def send_message(conversation_name, message):
    """Send message through WhatsApp"""
    return whatsapp_client.send_message(conversation_name, message)

def get_conversations():
    """Get list of conversations"""
    return whatsapp_client.get_conversations()

def add_message_callback(callback):
    """Add message callback"""
    return whatsapp_client.add_message_callback(callback)

def is_connected():
    """Check if connected to WhatsApp"""
    return whatsapp_client.is_connected

def get_user_data():
    """Get current user data"""
    return whatsapp_client.user_data

def add_status_callback(callback):
    """Add status callback"""
    return whatsapp_client.add_status_callback(callback)