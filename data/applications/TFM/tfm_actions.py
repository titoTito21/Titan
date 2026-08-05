"""TFM's Titan actions - the file manager, as something Titan can drive.

Split the way the work really divides:

- **Headless** file operations (list, find, copy, move, rename, delete, make a
  folder, read a size). These are what "copy those photos to the stick" needs,
  and doing them in a short-lived process means no window appears and nothing
  the user has open is disturbed.
- **Live** navigation and status, which only make sense against the open
  window: where the active panel is, what is selected, take me to this folder.

Deletions go to the Recycle Bin when Windows will take them, because an AI
misreading "clear that folder" must not be unrecoverable. Only when the shell
API is unavailable does it fall back to a real delete, and it says so.
"""

import os
import shutil
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
_MAX_LISTING = 300


def _editor():
    if _frame is None:
        raise RuntimeError("the file manager window is not open")
    return _frame


def _expand(path):
    return os.path.abspath(os.path.expandvars(os.path.expanduser(
        str(path or '').strip())))


def _human(size):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024 or unit == 'TB':
            return f"{size:.0f} {unit}" if unit == 'B' else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def _entry_line(root, name):
    full = os.path.join(root, name)
    try:
        if os.path.isdir(full):
            return f"[folder] {name}"
        return f"{name}  ({_human(os.path.getsize(full))})"
    except OSError:
        return name


# --------------------------------------------------------------------------- #
# Headless: the file system
# --------------------------------------------------------------------------- #
def list_folder(path=''):
    """List what is in a folder."""
    target = _expand(path) if path else os.path.expanduser('~')
    if not os.path.isdir(target):
        return fails(f"{target} is not a folder.")
    try:
        names = sorted(os.listdir(target))
    except OSError as e:
        return f"Could not read {target}: {e}"
    if not names:
        return f"{target} is empty."
    folders = [n for n in names if os.path.isdir(os.path.join(target, n))]
    files = [n for n in names if n not in folders]
    lines = [_entry_line(target, n) for n in folders + files][:_MAX_LISTING]
    more = ''
    if len(names) > _MAX_LISTING:
        more = f"\n... and {len(names) - _MAX_LISTING} more"
    return (f"{target} - {len(folders)} folders, {len(files)} files:\n"
            + "\n".join(lines) + more)


def find_files(query, path='', limit=60):
    """Find files and folders whose name contains some text."""
    words = [w for w in str(query or '').lower().split() if w]
    if not words:
        return "Say what to look for."
    root = _expand(path) if path else os.path.expanduser('~')
    if not os.path.isdir(root):
        return f"{root} is not a folder."
    limit = max(1, min(int(limit or 60), 200))
    hits = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for name in dirs + files:
            if all(word in name.lower() for word in words):
                hits.append(os.path.join(folder, name))
                if len(hits) >= limit:
                    break
        if len(hits) >= limit:
            break
    if not hits:
        return f"Nothing under {root} matches '{query}'."
    return (f"{len(hits)} matches for '{query}' under {root}:\n"
            + "\n".join(f"- {h}" for h in hits))


def folder_size(path):
    """How much space a folder takes, and how many files are in it."""
    root = _expand(path)
    if not os.path.isdir(root):
        return fails(f"{root} is not a folder.")
    total = count = 0
    for folder, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(folder, name))
                count += 1
            except OSError:
                continue
    return f"{root} holds {count} files, {_human(total)} in total."


def make_folder(path):
    """Create a folder."""
    target = _expand(path)
    if os.path.isdir(target):
        return f"{target} already exists."
    try:
        os.makedirs(target)
    except OSError as e:
        return f"Could not create {target}: {e}"
    return f"Created the folder {target}."


def _unique(destination):
    """A destination that does not overwrite anything: copying must never
    silently replace the user's file."""
    if not os.path.exists(destination):
        return destination
    stem, extension = os.path.splitext(destination)
    index = 2
    while os.path.exists(f"{stem} ({index}){extension}"):
        index += 1
    return f"{stem} ({index}){extension}"


def copy_path(source, destination):
    """Copy a file or a whole folder."""
    src, dst = _expand(source), _expand(destination)
    if not os.path.exists(src):
        return fails(f"There is nothing at {src}.")
    if not str(destination).strip():
        return needs('destination', f"Where should {os.path.basename(src)} "
                     f"be copied to?")
    if os.path.isdir(dst):
        dst = os.path.join(dst, os.path.basename(src))
    dst = _unique(dst)
    try:
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
    except OSError as e:
        return f"Could not copy {src}: {e}"
    return f"Copied {os.path.basename(src)} to {dst}."


def move_path(source, destination):
    """Move or rename a file or folder."""
    src, dst = _expand(source), _expand(destination)
    if not os.path.exists(src):
        return fails(f"There is nothing at {src}.")
    if not str(destination).strip():
        return needs('destination', f"Where should {os.path.basename(src)} "
                     f"be moved to?")
    if os.path.isdir(dst):
        dst = os.path.join(dst, os.path.basename(src))
    dst = _unique(dst)
    try:
        shutil.move(src, dst)
    except OSError as e:
        return f"Could not move {src}: {e}"
    return f"Moved {os.path.basename(src)} to {dst}."


