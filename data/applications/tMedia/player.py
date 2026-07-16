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

from translation import _
import common


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

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.status = wx.StaticText(self, label=_("Paused"))
        vbox.Add(self.status, flag=wx.ALL, border=10)

        self.play_pause_button = wx.Button(self, label=_("Pause"))
        vbox.Add(self.play_pause_button, flag=wx.ALL, border=5)

        position_label_text = _("Playback position")
        position_label = wx.StaticText(self, label=position_label_text)
        vbox.Add(position_label, flag=wx.LEFT | wx.TOP, border=10)
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
        self.position_slider.Bind(wx.EVT_SCROLL_THUMBTRACK, self.on_position_thumbtrack)
        self.position_slider.Bind(wx.EVT_SCROLL_THUMBRELEASE, self.on_position_release)
        self.position_slider.Bind(wx.EVT_SLIDER, self.on_position_seek)
        self.volume_slider.Bind(wx.EVT_SLIDER, self.on_volume_slider)

        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)

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

    def play_file(self, filepath: str, title: str = None):
        media = self.instance.media_new(filepath)
        self.player.set_media(media)
        self.player.play()
        threading.Thread(target=self.fade_in_volume, daemon=True).start()

        has_explicit_title = title is not None
        if not has_explicit_title:
            title = (
                filepath.split('/')[-1]
                if not filepath.startswith("http")
                else _("Streaming")
            )
        self.owner.SetTitle(_("Playing: %s") % title)
        self.status.SetLabel(_("Playing: ") + title)
        self.play_pause_button.SetLabel(_("Pause"))
        common.speak(_("Playing: %s") % title)

        self.is_playing = True

        if filepath.startswith("http") and not has_explicit_title:
            monitor_thread = threading.Thread(target=self.monitor_stream, args=(filepath,), daemon=True)
            monitor_thread.start()

    def monitor_stream(self, filepath: str):
        while not self.player.is_playing():
            wx.MilliSleep(50)

        media_title = self.player.get_media().get_meta(vlc.Meta.Title)
        if media_title:
            wx.CallAfter(self.owner.SetTitle, _("Playing: %s") % media_title)
            wx.CallAfter(self.status.SetLabel, _("Playing: ") + media_title)
            wx.CallAfter(common.speak, _("Playing: %s") % media_title)
        else:
            wx.CallAfter(common.speak, _("Stream loaded"))

    def on_toggle_play(self, event):
        if self.is_playing:
            self.player.pause()
            self.is_playing = False
            self.status.SetLabel(_("Paused"))
            self.play_pause_button.SetLabel(_("Play"))
            common.speak(_("Paused"))
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

    def change_volume(self, delta):
        """Keyboard-shortcut volume change (Up/Down); see seek() for why
        this announces while the slider's own handler does not."""
        volume = min(100, max(0, self.player.audio_get_volume() + delta))
        self.player.audio_set_volume(volume)
        self.volume_slider.SetValue(volume)
        common.speak(_("Volume: %d percent") % volume)

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
        self.player.audio_set_volume(volume)

    def _sync_position_slider(self):
        length = self.player.get_length()
        if length and length > 0:
            permille = int((self.player.get_time() / length) * 1000)
            self.position_slider.SetValue(max(0, min(1000, permille)))

    def on_position_timer(self, event):
        if not self._seeking:
            self._sync_position_slider()

    def on_key_down(self, event):
        key = event.GetKeyCode()

        if key == wx.WXK_SPACE:
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

        if self.player.is_playing():
            current_volume = self.player.audio_get_volume()
            for volume in range(current_volume, -1, -5):
                self.player.audio_set_volume(volume)
                wx.Yield()
                wx.MilliSleep(50)

        self.player.stop()
        common.speak(_("Player closed"))
