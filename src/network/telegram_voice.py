# -*- coding: utf-8 -*-
"""
Telegram Voice Call System

Uses group voice chat (py-tgcalls) for reliable two-way audio.

Call flow (TCE-to-TCE):
1. Create temporary megagroup
2. Invite the other user
3. Start group voice call with microphone via py-tgcalls
4. Send a marker message so the other TCE client shows incoming call dialog
5. Recipient joins the same group voice chat
6. Two-way audio through group voice chat
7. On call end: leave voice chat, delete temporary group

For incoming native Telegram calls:
- Accept signaling via Telethon (AcceptCallRequest)
- Audio limited (no Python WebRTC audio transport)
"""

import asyncio
import threading
import time
import tempfile
import wave
import os
import secrets
import hashlib
from datetime import datetime

import wx

from src.titan_core.sound import play_sound
from src.titan_core.translation import set_language
from src.settings.settings import get_setting

_ = set_language(get_setting('language', 'pl'))

# Voice call message markers for TCE-to-TCE signaling
CALL_REQUEST_PREFIX = "[TCE:CALL:"
CALL_END_PREFIX = "[TCE:CALLEND:"
CALL_MARKER_SUFFIX = "]"

# py-tgcalls availability
try:
    from pytgcalls import PyTgCalls
    from pytgcalls.types import MediaStream

    # Try multiple import paths for MediaDevices
    MediaDevices = None
    try:
        from pytgcalls import MediaDevices as _MD
        MediaDevices = _MD
    except ImportError:
        pass
    if not MediaDevices:
        try:
            from pytgcalls.media_devices import MediaDevices as _MD2
            MediaDevices = _MD2
        except ImportError:
            pass

    PYTGCALLS_AVAILABLE = True
    print("py-tgcalls loaded for voice calls")

except ImportError as e:
    PYTGCALLS_AVAILABLE = False
    PyTgCalls = None
    MediaStream = None
    MediaDevices = None
    print(f"py-tgcalls not available: {e}")

# DH parameters (Telegram official, for native call signaling)
TELEGRAM_DH_PRIME = int(
    '0xC150023E2F70DB7985DED064759CFECF0AF328E69A41DAF4D6F01B538135A6F91F8F8B2A0EC9BA9720CE352EFCF6C5680FFC'
    '424BD634864902DE0B4BD6D49F4E580230E3AE97D95C8B19442B3C0A10D8F5633FECEDD6926A7F6DAB0DDB7D457F9EA81B8465FCD6'
    'FFFEED114011DF91C059CAEDAF97625F6C96ECC74725556934EF781D866B34F011FCE4D835A090196E9A5F0E4449AF7EB697DDB9076'
    '494CA5F81104A305B6DD27665722C46B60E5DF680FB16B210607EF2E5E0B1C42E1C72030C6F4C7F3B0C0E6DA4B2B0AC03E70020C2D'
    '7F2ACFB7E6', 16
)
TELEGRAM_DH_GENERATOR = 2