def _to_recycle_bin(path):
    """Ask the Windows shell to bin it. Returns True when it did."""
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [('hwnd', wintypes.HWND),
                        ('wFunc', wintypes.UINT),
                        ('pFrom', wintypes.LPCWSTR),
                        ('pTo', wintypes.LPCWSTR),
                        ('fFlags', ctypes.c_uint16),
                        ('fAnyOperationsAborted', wintypes.BOOL),
                        ('hNameMappings', ctypes.c_void_p),
                        ('lpszProgressTitle', wintypes.LPCWSTR)]

        FO_DELETE = 3
        FOF_ALLOWUNDO = 0x0040
        FOF_NOCONFIRMATION = 0x0010
        FOF_SILENT = 0x0004
        operation = SHFILEOPSTRUCTW()
        operation.wFunc = FO_DELETE
        # The path list is double-null terminated.
        operation.pFrom = path + '\0\0'
        operation.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
        return result == 0 and not operation.fAnyOperationsAborted
    except Exception:
        return False


def delete_path(path):
    """Delete a file or folder, to the Recycle Bin where possible."""
    target = _expand(path)
    if not os.path.exists(target):
        return fails(f"There is nothing at {target}.")
    if _to_recycle_bin(target):
        return f"Moved {os.path.basename(target)} to the Recycle Bin."
    try:
        if os.path.isdir(target):
            shutil.rmtree(target)
        else:
            os.remove(target)
    except OSError as e:
        return f"Could not delete {target}: {e}"
    return (f"Deleted {os.path.basename(target)} permanently - the Recycle "
            f"Bin would not take it.")


def free_space(path=''):
    """How much room is left on a drive."""
    target = _expand(path) if path else os.path.expanduser('~')
    try:
        usage = shutil.disk_usage(target)
    except OSError as e:
        return f"Could not check {target}: {e}"
    return (f"{target}: {_human(usage.free)} free of {_human(usage.total)} "
            f"({usage.free * 100 // usage.total}%).")


# --------------------------------------------------------------------------- #
# Live: the open window
# --------------------------------------------------------------------------- #
def get_location():
    """Where the file manager is, and what is selected in it."""
    frame = _editor()
    where = frame._active_directory()
    selected = sorted(frame._active_selected_items() or [])
    if not selected:
        return f"The file manager is showing {where}, nothing selected."
    listed = ", ".join(selected[:10])
    more = f" and {len(selected) - 10} more" if len(selected) > 10 else ''
    return (f"The file manager is showing {where}. Selected: {listed}{more}.")


def go_to(path):
    """Take the file manager to a folder."""
    target = _expand(path)
    if not os.path.isdir(target):
        return f"{target} is not a folder."
    frame = _editor()
    control = frame.get_active_list_ctrl()
    attribute = 'current_path'
    selection = 'selected_items'
    if frame.settings.get_explorer_view_mode() == 'commander':
        side = frame.active_panel == 'left'
        attribute = 'left_path' if side else 'right_path'
        selection = 'left_selected_items' if side else 'right_selected_items'
    frame.is_drive_selection_mode = False
    setattr(frame, attribute, target)
    getattr(frame, selection).clear()
    frame.populate_file_list(ctrl=control, path=target)
    frame.update_window_title()
    frame.Raise()
    return f"The file manager is now showing {target}."


def refresh():
    """Re-read the folder the file manager is showing."""
    frame = _editor()
    frame.populate_file_list(ctrl=frame.get_active_list_ctrl())
    return "Refreshed the file list."


LIVE_HANDLERS = {
    'get_location': get_location,
    'go_to': go_to,
    'refresh': refresh,
    'list_folder': list_folder,
    'find_files': find_files,
    'folder_size': folder_size,
    'free_space': free_space,
    'make_folder': make_folder,
    'copy_path': copy_path,
    'move_path': move_path,
    'delete_path': delete_path,
}

HEADLESS_HANDLERS = {
    'list_folder': list_folder,
    'find_files': find_files,
    'folder_size': folder_size,
    'free_space': free_space,
    'make_folder': make_folder,
    'copy_path': copy_path,
    'move_path': move_path,
    'delete_path': delete_path,
}


def attach(frame):
    """Called by tfm.py once the window exists."""
    global _frame
    _frame = frame
    try:
        from src.titan_core.titan_actions import serve
    except Exception as e:
        print(f"[TFM] Titan actions unavailable: {e}")
        return False
    return serve(LIVE_HANDLERS, id='tfm', label='File Manager', kind='app')


if __name__ == '__main__':
    from src.titan_core.titan_actions import run_cli
    sys.exit(run_cli(HEADLESS_HANDLERS))
