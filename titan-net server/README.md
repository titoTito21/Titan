# Titan-Net Server

Complete messaging and application repository server for TCE Launcher.

## Features

### User Authentication
- User registration with username, password, and optional full name
- Unique 5-digit Titan number assigned to each account (e.g., 69522)
- Secure password hashing with SHA-256
- Session management with WebSocket connections
- Admin user support

### Private Messaging
- Real-time private messages between users
- Message persistence in SQLite database
- Message history retrieval
- Online/offline status tracking
- Find users by Titan number

### Chat Rooms
- Text chat rooms with message history
- Voice chat support via WebRTC signaling
- Password-protected rooms
- Room creator can delete their rooms
- Room member management
- Real-time message broadcasting

### Application Repository
- Multi-category support:
  - Applications
  - Components
  - Sound themes
  - Games
  - TCE packages
  - Language packs
- File upload with metadata
- Admin approval queue
- Download tracking
- Search functionality
- Category filtering
- Author information

### Blog Integration
- Link WordPress or external blogs to user accounts
- Blog URL storage per user

## Installation

### Requirements
- Python 3.8 or higher
- pip package manager

### Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure server (optional):
Edit `config.py` or set environment variables:
```bash
# Server ports
export WEBSOCKET_PORT=8001
export HTTP_PORT=8000

# Database path
export DATABASE_PATH=database/titannet.db

# Upload directory
export UPLOAD_DIR=uploads
```

3. Start the server:

**Windows:**
```bash
start_server.bat
```

**Linux/Mac:**
```bash
chmod +x start_server.sh
./start_server.sh
```

Or manually:
```bash
python main.py
```

## API Documentation

### WebSocket API (Port 8001)

Connect to: `ws://server:8001`

#### Authentication

**Register:**
```json
{
  "type": "register",
  "username": "john_doe",
  "password": "secure_password",
  "full_name": "John Doe"
}
```

Response:
```json
{
  "type": "register_response",
  "success": true,
  "user_id": 1,
  "username": "john_doe",
  "titan_number": 69522,
  "created_at": "2025-01-20T10:00:00"
}
```

**Login:**
```json
{
  "type": "login",
  "username": "john_doe",
  "password": "secure_password"
}
```

Response:
```json
{
  "type": "login_response",
  "success": true,
  "session_id": "abc123...",
  "user": {
    "id": 1,
    "username": "john_doe",
    "titan_number": 69522,
    "full_name": "John Doe",
    "is_admin": false,
    "blog_url": null
  },
  "online_users": [...]
}
```

#### Private Messages

**Send message:**
```json
{
  "type": "private_message",
  "recipient_id": 2,
  "message": "Hello!"
}
```

Or by Titan number:
```json
{
  "type": "private_message",
  "recipient_titan_number": 12345,
  "message": "Hello!"
}
```

**Get message history:**
```json
{
  "type": "get_messages",
  "user_id": 2,
  "limit": 100
}
```

#### Chat Rooms

**Create room:**
```json
{
  "type": "create_room",
  "name": "General Chat",
  "description": "Main chat room",
  "room_type": "text",
  "password": "optional_password"
}
```

**Join room:**
```json
{
  "type": "join_room",
  "room_id": 1,
  "password": "if_required"
}
```

**Send room message:**
```json
{
  "type": "room_message",
  "room_id": 1,
  "message": "Hello everyone!"
}
```

**Leave room:**
```json
{
  "type": "leave_room",
  "room_id": 1
}
```

**Delete room (creator only):**
```json
{
  "type": "delete_room",
  "room_id": 1
}
```

**Get available rooms:**
```json
{
  "type": "get_rooms"
}
```

**Get room messages:**
```json
{
  "type": "get_room_messages",
  "room_id": 1,
  "limit": 100
}
```

#### Voice Chat

Voice chat uses WebRTC signaling. Send offer/answer/ICE candidates:

```json
{
  "type": "voice_signal",
  "room_id": 1,
  "target_user_id": 2,
  "signal": {
    "type": "offer",
    "sdp": "..."
  }
}
```

#### Other

**Get online users:**
```json
{
  "type": "get_online_users"
}
```

**Update blog URL:**
```json
{
  "type": "update_blog",
  "blog_url": "https://myblog.com"
}
```

**Ping:**
```json
{
  "type": "ping"
}
```

