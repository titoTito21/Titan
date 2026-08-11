# -*- coding: utf-8 -*-
"""
Reading the Windows notification area, on the Windows the user actually has.

For twenty years the notification area was one `ToolbarWindow32` inside
`Shell_TrayWnd/TrayNotifyWnd/SysPager`, and every accessibility tool read it
by sending that toolbar `TB_*` messages.  On Windows 11 that toolbar does not
exist any more - the taskbar is XAML, and `TrayNotifyWnd` has no children at
all - so the old code found nothing and Titan showed an empty tray.  This
module reads it the way it can be read today:

* **UI Automation** over `Shell_TrayWnd`, where every icon is a real button
  (`SystemTray.NormalButton`, `.AccentButton`, `.OmniButton`,
  `.ShowDesktopButton`), each one named with the same text the hover tip
  shows - the app icons, the input indicator, the network, the volume, the
  battery, the clock, "Show hidden icons" and "Show desktop".  This is what
  Windows 11 answers to, and Windows 10 answers to it too.
* **The legacy toolbar**, kept for Windows 10 and earlier, but fixed: reading
  a button's text or rectangle means passing a *pointer* to a toolbar that
  lives in Explorer's process, so the buffer has to be allocated in Explorer
  (`VirtualAllocEx`) and read back (`ReadProcessMemory`).  Passing our own
  address - which is what this code used to do - can only ever fail, which is
  why every icon came back called "System Icon 1", "System Icon 2"...  It
  also means each icon knows its own rectangle, so clicking the third icon no
  longer clicks the first.

Pressing an icon goes through UI Automation's Invoke where there is one,
because Titan's shell puts Explorer's taskbar into auto-hide - the icons are
then off the screen, and a synthesised click at their coordinates would land
on whatever is underneath.  A real click is the last resort, not the first.
"""

import ctypes
import re
import time

from ctypes import wintypes

from src.platform_utils import IS_WINDOWS
from src.titan_core.translation import _

if IS_WINDOWS:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    # ctypes returns a C int by default, which truncates a 64-bit handle or
    # address into something that cannot be freed or read from.
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.VirtualAllocEx.restype = ctypes.c_void_p
    user32.SendMessageW.restype = ctypes.c_ssize_t
else:  # pragma: no cover - the notification area is a Windows thing
    user32 = kernel32 = None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WM_USER = 0x0400
TB_BUTTONCOUNT = WM_USER + 24
TB_GETBUTTON = WM_USER + 23
TB_GETBUTTONTEXTW = WM_USER + 75
TB_GETITEMRECT = WM_USER + 29

TBSTATE_HIDDEN = 0x08

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B

PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400

MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010

VK_APPS = 0x5D
KEYEVENTF_KEYUP = 0x0002

# UI Automation property ids we ask for by number, so no type library beyond
# UIAutomationCore is needed.
UIA_IsInvokePatternAvailablePropertyId = 30031
UIA_IsLegacyIAccessiblePatternAvailablePropertyId = 30090
UIA_InvokePatternId = 10000
UIA_LegacyIAccessiblePatternId = 10018

# The classes Windows 11 gives the notification area's buttons.  Matching on
# the prefix rather than the whole name is deliberate: Microsoft has already
# added and renamed these (Omni, Accent, Chevron...) between builds, and a new
# one should appear in Titan rather than silently vanish.
TRAY_CLASS_PREFIX = 'SystemTray.'

# Automation ids that tell an application's own icon from one of Windows'.
APP_ICON_AUTOMATION_ID = 'NotifyItemIcon'

# The flyout that holds the hidden icons on Windows 11.
OVERFLOW_CLASSES = ('TopLevelWindowForOverflowXamlIsland',
                    'NotifyIconOverflowWindow')


