# -*- coding: utf-8 -*-
"""
Telegram voice calls
====================

A call to a person is a **real Telegram call** (``phone.RequestCall`` and the
Diffie-Hellman exchange behind it), placed by py-tgcalls: ``play(user_id, ...)``
with a positive id is a peer-to-peer call, exactly what the phone app makes.
The peer's Telegram rings, wherever they are and whatever client they use.

Why this replaced the previous approach
---------------------------------------
Calling someone used to mean: create a throwaway megagroup, invite them to it,
start a group voice chat inside it, poll the participant count until somebody
else appeared, and delete the group afterwards. Every part of that was a way to
fail. The peer got "X added you to a group", not a ringing call; anyone not
using Titan had no reason to join; Telegram rate-limits channel creation, so a
few calls in a row ended in "Could not create voice chat group"; and the group
survived any crash between creation and deletion. py-tgcalls has supported
native peer-to-peer calls for a long time, so none of it was necessary.

Group voice chats are still supported - joining one is what ``join_call`` is
for - but they are now only used when the target really is a group.

Microphone
----------
A call the other side cannot hear is worse than a call that fails. The stream is
built with ``Flags.REQUIRED``, so a microphone that cannot be opened raises here
instead of quietly becoming a connected, silent call. The two old fallbacks
(``media_path="default"``, then a generated silent WAV) did exactly that, and
the WAV was deleted five seconds into the call it was feeding.

Signalling
----------
py-tgcalls owns the whole protocol: it requests, accepts, confirms and discards
calls and relays the signalling data. Nothing here (and nothing in
``telegram_client``) may answer ``UpdatePhoneCall`` itself - two clients
completing the same key exchange is a call that never connects.
"""

import asyncio
import threading
from datetime import datetime

import wx

from src.titan_core.sound import play_sound
from src.titan_core.translation import set_language
from src.settings.settings import get_setting

_ = set_language(get_setting('language', 'pl'))

# Voice call message markers, kept only so old marker messages sent by a
# previous version are still recognised and not shown as junk text.
CALL_REQUEST_PREFIX = "[TCE:CALL:"
CALL_END_PREFIX = "[TCE:CALLEND:"
CALL_MARKER_SUFFIX = "]"

# py-tgcalls availability
try:
    from pytgcalls import PyTgCalls
    from pytgcalls.types import CallConfig, GroupCallConfig, MediaStream

    try:
        from pytgcalls import MediaDevices
    except ImportError:                                  # older layouts
        from pytgcalls.media_devices import MediaDevices

    from pytgcalls.exceptions import (
        CallBusy, CallDeclined, CallDiscarded, NoActiveGroupCall,
        NotInCallError, TimedOutAnswer,
    )

    PYTGCALLS_AVAILABLE = True
    print("py-tgcalls loaded for voice calls")

except ImportError as e:
    PYTGCALLS_AVAILABLE = False
    PyTgCalls = None
    CallConfig = GroupCallConfig = MediaStream = MediaDevices = None

    class _Missing(Exception):
        pass

    CallBusy = CallDeclined = CallDiscarded = _Missing
    NoActiveGroupCall = NotInCallError = TimedOutAnswer = _Missing
    print(f"py-tgcalls not available: {e}")


class VoiceCallError(Exception):
    """Something the user needs to be told, already phrased for them."""


