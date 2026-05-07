"""
Titan-Net Interactive Games — Session window
============================================

Runtime UI for a single multiplayer interactive game session. Pairs with
``src.network.interactive_games`` (catalog) and the server-side Gemini
Live worker (Phase 4) wired through ``titan-net server/server.py``.

Layout (row 0 of the listbox is the virtual tab bar, mirroring TitanApp):
    - top toolbar: Send / Talk (push-to-talk) / Advance turn (host) /
      Leave / End (host) / Refresh
    - virtual tab bar: Log / Players / Character sheet / Sounds
    - main listbox: tab content
    - input row: text field + Send

Audio routing:
    - Voice from the active-turn player streams to the server via
      :meth:`TitanNetClient.game_voice_chunk`.
    - AI audio (TTS / Gemini Live audio out) arrives as
      ``on_game_ai_audio`` broadcasts and is played through pygame.
    - SFX broadcasts (`on_game_play_sound`) play to every player in the
      session.

This module never blocks the asyncio event loop — every server call goes
out on a worker thread and dispatches back through ``wx.CallAfter``.

All notification messages and on-screen text are in English; translation
is handled by the ``interactive_games`` gettext domain.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import threading
import time
from typing import Optional, Dict, List

import wx

from src.titan_core.translation import set_language
from src.settings.settings import get_setting
from src.titan_core.sound import (
    play_sound,
    initialize_sound,
    play_focus_sound,
    play_endoflist_sound,
)
from src.titan_core.skin_manager import apply_skin_to_window

_ = set_language(get_setting('language', 'pl'))

try:
    import accessible_output3.outputs.auto as _ao_auto
    _local_speaker = _ao_auto.Auto()
except Exception as _e:
    print(f"[Game Session] accessible_output3 unavailable: {_e}")
    _local_speaker = None


def _show_skinned_message(message, caption, style=wx.OK | wx.ICON_INFORMATION, parent=None):
    dlg = wx.MessageDialog(parent, message, caption, style)
    try:
        apply_skin_to_window(dlg)
    except Exception:
        pass
    result = dlg.ShowModal()
    dlg.Destroy()
    return result


def _speak(text, interrupt=True):
    """Quick TTS fallback — prefer titan_net_gui's stereo helper."""
    if not text:
        return
    try:
        from src.network import titan_net_gui
        helper = getattr(titan_net_gui, 'speak_titannet', None)
        if helper is not None:
            helper(text, interrupt=interrupt)
            return
    except Exception:
        pass
    if _local_speaker is not None:
        try:
            _local_speaker.speak(str(text), interrupt=interrupt)
        except Exception:
            pass


def _speak_notification(text, kind='info', play_sound_effect=True):
    if not text:
        return
    try:
        from src.network import titan_net_gui
        helper = getattr(titan_net_gui, 'speak_notification', None)
        if helper is not None:
            helper(text, notification_type=kind, play_sound_effect=play_sound_effect)
            return
    except Exception:
        pass
    if play_sound_effect:
        try:
            play_sound({'error': 'core/error.ogg', 'success': 'core/SELECT.ogg',
                        'warning': 'core/error.ogg'}.get(kind, 'ui/dialog.ogg'))
        except Exception:
            pass
    _speak(text)


try:
    initialize_sound()
except Exception as _e:
    print(f"[Game Session] initialize_sound() failed at import: {_e}")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SESSION_TABS = (
    ('log',       lambda: _("Game log")),
    ('players',   lambda: _("Players")),
    ('character', lambda: _("Character sheet")),
    ('sounds',    lambda: _("Sound effects")),
)

# How many log entries to keep client-side.
MAX_LOG_ENTRIES = 500


def _announce_tab_bar() -> None:
    try:
        from src.accessibility.messages import announce_tab_bar as _a
        _a()
        return
    except Exception:
        pass
    try:
        play_sound('ui/tapbar.ogg')
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Audio playback helper for AI audio chunks
# ---------------------------------------------------------------------------

