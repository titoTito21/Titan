# -*- coding: utf-8 -*-
"""The add-on's page in NVDA's own settings.

Built with ``guiHelper``, so every control gets its label the way NVDA's own
panels do and a screen reader announces it without anything being written
here. The panel is registered by the global plugin and removed again when the
add-on is terminated - a panel left behind by a removed add-on is a category
in NVDA's settings that raises when it is opened.

Three things about the shape of it, each of which was a mess before:

* **The page is a TABLE, not a procedure.** Every switch used to be written
  out three times - once in the config spec, once as a `check(...)` call with
  its default repeated, and once by hand in `onSave` - so adding one meant
  remembering three places, and forgetting the third gave a switch that ticks,
  reads back its old value, and does nothing. `PAGE` is the only place a
  switch is named now; the defaults come from `configSpec` (the one source of
  truth for what a switch starts as) and `onSave` writes whatever is on the
  page.

* **The switches are GROUPED, in real static boxes.** There are two dozen of
  them, and a flat column of two dozen check boxes is a page nobody finds
  anything on: a static box is a grouping Windows itself knows about, so a
  reader says which part of the page the keyboard has entered rather than the
  user counting. Titan's own settings window learned this and it is the same
  answer here.

* **A switch that only means something under another one SAYS so**, by being
  disabled until that one is on. "Including the status bar" is not an
  independent answer to an independent question - it is part of the live
  regions answer - and a page that lets it be ticked while live regions are
  off is a page that has taken an answer it will not act on.
"""

from . import configSpec
from . import i18n

_ = i18n.install(globals())


#: What a stored word is CALLED on the page. The value written into NVDA's
#: configuration is the spec's own word and never this - a setting whose
#: value is translated is a configuration file that means something
#: different on a Polish machine. Each is a callable so the catalogue is
#: asked at the moment the page is built rather than at import time.
WORDS = {
    # Translators: how a control's place is conveyed - as a pitch.
    'pitch': lambda: _('a higher or lower voice (high at the top of the '
                       'screen)'),
    # Translators: how a control's place is conveyed - by panning.
    'pan': lambda: _('the voice moved left or right'),
    # Translators: how a control's place is conveyed - both ways at once.
    'both': lambda: _('both'),
    # Translators: which recogniser reads a window - Windows' own.
    'local': lambda: _('Windows\' own recogniser (free, nothing is sent)'),
    # Translators: which recogniser reads a window - Titan's AI OCR.
    'ai': lambda: _('Titan\'s AI (understands it, sends a picture to your '
                    'provider)'),
}


