# -*- coding: utf-8 -*-
"""The ElevenLabs client.

`data/applications/elevenlabs client TCE Version/main.py`: a status bar and
a list of voices. Its status bar is where "generating" and "saved" are
said, and the focus is in the text box the whole time.
"""

MODULE = {
    'id': 'elevenlabs',
    'label': 'ElevenLabs',
    'match': {'titan': 'elevenlabs'},
    'lists': [{'match': {}, 'noun': 'voice'}],
    'live': [{'match': {'role': 'STATUSBAR'}, 'politeness': 'polite'}],
}
