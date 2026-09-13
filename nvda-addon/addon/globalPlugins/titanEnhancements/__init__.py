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

from . import agentLink
from . import channel                                # noqa: F401
from . import commands
from . import compat
from . import configSpec
from . import dialog_kind
from . import layers
from . import shared      # noqa: F401
from . import windowKind
from . import dialogs
from . import earcons
from . import focus
from . import gestures
from . import guest
from . import i18n
from . import interject
from . import link
from . import live
from . import menu as titan_menu
from . import monitors
from . import appReview
from . import ocrReview
from . import reporting
from . import palette
from . import virtualWindow
from . import widgetReview
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


def _close_described_applications():
    """Close the TCE applications this add-on opened.

    A described application is a subprocess of TITAN's that only this
    add-on is rendering, so NVDA going away with one open leaves a program
    running that nobody can see or reach.
    """
    try:
        from . import titan
        titan.close_all_described()
    except Exception:                                # noqa: BLE001
        pass


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = CATEGORY

    def __init__(self):
        super().__init__()
        self._panel = None
        self._smart_bound = False
        self._guest_bound = False
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
            try:
                # The ear for an agent on the far side of a wall - a guest,
                # or a game engine. Off until asked for, and a switch that
                # is off starts nothing at all: this opens a socket.
                agentLink.keep_running()
            except Exception as error:               # noqa: BLE001
                if compat.log is not None:
                    compat.log.error(
                        'Titan agent channel: %s' % error)
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
            agentLink.stop()
            agentLink.stop_variables()
        except Exception:                            # noqa: BLE001
            pass
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
            # NVDA's own `cancelSpeech` back. A wrapper left behind by an
            # add-on that has gone is a reader calling into a module
            # nobody owns - the same rule as `origin.stop` above.
            speaking.unfollow_cancel()
        except Exception:                            # noqa: BLE001
            pass
        try:
            if self._smart_bound:
                self._borrow_keys(False)
        except Exception:                            # noqa: BLE001
            pass
        try:
            if self._guest_bound:
                self._guest_bound = False
                for gesture in self.GUEST_KEYS:
                    try:
                        self.removeGestureBinding(gesture)
                    except Exception:                # noqa: BLE001
                        pass
        except Exception:                            # noqa: BLE001
            pass
        for leave in (guest.stop, states.stop, trackpad.stop,
                      surface.stop_now,
                      terminal.stop, monitors.stop, ocrReview.stop,
                      appReview.stop, virtualWindow.stop,
                      widgetReview.stop, _close_described_applications):
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
                # **What the user taught the other reader.** Titan being
                # there means Titan Access's own folder is there, and a
                # control they named in one reader should be named in the
                # other. On THIS thread, which is the watcher's own and
                # not the focus path: reading and writing a JSON file is
                # milliseconds, and milliseconds on every arrival is a
                # reader that got slower for no reason anybody can see.
                try:
                    ok, said = shared.sync_labels()
                    if compat.log is not None:
                        compat.log.info('Titan shared names: %s'
                                        % (said if ok else 'not shared: '
                                           + str(said)))
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
        self._keep_widget_keys_right()
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
            self._keep_palette_keys_right()
            self._keep_typing_keys_right()
        except Exception:                            # noqa: BLE001
            pass
        try:
            # **Arriving is not the only way to be somewhere.** Switching
            # this on WHILE looking at a guest - which is exactly what
            # somebody does - fired no foreground event, so nothing ever
            # started and the setting appeared to do nothing at all.
            # Found by trying to drive it from outside and discovering
            # that Windows will not let a background process change the
            # foreground window, which is also why the user's own machine
            # would have shown this. Refusing costs one class check.
            if not guest.following():
                guest.consider(obj)
            self._keep_guest_keys_right()
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
            # **The kind of window, when the kind of DIALOG is not the
            # question.** `dialog_kind` answers four kinds of dialog well
            # and says nothing about every other window, which is nearly
            # all of them; `windowKind` is the rest of that sentence. It
            # is asked only when the first said nothing, so a warning is
            # never also announced as "a small window".
            if not dialog_kind.announce(obj):
                windowKind.announce(obj)
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
        try:
            # **A virtual machine in front is the whole signal.** There is
            # deliberately no key to press: the guest's window IS another
            # computer's screen, so following the pointer in it is what
            # this does whenever the user is looking at one, and a window
            # that is not this guest's is a guest they have left.
            if not guest.crossing(obj):
                guest.consider(obj)
        except Exception:                            # noqa: BLE001
            pass
        try:
            self._keep_guest_keys_right()
        except Exception:                            # noqa: BLE001
            pass
        self._keep_keys_right()
        nextHandler()

    #: **The keys that move something in a picture.** Arrowing through a
    #: guest's icons, a game's menu or an installer's options changes
    #: nothing on the host - no focus event, no caret, no object - so the
    #: only thing that says what happened is the picture, and the only
    #: cheap moment to look at it is just after the key.
    #:
    #: Every one of them is SENT ON first and unconditionally. These are
    #: the guest's keys, or the game's; a reader that swallowed one would
    #: break the window it was trying to describe. They are bound only
    #: while such a window is really in front, and given straight back.
    #:
    #: Enter is here because it is where a new screen appears. Space is
    #: not: it is typing, and so is everything else left out.
    GUEST_KEYS = {
        'kb:upArrow': 'guestMoved',
        'kb:downArrow': 'guestMoved',
        'kb:leftArrow': 'guestMoved',
        'kb:rightArrow': 'guestMoved',
        'kb:tab': 'guestMoved',
        'kb:shift+tab': 'guestMoved',
        'kb:home': 'guestMoved',
        'kb:end': 'guestMoved',
        'kb:pageUp': 'guestMoved',
        'kb:pageDown': 'guestMoved',
        'kb:enter': 'guestMoved',
    }

    def _keep_guest_keys_right(self):
        try:
            want = bool(guest.following())
        except Exception:                            # noqa: BLE001
            want = False
        if want == getattr(self, '_guest_bound', False):
            return
        for gesture, script_name in self.GUEST_KEYS.items():
            try:
                if want:
                    self.bindGesture(gesture, script_name)
                else:
                    self.removeGestureBinding(gesture)
            except Exception:                        # noqa: BLE001
                pass
        self._guest_bound = want

    @script(description=_('In a virtual machine, a game or a window that '
                          'draws itself: say what the key moved onto'),
            category=CATEGORY)
    def script_guestMoved(self, gesture):
        # **Sent on first, and whatever happens next.** This key belongs
        # to the window being described.
        try:
            gesture.send()
        except Exception:                            # noqa: BLE001
            pass
        if not guest.following():
            # A binding that outlived its window: give the keys back
            # rather than reading somebody else's screen.
            self._keep_guest_keys_right()
            return
        try:
            if compat.core is not None:
                compat.core.callLater(int(guest.SETTLE * 1000),
                                      guest.after_key)
            else:
                guest.after_key()
        except Exception:                            # noqa: BLE001
            pass


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
        # The numpad corners, as in every other walked list: the first and
        # the last line, at their first and their last word.
        'kb:numpad7': 'ocrUpLeft',
        'kb:numpad9': 'ocrUpRight',
        'kb:numpad1': 'ocrDownLeft',
        'kb:numpad3': 'ocrDownRight',
    }

    #: The reviews' keys once more, for a Titan application described as a
    #: virtual window. The SAME keys in the same places for the third time,
    #: deliberately: a user should learn one set and not three. Up and Down
    #: are controls where the OCR review has lines, and Left and Right are
    #: what is inside one where the OCR review has words - the same
    #: relationship, one level up.
    #: What an edit-field mode holds: every printable key, so the
    #: character reaches the field, and the editing keys beside them.
    #: Held ONLY while a field is being typed into and given back the
    #: moment it is not - a reader still holding the alphabet in the next
    #: window is a machine that has stopped answering.
    TYPING_CHARACTERS = ('abcdefghijklmnopqrstuvwxyz0123456789'
                         "-=[];'\\,./`")

    TYPING_KEYS = ('space', 'backspace', 'delete', 'leftArrow',
                   'rightArrow', 'upArrow', 'downArrow', 'home', 'end',
                   'pageUp', 'pageDown', 'enter', 'tab')

    def _typing_gestures(self):
        wanted = {}
        for character in self.TYPING_CHARACTERS:
            wanted['kb:%s' % character] = 'appType'
            wanted['kb:shift+%s' % character] = 'appType'
        for name in self.TYPING_KEYS:
            wanted['kb:%s' % name] = 'appType'
            wanted['kb:control+%s' % name] = 'appType'
        # Escape is the way OUT, and is deliberately not relayed.
        wanted['kb:escape'] = 'appLeave'
        return wanted

    def _borrow_typing_keys(self, borrow=True):
        for gesture, script_name in self._typing_gestures().items():
            try:
                if borrow:
                    self.bindGesture(gesture, script_name)
                else:
                    self.removeGestureBinding(gesture)
            except Exception:                        # noqa: BLE001
                pass
        self._typing_bound = bool(borrow)

    def _keep_typing_keys_right(self):
        try:
            want = appReview.reviewing() and appReview.typing_mode()
        except Exception:                            # noqa: BLE001
            want = False
        if want != getattr(self, '_typing_bound', False):
            # The two sets overlap, so whichever is not wanted lets go
            # first or a key is left bound to the wrong script.
            if want:
                self._borrow_app_keys(False)
                self._borrow_typing_keys(True)
            else:
                self._borrow_typing_keys(False)
                self._app_bound = False
                self._keep_app_keys_right()

    @script(description=_('In a described application: type into the field'),
            category=CATEGORY)
    def script_appType(self, gesture):
        if not (appReview.reviewing() and appReview.typing_mode()):
            self._keep_typing_keys_right()
            gesture.send()
            return
        key = appReview.wire_key(
            getattr(gesture, 'mainKeyName', ''),
            getattr(gesture, 'modifierNames', None) or [])
        appReview.relay(key)

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
        # The numpad corners, as in every other walked list: the first and
        # the last control, and the end of what is inside them.
        'kb:numpad7': 'appUpLeft',
        'kb:numpad9': 'appUpRight',
        'kb:numpad1': 'appDownLeft',
        'kb:numpad3': 'appDownRight',
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
    #: The palette's keys - the virtual window's, minus everything that
    #: has no meaning in a list of commands. Held only while it is really
    #: up, and given back the moment it is not, which is the discipline
    #: every borrowed key in this add-on follows.
    PALETTE_KEYS = {
        'kb:upArrow': 'paletteUp',
        'kb:downArrow': 'paletteDown',
        'kb:home': 'paletteHome',
        'kb:end': 'paletteEnd',
        'kb:enter': 'paletteActivate',
        'kb:escape': 'paletteBack',
        # Left and Right by whichever layout is on (a character, the word
        # beside, the row beside), Shift the other way round, Control by
        # word - so the palette reads exactly like the virtual window.
        'kb:leftArrow': 'paletteCharLeft',
        'kb:rightArrow': 'paletteCharRight',
        'kb:shift+leftArrow': 'paletteShiftLeft',
        'kb:shift+rightArrow': 'paletteShiftRight',
        'kb:control+leftArrow': 'paletteWordLeft',
        'kb:control+rightArrow': 'paletteWordRight',
        # And the numpad as in the virtual window: the four corners of
        # the page (the start and end of the first row, of the last row),
        # and 4 / 6 the layout - one setting shared with the virtual
        # window, so a user who changed it there finds it changed here.
        'kb:numpad7': 'paletteUpLeft',
        'kb:numpad9': 'paletteUpRight',
        'kb:numpad1': 'paletteDownLeft',
        'kb:numpad3': 'paletteDownRight',
        'kb:numpad4': 'paletteLayoutBack',
        'kb:numpad6': 'paletteLayout',
    }

    def _borrow_palette_keys(self, borrow=True):
        for gesture, script_name in self.PALETTE_KEYS.items():
            try:
                if borrow:
                    self.bindGesture(gesture, script_name)
                else:
                    self.removeGestureBinding(gesture)
            except Exception:                        # noqa: BLE001
                pass
        self._palette_bound = bool(borrow)

    def _keep_palette_keys_right(self):
        try:
            want = palette.walking()
        except Exception:                            # noqa: BLE001
            want = False
        if want != getattr(self, '_palette_bound', False):
            self._borrow_palette_keys(want)
        self._keep_touch_right()

    # ------------------------------------------------------------ touch
    #: The trackpad's gestures, held while ANY walked list is up - the
    #: palette, the virtual window, the OCR review - and given back the
    #: moment none is. One script answers them all and asks
    #: :mod:`touchWalk` which list has them; the table of what each
    #: gesture does is there, in one place, with the finger counts.
    def _touch_gestures(self):
        from . import touchWalk
        return {'ts:%s' % action: 'walkTouch' for action in touchWalk.ACTIONS}

    def _keep_touch_right(self):
        try:
            from . import touchWalk
            want = bool(touchWalk.walker())
        except Exception:                            # noqa: BLE001
            want = False
        if want == getattr(self, '_touch_bound', False):
            return
        for gesture, script_name in self._touch_gestures().items():
            try:
                if want:
                    self.bindGesture(gesture, script_name)
                else:
                    self.removeGestureBinding(gesture)
            except Exception:                        # noqa: BLE001
                pass
        self._touch_bound = want

    @script(description=_('In a walked list: the trackpad - explore with a '
                          'finger, flick to move, more fingers for the '
                          'corners, the layout and the ends'),
            category=CATEGORY)
    def script_walkTouch(self, gesture):
        from . import touchWalk
        name = (getattr(gesture, 'identifiers', None) or [''])[0]
        handled, said = touchWalk.handle(
            touchWalk.action_of(name),
            getattr(gesture, 'x', None), getattr(gesture, 'y', None))
        if not handled:
            self._keep_touch_right()
            return
        # A gesture may have closed the list, or opened a menu inside it.
        self._keep_palette_keys_right()
        self._keep_virtual_keys_right()
        self._keep_ocr_keys_right()
        if said:
            dialogs.report(said)

    def _palette_key(self, gesture, act):
        if not palette.walking():
            self._keep_palette_keys_right()
            self._keep_typing_keys_right()
            gesture.send()
            return
        try:
            _ok, said = act()
        except Exception:                            # noqa: BLE001
            gesture.send()
            return
        # Running a command, or going back, changes whether these keys are
        # ours at all.
        self._keep_palette_keys_right()
        if said:
            dialogs.report(said)

    @script(description=_('In the application: the top left corner - the '
                          'first control'), category=CATEGORY)
    def script_appUpLeft(self, gesture):
        self._app_move(gesture, lambda: appReview.move_corner(-1, -1))

    @script(description=_('In the application: the top right corner - the '
                          'end of the first control'), category=CATEGORY)
    def script_appUpRight(self, gesture):
        self._app_move(gesture, lambda: appReview.move_corner(1, -1))

    @script(description=_('In the application: the bottom left corner - '
                          'the last control'), category=CATEGORY)
    def script_appDownLeft(self, gesture):
        self._app_move(gesture, lambda: appReview.move_corner(-1, 1))

    @script(description=_('In the application: the bottom right corner - '
                          'the end of the last control'), category=CATEGORY)
    def script_appDownRight(self, gesture):
        self._app_move(gesture, lambda: appReview.move_corner(1, 1))

    @script(description=_('In the screen review: the top left corner - the '
                          'start of the first line'), category=CATEGORY)
    def script_ocrUpLeft(self, gesture):
        self._ocr_move(gesture, lambda: ocrReview.move_corner(-1, -1))

    @script(description=_('In the screen review: the top right corner - the '
                          'end of the first line'), category=CATEGORY)
    def script_ocrUpRight(self, gesture):
        self._ocr_move(gesture, lambda: ocrReview.move_corner(1, -1))

    @script(description=_('In the screen review: the bottom left corner - '
                          'the start of the last line'), category=CATEGORY)
    def script_ocrDownLeft(self, gesture):
        self._ocr_move(gesture, lambda: ocrReview.move_corner(-1, 1))

    @script(description=_('In the screen review: the bottom right corner - '
                          'the end of the last line'), category=CATEGORY)
    def script_ocrDownRight(self, gesture):
        self._ocr_move(gesture, lambda: ocrReview.move_corner(1, 1))

    @script(description=_('In the command palette: the command above - or, '
                          'in the interaction layout, out of this row'),
            category=CATEGORY)
    def script_paletteUp(self, gesture):
        self._palette_key(gesture, lambda: palette.move(-1))

    @script(description=_('In the command palette: the command below - or, '
                          'in the interaction layout, into this row'),
            category=CATEGORY)
    def script_paletteDown(self, gesture):
        self._palette_key(gesture, lambda: palette.move(1))

    @script(description=_('In the command palette: the first command'),
            category=CATEGORY)
    def script_paletteHome(self, gesture):
        self._palette_key(gesture, lambda: palette.move_end(False))

    @script(description=_('In the command palette: the last command'),
            category=CATEGORY)
    def script_paletteEnd(self, gesture):
        self._palette_key(gesture, lambda: palette.move_end(True))

    @script(description=_('In the command palette: run this command'),
            category=CATEGORY)
    def script_paletteActivate(self, gesture):
        self._palette_key(gesture, palette.activate)


    def _palette_move(self, gesture, move):
        if not palette.walking():
            self._keep_palette_keys_right()
            gesture.send()
            return
        try:
            move()
        except Exception:                            # noqa: BLE001
            gesture.send()

    @script(description=_('In the palette: back through the row - a '
                          'character, the word beside, or the row beside, '
                          'by layout'), category=CATEGORY)
    def script_paletteCharLeft(self, gesture):
        self._palette_move(gesture, lambda: palette.move_across(-1))

    @script(description=_('In the palette: on through the row - a '
                          'character, the word beside, or the row beside, '
                          'by layout'), category=CATEGORY)
    def script_paletteCharRight(self, gesture):
        self._palette_move(gesture, lambda: palette.move_across(1))

    @script(description=_('In the palette: the other way through the row '
                          '- the word beside in the simple layout, a '
                          'character in the others'), category=CATEGORY)
    def script_paletteShiftLeft(self, gesture):
        self._palette_move(gesture, lambda: palette.move_across_shift(-1))

    @script(description=_('In the palette: the other way on through the '
                          'row - the word beside in the simple layout, a '
                          'character in the others'), category=CATEGORY)
    def script_paletteShiftRight(self, gesture):
        self._palette_move(gesture, lambda: palette.move_across_shift(1))

    @script(description=_('In the palette: the top left corner - the start '
                          'of the first row'), category=CATEGORY)
    def script_paletteUpLeft(self, gesture):
        self._palette_move(gesture, lambda: palette.move_corner(-1, -1))

    @script(description=_('In the palette: the top right corner - the end '
                          'of the first row'), category=CATEGORY)
    def script_paletteUpRight(self, gesture):
        self._palette_move(gesture, lambda: palette.move_corner(1, -1))

    @script(description=_('In the palette: the bottom left corner - the '
                          'start of the last row'), category=CATEGORY)
    def script_paletteDownLeft(self, gesture):
        self._palette_move(gesture, lambda: palette.move_corner(-1, 1))

    @script(description=_('In the palette: the bottom right corner - the '
                          'end of the last row'), category=CATEGORY)
    def script_paletteDownRight(self, gesture):
        self._palette_move(gesture, lambda: palette.move_corner(1, 1))

    @script(description=_('In the palette: the next layout - simple, '
                          'screen, interaction; shared with the virtual '
                          'window'), category=CATEGORY)
    def script_paletteLayout(self, gesture):
        self._palette_key(gesture, lambda: palette.layout_cycle(1))

    @script(description=_('In the palette: the previous layout - simple, '
                          'screen, interaction; shared with the virtual '
                          'window'), category=CATEGORY)
    def script_paletteLayoutBack(self, gesture):
        self._palette_key(gesture, lambda: palette.layout_cycle(-1))

    @script(description=_('In the palette: the word before, in this '
                          'command\'s name'), category=CATEGORY)
    def script_paletteWordLeft(self, gesture):
        self._palette_move(gesture, lambda: palette.move_word(-1))

    @script(description=_('In the palette: the word after, in this '
                          'command\'s name'), category=CATEGORY)
    def script_paletteWordRight(self, gesture):
        self._palette_move(gesture, lambda: palette.move_word(1))
    @script(description=_('In the command palette: back one level, or '
                          'close it'), category=CATEGORY)
    def script_paletteBack(self, gesture):
        self._palette_key(gesture, palette.back)

    #: How long the program is given to act on a key of its own before
    #: the virtual window is built again. Long enough for a folder to be
    #: read, short enough that the rebuild feels like part of the press.
    BACK_SETTLES_MS = 500

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
        'kb:backspace': 'virtualBack',
        'kb:f5': 'virtualRefresh',
        'kb:escape': 'virtualLeave',
        # By word with Control, by the control beside this one on the same
        # line with Shift - the plain Left/Right are already by character.
        'kb:control+leftArrow': 'virtualWordLeft',
        'kb:control+rightArrow': 'virtualWordRight',
        'kb:shift+leftArrow': 'virtualLineLeft',
        'kb:shift+rightArrow': 'virtualLineRight',
        # The numpad as the screen: the four diagonals go to the control
        # nearest each corner of the window, 5 clicks it, and 4 and 6 walk
        # the three layouts the arrows can follow - simple, screen,
        # interaction (see `virtualWindow.LAYOUTS`).
        'kb:numpad7': 'virtualUpLeft',
        'kb:numpad9': 'virtualUpRight',
        'kb:numpad1': 'virtualDownLeft',
        'kb:numpad3': 'virtualDownRight',
        'kb:numpad5': 'virtualClick',
        'kb:numpad4': 'virtualLayoutBack',
        'kb:numpad6': 'virtualLayout',
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
        # Both sets are let go, because either may be the one held.
        gestures = dict(self._virtual_gestures())
        if not borrow:
            gestures.update(self._virtual_typing_gestures())
        for gesture, script_name in gestures.items():
            try:
                if borrow:
                    self.bindGesture(gesture, script_name)
                else:
                    self.removeGestureBinding(gesture)
            except Exception:                        # noqa: BLE001
                pass

    def _virtual_typing_gestures(self):
        """Every key the edit-field mode holds.

        **All of them, and that is the point.** The mode is the virtual
        window's own: while it is on, the letters, the space and Enter go
        into the row the cursor is on, and the virtual window's own
        navigation is suspended. Holding only Escape - which is what this
        did first - gives the keys to whatever happens to be focused,
        which works over a real control and does nothing at all over a
        row read off a picture, where nothing is focused to receive them.
        """
        wanted = {}
        for character in self.TYPING_CHARACTERS:
            wanted['kb:%s' % character] = 'virtualType'
            wanted['kb:shift+%s' % character] = 'virtualType'
        for name in self.TYPING_KEYS:
            wanted['kb:%s' % name] = 'virtualType'
            wanted['kb:control+%s' % name] = 'virtualType'
            wanted['kb:shift+%s' % name] = 'virtualType'
        # Escape is the way out and is deliberately never typed.
        wanted['kb:escape'] = 'virtualLeave'
        return wanted

    @script(description=_('In the virtual window: type into the field'),
            category=CATEGORY)
    def script_virtualType(self, gesture):
        if not (virtualWindow.reviewing() and virtualWindow.typing_mode()):
            self._keep_virtual_keys_right()
            gesture.send()
            return
        # **With the modifiers**, or Control and an arrow is a plain
        # arrow and Control and Backspace takes one character.
        _ok, said = virtualWindow.type_key(
            '+'.join(list(getattr(gesture, 'modifierNames', None) or [])
                     + [str(getattr(gesture, 'mainKeyName', '') or '')]),
            gesture.send)
        if said:
            dialogs.report(said)

    def _virtual_wants(self):
        """Which keys the virtual window should be holding right now.

        ``''`` none, ``'all'`` the whole set, ``'escape'`` that key alone
        - which is the edit-field mode: the user pressed Enter on a field
        and every letter, every arrow and Enter itself now belong to the
        program they are typing into. Holding one key rather than none is
        the whole of what makes the mode leavable.
        """
        try:
            if not virtualWindow.reviewing():
                return ''
            return 'typing' if virtualWindow.typing_mode() else 'all'
        except Exception:                            # noqa: BLE001
            return ''

    def _keep_virtual_keys_right(self):
        want = self._virtual_wants()
        have = getattr(self, '_virtual_bound', '')
        self._keep_touch_right()
        if want == have:
            return
        # Let go of whatever is held before taking anything, or the two
        # sets overlap and a key is left bound to the wrong script.
        if have:
            self._borrow_virtual_keys(False)
        if want == 'all':
            self._borrow_virtual_keys(True)
        elif want == 'typing':
            for gesture, script_name in \
                    self._virtual_typing_gestures().items():
                try:
                    self.bindGesture(gesture, script_name)
                except Exception:                    # noqa: BLE001
                    pass
        self._virtual_bound = want

    #: A widget's keys. Fewer than the others because a widget answers
    #: one element at a time and nothing answers how many there are, so
    #: there is no page key, no Home and no End to offer honestly.
    WIDGET_KEYS = {
        'kb:upArrow': 'widgetUp',
        'kb:downArrow': 'widgetDown',
        'kb:leftArrow': 'widgetLeft',
        'kb:rightArrow': 'widgetRight',
        'kb:enter': 'widgetPress',
        'kb:escape': 'widgetLeave',
    }

    def _borrow_widget_keys(self, borrow=True):
        for gesture, script_name in self.WIDGET_KEYS.items():
            try:
                if borrow:
                    self.bindGesture(gesture, script_name)
                else:
                    self.removeGestureBinding(gesture)
            except Exception:                        # noqa: BLE001
                pass
        self._widget_bound = bool(borrow)

    def _keep_widget_keys_right(self):
        try:
            want = widgetReview.reviewing()
        except Exception:                            # noqa: BLE001
            want = False
        if want != getattr(self, '_widget_bound', False):
            self._borrow_widget_keys(want)

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
        self._keep_touch_right()

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

        Everything except a GAME. A game keeps its own keys - its menu is
        what the arrows are for, and the reader's job there is to say what
        has become highlighted, not to run a second cursor.

        **It asked for `MODE_APPLICATION` alone, and that is not the mode
        most windows are read in.** Windows' own recogniser reads them
        first - that is the tier order - and it leaves the watch in
        `MODE_LOCAL`, where the cursor is built exactly the same way by
        `smart.take_local`. So the mode change was announced, the
        controls were there to walk, and not one key was bound to walk
        them with: "Native TCE cursor on, and Tab does nothing" - which
        is a feature that reports success and cannot be used, the shape
        this add-on keeps paying for.
        """
        try:
            mode = surface.report().get('mode')
            want = bool(smart.active()) and mode != surface.MODE_GAME
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
        # **Walked, not a menu.** A `wx.Menu` takes the foreground, closes
        # when anything else happens, and says each entry once; every
        # other list in this add-on is walked. The real menu is still
        # there - `commands.titan_menu_as_a_menu` - for somebody who
        # wants the platform's own.
        commands.titan_menu()

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

    # ------------------------------------------------- a Titan widget
    def _widget_move(self, gesture, direction):
        if not widgetReview.reviewing():
            self._keep_widget_keys_right()
            gesture.send()
            return
        widgetReview.move(direction)

    @script(description=_('In a widget: up'), category=CATEGORY)
    def script_widgetUp(self, gesture):
        self._widget_move(gesture, 'up')

    @script(description=_('In a widget: down'), category=CATEGORY)
    def script_widgetDown(self, gesture):
        self._widget_move(gesture, 'down')

    @script(description=_('In a widget: left'), category=CATEGORY)
    def script_widgetLeft(self, gesture):
        self._widget_move(gesture, 'left')

    @script(description=_('In a widget: right'), category=CATEGORY)
    def script_widgetRight(self, gesture):
        self._widget_move(gesture, 'right')

    @script(description=_('In a widget: press what you are on'),
            category=CATEGORY)
    def script_widgetPress(self, gesture):
        if not widgetReview.reviewing():
            self._keep_widget_keys_right()
            gesture.send()
            return
        widgetReview.press()

    @script(description=_('Leave the widget'), category=CATEGORY)
    def script_widgetLeave(self, gesture):
        if not widgetReview.reviewing():
            self._keep_widget_keys_right()
            gesture.send()
            return
        _on, said = widgetReview.stop()
        self._keep_widget_keys_right()
        dialogs.report(said)

    @script(
        # Translators: an NVDA command.
        description=_('Titan widgets: choose one and walk it'),
        category=CATEGORY)
    def script_widgets(self, gesture):
        commands.walk_a_widget()
        self._keep_widget_keys_right()

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

    @script(description=_('In the virtual window: back - a character of '
                          'this control\'s text, the control beside it, or '
                          'the control before it at this level, by layout'),
            category=CATEGORY)
    def script_virtualLeft(self, gesture):
        self._virtual_move(gesture, lambda: virtualWindow.move_across(-1))

    @script(description=_('In the virtual window: on - a character of this '
                          'control\'s text, the control beside it, or the '
                          'control after it at this level, by layout'),
            category=CATEGORY)
    def script_virtualRight(self, gesture):
        self._virtual_move(gesture, lambda: virtualWindow.move_across(1))

    @script(description=_('In the virtual window: the word before, in this '
                          'control\'s text'), category=CATEGORY)
    def script_virtualWordLeft(self, gesture):
        self._virtual_move(gesture, lambda: virtualWindow.move_word(-1))

    @script(description=_('In the virtual window: the word after, in this '
                          'control\'s text'), category=CATEGORY)
    def script_virtualWordRight(self, gesture):
        self._virtual_move(gesture, lambda: virtualWindow.move_word(1))

    @script(description=_('In the virtual window: the other way back - the '
                          'control beside this one in the simple layout, a '
                          'character of its text in the others'),
            category=CATEGORY)
    def script_virtualLineLeft(self, gesture):
        self._virtual_move(gesture,
                           lambda: virtualWindow.move_across_shift(-1))

    @script(description=_('In the virtual window: the other way on - the '
                          'control beside this one in the simple layout, a '
                          'character of its text in the others'),
            category=CATEGORY)
    def script_virtualLineRight(self, gesture):
        self._virtual_move(gesture,
                           lambda: virtualWindow.move_across_shift(1))

    @script(description=_('In the virtual window: the top left corner of '
                          'the window'), category=CATEGORY)
    def script_virtualUpLeft(self, gesture):
        self._virtual_move(gesture, lambda: virtualWindow.move_diagonal(-1, -1))

    @script(description=_('In the virtual window: the top right corner of '
                          'the window'), category=CATEGORY)
    def script_virtualUpRight(self, gesture):
        self._virtual_move(gesture, lambda: virtualWindow.move_diagonal(1, -1))

    @script(description=_('In the virtual window: the bottom left corner of '
                          'the window'), category=CATEGORY)
    def script_virtualDownLeft(self, gesture):
        self._virtual_move(gesture, lambda: virtualWindow.move_diagonal(-1, 1))

    @script(description=_('In the virtual window: the bottom right corner '
                          'of the window'), category=CATEGORY)
    def script_virtualDownRight(self, gesture):
        self._virtual_move(gesture, lambda: virtualWindow.move_diagonal(1, 1))

    @script(description=_('In the virtual window: click the control with the '
                          'mouse - twice quickly for a double click'),
            category=CATEGORY)
    def script_virtualClick(self, gesture):
        if not virtualWindow.reviewing():
            self._keep_virtual_keys_right()
            gesture.send()
            return
        _ok, said = virtualWindow.click_mouse()
        if said:
            dialogs.report(said)

    def _virtual_layout(self, gesture, delta):
        if not virtualWindow.reviewing():
            self._keep_virtual_keys_right()
            gesture.send()
            return
        _ok, said = virtualWindow.layout_cycle(delta)
        if said:
            dialogs.report(said)

    @script(description=_('In the virtual window: the next layout the '
                          'arrows follow - simple, screen, interaction'),
            category=CATEGORY)
    def script_virtualLayout(self, gesture):
        self._virtual_layout(gesture, 1)

    @script(description=_('In the virtual window: the previous layout the '
                          'arrows follow - simple, screen, interaction'),
            category=CATEGORY)
    def script_virtualLayoutBack(self, gesture):
        self._virtual_layout(gesture, -1)

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
        # Enter on a field hands the keyboard over, so which keys this
        # holds has just changed.
        self._keep_virtual_keys_right()
        if said:
            dialogs.report(said)

    @script(description=_('In the virtual window: the program\'s own '
                          'Backspace - up one folder - and then build the '
                          'window again'),
            category=CATEGORY)
    def script_virtualBack(self, gesture):
        if not virtualWindow.reviewing():
            self._keep_virtual_keys_right()
            gesture.send()
            return
        # **The key is the program's; the rebuild is ours.** Backspace in
        # a file manager goes up a folder, and it always reached the
        # program perfectly well - what did not happen is the virtual
        # window noticing, so the user was walking the folder they had
        # just left. This is the same fault the Elten renderer had: what
        # counts as "the screen changed" decides whether anything the
        # user does is ever seen.
        gesture.send()
        try:
            import wx
            wx.CallLater(self.BACK_SETTLES_MS,
                         lambda: virtualWindow.refresh(keep_place=False))
        except Exception:                            # noqa: BLE001
            virtualWindow.refresh(keep_place=False)

    @script(description=_('In the virtual window: build it again'),
            category=CATEGORY)
    def script_virtualRefresh(self, gesture):
        if not virtualWindow.reviewing():
            self._keep_virtual_keys_right()
            gesture.send()
            return
        _ok, said = virtualWindow.refresh()
        dialogs.report(said)

    @script(description=_('Leave the virtual window, or the field being '
                          'typed into'), category=CATEGORY)
    def script_virtualLeave(self, gesture):
        if not virtualWindow.reviewing():
            self._keep_virtual_keys_right()
            gesture.send()
            return
        # **One level at a time.** Escape in a field comes back to the
        # controls; Escape in the controls leaves the window. Closing the
        # whole thing from inside a field would make one keystroke undo
        # two decisions.
        if virtualWindow.typing_mode():
            _ok, said = virtualWindow.leave_typing()
            self._keep_virtual_keys_right()
            dialogs.report(said)
            return
        if virtualWindow.in_a_menu():
            # Out of the menu, back to the window's own controls - one
            # level at a time, as everywhere else here.
            _ok, said = virtualWindow.close_menu()
            if said:
                dialogs.report(said)
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
        description=_('TCE applications: open one and walk it with the '
                      'arrow keys'),
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
        # Enter on a field hands the keyboard to it, so which keys this
        # holds has just changed.
        self._keep_typing_keys_right()
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
        # **One level at a time.** Escape in a field comes back to the
        # controls, Escape in a menu comes back to the
        # controls; Escape in the controls leaves the review. Closing the
        # whole thing from inside a menu would make one keystroke undo two
        # decisions - the same rule the virtual window's field mode
        # follows.
        if appReview.reviewing() and appReview.typing_mode():
            _ok, said = appReview.leave_typing()
            self._keep_typing_keys_right()
            if said:
                dialogs.report(said)
            return
        if appReview.reviewing() and appReview.in_a_menu():
            _ok, said = appReview.close_menu()
            if said:
                dialogs.report(said)
            return
        if not appReview.reviewing():
            self._keep_app_keys_right()
            gesture.send()
            return
        _on, said = appReview.stop()
        self._keep_app_keys_right()
        dialogs.report(said)

    @script(
        # Translators: an NVDA command.
        description=_('TCE applications: show it as real controls '
                      'instead'),
        category=CATEGORY)
    def script_appAsWindow(self, gesture):
        commands.application_as_a_window()
        self._keep_app_keys_right()

    @script(
        # Translators: an NVDA command.
        description=_('TCE applications: close it'),
        category=CATEGORY)
    def script_appClose(self, gesture):
        commands.close_application()
        self._keep_app_keys_right()

    @script(
        # Translators: an NVDA command.
        description=_('Titan: what it can start, its settings, what '
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

    #: The keys a layer borrows while it is open. Every printable key the
    #: layers use, plus the two that ask for help and the one that leaves -
    #: bound only while a layer is really open, and taken back the moment
    #: it is not, which is the same discipline the drawn-window cursor and
    #: the terminal review already follow. A reader still holding a letter
    #: in the next window is a machine that has stopped answering.
    @property
    def LAYER_KEYS(self):
        wanted = {'kb:escape'}
        for name in layers.names():
            for key in layers.keys_of(name):
                wanted.add('kb:%s' % key)
        for key in layers.HELP_KEYS:
            wanted.add('kb:%s' % key)
        return wanted

    def _borrow_layer_keys(self, borrow=True):
        for gesture in self.LAYER_KEYS:
            try:
                if borrow:
                    self.bindGesture(gesture, 'titanLayerKey')
                else:
                    self.removeGestureBinding(gesture)
            except Exception:                        # noqa: BLE001
                pass
        self._layer_bound = bool(borrow)

    def _keep_layer_keys_right(self):
        """A layer that has timed out has let its keys go.

        Asked rather than remembered, because the layer closes itself
        after a few seconds and nothing runs when it does - a layer still
        holding the alphabet is exactly the fault this bounds.
        """
        try:
            want = bool(layers.open_layer())
        except Exception:                            # noqa: BLE001
            want = False
        if want != getattr(self, '_layer_bound', False):
            self._borrow_layer_keys(want)

    def _open_layer(self, name):
        ok, said = layers.enter(name)
        if not ok:
            return
        self._borrow_layer_keys(True)
        try:
            from . import dialogs
            dialogs.report(said)
        except Exception:                            # noqa: BLE001
            pass
        # And let go by itself, so a layer entered by accident is gone
        # before the user types anything they meant for the program.
        try:
            import core
            core.callLater(int(layers.SECONDS * 1000) + 100,
                           self._keep_layer_keys_right)
        except Exception:                            # noqa: BLE001
            pass

    @script(
        # Translators: an NVDA command. It is bound to the layers' own
        # letters while a layer is open and to nothing the rest of the
        # time.
        description=_('In an open command layer: the key that chooses'),
        category=CATEGORY)
    def script_titanLayerKey(self, gesture):
        """One key, inside whatever layer is open."""
        from . import dialogs
        pressed = ''
        try:
            pressed = str(getattr(gesture, 'mainKeyName', '') or '')
        except Exception:                            # noqa: BLE001
            pressed = ''
        if pressed == 'escape':
            layers.leave()
            self._keep_layer_keys_right()
            return
        what, value = layers.chose(pressed)
        self._keep_layer_keys_right()
        if what == 'closed':
            # The layer went while the key was in the air: the key is the
            # program's, not ours.
            try:
                gesture.send()
            except Exception:                        # noqa: BLE001
                pass
            return
        if what == 'help':
            dialogs.browse('\n'.join(layers.help_for(value)),
                           layers.label(value))
            return
        if what == 'unknown':
            dialogs.report(layers.unknown_sentence(value))
            return
        run = getattr(commands, value, None)
        if run is None:
            return
        try:
            run()
        except Exception as error:                   # noqa: BLE001
            if compat.log is not None:
                compat.log.error('Titan layer: %s: %s'
                                 % (type(error).__name__, error))

    @script(
        # Translators: an NVDA command.
        description=_('Everything you may decide about the control you are '
                      'on: what it is called, what it is said to be, what '
                      'is added after it, its voice, or never announcing '
                      'it'),
        category=CATEGORY)   # no gesture: `c` in the reading layer
    def script_titanCustomise(self, gesture):
        commands.customise_control()

    @script(
        # Translators: an NVDA command.
        description=_('Opens the command palette: one key opens a layer, '
                      'the next key chooses in it, and ? says what is in '
                      'it'),
        category=CATEGORY,
        gestures=['kb:NVDA+shift+space', 'kb:NVDA+`'])
    def script_titanPalette(self, gesture):
        if palette.walking():
            # Pressed again while it is up: that is "close it", the same
            # answer every other mode in this add-on gives its own key.
            _ok, said = palette.stop()
            self._keep_palette_keys_right()
            self._keep_typing_keys_right()
            dialogs.report(said)
            return
        commands.command_palette(self._open_layer)
        self._keep_palette_keys_right()

    @script(
        # Translators: an NVDA command.
        description=_('Checks whether the reader module for this program '
                      'really does anything to it, and names the rules '
                      'that match nothing'),
        category=CATEGORY)
    def script_titanCheckModule(self, gesture):
        commands.check_module()

    @script(
        # Translators: an NVDA command.
        description=_('Says what this program is written in - the toolkit '
                      'it runs on, and what that means for reading it'),
        category=CATEGORY)
    def script_titanWrittenIn(self, gesture):
        commands.what_is_this_written_in()

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
