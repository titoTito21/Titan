# -*- coding: utf-8 -*-
"""What an icon IS, named without asking anybody.

A reader that says "graphic" for a warning triangle, a folder, a printer
and a photograph of a dog has said one word about four different things.
The AI can describe any of them and costs a picture of the user's screen
at a provider; this names the ones that can be named for certain, here,
in about a millisecond and with nothing leaving the machine.

**Windows draws most of the icons on Windows.** `SHGetStockIconInfo`
hands back the shell's own picture for some eighty kinds - a folder, a
document, a drive, the recycle bin, a printer, the shield, the warning
triangle - and an application's toolbar is full of the same artwork. So
an icon is drawn, compared against those, and named when it is clearly
one of them. That is the same technique :mod:`dialog_kind` already uses
to tell a warning box from a question, measured on this machine: the
right stock icon differs by about 0.1 per channel where the nearest
wrong one differs by 4.7.

**And it says nothing rather than guessing.** An icon that is somebody's
own artwork - a dog sitting outside - lands near nothing here and is
handed on to the tier that can actually describe it. Naming it "folder"
because folder was nearest would be worse than saying "picture".

The comparison, the drawing and the threshold all live in
:mod:`dialog_kind`, because there is no reason for two of them.
"""

import threading

from . import i18n

_ = i18n.install(globals())

_LOCK = threading.RLock()

#: The shell's own icons worth naming, as `SIID` numbers. Every one of
#: these is a picture somebody meets on a real machine, and every one has
#: a word a person would actually use for it.
#:
#: Deliberately not all eighty: the ones left out are either duplicates
#: of these at another size, or so specific ("the icon for a DVD-RAM
#: disc") that naming them would be worse than saying "picture".
STOCK = (
    (0, 'document'),           # SIID_DOCNOASSOC
    (1, 'document'),           # SIID_DOCASSOC
    (2, 'application'),        # SIID_APPLICATION
    (3, 'folder'),             # SIID_FOLDER
    (4, 'open folder'),        # SIID_FOLDEROPEN
    (5, 'drive'),              # SIID_DRIVE525
    (6, 'drive'),              # SIID_DRIVE35
    (7, 'removable drive'),    # SIID_DRIVEREMOVE
    (8, 'drive'),              # SIID_DRIVEFIXED
    (9, 'network drive'),      # SIID_DRIVENET
    (10, 'network drive'),     # SIID_DRIVENETDISABLED
    (11, 'disc drive'),        # SIID_DRIVECD
    (12, 'drive'),             # SIID_DRIVERAM
    (13, 'network'),           # SIID_WORLD
    (15, 'server'),            # SIID_SERVER
    (16, 'printer'),           # SIID_PRINTER
    (17, 'network'),           # SIID_MYNETWORK
    (22, 'find'),              # SIID_FIND
    (23, 'help'),              # SIID_HELP
    (28, 'network'),           # SIID_SHARE
    (29, 'shortcut'),          # SIID_LINK
    (30, 'blocked'),           # SIID_SLOWFILE
    (31, 'recycle bin'),       # SIID_RECYCLER
    (32, 'full recycle bin'),  # SIID_RECYCLERFULL
    (40, 'disc'),              # SIID_MEDIACDAUDIO
    (47, 'lock'),              # SIID_LOCK
    (49, 'computer'),          # SIID_AUTOLIST
    (50, 'printer'),           # SIID_PRINTERNET
    (51, 'folder'),            # SIID_SERVERSHARE
    (52, 'fax'),               # SIID_PRINTERFAX
    (54, 'printer'),           # SIID_PRINTERFILE
    (55, 'folder'),            # SIID_STACK
    (56, 'disc'),              # SIID_MEDIASVCD
    (57, 'folder'),            # SIID_STUFFEDFOLDER
    (58, 'drive'),             # SIID_DRIVEUNKNOWN
    (59, 'disc'),              # SIID_DRIVEDVD
    (60, 'disc'),              # SIID_MEDIADVD
    (69, 'disc'),              # SIID_MEDIACDR
    (70, 'disc'),              # SIID_MEDIACDRW
    (71, 'disc'),              # SIID_MEDIACDROM
    (72, 'music'),             # SIID_MEDIAAUDIODVD
    (73, 'video'),             # SIID_MEDIAMOVIEDVD
    (77, 'delete'),            # SIID_DELETE
    (78, 'warning'),           # SIID_WARNING
    (79, 'information'),       # SIID_INFO
    (80, 'error'),             # SIID_ERROR
    (81, 'key'),               # SIID_KEY
    (82, 'software'),          # SIID_SOFTWARE
    (83, 'rename'),            # SIID_RENAME
    (84, 'delete'),            # SIID_DELETE
    (85, 'music'),             # SIID_MEDIAAUDIOCD
    (88, 'computer'),          # SIID_DESKTOPPC
    (89, 'computer'),          # SIID_MOBILEPC
    (90, 'settings'),          # SIID_USERS
    (93, 'disc'),              # SIID_MEDIABLURAY
    (99, 'computer'),          # SIID_CLUSTEREDDRIVE
    (65, 'shield'),            # SIID_SHIELD
)

