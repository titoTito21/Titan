# -*- coding: utf-8 -*-
"""The trackpad as a touch screen, so NVDA's touch gestures work on a laptop.

NVDA has had touch support for years and almost nobody can use it, because
it needs a touch SCREEN: ``touchHandler.touchSupported()`` asks Windows for
``MAXIMUM_TOUCHES``, refuses a portable copy and refuses without UI Access.
A MacBook, a Magic Trackpad, and every Windows laptop made in the last
decade has a multi-touch surface sitting under the user's hands - and to
NVDA it is a mouse.

It is not a mouse. A Windows Precision Touchpad is a HID digitizer (usage
page 0x0D, usage 0x05) that reports every contact's identifier, position
and tip state, at full resolution, through Raw Input. Windows turns that
into a pointer for the desktop; nothing stops a program from reading the
contacts themselves.

So this reads them, maps the pad onto the screen ABSOLUTELY - the top left
of the pad is the top left of the screen, which is what makes it a touch
screen rather than a mouse - and hands the contacts to **NVDA's own tracker**
(``touchTracker.TrackerManager``). Everything after that is NVDA's: the
same recogniser that turns contacts into taps, flicks, holds and pinches,
the same ``TouchInputGesture``, the same identifiers (``ts(object):2finger_
flickright``), and therefore the same bindings the user already has and the
same entries in Input Gestures. Nothing here invents a gesture vocabulary.

**Why this is not simply "turning NVDA's touch support on".** That support
gets its contacts from ``RegisterPointerInputTarget``, which is about a
touch screen's pointers and needs UI Access; the tracker underneath it
needs neither, and is a plain Python object that takes ``update(ID, x, y,
complete)``. Driving the tracker directly is what lets this work on a
portable NVDA, without UI Access, on a machine with no touch screen at all.

**Nothing about the pad's ordinary behaviour changes.** Raw Input is a
listener: the pointer still moves, clicks still click, Windows' own
gestures still work. This reads the same reports Windows is reading. That
is also the honest limit - a flick left is also a two-finger scroll to
whatever is under the pointer - which is why it is off until asked for and
why turning it on is one gesture.

Needs no Titan and no Titan Access: it is NVDA, a touchpad and Windows.

**Not live-verified.** Every structure and constant here is out of the
Windows HID documentation and NVDA's own source, and the failure of every
step says which step it was (:func:`report`) - but this has not been run
against a real pad on this machine, and until it has, that is what it is.
"""

import ctypes
import ctypes.wintypes as wintypes
import threading
import time

from . import compat
from . import i18n

_ = i18n.install(globals())

# --------------------------------------------------------------------------- #
# Windows' own numbers
# --------------------------------------------------------------------------- #
HID_USAGE_PAGE_GENERIC = 0x01
HID_USAGE_PAGE_DIGITIZER = 0x0D
HID_USAGE_GENERIC_MOUSE = 0x02
HID_USAGE_DIGITIZER_TOUCH_PAD = 0x05

HID_USAGE_X = 0x30
HID_USAGE_Y = 0x31
HID_USAGE_TIP_SWITCH = 0x42
HID_USAGE_CONTACT_ID = 0x51
HID_USAGE_CONTACT_COUNT = 0x54

RIDEV_INPUTSINK = 0x00000100
RID_INPUT = 0x10000003
RIDI_PREPARSEDDATA = 0x20000005
RIM_TYPEMOUSE = 0
RIM_TYPEHID = 2
WM_INPUT = 0x00FF
WM_CLOSE = 0x0010
HWND_MESSAGE = -3

RI_MOUSE_HWHEEL = 0x0800

HIDP_STATUS_SUCCESS = 0x00110000

