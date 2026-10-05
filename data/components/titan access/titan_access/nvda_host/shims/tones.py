# -*- coding: utf-8 -*-
"""NVDA's `tones`: a beep through Titan Access's own tone player."""


def beep(hz, length, left=50, right=50, isSpeechBeepCommand=False):
    try:
        from titan_access.engine import get_engine
        sound = getattr(get_engine(), 'sound', None)
        pan = (float(right) - float(left)) / 100.0
        if sound is not None and hasattr(sound, 'play_tone'):
            sound.play_tone(float(hz), int(length), pan=pan)
    except Exception:                                # noqa: BLE001
        pass


def initialize():
    pass


def terminate():
    pass


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
