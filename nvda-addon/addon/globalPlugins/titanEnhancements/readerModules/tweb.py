# -*- coding: utf-8 -*-
"""tWeb / tBrowser.

`data/applications/tWeb/web.py` titles itself "<page> - tBrowser" and keeps
a two-part status bar. A browser's status bar is the one in every program
that really is a live region: it says what is loading and where a link
goes, and it changes while the focus is somewhere else entirely.
"""

MODULE = {
    'id': 'web',
    'label': 'Web Browser',
    'match': {'titan': 'web'},
    'title_is_a_place': True,
    'live': [{'match': {'role': 'STATUSBAR'}, 'politeness': 'polite'}],
}
