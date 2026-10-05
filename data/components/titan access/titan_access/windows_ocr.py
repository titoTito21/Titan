# -*- coding: utf-8 -*-
"""Windows' own recogniser, owned by Titan Access.

Inside NVDA a window is read with `contentRecog.uwpOcr`. Titan Access is
not NVDA, and it used to reach the same recogniser by asking TITAN for it
(``ocr.read_windows`` on Titan's typed doorway). That made the reader's
screen review, its local reading and its picture fallback depend on the
Titan it happens to be running in having that doorway - and a compiled
Titan freezes its own modules while this component is plain data beside
it, so a newer Titan Access in an older Titan answered every "read this
window" key with **"this Titan has no bridge call 'ocr.read_windows'"**.

So the reader owns it, start to finish, and needs nothing but Windows:

* the picture is taken here, with GDI (the screen behind the window's
  rectangle, then `PrintWindow` when that came back one flat colour);
* it is written as a PNG here (zlib, no imaging library);
* `Windows.Media.Ocr` - which every Windows 10 and 11 has - is asked
  through a short PowerShell script that loads the WinRT types and prints
  the lines with every word's rectangle as JSON.

No package to install, no NVDA, no add-on, nothing sent anywhere. Every
answer is a dict with ``ok`` and, when it failed, ``text`` saying WHY -
a reader must be told why it could not read, never handed an exception.
The shape is the one Titan's doorway answers, so `portable/link.py` can
answer ``ocr.windows`` / ``ocr.read_windows`` with it and the shared
`localOcr` cannot tell the difference.
"""

import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib

_IS_WINDOWS = sys.platform.startswith('win')

#: Long enough for a cold PowerShell and a big window.
TIMEOUT = 20.0

#: Remembered this long: the probe is a PowerShell start, and the reader
#: asks before every reading.
PROBE_KEPT = 600.0

_LOCK = threading.RLock()
_state = {'reads': 0, 'failed': 0, 'why': '', 'ms': 0.0, 'language': '',
          'captured': ''}
_available = {'checked': 0.0, 'ok': None, 'why': ''}

_SCRIPT = r"""
param([string]$Path, [string]$Lang = '', [switch]$Probe)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
  $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
  $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
  $engine = $null
  if ($Lang) {
    try { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($Lang)) } catch { $engine = $null }
  }
  if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
  if (-not $engine) {
    Write-Output '{"ok":false,"text":"Windows has no OCR language installed. Add one in Windows Settings, under Language."}'
    exit
  }
  if ($Probe) {
    $langs = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag })
    Write-Output (ConvertTo-Json @{ ok = $true; language = $engine.RecognizerLanguage.LanguageTag; languages = $langs } -Compress)
    exit
  }
  $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
  function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
  $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
  $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
  $stream.Dispose()
  $lines = @()
  foreach ($line in $result.Lines) {
    $words = @()
    foreach ($w in $line.Words) {
      $r = $w.BoundingRect
      $words += @{ text = $w.Text; left = [int]$r.X; top = [int]$r.Y; width = [int]$r.Width; height = [int]$r.Height }
    }
    $lines += ,@($words)
  }
  Write-Output (ConvertTo-Json @{ ok = $true; lines = $lines; language = $engine.RecognizerLanguage.LanguageTag } -Depth 6 -Compress)
} catch {
  Write-Output (ConvertTo-Json @{ ok = $false; text = ('Windows OCR failed: ' + $_.Exception.Message) } -Compress)
}
"""


