# -*- coding: utf-8 -*-
"""Dial ("TPad" / pokrętło) for Titan Access.

Python port of the C# ``InputGestures/DialManager.cs``. A rotary control toggled
with NumPad Minus: NumPad 4/6 cycle the category, NumPad 2/8 change the value /
navigate within it. Categories are filtered by the user's Dial settings.

Categories that adjust speech (Speed / Volume / Speech system / Synthesizer /
Voice) change the READER's own speech settings and apply them. The speech
system, synthesizer and voice are the three levels of `speech_systems` - the
same ones the speech system dialog (Insert+Ctrl+S), the settings page and the
walked settings offer, external NVDA add-on synthesizers included. The dial
used to cycle Titan's flat engine list on the live engine without saving,
which with an external synthesizer chosen changed nothing at all. Navigation categories (Characters / Words / Important places)
delegate to the matching subsystem.
"""

from titan_access.localization import L
from titan_access.contracts import SND_SR_CURSOR_ITEM

# Category ids (order matches the C# DialCategory enum).
CHARACTERS = "characters"
WORDS = "words"
BUTTONS = "buttons"
HEADINGS = "headings"
VOICE = "voice"
SPEECH_SYSTEM = "speechSystem"
SPEED = "speed"
VOLUME = "volume"
SYNTHESIZER = "synthesizer"
VARIANT = "variant"
IMPORTANT_PLACES = "importantPlaces"

_ALL = [CHARACTERS, WORDS, BUTTONS, HEADINGS, SPEED, VOLUME,
        SPEECH_SYSTEM, SYNTHESIZER, VOICE, VARIANT, IMPORTANT_PLACES]

# Category id -> (settings key, locale name key)
_CAT_META = {
    CHARACTERS: ("DialCharacters", "dial.cat.characters"),
    WORDS: ("DialWords", "dial.cat.words"),
    BUTTONS: ("DialButtons", "dial.cat.buttons"),
    HEADINGS: ("DialHeadings", "dial.cat.headings"),
    VOICE: ("DialVoice", "dial.cat.voice"),
    SPEECH_SYSTEM: ("DialSpeechSystem", "dial.cat.speechSystem"),
    SPEED: ("DialSpeed", "dial.cat.speed"),
    VOLUME: ("DialVolume", "dial.cat.volume"),
    SYNTHESIZER: ("DialSynthesizer", "dial.cat.synthesizer"),
    VARIANT: ("DialVariant", "dial.cat.variant"),
    IMPORTANT_PLACES: ("DialImportantPlaces", "dial.cat.importantPlaces"),
}


def category_name(cat):
    meta = _CAT_META.get(cat)
    return L(meta[1]) if meta else cat


