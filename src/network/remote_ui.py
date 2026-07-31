# -*- coding: utf-8 -*-
"""
Remote UI - render dialogs that the Titan-Net SERVER describes.

Titan-Net components sometimes need a screen that this build of Titan has
never heard of. Rather than shipping a new client and asking everybody to
update, the server sends a declarative JSON description of the dialog and
this module builds it out of ordinary wxPython widgets: labelled fields,
buttons, the active TCE skin, TCE sounds, and screen-reader announcements,
exactly like a dialog written by hand.

The client never receives or runs server code. It receives data, renders
what it recognises, and quietly skips what it does not - which is what makes
an old client able to open a screen written long after it was built.

A screen looks like::

    {"title": "Report a problem",
     "fields": [{"type": "text", "id": "subject", "label": "Subject",
                 "required": true},
                {"type": "multiline", "id": "details", "label": "Details"}],
     "buttons": [{"id": "send", "label": "Send", "action": "submit",
                  "default": true},
                 {"id": "cancel", "label": "Cancel", "action": "cancel"}]}

Pressing a submit button sends the field values back; the server answers
with what to do next (close, show a message, play a sound, correct a field,
or replace the screen entirely). See ``titan-net server/remote_ui.py`` for
the server half and the full schema.

All user-facing text is English and translated through gettext.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

import wx

from src.titan_core.translation import set_language
from src.settings.settings import get_setting
from src.titan_core.sound import (
    play_sound,
    initialize_sound,
    play_focus_sound,
    play_endoflist_sound,
)
from src.titan_core.skin_manager import apply_skin_to_window

_ = set_language(get_setting('language', 'pl'))

# The highest schema this renderer understands. Sent to the server so it can
# avoid features an older client would silently drop.
#   1 - form screens (fields + buttons) shown as a dialog
#   2 - view screens: a service window with a menu bar, tab bar, list and
#       controls, navigable exactly like the rest of Titan-Net
SCHEMA_VERSION = 2

# The client pops its own back stack instantly and then tells the server, so
# Escape never waits on the network. Must match TitanNetServer.
BACK_ACTION = '__back__'

try:
    import accessible_output3.outputs.auto as _ao_auto
    _local_speaker = _ao_auto.Auto()
except Exception as _e:  # pragma: no cover - platform dependent
    print(f"[Remote UI] accessible_output3 unavailable: {_e}")
    _local_speaker = None

try:
    initialize_sound()
except Exception as _e:
    print(f"[Remote UI] initialize_sound() failed at import: {_e}")


def speak_notification(text, notification_type='info', play_sound_effect=True):
    """Speak through titan_net_gui when it is up, else fall back to ao3."""
    if not text:
        return
    try:
        from src.network import titan_net_gui   # late import - circular safe
        helper = getattr(titan_net_gui, 'speak_notification', None)
        if helper is not None:
            helper(text, notification_type=notification_type,
                   play_sound_effect=play_sound_effect)
            return
    except Exception as e:
        print(f"[Remote UI] speak_notification helper failed: {e}")

    if play_sound_effect:
        sound_map = {
            'error': 'core/error.ogg',
            'warning': 'core/error.ogg',
            'success': 'core/SELECT.ogg',
            'info': 'ui/dialog.ogg',
        }
        try:
            play_sound(sound_map.get(notification_type, 'ui/dialog.ogg'))
        except Exception:
            pass
    if _local_speaker is not None:
        try:
            _local_speaker.speak(str(text), interrupt=True)
        except Exception:
            pass
    print(f"[Remote UI] {text}")


def _show_skinned_message(message, caption, style=wx.OK | wx.ICON_INFORMATION, parent=None):
    dlg = wx.MessageDialog(parent, message, caption, style)
    try:
        apply_skin_to_window(dlg)
    except Exception:
        pass
    result = dlg.ShowModal()
    dlg.Destroy()
    return result


def _items_of(field: Dict) -> List[Dict]:
    """Normalise a field's items, tolerating the plain-string shorthand."""
    items = field.get('items') or []
    out = []
    for entry in items:
        if isinstance(entry, dict):
            label = entry.get('label', entry.get('value'))
            out.append({'value': entry.get('value', label), 'label': str(label)})
        else:
            out.append({'value': entry, 'label': str(entry)})
    return out


# ---------------------------------------------------------------------------
# Field renderers
# ---------------------------------------------------------------------------

