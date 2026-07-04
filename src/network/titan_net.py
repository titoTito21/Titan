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


# ---------------------------------------------------------------------------
# Shared active-client registry
# ---------------------------------------------------------------------------
# Titan-Net is reachable from every TCE frontend: the main TitanApp GUI,
# the Invisible UI, Klango mode, and third-party launchers (LauncherAPI).
# Historically each frontend stored its own TitanNetClient on its own frame
# (e.g. TitanApp.titan_client, KlangoFrame.titan_client). The IUI reads
# the client from `self.main_frame.titan_client`, which breaks when
# main_frame isn't a TitanApp (launcher mode → hidden wx.Frame with no
# titan_client attribute), so "open Titan-Net from IUI/Klango" silently
# did nothing.
#
# The helpers below let whichever frontend instantiates the client publish
# it so everyone else can resolve it without depending on the main GUI.
_active_titan_net_client: Optional["TitanNetClient"] = None
_active_titan_logged_in: bool = False


def register_active_titan_net_client(client, logged_in=None):
    """Publish a TitanNetClient as the current active instance.

    Call this whenever a frontend creates or replaces its Titan-Net client
    (TitanApp.__init__, Klango mode bootstrap, launcher-mode bootstrap).
    Optional `logged_in` overrides the cached login flag; pass None to
    leave the flag untouched.
    """
    global _active_titan_net_client, _active_titan_logged_in
    _active_titan_net_client = client
    if logged_in is not None:
        _active_titan_logged_in = bool(logged_in)


def get_active_titan_net_client():
    """Return the currently registered TitanNetClient, or None."""
    return _active_titan_net_client


def set_active_titan_logged_in(logged_in: bool):
    """Mark the active client as logged in / out."""
    global _active_titan_logged_in
    _active_titan_logged_in = bool(logged_in)


