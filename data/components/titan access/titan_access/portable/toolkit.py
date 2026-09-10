# -*- coding: utf-8 -*-
"""What a window is WRITTEN IN, which is what decides how to read it.

A screen reader that knows a window is Qt knows why its list has no
columns; one that knows it is a Java AWT frame knows the accessibility
bridge has to be switched on before anything at all will be answered; one
that knows it is a Unity surface knows there is nothing to walk and the
picture is the only way in. Every app module ever written begins with
somebody working this out by hand.

It is worth having as a fact rather than a guess because it is ANSWERABLE.
Three kinds of evidence, and they are deliberately ordered by how hard
they are to be wrong about:

* **What the process has loaded.** `Qt6Core.dll` is Qt and nothing else,
  `jvm.dll` is a JVM, `libcef.dll` is Chromium embedded in something. A
  program cannot be running on a toolkit whose library it has not loaded,
  so this is the one piece of evidence that cannot be coincidence. It is
  also the one that can be refused: a process running as another user, or
  elevated, answers nothing, and that is reported rather than guessed
  around.
* **What UI Automation calls it.** `FrameworkId` is the toolkit's own
  answer - WPF, WinForm, XAML, Chrome, Gecko, Silverlight, Qt - and is
  free where UIA is answering at all.
* **The window class.** `WindowsForms10.Window.8.app...` is Windows
  Forms, `TfrmMain` is Delphi's VCL, `SunAwtFrame` is AWT. Weaker,
  because a program may name a class anything, but it is there when the
  other two are not.

**Nothing here is on the focus path.** Reading a process's module list is
tens of milliseconds and the answer does not change while the program
runs, so it is worked out once per process and kept.
"""

import ctypes
import threading

from . import i18n

_ = i18n.install(globals())

_LOCK = threading.RLock()

#: {pid: (framework, how, evidence)} - a process cannot change what it is
#: written in, so this is asked once and never again.
_known = {}

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
LIST_MODULES_ALL = 0x03

#: A loaded library that can only mean one thing, as ``(prefix, framework)``
#: matched against the START of the module's own file name.
#:
#: **Matched by prefix and never by substring.** The first version of this
#: asked whether the fragment appeared anywhere in the name, and `vcl`
#: appears in `srvcli.dll` - a Windows networking library that half the
#: programs on the machine have loaded - so a console, Explorer and 7-Zip
#: were all confidently reported as Delphi. A three-letter fragment
#: matched loosely is not evidence, it is a coincidence waiting to happen.
#:
#: The ORDER is the answer's precedence and it matters: an Electron
#: program has loaded Chromium too, and calling it Chromium would be true
#: and useless.
BY_LIBRARY = (
    ('electron.exe', 'electron'),
    ('libcef.', 'cef'),
    ('qt6core', 'qt'), ('qt5core', 'qt'), ('qtcore4', 'qt'),
    ('wxmsw', 'wx'), ('wxbase', 'wx'),
    ('javafx', 'javafx'),
    ('jvm.dll', 'java'), ('awt.dll', 'java'), ('java.dll', 'java'),
    ('libgtk-3', 'gtk'), ('libgtk-4', 'gtk'), ('gtk-3', 'gtk'),
    ('tk86', 'tk'), ('tk87', 'tk'), ('tcl86', 'tk'),
    ('presentationcore', 'wpf'), ('presentationframework', 'wpf'),
    ('system.windows.forms', 'winforms'),
    ('mfc140', 'mfc'), ('mfc120', 'mfc'), ('mfc110', 'mfc'), ('mfc42', 'mfc'),
    ('sdl2.dll', 'sdl'), ('sdl.dll', 'sdl'),
    ('unityplayer', 'unity'),
    ('sciter', 'sciter'),
    ('flutter_windows', 'flutter'),
    ('libglesv2.dll', 'chromium'), ('chrome_elf.dll', 'chromium'),
    ('xul.dll', 'gecko'),
    ('python3', 'python'),
)

