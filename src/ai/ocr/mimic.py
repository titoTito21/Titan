# -*- coding: utf-8 -*-
"""The accessible window that stands in for an inaccessible one.

What the user gets is an ordinary Titan list view - the same one Titan-Net, the
Feedback Hub and the Titan IM clients use, so it needs no learning: row 0 is
the tab bar, Left and Right cycle it, Enter activates, Escape goes back a level
and then closes, F5 looks again. Regions of the real screen become tabs;
controls become rows; Enter on a row presses the real control.

Three things beyond that are what make it usable rather than merely correct:

* **Everything tab.** A screen split into five regions is five key presses away
  from the thing you want. The first tab is always the whole screen flattened
  in reading order.
* **Live mode.** Watching a screen that changes by itself - a game's HUD, a
  progress bar, a match timer - and announcing only what changed. Re-reading
  the whole thing every few seconds would be unusable; "Health 40" the moment
  it drops is the point.
* **Ask about this screen.** A free-text question answered against a fresh
  reading, for when the structured list is not the shape of what you wanted to
  know ("is there a Skip button anywhere?").

The window never steals focus from the app it is reading except when the user
asks it to act, and it remembers which window it was opened for, so a scan
after alt-tabbing still reads the right program.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import wx

from src.ai import ai_provider
from src.ai.ocr import actions as actions_mod
from src.ai.ocr import capture as capture_mod
from src.ai.ocr import overlay as overlay_mod
from src.ai.ocr.form_view import ScreenForm, has_real_controls
from src.ai.ocr.model import Element, Region, Screen, elements_as_lines
from src.ai.ocr.recognizer import Reader
from src.network.im_ui_common import (
    TabbedListFrame, _, apply_skin_tree, show_message, speak_notification,
    speak_titannet,
)

TAB_ALL = '__all__'
TAB_SUMMARY = '__summary__'

# Keys the mimic can send straight into the target window. A custom-drawn menu
# usually answers these even when it exposes nothing readable at all.
PASS_THROUGH_KEYS = (
    ('escape', lambda: _("Escape")),
    ('enter', lambda: _("Enter")),
    ('tab', lambda: _("Tab")),
    ('up', lambda: _("Up arrow")),
    ('down', lambda: _("Down arrow")),
    ('left', lambda: _("Left arrow")),
    ('right', lambda: _("Right arrow")),
    ('space', lambda: _("Space")),
)


class _Note:
    """A row that is text rather than a control (the summary, a warning)."""

    def __init__(self, text: str, kind: str = 'note'):
        self.text = text
        self.kind = kind


class AIOcrFrame(TabbedListFrame):
    """The mimic window."""

    VIEW_ID = 'titan_ai_ocr'
    LIST_LABEL = _("What is on the screen:")

    def __init__(self, parent, scope: str = 'window', target_hwnd: int = 0,
                 target_title: str = '', start_overlay: bool = False):
        self.scope = scope or ai_provider.get_ocr_scope()
        self.reader = Reader()
        self.screen: Optional[Screen] = None
        # Remembered by the caller *before* this window existed. The mimic
        # opens on top of the program it is about, so "the window in front" is
        # this window a moment later - scanning that would photograph Titan
        # reading Titan, which is the one bug this feature cannot survive.
        self.target_hwnd = int(target_hwnd or 0)
        self.target_title = target_title or ''
        self._live_timer: Optional[wx.Timer] = None
        self._scanning = False
        self._last_announced = 0.0
        # 'list' reads a screen out; 'form' rebuilds it from real wx controls.
        # Which one a fresh reading lands in is decided by what is on the
        # screen - see _choose_view.
        self.view_mode = 'list'
        self._view_chosen = False
        # The overlay is the third view, and the only one that is not in this
        # window at all: it hooks the controls onto the real window and this
        # window steps aside until the user comes back from it.
        self._start_overlay = bool(start_overlay)
        self._overlay = None

        super().__init__(parent, title=self._title_text(), size=(940, 700))

        self.build_menu()
        # Scan after Show(), so the user is already sitting in a real window
        # (and hears the progress) while the reading runs.
        wx.CallLater(120, self.rescan)

    # ------------------------------------------------------------------ setup
    def build_tabs(self) -> Sequence[Tuple[str, str]]:
        tabs = [(TAB_ALL, _("Everything")), (TAB_SUMMARY, _("Summary"))]
        if self.screen is not None:
            for region in self.screen.regions:
                tabs.append(('region:' + region.label, region.label))
        return tabs

    def build_toolbar(self, sizer: wx.BoxSizer) -> None:
        row = wx.BoxSizer(wx.HORIZONTAL)

        scan = wx.Button(self.panel, label=_("Read the screen again"))
        scan.Bind(wx.EVT_BUTTON, lambda e: self.rescan())
        row.Add(scan, flag=wx.RIGHT, border=6)

        ask = wx.Button(self.panel, label=_("Ask about this screen"))
        ask.Bind(wx.EVT_BUTTON, lambda e: self.ask())
        row.Add(ask, flag=wx.RIGHT, border=6)

        self.view_button = wx.Button(self.panel, label=_("Rebuilt controls"))
        self.view_button.Bind(wx.EVT_BUTTON, lambda e: self.toggle_view())
        row.Add(self.view_button, flag=wx.RIGHT, border=6)

        overlay_button = wx.Button(self.panel, label=_("Put controls on the real window"))
        overlay_button.Bind(wx.EVT_BUTTON, lambda e: self.open_overlay())
        row.Add(overlay_button, flag=wx.RIGHT, border=6)

        close = wx.Button(self.panel, label=_("Close"))
        close.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        row.Add(close)
        sizer.Add(row, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=8)

    def build_footer(self, sizer: wx.BoxSizer) -> None:
        # The form lives below the list and the two swap places: one sizer, one
        # of them hidden. Building it here (a hook the base class calls while
        # laying the window out) keeps the base class unaware of it entirely.
        self.region_label = wx.StaticText(self.panel, label=_("Part of the screen:"))
        sizer.Add(self.region_label, flag=wx.LEFT | wx.RIGHT | wx.TOP, border=8)

        self.region_choice = wx.Choice(self.panel, choices=[])
        self.region_choice.SetName(_("Part of the screen"))
        self.region_choice.Bind(wx.EVT_CHOICE, lambda e: self._region_picked())
        sizer.Add(self.region_choice, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=8)

        self.form = ScreenForm(self.panel, self._on_form_action)
        sizer.Add(self.form, proportion=1, flag=wx.EXPAND | wx.ALL, border=8)

        self.region_label.Hide()
        self.region_choice.Hide()
        self.form.Hide()

    def build_menu(self) -> None:
        bar = wx.MenuBar()

        screen_menu = wx.Menu()
        self._bind(screen_menu, _("Read the screen again\tF5"), self.rescan)
        self._bind(screen_menu, _("Read a different window..."), self.choose_target)
        self._bind(screen_menu, _("Read the whole screen instead\tCtrl+W"),
                   self.toggle_scope)
        screen_menu.AppendSeparator()
        self.live_item = screen_menu.AppendCheckItem(
            wx.ID_ANY, _("Watch this screen and tell me what changes\tCtrl+L"))
        self.Bind(wx.EVT_MENU, lambda e: self.toggle_live(), self.live_item)
        screen_menu.AppendSeparator()
        self.view_item = screen_menu.AppendCheckItem(
            wx.ID_ANY, _("Rebuild the controls instead of listing them\tCtrl+M"))
        self.Bind(wx.EVT_MENU, lambda e: self.toggle_view(), self.view_item)
        self._bind(screen_menu,
                   _("Put the controls on the real window itself\tCtrl+O"),
                   self.open_overlay)
        screen_menu.AppendSeparator()
        self._bind(screen_menu, _("Ask about this screen...\tCtrl+F"), self.ask)
        self._bind(screen_menu, _("Copy everything\tCtrl+Shift+C"), self.copy_all)
        screen_menu.AppendSeparator()
        self._bind(screen_menu, _("Close\tEscape"), self.Close)
        bar.Append(screen_menu, _("&Screen"))

        control_menu = wx.Menu()
        self._bind(control_menu, _("Press\tEnter"), self._activate_selected)
        self._bind(control_menu, _("Read this entry in full\tCtrl+R"),
                   self.speak_selected)
        self._bind(control_menu, _("Copy this entry\tCtrl+C"), self.copy_selected)
        bar.Append(control_menu, _("&Control"))

        keys_menu = wx.Menu()
        for key, label in PASS_THROUGH_KEYS:
            self._bind(keys_menu, label(), lambda k=key: self.send_key(k))
        bar.Append(keys_menu, _("Send &key"))

        self.SetMenuBar(bar)

    def _bind(self, menu: wx.Menu, label: str, handler) -> None:
        item = menu.Append(wx.ID_ANY, label)
        self.Bind(wx.EVT_MENU, lambda e: handler(), item)

    def _title_text(self) -> str:
        if self.target_title:
            return _("AI OCR: {window}").format(window=self.target_title)
        return _("AI OCR")

    # ------------------------------------------------------------------- rows
    def load_items(self, tab_id: str, background: bool = False) -> None:
        self.apply_items(self._rows_for(tab_id), tab_id, background=background)

    def _rows_for(self, tab_id: str) -> List[Any]:
        if self.screen is None:
            return [] if self._scanning else [_Note(
                _("Nothing has been read yet. Press F5 to read the screen."))]

        if tab_id == TAB_SUMMARY:
            rows: List[Any] = []
            if self.screen.summary:
                rows.append(_Note(self.screen.summary, 'summary'))
            rows.append(_Note(_("Kind of screen: {kind}").format(
                kind=self.screen.kind), 'summary'))
            rows.append(_Note(_("Read {n} seconds ago").format(
                n=max(0, int(time.time() - self.screen.taken_at))), 'summary'))
            for warning in self.screen.warnings:
                rows.append(_Note(warning, 'warning'))
            return rows

        if tab_id == TAB_ALL:
            return list(self.screen.elements)

        if tab_id.startswith('region:'):
            region = self.screen.region_named(tab_id[len('region:'):])
            return list(region.elements) if region is not None else []
        return []

    def row_key(self, item: Any) -> str:
        if isinstance(item, Element):
            return item.key
        return getattr(item, 'text', '')[:60]

    def format_row(self, item: Any) -> str:
        if isinstance(item, _Note):
            if item.kind == 'warning':
                return _("Note: {text}").format(text=item.text)
            return item.text
        if not isinstance(item, Element):
            return str(item)

        text = item.spoken()
        # The Everything tab flattens the regions away, so it has to say which
        # part of the screen each row came from or the list loses its shape.
        if self.current_tab == TAB_ALL and item.region:
            text = f"{item.region}: {text}"
        if item.hint:
            text = f"{text} - {item.hint}"
        if item.rect is None and item.role in ('button', 'menuitem', 'listitem'):
            text = _("{text} (position unknown, cannot be pressed)").format(text=text)
        return text

    def status_text(self) -> str:
        if self._scanning:
            return _("Reading the screen...")
        if self.screen is None:
            return _("Nothing read yet")
        title = self.screen.title or self.target_title or _("Screen")
        if self.view_mode == 'form':
            region = self._current_region()
            return _("{title}, {region}: {n} rebuilt controls").format(
                title=title, region=region.label if region else _("Screen"),
                n=len(region.elements) if region else 0)
        pressable = sum(1 for element in self.screen.elements if element.actionable)
        return _("{title}: {n} entries, {k} can be pressed").format(
            title=title, n=len(self.items), k=pressable)

    # ------------------------------------------------------------- activation
    def activate(self, item: Any) -> None:
        if isinstance(item, _Note):
            speak_titannet(item.text)
            return
        if not isinstance(item, Element):
            return
        if not item.actionable:
            # Reading it out is the useful thing to do with a row that cannot
            # be pressed, and it is what the user pressed Enter expecting.
            self.speak_selected()
            return
        try:
            result = actions_mod.activate(self.screen, item)
        except actions_mod.ActionRefused as exc:
            speak_notification(str(exc), 'warning')
            return
        except Exception as exc:
            speak_notification(_("Could not press it: {error}").format(error=exc),
                               'error')
            return
        speak_titannet(result)
        # Pressing something changes the screen, so read it again - but give
        # the app time to draw whatever the press produced.
        wx.CallLater(900, self.rescan, True)

    def context_menu_items(self, item: Any):
        if not isinstance(item, Element):
            return ()
        entries = [(_("Read this entry in full"), self.speak_selected),
                   (_("Copy this entry"), self.copy_selected)]
        if item.actionable:
            entries.insert(0, (_("Press"), self._activate_selected))
            entries.append((_("Right-click it"),
                            lambda: self._press(item, 'right')))
        return entries

    def extra_key(self, keycode: int, modifiers: int, item: Optional[Any]) -> bool:
        # These three are about the window itself, so they work wherever the
        # focus is - including inside a rebuilt text field.
        if modifiers == wx.MOD_CONTROL and keycode == ord('M'):
            self.toggle_view()
            return True
        if modifiers == wx.MOD_CONTROL and keycode == ord('L'):
            self.toggle_live()
            return True
        if modifiers == wx.MOD_CONTROL and keycode == ord('W'):
            self.toggle_scope()
            return True
        if modifiers == wx.MOD_CONTROL and keycode == ord('O'):
            self.open_overlay()
            return True

        # Ctrl+C and Ctrl+R belong to the text field the user is typing in.
        # Stealing Ctrl+C there - to copy a list row that is not even on screen
        # - would break copying in the one place a user most expects it.
        if self._editing_text():
            return False

        if modifiers == wx.MOD_CONTROL and keycode == ord('R'):
            self.speak_selected()
            return True
        if modifiers == wx.MOD_CONTROL and keycode == ord('C'):
            self.copy_selected()
            return True
        return False

    def _editing_text(self) -> bool:
        return isinstance(self.FindFocus(), (wx.TextCtrl, wx.ComboBox))

    def on_escape(self) -> bool:
        # Escape goes back one level before it closes, the same as everywhere
        # else in Titan: out of the rebuilt controls into the reading list, and
        # only then out of the window.
        if self.view_mode == 'form':
            self.set_view('list')
            return False
        return True

    def on_closed(self) -> None:
        self._stop_live()
        # The overlay is made of windows hooked onto somebody else's window; it
        # must never outlive the thing that opened it.
        overlay_mod.close_overlay()
        self._overlay = None

    # ------------------------------------------------------------- scanning
    def rescan(self, quiet: bool = False) -> None:
        """Read the screen again. ``quiet`` skips the "reading..." announcement."""
        if self._scanning:
            if not quiet:
                speak_titannet(_("Already reading the screen."))
            return

        reason = ai_provider.vision_unavailable_reason()
        if reason:
            speak_notification(reason, 'error')
            self.screen = None
            self.apply_items([_Note(reason, 'warning')], self.current_tab)
            return

        self._scanning = True
        self.SetStatusText(self.status_text())
        if not quiet:
            speak_titannet(_("Reading the screen..."))

        started = self.screen

        def _done(screen, error):
            wx.CallAfter(self._scan_finished, screen, error, started, quiet)

        if not self.reader.read(_done, scope=self.scope, hwnd=self.target_hwnd,
                                reuse_previous=bool(self._live_timer)):
            self._scanning = False

    def _scan_finished(self, screen: Optional[Screen], error: str,
                       previous: Optional[Screen], quiet: bool) -> None:
        if self._closing:
            return
        self._scanning = False
        if error:
            speak_notification(error, 'error')
            self.SetStatusText(self.status_text())
            if self.screen is None:
                self.apply_items([_Note(error, 'warning')], self.current_tab)
            return

        self.screen = screen
        self.target_title = (screen.capture.title if screen.capture else '') \
            or self.target_title
        self.SetTitle(self._title_text())
        self.rebuild_tabs()
        self._choose_view(screen)

        if self._start_overlay:
            # Opened straight into the overlay: the list is still filled in
            # behind it, so coming back from the overlay lands somewhere real.
            self._start_overlay = False
            self.refresh()
            wx.CallAfter(self.open_overlay)
            return

        unchanged = 'unchanged' in (screen.warnings or [])
        if self._live_timer is not None and previous is not None:
            self._announce_changes(screen, previous, unchanged)
            if self.view_mode == 'form':
                self._fill_regions()
            else:
                self.refresh(background=True)
            return

        if self.view_mode == 'form':
            self._fill_regions()
        else:
            self.refresh()
        if quiet:
            return
        summary = screen.summary or screen.title
        if summary:
            speak_titannet(summary)
        elif not screen.elements:
            speak_notification(
                _("Nothing readable was found on this screen."), 'warning')

    def _announce_changes(self, screen: Screen, previous: Screen,
                          unchanged: bool) -> None:
        """Live mode's whole job: say what moved, and nothing else."""
        if unchanged:
            return
        changes = screen.diff(previous)
        spoken: List[str] = []
        for element in changes['changed'][:6]:
            spoken.append(f"{element.name or element.text}: "
                          f"{element.value or element.state}")
        for element in changes['added'][:6]:
            spoken.append(_("new: {text}").format(text=element.spoken()))
        for element in changes['removed'][:4]:
            spoken.append(_("gone: {text}").format(
                text=element.name or element.text))
        if not spoken:
            return
        # Never more often than every couple of seconds, whatever the interval
        # is set to: speech that cannot be kept up with is worse than silence.
        now = time.time()
        if now - self._last_announced < 2.0:
            return
        self._last_announced = now
        speak_titannet('. '.join(spoken))

    # ------------------------------------------------------------------ modes
    def toggle_scope(self) -> None:
        self.scope = 'screen' if self.scope == 'window' else 'window'
        speak_titannet(_("Reading the whole screen") if self.scope == 'screen'
                       else _("Reading the window in front"))
        self.reader.forget()
        self.rescan()

    def toggle_live(self) -> None:
        if self._live_timer is not None:
            self._stop_live()
            speak_titannet(_("Stopped watching this screen."))
            return

        seconds = ai_provider.get_ocr_live_seconds() or 10
        self._live_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda e: self.rescan(quiet=True), self._live_timer)
        self._live_timer.Start(seconds * 1000)
        try:
            self.live_item.Check(True)
        except Exception:
            pass
        speak_titannet(_(
            "Watching this screen. I will tell you what changes, about every "
            "{n} seconds. A reading only costs a request when the picture "
            "actually changed.").format(n=seconds))

    def _stop_live(self) -> None:
        if self._live_timer is not None:
            self._live_timer.Stop()
            self._live_timer = None
        try:
            self.live_item.Check(False)
        except Exception:
            pass

    # ------------------------------------------------------------- form view
    def _choose_view(self, screen: Optional[Screen]) -> None:
        """Pick the view a freshly read screen opens in - once per window.

        A settings page or a dialog is far more useful rebuilt as controls; a
        menu or a wall of text is more useful as a list. After the user has
        chosen a view themselves, their choice stands and this stops guessing.
        """
        if self._view_chosen or screen is None:
            return
        self._view_chosen = True
        if has_real_controls(screen):
            self.set_view('form', announce=False)

    def toggle_view(self) -> None:
        self._view_chosen = True
        self.set_view('list' if self.view_mode == 'form' else 'form')

    def set_view(self, mode: str, announce: bool = True) -> None:
        if mode not in ('list', 'form'):
            return
        self.view_mode = mode
        form = (mode == 'form')

        self.listbox.Show(not form)
        self.region_label.Show(form)
        self.region_choice.Show(form)
        self.form.Show(form)
        self.view_button.SetLabel(_("Read as a list") if form
                                  else _("Rebuilt controls"))
        try:
            self.view_item.Check(form)
        except Exception:
            pass

        if form:
            self._fill_regions()
        self.panel.Layout()

        if announce:
            speak_titannet(_("Rebuilt controls") if form else _("Reading list"))
        if form:
            self.form.focus_first()
        else:
            self.listbox.SetFocus()
        self.SetStatusText(self.status_text())

    def _fill_regions(self) -> None:
        """Refill the region picker and rebuild the form for the current one."""
        names = [region.label for region in (self.screen.regions if self.screen
                                             else [])]
        previous = self.region_choice.GetStringSelection()
        self.region_choice.Set(names or [_("(nothing read yet)")])
        if names:
            index = names.index(previous) if previous in names else 0
            self.region_choice.SetSelection(index)
        else:
            self.region_choice.SetSelection(0)
        self._rebuild_form()

    def _region_picked(self) -> None:
        self._rebuild_form()
        self.form.focus_first()

    def _current_region(self) -> Optional[Region]:
        if self.screen is None or not self.screen.regions:
            return None
        index = self.region_choice.GetSelection()
        if index < 0 or index >= len(self.screen.regions):
            return None
        return self.screen.regions[index]

    def _rebuild_form(self) -> None:
        count = self.form.rebuild(self.screen, self._current_region())
        self.SetStatusText(self.status_text())
        return count

    def _on_form_action(self, kind: str, element: Element, value) -> None:
        """A control in the rebuilt form was used - do it for real."""
        try:
            if kind == 'press':
                result = actions_mod.activate(self.screen, element)
            elif kind == 'toggle':
                result = actions_mod.toggle(self.screen, element)
            elif kind == 'text':
                result = actions_mod.set_text(self.screen, element, value or '')
            elif kind == 'slider':
                result = actions_mod.set_slider(self.screen, element, value)
            elif kind == 'nudge':
                result = actions_mod.nudge(self.screen, element, int(value))
            else:
                return
        except actions_mod.ActionRefused as exc:
            speak_notification(str(exc), 'warning')
            # The form still shows what the user just did, which is now a lie -
            # put it back to what the program actually has.
            self._rebuild_form()
            return
        except Exception as exc:
            speak_notification(_("Could not do that: {error}").format(error=exc),
                               'error')
            self._rebuild_form()
            return

        speak_titannet(result)
        # Read again and rebuild from what the program really did, so a control
        # that refused or clamped the value shows the value it kept.
        wx.CallLater(900, self.rescan, True)

    # ---------------------------------------------------------------- overlay
    def open_overlay(self) -> bool:
        """Hook the controls onto the real window and get out of the way.

        This window hides rather than staying open behind the overlay, for two
        reasons: the user asked for *the program*, not for a second window
        about it - and a visible mimic would be in every picture the overlay
        takes of the screen from then on.
        """
        if self.screen is None or self.screen.capture is None:
            speak_notification(_("Nothing has been read yet. Press F5 first."),
                               'warning')
            return False
        if self._overlay is not None:
            speak_titannet(_("The overlay is already on."))
            return False

        self._stop_live()
        self.Hide()
        overlay = overlay_mod.show_overlay(
            self.screen, scope=self.scope, target_hwnd=self.target_hwnd,
            reader=self.reader, on_closed=self._overlay_closed,
            target_title=self.target_title)
        if overlay is None:
            self._overlay = None
            self.Show()
            self.Raise()
            self.listbox.SetFocus()
            return False
        self._overlay = overlay
        return True

    def _overlay_closed(self) -> None:
        """Back from the overlay: this window comes back where it left off."""
        self._overlay = None
        if self._closing:
            return
        self.Show()
        self.Raise()
        self.listbox.SetFocus()
        speak_titannet(_("Back to the reading list."))

    def retarget(self, hwnd: int, title: str) -> None:
        """Point an already-open mimic at a different window."""
        if not hwnd or hwnd == self.target_hwnd:
            return
        self.target_hwnd = int(hwnd)
        self.target_title = title or ''
        self.scope = 'window'
        self.reader.forget()
        self.screen = None
        self.SetTitle(self._title_text())

    def choose_target(self) -> None:
        """Pick a window to read, for when the mimic itself is in the way."""
        windows = _visible_windows(exclude_hwnd=self.GetHandle())
        if not windows:
            speak_notification(_("No other windows are open."), 'warning')
            return
        dialog = wx.SingleChoiceDialog(
            self, _("Which window should I read?"), _("Read a different window"),
            [title for _hwnd, title in windows])
        apply_skin_tree(dialog)
        if dialog.ShowModal() == wx.ID_OK:
            hwnd, title = windows[dialog.GetSelection()]
            self.target_hwnd = hwnd
            self.target_title = title
            self.scope = 'window'
            self.reader.forget()
            self.SetTitle(self._title_text())
            # Raised first: a minimised or fully covered window has nothing to
            # photograph, and UI Automation only reads the foreground one.
            _raise_window(hwnd)
            wx.CallLater(350, self.rescan)
        dialog.Destroy()

    def ask(self) -> None:
        """Ask a free-text question about the screen, answered from a fresh read."""
        reason = ai_provider.vision_unavailable_reason()
        if reason:
            speak_notification(reason, 'error')
            return
        dialog = wx.TextEntryDialog(
            self, _("What would you like to know about this screen?"),
            _("Ask about this screen"))
        apply_skin_tree(dialog)
        question = dialog.GetValue().strip() if dialog.ShowModal() == wx.ID_OK else ''
        dialog.Destroy()
        if not question:
            return
        if self._scanning:
            speak_titannet(_("Already reading the screen."))
            return

        self._scanning = True
        speak_titannet(_("Looking..."))

        def _done(screen, error):
            wx.CallAfter(self._answer_ready, screen, error, question)

        if not self.reader.read(_done, scope=self.scope, hwnd=self.target_hwnd,
                                reuse_previous=False, question=question):
            self._scanning = False

    def _answer_ready(self, screen: Optional[Screen], error: str,
                      question: str) -> None:
        if self._closing:
            return
        self._scanning = False
        if error:
            speak_notification(error, 'error')
            return
        self.screen = screen
        self.rebuild_tabs()
        self.refresh()
        answer = screen.summary or _("See the list for what I found.")
        speak_titannet(answer)
        show_message(self, _("You asked: {question}\n\n{answer}").format(
            question=question, answer=answer), _("Ask about this screen"))

    # ------------------------------------------------------------- utilities
    def _press(self, element: Element, button: str) -> None:
        try:
            speak_titannet(actions_mod.activate(self.screen, element, button))
        except actions_mod.ActionRefused as exc:
            speak_notification(str(exc), 'warning')

    def send_key(self, key: str) -> None:
        try:
            speak_titannet(actions_mod.send_key(self.screen, key))
        except actions_mod.ActionRefused as exc:
            speak_notification(str(exc), 'warning')
            return
        wx.CallLater(700, self.rescan, True)

    def speak_selected(self) -> None:
        item = self.selected_item()
        if isinstance(item, _Note):
            speak_titannet(item.text)
            return
        if not isinstance(item, Element):
            return
        parts = [item.spoken()]
        if item.text and item.text != item.name:
            parts.append(item.text)
        if item.hint:
            parts.append(item.hint)
        speak_titannet('. '.join(parts))

    def copy_selected(self) -> None:
        item = self.selected_item()
        text = (item.text or item.name) if isinstance(item, Element) else \
            getattr(item, 'text', '')
        self._copy(text)

    def copy_all(self) -> None:
        if self.screen is None:
            speak_notification(_("Nothing has been read yet."), 'warning')
            return
        self._copy('\n'.join(elements_as_lines(self.screen)))

    def _copy(self, text: str) -> None:
        if not text:
            return
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Close()
            speak_titannet(_("Copied"))


