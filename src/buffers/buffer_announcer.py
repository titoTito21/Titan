# -*- coding: utf-8 -*-
"""
Titan Buffer System - announcer.

Centralises every spoken message and sound effect so buffer review sounds
identical in the GUI, Klango mode and the Titan UI overlay. Speech routing
mirrors klangomode.speak_klango / IUI.speak:

  * stereo_speech ON  -> speak_stereo() (uses Titan TTS when configured,
    otherwise falls back to accessible_output3 internally), with stereo pan.
  * stereo_speech OFF -> accessible_output3 directly.

Honours the existing settings (no new toggles are introduced):
  * announce_index        (invisible_interface) - append ", {i} of {n}" to elements
  * announce_widget_type  (invisible_interface) - append source kind to elements
  * announce_first_item   (invisible_interface) - preview the buffer's current
                            element when switching category or buffer
  * stereo_speech         (invisible_interface) - stereo speech + position
  * stereo_sound          (sound)               - stereo pan for sound effects

Category and buffer position ("1 of 2") is intrinsic to those levels and is
always spoken; only the per-element index is gated by announce_index, matching
how the IUI element list behaves.
"""

import threading

from src.settings.settings import get_setting
from src.titan_core.translation import set_language

# Sound effects (per the concept). tapbar / endoftapbar may need adding to a
# theme; play_sound() degrades gracefully (and can fall back to the default
# theme) when a file is missing.
SOUND_CATEGORY = "ui/tapbar.ogg"        # switching buffer category
SOUND_BUFFER = "ui/switch_list.ogg"     # switching buffer within a category
SOUND_LIST_BOUNDARY = "ui/endoftapbar.ogg"  # edge of category / buffer list
SOUND_ELEMENT = "core/FOCUS.ogg"        # moving between elements
SOUND_ELEMENT_BOUNDARY = "ui/endoflist.ogg"  # edge of element list

# Lazy speech handles (initialised on first use).
_speaker = None
_speak_stereo = None
_get_stereo_speech = None
_stereo_import_tried = False

# Cached translator, refreshed only when the language actually changes (so we
# don't rebuild every gettext catalog on each keystroke).
_cached_translator = None
_cached_lang = None


def _get_translator():
    global _cached_translator, _cached_lang
    try:
        lang = get_setting('language', 'pl')
    except Exception:
        lang = 'pl'
    if _cached_translator is None or lang != _cached_lang:
        try:
            _cached_translator = set_language(lang)
            _cached_lang = lang
        except Exception:
            _cached_translator = (lambda s: s)
            _cached_lang = lang
    return _cached_translator


def _get_speaker():
    global _speaker
    if _speaker is None:
        try:
            import accessible_output3.outputs.auto
            _speaker = accessible_output3.outputs.auto.Auto()
        except Exception as e:
            print(f"[BufferAnnouncer] speaker init failed: {e}")
            _speaker = False
    return _speaker or None


def _ensure_stereo():
    global _speak_stereo, _get_stereo_speech, _stereo_import_tried
    if not _stereo_import_tried:
        _stereo_import_tried = True
        try:
            from src.titan_core.stereo_speech import speak_stereo, get_stereo_speech
            _speak_stereo = speak_stereo
            _get_stereo_speech = get_stereo_speech
        except Exception as e:
            print(f"[BufferAnnouncer] stereo speech unavailable: {e}")
            _speak_stereo = None
            _get_stereo_speech = None
    return _speak_stereo


def _play(sound_file, pan=None):
    try:
        from src.titan_core.sound import play_sound
        play_sound(sound_file, pan=pan)
    except Exception as e:
        print(f"[BufferAnnouncer] sound error: {e}")


def _stereo_enabled():
    try:
        return get_setting('stereo_speech', 'False',
                           section='invisible_interface').lower() == 'true'
    except Exception:
        return False


def _sound_stereo_enabled():
    """True when positioning (stereo or 3D) is active per the sound mode."""
    try:
        from src.titan_core.sound import get_sound_mode
        return get_sound_mode() in ('stereo', '3d')
    except Exception:
        return get_setting('stereo_sound', 'False',
                           section='sound').lower() in ('true', '1')


def _pan_for(index, count):
    """Map a 1-based position to a 0.0(left)..1.0(right) pan value."""
    if count <= 1:
        return 0.5
    return (index - 1) / (count - 1)


def _index_enabled():
    """announce_index (invisible_interface) - same toggle the IUI element list uses."""
    try:
        return get_setting('announce_index', 'False',
                           section='invisible_interface').lower() == 'true'
    except Exception:
        return False


def _widget_type_enabled():
    """announce_widget_type (invisible_interface).

    The level labels ("buffer category" / "buffer") and the element source kind
    ("message" / "notification") are this buffer's equivalent of a control type,
    so - like the IUI widget-type hint - they are only spoken when this is on.
    """
    try:
        return get_setting('announce_widget_type', 'False',
                           section='invisible_interface').lower() == 'true'
    except Exception:
        return False


def _with_index(text, nav):
    """Append ", {index} of {total}" when announce_index is on, mirroring IUI.

    Applies to every level (category, buffer, element, parameter) so the spoken
    position is fully governed by the announce_index setting rather than being
    hard-coded into some messages.
    """
    if _index_enabled() and nav.count:
        _ = _get_translator()
        text += ", " + _("{index} of {total}").format(
            index=nav.index, total=nav.count)
    return text


