"""
Titan-Net Server - Main WebSocket Server
Handles real-time messaging, chat rooms, and client connections
"""

import asyncio
import websockets
import json
import logging
import struct
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, Set, Optional, List, Any
import secrets
import hashlib
from models import Database
from cerberus import CerberusProtocol, THREAT_NAMES
from dangerous_cerberus import DangerousCerberus
from hackback import HackBackProtocol, identify_cloud_provider
try:
    from gemini_game_worker import GeminiGameWorker
    _GAME_WORKER_AVAILABLE = True
except Exception as _gw_err:
    GeminiGameWorker = None  # type: ignore
    _GAME_WORKER_AVAILABLE = False
    print(f"[GAMES] GeminiGameWorker import failed: {_gw_err}")

# Binary voice packet constants
VOICE_AUDIO_TYPE = 0x01
VOICE_HEADER_SIZE = 13  # 1 + 4 + 4 + 4 bytes

# Create logs directory if it doesn't exist
import os
import re
os.makedirs('logs', exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/server.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('TitanNetServer')


# Substrings that indicate the SQLCipher in-memory cipher state is dead
# (overnight 2026-05-06 incident: the page-cache "deferred error condition"
# pattern raises these for hours without recovering, and there is no path
# back from in-process — a restart + auto-recovery from a clean backup is
# the only fix). When the heartbeat or backup loop sees one of these we
# short-circuit to ``os._exit(1)`` instead of waiting for the standard
# 3-strike grace window.
_FATAL_DB_ERROR_PATTERNS = (
    'malformed',         # "database disk image is malformed"
    'hmac check failed',
    'disk i/o error',
    'cipher',            # "sqlite3Codec deferred error condition", etc.
)


def _is_fatal_db_error(exc: BaseException) -> bool:
    """True if ``exc`` is the SQLCipher in-memory-state-dead pattern.

    ``MemoryError`` is the smoking-gun symptom of SQLCipher's deferred-
    error condition under cipher state corruption — a page-cache miss
    in that state raises ``MemoryError`` from C-level allocator paths.
    Treat it the same as an explicit ``database disk image is malformed``
    so we don't sit broken for hours waiting for someone to notice.
    """
    if isinstance(exc, MemoryError):
        return True
    msg = str(exc).lower() if exc else ''
    return any(p in msg for p in _FATAL_DB_ERROR_PATTERNS)


def _suicide_for_systemd_restart(reason: str) -> None:
    """Flush logs and ``os._exit(1)`` so systemd restarts us.

    Used by the heartbeat watchdog and the periodic-backup loop when an
    unrecoverable in-process DB state is detected. ``os._exit`` (not
    ``sys.exit``) because the pathological case is a wedged thread that
    won't drop locks — a clean shutdown won't return either, but
    ``os._exit`` doesn't try.
    """
    logger.critical(reason)
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass
    os._exit(1)


class TitanNetServer:
    def __init__(self, host: str = '0.0.0.0', port: int = 8001, db: Optional["Database"] = None):
        self.host = host
        self.port = port
        # Accept an externally-supplied Database so the websocket and HTTP
        # servers share ONE writer lock + executor. Constructing two separate
        # Database() instances in the same process broke coordination on
        # 2026-05-03 and produced the ``database is locked`` storm. The
        # singleton in models.Database also enforces this — passing an
        # explicit db here is just clearer at the call site.
        self.db = db if db is not None else Database()

        # Connected clients: {session_id: {"websocket": ws, "user_id": id, "username": name}}
        self.clients: Dict[str, Dict] = {}

        # Room voice channels: {room_id: {user_id: websocket}}
        self.voice_channels: Dict[int, Dict[int, websockets.WebSocketServerProtocol]] = {}

        # Room websocket cache: {room_id: {user_id: websocket}} — all members, updated on join/leave
        # Used for O(1) voice relay without DB queries
        self._room_websockets: Dict[int, Dict[int, any]] = {}

        # Room type cache: {room_id: room_type_str} — avoids DB on voice_start
        self._room_type_cache: Dict[int, str] = {}

        # Cache for frequently accessed data
        self._room_members_cache: Dict[str, Set[int]] = {}
        self._online_users_cache: Optional[List[Dict]] = None
        self._online_users_cache_time: float = 0

        # Broadcast messages cache
        self._broadcast_messages_cache: Dict[str, List[str]] = {}

        # Rooms list cache (invalidated on create/delete room)
        self._rooms_cache: Optional[List[Dict]] = None
        self._rooms_cache_time: float = 0

        # Interactive Games: per-session AI worker registry (Phase 4 fills this).
        # Maps session_id -> GeminiGameWorker. Cleanup runs in
        # _cleanup_game_sessions / _cleanup_game_sessions_by_id.
        self._game_session_workers: Dict[int, Any] = {}

        # --- Dangerous Cerberus Protocol (Enhanced Intrusion Detection) ---
        self.cerberus = DangerousCerberus(log_dir='logs', db_dir='database')
        self.cerberus.on_threat_level_change = self._cerberus_threat_changed
        self.cerberus.on_admin_notify = self._cerberus_notify_admins
        self.cerberus.on_shutdown_attacker = self._cerberus_shutdown_attacker
        self.cerberus.on_disconnect_ip = self._cerberus_disconnect_ip
        self.cerberus.on_ban_ip = self._cerberus_ban_ip

        # --- HackBack Protocol (Active Defense) ---
        self.hackback = HackBackProtocol(cerberus=self.cerberus, log_dir='logs')
        # Store event loop reference for thread-safe countermeasure scheduling
        try:
            self.hackback._loop = asyncio.get_event_loop()
        except RuntimeError:
            pass  # Will be set when server starts

        # Map IP -> session_ids for Cerberus tracking
        self._ip_sessions: Dict[str, Set[str]] = {}

        # --- Dedicated thread pools (executor isolation) ----------------
        # Default loop executor was being saturated by Interactive-Games
        # workers (Gemini Live tool calls hold SQLCipher writer locks for
        # seconds at a time). When that happens, every other handler that
        # uses run_in_executor(None, ...) — including handle_login's
        # authenticate_user — queues forever, so even WS handshakes that
        # succeed never get a login_response. We split the pools so the
        # auth path never competes with games / room writes.
        self._auth_executor = ThreadPoolExecutor(
            max_workers=8, thread_name_prefix='titannet-auth'
        )
        self._games_executor = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix='titannet-games'
        )
        # Hard cap on bcrypt + login I/O. Anything slower than this is
        # almost certainly a stuck DB; fail fast so the user sees a real
        # error instead of an indefinite spinner.
        self._auth_timeout_seconds = 8.0
        # Background task that prunes dead game workers (filled in start()).
        self._games_watchdog_task: Optional[asyncio.Task] = None

    def load_broadcast_messages(self, message_type: str, language: str = 'en') -> List[str]:
        """
        Load broadcast messages from file

        Args:
            message_type: Type of broadcast (e.g., 'newuser')
            language: Language code (e.g., 'en', 'pl')

        Returns:
            List of message templates
        """
        cache_key = f"{message_type}_{language}"

        # Return cached messages if available
        if cache_key in self._broadcast_messages_cache:
            return self._broadcast_messages_cache[cache_key]

        # Load from file
        file_path = f"broadcasts/{message_type}_{language}.txt"
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                messages = [line.strip() for line in f if line.strip()]

            # Cache the messages
            self._broadcast_messages_cache[cache_key] = messages
            logger.info(f"Loaded {len(messages)} broadcast messages from {file_path}")
            return messages
        except FileNotFoundError:
            logger.warning(f"Broadcast file not found: {file_path}, falling back to English")
            # Fallback to English if language file not found
            if language != 'en':
                return self.load_broadcast_messages(message_type, 'en')
            return []
        except Exception as e:
            logger.error(f"Error loading broadcast messages from {file_path}: {e}")
            return []

    def get_random_broadcast(self, message_type: str, language: str, **kwargs) -> Optional[str]:
        """
        Get random broadcast message with placeholders replaced

        Args:
            message_type: Type of broadcast (e.g., 'newuser')
            language: Language code (e.g., 'en', 'pl')
            **kwargs: Placeholder values (e.g., username='John', titan_number=12345)

        Returns:
            Formatted broadcast message or None if no messages available
        """
        messages = self.load_broadcast_messages(message_type, language)

        if not messages:
            return None

        # Pick random message
        import random
        message = random.choice(messages)

        # Replace placeholders
        try:
            return message.format(**kwargs)
        except KeyError as e:
            logger.error(f"Missing placeholder in broadcast message: {e}")
            return message

    def load_motd(self, language: str = 'en') -> Dict:
        """
        Load Message of the Day for given language with content hash.

        Args:
            language: Language code ('en', 'pl')

        Returns:
            Dict with 'text' and 'hash', or empty dict if no MOTD
        """
        file_path = f"broadcasts/motd_{language}.txt"
        fallback_path = "broadcasts/motd_en.txt"

        for path in [file_path, fallback_path]:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    text = f.read().strip()
                if text:
                    content_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
                    return {"text": text, "hash": content_hash}
            except FileNotFoundError:
                continue
            except Exception as e:
                logger.error(f"Error loading MOTD from {path}: {e}")
                continue

        return {}

    async def register_client(self, websocket: websockets.WebSocketServerProtocol, user_data: Dict) -> str:
        """Register new client connection"""
        session_id = secrets.token_urlsafe(32)
        self.clients[session_id] = {
            "websocket": websocket,
            "user_id": user_data['id'],
            "username": user_data['username'],
            "titan_number": user_data['titan_number']
        }

        # Update user status to online. Routed through the writer
        # executor so the asyncio loop is not blocked by ``_serialized_write``'s
        # retry/backoff loop (up to ~3.15 s + SQL time on contention) — that
        # blockage is what froze the whole server during the create-room
        # incident on 2026-05-03.
        try:
            await self.db.run_write_async(self.db.update_user_status, user_data['id'], 'online')
        except Exception as e:
            logger.error(f"register_client: update_user_status failed: {e}")

        logger.info(f"Client registered: {user_data['username']} (Session: {session_id})")

        # Notify all clients about new user online
        await self.broadcast_user_status(user_data['id'], 'online')

        return session_id

    async def unregister_client(self, session_id: str):
        """Unregister client connection"""
        if session_id in self.clients:
            client = self.clients[session_id]
            user_id = client['user_id']
            username = client['username']

            # Check if user has other active sessions before full cleanup
            other_sessions = [
                sid for sid, c in self.clients.items()
                if c['user_id'] == user_id and sid != session_id
            ]

            # Remove user from all voice channels
            for room_id in list(self.voice_channels.keys()):
                if user_id in self.voice_channels[room_id]:
                    del self.voice_channels[room_id][user_id]
                    if not self.voice_channels[room_id]:
                        del self.voice_channels[room_id]
                    # Notify room that user stopped voice
                    await self.broadcast_to_room(room_id, {
                        "type": "voice_stopped",
                        "room_id": room_id,
                        "user_id": user_id,
                        "username": username
                    })

            # Remove user from all room websocket caches
            for room_id in list(self._room_websockets.keys()):
                if user_id in self._room_websockets[room_id]:
                    del self._room_websockets[room_id][user_id]
                    if not self._room_websockets[room_id]:
                        del self._room_websockets[room_id]

            # Only remove from rooms and set offline if no other sessions remain
            if not other_sessions:
                # Remove user from all rooms and notify members. Routed
                # through the writer EXECUTOR (not the writer lock on the
                # asyncio thread) so the ``_serialized_write`` retry loop —
                # which can ``time.sleep`` for up to 3.15 s under
                # contention — runs on a worker thread and never freezes
                # the event loop. Sync calls on the loop here were the
                # root cause of the cascade-of-disconnects outage on
                # 2026-05-03.
                try:
                    user_rooms = await self.db.run_write_async(
                        self.db.delete_user_room_memberships, user_id
                    )

                    # Invalidate cache and notify room members
                    for room_id in user_rooms:
                        cache_key = f"room_members_{room_id}"
                        if cache_key in self._room_members_cache:
                            del self._room_members_cache[cache_key]
                        await self.broadcast_to_room(room_id, {
                            "type": "user_left_room",
                            "room_id": room_id,
                            "user_id": user_id,
                            "username": username
                        })
                except Exception as e:
                    logger.error(f"Error removing user {username} from rooms on disconnect: {e}")

                # Update user status to offline (also through the executor).
                try:
                    await self.db.run_write_async(self.db.update_user_status, user_id, 'offline')
                except Exception as e:
                    logger.error(f"unregister_client: update_user_status failed: {e}")

            del self.clients[session_id]
            logger.info(f"Client unregistered: {username} (Session: {session_id}){' (other sessions still active)' if other_sessions else ''}")

            # Only broadcast offline if no other sessions remain
            if not other_sessions:
                # Notify all clients about user offline
                await self.broadcast_user_status(user_id, 'offline')

    async def broadcast_user_status(self, user_id: int, status: str):
        """Broadcast user status change to all clients"""
        loop = asyncio.get_event_loop()
        user = await loop.run_in_executor(None, self.db.get_user_by_id, user_id)
        if not user:
            return

        # Check if user has custom business card sounds
        def _check_sounds():
            safe_username = re.sub(r'[^a-zA-Z0-9._-]', '_', user['username'])
            user_sfx_dir = os.path.join('data', 'sfx', safe_username)
            return os.path.isdir(user_sfx_dir) and len(os.listdir(user_sfx_dir)) > 0
        has_custom_sounds = await loop.run_in_executor(None, _check_sounds)

        message = {
            "type": "user_status",
            "user_id": user_id,
            "username": user['username'],
            "titan_number": user['titan_number'],
            "status": status,
            "has_custom_sounds": has_custom_sounds
        }

        await self.broadcast(message)

    async def broadcast(self, message: Dict, exclude_session: Optional[str] = None):
        """Broadcast message to all connected clients - optimized with parallel sends"""
        disconnected = []
        message_json = json.dumps(message)  # Serialize once

        async def send_to_client(session_id, client):
            try:
                await client['websocket'].send(message_json)
            except websockets.exceptions.ConnectionClosed:
                disconnected.append(session_id)

        # Send to all clients in parallel
        tasks = [
            send_to_client(session_id, client)
            for session_id, client in self.clients.items()
            if session_id != exclude_session
        ]

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # Clean up disconnected clients
        for session_id in disconnected:
            await self.unregister_client(session_id)

    async def send_to_user(self, user_id: int, message: Dict):
        """Send message to specific user - optimized"""
        message_json = json.dumps(message)  # Serialize once

        # Find and send to all sessions of this user (may have multiple sessions)
        async def send_to_client(client):
            try:
                await client['websocket'].send(message_json)
            except websockets.exceptions.ConnectionClosed:
                pass

        tasks = [
            send_to_client(client)
            for client in self.clients.values()
            if client['user_id'] == user_id
        ]

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def broadcast_to_room(self, room_id: int, message: Dict, exclude_user_id: Optional[int] = None):
        """Broadcast message to all members of a room - optimized with caching and parallel sends"""
        # Cache room members to avoid repeated DB queries
        cache_key = f"room_members_{room_id}"
        member_ids = self._room_members_cache.get(cache_key)

        if member_ids is None:
            loop = asyncio.get_event_loop()
            def _fetch():
                conn = self.db.get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT user_id FROM room_members WHERE room_id = ?", (room_id,))
                ids = {row['user_id'] for row in cursor.fetchall()}
                conn.close()
                return ids
            member_ids = await loop.run_in_executor(None, _fetch)
            self._room_members_cache[cache_key] = member_ids

        # Serialize message once
        message_json = json.dumps(message)

        async def send_to_client(client):
            try:
                await client['websocket'].send(message_json)
            except websockets.exceptions.ConnectionClosed:
                pass

        # Broadcast to members only - parallel sends
        tasks = [
            send_to_client(client)
            for client in self.clients.values()
            if client['user_id'] != exclude_user_id and client['user_id'] in member_ids
        ]

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def handle_login(self, websocket: websockets.WebSocketServerProtocol, data: Dict) -> Dict:
        """Handle login request"""
        username = data.get('username')
        password = data.get('password')
        language = data.get('language', 'en')

        if not username or not password:
            return {
                "type": "login_response",
                "success": False,
                "error": "Username and password required"
            }

        # Run auth on the dedicated auth pool with a hard timeout.
        # Default executor can be saturated by long-running game-worker DB
        # tool calls (see __init__ for the rationale). The timeout makes
        # sure the client gets a real error instead of an indefinite hang.
        loop = asyncio.get_event_loop()

        # Hard-ban gate: reject banned IP / hardware before authenticate_user
        # so we don't burn an auth-pool slot or refresh `last_login` on a
        # banned account. ``is_ip_hardware_banned`` is a pure SELECT (no
        # writer lock); safe on the auth pool.
        client_ip = self._get_client_ip(websocket)
        ip_for_db = client_ip if client_ip and client_ip != "unknown" else None
        hardware_id = data.get('hardware_id')
        if ip_for_db or hardware_id:
            try:
                banned = await loop.run_in_executor(
                    self._auth_executor,
                    self.db.is_ip_hardware_banned,
                    ip_for_db, hardware_id,
                )
                if banned:
                    logger.warning(
                        f"[LOGIN] Hard-banned login blocked: "
                        f"ip={client_ip} hwid={hardware_id} user='{username}'"
                    )
                    return {
                        "type": "login_response",
                        "success": False,
                        "error": "Login blocked - banned IP or device",
                    }
            except Exception as e:
                logger.error(f"[LOGIN] hard-ban check failed: {e}", exc_info=True)

        try:
            user = await asyncio.wait_for(
                loop.run_in_executor(
                    self._auth_executor,
                    self.db.authenticate_user, username, password,
                ),
                timeout=self._auth_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.error(
                f"[LOGIN] authenticate_user timed out after "
                f"{self._auth_timeout_seconds}s for user='{username}' — "
                f"DB or executor stalled"
            )
            return {
                "type": "login_response",
                "success": False,
                "error": "Server is busy, please try again",
            }
        except Exception as e:
            logger.error(f"[LOGIN] authenticate_user crashed for '{username}': {e}", exc_info=True)
            return {
                "type": "login_response",
                "success": False,
                "error": "Server error",
            }

        if user:
            # Register client WITHOUT broadcasting yet
            session_id = secrets.token_urlsafe(32)
            self.clients[session_id] = {
                "websocket": websocket,
                "user_id": user['id'],
                "username": user['username'],
                "titan_number": user['titan_number']
            }

            logger.info(f"Client registered: {user['username']} (Session: {session_id})")

            # Run all login data fetches in parallel (non-blocking).
            # Use the auth pool here too — these run right after a successful
            # auth and must not be queued behind game-worker DB writes.
            async def _fetch_login_data():
                # Status update is a WRITE — must go through the serialized
                # writer executor, not the multi-worker auth pool.
                update_status = self.db.run_write_async(self.db.update_user_status, user['id'], 'online')
                online_future = loop.run_in_executor(self._auth_executor, self.db.get_online_users)
                unread_future = loop.run_in_executor(self._auth_executor, self.db.get_unread_private_messages_summary, user['id'])

                # Check custom sounds (filesystem I/O)
                def _check_sounds():
                    safe_username = re.sub(r'[^a-zA-Z0-9._-]', '_', user['username'])
                    user_sfx_dir = os.path.join('data', 'sfx', safe_username)
                    return os.path.isdir(user_sfx_dir) and len(os.listdir(user_sfx_dir)) > 0
                sounds_future = loop.run_in_executor(self._auth_executor, _check_sounds)

                # MOTD is fast (file read), but run in executor too
                motd_future = loop.run_in_executor(self._auth_executor, self.load_motd, language)

                # Await all in parallel
                await update_status
                online_users, unread_summary, has_custom_sounds, motd = await asyncio.gather(
                    online_future, unread_future, sounds_future, motd_future
                )
                return online_users, unread_summary, has_custom_sounds, motd

            online_users, unread_summary, has_custom_sounds, motd = await _fetch_login_data()

            response = {
                "type": "login_response",
                "success": True,
                "session_id": session_id,
                "user": user,
                "online_users": online_users,
                "unread_messages_summary": unread_summary,
                "has_custom_sounds": has_custom_sounds,
                "broadcast_online": True  # Signal to broadcast after sending response
            }

            if motd:
                response["motd"] = motd

            return response
        else:
            return {
                "type": "login_response",
                "success": False,
                "error": "Invalid username or password"
            }

    async def handle_register(self, websocket: websockets.WebSocketServerProtocol, data: Dict) -> Dict:
        """Handle registration request"""
        logger.info(f"[REGISTER] Received registration request for user: {data.get('username')}")
        username = data.get('username')
        password = data.get('password')
        full_name = data.get('full_name')
        email = (data.get('email') or '').strip() or None  # Optional recovery email
        language = data.get('language', 'en')  # Get user's language, default to English

        if not username or not password:
            logger.warning("[REGISTER] Missing username or password")
            return {
                "type": "register_response",
                "success": False,
                "error": "Username and password required"
            }

        client_ip = self._get_client_ip(websocket)
        ip_for_db = client_ip if client_ip and client_ip != "unknown" else None
        hardware_id = data.get('hardware_id')

        logger.info(f"[REGISTER] Creating user in database...")
        loop = asyncio.get_event_loop()
        try:
            # Auth-adjacent write: must go through the dedicated auth pool,
            # not the default loop executor (saturated by game-worker DB I/O).
            # Hard timeout matches handle_login so a stalled writer produces
            # a real error instead of an indefinite hang.
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    self._auth_executor,
                    self.db.create_user,
                    username, password, full_name, ip_for_db, hardware_id, email,
                ),
                timeout=self._auth_timeout_seconds,
            )
            logger.info(f"[REGISTER] Database result: success={result.get('success')}, error={result.get('error', 'N/A')}")
        except asyncio.TimeoutError:
            logger.error(
                f"[REGISTER] create_user timed out after "
                f"{self._auth_timeout_seconds}s for user='{username}' — "
                f"DB or executor stalled"
            )
            result = {
                "success": False,
                "error": "Server is busy, please try again",
            }
        except Exception as e:
            logger.error(f"[REGISTER] Exception during create_user: {e}", exc_info=True)
            result = {
                "success": False,
                "error": f"Server error: {str(e)}"
            }

        # If registration successful, broadcast welcome message
        if result.get('success'):
            titan_number = result.get('titan_number')
            logger.info(f"[REGISTER] User {username} registered successfully with Titan #{titan_number}")

            # Issue an email-verification token and send it, if the user gave a
            # recovery address. Best-effort: a mail failure must not fail signup.
            if email and result.get('user_id'):
                try:
                    import mailer
                    ver = await loop.run_in_executor(
                        None, self.db.create_email_verification,
                        result['user_id'], email, 'verify',
                    )
                    if ver.get('success'):
                        await loop.run_in_executor(
                            None, mailer.send_verification, email, username, ver['token']
                        )
                except Exception as e:
                    logger.error(f"[REGISTER] Failed to send verification email: {e}", exc_info=True)

            # Broadcast new user message to all clients in multiple languages
            for lang in ['en', 'pl']:
                broadcast_text = self.get_random_broadcast(
                    'newuser',
                    lang,
                    username=username,
                    titan_number=titan_number
                )

                if broadcast_text:
                    broadcast_message = {
                        "type": "new_user_broadcast",
                        "language": lang,
                        "username": username,
                        "titan_number": titan_number,
                        "message": broadcast_text,
                        "timestamp": datetime.now().isoformat()
                    }
                    await self.broadcast(broadcast_message)
                    logger.info(f"[REGISTER] Broadcasted new user message in {lang}: {broadcast_text[:50]}...")

        response = {
            "type": "register_response",
            **result
        }
        logger.info(f"[REGISTER] Returning response: {response}")
        return response

    async def handle_private_message(self, session_id: str, data: Dict):
        """Handle private message"""
        client = self.clients.get(session_id)
        if not client:
            return

        recipient_id = data.get('recipient_id')
        recipient_titan_number = data.get('recipient_titan_number')
        message_text = data.get('message')

        if not message_text:
            return

        loop = asyncio.get_event_loop()

        # Find recipient by Titan number if provided
        if recipient_titan_number:
            recipient = await loop.run_in_executor(None, self.db.get_user_by_titan_number, recipient_titan_number)
            if recipient:
                recipient_id = recipient['id']

        if not recipient_id:
            return

        # Save message to database (non-blocking)
        message_data = await loop.run_in_executor(
            None, self.db.send_private_message,
            client['user_id'], recipient_id, message_text
        )

        # Check if sender has custom sounds
        safe_username = re.sub(r'[^a-zA-Z0-9._-]', '_', client['username'])
        user_sfx_dir = os.path.join('data', 'sfx', safe_username)
        has_custom_sounds = os.path.isdir(user_sfx_dir) and len(os.listdir(user_sfx_dir)) > 0

        # Send to recipient if online
        response = {
            "type": "private_message",
            "message_id": message_data['id'],
            "sender_id": client['user_id'],
            "sender_username": client['username'],
            "sender_titan_number": client['titan_number'],
            "message": message_text,
            "sent_at": message_data['sent_at'],
            "has_custom_sounds": has_custom_sounds
        }

        await self.send_to_user(recipient_id, response)

        # Send confirmation to sender
        await self.clients[session_id]['websocket'].send(json.dumps({
            "type": "message_sent",
            "message_id": message_data['id']
        }))

    async def handle_get_messages(self, session_id: str, data: Dict) -> Dict:
        """Handle get private messages request"""
        client = self.clients.get(session_id)
        if not client:
            return {"type": "error", "error": "Not authenticated"}

        other_user_id = data.get('user_id')
        limit = data.get('limit', 100)

        if not other_user_id:
            return {"type": "error", "error": "User ID required"}

        loop = asyncio.get_event_loop()
        messages = await loop.run_in_executor(
            None, self.db.get_private_messages, client['user_id'], other_user_id, limit
        )

        return {
            "type": "private_messages",
            "messages": messages
        }

    async def handle_mark_messages_read(self, session_id: str, data: Dict) -> Dict:
        """Handle mark private messages as read request"""
        client = self.clients.get(session_id)
        if not client:
            return {"type": "error", "error": "Not authenticated"}

        sender_user_id = data.get('sender_user_id')

        if not sender_user_id:
            return {"type": "error", "error": "Sender user ID required"}

        # Mark messages from sender to current user as read (non-blocking)
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(
            None, self.db.mark_private_messages_as_read, client['user_id'], sender_user_id
        )

        return {
            "type": "mark_messages_read_response",
            "success": success
        }

    async def handle_create_room(self, session_id: str, data: Dict):
        """Handle create chat room"""
        client = self.clients.get(session_id)
        if not client:
            return

        name = data.get('name')
        description = data.get('description', '')
        room_type = data.get('room_type', 'text')
        password = data.get('password')

        if not name:
            await self.clients[session_id]['websocket'].send(json.dumps({
                "type": "room_created",
                "success": False,
                "error": "Room name required"
            }))
            return

        # Route through the writer executor — same reason as
        # register_client / unregister_client: a sync call on the asyncio
        # loop blocks every other handler for up to ~3.15 s under
        # ``_serialized_write`` retry storms. Doing it on the writer thread
        # keeps the loop responsive while the SQL runs.
        result = await self.db.run_write_async(
            self.db.create_chat_room,
            name, client['user_id'], description, room_type, password,
        )

        response = {
            "type": "room_created",
            **result
        }

        await self.clients[session_id]['websocket'].send(json.dumps(response))

        # Broadcast new room to all clients
        if result.get('success'):
            self._rooms_cache = None  # Invalidate rooms cache
            await self.broadcast({
                "type": "new_room",
                "room_id": result['room_id'],
                "name": name,
                "creator": client['username'],
                "room_type": room_type
            })

    async def handle_join_room(self, session_id: str, data: Dict):
        """Handle join chat room"""
        client = self.clients.get(session_id)
        if not client:
            return

        room_id = data.get('room_id')
        password = data.get('password')

        if not room_id:
            return

        # Funnel writes through the dedicated db-writer thread so all SQLCipher
        # writes share one connection (one decrypted-page cache). Calling
        # ``loop.run_in_executor(None, self.db.join_chat_room, ...)`` would
        # land on a random default-pool worker with its own keyed connection
        # whose page cache can drift relative to the writer thread, which has
        # corrupted the live DB before. ``run_write_async`` is the rule.
        result = await self.db.run_write_async(
            self.db.join_chat_room, room_id, client['user_id'], password
        )

        response = {
            "type": "room_joined",
            "room_id": room_id,
            **result
        }

        await self.clients[session_id]['websocket'].send(json.dumps(response))

        # Invalidate room members cache
        cache_key = f"room_members_{room_id}"
        if hasattr(self, '_room_members_cache') and cache_key in self._room_members_cache:
            del self._room_members_cache[cache_key]

        # Update room websocket cache for voice relay
        # Always update websocket cache if user is a member (new join OR already a member)
        # This is critical: after reconnection, "Already a member" returns success=False
        # but the websocket still needs to be registered for voice routing
        is_member = result.get('success') or result.get('error') == 'Already a member'
        if is_member:
            if room_id not in self._room_websockets:
                self._room_websockets[room_id] = {}
            self._room_websockets[room_id][client['user_id']] = client['websocket']

        if result.get('success'):
            await self.broadcast_to_room(room_id, {
                "type": "user_joined_room",
                "room_id": room_id,
                "user_id": client['user_id'],
                "username": client['username']
            }, exclude_user_id=client['user_id'])

    async def handle_leave_room(self, session_id: str, data: Dict):
        """Handle leave chat room"""
        client = self.clients.get(session_id)
        if not client:
            return

        room_id = data.get('room_id')
        if not room_id:
            return

        user_id = client['user_id']
        username = client['username']

        # Remove from voice channel if active
        if room_id in self.voice_channels and user_id in self.voice_channels[room_id]:
            del self.voice_channels[room_id][user_id]
            if not self.voice_channels[room_id]:
                del self.voice_channels[room_id]
            # Notify room that user stopped voice
            await self.broadcast_to_room(room_id, {
                "type": "voice_stopped",
                "room_id": room_id,
                "user_id": user_id,
                "username": username
            })

        # Remove from room websocket cache
        if room_id in self._room_websockets and user_id in self._room_websockets[room_id]:
            del self._room_websockets[room_id][user_id]
            if not self._room_websockets[room_id]:
                del self._room_websockets[room_id]

        # Same writer-isolation rule as handle_join_room — leave_chat_room is
        # a write and must run on the db-writer thread, not the loop's default
        # executor pool, to avoid SQLCipher page-cache drift.
        await self.db.run_write_async(self.db.leave_chat_room, room_id, user_id)

        # Invalidate room members cache
        cache_key = f"room_members_{room_id}"
        if cache_key in self._room_members_cache:
            del self._room_members_cache[cache_key]

        # Notify room members
        await self.broadcast_to_room(room_id, {
            "type": "user_left_room",
            "room_id": room_id,
            "user_id": user_id,
            "username": username
        })

    async def handle_delete_room(self, session_id: str, data: Dict):
        """Handle delete chat room"""
        client = self.clients.get(session_id)
        if not client:
            return

        room_id = data.get('room_id')
        if not room_id:
            return

        success = await self.db.run_write_async(
            self.db.delete_chat_room, room_id, client['user_id']
        )

        response = {
            "type": "room_deleted",
            "room_id": room_id,
            "success": success
        }

        await self.clients[session_id]['websocket'].send(json.dumps(response))

        # Notify all clients and clean up
        if success:
            self._rooms_cache = None  # Invalidate rooms cache
            # Invalidate room members cache
            cache_key = f"room_members_{room_id}"
            if cache_key in self._room_members_cache:
                del self._room_members_cache[cache_key]

            # Clean up voice channels and caches
            if room_id in self.voice_channels:
                del self.voice_channels[room_id]
            if room_id in self._room_websockets:
                del self._room_websockets[room_id]
            self._room_type_cache.pop(room_id, None)

            await self.broadcast({
                "type": "room_removed",
                "room_id": room_id
            })

    async def handle_room_message(self, session_id: str, data: Dict):
        """Handle chat room message"""
        client = self.clients.get(session_id)
        if not client:
            return

        room_id = data.get('room_id')
        message_text = data.get('message')

        if not room_id or not message_text:
            return

        # Save message to database via the writer executor — every message
        # in every room hits this path, so a sync call here would freeze
        # the loop for ~3 s on every transient SQLCipher lock.
        message_data = await self.db.run_write_async(
            self.db.send_room_message, room_id, client['user_id'], message_text
        )

        # Broadcast to room members
        await self.broadcast_to_room(room_id, {
            "type": "room_message",
            "room_id": room_id,
            "message_id": message_data['id'],
            "user_id": client['user_id'],
            "username": client['username'],
            "titan_number": client['titan_number'],
            "message": message_text,
            "sent_at": message_data['sent_at']
        })

    async def handle_get_rooms(self, session_id: str) -> Dict:
        """Handle get available rooms - cached for 3 seconds"""
        import time
        current_time = time.time()

        if (self._rooms_cache is not None and
            current_time - self._rooms_cache_time < 3.0):
            rooms = self._rooms_cache
        else:
            loop = asyncio.get_event_loop()
            rooms = await loop.run_in_executor(None, self.db.get_available_rooms)
            self._rooms_cache = rooms
            self._rooms_cache_time = current_time

        return {
            "type": "rooms_list",
            "rooms": rooms
        }

    async def handle_get_room_messages(self, session_id: str, data: Dict) -> Dict:
        """Handle get room messages"""
        room_id = data.get('room_id')
        limit = data.get('limit', 100)

        if not room_id:
            return {"type": "error", "error": "Room ID required"}

        loop = asyncio.get_event_loop()
        messages = await loop.run_in_executor(None, self.db.get_room_messages, room_id, limit)

        return {
            "type": "room_messages",
            "room_id": room_id,
            "messages": messages
        }

    async def handle_voice_start(self, session_id: str, data: Dict):
        """Handle voice transmission start"""
        room_id = data.get('room_id')
        if not room_id:
            return

        client_info = self.clients.get(session_id)
        if not client_info:
            return

        user_id = client_info.get('user_id')
        username = client_info.get('username')

        # Check room type from cache first (avoid DB on repeated calls)
        room_type = self._room_type_cache.get(room_id)
        if room_type is None:
            loop = asyncio.get_event_loop()
            room_info = await loop.run_in_executor(None, self.db.get_room_by_id, room_id)
            if not room_info:
                return
            room_type = room_info['room_type']
            self._room_type_cache[room_id] = room_type

        if room_type == 'text':
            return

        # Verify room membership via _room_websockets (in-memory, no DB)
        if room_id not in self._room_websockets or user_id not in self._room_websockets[room_id]:
            # Fallback: check DB (first join before cache populated)
            loop = asyncio.get_event_loop()
            in_room = await loop.run_in_executor(None, self.db.is_user_in_room, room_id, user_id)
            if not in_room:
                return
            # Populate cache
            if room_id not in self._room_websockets:
                self._room_websockets[room_id] = {}
            self._room_websockets[room_id][user_id] = client_info['websocket']

        # Track user in voice channel (in-memory, no DB for audio relay)
        if room_id not in self.voice_channels:
            self.voice_channels[room_id] = {}
        self.voice_channels[room_id][user_id] = client_info['websocket']

        logger.info(f"Voice started: {username} in room {room_id}")

        # Broadcast voice_started to room members (including sender)
        await self.broadcast_to_room(room_id, {
            "type": "voice_started",
            "room_id": room_id,
            "user_id": user_id,
            "username": username
        }, exclude_user_id=None)

    async def handle_voice_audio_binary(self, session_id: str, raw_data: bytes):
        """Handle binary voice packet — zero-copy relay via websockets.broadcast().
        Uses _room_websockets cache for O(1) target lookup, no DB in hot path."""
        client_info = self.clients.get(session_id)
        if not client_info:
            return

        # Parse only the 13-byte header (no JSON, no base64)
        packet_type, room_id, user_id, seq = struct.unpack('>BIII', raw_data[:VOICE_HEADER_SIZE])
        if packet_type != VOICE_AUDIO_TYPE:
            return

        # Verify sender matches session
        if user_id != client_info.get('user_id'):
            return

        # Check voice channel membership (in-memory, no DB)
        if room_id not in self.voice_channels or user_id not in self.voice_channels[room_id]:
            return

        # Build target websocket set from _room_websockets cache (excludes sender)
        room_ws = self._room_websockets.get(room_id)
        if room_ws:
            targets = [ws for uid, ws in room_ws.items() if uid != user_id]
            if targets:
                # websockets.broadcast() — no backpressure, no per-client tasks, no await
                # Fastest path: single C-level loop, skips slow clients automatically
                websockets.broadcast(targets, raw_data)

    async def handle_voice_audio(self, session_id: str, data: Dict):
        """Handle voice audio chunk — JSON legacy fallback (self-monitor support)"""
        room_id = data.get('room_id')
        audio_data = data.get('data')
        self_monitor = data.get('self_monitor', False)

        if not room_id or not audio_data:
            return

        client_info = self.clients.get(session_id)
        if not client_info:
            return

        user_id = client_info.get('user_id')

        # Use in-memory voice_channels check (no DB)
        if room_id not in self.voice_channels or user_id not in self.voice_channels[room_id]:
            return

        # Pre-serialize once for all recipients
        message_json = json.dumps({
            "type": "voice_audio",
            "room_id": room_id,
            "user_id": user_id,
            "data": audio_data
        })

        # Build target websocket set from _room_websockets cache
        room_ws = self._room_websockets.get(room_id)
        if room_ws:
            targets = [ws for uid, ws in room_ws.items() if (self_monitor or uid != user_id)]
            if targets:
                websockets.broadcast(targets, message_json)

    async def handle_voice_stop(self, session_id: str, data: Dict):
        """Handle voice transmission stop"""
        room_id = data.get('room_id')
        if not room_id:
            return

        client_info = self.clients.get(session_id)
        if not client_info:
            return

        user_id = client_info.get('user_id')
        username = client_info.get('username')

        # Remove user from voice channel tracking
        if room_id in self.voice_channels and user_id in self.voice_channels[room_id]:
            del self.voice_channels[room_id][user_id]
            if not self.voice_channels[room_id]:
                del self.voice_channels[room_id]

        logger.info(f"Voice stopped: {username} in room {room_id}")

        # Broadcast voice_stopped to room members (including sender)
        await self.broadcast_to_room(room_id, {
            "type": "voice_stopped",
            "room_id": room_id,
            "user_id": user_id,
            "username": username
        }, exclude_user_id=None)

    async def handle_ptt_start(self, session_id: str, data: Dict):
        """Handle PTT button pressed - broadcast walkie-talkie start sound to room."""
        room_id = data.get('room_id')
        if not room_id:
            return
        client_info = self.clients.get(session_id)
        if not client_info:
            return
        user_id = client_info.get('user_id')
        username = client_info.get('username')
        # Broadcast to room members (exclude sender - they play locally)
        await self.broadcast_to_room(room_id, {
            "type": "ptt_started",
            "room_id": room_id,
            "user_id": user_id,
            "username": username
        }, exclude_user_id=user_id)

    async def handle_ptt_stop(self, session_id: str, data: Dict):
        """Handle PTT button released - broadcast walkie-talkie end sound to room."""
        room_id = data.get('room_id')
        if not room_id:
            return
        client_info = self.clients.get(session_id)
        if not client_info:
            return
        user_id = client_info.get('user_id')
        username = client_info.get('username')
        # Broadcast to room members (exclude sender - they play locally)
        await self.broadcast_to_room(room_id, {
            "type": "ptt_stopped",
            "room_id": room_id,
            "user_id": user_id,
            "username": username
        }, exclude_user_id=user_id)

    async def handle_get_online_users(self, session_id: str) -> Dict:
        """Handle get online users - cached for 2 seconds"""
        import time
        current_time = time.time()

        # Use cached data if less than 2 seconds old
        if (self._online_users_cache is not None and
            current_time - self._online_users_cache_time < 2.0):
            users = self._online_users_cache
        else:
            loop = asyncio.get_event_loop()
            users = await loop.run_in_executor(None, self.db.get_online_users)
            self._online_users_cache = users
            self._online_users_cache_time = current_time

        return {
            "type": "online_users",
            "users": users
        }

    async def handle_update_blog(self, session_id: str, data: Dict):
        """Handle update blog URL"""
        client = self.clients.get(session_id)
        if not client:
            return

        blog_url = data.get('blog_url')
        if blog_url:
            await self.db.run_write_async(self.db.update_user_blog, client['user_id'], blog_url)

            await self.clients[session_id]['websocket'].send(json.dumps({
                "type": "blog_updated",
                "success": True
            }))

    async def handle_voice_signal(self, session_id: str, data: Dict):
        """Handle WebRTC voice signaling"""
        client = self.clients.get(session_id)
        if not client:
            return

        room_id = data.get('room_id')
        target_user_id = data.get('target_user_id')
        signal_data = data.get('signal')

        if target_user_id:
            # Send signal to specific user
            await self.send_to_user(target_user_id, {
                "type": "voice_signal",
                "room_id": room_id,
                "from_user_id": client['user_id'],
                "from_username": client['username'],
                "signal": signal_data
            })
        else:
            # Broadcast to room
            await self.broadcast_to_room(room_id, {
                "type": "voice_signal",
                "room_id": room_id,
                "from_user_id": client['user_id'],
                "from_username": client['username'],
                "signal": signal_data
            }, exclude_user_id=client['user_id'])

    async def handle_get_all_users(self, session_id: str) -> Dict:
        """Get list of all users (admin/moderator only)"""
        if session_id not in self.clients:
            return {"success": False, "error": "Not authenticated"}

        client = self.clients[session_id]
        user_id = client['user_id']

        # Check if user is moderator/admin
        loop = asyncio.get_event_loop()
        if not await loop.run_in_executor(None, self.db.is_moderator, user_id):
            return {"success": False, "error": "Permission denied - moderator access required"}

        users = await loop.run_in_executor(None, self.db.get_all_users, user_id)
        return {"success": True, "users": users}

    async def handle_delete_user(self, session_id: str, data: Dict) -> Dict:
        """Delete user (admin/moderator only)"""
        if session_id not in self.clients:
            return {"type": "delete_user_response", "success": False, "error": "Not authenticated"}

        client = self.clients[session_id]
        moderator_id = client['user_id']
        target_user_id = data.get('user_id')

        if not target_user_id:
            return {"type": "delete_user_response", "success": False, "error": "User ID required"}

        # Delete user
        result = await self.db.run_write_async(self.db.delete_user, target_user_id, moderator_id)

        if result['success']:
            # Force disconnect the deleted user if online
            for sid, c in list(self.clients.items()):
                if c['user_id'] == target_user_id:
                    await self.unregister_client(sid)
                    try:
                        await c['websocket'].close(code=1000, reason="Account deleted")
                    except:
                        pass

        # Add response type for client
        return {"type": "delete_user_response", **result}

    async def handle_hard_ban_user(self, session_id: str, data: Dict) -> Dict:
        """Hard ban user - prevents new account creation (admin/moderator only)"""
        if session_id not in self.clients:
            return {"type": "hard_ban_response", "success": False, "error": "Not authenticated"}

        client = self.clients[session_id]
        moderator_id = client['user_id']
        target_user_id = data.get('user_id')
        reason = data.get('reason', '')
        ip_address = data.get('ip_address')
        hardware_id = data.get('hardware_id')

        if not target_user_id:
            return {"type": "hard_ban_response", "success": False, "error": "User ID required"}

        # Hard ban user
        result = await self.db.run_write_async(
            self.db.ban_user_hard, target_user_id, moderator_id, reason, ip_address, hardware_id
        )

        if result['success']:
            # Force disconnect the banned user if online
            for sid, c in list(self.clients.items()):
                if c['user_id'] == target_user_id:
                    await self.unregister_client(sid)
                    try:
                        await c['websocket'].close(code=1000, reason="Hard banned from server")
                    except:
                        pass

            # Notify all clients about the ban
            await self.broadcast({
                "type": "user_banned",
                "user_id": target_user_id,
                "ban_type": "hard"
            })

        # Add response type for client
        return {"type": "hard_ban_response", **result}

    async def handle_broadcast(self, session_id: str, data: Dict) -> Dict:
        """Send broadcast message to all users (moderator/developer only)"""
        if session_id not in self.clients:
            return {"success": False, "error": "Not authenticated"}

        client = self.clients[session_id]
        moderator_id = client['user_id']
        moderator_username = client['username']

        # Check if user is moderator or developer
        loop = asyncio.get_event_loop()
        if not await loop.run_in_executor(None, self.db.is_moderator, moderator_id):
            return {"success": False, "error": "Permission denied - moderator access required"}

        text_message = data.get('text_message', '').strip()
        voice_data = data.get('voice_data')  # base64 encoded audio

        if not text_message and not voice_data:
            return {"success": False, "error": "Broadcast must contain text or voice message"}

        # Log broadcast
        logger.info(f"Moderator {moderator_username} sending broadcast: text={bool(text_message)}, voice={bool(voice_data)}")
        logger.info(f"Total connected clients: {len(self.clients)}")

        # Broadcast to all connected clients
        broadcast_message = {
            "type": "moderation_broadcast",
            "moderator_username": moderator_username,
            "moderator_id": moderator_id,
            "text_message": text_message if text_message else None,
            "voice_data": voice_data if voice_data else None,
            "timestamp": datetime.now().isoformat()
        }

        logger.info(f"Broadcasting message: {broadcast_message.keys()}")
        await self.broadcast(broadcast_message)
        logger.info("Broadcast completed")

        return {"type": "broadcast_response", "success": True, "message": "Broadcast sent successfully"}

    # ------------------------------------------------------------------
    # Broadcast file editor (motd_*.txt, newuser_*.txt, ...) — moderator only.
    # All paths are constrained to the local broadcasts/ directory; only
    # plain .txt filenames without separators are accepted.
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_broadcast_filename(name: str) -> Optional[str]:
        """Validate a broadcast filename and return its sanitized form, or None."""
        if not isinstance(name, str):
            return None
        name = name.strip()
        if not name:
            return None
        if name != os.path.basename(name):
            return None
        if '/' in name or '\\' in name or '\0' in name:
            return None
        if name.startswith('.'):
            return None
        if not name.lower().endswith('.txt'):
            return None
        return name

    async def handle_list_broadcast_files(self, session_id: str, data: Dict) -> Dict:
        """List editable broadcast files (moderator only)."""
        if session_id not in self.clients:
            return {"type": "broadcast_files_list", "success": False, "error": "Not authenticated"}

        client = self.clients[session_id]
        moderator_id = client['user_id']

        loop = asyncio.get_event_loop()
        if not await loop.run_in_executor(None, self.db.is_moderator, moderator_id):
            return {"type": "broadcast_files_list", "success": False,
                    "error": "Permission denied - moderator access required"}

        def _list_files():
            try:
                if not os.path.isdir("broadcasts"):
                    return []
                files = []
                for name in sorted(os.listdir("broadcasts")):
                    if not name.lower().endswith('.txt'):
                        continue
                    path = os.path.join("broadcasts", name)
                    if not os.path.isfile(path):
                        continue
                    try:
                        size = os.path.getsize(path)
                    except OSError:
                        size = 0
                    files.append({"filename": name, "size": size})
                return files
            except Exception as e:
                logger.error(f"Error listing broadcast files: {e}")
                return []

        files = await loop.run_in_executor(None, _list_files)
        return {"type": "broadcast_files_list", "success": True, "files": files}

    async def handle_get_broadcast_file(self, session_id: str, data: Dict) -> Dict:
        """Return the content of a single broadcast file (moderator only)."""
        if session_id not in self.clients:
            return {"type": "broadcast_file_content", "success": False, "error": "Not authenticated"}

        client = self.clients[session_id]
        moderator_id = client['user_id']

        loop = asyncio.get_event_loop()
        if not await loop.run_in_executor(None, self.db.is_moderator, moderator_id):
            return {"type": "broadcast_file_content", "success": False,
                    "error": "Permission denied - moderator access required"}

        filename = self._safe_broadcast_filename(data.get('filename', ''))
        if not filename:
            return {"type": "broadcast_file_content", "success": False, "error": "Invalid filename"}

        def _read_file():
            path = os.path.join("broadcasts", filename)
            if not os.path.isfile(path):
                return None, "File not found"
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read(), None
            except Exception as e:
                logger.error(f"Error reading broadcast file {filename}: {e}")
                return None, str(e)

        content, err = await loop.run_in_executor(None, _read_file)
        if err is not None:
            return {"type": "broadcast_file_content", "success": False, "error": err, "filename": filename}
        return {"type": "broadcast_file_content", "success": True,
                "filename": filename, "content": content}

    async def handle_save_broadcast_file(self, session_id: str, data: Dict) -> Dict:
        """Overwrite a broadcast file with new content (moderator only)."""
        if session_id not in self.clients:
            return {"type": "broadcast_file_saved", "success": False, "error": "Not authenticated"}

        client = self.clients[session_id]
        moderator_id = client['user_id']
        moderator_username = client['username']

        loop = asyncio.get_event_loop()
        if not await loop.run_in_executor(None, self.db.is_moderator, moderator_id):
            return {"type": "broadcast_file_saved", "success": False,
                    "error": "Permission denied - moderator access required"}

        filename = self._safe_broadcast_filename(data.get('filename', ''))
        if not filename:
            return {"type": "broadcast_file_saved", "success": False, "error": "Invalid filename"}

        content = data.get('content', '')
        if not isinstance(content, str):
            return {"type": "broadcast_file_saved", "success": False, "error": "Invalid content"}
        # Hard cap to keep accidental huge payloads from filling disk.
        if len(content.encode('utf-8', errors='replace')) > 1_000_000:
            return {"type": "broadcast_file_saved", "success": False, "error": "Content exceeds 1 MB limit"}

        def _write_file():
            try:
                os.makedirs("broadcasts", exist_ok=True)
                path = os.path.join("broadcasts", filename)
                # Refuse to create a brand-new file from scratch — we only edit
                # existing broadcast templates / motd files.
                if not os.path.isfile(path):
                    return "File not found"
                tmp_path = path + ".tmp"
                with open(tmp_path, 'w', encoding='utf-8', newline='\n') as f:
                    f.write(content)
                os.replace(tmp_path, path)
                return None
            except Exception as e:
                logger.error(f"Error saving broadcast file {filename}: {e}")
                return str(e)

        err = await loop.run_in_executor(None, _write_file)
        if err is not None:
            return {"type": "broadcast_file_saved", "success": False, "error": err, "filename": filename}

        # Drop any cached message lists so the next consumer re-reads the file.
        try:
            self._broadcast_messages_cache.clear()
        except Exception:
            pass

        logger.info(f"Moderator {moderator_username} saved broadcast file: {filename} ({len(content)} chars)")
        return {"type": "broadcast_file_saved", "success": True, "filename": filename}

    async def handle_submit_app(self, session_id: str, data: Dict) -> Dict:
        """Submit new application to repository (waiting room)"""
        if session_id not in self.clients:
            return {"success": False, "error": "Not authenticated"}

        client = self.clients[session_id]
        user_id = client['user_id']
        username = client['username']

        # Get app data
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        category = data.get('category', 'general')
        version = data.get('version', '1.0')
        file_path = data.get('file_path', '').strip()
        file_size = data.get('file_size', 0)
        metadata = data.get('metadata', {})

        if not name or not file_path:
            return {"success": False, "error": "Name and file path are required"}

        # Whitelist allowed package extensions. The repository accepts ONLY
        # data packages — .tcepackage / .zip / .7z. Executables and other
        # binaries (.exe, .msi, .bat, .ps1, .sh, .dll, ...) are rejected at
        # the metadata stage so a malicious client cannot register an .exe
        # against an existing uploaded blob.
        ALLOWED_EXTENSIONS = ('.tcepackage', '.zip', '.7z')
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return {
                "success": False,
                "error": (
                    f"Invalid file type: {ext or '(no extension)'}. "
                    f"Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
                ),
            }

        try:
            # Add app to repository (pending approval)
            app_id = await self.db.run_write_async(
                self.db.add_app_to_repository,
                name, description, category, version, user_id, file_path, file_size, metadata
            )

            logger.info(f"User {username} submitted app: {name} (ID: {app_id})")

            # Broadcast notification to all users
            notification = {
                "type": "package_pending",
                "app_id": app_id,
                "app_name": name,
                "author_username": username,
                "author_id": user_id,
                "category": category,
                "version": version,
                "timestamp": datetime.now().isoformat()
            }
            await self.broadcast(notification)

            return {"type": "submit_app_response", "success": True, "app_id": app_id}
        except Exception as e:
            logger.error(f"Error submitting app: {e}")
            return {"success": False, "error": str(e)}

    async def handle_approve_app(self, session_id: str, data: Dict) -> Dict:
        """Approve application in repository (moderator/developer only)"""
        if session_id not in self.clients:
            return {"success": False, "error": "Not authenticated"}

        client = self.clients[session_id]
        moderator_id = client['user_id']
        moderator_username = client['username']

        # Check if user is moderator or developer
        loop = asyncio.get_event_loop()
        if not await loop.run_in_executor(None, self.db.is_moderator, moderator_id):
            return {"success": False, "error": "Permission denied - moderator access required"}

        app_id = data.get('app_id')
        if not app_id:
            return {"success": False, "error": "App ID is required"}

        try:
            # Approve the app
            success = await self.db.run_write_async(self.db.approve_app, app_id, moderator_id)

            if not success:
                return {"success": False, "error": "Failed to approve app"}

            # Get app details for notification
            approved_apps = await loop.run_in_executor(None, self.db.get_approved_apps)
            app_info = next((app for app in approved_apps if app['id'] == app_id), None)

            if app_info:
                logger.info(f"Moderator {moderator_username} approved app: {app_info['name']} (ID: {app_id})")

                # Broadcast notification to all users
                notification = {
                    "type": "package_approved",
                    "app_id": app_id,
                    "app_name": app_info['name'],
                    "author_username": app_info['author_username'],
                    "author_id": app_info['author_id'],
                    "category": app_info['category'],
                    "version": app_info.get('version', '1.0'),
                    "approved_by": moderator_username,
                    "timestamp": datetime.now().isoformat()
                }
                await self.broadcast(notification)

            return {"type": "approve_app_response", "success": True}
        except Exception as e:
            logger.error(f"Error approving app: {e}")
            return {"success": False, "error": str(e)}

    # ================================================================
    # FEEDBACK HUB
    # ================================================================
    # Attachments (logs / recordings / screenshots) are stored under
    # feedback/<username>/<YYYY-MM-DD>/<safe-title>.<ext>. Recordings and
    # log/text files can be read or played by every authenticated user.

    FEEDBACK_ATTACHMENT_DIR = 'feedback'
    FEEDBACK_MAX_ATTACHMENT_BYTES = 12 * 1024 * 1024  # 12 MB
    FEEDBACK_ENC_SUFFIX = '.enc'  # marker for Fernet-encrypted attachment payloads

    @staticmethod
    def _safe_filename(name: str) -> str:
        """Reduce a string to a filesystem-safe identifier."""
        name = name.strip()
        if not name:
            return 'untitled'
        # Collapse anything outside [A-Za-z0-9._-] to underscore
        cleaned = re.sub(r'[^A-Za-z0-9._-]+', '_', name)
        cleaned = cleaned.strip('._') or 'untitled'
        return cleaned[:80]

    def _feedback_fernet(self):
        """Reuse the OAuth Fernet for feedback attachment encryption at rest.

        Same TITAN_OAUTH_KEY env var as OAuth tokens - the goal is matching
        the OAuth at-rest encryption guarantees, not key separation.
        """
        # Database._oauth_fernet caches the Fernet instance internally.
        return self.db._oauth_fernet()

    def _save_feedback_attachment(self, username: str, title: str,
                                  data_b64: str, original_name: Optional[str]) -> Optional[Dict[str, str]]:
        """Persist an attachment encrypted with Fernet under feedback/<user>/<date>/.

        Synchronous - callers MUST run this in run_in_executor so the asyncio
        event loop can keep accepting login handshakes during a 12 MB upload.
        """
        if not data_b64:
            return None
        try:
            import base64
            payload = base64.b64decode(data_b64)
        except Exception as e:
            logger.error(f"[FEEDBACK] Invalid attachment base64: {e}")
            return None
        if len(payload) > self.FEEDBACK_MAX_ATTACHMENT_BYTES:
            logger.warning(f"[FEEDBACK] Attachment from {username} exceeded 12 MB")
            return None

        ext = ''
        if original_name and '.' in original_name:
            ext = '.' + original_name.rsplit('.', 1)[-1].lower()
            ext = re.sub(r'[^A-Za-z0-9.]+', '', ext)[:8]

        safe_user = self._safe_filename(username)
        safe_title = self._safe_filename(title)
        date_dir = datetime.now().strftime('%Y-%m-%d')
        rel_dir = os.path.join(self.FEEDBACK_ATTACHMENT_DIR, safe_user, date_dir)
        os.makedirs(rel_dir, exist_ok=True)

        # Encrypt before writing - matches OAuth at-rest encryption pattern.
        encrypted = False
        try:
            f = self._feedback_fernet()
            payload = f.encrypt(payload)
            encrypted = True
        except Exception as e:
            # If encryption is not configured (TITAN_OAUTH_KEY missing), fall
            # back to plain storage rather than rejecting the user's submission.
            logger.warning(f"[FEEDBACK] Attachment encryption unavailable, storing plain: {e}")

        stored_ext = ext + (self.FEEDBACK_ENC_SUFFIX if encrypted else '')

        # Avoid clobbering existing files with the same title/date
        candidate = os.path.join(rel_dir, f"{safe_title}{stored_ext}")
        suffix = 1
        while os.path.exists(candidate):
            candidate = os.path.join(rel_dir, f"{safe_title}_{suffix}{stored_ext}")
            suffix += 1

        try:
            with open(candidate, 'wb') as fh:
                fh.write(payload)
        except Exception as e:
            logger.error(f"[FEEDBACK] Failed to write attachment {candidate}: {e}")
            return None

        return {
            'attachment_path': candidate.replace('\\', '/'),
            'attachment_name': original_name or os.path.basename(candidate),
        }

    def _read_feedback_attachment(self, abs_path: str) -> Optional[bytes]:
        """Read an attachment from disk, decrypting Fernet-protected files.

        Synchronous - callers MUST run this in run_in_executor.
        """
        try:
            with open(abs_path, 'rb') as fh:
                raw = fh.read()
        except Exception as e:
            logger.error(f"[FEEDBACK] Failed to read attachment {abs_path}: {e}")
            return None

        # New attachments end in .enc and need decryption. Legacy plain files
        # are returned as-is so historical feedback still works.
        if abs_path.endswith(self.FEEDBACK_ENC_SUFFIX):
            try:
                f = self._feedback_fernet()
                return f.decrypt(raw)
            except Exception as e:
                logger.error(f"[FEEDBACK] Failed to decrypt attachment {abs_path}: {e}")
                return None
        return raw

    async def handle_create_feedback(self, session_id: str, data: Dict) -> Dict:
        """User submits a new feedback or idea entry.

        Heavy work (base64 decode, Fernet encrypt, file write, SQLite insert)
        runs in the default executor so a 12 MB attachment cannot block the
        asyncio event loop and lock out concurrent logins.
        """
        if session_id not in self.clients:
            return {"type": "create_feedback_response", "success": False, "error": "Not authenticated"}

        client = self.clients[session_id]
        user_id = client['user_id']
        username = client['username']

        item_type = (data.get('item_type') or '').strip()
        title = (data.get('title') or '').strip()
        content = (data.get('content') or '').strip()

        if item_type not in ('feedback', 'idea'):
            return {"type": "create_feedback_response", "success": False, "error": "Invalid item type"}
        if not title or not content:
            return {"type": "create_feedback_response", "success": False, "error": "Title and content are required"}

        loop = asyncio.get_event_loop()

        attachment_info = None
        attachment_b64 = data.get('attachment_data')
        if attachment_b64:
            try:
                attachment_info = await loop.run_in_executor(
                    None,
                    self._save_feedback_attachment,
                    username,
                    title,
                    attachment_b64,
                    data.get('attachment_name'),
                )
            except Exception as e:
                logger.error(f"[FEEDBACK] Attachment save crashed: {e}", exc_info=True)
                return {
                    "type": "create_feedback_response",
                    "success": False,
                    "error": "Attachment processing failed",
                }
            if attachment_info is None:
                return {
                    "type": "create_feedback_response",
                    "success": False,
                    "error": "Attachment too large or invalid (max 12 MB)",
                }

        try:
            result = await loop.run_in_executor(
                None,
                lambda: self.db.create_feedback_item(
                    item_type=item_type,
                    title=title,
                    content=content,
                    author_id=user_id,
                    attachment_path=(attachment_info or {}).get('attachment_path'),
                    attachment_name=(attachment_info or {}).get('attachment_name'),
                ),
            )
        except Exception as e:
            logger.error(f"[FEEDBACK] DB insert crashed: {e}", exc_info=True)
            return {"type": "create_feedback_response", "success": False, "error": "Database error"}

        if not result.get('success'):
            return {"type": "create_feedback_response", **result}

        logger.info(f"[FEEDBACK] {username} submitted {item_type} '{title}' (id={result['feedback_id']})")

        notification = {
            "type": "feedback_new",
            "feedback_id": result['feedback_id'],
            "item_type": item_type,
            "title": title,
            "author_username": username,
            "author_id": user_id,
            "timestamp": result['created_at'],
        }
        try:
            await self.broadcast(notification)
        except Exception as e:
            logger.error(f"[FEEDBACK] Broadcast feedback_new failed: {e}", exc_info=True)

        return {"type": "create_feedback_response", **result}

    async def handle_list_feedback(self, session_id: str, data: Dict) -> Dict:
        """Return all feedback or ideas with upvote/author metadata."""
        if session_id not in self.clients:
            return {"type": "list_feedback_response", "success": False, "error": "Not authenticated"}
        viewer_id = self.clients[session_id]['user_id']
        item_type = data.get('item_type')
        loop = asyncio.get_event_loop()
        items = await loop.run_in_executor(
            None, lambda: self.db.get_feedback_items(item_type=item_type, viewer_id=viewer_id)
        )
        return {
            "type": "list_feedback_response",
            "success": True,
            "item_type": item_type,
            "items": items,
        }

    async def handle_get_feedback(self, session_id: str, data: Dict) -> Dict:
        """Return one feedback/idea entry with attachment info."""
        if session_id not in self.clients:
            return {"type": "get_feedback_response", "success": False, "error": "Not authenticated"}
        viewer_id = self.clients[session_id]['user_id']
        feedback_id = int(data.get('feedback_id') or 0)
        loop = asyncio.get_event_loop()
        item = await loop.run_in_executor(
            None, lambda: self.db.get_feedback_item(feedback_id, viewer_id=viewer_id)
        )
        if not item:
            return {"type": "get_feedback_response", "success": False, "error": "Feedback not found"}
        return {"type": "get_feedback_response", "success": True, "item": item}

    async def handle_get_feedback_attachment(self, session_id: str, data: Dict) -> Dict:
        """Stream the attachment back to the requester (logs or recordings).

        Every authenticated user can fetch the attachment - logs are readable and
        recordings are playable by anyone, not just moderation. Disk read +
        Fernet decryption run in the executor to keep the event loop responsive.
        """
        if session_id not in self.clients:
            return {"type": "feedback_attachment_response", "success": False, "error": "Not authenticated"}
        feedback_id = int(data.get('feedback_id') or 0)
        loop = asyncio.get_event_loop()

        try:
            item = await loop.run_in_executor(None, self.db.get_feedback_item, feedback_id)
        except Exception as e:
            logger.error(f"[FEEDBACK] DB lookup crashed for attachment {feedback_id}: {e}", exc_info=True)
            return {"type": "feedback_attachment_response", "success": False, "error": "Database error"}

        if not item:
            return {"type": "feedback_attachment_response", "success": False, "error": "Feedback not found"}
        path = item.get('attachment_path')
        if not path:
            return {"type": "feedback_attachment_response", "success": False, "error": "No attachment"}

        # Defence-in-depth: only serve files that live under the feedback dir.
        abs_root = os.path.abspath(self.FEEDBACK_ATTACHMENT_DIR)
        abs_path = os.path.abspath(path)
        if not abs_path.startswith(abs_root + os.sep) and abs_path != abs_root:
            return {"type": "feedback_attachment_response", "success": False, "error": "Invalid path"}
        if not os.path.isfile(abs_path):
            return {"type": "feedback_attachment_response", "success": False, "error": "Attachment missing"}

        try:
            payload = await loop.run_in_executor(None, self._read_feedback_attachment, abs_path)
        except Exception as e:
            logger.error(f"[FEEDBACK] Attachment read crashed for {path}: {e}", exc_info=True)
            return {"type": "feedback_attachment_response", "success": False, "error": "Read error"}

        if payload is None:
            return {"type": "feedback_attachment_response", "success": False, "error": "Read error"}

        import base64
        return {
            "type": "feedback_attachment_response",
            "success": True,
            "feedback_id": feedback_id,
            "attachment_name": item.get('attachment_name'),
            "data": base64.b64encode(payload).decode('ascii'),
            "size": len(payload),
        }

    async def handle_upvote_feedback(self, session_id: str, data: Dict) -> Dict:
        """Toggle an upvote and broadcast the change."""
        if session_id not in self.clients:
            return {"type": "upvote_feedback_response", "success": False, "error": "Not authenticated"}
        client = self.clients[session_id]
        user_id = client['user_id']
        username = client['username']

        feedback_id = int(data.get('feedback_id') or 0)
        result = await self.db.run_write_async(self.db.upvote_feedback, feedback_id, user_id)
        if not result.get('success'):
            return {"type": "upvote_feedback_response", **result}

        logger.info(
            f"[FEEDBACK] {username} {result['action']} upvote on {result['item_type']} "
            f"'{result['title']}' (id={feedback_id}, total={result['upvote_count']})"
        )

        notification = {
            "type": "feedback_upvote",
            "feedback_id": feedback_id,
            "item_type": result['item_type'],
            "title": result['title'],
            "voter_username": username,
            "voter_id": user_id,
            "action": result['action'],
            "upvote_count": result['upvote_count'],
            "timestamp": datetime.now().isoformat(),
        }
        await self.broadcast(notification)

        return {"type": "upvote_feedback_response", **result}

    async def handle_change_feedback_status(self, session_id: str, data: Dict) -> Dict:
        """Moderator/developer changes feedback or idea status."""
        if session_id not in self.clients:
            return {"type": "change_feedback_status_response", "success": False, "error": "Not authenticated"}
        client = self.clients[session_id]
        moderator_id = client['user_id']
        moderator_username = client['username']

        feedback_id = int(data.get('feedback_id') or 0)
        new_status = (data.get('status') or '').strip()
        result = await self.db.run_write_async(
            self.db.set_feedback_status, feedback_id, new_status, moderator_id
        )
        if not result.get('success'):
            return {"type": "change_feedback_status_response", **result}

        logger.info(
            f"[FEEDBACK] {moderator_username} set {result['item_type']} '{result['title']}' "
            f"(id={feedback_id}) status to {new_status}"
        )

        notification = {
            "type": "feedback_status_changed",
            "feedback_id": feedback_id,
            "item_type": result['item_type'],
            "title": result['title'],
            "author_id": result['author_id'],
            "status": new_status,
            "moderator_username": moderator_username,
            "moderator_id": moderator_id,
            "timestamp": datetime.now().isoformat(),
        }
        await self.broadcast(notification)

        return {"type": "change_feedback_status_response", **result}

    async def handle_delete_feedback(self, session_id: str, data: Dict) -> Dict:
        """Author or moderator deletes a feedback/idea.

        DB delete and disk unlink run in the executor so a slow filesystem
        cannot block the event loop while another client is logging in.
        """
        if session_id not in self.clients:
            return {"type": "delete_feedback_response", "success": False, "error": "Not authenticated"}
        client = self.clients[session_id]
        user_id = client['user_id']
        username = client['username']

        feedback_id = int(data.get('feedback_id') or 0)
        loop = asyncio.get_event_loop()

        try:
            result = await loop.run_in_executor(
                None, self.db.delete_feedback_item, feedback_id, user_id
            )
        except Exception as e:
            logger.error(f"[FEEDBACK] DB delete crashed for id={feedback_id}: {e}", exc_info=True)
            return {"type": "delete_feedback_response", "success": False, "error": "Database error"}

        if not result.get('success'):
            return {"type": "delete_feedback_response", **result}

        # Best-effort attachment cleanup - never fail the request, never block the loop.
        att_path = result.get('attachment_path')
        if att_path:
            def _unlink_attachment():
                try:
                    abs_root = os.path.abspath(self.FEEDBACK_ATTACHMENT_DIR)
                    abs_path = os.path.abspath(att_path)
                    if abs_path.startswith(abs_root + os.sep) and os.path.isfile(abs_path):
                        os.remove(abs_path)
                except Exception as e:
                    logger.warning(f"[FEEDBACK] Could not remove attachment {att_path}: {e}")
            try:
                await loop.run_in_executor(None, _unlink_attachment)
            except Exception as e:
                logger.warning(f"[FEEDBACK] Attachment unlink dispatch failed: {e}")

        logger.info(
            f"[FEEDBACK] {username} deleted {result['item_type']} '{result['title']}' (id={feedback_id})"
        )

        notification = {
            "type": "feedback_deleted",
            "feedback_id": feedback_id,
            "item_type": result['item_type'],
            "title": result['title'],
            "deleted_by": username,
            "timestamp": datetime.now().isoformat(),
        }
        try:
            await self.broadcast(notification)
        except Exception as e:
            logger.error(f"[FEEDBACK] Broadcast feedback_deleted failed: {e}", exc_info=True)

        return {"type": "delete_feedback_response", **result}

    # ================================================================
    # INTERACTIVE GAMES (Entertainment tab)
    # ================================================================
    # Game definitions (catalog) live in interactive_games. API keys are
    # Fernet-encrypted via the same TITAN_OAUTH_KEY as OAuth tokens.
    # Attachments (rules zip, prompt txt, .ogg/.wav SFX) are encrypted
    # at rest under interactive_games/<creator>/<game_id>/.
    GAMES_ATTACHMENT_DIR = 'interactive_games'
    # Bumped from 80 MB → 250 MB so creators can ship folder-style games
    # (gamebook chapters + soundscape packs + multi-file rules archives).
    GAMES_MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024  # 25 MB per file
    GAMES_MAX_TOTAL_ATTACHMENT_BYTES = 250 * 1024 * 1024  # 250 MB per game
    GAMES_ENC_SUFFIX = '.enc'
    GAMES_ALLOWED_EXTS = {
        'rules_zip': {'.zip'},
        'prompt_txt': {'.txt', '.md', '.json'},
        'sound': {'.ogg', '.wav', '.mp3', '.flac', '.opus'},
    }

    def _games_fernet(self):
        """Reuse OAuth Fernet for game attachment encryption at rest."""
        return self.db._oauth_fernet()

    def _games_dir_for(self, creator_username: str, game_id: int) -> str:
        return os.path.join(
            self.GAMES_ATTACHMENT_DIR,
            self._safe_filename(creator_username),
            str(int(game_id)),
        )

    @staticmethod
    def _safe_folder_path(folder_path: Optional[str]) -> str:
        """Sanitize a relative folder path for safe nesting under the
        creator's game directory. Strips leading separators, normalizes,
        rejects ``..`` and absolute paths, runs every component through
        ``_safe_filename`` so the on-disk layout cannot escape the game
        attachment root."""
        if not folder_path:
            return ''
        cleaned = folder_path.replace('\\', '/').strip('/').strip()
        if not cleaned:
            return ''
        parts = []
        for piece in cleaned.split('/'):
            piece = piece.strip()
            if not piece or piece == '.' or piece == '..':
                continue
            safe = TitanNetServer._safe_filename(piece)
            if safe and safe != 'untitled':
                parts.append(safe)
        return '/'.join(parts)

    def _save_game_attachment(self, creator_username: str, game_id: int,
                              attachment_type: str,
                              data_b64: str, original_name: Optional[str],
                              folder_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Persist a game attachment encrypted with Fernet.

        ``folder_path`` is an optional sanitized relative directory inside
        the game's attachment root — used by folder uploads so creators
        can ship multi-file games (gamebook chapters, soundscape packs)
        with their original directory structure preserved.

        Synchronous. Caller MUST run this in run_in_executor — same I/O
        isolation rule as feedback attachments.
        """
        if not data_b64 or not original_name:
            return None
        try:
            import base64
            payload = base64.b64decode(data_b64)
        except Exception as e:
            logger.error(f"[GAMES] Invalid attachment base64: {e}")
            return None
        if len(payload) > self.GAMES_MAX_ATTACHMENT_BYTES:
            logger.warning(f"[GAMES] Attachment from {creator_username} exceeded 25 MB")
            return None

        ext = ''
        if '.' in original_name:
            ext = '.' + original_name.rsplit('.', 1)[-1].lower()
            ext = re.sub(r'[^A-Za-z0-9.]+', '', ext)[:8]

        allowed = self.GAMES_ALLOWED_EXTS.get(attachment_type, set())
        if allowed and ext not in allowed:
            logger.warning(f"[GAMES] Rejected attachment type={attachment_type} ext={ext}")
            return None

        safe_folder = self._safe_folder_path(folder_path)
        rel_dir = self._games_dir_for(creator_username, game_id)
        if safe_folder:
            rel_dir = os.path.join(rel_dir, *safe_folder.split('/'))
        try:
            os.makedirs(rel_dir, exist_ok=True)
        except Exception as e:
            logger.error(f"[GAMES] Cannot create dir {rel_dir}: {e}")
            return None

        encrypted = False
        try:
            f = self._games_fernet()
            payload = f.encrypt(payload)
            encrypted = True
        except Exception as e:
            logger.warning(f"[GAMES] Attachment encryption unavailable, storing plain: {e}")

        safe_base = self._safe_filename(os.path.splitext(original_name)[0]) or 'file'
        stored_ext = ext + (self.GAMES_ENC_SUFFIX if encrypted else '')
        candidate = os.path.join(rel_dir, f"{attachment_type}_{safe_base}{stored_ext}")
        suffix = 1
        while os.path.exists(candidate):
            candidate = os.path.join(rel_dir, f"{attachment_type}_{safe_base}_{suffix}{stored_ext}")
            suffix += 1
        try:
            with open(candidate, 'wb') as fh:
                fh.write(payload)
        except Exception as e:
            logger.error(f"[GAMES] Failed to write {candidate}: {e}")
            return None
        # Surface the folder path to the AI by embedding it in the stored
        # file_name (e.g. "chapters/12.txt"). DB schema doesn't change —
        # file_name is just text — but downstream prompt builders and the
        # client UI now see the original layout the creator uploaded.
        display_name = (safe_folder + '/' + original_name) if safe_folder else original_name
        return {
            'file_path': candidate.replace('\\', '/'),
            'file_name': display_name,
            'size_bytes': len(payload),
        }

    def _read_game_attachment(self, abs_path: str) -> Optional[bytes]:
        """Read a game attachment from disk, decrypting if encrypted."""
        try:
            with open(abs_path, 'rb') as fh:
                raw = fh.read()
        except Exception as e:
            logger.error(f"[GAMES] Read failed {abs_path}: {e}")
            return None
        if abs_path.endswith(self.GAMES_ENC_SUFFIX):
            try:
                f = self._games_fernet()
                return f.decrypt(raw)
            except Exception as e:
                logger.error(f"[GAMES] Decrypt failed {abs_path}: {e}")
                return None
        return raw

    def _read_game_attachment_text(self, abs_path: str) -> Optional[str]:
        """Helper for plain-text attachments (rules.txt) used by AI runtime."""
        raw = self._read_game_attachment(abs_path)
        if raw is None:
            return None
        try:
            return raw.decode('utf-8')
        except Exception:
            try:
                return raw.decode('utf-8', errors='replace')
            except Exception:
                return None

    async def handle_create_game(self, session_id: str, data: Dict) -> Dict:
        """Create a new interactive game entry.

        Heavy work (base64 decode, Fernet encrypt, file writes, multiple
        SQLite inserts) runs in the executor so the event loop can keep
        accepting logins during a multi-megabyte upload.
        """
        if session_id not in self.clients:
            return {"type": "create_game_response", "success": False, "error": "Not authenticated"}

        client = self.clients[session_id]
        user_id = client['user_id']
        username = client['username']

        name = (data.get('name') or '').strip()
        description = (data.get('description') or '').strip()
        provider = (data.get('provider') or 'gemini').strip().lower()
        api_key = (data.get('api_key') or '').strip()
        max_tokens = data.get('max_tokens')
        max_minutes = data.get('max_minutes')
        max_players = data.get('max_players')
        rules_text = data.get('rules_text')
        npc_voices = data.get('npc_voices') or {}
        attachments = data.get('attachments') or []  # [{type, name, data_b64}, ...]

        if not name:
            return {"type": "create_game_response", "success": False, "error": "Name is required"}
        if not api_key:
            return {"type": "create_game_response", "success": False, "error": "API key is required"}
        if provider not in Database.GAME_PROVIDERS:
            return {"type": "create_game_response", "success": False, "error": "Invalid provider"}

        # Validate total attachment payload up front.
        total_bytes = 0
        for att in attachments:
            data_b64 = att.get('data_b64') or ''
            try:
                import base64
                # Approximate size from base64 length to fail fast.
                est = (len(data_b64) * 3) // 4
                total_bytes += est
                if est > self.GAMES_MAX_ATTACHMENT_BYTES:
                    return {"type": "create_game_response", "success": False,
                            "error": "An attachment exceeds 25 MB"}
            except Exception:
                pass
        if total_bytes > self.GAMES_MAX_TOTAL_ATTACHMENT_BYTES:
            return {"type": "create_game_response", "success": False,
                    "error": "Total attachments exceed 250 MB"}

        loop = asyncio.get_event_loop()

        # Step 1: create the game row so we have an id for the attachments dir
        try:
            result = await loop.run_in_executor(
                None,
                lambda: self.db.create_game(
                    creator_id=user_id,
                    name=name, description=description,
                    provider=provider, api_key=api_key,
                    max_tokens=max_tokens, max_minutes=max_minutes,
                    max_players=max_players, rules_text=rules_text,
                    npc_voices=npc_voices,
                ),
            )
        except Exception as e:
            logger.error(f"[GAMES] create_game crashed: {e}", exc_info=True)
            return {"type": "create_game_response", "success": False, "error": "Database error"}

        if not result.get('success'):
            return {"type": "create_game_response", **result}
        game_id = result['game_id']

        # Step 2: persist + encrypt each attachment, then insert metadata rows.
        saved_attachments: List[Dict[str, Any]] = []
        try:
            for att in attachments:
                atype = (att.get('type') or 'other').strip().lower()
                aname = (att.get('name') or '').strip()
                data_b64 = att.get('data_b64')
                if not data_b64 or not aname:
                    continue
                if atype not in self.GAMES_ALLOWED_EXTS and atype != 'other':
                    continue

                folder_path = (att.get('folder_path') or '').strip()
                saved = await loop.run_in_executor(
                    None,
                    self._save_game_attachment,
                    username, game_id, atype, data_b64, aname, folder_path,
                )
                if saved is None:
                    continue
                ins = await loop.run_in_executor(
                    None,
                    lambda: self.db.add_game_attachment(
                        game_id=game_id, attachment_type=atype,
                        file_path=saved['file_path'], file_name=saved['file_name'],
                        mime_type=att.get('mime_type'), size_bytes=saved['size_bytes'],
                    ),
                )
                if ins.get('success'):
                    saved_attachments.append({
                        'attachment_id': ins['attachment_id'],
                        'attachment_type': atype,
                        'file_name': saved['file_name'],
                        'size_bytes': saved['size_bytes'],
                    })
        except Exception as e:
            logger.error(f"[GAMES] attachment save crashed: {e}", exc_info=True)

        logger.info(f"[GAMES] {username} created game '{name}' (id={game_id}, "
                    f"provider={provider}, attachments={len(saved_attachments)})")

        notification = {
            "type": "game_new",
            "game_id": game_id,
            "name": name,
            "creator_username": username,
            "provider": provider,
            "timestamp": datetime.now().isoformat(),
        }
        try:
            await self.broadcast(notification)
        except Exception as e:
            logger.error(f"[GAMES] broadcast game_new failed: {e}", exc_info=True)

        return {
            "type": "create_game_response",
            "success": True,
            "game_id": game_id,
            "name": name,
            "attachments": saved_attachments,
        }

    async def handle_list_games(self, session_id: str, data: Dict) -> Dict:
        """Return all active games with creator metadata."""
        if session_id not in self.clients:
            return {"type": "list_games_response", "success": False, "error": "Not authenticated"}
        viewer_id = self.clients[session_id]['user_id']
        loop = asyncio.get_event_loop()
        try:
            items = await loop.run_in_executor(
                None, lambda: self.db.list_games(viewer_id=viewer_id, only_active=True)
            )
        except Exception as e:
            logger.error(f"[GAMES] list crashed: {e}", exc_info=True)
            return {"type": "list_games_response", "success": False, "error": "Database error"}
        return {"type": "list_games_response", "success": True, "games": items}

    async def handle_get_game(self, session_id: str, data: Dict) -> Dict:
        """Return one game definition with attachments. API key is never returned."""
        if session_id not in self.clients:
            return {"type": "get_game_response", "success": False, "error": "Not authenticated"}
        viewer_id = self.clients[session_id]['user_id']
        game_id = int(data.get('game_id') or 0)
        loop = asyncio.get_event_loop()
        try:
            item = await loop.run_in_executor(
                None, lambda: self.db.get_game(game_id, viewer_id=viewer_id, include_api_key=False)
            )
        except Exception as e:
            logger.error(f"[GAMES] get_game crashed: {e}", exc_info=True)
            return {"type": "get_game_response", "success": False, "error": "Database error"}
        if not item:
            return {"type": "get_game_response", "success": False, "error": "Game not found"}
        return {"type": "get_game_response", "success": True, "game": item}

    async def handle_delete_game(self, session_id: str, data: Dict) -> Dict:
        """Owner or moderator deletes a game (cascades through sessions+attachments)."""
        if session_id not in self.clients:
            return {"type": "delete_game_response", "success": False, "error": "Not authenticated"}
        client = self.clients[session_id]
        user_id = client['user_id']
        username = client['username']
        game_id = int(data.get('game_id') or 0)
        loop = asyncio.get_event_loop()

        try:
            result = await loop.run_in_executor(
                None, lambda: self.db.delete_game(game_id, requester_id=user_id)
            )
        except Exception as e:
            logger.error(f"[GAMES] delete crashed: {e}", exc_info=True)
            return {"type": "delete_game_response", "success": False, "error": "Database error"}

        if not result.get('success'):
            return {"type": "delete_game_response", **result}

        # Best-effort attachment cleanup; never fail the request.
        for path in result.get('attachment_paths') or []:
            def _unlink(p=path):
                try:
                    abs_root = os.path.abspath(self.GAMES_ATTACHMENT_DIR)
                    abs_path = os.path.abspath(p)
                    if abs_path.startswith(abs_root + os.sep) and os.path.isfile(abs_path):
                        os.remove(abs_path)
                except Exception as e:
                    logger.warning(f"[GAMES] unlink {p} failed: {e}")
            try:
                await loop.run_in_executor(None, _unlink)
            except Exception:
                pass

        # Notify any session that a Gemini Live worker should shut down too
        # (real cleanup happens in Phase 4 when sessions exist).
        try:
            await self._cleanup_game_sessions(game_id, reason='game_deleted')
        except Exception as e:
            logger.error(f"[GAMES] session cleanup after delete failed: {e}", exc_info=True)

        logger.info(f"[GAMES] {username} deleted game '{result.get('name')}' (id={game_id})")

        notification = {
            "type": "game_deleted",
            "game_id": game_id,
            "name": result.get('name'),
            "deleted_by": username,
            "timestamp": datetime.now().isoformat(),
        }
        try:
            await self.broadcast(notification)
        except Exception as e:
            logger.error(f"[GAMES] broadcast game_deleted failed: {e}", exc_info=True)

        return {
            "type": "delete_game_response",
            "success": True,
            "game_id": game_id,
            "name": result.get('name'),
        }

    async def handle_get_game_attachment(self, session_id: str, data: Dict) -> Dict:
        """Stream an attachment back (rules zip, prompt txt, sfx)."""
        if session_id not in self.clients:
            return {"type": "game_attachment_response", "success": False, "error": "Not authenticated"}
        attachment_id = int(data.get('attachment_id') or 0)
        loop = asyncio.get_event_loop()
        try:
            att = await loop.run_in_executor(self._games_executor, self.db.get_game_attachment, attachment_id)
        except Exception as e:
            logger.error(f"[GAMES] attachment lookup crashed: {e}", exc_info=True)
            return {"type": "game_attachment_response", "success": False, "error": "Database error"}
        if not att:
            return {"type": "game_attachment_response", "success": False, "error": "Attachment not found"}

        abs_root = os.path.abspath(self.GAMES_ATTACHMENT_DIR)
        abs_path = os.path.abspath(att['file_path'])
        if not abs_path.startswith(abs_root + os.sep):
            return {"type": "game_attachment_response", "success": False, "error": "Invalid path"}
        if not os.path.isfile(abs_path):
            return {"type": "game_attachment_response", "success": False, "error": "File missing"}

        try:
            payload = await loop.run_in_executor(self._games_executor, self._read_game_attachment, abs_path)
        except Exception as e:
            logger.error(f"[GAMES] attachment read crashed: {e}", exc_info=True)
            return {"type": "game_attachment_response", "success": False, "error": "Read error"}
        if payload is None:
            return {"type": "game_attachment_response", "success": False, "error": "Read error"}

        import base64
        return {
            "type": "game_attachment_response",
            "success": True,
            "attachment_id": attachment_id,
            "attachment_type": att.get('attachment_type'),
            "file_name": att.get('file_name'),
            "data": base64.b64encode(payload).decode('ascii'),
            "size": len(payload),
        }

    # ----------- Sessions (Phase 3 + Phase 4 hooks) ------------------

    async def _cleanup_game_sessions(self, game_id: int, reason: str = 'cleanup'):
        """Stop any running Gemini Live workers + mark sessions ended.

        Active worker registry lives in self._game_session_workers (filled
        in Phase 4). For Phase 3 we just mark sessions ended in the DB
        and broadcast a session_ended event to participants.
        """
        if not hasattr(self, '_game_session_workers'):
            self._game_session_workers = {}  # session_id -> worker
        loop = asyncio.get_event_loop()
        try:
            sessions = await loop.run_in_executor(
                self._games_executor, lambda: self.db.list_active_sessions(game_id=game_id)
            )
        except Exception as e:
            logger.error(f"[GAMES] cleanup list crashed: {e}", exc_info=True)
            return
        for s in sessions:
            sid = s['id']
            worker = self._game_session_workers.pop(sid, None)
            if worker is not None:
                try:
                    await worker.shutdown(reason)
                except Exception as e:
                    logger.error(f"[GAMES] worker shutdown failed: {e}", exc_info=True)
            try:
                # Writes go through the db-writer thread (one connection, one
                # page cache). _games_executor is reserved for game READS.
                await self.db.run_write_async(self.db.end_game_session, sid)
            except Exception as e:
                logger.error(f"[GAMES] end_game_session failed: {e}", exc_info=True)
            try:
                await self._broadcast_to_session(sid, {
                    "type": "game_session_ended",
                    "session_id": sid,
                    "reason": reason,
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception as e:
                logger.error(f"[GAMES] session_ended broadcast failed: {e}", exc_info=True)

    async def _broadcast_to_session(self, session_id: int, message: Dict):
        """Send a message to every connected player of a game session."""
        loop = asyncio.get_event_loop()
        try:
            sess = await loop.run_in_executor(self._games_executor, self.db.get_game_session, session_id)
        except Exception as e:
            logger.error(f"[GAMES] _broadcast_to_session lookup failed: {e}", exc_info=True)
            return
        if not sess:
            return
        active_user_ids = {p['user_id'] for p in sess.get('players', [])
                           if not p.get('left_at')}
        payload = json.dumps(message)
        for sid, client in list(self.clients.items()):
            if client['user_id'] in active_user_ids:
                try:
                    await client['websocket'].send(payload)
                except Exception as e:
                    logger.warning(f"[GAMES] send to {client.get('username')} failed: {e}")

    async def handle_start_game_session(self, session_id: str, data: Dict) -> Dict:
        """Host (creator or any logged-in user) starts a new lobby."""
        if session_id not in self.clients:
            return {"type": "start_game_session_response", "success": False, "error": "Not authenticated"}
        client = self.clients[session_id]
        user_id = client['user_id']
        username = client['username']
        game_id = int(data.get('game_id') or 0)

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                self._games_executor, lambda: self.db.create_game_session(game_id, host_id=user_id)
            )
        except Exception as e:
            logger.error(f"[GAMES] create_session crashed: {e}", exc_info=True)
            return {"type": "start_game_session_response", "success": False, "error": "Database error"}
        if not result.get('success'):
            return {"type": "start_game_session_response", **result}

        # Spawn the AI worker if the SDK is available. Stub mode kicks in
        # automatically when google-generativeai is missing or the
        # provider is not yet wired (OpenAI/Anthropic ship in follow-ups).
        gs_id = int(result['session_id'])
        if _GAME_WORKER_AVAILABLE and GeminiGameWorker is not None:
            try:
                worker = GeminiGameWorker(
                    db=self.db, session_id=gs_id, game_id=game_id,
                    broadcast_cb=self._broadcast_to_session,
                    send_to_user_cb=self._send_to_user,
                    attachment_dir=self.GAMES_ATTACHMENT_DIR,
                    enc_suffix=self.GAMES_ENC_SUFFIX,
                    fernet_factory=self._games_fernet,
                    games_executor=self._games_executor,
                )
                await worker.start()
                self._game_session_workers[gs_id] = worker
                # Move session into running state once the worker is up.
                await loop.run_in_executor(
                    self._games_executor, lambda: self.db.set_session_status(gs_id, 'running')
                )
            except Exception as e:
                logger.error(f"[GAMES] worker spawn for session {gs_id} failed: {e}", exc_info=True)

        logger.info(f"[GAMES] {username} started session {gs_id} for game {game_id}")
        notification = {
            "type": "game_session_started",
            "session_id": gs_id,
            "game_id": game_id,
            "game_name": result.get('game_name'),
            "host_username": username,
            "host_id": user_id,
            "max_players": result.get('max_players'),
            "timestamp": datetime.now().isoformat(),
        }
        try:
            await self.broadcast(notification)
        except Exception as e:
            logger.error(f"[GAMES] broadcast session_started failed: {e}", exc_info=True)
        return {"type": "start_game_session_response", **result}

    async def _send_to_user(self, user_id: int, message: Dict):
        """Send a message to one specific user across any of their sessions.

        Used for whisper() tool calls — the AI sends a private line to
        a single player. We pick the first connected session for them;
        that's good enough for single-device users (the typical case).
        """
        payload = json.dumps(message)
        for sid, client in list(self.clients.items()):
            if client['user_id'] == user_id:
                try:
                    await client['websocket'].send(payload)
                    return
                except Exception as e:
                    logger.warning(f"[GAMES] whisper send to user {user_id} failed: {e}")

    async def handle_join_game_session(self, session_id: str, data: Dict) -> Dict:
        if session_id not in self.clients:
            return {"type": "join_game_session_response", "success": False, "error": "Not authenticated"}
        client = self.clients[session_id]
        user_id = client['user_id']
        username = client['username']
        gs_id = int(data.get('session_id') or 0)

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                self._games_executor, lambda: self.db.add_session_player(gs_id, user_id)
            )
        except Exception as e:
            logger.error(f"[GAMES] join_session crashed: {e}", exc_info=True)
            return {"type": "join_game_session_response", "success": False, "error": "Database error"}
        if not result.get('success'):
            return {"type": "join_game_session_response", **result}

        # Tell every player in the session that someone joined
        await self._broadcast_to_session(gs_id, {
            "type": "game_player_joined",
            "session_id": gs_id,
            "user_id": user_id,
            "username": username,
            "timestamp": datetime.now().isoformat(),
        })
        return {"type": "join_game_session_response", **result}

    async def handle_leave_game_session(self, session_id: str, data: Dict) -> Dict:
        if session_id not in self.clients:
            return {"type": "leave_game_session_response", "success": False, "error": "Not authenticated"}
        client = self.clients[session_id]
        user_id = client['user_id']
        username = client['username']
        gs_id = int(data.get('session_id') or 0)

        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                self._games_executor, lambda: self.db.remove_session_player(gs_id, user_id)
            )
        except Exception as e:
            logger.error(f"[GAMES] leave_session crashed: {e}", exc_info=True)

        # Tell remaining players, and end the session if nobody is left.
        try:
            sess = await loop.run_in_executor(self._games_executor, self.db.get_game_session, gs_id)
        except Exception as e:
            logger.error(f"[GAMES] post-leave lookup failed: {e}", exc_info=True)
            sess = None

        await self._broadcast_to_session(gs_id, {
            "type": "game_player_left",
            "session_id": gs_id,
            "user_id": user_id,
            "username": username,
            "timestamp": datetime.now().isoformat(),
        })

        # If the lobby is now empty, hard-delete the session row. There is
        # nothing to replay (the AI never had anyone to talk to) so we'd
        # rather keep the catalog clean than preserve a status='ended' ghost.
        if sess and not any(not p.get('left_at') for p in sess.get('players', [])):
            await self._cleanup_game_sessions_by_id(
                gs_id, reason='all_players_left', hard_delete=True
            )

        return {"type": "leave_game_session_response", "success": True, "session_id": gs_id}

    async def _cleanup_game_sessions_by_id(self, gs_id: int, reason: str = 'cleanup',
                                            hard_delete: bool = False):
        """Single-session variant of _cleanup_game_sessions used on natural lobby drain.

        ``hard_delete=True`` removes the session row entirely (used when the
        last player leaves so empty lobbies don't clutter the DB / catalog).
        Otherwise we just mark it ended so a replay log is preserved.
        """
        if not hasattr(self, '_game_session_workers'):
            self._game_session_workers = {}
        worker = self._game_session_workers.pop(gs_id, None)
        if worker is not None:
            try:
                await worker.shutdown(reason)
            except Exception as e:
                logger.error(f"[GAMES] worker shutdown failed: {e}", exc_info=True)
        loop = asyncio.get_event_loop()
        # Broadcast first while the player set is still in memory — once we
        # hard-delete, _broadcast_to_session can't resolve recipients.
        await self._broadcast_to_session(gs_id, {
            "type": "game_session_ended",
            "session_id": gs_id,
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
        })
        try:
            if hard_delete:
                # Writes funnel through db-writer thread to share one keyed
                # SQLCipher connection (no page-cache drift, no HMAC corruption).
                await self.db.run_write_async(self.db.delete_game_session, gs_id)
                logger.info(f"[GAMES] session {gs_id} hard-deleted ({reason})")
            else:
                await self.db.run_write_async(self.db.end_game_session, gs_id)
        except Exception as e:
            logger.error(f"[GAMES] end/delete_game_session failed: {e}", exc_info=True)

    async def handle_get_game_session(self, session_id: str, data: Dict) -> Dict:
        if session_id not in self.clients:
            return {"type": "get_game_session_response", "success": False, "error": "Not authenticated"}
        gs_id = int(data.get('session_id') or 0)
        loop = asyncio.get_event_loop()
        try:
            sess = await loop.run_in_executor(self._games_executor, self.db.get_game_session, gs_id)
        except Exception as e:
            logger.error(f"[GAMES] get_session crashed: {e}", exc_info=True)
            return {"type": "get_game_session_response", "success": False, "error": "Database error"}
        if not sess:
            return {"type": "get_game_session_response", "success": False, "error": "Session not found"}
        return {"type": "get_game_session_response", "success": True, "session": sess}

    async def handle_list_game_sessions(self, session_id: str, data: Dict) -> Dict:
        if session_id not in self.clients:
            return {"type": "list_game_sessions_response", "success": False, "error": "Not authenticated"}
        game_id = data.get('game_id')
        if game_id is not None:
            game_id = int(game_id)
        loop = asyncio.get_event_loop()
        try:
            items = await loop.run_in_executor(
                self._games_executor, lambda: self.db.list_active_sessions(game_id=game_id)
            )
        except Exception as e:
            logger.error(f"[GAMES] list_sessions crashed: {e}", exc_info=True)
            return {"type": "list_game_sessions_response", "success": False, "error": "Database error"}
        return {"type": "list_game_sessions_response", "success": True, "sessions": items}

    async def handle_game_player_action(self, session_id: str, data: Dict) -> Dict:
        """Player sends a typed action (between turns or replacing voice)."""
        if session_id not in self.clients:
            return {"type": "game_player_action_response", "success": False, "error": "Not authenticated"}
        client = self.clients[session_id]
        user_id = client['user_id']
        username = client['username']
        gs_id = int(data.get('session_id') or 0)
        text = (data.get('text') or '').strip()
        if not text:
            return {"type": "game_player_action_response", "success": False, "error": "Empty action"}
        if len(text) > 4000:
            return {"type": "game_player_action_response", "success": False, "error": "Action too long"}

        loop = asyncio.get_event_loop()
        try:
            sess = await loop.run_in_executor(self._games_executor, self.db.get_game_session, gs_id)
        except Exception as e:
            logger.error(f"[GAMES] action lookup failed: {e}", exc_info=True)
            return {"type": "game_player_action_response", "success": False, "error": "Database error"}
        if not sess or sess['status'] == 'ended':
            return {"type": "game_player_action_response", "success": False, "error": "Session ended"}
        active_ids = {p['user_id'] for p in sess.get('players', []) if not p.get('left_at')}
        if user_id not in active_ids:
            return {"type": "game_player_action_response", "success": False, "error": "Not in this session"}

        # Persist for replay through the serialized writer executor.
        # Required by the corruption-prevention rule: all writes funnel to
        # the single db-writer thread so SQLCipher never sees concurrent
        # writers (see Database.run_write docstring + sqlcipher_hardening.md).
        try:
            await self.db.run_write_async(
                self.db.log_session_event,
                gs_id, sess.get('current_turn_idx', 0),
                f"player:{username}", "text_action", {"text": text},
            )
        except Exception as e:
            logger.warning(f"[GAMES] log player action failed: {e}")

        # Echo to the room so other players see it
        await self._broadcast_to_session(gs_id, {
            "type": "game_player_action",
            "session_id": gs_id,
            "user_id": user_id,
            "username": username,
            "text": text,
            "timestamp": datetime.now().isoformat(),
        })

        # Forward to the AI worker (Phase 4 wires this end-to-end).
        worker = getattr(self, '_game_session_workers', {}).get(gs_id)
        if worker is not None:
            try:
                await worker.send_player_text(user_id=user_id, username=username, text=text)
            except Exception as e:
                logger.error(f"[GAMES] worker.send_player_text failed: {e}", exc_info=True)

        return {"type": "game_player_action_response", "success": True, "session_id": gs_id}

    async def handle_game_voice_chunk(self, session_id: str, data: Dict) -> Dict:
        """Audio chunk from the current-turn player.

        Phase 5 wires audio routing. For now we accept the frame, log
        size, and forward to the worker if one is attached.
        """
        if session_id not in self.clients:
            return {"type": "game_voice_chunk_response", "success": False, "error": "Not authenticated"}
        client = self.clients[session_id]
        user_id = client['user_id']
        username = client['username']
        gs_id = int(data.get('session_id') or 0)
        audio_b64 = data.get('audio_b64') or ''
        if not audio_b64:
            return {"type": "game_voice_chunk_response", "success": False, "error": "Empty chunk"}

        worker = getattr(self, '_game_session_workers', {}).get(gs_id)
        if worker is None:
            # Worker not attached yet (Phase 4). We still respond OK so the
            # client doesn't think the protocol is broken.
            return {"type": "game_voice_chunk_response", "success": True,
                    "session_id": gs_id, "queued": False, "note": "AI worker offline"}
        try:
            await worker.send_voice_chunk(user_id=user_id, username=username, audio_b64=audio_b64)
        except Exception as e:
            logger.error(f"[GAMES] worker.send_voice_chunk failed: {e}", exc_info=True)
            return {"type": "game_voice_chunk_response", "success": False, "error": "Voice routing error"}
        return {"type": "game_voice_chunk_response", "success": True, "session_id": gs_id, "queued": True}

    async def handle_game_advance_turn(self, session_id: str, data: Dict) -> Dict:
        """Manually advance the turn (host-only)."""
        if session_id not in self.clients:
            return {"type": "game_advance_turn_response", "success": False, "error": "Not authenticated"}
        client = self.clients[session_id]
        user_id = client['user_id']
        gs_id = int(data.get('session_id') or 0)

        loop = asyncio.get_event_loop()
        try:
            sess = await loop.run_in_executor(self._games_executor, self.db.get_game_session, gs_id)
        except Exception as e:
            logger.error(f"[GAMES] advance lookup failed: {e}", exc_info=True)
            return {"type": "game_advance_turn_response", "success": False, "error": "Database error"}
        if not sess:
            return {"type": "game_advance_turn_response", "success": False, "error": "Session not found"}
        if sess['host_id'] != user_id and sess.get('game_creator_id') != user_id:
            return {"type": "game_advance_turn_response", "success": False, "error": "Only the host can advance the turn"}

        order = sess.get('turn_order') or [p['user_id'] for p in sess.get('players', []) if not p.get('left_at')]
        if not order:
            return {"type": "game_advance_turn_response", "success": False, "error": "No turn order set"}
        new_idx = (int(sess.get('current_turn_idx') or 0) + 1) % len(order)
        try:
            await loop.run_in_executor(
                self._games_executor, lambda: self.db.update_session_turn(gs_id, order, new_idx)
            )
        except Exception as e:
            logger.error(f"[GAMES] advance update failed: {e}", exc_info=True)
            return {"type": "game_advance_turn_response", "success": False, "error": "Database error"}

        active_user_id = order[new_idx]
        await self._broadcast_to_session(gs_id, {
            "type": "game_turn_changed",
            "session_id": gs_id,
            "active_user_id": active_user_id,
            "current_turn_idx": new_idx,
            "turn_order": order,
            "timestamp": datetime.now().isoformat(),
        })
        return {"type": "game_advance_turn_response", "success": True,
                "session_id": gs_id, "active_user_id": active_user_id,
                "current_turn_idx": new_idx}

    async def handle_wipe_all_game_sessions(self, session_id: str, data: Dict) -> Dict:
        """Moderator/admin clean-up: hard-delete every session row.

        Goes through the LIVE server's Database connection — never via a
        parallel `Database()` standalone script (that path is what
        corrupted the SQLCipher pages on 2026-04-30, see
        sqlcipher_safety.md). Worker registry is also drained so any
        running Gemini Live connections shut down cleanly first.
        """
        if session_id not in self.clients:
            return {"type": "wipe_all_game_sessions_response", "success": False, "error": "Not authenticated"}
        client = self.clients[session_id]
        user_id = client['user_id']
        username = client['username']

        loop = asyncio.get_event_loop()
        try:
            is_mod = await loop.run_in_executor(self._games_executor, self.db.is_moderator, user_id)
        except Exception as e:
            logger.error(f"[GAMES] wipe is_moderator check crashed: {e}", exc_info=True)
            return {"type": "wipe_all_game_sessions_response", "success": False, "error": "Database error"}
        if not is_mod:
            return {"type": "wipe_all_game_sessions_response", "success": False, "error": "Permission denied"}

        # Shut down every running worker first so no in-flight tool call
        # writes a row right after we wipe.
        workers = list(self._game_session_workers.items())
        self._game_session_workers.clear()
        for sid, worker in workers:
            try:
                await worker.shutdown('admin_wipe')
            except Exception as e:
                logger.warning(f"[GAMES] worker shutdown during wipe failed: {e}")

        try:
            # Bulk delete is a write — run it on the db-writer thread.
            result = await self.db.run_write_async(self.db.delete_all_game_sessions)
        except Exception as e:
            logger.error(f"[GAMES] delete_all_game_sessions crashed: {e}", exc_info=True)
            return {"type": "wipe_all_game_sessions_response", "success": False, "error": "Database error"}

        logger.info(
            f"[GAMES] {username} wiped all sessions: "
            f"sessions={result.get('sessions_deleted')} "
            f"players={result.get('players_deleted')} "
            f"log={result.get('log_deleted')}"
        )
        return {"type": "wipe_all_game_sessions_response", **result}

    async def handle_game_end_session(self, session_id: str, data: Dict) -> Dict:
        """Host or moderator ends a running session early."""
        if session_id not in self.clients:
            return {"type": "game_end_session_response", "success": False, "error": "Not authenticated"}
        client = self.clients[session_id]
        user_id = client['user_id']
        gs_id = int(data.get('session_id') or 0)

        loop = asyncio.get_event_loop()
        try:
            sess = await loop.run_in_executor(self._games_executor, self.db.get_game_session, gs_id)
        except Exception as e:
            logger.error(f"[GAMES] end lookup failed: {e}", exc_info=True)
            return {"type": "game_end_session_response", "success": False, "error": "Database error"}
        if not sess:
            return {"type": "game_end_session_response", "success": False, "error": "Session not found"}
        if sess['host_id'] != user_id:
            try:
                is_mod = await loop.run_in_executor(self._games_executor, self.db.is_moderator, user_id)
            except Exception as e:
                logger.error(f"[GAMES] end is_moderator check crashed: {e}", exc_info=True)
                return {"type": "game_end_session_response", "success": False, "error": "Database error"}
            if not is_mod:
                return {"type": "game_end_session_response", "success": False, "error": "Permission denied"}

        await self._cleanup_game_sessions_by_id(gs_id, reason='ended_by_host')
        return {"type": "game_end_session_response", "success": True, "session_id": gs_id}

    # ================================================================
    # CERBERUS PROTOCOL CALLBACKS
    # ================================================================

    def _cerberus_threat_changed(self, level: int, reason: str, attacker_ip: str):
        """Called when Cerberus threat level changes"""
        logger.warning(
            f"[CERBERUS] Threat level: {THREAT_NAMES.get(level, '?')} | "
            f"Reason: {reason} | Attacker: {attacker_ip}"
        )

    def _cerberus_notify_admins(self, title: str, message: str, level: int):
        """Notify moderators/admins about a confirmed security event.

        Regular users never receive Cerberus alerts. Cerberus itself already
        filters out ALERT-level noise, so anything reaching this callback is a
        real LOCKDOWN/CERBERUS escalation worth moderator attention.
        """
        alert = {
            "type": "cerberus_alert",
            "title": title,
            "message": message,
            "threat_level": level,
            "threat_name": THREAT_NAMES.get(level, "UNKNOWN"),
            "timestamp": datetime.now().isoformat()
        }

        for session_id, client in list(self.clients.items()):
            user = self.db.get_user_by_id(client['user_id'])
            if not user:
                continue
            is_admin = user.get('is_admin') or user.get('role') == 'admin'
            try:
                is_mod = self.db.is_moderator(client['user_id'])
            except Exception:
                is_mod = False
            if not (is_admin or is_mod):
                continue
            try:
                asyncio.ensure_future(
                    client['websocket'].send(json.dumps(alert))
                )
            except Exception:
                pass

    def _cerberus_shutdown_attacker(self, attacker_ip: str, reason: str):
        """Send shutdown to attacker's client + engage infrastructure countermeasures"""
        # Send cerberus_shutdown to all sessions from attacker's IP (shuts down their client)
        shutdown_msg = self.cerberus.get_cerberus_client_message(reason)
        shutdown_json = json.dumps(shutdown_msg)

        sessions_to_close = []
        for session_id, client in list(self.clients.items()):
            ws = client['websocket']
            client_ip = ws.remote_address[0] if ws.remote_address else None
            if client_ip == attacker_ip:
                sessions_to_close.append((session_id, ws))

        for session_id, ws in sessions_to_close:
            try:
                asyncio.ensure_future(ws.send(shutdown_json))
                asyncio.ensure_future(ws.close(1008, "Cerberus Protocol"))
            except Exception:
                pass

        logger.critical(
            f"[CERBERUS] Shutdown sent to {len(sessions_to_close)} sessions "
            f"from {attacker_ip}"
        )

        # Launch infrastructure countermeasures against the attacker's server
        # (SSH remote shutdown + CPU exhaustion, permanent for cloud/botnet)
        asyncio.ensure_future(
            self.hackback.engage_infrastructure(
                attacker_ip, reason, permanent=True
            )
        )

        logger.critical(
            f"[CERBERUS] Infrastructure countermeasures engaged against "
            f"{attacker_ip} | {reason}"
        )

    def _cerberus_disconnect_ip(self, ip: str):
        """Disconnect all sessions from an IP"""
        for session_id, client in list(self.clients.items()):
            ws = client['websocket']
            client_ip = ws.remote_address[0] if ws.remote_address else None
            if client_ip == ip:
                try:
                    asyncio.ensure_future(ws.close(1008, "Blocked by Cerberus"))
                except Exception:
                    pass

    def _cerberus_ban_ip(self, ip: str, reason: str, permanent: bool = False):
        """Ban IP via Cerberus - log to intrusion log"""
        logger.warning(f"[CERBERUS] IP banned: {ip} | permanent={permanent} | reason={reason}")

    def _get_client_ip(self, websocket) -> str:
        """Extract client IP from websocket connection"""
        try:
            addr = websocket.remote_address
            if addr:
                return addr[0]
        except Exception:
            pass
        return "unknown"

    async def handle_client(self, websocket: websockets.WebSocketServerProtocol):
        """Handle individual client connection"""
        session_id = None
        client_addr = websocket.remote_address
        client_ip = self._get_client_ip(websocket)

        # --- HackBack: Cloud infrastructure instant-ban ---
        if self.hackback.process_titan_net_connection(client_ip):
            provider = identify_cloud_provider(client_ip)
            logger.warning(
                f"[HACKBACK] Cloud IP rejected: {client_ip} ({provider})"
            )
            shutdown_msg = self.cerberus.get_cerberus_client_message(
                f"Cloud infrastructure ({provider}) - zero tolerance policy"
            )
            try:
                await websocket.send(json.dumps(shutdown_msg))
                await websocket.close(1008, "HackBack: Cloud IP blocked")
            except Exception:
                pass
            # Engage countermeasures against the cloud/botnet server
            await self.hackback.engage_infrastructure(
                client_ip,
                f"Cloud infrastructure ({provider}) - zero tolerance policy",
                permanent=True,
            )
            return

        # --- Cerberus: Check if IP is banned ---
        if self.cerberus.is_ip_banned(client_ip):
            logger.warning(f"[CERBERUS] Blocked banned IP: {client_ip}")
            shutdown_msg = self.cerberus.get_cerberus_client_message(
                "Your IP has been permanently blocked by Cerberus Protocol"
            )
            try:
                await websocket.send(json.dumps(shutdown_msg))
                await websocket.close(1008, "Blocked by Cerberus")
            except Exception:
                pass
            # Banned IP trying again - engage countermeasures
            await self.hackback.engage_infrastructure(
                client_ip,
                "Banned IP reconnection attempt",
                permanent=True,
            )
            return

        # --- Cerberus: DDoS detection - record connection ---
        if self.cerberus.record_connection(client_ip):
            logger.warning(f"[CERBERUS] DDoS blocked connection from {client_ip}")
            try:
                await websocket.close(1008, "Connection rate limited")
            except Exception:
                pass
            return

        # Track IP -> session mapping
        if client_ip not in self._ip_sessions:
            self._ip_sessions[client_ip] = set()

        logger.info(f"[CONNECTION] New client connected from {client_addr}")

        try:
            async for message in websocket:
                try:
                    # Binary frame = voice audio (fast path, zero-copy relay)
                    if isinstance(message, bytes):
                        if session_id and len(message) >= VOICE_HEADER_SIZE:
                            await self.handle_voice_audio_binary(session_id, message)
                        continue

                    # --- Cerberus: Message flood detection ---
                    if self.cerberus.record_message(client_ip):
                        logger.warning(f"[CERBERUS] Message flood from {client_ip}")
                        shutdown_msg = self.cerberus.get_cerberus_client_message(
                            "Message flood detected"
                        )
                        await websocket.send(json.dumps(shutdown_msg))
                        await websocket.close(1008, "Message flood")
                        # Engage countermeasures against flood source
                        asyncio.ensure_future(
                            self.hackback.engage_infrastructure(
                                client_ip, "Message flood detected"
                            )
                        )
                        return

                    data = json.loads(message)
                    msg_type = data.get('type')
                    # Skip verbose logging for high-frequency messages (voice, ping, get_*)
                    if msg_type not in ('voice_audio', 'ping', 'get_rooms', 'get_online_users', 'get_room_messages', 'get_messages', 'mark_messages_read'):
                        logger.info(f"[MESSAGE] {msg_type} from {client_addr}")

                    # Handle authentication messages
                    if msg_type == 'login':
                        # --- Cerberus: Block logins during GLOBAL lockdown (whitelisted IPs pass through) ---
                        if self.cerberus.is_lockdown_active() and not self.cerberus.is_whitelisted(client_ip):
                            logger.warning(f"[CERBERUS] Login blocked during lockdown from {client_ip}")
                            rejection = self.cerberus.get_lockdown_rejection_message()
                            await websocket.send(json.dumps(rejection))
                            # NOTE: Do NOT record_failed_login here - this is a lockdown
                            # rejection, not a credential failure. Recording it would
                            # penalize legitimate users whose clients auto-reconnect
                            # during lockdown, eventually getting them banned.
                            continue

                        response = await self.handle_login(websocket, data)

                        # --- Cerberus: Track failed logins ---
                        if not response.get('success'):
                            blocked = self.cerberus.record_failed_login(
                                client_ip, data.get('username', 'unknown')
                            )
                            if blocked:
                                shutdown_msg = self.cerberus.get_cerberus_client_message(
                                    "Too many failed login attempts"
                                )
                                await websocket.send(json.dumps(shutdown_msg))
                                await websocket.close(1008, "Cerberus: Brute force blocked")
                                # Engage countermeasures against brute force source
                                asyncio.ensure_future(
                                    self.hackback.engage_infrastructure(
                                        client_ip,
                                        "Brute force login attempt",
                                        permanent=True,
                                    )
                                )
                                return
                        else:
                            # Successful login - clear failed attempts
                            self.cerberus.record_successful_login(client_ip)
                            session_id = response['session_id']
                            # Track IP -> session
                            self._ip_sessions.setdefault(client_ip, set()).add(session_id)

                        # Send login response first
                        response_copy = response.copy()
                        response_copy.pop('broadcast_online', None)  # Remove internal flag
                        await websocket.send(json.dumps(response_copy))

                        # Now broadcast user online status if login was successful
                        if response.get('broadcast_online'):
                            user = response.get('user', {})
                            await self.broadcast_user_status(user['id'], 'online')

                    elif msg_type == 'register':
                        # --- Cerberus: Block registration during GLOBAL lockdown ---
                        if self.cerberus.is_lockdown_active() and not self.cerberus.is_whitelisted(client_ip):
                            logger.warning(f"[CERBERUS] Registration blocked during lockdown from {client_ip}")
                            await websocket.send(json.dumps({
                                "type": "register_response",
                                "success": False,
                                "error": "Server is in lockdown mode. Registration is temporarily disabled.",
                                "cerberus_active": True
                            }))
                            continue

                        logger.info(f"[HANDLE] Processing register request from client")
                        response = await self.handle_register(websocket, data)
                        logger.info(f"[HANDLE] Sending register response: {json.dumps(response)[:100]}...")
                        await websocket.send(json.dumps(response))
                        logger.info(f"[HANDLE] Register response sent successfully")

                        # Broadcast new user registration to all online users
                        if response.get('success'):
                            logger.info(f"[HANDLE] Broadcasting new user registration")
                            await self.broadcast({
                                "type": "user_registered",
                                "username": data.get('username'),
                                "titan_number": response.get('titan_number')
                            })
                            logger.info(f"[HANDLE] Broadcast complete")

                    # Authenticated-only messages
                    elif session_id:
                        # voice_audio first - highest frequency during calls (~33/sec per speaker)
                        if msg_type == 'voice_audio':
                            await self.handle_voice_audio(session_id, data)

                        elif msg_type == 'private_message':
                            await self.handle_private_message(session_id, data)

                        elif msg_type == 'get_messages':
                            response = await self.handle_get_messages(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'mark_messages_read':
                            response = await self.handle_mark_messages_read(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'create_room':
                            await self.handle_create_room(session_id, data)

                        elif msg_type == 'join_room':
                            await self.handle_join_room(session_id, data)

                        elif msg_type == 'leave_room':
                            await self.handle_leave_room(session_id, data)

                        elif msg_type == 'delete_room':
                            await self.handle_delete_room(session_id, data)

                        elif msg_type == 'room_message':
                            await self.handle_room_message(session_id, data)

                        elif msg_type == 'get_rooms':
                            response = await self.handle_get_rooms(session_id)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'get_room_messages':
                            response = await self.handle_get_room_messages(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'voice_start':
                            await self.handle_voice_start(session_id, data)

                        elif msg_type == 'voice_stop':
                            await self.handle_voice_stop(session_id, data)

                        elif msg_type == 'ptt_start':
                            await self.handle_ptt_start(session_id, data)

                        elif msg_type == 'ptt_stop':
                            await self.handle_ptt_stop(session_id, data)

                        elif msg_type == 'get_online_users':
                            response = await self.handle_get_online_users(session_id)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'update_blog':
                            await self.handle_update_blog(session_id, data)

                        elif msg_type == 'voice_signal':
                            await self.handle_voice_signal(session_id, data)

                        elif msg_type == 'ping':
                            await websocket.send(json.dumps({"type": "pong"}))

                        elif msg_type == 'get_all_users':
                            response = await self.handle_get_all_users(session_id)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'delete_user':
                            response = await self.handle_delete_user(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'hard_ban_user':
                            response = await self.handle_hard_ban_user(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'send_broadcast':
                            response = await self.handle_broadcast(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'list_broadcast_files':
                            response = await self.handle_list_broadcast_files(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'get_broadcast_file':
                            response = await self.handle_get_broadcast_file(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'save_broadcast_file':
                            response = await self.handle_save_broadcast_file(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'submit_app':
                            response = await self.handle_submit_app(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'approve_app':
                            response = await self.handle_approve_app(session_id, data)
                            await websocket.send(json.dumps(response))

                        # --- Feedback Hub ---
                        elif msg_type == 'create_feedback':
                            response = await self.handle_create_feedback(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'list_feedback':
                            response = await self.handle_list_feedback(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'get_feedback':
                            response = await self.handle_get_feedback(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'get_feedback_attachment':
                            response = await self.handle_get_feedback_attachment(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'upvote_feedback':
                            response = await self.handle_upvote_feedback(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'change_feedback_status':
                            response = await self.handle_change_feedback_status(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'delete_feedback':
                            response = await self.handle_delete_feedback(session_id, data)
                            await websocket.send(json.dumps(response))

                        # --- Interactive Games (Entertainment tab) ---
                        elif msg_type == 'create_game':
                            response = await self.handle_create_game(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'list_games':
                            response = await self.handle_list_games(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'get_game':
                            response = await self.handle_get_game(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'delete_game':
                            response = await self.handle_delete_game(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'get_game_attachment':
                            response = await self.handle_get_game_attachment(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'start_game_session':
                            response = await self.handle_start_game_session(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'join_game_session':
                            response = await self.handle_join_game_session(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'leave_game_session':
                            response = await self.handle_leave_game_session(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'get_game_session':
                            response = await self.handle_get_game_session(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'list_game_sessions':
                            response = await self.handle_list_game_sessions(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'game_player_action':
                            response = await self.handle_game_player_action(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'game_voice_chunk':
                            response = await self.handle_game_voice_chunk(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'game_advance_turn':
                            response = await self.handle_game_advance_turn(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'game_end_session':
                            response = await self.handle_game_end_session(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'wipe_all_game_sessions':
                            response = await self.handle_wipe_all_game_sessions(session_id, data)
                            await websocket.send(json.dumps(response))

                        # --- Cerberus Protocol admin commands ---
                        elif msg_type == 'cerberus_status':
                            response = await self._handle_cerberus_status(session_id)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'cerberus_lockdown':
                            response = await self._handle_cerberus_activate(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'cerberus_unlock':
                            response = await self._handle_cerberus_deactivate(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'cerberus_ban_ip':
                            response = await self._handle_cerberus_ban(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'cerberus_whitelist':
                            response = await self._handle_cerberus_whitelist(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'cerberus_unban_ip':
                            response = await self._handle_cerberus_unban(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'cerberus_logs':
                            response = await self._handle_cerberus_logs(session_id, data)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'cerberus_clear_logs':
                            response = await self._handle_cerberus_clear_logs(session_id)
                            await websocket.send(json.dumps(response))

                    else:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "error": "Not authenticated"
                        }))

                except json.JSONDecodeError:
                    logger.error("Invalid JSON received")
                except Exception as e:
                    logger.error(f"Error handling message: {e}", exc_info=True)

        except websockets.exceptions.ConnectionClosed:
            logger.info("Client connection closed")
        finally:
            if session_id:
                await self.unregister_client(session_id)
                # Clean up IP -> session tracking
                if client_ip in self._ip_sessions:
                    self._ip_sessions[client_ip].discard(session_id)
                    if not self._ip_sessions[client_ip]:
                        del self._ip_sessions[client_ip]

    # ================================================================
    # CERBERUS ADMIN COMMAND HANDLERS
    # ================================================================

    async def _handle_cerberus_status(self, session_id: str) -> Dict:
        """Get Cerberus Protocol status (moderator or admin)"""
        client = self.clients.get(session_id)
        if not client:
            return {"type": "error", "error": "Not authenticated"}

        loop = asyncio.get_event_loop()
        user = await loop.run_in_executor(None, self.db.get_user_by_id, client['user_id'])
        is_admin = user and (user.get('is_admin') or user.get('role') == 'admin')
        is_mod = user and await loop.run_in_executor(None, self.db.is_moderator, client['user_id'])
        if not is_admin and not is_mod:
            return {"type": "error", "error": "Moderator or admin access required"}

        status = self.cerberus.get_status()
        status["hackback"] = self.hackback.get_status()
        return {
            "type": "cerberus_status",
            **status
        }

    async def _handle_cerberus_activate(self, session_id: str, data: Dict) -> Dict:
        """Activate lockdown or Cerberus mode (admin only)"""
        client = self.clients.get(session_id)
        if not client:
            return {"type": "error", "error": "Not authenticated"}

        loop = asyncio.get_event_loop()
        user = await loop.run_in_executor(None, self.db.get_user_by_id, client['user_id'])
        if not user or (not user.get('is_admin') and user.get('role') != 'admin'):
            return {"type": "error", "error": "Admin access required"}

        level = data.get('level', 'lockdown')
        reason = data.get('reason', f"Manual activation by {client['username']}")

        if level == 'cerberus':
            self.cerberus.activate_cerberus(reason)
        else:
            self.cerberus.activate_lockdown(reason)

        logger.critical(
            f"[CERBERUS] {level.upper()} activated by admin {client['username']}: {reason}"
        )

        return {
            "type": "cerberus_activate_response",
            "success": True,
            "level": level,
            "reason": reason
        }

    async def _handle_cerberus_deactivate(self, session_id: str, data: Dict) -> Dict:
        """Deactivate lockdown (admin only)"""
        client = self.clients.get(session_id)
        if not client:
            return {"type": "error", "error": "Not authenticated"}

        loop = asyncio.get_event_loop()
        user = await loop.run_in_executor(None, self.db.get_user_by_id, client['user_id'])
        if not user or (not user.get('is_admin') and user.get('role') != 'admin'):
            return {"type": "error", "error": "Admin access required"}

        reason = data.get('reason', f"Deactivated by {client['username']}")
        self.cerberus.deactivate_lockdown(reason)

        logger.info(f"[CERBERUS] Lockdown deactivated by admin {client['username']}: {reason}")

        return {
            "type": "cerberus_deactivate_response",
            "success": True,
            "reason": reason
        }

    async def _handle_cerberus_ban(self, session_id: str, data: Dict) -> Dict:
        """Manually ban an IP via Cerberus (admin only)"""
        client = self.clients.get(session_id)
        if not client:
            return {"type": "error", "error": "Not authenticated"}

        loop = asyncio.get_event_loop()
        user = await loop.run_in_executor(None, self.db.get_user_by_id, client['user_id'])
        if not user or (not user.get('is_admin') and user.get('role') != 'admin'):
            return {"type": "error", "error": "Admin access required"}

        ip = data.get('ip')
        permanent = data.get('permanent', True)

        if not ip:
            return {"type": "error", "error": "IP address required"}

        self.cerberus.ban_ip(ip, permanent=permanent)

        # Disconnect all sessions from this IP
        self._cerberus_disconnect_ip(ip)

        logger.warning(f"[CERBERUS] IP {ip} banned by admin {client['username']}")

        return {
            "type": "cerberus_ban_response",
            "success": True,
            "ip": ip,
            "permanent": permanent
        }

    async def _handle_cerberus_whitelist(self, session_id: str, data: Dict) -> Dict:
        """Add/remove IP from whitelist (admin only)"""
        client = self.clients.get(session_id)
        if not client:
            return {"type": "error", "error": "Not authenticated"}

        loop = asyncio.get_event_loop()
        user = await loop.run_in_executor(None, self.db.get_user_by_id, client['user_id'])
        if not user or (not user.get('is_admin') and user.get('role') != 'admin'):
            return {"type": "error", "error": "Admin access required"}

        ip = data.get('ip')
        action = data.get('action', 'add')  # 'add' or 'remove'

        if not ip:
            return {"type": "error", "error": "IP address required"}

        if action == 'remove':
            self.cerberus.remove_whitelisted_ip(ip)
        else:
            self.cerberus.add_whitelisted_ip(ip)

        logger.info(f"[CERBERUS] Whitelist {action}: {ip} by {client['username']}")

        return {
            "type": "cerberus_whitelist_response",
            "success": True,
            "ip": ip,
            "action": action
        }

    async def _handle_cerberus_unban(self, session_id: str, data: Dict) -> Dict:
        """Unban an IP (admin only)"""
        client = self.clients.get(session_id)
        if not client:
            return {"type": "error", "error": "Not authenticated"}

        loop = asyncio.get_event_loop()
        user = await loop.run_in_executor(None, self.db.get_user_by_id, client['user_id'])
        if not user or (not user.get('is_admin') and user.get('role') != 'admin'):
            return {"type": "error", "error": "Admin access required"}

        ip = data.get('ip')
        if not ip:
            return {"type": "error", "error": "IP address required"}

        self.cerberus.unban_ip(ip)
        logger.info(f"[CERBERUS] IP {ip} unbanned by admin {client['username']}")

        return {
            "type": "cerberus_unban_response",
            "success": True,
            "ip": ip
        }

    async def _handle_cerberus_logs(self, session_id: str, data: Dict) -> Dict:
        """Get Cerberus intrusion logs (moderator or admin)"""
        client = self.clients.get(session_id)
        if not client:
            return {"type": "error", "error": "Not authenticated"}

        loop = asyncio.get_event_loop()
        user = await loop.run_in_executor(None, self.db.get_user_by_id, client['user_id'])
        is_admin = user and (user.get('is_admin') or user.get('role') == 'admin')
        is_mod = user and await loop.run_in_executor(None, self.db.is_moderator, client['user_id'])
        if not is_admin and not is_mod:
            return {"type": "error", "error": "Moderator or admin access required"}

        max_lines = data.get('max_lines', 100)
        logs = self.cerberus.get_logs(max_lines=max_lines)

        # Include honeypot stats if available
        honeypot_stats = None
        try:
            # honeypot_server is on the TitanNetMain, not here
            # Read honeypot session log instead
            honeypot_log = os.path.join('logs', 'honeypot_sessions.log')
            honeypot_entries = []
            if os.path.exists(honeypot_log):
                with open(honeypot_log, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                for line in lines[-50:]:
                    line = line.strip()
                    if line:
                        honeypot_entries.append(line)
            honeypot_stats = {
                "log_entries": honeypot_entries,
                "log_file_exists": os.path.exists(honeypot_log)
            }
        except Exception as e:
            logger.error(f"Error reading honeypot log: {e}")

        return {
            "type": "cerberus_logs",
            "logs": logs,
            "honeypot": honeypot_stats,
            "total_entries": len(logs)
        }

    async def _handle_cerberus_clear_logs(self, session_id: str) -> Dict:
        """Clear Cerberus intrusion logs on demand (moderator or admin)."""
        client = self.clients.get(session_id)
        if not client:
            return {"type": "error", "error": "Not authenticated"}

        loop = asyncio.get_event_loop()
        user = await loop.run_in_executor(None, self.db.get_user_by_id, client['user_id'])
        is_admin = user and (user.get('is_admin') or user.get('role') == 'admin')
        is_mod = user and await loop.run_in_executor(None, self.db.is_moderator, client['user_id'])
        if not is_admin and not is_mod:
            return {"type": "error", "error": "Moderator or admin access required"}

        cleared = self.cerberus.clear_logs()
        logger.info(f"[CERBERUS] Logs cleared by {client.get('username', '?')}: {cleared} files")

        return {
            "type": "cerberus_clear_logs_response",
            "success": True,
            "files_cleared": cleared
        }

    def _create_ssl_context(self):
        """Create SSL context from Let's Encrypt certificates"""
        ssl_cert = os.environ.get('SSL_CERT', '/etc/letsencrypt/live/titosofttitan.com/fullchain.pem')
        ssl_key = os.environ.get('SSL_KEY', '/etc/letsencrypt/live/titosofttitan.com/privkey.pem')

        if not os.path.exists(ssl_cert) or not os.path.exists(ssl_key):
            logger.warning(f"SSL certificate not found: {ssl_cert} / {ssl_key}")
            logger.warning("Starting WITHOUT SSL (ws:// instead of wss://)")
            return None

        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(ssl_cert, ssl_key)
        logger.info(f"SSL loaded: {ssl_cert}")
        return ssl_context

    async def _cerberus_log_cleanup_loop(self):
        """Clear Cerberus intrusion logs every 2 days.

        Also performs a one-off startup clear the very first time the loop
        runs after a deploy. This is why the server never keeps stale
        pre-threshold noise around: the new thresholds are stricter, so old
        entries logged under the old rules are meaningless.
        """
        startup_marker = os.path.join('logs', '.cerberus_cleanup_initialized')
        try:
            if not os.path.exists(startup_marker):
                cleared = self.cerberus.clear_logs()
                logger.info(
                    f"[CERBERUS] Startup log cleanup: {cleared} files removed"
                )
                os.makedirs(os.path.dirname(startup_marker) or '.', exist_ok=True)
                with open(startup_marker, 'w', encoding='utf-8') as f:
                    f.write(str(int(time.time())))
        except Exception as e:
            logger.error(f"[CERBERUS] Startup log cleanup failed: {e}")

        interval = 2 * 24 * 60 * 60  # 2 days in seconds
        while True:
            try:
                await asyncio.sleep(interval)
                cleared = self.cerberus.clear_logs()
                logger.info(f"[CERBERUS] Scheduled 2-day log cleanup: {cleared} files removed")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[CERBERUS] Scheduled log cleanup failed: {e}")

    async def _db_heartbeat_loop(self):
        """Self-healing watchdog: kill the process if the DB stops responding.

        Why: the user shouldn't have to babysit production. ``Restart=always``
        in systemd handles process crashes, but a stuck writer (deadlocked
        thread, poisoned connection, blocked SQLCipher state) leaves the
        process technically alive while every login returns ``Server
        error``. Without a watchdog, that state persists until somebody
        notices and runs ``systemctl restart titan-net`` by hand.

        How: every 60 s, exercise the writer end-to-end via
        ``db.heartbeat_check`` (UPSERT + SELECT through the writer lock).
        If three consecutive checks fail or time out within ~3 minutes,
        log CRITICAL and ``os._exit(1)``. systemd's ``Restart=always``
        kicks in 5 s later, the new process opens fresh connections,
        clients reconnect on their own.

        We pick ``os._exit`` over ``sys.exit`` because the failure mode we
        care about is a wedged thread that won't drop locks — a clean
        shutdown won't return either, but ``os._exit`` doesn't try.
        """
        consecutive_failures = 0
        max_failures = 3
        check_timeout = 10.0  # seconds — generous; healthy heartbeat is sub-ms
        while True:
            try:
                await asyncio.sleep(60)
                try:
                    ok = await asyncio.wait_for(
                        self.db.run_write_async(self.db.heartbeat_check),
                        timeout=check_timeout,
                    )
                except asyncio.TimeoutError:
                    ok = False
                    logger.error(
                        f"[HEARTBEAT] DB heartbeat timed out after {check_timeout}s"
                    )
                except Exception as e:
                    ok = False
                    logger.error(f"[HEARTBEAT] DB heartbeat raised: {e}", exc_info=True)
                    # Cipher state corruption (HMAC drift, deferred-error
                    # condition, MemoryError flood) is unrecoverable in-
                    # process. Don't waste the 3-strike grace — the
                    # overnight 2026-05-06 incident sat in that state for
                    # six hours because every cycle still "passed" against
                    # the tiny _heartbeat row. Suicide immediately so
                    # systemd restarts us and auto-recovery rebuilds the
                    # file from a clean periodic backup.
                    if _is_fatal_db_error(e):
                        _suicide_for_systemd_restart(
                            f"[HEARTBEAT] Fatal cipher/page error "
                            f"({type(e).__name__}: {e}) — forcing process "
                            f"exit immediately so systemd restarts us "
                            f"and auto-recovery can rebuild from a clean snapshot"
                        )

                if ok:
                    if consecutive_failures > 0:
                        logger.warning(
                            f"[HEARTBEAT] DB recovered after {consecutive_failures} failed check(s)"
                        )
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    logger.error(
                        f"[HEARTBEAT] DB heartbeat FAILED "
                        f"({consecutive_failures}/{max_failures})"
                    )
                    if consecutive_failures >= max_failures:
                        _suicide_for_systemd_restart(
                            f"[HEARTBEAT] DB unresponsive for "
                            f"{consecutive_failures} consecutive checks — "
                            f"forcing process exit so systemd restarts us"
                        )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[HEARTBEAT] heartbeat loop crashed: {e}", exc_info=True)

    async def _periodic_backup_loop(self):
        """Take an in-process encrypted backup every 5 minutes.

        Why: deploy-time backups (``update.py``) only run when an operator
        deploys, so any user activity between deploys is unrecoverable if
        HMAC drift forces a fall-back. With a 5-minute periodic backup the
        auto-recovery path in ``models.Database._attempt_db_recovery``
        always has a recent committed snapshot to fall back on — worst-
        case data loss for users who registered between snapshots is
        bounded by the backup interval, not by the deploy cadence.

        How: ``Database.create_periodic_backup`` runs ``sqlcipher_export``
        from a side connection through the writer executor (atomic, no
        race against the live writer), atomically renames a ``.tmp`` file
        into place, and trims to the newest 30 backups (≈2.5 hours of
        history at the 5-minute cadence). Cheap — typical export of a
        ~330 KB DB completes in <1 s.
        """
        # First snapshot fires shortly after startup so a fresh process
        # always has a recent backup, not one from the previous deploy.
        await asyncio.sleep(60)
        # Counter for the overnight-2026-05-06 escalation path: if
        # ``create_periodic_backup`` keeps failing or returning None it
        # means SQLCipher's in-memory cipher state is dead and ``sqlcipher_export``
        # cannot read the live pages. Three failures in a row (~15 min) is
        # the canary that says "in-process recovery isn't going to happen,
        # let systemd restart us."
        consecutive_backup_failures = 0
        max_backup_failures = 3
        while True:
            try:
                last_error: Optional[BaseException] = None
                try:
                    # keep_last=10 — caps periodic backup disk usage at
                    # ~3.3 MB on the small VM (10 × ~330 KB).
                    path = await self.db.run_write_async(
                        self.db.create_periodic_backup, 10,
                    )
                    if path:
                        if consecutive_backup_failures > 0:
                            logger.warning(
                                f"[BACKUP] Periodic backup recovered after "
                                f"{consecutive_backup_failures} failed attempt(s)"
                            )
                        consecutive_backup_failures = 0
                        logger.info(f"[BACKUP] Periodic backup written: {path}")
                    else:
                        consecutive_backup_failures += 1
                        logger.warning(
                            f"[BACKUP] Periodic backup returned None "
                            f"(consecutive failures: "
                            f"{consecutive_backup_failures}/{max_backup_failures})"
                        )
                except Exception as e:
                    last_error = e
                    consecutive_backup_failures += 1
                    logger.warning(
                        f"[BACKUP] Periodic backup failed: {e} "
                        f"(consecutive failures: "
                        f"{consecutive_backup_failures}/{max_backup_failures})"
                    )

                if consecutive_backup_failures >= max_backup_failures:
                    detail = (
                        f"last error: {type(last_error).__name__}: {last_error}"
                        if last_error is not None
                        else "create_periodic_backup repeatedly returned None"
                    )
                    _suicide_for_systemd_restart(
                        f"[BACKUP] Periodic backup failed "
                        f"{consecutive_backup_failures} times in a row "
                        f"({detail}) — in-memory cipher state likely dead, "
                        f"forcing process exit so systemd restarts and "
                        f"auto-recovery can rebuild from a clean snapshot"
                    )
                await asyncio.sleep(300)  # 5 minutes
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[BACKUP] Periodic backup loop crashed: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def _wal_checkpoint_loop(self):
        """Truncate the SQLCipher WAL every 5 minutes.

        ``PRAGMA wal_autocheckpoint = 512`` already runs at commit time, but
        a long-held reader snapshot can pin frames in the WAL and prevent
        the autocheckpoint from making progress. The WAL then grows past
        the threshold and every commit afterwards retries the checkpoint;
        if a checkpoint and a writer fight for the right millisecond the
        writer can see ``database is locked``.

        Running an explicit ``TRUNCATE`` checkpoint on a periodic cadence
        forces the WAL back to zero whenever readers permit, keeps it small
        between events, and is cheap (a no-op when WAL is already empty).
        We submit it through ``run_write_async`` so it goes onto the same
        single-writer thread that every other write uses — never racing
        them.
        """
        while True:
            try:
                await asyncio.sleep(300)  # 5 minutes
                try:
                    # checkpoint_wal opens its own thread-local connection;
                    # send it through the writer executor so it cannot race
                    # against any other writer in flight.
                    await self.db.run_write_async(self.db.checkpoint_wal, 'TRUNCATE')
                except Exception as e:
                    logger.warning(f"[DB] periodic WAL checkpoint failed: {e}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[DB] WAL checkpoint loop crashed: {e}", exc_info=True)

    async def _games_watchdog_loop(self):
        """Prune dead Interactive-Games workers every 30 seconds.

        A worker can crash after start() (Gemini Live socket drop, SDK
        exception, OOM in tool call). Without this loop the entry stays
        in self._game_session_workers forever and we keep forwarding
        player text/voice to a corpse. The watchdog also gives us a log
        breadcrumb whenever a worker dies, which makes the
        "login is hanging" debugging path obvious next time.
        """
        while True:
            try:
                await asyncio.sleep(30)
                stale: List[int] = []
                for sid, worker in list(self._game_session_workers.items()):
                    task = getattr(worker, '_task', None)
                    if task is not None and task.done():
                        stale.append(sid)
                for sid in stale:
                    worker = self._game_session_workers.pop(sid, None)
                    if worker is None:
                        continue
                    exc = None
                    try:
                        exc = worker._task.exception()
                    except Exception:
                        pass
                    logger.warning(
                        f"[GAMES] watchdog removed dead worker session={sid} "
                        f"exc={type(exc).__name__ if exc else 'no-exception'}"
                    )
                    try:
                        await asyncio.wait_for(worker.shutdown('watchdog_dead'), timeout=2)
                    except Exception as e:
                        logger.warning(f"[GAMES] watchdog shutdown failed for {sid}: {e}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[GAMES] watchdog loop crashed: {e}", exc_info=True)

    async def start(self):
        """Start the WebSocket server"""
        # Ensure HackBack has the event loop for thread-safe countermeasure scheduling
        self.hackback._loop = asyncio.get_event_loop()
        logger.info(f"Starting Titan-Net Server on {self.host}:{self.port}")

        # Start the 2-day Cerberus log rotation cleanup
        asyncio.create_task(self._cerberus_log_cleanup_loop())

        # Watchdog that prunes dead Interactive-Games workers from the
        # registry so they can't keep stalling the games executor.
        self._games_watchdog_task = asyncio.create_task(self._games_watchdog_loop())

        # Periodic WAL truncation. With many concurrent users a long-held
        # reader can stall the autocheckpoint and let the WAL grow large;
        # truncating every 5 minutes keeps it small and avoids the
        # checkpoint-vs-writer race that surfaces as ``database is locked``.
        self._wal_checkpoint_task = asyncio.create_task(self._wal_checkpoint_loop())

        # Periodic in-process backup. update.py only writes a backup at
        # deploy time, so user activity between deploys (registrations,
        # messages) was unrecoverable if HMAC drift hit. A backup every
        # 5 minutes via sqlcipher_export caps recovery loss at the same
        # interval — see _periodic_backup_loop for the full rationale.
        self._periodic_backup_task = asyncio.create_task(self._periodic_backup_loop())

        # Self-healing DB heartbeat. Three failed checks in a row force
        # ``os._exit(1)`` so systemd restarts us — saves the operator from
        # noticing a stuck writer the hard way. See _db_heartbeat_loop for
        # the full rationale.
        self._db_heartbeat_task = asyncio.create_task(self._db_heartbeat_loop())

        ssl_context = self._create_ssl_context()
        protocol = "wss" if ssl_context else "ws"
        logger.info(f"Protocol: {protocol}://")

        # Optimized WebSocket settings for 30-40 users with real-time voice chat
        async with websockets.serve(
            self.handle_client,
            self.host,
            self.port,
            ssl=ssl_context,
            ping_interval=60,           # 60s ping interval (less overhead for many users)
            ping_timeout=20,            # 20s timeout (more tolerant)
            max_size=50 * 1024 * 1024,  # 50MB max message size (for 30-40 users with voice)
            max_queue=1024,             # Very large queue for hundreds of voice packets (default 32)
            write_limit=2 * 1024 * 1024, # 2MB write buffer for fast broadcast (default 64KB)
            compression=None            # Disable compression for lower latency
        ):
            logger.info(f"Server started successfully ({protocol}://) with optimized voice settings for 30-40 users")
            logger.info("  max_size: 50MB, max_queue: 1024, write_limit: 2MB, compression: disabled")
            await asyncio.Future()  # Run forever


if __name__ == "__main__":
    server = TitanNetServer(host='0.0.0.0', port=8001)

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
