# -*- coding: utf-8 -*-
"""A window that answers nothing, read as a picture - and watched.

Some programs have no accessibility at all. A Unity game draws its menu
onto a texture; an installer paints its own widgets; a program written
against a toolkit nobody wired up exposes one window and no children. A
screen reader lands on it and says the window's title, and that is the
whole of what it can say, for ever. The user knows a menu is there because
they can hear the game's own sounds, and they cannot know what is on it.

Titan has the answer to the first half already: AI OCR reads a window into
structured elements, and it is told that "a highlight means selected or
focused" - so the reading names the item the game has highlighted. This is
that, made continuous, which is the half that turns a reading into
something you can PLAY with: press down, the highlight moves, and the new
item is spoken.

**What makes it affordable is that a request is only spent when the picture
changes.** Titan's recogniser compares the new capture with the last one
and answers from the previous reading when they look alike, so a poll on a
still screen is a screenshot and a comparison - locally, in Titan, costing
nothing at a provider. That is only true when nothing is ASKED: a question
forces a fresh request every time (``recognizer.read_screen`` skips the
model only ``if previous is not None and ... and not question``). So this
never asks a question. It reads the window and looks for the highlight in
the answer itself.

**It is off until it is asked for, and it says why.** A reading sends a
picture of the user's screen to their AI provider. That is not something to
switch on for somebody, it is not something to do because a window happened
to look empty, and it is not something to do silently - so it needs the
switch, it needs a window that really answers nothing (or a reader module
that says this program is like that), and the watch is a key the user
presses.

Needs Titan running, because Titan owns the provider, the key and the
capture. Does not need Titan Access.
"""

import threading
import time

from . import compat
from . import i18n

_ = i18n.install(globals())

#: Window classes that are a drawn surface rather than an interface. Every
#: one of these is an engine that paints its own controls, so its window
#: has no children and never will.
#: Engines that paint a GAME. Every one of these has its own menu that
#: answers its own keys, and what the player needs is to be told what has
#: become highlighted as they move - not a second cursor of ours.
GAME_CLASSES = frozenset({
    'UnityWndClass', 'GLFW30', 'SDL_app', 'Godot_Engine', 'UnrealWindow',
    'LWJGL', 'GLUT', 'OgreGLWindow', 'SFML_Window', 'RenderWindow',
    'MonoGame', 'love_window', 'GameMakerWindow',
})

#: Everything else that draws its own interface: an installer that paints
#: its widgets, a program written against a toolkit nobody wired up. There
#: is no keyboard model underneath at all, so one is built out of the
#: reading and the keys walk THAT.
DRAWN_CLASSES = GAME_CLASSES

#: **A game and an inaccessible application are not the same problem, and
#: the same answer is wrong for one of them.**
#:
#: A game already has a keyboard model - its menu moves with the arrow
#: keys, and what the player cannot do is SEE which item is now
#: highlighted. Taking those keys to drive a cursor of our own would break
#: the game while appearing to help; what is wanted is to follow the
#: highlight and say it.
#:
#: An inaccessible application has no keyboard model that reaches the user
#: at all: Tab does whatever the program does with it and the reader can
#: say nothing about where it went. There, a cursor of our own IS the
#: interface, and Tab and the arrows should walk the controls that were
#: read exactly as they walk real ones.
MODE_GAME = 'game'
MODE_APPLICATION = 'application'

#: **The reading becomes the window's own interface.** Titan's AI OCR overlay
#: rebuilds every control it read as a REAL control - a wx button, a wx edit,
#: a wx check box - parented into the target's own window at the coordinates
#: of the real one. Nothing in this add-on then reads it: NVDA reads it the
#: way it reads any program's controls, because that is what they are. Tab
#: moves, the arrows move, Enter presses, and the reader announces a name, a
#: role and a state it got from Windows rather than from us.
#:
#: That is the difference between this and MODE_APPLICATION, and it is the
#: whole difference: the other one is a cursor of ours over a list of lines,
#: which is a reading you can move through; this is the application being
#: navigable, the way it would be if somebody had written a script for it.
#:
#: It is the default for anything that is not a game, and MODE_APPLICATION is
#: what it falls back to - a reading whose elements carry no rectangles can be
#: read and cannot be placed, and a window that will not adopt a child window
#: cannot wear one. Neither of those is a reason to leave the user with
#: nothing.
MODE_NATIVE = 'native'

#: **Windows' own OCR, and no model at all.**
#:
#: The reading is the words and where each line is, from the recogniser
#: built into Windows that NVDA already wraps - local, free, about a tenth
#: of a second, and nothing leaves the machine. That is enough to make a
#: drawn window navigable: the cursor is built from it and a control
#: presses itself by clicking where it was read.
#:
#: It is what MODE_NATIVE falls back to, and it is a better floor than the
#: AI list ever was: a window that will not wear controls is now read for
#: nothing rather than at a request per change.
MODE_LOCAL = 'local'

MODES = (MODE_GAME, MODE_APPLICATION, MODE_NATIVE, MODE_LOCAL)


def mode_for(obj, module=None):
    """Which of the three this window is. Never raises.

    A reader module may simply say (`"surface": {"ocr": "native"}`); the user
    may have said, per program; and otherwise the window class decides,
    because an engine that paints a game is the one thing here that can be
    recognised outright.

    A window that is not a game gets MODE_NATIVE, because that is the answer
    somebody actually wants from this: not a reading they can arrow through
    but an application they can use. MODE_APPLICATION is still reachable by
    name, and is what MODE_NATIVE falls back to when the controls cannot be
    put where the real ones are.
    """
    if module is not None:
        try:
            said = module.surface.get('ocr')
        except Exception:                            # noqa: BLE001
            said = None
        if said in MODES:
            return said
    try:
        from . import perProgram
        if perProgram.answered('surfaceGame',
                               perProgram.application_of(obj)):
            return MODE_GAME if perProgram.value('surfaceGame', obj) \
                else _not_a_game()
    except Exception:                                # noqa: BLE001
        pass
    if _text(getattr(obj, 'windowClassName', '')) in GAME_CLASSES:
        return MODE_GAME
    return _not_a_game()


