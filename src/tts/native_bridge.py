"""Running a TTS engine's Windows bridge where there is no Windows.

Five of the bundled engines - DECtalk, Eloquence, SMP, Festival and Milena -
are Windows DLLs and programs wrapped in a small bridge ``.exe`` that Titan
drives over pipes (or, for Milena, runs once per utterance). Nothing in the
protocol is Windows; only the process is. So on Linux and macOS the same
executable is started under Wine, which runs it as it is: the DLL loads,
the PCM comes back over the same pipe, and the engine cannot tell.

Wine is looked for on the PATH, then in ``TITAN_WINE`` (the path to a
``wine`` binary, for a portable build), and an engine whose bridge cannot
be run here answers :func:`bridge_available` False - which is how it has
always answered when the ``.exe`` was missing.

Measured (Debian 11 in WSLg, Wine 11.18 portable): ``wineboot`` once, then
the DECtalk bridge answers READY and returns PCM for a SPEAK line.
"""
import os
import shutil
import sys

IS_WINDOWS = sys.platform == 'win32'

_wine = None
_looked = False


def wine_path():
    """The wine binary to use off Windows, or None."""
    global _wine, _looked
    if IS_WINDOWS:
        return None
    if _looked:
        return _wine
    _looked = True
    candidate = os.environ.get('TITAN_WINE', '').strip()
    if candidate and os.path.isfile(candidate):
        _wine = candidate
        return _wine
    for name in ('wine', 'wine64', 'wine-stable'):
        found = shutil.which(name)
        if found:
            _wine = found
            return _wine
    home = os.path.expanduser('~/wine')
    try:
        for entry in sorted(os.listdir(home), reverse=True):
            binary = os.path.join(home, entry, 'bin', 'wine')
            if os.path.isfile(binary):
                _wine = binary
                return _wine
    except OSError:
        pass
    return None


def bridge_available(exe_path):
    """Can this bridge executable be started on this machine?"""
    if not exe_path or not os.path.isfile(exe_path):
        return False
    if IS_WINDOWS:
        return True
    return wine_path() is not None


def bridge_command(exe_path, *args):
    """The argv that starts the bridge here: the exe itself, or wine + exe."""
    if IS_WINDOWS:
        return [exe_path, *args]
    wine = wine_path()
    if wine is None:
        raise FileNotFoundError('wine is not installed; the Windows bridge cannot run here')
    return [wine, exe_path, *args]


def popen_kwargs():
    """What every bridge Popen wants beside the command."""
    if IS_WINDOWS:
        return {'creationflags': getattr(__import__('subprocess'), 'CREATE_NO_WINDOW', 0)}
    env = dict(os.environ)
    env.setdefault('WINEDEBUG', '-all')
    env.setdefault('WINEPREFIX', os.path.join(
        os.environ.get('XDG_DATA_HOME', os.path.expanduser('~/.local/share')),
        'titan', 'wine'))
    return {'env': env}


def why_unavailable(exe_path):
    if not exe_path or not os.path.isfile(exe_path):
        return 'the bridge executable is missing'
    if not IS_WINDOWS and wine_path() is None:
        return 'wine is not installed (apt install wine, or set TITAN_WINE)'
    return ''


def host_path(path):
    """A path as the bridge sees it: itself on Windows, a Z: path under Wine.

    A Windows program given a Unix path such as /home/x/y.txt reads it as a
    relative path and finds nothing; Wine's default Z: drive is the Unix
    root, so the same file is Z:/home/x/y.txt to it, with backslashes.
    """
    if IS_WINDOWS or not path:
        return path
    absolute = os.path.abspath(path)
    return 'Z:' + absolute.replace('/', chr(92))
