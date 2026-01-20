"""
Titan-Net HTTP API Server
Handles file uploads, downloads, and repository management
"""

from aiohttp import web, MultipartReader
import aiohttp_cors
import logging
import os
import json
import hashlib
from datetime import datetime
from typing import Dict, Optional
import mimetypes
from models import Database

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
    def __init__(self, host: str = '0.0.0.0', port: int = 8000, upload_dir: str = 'uploads'):
        self.host = host
        self.port = port
        self.upload_dir = upload_dir
        self.db = Database()

        # Create upload directory structure
        os.makedirs(upload_dir, exist_ok=True)
        os.makedirs(os.path.join(upload_dir, 'pending'), exist_ok=True)
        os.makedirs(os.path.join(upload_dir, 'approved'), exist_ok=True)

        self.app = web.Application(client_max_size=100 * 1024 * 1024)  # 100MB max
        self.setup_routes()
        self.setup_cors()

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
        self.app.router.add_post('/api/upload', self.handle_upload)
        self.app.router.add_get('/api/repository', self.handle_get_repository)
        self.app.router.add_get('/api/repository/{category}', self.handle_get_category)
        self.app.router.add_get('/api/pending', self.handle_get_pending)
        self.app.router.add_post('/api/approve/{app_id}', self.handle_approve)
        self.app.router.add_get('/api/download/{app_id}', self.handle_download)
        self.app.router.add_delete('/api/delete/{app_id}', self.handle_delete)
        self.app.router.add_get('/api/stats', self.handle_stats)
        self.app.router.add_get('/api/search', self.handle_search)

    def verify_token(self, request: web.Request) -> Optional[Dict]:
        """Verify authentication token"""
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return None

        token = auth_header[7:]  # Remove 'Bearer ' prefix

        # In a real implementation, verify JWT or session token
        # For now, we'll use a simple approach
        try:
            # Token format: base64(user_id:username)
            import base64
            decoded = base64.b64decode(token).decode('utf-8')
            user_id, username = decoded.split(':', 1)
            return {
                'id': int(user_id),
                'username': username
            }
        except:
            return None

    def verify_admin(self, user_id: int) -> bool:
        """Verify if user is admin"""
        user = self.db.get_user_by_id(user_id)
        return user and user.get('is_admin', False)

    async def handle_upload(self, request: web.Request) -> web.Response:
        """Handle file upload to repository"""
        try:
            # Verify authentication
            user = self.verify_token(request)
            if not user:
                return web.json_response({
                    'success': False,
                    'error': 'Authentication required'
                }, status=401)

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

            # Generate file hash
            file_hash = hashlib.sha256(file_data).hexdigest()
            file_ext = os.path.splitext(filename)[1]
            stored_filename = f"{file_hash}{file_ext}"

            # Save to pending directory
            file_path = os.path.join(self.upload_dir, 'pending', stored_filename)
            with open(file_path, 'wb') as f:
                f.write(file_data)

            # Add to database
            app_id = self.db.add_app_to_repository(
                name=metadata['name'],
                description=metadata['description'],
                category=metadata['category'],
                version=metadata['version'],
                author_id=user['id'],
                file_path=file_path,
                file_size=len(file_data),
                metadata=metadata
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

    async def handle_get_repository(self, request: web.Request) -> web.Response:
        """Get all approved apps from repository"""
        try:
            apps = self.db.get_approved_apps()

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
            apps = self.db.get_approved_apps(category=category)

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

            apps = self.db.get_pending_apps()

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

            # Get app info
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT file_path FROM app_repository WHERE id = ?", (app_id,))
            app = cursor.fetchone()
            conn.close()

            if not app:
                return web.json_response({
                    'success': False,
                    'error': 'App not found'
                }, status=404)

            # Move file from pending to approved
            old_path = app['file_path']
            if os.path.exists(old_path):
                filename = os.path.basename(old_path)
                new_path = os.path.join(self.upload_dir, 'approved', filename)
                os.rename(old_path, new_path)

                # Update database
                conn = self.db.get_connection()
                cursor = conn.cursor()
                cursor.execute("UPDATE app_repository SET file_path = ? WHERE id = ?", (new_path, app_id))
                conn.commit()
                conn.close()

            # Approve app
            success = self.db.approve_app(app_id, user['id'])

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

            if not app['approved']:
                return web.json_response({
                    'success': False,
                    'error': 'App not approved yet'
                }, status=403)

            file_path = app['file_path']
            if not os.path.exists(file_path):
                return web.json_response({
                    'success': False,
                    'error': 'File not found'
                }, status=404)

            # Increment download counter
            self.db.increment_app_downloads(app_id)

            # Determine content type
            content_type = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'

            # Send file
            return web.FileResponse(
                file_path,
                headers={
                    'Content-Disposition': f'attachment; filename="{app["name"]}"',
                    'Content-Type': content_type
                }
            )

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

            # Delete file
            file_path = app['file_path']
            if os.path.exists(file_path):
                os.remove(file_path)

            # Delete from database
            cursor.execute("DELETE FROM app_repository WHERE id = ?", (app_id,))
            conn.commit()
            conn.close()

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

    async def start(self):
        """Start the HTTP server"""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        logger.info(f"HTTP API Server started on {self.host}:{self.port}")


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