def _not_a_game():
    """What a window that is not a game gets - the user's own answer.

    Which recogniser reads an unreadable window is a real choice with a real
    cost on one side of it, so it is a setting rather than a decision made
    for somebody: Windows' own is free, local and private; Titan's AI OCR
    understands what it reads and sends a picture of the screen to a
    provider to do it.
    """
    try:
        from . import configSpec
        answer = str(configSpec.read().get('ocrTier') or '').strip()
    except Exception:                                # noqa: BLE001
        answer = ''
    if answer == 'ai':
        return MODE_NATIVE
    if answer == 'both':
        # **Windows' own recogniser FIRST, and the AI only when it cannot.**
        #
        # It was the other way round, and both halves of that were wrong.
        # The cheap half: Windows' recogniser is local, private, free and
        # answers in a tenth of a second, while the AI is a picture of the
        # user's screen sent to a provider and a call that has been
        # measured taking longer than the bus will wait for it - "Titan
        # did not answer within 12s", in the log, from a window this
        # started reading by itself.
        #
        # The expensive half is what it does to the READER. The Action
        # Bus is one pipe: a call that takes twelve seconds is twelve
        # seconds in which every other call queues behind it, including
        # the ones NVDA makes on its own main thread. An automatic
        # feature that can do that is not a feature that reads a window,
        # it is a feature that stops the screen reader.
        #
        # So the free one goes first and the AI is the fallback -
        # `_watch` promotes to it when the local reading comes back with
        # nothing worth saying, which is the only case the AI was ever
        # needed for.
        return MODE_LOCAL
    return MODE_LOCAL


#: How often the window is looked at while watching. A poll on a still
#: screen is a capture and a comparison; this is fast enough to follow a
#: menu being arrowed through and slow enough that a game which repaints
#: constantly does not spend a request per frame.
POLL = 1.2

#: A screen that really is changing every poll - a game with animation
#: behind its menu - would spend a request every time. After this many
#: consecutive changed readings the watch slows down, and says so.
BUSY_ENOUGH = 5
SLOW_POLL = 4.0

#: What marks the highlighted item in a reading. The model is told in
#: `recognizer.SYSTEM_PROMPT` that a highlight means selected or focused,
#: and `Element.spoken()` puts the state at the end of the line.
HIGHLIGHT = ('selected', 'focused', 'highlighted')

def _log(text, error=False):
    """A feature that does nothing must at least say so somewhere.

    "OCR does not work in this game" is a report with no evidence in it,
    and every step here can refuse for a different reason: the switch, the
    window, Titan, AI OCR's own setting, a game in exclusive full screen
    that cannot be photographed at all. Each of those is a different thing
    to do about it.
    """
    if compat.log is None:
        return
    try:
        (compat.log.error if error else compat.log.info)(
            'Titan window reading: %s' % text)
    except Exception:                                # noqa: BLE001
        pass


_LOCK = threading.RLock()
_watching = {'hwnd': 0, 'thread': None, 'stop': None, 'last': '',
             'reads': 0, 'changed': 0, 'why': '', 'mode': MODE_GAME,
             'said': 0, 'last_said': '', 'empty': 0}

#: Windows already considered and declined, so a game that cannot be read
#: is not re-read every time it comes to the front.
_declined = set()


def report():
    with _LOCK:
        return {'watching': int(_watching['hwnd'] or 0),
                'mode': _watching['mode'],
                'reads': _watching['reads'],
                'changed': _watching['changed'],
                'why': _watching['why'],
                'said': _watching['said'],
                'last_said': _watching['last_said'],
                'empty': _watching['empty'],
                'enabled': wanted()}


def wanted(obj=None):
    """Whether this may read a window as a picture - HERE.

    Per program, because that is where the answer really differs: a game
    that exposes nothing is worth reading and the program the user is in
    all day is not, and one switch for the machine cannot say both.
    """
    from . import perProgram
    return bool(perProgram.value('surfaceReading', obj))


def _text(value):
    return str(value or '').strip()


def _role(obj):
    return _text(getattr(getattr(obj, 'role', None), 'name', '')).upper()


# --------------------------------------------------------------------------- #
# Whether this window has anything to say for itself
# --------------------------------------------------------------------------- #
#: Window classes that are certainly NOT a drawn surface, whatever their
#: children look like at the moment they are asked. A terminal, a console,
#: Explorer, a dialog and a browser all have real controls, and a terminal
#: in particular can answer with nothing at all while it is starting - so
#: it is named here rather than left to a test it would fail one time in
#: fifty. Being wrong in this direction is the expensive one: it puts a
#: question in front of somebody about a window that was never the point.
NOT_DRAWN_CLASSES = frozenset({
    'CASCADIA_HOSTING_WINDOW_CLASS',    # Windows Terminal
    'ConsoleWindowClass',               # the old console
    'CabinetWClass', 'ExploreWClass',   # Explorer
    'Progman', 'WorkerW', 'Shell_TrayWnd',
    '#32770',                           # every dialog
    'Chrome_WidgetWin_1', 'MozillaWindowClass',
    'Notepad', 'WordPadClass', 'SunAwtFrame',
    'Windows.UI.Core.CoreWindow',
    'ApplicationFrameWindow',           # every packaged app
    'XLMAIN', 'OpusApp',                # Excel, Word
})


#: The programs whose window IS another computer's screen.
#:
#: **Matched on the executable, not the window class**, because the class
#: is not reliable for the one that matters: VirtualBox's window is a
#: plain `QWidget` and so is half of everything else written in Qt.
#: The executable is exact, and it is what `appModule.appName` already
#: answers.
VM_PROGRAMS = frozenset({
    'virtualboxvm', 'virtualbox',            # Oracle VirtualBox
    # VMware Workstation and Player. `vmware` is the Workstation window
    # the user sits in front of; `vmware-vmx` is the process that really
    # runs the guest and owns the display on some versions; `vmrc` is the
    # standalone Remote Console.
    'vmware', 'vmware-vmx', 'vmplayer', 'vmrc', 'vmware-view',
    'vmconnect',                             # Hyper-V
    'qemu-system-x86_64', 'qemu-system-i386', 'qemu',
    'mstsc',                                 # Remote Desktop
    'vncviewer', 'tvnviewer', 'uvncviewer',  # VNC
    'xfreerdp', 'remmina',
})