#: **"Strzalka" and "klepsydra" are CURSORS, not icons**, and they come
#: from a different call: `LoadCursorW(NULL, IDC_*)` rather than
#: `SHGetStockIconInfo`. They are here because the user named them in one
#: breath with the icons - and rightly, since from the outside they are
#: the same thing: a small system picture with a meaning everybody knows.
#:
#: The two busy ones are compared by HANDLE in :mod:`states`, which is
#: exact and cheaper; this is the whole set, said in words.
CURSORS = (
    (32512, 'arrow'),          # OCR_NORMAL
    (32513, 'text cursor'),    # OCR_IBEAM
    (32514, 'hourglass'),      # OCR_WAIT
    (32515, 'crosshair'),      # OCR_CROSS
    (32516, 'text cursor'),    # OCR_UP
    (32642, 'resize'),         # OCR_SIZENWSE
    (32643, 'resize'),         # OCR_SIZENESW
    (32644, 'resize'),         # OCR_SIZEWE
    (32645, 'resize'),         # OCR_SIZENS
    (32646, 'move'),           # OCR_SIZEALL
    (32648, 'not allowed'),    # OCR_NO
    (32649, 'hand'),           # OCR_HAND
    (32650, 'busy'),           # OCR_APPSTARTING
    (32651, 'help'),           # OCR_HELP
)

_references = []
_counted = {'asked': 0, 'named': 0, 'unknown': 0, 'dropped': 0}


def report():
    with _LOCK:
        found = dict(_counted)
    found['references'] = len(_references)
    return found


def forget():
    with _LOCK:
        del _references[:]
        for key in _counted:
            _counted[key] = 0


def word(kind):
    """The name for a kind, in the user's own language."""
    return {
        # Translators: what an icon shows.
        'document': _('document'), 'application': _('application'),
        'folder': _('folder'), 'drive': _('drive'),
        'network drive': _('network drive'), 'network': _('network'),
        'computer': _('computer'), 'printer': _('printer'),
        'question': _('question'), 'lock': _('lock'),
        'recycle bin': _('recycle bin'), 'find': _('find'),
        'shield': _('shield'), 'delete': _('delete'),
        'warning': _('warning'), 'information': _('information'),
        'error': _('error'), 'key': _('key'), 'software': _('software'),
        'rename': _('rename'),
        'open folder': _('open folder'),
        'removable drive': _('removable drive'),
        'disc drive': _('disc drive'), 'server': _('server'),
        'help': _('help'), 'shortcut': _('shortcut'),
        'blocked': _('blocked'), 'full recycle bin': _('full recycle bin'),
        'disc': _('disc'), 'fax': _('fax'), 'video': _('video'),
        'music': _('music'), 'settings': _('settings'),
        # The cursors.
        'arrow': _('arrow'), 'text cursor': _('text cursor'),
        'hourglass': _('hourglass'), 'crosshair': _('crosshair'),
        'resize': _('resize'), 'move': _('move'),
        'not allowed': _('not allowed'), 'hand': _('hand'),
        'busy': _('busy'),
    }.get(str(kind or ''), '')


#: Where one word is the other in every sense a reader cares about. An
#: open folder is a folder; a removable drive is a drive. Written down
#: because Windows 11 hands back the SAME ARTWORK for both of each pair,
#: and two words on one picture is a picture that can only ever be
#: refused - measured here: `folder` and `open folder` differ by 0.000,
#: and so do `drive` and `removable drive`.
SAME_THING = {
    'open folder': 'folder',
    'removable drive': 'drive',
}


def _general(word):
    return SAME_THING.get(word, word)


