# -*- coding: utf-8 -*-
"""A window onto what each kind of thing sounds like, and in what order.

:mod:`classes` is the model - which semantic class has which voice, and
whose answer that is. This is the one place a user can see the whole list,
hear one, change it and put it back.

**It is accessible because it is native.** A notebook with two pages, a
grouped list, real drop-downs, real spin controls and real buttons - every
one of them a control Windows itself knows about, so a reader announces it
without a word being written here. That is the rule the Titan shell arrived
at and the rule this add-on applies to everything it puts on the screen.

**It is ORDERLY, which is not the same as small.** A voice is now seven
things - a synthesizer, a voice, a variant, a pitch, a rate, a volume and an
inflection - and seven controls in a column is a form nobody can hold in
their head. So they are two groups with a heading each ("Which voice",
"How it sounds"), the classes themselves are grouped by what they are FOR,
and the thing that is not a voice at all - the order the parts of a control
are read in - is a page of its own rather than a fourth group nobody
expects.

**A change is HEARD before it is kept.** Whether a two-point pitch change is
audible depends on the synthesizer, the rate and the listener - which is
exactly the kind of question that cannot be answered by reading a number.
So Try speaks the sample in the voice as it stands on the page, on the
synthesizer that voice actually names.

**What a synthesizer has is asked of it, at the moment it is chosen.** The
voices belong to the synthesizer and the variants belong to the voice, so
choosing one refills the next - a list of the voices of a synthesizer the
user is not using is a list that looks right and is wrong.
"""

from . import classes
from . import personalities
from . import i18n
from . import speaking

_ = i18n.install(globals())

#: The one entry that means "leave it alone". Every name in a profile is
#: optional and empty is the default, so the list has to be able to say so -
#: and it has to be first, because that is the answer for every class the
#: user has not touched.
def _inherit():
    # Translators: the first entry of every voice list in the class manager.
    return _('(the one NVDA is using)')


