import wx
import os
import tempfile
import subprocess
import configparser
import threading
from translation import _

class SpeechToSpeechDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Speech to Speech Conversion"), size=(600, 400))

        self.parent = parent
        self.client = parent.client
        self.input_file = None
        self.output_file = None

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Instructions
        info_text = wx.StaticText(panel, label=_(
            "Convert speech from one voice to another.\n"
            "Select an audio file and a target voice to create a new version."
        ))
        vbox.Add(info_text, 0, wx.ALL, 10)

        # Input file selection
        input_label = wx.StaticText(panel, label=_("Input Audio File:"))
        vbox.Add(input_label, 0, wx.ALL, 5)

        input_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.input_path_ctrl = wx.TextCtrl(panel, style=wx.TE_READONLY)
        input_sizer.Add(self.input_path_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        self.browse_button = wx.Button(panel, label=_("Browse..."))
        self.browse_button.Bind(wx.EVT_BUTTON, self.OnBrowse)
        input_sizer.Add(self.browse_button, 0, wx.ALL, 5)

        vbox.Add(input_sizer, 0, wx.EXPAND)

        # Voice selection
        voice_label = wx.StaticText(panel, label=_("Target Voice:"))
        vbox.Add(voice_label, 0, wx.ALL, 5)

        self.voice_choice = wx.Choice(panel, choices=[voice['name'] for voice in parent.voices])
        vbox.Add(self.voice_choice, 0, wx.EXPAND | wx.ALL, 5)

        # Model selection
        model_label = wx.StaticText(panel, label=_("Model:"))
        vbox.Add(model_label, 0, wx.ALL, 5)

        self.model_choice = wx.Choice(panel, choices=[
            "eleven_english_sts_v2",
            "eleven_multilingual_sts_v2"
        ])
        self.model_choice.SetSelection(1)
        vbox.Add(self.model_choice, 0, wx.EXPAND | wx.ALL, 5)

        # Progress bar
        self.progress_bar = wx.Gauge(panel, range=100, style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)
        vbox.Add(self.progress_bar, 0, wx.EXPAND | wx.ALL, 10)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.convert_button = wx.Button(panel, label=_("Convert"))
        self.convert_button.Bind(wx.EVT_BUTTON, self.OnConvert)
        button_sizer.Add(self.convert_button, 0, wx.ALL, 5)

        self.play_button = wx.Button(panel, label=_("Play Result"))
        self.play_button.Bind(wx.EVT_BUTTON, self.OnPlay)
        self.play_button.Disable()
        button_sizer.Add(self.play_button, 0, wx.ALL, 5)

        self.save_button = wx.Button(panel, label=_("Save Result"))
        self.save_button.Bind(wx.EVT_BUTTON, self.OnSave)
        self.save_button.Disable()
        button_sizer.Add(self.save_button, 0, wx.ALL, 5)

        self.close_button = wx.Button(panel, label=_("Close"))
        self.close_button.Bind(wx.EVT_BUTTON, self.OnClose)
        button_sizer.Add(self.close_button, 0, wx.ALL, 5)

        vbox.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        panel.SetSizer(vbox)

    def OnBrowse(self, event):
        """Browse for input audio file"""
        with wx.FileDialog(self, _("Choose audio file"),
                          wildcard=_("Audio files (*.mp3;*.wav;*.ogg;*.flac)|*.mp3;*.wav;*.ogg;*.flac|All files (*.*)|*.*"),
                          style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return

            self.input_file = fileDialog.GetPath()
            self.input_path_ctrl.SetValue(self.input_file)

    def OnConvert(self, event):
        """Convert speech to speech"""
        if not self.input_file:
            wx.MessageBox(_("Please select an input audio file"), _("Error"), wx.OK | wx.ICON_ERROR)
            return

        selected_index = self.voice_choice.GetSelection()
        if selected_index == -1:
            wx.MessageBox(_("Please select a target voice"), _("Error"), wx.OK | wx.ICON_ERROR)
            return

        self.convert_button.Disable()
        self.convert_button.SetLabel(_("Converting..."))
        threading.Thread(target=self.ConvertAudio).start()

    def ConvertAudio(self):
        """Perform the actual conversion"""
        try:
            selected_voice_id = self.parent.voices[self.voice_choice.GetSelection()]['id']
            model_id = self.model_choice.GetStringSelection()

            # Update progress
            wx.CallAfter(self.progress_bar.SetValue, 25)

            # Read input audio file
            with open(self.input_file, 'rb') as f:
                audio_data = f.read()

            wx.CallAfter(self.progress_bar.SetValue, 50)

            # Convert using API
            result = self.client.speech_to_speech.convert(
                voice_id=selected_voice_id,
                audio=audio_data,
                model_id=model_id
            )

            wx.CallAfter(self.progress_bar.SetValue, 75)

            # Save result to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                for chunk in result:
                    tmp.write(chunk)
                self.output_file = tmp.name

            wx.CallAfter(self.progress_bar.SetValue, 100)
            wx.CallAfter(self.OnConversionComplete)

        except Exception as e:
            wx.CallAfter(wx.MessageBox, _(f"Error during conversion: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)
            wx.CallAfter(self.OnConversionComplete)

    def OnConversionComplete(self):
        """Called when conversion is complete"""
        self.convert_button.Enable()
        self.convert_button.SetLabel(_("Convert"))

        if self.output_file:
            self.play_button.Enable()
            self.save_button.Enable()
            wx.MessageBox(_("Conversion completed successfully"), _("Success"), wx.OK | wx.ICON_INFORMATION)

    def OnPlay(self, event):
        """Play the converted audio"""
        if not self.output_file:
            return

        try:
            config = configparser.ConfigParser()
            settings_path = os.path.expandvars(r'%appdata%\Titosoft\Titan\Additional apps\elevenlabsclient.ini')
            config.read(settings_path)
            playback_mode = config.get('Settings', 'playback_mode', fallback='mpv')

            if playback_mode == 'mpv':
                subprocess.Popen(['mpv', '--force-window', '--', self.output_file])
            else:
                import tplayer
                player = tplayer.TPlayer(self.output_file)
                player.run()

        except Exception as e:
            wx.MessageBox(_(f"Error playing audio: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnSave(self, event):
        """Save the converted audio"""
        if not self.output_file:
            return

        try:
            with wx.FileDialog(self, _("Save converted audio"),
                              wildcard=_("MP3 files (*.mp3)|*.mp3"),
                              style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fileDialog:
                if fileDialog.ShowModal() == wx.ID_CANCEL:
                    return

                save_path = fileDialog.GetPath()

                # Copy temp file to destination
                import shutil
                shutil.copy(self.output_file, save_path)

                wx.MessageBox(_("Audio saved successfully"), _("Success"), wx.OK | wx.ICON_INFORMATION)

        except Exception as e:
            wx.MessageBox(_(f"Error saving audio: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnClose(self, event):
        """Close dialog"""
        # Clean up temp file
        if self.output_file and os.path.exists(self.output_file):
            try:
                os.remove(self.output_file)
            except:
                pass

        self.EndModal(wx.ID_OK)
