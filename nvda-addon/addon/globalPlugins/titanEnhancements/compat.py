# -*- coding: utf-8 -*-
"""What this NVDA has, asked rather than assumed.

An add-on that imports a name NVDA does not have fails at IMPORT, which for
a global plugin means the whole add-on is absent - and NVDA reports that in
its log, where nobody using it is looking. Every optional part of NVDA is
therefore reached through this module, which answers None rather than
raising, and the feature above it is switched off with a reason that can be
read back (``missing()``).

**Nothing here is a version test.** Version numbers are a proxy for what is
present, and a poor one: NVDA's alpha builds carry a year that has not
happened and a downstream fork may carry anything at all. So the question is
always "is this attribute there", asked once at import and remembered.
"""

import sys

#: Why a capability is unavailable - feature name -> one sentence.
_MISSING = {}


def _note(feature, reason):
    _MISSING[feature] = reason
    return None


def missing():
    """Every capability this NVDA has not got, and why."""
    return dict(_MISSING)


def _try(feature, importer):
    try:
        value = importer()
    except Exception as error:                       # noqa: BLE001
        return _note(feature, f'{type(error).__name__}: {error}')
    if value is None:
        return _note(feature, 'this NVDA does not have it')
    return value


# --------------------------------------------------------------------------- #
# The parts we cannot work without
# --------------------------------------------------------------------------- #
def _import_speech():
    import speech
    return speech


def _import_commands():
    from speech import commands
    return commands


speech = _try('speech', _import_speech)
speechCommands = _try('speech.commands', _import_commands)


def _import_extensions():
    from speech import extensions
    return extensions


speechExtensions = _try('speech.extensions', _import_extensions)


def _import_queue():
    import queueHandler
    return queueHandler


queueHandler = _try('queueHandler', _import_queue)


def _import_synth_handler():
    import synthDriverHandler
    return synthDriverHandler


synthDriverHandler = _try('synthDriverHandler', _import_synth_handler)


def _import_braille():
    import braille
    return braille


braille = _try('braille', _import_braille)


def _import_ui():
    import ui
    return ui


ui = _try('ui', _import_ui)


def _import_tones():
    import tones
    return tones


tones = _try('tones', _import_tones)


def _import_nvwave():
    import nvwave
    return nvwave


nvwave = _try('nvwave', _import_nvwave)


def _import_log():
    from logHandler import log
    return log


log = _try('logHandler.log', _import_log)


def _import_config():
    import config
    return config


config = _try('config', _import_config)


def _import_api():
    import api
    return api


api = _try('api', _import_api)


def _import_core():
    import core
    return core


#: NVDA's own main loop. `callLater` is the one thing wanted from it -
#: doing something a moment after a key, on the thread that is allowed to
#: read the screen and speak - and it is reached here rather than
#: imported where it is used, like everything else NVDA owns, so an NVDA
#: without it answers None instead of raising.
core = _try('core', _import_core)


def _import_gui():
    import gui
    return gui


#: NVDA's own interface - ``gui.mainFrame`` is the window every dialog and
#: every menu this add-on puts up belongs to, and ``prePopup`` /
#: ``postPopup`` is how NVDA hands it the foreground and takes it back.
#: Asked through here rather than imported, because the modules that use it
#: are shared with Titan Access, where the frame is Titan's own.
gui = _try('gui', _import_gui)


def _import_control_types():
    import controlTypes
    return controlTypes


controlTypes = _try('controlTypes', _import_control_types)


def _import_text_infos():
    import textInfos
    return textInfos


textInfos = _try('textInfos', _import_text_infos)


def _import_display_model():
    # NVDA's off-screen model: what every process DREW, kept by the GDI
    # hooks in the copy of `nvdaHelperRemote.dll` injected into it. The
    # tier under both OCR tiers - see `drawnText`.
    import displayModel
    return displayModel


displayModel = _try('displayModel', _import_display_model)


def _import_input_core():
    import inputCore
    return inputCore


inputCore = _try('inputCore', _import_input_core)


def _import_keyboard_gesture():
    from keyboardHandler import KeyboardInputGesture
    return KeyboardInputGesture


KeyboardInputGesture = _try('keyboardHandler.KeyboardInputGesture',
                            _import_keyboard_gesture)


# --------------------------------------------------------------------------- #
# The prosody commands, each asked for by name
# --------------------------------------------------------------------------- #
def _command(name):
    if speechCommands is None:
        return None
    value = getattr(speechCommands, name, None)
    if value is None:
        return _note(f'speech.commands.{name}',
                     'this NVDA does not carry that speech command')
    return value


PitchCommand = _command('PitchCommand')
RateCommand = _command('RateCommand')
VolumeCommand = _command('VolumeCommand')
BeepCommand = _command('BeepCommand')
BreakCommand = _command('BreakCommand')
IndexCommand = _command('IndexCommand')
CallbackCommand = _command('CallbackCommand')
LangChangeCommand = _command('LangChangeCommand')
EndUtteranceCommand = _command('EndUtteranceCommand')
CharacterModeCommand = _command('CharacterModeCommand')


def can_pan_streams():
    """Whether ``WavePlayer.setVolume`` is here at all.

    This is the one call the whole "any synthesizer can be panned" claim
    rests on. It arrived with NVDA's WASAPI player; before that there is
    nothing below the synth to pan, and the honest answer is to say so
    rather than to pan nothing quietly.
    """
    if nvwave is None:
        return False
    player = getattr(nvwave, 'WavePlayer', None)
    if player is None:
        _note('nvwave.WavePlayer', 'this NVDA has no WavePlayer')
        return False
    if not hasattr(player, 'setVolume'):
        _note('nvwave.WavePlayer.setVolume',
              'this NVDA cannot set the volume of one channel of a stream')
        return False
    return True


def running_under_nvda():
    """True when this really is NVDA and not a test runner importing us."""
    return 'globalPluginHandler' in sys.modules or speech is not None
