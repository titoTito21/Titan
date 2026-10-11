# -*- coding: utf-8 -*-
"""What Titan Access can speak WITH: speech system, synthesizer, voice.

Three levels, because that is how speech is really organised on every
platform this reader runs on, and flattening them is how a list of 400
voices with no order happens:

* a **speech system** - Titan's own voice (whatever Titan speaks with),
  Titan TTS (the engines Titan ships: Eloquence, DECtalk, Supertonic...),
  Microsoft SAPI 5, eSpeak NG, speech-dispatcher on Linux, ``say`` on a
  Mac. Only the ones this machine really has are offered.
* a **synthesizer** inside it - one Titan TTS engine, or one of
  speech-dispatcher's output modules (espeak-ng, festival, rhvoice...).
  Systems that are one synthesizer have exactly one row here.
* a **voice** of that synthesizer.

No wx here: this is the model the dialog (`speech_system_dialog`) shows
and the tests drive. Voices are listed WITHOUT switching the reader's
live engine - listing by `set_engine` on the speaking engine is how a
reader starts talking in the voice it was merely asked about.

A fourth level, the **variant**, exists where a synthesizer has one:
Cerence's compact / embedded-pro / embedded-high per voice.

Choosing writes the reader's own Speech settings (``OwnVoice``,
``Synthesizer``, ``Voice``, ``Variant``, ``SpeechDispatcherModule``) and applies them,
so the choice is the same one the settings page makes - one store, one
meaning.
"""

import sys

try:
    from .localization import L
except Exception:                                    # noqa: BLE001
    def L(key, *args):
        return key

#: The speech systems by id, with the words they are shown as.
SYSTEM_TITAN = 'titan'        # whatever Titan itself speaks with
SYSTEM_TITANTTS = 'titantts'  # Titan's own engines, from the registry
PLATFORM = ('sapi5', 'espeak', 'spd', 'say')

_SYSTEM_LABELS = {
    SYSTEM_TITAN: 'speechSystem.system.titan',
    SYSTEM_TITANTTS: 'speechSystem.system.titantts',
    'sapi5': 'speechSystem.system.sapi5',
    'espeak': 'speechSystem.system.espeak',
    'spd': 'speechSystem.system.spd',
    'say': 'speechSystem.system.say',
    'nvda': 'speechSystem.system.nvda',
}

#: External synthesis - NVDA add-on synthesizers installed in Titan Access
#: (`nvda_host`). A system of the reader's own; Titan's TTS never sees it.
SYSTEM_EXTERNAL = 'nvda'


def _registry():
    try:
        from src.tts.engine_registry import get_engine_registry
        return get_engine_registry()
    except Exception:                                # noqa: BLE001
        return None


def _engine():
    """A StereoSpeech to ASK - the reader's private one, never switched."""
    try:
        from src.titan_core import tce_speech
        return tce_speech.get_private_reader_engine()
    except Exception:                                # noqa: BLE001
        return None


def _offered(engine):
    try:
        return [str(one) for one in (engine.get_available_engines() or [])]
    except Exception:                                # noqa: BLE001
        return []


def _titantts_ids(engine=None):
    """Titan TTS engines this machine lists, in the registry's order."""
    registry = _registry()
    offered = _offered(engine) if engine is not None else []
    found = []
    try:
        for one in registry.get_all_engines():
            if getattr(one, 'engine_category', '') != 'titantts':
                continue
            if offered and one.engine_id not in offered:
                continue
            found.append(one.engine_id)
    except Exception:                                # noqa: BLE001
        pass
    return found


def _engine_name(engine_id):
    registry = _registry()
    try:
        one = registry.get_engine(engine_id)
        name = str(getattr(one, 'engine_name', '') or '')
        if name:
            return name
    except Exception:                                # noqa: BLE001
        pass
    return str(engine_id)


def system_of(engine_id):
    """The system a synthesizer id belongs to."""
    engine_id = str(engine_id or '')
    if engine_id.startswith('nvda:'):
        return SYSTEM_EXTERNAL
    if engine_id in ('espeak', 'espeak_dll'):
        return 'espeak'
    if engine_id in PLATFORM:
        return engine_id
    return SYSTEM_TITANTTS if engine_id else SYSTEM_TITAN


