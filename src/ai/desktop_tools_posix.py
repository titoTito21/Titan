"""The desktop tools' window half on Linux and macOS.

Keys and the mouse were pynput already and work everywhere; what leaned on
win32gui is the windows - which is in front, which are open, bringing one
forward, reading the focused one, photographing the screen. On Linux that
is X11 through ``xdotool``/``wmctrl`` (XWayland carries it under Wayland,
which is what WSLg and GNOME give a Titan window anyway) and the
accessibility tree through AT-SPI 2 (``gi.repository.Atspi``), the same
tree Orca reads. On macOS it is System Events through ``osascript``, which
needs the Accessibility permission the user grants once.

Every function answers a sentence, never raises, and names the tool that
is missing when one is.
"""
import os
import shutil
import subprocess
import sys
import tempfile

IS_MACOS = sys.platform == 'darwin'


def _run(command, timeout=15):
    try:
        done = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=timeout)
        return done.returncode, done.stdout.decode('utf-8', errors='replace')
    except FileNotFoundError:
        return 127, f"{command[0]} is not installed"
    except subprocess.TimeoutExpired:
        return 1, 'the command timed out'
    except Exception as e:
        return 1, str(e)


def _osascript(script):
    return _run(['osascript', '-e', script])


_FRONT_APP = ('tell application "System Events" to get name of first application '
              'process whose frontmost is true')
_FRONT_WINDOW = ('tell application "System Events" to get name of front window of '
                 'first application process whose frontmost is true')


# --------------------------------------------------------------------------- #
# Which window
# --------------------------------------------------------------------------- #
def get_foreground_window(**_):
    """Title of the focused window."""
    if IS_MACOS:
        code, app = _osascript(_FRONT_APP)
        if code:
            return f"Error reading foreground window: {app.strip()}"
        _code, title = _osascript(_FRONT_WINDOW)
        title = title.strip() if not _code else ''
        return f"Foreground window: {title or app.strip()!r} (application {app.strip()})"
    if shutil.which('xdotool'):
        code, output = _run(['xdotool', 'getactivewindow', 'getwindowname'])
        if not code:
            return f"Foreground window: {output.strip()!r}"
    focused = _atspi_focused_window()
    if focused:
        return f"Foreground window: {focused!r}"
    return "No foreground window (install xdotool, or run under a session with AT-SPI)."


def list_windows(**_):
    """Titles of the visible top-level windows."""
    if IS_MACOS:
        code, output = _osascript(
            'tell application "System Events" to get name of every window of '
            '(every application process whose visible is true)')
        if code:
            return f"Error listing windows: {output.strip()}"
        titles = [t.strip() for t in output.replace('\n', ',').split(',') if t.strip()]
    else:
        titles = None
        if shutil.which('wmctrl'):
            code, output = _run(['wmctrl', '-l'])
            if not code:
                titles = []
                for line in output.splitlines():
                    parts = line.split(None, 3)
                    if len(parts) == 4 and parts[3].strip():
                        titles.append(parts[3].strip())
        if titles is None:
            # No EWMH window manager (WSLg's is one): the accessibility tree.
            titles = _atspi_window_titles()
        if titles is None:
            return "Cannot list windows (install wmctrl, or run under a session with AT-SPI)."
    seen, uniq = set(), []
    for t in titles:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return "Open windows:\n" + "\n".join(f"- {t}" for t in uniq[:60]) if uniq else "No visible windows."


def focus_window(title, **_):
    """Bring the window whose title contains ``title`` to the front."""
    wanted = str(title or '').strip()
    if not wanted:
        return "Say part of the window's title."
    if IS_MACOS:
        script = (f'tell application "System Events"\n'
                  f'  repeat with p in (every application process whose visible is true)\n'
                  f'    repeat with w in (every window of p)\n'
                  f'      if name of w contains "{wanted}" then\n'
                  f'        set frontmost of p to true\n'
                  f'        perform action "AXRaise" of w\n'
                  f'        return name of w\n'
                  f'      end if\n'
                  f'    end repeat\n'
                  f'  end repeat\n'
                  f'end tell\nreturn ""')
        code, output = _osascript(script)
        if code:
            return f"Error focusing window: {output.strip()}"
        return f"Focused window {output.strip()!r}." if output.strip() else f"No window matches {wanted!r}."
    if shutil.which('wmctrl'):
        code, output = _run(['wmctrl', '-a', wanted])
        if not code:
            return f"Focused a window matching {wanted!r}."
    if shutil.which('xdotool'):
        code, output = _run(['xdotool', 'search', '--name', wanted, 'windowactivate'])
        if not code:
            return f"Focused a window matching {wanted!r}."
        return f"No window matches {wanted!r}."
    return "Cannot focus windows (install wmctrl or xdotool)."


# --------------------------------------------------------------------------- #
# Reading the focused window - the accessibility tree
# --------------------------------------------------------------------------- #
def _atspi():
    try:
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi
        return Atspi
    except Exception:
        return None


