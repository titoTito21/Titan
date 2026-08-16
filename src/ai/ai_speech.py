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


#: The sound of the AI asking the user something - the creation kit's
#: questionnaire, the agent's and the assistant's follow-up questions, and an
#: action that needs an answer before it can run. The question usually arrives
#: while the user is listening to something else, and this is what tells them
#: a dialog is now there.
#:
#: It is the STATUS BAR sound, not `ai/agent_question.ogg`: a question is not
#: an error and must not sound like one. Every theme carries `ui/statusbar.ogg`
#: and each of them has its own, so the cue also sounds like the rest of the
#: theme the user chose.
SOUND_QUESTION = 'ui/statusbar.ogg'


def play_question_sound():
    """Play it. Never raises, never blocks.

    A name inside the AI's own folder (`ai/...`) goes through
    `play_ai_sound`, which knows that set belongs to the feature; anything
    else is an ordinary theme sound and is played as one - so pointing
    `SOUND_QUESTION` at either kind is all it takes to change the cue.
    """
    name = SOUND_QUESTION
    try:
        from src.titan_core import sound
        if '/' not in name or name.startswith('ai/'):
            return bool(sound.play_ai_sound(name))
        sound.play_sound(name)
        return True
    except Exception:
        return False


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


def assistant_uses_titan_tts():
    """True when the voice assistant itself speaks with Titan TTS (either chosen
    outright or resolved that way because no cloud TTS key is configured)."""
    try:
        from src.ai import ai_provider
        return ai_provider.resolve_assistant_tts() == 'titan'
    except Exception:
        return False


def speak_status(text, interrupt=True):
    """Speak a PROGRESS status of the assistant ("Thinking...", "Speaking...").

    These are useful while the assistant answers in a cloud voice: the status is
    narrated by Titan TTS / the screen reader and the reply arrives in a clearly
    different voice. When the assistant itself speaks with **Titan TTS**, status
    and answer share one voice, so the chatter only talks over the answer - the
    audio cues (listening / end of dictation / thinking) already mark those
    steps. In that case nothing is spoken and only the assistant's own replies
    (and real messages such as errors) are heard.
    """
    if assistant_uses_titan_tts():
        return
    speak(text, interrupt=interrupt)


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