def systems(engine=None):
    """``[(system_id, label)]`` - only what this machine has."""
    engine = engine if engine is not None else _engine()
    offered = _offered(engine) if engine is not None else []
    found = [(SYSTEM_TITAN, L(_SYSTEM_LABELS[SYSTEM_TITAN]))]
    if _titantts_ids(engine):
        found.append((SYSTEM_TITANTTS, L(_SYSTEM_LABELS[SYSTEM_TITANTTS])))
    for system in PLATFORM:
        names = ('espeak', 'espeak_dll') if system == 'espeak' else (system,)
        if any(name in offered for name in names):
            found.append((system, L(_SYSTEM_LABELS[system])))
    if _external():
        found.append((SYSTEM_EXTERNAL, L(_SYSTEM_LABELS[SYSTEM_EXTERNAL])))
    return found


def _external():
    """``[(synth_id, label)]`` of the NVDA add-on synthesizers."""
    try:
        from . import nvda_host
        if not nvda_host.installed():
            return []
        return [('nvda:%s' % one['name'], '%s (%s)' % (one['description'],
                                                      one['addon']))
                for one in nvda_host.synthesizers() if not one['error']]
    except Exception:                                # noqa: BLE001
        return []


def synthesizers(system, engine=None):
    """``[(synth_id, label)]`` of one system.

    A synth id is the engine id Titan speaks with, except under
    speech-dispatcher, where it is ``spd:<module>`` (``spd:`` for its
    default module)."""
    engine = engine if engine is not None else _engine()
    system = str(system or '')
    if system == SYSTEM_TITAN:
        return [('', L('speechSystem.synth.titan'))]
    if system == SYSTEM_EXTERNAL:
        return _external()
    if system == SYSTEM_TITANTTS:
        return [(one, _engine_name(one)) for one in _titantts_ids(engine)]
    if system == 'spd':
        modules = []
        try:
            modules = list(engine.get_spd_modules() or [])
        except Exception:                            # noqa: BLE001
            modules = []
        rows = [('spd:', L('speechSystem.synth.spdDefault'))]
        rows += [('spd:%s' % one, one) for one in modules]
        return rows
    if system == 'espeak':
        offered = _offered(engine)
        engine_id = 'espeak' if 'espeak' in offered or not offered \
            else 'espeak_dll'
        return [(engine_id, _engine_name(engine_id))]
    if system in PLATFORM:
        return [(system, _engine_name(system))]
    return []


def _spd_voices(engine, module):
    """speech-dispatcher's voices for one module, asked without changing the
    module the engine speaks with."""
    keep = getattr(engine, 'spd_module', None)
    keep_voice = getattr(engine, 'spd_voice', None)
    try:
        engine.spd_module = module or None
        return list(engine.get_spd_voices() or [])
    except Exception:                                # noqa: BLE001
        return []
    finally:
        engine.spd_module = keep
        engine.spd_voice = keep_voice


def _com_on_this_thread():
    if not sys.platform.startswith('win'):
        return
    try:
        import pythoncom
        pythoncom.CoInitialize()
        return
    except Exception:                                # noqa: BLE001
        pass
    try:
        import ctypes
        ctypes.windll.ole32.CoInitializeEx(None, 2)
    except Exception:                                # noqa: BLE001
        pass


#: The voices of a synthesizer are asked once a minute at most. Asking is
#: COM for SAPI, a process for a Wine bridge, a subprocess for
#: speech-dispatcher - and the walked settings, the ring and the TPad all
#: say the voice's NAME, which is a lookup in this list.
VOICES_KEPT_S = 60.0
_voice_cache = {}


def forget_voices():
    _voice_cache.clear()
    _variant_cache.clear()


def voices(synth, engine=None, fresh=False):
    """``[(voice_id, label)]`` of one synthesizer. The id is what the
    reader's settings store and `speech_adapter._voice_index` finds."""
    import time
    synth = str(synth or '')
    kept = _voice_cache.get(synth)
    if kept is not None and not fresh and \
            time.time() - kept[0] < VOICES_KEPT_S:
        return list(kept[1])
    rows = _voices_now(synth, engine)
    if rows:
        _voice_cache[synth] = (time.time(), list(rows))
    return rows


def cached_voices(synth):
    """The voices already known for ``synth`` (however old), or None -
    never asks the synthesizer."""
    kept = _voice_cache.get(str(synth or ''))
    return list(kept[1]) if kept is not None else None