class TelegramVoiceClient:
    """Native Telegram calls, plus joining a group voice chat."""

    # Call states
    IDLE = 'idle'
    SETTING_UP = 'setting_up'
    CONNECTING = 'connecting'
    RINGING = 'ringing'      # the peer's Telegram is ringing
    CONNECTED = 'connected'
    ENDING = 'ending'

    # How long Telegram waits for the peer to pick up.
    ANSWER_TIMEOUT_SECONDS = 60

    def __init__(self, telethon_client):
        self.telethon_client = telethon_client
        self.state = self.IDLE

        # PyTgCalls
        self.pytgcalls = None
        self._pytgcalls_started = False
        self._handlers_bound = False

        # Call state. ``current_chat_id`` is what py-tgcalls is keyed on: a
        # positive user id for a call, a negative chat id for a voice chat.
        self.current_peer = None
        self.current_peer_name = None
        self.current_chat_id = None
        self.call_transport = None          # 'private' | 'group'
        self.call_start_time = None
        self.is_muted = False
        self.mic_active = False

        # The call that is ringing at us right now, as py-tgcalls sees it.
        self.incoming_call = None

        # Callbacks
        self.callbacks = []

        if PYTGCALLS_AVAILABLE and telethon_client and PyTgCalls:
            try:
                # Must be constructed where the Telethon loop is running: the
                # binding captures that loop and delivers every callback on it.
                self.pytgcalls = PyTgCalls(telethon_client)
                print("PyTgCalls initialized")
            except Exception as e:
                print(f"PyTgCalls init failed: {e}")

    # === BACKWARDS COMPATIBILITY ===============================================
    # The group id of a call used to be public state; keep the name readable for
    # anything still looking at it.
    @property
    def current_group_id(self):
        if self.call_transport == 'group':
            return self.current_chat_id
        return None

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
        """The Telegram client's event loop, only while it is actually running.

        Handing back a loop that is not running invites
        ``run_until_complete`` from a worker thread on a loop another thread
        owns, which either deadlocks or corrupts the client's state.
        """
        loop = None
        try:
            from src.network import telegram_client as tc_mod
            loop = getattr(tc_mod.telegram_client, 'event_loop', None)
        except Exception:
            loop = None

        if loop is None and self.telethon_client is not None:
            loop = getattr(self.telethon_client, '_loop', None)

        if loop is not None and loop.is_running():
            return loop
        return None

    async def _resolve_entity(self, recipient_id):
        """Resolve username/name to a Telethon entity."""
        try:
            from src.network import telegram_client as tc_mod

            cached = getattr(tc_mod.telegram_client, 'chat_users', None)
            if cached and recipient_id in cached:
                return cached[recipient_id]['entity']

            for dialog in getattr(tc_mod.telegram_client, 'dialogs', None) or []:
                if dialog.get('name') == recipient_id or \
                        dialog.get('title') == recipient_id:
                    return dialog['entity']
        except Exception:
            pass

        try:
            return await self.telethon_client.get_entity(recipient_id)
        except Exception as e:
            print(f"Could not resolve '{recipient_id}': {e}")
            return None

    async def _ensure_pytgcalls_started(self):
        """Start the PyTgCalls client (and bind its handlers) once."""
        if not self.pytgcalls:
            return False

        if not self._pytgcalls_started:
            try:
                await self.pytgcalls.start()
                self._pytgcalls_started = True
                print("PyTgCalls client started")
            except Exception as e:
                if "already" in str(e).lower():
                    self._pytgcalls_started = True
                else:
                    print(f"PyTgCalls start failed: {e}")
                    return False

        self._bind_handlers()
        return True

    def _bind_handlers(self):
        """Listen for what the call itself does.

        The previous version had to poll Telegram for the participant count to
        notice an answer, and had no way at all to notice the other side hanging
        up on a native call. py-tgcalls reports both.
        """
        if self._handlers_bound or not self.pytgcalls:
            return
        try:
            self.pytgcalls.add_handler(self._on_call_update)
            self._handlers_bound = True
        except Exception as e:
            print(f"[Telegram voice] could not bind call handlers: {e}")

    async def _on_call_update(self, _client, update):
        try:
            from pytgcalls.types import ChatUpdate
        except Exception:
            return

        if not isinstance(update, ChatUpdate):
            return

        status = update.status

        if status & ChatUpdate.Status.INCOMING_CALL:
            await self._handle_incoming(update.chat_id)
            return

        if status & ChatUpdate.Status.LEFT_CALL:
            # Covers the peer hanging up, declining, being busy, and the voice
            # chat being closed under us.
            if update.chat_id == self.current_chat_id and self.state != self.IDLE:
                busy = bool(status & ChatUpdate.Status.BUSY_CALL)
                await self._finish_call(
                    _("The other person is busy") if busy else None)
            elif self.incoming_call and \
                    self.incoming_call.get('user_id') == update.chat_id:
                self.incoming_call = None
                self._notify('incoming_call_cancelled', {})

    async def _handle_incoming(self, user_id):
        """Somebody is calling us."""
        name = str(user_id)
        try:
            entity = await self.telethon_client.get_entity(user_id)
            name = (getattr(entity, 'first_name', None) or
                    getattr(entity, 'username', None) or name)
        except Exception:
            pass

        self.incoming_call = {'user_id': user_id, 'name': name}
        self._notify('incoming_call', {'caller_id': user_id, 'caller_name': name})

    # === MICROPHONE ===

    def _check_microphone(self):
        """Return ``(ok, reason)`` from the shared Windows microphone check."""
        try:
            from src.system.mic_permission import check_microphone
            return check_microphone()
        except Exception as e:
            # Never block a call because the checker itself failed.
            print(f"[Telegram voice] microphone check unavailable: {e}")
            return True, 'unknown'

    def _microphone_error(self, reason):
        try:
            from src.system.mic_permission import explain
            return explain(reason)
        except Exception:
            return _("The microphone is not available.")

    def _microphone_stream(self):
        """The live microphone as a py-tgcalls stream.

        ``Flags.REQUIRED`` is the whole point: without it a microphone that
        cannot be opened is dropped from the stream and the call connects with
        nothing on it, which is how a call used to look perfectly normal while
        the other side heard silence.
        """
        if not MediaDevices or not MediaStream:
            raise VoiceCallError(
                _("Voice calls require py-tgcalls. Install it with: "
                  "pip install py-tgcalls"))

        try:
            microphones = list(MediaDevices.microphone_devices())
        except Exception as e:
            raise VoiceCallError(
                _("The microphone list could not be read: {error}").format(error=e))

        if not microphones:
            raise VoiceCallError(_("No microphone was found."))

        device = self._preferred_microphone(microphones)
        try:
            stream = MediaStream(
                device,
                audio_flags=MediaStream.Flags.REQUIRED,
                video_flags=MediaStream.Flags.IGNORE,
            )
        except Exception as e:
            raise VoiceCallError(
                _("The microphone could not be opened: {error}").format(error=e))

        self.mic_active = True
        print(f"[Telegram voice] microphone: {device}")
        return stream

    @staticmethod
    def _preferred_microphone(microphones):
        """Windows' own default device, when it names one."""
        for device in microphones:
            if str(getattr(device, 'title', '')).lower().startswith('default'):
                return device
        return microphones[0]

    # === OUTGOING CALL ===

    async def start_call(self, recipient_id):
        """Place a call. A person gets a real Telegram call; a group is joined."""
        if self.state != self.IDLE:
            self._notify('call_failed', {'error': _('Call already in progress')})
            return False

        if not PYTGCALLS_AVAILABLE or not self.pytgcalls:
            self._notify('call_failed', {
                'error': _('Voice calls require py-tgcalls. Install it with: '
                           'pip install py-tgcalls')
            })
            return False

        # A call nobody can be heard on is worse than a refused call: check the
        # Windows microphone Privacy switches first and say exactly what to fix.
        mic_ok, mic_reason = self._check_microphone()
        if not mic_ok:
            self._notify('call_failed', {'error': self._microphone_error(mic_reason)})
            return False

        self.current_peer = recipient_id
        self.current_peer_name = recipient_id
        self.mic_active = False
        self._set_state(self.SETTING_UP, {'recipient': recipient_id})

        try:
            if not await self._ensure_pytgcalls_started():
                raise VoiceCallError(_("Could not start voice system"))

            chat_id, display_name, is_private = await self._resolve_target(recipient_id)
            self.current_peer_name = display_name
            self.current_chat_id = chat_id
            self.call_transport = 'private' if is_private else 'group'

            stream = self._microphone_stream()

            self._set_state(self.CONNECTING, {'recipient': display_name})
            play_sound('titannet/ring_out.ogg')

            if is_private:
                # ``play`` returns once the call is really connected, and raises
                # for every way it can fail to be. Run it alongside the UI so the
                # call window can appear while the peer's phone is ringing.
                self._set_state(self.RINGING, {'recipient': display_name})
                self._notify('call_ringing', {
                    'recipient': display_name,
                    'type': 'outgoing',
                })
                asyncio.ensure_future(self._run_private_call(chat_id, stream))
                return True

            await self.pytgcalls.play(chat_id, stream,
                                      GroupCallConfig(auto_start=True))
            self._mark_connected(display_name)
            return True

        except VoiceCallError as e:
            await self._reset(str(e))
            return False
        except Exception as e:
            print(f"Start call failed: {e}")
            import traceback
            traceback.print_exc()
            await self._reset(self._explain(e))
            return False

    async def _resolve_target(self, recipient_id):
        """``(chat_id, display_name, is_private)`` for whoever is being called.

        py-tgcalls reads the sign of the id: positive is a person and means a
        real call, negative is a chat and means its voice chat.
        """
        if isinstance(recipient_id, int):
            return recipient_id, str(recipient_id), recipient_id > 0

        entity = await self._resolve_entity(recipient_id)
        if entity is None:
            raise VoiceCallError(
                _("{name} could not be found on Telegram").format(name=recipient_id))

        name = (getattr(entity, 'first_name', None) or
                getattr(entity, 'username', None) or
                getattr(entity, 'title', None) or str(recipient_id))

        from telethon.tl.types import User
        if isinstance(entity, User):
            return entity.id, name, True

        from telethon import utils as tg_utils
        return tg_utils.get_peer_id(entity), name, False

    async def _run_private_call(self, user_id, stream):
        """Await the outgoing call, and report what actually happened to it."""
        try:
            await self.pytgcalls.play(
                user_id, stream,
                CallConfig(timeout=self.ANSWER_TIMEOUT_SECONDS))
        except TimedOutAnswer:
            self._notify('call_unanswered', {'recipient': self.current_peer_name})
            await self._reset(_("{name} did not answer").format(
                name=self.current_peer_name))
            return
        except CallDeclined:
            await self._reset(_("{name} declined the call").format(
                name=self.current_peer_name))
            return
        except CallBusy:
            await self._reset(_("{name} is busy").format(
                name=self.current_peer_name))
            return
        except CallDiscarded:
            await self._finish_call(None)
            return
        except Exception as e:
            print(f"[Telegram voice] outgoing call failed: {e}")
            import traceback
            traceback.print_exc()
            await self._reset(self._explain(e))
            return

        self._mark_connected(self.current_peer_name)

    def _mark_connected(self, peer_name):
        """RINGING/CONNECTING -> CONNECTED, exactly once."""
        if self.state in (self.CONNECTED, self.IDLE, self.ENDING):
            return
        self.call_start_time = datetime.now()
        self._set_state(self.CONNECTED, {'recipient': peer_name})
        play_sound('titannet/callsuccess.ogg')
        self._notify('call_started', {
            'recipient': peer_name,
            'type': 'outgoing',
            'chat_id': self.current_chat_id,
        })

    @staticmethod
    def _explain(error):
        """Turn a library failure into something worth reading aloud."""
        text = str(error)
        if isinstance(error, NoActiveGroupCall):
            return _("There is no voice chat in this group")
        if isinstance(error, NotInCallError):
            return _("There is no call in progress")
        if 'FLOOD' in text.upper():
            return _("Telegram is rate-limiting calls. Try again in a moment.")
        if 'PRIVACY' in text.upper() or 'USER_PRIVACY' in text.upper():
            return _("This person does not accept calls from you")
        if 'CALL_PROTOCOL' in text.upper():
            return _("The other side's Telegram cannot take this call")
        return text or _("The call could not be started")

    # === INCOMING CALL ===

    async def answer_call(self, user_id=None):
        """Answer the call that is ringing.

        Answering is simply placing our side of the same call: py-tgcalls knows
        a call was requested from this user and accepts it instead of starting a
        new one. The previous version ran its own ``AcceptCallRequest`` with a
        random g_b and no key exchange, which is why a "connected" incoming call
        carried no audio at all.
        """
        if user_id is None:
            user_id = (self.incoming_call or {}).get('user_id')
        if not user_id:
            self._notify('call_failed', {'error': _("There is no call to answer")})
            return False

        if not PYTGCALLS_AVAILABLE or not self.pytgcalls:
            self._notify('call_failed', {
                'error': _('Voice calls require py-tgcalls. Install it with: '
                           'pip install py-tgcalls')
            })
            return False

        mic_ok, mic_reason = self._check_microphone()
        if not mic_ok:
            self._notify('call_failed', {'error': self._microphone_error(mic_reason)})
            return False

        name = (self.incoming_call or {}).get('name') or str(user_id)
        self.current_peer = user_id
        self.current_peer_name = name
        self.current_chat_id = user_id
        self.call_transport = 'private'
        self.mic_active = False
        self._set_state(self.CONNECTING, {'recipient': name})

        try:
            if not await self._ensure_pytgcalls_started():
                raise VoiceCallError(_("Could not start voice system"))
            stream = self._microphone_stream()
            await self.pytgcalls.play(
                user_id, stream, CallConfig(timeout=self.ANSWER_TIMEOUT_SECONDS))
        except VoiceCallError as e:
            await self._reset(str(e))
            return False
        except Exception as e:
            print(f"Answer call failed: {e}")
            await self._reset(self._explain(e))
            return False

        self.incoming_call = None
        self.call_start_time = datetime.now()
        self._set_state(self.CONNECTED, {'recipient': name})
        play_sound('titannet/callsuccess.ogg')
        self._notify('call_answered', {'caller': name})
        self._notify('call_started', {'recipient': name, 'type': 'incoming_accepted'})
        return True

    # Kept under the old name so existing callers keep working.
    async def answer_native_call(self, call_data):
        return await self.answer_call((call_data or {}).get('caller_id'))

    # === GROUP VOICE CHAT ===

    async def join_call(self, group_id):
        """Join an existing group voice chat."""
        if self.state != self.IDLE:
            self._notify('call_failed', {'error': _('Call already in progress')})
            return False

        if not PYTGCALLS_AVAILABLE or not self.pytgcalls:
            self._notify('call_failed', {
                'error': _('Voice calls require py-tgcalls. Install it with: '
                           'pip install py-tgcalls')
            })
            return False

        mic_ok, mic_reason = self._check_microphone()
        if not mic_ok:
            self._notify('call_failed', {'error': self._microphone_error(mic_reason)})
            return False

        # A raw channel id has to be marked before py-tgcalls will read it as a
        # chat rather than a person.
        chat_id = int(group_id)
        if chat_id > 0:
            chat_id = int(f"-100{chat_id}")

        self.current_chat_id = chat_id
        self.call_transport = 'group'
        self.mic_active = False
        self._set_state(self.CONNECTING, {'group_id': chat_id})

        try:
            if not await self._ensure_pytgcalls_started():
                raise VoiceCallError(_("Could not start voice system"))
            stream = self._microphone_stream()
            await self.pytgcalls.play(chat_id, stream,
                                      GroupCallConfig(auto_start=True))
        except VoiceCallError as e:
            await self._reset(str(e))
            return False
        except Exception as e:
            print(f"Join call failed: {e}")
            await self._reset(self._explain(e))
            return False

        self.call_start_time = datetime.now()
        self._set_state(self.CONNECTED, {'group_id': chat_id})
        play_sound('titannet/callsuccess.ogg')
        self._notify('call_started', {'type': 'incoming_accepted',
                                      'group_id': chat_id})
        return True

    # === END CALL ===

    async def end_call(self):
        """Hang up, whichever kind of call this is."""
        if self.state == self.IDLE:
            # Nothing of ours is running, but a call may still be ringing at us.
            if self.incoming_call:
                await self._decline_incoming()
                return True
            return False

        self._set_state(self.ENDING)

        if self.pytgcalls and self.current_chat_id is not None:
            try:
                await self.pytgcalls.leave_call(self.current_chat_id)
            except NotInCallError:
                pass
            except Exception as e:
                print(f"[Telegram voice] leave call: {e}")

        await self._finish_call(None)
        return True

    async def _decline_incoming(self):
        """Refuse a call that is ringing without ever answering it."""
        incoming, self.incoming_call = self.incoming_call, None
        user_id = (incoming or {}).get('user_id')
        if not user_id or not self.pytgcalls:
            return
        try:
            await self.pytgcalls.leave_call(user_id)
        except Exception as e:
            print(f"[Telegram voice] declining: {e}")

    async def _finish_call(self, reason):
        """The call is over - announce it once and go back to idle."""
        if self.state == self.IDLE:
            return
        if reason:
            self._notify('call_failed', {'error': reason})
        self._reset_state()
        play_sound('titannet/bye.ogg')
        self._notify('call_ended', {})

    async def _reset(self, error_message):
        """A call that never happened: report why and go back to idle."""
        if self.pytgcalls and self.current_chat_id is not None:
            try:
                await self.pytgcalls.leave_call(self.current_chat_id)
            except Exception:
                pass
        self._reset_state()
        if error_message:
            self._notify('call_failed', {'error': error_message})
        self._notify('call_ended', {})

    def _reset_state(self):
        self.state = self.IDLE
        self.current_peer = None
        self.current_peer_name = None
        self.current_chat_id = None
        self.call_transport = None
        self.call_start_time = None
        self.is_muted = False
        self.mic_active = False
        self._notify('state_changed', {'old_state': self.ENDING,
                                       'new_state': self.IDLE})

    # === MUTE ===

    async def toggle_mute(self):
        """Toggle the microphone.

        ``pause``/``resume`` (what this used to call) stop the whole stream
        rather than muting it, which on a live call reads to the other side as
        the connection dying.
        """
        if self.state != self.CONNECTED or not self.pytgcalls or \
                self.current_chat_id is None:
            return False

        try:
            if self.is_muted:
                await self.pytgcalls.unmute(self.current_chat_id)
            else:
                await self.pytgcalls.mute(self.current_chat_id)
            self.is_muted = not self.is_muted
            self._notify('mute_changed', {'muted': self.is_muted})
            return True
        except Exception as e:
            print(f"Mute toggle failed: {e}")
            return False

    # === STATUS ===

    ACTIVE_STATES = (SETTING_UP, CONNECTING, RINGING, CONNECTED)

    def get_status(self):
        """Get current call status."""
        duration = 0
        if self.call_start_time:
            duration = (datetime.now() - self.call_start_time).total_seconds()

        return {
            # Ringing is a call in progress. Leaving it out (as this used to)
            # meant a second call could be started over the first, and the call
            # window could not tell "not answered yet" from "no call".
            'active': self.state in self.ACTIVE_STATES,
            'state': self.state,
            'peer': self.current_peer,
            'peer_name': self.current_peer_name,
            'duration': duration,
            'muted': self.is_muted,
            'has_audio': PYTGCALLS_AVAILABLE and self.pytgcalls is not None,
            'transport': self.call_transport,
            'group_id': self.current_group_id,
            'chat_id': self.current_chat_id,
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
    print(f"Voice client initialized (py-tgcalls: "
          f"{'available' if PYTGCALLS_AVAILABLE else 'not available'})")

    # Bind the incoming-call handler right away: a call can ring before the user
    # has ever placed one, and binding only happened on the first outgoing call.
    loop = _voice_client._get_event_loop()
    if loop is not None:
        asyncio.run_coroutine_threadsafe(
            _voice_client._ensure_pytgcalls_started(), loop)


def _run_on_loop(coro, timeout=120):
    """Run async coroutine on the Telegram event loop."""
    if not _voice_client:
        coro.close()
        raise RuntimeError("Voice client not initialized")

    loop = _voice_client._get_event_loop()
    if loop is None:
        coro.close()
        raise RuntimeError("The Telegram client is not running")

    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


def _in_background(coro_factory, label, timeout=120):
    """Run a call operation off the GUI thread and never let it raise there."""
    def _work():
        try:
            _run_on_loop(coro_factory(), timeout=timeout)
        except Exception as e:
            print(f"{label}: {e}")
            import traceback
            traceback.print_exc()
            if _voice_client:
                _voice_client._notify('call_failed', {'error': str(e)})

    threading.Thread(target=_work, daemon=True).start()
    return True


def start_voice_call(recipient):
    """Start voice call with recipient."""
    if not _voice_client:
        print("Voice client not initialized")
        return False

    if not _voice_client.telethon_client:
        print("Telegram client not connected")
        return False

    # The whole call is awaited on the Telegram loop, so the timeout has to
    # outlast ringing - 120 s used to cut a ringing call off mid-ring.
    return _in_background(lambda: _voice_client.start_call(recipient),
                          "Voice call error",
                          timeout=_voice_client.ANSWER_TIMEOUT_SECONDS + 30)


def join_voice_call(group_id):
    """Join an existing group voice chat."""
    if not _voice_client:
        print("Voice client not initialized")
        return False
    return _in_background(lambda: _voice_client.join_call(group_id),
                          "Join call error")


def answer_voice_call(call_data=None):
    """Answer the incoming call."""
    if not _voice_client:
        print("Voice client not initialized")
        return False
    caller_id = (call_data or {}).get('caller_id')
    return _in_background(lambda: _voice_client.answer_call(caller_id),
                          "Answer call error",
                          timeout=_voice_client.ANSWER_TIMEOUT_SECONDS + 30)


def end_voice_call():
    """End current voice call."""
    if not _voice_client:
        return False
    return _in_background(lambda: _voice_client.end_call(),
                          "End call error", timeout=20)


def toggle_mute():
    """Toggle microphone mute."""
    if not _voice_client:
        return False
    return _in_background(lambda: _voice_client.toggle_mute(),
                          "Mute error", timeout=10)


def is_call_active():
    """Check if a call is in progress - including one that is still ringing."""
    if not _voice_client:
        return False
    return _voice_client.state in TelegramVoiceClient.ACTIVE_STATES


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


def call_transport_label():
    """What the audio actually travels over, for the call window to show."""
    if not PYTGCALLS_AVAILABLE:
        return _("Audio: unavailable (py-tgcalls is not installed)")
    status = get_call_status()
    if status.get('transport') == 'group':
        return _("Audio: group voice chat")
    return _("Audio: Telegram call")


# === TCE CALL MESSAGE DETECTION ===

def parse_call_message(message_text):
    """Parse a marker message left by an older version of Titan.

    Nothing sends these any more - a call is a real Telegram call - but a
    marker still sitting in somebody's history must not be shown as a message.
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
