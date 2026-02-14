"""
Titan-Net Forum GUI
Forum interface with topics, replies, and multi-line text editing
"""
import wx
import threading
import accessible_output3.outputs.auto
from src.network.titan_net import TitanNetClient
from src.titan_core.sound import play_sound
from src.titan_core.translation import set_language
from src.settings.settings import get_setting
from src.titan_core.stereo_speech import get_stereo_speech

# Get the translation function
_ = set_language(get_setting('language', 'pl'))

speaker = accessible_output3.outputs.auto.Auto()
stereo_speech = get_stereo_speech()


class ForumTopicsWindow(wx.Frame):
    """Main forum window showing topic list"""

    def __init__(self, parent, titan_client: TitanNetClient):
        super().__init__(parent, title=_("Titan-Net Forum"), size=(900, 650))
        self.titan_client = titan_client
        self.InitUI()
        self.Centre()

        play_sound('ui/window_open.ogg')

        # Load initial topics
        wx.CallAfter(self.load_topics)

    def InitUI(self):
        """Initialize UI"""
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Title
        title_label = wx.StaticText(panel, label=_("Titan-Net Forum"))
        font = title_label.GetFont()
        font.PointSize += 4
        font = font.Bold()
        title_label.SetFont(font)
        vbox.Add(title_label, flag=wx.ALL | wx.ALIGN_CENTER, border=10)

        # Category filter
        category_box = wx.BoxSizer(wx.HORIZONTAL)
        wx.StaticText(panel, label=_("Category:"))
        self.category_choice = wx.Choice(panel, choices=[
            _("All"),
            _("General"),
            _("Help"),
            _("Announcements"),
            _("Discussion")
        ])
        self.category_choice.SetSelection(0)
        self.category_choice.Bind(wx.EVT_CHOICE, self.OnCategoryChange)
        category_box.Add(wx.StaticText(panel, label=_("Category:")), flag=wx.RIGHT, border=5)
        category_box.Add(self.category_choice, proportion=1)
        vbox.Add(category_box, flag=wx.EXPAND | wx.ALL, border=5)

        # Topics list
        self.topics_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.topics_list.AppendColumn(_("Title"), width=400)
        self.topics_list.AppendColumn(_("Author"), width=150)
        self.topics_list.AppendColumn(_("Replies"), width=80)
        self.topics_list.AppendColumn(_("Views"), width=80)
        self.topics_list.AppendColumn(_("Last Update"), width=150)

        self.topics_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.OnTopicOpen)
        self.topics_list.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.topics_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        # Buttons
        btn_box = wx.BoxSizer(wx.HORIZONTAL)

        self.new_topic_btn = wx.Button(panel, label=_("New Topic"))
        self.new_topic_btn.Bind(wx.EVT_BUTTON, self.OnNewTopic)
        self.new_topic_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        btn_box.Add(self.new_topic_btn, flag=wx.RIGHT, border=5)

        self.refresh_btn = wx.Button(panel, label=_("Refresh"))
        self.refresh_btn.Bind(wx.EVT_BUTTON, self.OnRefresh)
        self.refresh_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        btn_box.Add(self.refresh_btn, flag=wx.RIGHT, border=5)

        self.search_btn = wx.Button(panel, label=_("Search"))
        self.search_btn.Bind(wx.EVT_BUTTON, self.OnSearch)
        self.search_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        btn_box.Add(self.search_btn, flag=wx.RIGHT, border=5)

        vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.ALL, border=10)

        panel.SetSizer(vbox)

    def OnFocus(self, event):
        """Handle focus events with sound"""
        play_sound('core/FOCUS.ogg', position=0.5)
        event.Skip()

    def load_topics(self, category=None):
        """Load topics from server"""
        def _load():
            # Map UI category to API category
            category_map = {
                _("All"): None,
                _("General"): "general",
                _("Help"): "help",
                _("Announcements"): "announcements",
                _("Discussion"): "discussion"
            }

            api_category = category_map.get(category) if category else None
            result = self.titan_client.get_forum_topics(category=api_category, limit=100)
            wx.CallAfter(self._display_topics, result)

        threading.Thread(target=_load, daemon=True).start()

    def _display_topics(self, result):
        """Display topics in list"""
        self.topics_list.DeleteAllItems()

        if result.get('success'):
            topics = result.get('topics', [])

            for topic in topics:
                idx = self.topics_list.InsertItem(
                    self.topics_list.GetItemCount(),
                    topic['title']
                )
                self.topics_list.SetItem(idx, 1, topic['author_username'])
                self.topics_list.SetItem(idx, 2, str(topic['reply_count']))
                self.topics_list.SetItem(idx, 3, str(topic['views']))

                # Format date
                try:
                    updated_at = topic['updated_at'].split('T')[0]
                except:
                    updated_at = topic['updated_at']
                self.topics_list.SetItem(idx, 4, updated_at)

                # Store topic_id
                self.topics_list.SetItemData(idx, topic['id'])

            if not topics:
                wx.MessageBox(_("No topics found"), _("Forum"), wx.OK | wx.ICON_INFORMATION)
        else:
            play_sound('core/error.ogg')
            wx.MessageBox(
                result.get('error', _('Failed to load topics')),
                _("Error"),
                wx.OK | wx.ICON_ERROR
            )

    def OnCategoryChange(self, event):
        """Handle category selection change"""
        play_sound('core/SELECT.ogg')
        category = self.category_choice.GetStringSelection()
        self.load_topics(category)

    def OnTopicOpen(self, event):
        """Open topic view"""
        play_sound('core/SELECT.ogg')

        selected = self.topics_list.GetFirstSelected()
        if selected == -1:
            return

        topic_id = self.topics_list.GetItemData(selected)

        # Open topic window
        topic_window = ForumTopicWindow(self, self.titan_client, topic_id)
        topic_window.Show()

    def OnNewTopic(self, event):
        """Create new topic"""
        play_sound('core/SELECT.ogg')

        dialog = NewTopicDialog(self, self.titan_client)
        if dialog.ShowModal() == wx.ID_OK:
            # Refresh list
            self.load_topics()
        dialog.Destroy()

    def OnRefresh(self, event):
        """Refresh topics list"""
        play_sound('core/SELECT.ogg')
        category = self.category_choice.GetStringSelection()
        self.load_topics(category)

    def OnSearch(self, event):
        """Search forum"""
        play_sound('core/SELECT.ogg')

        dlg = wx.TextEntryDialog(self, _("Enter search query:"), _("Search Forum"))
        if dlg.ShowModal() == wx.ID_OK:
            query = dlg.GetValue().strip()
            if query:
                def _search():
                    result = self.titan_client.search_forum(query)
                    wx.CallAfter(self._display_topics, result)

                threading.Thread(target=_search, daemon=True).start()

        dlg.Destroy()