def _clean(text):
    """One line out of a tray tooltip, which is often three.

    Windows puts the whole state of a thing in the name - "Network ...\\n
    Internet access\\n\\nOpenVPN\\nConnected" - and all of it is worth
    hearing; it just must not arrive with the line breaks still in it.
    """
    if not text:
        return ''
    text = re.sub(r'[‎‏‪-‮]', '', str(text))
    parts = [part.strip() for part in re.split(r'[\r\n]+', text)]
    return ' - '.join(part for part in parts if part).strip()


class SystemTrayIcon:
    """One notification-area icon, however it was found.

    The interface is the one the rest of Titan already used - `text`,
    `tooltip`, `left_click()`, `right_click()` - so the tray list dialog and
    the shell's own notification area did not have to change with it.
    """

    def __init__(self, text='', tooltip='', hwnd=0, button_id=-1,
                 element=None, rect=None, hidden=False, system=False,
                 index=-1, automation_id='', class_name='', chevron=False,
                 runtime_id=()):
        self.text = _clean(text) or _("Notification icon")
        self.tooltip = _clean(tooltip) or self.text
        self.hwnd = hwnd
        self.button_id = button_id
        self.index = index
        self.element = element        # a UIA element, when UIA found it
        self.rect = rect              # screen pixels: (left, top, right, bottom)
        self.hidden = bool(hidden)
        self.system = bool(system)
        self.automation_id = automation_id
        self.class_name = class_name
        # "Show hidden icons".  Windows gives it no property of its own that
        # tells it apart, so it is recognised where the whole tray is in
        # front of us - see `_mark_chevron`.
        self.chevron = bool(chevron)
        self._revived = False
        # UI Automation's own identity for the element, which survives the
        # icon being renamed - and a tray icon is renamed constantly, since
        # its name carries the battery percentage or the volume.
        self.runtime_id = tuple(runtime_id or ())

    # -- what it looks like ----------------------------------------------
    def icon_handle(self):
        """The icon's own HICON, where this Windows will part with one.

        There is no general way to ask for the picture: a notification icon
        is registered by its owner with `Shell_NotifyIcon` and the bitmap
        stays in that process, and on Windows 11 the tray is XAML, so the
        button carries an `Image` element with no readable source.  What can
        be had is the icon of the *window* that registered it, which for an
        application is the same picture - so that is what is asked for, and
        anything that answers nothing gets no picture rather than a letter
        drawn in its place.
        """
        hwnd = self.hwnd
        if not hwnd and self.element is not None:
            try:
                hwnd = int(self.element.CurrentNativeWindowHandle or 0)
            except Exception:
                hwnd = 0
        if not hwnd or not user32:
            return 0

        WM_GETICON = 0x007F
        ICON_SMALL, ICON_BIG, ICON_SMALL2 = 0, 1, 2
        GCLP_HICONSM, GCLP_HICON = -34, -14
        for which in (ICON_SMALL2, ICON_SMALL, ICON_BIG):
            try:
                handle = user32.SendMessageW(hwnd, WM_GETICON, which, 0)
            except Exception:
                handle = 0
            if handle:
                return int(handle)
        getter = getattr(user32, 'GetClassLongPtrW', None) or             getattr(user32, 'GetClassLongW', None)
        if getter is None:
            return 0
        for index in (GCLP_HICONSM, GCLP_HICON):
            try:
                handle = getter(hwnd, index)
            except Exception:
                handle = 0
            if handle:
                return int(handle)
        return 0

    # -- what it is ------------------------------------------------------
    @property
    def key(self):
        """What makes this the same icon as one read a moment ago."""
        if self.runtime_id:
            return self.runtime_id
        if self.hwnd and self.button_id >= 0:
            return (self.hwnd, self.button_id)
        return (self.text,)

    @property
    def short_text(self):
        return self.text.split(' - ')[0] if self.text else ''

    def centre(self):
        if not self.rect:
            return None
        left, top, right, bottom = self.rect
        if right <= left or bottom <= top:
            return None
        return ((left + right) // 2, (top + bottom) // 2)

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<SystemTrayIcon {self.text!r}{' hidden' if self.hidden else ''}>"

    # -- pressing it -----------------------------------------------------
    def _revive(self):
        """Get a hidden icon's element back after its flyout closed.

        A hidden icon only exists while the overflow flyout is open, so an
        element read from it dies with the flyout - and a stale rectangle
        would send a click at whatever is on that spot now.  Opening the
        flyout again and matching by name is what makes a hidden icon
        pressable minutes after it was listed.
        """
        if not self.hidden or self._revived:
            return False
        self._revived = True
        for icon in expand_hidden_icons():
            if icon.text == self.text:
                self.element = icon.element
                self.rect = icon.rect
                return True
        return False

    def left_click(self):
        """Do what clicking the icon does."""
        if self.element is not None:
            if _uia_invoke(self.element):
                return True
        if self._revive() and _uia_invoke(self.element):
            return True
        if self.hwnd and self.index >= 0:
            if _legacy_click(self.hwnd, self.index, right=False):
                return True
        return _real_click(self.centre(), right=False)

    def right_click(self):
        """Open the icon's own menu.

        There is no UI Automation pattern for a context menu, so the element
        is focused and asked for one with the Applications key; a real right
        click is the fallback, and the only route the legacy toolbar has.
        """
        if self.element is not None:
            if _uia_context_menu(self.element):
                return True
        if self._revive() and _uia_context_menu(self.element):
            return True
        if self.hwnd and self.index >= 0:
            if _legacy_click(self.hwnd, self.index, right=True):
                return True
        return _real_click(self.centre(), right=True)


# ---------------------------------------------------------------------------
# UI Automation - Windows 11 and 10
# ---------------------------------------------------------------------------

_uia = None
_uia_failed = False


def _automation():
    """The one UI Automation object this module uses.

    Created on whatever thread asks first, which in Titan is the GUI thread -
    the same thread every caller here runs on, so no element ever crosses an
    apartment boundary.
    """
    global _uia, _uia_failed
    if _uia is not None or _uia_failed:
        return _uia
    try:
        import comtypes
        import comtypes.client
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
        except Exception:
            # Already initialised on this thread, which is the normal case
            # inside wx; the mode it was initialised with is the one we use.
            pass
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen.UIAutomationClient import CUIAutomation, IUIAutomation
        _uia = comtypes.client.CreateObject(CUIAutomation,
                                            interface=IUIAutomation)
    except Exception as error:
        _uia_failed = True
        print(f"[Tray] UI Automation is unavailable: {error}")
    return _uia


def _element_from_class(class_name):
    automation = _automation()
    if automation is None or not user32:
        return None
    try:
        hwnd = user32.FindWindowW(class_name, None)
        if not hwnd:
            return None
        return automation.ElementFromHandle(ctypes.c_void_p(hwnd))
    except Exception:
        return None


def _child_windows(parent):
    """The direct children of a window, in z-order."""
    if not user32 or not parent:
        return []
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd, _lparam):
        found.append(hwnd)
        return True

    try:
        user32.EnumChildWindows(parent, collect, 0)
    except Exception:
        return []
    return [hwnd for hwnd in found if user32.GetParent(hwnd) == parent]


