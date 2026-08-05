# -*- coding: utf-8 -*-
"""The two places bookmarks are used from: a dialog inside the player and a
top-level view listing everything TMedia can be resumed.

Both are plain lists of readable lines rather than a grid, so a screen reader
announces the whole bookmark ("chapter 4, track 12, 1:23:45") in one go, the
way the rest of Titan's lists behave.
"""

import wx

from translation import _

import bookmarks
import common


def position_label(kind, track, track_title, position, total_tracks=0):
    """One readable position: a time for a single file, and the track it is
    in for an audiobook (which is the only thing that makes a bookmark in a
    multi-file book meaningful)."""
    time_text = common.format_time(position)
    if kind != 'audiobook':
        return time_text
    number = int(track or 0) + 1
    if total_tracks:
        where = _("Track %(number)d of %(total)d") % {'number': number,
                                                      'total': total_tracks}
    else:
        where = _("Track %d") % number
    if track_title:
        where = "%s: %s" % (where, track_title)
    return "%s - %s" % (where, time_text)


def entry_position_label(entry, place):
    """``place`` is a resume point or a bookmark from ``entry``."""
    return position_label(entry.get('kind'), place.get('track', 0),
                          place.get('track_title', ''),
                          place.get('position', 0),
                          len(entry.get('tracks') or []))