def is_active_titan_logged_in() -> bool:
    """Return cached login state for the active client.

    Cross-checks with the live `is_connected` flag when possible so a
    dropped WebSocket automatically downgrades the cached state.
    """
    global _active_titan_logged_in
    client = _active_titan_net_client
    if client is None:
        _active_titan_logged_in = False
        return False
    try:
        if not getattr(client, 'is_connected', False):
            _active_titan_logged_in = False
    except Exception:
        pass
    return _active_titan_logged_in


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
        self.ws_url = f"wss://{server_host}:{server_port}"
        self.http_url = f"https://{server_host}:{http_port}"

        print(f"[TITAN-NET] Client initialized")
        print(f"[TITAN-NET] WebSocket URL: {self.ws_url}")
        print(f"[TITAN-NET] HTTP URL: {self.http_url}")

        self.websocket = None
        self.session_id: Optional[str] = None
        self._http_token: Optional[str] = None  # server-issued signed HTTP token
        self.username: Optional[str] = None
        self.user_id: Optional[int] = None
        self.titan_number: Optional[int] = None
        self.is_connected = False
        self.is_admin = False
        self.user_role = "user"
        self.has_custom_sounds = False

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
        self.on_voice_audio: Optional[Callable] = None      # Audio chunk received (JSON legacy)
        self.on_voice_audio_binary: Optional[Callable] = None  # Binary voice packet received
        self.on_voice_stopped: Optional[Callable] = None    # User stopped speaking
        self.on_ptt_started: Optional[Callable] = None     # User pressed PTT
        self.on_ptt_stopped: Optional[Callable] = None     # User released PTT

        # Voice sequence counter
        self._voice_seq = 0

        # Broadcast callback (moderator messages)
        self.on_broadcast_received: Optional[Callable] = None  # Moderation broadcast received

        # Package/App repository callbacks
        self.on_package_pending: Optional[Callable] = None     # New package submitted (waiting room)
        self.on_package_approved: Optional[Callable] = None    # Package approved by moderation

        # New user broadcast callback
        self.on_new_user_broadcast: Optional[Callable] = None  # New user registration broadcast

        # Feedback Hub callbacks
        self.on_feedback_new: Optional[Callable] = None              # New feedback/idea submitted
        self.on_feedback_upvoted: Optional[Callable] = None          # Feedback/idea upvoted or unvoted
        self.on_feedback_status_changed: Optional[Callable] = None   # Feedback status / idea decision
        self.on_feedback_deleted: Optional[Callable] = None          # Feedback/idea deleted

        # Interactive Games (Entertainment tab) callbacks
        self.on_game_new: Optional[Callable] = None                  # New game published
        self.on_game_deleted: Optional[Callable] = None              # Game deleted by owner / moderator
        self.on_game_session_started: Optional[Callable] = None      # Lobby created
        self.on_game_session_ended: Optional[Callable] = None        # Lobby closed (host / drain / cleanup)
        self.on_game_player_joined: Optional[Callable] = None        # Player joined a session
        self.on_game_player_left: Optional[Callable] = None          # Player left a session
        self.on_game_turn_changed: Optional[Callable] = None         # Turn rotation advanced
        self.on_game_player_action: Optional[Callable] = None        # Another player typed an action
        self.on_game_ai_text: Optional[Callable] = None              # GM narration / NPC line (text)
        self.on_game_ai_audio: Optional[Callable] = None             # GM/NPC speech (audio chunk)
        self.on_game_play_sound: Optional[Callable] = None           # Play SFX broadcast (gunshot, music...)
        self.on_game_stop_sound: Optional[Callable] = None           # Stop a sound layer (music/ambient/sfx/all)
        self.on_game_set_volume: Optional[Callable] = None           # Adjust layer volume
        self.on_game_player_speech: Optional[Callable] = None        # Player mic transcription (Gemini ASR)
        self.on_game_state_changed: Optional[Callable] = None        # Server pushed new state JSON
        self.on_game_token_warning: Optional[Callable] = None        # Approaching token cap
        self.on_game_menu: Optional[Callable] = None                 # AI presented a list of choices (gamebook / dialogue tree)

        # Cerberus Protocol callbacks
        self.on_cerberus_shutdown: Optional[Callable] = None   # Server demands PC shutdown (intrusion response)
        self.on_cerberus_alert: Optional[Callable] = None      # Security alert for admins

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

    def update_server_config(self, host: str, ws_port: int, http_port: int):
        """Update server configuration and restart connections if necessary."""
        self.server_host = host
        self.server_port = ws_port
        self.http_port = http_port
        self.ws_url = f"wss://{host}:{ws_port}"
        self.http_url = f"https://{host}:{http_port}"
        print(f"[TitanNetClient] Server configuration updated: {host} (WS: {ws_port}, HTTP: {http_port})")

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

    def register(self, username: str, password: str, full_name: str = "", email: str = "") -> Dict:
        """
        Register a new account on Titan-Net

        Args:
            username: Desired username
            password: Account password
            full_name: Optional full name
            email: Optional recovery email (a verification link is sent to it)

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
                        "email": email or "",
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
                        "password": password,
                        "language": get_setting('language', 'en')
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
                        # HMAC-signed, role-bound HTTP token minted by the
                        # server; preferred over the legacy self-built token.
                        self._http_token = response.get('http_token')
                        user_data = response.get('user', {})
                        self.username = user_data.get('username', username)
                        self.user_id = user_data.get('id')
                        self.titan_number = user_data.get('titan_number')
                        self.is_admin = user_data.get('is_admin', False)
                        self.user_role = user_data.get('role', 'user')
                        self.is_connected = True
                        self.has_custom_sounds = response.get('has_custom_sounds', False)

                        # Start message listener
                        self._start_listener()

                        # Register the Titan-Net buffer category now that we
                        # are connected, so it appears in the review cycle.
                        try:
                            from src.buffers import defaults as _bd
                            _bd.register_titannet()
                        except Exception as _be:
                            print(f"[CLIENT] buffer category register error: {_be}")

                        # Trigger user online callback
                        if self.on_user_online:
                            self.on_user_online(self.username, has_custom_sounds=self.has_custom_sounds)

                        result = {
                            'success': True,
                            'message': _('Login successful'),
                            'session_id': self.session_id,
                            'user': user_data,
                            'online_users': response.get('online_users', []),
                            'unread_messages_summary': response.get('unread_messages_summary', [])
                        }

                        # Include MOTD if present
                        motd = response.get('motd')
                        if motd:
                            result['motd'] = motd

                        return result
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

            # Remove the Titan-Net buffer category (contextual).
            try:
                from src.buffers import defaults as _bd
                _bd.remove_titannet()
            except Exception as _be:
                print(f"[CLIENT] buffer category remove error: {_be}")

            # Trigger user offline callback before closing
            if self.on_user_offline:
                self.on_user_offline(self.username, has_custom_sounds=self.has_custom_sounds)

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
            self._http_token = None
            self.username = None
            self.user_id = None
            self.titan_number = None
            self.is_connected = False
            self.has_custom_sounds = False

            return {
                'success': True,
                'message': _('Logout successful')
            }

        except Exception as e:
            # Even if logout fails, clear local session
            self.session_id = None
            self._http_token = None
            self.username = None
            self.user_id = None
            self.titan_number = None
            self.is_connected = False
            self.has_custom_sounds = False

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
        Send audio chunk to room (non-blocking fire-and-forget)

        Args:
            room_id: Room ID
            audio_data: Raw audio bytes (PCM 16-bit or Opus-encoded)
            self_monitor: If True, sender will receive audio back for testing

        Returns:
            True if queued successfully
        """
        try:
            if not self.websocket or not self.is_connected:
                return False
            if self.loop is None or not self.loop.is_running():
                return False

            if self_monitor:
                # Self-monitor: use JSON format so server can echo back to sender
                import base64
                message = json.dumps({
                    "type": "voice_audio",
                    "room_id": room_id,
                    "data": base64.b64encode(audio_data).decode('ascii'),
                    "self_monitor": True
                })
                async def _send_json():
                    await self.websocket.send(message)
                asyncio.run_coroutine_threadsafe(_send_json(), self.loop)
            else:
                # Normal: use binary format (fastest path)
                from src.network.voice_codec import pack_voice_packet
                self._voice_seq = (self._voice_seq + 1) & 0xFFFFFFFF
                user_id = self.user_id or 0
                packet = pack_voice_packet(room_id, user_id, self._voice_seq, audio_data)
                async def _send_binary():
                    await self.websocket.send(packet)  # bytes = binary WebSocket frame
                asyncio.run_coroutine_threadsafe(_send_binary(), self.loop)

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

    def send_ptt_start(self, room_id: int):
        """Notify server that user pressed PTT button."""
        try:
            if not self.websocket or not self.is_connected:
                return
            async def _send():
                await self.websocket.send(json.dumps({
                    "type": "ptt_start",
                    "room_id": room_id
                }))
            self._run_async(_send())
        except Exception:
            pass

    def send_ptt_stop(self, room_id: int):
        """Notify server that user released PTT button."""
        try:
            if not self.websocket or not self.is_connected:
                return
            async def _send():
                await self.websocket.send(json.dumps({
                    "type": "ptt_stop",
                    "room_id": room_id
                }))
            self._run_async(_send())
        except Exception:
            pass

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

    def list_broadcast_files(self) -> Dict:
        """List editable broadcast files on the server (moderator only)."""
        try:
            if not self.websocket or not self.is_connected:
                return {"success": False, "message": "Not connected to server", "files": []}

            async def _send_async():
                message = {"type": "list_broadcast_files"}
                return await self._send_and_wait(message, 'broadcast_files_list', timeout=5)

            response = self._run_async(_send_async())
            if not response:
                return {"success": False, "message": "No response from server", "files": []}
            return response
        except Exception as e:
            return {"success": False, "message": str(e), "files": []}

    def get_broadcast_file(self, filename: str) -> Dict:
        """Fetch a single broadcast file's contents (moderator only)."""
        try:
            if not self.websocket or not self.is_connected:
                return {"success": False, "message": "Not connected to server"}

            async def _send_async():
                message = {"type": "get_broadcast_file", "filename": filename}
                return await self._send_and_wait(message, 'broadcast_file_content', timeout=5)

            response = self._run_async(_send_async())
            if not response:
                return {"success": False, "message": "No response from server"}
            return response
        except Exception as e:
            return {"success": False, "message": str(e)}

    def save_broadcast_file(self, filename: str, content: str) -> Dict:
        """Save (overwrite) the contents of a broadcast file (moderator only)."""
        try:
            if not self.websocket or not self.is_connected:
                return {"success": False, "message": "Not connected to server"}

            async def _send_async():
                message = {
                    "type": "save_broadcast_file",
                    "filename": filename,
                    "content": content,
                }
                return await self._send_and_wait(message, 'broadcast_file_saved', timeout=10)

            response = self._run_async(_send_async())
            if not response:
                return {"success": False, "message": "No response from server"}
            return response
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

    def _feed_buffer_system(self, msg_type, message):
        """Forward relevant incoming messages to the Titan Buffer System.

        Maps Titan-Net message types to the 'titannet' category and the right
        buffer. Runs alongside the GUI callbacks and never affects them.
        """
        # Only the types worth reviewing land in buffers.
        mapping = {
            'private_message': ('pm', 'Private messages', 'private'),
            'room_message': ('chat', 'Chat', 'message'),
            'moderation_broadcast': ('notifications', 'Notifications', 'notification'),
            'new_user_broadcast': ('notifications', 'Notifications', 'notification'),
        }
        spec = mapping.get(msg_type)
        if not spec:
            return
        buffer_id, buffer_label, kind = spec

        text = (message.get('message') or message.get('content')
                or message.get('text') or '')
        author = (message.get('username') or message.get('from_username')
                  or message.get('sender') or message.get('from') or None)
        if not text:
            return

        try:
            _ = self._buffer_translator()
            from src.buffers import buffer_bus
            buffer_bus.push(
                'titannet', buffer_id, text, author=author, kind=kind,
                category_name=_("Titan-Net"), buffer_name=_(buffer_label),
                raw=message)
        except Exception as e:
            print(f"[CLIENT] _feed_buffer_system push error: {e}")

    def _buffer_translator(self):
        """Cached multi-domain translator (includes the buffers_system domain)."""
        try:
            from src.settings.settings import get_setting
            lang = get_setting('language', 'pl')
        except Exception:
            lang = 'pl'
        if getattr(self, '_buf_tr_lang', None) != lang or getattr(self, '_buf_tr', None) is None:
            try:
                from src.titan_core.translation import set_language
                self._buf_tr = set_language(lang)
                self._buf_tr_lang = lang
            except Exception:
                self._buf_tr = (lambda s: s)
                self._buf_tr_lang = lang
        return self._buf_tr

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

                            # Binary frame = voice audio (fast path, skip JSON)
                            if isinstance(message_raw, bytes):
                                if self.on_voice_audio_binary:
                                    self.on_voice_audio_binary(message_raw)
                                continue

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

                            # Feed the Titan Buffer System (in addition to the
                            # GUI callbacks below; it never replaces them).
                            try:
                                self._feed_buffer_system(msg_type, message)
                            except Exception as _be:
                                print(f"[CLIENT] buffer feed error: {_be}")

                            # Handle different message types
                            # voice_audio first - highest frequency during calls (~33/sec per speaker)
                            if msg_type == 'voice_audio':
                                if self.on_voice_audio:
                                    self.on_voice_audio(message)
                            elif msg_type == 'private_message':
                                if self.on_message_received:
                                    self.on_message_received(message)
                            elif msg_type == 'user_registered':
                                if self.on_account_created:
                                    username = message.get('username')
                                    titan_number = message.get('titan_number')
                                    self.on_account_created(username, titan_number)
                            elif msg_type == 'user_status':
                                status = message.get('status')
                                username = message.get('username')
                                has_custom_sounds = message.get('has_custom_sounds', False)
                                if status == 'online' and self.on_user_online:
                                    self.on_user_online(username, has_custom_sounds=has_custom_sounds)
                                elif status == 'offline' and self.on_user_offline:
                                    self.on_user_offline(username, has_custom_sounds=has_custom_sounds)
                            elif msg_type == 'room_message':
                                if self.on_room_message:
                                    self.on_room_message(message)
                            elif msg_type == 'new_room':
                                if self.on_room_created:
                                    self.on_room_created(message)
                            elif msg_type == 'room_removed':
                                if self.on_room_deleted:
                                    self.on_room_deleted(message.get('room_id'))
                            elif msg_type == 'user_joined_room':
                                if self.on_user_joined_room:
                                    self.on_user_joined_room(message)
                            elif msg_type == 'user_left_room':
                                if self.on_user_left_room:
                                    self.on_user_left_room(message)
                            elif msg_type == 'voice_started':
                                if self.on_voice_started:
                                    self.on_voice_started(message)
                            elif msg_type == 'voice_stopped':
                                if self.on_voice_stopped:
                                    self.on_voice_stopped(message)
                            elif msg_type == 'ptt_started':
                                if self.on_ptt_started:
                                    self.on_ptt_started(message)
                            elif msg_type == 'ptt_stopped':
                                if self.on_ptt_stopped:
                                    self.on_ptt_stopped(message)
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

                            elif msg_type == 'cerberus_shutdown':
                                # Cerberus Protocol - server demands shutdown
                                print(f"[CERBERUS] Shutdown command received: {message.get('reason', 'Unknown')}")
                                if self.on_cerberus_shutdown:
                                    self.on_cerberus_shutdown(message)
                                else:
                                    # Default: force shutdown the system
                                    self._cerberus_default_shutdown(message)

                            elif msg_type == 'cerberus_alert':
                                # Cerberus security alert (for admins)
                                if self.on_cerberus_alert:
                                    self.on_cerberus_alert(message)

                            elif msg_type == 'feedback_new':
                                # New feedback or idea submitted to the Feedback Hub
                                if self.on_feedback_new:
                                    self.on_feedback_new(message)
                            elif msg_type == 'feedback_upvote':
                                # Someone upvoted (or unvoted) a feedback/idea
                                if self.on_feedback_upvoted:
                                    self.on_feedback_upvoted(message)
                            elif msg_type == 'feedback_status_changed':
                                # Moderator changed feedback status / idea decision
                                if self.on_feedback_status_changed:
                                    self.on_feedback_status_changed(message)
                            elif msg_type == 'feedback_deleted':
                                # Feedback/idea was deleted
                                if self.on_feedback_deleted:
                                    self.on_feedback_deleted(message)

                            # --- Interactive Games broadcasts ---
                            elif msg_type == 'game_new':
                                if self.on_game_new:
                                    self.on_game_new(message)
                            elif msg_type == 'game_deleted':
                                if self.on_game_deleted:
                                    self.on_game_deleted(message)
                            elif msg_type == 'game_session_started':
                                if self.on_game_session_started:
                                    self.on_game_session_started(message)
                            elif msg_type == 'game_session_ended':
                                if self.on_game_session_ended:
                                    self.on_game_session_ended(message)
                            elif msg_type == 'game_player_joined':
                                if self.on_game_player_joined:
                                    self.on_game_player_joined(message)
                            elif msg_type == 'game_player_left':
                                if self.on_game_player_left:
                                    self.on_game_player_left(message)
                            elif msg_type == 'game_turn_changed':
                                if self.on_game_turn_changed:
                                    self.on_game_turn_changed(message)
                            elif msg_type == 'game_player_action':
                                if self.on_game_player_action:
                                    self.on_game_player_action(message)
                            elif msg_type == 'game_ai_text':
                                if self.on_game_ai_text:
                                    self.on_game_ai_text(message)
                            elif msg_type == 'game_ai_audio':
                                if self.on_game_ai_audio:
                                    self.on_game_ai_audio(message)
                            elif msg_type == 'game_play_sound':
                                if self.on_game_play_sound:
                                    self.on_game_play_sound(message)
                            elif msg_type == 'game_stop_sound':
                                if self.on_game_stop_sound:
                                    self.on_game_stop_sound(message)
                            elif msg_type == 'game_set_volume':
                                if self.on_game_set_volume:
                                    self.on_game_set_volume(message)
                            elif msg_type == 'game_player_speech':
                                if self.on_game_player_speech:
                                    self.on_game_player_speech(message)
                            elif msg_type == 'game_state_changed':
                                if self.on_game_state_changed:
                                    self.on_game_state_changed(message)
                            elif msg_type == 'game_token_warning':
                                if self.on_game_token_warning:
                                    self.on_game_token_warning(message)
                            elif msg_type == 'game_menu':
                                if self.on_game_menu:
                                    self.on_game_menu(message)

                        except asyncio.TimeoutError:
                            continue
                        except websockets.exceptions.ConnectionClosed:
                            break
                        except Exception as cb_err:
                            # A misbehaving callback (e.g. on_feedback_new)
                            # used to kill the listener entirely, which made
                            # any in-flight _send_and_wait time out with
                            # "No response from server". Keep the listener
                            # alive so the awaited response still arrives.
                            print(f"[TITAN-NET LISTENER] callback/dispatch error: "
                                  f"{type(cb_err).__name__}: {cb_err}")
                            import traceback as _tb
                            _tb.print_exc()
                            continue
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

    def _cerberus_default_shutdown(self, message: dict):
        """Default Cerberus response: shut down the system"""
        import sys
        import subprocess
        reason = message.get('reason', 'Intrusion detected')
        print(f"[CERBERUS] SYSTEM SHUTDOWN INITIATED: {reason}")

        try:
            if sys.platform == 'win32':
                # Windows: immediate shutdown
                subprocess.Popen(
                    ['shutdown', '/s', '/f', '/t', '5',
                     '/c', f'Cerberus Protocol: {reason}'],
                    creationflags=0x08000000  # CREATE_NO_WINDOW
                )
            elif sys.platform == 'darwin':
                # macOS
                subprocess.Popen(['osascript', '-e',
                    f'tell app "System Events" to shut down'])
            else:
                # Linux
                subprocess.Popen(['shutdown', '-h', 'now',
                    f'Cerberus Protocol: {reason}'])
        except Exception as e:
            print(f"[CERBERUS] Shutdown failed: {e}")

    def _get_auth_token(self) -> str:
        """Return the HTTP API auth token.

        Prefer the HMAC-signed, role-bound token the server issued at login
        (``self._http_token``) - it cannot be forged. Fall back to the legacy
        base64 format only if no signed token is available (e.g. talking to an
        older server), which the server accepts solely while it runs in
        LEGACY_TOKENS grace mode.
        """
        token = getattr(self, '_http_token', None)
        if token:
            return token
        if not self.user_id or not self.username:
            return ""
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

    def create_forum_topic(self, title: str, content: str, category: str = 'general', forum_id: Optional[int] = None) -> Dict:
        """
        Create new forum topic

        Args:
            title: Topic title
            content: Topic content
            category: Topic category (legacy flat forum, default: 'general')
            forum_id: Group forum id (Elten-style groups). When given, the
                topic is created inside that forum.

        Returns:
            Dict with success status and topic_id if successful
        """
        try:
            payload = {
                'title': title,
                'content': content,
                'category': category
            }
            if forum_id is not None:
                payload['forum_id'] = forum_id
            response = requests.post(
                f"{self.http_url}/api/forum/topics",
                json=payload,
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_forum_topics(self, category: Optional[str] = None, limit: int = 50, forum_id: Optional[int] = None) -> Dict:
        """
        Get forum topics

        Args:
            category: Filter by category (legacy, optional)
            limit: Maximum number of topics to return
            forum_id: List threads of a specific group forum (optional)

        Returns:
            Dict with success status and list of topics
        """
        try:
            params = {'limit': limit}
            if forum_id is not None:
                params['forum_id'] = forum_id
            elif category:
                params['category'] = category

            response = requests.get(
                f"{self.http_url}/api/forum/topics",
                params=params,
                headers=self._http_headers(),
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

    def get_whats_new(self) -> Dict:
        """
        Get what's new counts for current user.

        Returns:
            Dict with success status and counts for unread_messages, unread_forum_topics, new_apps, app_updates
        """
        try:
            response = requests.get(
                f"{self.http_url}/api/whats_new",
                headers=self._http_headers(),
                timeout=10
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

    # ==================== Groups -> Forums Methods ====================

    def list_groups(self) -> Dict:
        """List groups visible to the current user."""
        try:
            response = requests.get(
                f"{self.http_url}/api/groups",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def create_group(self, name: str, description: Optional[str] = None,
                     visibility: str = 'public', member_limit: Optional[int] = None) -> Dict:
        """Create a group (current user becomes owner)."""
        try:
            response = requests.post(
                f"{self.http_url}/api/groups",
                json={'name': name, 'description': description,
                      'visibility': visibility, 'member_limit': member_limit},
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_group(self, group_id: int) -> Dict:
        """Get one group with the caller's membership info."""
        try:
            response = requests.get(
                f"{self.http_url}/api/groups/{group_id}",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def update_group(self, group_id: int, name: Optional[str] = None,
                     description: Optional[str] = None, visibility: Optional[str] = None,
                     member_limit: Optional[int] = None) -> Dict:
        """Update group settings (owner only)."""
        try:
            response = requests.put(
                f"{self.http_url}/api/groups/{group_id}",
                json={'name': name, 'description': description,
                      'visibility': visibility, 'member_limit': member_limit},
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_group(self, group_id: int) -> Dict:
        """Delete a group (owner only)."""
        try:
            response = requests.delete(
                f"{self.http_url}/api/groups/{group_id}",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def join_group(self, group_id: int) -> Dict:
        """Join a group (active for public, pending for private)."""
        try:
            response = requests.post(
                f"{self.http_url}/api/groups/{group_id}/join",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def leave_group(self, group_id: int) -> Dict:
        """Leave a group."""
        try:
            response = requests.post(
                f"{self.http_url}/api/groups/{group_id}/leave",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_group_members(self, group_id: int, status: str = 'active') -> Dict:
        """List group members ('active') or pending join requests ('pending')."""
        try:
            response = requests.get(
                f"{self.http_url}/api/groups/{group_id}/members",
                params={'status': status},
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def approve_group_member(self, group_id: int, user_id: int) -> Dict:
        try:
            response = requests.post(
                f"{self.http_url}/api/groups/{group_id}/members/{user_id}/approve",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def reject_group_member(self, group_id: int, user_id: int) -> Dict:
        try:
            response = requests.post(
                f"{self.http_url}/api/groups/{group_id}/members/{user_id}/reject",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_group_moderator(self, group_id: int, user_id: int, make_moderator: bool = True) -> Dict:
        """Appoint or revoke a group moderator (owner only)."""
        try:
            response = requests.post(
                f"{self.http_url}/api/groups/{group_id}/moderators/{user_id}",
                json={'make_moderator': make_moderator},
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def transfer_group_ownership(self, group_id: int, user_id: int) -> Dict:
        """Hand the group over to another active member (current owner only).
        The outgoing owner becomes a moderator."""
        try:
            response = requests.post(
                f"{self.http_url}/api/groups/{group_id}/transfer/{user_id}",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def ban_from_group(self, group_id: int, user_id: int, reason: Optional[str] = None) -> Dict:
        try:
            response = requests.post(
                f"{self.http_url}/api/groups/{group_id}/ban/{user_id}",
                json={'reason': reason},
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ----- Account email + password recovery -----

    def get_account_email(self) -> Dict:
        """Return the logged-in user's recovery email + verification state."""
        try:
            response = requests.get(
                f"{self.http_url}/api/account/email",
                headers=self._http_headers(), timeout=10)
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_account_email(self, email: str) -> Dict:
        """Set/replace the recovery email; a verification link is emailed to it."""
        try:
            response = requests.post(
                f"{self.http_url}/api/account/email",
                json={'email': email}, headers=self._http_headers(), timeout=15)
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def verify_email(self, token: str) -> Dict:
        """Consume an email-verification token (from the emailed link)."""
        try:
            response = requests.post(
                f"{self.http_url}/api/account/verify_email",
                json={'token': token}, headers=self._http_headers(), timeout=10)
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def forgot_password(self, identifier: str) -> Dict:
        """Request a password-reset link for a username or verified email. The
        server always answers generically (no account enumeration)."""
        try:
            response = requests.post(
                f"{self.http_url}/api/auth/forgot_password",
                json={'identifier': identifier},
                headers=self._http_headers(), timeout=15)
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def reset_password(self, token: str, new_password: str) -> Dict:
        """Complete a password reset with the emailed token + a new password."""
        try:
            response = requests.post(
                f"{self.http_url}/api/auth/reset_password",
                json={'token': token, 'new_password': new_password},
                headers=self._http_headers(), timeout=15)
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ----- User mailbox (username@domain) -----

    def get_mailbox(self, folder: str = 'inbox') -> Dict:
        """List messages in the given folder ('inbox' or 'sent')."""
        try:
            path = 'sent' if folder == 'sent' else 'inbox'
            response = requests.get(
                f"{self.http_url}/api/mail/{path}",
                headers=self._http_headers(), timeout=10)
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_mail(self, mail_id: int) -> Dict:
        """Fetch a single message (marks it read)."""
        try:
            response = requests.get(
                f"{self.http_url}/api/mail/{mail_id}",
                headers=self._http_headers(), timeout=10)
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_mail(self, mail_id: int) -> Dict:
        try:
            response = requests.delete(
                f"{self.http_url}/api/mail/{mail_id}",
                headers=self._http_headers(), timeout=10)
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def send_mail(self, to_addr: str, subject: str, body: str) -> Dict:
        """Send mail from the user's username@domain identity. Local recipients
        are delivered internally; remote ones go out via the server's mailer."""
        try:
            response = requests.post(
                f"{self.http_url}/api/mail/send",
                json={'to': to_addr, 'subject': subject, 'body': body},
                headers=self._http_headers(), timeout=15)
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def unban_from_group(self, group_id: int, user_id: int) -> Dict:
        try:
            response = requests.post(
                f"{self.http_url}/api/groups/{group_id}/unban/{user_id}",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_group_forums(self, group_id: int) -> Dict:
        """List the forums (categories) of a group."""
        try:
            response = requests.get(
                f"{self.http_url}/api/groups/{group_id}/forums",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def create_group_forum(self, group_id: int, name: str, description: Optional[str] = None) -> Dict:
        """Create a forum inside a group (owner/moderator only)."""
        try:
            response = requests.post(
                f"{self.http_url}/api/groups/{group_id}/forums",
                json={'name': name, 'description': description},
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_group_forum(self, forum_id: int) -> Dict:
        """Delete a forum and its threads (owner/moderator only)."""
        try:
            response = requests.delete(
                f"{self.http_url}/api/forums/{forum_id}",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def move_topic_to_forum(self, topic_id: int, forum_id: int) -> Dict:
        """Move a thread to another forum. Same-group is immediate; cross-group
        returns status 'pending' until a target-group moderator approves."""
        try:
            response = requests.post(
                f"{self.http_url}/api/forum/topics/{topic_id}/move",
                json={'forum_id': forum_id},
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_move_requests(self) -> Dict:
        """Pending cross-group move requests the current user can act on."""
        try:
            response = requests.get(
                f"{self.http_url}/api/forum/move_requests",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def approve_move_request(self, request_id: int) -> Dict:
        try:
            response = requests.post(
                f"{self.http_url}/api/forum/move_requests/{request_id}/approve",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def reject_move_request(self, request_id: int) -> Dict:
        try:
            response = requests.post(
                f"{self.http_url}/api/forum/move_requests/{request_id}/reject",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ==================== Extension System Methods ====================

    def submit_extension(self, slug: str, name: str, client_code: str,
                         description: Optional[str] = None, version: str = '1.0',
                         manifest: Optional[str] = None, kind: str = 'single',
                         bundle: Optional[str] = None, entry: Optional[str] = None,
                         moderators_only: bool = False, allowed_regions=None,
                         blocked_regions=None) -> Dict:
        """Submit a new extension for approval (status pending).

        A 'single' extension passes ``client_code``; a 'folder' extension passes
        a base64 zip in ``bundle`` (with ``entry`` = entry file). The audience
        gates (moderators_only, allowed/blocked regions) travel with it."""
        try:
            response = requests.post(
                f"{self.http_url}/api/extensions",
                json={'slug': slug, 'name': name, 'description': description,
                      'version': version, 'client_code': client_code, 'manifest': manifest,
                      'kind': kind, 'bundle': bundle, 'entry': entry,
                      'moderators_only': moderators_only,
                      'allowed_regions': allowed_regions or [],
                      'blocked_regions': blocked_regions or []},
                headers=self._http_headers(),
                timeout=30
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_extensions(self, status: Optional[str] = None) -> Dict:
        """List extensions (active for everyone; staff also sees pending)."""
        try:
            params = {}
            if status:
                params['status'] = status
            response = requests.get(
                f"{self.http_url}/api/extensions",
                params=params,
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_extension(self, extension_id: int) -> Dict:
        try:
            response = requests.get(
                f"{self.http_url}/api/extensions/{extension_id}",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def approve_extension(self, extension_id: int, note: Optional[str] = None) -> Dict:
        try:
            response = requests.post(
                f"{self.http_url}/api/extensions/{extension_id}/approve",
                json={'note': note},
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def reject_extension(self, extension_id: int, note: Optional[str] = None) -> Dict:
        try:
            response = requests.post(
                f"{self.http_url}/api/extensions/{extension_id}/reject",
                json={'note': note},
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_extension_client(self, slug: str) -> Dict:
        """Download an active extension's client code."""
        try:
            response = requests.get(
                f"{self.http_url}/api/extensions/{slug}/client",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def extension_data_get(self, slug: str, key: str) -> Dict:
        try:
            response = requests.get(
                f"{self.http_url}/api/extensions/{slug}/data/{key}",
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def extension_data_set(self, slug: str, key: str, value) -> Dict:
        try:
            response = requests.put(
                f"{self.http_url}/api/extensions/{slug}/data/{key}",
                json={'value': value},
                headers=self._http_headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ==================== Curated Moderation Capability (jail) ====

    def jail_user(self, user_id: int, minutes: int, reason: Optional[str] = None) -> Dict:
        try:
            response = requests.post(
                f"{self.http_url}/api/moderation/jail",
                json={'user_id': user_id, 'minutes': minutes, 'reason': reason},
                headers=self._http_headers(), timeout=10)
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def release_user(self, user_id: int) -> Dict:
        try:
            response = requests.post(
                f"{self.http_url}/api/moderation/release",
                json={'user_id': user_id}, headers=self._http_headers(), timeout=10)
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def upload_extension_asset(self, extension_id: int, kind: str, name: str,
                               content: str, mime: Optional[str] = None) -> Dict:
        """Attach a sound/tts/lang asset to an extension (content base64 for
        binary, plain text/JSON otherwise)."""
        try:
            response = requests.post(
                f"{self.http_url}/api/extensions/{extension_id}/assets",
                json={'kind': kind, 'name': name, 'content': content, 'mime': mime},
                headers=self._http_headers(), timeout=20)
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_extension_assets(self, slug: str) -> Dict:
        try:
            response = requests.get(
                f"{self.http_url}/api/extensions/{slug}/assets",
                headers=self._http_headers(), timeout=10)
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_extension_asset(self, slug: str, kind: str, name: str) -> Dict:
        try:
            response = requests.get(
                f"{self.http_url}/api/extensions/{slug}/asset/{kind}/{name}",
                headers=self._http_headers(), timeout=15)
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

    def download_app(self, app_id: int, save_path: str = None,
                     progress_callback=None) -> Dict:
        """
        Download app from repository.

        Args:
            app_id: App ID
            save_path: If given, the file is STREAMED straight to this path in
                1 MB chunks (constant memory, works for multi-GB packages) and
                the result carries ``file_path`` instead of ``file_data``.
                If omitted, the legacy behaviour is kept and the whole file is
                returned in memory as ``file_data`` (only safe for small files).
            progress_callback: Optional callable(bytes_done, total_bytes) invoked
                as bytes arrive. total_bytes is 0 when the server sends no
                Content-Length.

        Returns:
            Dict with success status, filename, and either file_path or file_data
        """
        try:
            response = requests.get(
                f"{self.http_url}/api/download/{app_id}",
                headers=self._http_headers(),
                # (connect, read) - a multi-GB download over a slow link can
                # take many minutes; read timeout is the gap between bytes.
                timeout=(30, 1800),
                stream=bool(save_path),
            )

            if response.status_code == 200:
                # Get filename from Content-Disposition header
                content_disposition = response.headers.get('Content-Disposition', '')
                filename = 'app.zip'
                if 'filename=' in content_disposition:
                    filename = content_disposition.split('filename=')[1].strip('"')

                if save_path:
                    total = int(response.headers.get('Content-Length', 0) or 0)
                    downloaded = 0
                    with open(save_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if not chunk:
                                continue
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback:
                                try:
                                    progress_callback(downloaded, total)
                                except Exception:
                                    pass
                    return {
                        "success": True,
                        "file_path": save_path,
                        "filename": filename,
                        "size": downloaded,
                    }

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
                   description: str = '', category: str = 'tools',
                   progress_callback=None) -> Dict:
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
            import uuid

            if not os.path.exists(file_path):
                return {"success": False, "error": "File not found"}

            filename = os.path.basename(file_path)

            # Prepare metadata as JSON
            metadata = {
                'name': name,
                'version': version,
                'description': description,
                'category': category
            }

            # Build the multipart/form-data body as a generator so the file is
            # streamed off disk in 1 MB blocks and never held in RAM.
            #
            # NOTE: plain `requests` with files=/a file object does NOT stream
            # - urllib3's encode_multipart_formdata does fp.read() and assembles
            # the entire body as one bytes object first. For a multi-GB TCE
            # package that exhausts client memory and the upload dies BEFORE a
            # single byte reaches the server (no request even shows up in the
            # server log). Passing a generator as `data=` makes requests use
            # chunked transfer-encoding and pull the body lazily, keeping memory
            # flat regardless of package size. aiohttp dechunks transparently
            # and request.multipart() reads it exactly as before.
            boundary = '----TitanNetBoundary' + uuid.uuid4().hex
            crlf = b'\r\n'
            dashb = ('--' + boundary).encode('ascii')

            preamble = (
                dashb + crlf
                + b'Content-Disposition: form-data; name="metadata"\r\n'
                + b'Content-Type: application/json\r\n\r\n'
                + json.dumps(metadata).encode('utf-8') + crlf
                + dashb + crlf
                + ('Content-Disposition: form-data; name="file"; '
                   'filename="%s"\r\n' % filename).encode('utf-8')
                + b'Content-Type: application/octet-stream\r\n\r\n'
            )
            epilogue = crlf + dashb + b'--' + crlf

            # Total body size for progress reporting (preamble + file + epilogue).
            total_size = len(preamble) + os.path.getsize(file_path) + len(epilogue)

            def _report(sent):
                if progress_callback:
                    try:
                        progress_callback(sent, total_size)
                    except Exception:
                        pass

            def body_stream():
                sent = 0
                yield preamble
                sent += len(preamble)
                _report(sent)
                with open(file_path, 'rb') as fh:
                    while True:
                        chunk = fh.read(1024 * 1024)
                        if not chunk:
                            break
                        yield chunk
                        sent += len(chunk)
                        _report(sent)
                yield epilogue
                sent += len(epilogue)
                _report(sent)

            headers = self._http_headers(include_content_type=False)
            headers['Content-Type'] = (
                'multipart/form-data; boundary=%s' % boundary
            )

            # (connect timeout, read timeout). A multi-GB upload over a slow
            # link can take many minutes; the read timeout is the gap allowed
            # between bytes, not the total transfer time.
            response = requests.post(
                f"{self.http_url}/api/repository/upload",
                data=body_stream(),
                headers=headers,
                timeout=(30, 1800)
            )

            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def upload_user_sound(self, file_path: str, sound_type: str) -> Dict:
        """
        Upload a business-card sound (login/logout/new_message/avatar) to the server.

        Args:
            file_path: Path to audio file (wav/ogg/mp3)
            sound_type: One of 'login', 'logout', 'new_message', 'avatar'

        Returns:
            Dict with success status
        """
        try:
            import os

            if not os.path.exists(file_path):
                return {"success": False, "error": "File not found"}

            with open(file_path, 'rb') as f:
                file_data = f.read()

            filename = os.path.basename(file_path)
            metadata = {'sound_type': sound_type}

            files = {
                'metadata': (None, json.dumps(metadata), 'application/json'),
                'file': (filename, file_data, 'application/octet-stream')
            }

            response = requests.post(
                f"{self.http_url}/api/users/sounds/upload",
                files=files,
                headers=self._http_headers(include_content_type=False),
                timeout=30
            )

            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def download_user_sound(self, username: str, sound_type: str) -> Dict:
        """
        Download a user's business-card sound from the server.

        Args:
            username: Target username
            sound_type: One of 'login', 'logout', 'new_message', 'avatar'

        Returns:
            Dict with success, file_data, and content_type
        """
        try:
            response = requests.get(
                f"{self.http_url}/api/users/sounds/{username}/{sound_type}",
                headers=self._http_headers(include_content_type=False),
                timeout=15
            )

            if response.status_code == 200:
                return {
                    "success": True,
                    "file_data": response.content,
                    "content_type": response.headers.get('Content-Type', 'application/octet-stream')
                }
            else:
                return {"success": False, "error": f"HTTP {response.status_code}"}
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
    #
    # NOTE: There is intentionally no client method to self-promote to
    # developer/moderator/admin. Roles are assigned server-side by an
    # existing administrator. Any "set_developer" / self-elevation path
    # is a privilege-escalation vulnerability and must not be reintroduced.

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

    # ================================================================
    # CERBERUS PROTOCOL (via WebSocket)
    # ================================================================

    def get_cerberus_status(self) -> Optional[Dict]:
        """Get Cerberus Protocol status (moderator or admin)"""
        try:
            async def _request():
                return await self._send_and_wait(
                    {"type": "cerberus_status"},
                    "cerberus_status",
                    timeout=10
                )
            return self._run_async(_request())
        except Exception as e:
            print(f"Cerberus status error: {e}")
            return None

    def get_cerberus_ai_assessment(self) -> Optional[Dict]:
        """Run the Cerberus AI analyst (Gemini) + risk snapshot (mod/admin).
        May take a few seconds while the model responds."""
        try:
            async def _request():
                return await self._send_and_wait(
                    {"type": "cerberus_ai_assessment"},
                    "cerberus_ai_assessment",
                    timeout=45
                )
            return self._run_async(_request())
        except Exception as e:
            print(f"Cerberus AI assessment error: {e}")
            return None

    def get_cerberus_logs(self, max_lines: int = 100) -> Optional[Dict]:
        """Get Cerberus intrusion logs (moderator or admin)"""
        try:
            async def _request():
                return await self._send_and_wait(
                    {"type": "cerberus_logs", "max_lines": max_lines},
                    "cerberus_logs",
                    timeout=10
                )
            return self._run_async(_request())
        except Exception as e:
            print(f"Cerberus logs error: {e}")
            return None

    def cerberus_activate(self, level: str = 'lockdown', reason: str = '') -> Optional[Dict]:
        """Activate Cerberus lockdown or full mode (admin only)"""
        try:
            async def _request():
                return await self._send_and_wait(
                    {"type": "cerberus_lockdown", "level": level, "reason": reason},
                    "cerberus_activate_response",
                    timeout=10
                )
            return self._run_async(_request())
        except Exception as e:
            print(f"Cerberus activate error: {e}")
            return None

    def cerberus_deactivate(self, reason: str = '') -> Optional[Dict]:
        """Deactivate Cerberus lockdown (admin only)"""
        try:
            async def _request():
                return await self._send_and_wait(
                    {"type": "cerberus_unlock", "reason": reason},
                    "cerberus_deactivate_response",
                    timeout=10
                )
            return self._run_async(_request())
        except Exception as e:
            print(f"Cerberus deactivate error: {e}")
            return None

    def cerberus_ban_ip(self, ip: str, permanent: bool = True) -> Optional[Dict]:
        """Ban IP via Cerberus (admin only)"""
        try:
            async def _request():
                return await self._send_and_wait(
                    {"type": "cerberus_ban_ip", "ip": ip, "permanent": permanent},
                    "cerberus_ban_response",
                    timeout=10
                )
            return self._run_async(_request())
        except Exception as e:
            print(f"Cerberus ban error: {e}")
            return None

    def cerberus_unban_ip(self, ip: str) -> Optional[Dict]:
        """Unban IP via Cerberus (admin only)"""
        try:
            async def _request():
                return await self._send_and_wait(
                    {"type": "cerberus_unban_ip", "ip": ip},
                    "cerberus_unban_response",
                    timeout=10
                )
            return self._run_async(_request())
        except Exception as e:
            print(f"Cerberus unban error: {e}")
            return None

    def cerberus_whitelist_ip(self, ip: str, action: str = 'add') -> Optional[Dict]:
        """Add/remove IP from Cerberus whitelist (admin only)"""
        try:
            async def _request():
                return await self._send_and_wait(
                    {"type": "cerberus_whitelist", "ip": ip, "action": action},
                    "cerberus_whitelist_response",
                    timeout=10
                )
            return self._run_async(_request())
        except Exception as e:
            print(f"Cerberus whitelist error: {e}")
            return None

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

    # =====================================================================
    # Feedback Hub
    # =====================================================================
    # All Feedback Hub traffic goes through the WebSocket because the same
    # broadcast channel notifies everyone of new items, upvotes and status
    # changes (matches package_pending / package_approved style).

    def create_feedback(self, item_type: str, title: str, content: str,
                        attachment_data: Optional[bytes] = None,
                        attachment_name: Optional[str] = None) -> Dict:
        """Submit a new feedback or idea entry to the Feedback Hub.

        Args:
            item_type: 'feedback' or 'idea'
            title: One-line subject (used as filename for attachments)
            content: Multi-line body
            attachment_data: Raw bytes of an optional attachment (max 12 MB)
            attachment_name: Original filename (used to derive extension)
        """
        if not self.is_connected or not self.websocket:
            return {"success": False, "error": _('Not logged in')}
        try:
            attachment_b64 = None
            if attachment_data:
                if len(attachment_data) > 12 * 1024 * 1024:
                    return {"success": False, "error": _('Attachment exceeds 12 MB')}
                attachment_b64 = base64.b64encode(attachment_data).decode('ascii')

            async def _send():
                message = {
                    "type": "create_feedback",
                    "item_type": item_type,
                    "title": title,
                    "content": content,
                    "attachment_data": attachment_b64,
                    "attachment_name": attachment_name,
                }
                return await self._send_and_wait(message, 'create_feedback_response', timeout=30)

            response = self._run_async(_send())
            return response if response else {"success": False, "error": _('No response from server')}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_feedback(self, item_type: Optional[str] = None) -> Dict:
        """Fetch feedback or ideas (item_type=None returns both)."""
        if not self.is_connected or not self.websocket:
            return {"success": False, "items": [], "error": _('Not logged in')}
        try:
            async def _send():
                message = {"type": "list_feedback", "item_type": item_type}
                return await self._send_and_wait(message, 'list_feedback_response', timeout=10)

            response = self._run_async(_send())
            return response if response else {"success": False, "items": [], "error": _('No response from server')}
        except Exception as e:
            return {"success": False, "items": [], "error": str(e)}

    def get_feedback(self, feedback_id: int) -> Dict:
        """Fetch a single feedback/idea entry with author and upvote info."""
        if not self.is_connected or not self.websocket:
            return {"success": False, "error": _('Not logged in')}
        try:
            async def _send():
                message = {"type": "get_feedback", "feedback_id": feedback_id}
                return await self._send_and_wait(message, 'get_feedback_response', timeout=10)

            response = self._run_async(_send())
            return response if response else {"success": False, "error": _('No response from server')}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_feedback_attachment(self, feedback_id: int) -> Dict:
        """Download the attachment (logs/recording) for any feedback/idea."""
        if not self.is_connected or not self.websocket:
            return {"success": False, "error": _('Not logged in')}
        try:
            async def _send():
                message = {"type": "get_feedback_attachment", "feedback_id": feedback_id}
                return await self._send_and_wait(message, 'feedback_attachment_response', timeout=30)

            response = self._run_async(_send())
            if not response:
                return {"success": False, "error": _('No response from server')}
            if response.get('success') and response.get('data'):
                try:
                    response['bytes'] = base64.b64decode(response['data'])
                except Exception as decode_err:
                    return {"success": False, "error": str(decode_err)}
            return response
        except Exception as e:
            return {"success": False, "error": str(e)}

    def upvote_feedback(self, feedback_id: int) -> Dict:
        """Toggle an upvote on a feedback or idea (one per user, never the author)."""
        if not self.is_connected or not self.websocket:
            return {"success": False, "error": _('Not logged in')}
        try:
            async def _send():
                message = {"type": "upvote_feedback", "feedback_id": feedback_id}
                return await self._send_and_wait(message, 'upvote_feedback_response', timeout=10)

            response = self._run_async(_send())
            return response if response else {"success": False, "error": _('No response from server')}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def change_feedback_status(self, feedback_id: int, status: str) -> Dict:
        """Moderator/admin sets the status of a feedback or idea decision."""
        if not self.is_connected or not self.websocket:
            return {"success": False, "error": _('Not logged in')}
        try:
            async def _send():
                message = {
                    "type": "change_feedback_status",
                    "feedback_id": feedback_id,
                    "status": status,
                }
                return await self._send_and_wait(message, 'change_feedback_status_response', timeout=10)

            response = self._run_async(_send())
            return response if response else {"success": False, "error": _('No response from server')}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_feedback(self, feedback_id: int) -> Dict:
        """Author or moderator deletes a feedback/idea entry."""
        if not self.is_connected or not self.websocket:
            return {"success": False, "error": _('Not logged in')}
        try:
            async def _send():
                message = {"type": "delete_feedback", "feedback_id": feedback_id}
                return await self._send_and_wait(message, 'delete_feedback_response', timeout=10)

            response = self._run_async(_send())
            return response if response else {"success": False, "error": _('No response from server')}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =====================================================================
    # INTERACTIVE GAMES (Entertainment tab)
    # =====================================================================
    # The API key never leaves the server after creation. Attachments are
    # base64-encoded on the wire and Fernet-encrypted at rest. All methods
    # mirror the feedback hub style: blocking helpers that run their async
    # body via _run_async + _send_and_wait.

    def create_game(self, name: str, description: str, provider: str,
                    api_key: str,
                    attachments: Optional[List[Dict]] = None,
                    max_tokens: Optional[int] = None,
                    max_minutes: Optional[int] = None,
                    max_players: Optional[int] = None,
                    rules_text: Optional[str] = None,
                    npc_voices: Optional[Dict[str, str]] = None) -> Dict:
        """Publish a new interactive game.

        ``attachments`` is a list of ``{type, name, folder_path?, bytes,
        mime_type?}`` where type is one of ``rules_zip``, ``prompt_txt``
        or ``sound``. ``folder_path`` is the relative directory inside a
        folder upload (empty string for plain single-file picks). Each
        entry's ``bytes`` is base64-encoded before transmission.
        """
        if not self.is_connected or not self.websocket:
            return {"success": False, "error": _('Not logged in')}
        try:
            wire_attachments: List[Dict] = []
            total_size = 0
            for att in (attachments or []):
                payload = att.get('bytes')
                if not payload:
                    continue
                if not isinstance(payload, (bytes, bytearray)):
                    continue
                if len(payload) > 25 * 1024 * 1024:
                    return {"success": False, "error": _('Attachment exceeds 25 MB')}
                total_size += len(payload)
                wire_attachments.append({
                    'type': att.get('type') or 'other',
                    'name': att.get('name') or 'attachment',
                    'folder_path': att.get('folder_path') or '',
                    'mime_type': att.get('mime_type'),
                    'data_b64': base64.b64encode(payload).decode('ascii'),
                })
            if total_size > 250 * 1024 * 1024:
                return {"success": False, "error": _('Total attachments exceed 250 MB')}

            async def _send():
                message = {
                    "type": "create_game",
                    "name": name,
                    "description": description,
                    "provider": provider,
                    "api_key": api_key,
                    "max_tokens": max_tokens,
                    "max_minutes": max_minutes,
                    "max_players": max_players,
                    "rules_text": rules_text,
                    "npc_voices": npc_voices or {},
                    "attachments": wire_attachments,
                }
                return await self._send_and_wait(message, 'create_game_response', timeout=60)

            response = self._run_async(_send())
            return response if response else {"success": False, "error": _('No response from server')}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_games(self) -> Dict:
        """Fetch the catalog of active interactive games."""
        if not self.is_connected or not self.websocket:
            return {"success": False, "games": [], "error": _('Not logged in')}
        try:
            async def _send():
                message = {"type": "list_games"}
                return await self._send_and_wait(message, 'list_games_response', timeout=15)

            response = self._run_async(_send())
            return response if response else {"success": False, "games": [], "error": _('No response from server')}
        except Exception as e:
            return {"success": False, "games": [], "error": str(e)}

    def get_game(self, game_id: int) -> Dict:
        """Fetch a single game definition with attachments (no API key)."""
        if not self.is_connected or not self.websocket:
            return {"success": False, "error": _('Not logged in')}
        try:
            async def _send():
                message = {"type": "get_game", "game_id": game_id}
                return await self._send_and_wait(message, 'get_game_response', timeout=10)

            response = self._run_async(_send())
            return response if response else {"success": False, "error": _('No response from server')}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_game(self, game_id: int) -> Dict:
        """Owner or moderator deletes a game."""
        if not self.is_connected or not self.websocket:
            return {"success": False, "error": _('Not logged in')}
        try:
            async def _send():
                message = {"type": "delete_game", "game_id": game_id}
                return await self._send_and_wait(message, 'delete_game_response', timeout=15)

            response = self._run_async(_send())
            return response if response else {"success": False, "error": _('No response from server')}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_game_attachment(self, attachment_id: int) -> Dict:
        """Download a game attachment by id."""
        if not self.is_connected or not self.websocket:
            return {"success": False, "error": _('Not logged in')}
        try:
            async def _send():
                message = {"type": "get_game_attachment", "attachment_id": attachment_id}
                return await self._send_and_wait(message, 'game_attachment_response', timeout=30)

            response = self._run_async(_send())
            if not response:
                return {"success": False, "error": _('No response from server')}
            if response.get('success') and response.get('data'):
                try:
                    response['bytes'] = base64.b64decode(response['data'])
                except Exception as decode_err:
                    return {"success": False, "error": str(decode_err)}
            return response
        except Exception as e:
            return {"success": False, "error": str(e)}

    def start_game_session(self, game_id: int) -> Dict:
        """Open a new lobby session for ``game_id``."""
        if not self.is_connected or not self.websocket:
            return {"success": False, "error": _('Not logged in')}
        try:
            async def _send():
                message = {"type": "start_game_session", "game_id": game_id}
                return await self._send_and_wait(message, 'start_game_session_response', timeout=15)

            response = self._run_async(_send())
            return response if response else {"success": False, "error": _('No response from server')}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def join_game_session(self, session_id: int) -> Dict:
        """Join an existing lobby session."""
        if not self.is_connected or not self.websocket:
            return {"success": False, "error": _('Not logged in')}
        try:
            async def _send():
                message = {"type": "join_game_session", "session_id": session_id}
                return await self._send_and_wait(message, 'join_game_session_response', timeout=10)

            response = self._run_async(_send())
            return response if response else {"success": False, "error": _('No response from server')}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def leave_game_session(self, session_id: int) -> Dict:
        """Leave a session. Drains workers when the lobby empties."""
        if not self.is_connected or not self.websocket:
            return {"success": False, "error": _('Not logged in')}
        try:
            async def _send():
                message = {"type": "leave_game_session", "session_id": session_id}
                return await self._send_and_wait(message, 'leave_game_session_response', timeout=10)

            response = self._run_async(_send())
            return response if response else {"success": False, "error": _('No response from server')}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_game_session(self, session_id: int) -> Dict:
        """Fetch a session snapshot (state, turn order, players)."""
        if not self.is_connected or not self.websocket:
            return {"success": False, "error": _('Not logged in')}
        try:
            async def _send():
                message = {"type": "get_game_session", "session_id": session_id}
                return await self._send_and_wait(message, 'get_game_session_response', timeout=10)

            response = self._run_async(_send())
            return response if response else {"success": False, "error": _('No response from server')}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_game_sessions(self, game_id: Optional[int] = None) -> Dict:
        """List active lobbies, optionally filtered by game_id."""
        if not self.is_connected or not self.websocket:
            return {"success": False, "sessions": [], "error": _('Not logged in')}
        try:
            async def _send():
                message = {"type": "list_game_sessions", "game_id": game_id}
                return await self._send_and_wait(message, 'list_game_sessions_response', timeout=10)

            response = self._run_async(_send())
            return response if response else {"success": False, "sessions": [], "error": _('No response from server')}
        except Exception as e:
            return {"success": False, "sessions": [], "error": str(e)}

    def game_player_action(self, session_id: int, text: str) -> Dict:
        """Send a typed action ("I draw my sword and attack the troll")."""
        if not self.is_connected or not self.websocket:
            return {"success": False, "error": _('Not logged in')}
        if not (text or '').strip():
            return {"success": False, "error": _('Empty action')}
        try:
            async def _send():
                message = {"type": "game_player_action", "session_id": session_id, "text": text}
                return await self._send_and_wait(message, 'game_player_action_response', timeout=15)

            response = self._run_async(_send())
            return response if response else {"success": False, "error": _('No response from server')}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def game_voice_chunk(self, session_id: int, audio_bytes: bytes) -> Dict:
        """Stream a single audio chunk from the active player's mic.

        Fire-and-forget: voice frames arrive at ~33 Hz from the mic, so
        making each one a request/response with a 10 s timeout swamps the
        ``_send_and_wait`` correlation table and produces "No response
        from server" errors that have nothing to do with the actual
        AI session. We just push the JSON onto the websocket and let
        the server queue it on the worker. Actual VAD / end-of-turn
        detection happens server-side via Gemini Live.
        """
        if not self.is_connected or not self.websocket:
            return {"success": False, "error": _('Not logged in')}
        if not audio_bytes:
            return {"success": False, "error": _('Empty chunk')}
        try:
            audio_b64 = base64.b64encode(audio_bytes).decode('ascii')

            async def _send():
                await self.websocket.send(json.dumps({
                    "type": "game_voice_chunk",
                    "session_id": session_id,
                    "audio_b64": audio_b64,
                }))

            self._run_async(_send())
            return {"success": True, "session_id": session_id, "queued": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def game_advance_turn(self, session_id: int) -> Dict:
        """Manually advance the turn (host-only on the server side)."""
        if not self.is_connected or not self.websocket:
            return {"success": False, "error": _('Not logged in')}
        try:
            async def _send():
                message = {"type": "game_advance_turn", "session_id": session_id}
                return await self._send_and_wait(message, 'game_advance_turn_response', timeout=10)

            response = self._run_async(_send())
            return response if response else {"success": False, "error": _('No response from server')}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def game_end_session(self, session_id: int) -> Dict:
        """Host or moderator ends a running session early."""
        if not self.is_connected or not self.websocket:
            return {"success": False, "error": _('Not logged in')}
        try:
            async def _send():
                message = {"type": "game_end_session", "session_id": session_id}
                return await self._send_and_wait(message, 'game_end_session_response', timeout=10)

            response = self._run_async(_send())
            return response if response else {"success": False, "error": _('No response from server')}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def wipe_all_game_sessions(self) -> Dict:
        """Moderator/admin: hard-delete every session row + drain workers.

        Goes through the running server, never opens a parallel DB
        connection. See sqlcipher_safety.md memory for context.
        """
        if not self.is_connected or not self.websocket:
            return {"success": False, "error": _('Not logged in')}
        try:
            async def _send():
                message = {"type": "wipe_all_game_sessions"}
                return await self._send_and_wait(message, 'wipe_all_game_sessions_response', timeout=30)

            response = self._run_async(_send())
            return response if response else {"success": False, "error": _('No response from server')}
        except Exception as e:
            return {"success": False, "error": str(e)}