def _window_class(hwnd):
    if not user32 or not hwnd:
        return ''
    buffer = ctypes.create_unicode_buffer(256)
    try:
        user32.GetClassNameW(hwnd, buffer, 256)
    except Exception:
        return ''
    return buffer.value or ''


def _tray_roots():
    """The elements the notification area's buttons live under.

    On Windows 11 the taskbar's contents are a XAML island hosted in a
    `Windows.UI.Composition.DesktopWindowContentBridge` child window, and
    that island has a UI Automation tree **of its own**: walking down from
    `Shell_TrayWnd` reaches `TrayNotifyWnd` and `MSTaskSwWClass` and stops,
    which is exactly the empty tray this module was written to fix - the
    fix was right about UI Automation and wrong about where to start.  So
    the island's own window is asked first, and `Shell_TrayWnd` itself
    second, which is what the builds before it answer to.
    """
    automation = _automation()
    if automation is None or not user32:
        return []
    try:
        tray = user32.FindWindowW('Shell_TrayWnd', None)
    except Exception:
        tray = 0
    if not tray:
        return []
    roots = []
    for hwnd in _child_windows(tray):
        if not _window_class(hwnd).startswith('Windows.UI.'):
            continue
        try:
            roots.append(automation.ElementFromHandle(ctypes.c_void_p(hwnd)))
        except Exception:
            pass
    try:
        roots.append(automation.ElementFromHandle(ctypes.c_void_p(tray)))
    except Exception:
        pass
    return roots