class TelegramVoiceClient:
    """Voice call client using group voice chat for two-way audio."""

    # Call states
    IDLE = 'idle'
    SETTING_UP = 'setting_up'
    CONNECTING = 'connecting'
    CONNECTED = 'connected'
    ENDING = 'ending'

    def __init__(self, telethon_client):
        self.telethon_client = telethon_client
        self.state = self.IDLE

        # PyTgCalls
        self.pytgcalls = None
        self._pytgcalls_started = False

        # Call state
        self.current_peer = None
        self.current_peer_name = None
        self.current_group_id = None
        self.current_group_entity = None
        self.call_start_time = None
        self.is_muted = False

        # Native call state (incoming calls)
        self.current_call_object = None
        self.dh_params = None

        # Callbacks
        self.callbacks = []

        # Initialize PyTgCalls
        if PYTGCALLS_AVAILABLE and telethon_client and PyTgCalls:
            try:
                self.pytgcalls = PyTgCalls(telethon_client)
                print("PyTgCalls initialized")
            except Exception as e:
                print(f"PyTgCalls init failed: {e}")

    # === CALLBACK MANAGEMENT ===

    def add_callback(self, callback):
        """Add callback for call events."""
        self.callbacks.append(callback)

    def _notify(self, event_type, data=None):
        """Notify all callbacks."""
        for cb in self.callbacks:
            try:
                wx.CallAfter(cb, event_type, data or {})
            except Exception:
                pass

    def _set_state(self, new_state, data=None):
        """Update state and notify."""
        old = self.state
        self.state = new_state
        self._notify('state_changed', {
            'old_state': old,
            'new_state': new_state,
            **(data or {})
        })

    # === HELPERS ===

    def _get_event_loop(self):
        """Get the Telegram client's event loop."""
        try:
            from src.network import telegram_client as tc_mod
            if hasattr(tc_mod.telegram_client, 'event_loop') and tc_mod.telegram_client.event_loop:
                return tc_mod.telegram_client.event_loop
        except Exception:
            pass

        if self.telethon_client and hasattr(self.telethon_client, '_loop'):
            return self.telethon_client._loop
        return None

    async def _resolve_entity(self, recipient_id):
        """Resolve username/name to Telethon entity."""
        try:
            from src.network import telegram_client as tc_mod

            # Check cached users
            if hasattr(tc_mod.telegram_client, 'chat_users') and recipient_id in tc_mod.telegram_client.chat_users:
                return tc_mod.telegram_client.chat_users[recipient_id]['entity']

            # Check dialogs
            if hasattr(tc_mod.telegram_client, 'dialogs'):
                for dialog in tc_mod.telegram_client.dialogs:
                    if dialog['name'] == recipient_id or dialog.get('title') == recipient_id:
                        return dialog['entity']

            # Last resort: direct resolve
            return await self.telethon_client.get_entity(recipient_id)
        except Exception as e:
            print(f"Could not resolve '{recipient_id}': {e}")
            return None

    async def _ensure_pytgcalls_started(self):
        """Start PyTgCalls client if not already running."""
        if not self.pytgcalls:
            return False

        if self._pytgcalls_started:
            return True

        try:
            await self.pytgcalls.start()
            self._pytgcalls_started = True
            print("PyTgCalls client started")
            return True
        except Exception as e:
            if "already" in str(e).lower():
                self._pytgcalls_started = True
                return True
            print(f"PyTgCalls start failed: {e}")
            return False

    # === OUTGOING CALL ===

    async def start_call(self, recipient_id):
        """Start voice call with recipient using group voice chat."""
        if self.state != self.IDLE:
            self._notify('call_failed', {'error': _('Call already in progress')})
            return False

        if not PYTGCALLS_AVAILABLE or not self.pytgcalls:
            self._notify('call_failed', {
                'error': _('Voice calls require py-tgcalls. Install with: pip install py-tgcalls')
            })
            return False

        self.current_peer = recipient_id
        self.current_peer_name = recipient_id
        self._set_state(self.SETTING_UP, {'recipient': recipient_id})
        play_sound('titannet/ring_out.ogg')

        try:
            # Step 1: Start PyTgCalls
            if not await self._ensure_pytgcalls_started():
                raise Exception(_("Could not start voice system"))

            # Step 2: Create temporary group
            group_id = await self._create_voice_group(recipient_id)
            if not group_id:
                raise Exception(_("Could not create voice chat group"))

            # Step 3: Start voice chat with microphone
            self._set_state(self.CONNECTING, {'recipient': recipient_id})
            voice_ok = await self._start_voice_in_group(group_id)

            if not voice_ok:
                raise Exception(_("Could not start voice chat"))

            # Step 4: Send call notification to recipient
            await self._send_call_notification(recipient_id, group_id)

            # Connected!
            self.call_start_time = datetime.now()
            self._set_state(self.CONNECTED, {'recipient': recipient_id})
            play_sound('titannet/callsuccess.ogg')
            self._notify('call_started', {
                'recipient': recipient_id,
                'type': 'outgoing',
                'group_id': group_id
            })
            return True

        except Exception as e:
            print(f"Start call failed: {e}")
            import traceback
            traceback.print_exc()
            await self._safe_cleanup()
            self._set_state(self.IDLE)
            self._notify('call_failed', {'error': str(e)})
            return False

    async def _create_voice_group(self, recipient_id):
        """Create temporary megagroup for voice call."""
        try:
            from telethon.tl.functions.channels import CreateChannelRequest, InviteToChannelRequest

            group_title = f"Voice Call {datetime.now().strftime('%H:%M:%S')}"

            result = await self.telethon_client(CreateChannelRequest(
                title=group_title,
                about="Temporary voice call - auto-deleted after call",
                megagroup=True
            ))

            if not result or not result.chats:
                return None

            group = result.chats[0]
            self.current_group_id = group.id
            self.current_group_entity = group
            print(f"Voice group created: {group.id} ({group_title})")

            # Try to invite recipient
            try:
                entity = await self._resolve_entity(recipient_id)
                if entity:
                    input_user = await self.telethon_client.get_input_entity(entity)
                    await self.telethon_client(InviteToChannelRequest(
                        channel=group,
                        users=[input_user]
                    ))
                    print(f"Invited {recipient_id} to voice group")

                    # Get display name
                    if hasattr(entity, 'first_name'):
                        self.current_peer_name = entity.first_name
                    elif hasattr(entity, 'username') and entity.username:
                        self.current_peer_name = entity.username
                else:
                    print(f"Could not find user: {recipient_id}")
            except Exception as invite_err:
                print(f"Could not invite {recipient_id}: {invite_err}")
                # Group still created, can proceed

            return group.id

        except Exception as e:
            print(f"Group creation failed: {e}")
            return None

    async def _start_voice_in_group(self, group_id):
        """Start voice chat in group with microphone capture."""
        if not self.pytgcalls:
            return False

        # Method 1: Microphone device
        if MediaDevices:
            try:
                mic = None
                if hasattr(MediaDevices, 'microphone_devices'):
                    mics = MediaDevices.microphone_devices()
                    if mics:
                        mic = mics[0]
                elif hasattr(MediaDevices, 'get_audio_device'):
                    mic = MediaDevices.get_audio_device()

                if mic:
                    stream = MediaStream(audio_path=mic)
                    await self.pytgcalls.play(group_id, stream)
                    print(f"Voice started with microphone: {mic}")
                    return True
            except Exception as mic_err:
                print(f"Microphone method failed: {mic_err}")

        # Method 2: Try default audio (some versions auto-detect mic)
        try:
            stream = MediaStream(audio_path="default")
            await self.pytgcalls.play(group_id, stream)
            print("Voice started with default audio")
            return True
        except Exception:
            pass

        # Method 3: Silent audio fallback (voice chat active but no mic)
        try:
            temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            temp_path = temp_file.name
            temp_file.close()

            with wave.open(temp_path, 'wb') as wav:
                wav.setnchannels(2)
                wav.setsampwidth(2)
                wav.setframerate(48000)
                # 30 seconds of silence (will loop or end)
                wav.writeframes(b'\x00' * (48000 * 2 * 2 * 30))

            stream = MediaStream(media_path=temp_path)
            await self.pytgcalls.play(group_id, stream)
            print("Voice started with silent audio (microphone not available)")

            # Clean up temp file after delay
            def cleanup_temp():
                time.sleep(5)
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
            threading.Thread(target=cleanup_temp, daemon=True).start()

            return True

        except Exception as silent_err:
            print(f"Silent audio fallback failed: {silent_err}")

        return False

    async def _send_call_notification(self, recipient_id, group_id):
        """Send a marker message so the recipient's TCE client shows incoming call dialog."""
        try:
            entity = await self._resolve_entity(recipient_id)
            if entity:
                # Get our display name
                me = await self.telethon_client.get_me()
                my_name = me.first_name or me.username or "User"

                # Send marker message
                marker = f"{CALL_REQUEST_PREFIX}{group_id}:{my_name}{CALL_MARKER_SUFFIX}"
                await self.telethon_client.send_message(entity, marker)
                print(f"Call notification sent to {recipient_id}")
        except Exception as e:
            print(f"Could not send call notification: {e}")
            # Not critical - call still works, recipient just won't get auto-dialog

    # === JOIN CALL (for receiving side) ===

    async def join_call(self, group_id):
        """Join an existing group voice chat (called by recipient)."""
        if self.state != self.IDLE:
            self._notify('call_failed', {'error': _('Call already in progress')})
            return False

        if not PYTGCALLS_AVAILABLE or not self.pytgcalls:
            self._notify('call_failed', {
                'error': _('Voice calls require py-tgcalls. Install with: pip install py-tgcalls')
            })
            return False

        self.current_group_id = group_id
        self._set_state(self.CONNECTING, {'group_id': group_id})

        try:
            # Start PyTgCalls
            if not await self._ensure_pytgcalls_started():
                raise Exception(_("Could not start voice system"))

            # Join voice chat with microphone
            voice_ok = await self._start_voice_in_group(group_id)

            if not voice_ok:
                raise Exception(_("Could not join voice chat"))

            self.call_start_time = datetime.now()
            self._set_state(self.CONNECTED, {'group_id': group_id})
            play_sound('titannet/callsuccess.ogg')
            self._notify('call_started', {
                'type': 'incoming_accepted',
                'group_id': group_id
            })
            return True

        except Exception as e:
            print(f"Join call failed: {e}")
            self._set_state(self.IDLE)
            self._notify('call_failed', {'error': str(e)})
            return False

    # === INCOMING NATIVE CALL (signaling only) ===

    async def answer_native_call(self, call_data):
        """Answer incoming native Telegram call via signaling.

        Note: Audio does NOT work through native calls in Python.
        This only accepts the signaling so the caller sees 'connected'.
        """
        if not self.telethon_client:
            return False

        try:
            call_obj = call_data.get('call_object')
            if not call_obj:
                return False

            self.current_peer = call_data.get('caller_id')
            self.current_call_object = call_obj
            self.call_start_time = datetime.now()

            from telethon.tl.functions.phone import AcceptCallRequest
            from telethon.tl.types import PhoneCallProtocol

            p = TELEGRAM_DH_PRIME
            b = secrets.randbelow(p - 3) + 2
            g_b = pow(TELEGRAM_DH_GENERATOR, b, p).to_bytes(256, byteorder='big')

            protocol = PhoneCallProtocol(
                min_layer=65, max_layer=92,
                udp_p2p=True, udp_reflector=True,
                library_versions=['2.4.4']
            )

            await self.telethon_client(AcceptCallRequest(
                peer=call_obj, g_b=g_b, protocol=protocol
            ))

            self.dh_params = {'b': b, 'p': p, 'protocol': protocol}
            self._set_state(self.CONNECTED)
            play_sound('titannet/callsuccess.ogg')
            self._notify('call_answered', {'caller': self.current_peer})
            return True

        except Exception as e:
            print(f"Answer native call failed: {e}")
            self._notify('call_failed', {'error': str(e)})
            return False

    # === END CALL ===

    async def end_call(self):
        """End current voice call."""
        if self.state == self.IDLE:
            return False

        self._set_state(self.ENDING)

        try:
            # Send end marker to peer
            if self.current_peer and self.current_group_id:
                try:
                    entity = await self._resolve_entity(self.current_peer)
                    if entity:
                        marker = f"{CALL_END_PREFIX}{self.current_group_id}{CALL_MARKER_SUFFIX}"
                        await self.telethon_client.send_message(entity, marker)
                except Exception:
                    pass

            # End native call signaling
            if self.current_call_object and self.telethon_client:
                try:
                    from telethon.tl.functions.phone import DiscardCallRequest
                    from telethon.tl.types import PhoneCallDiscardReasonHangup

                    duration = 0
                    if self.call_start_time:
                        duration = int((datetime.now() - self.call_start_time).total_seconds())

                    await self.telethon_client(DiscardCallRequest(
                        peer=self.current_call_object,
                        duration=duration,
                        reason=PhoneCallDiscardReasonHangup(),
                        connection_id=0
                    ))
                except Exception as e:
                    print(f"Native call discard: {e}")

            # Leave group voice chat
            if self.pytgcalls and self.current_group_id:
                try:
                    if hasattr(self.pytgcalls, 'leave_call'):
                        await self.pytgcalls.leave_call(self.current_group_id)
                    elif hasattr(self.pytgcalls, 'leave_group_call'):
                        await self.pytgcalls.leave_group_call(self.current_group_id)
                    print("Left group voice chat")
                except Exception as e:
                    print(f"Leave voice chat: {e}")

            # Delete temporary group
            await self._safe_cleanup()

        finally:
            # Reset state
            self.state = self.IDLE
            self.current_peer = None
            self.current_peer_name = None
            self.current_group_id = None
            self.current_group_entity = None
            self.current_call_object = None
            self.call_start_time = None
            self.is_muted = False
            self.dh_params = None

            play_sound('titannet/bye.ogg')
            self._notify('call_ended', {})

        return True

    async def _safe_cleanup(self):
        """Delete temporary voice group."""
        if not self.current_group_id or not self.telethon_client:
            return

        try:
            from telethon.tl.functions.channels import DeleteChannelRequest

            if self.current_group_entity:
                await self.telethon_client(DeleteChannelRequest(channel=self.current_group_entity))
            else:
                entity = await self.telethon_client.get_entity(self.current_group_id)
                await self.telethon_client(DeleteChannelRequest(channel=entity))
            print("Voice group deleted")
        except Exception as e:
            print(f"Group cleanup failed: {e}")

    # === MUTE ===

    async def toggle_mute(self):
        """Toggle microphone mute."""
        if self.state != self.CONNECTED or not self.pytgcalls or not self.current_group_id:
            return False

        try:
            if self.is_muted:
                # Unmute
                if hasattr(self.pytgcalls, 'resume'):
                    await self.pytgcalls.resume(self.current_group_id)
                elif hasattr(self.pytgcalls, 'unmute_stream'):
                    await self.pytgcalls.unmute_stream(self.current_group_id)
            else:
                # Mute
                if hasattr(self.pytgcalls, 'pause'):
                    await self.pytgcalls.pause(self.current_group_id)
                elif hasattr(self.pytgcalls, 'mute_stream'):
                    await self.pytgcalls.mute_stream(self.current_group_id)

            self.is_muted = not self.is_muted
            self._notify('mute_changed', {'muted': self.is_muted})
            return True

        except Exception as e:
            print(f"Mute toggle failed: {e}")
            return False

    # === STATUS ===

    def get_status(self):
        """Get current call status."""
        duration = 0
        if self.call_start_time:
            duration = (datetime.now() - self.call_start_time).total_seconds()

        return {
            'active': self.state in (self.CONNECTING, self.CONNECTED),
            'state': self.state,
            'peer': self.current_peer,
            'peer_name': self.current_peer_name,
            'duration': duration,
            'muted': self.is_muted,
            'has_audio': PYTGCALLS_AVAILABLE and self.pytgcalls is not None,
            'group_id': self.current_group_id
        }


