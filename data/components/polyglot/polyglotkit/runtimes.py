# -*- coding: utf-8 -*-
"""Which language a file is written in, and how to run it.

A runtime is DATA: the extensions it answers, the command that runs a file
(or the command that compiles it and the command that runs what came out),
and where to look for the interpreter. The built-in table covers what this
component can run on its own (Lua, carried here) and the common interpreters a
machine may have (Ruby - including the one the Elten bridge carries - Node.js,
PowerShell, .NET, Go, a C compiler). The user's own table,
``%APPDATA%/titosoft/Titan/polyglot/runtimes.json``, is read after it and wins
on an id it shares, so any language with a command line can be added without
touching Titan or this component. Settings -> Polyglot edits that table.

Placeholders in a command: ``{file}`` the source, ``{dir}`` its folder,
``{name}`` the file name without its extension, ``{out}`` what a compile step
wrote, ``{sdk}`` this component's ``sdk`` folder, ``{component}`` this
component's folder.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys

COMPONENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK_DIR = os.path.join(COMPONENT_DIR, 'sdk')
IS_WINDOWS = sys.platform == 'win32'
EXE = '.exe' if IS_WINDOWS else ''


def user_dir():
    """``.../titosoft/Titan/polyglot`` - the user's table, caches, app data."""
    if IS_WINDOWS:
        base = os.getenv('APPDATA') or os.path.expanduser('~')
    elif sys.platform == 'darwin':
        base = os.path.join(os.path.expanduser('~'), 'Library',
                            'Application Support')
    else:
        base = os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(base, 'titosoft', 'Titan', 'polyglot')


def user_table_path():
    return os.path.join(user_dir(), 'runtimes.json')


def _titan_data_dirs(*parts):
    """The bundled data folder and the user's overlay, in that order."""
    out = []
    root = os.path.dirname(os.path.dirname(COMPONENT_DIR))     # .../data
    out.append(os.path.join(root, *parts))
    if IS_WINDOWS:
        base = os.getenv('APPDATA') or ''
    else:
        base = os.path.join(os.path.expanduser('~'), '.config')
    if base:
        out.append(os.path.join(base, 'titosoft', 'Titan', 'data', *parts))
    return out