#: The whole page: groups of settings, in the order somebody would ask the
#: questions. A row is ``(key, label, depends-on)``; an empty third field
#: means it stands on its own. Nothing here carries a default - that is
#: ``configSpec``'s answer and there must not be a second one - and nothing
#: here says what KIND of control a row is either: a setting whose spec is
#: an option is a list of the words it allows, and every other one is a
#: check box. One declaration, read two ways.
def _page():
    """Built rather than declared, so the labels go through gettext once the
    catalogue is installed rather than at import time."""
    return (
        # Translators: a group of settings in the Titan panel.
        (_('Announcing controls'),
         # Translators: what the 'Announcing controls' category is for.
         _('How a control is read out: its name, what it is, its state, '
           'and what a picture or a dialog is called.'), (
            # Translators: a setting in the Titan enhancements panel.
            ('pitchedFocus',
             _('Read Titan\'s controls the way Titan Access does: the name, '
               'then the control type a little lower, then the state a little '
               'higher'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('pitchedEverywhere',
             _('Read every control that way, in every program - not only in '
               'Titan'), 'pitchedFocus'),
            # Translators: a setting in the Titan enhancements panel.
            ('appSemantics',
             _('Read Titan\'s own applications as what they are: a row of the '
               'file manager as a file or a folder with its date and type, a '
               'note as a note'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('windowsSemantics',
             _('Read every other program that way too: a row of a list with '
               'the columns beside its name, and a part of the window NVDA '
               'enters in silence'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('readerModules',
             _('Use the reader modules: what each program\'s own lists, panes '
               'and rows mean'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('graphicKinds',
             _('Say what a picture is - an icon, a picture, an animation - '
               'instead of "graphic"'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('dialogKinds',
             _('Say what kind of dialog it is - a question, a warning, an '
               'error - anywhere in Windows'), ''),
            # Translators: a setting in the Titan enhancements panel.
            # Translators: a setting in the Titan enhancements panel.
            ('windowKinds',
             _('Say what kind of window you have arrived in - an '
               'application, a game, a small window, the desktop - and '
               'what its icon is'), ''),
            ('menuLeaving', _('Say when the keyboard leaves a menu'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('soundScheme',
             _('Answer a control\'s state with a sound where you have '
               'chosen one, instead of the word (set them under Sound '
               'scheme)'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('speechOrigins',
             _('Give keyboard echo, a spelled word, a message and what '
               'another program says through the controller a voice of '
               'their own (set them under Voices and reading order)'), ''),
        )),
        # Translators: a group of settings in the Titan panel.
        (_('Changes elsewhere'),
         # Translators: what the 'Changes elsewhere' category is for.
         _('What is said about something that changed while you were '
           'looking somewhere else.'), (
            # Translators: a setting in the Titan enhancements panel.
            ('liveRegions',
             _('Announce live regions - anything a reader module or Titan '
               'declares live'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('liveStatusBars',
             _('Including the status bar of the window you are in'),
             'liveRegions'),
            # Translators: a setting in the Titan enhancements panel.
            ('busyState',
             _('Say when the program is busy (the hourglass)'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('attentionState',
             _('Say when a window asks for your attention'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('monitors',
             _('Watch the areas you have marked, and say when one changes'),
             ''),
            # Translators: a setting in the Titan enhancements panel.
            ('journal',
             _('Keep what the reader has said, so you can look back at it '
               'and go to what said it'), ''),
        )),
        # Translators: a group of settings in the Titan panel.
        (_('Sound'),
         # Translators: what the 'Sound' category is for.
         _('Sounds, and where in the stereo image the voice comes from.'), (
            # Translators: a setting in the Titan enhancements panel.
            ('position',
             _('Place the voice where the control is, in Titan'), ''),
            # Translators: a setting in the Titan enhancements panel: how a
            # control's place is conveyed.
            ('positionAs', _('Carry that place as:'), 'position'),
            # Translators: a setting in the Titan enhancements panel.
            ('positionEverywhere',
             _('Place it that way everywhere else too, in every program'),
             'position'),
            # Translators: a setting in the Titan enhancements panel.
            ('positionMarker',
             _('When the voice cannot be placed, mark the position with a '
               'tone'), 'position'),
            # Translators: a setting in the Titan enhancements panel.
            ('earcons',
             _('Play Titan\'s own cursor sounds on every control, outside '
               'Titan\'s own windows (they already play their own)'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('auditoryIcons',
             _('Play a short sound for what just happened - on a button, '
               'something opened, that was refused'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('auditoryIconsEverywhere',
             _('Play them on every control in every program, not only in '
               'Titan\'s own windows'), 'auditoryIcons'),
        )),
        # Translators: a group of settings in the Titan panel.
        (_('Titan\'s announcements'),
         # Translators: what the 'Titan's announcements' category is for.
         _('What Titan may say through NVDA, and how much of it may '
           'replace NVDA\'s own words.'), (
            # Translators: a setting in the Titan enhancements panel.
            ('announcements',
             _('Let Titan make its own announcements through NVDA'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('replaceFocus',
             _('Let one of them replace NVDA\'s own report of that control'),
             'announcements'),
            # Translators: a setting in the Titan enhancements panel.
            ('prosody',
             _('Apply the pitch, rate and volume Titan asks for'),
             'announcements'),
            # Translators: a setting in the Titan enhancements panel.
            ('braille', _('Show Titan\'s announcements in braille'),
             'announcements'),
            # Translators: a setting in the Titan enhancements panel.
            ('standDownForTitanAccess',
             _('Stay silent while Titan Access is the reader'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('announceConnection',
             _('Say when Titan connects and disconnects'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('reportContext',
             _('Tell Titan which program you are in, so its own features '
               'can be about that program'), ''),
        )),
        # Translators: a group of settings in the Titan panel. Its own
        # msgid rather than the layer entry's "Titan itself": the layer
        # opens the whole of Titan, and this group is only about the
        # settings inside it, so one word cannot serve both.
        (_("Titan's own settings"),
         # Translators: what the "Titan's own settings" category is for.
         _('The list of Titan you walk with the arrow keys - what it can '
           'start, its settings, its macros. Enter on a setting changes '
           'it; Save is at the end of the categories.'), (
            # Translators: a setting in the Titan enhancements panel.
            ('titanValues', _('Say what a setting is set to'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('titanCounts', _('Say how many are in a list'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('titanAutoSave', _('Save Titan\'s settings straight away'), ''),
        )),
        # Translators: a group of settings in the Titan panel.
        (_('Virtual machines'),
         # Translators: what the 'Virtual machines' category is for.
         _('A guest is another computer\'s screen, so there is nothing in '
           'it for a reader to read. This follows the pointer instead: '
           'what is written on its row, and what the pointer\'s own shape '
           'says the control is. No key to press, and nothing is '
           'installed in the guest.'), (
            # Translators: a setting in the Titan enhancements panel.
            ('guestCursor', _('Read what the pointer is on'), ''),
            # Translators: a setting in the Titan enhancements panel. The
            # agent channel: something INSIDE the guest, or inside a game,
            # reporting what it sees - which is the only way to get real
            # text rather than a picture.
            ('agentLink',
             _('Also listen for an agent inside a guest or a game telling '
               'the reader what it sees. Nothing is needed in the guest for '
               'the pointer above; this is for real text, where you can put '
               'something there'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('agentFromGuest',
             _('Let such an agent reach the reader over the network. Without '
               'this it is heard only from this computer, or through VMware '
               'itself, which needs no network at all'), 'agentLink'),
        )),
        # Translators: a group of settings in the Titan panel.
        (_('Permissions'),
         # Translators: text on the Titan enhancements panel.
         _('What NVDA can see is always answered: it is your own screen, '
           'described to your own desktop, and it is what lets Titan read the '
           'window you are really in.'), (
            # Translators: a setting in the Titan enhancements panel.
            ('letTitanDrive',
             _('Let Titan change NVDA - its voice, its review cursor, its '
               'rate and its settings'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('letTitanPressKeys',
             _('Let Titan run NVDA\'s own commands. A command is whatever you '
               'bound that key to, so this is off until you turn it on'),
             'letTitanDrive'),
        )),
        # Translators: a group of settings in the Titan panel.
        (_('Unreadable windows'),
         # Translators: text on the Titan enhancements panel.
         _('These need Titan running with its AI features on, and both send a '
           'picture of part of your screen to your AI provider - which is why '
           'they start off. A window is only ever read after you have been '
           'asked about that program.'), (
            # Translators: a setting in the Titan enhancements panel.
            ('surfaceReading',
             _('Read a window that exposes nothing - a game\'s menu, an '
               'installer that draws its own widgets - and give it real '
               'controls you can Tab through, or follow what is highlighted '
               'if it is a game'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('autoLabel',
             _('Work out a name for an unnamed control by reading it once, '
               'and remember it'), ''),
            # Translators: a setting in the Titan enhancements panel. The
            # display-model tier: what the program passed to a GDI text call,
            # read from NVDA's own hooks instead of from a picture.
            ('drawnText',
             _('Read what the program drew, before taking any picture of '
               'it (exact, instant, and nothing leaves the machine)'), ''),
            # Translators: a setting in the Titan enhancements panel: which
            # recogniser reads a window that shows a screen reader nothing.
            ('ocrTier', _('Read such a window with:'), ''),
            # Translators: a setting in the Titan enhancements panel.
            ('localOcrLanguage',
             _('The language Windows\' own recogniser reads in:'),
             ''),
        )),
        # Translators: a group of settings in the Titan panel.
        (_('Terminal'),
         # Translators: text on the Titan enhancements panel.
         _('Numpad minus turns the review on and off. While it is on the '
           'plain arrow keys walk the buffer - lines with up and down, '
           'characters with left and right, a screenful with page up and '
           'page down - and each line is marked by a short beep pitched by '
           'where it is on the screen. Escape leaves.'), ()),
        # Translators: a group of settings in the Titan panel.
        (_('Touchpad'),
         # Translators: text on the Titan enhancements panel.
         _('NVDA and the wheel to the right turns it on, to the left turns it '
           'off - which a touchpad can do with two fingers.'), (
            # Translators: a setting in the Titan enhancements panel.
            ('trackpad',
             _('Use the laptop\'s touchpad as a touch screen, so NVDA\'s own '
               'touch gestures work on it'), ''),
        )),
    )


def keys_on_the_page():
    """Every setting the page offers. Read by the tests, which is the point:
    a switch in the config spec that no page shows is a switch nobody can
    reach, and one on the page that the spec has not got is one that cannot
    be saved."""
    return [key for _label, _note, rows in _page() for key, _l, _d in rows]


def build():
    """The panel class, or None when NVDA's settings GUI is not here."""
    try:
        import wx
        from gui import guiHelper
        from gui.settingsDialogs import SettingsPanel
    except Exception:                                # noqa: BLE001
        return None

    class TitanEnhancementsPanel(SettingsPanel):
        # Translators: the title of the add-on's category in NVDA settings.
        title = _('Titan enhancements')

        def makeSettings(self, sizer):
            """A CATEGORY at a time, because the page has outgrown a column.

            **A settings page nobody can find anything on is a page of
            settings nobody uses.** There are more than thirty switches now,
            across eight subjects that have nothing to do with each other,
            and a single column of them is a page somebody arrows through
            for a minute to find the one they came for. NVDA's own settings
            dialog answers this with a category list, and so does Titan's;
            this is the same shape one level down.

            Two lists, and both of them native. The categories are a
            `wx.ListBox`; the switches of the chosen one are a real
            check-list, where every row is a check box Windows itself
            reports - so a reader says the name AND whether it is ticked,
            which an owner-drawn `wx.CheckListBox` cannot (see
            `classManager`). Anything that is not a switch - a choice with
            three answers - is a real control under the list.
            """
            import wx
            helper = guiHelper.BoxSizerHelper(self, sizer=sizer)
            self._values = configSpec.read()
            self._starts = configSpec.defaults()
            self._groups = _page()
            self._boxes = {}
            self._choices = {}
            self._depends = {}

            side = wx.BoxSizer(wx.HORIZONTAL)
            left = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
            # Translators: the list of setting categories in the Titan panel.
            self.categories = left.addLabeledControl(
                _('&Categories'), wx.ListBox,
                choices=[label for label, _note, _rows in self._groups],
                style=wx.LB_SINGLE)
            self.categories.Bind(wx.EVT_LISTBOX, self._category_chosen)
            side.Add(left.sizer, 0, wx.EXPAND | wx.RIGHT, 10)

            self.page = wx.Panel(self)
            self.pageSizer = wx.BoxSizer(wx.VERTICAL)
            self.page.SetSizer(self.pageSizer)
            side.Add(self.page, 1, wx.EXPAND)
            helper.addItem(side, flag=wx.EXPAND, proportion=1)

            buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
            # Translators: a button on the Titan enhancements panel.
            classes = buttons.addButton(
                self, label=_('Voices and reading order...'))
            classes.Bind(wx.EVT_BUTTON, self._classes)
            # Translators: a button on the Titan enhancements panel.
            modules = buttons.addButton(self, label=_('Reader modules...'))
            modules.Bind(wx.EVT_BUTTON, self._modules)
            # Translators: a button on the Titan enhancements panel: shows
            # the key an agent inside a guest has to carry.
            key = buttons.addButton(self, label=_('The agent\'s key...'))
            key.Bind(wx.EVT_BUTTON, self._agent_key)
            helper.addItem(buttons)
            helper.addItem(wx.StaticText(self, label=self._state()))

            if self._groups:
                self.categories.SetSelection(0)
            self._show_category(0)

        # ------------------------------------------------------ the pages
        def _category_chosen(self, _event):
            self._show_category(self.categories.GetSelection())

        def _show_category(self, index):
            """Build the chosen category's controls, keeping every answer.

            The switches of a category that is not showing still hold what
            the user set: `_boxes` and `_choices` are keyed on the setting
            and never cleared, so `onSave` writes the whole page whichever
            category happens to be up when Save is pressed. A page that
            saved only what was on the screen would silently discard
            everything the user changed and then moved away from.
            """
            import wx
            if index < 0 or index >= len(self._groups):
                return
            self.pageSizer.Clear(delete_windows=True)
            self._live = {}
            label, note, rows = self._groups[index]
            switches = [row for row in rows if not _options_for(row[0])[0]]
            others = [row for row in rows if _options_for(row[0])[0]]

            # **What the category is FOR is said before its switches, and in
            # something a reader can land on.** It used to be a
            # `wx.StaticText` added after everything else: a static text
            # cannot take the keyboard and a screen reader cannot reach one,
            # so the sentence explaining that two of these switches send a
            # picture of your screen to a provider was, to the people this
            # add-on is for, not on the page at all. A read-only text
            # control is focusable and carries the reader's own cursor -
            # the same answer `Static` got in the Elten port.
            if note:
                explain = wx.TextCtrl(
                    self.page, value=note,
                    style=wx.TE_READONLY | wx.TE_MULTILINE | wx.NO_BORDER)
                explain.SetMinSize((-1, 44))
                a11y_name(explain, label)
                self.pageSizer.Add(explain, 0, wx.EXPAND | wx.BOTTOM, 6)

            if switches:
                # Translators: the list of switches for the chosen category.
                self.pageSizer.Add(wx.StaticText(
                    self.page, label=_('{category}: switches').format(
                        category=label)), 0, wx.BOTTOM, 3)
                listed = _check_list_class()(
                    self.page, choices=[text for _key, text, _d in switches])
                for at, (key, _text, depends) in enumerate(switches):
                    listed.Check(at, bool(self._values.get(
                        key, self._starts.get(key, True))))
                    self._live[key] = (listed, at)
                    if depends:
                        self._depends.setdefault(depends, []).append(key)
                listed.Bind(wx.EVT_CHECKLISTBOX, self._ticked)
                self.pageSizer.Add(listed, 1, wx.EXPAND | wx.BOTTOM, 6)
                a11y_name(listed, label)

            for key, text, depends in others:
                words, labels = _options_for(key)
                self.pageSizer.Add(wx.StaticText(self.page, label=text), 0)
                control = wx.Choice(self.page, choices=labels)
                wanted = str(self._values.get(key,
                                              self._starts.get(key, '')) or '')
                try:
                    control.SetSelection(words.index(wanted))
                except ValueError:
                    control.SetSelection(0)
                self.pageSizer.Add(control, 0, wx.BOTTOM, 6)
                self._choices[key] = (control, words)
                if depends:
                    self._depends.setdefault(depends, []).append(key)

            self.page.Layout()
            self.Layout()
            self._follow(None)

        def _ticked(self, event):
            """What the user just did, kept where the page can find it.

            The check-list is thrown away when the category changes, so its
            answers have to be taken out of it as they are made rather than
            read off it at Save - which would read a control that is gone.
            """
            try:
                index = event.GetSelection()
            except Exception:                        # noqa: BLE001
                index = -1
            for key, (listed, at) in self._live.items():
                if index in (-1, at):
                    self._values[key] = bool(listed.IsChecked(at))
            self._follow(None)
            event.Skip()

        def _follow(self, _event):
            """A setting that only means something under a switch is disabled
            until that switch is on - and keeps its answer, so turning the
            parent back on gives the user what they said rather than a
            default.

            Only what is on the screen: a category that is not showing has
            no controls to enable, and its answers are in `_values` where
            Save will find them.
            """
            for parent, children in self._depends.items():
                on = bool(self._values.get(
                    parent, self._starts.get(parent, True)))
                for child in children:
                    pair = self._choices.get(child)
                    if pair is not None:
                        try:
                            pair[0].Enable(on)
                        except Exception:            # noqa: BLE001
                            pass

        # ------------------------------------------------------------ buttons
        def _classes(self, _event):
            from . import classManager
            classManager.show(self)

        def _modules(self, _event):
            from . import commands
            commands.reader_modules()

        def _agent_key(self, _event):
            """Show the key, so it can be copied into an agent.

            A read-only text control rather than a message box: the whole
            point is to select it and copy it, and a reader has its own
            cursor in a text control and none in a dialog's static text.
            """
            import wx
            from . import agentLink
            # Translators: the title of the dialog showing the agent's key.
            dialog = wx.Dialog(self, title=_('The agent\'s key'))
            inside = wx.BoxSizer(wx.VERTICAL)
            # Translators: text in the dialog showing the agent's key.
            words = _('An agent must carry this key in every line it sends, '
                      'or the reader drops it without answering. Copy it '
                      'into the agent; it never leaves this computer '
                      'otherwise. The agent talks to port {port}.').format(
                          port=agentLink.PORT)
            note = wx.TextCtrl(dialog, value=words, style=(
                wx.TE_READONLY | wx.TE_MULTILINE | wx.NO_BORDER))
            note.SetMinSize((420, 70))
            # Translators: the name of the explanation in the key dialog.
            a11y_name(note, _('What the key is for'))
            inside.Add(note, 0, wx.EXPAND | wx.ALL, 6)
            # Translators: the label of the field holding the agent's key.
            inside.Add(wx.StaticText(dialog, label=_('&Key')), 0, wx.LEFT, 6)
            field = wx.TextCtrl(dialog, value=agentLink.token(),
                                style=wx.TE_READONLY)
            field.SetMinSize((420, -1))
            # Translators: the name of the field holding the agent's key.
            a11y_name(field, _('The agent\'s key'))
            inside.Add(field, 0, wx.EXPAND | wx.ALL, 6)
            buttons = dialog.CreateButtonSizer(wx.CLOSE)
            if buttons is not None:
                inside.Add(buttons, 0, wx.EXPAND | wx.ALL, 6)
            dialog.SetSizerAndFit(inside)
            field.SetFocus()
            field.SelectAll()
            dialog.ShowModal()
            dialog.Destroy()

        def _state(self):
            """What this NVDA can actually do, said plainly on the panel.

            A switch for something the machine cannot do is a switch that
            lies. The user is told here, once, rather than finding out by
            turning positioned speech on and hearing nothing move.
            """
            from . import panner
            report = panner.PANNER.report()
            if report['stream_panning']:
                return _('This NVDA can place the voice of the current '
                         'synthesizer ({name}).').format(
                             name=report['synth'] or _('unknown'))
            return _('This NVDA cannot place the voice of the current '
                     'synthesizer: {reason}').format(
                         reason=report['problem'] or _('the reason is unknown'))

        def onSave(self):
            """The whole page, not the category that happens to be up.

            Every switch's answer lives in `_values` from the moment it is
            ticked, so a user who changes something in one category and
            moves to another loses nothing - which a page that read its
            controls at Save would do silently.
            """
            answers = dict(self._values)
            for key, (control, words) in self._choices.items():
                try:
                    index = control.GetSelection()
                except Exception:                    # noqa: BLE001
                    continue
                if 0 <= index < len(words):
                    answers[key] = words[index]
            configSpec.write({key: answers[key] for key in configSpec.SPEC
                              if key in answers})
            configSpec.apply()

    return TitanEnhancementsPanel

def register():
    """Put the panel into NVDA's settings. Returns the class, or None."""
    panel = build()
    if panel is None:
        return None
    try:
        from gui.settingsDialogs import NVDASettingsDialog
        if panel not in NVDASettingsDialog.categoryClasses:
            NVDASettingsDialog.categoryClasses.append(panel)
        return panel
    except Exception:                                # noqa: BLE001
        return None


def unregister(panel):
    if panel is None:
        return
    try:
        from gui.settingsDialogs import NVDASettingsDialog
        if panel in NVDASettingsDialog.categoryClasses:
            NVDASettingsDialog.categoryClasses.remove(panel)
    except Exception:                                # noqa: BLE001
        pass


def _check_list_class():
    """NVDA's accessible checkable list, or wx's if this NVDA has none.

    A `wx.CheckListBox` on Windows is an owner-drawn list box - wxWidgets
    paints the little square itself, so there is no check box for the
    platform to report and a reader says the name without saying whether it
    is ticked. Titan learned this building its own settings; NVDA learned it
    before either of us.
    """
    import wx
    try:
        from gui import nvdaControls
        found = getattr(nvdaControls, 'CustomCheckListBox', None)
        if found is not None:
            return found
    except Exception:                                # noqa: BLE001
        pass
    return wx.CheckListBox


def a11y_name(control, name):
    """Name a native control for MSAA as well as for wx.

    `SetName` alone is wx's own name and never reaches a screen reader for a
    native list: it answers with its own IAccessible, whose name comes from
    window text these controls have none of.
    """
    try:
        control.SetName(str(name))
    except Exception:                                # noqa: BLE001
        pass


#: A setting whose answers are not in the spec because they are a fact about
#: THIS machine. The spec can say what a setting may be only when the answer
#: is the same everywhere; which languages Windows can read in is not.
def _options_for(key):
    """``(values, labels)`` for a setting with more than two answers.

    ``([], [])`` for an ordinary switch, which is what tells the page to
    render it as one.
    """
    words = configSpec.choices(key)
    if words:
        return words, [WORDS.get(word, lambda w=word: w)() for word in words]
    if key == 'localOcrLanguage':
        # Translators: the first entry of the OCR language list - whatever
        # Windows is set to.
        values, labels = [''], [_('(whatever Windows is set to)')]
        try:
            from contentRecog import uwpOcr
            for language in uwpOcr.getLanguages() or []:
                values.append(str(language))
                labels.append(str(language))
        except Exception:                            # noqa: BLE001
            pass
        return values, labels
    return [], []