#: A virtual machine's own window class, where it has a distinctive one.
#: Matched as well as the executable rather than instead of it: VMware
#: Workstation's frame is `VMUIFrame` and has been for twenty years, and a
#: window recognised two ways is one that is still recognised when the
#: user runs it under a name this list has not got.
VM_CLASSES = frozenset({
    'VMUIFrame',                             # VMware Workstation / Player
    'VMwareUnityWindowClass',
    'VirtualBoxVM', 'QemuWindowClass',
    'TscShellContainerClass',                # Remote Desktop
    'VNCViewerClass', 'VNCMDI_Window',
})

#: The child window a virtual machine paints its guest's screen onto,
#: where it has one of its own. Reading THAT rather than the whole window
#: is what keeps the host's menu bar and status line out of the guest's
#: screen - they are the host's interface, they are readable already, and
#: recognising them as part of the guest is how a VM reading comes back
#: with "File Machine View" at the top of somebody's Linux console.
VM_DISPLAY_CLASSES = frozenset({
    # VMware paints the guest onto its own child: `MKSEmbedded` is the
    # Workstation console, and it is what has to be read rather than the
    # frame around it.
    'MKSEmbedded', 'VMwareUnityView', 'MKSWindow',
    'IHWindowClass',                         # Remote Desktop
    'SDL_app',                               # QEMU
})

#: What VirtualBox paints its guest onto is a plain `QWidget`, which is
#: also the class of every Qt program on the machine. So it is looked for
#: only INSIDE a window already known to be a virtual machine - never as
#: the thing that decides one. Putting it in the recognising set made
#: every Qt program a virtual machine, which is the false positive this
#: repository keeps paying for and the reason the two sets are apart.
VM_DISPLAY_INSIDE_ONLY = frozenset({'QWidget'})


def is_virtual_machine(obj):
    """Whether this window is another computer's screen.

    A virtual machine is the case this whole tier exists for and the one
    it was getting wrong: the window really does expose things - a menu
    bar, a status line, the host's own chrome - so "no children at all"
    answers no, and the guest's screen, which exposes nothing at all, was
    never read.
    """
    if obj is None:
        return False
    try:
        name = _text(getattr(getattr(obj, 'appModule', None),
                             'appName', '')).lower()
    except Exception:                                # noqa: BLE001
        name = ''
    if name and name in VM_PROGRAMS:
        return True
    window_class = _text(getattr(obj, 'windowClassName', ''))
    # Deliberately NOT `VM_DISPLAY_INSIDE_ONLY`: see why beside it.
    return window_class in VM_CLASSES or window_class in VM_DISPLAY_CLASSES


#: The smallest rectangle that can be another computer's screen. The
#: fallback below looks for "the biggest child that exposes nothing", and
#: on VMware Workstation the biggest such child is `unibar.ahTarget` - the
#: auto-hide strip along the top of the window, **1894 by 1 pixels**. It
#: has no children, so it qualified; the real console is nested five
#: levels down, so it never did. What was then watched was a one-pixel
#: line: Windows' recogniser read no words in it, ever, the picture never
#: changed, and the whole feature was silent while reporting that it was
#: working. A screen has a SIZE, and saying so is what stops this.
SMALLEST_DISPLAY = (240, 180)

#: How far down to look for the guest's own window, and how many nodes to
#: look at. VMware nests the console under the frame, a view, a status
#: pane and two containers - so one level down is not enough and an
#: unbounded walk is not affordable. This runs on `event_foreground`, not
#: on the focus path, but a window with thousands of controls must not
#: make arriving in it expensive.
DISPLAY_DEPTH = 8
DISPLAY_BUDGET = 300


def _big_enough(location):
    """Whether that rectangle could be a screen at all."""
    try:
        width = int(location[2]) if len(location) > 2 else 0
        height = int(location[3]) if len(location) > 3 else 0
    except Exception:                                # noqa: BLE001
        return False
    return (width >= SMALLEST_DISPLAY[0]
            and height >= SMALLEST_DISPLAY[1])


def _descendants(obj, depth=DISPLAY_DEPTH, budget=DISPLAY_BUDGET):
    """Every window inside this one, breadth first, bounded.

    Bounded on both axes on purpose: the depth because the guest is nested
    and the budget because this must cost the same in a window with five
    children and one with five hundred.
    """
    found = []
    level = [obj]
    while level and depth > 0 and len(found) < budget:
        depth -= 1
        below = []
        for parent in level:
            try:
                children = list(parent.children or [])
            except Exception:                        # noqa: BLE001
                continue
            for child in children:
                found.append(child)
                below.append(child)
                if len(found) >= budget:
                    return found
        level = below
    return found


def _overlaps(location, outer):
    """Whether that rectangle is really ON this window.

    **VMware keeps more than one `MKSEmbedded`**, and the spare is parked
    at (-31797, -31820) - the same trick Titan's own offscreen bridge
    frame uses. Matched on class alone the parked one won, and what was
    then read was a console nobody can see: a picture that is always the
    same, no words in it, and a reader that says nothing while reporting
    that it found the guest. So a candidate has to be where the window is.
    """
    if not location or not outer:
        return True                                  # cannot tell: allow
    try:
        left, top, width, height = (int(location[0]), int(location[1]),
                                    int(location[2]), int(location[3]))
        o_left, o_top, o_width, o_height = (int(outer[0]), int(outer[1]),
                                            int(outer[2]), int(outer[3]))
    except Exception:                                # noqa: BLE001
        return True
    return (left < o_left + o_width and left + width > o_left
            and top < o_top + o_height and top + height > o_top)


def _on_the_screen(location):
    """Whether that rectangle is anywhere a person could see it.

    Windows parks a minimised window at (-32000, -32000), and VMware
    parks its spare console at (-31797, -31820) - so "off the screen" is
    what tells a real guest from one that exists only in the process.
    Answers True when it cannot be told: a check that cannot see must not
    be the thing that refuses.
    """
    if not location:
        return True
    try:
        left, top, width, height = (int(location[0]), int(location[1]),
                                    int(location[2]), int(location[3]))
    except Exception:                                # noqa: BLE001
        return True
    if width <= 0 or height <= 0:
        return False
    try:
        import ctypes
        metrics = ctypes.windll.user32.GetSystemMetrics
        # SM_XVIRTUALSCREEN 76, SM_YVIRTUALSCREEN 77, CX 78, CY 79
        bounds = (metrics(76), metrics(77), metrics(78), metrics(79))
    except Exception:                                # noqa: BLE001
        return True
    if bounds[2] <= 0 or bounds[3] <= 0:
        return True
    return _overlaps(location, bounds)


