# -*- coding: utf-8 -*-
"""tReminder.

`data/applications/tReminder/reminder.py`: Nazwa / Opis / Data / Godzina /
Priorytet - five columns, which is exactly the case a reader saying only
the first one throws away: a reminder is its time.
"""

MODULE = {
    'id': 'reminder',
    'label': 'Reminders',
    'match': {'titan': 'reminder'},
    'lists': [{'match': {}, 'noun': 'reminder'}],
}
