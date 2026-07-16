# -*- coding: utf-8 -*-
"""Headless VLC playback engine: no wx, no UI, no TTS, no sound effects --
just play/pause/stop a single file.

PlayerPanel (player.py) wraps this with the full accessible TMedia UI and
TCE speech/sound theme. Other Titan apps that only want a silent preview
toggle (e.g. TFM playing/pausing the audio file under the cursor on Space)
should import this module directly instead -- that's the whole point of
keeping it dependency-free: no wx, no `common.py` announcements/sounds, just
bare playback, so a file manager doesn't have to pull in its own VLC/player
stack or Titan's speech/sound theme just to preview a file.

Reachable from a sibling app dir via:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tMedia'))
    from media_engine import MediaEngine
"""
import os
import sys
import ctypes


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

import vlc


class MediaEngine:
    """Bare play/pause/stop wrapper around a single VLC media_player instance."""

    def __init__(self):
        self.instance = vlc.Instance()
        self.player = self.instance.media_player_new()
        self.current_path = None

    def toggle_preview(self, path):
        """Space-bar semantics: pressing it again on the same file
        pauses/resumes; pressing it on a different file switches to that
        file and plays it. Returns True if now playing, False if paused."""
        if self.current_path == path:
            if self.player.is_playing():
                self.player.pause()
                return False
            self.player.play()
            return True

        media = self.instance.media_new(path)
        self.player.set_media(media)
        self.player.play()
        self.current_path = path
        return True

    def is_playing(self):
        return bool(self.player.is_playing())

    def stop(self):
        self.player.stop()
        self.current_path = None

    def release(self):
        self.stop()
        self.player.release()
        self.instance.release()