def _biggest(candidates):
    """The largest of them, or None."""
    best = None
    best_area = -1
    for child, location in candidates:
        try:
            area = int(location[2]) * int(location[3])
        except Exception:                            # noqa: BLE001
            continue
        if area > best_area:
            best, best_area = child, area
    return best


def display_of(obj):
    """The child a virtual machine paints the guest onto, or ``obj``.

    Its own class where it has one - looked for at ANY depth, because
    VMware Workstation keeps `MKSEmbedded` under the frame, a view, a
    status pane and two containers, and looking only at the frame's own
    children never reached it. Otherwise the biggest child that exposes
    nothing and is big enough to be a screen. Every candidate has to be
    where the window is: see :func:`_overlaps`.
    """
    if obj is None:
        return obj
    inside = _descendants(obj)
    if not inside:
        return obj
    outer = getattr(obj, 'location', None)
    # A minimised window is parked off the screen too, and then nothing
    # inside it overlaps anything - so the outer is only used to choose
    # between candidates when the window itself is somewhere visible.
    outer_ok = _on_the_screen(outer)
    named = []
    qt = []
    drawn = []
    for child in inside:
        try:
            location = getattr(child, 'location', None)
            if not _on_the_screen(location):
                continue
            if outer_ok and not _overlaps(location, outer):
                continue
            child_class = _text(getattr(child, 'windowClassName', ''))
            if child_class in VM_DISPLAY_CLASSES:
                named.append((child, location or (0, 0, 0, 0)))
                continue
            if not location or not _big_enough(location):
                continue
            # Only ever reached from inside a window already known to be a
            # virtual machine, which is what makes matching a plain
            # `QWidget` safe - and it still has to be big enough to be a
            # screen rather than a Qt spacer.
            if child_class in VM_DISPLAY_INSIDE_ONLY:
                qt.append((child, location))
            elif _has_no_children(child):
                drawn.append((child, location))
        except Exception:                            # noqa: BLE001
            continue
    # **The certain answer first, wherever it is.** A window that says it
    # is the console is the console; nothing measured can beat that. Where
    # there are several, the one with the most screen on it.
    for candidates in (named, qt, drawn):
        best = _biggest(candidates)
        if best is not None:
            return best
    return obj


def looks_drawn(obj, module=None):
    """Whether this window paints its own interface and exposes NOTHING.

    The bar is deliberately high, because the cost of being wrong is a
    question put to somebody about a window that was never the point. A
    terminal, Explorer, a browser, a dialog all have controls; what this is
    looking for is a window with no interface in it at all - a game that
    draws its menu onto a texture.

    Four answers, cheapest first:

    * A reader module saying so, which is the only certain one.
    * A class that is certainly NOT a surface - said before anything is
      measured, because a terminal can answer with no children at all
      while it is still starting up.
    * A class that is certainly a surface: an engine that paints its own
      window (Unity, SDL, Godot).
    * And finally the measurement, which is now "no children AT ALL"
      rather than "no NAMED children among the first twelve". A window
      whose children are merely unnamed is a window with an interface this
      reader is failing to read, which is a different problem with a
      different answer; a window with no children is a surface.
    """
    if obj is None:
        return False
    if module is not None:
        try:
            if module.reads_surface():
                return True
        except Exception:                            # noqa: BLE001
            pass
    # **A virtual machine before anything is measured.** Its window has a
    # menu bar and a status line - real controls, readable ones - so every
    # measurement below answers "this has an interface" and the guest's
    # screen, which has none at all, was never read. It is the case this
    # tier exists for and the one it was getting wrong.
    if is_virtual_machine(obj):
        return True
    window_class = _text(getattr(obj, 'windowClassName', ''))
    if window_class in NOT_DRAWN_CLASSES:
        return False
    if window_class in DRAWN_CLASSES:
        return True
    if _role(obj) not in ('WINDOW', 'PANE', 'APPLICATION', 'UNKNOWN'):
        return False
    return _has_no_children(obj)


def _has_no_children(obj):
    """Whether the reader can reach anything at all inside this window.

    **Anything, not anything NAMED.** The first version asked whether any
    of the first twelve children had a name, which is true of a window
    whose named controls happen to come thirteenth - and answering "this
    exposes nothing" about a real interface is how a user is asked about
    their terminal. A window that a screen reader can find no child of
    whatsoever is the case this feature is for, and it is not a judgement.
    """
    try:
        children = list(obj.children or [])
    except Exception:                                # noqa: BLE001
        return False                                 # cannot tell: assume no
    return not children


# --------------------------------------------------------------------------- #
# Reading one
# --------------------------------------------------------------------------- #
def read(hwnd=0, timeout=45.0):
    """Read the window as a picture. ``(ok, text)``.

    No question is asked, and that is not a simplification: a question makes
    Titan spend a request on every reading, and this is called repeatedly.
    """
    from .link import LINK
    if not LINK.connected():
        return False, _('Titan is not running, so there is nothing to read '
                        'the screen with.')
    try:
        handle = int(hwnd or 0)
    except (TypeError, ValueError):
        handle = 0
    ok, text = LINK.run_action('ocr', 'read_window', timeout=timeout,
                               hwnd=handle)
    said = _text(text)
    if ok and not looks_like_a_reading(said):
        # **A refusal is not a reading, and it arrives as a success.**
        # Titan answers "AI OCR is switched off. Turn it on in Settings"
        # as ordinary prose with the call reported as having worked - so a
        # watcher that trusted `ok` would poll that sentence for a
        # highlight for ever, finding none, telling the user nothing and
        # never saying why the window had gone quiet.
        return False, said
    return bool(ok), said


