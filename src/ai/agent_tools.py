"""Computer-control tools for the Titan AI Agent (see :mod:`src.ai.ai_agent`).

Each tool is a dict {name, description, parameters (JSON-schema), run, risk}.
``risk`` is 'auto' (observation and ordinary operating: read screen, type, keys,
click, focus) or 'confirm' (executing programs / shell, writing or deleting
files) which the agent gates through the confirmation policy. ``always_confirm``
marks tools (run_shell) that must prompt even under the most permissive policy.

Observation reads the foreground window and its child controls via Win32 (no COM
typelib needed); richer UIA object navigation and screenshot/vision are planned
follow-ups. Input synthesis uses pynput.
"""

import os
import subprocess
import sys

try:
    from src.titan_core.translation import set_language
    from src.settings.settings import get_setting
    _ = set_language(get_setting('language', 'pl'))
except Exception:  # pragma: no cover - translation is optional at import time
    def _(s):
        return s


# --------------------------------------------------------------------------- #
# Human-readable action descriptions (for narration / confirm dialogs)
# --------------------------------------------------------------------------- #
def _clip(value, limit=80):
    s = str(value).replace('\n', ' ').strip()
    return s if len(s) <= limit else s[:limit] + '...'


def describe_action(name, args):
    """A short, human-readable sentence for a tool call, for the on-screen
    transcript / spoken narration / confirm dialogs - so the user never sees a
    raw identifier like ``run_shell(command=...)``."""
    a = args or {}

    def g(key, default=''):
        v = a.get(key, default)
        return _clip(v) if v not in (None, '') else default

    simple = {
        'get_foreground_window': _("Checking the active window"),
        'list_windows': _("Listing the open windows"),
        'read_focused_window': _("Reading the current window"),
        'screenshot': _("Taking a screenshot to see the screen"),
        'speak': _("Speaking to you"),
        'titan_list_settings': _("Reading Titan settings"),
        'titan_list_components': _("Listing Titan components"),
        'titan_list_addons': _("Listing Titan add-ons"),
        'titan_list_tts_engines': _("Listing the TTS engines"),
        'titan_open_settings': _("Opening Titan settings"),
        'list_tce_items': _("Listing Titan apps and games"),
    }
    if name in simple and not (name == 'titan_list_settings' and a.get('section')):
        return simple[name]

    handlers = {
        'list_files': lambda: _("Listing files in {path}").format(path=g('path') or '.'),
        'read_file': lambda: _("Reading the file {path}").format(path=g('path')),
        'type_text': lambda: _("Typing text"),
        'press_keys': lambda: _("Pressing {keys}").format(keys=g('keys')),
        'click': lambda: _("Clicking at {x}, {y}").format(x=a.get('x'), y=a.get('y')),
        'move_mouse': lambda: _("Moving the mouse to {x}, {y}").format(x=a.get('x'), y=a.get('y')),
        'focus_window': lambda: _("Switching to the window {title}").format(title=g('title')),
        'launch_program': lambda: _("Launching {path}").format(path=g('path')),
        'run_shell': lambda: _("Running a system command: {command}").format(command=g('command')),
        'write_file': lambda: _("Writing the file {path}").format(path=g('path')),
        'delete_path': lambda: _("Deleting {path}").format(path=g('path')),
        'web_search': lambda: _("Searching the web for {query}").format(query=g('query')),
        'get_definition': lambda: _("Looking up the definition of {term}").format(term=g('term')),
        'get_weather': lambda: (_("Checking the weather for {loc}").format(loc=g('location'))
                                if a.get('location') else _("Checking the weather")),
        'launch_tce_item': lambda: _("Launching {name}").format(name=g('name')),
        'play_music': lambda: (
            _("Playing {q} on {src}").format(q=g('query'), src=g('source'))
            if a.get('query') and a.get('source')
            else _("Playing {q}").format(q=g('query')) if a.get('query')
            else _("Playing music")),
        'titan_get_setting': lambda: _("Reading the setting {name}").format(
            name=f"{a.get('section', 'general')}.{g('key')}"),
        'titan_set_setting': lambda: _("Changing the setting {name} to {value}").format(
            name=f"{a.get('section', 'general')}.{g('key')}", value=g('value')),
        'titan_list_settings': lambda: _("Reading the {section} settings").format(section=g('section')),
        'titan_run_component_action': lambda: _("Running the component action {action}").format(action=g('action')),
        'titan_set_component_enabled': lambda: (
            _("Enabling the component {name}") if str(a.get('enabled', True)).lower() in ('true', '1', 'yes')
            else _("Disabling the component {name}")).format(name=g('component')),
        'titan_launch': lambda: _("Launching {name}").format(name=g('name')),
        'titan_im_login': lambda: _("Logging in to {service} as {user}").format(
            service=g('service'), user=g('username')),
        'titan_list_im_contacts': lambda: _("Listing {service} contacts").format(service=g('service')),
        'titan_send_message': lambda: _("Sending a message to {recipient} on {service}").format(
            recipient=g('recipient'), service=g('service')),
        'ask_user': lambda: _("Asking you: {question}").format(question=g('question')),
        'browser_open': lambda: _("Opening the web page {url}").format(url=g('url')),
        'browser_read': lambda: _("Reading the web page"),
        'browser_fill': lambda: _("Filling in the field {field}").format(field=g('field')),
        'browser_select': lambda: _("Choosing {option} for {field}").format(
            option=g('option'), field=g('field')),
        'browser_check': lambda: _("Ticking the box {field}").format(field=g('field')),
        'browser_click': lambda: _("Clicking {target} on the page").format(target=g('target')),
        'browser_submit': lambda: _("Submitting the form"),
        'browser_back': lambda: _("Going back to the previous page"),
        'browser_close': lambda: _("Closing the browser"),
    }
    if name in handlers:
        try:
            return handlers[name]()
        except Exception:
            pass
    if name in simple:
        return simple[name]
    # Unknown tool (e.g. one contributed by a component): we have no hand-written
    # phrase for it. Return None so narration defers to the AI's OWN generated
    # text describing what it is doing; callers that must show something (confirm
    # dialogs) fall back to the tool's human-readable description.
    return None