def _walk_tray_buttons(root, out, depth=0, budget=None):
    """Collect every `SystemTray.*` button under `root`.

    The tray sits a few levels down inside a XAML island whose shape has
    already changed between Windows 11 builds, so this looks for the buttons
    by what they are rather than by where they were last time.
    """
    automation = _automation()
    if automation is None or root is None or depth > 8:
        return
    if budget is not None and time.monotonic() > budget:
        return
    try:
        walker = automation.ControlViewWalker
        child = walker.GetFirstChildElement(root)
    except Exception:
        return
    while child:
        try:
            class_name = child.CurrentClassName or ''
        except Exception:
            class_name = ''
        try:
            if class_name.startswith(TRAY_CLASS_PREFIX):
                out.append(child)
            else:
                _walk_tray_buttons(child, out, depth + 1, budget)
        except Exception:
            pass
        try:
            child = walker.GetNextSiblingElement(child)
        except Exception:
            break


def _icon_from_element(element, hidden=False):
    try:
        name = element.CurrentName or ''
    except Exception:
        name = ''
    try:
        automation_id = element.CurrentAutomationId or ''
    except Exception:
        automation_id = ''
    rect = None
    try:
        bounds = element.CurrentBoundingRectangle
        rect = (int(bounds.left), int(bounds.top), int(bounds.right),
                int(bounds.bottom))
    except Exception:
        pass
    if not _clean(name):
        return None
    try:
        class_name = element.CurrentClassName or ''
    except Exception:
        class_name = ''
    try:
        runtime_id = tuple(element.GetRuntimeId())
    except Exception:
        runtime_id = ()
    return SystemTrayIcon(text=name, tooltip=name, element=element, rect=rect,
                          hidden=hidden, automation_id=automation_id,
                          class_name=class_name, runtime_id=runtime_id,
                          system=(automation_id != APP_ICON_AUTOMATION_ID))


def _uia_icons():
    """Every notification-area icon Windows 11 will admit to."""
    elements = []
    budget = time.monotonic() + 3.0
    for root in _tray_roots():
        _walk_tray_buttons(root, elements, budget=budget)
        if elements:
            # The first root that answers is the one this Windows keeps the
            # tray in; asking the next would read the same icons twice.
            break
    icons = []
    seen = set()
    for element in elements:
        icon = _icon_from_element(element)
        if icon is None or icon.key in seen:
            continue
        seen.add(icon.key)
        icons.append(icon)
    _mark_chevron(icons)
    return icons


def _mark_chevron(icons):
    """Find "Show hidden icons" by where it is, because nothing else says.

    Every button in the Windows 11 tray answers with the same class family,
    the same automation id and the same "button" role, and the chevron's name
    is whatever the user's language calls it - so it cannot be matched on a
    word without breaking on every other Windows.  What is fixed is the
    layout: the chevron is the first thing in the notification area, before
    the applications' own icons.
    """
    if not icons:
        return
    first = icons[0]
    if first.automation_id == APP_ICON_AUTOMATION_ID:
        return
    if not first.class_name.endswith(('NormalButton', 'ChevronButton')):
        return
    first.chevron = True


