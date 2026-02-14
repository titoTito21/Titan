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
import requests
import base64
from src.titan_core.translation import set_language
from src.settings.settings import get_setting

# Get the translation function
_ = set_language(get_setting('language', 'pl'))


class TitanNetClient:
    """Client for Titan-Net server communication"""

    def __init__(self, server_host: str = "titosofttitan.com", server_port: int = 8001, http_port: int = 8000):
        """
        Initialize Titan-Net client

        Args:
            server_host: Hostname of the Titan-Net server
            server_port: WebSocket port (default 8001)
            http_port: HTTP API port (default 8000)
        """
        self.server_host = server_host
        self.server_port = server_port
        self.http_port = http_port
        self.ws_url = f"ws://{server_host}:{server_port}"
        self.http_url = f"http://{server_host}:{http_port}"

        print(f"[TITAN-NET] Client initialized")
        print(f"[TITAN-NET] WebSocket URL: {self.ws_url}")
        print(f"[TITAN-NET] HTTP URL: {self.http_url}")

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

        # Voice chat callbacks
        self.on_voice_started: Optional[Callable] = None    # User started speaking
        self.on_voice_audio: Optional[Callable] = None      # Audio chunk received
        self.on_voice_stopped: Optional[Callable] = None    # User stopped speaking

        # Broadcast callback (moderator messages)
        self.on_broadcast_received: Optional[Callable] = None  # Moderation broadcast received

        # Package/App repository callbacks
        self.on_package_pending: Optional[Callable] = None     # New package submitted (waiting room)
        self.on_package_approved: Optional[Callable] = None    # Package approved by moderation

        # New user broadcast callback
        self.on_new_user_broadcast: Optional[Callable] = None  # New user registration broadcast

        # Listener thread
        self.listener_thread: Optional[threading.Thread] = None
        self.listener_running = False

        # Event loop for WebSocket - persistent loop in separate thread
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.loop_thread: Optional[threading.Thread] = None
        self.loop_ready = threading.Event()

        # Request/response tracking - maps unique request ID to response
        self._pending_requests = {}  # {request_id: asyncio.Event}
        self._cached_responses = {}  # {request_id: response}
        self._request_counter = 0  # Counter for unique request IDs
        self._request_lock = threading.Lock()  # Lock for request counter

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
            if self.loop_thread and self.loop_thread.is_alive():
                self.loop_thread.join(timeout=2)
        self.loop = None

    def __del__(self):
        """Cleanup when object is destroyed"""
        try:
            self._stop_listener()
            self._stop_event_loop()
        except:
            pass  # Ignore errors during cleanup

    def _run_async(self, coro):
        """Run async coroutine in persistent event loop"""
        if self.loop is None or not self.loop.is_running():
            raise RuntimeError("Event loop is not running")

        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=60)  # 60 second timeout for all operations including uploads

    async def _connect(self):
        """Connect to WebSocket server"""
        try:
            print(f"[TITAN-NET] Connecting to {self.ws_url}...")
            # Close any existing websocket
            if self.websocket:
                print(f"[TITAN-NET] Closing existing websocket...")
                try:
                    await self.websocket.close()
                except:
                    pass
                self.websocket = None

            # Add timeout to prevent hanging when server is unreachable
            # Optimized settings for 30-40 users with voice chat
            self.websocket = await asyncio.wait_for(
                websockets.connect(
                    self.ws_url,
                    ping_interval=None,
                    close_timeout=5,
                    max_size=50 * 1024 * 1024,   # 50MB for many users with voice
                    max_queue=1024,              # Large queue for voice packets
                    write_limit=2 * 1024 * 1024, # 2MB write buffer
                    compression=None             # No compression for low latency
                ),
                timeout=3.0  # 3 second timeout
            )
            print(f"[TITAN-NET] Connected successfully!")
            return True
        except asyncio.TimeoutError:
            print(f"[TITAN-NET] Connection timeout: server not responding at {self.ws_url}")
            return False
        except Exception as e:
            print(f"[TITAN-NET] Connection error to {self.ws_url}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def _send_and_wait(self, message: Dict, expected_response_type: str, timeout: int = 5) -> Optional[Dict]:
        """Send message and wait for response via listener (for active connections)"""
        try:
            # Generate unique request ID to handle concurrent requests of the same type
            with self._request_lock:
                self._request_counter += 1
                request_id = f"{expected_response_type}_{self._request_counter}"

            # Create asyncio event to wait for response
            response_event = asyncio.Event()
            self._pending_requests[request_id] = (response_event, expected_response_type)

            # Add request ID to message for tracking (optional, depends on protocol)
            message_copy = message.copy()
            message_copy['_request_id'] = request_id

            # Send message
            await self.websocket.send(json.dumps(message_copy))

            # Wait for response from listener (asyncio await, not blocking)
            try:
                await asyncio.wait_for(response_event.wait(), timeout=timeout)
                result = self._cached_responses.get(request_id)
                # Clean up
                self._cached_responses.pop(request_id, None)
                self._pending_requests.pop(request_id, None)
                return result
            except asyncio.TimeoutError:
                # Timeout - clean up
                self._pending_requests.pop(request_id, None)
                return None

        except Exception as e:
            print(f"Send error: {e}")
            # Clean up on error
            if 'request_id' in locals():
                self._pending_requests.pop(request_id, None)
            return None

    def check_server(self) -> bool:
        """
        Check if Titan-Net server is accessible

        Returns:
            bool: True if server is reachable, False otherwise
        """
        try:
            print(f"[TITAN-NET] Checking server at {self.ws_url}...")
            async def _check():
                try:
                    # Try to connect with short timeout and optimized settings
                    ws = await asyncio.wait_for(
                        websockets.connect(
                            self.ws_url,
                            ping_interval=None,
                            max_size=50 * 1024 * 1024,   # 50MB
                            max_queue=1024,              # Large queue
                            write_limit=2 * 1024 * 1024, # 2MB write buffer
                            compression=None
                        ),
                        timeout=10.0  # Server check - 10 seconds for international connections
                    )
                    await ws.close()
                    print(f"[TITAN-NET] Server check: OK")
                    return True
                except asyncio.TimeoutError:
                    print(f"[TITAN-NET] Server check: Timeout")
                    return False
                except ConnectionRefusedError:
                    print(f"[TITAN-NET] Server check: Connection refused")
                    return False
                except Exception as e:
                    print(f"[TITAN-NET] Server check: Error - {type(e).__name__}: {e}")
                    return False

            result = self._run_async(_check())
            print(f"[TITAN-NET] Server check result: {result}")
            return result
        except Exception as e:
            print(f"[TITAN-NET] Server check exception: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
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
                ws = None
                try:
                    print(f"[TITAN-NET] Registering {username} at {self.ws_url}")
                    # Create dedicated connection with optimized settings
                    ws = await asyncio.wait_for(
                        websockets.connect(
                            self.ws_url,
                            ping_interval=None,
                            max_size=50 * 1024 * 1024,   # 50MB for many users
                            max_queue=1024,              # Large queue
                            write_limit=2 * 1024 * 1024, # 2MB write buffer
                            compression=None
                        ),
                        timeout=10.0
                    )
                    print(f"[TITAN-NET] Connected")

                    # Send registration request
                    from src.settings.settings import get_setting
                    current_language = get_setting('language', 'en')

                    request = {
                        "type": "register",
                        "username": username,
                        "password": password,
                        "full_name": full_name,
                        "language": current_language
                    }

                    await ws.send(json.dumps(request))
                    print(f"[TITAN-NET] Request sent")

                    # Wait for response
                    response_raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    response = json.loads(response_raw)
                    print(f"[TITAN-NET] Response: {response.get('success')}")

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
                except asyncio.TimeoutError:
                    print(f"[TITAN-NET] Timeout")
                    return {
                        'success': False,
                        'message': _('Cannot connect to Titan-Net server')
                    }
                except Exception as e:
                    print(f"[TITAN-NET] Error: {e}")
                    return {
                        'success': False,
                        'message': _('Registration error: {error}').format(error=str(e))
                    }
                finally:
                    if ws:
                        try:
                            await ws.close()
                        except:
                            pass

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
            print(f"[TITAN-NET] Logging in {username} at {self.ws_url}")

            async def _login():
                try:
                    # Create dedicated connection for login with optimized settings for 30-40 users with voice
                    ws = await asyncio.wait_for(
                        websockets.connect(
                            self.ws_url,
                            ping_interval=None,
                            max_size=50 * 1024 * 1024,   # 50MB for many users with voice
                            max_queue=1024,              # Very large queue for voice packets
                            write_limit=2 * 1024 * 1024, # 2MB write buffer
                            compression=None             # Disable compression for lower latency
                        ),
                        timeout=10.0
                    )
                    print(f"[TITAN-NET] Connected")

                    # Send login request
                    request = {
                        "type": "login",
                        "username": username,
                        "password": password
                    }

                    await ws.send(json.dumps(request))
                    print(f"[TITAN-NET] Request sent")

                    # Wait for response
                    response_raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    response = json.loads(response_raw)
                    print(f"[TITAN-NET] Response: {response.get('success')}")

                    if response.get('type') == 'login_response' and response.get('success'):
                        # Store the websocket for persistent connection
                        self.websocket = ws
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
                            'online_users': response.get('online_users', []),
                            'unread_messages_summary': response.get('unread_messages_summary', [])
                        }
                    else:
                        await ws.close()
                        return {
                            'success': False,
                            'message': response.get('error', _('Login failed'))
                        }
                except asyncio.TimeoutError:
                    print(f"[TITAN-NET] Timeout")
                    return {
                        'success': False,
                        'message': _('Cannot connect to Titan-Net server')
                    }
                except Exception as e:
                    print(f"[TITAN-NET] Error: {e}")
                    return {
                        'success': False,
                        'message': _('Login error: {error}').format(error=str(e))
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

    def get_all_users(self) -> Dict:
        """
        Get list of all registered users (moderator/developer only)

        Returns:
            Dict with 'success' (bool), 'users' (list), and 'message' (str)
        """
        try:
            response = requests.get(
                f"{self.http_url}/api/users/all",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "users": []
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

    # ==================== Voice Chat Methods ====================

    def start_voice_transmission(self, room_id: int) -> Dict:
        """
        Start transmitting voice to room

        Args:
            room_id: Room ID to transmit voice to

        Returns:
            Dict with success status
        """
        try:
            if not self.websocket or not self.is_connected:
                return {"success": False, "message": "Not connected to server"}

            async def _start_voice():
                message = {
                    "type": "voice_start",
                    "room_id": room_id,
                    "audio_config": {
                        "sample_rate": 16000,
                        "channels": 1,
                        "sample_width": 2
                    }
                }
                await self.websocket.send(json.dumps(message))

            self._run_async(_start_voice())
            return {"success": True, "message": "Voice transmission started"}

        except Exception as e:
            return {"success": False, "message": str(e)}

    def send_voice_audio(self, room_id: int, audio_data: bytes, self_monitor: bool = False) -> bool:
        """
        Send audio chunk to room

        Args:
            room_id: Room ID
            audio_data: Raw audio bytes (PCM 16-bit)
            self_monitor: If True, sender will receive audio back for testing

        Returns:
            True if sent successfully
        """
        try:
            if not self.websocket or not self.is_connected:
                return False

            import base64

            async def _send_audio():
                message = {
                    "type": "voice_audio",
                    "room_id": room_id,
                    "data": base64.b64encode(audio_data).decode('utf-8'),
                    "self_monitor": self_monitor
                }
                await self.websocket.send(json.dumps(message))

            self._run_async(_send_audio())
            return True

        except Exception as e:
            print(f"Error sending voice audio: {e}")
            return False

    def stop_voice_transmission(self, room_id: int) -> Dict:
        """
        Stop voice transmission

        Args:
            room_id: Room ID

        Returns:
            Dict with success status
        """
        try:
            if not self.websocket or not self.is_connected:
                return {"success": False, "message": "Not connected to server"}

            async def _stop_voice():
                message = {
                    "type": "voice_stop",
                    "room_id": room_id
                }
                await self.websocket.send(json.dumps(message))

            self._run_async(_stop_voice())
            return {"success": True, "message": "Voice transmission stopped"}

        except Exception as e:
            return {"success": False, "message": str(e)}

    def send_broadcast(self, text_message: str = "", voice_data: bytes = None) -> Dict:
        """
        Send broadcast message to all users (moderator/developer only)

        Args:
            text_message: Text message to broadcast
            voice_data: Optional voice data (raw audio bytes, will be base64 encoded)

        Returns:
            Dict with success status and message
        """
        try:
            if not self.websocket or not self.is_connected:
                return {"success": False, "message": "Not connected to server"}

            # Encode voice data if provided
            voice_data_encoded = None
            if voice_data:
                voice_data_encoded = base64.b64encode(voice_data).decode('utf-8')

            async def _send_broadcast_async():
                message = {
                    "type": "send_broadcast",
                    "text_message": text_message,
                    "voice_data": voice_data_encoded
                }
                response = await self._send_and_wait(message, 'broadcast_response', timeout=5)
                return response

            # Execute async function and wait for response
            response = self._run_async(_send_broadcast_async())
            return response if response else {"success": False, "message": "No response from server"}

        except Exception as e:
            return {"success": False, "message": str(e)}

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

    def mark_private_messages_as_read(self, sender_user_id: int) -> Dict:
        """
        Mark private messages from a sender as read

        Args:
            sender_user_id: ID of the sender whose messages to mark as read

        Returns:
            Dict with 'success' (bool) and 'message' (str)
        """
        if not self.is_connected or not self.websocket:
            return {
                'success': False,
                'message': _('Not logged in')
            }

        try:
            async def _mark_messages_read():
                request = {
                    "type": "mark_messages_read",
                    "sender_user_id": sender_user_id
                }

                response = await self._send_and_wait(request, "mark_messages_read_response", timeout=5.0)

                if response and response.get('type') == 'mark_messages_read_response':
                    return {
                        'success': response.get('success', False),
                        'message': _('Messages marked as read') if response.get('success') else _('Failed to mark messages as read')
                    }
                return {
                    'success': False,
                    'message': _('No response from server')
                }

            return self._run_async(_mark_messages_read())

        except Exception as e:
            return {
                'success': False,
                'message': str(e)
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
                            request_id = message.get('_request_id')

                            # First, try to match by request ID (for concurrent requests)
                            if request_id and request_id in self._pending_requests:
                                event, expected_type = self._pending_requests[request_id]
                                self._cached_responses[request_id] = message
                                event.set()
                                continue  # Don't process as regular message

                            # Fallback: match by message type (for backwards compatibility)
                            for req_id, (event, expected_type) in list(self._pending_requests.items()):
                                if msg_type == expected_type:
                                    self._cached_responses[req_id] = message
                                    event.set()
                                    break  # Process only the first match

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
                            elif msg_type == 'voice_started':
                                # User started speaking
                                if self.on_voice_started:
                                    self.on_voice_started(message)
                            elif msg_type == 'voice_audio':
                                # Voice audio chunk received
                                if self.on_voice_audio:
                                    self.on_voice_audio(message)
                            elif msg_type == 'voice_stopped':
                                # User stopped speaking
                                if self.on_voice_stopped:
                                    self.on_voice_stopped(message)
                            elif msg_type == 'moderation_broadcast':
                                # Moderation broadcast received
                                print(f"[CLIENT] Moderation broadcast received: {message}")
                                print(f"[CLIENT] Callback exists: {self.on_broadcast_received is not None}")
                                if self.on_broadcast_received:
                                    print("[CLIENT] Calling on_broadcast_received callback...")
                                    self.on_broadcast_received(message)
                                    print("[CLIENT] Callback completed")
                                else:
                                    print("[CLIENT] WARNING: No broadcast callback registered!")
                            elif msg_type == 'package_pending':
                                # New package submitted (waiting room)
                                if self.on_package_pending:
                                    self.on_package_pending(message)
                            elif msg_type == 'package_approved':
                                # Package approved by moderation
                                if self.on_package_approved:
                                    self.on_package_approved(message)
                            elif msg_type == 'new_user_broadcast':
                                # New user registration broadcast
                                if self.on_new_user_broadcast:
                                    self.on_new_user_broadcast(message)

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

    def _get_auth_token(self) -> str:
        """Generate authentication token for HTTP API"""
        if not self.user_id or not self.username:
            return ""
        # Simple token format: base64(user_id:username)
        token_str = f"{self.user_id}:{self.username}"
        return base64.b64encode(token_str.encode()).decode()

    def _http_headers(self, include_content_type: bool = True) -> Dict:
        """Get HTTP headers with auth token

        Args:
            include_content_type: If False, omits Content-Type (needed for multipart uploads)
        """
        headers = {}
        if include_content_type:
            headers['Content-Type'] = 'application/json'
        token = self._get_auth_token()
        if token:
            headers['Authorization'] = f'Bearer {token}'
        return headers

    # Forum Methods (HTTP API)

    def create_forum_topic(self, title: str, content: str, category: str = 'general') -> Dict:
        """
        Create new forum topic

        Args:
            title: Topic title
            content: Topic content
            category: Topic category (default: 'general')

        Returns:
            Dict with success status and topic_id if successful
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/forum/topics",
                json={
                    'title': title,
                    'content': content,
                    'category': category
                },
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_forum_topics(self, category: Optional[str] = None, limit: int = 50) -> Dict:
        """
        Get forum topics

        Args:
            category: Filter by category (optional)
            limit: Maximum number of topics to return

        Returns:
            Dict with success status and list of topics
        """
        try:
            params = {'limit': limit}
            if category:
                params['category'] = category

            response = requests.get(
                f"{self.http_url}/api/forum/topics",
                params=params,
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_forum_topic(self, topic_id: int) -> Dict:
        """
        Get single forum topic details

        Args:
            topic_id: Topic ID

        Returns:
            Dict with success status and topic details
        """
        try:
            response = requests.get(
                f"{self.http_url}/api/forum/topics/{topic_id}",
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def add_forum_reply(self, topic_id: int, content: str) -> Dict:
        """
        Add reply to forum topic

        Args:
            topic_id: Topic ID
            content: Reply content

        Returns:
            Dict with success status and reply_id if successful
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/forum/topics/{topic_id}/replies",
                json={'content': content},
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_forum_replies(self, topic_id: int, limit: int = 100) -> Dict:
        """
        Get replies for forum topic

        Args:
            topic_id: Topic ID
            limit: Maximum number of replies to return

        Returns:
            Dict with success status and list of replies
        """
        try:
            response = requests.get(
                f"{self.http_url}/api/forum/topics/{topic_id}/replies",
                params={'limit': limit},
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def mark_topic_as_read(self, topic_id: int, reply_count: int) -> Dict:
        """
        Mark forum topic as read

        Args:
            topic_id: Topic ID
            reply_count: Current number of replies

        Returns:
            Dict with success status
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/forum/topics/{topic_id}/mark_read",
                json={'reply_count': reply_count},
                headers=self._http_headers(),
                timeout=5
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_forum_topic(self, topic_id: int) -> Dict:
        """
        Delete forum topic (author or admin only)

        Args:
            topic_id: Topic ID

        Returns:
            Dict with success status
        """
        try:
            response = requests.delete(
                f"{self.http_url}/api/forum/topics/{topic_id}",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def search_forum(self, query: str, category: Optional[str] = None, limit: int = 50) -> Dict:
        """
        Search forum topics

        Args:
            query: Search query
            category: Filter by category (optional)
            limit: Maximum number of results

        Returns:
            Dict with success status and list of topics
        """
        try:
            params = {'q': query, 'limit': limit}
            if category:
                params['category'] = category

            response = requests.get(
                f"{self.http_url}/api/forum/search",
                params=params,
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_my_forum_topics(self, limit: int = 50) -> Dict:
        """
        Get forum topics created by current user

        Args:
            limit: Maximum number of topics to return

        Returns:
            Dict with success status and list of topics
        """
        try:
            response = requests.get(
                f"{self.http_url}/api/forum/my_topics",
                params={'limit': limit},
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ==================== App Repository Methods ====================

    def get_apps(self, status: Optional[str] = None, category: Optional[str] = None,
                 limit: int = 100) -> Dict:
        """
        Get apps from repository

        Args:
            status: Filter by status ('approved', 'pending', or None for all)
            category: Filter by category (or None for all)
            limit: Maximum number of apps to return

        Returns:
            Dict with success status and list of apps
        """
        try:
            params = {'limit': limit}
            if status:
                params['status'] = status
            if category:
                params['category'] = category

            response = requests.get(
                f"{self.http_url}/api/repository/apps",
                params=params,
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_app_details(self, app_id: int) -> Dict:
        """
        Get details of a specific app

        Args:
            app_id: App ID

        Returns:
            Dict with success status and app details
        """
        try:
            response = requests.get(
                f"{self.http_url}/api/repository/apps/{app_id}",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def download_app(self, app_id: int) -> Dict:
        """
        Download app from repository

        Args:
            app_id: App ID

        Returns:
            Dict with success status, file_data, and filename
        """
        try:
            response = requests.get(
                f"{self.http_url}/api/download/{app_id}",
                headers=self._http_headers(),
                timeout=30  # Longer timeout for file download
            )

            if response.status_code == 200:
                # Get filename from Content-Disposition header
                content_disposition = response.headers.get('Content-Disposition', '')
                filename = 'app.zip'
                if 'filename=' in content_disposition:
                    filename = content_disposition.split('filename=')[1].strip('"')

                return {
                    "success": True,
                    "file_data": response.content,
                    "filename": filename
                }
            else:
                return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def upload_app(self, file_path: str, name: str, version: str = '',
                   description: str = '', category: str = 'tools') -> Dict:
        """
        Upload app to repository

        Args:
            file_path: Path to file to upload
            name: App name
            version: App version
            description: App description
            category: App category

        Returns:
            Dict with success status and app_id
        """
        try:
            import os

            if not os.path.exists(file_path):
                return {"success": False, "error": "File not found"}

            # Read file
            with open(file_path, 'rb') as f:
                file_data = f.read()

            filename = os.path.basename(file_path)

            # Prepare metadata as JSON
            metadata = {
                'name': name,
                'version': version,
                'description': description,
                'category': category
            }

            # Prepare multipart form data with metadata as JSON
            files = {
                'metadata': (None, json.dumps(metadata), 'application/json'),
                'file': (filename, file_data, 'application/octet-stream')
            }

            response = requests.post(
                f"{self.http_url}/api/repository/upload",
                files=files,
                headers=self._http_headers(include_content_type=False),
                timeout=60  # Longer timeout for upload
            )

            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def approve_app(self, app_id: int) -> Dict:
        """
        Approve app in repository (admin only)

        Args:
            app_id: App ID to approve

        Returns:
            Dict with success status
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/repository/apps/{app_id}/approve",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_app(self, app_id: int) -> Dict:
        """
        Delete app from repository (admin or uploader only)

        Args:
            app_id: App ID to delete

        Returns:
            Dict with success status
        """
        try:
            response = requests.delete(
                f"{self.http_url}/api/repository/apps/{app_id}",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def search_apps(self, query: str, category: Optional[str] = None) -> Dict:
        """
        Search apps in repository

        Args:
            query: Search query string
            category: Optional category filter

        Returns:
            Dict with success status and list of matching apps
        """
        try:
            params = {'q': query}
            if category:
                params['category'] = category

            response = requests.get(
                f"{self.http_url}/api/search",
                params=params,
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    # Role Management Methods

    def set_developer_role(self) -> Dict:
        """
        Set current user role to developer (auto-detection from source code)

        Returns:
            Dict with success status
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/users/set_developer",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_user_role(self) -> Dict:
        """
        Get current user's role

        Returns:
            Dict with role information
        """
        try:
            response = requests.get(
                f"{self.http_url}/api/users/role",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def promote_to_moderator(self, username: str, title: str = "Moderator") -> Dict:
        """
        Promote user to moderator (developer only)

        Args:
            username: Username to promote
            title: Custom moderator title

        Returns:
            Dict with success status
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/moderation/promote",
                headers=self._http_headers(),
                json={"username": username, "title": title},
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def demote_from_moderator(self, username: str) -> Dict:
        """
        Demote moderator to regular user (developer only)

        Args:
            username: Username to demote

        Returns:
            Dict with success status
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/moderation/demote",
                headers=self._http_headers(),
                json={"username": username},
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_all_moderators(self) -> Dict:
        """
        Get list of all moderators

        Returns:
            Dict with moderators list
        """
        try:
            response = requests.get(
                f"{self.http_url}/api/moderation/moderators",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    # Ban System Methods

    def ban_user_from_room(self, room_id: int, user_id: int, ban_type: str = 'permanent',
                          duration_hours: int = None, reason: str = "", ip_address: str = None) -> Dict:
        """
        Ban user from room

        Args:
            room_id: Room ID
            user_id: User ID to ban
            ban_type: 'temporary', 'permanent', or 'ip'
            duration_hours: Duration in hours for temporary bans
            reason: Ban reason
            ip_address: IP address for IP bans

        Returns:
            Dict with success status
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/moderation/ban/room",
                headers=self._http_headers(),
                json={
                    "room_id": room_id,
                    "user_id": user_id,
                    "ban_type": ban_type,
                    "duration_hours": duration_hours,
                    "reason": reason,
                    "ip_address": ip_address
                },
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def ban_user_globally(self, user_id: int, ban_type: str = 'permanent',
                         duration_hours: int = None, reason: str = "", ip_address: str = None) -> Dict:
        """
        Ban user globally from TCE Community

        Args:
            user_id: User ID to ban
            ban_type: 'temporary', 'permanent', or 'ip'
            duration_hours: Duration in hours for temporary bans
            reason: Ban reason
            ip_address: IP address for IP bans

        Returns:
            Dict with success status
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/moderation/ban/global",
                headers=self._http_headers(),
                json={
                    "user_id": user_id,
                    "ban_type": ban_type,
                    "duration_hours": duration_hours,
                    "reason": reason,
                    "ip_address": ip_address
                },
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def ban_user_hard(self, user_id: int, reason: str, ip_address: str = None, hardware_id: str = None) -> Dict:
        """
        Hard ban user - most restrictive ban
        Bans user, IP, and hardware ID permanently
        Only developers can issue hard bans

        Args:
            user_id: User ID to ban
            reason: Ban reason (required)
            ip_address: IP address to ban
            hardware_id: Hardware ID to ban

        Returns:
            Dict with success status
        """
        if not self.websocket or not self.is_connected:
            return {"success": False, "error": "Not connected"}

        try:
            async def _hard_ban():
                message = {
                    "type": "hard_ban_user",
                    "user_id": user_id,
                    "reason": reason,
                    "ip_address": ip_address,
                    "hardware_id": hardware_id
                }

                response = await self._send_and_wait(message, "hard_ban_response", timeout=10)
                return response if response else {"success": False, "error": "Timeout"}

            return self._run_async(_hard_ban())
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_user(self, user_id: int) -> Dict:
        """
        Delete user permanently (moderator/developer only)
        Removes user and all their data from the system

        Args:
            user_id: User ID to delete

        Returns:
            Dict with success status
        """
        if not self.websocket or not self.is_connected:
            return {"success": False, "error": "Not connected"}

        try:
            async def _delete_user():
                message = {
                    "type": "delete_user",
                    "user_id": user_id
                }

                response = await self._send_and_wait(message, "delete_user_response", timeout=10)
                return response if response else {"success": False, "error": "Timeout"}

            return self._run_async(_delete_user())
        except Exception as e:
            return {"success": False, "error": str(e)}

    def ban_user_from_forum(self, user_id: int, ban_type: str = 'permanent',
                           duration_hours: int = None, reason: str = "") -> Dict:
        """
        Ban user from forum

        Args:
            user_id: User ID to ban
            ban_type: 'temporary', 'permanent'
            duration_hours: Duration in hours for temporary bans
            reason: Ban reason

        Returns:
            Dict with success status
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/moderation/ban/forum",
                headers=self._http_headers(),
                json={
                    "user_id": user_id,
                    "ban_type": ban_type,
                    "duration_hours": duration_hours,
                    "reason": reason
                },
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def check_ban_status(self, user_id: int) -> Dict:
        """
        Check user ban status

        Args:
            user_id: User ID to check

        Returns:
            Dict with ban status
        """
        try:
            response = requests.get(
                f"{self.http_url}/api/moderation/ban/check/{user_id}",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def unban_user_globally(self, user_id: int) -> Dict:
        """
        Unban user globally from TCE Community

        Args:
            user_id: User ID to unban

        Returns:
            Dict with success status
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/moderation/unban/global",
                headers=self._http_headers(),
                json={"user_id": user_id},
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def unban_user_from_forum(self, user_id: int) -> Dict:
        """
        Unban user from forum

        Args:
            user_id: User ID to unban

        Returns:
            Dict with success status
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/moderation/unban/forum",
                headers=self._http_headers(),
                json={"user_id": user_id},
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def unban_user_from_room_by_id(self, room_id: int, user_id: int) -> Dict:
        """
        Unban user from room by user ID

        Args:
            room_id: Room ID
            user_id: User ID to unban

        Returns:
            Dict with success status
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/moderation/unban/room",
                headers=self._http_headers(),
                json={"room_id": room_id, "user_id": user_id},
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    # App Repository Methods (additional)

    def reject_app(self, app_id: int) -> Dict:
        """
        Reject app in repository (moderator only)

        Args:
            app_id: App ID to reject

        Returns:
            Dict with success status
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/repository/apps/{app_id}/reject",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_pending_apps(self) -> Dict:
        """
        Get pending apps awaiting approval

        Returns:
            Dict with pending apps list
        """
        try:
            response = requests.get(
                f"{self.http_url}/api/repository/apps/pending",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    # Forum Moderation Methods

    def lock_forum_topic(self, topic_id: int) -> Dict:
        """
        Lock forum topic (moderator only)

        Args:
            topic_id: Topic ID to lock

        Returns:
            Dict with success status
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/forum/topics/{topic_id}/lock",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def unlock_forum_topic(self, topic_id: int) -> Dict:
        """
        Unlock forum topic (moderator only)

        Args:
            topic_id: Topic ID to unlock

        Returns:
            Dict with success status
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/forum/topics/{topic_id}/unlock",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def pin_forum_topic(self, topic_id: int) -> Dict:
        """
        Pin forum topic (moderator only)

        Args:
            topic_id: Topic ID to pin

        Returns:
            Dict with success status
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/forum/topics/{topic_id}/pin",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def unpin_forum_topic(self, topic_id: int) -> Dict:
        """
        Unpin forum topic (moderator only)

        Args:
            topic_id: Topic ID to unpin

        Returns:
            Dict with success status
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/forum/topics/{topic_id}/unpin",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_forum_reply(self, reply_id: int) -> Dict:
        """
        Delete forum reply (moderator only)

        Args:
            reply_id: Reply ID to delete

        Returns:
            Dict with success status
        """
        try:
            response = requests.delete(
                f"{self.http_url}/api/forum/replies/{reply_id}",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def edit_forum_reply(self, reply_id: int, new_content: str) -> Dict:
        """
        Edit forum reply (moderator only)

        Args:
            reply_id: Reply ID to edit
            new_content: New content for the reply

        Returns:
            Dict with success status
        """
        try:
            response = requests.put(
                f"{self.http_url}/api/forum/replies/{reply_id}",
                headers=self._http_headers(),
                json={"content": new_content},
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def move_forum_topic(self, topic_id: int, category: str) -> Dict:
        """
        Move forum topic to different category (moderator only)

        Args:
            topic_id: Topic ID to move
            category: New category

        Returns:
            Dict with success status
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/forum/topics/{topic_id}/move",
                headers=self._http_headers(),
                json={"category": category},
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    # Room Moderation Methods

    def kick_user_from_room(self, room_id: int, username: str) -> Dict:
        """
        Kick user from room (moderator/room creator only)

        Args:
            room_id: Room ID
            username: Username to kick

        Returns:
            Dict with success status
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/rooms/{room_id}/kick",
                headers=self._http_headers(),
                json={"username": username},
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def ban_user_from_room_by_username(self, room_id: int, username: str, reason: str = "") -> Dict:
        """
        Ban user from room by username (room creator only)

        Args:
            room_id: Room ID
            username: Username to ban
            reason: Ban reason (optional)

        Returns:
            Dict with success status
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/rooms/{room_id}/ban",
                headers=self._http_headers(),
                json={"username": username, "reason": reason},
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def unban_user_from_room(self, room_id: int, username: str) -> Dict:
        """
        Unban user from room (moderator/room creator only)

        Args:
            room_id: Room ID
            username: Username to unban

        Returns:
            Dict with success status
        """
        try:
            response = requests.post(
                f"{self.http_url}/api/rooms/{room_id}/unban",
                headers=self._http_headers(),
                json={"username": username},
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_room_message(self, message_id: int) -> Dict:
        """
        Delete room message (moderator only)

        Args:
            message_id: Message ID to delete

        Returns:
            Dict with success status
        """
        try:
            response = requests.delete(
                f"{self.http_url}/api/rooms/messages/{message_id}",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_chat_room_by_moderator(self, room_id: int) -> Dict:
        """
        Delete chat room (moderator only)

        Args:
            room_id: Room ID to delete

        Returns:
            Dict with success status
        """
        try:
            response = requests.delete(
                f"{self.http_url}/api/rooms/{room_id}/moderate",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_room_by_moderator(self, room_id: int) -> Dict:
        """
        Delete chat room (moderator only) - Alias for delete_chat_room_by_moderator

        Args:
            room_id: Room ID to delete

        Returns:
            Dict with success status
        """
        return self.delete_chat_room_by_moderator(room_id)
