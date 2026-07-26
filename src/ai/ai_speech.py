"""Shared spoken-feedback helper for all AI features (creation kit, agent,
assistant).

The AI features announce short status/progress messages ("Generating...",
"Listening...", "The AI has some questions", ...). Historically these went only
through ``accessible_output3`` (a system screen reader), which stays SILENT for
users who drive Titan with **Titan TTS** instead of NVDA/JAWS - so those users
heard nothing from the AI.

:func:`speak` fixes that by preferring Titan TTS (stereo speech) whenever it is
enabled in settings, and only falling back to accessible_output3 / the platform
notification voice otherwise. It never blocks (Titan TTS is spoken
asynchronously) and never raises.
"""


def titan_tts_enabled():
    """True when the user has turned on Titan TTS (stereo speech) for the
    invisible interface. Best effort - returns False on any error.

    NOTE: the value lives at key ``stereo_speech`` in the ``invisible_interface``
    SECTION. ``get_setting('invisible_interface', {})`` does NOT work - that reads
    a key called 'invisible_interface' from [general] and always yields the {}
    default (the bug that made the AI ignore Titan TTS)."""
    try:
        from src.settings.settings import get_setting
        val = get_setting('stereo_speech', 'False', section='invisible_interface')
        return str(val).lower() in ('true', '1')
    except Exception:
        return False


def speak(text, interrupt=True):
    """Speak ``text`` for the AI features:

      1. **Titan TTS** (``speak_stereo``, async) when it is enabled - so Titan
         TTS users actually hear the AI.
      2. otherwise the **screen reader** (accessible_output3), but only when one
         is actually running - like the IUI's screen-reader path.
      3. otherwise **stay silent**. No Titan TTS and no screen reader most likely
         means a low-vision user reading the screen visually, so forcing the
         platform (SAPI) voice for every status message would be intrusive; the
         GUI already shows the same status on screen.
    """
    text = str(text)
    if titan_tts_enabled():
        try:
            from src.titan_core.stereo_speech import speak_stereo
            speak_stereo(text, position=0.0, pitch_offset=0, async_mode=True)
            return
        except Exception:
            pass
    # Screen reader if one is genuinely running; stays silent otherwise
    # (speak_sr_only never falls back to the platform voice).
    try:
        from src.accessibility.messages import speak_sr_only
        speak_sr_only(text, interrupt=interrupt)
    except Exception:
        pass
