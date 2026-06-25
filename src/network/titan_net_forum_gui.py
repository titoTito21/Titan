"""
Titan-Net Forum GUI
Forum interface with topics, replies, and multi-line text editing
"""
import wx
import threading
from src.network.titan_net import TitanNetClient
from src.titan_core.sound import play_sound
from src.titan_core.translation import set_language
from src.settings.settings import get_setting
from src.accessibility.lazy_speaker import LazySpeaker
from src.titan_core.skin_manager import apply_skin_to_window

# Get the translation function
_ = set_language(get_setting('language', 'pl'))

speaker = LazySpeaker()


def _show_skinned_message(message, caption, style=wx.OK | wx.ICON_INFORMATION, parent=None):
    dlg = wx.MessageDialog(parent, message, caption, style)
    try:
        apply_skin_to_window(dlg)
    except Exception:
        pass
    result = dlg.ShowModal()
    dlg.Destroy()
    return result


def _new_text_entry_dialog(*args, **kwargs):
    dlg = wx.TextEntryDialog(*args, **kwargs)
    try:
        apply_skin_to_window(dlg)
    except Exception:
        pass
    return dlg


class ForumTopicsWindow(wx.Frame):
    """Main forum window showing topic list.

    Two modes:
      * Legacy flat forum: ``forum_id`` is None -> the category Choice filters
        the global forum (kept for backward compatibility).
      * Group forum (Elten-style): ``forum_id``/``forum_name`` are set -> the
        window shows the threads of one forum inside a group; the category
        Choice is hidden and new topics post into that forum.
    """

    def __init__(self, parent, titan_client: TitanNetClient, forum_id=None, forum_name=None, can_post=True):
        self.forum_id = forum_id
        self.forum_name = forum_name
        self.can_post = can_post
        win_title = forum_name if forum_name else _("Titan-Net Forum")
        super().__init__(parent, title=win_title, size=(900, 650))
        self.titan_client = titan_client
        self.InitUI()
        self.Centre()

        play_sound('ui/window_open.ogg')

        # Register in window switcher
        from src.ui.window_switcher import register_window
        register_window(win_title, window=self, category='messenger')

        # Load initial topics
        wx.CallAfter(self.load_topics)

    def InitUI(self):
        """Initialize UI"""
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Title
        title_label = wx.StaticText(panel, label=(self.forum_name or _("Titan-Net Forum")))
        font = title_label.GetFont()
        font.PointSize += 4
        font = font.Bold()
        title_label.SetFont(font)
        vbox.Add(title_label, flag=wx.ALL | wx.ALIGN_CENTER, border=10)

        # Category filter (legacy flat forum only). In a group forum the
        # threads belong to a single forum, so there is no category selector.
        self.category_choice = None
        if self.forum_id is None:
            category_box = wx.BoxSizer(wx.HORIZONTAL)
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
            if self.forum_id is not None:
                # Group forum: list this forum's threads by id.
                result = self.titan_client.get_forum_topics(forum_id=self.forum_id, limit=100)
            else:
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
                _show_skinned_message(_("No topics found"), _("Forum"), wx.OK | wx.ICON_INFORMATION)
        else:
            play_sound('core/error.ogg')
            _show_skinned_message(
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

        from src.ui.window_switcher import register_window
        topic_title = self.topics_list.GetItemText(selected)
        register_window(f"Forum: {topic_title}", window=topic_window, category='messenger')

    def OnNewTopic(self, event):
        """Create new topic"""
        play_sound('core/SELECT.ogg')

        if self.forum_id is not None and not self.can_post:
            _show_skinned_message(_("Join the group to post"), _("Forum"), wx.OK | wx.ICON_INFORMATION)
            return

        dialog = NewTopicDialog(self, self.titan_client, forum_id=self.forum_id)
        if dialog.ShowModal() == wx.ID_OK:
            # Refresh list
            self.load_topics()
        dialog.Destroy()

    def OnRefresh(self, event):
        """Refresh topics list"""
        play_sound('core/SELECT.ogg')
        category = self.category_choice.GetStringSelection() if self.category_choice else None
        self.load_topics(category)

    def OnSearch(self, event):
        """Search forum"""
        play_sound('core/SELECT.ogg')

        dlg = _new_text_entry_dialog(self, _("Enter search query:"), _("Search Forum"))
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

    def __init__(self, parent, titan_client: TitanNetClient, topic_id: int, last_known_reply_count: int = 0):
        super().__init__(parent, title=_("Forum Topic"), size=(750, 650))
        self.titan_client = titan_client
        self.topic_id = topic_id
        self.topic_data = None
        self.last_known_reply_count = last_known_reply_count
        self._reply_positions = []  # Character positions of each reply in replies_display
        self._first_new_reply_pos = -1  # Position of first new reply
        self.InitUI()
        self.Centre()

        self.Bind(wx.EVT_CHAR_HOOK, self.OnKeyPress)
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
        self.reply_input.Bind(wx.EVT_KEY_DOWN, self.OnReplyKeyDown)
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

    def OnKeyPress(self, event):
        """Handle keyboard shortcuts for post navigation"""
        keycode = event.GetKeyCode()
        focused = self.FindFocus()

        if event.ControlDown() and focused != self.reply_input:
            if keycode == ord('U'):
                # Ctrl+U -> jump to first new/unread reply
                self._jump_to_first_new_reply()
                return
            elif keycode == ord('.'):
                # Ctrl+. -> jump to last reply
                self._jump_to_reply(-1)
                return
            elif keycode == ord(','):
                # Ctrl+, -> jump to first reply (topic post)
                self._jump_to_reply(0)
                return

        event.Skip()

    def OnReplyKeyDown(self, event):
        """Handle Ctrl+Enter to send reply"""
        if event.ControlDown() and event.GetKeyCode() == wx.WXK_RETURN:
            self.OnSendReply(None)
            return
        event.Skip()

    def _jump_to_first_new_reply(self):
        """Jump to the first new/unread reply"""
        if self._first_new_reply_pos >= 0:
            self.replies_display.SetFocus()
            self.replies_display.SetInsertionPoint(self._first_new_reply_pos)
            self.replies_display.ShowPosition(self._first_new_reply_pos)
            play_sound('core/FOCUS.ogg')
            speaker.output(_("First new reply"))
        else:
            # No new replies, go to last
            speaker.output(_("No new replies"))
            self._jump_to_reply(-1)

    def _jump_to_reply(self, index):
        """Jump to a specific reply by index. -1 = last reply, 0 = first (topic post)."""
        if index == 0:
            # Jump to first post
            self.first_post.SetFocus()
            self.first_post.SetInsertionPoint(0)
            play_sound('core/FOCUS.ogg')
            return

        if not self._reply_positions:
            return

        if index < 0:
            index = len(self._reply_positions) + index

        if 0 <= index < len(self._reply_positions):
            pos = self._reply_positions[index]
            self.replies_display.SetFocus()
            self.replies_display.SetInsertionPoint(pos)
            self.replies_display.ShowPosition(pos)
            play_sound('core/FOCUS.ogg')

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
            _show_skinned_message(_("Failed to load topic"), _("Error"), wx.OK | wx.ICON_ERROR)
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

        # Display replies with position tracking
        self._reply_positions = []
        self._first_new_reply_pos = -1

        if replies_result.get('success'):
            replies = replies_result.get('replies', [])
            replies_text = ""

            if replies:
                for i, reply in enumerate(replies, 1):
                    # Track position of this reply
                    self._reply_positions.append(len(replies_text))

                    # Track first new reply (replies after last_known_reply_count are new)
                    if i > self.last_known_reply_count and self._first_new_reply_pos < 0:
                        self._first_new_reply_pos = len(replies_text)

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
            _show_skinned_message(_("Please enter reply content"), _("Error"), wx.OK | wx.ICON_WARNING)
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
            _show_skinned_message(_("Reply sent successfully"), _("Success"), wx.OK | wx.ICON_INFORMATION)

            # Clear input
            self.reply_input.Clear()

            # Refresh
            self.load_topic()
        else:
            play_sound('core/error.ogg')
            error = result.get('error', _('Failed to send reply'))
            _show_skinned_message(error, _("Error"), wx.OK | wx.ICON_ERROR)

    def OnRefresh(self, event):
        """Refresh topic"""
        play_sound('core/SELECT.ogg')
        self.load_topic()


class NewTopicDialog(wx.Dialog):
    """Dialog for creating new topic"""

    def __init__(self, parent, titan_client: TitanNetClient, forum_id=None):
        super().__init__(parent, title=_("New Forum Topic"), size=(600, 500))
        self.titan_client = titan_client
        self.forum_id = forum_id
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

        # Category (legacy flat forum only). In a group forum the topic goes
        # straight into the selected forum, so no category picker is shown.
        self.category_choice = None
        if self.forum_id is None:
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
        category = self.category_choice.GetStringSelection() if self.category_choice else 'general'

        if not title or not content:
            _show_skinned_message(_("Title and content are required"), _("Error"), wx.OK | wx.ICON_WARNING)
            return

        # Send
        def _create():
            result = self.titan_client.create_forum_topic(
                title, content, category, forum_id=self.forum_id
            )
            wx.CallAfter(self._on_created, result)

        threading.Thread(target=_create, daemon=True).start()

    def _on_created(self, result):
        """Handle topic created"""
        if result.get('success'):
            play_sound('titannet/new_feedpost.ogg')
            _show_skinned_message(_("Topic created successfully"), _("Success"), wx.OK | wx.ICON_INFORMATION)
            self.EndModal(wx.ID_OK)
        else:
            play_sound('core/error.ogg')
            error = result.get('error', _('Failed to create topic'))
            _show_skinned_message(error, _("Error"), wx.OK | wx.ICON_ERROR)

    def OnCancel(self, event):
        """Handle cancel button"""
        play_sound('core/SELECT.ogg')
        self.EndModal(wx.ID_CANCEL)


class NewGroupDialog(wx.Dialog):
    """Dialog for creating a new group."""

    def __init__(self, parent, titan_client: TitanNetClient):
        super().__init__(parent, title=_("New Group"), size=(500, 400))
        self.titan_client = titan_client
        self.InitUI()
        self.Centre()
        play_sound('ui/dialog.ogg')

    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        vbox.Add(wx.StaticText(panel, label=_("Group name:")), flag=wx.LEFT | wx.TOP, border=5)
        self.name_input = wx.TextCtrl(panel)
        self.name_input.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.name_input, flag=wx.EXPAND | wx.ALL, border=5)

        vbox.Add(wx.StaticText(panel, label=_("Description:")), flag=wx.LEFT | wx.TOP, border=5)
        self.desc_input = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_WORDWRAP, size=(-1, 80))
        self.desc_input.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.desc_input, flag=wx.EXPAND | wx.ALL, border=5)

        vbox.Add(wx.StaticText(panel, label=_("Visibility:")), flag=wx.LEFT | wx.TOP, border=5)
        # Labels are translated; the API value is chosen by index.
        self._visibility_values = ['public', 'private', 'hidden']
        self.visibility_choice = wx.Choice(panel, choices=[
            _("Public (anyone can join)"),
            _("Private (join needs approval)"),
            _("Hidden (invite only)")
        ])
        self.visibility_choice.SetSelection(0)
        self.visibility_choice.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.visibility_choice, flag=wx.EXPAND | wx.ALL, border=5)

        vbox.Add(wx.StaticText(panel, label=_("Member limit (0 = unlimited):")), flag=wx.LEFT | wx.TOP, border=5)
        self.limit_input = wx.SpinCtrl(panel, min=0, max=100000, initial=0)
        self.limit_input.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.limit_input, flag=wx.EXPAND | wx.ALL, border=5)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        create_btn = wx.Button(panel, wx.ID_OK, _("Create Group"))
        create_btn.Bind(wx.EVT_BUTTON, self.OnCreate)
        create_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        btn_box.Add(create_btn, flag=wx.RIGHT, border=5)
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        cancel_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        btn_box.Add(cancel_btn)
        vbox.Add(btn_box, flag=wx.ALIGN_RIGHT | wx.ALL, border=10)

        panel.SetSizer(vbox)

    def OnFocus(self, event):
        play_sound('core/FOCUS.ogg', position=0.5)
        event.Skip()

    def OnCreate(self, event):
        play_sound('core/SELECT.ogg')
        name = self.name_input.GetValue().strip()
        if not name:
            _show_skinned_message(_("Group name is required"), _("Error"), wx.OK | wx.ICON_WARNING)
            return
        description = self.desc_input.GetValue().strip()
        visibility = self._visibility_values[self.visibility_choice.GetSelection()]
        member_limit = self.limit_input.GetValue() or None

        def _create():
            result = self.titan_client.create_group(name, description, visibility, member_limit)
            wx.CallAfter(self._on_created, result)

        threading.Thread(target=_create, daemon=True).start()

    def _on_created(self, result):
        if result.get('success'):
            play_sound('titannet/new_feedpost.ogg')
            _show_skinned_message(_("Group created successfully"), _("Success"), wx.OK | wx.ICON_INFORMATION)
            self.EndModal(wx.ID_OK)
        else:
            play_sound('core/error.ogg')
            _show_skinned_message(result.get('error', _('Failed to create group')), _("Error"), wx.OK | wx.ICON_ERROR)


