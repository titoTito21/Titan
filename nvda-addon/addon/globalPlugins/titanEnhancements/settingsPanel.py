# -*- coding: utf-8 -*-
"""The add-on's page in NVDA's own settings.

Built with ``guiHelper``, so every control gets its label the way NVDA's own
panels do and a screen reader announces it without anything being written
here. The panel is registered by the global plugin and removed again when
the add-on is terminated - a panel left behind by a removed add-on is a
category in NVDA's settings that raises when it is opened.
"""

from . import configSpec
from . import i18n

_ = i18n.install(globals())


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

            def check(label, key, default=True):
                box = helper.addItem(wx.CheckBox(self, label=label))
                box.SetValue(bool(values.get(key, default)))
                return box

            # Translators: a setting in the Titan enhancements panel.
            self.announcementsBox = check(
                _('Let Titan make its own announcements through NVDA'),
                'announcements')
            # Translators: a setting in the Titan enhancements panel.
            self.replaceFocusBox = check(
                _('Let a Titan announcement replace NVDA\'s own report of '
                  'that control'), 'replaceFocus')
            # Translators: a setting in the Titan enhancements panel.
            self.positionBox = check(
                _('Place the voice where Titan says the control is'),
                'position')
            # Translators: a setting in the Titan enhancements panel.
            self.markerBox = check(
                _('When the voice cannot be placed, mark the position with a '
                  'tone'), 'positionMarker')
            # Translators: a setting in the Titan enhancements panel.
            self.prosodyBox = check(
                _('Apply the pitch, rate and volume Titan asks for'),
                'prosody')
            # Translators: a setting in the Titan enhancements panel.
            self.brailleBox = check(
                _('Show Titan\'s announcements in braille'), 'braille')
            # Translators: a setting in the Titan enhancements panel.
            self.standDownBox = check(
                _('Stay silent while Titan Access is the reader'),
                'standDownForTitanAccess')
            # Translators: a setting in the Titan enhancements panel.
            self.announceConnectionBox = check(
                _('Say when Titan connects and disconnects'),
                'announceConnection')

            # The other direction: Titan reaching INTO NVDA. A real group,
            # because a static box is a grouping Windows itself knows about,
            # so a reader says which part of the panel the keyboard entered
            # rather than this being four more check boxes to count through.
            back = helper.addItem(guiHelper.BoxSizerHelper(
                self, sizer=wx.StaticBoxSizer(
                    # Translators: a group of settings in the Titan panel.
                    wx.StaticBox(self, label=_('What Titan may do to NVDA')),
                    wx.VERTICAL)))

            def check_back(label, key, default=True):
                box = back.addItem(wx.CheckBox(back.sizer.GetStaticBox(),
                                               label=label))
                box.SetValue(bool(values.get(key, default)))
                return box

            # Translators: a setting in the Titan enhancements panel.
            self.driveBox = check_back(
                _('Let Titan change NVDA - its voice, its review cursor, its '
                  'rate and its settings'), 'letTitanDrive')
            # Translators: a setting in the Titan enhancements panel.
            self.pressKeysBox = check_back(
                _('Let Titan run NVDA\'s own commands. A command is whatever '
                  'you bound that key to, so this is off until you turn it '
                  'on'), 'letTitanPressKeys', default=False)
            # Translators: text on the Titan enhancements panel.
            back.addItem(wx.StaticText(
                back.sizer.GetStaticBox(),
                label=_('What NVDA can see is always answered: it is your own '
                        'screen, described to your own desktop, and it is '
                        'what lets Titan\'s AI OCR read the window you are '
                        'really in.')))

            helper.addItem(wx.StaticText(self, label=self._state()))

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
            configSpec.write({
                'announcements': self.announcementsBox.GetValue(),
                'replaceFocus': self.replaceFocusBox.GetValue(),
                'position': self.positionBox.GetValue(),
                'positionMarker': self.markerBox.GetValue(),
                'prosody': self.prosodyBox.GetValue(),
                'braille': self.brailleBox.GetValue(),
                'standDownForTitanAccess': self.standDownBox.GetValue(),
                'announceConnection': self.announceConnectionBox.GetValue(),
                'letTitanDrive': self.driveBox.GetValue(),
                'letTitanPressKeys': self.pressKeysBox.GetValue(),
            })
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