# --------------------------------------------------------------------------- #
# Window list helpers
# --------------------------------------------------------------------------- #
def _visible_windows(exclude_hwnd: int = 0) -> List[Tuple[int, str]]:
    out: List[Tuple[int, str]] = []
    try:
        import win32gui
    except Exception:
        return out

    def _collect(hwnd, _param):
        try:
            if not win32gui.IsWindowVisible(hwnd) or hwnd == exclude_hwnd:
                return True
            title = win32gui.GetWindowText(hwnd) or ''
            if not title.strip():
                return True
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            if right - left < 60 or bottom - top < 40:
                return True
            out.append((hwnd, title))
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(_collect, None)
    except Exception:
        pass
    return out


def _raise_window(hwnd: int) -> None:
    try:
        import win32con
        import win32gui
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
_frame: Optional[AIOcrFrame] = None


def show_ai_ocr(parent=None, scope: Optional[str] = None) -> Optional[AIOcrFrame]:
    """Open (or raise) the AI OCR mimic.

    Raising an existing window re-reads instead of just showing a stale
    photograph: the shortcut is pressed when the user wants to know what is on
    screen *now*.
    """
    global _frame

    if not ai_provider.is_ai_enabled():
        speak_notification(_("AI features are switched off in Settings, AI "
                             "features."), 'warning')
        return None
    if not ai_provider.get_ocr_enabled():
        speak_notification(_("AI OCR is switched off. Turn it on in Settings, "
                             "AI features."), 'warning')
        return None

    # Read the foreground window BEFORE anything of ours can take the focus -
    # including raising an already-open mimic.
    target_hwnd, target_title = capture_mod.foreground_window()

    if _frame is not None:
        try:
            if target_hwnd and target_hwnd != _frame.GetHandle():
                # Pressing the shortcut over a different program retargets the
                # open mimic at it, rather than re-reading the old one.
                _frame.retarget(target_hwnd, target_title)
            _frame.Raise()
            _frame.listbox.SetFocus()
            _frame.rescan()
            return _frame
        except Exception:
            _frame = None

    frame = AIOcrFrame(parent, scope=scope or ai_provider.get_ocr_scope(),
                       target_hwnd=target_hwnd, target_title=target_title)

    def _forget(event):
        global _frame
        _frame = None
        event.Skip()

    frame.Bind(wx.EVT_CLOSE, _forget)
    frame.Show()
    frame.listbox.SetFocus()
    _frame = frame
    return frame


