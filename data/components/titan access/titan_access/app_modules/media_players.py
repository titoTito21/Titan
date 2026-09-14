# -*- coding: utf-8 -*-
"""Media players: VLC, foobar2000, Winamp, AIMP, MusicBee, Windows Media
Player, and the editors people keep beside them (Notepad++).

In the spirit of NVDA's ``vlc``, ``foobar2000`` and ``winamp`` modules.
A player's window title is what is PLAYING and it changes with the focus
standing still, so no focus event ever says a track has changed; the
module reads the top-level window's text on every focus inside the
program and says it once when it differs from the last one heard. The
same rule names the DOCUMENT in an editor whose title is the file.
"""

import ctypes

from titan_access.localization import L
from titan_access.app_modules.base import AppModuleBase


def _window_title(hwnd):
    """The top-level window's text over *hwnd*, or ''."""
    try:
        user32 = ctypes.windll.user32
        root = user32.GetAncestor(int(hwnd or 0), 2) if hwnd else 0
        if not root:
            root = user32.GetForegroundWindow()
        buffer = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(root, buffer, 512)
        return buffer.value.strip()
    except Exception:
        return ""


class _TitleIsNewsModule(AppModuleBase):
    """A program whose window title says what it is doing."""

    #: Locale key of the program's name.
    name_key = ""
    #: Locale key of the sentence said when the title changes ("{0}").
    news_key = "media.playing"
    #: Text the program appends to every title, taken off before it is
    #: said ("Song - VLC media player" -> "Song").
    suffixes = ()

    def __init__(self, engine):
        super().__init__(engine)
        self._last_title = None

    @property
    def app_name(self):
        return L(self.name_key) if self.name_key else self.process_name

    def on_lose_focus(self, obj):
        self._last_title = None
        super().on_lose_focus(obj)

    def on_gain_focus(self, obj):
        self._announce_welcome_once(self.app_name)

    def clean_title(self, title):
        for suffix in self.suffixes:
            if title.lower().endswith(suffix.lower()):
                title = title[:-len(suffix)].rstrip(" -–—|")
        return title.strip()

    def customize_object(self, obj):
        if obj is None:
            return obj
        try:
            title = self.clean_title(_window_title(getattr(obj, "hwnd", 0)))
        except Exception:
            return obj
        if not title or title == self._last_title:
            return obj
        first = self._last_title is None
        self._last_title = title
        if first:
            # The first title is where the user arrived; the welcome said
            # the program and the title alone is not yet news.
            return obj
        try:
            news = L(self.news_key, title)
            obj.description = ("%s, %s" % (obj.description, news)
                               if obj.description else news)
        except Exception:
            pass
        return obj


class VlcModule(_TitleIsNewsModule):
    process_name = "vlc"
    name_key = "media.vlc"
    suffixes = ("VLC media player",)


class Foobar2000Module(_TitleIsNewsModule):
    process_name = "foobar2000"
    name_key = "media.foobar"
    suffixes = ("[foobar2000]", "foobar2000")


class WinampModule(_TitleIsNewsModule):
    process_name = "winamp"
    name_key = "media.winamp"
    suffixes = ("- Winamp",)


class AimpModule(_TitleIsNewsModule):
    process_name = "aimp"
    name_key = "media.aimp"
    suffixes = ("- AIMP",)


class MusicBeeModule(_TitleIsNewsModule):
    process_name = "musicbee"
    name_key = "media.musicbee"
    suffixes = ("- MusicBee",)


class MediaPlayerModule(_TitleIsNewsModule):
    process_names = {"wmplayer", "microsoft.media.player"}
    process_name = "wmplayer"
    name_key = "media.wmp"
    suffixes = ("- Windows Media Player",)


class NotepadPlusPlusModule(_TitleIsNewsModule):
    """Notepad++: the document is the title.

    The editing surface is a Scintilla control, which exposes no UI
    Automation text pattern, so the caret is read through the reader's
    own text tiers as far as they reach; what this module adds is the
    name of the document as it changes, and the program's own name.
    """
    process_name = "notepad++"
    name_key = "media.notepadpp"
    news_key = "media.document"
    suffixes = ("- Notepad++",)
