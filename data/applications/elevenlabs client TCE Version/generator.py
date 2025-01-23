import wx
import os
import tempfile
import threading
import shutil
from elevenlabs import generate
import subprocess
import configparser
import tplayer

class Generator:
    def __init__(self, frame):
        self.frame = frame
        self.temp_filename = None

    def UpdateProgress(self, value):
        self.frame.progress_bar.SetValue(value)
        wx.Yield()

    def ShowErrorMessage(self, message):
        wx.MessageBox(message, "Error", wx.OK | wx.ICON_ERROR)

    def OnGenerate(self, event):
        self.frame.generate_button.Disable()
        self.frame.generate_button.SetLabel("Generating...")
        self.frame.play_button.Disable()
        threading.Thread(target=self.GenerateAudio).start()

    def GenerateAudio(self):
        try:
            text = self.frame.text_ctrl.GetValue()
            selected_voice = self.frame.voice_choice.GetString(self.frame.voice_choice.GetSelection())

            for progress in range(0, 101, 25):
                wx.CallAfter(self.UpdateProgress, progress)
                wx.MilliSleep(100)

            audio_stream = generate(
                text=text,
                voice=selected_voice,
                model="eleven_multilingual_v2",
                stream=True
            )

            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                self.temp_filename = tmp.name
                for audio_chunk in audio_stream:
                    tmp.write(audio_chunk)

            wx.CallAfter(self.OnGenerateComplete)

        except Exception as e:
            wx.CallAfter(self.ShowErrorMessage, f"Error generating audio: {str(e)}")
            wx.CallAfter(self.OnGenerateComplete)

    def OnGenerateComplete(self):
        self.frame.generate_button.Enable()
        self.frame.generate_button.SetLabel("Generate")
        if self.temp_filename:
            self.frame.play_button.Enable()
            self.OnPlay(None)

    def OnPlay(self, event):
        config = configparser.ConfigParser()
        config.read(r'%appdata%\Titosoft\Titan\Additional apps\elevenlabsclient.ini')
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
                self.ShowErrorMessage(f"Error playing audio: {str(e)}")

    def play_with_tminiplayer(self):
        player = tplayer.TPlayer(self.temp_filename)
        player.run()

    def OnSave(self, event):
        if not self.temp_filename:
            return
        try:
            with wx.FileDialog(self.frame, "Save file to disc", wildcard="MP3 files (*.mp3)|*.mp3",
                               style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fileDialog:
                if fileDialog.ShowModal() == wx.ID_CANCEL:
                    return
                save_path = fileDialog.GetPath()
                shutil.copy(self.temp_filename, save_path)
            os.remove(self.temp_filename)
        except Exception as e:
            self.ShowErrorMessage(f"Error saving file: {str(e)}")
