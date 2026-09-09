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
        (_('How a control is read'), '', (
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
            ('menuLeaving', _('Say when the keyboard leaves a menu'), ''),
        )),
        # Translators: a group of settings in the Titan panel.
        (_('What changes while you are looking elsewhere'), '', (
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
        )),
        # Translators: a group of settings in the Titan panel.
        (_('Sounds, and where the voice comes from'), '', (
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
        )),
        # Translators: a group of settings in the Titan panel.
        (_('What Titan may say through NVDA'), '', (
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
        )),
        # Translators: a group of settings in the Titan panel.
        (_('What Titan may do to NVDA'),
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
        (_('A window that shows a screen reader nothing'),
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
        )),
        # Translators: a group of settings in the Titan panel.
        (_('The touchpad'),
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
            helper = guiHelper.BoxSizerHelper(self, sizer=sizer)
            values = configSpec.read()
            starts = configSpec.defaults()
            self._boxes = {}
            self._choices = {}
            self._depends = {}

            for label, note, rows in _page():
                group = helper.addItem(guiHelper.BoxSizerHelper(
                    self, sizer=wx.StaticBoxSizer(
                        wx.StaticBox(self, label=label), wx.VERTICAL)))
                parent = group.sizer.GetStaticBox()
                for key, text, depends in rows:
                    words = configSpec.choices(key)
                    if words:
                        self._add_choice(group, parent, key, text, words,
                                         values, starts)
                    else:
                        box = group.addItem(wx.CheckBox(parent, label=text))
                        box.SetValue(bool(values.get(key,
                                                     starts.get(key, True))))
                        self._boxes[key] = box
                    if depends:
                        self._depends.setdefault(depends, []).append(key)
                if note:
                    group.addItem(wx.StaticText(parent, label=note))

            for key in self._depends:
                box = self._boxes.get(key)
                if box is not None:
                    box.Bind(wx.EVT_CHECKBOX, self._follow)
            self._follow(None)

            # Translators: a button on the Titan enhancements panel.
            classes = helper.addItem(wx.Button(self,
                                               label=_('Voice classes...')))
            classes.Bind(wx.EVT_BUTTON, self._classes)
            # Translators: a button on the Titan enhancements panel.
            modules = helper.addItem(wx.Button(self,
                                               label=_('Reader modules...')))
            modules.Bind(wx.EVT_BUTTON, self._modules)

            helper.addItem(wx.StaticText(self, label=self._state()))

        def _add_choice(self, group, parent, key, text, words, values, starts):
            """A setting with more than two answers, as a real list.

            The words the user reads are this add-on's; the words that are
            STORED are the spec's, and the two are kept apart on purpose -
            translating a setting's value is how a Polish NVDA comes to have
            a configuration file no other NVDA can read.
            """
            labels = [WORDS.get(word, lambda w=word: w)() for word in words]
            control = group.addLabeledControl(text, wx.Choice, choices=labels)
            wanted = str(values.get(key, starts.get(key, '')) or '')
            try:
                control.SetSelection(words.index(wanted))
            except ValueError:
                control.SetSelection(0)
            self._choices[key] = (control, words)

        # ------------------------------------------------------- dependencies
        def _follow(self, _event):
            """A setting that only means something under a switch is disabled
            until that switch is on - and stays where it was, so turning the
            parent back on gives the user their answer back rather than a
            default."""
            for parent, children in self._depends.items():
                on = bool(self._boxes[parent].GetValue()) \
                    if parent in self._boxes else True
                for child in children:
                    control = self._boxes.get(child)
                    if control is None:
                        pair = self._choices.get(child)
                        control = pair[0] if pair else None
                    if control is not None:
                        control.Enable(on)

        # ------------------------------------------------------------ buttons
        def _classes(self, _event):
            from . import classManager
            classManager.show(self)

        def _modules(self, _event):
            from . import commands
            commands.reader_modules()

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
            # Whatever is on the page. Restating the keys here is how a
            # switch comes to tick and never save.
            answers = {key: box.GetValue()
                       for key, box in self._boxes.items()}
            for key, (control, words) in self._choices.items():
                index = control.GetSelection()
                if 0 <= index < len(words):
                    answers[key] = words[index]
            configSpec.write(answers)
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
