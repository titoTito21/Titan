"""
Titan-Net HTTP API Server
Handles file uploads, downloads, and repository management
"""

from aiohttp import web, MultipartReader
import aiohttp_cors
import asyncio
import functools
import logging
import os
import ssl
import json
import hashlib
import base64
import re
from datetime import datetime
from typing import Dict, Optional, Any
import mimetypes
import urllib.parse
import tempfile
from models import Database
from config import Config

# Create logs directory if it doesn't exist
import os
os.makedirs('logs', exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/http_server.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('TitanNetHTTP')


class TitanNetHTTPServer:
    def __init__(self, host: str = '0.0.0.0', port: int = 8000, upload_dir: str = 'uploads',
                 db: Optional[Any] = None, cerberus: Optional[Any] = None,
                 web_root: Optional[str] = None):
        self.host = host
        self.port = port
        self.upload_dir = upload_dir
        # MUST share the websocket server's Database instance. Two separate
        # Database() constructions in the same process means two separate
        # writer locks and two SQLite-level writers racing — the actual root
        # cause of the 2026-05-03 ``database is locked`` outage. The Database
        # class also enforces a per-process singleton internally, so passing
        # ``db`` is belt and braces.
        self.db = db if db is not None else Database()
        # Optional reference to the WS server, set by main.py so that OAuth
        # callbacks (and similar) can push live events to connected clients.
        self.ws_server: Optional[Any] = None
        # Cerberus protection (shared with the WS server). When provided the
        # middleware rejects banned / locked-down IPs before they ever reach
        # a handler — same shielding the desktop client gets over WebSocket.
        self.cerberus = cerberus
        # Optional static web root for the accessible browser portal.
        self.web_root = web_root

        # Create upload directory structure
        os.makedirs(upload_dir, exist_ok=True)
        os.makedirs(os.path.join(upload_dir, 'pending'), exist_ok=True)
        os.makedirs(os.path.join(upload_dir, 'approved'), exist_ok=True)

        middlewares = []
        if self.cerberus is not None:
            middlewares.append(self._cerberus_middleware)
        self.app = web.Application(
            # Cap the whole request body. TCE packages can be large, so this
            # tracks Config.MAX_UPLOAD_SIZE (default 1GB) instead of a
            # hardcoded 100MB. aiohttp rejects anything bigger before it ever
            # reaches handle_upload. The +16MB margin covers multipart framing
            # (boundaries, the metadata part, headers) so a file of exactly
            # MAX_UPLOAD_SIZE bytes isn't rejected by a few bytes of overhead —
            # the precise per-file limit is still enforced in handle_upload.
            client_max_size=Config.MAX_UPLOAD_SIZE + 16 * 1024 * 1024,
            middlewares=middlewares,
        )
        self.setup_routes()
        self.setup_cors()

    @staticmethod
    def _get_client_ip(request: web.Request) -> Optional[str]:
        """Resolve the real client IP behind the Apache reverse proxy."""
        xff = request.headers.get('X-Forwarded-For')
        if xff:
            return xff.split(',')[0].strip()
        real = request.headers.get('X-Real-IP')
        if real:
            return real.strip()
        return request.remote

    @web.middleware
    async def _cerberus_middleware(self, request: web.Request, handler):
        """Reject banned IPs and lockdown traffic before handlers run.

        Mirrors the WS-side gate in server.py so the browser portal gets the
        same Cerberus shielding the desktop client has had.
        """
        ip = self._get_client_ip(request)
        path = request.path or ''

        # OAuth callbacks must always reach us (provider-initiated traffic).
        oauth_path = path.startswith('/oauth/')

        try:
            if ip and not oauth_path:
                if self.cerberus.is_ip_banned(ip):
                    logger.warning(f"[CERBERUS] HTTP blocked banned IP {ip} -> {path}")
                    return web.json_response(
                        {'success': False, 'error': 'Forbidden'}, status=403,
                    )
                if self.cerberus.is_lockdown_active() and not self.cerberus.is_whitelisted(ip):
                    logger.warning(f"[CERBERUS] HTTP lockdown blocked {ip} -> {path}")
                    return web.json_response(
                        {'success': False, 'error': 'Server in lockdown mode'},
                        status=503,
                    )
        except Exception as e:
            logger.error(f"[CERBERUS] middleware check failed for {ip}: {e}")

        return await handler(request)

    def setup_cors(self):
        """Setup CORS for cross-origin requests"""
        cors = aiohttp_cors.setup(self.app, defaults={
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
                allow_methods="*"
            )
        })

        # Configure CORS on all routes
        for route in list(self.app.router.routes()):
            cors.add(route)

    def setup_routes(self):
        """Setup HTTP routes"""
        self.app.router.add_post('/api/repository/upload', self.handle_upload)
        self.app.router.add_get('/api/repository/apps', self.handle_get_apps)
        self.app.router.add_get('/api/repository/apps/{app_id}', self.handle_get_app_details)
        self.app.router.add_get('/api/repository', self.handle_get_repository)
        self.app.router.add_get('/api/repository/{category}', self.handle_get_category)
        self.app.router.add_get('/api/pending', self.handle_get_pending)
        self.app.router.add_post('/api/approve/{app_id}', self.handle_approve)
        self.app.router.add_get('/api/download/{app_id}', self.handle_download)
        self.app.router.add_delete('/api/delete/{app_id}', self.handle_delete)
        self.app.router.add_get('/api/stats', self.handle_stats)
        self.app.router.add_get('/api/search', self.handle_search)

        # Forum routes
        self.app.router.add_post('/api/forum/topics', self.handle_create_topic)
        self.app.router.add_get('/api/forum/topics', self.handle_get_topics)
        self.app.router.add_get('/api/forum/topics/{topic_id}', self.handle_get_topic)
        self.app.router.add_post('/api/forum/topics/{topic_id}/replies', self.handle_add_reply)
        self.app.router.add_get('/api/forum/topics/{topic_id}/replies', self.handle_get_replies)
        self.app.router.add_delete('/api/forum/topics/{topic_id}', self.handle_delete_topic)
        self.app.router.add_get('/api/forum/search', self.handle_search_forum)
        self.app.router.add_get('/api/forum/my_topics', self.handle_get_my_topics)

        # Groups -> Forums -> Threads (Elten-style)
        self.app.router.add_get('/api/groups', self.handle_list_groups)
        self.app.router.add_post('/api/groups', self.handle_create_group)
        self.app.router.add_get('/api/groups/{group_id}', self.handle_get_group)
        self.app.router.add_put('/api/groups/{group_id}', self.handle_update_group)
        self.app.router.add_delete('/api/groups/{group_id}', self.handle_delete_group)
        self.app.router.add_post('/api/groups/{group_id}/join', self.handle_join_group)
        self.app.router.add_post('/api/groups/{group_id}/leave', self.handle_leave_group)
        self.app.router.add_get('/api/groups/{group_id}/members', self.handle_group_members)
        self.app.router.add_post('/api/groups/{group_id}/members/{user_id}/approve', self.handle_approve_member)
        self.app.router.add_post('/api/groups/{group_id}/members/{user_id}/reject', self.handle_reject_member)
        self.app.router.add_post('/api/groups/{group_id}/moderators/{user_id}', self.handle_set_group_moderator)
        self.app.router.add_post('/api/groups/{group_id}/transfer/{user_id}', self.handle_transfer_group_ownership)
        self.app.router.add_post('/api/groups/{group_id}/ban/{user_id}', self.handle_ban_from_group)
        self.app.router.add_post('/api/groups/{group_id}/unban/{user_id}', self.handle_unban_from_group)
        # Forums within a group
        self.app.router.add_get('/api/groups/{group_id}/forums', self.handle_list_group_forums)
        self.app.router.add_post('/api/groups/{group_id}/forums', self.handle_create_group_forum)
        self.app.router.add_delete('/api/forums/{forum_id}', self.handle_delete_group_forum)
        # Cross-group thread move requests
        self.app.router.add_get('/api/forum/move_requests', self.handle_list_move_requests)
        self.app.router.add_post('/api/forum/move_requests/{request_id}/approve', self.handle_approve_move)
        self.app.router.add_post('/api/forum/move_requests/{request_id}/reject', self.handle_reject_move)

        # Titan-Net Extension System (moderator add-ons + two-person approval)
        self.app.router.add_get('/api/extensions', self.handle_list_extensions)
        self.app.router.add_post('/api/extensions', self.handle_submit_extension)
        self.app.router.add_get('/api/extensions/{ext_id}', self.handle_get_extension)
        self.app.router.add_post('/api/extensions/{ext_id}/approve', self.handle_approve_extension)
        self.app.router.add_post('/api/extensions/{ext_id}/reject', self.handle_reject_extension)
        self.app.router.add_get('/api/extensions/{slug}/client', self.handle_extension_client)
        self.app.router.add_get('/api/extensions/{slug}/data/{key}', self.handle_extension_data_get)
        self.app.router.add_put('/api/extensions/{slug}/data/{key}', self.handle_extension_data_set)
        # Extension assets (server-streamed sounds / TTS / languages)
        self.app.router.add_post('/api/extensions/{ext_id}/assets', self.handle_add_extension_asset)
        self.app.router.add_get('/api/extensions/{slug}/assets', self.handle_list_extension_assets)
        self.app.router.add_get('/api/extensions/{slug}/asset/{kind}/{name}', self.handle_get_extension_asset)

        # Curated moderation capability extensions build on (server-enforced).
        self.app.router.add_post('/api/moderation/jail', self.handle_jail_user)
        self.app.router.add_post('/api/moderation/release', self.handle_release_user)

        # User role management routes
        # NOTE: '/api/users/set_developer' was REMOVED (privilege-escalation
        # vulnerability — any authenticated user could self-promote to the
        # developer role). Roles are assigned only by an existing developer
        # via /api/moderation/promote.
        self.app.router.add_get('/api/users/role', self.handle_get_user_role)
        self.app.router.add_get('/api/users/all', self.handle_get_all_users)

        # Moderation routes
        self.app.router.add_post('/api/moderation/promote', self.handle_promote_moderator)
        self.app.router.add_post('/api/moderation/demote', self.handle_demote_moderator)
        self.app.router.add_get('/api/moderation/moderators', self.handle_get_moderators)
        self.app.router.add_post('/api/moderation/change_password', self.handle_admin_change_password)

        # Account email + password recovery routes
        self.app.router.add_post('/api/account/email', self.handle_set_account_email)
        self.app.router.add_get('/api/account/email', self.handle_get_account_email)
        self.app.router.add_post('/api/account/verify_email', self.handle_verify_email)
        self.app.router.add_post('/api/auth/forgot_password', self.handle_forgot_password)
        self.app.router.add_post('/api/auth/reset_password', self.handle_reset_password)

        # User mailbox routes
        self.app.router.add_get('/api/mail/inbox', self.handle_mail_inbox)
        self.app.router.add_get('/api/mail/sent', self.handle_mail_sent)
        self.app.router.add_get('/api/mail/{mail_id}', self.handle_mail_get)
        self.app.router.add_post('/api/mail/{mail_id}/read', self.handle_mail_mark_read)
        self.app.router.add_delete('/api/mail/{mail_id}', self.handle_mail_delete)
        self.app.router.add_post('/api/mail/send', self.handle_mail_send)
        # Internal: Postfix delivery pipe ingests inbound mail here.
        self.app.router.add_post('/api/mail/incoming', self.handle_mail_incoming)

        # Ban system routes
        self.app.router.add_post('/api/moderation/ban/room', self.handle_ban_from_room)
        self.app.router.add_post('/api/moderation/ban/global', self.handle_ban_globally)
        self.app.router.add_post('/api/moderation/ban/hard', self.handle_ban_hard)
        self.app.router.add_post('/api/moderation/ban/forum', self.handle_ban_from_forum)
        self.app.router.add_post('/api/moderation/unban/room', self.handle_unban_from_room)
        self.app.router.add_post('/api/moderation/unban/global', self.handle_unban_globally)
        self.app.router.add_post('/api/moderation/unban/forum', self.handle_unban_from_forum)
        self.app.router.add_get('/api/moderation/ban/check/{user_id}', self.handle_check_ban_status)

        # App repository moderation routes
        self.app.router.add_post('/api/repository/apps/{app_id}/reject', self.handle_reject_app)
        self.app.router.add_get('/api/repository/apps/pending', self.handle_get_pending_apps)
        self.app.router.add_post('/api/repository/apps/{app_id}/approve', self.handle_approve_app)
        # TODO: handle_update_app not yet implemented
        # self.app.router.add_post('/api/repository/apps/{app_id}/update', self.handle_update_app)

        # Forum moderation routes
        self.app.router.add_post('/api/forum/topics/{topic_id}/lock', self.handle_lock_topic)
        self.app.router.add_post('/api/forum/topics/{topic_id}/unlock', self.handle_unlock_topic)
        self.app.router.add_post('/api/forum/topics/{topic_id}/pin', self.handle_pin_topic)
        self.app.router.add_post('/api/forum/topics/{topic_id}/unpin', self.handle_unpin_topic)
        self.app.router.add_delete('/api/forum/replies/{reply_id}', self.handle_delete_reply)
        self.app.router.add_put('/api/forum/replies/{reply_id}', self.handle_edit_reply)
        self.app.router.add_post('/api/forum/topics/{topic_id}/move', self.handle_move_topic)
        self.app.router.add_post('/api/forum/topics/{topic_id}/mark_read', self.handle_mark_topic_read)

        # What's New route
        self.app.router.add_get('/api/whats_new', self.handle_whats_new)

        # Room moderation routes
        self.app.router.add_post('/api/rooms/{room_id}/kick', self.handle_kick_user)
        self.app.router.add_post('/api/rooms/{room_id}/ban', self.handle_ban_user)
        self.app.router.add_post('/api/rooms/{room_id}/unban', self.handle_unban_user)
        self.app.router.add_delete('/api/rooms/messages/{message_id}', self.handle_delete_message)
        self.app.router.add_delete('/api/rooms/{room_id}/moderate', self.handle_delete_room)

        # User sound (business card) routes
        self.app.router.add_post('/api/users/sounds/upload', self.handle_user_sound_upload)
        self.app.router.add_get('/api/users/sounds/{username}/{sound_type}', self.handle_get_user_sound)

        # OAuth proxy routes (Spotify, Allegro, ...)
        self.app.router.add_get('/oauth/{provider}/start', self.handle_oauth_start)
        self.app.router.add_get('/oauth/{provider}/callback', self.handle_oauth_callback)
        self.app.router.add_get('/api/oauth/{provider}/token', self.handle_oauth_get_token)
        self.app.router.add_get('/api/oauth/{provider}/status', self.handle_oauth_status)
        self.app.router.add_delete('/api/oauth/{provider}', self.handle_oauth_disconnect)

        # Static accessible web portal (mirrors the desktop UI in a browser).
        # Mounted at /titannet/ to match the public URL — Apache also serves
        # this prefix directly; the aiohttp route is a fallback so the portal
        # still works if Apache config has not been updated yet.
        if self.web_root and os.path.isdir(self.web_root):
            async def _serve_titannet_index(request: web.Request) -> web.Response:
                idx = os.path.join(self.web_root, 'index.html')
                if os.path.isfile(idx):
                    return web.FileResponse(idx)
                return web.Response(status=404, text='Not found')

            # /titannet (no trailing slash) MUST 301 to /titannet/ — otherwise
            # the browser stays at /titannet and every relative link/sound
            # in the page resolves against the document root, producing 404s
            # for login.html, repository.html, sounds/*.ogg, etc.
            async def _redirect_titannet(request: web.Request) -> web.Response:
                raise web.HTTPMovedPermanently(location='/titannet/')

            self.app.router.add_get('/titannet', _redirect_titannet)
            self.app.router.add_get('/titannet/', _serve_titannet_index)
            self.app.router.add_static('/titannet/', self.web_root, show_index=False)

    def verify_token(self, request: web.Request) -> Optional[Dict]:
        """Authenticate a request via its Bearer token.

        Tokens are HMAC-signed and role-bound (auth_tokens). A signed token that
        fails verification is a forgery/tamper attempt and is reported to
        Cerberus. Legacy base64("id:username") tokens are accepted ONLY while
        Config.LEGACY_TOKENS is on (rollout grace); otherwise they are treated
        as forged. The user's role/is_admin is always taken from the DATABASE,
        never from the token, so privileges cannot be spoofed and demotions
        take effect immediately.
        """
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return None
        token = auth_header[7:]
        ip = None
        try:
            ip = self._get_client_ip(request)
        except Exception:
            ip = None

        try:
            import auth_tokens
            from config import Config

            if auth_tokens.looks_like_signed(token):
                payload = auth_tokens.verify(token)
                if not payload:
                    # Valid-looking signed token that fails signature/expiry =
                    # tamper/forgery attempt.
                    self._note_forged_token(ip, "invalid signed token")
                    return None
                user = self.db.get_user_by_id(int(payload['uid']))
                if not user or user['username'] != payload.get('un'):
                    self._note_forged_token(ip, "signed token user mismatch")
                    return None
                return self._auth_user_dict(user)

            # --- Legacy base64("id:username") token ---
            if not Config.LEGACY_TOKENS:
                # Signed tokens are mandatory: a legacy token is now an
                # impersonation attempt (anyone can craft one).
                self._note_forged_token(ip, "legacy token rejected (strict mode)")
                return None
            import base64
            decoded = base64.b64decode(token).decode('utf-8')
            user_id_str, username = decoded.split(':', 1)
            user_id = int(user_id_str)
            user = self.db.get_user_by_id(user_id)
            if not user or user['username'] != username:
                self._note_forged_token(ip, f"legacy token invalid user {user_id}")
                return None
            return self._auth_user_dict(user)
        except (ValueError, TypeError, KeyError):
            self._note_forged_token(ip, "malformed token")
            return None
        except Exception as e:
            logger.error(f"Token verification error: {e}")
            return None

    def _auth_user_dict(self, user: Dict) -> Dict:
        """Normalize an authenticated user, with role/is_admin from the DB."""
        return {
            'id': user['id'],
            'username': user['username'],
            'is_admin': bool(user.get('is_admin', False)),
            'role': user.get('role') or ('admin' if user.get('is_admin') else 'user'),
        }

    def _note_forged_token(self, ip: Optional[str], reason: str):
        """Report a forged/invalid token to Cerberus (impersonation signal)."""
        logger.warning(f"Token verification failed from {ip}: {reason}")
        try:
            if self.cerberus is not None and ip:
                self.cerberus.record_forged_token(ip, reason)
        except Exception as e:
            logger.error(f"record_forged_token failed: {e}")

    def verify_admin(self, user_id: int) -> bool:
        """Verify if user is admin"""
        user = self.db.get_user_by_id(user_id)
        return user and user.get('is_admin', False)

    async def handle_upload(self, request: web.Request) -> web.Response:
        """Handle file upload to repository.

        The file part is streamed to a temp file on disk in chunks rather
        than buffered fully in memory. This is what makes large (up to
        Config.MAX_UPLOAD_SIZE, default 1GB) TCE packages uploadable without
        the server allocating a gigabyte+ of RAM per concurrent upload. The
        SHA-256 hash and byte count are computed incrementally while writing.
        """
        MAX_FILE_SIZE = Config.MAX_UPLOAD_SIZE
        # 4 MB read chunks: large enough that per-chunk overhead is negligible
        # for a 1GB file, small enough to keep memory flat.
        CHUNK_SIZE = 4 * 1024 * 1024
        ALLOWED_EXTENSIONS = ('.tcepackage', '.zip', '.7z')

        temp_path = None
        try:
            # Verify authentication
            user = self.verify_token(request)
            if not user:
                return web.json_response({
                    'success': False,
                    'error': 'Authentication required'
                }, status=401)

            # Check Content-Length before reading
            content_length = request.content_length
            if content_length and content_length > MAX_FILE_SIZE:
                return web.json_response({
                    'success': False,
                    'error': f'File too large. Max size: {MAX_FILE_SIZE} bytes'
                }, status=413)

            reader = await request.multipart()

            metadata = {}
            filename = None
            file_ext = None
            file_size = 0
            file_hash = None

            pending_dir = os.path.join(self.upload_dir, 'pending')

            async for part in reader:
                if part.name == 'metadata':
                    metadata_text = await part.text()
                    metadata = json.loads(metadata_text)
                elif part.name == 'file':
                    if not part.filename:
                        continue

                    # Sanitize filename and validate extension BEFORE writing
                    # a single byte, so a rejected type never touches disk.
                    filename = re.sub(r'[^a-zA-Z0-9._-]', '_', part.filename)
                    file_ext = os.path.splitext(filename)[1].lower()
                    # Whitelist allowed package extensions. The repository is
                    # for TCE data packages — never raw executables. .exe /
                    # .msi / .bat / .ps1 / .sh / .dll / etc. are rejected up
                    # front so an attacker cannot smuggle a binary through.
                    if file_ext not in ALLOWED_EXTENSIONS:
                        return web.json_response({
                            'success': False,
                            'error': (
                                f'Invalid file type: {file_ext or "(no extension)"}. '
                                f'Allowed: {", ".join(ALLOWED_EXTENSIONS)}'
                            )
                        }, status=400)

                    # Stream the part to a temp file, hashing as we go.
                    hasher = hashlib.sha256()
                    fd, temp_path = tempfile.mkstemp(suffix='.part', dir=pending_dir)
                    oversize = False
                    with os.fdopen(fd, 'wb') as out:
                        while True:
                            chunk = await part.read_chunk(CHUNK_SIZE)
                            if not chunk:
                                break
                            file_size += len(chunk)
                            if file_size > MAX_FILE_SIZE:
                                oversize = True
                                break
                            hasher.update(chunk)
                            out.write(chunk)

                    if oversize:
                        try:
                            os.remove(temp_path)
                        except OSError:
                            pass
                        temp_path = None
                        return web.json_response({
                            'success': False,
                            'error': f'File too large. Max size: {MAX_FILE_SIZE} bytes'
                        }, status=413)

                    file_hash = hasher.hexdigest()

            if not temp_path or not filename or file_size == 0:
                return web.json_response({
                    'success': False,
                    'error': 'File data required'
                }, status=400)

            # Validate required fields
            required_fields = ['name', 'description', 'category', 'version']
            for field in required_fields:
                if field not in metadata:
                    return web.json_response({
                        'success': False,
                        'error': f'Missing required field: {field}'
                    }, status=400)

            # Validate category
            valid_categories = [
                'application', 'component', 'sound_theme',
                'game', 'tce_package', 'language_pack'
            ]
            if metadata['category'] not in valid_categories:
                return web.json_response({
                    'success': False,
                    'error': f'Invalid category. Must be one of: {", ".join(valid_categories)}'
                }, status=400)

            # Move the temp file into place under its content-hash name.
            stored_filename = f"{file_hash}{file_ext}"
            file_path = os.path.join(pending_dir, stored_filename)
            try:
                os.replace(temp_path, file_path)
                temp_path = None
            except OSError as e:
                logger.error(f"Failed to store uploaded file: {e}")
                return web.json_response({
                    'success': False,
                    'error': 'Failed to save file'
                }, status=500)

            # Add to database (writer executor — keeps the aiohttp loop responsive
            # while the @_serialized_write retry/backoff runs on db-writer thread).
            app_id = await self.db.run_write_async(
                self.db.add_app_to_repository,
                metadata['name'], metadata['description'], metadata['category'],
                metadata['version'], user['id'], file_path, file_size, metadata,
            )

            logger.info(f"File uploaded: {metadata['name']} by {user['username']} (ID: {app_id})")

            return web.json_response({
                'success': True,
                'app_id': app_id,
                'message': 'File uploaded successfully. Pending admin approval.'
            })

        except Exception as e:
            logger.error(f"Upload error: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)
        finally:
            # Never leave a half-written .part file behind on any error path.
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    async def handle_get_apps(self, request: web.Request) -> web.Response:
        """Get apps from repository with filters"""
        try:
            status = request.query.get('status')  # 'approved', 'pending', or None for all
            category = request.query.get('category')

            # Validate and parse limit
            try:
                limit = int(request.query.get('limit', 100))
                if limit < 1 or limit > 1000:
                    limit = 100
            except (ValueError, TypeError):
                limit = 100

            conn = self.db.get_connection()
            cursor = conn.cursor()

            # Build query based on filters
            query = """
                SELECT ar.*, u.username as uploader_username
                FROM app_repository ar
                JOIN users u ON ar.author_id = u.id
                WHERE 1=1
            """
            params = []

            if status == 'approved':
                query += " AND ar.approved = 1"
            elif status == 'pending':
                query += " AND ar.approved = 0"
            # If status is None, show all

            if category:
                query += " AND ar.category = ?"
                params.append(category)

            query += " ORDER BY ar.uploaded_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            apps = [dict(row) for row in cursor.fetchall()]

            # Remove file paths from response
            for app in apps:
                app.pop('file_path', None)

            conn.close()

            return web.json_response({
                'success': True,
                'apps': apps
            })

        except Exception as e:
            logger.error(f"Get apps error: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    async def handle_get_app_details(self, request: web.Request) -> web.Response:
        """Get details of a specific app"""
        try:
            app_id = int(request.match_info['app_id'])

            conn = self.db.get_connection()
            cursor = conn.cursor()

            # Get app with author username
            cursor.execute("""
                SELECT ar.*, u.username as uploader_username
                FROM app_repository ar
                JOIN users u ON ar.author_id = u.id
                WHERE ar.id = ?
            """, (app_id,))

            app = cursor.fetchone()
            conn.close()

            if not app:
                return web.json_response({
                    'success': False,
                    'error': 'App not found'
                }, status=404)

            app_dict = dict(app)
            # Remove file path for security
            app_dict.pop('file_path', None)

            # Best-effort: mark this app as seen for the requesting user so it
            # clears from their What's New (new apps / app updates). Never let a
            # failure here break the details response.
            try:
                loop = asyncio.get_event_loop()
                user = await loop.run_in_executor(None, self.verify_token, request)
                if user:
                    await loop.run_in_executor(
                        None, self.db.mark_app_as_seen, user['id'], app_id
                    )
            except Exception as seen_err:
                logger.warning(f"Could not mark app {app_id} as seen: {seen_err}")

            return web.json_response({
                'success': True,
                'app': app_dict
            })

        except Exception as e:
            logger.error(f"Get app details error: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    async def handle_get_repository(self, request: web.Request) -> web.Response:
        """Get all approved apps from repository"""
        try:
            loop = asyncio.get_event_loop()
            apps = await loop.run_in_executor(None, self.db.get_approved_apps)

            # Remove file paths from response
            for app in apps:
                app.pop('file_path', None)

            return web.json_response({
                'success': True,
                'apps': apps
            })

        except Exception as e:
            logger.error(f"Get repository error: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    async def handle_get_category(self, request: web.Request) -> web.Response:
        """Get apps by category"""
        try:
            category = request.match_info['category']
            loop = asyncio.get_event_loop()
            apps = await loop.run_in_executor(
                None, lambda: self.db.get_approved_apps(category=category)
            )

            # Remove file paths from response
            for app in apps:
                app.pop('file_path', None)

            return web.json_response({
                'success': True,
                'category': category,
                'apps': apps
            })

        except Exception as e:
            logger.error(f"Get category error: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    async def handle_get_pending(self, request: web.Request) -> web.Response:
        """Get pending apps (admin only)"""
        try:
            # Verify admin
            user = self.verify_token(request)
            if not user:
                return web.json_response({
                    'success': False,
                    'error': 'Authentication required'
                }, status=401)

            if not self.verify_admin(user['id']):
                return web.json_response({
                    'success': False,
                    'error': 'Admin access required'
                }, status=403)

            loop = asyncio.get_event_loop()
            apps = await loop.run_in_executor(None, self.db.get_pending_apps)

            # Remove file paths from response
            for app in apps:
                app.pop('file_path', None)

            return web.json_response({
                'success': True,
                'apps': apps
            })

        except Exception as e:
            logger.error(f"Get pending error: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    async def handle_approve(self, request: web.Request) -> web.Response:
        """Approve pending app (admin only)"""
        try:
            # Verify admin
            user = self.verify_token(request)
            if not user:
                return web.json_response({
                    'success': False,
                    'error': 'Authentication required'
                }, status=401)

            if not self.verify_admin(user['id']):
                return web.json_response({
                    'success': False,
                    'error': 'Admin access required'
                }, status=403)

            app_id = int(request.match_info['app_id'])

            # Use transaction to prevent race conditions
            conn = self.db.get_connection()
            try:
                cursor = conn.cursor()

                # Start transaction
                cursor.execute("BEGIN IMMEDIATE")

                # Get app info with lock
                cursor.execute("SELECT file_path, approved FROM app_repository WHERE id = ?", (app_id,))
                app = cursor.fetchone()

                if not app:
                    conn.rollback()
                    return web.json_response({
                        'success': False,
                        'error': 'App not found'
                    }, status=404)

                # Check if already approved
                if app['approved']:
                    conn.rollback()
                    return web.json_response({
                        'success': False,
                        'error': 'App already approved'
                    }, status=400)

                # Move file from pending to approved (atomic operation)
                old_path = app['file_path']
                if os.path.exists(old_path):
                    filename = os.path.basename(old_path)
                    new_path = os.path.join(self.upload_dir, 'approved', filename)

                    try:
                        os.rename(old_path, new_path)
                    except OSError as e:
                        conn.rollback()
                        logger.error(f"Failed to move file: {e}")
                        return web.json_response({
                            'success': False,
                            'error': 'Failed to move file'
                        }, status=500)

                    # Update database with new path
                    cursor.execute("UPDATE app_repository SET file_path = ? WHERE id = ?", (new_path, app_id))

                # Approve app. Sync call is intentional here: we are inside
                # a manual ``BEGIN IMMEDIATE`` transaction on the asyncio
                # thread's SQLCipher connection, and ``approve_app`` uses
                # the same thread-local connection. Routing it through the
                # writer executor would open a second connection that
                # would race the in-flight transaction and time out on
                # SQLite-level lock contention.
                success = self.db.approve_app(app_id, user['id'])

                if success:
                    conn.commit()
                else:
                    conn.rollback()
                    return web.json_response({
                        'success': False,
                        'error': 'Failed to approve app'
                    }, status=500)

            except Exception as e:
                conn.rollback()
                raise
            finally:
                conn.close()

            # Return success after commit
            success = True

            if success:
                logger.info(f"App {app_id} approved by {user['username']}")
                return web.json_response({
                    'success': True,
                    'message': 'App approved successfully'
                })
            else:
                return web.json_response({
                    'success': False,
                    'error': 'Failed to approve app'
                }, status=500)

        except Exception as e:
            logger.error(f"Approve error: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    async def handle_download(self, request: web.Request) -> web.Response:
        """Download app file"""
        try:
            app_id = int(request.match_info['app_id'])

            # Get app info
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT file_path, name, approved
                FROM app_repository WHERE id = ?
            """, (app_id,))
            app = cursor.fetchone()
            conn.close()

            if not app:
                return web.json_response({
                    'success': False,
                    'error': 'App not found'
                }, status=404)

            file_path = app['file_path']
            if not os.path.exists(file_path):
                return web.json_response({
                    'success': False,
                    'error': 'File not found'
                }, status=404)

            # Increment download counter (only for approved apps)
            if app['approved']:
                await self.db.run_write_async(self.db.increment_app_downloads, app_id)

            # Determine content type
            content_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'

            # Build the download filename: <app name>.<original extension>.
            # Falls back to the stored file's basename when name/ext are missing.
            ext = os.path.splitext(file_path)[1]
            raw_name = (app['name'] or os.path.splitext(os.path.basename(file_path))[0] or 'download')
            safe_name = re.sub(r'[\\/:*?"<>|\r\n]+', '_', raw_name).strip() or 'download'
            if ext and not safe_name.lower().endswith(ext.lower()):
                download_name = f"{safe_name}{ext}"
            else:
                download_name = safe_name or os.path.basename(file_path)

            # RFC 5987 filename* for non-ASCII names + plain filename fallback.
            ascii_fallback = re.sub(r'[^\x20-\x7e]+', '_', download_name)
            quoted = urllib.parse.quote(download_name, safe='')
            disposition = (
                f'attachment; filename="{ascii_fallback}"; '
                f"filename*=UTF-8''{quoted}"
            )

            headers = {
                'Content-Disposition': disposition,
                'Content-Type': content_type,
                'X-App-Approved': '1' if app['approved'] else '0'  # Custom header for client
            }

            # Send file (works for both approved and pending)
            return web.FileResponse(file_path, headers=headers)

        except Exception as e:
            logger.error(f"Download error: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    async def handle_delete(self, request: web.Request) -> web.Response:
        """Delete app (admin or author only)"""
        try:
            # Verify authentication
            user = self.verify_token(request)
            if not user:
                return web.json_response({
                    'success': False,
                    'error': 'Authentication required'
                }, status=401)

            app_id = int(request.match_info['app_id'])

            # Get app info
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT file_path, author_id
                FROM app_repository WHERE id = ?
            """, (app_id,))
            app = cursor.fetchone()

            if not app:
                conn.close()
                return web.json_response({
                    'success': False,
                    'error': 'App not found'
                }, status=404)

            # Check permissions
            is_admin = self.verify_admin(user['id'])
            is_author = app['author_id'] == user['id']

            if not (is_admin or is_author):
                conn.close()
                return web.json_response({
                    'success': False,
                    'error': 'Permission denied'
                }, status=403)

            # Close the read-only fetch connection before any writes.
            conn.close()

            # Delete file
            file_path = app['file_path']
            if os.path.exists(file_path):
                os.remove(file_path)

            # Delete from database via the writer executor (replaces the
            # bare cursor.execute that bypassed _serialized_write).
            await self.db.run_write_async(self.db.delete_app_from_repository, app_id)

            logger.info(f"App {app_id} deleted by {user['username']}")

            return web.json_response({
                'success': True,
                'message': 'App deleted successfully'
            })

        except Exception as e:
            logger.error(f"Delete error: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    async def handle_stats(self, request: web.Request) -> web.Response:
        """Get repository statistics"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()

            # Get total counts
            cursor.execute("SELECT COUNT(*) as total FROM app_repository WHERE approved = 1")
            total_apps = cursor.fetchone()['total']

            cursor.execute("SELECT COUNT(*) as total FROM app_repository WHERE approved = 0")
            pending_apps = cursor.fetchone()['total']

            cursor.execute("SELECT SUM(downloads) as total FROM app_repository WHERE approved = 1")
            total_downloads = cursor.fetchone()['total'] or 0

            # Get category counts
            cursor.execute("""
                SELECT category, COUNT(*) as count
                FROM app_repository WHERE approved = 1
                GROUP BY category
            """)
            categories = {row['category']: row['count'] for row in cursor.fetchall()}

            conn.close()

            return web.json_response({
                'success': True,
                'stats': {
                    'total_apps': total_apps,
                    'pending_apps': pending_apps,
                    'total_downloads': total_downloads,
                    'categories': categories
                }
            })

        except Exception as e:
            logger.error(f"Stats error: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    async def handle_search(self, request: web.Request) -> web.Response:
        """Search repository"""
        try:
            query = request.query.get('q', '')
            category = request.query.get('category')

            if not query:
                return web.json_response({
                    'success': False,
                    'error': 'Search query required'
                }, status=400)

            conn = self.db.get_connection()
            cursor = conn.cursor()

            if category:
                cursor.execute("""
                    SELECT ar.*, u.username as author_username
                    FROM app_repository ar
                    JOIN users u ON ar.author_id = u.id
                    WHERE ar.approved = 1 AND ar.category = ?
                      AND (ar.name LIKE ? OR ar.description LIKE ?)
                    ORDER BY ar.uploaded_at DESC
                """, (category, f'%{query}%', f'%{query}%'))
            else:
                cursor.execute("""
                    SELECT ar.*, u.username as author_username
                    FROM app_repository ar
                    JOIN users u ON ar.author_id = u.id
                    WHERE ar.approved = 1
                      AND (ar.name LIKE ? OR ar.description LIKE ?)
                    ORDER BY ar.uploaded_at DESC
                """, (f'%{query}%', f'%{query}%'))

            apps = [dict(row) for row in cursor.fetchall()]

            # Remove file paths
            for app in apps:
                app.pop('file_path', None)

            conn.close()

            return web.json_response({
                'success': True,
                'query': query,
                'apps': apps
            })

        except Exception as e:
            logger.error(f"Search error: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    # Forum handlers

    async def handle_create_topic(self, request: web.Request) -> web.Response:
        """Create new forum topic"""
        try:
            # Verify authentication
            user = self.verify_token(request)
            if not user:
                return web.json_response({
                    'success': False,
                    'error': 'Authentication required'
                }, status=401)

            data = await request.json()
            title = data.get('title', '').strip()
            content = data.get('content', '').strip()
            category = data.get('category', 'general')
            forum_id = data.get('forum_id')
            try:
                forum_id = int(forum_id) if forum_id is not None else None
            except (ValueError, TypeError):
                forum_id = None

            if not title or not content:
                return web.json_response({
                    'success': False,
                    'error': 'Title and content required'
                }, status=400)

            # When posting into a group forum, ensure the author is allowed to
            # (active member and not banned from that group).
            if forum_id is not None:
                loop = asyncio.get_event_loop()
                forum = await loop.run_in_executor(None, self.db.get_group_forum, forum_id)
                if not forum:
                    return web.json_response({'success': False, 'error': 'Forum not found'}, status=404)
                group_id = forum['group_id']
                banned = await loop.run_in_executor(None, self.db.is_user_banned_from_group, group_id, user['id'])
                if banned:
                    return web.json_response({'success': False, 'error': 'You are banned from this group'}, status=403)
                role = await loop.run_in_executor(None, self.db.get_group_role, group_id, user['id'])
                is_admin = user.get('is_admin')
                if not role and not is_admin:
                    return web.json_response({'success': False, 'error': 'Join the group to post'}, status=403)

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.db.create_forum_topic, title, content, user['id'], category, forum_id
            )

            logger.info(f"Forum topic created: '{title}' by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Create topic error: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    async def handle_get_topics(self, request: web.Request) -> web.Response:
        """Get forum topics - non-blocking DB"""
        try:
            category = request.query.get('category')
            forum_id = request.query.get('forum_id')
            try:
                forum_id = int(forum_id) if forum_id is not None else None
            except (ValueError, TypeError):
                forum_id = None

            # Validate limit parameter
            try:
                limit = int(request.query.get('limit', 50))
                if limit < 1 or limit > 1000:
                    limit = 50
            except (ValueError, TypeError):
                limit = 50

            # Get user_id for new replies detection
            loop = asyncio.get_event_loop()
            user = await loop.run_in_executor(None, self.verify_token, request)
            user_id = user['id'] if user else None

            topics = await loop.run_in_executor(
                None, self.db.get_forum_topics, category, limit, user_id, forum_id
            )

            return web.json_response({
                'success': True,
                'topics': topics
            })

        except Exception as e:
            logger.error(f"Get topics error: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    async def handle_get_topic(self, request: web.Request) -> web.Response:
        """Get single topic details - non-blocking DB"""
        try:
            topic_id = int(request.match_info['topic_id'])

            loop = asyncio.get_event_loop()
            topic = await loop.run_in_executor(None, self.db.get_forum_topic, topic_id)

            if not topic:
                return web.json_response({
                    'success': False,
                    'error': 'Topic not found'
                }, status=404)

            return web.json_response({
                'success': True,
                'topic': topic
            })

        except Exception as e:
            logger.error(f"Get topic error: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    async def handle_add_reply(self, request: web.Request) -> web.Response:
        """Add reply to topic"""
        try:
            # Verify authentication
            user = self.verify_token(request)
            if not user:
                return web.json_response({
                    'success': False,
                    'error': 'Authentication required'
                }, status=401)

            topic_id = int(request.match_info['topic_id'])
            data = await request.json()
            content = data.get('content', '').strip()

            if not content:
                return web.json_response({
                    'success': False,
                    'error': 'Content required'
                }, status=400)

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.db.add_forum_reply, topic_id, user['id'], content
            )

            if result.get('success'):
                logger.info(f"Reply added to topic {topic_id} by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Add reply error: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    async def handle_get_replies(self, request: web.Request) -> web.Response:
        """Get replies for topic"""
        try:
            topic_id = int(request.match_info['topic_id'])

            # Validate limit parameter
            try:
                limit = int(request.query.get('limit', 100))
                if limit < 1 or limit > 1000:
                    limit = 100
            except (ValueError, TypeError):
                limit = 100

            loop = asyncio.get_event_loop()
            replies = await loop.run_in_executor(
                None, self.db.get_forum_replies, topic_id, limit
            )

            return web.json_response({
                'success': True,
                'replies': replies
            })

        except Exception as e:
            logger.error(f"Get replies error: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    async def handle_delete_topic(self, request: web.Request) -> web.Response:
        """Delete forum topic"""
        try:
            # Verify authentication
            user = self.verify_token(request)
            if not user:
                return web.json_response({
                    'success': False,
                    'error': 'Authentication required'
                }, status=401)

            topic_id = int(request.match_info['topic_id'])

            success = await self.db.run_write_async(self.db.delete_forum_topic, topic_id, user['id'])

            if success:
                logger.info(f"Topic {topic_id} deleted by {user['username']}")
                return web.json_response({
                    'success': True,
                    'message': 'Topic deleted successfully'
                })
            else:
                return web.json_response({
                    'success': False,
                    'error': 'Permission denied or topic not found'
                }, status=403)

        except Exception as e:
            logger.error(f"Delete topic error: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    async def handle_search_forum(self, request: web.Request) -> web.Response:
        """Search forum"""
        try:
            query = request.query.get('q', '').strip()
            category = request.query.get('category')

            # Validate limit parameter
            try:
                limit = int(request.query.get('limit', 50))
                if limit < 1 or limit > 1000:
                    limit = 50
            except (ValueError, TypeError):
                limit = 50

            if not query:
                return web.json_response({
                    'success': False,
                    'error': 'Search query required'
                }, status=400)

            loop = asyncio.get_event_loop()
            topics = await loop.run_in_executor(
                None, self.db.search_forum, query, category, limit
            )

            return web.json_response({
                'success': True,
                'query': query,
                'topics': topics
            })

        except Exception as e:
            logger.error(f"Search forum error: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    async def handle_get_my_topics(self, request: web.Request) -> web.Response:
        """Get topics created by authenticated user"""
        try:
            # Verify authentication
            user = self.verify_token(request)
            if not user:
                return web.json_response({
                    'success': False,
                    'error': 'Authentication required'
                }, status=401)

            # Validate limit parameter
            try:
                limit = int(request.query.get('limit', 50))
                if limit < 1 or limit > 1000:
                    limit = 50
            except (ValueError, TypeError):
                limit = 50

            loop = asyncio.get_event_loop()
            topics = await loop.run_in_executor(None, self.db.get_user_topics, user['id'], limit)

            return web.json_response({
                'success': True,
                'topics': topics
            })

        except Exception as e:
            logger.error(f"Get my topics error: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    # =====================================================================
    # Groups -> Forums -> Threads (Elten-style) Handlers
    # =====================================================================

    # ----- Account email + password recovery -----

    async def handle_get_account_email(self, request: web.Request) -> web.Response:
        """Return the authenticated user's recovery email + verification state."""
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            loop = asyncio.get_event_loop()
            full = await loop.run_in_executor(None, self.db.get_user_by_id, user['id'])
            return web.json_response({
                'success': True,
                'email': (full or {}).get('email'),
                'email_verified': bool((full or {}).get('email_verified')),
            })
        except Exception as e:
            logger.error(f"Get account email error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_set_account_email(self, request: web.Request) -> web.Response:
        """Set/replace the authenticated user's recovery email and send a
        verification link to it."""
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            data = await request.json() if request.can_read_body else {}
            email = (data.get('email') or '').strip()
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.db.set_user_email, user['id'], email)
            if result.get('success') and result.get('token'):
                try:
                    import mailer
                    await loop.run_in_executor(
                        None, mailer.send_verification, email, user.get('username', ''), result['token']
                    )
                except Exception as me:
                    logger.error(f"Verification email send failed: {me}", exc_info=True)
                # Do not leak the token to the client.
                result = {'success': True, 'email': email, 'email_verified': False}
            return web.json_response(result, status=200 if result.get('success') else 400)
        except Exception as e:
            logger.error(f"Set account email error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_verify_email(self, request: web.Request) -> web.Response:
        """Consume an email-verification token (from the emailed link)."""
        try:
            data = await request.json() if request.can_read_body else {}
            token = (data.get('token') or '').strip()
            if not token:
                return web.json_response({'success': False, 'error': 'Missing token'}, status=400)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.db.verify_email, token)
            return web.json_response(result, status=200 if result.get('success') else 400)
        except Exception as e:
            logger.error(f"Verify email error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    def _note_authz_violation(self, request: web.Request, user: Dict, resource: str):
        """Report a cross-user (IDOR) access attempt to Cerberus."""
        try:
            if self.cerberus is not None:
                ip = self._get_client_ip(request)
                self.cerberus.record_authz_violation(ip, (user or {}).get('id'), resource)
        except Exception as e:
            logger.error(f"record_authz_violation failed: {e}")

    def _note_privilege_escalation(self, request: web.Request, user: Dict, resource: str):
        """Report an attempt to use a moderator/admin capability without the role."""
        try:
            if self.cerberus is not None:
                ip = self._get_client_ip(request)
                self.cerberus.record_privilege_escalation(ip, (user or {}).get('id'), resource)
        except Exception as e:
            logger.error(f"record_privilege_escalation failed: {e}")

    async def handle_forgot_password(self, request: web.Request) -> web.Response:
        """Start a password reset. Always answers 200 with a generic message so
        an attacker cannot tell whether an account/email exists."""
        try:
            # Rate-limit / escalate reset abuse per source IP.
            try:
                if self.cerberus is not None:
                    self.cerberus.record_password_reset_request(self._get_client_ip(request))
            except Exception:
                pass
            data = await request.json() if request.can_read_body else {}
            identifier = (data.get('identifier') or '').strip()
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.db.create_password_reset, identifier)
            if result.get('success') and result.get('found') and result.get('token'):
                try:
                    import mailer
                    await loop.run_in_executor(
                        None, mailer.send_password_reset,
                        result['email'], result.get('username', ''), result['token'],
                    )
                except Exception as me:
                    logger.error(f"Password reset email send failed: {me}", exc_info=True)
            # Generic response regardless of whether an account matched.
            return web.json_response({
                'success': True,
                'message': 'If an account with a verified email matches, a reset link has been sent.',
            })
        except Exception as e:
            logger.error(f"Forgot password error: {e}", exc_info=True)
            # Still avoid leaking; report generic success.
            return web.json_response({
                'success': True,
                'message': 'If an account with a verified email matches, a reset link has been sent.',
            })

    async def handle_reset_password(self, request: web.Request) -> web.Response:
        """Complete a password reset with a token + new password."""
        try:
            data = await request.json() if request.can_read_body else {}
            token = (data.get('token') or '').strip()
            new_password = data.get('new_password') or ''
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.db.reset_password_with_token, token, new_password
            )
            return web.json_response(result, status=200 if result.get('success') else 400)
        except Exception as e:
            logger.error(f"Reset password error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    # ----- User mailboxes -----

    async def handle_mail_inbox(self, request: web.Request) -> web.Response:
        return await self._mail_list(request, 'inbox')

    async def handle_mail_sent(self, request: web.Request) -> web.Response:
        return await self._mail_list(request, 'sent')

    async def _mail_list(self, request: web.Request, folder: str) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            loop = asyncio.get_event_loop()
            messages = await loop.run_in_executor(None, self.db.list_mailbox, user['id'], folder)
            address = await loop.run_in_executor(None, self.db.user_mail_address, user['username'])
            return web.json_response({'success': True, 'messages': messages, 'address': address})
        except Exception as e:
            logger.error(f"Mail list error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_mail_get(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            mail_id = int(request.match_info['mail_id'])
            loop = asyncio.get_event_loop()
            msg = await loop.run_in_executor(None, self.db.get_mail, mail_id, user['id'])
            if not msg:
                # Either the id does not exist or it belongs to another user.
                # If it exists but is owned by someone else, that is a cross-user
                # access attempt -> tell Cerberus.
                exists = await loop.run_in_executor(None, self.db.mail_exists, mail_id)
                if exists:
                    self._note_authz_violation(request, user, f"mail/{mail_id}")
                return web.json_response({'success': False, 'error': 'Not found'}, status=404)
            # Reading marks it read.
            await loop.run_in_executor(None, self.db.mark_mail_read, mail_id, user['id'])
            return web.json_response({'success': True, 'message': msg})
        except Exception as e:
            logger.error(f"Mail get error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_mail_mark_read(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            mail_id = int(request.match_info['mail_id'])
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.db.mark_mail_read, mail_id, user['id'])
            return web.json_response(result)
        except Exception as e:
            logger.error(f"Mail mark read error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_mail_delete(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            mail_id = int(request.match_info['mail_id'])
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.db.delete_mail, mail_id, user['id'])
            return web.json_response(result)
        except Exception as e:
            logger.error(f"Mail delete error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_mail_send(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            data = await request.json() if request.can_read_body else {}
            to_addr = (data.get('to') or '').strip()
            subject = (data.get('subject') or '').strip()
            body = data.get('body') or ''
            if not to_addr:
                return web.json_response({'success': False, 'error': 'Recipient is required'}, status=400)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.db.send_user_mail, user['id'], to_addr, subject, body
            )
            # If the recipient is remote, hand the message to the outbound mailer.
            if result.get('success') and result.get('external_recipient'):
                try:
                    import mailer
                    from email.message import EmailMessage
                    msg = EmailMessage()
                    msg['Subject'] = subject
                    msg['From'] = result.get('from_addr')
                    msg['To'] = result['external_recipient']
                    msg.set_content(body)
                    await loop.run_in_executor(
                        None, mailer.send_message, msg, result.get('from_addr'),
                        [result['external_recipient']],
                    )
                except Exception as me:
                    logger.error(f"Outbound mail send failed: {me}", exc_info=True)
            return web.json_response(result, status=200 if result.get('success') else 400)
        except Exception as e:
            logger.error(f"Mail send error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_mail_incoming(self, request: web.Request) -> web.Response:
        """Ingest a message delivered by the Postfix pipe (mail_delivery.py).
        Authenticated by a shared secret so the delivery script never opens the
        SQLCipher DB directly (single-writer safety)."""
        try:
            from config import Config
            token = request.headers.get('X-Titan-Mail-Token', '')
            if not Config.MAIL_INGEST_TOKEN or token != Config.MAIL_INGEST_TOKEN:
                return web.json_response({'success': False, 'error': 'Forbidden'}, status=403)
            data = await request.json() if request.can_read_body else {}
            recipient = (data.get('recipient') or '').strip()
            sender = (data.get('sender') or '').strip()
            subject = (data.get('subject') or '').strip()
            body = data.get('body') or ''
            loop = asyncio.get_event_loop()
            local = await loop.run_in_executor(None, self.db.resolve_local_user_by_address, recipient)
            if not local:
                # Unknown mailbox: accept and drop (avoids Postfix retry loops).
                return web.json_response({'success': True, 'delivered': False})
            result = await loop.run_in_executor(
                None, self.db.store_incoming_mail, local['id'], sender, recipient, subject, body
            )
            return web.json_response({'success': True, 'delivered': True, 'mail_id': result.get('mail_id')})
        except Exception as e:
            logger.error(f"Mail incoming error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    def _require_auth(self, request: web.Request):
        """Return the authenticated user dict or None."""
        return self.verify_token(request)

    @staticmethod
    def _auth_required_response():
        return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

    async def handle_list_groups(self, request: web.Request) -> web.Response:
        """List groups visible to the authenticated user."""
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            loop = asyncio.get_event_loop()
            groups = await loop.run_in_executor(None, self.db.list_groups, user['id'])
            return web.json_response({'success': True, 'groups': groups})
        except Exception as e:
            logger.error(f"List groups error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_create_group(self, request: web.Request) -> web.Response:
        """Create a group (any authenticated user; becomes owner)."""
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            data = await request.json()
            name = (data.get('name') or '').strip()
            description = data.get('description')
            visibility = data.get('visibility', 'public')
            member_limit = data.get('member_limit')
            try:
                member_limit = int(member_limit) if member_limit not in (None, '') else None
            except (ValueError, TypeError):
                member_limit = None
            if not name:
                return web.json_response({'success': False, 'error': 'Group name required'}, status=400)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.db.create_group, name, description, user['id'], visibility, member_limit
            )
            status = 200 if result.get('success') else 400
            if result.get('success'):
                logger.info(f"Group created: '{name}' by {user['username']}")
            return web.json_response(result, status=status)
        except Exception as e:
            logger.error(f"Create group error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_get_group(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            group_id = int(request.match_info['group_id'])
            loop = asyncio.get_event_loop()
            group = await loop.run_in_executor(None, self.db.get_group, group_id, user['id'])
            if not group:
                return web.json_response({'success': False, 'error': 'Group not found'}, status=404)
            return web.json_response({'success': True, 'group': group})
        except Exception as e:
            logger.error(f"Get group error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_update_group(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            group_id = int(request.match_info['group_id'])
            data = await request.json()
            member_limit = data.get('member_limit')
            if member_limit not in (None, ''):
                try:
                    member_limit = int(member_limit)
                except (ValueError, TypeError):
                    member_limit = None
            else:
                member_limit = None
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.db.update_group, group_id, user['id'],
                data.get('name'), data.get('description'), data.get('visibility'), member_limit
            )
            return web.json_response(result, status=200 if result.get('success') else 403)
        except Exception as e:
            logger.error(f"Update group error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_delete_group(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            group_id = int(request.match_info['group_id'])
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.db.delete_group, group_id, user['id'])
            return web.json_response(result, status=200 if result.get('success') else 403)
        except Exception as e:
            logger.error(f"Delete group error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_join_group(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            group_id = int(request.match_info['group_id'])
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.db.join_group, group_id, user['id'])
            return web.json_response(result, status=200 if result.get('success') else 400)
        except Exception as e:
            logger.error(f"Join group error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_leave_group(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            group_id = int(request.match_info['group_id'])
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.db.leave_group, group_id, user['id'])
            return web.json_response(result, status=200 if result.get('success') else 400)
        except Exception as e:
            logger.error(f"Leave group error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_group_members(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            group_id = int(request.match_info['group_id'])
            status = request.query.get('status', 'active')
            if status not in ('active', 'pending'):
                status = 'active'
            loop = asyncio.get_event_loop()
            # Only moderators may list pending join requests.
            if status == 'pending':
                is_mod = await loop.run_in_executor(None, self.db.is_group_moderator, group_id, user['id'])
                if not is_mod:
                    return web.json_response({'success': False, 'error': 'Moderators only'}, status=403)
            members = await loop.run_in_executor(None, self.db.list_group_members, group_id, status)
            return web.json_response({'success': True, 'members': members})
        except Exception as e:
            logger.error(f"Group members error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_approve_member(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            group_id = int(request.match_info['group_id'])
            target = int(request.match_info['user_id'])
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.db.approve_member, group_id, target, user['id'])
            return web.json_response(result, status=200 if result.get('success') else 403)
        except Exception as e:
            logger.error(f"Approve member error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_reject_member(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            group_id = int(request.match_info['group_id'])
            target = int(request.match_info['user_id'])
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.db.reject_member, group_id, target, user['id'])
            return web.json_response(result, status=200 if result.get('success') else 403)
        except Exception as e:
            logger.error(f"Reject member error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_set_group_moderator(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            group_id = int(request.match_info['group_id'])
            target = int(request.match_info['user_id'])
            data = await request.json() if request.can_read_body else {}
            make = bool(data.get('make_moderator', True))
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.db.set_group_moderator, group_id, target, user['id'], make
            )
            return web.json_response(result, status=200 if result.get('success') else 403)
        except Exception as e:
            logger.error(f"Set group moderator error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_transfer_group_ownership(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            group_id = int(request.match_info['group_id'])
            target = int(request.match_info['user_id'])
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.db.transfer_group_ownership, group_id, target, user['id']
            )
            return web.json_response(result, status=200 if result.get('success') else 403)
        except Exception as e:
            logger.error(f"Transfer group ownership error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_ban_from_group(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            group_id = int(request.match_info['group_id'])
            target = int(request.match_info['user_id'])
            data = await request.json() if request.can_read_body else {}
            reason = data.get('reason')
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.db.ban_user_from_group, group_id, target, user['id'], reason
            )
            return web.json_response(result, status=200 if result.get('success') else 403)
        except Exception as e:
            logger.error(f"Ban from group error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_unban_from_group(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            group_id = int(request.match_info['group_id'])
            target = int(request.match_info['user_id'])
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.db.unban_user_from_group, group_id, target, user['id']
            )
            return web.json_response(result, status=200 if result.get('success') else 403)
        except Exception as e:
            logger.error(f"Unban from group error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_list_group_forums(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            group_id = int(request.match_info['group_id'])
            loop = asyncio.get_event_loop()
            # Respect hidden-group privacy: get_group returns None for hidden
            # groups the caller cannot see.
            group = await loop.run_in_executor(None, self.db.get_group, group_id, user['id'])
            if not group:
                return web.json_response({'success': False, 'error': 'Group not found'}, status=404)
            forums = await loop.run_in_executor(None, self.db.list_group_forums, group_id)
            return web.json_response({'success': True, 'forums': forums})
        except Exception as e:
            logger.error(f"List group forums error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_create_group_forum(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            group_id = int(request.match_info['group_id'])
            data = await request.json()
            name = (data.get('name') or '').strip()
            description = data.get('description')
            if not name:
                return web.json_response({'success': False, 'error': 'Forum name required'}, status=400)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.db.create_group_forum, group_id, name, description, user['id']
            )
            return web.json_response(result, status=200 if result.get('success') else 403)
        except Exception as e:
            logger.error(f"Create group forum error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_delete_group_forum(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            forum_id = int(request.match_info['forum_id'])
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.db.delete_group_forum, forum_id, user['id'])
            return web.json_response(result, status=200 if result.get('success') else 403)
        except Exception as e:
            logger.error(f"Delete group forum error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_list_move_requests(self, request: web.Request) -> web.Response:
        """Pending cross-group move requests the caller can act on."""
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            loop = asyncio.get_event_loop()
            requests = await loop.run_in_executor(None, self.db.list_pending_moves_for_user, user['id'])
            return web.json_response({'success': True, 'requests': requests})
        except Exception as e:
            logger.error(f"List move requests error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_approve_move(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            request_id = int(request.match_info['request_id'])
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.db.approve_topic_move, request_id, user['id'])
            # Notify the thread author that their thread was moved.
            if result.get('success') and result.get('author_id'):
                forum = await loop.run_in_executor(None, self.db.get_group_forum, result.get('to_forum_id'))
                forum_name = forum['name'] if forum else 'another forum'
                group_name = forum['group_name'] if forum else ''
                title = result.get('title') or 'your thread'
                msg = (f"Your thread '{title}' was moved to forum "
                       f"'{forum_name}' in group '{group_name}'.")
                try:
                    await loop.run_in_executor(
                        None, self.db.send_private_message, user['id'], result['author_id'], msg
                    )
                except Exception as notify_err:
                    logger.warning(f"Move-approval notify failed: {notify_err}")
            return web.json_response(result, status=200 if result.get('success') else 403)
        except Exception as e:
            logger.error(f"Approve move error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_reject_move(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            request_id = int(request.match_info['request_id'])
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.db.reject_topic_move, request_id, user['id'])
            return web.json_response(result, status=200 if result.get('success') else 403)
        except Exception as e:
            logger.error(f"Reject move error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    # =====================================================================
    # Titan-Net Extension System Handlers
    # =====================================================================

    async def _is_staff(self, user, loop):
        if not user:
            return False
        if user.get('is_admin'):
            return True
        return await loop.run_in_executor(None, self.db.is_moderator, user['id'])

    async def handle_submit_extension(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            loop = asyncio.get_event_loop()
            if not await self._is_staff(user, loop):
                return web.json_response({'success': False, 'error': 'Moderators only'}, status=403)
            data = await request.json()
            slug = (data.get('slug') or '').strip()
            name = (data.get('name') or '').strip()
            if not slug or not name:
                return web.json_response({'success': False, 'error': 'Slug and name required'}, status=400)
            kind = data.get('kind', 'single')
            bundle = data.get('bundle')
            entry = data.get('entry')
            moderators_only = bool(data.get('moderators_only', False))
            allowed_regions = data.get('allowed_regions') or []
            blocked_regions = data.get('blocked_regions') or []
            result = await loop.run_in_executor(
                None,
                functools.partial(
                    self.db.submit_extension, user['id'], slug, name, data.get('description'),
                    data.get('version', '1.0'), data.get('client_code', ''), data.get('manifest'),
                    kind=kind, bundle=bundle, entry=entry, moderators_only=moderators_only,
                    allowed_regions=allowed_regions, blocked_regions=blocked_regions,
                )
            )
            if result.get('success'):
                logger.info(f"Extension submitted: '{slug}' by {user['username']}")
            return web.json_response(result, status=200 if result.get('success') else 400)
        except Exception as e:
            logger.error(f"Submit extension error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_list_extensions(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            loop = asyncio.get_event_loop()
            status = request.query.get('status')
            include_pending = await self._is_staff(user, loop)
            extensions = await loop.run_in_executor(
                None, self.db.list_extensions, status, user['id'], include_pending
            )
            return web.json_response({'success': True, 'extensions': extensions})
        except Exception as e:
            logger.error(f"List extensions error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_get_extension(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            ext_id = int(request.match_info['ext_id'])
            loop = asyncio.get_event_loop()
            ext = await loop.run_in_executor(None, self.db.get_extension, ext_id, None)
            if not ext:
                return web.json_response({'success': False, 'error': 'Extension not found'}, status=404)
            # Only staff or the author may see pending/rejected code bodies.
            if ext.get('status') != 'active':
                if not (await self._is_staff(user, loop) or ext.get('author_id') == user['id']):
                    return web.json_response({'success': False, 'error': 'Not allowed'}, status=403)
            return web.json_response({'success': True, 'extension': ext})
        except Exception as e:
            logger.error(f"Get extension error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_approve_extension(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            ext_id = int(request.match_info['ext_id'])
            data = await request.json() if request.can_read_body else {}
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.db.review_extension, ext_id, user['id'], True, data.get('note')
            )
            if result.get('success'):
                logger.info(f"Extension {ext_id} approved by {user['username']}")
            return web.json_response(result, status=200 if result.get('success') else 403)
        except Exception as e:
            logger.error(f"Approve extension error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_reject_extension(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            ext_id = int(request.match_info['ext_id'])
            data = await request.json() if request.can_read_body else {}
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.db.review_extension, ext_id, user['id'], False, data.get('note')
            )
            return web.json_response(result, status=200 if result.get('success') else 403)
        except Exception as e:
            logger.error(f"Reject extension error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_extension_client(self, request: web.Request) -> web.Response:
        """Download an ACTIVE extension's client code (for clients to load)."""
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            slug = request.match_info['slug']
            loop = asyncio.get_event_loop()
            ext = await loop.run_in_executor(None, self.db.get_active_extension_client, slug)
            if not ext:
                return web.json_response({'success': False, 'error': 'Active extension not found'}, status=404)
            return web.json_response({'success': True, 'extension': ext})
        except Exception as e:
            logger.error(f"Extension client error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_extension_data_get(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            slug = request.match_info['slug']
            key = request.match_info['key']
            loop = asyncio.get_event_loop()
            ext = await loop.run_in_executor(None, self.db.get_extension, None, slug)
            if not ext or ext.get('status') != 'active':
                return web.json_response({'success': False, 'error': 'Active extension not found'}, status=404)
            value = await loop.run_in_executor(None, self.db.ext_storage_get, ext['id'], key)
            return web.json_response({'success': True, 'key': key, 'value': value})
        except Exception as e:
            logger.error(f"Extension data get error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_extension_data_set(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            slug = request.match_info['slug']
            key = request.match_info['key']
            data = await request.json()
            loop = asyncio.get_event_loop()
            ext = await loop.run_in_executor(None, self.db.get_extension, None, slug)
            if not ext or ext.get('status') != 'active':
                return web.json_response({'success': False, 'error': 'Active extension not found'}, status=404)
            result = await loop.run_in_executor(
                None, self.db.ext_storage_set, ext['id'], key, data.get('value')
            )
            return web.json_response(result, status=200 if result.get('success') else 400)
        except Exception as e:
            logger.error(f"Extension data set error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_add_extension_asset(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            ext_id = int(request.match_info['ext_id'])
            data = await request.json()
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.db.add_extension_asset, ext_id, user['id'],
                data.get('kind'), data.get('name'), data.get('content', ''), data.get('mime')
            )
            return web.json_response(result, status=200 if result.get('success') else 403)
        except Exception as e:
            logger.error(f"Add extension asset error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_list_extension_assets(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            slug = request.match_info['slug']
            loop = asyncio.get_event_loop()
            assets = await loop.run_in_executor(None, self.db.list_extension_assets, slug)
            return web.json_response({'success': True, 'assets': assets})
        except Exception as e:
            logger.error(f"List extension assets error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_get_extension_asset(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            slug = request.match_info['slug']
            kind = request.match_info['kind']
            name = request.match_info['name']
            loop = asyncio.get_event_loop()
            asset = await loop.run_in_executor(None, self.db.get_extension_asset, slug, kind, name)
            if not asset:
                return web.json_response({'success': False, 'error': 'Asset not found'}, status=404)
            return web.json_response({'success': True, 'asset': asset})
        except Exception as e:
            logger.error(f"Get extension asset error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    # =====================================================================
    # Curated moderation capability (timed jail / release)
    # =====================================================================

    async def handle_jail_user(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            data = await request.json()
            target = int(data.get('user_id'))
            minutes = int(data.get('minutes', 0))
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.db.jail_user, target, user['id'], minutes, data.get('reason')
            )
            if result.get('success'):
                logger.info(f"User {target} jailed for {minutes}m by {user['username']}")
            return web.json_response(result, status=200 if result.get('success') else 403)
        except Exception as e:
            logger.error(f"Jail user error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_release_user(self, request: web.Request) -> web.Response:
        try:
            user = self._require_auth(request)
            if not user:
                return self._auth_required_response()
            data = await request.json()
            target = int(data.get('user_id'))
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.db.release_user, target, user['id'])
            return web.json_response(result, status=200 if result.get('success') else 403)
        except Exception as e:
            logger.error(f"Release user error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    # Role Management Handlers

    async def handle_set_developer(self, request: web.Request) -> web.Response:
        """DISABLED — was a privilege-escalation vulnerability.

        Previously promoted any authenticated caller to ``developer`` based
        solely on a client-side check (``not sys.frozen``). Anyone running
        from source automatically became a developer / moderator on first
        login. The route is no longer registered; this stub remains as
        defense-in-depth so reintroducing the route still fails closed and
        leaves an audit trail. To grant developer/moderator roles, a current
        developer must use ``/api/moderation/promote``.
        """
        try:
            user = self.verify_token(request)
            ident = user['username'] if user else 'unauthenticated'
        except Exception:
            ident = 'unauthenticated'
        peer = request.remote
        logger.warning(
            f"Blocked self-promotion attempt on /api/users/set_developer "
            f"from user={ident} peer={peer}"
        )
        return web.json_response(
            {'success': False, 'error': 'Endpoint removed (self-promotion not allowed)'},
            status=410,
        )

    async def handle_get_user_role(self, request: web.Request) -> web.Response:
        """Get current user's role"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            loop = asyncio.get_event_loop()
            role = await loop.run_in_executor(None, self.db.get_user_role, user['id'])

            return web.json_response({'success': True, 'role': role})

        except Exception as e:
            logger.error(f"Get user role error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_get_all_users(self, request: web.Request) -> web.Response:
        """Get all registered users (moderator/developer only)"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            # Check if user is moderator or developer
            loop = asyncio.get_event_loop()
            role = await loop.run_in_executor(None, self.db.get_user_role, user['id'])
            if role not in ('moderator', 'developer'):
                return web.json_response({'success': False, 'error': 'Moderator access required'}, status=403)

            # Get all users from database
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, username, titan_number, full_name, created_at
                FROM users
                ORDER BY username ASC
            """)

            users = []
            for row in cursor.fetchall():
                users.append({
                    'id': row['id'],
                    'username': row['username'],
                    'titan_number': row['titan_number'],
                    'full_name': row['full_name'] or '',
                    'created_at': row['created_at']
                })

            logger.info(f"User {user['username']} retrieved {len(users)} total users")
            return web.json_response({'success': True, 'users': users})

        except Exception as e:
            logger.error(f"Get all users error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    # Moderation Handlers

    def _is_privileged(self, user: Dict) -> bool:
        """Staff role check used to gate + detect privilege escalation."""
        return bool(user and (user.get('is_admin') or user.get('role') in ('developer', 'admin')))

    async def handle_promote_moderator(self, request: web.Request) -> web.Response:
        """Promote user to moderator (developer only)"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)
            if not self._is_privileged(user):
                self._note_privilege_escalation(request, user, '/api/moderation/promote')
                return web.json_response({'success': False, 'error': 'Not allowed'}, status=403)

            data = await request.json()
            username = data.get('username')
            title = data.get('title', 'Moderator')

            if not username:
                return web.json_response({'success': False, 'error': 'Username required'}, status=400)

            # Get user ID by username
            loop = asyncio.get_event_loop()
            target_user = await loop.run_in_executor(
                None,
                lambda: self.db.get_connection().cursor().execute(
                    "SELECT id FROM users WHERE username = ?", (username,)
                ).fetchone(),
            )

            if not target_user:
                return web.json_response({'success': False, 'error': 'User not found'}, status=404)

            result = await self.db.run_write_async(
                self.db.promote_to_moderator, target_user['id'], user['id'], title
            )

            if result['success']:
                logger.info(f"User {username} promoted to moderator by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Promote moderator error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_demote_moderator(self, request: web.Request) -> web.Response:
        """Demote moderator to regular user (developer only)"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)
            if not self._is_privileged(user):
                self._note_privilege_escalation(request, user, '/api/moderation/demote')
                return web.json_response({'success': False, 'error': 'Not allowed'}, status=403)

            data = await request.json()
            username = data.get('username')

            if not username:
                return web.json_response({'success': False, 'error': 'Username required'}, status=400)

            # Get user ID by username
            loop = asyncio.get_event_loop()
            target_user = await loop.run_in_executor(
                None,
                lambda: self.db.get_connection().cursor().execute(
                    "SELECT id FROM users WHERE username = ?", (username,)
                ).fetchone(),
            )

            if not target_user:
                return web.json_response({'success': False, 'error': 'User not found'}, status=404)

            result = await self.db.run_write_async(
                self.db.demote_from_moderator, target_user['id'], user['id']
            )

            if result['success']:
                logger.info(f"User {username} demoted from moderator by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Demote moderator error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_get_moderators(self, request: web.Request) -> web.Response:
        """Get list of all moderators"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            loop = asyncio.get_event_loop()
            moderators = await loop.run_in_executor(None, self.db.get_all_moderators)

            return web.json_response({'success': True, 'moderators': moderators})

        except Exception as e:
            logger.error(f"Get moderators error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_admin_change_password(self, request: web.Request) -> web.Response:
        """Admin / developer forced password reset for any user.

        Body: ``{"username": "...", "new_password": "..."}``
        Auth: requires the caller to hold the ``developer`` role. Moderators
        are NOT enough — resetting a password is account takeover-grade and
        must stay narrowly scoped.
        """
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            loop = asyncio.get_event_loop()
            if not await loop.run_in_executor(None, self.db.is_developer, user['id']):
                return web.json_response(
                    {'success': False, 'error': 'Developer role required'}, status=403,
                )

            data = await request.json()
            username = (data.get('username') or '').strip()
            new_password = data.get('new_password') or ''

            if not username:
                return web.json_response({'success': False, 'error': 'Username required'}, status=400)
            if len(new_password) < 8:
                return web.json_response(
                    {'success': False, 'error': 'Password must be at least 8 characters'},
                    status=400,
                )

            result = await self.db.run_write_async(
                self.db.change_user_password, username, new_password,
            )
            if result.get('success'):
                logger.warning(
                    f"ADMIN PASSWORD RESET: user='{username}' by "
                    f"caller='{user['username']}' (id={user['id']})"
                )
                return web.json_response({
                    'success': True,
                    'username': result.get('username'),
                    'user_id': result.get('user_id'),
                })
            return web.json_response(result, status=400)

        except Exception as e:
            logger.error(f"Admin change_password error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    # Ban System Handlers

    async def handle_ban_from_room(self, request: web.Request) -> web.Response:
        """Ban user from room"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            data = await request.json()
            room_id = data.get('room_id')
            user_id = data.get('user_id')
            ban_type = data.get('ban_type', 'permanent')
            duration_hours = data.get('duration_hours')
            reason = data.get('reason', '')
            ip_address = data.get('ip_address')

            if not room_id or not user_id:
                return web.json_response({'success': False, 'error': 'Room ID and User ID required'}, status=400)

            result = await self.db.run_write_async(
                self.db.ban_user_from_room_extended,
                room_id, user_id, user['id'], ban_type, duration_hours, reason, ip_address,
            )

            if result['success']:
                logger.info(f"User {user_id} banned from room {room_id} by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Ban from room error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_ban_globally(self, request: web.Request) -> web.Response:
        """Ban user globally from TCE Community"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            data = await request.json()
            user_id = data.get('user_id')
            ban_type = data.get('ban_type', 'permanent')
            duration_hours = data.get('duration_hours')
            reason = data.get('reason', '')
            ip_address = data.get('ip_address')

            if not user_id:
                return web.json_response({'success': False, 'error': 'User ID required'}, status=400)

            result = await self.db.run_write_async(
                self.db.ban_user_globally,
                user_id, user['id'], ban_type, duration_hours, reason, ip_address,
            )

            if result['success']:
                logger.info(f"User {user_id} banned globally by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Ban globally error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_ban_hard(self, request: web.Request) -> web.Response:
        """Hard ban user - most restrictive ban (IP + Hardware + User)"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            # Require developer role for hard bans
            loop = asyncio.get_event_loop()
            if not await loop.run_in_executor(None, self.db.is_developer, user['id']):
                return web.json_response({'success': False, 'error': 'Only developers can issue hard bans'}, status=403)

            data = await request.json()
            user_id = data.get('user_id')
            reason = data.get('reason', '')
            ip_address = data.get('ip_address')
            hardware_id = data.get('hardware_id')

            if not user_id:
                return web.json_response({'success': False, 'error': 'User ID required'}, status=400)

            if not reason:
                return web.json_response({'success': False, 'error': 'Reason required for hard ban'}, status=400)

            result = await self.db.run_write_async(
                self.db.ban_user_hard,
                user_id, user['id'], reason, ip_address, hardware_id,
            )

            if result['success']:
                logger.warning(f"HARD BAN issued: User {user_id} by {user['username']} - Reason: {reason}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Hard ban error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_ban_from_forum(self, request: web.Request) -> web.Response:
        """Ban user from forum"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            data = await request.json()
            user_id = data.get('user_id')
            ban_type = data.get('ban_type', 'permanent')
            duration_hours = data.get('duration_hours')
            reason = data.get('reason', '')

            if not user_id:
                return web.json_response({'success': False, 'error': 'User ID required'}, status=400)

            result = await self.db.run_write_async(
                self.db.ban_user_from_forum,
                user_id, user['id'], ban_type, duration_hours, reason,
            )

            if result['success']:
                logger.info(f"User {user_id} banned from forum by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Ban from forum error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_unban_from_room(self, request: web.Request) -> web.Response:
        """Unban user from room"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            data = await request.json()
            room_id = data.get('room_id')
            user_id = data.get('user_id')

            if not room_id or not user_id:
                return web.json_response({'success': False, 'error': 'Room ID and User ID required'}, status=400)

            result = await self.db.run_write_async(
                self.db.unban_user_from_room, room_id, user_id, user['id']
            )

            if result['success']:
                logger.info(f"User {user_id} unbanned from room {room_id} by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Unban from room error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_unban_globally(self, request: web.Request) -> web.Response:
        """Unban user globally"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            loop = asyncio.get_event_loop()
            if not await loop.run_in_executor(None, self.db.is_moderator, user['id']):
                return web.json_response({'success': False, 'error': 'Permission denied'}, status=403)

            data = await request.json()
            user_id = data.get('user_id')

            if not user_id:
                return web.json_response({'success': False, 'error': 'User ID required'}, status=400)

            result = await self.db.run_write_async(self.db.unban_user_globally, user_id)

            if result['success']:
                logger.info(f"User {user_id} unbanned globally by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Unban globally error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_unban_from_forum(self, request: web.Request) -> web.Response:
        """Unban user from forum"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            loop = asyncio.get_event_loop()
            if not await loop.run_in_executor(None, self.db.is_moderator, user['id']):
                return web.json_response({'success': False, 'error': 'Permission denied'}, status=403)

            data = await request.json()
            user_id = data.get('user_id')

            if not user_id:
                return web.json_response({'success': False, 'error': 'User ID required'}, status=400)

            result = await self.db.run_write_async(self.db.unban_user_from_forum, user_id)

            if result['success']:
                logger.info(f"User {user_id} unbanned from forum by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Unban from forum error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_check_ban_status(self, request: web.Request) -> web.Response:
        """Check user ban status"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            user_id = int(request.match_info['user_id'])

            loop = asyncio.get_event_loop()
            global_ban, forum_ban = await asyncio.gather(
                loop.run_in_executor(None, self.db.is_user_banned_globally, user_id),
                loop.run_in_executor(None, self.db.is_user_banned_from_forum, user_id),
            )

            return web.json_response({
                'success': True,
                'global_ban': global_ban,
                'forum_ban': forum_ban
            })

        except Exception as e:
            logger.error(f"Check ban status error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    # App Repository Moderation Handlers

    async def handle_reject_app(self, request: web.Request) -> web.Response:
        """Reject app in repository (moderator only)"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            app_id = int(request.match_info['app_id'])

            success = await self.db.run_write_async(self.db.reject_app, app_id, user['id'])

            if success:
                logger.info(f"App {app_id} rejected by {user['username']}")
                return web.json_response({'success': True, 'message': 'App rejected'})
            else:
                return web.json_response({'success': False, 'error': 'Failed to reject app'}, status=400)

        except Exception as e:
            logger.error(f"Reject app error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_get_pending_apps(self, request: web.Request) -> web.Response:
        """Get pending apps awaiting approval"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            loop = asyncio.get_event_loop()
            apps = await loop.run_in_executor(None, self.db.get_pending_apps)

            return web.json_response({'success': True, 'apps': apps})

        except Exception as e:
            logger.error(f"Get pending apps error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_approve_app(self, request: web.Request) -> web.Response:
        """Approve app in repository (moderator only)"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            app_id = int(request.match_info['app_id'])

            success = await self.db.run_write_async(self.db.approve_app, app_id, user['id'])

            if success:
                logger.info(f"App {app_id} approved by {user['username']}")
                return web.json_response({'success': True, 'message': 'App approved'})
            else:
                return web.json_response({'success': False, 'error': 'Failed to approve app'}, status=400)

        except Exception as e:
            logger.error(f"Approve app error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    # Forum Moderation Handlers

    async def handle_lock_topic(self, request: web.Request) -> web.Response:
        """Lock forum topic (moderator only)"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            topic_id = int(request.match_info['topic_id'])

            result = await self.db.run_write_async(self.db.lock_forum_topic, topic_id, user['id'])

            if result['success']:
                logger.info(f"Topic {topic_id} locked by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Lock topic error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_unlock_topic(self, request: web.Request) -> web.Response:
        """Unlock forum topic (moderator only)"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            topic_id = int(request.match_info['topic_id'])

            result = await self.db.run_write_async(self.db.unlock_forum_topic, topic_id, user['id'])

            if result['success']:
                logger.info(f"Topic {topic_id} unlocked by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Unlock topic error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_pin_topic(self, request: web.Request) -> web.Response:
        """Pin forum topic (moderator only)"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            topic_id = int(request.match_info['topic_id'])

            result = await self.db.run_write_async(self.db.pin_forum_topic, topic_id, user['id'])

            if result['success']:
                logger.info(f"Topic {topic_id} pinned by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Pin topic error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_unpin_topic(self, request: web.Request) -> web.Response:
        """Unpin forum topic (moderator only)"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            topic_id = int(request.match_info['topic_id'])

            result = await self.db.run_write_async(self.db.unpin_forum_topic, topic_id, user['id'])

            if result['success']:
                logger.info(f"Topic {topic_id} unpinned by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Unpin topic error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_delete_reply(self, request: web.Request) -> web.Response:
        """Delete forum reply (moderator only)"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            reply_id = int(request.match_info['reply_id'])

            result = await self.db.run_write_async(self.db.delete_forum_reply, reply_id, user['id'])

            if result['success']:
                logger.info(f"Reply {reply_id} deleted by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Delete reply error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_edit_reply(self, request: web.Request) -> web.Response:
        """Edit forum reply (moderator only)"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            reply_id = int(request.match_info['reply_id'])
            data = await request.json()
            new_content = data.get('content')

            if not new_content:
                return web.json_response({'success': False, 'error': 'Content required'}, status=400)

            result = await self.db.run_write_async(
                self.db.edit_forum_reply, reply_id, new_content, user['id']
            )

            if result['success']:
                logger.info(f"Reply {reply_id} edited by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Edit reply error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_move_topic(self, request: web.Request) -> web.Response:
        """Move forum topic to different category (moderator only)"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            topic_id = int(request.match_info['topic_id'])
            data = await request.json()
            forum_id = data.get('forum_id')
            category = data.get('category')

            # Preferred path: move to a group forum by id. Same-group moves are
            # immediate; cross-group moves create a request the target group's
            # moderators must approve (status 'pending').
            if forum_id is not None:
                try:
                    forum_id = int(forum_id)
                except (ValueError, TypeError):
                    return web.json_response({'success': False, 'error': 'Invalid forum_id'}, status=400)
                result = await self.db.run_write_async(
                    self.db.request_topic_move, topic_id, forum_id, user['id']
                )
                if result.get('success'):
                    logger.info(f"Topic {topic_id} move ({result.get('status')}) by {user['username']}")
                return web.json_response(result, status=200 if result.get('success') else 403)

            # Legacy path: move within the flat forum by category text.
            if not category:
                return web.json_response({'success': False, 'error': 'forum_id or category required'}, status=400)

            result = await self.db.run_write_async(
                self.db.move_forum_topic, topic_id, category, user['id']
            )

            if result['success']:
                logger.info(f"Topic {topic_id} moved to {category} by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Move topic error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_mark_topic_read(self, request: web.Request) -> web.Response:
        """Mark forum topic as read by user"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            topic_id = int(request.match_info['topic_id'])
            data = await request.json()
            reply_count = int(data.get('reply_count', 0))

            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                None, self.db.mark_topic_as_read, user['id'], topic_id, reply_count
            )

            return web.json_response({
                'success': success,
                'message': 'Topic marked as read' if success else 'Failed to mark topic as read'
            })

        except Exception as e:
            logger.error(f"Mark topic read error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_whats_new(self, request: web.Request) -> web.Response:
        """Get what's new counts for current user - non-blocking DB"""
        try:
            loop = asyncio.get_event_loop()
            user = await loop.run_in_executor(None, self.verify_token, request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            data = await loop.run_in_executor(None, self.db.get_whats_new, user['id'])

            return web.json_response({
                'success': True,
                **data
            })

        except Exception as e:
            logger.error(f"What's new error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    # Room Moderation Handlers

    async def handle_kick_user(self, request: web.Request) -> web.Response:
        """Kick user from room (moderator/room creator only)"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            room_id = int(request.match_info['room_id'])
            data = await request.json()
            username = data.get('username')

            if not username:
                return web.json_response({'success': False, 'error': 'Username required'}, status=400)

            # Get user ID by username
            loop = asyncio.get_event_loop()
            target_user = await loop.run_in_executor(
                None,
                lambda: self.db.get_connection().cursor().execute(
                    "SELECT id FROM users WHERE username = ?", (username,)
                ).fetchone(),
            )

            if not target_user:
                return web.json_response({'success': False, 'error': 'User not found'}, status=404)

            result = await self.db.run_write_async(
                self.db.kick_user_from_room, room_id, target_user['id'], user['id']
            )

            if result['success']:
                logger.info(f"User {username} kicked from room {room_id} by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Kick user error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_ban_user(self, request: web.Request) -> web.Response:
        """Ban user from room (moderator/room creator only)"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            room_id = int(request.match_info['room_id'])
            data = await request.json()
            username = data.get('username')
            reason = data.get('reason', '')

            if not username:
                return web.json_response({'success': False, 'error': 'Username required'}, status=400)

            # Get user ID by username
            loop = asyncio.get_event_loop()
            target_user = await loop.run_in_executor(
                None,
                lambda: self.db.get_connection().cursor().execute(
                    "SELECT id FROM users WHERE username = ?", (username,)
                ).fetchone(),
            )

            if not target_user:
                return web.json_response({'success': False, 'error': 'User not found'}, status=404)

            result = await self.db.run_write_async(
                self.db.ban_user_from_room, room_id, target_user['id'], user['id'], reason
            )

            if result['success']:
                logger.info(f"User {username} banned from room {room_id} by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Ban user error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_unban_user(self, request: web.Request) -> web.Response:
        """Unban user from room (moderator/room creator only)"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            room_id = int(request.match_info['room_id'])
            data = await request.json()
            username = data.get('username')

            if not username:
                return web.json_response({'success': False, 'error': 'Username required'}, status=400)

            # Get user ID by username
            loop = asyncio.get_event_loop()
            target_user = await loop.run_in_executor(
                None,
                lambda: self.db.get_connection().cursor().execute(
                    "SELECT id FROM users WHERE username = ?", (username,)
                ).fetchone(),
            )

            if not target_user:
                return web.json_response({'success': False, 'error': 'User not found'}, status=404)

            result = await self.db.run_write_async(
                self.db.unban_user_from_room, room_id, target_user['id'], user['id']
            )

            if result['success']:
                logger.info(f"User {username} unbanned from room {room_id} by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Unban user error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_delete_message(self, request: web.Request) -> web.Response:
        """Delete room message (moderator only)"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            message_id = int(request.match_info['message_id'])

            result = await self.db.run_write_async(
                self.db.delete_room_message, message_id, user['id']
            )

            if result['success']:
                logger.info(f"Message {message_id} deleted by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Delete message error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_delete_room(self, request: web.Request) -> web.Response:
        """Delete room (moderator only)"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            room_id = int(request.match_info['room_id'])

            result = await self.db.run_write_async(
                self.db.delete_chat_room_by_moderator, room_id, user['id']
            )

            if result['success']:
                logger.info(f"Room {room_id} deleted by {user['username']}")

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Delete room error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    # ------------------------------------------------------------------
    # User sound (business card) endpoints
    # ------------------------------------------------------------------
    VALID_SOUND_TYPES = {'login', 'logout', 'new_message', 'avatar'}
    VALID_SOUND_EXTENSIONS = {'.wav', '.ogg', '.mp3'}
    MAX_SOUND_SIZE = 5 * 1024 * 1024  # 5 MB per file

    async def handle_user_sound_upload(self, request: web.Request) -> web.Response:
        """Upload a user business-card sound (login/logout/new_message/avatar)."""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

            reader = await request.multipart()
            metadata = {}
            file_data = None
            filename = None

            async for part in reader:
                if part.name == 'metadata':
                    metadata = json.loads(await part.text())
                elif part.name == 'file':
                    filename = part.filename
                    file_data = await part.read()

            if not file_data or not filename:
                return web.json_response({'success': False, 'error': 'File data required'}, status=400)

            sound_type = metadata.get('sound_type', '')
            if sound_type not in self.VALID_SOUND_TYPES:
                return web.json_response({
                    'success': False,
                    'error': f'Invalid sound_type. Must be one of: {", ".join(self.VALID_SOUND_TYPES)}'
                }, status=400)

            ext = os.path.splitext(filename)[1].lower()
            if ext not in self.VALID_SOUND_EXTENSIONS:
                return web.json_response({
                    'success': False,
                    'error': f'Invalid file type. Allowed: {", ".join(self.VALID_SOUND_EXTENSIONS)}'
                }, status=400)

            if len(file_data) > self.MAX_SOUND_SIZE:
                return web.json_response({'success': False, 'error': 'File too large (max 5 MB)'}, status=413)

            # Store in data/sfx/{username}/
            username = user['username']
            safe_username = re.sub(r'[^a-zA-Z0-9._-]', '_', username)
            user_sfx_dir = os.path.join('data', 'sfx', safe_username)
            os.makedirs(user_sfx_dir, exist_ok=True)

            dest_path = os.path.join(user_sfx_dir, f'{sound_type}{ext}')

            # Remove old file with different extension if exists
            for old_ext in self.VALID_SOUND_EXTENSIONS:
                old_path = os.path.join(user_sfx_dir, f'{sound_type}{old_ext}')
                if os.path.exists(old_path) and old_path != dest_path:
                    os.remove(old_path)

            with open(dest_path, 'wb') as f:
                f.write(file_data)

            logger.info(f"User sound uploaded: {safe_username}/{sound_type}{ext} ({len(file_data)} bytes)")

            return web.json_response({
                'success': True,
                'sound_type': sound_type,
                'path': f'{safe_username}/{sound_type}{ext}'
            })

        except Exception as e:
            logger.error(f"User sound upload error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_get_user_sound(self, request: web.Request) -> web.Response:
        """Download a user's business-card sound."""
        try:
            username = request.match_info['username']
            sound_type = request.match_info['sound_type']

            if sound_type not in self.VALID_SOUND_TYPES:
                return web.json_response({'success': False, 'error': 'Invalid sound type'}, status=400)

            safe_username = re.sub(r'[^a-zA-Z0-9._-]', '_', username)
            user_sfx_dir = os.path.join('data', 'sfx', safe_username)

            # Find the file (could be .wav, .ogg, or .mp3)
            for ext in self.VALID_SOUND_EXTENSIONS:
                file_path = os.path.join(user_sfx_dir, f'{sound_type}{ext}')
                if os.path.exists(file_path):
                    return web.FileResponse(file_path)

            return web.json_response({'success': False, 'error': 'Sound not found'}, status=404)

        except Exception as e:
            logger.error(f"Get user sound error: {e}", exc_info=True)
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    def _create_ssl_context(self):
        """Create SSL context from Let's Encrypt certificates"""
        ssl_cert = os.environ.get('SSL_CERT', '/etc/letsencrypt/live/titosofttitan.com/fullchain.pem')
        ssl_key = os.environ.get('SSL_KEY', '/etc/letsencrypt/live/titosofttitan.com/privkey.pem')

        if not os.path.exists(ssl_cert) or not os.path.exists(ssl_key):
            logger.warning(f"SSL certificate not found: {ssl_cert} / {ssl_key}")
            logger.warning("Starting HTTP server WITHOUT SSL")
            return None

        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(ssl_cert, ssl_key)
        logger.info(f"HTTP SSL loaded: {ssl_cert}")
        return ssl_context

    # ------------------------------------------------------------------
    # OAuth proxy handlers (Spotify, Allegro, ...)
    # ------------------------------------------------------------------
    def _verify_session_query(self, request: web.Request) -> Optional[Dict]:
        """Bearer-equivalent for browser navigations: read ?session=...."""
        token = request.query.get('session')
        if not token:
            return None
        try:
            decoded = base64.b64decode(token).decode('utf-8')
            user_id_str, username = decoded.split(':', 1)
            user_id = int(user_id_str)
            user = self.db.get_user_by_id(user_id)
            if not user or user['username'] != username:
                return None
            return {
                'id': user['id'],
                'username': user['username'],
                'is_admin': user.get('is_admin', False),
            }
        except (ValueError, TypeError, KeyError):
            return None

    def _oauth_provider_config(self, provider: str) -> Optional[Dict]:
        try:
            from config import Config
            return Config.OAUTH_PROVIDERS.get(provider)
        except Exception:
            return None

    def _oauth_public_url(self) -> str:
        from config import Config
        return Config.OAUTH_PUBLIC_URL.rstrip('/')

    def _oauth_redirect_uri(self, provider: str) -> str:
        return f"{self._oauth_public_url()}/oauth/{provider}/callback"

    async def handle_oauth_start(self, request: web.Request) -> web.Response:
        """
        Step 1: authenticated client hits this. We persist a CSRF state tied to
        the user, then redirect them to the provider's authorize URL.

        Auth: either 'Authorization: Bearer ...' header (API callers) or
        '?session=...' query param (browser navigation, since browsers cannot
        attach custom headers on plain GET).
        """
        provider = request.match_info['provider']
        cfg = self._oauth_provider_config(provider)
        if not cfg:
            return web.json_response({'success': False, 'error': 'Unknown provider'}, status=404)
        if not cfg['client_id']:
            return web.json_response({
                'success': False,
                'error': f'{provider} not configured on server'
            }, status=500)

        user = self.verify_token(request) or self._verify_session_query(request)
        if not user:
            return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

        import secrets as _secrets
        from urllib.parse import urlencode
        state = _secrets.token_urlsafe(32)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, self.db.oauth_save_state, state, user['id'], provider
        )

        params = {
            'client_id': cfg['client_id'],
            'response_type': 'code',
            'redirect_uri': self._oauth_redirect_uri(provider),
            'state': state,
        }
        if cfg.get('scope'):
            params['scope'] = cfg['scope']
        # Spotify supports show_dialog to force re-consent; harmless for others
        if provider == 'spotify':
            params['show_dialog'] = 'false'

        return web.HTTPFound(f"{cfg['auth_url']}?{urlencode(params)}")

    async def handle_oauth_callback(self, request: web.Request) -> web.Response:
        """
        Step 2: provider redirects the user's browser here. We validate state,
        exchange the code for tokens, store encrypted, and show a "you can
        close this tab" page. Also pushes a WS event to the user if connected.
        """
        provider = request.match_info['provider']
        cfg = self._oauth_provider_config(provider)
        if not cfg:
            return web.Response(text='Unknown provider', status=404)

        error = request.query.get('error')
        if error:
            return self._oauth_html_page(
                title='Authorization rejected',
                body=f'Provider returned error: <code>{error}</code>. You can close this tab.'
            )

        code = request.query.get('code')
        state = request.query.get('state')
        if not code or not state:
            return web.Response(text='Missing code or state', status=400)

        loop = asyncio.get_event_loop()
        consumed = await loop.run_in_executor(None, self.db.oauth_consume_state, state)
        if not consumed or consumed['provider'] != provider:
            return web.Response(text='Invalid or expired state', status=400)
        user_id = consumed['user_id']

        # Exchange code for tokens
        try:
            token_data = await self._oauth_exchange_code(provider, cfg, code)
        except Exception as e:
            logger.error(f"OAuth code exchange failed for {provider}: {e}", exc_info=True)
            return self._oauth_html_page(
                title='Authorization failed',
                body='Could not exchange the authorization code for a token. You can close this tab.'
            )

        access_token = token_data.get('access_token')
        if not access_token:
            return self._oauth_html_page(
                title='Authorization failed',
                body='Provider did not return an access token. You can close this tab.'
            )

        refresh_token = token_data.get('refresh_token')
        scope = token_data.get('scope') or cfg.get('scope') or ''
        expires_at = self._oauth_expires_at(token_data.get('expires_in'))

        await loop.run_in_executor(
            None, self.db.oauth_save_token,
            user_id, provider, access_token, refresh_token, expires_at, scope
        )

        # Best-effort push to WS so the desktop UI updates immediately
        await self._oauth_notify_ws(user_id, provider)

        return self._oauth_html_page(
            title='Authorization successful',
            body=f'Connected to <b>{provider}</b>. You can close this tab and return to TCE.'
        )

    async def handle_oauth_get_token(self, request: web.Request) -> web.Response:
        """
        Authenticated endpoint: returns a fresh access_token for the user/provider.
        Auto-refreshes server-side if expired and a refresh_token is stored.
        """
        provider = request.match_info['provider']
        cfg = self._oauth_provider_config(provider)
        if not cfg:
            return web.json_response({'success': False, 'error': 'Unknown provider'}, status=404)

        user = self.verify_token(request)
        if not user:
            return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

        loop = asyncio.get_event_loop()
        token = await loop.run_in_executor(
            None, self.db.oauth_get_token, user['id'], provider
        )
        if not token:
            return web.json_response({'success': False, 'error': 'Not connected'}, status=404)

        if self._oauth_is_expired(token['expires_at']) and token['refresh_token']:
            try:
                refreshed = await self._oauth_refresh(provider, cfg, token['refresh_token'])
                access_token = refreshed.get('access_token')
                if not access_token:
                    raise RuntimeError('no access_token in refresh response')
                # Some providers (Spotify) don't always return a new refresh_token
                new_refresh = refreshed.get('refresh_token')
                expires_at = self._oauth_expires_at(refreshed.get('expires_in'))
                scope = refreshed.get('scope') or token['scope']
                await loop.run_in_executor(
                    None, self.db.oauth_save_token,
                    user['id'], provider, access_token, new_refresh, expires_at, scope
                )
                token = {
                    'access_token': access_token,
                    'expires_at': expires_at,
                    'scope': scope,
                }
            except Exception as e:
                logger.error(f"OAuth refresh failed for {provider} user {user['id']}: {e}")
                return web.json_response({
                    'success': False,
                    'error': 'Token expired and refresh failed - reconnect required'
                }, status=401)

        return web.json_response({
            'success': True,
            'access_token': token['access_token'],
            'expires_at': token['expires_at'],
            'scope': token['scope'],
        })

    async def handle_oauth_status(self, request: web.Request) -> web.Response:
        """Lightweight 'am I connected?' check without exposing the token."""
        provider = request.match_info['provider']
        if not self._oauth_provider_config(provider):
            return web.json_response({'success': False, 'error': 'Unknown provider'}, status=404)

        user = self.verify_token(request)
        if not user:
            return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

        loop = asyncio.get_event_loop()
        token = await loop.run_in_executor(
            None, self.db.oauth_get_token, user['id'], provider
        )
        return web.json_response({
            'success': True,
            'connected': bool(token),
            'expires_at': token['expires_at'] if token else None,
            'scope': token['scope'] if token else None,
        })

    async def handle_oauth_disconnect(self, request: web.Request) -> web.Response:
        """Forget stored tokens for this user/provider."""
        provider = request.match_info['provider']
        if not self._oauth_provider_config(provider):
            return web.json_response({'success': False, 'error': 'Unknown provider'}, status=404)

        user = self.verify_token(request)
        if not user:
            return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

        loop = asyncio.get_event_loop()
        deleted = await loop.run_in_executor(
            None, self.db.oauth_delete_token, user['id'], provider
        )
        return web.json_response({'success': True, 'deleted': deleted})

    # ---- OAuth helpers ----

    async def _oauth_exchange_code(self, provider: str, cfg: Dict, code: str) -> Dict:
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': self._oauth_redirect_uri(provider),
        }
        return await self._oauth_token_request(cfg, data)

    async def _oauth_refresh(self, _provider: str, cfg: Dict, refresh_token: str) -> Dict:
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
        }
        return await self._oauth_token_request(cfg, data)

    async def _oauth_token_request(self, cfg: Dict, data: Dict) -> Dict:
        import aiohttp
        headers = {'Accept': 'application/json'}
        auth = None
        if cfg.get('token_auth_style') == 'basic':
            auth = aiohttp.BasicAuth(cfg['client_id'], cfg['client_secret'])
        else:
            data['client_id'] = cfg['client_id']
            data['client_secret'] = cfg['client_secret']

        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(cfg['token_url'], data=data, headers=headers, auth=auth) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(f"token endpoint {resp.status}: {text[:300]}")
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    raise RuntimeError(f"non-JSON token response: {text[:300]}")

    @staticmethod
    def _oauth_expires_at(expires_in) -> Optional[str]:
        if not expires_in:
            return None
        try:
            from datetime import timedelta
            return (datetime.now() + timedelta(seconds=int(expires_in) - 30)).isoformat()
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _oauth_is_expired(expires_at: Optional[str]) -> bool:
        if not expires_at:
            return False
        try:
            return datetime.now() >= datetime.fromisoformat(expires_at)
        except (ValueError, TypeError):
            return True

    async def _oauth_notify_ws(self, user_id: int, provider: str) -> None:
        """Push 'oauth_connected' to the user's WS if connected. Best-effort."""
        try:
            ws_server = getattr(self, 'ws_server', None)
            if not ws_server:
                return
            send = getattr(ws_server, 'send_to_user', None)
            if not send:
                return
            payload = {'type': 'oauth_connected', 'provider': provider}
            result = send(user_id, payload)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.warning(f"OAuth WS notify failed: {e}")

    @staticmethod
    def _oauth_html_page(title: str, body: str) -> web.Response:
        html = (
            "<!DOCTYPE html><html lang='en'><head>"
            "<meta charset='utf-8'>"
            f"<title>{title}</title>"
            "<style>body{font-family:system-ui,sans-serif;max-width:480px;"
            "margin:80px auto;padding:0 16px;line-height:1.5}"
            "h1{font-size:1.4rem}code{background:#eee;padding:2px 4px;border-radius:3px}"
            "</style></head><body>"
            f"<h1>{title}</h1><p>{body}</p>"
            "</body></html>"
        )
        return web.Response(text=html, content_type='text/html')

    async def start(self):
        """Start the HTTP server"""
        ssl_context = self._create_ssl_context()
        protocol = "https" if ssl_context else "http"

        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port, ssl_context=ssl_context)
        await site.start()
        logger.info(f"HTTP API Server started on {protocol}://{self.host}:{self.port}")


if __name__ == "__main__":
    import asyncio

    server = TitanNetHTTPServer(host='0.0.0.0', port=8000)

    async def run_server():
        await server.start()
        await asyncio.Future()  # Run forever

    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("HTTP server stopped by user")
    except Exception as e:
        logger.error(f"HTTP server error: {e}", exc_info=True)
