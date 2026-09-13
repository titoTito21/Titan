# -*- coding: utf-8 -*-
"""What KIND of dialog this is - anywhere on Windows, not only in Titan.

Titan Access has always said it: a question, a warning, an error, a notice,
each with its own tone and the word said a little lower. Titan tells the
reader which, because a skinned dialog's icon is not reliably detectable
from outside and a confirmation the user cannot tell from a notice is a
confirmation they will answer wrongly.

That was true of Titan's dialogs and left every other dialog on the machine
sounding the same. A message box in Explorer, an installer's "are you
sure", a browser's "your changes will be lost" - all of them arrive as a
name, a role and some buttons, and whether the answer matters is something
the user has to work out from the words.

**It does not have to be told; on Windows it can be read.** A dialog put up
by ``MessageBox`` carries a standard icon in a static control, and the four
system icons are shared handles - the same ``HICON`` this process gets from
``LoadIcon(NULL, IDI_*)``. That is a comparison of two numbers, and it is
exact: no picture is examined, nothing is guessed, and it costs a handful of
microseconds on a window that has just appeared.

Where there is no icon there is still the dialog's own SHAPE. A box with Yes
and No in it is a question - not by resemblance but by construction, because
those are the answers it will accept. A box offering Abort, Retry and Ignore
is reporting a failure. Both are read off the standard control ids, so they
are the same in every language.

**Nothing here needs Titan, and nothing here needs Titan Access.** Titan
Access is an optional component, so the word said is the ADD-ON's own,
translated with the rest of it. When Titan itself raises a dialog it still
pushes its own word through :func:`interject.dialog_kind` - the same word
its own reader says - and that path is untouched and wins, so a user with
both hears one vocabulary and a user with neither still hears the kind.
"""

import ctypes
import threading

from . import compat
from . import i18n

_ = i18n.install(globals())

#: The four, in NVDA's own terms and Titan Access's.
KINDS = ('question', 'information', 'warning', 'error')

#: **The icon a dialog carries, matched by its PIXELS.**
#:
#: The first attempt here compared icon HANDLES: Windows' four system icons
#: are shared, so `LoadIcon(NULL, IDI_*)` gives the same `HICON` the dialog
#: holds. Measured against four real message boxes, that is simply false -
#: a message box makes an icon of its own (`0x5a100b85` where the shared
#: one is `0x1002d`), so the comparison matched nothing, every time, and
#: the whole feature was quietly answering "I cannot tell".
#:
#: The second attempt hashed the drawn pixels and also matched nothing. The
#: third measured HOW different they were, which is what found it: on
#: Windows 10 and 11 a message box does not use the legacy `IDI_*` icons at
#: all. It uses the SHELL's stock icons, and the mean difference between
#: what the dialog holds and `SHGetStockIconInfo` is **0.1** per channel -
#: a couple of anti-aliased pixels - against 4.7 for the nearest other
#: stock icon and 26 to 45 for the legacy ones it was being compared with.
#:
#: So: draw both, compare, and accept the nearest only when it is clearly
#: nearest. An exact hash is the wrong instrument for two renderings of one
#: picture; a threshold with a margin under it is the right one, and the
#: numbers below are the measured ones and not a guess.
STOCK_ICONS = (
    (78, 'warning'),        # SIID_WARNING
    (79, 'information'),    # SIID_INFO
    (80, 'error'),          # SIID_ERROR
    (23, 'question'),       # SIID_HELP - what MB_ICONQUESTION really shows
)

#: The legacy four, still what an older Windows and a program with its own
#: dialog template put up. Kept BESIDE the stock ones rather than instead
#: of them: both are true, on different machines and in different programs.
LEGACY_ICONS = (
    (32513, 'error'), (32514, 'question'),
    (32515, 'warning'), (32516, 'information'),
)

#: How close counts as the same picture, and how much clearer the winner
#: must be than the runner-up. Measured: the right answer scores 0.1 and
#: the next one 4.7, so there is a wide gap to sit in - and a dialog whose
#: icon is somebody's own artwork lands near nothing and is answered "I
#: cannot tell", which is the honest answer.
SAME_PICTURE = 2.0
CLEAR_MARGIN = 2.0