class _Field:
    """One rendered field: knows its widget, its value, and how to focus it."""

    def __init__(self, spec: Dict, control, label_ctrl=None):
        self.spec = spec
        self.id = spec.get('id')
        self.type = spec.get('type')
        self.control = control
        self.label_ctrl = label_ctrl
        self.error_ctrl = None

    @property
    def label(self) -> str:
        return self.spec.get('label') or self.id or ''

    def get_value(self):
        ctrl = self.control
        try:
            if self.type in ('text', 'multiline'):
                return ctrl.GetValue()
            if self.type == 'number':
                return int(ctrl.GetValue())
            if self.type == 'checkbox':
                return bool(ctrl.GetValue())
            if self.type == 'radio':
                items = _items_of(self.spec)
                index = ctrl.GetSelection()
                return items[index]['value'] if 0 <= index < len(items) else None
            if self.type in ('choice', 'list'):
                items = _items_of(self.spec)
                index = ctrl.GetSelection()
                if index is None or index < 0 or index >= len(items):
                    return None
                return items[index]['value']
        except Exception as e:
            print(f"[Remote UI] could not read field {self.id}: {e}")
        return None

    def set_value(self, value):
        ctrl = self.control
        try:
            if self.type in ('text', 'multiline'):
                ctrl.SetValue('' if value is None else str(value))
            elif self.type == 'number':
                ctrl.SetValue(int(value))
            elif self.type == 'checkbox':
                ctrl.SetValue(bool(value))
            elif self.type in ('choice', 'radio', 'list'):
                items = _items_of(self.spec)
                for index, item in enumerate(items):
                    if item['value'] == value or str(item['label']) == str(value):
                        ctrl.SetSelection(index)
                        break
        except Exception as e:
            print(f"[Remote UI] could not set field {self.id}: {e}")

    def set_items(self, items: List[Dict]):
        """Replace a choice/radio/list field's options (server-driven refresh)."""
        self.spec['items'] = items
        labels = [str(item.get('label', item.get('value'))) for item in items]
        try:
            if self.type in ('choice', 'list'):
                self.control.Set(labels)
                if labels:
                    self.control.SetSelection(0)
            elif self.type == 'radio':
                # wx.RadioBox cannot be re-populated; leave it and log, so a
                # server author finds out during testing rather than never.
                print("[Remote UI] radio items cannot be replaced after render; "
                      "use a choice field for dynamic options")
        except Exception as e:
            print(f"[Remote UI] could not update items for {self.id}: {e}")

    def focus(self):
        try:
            self.control.SetFocus()
        except Exception:
            pass

    def validate(self) -> Optional[str]:
        """Client-side check, so an obvious mistake is spoken immediately.

        The server validates again and has the last word - this only saves a
        round trip and gives instant feedback.
        """
        spec = self.spec
        if self.type in ('text', 'multiline'):
            value = self.get_value() or ''
            if spec.get('required') and not value.strip():
                return _("This field is required")
            limit = spec.get('max_length')
            if limit and len(value) > int(limit):
                return _("Maximum {n} characters").format(n=limit)
        elif self.type in ('choice', 'radio', 'list'):
            if spec.get('required') and self.get_value() is None:
                return _("Choose an option")
        return None