### HTTP API (Port 8000)

Base URL: `http://server:8000`

#### Authentication

Most endpoints require Bearer token authentication:
```
Authorization: Bearer <token>
```

Token format: Base64 encoded `user_id:username`

#### Endpoints

**Upload file to repository:**
```
POST /api/upload
Content-Type: multipart/form-data
Authorization: Bearer <token>

Fields:
- metadata: JSON with {name, description, category, version}
- file: Binary file data

Categories: application, component, sound_theme, game, tce_package, language_pack
```

**Get repository (approved apps):**
```
GET /api/repository
```

**Get category:**
```
GET /api/repository/{category}
```

**Get pending apps (admin only):**
```
GET /api/pending
Authorization: Bearer <token>
```

**Approve app (admin only):**
```
POST /api/approve/{app_id}
Authorization: Bearer <token>
```

**Download app:**
```
GET /api/download/{app_id}
```

**Delete app (admin/author only):**
```
DELETE /api/delete/{app_id}
Authorization: Bearer <token>
```

**Get statistics:**
```
GET /api/stats
```

**Search repository:**
```
GET /api/search?q=keyword&category=application
```

## Database Schema

### Tables

- **users** - User accounts with Titan numbers
- **private_messages** - Private message history
- **chat_rooms** - Chat room definitions
- **room_messages** - Room message history
- **room_members** - Room membership
- **app_repository** - Application repository
- **sessions** - Active WebSocket sessions

### Creating Admin User

Connect to the database and update a user:

```bash
sqlite3 database/titannet.db
```

```sql
UPDATE users SET is_admin = 1 WHERE username = 'admin';
```

## Directory Structure

```
titan-net server/
├── main.py              # Main entry point
├── server.py            # WebSocket server
├── http_server.py       # HTTP API server
├── models.py            # Database models
├── config.py            # Configuration
├── requirements.txt     # Python dependencies
├── README.md            # This file
├── start_server.bat     # Windows startup script
├── start_server.sh      # Linux/Mac startup script
├── database/            # SQLite database
│   └── titannet.db
├── uploads/             # Uploaded files
│   ├── pending/         # Pending approval
│   └── approved/        # Approved files
└── logs/                # Server logs
    ├── main.log
    ├── server.log
    └── http_server.log
```

## Security Notes

1. Change `SECRET_KEY` in production
2. Use HTTPS/WSS in production with reverse proxy (nginx, apache)
3. Implement rate limiting for API endpoints
4. Use proper JWT tokens instead of simple Base64 encoding
5. Enable database backups
6. Set up firewall rules

## Example Client Code

### Python WebSocket Client

```python
import asyncio
import websockets
import json

async def connect():
    uri = "ws://localhost:8001"

    async with websockets.connect(uri) as websocket:
        # Login
        await websocket.send(json.dumps({
            "type": "login",
            "username": "john_doe",
            "password": "password123"
        }))

        response = await websocket.recv()
        print(f"Login: {response}")

        # Send private message
        await websocket.send(json.dumps({
            "type": "private_message",
            "recipient_titan_number": 12345,
            "message": "Hello from Python!"
        }))

        # Listen for messages
        async for message in websocket:
            data = json.loads(message)
            print(f"Received: {data}")

asyncio.run(connect())
```

### Python HTTP Client

```python
import requests
import base64

# Generate token
user_id = 1
username = "john_doe"
token = base64.b64encode(f"{user_id}:{username}".encode()).decode()

# Upload file
files = {
    'metadata': ('', json.dumps({
        'name': 'My App',
        'description': 'Description',
        'category': 'application',
        'version': '1.0.0'
    })),
    'file': ('myapp.zip', open('myapp.zip', 'rb'))
}

headers = {'Authorization': f'Bearer {token}'}
response = requests.post('http://localhost:8000/api/upload', files=files, headers=headers)
print(response.json())
```

## Troubleshooting

**Port already in use:**
- Change ports in `config.py` or environment variables

**Database locked:**
- Close any database connections
- Restart the server

**WebSocket connection fails:**
- Check firewall settings
- Verify server is running
- Check server logs in `logs/` directory

**Upload fails:**
- Check file size (max 100MB by default)
- Verify category is valid
- Check upload directory permissions

## License

This server is part of TCE Launcher project.

## Support

For issues and questions, please contact the TCE Launcher development team.