#: The same recogniser as a RESIDENT process: one request per line on
#: stdin (``path<TAB>language``), one JSON answer per line on stdout.
#: Starting PowerShell and loading the WinRT types is most of a second;
#: a reading itself is a tenth of one - and a caret read on every arrow
#: key cannot pay the first part each time.
_SERVER = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
[Console]::InputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
$engines = @{}
[Console]::Out.WriteLine('{"ok":true,"ready":true}'); [Console]::Out.Flush()
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($line -eq $null) { break }
  try {
    $parts = $line.Split("`t")
    $path = $parts[0]; $lang = ''
    if ($parts.Count -gt 1) { $lang = $parts[1] }
    if (-not $engines.ContainsKey($lang)) {
      $engine = $null
      if ($lang) { try { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($lang)) } catch { $engine = $null } }
      if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
      $engines[$lang] = $engine
    }
    $engine = $engines[$lang]
    if (-not $engine) { [Console]::Out.WriteLine('{"ok":false,"text":"Windows has no OCR language installed."}'); [Console]::Out.Flush(); continue }
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $stream.Dispose()
    $lines = @()
    foreach ($l in $result.Lines) {
      $words = @()
      foreach ($w in $l.Words) { $r = $w.BoundingRect; $words += @{ text = $w.Text; left = [int]$r.X; top = [int]$r.Y; width = [int]$r.Width; height = [int]$r.Height } }
      $lines += ,@($words)
    }
    [Console]::Out.WriteLine((ConvertTo-Json @{ ok = $true; lines = $lines; language = $engine.RecognizerLanguage.LanguageTag } -Depth 6 -Compress))
  } catch {
    [Console]::Out.WriteLine((ConvertTo-Json @{ ok = $false; text = ('Windows OCR failed: ' + $_.Exception.Message) } -Compress))
  }
  [Console]::Out.Flush()
}
"""

_server = {'process': None, 'lock': threading.Lock(), 'started': 0}


def stop_server():
    """End the resident recogniser - with the reader, or by the tests."""
    process = _server.get('process')
    _server['process'] = None
    if process is not None:
        try:
            process.kill()
        except Exception:                            # noqa: BLE001
            pass


import atexit                                         # noqa: E402
atexit.register(stop_server)


def _server_path():
    path = os.path.join(_folder(), 'windows_ocr_server.ps1')
    try:
        with open(path, 'r', encoding='utf-8-sig') as handle:
            if handle.read() == _SERVER:
                return path
    except OSError:
        pass
    with open(path, 'w', encoding='utf-8-sig') as handle:
        handle.write(_SERVER)
    return path


def _ask_server(path, language, timeout=TIMEOUT):
    """One reading by the resident recogniser, or None when it cannot be
    had (then the one-shot script is used)."""
    if not _IS_WINDOWS:
        return None
    with _server['lock']:
        process = _server['process']
        if process is None or process.poll() is not None:
            try:
                flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                process = subprocess.Popen(
                    ['powershell.exe', '-NoProfile', '-NonInteractive',
                     '-ExecutionPolicy', 'Bypass', '-File', _server_path()],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, creationflags=flags)
                first = process.stdout.readline()
                if b'ready' not in first:
                    process.kill()
                    return None
            except Exception:                        # noqa: BLE001
                return None
            _server['process'] = process
            _server['started'] += 1
        try:
            request = ('%s\t%s\n' % (path, language or '')).encode('utf-8')
            process.stdin.write(request)
            process.stdin.flush()
            answer = _readline_within(process, timeout)
        except Exception:                            # noqa: BLE001
            answer = None
        if answer is None:
            try:
                process.kill()
            except Exception:                        # noqa: BLE001
                pass
            _server['process'] = None
            return None
    try:
        found = json.loads(answer.decode('utf-8', 'replace').lstrip('\ufeff'))
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def _readline_within(process, timeout):
    """A line from the server, or None when it took longer than timeout."""
    box = {}

    def read():
        box['line'] = process.stdout.readline()

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(timeout)
    line = box.get('line')
    return line if line else None


def _text(value):
    return str(value or '').strip()


def _folder():
    folder = os.path.join(tempfile.gettempdir(), 'titan_access_ocr')
    os.makedirs(folder, exist_ok=True)
    return folder


def _script_path():
    """The script, written into the temp folder when it is not already
    there as it should be. A file rather than ``-Command``: quoting a
    script this long for a command line is a bug factory."""
    path = os.path.join(_folder(), 'windows_ocr.ps1')
    try:
        with open(path, 'r', encoding='utf-8-sig') as handle:
            if handle.read() == _SCRIPT:
                return path
    except OSError:
        pass
    with open(path, 'w', encoding='utf-8-sig') as handle:
        handle.write(_SCRIPT)
    return path


def _run(arguments, timeout=TIMEOUT):
    """PowerShell with the script; the parsed JSON, or ``{'ok': False}``."""
    if not _IS_WINDOWS:
        return {'ok': False, 'text': 'Windows OCR exists only on Windows'}
    command = ['powershell.exe', '-NoProfile', '-NonInteractive',
               '-ExecutionPolicy', 'Bypass', '-File', _script_path()]
    command += list(arguments)
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        done = subprocess.run(command, capture_output=True, timeout=timeout,
                              creationflags=flags)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'text': 'Windows OCR did not answer in time'}
    except Exception as error:                       # noqa: BLE001
        return {'ok': False,
                'text': 'PowerShell could not be started: %s' % error}
    out = (done.stdout or b'').decode('utf-8', 'replace').strip()
    # Only the last line is the answer; anything before it is PowerShell
    # talking to itself (a profile warning, a progress record).
    last = out.splitlines()[-1] if out else ''
    try:
        found = json.loads(last.lstrip('﻿'))
    except ValueError:
        err = (done.stderr or b'').decode('utf-8', 'replace').strip()
        return {'ok': False, 'text': 'Windows OCR answered nothing readable'
                + (': ' + err[:200] if err else '')}
    return found if isinstance(found, dict) else {'ok': False,
                                                  'text': 'no answer'}


def available(force=False):
    """Whether Windows' recogniser can be asked here. ``(ok, why)``."""
    with _LOCK:
        fresh = time.time() - _available['checked'] < PROBE_KEPT
        if fresh and not force and _available['ok'] is not None:
            return bool(_available['ok']), _available['why']
    found = _run(['-Probe'])
    ok = bool(found.get('ok'))
    why = '' if ok else (_text(found.get('text'))
                         or 'Windows OCR is not here')
    with _LOCK:
        _available.update({'checked': time.time(), 'ok': ok, 'why': why})
        if ok:
            _state['language'] = _text(found.get('language'))
    return ok, why


