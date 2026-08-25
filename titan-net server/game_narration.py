"""
Titan-Net interactive games - who says the narration out loud.

Gemini used to say it. The model was asked for AUDIO, it synthesised the
narration itself, and the server shipped the PCM to every player. Three
things were wrong with that, and they are all the same thing: the audio
is made by somebody else, far away, after the words already exist.

  * **It is slow.** Nothing reaches a player until the model has
    finished speaking a sentence it had already finished writing. The
    text was sitting on this server the whole time.
  * **It cannot be interrupted.** A player who wants to cut in has to
    wait out a stream that is already in flight, across a websocket, in
    chunks. Stopping a local voice is instant; stopping a remote one is
    a negotiation.
  * **It is not the table's voice.** It is whichever voice the model
    was configured with - not the narrator the people playing chose.

So the model is asked for TEXT, which arrives as fast as text does, and
the **session host's own Titan TTS** speaks it: the server sends the host
a ``game_speak_request``, the host's Titan renders it with whatever
engine and voice that user has set up (Supertonic, Eloquence, SAPI,
ElevenLabs...) and streams the audio back, and the server relays it to
the table as the ``game_ai_audio`` every client already knows how to
play. One narrator for everyone, chosen by the person running the game
rather than baked into the game.

The host is a person on a laptop, so this module assumes they will
sometimes be slow, silent, or gone. Every utterance therefore has a
deadline, and missing it is not an error: the table is simply told to
speak that line with its own voices instead (``game_speak_locally``).
The words always get said - the only question is by whom.

Nothing here touches a websocket. The server hands in two callbacks
(one to the room, one to a user) exactly as the game worker does, so
this is testable with no network, no model and no audio device.
"""

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger('titan-net.game_narration')

# How long the host gets to produce the FIRST chunk of an utterance
# before the table gives up and speaks it locally. A Titan TTS engine
# renders a sentence in well under a second; this is generous enough to
# cover a busy machine and short enough that nobody sits in silence
# wondering whether the game has stopped.
FIRST_CHUNK_TIMEOUT_S = 3.5

# Once audio has started arriving, a gap this long means the host has
# stalled mid-sentence (closed the lid, lost the network). The rest is
# not waited for - the utterance is closed and play continues.
STALL_TIMEOUT_S = 6.0

# A single utterance may not stream for ever: a runaway engine, or a host
# that keeps sending, must not be able to hold the table or fill memory.
MAX_UTTERANCE_S = 120.0

# Per-chunk ceiling (base64 characters). A Titan TTS chunk is a fraction
# of this; anything larger is not narration.
MAX_CHUNK_B64 = 512 * 1024

# The host may not run further ahead of the table than this. Narration is
# consumed in real time, so a host queueing dozens of utterances means
# something is wrong at their end rather than that the game is fast.
MAX_PENDING = 8


class _Utterance:
    """One line of narration, from the moment it is asked for."""

    __slots__ = ('id', 'text', 'actor', 'interrupt', 'requested_at',
                 'first_chunk_at', 'last_chunk_at', 'chunks', 'closed',
                 'spoken_locally')

    def __init__(self, uid: str, text: str, actor: str, interrupt: bool):
        self.id = uid
        self.text = text
        self.actor = actor
        self.interrupt = interrupt
        self.requested_at = time.monotonic()
        self.first_chunk_at: Optional[float] = None
        self.last_chunk_at: Optional[float] = None
        self.chunks = 0
        self.closed = False
        # True once the table has been told to say this line itself, so
        # it can never be said twice.
        self.spoken_locally = False

    def age(self) -> float:
        return time.monotonic() - self.requested_at

    def silent_for(self) -> float:
        last = self.last_chunk_at or self.requested_at
        return time.monotonic() - last


