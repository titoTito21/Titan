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
from . import dialog_kind
from . import dialogs
from . import earcons
from . import focus
from . import gestures
from . import i18n
from . import interject
from . import link
from . import live
from . import menu as titan_menu
from . import monitors
from . import appReview
from . import ocrReview
from . import reporting
from . import virtualWindow
from . import journal
from . import origin
from . import panner
from . import procedures
from . import settingsPanel
from . import smart
from . import speaking
from . import states
from . import surface
from . import terminal
from . import tce
from . import trackpad

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
        self._smart_bound = False
        self._terminal_bound = False
        self._ocr_bound = False
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
            # **Where an utterance came from is only knowable while NVDA is
            # still in the function that knows.** By the time the filter
            # above sees it, keyboard echo and a message from another
            # program are both a list of strings. This wraps NVDA's own
            # named entry points to leave a mark, and it is put back in
            # `terminate` exactly as it was found.
            try:
                origin.start()
            except Exception as error:               # noqa: BLE001
                if compat.log is not None:
                    compat.log.error(
                        'Titan enhancements: speech origins: %s' % error)
            try:
                # Only when there is something to watch: a thread polling
                # nothing is a thread reading the screen for no reason, and
                # this one can reach Windows' own recogniser.
                monitors._keep_running()
            except Exception:                        # noqa: BLE001
                pass
            # Whether the voice can be placed by the audio session is a COM
            # walk; it is worked out now, on a thread, so the first
            # capability question Titan asks does not wait for it.
            try:
                panner.PANNER.probe_session()
            except Exception:                        # noqa: BLE001
                pass
            link.start()
            # The two things a sighted person gets without looking at
            # anything: the hourglass, and a window whose taskbar button is
            # flashing. Both are cheap and both stand down with a reason
            # rather than raising anywhere near the reader.
            try:
                states.start()
            except Exception:                        # noqa: BLE001
                pass
            if configSpec.read().get('trackpad', False):
                # **Never silently.** This used to be `except: pass`, so a
                # pad that would not start was indistinguishable from a
                # user who had not switched it on - and the answer to "no
                # gestures" was nowhere at all.
                try:
                    ok, why = trackpad.start()
                    if not ok and compat.log is not None:
                        compat.log.error(
                            'Titan trackpad did not start: %s' % why)
                except Exception as error:           # noqa: BLE001
                    if compat.log is not None:
                        compat.log.error(
                            'Titan trackpad raised on start: %s' % error)
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
            # NVDA's own speech functions back, exactly as they were. A
            # wrapper left behind by an add-on that has gone is a reader
            # calling into a module nobody owns.
            origin.stop()
        except Exception:                            # noqa: BLE001
            pass
        try:
            speaking.restore_standing()
        except Exception:                            # noqa: BLE001
            pass
        try:
            if self._smart_bound:
                self._borrow_keys(False)
        except Exception:                            # noqa: BLE001
            pass
        for leave in (states.stop, trackpad.stop, surface.stop_now,
                      terminal.stop, monitors.stop, ocrReview.stop,
                      appReview.stop, virtualWindow.stop):
            try:
                leave()
            except Exception:                        # noqa: BLE001
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
            else:
                # **Letting go is not something Titan can always tell us.**
                # `detach` is Titan saying goodbye, and a Titan that was
                # killed, crashed or lost the pipe says nothing at all - so
                # the pid, the pan and the "attached" the status command
                # reports all stayed as they were, and the add-on went on
                # treating a dead process's windows as Titan's.
                try:
                    link.LINK.detach()
                except Exception:                    # noqa: BLE001
                    panner.PANNER.restore()
                    focus.set_titan_pid(0)
            if not configSpec.read().get('announceConnection', True):
                continue
            dialogs.report(_('Titan connected.') if now
                           else _('Titan disconnected.'))

    # ------------------------------------------------------------- events
    def event_gainFocus(self, obj, nextHandler):
        """Let a Titan announcement stand in for NVDA's own report.

        Only ever for one event, only inside the process Titan told us is
        its own, and only when Titan asked. Everything else - the review
        cursor, braille, the object cache - still happens: the report is
        made with speech muted rather than skipped.
        """
        self._keep_keys_right()
        # **The application review is NOT ended by a focus change.** The two
        # reviews above are about a window - a terminal, a recognised
        # screen - and outliving it would swallow the user's arrow keys
        # somewhere else. A described application has no window on this
        # machine at all: it is a process of Titan's being rendered here,
        # so moving the focus is how somebody walks away from it and comes
        # back. What the binding must follow is whether the review is on.
        self._keep_app_keys_right()
        self._keep_virtual_keys_right()
        try:
            # **A recording follows the CONTROL, not the keys.** A step is
            # where the user went and what they did there, so the focus is
            # what a recording is made of - and only the last control of a
            # run of Tabs, because passing through one is not visiting it.
            if procedures.recording():
                procedures.note_focus(obj)
        except Exception:                            # noqa: BLE001
            pass
        try:
            # **A review cursor must not outlive the terminal.** Left
            # running over a window the user has moved away from, it would
            # swallow their arrow keys in whatever they moved to - which is
            # the one way this feature could make a machine worse.
            if terminal.left_the_terminal():
                self._keep_terminal_keys_right()
            if ocrReview.left_the_window():
                self._keep_ocr_keys_right()
            if virtualWindow.left_the_window():
                self._keep_virtual_keys_right()
        except Exception:                            # noqa: BLE001
            pass
        try:
            # **Arriving in Titan, and leaving it.** Titan Access plays a
            # cue and says the desktop's name on the way in, because
            # somebody coming back from another program needs to know
            # where they are before a control is announced. Here rather
            # than in `event_foreground`: a window of Titan's own can take
            # the focus without ever being the foreground window - the
            # shell's furniture does it constantly - and the question is
            # about the process the keyboard is in.
            tce.crossing(obj)
        except Exception:                            # noqa: BLE001
            pass
        if not configSpec.read().get('replaceFocus', True):
            nextHandler()
            return
        try:
            focus.handle_gain_focus(obj, nextHandler)
        except Exception:                            # noqa: BLE001
            nextHandler()

    def event_foreground(self, obj, nextHandler):
        """A new window is in front.

        Two things belong HERE and not on every focus event, because both
        are questions about arriving somewhere rather than about a control:
        what kind of dialog this is, and whether this window exposes
        anything at all. Asking either per control is what made the region
        layer announce "dialog" in front of every button.
        """
        try:
            dialog_kind.announce(obj)
        except Exception:                            # noqa: BLE001
            pass
        try:
            surface.consider(obj, focus.module_for(obj))
        except Exception:                            # noqa: BLE001
            pass
        try:
            # **And the other direction.** Titan cannot work out which
            # window the user is really in; NVDA can, so it says so - once
            # per program rather than per event, on a thread of its own.
            reporting.changed(obj)
        except Exception:                            # noqa: BLE001
            pass
        try:
            # **A subsystem that comes on where it belongs.** The virtual
            # window is remembered per program, so arriving in a program
            # the user walks that way puts it back up without their asking
            # again - and only ever in a program they turned it on in
            # themselves, which is what keeps it from being a surprise.
            if virtualWindow.left_the_window() or virtualWindow.consider():
                self._keep_virtual_keys_right()
        except Exception:                            # noqa: BLE001
            pass
        self._keep_keys_right()
        nextHandler()

    #: The keys a drawn window's model borrows, and what each does. Tab
    #: and the up/down arrows walk the controls that were READ; Enter
    #: presses the one the cursor is on; Escape gives the keyboard back.
    #:
    #: Left and Right are deliberately NOT here. In a game they are how
    #: the game's own menu moves, and the highlight moving is what the
    #: watcher announces - so taking them would break the thing this is
    #: for while appearing to help.
    SMART_KEYS = {
        'kb:tab': 'smartNext',
        'kb:shift+tab': 'smartPrevious',
        'kb:downArrow': 'smartNext',
        'kb:upArrow': 'smartPrevious',
        'kb:enter': 'smartPress',
        'kb:escape': 'smartLeave',
    }

    #: The keys a terminal review borrows. Plain arrows, no modifier - that
    #: is the whole interaction, and it is why they can only be held while
    #: review is really on, in a terminal.
    TERMINAL_KEYS = {
        'kb:upArrow': 'terminalUp',
        'kb:downArrow': 'terminalDown',
        'kb:leftArrow': 'terminalLeft',
        'kb:rightArrow': 'terminalRight',
        'kb:pageUp': 'terminalPageUp',
        'kb:pageDown': 'terminalPageDown',
        'kb:home': 'terminalHome',
        'kb:end': 'terminalEnd',
        'kb:escape': 'terminalLeave',
    }

    def _borrow_terminal_keys(self, borrow=True):
        """The arrows, for as long as a terminal is being reviewed.

        Same discipline as the drawn-window cursor above and for the same
        reason: these are the shell's own keys the rest of the time, and a
        reader still holding them in the next window is a machine that has
        stopped answering its arrow keys.
        """
        for gesture, script_name in self.TERMINAL_KEYS.items():
            try:
                if borrow:
                    self.bindGesture(gesture, script_name)
                else:
                    self.removeGestureBinding(gesture)
            except Exception:                        # noqa: BLE001
                pass
        self._terminal_bound = bool(borrow)

    def _keep_terminal_keys_right(self):
        try:
            want = terminal.reviewing()
        except Exception:                            # noqa: BLE001
            want = False
        if want != getattr(self, '_terminal_bound', False):
            self._borrow_terminal_keys(want)

    #: The same keys again, for the recognised screen. Deliberately the same
    #: ones in the same places as the terminal review: a user should learn
    #: one set and not two. The two reviews cannot both be up - starting
    #: either is a key press, and each ends the other's binding by the same
    #: rule that ends its own.
    OCR_KEYS = {
        'kb:upArrow': 'ocrUp',
        'kb:downArrow': 'ocrDown',
        'kb:leftArrow': 'ocrLeft',
        'kb:rightArrow': 'ocrRight',
        'kb:pageUp': 'ocrPageUp',
        'kb:pageDown': 'ocrPageDown',
        'kb:home': 'ocrHome',
        'kb:end': 'ocrEnd',
        'kb:enter': 'ocrClick',
        'kb:f5': 'ocrRefresh',
        'kb:escape': 'ocrLeave',
    }

    #: The reviews' keys once more, for a Titan application described as a
    #: virtual window. The SAME keys in the same places for the third time,
    #: deliberately: a user should learn one set and not three. Up and Down
    #: are controls where the OCR review has lines, and Left and Right are
    #: what is inside one where the OCR review has words - the same
    #: relationship, one level up.
    APP_KEYS = {
        'kb:upArrow': 'appUp',
        'kb:downArrow': 'appDown',
        'kb:leftArrow': 'appLeft',
        'kb:rightArrow': 'appRight',
        'kb:pageUp': 'appPageUp',
        'kb:pageDown': 'appPageDown',
        'kb:home': 'appHome',
        'kb:end': 'appEnd',
        'kb:enter': 'appActivate',
        'kb:space': 'appToggle',
        'kb:f5': 'appRefresh',
        'kb:escape': 'appLeave',
    }

    def _borrow_app_keys(self, borrow=True):
        for gesture, script_name in self.APP_KEYS.items():
            try:
                if borrow:
                    self.bindGesture(gesture, script_name)
                else:
                    self.removeGestureBinding(gesture)
            except Exception:                        # noqa: BLE001
                pass
        self._app_bound = bool(borrow)

    def _keep_app_keys_right(self):
        try:
            want = appReview.reviewing()
        except Exception:                            # noqa: BLE001
            want = False
        if want != getattr(self, '_app_bound', False):
            self._borrow_app_keys(want)

    #: The same keys a fourth time, for any window at all walked as a
    #: virtual window. Enter CLICKS here rather than pressing a described
    #: control, because outside Titan there is no description - there is a
    #: control on the screen, and clicking it is what a sighted person
    #: would do.
    VIRTUAL_KEYS = {
        'kb:upArrow': 'virtualUp',
        'kb:downArrow': 'virtualDown',
        'kb:leftArrow': 'virtualLeft',
        'kb:rightArrow': 'virtualRight',
        'kb:pageUp': 'virtualPageUp',
        'kb:pageDown': 'virtualPageDown',
        'kb:home': 'virtualHome',
        'kb:end': 'virtualEnd',
        'kb:enter': 'virtualActivate',
        'kb:f5': 'virtualRefresh',
        'kb:escape': 'virtualLeave',
    }

    def _virtual_gestures(self):
        """Every key the virtual window borrows, quick navigation and all.

        **One script for every letter**, which is what makes fifteen
        letters and their fifteen backwards twins two entries in Input
        Gestures rather than thirty. NVDA hands the script the gesture, so
        the letter is read off the key that was really pressed.
        """
        gestures = dict(self.VIRTUAL_KEYS)
        from . import virtualWindow as vw
        for letter in vw.QUICK:
            gestures['kb:%s' % letter] = 'virtualQuick'
            gestures['kb:shift+%s' % letter] = 'virtualQuickBack'
        return gestures

    def _borrow_virtual_keys(self, borrow=True):
        for gesture, script_name in self._virtual_gestures().items():
            try:
                if borrow:
                    self.bindGesture(gesture, script_name)
                else:
                    self.removeGestureBinding(gesture)
            except Exception:                        # noqa: BLE001
                pass
        self._virtual_bound = bool(borrow)

    def _keep_virtual_keys_right(self):
        try:
            want = virtualWindow.reviewing()
        except Exception:                            # noqa: BLE001
            want = False
        if want != getattr(self, '_virtual_bound', False):
            self._borrow_virtual_keys(want)

    def _borrow_ocr_keys(self, borrow=True):
        for gesture, script_name in self.OCR_KEYS.items():
            try:
                if borrow:
                    self.bindGesture(gesture, script_name)
                else:
                    self.removeGestureBinding(gesture)
            except Exception:                        # noqa: BLE001
                pass
        self._ocr_bound = bool(borrow)

    def _keep_ocr_keys_right(self):
        try:
            want = ocrReview.reviewing()
        except Exception:                            # noqa: BLE001
            want = False
        if want != getattr(self, '_ocr_bound', False):
            self._borrow_ocr_keys(want)

    def _borrow_keys(self, borrow=True):
        """Take the navigation keys while a drawn window is being read.

        **Bound only while it is really needed and given straight back.** A
        reader that held Tab for the whole session would break every other
        program on the machine, so the binding follows the watch: it is
        made when a window starts being read and removed the moment it
        stops. Every script also passes the key through if it turns out
        not to be in that window, which is the second guard - a binding
        that outlived its window would otherwise swallow a keystroke with
        nothing to say about it.
        """
        for gesture, script_name in self.SMART_KEYS.items():
            try:
                if borrow:
                    self.bindGesture(gesture, script_name)
                else:
                    self.removeGestureBinding(gesture)
            except Exception:                        # noqa: BLE001
                pass
        self._smart_bound = bool(borrow)

    def _keep_keys_right(self):
        """Borrow the navigation keys, or give them back. Cheap; called on
        the events that can change the answer.

        Only for an inaccessible APPLICATION. A game keeps its own keys -
        its menu is what the arrows are for, and the reader's job there is
        to say what has become highlighted, not to run a second cursor.
        """
        try:
            want = (smart.active()
                    and surface.report().get('mode')
                    == surface.MODE_APPLICATION)
        except Exception:                            # noqa: BLE001
            want = False
        if want != self._smart_bound:
            self._borrow_keys(want)

    def _smart_here(self):
        """Whether the drawn window being read is the one in front."""
        if not smart.active():
            return False
        try:
            import api
            focus = api.getFocusObject()
            import ctypes
            root = int(ctypes.windll.user32.GetAncestor(
                ctypes.c_void_p(int(getattr(focus, 'windowHandle', 0) or 0)),
                2) or 0)
            return root == smart.window()
        except Exception:                            # noqa: BLE001
            return True

    def event_nameChange(self, obj, nextHandler):
        """Something changed while the focus was somewhere else."""
        self._live(obj)
        nextHandler()

    def event_valueChange(self, obj, nextHandler):
        self._live(obj)
        nextHandler()

    def _live(self, obj):
        try:
            live.changed(obj, focus.module_for(obj))
        except Exception:                            # noqa: BLE001
            pass

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
        description=_('Reads the last AI OCR reading again, without '
                      'reading the screen afresh'),
        category=CATEGORY)
    def script_titanOcrAgain(self, gesture):
        commands.ocr_again()

    @script(
        # Translators: an NVDA command.
        description=_('Presses a control AI OCR read, by its name'),
        category=CATEGORY)
    def script_titanOcrPress(self, gesture):
        commands.ocr_press()

    @script(
        # Translators: an NVDA command.
        description=_('Sends a whole key to the window AI OCR read'),
        category=CATEGORY)
    def script_titanOcrKey(self, gesture):
        commands.ocr_key()

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
        description=_('Reads Titan\'s notifications'),
        category=CATEGORY)
    def script_titanNotifications(self, gesture):
        commands.notifications()

    @script(
        # Translators: an NVDA command.
        description=_('Reads a Titan buffer: what arrived while its window '
                      'was closed'),
        category=CATEGORY)
    def script_titanBuffers(self, gesture):
        commands.buffers()

    @script(
        # Translators: an NVDA command.
        description=_('Says what Titan is showing right now'),
        category=CATEGORY)
    def script_titanShowing(self, gesture):
        commands.showing()

    @script(
        # Translators: an NVDA command.
        description=_('Lists Titan\'s components'),
        category=CATEGORY)
    def script_titanComponents(self, gesture):
        commands.components()

    @script(
        # Translators: an NVDA command.
        description=_('Asks Titan what it can do, so every one of its '
                      'actions can be given a key in Input Gestures'),
        category=CATEGORY)
    def script_titanRefreshActions(self, gesture):
        commands.refresh_actions(self)

    def _smart_move(self, gesture, step):
        if not self._smart_here():
            gesture.send()
            return
        moved = smart.move(step)
        if moved is None:
            gesture.send()
            return
        smart.say(moved)

    @script(
        # Translators: an NVDA command.
        description=_('Read this window with Windows\' own recogniser - no '
                      'AI, nothing sent anywhere'),
        category=CATEGORY, gesture='kb:NVDA+shift+o')
    def script_readLocally(self, gesture):
        commands.read_locally()
        self._keep_keys_right()

    @script(
        # Translators: an NVDA command.
        description=_('The windows, their controls, and what each control '
                      'can do'),
        category=CATEGORY, gesture='kb:NVDA+control+w')
    def script_windowsAndActions(self, gesture):
        commands.windows_and_actions()

    @script(
        # Translators: an NVDA command.
        description=_('The manager: place markers, watched areas and the '
                      'sound scheme'),
        category=CATEGORY, gesture='kb:NVDA+shift+j')
    def script_manager(self, gesture):
        commands.manager()

    @script(
        # Translators: an NVDA command.
        description=_('Run the add-on\'s own features here and say what '
                      'worked'),
        category=CATEGORY)
    def script_selfTest(self, gesture):
        commands.self_test()

    # ------------------------------------------------- the recognised screen
    @script(
        # Translators: an NVDA command.
        description=_('Read this window and walk it with the arrow keys; '
                      'Enter clicks where you are'),
        category=CATEGORY, gesture='kb:NVDA+o')
    def script_ocrReview(self, gesture):
        def work():
            _on, said = ocrReview.toggle()
            self._keep_ocr_keys_right()
            dialogs.report(said)
        commands._work(work)

    def _ocr_move(self, gesture, move):
        if not ocrReview.reviewing():
            self._keep_ocr_keys_right()
            gesture.send()
            return
        try:
            move()
        except Exception:                            # noqa: BLE001
            gesture.send()

    @script(description=_('In the screen review: the line above'),
            category=CATEGORY)
    def script_ocrUp(self, gesture):
        self._ocr_move(gesture, lambda: ocrReview.move_line(-1))

    @script(description=_('In the screen review: the line below'),
            category=CATEGORY)
    def script_ocrDown(self, gesture):
        self._ocr_move(gesture, lambda: ocrReview.move_line(1))

    @script(description=_('In the screen review: the word before'),
            category=CATEGORY)
    def script_ocrLeft(self, gesture):
        self._ocr_move(gesture, lambda: ocrReview.move_word(-1))

    @script(description=_('In the screen review: the word after'),
            category=CATEGORY)
    def script_ocrRight(self, gesture):
        self._ocr_move(gesture, lambda: ocrReview.move_word(1))

    @script(description=_('In the screen review: a screenful back'),
            category=CATEGORY)
    def script_ocrPageUp(self, gesture):
        self._ocr_move(gesture, lambda: ocrReview.move_page(-1))

    @script(description=_('In the screen review: a screenful on'),
            category=CATEGORY)
    def script_ocrPageDown(self, gesture):
        self._ocr_move(gesture, lambda: ocrReview.move_page(1))

    @script(description=_('In the screen review: the start of the line'),
            category=CATEGORY)
    def script_ocrHome(self, gesture):
        self._ocr_move(gesture, lambda: ocrReview.move_end(False))

    @script(description=_('In the screen review: the end of the line'),
            category=CATEGORY)
    def script_ocrEnd(self, gesture):
        self._ocr_move(gesture, lambda: ocrReview.move_end(True))

    @script(
        # Translators: an NVDA command.
        description=_('In the screen review: click where you are'),
        category=CATEGORY)
    def script_ocrClick(self, gesture):
        if not ocrReview.reviewing():
            gesture.send()
            return
        _ok, said = ocrReview.click()
        dialogs.report(said)

    @script(
        # Translators: an NVDA command.
        description=_('In the screen review: read the window again'),
        category=CATEGORY)
    def script_ocrRefresh(self, gesture):
        if not ocrReview.reviewing():
            gesture.send()
            return

        def work():
            _ok, said = ocrReview.refresh()
            dialogs.report(said)
        commands._work(work)

    @script(
        # Translators: an NVDA command.
        description=_('Leave the screen review'), category=CATEGORY)
    def script_ocrLeave(self, gesture):
        if not ocrReview.reviewing():
            gesture.send()
            return
        _on, said = ocrReview.stop()
        self._keep_ocr_keys_right()
        dialogs.report(said)

    # ---------------------------------------------- what the reader said
    @script(
        # Translators: an NVDA command.
        description=_('What the reader has said, and go back to what said '
                      'it'),
        category=CATEGORY, gesture='kb:NVDA+shift+h')
    def script_journal(self, gesture):
        commands.read_journal()

    @script(
        # Translators: an NVDA command.
        description=_('Find something the reader said, and go back to what '
                      'said it'),
        category=CATEGORY)
    def script_searchJournal(self, gesture):
        commands.search_journal()

    @script(
        # Translators: an NVDA command.
        description=_('What the reader has said, as a page to read'),
        category=CATEGORY)
    def script_journalPage(self, gesture):
        commands.journal_page()

    # ------------------------------------------------------- procedures
    @script(
        # Translators: an NVDA command.
        description=_('Start recording what you do, or keep what was '
                      'recorded'),
        category=CATEGORY, gesture='kb:NVDA+shift+r')
    def script_recordProcedure(self, gesture):
        commands.record_procedure()

    @script(
        # Translators: an NVDA command.
        description=_('Throw away what is being recorded'),
        category=CATEGORY)
    def script_cancelProcedure(self, gesture):
        commands.cancel_procedure()

    @script(
        # Translators: an NVDA command.
        description=_('Do one of this program\'s recorded procedures again'),
        category=CATEGORY, gesture='kb:NVDA+r')
    def script_runProcedure(self, gesture):
        commands.run_procedure()

    @script(
        # Translators: an NVDA command.
        description=_('Read the steps of a recorded procedure'),
        category=CATEGORY)
    def script_readProcedure(self, gesture):
        commands.read_procedure()

    # -------------------------------------------------- finding a control
    @script(
        # Translators: an NVDA command.
        description=_('Find a control in this window by its name or by what '
                      'is written on the screen'),
        category=CATEGORY, gesture='kb:NVDA+control+f')
    def script_findControl(self, gesture):
        commands.find_control()

    @script(
        # Translators: an NVDA command.
        description=_('Find a control by what it DOES, using the AI'),
        category=CATEGORY)
    def script_findControlWithAI(self, gesture):
        commands.find_control_with_ai()

    # ------------------------------------------------------ place markers
    @script(
        # Translators: an NVDA command.
        description=_('Mark the control you are on, so a key comes back to '
                      'it'),
        category=CATEGORY, gesture='kb:NVDA+shift+m')
    def script_markThis(self, gesture):
        commands.mark_this()

    @script(
        # Translators: an NVDA command.
        description=_('Go to one of this program\'s place markers'),
        category=CATEGORY, gesture='kb:NVDA+m')
    def script_goToMarker(self, gesture):
        commands.go_to_marker()

    @script(
        # Translators: an NVDA command.
        description=_('Forget one of this program\'s place markers'),
        category=CATEGORY)
    def script_forgetMarker(self, gesture):
        commands.forget_marker()

    @script(
        # Translators: an NVDA command.
        description=_('Which state is answered with a sound instead of the '
                      'word'),
        category=CATEGORY)
    def script_soundScheme(self, gesture):
        commands.sound_scheme()

    # -------------------------------------------------- watching an area
    @script(
        # Translators: an NVDA command.
        description=_('Watch the object the navigator is on, and say when '
                      'it changes'),
        category=CATEGORY, gesture='kb:NVDA+shift+w')
    def script_watchThis(self, gesture):
        commands.watch_this()

    @script(
        # Translators: an NVDA command.
        description=_('Watch the area this object covers with Windows\' '
                      'own recogniser, and say when it changes'),
        category=CATEGORY)
    def script_watchThisArea(self, gesture):
        commands.watch_this_area()

    @script(
        # Translators: an NVDA command.
        description=_('Watch this whole window with Windows\' own '
                      'recogniser, and say when it changes'),
        category=CATEGORY)
    def script_watchThisWindow(self, gesture):
        commands.watch_this_window()

    @script(
        # Translators: an NVDA command.
        description=_('What is being watched, and stop watching one'),
        category=CATEGORY, gesture='kb:NVDA+control+shift+w')
    def script_watchedAreas(self, gesture):
        commands.watched_areas()

    # ------------------------------------------- any window at all
    def _virtual_move(self, gesture, move):
        if not virtualWindow.reviewing():
            self._keep_virtual_keys_right()
            gesture.send()
            return
        try:
            move()
        except Exception:                            # noqa: BLE001
            gesture.send()

    @script(description=_('In the virtual window: the control above'),
            category=CATEGORY)
    def script_virtualUp(self, gesture):
        self._virtual_move(gesture, lambda: virtualWindow.move(-1))

    @script(description=_('In the virtual window: the control below'),
            category=CATEGORY)
    def script_virtualDown(self, gesture):
        self._virtual_move(gesture, lambda: virtualWindow.move(1))

    @script(description=_('In the virtual window: back through what this '
                          'control says'),
            category=CATEGORY)
    def script_virtualLeft(self, gesture):
        self._virtual_move(gesture, lambda: virtualWindow.move_inside(-1))

    @script(description=_('In the virtual window: on through what this '
                          'control says'),
            category=CATEGORY)
    def script_virtualRight(self, gesture):
        self._virtual_move(gesture, lambda: virtualWindow.move_inside(1))

    @script(description=_('In the virtual window: ten controls back'),
            category=CATEGORY)
    def script_virtualPageUp(self, gesture):
        self._virtual_move(gesture, lambda: virtualWindow.move_page(-1))

    @script(description=_('In the virtual window: ten controls on'),
            category=CATEGORY)
    def script_virtualPageDown(self, gesture):
        self._virtual_move(gesture, lambda: virtualWindow.move_page(1))

    @script(description=_('In the virtual window: the first control'),
            category=CATEGORY)
    def script_virtualHome(self, gesture):
        self._virtual_move(gesture, lambda: virtualWindow.move_end(False))

    @script(description=_('In the virtual window: the last control'),
            category=CATEGORY)
    def script_virtualEnd(self, gesture):
        self._virtual_move(gesture, lambda: virtualWindow.move_end(True))

    @script(description=_('In the virtual window: click what you are on'),
            category=CATEGORY)
    def script_virtualActivate(self, gesture):
        if not virtualWindow.reviewing():
            self._keep_virtual_keys_right()
            gesture.send()
            return
        _ok, said = virtualWindow.activate()
        if said:
            dialogs.report(said)

    @script(description=_('In the virtual window: build it again'),
            category=CATEGORY)
    def script_virtualRefresh(self, gesture):
        if not virtualWindow.reviewing():
            self._keep_virtual_keys_right()
            gesture.send()
            return
        _ok, said = virtualWindow.refresh()
        dialogs.report(said)

    @script(description=_('Leave the virtual window'), category=CATEGORY)
    def script_virtualLeave(self, gesture):
        if not virtualWindow.reviewing():
            self._keep_virtual_keys_right()
            gesture.send()
            return
        _on, said = virtualWindow.stop()
        self._keep_virtual_keys_right()
        dialogs.report(said)

    def _quick(self, gesture, back):
        if not virtualWindow.reviewing():
            self._keep_virtual_keys_right()
            gesture.send()
            return
        if virtualWindow.typing_now():
            # The keyboard is in a field, a document or a terminal, so a
            # bare letter is the letter. This mode can turn itself on in a
            # program the user chose, which is exactly when this matters.
            gesture.send()
            return
        letter = str(getattr(gesture, 'mainKeyName', '') or '').lower()
        if letter not in virtualWindow.QUICK:
            # A key that turns out not to be ours is passed straight
            # through - the second guard every borrowed key here carries,
            # so a binding that outlived its window swallows nothing.
            gesture.send()
            return
        _ok, said = virtualWindow.jump(letter, back=back)
        if said:
            dialogs.report(said)

    @script(description=_('In the virtual window: the next button, heading, '
                          'check box, list and so on - b, h, x, i, l, c, e, '
                          't, k, g, s, m, a, o'),
            category=CATEGORY)
    def script_virtualQuick(self, gesture):
        self._quick(gesture, back=False)

    @script(description=_('In the virtual window: the same, backwards'),
            category=CATEGORY)
    def script_virtualQuickBack(self, gesture):
        self._quick(gesture, back=True)

    @script(
        # Translators: an NVDA command.
        description=_('Walk this window as a virtual window of all its '
                      'controls'),
        category=CATEGORY)
    def script_virtualWindow(self, gesture):
        _on, said = virtualWindow.toggle()
        self._keep_virtual_keys_right()
        dialogs.report(said)

    # --------------------------------------------- a Titan application
    @script(
        # Translators: an NVDA command.
        description=_('Open one of Titan\'s applications and walk it with '
                      'the arrow keys'),
        category=CATEGORY, gesture='kb:NVDA+shift+a')
    def script_titanApplications(self, gesture):
        def work():
            commands.titan_applications()
            self._keep_app_keys_right()
        commands._work(work)

    def _app_move(self, gesture, move):
        if not appReview.reviewing():
            self._keep_app_keys_right()
            gesture.send()
            return
        try:
            move()
        except Exception:                            # noqa: BLE001
            gesture.send()

    @script(description=_('In an application: the control above'),
            category=CATEGORY)
    def script_appUp(self, gesture):
        self._app_move(gesture, lambda: appReview.move(-1))

    @script(description=_('In an application: the control below'),
            category=CATEGORY)
    def script_appDown(self, gesture):
        self._app_move(gesture, lambda: appReview.move(1))

    @script(description=_('In an application: back through what is inside '
                          'this control'),
            category=CATEGORY)
    def script_appLeft(self, gesture):
        self._app_move(gesture, lambda: appReview.move_inside(-1))

    @script(description=_('In an application: on through what is inside '
                          'this control'),
            category=CATEGORY)
    def script_appRight(self, gesture):
        self._app_move(gesture, lambda: appReview.move_inside(1))

    @script(description=_('In an application: ten controls back'),
            category=CATEGORY)
    def script_appPageUp(self, gesture):
        self._app_move(gesture, lambda: appReview.move_page(-1))

    @script(description=_('In an application: ten controls on'),
            category=CATEGORY)
    def script_appPageDown(self, gesture):
        self._app_move(gesture, lambda: appReview.move_page(1))

    @script(description=_('In an application: the first control'),
            category=CATEGORY)
    def script_appHome(self, gesture):
        self._app_move(gesture, lambda: appReview.move_end(False))

    @script(description=_('In an application: the last control'),
            category=CATEGORY)
    def script_appEnd(self, gesture):
        self._app_move(gesture, lambda: appReview.move_end(True))

    @script(description=_('In an application: press what you are on'),
            category=CATEGORY)
    def script_appActivate(self, gesture):
        if not appReview.reviewing():
            self._keep_app_keys_right()
            gesture.send()
            return
        _ok, said = appReview.activate()
        if said:
            dialogs.report(said)

    @script(description=_('In an application: tick or untick what you are '
                          'on'),
            category=CATEGORY)
    def script_appToggle(self, gesture):
        if not appReview.reviewing():
            self._keep_app_keys_right()
            gesture.send()
            return
        _ok, said = appReview.toggle()
        if said:
            dialogs.report(said)

    @script(description=_('In an application: read the screen again'),
            category=CATEGORY)
    def script_appRefresh(self, gesture):
        if not appReview.reviewing():
            self._keep_app_keys_right()
            gesture.send()
            return
        _ok, said = appReview.refresh()
        dialogs.report(said)

    @script(description=_('Leave the application review'),
            category=CATEGORY)
    def script_appLeave(self, gesture):
        if not appReview.reviewing():
            self._keep_app_keys_right()
            gesture.send()
            return
        _on, said = appReview.stop()
        self._keep_app_keys_right()
        dialogs.report(said)

    @script(
        # Translators: an NVDA command.
        description=_('Type into the field you are on in a Titan '
                      'application'),
        category=CATEGORY)
    def script_appType(self, gesture):
        commands.type_into_application()

    @script(
        # Translators: an NVDA command.
        description=_('Show the application being reviewed as real '
                      'controls instead'),
        category=CATEGORY)
    def script_appAsWindow(self, gesture):
        commands.application_as_a_window()
        self._keep_app_keys_right()

    @script(
        # Translators: an NVDA command.
        description=_('Close the Titan application being reviewed'),
        category=CATEGORY)
    def script_appClose(self, gesture):
        commands.close_application()
        self._keep_app_keys_right()

    @script(
        # Translators: an NVDA command.
        description=_('Titan: everything it can start, its settings, what '
                      'arrived'),
        category=CATEGORY, gesture='kb:NVDA+shift+i')
    def script_titanWindow(self, gesture):
        commands.titan_window()

    # ------------------------------------------------------- the terminal
    @script(
        # Translators: an NVDA command.
        description=_('In a terminal: review what is on the screen with the '
                      'plain arrow keys'),
        category=CATEGORY, gesture='kb:numpadMinus')
    def script_terminalReview(self, gesture):
        """**One review key, and what it reviews is decided by where you
        are.**

        In a terminal it is the terminal's own text. Everywhere else it is
        the window itself, as a virtual window of every control in it -
        which is what the user asked for, and it is the same idea one
        level up: the same keys walk the same shape whatever is underneath.

        Deciding here rather than making the user remember two keys is the
        point. A terminal is the one window whose content is text rather
        than controls, so it is the one case that needs its own answer -
        and asking `terminal.is_terminal` is exactly that question.
        """
        if virtualWindow.reviewing():
            _on, said = virtualWindow.stop()
            self._keep_virtual_keys_right()
            dialogs.report(said)
            return
        if terminal.reviewing() or terminal.is_terminal():
            on, said = terminal.toggle()
            self._keep_terminal_keys_right()
            dialogs.report(said)
            return
        _on, said = virtualWindow.toggle()
        self._keep_virtual_keys_right()
        dialogs.report(said)

    def _terminal_move(self, gesture, move):
        """One review key. Passes the key through when review is not on.

        A binding that outlived its window would otherwise swallow an arrow
        key in whatever the user moved to, with nothing to say about it -
        the same guard the drawn-window cursor has, for the same reason.
        """
        if not terminal.reviewing():
            self._keep_terminal_keys_right()
            gesture.send()
            return
        try:
            move()
        except Exception:                            # noqa: BLE001
            gesture.send()

    @script(description=_('In a terminal review: the line above'),
            category=CATEGORY)
    def script_terminalUp(self, gesture):
        self._terminal_move(gesture, lambda: terminal.move_line(-1))

    @script(description=_('In a terminal review: the line below'),
            category=CATEGORY)
    def script_terminalDown(self, gesture):
        self._terminal_move(gesture, lambda: terminal.move_line(1))

    @script(description=_('In a terminal review: the character before'),
            category=CATEGORY)
    def script_terminalLeft(self, gesture):
        self._terminal_move(gesture, lambda: terminal.move_char(-1))

    @script(description=_('In a terminal review: the character after'),
            category=CATEGORY)
    def script_terminalRight(self, gesture):
        self._terminal_move(gesture, lambda: terminal.move_char(1))

    @script(description=_('In a terminal review: a screenful back'),
            category=CATEGORY)
    def script_terminalPageUp(self, gesture):
        self._terminal_move(gesture, lambda: terminal.move_page(-1))

    @script(description=_('In a terminal review: a screenful on'),
            category=CATEGORY)
    def script_terminalPageDown(self, gesture):
        self._terminal_move(gesture, lambda: terminal.move_page(1))

    @script(description=_('In a terminal review: the start of the line'),
            category=CATEGORY)
    def script_terminalHome(self, gesture):
        self._terminal_move(gesture, lambda: terminal.move_end(False))

    @script(description=_('In a terminal review: the end of the line'),
            category=CATEGORY)
    def script_terminalEnd(self, gesture):
        self._terminal_move(gesture, lambda: terminal.move_end(True))

    @script(description=_('Leave the terminal review'), category=CATEGORY)
    def script_terminalLeave(self, gesture):
        if not terminal.reviewing():
            gesture.send()
            return
        _on, said = terminal.stop()
        self._keep_terminal_keys_right()
        dialogs.report(said)

    @script(description=_('In a window being read as a picture: the next '
                          'control'), category=CATEGORY)
    def script_smartNext(self, gesture):
        self._smart_move(gesture, 1)

    @script(description=_('In a window being read as a picture: the '
                          'previous control'), category=CATEGORY)
    def script_smartPrevious(self, gesture):
        self._smart_move(gesture, -1)

    @script(description=_('In a window being read as a picture: press the '
                          'control you are on'), category=CATEGORY)
    def script_smartPress(self, gesture):
        if not self._smart_here():
            gesture.send()
            return
        commands.smart_press()

    @script(description=_('Stop reading this window as a picture and give '
                          'the keyboard back'), category=CATEGORY)
    def script_smartLeave(self, gesture):
        if not self._smart_here():
            gesture.send()
            return
        commands.watch_surface()

    @script(
        # Translators: an NVDA command.
        description=_('Says where the keyboard is: the window, the dialog '
                      'and the part of it you are in'),
        category=CATEGORY, gesture='kb:NVDA+alt+w')
    def script_titanWhereAmI(self, gesture):
        commands.where_am_i()

    @script(
        # Translators: an NVDA command.
        description=_('Opens the voices: what each kind of thing sounds '
                      'like, and in what order a control is read'),
        category=CATEGORY, gesture='kb:NVDA+alt+c')
    def script_titanClasses(self, gesture):
        commands.voice_classes()

    @script(
        # Translators: an NVDA command.
        description=_('Gives the control you are on a name, and remembers '
                      'it'),
        category=CATEGORY, gesture='kb:NVDA+alt+l')
    def script_titanLabel(self, gesture):
        commands.label_control()

    @script(
        # Translators: an NVDA command.
        description=_('Says what the picture or the control you are on '
                      'shows, by reading it'),
        category=CATEGORY, gesture='kb:NVDA+alt+g')
    def script_titanDescribe(self, gesture):
        commands.describe_control()

    @script(
        # Translators: an NVDA command.
        description=_('Reads a window that exposes nothing - a game\'s menu '
                      '- as a picture, and follows what is highlighted'),
        category=CATEGORY, gesture='kb:NVDA+alt+u')
    def script_titanSurface(self, gesture):
        commands.watch_surface()

    @script(
        # Translators: an NVDA command.
        description=_('Writes a reader module for the program you are in'),
        category=CATEGORY, gesture='kb:NVDA+alt+d')
    def script_titanDraftModule(self, gesture):
        commands.draft_module()

    @script(
        # Translators: an NVDA command.
        description=_('Lists the reader modules and what each one knows'),
        category=CATEGORY)
    def script_titanReaderModules(self, gesture):
        commands.reader_modules()

    @script(
        # Translators: an NVDA command.
        description=_('Uses the laptop\'s touchpad as a touch screen, so '
                      'NVDA\'s touch gestures work on it'),
        category=CATEGORY, gesture='kb:NVDA+windows+t')
    def script_titanTrackpad(self, gesture):
        commands.toggle_trackpad()

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


# --------------------------------------------------------------------------- #
# One key per numbered place marker
# --------------------------------------------------------------------------- #
#: **The number is the whole point of a place marker.** JAWS' numbered ones
#: are why anybody uses the feature: the third thing you marked is always the
#: third thing, so going there becomes a key you press without reading a
#: list. A list is what you open when you have forgotten.
#:
#: They are made on the CLASS and not in `__init__`, because NVDA's Input
#: Gestures dialog does not list what an instance carries - it walks
#: `cls.__dict__` along the mro. A script set on the instance runs perfectly
#: once a gesture is bound to it and can never be FOUND to bind one, which
#: is this add-on's own most expensive mistake, made once already.
def _install_marker_scripts():
    from . import markers

    def make(number):
        def script(self, gesture):
            commands.marker_number(number)
        script.__name__ = 'script_marker%d' % number
        # Translators: an NVDA command. {n} is the marker's number.
        script.__doc__ = _('Go to place marker {n} in this program').format(
            n=number)
        script.category = CATEGORY
        return script

    for number in range(1, markers.NUMBERED + 1):
        setattr(GlobalPlugin, 'script_marker%d' % number, make(number))


_install_marker_scripts()
