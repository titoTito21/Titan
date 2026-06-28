# -*- coding: utf-8 -*-
"""Dial ("TPad" / pokrętło) for Titan Access.

Python port of the C# ``InputGestures/DialManager.cs``. A rotary control toggled
with NumPad Minus: NumPad 4/6 cycle the category, NumPad 2/8 change the value /
navigate within it. Categories are filtered by the user's Dial settings.

Categories that adjust speech (Speed / Volume / Voice / Synthesizer) drive the
**live Titan TTS** through the engine's speech adapter -- i.e. the dial is the
sanctioned way to change Titan TTS from the reader (unlike startup, which never
imposes anything). Navigation categories (Characters / Words / Important places)
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
SPEED = "speed"
VOLUME = "volume"
SYNTHESIZER = "synthesizer"
IMPORTANT_PLACES = "importantPlaces"

_ALL = [CHARACTERS, WORDS, BUTTONS, HEADINGS, VOICE, SPEED, VOLUME,
        SYNTHESIZER, IMPORTANT_PLACES]

# Category id -> (settings key, locale name key)
_CAT_META = {
    CHARACTERS: ("DialCharacters", "dial.cat.characters"),
    WORDS: ("DialWords", "dial.cat.words"),
    BUTTONS: ("DialButtons", "dial.cat.buttons"),
    HEADINGS: ("DialHeadings", "dial.cat.headings"),
    VOICE: ("DialVoice", "dial.cat.voice"),
    SPEED: ("DialSpeed", "dial.cat.speed"),
    VOLUME: ("DialVolume", "dial.cat.volume"),
    SYNTHESIZER: ("DialSynthesizer", "dial.cat.synthesizer"),
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
        if cat == VOICE:
            return self._change_voice(nxt)
        if cat == SYNTHESIZER:
            return self._change_engine(nxt)
        if cat == CHARACTERS and self.engine.editable is not None:
            self.engine.editable.navigate_char(nxt)
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
    def _change_speed(self, nxt):
        s = self.engine.settings
        rate = max(-10, min(10, s.rate + (1 if nxt else -1)))
        s.rate = rate
        s.save()
        if self.engine.speech is not None:
            self.engine.speech.set_rate(rate)
        percent = (rate + 10) * 5
        self.engine.speak(L("dial.speed", percent), interrupt=True)
        return True

    def _change_volume(self, nxt):
        s = self.engine.settings
        vol = max(0, min(100, s.volume + (10 if nxt else -10)))
        s.volume = vol
        s.save()
        if self.engine.speech is not None:
            self.engine.speech.set_volume(vol)
        self.engine.speak(L("dial.volume", vol), interrupt=True)
        return True

    def _change_voice(self, nxt):
        sp = self.engine.speech
        voices = sp.get_voices() if sp is not None else []
        if not voices:
            self.engine.speak(L("dial.noVoices"), interrupt=True)
            return True
        self._voice_index = (self._voice_index + (1 if nxt else -1)) % len(voices)
        v = voices[self._voice_index]
        name = v.get("display_name") or v.get("name") or v.get("id") if isinstance(v, dict) else str(v)
        sp.set_voice(self._voice_index)
        self.engine.speak(str(name).split("(")[0].strip(), interrupt=True)
        return True

    def _change_engine(self, nxt):
        sp = self.engine.speech
        engines = sp.get_engines() if sp is not None else []
        if not engines:
            self.engine.speak(L("dial.noCategories"), interrupt=True)
            return True
        self._engine_index = (self._engine_index + (1 if nxt else -1)) % len(engines)
        eng = str(engines[self._engine_index])
        sp.set_engine(eng)
        self.engine.speak(eng, interrupt=True)
        return True
