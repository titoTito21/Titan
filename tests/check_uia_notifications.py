# -*- coding: utf-8 -*-
"""Prove Titan Access says a UI Automation notification, live.

    python tests/check_uia_notifications.py

The real engine, with its speech replaced by a recorder, and beside it
`tests/uia_notification_source.py` - a window of its own that answers
WM_GETOBJECT with a provider and raises `UiaRaiseNotificationEvent`, the
way a program tells a reader something happened without moving the focus.
An important notification must interrupt, an ordinary one must queue, and
the same words twice inside a second must be said once.
"""

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_titan_access_live as live                      # noqa: E402

SOURCE = os.path.join(HERE, 'uia_notification_source.py')


def main():
    engine = live.start_engine()
    listener = getattr(engine, 'notifications', None)
    print('listener:', listener.report() if listener else None, flush=True)
    failures = []
    if listener is None or not listener.notifications_on:
        failures.append('the engine is not listening for notifications')
    try:
        for text, kind, processing in (('Skopiowano do schowka', 2, 0),
                                       ('Nowa wiadomość od Ani', 0, 3),
                                       ('Nowa wiadomość od Ani', 0, 3)):
            live.mark('raise %r (processing %d)' % (text, processing))
            subprocess.call([sys.executable, SOURCE, text, str(kind),
                             str(processing)])
            time.sleep(0.5)
    finally:
        engine.stop()
    spoken = [row for row in live.said if row[1] != 'MARK']
    texts = [row[2] for row in spoken]
    print('spoken:', texts, flush=True)
    if 'Skopiowano do schowka' not in texts:
        failures.append('the important notification was not said')
    if texts.count('Nowa wiadomość od Ani') != 2:
        failures.append('the queued notification was said %d times, not 2'
                        % texts.count('Nowa wiadomość od Ani'))
    kinds = {row[2]: row[1] for row in spoken}
    if kinds.get('Skopiowano do schowka') == 'q':
        failures.append('an important notification did not interrupt')
    if kinds.get('Nowa wiadomość od Ani') not in ('q', None):
        failures.append('an ordinary notification interrupted')
    if listener is not None:
        print('counts:', listener.report(), flush=True)
    if failures:
        print('FAILED:', '; '.join(failures))
        return 1
    print('OK: notifications reach the reader, important ones interrupt')
    return 0


if __name__ == '__main__':
    sys.exit(main())