#: The icon is drawn at this size to be compared. 32 is what a message box
#: uses; anything else is scaled to it, which is what makes a dialog with a
#: large icon comparable with a reference at the ordinary size.
ICON_SIZE = 32

#: The control id `MessageBox` gives its icon. Looked for first, and then
#: any static that is an icon at all - a program with its own dialog
#: template numbers its controls however it likes.
_ICON_ID = 0x0014
_STM_GETICON = 0x0171
_SS_TYPEMASK = 0x1F
_SS_ICON = 0x03


#: The standard answer buttons, by the ids Windows gives them. Language
#: independent, which is the whole reason to read the id rather than the
#: label.
_IDOK, _IDCANCEL, _IDABORT, _IDRETRY, _IDIGNORE, _IDYES, _IDNO = range(1, 8)

#: What a dialog's own buttons prove about it.
#:
#: Deliberately only the two that are certain. A box with Yes and No IS a
#: question - those are the answers it takes. A box offering Abort, Retry
#: and Ignore IS reporting something that failed. An OK-and-Cancel box is
#: NOT inferred from: it may be a confirmation or a settings page, and an
#: error box with a lone OK button called "information" would be worse than
#: saying nothing at all, which is what this does instead.
_BY_BUTTONS = (
    (('yes', 'no'), 'question'),
    (('abort', 'retry', 'ignore'), 'error'),
)

_LOCK = threading.RLock()
_seen = {}
_counted = {'icon': 0, 'drawn': 0, 'buttons': 0, 'none': 0}


def counts():
    with _LOCK:
        return dict(_counted)


def forget():
    del _references[:]
    _backgrounds.clear()
    with _LOCK:
        _seen.clear()
        for key in _counted:
            _counted[key] = 0


def _user32():
    try:
        return ctypes.windll.user32
    except Exception:                                # noqa: BLE001
        return None


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', ctypes.c_uint32), ('biWidth', ctypes.c_int32),
                ('biHeight', ctypes.c_int32), ('biPlanes', ctypes.c_uint16),
                ('biBitCount', ctypes.c_uint16),
                ('biCompression', ctypes.c_uint32),
                ('biSizeImage', ctypes.c_uint32),
                ('biXPelsPerMeter', ctypes.c_int32),
                ('biYPelsPerMeter', ctypes.c_int32),
                ('biClrUsed', ctypes.c_uint32),
                ('biClrImportant', ctypes.c_uint32)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [('bmiHeader', _BITMAPINFOHEADER),
                ('bmiColors', ctypes.c_uint32 * 3)]


class _RECT(ctypes.Structure):
    _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long),
                ('right', ctypes.c_long), ('bottom', ctypes.c_long)]


class _SHSTOCKICONINFO(ctypes.Structure):
    _fields_ = [('cbSize', ctypes.c_uint32), ('hIcon', ctypes.c_void_p),
                ('iSysImageIndex', ctypes.c_int), ('iIcon', ctypes.c_int),
                ('szPath', ctypes.c_wchar * 260)]