def _collapse(made):
    """One word per picture, or no picture at all.

    **Two words on one picture is worse than no picture.** `_closest`
    refuses anything whose nearest rival is close, which is right and is
    why those pictures answered nothing - but the reason they are close
    is that they are IDENTICAL, and a rule about near misses cannot help
    with that. So they are dealt with here, where the references are
    built, and there are exactly two cases:

    * the words mean the same thing (:data:`SAME_THING`), and the general
      one is the answer - which is what a listener wanted anyway;
    * they do not, and the picture is DROPPED. Measured on Windows 11,
      `disc` and `shield` are one picture and so are `music` and
      `computer` - generic artwork for icons Windows no longer draws
      differently - so naming either would be inventing a fact about
      the user's screen. Dropping it also saves comparing against it.
    """
    words = {}
    pictures = {}
    order = []
    for kind, picture in made:
        key = bytes(bytearray(picture))
        if key not in words:
            words[key] = []
            pictures[key] = picture
            order.append(key)
        words[key].append(kind)
    kept = []
    dropped = 0
    for key in order:
        general = {_general(word) for word in words[key]}
        if len(general) != 1:
            dropped += 1
            continue
        kept.append((general.pop(), pictures[key]))
    with _LOCK:
        _counted['dropped'] = dropped
    return kept


def _known():
    """The reference pictures, drawn once.

    Once, because they do not change for the life of the session and this
    is asked on the focus path - twenty icon renderings per control would
    be a reader that had stopped.
    """
    with _LOCK:
        if _references:
            return list(_references)
    from . import dialog_kind
    made = []
    for siid, kind in STOCK:
        handle = dialog_kind.stock_icon(siid)
        if not handle:
            continue
        picture = dialog_kind._drawn(handle)
        if picture:
            made.append((kind, picture))
    made = _collapse(made)
    with _LOCK:
        del _references[:]
        _references.extend(made)
    return list(made)


def cursor_now():
    """What the mouse pointer is showing, in a word. ``''`` for unknown.

    By HANDLE, not by comparing pictures: Windows' own cursors are
    shared, so `LoadCursorW(NULL, IDC_*)` hands back the very handle the
    pointer is using. That is a comparison of two numbers - exact, and
    about as cheap as anything can be.
    """
    try:
        import ctypes

        class _INFO(ctypes.Structure):
            _fields_ = [('cbSize', ctypes.c_uint),
                        ('flags', ctypes.c_uint),
                        ('hCursor', ctypes.c_void_p),
                        ('x', ctypes.c_long), ('y', ctypes.c_long)]
        user32 = ctypes.windll.user32
        info = _INFO()
        info.cbSize = ctypes.sizeof(_INFO)
        if not user32.GetCursorInfo(ctypes.byref(info)):
            return ''
        now = int(info.hCursor or 0)
        if not now:
            return ''
        user32.LoadCursorW.restype = ctypes.c_void_p
        for number, kind in CURSORS:
            handle = int(user32.LoadCursorW(None,
                                            ctypes.c_void_p(number)) or 0)
            if handle and handle == now:
                return kind
    except Exception:                                # noqa: BLE001
        return ''
    return ''


def of_handle(hicon):
    """What that icon shows, or ``''``. ``hicon`` is a Windows icon."""
    if not hicon:
        return ''
    from . import dialog_kind
    with _LOCK:
        _counted['asked'] += 1
    picture = dialog_kind._drawn(int(hicon))
    if not picture:
        return ''
    kind = dialog_kind._closest(picture, _known())
    with _LOCK:
        if kind:
            _counted['named'] += 1
        else:
            _counted['unknown'] += 1
    return kind


def of_window(hwnd):
    """What the icon of that WINDOW shows, or ``''``.

    A window's own icon is what the taskbar shows for it, and for a
    dialog it is very often one of the shell's - which is exactly what
    somebody arriving in it wants said.
    """
    from . import dialog_kind
    handle = dialog_kind.window_icon(hwnd)
    return of_handle(handle) if handle else ''


def describe(obj):
    """What this control's picture shows, in a word. ``(ok, said)``.

    ``(False, '')`` means "not one of the ones that can be named", which
    is a real answer and the one that hands the question to the tier that
    can describe anything.
    """
    if obj is None:
        return False, ''
    try:
        hwnd = int(getattr(obj, 'windowHandle', 0) or 0)
    except (TypeError, ValueError):
        return False, ''
    kind = of_window(hwnd) if hwnd else ''
    if not kind:
        return False, ''
    said = word(kind)
    return (True, said) if said else (False, '')
