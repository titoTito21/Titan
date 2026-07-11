#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import ctypes
import platform

try:
    from src.titan_core.skin_manager import apply_skin_to_window
except ImportError:
    apply_skin_to_window = None


def _apply_skin_to_tree(window):
    if not apply_skin_to_window or not window:
        return
    try:
        apply_skin_to_window(window)
    except Exception:
        return
    for child in window.GetChildren():
        _apply_skin_to_tree(child)

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
    try:
        import accessible_output3.outputs.auto
        ao = accessible_output3.outputs.auto.Auto()
        ao_enabled = True
    except ImportError:
        ao_enabled = False
except ImportError:
    sys.exit(1)

from translation import _


class Player(wx.Frame):
    def __init__(self, parent, *args, **kwargs):
        super(Player, self).__init__(parent, *args, **kwargs)
        self.SetTitle(_("Player"))
        self.SetSize((600, 400))
        panel = wx.Panel(self)

        self.instance = None
        self.player = None

        self.instance = vlc.Instance()
        self.player = self.instance.media_player_new()

        self.is_playing = False
        self.is_stream = False

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.status = wx.StaticText(panel, label=_("Paused"))
        vbox.Add(self.status, flag=wx.ALL, border=10)

        panel.SetSizer(vbox)
        _apply_skin_to_tree(self)

        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)
        self.Bind(wx.EVT_CLOSE, self.on_close)

        self.parent = parent

        self.speak_message(_("Player"))

        self.target_volume = 100


    def speak_message(self, message):
        if ao_enabled:
            ao.speak(message)
        else:
            print(f"[TTS MESSAGE]: {message}")

    def fade_in_volume(self):
        current_volume = 0
        self.player.audio_set_volume(current_volume)
        while current_volume < self.target_volume:
            current_volume = min(self.target_volume, current_volume + 5)
            self.player.audio_set_volume(current_volume)
            wx.MilliSleep(50)

    def play_file(self, filepath: str):
        media = self.instance.media_new(filepath)
        self.player.set_media(media)
        self.player.play()
        threading.Thread(target=self.fade_in_volume).start()

        title = (
            filepath.split('/')[-1]
            if not filepath.startswith("http")
            else _("Streaming")
        )
        self.SetTitle(title)
        self.status.SetLabel(_("Playing: ") + title)
        self.speak_message(_("Playing: %s") % title)

        self.is_playing = True

        if filepath.startswith("http"):
            monitor_thread = threading.Thread(target=self.monitor_stream, args=(filepath,))
            monitor_thread.start()

    def monitor_stream(self, filepath: str):
        while not self.player.is_playing():
            pass

        media_title = self.player.get_media().get_meta(vlc.Meta.Title)
        if media_title:
            self.SetTitle(media_title)
            self.status.SetLabel(_("Playing: ") + media_title)
            try:
                self.GetParent().GetParent().speak_message(_("Playing: %s") % media_title)
            except Exception:
                pass
        else:
            try:
                self.GetParent().GetParent().speak_message(_("Stream loaded"))
            except Exception:
                pass

    def on_key_down(self, event):
        key = event.GetKeyCode()

        if key == wx.WXK_SPACE:
            if self.is_playing:
                self.player.pause()
                self.is_playing = False
                self.status.SetLabel(_("Paused"))
                try:
                    self.GetParent().GetParent().speak_message(_("Paused"))
                except Exception:
                    pass
            else:
                self.player.play()
                self.is_playing = True
                self.status.SetLabel(_("Playing"))
                try:
                    self.GetParent().GetParent().speak_message(_("Playing"))
                except Exception:
                    pass

        elif key == wx.WXK_LEFT:
            current_time = self.player.get_time()
            self.player.set_time(max(0, current_time - 10000))
            self.status.SetLabel(_("Rewind 10s"))
            try:
                self.GetParent().GetParent().speak_message(_("Rewind 10 seconds"))
            except Exception:
                pass

        elif key == wx.WXK_RIGHT:
            current_time = self.player.get_time()
            self.player.set_time(current_time + 10000)
            self.status.SetLabel(_("Forward 10s"))
            try:
                self.GetParent().GetParent().speak_message(_("Forward 10 seconds"))
            except Exception:
                pass

        elif key == wx.WXK_UP:
            volume = min(100, self.player.audio_get_volume() + 10)
            self.player.audio_set_volume(volume)
            self.status.SetLabel(_("Volume: %d%%") % volume)
            self.speak_message(_("Volume: %d percent") % volume)

        elif key == wx.WXK_DOWN:
            volume = max(0, self.player.audio_get_volume() - 10)
            self.player.audio_set_volume(volume)
            self.status.SetLabel(_("Volume: %d%%") % volume)
            self.speak_message(_("Volume: %d percent") % volume)

        elif key == wx.WXK_ESCAPE:
            self.on_close(event)
        else:
            event.Skip()

    def on_close(self, event):
        if self.player.is_playing():
            current_volume = self.player.audio_get_volume()
            for volume in range(current_volume, -1, -5):
                self.player.audio_set_volume(volume)
                wx.Yield()
                wx.MilliSleep(50)

        self.player.stop()
        self.Destroy()
        self.speak_message(_("Player closed"))


if __name__ == "__main__":
    class MockParent(wx.Frame):
        def __init__(self, *args, **kwargs):
            super(MockParent, self).__init__(*args, **kwargs)
            self.tts_enabled = False

        def speak_message(self, message):
            print("[TTS MESSAGE]:", message)

    class MockGrandParent(wx.Frame):
        def __init__(self, *args, **kwargs):
            super(MockGrandParent, self).__init__(*args, **kwargs)
            self.tts_enabled = False

        def speak_message(self, message):
            print("[TTS MESSAGE]:", message)

    app = wx.App()
    grandparent = MockGrandParent(None, title="GrandParent")
    parent = MockParent(grandparent)
    player_frame = Player(parent)
    player_frame.Show()

    app.MainLoop()