def show_ai_ocr_overlay(parent=None, scope: Optional[str] = None) -> Optional[AIOcrFrame]:
    """Read the window the user is in and put the controls straight onto it.

    The overlay without the detour through the reading list: nothing of Titan's
    appears on screen at all, the program the user was already in simply gains
    an accessible surface. The mimic window is still built - it is what does the
    reading, and it is what Escape comes back to - but it stays hidden until
    then.
    """
    global _frame

    if not ai_provider.is_ai_enabled():
        speak_notification(_("AI features are switched off in Settings, AI "
                             "features."), 'warning')
        return None
    if not ai_provider.get_ocr_enabled():
        speak_notification(_("AI OCR is switched off. Turn it on in Settings, "
                             "AI features."), 'warning')
        return None

    target_hwnd, target_title = capture_mod.foreground_window()
    if _frame is not None:
        try:
            if target_hwnd and target_hwnd != _frame.GetHandle():
                _frame.retarget(target_hwnd, target_title)
            _frame._start_overlay = True
            _frame.rescan()
            return _frame
        except Exception:
            _frame = None

    frame = AIOcrFrame(parent, scope=scope or ai_provider.get_ocr_scope(),
                       target_hwnd=target_hwnd, target_title=target_title,
                       start_overlay=True)

    def _forget(event):
        global _frame
        _frame = None
        event.Skip()

    frame.Bind(wx.EVT_CLOSE, _forget)
    # Deliberately not shown: the first reading opens the overlay, and this
    # window only appears if the user comes back from it.
    _frame = frame
    return frame


def get_ai_ocr_frame() -> Optional[AIOcrFrame]:
    return _frame