def looks_like_a_reading(text):
    """Whether this is a reading of a window or a sentence about one.

    By SHAPE, never by wording: `model.elements_as_lines` writes the
    title, the summary, then `[Region]` blocks, and Titan's refusals are
    one paragraph with none of that. Matching the words would break the
    moment Titan says them in another language, which is a mistake this
    repository has already made once in the other direction.
    """
    return any(line.lstrip().startswith('[')
               for line in str(text or '').splitlines())


def highlight_in(reading):
    """The line of a reading that is the highlighted item, or ''.

    Read out of the reading rather than asked for, because asking is what
    costs a request. The model marks it - it is told that a highlight means
    selected or focused - and the state is the last thing on the line.
    """
    for line in str(reading or '').splitlines():
        plain = line.strip()
        if not plain or plain.startswith('['):
            continue
        low = plain.lower()
        if any(low.endswith(mark) or (', %s' % mark) in low
               for mark in HIGHLIGHT):
            return plain.strip(' -')
    return ''


def _say(text, interrupt=True):
    # **Written down before it is spoken.** "It reads the window and says
    # nothing" is a report with no evidence in it, and it wears at least
    # four different faults: nothing was read, something was read and
    # nothing was new, something was said and NVDA dropped it, or the
    # watch was not running at all. Only a record of what this decided to
    # say tells them apart.
    with _LOCK:
        _watching['said'] += 1
        _watching['last_said'] = str(text or '')[:200]
    if compat.queueHandler is None or compat.ui is None:
        return
    def speak():
        try:
            compat.ui.message(text)
        except Exception:                            # noqa: BLE001
            pass
    compat.queueHandler.queueFunction(compat.queueHandler.eventQueue, speak)


# --------------------------------------------------------------------------- #
# Watching one
# --------------------------------------------------------------------------- #
def _window_alive(hwnd):
    try:
        import ctypes
        return bool(ctypes.windll.user32.IsWindow(ctypes.c_void_p(int(hwnd))))
    except Exception:                                # noqa: BLE001
        return True


def _foreground():
    try:
        import ctypes
        ctypes.windll.user32.GetForegroundWindow.restype = ctypes.c_void_p
        return int(ctypes.windll.user32.GetForegroundWindow() or 0)
    except Exception:                                # noqa: BLE001
        return 0


def _root_owner(hwnd):
    """The top-level window this one belongs to. GA_ROOTOWNER."""
    try:
        import ctypes
        return int(ctypes.windll.user32.GetAncestor(ctypes.c_void_p(int(hwnd)),
                                                    3) or hwnd)
    except Exception:                                # noqa: BLE001
        return int(hwnd or 0)


def _user_is_here(hwnd):
    """Whether the user is still in the window being watched.

    Not simply "is it the foreground window": with an overlay on it, the
    keyboard is on a control of Titan's. A control parented INTO the target
    (the usual case) leaves the target foreground, but the two fallbacks - an
    owned window, and a floating one - are top-level windows of their own, and
    asking the plain question about those answers "the user has gone
    somewhere else" for as long as the overlay is being used, which would
    stop it being refreshed exactly while somebody is working in it.
    """
    front = _foreground()
    handle = int(hwnd or 0)
    if front in (0, handle) or _root_owner(front) == handle:
        return True
    # **The window being read may be INSIDE the one the user is in.** A
    # virtual machine is read at its guest's screen, which is a child of
    # the frame the user is sitting in front of - so the plain question
    # answered "they have gone somewhere else" on every poll, for ever,
    # and the reading never happened at all. Seen live on VMware
    # Workstation: the watch started, said it was reading the guest, and
    # then read nothing.
    try:
        import ctypes
        if handle and front:
            root = ctypes.windll.user32.GetAncestor(
                ctypes.c_void_p(handle), 2)          # GA_ROOT
            if int(root or 0) == int(front):
                return True
    except Exception:                                # noqa: BLE001
        pass
    # And the frame this watch was started FOR, where it was told one.
    with _LOCK:
        theirs = int(_watching.get('for_hwnd') or 0)
    return bool(theirs) and int(front) == theirs


# --------------------------------------------------------------------------- #
# The window, worn as real controls
# --------------------------------------------------------------------------- #
#: A reading takes seconds - a picture, and a request to a vision provider -
#: and putting one on a window takes a reading first. Titan's own default for
#: a bridge call is twelve seconds, which is a sensible figure for a question
#: and the wrong one for this.
OVERLAY_TIMEOUT = 90.0


def _overlay(call, timeout=OVERLAY_TIMEOUT, **args):
    """One overlay call into Titan. ``(state, sentence)``.

    Typed on purpose. The prose actions answer a model as well as a client,
    so "the overlay went up" and "it could not be put there" are both
    sentences with `ok` true - and a watcher reading a sentence to find out
    whether its own feature is working is the mistake this repository has
    made in every direction it can be made. `titan.bridge`'s `ocr.overlay*`
    answer a real boolean.
    """
    from .link import LINK
    if not LINK.connected():
        return None, _('Titan is not running, so there is nothing to read '
                       'the screen with.')
    ok, data = LINK.bridge(call, timeout=timeout, **args)
    if not ok:
        return None, _text(data)
    if not isinstance(data, dict):
        return None, _('Titan answered something unexpected.')
    return data, _text(data.get('said'))


def overlay_open():
    """Whether an overlay is on a window at the moment, and which."""
    state, _said = _overlay('ocr.overlay', timeout=8.0)
    return state or {'open': False}


def overlay_show(hwnd):
    """Read the window and wear the reading as real controls. ``(ok, text)``."""
    state, said = _overlay('ocr.overlay_show', hwnd=int(hwnd or 0), read=True)
    if state is None:
        return False, said
    return bool(state.get('open')), said


def overlay_refresh():
    """Look again; rebuild the controls only if the window has changed."""
    state, said = _overlay('ocr.overlay_refresh')
    if state is None:
        return False, said
    return bool(state.get('open')), said


def overlay_close():
    _overlay('ocr.overlay_close', timeout=10.0)


