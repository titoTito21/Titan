# -*- coding: utf-8 -*-
"""Titan Antivirus.

Read out of `data/applications/tAntivirus/main.py`: three report lists, each
named by the application itself - "Scan results" (File / Threat / Status /
Location), "Quarantined files" (Name / Threat / Original location / Date)
and "Finished scans" (Date / Scanned / Engine / Files / Threats) - a real
`wx.Gauge` called "Scan progress" and a status bar the application rewrites
at most every few seconds while a scan runs.

The Threat column is what makes a row worth writing down: a threat's name
IS what the row is, so a result is read "eicar.com, Win.Test.EICAR_HDB-1,
Status: Quarantined, Location: C:\\Users\\...\\Downloads" - the file, then
what it is, then what was done about it - rather than four cells in a row.
The status bar is live, polite, so "Scanned 400 of 900 files" and "Scan
finished: no threats found" are heard without leaving the list.
"""

MODULE = {
    'id': 'tantivirus',
    'label': 'Titan Antivirus',
    'match': {'titan': 'tantivirus'},
    'lists': [
        {'match': {'columns': ['Threat']}, 'kind_column': 'Threat',
         'noun': ''},
        {'match': {'columns': ['Zagrożenie']}, 'kind_column': 'Zagrożenie',
         'noun': ''},
        # History rows are scans, not threats: read plainly, column by
        # column.
        {'match': {}, 'noun': ''},
    ],
    'live': [
        {'match': {'role': 'STATUSBAR'}, 'politeness': 'polite'},
    ],
}
