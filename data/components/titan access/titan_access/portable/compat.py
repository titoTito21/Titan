# -*- coding: utf-8 -*-
"""NVDA's own services, answered by Titan Access's.

The shared modules are byte-identical in both trees, so each of them says
``from . import compat`` and reads ``compat.speech``, ``compat.tones``,
``compat.ui`` and the rest - the add-on's spelling, because the add-on is
where they are written. Inside NVDA that reaches NVDA. This is the other
end: the same names, answering through Titan Access's own speech, sounds
and logging.

**Every name here answers None where there is nothing behind it**, which
is exactly what the add-on's own `compat` does and the property the shared
modules are written against: each of them checks before it uses, and
degrades to saying less rather than to an exception. That is what makes
one file work in a reader with NVDA under it and one without.

Nothing here is a pretence. A name that Titan Access has no equivalent for
- NVDA's speech commands, its braille handler, its input core - answers
None and is recorded in :func:`missing`, so "why is that quiet in Titan
Access" has an answer rather than a shrug.
"""

import threading

_LOCK = threading.RLock()

#: What was asked for and is not here. Read by a check, and by anybody
#: wondering why a shared module says less on this side.
_missing = {}


def _note(name, why):
    with _LOCK:
        _missing[name] = why
    return None


def missing():
    """{name: why} - what a shared module asked for and did not get."""
    with _LOCK:
        return dict(_missing)


# --------------------------------------------------------------------------- #
# Speech
# --------------------------------------------------------------------------- #
class _Speech(object):
    """Enough of NVDA's ``speech`` for the shared modules.

    They use exactly two things - say this, and stop - and both go to
    Titan Access's own adapter, which is the queue everything else in this
    reader speaks through. Speaking around it would be a second voice
    talking over the first.
    """

    def speakMessage(self, text):
        return self.speakText(text)

    def speak(self, sequence, **_kw):
        """NVDA's ``speech.speak(sequence)``: the words of a sequence, said.

        A sequence is strings with speech commands between them (a pitch,
        a rate, a break); the smart OCR cursor hands one over. The commands
        are what this adapter cannot carry, so the strings are said as one
        line and nothing is dropped - every word, no tone.
        """
        if isinstance(sequence, str):
            return self.speakText(sequence)
        words = []
        try:
            for item in sequence or ():
                if isinstance(item, str) and item.strip():
                    words.append(item.strip())
        except TypeError:
            return False
        if not words:
            return False
        return self.speakText(', '.join(words))

    def speakText(self, text, **_kw):
        try:
            from .. import speech_adapter
            speech_adapter.speak(str(text or ''))
            return True
        except Exception:                            # noqa: BLE001
            return False

    def cancelSpeech(self):
        try:
            from .. import speech_adapter
            speech_adapter.stop()
            return True
        except Exception:                            # noqa: BLE001
            return False

    # **Titan Access's own two**, which NVDA's `speech` has not got: a
    # whole utterance in a voice CLASS, and one with a profile as it
    # stands on a dialog. `dialogs.report` and `classes.speak_sample` ask
    # for them by name and fall back where they are absent.
    def speak_in_class(self, text, tag, interrupt=False):
        try:
            from .. import speech_adapter
            return bool(speech_adapter.speak_in_class(str(text or ''), tag,
                                                      interrupt=interrupt))
        except Exception:                            # noqa: BLE001
            return False

    def speak_with(self, profile, text, interrupt=True):
        try:
            from .. import speech_adapter
            return bool(speech_adapter.speak_with(profile, str(text or ''),
                                                  interrupt=interrupt))
        except Exception:                            # noqa: BLE001
            return False


class _Ui(object):
    """NVDA's ``ui.message``: say one thing, now."""

    def message(self, text):
        return _Speech().speakText(text)

    def browseableMessage(self, text, title=None, isHtml=False):
        return _Speech().speakText(text)


