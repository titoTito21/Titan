# -*- coding: utf-8 -*-
"""What the application SAYS, said where the user is.

Every one of Titan's applications announces what it has just done -
"Note saved!", "Folder created!", "Note deleted!", "Settings saved!" -
and every one of them reaches speech the same way::

    try:
        from src.titan_core.tce_speech import speak as _tce_speak
    except ImportError:
        import accessible_output3.outputs.auto as _ao3
        _speaker = _ao3.Auto()

Left alone under this shim, both halves of that are wrong in the same two
ways, and together they are the whole of the reported "saving a note says
Titan is working, does nothing, and only much later does TITAN say the
note was saved":

- **It is spoken in the wrong place.** The application is a subprocess of
  Titan's, and the person it is talking to is in Elten - possibly on
  another machine. An announcement made through a TTS engine here is an
  announcement the renderer never hears about and the user, sitting where
  the interface is, is not told.
- **It is spoken at ruinous cost, on the loop's own thread.**
  `tce_speech.speak` builds a whole `StereoSpeech` on its first call -
  the SAPI voices enumerated over COM, every Titan TTS engine loaded, the
  speech subprocess bridge probed with a `subprocess.run` - and does it
  INSIDE the subprocess, from the button handler. The shim sends the
  screen when it is about to wait, so all of that is time in which the
  interface hears nothing at all: the client waits out its whole patience
  and says the application has not answered. And because every one of
  these announcements is the FIRST speech the application makes, every
  one of them pays the full price - which is exactly why only the actions
  that announce something were slow.

So the two doorways are answered here instead, and what the application
says becomes one line on the wire (`said`). It costs microseconds, it
cannot block, and the sentence arrives where the interface is.

The boundary is deliberately these two NAMES rather than "anything that
might make a noise". Each application's SAPI / `say` / `spd-say` fallback
is reached only when both of these are missing, and answering both means
they never are - so there is nothing left to guess at.
"""

import sys
import types


def install(shim):
    """Answer the speech doorways a TCE application knows. Idempotent."""
    for finder in sys.meta_path:
        if getattr(finder, '_titan_speech', False):
            return
    sys.meta_path.insert(0, _Finder(shim))


#: What is claimed, and nothing else. `src.titan_core.tce_speech` is the
#: leaf only: `src` and `src.titan_core` are real packages the application
#: may want other things out of, and claiming a package would take those
#: away as well.
def _ours(name):
    if name == 'src.titan_core.tce_speech':
        return True
    return name == 'accessible_output3' or name.startswith('accessible_output3.')


class _Finder(object):
    _titan_speech = True

    def __init__(self, shim):
        self.shim = shim

    def find_module(self, name, path=None):
        return self if _ours(name) else None

    def load_module(self, name):
        if name in sys.modules:
            return sys.modules[name]
        module = _build(name, self.shim)
        sys.modules[name] = module
        return module

    def find_spec(self, name, path=None, target=None):
        if not _ours(name):
            return None
        import importlib.machinery
        return importlib.machinery.ModuleSpec(name, _Loader(self.shim))


class _Loader(object):
    def __init__(self, shim):
        self.shim = shim

    def create_module(self, spec):
        return _build(spec.name, self.shim)

    def exec_module(self, module):
        return None


def _build(name, shim):
    module = types.ModuleType(name)
    module.__path__ = []
    module.__package__ = name
    if name == 'src.titan_core.tce_speech':
        _fill_tce_speech(module, shim)
    elif name.startswith('accessible_output3'):
        _fill_ao3(module, shim)
    return module


# --------------------------------------------------------------------- said
def _say(shim, text, position=0.0, pitch=0, interrupt=True):
    """One thing the application said, put on the wire.

    Empty is not said: an application clearing an announcement by speaking
    nothing would otherwise be a blank line the renderer reads out.
    """
    text = '' if text is None else str(text).strip()
    if not text:
        return
    try:
        shim.RUNTIME.say('said', text=text, position=float(position or 0.0),
                         pitch=int(pitch or 0), interrupt=bool(interrupt))
    except Exception:
        pass


def _fill_tce_speech(module, shim):
    """`src.titan_core.tce_speech`, as far as an application uses it.

    Everything that SETS something is remembered and answered rather than
    acted on: which voice, rate and pitch the words come out in is the
    business of whoever is rendering the interface, and an application
    reaching in to change them here would be changing a machine it is not
    speaking on. Every one of them still answers, because an application
    reads what it set back.
    """
    state = {'rate': 0, 'volume': 100, 'pitch': 0, 'engine': '', 'voice': 0,
             'config': {}}

    def speak(text, position=0.0, interrupt=True, pitch_offset=0):
        _say(shim, text, position, pitch_offset, interrupt)

    def speak_async(text, position=0.0, interrupt=True, pitch_offset=0):
        _say(shim, text, position, pitch_offset, interrupt)

    def stop():
        return None

    def _setter(key):
        def set_it(value):
            state[key] = value
            return True
        return set_it

    module.speak = speak
    module.speak_async = speak_async
    module.stop = stop
    module.set_rate = _setter('rate')
    module.set_volume = _setter('volume')
    module.set_pitch = _setter('pitch')
    module.set_engine = _setter('engine')
    module.set_voice = _setter('voice')
    module.get_available_engines = lambda: []
    module.get_available_voices = lambda: []
    module.set_engine_config = (
        lambda engine_id, key, value: state['config'].setdefault(
            engine_id, {}).__setitem__(key, value))
    module.get_engine_config = (
        lambda engine_id, key, default=None:
        state['config'].get(engine_id, {}).get(key, default))
    module.is_stereo_available = lambda: True
    # **Never a live engine.** This is what Titan Access asks for and it
    # is the one thing that must not be built inside an application's
    # subprocess; None is what that function already promises when the
    # engine cannot be loaded, and every caller of it handles None.
    module.get_reader_engine = lambda: None
    module.__getattr__ = _asking(module.__name__, shim)


def _fill_ao3(module, shim):
    """`accessible_output3`, as far as an application uses it.

    One class, `Auto`, with the three methods every call site here uses.
    `braille` is silently nothing rather than spoken: a braille line and a
    spoken sentence are different things, and saying one as the other
    would put text in front of the user that was written to be felt.
    """
    class Auto(object):
        def __init__(self, *_a, **_k):
            pass

        def speak(self, text, interrupt=False, **_k):
            _say(shim, text, interrupt=interrupt)

        def output(self, text, interrupt=False, **_k):
            _say(shim, text, interrupt=interrupt)

        def braille(self, *_a, **_k):
            return None

        def stop(self, *_a, **_k):
            return None

        def is_active(self):
            return True

    module.Auto = Auto
    module.Output = Auto
    module.__getattr__ = _asking(module.__name__, shim)


def _asking(name, shim):
    """The long tail, answered rather than raised - the same rule as the
    rest of the shim, so an application asking for a corner of these that
    nobody has written carries on being wrong about one thing."""
    def answer(what):
        if what.startswith('__'):
            raise AttributeError(what)
        shim.RUNTIME.note_unknown('%s.%s' % (name, what))
        if what[:1].isupper():
            return shim._UnknownClass
        return shim._Silence(what)
    return answer