def _overflow_icons():
    """The hidden icons - only the ones the flyout is already showing.

    Opening the flyout to read it would make a periodic refresh flash the
    screen, so this reads it when it is open and `expand_hidden_icons()` is
    what opens it, exactly as pressing the chevron does for anybody else.
    """
    icons = []
    for class_name in OVERFLOW_CLASSES:
        root = _element_from_class(class_name)
        if root is None:
            continue
        elements = []
        _walk_tray_buttons(root, elements, budget=time.monotonic() + 2.0)
        for element in elements:
            icon = _icon_from_element(element, hidden=True)
            if icon is not None:
                icons.append(icon)
    return icons


def is_chevron(icon):
    """True for the "Show hidden icons" button."""
    return bool(getattr(icon, 'chevron', False))


def is_show_desktop(icon):
    """True for Windows' own "Show desktop" button at the end of the tray.

    Windows gives this one a class of its own, which is the one thing in the
    notification area that can be recognised without reading a word of the
    user's language.
    """
    return str(getattr(icon, 'class_name', '')).endswith('ShowDesktopButton')


_TIME_PATTERN = re.compile(r'\d{1,2}[:.]\d{2}')


def is_clock(icon):
    """True for Windows' own clock.

    There is no property that says so, and its name is whatever the user's
    language and time format make of it - but every one of them contains a
    time, and only the clock's does.  Matched together with the class
    Windows 11 gives it, so a button that merely mentions a time (a reminder,
    a media player) is not mistaken for the clock.
    """
    class_name = str(getattr(icon, 'class_name', ''))
    if not class_name.endswith('OmniButton'):
        return False
    return bool(_TIME_PATTERN.search(getattr(icon, 'text', '') or ''))


def expand_hidden_icons():
    """Open the hidden-icons flyout and return what is in it."""
    chevron = None
    for icon in _uia_icons():
        if is_chevron(icon):
            chevron = icon
            break
    if chevron is None:
        return []
    chevron.left_click()
    # The flyout is a XAML popup; it is built when it is shown, so there is
    # nothing to read until it is.
    for _attempt in range(20):
        time.sleep(0.05)
        icons = _overflow_icons()
        if icons:
            return icons
    return []


def _uia_invoke(element):
    automation = _automation()
    if automation is None or element is None:
        return False
    try:
        if element.GetCurrentPropertyValue(
                UIA_IsInvokePatternAvailablePropertyId):
            pattern = element.GetCurrentPattern(UIA_InvokePatternId)
            if pattern:
                from comtypes.gen.UIAutomationClient import IUIAutomationInvokePattern
                pattern.QueryInterface(IUIAutomationInvokePattern).Invoke()
                return True
    except Exception as error:
        print(f"[Tray] invoke failed: {error}")
    try:
        if element.GetCurrentPropertyValue(
                UIA_IsLegacyIAccessiblePatternAvailablePropertyId):
            from comtypes.gen.UIAutomationClient import \
                IUIAutomationLegacyIAccessiblePattern
            pattern = element.GetCurrentPattern(UIA_LegacyIAccessiblePatternId)
            if pattern:
                pattern.QueryInterface(
                    IUIAutomationLegacyIAccessiblePattern).DoDefaultAction()
                return True
    except Exception as error:
        print(f"[Tray] default action failed: {error}")
    return False


def _uia_context_menu(element):
    if element is None or not user32:
        return False
    try:
        element.SetFocus()
    except Exception:
        return False
    try:
        user32.keybd_event(VK_APPS, 0, 0, 0)
        user32.keybd_event(VK_APPS, 0, KEYEVENTF_KEYUP, 0)
        return True
    except Exception as error:
        print(f"[Tray] context menu failed: {error}")
        return False


# ---------------------------------------------------------------------------
# The legacy toolbar - Windows 10 and earlier
# ---------------------------------------------------------------------------


class TBBUTTON(ctypes.Structure):
    _fields_ = [
        ('iBitmap', ctypes.c_int),
        ('idCommand', ctypes.c_int),
        ('fsState', ctypes.c_byte),
        ('fsStyle', ctypes.c_byte),
        ('bReserved', ctypes.c_byte * 6),
        ('dwData', ctypes.c_size_t),
        ('iString', ctypes.c_ssize_t),
    ]


