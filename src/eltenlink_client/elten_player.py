"""
EltenPlayer - Audio player control for EltenLink client.
Port of Ruby Player class from elten/src/eapi/Controls.rb.

Uses pygame.mixer.music for broad format support (OGG, Opus, MP3, WAV).

Keyboard controls (matching Ruby Player):
  Space       - Play/Pause toggle
  Left/Right  - Seek backward/forward 5 seconds
  Up/Down     - Volume up/down
  Ctrl+Up/Down    - Tempo up/down (announced only)
  Shift+Left/Right - Pan left/right (announced only)
  Shift+Up/Down   - Pitch up/down (announced only)
  Backspace   - Reset all to defaults
  Home        - Jump to start
  End         - Jump to end
  P           - Announce current position
  D           - Announce duration
  S           - Save file dialog
"""

import wx
import os
import subprocess
import threading
import tempfile
import time
import requests
from concurrent.futures import ThreadPoolExecutor

from src.titan_core.translation import set_language
from src.settings.settings import get_setting


def _get_root():
    """Get project root directory (works in both dev and compiled)."""
    import sys
    if hasattr(sys, '_MEIPASS') or getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _find_ffmpeg():
    """Find ffmpeg executable in data/bin/ relative to project root."""
    try:
        candidate = os.path.join(_get_root(), 'data', 'bin', 'ffmpeg.exe')
        if os.path.exists(candidate):
            return candidate
    except Exception:
        pass
    return 'ffmpeg'


def _find_ffprobe():
    """Find ffprobe executable in data/bin/ relative to project root."""
    try:
        candidate = os.path.join(_get_root(), 'data', 'bin', 'ffprobe.exe')
        if os.path.exists(candidate):
            return candidate
    except Exception:
        pass
    return 'ffprobe'


_FFMPEG = _find_ffmpeg()
_FFPROBE = _find_ffprobe()

# Shared download pool and HTTP session for fast parallel downloads
_download_pool = ThreadPoolExecutor(max_workers=50)
_http_session = requests.Session()
_http_session.headers.update({'Connection': 'keep-alive'})
adapter = requests.adapters.HTTPAdapter(pool_connections=50, pool_maxsize=50)
_http_session.mount('https://', adapter)
_http_session.mount('http://', adapter)

_ = set_language(get_setting('language', 'pl'))

# Screen reader output
try:
    import accessible_output3.outputs.auto
    _speaker = accessible_output3.outputs.auto.Auto()
except Exception:
    _speaker = None

try:
    from src.titan_core.stereo_speech import speak_stereo, get_stereo_speech
    _STEREO_AVAILABLE = True
except ImportError:
    _STEREO_AVAILABLE = False


def _speak(text):
    """Speak text via screen reader."""
    if not text:
        return
    try:
        stereo_on = get_setting('stereo_speech', 'False', section='invisible_interface').lower() == 'true'
        if stereo_on and _STEREO_AVAILABLE:
            speak_stereo(text, position=0.0, pitch_offset=0, async_mode=True)
        elif _speaker:
            _speaker.output(text)
    except Exception:
        if _speaker:
            try:
                _speaker.output(text)
            except Exception:
                pass


def _format_time(seconds):
    """Format seconds to HH:MM:SS."""
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# Global lock for pygame.mixer.music (it's a singleton)
_music_lock = threading.Lock()
_active_player = None