# --------------------------------------------------------------------------- #
# The picture
# --------------------------------------------------------------------------- #

def encode_png(width, height, bgra):
    """A 32-bit top-down BGRA buffer as an RGB PNG. Titan Access carries
    no imaging library and needs none for this."""
    rows = []
    stride = width * 4
    for y in range(height):
        row = bgra[y * stride:(y + 1) * stride]
        rgb = bytearray(width * 3)
        rgb[0::3] = row[2::4]
        rgb[1::3] = row[1::4]
        rgb[2::3] = row[0::4]
        rows.append(b'\x00' + bytes(rgb))
    raw = zlib.compress(b''.join(rows), 6)

    def chunk(kind, data):
        body = kind + data
        return (struct.pack('>I', len(data)) + body
                + struct.pack('>I', zlib.crc32(body) & 0xffffffff))

    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header)
            + chunk(b'IDAT', raw) + chunk(b'IEND', b''))


def _flat(bgra):
    """Whether a capture is one colour and nothing else - what a window
    that would not draw itself gives. A picture that is MOSTLY one colour
    (a desktop, a document) is not flat."""
    if len(bgra) < 8:
        return True
    first = bgra[0:3]
    step = max(4, (len(bgra) // 4 // 2304) * 4)
    for at in range(0, len(bgra) - 3, step):
        if bgra[at:at + 3] != first:
            return False
    return True


def window_rect(hwnd):
    """``(left, top, right, bottom)`` of a window on the screen, or None."""
    if not _IS_WINDOWS or not hwnd:
        return None
    import ctypes
    from ctypes import wintypes
    rect = wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(wintypes.HWND(int(hwnd)),
                                               ctypes.byref(rect)):
        return None
    if rect.right <= rect.left or rect.bottom <= rect.top:
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def _screen_rect():
    import ctypes
    user32 = ctypes.windll.user32
    left = user32.GetSystemMetrics(76)      # SM_XVIRTUALSCREEN
    top = user32.GetSystemMetrics(77)
    width = user32.GetSystemMetrics(78)
    height = user32.GetSystemMetrics(79)
    return left, top, left + width, top + height


def capture(left, top, width, height, hwnd=0):
    """``(width, height, bgra)`` of a rectangle of the screen, or None.

    The screen first, because that is what the user is looking at; a
    window that composes with Direct3D can come back flat from the screen
    and whole from `PrintWindow` (asked with PW_RENDERFULLCONTENT), so
    that is tried before the capture is given up on.
    """
    if not _IS_WINDOWS or width <= 0 or height <= 0:
        return None
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    user32.GetAncestor.restype = ctypes.c_void_p
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetDC.restype = ctypes.c_void_p
    user32.GetDC.argtypes = [ctypes.c_void_p]
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.GetWindowDC.restype = ctypes.c_void_p
    user32.GetWindowDC.argtypes = [ctypes.c_void_p]
    user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_uint]
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
    gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                             ctypes.c_int]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.BitBlt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                             ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
    gdi32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_uint, ctypes.c_uint,
                                ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_uint]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [('biSize', wintypes.DWORD), ('biWidth', ctypes.c_long),
                    ('biHeight', ctypes.c_long), ('biPlanes', wintypes.WORD),
                    ('biBitCount', wintypes.WORD),
                    ('biCompression', wintypes.DWORD),
                    ('biSizeImage', wintypes.DWORD),
                    ('biXPelsPerMeter', ctypes.c_long),
                    ('biYPelsPerMeter', ctypes.c_long),
                    ('biClrUsed', wintypes.DWORD),
                    ('biClrImportant', wintypes.DWORD)]

    def read_bits(memory, bitmap):
        info = BITMAPINFOHEADER()
        info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.biWidth = width
        info.biHeight = -height                 # top-down
        info.biPlanes = 1
        info.biBitCount = 32
        buffer = ctypes.create_string_buffer(width * height * 4)
        got = gdi32.GetDIBits(memory, bitmap, 0, height, buffer,
                              ctypes.byref(info), 0)
        return buffer.raw if got else None

    def grab(source_dc, x, y):
        memory = gdi32.CreateCompatibleDC(source_dc)
        bitmap = gdi32.CreateCompatibleBitmap(source_dc, width, height)
        old = gdi32.SelectObject(memory, bitmap)
        try:
            if not gdi32.BitBlt(memory, 0, 0, width, height, source_dc,
                                x, y, 0x00CC0020 | 0x40000000):
                return None
            gdi32.SelectObject(memory, old)
            return read_bits(memory, bitmap)
        finally:
            gdi32.SelectObject(memory, old)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory)

    # **The screen shows what is IN FRONT.** For a window that is not the
    # foreground one, the screen at its rectangle is whatever covers it,
    # so its own drawing is asked first there.
    in_front = True
    if hwnd:
        try:
            root = user32.GetAncestor(ctypes.c_void_p(int(hwnd)), 2)
            in_front = int(root or 0) == int(user32.GetForegroundWindow()
                                             or 0)
        except Exception:                            # noqa: BLE001
            in_front = True
    bits = None
    if in_front:
        screen = user32.GetDC(None)
        try:
            bits = grab(screen, left, top)
        finally:
            user32.ReleaseDC(None, screen)
        if bits and not _flat(bits):
            with _LOCK:
                _state['captured'] = 'screen'
            return width, height, bits
    rect = window_rect(hwnd) if hwnd else None
    if rect is None:
        return None
    # PrintWindow paints the WHOLE window; the rectangle asked for is cut
    # out of it afterwards.
    w_left, w_top, w_right, w_bottom = rect
    whole_w, whole_h = w_right - w_left, w_bottom - w_top
    window_dc = user32.GetWindowDC(ctypes.c_void_p(int(hwnd)))
    if not window_dc:
        return None
    try:
        memory = gdi32.CreateCompatibleDC(window_dc)
        bitmap = gdi32.CreateCompatibleBitmap(window_dc, whole_w, whole_h)
        old = gdi32.SelectObject(memory, bitmap)
        try:
            if not user32.PrintWindow(ctypes.c_void_p(int(hwnd)), memory, 2):
                return None
            cut_dc = gdi32.CreateCompatibleDC(window_dc)
            cut = gdi32.CreateCompatibleBitmap(window_dc, width, height)
            cut_old = gdi32.SelectObject(cut_dc, cut)
            try:
                gdi32.BitBlt(cut_dc, 0, 0, width, height, memory,
                             left - w_left, top - w_top, 0x00CC0020)
                gdi32.SelectObject(cut_dc, cut_old)
                bits = read_bits(cut_dc, cut)
            finally:
                gdi32.SelectObject(cut_dc, cut_old)
                gdi32.DeleteObject(cut)
                gdi32.DeleteDC(cut_dc)
        finally:
            gdi32.SelectObject(memory, old)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory)
    finally:
        user32.ReleaseDC(ctypes.c_void_p(int(hwnd)), window_dc)
    if bits and not _flat(bits):
        with _LOCK:
            _state['captured'] = 'window'
        return width, height, bits
    return None


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #

