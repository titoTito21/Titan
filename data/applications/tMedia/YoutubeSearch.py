import wx
import yt_dlp
import webbrowser
from translation import _

class YoutubeSearchApp(wx.Frame):
    def __init__(self, parent, *args, **kwargs):
        super(YoutubeSearchApp, self).__init__(parent, *args, **kwargs)

        self.SetTitle(_("YouTube Search"))
        self.SetSize((600, 400))
        panel = wx.Panel(self)

        vbox = wx.BoxSizer(wx.VERTICAL)

        self.search_field = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        vbox.Add(self.search_field, flag=wx.EXPAND | wx.ALL, border=10)
        self.search_field.Bind(wx.EVT_TEXT_ENTER, self.on_search)

        self.search_button = wx.Button(panel, label=_("Search"))
        vbox.Add(self.search_button, flag=wx.ALL, border=10)
        self.search_button.Bind(wx.EVT_BUTTON, self.on_search)

        self.results_list = wx.ListBox(panel)
        vbox.Add(self.results_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)
        self.results_list.Bind(wx.EVT_LISTBOX_DCLICK, self._show_selection_context_menu)
        self.results_list.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)
        self.results_list.Bind(wx.EVT_RIGHT_DOWN, self.on_right_click)

        panel.SetSizer(vbox)

        self.query = None
        self.videos = []
        
        # Simple cache for search results
        self.search_cache = {}

    def on_search(self, event):
        self.GetParent().play_sound('enter')
        query = self.search_field.GetValue().strip()
        if query:
            self.query = query
            
            # Check cache first
            if query in self.search_cache:
                self.GetParent().play_sound('ding')
                self.videos = self.search_cache[query]
                self.display_cached_results(query)
            else:
                self.videos = []
                self.search_videos(query)

    def display_cached_results(self, query):
        """Display cached search results quickly"""
        self.results_list.Clear()
        
        if self.videos:
            for video in self.videos:
                title = video.get('title', 'Unknown Title')
                duration = video.get('duration_string', '')
                uploader = video.get('uploader', '')
                
                # Format display string with duration and uploader info
                display_text = title
                if duration:
                    display_text += f" [{duration}]"
                if uploader:
                    display_text += f" - {uploader}"
                    
                self.results_list.Append(display_text)
            
            result_count = len(self.videos)
            self.GetParent().speak_message(_("Found %d cached results for: %s") % (result_count, query))
        else:
            self.GetParent().speak_message(_("No cached results found"))

    def search_videos(self, query):
        self.results_list.Clear()
        self.GetParent().play_sound('loading')

        # Optimized yt-dlp options for faster search with anti-bot measures
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,  # Faster extraction for search results
            'flat_playlist': True,  # Optimization for speed
            'no_check_certificate': True,  # Skip certificate checks for speed
            'geo_bypass': True,  # Bypass geo-restrictions
            'ignoreerrors': True,  # Continue on errors
            'socket_timeout': 10,  # Prevent hanging
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'referer': 'https://www.youtube.com/',
            'headers': {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            },
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Search for 25 results for better selection, sorted by relevance
                result = ydl.extract_info(f"ytsearch25:{query}", download=False)
                
                if result and 'entries' in result:
                    self.videos = [video for video in result['entries'] if video]  # Filter out None entries
                    
                    if self.videos:
                        for video in self.videos:
                            title = video.get('title', 'Unknown Title')
                            duration = video.get('duration_string', '')
                            uploader = video.get('uploader', '')
                            
                            # Format display string with duration and uploader info
                            display_text = title
                            if duration:
                                display_text += f" [{duration}]"
                            if uploader:
                                display_text += f" - {uploader}"
                                
                            self.results_list.Append(display_text)
                        
                        # Cache the results for faster future searches
                        self.search_cache[query] = self.videos.copy()
                        
                        self.GetParent().play_sound('ding')
                        result_count = len(self.videos)
                        self.GetParent().speak_message(_("Found %d results for: %s") % (result_count, query))
                    else:
                        self.GetParent().speak_message(_("No results found for: %s") % query)
                else:
                    self.GetParent().speak_message(_("No results found for: %s") % query)
                    
        except Exception as e:
            error_msg = str(e)
            # Provide more specific error messages
            if "network" in error_msg.lower() or "connection" in error_msg.lower():
                self.GetParent().speak_message(_("Network connection error. Check your internet connection."))
            elif "timeout" in error_msg.lower():
                self.GetParent().speak_message(_("Search timed out. Please try again."))
            else:
                self.GetParent().speak_message(_("Search error: %s") % error_msg)

    def _show_selection_context_menu(self, event=None):
        selection = self.results_list.GetSelection()
        if selection != wx.NOT_FOUND:
            self.results_list.SetSelection(selection) # Ensure the item is selected

            menu = wx.Menu()
            open_browser_item = menu.Append(wx.ID_ANY, _("Open in Browser"))

            self.Bind(wx.EVT_MENU, self.on_open_in_browser, open_browser_item)

            # Determine position for the context menu
            if event and hasattr(event, 'GetPosition'): # Check if it's a mouse event
                pos = event.GetPosition()
            else: # For keyboard events (Enter)
                # For ListBox, we can't get item rect directly.
                # Instead, we'll show the menu at the current mouse position or a default position.
                # A simple approach is to show it at the center of the listbox or at the top-left.
                # For now, let's use the current mouse position if available, otherwise a default.
                pos = self.results_list.GetPosition()
                pos = self.results_list.ClientToScreen(pos)

            self.results_list.PopupMenu(menu, pos)
            menu.Destroy()

    def on_key_down(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN:
            self._show_selection_context_menu() # Call the new method
        else:
            event.Skip()


    def on_right_click(self, event):
        selection = self.results_list.GetSelection()
        if selection != wx.NOT_FOUND:
            self.results_list.SetSelection(selection) # Select the item that was right-clicked
            menu = wx.Menu()
            open_browser_item = menu.Append(wx.ID_ANY, _("Open in Browser"))

            self.Bind(wx.EVT_MENU, self.on_open_in_browser, open_browser_item)

            self.PopupMenu(menu, event.GetPosition())
            menu.Destroy()


    def on_open_in_browser(self, event):
        selection = self.results_list.GetSelection()
        if selection != wx.NOT_FOUND:
            video = self.videos[selection]
            
            # Handle both flat and full extracted entries
            video_id = video.get('id', '')
            video_url = video.get('webpage_url', '')
            
            # For flat extractions, we primarily have the video ID
            if video_id:
                final_url = f"https://www.youtube.com/watch?v={video_id}"
            elif video_url:
                final_url = video_url
            elif video.get('url'):
                final_url = video.get('url')
            else:
                self.GetParent().speak_message(_("No valid video URL found"))
                return
            
            webbrowser.open(final_url)