def _drawn(hicon, background=None):
    """The icon's pixels, drawn at :data:`ICON_SIZE`. ``None`` for nothing.

    Drawn rather than read out of the bitmap, because the two pictures being
    compared may be stored differently - one 32-bit with an alpha channel,
    one a colour bitmap and a mask - and what matters is what they LOOK
    like. Everything is released; an icon comparison that leaked a device
    context per dialog would be a reader that runs a machine out of GDI
    handles in a day.
    """
    if not hicon:
        return None
    try:
        gdi32 = ctypes.windll.gdi32
        user32 = _user32()
    except Exception:                                # noqa: BLE001
        return None
    if user32 is None:
        return None
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateDIBSection.restype = ctypes.c_void_p
    gdi32.SelectObject.restype = ctypes.c_void_p
    dc = bitmap = old = None
    try:
        dc = gdi32.CreateCompatibleDC(None)
        if not dc:
            return None
        info = _BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        info.bmiHeader.biWidth = ICON_SIZE
        info.bmiHeader.biHeight = -ICON_SIZE       # top down
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        bits = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(ctypes.c_void_p(dc),
                                        ctypes.byref(info), 0,
                                        ctypes.byref(bits), None, 0)
        if not bitmap:
            return None
        old = gdi32.SelectObject(ctypes.c_void_p(dc), ctypes.c_void_p(bitmap))
        ctypes.memset(bits, 0, ICON_SIZE * ICON_SIZE * 4)
        if background is not None:
            brush = gdi32.CreateSolidBrush(int(background))
            area = _RECT(0, 0, ICON_SIZE, ICON_SIZE)
            user32.FillRect(ctypes.c_void_p(dc), ctypes.byref(area),
                            ctypes.c_void_p(brush))
            gdi32.DeleteObject(ctypes.c_void_p(brush))
        drawn = user32.DrawIconEx(ctypes.c_void_p(dc), 0, 0,
                                  ctypes.c_void_p(hicon), ICON_SIZE,
                                  ICON_SIZE, 0, None, 0x0003)   # DI_NORMAL
        if not drawn:
            return None
        return ctypes.string_at(bits, ICON_SIZE * ICON_SIZE * 4)
    except Exception:                                # noqa: BLE001
        return None
    finally:
        try:
            if old:
                gdi32.SelectObject(ctypes.c_void_p(dc), ctypes.c_void_p(old))
            if bitmap:
                gdi32.DeleteObject(ctypes.c_void_p(bitmap))
            if dc:
                gdi32.DeleteDC(ctypes.c_void_p(dc))
        except Exception:                            # noqa: BLE001
            pass


def _difference(one, other):
    """Mean absolute difference per COLOUR byte. Small is the same picture.

    The alpha byte is skipped, and that is not tidiness: an icon drawn by
    `DrawIconEx` carries one and a square captured off the screen does not,
    so comparing it would put a constant difference between every pair and
    swamp the thing being measured.
    """
    if not one or not other or len(one) != len(other):
        return 999.0
    total = 0
    count = 0
    for index in range(0, len(one) - 3, 4):
        for channel in range(3):
            total += abs(one[index + channel] - other[index + channel])
            count += 1
    return (total / float(count)) if count else 999.0


_references = []


def _known_icons():
    """The reference pictures, drawn once.

    Once, because they do not change for the life of the session and this
    is reached from a window that has just appeared - a moment the user is
    already waiting through, but not one to spend eight icon renderings in
    twice.
    """
    if _references:
        return list(_references)
    user32 = _user32()
    if user32 is None:
        return []
    try:
        user32.LoadIconW.restype = ctypes.c_void_p
    except Exception:                                # noqa: BLE001
        return []
    for number, kind in LEGACY_ICONS:
        try:
            handle = int(user32.LoadIconW(None, ctypes.c_void_p(number)) or 0)
        except Exception:                            # noqa: BLE001
            continue
        picture = _drawn(handle)
        if picture:
            _references.append((kind, picture))
    try:
        shell32 = ctypes.windll.shell32
    except Exception:                                # noqa: BLE001
        shell32 = None
    if shell32 is not None:
        for siid, kind in STOCK_ICONS:
            info = _SHSTOCKICONINFO()
            info.cbSize = ctypes.sizeof(_SHSTOCKICONINFO)
            try:
                # SHGSI_ICON
                if shell32.SHGetStockIconInfo(siid, 0x000000100,
                                              ctypes.byref(info)) != 0:
                    continue
            except Exception:                        # noqa: BLE001
                continue
            picture = _drawn(int(info.hIcon or 0))
            if picture:
                _references.append((kind, picture))
    return list(_references)


def stock_icon(siid):
    """The shell's own icon for that `SIID`, as a handle. ``0`` for none.

    Lifted out of the reference builder so :mod:`iconNames` can ask for
    the same pictures without a second copy of the call - there is one
    way to get a stock icon and this is it.
    """
    try:
        shell32 = ctypes.windll.shell32
    except Exception:                                # noqa: BLE001
        return 0
    info = _SHSTOCKICONINFO()
    info.cbSize = ctypes.sizeof(_SHSTOCKICONINFO)
    try:
        # SHGSI_ICON
        if shell32.SHGetStockIconInfo(int(siid), 0x000000100,
                                      ctypes.byref(info)) != 0:
            return 0
    except Exception:                                # noqa: BLE001
        return 0
    return int(info.hIcon or 0)


