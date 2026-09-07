# -*- coding: utf-8 -*-
"""Titan enhancements - NVDA and the Titan desktop, as one thing.

Titan is an accessible desktop whose interface is built to be HEARD: a
control on the left of the window sounds on the left, a row of a board is
lower and quieter the further away it is, an announcement carries a role, a
state and a place in a list. Its own reader, Titan Access, gets all of that.
NVDA got a string, because the NVDA controller protocol - which is how
``accessible_output3`` reaches a reader - carries text and nothing else.

Worse, it got LESS than a string: Titan's ``announce_view_switched`` and
``announce_shell_group`` deliberately stayed silent whenever the reader was
not Titan Access, because NVDA reads the control itself and Titan's sentence
would have been a second, worse copy of it.

This add-on is the other end of a channel that carries the structure. Titan
calls into NVDA over its own Action Bus with the position, the pitch, the
role and the braille; the position is applied to whatever synthesizer the
user has chosen, by setting the per-channel volume of the stream underneath
it; and the announcement replaces NVDA's own report of that control instead
of racing it.

Nothing here requires Titan to be running, or to be installed. With no
Titan, the bus connection retries quietly in the background and every
gesture says that Titan is not running.
"""

import threading
import time

import globalPluginHandler

from . import channel                                # noqa: F401
from . import commands
from . import compat
from . import configSpec
from . import dialogs
from . import earcons
from . import focus
from . import gestures
from . import i18n
from . import interject
from . import link
from . import menu as titan_menu
from . import panner
from . import settingsPanel

_ = i18n.install(globals())

try:
    from scriptHandler import script
except Exception:                                    # noqa: BLE001
    def script(**_kwargs):                           # pragma: no cover
        def decorate(function):
            return function
        return decorate

#: Shown in NVDA's Input Gestures dialog.
CATEGORY = 'Titan'

