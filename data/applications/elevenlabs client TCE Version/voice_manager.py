import wx
import os
from translation import _

class VoiceManagerDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Voice Manager"), size=(800, 600))

        self.parent = parent
        self.client = parent.client
        self.voices = []

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Voice list
        voice_label = wx.StaticText(panel, label=_("Your Voices:"))
        vbox.Add(voice_label, 0, wx.ALL, 5)

        # Create list control with columns
        self.voice_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.voice_list.AppendColumn(_("Name"), width=200)
        self.voice_list.AppendColumn(_("Category"), width=150)
        self.voice_list.AppendColumn(_("Description"), width=300)
        self.voice_list.AppendColumn(_("Labels"), width=150)
        vbox.Add(self.voice_list, 1, wx.EXPAND | wx.ALL, 5)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.refresh_button = wx.Button(panel, label=_("Refresh"))
        self.refresh_button.Bind(wx.EVT_BUTTON, self.OnRefresh)
        button_sizer.Add(self.refresh_button, 0, wx.ALL, 5)

        self.view_button = wx.Button(panel, label=_("View Details"))
        self.view_button.Bind(wx.EVT_BUTTON, self.OnViewDetails)
        self.view_button.Disable()
        button_sizer.Add(self.view_button, 0, wx.ALL, 5)

        self.edit_button = wx.Button(panel, label=_("Edit Voice"))
        self.edit_button.Bind(wx.EVT_BUTTON, self.OnEditVoice)
        self.edit_button.Disable()
        button_sizer.Add(self.edit_button, 0, wx.ALL, 5)

        self.settings_button = wx.Button(panel, label=_("Voice Settings"))
        self.settings_button.Bind(wx.EVT_BUTTON, self.OnVoiceSettings)
        self.settings_button.Disable()
        button_sizer.Add(self.settings_button, 0, wx.ALL, 5)

        self.delete_button = wx.Button(panel, label=_("Delete"))
        self.delete_button.Bind(wx.EVT_BUTTON, self.OnDelete)
        self.delete_button.Disable()
        button_sizer.Add(self.delete_button, 0, wx.ALL, 5)

        self.close_button = wx.Button(panel, label=_("Close"))
        self.close_button.Bind(wx.EVT_BUTTON, self.OnClose)
        button_sizer.Add(self.close_button, 0, wx.ALL, 5)

        vbox.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        panel.SetSizer(vbox)

        # Bind selection event
        self.voice_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.OnItemSelected)

        # Load voices
        self.LoadVoices()

    def LoadVoices(self):
        """Load voices from ElevenLabs API"""
        try:
            self.voice_list.DeleteAllItems()
            self.voices = []

            # Get voices from API
            response = self.client.voices.get_all()

            for voice in response.voices:
                # Add to list
                index = self.voice_list.InsertItem(self.voice_list.GetItemCount(), voice.name)
                self.voice_list.SetItem(index, 1, voice.category if hasattr(voice, 'category') else "")
                self.voice_list.SetItem(index, 2, voice.description[:50] if hasattr(voice, 'description') and voice.description else "")
                labels = ", ".join([str(k) for k in voice.labels.keys()]) if hasattr(voice, 'labels') and voice.labels else ""
                self.voice_list.SetItem(index, 3, labels)

                # Store full voice
                self.voices.append(voice)

        except Exception as e:
            wx.MessageBox(_(f"Error loading voices: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnRefresh(self, event):
        """Refresh voice list"""
        self.LoadVoices()
        wx.MessageBox(_("Voice list refreshed"), _("Success"), wx.OK | wx.ICON_INFORMATION)

    def OnItemSelected(self, event):
        """Enable buttons when item is selected"""
        selected = self.voice_list.GetFirstSelected()
        if selected != -1:
            voice = self.voices[selected]
            # Only enable edit/delete for custom voices (not premade)
            if hasattr(voice, 'category') and voice.category != 'premade':
                self.edit_button.Enable()
                self.delete_button.Enable()
            else:
                self.edit_button.Disable()
                self.delete_button.Disable()

            self.view_button.Enable()
            self.settings_button.Enable()

    def OnViewDetails(self, event):
        """View detailed information about selected voice"""
        selected = self.voice_list.GetFirstSelected()
        if selected == -1:
            return

        try:
            voice = self.voices[selected]

            # Get detailed voice info
            voice_info = self.client.voices.get(voice_id=voice.voice_id)

            # Create details dialog
            details = [
                f"Name: {voice_info.name}",
                f"Voice ID: {voice_info.voice_id}",
                f"Category: {voice_info.category if hasattr(voice_info, 'category') else 'N/A'}",
                f"Description: {voice_info.description if hasattr(voice_info, 'description') else 'N/A'}",
                "",
                "Labels:"
            ]

            if hasattr(voice_info, 'labels') and voice_info.labels:
                for key, value in voice_info.labels.items():
                    details.append(f"  {key}: {value}")

            if hasattr(voice_info, 'settings'):
                details.append("")
                details.append("Settings:")
                details.append(f"  Stability: {voice_info.settings.stability}")
                details.append(f"  Similarity Boost: {voice_info.settings.similarity_boost}")
                if hasattr(voice_info.settings, 'style'):
                    details.append(f"  Style: {voice_info.settings.style}")
                if hasattr(voice_info.settings, 'use_speaker_boost'):
                    details.append(f"  Speaker Boost: {voice_info.settings.use_speaker_boost}")

            details_text = "\n".join(details)

            dlg = wx.MessageDialog(self, details_text, _("Voice Details"), wx.OK)
            dlg.ShowModal()
            dlg.Destroy()

        except Exception as e:
            wx.MessageBox(_(f"Error getting voice details: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnEditVoice(self, event):
        """Edit selected voice"""
        selected = self.voice_list.GetFirstSelected()
        if selected == -1:
            return

        try:
            voice = self.voices[selected]

            # Open edit dialog
            dlg = VoiceEditDialog(self, voice)
            if dlg.ShowModal() == wx.ID_OK:
                # Update voice
                name = dlg.name_ctrl.GetValue()
                description = dlg.description_ctrl.GetValue()

                self.client.voices.edit(
                    voice_id=voice.voice_id,
                    name=name,
                    description=description
                )

                # Refresh list
                self.LoadVoices()
                wx.MessageBox(_("Voice updated successfully"), _("Success"), wx.OK | wx.ICON_INFORMATION)

            dlg.Destroy()

        except Exception as e:
            wx.MessageBox(_(f"Error editing voice: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnVoiceSettings(self, event):
        """Edit voice settings"""
        selected = self.voice_list.GetFirstSelected()
        if selected == -1:
            return

        try:
            voice = self.voices[selected]

            # Get current settings
            voice_info = self.client.voices.get(voice_id=voice.voice_id)

            # Open settings dialog
            dlg = VoiceSettingsDialog(self, voice_info)
            if dlg.ShowModal() == wx.ID_OK:
                # Update voice settings
                stability = dlg.stability_slider.GetValue() / 100.0
                similarity_boost = dlg.similarity_slider.GetValue() / 100.0
                style = dlg.style_slider.GetValue() / 100.0 if hasattr(dlg, 'style_slider') else 0.0
                use_speaker_boost = dlg.speaker_boost_check.GetValue() if hasattr(dlg, 'speaker_boost_check') else True

                self.client.voices.edit_settings(
                    voice_id=voice.voice_id,
                    stability=stability,
                    similarity_boost=similarity_boost,
                    style=style,
                    use_speaker_boost=use_speaker_boost
                )

                wx.MessageBox(_("Voice settings updated successfully"), _("Success"), wx.OK | wx.ICON_INFORMATION)

            dlg.Destroy()

        except Exception as e:
            wx.MessageBox(_(f"Error updating voice settings: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnDelete(self, event):
        """Delete selected voice"""
        selected = self.voice_list.GetFirstSelected()
        if selected == -1:
            return

        # Confirm deletion
        if wx.MessageBox(_("Are you sure you want to delete this voice?"),
                        _("Confirm Delete"), wx.YES_NO | wx.ICON_QUESTION) != wx.YES:
            return

        try:
            voice = self.voices[selected]

            # Delete voice
            self.client.voices.delete(voice_id=voice.voice_id)

            # Refresh list
            self.LoadVoices()

            # Refresh parent voice list
            self.parent.voices = self.parent.get_available_voices()
            self.parent.voice_choice.Clear()
            for v in self.parent.voices:
                self.parent.voice_choice.Append(v['name'])

            wx.MessageBox(_("Voice deleted successfully"), _("Success"), wx.OK | wx.ICON_INFORMATION)

        except Exception as e:
            wx.MessageBox(_(f"Error deleting voice: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnClose(self, event):
        """Close dialog"""
        self.EndModal(wx.ID_OK)


class VoiceEditDialog(wx.Dialog):
    def __init__(self, parent, voice):
        super().__init__(parent, title=_("Edit Voice"), size=(400, 250))

        self.voice = voice

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Name
        name_label = wx.StaticText(panel, label=_("Name:"))
        vbox.Add(name_label, 0, wx.ALL, 5)
        self.name_ctrl = wx.TextCtrl(panel, value=voice.name)
        vbox.Add(self.name_ctrl, 0, wx.EXPAND | wx.ALL, 5)

        # Description
        desc_label = wx.StaticText(panel, label=_("Description:"))
        vbox.Add(desc_label, 0, wx.ALL, 5)
        self.description_ctrl = wx.TextCtrl(panel, value=voice.description if hasattr(voice, 'description') and voice.description else "", style=wx.TE_MULTILINE)
        vbox.Add(self.description_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        ok_button = wx.Button(panel, wx.ID_OK, _("OK"))
        cancel_button = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        button_sizer.Add(ok_button, 0, wx.ALL, 5)
        button_sizer.Add(cancel_button, 0, wx.ALL, 5)

        vbox.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        panel.SetSizer(vbox)


class VoiceSettingsDialog(wx.Dialog):
    def __init__(self, parent, voice):
        super().__init__(parent, title=_("Voice Settings"), size=(400, 400))

        self.voice = voice

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Get current settings
        if hasattr(voice, 'settings'):
            stability = int(voice.settings.stability * 100)
            similarity_boost = int(voice.settings.similarity_boost * 100)
            style = int(voice.settings.style * 100) if hasattr(voice.settings, 'style') else 0
            use_speaker_boost = voice.settings.use_speaker_boost if hasattr(voice.settings, 'use_speaker_boost') else True
        else:
            stability = 50
            similarity_boost = 75
            style = 0
            use_speaker_boost = True

        # Stability
        stability_label = wx.StaticText(panel, label=_("Stability (0-100):"))
        vbox.Add(stability_label, 0, wx.ALL, 5)
        self.stability_slider = wx.Slider(panel, value=stability, minValue=0, maxValue=100, style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        vbox.Add(self.stability_slider, 0, wx.EXPAND | wx.ALL, 5)

        # Similarity Boost
        similarity_label = wx.StaticText(panel, label=_("Similarity Boost (0-100):"))
        vbox.Add(similarity_label, 0, wx.ALL, 5)
        self.similarity_slider = wx.Slider(panel, value=similarity_boost, minValue=0, maxValue=100, style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        vbox.Add(self.similarity_slider, 0, wx.EXPAND | wx.ALL, 5)

        # Style
        style_label = wx.StaticText(panel, label=_("Style (0-100):"))
        vbox.Add(style_label, 0, wx.ALL, 5)
        self.style_slider = wx.Slider(panel, value=style, minValue=0, maxValue=100, style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        vbox.Add(self.style_slider, 0, wx.EXPAND | wx.ALL, 5)

        # Speaker Boost
        self.speaker_boost_check = wx.CheckBox(panel, label=_("Use Speaker Boost"))
        self.speaker_boost_check.SetValue(use_speaker_boost)
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
        cancel_button = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        button_sizer.Add(ok_button, 0, wx.ALL, 5)
        button_sizer.Add(cancel_button, 0, wx.ALL, 5)

        vbox.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        panel.SetSizer(vbox)
