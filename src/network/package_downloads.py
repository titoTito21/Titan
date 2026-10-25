# -*- coding: utf-8 -*-
"""Where a package downloaded from the Titan-Net repository is saved.

Settings -> Titan-Net -> "Folder for downloaded packages"
(``titannet/packages_folder``).  Left empty it is the user's own Downloads
folder - the place every other program puts what it downloads, and so the
place somebody goes looking for it.  It used to be ``data/downloaded
packages`` RELATIVE TO THE WORKING DIRECTORY: inside the program's folder
when Titan was started from it, somewhere else entirely when it was not,
and never anywhere a user would think of looking.

One module, because three places save a package: the Titan-Net window, the
``titannet.repository_download`` action and the settings page that shows
the default.
"""

import os
import sys

SECTION = 'titannet'
KEY = 'packages_folder'


def user_downloads_folder():
    """The user's own Downloads folder, wherever they have moved it."""
    home = os.path.expanduser('~')
    if sys.platform == 'win32':
        try:
            import ctypes
            import uuid

            class GUID(ctypes.Structure):
                _fields_ = [('Data1', ctypes.c_ulong), ('Data2', ctypes.c_ushort),
                            ('Data3', ctypes.c_ushort), ('Data4', ctypes.c_ubyte * 8)]

            # FOLDERID_Downloads: the real one, even when the user moved it
            # to another drive - the name "Downloads" under the profile is
            # only where it starts.
            value = uuid.UUID('{374DE290-123F-4565-9164-39C4925E467B}')
            folder_id = GUID(value.time_low, value.time_mid, value.time_hi_version,
                             (ctypes.c_ubyte * 8)(*value.bytes[8:]))
            path = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(
                    ctypes.byref(folder_id), 0, None, ctypes.byref(path)) == 0:
                result = path.value
                ctypes.windll.ole32.CoTaskMemFree(path)
                if result and os.path.isdir(result):
                    return result
        except Exception:
            pass
    elif sys.platform != 'darwin':
        # Linux: the XDG folder, which is "Pobrane" on a Polish desktop and
        # not "Downloads" at all.
        try:
            import subprocess
            found = subprocess.run(['xdg-user-dir', 'DOWNLOAD'],
                                   capture_output=True, text=True,
                                   timeout=3).stdout.strip()
            if found and found != home and os.path.isdir(found):
                return found
        except Exception:
            pass
    return os.path.join(home, 'Downloads')


def chosen_folder():
    """What the user chose, or '' for the default."""
    try:
        from src.settings.settings import get_setting
        return str(get_setting(KEY, '', section=SECTION) or '').strip()
    except Exception:
        return ''


def packages_folder(create=True):
    """The folder a downloaded package goes into, made if it is missing.

    A chosen folder that cannot be made (a drive that is no longer there)
    falls back to the Downloads folder rather than failing the download -
    the package is what the user asked for, the folder only where it goes.
    """
    folder = chosen_folder()
    folder = os.path.expandvars(os.path.expanduser(folder)) if folder else ''
    candidates = [folder] if folder else []
    candidates.append(user_downloads_folder())
    for candidate in candidates:
        if not candidate:
            continue
        if not create:
            return candidate
        try:
            os.makedirs(candidate, exist_ok=True)
            return candidate
        except OSError as e:
            print(f"[Titan-Net] cannot use {candidate!r} for packages: {e}")
    return candidates[-1]


def _safe(text, extra=''):
    return "".join(c for c in str(text or '') if c.isalnum() or c in ('-', '_') + tuple(extra)).strip()


def package_filename(app):
    """``<author>_<name>_v<version>.TCEPACKAGE``, as the window always named it."""
    author = _safe(app.get('uploader_username', app.get('author_username', 'unknown'))) or 'unknown'
    name = _safe(app.get('name', '')) or 'package'
    version = _safe(app.get('version', '1.0') or '1.0', extra='.') or '1.0'
    return f"{author}_{name}_v{version}.TCEPACKAGE"


def save_path_for(app, folder=None):
    """Where ``app`` is saved, never over a file that is already there."""
    folder = folder or packages_folder()
    base, ext = os.path.splitext(package_filename(app))
    path = os.path.join(folder, base + ext)
    number = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({number}){ext}")
        number += 1
    return path
