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


#: How long any one check may take. This whole self-test is asked over the
#: bus and answered on NVDA's own main thread, so a check that takes ten
#: seconds is ten seconds of a reader that has stopped answering - which
#: is exactly how it read from the outside: "the application
#: disconnected", about an NVDA that was perfectly alive and busy walking
#: windows. A check that freezes the reader it is checking is worse than
#: no check at all.
BUDGET = 6.0


def _try(name, work):
    """One check. ``{name, ok, said}`` - never raises, never hangs.

    It never raises because a check that takes the harness down tells you
    about one thing and hides the rest; it never hangs because the harness
    runs inside the thing being checked.
    """
    started = time.time()
    done, answer = _budgeted(work, BUDGET,
                             (False, 'gave up after %g seconds - it is not '
                                     'broken, it is slower than this check '
                                     'may wait' % BUDGET))
    try:
        ok, said = answer
    except Exception:                                # noqa: BLE001
        ok, said = False, str(answer)
    return {'check': name, 'ok': bool(ok), 'said': str(said),
            'ms': int((time.time() - started) * 1000),
            'gave_up': not done}


# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #
#: What every check that is ABOUT the window in front says when there is
#: no window in front. Not a failure: it is a true answer about the
#: machine, and four checks going red over one environmental fact - the
#: desktop showing, the screen locked, a window closing as this ran -
#: teaches people to ignore the whole report. The same discipline the
#: anchoring check already carries.
NO_WINDOW = ('there is no window in front to look at, so there is nothing '
             'here to read - not a fault')

# GetCursorInfo's flags. 0 is "hidden", 2 is CURSOR_SUPPRESSED - Windows
# saying the pointer is put away because the user is on touch or pen. Either
# way there is no cursor image to name, which is a machine with nothing to
# test here rather than anything wrong: a guest read on such a machine simply
# has no pointer to follow.
CURSOR_SHOWING = 0x1
CURSOR_SUPPRESSED = 0x2
NO_POINTER = ('the pointer is put away (Windows says {why}), so there is no '
              'cursor image to name - not a fault')


def _no_window():
    """Whether there is really no foreground window at all.

    Asked of NVDA and of Windows, because they can disagree: NVDA answers
    about the object it is tracking and Windows about the handle, and a
    window that is closing is briefly one and not the other.
    """
    try:
        import api
        if api.getForegroundObject() is not None:
            return False
    except Exception:                                # noqa: BLE001
        pass
    try:
        import ctypes
        ctypes.windll.user32.GetForegroundWindow.restype = ctypes.c_void_p
        return not int(ctypes.windll.user32.GetForegroundWindow() or 0)
    except Exception:                                # noqa: BLE001
        return True


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
    if not hwnd and _no_window():
        return True, NO_WINDOW
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
        if _no_window():
            return True, NO_WINDOW
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
        return True, NO_WINDOW
    found = wa.controls(window)
    if not found:
        if _no_window():
            return True, NO_WINDOW
        # A window that IS there and lists nothing is a real answer about
        # a real window - a menu, or a window that exposes nothing - so it
        # says which of the two it is rather than being counted as broken.
        return True, ('the window in front lists no controls at all, which '
                      'is what the recognised-screen review is for')
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
    note = {}
    again = anchors.find(anchor, note)
    if again is None:
        return False, ('the control was anchored as %s and could NOT be '
                       'found again - a marker made here would not come '
                       'back to it (%s)'
                       % (anchor.get('kind'), note.get('why') or 'no reason'))
    return True, 'anchored as %s and found again' % anchor.get('kind')


