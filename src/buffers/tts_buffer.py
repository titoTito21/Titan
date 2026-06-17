# -*- coding: utf-8 -*-
"""
Titan Buffer System - interactive TTS engine category.

A live buffer category that controls the CURRENT TTS engine through the same
buffer keys:

    [  ]   switch parameter (Voice, Speed, Pitch, Volume + engine config fields)
    {  }   first / last parameter
    ,  .   change the current parameter's value
    <  >   jump the value to minimum / maximum

There is no ping (nothing is pushed into it). Every change is applied to the
live TTS engine AND written to settings immediately, so it never drifts out of
sync with the Settings GUI (section [stereo_speech]; engine fields as
engine.<id>.<key>).

Only the currently active engine drives this category; switching engine changes
which parameters appear (the engine's get_config_fields() are merged in).
"""

from src.settings.settings import get_setting, set_setting

CATEGORY_ID = 'tts'

# Standard parameter ids (always present).
_STD = ('voice', 'rate', 'pitch', 'volume')


def _t():
    try:
        from src.titan_core.translation import set_language
        return set_language(get_setting('language', 'pl'))
    except Exception:
        return lambda s: s


def _speech():
    """The LIVE StereoSpeech singleton - the SAME instance the announcer and
    the whole app actually speak through (get_stereo_speech).

    Important: tce_speech._init() builds its OWN separate StereoSpeech, so
    setting voice/rate/pitch there would NOT affect what the user hears. We
    target the singleton so changes (e.g. SAPI voice) apply immediately and
    are spoken right away in the new voice. Returns None if unavailable.
    """
    try:
        from src.titan_core.stereo_speech import get_stereo_speech
        return get_stereo_speech()
    except Exception:
        return None


def _engine_id():
    ss = _speech()
    try:
        return ss.get_engine() if ss else ''
    except Exception:
        return ''


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# --------------------------------------------------------------------------- #
#  Settings helpers (section [stereo_speech])
# --------------------------------------------------------------------------- #
def _get_int(key, default):
    try:
        return int(get_setting(key, str(default), section='stereo_speech'))
    except Exception:
        return default


def _set_int(key, value):
    try:
        set_setting(key, str(int(value)), section='stereo_speech')
    except Exception:
        pass


# --------------------------------------------------------------------------- #
#  Voice helpers
# --------------------------------------------------------------------------- #
def _voice_list():
    """Return [(voice_id, voice_name)] for the current engine."""
    try:
        voices = _speech().get_available_voices() or []
    except Exception:
        voices = []
    norm = []
    for v in voices:
        if isinstance(v, dict):
            vid = (v.get('id') or v.get('voice_id') or v.get('language')
                   or v.get('name') or '')
            vname = v.get('name') or vid
        else:
            vid = vname = str(v)
        norm.append((str(vid), str(vname)))
    return norm


def _voice_index(norm):
    cur = get_setting('voice', '', section='stereo_speech')
    for i, (vid, vname) in enumerate(norm):
        if cur and (vid == cur or vname == cur):
            return i
    return 0


# --------------------------------------------------------------------------- #
#  Engine config field helpers
# --------------------------------------------------------------------------- #
def _engine_fields():
    """Return (engine_id, [adjustable field descriptors])."""
    engine_id = _engine_id()
    if not engine_id:
        return ('', [])
    try:
        from src.tts.engine_registry import get_engine_registry
        reg = get_engine_registry()
        eng = reg.get_titantts_engine(engine_id) if reg else None
        if not eng or not hasattr(eng, 'get_config_fields'):
            return (engine_id, [])
        fields = eng.get_config_fields() or []
        # Only types that can be cycled/stepped/toggled with , . keys.
        return (engine_id, [f for f in fields
                            if f.get('type') in ('choice', 'slider', 'checkbox')])
    except Exception as e:
        print(f"[TTSBuffer] engine fields error: {e}")
        return (engine_id, [])


def _field_value(engine_id, field):
    try:
        return _speech().get_engine_config(engine_id, field.get('key'),
                                           field.get('default'))
    except Exception:
        return field.get('default')


def _field_display(field, value):
    _ = _t()
    ftype = field.get('type')
    if ftype == 'choice':
        for val, disp in (field.get('options') or []):
            if val == value:
                return str(disp)
        return str(value)
    if ftype == 'checkbox':
        on = str(value).lower() in ('1', 'true', 'yes', 'on')
        return _("On") if on else _("Off")
    return str(value)


