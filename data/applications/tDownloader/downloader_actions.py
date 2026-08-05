"""tDownloader's Titan actions - fetching a file, with or without the window.

Downloading does not need a window. The download folder is in the manager's own
ini file, so a headless run reads it, fetches the file there and tells the user
where it went - which is what "download that and put it in my documents" should
cost.

The open manager is still preferred when there is one: the download then shows
up in its list with its own progress and completion announcement, exactly as if
the user had typed the address in. So ``mode`` is ``any``.

The fetch itself runs detached. A headless action returns as soon as it has
something to say, and a large file would otherwise be killed halfway by the
action timeout.
"""

import configparser
import os
import subprocess
import sys

# Titan tells us where it is (a packaged add-on runs from an extraction
# cache, so '../../..' from this file would point nowhere near Titan). The
# relative guess is the fallback for running this module by hand.
_TITAN_ROOT = os.environ.get('TITAN_ROOT') or os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if _TITAN_ROOT not in sys.path:
    sys.path.insert(0, _TITAN_ROOT)

from src.titan_core.titan_actions import fails, needs

_frame = None


def _settings_path():
    return os.path.join(os.getenv('APPDATA') or os.path.expanduser('~'),
                        'titosoft', 'titan', 'appsettings', 'tdm.ini')


def _read_folder():
    config = configparser.ConfigParser()
    try:
        config.read(_settings_path(), encoding='utf-8')
        folder = config.get('Settings', 'download_directory', fallback='')
    except Exception:
        folder = ''
    if not folder or not os.path.isdir(folder):
        folder = os.path.join(os.path.expanduser('~'), 'Downloads')
    return folder


def _write_folder(folder):
    config = configparser.ConfigParser()
    path = _settings_path()
    try:
        config.read(path, encoding='utf-8')
    except Exception:
        pass
    if not config.has_section('Settings'):
        config.add_section('Settings')
    config['Settings']['download_directory'] = folder
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        config.write(handle)


def _name_from_url(url):
    return os.path.basename(url.split('?')[0].split('#')[0]) or 'download'


def _fetch_detached(url, target):
    """Download in a process that outlives this one.

    Returning the moment the download *starts* is deliberate: a big file must
    not be cut off by the action timeout, and the user does not want to wait
    for it before being told anything.
    """
    executable = sys.executable
    windowless = os.path.join(os.path.dirname(executable), 'pythonw.exe')
    if os.path.isfile(windowless):
        executable = windowless
    code = ("import sys, urllib.request\n"
            "request = urllib.request.Request(sys.argv[1], headers={"
            "'User-Agent': 'Titan Download Manager'})\n"
            "with urllib.request.urlopen(request) as response, "
            "open(sys.argv[2], 'wb') as out:\n"
            "    while True:\n"
            "        chunk = response.read(65536)\n"
            "        if not chunk:\n"
            "            break\n"
            "        out.write(chunk)\n")
    flags = 0
    if sys.platform == 'win32':
        flags = 0x00000008 | subprocess.CREATE_NO_WINDOW    # DETACHED_PROCESS
    try:
        subprocess.Popen([executable, '-c', code, url, target],
                         creationflags=flags, close_fds=True)
        return True
    except Exception as e:
        print(f"[tDownloader] Could not start the download: {e}")
        return False


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #
def download(url, folder=''):
    """Download a file to the user's download folder."""
    address = str(url or '').strip()
    if not address:
        return needs('url', "What should be downloaded? Give the web address.")
    if not (address.startswith('http://') or address.startswith('https://')):
        return fails(f"'{address}' is not a full http:// or https:// address.")

    if _frame is not None:
        # The manager is open: hand it the download so it appears in its list
        # with its own progress and completion announcement.
        import downloader
        dialog = downloader.NewDownloadDialog(_frame, url_preset=address)
        dialog.OnOk(None)
        _frame.Raise()
        return (f"Started downloading {_name_from_url(address)} to "
                f"{_frame.download_directory}.")

    destination = str(folder or '').strip() or _read_folder()
    destination = os.path.abspath(os.path.expandvars(
        os.path.expanduser(destination)))
    try:
        os.makedirs(destination, exist_ok=True)
    except OSError as e:
        return fails(f"Could not use {destination}: {e}")
    target = os.path.join(destination, _name_from_url(address))
    stem, extension = os.path.splitext(target)
    counter = 2
    while os.path.exists(target):
        target = f"{stem} ({counter}){extension}"
        counter += 1
    if not _fetch_detached(address, target):
        return fails(f"Could not start downloading {address}.")
    return (f"Downloading {os.path.basename(target)} to {destination}. It "
            f"carries on in the background.")


def get_download_folder():
    """Say where downloads are saved."""
    if _frame is not None:
        return f"Downloads are saved to {_frame.download_directory}."
    return f"Downloads are saved to {_read_folder()}."


def set_download_folder(path):
    """Change where downloads are saved."""
    target = str(path or '').strip()
    if not target:
        return needs('path', "Which folder should downloads be saved in?")
    target = os.path.abspath(os.path.expandvars(os.path.expanduser(target)))
    try:
        os.makedirs(target, exist_ok=True)
    except OSError as e:
        return fails(f"Could not create {target}: {e}")
    if _frame is not None:
        _frame.save_download_directory(target)
    else:
        try:
            _write_folder(target)
        except OSError as e:
            return fails(f"Could not save the setting: {e}")
    return f"Downloads will now be saved to {target}."


def list_downloads():
    """List what has been downloaded."""
    if _frame is not None:
        downloads = _frame.downloads or {}
        if not downloads:
            return "The Download Manager has no downloads listed."
        return (f"{len(downloads)} downloads:\n"
                + "\n".join(f"- {name}" for name in sorted(downloads)))
    # The manager keeps its own list encrypted; without the window the honest
    # answer is what is actually in the download folder.
    folder = _read_folder()
    try:
        names = sorted(name for name in os.listdir(folder)
                       if os.path.isfile(os.path.join(folder, name)))
    except OSError as e:
        return fails(f"Could not read {folder}: {e}")
    if not names:
        return f"{folder} is empty."
    return (f"{len(names)} files in {folder}:\n"
            + "\n".join(f"- {name}" for name in names[:100]))


HANDLERS = {
    'download': download,
    'list_downloads': list_downloads,
    'get_download_folder': get_download_folder,
    'set_download_folder': set_download_folder,
}


def attach(frame):
    """Called by downloader.py once the window exists."""
    global _frame
    _frame = frame
    try:
        from src.titan_core.titan_actions import serve
    except Exception as e:
        print(f"[tDownloader] Titan actions unavailable: {e}")
        return False
    return serve(HANDLERS, id='tdownloader', label='Download Manager',
                 kind='app')


if __name__ == '__main__':
    from src.titan_core.titan_actions import run_cli
    sys.exit(run_cli(HANDLERS))
