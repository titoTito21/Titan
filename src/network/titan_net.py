"""
Titan-Net Client API
Handles WebSocket communication with Titan-Net server for authentication and messaging
"""
import asyncio
import websockets
import json
import threading
import time
from typing import Optional, Dict, List, Callable
import random
from src.titan_core.translation import set_language
from src.settings.settings import get_setting

# Get the translation function
_ = set_language(get_setting('language', 'pl'))


class TitanNetClient:
    """Client for Titan-Net server communication"""

    def __init__(self, server_host: str = "localhost", server_port: int = 8001):
        """
        Initialize Titan-Net client

        Args:
            server_host: Hostname of the Titan-Net server
            server_port: WebSocket port (default 8001)
        """
        self.server_host = server_host
        self.server_port = server_port
        self.ws_url = f"ws://{server_host}:{server_port}"

        self.websocket = None
        self.session_id: Optional[str] = None
        self.username: Optional[str] = None
        self.user_id: Optional[int] = None
        self.titan_number: Optional[int] = None
        self.is_connected = False

        # Callbacks
        self.on_user_online: Optional[Callable] = None
        self.on_user_offline: Optional[Callable] = None
        self.on_account_created: Optional[Callable] = None
        self.on_message_received: Optional[Callable] = None
        self.on_connection_lost: Optional[Callable] = None
        self.on_room_message: Optional[Callable] = None
        self.on_room_created: Optional[Callable] = None
        self.on_room_joined: Optional[Callable] = None
        self.on_room_deleted: Optional[Callable] = None
        self.on_user_joined_room: Optional[Callable] = None
        self.on_user_left_room: Optional[Callable] = None

        # Listener thread
        self.listener_thread: Optional[threading.Thread] = None
        self.listener_running = False

        # Event loop for WebSocket - persistent loop in separate thread
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.loop_thread: Optional[threading.Thread] = None
        self.loop_ready = threading.Event()

        # Request/response tracking - maps message type to response
        self._pending_requests = {}  # {msg_type: asyncio.Event}
        self._cached_responses = {}  # {msg_type: response}

        # Start persistent event loop thread
        self._start_event_loop()

    def _start_event_loop(self):
        """Start persistent event loop in separate thread"""
        def run_loop():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop_ready.set()
            self.loop.run_forever()

        self.loop_thread = threading.Thread(target=run_loop, daemon=True)
        self.loop_thread.start()
        self.loop_ready.wait()  # Wait for loop to be ready

    def _stop_event_loop(self):
        """Stop the persistent event loop"""
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
            if self.loop_thread:
                self.loop_thread.join(timeout=2)

    def __del__(self):
        """Cleanup when object is destroyed"""
        try:
            self._stop_event_loop()
        except:
            pass

    def _run_async(self, coro):
        """Run async coroutine in persistent event loop"""
        if self.loop is None or not self.loop.is_running():
            raise RuntimeError("Event loop is not running")

        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=30)  # 30 second timeout

    async def _connect(self):
        """Connect to WebSocket server"""
        try:
            # Add timeout to prevent hanging when server is unreachable
            self.websocket = await asyncio.wait_for(
                websockets.connect(self.ws_url, ping_interval=30),
                timeout=5.0  # 5 second timeout
            )
            return True
        except asyncio.TimeoutError:
            print(f"Connection timeout: server not responding")
            return False
        except Exception as e:
            print(f"Connection error: {e}")
            return False

    async def _send_and_wait_direct(self, message: Dict, timeout: int = 10) -> Optional[Dict]:
        """Send message and wait for direct response (without listener)"""
        try:
            await self.websocket.send(json.dumps(message))
            response_raw = await asyncio.wait_for(self.websocket.recv(), timeout=timeout)
            response = json.loads(response_raw)
            return response
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            print(f"Send error: {e}")
            return None

    async def _send_and_wait(self, message: Dict, expected_response_type: str, timeout: int = 10) -> Optional[Dict]:
        """Send message and wait for response via listener (for active connections)"""
        try:
            # Create asyncio event to wait for response of this type
            response_event = asyncio.Event()
            self._pending_requests[expected_response_type] = response_event
            # Clear any old cached response
            self._cached_responses.pop(expected_response_type, None)

            # Send message
            await self.websocket.send(json.dumps(message))

            # Wait for response from listener (asyncio await, not blocking)
            try:
                await asyncio.wait_for(response_event.wait(), timeout=timeout)
                result = self._cached_responses.get(expected_response_type)
                # Clean up
                self._cached_responses.pop(expected_response_type, None)
                self._pending_requests.pop(expected_response_type, None)
                return result
            except asyncio.TimeoutError:
                # Timeout
                self._pending_requests.pop(expected_response_type, None)
                return None

        except Exception as e:
            print(f"Send error: {e}")
            # Clean up
            self._pending_requests.pop(expected_response_type, None)
            return None

    def check_server(self) -> bool:
        """
        Check if Titan-Net server is accessible

        Returns:
            bool: True if server is reachable, False otherwise
        """
        try:
            async def _check():
                try:
                    # Try to connect with short timeout
                    ws = await asyncio.wait_for(
                        websockets.connect(self.ws_url, ping_interval=None),
                        timeout=5.0  # Increased timeout to 5 seconds
                    )
                    await ws.close()
                    return True
                except asyncio.TimeoutError:
                    return False
                except ConnectionRefusedError:
                    return False
                except Exception:
                    return False

            return self._run_async(_check())
        except Exception:
            return False

    def register(self, username: str, password: str, full_name: str = "") -> Dict:
        """
        Register a new account on Titan-Net

        Args:
            username: Desired username
            password: Account password
            full_name: Optional full name

        Returns:
            Dict with 'success' (bool), 'message' (str), 'user_id', and 'titan_number' (5-digit)
        """
        try:
            async def _register():
                # Connect to server
                if not await self._connect():
                    return {
                        'success': False,
                        'message': _('Cannot connect to Titan-Net server')
                    }

                # Send registration request
                request = {
                    "type": "register",
                    "username": username,
                    "password": password,
                    "full_name": full_name
                }

                response = await self._send_and_wait_direct(request)

                # Close connection
                await self.websocket.close()

                if not response:
                    return {
                        'success': False,
                        'message': _('No response from server')
                    }

                if response.get('type') == 'register_response' and response.get('success'):
                    titan_number = response.get('titan_number')

                    # Trigger account created callback
                    if self.on_account_created:
                        self.on_account_created(username, titan_number)

                    return {
                        'success': True,
                        'message': _('Account created successfully'),
                        'user_id': response.get('user_id'),
                        'titan_number': titan_number
                    }
                else:
                    return {
                        'success': False,
                        'message': response.get('error', _('Registration failed'))
                    }

            return self._run_async(_register())

        except Exception as e:
            return {
                'success': False,
                'message': _('Registration error: {error}').format(error=str(e))
            }

    def login(self, username: str, password: str) -> Dict:
        """
        Login to Titan-Net

        Args:
            username: Username
            password: Password

        Returns:
            Dict with 'success' (bool), 'message' (str), 'session_id', and user data
        """
        try:
            async def _login():
                # Connect to server
                if not await self._connect():
                    return {
                        'success': False,
                        'message': _('Cannot connect to Titan-Net server')
                    }

                # Send login request
                request = {
                    "type": "login",
                    "username": username,
                    "password": password
                }

                response = await self._send_and_wait_direct(request)

                if not response:
                    await self.websocket.close()
                    return {
                        'success': False,
                        'message': _('No response from server')
                    }

                if response.get('type') == 'login_response' and response.get('success'):
                    self.session_id = response.get('session_id')
                    user_data = response.get('user', {})
                    self.username = user_data.get('username', username)
                    self.user_id = user_data.get('id')
                    self.titan_number = user_data.get('titan_number')
                    self.is_connected = True

                    # Start message listener
                    self._start_listener()

                    # Trigger user online callback
                    if self.on_user_online:
                        self.on_user_online(self.username)

                    return {
                        'success': True,
                        'message': _('Login successful'),
                        'session_id': self.session_id,
                        'user': user_data,
                        'online_users': response.get('online_users', [])
                    }
                else:
                    await self.websocket.close()
                    return {
                        'success': False,
                        'message': response.get('error', _('Login failed'))
                    }

            return self._run_async(_login())

        except Exception as e:
            return {
                'success': False,
                'message': _('Login error: {error}').format(error=str(e))
            }

    def logout(self) -> Dict:
        """
        Logout from Titan-Net

        Returns:
            Dict with 'success' (bool) and 'message' (str)
        """
        if not self.is_connected:
            return {
                'success': False,
                'message': _('Not logged in')
            }

        try:
            # Stop listener
            self._stop_listener()

            # Trigger user offline callback before closing
            if self.on_user_offline:
                self.on_user_offline(self.username)

            # Close WebSocket connection
            if self.websocket:
                try:
                    async def _close():
                        await self.websocket.close()

                    self._run_async(_close())
                except Exception:
                    pass  # Ignore errors during websocket close

            # Clear session data
            self.session_id = None
            self.username = None
            self.user_id = None
            self.titan_number = None
            self.is_connected = False

            return {
                'success': True,
                'message': _('Logout successful')
            }

        except Exception as e:
            # Even if logout fails, clear local session
            self.session_id = None
            self.username = None
            self.user_id = None
            self.titan_number = None
            self.is_connected = False

            return {
                'success': False,
                'message': _('Logout error: {error}').format(error=str(e))
            }

    def send_private_message(self, recipient_id: int, message: str) -> Dict:
        """
        Send a private message to another user

        Args:
            recipient_id: User ID of recipient
            message: Message content

        Returns:
            Dict with 'success' (bool) and 'message' (str)
        """
        if not self.is_connected or not self.websocket:
            return {
                'success': False,
                'message': _('Not logged in')
            }

        try:
            async def _send_message():
                request = {
                    "type": "private_message",
                    "recipient_id": recipient_id,
                    "message": message
                }

                await self.websocket.send(json.dumps(request))

                return {
                    'success': True,
                    'message': _('Message sent')
                }

            return self._run_async(_send_message())

        except Exception as e:
            return {
                'success': False,
                'message': _('Error sending message: {error}').format(error=str(e))
            }

    def create_room(self, name: str, description: str = "", room_type: str = "text", password: str = "") -> Dict:
        """
        Create a chat room

        Args:
            name: Room name
            description: Room description
            room_type: 'text' or 'voice'
            password: Optional password for private room

        Returns:
            Dict with 'success' (bool), 'room_id' (int), and 'message' (str)
        """
        if not self.is_connected or not self.websocket:
            return {
                'success': False,
                'message': _('Not logged in')
            }

        try:
            async def _create_room():
                request = {
                    "type": "create_room",
                    "name": name,
                    "description": description,
                    "room_type": room_type
                }
                if password:
                    request["password"] = password

                response = await self._send_and_wait(request, "room_created")

                if response and response.get('type') == 'room_created':
                    if response.get('success'):
                        return {
                            'success': True,
                            'room_id': response.get('room_id'),
                            'message': _('Room created successfully')
                        }
                    else:
                        return {
                            'success': False,
                            'message': response.get('error', _('Failed to create room'))
                        }
                return {
                    'success': False,
                    'message': _('No response from server')
                }

            return self._run_async(_create_room())

        except Exception as e:
            return {
                'success': False,
                'message': _('Error creating room: {error}').format(error=str(e))
            }

    def join_room(self, room_id: int, password: str = "") -> Dict:
        """
        Join a chat room

        Args:
            room_id: ID of the room to join
            password: Password if room is private

        Returns:
            Dict with 'success' (bool) and 'message' (str)
        """
        if not self.is_connected or not self.websocket:
            return {
                'success': False,
                'message': _('Not logged in')
            }

        try:
            async def _join_room():
                request = {
                    "type": "join_room",
                    "room_id": room_id
                }
                if password:
                    request["password"] = password

                response = await self._send_and_wait(request, "room_joined")

                if response and response.get('type') == 'room_joined':
                    if response.get('success'):
                        return {
                            'success': True,
                            'message': _('Joined room successfully')
                        }
                    else:
                        return {
                            'success': False,
                            'message': response.get('error', _('Failed to join room'))
                        }
                return {
                    'success': False,
                    'message': _('No response from server')
                }

            return self._run_async(_join_room())

        except Exception as e:
            return {
                'success': False,
                'message': _('Error joining room: {error}').format(error=str(e))
            }

    def leave_room(self, room_id: int) -> Dict:
        """
        Leave a chat room

        Args:
            room_id: ID of the room to leave

        Returns:
            Dict with 'success' (bool) and 'message' (str)
        """
        if not self.is_connected or not self.websocket:
            return {
                'success': False,
                'message': _('Not logged in')
            }

        try:
            async def _leave_room():
                request = {
                    "type": "leave_room",
                    "room_id": room_id
                }

                await self.websocket.send(json.dumps(request))

                return {
                    'success': True,
                    'message': _('Left room')
                }

            return self._run_async(_leave_room())

        except Exception as e:
            return {
                'success': False,
                'message': _('Error leaving room: {error}').format(error=str(e))
            }

    def delete_room(self, room_id: int) -> Dict:
        """
        Delete a chat room (creator only)

        Args:
            room_id: ID of the room to delete

        Returns:
            Dict with 'success' (bool) and 'message' (str)
        """
        if not self.is_connected or not self.websocket:
            return {
                'success': False,
                'message': _('Not logged in')
            }

        try:
            async def _delete_room():
                request = {
                    "type": "delete_room",
                    "room_id": room_id
                }

                response = await self._send_and_wait(request, "room_deleted")

                if response and response.get('type') == 'room_deleted':
                    if response.get('success'):
                        return {
                            'success': True,
                            'message': _('Room deleted')
                        }
                    else:
                        return {
                            'success': False,
                            'message': _('Failed to delete room')
                        }
                return {
                    'success': False,
                    'message': _('No response from server')
                }

            return self._run_async(_delete_room())

        except Exception as e:
            return {
                'success': False,
                'message': _('Error deleting room: {error}').format(error=str(e))
            }

    def send_room_message(self, room_id: int, message: str) -> Dict:
        """
        Send a message to a chat room

        Args:
            room_id: ID of the room
            message: Message content

        Returns:
            Dict with 'success' (bool) and 'message' (str)
        """
        if not self.is_connected or not self.websocket:
            return {
                'success': False,
                'message': _('Not logged in')
            }

        try:
            async def _send_room_message():
                request = {
                    "type": "room_message",
                    "room_id": room_id,
                    "message": message
                }

                await self.websocket.send(json.dumps(request))

                return {
                    'success': True,
                    'message': _('Message sent')
                }

            return self._run_async(_send_room_message())

        except Exception as e:
            return {
                'success': False,
                'message': _('Error sending message: {error}').format(error=str(e))
            }

    def get_rooms(self) -> Dict:
        """
        Get list of available chat rooms

        Returns:
            Dict with 'success' (bool), 'rooms' (list), and 'message' (str)
        """
        if not self.is_connected or not self.websocket:
            return {
                'success': False,
                'message': _('Not logged in'),
                'rooms': []
            }

        try:
            async def _get_rooms():
                request = {"type": "get_rooms"}

                response = await self._send_and_wait(request, "rooms_list")

                if response and response.get('type') == 'rooms_list':
                    return {
                        'success': True,
                        'rooms': response.get('rooms', []),
                        'message': _('Rooms retrieved')
                    }
                return {
                    'success': False,
                    'rooms': [],
                    'message': _('No response from server')
                }

            return self._run_async(_get_rooms())

        except Exception as e:
            return {
                'success': False,
                'rooms': [],
                'message': _('Error getting rooms: {error}').format(error=str(e))
            }

    def get_online_users(self) -> Dict:
        """
        Get list of online users

        Returns:
            Dict with 'success' (bool), 'users' (list), and 'message' (str)
        """
        if not self.is_connected or not self.websocket:
            return {
                'success': False,
                'message': _('Not logged in'),
                'users': []
            }

        try:
            async def _get_online_users():
                request = {"type": "get_online_users"}

                response = await self._send_and_wait(request, "online_users")

                if response and response.get('type') == 'online_users':
                    return {
                        'success': True,
                        'users': response.get('users', []),
                        'message': _('Users retrieved')
                    }
                return {
                    'success': False,
                    'users': [],
                    'message': _('No response from server')
                }

            return self._run_async(_get_online_users())

        except Exception as e:
            return {
                'success': False,
                'users': [],
                'message': _('Error getting users: {error}').format(error=str(e))
            }

    def get_room_messages(self, room_id: int, limit: int = 100) -> Dict:
        """
        Get message history from a chat room

        Args:
            room_id: ID of the room
            limit: Maximum number of messages to retrieve

        Returns:
            Dict with 'success' (bool), 'messages' (list), and 'message' (str)
        """
        if not self.is_connected or not self.websocket:
            return {
                'success': False,
                'message': _('Not logged in'),
                'messages': []
            }

        try:
            async def _get_room_messages():
                request = {
                    "type": "get_room_messages",
                    "room_id": room_id,
                    "limit": limit
                }

                response = await self._send_and_wait(request, "room_messages")

                if response and response.get('type') == 'room_messages':
                    return {
                        'success': True,
                        'messages': response.get('messages', []),
                        'message': _('Messages retrieved')
                    }
                return {
                    'success': False,
                    'messages': [],
                    'message': _('No response from server')
                }

            return self._run_async(_get_room_messages())

        except Exception as e:
            return {
                'success': False,
                'messages': [],
                'message': _('Error getting messages: {error}').format(error=str(e))
            }

    def get_private_messages(self, user_id: int, limit: int = 100) -> Dict:
        """
        Get private message history with a user

        Args:
            user_id: ID of the other user
            limit: Maximum number of messages to retrieve

        Returns:
            Dict with 'success' (bool), 'messages' (list), and 'message' (str)
        """
        if not self.is_connected or not self.websocket:
            return {
                'success': False,
                'message': _('Not logged in'),
                'messages': []
            }

        try:
            async def _get_private_messages():
                request = {
                    "type": "get_messages",
                    "user_id": user_id,
                    "limit": limit
                }

                response = await self._send_and_wait(request, "private_messages")

                if response and response.get('type') == 'private_messages':
                    return {
                        'success': True,
                        'messages': response.get('messages', []),
                        'message': _('Messages retrieved')
                    }
                return {
                    'success': False,
                    'messages': [],
                    'message': _('No response from server')
                }

            return self._run_async(_get_private_messages())

        except Exception as e:
            return {
                'success': False,
                'messages': [],
                'message': _('Error getting messages: {error}').format(error=str(e))
            }

    def _start_listener(self):
        """Start WebSocket message listener thread"""
        if self.listener_running:
            return

        self.listener_running = True
        self.listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.listener_thread.start()

    def _stop_listener(self):
        """Stop message listener thread"""
        self.listener_running = False
        if self.listener_thread:
            self.listener_thread.join(timeout=2)
            self.listener_thread = None

    def _listen_loop(self):
        """Listen for incoming messages from server"""
        async def _listener():
            try:
                while self.listener_running and self.is_connected:
                    if self.websocket:
                        try:
                            message_raw = await asyncio.wait_for(self.websocket.recv(), timeout=1.0)
                            message = json.loads(message_raw)

                            # Check if this is a response to a pending request
                            msg_type = message.get('type')
                            if msg_type in self._pending_requests:
                                self._cached_responses[msg_type] = message
                                self._pending_requests[msg_type].set()
                                continue  # Don't process as regular message

                            # Handle different message types

                            if msg_type == 'private_message':
                                if self.on_message_received:
                                    self.on_message_received(message)
                            elif msg_type == 'user_registered':
                                # Broadcast when new user registers
                                if self.on_account_created:
                                    username = message.get('username')
                                    titan_number = message.get('titan_number')
                                    self.on_account_created(username, titan_number)
                            elif msg_type == 'user_status':
                                # Handle user online/offline status
                                status = message.get('status')
                                username = message.get('username')
                                if status == 'online' and self.on_user_online:
                                    self.on_user_online(username)
                                elif status == 'offline' and self.on_user_offline:
                                    self.on_user_offline(username)
                            elif msg_type == 'room_message':
                                # Room message received
                                if self.on_room_message:
                                    self.on_room_message(message)
                            elif msg_type == 'new_room':
                                # New room created broadcast
                                if self.on_room_created:
                                    self.on_room_created(message)
                            elif msg_type == 'room_removed':
                                # Room deleted broadcast
                                if self.on_room_deleted:
                                    self.on_room_deleted(message.get('room_id'))
                            elif msg_type == 'user_joined_room':
                                # User joined room notification
                                if self.on_user_joined_room:
                                    self.on_user_joined_room(message)
                            elif msg_type == 'user_left_room':
                                # User left room notification
                                if self.on_user_left_room:
                                    self.on_user_left_room(message)

                        except asyncio.TimeoutError:
                            continue
                        except websockets.exceptions.ConnectionClosed:
                            break
                    else:
                        break

            except Exception as e:
                print(f"Listener error: {e}")
                if self.on_connection_lost:
                    self.on_connection_lost()

        # Use the main event loop instead of creating a new one
        # This prevents the "Future attached to different loop" error
        future = asyncio.run_coroutine_threadsafe(_listener(), self.loop)
        try:
            future.result()
        except Exception as e:
            print(f"Listener thread error: {e}")