class _RemoteBuffer:
    """A block of memory inside the process that owns a window.

    Sending a toolbar `TB_GETBUTTONTEXTW` means handing it somewhere to write
    the answer, and the toolbar writes it in *its* address space.  Without
    this the message can only fail - which is exactly what the tray reader
    used to do on every Windows.
    """

    def __init__(self, hwnd, size=1024):
        self.process = None
        self.address = None
        self.size = size
        if not IS_WINDOWS or not hwnd:
            return
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return
        access = (PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE
                  | PROCESS_QUERY_INFORMATION)
        handle = kernel32.OpenProcess(access, False, pid.value)
        if not handle:
            return
        self.process = handle
        self.address = kernel32.VirtualAllocEx(
            ctypes.c_void_p(handle), None, ctypes.c_size_t(size),
            MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)

    def ok(self):
        return bool(self.process and self.address)

    def read(self, into):
        if not self.ok():
            return False
        read = ctypes.c_size_t(0)
        return bool(kernel32.ReadProcessMemory(
            ctypes.c_void_p(self.process), ctypes.c_void_p(self.address),
            ctypes.byref(into), ctypes.sizeof(into), ctypes.byref(read)))

    def read_at(self, address, into):
        if not self.process or not address:
            return False
        read = ctypes.c_size_t(0)
        return bool(kernel32.ReadProcessMemory(
            ctypes.c_void_p(self.process), ctypes.c_void_p(address),
            ctypes.byref(into), ctypes.sizeof(into), ctypes.byref(read)))

    def close(self):
        try:
            if self.process and self.address:
                kernel32.VirtualFreeEx(ctypes.c_void_p(self.process),
                                       ctypes.c_void_p(self.address), 0,
                                       MEM_RELEASE)
            if self.process:
                kernel32.CloseHandle(ctypes.c_void_p(self.process))
        except Exception:
            pass
        self.process = self.address = None

    def __enter__(self):
        return self

    def __exit__(self, *_exception):
        self.close()


def _find_legacy_toolbar():
    """`Shell_TrayWnd/TrayNotifyWnd/[SysPager/]ToolbarWindow32`, if it exists."""
    if not IS_WINDOWS:
        return None
    tray = user32.FindWindowW('Shell_TrayWnd', None)
    if not tray:
        return None
    notify = user32.FindWindowExW(tray, 0, 'TrayNotifyWnd', None)
    if not notify:
        return None
    pager = user32.FindWindowExW(notify, 0, 'SysPager', None)
    parent = pager or notify
    return user32.FindWindowExW(parent, 0, 'ToolbarWindow32', None) or None


def _find_legacy_overflow_toolbar():
    if not IS_WINDOWS:
        return None
    overflow = user32.FindWindowW('NotifyIconOverflowWindow', None)
    if not overflow:
        return None
    return user32.FindWindowExW(overflow, 0, 'ToolbarWindow32', None) or None


