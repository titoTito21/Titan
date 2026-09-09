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
from . import panner
from . import settingsPanel
from . import smart
from . import states
from . import surface
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
            if self._smart_bound:
                self._borrow_keys(False)
        except Exception:                            # noqa: BLE001
            pass
        for leave in (states.stop, trackpad.stop, surface.stop_now):
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

    def _borrow_keys(self, borrow=True):
        """Take the navigation keys while a drawn window is being read.

        **Bound only while it is真 needed and given straight back.** A
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
        description=_('Opens the voice classes: what each kind of thing '
                      'sounds like'),
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