class _Tones(object):
    """NVDA's ``tones.beep``. Titan has a mixer; a tone is a tone.

    **It reached nothing.** `play_tone` is a METHOD of `SoundManager` -
    the instance the running engine holds as `engine.sound` - and this
    asked the `sound_manager` MODULE for a function of that name, found
    none, and answered False. Every row tone of the palette, a message and
    the virtual window, and every beep a shared module asked for, was
    silent in Titan Access while perfect in NVDA. The engine's own manager
    plays it now; NVDA's ``left``/``right`` volumes (0..100) become the
    pan the mixer takes.
    """

    def beep(self, hz, length, left=50, right=50):
        manager = self._manager()
        if manager is None:
            return False
        try:
            left_v = max(0.0, min(100.0, float(left)))
            right_v = max(0.0, min(100.0, float(right)))
            total = left_v + right_v
            pan = 0.0 if total <= 0 else (right_v - left_v) / total
            gain = 0.45 * (max(left_v, right_v) / 100.0) if total else 0.0
            manager.play_tone(float(hz), int(length), pan=pan,
                              gain=max(0.05, gain))
            return True
        except Exception:                            # noqa: BLE001
            return False

    @staticmethod
    def _manager():
        """The running engine's sound manager, or one of our own."""
        try:
            from titan_access.engine import TitanAccessEngine
            engine = TitanAccessEngine.instance
            if engine is not None and getattr(engine, 'sound', None) is not None:
                return engine.sound
        except Exception:                            # noqa: BLE001
            pass
        try:
            from titan_access import sound_manager
            import os
            spare = getattr(sound_manager, '_SPARE', None)
            if spare is None:
                sfx = os.path.join(os.path.dirname(os.path.dirname(
                    os.path.abspath(sound_manager.__file__))), 'sfx')
                spare = sound_manager.SoundManager(sfx)
                sound_manager._SPARE = spare
            return spare
        except Exception:                            # noqa: BLE001
            return None


class _Log(object):
    """NVDA's ``logHandler.log``, into Titan's own logging."""

    def _write(self, level, message):
        try:
            import logging
            logging.getLogger('TitanAccess').log(level, str(message))
        except Exception:                            # noqa: BLE001
            pass

    def info(self, message, **_kw):
        import logging
        self._write(logging.INFO, message)

    def debug(self, message, **_kw):
        import logging
        self._write(logging.DEBUG, message)

    def warning(self, message, **_kw):
        import logging
        self._write(logging.WARNING, message)

    def error(self, message, **_kw):
        import logging
        self._write(logging.ERROR, message)

    def exception(self, message, **_kw):
        import logging
        self._write(logging.ERROR, message)


class _QueueHandler(object):
    """NVDA's ``queueHandler``, which is how a worker asks the reader's
    own thread to do something.

    Titan Access is a Titan component and Titan's thread is wx's, so this
    is `wx.CallAfter` - the same guarantee, through the same mechanism
    Titan's own action layer uses.
    """

    eventQueue = 'eventQueue'

    def queueFunction(self, _queue, function, *args, **kwargs):
        try:
            import wx
            wx.CallAfter(function, *args, **kwargs)
            return True
        except Exception:                            # noqa: BLE001
            try:
                function(*args, **kwargs)
                return True
            except Exception:                        # noqa: BLE001
                return False


class _Api(object):
    """NVDA's ``api``: what has the focus, and what is in front.

    **Answered by THIS reader's focus, through the seam.** The shared
    commands - where am I, label this control, describe it, customise
    it, the managers' own pages - all ask ``compat.api.getFocusObject()``
    and refuse with "the reader is not reporting a focus" when it answers
    None. It used to look for a focus on the `engine` MODULE (attributes
    it has never had; the running engine is an instance), so in Titan
    Access every one of those commands refused, every time, whatever the
    user was on. `readerApi.hooks` is the engine's own answer - the
    control it last announced - installed by `nvda_shape.Hooks`, which is
    also what the markers, monitors and procedures already use.
    """

    @staticmethod
    def _hooks():
        try:
            from . import readerApi
            return readerApi.hooks
        except Exception:                            # noqa: BLE001
            return None

    def getFocusObject(self):
        hooks = self._hooks()
        if hooks is not None:
            try:
                found = hooks.focus()
                if found is not None:
                    return found
            except Exception:                        # noqa: BLE001
                pass
        return None

    def getNavigatorObject(self):
        """This reader has no navigator apart from its focus."""
        return self.getFocusObject()

    def getForegroundObject(self):
        hooks = self._hooks()
        if hooks is not None:
            try:
                found = hooks.foreground()
                if found is not None:
                    return found
            except Exception:                        # noqa: BLE001
                pass
        return self.getFocusObject()

    def getDesktopObject(self):
        return None

    def getMainWindowHandle(self):
        """Titan's own main window, which is what ``gui.mainFrame`` is."""
        try:
            frame = gui.mainFrame
            return int(frame.GetHandle()) if frame is not None else 0
        except Exception:                            # noqa: BLE001
            return 0