def build():
    """The dialog class, or None when there is no wx."""
    try:
        import wx
        from gui import guiHelper
    except Exception:                                # noqa: BLE001
        return None

    class ClassManager(wx.Dialog):

        def __init__(self, parent):
            # Translators: the title of the voice class manager.
            super().__init__(parent, title=_('Voices and reading order'),
                             style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
            self._rows = classes.described()
            main = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
            self.book = main.addItem(wx.Notebook(self))
            self._voice_page()
            self._order_page()
            main.addDialogDismissButtons(self.CreateButtonSizer(wx.CLOSE))
            self.Bind(wx.EVT_BUTTON, self._close, id=wx.ID_CLOSE)
            self.EscapeId = wx.ID_CLOSE
            self.Sizer = main.sizer
            main.sizer.Fit(self)
            self.CentreOnScreen()

        # ------------------------------------------------------- the voices
        def _voice_page(self):
            page = wx.Panel(self.book)
            # Translators: a page of the class manager.
            self.book.AddPage(page, _('Voices'))
            helper = guiHelper.BoxSizerHelper(page, orientation=wx.VERTICAL)

            # Translators: the label of the list of voice classes.
            self.list = helper.addLabeledControl(
                _('What is being said'), wx.ListBox,
                choices=self._labels(), style=wx.LB_SINGLE)
            self.list.Bind(wx.EVT_LISTBOX, self._chosen)
            # **The sentence the row used to be.** A row has to be the
            # thing itself, and the explanation of what a class is FOR is
            # still worth having - "detail" means nothing, "the columns
            # beside a row's name" is something to have an opinion about.
            # It is read-only text rather than a label because a reader
            # cannot land on a `wx.StaticText`.
            self.meaning = helper.addItem(wx.TextCtrl(
                page, style=wx.TE_READONLY | wx.TE_MULTILINE,
                size=(-1, 46)))
            # Translators: the label of the text that explains a voice
            # class.
            self.meaning.SetName(_('What this is'))
            if self._rows:
                self.list.SetSelection(0)

            which = helper.addItem(guiHelper.BoxSizerHelper(
                page, sizer=wx.StaticBoxSizer(
                    # Translators: a group in the voice class manager.
                    wx.StaticBox(page, label=_('Which voice')),
                    wx.VERTICAL)))
            box = which.sizer.GetStaticBox()
            # Translators: a control in the voice class manager.
            self.synth = which.addLabeledControl(_('&Synthesizer'), wx.Choice,
                                                 choices=[_inherit()])
            self.synth.Bind(wx.EVT_CHOICE, self._synth_chosen)
            # Translators: a control in the voice class manager.
            self.voice = which.addLabeledControl(_('&Voice'), wx.Choice,
                                                 choices=[_inherit()])
            self.voice.Bind(wx.EVT_CHOICE, self._voice_chosen)
            # Translators: a control in the voice class manager.
            self.variant = which.addLabeledControl(_('V&ariant'), wx.Choice,
                                                   choices=[_inherit()])
            # Translators: text in the voice class manager, under the
            # synthesizer list.
            self.note = which.addItem(wx.StaticText(box, label=''))

            dials = helper.addItem(guiHelper.BoxSizerHelper(
                page, sizer=wx.StaticBoxSizer(
                    # Translators: a group in the voice class manager.
                    wx.StaticBox(page, label=_('How it sounds')),
                    wx.VERTICAL)))

            def spin(label):
                return dials.addLabeledControl(
                    label, wx.SpinCtrl, min=-classes.LIMIT,
                    max=classes.LIMIT, initial=0)

            # Translators: a dial in the voice class manager.
            self.pitch = spin(_('&Pitch'))
            # Translators: a dial in the voice class manager.
            self.rate = spin(_('&Rate'))
            # Translators: a dial in the voice class manager.
            self.volume = spin(_('V&olume'))
            # Translators: a dial in the voice class manager.
            self.inflection = spin(_('&Inflection'))

            # **A name instead of four numbers.** Emacspeak's oldest and
            # most humane idea after the icons: a mode says "this is
            # bolder", not "this is pitch 4". Choosing one fills the dials
            # in, and they can then be edited - so this is a starting
            # point somebody can have an opinion about rather than a
            # second, competing way to set the same thing.
            self.overlay = dials.addLabeledControl(
                # Translators: a control in the voice class manager.
                _('&Named voice'), wx.Choice,
                choices=[personalities.label_of(name)
                         for name in personalities.NAMES] + [_('(edited)')])
            self.overlay.Bind(wx.EVT_CHOICE, self._overlay_chosen)

            buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
            # Translators: a button in the voice class manager.
            try_it = buttons.addButton(page, label=_('&Try it'))
            try_it.Bind(wx.EVT_BUTTON, self._try)
            # Translators: a button in the voice class manager.
            keep = buttons.addButton(page, label=_('&Keep'))
            keep.Bind(wx.EVT_BUTTON, self._keep)
            # Translators: a button in the voice class manager.
            back = buttons.addButton(page, label=_('Put this one &back'))
            back.Bind(wx.EVT_BUTTON, self._back)
            # Translators: a button in the voice class manager.
            all_back = buttons.addButton(page, label=_('Put them a&ll back'))
            all_back.Bind(wx.EVT_BUTTON, self._all_back)
            helper.addItem(buttons)

            page.Sizer = helper.sizer
            self._fill_synths()
            self._show()

        # -------------------------------------------------------- the order
        def _order_page(self):
            page = wx.Panel(self.book)
            # Translators: a page of the class manager.
            self.book.AddPage(page, _('Reading order'))
            helper = guiHelper.BoxSizerHelper(page, orientation=wx.VERTICAL)
            # Translators: text at the top of the reading order page.
            helper.addItem(wx.StaticText(page, label=_(
                'The parts of a control, in the order they are read. Move '
                'them with the buttons, and untick anything that should not '
                'be said at all. "Checked, check box" and "check box, '
                'checked" are the same three facts in two orders - this is '
                'where you say which.')))
            # **NVDA's own checkable list**, not wx's. A `wx.CheckListBox`
            # on Windows is an owner-drawn list box - wxWidgets paints the
            # little square itself, so there is no check box there for the
            # platform to report and a reader says the name without saying
            # whether it is ticked. Titan learned this building its own
            # settings; NVDA learned it before either of us, and
            # `CustomCheckListBox` is its answer. The plain one is the
            # fallback for an NVDA that has not got it, where the words are
            # still right even if the state is not announced.
            self.parts = helper.addLabeledControl(
                # Translators: the label of the reading order list.
                _('&Parts of a control'), _check_list_class())
            self._fill_order()

            buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
            # Translators: a button on the reading order page.
            up = buttons.addButton(page, label=_('Move &up'))
            up.Bind(wx.EVT_BUTTON, lambda e: self._move(-1))
            # Translators: a button on the reading order page.
            down = buttons.addButton(page, label=_('Move &down'))
            down.Bind(wx.EVT_BUTTON, lambda e: self._move(1))
            # Translators: a button on the reading order page.
            keep = buttons.addButton(page, label=_('&Keep this order'))
            keep.Bind(wx.EVT_BUTTON, self._keep_order)
            # Translators: a button on the reading order page.
            back = buttons.addButton(page, label=_('Put the order &back'))
            back.Bind(wx.EVT_BUTTON, self._back_order)
            helper.addItem(buttons)
            page.Sizer = helper.sizer

        def _fill_order(self, at=0):
            words = classes.part_names()
            self._order = classes.order()
            self.parts.Set([words.get(name, name)
                            for name, _on in self._order])
            for index, (_name, on) in enumerate(self._order):
                self.parts.Check(index, on)
            if self._order:
                self.parts.SetSelection(max(0, min(at, len(self._order) - 1)))

        def _read_order(self):
            return [(name, bool(self.parts.IsChecked(index)))
                    for index, (name, _on) in enumerate(self._order)]

        def _move(self, step):
            rows = self._read_order()
            at = self.parts.GetSelection()
            to = at + step
            if at < 0 or to < 0 or to >= len(rows):
                return
            rows[at], rows[to] = rows[to], rows[at]
            classes.set_order(rows)
            self._fill_order(at=to)
            self.parts.SetFocus()

        def _keep_order(self, _event):
            classes.set_order(self._read_order())
            self._fill_order(at=max(0, self.parts.GetSelection()))
            # Translators: said when the reading order is saved.
            self._said(_('The reading order is kept.'))

        def _back_order(self, _event):
            classes.reset_order()
            self._fill_order()
            # Translators: said when the reading order is put back.
            self._said(_('The reading order is back to the default.'))

        # ------------------------------------------------------------ lists
        def _labels(self):
            """Every class, with its group written in front of it.

            A flat list of nearly thirty is a list nobody finds anything
            in, and a wx.ListBox has no groups - so the group is part of
            the row. It reads as "Messages: system notification".

            **The row is the SHORT name**, not the sentence explaining it.
            A list is read one row at a time with the arrows, so a row has
            to be the thing itself - "control name", "keyboard echo",
            "watched area" - and a sentence in every row is a sentence
            heard on every arrow key by somebody who wanted the one below.
            The explanation is still there, under the list, where it can be
            read by whoever wants it.
            """
            groups = classes.group_names()
            out = []
            for row in self._rows:
                said = row.get('label') or row['id']
                if row['changed']:
                    # Translators: marks a voice class the user has changed.
                    said = _('{what} (changed)').format(what=said)
                out.append('{}: {}'.format(groups.get(row['group'], ''), said))
            return out

        def _fill_synths(self):
            found = speaking.synthesizers()
            self._synths = [''] + [name for name, _label in found]
            self.synth.Set([_inherit()] + [label for _n, label in found])

        def _fill_voices(self, wanted='', variant=''):
            found = speaking.voices_of(self._chosen_synth())
            self._voices = [''] + [key for key, _label in found]
            self.voice.Set([_inherit()] + [label for _k, label in found])
            self._select(self.voice, self._voices, wanted)
            self._fill_variants(variant)

        def _fill_variants(self, wanted=''):
            found = speaking.variants_of(self._chosen_synth(),
                                         self._chosen_voice())
            self._variants = [''] + [key for key, _label in found]
            self.variant.Set([_inherit()] + [label for _k, label in found])
            self._select(self.variant, self._variants, wanted)
            self.variant.Enable(len(self._variants) > 1)

        @staticmethod
        def _select(control, keys, wanted):
            try:
                control.SetSelection(keys.index(str(wanted or '')))
            except ValueError:
                control.SetSelection(0)

        def _chosen_synth(self):
            index = self.synth.GetSelection()
            return self._synths[index] if 0 <= index < len(self._synths) else ''

        def _chosen_voice(self):
            index = self.voice.GetSelection()
            return self._voices[index] if 0 <= index < len(self._voices) else ''

        def _chosen_variant(self):
            index = self.variant.GetSelection()
            return self._variants[index] \
                if 0 <= index < len(self._variants) else ''

        # ------------------------------------------------------------ state
        def _current(self):
            index = self.list.GetSelection()
            if index < 0 or index >= len(self._rows):
                return None
            return self._rows[index]

        def _show(self):
            row = self._current()
            voice = (row or {}).get('voice') or {}
            self.pitch.SetValue(int(voice.get('pitch') or 0))
            self.rate.SetValue(int(voice.get('rate') or 0))
            self.volume.SetValue(int(voice.get('volume') or 0))
            self.inflection.SetValue(int(voice.get('inflection') or 0))
            # **A class that is PART of an utterance may not name a
            # synthesizer**, and the honest way to say so is to take the
            # control away rather than to accept the answer and ignore it.
            whole = bool((row or {}).get('whole'))
            self.synth.Enable(whole)
            self._select(self.synth, self._synths,
                         voice.get('synth') if whole else '')
            self._fill_voices(voice.get('voice') or '',
                              voice.get('variant') or '')
            self.note.SetLabel(self._note_for(row, whole))
            self.meaning.SetValue(str((row or {}).get('meaning') or ''))
            self._show_overlay(voice)

        def _show_overlay(self, voice):
            wearing = personalities.matching(voice)
            if wearing:
                self.overlay.SetSelection(
                    personalities.NAMES.index(wearing))
            else:
                # Not one of them, and saying so is the honest answer: a
                # name shown for dials that no longer match it would be a
                # manager that lies about what is in force.
                self.overlay.SetSelection(len(personalities.NAMES))

        def _overlay_chosen(self, _event):
            at = self.overlay.GetSelection()
            if not 0 <= at < len(personalities.NAMES):
                return
            row = self._current()
            if row is None:
                return
            made = personalities.put_on(self._dials_now(),
                                        personalities.NAMES[at])
            self.pitch.SetValue(int(made.get('pitch') or 0))
            self.rate.SetValue(int(made.get('rate') or 0))
            self.volume.SetValue(int(made.get('volume') or 0))
            self.inflection.SetValue(int(made.get('inflection') or 0))
            self._try(None)

        def _dials_now(self):
            return {'pitch': self.pitch.GetValue(),
                    'rate': self.rate.GetValue(),
                    'volume': self.volume.GetValue(),
                    'inflection': self.inflection.GetValue()}

        def _note_for(self, row, whole):
            if row is None:
                return ''
            refused = speaking.refused().get(self._chosen_synth())
            if refused:
                # Translators: shown when a synthesizer will not start.
                return _('That synthesizer would not start: {why}').format(
                    why=refused)
            if row['id'] == 'text':
                # Translators: shown for the class that reads text.
                return _('Reading text is NVDA\'s own: choosing a '
                         'synthesizer here puts it in NVDA\'s say all '
                         'configuration profile, so NVDA switches to it '
                         'while it reads and back again afterwards.')
            if whole:
                # Translators: shown for a class that is a whole message.
                return _('This is a whole message, so it may have a '
                         'synthesizer of its own.')
            # Translators: shown for a class that is part of a control's
            # reading.
            return _('This is part of a control\'s reading, so it shares the '
                     'reader\'s synthesizer. A voice or a variant of that '
                     'synthesizer can still be chosen.')

        def _profile(self):
            wanted = {'pitch': self.pitch.GetValue(),
                      'rate': self.rate.GetValue(),
                      'volume': self.volume.GetValue(),
                      'inflection': self.inflection.GetValue(),
                      'voice': self._chosen_voice(),
                      'variant': self._chosen_variant()}
            if self.synth.IsEnabled():
                wanted['synth'] = self._chosen_synth()
            return {key: value for key, value in wanted.items() if value}

        def _refresh(self, keep_at=None):
            self._rows = classes.described()
            at = self.list.GetSelection() if keep_at is None else keep_at
            self.list.Set(self._labels())
            if 0 <= at < len(self._rows):
                self.list.SetSelection(at)
            self._show()

        def _said(self, text):
            from . import dialogs
            dialogs.report(text)

        # ---------------------------------------------------------- actions
        def _chosen(self, _event):
            self._show()

        def _synth_chosen(self, _event):
            self._fill_voices()
            self.note.SetLabel(self._note_for(self._current(),
                                              self.synth.IsEnabled()))

        def _voice_chosen(self, _event):
            self._fill_variants()

        def _try(self, _event):
            """Speak the sample as the page stands, not as it is stored.

            The whole point of the button: the user is deciding whether a
            change is audible, and a preview of what is already saved would
            answer a different question.
            """
            row = self._current()
            if row is None:
                return
            classes.speak_sample(row['id'], self._profile())

        def _keep(self, _event):
            row = self._current()
            if row is None:
                return
            profile = self._profile()
            classes.set_voice(row['id'], profile)
            said = _('Kept.')
            if row['id'] == 'text':
                # **Reading text is the one class this add-on cannot speak
                # itself.** Say all feeds itself: each utterance carries the
                # callbacks that queue the next line, so taking the words
                # away to another synthesizer stops the reading after one
                # line. NVDA already switches synthesizer for say all, through
                # a configuration profile, at the right utterance boundary -
                # so the answer is to put the chosen synthesizer in that
                # profile and let NVDA do what it already does.
                from . import sayall_profile
                ok, note = sayall_profile.set_synth(
                    profile.get('synth', ''), profile.get('voice', ''),
                    profile.get('variant', ''))
                said = note if note else said
                if not ok:
                    self._said(said)
                    self._refresh()
                    return
            self._refresh()
            # Translators: said when a voice class is saved.
            self._said(said)

        def _back(self, _event):
            row = self._current()
            if row is None:
                return
            classes.reset(row['id'])
            if row['id'] == 'text':
                self._forget_reading_voice()
            self._refresh()

        def _all_back(self, _event):
            classes.reset(None)
            self._forget_reading_voice()
            self._refresh(keep_at=0)

        @staticmethod
        def _forget_reading_voice():
            """Take the say-all arrangement away with the class.

            Putting a class back has to put back everything it did, or the
            table would say the reader's own voice while NVDA went on
            reading text with something else - which is the worst kind of
            wrong: a setting that shows one thing and does another.
            """
            try:
                from . import sayall_profile
                sayall_profile.clear()
            except Exception:                        # noqa: BLE001
                pass

        def _close(self, _event):
            self.Destroy()

    return ClassManager


def show(parent=None):
    """Put the manager up. Answers whether it could."""
    manager = build()
    if manager is None:
        return False
    try:
        import gui
        import wx
        if parent is None:
            parent = gui.mainFrame

        def open_it():
            dialog = manager(parent)
            dialog.Show()
        wx.CallAfter(open_it)
        return True
    except Exception:                                # noqa: BLE001
        return False


def _check_list_class():
    """NVDA's accessible checkable list, or wx's if this NVDA has none."""
    import wx
    try:
        from gui import nvdaControls
        found = getattr(nvdaControls, 'CustomCheckListBox', None)
        if found is not None:
            return found
    except Exception:                                # noqa: BLE001
        pass
    return wx.CheckListBox
