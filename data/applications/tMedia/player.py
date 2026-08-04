#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PlayerPanel: the "now playing" view embedded in TMediaApp's content area.

Not a standalone Frame -- TMedia used to open this as a second top-level
window on top of the picker window, which is exactly the "2 windows" UX the
media catalog/search views were merged out of. See tmedia.py's view-stack
(show_view/go_back) for how this panel is swapped in and torn down.

Doubles as Titan's shared media player: any Titan app/component can play a
file or stream through it via the standard app_manager convention --
open_application(find_application_by_shortname("media"), path_or_url) --
which lands here as sys.argv[1] (see tmedia.py __main__).

The panel plays a *playlist*, not a file: a single film or track is a
one-item list and an audiobook is the whole folder (playlist.py builds it),
which is what lets one book be one item that advances by itself and carries
one set of bookmarks. Positions are remembered by bookmarks.py -- the resume
point automatically, named bookmarks on Ctrl+B -- so a long film or a book
continues where it was left instead of restarting.
"""

import os
import sys
import ctypes
import platform


def load_local_vlc():
    current_dir = os.path.dirname(os.path.abspath(__file__))

    if os.name == 'nt':
        libvlc_path = os.path.join(current_dir, 'libvlc.dll')
        libvlccore_path = os.path.join(current_dir, 'libvlccore.dll')

        if os.path.exists(libvlc_path) and os.path.exists(libvlccore_path):
            os.environ["PATH"] = current_dir + ";" + os.environ["PATH"]
            try:
                ctypes.cdll.LoadLibrary(libvlccore_path)
                ctypes.cdll.LoadLibrary(libvlc_path)
            except OSError:
                pass

    elif sys.platform == 'darwin':
        libvlc_dylib = os.path.join(current_dir, 'libvlc.dylib')
        if os.path.exists(libvlc_dylib):
            try:
                ctypes.cdll.LoadLibrary(libvlc_dylib)
            except OSError:
                pass


load_local_vlc()

try:
    import wx
    import vlc
    import threading
except ImportError:
    sys.exit(1)

from urllib.parse import unquote

from translation import _
import bookmarks
from bookmarks_gui import BookmarksDialog, position_label
import common

# How often the resume point is written while something plays. Often enough
# that a crash or a closed window loses seconds, rarely enough that the JSON
# file is not rewritten on every timer tick.
RESUME_SAVE_INTERVAL_MS = 5000


class PlayerPanel(wx.Panel):
    """Embedded playback view. `owner` is the TMediaApp frame (for go_back()
    and window-title updates); accessibility/sound go through common.py
    directly, same as the other panels.

    Volume and playback position are wx.Slider controls rather than
    increase/decrease buttons: a slider's native role already reports its
    value to a screen reader as it changes, and dragging/arrow-keying one is
    the standard accessible control for a continuous range in this codebase
    (see the volume/rate/pitch sliders in src/ui/settingsgui.py).
    """

    def __init__(self, parent, owner, *args, **kwargs):
        super(PlayerPanel, self).__init__(parent, *args, **kwargs)
        self.owner = owner

        self.instance = vlc.Instance()
        self.player = self.instance.media_player_new()

        self.is_playing = False
        self.target_volume = 100
        self._seeking = False

        # Playlist / bookmark state.
        self.store = bookmarks.get_store()
        self.tracks = []                 # [{'url', 'title'}]
        self.track_index = 0
        self.media_id = None             # what bookmarks are filed under
        self.media_title = ''
        self.media_kind = 'file'         # 'file' or 'audiobook'
        self._explicit_title = False
        self._pending_seek_ms = 0
        self._resume_save_due = 0
        self._advancing = False

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.status = wx.StaticText(self, label=_("Paused"))
        vbox.Add(self.status, flag=wx.ALL, border=10)

        self.track_status = wx.StaticText(self, label="")
        vbox.Add(self.track_status, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        controls = wx.BoxSizer(wx.HORIZONTAL)
        self.previous_button = wx.Button(self, label=_("Previous track"))
        controls.Add(self.previous_button, flag=wx.RIGHT, border=5)
        self.play_pause_button = wx.Button(self, label=_("Pause"))
        controls.Add(self.play_pause_button, flag=wx.RIGHT, border=5)
        self.next_button = wx.Button(self, label=_("Next track"))
        controls.Add(self.next_button, flag=wx.RIGHT, border=5)
        self.add_bookmark_button = wx.Button(self, label=_("Add bookmark"))
        controls.Add(self.add_bookmark_button, flag=wx.RIGHT, border=5)
        self.bookmarks_button = wx.Button(self, label=_("Bookmarks..."))
        controls.Add(self.bookmarks_button)
        vbox.Add(controls, flag=wx.ALL, border=5)

        position_label_text = _("Playback position")
        position_label_ctrl = wx.StaticText(self, label=position_label_text)
        vbox.Add(position_label_ctrl, flag=wx.LEFT | wx.TOP, border=10)
        self.position_slider = wx.Slider(self, value=0, minValue=0, maxValue=1000,
                                          style=wx.SL_HORIZONTAL)
        self.position_slider.SetLabel(position_label_text)
        vbox.Add(self.position_slider, flag=wx.LEFT | wx.RIGHT | wx.EXPAND, border=10)

        volume_label_text = _("Volume")
        volume_label = wx.StaticText(self, label=volume_label_text)
        vbox.Add(volume_label, flag=wx.LEFT | wx.TOP, border=10)
        self.volume_slider = wx.Slider(self, value=self.target_volume, minValue=0, maxValue=100,
                                        style=wx.SL_HORIZONTAL)
        self.volume_slider.SetLabel(volume_label_text)
        vbox.Add(self.volume_slider, flag=wx.LEFT | wx.RIGHT | wx.EXPAND, border=10)

        self.SetSizer(vbox)
        common.apply_skin(self)

        self.play_pause_button.Bind(wx.EVT_BUTTON, self.on_toggle_play)
        self.previous_button.Bind(wx.EVT_BUTTON, lambda e: self.previous_track())
        self.next_button.Bind(wx.EVT_BUTTON, lambda e: self.next_track())
        self.add_bookmark_button.Bind(wx.EVT_BUTTON, lambda e: self.add_bookmark())
        self.bookmarks_button.Bind(wx.EVT_BUTTON, lambda e: self.show_bookmarks())
        self.position_slider.Bind(wx.EVT_SCROLL_THUMBTRACK, self.on_position_thumbtrack)
        self.position_slider.Bind(wx.EVT_SCROLL_THUMBRELEASE, self.on_position_release)
        self.position_slider.Bind(wx.EVT_SLIDER, self.on_position_seek)
        self.volume_slider.Bind(wx.EVT_SLIDER, self.on_volume_slider)

        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)

        self._show_track_controls(False)

        self.position_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_position_timer, self.position_timer)
        self.position_timer.Start(500)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

    def focus_default(self):
        self.play_pause_button.SetFocus()

    def _on_destroy(self, event):
        if self.position_timer.IsRunning():
            self.position_timer.Stop()
        event.Skip()

    def fade_in_volume(self):
        current_volume = 0
        self.player.audio_set_volume(current_volume)
        while current_volume < self.target_volume:
            current_volume = min(self.target_volume, current_volume + 5)
            self.player.audio_set_volume(current_volume)
            wx.MilliSleep(50)

    # ------------------------------------------------------------------ #
    # Starting playback
    # ------------------------------------------------------------------ #
    def play_file(self, filepath: str, title: str = None, start_position=None):
        """Play a single file or stream (the shared-player entry point)."""
        self._explicit_title = title is not None
        display = title or (
            unquote(filepath).split('/')[-1]
            if not filepath.startswith("http") else _("Streaming")
        )
        self.play_playlist([{'url': filepath, 'title': display}],
                           title=display, media_id=filepath, kind='file',
                           start=(0, start_position) if start_position else None)

    def play_playlist(self, tracks, title=None, media_id=None, kind='audiobook',
                      start=None, resume=True):
        """Play ``tracks`` as one item. ``start`` is an explicit
        ``(track, position)`` (a bookmark the user picked); without it the
        saved resume point is used, which is what makes a long film or a book
        continue by itself."""
        self.tracks = [t for t in tracks if t.get('url')]
        if not self.tracks:
            self.status.SetLabel(_("Nothing to play"))
            common.speak(_("Nothing to play"))
            return

        self.media_kind = kind
        self.media_title = title or self.tracks[0].get('title') or ''
        self.media_id = media_id or self.tracks[0]['url']
        if kind == 'audiobook':
            self._explicit_title = True

        index, position = 0, 0
        resumed = False
        if start:
            index, position = int(start[0] or 0), int(start[1] or 0)
        elif resume:
            saved = self.store.get_resume(self.media_id)
            if saved:
                index = int(saved.get('track', 0) or 0)
                position = int(saved.get('position', 0) or 0)
                resumed = bool(position or index)

        self._show_track_controls(len(self.tracks) > 1)
        self._load_track(index, position)

        if resumed:
            where = position_label(self.media_kind, self.track_index,
                                   self._track_title(self.track_index),
                                   position, len(self.tracks))
            common.speak(_("Resuming from %s") % where)

    def _track_title(self, index):
        if 0 <= index < len(self.tracks):
            return self.tracks[index].get('title') or ''
        return ''

    def _load_track(self, index, position_ms=0, announce=True):
        if not self.tracks:
            return
        self.track_index = max(0, min(int(index), len(self.tracks) - 1))
        track = self.tracks[self.track_index]
        url = track['url']

        self.player.stop()
        media = self.instance.media_new(url)
        self.player.set_media(media)
        self.player.play()
        threading.Thread(target=self.fade_in_volume, daemon=True).start()

        self.is_playing = True
        self._advancing = False
        self._pending_seek_ms = max(0, int(position_ms or 0))
        self._resume_save_due = 0
        self.position_slider.SetValue(0)
        self._update_labels()
        self.play_pause_button.SetLabel(_("Pause"))

        if announce:
            common.speak(_("Playing: %s") % self._now_playing_text())

        if (self.media_kind == 'file' and url.startswith("http")
                and not self._explicit_title):
            threading.Thread(target=self.monitor_stream, args=(url,),
                             daemon=True).start()

    def _now_playing_text(self):
        """What is playing, said the way it reads best: a book announces the
        track it reached, a single file just its own name."""
        if self.media_kind == 'audiobook' and len(self.tracks) > 1:
            return _("%(book)s - track %(number)d of %(total)d: %(title)s") % {
                'book': self.media_title,
                'number': self.track_index + 1,
                'total': len(self.tracks),
                'title': self._track_title(self.track_index)}
        return self._track_title(self.track_index) or self.media_title

    def _update_labels(self):
        text = self._now_playing_text()
        self.owner.SetTitle(_("Playing: %s") % text)
        self.status.SetLabel(_("Playing: ") + text)
        if len(self.tracks) > 1:
            self.track_status.SetLabel(_("Track %(number)d of %(total)d: %(title)s") % {
                'number': self.track_index + 1,
                'total': len(self.tracks),
                'title': self._track_title(self.track_index)})
        else:
            self.track_status.SetLabel("")

    def _show_track_controls(self, show):
        self.previous_button.Show(show)
        self.next_button.Show(show)
        self.Layout()

    def monitor_stream(self, filepath: str):
        while not self.player.is_playing():
            wx.MilliSleep(50)

        media = self.player.get_media()
        media_title = media.get_meta(vlc.Meta.Title) if media else None
        if media_title:
            wx.CallAfter(self.owner.SetTitle, _("Playing: %s") % media_title)
            wx.CallAfter(self.status.SetLabel, _("Playing: ") + media_title)
            wx.CallAfter(common.speak, _("Playing: %s") % media_title)
        else:
            wx.CallAfter(common.speak, _("Stream loaded"))

    # ------------------------------------------------------------------ #
    # Transport
    # ------------------------------------------------------------------ #
    def on_toggle_play(self, event):
        if self.is_playing:
            self.player.pause()
            self.is_playing = False
            self.status.SetLabel(_("Paused"))
            self.play_pause_button.SetLabel(_("Play"))
            common.speak(_("Paused"))
            # Pausing is exactly when the user walks away: keep the place now.
            self.save_resume(force=True)
        else:
            self.player.play()
            self.is_playing = True
            self.status.SetLabel(_("Playing"))
            self.play_pause_button.SetLabel(_("Pause"))
            common.speak(_("Playing"))

    def seek(self, offset_ms):
        """Keyboard-shortcut seek (Left/Right). Announces via TTS since,
        unlike dragging the position slider, the slider itself isn't focused
        so no native accessible value announcement happens on its own."""
        current_time = self.player.get_time()
        new_time = max(0, current_time + offset_ms)
        self.player.set_time(new_time)
        self._sync_position_slider()
        if offset_ms < 0:
            common.speak(_("Rewind 10 seconds"))
        else:
            common.speak(_("Forward 10 seconds"))

    def next_track(self, announce=True):
        if self.track_index + 1 >= len(self.tracks):
            common.speak(_("Last track"))
            return False
        self.save_resume(force=True)
        self._load_track(self.track_index + 1, 0, announce=announce)
        return True

    def previous_track(self):
        if self.track_index <= 0:
            common.speak(_("First track"))
            return False
        self.save_resume(force=True)
        self._load_track(self.track_index - 1, 0)
        return True

    def restart(self):
        """Start the whole item from the beginning and drop its resume point."""
        if self.media_id:
            self.store.clear_resume(self.media_id)
        self._load_track(0, 0, announce=False)
        common.speak(_("Starting from the beginning"))

    def jump_to(self, track, position):
        """Go to a bookmark: a different track is loaded, the same one is
        just seeked."""
        track = max(0, min(int(track or 0), max(0, len(self.tracks) - 1)))
        position = max(0, int(position or 0))
        if track != self.track_index:
            self._load_track(track, position, announce=False)
        else:
            self.player.set_time(position)
            self._pending_seek_ms = 0 if self.player.is_playing() else position
            self._sync_position_slider()
        common.speak(_("Jumped to %s") % position_label(
            self.media_kind, track, self._track_title(track), position,
            len(self.tracks)))

    def change_volume(self, delta):
        """Keyboard-shortcut volume change (Up/Down); see seek() for why
        this announces while the slider's own handler does not."""
        volume = min(100, max(0, self.player.audio_get_volume() + delta))
        self.player.audio_set_volume(volume)
        self.target_volume = volume
        self.volume_slider.SetValue(volume)
        common.speak(_("Volume: %d percent") % volume)

    # ------------------------------------------------------------------ #
    # Bookmarks
    # ------------------------------------------------------------------ #
    def _current_place(self):
        return {'track': self.track_index,
                'position': max(0, self.player.get_time() or 0),
                'track_title': self._track_title(self.track_index)}

    def add_bookmark(self, ask_name=False):
        """Ctrl+B drops a bookmark straight away (an audiobook listener wants
        to keep listening); Ctrl+Shift+B asks for a name first."""
        if not self.media_id:
            return
        place = self._current_place()
        default = _("Bookmark %s") % common.format_time(place['position'])
        name = default
        if ask_name:
            dlg = wx.TextEntryDialog(self, _("Bookmark name"),
                                     _("Add bookmark"), default)
            if dlg.ShowModal() != wx.ID_OK:
                dlg.Destroy()
                return
            name = dlg.GetValue().strip() or default
            dlg.Destroy()
        self.store.add_bookmark(self.media_id, name, place['position'],
                                track=place['track'],
                                track_title=place['track_title'],
                                title=self.media_title, kind=self.media_kind,
                                tracks=self.tracks)
        common.play_sound('done')
        message = _("Bookmark added at %s") % position_label(
            self.media_kind, place['track'], place['track_title'],
            place['position'], len(self.tracks))
        self.status.SetLabel(message)
        common.speak(message)

    def show_bookmarks(self):
        if not self.media_id:
            return
        dlg = BookmarksDialog(self, self.store, self.media_id,
                              kind=self.media_kind, title=self.media_title,
                              current=self._current_place(), tracks=self.tracks)
        result = dlg.ShowModal()
        chosen = dlg.result
        dlg.Destroy()
        if result == wx.ID_OK and chosen:
            self.jump_to(chosen[0], chosen[1])
        else:
            self.play_pause_button.SetFocus()

    def save_resume(self, force=False):
        """Write where playback got to. Streams and short files are skipped,
        and an item played to its end is forgotten so it starts over."""
        if not self.media_id or not self.tracks:
            return
        position = self.player.get_time()
        length = self.player.get_length()
        if position is None or position < 0:
            return
        last_track = self.track_index >= len(self.tracks) - 1
        if (bookmarks.should_keep_resume(position, length, self.media_kind)
                or (self.media_kind == 'audiobook' and self.track_index > 0
                    and not (last_track and length
                             and position > length - bookmarks.RESUME_END_MARGIN_MS))):
            self.store.set_resume(self.media_id, position,
                                  track=self.track_index,
                                  track_title=self._track_title(self.track_index),
                                  length=length or 0, title=self.media_title,
                                  kind=self.media_kind, tracks=self.tracks)
        elif force and length and position > length - bookmarks.RESUME_END_MARGIN_MS \
                and last_track:
            self.store.clear_resume(self.media_id)

    # ------------------------------------------------------------------ #
    # Position slider / timer
    # ------------------------------------------------------------------ #
    def on_position_thumbtrack(self, event):
        self._seeking = True
        event.Skip()

    def on_position_release(self, event):
        self._seeking = False
        event.Skip()

    def on_position_seek(self, event):
        length = self.player.get_length()
        if length and length > 0:
            position = self.position_slider.GetValue() / 1000.0
            self.player.set_time(int(position * length))

    def on_volume_slider(self, event):
        volume = self.volume_slider.GetValue()
        self.target_volume = volume
        self.player.audio_set_volume(volume)

    def _sync_position_slider(self):
        length = self.player.get_length()
        if length and length > 0:
            permille = int((self.player.get_time() / length) * 1000)
            self.position_slider.SetValue(max(0, min(1000, permille)))

    def on_position_timer(self, event):
        # A resume point can only be applied once VLC has actually opened the
        # media (before that, set_time is silently dropped).
        if self._pending_seek_ms and self.player.is_playing():
            length = self.player.get_length()
            if length and length > 0:
                self.player.set_time(min(self._pending_seek_ms, length - 1000))
                self._pending_seek_ms = 0

        if not self._seeking:
            self._sync_position_slider()

        if self.is_playing:
            self._resume_save_due += 500
            if self._resume_save_due >= RESUME_SAVE_INTERVAL_MS:
                self._resume_save_due = 0
                self.save_resume()

        if self.is_playing and not self._advancing:
            try:
                ended = self.player.get_state() == vlc.State.Ended
            except Exception:
                ended = False
            if ended:
                self._advancing = True
                wx.CallAfter(self._on_track_finished)

    def _on_track_finished(self):
        """End of a track: move on through the book, or finish."""
        if self.track_index + 1 < len(self.tracks):
            self._load_track(self.track_index + 1, 0)
            return
        self.is_playing = False
        self._advancing = False
        if self.media_id:
            self.store.clear_resume(self.media_id)
        self.status.SetLabel(_("Finished"))
        self.play_pause_button.SetLabel(_("Play"))
        common.play_sound('done')
        common.speak(_("Finished"))

    # ------------------------------------------------------------------ #
    # Keyboard
    # ------------------------------------------------------------------ #
    def announce_keys(self):
        common.speak(_("Space play or pause. Left and right arrows seek ten "
                       "seconds. Up and down arrows change volume. Control "
                       "plus left or right changes track. Control plus B adds "
                       "a bookmark, control plus shift plus B adds a named "
                       "bookmark, B opens the bookmark list. Control plus home "
                       "starts from the beginning. Escape closes the player."))

    def on_key_down(self, event):
        key = event.GetKeyCode()
        control = event.ControlDown()
        shift = event.ShiftDown()

        if control and key in (wx.WXK_LEFT, wx.WXK_NUMPAD_LEFT):
            self.previous_track()
        elif control and key in (wx.WXK_RIGHT, wx.WXK_NUMPAD_RIGHT):
            self.next_track()
        elif control and key in (wx.WXK_HOME, wx.WXK_NUMPAD_HOME):
            self.restart()
        elif control and key in (ord('B'), ord('b')):
            self.add_bookmark(ask_name=shift)
        elif key in (ord('B'), ord('b')) and not event.HasModifiers():
            self.show_bookmarks()
        elif key == wx.WXK_F1:
            self.announce_keys()
        elif key == wx.WXK_SPACE:
            self.on_toggle_play(event)
        elif key == wx.WXK_LEFT:
            self.seek(-10000)
        elif key == wx.WXK_RIGHT:
            self.seek(10000)
        elif key == wx.WXK_UP:
            self.change_volume(10)
        elif key == wx.WXK_DOWN:
            self.change_volume(-10)
        elif key == wx.WXK_ESCAPE:
            self.owner.go_back()
        else:
            event.Skip()

    def stop_and_cleanup(self):
        """Fade out and release the VLC player. Called by the owner before
        this panel is torn down (navigating back or playing something new)."""
        if self.position_timer.IsRunning():
            self.position_timer.Stop()

        # Save the place BEFORE stopping - once VLC is stopped, get_time() is
        # gone and a two hour film would restart from zero.
        self.save_resume(force=True)

        if self.player.is_playing():
            current_volume = self.player.audio_get_volume()
            for volume in range(current_volume, -1, -5):
                self.player.audio_set_volume(volume)
                wx.Yield()
                wx.MilliSleep(50)

        self.player.stop()
        common.speak(_("Player closed"))