# --------------------------------------------------------------------------- #
# Observation (risk: auto)
# --------------------------------------------------------------------------- #
def _win32():
    import win32gui
    return win32gui


def get_foreground_window(**_):
    """Title of the currently focused (foreground) window."""
    try:
        w = _win32()
        hwnd = w.GetForegroundWindow()
        title = w.GetWindowText(hwnd)
        return f"Foreground window: {title!r} (hwnd {hwnd})" if hwnd else "No foreground window."
    except Exception as e:
        return f"Error reading foreground window: {e}"


def list_windows(**_):
    """List titles of visible top-level windows."""
    try:
        w = _win32()
        out = []

        def _cb(hwnd, _acc):
            if w.IsWindowVisible(hwnd):
                t = w.GetWindowText(hwnd)
                if t.strip():
                    out.append(t)
        w.EnumWindows(_cb, None)
        seen, uniq = set(), []
        for t in out:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        return "Open windows:\n" + "\n".join(f"- {t}" for t in uniq[:60]) if uniq else "No visible windows."
    except Exception as e:
        return f"Error listing windows: {e}"


def read_focused_window(**_):
    """Read the foreground window: its title, the focused control, and the text
    of its child controls (buttons, labels, list items) so the agent can 'see'
    the screen through the accessibility/Win32 layer."""
    try:
        import win32gui
        import win32process
        import ctypes
        from ctypes import wintypes
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return "No foreground window."
        title = win32gui.GetWindowText(hwnd)
        lines = [f"Window: {title!r}"]

        # Focused control via GUI thread info.
        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                        ("rcCaret", wintypes.RECT)]
        gti = GUITHREADINFO()
        gti.cbSize = ctypes.sizeof(GUITHREADINFO)
        tid, _pid = win32process.GetWindowThreadProcessId(hwnd)
        if ctypes.windll.user32.GetGUIThreadInfo(tid, ctypes.byref(gti)) and gti.hwndFocus:
            ft = win32gui.GetWindowText(gti.hwndFocus)
            fc = win32gui.GetClassName(gti.hwndFocus)
            lines.append(f"Focused control: class={fc!r} text={ft!r}")

        # Child controls' text.
        texts = []

        def _cb(child, _acc):
            t = win32gui.GetWindowText(child)
            if t.strip():
                texts.append(t.strip())
        try:
            win32gui.EnumChildWindows(hwnd, _cb, None)
        except Exception:
            pass
        if texts:
            uniq = []
            for t in texts:
                if t not in uniq:
                    uniq.append(t)
            lines.append("Controls: " + " | ".join(uniq[:40]))
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading focused window: {e}"