class Runtime(object):
    """One language. Everything about it is plain data."""

    def __init__(self, id, name, extensions, command=None, compile=None,
                 output='{name}' + EXE, find=None, env=None, inprocess=False,
                 sdk=True, note='', source='builtin'):
        self.id = str(id)
        self.name = str(name or id)
        self.extensions = [e.lower() if e.startswith('.') else '.' + e.lower()
                           for e in (extensions or [])]
        self.command = list(command or [])
        self.compile = list(compile or [])
        self.output = output
        #: Interpreter candidates: absolute paths (placeholders allowed) or
        #: names looked for on PATH. The first that exists is ``{exe}``.
        self.find = list(find or [])
        self.env = dict(env or {})
        self.inprocess = bool(inprocess)
        self.sdk = bool(sdk)
        self.note = note
        self.source = source
        self.disabled = False

    # ------------------------------------------------------------ finding
    def executable(self):
        """The interpreter or compiler found on this machine, or ''."""
        if self.inprocess:
            return sys.executable
        for candidate in self.find:
            candidate = expand(candidate, {})
            if os.path.isabs(candidate):
                if os.path.isfile(candidate):
                    return candidate
                continue
            found = shutil.which(candidate)
            if found:
                return found
        return ''

    def available(self):
        return self.inprocess or bool(self.executable()) or (
            not self.find and bool(self.command or self.compile))

    def why_not(self):
        """One sentence: what is missing for this language to run."""
        if self.available():
            return ''
        from .i18n import _
        names = ', '.join(os.path.basename(f) for f in self.find) or self.id
        return _("No interpreter or compiler for {} was found (looked for: "
                 "{}). Install it, or give its path in Settings -> "
                 "Polyglot.").format(self.name, names)

    # ----------------------------------------------------------- commands
    def values(self, path):
        folder, base = os.path.split(os.path.abspath(path))
        return {'file': os.path.abspath(path), 'dir': folder,
                'name': os.path.splitext(base)[0], 'sdk': SDK_DIR,
                'component': COMPONENT_DIR, 'exe': self.executable(),
                'python': sys.executable}

    def build_dir(self, path):
        digest = hashlib.sha1(os.path.abspath(path).lower().encode(
            'utf-8', 'replace')).hexdigest()[:16]
        return os.path.join(user_dir(), 'build', '%s-%s' % (self.id, digest))

    def prepare(self, path, log=None):
        """Compile when this runtime compiles. Answers the run command.

        The result is cached by the source's modification time, so a
        compiled game starts at once the second time. Raises RuntimeError
        with the compiler's own words when the compile fails.
        """
        values = self.values(path)
        if self.compile:
            out_dir = self.build_dir(path)
            os.makedirs(out_dir, exist_ok=True)
            out = os.path.join(out_dir, expand(self.output, values))
            values['out'] = out
            values['outdir'] = out_dir
            fresh = (os.path.isfile(out) and
                     os.path.getmtime(out) >= _newest_source(values['dir']))
            if not fresh:
                command = [expand(part, values) for part in self.compile]
                kwargs = {}
                if IS_WINDOWS:
                    kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
                done = subprocess.run(command, cwd=values['dir'],
                                      capture_output=True, timeout=600,
                                      env=self.environment(path), **kwargs)
                text = (done.stdout + done.stderr).decode('utf-8', 'replace')
                if log:
                    log('compile %s: %s' % (' '.join(command), text.strip()))
                if done.returncode != 0 or not os.path.isfile(out):
                    raise RuntimeError(
                        "Compiling %s failed:\n%s"
                        % (os.path.basename(path), text.strip()[-2000:]))
        command = self.command or ['{out}']
        return [expand(part, values) for part in command]

    def environment(self, path):
        """The guest's environment: Titan's, plus where the SDK is."""
        env = os.environ.copy()
        for key in ('RUBYOPT', 'PYTHONHOME', 'PYTHONPATH'):
            env.pop(key, None)
        values = self.values(path)
        env['TITAN_POLYGLOT'] = '1'
        env['TITAN_SDK'] = SDK_DIR
        if self.sdk:
            for key in ('RUBYLIB', 'NODE_PATH', 'PSModulePath', 'LUA_PATH'):
                current = env.get(key, '')
                env[key] = SDK_DIR + (os.pathsep + current if current else '')
        for key, value in self.env.items():
            env[key] = expand(str(value), values)
        return env

    def describe(self):
        state = 'ready' if self.available() else 'not found'
        where = self.executable() if not self.inprocess else 'built in'
        return {'id': self.id, 'name': self.name,
                'extensions': self.extensions, 'available': self.available(),
                'state': state, 'path': where, 'source': self.source,
                'compiles': bool(self.compile), 'note': self.note,
                'disabled': self.disabled}


def _newest_source(folder):
    newest = 0.0
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in
                   ('bin', 'obj', 'build', '__pycache__')]
        for name in files:
            try:
                newest = max(newest, os.path.getmtime(os.path.join(root, name)))
            except OSError:
                pass
    return newest


def expand(text, values):
    text = os.path.expandvars(str(text))
    for key, value in values.items():
        text = text.replace('{%s}' % key, str(value))
    return text


INTERPRETERS = os.path.join(COMPONENT_DIR, 'interpreters')


def _carried(*parts):
    """An interpreter inside this component's own ``interpreters`` folder."""
    return os.path.join(INTERPRETERS, *parts)


def _ruby_candidates():
    out = [_carried('ruby', 'bin', 'ruby' + EXE)]
    for folder in _titan_data_dirs('components', 'elten_bridge', 'ruby', 'bin'):
        out.append(os.path.join(folder, 'ruby' + EXE))
    out.append('ruby')
    return out


def _quickjs():
    if IS_WINDOWS:
        return _carried('quickjs', 'qjs.exe')
    if sys.platform.startswith('linux'):
        return _carried('quickjs', 'qjs-linux')
    return 'qjs'


