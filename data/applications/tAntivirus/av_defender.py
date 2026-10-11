# -*- coding: utf-8 -*-
"""Microsoft Defender, as a second opinion from the same menu.

Defender is already on almost every Windows machine and has a command-line
scanner, ``MpCmdRun.exe``. It is asked with ``-DisableRemediation``, which
means Defender REPORTS and does not act: what happens to a threat is decided
in Titan Antivirus' own window - the same ask, quarantine or delete as a
ClamAV finding - so the two engines behave alike to the person using them.

``MpCmdRun`` scans one path per run and prints its threats as blocks of
``Threat : <name>`` followed by ``file : <path>`` resource lines; exit code
2 means it found something, 0 that it did not.
"""

import glob
import os
import re
import subprocess
import sys

import av_engine

_THREAT = re.compile(r'^\s*Threat\s*:\s*(.+?)\s*$', re.IGNORECASE)
_FILE = re.compile(r'^\s*(?:file|containerfile)\s*:\s*(.+?)\s*$',
                   re.IGNORECASE)


def locate():
    """The newest ``MpCmdRun.exe``, or ''.

    The platform folder under ProgramData is the one Defender updates
    itself into; the one under Program Files is the copy Windows shipped,
    which is older but always there.
    """
    if sys.platform != 'win32':
        return ''
    program_data = os.environ.get('ProgramData', r'C:\ProgramData')
    platforms = sorted(glob.glob(os.path.join(
        program_data, 'Microsoft', 'Windows Defender', 'Platform', '*',
        'MpCmdRun.exe')), reverse=True)
    if platforms:
        return platforms[0]
    shipped = os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'),
                           'Windows Defender', 'MpCmdRun.exe')
    return shipped if os.path.isfile(shipped) else ''


def available():
    return bool(locate())


def parse_output(text, scanned_path=''):
    """``[(path, threat)]`` out of one MpCmdRun run's output."""
    found = []
    threat = ''
    for line in (text or '').splitlines():
        match = _THREAT.match(line)
        if match:
            threat = match.group(1)
            continue
        match = _FILE.match(line)
        if match and threat:
            found.append((match.group(1), threat))
    if threat and not found:
        # A threat Defender did not attach a resource to is about the path
        # it was asked about.
        found.append((scanned_path, threat))
    return found


def scan(job, files, summary):
    """Scan for an `av_engine.ScanJob`: the paths it was given, one run
    each (a folder is one run, so progress is per path, not per file)."""
    program = locate()
    if not program:
        raise av_engine.EngineError('defender_missing')
    targets = job.paths or files
    total = len(targets)
    summary['files'] = len(files)
    job.on_status('scanning')
    for index, path in enumerate(targets, 1):
        if job.cancelled:
            break
        try:
            completed = subprocess.run(
                [program, '-Scan', '-ScanType', '3', '-File', path,
                 '-DisableRemediation'],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=6 * 3600, **av_engine._no_window())
        except (OSError, subprocess.TimeoutExpired):
            summary['errors'] += 1
            continue
        output = completed.stdout.decode('utf-8', 'replace')
        if completed.returncode == 2:
            for found_path, threat in parse_output(output, path):
                job._found(found_path, threat)
        elif completed.returncode not in (0, 2):
            summary['errors'] += 1
        job.on_progress(index, total, path)