def _find_control():
    from . import findControl
    rows = findControl.controls()
    if not rows:
        if _no_window():
            return True, NO_WINDOW
        return True, ('the window in front offers no controls to search, '
                      'which is a true answer about it')
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
    # **An idle watch has to say why it is idle.** This printed 'running' or
    # 'idle' and nothing else, so the one thing a reader needs in order to do
    # anything about it - the switch is off, or there is nothing to watch -
    # reached nobody, and `_state['why']` was a field nothing delivered.
    found = monitors.report()
    how = 'running'
    if not found['running']:
        how = 'idle'
        if found.get('why'):
            how += ' (%s)' % found['why']
    return True, ('%d watched, %d of them readable right now, watch %s; '
                  'here is %r, watchable by %s%s'
                  % (len(rows), read, how,
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
    note = {}
    nodes = virtualWindow.nodes_of(window, note)
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
    return True, ('%d controls in %d ms%s, mostly %s; %d of the %d '
                  'quick-navigation letters find something here (%s); '
                  'first %r%s'
                  % (len(nodes), note.get('ms') or 0,
                     (' (ran out of %s)' % note['ran_out'])
                     if note.get('ran_out') else '',
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
    import time
    # **A budget, because this runs on NVDA's own thread.** Walking a
    # window is a call into another process per node, and walking twelve
    # of them took long enough that NVDA stopped answering the bus and the
    # whole self-test came back as "the application disconnected". A check
    # that freezes the reader it is checking is worse than no check: the
    # add-on's own semantic layer carries exactly this rule, and this
    # ignored it.
    BUDGET = 1.5
    deadline = time.time() + BUDGET
    best, where, walked, took = 0, '', 0, 0.0
    try:
        windows = windowsAndActions.windows()
    except Exception:                                # noqa: BLE001
        return ''
    for label, obj in (windows or [])[:6]:
        if time.time() > deadline:
            break
        started = time.time()
        try:
            count = len(virtualWindow.nodes_of(obj))
        except Exception:                            # noqa: BLE001
            continue
        walked += 1
        if count > best:
            # **Timed, because this is what the user waits for.** Walking a
            # window is a call into another process per node, and how long
            # that takes on a rich window is the difference between a mode
            # that opens and one that appears to hang.
            best, where, took = count, str(label), time.time() - started
    if not walked:
        return ''
    return ('; across %d open windows the richest is %s with %d controls '
            'in %d ms'
            % (walked, where.split(' (')[0], best, int(took * 1000)))


def _budgeted(work, seconds, otherwise):
    """Run something on a thread and give up on it. ``(done, answer)``.

    The self-test is asked over the bus and answered on NVDA's own main
    thread, so anything in it that can take seconds has to be able to be
    abandoned - or a check that is merely slow reads as a reader that has
    crashed.
    """
    import threading
    box = {}

    def run():
        try:
            box['answer'] = work()
        except Exception as error:                   # noqa: BLE001
            box['answer'] = (False, '%s: %s' % (type(error).__name__, error))
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(seconds)
    if 'answer' not in box:
        return False, otherwise
    return True, box['answer']


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


def _widgets():
    """A Titan widget, walked the way the widget review walks one.

    **It puts the cursor back.** The widget's cursor is Titan's own and
    the user may be sitting on it, so this moves down and then up again -
    and says so, because a check that quietly moved something would be a
    check nobody should run while working.
    """
    from . import titan
    from .link import LINK
    if not LINK.connected():
        return True, 'Titan is not running, so it has no widgets'
    ok, rows = titan.widgets()
    if not ok:
        return False, str(rows)
    if not rows:
        return True, 'Titan has no widgets'
    walkable = [row for row in rows
                if str(row.get('type') or '') == 'grid']
    if not walkable:
        return True, ('%d widgets, none of them a grid - nothing to walk'
                      % len(rows))
    name = str(walkable[0].get('id') or walkable[0].get('name') or '')
    ok, first = titan.read_widget(name)
    if not ok:
        return False, 'could not read %s: %s' % (name, first)
    ok, moved = titan.move_widget(name, 'down')
    if not ok:
        return False, 'could not move in %s: %s' % (name, moved)
    titan.move_widget(name, 'up')
    ok, back = titan.read_widget(name)
    where = 'put back' if ok and back == first else 'NOT put back'
    if moved == first:
        return True, ('%d widgets, %d walkable; %s has one element only '
                      '(%s)' % (len(rows), len(walkable), name, first[:40]))
    return True, ('%d widgets, %d walkable; %s moved %r -> %r, cursor %s'
                  % (len(rows), len(walkable), name, first[:30],
                     moved[:30], where))


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


def _cursor_flags():
    """``GetCursorInfo``'s flags, or None when the call itself failed.

    Kept apart from :func:`guest._cursor_info`, which answers the handle and
    the place and deliberately nothing else - what the flags are FOR is
    telling "there is no pointer just now" from "Windows would not say".
    """
    try:
        import ctypes

        class _INFO(ctypes.Structure):
            _fields_ = [('cbSize', ctypes.c_uint),
                        ('flags', ctypes.c_uint),
                        ('hCursor', ctypes.c_void_p),
                        ('x', ctypes.c_long), ('y', ctypes.c_long)]
        info = _INFO()
        info.cbSize = ctypes.sizeof(_INFO)
        if not ctypes.windll.user32.GetCursorInfo(ctypes.byref(info)):
            return None
        return int(info.flags)
    except Exception:                                # noqa: BLE001
        return None


def _guest_cursor():
    """The whole guest chain, on whatever window is in front.

    **The part that could not be tested any other way.** A cursor inside a
    guest is one the virtual machine built from the guest's own bitmap, so
    it has a handle nobody has ever seen and comparing handles - which is
    what naming a cursor has always done - answers nothing at all. Here the
    current pointer is COPIED, which gives exactly that: a handle that is
    nobody's, showing a picture that is somebody's. Naming the copy is
    naming a guest's cursor.
    """
    import ctypes
    import time
    from . import guest
    from . import iconNames
    from . import localOcr
    try:
        user32 = ctypes.windll.user32
        user32.CopyIcon.restype = ctypes.c_void_p
    except Exception as error:                       # noqa: BLE001
        return False, 'no user32: %s' % error
    handle, x, y = guest._cursor_info()
    if not handle:
        # Windows answering "there is no cursor right now" is an answer, and
        # a different thing from Windows refusing to answer. Reported as a
        # failure it sent the reader looking for a bug in GetCursorInfo on a
        # machine that was merely on touch input - and a check that fails for
        # a reason the code handles correctly is one people learn to ignore.
        flags = _cursor_flags()
        if flags is not None and not flags & CURSOR_SHOWING:
            why = ('it is suppressed for touch or pen input'
                   if flags & CURSOR_SUPPRESSED else 'it is hidden')
            return True, NO_POINTER.format(why=why)
        return False, 'Windows would not say what the pointer is'
    by_handle = iconNames.cursor_now()
    copy = int(user32.CopyIcon(ctypes.c_void_p(handle)) or 0)
    if not copy:
        return False, 'the pointer could not be copied'
    started = time.time()
    try:
        by_picture = guest.shape_of(copy)
    finally:
        try:
            user32.DestroyIcon(ctypes.c_void_p(copy))
        except Exception:                            # noqa: BLE001
            pass
    drawing = int((time.time() - started) * 1000)
    if by_handle and by_picture != by_handle:
        return False, ('a guest\'s cursor would be named %r where the same '
                       'picture by handle is %r' % (by_picture, by_handle))
    said = ['pointer %r by handle, %r by picture (%d ms)'
            % (by_handle or '', by_picture or '', drawing)]
    # And the other half: the strip the pointer is on, read for real.
    ready, why = localOcr.available()
    if not ready:
        said.append('no recogniser: %s' % why)
        return True, '; '.join(said)
    try:
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        hwnd = int(user32.GetForegroundWindow() or 0)
    except Exception:                                # noqa: BLE001
        hwnd = 0
    if not hwnd:
        if _no_window():
            return True, '; '.join(said + [NO_WINDOW])
        return False, 'no foreground window'
    where = guest.strip_for(hwnd, y)
    if where is None:
        said.append('that window has no place on the screen')
        return True, '; '.join(said)
    started = time.time()
    words = guest.words_at(hwnd, y)
    took = int((time.time() - started) * 1000)
    said.append('the pointer\'s row: %r in %d ms (strip %d by %d)'
                % (words[:48], took, where[2], where[3]))
    said.append('would say %r' % guest.sentence(words, by_picture)[:60])
    return True, '; '.join(said)


def _guest_windows():
    """Every virtual machine's guest screen that is open, by window handle.

    Found by CLASS rather than by what is in front, because that is the one
    question that can be answered at any moment: a guest is being read
    correctly or it is not, and waiting until the user happens to be looking
    at it is how a reading fault goes unnoticed for a week.

    **The child, not the frame.** A virtual machine's frame carries a menu
    bar, a tab strip and a status line of its own - the host's interface,
    which a reader reads properly already - and paints the guest onto a
    child of its own (`MKSEmbedded` and its kind). Reading the frame is how
    a guest reading comes back with "File Machine View" at the top of
    somebody's installer.
    """
    import ctypes
    from . import surface
    user32 = ctypes.windll.user32
    frames = []
    displays = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def each_child(handle, _param):
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(handle, name, 256)
        if (str(name.value or '') in surface.VM_DISPLAY_CLASSES
                and user32.IsWindowVisible(handle)):
            # VMware keeps a SPARE console: two `MKSEmbedded` children of
            # one frame, the same size, at the same place, one of them
            # invisible - and the invisible one draws nothing, so a capture
            # of it is refused and the guest reads as empty. Measured here,
            # along with a parked Remote Desktop `IHWindowClass` at the full
            # size of the screen, which is what "biggest wins" chose.
            displays.append(int(handle))
        return True

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def each_top(handle, _param):
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(handle, name, 256)
        if (str(name.value or '') in surface.VM_CLASSES
                and user32.IsWindowVisible(handle)):
            frames.append(int(handle))
            try:
                user32.EnumChildWindows(handle, each_child, None)
            except Exception:                        # noqa: BLE001
                pass
        return True

    try:
        user32.EnumWindows(each_top, None)
    except Exception:                                # noqa: BLE001
        return []

    def area(handle):
        rect = _rect_of(handle)
        return 0 if rect is None else rect[2] * rect[3]

    # Biggest first, and a display child before the frame that holds it.
    ordered = sorted(set(displays), key=area, reverse=True)
    ordered += [one for one in sorted(set(frames), key=area, reverse=True)
                if one not in displays]
    return [one for one in ordered if area(one) > 0]


def _rect_of(hwnd):
    import ctypes
    from ctypes import wintypes
    rect = wintypes.RECT()
    try:
        if not ctypes.windll.user32.GetWindowRect(ctypes.c_void_p(int(hwnd)),
                                                 ctypes.byref(rect)):
            return None
    except Exception:                                # noqa: BLE001
        return None
    return (rect.left, rect.top, rect.right - rect.left,
            rect.bottom - rect.top)


def _guest_screen():
    """A guest's whole screen, read for real, with the highlight found.

    **This is the check that answers "does it read the virtual machine".**
    The pointer check above proves the cursor half; this proves the half
    that matters when somebody is installing an operating system in a
    guest - the picture, the words in it, and which row the arrow keys are
    on - and it does it without the user having to be looking at the guest
    when it runs.
    """
    import time
    from . import guest
    from . import localOcr
    windows = _guest_windows()
    if not windows:
        return True, 'no virtual machine is open, so there is nothing to read'
    hwnd = windows[0]
    rect = _rect_of(hwnd)
    if rect is None or rect[2] < 64 or rect[3] < 64:
        return False, 'the guest\'s window has no usable place on the screen'
    said = ['guest window %d, %d by %d' % (hwnd, rect[2], rect[3])]
    started = time.time()
    picture = localOcr.from_window(hwnd, rect[2], rect[3])
    said.append('its own picture %s in %d ms'
                % ('came back' if picture is not None else 'REFUSED',
                   (time.time() - started) * 1000))
    if picture is None:
        why = (localOcr.report().get('capture') or {}).get('why')
        return False, '; '.join(said + [why or 'no reason was recorded'])
    ready, why = localOcr.available()
    if not ready:
        return True, '; '.join(said + ['no recogniser: %s' % why])
    started = time.time()
    reading = localOcr.read(rect[0], rect[1], rect[2], rect[3], hwnd=hwnd)
    took = int((time.time() - started) * 1000)
    if reading is None or not reading:
        said.append('read nothing in %d ms (%s)'
                    % (took, localOcr.report().get('why') or 'no reason given'))
        return False, '; '.join(said)
    rows = reading.rows()
    said.append('%d lines in %d ms' % (len(rows), took))
    said.append('first: %r' % ' | '.join(row[0] for row in rows[:3])[:80])
    said.append('highlighted: %r' % (guest.selected_in(reading) or ''))
    return True, '; '.join(said)


def _touch_gestures():
    """How NVDA spells a touch gesture, and how this add-on names one.

    **The one thing that could be asked without a finger.** Every earlier
    touchpad fault was found by a real drag; this one is a NAME, and a name
    can be compared with the names NVDA itself is bound to. The live log said
    `first gesture: ts(TouchMode.OBJECT):hoverdown` while every binding in
    NVDA reads `ts(object):...`, so nothing this pad emitted could ever have
    run a script - and the counters said 539 gestures, which looked like a
    pad that worked.
    """
    from . import trackpad
    found = trackpad.report()
    said = ['contacts %d, gestures %d, ran %d, unbound %d, failed %d'
            % (found.get('contacts', 0), found.get('gestures', 0),
               found.get('ran', 0), found.get('unbound', 0),
               found.get('failed', 0))]
    if not found.get('on'):
        said.append('the pad is not being read (%s)'
                    % (found.get('why') or 'the setting is off'))
    # What NVDA's own bindings look like: the answer this rests on.
    spellings = set()
    try:
        import inputCore
        maps = [getattr(inputCore.manager, 'userGestureMap', None)]
        for module in (getattr(inputCore, 'manager', None),):
            maps.append(getattr(module, 'localeGestureMap', None))
        for one in maps:
            entries = getattr(one, '_map', None) or {}
            for key in entries:
                text = str(key)
                if text.startswith('ts(') or text.startswith('ts:'):
                    spellings.add(text.split(':')[0])
    except Exception as error:                       # noqa: BLE001
        said.append('NVDA would not say how it binds touch: %s' % error)
    # And what a gesture of ours would be called, asked of NVDA's own class.
    named = ''
    try:
        import touchHandler
        mode = trackpad._mode()
        plain = str(getattr(mode, 'value', mode))
        named = 'the mode is %r and its value is %r' % (str(mode), plain)
        if str(mode) != plain:
            named += ' - so the value is what goes in'
    except Exception as error:                       # noqa: BLE001
        named = 'the mode could not be read: %s' % error
    said.append(named)
    if spellings:
        said.append('NVDA binds ' + ', '.join(sorted(spellings)[:4]))
    chose = found.get('mode_as') or 'not decided yet (no gesture yet)'
    said.append('this add-on passes the mode as: %s' % chose)
    return True, '; '.join(said)


CHECKS = (
    ('local OCR', _local_ocr),
    ('the touchpad\'s gestures', _touch_gestures),
    ('the guest\'s screen', _guest_screen),
    ('the guest\'s pointer', _guest_cursor),
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
    ('the widgets', _widgets),
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