def _csc():
    """The C# compiler of the .NET Framework 4 every Windows carries."""
    windows = os.environ.get('WINDIR', r'C:\Windows')
    return [os.path.join(windows, 'Microsoft.NET', folder, 'v4.0.30319',
                         'csc.exe')
            for folder in ('Framework64', 'Framework')]


def builtin():
    """The languages this component knows how to run out of the box.

    The first four need nothing installed: Lua is interpreted by this
    component, JavaScript runs on the QuickJS it carries, Ruby on the Ruby it
    carries, and C# is compiled by the compiler that is part of Windows
    (as PowerShell is). The rest are used when their tools are on the
    machine.
    """
    table = [
        Runtime('lua', 'Lua', ['.lua'], inprocess=True,
                note="Lua 5.1, interpreted by this component itself."),
        Runtime('javascript', 'JavaScript', ['.js', '.mjs'],
                command=['{exe}', '--std', '-I',
                         os.path.join('{sdk}', 'titan_qjs.js'), '{file}'],
                find=[_quickjs()], sdk=False,
                note="QuickJS-ng 0.17, carried by this component."),
        Runtime('ruby', 'Ruby', ['.rb'], command=['{exe}', '{file}'],
                find=_ruby_candidates(),
                note="Ruby 4.0, carried by this component."),
    ]
    if IS_WINDOWS:
        table.append(Runtime(
            'csharp', 'C#', ['.cs'],
            compile=['{exe}', '/nologo', '/codepage:65001', '/target:exe',
                     '/out:{out}', '/r:System.Web.Extensions.dll',
                     os.path.join('{sdk}', 'Titan.cs'),
                     os.path.join('{dir}', '*.cs')],
            command=['{out}'], find=_csc(),
            note="C# 5, compiled by the .NET Framework compiler that is "
                 "part of Windows; the SDK's Titan class is compiled in."))
        table.append(Runtime(
            'powershell', 'PowerShell', ['.ps1'],
            command=['{exe}', '-NoLogo', '-NoProfile', '-ExecutionPolicy',
                     'Bypass', '-File', '{file}'],
            find=['pwsh', 'powershell'],
            note="Part of Windows. Windows PowerShell 5.1 needs a script "
                 "saved as UTF-8 with a BOM."))
    else:
        table.append(Runtime('shell', 'Shell', ['.sh'],
                             command=['{exe}', '{file}'], find=['bash', 'sh']))
    table.extend([
        Runtime('nodejs', 'JavaScript (Node.js)', ['.cjs'],
                command=['{exe}', '{file}'], find=['node', 'nodejs']),
        Runtime('typescript', 'TypeScript (Deno)', ['.ts'],
                command=['{exe}', 'run', '--allow-all', '{file}'],
                find=['deno']),
        Runtime('go', 'Go', ['.go'], compile=['{exe}', 'build', '-o', '{out}',
                                             '{file}'],
                find=['go']),
        Runtime('c', 'C', ['.c'],
                compile=['{exe}', '{file}', '-O2', '-o', '{out}'],
                find=['gcc', 'clang', 'tcc']),
        Runtime('cpp', 'C++', ['.cpp', '.cc', '.cxx'],
                compile=['{exe}', '{file}', '-O2', '-o', '{out}'],
                find=['g++', 'clang++']),
        Runtime('rust', 'Rust', ['.rs'],
                compile=['{exe}', '-O', '{file}', '-o', '{out}'],
                find=['rustc']),
        Runtime('perl', 'Perl', ['.pl'], command=['{exe}', '{file}'],
                find=['perl']),
        Runtime('php', 'PHP', ['.php'], command=['{exe}', '{file}'],
                find=['php']),
    ])
    return table


#: The fields of an entry in the user's table, in the order they are shown.
FIELDS = ('id', 'name', 'extensions', 'find', 'command', 'compile', 'output',
          'env', 'sdk', 'note', 'disabled')