def _atspi_focused_window():
    Atspi = _atspi()
    if Atspi is None:
        return ''
    showing = ''
    try:
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if app is None:
                continue
            for j in range(app.get_child_count()):
                window = app.get_child_at_index(j)
                if window is None:
                    continue
                states = window.get_state_set()
                if states.contains(Atspi.StateType.ACTIVE):
                    return window.get_name() or app.get_name() or ''
                if states.contains(Atspi.StateType.SHOWING) and window.get_name():
                    showing = window.get_name()
    except Exception:
        return ''
    return showing


def _atspi_window_titles():
    Atspi = _atspi()
    if Atspi is None:
        return None
    titles = []
    try:
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if app is None:
                continue
            for j in range(app.get_child_count()):
                window = app.get_child_at_index(j)
                if window is None:
                    continue
                states = window.get_state_set()
                if states.contains(Atspi.StateType.SHOWING) and window.get_name():
                    titles.append(window.get_name())
    except Exception:
        return None
    return titles


def read_focused_window(**_):
    """The focused window: its title, the focused control, and its controls' text."""
    if IS_MACOS:
        code, app = _osascript(_FRONT_APP)
        if code:
            return f"Error reading focused window: {app.strip()}"
        _code, title = _osascript(_FRONT_WINDOW)
        lines = [f"Window: {(title.strip() if not _code else app.strip())!r}"]
        code, focused = _osascript(
            'tell application "System Events" to tell (first application process whose '
            'frontmost is true) to get {role, name, value} of (first UI element whose focused is true)')
        if not code and focused.strip():
            lines.append(f"Focused control: {focused.strip()}")
        code, controls = _osascript(
            'tell application "System Events" to tell (first application process whose '
            'frontmost is true) to get name of every UI element of front window')
        if not code:
            names = [n.strip() for n in controls.split(',') if n.strip() and n.strip() != 'missing value']
            if names:
                lines.append("Controls: " + " | ".join(names[:40]))
        elif 'not allowed assistive access' in controls:
            lines.append("(Grant Titan the Accessibility permission in System Settings to read controls.)")
        return "\n".join(lines)

    Atspi = _atspi()
    if Atspi is None:
        title = get_foreground_window()
        return title + "\n(Install python3-gi and gir1.2-atspi-2.0 to read the controls.)"
    try:
        desktop = Atspi.get_desktop(0)
        active = None
        showing = None
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if app is None:
                continue
            for j in range(app.get_child_count()):
                window = app.get_child_at_index(j)
                if window is None:
                    continue
                states = window.get_state_set()
                if states.contains(Atspi.StateType.ACTIVE):
                    active = window
                    break
                if states.contains(Atspi.StateType.SHOWING) and window.get_name():
                    showing = window
            if active is not None:
                break
        # A compositor that never marks a window ACTIVE (WSLg's Weston does
        # not, reliably) still has one showing; that is the one to read.
        active = active or showing
        if active is None:
            return "No foreground window."
        lines = [f"Window: {active.get_name()!r}"]
        texts = []
        focused = None

        def walk(node, depth):
            nonlocal focused
            if depth > 12 or len(texts) > 200:
                return
            try:
                count = node.get_child_count()
            except Exception:
                return
            for k in range(min(count, 200)):
                child = node.get_child_at_index(k)
                if child is None:
                    continue
                try:
                    states = child.get_state_set()
                    name = child.get_name() or ''
                    role = child.get_role_name() or ''
                    if states.contains(Atspi.StateType.FOCUSED) and focused is None:
                        focused = (role, name)
                    if name.strip() and role not in ('panel', 'filler', 'frame', 'window'):
                        texts.append(f"{name.strip()} ({role})")
                except Exception:
                    pass
                walk(child, depth + 1)

        walk(active, 0)
        if focused:
            lines.append(f"Focused control: role={focused[0]!r} text={focused[1]!r}")
        if texts:
            uniq = []
            for t in texts:
                if t not in uniq:
                    uniq.append(t)
            lines.append("Controls: " + " | ".join(uniq[:40]))
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading focused window: {e}"


# --------------------------------------------------------------------------- #
# A picture of the screen
# --------------------------------------------------------------------------- #
def screenshot_png_path():
    """A PNG of the screen in a temp file, or (None, reason)."""
    path = os.path.join(tempfile.gettempdir(), 'titan_screenshot.png')
    if IS_MACOS:
        code, output = _run(['screencapture', '-x', path])
        return (path, '') if not code else (None, output.strip())
    for command in (['gnome-screenshot', '-f', path], ['grim', path],
                    ['import', '-window', 'root', path], ['scrot', '-o', path],
                    ['spectacle', '-b', '-n', '-o', path]):
        if shutil.which(command[0]):
            code, output = _run(command, timeout=30)
            if not code and os.path.exists(path):
                return path, ''
    return None, "no screenshot tool found (gnome-screenshot, grim, scrot or ImageMagick's import)"
