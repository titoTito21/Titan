# -*- coding: utf-8 -*-
"""Windows' own recogniser, reached from Titan rather than from NVDA.

Inside NVDA the screen is read by `contentRecog.uwpOcr`, NVDA's wrapper
round `Windows.Media.Ocr`. Titan Access is not NVDA and has no such
module, so every "read this window" key there - the screen review, the
local reading, the virtual window's picture fallback - answered "this NVDA
has no Windows OCR" on a machine that has a recogniser built in.

This is the same recogniser asked directly: the picture is written to a
PNG in the user's temp folder, and a short PowerShell script loads the
WinRT types (`Windows.Media.Ocr.OcrEngine`, which every Windows 10 and 11
has) and prints the lines with each word's rectangle as JSON. No package
to install, nothing sent anywhere. Measured: 0.7 s for a 900x500 picture,
most of it PowerShell starting. Python's own WinRT projection would be
faster and is not installed with Titan, which is why it is not used.

Windows only, and every answer is ``(ok, lines_or_reason)`` - a reader
asking this must be told WHY it could not read, never handed an exception.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time

_IS_WINDOWS = sys.platform.startswith('win')

#: Long enough for a cold PowerShell and a big window; a recogniser that
#: has not answered by then is not something a key press waits for.
TIMEOUT = 20.0

_LOCK = threading.RLock()
_state = {'reads': 0, 'failed': 0, 'why': '', 'ms': 0.0, 'language': ''}
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


def _script_path():
    """The script, written once per process into the temp folder.

    A file rather than ``-Command``: the script is longer than a command
    line comfortably carries, and quoting it for cmd.exe is a bug factory.
    """
    folder = os.path.join(tempfile.gettempdir(), 'titan_ocr')
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, 'windows_ocr.ps1')
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
        return {'ok': False, 'text': 'PowerShell could not be started: %s'
                % error}
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
    """Whether Windows' recogniser can be asked here. ``(ok, why)``.

    Remembered for ten minutes: the answer is a PowerShell start, and the
    reader asks it before every reading.
    """
    with _LOCK:
        fresh = time.time() - _available['checked'] < 600
        if fresh and not force and _available['ok'] is not None:
            return bool(_available['ok']), _available['why']
    found = _run(['-Probe'], timeout=TIMEOUT)
    ok = bool(found.get('ok'))
    why = '' if ok else str(found.get('text') or 'Windows OCR is not here')
    with _LOCK:
        _available.update({'checked': time.time(), 'ok': ok, 'why': why})
        if ok:
            _state['language'] = str(found.get('language') or '')
    return ok, why


def read_png(data, language=''):
    """Read an encoded PNG. ``(ok, lines)`` where a line is a list of words,
    each ``{'text', 'left', 'top', 'width', 'height'}`` in the PICTURE's
    pixels; or ``(False, why)``."""
    if not data:
        return False, 'there is no picture to read'
    folder = os.path.join(tempfile.gettempdir(), 'titan_ocr')
    os.makedirs(folder, exist_ok=True)
    handle, path = tempfile.mkstemp(suffix='.png', dir=folder)
    started = time.time()
    try:
        with os.fdopen(handle, 'wb') as out:
            out.write(data)
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
        why = str(found.get('text') or 'Windows OCR read nothing')
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
                 and str(word.get('text') or '').strip()]
        if words:
            lines.append(words)
    with _LOCK:
        _state['reads'] += 1
        _state['ms'] = round((time.time() - started) * 1000.0, 1)
        _state['language'] = str(found.get('language') or '')
    return True, lines


def report():
    with _LOCK:
        found = dict(_state)
        found['available'] = _available['ok']
    return found
