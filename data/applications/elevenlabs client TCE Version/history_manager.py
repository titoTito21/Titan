import wx
import os
import tempfile
import shutil
from translation import _
from datetime import datetime
import subprocess
import configparser
from api_key_helper import check_api_key

class HistoryDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("History Manager"), size=(800, 600))

        self.parent = parent
        self.client = parent.client
        self.history_items = []

        # Check if API key is configured
        if not check_api_key(parent):
            self.Destroy()
            return

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # History list
        history_label = wx.StaticText(panel, label=_("Generation History:"))
        vbox.Add(history_label, 0, wx.ALL, 5)

        # Create list control with columns
        self.history_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.history_list.AppendColumn(_("Date"), width=150)
        self.history_list.AppendColumn(_("Text"), width=400)
        self.history_list.AppendColumn(_("Voice"), width=150)
        self.history_list.AppendColumn(_("Characters"), width=100)
        vbox.Add(self.history_list, 1, wx.EXPAND | wx.ALL, 5)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.refresh_button = wx.Button(panel, label=_("Refresh"))
        self.refresh_button.Bind(wx.EVT_BUTTON, self.OnRefresh)
        button_sizer.Add(self.refresh_button, 0, wx.ALL, 5)

        self.play_button = wx.Button(panel, label=_("Play"))
        self.play_button.Bind(wx.EVT_BUTTON, self.OnPlay)
        self.play_button.Disable()
        button_sizer.Add(self.play_button, 0, wx.ALL, 5)

        self.download_button = wx.Button(panel, label=_("Download"))
        self.download_button.Bind(wx.EVT_BUTTON, self.OnDownload)
        self.download_button.Disable()
        button_sizer.Add(self.download_button, 0, wx.ALL, 5)

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
        self.history_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.OnItemSelected)

        # Load history
        self.LoadHistory()

    def LoadHistory(self):
        """Load generation history from ElevenLabs API"""
        try:
            self.history_list.DeleteAllItems()
            self.history_items = []

            # Get history from API - correct method is get() not get_all()
            try:
                history = self.client.history.get()
            except AttributeError:
                # Fallback if history API not available
                wx.MessageBox(_("History API not available."), _("Information"), wx.OK | wx.ICON_INFORMATION)
                return

            # Handle different response formats
            if hasattr(history, 'history'):
                history_items = history.history
            else:
                history_items = history if isinstance(history, list) else []

            for item in history_items:
                # Add to list
                index = self.history_list.InsertItem(self.history_list.GetItemCount(),
                                                      datetime.fromtimestamp(item.date_unix).strftime("%Y-%m-%d %H:%M:%S"))
                self.history_list.SetItem(index, 1, item.text[:50] + "..." if len(item.text) > 50 else item.text)
                self.history_list.SetItem(index, 2, item.voice_name)
                self.history_list.SetItem(index, 3, str(item.character_count_change_from))

                # Store full item
                self.history_items.append(item)

        except Exception as e:
            wx.MessageBox(_(f"Error loading history: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnRefresh(self, event):
        """Refresh history list"""
        self.LoadHistory()
        wx.MessageBox(_("History refreshed"), _("Success"), wx.OK | wx.ICON_INFORMATION)

    def OnItemSelected(self, event):
        """Enable buttons when item is selected"""
        self.play_button.Enable()
        self.download_button.Enable()
        self.delete_button.Enable()

    def OnPlay(self, event):
        """Play selected history item"""
        selected = self.history_list.GetFirstSelected()
        if selected == -1:
            return

        try:
            item = self.history_items[selected]

            # Download audio
            audio = self.client.history.get_audio(history_item_id=item.history_item_id)

            # Save to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                tmp.write(audio)
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
            wx.MessageBox(_(f"Error playing audio: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnDownload(self, event):
        """Download selected history item"""
        selected = self.history_list.GetFirstSelected()
        if selected == -1:
            return

        try:
            item = self.history_items[selected]

            # Ask where to save
            with wx.FileDialog(self, _("Save audio file"), wildcard=_("MP3 files (*.mp3)|*.mp3"),
                               style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fileDialog:
                if fileDialog.ShowModal() == wx.ID_CANCEL:
                    return
                save_path = fileDialog.GetPath()

            # Download audio
            audio = self.client.history.get_audio(history_item_id=item.history_item_id)

            # Save to file
            with open(save_path, 'wb') as f:
                f.write(audio)

            wx.MessageBox(_("Audio saved successfully"), _("Success"), wx.OK | wx.ICON_INFORMATION)

        except Exception as e:
            wx.MessageBox(_(f"Error downloading audio: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnDelete(self, event):
        """Delete selected history item"""
        selected = self.history_list.GetFirstSelected()
        if selected == -1:
            return

        # Confirm deletion
        if wx.MessageBox(_("Are you sure you want to delete this history item?"),
                        _("Confirm Delete"), wx.YES_NO | wx.ICON_QUESTION) != wx.YES:
            return

        try:
            item = self.history_items[selected]

            # Delete from API
            self.client.history.delete(history_item_id=item.history_item_id)

            # Refresh list
            self.LoadHistory()

            wx.MessageBox(_("History item deleted successfully"), _("Success"), wx.OK | wx.ICON_INFORMATION)

        except Exception as e:
            wx.MessageBox(_(f"Error deleting history item: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnClose(self, event):
        """Close dialog"""
        self.EndModal(wx.ID_OK)
