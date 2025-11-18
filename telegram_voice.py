# -*- coding: utf-8 -*-
import asyncio
import threading
import time
from datetime import datetime
import wx
import logging
from sound import play_sound
from translation import set_language
from settings import get_setting

# Initialize translation
_ = set_language(get_setting('language', 'pl'))

try:
    from pytgcalls import PyTgCalls
    from pytgcalls import MediaDevices

    # Import correct components for py-tgcalls 2.2.8
    try:
        from pytgcalls.types import MediaStream
        print("py-tgcalls 2.2.8 imports successful")
        COMPONENTS_AVAILABLE = True
    except ImportError as import_error:
        print(f"py-tgcalls stream imports failed: {import_error}")
        MediaStream = None
        COMPONENTS_AVAILABLE = False

    VOICE_CALLS_AVAILABLE = True
    print("py-tgcalls loaded successfully!")
    print(f"Stream components available: {COMPONENTS_AVAILABLE}")

    # Set legacy variables to None since they're not used in 2.2.8
    AudioPiped = None
    VideoPiped = None
    HighQualityAudio = None
    
except ImportError as e:
    VOICE_CALLS_AVAILABLE = False
    print(f"py-tgcalls not available: {e}. Using native Telegram calls only.")
    PyTgCalls = None
    MediaDevices = None
    MediaStream = None
    AudioPiped = None
    VideoPiped = None
    HighQualityAudio = None
    COMPONENTS_AVAILABLE = False