class EltenPlayer(wx.Panel):
    """Accessible audio player control.

    Can play local files or URLs. Uses pygame.mixer.music for broad
    format support including Opus, OGG Vorbis, MP3, WAV.
    Supports keyboard controls matching the Ruby Elten Player class.
    """

    def __init__(self, parent, file_or_url="", label="", autoplay=True, id=wx.ID_ANY):
        super().__init__(parent, id, style=wx.TAB_TRAVERSAL | wx.WANTS_CHARS)

        self.label = label
        self._file_or_url = file_or_url
        self._local_file = None
        self._autoplay = autoplay
        self._paused = True
        self._loaded = False
        self._loading = False
        self._closed = False
        self._duration = 0
        self._play_start_time = 0
        self._play_offset = 0  # Track seek position
        self._original_file = None  # Source file for effects re-processing
        self._effects_timer = None  # Debounce timer for effect changes

        # Audio properties (matching Ruby Player defaults)
        self._volume = 0.8
        self._pan = 0.0
        self._tempo = 0  # percent change (-50 to +100)
        self._pitch_factor = 1.0  # frequency multiplier

        # Build minimal UI - just a label for screen readers
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        display_label = label if label else _("Audio player")
        self._label_ctrl = wx.StaticText(self, label=display_label)
        sizer.Add(self._label_ctrl, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 2)

        self._status_text = wx.StaticText(self, label="")
        sizer.Add(self._status_text, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 2)

        self.SetSizer(sizer)

        # Bind keyboard events - use CHAR_HOOK to capture modifier+arrow
        # before parent ScrolledPanel consumes them
        self.Bind(wx.EVT_CHAR_HOOK, self.OnKeyDown)
        self.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self._label_ctrl.Bind(wx.EVT_CHAR_HOOK, self.OnKeyDown)
        self._status_text.Bind(wx.EVT_CHAR_HOOK, self.OnKeyDown)

        # Start loading/playing
        if file_or_url:
            self._start_load(file_or_url)

    def _start_load(self, file_or_url):
        """Submit all preparation work to pool thread - UI stays responsive."""
        if self._loading:
            return
        self._loading = True
        if file_or_url.startswith("http://") or file_or_url.startswith("https://"):
            self._status_text.SetLabel(_("Downloading..."))
        _download_pool.submit(self._prepare_file, file_or_url)

    def _prepare_file(self, file_or_url):
        """Pool thread: download (if URL) + convert + get duration. Never blocks UI."""
        try:
            filepath = file_or_url
            if file_or_url.startswith("http://") or file_or_url.startswith("https://"):
                resp = _http_session.get(file_or_url, timeout=30)
                if resp.status_code != 200:
                    wx.CallAfter(self._on_load_error, _("Failed to download audio"))
                    return
                content_type = resp.headers.get('Content-Type', '').lower()
                if 'opus' in content_type:
                    ext = '.opus'
                elif 'ogg' in content_type:
                    ext = '.ogg'
                elif 'mp3' in content_type or 'mpeg' in content_type:
                    ext = '.mp3'
                elif 'wav' in content_type:
                    ext = '.wav'
                elif '.mp3' in file_or_url.lower():
                    ext = '.mp3'
                elif '.wav' in file_or_url.lower():
                    ext = '.wav'
                elif '.opus' in file_or_url.lower():
                    ext = '.opus'
                elif resp.content[:4] == b'OggS' and b'OpusHead' in resp.content[:100]:
                    ext = '.opus'
                elif resp.content[:4] == b'OggS':
                    ext = '.ogg'
                else:
                    ext = '.ogg'
                tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                tmp.write(resp.content)
                tmp.close()
                filepath = tmp.name

            # Convert if needed
            ext = os.path.splitext(filepath)[1].lower()
            if ext in ('.opus',) or ext not in ('.ogg', '.mp3', '.wav'):
                wav_path = self._convert_to_wav(filepath)
                if wav_path:
                    filepath = wav_path

            # Get duration (ffprobe/pydub) - heavy, must be in pool
            duration = self._get_duration(filepath)

            self._local_file = filepath
            wx.CallAfter(self._load_pygame, filepath, duration)
        except Exception as e:
            wx.CallAfter(self._on_load_error, str(e))

    def _convert_to_wav(self, filepath):
        """Convert audio file to WAV using ffmpeg (for Opus and other unsupported formats)."""
        wav_path = filepath + '.wav'
        try:
            result = subprocess.run(
                [_FFMPEG, '-y', '-i', filepath, '-acodec', 'pcm_s16le', '-ar', '22050', '-ac', '2', wav_path],
                capture_output=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            if result.returncode == 0 and os.path.exists(wav_path):
                print(f"[EltenPlayer] Converted to WAV: {wav_path}")
                return wav_path
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[EltenPlayer] ffmpeg conversion failed: {e}")

        # Try pydub as fallback
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(filepath)
            audio = audio.set_frame_rate(22050).set_channels(2)
            audio.export(wav_path, format='wav')
            if os.path.exists(wav_path):
                print(f"[EltenPlayer] Converted to WAV via pydub: {wav_path}")
                return wav_path
        except Exception as e:
            print(f"[EltenPlayer] pydub conversion failed: {e}")

        return None

    def _load_pygame(self, filepath, duration):
        """UI thread: just mark file as ready. pygame.mixer.music.load() happens in play()."""
        self._duration = duration
        self._local_file = filepath
        self._original_file = filepath
        self._loaded = True
        self._loading = False
        self._status_text.SetLabel(_format_time(self._duration))
        if self._autoplay:
            self.play()

    def _get_duration(self, filepath):
        """Get audio duration using ffprobe, pydub, or pygame Sound fallback."""
        # Try ffprobe (fast, accurate)
        try:
            result = subprocess.run(
                [_FFPROBE, '-v', 'quiet', '-print_format', 'json', '-show_format', filepath],
                capture_output=True, timeout=10, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            if result.returncode == 0:
                import json
                info = json.loads(result.stdout)
                dur = float(info.get('format', {}).get('duration', 0))
                if dur > 0:
                    return dur
        except Exception:
            pass

        # Try pydub
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(filepath)
            return len(audio) / 1000.0
        except Exception:
            pass

        # Try pygame Sound (only works for WAV/OGG Vorbis)
        try:
            import pygame
            snd = pygame.mixer.Sound(filepath)
            dur = snd.get_length()
            del snd
            return dur
        except Exception:
            pass

        return 0

    def _on_load_error(self, message):
        """Handle load error."""
        self._loading = False
        self._loaded = False
        self._status_text.SetLabel(_("Error"))
        print(f"[EltenPlayer] Load error: {message}")
        _speak(_("Failed to play audio") + ": " + message)

    # ---- Playback Controls ----

    def play(self):
        """Start or resume playback."""
        global _active_player
        if not self._loaded:
            return
        import pygame
        with _music_lock:
            if self._paused and _active_player is self and pygame.mixer.music.get_pos() != -1:
                pygame.mixer.music.unpause()
            else:
                # Stop previous player and update its state
                if _active_player is not None and _active_player is not self:
                    try:
                        _active_player._paused = True
                        _active_player._status_text.SetLabel(_("Paused"))
                    except Exception:
                        pass
                # Always load file (not loaded in _load_pygame since it's lazy)
                pygame.mixer.music.load(self._local_file)
                pygame.mixer.music.set_volume(self._volume)
                pygame.mixer.music.play(start=self._play_offset)
                self._play_start_time = time.time() - self._play_offset
                _active_player = self
        self._paused = False
        self._status_text.SetLabel(_("Playing"))

    def pause(self):
        """Pause playback."""
        import pygame
        with _music_lock:
            if _active_player is self:
                pygame.mixer.music.pause()
                # Track current position
                pos_ms = pygame.mixer.music.get_pos()
                if pos_ms > 0:
                    self._play_offset = self._play_offset + pos_ms / 1000.0
        self._paused = True
        self._status_text.SetLabel(_("Paused"))

    def toggle_pause(self):
        """Toggle play/pause."""
        if self._paused:
            self.play()
            _speak(_("Playing"))
        else:
            self.pause()
            _speak(_("Paused"))

    def stop(self):
        """Stop playback completely."""
        global _active_player
        import pygame
        with _music_lock:
            if _active_player is self:
                pygame.mixer.music.stop()
        self._paused = True
        self._play_offset = 0
        self._status_text.SetLabel(_("Stopped"))

    def close(self):
        """Close and release resources."""
        global _active_player
        self.stop()
        self._closed = True
        with _music_lock:
            if _active_player is self:
                _active_player = None
        # Clean up temp file
        if self._local_file and self._local_file.startswith(tempfile.gettempdir()):
            try:
                os.unlink(self._local_file)
            except Exception:
                pass

    def _get_position(self):
        """Get current playback position in seconds."""
        import pygame
        if _active_player is not self:
            return self._play_offset
        pos_ms = pygame.mixer.music.get_pos()
        if pos_ms == -1:
            return self._play_offset
        return self._play_offset + pos_ms / 1000.0

    @property
    def is_playing(self):
        import pygame
        return _active_player is self and pygame.mixer.music.get_busy() and not self._paused

    @property
    def is_paused(self):
        return self._paused

    @property
    def is_loaded(self):
        return self._loaded

    @property
    def duration(self):
        return self._duration

    # ---- Volume Control ----

    def _apply_volume(self):
        """Apply current volume to music."""
        import pygame
        if _active_player is self:
            pygame.mixer.music.set_volume(min(1.0, self._volume))

    def volume_up(self):
        """Increase volume."""
        step = 0.01 if self._volume < 1.0 else 0.1
        self._volume = min(1.0, self._volume + step)
        self._apply_volume()
        pct = int(self._volume * 100)
        _speak(f"{pct}%")

    def volume_down(self):
        """Decrease volume."""
        step = 0.01 if self._volume <= 1.1 else 0.1
        self._volume = max(0.05, self._volume - step)
        self._apply_volume()
        pct = int(self._volume * 100)
        _speak(f"{pct}%")

    def pan_left(self):
        """Pan left."""
        self._pan = max(-1.0, self._pan - 0.1)
        if abs(self._pan) < 0.05:
            self._pan = 0.0
            _speak(_("Center"))
        else:
            _speak(f"{int(self._pan * 100)}")
        self._schedule_reprocess()

    def pan_right(self):
        """Pan right."""
        self._pan = min(1.0, self._pan + 0.1)
        if abs(self._pan) < 0.05:
            self._pan = 0.0
            _speak(_("Center"))
        else:
            _speak(f"{int(self._pan * 100)}")
        self._schedule_reprocess()

    def reset_defaults(self):
        """Reset volume, pan, tempo, pitch to defaults (Backspace)."""
        self._volume = 0.8
        self._pan = 0.0
        self._tempo = 0
        self._pitch_factor = 1.0
        self._apply_volume()
        if self._original_file and self._local_file != self._original_file:
            threading.Thread(target=self._apply_effects, daemon=True).start()
        _speak(_("Reset"))

    # ---- Effects (pan / tempo / pitch) ----

    def _schedule_reprocess(self):
        """Schedule audio reprocessing after a short delay (debounce)."""
        if self._effects_timer:
            try:
                self._effects_timer.Stop()
            except Exception:
                pass
        self._effects_timer = wx.CallLater(400, self._do_reprocess)

    def _do_reprocess(self):
        """Run audio reprocessing in background thread."""
        threading.Thread(target=self._apply_effects, daemon=True).start()

    @staticmethod
    def _append_atempo(filters, rate):
        """Append atempo filter(s), chaining when rate is outside 0.5-2.0 range."""
        while rate > 2.0:
            filters.append("atempo=2.0")
            rate /= 2.0
        while rate < 0.5:
            filters.append("atempo=0.5")
            rate /= 0.5
        filters.append(f"atempo={rate:.4f}")

    def _apply_effects(self):
        """Apply pan/tempo/pitch to audio using ffmpeg, then reload at current position."""
        if not self._original_file or not os.path.exists(self._original_file):
            return

        all_default = (
            abs(self._pan) < 0.01 and
            abs(self._tempo) < 1 and
            abs(self._pitch_factor - 1.0) < 0.005
        )
        if all_default and self._local_file == self._original_file:
            return

        pos = self._get_position()

        # Build ffmpeg filter chain
        filters = []

        if abs(self._pan) > 0.01:
            if self._pan > 0:
                left = max(0.0, 1.0 - self._pan)
                right = 1.0
            else:
                left = 1.0
                right = max(0.0, 1.0 + self._pan)
            filters.append("aformat=channel_layouts=stereo")
            filters.append(f"pan=stereo|c0={left:.3f}*c0|c1={right:.3f}*c1")

        # Pitch shift without tempo change: shift sample rate, compensate speed
        if abs(self._pitch_factor - 1.0) > 0.005:
            pf = self._pitch_factor
            filters.append(f"asetrate=22050*{pf:.4f}")
            filters.append("aresample=22050")
            comp = max(0.1, min(10.0, 1.0 / pf))
            self._append_atempo(filters, comp)

        # Tempo change (speed without pitch)
        if abs(self._tempo) > 1:
            rate = max(0.1, min(10.0, 1.0 + self._tempo / 100.0))
            self._append_atempo(filters, rate)

        if not filters:
            target = self._original_file
        else:
            af = ','.join(filters)
            out_file = self._original_file + '_fx.wav'
            try:
                result = subprocess.run(
                    [_FFMPEG, '-y', '-i', self._original_file, '-af', af,
                     '-acodec', 'pcm_s16le', '-ar', '22050', '-ac', '2', out_file],
                    capture_output=True, timeout=60,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                if result.returncode != 0:
                    print(f"[EltenPlayer] ffmpeg effects failed: {result.stderr.decode()}")
                    return
                target = out_file
            except FileNotFoundError:
                print("[EltenPlayer] ffmpeg not found - audio effects unavailable")
                return
            except Exception as e:
                print(f"[EltenPlayer] Effects error: {e}")
                return

        # Reload at current position
        try:
            import pygame
            with _music_lock:
                if _active_player is self:
                    was_playing = not self._paused
                    pygame.mixer.music.load(target)
                    pygame.mixer.music.set_volume(self._volume)
                    self._local_file = target
                    if was_playing:
                        self._play_offset = pos
                        try:
                            pygame.mixer.music.play(start=pos)
                        except Exception:
                            self._play_offset = 0
                            pygame.mixer.music.play()
                else:
                    self._local_file = target
        except Exception as e:
            print(f"[EltenPlayer] Reload after effects failed: {e}")

    # ---- Seek Control ----

    def seek_forward(self, seconds=5):
        """Seek forward by seconds."""
        if not self._loaded:
            return
        import pygame
        new_pos = self._get_position() + seconds
        if self._duration > 0:
            new_pos = min(new_pos, self._duration - 0.5)
        self._play_offset = max(0, new_pos)
        if _active_player is self and not self._paused:
            try:
                pygame.mixer.music.play(start=self._play_offset)
            except Exception:
                # Some formats don't support start offset - restart
                pygame.mixer.music.play()
        pos_str = _format_time(self._play_offset)
        _speak(pos_str)

    def seek_backward(self, seconds=5):
        """Seek backward by seconds."""
        if not self._loaded:
            return
        import pygame
        new_pos = self._get_position() - seconds
        self._play_offset = max(0, new_pos)
        if _active_player is self and not self._paused:
            try:
                pygame.mixer.music.play(start=self._play_offset)
            except Exception:
                pygame.mixer.music.play()
        pos_str = _format_time(self._play_offset)
        _speak(pos_str)

    def seek_to_start(self):
        """Jump to start."""
        if not self._loaded:
            return
        import pygame
        self._play_offset = 0
        if _active_player is self and not self._paused:
            pygame.mixer.music.play()
        _speak(_("Start"))

    def seek_to_end(self):
        """Jump near end."""
        if not self._loaded or self._duration <= 0:
            return
        import pygame
        self._play_offset = max(0, self._duration - 1)
        if _active_player is self and not self._paused:
            try:
                pygame.mixer.music.play(start=self._play_offset)
            except Exception:
                pass
        _speak(_("End"))

    # ---- Info ----

    def announce_position(self):
        """Announce current playback position (P key)."""
        pos = self._get_position()
        _speak(_format_time(pos))

    def announce_duration(self):
        """Announce total duration (D key)."""
        _speak(_format_time(self._duration))

    # ---- Save ----

    def save_file(self):
        """Save audio file to disk (S key)."""
        if not self._local_file:
            _speak(_("No file to save"))
            return

        with wx.FileDialog(
            self.GetTopLevelParent(),
            _("Save audio file"),
            defaultFile=self.label + ".ogg" if self.label else "audio.ogg",
            wildcard=_("Audio files") + " (*.ogg;*.mp3;*.wav)|*.ogg;*.mp3;*.wav",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                path = dlg.GetPath()
                try:
                    import shutil
                    shutil.copy2(self._local_file, path)
                    _speak(_("Saved"))
                except Exception as e:
                    _speak(_("Error") + ": " + str(e))

    # ---- Keyboard Handling ----

    def OnKeyDown(self, event):
        """Handle keyboard input matching Ruby Player controls."""
        key = event.GetKeyCode()
        ctrl = event.ControlDown()
        shift = event.ShiftDown()

        # Tab/Shift+Tab: navigate to next/previous control (like Ruby)
        if key == wx.WXK_TAB:
            flags = wx.NavigationKeyEvent.FromTab
            if shift:
                flags |= wx.NavigationKeyEvent.IsBackward
            else:
                flags |= wx.NavigationKeyEvent.IsForward
            self.Navigate(flags)
            return

        if key == wx.WXK_SPACE:
            self.toggle_pause()
            return

        if key == wx.WXK_BACK:
            self.reset_defaults()
            return

        if key == wx.WXK_HOME:
            self.seek_to_start()
            return

        if key == wx.WXK_END:
            self.seek_to_end()
            return

        # No modifiers - plain arrows
        if not ctrl and not shift:
            if key == wx.WXK_RIGHT:
                self.seek_forward(5)
                return
            elif key == wx.WXK_LEFT:
                self.seek_backward(5)
                return
            elif key == wx.WXK_UP:
                self.volume_up()
                return
            elif key == wx.WXK_DOWN:
                self.volume_down()
                return

        # Ctrl + arrows: tempo
        if ctrl and not shift:
            if key == wx.WXK_UP:
                self._tempo = min(100, self._tempo + 2)
                if self._tempo == 0:
                    _speak(_("Normal"))
                else:
                    _speak(f"{self._tempo:+d}%")
                self._schedule_reprocess()
                return
            elif key == wx.WXK_DOWN:
                self._tempo = max(-50, self._tempo - 2)
                if self._tempo == 0:
                    _speak(_("Normal"))
                else:
                    _speak(f"{self._tempo:+d}%")
                self._schedule_reprocess()
                return

        # Shift + arrows: pan (left/right) or pitch (up/down)
        if shift and not ctrl:
            if key == wx.WXK_LEFT:
                self.pan_left()
                return
            elif key == wx.WXK_RIGHT:
                self.pan_right()
                return
            elif key == wx.WXK_UP:
                self._pitch_factor = min(2.0, self._pitch_factor + 0.004)
                if abs(self._pitch_factor - 1.0) < 0.005:
                    _speak(_("Normal"))
                else:
                    _speak(f"{int(self._pitch_factor * 100)}%")
                self._schedule_reprocess()
                return
            elif key == wx.WXK_DOWN:
                self._pitch_factor = max(0.5, self._pitch_factor - 0.004)
                if abs(self._pitch_factor - 1.0) < 0.005:
                    _speak(_("Normal"))
                else:
                    _speak(f"{int(self._pitch_factor * 100)}%")
                self._schedule_reprocess()
                return

        # P - position
        if key == ord('P') and not ctrl and not shift:
            self.announce_position()
            return

        # D - duration
        if key == ord('D') and not ctrl and not shift:
            self.announce_duration()
            return

        # S - save
        if key == ord('S') and not ctrl and not shift:
            self.save_file()
            return

        event.Skip()

    def OnFocus(self, event):
        """Announce label and auto-play when focused."""
        if self.label:
            _speak(self.label)
        elif self._loaded:
            _speak(_("Audio player"))
        if self._loaded and self._paused:
            self.play()
        elif not self._loaded:
            self._autoplay = True
        event.Skip()

    def __del__(self):
        """Cleanup on destruction."""
        try:
            self.close()
        except Exception:
            pass