def speak(text, position=0.0, pitch_offset=0, interrupt=True):
    """Speak text, mirroring klangomode.speak_klango behaviour."""
    if not text:
        return

    if _stereo_enabled() and _ensure_stereo():
        def _run():
            try:
                if interrupt and _get_stereo_speech:
                    try:
                        ss = _get_stereo_speech()
                        if ss:
                            ss.stop()
                    except Exception:
                        pass
                _speak_stereo(text, position=position,
                              pitch_offset=pitch_offset, async_mode=True)
            except Exception as e:
                print(f"[BufferAnnouncer] stereo speak error: {e}")
                spk = _get_speaker()
                if spk:
                    spk.output(text)
        threading.Thread(target=_run, daemon=True).start()
    else:
        def _run():
            try:
                spk = _get_speaker()
                if spk:
                    if interrupt and hasattr(spk, 'stop'):
                        try:
                            spk.stop()
                        except Exception:
                            pass
                    spk.output(text)
            except Exception as e:
                print(f"[BufferAnnouncer] speak error: {e}")
        threading.Thread(target=_run, daemon=True).start()


def announce(nav):
    """Speak + play the right sound for a NavResult from buffer_controller."""
    try:
        if nav is None:
            return
        if nav.level == "category":
            _announce_level(nav, SOUND_CATEGORY, SOUND_LIST_BOUNDARY,
                            _category_text)
        elif nav.level == "buffer":
            _announce_level(nav, SOUND_BUFFER, SOUND_LIST_BOUNDARY,
                            _buffer_text)
        elif nav.level == "element":
            _announce_element(nav)
        elif nav.level == "parameter":
            _announce_level(nav, SOUND_BUFFER, SOUND_LIST_BOUNDARY,
                            _parameter_text)
        elif nav.level == "value":
            # Interactive (TTS) value change: just announce the new value.
            _play(SOUND_ELEMENT)
            if nav.text:
                speak(nav.text)
    except Exception as e:
        print(f"[BufferAnnouncer] announce error: {e}")


def _announce_level(nav, move_sound, boundary_sound, text_fn):
    sound_stereo = _sound_stereo_enabled()
    pan = _pan_for(nav.index, nav.count) if sound_stereo else None
    if nav.moved:
        _play(move_sound, pan=pan)
    else:
        _play(boundary_sound)

    if nav.count == 0:
        return
    text = text_fn(nav)
    position = (pan * 2.0 - 1.0) if (sound_stereo and pan is not None) else 0.0
    speak(text, position=position)


def _announce_element(nav):
    sound_stereo = _sound_stereo_enabled()
    if nav.count == 0:
        # Empty buffer: report it instead of staying silent.
        _ = _get_translator()
        _play(SOUND_ELEMENT_BOUNDARY)
        speak(_("Buffer is empty"))
        return

    pan = _pan_for(nav.index, nav.count) if sound_stereo else None
    if nav.moved:
        _play(SOUND_ELEMENT, pan=pan)
    else:
        _play(SOUND_ELEMENT_BOUNDARY)

    text = _element_text(nav)
    position = (pan * 2.0 - 1.0) if (sound_stereo and pan is not None) else 0.0
    speak(text, position=position)


# --------------------------------------------------------------------------- #
#  Text builders
# --------------------------------------------------------------------------- #
def _first_item_enabled():
    """announce_first_item (invisible_interface).

    When off, navigating to a category or buffer announces only its name (and,
    per their own settings, type/index) - never the content of the buffer's
    current element. When on, the current element is previewed, mirroring the
    IUI "announce first item in category" behaviour.
    """
    try:
        return get_setting('announce_first_item', 'False',
                           section='invisible_interface').lower() == 'true'
    except Exception:
        return False


def _element_preview():
    """Current element of the active buffer when announce_first_item is on,
    otherwise "". Used by both the category and buffer level so the same
    setting governs every automatic element read-out during navigation."""
    if not _first_item_enabled():
        return ""
    try:
        from src.buffers.buffer_system import get_buffer_manager
        return get_buffer_manager().current_element_preview()
    except Exception:
        return ""


def _category_text(nav):
    _ = _get_translator()
    text = str(nav.name)
    if _widget_type_enabled():
        text += ", " + _("buffer category")
    text = _with_index(text, nav)
    # Honour the existing IUI setting: append the active buffer's current
    # element when announce_first_item is enabled.
    preview = _element_preview()
    if preview:
        text += ", " + preview
    return text


def _buffer_text(nav):
    _ = _get_translator()
    text = str(nav.name)
    if _widget_type_enabled():
        text += ", " + _("buffer")
    text = _with_index(text, nav)
    # Same announce_first_item gate as the category level: preview the newly
    # selected buffer's current element only when the setting is on.
    preview = _element_preview()
    if preview:
        text += ", " + preview
    return text


def _parameter_text(nav):
    # nav.name already carries "Label: value" from the live handler.
    return _with_index(str(nav.name), nav)


def _element_text(nav):
    _ = _get_translator()
    if nav.author and nav.kind in ('message', 'private'):
        text = _("Message from {author}, {text}").format(
            author=nav.author, text=nav.text)
    elif nav.author:
        text = _("{author}: {text}").format(author=nav.author, text=nav.text)
    else:
        text = nav.text

    # announce_widget_type -> append a friendly source-kind hint when present.
    if _widget_type_enabled() and nav.kind:
        kind_labels = {
            'message': _("message"),
            'private': _("message"),
            'notification': _("notification"),
        }
        text += ", " + kind_labels.get(nav.kind, str(nav.kind))

    # announce_index -> append the element position.
    text = _with_index(text, nav)

    return text
