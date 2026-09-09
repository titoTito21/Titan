# -*- coding: utf-8 -*-
"""Ask the NVDA that is really running what the add-on is really doing.

    python nvda-addon/tests/check_live_nvda.py

The suite proves the parts with no NVDA under it, which is why it can be
run anywhere - and it is exactly why it cannot answer the questions that
have cost this add-on the most. Every one of those was found by driving
the live thing and by nothing else: an announcement Titan sent and NVDA
never spoke, a capability answered so slowly that Titan cached an empty
one, a script installed where the Input Gestures dialog does not look.

So this joins Titan's own Action Bus as a client, waits for NVDA's add-on
to appear on it, and asks. Titan does not have to be running: the bus is
started here, and the add-on connects to whatever is listening.

Nothing here changes anything. It reads.
"""

import json
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

WAIT = 60.0


def _say(line=''):
    try:
        print(line)
    except UnicodeEncodeError:                       # a console that cannot
        print(str(line).encode('ascii', 'replace').decode('ascii'))


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                # noqa: BLE001
        pass
    from src.titan_core.actions import bus
    from src.titan_core import titan_actions

    # **Two servers on one pipe name is not an error, it is a SPLIT bus.**
    # Windows lets any number of processes create instances of the same
    # named pipe, and a client is handed whichever instance is free - so
    # starting a bus here while Titan (or a forgotten copy of this check)
    # is already running does not fail: half the add-ons join one and half
    # join the other, and each side reports the other's peers as absent.
    # An hour went into that once. It is checked for rather than warned
    # about, because the symptom is "the add-on is not there" and nothing
    # in it points here.
    other = titan_actions.PipeChannel.connect(titan_actions.PIPE_NAME)
    if other is not None:
        other.close()
        _say('Something is already listening on ' + titan_actions.PIPE_NAME
             + '.')
        _say('That is Titan itself, or a copy of this check that is still '
             'running. Close it first: two servers on one pipe name split '
             'the bus in half and each side reports the other half missing.')
        return 1

    # A client joining is announced out loud by Titan, and this is a check
    # rather than a program the user opened.
    bus._announce_client = lambda *_a, **_k: None
    bus.start()
    time.sleep(0.5)
    began = time.time()
    while time.time() - began < WAIT and bus.get_peer('nvda') is None:
        time.sleep(0.5)
    peer = bus.get_peer('nvda')
    if peer is None:
        _say('No NVDA add-on joined in %d seconds.' % WAIT)
        _say('Is NVDA running, and is Titan enhancements installed and on?')
        bus.stop()
        return 1
    _say('NVDA joined: pid %s, %d actions declared.'
         % (getattr(peer, 'pid', '?'), len(getattr(peer, 'actions', []) or [])))

    def ask(call, **args):
        ok, answer = bus.invoke('nvda', call, args, timeout=20.0)
        if not ok:
            return None
        if isinstance(answer, str):
            try:
                return json.loads(answer)
            except ValueError:
                return answer
        return answer

    problems = []

    able = ask('capabilities') or {}
    _say('')
    _say('--- what it says it can take')
    _say('  synthesizer: %s (%s channels)'
         % (able.get('synth') or '?', able.get('channels')))
    for name in ('announce', 'segments', 'position', 'position_marker',
                 'pitch', 'rate', 'volume', 'braille', 'replaces_focus',
                 'dialog_kind', 'state_suffix'):
        _say('  %-16s %s' % (name, able.get(name)))
    if able.get('problem'):
        _say('  problem: %s' % able['problem'])
    if not able.get('announce'):
        problems.append("Titan's announcements are switched off in the "
                        "add-on, so Titan falls back to speaking through "
                        "accessible_output3. That is the switch working, "
                        "not a fault - but nothing structured arrives.")
    if not able.get('position'):
        problems.append('The voice cannot be placed: %s'
                        % (able.get('problem') or 'no reason given'))

    settings = ask('settings') or {}
    reading = settings.get('reading') or {}
    _say('')
    _say('--- what it has really done')
    for name in ('titan_coordinates', 'can_mute', 'can_pitch', 'can_place',
                 'three_tones', 'replaced', 'placed', 'semantic',
                 'windows_semantic', 'cursor_sounds', 'bindable'):
        if name in reading:
            _say('  %-18s %s' % (name, reading[name]))
    if reading.get('why_not_placed'):
        _say('  why not placed: %s' % reading['why_not_placed'])
    known = reading.get('applications')
    if known is not None:
        _say('  Titan applications it can recognise by their window: %s'
             % (', '.join(known) if known else '(none - is Titan running?)'))
    if reading.get('bindable') == 0:
        problems.append('No Titan action is bindable. Ask Titan what it can '
                        'do (the Titan menu, or NVDA+alt+t) once Titan is '
                        'running.')
    if reading.get('can_place') and not reading.get('placed'):
        problems.append('The voice CAN be placed and nothing has been placed '
                        'yet. Inside Titan that needs "Place the voice where '
                        'the control is"; anywhere else it needs the second '
                        'switch under it, which starts off. Then move the '
                        'focus about and run this again.')

    where = ask('context') or {}
    _say('')
    _say('--- what it can see right now')
    if not where.get('available'):
        _say('  it could not answer: %s' % where.get('why'))
        problems.append('NVDA did not answer what it can see.')
    else:
        focus = where.get('focus') or {}
        _say('  application: %s' % (focus.get('app') or '?'))
        _say('  window:      %s' % (focus.get('window') or '?'))
        _say('  focus:       %s (%s)' % (focus.get('name') or '',
                                         focus.get('role') or ''))

    said = ask('describe') or {}
    _say('')
    _say('--- how it would read that control')
    if said.get('segments'):
        for text, tone in said['segments']:
            _say('  %+3s  %s' % (tone if isinstance(tone, (int, float))
                                 else tone, text))
    else:
        _say('  nothing: %s' % (said.get('why') or 'no control'))
    _say('  in a Titan window: %s' % said.get('in_titan'))

    _say('')
    if problems:
        _say('--- worth looking at')
        for problem in problems:
            _say('  * %s' % problem)
    else:
        _say('Nothing looks wrong.')
    bus.stop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
