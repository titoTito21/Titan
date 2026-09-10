# -*- coding: utf-8 -*-
"""The Titan download manager.

`data/applications/tDownloader/downloader.py`: "Download list", with File
name and Link. The link is a URL, which is a sentence on its own in the
middle of a row - so it is quietened: it is still there for the reader's
own table navigation, and it is not read on every arrow key.
"""

MODULE = {
    'id': 'tdm',
    'label': 'Download Manager',
    'match': {'titan': 'tdm'},
    'lists': [{'match': {}, 'noun': 'download',
               'quiet': ['Link do Pobrania', 'Link', 'Download link']}],
    'live': [{'match': {'role': 'PROGRESSBAR'}, 'politeness': 'polite'}],
}
