"""
Titan-Net Server - Database Models
SQLite database models for user accounts, messages, rooms, and repository
"""

import sqlite3
import hashlib
import secrets
import random
from datetime import datetime
from typing import Optional, List, Dict, Any
import json


class Database:
    def __init__(self, db_path: str = "database/titannet.db"):
        self.db_path = db_path
        self.init_database()

    def get_connection(self):
        """Get database connection"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_database(self):
        """Initialize database schema"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                titan_number INTEGER UNIQUE NOT NULL,
                full_name TEXT,
                created_at TEXT NOT NULL,
                last_login TEXT,
                is_admin INTEGER DEFAULT 0,
                blog_url TEXT,
                status TEXT DEFAULT 'offline'
            )
        """)

        # Private messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS private_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                recipient_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                read INTEGER DEFAULT 0,
                FOREIGN KEY (sender_id) REFERENCES users(id),
                FOREIGN KEY (recipient_id) REFERENCES users(id)
            )
        """)

        # Chat rooms table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                creator_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                room_type TEXT DEFAULT 'text',
                password_hash TEXT,
                is_private INTEGER DEFAULT 0,
                FOREIGN KEY (creator_id) REFERENCES users(id)
            )
        """)

        # Room messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS room_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                FOREIGN KEY (room_id) REFERENCES chat_rooms(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Room members table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS room_members (
                room_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at TEXT NOT NULL,
                PRIMARY KEY (room_id, user_id),
                FOREIGN KEY (room_id) REFERENCES chat_rooms(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Application repository table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_repository (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                category TEXT NOT NULL,
                version TEXT,
                author_id INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                file_size INTEGER,
                uploaded_at TEXT NOT NULL,
                approved INTEGER DEFAULT 0,
                approved_by INTEGER,
                approved_at TEXT,
                downloads INTEGER DEFAULT 0,
                metadata TEXT,
                FOREIGN KEY (author_id) REFERENCES users(id),
                FOREIGN KEY (approved_by) REFERENCES users(id)
            )
        """)

        # Sessions table for WebSocket connections
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                connected_at TEXT NOT NULL,
                last_activity TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        conn.commit()
        conn.close()

    def generate_unique_titan_number(self) -> int:
        """Generate unique 5-digit Titan number"""
        conn = self.get_connection()
        cursor = conn.cursor()

        max_attempts = 10000
        for _ in range(max_attempts):
            titan_number = random.randint(10000, 99999)
            cursor.execute("SELECT id FROM users WHERE titan_number = ?", (titan_number,))
            if cursor.fetchone() is None:
                conn.close()
                return titan_number

        conn.close()
        raise ValueError("Could not generate unique Titan number")

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash password using SHA-256"""
        return hashlib.sha256(password.encode()).hexdigest()

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """Verify password against hash"""
        return Database.hash_password(password) == password_hash

    def create_user(self, username: str, password: str, full_name: Optional[str] = None) -> Dict[str, Any]:
        """Create new user account"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            titan_number = self.generate_unique_titan_number()
            password_hash = self.hash_password(password)
            created_at = datetime.now().isoformat()

            cursor.execute("""
                INSERT INTO users (username, password_hash, titan_number, full_name, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (username, password_hash, titan_number, full_name, created_at))

            user_id = cursor.lastrowid
            conn.commit()

            return {
                "success": True,
                "user_id": user_id,
                "username": username,
                "titan_number": titan_number,
                "created_at": created_at
            }
        except sqlite3.IntegrityError as e:
            conn.rollback()
            return {
                "success": False,
                "error": "Username already exists"
            }
        finally:
            conn.close()

    def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """Authenticate user and return user data"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, username, password_hash, titan_number, full_name, is_admin, blog_url
            FROM users WHERE username = ?
        """, (username,))

        user = cursor.fetchone()

        if user and self.verify_password(password, user['password_hash']):
            # Update last login
            cursor.execute("""
                UPDATE users SET last_login = ?, status = 'online'
                WHERE id = ?
            """, (datetime.now().isoformat(), user['id']))
            conn.commit()

            conn.close()
            return {
                "id": user['id'],
                "username": user['username'],
                "titan_number": user['titan_number'],
                "full_name": user['full_name'],
                "is_admin": bool(user['is_admin']),
                "blog_url": user['blog_url']
            }

        conn.close()
        return None

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user by ID"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, username, titan_number, full_name, is_admin, blog_url, status
            FROM users WHERE id = ?
        """, (user_id,))

        user = cursor.fetchone()
        conn.close()

        if user:
            return dict(user)
        return None

    def get_user_by_titan_number(self, titan_number: int) -> Optional[Dict[str, Any]]:
        """Get user by Titan number"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, username, titan_number, full_name, is_admin, blog_url, status
            FROM users WHERE titan_number = ?
        """, (titan_number,))

        user = cursor.fetchone()
        conn.close()

        if user:
            return dict(user)
        return None

    def update_user_status(self, user_id: int, status: str):
        """Update user online status"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))
        conn.commit()
        conn.close()

    def get_online_users(self) -> List[Dict[str, Any]]:
        """Get list of online users"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, username, titan_number, full_name, status
            FROM users WHERE status = 'online'
        """)

        users = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return users

    def send_private_message(self, sender_id: int, recipient_id: int, message: str) -> Dict[str, Any]:
        """Send private message"""
        conn = self.get_connection()
        cursor = conn.cursor()

        sent_at = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO private_messages (sender_id, recipient_id, message, sent_at)
            VALUES (?, ?, ?, ?)
        """, (sender_id, recipient_id, message, sent_at))

        message_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return {
            "id": message_id,
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "message": message,
            "sent_at": sent_at
        }

    def get_private_messages(self, user1_id: int, user2_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        """Get private messages between two users"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT pm.*,
                   u1.username as sender_username,
                   u2.username as recipient_username
            FROM private_messages pm
            JOIN users u1 ON pm.sender_id = u1.id
            JOIN users u2 ON pm.recipient_id = u2.id
            WHERE (pm.sender_id = ? AND pm.recipient_id = ?)
               OR (pm.sender_id = ? AND pm.recipient_id = ?)
            ORDER BY pm.sent_at DESC
            LIMIT ?
        """, (user1_id, user2_id, user2_id, user1_id, limit))

        messages = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return messages

    def create_chat_room(self, name: str, creator_id: int, description: str = "",
                        room_type: str = "text", password: Optional[str] = None) -> Dict[str, Any]:
        """Create new chat room"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            created_at = datetime.now().isoformat()
            password_hash = self.hash_password(password) if password else None
            is_private = 1 if password else 0

            cursor.execute("""
                INSERT INTO chat_rooms (name, description, creator_id, created_at, room_type, password_hash, is_private)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, description, creator_id, created_at, room_type, password_hash, is_private))

            room_id = cursor.lastrowid

            # Add creator as member
            cursor.execute("""
                INSERT INTO room_members (room_id, user_id, joined_at)
                VALUES (?, ?, ?)
            """, (room_id, creator_id, created_at))

            conn.commit()
            conn.close()

            return {
                "success": True,
                "room_id": room_id,
                "name": name,
                "room_type": room_type
            }
        except sqlite3.IntegrityError:
            conn.rollback()
            conn.close()
            return {
                "success": False,
                "error": "Room name already exists"
            }

    def join_chat_room(self, room_id: int, user_id: int, password: Optional[str] = None) -> Dict[str, Any]:
        """Join chat room"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Check if room exists and get password hash
        cursor.execute("SELECT password_hash FROM chat_rooms WHERE id = ?", (room_id,))
        room = cursor.fetchone()

        if not room:
            conn.close()
            return {"success": False, "error": "Room not found"}

        # Verify password if room is private
        if room['password_hash']:
            if not password or not self.verify_password(password, room['password_hash']):
                conn.close()
                return {"success": False, "error": "Invalid password"}

        try:
            joined_at = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO room_members (room_id, user_id, joined_at)
                VALUES (?, ?, ?)
            """, (room_id, user_id, joined_at))
            conn.commit()
            conn.close()
            return {"success": True}
        except sqlite3.IntegrityError:
            conn.close()
            return {"success": False, "error": "Already a member"}

    def leave_chat_room(self, room_id: int, user_id: int):
        """Leave chat room"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM room_members WHERE room_id = ? AND user_id = ?", (room_id, user_id))
        conn.commit()
        conn.close()

    def delete_chat_room(self, room_id: int, user_id: int) -> bool:
        """Delete chat room (only by creator)"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Check if user is creator
        cursor.execute("SELECT creator_id FROM chat_rooms WHERE id = ?", (room_id,))
        room = cursor.fetchone()

        if not room or room['creator_id'] != user_id:
            conn.close()
            return False

        # Delete room and all related data
        cursor.execute("DELETE FROM room_messages WHERE room_id = ?", (room_id,))
        cursor.execute("DELETE FROM room_members WHERE room_id = ?", (room_id,))
        cursor.execute("DELETE FROM chat_rooms WHERE id = ?", (room_id,))

        conn.commit()
        conn.close()
        return True

    def send_room_message(self, room_id: int, user_id: int, message: str) -> Dict[str, Any]:
        """Send message to chat room"""
        conn = self.get_connection()
        cursor = conn.cursor()

        sent_at = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO room_messages (room_id, user_id, message, sent_at)
            VALUES (?, ?, ?, ?)
        """, (room_id, user_id, message, sent_at))

        message_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return {
            "id": message_id,
            "room_id": room_id,
            "user_id": user_id,
            "message": message,
            "sent_at": sent_at
        }

    def get_room_messages(self, room_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        """Get messages from chat room"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT rm.*, u.username, u.titan_number
            FROM room_messages rm
            JOIN users u ON rm.user_id = u.id
            WHERE rm.room_id = ?
            ORDER BY rm.sent_at DESC
            LIMIT ?
        """, (room_id, limit))

        messages = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return messages

    def get_available_rooms(self) -> List[Dict[str, Any]]:
        """Get list of all chat rooms"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT cr.*, u.username as creator_username,
                   (SELECT COUNT(*) FROM room_members WHERE room_id = cr.id) as member_count
            FROM chat_rooms cr
            JOIN users u ON cr.creator_id = u.id
        """)

        rooms = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return rooms

    def add_app_to_repository(self, name: str, description: str, category: str,
                             version: str, author_id: int, file_path: str,
                             file_size: int, metadata: Dict[str, Any]) -> int:
        """Add application to repository (pending approval)"""
        conn = self.get_connection()
        cursor = conn.cursor()

        uploaded_at = datetime.now().isoformat()
        metadata_json = json.dumps(metadata)

        cursor.execute("""
            INSERT INTO app_repository
            (name, description, category, version, author_id, file_path, file_size, uploaded_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, description, category, version, author_id, file_path, file_size, uploaded_at, metadata_json))

        app_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return app_id

    def approve_app(self, app_id: int, admin_id: int) -> bool:
        """Approve application in repository"""
        conn = self.get_connection()
        cursor = conn.cursor()

        approved_at = datetime.now().isoformat()
        cursor.execute("""
            UPDATE app_repository
            SET approved = 1, approved_by = ?, approved_at = ?
            WHERE id = ?
        """, (admin_id, approved_at, app_id))

        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success

    def get_pending_apps(self) -> List[Dict[str, Any]]:
        """Get apps pending approval"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT ar.*, u.username as author_username
            FROM app_repository ar
            JOIN users u ON ar.author_id = u.id
            WHERE ar.approved = 0
            ORDER BY ar.uploaded_at DESC
        """)

        apps = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return apps

    def get_approved_apps(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get approved apps from repository"""
        conn = self.get_connection()
        cursor = conn.cursor()

        if category:
            cursor.execute("""
                SELECT ar.*, u.username as author_username
                FROM app_repository ar
                JOIN users u ON ar.author_id = u.id
                WHERE ar.approved = 1 AND ar.category = ?
                ORDER BY ar.uploaded_at DESC
            """, (category,))
        else:
            cursor.execute("""
                SELECT ar.*, u.username as author_username
                FROM app_repository ar
                JOIN users u ON ar.author_id = u.id
                WHERE ar.approved = 1
                ORDER BY ar.uploaded_at DESC
            """)

        apps = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return apps

    def increment_app_downloads(self, app_id: int):
        """Increment download counter"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE app_repository SET downloads = downloads + 1 WHERE id = ?", (app_id,))
        conn.commit()
        conn.close()

    def update_user_blog(self, user_id: int, blog_url: str):
        """Update user blog URL"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET blog_url = ? WHERE id = ?", (blog_url, user_id))
        conn.commit()
        conn.close()