def _encode_png(arr):
    """Encode an (h, w, 3) uint8 RGB numpy array to PNG bytes (no PIL needed)."""
    import zlib
    import struct
    import numpy as np
    h, w = arr.shape[0], arr.shape[1]
    # Prepend a zero filter byte to every scanline, then zlib-compress.
    raw = np.zeros((h, 1 + w * 3), dtype=np.uint8)
    raw[:, 1:] = arr.reshape(h, w * 3)
    compressed = zlib.compress(raw.tobytes(), 6)

    def chunk(typ, data):
        return (struct.pack('>I', len(data)) + typ + data
                + struct.pack('>I', zlib.crc32(typ + data) & 0xffffffff))
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)  # 8-bit, colour type 2 (RGB)
    return sig + chunk(b'IHDR', ihdr) + chunk(b'IDAT', compressed) + chunk(b'IEND', b'')


def _capture_primary_screen():
    """Grab the primary monitor via GDI. Returns (rgb_ndarray, screen_w, screen_h)."""
    import numpy as np
    import win32gui
    import win32ui
    import win32con
    import win32api
    sw = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
    sh = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
    hwnd = win32gui.GetDesktopWindow()
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc_dc, sw, sh)
    save_dc.SelectObject(bmp)
    save_dc.BitBlt((0, 0), (sw, sh), mfc_dc, (0, 0), win32con.SRCCOPY)
    bits = bmp.GetBitmapBits(True)  # BGRA, top-down
    arr = np.frombuffer(bits, dtype=np.uint8).reshape(sh, sw, 4)
    rgb = arr[:, :, [2, 1, 0]].copy()  # BGRA -> RGB
    # Clean up GDI resources.
    win32gui.DeleteObject(bmp.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)
    return rgb, sw, sh


def screenshot(**_):
    """Capture the primary screen as an image so you can SEE what is on screen,
    then click by coordinates. Returns an image plus the true screen size.

    IMPORTANT: give click/move coordinates in ACTUAL screen pixels (the full
    screen size reported below), not image pixels."""
    try:
        import math
        rgb, sw, sh = _capture_primary_screen()
        # Downscale so the longest side is <= 1568 px (keeps tokens sane).
        factor = max(1, math.ceil(max(sw, sh) / 1568))
        if factor > 1:
            rgb = rgb[::factor, ::factor]
        ih, iw = rgb.shape[0], rgb.shape[1]
        png = _encode_png(rgb)
        note = (f"Screenshot captured. The image is {iw}x{ih} pixels; the ACTUAL "
                f"screen is {sw}x{sh} pixels. Give click/move coordinates in "
                f"ACTUAL screen pixels (0..{sw} wide, 0..{sh} tall).")
        return {'text': note, 'image_png': png}
    except Exception as e:
        return f"Error taking screenshot: {e}"


def list_files(path=".", **_):
    """List entries in a directory."""
    try:
        path = os.path.expanduser(path or ".")
        if not os.path.isdir(path):
            return f"Not a directory: {path}"
        entries = sorted(os.listdir(path))
        marked = [(e + "/" if os.path.isdir(os.path.join(path, e)) else e) for e in entries]
        return f"{path}:\n" + "\n".join(marked[:200]) if marked else f"{path} is empty."
    except Exception as e:
        return f"Error listing {path}: {e}"


