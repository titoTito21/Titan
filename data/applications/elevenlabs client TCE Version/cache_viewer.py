import wx
import os
import subprocess
import configparser
from translation import _
from datetime import datetime

class CacheViewerDialog(wx.Dialog):
    def __init__(self, parent, cache_manager):
        super().__init__(parent, title=_("Generation Cache"), size=(800, 600))

        self.parent = parent
        self.cache = cache_manager

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Cache info
        cache_info = self.cache.get_cache_info()
        info_text = _(f"Cached Items: {cache_info['item_count']} / {cache_info['max_items']}  |  "
                     f"Size: {cache_info['total_size_mb']:.2f} MB")
        info_label = wx.StaticText(panel, label=info_text)
        vbox.Add(info_label, 0, wx.ALL, 5)

        # Cache list
        list_label = wx.StaticText(panel, label=_("Cached Generations:"))
        vbox.Add(list_label, 0, wx.ALL, 5)

        self.cache_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.cache_list.AppendColumn(_("Time"), width=150)
        self.cache_list.AppendColumn(_("Text Preview"), width=300)
        self.cache_list.AppendColumn(_("Voice"), width=120)
        self.cache_list.AppendColumn(_("Model"), width=150)
        self.cache_list.AppendColumn(_("Chars"), width=80)
        vbox.Add(self.cache_list, 1, wx.EXPAND | wx.ALL, 5)

        # Details
        details_label = wx.StaticText(panel, label=_("Details:"))
        vbox.Add(details_label, 0, wx.ALL, 5)

        self.details_text = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 100))
        vbox.Add(self.details_text, 0, wx.EXPAND | wx.ALL, 5)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.play_button = wx.Button(panel, label=_("Play"))
        self.play_button.Bind(wx.EVT_BUTTON, self.OnPlay)
        self.play_button.Disable()
        button_sizer.Add(self.play_button, 0, wx.ALL, 5)

        self.use_button = wx.Button(panel, label=_("Use This"))
        self.use_button.Bind(wx.EVT_BUTTON, self.OnUse)
        self.use_button.Disable()
        button_sizer.Add(self.use_button, 0, wx.ALL, 5)

        self.delete_button = wx.Button(panel, label=_("Delete"))
        self.delete_button.Bind(wx.EVT_BUTTON, self.OnDelete)
        self.delete_button.Disable()
        button_sizer.Add(self.delete_button, 0, wx.ALL, 5)

        self.clear_button = wx.Button(panel, label=_("Clear All"))
        self.clear_button.Bind(wx.EVT_BUTTON, self.OnClearAll)
        button_sizer.Add(self.clear_button, 0, wx.ALL, 5)

        self.close_button = wx.Button(panel, label=_("Close"))
        self.close_button.Bind(wx.EVT_BUTTON, self.OnClose)
        button_sizer.Add(self.close_button, 0, wx.ALL, 5)

        vbox.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        panel.SetSizer(vbox)

        # Bind selection event
        self.cache_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.OnItemSelected)

        # Load cache
        self.LoadCache()

    def LoadCache(self):
        """Load cache items into list"""
        try:
            self.cache_list.DeleteAllItems()
            self.cache_items = self.cache.get_recent(self.cache.max_items)

            for item in self.cache_items:
                # Parse timestamp
                try:
                    timestamp = datetime.fromisoformat(item['timestamp'])
                    time_str = timestamp.strftime("%Y-%m-%d %H:%M")
                except:
                    time_str = item['timestamp']

                index = self.cache_list.InsertItem(self.cache_list.GetItemCount(), time_str)
                self.cache_list.SetItem(index, 1, item['text'])
                self.cache_list.SetItem(index, 2, item['voice_name'])
                self.cache_list.SetItem(index, 3, item['model_id'])
                self.cache_list.SetItem(index, 4, str(item['character_count']))

        except Exception as e:
            wx.MessageBox(_(f"Error loading cache: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnItemSelected(self, event):
        """Display item details when selected"""
        selected = self.cache_list.GetFirstSelected()
        if selected == -1:
            return

        item = self.cache_items[selected]

        details = []
        details.append(f"Text Preview: {item['text']}")
        details.append(f"Voice: {item['voice_name']} ({item['voice_id']})")
        details.append(f"Model: {item['model_id']}")
        details.append(f"Characters: {item['character_count']}")
        details.append(f"")
        details.append(f"Settings:")
        details.append(f"  Stability: {item['settings'].get('stability', 0.5):.2f}")
        details.append(f"  Similarity Boost: {item['settings'].get('similarity_boost', 0.75):.2f}")
        details.append(f"  Style: {item['settings'].get('style', 0):.2f}")
        details.append(f"  Speaker Boost: {item['settings'].get('use_speaker_boost', True)}")
        details.append(f"")
        details.append(f"Generated: {item['timestamp']}")
        details.append(f"File: {os.path.basename(item['audio_path'])}")

        self.details_text.SetValue("\n".join(details))

        self.play_button.Enable()
        self.use_button.Enable()
        self.delete_button.Enable()

    def OnPlay(self, event):
        """Play selected cached audio"""
        selected = self.cache_list.GetFirstSelected()
        if selected == -1:
            return

        try:
            item = self.cache_items[selected]
            audio_path = item['audio_path']

            if not os.path.exists(audio_path):
                wx.MessageBox(_("Audio file not found in cache."), _("Error"), wx.OK | wx.ICON_ERROR)
                return

            # Play with configured player
            config = configparser.ConfigParser()
            settings_path = os.path.expandvars(r'%appdata%\Titosoft\Titan\Additional apps\elevenlabsclient.ini')
            config.read(settings_path)
            playback_mode = config.get('Settings', 'playback_mode', fallback='mpv')

            if playback_mode == 'mpv':
                subprocess.Popen(['mpv', '--force-window', '--', audio_path])
            else:
                import tplayer
                player = tplayer.TPlayer(audio_path)
                player.run()

        except Exception as e:
            wx.MessageBox(_(f"Error playing audio: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnUse(self, event):
        """Use selected cached audio as current generation"""
        selected = self.cache_list.GetFirstSelected()
        if selected == -1:
            return

        try:
            item = self.cache_items[selected]

            # Get cached audio
            audio_data = self.cache.get_by_key(item['key'])
            if not audio_data:
                wx.MessageBox(_("Could not retrieve cached audio."), _("Error"), wx.OK | wx.ICON_ERROR)
                return

            # Save to parent's temp file
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
                tmp.write(audio_data)
                self.parent.generator.temp_filename = tmp.name

            # Enable play button in parent
            self.parent.play_button.Enable()

            wx.MessageBox(_("Cached audio loaded! You can now play or save it."),
                         _("Success"), wx.OK | wx.ICON_INFORMATION)

            self.EndModal(wx.ID_OK)

        except Exception as e:
            wx.MessageBox(_(f"Error using cached audio: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnDelete(self, event):
        """Delete selected cache item"""
        selected = self.cache_list.GetFirstSelected()
        if selected == -1:
            return

        if wx.MessageBox(_("Delete this cached item?"), _("Confirm Delete"),
                        wx.YES_NO | wx.ICON_QUESTION) != wx.YES:
            return

        try:
            item = self.cache_items[selected]

            # Remove from cache
            if os.path.exists(item['audio_path']):
                os.remove(item['audio_path'])

            # Remove from index
            self.cache.cache_index.remove(item)
            self.cache._save_cache_index()

            # Reload list
            self.LoadCache()

            wx.MessageBox(_("Cache item deleted."), _("Success"), wx.OK | wx.ICON_INFORMATION)

        except Exception as e:
            wx.MessageBox(_(f"Error deleting cache item: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnClearAll(self, event):
        """Clear all cache"""
        if wx.MessageBox(_("Clear entire cache?\n\nThis cannot be undone."),
                        _("Confirm Clear"), wx.YES_NO | wx.ICON_WARNING) != wx.YES:
            return

        try:
            self.cache.clear()
            self.LoadCache()
            wx.MessageBox(_("Cache cleared."), _("Success"), wx.OK | wx.ICON_INFORMATION)

        except Exception as e:
            wx.MessageBox(_(f"Error clearing cache: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnClose(self, event):
        """Close dialog"""
        self.EndModal(wx.ID_OK)
