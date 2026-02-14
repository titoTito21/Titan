# database.py

import wx
import os
import tempfile
import subprocess
import configparser
from translation import _
from api_key_helper import check_api_key

class VoiceDatabaseDialog(wx.Dialog):
    def __init__(self, parent):
        super(VoiceDatabaseDialog, self).__init__(parent, title=_("ElevenLabs Voice Library (Community Voices)"), size=(900, 650))

        self.parent = parent
        self.client = parent.client
        self.voices = []

        # Check if API key is configured
        if not check_api_key(parent):
            self.Destroy()
            return

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Info text
        info_text = wx.StaticText(panel, label=_("Browse and add voices shared by the ElevenLabs community"))
        font = info_text.GetFont()
        font.PointSize += 1
        font = font.Bold()
        info_text.SetFont(font)
        vbox.Add(info_text, 0, wx.ALL | wx.ALIGN_CENTER, 10)

        # Search controls
        search_sizer = wx.BoxSizer(wx.HORIZONTAL)
        search_label = wx.StaticText(panel, label=_("Search:"))
        search_sizer.Add(search_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        self.search_ctrl = wx.TextCtrl(panel)
        self.search_ctrl.Bind(wx.EVT_TEXT, self.OnSearch)
        search_sizer.Add(self.search_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        vbox.Add(search_sizer, 0, wx.EXPAND)

        # Filter controls
        filter_sizer = wx.BoxSizer(wx.HORIZONTAL)

        category_label = wx.StaticText(panel, label=_("Category:"))
        filter_sizer.Add(category_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        self.category_choice = wx.Choice(panel, choices=[
            _("All"),
            _("Premade"),
            _("Cloned"),
            _("Generated"),
            _("Professional")
        ])
        self.category_choice.SetSelection(0)
        self.category_choice.Bind(wx.EVT_CHOICE, self.OnFilter)
        filter_sizer.Add(self.category_choice, 0, wx.ALL, 5)

        language_label = wx.StaticText(panel, label=_("Language:"))
        filter_sizer.Add(language_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        self.language_choice = wx.Choice(panel, choices=[
            _("All"),
            "English",
            "Spanish",
            "French",
            "German",
            "Italian",
            "Polish",
            "Portuguese",
            "Russian",
            "Chinese",
            "Japanese",
            "Korean"
        ])
        self.language_choice.SetSelection(0)
        self.language_choice.Bind(wx.EVT_CHOICE, self.OnFilter)
        filter_sizer.Add(self.language_choice, 0, wx.ALL, 5)

        vbox.Add(filter_sizer, 0, wx.EXPAND)

        # Voice list
        voice_label = wx.StaticText(panel, label=_("Available Voices:"))
        vbox.Add(voice_label, 0, wx.ALL, 5)

        self.voice_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.voice_list.AppendColumn(_("Name"), width=200)
        self.voice_list.AppendColumn(_("Category"), width=100)
        self.voice_list.AppendColumn(_("Gender"), width=80)
        self.voice_list.AppendColumn(_("Age"), width=80)
        self.voice_list.AppendColumn(_("Accent"), width=120)
        self.voice_list.AppendColumn(_("Use Case"), width=150)
        vbox.Add(self.voice_list, 1, wx.EXPAND | wx.ALL, 5)

        # Details
        details_label = wx.StaticText(panel, label=_("Voice Details:"))
        vbox.Add(details_label, 0, wx.ALL, 5)

        self.details_text = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 80))
        vbox.Add(self.details_text, 0, wx.EXPAND | wx.ALL, 5)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.preview_button = wx.Button(panel, label=_("Preview Voice"))
        self.preview_button.Bind(wx.EVT_BUTTON, self.OnPreview)
        self.preview_button.Disable()
        button_sizer.Add(self.preview_button, 0, wx.ALL, 5)

        self.add_button = wx.Button(panel, label=_("Add to My Voices"))
        self.add_button.Bind(wx.EVT_BUTTON, self.OnAddVoice)
        self.add_button.Disable()
        button_sizer.Add(self.add_button, 0, wx.ALL, 5)

        self.refresh_button = wx.Button(panel, label=_("Refresh"))
        self.refresh_button.Bind(wx.EVT_BUTTON, self.OnRefresh)
        button_sizer.Add(self.refresh_button, 0, wx.ALL, 5)

        self.close_button = wx.Button(panel, label=_("Close"))
        self.close_button.Bind(wx.EVT_BUTTON, self.OnClose)
        button_sizer.Add(self.close_button, 0, wx.ALL, 5)

        vbox.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        panel.SetSizer(vbox)

        # Bind selection event
        self.voice_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.OnVoiceSelected)

        # Load voices
        self.LoadVoices()

    def LoadVoices(self):
        """Load shared voices from ElevenLabs Voice Library"""
        try:
            self.voice_list.DeleteAllItems()
            self.voices = []

            # Get shared/public voices from ElevenLabs Voice Library
            # Note: This gets community-shared voices, not user's personal voices
            try:
                # Try to get shared voices (Voice Library)
                response = self.client.voices.get_shared_voices()

                if hasattr(response, 'voices'):
                    voices_list = response.voices
                else:
                    # If response is already a list
                    voices_list = response

                for voice in voices_list:
                    self.voices.append(voice)
                    self.AddVoiceToList(voice)

                if not self.voices:
                    wx.MessageBox(_("No shared voices found in ElevenLabs Voice Library."),
                                _("Information"), wx.OK | wx.ICON_INFORMATION)

            except AttributeError:
                # Fallback: If shared voices API not available, use all voices
                wx.MessageBox(_("Shared Voice Library API not available.\nShowing all available voices instead."),
                            _("Information"), wx.OK | wx.ICON_INFORMATION)

                response = self.client.voices.get_all()
                for voice in response.voices:
                    self.voices.append(voice)
                    self.AddVoiceToList(voice)

        except Exception as e:
            wx.MessageBox(_(f"Error loading voices: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def AddVoiceToList(self, voice):
        """Add a voice to the list control"""
        index = self.voice_list.InsertItem(self.voice_list.GetItemCount(), voice.name)

        # Category
        category = getattr(voice, 'category', 'Unknown')
        self.voice_list.SetItem(index, 1, category)

        # Labels (gender, age, accent, use_case)
        labels = getattr(voice, 'labels', {})
        gender = labels.get('gender', '')
        age = labels.get('age', '')
        accent = labels.get('accent', '')
        use_case = labels.get('use case', '')

        self.voice_list.SetItem(index, 2, gender)
        self.voice_list.SetItem(index, 3, age)
        self.voice_list.SetItem(index, 4, accent)
        self.voice_list.SetItem(index, 5, use_case)

    def OnSearch(self, event):
        """Filter voices by search text"""
        search_text = self.search_ctrl.GetValue().lower()

        self.voice_list.DeleteAllItems()

        for voice in self.voices:
            if search_text in voice.name.lower():
                # Also apply category filter
                if self.FilterVoice(voice):
                    self.AddVoiceToList(voice)

    def OnFilter(self, event):
        """Filter voices by category and language"""
        self.voice_list.DeleteAllItems()

        search_text = self.search_ctrl.GetValue().lower()

        for voice in self.voices:
            if search_text and search_text not in voice.name.lower():
                continue

            if self.FilterVoice(voice):
                self.AddVoiceToList(voice)

    def FilterVoice(self, voice):
        """Check if voice matches current filters"""
        # Category filter
        category_idx = self.category_choice.GetSelection()
        if category_idx > 0:
            category_map = {
                1: 'premade',
                2: 'cloned',
                3: 'generated',
                4: 'professional'
            }
            required_category = category_map.get(category_idx, '')
            voice_category = getattr(voice, 'category', '').lower()
            if voice_category != required_category:
                return False

        # Language filter
        language_idx = self.language_choice.GetSelection()
        if language_idx > 0:
            required_language = self.language_choice.GetStringSelection().lower()
            labels = getattr(voice, 'labels', {})
            accent = labels.get('accent', '').lower()
            if required_language not in accent:
                return False

        return True

    def OnVoiceSelected(self, event):
        """Display voice details when selected"""
        selected = self.voice_list.GetFirstSelected()
        if selected == -1:
            return

        voice = self.voices[selected]

        details = []
        details.append(f"Name: {voice.name}")

        if hasattr(voice, 'voice_id'):
            details.append(f"Voice ID: {voice.voice_id}")

        if hasattr(voice, 'public_owner_id'):
            details.append(f"Creator: {voice.public_owner_id}")

        if hasattr(voice, 'category'):
            details.append(f"Category: {voice.category}")

        if hasattr(voice, 'description') and voice.description:
            details.append(f"Description: {voice.description}")

        if hasattr(voice, 'use_case') and voice.use_case:
            details.append(f"Use Case: {voice.use_case}")

        if hasattr(voice, 'labels') and voice.labels:
            details.append("\nLabels:")
            for key, value in voice.labels.items():
                details.append(f"  {key}: {value}")

        self.details_text.SetValue("\n".join(details))

        # Enable preview and add buttons for shared voices
        self.preview_button.Enable()
        self.add_button.Enable()

    def OnPreview(self, event):
        """Preview the selected voice"""
        selected = self.voice_list.GetFirstSelected()
        if selected == -1:
            return

        try:
            voice = self.voices[selected]

            # Generate preview text
            preview_text = _("Hello, this is a preview of this voice. How do you like it?")

            # Generate audio
            audio = self.parent.client.text_to_speech.convert(
                text=preview_text,
                voice_id=voice.voice_id,
                model_id="eleven_multilingual_v2",
                output_format="mp3_44100_128"
            )

            # Save to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                for chunk in audio:
                    tmp.write(chunk)
                temp_path = tmp.name

            # Play with configured player
            config = configparser.ConfigParser()
            settings_path = os.path.expandvars(r'%appdata%\Titosoft\Titan\Additional apps\elevenlabsclient.ini')
            config.read(settings_path)
            playback_mode = config.get('Settings', 'playback_mode', fallback='mpv')

            if playback_mode == 'mpv':
                subprocess.Popen(['mpv', '--force-window', '--', temp_path])
            else:
                import tplayer
                player = tplayer.TPlayer(temp_path)
                player.run()

        except Exception as e:
            wx.MessageBox(_(f"Error previewing voice: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnAddVoice(self, event):
        """Add selected shared voice to user's voice library"""
        selected = self.voice_list.GetFirstSelected()
        if selected == -1:
            return

        try:
            voice = self.voices[selected]

            # Get the public_user_id and voice_id
            if not hasattr(voice, 'public_owner_id'):
                wx.MessageBox(_("This voice cannot be added (missing owner information)."),
                            _("Error"), wx.OK | wx.ICON_ERROR)
                return

            # Confirm addition
            msg = _(f"Add '{voice.name}' to your voice library?\n\n"
                   f"This will make it available in your voice selection.")

            dlg = wx.MessageDialog(self, msg, _("Confirm Add Voice"),
                                  wx.YES_NO | wx.ICON_QUESTION)
            if dlg.ShowModal() != wx.ID_YES:
                dlg.Destroy()
                return
            dlg.Destroy()

            # Add the shared voice to user's library
            try:
                # Use the add_sharing_voice or similar method
                added_voice = self.client.voices.add(
                    public_user_id=voice.public_owner_id,
                    voice_id=voice.voice_id,
                    new_name=voice.name  # Can optionally rename
                )

                wx.MessageBox(_(f"Voice '{voice.name}' successfully added to your library!"),
                            _("Success"), wx.OK | wx.ICON_INFORMATION)

                # Refresh parent's voice list
                self.parent.voices = self.parent.get_available_voices()
                self.parent.voice_choice.Clear()
                for v in self.parent.voices:
                    self.parent.voice_choice.Append(v['name'])

            except AttributeError:
                # If the add method doesn't work as expected, try alternative
                wx.MessageBox(_("Unable to add voice. The API method may have changed.\n\n"
                              "Try using the voice ID directly in generation."),
                            _("Error"), wx.OK | wx.ICON_ERROR)

        except Exception as e:
            wx.MessageBox(_(f"Error adding voice: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnRefresh(self, event):
        """Refresh voice list"""
        self.LoadVoices()
        wx.MessageBox(_("Voice library refreshed"), _("Success"), wx.OK | wx.ICON_INFORMATION)

    def OnClose(self, event):
        """Close dialog"""
        self.EndModal(wx.ID_OK)