def read_png(data, language=''):
    """Read an encoded PNG. ``(ok, lines)`` - a line is a list of words,
    each ``{'text', 'left', 'top', 'width', 'height'}`` in the PICTURE's
    pixels - or ``(False, why)``."""
    if not data:
        return False, 'there is no picture to read'
    handle, path = tempfile.mkstemp(suffix='.png', dir=_folder())
    started = time.time()
    try:
        with os.fdopen(handle, 'wb') as out:
            out.write(data)
        found = _ask_server(path, language)
        if found is None:
            arguments = ['-Path', path]
            if language:
                arguments += ['-Lang', str(language)]
            found = _run(arguments)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if not found.get('ok'):
        why = _text(found.get('text')) or 'Windows OCR read nothing'
        with _LOCK:
            _state['failed'] += 1
            _state['why'] = why
        return False, why
    lines = []
    for line in found.get('lines') or []:
        # ConvertTo-Json flattens a one-element array into the element.
        if isinstance(line, dict):
            line = [line]
        words = [word for word in line or [] if isinstance(word, dict)
                 and _text(word.get('text'))]
        if words:
            lines.append(words)
    with _LOCK:
        _state['reads'] += 1
        _state['ms'] = round((time.time() - started) * 1000.0, 1)
        _state['language'] = _text(found.get('language'))
    return True, lines