# ============================================================
# MODULE-LEVEL API (backward compatible)
# ============================================================

_voice_client = None
# Keep old name for backward compatibility
telegram_voice_client = None


def initialize_voice_client(telethon_client):
    """Initialize the global voice client."""
    global _voice_client, telegram_voice_client
    _voice_client = TelegramVoiceClient(telethon_client)
    telegram_voice_client = _voice_client
    print(f"Voice client initialized (py-tgcalls: {'available' if PYTGCALLS_AVAILABLE else 'not available'})")


def _run_on_loop(coro, timeout=120):
    """Run async coroutine on the Telegram event loop."""
    if not _voice_client:
        raise RuntimeError("Voice client not initialized")

    loop = _voice_client._get_event_loop()
    if not loop:
        raise RuntimeError("No event loop available")

    if loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)
    else:
        return loop.run_until_complete(coro)


def start_voice_call(recipient):
    """Start voice call with recipient."""
    if not _voice_client:
        print("Voice client not initialized")
        return False

    if not _voice_client.telethon_client:
        print("Telegram client not connected")
        return False

    def call_async():
        try:
            result = _run_on_loop(_voice_client.start_call(recipient))
            if not result:
                print(f"Call to {recipient} failed")
        except Exception as e:
            print(f"Voice call error: {e}")
            import traceback
            traceback.print_exc()

    threading.Thread(target=call_async, daemon=True).start()
    return True