def _watch_locally(hwnd, stop):
    """Watch a window with WINDOWS' own OCR - free, local, nothing sent.

    **The tier under the AI one, and for a window that is watched it is the
    one that matters.** A game menu repaints constantly; a reading per poll
    from a vision provider is a request per poll and somebody's money. This
    is a screenshot and Windows' own recogniser: about a tenth of a second,
    on this machine, and nothing leaves it.

    It gives the WORDS and where each line is, which is enough to make the
    window navigable - the cursor is built from it and a control presses
    itself by clicking where it was read. What it cannot give is
    understanding: which of these is a button, what is highlighted. That
    stays with the AI, and this is what stops the AI being asked about a
    screen that has not changed.

    Answers ``''`` when it is done, or the name of the mode to fall back to.
    """
    from . import localOcr
    ok, why = localOcr.available()
    if not ok:
        _log('no local OCR: %s' % why)
        return MODE_APPLICATION
    interval = POLL
    busy = 0
    last = None
    while True:
        if not _window_alive(hwnd):
            _say(_('That window has closed.'))
            break
        if _user_is_here(hwnd):
            reading = localOcr.read_window(hwnd)
            with _LOCK:
                _watching['reads'] += 1
            if reading is None:
                with _LOCK:
                    _watching['why'] = localOcr.report().get('why', '')
                _log('local reading failed: %s'
                     % _watching.get('why', ''), error=True)
                return MODE_APPLICATION
            if not reading.lines:
                # **Windows read the window and found no words in it.**
                # That is the one case the AI was ever needed for, and it
                # is what "Windows' own recogniser first, the AI when it
                # cannot" actually means - the promotion was documented
                # here and only ever happened when the recogniser
                # RAISED, so a window it read as blank was watched for
                # ever in silence. Counted rather than acted on at once:
                # a screen is legitimately blank for a moment while it
                # repaints.
                with _LOCK:
                    _watching['empty'] += 1
                    enough = _watching['empty'] >= EMPTY_ENOUGH
                if enough:
                    _log('Windows read nothing in this window %d times; '
                         'asking the AI instead' % EMPTY_ENOUGH)
                    return MODE_APPLICATION
            else:
                with _LOCK:
                    _watching['empty'] = 0
            if reading.changed_from(last):
                with _LOCK:
                    _watching['changed'] += 1
                try:
                    from . import smart
                    smart.take_local(hwnd, reading)
                except Exception:                    # noqa: BLE001
                    pass
                # **What is HIGHLIGHTED first, and instead.**
                #
                # In a virtual machine - and in any window that paints its
                # own menu - the highlight IS the interface: it is the
                # entry the arrow keys are on. When it moves, the whole
                # screen "changes" as far as a diff of the text is
                # concerned, and reading the new lines would recite the
                # menu instead of saying which item the user is on. So
                # when there is a highlight and it has moved, that is the
                # answer, and the diff is not used at all.
                said_it = False
                try:
                    from . import virtualInput
                    nodes = virtualInput.build(
                        reading, getattr(reading, 'highlights', None))
                    chosen = ' '.join(
                        node.text for node in virtualInput.selected_in(nodes))
                    if chosen and chosen != _highlight_was.get(hwnd):
                        _highlight_was[hwnd] = chosen
                        _say(chosen)
                        said_it = True
                except Exception:                    # noqa: BLE001
                    said_it = False
                # Only what is NEW. A window whose whole reading is
                # announced on every change would be a reader reading a
                # menu from the top every time one line of it moved. This
                # is what a terminal in a virtual machine needs: the lines
                # that have just appeared, and nothing else.
                if not said_it:
                    for line in reading.added_since(last)[:MAX_SAID]:
                        _say(line, interrupt=False)
                last = reading
                busy += 1
                if busy >= BUSY_ENOUGH and interval == POLL:
                    interval = SLOW_POLL
            else:
                busy = 0
                interval = POLL
        if stop.wait(interval):
            break
    return ''


#: How many readings in a row may come back with no words in them
#: before the AI is asked instead. A screen really is blank for a moment
#: while it repaints, so this is not one - and a window Windows cannot
#: read at all reaches it in a couple of seconds.
EMPTY_ENOUGH = 3


#: What was highlighted last time, per window. A highlight that has not
#: moved is not news, and saying it on every poll would be a reader
#: repeating the same menu entry twice a second.
_highlight_was = {}


#: How many new lines are said when a window changes. A screen that has
#: been replaced wholesale would otherwise be read out from the top, which
#: is the thing the diff exists to avoid.
MAX_SAID = 6


def _watch_native(hwnd, stop):
    """Watch a window by WEARING it: the reading, as the window's controls.

    Nothing is announced from here and nothing is parsed. The controls are
    real, so NVDA reads them itself - which is the whole claim of this mode,
    and the reason there is no cursor, no line, no highlight and no voice in
    it. What this loop does is keep them TRUE: ask Titan to look again, which
    costs nothing at a provider while the picture is the same and rebuilds
    them when it is not.

    Answers ``''`` when it is done, or the name of the mode to fall back to
    when the window will not wear an overlay.
    """
    ok, said = overlay_show(hwnd)
    if not ok:
        # Nothing could be placed where it really is, or the window would not
        # adopt the controls. A reading the user can still move through is
        # worth far more than a sentence about a feature, so this hands over
        # rather than stopping.
        _log('no overlay: %s' % said, error=True)
        return MODE_APPLICATION
    _say(said or _('This window now has controls you can Tab through.'))
    interval = POLL
    busy = 0
    while not stop.wait(interval):
        if not _window_alive(hwnd):
            _say(_('That window has closed.'))
            break
        if not _user_is_here(hwnd):
            continue
        ok, said = overlay_refresh()
        with _LOCK:
            _watching['reads'] += 1
        if not ok:
            # The overlay has gone - the user pressed Escape on it, or Titan
            # took it off. That is an answer, not a failure: they asked for
            # the real window back.
            with _LOCK:
                _watching['why'] = said
            _log('the overlay is no longer there: %s' % said)
            break
        busy += 1
        if busy >= BUSY_ENOUGH and interval == POLL:
            interval = SLOW_POLL
    return ''


