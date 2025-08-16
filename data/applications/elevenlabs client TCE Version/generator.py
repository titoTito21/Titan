import wx
import os
import tempfile
import threading
import shutil
from elevenlabs.client import ElevenLabs
import subprocess
import configparser
import tplayer
from translation import _

class Generator:
    def __init__(self, frame):
        self.frame = frame
        self.temp_filename = None

    def UpdateProgress(self, value):
        self.frame.progress_bar.SetValue(value)
        wx.Yield()

    def ShowErrorMessage(self, message):
        wx.MessageBox(message, _("Błąd"), wx.OK | wx.ICON_ERROR)

    def OnGenerate(self, event):
        self.frame.generate_button.Disable()
        self.frame.generate_button.SetLabel(_("Generowanie..."))
        self.frame.play_button.Disable()
        threading.Thread(target=self.GenerateAudio).start()

    def GenerateAudio(self):
        try:
            text = self.frame.text_ctrl.GetValue()
            selected_index = self.frame.voice_choice.GetSelection()
            if selected_index == -1:
                wx.CallAfter(self.ShowErrorMessage, _("Proszę wybrać głos"))
                wx.CallAfter(self.OnGenerateComplete)
                return
                
            selected_voice_id = self.frame.voices[selected_index]['id']

            for progress in range(0, 101, 25):
                wx.CallAfter(self.UpdateProgress, progress)
                wx.MilliSleep(100)

            audio = self.frame.client.text_to_speech.convert(
                text=text,
                voice_id=selected_voice_id,
                model_id="eleven_multilingual_v2",
                output_format="mp3_44100_128"
            )

            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                self.temp_filename = tmp.name
                tmp.write(audio)

            wx.CallAfter(self.OnGenerateComplete)

        except Exception as e:
            wx.CallAfter(self.ShowErrorMessage, _(f"Błąd podczas generowania audio: {str(e)}"))
            wx.CallAfter(self.OnGenerateComplete)

    def OnGenerateComplete(self):
        self.frame.generate_button.Enable()
        self.frame.generate_button.SetLabel(_("Generuj"))
        if self.temp_filename:
            self.frame.play_button.Enable()
            self.OnPlay(None)

    def OnPlay(self, event):
        config = configparser.ConfigParser()
        settings_path = os.path.expandvars(r'%appdata%\Titosoft\Titan\Additional apps\elevenlabsclient.ini')
        config.read(settings_path)
        playback_mode = config.get('Settings', 'playback_mode', fallback='mpv')

        if playback_mode == 'mpv':
            self.play_with_mpv()
        else:
            threading.Thread(target=self.play_with_tminiplayer).start()

    def play_with_mpv(self):
        if self.temp_filename:
            try:
                subprocess.Popen(['mpv', '--force-window', '--', self.temp_filename])
            except Exception as e:
                self.ShowErrorMessage(_(f"Błąd podczas odtwarzania audio: {str(e)}"))

    def play_with_tminiplayer(self):
        player = tplayer.TPlayer(self.temp_filename)
        player.run()

    def OnSave(self, event):
        if not self.temp_filename:
            return
        try:
            with wx.FileDialog(self.frame, _("Zapisz plik na dysku"), wildcard=_("Pliki MP3 (*.mp3)|*.mp3"),
                               style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fileDialog:
                if fileDialog.ShowModal() == wx.ID_CANCEL:
                    return
                save_path = fileDialog.GetPath()
                shutil.copy(self.temp_filename, save_path)
            os.remove(self.temp_filename)
        except Exception as e:
            self.ShowErrorMessage(_(f"Błąd podczas zapisywania pliku: {str(e)}"))
