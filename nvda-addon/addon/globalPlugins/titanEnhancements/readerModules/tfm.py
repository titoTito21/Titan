# -*- coding: utf-8 -*-
"""The Titan file manager.

Read out of `data/applications/TFM/gui.py`: three lists, each named by the
application itself (`SetName`) - "File list", "Left panel", "Right panel" -
with the columns Name / Date modified / Type, and a frame titled with the
folder it is showing.

The Type column is what makes this worth writing down: it already holds the
application's own word for what a row is, in the user's own language, so
the row can be read as "readme.txt, Text file" without one translated noun
being written here.
"""

MODULE = {
    'id': 'tfm',
    'label': 'File Manager',
    'match': {'titan': 'tfm'},
    # The window's title IS the folder, so a title that has changed is the
    # user having moved - the one thing no reader can notice on its own,
    # because the focus never leaves the list.
    'title_is_a_place': True,
    'lists': [
        {'match': {'columns': ['Type']},
         'kind_column': 'Type', 'noun': 'file'},
        {'match': {'columns': ['Typ']},
         'kind_column': 'Typ', 'noun': 'file'},
        # The floor: a list of this application's whose columns are named
        # in a language neither line above knows.
        {'match': {}, 'noun': 'file'},
    ],
    'live': [
        {'match': {'role': 'STATUSBAR'}, 'politeness': 'polite'},
    ],
}