def prefetch_voices(synth):
    """Read the voices of ``synth`` on a thread of their own, so the next
    one to ask finds them."""
    import threading
    synth = str(synth or '')
    if not synth or synth in _voice_cache:
        return

    def read():
        try:
            voices(synth)
        except Exception:                            # noqa: BLE001
            pass
    threading.Thread(target=read, name='TitanAccessVoicePrefetch',
                     daemon=True).start()


_variant_cache = {}


def variants(synth, voice='', fresh=False):
    """``[(variant_id, label)]`` of one voice of one synthesizer - the
    FOURTH level, which only some synthesizers have: Cerence installs a
    voice as compact, embedded-pro or embedded-high and lets the quality
    be chosen per voice; eSpeak has its variants. Empty for everything
    without one, so the level is simply not offered there."""
    import time
    synth = str(synth or '')
    if not synth.startswith('nvda:'):
        return []
    key = (synth, str(voice or ''))
    kept = _variant_cache.get(key)
    if kept is not None and not fresh and \
            time.time() - kept[0] < VOICES_KEPT_S:
        return list(kept[1])
    try:
        from .nvda_host import external
        rows = external.variants(synth, voice or None)
    except Exception:                                # noqa: BLE001
        rows = []
    _variant_cache[key] = (time.time(), list(rows))
    return rows


def cached_variants(synth, voice=''):
    kept = _variant_cache.get((str(synth or ''), str(voice or '')))
    return list(kept[1]) if kept is not None else None


def current_variant(settings):
    """The variant the reader is set to, '' for the synthesizer's own."""
    try:
        return str(settings.get('Speech', 'Variant', '') or '')
    except Exception:                                # noqa: BLE001
        return ''


def _voices_now(synth, engine=None):
    # An external synthesizer is asked BEFORE Titan's engine is made: making
    # the private engine loads every Titan TTS engine and its bridges, which
    # is seconds the first time and nothing an NVDA synthesizer needs.
    if synth.startswith('nvda:'):
        try:
            from .nvda_host import external
            return external.voices(synth)
        except Exception:                            # noqa: BLE001
            return []
    engine = engine if engine is not None else _engine()
    if not synth or engine is None:
        return []
    raw = []
    try:
        if synth.startswith('spd:'):
            raw = _spd_voices(engine, synth[4:])
        elif synth == 'sapi5':
            # SAPI is COM, and the dialog asks on a worker of its own: a
            # thread that never joined an apartment gets no voices at all.
            _com_on_this_thread()
            for one in engine._get_all_sapi_voices() or []:
                name = one.get('name', '')
                if one.get('is_32bit'):
                    name += ' (32-bit)'
                raw.append(name)
        elif synth in ('espeak', 'espeak_dll'):
            raw = list(engine.get_espeak_voices() or [])
        elif synth == 'say':
            raw = list(engine.get_say_voices() or [])
        else:
            registry = _registry()
            one = registry.get_titantts_engine(synth) if registry else None
            raw = list(one.get_voices() or []) if one is not None else []
    except Exception as error:                       # noqa: BLE001
        print(f"[TitanAccess] voices of {synth}: {error}")
        raw = []
    rows = []
    for one in raw:
        if isinstance(one, dict):
            label = str(one.get('display_name') or one.get('name')
                        or one.get('id') or '')
            key = str(one.get('id') or one.get('display_name')
                      or one.get('name') or '')
        else:
            label = key = str(one)
        if key:
            rows.append((key, label or key))
    return rows


def current(settings):
    """``(system, synth, voice)`` the reader is set to now."""
    try:
        own = settings.get_bool('Speech', 'OwnVoice', False)
    except Exception:                                # noqa: BLE001
        own = False
    if not own:
        return SYSTEM_TITAN, '', ''
    engine_id = str(settings.get('Speech', 'Synthesizer', '') or '')
    voice = str(settings.get('Speech', 'Voice', '') or '')
    system = system_of(engine_id)
    synth = engine_id
    if engine_id == 'spd':
        synth = 'spd:%s' % str(settings.get(
            'Speech', 'SpeechDispatcherModule', '') or '')
    return system, synth, voice


def profile_of(synth, voice, variant=''):
    """The voice profile `speech_adapter.speak_with` borrows for a Test."""
    synth = str(synth or '')
    if not synth:
        return {}
    if synth.startswith('spd:'):
        return {'synth': 'spd', 'spd_module': synth[4:], 'voice': voice}
    profile = {'synth': synth, 'voice': voice}
    if variant:
        profile['variant'] = str(variant)
    return profile