def read_user_entries(log=None):
    """The user's table as it is on the disk: a list of plain dicts.

    An entry whose ``id`` is a built-in language changes only the fields it
    names; any other entry is a language of the user's own.
    """
    path = user_table_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except Exception as error:
        if log:
            log('cannot read %s: %s' % (path, error))
        return []
    entries = data.get('runtimes', data) if isinstance(data, dict) else data
    return [dict(entry) for entry in (entries if isinstance(entries, list)
                                      else [])
            if isinstance(entry, dict) and entry.get('id')]


def write_user_entries(entries):
    """Write the user's table; anything else in the file is kept."""
    path = user_table_path()
    data = {}
    if os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}
    data['runtimes'] = [dict(entry) for entry in entries if entry.get('id')]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    os.replace(temporary, path)
    return path


def entry_of(runtime):
    """Everything about a runtime, as an entry of the user's table."""
    return {'id': runtime.id, 'name': runtime.name,
            'extensions': list(runtime.extensions), 'find': list(runtime.find),
            'command': list(runtime.command), 'compile': list(runtime.compile),
            'output': runtime.output, 'env': dict(runtime.env),
            'sdk': runtime.sdk, 'note': runtime.note,
            'disabled': runtime.disabled}


def difference(base, entry):
    """Only what ``entry`` changes about the built-in ``base``.

    Answers ``{'id': ...}`` and nothing else when it changes nothing - which
    is how putting a built-in language back the way it was is written.
    """
    full = entry_of(base)
    out = {'id': base.id}
    for key in FIELDS[1:]:
        if key not in entry:
            continue
        value = entry[key]
        if key == 'extensions':
            value = Runtime('x', 'x', value).extensions
        if value != full[key]:
            out[key] = value
    return out


def _runtime_from(entry, base=None):
    """A Runtime out of a user entry, over ``base`` when it is a built-in."""
    fields = entry_of(base) if base is not None else {}
    fields.update({k: v for k, v in entry.items() if k in FIELDS})
    runtime = Runtime(
        fields['id'], fields.get('name') or fields['id'],
        fields.get('extensions'), command=fields.get('command'),
        compile=fields.get('compile'),
        output=fields.get('output') or '{name}' + EXE,
        find=fields.get('find'), env=fields.get('env'),
        inprocess=bool(base is not None and base.inprocess
                       and not entry.get('command')),
        sdk=fields.get('sdk', True), note=fields.get('note', ''),
        source='changed' if base is not None else 'user')
    runtime.disabled = bool(fields.get('disabled'))
    return runtime


def runtimes_from(entries, log=None, include_disabled=False):
    """The built-in table with ``entries`` laid over it.

    Built-in languages first, in their own order, then the user's own; a
    switched-off language is left out unless ``include_disabled``.
    """
    table = {r.id: r for r in builtin()}
    for entry in entries:
        try:
            runtime = _runtime_from(entry, table.get(str(entry['id'])))
        except Exception as error:
            if log:
                log('runtime %r refused: %s' % (entry.get('id'), error))
            continue
        if runtime.source == 'changed' and difference(
                table[runtime.id], entry) == {'id': runtime.id}:
            runtime.source = 'builtin'
        table[runtime.id] = runtime
    out = list(table.values())
    if not include_disabled:
        out = [r for r in out if not r.disabled]
    return out


def all_runtimes(log=None, include_disabled=False):
    """Built-in first, the user's own over them by id."""
    return runtimes_from(read_user_entries(log), log, include_disabled)


def by_id(runtime_id):
    for runtime in all_runtimes():
        if runtime.id == runtime_id:
            return runtime
    return None


def for_file(path):
    """The runtime for this file by its extension, or None."""
    ext = os.path.splitext(str(path))[1].lower()
    if not ext or ext in ('.py', '.pyc', '.pyd', '.pyw', '.so', '.exe',
                          '.app', '.tce'):
        return None
    table = all_runtimes()
    # A language the user added wins an extension it shares with a built-in
    # one: adding it is how somebody says which interpreter a .js should get.
    table.sort(key=lambda r: 0 if r.source == 'user' else 1)
    for runtime in table:
        if ext in runtime.extensions:
            return runtime
    return None


def extensions():
    out = []
    for runtime in all_runtimes():
        out.extend(runtime.extensions)
    return out