class ForumTopicWindow(wx.Frame):
    """Window showing single topic with replies"""

    def __init__(self, parent, titan_client: TitanNetClient, topic_id: int):
        super().__init__(parent, title=_("Forum Topic"), size=(750, 650))
        self.titan_client = titan_client
        self.topic_id = topic_id
        self.topic_data = None
        self.InitUI()
        self.Centre()

        play_sound('ui/window_open.ogg')

        # Load topic data
        wx.CallAfter(self.load_topic)

    def InitUI(self):
        """Initialize UI"""
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Topic title
        self.title_label = wx.StaticText(panel, label="")
        font = self.title_label.GetFont()
        font.PointSize += 3
        font = font.Bold()
        self.title_label.SetFont(font)
        vbox.Add(self.title_label, flag=wx.ALL, border=10)

        # First post (read-only, multi-line)
        wx.StaticText(panel, label=_("Topic Content:"))
        self.first_post = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP,
            size=(-1, 120)
        )
        self.first_post.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.first_post, flag=wx.EXPAND | wx.ALL, border=5)

        # Separator
        vbox.Add(wx.StaticLine(panel), flag=wx.EXPAND | wx.ALL, border=5)

        # Replies (read-only, multi-line)
        wx.StaticText(panel, label=_("Replies:"))
        self.replies_display = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP
        )
        self.replies_display.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.replies_display, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        # Reply input (multi-line)
        wx.StaticText(panel, label=_("Your Reply:"))
        self.reply_input = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE | wx.TE_WORDWRAP,
            size=(-1, 100)
        )
        self.reply_input.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.reply_input, flag=wx.EXPAND | wx.ALL, border=5)

        # Buttons
        btn_box = wx.BoxSizer(wx.HORIZONTAL)

        self.send_btn = wx.Button(panel, label=_("Send Reply"))
        self.send_btn.Bind(wx.EVT_BUTTON, self.OnSendReply)
        self.send_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        btn_box.Add(self.send_btn, flag=wx.RIGHT, border=5)

        self.refresh_btn = wx.Button(panel, label=_("Refresh"))
        self.refresh_btn.Bind(wx.EVT_BUTTON, self.OnRefresh)
        self.refresh_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        btn_box.Add(self.refresh_btn)

        vbox.Add(btn_box, flag=wx.ALIGN_RIGHT | wx.ALL, border=5)

        panel.SetSizer(vbox)

    def OnFocus(self, event):
        """Handle focus events with sound"""
        play_sound('core/FOCUS.ogg', position=0.5)
        event.Skip()

    def load_topic(self):
        """Load topic and replies"""
        def _load():
            # Get topic details
            topic_result = self.titan_client.get_forum_topic(self.topic_id)

            # Get replies
            replies_result = self.titan_client.get_forum_replies(self.topic_id, limit=100)

            wx.CallAfter(self._display_topic, topic_result, replies_result)

        threading.Thread(target=_load, daemon=True).start()

    def _display_topic(self, topic_result, replies_result):
        """Display topic and replies"""
        if not topic_result.get('success'):
            play_sound('core/error.ogg')
            wx.MessageBox(_("Failed to load topic"), _("Error"), wx.OK | wx.ICON_ERROR)
            self.Close()
            return

        topic = topic_result.get('topic', {})
        self.topic_data = topic

        # Display title
        self.title_label.SetLabel(topic['title'])
        self.SetTitle(topic['title'])

        # Display first post
        first_post_text = f"{_('Author')}: {topic['author_username']} (#{topic['author_titan_number']})\n"
        first_post_text += f"{_('Posted')}: {topic['created_at']}\n"
        first_post_text += f"{_('Views')}: {topic['views']}\n\n"
        first_post_text += topic['content']
        self.first_post.SetValue(first_post_text)

        # Display replies
        if replies_result.get('success'):
            replies = replies_result.get('replies', [])
            replies_text = ""

            if replies:
                for i, reply in enumerate(replies, 1):
                    replies_text += f"--- {_('Reply')} #{i} ---\n"
                    replies_text += f"{_('Author')}: {reply['author_username']} (#{reply['author_titan_number']})\n"
                    replies_text += f"{_('Posted')}: {reply['created_at']}\n\n"
                    replies_text += reply['content']
                    replies_text += "\n\n"
            else:
                replies_text = _("No replies yet. Be the first to reply!")

            self.replies_display.SetValue(replies_text)

    def OnSendReply(self, event):
        """Send reply to topic"""
        play_sound('core/SELECT.ogg')

        content = self.reply_input.GetValue().strip()

        if not content:
            wx.MessageBox(_("Please enter reply content"), _("Error"), wx.OK | wx.ICON_WARNING)
            return

        # Send reply
        def _send():
            result = self.titan_client.add_forum_reply(self.topic_id, content)
            wx.CallAfter(self._on_reply_sent, result)

        self.send_btn.Enable(False)
        threading.Thread(target=_send, daemon=True).start()

    def _on_reply_sent(self, result):
        """Handle reply sent"""
        self.send_btn.Enable(True)

        if result.get('success'):
            play_sound('titannet/message_send.ogg')
            wx.MessageBox(_("Reply sent successfully"), _("Success"), wx.OK | wx.ICON_INFORMATION)

            # Clear input
            self.reply_input.Clear()

            # Refresh
            self.load_topic()
        else:
            play_sound('core/error.ogg')
            error = result.get('error', _('Failed to send reply'))
            wx.MessageBox(error, _("Error"), wx.OK | wx.ICON_ERROR)

    def OnRefresh(self, event):
        """Refresh topic"""
        play_sound('core/SELECT.ogg')
        self.load_topic()


