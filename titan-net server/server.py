"""
Titan-Net Server - Main WebSocket Server
Handles real-time messaging, chat rooms, and client connections
"""

import asyncio
import websockets
import json
import logging
from datetime import datetime
from typing import Dict, Set, Optional
import secrets
from models import Database

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


class TitanNetServer:
    def __init__(self, host: str = '0.0.0.0', port: int = 8001):
        self.host = host
        self.port = port
        self.db = Database()

        # Connected clients: {session_id: {"websocket": ws, "user_id": id, "username": name}}
        self.clients: Dict[str, Dict] = {}

        # Room voice channels: {room_id: {user_id: websocket}}
        self.voice_channels: Dict[int, Dict[int, websockets.WebSocketServerProtocol]] = {}

    async def register_client(self, websocket: websockets.WebSocketServerProtocol, user_data: Dict) -> str:
        """Register new client connection"""
        session_id = secrets.token_urlsafe(32)
        self.clients[session_id] = {
            "websocket": websocket,
            "user_id": user_data['id'],
            "username": user_data['username'],
            "titan_number": user_data['titan_number']
        }

        # Update user status to online
        self.db.update_user_status(user_data['id'], 'online')

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

            # Update user status to offline
            self.db.update_user_status(user_id, 'offline')

            del self.clients[session_id]
            logger.info(f"Client unregistered: {username} (Session: {session_id})")

            # Notify all clients about user offline
            await self.broadcast_user_status(user_id, 'offline')

    async def broadcast_user_status(self, user_id: int, status: str):
        """Broadcast user status change to all clients"""
        user = self.db.get_user_by_id(user_id)
        if not user:
            return

        message = {
            "type": "user_status",
            "user_id": user_id,
            "username": user['username'],
            "titan_number": user['titan_number'],
            "status": status
        }

        await self.broadcast(message)

    async def broadcast(self, message: Dict, exclude_session: Optional[str] = None):
        """Broadcast message to all connected clients"""
        disconnected = []
        for session_id, client in self.clients.items():
            if session_id == exclude_session:
                continue

            try:
                await client['websocket'].send(json.dumps(message))
            except websockets.exceptions.ConnectionClosed:
                disconnected.append(session_id)

        # Clean up disconnected clients
        for session_id in disconnected:
            await self.unregister_client(session_id)

    async def send_to_user(self, user_id: int, message: Dict):
        """Send message to specific user"""
        for client in self.clients.values():
            if client['user_id'] == user_id:
                try:
                    await client['websocket'].send(json.dumps(message))
                except websockets.exceptions.ConnectionClosed:
                    pass

    async def broadcast_to_room(self, room_id: int, message: Dict, exclude_user_id: Optional[int] = None):
        """Broadcast message to all members of a room"""
        # Get room members from database
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM room_members WHERE room_id = ?", (room_id,))
        member_ids = {row['user_id'] for row in cursor.fetchall()}
        conn.close()

        # Broadcast to members only
        for client in self.clients.values():
            if client['user_id'] == exclude_user_id:
                continue

            if client['user_id'] not in member_ids:
                continue

            try:
                await client['websocket'].send(json.dumps(message))
            except websockets.exceptions.ConnectionClosed:
                pass

    async def handle_login(self, websocket: websockets.WebSocketServerProtocol, data: Dict) -> Dict:
        """Handle login request"""
        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return {
                "type": "login_response",
                "success": False,
                "error": "Username and password required"
            }

        user = self.db.authenticate_user(username, password)

        if user:
            # Register client WITHOUT broadcasting yet
            session_id = secrets.token_urlsafe(32)
            self.clients[session_id] = {
                "websocket": websocket,
                "user_id": user['id'],
                "username": user['username'],
                "titan_number": user['titan_number']
            }

            # Update user status to online
            self.db.update_user_status(user['id'], 'online')

            logger.info(f"Client registered: {user['username']} (Session: {session_id})")

            # Get online users
            online_users = self.db.get_online_users()

            return {
                "type": "login_response",
                "success": True,
                "session_id": session_id,
                "user": user,
                "online_users": online_users,
                "broadcast_online": True  # Signal to broadcast after sending response
            }
        else:
            return {
                "type": "login_response",
                "success": False,
                "error": "Invalid username or password"
            }

    async def handle_register(self, websocket: websockets.WebSocketServerProtocol, data: Dict) -> Dict:
        """Handle registration request"""
        username = data.get('username')
        password = data.get('password')
        full_name = data.get('full_name')

        if not username or not password:
            return {
                "type": "register_response",
                "success": False,
                "error": "Username and password required"
            }

        result = self.db.create_user(username, password, full_name)

        return {
            "type": "register_response",
            **result
        }

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

        # Find recipient by Titan number if provided
        if recipient_titan_number:
            recipient = self.db.get_user_by_titan_number(recipient_titan_number)
            if recipient:
                recipient_id = recipient['id']

        if not recipient_id:
            return

        # Save message to database
        message_data = self.db.send_private_message(
            client['user_id'],
            recipient_id,
            message_text
        )

        # Send to recipient if online
        response = {
            "type": "private_message",
            "message_id": message_data['id'],
            "sender_id": client['user_id'],
            "sender_username": client['username'],
            "sender_titan_number": client['titan_number'],
            "message": message_text,
            "sent_at": message_data['sent_at']
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

        messages = self.db.get_private_messages(client['user_id'], other_user_id, limit)

        return {
            "type": "private_messages",
            "messages": messages
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

        result = self.db.create_chat_room(
            name, client['user_id'], description, room_type, password
        )

        response = {
            "type": "room_created",
            **result
        }

        await self.clients[session_id]['websocket'].send(json.dumps(response))

        # Broadcast new room to all clients
        if result.get('success'):
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

        result = self.db.join_chat_room(room_id, client['user_id'], password)

        response = {
            "type": "room_joined",
            "room_id": room_id,
            **result
        }

        await self.clients[session_id]['websocket'].send(json.dumps(response))

        # Notify room members
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

        self.db.leave_chat_room(room_id, client['user_id'])

        # Notify room members
        await self.broadcast_to_room(room_id, {
            "type": "user_left_room",
            "room_id": room_id,
            "user_id": client['user_id'],
            "username": client['username']
        })

    async def handle_delete_room(self, session_id: str, data: Dict):
        """Handle delete chat room"""
        client = self.clients.get(session_id)
        if not client:
            return

        room_id = data.get('room_id')
        if not room_id:
            return

        success = self.db.delete_chat_room(room_id, client['user_id'])

        response = {
            "type": "room_deleted",
            "room_id": room_id,
            "success": success
        }

        await self.clients[session_id]['websocket'].send(json.dumps(response))

        # Notify all clients
        if success:
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

        # Save message to database
        message_data = self.db.send_room_message(room_id, client['user_id'], message_text)

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
        """Handle get available rooms"""
        rooms = self.db.get_available_rooms()

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

        messages = self.db.get_room_messages(room_id, limit)

        return {
            "type": "room_messages",
            "room_id": room_id,
            "messages": messages
        }

    async def handle_get_online_users(self, session_id: str) -> Dict:
        """Handle get online users"""
        users = self.db.get_online_users()

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
            self.db.update_user_blog(client['user_id'], blog_url)

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

    async def handle_client(self, websocket: websockets.WebSocketServerProtocol):
        """Handle individual client connection"""
        session_id = None

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get('type')

                    # Handle authentication messages
                    if msg_type == 'login':
                        response = await self.handle_login(websocket, data)
                        if response.get('success'):
                            session_id = response['session_id']

                        # Send login response first
                        response_copy = response.copy()
                        response_copy.pop('broadcast_online', None)  # Remove internal flag
                        await websocket.send(json.dumps(response_copy))

                        # Now broadcast user online status if login was successful
                        if response.get('broadcast_online'):
                            user = response.get('user', {})
                            await self.broadcast_user_status(user['id'], 'online')

                    elif msg_type == 'register':
                        response = await self.handle_register(websocket, data)
                        await websocket.send(json.dumps(response))

                        # Broadcast new user registration to all online users
                        if response.get('success'):
                            await self.broadcast({
                                "type": "user_registered",
                                "username": data.get('username'),
                                "titan_number": response.get('titan_number')
                            })

                    # Authenticated-only messages
                    elif session_id:
                        if msg_type == 'private_message':
                            await self.handle_private_message(session_id, data)

                        elif msg_type == 'get_messages':
                            response = await self.handle_get_messages(session_id, data)
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

                        elif msg_type == 'get_online_users':
                            response = await self.handle_get_online_users(session_id)
                            await websocket.send(json.dumps(response))

                        elif msg_type == 'update_blog':
                            await self.handle_update_blog(session_id, data)

                        elif msg_type == 'voice_signal':
                            await self.handle_voice_signal(session_id, data)

                        elif msg_type == 'ping':
                            await websocket.send(json.dumps({"type": "pong"}))

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

    async def start(self):
        """Start the WebSocket server"""
        logger.info(f"Starting Titan-Net Server on {self.host}:{self.port}")

        async with websockets.serve(self.handle_client, self.host, self.port, ping_interval=30, ping_timeout=10):
            logger.info("Server started successfully")
            await asyncio.Future()  # Run forever


if __name__ == "__main__":
    server = TitanNetServer(host='0.0.0.0', port=8001)

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