#: Windows' recogniser reads small print badly; NVDA's own wrapper
#: enlarges anything under a hundred pixels up to four times
#: (`UwpOcr.getResizeFactor`), and so does this - but never past the
#: engine's own limit of 10000 pixels a side, measured in NVDA.
SMALL = 100
MAX_SIDE = 10000


def _enlarge(width, height, bgra):
    """``(factor, width, height, bgra)`` - the picture enlarged by a
    whole factor (each pixel repeated) when it is small."""
    if min(width, height) >= SMALL:
        return 1, width, height, bgra
    factor = 4
    while factor > 1 and max(width, height) * factor > MAX_SIDE:
        factor -= 1
    if factor <= 1:
        return 1, width, height, bgra
    stride = width * 4
    rows = []
    for y in range(height):
        row = bgra[y * stride:(y + 1) * stride]
        wide = b''.join(row[x:x + 4] * factor for x in range(0, stride, 4))
        rows.extend([wide] * factor)
    return factor, width * factor, height * factor, b''.join(rows)


def read_rect(left, top, width, height, hwnd=0, language=''):
    """Read a rectangle of the screen. The answer Titan's doorway gives:
    ``{'ok', 'lines', 'text'}``, every word's rectangle in SCREEN
    coordinates."""
    shot = capture(int(left), int(top), int(width), int(height), hwnd=hwnd)
    if shot is None:
        return {'ok': False, 'lines': [],
                'text': 'that window could not be photographed'}
    shot_w, shot_h, bits = shot
    factor, shot_w, shot_h, bits = _enlarge(shot_w, shot_h, bits)
    ok, found = read_png(encode_png(shot_w, shot_h, bits), language)
    if not ok:
        return {'ok': False, 'lines': [], 'text': str(found)}
    lines = []
    for words in found:
        line = []
        for word in words:
            line.append({'text': _text(word.get('text')),
                         'left': int(left) + int(word.get('left') or 0)
                         // factor,
                         'top': int(top) + int(word.get('top') or 0)
                         // factor,
                         'width': int(word.get('width') or 0) // factor,
                         'height': int(word.get('height') or 0) // factor})
        if line:
            lines.append(line)
    with _LOCK:
        return {'ok': True, 'lines': lines, 'ms': _state['ms'],
                'language': _state['language']}


def read_window(hwnd=0, language=''):
    """Read a window (or, with none, the whole screen)."""
    rect = window_rect(hwnd) if hwnd else None
    if rect is None:
        if hwnd:
            return {'ok': False, 'lines': [],
                    'text': 'that window has no place on the screen'}
        if not _IS_WINDOWS:
            return {'ok': False, 'lines': [],
                    'text': 'Windows OCR exists only on Windows'}
        rect = _screen_rect()
    left, top, right, bottom = rect
    return read_rect(left, top, right - left, bottom - top, hwnd=hwnd,
                     language=language)


def report():
    with _LOCK:
        found = dict(_state)
        found['available'] = _available['ok']
    found['resident_starts'] = _server['started']
    return found


# --------------------------------------------------------------------------- #
# Answered for the shared modules, in the shape of Titan's doorway
# --------------------------------------------------------------------------- #

def call_windows(args):
    """``ocr.windows``: whether the recogniser answers, in which language."""
    ok, why = available(force=bool((args or {}).get('force')))
    found = report()
    found.update({'ok': bool(ok), 'text': why})
    return found


def call_read_windows(args):
    """``ocr.read_windows``: one window, or one rectangle of it."""
    args = args or {}
    language = _text(args.get('language'))
    if all(key in args for key in ('left', 'top', 'width', 'height')):
        return read_rect(args['left'], args['top'], args['width'],
                         args['height'], hwnd=int(args.get('hwnd') or 0),
                         language=language)
    return read_window(int(args.get('hwnd') or 0), language=language)