def window_icon(hwnd):
    """The icon a WINDOW carries, as a handle. ``0`` for none.

    `WM_GETICON` first, because that is the window's own; the class icon
    after it, because a window that never set one still shows the
    program's. Asked with a timeout the way Titan's shell asks - a window
    that has hung must not hold the reader.
    """
    user32 = _user32()
    if user32 is None or not hwnd:
        return 0
    try:
        user32.SendMessageW.restype = ctypes.c_void_p
        for which in (1, 0, 2):          # BIG, SMALL, SMALL2
            handle = int(user32.SendMessageW(ctypes.c_void_p(int(hwnd)),
                                             0x007F, which, 0) or 0)
            if handle:
                return handle
    except Exception:                                # noqa: BLE001
        pass
    for index in (-14, -34):             # GCLP_HICON, GCLP_HICONSM
        try:
            user32.GetClassLongPtrW.restype = ctypes.c_void_p
            handle = int(user32.GetClassLongPtrW(ctypes.c_void_p(int(hwnd)),
                                                 index) or 0)
        except Exception:                            # noqa: BLE001
            continue
        if handle:
            return handle
    return 0


def _closest(picture, references=None):
    """The kind this picture is, or ''.

    Accepted only when it is close AND clearly closer than anything else:
    a dialog carrying somebody's own artwork lands near nothing and is
    answered "I cannot tell", which is the honest answer and the one that
    leaves NVDA's own report exactly as it was.
    """
    if not picture:
        return ''
    scored = sorted((_difference(picture, reference), kind)
                    for kind, reference
                    in (_known_icons() if references is None else references))
    if not scored:
        return ''
    best, kind = scored[0]
    if best > SAME_PICTURE:
        return ''
    if len(scored) > 1:
        for score, other in scored[1:]:
            if other == kind:
                continue
            if score - best < CLEAR_MARGIN:
                return ''
            break
    return kind


_ENUM_CHILD = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p,
                                 ctypes.c_void_p) \
    if hasattr(ctypes, 'WINFUNCTYPE') else None


def _icon_windows(hwnd):
    """Every static in this dialog that is an icon, the standard one first.

    A program with its own dialog template numbers its controls however it
    likes, so the id `MessageBox` uses is asked for first and then every
    child that is a static with `SS_ICON` - which is what an icon in a
    dialog IS, whoever built it.
    """
    user32 = _user32()
    if user32 is None or not hwnd:
        return []
    found = []
    try:
        user32.GetDlgItem.restype = ctypes.c_void_p
        standard = user32.GetDlgItem(ctypes.c_void_p(hwnd), _ICON_ID)
        if standard:
            found.append(int(standard))
    except Exception:                                # noqa: BLE001
        pass
    if _ENUM_CHILD is None:
        return found

    def each(child, _lparam):
        try:
            name = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(ctypes.c_void_p(child), name, 64)
            if str(name.value or '').lower() != 'static':
                return True
            style = int(user32.GetWindowLongW(ctypes.c_void_p(child), -16))
            if (style & _SS_TYPEMASK) == _SS_ICON and int(child) not in found:
                found.append(int(child))
        except Exception:                            # noqa: BLE001
            pass
        return True
    try:
        user32.EnumChildWindows(ctypes.c_void_p(hwnd), _ENUM_CHILD(each), None)
    except Exception:                                # noqa: BLE001
        pass
    return found


def _icon_kind(hwnd):
    """The kind, from the dialog's own icon, or ''."""
    user32 = _user32()
    if user32 is None or not hwnd:
        return ''
    for window in _icon_windows(hwnd)[:4]:
        try:
            user32.SendMessageW.restype = ctypes.c_void_p
            handle = int(user32.SendMessageW(ctypes.c_void_p(window),
                                             _STM_GETICON, 0, 0) or 0)
        except Exception:                            # noqa: BLE001
            continue
        if not handle:
            continue
        kind = _closest(_drawn(handle))
        if kind:
            return kind
    return ''