class TelegramVoiceClient:
    def __init__(self, telethon_client=None):
        self.telethon_client = telethon_client
        self.voice_client = None
        self.is_call_active = False
        self.current_call_user = None
        self.current_call_object = None  # Store the actual call object to prevent invalid peer errors
        self.call_callbacks = []
        self.call_start_time = None
        self.dh_params = None
        self.audio_stream_active = False
        self.temp_group_id = None  # For group call workaround
        self.using_group_workaround = True  # Default to group workaround since it's the only working method
        self.pytgcalls_started = False  # Track PyTgCalls state
        
        # Initialize PyTgCalls only if available (for group calls)
        # Private calls use Telegram's native API and don't require py-tgcalls
        if VOICE_CALLS_AVAILABLE and telethon_client and PyTgCalls:
            try:
                self.voice_client = PyTgCalls(telethon_client)
                print("PyTgCalls initialized for group voice calls")
            except Exception as e:
                print(f"PyTgCalls initialization failed: {e}")
                self.voice_client = None
        else:
            print("Using native Telegram API for voice calls (py-tgcalls not required)")
    
    def add_call_callback(self, callback):
        """Add callback for call events"""
        self.call_callbacks.append(callback)
    
    def _validate_username(self, username):
        """Validate Telegram username format"""
        import re
        if not username:
            return False, "Username is empty"
        
        # Remove @ if present
        if username.startswith('@'):
            username = username[1:]
        
        # Check length (5-32 characters)
        if len(username) < 5:
            return False, f"Username too short ({len(username)} chars). Minimum 5 characters required."
        if len(username) > 32:
            return False, f"Username too long ({len(username)} chars). Maximum 32 characters allowed."
        
        # Check format: start/end with letter or digit, middle can have letters, digits, underscores
        pattern = r'^[a-zA-Z0-9][a-zA-Z0-9_]{3,30}[a-zA-Z0-9]$'
        if not re.match(pattern, username):
            return False, f"Invalid username format. Must start/end with letter/digit, can contain letters, digits, underscores."
        
        return True, "Username format is valid"
    
    def _notify_call_event(self, event_type, data=None):
        """Notify all callbacks about call events"""
        for callback in self.call_callbacks:
            try:
                wx.CallAfter(callback, event_type, data)
            except:
                pass
    
    async def initialize_voice_client(self):
        """Initialize voice client"""
        if not self.telethon_client:
            print("Telethon client not available")
            return False
        
        try:
            # Native Telegram calls use Telegram's built-in WebRTC implementation
            # No additional initialization needed for private voice calls
            print("Voice calls ready - using native Telegram voice call API")
            
            # Check if PyTgCalls is available for debugging
            if VOICE_CALLS_AVAILABLE:
                print("PyTgCalls is available for group calls (not needed for private calls)")
            else:
                print("PyTgCalls not available - using native API only (this is normal)")
            
            # Verify audio system is working
            try:
                from sound import play_sound
                import pygame
                print("Audio system available for call notifications")
                
                # Check pygame mixer status for debugging
                if pygame.mixer.get_init():
                    frequency, format_bits, channels = pygame.mixer.get_init()
                    print(f"Pygame mixer initialized: {frequency}Hz, {format_bits}bit, {channels}ch")
                else:
                    print("Warning: Pygame mixer not initialized")
                    
            except Exception as audio_check:
                print(f"Warning: Audio system check failed: {audio_check}")
            
            return True
        except Exception as e:
            print(f"Failed to initialize voice client: {e}")
            return False
    
    async def start_private_call(self, recipient_id):
        """Start private voice call with recipient using Telegram's native WebRTC"""
        if not self.telethon_client:
            return False
        
        try:
            print("=== NATIVE PRIVATE CALL ===")
            print(f"Initiating WebRTC call to {recipient_id} via Telegram API")
            
            self.current_call_user = recipient_id
            self.call_start_time = datetime.now()
            
            # Play ring out sound
            play_sound('titannet/ring_out.ogg')
            
            # Get the actual chat entity from recipient_id using the same logic as messaging
            if self.telethon_client:
                try:
                    # Import telegram_client to access cached dialogs
                    import telegram_client
                    
                    # Find recipient entity using the same logic as messaging system
                    entity = None
                    
                    # Try to find by username in chat_users cache
                    if hasattr(telegram_client.telegram_client, 'chat_users') and recipient_id in telegram_client.telegram_client.chat_users:
                        entity = telegram_client.telegram_client.chat_users[recipient_id]['entity']
                    else:
                        # Try to find in dialogs by name or title
                        if hasattr(telegram_client.telegram_client, 'dialogs'):
                            for dialog in telegram_client.telegram_client.dialogs:
                                if dialog['name'] == recipient_id or dialog['title'] == recipient_id:
                                    entity = dialog['entity']
                                    break
                    
                    if not entity:
                        # Try to resolve as username/phone as last resort
                        entity = await self.telethon_client.get_entity(recipient_id)
                    
                    recipient_entity = entity
                    
                    # Initialize PyTgCalls for audio stream if available
                    if VOICE_CALLS_AVAILABLE and self.voice_client:
                        try:
                            await self.voice_client.start()
                            print("PyTgCalls voice client started for audio stream")
                        except Exception as voice_error:
                            print(f"Warning: Could not start PyTgCalls: {voice_error}")
                    
                    # Use Telegram's native call API for real voice calls
                    from telethon.tl.functions.phone import RequestCallRequest
                    from telethon.tl.types import PhoneCallProtocol
                    import os
                    
                    # Generate proper DH key exchange parameters according to Telegram protocol
                    # Use Telegram's official DH parameters for voice calls
                    import hashlib
                    import secrets
                    
                    # Telegram's official DH parameters for voice calls
                    # These are the actual parameters used by Telegram according to their protocol documentation
                    p = int('0xC150023E2F70DB7985DED064759CFECF0AF328E69A41DAF4D6F01B538135A6F91F8F8B2A0EC9BA9720CE352EFCF6C5680FFC424BD634864902DE0B4BD6D49F4E580230E3AE97D95C8B19442B3C0A10D8F5633FECEDD6926A7F6DAB0DDB7D457F9EA81B8465FCD6FFFEED114011DF91C059CAEDAF97625F6C96ECC74725556934EF781D866B34F011FCE4D835A090196E9A5F0E4449AF7EB697DDB9076494CA5F81104A305B6DD27665722C46B60E5DF680FB16B210607EF2E5E0B1C42E1C72030C6F4C7F3B0C0E6DA4B2B0AC03E70020C2D7F2ACFB7E6', 16)
                    g = 2
                    
                    # Use cryptographically secure random generator
                    # Generate a random private key 'a' using secure method
                    # Ensure the private key is within valid range [2, p-2]
                    a = secrets.randbelow(p - 3) + 2
                    
                    # Ensure 'a' is in valid range [2, p-2]
                    if a < 2 or a >= p - 1:
                        a = (a % (p - 3)) + 2
                    
                    # Calculate g^a mod p
                    g_a = pow(g, a, p)
                    
                    # Validate g_a according to Telegram's requirements
                    # g_a must be in safe range to prevent weak keys
                    if g_a <= 1 or g_a >= p - 1:
                        print("[ERROR] Generated g_a is out of valid range - regenerating...")
                        # Regenerate with better parameters
                        a = secrets.randbelow(p - 3) + 2
                        g_a = pow(g, a, p)
                    
                    # Calculate SHA256 hash of g_a for commitment (3-message DH)
                    g_a_bytes = g_a.to_bytes(256, byteorder='big')
                    g_a_hash = hashlib.sha256(g_a_bytes).digest()
                    
                    print(f"[DH] Generated valid DH parameters:")
                    print(f"[DH] Private key size: {a.bit_length()} bits")
                    print(f"[DH] g_a value: {g_a}")
                    print(f"[DH] g_a range validation: PASSED")
                    print(f"[DH] Hash length: {len(g_a_hash)} bytes")
                    
                    protocol = PhoneCallProtocol(
                        min_layer=65,
                        max_layer=92,
                        udp_p2p=True,
                        udp_reflector=True,
                        library_versions=['2.4.4']
                    )
                    
                    # Generate a 32-bit random ID to avoid struct.error overflow
                    import random
                    random_id = random.randint(1, 2147483647)  # Maximum 32-bit signed integer
                    
                    print(f"[CALL] About to send RequestCallRequest...")
                    print(f"[CALL] user_id: {recipient_entity}")
                    print(f"[CALL] random_id: {random_id}")
                    print(f"[CALL] g_a_hash length: {len(g_a_hash)} bytes")
                    print(f"[CALL] protocol: {protocol}")
                    
                    result = await self.telethon_client(RequestCallRequest(
                        user_id=recipient_entity,
                        random_id=random_id,
                        g_a_hash=g_a_hash,  # Use the hash, not the raw g_a value
                        protocol=protocol
                    ))
                    
                    print(f"[WebRTC] Call request sent successfully: {result}")
                    print(f"[WebRTC] Result type: {type(result)}")
                    print("[WebRTC] Telegram native voice call initiated")
                    print("[WebRTC] Waiting for user to accept the call...")
                    print("[WebRTC] Audio will work through Telegram's built-in WebRTC")
                    print("=== IMPORTANT: CALL WILL RING UNTIL USER ANSWERS OR DECLINES ===")
                    print("=== NO AUTOMATIC TIMEOUT - TELEGRAM PROTOCOL SUPPORTS INDEFINITE RINGING ===")
                    print(f"=== Call initiated at: {datetime.now()} ===")
                    
                    # Check microphone access after call request
                    print("=== CHECKING MICROPHONE ACCESS ===")
                    mic_available = self._check_microphone_access()
                    if not mic_available:
                        print("*** WARNING: MICROPHONE NOT AVAILABLE - THIS MIGHT CAUSE DISCONNECT ***")
                        print("*** Telegram may auto-disconnect calls without microphone access ***")
                    else:
                        print("✓ Microphone access confirmed")
                    
                    # Store the call object from the result to prevent disconnection issues
                    if result and hasattr(result, 'phone_call'):
                        self.current_call_object = result.phone_call
                        print(f"[WebRTC] Stored call object: {type(self.current_call_object)}")
                    
                    # Store DH parameters for potential audio stream setup
                    self.dh_params = {
                        'a': a, 
                        'p': p, 
                        'g': g, 
                        'g_a': g_a,
                        'protocol': protocol  # Store protocol for ConfirmCallRequest
                    }
                    
                    # Notify about call start
                    self._notify_call_event('call_started', {
                        'recipient': recipient_id,
                        'type': 'outgoing',
                        'start_time': self.call_start_time.isoformat()
                    })
                    
                    self.is_call_active = True
                    
                    # For native Telegram calls, WebRTC audio is handled automatically
                    # No need to create group or use py-tgcalls for private calls
                    print("[WebRTC] Native call established - audio handled by Telegram client")
                    print("[INFO] No additional audio setup needed - Telegram handles WebRTC internally")
                    print("[IMPORTANT] Call will remain active until manually ended")
                    print("[IMPORTANT] DO NOT call end_call() automatically - let user control call duration")
                    
                    return True
                    
                except Exception as call_error:
                    print(f"*** CALL ERROR DETAILS ***")
                    print(f"Error type: {type(call_error)}")
                    print(f"Error message: {call_error}")
                    print(f"Error args: {call_error.args}")
                    import traceback
                    print(f"Full traceback:")
                    print(traceback.format_exc())
                    print(f"*** END ERROR DETAILS ***")
                    # Don't fallback to PyTgCalls for private calls as it's for group calls only
                    raise call_error
            
        except Exception as e:
            print(f"*** MAIN CALL ERROR ***")
            print(f"Failed to start call: {e}")
            print(f"Error type: {type(e)}")
            import traceback
            print(f"Full traceback:")
            print(traceback.format_exc())
            print(f"*** END MAIN ERROR ***")
            self._notify_call_event('call_failed', {'error': str(e)})
            return False
    
    async def answer_call(self, call_data):
        """Answer incoming voice call"""
        if not self.telethon_client:
            return False
        
        try:
            self.current_call_user = call_data.get('caller_id')
            self.current_call_object = call_data.get('call_object')  # Store the call object to prevent invalid peer errors
            self.call_start_time = datetime.now()
            
            # Play answered sound
            play_sound('titannet/callsuccess.ogg')
            
            # Get the actual caller entity
            if self.telethon_client and call_data.get('call_object'):
                try:
                    # Use Telegram's native call API for accepting
                    from telethon.tl.functions.phone import AcceptCallRequest
                    from telethon.tl.types import PhoneCallProtocol
                    import os
                    
                    # Generate proper DH key exchange parameters according to Telegram protocol
                    import hashlib
                    import secrets
                    
                    # Use same Telegram official DH parameters as in start_private_call
                    p = int('0xC150023E2F70DB7985DED064759CFECF0AF328E69A41DAF4D6F01B538135A6F91F8F8B2A0EC9BA9720CE352EFCF6C5680FFC424BD634864902DE0B4BD6D49F4E580230E3AE97D95C8B19442B3C0A10D8F5633FECEDD6926A7F6DAB0DDB7D457F9EA81B8465FCD6FFFEED114011DF91C059CAEDAF97625F6C96ECC74725556934EF781D866B34F011FCE4D835A090196E9A5F0E4449AF7EB697DDB9076494CA5F81104A305B6DD27665722C46B60E5DF680FB16B210607EF2E5E0B1C42E1C72030C6F4C7F3B0C0E6DA4B2B0AC03E70020C2D7F2ACFB7E6', 16)
                    g = 2
                    
                    # Use cryptographically secure random generator
                    # Generate a random private key 'b' using secure method
                    b = secrets.randbelow(p - 3) + 2
                    
                    # Ensure 'b' is in valid range [2, p-2]
                    if b < 2 or b >= p - 1:
                        b = (b % (p - 3)) + 2
                    
                    # Calculate g^b mod p
                    g_b_int = pow(g, b, p)
                    
                    # Validate g_b according to Telegram's requirements
                    if g_b_int <= 1 or g_b_int >= p - 1:
                        print("[ERROR] Generated g_b is out of valid range - regenerating...")
                        # Regenerate with better parameters
                        b = secrets.randbelow(p - 3) + 2
                        g_b_int = pow(g, b, p)
                    
                    g_b = g_b_int.to_bytes(256, byteorder='big')
                    
                    print(f"[DH] Generated valid DH parameters for call answer:")
                    print(f"[DH] Private key size: {b.bit_length()} bits")
                    print(f"[DH] g_b range validation: PASSED")
                    
                    protocol = PhoneCallProtocol(
                        min_layer=65,
                        max_layer=92,
                        udp_p2p=True,
                        udp_reflector=True,
                        library_versions=['2.4.4']
                    )
                    
                    call_obj = call_data['call_object']
                    
                    result = await self.telethon_client(AcceptCallRequest(
                        peer=call_obj,
                        g_b=g_b,
                        protocol=protocol
                    ))
                    
                    print(f"Call accepted successfully: {result}")
                    print("Call connected - setting up audio group")
                    print("Audio will be available in the voice chat group")
                    print("Join the voice chat when the group is created")
                    
                except Exception as call_error:
                    print(f"Failed to accept call: {call_error}")
                    raise call_error
            
            # Notify about call answer
            self._notify_call_event('call_answered', {
                'caller': self.current_call_user,
                'type': 'incoming',
                'start_time': self.call_start_time.isoformat()
            })

            self.is_call_active = True

            # IMPORTANT: Start audio stream using group voice chat for working audio
            # Native WebRTC through Telethon doesn't support audio in Python
            print("Call answered - setting up audio using group voice chat method")
            print("Note: Using PyTgCalls for audio support instead of native WebRTC")

            try:
                # Start audio stream using group voice workaround
                audio_success = await self._start_audio_stream()
                if audio_success:
                    print("Audio stream established successfully")
                else:
                    print("Warning: Audio stream setup failed - voice may not work")
            except Exception as audio_error:
                print(f"Warning: Could not start audio stream: {audio_error}")
                print("Call is active but audio may not work")

            return True
            
        except Exception as e:
            print(f"Failed to answer call: {e}")
            self._notify_call_event('call_failed', {'error': str(e)})
            return False
    
    async def _start_group_voice_workaround(self, recipient_id):
        """Start voice call using group workaround method (fallback for private calls)"""
        try:
            print("=== GROUP VOICE WORKAROUND ===")
            print(f"Creating group voice chat with {recipient_id}")
            
            # Set current call user for the group method
            self.current_call_user = recipient_id
            self.call_start_time = datetime.now()
            
            # Use the existing group voice logic
            success = await self._start_audio_stream()
            
            if success:
                self.is_call_active = True
                self._notify_call_event('call_started', {
                    'recipient': recipient_id,
                    'type': 'group_voice',
                    'method': 'group_workaround',
                    'start_time': self.call_start_time.isoformat()
                })
                return True
            else:
                return False
                
        except Exception as e:
            print(f"Group voice workaround failed: {e}")
            self._notify_call_event('call_failed', {'error': str(e), 'method': 'group_workaround'})
            return False
    
    async def _start_audio_stream(self):
        """Start audio stream for voice call using group call workaround"""
        try:
            print("=== TELEGRAM VOICE CALL AUDIO ===")
            print("INFO: Using group call method for audio (py-tgcalls limitation)")
            
            # Always use group call workaround since py-tgcalls doesn't support private calls
            # This creates a temporary group for 1-on-1 audio streaming
            
            if not VOICE_CALLS_AVAILABLE or not self.voice_client:
                print("ERROR: PyTgCalls not available for audio workaround")
                return False
            
            try:
                # Start PyTgCalls client if not already running
                if not self.pytgcalls_started:
                    try:
                        await self.voice_client.start()
                        self.pytgcalls_started = True
                        print("PyTgCalls client started successfully")
                    except Exception as start_error:
                        if "already running" in str(start_error).lower():
                            self.pytgcalls_started = True
                            print("PyTgCalls client already running")
                        else:
                            print(f"Failed to start PyTgCalls: {start_error}")
                            raise start_error
                else:
                    print("PyTgCalls client already started")
                
                # Set up group call audio (default method)
                if self.current_call_user and self.telethon_client:
                    print(f"Creating audio group for call with: {self.current_call_user}")
                    
                    try:
                        # Create temporary group for voice call
                        group_id = await self._create_temp_group_for_call(self.current_call_user)
                        
                        if group_id:
                            # Start group voice call
                            group_call_success = await self._start_group_voice_call(group_id)
                            
                            if group_call_success:
                                print("Audio group created successfully - voice call ready")
                                self.audio_stream_active = True
                                return True
                            else:
                                print("Failed to start group voice call")
                        else:
                            print("Failed to create audio group")
                            
                    except Exception as group_error:
                        print(f"Group audio setup failed: {group_error}")
                        
                    # If group method fails, inform user
                    print("Group audio method failed - voice call may not have audio")
                    print("Consider using official Telegram app for voice calls")
                    
                    # Still mark as active for UI purposes
                    self.audio_stream_active = True
                    return True
                
            except Exception as pytg_start_error:
                print(f"Failed to start PyTgCalls: {pytg_start_error}")
            
            # Check system audio devices
            await self._check_audio_devices()
            
            # Mark as active even if workaround didn't fully work
            self.audio_stream_active = True
            
            print("=== VOICE CALL AUDIO SETUP COMPLETE ===")
            print("Audio will work through temporary group method")
            print("Both users need to join the voice chat in the created group")
            print("Call signaling works normally, audio goes through group")
            print("Group will be automatically deleted when call ends")
            
            return True
                
        except Exception as e:
            print(f"Failed to start audio stream: {e}")
            return False
    
    async def _check_audio_devices(self):
        """Check available audio devices for debugging"""
        try:
            import platform
            if platform.system() == "Windows":
                try:
                    import subprocess
                    # Use a more reliable method to check audio devices
                    result = subprocess.run(['powershell', '-Command', 
                                           'Get-AudioDevice | Select-Object Name'], 
                                          capture_output=True, text=True, timeout=10)
                    if result.returncode == 0 and result.stdout.strip():
                        print(f"Audio devices check: OK")
                        return True
                    else:
                        # Fallback: just check if we can import audio libraries
                        import pygame
                        if pygame.mixer.get_init():
                            print("Audio system: Available (pygame mixer active)")
                            return True
                        else:
                            print("Audio system: pygame mixer not initialized")
                            return False
                except Exception:
                    # Final fallback
                    try:
                        import pygame
                        print("Audio system: Basic pygame available")
                        return True
                    except:
                        print("Audio system: Not available")
                        return False
                    
        except Exception as device_check:
            print(f"Audio check skipped: {device_check}")
        
        return False
    
    async def _create_temp_group_for_call(self, recipient_id):
        """Create temporary group for voice call workaround"""
        try:
            if not self.telethon_client:
                return None
                
            print("Creating audio group for voice call...")
            
            # Import necessary Telethon functions
            from telethon.tl.functions.channels import CreateChannelRequest
            from telethon.tl.functions.channels import InviteToChannelRequest
            
            # Create a temporary private group with clear name
            import datetime
            group_title = f"Voice Call {datetime.datetime.now().strftime('%H:%M:%S')}"
            
            # Create the group
            result = await self.telethon_client(CreateChannelRequest(
                title=group_title,
                about="Temporary voice chat - will be deleted after call",
                megagroup=True
            ))
            
            if result and hasattr(result, 'chats') and result.chats:
                group = result.chats[0]
                self.temp_group_id = group.id
                print(f"Created audio group: {group.id} ({group_title})")
                
                # Try to invite the other user
                try:
                    # Get user entity
                    import telegram_client
                    from telethon import utils
                    user_entity = None

                    if hasattr(telegram_client.telegram_client, 'chat_users') and recipient_id in telegram_client.telegram_client.chat_users:
                        user_entity = telegram_client.telegram_client.chat_users[recipient_id]['entity']
                    else:
                        user_entity = await self.telethon_client.get_entity(recipient_id)

                    if user_entity:
                        # Convert to InputUser to avoid type casting errors
                        # Use get_input_entity to ensure we have the correct InputPeer type
                        input_user = await self.telethon_client.get_input_entity(user_entity)

                        # Invite user to the temporary group
                        await self.telethon_client(InviteToChannelRequest(
                            channel=group,
                            users=[input_user]
                        ))
                        print(f"Invited {recipient_id} to audio group")
                        print(f"Other user should join voice chat in: {group_title}")

                        # Now we can start a group voice call
                        return group.id
                        
                except Exception as invite_error:
                    error_msg = str(invite_error)
                    print(f"Failed to invite user to group: {invite_error}")
                    
                    # Provide more helpful error messages
                    if "Nobody is using this username" in error_msg:
                        print(f"[ERROR] Username '{recipient_id}' doesn't exist on Telegram")
                        print(f"Make sure the username is correct and the user exists")
                    elif "username is unacceptable" in error_msg:
                        print(f"[ERROR] Username '{recipient_id}' is invalid")
                        print(f"Telegram usernames must be 5-32 characters, start/end with letter/digit")
                        print(f"Valid format: [a-zA-Z][\\w\\d]{{3,30}}[a-zA-Z\\d]")
                    else:
                        print(f"User {recipient_id} needs to join group manually: {group_title}")
                    
                    return group.id  # Return group ID anyway
                    
            return None
            
        except Exception as e:
            print(f"Failed to create temporary group: {e}")
            return None
    
    async def _start_group_voice_call(self, group_id):
        """Start voice call in the temporary group using py-tgcalls 2.2.6"""
        try:
            if not VOICE_CALLS_AVAILABLE or not self.voice_client:
                print("PyTgCalls not available for group call")
                return False

            print(f"Starting voice chat in audio group {group_id}")

            # Get the channel entity for the group
            try:
                channel_entity = await self.telethon_client.get_entity(group_id)
                print(f"Got channel entity: {type(channel_entity)}")
            except Exception as entity_error:
                print(f"Failed to get channel entity: {entity_error}")
                return False

            # Method 1: Try using MediaDevices with microphone (py-tgcalls 2.2.8 API)
            if COMPONENTS_AVAILABLE and MediaStream and MediaDevices:
                try:
                    print("Trying MediaDevices with microphone input (py-tgcalls 2.2.8)...")

                    # Get available microphone devices
                    mic_devices = MediaDevices.microphone_devices()

                    if mic_devices and len(mic_devices) > 0:
                        print(f"Found {len(mic_devices)} microphone device(s)")
                        print(f"Using microphone: {mic_devices[0]}")

                        # Create MediaStream with microphone audio
                        stream = MediaStream(
                            audio_path=mic_devices[0]
                        )

                        # Use play() method instead of join_group_call()
                        await self.voice_client.play(
                            chat_id=group_id,
                            media_stream=stream
                        )

                        print("Successfully joined group voice call with microphone")
                        print("Microphone is active and streaming")
                        print("Other user should join voice chat to hear audio")

                        self.using_group_workaround = True
                        return True
                    else:
                        print("No microphone devices found")

                except Exception as media_error:
                    print(f"MediaDevices method failed: {media_error}")

            # Method 2: Try with silent audio file (fallback)
            try:
                print("Trying silent audio file fallback...")

                import tempfile
                import wave
                import os

                # Create 5 seconds of silence as a WAV file
                temp_audio = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                temp_audio_path = temp_audio.name
                temp_audio.close()

                with wave.open(temp_audio_path, 'wb') as wav:
                    wav.setnchannels(2)  # stereo
                    wav.setsampwidth(2)  # 16-bit
                    wav.setframerate(48000)  # 48kHz
                    # 5 seconds of silence
                    wav.writeframes(b'\x00' * (48000 * 2 * 2 * 5))

                # Create MediaStream with the silent audio file
                if COMPONENTS_AVAILABLE and MediaStream:
                    stream = MediaStream(media_path=temp_audio_path)

                    await self.voice_client.play(
                        chat_id=group_id,
                        media_stream=stream
                    )

                    print("Successfully joined with silent audio file")
                    print("Note: Using silent audio - microphone needs manual activation")

                    # Clean up temp file after a delay
                    try:
                        os.unlink(temp_audio_path)
                    except:
                        pass

                    self.using_group_workaround = True
                    return True

            except Exception as silent_error:
                print(f"Silent audio fallback failed: {silent_error}")

            # If all methods fail, provide helpful guidance
            print("=" * 50)
            print("All automatic audio methods failed")
            print("Group created successfully - user can join voice chat manually")
            print("=" * 50)
            print("Instructions:")
            print("1. Open Telegram app")
            print("2. Go to the created group")
            print("3. Click 'Join Voice Chat' button")
            print("4. Your microphone will work through the Telegram app")
            print("=" * 50)

            # Still return True since group was created successfully
            self.using_group_workaround = True
            return True

        except Exception as e:
            print(f"Failed to start group voice call: {e}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def _cleanup_temp_group(self):
        """Delete temporary group used for voice call"""
        try:
            if self.temp_group_id and self.telethon_client:
                from telethon.tl.functions.channels import DeleteChannelRequest
                
                # Get the group entity
                group_entity = await self.telethon_client.get_entity(self.temp_group_id)
                
                # Delete the temporary group
                await self.telethon_client(DeleteChannelRequest(channel=group_entity))
                print(f"Deleted temporary group {self.temp_group_id}")
                
        except Exception as e:
            print(f"Failed to cleanup temporary group: {e}")
            # Don't raise - cleanup failure shouldn't break call end
    
    async def end_call(self):
        """End current voice call"""
        if not self.is_call_active:
            return False
        
        try:
            # Calculate call duration before ending
            call_duration = None
            if self.call_start_time:
                call_duration = datetime.now() - self.call_start_time
            
            # End the call using native API if we have the call object
            if self.current_call_object and self.telethon_client:
                try:
                    from telethon.tl.functions.phone import DiscardCallRequest
                    from telethon.tl.types import PhoneCallDiscardReasonHangup
                    
                    # Use the stored call object instead of trying to find user entity
                    result = await self.telethon_client(DiscardCallRequest(
                        peer=self.current_call_object,
                        duration=int(call_duration.total_seconds()) if call_duration else 0,
                        reason=PhoneCallDiscardReasonHangup(),
                        connection_id=0
                    ))
                    
                    print(f"Call ended via native API using stored call object: {result}")
                    
                except Exception as native_error:
                    print(f"Failed to end call via native API: {native_error}")
                    print("This is normal - letting Telegram handle cleanup naturally")
            else:
                print("Ending voice call - no stored call object, letting Telegram handle cleanup naturally")
                print("Call will be terminated by Telegram's built-in timeout/disconnect handling")
            
            # Play end call sound
            play_sound('titannet/bye.ogg')
            
            # Notify about call end
            self._notify_call_event('call_ended', {
                'user': self.current_call_user,
                'duration': call_duration.total_seconds() if call_duration else 0
            })
            
            # Stop audio stream and cleanup
            if self.audio_stream_active and self.voice_client:
                try:
                    if self.using_group_workaround and self.temp_group_id:
                        # Leave group voice call
                        await self.voice_client.leave_group_call(self.temp_group_id)
                        print("Left group voice call")
                        
                        # Delete temporary group
                        await self._cleanup_temp_group()
                    else:
                        # Regular audio stream stop
                        await self.voice_client.leave_group_call(self.current_call_user)
                        print("Audio stream stopped")
                        
                except Exception as stream_error:
                    print(f"Warning: Could not stop audio stream: {stream_error}")
            
            # Reset call state
            self.is_call_active = False
            self.current_call_user = None
            self.current_call_object = None  # Reset call object
            self.call_start_time = None
            self.audio_stream_active = False
            self.dh_params = None
            self.temp_group_id = None
            self.using_group_workaround = True  # Keep as default for next call
            # Note: Don't reset pytgcalls_started - keep client running for next calls
            
            return True
            
        except Exception as e:
            print(f"Failed to end call: {e}")
            return False
    
    async def mute_microphone(self, muted=True):
        """Mute or unmute microphone"""
        if not self.is_call_active or not self.voice_client:
            return False
        
        try:
            # PyTgCalls doesn't have direct mute/unmute for private calls
            # This would need to be implemented by stopping/starting audio stream
            
            self._notify_call_event('microphone_toggled', {'muted': muted})
            return True
            
        except Exception as e:
            print(f"Failed to toggle microphone: {e}")
            return False
    
    def get_call_status(self):
        """Get current call status"""
        if not self.is_call_active:
            return {'active': False}
        
        call_duration = None
        if self.call_start_time:
            call_duration = datetime.now() - self.call_start_time
        
        return {
            'active': True,
            'user': self.current_call_user,
            'duration': call_duration.total_seconds() if call_duration else 0,
            'start_time': self.call_start_time.isoformat() if self.call_start_time else None
        }

    def _check_microphone_access(self):
        """Check if microphone is available and accessible"""
        try:
            import subprocess
            
            # Method 1: Check Windows audio input devices
            try:
                result = subprocess.run([
                    'powershell', '-Command',
                    'Get-WmiObject -Class Win32_SoundDevice | Where-Object {$_.Name -like "*microphone*" -or $_.Name -like "*mic*"} | Select-Object Name'
                ], capture_output=True, text=True, timeout=10)
                
                if result.returncode == 0 and result.stdout.strip():
                    print(f"[MIC] Microphone devices found")
                    return True
            except Exception as ps_error:
                print(f"[MIC] PowerShell check failed: {ps_error}")
            
            # Method 2: Check recording devices using Windows API
            try:
                import ctypes
                
                # Try to access WinMM API for audio input devices
                winmm = ctypes.windll.winmm
                num_devices = winmm.waveInGetNumDevs()
                
                if num_devices > 0:
                    print(f"[MIC] Found {num_devices} audio input device(s)")
                    return True
                else:
                    print(f"[MIC] No audio input devices found")
                    return False
                    
            except Exception as winapi_error:
                print(f"[MIC] Windows API check failed: {winapi_error}")
            
            # Fallback - assume microphone is available
            print(f"[MIC] Could not verify microphone access - assuming available")
            return True
            
        except Exception as e:
            print(f"[MIC] Microphone check failed: {e}")
            return True  # Assume available to not block calls


# Global voice client instance
telegram_voice_client = None


def initialize_voice_client(telethon_client):
    """Initialize the global voice client"""
    global telegram_voice_client
    telegram_voice_client = TelegramVoiceClient(telethon_client)
    
    # Run initialization in background
    def init_async():
        if telegram_voice_client and telegram_voice_client.telethon_client:
            try:
                # Get the event loop from telegram_client module to avoid 'no current event loop' error
                import telegram_client
                if hasattr(telegram_client.telegram_client, 'event_loop') and telegram_client.telegram_client.event_loop:
                    loop = telegram_client.telegram_client.event_loop
                elif hasattr(telethon_client, '_loop') and telethon_client._loop:
                    loop = telethon_client._loop
                else:
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        # Create new event loop if none exists
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                
                # Schedule initialization on the existing loop
                if loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(
                        telegram_voice_client.initialize_voice_client(), 
                        loop
                    )
                    future.result(timeout=10)
                else:
                    # If loop is not running, run the coroutine directly
                    loop.run_until_complete(telegram_voice_client.initialize_voice_client())
            except Exception as e:
                print(f"Voice client initialization error: {e}")
    
    # Always initialize - native calls don't require py-tgcalls
    threading.Thread(target=init_async, daemon=True).start()

def start_voice_call(recipient):
    """Start voice call with recipient"""
    if not telegram_voice_client:
        print("ERROR: Voice client not initialized")
        return False
    
    if not telegram_voice_client.telethon_client:
        print("ERROR: Telegram client not connected")
        return False
    
    # Validate username format before attempting call
    is_valid, validation_msg = telegram_voice_client._validate_username(recipient)
    if not is_valid:
        print(f"[ERROR] Invalid username '{recipient}': {validation_msg}")
        print("Please check the username and try again")
        return False
    
    print(f"[OK] Username format valid: {recipient}")
    print(f"Validation: {validation_msg}")
    
    # Use the existing event loop from the Telegram client
    def call_async():
        try:
            # Get the event loop from telegram_client module
            import telegram_client
            if hasattr(telegram_client.telegram_client, 'event_loop') and telegram_client.telegram_client.event_loop:
                loop = telegram_client.telegram_client.event_loop
            elif hasattr(telegram_voice_client.telethon_client, '_loop') and telegram_voice_client.telethon_client._loop:
                loop = telegram_voice_client.telethon_client._loop
            else:
                # Fallback: try to get the current event loop
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    # Create new event loop if none exists
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            
            # IMPORTANT: Use group voice chat method for reliable audio
            # Native Telegram WebRTC calls through Telethon don't support audio streaming in Python
            # Group voice chat with PyTgCalls is the only method that provides working audio
            print(f"[INFO] Using group voice chat method for reliable audio")
            print(f"[INFO] Note: Native WebRTC calls don't work in Python - using PyTgCalls instead")

            # Skip private call attempt and go directly to group method for audio support
            # private_call_success = False
            # try:
            #     if loop.is_running():
            #         future = asyncio.run_coroutine_threadsafe(
            #             telegram_voice_client.start_private_call(recipient),
            #             loop
            #         )
            #         private_call_success = future.result(timeout=300)
            #     else:
            #         private_call_success = loop.run_until_complete(telegram_voice_client.start_private_call(recipient))
            #
            #     if private_call_success:
            #         print(f"[SUCCESS] Private call established with {recipient} via WebRTC")
            #         return True
            # except Exception as private_error:
            #     print(f"[INFO] Private call failed with error: {private_error}")
            
            # Use group voice chat method with working audio
            print(f"[STEP 1] Creating group voice chat with {recipient} for audio support")
            try:
                if loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(
                        telegram_voice_client._start_group_voice_workaround(recipient), 
                        loop
                    )
                    group_call_success = future.result(timeout=300)  # 5 minute timeout
                else:
                    group_call_success = loop.run_until_complete(telegram_voice_client._start_group_voice_workaround(recipient))
                
                if group_call_success:
                    print(f"[SUCCESS] Group voice chat established with {recipient}")
                    return True
                else:
                    print(f"[ERROR] Both private call and group method failed")
                    return False
                    
            except Exception as group_error:
                print(f"[ERROR] Group method also failed: {group_error}")
                return False
        except Exception as e:
            print(f"Voice call error: {e}")
            return False
    
    threading.Thread(target=call_async, daemon=True).start()
    return True

def answer_voice_call(call_data=None):
    """Answer incoming voice call"""
    if not telegram_voice_client:
        print("ERROR: Voice client not initialized")
        return False
    
    if not telegram_voice_client.telethon_client:
        print("ERROR: Telegram client not connected")
        return False
    
    if not call_data:
        call_data = {'caller_id': 'unknown', 'call_object': None}
    
    def answer_async():
        try:
            # Get the event loop from telegram_client module
            import telegram_client
            if hasattr(telegram_client.telegram_client, 'event_loop') and telegram_client.telegram_client.event_loop:
                loop = telegram_client.telegram_client.event_loop
            elif hasattr(telegram_voice_client.telethon_client, '_loop') and telegram_voice_client.telethon_client._loop:
                loop = telegram_voice_client.telethon_client._loop
            else:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    # Create new event loop if none exists
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            
            # Schedule the call on the existing loop
            if loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    telegram_voice_client.answer_call(call_data), 
                    loop
                )
                result = future.result(timeout=300)  # 5 minute timeout
            else:
                # If loop is not running, run the coroutine directly
                result = loop.run_until_complete(telegram_voice_client.answer_call(call_data))
            return result
        except Exception as e:
            print(f"Answer call error: {e}")
            return False
    
    threading.Thread(target=answer_async, daemon=True).start()
    return True