#: The NVDA key, in either of the two things a user may have chosen it to
#: be. Asked of the hardware (`GetAsyncKeyState`) rather than of any
#: library's idea of what is held: a key that was pressed on another
#: desktop - a lock screen, a UAC prompt - never has its release seen by
#: anything running here, which Titan's own shell has already paid for.
VK_INSERT = 0x2D
VK_CAPITAL = 0x14
VK_NUMPAD0 = 0x60


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [('usUsagePage', wintypes.USHORT),
                ('usUsage', wintypes.USHORT),
                ('dwFlags', wintypes.DWORD),
                ('hwndTarget', wintypes.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [('dwType', wintypes.DWORD),
                ('dwSize', wintypes.DWORD),
                ('hDevice', wintypes.HANDLE),
                ('wParam', ctypes.c_void_p)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [('Usage', wintypes.USHORT),
                ('UsagePage', wintypes.USHORT),
                ('InputReportByteLength', wintypes.USHORT),
                ('OutputReportByteLength', wintypes.USHORT),
                ('FeatureReportByteLength', wintypes.USHORT),
                ('Reserved', wintypes.USHORT * 17),
                ('NumberLinkCollectionNodes', wintypes.USHORT),
                ('NumberInputButtonCaps', wintypes.USHORT),
                ('NumberInputValueCaps', wintypes.USHORT),
                ('NumberInputDataIndices', wintypes.USHORT),
                ('NumberOutputButtonCaps', wintypes.USHORT),
                ('NumberOutputValueCaps', wintypes.USHORT),
                ('NumberOutputDataIndices', wintypes.USHORT),
                ('NumberFeatureButtonCaps', wintypes.USHORT),
                ('NumberFeatureValueCaps', wintypes.USHORT),
                ('NumberFeatureDataIndices', wintypes.USHORT)]


class _RANGE(ctypes.Structure):
    _fields_ = [('UsageMin', wintypes.USHORT), ('UsageMax', wintypes.USHORT),
                ('StringMin', wintypes.USHORT), ('StringMax', wintypes.USHORT),
                ('DesignatorMin', wintypes.USHORT),
                ('DesignatorMax', wintypes.USHORT),
                ('DataIndexMin', wintypes.USHORT),
                ('DataIndexMax', wintypes.USHORT)]


class _NOTRANGE(ctypes.Structure):
    _fields_ = [('Usage', wintypes.USHORT), ('Reserved1', wintypes.USHORT),
                ('StringIndex', wintypes.USHORT),
                ('Reserved2', wintypes.USHORT),
                ('DesignatorIndex', wintypes.USHORT),
                ('Reserved3', wintypes.USHORT),
                ('DataIndex', wintypes.USHORT), ('Reserved4', wintypes.USHORT)]


class _VALUE_UNION(ctypes.Union):
    _fields_ = [('Range', _RANGE), ('NotRange', _NOTRANGE)]


class HIDP_VALUE_CAPS(ctypes.Structure):
    _fields_ = [('UsagePage', wintypes.USHORT),
                ('ReportID', ctypes.c_ubyte),
                ('IsAlias', ctypes.c_ubyte),
                ('BitField', wintypes.USHORT),
                ('LinkCollection', wintypes.USHORT),
                ('LinkUsage', wintypes.USHORT),
                ('LinkUsagePage', wintypes.USHORT),
                ('IsRange', ctypes.c_ubyte),
                ('IsStringRange', ctypes.c_ubyte),
                ('IsDesignatorRange', ctypes.c_ubyte),
                ('IsAbsolute', ctypes.c_ubyte),
                ('HasNull', ctypes.c_ubyte),
                ('Reserved', ctypes.c_ubyte),
                ('BitSize', wintypes.USHORT),
                ('ReportCount', wintypes.USHORT),
                ('Reserved2', wintypes.USHORT * 5),
                ('UnitsExp', wintypes.ULONG),
                ('Units', wintypes.ULONG),
                ('LogicalMin', wintypes.LONG),
                ('LogicalMax', wintypes.LONG),
                ('PhysicalMin', wintypes.LONG),
                ('PhysicalMax', wintypes.LONG),
                ('u', _VALUE_UNION)]


def _log(text, error=False):
    """Say what happened, where somebody can find it.

    **A feature that fails silently is the fault, not the failure.** This
    was written to answer every refusal with a sentence in `report()` - and
    `report()` is only read by somebody who thinks to press the status
    key. Meanwhile `GlobalPlugin.__init__` calls `start()` inside a
    `try/except: pass`, so a pad that would not start said nothing at all,
    to anybody, ever. NVDA's log is where a user is asked to look when
    something does not work, so that is where this goes.
    """
    if compat.log is None:
        return
    try:
        (compat.log.error if error else compat.log.info)(
            'Titan trackpad: %s' % text)
    except Exception:                                # noqa: BLE001
        pass


_LOCK = threading.RLock()
_state = {'on': False, 'why': '', 'contacts': 0, 'gestures': 0,
          'devices': 0, 'hwnd': 0, 'started': 0.0}
_held = {'proc': None, 'class': None, 'window': None,
         'surface': False}
_preparsed = {}


def report():
    """What this layer really is right now, for the status command."""
    with _LOCK:
        found = dict(_state)
    found['available'] = available()[0]
    return found


def available():
    """``(yes, why not)`` - whether this can work on this machine at all."""
    try:
        ctypes.windll.user32, ctypes.windll.hid
    except Exception as error:                       # noqa: BLE001
        return False, _('Windows will not answer: {why}').format(why=error)
    if compat.inputCore is None:
        return False, _('This NVDA does not expose its input system.')
    try:
        import touchTracker                          # noqa: F401
        import touchHandler                          # noqa: F401
    except Exception as error:                       # noqa: BLE001
        return False, _('This NVDA has no touch support to drive: '
                        '{why}').format(why=error)
    return True, ''


# --------------------------------------------------------------------------- #
# Reading the pad
# --------------------------------------------------------------------------- #
def _hid():
    return ctypes.windll.hid


def _preparsed_for(device):
    """The HID report descriptor Windows has already parsed, kept per device.

    Kept, because it is the same for the life of the device and asking for
    it is two calls into the driver - which is not something to do per
    report on a surface reporting a hundred times a second.
    """
    key = int(device or 0)
    if key in _preparsed:
        return _preparsed[key]
    user32 = ctypes.windll.user32
    size = wintypes.UINT(0)
    if user32.GetRawInputDeviceInfoW(wintypes.HANDLE(key), RIDI_PREPARSEDDATA,
                                     None, ctypes.byref(size)) != 0:
        _preparsed[key] = None
        return None
    if not size.value:
        _preparsed[key] = None
        return None
    buffer = ctypes.create_string_buffer(size.value)
    if user32.GetRawInputDeviceInfoW(wintypes.HANDLE(key), RIDI_PREPARSEDDATA,
                                     buffer, ctypes.byref(size)) <= 0:
        _preparsed[key] = None
        return None
    caps = HIDP_CAPS()
    if _hid().HidP_GetCaps(buffer, ctypes.byref(caps)) != HIDP_STATUS_SUCCESS:
        _preparsed[key] = None
        return None
    count = wintypes.USHORT(caps.NumberInputValueCaps)
    values = (HIDP_VALUE_CAPS * max(1, count.value))()
    if _hid().HidP_GetValueCaps(0, values, ctypes.byref(count),
                                buffer) != HIDP_STATUS_SUCCESS:
        _preparsed[key] = None
        return None
    # One entry per contact: the link collection it lives in, and the
    # logical range of its X and Y, which is what the pad is measured in.
    contacts = {}
    for index in range(count.value):
        one = values[index]
        usage = one.u.Range.UsageMin if one.IsRange else one.u.NotRange.Usage
        if one.UsagePage != HID_USAGE_PAGE_GENERIC or \
                usage not in (HID_USAGE_X, HID_USAGE_Y):
            continue
        entry = contacts.setdefault(int(one.LinkCollection), {})
        entry['x' if usage == HID_USAGE_X else 'y'] = (int(one.LogicalMin),
                                                       int(one.LogicalMax))
    kept = {'data': buffer, 'contacts': contacts}
    _preparsed[key] = kept if contacts else None
    return _preparsed[key]


def _usage_value(preparsed, page, collection, usage, report_bytes, length):
    value = wintypes.ULONG(0)
    status = _hid().HidP_GetUsageValue(0, page, collection, usage,
                                       ctypes.byref(value), preparsed,
                                       report_bytes, length)
    if status != HIDP_STATUS_SUCCESS:
        return None
    return int(value.value)


def _tip_down(preparsed, collection, report_bytes, length):
    """Whether the finger in this collection is touching the pad.

    Tip Switch is a BUTTON usage, so it is read as one: the usage appearing
    in the list means pressed, and its absence means the finger has lifted.
    That absence is the whole of "complete" - it is what turns a contact
    into a tap rather than a hover that never ends.
    """
    count = wintypes.ULONG(16)
    usages = (wintypes.USHORT * 16)()
    status = _hid().HidP_GetUsages(0, HID_USAGE_PAGE_DIGITIZER, collection,
                                   usages, ctypes.byref(count), preparsed,
                                   report_bytes, length)
    if status != HIDP_STATUS_SUCCESS:
        return None
    return any(usages[index] == HID_USAGE_TIP_SWITCH
               for index in range(min(count.value, 16)))


def _screen_size():
    try:
        user32 = ctypes.windll.user32
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    except Exception:                                # noqa: BLE001
        return 0, 0


def contacts_in(report_bytes, length, device):
    """``[(id, x, y, down)]`` in SCREEN coordinates, or ``[]``.

    Absolute, and that is the design: the top left of the pad is the top
    left of the screen. A finger put down in the middle of the pad is a
    finger on the middle of the screen, so a tap reports what is there -
    which is what makes this a touch screen and not a mouse with gestures.
    """
    known = _preparsed_for(device)
    if not known:
        return []
    preparsed, collections = known['data'], known['contacts']
    width, height = _screen_size()
    if not width or not height:
        return []
    # **CONTACT COUNT is what says how many of the slots are real.**
    #
    # A precision touchpad describes as many contact collections as it can
    # ever report - five, here - and every report carries all five whether
    # or not there are five fingers on it. The unused ones are not absent:
    # they come back as position (0, 0), tip switch clear, and contact id
    # ZERO, which is the same id the first real finger has.
    #
    # Measured, with one finger drawn across the pad: 238 reports became
    # 1190 contacts, 955 of which were "finger 0 has lifted at the top left
    # corner". Every touch was a press immediately followed by a lift, so
    # not one gesture could ever have been recognised - a tap needs the
    # finger to still be there on the next report.
    #
    # Usage 0x54 on the TOP-level collection is the count of contacts this
    # report actually carries, and the first that many collections are the
    # ones to read. Nothing is invented for the rest: a finger that stops
    # being reported has lifted, and `feed` already says so.
    count = _usage_value(preparsed, HID_USAGE_PAGE_DIGITIZER, 0,
                         HID_USAGE_CONTACT_COUNT, report_bytes, length)
    found = []
    for index, (collection, ranges) in enumerate(sorted(collections.items())):
        if count is not None and index >= max(0, count):
            break
        if 'x' not in ranges or 'y' not in ranges:
            continue
        raw_x = _usage_value(preparsed, HID_USAGE_PAGE_GENERIC, collection,
                             HID_USAGE_X, report_bytes, length)
        raw_y = _usage_value(preparsed, HID_USAGE_PAGE_GENERIC, collection,
                             HID_USAGE_Y, report_bytes, length)
        if raw_x is None or raw_y is None:
            continue
        identifier = _usage_value(preparsed, HID_USAGE_PAGE_DIGITIZER,
                                  collection, HID_USAGE_CONTACT_ID,
                                  report_bytes, length)
        if identifier is None:
            identifier = collection
        down = _tip_down(preparsed, collection, report_bytes, length)
        if down is None:
            down = True
        low_x, high_x = ranges['x']
        low_y, high_y = ranges['y']
        span_x = max(1, high_x - low_x)
        span_y = max(1, high_y - low_y)
        x = int((raw_x - low_x) / span_x * (width - 1))
        y = int((raw_y - low_y) / span_y * (height - 1))
        found.append((int(identifier), max(0, min(width - 1, x)),
                      max(0, min(height - 1, y)), bool(down)))
    return found


# --------------------------------------------------------------------------- #
# Handing them to NVDA
# --------------------------------------------------------------------------- #
_manager = None
_down = set()

#: Where each finger that is down was last seen, so it can be COMPLETED
#: there. See `feed`: a lift reported at the wrong place is a flick pointed
#: at the wrong direction.
_where = {}


class TouchSurface:
    """What NVDA's own touch scripts reach for, without a touch screen.

    **This is the piece that was missing, and the pad was useless without
    it.** Feeding contacts to a `TrackerManager` really does produce
    gestures - measured, they arrived as `ts(object):tap` and the rest -
    but NVDA's own touch scripts then do `touchHandler.handler
    .screenExplorer`, and `handler` is None on a machine whose touch
    support never started. Every one of them raised `AttributeError:
    'NoneType' object has no attribute 'screenExplorer'` the moment a
    finger moved: the gesture was recognised, dispatched, and died in the
    script.

    So the add-on provides a handler. Not a pretence of one - it carries
    the three things NVDA's scripts and its core pump actually use, and
    each is the REAL object: `screenExplorer.ScreenExplorer` (which is
    what makes a finger on the pad read what is under it, and is the whole
    of "like a touch screen"), the tracker the contacts go into, and the
    touch mode. `TouchHandler`'s own thread, window and pointer
    registration are what need a touch screen and UI Access, and are
    exactly what is left out.

    Installed only when NVDA has none of its own, and taken away again on
    the way out.
    """

    def __init__(self):
        import screenExplorer
        import touchHandler
        import touchTracker
        self.trackerManager = touchTracker.TrackerManager()
        self.screenExplorer = screenExplorer.ScreenExplorer()
        self._curTouchMode = touchHandler.TouchMode.OBJECT
        self.pendingEmitsTimer = None

    def setMode(self, mode):
        """NVDA's own three-finger tap lands here."""
        import touchHandler
        available = getattr(touchHandler, 'availableTouchModes', ())
        if available and mode not in available:
            raise RuntimeError('Unknown mode %s' % mode)
        self._curTouchMode = mode

    _pumped = 0

    def pump(self):
        """Whatever the tracker has decided, executed. NVDA's core calls it.

        **The gestures are emitted HERE and not where the contacts
        arrive**, which is NVDA's own design and not a detail: a tap is
        held back for a moment in case a second one follows and makes it a
        double tap (`pendingEmitInterval`), so a tracker that is only
        drained when the next finger report arrives emits that tap late,
        or - for the last tap before the user lifts off - never. Being
        pumped repeatedly is what makes a double tap, a hold and a
        tap-and-hold possible at all.
        """
        TouchSurface._pumped += 1
        if TouchSurface._pumped == 1:
            _log('NVDA is pumping the touch handler')
        try:
            _emit(self.trackerManager, self._curTouchMode)
        except Exception as error:                   # noqa: BLE001
            # Never into NVDA's core pump: an exception here is "errors in
            # this core pump cycle", every cycle, for ever.
            _log('emitting gestures failed: %s' % error, error=True)
        self._ask_again()

    def _ask_again(self):
        """Keep the pump coming while the tracker still has something."""
        try:
            import core
            if self.trackerManager.pendingEmitInterval is not None:
                core.requestPump()
        except Exception:                            # noqa: BLE001
            pass

    def notifyInteraction(self, obj):
        """Tell Windows that a touch is interacting with this object.

        **NVDA's own scripts call this and it was not here**, so the very
        first gesture the pad produced died on
        `AttributeError: 'TouchSurface' object has no attribute
        'notifyInteraction'` - seen in the log at the moment a real finger
        made a real tap. The gesture was recognised, dispatched, and threw
        inside the script, which is the same failure the whole class was
        written to fix, one method further along.

        NVDA's is `AccNotifyTouchInteraction(NVDA's window, the object's
        window, the centre of it)`, which is what makes Windows show its
        own touch feedback. It is best-effort by nature - the call is a
        courtesy to the system, and a screen reader must not stop working
        because it failed - so anything it raises is swallowed here rather
        than in the caller.
        """
        try:
            import ctypes
            import api
            location = getattr(obj, 'location', None)
            if not location:
                return
            try:
                point = location.center
                x, y = int(point.x), int(point.y)
            except Exception:                        # noqa: BLE001
                # An older NVDA answers a plain (left, top, width, height).
                left, top, width, height = location[:4]
                x, y = int(left + width / 2), int(top + height / 2)
            ctypes.windll.user32.AccNotifyTouchInteraction(
                ctypes.wintypes.HWND(api.getMainWindowHandle())
                if hasattr(ctypes, 'wintypes') else api.getMainWindowHandle(),
                int(getattr(obj, 'windowHandle', 0) or 0),
                ctypes.wintypes.POINT(x, y))
        except Exception:                            # noqa: BLE001
            # Windows refuses this outright on a machine with no touch
            # digitiser registered, which is most of them and is fine: it
            # is feedback, not function.
            pass

    def terminate(self):
        """NVDA calls this on the way out; there is no thread to join."""
        self.pendingEmitsTimer = None


def _surface():
    """The touch handler in force - NVDA's own, or the one we installed."""
    try:
        import touchHandler
        return getattr(touchHandler, 'handler', None)
    except Exception:                                # noqa: BLE001
        return None


def _install_surface():
    """Give NVDA a touch handler if it has none. ``(ok, why not)``."""
    try:
        import touchHandler
    except Exception as error:                       # noqa: BLE001
        return False, str(error)
    if getattr(touchHandler, 'handler', None) is not None:
        # NVDA has real touch support running; it is in charge and the pad
        # simply adds contacts to the tracker it already has.
        return True, ''
    try:
        touchHandler.handler = TouchSurface()
    except Exception as error:                       # noqa: BLE001
        return False, str(error)
    _held['surface'] = True
    return True, ''


def _remove_surface():
    """Take ours away again, and never NVDA's."""
    if not _held.get('surface'):
        return
    try:
        import touchHandler
        handler = getattr(touchHandler, 'handler', None)
        if isinstance(handler, TouchSurface):
            touchHandler.handler = None
    except Exception:                                # noqa: BLE001
        pass
    _held['surface'] = False


def _tracker_manager():
    """The tracker the contacts go into - the handler's own, always.

    One tracker, so the gestures the pad makes are the gestures NVDA's own
    scripts are pumped for. Keeping a second one of our own is how the
    contacts and the emission end up in two different places.
    """
    global _manager
    handler = _surface()
    if handler is not None and getattr(handler, 'trackerManager', None) \
            is not None:
        return handler.trackerManager
    if _manager is not None:
        return _manager
    try:
        import touchTracker
        _manager = touchTracker.TrackerManager()
    except Exception as error:                       # noqa: BLE001
        with _LOCK:
            _state['why'] = str(error)
        _manager = None
    return _manager


def _mode():
    handler = _surface()
    if handler is not None:
        try:
            return handler._curTouchMode
        except Exception:                            # noqa: BLE001
            pass
    try:
        import touchHandler
        return touchHandler.TouchMode.OBJECT
    except Exception:                                # noqa: BLE001
        return 'object'


def _emit(manager=None, mode=None):
    """Whatever NVDA's own tracker has decided, executed as a gesture.

    On NVDA's main thread, always: a gesture runs a script, and a script
    reads the screen, moves the review cursor and speaks. None of that
    belongs on a thread that is reading HID reports.
    """
    manager = _tracker_manager() if manager is None else manager
    if manager is None or compat.inputCore is None:
        return
    try:
        import touchHandler
    except Exception:                                # noqa: BLE001
        return
    mode = _mode() if mode is None else mode
    for preheld, tracker in list(manager.emitTrackers()):
        try:
            gesture = touchHandler.TouchInputGesture(preheld, tracker, mode)
        except Exception:                            # noqa: BLE001
            continue

        def run(gesture=gesture):
            try:
                compat.inputCore.manager.executeGesture(gesture)
            except Exception:                        # noqa: BLE001
                # An unbound gesture raises NoInputGestureAction, which is
                # not a fault: most gestures are bound to nothing.
                pass
        with _LOCK:
            _state['gestures'] += 1
            if _state['gestures'] == 1:
                _log('first gesture: %s'
                     % (getattr(gesture, 'identifiers', ['?']) or ['?'])[0])
        if compat.queueHandler is None:
            run()
        else:
            compat.queueHandler.queueFunction(
                compat.queueHandler.eventQueue, run)


def feed(contacts):
    """One report's worth of contacts, into NVDA's tracker.

    A finger that was down and is not in this report has LIFTED. The pad
    stops mentioning a contact rather than announcing its end, so nothing
    would ever complete and every touch would be an endless hover - which
    is the one thing a tracker cannot recover from.

    **And it has to be completed WHERE IT WAS.** This used to say
    ``update(gone, 0, 0, True)``, and (0, 0) is the top-left corner of the
    screen. Reported as "exploring works, double tap works, gestures do
    not", and that is exactly the shape the fault has: NVDA's tracker
    decides a flick from the VELOCITY of the last tenth of a second, worked
    out by least squares over the recent samples
    (`touchTracker.SingleTouchTracker`). Handing it a final sample at the
    corner of the screen puts an enormous jump into that window, so every
    flick came out pointing at the top-left whatever the finger really did,
    and `maxAbsDeltaX/Y` was junk as well. Hovering never noticed, because
    it uses the live position while the finger is down; a tap barely
    noticed, because it is decided by how little the finger moved.
    """
    manager = _tracker_manager()
    if manager is None:
        return 0
    seen = set()
    for identifier, x, y, down in contacts:
        seen.add(identifier)
        try:
            manager.update(identifier, x, y, not down)
        except Exception:                            # noqa: BLE001
            continue
        if down:
            _down.add(identifier)
            _where[identifier] = (x, y)
        else:
            _down.discard(identifier)
            _where.pop(identifier, None)
    for gone in list(_down - seen):
        where = _where.pop(gone, None)
        if where is None:
            # It cannot be in `_down` without having had a position, so
            # there is nothing truthful to complete it at - and an invented
            # end point is the whole of what this comment is about.
            _down.discard(gone)
            continue
        try:
            manager.update(gone, where[0], where[1], True)   # where it WAS
        except Exception:                            # noqa: BLE001
            pass
        _down.discard(gone)
    if contacts and not _first['contact']:
        _first['contact'] = True
        _log('first finger: %r' % (contacts[0],))
    with _LOCK:
        _state['contacts'] += len(contacts)
    # **Ask NVDA to pump; do not emit from here.** This is the thread that
    # reads HID reports, and a gesture runs a script that reads the screen
    # and speaks. NVDA's core pump is where its own touch support does it,
    # and going through it is also what gives a tap the moment it needs to
    # become a double tap.
    try:
        import core
        core.requestPump()
    except Exception:                                # noqa: BLE001
        _emit()
    return len(contacts)


# --------------------------------------------------------------------------- #
# The window that receives them
# --------------------------------------------------------------------------- #
_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_uint,
                              ctypes.c_void_p, ctypes.c_void_p) \
    if hasattr(ctypes, 'WINFUNCTYPE') else None


def _nvda_key_down():
    try:
        user32 = ctypes.windll.user32
        return any(user32.GetAsyncKeyState(key) & 0x8000
                   for key in (VK_INSERT, VK_CAPITAL, VK_NUMPAD0))
    except Exception:                                # noqa: BLE001
        return False


def _wheel(delta):
    """NVDA + the horizontal wheel: right turns this on, left turns it off.

    A trackpad's two-finger sideways swipe IS the horizontal wheel, so the
    gesture that switches trackpad support on is one the trackpad itself
    can make - which matters when the reason to switch it on is that the
    user is holding a trackpad.
    """
    if not _nvda_key_down():
        return
    if delta > 0:
        if not _state['on']:
            start()
            _say(_('Trackpad gestures on.'))
    elif delta < 0:
        if _state['on']:
            stop()
            _say(_('Trackpad gestures off.'))


def _say(text):
    if compat.queueHandler is None or compat.ui is None:
        return
    def speak():
        try:
            compat.ui.message(text)
        except Exception:                            # noqa: BLE001
            pass
    compat.queueHandler.queueFunction(compat.queueHandler.eventQueue, speak)


#: Said once each, so one touch of the pad answers the whole question:
#: did Windows send anything, did it parse, did a gesture come out. Every
#: one of these was invisible before, and "no gestures" could have meant
#: any of the three.
_first = {'message': False, 'contact': False, 'hid': False}


def _handle_input(lparam):
    user32 = ctypes.windll.user32
    if not _first['message']:
        _first['message'] = True
        _log('Windows is sending raw input')
    size = wintypes.UINT(0)
    header = ctypes.sizeof(RAWINPUTHEADER)
    if user32.GetRawInputData(ctypes.c_void_p(lparam), RID_INPUT, None,
                              ctypes.byref(size), header) != 0:
        return
    if not size.value:
        return
    buffer = ctypes.create_string_buffer(size.value)
    if user32.GetRawInputData(ctypes.c_void_p(lparam), RID_INPUT, buffer,
                              ctypes.byref(size), header) != size.value:
        return
    head = RAWINPUTHEADER.from_buffer_copy(buffer.raw[:header])
    if head.dwType == RIM_TYPEMOUSE:
        # usButtonFlags is the first USHORT after the header's 8-byte
        # dwFlags/ulButtons preamble; the horizontal wheel puts its amount
        # in the high word of usButtonData beside it.
        try:
            flags, data = ctypes.cast(
                ctypes.byref(buffer, header + 4),
                ctypes.POINTER(wintypes.USHORT * 2)).contents
            if flags & RI_MOUSE_HWHEEL:
                amount = ctypes.c_short(data).value
                _wheel(amount)
        except Exception:                            # noqa: BLE001
            pass
        return
    if head.dwType != RIM_TYPEHID:
        return
    if not _first['hid']:
        _first['hid'] = True
        _log('the pad is sending reports')
    # RAWHID: dwSizeHid, dwCount, then the reports one after another.
    try:
        sizes = ctypes.cast(ctypes.byref(buffer, header),
                            ctypes.POINTER(wintypes.DWORD * 2)).contents
        one, many = int(sizes[0]), int(sizes[1])
    except Exception:                                # noqa: BLE001
        return
    start_at = header + 8
    for index in range(min(many, 16)):
        piece = buffer.raw[start_at + index * one:start_at + (index + 1) * one]
        if len(piece) != one:
            break
        try:
            feed(contacts_in(ctypes.create_string_buffer(piece, one), one,
                             head.hDevice))
        except Exception:                            # noqa: BLE001
            continue


def _loop():
    user32 = ctypes.windll.user32

    def procedure(hwnd, message, wparam, lparam):
        if message == WM_INPUT:
            try:
                _handle_input(lparam)
            except Exception:                        # noqa: BLE001
                pass
        return int(user32.DefWindowProcW(ctypes.c_void_p(hwnd), message,
                                         ctypes.c_void_p(wparam),
                                         ctypes.c_void_p(lparam)))

    class WNDCLASS(ctypes.Structure):
        _fields_ = [('style', ctypes.c_uint), ('lpfnWndProc', _WNDPROC),
                    ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                    ('hInstance', ctypes.c_void_p), ('hIcon', ctypes.c_void_p),
                    ('hCursor', ctypes.c_void_p),
                    ('hbrBackground', ctypes.c_void_p),
                    ('lpszMenuName', ctypes.c_wchar_p),
                    ('lpszClassName', ctypes.c_wchar_p)]

    _held['proc'] = _WNDPROC(procedure)
    name = 'TitanEnhancementsTrackpad'
    wanted = WNDCLASS()
    wanted.lpfnWndProc = _held['proc']
    wanted.lpszClassName = name
    try:
        wanted.hInstance = ctypes.c_void_p(
            ctypes.windll.kernel32.GetModuleHandleW(None))
    except Exception:                                # noqa: BLE001
        wanted.hInstance = None
    _held['class'] = wanted
    try:
        user32.RegisterClassW(ctypes.byref(wanted))
        user32.CreateWindowExW.restype = ctypes.c_void_p
            # **`hInstance` must go back as a POINTER.** Reading it off
            # the class structure gives a plain Python int, and a module
            # handle is too large for the C int ctypes converts a bare int
            # into: `CreateWindowExW` raises `OverflowError: int too long
            # to convert` before Windows is ever called. Caught by driving
            # the real thing - both windows here failed at creation, which
            # each module then reported as "the window would not be
            # created" and nobody would have known why.
        hwnd = int(user32.CreateWindowExW(0, ctypes.c_wchar_p(name),
                                          ctypes.c_wchar_p(name), 0, 0, 0, 0,
                                          0, ctypes.c_void_p(HWND_MESSAGE),
                                          None,
                                          ctypes.c_void_p(wanted.hInstance),
                                          None) or 0)
    except Exception as error:                       # noqa: BLE001
        with _LOCK:
            _state['why'] = 'the window would not be created: %s' % error
        _log(_state['why'], error=True)
        return
    if not hwnd:
        with _LOCK:
            _state['why'] = 'the window would not be created'
        _log(_state['why'], error=True)
        return
    devices = (RAWINPUTDEVICE * 2)()
    devices[0].usUsagePage = HID_USAGE_PAGE_DIGITIZER
    devices[0].usUsage = HID_USAGE_DIGITIZER_TOUCH_PAD
    devices[0].dwFlags = RIDEV_INPUTSINK
    devices[0].hwndTarget = hwnd
    devices[1].usUsagePage = HID_USAGE_PAGE_GENERIC
    devices[1].usUsage = HID_USAGE_GENERIC_MOUSE
    devices[1].dwFlags = RIDEV_INPUTSINK
    devices[1].hwndTarget = hwnd
    if not user32.RegisterRawInputDevices(devices, 2,
                                          ctypes.sizeof(RAWINPUTDEVICE)):
        try:
            code = ctypes.GetLastError()
        except Exception:                            # noqa: BLE001
            code = 0
        with _LOCK:
            _state['why'] = ('Windows refused to send the pad\'s reports '
                             '(error %d)' % code)
        _log(_state['why'], error=True)
        user32.DestroyWindow(ctypes.c_void_p(hwnd))
        _held['proc'] = None
        return
    with _LOCK:
        _state.update({'on': True, 'why': '', 'hwnd': hwnd,
                       'started': time.time()})

    class MSG(ctypes.Structure):
        _fields_ = [('hwnd', ctypes.c_void_p), ('message', ctypes.c_uint),
                    ('wParam', ctypes.c_void_p), ('lParam', ctypes.c_void_p),
                    ('time', ctypes.c_uint), ('pt_x', ctypes.c_long),
                    ('pt_y', ctypes.c_long)]
    message = MSG()
    while True:
        got = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
        if got in (0, -1):
            break
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))
    try:
        user32.DestroyWindow(ctypes.c_void_p(hwnd))
    except Exception:                                # noqa: BLE001
        pass
    _held['proc'] = None
    _held['class'] = None
    with _LOCK:
        _state.update({'on': False, 'hwnd': 0})


