import wx
from translation import _
from elevenlabs.client import ElevenLabs
import os
import configparser
import key_dialog
from menu_bar import MenuBar
from database import VoiceDatabaseDialog
from generator import Generator
from support_dialog import SupportDialog
from clonegen import VoiceCloningDialog, clone_and_notify
from settings import SettingsDialog
from tplayer import TPlayer
from history_manager import HistoryDialog
from voice_manager import VoiceManagerDialog
from speech_to_speech import SpeechToSpeechDialog
from sound_effects import SoundEffectsDialog
from user_info import UserInfoDialog, ModelsDialog
from cache_viewer import CacheViewerDialog

class ElevenLabsClient(wx.Frame):
    def __init__(self, parent, title):
        super(ElevenLabsClient, self).__init__(parent, title=title, size=(600, 500))

        self.client = None
        self.init_elevenlabs_client()
        self.generator = Generator(self)
        self.InitUI()
        self.CreateStatusBar()
        self.SetStatusText(_("Ready"))
        self.Centre()
        
    def init_elevenlabs_client(self):
        """Initialize ElevenLabs client with API key if available"""
        settings_path = os.path.expandvars(r'%appdata%\Titosoft\Titan\Additional apps\elevenlabsclient.ini')
        if os.path.exists(settings_path):
            config = configparser.ConfigParser()
            config.read(settings_path)
            api_key = config.get('Settings', 'api_key', fallback=None)
            if api_key:
                self.client = ElevenLabs(api_key=api_key)
        
        if not self.client:
            self.client = ElevenLabs()

    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Text input
        text_label = wx.StaticText(panel, label=_("Text to generate:"))
        vbox.Add(text_label, 0, wx.LEFT | wx.TOP, 10)
        self.text_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE)
        vbox.Add(self.text_ctrl, 1, wx.EXPAND | wx.ALL, 10)

        # Voice selection
        voices_label = wx.StaticText(panel, label=_("Voice:"))
        vbox.Add(voices_label, 0, wx.LEFT | wx.TOP, 10)
        self.voices = self.get_available_voices()
        self.voice_choice = wx.Choice(panel, choices=[voice['name'] for voice in self.voices])
        vbox.Add(self.voice_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # Model selection
        model_label = wx.StaticText(panel, label=_("Model:"))
        vbox.Add(model_label, 0, wx.LEFT | wx.TOP, 10)
        self.model_choice = wx.Choice(panel, choices=[
            "eleven_monolingual_v1",
            "eleven_multilingual_v1",
            "eleven_multilingual_v2",
            "eleven_turbo_v2",
            "eleven_turbo_v2_5"
        ])
        self.model_choice.SetSelection(2)  # Default to multilingual v2
        vbox.Add(self.model_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # Voice settings button
        self.settings_button = wx.Button(panel, label=_("Voice Settings..."))
        self.settings_button.Bind(wx.EVT_BUTTON, self.OnVoiceSettings)
        vbox.Add(self.settings_button, 0, wx.EXPAND | wx.ALL, 10)

        # Action buttons
        self.generate_button = wx.Button(panel, label=_("Generate"))
        self.generate_button.Bind(wx.EVT_BUTTON, self.generator.OnGenerate)
        vbox.Add(self.generate_button, 0, wx.EXPAND | wx.ALL, 10)

        self.play_button = wx.Button(panel, label=_("&Play"))
        self.play_button.Bind(wx.EVT_BUTTON, self.generator.OnPlay)
        self.play_button.Disable()
        vbox.Add(self.play_button, 0, wx.EXPAND | wx.ALL, 10)

        self.save_button = wx.Button(panel, label=_("&Save to disk"))
        self.save_button.Bind(wx.EVT_BUTTON, self.generator.OnSave)
        vbox.Add(self.save_button, 0, wx.EXPAND | wx.ALL, 10)

        self.progress_bar = wx.Gauge(panel, range=100, style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)
        vbox.Add(self.progress_bar, 0, wx.EXPAND | wx.ALL, 10)

        # Menu bar
        menu_bar = MenuBar(self)
        self.SetMenuBar(menu_bar)
        panel.SetSizer(vbox)
        
    def get_available_voices(self):
        """Get available voices from ElevenLabs API"""
        try:
            # Correct method - voices.get_all() returns all user's voices
            try:
                response = self.client.voices.get_all()

                # Handle different response formats
                if hasattr(response, 'voices'):
                    voices_list = response.voices
                else:
                    voices_list = response if isinstance(response, list) else []

                return [{'name': voice.name, 'id': voice.voice_id} for voice in voices_list]

            except AttributeError:
                # Fallback: try alternative method
                voices_list = self.client.voices.get_all()
                if isinstance(voices_list, list):
                    return [{'name': voice.name, 'id': voice.voice_id} for voice in voices_list]
                else:
                    raise

        except Exception as e:
            error_msg = str(e)
            wx.MessageBox(
                _(f"Error loading voices: {error_msg}\n\nPlease check your API key in File → Client Settings"),
                _("Error"),
                wx.OK | wx.ICON_ERROR
            )
            # Return empty list instead of fake default
            return []

    def OnVoiceSettings(self, event):
        """Open voice settings dialog"""
        dlg = VoiceSettingsDialog(self, self.generator)
        dlg.ShowModal()
        dlg.Destroy()

    def OnVoiceCloning(self, event):
        """Open voice cloning dialog"""
        dialog = VoiceCloningDialog(self)
        if dialog.ShowModal() == wx.ID_OK:
            voice_name = dialog.name_text_ctrl.GetValue()
            voice_description = dialog.description_text_ctrl.GetValue()
            path = dialog.path
            clone_and_notify(self, voice_name, voice_description, path)
            # Refresh voice list
            self.voices = self.get_available_voices()
            self.voice_choice.Clear()
            for voice in self.voices:
                self.voice_choice.Append(voice['name'])

    def OnSetApiKey(self, event):
        """Set API key"""
        dialog = key_dialog.ApiKeyDialog(self)
        if dialog.ShowModal() == wx.ID_OK:
            with open('API_key.tkf', 'w') as file:
                file.write(f'API_key="{dialog.api_key_value}"')

            wx.MessageBox(
                _("To use the API key, the program must be restarted to refresh the voice list and unlock premium ElevenLabs features."),
                _("ElevenLabs Client"),
                wx.OK | wx.ICON_INFORMATION
            )

    def OnVoiceDatabase(self, event):
        """Open voice database"""
        support_dlg = SupportDialog(self)
        support_dlg.ShowModal()
        support_dlg.Destroy()
        db_dlg = VoiceDatabaseDialog(self)
        db_dlg.ShowModal()
        db_dlg.Destroy()
        # Refresh voice list
        self.voices = self.get_available_voices()
        self.voice_choice.Clear()
        for voice in self.voices:
            self.voice_choice.Append(voice['name'])

    def OnClientSettings(self, event):
        """Open client settings"""
        settings_dlg = SettingsDialog(self)
        if settings_dlg.ShowModal() == wx.ID_OK:
            settings_dlg.SaveSettings()
            wx.MessageBox(_("Settings have been saved."), _("Client Settings"), wx.OK | wx.ICON_INFORMATION)
        settings_dlg.Destroy()

    def OnHistory(self, event):
        """Open history manager"""
        dlg = HistoryDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def OnVoiceManager(self, event):
        """Open voice manager"""
        dlg = VoiceManagerDialog(self)
        dlg.ShowModal()
        dlg.Destroy()
        # Refresh voice list
        self.voices = self.get_available_voices()
        self.voice_choice.Clear()
        for voice in self.voices:
            self.voice_choice.Append(voice['name'])

    def OnSpeechToSpeech(self, event):
        """Open speech to speech conversion"""
        dlg = SpeechToSpeechDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def OnSoundEffects(self, event):
        """Open sound effects generator"""
        dlg = SoundEffectsDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def OnUserInfo(self, event):
        """Open user information and subscription dialog"""
        dlg = UserInfoDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def OnModels(self, event):
        """Open models dialog"""
        dlg = ModelsDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def OnCacheViewer(self, event):
        """Open cache viewer"""
        dlg = CacheViewerDialog(self, self.generator.cache)
        dlg.ShowModal()
        dlg.Destroy()

class VoiceSettingsDialog(wx.Dialog):
    """Dialog for adjusting voice generation settings"""
    def __init__(self, parent, generator):
        super().__init__(parent, title=_("Voice Generation Settings"), size=(400, 400))

        self.generator = generator

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Stability
        stability_label = wx.StaticText(panel, label=_("Stability (0-100):"))
        vbox.Add(stability_label, 0, wx.ALL, 5)
        self.stability_slider = wx.Slider(panel, value=int(generator.stability * 100),
                                          minValue=0, maxValue=100,
                                          style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        vbox.Add(self.stability_slider, 0, wx.EXPAND | wx.ALL, 5)

        # Similarity Boost
        similarity_label = wx.StaticText(panel, label=_("Similarity Boost (0-100):"))
        vbox.Add(similarity_label, 0, wx.ALL, 5)
        self.similarity_slider = wx.Slider(panel, value=int(generator.similarity_boost * 100),
                                          minValue=0, maxValue=100,
                                          style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        vbox.Add(self.similarity_slider, 0, wx.EXPAND | wx.ALL, 5)

        # Style
        style_label = wx.StaticText(panel, label=_("Style (0-100):"))
        vbox.Add(style_label, 0, wx.ALL, 5)
        self.style_slider = wx.Slider(panel, value=int(generator.style * 100),
                                      minValue=0, maxValue=100,
                                      style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        vbox.Add(self.style_slider, 0, wx.EXPAND | wx.ALL, 5)

        # Speaker Boost
        self.speaker_boost_check = wx.CheckBox(panel, label=_("Use Speaker Boost"))
        self.speaker_boost_check.SetValue(generator.use_speaker_boost)
        vbox.Add(self.speaker_boost_check, 0, wx.ALL, 5)

        # Info text
        info_text = wx.StaticText(panel, label=_(
            "Stability: Higher values make the voice more consistent\n"
            "Similarity Boost: Higher values make the voice closer to the original\n"
            "Style: Controls the expressiveness (V2 models only)\n"
            "Speaker Boost: Enhances similarity to the original speaker"
        ))
        vbox.Add(info_text, 0, wx.ALL, 5)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        ok_button = wx.Button(panel, wx.ID_OK, _("OK"))
        ok_button.Bind(wx.EVT_BUTTON, self.OnOK)
        cancel_button = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        button_sizer.Add(ok_button, 0, wx.ALL, 5)
        button_sizer.Add(cancel_button, 0, wx.ALL, 5)

        vbox.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        panel.SetSizer(vbox)

    def OnOK(self, event):
        """Save settings to generator"""
        self.generator.stability = self.stability_slider.GetValue() / 100.0
        self.generator.similarity_boost = self.similarity_slider.GetValue() / 100.0
        self.generator.style = self.style_slider.GetValue() / 100.0
        self.generator.use_speaker_boost = self.speaker_boost_check.GetValue()
        self.EndModal(wx.ID_OK)


if __name__ == '__main__':
    settings_path = os.path.expandvars(r'%appdata%\Titosoft\Titan\Additional apps\elevenlabsclient.ini')
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)

    app = wx.App()
    frame = ElevenLabsClient(None, title=_("ElevenLabs Client"))
    frame.Show()
    app.MainLoop()