# --------------------------------------------------------------------------- #
#  Handler
# --------------------------------------------------------------------------- #
class TTSParameterHandler:
    """Drives the interactive TTS category for the current engine."""

    def list_params(self):
        _ = _t()
        params = []

        # Voice
        norm = _voice_list()
        voice_disp = norm[_voice_index(norm)][1] if norm else _("None")
        params.append(('voice', "{}: {}".format(_("Voice"), voice_disp)))

        # Speed / Pitch / Volume
        params.append(('rate', "{}: {}".format(_("Speed"), _get_int('rate', 0))))
        params.append(('pitch', "{}: {}".format(_("Pitch"), _get_int('pitch', 0))))
        params.append(('volume', "{}: {}".format(_("Volume"), _get_int('volume', 100))))

        # Current engine's extra config fields
        engine_id, fields = _engine_fields()
        for f in fields:
            val = _field_value(engine_id, f)
            label = f.get('label') or f.get('key')
            params.append(('cfg:' + f.get('key'),
                           "{}: {}".format(label, _field_display(f, val))))
        return params

    def adjust(self, param_id, direction, extreme=False):
        """Apply a value change to a parameter; return the new value string."""
        if param_id == 'voice':
            return self._adjust_voice(direction, extreme)
        if param_id in ('rate', 'pitch'):
            return self._adjust_ranged(param_id, direction, extreme,
                                       lo=-10, hi=10, step=1)
        if param_id == 'volume':
            return self._adjust_ranged('volume', direction, extreme,
                                       lo=0, hi=100, step=5)
        if param_id.startswith('cfg:'):
            return self._adjust_cfg(param_id[4:], direction, extreme)
        return ""

    # -- standard params --
    def _adjust_ranged(self, key, direction, extreme, lo, hi, step):
        cur = _get_int(key, 0 if key != 'volume' else 100)
        new = (hi if direction > 0 else lo) if extreme \
            else _clamp(cur + direction * step, lo, hi)
        try:
            speech = _speech()
            getattr(speech, 'set_' + ('rate' if key == 'rate'
                                      else 'pitch' if key == 'pitch'
                                      else 'volume'))(new)
        except Exception as e:
            print(f"[TTSBuffer] apply {key} error: {e}")
        _set_int(key, new)
        return str(new)

    def _adjust_voice(self, direction, extreme):
        _ = _t()
        norm = _voice_list()
        if not norm:
            return _("No voices")
        i = _voice_index(norm)
        if extreme:
            i = (len(norm) - 1) if direction > 0 else 0
        else:
            i = _clamp(i + direction, 0, len(norm) - 1)
        vid, vname = norm[i]
        try:
            _speech().set_voice(i)
        except Exception as e:
            print(f"[TTSBuffer] set_voice error: {e}")
        try:
            set_setting('voice', vid, section='stereo_speech')
        except Exception:
            pass
        return vname

    # -- engine config fields --
    def _adjust_cfg(self, key, direction, extreme):
        _ = _t()
        engine_id, fields = _engine_fields()
        field = next((f for f in fields if f.get('key') == key), None)
        if not field:
            return ""
        ftype = field.get('type')
        cur = _field_value(engine_id, field)

        if ftype == 'choice':
            opts = field.get('options') or []
            vals = [o[0] for o in opts]
            if not vals:
                return ""
            try:
                idx = vals.index(cur)
            except ValueError:
                idx = 0
            idx = (len(vals) - 1 if direction > 0 else 0) if extreme \
                else _clamp(idx + direction, 0, len(vals) - 1)
            newval = vals[idx]
            disp = str(opts[idx][1])
        elif ftype == 'slider':
            mn = int(field.get('min', 0))
            mx = int(field.get('max', 100))
            step = int(field.get('step', 1) or 1)
            try:
                c = int(cur)
            except Exception:
                c = mn
            newval = (mx if direction > 0 else mn) if extreme \
                else _clamp(c + direction * step, mn, mx)
            disp = str(newval)
        elif ftype == 'checkbox':
            on = str(cur).lower() in ('1', 'true', 'yes', 'on')
            newval = (not on)
            disp = _("On") if newval else _("Off")
        else:
            return str(cur)

        try:
            _speech().set_engine_config(engine_id, key, newval)
        except Exception as e:
            print(f"[TTSBuffer] set_engine_config error: {e}")
        # Persist where the Settings GUI reads it, so the two never conflict.
        try:
            set_setting('engine.{}.{}'.format(engine_id, key), str(newval),
                        section='stereo_speech')
        except Exception:
            pass
        return disp


def register():
    """Register the live TTS category. Safe to call once at startup."""
    try:
        from src.buffers.buffer_system import get_buffer_manager
        get_buffer_manager().register_live_category(
            CATEGORY_ID, _t()("TTS engine"), TTSParameterHandler())
    except Exception as e:
        print(f"[TTSBuffer] register error: {e}")


def refresh():
    """Re-sync the live TTS category to the CURRENT engine.

    Call after the user changes the TTS engine in Settings so the buffer's
    parameters reflect the new engine (its config fields differ). Resets the
    current parameter to the first one, since the old engine's fields may no
    longer exist. Registers the category first if it was not yet present.
    """
    try:
        from src.buffers.buffer_system import get_buffer_manager
        mgr = get_buffer_manager()
        cat = mgr.categories.get(CATEGORY_ID)
        if cat is None:
            register()
            return
        params = TTSParameterHandler().list_params()
        cat.current_buffer_id = params[0][0] if params else None
    except Exception as e:
        print(f"[TTSBuffer] refresh error: {e}")