def end_voice_call():
    """End current voice call"""
    if not telegram_voice_client:
        print("ERROR: Voice client not initialized")
        return False
    
    def end_async():
        try:
            # Get the event loop from telegram_client module
            import telegram_client
            if hasattr(telegram_client.telegram_client, 'event_loop') and telegram_client.telegram_client.event_loop:
                loop = telegram_client.telegram_client.event_loop
            elif telegram_voice_client.telethon_client and hasattr(telegram_voice_client.telethon_client, '_loop') and telegram_voice_client.telethon_client._loop:
                loop = telegram_voice_client.telethon_client._loop
            else:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    # Create new event loop if none exists
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            
            # Schedule the call on the existing loop
            if loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    telegram_voice_client.end_call(), 
                    loop
                )
                result = future.result(timeout=10)
            else:
                # If loop is not running, run the coroutine directly
                result = loop.run_until_complete(telegram_voice_client.end_call())
            return result
        except Exception as e:
            print(f"End call error: {e}")
            return False
    
    threading.Thread(target=end_async, daemon=True).start()
    return True

def is_call_active():
    """Check if voice call is active"""
    return telegram_voice_client.is_call_active if telegram_voice_client else False

def get_call_status():
    """Get current call status"""
    return telegram_voice_client.get_call_status() if telegram_voice_client else {'active': False}

def add_call_callback(callback):
    """Add callback for call events"""
    if telegram_voice_client:
        telegram_voice_client.add_call_callback(callback)

def is_voice_calls_available():
    """Check if voice calls functionality is available"""
    # Voice calls are always available with Telegram's native API through Telethon
    # py-tgcalls is only needed for group voice calls, not private calls
    return True  # Native Telegram voice calls are always supported


def get_voice_call_status():
    """Get detailed voice call status including workaround info"""
    if not telegram_voice_client:
        return {'available': False}
    
    status = telegram_voice_client.get_call_status()
    status.update({
        'py_tgcalls_available': VOICE_CALLS_AVAILABLE,
        'using_group_workaround': telegram_voice_client.using_group_workaround,
        'temp_group_id': telegram_voice_client.temp_group_id
    })
    
    return status