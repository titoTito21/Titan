# -*- coding: utf-8 -*-
"""Run the add-on's own features, inside the NVDA that is really running.

Every other check in this repository asks a question a stand-in can answer:
does this function return the right thing, does that module import, is every
string translated. All of them passed while the local recogniser returned an
empty reading for every window on the machine - because the stand-in was
built in the shape the code EXPECTED rather than the shape NVDA really
hands back, so the test agreed with the bug.

This is the other kind. It runs inside the live NVDA, uses the real
`contentRecog`, the real object tree and the real stores, and reports what
actually happened. It is reachable over the Action Bus (`selftest`), so it
can be asked from outside without the user pressing anything - which is what
makes it a thing that gets run.

**It changes nothing and spends nothing.** It reads; it does not click, type,
press a control, send anything to a provider or write to any of the stores.
The one thing it does that costs anything at all is a local recognition of
the foreground window, which is a screenshot and Windows' own engine.
"""

import time

from . import compat


def _try(name, work):
    """One check. ``{name, ok, said}`` - and never raises, because a check
    that takes the harness down tells you about one thing and hides the
    rest."""
    started = time.time()
    try:
        ok, said = work()
    except Exception as error:                       # noqa: BLE001
        ok, said = False, '%s: %s' % (type(error).__name__, error)
    return {'check': name, 'ok': bool(ok), 'said': str(said),
            'ms': int((time.time() - started) * 1000)}


# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #
def _local_ocr():
    """The one that was broken, and the one a stand-in could not catch."""
    from . import localOcr
    ready, why = localOcr.available()
    if not ready:
        return False, why
    try:
        import ctypes
        ctypes.windll.user32.GetForegroundWindow.restype = ctypes.c_void_p
        hwnd = int(ctypes.windll.user32.GetForegroundWindow() or 0)
    except Exception as error:                       # noqa: BLE001
        return False, 'no foreground window: %s' % error
    if not hwnd:
        return False, 'no foreground window'
    reading = localOcr.read_window(hwnd)
    if reading is None:
        return False, localOcr.report().get('why') or 'nothing came back'
    rows = reading.rows()
    if not rows:
        return False, ('the recogniser ran and the reading was empty - '
                       'check the shape of LinesWordsResult.data')
    text, rect = rows[0]
    return True, ('%d lines, first "%s" at %r, %d ms'
                  % (len(rows), text[:40], rect,
                     localOcr.report().get('ms', 0)))


def _ocr_review():
    from . import localOcr
    from . import ocrReview
    ready, why = localOcr.available()
    if not ready:
        return False, why
    ok, said = ocrReview.start()
    if not ok:
        return False, said
    try:
        ocrReview.move_line(1)
        found = ocrReview.here()
        if found is None:
            return False, 'the cursor is on nothing'
        text, rect = found
        if not rect or rect[2] <= 0:
            return False, 'the cursor has no place on the screen to click'
        return True, 'walked to "%s" at %r' % (text[:40], rect)
    finally:
        ocrReview.stop()


def _controls():
    from . import windowsAndActions as wa
    window = wa.foreground()
    if window is None:
        return False, 'there is no window in front'
    found = wa.controls(window)
    if not found:
        return False, 'nothing in the window in front could be listed'
    with_verbs = [row for row in found if row['actions']]
    return True, ('%d controls, %d of them offering an action; first "%s"'
                  % (len(found), len(with_verbs), found[0]['label'][:40]))


def _anchor():
    """A control remembered and found again - what the markers, the
    monitors, the journal and the procedures all rest on."""
    from . import anchors
    try:
        import api
        obj = api.getFocusObject()
    except Exception as error:                       # noqa: BLE001
        return False, 'no focus: %s' % error
    if obj is None:
        return False, 'NVDA is not reporting a focus'
    anchor = anchors.anchor_for(obj)
    if anchor is None:
        # **Not a failure.** Some controls genuinely have nothing about them
        # that would still be true next time, and the right behaviour there
        # is to refuse - a marker on this control would be refused too, and
        # the user would be told so. A check that goes red for the correct
        # answer is a check people learn to ignore.
        return True, ('this control has nothing stable to be remembered by, '
                      'so marking or watching it would be refused - which '
                      'is the right answer, not a fault')
    again = anchors.find(anchor)
    if again is None:
        return False, ('the control was anchored as %s and could NOT be '
                       'found again - a marker made here would not come '
                       'back to it' % anchor.get('kind'))
    return True, 'anchored as %s and found again' % anchor.get('kind')


def _find_control():
    from . import findControl
    rows = findControl.controls()
    if not rows:
        return False, 'nothing in this window to search'
    wanted = rows[0]['label'].split(',')[0].strip()
    hits = findControl.by_words(wanted, rows)
    if not hits:
        return False, 'searching for "%s" found nothing' % wanted
    return True, '"%s" found %d' % (wanted, len(hits))


def _journal():
    from . import journal
    return (True, '%d lines kept, %d of them with a way back'
            % (len(journal.lines()),
               len([row for row in journal.lines() if journal.can_go(row)])))