#: Delphi and C++ Builder ship their runtime as PACKAGES - `vcl280.bpl`,
#: `rtl280.bpl` - so the extension is half the evidence and the prefix
#: alone is not enough. Kept apart from :data:`BY_LIBRARY` because the
#: rule really is different, rather than being a special case hidden in
#: a table that says it matches prefixes.
DELPHI_PACKAGES = ('vcl', 'rtl', 'vclx', 'dbrtl')

#: What UI Automation calls the toolkit, mapped onto ours.
BY_UIA = {
    'wpf': 'wpf', 'winform': 'winforms', 'win32': 'win32',
    'xaml': 'xaml', 'directui': 'directui', 'chrome': 'chromium',
    'gecko': 'gecko', 'silverlight': 'silverlight', 'qt': 'qt',
    'javafx': 'javafx', 'internetexplorer': 'mshtml',
}

#: The window class, where it is the toolkit's own. Matched by prefix.
BY_CLASS = (
    ('windowsforms', 'winforms'),
    ('hwndwrapper', 'wpf'),
    ('sunawtframe', 'java'), ('sunawtdialog', 'java'),
    ('qwidget', 'qt'), ('qt5', 'qt'), ('qt6', 'qt'),
    ('wxwindow', 'wx'), ('wxframe', 'wx'),
    ('gtkwindow', 'gtk'), ('gdkwindowtoplevel', 'gtk'),
    ('tktoplevel', 'tk'), ('tkchild', 'tk'),
    ('afx:', 'mfc'), ('afxwnd', 'mfc'),
    ('thunderrt', 'vb6'), ('thundermain', 'vb6'),
    ('chrome_widgetwin', 'chromium'),
    ('mozillawindowclass', 'gecko'),
    ('consolewindowclass', 'console'),
    ('cascadia_hosting_window_class', 'console'),
    ('unitywndclass', 'unity'),
    ('sdl_app', 'sdl'),
    ('godot_engine', 'godot'),
    ('#32770', 'win32'),
    ('electron', 'electron'),
    ('flutterview', 'flutter'),
)

#: What each is CALLED, for a person. A framework with no word here is
#: reported by its own name rather than not at all.
WORDS = {
    'winforms': 'Windows Forms', 'wpf': 'WPF', 'xaml': 'WinUI / XAML',
    'win32': 'Win32', 'mfc': 'MFC', 'vcl': 'Delphi / C++ Builder',
    'qt': 'Qt', 'wx': 'wxWidgets', 'gtk': 'GTK', 'tk': 'Tk',
    'java': 'Java (AWT/Swing)', 'javafx': 'JavaFX',
    'chromium': 'Chromium', 'cef': 'Chromium (embedded)',
    'electron': 'Electron', 'gecko': 'Gecko', 'mshtml': 'Internet Explorer',
    'silverlight': 'Silverlight', 'directui': 'DirectUI',
    'unity': 'Unity', 'godot': 'Godot', 'sdl': 'SDL',
    'console': 'a console', 'vb6': 'Visual Basic 6',
    'python': 'Python', 'sciter': 'Sciter', 'flutter': 'Flutter',
}

#: What a reader has to know about each, in one sentence. This is the part
#: that is worth having: it is the difference between naming a toolkit and
#: knowing what to do about it.
NOTES = {
    'java': 'Java Access Bridge has to be on, or nothing is answered at all.',
    'javafx': 'Java Access Bridge has to be on.',
    'qt': 'Qt answers UI Automation only when its accessibility plugin is '
          'loaded; a list often reports no columns.',
    'wx': 'wxWidgets controls are real Win32 controls, so MSAA answers even '
          'where UI Automation does not.',
    'gtk': 'GTK on Windows exposes little; the picture is often the only '
           'way in.',
    'tk': 'Tk draws its own widgets and names almost nothing.',
    'vcl': 'Delphi answers MSAA for the standard controls and nothing for '
           'its own.',
    'vb6': 'Windows proxies the standard controls, so MSAA answers even '
           'for a program from 1998.',
    'unity': 'A game that paints its own screen: there is nothing to walk.',
    'godot': 'Paints its own screen: there is nothing to walk.',
    'sdl': 'Paints its own screen: there is nothing to walk.',
    'console': 'A console: the text is the interface, and it is reviewed '
               'rather than walked.',
    'directui': 'DirectUI draws its own controls; UI Automation is the only '
                'way in and it is often thin.',
    'flutter': 'Flutter paints its own screen and answers a tree of its own '
               'only when semantics are switched on.',
}


