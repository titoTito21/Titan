# -*- coding: utf-8 -*-
"""Scan with antivirus: - the shell's half of Titan Antivirus.

What it adds, and where:

* the menu of a file, a folder or a drive in the file browser, the menu of
  the folder's background, and the menu of a desktop icon: a submenu
  "Scan with antivirus:" holding Titan Antivirus (ClamAV) and - on Windows,
  where it is there - Microsoft Defender;
* the browser's Tools menu: scan the folder being shown;
* the Start menu: a Titan Antivirus branch with Open and Quick scan;
* the shell starting: Titan Antivirus' background protection (the
  Downloads watcher and the scheduled scan), when the user switched either
  on in its settings.

**The scan itself never runs in this process.** This process is the shell
- the appbar and the shell hook make it what every other program's
broadcasts go through - and a scan is minutes of disk. So a request is
written into Titan Antivirus' requests folder and the application does the
work: a running one picks the file up within a second, and when none is
running Titan starts it with the request's path as its argument, through
`app_manager.open_application`, exactly as the Applications list would.

Nothing here is Windows-only except Defender: on Linux the same menus
offer Titan Antivirus over the system's ClamAV.
"""

import glob
import gettext
import importlib.util
import os
import sys

APP_SHORTNAME = 'tantivirus'

_cache = {}


# --------------------------------------------------------------------------
# The application this add-on hands its work to
# --------------------------------------------------------------------------
def _app_info():
    try:
        from src.titan_core import app_manager
        return app_manager.find_application_by_shortname(APP_SHORTNAME)
    except Exception:                                # noqa: BLE001
        return None


def _store():
    """Titan Antivirus' own `av_store`, loaded under a name of its own.

    Loaded from the application's folder rather than copied here, so the
    two can never disagree about where a request goes; under a private
    module name, so it is not the `av_store` of anything else in this
    process.
    """
    if 'store' in _cache:
        return _cache['store']
    info = _app_info()
    store = None
    if info:
        path = os.path.join(info['path'], 'av_store.py')
        if os.path.isfile(path):
            spec = importlib.util.spec_from_file_location(
                'titan_antivirus_shell_store', path)
            store = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(store)
    _cache['store'] = store
    return store


def _(text):
    """The application's own catalogue, so the menu and the window use the
    same words, in the user's language."""
    translator = _cache.get('gettext')
    if translator is None:
        translator = lambda value: value                    # noqa: E731
        info = _app_info()
        try:
            from src.titan_core import translation
            language = getattr(translation, 'language_code', 'en')
        except Exception:                            # noqa: BLE001
            language = 'en'
        if info:
            catalogue = gettext.translation(
                'messages', os.path.join(info['path'], 'languages'),
                languages=[language], fallback=True)
            translator = catalogue.gettext
        _cache['gettext'] = translator
    return translator(text)


def defender_available():
    if sys.platform != 'win32':
        return False
    program_data = os.environ.get('ProgramData', r'C:\ProgramData')
    if glob.glob(os.path.join(program_data, 'Microsoft', 'Windows Defender',
                              'Platform', '*', 'MpCmdRun.exe')):
        return True
    return os.path.isfile(os.path.join(
        os.environ.get('ProgramFiles', r'C:\Program Files'),
        'Windows Defender', 'MpCmdRun.exe'))


def send(api, kind, paths=(), engine='clamav', argument=None):
    """Hand Titan Antivirus one request, starting it when it is not running.

    Answers True when the request went somewhere; says why when it did not.
    """
    store = _store()
    info = _app_info()
    if store is None or info is None:
        api.speak(_("Titan Antivirus is not installed."))
        return False
    if kind == 'guard':
        request = None
    else:
        request = store.write_request(list(paths), engine=engine, kind=kind)
    if store.running_instance():
        if request is None:
            store.write_request([], kind='guard')
        return True
    try:
        from src.titan_core import app_manager
        app_manager.open_application(info, argument or request)
    except Exception as error:                       # noqa: BLE001
        api.log(f'could not start Titan Antivirus: {error}')
        api.speak(_("Titan Antivirus could not be started."))
        return False
    return True


def scan_entries(api, paths):
    """The "Scan with antivirus:" branch for ``paths``, or [] for none."""
    paths = [path for path in paths if path]
    if not paths:
        return []
    children = [{'id': 'clamav', 'label': 'Titan Antivirus',
                 'action': lambda: send(api, 'scan', paths, 'clamav')}]
    if defender_available():
        children.append({'id': 'defender', 'label': _("Microsoft Defender"),
                         'action': lambda: send(api, 'scan', paths,
                                                'defender')})
    return [{'id': 'scan', 'label': _("Scan with antivirus:"),
             'children': children}]


def _entry_path(entry):
    if not isinstance(entry, dict):
        return ''
    return str(entry.get('path') or entry.get('root') or '')


def _location_path(browser):
    location = str(getattr(browser, 'location', '') or '')
    return location if location and os.path.isdir(location) else ''


# --------------------------------------------------------------------------
# The shell
# --------------------------------------------------------------------------
def on_shell_start(api, shell):
    """Start the background protection, when the user wants it."""
    store = _store()
    if store is None:
        return
    settings = store.settings()
    if settings.get('watch_downloads') or settings.get('schedule_enabled'):
        send(api, 'guard', argument='--guard')


# --------------------------------------------------------------------------
# The file browser
# --------------------------------------------------------------------------
def explorer_context_items(api, browser, where, selection):
    if where == 'item':
        return scan_entries(api, [_entry_path(one) for one in selection or []])
    return scan_entries(api, [_location_path(browser)])


def explorer_menu_items(api, browser):
    location = _location_path(browser)
    if not location:
        return []
    return [{'id': 'scan_folder', 'label': _("Scan this folder with Titan "
                                             "Antivirus"),
             'action': lambda: send(api, 'scan', [location], 'clamav')}]


# --------------------------------------------------------------------------
# The desktop
# --------------------------------------------------------------------------
def desktop_menu_items(api, desktop, where, entry):
    if where != 'item':
        return []
    return scan_entries(api, [_entry_path(entry)])


# --------------------------------------------------------------------------
# The Start menu
# --------------------------------------------------------------------------
def start_menu_items(api, menu):
    if _app_info() is None:
        return []
    return [{'id': 'antivirus', 'label': 'Titan Antivirus', 'children': [
        {'id': 'open', 'label': _("Open Titan Antivirus"),
         'action': lambda: send(api, 'show')},
        {'id': 'quick', 'label': _("Quick scan"),
         'action': lambda: send(api, 'quick')},
    ]}]