class GroupForumsWindow(wx.Frame):
    """Lists the forums (categories) of one group and opens their threads."""

    def __init__(self, parent, titan_client: TitanNetClient, group: dict):
        self.group = group
        self.group_id = group['id']
        title = _("Group: {name}").format(name=group.get('name', ''))
        super().__init__(parent, title=title, size=(800, 600))
        self.titan_client = titan_client
        self.InitUI()
        self.Centre()
        play_sound('ui/window_open.ogg')
        from src.ui.window_switcher import register_window
        register_window(title, window=self, category='messenger')
        wx.CallAfter(self.load_forums)

    def _is_moderator(self):
        return self.group.get('my_role') in ('owner', 'moderator')

    def _is_member(self):
        return self.group.get('my_status') == 'active'

    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        title_label = wx.StaticText(panel, label=self.group.get('name', ''))
        font = title_label.GetFont(); font.PointSize += 4; font = font.Bold()
        title_label.SetFont(font)
        vbox.Add(title_label, flag=wx.ALL | wx.ALIGN_CENTER, border=10)

        self.forums_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.forums_list.AppendColumn(_("Forum"), width=300)
        self.forums_list.AppendColumn(_("Threads"), width=100)
        self.forums_list.AppendColumn(_("Description"), width=350)
        self.forums_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.OnOpenForum)
        self.forums_list.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.forums_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        open_btn = wx.Button(panel, label=_("Open"))
        open_btn.Bind(wx.EVT_BUTTON, self.OnOpenForum)
        open_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        btn_box.Add(open_btn, flag=wx.RIGHT, border=5)

        if self._is_moderator():
            new_forum_btn = wx.Button(panel, label=_("New Forum"))
            new_forum_btn.Bind(wx.EVT_BUTTON, self.OnNewForum)
            new_forum_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
            btn_box.Add(new_forum_btn, flag=wx.RIGHT, border=5)

            del_forum_btn = wx.Button(panel, label=_("Delete Forum"))
            del_forum_btn.Bind(wx.EVT_BUTTON, self.OnDeleteForum)
            del_forum_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
            btn_box.Add(del_forum_btn, flag=wx.RIGHT, border=5)

            members_btn = wx.Button(panel, label=_("Pending Members"))
            members_btn.Bind(wx.EVT_BUTTON, self.OnPendingMembers)
            members_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
            btn_box.Add(members_btn, flag=wx.RIGHT, border=5)

        refresh_btn = wx.Button(panel, label=_("Refresh"))
        refresh_btn.Bind(wx.EVT_BUTTON, lambda e: (play_sound('core/SELECT.ogg'), self.load_forums()))
        refresh_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        btn_box.Add(refresh_btn)

        vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.ALL, border=10)
        panel.SetSizer(vbox)

    def OnFocus(self, event):
        play_sound('core/FOCUS.ogg', position=0.5)
        event.Skip()

    def load_forums(self):
        def _load():
            result = self.titan_client.list_group_forums(self.group_id)
            wx.CallAfter(self._display_forums, result)
        threading.Thread(target=_load, daemon=True).start()

    def _display_forums(self, result):
        self.forums_list.DeleteAllItems()
        if not result.get('success'):
            play_sound('core/error.ogg')
            _show_skinned_message(result.get('error', _('Failed to load forums')), _("Error"), wx.OK | wx.ICON_ERROR)
            return
        forums = result.get('forums', [])
        for forum in forums:
            idx = self.forums_list.InsertItem(self.forums_list.GetItemCount(), forum['name'])
            self.forums_list.SetItem(idx, 1, str(forum.get('topic_count', 0)))
            self.forums_list.SetItem(idx, 2, forum.get('description') or '')
            self.forums_list.SetItemData(idx, forum['id'])
        if not forums:
            _show_skinned_message(_("No forums in this group yet"), _("Group"), wx.OK | wx.ICON_INFORMATION)

    def _selected_forum(self):
        sel = self.forums_list.GetFirstSelected()
        if sel == -1:
            return None, None
        return self.forums_list.GetItemData(sel), self.forums_list.GetItemText(sel)

    def OnOpenForum(self, event):
        play_sound('core/SELECT.ogg')
        forum_id, forum_name = self._selected_forum()
        if forum_id is None:
            return
        win = ForumTopicsWindow(self, self.titan_client, forum_id=forum_id,
                                forum_name=forum_name, can_post=self._is_member())
        win.Show()

    def OnNewForum(self, event):
        play_sound('core/SELECT.ogg')
        dlg = _new_text_entry_dialog(self, _("Forum name:"), _("New Forum"))
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip()
            if name:
                def _create():
                    result = self.titan_client.create_group_forum(self.group_id, name)
                    wx.CallAfter(self._on_forum_changed, result)
                threading.Thread(target=_create, daemon=True).start()
        dlg.Destroy()

    def OnDeleteForum(self, event):
        play_sound('core/SELECT.ogg')
        forum_id, forum_name = self._selected_forum()
        if forum_id is None:
            return
        confirm = _show_skinned_message(
            _("Delete forum '{name}' and all its threads?").format(name=forum_name),
            _("Confirm"), wx.YES_NO | wx.ICON_WARNING
        )
        if confirm == wx.ID_YES:
            def _delete():
                result = self.titan_client.delete_group_forum(forum_id)
                wx.CallAfter(self._on_forum_changed, result)
            threading.Thread(target=_delete, daemon=True).start()

    def _on_forum_changed(self, result):
        if result.get('success'):
            play_sound('core/SELECT.ogg')
            self.load_forums()
        else:
            play_sound('core/error.ogg')
            _show_skinned_message(result.get('error', _('Operation failed')), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnPendingMembers(self, event):
        play_sound('core/SELECT.ogg')
        dlg = GroupMembersDialog(self, self.titan_client, self.group_id)
        dlg.ShowModal()
        dlg.Destroy()


class GroupMembersDialog(wx.Dialog):
    """Moderator view of pending join requests with approve/reject."""

    def __init__(self, parent, titan_client: TitanNetClient, group_id: int):
        super().__init__(parent, title=_("Pending Members"), size=(500, 400))
        self.titan_client = titan_client
        self.group_id = group_id
        self.InitUI()
        self.Centre()
        play_sound('ui/dialog.ogg')
        wx.CallAfter(self.load_pending)

    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.members_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.members_list.AppendColumn(_("User"), width=250)
        self.members_list.AppendColumn(_("Titan number"), width=120)
        vbox.Add(self.members_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        approve_btn = wx.Button(panel, label=_("Approve"))
        approve_btn.Bind(wx.EVT_BUTTON, lambda e: self._act(True))
        btn_box.Add(approve_btn, flag=wx.RIGHT, border=5)
        reject_btn = wx.Button(panel, label=_("Reject"))
        reject_btn.Bind(wx.EVT_BUTTON, lambda e: self._act(False))
        btn_box.Add(reject_btn, flag=wx.RIGHT, border=5)
        close_btn = wx.Button(panel, wx.ID_CANCEL, _("Close"))
        btn_box.Add(close_btn)
        vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.ALL, border=10)
        panel.SetSizer(vbox)

    def load_pending(self):
        def _load():
            result = self.titan_client.get_group_members(self.group_id, status='pending')
            wx.CallAfter(self._display, result)
        threading.Thread(target=_load, daemon=True).start()

    def _display(self, result):
        self.members_list.DeleteAllItems()
        if not result.get('success'):
            play_sound('core/error.ogg')
            _show_skinned_message(result.get('error', _('Failed to load members')), _("Error"), wx.OK | wx.ICON_ERROR)
            return
        for m in result.get('members', []):
            idx = self.members_list.InsertItem(self.members_list.GetItemCount(), m['username'])
            self.members_list.SetItem(idx, 1, str(m.get('titan_number', '')))
            self.members_list.SetItemData(idx, m['user_id'])

    def _act(self, approve):
        play_sound('core/SELECT.ogg')
        sel = self.members_list.GetFirstSelected()
        if sel == -1:
            return
        user_id = self.members_list.GetItemData(sel)

        def _do():
            if approve:
                result = self.titan_client.approve_group_member(self.group_id, user_id)
            else:
                result = self.titan_client.reject_group_member(self.group_id, user_id)
            wx.CallAfter(self._on_done, result)
        threading.Thread(target=_do, daemon=True).start()

    def _on_done(self, result):
        if result.get('success'):
            play_sound('core/SELECT.ogg')
            self.load_pending()
        else:
            play_sound('core/error.ogg')
            _show_skinned_message(result.get('error', _('Operation failed')), _("Error"), wx.OK | wx.ICON_ERROR)


class ForumGroupsWindow(wx.Frame):
    """Top-level Elten-style entry: browse groups, then open a group's forums."""

    def __init__(self, parent, titan_client: TitanNetClient):
        super().__init__(parent, title=_("Titan-Net Groups"), size=(800, 600))
        self.titan_client = titan_client
        self._groups = []
        self.InitUI()
        self.Centre()
        play_sound('ui/window_open.ogg')
        from src.ui.window_switcher import register_window
        register_window("Titan-Net Groups", window=self, category='messenger')
        wx.CallAfter(self.load_groups)

    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        title_label = wx.StaticText(panel, label=_("Titan-Net Groups"))
        font = title_label.GetFont(); font.PointSize += 4; font = font.Bold()
        title_label.SetFont(font)
        vbox.Add(title_label, flag=wx.ALL | wx.ALIGN_CENTER, border=10)

        self.groups_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.groups_list.AppendColumn(_("Group"), width=300)
        self.groups_list.AppendColumn(_("Visibility"), width=120)
        self.groups_list.AppendColumn(_("Members"), width=100)
        self.groups_list.AppendColumn(_("Your status"), width=150)
        self.groups_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.OnOpenGroup)
        self.groups_list.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.groups_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=5)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (
            (_("Open"), self.OnOpenGroup),
            (_("Join"), self.OnJoin),
            (_("Leave"), self.OnLeave),
            (_("New Group"), self.OnNewGroup),
            (_("Refresh"), lambda e: (play_sound('core/SELECT.ogg'), self.load_groups())),
        ):
            btn = wx.Button(panel, label=label)
            btn.Bind(wx.EVT_BUTTON, handler)
            btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
            btn_box.Add(btn, flag=wx.RIGHT, border=5)
        vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.ALL, border=10)
        panel.SetSizer(vbox)

    def OnFocus(self, event):
        play_sound('core/FOCUS.ogg', position=0.5)
        event.Skip()

    def load_groups(self):
        def _load():
            result = self.titan_client.list_groups()
            wx.CallAfter(self._display_groups, result)
        threading.Thread(target=_load, daemon=True).start()

    _VISIBILITY_LABELS = None

    def _visibility_label(self, value):
        labels = {
            'public': _("Public"),
            'private': _("Private"),
            'hidden': _("Hidden"),
        }
        return labels.get(value, value)

    def _status_label(self, group):
        role = group.get('my_role')
        status = group.get('my_status')
        if status == 'active':
            if role == 'owner':
                return _("Owner")
            if role == 'moderator':
                return _("Moderator")
            return _("Member")
        if status == 'pending':
            return _("Pending")
        return _("Not joined")

    def _display_groups(self, result):
        self.groups_list.DeleteAllItems()
        if not result.get('success'):
            play_sound('core/error.ogg')
            _show_skinned_message(result.get('error', _('Failed to load groups')), _("Error"), wx.OK | wx.ICON_ERROR)
            return
        self._groups = result.get('groups', [])
        for group in self._groups:
            idx = self.groups_list.InsertItem(self.groups_list.GetItemCount(), group['name'])
            self.groups_list.SetItem(idx, 1, self._visibility_label(group.get('visibility')))
            self.groups_list.SetItem(idx, 2, str(group.get('member_count', 0)))
            self.groups_list.SetItem(idx, 3, self._status_label(group))
            self.groups_list.SetItemData(idx, group['id'])
        if not self._groups:
            _show_skinned_message(_("No groups yet. Create the first one!"), _("Groups"), wx.OK | wx.ICON_INFORMATION)

    def _selected_group(self):
        sel = self.groups_list.GetFirstSelected()
        if sel == -1:
            return None
        gid = self.groups_list.GetItemData(sel)
        for g in self._groups:
            if g['id'] == gid:
                return g
        return None

    def OnOpenGroup(self, event):
        play_sound('core/SELECT.ogg')
        group = self._selected_group()
        if not group:
            return
        if group.get('my_status') != 'active' and group.get('visibility') == 'hidden':
            return
        win = GroupForumsWindow(self, self.titan_client, group)
        win.Show()

    def OnJoin(self, event):
        play_sound('core/SELECT.ogg')
        group = self._selected_group()
        if not group:
            return

        def _join():
            result = self.titan_client.join_group(group['id'])
            wx.CallAfter(self._on_membership, result)
        threading.Thread(target=_join, daemon=True).start()

    def OnLeave(self, event):
        play_sound('core/SELECT.ogg')
        group = self._selected_group()
        if not group:
            return

        def _leave():
            result = self.titan_client.leave_group(group['id'])
            wx.CallAfter(self._on_membership, result)
        threading.Thread(target=_leave, daemon=True).start()

    def _on_membership(self, result):
        if result.get('success'):
            play_sound('core/SELECT.ogg')
            status = result.get('status')
            if status == 'pending':
                _show_skinned_message(_("Join request sent. Awaiting approval."), _("Groups"), wx.OK | wx.ICON_INFORMATION)
            self.load_groups()
        else:
            play_sound('core/error.ogg')
            _show_skinned_message(result.get('error', _('Operation failed')), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnNewGroup(self, event):
        play_sound('core/SELECT.ogg')
        dlg = NewGroupDialog(self, self.titan_client)
        if dlg.ShowModal() == wx.ID_OK:
            self.load_groups()
        dlg.Destroy()


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