def _legacy_toolbar_icons(toolbar, hidden=False):
    if not toolbar:
        return []
    icons = []
    count = user32.SendMessageW(toolbar, TB_BUTTONCOUNT, 0, 0)
    if count <= 0:
        return []
    with _RemoteBuffer(toolbar) as remote:
        if not remote.ok():
            return []
        for index in range(count):
            try:
                button = TBBUTTON()
                user32.SendMessageW(toolbar, TB_GETBUTTON, index,
                                    ctypes.c_void_p(remote.address))
                remote.read(button)

                text = ctypes.create_unicode_buffer(256)
                length = user32.SendMessageW(toolbar, TB_GETBUTTONTEXTW,
                                             button.idCommand,
                                             ctypes.c_void_p(remote.address))
                if length > 0:
                    remote.read(text)

                rect = wintypes.RECT()
                user32.SendMessageW(toolbar, TB_GETITEMRECT, index,
                                    ctypes.c_void_p(remote.address))
                remote.read(rect)
                point = wintypes.POINT((rect.left + rect.right) // 2,
                                       (rect.top + rect.bottom) // 2)
                user32.ClientToScreen(toolbar, ctypes.byref(point))

                name = text.value or _("Notification icon")
                icons.append(SystemTrayIcon(
                    text=name, tooltip=name, hwnd=toolbar,
                    button_id=button.idCommand, index=index,
                    rect=(point.x - 8, point.y - 8, point.x + 8, point.y + 8),
                    hidden=hidden or bool(button.fsState & TBSTATE_HIDDEN)))
            except Exception as error:
                print(f"[Tray] could not read icon {index}: {error}")
    return icons


def _legacy_icons():
    icons = _legacy_toolbar_icons(_find_legacy_toolbar())
    icons.extend(_legacy_toolbar_icons(_find_legacy_overflow_toolbar(),
                                       hidden=True))
    return icons


def _legacy_click(toolbar, index, right=False):
    """Click a legacy toolbar icon where the icon really is."""
    if not IS_WINDOWS or not toolbar:
        return False
    try:
        with _RemoteBuffer(toolbar, size=64) as remote:
            if not remote.ok():
                return False
            rect = wintypes.RECT()
            user32.SendMessageW(toolbar, TB_GETITEMRECT, index,
                                ctypes.c_void_p(remote.address))
            if not remote.read(rect):
                return False
        x = (rect.left + rect.right) // 2
        y = (rect.top + rect.bottom) // 2
        lparam = (y << 16) | (x & 0xFFFF)
        user32.PostMessageW(toolbar, WM_MOUSEMOVE, 0, lparam)
        if right:
            user32.PostMessageW(toolbar, WM_RBUTTONDOWN, 0, lparam)
            user32.PostMessageW(toolbar, WM_RBUTTONUP, 0, lparam)
            user32.PostMessageW(toolbar, WM_CONTEXTMENU, toolbar, lparam)
        else:
            user32.PostMessageW(toolbar, WM_LBUTTONDOWN, 0, lparam)
            user32.PostMessageW(toolbar, WM_LBUTTONUP, 0, lparam)
        return True
    except Exception as error:
        print(f"[Tray] legacy click failed: {error}")
        return False


# ---------------------------------------------------------------------------
# A real click, when nothing else will do
# ---------------------------------------------------------------------------


def _real_click(point, right=False):
    """Move the pointer, click, and put the pointer back where it was."""
    if not IS_WINDOWS or not point:
        return False
    x, y = point
    try:
        original = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(original))
        user32.SetCursorPos(int(x), int(y))
        time.sleep(0.02)
        down = MOUSEEVENTF_RIGHTDOWN if right else MOUSEEVENTF_LEFTDOWN
        up = MOUSEEVENTF_RIGHTUP if right else MOUSEEVENTF_LEFTUP
        user32.mouse_event(down, 0, 0, 0, 0)
        user32.mouse_event(up, 0, 0, 0, 0)
        time.sleep(0.02)
        user32.SetCursorPos(original.x, original.y)
        return True
    except Exception as error:
        print(f"[Tray] click failed: {error}")
        return False


# ---------------------------------------------------------------------------
# What the rest of Titan calls
# ---------------------------------------------------------------------------


def get_tray_icons(include_hidden=True):
    """Every notification-area icon, newest Windows first.

    UI Automation is asked first because it is the only thing that answers on
    Windows 11; the legacy toolbar is tried when it finds nothing, which is
    the case on a Windows old enough to still have one and on a machine where
    UI Automation is unavailable.
    """
    if not IS_WINDOWS:
        return []
    icons = []
    try:
        icons = _uia_icons()
    except Exception as error:
        print(f"[Tray] the UI Automation reader failed: {error}")
    if not icons:
        try:
            icons = _legacy_icons()
        except Exception as error:
            print(f"[Tray] the legacy reader failed: {error}")
    if include_hidden:
        try:
            existing = {icon.text for icon in icons}
            for icon in _overflow_icons():
                if icon.text not in existing:
                    icons.append(icon)
        except Exception:
            pass
    return icons