def join_voice_call(group_id):
    """Join an existing group voice chat (for receiving calls)."""
    if not _voice_client:
        print("Voice client not initialized")
        return False

    def join_async():
        try:
            result = _run_on_loop(_voice_client.join_call(group_id))
            if not result:
                print(f"Failed to join call in group {group_id}")
        except Exception as e:
            print(f"Join call error: {e}")
            import traceback
            traceback.print_exc()

    threading.Thread(target=join_async, daemon=True).start()
    return True


def answer_voice_call(call_data=None):
    """Answer incoming voice call."""
    if not _voice_client:
        print("Voice client not initialized")
        return False

    if not call_data:
        call_data = {}

    def answer_async():
        try:
            _run_on_loop(_voice_client.answer_native_call(call_data))
        except Exception as e:
            print(f"Answer call error: {e}")

    threading.Thread(target=answer_async, daemon=True).start()
    return True


def end_voice_call():
    """End current voice call."""
    if not _voice_client:
        return False

    def end_async():
        try:
            _run_on_loop(_voice_client.end_call(), timeout=15)
        except Exception as e:
            print(f"End call error: {e}")

    threading.Thread(target=end_async, daemon=True).start()
    return True


def toggle_mute():
    """Toggle microphone mute."""
    if not _voice_client:
        return False

    def mute_async():
        try:
            _run_on_loop(_voice_client.toggle_mute(), timeout=5)
        except Exception as e:
            print(f"Mute error: {e}")

    threading.Thread(target=mute_async, daemon=True).start()
    return True


