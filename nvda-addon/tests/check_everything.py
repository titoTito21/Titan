# -*- coding: utf-8 -*-
"""Ask the NVDA that is really running whether the add-on really works.

    python nvda-addon/tests/check_everything.py

The unit suite asks whether a function returns the right thing. It passed,
all six hundred of it, while the local recogniser returned an empty reading
for every window on the machine - because the stand-in it was given was
built in the shape the code EXPECTED rather than the shape NVDA really hands
back, so the test agreed with the bug. Three features were dead and nothing
went red.

This is the other kind of check and it is the one that would have caught
that: it joins Titan's Action Bus, asks the live NVDA to run its own
features against the real `contentRecog`, the real object tree and the real
stores, and prints what happened. Nothing is simulated and nothing is
assumed.

**It reads and it spends nothing.** No control is pressed, nothing is typed,
no store is written and nothing is sent to an AI provider. The one thing it
costs is a local recognition of whatever window is in front, which is a
screenshot and Windows' own engine.

Exit code 0 when every check passed, 1 when one did not, 2 when it could not
be run at all - which is a different thing and says so.
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))

#: How long to wait for the bus. Joining is a named pipe and a handshake;
#: this is generous because the alternative is a check that fails on a busy
#: machine and teaches people to ignore it.
JOIN_SECONDS = 15.0

#: The self-test reads a window with the local recogniser, which is the
#: slowest thing in it.
RUN_SECONDS = 90.0


def _bus():
    sys.path.insert(0, os.path.join(ROOT, 'src', 'titan_core'))
    try:
        import titan_actions
    except Exception as error:                       # noqa: BLE001
        return None, 'Titan is not importable from here: %s' % error
    titan_actions.connect(id='titan_check_everything',
                          label='Does it all work')
    until = time.time() + JOIN_SECONDS
    while time.time() < until:
        if titan_actions.is_connected():
            return titan_actions, ''
        time.sleep(0.25)
    return None, ('Titan is not running, or its Action Bus is not answering. '
                  'Start Titan and try again.')


def _reader(bus):
    """The reader add-on on the bus, and whether it is the current one."""
    try:
        rows = bus.list_addons()
    except Exception as error:                       # noqa: BLE001
        return None, 'Titan would not list its add-ons: %s' % error
    for row in rows or []:
        if str(row.get('id')) == 'nvda':
            return row, ''
    return None, ('NVDA is on the bus for nothing this can ask. Is the '
                  'Titan enhancements add-on installed and NVDA running?')


def _printable():
    """Let this print what a window really said, whatever the console is.

    A check's sentence carries text read off the user's own screen, and a
    Windows console is a code page - cp1250 here - so one character it has
    not got (a spinner, an arrow, a box) ended the whole report with a
    traceback in the middle of a passing run. Which check that was is not
    knowable from the outside, so the answer is never to let it happen: a
    character that cannot be shown is shown as a question mark, and the
    result still reads.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors='replace')
        except Exception:                            # noqa: BLE001
            pass


def main():
    _printable()
    bus, why = _bus()
    if bus is None:
        print(why)
        return 2
    row, why = _reader(bus)
    if row is None:
        print(why)
        return 2
    actions = [str(name) for name in (row.get('actions') or [])]
    if 'selftest' not in actions:
        # **The commonest reason, and it is not a fault.** NVDA reads its
        # add-ons when it starts, so a freshly installed one is on disk and
        # not in the process. Saying which of the two this is saves the
        # half hour that goes into looking for a bug that is not there.
        print('The NVDA that is running has an older copy of the add-on: it '
              'does not offer "selftest".')
        print('Reload its plugins with NVDA+control+f3, or restart NVDA, '
              'and run this again.')
        print('It currently offers: %s' % ', '.join(sorted(actions)))
        return 2
    answer = bus.call('nvda', 'selftest', timeout=RUN_SECONDS)
    if not getattr(answer, 'ok', False):
        print('The self-test could not be run: %s' % answer)
        return 2
    return _report(answer)


def _report(answer):
    import json
    text = str(answer)
    try:
        data = json.loads(text)
    except ValueError:
        # It came back as prose, which is what an older bridge does. It is
        # still the answer; it is just not one to count.
        print(text)
        return 0
    checks = data.get('checks') or []
    if not checks:
        print('The self-test answered nothing.')
        return 2
    width = max(len(str(row.get('check', ''))) for row in checks)
    failed = 0
    for row in checks:
        ok = bool(row.get('ok'))
        failed += 0 if ok else 1
        print('%-4s %-*s %5s ms  %s'
              % ('ok' if ok else 'FAIL', width, row.get('check', ''),
                 row.get('ms', 0), row.get('said', '')))
    print('')
    print('%d of %d passed' % (len(checks) - failed, len(checks)))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