def read_file(path, max_chars=8000, **_):
    """Read a text file (capped)."""
    try:
        path = os.path.expanduser(path)
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            data = fh.read(int(max_chars) + 1)
        if len(data) > int(max_chars):
            data = data[:int(max_chars)] + "\n... (truncated)"
        return data or "(empty file)"
    except Exception as e:
        return f"Error reading {path}: {e}"


# --------------------------------------------------------------------------- #
# Input synthesis (risk: auto - ordinary operating)
# --------------------------------------------------------------------------- #
def _kbd():
    from pynput.keyboard import Controller, Key
    return Controller, Key


def type_text(text, **_):
    """Type text at the current keyboard focus."""
    try:
        Controller, _Key = _kbd()
        Controller().type(str(text))
        return f"Typed {len(str(text))} characters."
    except Exception as e:
        return f"Error typing: {e}"


_KEY_ALIASES = {
    'enter': 'enter', 'return': 'enter', 'tab': 'tab', 'esc': 'esc', 'escape': 'esc',
    'space': 'space', 'backspace': 'backspace', 'delete': 'delete', 'del': 'delete',
    'home': 'home', 'end': 'end', 'pageup': 'page_up', 'pagedown': 'page_down',
    'up': 'up', 'down': 'down', 'left': 'left', 'right': 'right',
    'ctrl': 'ctrl', 'control': 'ctrl', 'alt': 'alt', 'shift': 'shift',
    'win': 'cmd', 'cmd': 'cmd', 'super': 'cmd',
}


def press_keys(keys, **_):
    """Press a key or chord, e.g. 'enter', 'ctrl+s', 'alt+F4'. Function keys
    like 'f4' and single characters are supported."""
    try:
        _Controller, Key = _kbd()
        from pynput.keyboard import Controller
        kb = Controller()
        parts = [p.strip() for p in str(keys).replace(' ', '').split('+') if p.strip()]
        resolved = []
        for p in parts:
            low = p.lower()
            if low in _KEY_ALIASES:
                resolved.append(getattr(Key, _KEY_ALIASES[low]))
            elif len(low) == 2 and low[0] == 'f' and low[1:].isdigit():
                resolved.append(getattr(Key, low))  # f1..f9
            elif low.startswith('f') and low[1:].isdigit():
                resolved.append(getattr(Key, low))  # f10..f12
            else:
                resolved.append(p if len(p) == 1 else p)
        # Modifiers held around the final key.
        *mods, last = resolved
        for m in mods:
            kb.press(m)
        try:
            kb.press(last)
            kb.release(last)
        finally:
            for m in reversed(mods):
                kb.release(m)
        return f"Pressed {keys}."
    except Exception as e:
        return f"Error pressing keys {keys}: {e}"


def _mouse():
    from pynput.mouse import Controller, Button
    return Controller, Button


def click(x, y, button="left", **_):
    """Move the mouse to (x, y) and click. button is 'left', 'right' or 'middle'."""
    try:
        Controller, Button = _mouse()
        m = Controller()
        m.position = (int(x), int(y))
        btn = {'left': Button.left, 'right': Button.right, 'middle': Button.middle}.get(str(button), Button.left)
        m.click(btn, 1)
        return f"Clicked {button} at ({int(x)}, {int(y)})."
    except Exception as e:
        return f"Error clicking: {e}"


def move_mouse(x, y, **_):
    """Move the mouse cursor to (x, y)."""
    try:
        Controller, _Button = _mouse()
        Controller().position = (int(x), int(y))
        return f"Moved mouse to ({int(x)}, {int(y)})."
    except Exception as e:
        return f"Error moving mouse: {e}"


def focus_window(title, **_):
    """Bring the first visible window whose title contains ``title`` to the front."""
    try:
        w = _win32()
        target = [None]

        def _cb(hwnd, _acc):
            if w.IsWindowVisible(hwnd) and title.lower() in w.GetWindowText(hwnd).lower():
                if target[0] is None:
                    target[0] = hwnd
        w.EnumWindows(_cb, None)
        if target[0] is None:
            return f"No window matching {title!r}."
        try:
            w.ShowWindow(target[0], 9)  # SW_RESTORE
        except Exception:
            pass
        w.SetForegroundWindow(target[0])
        return f"Focused window {w.GetWindowText(target[0])!r}."
    except Exception as e:
        return f"Error focusing window: {e}"


