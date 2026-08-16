# -*- coding: utf-8 -*-
"""
Projects: an add-on that takes longer than one sitting.

The creation kit was built around one round trip - describe it, generate it,
save it - which is right for a statusbar applet and wrong for anything
bigger. A component with four screens, a launcher, an application with its
own file format: those are built over hours, in several passes, with the
questions answered once and the plan kept. Close the dialog and all of it
was gone.

A **project** is the whole session on disk: which kind is being built, what
was asked for, every question the AI asked and every answer given, the plan,
the conversation so far, and the files as they stand. Reopen it and the next
"Generate" carries on from exactly where it stopped - the model still has
the conversation, so "now add a settings page" means what it says.

    %APPDATA%/titosoft/Titan/ai projects/<name>/
        project.json      what the session is and what was said
        files/            the add-on as it currently stands

The files are kept as real files rather than inside the JSON, so a project
can be opened in an editor, diffed, or copied into `data/` by hand - and so
that a half-finished add-on is never trapped in a format only this dialog
can read.
"""

import json
import os
import re
import shutil
import time

from src import platform_utils

PROJECT_DIR = 'ai projects'
MANIFEST = 'project.json'
FILES_DIR = 'files'

#: Bumped only if the shape below ever changes incompatibly; a project from
#: an older Titan is still opened, with whatever it has.
FORMAT = 1


def projects_root():
    """The folder projects live in, created if it is not there."""
    return platform_utils.ensure_user_data_subdir(PROJECT_DIR)


def safe_name(name):
    """A folder name from what the user typed."""
    name = re.sub(r'[^A-Za-z0-9 ._-]', '_', str(name or '')).strip().strip('.')
    return name or f"project_{int(time.time())}"


def project_path(name):
    """Where a project of this name would be created."""
    return os.path.join(projects_root(), safe_name(name))


def find_project(name):
    """The folder of an EXISTING project called `name`, or None.

    The name the user sees is the one in `project.json`, and the folder is
    `safe_name()` of whatever they typed - so the two are not always the same
    string, and a project can also be renamed, copied in by hand, or carried
    over from another machine. Looking only where the name would have put it
    is what makes a project that is plainly there report "could not be read",
    so the folders are asked as well: first the obvious one, then a folder of
    that name, then whatever project calls itself that.
    """
    direct = project_path(name)
    if os.path.isfile(os.path.join(direct, MANIFEST)):
        return direct
    wanted = str(name or '').strip().lower()
    if not wanted:
        return None
    root = projects_root()
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return None
    fallback = None
    for entry in entries:
        folder = os.path.join(root, entry)
        manifest = os.path.join(folder, MANIFEST)
        if not os.path.isfile(manifest):
            continue
        if entry.strip().lower() == wanted:
            return folder
        if fallback is None:
            data = _read_json(manifest)
            if str(data.get('name', '')).strip().lower() == wanted:
                fallback = folder
    return fallback


def exists(name):
    return find_project(name) is not None


def save(name, kind_id, description='', messages=(), files=None,
         questions=(), answers=None, plan='', options=None, raw=''):
    """Write (or overwrite) one project. Returns its folder.

    Everything is optional except the name and the kind: a project saved
    before anything has been generated is a description and a plan, which is
    worth keeping on its own.
    """
    folder = find_project(name) or project_path(name)
    os.makedirs(folder, exist_ok=True)
    files = dict(files or {})
    created = ''
    manifest_path = os.path.join(folder, MANIFEST)
    if os.path.isfile(manifest_path):
        created = str(_read_json(manifest_path).get('created', ''))

    data = {
        'format': FORMAT,
        'name': str(name),
        'kind': str(kind_id or ''),
        'description': str(description or ''),
        'plan': str(plan or ''),
        'raw': str(raw or ''),
        'messages': [message for message in (messages or ())
                     if isinstance(message, dict)],
        'questions': list(questions or ()),
        'answers': dict(answers or {}),
        'options': dict(options or {}),
        'files': sorted(files),
        'created': created or _now(),
        'updated': _now(),
    }
    _write_json(manifest_path, data)

    # The files, as files. Written fresh each time so a file the model
    # dropped in a later pass does not linger from an earlier one.
    tree = os.path.join(folder, FILES_DIR)
    shutil.rmtree(tree, ignore_errors=True)
    for relative, content in files.items():
        target = os.path.join(tree, relative.replace('/', os.sep))
        os.makedirs(os.path.dirname(target) or tree, exist_ok=True)
        with open(target, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(content)
    return folder


def load(name):
    """One project as a dict, with its files read back in, or None.

    Says on the console why it could not, because "that project could not be
    read" is not something the user can act on.
    """
    folder = find_project(name)
    if folder is None:
        print(f"[AI projects] no project called {name!r} under "
              f"{projects_root()}")
        return None
    manifest_path = os.path.join(folder, MANIFEST)
    data = _read_json(manifest_path)
    if not data:
        print(f"[AI projects] {manifest_path} is empty or unreadable")
        return None
    data.setdefault('name', name)
    data['path'] = folder
    data['files'] = _read_tree(os.path.join(folder, FILES_DIR))
    return data


def describe(name):
    """What the list needs: no files read, no conversation loaded."""
    folder = find_project(name)
    if folder is None:
        return None
    data = _read_json(os.path.join(folder, MANIFEST))
    return {
        'name': data.get('name', name),
        'kind': data.get('kind', ''),
        'description': data.get('description', ''),
        'files': len(data.get('files', []) or []),
        'turns': len(data.get('messages', []) or []),
        'created': data.get('created', ''),
        'updated': data.get('updated', ''),
        'path': folder,
    }


def list_projects():
    """Every project, most recently changed first."""
    root = projects_root()
    found = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return found
    for name in names:
        if not os.path.isdir(os.path.join(root, name)):
            continue
        described = describe(name)
        if described:
            found.append(described)
    found.sort(key=lambda entry: entry.get('updated', ''), reverse=True)
    return found


def delete(name):
    folder = find_project(name)
    if not folder or not os.path.isdir(folder):
        return False
    shutil.rmtree(folder, ignore_errors=True)
    return not os.path.isdir(folder)


def rename(name, new_name):
    source = find_project(name)
    target = project_path(new_name)
    if not source or not os.path.isdir(source) or os.path.exists(target):
        return False
    os.rename(source, target)
    manifest_path = os.path.join(target, MANIFEST)
    data = _read_json(manifest_path)
    if data:
        data['name'] = str(new_name)
        data['updated'] = _now()
        _write_json(manifest_path, data)
    return True


def suggest_name(kind_label, description):
    """A name for a project nobody has named yet: the first few words."""
    words = re.findall(r"[A-Za-z0-9]+", str(description or ''))[:4]
    if words:
        return safe_name(' '.join(words))
    return safe_name(f"{kind_label} {time.strftime('%Y-%m-%d %H-%M')}")


# --------------------------------------------------------------------------
def _now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _read_json(path):
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as error:
        print(f"[AI projects] could not read {path}: {error}")
        return {}


def _write_json(path, data):
    try:
        with open(path, 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        return True
    except OSError as error:
        print(f"[AI projects] could not write {path}: {error}")
        return False


def _read_tree(root):
    """{relative path: content} for everything under `root`."""
    files = {}
    if not os.path.isdir(root):
        return files
    for dirpath, _dirs, names in os.walk(root):
        for name in sorted(names):
            full = os.path.join(dirpath, name)
            relative = os.path.relpath(full, root).replace(os.sep, '/')
            try:
                with open(full, encoding='utf-8', errors='replace') as handle:
                    files[relative] = handle.read()
            except OSError:
                continue
    return files