class NarrationRelay:
    """The session's narrator: asks the host to speak, relays what comes
    back, and speaks locally when nothing does.

    ``broadcast_cb(session_id, message)`` reaches the whole table and
    ``send_to_user_cb(user_id, message)`` reaches one person - the same
    two callbacks the game worker is given, so the server keeps sole
    control of the wire.
    """

    def __init__(self, *, session_id: int,
                 broadcast_cb: Callable[[int, Dict], Awaitable[None]],
                 send_to_user_cb: Optional[Callable[[int, Dict], Awaitable[None]]] = None,
                 host_id: Optional[int] = None):
        self.session_id = int(session_id)
        self._broadcast = broadcast_cb
        self._send_to_user = send_to_user_cb
        self._host_id: Optional[int] = int(host_id) if host_id is not None else None
        # The host has to SAY it can narrate. Assuming it and finding out
        # by silence costs the table a timeout on every single line, so
        # the default is "no host narrator" and the host opts in.
        self._host_ready = False
        self._host_voice: Optional[str] = None
        self._pending: Dict[str, _Utterance] = {}
        self._counter = 0
        self._watch: Optional[asyncio.Task] = None
        self._stopped = False
        # Counted for the dashboard: one utterance the host never spoke
        # is not a fault, but a session where that is EVERY line means the
        # host's narration never worked and nobody was told.
        self.stats = {
            'requested': 0,
            'streamed': 0,
            'timed_out': 0,
            'refused': 0,
            'local': 0,
        }

    # ---------------- host capability ----------------

    def set_host(self, user_id: Optional[int]):
        """The host changed (or was learnt). Anything the old host owed
        is abandoned rather than waited for."""
        if self._host_id == user_id:
            return
        self._host_id = int(user_id) if user_id is not None else None
        self._host_ready = False
        self._host_voice = None

    def host_can_speak(self, user_id: int, capable: bool, voice: Optional[str] = None) -> bool:
        """The host's client reporting whether it can narrate.

        Only the HOST is listened to: another player announcing a voice
        would be offering to narrate a game that is not theirs.
        """
        if self._host_id is None or int(user_id) != self._host_id:
            return False
        self._host_ready = bool(capable)
        self._host_voice = voice or None
        logger.info(
            "[GAMES] session %s: host %s %s narrate%s",
            self.session_id, user_id,
            'can' if self._host_ready else 'cannot',
            (' (%s)' % self._host_voice) if self._host_voice else '')
        return True

    def host_gone(self, user_id: int):
        """The host disconnected. Everything they owed is spoken locally."""
        if self._host_id is None or int(user_id) != self._host_id:
            return
        self._host_ready = False

    @property
    def narrating(self) -> bool:
        """True when narration audio is expected to arrive from the host."""
        return bool(self._host_ready and self._host_id is not None and self._send_to_user)

    # ---------------- asking for a line ----------------

    async def say(self, text: str, *, actor: str = 'gm',
                  interrupt: bool = False) -> Optional[str]:
        """Have this line narrated. Returns the utterance id, or None when
        the table is to speak it itself.

        The CALLER still broadcasts the text - this decides only who says
        it out loud, and the answer rides on the text message as
        ``spoken``, so a client never has to guess.
        """
        text = (text or '').strip()
        if not text:
            return None
        if not self.narrating:
            return None
        if len(self._pending) >= MAX_PENDING:
            # The host is not keeping up. Speaking locally is better
            # than queueing behind a machine that has stopped answering.
            logger.warning(
                "[GAMES] session %s: %d utterances outstanding, speaking locally",
                self.session_id, len(self._pending))
            return None

        self._counter += 1
        uid = "u%d-%d" % (self.session_id, self._counter)
        utt = _Utterance(uid, text, actor, interrupt)
        self._pending[uid] = utt
        self.stats['requested'] += 1
        try:
            await self._send_to_user(self._host_id, {
                'type': 'game_speak_request',
                'session_id': self.session_id,
                'utterance_id': uid,
                'actor': actor,
                'text': text,
                'interrupt': bool(interrupt),
            })
        except Exception as e:
            logger.warning("[GAMES] session %s: speak request failed: %s", self.session_id, e)
            self._pending.pop(uid, None)
            return None
        self._ensure_watch()
        return uid

    # ---------------- what comes back ----------------

    async def on_chunk(self, user_id: int, data: Dict) -> Dict:
        """A slice of narration audio from the host, relayed to the table.

        Refused unless it is the host, for a line this session actually
        asked for: an unsolicited chunk is somebody trying to play audio
        at a room they are not narrating.
        """
        if self._host_id is None or int(user_id) != self._host_id:
            self.stats['refused'] += 1
            return {'success': False, 'error': 'Not the session host'}
        uid = str(data.get('utterance_id') or '')
        utt = self._pending.get(uid)
        if utt is None:
            self.stats['refused'] += 1
            return {'success': False, 'error': 'Unknown utterance'}
        audio_b64 = data.get('audio_b64') or ''
        if audio_b64 and len(audio_b64) > MAX_CHUNK_B64:
            self.stats['refused'] += 1
            return {'success': False, 'error': 'Chunk too large'}

        now = time.monotonic()
        if audio_b64:
            if utt.first_chunk_at is None:
                utt.first_chunk_at = now
            utt.last_chunk_at = now
            utt.chunks += 1
            # Relayed as the message every client ALREADY plays, so the
            # whole of this change reaches an unmodified client as
            # ordinary narration audio.
            await self._broadcast(self.session_id, {
                'type': 'game_ai_audio',
                'session_id': self.session_id,
                'actor': utt.actor,
                'utterance_id': uid,
                'audio_b64': audio_b64,
                'mime_type': data.get('mime_type') or 'audio/wav',
                # Only the first chunk of an interrupting line clears what
                # is playing; the rest must join on to it.
                'interrupt': bool(utt.interrupt and utt.chunks == 1),
            })

        if data.get('final'):
            self._close(uid, streamed=utt.chunks > 0)
        return {'success': True, 'utterance_id': uid}

    async def on_failed(self, user_id: int, data: Dict) -> Dict:
        """The host could not speak this line - say it at the table
        instead, at once rather than after the deadline."""
        if self._host_id is None or int(user_id) != self._host_id:
            return {'success': False, 'error': 'Not the session host'}
        uid = str(data.get('utterance_id') or '')
        utt = self._pending.get(uid)
        if utt is None:
            return {'success': False, 'error': 'Unknown utterance'}
        logger.info("[GAMES] session %s: host could not speak %s: %s",
                    self.session_id, uid, data.get('error'))
        await self._speak_locally(utt)
        self._close(uid, streamed=False)
        return {'success': True, 'utterance_id': uid}

    # ---------------- deadlines ----------------

    def _ensure_watch(self):
        if self._watch is None or self._watch.done():
            self._watch = asyncio.ensure_future(self._watch_deadlines())

    async def _watch_deadlines(self):
        """One task, running only while lines are outstanding.

        A host who never answers must not leave the table in silence, so
        every utterance is given its deadline and then handed back to the
        players' own voices.
        """
        try:
            while not self._stopped and self._pending:
                await asyncio.sleep(0.25)
                for uid, utt in list(self._pending.items()):
                    if utt.closed:
                        continue
                    started = utt.first_chunk_at is not None
                    late = (utt.silent_for() > (STALL_TIMEOUT_S if started
                                                else FIRST_CHUNK_TIMEOUT_S))
                    too_long = utt.age() > MAX_UTTERANCE_S
                    if not (late or too_long):
                        continue
                    self.stats['timed_out'] += 1
                    logger.info(
                        "[GAMES] session %s: %s not narrated in time "
                        "(chunks=%d, age=%.1fs) - the table will say it",
                        self.session_id, uid, utt.chunks, utt.age())
                    if not started:
                        # Nothing was heard, so the line has not been said
                        # at all and the players' own voices must say it.
                        await self._speak_locally(utt)
                    self._close(uid, streamed=started)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("[GAMES] session %s: narration watch crashed: %s",
                         self.session_id, e, exc_info=True)

    async def _speak_locally(self, utt: '_Utterance'):
        """Tell the table to say this line with its own voices.

        A separate message rather than a re-send of the text: the text is
        already in every player's log, and putting it there twice is what
        a screen-reader user hears as the game repeating itself.
        """
        if utt.spoken_locally:
            return
        utt.spoken_locally = True
        self.stats['local'] += 1
        try:
            await self._broadcast(self.session_id, {
                'type': 'game_speak_locally',
                'session_id': self.session_id,
                'utterance_id': utt.id,
                'actor': utt.actor,
                'text': utt.text,
                'interrupt': bool(utt.interrupt),
            })
        except Exception as e:
            logger.warning("[GAMES] session %s: local-speech broadcast failed: %s",
                           self.session_id, e)

    def _close(self, uid: str, *, streamed: bool):
        utt = self._pending.pop(uid, None)
        if utt is None:
            return
        utt.closed = True
        if streamed:
            self.stats['streamed'] += 1

    # ---------------- teardown ----------------

    async def stop(self):
        """Session over. Anything still owed is dropped, not spoken: the
        game has ended and narrating into it would be talking to a room
        that has gone."""
        self._stopped = True
        self._pending.clear()
        if self._watch is not None and not self._watch.done():
            self._watch.cancel()
            try:
                await self._watch
            except (asyncio.CancelledError, Exception):
                pass
        self._watch = None

    def status(self) -> Dict[str, Any]:
        """What the moderator dashboard shows about narration."""
        return {
            'host_id': self._host_id,
            'host_ready': self._host_ready,
            'host_voice': self._host_voice,
            'narrating': self.narrating,
            'pending': len(self._pending),
            'stats': dict(self.stats),
        }