def speak(text, **_):
    """Speak a short message to the user via Titan TTS / screen reader."""
    try:
        from src.ai.ai_speech import speak as _speak
        _speak(str(text))
        return "Spoke to the user."
    except Exception as e:
        return f"Could not speak: {e}"


# --------------------------------------------------------------------------- #
# Executing / mutating (risk: confirm)
# --------------------------------------------------------------------------- #
# Friendly names the model is likely to use for common Windows programs that
# are NOT on PATH: they live in the "App Paths" registry, which only ShellExecute
# / cmd's ``start`` resolves - a bare ``cmd /c msedge`` fails silently.
_KNOWN_PROGRAMS = {
    'edge': 'msedge', 'microsoft edge': 'msedge', 'ms edge': 'msedge', 'msedge': 'msedge',
    'chrome': 'chrome', 'google chrome': 'chrome',
    'firefox': 'firefox', 'mozilla firefox': 'firefox',
    'brave': 'brave', 'opera': 'opera',
    'notepad': 'notepad', 'wordpad': 'wordpad', 'paint': 'mspaint',
    'calculator': 'calc', 'calc': 'calc',
    'explorer': 'explorer', 'file explorer': 'explorer',
    'cmd': 'cmd', 'command prompt': 'cmd', 'powershell': 'powershell',
    'word': 'winword', 'excel': 'excel', 'powerpoint': 'powerpnt', 'outlook': 'outlook',
}


def launch_program(path, args="", **_):
    """Launch a program or open a file/URL with its default handler."""
    try:
        raw = str(path).strip()
        expanded = os.path.expanduser(raw)

        # 1. A real file/executable path we can see on disk.
        if os.path.exists(expanded):
            if args:
                subprocess.Popen([expanded] + str(args).split())
            else:
                os.startfile(expanded)  # noqa: intended - opens with default handler
            return f"Launched: {expanded} {args}".strip()

        # 2. A URL / URI -> open with the OS default handler (browser, etc.).
        scheme = raw.split('://', 1)[0]
        if '://' in raw and scheme and all(c.isalnum() or c in '+.-' for c in scheme):
            os.startfile(raw)  # noqa: intended - opens with default handler
            return f"Opened: {raw}"

        # 3. A program name (possibly friendly, e.g. "Microsoft Edge"). Resolve
        #    known aliases then launch via cmd's ``start``, which - unlike a bare
        #    ``cmd /c <name>`` - consults the App Paths registry, so browsers and
        #    Office apps that are not on PATH still launch.
        target = _KNOWN_PROGRAMS.get(raw.lower(), raw)
        cmd = f'start "" "{target}"' + (f' {args}' if args else '')
        subprocess.Popen(cmd, shell=True)
        return f"Launched: {target} {args}".strip()
    except Exception as e:
        return f"Error launching {path}: {e}"


def run_shell(command, **_):
    """Run a shell command and return its output (stdout+stderr, capped)."""
    try:
        proc = subprocess.run(command, shell=True, capture_output=True, text=True,
                              timeout=60, encoding='utf-8', errors='replace')
        out = (proc.stdout or '') + (proc.stderr or '')
        out = out.strip() or f"(no output, exit code {proc.returncode})"
        return out[:6000]
    except subprocess.TimeoutExpired:
        return "Command timed out after 60 seconds."
    except Exception as e:
        return f"Error running command: {e}"


def write_file(path, content, **_):
    """Write text to a file (creates or overwrites)."""
    try:
        path = os.path.expanduser(path)
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(str(content))
        return f"Wrote {len(str(content))} characters to {path}."
    except Exception as e:
        return f"Error writing {path}: {e}"


def delete_path(path, **_):
    """Delete a file or an (empty) directory."""
    try:
        path = os.path.expanduser(path)
        if os.path.isdir(path):
            os.rmdir(path)
        else:
            os.remove(path)
        return f"Deleted {path}."
    except Exception as e:
        return f"Error deleting {path}: {e}"


