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
from cache_manager import GenerationCache

class Generator:
    def __init__(self, frame):
        self.frame = frame
        self.temp_filename = None
        # Default voice settings
        self.stability = 0.5
        self.similarity_boost = 0.75
        self.style = 0.0
        self.use_speaker_boost = True
        # Cache manager
        self.cache = GenerationCache(max_items=10)
        # Last generation info for smart detection
        self.last_text = None
        self.last_voice_id = None

    def UpdateProgress(self, value):
        self.frame.progress_bar.SetValue(value)
        wx.Yield()

    def ShowErrorMessage(self, message):
        wx.MessageBox(message, _("Error"), wx.OK | wx.ICON_ERROR)

    def OnGenerate(self, event):
        """Generate audio with smart features"""
        text = self.frame.text_ctrl.GetValue().strip()
        selected_index = self.frame.voice_choice.GetSelection()

        if not text:
            wx.MessageBox(_("Please enter text to generate."), _("Error"), wx.OK | wx.ICON_ERROR)
            return

        # Check if voices are loaded
        if not self.frame.voices or len(self.frame.voices) == 0:
            wx.MessageBox(
                _("No voices available.\n\nPlease check:\n1. Your API key is configured\n2. You have voices in your ElevenLabs account\n\nYou can add voices from: Voices → Voice Library"),
                _("No Voices Available"),
                wx.OK | wx.ICON_WARNING
            )
            return

        if selected_index == -1:
            wx.MessageBox(_("Please select a voice"), _("Error"), wx.OK | wx.ICON_ERROR)
            return

        # Safety check - make sure index is valid
        if selected_index >= len(self.frame.voices):
            wx.MessageBox(
                _("Invalid voice selection. Please refresh the voice list."),
                _("Error"),
                wx.OK | wx.ICON_ERROR
            )
            return

        selected_voice_id = self.frame.voices[selected_index]['id']
        selected_voice_name = self.frame.voices[selected_index]['name']
        model_id = self.frame.model_choice.GetStringSelection()

        # Character count
        char_count = len(text)

        # Feature 1: Check cache for exact match
        settings = {
            'stability': self.stability,
            'similarity_boost': self.similarity_boost,
            'style': self.style,
            'use_speaker_boost': self.use_speaker_boost
        }

        cached_audio = self.cache.get(text, selected_voice_id, model_id, settings)
        if cached_audio:
            dlg = wx.MessageDialog(
                self.frame,
                _("This exact generation already exists in cache.\n\nUse cached version (saves characters)?"),
                _("Cached Generation Found"),
                wx.YES_NO | wx.ICON_QUESTION
            )
            if dlg.ShowModal() == wx.ID_YES:
                # Use cached version
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                    tmp.write(cached_audio)
                    self.temp_filename = tmp.name
                self.frame.play_button.Enable()
                self.OnPlay(None)
                dlg.Destroy()
                return
            dlg.Destroy()

        # Feature 2: Check for similar/recent generations
        similar = self.cache.check_similar(text)
        if similar['found']:
            item = similar['item']
            msg = _(f"Similar text was generated recently:\n\n"
                   f"Text: {item['text']}...\n"
                   f"Voice: {item['voice_name']}\n"
                   f"Characters: {item['character_count']}\n\n"
                   f"Continue with new generation?")

            dlg = wx.MessageDialog(self.frame, msg, _("Similar Generation Detected"),
                                  wx.YES_NO | wx.ICON_WARNING)
            if dlg.ShowModal() == wx.ID_NO:
                dlg.Destroy()
                return
            dlg.Destroy()

        # Feature 3: Character count confirmation
        if char_count > 500:
            msg = _(f"This generation will use {char_count} characters.\n\n"
                   f"Continue?")
            dlg = wx.MessageDialog(self.frame, msg, _("Character Usage Confirmation"),
                                  wx.YES_NO | wx.ICON_QUESTION)
            if dlg.ShowModal() == wx.ID_NO:
                dlg.Destroy()
                return
            dlg.Destroy()

        # Feature 4: Preview option for long text
        if char_count > 200:
            msg = _(f"Generate preview first?\n\n"
                   f"Preview (first 150 chars): ~150 characters\n"
                   f"Full generation: {char_count} characters\n\n"
                   f"Preview helps test voice settings with minimal cost.")

            dlg = wx.MessageDialog(self.frame, msg, _("Preview Option"),
                                  wx.YES_NO_CANCEL | wx.ICON_QUESTION)
            dlg.SetYesNoCancelLabels(_("Preview"), _("Full Generation"), _("Cancel"))
            result = dlg.ShowModal()
            dlg.Destroy()

            if result == wx.ID_CANCEL:
                return
            elif result == wx.ID_YES:
                # Generate preview
                self.GeneratePreview(text[:150], selected_voice_id, selected_voice_name, model_id)
                return

        # Proceed with full generation
        self.frame.generate_button.Disable()
        self.frame.generate_button.SetLabel(_("Generating..."))
        self.frame.play_button.Disable()
        threading.Thread(target=self.GenerateAudio, args=(text, selected_voice_id, selected_voice_name, model_id, char_count)).start()

    def GeneratePreview(self, preview_text, voice_id, voice_name, model_id):
        """Generate preview of first portion of text"""
        self.frame.generate_button.Disable()
        self.frame.generate_button.SetLabel(_("Generating preview..."))
        self.frame.play_button.Disable()
        threading.Thread(target=self.GenerateAudio, args=(preview_text, voice_id, voice_name, model_id, len(preview_text), True)).start()

    def GenerateAudio(self, text, voice_id, voice_name, model_id, char_count, is_preview=False):
        try:
            wx.CallAfter(self.UpdateProgress, 10)

            # Prepare voice settings
            from elevenlabs import VoiceSettings
            voice_settings = VoiceSettings(
                stability=self.stability,
                similarity_boost=self.similarity_boost,
                style=self.style,
                use_speaker_boost=self.use_speaker_boost
            )

            wx.CallAfter(self.UpdateProgress, 25)

            # Generate audio
            audio_generator = self.frame.client.text_to_speech.convert(
                text=text,
                voice_id=voice_id,
                model_id=model_id,
                voice_settings=voice_settings,
                output_format="mp3_44100_128"
            )

            wx.CallAfter(self.UpdateProgress, 50)

            # Collect audio data
            audio_data = b''
            for chunk in audio_generator:
                audio_data += chunk

            wx.CallAfter(self.UpdateProgress, 75)

            # Save to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                tmp.write(audio_data)
                self.temp_filename = tmp.name

            wx.CallAfter(self.UpdateProgress, 90)

            # Add to cache (only if full generation, not preview)
            if not is_preview:
                settings = {
                    'stability': self.stability,
                    'similarity_boost': self.similarity_boost,
                    'style': self.style,
                    'use_speaker_boost': self.use_speaker_boost
                }
                self.cache.add(text, voice_id, voice_name, model_id, settings, audio_data)

                # Update last generation info
                self.last_text = text
                self.last_voice_id = voice_id

            wx.CallAfter(self.UpdateProgress, 100)

            if is_preview:
                wx.CallAfter(self.OnPreviewComplete, char_count)
            else:
                wx.CallAfter(self.OnGenerateComplete)

        except Exception as e:
            wx.CallAfter(self.ShowErrorMessage, _(f"Error generating audio: {str(e)}"))
            wx.CallAfter(self.OnGenerateComplete, is_preview)

    def OnPreviewComplete(self, char_count):
        """Called when preview generation is complete"""
        self.frame.generate_button.Enable()
        self.frame.generate_button.SetLabel(_("Generate"))

        if self.temp_filename:
            self.frame.play_button.Enable()
            self.OnPlay(None)

            # Ask if user wants full generation
            msg = _(f"Preview generated successfully!\n\n"
                   f"Generate full text?\n"
                   f"Full text: {char_count} characters")

            dlg = wx.MessageDialog(self.frame, msg, _("Preview Complete"),
                                  wx.YES_NO | wx.ICON_QUESTION)
            if dlg.ShowModal() == wx.ID_YES:
                # Trigger full generation
                wx.CallAfter(self.frame.generate_button.GetEventHandler().ProcessEvent,
                           wx.CommandEvent(wx.EVT_BUTTON.typeId, self.frame.generate_button.GetId()))
            dlg.Destroy()

    def OnGenerateComplete(self, is_preview=False):
        """Called when generation is complete"""
        self.frame.generate_button.Enable()
        self.frame.generate_button.SetLabel(_("Generate"))

        if self.temp_filename:
            self.frame.play_button.Enable()
            if not is_preview:
                self.OnPlay(None)

                # Show cache info
                cache_info = self.cache.get_cache_info()
                status_msg = _(f"Generation complete! ({cache_info['item_count']} items in cache)")
                wx.CallAfter(self.frame.SetStatusText, status_msg)

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
                self.ShowErrorMessage(_(f"Error playing audio: {str(e)}"))

    def play_with_tminiplayer(self):
        player = tplayer.TPlayer(self.temp_filename)
        player.run()

    def OnSave(self, event):
        if not self.temp_filename:
            return
        try:
            with wx.FileDialog(self.frame, _("Save audio file"), wildcard=_("MP3 files (*.mp3)|*.mp3"),
                               style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fileDialog:
                if fileDialog.ShowModal() == wx.ID_CANCEL:
                    return
                save_path = fileDialog.GetPath()
                shutil.copy(self.temp_filename, save_path)
            os.remove(self.temp_filename)
        except Exception as e:
            self.ShowErrorMessage(_(f"Error saving file: {str(e)}"))