def settings_for(system, synth, voice, variant=''):
    """``{(section, key): value}`` - what a choice of speech system,
    synthesizer and voice is in the reader's settings. One place, so the
    dialog, the settings page, the walked settings, a profile and the TPad
    all write the same thing."""
    system = str(system or '')
    if system == SYSTEM_TITAN:
        return {('Speech', 'OwnVoice'): False}
    synth = str(synth or '')
    engine_id, module = synth, ''
    if synth.startswith('spd:'):
        engine_id, module = 'spd', synth[4:]
    # The variant belongs to the voice: a new voice starts on its own
    # default ('' - whatever the synthesizer gives it) rather than on a
    # variant name that may mean nothing to it.
    return {('Speech', 'OwnVoice'): True,
            ('Speech', 'Synthesizer'): engine_id,
            ('Speech', 'Voice'): str(voice or ''),
            ('Speech', 'Variant'): str(variant or ''),
            ('Speech', 'SpeechDispatcherModule'): module}


def first_synth(system, engine=None):
    rows = synthesizers(system, engine)
    return rows[0][0] if rows else ''


def label_of(rows, wanted):
    for key, label in rows:
        if str(key) == str(wanted):
            return label
    return str(wanted or '')


def step(settings, level, forward=True, engine=None, reader=None):
    """Move ONE of the three levels to the next (or previous) choice, as
    the TPad and the settings ring do: the system (and then its first
    synthesizer), the synthesizer (inside the system), or the voice (of
    the synthesizer). Writes and applies it; answers the words to say, or
    '' when there is nothing to move to."""
    system, synth, voice = current(settings)
    variant = current_variant(settings)
    if level == 'variant':
        if system == SYSTEM_TITAN or not synth:
            return ''
        rows = variants(synth, voice)
        if not rows:
            return ''
        keys = [str(key) for key, _label in rows]
        at = keys.index(variant) if variant in keys else -1
        at = (at + (1 if forward else -1)) % len(keys)
        choose(settings, system, synth, voice, reader, variant=keys[at])
        return rows[at][1]
    if level == 'system':
        rows = systems(engine)
    elif level == 'synth':
        if system == SYSTEM_TITAN:
            return ''
        rows = synthesizers(system, engine)
    else:
        if system == SYSTEM_TITAN or not synth:
            return ''
        rows = voices(synth, engine)
    if not rows:
        return ''
    keys = [str(key) for key, _label in rows]
    now = {'system': system, 'synth': synth}.get(level, voice)
    at = keys.index(str(now)) if str(now) in keys else -1
    at = (at + (1 if forward else -1)) % len(keys)
    chosen = keys[at]
    if level == 'system':
        system = chosen
        synth = first_synth(system, engine)
        voice = ''
    elif level == 'synth':
        synth, voice = chosen, ''
    else:
        voice = chosen
    choose(settings, system, synth, voice, reader)
    return rows[at][1]


def _set_bool(settings, key, value):
    if hasattr(settings, 'set_bool'):
        settings.set_bool('Speech', key, value)
    else:
        settings.set('Speech', key, 'true' if value else 'false')


def choose(settings, system, synth, voice, engine=None, variant=''):
    """Write the choice into the reader's Speech settings and apply it.

    ``engine`` is the running TitanAccessEngine (its ``apply_settings``
    swaps the reader onto its own engine or back onto Titan's). Answers the
    sentence to say."""
    for (_section, key), value in settings_for(system, synth, voice,
                                               variant).items():
        if isinstance(value, bool):
            _set_bool(settings, key, value)
        else:
            settings.set('Speech', key, value)
    try:
        settings.save()
    except Exception:                                # noqa: BLE001
        pass
    if engine is not None:
        try:
            if hasattr(engine, 'apply_settings'):
                engine.apply_settings()
            elif getattr(engine, 'speech', None) is not None:
                engine.speech.apply_settings()
        except Exception as error:                   # noqa: BLE001
            print(f"[TitanAccess] speech system apply: {error}")
    return L('speechSystem.chosen')


def platform_word():
    if sys.platform.startswith('win'):
        return 'windows'
    if sys.platform == 'darwin':
        return 'macos'
    return 'linux'