def is_call_active():
    """Check if voice call is active."""
    if not _voice_client:
        return False
    return _voice_client.state in (TelegramVoiceClient.CONNECTING, TelegramVoiceClient.CONNECTED)


def get_call_status():
    """Get current call status."""
    if not _voice_client:
        return {'active': False, 'state': 'idle'}
    return _voice_client.get_status()


def add_call_callback(callback):
    """Add callback for call events."""
    if _voice_client:
        _voice_client.add_callback(callback)


def is_voice_calls_available():
    """Check if voice calls are available."""
    return PYTGCALLS_AVAILABLE


def get_voice_call_status():
    """Get detailed voice call status."""
    status = get_call_status()
    status['py_tgcalls_available'] = PYTGCALLS_AVAILABLE
    return status


# === TCE CALL MESSAGE DETECTION ===

def parse_call_message(message_text):
    """Parse a TCE voice call marker message.

    Returns:
        dict with 'type' ('call_request' or 'call_end'), 'group_id', and optionally 'caller_name'
        or None if not a call message.
    """
    if not message_text:
        return None

    text = message_text.strip()

    # Check for call request: [TCE:CALL:group_id:caller_name]
    if text.startswith(CALL_REQUEST_PREFIX) and text.endswith(CALL_MARKER_SUFFIX):
        content = text[len(CALL_REQUEST_PREFIX):-len(CALL_MARKER_SUFFIX)]
        parts = content.split(':', 1)
        if len(parts) >= 1:
            try:
                group_id = int(parts[0])
                caller_name = parts[1] if len(parts) > 1 else "Unknown"
                return {
                    'type': 'call_request',
                    'group_id': group_id,
                    'caller_name': caller_name
                }
            except ValueError:
                pass

    # Check for call end: [TCE:CALLEND:group_id]
    if text.startswith(CALL_END_PREFIX) and text.endswith(CALL_MARKER_SUFFIX):
        content = text[len(CALL_END_PREFIX):-len(CALL_MARKER_SUFFIX)]
        try:
            group_id = int(content)
            return {
                'type': 'call_end',
                'group_id': group_id
            }
        except ValueError:
            pass

    return None


def is_call_message(message_text):
    """Check if a message is a TCE voice call marker."""
    return parse_call_message(message_text) is not None
