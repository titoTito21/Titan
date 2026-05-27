"""
Titan-Net HTTP API Server
Handles file uploads, downloads, and repository management
"""

from aiohttp import web, MultipartReader
import aiohttp_cors
import asyncio
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
from models import Database

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
            client_max_size=100 * 1024 * 1024,  # 100MB max
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
        """Verify authentication token with database lookup"""
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return None

        token = auth_header[7:]  # Remove 'Bearer ' prefix

        try:
            # Token format: base64(user_id:username)
            import base64
            decoded = base64.b64decode(token).decode('utf-8')
            user_id_str, username = decoded.split(':', 1)
            user_id = int(user_id_str)

            # CRITICAL FIX: Verify user exists in database
            user = self.db.get_user_by_id(user_id)
            if not user or user['username'] != username:
                logger.warning(f"Token verification failed: invalid user {user_id}:{username}")
                return None

            return {
                'id': user['id'],
                'username': user['username'],
                'is_admin': user.get('is_admin', False)
            }
        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"Token verification failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Token verification error: {e}")
            return None

    def verify_admin(self, user_id: int) -> bool:
        """Verify if user is admin"""
        user = self.db.get_user_by_id(user_id)
        return user and user.get('is_admin', False)

    async def handle_upload(self, request: web.Request) -> web.Response:
        """Handle file upload to repository"""
        MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

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

            # Read metadata
            metadata = {}
            file_data = None
            filename = None

            async for part in reader:
                if part.name == 'metadata':
                    metadata_text = await part.text()
                    metadata = json.loads(metadata_text)
                elif part.name == 'file':
                    filename = part.filename
                    file_data = await part.read()

            if not file_data or not filename:
                return web.json_response({
                    'success': False,
                    'error': 'File data required'
                }, status=400)

            # Validate file size after reading
            if len(file_data) > MAX_FILE_SIZE:
                return web.json_response({
                    'success': False,
                    'error': 'File too large'
                }, status=413)

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

            # Sanitize filename
            import re
            filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)

            # Whitelist allowed package extensions. The repository is for TCE
            # data packages — never raw executables. .exe / .msi / .bat / .ps1
            # / .sh / .dll / etc. are rejected up front so an attacker cannot
            # smuggle a binary through the upload endpoint.
            ALLOWED_EXTENSIONS = ('.tcepackage', '.zip', '.7z')
            file_ext = os.path.splitext(filename)[1].lower()
            if file_ext not in ALLOWED_EXTENSIONS:
                return web.json_response({
                    'success': False,
                    'error': (
                        f'Invalid file type: {file_ext or "(no extension)"}. '
                        f'Allowed: {", ".join(ALLOWED_EXTENSIONS)}'
                    )
                }, status=400)

            # Generate file hash
            file_hash = hashlib.sha256(file_data).hexdigest()
            stored_filename = f"{file_hash}{file_ext}"

            # Save to pending directory with error handling
            file_path = os.path.join(self.upload_dir, 'pending', stored_filename)
            try:
                with open(file_path, 'wb') as f:
                    f.write(file_data)
            except OSError as e:
                logger.error(f"Failed to write file: {e}")
                return web.json_response({
                    'success': False,
                    'error': 'Failed to save file'
                }, status=500)

            # Add to database (writer executor — keeps the aiohttp loop responsive
            # while the @_serialized_write retry/backoff runs on db-writer thread).
            app_id = await self.db.run_write_async(
                self.db.add_app_to_repository,
                metadata['name'], metadata['description'], metadata['category'],
                metadata['version'], user['id'], file_path, len(file_data), metadata,
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

            if not title or not content:
                return web.json_response({
                    'success': False,
                    'error': 'Title and content required'
                }, status=400)

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.db.create_forum_topic, title, content, user['id'], category
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
                None, self.db.get_forum_topics, category, limit, user_id
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

    async def handle_promote_moderator(self, request: web.Request) -> web.Response:
        """Promote user to moderator (developer only)"""
        try:
            user = self.verify_token(request)
            if not user:
                return web.json_response({'success': False, 'error': 'Authentication required'}, status=401)

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
            category = data.get('category')

            if not category:
                return web.json_response({'success': False, 'error': 'Category required'}, status=400)

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