def _scheme():
    from . import elements
    from . import schemes
    played = []
    before = schemes.play
    schemes.play = lambda sounds: played.extend(sounds)
    try:
        said = elements._sounded([('CHECKED', 'checked')])
    finally:
        schemes.play = before
    way = schemes.way_of('CHECKED')
    return True, ('"checked" is set to %s; the reading said %r and played %d'
                  % (way, said, len(played)))


def _labels():
    from . import labels
    try:
        import api
        obj = api.getFocusObject()
    except Exception:                                # noqa: BLE001
        obj = None
    label, source = labels.applies(obj) if obj is not None else ('', '')
    return True, ('%d names kept; this control reads as %r (%s)'
                  % (labels.count(), label, source or 'its own name'))


def _monitors():
    # **Nothing is saved here.** A check that left a monitor behind would
    # be a check that changes the reader of whoever ran it, and a watch
    # thread nobody asked for.
    from . import monitors
    rows = monitors.all_monitors()
    read = 0
    for row in rows:
        if monitors._read(row) is not None:
            read += 1
    # What could be watched RIGHT NOW, which is the half a count of saved
    # monitors says nothing about: the navigator object is what a watch is
    # made from, and a progress bar is exactly the thing that has no name,
    # no strong key, and a rectangle.
    obj = monitors.here()
    if obj is None:
        return False, ('%d watched, but there is no object to make one '
                       'from - not the navigator, the focus or the '
                       'foreground window' % len(rows))
    by = 'a control' if monitors._anchor(obj) else 'its place'
    rect = monitors._rect_of(obj)
    return True, ('%d watched, %d of them readable right now, watch %s; '
                  'here is %r, watchable by %s%s'
                  % (len(rows), read,
                     'running' if monitors.report()['running'] else 'idle',
                     monitors._describe(obj), by,
                     ' and as an area' if rect and rect[2] > 0 else
                     ', with no area'))


def _speech_origins():
    from . import origin
    report = origin.report()
    if not report['wrapped']:
        return False, ('nothing is marked: %s'
                       % (report['missing'] or 'start() was never called'))
    return True, ('marking %s; seen %s'
                  % (', '.join(report['wrapped']), report['seen'] or 'none'))


def _voice():
    from . import panner
    from . import voices
    report = panner.PANNER.report()
    return True, ('synthesizer %s, place %s, classes can be heard: %s'
                  % (report.get('synth'), report.get('stream_panning'),
                     voices.can_hear_the_difference()))


def _virtual_window():
    """The window the user is in, built as a virtual window.

    Nothing is turned on and nothing is left running: the tree is walked,
    counted, and thrown away. What this is really asking is whether the
    walk answers at all in the program the user happens to be in - which
    is a different question from whether the code is right, and the only
    one a unit test cannot ask.
    """
    from . import virtualWindow
    window = virtualWindow._foreground()
    if window is None:
        return False, 'there is no window in front to walk'
    nodes = virtualWindow.nodes_of(window)
    if not nodes:
        return True, ('this window answers nothing - which is what the '
                      'recognised-screen review is for, not a fault')
    kinds = {}
    for node in nodes:
        kinds[node['role']] = kinds.get(node['role'], 0) + 1
    top = sorted(kinds.items(), key=lambda row: -row[1])[:3]
    # Quick navigation over what was really found, so a letter that
    # matches nothing on this machine is reported rather than assumed.
    reachable = [letter for letter, roles in virtualWindow.QUICK.items()
                 if any(node['role'].upper() in roles for node in nodes)]
    return True, ('%d controls, mostly %s; %d of the %d quick-navigation '
                  'letters find something here (%s); first %r%s'
                  % (len(nodes),
                     ', '.join('%s %d' % (name.lower(), count)
                               for name, count in top),
                     len(reachable), len(virtualWindow.QUICK),
                     ''.join(sorted(reachable)) or 'none',
                     nodes[0]['name'] or nodes[0]['value'],
                     _richest_window()))


def _richest_window():
    """The same walk over every window that is really open, read only.

    The window the user happens to be in may be a terminal with five
    controls in it, which is a true answer and thin evidence. This walks
    the others as well - nothing is focused, shown or changed - so the
    check says whether the walk copes with a real, complicated window
    rather than only with a simple one.
    """
    from . import virtualWindow
    from . import windowsAndActions
    best, where, walked = 0, '', 0
    try:
        windows = windowsAndActions.windows()
    except Exception:                                # noqa: BLE001
        return ''
    for label, obj in (windows or [])[:12]:
        try:
            count = len(virtualWindow.nodes_of(obj))
        except Exception:                            # noqa: BLE001
            continue
        walked += 1
        if count > best:
            best, where = count, str(label)
    if not walked:
        return ''
    return ('; across %d open windows the richest is %s with %d controls'
            % (walked, where.split(' (')[0], best))