def _has_button(hwnd, control_id):
    user32 = _user32()
    if user32 is None:
        return False
    try:
        user32.GetDlgItem.restype = ctypes.c_void_p
        window = user32.GetDlgItem(ctypes.c_void_p(hwnd), int(control_id))
    except Exception:                                # noqa: BLE001
        return False
    if not window:
        return False
    try:
        return bool(user32.IsWindowVisible(ctypes.c_void_p(window)))
    except Exception:                                # noqa: BLE001
        return True


def _button_kind(hwnd):
    """The kind the dialog's own answers prove, or ''."""
    if not hwnd:
        return ''
    ids = {'ok': _IDOK, 'cancel': _IDCANCEL, 'abort': _IDABORT,
           'retry': _IDRETRY, 'ignore': _IDIGNORE, 'yes': _IDYES,
           'no': _IDNO}
    present = {name for name, number in ids.items()
               if _has_button(hwnd, number)}
    for wanted, kind in _BY_BUTTONS:
        if set(wanted) <= present:
            return kind
    return ''


#: A task dialog - `TaskDialog()`, Vista onwards, and what a modern
#: Windows really puts up - is a `#32770` like any other, with its whole
#: interface inside one `DirectUIHWND`. There is no icon CONTROL in it, so
#: the reading above finds nothing; what there is instead is an image
#: element that accessibility exposes, named by the dialog itself.
TASK_DIALOG_CHILD = 'DirectUIHWND'
TASK_DIALOG_ICON = 'maininstructionicon'

#: How big a drawn icon may be and still be the dialog's own. A task
#: dialog's is 32 at 100%; a high-DPI machine draws it larger.
DRAWN_MIN = 16
DRAWN_MAX = 96


def is_task_dialog(obj):
    """Whether this is a task dialog rather than a message box."""
    try:
        children = list(obj.children or [])[:8]
    except Exception:                                # noqa: BLE001
        return False
    for child in children:
        if str(getattr(child, 'windowClassName', '') or '') \
                == TASK_DIALOG_CHILD:
            return True
    return False


def _icon_element(obj, depth=0):
    """The image a task dialog draws its icon into, or None.

    Found through NVDA's own object tree rather than through UI Automation
    directly: NVDA has already built it, it is the same tree, and an add-on
    that talked to UIA itself would be a second implementation of something
    the reader is holding in its hand.
    """
    if obj is None or depth > 5:
        return None
    try:
        children = list(obj.children or [])[:24]
    except Exception:                                # noqa: BLE001
        return None
    for child in children:
        name = str(getattr(child, 'name', '') or '').strip().lower()
        role = str(getattr(getattr(child, 'role', None), 'name', '')
                   or '').upper()
        if name == TASK_DIALOG_ICON:
            return child
        if role in ('GRAPHIC', 'ICON'):
            try:
                where = child.location
            except Exception:                        # noqa: BLE001
                where = None
            if where and DRAWN_MIN <= int(where[2]) <= DRAWN_MAX \
                    and abs(int(where[2]) - int(where[3])) <= 4:
                return child
        found = _icon_element(child, depth + 1)
        if found is not None:
            return found
    return None