def _build_field(panel, vbox, spec: Dict, fields: Dict[str, _Field]):
    """Turn one field description into a labelled, accessible widget.

    Shared by the dialog renderer and the service window, so a control
    behaves and reads identically wherever a screen puts it."""
    ftype = spec.get('type')
    label_text = spec.get('label') or ''

    if ftype == 'separator':
        vbox.Add(wx.StaticLine(panel), flag=wx.EXPAND | wx.ALL, border=8)
        return None

    if ftype == 'static':
        text = spec.get('text') or label_text
        # A read-only text control instead of StaticText: screen readers
        # can move through it line by line, which matters for reports.
        ctrl = wx.TextCtrl(panel, value=str(text),
                           style=wx.TE_MULTILINE | wx.TE_READONLY)
        ctrl.SetName(label_text or _("Information"))
        vbox.Add(ctrl, proportion=1, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
                 border=10)
        return None

    # Everything below is an input, so it gets a visible label first.
    if label_text and ftype != 'radio':
        static = wx.StaticText(panel, label=label_text)
        vbox.Add(static, flag=wx.LEFT | wx.TOP, border=10)
    else:
        static = None

    control = None
    if ftype in ('text', 'multiline'):
        style = 0
        if ftype == 'multiline':
            style |= wx.TE_MULTILINE
        if spec.get('password'):
            style |= wx.TE_PASSWORD
        if spec.get('readonly'):
            style |= wx.TE_READONLY
        control = wx.TextCtrl(panel, value=str(spec.get('default') or ''), style=style)
        if spec.get('max_length') and ftype == 'text':
            try:
                control.SetMaxLength(int(spec['max_length']))
            except Exception:
                pass
        vbox.Add(control,
                 proportion=1 if ftype == 'multiline' else 0,
                 flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

    elif ftype == 'number':
        control = wx.SpinCtrl(panel,
                              min=int(spec.get('min', 0)),
                              max=int(spec.get('max', 1000000)),
                              initial=int(spec.get('default', 0)))
        vbox.Add(control, flag=wx.LEFT | wx.RIGHT, border=10)

    elif ftype == 'checkbox':
        control = wx.CheckBox(panel, label=label_text or spec.get('id'))
        control.SetValue(bool(spec.get('default')))
        vbox.Add(control, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

    elif ftype == 'radio':
        items = _items_of(spec)
        labels = [item['label'] for item in items] or [_("(no options)")]
        control = wx.RadioBox(panel, label=label_text or spec.get('id'),
                              choices=labels, majorDimension=1,
                              style=wx.RA_SPECIFY_COLS)
        vbox.Add(control, flag=wx.EXPAND | wx.ALL, border=10)

    elif ftype in ('choice', 'list'):
        items = _items_of(spec)
        labels = [item['label'] for item in items]
        if ftype == 'choice' and spec.get('style') != 'list':
            control = wx.Choice(panel, choices=labels)
        else:
            control = wx.ListBox(panel, choices=labels)
        vbox.Add(control,
                 proportion=1 if ftype == 'list' else 0,
                 flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

    else:
        # A field type this build does not know: show the label so the
        # user can see something is there, and carry on. This is what
        # lets a newer server talk to an older client.
        print(f"[Remote UI] skipping unsupported field type '{ftype}'")
        return None

    if control is not None:
        control.SetName(label_text or spec.get('id') or ftype)
        if spec.get('hint'):
            try:
                control.SetToolTip(str(spec['hint']))
            except Exception:
                pass
        field = _Field(spec, control, static)
        if field.id:
            fields[field.id] = field
        # Apply a default that came in as a value rather than a widget arg.
        if spec.get('default') is not None and ftype in ('choice', 'radio', 'list'):
            field.set_value(spec['default'])
    return control


class RemoteScreenDialog(wx.Dialog):
    """Renders one server-defined screen and round-trips its buttons.

    Nothing about this dialog is specific to any particular screen - the same
    class shows a survey, a moderation form, or a report viewer, depending
    entirely on what the server described.
    """

    def __init__(self, parent, titan_client, slug: str, definition: Dict):
        title = definition.get('title') or _("Server screen")
        size = definition.get('size') or [620, 520]
        super().__init__(parent, title=title, size=tuple(size),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.titan_client = titan_client
        self.slug = slug
        self.definition = definition
        self.fields: Dict[str, _Field] = {}
        self._busy = False
        self._default_button = None

        self._build()
        self.Centre()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        try:
            apply_skin_to_window(self)
        except Exception:
            pass
        try:
            play_sound('ui/dialog.ogg')
        except Exception:
            pass

        opening_sound = definition.get('sound')
        if opening_sound:
            self._play_server_sound(opening_sound)
        if definition.get('announce'):
            speak_notification(definition['announce'], 'info', play_sound_effect=False)

    # --- construction ---------------------------------------------------

    def _build(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        description = self.definition.get('description')
        if description:
            intro = wx.TextCtrl(panel, value=str(description),
                                style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_NO_VSCROLL)
            intro.SetName(_("Description"))
            vbox.Add(intro, flag=wx.EXPAND | wx.ALL, border=10)

        first_input = None
        for spec in self.definition.get('fields', []):
            control = self._build_field(panel, vbox, spec)
            if control is not None and first_input is None:
                if spec.get('type') not in ('static', 'separator'):
                    first_input = control

        vbox.AddStretchSpacer()

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        for spec in self.definition.get('buttons', []):
            button = wx.Button(panel, label=spec.get('label') or spec.get('id'))
            button.Bind(wx.EVT_BUTTON,
                        lambda evt, s=spec: self._on_button(s))
            btn_box.Add(button, flag=wx.ALL, border=5)
            if spec.get('default') and self._default_button is None:
                self._default_button = button
                button.SetDefault()
        vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=10)

        panel.SetSizer(vbox)
        self.Layout()
        if first_input is not None:
            first_input.SetFocus()

    def _build_field(self, panel, vbox, spec: Dict):
        return _build_field(panel, vbox, spec, self.fields)
    # --- interaction ----------------------------------------------------

    def _on_key(self, event: wx.KeyEvent):
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_ESCAPE:
            try:
                play_sound('ui/popupclose.ogg')
            except Exception:
                pass
            self.EndModal(wx.ID_CANCEL)
            return
        event.Skip()

    def _collect(self) -> Dict[str, Any]:
        return {fid: field.get_value() for fid, field in self.fields.items()}

    def _validate(self) -> bool:
        for field in self.fields.values():
            problem = field.validate()
            if problem:
                speak_notification(f"{field.label}: {problem}", 'error')
                field.focus()
                return False
        return True

    def _on_button(self, spec: Dict):
        if self._busy:
            return
        action = spec.get('action') or 'submit'

        if spec.get('confirm'):
            confirmed = _show_skinned_message(
                str(spec['confirm']), self.GetTitle(),
                wx.YES_NO | wx.ICON_QUESTION, self)
            # ShowModal() returns wx.ID_YES, never wx.YES.
            if confirmed != wx.ID_YES:
                return

        if spec.get('sound'):
            self._play_server_sound(spec['sound'])

        if action == 'cancel':
            try:
                play_sound('ui/popupclose.ogg')
            except Exception:
                pass
            self.EndModal(wx.ID_CANCEL)
            return

        if action == 'open':
            target = spec.get('screen')
            self.EndModal(wx.ID_OK)
            if target:
                wx.CallAfter(open_screen, self.GetParent(), self.titan_client, target)
            return

        values = self._collect() if action == 'submit' else {}
        if action == 'submit' and not self._validate():
            return

        try:
            play_sound('core/SELECT.ogg')
        except Exception:
            pass
        self._set_busy(True)
        button_id = spec.get('id') or action
        slug = self.slug

        def _send():
            result = self.titan_client.remote_screen_action(
                slug, button_id, values, kind=action)
            wx.CallAfter(self._on_action_result, result)

        threading.Thread(target=_send, daemon=True).start()

    def _set_busy(self, busy: bool):
        self._busy = busy
        try:
            self.SetCursor(wx.Cursor(wx.CURSOR_WAIT if busy else wx.CURSOR_ARROW))
        except Exception:
            pass

    def _on_action_result(self, response: Dict):
        self._set_busy(False)
        if not response.get('success'):
            reason = response.get('error') or _("The server could not complete that")
            speak_notification(reason, 'error')
            _show_skinned_message(reason, self.GetTitle(), wx.OK | wx.ICON_ERROR, self)
            return
        self._apply_result(response.get('result') or {})

    def _apply_result(self, result: Dict):
        """Do whatever the server's answer asked for."""
        if result.get('sound'):
            self._play_server_sound(result['sound'])

        errors = result.get('errors')
        if errors:
            first = None
            for fid, problem in errors.items():
                field = self.fields.get(fid)
                if field and first is None:
                    first = (field, problem)
            if first:
                field, problem = first
                speak_notification(f"{field.label}: {problem}", 'error')
                field.focus()
            else:
                speak_notification('; '.join(str(v) for v in errors.values()), 'error')
            return

        if isinstance(result.get('values'), dict):
            for fid, value in result['values'].items():
                field = self.fields.get(fid)
                if field:
                    field.set_value(value)
        if isinstance(result.get('items'), dict):
            for fid, items in result['items'].items():
                field = self.fields.get(fid)
                if field:
                    field.set_items(items)

        if result.get('announce'):
            speak_notification(result['announce'], 'info', play_sound_effect=False)

        # A follow-up screen replaces this one, so a wizard is just a chain of
        # ordinary screens rather than anything the client has to understand.
        follow_up = result.get('screen')
        if isinstance(follow_up, dict):
            parent = self.GetParent()
            client = self.titan_client
            slug = self.slug
            message_text = result.get('message')
            self.EndModal(wx.ID_OK)
            if message_text:
                speak_notification(message_text, 'info')
            wx.CallAfter(show_screen, parent, client, slug, follow_up)
            return

        if result.get('message'):
            speak_notification(result['message'], 'info', play_sound_effect=False)
            _show_skinned_message(result['message'], self.GetTitle(),
                                  wx.OK | wx.ICON_INFORMATION, self)

        if result.get('close'):
            self.EndModal(wx.ID_OK)

    def _play_server_sound(self, name: str):
        """Play one of the server's registered sounds by name."""
        _play_server_sound(self.titan_client, name)


def _play_server_sound(titan_client, name: str):
    try:
        from src.network import server_sounds
        server_sounds.play(titan_client, {'name': name})
    except Exception as e:
        print(f"[Remote UI] could not play server sound '{name}': {e}")


# ---------------------------------------------------------------------------
# Service window (a 'view' screen)
# ---------------------------------------------------------------------------

class RemoteServiceFrame(wx.Frame):
    """A whole Titan-Net SERVICE, described entirely by the server.

    Where a dialog is one form, this is the shape everything bigger takes: a
    menu bar, a tab bar, a list you arrow through, optional controls, and an
    action row. Firing a row asks the server what comes next, and the answer
    is just another screen - which is how a service becomes a tree of lists
    without the client knowing anything about what the service DOES.

    The interaction is deliberately identical to the Feedback Hub and the
    main Titan-Net window: row 0 is the tab bar, Left/Right cycles it,
    Enter opens, Escape goes back one level and then closes, F5 refreshes.
    Somebody who can use one Titan-Net list can use every service.
    """

    def __init__(self, parent, titan_client, slug: str, definition: Dict):
        super().__init__(parent, title=definition.get('title') or _("Service"),
                         size=tuple(definition.get('size') or [820, 620]))
        self.titan_client = titan_client
        self.slug = slug
        # Back stack: the server keeps the authoritative copy, this one makes
        # Escape instant instead of a round trip.
        self.stack: List[Dict] = [definition]
        self.fields: Dict[str, _Field] = {}
        self.rows: List[Dict] = []
        self._busy = False
        self._last_focus_idx = 0
        self._refresh_timer = None

        self.CreateStatusBar()
        self.panel = wx.Panel(self)
        self.listbox = None
        self._render()

        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Centre()
        self.Show()
        try:
            play_sound('ui/dialog.ogg')
        except Exception:
            pass

    # --- current screen -------------------------------------------------

    @property
    def current(self) -> Dict:
        return self.stack[-1]

    # --- rendering ------------------------------------------------------

    def _render(self):
        """Rebuild the whole window for whatever screen is on top of the stack.

        Rebuilding rather than patching keeps a service that swaps its menus
        or tabs between screens honest - there is no stale widget left over
        from the previous level.
        """
        screen = self.current
        self.SetTitle(screen.get('title') or _("Service"))
        self.fields.clear()

        self.panel.DestroyChildren()
        vbox = wx.BoxSizer(wx.VERTICAL)

        self._build_menu_bar(screen)

        description = screen.get('description')
        if description:
            intro = wx.TextCtrl(self.panel, value=str(description),
                                style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_NO_VSCROLL,
                                size=(-1, 60))
            intro.SetName(_("Description"))
            vbox.Add(intro, flag=wx.EXPAND | wx.ALL, border=8)

        # Controls (search boxes, filters) sit above the list, like the rest
        # of Titan-Net's views.
        for spec in screen.get('fields', []):
            _build_field(self.panel, vbox, spec, self.fields)

        self.listbox = wx.ListBox(self.panel)
        self.listbox.Bind(wx.EVT_LISTBOX, self._on_select)
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._activate_row())
        vbox.Add(self.listbox, proportion=1, flag=wx.EXPAND | wx.ALL, border=8)

        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        for spec in screen.get('buttons', []):
            button = wx.Button(self.panel, label=spec.get('label') or spec.get('id'))
            button.Bind(wx.EVT_BUTTON, lambda e, s=spec: self._on_button(s))
            btn_box.Add(button, flag=wx.ALL, border=4)
            if spec.get('default'):
                button.SetDefault()
        if btn_box.GetItemCount():
            vbox.Add(btn_box, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=8)

        self.panel.SetSizer(vbox)
        self.panel.Layout()
        try:
            apply_skin_to_window(self)
        except Exception:
            pass

        self._fill_list()
        self._arm_auto_refresh(screen)

        if screen.get('sound'):
            _play_server_sound(self.titan_client, screen['sound'])
        if screen.get('announce'):
            speak_notification(screen['announce'], 'info', play_sound_effect=False)

    def _build_menu_bar(self, screen: Dict):
        """Build the Alt-reachable menu bar the server described."""
        menus = screen.get('menus') or []
        if not menus:
            self.SetMenuBar(wx.MenuBar())
            return
        menubar = wx.MenuBar()
        for menu_spec in menus:
            menu = wx.Menu()
            for item_spec in menu_spec.get('items', []):
                if item_spec.get('separator'):
                    menu.AppendSeparator()
                    continue
                item = menu.Append(wx.ID_ANY, item_spec.get('label') or item_spec.get('id'))
                self.Bind(wx.EVT_MENU,
                          lambda e, s=item_spec: self._on_menu_item(s), item)
            menubar.Append(menu, menu_spec.get('label') or '')
        self.SetMenuBar(menubar)

    def _tab_bar_text(self) -> str:
        tabs = self.current.get('tabs') or []
        active = self.current.get('active_tab')
        index = next((i for i, t in enumerate(tabs) if t['id'] == active), 0)
        label = tabs[index]['label'] if tabs else ''
        return _("{}, {} of {}").format(label, index + 1, len(tabs))

    def _has_tab_bar(self) -> bool:
        return bool(self.current.get('tabs'))

    def _is_tab_bar_row(self, idx: int) -> bool:
        """Row 0 is the virtual tab bar - same contract as the Feedback Hub."""
        if idx != 0 or not self.listbox or self.listbox.GetCount() == 0:
            return False
        try:
            data = self.listbox.GetClientData(0)
        except Exception:
            return False
        return isinstance(data, dict) and data.get('type') == 'tab_bar'

    def _format_row(self, row: Dict) -> str:
        label = row.get('label', '?')
        sublabel = row.get('sublabel')
        return f"{label}, {sublabel}" if sublabel else label

    def _fill_list(self, keep_position: bool = False):
        screen = self.current
        previous = self.listbox.GetSelection() if keep_position else -1

        self.rows = list(screen.get('items') or [])
        self.listbox.Clear()
        if self._has_tab_bar():
            self.listbox.Append(self._tab_bar_text(), {'type': 'tab_bar'})
        for row in self.rows:
            self.listbox.Append(self._format_row(row), row)

        count = self.listbox.GetCount()
        if count:
            # After a refresh, stay where the user was - losing the cursor
            # position is disorienting when the list is read aloud.
            target = previous if 0 <= previous < count else 0
            self.listbox.SetSelection(target)
            self._last_focus_idx = target
        self.listbox.SetFocus()

        status = screen.get('status')
        if not self.rows and not status:
            status = screen.get('empty') or _("This list is empty")
        self.SetStatusText(str(status or ''))
        if status and not keep_position:
            speak_notification(str(status), 'info', play_sound_effect=False)

    def _arm_auto_refresh(self, screen: Dict):
        if self._refresh_timer is not None:
            self._refresh_timer.Stop()
            self._refresh_timer = None
        seconds = screen.get('refresh_seconds')
        if not seconds:
            return
        self._refresh_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda e: self._refresh(), self._refresh_timer)
        self._refresh_timer.Start(int(seconds) * 1000)

    # --- interaction ----------------------------------------------------

    def _values(self) -> Dict[str, Any]:
        return {fid: field.get_value() for fid, field in self.fields.items()}

    def _selected_row(self) -> Optional[Dict]:
        idx = self.listbox.GetSelection()
        if idx == wx.NOT_FOUND or self._is_tab_bar_row(idx):
            return None
        offset = 1 if self._has_tab_bar() else 0
        row_idx = idx - offset
        if 0 <= row_idx < len(self.rows):
            return self.rows[row_idx]
        return None

    def _activate_row(self):
        row = self._selected_row()
        if row is None:
            return
        if row.get('sound'):
            _play_server_sound(self.titan_client, row['sound'])
        try:
            play_sound('core/SELECT.ogg')
        except Exception:
            pass
        values = self._values()
        values['item'] = row.get('id')
        self._fire(row.get('action') or 'activate', values, kind='activate')

    def _cycle_tab(self, direction: int):
        tabs = self.current.get('tabs') or []
        if not tabs:
            return
        active = self.current.get('active_tab')
        index = next((i for i, t in enumerate(tabs) if t['id'] == active), 0)
        new_index = index + direction
        if new_index < 0 or new_index >= len(tabs):
            try:
                play_sound('ui/endoftapbar.ogg')
            except Exception:
                pass
            return
        try:
            play_sound('ui/switch_list.ogg')
        except Exception:
            pass
        new_tab = tabs[new_index]['id']
        self.current['active_tab'] = new_tab
        self.listbox.SetString(0, self._tab_bar_text())
        # Ask the service for that tab's rows. A service that ignores the
        # 'tab' action simply keeps the list it already had.
        values = self._values()
        values['tab'] = new_tab
        self._fire('tab', values, kind='action', quiet=True)

    def _refresh(self):
        self._fire('refresh', self._values(), kind='action', quiet=True)

    def _go_back(self) -> bool:
        """Pop one level. Returns False when there is nowhere left to go."""
        if len(self.stack) <= 1:
            return False
        self.stack.pop()
        try:
            play_sound('ui/popupclose.ogg')
        except Exception:
            pass
        self._render()
        # Tell the server we moved, so its copy validates the right screen.
        slug = self.slug
        client = self.titan_client

        def _notify():
            try:
                client.remote_screen_action(slug, BACK_ACTION, {}, kind='action')
            except Exception as e:
                print(f"[Remote UI] back notification failed: {e}")

        threading.Thread(target=_notify, daemon=True).start()
        return True

    def _on_key(self, event: wx.KeyEvent):
        keycode = event.GetKeyCode()
        modifiers = event.GetModifiers()
        focus = self.FindFocus()

        if keycode == wx.WXK_ESCAPE and modifiers == wx.MOD_NONE:
            if not self._go_back():
                self.Close()
            return
        if keycode == wx.WXK_F5:
            self._refresh()
            return
        if keycode == wx.WXK_TAB and modifiers == wx.MOD_CONTROL:
            self._cycle_tab(+1)
            return
        if keycode == wx.WXK_TAB and modifiers == (wx.MOD_CONTROL | wx.MOD_SHIFT):
            self._cycle_tab(-1)
            return

        if focus is not self.listbox:
            event.Skip()
            return

        idx = self.listbox.GetSelection()
        count = self.listbox.GetCount()

        if keycode in (wx.WXK_LEFT, wx.WXK_RIGHT):
            # Left/Right is the tab bar's, and nothing else's - swallowing it
            # on regular rows stops it silently moving the selection.
            if self._is_tab_bar_row(idx):
                self._cycle_tab(-1 if keycode == wx.WXK_LEFT else +1)
            return
        if keycode in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and not event.AltDown():
            self._activate_row()
            return

        # Manual arrow handling so every move plays the same stereo focus cue
        # as the main Titan-Net lists (EVT_LISTBOX does not fire for
        # programmatic SetSelection on Windows).
        new_idx = idx
        if keycode == wx.WXK_UP:
            new_idx = idx - 1
        elif keycode == wx.WXK_DOWN:
            new_idx = idx + 1
        elif keycode == wx.WXK_HOME:
            new_idx = 0
        elif keycode == wx.WXK_END:
            new_idx = count - 1
        else:
            event.Skip()
            return

        if 0 <= new_idx < count and new_idx != idx:
            self.listbox.SetSelection(new_idx)
            self._emit_focus_feedback(new_idx)
        else:
            try:
                play_endoflist_sound()
            except Exception:
                pass

    def _emit_focus_feedback(self, idx: int):
        if self._is_tab_bar_row(idx):
            _announce_tab_bar()
            self._last_focus_idx = idx
            return
        offset = 1 if self._has_tab_bar() else 0
        real_count = max(0, self.listbox.GetCount() - offset)
        pan = 0.0
        if real_count > 1:
            pan = (idx - offset) / (real_count - 1)
        try:
            play_focus_sound(pan=max(0.0, min(1.0, pan)))
        except Exception:
            pass
        self._last_focus_idx = idx

    def _on_select(self, event):
        idx = self.listbox.GetSelection()
        if idx >= 0:
            self._emit_focus_feedback(idx)

    def _on_button(self, spec: Dict):
        action = spec.get('action') or 'submit'
        if spec.get('confirm'):
            # ShowModal() returns wx.ID_YES, never wx.YES.
            if _show_skinned_message(str(spec['confirm']), self.GetTitle(),
                                     wx.YES_NO | wx.ICON_QUESTION, self) != wx.ID_YES:
                return
        if spec.get('sound'):
            _play_server_sound(self.titan_client, spec['sound'])

        if action == 'cancel':
            if not self._go_back():
                self.Close()
            return
        if action == 'open':
            target = spec.get('screen')
            if target:
                open_screen(self, self.titan_client, target)
            return
        values = self._values() if action == 'submit' else {}
        if action == 'submit' and not self._validate():
            return
        self._fire(spec.get('id') or action, values, kind=action)

    def _on_menu_item(self, spec: Dict):
        action = spec.get('action') or 'menu'
        if spec.get('confirm'):
            if _show_skinned_message(str(spec['confirm']), self.GetTitle(),
                                     wx.YES_NO | wx.ICON_QUESTION, self) != wx.ID_YES:
                return
        if spec.get('sound'):
            _play_server_sound(self.titan_client, spec['sound'])

        if action == 'close':
            self.Close()
            return
        if action == 'refresh':
            self._refresh()
            return
        if action == 'open':
            if spec.get('screen'):
                open_screen(self, self.titan_client, spec['screen'])
            return
        if action == 'submit' and not self._validate():
            return
        values = self._values()
        # A menu item usually acts on whatever row the user is sitting on, so
        # send it along - a service can ignore it.
        row = self._selected_row()
        if row is not None:
            values['item'] = row.get('id')
        self._fire(spec.get('id') or action, values,
                   kind='submit' if action == 'submit' else 'action')

    def _validate(self) -> bool:
        for field in self.fields.values():
            problem = field.validate()
            if problem:
                speak_notification(f"{field.label}: {problem}", 'error')
                field.focus()
                return False
        return True

    def _fire(self, action: str, values: Dict, kind: str = 'submit',
              quiet: bool = False):
        if self._busy:
            return
        self._busy = True
        slug = self.slug

        def _send():
            result = self.titan_client.remote_screen_action(slug, action, values, kind=kind)
            wx.CallAfter(self._on_action_result, result, quiet)

        threading.Thread(target=_send, daemon=True).start()

    def _on_action_result(self, response: Dict, quiet: bool = False):
        self._busy = False
        if not response.get('success'):
            reason = response.get('error') or _("The server could not complete that")
            speak_notification(reason, 'error')
            if not quiet:
                _show_skinned_message(reason, self.GetTitle(), wx.OK | wx.ICON_ERROR, self)
            return
        self._apply_result(response.get('result') or {}, quiet)

    def _apply_result(self, result: Dict, quiet: bool = False):
        if result.get('sound'):
            _play_server_sound(self.titan_client, result['sound'])

        errors = result.get('errors')
        if errors:
            for fid, problem in errors.items():
                field = self.fields.get(fid)
                if field:
                    speak_notification(f"{field.label}: {problem}", 'error')
                    field.focus()
                    return
            speak_notification('; '.join(str(v) for v in errors.values()), 'error')
            return

        if isinstance(result.get('values'), dict):
            for fid, value in result['values'].items():
                field = self.fields.get(fid)
                if field:
                    field.set_value(value)

        if result.get('announce'):
            speak_notification(result['announce'], 'info', play_sound_effect=False)

        follow_up = result.get('screen')
        if isinstance(follow_up, dict):
            if follow_up.get('kind') == 'view':
                if result.get('restored'):
                    # The server handed back the screen we returned to; our
                    # own pop already happened, so just redraw.
                    self.stack[-1] = follow_up
                else:
                    self.stack.append(follow_up)
                self._render()
            else:
                # A form opened from a service is a modal on top of it, and
                # closing it comes back here.
                dialog = RemoteScreenDialog(self, self.titan_client, self.slug, follow_up)
                try:
                    dialog.ShowModal()
                finally:
                    dialog.Destroy()
                self._refresh()
        elif result.get('refresh'):
            # In-place list update: keep the user exactly where they were.
            if isinstance(result.get('items'), list):
                self.current['items'] = result['items']
            if result.get('status') is not None:
                self.current['status'] = result['status']
            self._fill_list(keep_position=True)
        elif result.get('back'):
            if not self._go_back():
                self.Close()
                return

        if result.get('message'):
            speak_notification(result['message'], 'info', play_sound_effect=False)
            if not quiet:
                _show_skinned_message(result['message'], self.GetTitle(),
                                      wx.OK | wx.ICON_INFORMATION, self)

        if result.get('close'):
            self.Close()

    def _on_close(self, event):
        if self._refresh_timer is not None:
            try:
                self._refresh_timer.Stop()
            except Exception:
                pass
        try:
            play_sound('ui/popupclose.ogg')
        except Exception:
            pass
        event.Skip()


def _announce_tab_bar():
    """Speak the 'Tab bar' marker the way the rest of Titan-Net does."""
    try:
        play_sound('ui/tapbar.ogg')
    except Exception:
        pass
    if _is_screen_reader_running():
        speak_notification(_("Tab bar"), 'info', play_sound_effect=False)


def _is_screen_reader_running() -> bool:
    """Only real screen readers get the 'Tab bar' hint - not SAPI fallbacks."""
    try:
        from src.ui.gui import _is_screen_reader_running as _check
        return bool(_check())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def show_screen(parent, titan_client, slug: str, definition: Dict):
    """Show an already-fetched screen definition.

    A 'view' becomes a service window; anything else is a form dialog. The
    caller does not need to know which - the server decided.
    """
    if not isinstance(definition, dict) or not definition.get('title'):
        speak_notification(_("The server sent a screen this client cannot show"), 'error')
        return
    # A kind this build has never heard of degrades to the form renderer
    # rather than refusing to open - the same reasoning as unknown fields.
    kind = definition.get('kind') or 'dialog'
    if kind == 'view':
        RemoteServiceFrame(parent, titan_client, slug, definition)
        return
    if kind != 'dialog':
        print(f"[Remote UI] unknown screen kind '{kind}', showing it as a form")
    dialog = RemoteScreenDialog(parent, titan_client, slug, definition)
    try:
        dialog.ShowModal()
    finally:
        dialog.Destroy()


def open_screen(parent, titan_client, slug: str):
    """Fetch a screen from the server and show it.

    The fetch runs on a worker thread, so the GUI never freezes on a slow
    link; the dialog appears when the definition arrives.
    """
    if titan_client is None:
        speak_notification(_("Not connected to Titan-Net"), 'error')
        return

    def _fetch():
        result = titan_client.open_remote_screen(slug)
        wx.CallAfter(_show, result)

    def _show(result: Dict):
        if not result.get('success'):
            reason = result.get('error') or _("Could not open that screen")
            speak_notification(reason, 'error')
            return
        payload = result.get('result') or {}
        if payload.get('sound'):
            try:
                from src.network import server_sounds
                server_sounds.play(titan_client, {'name': payload['sound']})
            except Exception:
                pass
        definition = payload.get('screen')
        if not definition:
            if payload.get('message'):
                speak_notification(payload['message'], 'info')
            return
        show_screen(parent, titan_client, slug, definition)

    threading.Thread(target=_fetch, daemon=True).start()


def handle_push(parent, titan_client, message: Dict):
    """The server opened a screen on us without being asked."""
    slug = message.get('slug')
    definition = message.get('screen')
    if not slug or not isinstance(definition, dict):
        return
    wx.CallAfter(show_screen, parent, titan_client, slug, definition)


def list_menu_screens(titan_client) -> List[Dict]:
    """Screens that asked to appear in the client's menu.

    Returns an empty list on any failure - a server without Remote UI, or an
    unreachable one, simply contributes no menu entries.
    """
    if titan_client is None:
        return []
    try:
        result = titan_client.list_remote_screens()
    except Exception as e:
        print(f"[Remote UI] could not list screens: {e}")
        return []
    if not result.get('success'):
        return []
    return [screen for screen in result.get('screens', [])
            if screen.get('in_menu')]
