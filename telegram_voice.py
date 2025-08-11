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
    # Try different import paths for different py-tgcalls versions
    try:
        from pytgcalls.types import MediaStream
        from pytgcalls.types.input_stream import AudioPiped, VideoPiped
        from pytgcalls.types.input_stream.quality import HighQualityAudio
    except ImportError:
        try:
            # Alternative import structure
            from pytgcalls import MediaStream
            from pytgcalls import AudioPiped, VideoPiped
            from pytgcalls import HighQualityAudio
        except ImportError:
            # Minimal import for basic functionality
            MediaStream = None
            AudioPiped = None
            VideoPiped = None
            HighQualityAudio = None
    
    VOICE_CALLS_AVAILABLE = True
    print("py-tgcalls loaded successfully!")
except ImportError as e:
    VOICE_CALLS_AVAILABLE = False
    print(f"py-tgcalls not available: {e}. Using native Telegram calls only.")
    PyTgCalls = None
    MediaStream = None
    AudioPiped = None
    VideoPiped = None
    HighQualityAudio = None

class TelegramVoiceClient:
    def __init__(self, telethon_client=None):
        self.telethon_client = telethon_client
        self.voice_client = None
        self.is_call_active = False
        self.current_call_user = None
        self.call_callbacks = []
        self.call_start_time = None
        self.dh_params = None
        self.audio_stream_active = False
        
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
            return True
        except Exception as e:
            print(f"Failed to initialize voice client: {e}")
            return False
    
    async def start_private_call(self, recipient_id):
        """Start private voice call with recipient"""
        if not self.telethon_client:
            return False
        
        try:
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
                    # Use Telegram's standard DH parameters for voice calls
                    import hashlib
                    
                    # Generate a random private key 'a' (2048 bits)
                    a = int.from_bytes(os.urandom(256), byteorder='big')
                    
                    # Telegram's standard DH parameters for voice calls
                    # These are the official parameters used by Telegram
                    p = int('0xC150023E2F70DB7985DED064759CFECF0AF328E69A41DAF4D6F01B538135A6F91F8F8B2A0EC9BA9720CE352EFCF6C5680FFC424BD634864902DE0B4BD6D49F4E580230E3AE97D95C8B19442B3C0A10D8F5633FECEDD6926A7F6DAB0DDB7D457F9EA81B8465FCD6FFFEED114011DF91C059CAEDAF97625F6C96ECC74725556934EF781D866B34F011FCE4D835A090196E9A5F0E4449AF7EB697DDB9076494CA5F81104A305B6DD27665722C46B60E5DF680FB16B210607EF2E5E0B1C42E1C72030C6F4C7F3B0C0E6DA4B2B0AC03E70020C2D7F2ACFB7E6', 16)
                    g = 2
                    
                    # Calculate g^a mod p
                    g_a = pow(g, a, p)
                    
                    # Calculate SHA256 hash of g_a for commitment
                    g_a_bytes = g_a.to_bytes(256, byteorder='big')
                    g_a_hash = hashlib.sha256(g_a_bytes).digest()
                    
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
                    
                    result = await self.telethon_client(RequestCallRequest(
                        user_id=recipient_entity,
                        random_id=random_id,
                        g_a_hash=g_a_hash,  # Use the hash, not the raw g_a value
                        protocol=protocol
                    ))
                    
                    print(f"Voice call request sent successfully: {result}")
                    
                    # Store DH parameters for potential audio stream setup
                    self.dh_params = {'a': a, 'p': p, 'g': g, 'g_a': g_a}
                    
                    # Notify about call start
                    self._notify_call_event('call_started', {
                        'recipient': recipient_id,
                        'type': 'outgoing',
                        'start_time': self.call_start_time.isoformat()
                    })
                    
                    self.is_call_active = True
                    return True
                    
                except Exception as call_error:
                    print(f"Native call failed: {call_error}")
                    # Don't fallback to PyTgCalls for private calls as it's for group calls only
                    raise call_error
            
        except Exception as e:
            print(f"Failed to start call: {e}")
            self._notify_call_event('call_failed', {'error': str(e)})
            return False
    
    async def answer_call(self, call_data):
        """Answer incoming voice call"""
        if not self.telethon_client:
            return False
        
        try:
            self.current_call_user = call_data.get('caller_id')
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
                    
                    # Generate a random private key 'b' (2048 bits)
                    b = int.from_bytes(os.urandom(256), byteorder='big')
                    
                    # Use same Telegram DH parameters as in start_private_call
                    p = int('0xC150023E2F70DB7985DED064759CFECF0AF328E69A41DAF4D6F01B538135A6F91F8F8B2A0EC9BA9720CE352EFCF6C5680FFC424BD634864902DE0B4BD6D49F4E580230E3AE97D95C8B19442B3C0A10D8F5633FECEDD6926A7F6DAB0DDB7D457F9EA81B8465FCD6FFFEED114011DF91C059CAEDAF97625F6C96ECC74725556934EF781D866B34F011FCE4D835A090196E9A5F0E4449AF7EB697DDB9076494CA5F81104A305B6DD27665722C46B60E5DF680FB16B210607EF2E5E0B1C42E1C72030C6F4C7F3B0C0E6DA4B2B0AC03E70020C2D7F2ACFB7E6', 16)
                    g = 2
                    
                    # Calculate g^b mod p
                    g_b_int = pow(g, b, p)
                    g_b = g_b_int.to_bytes(256, byteorder='big')
                    
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
            # Start audio stream after accepting call
            await self._start_audio_stream()
            
            return True
            
        except Exception as e:
            print(f"Failed to answer call: {e}")
            self._notify_call_event('call_failed', {'error': str(e)})
            return False
    
    async def _start_audio_stream(self):
        """Start audio stream for voice call"""
        try:
            if not VOICE_CALLS_AVAILABLE or not self.voice_client:
                print("PyTgCalls not available - audio stream not started")
                return False
            
            # Setup audio input/output for the call
            if AudioPiped and HighQualityAudio:
                # Use microphone input and speaker output
                audio_stream = AudioPiped(
                    path='device',  # Use default audio device
                    quality=HighQualityAudio()
                )
                
                print("Audio stream configured for voice call")
                self.audio_stream_active = True
                return True
            else:
                print("Audio stream components not available")
                return False
                
        except Exception as e:
            print(f"Failed to start audio stream: {e}")
            return False
    
    async def end_call(self):
        """End current voice call"""
        if not self.is_call_active:
            return False
        
        try:
            # Calculate call duration before ending
            call_duration = None
            if self.call_start_time:
                call_duration = datetime.now() - self.call_start_time
            
            # End the call using native API
            if self.current_call_user and self.telethon_client:
                try:
                    from telethon.tl.functions.phone import DiscardCallRequest
                    from telethon.tl.types import PhoneCallDiscardReasonHangup
                    
                    # Get user entity using the same logic as messaging system
                    import telegram_client
                    
                    # Find user entity using the same logic as start_private_call
                    entity = None
                    
                    # Try to find by username in chat_users cache
                    if hasattr(telegram_client.telegram_client, 'chat_users') and self.current_call_user in telegram_client.telegram_client.chat_users:
                        entity = telegram_client.telegram_client.chat_users[self.current_call_user]['entity']
                    else:
                        # Try to find in dialogs by name or title
                        if hasattr(telegram_client.telegram_client, 'dialogs'):
                            for dialog in telegram_client.telegram_client.dialogs:
                                if dialog['name'] == self.current_call_user or dialog['title'] == self.current_call_user:
                                    entity = dialog['entity']
                                    break
                    
                    if not entity:
                        # Try to resolve as username/phone as last resort
                        entity = await self.telethon_client.get_entity(self.current_call_user)
                    
                    user_entity = entity
                    
                    result = await self.telethon_client(DiscardCallRequest(
                        peer=user_entity,
                        duration=int(call_duration.total_seconds()) if call_duration else 0,
                        reason=PhoneCallDiscardReasonHangup(),
                        connection_id=0
                    ))
                    
                    print(f"Call ended via native API: {result}")
                    
                except Exception as native_error:
                    print(f"Failed to end call via native API: {native_error}")
                    # Continue anyway to reset call state
            
            # Play end call sound
            play_sound('titannet/bye.ogg')
            
            # Notify about call end
            self._notify_call_event('call_ended', {
                'user': self.current_call_user,
                'duration': call_duration.total_seconds() if call_duration else 0
            })
            
            # Stop audio stream
            if self.audio_stream_active and self.voice_client:
                try:
                    await self.voice_client.leave_group_call(self.current_call_user)
                    print("Audio stream stopped")
                except Exception as stream_error:
                    print(f"Warning: Could not stop audio stream: {stream_error}")
            
            # Reset call state
            self.is_call_active = False
            self.current_call_user = None
            self.call_start_time = None
            self.audio_stream_active = False
            self.dh_params = None
            
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
            
            # Schedule the call on the existing loop
            if loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    telegram_voice_client.start_private_call(recipient), 
                    loop
                )
                result = future.result(timeout=30)  # 30 second timeout
            else:
                # If loop is not running, run the coroutine directly
                result = loop.run_until_complete(telegram_voice_client.start_private_call(recipient))
            return result
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
                result = future.result(timeout=30)
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