def _from_the_screen(where):
    """The pixels of a square of the screen, at :data:`ICON_SIZE`."""
    try:
        left, top, width, height = (int(one) for one in where[:4])
    except Exception:                                # noqa: BLE001
        return None
    if width <= 0 or height <= 0:
        return None
    user32 = _user32()
    if user32 is None:
        return None
    try:
        gdi32 = ctypes.windll.gdi32
        user32.GetDC.restype = ctypes.c_void_p
        screen = user32.GetDC(None)
    except Exception:                                # noqa: BLE001
        return None
    if not screen:
        return None
    dc = bitmap = old = None
    try:
        gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
        gdi32.CreateDIBSection.restype = ctypes.c_void_p
        gdi32.SelectObject.restype = ctypes.c_void_p
        dc = gdi32.CreateCompatibleDC(None)
        if not dc:
            return None
        info = _BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        info.bmiHeader.biWidth = ICON_SIZE
        info.bmiHeader.biHeight = -ICON_SIZE
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        bits = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(ctypes.c_void_p(dc),
                                        ctypes.byref(info), 0,
                                        ctypes.byref(bits), None, 0)
        if not bitmap:
            return None
        old = gdi32.SelectObject(ctypes.c_void_p(dc), ctypes.c_void_p(bitmap))
        gdi32.SetStretchBltMode(ctypes.c_void_p(dc), 4)       # HALFTONE
        gdi32.StretchBlt(ctypes.c_void_p(dc), 0, 0, ICON_SIZE, ICON_SIZE,
                         ctypes.c_void_p(screen), left, top, width, height,
                         0x00CC0020)                          # SRCCOPY
        return ctypes.string_at(bits, ICON_SIZE * ICON_SIZE * 4)
    except Exception:                                # noqa: BLE001
        return None
    finally:
        try:
            if old:
                gdi32.SelectObject(ctypes.c_void_p(dc), ctypes.c_void_p(old))
            if bitmap:
                gdi32.DeleteObject(ctypes.c_void_p(bitmap))
            if dc:
                gdi32.DeleteDC(ctypes.c_void_p(dc))
            user32.ReleaseDC(None, ctypes.c_void_p(screen))
        except Exception:                            # noqa: BLE001
            pass


def _on_background(colour):
    """The reference icons drawn onto ``colour``, kept per colour.

    A screen capture has the dialog's background behind the icon and no
    alpha at all, so the references have to be drawn onto the same
    background before the two can be compared. The colour is sampled from
    the capture's own corner rather than assumed to be white - a dialog in
    the dark theme is not white, and a wrong background is what turns a
    match into a near miss.
    """
    kept = _backgrounds.get(colour)
    if kept is not None:
        return kept
    made = []
    user32 = _user32()
    if user32 is None:
        return made
    try:
        gdi32 = ctypes.windll.gdi32
        shell32 = ctypes.windll.shell32
    except Exception:                                # noqa: BLE001
        return made
    handles = []
    try:
        user32.LoadIconW.restype = ctypes.c_void_p
        for number, kind in LEGACY_ICONS:
            handles.append((kind, int(user32.LoadIconW(
                None, ctypes.c_void_p(number)) or 0)))
        for siid, kind in STOCK_ICONS:
            info = _SHSTOCKICONINFO()
            info.cbSize = ctypes.sizeof(_SHSTOCKICONINFO)
            if shell32.SHGetStockIconInfo(siid, 0x000000100,
                                          ctypes.byref(info)) == 0:
                handles.append((kind, int(info.hIcon or 0)))
    except Exception:                                # noqa: BLE001
        pass
    for kind, handle in handles:
        picture = _drawn(handle, background=colour)
        if picture:
            made.append((kind, picture))
    if len(_backgrounds) > 8:
        _backgrounds.clear()
    _backgrounds[colour] = made
    return made


_backgrounds = {}


def _drawn_kind(obj):
    """The kind of a dialog that DRAWS its icon rather than holding one.

    **Safe by construction, which is what makes it shippable.** The capture
    can fail for reasons this cannot see - the dialog covered by something,
    a display scaling the coordinates differently - and a failed capture is
    a square of flat background. Measured that way deliberately: a flat
    square scores 60 or more against every reference, and the threshold
    that lets a real icon through is 2. So a capture that did not work
    answers "I cannot tell" rather than the icon that happens to have the
    most background in it.
    """
    element = _icon_element(obj)
    if element is None:
        return ''
    try:
        where = element.location
    except Exception:                                # noqa: BLE001
        return ''
    picture = _from_the_screen(where or ())
    if not picture:
        return ''
    colour = picture[0] | (picture[1] << 8) | (picture[2] << 16)
    return _closest(picture, _on_background(colour))


def _root(hwnd):
    """The dialog itself, from whatever handle we were given."""
    user32 = _user32()
    if user32 is None or not hwnd:
        return int(hwnd or 0)
    try:
        user32.GetAncestor.restype = ctypes.c_void_p
        return int(user32.GetAncestor(ctypes.c_void_p(int(hwnd)), 2) or hwnd)
    except Exception:                                # noqa: BLE001
        return int(hwnd or 0)