class _Gui(object):
    """NVDA's ``gui``, answered with Titan's own window.

    The shared modules put their dialogs and their menus on
    ``compat.gui.mainFrame`` and wrap a popup in ``prePopup`` /
    ``postPopup``, which is how NVDA hands a window the foreground and
    takes it back. Titan has a main window of its own and wx already gives
    a dialog parented to it the foreground, so the two calls are honestly
    nothing here rather than an imitation of NVDA's.
    """

    @property
    def mainFrame(self):
        try:
            import wx
        except Exception:                            # noqa: BLE001
            return None
        try:
            app = wx.GetApp()
        except Exception:                            # noqa: BLE001
            return None
        if app is None:
            return None
        try:
            found = app.GetTopWindow()
        except Exception:                            # noqa: BLE001
            return None
        # A window wx has already destroyed answers every attribute with a
        # RuntimeError from inside its own event loop, where nothing
        # catches it - so it is not somewhere to put a menu.
        try:
            if found is None or not bool(found):
                return None
        except Exception:                            # noqa: BLE001
            return None
        # **The calls are made ON THE FRAME.** The shared dialogs say
        # ``gui.mainFrame.prePopup()`` - NVDA's MainFrame has the method -
        # and a plain wx.Frame has not, so every question the shared
        # modules asked here (`dialogs.confirm`, `choose`, `ask_text`,
        # `customise`) raised `AttributeError` inside a `wx.CallAfter`,
        # where nothing catches it: no dialog, nothing said. Measured:
        # "read this window as a picture?" never appeared, and a new
        # speech scheme could not be named. The two are given to the
        # frame, as the nothing they honestly are here.
        for name in ('prePopup', 'postPopup'):
            if not hasattr(found, name):
                try:
                    setattr(found, name, _no_popup)
                except Exception:                    # noqa: BLE001
                    pass
        return found

    def prePopup(self):
        return None

    def postPopup(self):
        return None


def _no_popup():
    """What NVDA's ``prePopup`` / ``postPopup`` are here: nothing. wx
    gives a dialog parented to Titan's window the foreground itself."""
    return None


speech = _Speech()
ui = _Ui()
gui = _Gui()
tones = _Tones()
log = _Log()
queueHandler = _QueueHandler()
api = _Api()

#: Windows' own wave player. Titan has a mixer of its own and the shared
#: modules fall back to it, so this is deliberately absent rather than
#: half-answered: a `play` that silently does nothing is worse than one
#: that says it cannot.
nvwave = _note('nvwave', 'Titan plays its own sounds through its mixer')
displayModel = _note('displayModel', 'the drawn text of a window is read by Windows OCR here')

#: NVDA's own, with no equivalent here. Each is recorded rather than being
#: quietly None, so a shared module that says less on this side can be
#: asked why.
speechCommands = _note('speechCommands', 'NVDA speech commands')
speechExtensions = _note('speechExtensions', "NVDA's speech filter")
synthDriverHandler = _note('synthDriverHandler', "NVDA's synthesizers")
braille = _note('braille', "NVDA's braille handler")
config = _note('config', "NVDA's configuration")
controlTypes = _note('controlTypes', "NVDA's role table")
textInfos = _note('textInfos', "NVDA's text infos")
inputCore = _note('inputCore', "NVDA's input core")
KeyboardInputGesture = _note('KeyboardInputGesture', "NVDA's key gestures")

PitchCommand = None
RateCommand = None
VolumeCommand = None
BeepCommand = None
BreakCommand = None
IndexCommand = None
CallbackCommand = None
LangChangeCommand = None
EndUtteranceCommand = None
CharacterModeCommand = None


def report():
    """What this shim really answers, for a check that can be run."""
    return {'speech': speech is not None, 'ui': ui is not None,
            'tones': tones is not None, 'log': log is not None,
            'queueHandler': queueHandler is not None,
            'api': api is not None, 'missing': missing()}
