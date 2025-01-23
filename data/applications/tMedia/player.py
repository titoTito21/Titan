#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import ctypes
import platform

def load_local_vlc():
    """
    Funkcja opcjonalnie wczytuje lokalne biblioteki VLC zależnie od systemu.
    Jeśli nie znajdzie lokalnych bibliotek, spróbuje użyć systemowych.
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Windows
    if os.name == 'nt':
        libvlc_path = os.path.join(current_dir, 'libvlc.dll')
        libvlccore_path = os.path.join(current_dir, 'libvlccore.dll')

        if os.path.exists(libvlc_path) and os.path.exists(libvlccore_path):
            # Dodajemy katalog do PATH, by Windows znalazł zależne .dll
            os.environ["PATH"] = current_dir + ";" + os.environ["PATH"]
            try:
                ctypes.cdll.LoadLibrary(libvlccore_path)
                ctypes.cdll.LoadLibrary(libvlc_path)
                print("Załadowano lokalne biblioteki VLC z katalogu:", current_dir)
            except OSError as e:
                print("Nie udało się załadować lokalnych bibliotek VLC:", e)
        else:
            print("Nie znaleziono lokalnych bibliotek VLC w katalogu:", current_dir)

    # macOS
    elif sys.platform == 'darwin':
        # Jeżeli chcesz używać lokalnych bibliotek, np. libvlc.dylib:
        libvlc_dylib = os.path.join(current_dir, 'libvlc.dylib')
        if os.path.exists(libvlc_dylib):
            try:
                ctypes.cdll.LoadLibrary(libvlc_dylib)
                print("Załadowano lokalną bibliotekę libvlc.dylib z:", current_dir)
            except OSError as e:
                print("Nie udało się załadować lokalnej libvlc.dylib:", e)
        else:
            print("Nie znaleziono lokalnej libvlc.dylib w katalogu:", current_dir)

    # Linux (zazwyczaj VLC jest zainstalowane systemowo)
    else:
        print("Linux – zakładam użycie systemowej instalacji VLC.")
        # Jeśli chciałbyś użyć lokalnego .so, można tu dodać analogiczny kod.


# -----------------------------------------------------------
# Najpierw podejmujemy próbę załadowania lokalnych bibliotek
# -----------------------------------------------------------
load_local_vlc()

# -----------------------------------------------------------
# Importy właściwe do obsługi GUI i VLC
# -----------------------------------------------------------
try:
    import wx
    import vlc
    import threading
except ImportError as e:
    print("Brakuje wymaganego modułu:", e)
    sys.exit(1)

# -----------------------------------------------------------
# Klasa Player
# -----------------------------------------------------------
class Player(wx.Frame):
    def __init__(self, parent, *args, **kwargs):
        super(Player, self).__init__(parent, *args, **kwargs)
        self.SetTitle("Odtwarzacz")
        self.SetSize((600, 400))
        panel = wx.Panel(self)

        # Instancja VLC
        self.instance = vlc.Instance()
        self.player = self.instance.media_player_new()

        self.is_playing = False
        self.is_stream = False

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.status = wx.StaticText(panel, label="Wstrzymano")
        vbox.Add(self.status, flag=wx.ALL, border=10)

        panel.SetSizer(vbox)

        # Obsługa klawiatury
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)

        self.parent = parent

        # Komunikat TTS przy otwieraniu odtwarzacza
        # (zakładamy, że 'speak_message' jest zdefiniowane w "grandparent", np. TMediaApp)
        self.GetParent().GetParent().speak_message("Odtwarzacz")

    def play_file(self, filepath: str):
        """
        Odtwarza plik lokalny lub strumień (HTTP).
        """
        media = self.instance.media_new(filepath)
        self.player.set_media(media)
        self.player.play()

        title = (
            filepath.split('/')[-1]
            if not filepath.startswith("http")
            else "Odtwarzanie strumienia"
        )
        self.SetTitle(title)
        self.status.SetLabel("Odtwarzanie: " + title)
        self.GetParent().GetParent().speak_message(f"Odtwarzanie: {title}")

        self.is_playing = True

        # Uruchom wątek monitorujący start strumienia (jeśli to URL)
        if filepath.startswith("http"):
            monitor_thread = threading.Thread(target=self.monitor_stream, args=(filepath,))
            monitor_thread.start()

    def monitor_stream(self, filepath: str):
        """
        Wątek sprawdzający, kiedy VLC faktycznie rozpocznie odtwarzanie strumienia.
        Gdy to się stanie – pobiera np. tytuł (metadane).
        """
        while not self.player.is_playing():
            pass  # czekaj, aż strumień się rozpocznie

        media_title = self.player.get_media().get_meta(vlc.Meta.Title)
        if media_title:
            self.SetTitle(media_title)
            self.status.SetLabel(f"Odtwarzanie: {media_title}")
            self.GetParent().GetParent().speak_message(f"Odtwarzanie: {media_title}")
        else:
            self.GetParent().GetParent().speak_message("Strumień został załadowany")

    def on_key_down(self, event):
        key = event.GetKeyCode()

        if key == wx.WXK_SPACE:
            # Pauzowanie / wznawianie
            if self.is_playing:
                self.player.pause()
                self.is_playing = False
                self.status.SetLabel("Wstrzymano")
                self.GetParent().GetParent().speak_message("Wstrzymano")
            else:
                self.player.play()
                self.is_playing = True
                self.status.SetLabel("Odtwarzanie")
                self.GetParent().GetParent().speak_message("Odtwarzanie")

        elif key == wx.WXK_LEFT:
            # Przewijanie w lewo o 10 sekund
            current_time = self.player.get_time()
            self.player.set_time(max(0, current_time - 10000))
            self.status.SetLabel("Przewijanie w lewo")
            self.GetParent().GetParent().speak_message("Przewijanie w lewo")

        elif key == wx.WXK_RIGHT:
            # Przewijanie w prawo o 10 sekund
            current_time = self.player.get_time()
            self.player.set_time(current_time + 10000)
            self.status.SetLabel("Przewijanie w prawo")
            self.GetParent().GetParent().speak_message("Przewijanie w prawo")

        elif key == wx.WXK_UP:
            # Głośniej
            volume = min(100, self.player.audio_get_volume() + 10)
            self.player.audio_set_volume(volume)
            self.status.SetLabel(f"Głośność: {volume}%")
            self.GetParent().GetParent().speak_message(f"Głośność: {volume} procent")

        elif key == wx.WXK_DOWN:
            # Ciszej
            volume = max(0, self.player.audio_get_volume() - 10)
            self.player.audio_set_volume(volume)
            self.status.SetLabel(f"Głośność: {volume}%")
            self.GetParent().GetParent().speak_message(f"Głośność: {volume} procent")

        elif key == wx.WXK_ESCAPE:
            # Zatrzymanie i zamknięcie
            self.player.stop()
            self.Close()
            self.GetParent().GetParent().speak_message("Zamknięto odtwarzacz")
        else:
            event.Skip()  # Pozwala obsłużyć inne klawisze, np. do obsługi okna

# -----------------------------------------------------------
# Kod testowy (opcjonalny)
# -----------------------------------------------------------
if __name__ == "__main__":
    """
    Przykładowe uruchomienie testowe.
    Wymaga minimalnej ramki wxPython z definicją speak_message (lub zrezygnować z TTS).
    """
    class MockParent(wx.Frame):
        def __init__(self, *args, **kwargs):
            super(MockParent, self).__init__(*args, **kwargs)
            self.tts_enabled = False

        def speak_message(self, message):
            print("[TTS MESSAGE]:", message)

    class MockGrandParent(wx.Frame):
        def __init__(self, *args, **kwargs):
            super(MockGrandParent, self).__init__(*args, **kwargs)
            # Symulujemy, że w "grandparent" jest speak_message
            self.tts_enabled = False

        def speak_message(self, message):
            print("[TTS MESSAGE]:", message)

    app = wx.App()
    grandparent = MockGrandParent(None, title="GrandParent")
    parent = MockParent(grandparent)
    player_frame = Player(parent)
    player_frame.Show()

    # Można przetestować odtwarzanie pliku lokalnego lub strumienia
    # (np. player_frame.play_file("ścieżka/do/pliku.mp3") lub player_frame.play_file("http://..."))

    app.MainLoop()