#: How often the connection is looked at. This is not a poll of Titan - the
#: bus client keeps its own connection - only of a flag, so it can be lazy.
WATCH_SECONDS = 3.0


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = CATEGORY

    def __init__(self):
        super().__init__()
        self._panel = None
        self._watching = threading.Event()
        self._watcher = None
        self._connected = False
        configSpec.register()
        try:
            configSpec.apply()
        except Exception as error:                   # noqa: BLE001
            if compat.log is not None:
                compat.log.error(f'Titan enhancements: settings: {error}')
        self._panel = settingsPanel.register()
        # Every Titan action the user could bind a key to LAST time, put back
        # before Titan is anywhere near running. NVDA starts first on most
        # machines, and a gesture the user bound that is missing until the
        # desktop comes up is indistinguishable from one bound to nothing.
        try:
            gestures.install(self)
        except Exception as error:                   # noqa: BLE001
            if compat.log is not None:
                compat.log.error(f'Titan enhancements: gestures: {error}')
        if configSpec.read().get('enabled', True):
            # The speech filter goes in before the bus does: Titan may arm a
            # dialog kind on its very first call, and a filter registered
            # after that would miss it.
            interject.start()
            # Whether the voice can be placed by the audio session is a COM
            # walk; it is worked out now, on a thread, so the first
            # capability question Titan asks does not wait for it.
            try:
                panner.PANNER.probe_session()
            except Exception:                        # noqa: BLE001
                pass
            link.start()
            self._start_watching()

    # ----------------------------------------------------------- lifecycle
    def terminate(self):
        """Leave NVDA exactly as it was found.

        The restore is the important half: a stream left panned is an NVDA
        that speaks out of one ear for the rest of the session, and that
        would outlive the add-on that did it.
        """
        self._watching.set()
        try:
            earcons.stop()
        except Exception:                            # noqa: BLE001
            pass
        try:
            interject.stop()
        except Exception:                            # noqa: BLE001
            pass
        try:
            panner.PANNER.restore()
        except Exception:                            # noqa: BLE001
            pass
        try:
            link.stop()
        except Exception:                            # noqa: BLE001
            pass
        settingsPanel.unregister(self._panel)
        self._panel = None
        try:
            super().terminate()
        except Exception:                            # noqa: BLE001
            pass

    def _start_watching(self):
        if not configSpec.read().get('announceConnection', True):
            return
        self._watching.clear()
        self._watcher = threading.Thread(target=self._watch,
                                         name='TitanEnhancementsWatch',
                                         daemon=True)
        self._watcher.start()

    def _watch(self):
        """Say when Titan arrives and when it goes.

        Nothing else on the machine would tell the user that the desktop
        they are sitting in has come back, and the difference matters: with
        Titan there, its own announcements are richer than NVDA's; without
        it, NVDA is on its own and the user should know which of the two
        they are hearing.
        """
        while not self._watching.wait(WATCH_SECONDS):
            try:
                now = link.LINK.connected()
            except Exception:                        # noqa: BLE001
                now = False
            if now == self._connected:
                continue
            self._connected = now
            if now:
                # Who Titan is, asked at once. Everything that behaves
                # differently inside Titan's own windows needs this, and
                # waiting to be told meant waiting for Titan to speak.
                try:
                    link.LINK.introduce()
                except Exception:                    # noqa: BLE001
                    pass
                # Titan is there: ask it what it can do, so a Titan with
                # something installed since last time is bindable without
                # either program being restarted. On its own worker; the
                # user is told nothing unless they asked.
                gestures.refresh(self)
            if not configSpec.read().get('announceConnection', True):
                continue
            dialogs.report(_('Titan connected.') if now
                           else _('Titan disconnected.'))
            if not now:
                panner.PANNER.restore()
                focus.set_titan_pid(0)

    # ------------------------------------------------------------- events
    def event_gainFocus(self, obj, nextHandler):
        """Let a Titan announcement stand in for NVDA's own report.

        Only ever for one event, only inside the process Titan told us is
        its own, and only when Titan asked. Everything else - the review
        cursor, braille, the object cache - still happens: the report is
        made with speech muted rather than skipped.
        """
        if not configSpec.read().get('replaceFocus', True):
            nextHandler()
            return
        try:
            focus.handle_gain_focus(obj, nextHandler)
        except Exception:                            # noqa: BLE001
            nextHandler()

    # ------------------------------------------------------------ scripts
    @script(
        # Translators: an NVDA command.
        description=_('Reports whether Titan is connected and what it can '
                      'send to this NVDA'),
        category=CATEGORY, gesture='kb:NVDA+alt+t')
    def script_titanStatus(self, gesture):
        commands.status()

    @script(
        # Translators: an NVDA command.
        description=_('Opens the Titan menu: everything Titan can do'),
        category=CATEGORY, gesture='kb:NVDA+shift+t')
    def script_titanMenu(self, gesture):
        titan_menu.show(self)

    @script(
        # Translators: an NVDA command.
        description=_('Runs one of the macros in Titan'),
        category=CATEGORY, gesture='kb:NVDA+alt+m')
    def script_titanMacros(self, gesture):
        commands.macros()

    @script(
        # Translators: an NVDA command.
        description=_('Runs anything Titan or one of its add-ons can do'),
        category=CATEGORY, gesture='kb:NVDA+alt+a')
    def script_titanActions(self, gesture):
        commands.actions()

    @script(
        # Translators: an NVDA command.
        description=_('Reads the current window with Titan\'s AI OCR'),
        category=CATEGORY, gesture='kb:NVDA+alt+o')
    def script_titanOcrRead(self, gesture):
        commands.ocr_read()

    @script(
        # Translators: an NVDA command.
        description=_('Asks Titan\'s AI a question about the current window'),
        category=CATEGORY, gesture='kb:NVDA+alt+q')
    def script_titanOcrAsk(self, gesture):
        commands.ocr_ask()

    @script(
        # Translators: an NVDA command.
        description=_('Puts Titan\'s AI OCR overlay over the current window'),
        category=CATEGORY, gesture='kb:NVDA+alt+shift+o')
    def script_titanOcrOverlay(self, gesture):
        commands.ocr_overlay()

    @script(
        # Translators: an NVDA command.
        description=_('Asks Titan\'s AI assistant a question'),
        category=CATEGORY, gesture='kb:NVDA+alt+i')
    def script_titanAssistant(self, gesture):
        commands.assistant(act=False)

    @script(
        # Translators: an NVDA command.
        description=_('Tells Titan\'s AI to do something, and lets it act'),
        category=CATEGORY, gesture='kb:NVDA+alt+shift+i')
    def script_titanAssistantAct(self, gesture):
        commands.assistant(act=True)

    @script(
        # Translators: an NVDA command.
        description=_('Reads the conversation with Titan\'s AI assistant'),
        category=CATEGORY)
    def script_titanAssistantHistory(self, gesture):
        commands.assistant_history()

    @script(
        # Translators: an NVDA command.
        description=_('Forgets the conversation with Titan\'s AI assistant'),
        category=CATEGORY)
    def script_titanAssistantForget(self, gesture):
        commands.assistant_forget()

    @script(
        # Translators: an NVDA command.
        description=_('Asks Titan what it can do, so every one of its '
                      'actions can be given a key in Input Gestures'),
        category=CATEGORY)
    def script_titanRefreshActions(self, gesture):
        commands.refresh_actions(self)

    @script(
        # Translators: an NVDA command.
        description=_('Turns positioned speech for Titan on and off'),
        category=CATEGORY, gesture='kb:NVDA+alt+p')
    def script_titanTogglePosition(self, gesture):
        commands.toggle_position()

    @script(
        # Translators: an NVDA command.
        description=_('Turns Titan\'s own announcements on and off'),
        category=CATEGORY, gesture='kb:NVDA+alt+n')
    def script_titanToggleAnnouncements(self, gesture):
        commands.toggle_announcements()
