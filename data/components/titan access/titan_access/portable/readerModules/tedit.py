# -*- coding: utf-8 -*-
"""tEdit.

`data/applications/tEdit/tedit.py` titles itself "<file> - TEdit", so the
title says which document this is - and it changes when the user opens or
saves one, which is a move nothing else reports.
"""

MODULE = {
    'id': 'tedit',
    'label': 'Text Editor',
    'match': {'titan': 'tedit'},
    'title_is_a_place': True,
    'live': [{'match': {'role': 'STATUSBAR'}, 'politeness': 'polite'}],
}