class DialManager:
    """The dial state machine (port of DialManager.cs)."""

    def __init__(self, engine):
        self.engine = engine
        self.enabled = False
        self._categories = []
        self._index = 0
        self._voice_index = 0
        self._engine_index = 0
        self.refresh_categories()

    # ------------------------------------------------------------------ #
    def refresh_categories(self):
        s = self.engine.settings
        self._categories = [c for c in _ALL
                            if s.get_bool("Dial", _CAT_META[c][0], True)]
        if not self._categories:
            self._categories = list(_ALL)
        if self._index >= len(self._categories):
            self._index = 0

    @property
    def current(self):
        return self._categories[self._index] if self._categories else CHARACTERS

    # ------------------------------------------------------------------ #
    # Engine entry points
    # ------------------------------------------------------------------ #
    def toggle(self):
        """NumPad Minus: turn the dial on/off. Returns True (key handled)."""
        self.enabled = not self.enabled
        self.engine.play(SND_SR_CURSOR_ITEM)
        if self.enabled:
            self.refresh_categories()
            self.engine.speak("{0}, {1}".format(L("dial.tpad"),
                                                category_name(self.current)),
                              interrupt=True)
        else:
            self.engine.speak(L("dial.objectNav"), interrupt=True)
        return True

    def handle_key(self, key_name):
        """Route a NumPad key while the dial is active. Returns True if handled."""
        if key_name == "numpad6":
            return self._cycle_category(1)
        if key_name == "numpad4":
            return self._cycle_category(-1)
        if key_name == "numpad8":
            return self._change_item(False)
        if key_name == "numpad2":
            return self._change_item(True)
        return False

    # ------------------------------------------------------------------ #
    def _cycle_category(self, delta):
        if not self._categories:
            self.engine.speak(L("dial.noCategories"), interrupt=True)
            return True
        self._index = (self._index + delta) % len(self._categories)
        self.engine.play(SND_SR_CURSOR_ITEM)
        self.engine.speak(category_name(self.current), interrupt=True)
        return True

    def _change_item(self, nxt):
        cat = self.current
        if cat == SPEED:
            return self._change_speed(nxt)
        if cat == VOLUME:
            return self._change_volume(nxt)
        if cat == SPEECH_SYSTEM:
            return self._step_speech('system', nxt)
        if cat == SYNTHESIZER:
            return self._step_speech('synth', nxt)
        if cat == VOICE:
            return self._step_speech('voice', nxt)
        if cat == VARIANT:
            return self._step_speech('variant', nxt)
        if cat == CHARACTERS and self.engine.editable is not None:
            # `Navigation/PhoneticInDial`: a letter reached through the dial
            # is said phonetically (or not) as THIS setting says, whatever
            # the text-editing one says about the arrows.
            try:
                phonetic = bool(self.engine.settings.get_bool(
                    "Navigation", "PhoneticInDial", True))
            except Exception:
                phonetic = True
            self.engine.editable.phonetic_override = phonetic
            try:
                self.engine.editable.navigate_char(nxt)
            finally:
                self.engine.editable.phonetic_override = None
            return True
        if cat == WORDS and self.engine.editable is not None:
            self.engine.editable.navigate_word(nxt)
            return True
        if cat == IMPORTANT_PLACES and self.engine.important_places is not None:
            self.engine.important_places.navigate(nxt)
            return True
        if cat in (BUTTONS, HEADINGS) and self.engine.browse is not None:
            # Quick-nav by type when a browse buffer is available (web document).
            key = "b" if cat == BUTTONS else "h"
            ok = False
            try:
                ok = self.engine.browse.quick_nav_by_char(key, backward=not nxt)
            except Exception as e:
                print(f"[TitanAccess] dial quick-nav error: {e}")
            if not ok:
                self.engine.speak(L("dial.notAvailableHere"), interrupt=True)
            return True
        return True

    # ------------------------------------------------------------------ #
    # Speech-adjusting categories -> live Titan TTS
    # ------------------------------------------------------------------ #
    def _apply(self):
        """The reader's own speech, whichever system it speaks with."""
        apply_all = getattr(self.engine, 'apply_settings', None)
        if callable(apply_all):
            try:
                apply_all('dial')
                return
            except Exception as e:
                print(f"[TitanAccess] dial apply: {e}")
        if self.engine.speech is not None:
            try:
                self.engine.speech.apply_settings()
            except Exception:
                pass

    def _change_speed(self, nxt):
        s = self.engine.settings
        rate = max(-10, min(10, s.rate + (1 if nxt else -1)))
        s.rate = rate
        s.save()
        self._apply()
        percent = (rate + 10) * 5
        self.engine.speak(L("dial.speed", percent), interrupt=True)
        return True

    def _change_volume(self, nxt):
        s = self.engine.settings
        vol = max(0, min(100, s.volume + (10 if nxt else -10)))
        s.volume = vol
        s.save()
        self._apply()
        self.engine.speak(L("dial.volume", vol), interrupt=True)
        return True

    def _step_speech(self, level, nxt):
        from titan_access import speech_systems
        try:
            said = speech_systems.step(self.engine.settings, level,
                                       forward=nxt, reader=self.engine)
        except Exception as e:
            print(f"[TitanAccess] dial {level}: {e}")
            said = ''
        if not said:
            key = {'voice': "dial.noVoices",
                   'variant': "dial.noVariants"}.get(level, "dial.nothingHere")
            self.engine.speak(L(key), interrupt=True)
            return True
        self.engine.speak(str(said), interrupt=True)
        return True