def is_dialog(obj):
    """Whether this is a dialog at all, by role or by window class."""
    role = str(getattr(getattr(obj, 'role', None), 'name', '') or '').upper()
    if role in ('DIALOG', 'ALERT'):
        return True
    return str(getattr(obj, 'windowClassName', '') or '') == '#32770'


def kind_of(obj):
    """``(kind, how)`` for this dialog. ``('', '')`` when it cannot be told.

    ``how`` is 'icon' when the dialog really carries one of Windows' four
    and 'buttons' when it was read off what the dialog will accept as an
    answer. The two are kept apart because they are different strengths of
    claim, and a caller that wants only the certain one can have it.
    """
    if obj is None or not is_dialog(obj):
        return '', ''
    try:
        hwnd = _root(int(getattr(obj, 'windowHandle', 0) or 0))
    except (TypeError, ValueError):
        return '', ''
    if not hwnd:
        return '', ''
    kind = _icon_kind(hwnd)
    if kind:
        with _LOCK:
            _counted['icon'] += 1
        return kind, 'icon'
    if is_task_dialog(obj):
        kind = _drawn_kind(obj)
        if kind:
            with _LOCK:
                _counted['drawn'] += 1
            return kind, 'drawn'
    kind = _button_kind(hwnd)
    if kind:
        with _LOCK:
            _counted['buttons'] += 1
        return kind, 'buttons'
    with _LOCK:
        _counted['none'] += 1
    return '', ''


def word(kind):
    """The kind as the word this add-on says for it.

    The add-on's own, because Titan Access - whose catalogue these words
    match - is an OPTIONAL component and half the machines this runs on
    will not have it. Where Titan does raise the dialog it pushes its own
    word, and that path wins, so nobody ends up with two vocabularies.
    """
    return {
        # Translators: the kind of a dialog, said with the dialog's own tone.
        'question': _('question'),
        # Translators: the kind of a dialog.
        'information': _('information'),
        # Translators: the kind of a dialog.
        'warning': _('warning'),
        # Translators: the kind of a dialog.
        'error': _('error'),
    }.get(kind, '')


def wanted():
    """Whether the reader may say what kind of dialog this is.

    The switch lives in NVDA's own configuration, which the OTHER reader
    has not got - and this file is shared between them. Absent, the
    answer is yes: a reader without that switch has not turned it off.
    """
    try:
        from . import configSpec
    except Exception:                                # noqa: BLE001
        return True
    return bool(configSpec.read().get('dialogKinds', True))


def announce(obj):
    """Say what kind of dialog has just appeared. ``''`` for nothing.

    Said ONCE per dialog window: a dialog whose focus moves between its own
    controls is the same dialog, and a reader that said "question" on every
    control of it would be the bug this add-on has already fixed once for
    regions.
    """
    if not wanted():
        return ''
    kind, how = kind_of(obj)
    if not kind:
        return ''
    try:
        hwnd = _root(int(getattr(obj, 'windowHandle', 0) or 0))
    except (TypeError, ValueError):
        hwnd = 0
    with _LOCK:
        if _seen.get(hwnd) == kind:
            return ''
        # A dialog handle is reused as freely as any other; the map is
        # small and is cleared whenever the add-on stops.
        if len(_seen) > 64:
            _seen.clear()
        _seen[hwnd] = kind
    # **Said through NVDA's own speech filter where there is one.** That
    # is what puts the word in the SAME utterance as the dialog's own
    # report, so it cannot be cut off by it. The other reader has no such
    # filter and says it itself.
    try:
        from . import interject
        interject.dialog_kind(kind=kind, label=word(kind))
    except Exception:                                # noqa: BLE001
        try:
            from . import compat
            if compat.ui is not None:
                compat.ui.message(word(kind))
        except Exception:                            # noqa: BLE001
            pass
    return kind


def report():
    """What this layer has really done, for the status command."""
    found = counts()
    return {'icon': found['icon'], 'drawn': found['drawn'],
            'buttons': found['buttons'], 'undecided': found['none'],
            'available': _user32() is not None,
            'enabled': wanted()}