class _AIAudioPlayer:
    """Plays back AI audio chunks (Gemini Live audio out + TTS).

    Two parallel audio paths so SFX and TTS never fight over the same
    output channel:

      1. **Streaming PCM via sounddevice OutputStream** — Gemini Live
         ships PCM at 24 kHz mono 16-bit, and Live audio chunks
         arrive faster than realtime (the model "speaks" 2 s of audio
         in ~500 ms wall time). We push raw PCM into a thread-safe
         buffer and let an OutputStream callback drain it at the
         exact source rate. No resampling, no per-chunk Sound objects,
         no clicky gaps.

      2. **pygame.mixer.Sound for SFX** — game sound effects fetched
         via the ``play_sound`` tool play through the shared mixer
         the rest of TCE uses. Because they're on a different audio
         backend than the streaming TTS, they overlap with the
         narration cleanly (cinematic feel — gunshot during AI
         narration etc., per user request).
    """

    DEFAULT_RATE = 24000  # Gemini Live PCM rate
    CHUNK_SAMPLES = 480   # 20 ms at 24kHz — small enough that interrupt
                          # tears down audio fast, large enough that the
                          # OutputStream callback never starves on a slow
                          # decode loop

    def __init__(self):
        self._lock = threading.Lock()
        self._tempdir = tempfile.mkdtemp(prefix='titan_game_audio_')
        self._counter = 0
        self._enabled = True

        # ---- Streaming PCM playback (Gemini TTS) via sounddevice ----
        # Buffer raw int16 PCM bytes. The OutputStream callback pulls
        # exactly the number of samples it needs every tick — silence
        # is filled in if the buffer underruns (still better than
        # speed drift / clicks).
        self._sd = None
        self._stream = None
        self._pcm_buf = bytearray()
        self._pcm_lock = threading.Lock()
        self._pcm_rate = self.DEFAULT_RATE
        try:
            import sounddevice as sd
            self._sd = sd
            self._open_stream(self._pcm_rate)
        except Exception as e:
            print(f"[Game Session] sounddevice unavailable, falling back "
                  f"to pygame WAV playback: {e}")

        # ---- Layered SFX/music playback via pygame.mixer ----
        # Three independent layers so the AI can stack a music bed
        # under ambient under one-shot SFX, exactly like a film mix.
        # Each layer owns its own dedicated mixer Channel.
        try:
            import pygame
            self._pygame = pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            # Reserve channels 0/1/2 so they're never stolen by
            # find_channel(force=True) for ad-hoc Sound.play() calls.
            pygame.mixer.set_reserved(3)
            self._channels = {
                'music':   pygame.mixer.Channel(0),
                'ambient': pygame.mixer.Channel(1),
                'sfx':     pygame.mixer.Channel(2),
            }
            self._layer_volume = {'music': 1.0, 'ambient': 1.0, 'sfx': 1.0}
            self._layer_sounds = {}  # layer -> Sound object (kept alive while looping)
        except Exception as e:
            print(f"[Game Session] pygame mixer unavailable: {e}")
            self._pygame = None
            self._channels = {}
            self._layer_volume = {}
            self._layer_sounds = {}

        # ---- Cache fetched attachments ----
        # First play_sound for an attachment_id pulls the bytes from
        # the server; subsequent calls (loops, replays) reuse the
        # in-memory copy. This is what the user calls "streaming" —
        # the audio doesn't have to be re-downloaded each time.
        self._attachment_cache = {}  # attachment_id -> bytes

    def _open_stream(self, rate: int):
        """Open / re-open the sounddevice OutputStream at the given rate."""
        if self._sd is None:
            return
        try:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            stream = self._sd.RawOutputStream(
                samplerate=rate,
                channels=1,
                dtype='int16',
                blocksize=self.CHUNK_SAMPLES,
                callback=self._sd_callback,
            )
            stream.start()
            self._stream = stream
            self._pcm_rate = rate
            print(f"[Game Session] AI TTS stream opened at {rate} Hz")
        except Exception as e:
            print(f"[Game Session] AI TTS stream open failed: {e}")
            self._sd = None  # disable streaming path

    def _sd_callback(self, outdata, frames, time, status):
        """sounddevice pulls 'frames' samples on every tick.

        We pop ``frames * 2`` bytes from the buffer (16-bit mono = 2 B
        per sample). Underrun is filled with silence — better than
        speed drift, and Gemini chunks usually catch up within one
        tick because they arrive faster than realtime.
        """
        needed = frames * 2  # int16 mono
        with self._pcm_lock:
            available = len(self._pcm_buf)
            if available >= needed:
                payload = bytes(self._pcm_buf[:needed])
                del self._pcm_buf[:needed]
            else:
                payload = bytes(self._pcm_buf) + b'\x00' * (needed - available)
                self._pcm_buf.clear()
        try:
            outdata[:] = payload
        except Exception:
            # outdata is a CFFI buffer; assigning bytes works, but if
            # frames count differs we silently drop.
            pass

    def play_chunk(self, audio_b64: str, mime_type: Optional[str] = None,
                   interrupt: bool = False):
        """Route audio to the right backend based on mime_type.

        * ``audio/pcm`` (Gemini Live TTS) → sounddevice streaming buffer.
          Continuous, no gaps, plays at exact source rate.
        * everything else (.ogg/.mp3/.wav SFX from game attachments) →
          pygame.mixer.Sound. Pygame is on a separate audio path so
          SFX overlaps cleanly with the AI narration.
        """
        if not self._enabled or not audio_b64:
            return
        try:
            data = base64.b64decode(audio_b64)
        except Exception as e:
            print(f"[Game Session] audio decode failed: {e}")
            return

        mt = (mime_type or '').lower()
        is_raw_pcm = ('audio/pcm' in mt) or ('audio/l16' in mt)

        if is_raw_pcm:
            self._enqueue_pcm(data, mime_type=mt, interrupt=interrupt)
            return
        # SFX / WAV / OGG / MP3 path → pygame
        self._play_via_pygame(data, mime_type=mime_type, interrupt=interrupt)

    def _enqueue_pcm(self, pcm: bytes, mime_type: str, interrupt: bool):
        """Push raw PCM into the sounddevice playback buffer."""
        # Pull source rate out of the mime ("audio/pcm;rate=24000").
        rate = self.DEFAULT_RATE
        for part in mime_type.replace(' ', '').split(';'):
            if part.startswith('rate='):
                try:
                    rate = int(part.split('=', 1)[1])
                except Exception:
                    pass
        # Re-open the stream if the rate changed.
        if self._sd is not None and rate != self._pcm_rate:
            self._open_stream(rate)
        if self._sd is None or self._stream is None:
            # Fallback when sounddevice isn't installed: wrap in WAV
            # and play through pygame. Quality / gap tradeoffs are
            # worse but at least the user hears something.
            self._fallback_pcm_via_pygame(pcm, rate, interrupt=interrupt)
            return
        with self._pcm_lock:
            if interrupt:
                self._pcm_buf.clear()
            self._pcm_buf.extend(pcm)

    def _fallback_pcm_via_pygame(self, pcm: bytes, rate: int, interrupt: bool):
        """Wrap raw PCM in a WAV header and play via pygame.

        Used only when sounddevice is not available — playback will
        have audible seams between chunks but at least functions.
        """
        if self._pygame is None:
            return
        import struct
        bits = 16
        channels = 1
        byte_rate = rate * channels * bits // 8
        block_align = channels * bits // 8
        data_size = len(pcm)
        header = b''.join([
            b'RIFF', struct.pack('<I', 36 + data_size), b'WAVE',
            b'fmt ', struct.pack('<I', 16), struct.pack('<H', 1),
            struct.pack('<H', channels), struct.pack('<I', rate),
            struct.pack('<I', byte_rate), struct.pack('<H', block_align),
            struct.pack('<H', bits), b'data', struct.pack('<I', data_size),
        ])
        self._play_via_pygame(header + pcm, mime_type='audio/wav',
                              interrupt=interrupt)

    @staticmethod
    def _pan_to_lr(p: float) -> tuple:
        """Linear stereo pan: returns (left_factor, right_factor) for
        a pan value in [-1, +1]. -1 → (1, 0); 0 → (1, 1); +1 → (0, 1)."""
        p = max(-1.0, min(1.0, float(p or 0.0)))
        left  = 1.0 if p <= 0.0 else max(0.0, 1.0 - p)
        right = 1.0 if p >= 0.0 else max(0.0, 1.0 + p)
        return left, right

    def _play_via_pygame(self, data: bytes, mime_type: Optional[str],
                         interrupt: bool, layer: str = 'sfx',
                         loop: bool = False, volume: float = 1.0,
                         pan: float = 0.0,
                         pan_to: Optional[float] = None,
                         pan_duration_ms: int = 1500):
        """Play through pygame.mixer on the requested layer.

        Music + ambient go on reserved Channels (0/1) so they keep
        looping under whatever else plays. SFX use the reserved
        Channel 2 so multiple SFX never queue indefinitely — a new
        one replaces the old one (matches typical game behaviour).

        ``pan`` is a continuous stereo position in [-1.0, +1.0]: -1 =
        full left, 0 = centered, +1 = full right. Linear panning via
        ``Channel.set_volume(left, right)`` — pygame multiplies the
        channel L/R factors with the sound's own volume. Float values
        like 0.3 / 0.5 / 0.7 produce smooth audiogame-style spatial
        positioning, not just hard left/right.

        ``pan_to`` (optional) triggers a smooth motion sweep: pan is
        interpolated linearly from ``pan`` to ``pan_to`` over
        ``pan_duration_ms`` milliseconds, with channel volume updated
        every ~30 ms (~33 fps). This is what makes a flyover sound
        like real spatial motion instead of a few discrete jumps. A
        per-layer token cancels any in-flight sweep when a new SFX
        starts on the same channel, so sweeps never bleed across cues.
        """
        if self._pygame is None:
            return
        ext = '.wav'
        mt = (mime_type or '').lower()
        if 'opus' in mt:
            ext = '.opus'
        elif 'ogg' in mt:
            ext = '.ogg'
        elif 'mp3' in mt or 'mpeg' in mt:
            ext = '.mp3'
        elif 'flac' in mt:
            ext = '.flac'
        with self._lock:
            self._counter += 1
            path = os.path.join(self._tempdir, f'chunk_{self._counter}{ext}')
        try:
            with open(path, 'wb') as fh:
                fh.write(data)
        except Exception as e:
            print(f"[Game Session] sfx write failed: {e}")
            return
        try:
            sound = self._pygame.mixer.Sound(path)
            ch = self._channels.get(layer)
            # Compute per-side factors for linear stereo panning. pygame
            # multiplies channel L/R with the sound's own volume, so we
            # leave volume on `sound.set_volume` and use the channel
            # volume purely for left/right balance.
            start_pan = max(-1.0, min(1.0, float(pan or 0.0)))
            left_factor, right_factor = self._pan_to_lr(start_pan)
            if ch is None:
                # Unknown layer — fall back to one-shot Sound.play() with
                # no panning (Sound.play returns its own Channel; we don't
                # track it so we can't re-pan it later or sweep it).
                if interrupt:
                    self._pygame.mixer.stop()
                sound.set_volume(volume)
                sound.play()
                return
            # Adjust effective volume = sound volume * layer volume
            base = self._layer_volume.get(layer, 1.0)
            sound.set_volume(max(0.0, min(1.0, volume * base)))
            # Keep a reference so loop'd music doesn't get GC'd
            self._layer_sounds[layer] = sound
            loops = -1 if loop else 0
            ch.play(sound, loops=loops)
            # Apply the L/R balance AFTER play() — pygame resets channel
            # volume to (1, 1) on each new play(). We always set it (even
            # for centered sounds) so a previously-panned SFX never leaks
            # its position into the next play on the same channel.
            try:
                ch.set_volume(left_factor, right_factor)
            except Exception:
                pass
            # Cancel any in-flight sweep on this layer (each new play()
            # bumps the token; old sweep threads check it and exit).
            if not hasattr(self, '_layer_sweep_tokens'):
                self._layer_sweep_tokens = {}
            self._layer_sweep_tokens[layer] = (
                self._layer_sweep_tokens.get(layer, 0) + 1
            )
            # If the AI asked for a motion sweep, kick off the
            # interpolator. Skip if the start and end are effectively
            # the same — saves a thread for nothing.
            if pan_to is not None:
                try:
                    target_pan = max(-1.0, min(1.0, float(pan_to)))
                except Exception:
                    target_pan = start_pan
                if abs(target_pan - start_pan) > 0.01:
                    duration_s = max(0.05, float(pan_duration_ms) / 1000.0)
                    token = self._layer_sweep_tokens[layer]
                    self._spawn_pan_sweep(ch, layer, token,
                                          start_pan, target_pan, duration_s)
        except Exception as e:
            print(f"[Game Session] layer={layer} play failed: {e}")

    def _spawn_pan_sweep(self, channel, layer: str, token: int,
                          start_pan: float, target_pan: float,
                          duration_s: float):
        """Background thread that interpolates pan over ``duration_s``.

        Updates ``Channel.set_volume(L, R)`` every ~30 ms (~33 fps) so a
        flyover or pass-by sounds genuinely continuous. Bails out if a
        newer play() on the same layer bumped the token, or if pygame
        raises (mixer shut down etc.).
        """
        TICK_S = 0.030

        def _sweep():
            try:
                start_t = time.monotonic()
                while True:
                    if self._layer_sweep_tokens.get(layer) != token:
                        return
                    elapsed = time.monotonic() - start_t
                    if elapsed >= duration_s:
                        L, R = self._pan_to_lr(target_pan)
                        try:
                            channel.set_volume(L, R)
                        except Exception:
                            pass
                        return
                    t = elapsed / duration_s
                    cur_pan = start_pan + (target_pan - start_pan) * t
                    L, R = self._pan_to_lr(cur_pan)
                    try:
                        channel.set_volume(L, R)
                    except Exception:
                        return
                    time.sleep(TICK_S)
            except Exception as e:
                print(f"[Game Session] pan sweep failed: {e}")

        threading.Thread(target=_sweep, daemon=True).start()

    def stop_layer(self, layer: str):
        """Stop music/ambient/sfx — or 'all' to silence everything."""
        if self._pygame is None:
            return
        if layer == 'all':
            for ch in self._channels.values():
                try:
                    ch.stop()
                except Exception:
                    pass
            self._layer_sounds.clear()
            return
        ch = self._channels.get(layer)
        if ch is not None:
            try:
                ch.stop()
            except Exception:
                pass
        self._layer_sounds.pop(layer, None)

    def set_layer_volume(self, layer: str, volume: float):
        """Adjust layer volume. Applied to currently-playing sound too."""
        volume = max(0.0, min(1.0, float(volume)))
        if layer not in self._layer_volume:
            return
        self._layer_volume[layer] = volume
        snd = self._layer_sounds.get(layer)
        if snd is not None:
            try:
                snd.set_volume(volume)
            except Exception:
                pass

    def stop_all(self):
        # Stop streaming TTS by clearing the PCM buffer (callback will
        # immediately get silence for the rest of this turn).
        with self._pcm_lock:
            self._pcm_buf.clear()
        if self._pygame is not None:
            try:
                self._pygame.mixer.stop()
            except Exception:
                pass

    def shutdown(self):
        self._enabled = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        try:
            import shutil
            shutil.rmtree(self._tempdir, ignore_errors=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Push-to-talk capture worker
# ---------------------------------------------------------------------------

class _MicCapture(threading.Thread):
    """Capture microphone audio while ``active`` is set and forward
    base64-encoded chunks via ``send_callback``.

    Uses sounddevice when available, falling back to a no-op when not —
    voice features are optional on platforms without it.
    """

    def __init__(self, send_callback):
        super().__init__(daemon=True)
        self._send = send_callback
        self._stop = threading.Event()
        self._active = threading.Event()
        self._sd = None
        try:
            import sounddevice as sd
            self._sd = sd
        except Exception as e:
            print(f"[Game Session] sounddevice unavailable: {e}")
        self._sample_rate = 16000
        self._channels = 1
        self._chunk_ms = 30  # webrtcvad-friendly sizing in case Phase 4 enables VAD

    def set_active(self, active: bool):
        if active:
            self._active.set()
        else:
            self._active.clear()

    def stop(self):
        self._stop.set()
        self._active.clear()

    def run(self):
        if self._sd is None:
            print("[Game Session] mic capture disabled (sounddevice missing)")
            return
        chunk_frames = int(self._sample_rate * self._chunk_ms / 1000)
        try:
            with self._sd.InputStream(samplerate=self._sample_rate,
                                      channels=self._channels,
                                      dtype='int16',
                                      blocksize=chunk_frames) as stream:
                while not self._stop.is_set():
                    if not self._active.is_set():
                        # idle wait without burning CPU
                        time.sleep(0.05)
                        continue
                    try:
                        data, _overflow = stream.read(chunk_frames)
                        if data is None:
                            continue
                        # data is a NumPy array — convert to bytes
                        try:
                            payload = data.tobytes()
                        except Exception:
                            payload = bytes(data)
                        self._send(payload)
                    except Exception as e:
                        print(f"[Game Session] mic read failed: {e}")
                        time.sleep(0.1)
        except Exception as e:
            print(f"[Game Session] mic stream init failed: {e}")


# ---------------------------------------------------------------------------
# Main session frame
# ---------------------------------------------------------------------------

class GameSessionFrame(wx.Frame):
    """One window per running interactive game session."""

    def __init__(self, parent, titan_client, session_id: int,
                 game_id: int, is_host: bool):
        super().__init__(parent, title=_("Interactive game session"),
                         size=(820, 620))
        self.titan_client = titan_client
        self.session_id = session_id
        self.game_id = game_id
        self.is_host = is_host
        self.session: Optional[Dict] = None
        self.log_entries: List[Dict] = []     # {actor, text, ts, kind}
        self.players_cache: List[Dict] = []
        self.sounds_cache: List[Dict] = []    # {file_name, last_played}
        self.current_tab = 'log'
        self._last_focus_idx = -1
        self._closed = False
        self._mic_active = False

        self.audio = _AIAudioPlayer()
        self.mic = _MicCapture(self._on_mic_chunk)
        self.mic.start()

        self._build()
        self.Centre()
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self._install_callbacks()

        try:
            play_sound('titannet/interactive games/session opened.ogg')
        except Exception:
            try:
                play_sound('ui/popup.ogg')
            except Exception:
                pass

        # Initial pull
        wx.CallAfter(self._refresh_session)

    def _build(self):
        self.panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.view_label = wx.StaticText(self.panel, label=_("Interactive game session"))
        sizer.Add(self.view_label, flag=wx.ALL, border=8)

        # --- Toolbar ---
        bar = wx.BoxSizer(wx.HORIZONTAL)
        self.send_btn = wx.Button(self.panel, label=_("Send action"))
        self.send_btn.Bind(wx.EVT_BUTTON, self._on_send_action)
        bar.Add(self.send_btn, flag=wx.RIGHT, border=4)

        # Mic is always available — the AI decides whose action is in scope
        # by reading the [username] prefix on each player message. There is
        # no manual turn gating anymore.
        self.talk_btn = wx.ToggleButton(self.panel, label=_("Talk (mic OFF)"))
        self.talk_btn.Bind(wx.EVT_TOGGLEBUTTON, self._on_toggle_mic)
        bar.Add(self.talk_btn, flag=wx.RIGHT, border=4)

        self.leave_btn = wx.Button(self.panel, label=_("Leave"))
        self.leave_btn.Bind(wx.EVT_BUTTON, self._on_leave)
        bar.Add(self.leave_btn, flag=wx.RIGHT, border=4)

        self.end_btn = wx.Button(self.panel, label=_("End session"))
        self.end_btn.Bind(wx.EVT_BUTTON, self._on_end)
        if not self.is_host:
            self.end_btn.Hide()
        bar.Add(self.end_btn, flag=wx.RIGHT, border=4)

        self.refresh_btn = wx.Button(self.panel, label=_("Refresh"))
        self.refresh_btn.Bind(wx.EVT_BUTTON, lambda e: self._refresh_session())
        bar.Add(self.refresh_btn, flag=wx.RIGHT, border=4)

        sizer.Add(bar, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=8)

        # --- Tab content list ---
        sizer.Add(wx.StaticText(self.panel, label=_("Session view:")),
                  flag=wx.LEFT | wx.RIGHT | wx.TOP, border=8)
        self.listbox = wx.ListBox(self.panel, style=wx.LB_SINGLE)
        self.listbox.Bind(wx.EVT_LISTBOX, self._on_select)
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, self._on_activate)
        sizer.Add(self.listbox, proportion=1, flag=wx.EXPAND | wx.ALL, border=8)

        # --- Action row ---
        action_box = wx.BoxSizer(wx.HORIZONTAL)
        action_box.Add(wx.StaticText(self.panel, label=_("Type your action:")),
                       flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=4)
        self.input_ctrl = wx.TextCtrl(self.panel, style=wx.TE_PROCESS_ENTER)
        self.input_ctrl.Bind(wx.EVT_TEXT_ENTER, self._on_send_action)
        action_box.Add(self.input_ctrl, proportion=1,
                       flag=wx.LEFT | wx.RIGHT | wx.EXPAND, border=4)
        sizer.Add(action_box, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=8)

        self.CreateStatusBar()
        self.panel.SetSizer(sizer)

        self.Bind(wx.EVT_CHAR_HOOK, self._on_key_hook)

        accel = wx.AcceleratorTable([
            (wx.ACCEL_NORMAL, wx.WXK_F5, self.refresh_btn.GetId()),
            (wx.ACCEL_CTRL, ord('T'), self.talk_btn.GetId()),
        ])
        self.SetAcceleratorTable(accel)
        self.Bind(wx.EVT_MENU, lambda e: self._refresh_session(), id=self.refresh_btn.GetId())

    # ------------------------------------------------------------------
    # Broadcast subscriptions
    # ------------------------------------------------------------------

    def _install_callbacks(self):
        self._old_callbacks = {}
        names = (
            'game_session_ended', 'game_player_joined', 'game_player_left',
            'game_turn_changed', 'game_player_action', 'game_ai_text',
            'game_ai_audio', 'game_play_sound', 'game_stop_sound',
            'game_set_volume', 'game_state_changed', 'game_token_warning',
            'game_menu',
        )
        for name in names:
            self._old_callbacks[name] = getattr(self.titan_client, f'on_{name}', None)
        self.titan_client.on_game_session_ended = self._handle_session_ended
        self.titan_client.on_game_player_joined = self._handle_player_joined
        self.titan_client.on_game_player_left = self._handle_player_left
        self.titan_client.on_game_turn_changed = self._handle_turn_changed
        self.titan_client.on_game_player_action = self._handle_player_action
        self.titan_client.on_game_ai_text = self._handle_ai_text
        self.titan_client.on_game_ai_audio = self._handle_ai_audio
        self.titan_client.on_game_play_sound = self._handle_play_sound
        self.titan_client.on_game_stop_sound = self._handle_stop_sound
        self.titan_client.on_game_set_volume = self._handle_set_volume
        self.titan_client.on_game_state_changed = self._handle_state_changed
        self.titan_client.on_game_token_warning = self._handle_token_warning
        self.titan_client.on_game_player_speech = self._handle_player_speech
        self.titan_client.on_game_menu = self._handle_game_menu

    def _restore_callbacks(self):
        for name, cb in (self._old_callbacks or {}).items():
            try:
                setattr(self.titan_client, f'on_{name}', cb)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Remote event handlers — every one of these runs on the listener
    # thread, so anything UI-bound is dispatched via wx.CallAfter.
    # ------------------------------------------------------------------

    def _is_for_session(self, message: Dict) -> bool:
        return int(message.get('session_id') or 0) == int(self.session_id)

    def _handle_session_ended(self, message: Dict):
        if not self._is_for_session(message):
            return
        wx.CallAfter(self._on_session_ended_local, message.get('reason') or '')

    def _on_session_ended_local(self, reason: str):
        try:
            play_sound('titannet/interactive games/session ended.ogg')
        except Exception:
            pass
        _speak_notification(_("Session ended: {reason}").format(reason=reason or _("done")),
                            'warning', play_sound_effect=False)
        self._append_log('system', _("Session ended ({reason})").format(reason=reason or '?'))
        self.send_btn.Disable()
        self.talk_btn.Disable()
        self.input_ctrl.Disable()
        self.mic.set_active(False)

    def _handle_player_joined(self, message: Dict):
        if not self._is_for_session(message):
            return
        wx.CallAfter(self._refresh_session)
        wx.CallAfter(self._append_log, 'system',
                     _("{user} joined").format(user=message.get('username', '?')))
        try:
            play_sound('titannet/interactive games/player joined.ogg')
        except Exception:
            pass

    def _handle_player_left(self, message: Dict):
        if not self._is_for_session(message):
            return
        wx.CallAfter(self._refresh_session)
        wx.CallAfter(self._append_log, 'system',
                     _("{user} left").format(user=message.get('username', '?')))
        try:
            play_sound('titannet/interactive games/player left.ogg')
        except Exception:
            pass

    def _handle_turn_changed(self, message: Dict):
        """Turn rotation is purely informational now.

        Old design forced the mic open/closed based on whose turn it was.
        New design: any player can talk anytime, the AI reads the
        [username] prefix on each message and decides who's acting.
        We still log turn changes if the AI emits one.
        """
        if not self._is_for_session(message):
            return
        active_id = int(message.get('active_user_id') or 0)
        idx = int(message.get('current_turn_idx', 0) or 0)
        wx.CallAfter(self._on_turn_changed_local, active_id, idx)

    def _on_turn_changed_local(self, active_id: int, idx: int):
        try:
            play_sound('titannet/interactive games/turn changed.ogg')
        except Exception:
            pass
        name = '?'
        for p in self.players_cache:
            if p.get('user_id') == active_id:
                name = p.get('username', '?')
                break
        my_id = int(getattr(self.titan_client, 'user_id', 0) or 0)
        if active_id == my_id:
            self._append_log('system', _("Spotlight on you (slot {n})").format(n=idx + 1))
        else:
            self._append_log('system', _("Spotlight on {user} (slot {n})").format(user=name, n=idx + 1))

    def _handle_player_action(self, message: Dict):
        if not self._is_for_session(message):
            return
        wx.CallAfter(self._append_log, f"player:{message.get('username', '?')}",
                     message.get('text', ''))

    def _handle_ai_text(self, message: Dict):
        if not self._is_for_session(message):
            return
        text = (message.get('text') or '').strip()
        if not text:
            return
        actor = message.get('actor') or 'gm'

        # De-duplicate near-identical lines that arrive close together.
        # The server worker also dedupes (see flush_text in
        # gemini_game_worker.py) but this is belt-and-braces against any
        # path that bypasses that — and against the model legitimately
        # repeating itself. Window matches the server: 30 s. We allow
        # delta broadcasts through (server already strips the duplicate
        # prefix in the continuation case), so an exact prefix match here
        # is still a duplicate.
        DEDUP_WINDOW_S = 30.0
        DEDUP_PREFIX_LEN = 80
        now = time.time()
        last = getattr(self, '_last_ai_text', None)
        if last is not None:
            prev_text, prev_time = last
            if (now - prev_time) < DEDUP_WINDOW_S:
                a = prev_text.strip().lower()
                b = text.strip().lower()
                if a == b:
                    print(f"[Game Session] dropped exact-duplicate AI text: {text[:80]!r}")
                    return
                a_pref = a[:DEDUP_PREFIX_LEN]
                b_pref = b[:DEDUP_PREFIX_LEN]
                if a_pref == b_pref and len(a_pref) >= 20:
                    print(f"[Game Session] dropped near-duplicate AI text: {text[:80]!r}")
                    return
        self._last_ai_text = (text, now)

        # Append to the on-screen log only. Gemini Live ships its own
        # TTS audio via game_ai_audio broadcasts — re-speaking the same
        # narration through TitanTTS would double-up the narration and
        # the user explicitly asked us not to do that.
        wx.CallAfter(self._append_log, f"ai:{actor}", text)

    def _handle_ai_audio(self, message: Dict):
        if not self._is_for_session(message):
            return
        audio_b64 = message.get('audio_b64')
        mime = message.get('mime_type')
        interrupt = bool(message.get('interrupt'))
        if audio_b64:
            self.audio.play_chunk(audio_b64, mime_type=mime, interrupt=interrupt)

    def _handle_play_sound(self, message: Dict):
        if not self._is_for_session(message):
            return
        theme_path = message.get('theme_path')
        attachment_id = message.get('attachment_id')
        layer = (message.get('layer') or 'sfx').strip().lower()
        loop = bool(message.get('loop', False))
        try:
            volume = float(message.get('volume', 1.0))
        except Exception:
            volume = 1.0
        # Continuous stereo pan in [-1, +1]. Float values like 0.3 / 0.5
        # produce smooth spatial positioning, not just hard left/right —
        # this is the audiogame-style fluid panning the AI should use
        # for combat (attacker on the right, footsteps far left, etc.).
        try:
            pan = float(message.get('pan', 0.0))
        except Exception:
            pan = 0.0
        pan = max(-1.0, min(1.0, pan))
        # Optional motion sweep: pan_to is the destination position; the
        # client interpolates pan from start to end over pan_duration_ms
        # at ~33 fps, so a fly-by really sounds like a fly-by, not steps.
        pan_to_raw = message.get('pan_to')
        if pan_to_raw is None:
            pan_to = None
        else:
            try:
                pan_to = max(-1.0, min(1.0, float(pan_to_raw)))
            except Exception:
                pan_to = None
        try:
            pan_duration_ms = int(message.get('pan_duration_ms', 1500))
        except Exception:
            pan_duration_ms = 1500
        pan_duration_ms = max(50, min(30000, pan_duration_ms))
        if theme_path:
            # TCE theme sound — one-shot, no layer routing or panning.
            try:
                play_sound(theme_path)
            except Exception as e:
                print(f"[Game Session] play_sound theme {theme_path}: {e}")
            wx.CallAfter(self._append_sound, theme_path)
        elif attachment_id:
            wx.CallAfter(self._fetch_and_play_attachment, int(attachment_id),
                         message.get('label') or f"attachment_{attachment_id}",
                         layer, loop, volume, pan, pan_to, pan_duration_ms)

    def _handle_stop_sound(self, message: Dict):
        if not self._is_for_session(message):
            return
        layer = (message.get('layer') or 'all').strip().lower()
        wx.CallAfter(self.audio.stop_layer, layer)
        wx.CallAfter(self._append_sound, _("stop {layer}").format(layer=layer))

    def _handle_player_speech(self, message: Dict):
        """Gemini transcribed someone's mic input. Show it to all players."""
        if not self._is_for_session(message):
            return
        text = message.get('text', '').strip()
        if not text:
            return
        wx.CallAfter(self._append_log, 'voice', text)

    def _handle_set_volume(self, message: Dict):
        if not self._is_for_session(message):
            return
        layer = (message.get('layer') or '').strip().lower()
        try:
            volume = float(message.get('volume', 1.0))
        except Exception:
            return
        wx.CallAfter(self.audio.set_layer_volume, layer, volume)
        wx.CallAfter(self._append_sound,
                     _("volume {layer}={volume:.2f}").format(layer=layer, volume=volume))

    def _fetch_and_play_attachment(self, attachment_id: int, label: str,
                                    layer: str = 'sfx', loop: bool = False,
                                    volume: float = 1.0, pan: float = 0.0,
                                    pan_to: Optional[float] = None,
                                    pan_duration_ms: int = 1500):
        """Fetch (or reuse cached) attachment bytes + dispatch to the layer.

        First call for an ID downloads from the server; subsequent calls
        (e.g. looped music replays) reuse the in-memory cache. Network
        round-trip is still done on the worker thread so the UI stays
        responsive. ``pan`` is the continuous stereo start position in
        [-1, +1]; ``pan_to`` (optional) is the destination — the client
        interpolates between them over ``pan_duration_ms`` for a smooth
        audiogame-style flyover.
        """
        cache = getattr(self.audio, '_attachment_cache', None)
        if cache is not None and attachment_id in cache:
            cached = cache[attachment_id]
            self.audio._play_via_pygame(
                cached['bytes'], mime_type=cached.get('mime'),
                interrupt=False, layer=layer, loop=loop, volume=volume,
                pan=pan, pan_to=pan_to, pan_duration_ms=pan_duration_ms,
            )
            wx.CallAfter(self._append_sound, _("[{layer}] {label} (cached)").format(
                layer=layer, label=label))
            return

        def _fetch():
            result = self.titan_client.get_game_attachment(attachment_id)
            if not result.get('success') or not result.get('bytes'):
                print(f"[Game Session] Failed to fetch SFX {attachment_id}: {result.get('error')}")
                return
            fname = result.get('file_name') or label or ''
            ext = os.path.splitext(fname)[1].lower()
            mime_map = {
                '.ogg':  'audio/ogg',
                '.opus': 'audio/opus',
                '.wav':  'audio/wav',
                '.mp3':  'audio/mpeg',
                '.flac': 'audio/flac',
            }
            mime = mime_map.get(ext)
            payload = result['bytes']
            # Cache for future replays (loops, repeated cues)
            if cache is not None:
                cache[attachment_id] = {'bytes': payload, 'mime': mime}
            self.audio._play_via_pygame(
                payload, mime_type=mime, interrupt=False,
                layer=layer, loop=loop, volume=volume,
                pan=pan, pan_to=pan_to, pan_duration_ms=pan_duration_ms,
            )
            wx.CallAfter(self._append_sound, _("[{layer}] {label}").format(
                layer=layer, label=label))
        threading.Thread(target=_fetch, daemon=True).start()

    def _handle_state_changed(self, message: Dict):
        if not self._is_for_session(message):
            return
        wx.CallAfter(self._refresh_session)

    def _handle_token_warning(self, message: Dict):
        if not self._is_for_session(message):
            return
        used = message.get('tokens_used', 0)
        cap = message.get('max_tokens', 0)
        text = _("Token budget warning: {used}/{cap}").format(used=used, cap=cap)
        wx.CallAfter(self._append_log, 'system', text)
        try:
            play_sound('core/error.ogg')
        except Exception:
            pass
        _speak_notification(text, 'warning', play_sound_effect=False)

    def _handle_game_menu(self, message: Dict):
        """The AI called present_menu — show the choices to this player.

        ``target_user_id`` filters menus that are private to a specific
        player (e.g. a split-the-party gamebook decision). The pick is
        sent back as a regular game_player_action so the AI sees it as
        the player's next message.
        """
        if not self._is_for_session(message):
            return
        target = message.get('target_user_id')
        if target:
            try:
                my_id = int(getattr(self.titan_client, 'user_id', 0) or 0)
                if int(target) != my_id:
                    return
            except Exception:
                return
        items = message.get('items') or []
        prompt_text = (message.get('prompt') or '').strip() or _("Choose:")
        wx.CallAfter(self._show_game_menu, prompt_text, items)

    def _show_game_menu(self, prompt_text: str, items: List[Dict]):
        labels = [str(it.get('label') or '?') for it in items if isinstance(it, dict)]
        if not labels:
            return
        try:
            play_sound('ui/dialog.ogg')
        except Exception:
            pass
        # Mirror the prompt + numbered options into the log so screen-reader
        # users can review the choices in the session history even after
        # they pick. Use natural-language numbering ("1.") so the log
        # reads cleanly aloud.
        try:
            self._append_log('system', prompt_text)
            for idx, label in enumerate(labels, start=1):
                self._append_log('system', f"{idx}. {label}")
        except Exception:
            pass

        dlg = wx.SingleChoiceDialog(self, prompt_text,
                                    _("Choose"), labels)
        try:
            if dlg.ShowModal() == wx.ID_OK:
                pick = dlg.GetStringSelection()
                if pick:
                    self._send_menu_choice(pick)
        finally:
            dlg.Destroy()

    def _send_menu_choice(self, label: str):
        """Submit the player's menu pick as a regular player action so the
        AI receives it as the next turn's text."""
        if not label:
            return

        def _run():
            try:
                self.titan_client.game_player_action(self.session_id, label)
            except Exception as e:
                print(f"[Game Session] menu choice send failed: {e}")
        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Session refresh + tab rendering
    # ------------------------------------------------------------------

    def _refresh_session(self):
        if self._closed:
            return

        def _fetch():
            result = self.titan_client.get_game_session(self.session_id)
            wx.CallAfter(self._apply_session, result)
        threading.Thread(target=_fetch, daemon=True).start()

    def _apply_session(self, result: Dict):
        if self._closed:
            return
        if not result.get('success'):
            _speak_notification(result.get('error') or _("Failed to load session"), 'error')
            return
        sess = result.get('session') or {}
        self.session = sess
        self.players_cache = sess.get('players') or []
        # Mic is always available — no per-turn gating. The AI infers
        # who's acting from the [username] prefix on each message.
        self._render_current_tab()
        self._update_status()

    def _update_status(self):
        sess = self.session or {}
        used = sess.get('tokens_used') or 0
        cap = sess.get('max_tokens') or 0
        status = sess.get('status') or 'lobby'
        active_count = sum(1 for p in self.players_cache if not p.get('left_at'))
        self.SetStatusText(_("Status: {status} | players: {n} | tokens: {used}/{cap}").format(
            status=status, n=active_count, used=used, cap=cap,
        ))

    def _tab_index(self, key: str) -> int:
        for i, (k, _f) in enumerate(SESSION_TABS):
            if k == key:
                return i
        return 0

    def _tab_bar_text(self) -> str:
        idx = self._tab_index(self.current_tab)
        label = SESSION_TABS[idx][1]()
        return _("{}, {} of {}").format(label, idx + 1, len(SESSION_TABS))

    def _is_tab_bar_row(self, idx: int) -> bool:
        if idx != 0 or self.listbox.GetCount() == 0:
            return False
        try:
            data = self.listbox.GetClientData(0)
        except Exception:
            return False
        return isinstance(data, dict) and data.get('type') == 'tab_bar'

    def _render_current_tab(self):
        self.listbox.Clear()
        self.listbox.Append(self._tab_bar_text(), {'type': 'tab_bar'})
        if self.current_tab == 'log':
            self._render_log_rows()
        elif self.current_tab == 'players':
            self._render_player_rows()
        elif self.current_tab == 'character':
            self._render_character_rows()
        elif self.current_tab == 'sounds':
            self._render_sound_rows()
        else:
            self.listbox.Append(_("(empty)"), {'type': 'placeholder'})
        self.listbox.SetSelection(0)
        self._last_focus_idx = 0

    def _render_log_rows(self):
        if not self.log_entries:
            self.listbox.Append(_("(no events yet)"), {'type': 'placeholder'})
            return
        for entry in self.log_entries[-MAX_LOG_ENTRIES:]:
            actor = entry.get('actor', '?')
            text = entry.get('text', '')
            label = _("[{actor}] {text}").format(actor=actor, text=text[:200])
            self.listbox.Append(label, {'type': 'log_entry', 'entry': entry})

    def _render_player_rows(self):
        if not self.players_cache:
            self.listbox.Append(_("(no players)"), {'type': 'placeholder'})
            return
        order = (self.session or {}).get('turn_order') or []
        active_idx = int((self.session or {}).get('current_turn_idx') or 0)
        active_id = order[active_idx] if (order and 0 <= active_idx < len(order)) else None
        for p in self.players_cache:
            uid = p.get('user_id')
            mark = '* ' if uid == active_id else '  '
            left = p.get('left_at')
            label = _("{mark}{user} (id {n}){left}").format(
                mark=mark, user=p.get('username', '?'), n=p.get('titan_number', '?'),
                left=_(" [left]") if left else '',
            )
            self.listbox.Append(label, {'type': 'player', 'player': p})

    def _render_character_rows(self):
        sess = self.session or {}
        my_id = getattr(self.titan_client, 'user_id', None)
        my_state = {}
        for p in self.players_cache:
            if p.get('user_id') == my_id:
                my_state = p.get('character_state') or {}
                break
        if not my_state:
            self.listbox.Append(_("(no character data yet — the AI will populate this)"),
                                {'type': 'placeholder'})
            return
        # Flatten 1 level of dict -> "key: value" rows.
        for k, v in my_state.items():
            if isinstance(v, (dict, list)):
                value_str = json.dumps(v, ensure_ascii=False)
            else:
                value_str = str(v)
            label = _("{key}: {value}").format(key=k, value=value_str[:160])
            self.listbox.Append(label, {'type': 'character_field', 'key': k, 'value': v})

    def _render_sound_rows(self):
        if not self.sounds_cache:
            self.listbox.Append(_("(no sound events yet)"), {'type': 'placeholder'})
            return
        for s in self.sounds_cache[-MAX_LOG_ENTRIES:]:
            label = _("Played: {label} at {ts}").format(label=s.get('label', '?'),
                                                        ts=s.get('ts', ''))
            self.listbox.Append(label, {'type': 'sound', 'sound': s})

    def _append_log(self, actor: str, text: str):
        self.log_entries.append({'actor': actor, 'text': text, 'ts': time.strftime('%H:%M:%S')})
        if len(self.log_entries) > MAX_LOG_ENTRIES * 2:
            self.log_entries = self.log_entries[-MAX_LOG_ENTRIES:]
        if self.current_tab == 'log':
            self._render_current_tab()

    def _append_sound(self, label: str):
        self.sounds_cache.append({'label': label, 'ts': time.strftime('%H:%M:%S')})
        if len(self.sounds_cache) > MAX_LOG_ENTRIES * 2:
            self.sounds_cache = self.sounds_cache[-MAX_LOG_ENTRIES:]
        if self.current_tab == 'sounds':
            self._render_current_tab()

    # ------------------------------------------------------------------
    # Keyboard / focus
    # ------------------------------------------------------------------

    def _emit_focus_feedback(self, idx: int):
        item_count = self.listbox.GetCount()
        if self._is_tab_bar_row(idx):
            _announce_tab_bar()
            self._last_focus_idx = idx
            return
        pan = 0.0
        real = max(0, item_count - 1)
        if real > 1:
            pan = (idx - 1) / (real - 1)
        try:
            play_focus_sound(pan=pan)
        except Exception:
            pass
        self._last_focus_idx = idx

    def _on_select(self, event):
        idx = self.listbox.GetSelection()
        if idx < 0:
            return
        self._emit_focus_feedback(idx)

    def _cycle_tab(self, direction: int):
        idx = self._tab_index(self.current_tab)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(SESSION_TABS):
            try:
                play_sound('ui/endoftapbar.ogg')
            except Exception:
                pass
            return
        self.current_tab = SESSION_TABS[new_idx][0]
        try:
            play_sound('ui/switch_list.ogg')
        except Exception:
            pass
        self._render_current_tab()

    def _on_key_hook(self, event: wx.KeyEvent):
        keycode = event.GetKeyCode()
        modifiers = event.GetModifiers()
        focus = self.FindFocus()

        if keycode == wx.WXK_ESCAPE and modifiers == wx.MOD_NONE:
            self.Close()
            return
        if keycode == wx.WXK_TAB and modifiers == wx.MOD_CONTROL:
            self._cycle_tab(+1)
            return
        if keycode == wx.WXK_TAB and modifiers == (wx.MOD_CONTROL | wx.MOD_SHIFT):
            self._cycle_tab(-1)
            return

        if focus is self.listbox:
            idx = self.listbox.GetSelection()
            item_count = self.listbox.GetCount()
            if keycode in (wx.WXK_LEFT, wx.WXK_RIGHT) and self._is_tab_bar_row(idx):
                self._cycle_tab(-1 if keycode == wx.WXK_LEFT else +1)
                return
            if keycode in (wx.WXK_LEFT, wx.WXK_RIGHT):
                return
            if keycode in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and not event.AltDown():
                self._on_activate(event)
                return
            new_idx = idx
            if keycode == wx.WXK_UP:
                new_idx = idx - 1
            elif keycode == wx.WXK_DOWN:
                new_idx = idx + 1
            elif keycode == wx.WXK_HOME:
                new_idx = 0
            elif keycode == wx.WXK_END:
                new_idx = item_count - 1
            else:
                event.Skip()
                return
            if 0 <= new_idx < item_count and new_idx != idx:
                self.listbox.SetSelection(new_idx)
                self._emit_focus_feedback(new_idx)
            else:
                try:
                    play_endoflist_sound()
                except Exception:
                    pass
            return
        event.Skip()

    def _on_activate(self, event):
        idx = self.listbox.GetSelection()
        if idx <= 0:
            return
        try:
            data = self.listbox.GetClientData(idx)
        except Exception:
            return
        if not isinstance(data, dict):
            return
        if data.get('type') == 'log_entry':
            entry = data.get('entry') or {}
            _speak(entry.get('text', ''))
        elif data.get('type') == 'character_field':
            v = data.get('value')
            text = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
            _speak(_("{key}: {value}").format(key=data.get('key', '?'), value=text))

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _on_send_action(self, event):
        text = self.input_ctrl.GetValue().strip()
        if not text:
            _speak_notification(_("Type something first"), 'error')
            return
        self.input_ctrl.SetValue('')
        try:
            play_sound('core/SELECT.ogg')
        except Exception:
            pass

        def _send():
            result = self.titan_client.game_player_action(self.session_id, text)
            wx.CallAfter(self._on_action_result, result, text)
        threading.Thread(target=_send, daemon=True).start()

    def _on_action_result(self, result: Dict, text: str):
        if not result.get('success'):
            _speak_notification(result.get('error') or _("Action rejected"), 'error')
            return
        # Server echoes the action back via game_player_action broadcast,
        # so we don't append locally to avoid duplicates.

    def _on_toggle_mic(self, event):
        active = self.talk_btn.GetValue()
        self._mic_active = active
        self.mic.set_active(active)
        self.talk_btn.SetLabel(_("Talk (mic ON)") if active else _("Talk (mic OFF)"))
        try:
            play_sound('core/SELECT.ogg' if active else 'ui/popupclose.ogg')
        except Exception:
            pass

    def _on_mic_chunk(self, payload: bytes):
        # Called from the mic capture thread; do NOT touch wx here.
        # Mic is open as long as the player toggled Talk on — the AI
        # decides who's acting via the [username] prefix in player
        # messages (no manual turn gating anymore).
        if self._closed or not self._mic_active:
            return
        try:
            self.titan_client.game_voice_chunk(self.session_id, payload)
        except Exception as e:
            print(f"[Game Session] voice chunk send failed: {e}")

    def _on_leave(self, event):
        confirm = _show_skinned_message(_("Leave this session?"), _("Leave"),
                        wx.YES_NO | wx.ICON_QUESTION, self)
        if confirm != wx.YES:
            return

        def _send():
            self.titan_client.leave_game_session(self.session_id)
            wx.CallAfter(self.Close)
        threading.Thread(target=_send, daemon=True).start()

    def _on_end(self, event):
        if not self.is_host:
            return
        confirm = _show_skinned_message(_("End the session for everyone?"),
                        _("End Session"),
                        wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
                        self)
        if confirm != wx.YES:
            return

        def _send():
            self.titan_client.game_end_session(self.session_id)
        threading.Thread(target=_send, daemon=True).start()

    def _on_close(self, event):
        if self._closed:
            event.Skip()
            return
        self._closed = True
        try:
            self.mic.stop()
        except Exception:
            pass
        try:
            self.audio.shutdown()
        except Exception:
            pass
        # Best-effort: leave the session so other players see us drop.
        try:
            threading.Thread(
                target=lambda: self.titan_client.leave_game_session(self.session_id),
                daemon=True,
            ).start()
        except Exception:
            pass
        self._restore_callbacks()
        event.Skip()


# ---------------------------------------------------------------------------
# Convenience launcher
# ---------------------------------------------------------------------------

def open_game_session(parent, titan_client, session_id: int,
                      game_id: int, is_host: bool = False) -> Optional[GameSessionFrame]:
    """Open a session window. Returns the frame for caller bookkeeping."""
    if not titan_client or not getattr(titan_client, 'is_connected', False):
        _speak_notification(_("You must be connected to Titan-Net"), 'error')
        return None
    frame = GameSessionFrame(parent, titan_client,
                             session_id=session_id, game_id=game_id, is_host=is_host)
    frame.Show()
    try:
        from src.ui.window_switcher import register_window
        register_window(_("Titan-Net: Game Session #{sid}").format(sid=session_id),
                        window=frame, category='messenger')
    except Exception:
        pass
    return frame