_thread = None


def running():
    with _LOCK:
        return bool(_state['on'])


def start():
    """Begin reading the pad. ``(ok, sentence)``."""
    global _thread
    ready, why = available()
    if not ready:
        with _LOCK:
            _state['why'] = why
        _log('not starting - %s' % why, error=True)
        return False, why
    if running():
        return True, _('Trackpad gestures are already on.')
    if _WNDPROC is None:
        return False, _('This Python has no stdcall callbacks.')
    # NVDA's own touch scripts need a handler to exist before the first
    # gesture arrives, or every one of them raises where nobody sees it.
    ready, why = _install_surface()
    if not ready:
        with _LOCK:
            _state['why'] = why
        _log('no touch handler could be made - %s' % why, error=True)
        return False, why
    _log('touch handler %s'
         % ('installed' if _held.get('surface') else "is NVDA's own"))
    _thread = threading.Thread(target=_loop, name='TitanTrackpad',
                               daemon=True)
    _thread.start()
    for _wait in range(40):
        if running():
            _log('reading the pad')
            return True, _('Trackpad gestures on.')
        time.sleep(0.05)
    with _LOCK:
        why = _state['why'] or _('the pad did not start')
    _log('did not start - %s' % why, error=True)
    return False, why


def stop():
    """Give the pad back. Idempotent."""
    _remove_surface()
    with _LOCK:
        hwnd = int(_state['hwnd'] or 0)
    if not hwnd:
        with _LOCK:
            _state['on'] = False
        return True
    try:
        ctypes.windll.user32.PostMessageW(ctypes.c_void_p(hwnd), WM_CLOSE,
                                          0, 0)
    except Exception:                                # noqa: BLE001
        pass
    return True


def toggle():
    if running():
        stop()
        return False, _('Trackpad gestures off.')
    ok, said = start()
    return ok, said