class BookmarksDialog(wx.Dialog):
    """The bookmarks of ONE media item: the automatic resume point first,
    then every named bookmark. Enter jumps, Delete removes, F2 renames."""

    def __init__(self, parent, store, media_id, kind='file', title=None,
                 current=None, tracks=None):
        super(BookmarksDialog, self).__init__(
            parent, title=_("Bookmarks: %s") % (title or ''), size=(560, 420))

        self.store = store
        self.media_id = media_id
        self.kind = kind
        self.media_title = title
        self.current = current          # {'track', 'position', 'track_title'}
        self.tracks = tracks or []
        self.places = []                # rows: ('resume'|'bookmark', data)
        self.result = None              # (track, position) once Go to is used

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        label = wx.StaticText(panel, label=_("Bookmarks"))
        vbox.Add(label, flag=wx.LEFT | wx.TOP, border=10)

        self.list_box = wx.ListBox(panel)
        self.list_box.SetName(_("Bookmarks"))
        vbox.Add(self.list_box, proportion=1,
                 flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.go_button = wx.Button(panel, wx.ID_OK, _("Go to"))
        self.go_button.SetDefault()
        buttons.Add(self.go_button, flag=wx.RIGHT, border=5)
        self.add_button = wx.Button(panel, label=_("Add here"))
        buttons.Add(self.add_button, flag=wx.RIGHT, border=5)
        self.rename_button = wx.Button(panel, label=_("Rename"))
        buttons.Add(self.rename_button, flag=wx.RIGHT, border=5)
        self.delete_button = wx.Button(panel, label=_("Delete"))
        buttons.Add(self.delete_button, flag=wx.RIGHT, border=5)
        buttons.Add(wx.Button(panel, wx.ID_CANCEL, _("Close")))
        vbox.Add(buttons, flag=wx.ALL, border=10)

        panel.SetSizer(vbox)
        common.apply_skin(self)

        self.add_button.Enable(bool(current))
        self.list_box.Bind(wx.EVT_LISTBOX_DCLICK, self.on_go)
        self.go_button.Bind(wx.EVT_BUTTON, self.on_go)
        self.add_button.Bind(wx.EVT_BUTTON, self.on_add)
        self.rename_button.Bind(wx.EVT_BUTTON, self.on_rename)
        self.delete_button.Bind(wx.EVT_BUTTON, self.on_delete)
        self.list_box.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)

        self.refresh()

    # ------------------------------------------------------------------ #
    def refresh(self, select=0):
        entry = self.store.get_entry(self.media_id) or {}
        if not entry.get('kind'):
            entry['kind'] = self.kind
        if not entry.get('tracks') and self.tracks:
            entry['tracks'] = self.tracks
        self.places = []
        self.list_box.Clear()

        resume = entry.get('resume')
        if resume and resume.get('position'):
            self.places.append(('resume', resume))
            self.list_box.Append(_("Resume point - %s")
                                 % entry_position_label(entry, resume))
        for bookmark in entry.get('bookmarks') or []:
            self.places.append(('bookmark', bookmark))
            self.list_box.Append("%s - %s" % (
                bookmark.get('name') or _("Bookmark"),
                entry_position_label(entry, bookmark)))

        has_places = bool(self.places)
        if not has_places:
            self.list_box.Append(_("No bookmarks yet"))
        self.go_button.Enable(has_places)
        self.rename_button.Enable(has_places)
        self.delete_button.Enable(has_places)
        if self.list_box.GetCount():
            self.list_box.SetSelection(min(max(select, 0),
                                           self.list_box.GetCount() - 1))
        self.list_box.SetFocus()

    def _selected(self):
        index = self.list_box.GetSelection()
        if index == wx.NOT_FOUND or index >= len(self.places):
            return None, None
        return self.places[index]

    # ------------------------------------------------------------------ #
    def on_go(self, event):
        kind, place = self._selected()
        if not place:
            return
        self.result = (int(place.get('track', 0)), int(place.get('position', 0)))
        common.play_sound('enter')
        if self.IsModal():
            self.EndModal(wx.ID_OK)
        else:
            self.Hide()

    def on_add(self, event):
        if not self.current:
            return
        default = _("Bookmark %s") % common.format_time(self.current.get('position', 0))
        dlg = wx.TextEntryDialog(self, _("Bookmark name"), _("Add bookmark"), default)
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip() or default
            self.store.add_bookmark(self.media_id, name,
                                    self.current.get('position', 0),
                                    track=self.current.get('track', 0),
                                    track_title=self.current.get('track_title', ''),
                                    title=self.media_title, kind=self.kind,
                                    tracks=self.tracks)
            common.play_sound('done')
            common.speak(_("Bookmark added"))
            self.refresh(self.list_box.GetCount())
        dlg.Destroy()

    def on_rename(self, event):
        kind, place = self._selected()
        if kind != 'bookmark':
            common.speak(_("The resume point cannot be renamed"))
            return
        index = self.list_box.GetSelection()
        dlg = wx.TextEntryDialog(self, _("Bookmark name"), _("Rename bookmark"),
                                 place.get('name', ''))
        if dlg.ShowModal() == wx.ID_OK:
            self.store.rename_bookmark(self.media_id, place.get('id'),
                                       dlg.GetValue().strip())
            self.refresh(index)
        dlg.Destroy()

    def on_delete(self, event):
        kind, place = self._selected()
        if not place:
            return
        index = self.list_box.GetSelection()
        if kind == 'resume':
            self.store.clear_resume(self.media_id)
            common.speak(_("Resume point removed"))
        else:
            self.store.remove_bookmark(self.media_id, place.get('id'))
            common.speak(_("Bookmark removed"))
        common.play_sound('click')
        self.refresh(max(0, index - 1))

    def on_key_down(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_RETURN:
            self.on_go(event)
        elif key == wx.WXK_DELETE:
            self.on_delete(event)
        elif key == wx.WXK_F2:
            self.on_rename(event)
        else:
            event.Skip()


class BookmarksPanel(wx.Panel):
    """Root view listing every film, recording and audiobook TMedia can pick
    up again - the point of the whole feature: nothing has to be found in the
    catalog tree a second time."""

    def __init__(self, parent, owner, *args, **kwargs):
        super(BookmarksPanel, self).__init__(parent, *args, **kwargs)
        self.owner = owner
        self.store = bookmarks.get_store()
        self.entries = []

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.info = wx.StaticText(self, label=_("Bookmarks and resume points"))
        vbox.Add(self.info, flag=wx.LEFT | wx.TOP, border=10)

        self.list_box = wx.ListBox(self)
        self.list_box.SetName(_("Bookmarks and resume points"))
        vbox.Add(self.list_box, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.play_button = wx.Button(self, label=_("Resume"))
        buttons.Add(self.play_button, flag=wx.RIGHT, border=5)
        self.bookmarks_button = wx.Button(self, label=_("Bookmarks..."))
        buttons.Add(self.bookmarks_button, flag=wx.RIGHT, border=5)
        self.forget_button = wx.Button(self, label=_("Forget"))
        buttons.Add(self.forget_button)
        vbox.Add(buttons, flag=wx.LEFT | wx.BOTTOM, border=10)

        self.SetSizer(vbox)
        common.apply_skin(self)

        self.list_box.Bind(wx.EVT_LISTBOX_DCLICK, self.on_play)
        self.play_button.Bind(wx.EVT_BUTTON, self.on_play)
        self.bookmarks_button.Bind(wx.EVT_BUTTON, self.on_bookmarks)
        self.forget_button.Bind(wx.EVT_BUTTON, self.on_forget)
        self.list_box.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)

        self.refresh()

    def focus_default(self):
        self.refresh()
        self.list_box.SetFocus()

    # ------------------------------------------------------------------ #
    def refresh(self, select=0):
        self.store.load()
        self.entries = self.store.entries()
        self.list_box.Clear()
        for entry in self.entries:
            self.list_box.Append(self._describe(entry))
        if not self.entries:
            self.list_box.Append(_("Nothing to resume yet"))
            self.info.SetLabel(_("Nothing to resume yet. Positions are saved "
                                 "automatically while you listen."))
        else:
            self.info.SetLabel(_("%d items") % len(self.entries))
        if self.list_box.GetCount():
            self.list_box.SetSelection(min(max(select, 0),
                                           self.list_box.GetCount() - 1))
        enabled = bool(self.entries)
        for button in (self.play_button, self.bookmarks_button, self.forget_button):
            button.Enable(enabled)

    def _describe(self, entry):
        title = entry.get('title') or entry.get('url') or ''
        parts = [title]
        if entry.get('kind') == 'audiobook':
            parts.append(_("audiobook"))
        resume = entry.get('resume')
        if resume and resume.get('position'):
            parts.append(entry_position_label(entry, resume))
        count = len(entry.get('bookmarks') or [])
        if count:
            parts.append(_("%d bookmarks") % count)
        return " - ".join(p for p in parts if p)

    def _selected(self):
        index = self.list_box.GetSelection()
        if index == wx.NOT_FOUND or index >= len(self.entries):
            return None
        return self.entries[index]

    # ------------------------------------------------------------------ #
    def _start(self, entry, start=None):
        url = entry.get('url')
        if not url:
            return
        title = entry.get('title')
        common.play_sound('enter')
        if entry.get('kind') == 'audiobook':
            self.owner.play_folder(url, title, start=start,
                                   fallback_tracks=entry.get('tracks'))
        else:
            self.owner.play_media(url, title,
                                  start_position=start[1] if start else None)

    def on_play(self, event):
        entry = self._selected()
        if entry:
            self._start(entry)

    def on_bookmarks(self, event):
        entry = self._selected()
        if not entry:
            return
        dlg = BookmarksDialog(self, self.store, entry.get('url'),
                              kind=entry.get('kind', 'file'),
                              title=entry.get('title'),
                              tracks=entry.get('tracks'))
        result = dlg.ShowModal()
        chosen = dlg.result
        dlg.Destroy()
        if result == wx.ID_OK and chosen:
            self._start(entry, start=chosen)
        else:
            self.refresh(self.list_box.GetSelection())

    def on_forget(self, event):
        entry = self._selected()
        if not entry:
            return
        index = self.list_box.GetSelection()
        self.store.forget(entry.get('url'))
        common.play_sound('click')
        common.speak(_("Removed"))
        self.refresh(max(0, index - 1))

    def on_key_down(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_RETURN:
            self.on_play(event)
        elif key == wx.WXK_DELETE:
            self.on_forget(event)
        elif key == wx.WXK_F5:
            self.refresh(self.list_box.GetSelection())
        elif key in (ord('B'), ord('b')) and not event.HasModifiers():
            self.on_bookmarks(event)
        elif key == wx.WXK_ESCAPE:
            self.owner.go_back()
        else:
            event.Skip()