def _auditory_icons():
    """Emacspeak's icons: are they there, and will NVDA really play one."""
    from . import icons
    missing = [name for name in icons.NAMES if not icons.path_of(name)]
    if missing:
        return False, ('%d of %d icons have no sound: %s'
                       % (len(missing), len(icons.NAMES),
                          ', '.join(missing[:6])))
    played = icons.try_it('select-object')
    off = [row['id'] for row in icons.described() if not row['on']]
    return bool(played), (
        '%d icons, all with a sound; one played: %s; on everywhere: %s; '
        'switched off by you: %s'
        % (len(icons.NAMES), 'yes' if played else 'NO - nvwave refused',
           'yes' if icons.everywhere() else 'no', ', '.join(off) or 'none'))


def _titan_map():
    """How much of Titan this add-on really reaches, asked of Titan.

    Not a count of what is written here: `capabilities` is Titan's own
    answer about what its bridge serves, so a Titan newer than this
    add-on is reported honestly instead of assumed.

    **It sweeps the whole add-on, not the map module.** Reading only
    `titan.py` reported 49 of 58 while nothing at all was missing - the
    other nine are asked for by `link`, `commands`, `semantics` and
    `surface`, which are just as much this add-on asking. A measurement
    that under-reports is worse than none: it invites work on a gap that
    is not there.
    """
    from . import titan
    from .link import LINK
    if not LINK.connected():
        return True, 'Titan is not running, so there is nothing to reach'
    ok, data = LINK.bridge('capabilities')
    if not ok:
        return False, 'Titan would not say what it can do: %s' % data
    calls = set(data.get('calls') or []) if isinstance(data, dict) else set()
    if not calls:
        return False, 'Titan listed no calls at all'
    asked = _asked_for()
    missing = sorted(calls - asked)
    ok, rows = titan.applications()
    ok2, bar = titan.statusbar()
    said = ('Titan serves %d calls and this asks for %d of them; '
            'applications: %s; status bar: %s'
            % (len(calls), len(calls & asked),
               len(rows) if ok else 'refused: %s' % rows,
               len(bar) if ok2 else 'refused'))
    if missing:
        return False, ('%s - NOT reached: %s'
                       % (said, ', '.join(missing)))
    return True, said + '; nothing unreached'


def _asked_for():
    """Every bridge call this add-on names, swept over its own source.

    A dotted name in any call position counts, because a call reached
    through one of this add-on's own typed helpers is still a call this
    add-on makes - matching only `bridge(` reported four in daily use as
    forgotten.
    """
    import os
    import re
    here = os.path.dirname(os.path.abspath(__file__))
    asked = set()
    for name in sorted(os.listdir(here)):
        if not name.endswith('.py'):
            continue
        try:
            with open(os.path.join(here, name), encoding='utf-8') as handle:
                text = handle.read()
        except Exception:                            # noqa: BLE001
            continue
        asked.update(re.findall(r"bridge\('([a-z_.]+)'", text))
        asked.update(re.findall(r"\(\s*'([a-z_]+\.[a-z_]+)'", text))
    return asked


def _voice_classes():
    """The classes, the named voices, and what the user has changed."""
    from . import classes
    from . import personalities
    rows = classes.described()
    changed = [row['id'] for row in rows if row['changed']]
    unlabelled = [row['id'] for row in rows if not row.get('label')]
    if unlabelled:
        return False, ('%d classes have no short name: %s'
                       % (len(unlabelled), ', '.join(unlabelled[:6])))
    wearing = {}
    for row in rows:
        name = personalities.matching(row['voice'])
        if name and name != 'plain':
            wearing[row['id']] = name
    return True, ('%d classes, %d named voices; you have changed %d (%s); '
                  'reading order %s'
                  % (len(rows), len(personalities.NAMES), len(changed),
                     ', '.join(changed[:5]) or 'none',
                     ', '.join(classes.parts_read()) or 'nothing'))


CHECKS = (
    ('local OCR', _local_ocr),
    ('screen review', _ocr_review),
    ('windows and actions', _controls),
    ('anchoring a control', _anchor),
    ('finding a control', _find_control),
    ('the journal', _journal),
    ('the sound scheme', _scheme),
    ('the names', _labels),
    ('the monitors', _monitors),
    ('speech origins', _speech_origins),
    ('the voice', _voice),
    ('the voice classes', _voice_classes),
    ('the virtual window', _virtual_window),
    ('auditory icons', _auditory_icons),
    ('all of Titan', _titan_map),
)


def run(**_kwargs):
    """Every check, in order. ``{ok, checks: [...]}``.

    Answers a dictionary rather than speaking: this is asked over the bus
    by something that wants to read it, and a harness that spoke would be
    a harness nobody could run while using the machine.
    """
    rows = [_try(name, work) for name, work in CHECKS]
    return {'ok': all(row['ok'] for row in rows), 'checks': rows,
            'failed': [row['check'] for row in rows if not row['ok']]}


def as_text(answer=None):
    """The result as a page a person reads."""
    answer = answer or run()
    lines = []
    for row in answer['checks']:
        lines.append('%s  %s  (%d ms)  %s'
                     % ('ok  ' if row['ok'] else 'FAIL',
                        row['check'], row['ms'], row['said']))
    lines.append('')
    lines.append('%d of %d passed'
                 % (len([r for r in answer['checks'] if r['ok']]),
                    len(answer['checks'])))
    return '\n'.join(lines)