def _text(value):
    return str(value or '').strip()


def word(framework):
    """What this framework is called, for a person."""
    name = _text(framework)
    return WORDS.get(name, name)


def note(framework):
    """What a reader has to know about it, or ''."""
    return NOTES.get(_text(framework), '')


# --------------------------------------------------------------------------- #
# The evidence
# --------------------------------------------------------------------------- #
def modules_of(pid):
    """Every library this process has loaded, lower-cased. ``[]`` when the
    process will not say - which is a refusal, not an absence."""
    if not pid:
        return []
    try:
        kernel32 = ctypes.windll.kernel32
        psapi = getattr(ctypes.windll, 'psapi', kernel32)
    except Exception:                                # noqa: BLE001
        return []
    handle = None
    for access in (PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ,
                   PROCESS_QUERY_INFORMATION | PROCESS_VM_READ,
                   PROCESS_QUERY_LIMITED_INFORMATION):
        try:
            handle = kernel32.OpenProcess(access, False, int(pid))
        except Exception:                            # noqa: BLE001
            handle = None
        if handle:
            break
    if not handle:
        return []
    found = []
    try:
        needed = ctypes.c_ulong(0)
        count = 2048
        array = (ctypes.c_void_p * count)()
        enum = getattr(psapi, 'EnumProcessModulesEx', None) \
            or getattr(kernel32, 'K32EnumProcessModulesEx', None)
        ok = False
        if enum is not None:
            ok = bool(enum(handle, ctypes.byref(array),
                           ctypes.sizeof(array), ctypes.byref(needed),
                           LIST_MODULES_ALL))
        if not ok:
            plain = getattr(psapi, 'EnumProcessModules', None) \
                or getattr(kernel32, 'K32EnumProcessModules', None)
            if plain is None:
                return []
            ok = bool(plain(handle, ctypes.byref(array),
                            ctypes.sizeof(array), ctypes.byref(needed)))
        if not ok:
            return []
        slot = ctypes.sizeof(ctypes.c_void_p)
        how_many = min(count, int(needed.value // slot))
        base = getattr(psapi, 'GetModuleBaseNameW', None) \
            or getattr(kernel32, 'K32GetModuleBaseNameW', None)
        if base is None:
            return []
        # **A module handle is a POINTER, and ctypes converts a bare Python
        # int to a C int.** Reading `array[index]` gives an int, and handing
        # that over truncated every handle above 2 GB to 32 bits - so
        # `GetModuleBaseNameW` was asked about an address that is not a
        # module and answered nothing for all but the two lowest. Measured:
        # 2 names out of 89 modules. It is the same trap the trackpad's
        # `hInstance` hit, one API along.
        base.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_wchar_p, ctypes.c_ulong]
        base.restype = ctypes.c_ulong
        name = ctypes.create_unicode_buffer(260)
        for index in range(how_many):
            module = array[index]
            if not module:
                continue
            try:
                if base(handle, ctypes.c_void_p(module), name, 260):
                    found.append(str(name.value or '').lower())
            except Exception:                        # noqa: BLE001
                continue
    finally:
        try:
            ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:                            # noqa: BLE001
            pass
    return found


def _by_library(loaded):
    """``(framework, evidence)`` its libraries PROVE, or ``('', '')``.

    A program cannot be running on a toolkit whose library it has not
    loaded, which is what makes this the one piece of evidence here that
    cannot be a coincidence - as long as the matching is exact. See
    :data:`BY_LIBRARY` for what "exact" had to be taught.
    """
    for prefix, framework in BY_LIBRARY:
        for name in loaded:
            if name.startswith(prefix):
                return framework, name
    for name in loaded:
        if not name.endswith('.bpl'):
            continue
        stem = name[:-4].rstrip('0123456789')
        if stem in DELPHI_PACKAGES:
            return 'vcl', name
    return '', ''


#: What a native Win32 program has loaded and a managed or drawn one
#: usually has not. Only ever the LAST answer, and only when the modules
#: were really read: a process that refused to say must not be reported
#: as native, which is a guess wearing the clothes of evidence.
NATIVE_LIBRARIES = ('comctl32.dll', 'comdlg32.dll')


def _looks_native(loaded):
    return any(name in NATIVE_LIBRARIES for name in loaded)


def uia_framework(obj):
    """What UI Automation calls this window's toolkit, lower-cased, or ''."""
    for attribute in ('UIAElement', '_UIAElement'):
        element = getattr(obj, attribute, None)
        if element is None:
            continue
        for name in ('CachedFrameworkId', 'CurrentFrameworkId'):
            try:
                said = _text(getattr(element, name, ''))
            except Exception:                        # noqa: BLE001
                continue
            if said:
                return said.lower()
    return ''


def _by_class(window_class):
    said = _text(window_class).lower()
    if not said:
        return ''
    for prefix, framework in BY_CLASS:
        if said.startswith(prefix) or prefix in said:
            return framework
    return ''


def _pid_of(obj):
    try:
        return int(getattr(obj, 'processID', 0) or 0)
    except (TypeError, ValueError):
        return 0


def of(obj, again=False):
    """``(framework, how, evidence)`` for the window this object is in.

    ``how`` is 'library', 'uia' or 'class' - which of the three answered,
    strongest first - and ``evidence`` is the thing that decided it, so an
    answer can always be checked rather than believed. ``('', '', '')``
    when nothing could be told, which is an honest answer about a window
    running as another user.
    """
    if obj is None:
        return '', '', ''
    pid = _pid_of(obj)
    if pid and not again:
        with _LOCK:
            kept = _known.get(pid)
        if kept is not None:
            return kept
    answer = ('', '', '')
    loaded = modules_of(pid) if pid else []
    framework, evidence = _by_library(loaded)
    if framework:
        answer = (framework, 'library', evidence)
    if not answer[0]:
        said = uia_framework(obj)
        framework = BY_UIA.get(said, '')
        if framework:
            answer = (framework, 'uia', said)
    if not answer[0]:
        window_class = _text(getattr(obj, 'windowClassName', ''))
        framework = _by_class(window_class)
        if framework:
            answer = (framework, 'class', window_class)
    if not answer[0] and loaded and _looks_native(loaded):
        # Everything else came back empty AND the modules really were
        # read: a program with the common controls loaded and no toolkit
        # library at all is a native Win32 one, which is worth saying
        # because Windows proxies its standard controls and MSAA answers
        # for them.
        answer = ('win32', 'library',
                  next(name for name in loaded if name in NATIVE_LIBRARIES))
    if pid:
        with _LOCK:
            if len(_known) > 128:
                _known.clear()
            _known[pid] = answer
    return answer


def describe(obj):
    """One sentence about what this window is written in, or ''."""
    framework, how, evidence = of(obj)
    if not framework:
        return ''
    said = word(framework)
    reason = {'library': _('it has loaded {what}'),
              'uia': _('UI Automation calls it {what}'),
              'class': _('its window class is {what}')}.get(how, '{what}')
    line = _('This window is {framework} - {why}.').format(
        framework=said, why=reason.format(what=evidence))
    extra = note(framework)
    return line + (' ' + extra if extra else '')


def forget():
    with _LOCK:
        _known.clear()


def report():
    with _LOCK:
        return {'known': len(_known)}