def _watch(hwnd, stop):
    """One window, until the user stops it or the window goes.

    Three shapes, and the mode decides which. NATIVE wears the reading as the
    window's own controls and has a loop of its own; GAME is told what has
    become highlighted; APPLICATION gets a cursor of ours over the reading.
    """
    with _LOCK:
        mode = _watching['mode']
    if mode == MODE_NATIVE:
        fallback = _watch_native(hwnd, stop)
        if not fallback:
            _finish_watch()
            return
        # The window would not wear an overlay. Say so once - the user asked
        # for this window to be readable and is about to get the weaker
        # answer, and being told which they got is the difference between a
        # feature that degraded and one that is quietly not what it claimed.
        _say(_('This window will not take controls of its own, so it is being '
               'read with Windows\' own recogniser instead.'))
        with _LOCK:
            _watching['mode'] = mode = MODE_LOCAL
    if mode == MODE_LOCAL:
        # Free, local, and still navigable. The AI is not asked at all.
        fallback = _watch_locally(hwnd, stop)
        if not fallback:
            _finish_watch()
            return
        _say(_('Windows cannot read this window either, so it is being read '
               'with AI instead.'))
        with _LOCK:
            _watching['mode'] = mode = MODE_APPLICATION
    interval = POLL
    busy = 0
    while not stop.wait(interval):
        if not _window_alive(hwnd):
            _say(_('That window has closed.'))
            break
        if not _user_is_here(hwnd):
            # The user is somewhere else; nothing to say about a window
            # they are not in, and nothing to spend on it either.
            continue
        ok, text = read(hwnd)
        with _LOCK:
            _watching['reads'] += 1
        if not ok:
            with _LOCK:
                _watching['why'] = text
                _declined.add(hwnd)
            # Titan's own sentence, which names the one thing that changes
            # the answer - AI OCR switched off, no key, or a game in
            # exclusive full screen, which cannot be photographed at all.
            _log('stopped: %s' % text, error=True)
            _say(text)
            break
        with _LOCK:
            mode = _watching['mode']
        # An APPLICATION becomes a model of controls the keyboard walks; a
        # GAME keeps its own keys and is told what is highlighted.
        if mode == MODE_APPLICATION:
            try:
                from . import smart
                smart.take(hwnd, text)
            except Exception:                        # noqa: BLE001
                pass
        found = highlight_in(text) if mode == MODE_GAME else ''
        if mode == MODE_APPLICATION:
            # What changed is the READING, so the cursor is what says
            # whether anything is worth saying.
            found = ''
        with _LOCK:
            same = (found == _watching['last'])
            if not same:
                _watching['last'] = found
                _watching['changed'] += 1
        if same:
            busy = 0
            interval = POLL
            continue
        busy += 1
        if busy >= BUSY_ENOUGH and interval == POLL:
            interval = SLOW_POLL
            _say(_('This screen keeps changing, so it is being read less '
                   'often.'))
        if found:
            _say(found)
    _finish_watch()


def _finish_watch():
    """Everything a watch leaves behind, whichever shape it was.

    The overlay is taken off deliberately rather than left standing. It is
    real controls over somebody's real window: left there after the watch has
    ended they would go on being read while nothing was keeping them true - an
    interface that is right about a screen which has moved on, and that is
    worse than no interface at all.
    """
    with _LOCK:
        was_native = _watching['mode'] == MODE_NATIVE
        _watching['hwnd'] = 0
        _watching['thread'] = None
        _watching['stop'] = None
    if was_native:
        try:
            overlay_close()
        except Exception:                            # noqa: BLE001
            pass
    try:
        from . import smart
        smart.forget()
    except Exception:                                # noqa: BLE001
        pass


def watching():
    """The window being watched, as the USER's window.

    Not always the one being photographed: a virtual machine is read at
    its guest's screen, which is a child. `consider` asks this to decide
    whether it is already watching what the user is in - and comparing
    the frame against the guest never matched, so every foreground event
    started a NEW watch and killed the one before it. Seen live: the
    reading beginning again every fifteen seconds and never settling.
    """
    with _LOCK:
        return int(_watching.get('for_hwnd') or _watching['hwnd'] or 0)


def reading_hwnd():
    """The window actually being photographed - the guest, for a VM."""
    with _LOCK:
        return int(_watching['hwnd'] or 0)


def _root(hwnd):
    try:
        import ctypes
        return int(ctypes.windll.user32.GetAncestor(ctypes.c_void_p(int(hwnd)),
                                                    2) or hwnd)
    except Exception:                                # noqa: BLE001
        return int(hwnd or 0)


def consider(obj, module=None):
    """A window has come to the front with nothing in it. ASK about it.

    **It asks; it does not decide.** Reading a window means sending
    pictures of it to an AI provider, repeatedly, and a reader that
    started doing that because a window looked empty would be spending
    somebody's money and privacy on a guess about what they wanted. The
    window being unreadable is a good reason to raise the question and no
    reason at all to answer it.

    So: once per program, and never again. Yes turns it on for that
    program and starts; no turns it OFF for that program, which is what
    stops it ever asking again. Either way the answer is the per-program
    switch the Titan menu shows, so it can be changed later without
    hunting for where it was set.
    """
    from . import perProgram
    if obj is None:
        return False
    try:
        hwnd = _root(int(getattr(obj, 'windowHandle', 0) or 0))
    except (TypeError, ValueError):
        return False
    if not hwnd or hwnd == watching():
        return False
    with _LOCK:
        if hwnd in _declined:
            return False
    program = perProgram.application_of(obj)
    if not program:
        return False
    # An answer already given - here or generally - is obeyed in silence.
    if perProgram.answered('surfaceReading', program):
        if not perProgram.value('surfaceReading', obj):
            return False
        return _begin(obj, module, hwnd)
    if _global_on():
        # The user has asked for this everywhere; asking again per program
        # would be asking them to confirm something they already said.
        return _begin(obj, module, hwnd)
    try:
        if not looks_drawn(obj, module):
            return False
    except Exception:                                # noqa: BLE001
        return False
    return _ask_about(obj, module, hwnd, program)


def _global_on():
    from . import configSpec
    return bool(configSpec.read().get('surfaceReading', False))


