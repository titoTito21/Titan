# database.py

import wx
import requests
import os
import zipfile
import support_dialog
from clonegen import clone_and_notify
from translation import _

VOICE_DB_URL = "http://194.233.161.10/elevenDB/dblist.txt"
VOICE_ZIP_URL_TEMPLATE = "http://194.233.161.10/elevenDB/voicedb/{}.zip"

class VoiceDatabaseDialog(wx.Dialog):
    def __init__(self, parent):
        super(VoiceDatabaseDialog, self).__init__(parent, title=_("Baza danych głosów"), size=(400, 300))
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Download voice list from server
        try:
            response = requests.get(VOICE_DB_URL)
            response.raise_for_status()
            voices_data = response.text.splitlines()
            self.voices = {line.split('=')[0]: line.split('=')[1] for line in voices_data}
        except:
            wx.MessageBox(_("Nie można połączyć się z serwerem bazy danych głosów"), _("Błąd"), wx.OK | wx.ICON_ERROR)
            self.EndModal(wx.ID_CANCEL)
            return

        self.voice_listbox = wx.ListBox(self, choices=list(self.voices.keys()))
        vbox.Add(self.voice_listbox, 1, wx.EXPAND | wx.ALL, 10)

        self.description_ctrl = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY)
        vbox.Add(self.description_ctrl, 1, wx.EXPAND | wx.ALL, 10)

        self.download_button = wx.Button(self, label=_("Download"))
        self.download_button.Bind(wx.EVT_BUTTON, self.OnDownload)
        vbox.Add(self.download_button, 0, wx.EXPAND | wx.ALL, 10)

        self.Bind(wx.EVT_LISTBOX, self.OnVoiceSelected, self.voice_listbox)

        self.SetSizer(vbox)

    def OnVoiceSelected(self, event):
        selected_voice = self.voice_listbox.GetStringSelection()
        self.description_ctrl.SetValue(self.voices[selected_voice])

    def OnDownload(self, event):
        selected_voice = self.voice_listbox.GetStringSelection()
        if not selected_voice:
            wx.MessageBox(_("Proszę najpierw wybrać głos."), _("Błąd"), wx.OK | wx.ICON_ERROR)
            return

        zip_url = VOICE_ZIP_URL_TEMPLATE.format(selected_voice)

        # Download the ZIP file
        try:
            response = requests.get(zip_url, stream=True)
            response.raise_for_status()

            # Save the ZIP temporarily
            zip_path = os.path.join(os.getcwd(), f"{selected_voice}.zip")
            with open(zip_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # Extract the ZIP
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(selected_voice)

            os.remove(zip_path)

            # Ask if the user wants to clone
            dlg = wx.MessageDialog(self, _("Voice downloaded"), _("Do you want to clone this voice and add it to your elevenLabs voice library?"), wx.YES_NO | wx.ICON_QUESTION)
            if dlg.ShowModal() == wx.ID_YES:
                clone_and_notify(self, selected_voice, self.voices[selected_voice], selected_voice)

            dlg.Destroy()
            self.EndModal(wx.ID_OK)

        except:
            wx.MessageBox(_(f"Nie udało się pobrać i sklonować głosu: {selected_voice}"), _("Błąd"), wx.OK | wx.ICON_ERROR)

