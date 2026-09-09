# -*- coding: utf-8 -*-
"""tMedia.

`data/applications/tMedia/tmedia.py` and `player.py`: a list the
application names "TMedia functions", a bookmarks list, and a title that
becomes "Playing: <what>" while something is playing - which is a live
change the focus never goes near.
"""

MODULE = {
    'id': 'tmedia',
    'label': 'Media',
    'match': {'titan': 'tmedia'},
    'title_is_a_place': True,
    'lists': [{'match': {}, 'noun': ''}],
}
