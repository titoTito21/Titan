import wx
import os
import tempfile
import subprocess
import configparser
import threading
from translation import _

class SoundEffectsDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Sound Effects Generation"), size=(600, 400))

        self.parent = parent
        self.client = parent.client
        self.output_file = None

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Instructions
        info_text = wx.StaticText(panel, label=_(
            "Generate sound effects using AI.\n"
            "Describe the sound you want to create."
        ))
        vbox.Add(info_text, 0, wx.ALL, 10)

        # Text input
        text_label = wx.StaticText(panel, label=_("Sound Description:"))
        vbox.Add(text_label, 0, wx.ALL, 5)

        self.text_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE)
        self.text_ctrl.SetValue(_("A dog barking"))
        vbox.Add(self.text_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        # Duration
        duration_label = wx.StaticText(panel, label=_("Duration (seconds, 0.5-22):"))
        vbox.Add(duration_label, 0, wx.ALL, 5)

        self.duration_spin = wx.SpinCtrlDouble(panel, value="3.0", min=0.5, max=22.0, inc=0.5)
        vbox.Add(self.duration_spin, 0, wx.EXPAND | wx.ALL, 5)

        # Prompt influence
        influence_label = wx.StaticText(panel, label=_("Prompt Influence (0.0-1.0):"))
        vbox.Add(influence_label, 0, wx.ALL, 5)

        self.influence_slider = wx.Slider(panel, value=30, minValue=0, maxValue=100,
                                          style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        vbox.Add(self.influence_slider, 0, wx.EXPAND | wx.ALL, 5)

        # Progress bar
        self.progress_bar = wx.Gauge(panel, range=100, style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)
        vbox.Add(self.progress_bar, 0, wx.EXPAND | wx.ALL, 10)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.generate_button = wx.Button(panel, label=_("Generate"))
        self.generate_button.Bind(wx.EVT_BUTTON, self.OnGenerate)
        button_sizer.Add(self.generate_button, 0, wx.ALL, 5)

        self.play_button = wx.Button(panel, label=_("Play"))
        self.play_button.Bind(wx.EVT_BUTTON, self.OnPlay)
        self.play_button.Disable()
        button_sizer.Add(self.play_button, 0, wx.ALL, 5)

        self.save_button = wx.Button(panel, label=_("Save"))
        self.save_button.Bind(wx.EVT_BUTTON, self.OnSave)
        self.save_button.Disable()
        button_sizer.Add(self.save_button, 0, wx.ALL, 5)

        self.close_button = wx.Button(panel, label=_("Close"))
        self.close_button.Bind(wx.EVT_BUTTON, self.OnClose)
        button_sizer.Add(self.close_button, 0, wx.ALL, 5)

        vbox.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        panel.SetSizer(vbox)

    def OnGenerate(self, event):
        """Generate sound effect"""
        text = self.text_ctrl.GetValue().strip()
        if not text:
            wx.MessageBox(_("Please enter a sound description"), _("Error"), wx.OK | wx.ICON_ERROR)
            return

        self.generate_button.Disable()
        self.generate_button.SetLabel(_("Generating..."))
        threading.Thread(target=self.GenerateSound).start()

    def GenerateSound(self):
        """Perform the actual sound generation"""
        try:
            text = self.text_ctrl.GetValue()
            duration = self.duration_spin.GetValue()
            prompt_influence = self.influence_slider.GetValue() / 100.0

            # Update progress
            wx.CallAfter(self.progress_bar.SetValue, 25)

            # Generate sound using API
            result = self.client.text_to_sound_effects.convert(
                text=text,
                duration_seconds=duration,
                prompt_influence=prompt_influence
            )

            wx.CallAfter(self.progress_bar.SetValue, 75)

            # Save result to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                for chunk in result:
                    tmp.write(chunk)
                self.output_file = tmp.name

            wx.CallAfter(self.progress_bar.SetValue, 100)
            wx.CallAfter(self.OnGenerationComplete)

        except Exception as e:
            wx.CallAfter(wx.MessageBox, _(f"Error during generation: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)
            wx.CallAfter(self.OnGenerationComplete)

    def OnGenerationComplete(self):
        """Called when generation is complete"""
        self.generate_button.Enable()
        self.generate_button.SetLabel(_("Generate"))

        if self.output_file:
            self.play_button.Enable()
            self.save_button.Enable()
            wx.MessageBox(_("Sound effect generated successfully"), _("Success"), wx.OK | wx.ICON_INFORMATION)

    def OnPlay(self, event):
        """Play the generated sound"""
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
        """Save the generated sound"""
        if not self.output_file:
            return

        try:
            with wx.FileDialog(self, _("Save sound effect"),
                              wildcard=_("MP3 files (*.mp3)|*.mp3"),
                              style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fileDialog:
                if fileDialog.ShowModal() == wx.ID_CANCEL:
                    return

                save_path = fileDialog.GetPath()

                # Copy temp file to destination
                import shutil
                shutil.copy(self.output_file, save_path)

                wx.MessageBox(_("Sound effect saved successfully"), _("Success"), wx.OK | wx.ICON_INFORMATION)

        except Exception as e:
            wx.MessageBox(_(f"Error saving sound: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnClose(self, event):
        """Close dialog"""
        # Clean up temp file
        if self.output_file and os.path.exists(self.output_file):
            try:
                os.remove(self.output_file)
            except:
                pass

        self.EndModal(wx.ID_OK)