def _begin(obj, module, hwnd):
    """Start reading, having established that the user wants it."""
    try:
        if not looks_drawn(obj, module):
            return False
    except Exception:                                # noqa: BLE001
        return False
    mode = mode_for(obj, module)
    # **A virtual machine is read at its GUEST's screen.** The handle that
    # arrived is the host's window, menu bar and all; reading that gives
    # somebody "File Machine View" across the top of their Linux console
    # every time. The guest is a child that exposes nothing, sitting under
    # chrome that exposes plenty.
    theirs = hwnd
    if is_virtual_machine(obj):
        try:
            display = display_of(obj)
            inner = int(getattr(display, 'windowHandle', 0) or 0)
            if inner and inner != hwnd:
                _log('a virtual machine: reading the guest\'s screen')
                hwnd = inner
        except Exception:                            # noqa: BLE001
            pass
    _log('%s exposes nothing; reading it as a %s'
         % (str(getattr(obj, 'windowClassName', '') or 'this window'), mode))
    ok, said = start(hwnd, mode, for_hwnd=theirs)
    if not ok:
        with _LOCK:
            if len(_declined) > 32:
                _declined.clear()
            _declined.add(hwnd)
        _log('not reading it: %s' % said, error=True)
        _say(said)
    return bool(ok)


#: Programs already asked about in this session, so a window that comes and
#: goes does not ask twice before the answer has been given.
_asked = set()


from . import perProgram                            # noqa: E402


def _write_a_module(obj, module, program):
    """Write a reader module for this program, so it is KNOWN next time.

    The per-program switch would have been enough to make it work again,
    and a module is the better answer for the same reason the modules
    exist at all: it is data, it says WHY - that this program draws its
    own interface and which of the two kinds it is - it can be corrected,
    and it can be given to somebody else who has the same program. The
    switch is a preference; this is knowledge about a program, which is
    what a reader module is for.

    Never overwrites one that exists: a module somebody has corrected is
    worth more than anything observed here.
    """
    if module is not None:
        return False                                 # it already has one
    try:
        from . import draft
        written, _seen = draft.draft_for(obj)
        if not written:
            return False
        written['surface'] = {'ocr': mode_for(obj, None)}
        written.setdefault('label', perProgram.label_of(obj) or program)
        where, problem = draft.save(written, name=program)
        if problem:
            _log('no module written: %s' % problem)
            return False
        _log('wrote a reader module: %s' % where)
        return True
    except Exception as error:                       # noqa: BLE001
        _log('no module written: %s' % error)
        return False


def _ask_about(obj, module, hwnd, program):
    """Put the question, once, without blocking the event that raised it."""
    with _LOCK:
        if program in _asked:
            return False
        _asked.add(program)
    from . import compat
    from . import dialogs
    name = perProgram.label_of(obj) or program
    _log('asking whether to read %s as a picture' % name)

    def ask():
        # Translators: asked when a window exposes nothing a reader can
        # read. {program} is the program's name.
        question = _('{program} has a window that shows nothing a screen '
                     'reader can read. Read it as a picture with AI '
                     'instead? This sends pictures of that window to your '
                     'AI provider each time it changes. You can change '
                     'this later in the Titan menu.').format(program=name)

        def yes():
            perProgram.set_value('surfaceReading', program, True)
            _log('%s: yes' % name)
            _write_a_module(obj, module, program)
            _begin(obj, module, hwnd)

        def no():
            # Written down as a NO, not merely left unanswered: that is
            # what stops it ever asking about this program again.
            perProgram.set_value('surfaceReading', program, False)
            _log('%s: no' % name)
        dialogs.confirm(question,
                        # Translators: the title of that question.
                        _('Read this window as a picture?'), yes, on_no=no)
    if compat.queueHandler is None:
        ask()
    else:
        compat.queueHandler.queueFunction(compat.queueHandler.eventQueue, ask)
    return True


def forget_declined():
    with _LOCK:
        _declined.clear()
        _asked.clear()


def _mode_here():
    """The mode for the window the user is in, when nobody said which.

    A key pressed on a window carries no opinion about what kind of window it
    is, and the answer matters: MODE_GAME leaves the game its own keys, and
    starting a game in MODE_NATIVE would put controls of ours in front of a
    menu that already answered the arrows. So the same question the automatic
    path asks - the reader module, the user's own answer for this program, the
    window class - is asked here too, rather than one of the three being made
    the default for a window nobody has looked at.
    """
    try:
        import api
        obj = api.getFocusObject()
    except Exception:                                # noqa: BLE001
        return MODE_NATIVE
    try:
        from . import focus
        module = focus.module_for(obj)
    except Exception:                                # noqa: BLE001
        module = None
    try:
        return mode_for(obj, module)
    except Exception:                                # noqa: BLE001
        return MODE_NATIVE


def start(hwnd, mode=None, for_hwnd=0):
    """Begin watching a window. ``(ok, sentence)``.

    ``for_hwnd`` is the window the USER is in, where that is not the one
    being read - a virtual machine is read at its guest's screen, and the
    user is in the frame around it.
    """
    if not wanted():
        return False, _('Reading a window as a picture is switched off. Turn '
                        'it on in NVDA\'s settings, under Titan.')
    from .link import LINK
    if not LINK.connected():
        return False, _('Titan is not running, so there is nothing to read '
                        'the screen with.')
    try:
        handle = int(hwnd or 0)
    except (TypeError, ValueError):
        handle = 0
    if not handle:
        return False, _('There is no window to read.')
    if mode not in MODES:
        mode = _mode_here()
    stop_now()
    stop = threading.Event()
    thread = threading.Thread(target=_watch, args=(handle, stop),
                              name='TitanSurfaceWatch', daemon=True)
    with _LOCK:
        _watching.update({'hwnd': handle, 'thread': thread, 'stop': stop,
                          'last': '', 'why': '', 'mode': mode,
                          'for_hwnd': int(for_hwnd or handle)})
    thread.start()
    if mode == MODE_NATIVE:
        # It is worth saying which of the two happened: this one is about to
        # put controls in the window, and the user should know that is what
        # the noise and the moment's wait are.
        return True, _('Reading this window, and putting its controls on it.')
    return True, _('Watching this window.')


def stop_now():
    with _LOCK:
        stop = _watching.get('stop')
        _watching['hwnd'] = 0
    if stop is not None:
        stop.set()
        return True
    return False


def toggle(hwnd):
    if watching():
        stop_now()
        return True, _('No longer watching.')
    return start(hwnd)
