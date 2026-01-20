"""
Titan-Net Test Client
Simple command-line client for testing server functionality
"""

import asyncio
import websockets
import json
import sys
from typing import Optional


class TitanNetClient:
    def __init__(self, host: str = 'localhost', port: int = 8001):
        self.uri = f"ws://{host}:{port}"
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.session_id: Optional[str] = None
        self.user_data: Optional[dict] = None
        self.running = False

    async def connect(self):
        """Connect to server"""
        try:
            self.websocket = await websockets.connect(self.uri)
            print(f"Connected to {self.uri}")
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False

    async def send(self, message: dict):
        """Send message to server"""
        if not self.websocket:
            print("Not connected")
            return

        try:
            await self.websocket.send(json.dumps(message))
        except Exception as e:
            print(f"Send failed: {e}")

    async def receive(self):
        """Receive messages from server"""
        try:
            async for message in self.websocket:
                data = json.loads(message)
                await self.handle_message(data)
        except websockets.exceptions.ConnectionClosed:
            print("Connection closed")
            self.running = False
        except Exception as e:
            print(f"Receive error: {e}")
            self.running = False

    async def handle_message(self, data: dict):
        """Handle received message"""
        msg_type = data.get('type')

        if msg_type == 'login_response':
            if data.get('success'):
                self.session_id = data.get('session_id')
                self.user_data = data.get('user')
                print(f"\nLogin successful!")
                print(f"Username: {self.user_data['username']}")
                print(f"Titan Number: {self.user_data['titan_number']}")
                print(f"Online users: {len(data.get('online_users', []))}")
            else:
                print(f"\nLogin failed: {data.get('error')}")

        elif msg_type == 'register_response':
            if data.get('success'):
                print(f"\nRegistration successful!")
                print(f"Username: {data.get('username')}")
                print(f"Titan Number: {data.get('titan_number')}")
                print(f"You can now login")
            else:
                print(f"\nRegistration failed: {data.get('error')}")

        elif msg_type == 'private_message':
            print(f"\n[PM from {data.get('sender_username')} (#{data.get('sender_titan_number')})]")
            print(f"  {data.get('message')}")

        elif msg_type == 'room_message':
            print(f"\n[Room #{data.get('room_id')} - {data.get('username')}]")
            print(f"  {data.get('message')}")

        elif msg_type == 'user_status':
            print(f"\n[Status] {data.get('username')} is now {data.get('status')}")

        elif msg_type == 'room_created':
            if data.get('success'):
                print(f"\nRoom created! ID: {data.get('room_id')}")
            else:
                print(f"\nRoom creation failed: {data.get('error')}")

        elif msg_type == 'room_joined':
            if data.get('success'):
                print(f"\nJoined room #{data.get('room_id')}")
            else:
                print(f"\nFailed to join room: {data.get('error')}")

        elif msg_type == 'user_joined_room':
            print(f"\n[Room #{data.get('room_id')}] {data.get('username')} joined")

        elif msg_type == 'user_left_room':
            print(f"\n[Room #{data.get('room_id')}] {data.get('username')} left")

        elif msg_type == 'rooms_list':
            print(f"\nAvailable rooms:")
            for room in data.get('rooms', []):
                print(f"  #{room['id']} - {room['name']} ({room['room_type']}) - {room['member_count']} members")

        elif msg_type == 'online_users':
            print(f"\nOnline users:")
            for user in data.get('users', []):
                print(f"  {user['username']} (#{user['titan_number']})")

        elif msg_type == 'error':
            print(f"\nError: {data.get('error')}")

        else:
            print(f"\nReceived: {data}")

    async def register(self):
        """Register new account"""
        print("\n=== Register ===")
        username = input("Username: ")
        password = input("Password: ")
        full_name = input("Full name (optional): ")

        await self.send({
            "type": "register",
            "username": username,
            "password": password,
            "full_name": full_name if full_name else None
        })

    async def login(self):
        """Login to server"""
        print("\n=== Login ===")
        username = input("Username: ")
        password = input("Password: ")

        await self.send({
            "type": "login",
            "username": username,
            "password": password
        })

    async def send_private_message(self):
        """Send private message"""
        print("\n=== Send Private Message ===")
        titan_number = input("Recipient Titan Number: ")
        message = input("Message: ")

        await self.send({
            "type": "private_message",
            "recipient_titan_number": int(titan_number),
            "message": message
        })

    async def create_room(self):
        """Create chat room"""
        print("\n=== Create Room ===")
        name = input("Room name: ")
        description = input("Description: ")
        room_type = input("Type (text/voice) [text]: ") or "text"
        password = input("Password (optional): ")

        await self.send({
            "type": "create_room",
            "name": name,
            "description": description,
            "room_type": room_type,
            "password": password if password else None
        })

    async def join_room(self):
        """Join chat room"""
        print("\n=== Join Room ===")
        room_id = input("Room ID: ")
        password = input("Password (if required): ")

        await self.send({
            "type": "join_room",
            "room_id": int(room_id),
            "password": password if password else None
        })

    async def send_room_message(self):
        """Send message to room"""
        print("\n=== Send Room Message ===")
        room_id = input("Room ID: ")
        message = input("Message: ")

        await self.send({
            "type": "room_message",
            "room_id": int(room_id),
            "message": message
        })

    async def list_rooms(self):
        """List available rooms"""
        await self.send({"type": "get_rooms"})

    async def list_online_users(self):
        """List online users"""
        await self.send({"type": "get_online_users"})

    async def show_menu(self):
        """Show main menu"""
        print("\n" + "="*50)
        print("Titan-Net Test Client")
        print("="*50)
        if self.user_data:
            print(f"Logged in as: {self.user_data['username']} (#{self.user_data['titan_number']})")
        else:
            print("Not logged in")
        print("="*50)
        print("1. Register")
        print("2. Login")
        print("3. Send private message")
        print("4. Create room")
        print("5. Join room")
        print("6. Send room message")
        print("7. List rooms")
        print("8. List online users")
        print("9. Quit")
        print("="*50)

    async def run(self):
        """Run interactive client"""
        if not await self.connect():
            return

        self.running = True

        # Start receive task
        receive_task = asyncio.create_task(self.receive())

        try:
            while self.running:
                await self.show_menu()
                choice = input("\nChoice: ")

                if choice == '1':
                    await self.register()
                elif choice == '2':
                    await self.login()
                elif choice == '3':
                    if self.session_id:
                        await self.send_private_message()
                    else:
                        print("Please login first")
                elif choice == '4':
                    if self.session_id:
                        await self.create_room()
                    else:
                        print("Please login first")
                elif choice == '5':
                    if self.session_id:
                        await self.join_room()
                    else:
                        print("Please login first")
                elif choice == '6':
                    if self.session_id:
                        await self.send_room_message()
                    else:
                        print("Please login first")
                elif choice == '7':
                    if self.session_id:
                        await self.list_rooms()
                    else:
                        print("Please login first")
                elif choice == '8':
                    if self.session_id:
                        await self.list_online_users()
                    else:
                        print("Please login first")
                elif choice == '9':
                    print("Goodbye!")
                    self.running = False
                    break
                else:
                    print("Invalid choice")

                await asyncio.sleep(0.1)

        except KeyboardInterrupt:
            print("\nInterrupted by user")
        finally:
            self.running = False
            if self.websocket:
                await self.websocket.close()
            receive_task.cancel()


def main():
    """Main entry point"""
    host = sys.argv[1] if len(sys.argv) > 1 else 'localhost'
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8001

    client = TitanNetClient(host, port)

    try:
        asyncio.run(client.run())
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
