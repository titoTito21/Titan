# -*- coding: utf-8 -*-
"""tNotes.

`data/applications/tNotes/notes.py`: one list called "Notes list" with Note
title / Date created / Date modified, and a row that is either a note or a
folder - which the columns do NOT say. So the noun is the floor here, and
the window's title is the folder the user is in.
"""

MODULE = {
    'id': 'tnotes',
    'label': 'Notes',
    'match': {'titan': 'tnotes'},
    'title_is_a_place': True,
    'lists': [{'match': {}, 'noun': 'note'}],
}