class NewTopicDialog(wx.Dialog):
    """Dialog for creating new topic"""

    def __init__(self, parent, titan_client: TitanNetClient):
        super().__init__(parent, title=_("New Forum Topic"), size=(600, 500))
        self.titan_client = titan_client
        self.InitUI()
        self.Centre()

        play_sound('ui/dialog.ogg')

    def InitUI(self):
        """Initialize UI"""
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Title
        wx.StaticText(panel, label=_("Title:"))
        self.title_input = wx.TextCtrl(panel)
        self.title_input.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(wx.StaticText(panel, label=_("Title:")), flag=wx.LEFT | wx.TOP, border=5)
        vbox.Add(self.title_input, flag=wx.EXPAND | wx.ALL, border=5)

        # Category
        wx.StaticText(panel, label=_("Category:"))
        self.category_choice = wx.Choice(panel, choices=[
            "general", "help", "announcements", "discussion"
        ])
        self.category_choice.SetSelection(0)
        self.category_choice.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(wx.StaticText(panel, label=_("Category:")), flag=wx.LEFT | wx.TOP, border=5)
        vbox.Add(self.category_choice, flag=wx.EXPAND | wx.ALL, border=5)

        # Content (multi-line)
        wx.StaticText(panel, label=_("Content:"))
        self.content_input = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_WORDWRAP)
        self.content_input.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(wx.StaticText(panel, label=_("Content:")), flag=wx.LEFT | wx.TOP, border=5)
        vbox.Add(self.content_input, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        # Buttons
        btn_box = wx.BoxSizer(wx.HORIZONTAL)

        create_btn = wx.Button(panel, wx.ID_OK, _("Create Topic"))
        create_btn.Bind(wx.EVT_BUTTON, self.OnCreate)
        create_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        btn_box.Add(create_btn, flag=wx.RIGHT, border=5)

        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        cancel_btn.Bind(wx.EVT_BUTTON, self.OnCancel)
        cancel_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        btn_box.Add(cancel_btn)

        vbox.Add(btn_box, flag=wx.ALIGN_RIGHT | wx.ALL, border=10)

        panel.SetSizer(vbox)

    def OnFocus(self, event):
        """Handle focus events with sound"""
        play_sound('core/FOCUS.ogg', position=0.5)
        event.Skip()

    def OnCreate(self, event):
        """Create topic"""
        play_sound('core/SELECT.ogg')

        title = self.title_input.GetValue().strip()
        content = self.content_input.GetValue().strip()
        category = self.category_choice.GetStringSelection()

        if not title or not content:
            wx.MessageBox(_("Title and content are required"), _("Error"), wx.OK | wx.ICON_WARNING)
            return

        # Send
        def _create():
            result = self.titan_client.create_forum_topic(title, content, category)
            wx.CallAfter(self._on_created, result)

        threading.Thread(target=_create, daemon=True).start()

    def _on_created(self, result):
        """Handle topic created"""
        if result.get('success'):
            play_sound('titannet/new_feedpost.ogg')
            wx.MessageBox(_("Topic created successfully"), _("Success"), wx.OK | wx.ICON_INFORMATION)
            self.EndModal(wx.ID_OK)
        else:
            play_sound('core/error.ogg')
            error = result.get('error', _('Failed to create topic'))
            wx.MessageBox(error, _("Error"), wx.OK | wx.ICON_ERROR)

    def OnCancel(self, event):
        """Handle cancel button"""
        play_sound('core/SELECT.ogg')
        self.EndModal(wx.ID_CANCEL)


if __name__ == "__main__":
    # Test
    app = wx.App()

    from src.network.titan_net import TitanNetClient

    client = TitanNetClient("titosofttitan.com", 8001, 8000)

    # Login first
    result = client.login("test", "test")
    if result.get('success'):
        window = ForumTopicsWindow(None, client)
        window.Show()
        app.MainLoop()
    else:
        print("Login failed")