# --------------------------------------------------------------------------- #
# Tool registry
# --------------------------------------------------------------------------- #
def _tool(name, description, run, risk='auto', properties=None, required=None,
          always_confirm=False):
    return {
        'name': name, 'description': description, 'run': run, 'risk': risk,
        'always_confirm': always_confirm,
        'parameters': {
            'type': 'object',
            'properties': properties or {},
            'required': required or [],
        },
    }


def get_tools():
    """The full toolset available to the agent (Windows)."""
    S = {'type': 'string'}
    N = {'type': 'number'}
    return [
        _tool('get_foreground_window', "Get the title of the focused window.", get_foreground_window),
        _tool('list_windows', "List titles of all visible windows.", list_windows),
        _tool('read_focused_window',
              "Read the focused window: title, focused control and child control "
              "text, so you can see what is on screen.", read_focused_window),
        _tool('screenshot',
              "Capture the screen as an image so you can visually see what is on "
              "screen, then click by coordinates. Coordinates are ACTUAL screen "
              "pixels.", screenshot),
        _tool('list_files', "List entries in a directory.", list_files,
              properties={'path': dict(S, description="Directory path (default current).")}),
        _tool('read_file', "Read a text file (capped).", read_file,
              properties={'path': dict(S, description="File path."),
                          'max_chars': dict(N, description="Max characters (default 8000).")},
              required=['path']),
        _tool('type_text', "Type text at the current keyboard focus.", type_text,
              properties={'text': dict(S, description="Text to type.")}, required=['text']),
        _tool('press_keys', "Press a key or chord, e.g. 'enter', 'ctrl+s', 'alt+F4'.",
              press_keys, properties={'keys': dict(S, description="Key or chord.")},
              required=['keys']),
        _tool('click', "Move the mouse and click at screen coordinates.", click,
              properties={'x': N, 'y': N,
                          'button': dict(S, description="left, right or middle.")},
              required=['x', 'y']),
        _tool('move_mouse', "Move the mouse cursor to screen coordinates.", move_mouse,
              properties={'x': N, 'y': N}, required=['x', 'y']),
        _tool('focus_window', "Bring a window (matched by title substring) to the front.",
              focus_window, properties={'title': dict(S, description="Title substring.")},
              required=['title']),
        _tool('speak', "Speak a short message to the user via the screen reader.",
              speak, properties={'text': dict(S, description="Message to speak.")},
              required=['text']),
        # Confirm-tier: executing / mutating.
        _tool('launch_program', "Launch a program, or open a file/URL with its "
              "default handler.", launch_program, risk='confirm',
              properties={'path': dict(S, description="Program path, file or URL."),
                          'args': dict(S, description="Optional command-line arguments.")},
              required=['path']),
        _tool('run_shell', "Run a shell command and return its output.", run_shell,
              risk='confirm', always_confirm=True,
              properties={'command': dict(S, description="Command line to run.")},
              required=['command']),
        _tool('write_file', "Write (create or overwrite) a text file.", write_file,
              risk='confirm',
              properties={'path': dict(S, description="File path."),
                          'content': dict(S, description="Text content.")},
              required=['path', 'content']),
        _tool('delete_path', "Delete a file or an empty directory.", delete_path,
              risk='confirm', properties={'path': dict(S, description="Path to delete.")},
              required=['path']),
    ] + _browser_tools() + _titan_tools()


def _browser_tools():
    """Web-browser automation tools (navigate pages, fill in forms). Imported
    lazily so a missing selenium install never breaks the rest of the toolset."""
    try:
        from src.ai.browser_tools import get_browser_tools
        return get_browser_tools()
    except Exception as e:
        print(f"[agent_tools] Browser tools unavailable: {e}")
        return []


def _titan_tools():
    """Titan-native tools (settings, components, add-ons, IM). Imported lazily
    to avoid an import cycle (titan_tools imports _tool from this module)."""
    try:
        from src.ai.titan_tools import get_titan_tools
        return get_titan_tools()
    except Exception as e:
        print(f"[agent_tools] Titan tools unavailable: {e}")
        return []
