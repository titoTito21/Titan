"""TInterpreter.TDL - the interpreter's site-packages as one compressed file.

    python src/titan_core/tdl.py build <site-packages> [...] -o TInterpreter.TDL
    python src/titan_core/tdl.py list TInterpreter.TDL
    python src/titan_core/tdl.py check TInterpreter.TDL

A compiled Titan runs its applications and games with its own
``_internal/python.exe``, and that interpreter needs every library an
application might import: 600 MB of site-packages on the build machine, as
tens of thousands of files, most of which a given user never touches. A TDL
("TCE dynamic library") is that folder in ONE file, compressed, and read on
demand:

- **One unit per distribution.** numpy, numpy.libs and numpy's dist-info
  are one unit; ``google/genai`` and ``google/protobuf`` are two, because a
  namespace package is shared by the distributions that fill it. A unit is
  stored as up to two LZMA streams - executables with the x86 branch filter
  in front (it is what makes a .pyd or a .dll compress well), everything
  else without it.
- **Nothing is unpacked until it is imported.** ``install()`` (run by a
  ``.pth`` file in the interpreter's own site-packages) puts the cache on
  ``sys.path`` and puts a finder in front of the path finder. The finder
  never answers an import itself: it looks the name up in the index,
  unpacks its unit into ``%LOCALAPPDATA%/titosoft/Titan/interpreter/
  <build>/`` if that has not happened yet, and lets Python's own path
  finder do the finding. Afterwards everything is a real file - ``__file__``,
  ``.pyd``, package data and ``importlib.metadata`` all behave as in a
  plain site-packages, which is the only way thousands of third-party
  packages can be expected to work.
- **sys.path still decides**, so an application's own copy of a library
  and the standard library win as they always did (see ``find_spec``).
- ``.pth`` files are honoured the way ``site`` honours them: their path
  lines become roots (pywin32's ``win32``, ``win32/lib``, ``pythonwin``),
  and their ``import`` lines run once the unit they belong to is unpacked,
  at every start after that.
- Two processes importing the same thing at once unpack it once: a lock
  file per unit, and a marker written only when the unit is complete. The
  files that make a package FINDABLE (``__init__``, a top-level module) are
  written last, so another process never imports half a package.

Standard library only, and importable on its own (it is copied into the
interpreter's ``Lib`` as ``titan_tdl.py``): it runs before anything of
Titan's is on the path.
"""

# Only what costs nothing at import: this module is imported by EVERY start
# of the applications' interpreter, from a zip. json, lzma, hashlib and
# threading are imported where they are used - when something is unpacked
# or built - which measured 30 ms off every start.
import _thread
import marshal
import os
import struct
import sys

MAGIC = b'TDL1'
VERSION = 1
FILE_NAME = 'TInterpreter.TDL'

#: An executable part is filtered for x86 branches before LZMA.
BINARY_SUFFIXES = ('.pyd', '.dll', '.exe', '.so', '.dylib')
MODULE_SUFFIXES = ('.py', '.pyc', '.pyd', '.so')

#: Distributions a build machine has for BUILDING, never for running.
#: pip stays: ``python.exe -m pip install`` into Lib/site-packages works
#: beside the TDL, and it is 3 MB packed.
DEFAULT_EXCLUDED_DISTS = (
    'setuptools', 'wheel', 'nuitka', 'pyinstaller',
    'pyinstaller-hooks-contrib', 'cython', 'altgraph', 'pefile',
    'pywin32-ctypes', 'ordered-set', 'zstandard', 'build', 'twine',
)

#: Paths (relative to site-packages, '/'-separated) that are shipped by a
#: package for another platform or for a feature nobody can use here.
#: ``prune_rules()`` adds the platform half.
_PRUNE_ALWAYS = (
    '__pycache__',
    'PyWin32.chm',
)

_LEN = struct.Struct('<Q')
def _dist_info_match(name):
    """'numpy-2.4.dist-info' -> 'numpy'; None for anything else."""
    import re
    match = re.match(r'^(.+?)-[^-]+\.(dist-info|egg-info)$', name, re.I)
    return match.group(1) if match else None


def normalize(name):
    """A distribution's name the way importlib.metadata compares it:
    runs of '-', '_' and '.' become one '_', lower case."""
    out = []
    for char in name.lower():
        if char in '-_.':
            if not out or out[-1] != '_':
                out.append('_')
        else:
            out.append(char)
    return ''.join(out)


def prune_rules(platform=None):
    """Relative paths that are left out of an interpreter for `platform`."""
    platform = platform or sys.platform
    rules = list(_PRUNE_ALWAYS)
    # speech_recognition's offline recogniser needs the pocketsphinx
    # package, which Titan does not ship; its 40 MB of English models are
    # unreachable without it.
    try:
        import importlib.util
        has_sphinx = importlib.util.find_spec('pocketsphinx') is not None
    except Exception:
        has_sphinx = False
    if not has_sphinx:
        rules.append('speech_recognition/pocketsphinx-data')
    if platform.startswith('win'):
        rules += ['speech_recognition/flac-linux-x86',
                  'speech_recognition/flac-linux-x86_64',
                  'speech_recognition/flac-mac',
                  'selenium/webdriver/common/linux',
                  'selenium/webdriver/common/macos']
    elif platform.startswith('linux'):
        rules += ['speech_recognition/flac-win32.exe',
                  'speech_recognition/flac-mac',
                  'selenium/webdriver/common/windows',
                  'selenium/webdriver/common/macos']
    elif platform == 'darwin':
        rules += ['speech_recognition/flac-win32.exe',
                  'speech_recognition/flac-linux-x86',
                  'speech_recognition/flac-linux-x86_64',
                  'selenium/webdriver/common/windows',
                  'selenium/webdriver/common/linux']
    return rules


def is_pruned(rel, rules):
    """True when `rel` (or a folder it is in) is one of `rules`."""
    parts = rel.split('/')
    if '__pycache__' in parts and '__pycache__' in rules:
        return True
    for rule in rules:
        if rel == rule or rel.startswith(rule + '/'):
            return True
    return False


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def _read_record(dist_dir):
    """The '/'-separated paths a dist-info's RECORD names, inside site-packages."""
    paths = []
    record = os.path.join(dist_dir, 'RECORD')
    installed = os.path.join(dist_dir, 'installed-files.txt')
    try:
        if os.path.isfile(record):
            with open(record, encoding='utf-8', errors='replace') as handle:
                for line in handle:
                    path = line.rsplit(',', 2)[0].strip().strip('"')
                    if path:
                        paths.append(path.replace('\\', '/'))
        elif os.path.isfile(installed):
            base = os.path.basename(dist_dir)
            with open(installed, encoding='utf-8', errors='replace') as handle:
                for line in handle:
                    line = line.strip().replace('\\', '/')
                    if line:
                        paths.append(os.path.normpath(base + '/' + line)
                                     .replace('\\', '/'))
    except OSError:
        pass
    return [p for p in paths if not p.startswith('../') and not p.startswith('/')]


def _dist_name(dist_dir):
    """The distribution's name, from METADATA, else from the folder name."""
    for name in ('METADATA', 'PKG-INFO'):
        path = os.path.join(dist_dir, name)
        try:
            with open(path, encoding='utf-8', errors='replace') as handle:
                for line in handle:
                    if line.lower().startswith('name:'):
                        return line.split(':', 1)[1].strip()
                    if not line.strip():
                        break
        except OSError:
            continue
    return _dist_info_match(os.path.basename(dist_dir)) or os.path.basename(dist_dir)


def _walk(root):
    """Every file under `root`, as '/'-separated paths relative to it."""
    found = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        rel_dir = os.path.relpath(folder, root).replace('\\', '/')
        for name in files:
            rel = name if rel_dir == '.' else rel_dir + '/' + name
            found.append(rel)
    return found


def _parse_pth(text):
    """(path lines, import lines) of a .pth file, as site.addpackage reads it."""
    paths, imports = [], []
    for line in text.splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        if line.startswith(('import ', 'import\t')):
            imports.append(line.rstrip())
        else:
            paths.append(line.strip().replace('\\', '/').rstrip('/'))
    return paths, imports


def collect(sources, excluded_dists=DEFAULT_EXCLUDED_DISTS, rules=None):
    """Work out what goes into a TDL: {'files': {rel: (abs, unit)}, ...}.

    `sources` are site-packages folders, the first winning a path that
    more than one holds.
    """
    rules = prune_rules() if rules is None else rules
    excluded = {normalize(d) for d in excluded_dists}
    files = {}          # rel -> absolute path
    owner = {}          # rel -> unit
    dists = {}          # normalized dist name -> {'unit', 'info'}
    pth_files = {}      # rel of the .pth -> text
    skipped_units = set()

    for source in sources:
        source = os.path.abspath(source)
        if not os.path.isdir(source):
            continue
        for rel in _walk(source):
            if rel in files or is_pruned(rel, rules):
                continue
            files[rel] = os.path.join(source, rel.replace('/', os.sep))
        for entry in sorted(os.listdir(source)):
            full = os.path.join(source, entry)
            if not (os.path.isdir(full) and _dist_info_match(entry)):
                continue
            name = _dist_name(full)
            unit = normalize(name)
            if unit in excluded:
                skipped_units.add(unit)
            dists.setdefault(unit, {'unit': unit, 'info': entry, 'name': name})
            for rel in _read_record(full) + [entry + '/' + r for r in
                                             os.listdir(full)]:
                rel = rel.replace('\\', '/')
                if rel in files and rel not in owner:
                    owner[rel] = unit

    # A file no RECORD names belongs with whatever owns its top folder, if
    # one distribution does; otherwise it is a unit of its own.
    top_owners = {}
    for rel, unit in owner.items():
        top_owners.setdefault(rel.split('/')[0], set()).add(unit)
    for rel in files:
        if rel in owner:
            continue
        top = rel.split('/')[0]
        units = top_owners.get(top, set())
        if len(units) == 1:
            owner[rel] = next(iter(units))
        else:
            stem = top.split('.')[0] if '/' not in rel else top
            owner[rel] = '~' + normalize(stem)

    for rel in list(files):
        if owner.get(rel) in skipped_units:
            del files[rel]
            owner.pop(rel, None)
    for unit in skipped_units:
        dists.pop(unit, None)

    for rel in files:
        if '/' not in rel and rel.endswith('.pth'):
            try:
                with open(files[rel], encoding='utf-8', errors='replace') as h:
                    pth_files[rel] = h.read()
            except OSError:
                pass

    return {'files': files, 'owner': owner, 'dists': dists,
            'pth': pth_files, 'skipped': sorted(skipped_units)}


def _module_names(rels, roots, init_dirs):
    """{dotted name: root} for the importable things these files provide.

    A folder holding an ``__init__`` is a package and ends the name; a
    folder without one is a namespace and the name goes one level deeper.
    """
    names = {}
    namespaces = {}
    for rel in rels:
        for root in roots:
            prefix = root + '/' if root else ''
            if root and not rel.startswith(prefix):
                continue
            inner = rel[len(prefix):]
            parts = inner.split('/')
            dotted = []
            for index, part in enumerate(parts):
                last = index == len(parts) - 1
                if last:
                    stem, ext = os.path.splitext(part)
                    stem = stem.split('.')[0]
                    if ext in MODULE_SUFFIXES and stem.isidentifier() and \
                            stem != '__init__':
                        names['.'.join(dotted + [stem])] = root
                    elif stem == '__init__' and dotted:
                        names['.'.join(dotted)] = root
                    break
                if not part.isidentifier():
                    break
                dotted.append(part)
                folder = prefix + '/'.join(parts[:index + 1])
                if folder in init_dirs:
                    names['.'.join(dotted)] = root
                    break
                namespaces.setdefault('.'.join(dotted), root)
            # a file in a root may also be under a deeper root; keep going
    return names, namespaces


def build(sources, output, excluded_dists=DEFAULT_EXCLUDED_DISTS, rules=None,
          preset=None, log=print):
    """Write a TDL of `sources` to `output`; returns its index."""
    import hashlib
    import json
    import lzma
    if preset is None:
        preset = 9 | lzma.PRESET_EXTREME
    plan = collect(sources, excluded_dists, rules)
    files, owner = plan['files'], plan['owner']

    roots = ['']
    unit_pth = {}
    for rel, text in sorted(plan['pth'].items()):
        if rel.endswith('-nspkg.pth'):
            continue        # namespace shims; the finder makes namespaces
        paths, imports = _parse_pth(text)
        unit = owner.get(rel)
        for path in paths:
            if path and path not in roots and not os.path.isabs(path):
                roots.append(path)
        if imports and unit:
            unit_pth.setdefault(unit, []).extend(imports)

    init_dirs = set()
    for rel in files:
        base = rel.rsplit('/', 1)
        if len(base) == 2 and os.path.splitext(base[1])[0].split('.')[0] == '__init__':
            init_dirs.add(base[0])

    by_unit = {}
    for rel in sorted(files):
        if rel.endswith('.pth') and '/' not in rel:
            continue
        by_unit.setdefault(owner[rel], []).append(rel)

    modules = {}
    namespaces = {}
    for unit, rels in by_unit.items():
        names, spaces = _module_names(rels, roots, init_dirs)
        for name, root in names.items():
            entry = modules.setdefault(name, {'root': root, 'units': []})
            if unit not in entry['units']:
                entry['units'].append(unit)
        for name, root in spaces.items():
            entry = namespaces.setdefault(name, {'root': root, 'units': []})
            if unit not in entry['units']:
                entry['units'].append(unit)
    for name in list(namespaces):
        if name in modules:
            del namespaces[name]
    # A namespace with something importable beneath it is just a folder;
    # one without (pywin32_system32 holds only DLLs) is unpacked whole.
    for name, entry in namespaces.items():
        entry['children'] = any(m.startswith(name + '.') for m in modules)

    def late(rel):
        # findable-last order: what makes a package importable is written
        # after everything inside it
        name = rel.rsplit('/', 1)[-1]
        stem = os.path.splitext(name)[0].split('.')[0]
        top_level = any(rel == (r + '/' if r else '') + name for r in roots)
        return (stem == '__init__' or top_level, rel)

    def pack_unit(unit):
        """(blobs, listing, sha1) of one unit - run on a worker thread;
        lzma lets go of the GIL while it compresses."""
        rels = sorted(by_unit[unit], key=late)
        digest = hashlib.sha1()
        blobs, listing = [], []
        for binary in (True, False):
            chosen = [r for r in rels
                      if r.lower().endswith(BINARY_SUFFIXES) == binary]
            if not chosen:
                continue
            total = sum(os.path.getsize(files[r]) for r in chosen)
            # a dictionary bigger than the data buys nothing and costs
            # ~11x its size in encoder memory per thread
            dict_size = 1 << 16
            while dict_size < min(total, 64 << 20):
                dict_size <<= 1
            filters = [{'id': lzma.FILTER_LZMA2, 'preset': preset,
                        'dict_size': dict_size}]
            if binary:
                filters.insert(0, {'id': lzma.FILTER_X86})
            comp = lzma.LZMACompressor(format=lzma.FORMAT_XZ,
                                       check=lzma.CHECK_CRC32, filters=filters)
            chunks = []
            usize = 0
            for rel in chosen:
                with open(files[rel], 'rb') as handle:
                    data = handle.read()
                digest.update(rel.encode('utf-8'))
                digest.update(data)
                chunks.append(comp.compress(data))
                listing.append([rel, len(blobs), usize, len(data)])
                usize += len(data)
            chunks.append(comp.flush())
            blobs.append((b''.join(chunks), usize))
        order = {rel: i for i, rel in enumerate(rels)}
        listing.sort(key=lambda item: order[item[0]])
        return blobs, listing, digest.digest()

    from concurrent.futures import ThreadPoolExecutor
    workers = max(1, min(4, (os.cpu_count() or 2) - 1))
    units = {}
    digest = hashlib.sha1()
    tmp = output + '.part'
    with open(tmp, 'wb') as out, ThreadPoolExecutor(workers) as pool:
        out.write(MAGIC + _LEN.pack(0))
        names = sorted(by_unit)
        for unit, (blobs, listing, unit_digest) in zip(names, pool.map(pack_unit, names)):
            digest.update(unit.encode('utf-8') + unit_digest)
            parts = []
            for blob, usize in blobs:
                parts.append([out.tell(), len(blob), usize])
                out.write(blob)
            # top folders that are not packages and hold DLLs directly
            # (pywin32_system32): the DLL search path needs them
            dll = sorted({rel.split('/')[0] for rel, *_ in listing
                          if rel.count('/') == 1
                          and rel.lower().endswith('.dll')
                          and rel.split('/')[0] not in init_dirs})
            units[unit] = {'parts': parts, 'files': listing,
                           'pth': unit_pth.get(unit, []), 'dll': dll}
            log(f"  {unit}: {len(listing)} files, "
                f"{sum(p[2] for p in parts) / 1048576:.1f} MB -> "
                f"{sum(p[1] for p in parts) / 1048576:.1f} MB")

        dists = {name: {'unit': d['unit'], 'info': d['info']}
                 for name, d in plan['dists'].items() if d['unit'] in units}
        index = {
            'version': VERSION,
            'build': digest.hexdigest()[:16],
            'python': '%d.%d' % sys.version_info[:2],
            'tag': sys.implementation.cache_tag,
            'platform': sys.platform,
            'roots': roots,
            'modules': modules,
            'namespaces': namespaces,
            'dists': dists,
            'units': {u: {'parts': v['parts'], 'pth': v['pth'],
                          'dll': v['dll'], 'count': len(v['files'])}
                      for u, v in units.items()},
        }
        lists = lzma.compress(json.dumps({u: v['files'] for u, v in units.items()},
                                         separators=(',', ':')).encode('utf-8'))
        index['lists'] = [out.tell(), len(lists)]
        out.write(lists)
        # marshal, not json: read at every interpreter start, and marshal
        # is built in (no import) and several times faster to load. A TDL
        # is tied to one Python anyway (the 'tag' check).
        head = marshal.dumps(index)
        at = out.tell()
        out.write(head)
        out.seek(len(MAGIC))
        out.write(_LEN.pack(at))
    os.replace(tmp, output)
    return index


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

class TDL:
    """An open TDL: its index, and unpacking a unit into a folder."""

    def __init__(self, path):
        self.path = path
        with open(path, 'rb') as handle:
            magic = handle.read(len(MAGIC))
            if magic != MAGIC:
                raise ValueError(f"{path} is not a TDL")
            at = _LEN.unpack(handle.read(_LEN.size))[0]
            handle.seek(at)
            self.index = marshal.loads(handle.read())
        self._lists = None
        self._lock = _thread.allocate_lock()

    def lists(self):
        with self._lock:
            if self._lists is None:
                import json
                import lzma
                at, size = self.index['lists']
                with open(self.path, 'rb') as handle:
                    handle.seek(at)
                    self._lists = json.loads(lzma.decompress(handle.read(size)))
            return self._lists

    def extract_unit(self, unit, target):
        """Write every file of `unit` under `target`; files that make a
        package findable come last (they are listed last)."""
        import lzma
        info = self.index['units'][unit]
        listing = self.lists()[unit]
        streams = {}
        with open(self.path, 'rb') as handle:
            for number, (start, size, _usize) in enumerate(info['parts']):
                handle.seek(start)
                streams[number] = handle.read(size)
        decoded = {n: lzma.decompress(blob) for n, blob in streams.items()}
        for rel, part, offset, size in listing:
            data = decoded[part][offset:offset + size]
            dest = os.path.join(target, rel.replace('/', os.sep))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if os.path.isfile(dest) and os.path.getsize(dest) == size:
                continue
            tmp = f'{dest}.{os.getpid()}.tmp'
            with open(tmp, 'wb') as out:
                out.write(data)
            try:
                os.replace(tmp, dest)
            except OSError:
                # a file of the same name another process has loaded
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        return len(listing)

    def check(self):
        """[(unit, error)] for every unit that does not decompress whole."""
        import lzma
        bad = []
        lists = self.lists()
        with open(self.path, 'rb') as handle:
            for unit, info in self.index['units'].items():
                try:
                    sizes = []
                    for start, size, usize in info['parts']:
                        handle.seek(start)
                        data = lzma.decompress(handle.read(size))
                        if len(data) != usize:
                            raise ValueError(f"{len(data)} bytes, not {usize}")
                        sizes.append(usize)
                    for rel, part, offset, size in lists[unit]:
                        if offset + size > sizes[part]:
                            raise ValueError(f"{rel} runs past its stream")
                except Exception as error:      # noqa: BLE001
                    bad.append((unit, str(error)))
        return bad


# ---------------------------------------------------------------------------
# The import side
# ---------------------------------------------------------------------------

def cache_root():
    base = (os.environ.get('LOCALAPPDATA')
            or os.environ.get('XDG_CACHE_HOME')
            or os.path.join(os.path.expanduser('~'), '.cache'))
    return os.path.join(base, 'titosoft', 'Titan', 'interpreter')


class _UnitLock:
    """A lock file shared by every process unpacking into one cache."""

    def __init__(self, path):
        self.path = path
        self.handle = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        import time
        self.handle = open(self.path, 'a+b')
        deadline = time.monotonic() + 300
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt
                    self.handle.seek(0)
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() > deadline:
                    return self         # unpack anyway rather than hang
                time.sleep(0.05)

    def __exit__(self, *exc):
        try:
            if os.name == 'nt':
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self.handle.close()


class TDLFinder:
    """The finder in front of the path finder that unpacks on demand."""

    def __init__(self, tdl, cache):
        self.tdl = tdl
        self.cache = cache
        self.site = os.path.join(cache, 'site-packages')
        self.marks = os.path.join(cache, '.units')
        self.index = tdl.index
        self._done = set()
        self._busy = _thread.RLock()
        try:
            for name in os.listdir(self.marks):
                if name.endswith('.ok'):
                    self._done.add(name[:-3])
        except OSError:
            pass
        self.unpacked = []          # units unpacked by this process

    def root_dir(self, root):
        return os.path.join(self.site, root.replace('/', os.sep)) if root \
            else self.site

    # -- units ---------------------------------------------------------
    def ensure(self, units):
        """Unpack every unit in `units` not unpacked yet; True if any was."""
        missing = [u for u in units if u not in self._done
                   and u in self.index['units']]
        if not missing:
            return False
        with self._busy:
            for unit in missing:
                if unit in self._done:
                    continue
                mark = os.path.join(self.marks, unit + '.ok')
                with _UnitLock(os.path.join(self.marks, unit + '.lock')):
                    if not os.path.isfile(mark):
                        self.tdl.extract_unit(unit, self.site)
                        with open(mark, 'w') as handle:
                            handle.write(self.index['build'])
                self._done.add(unit)
                self.unpacked.append(unit)
            import importlib
            importlib.invalidate_caches()
            for unit in missing:
                self._activate(unit)
        return True

    def _activate(self, unit):
        """What site would have done for this unit: its DLL folders on the
        search path, its .pth import lines run. Read from the index - this
        runs at every start for every unit already unpacked."""
        for top in self.index['units'].get(unit, {}).get('dll', []):
            folder = os.path.join(self.site, top.replace('/', os.sep))
            if not os.path.isdir(folder):
                continue
            try:
                if hasattr(os, 'add_dll_directory'):
                    os.add_dll_directory(folder)
            except OSError:
                pass
            os.environ['PATH'] = folder + os.pathsep + os.environ.get('PATH', '')
        self.run_pth(unit)

    def run_pth(self, unit):
        for line in self.index['units'].get(unit, {}).get('pth', []):
            try:
                exec(line, {'__name__': '__tdl_pth__'})  # noqa: S102 - as site does
            except Exception:
                pass

    # -- meta path finder ----------------------------------------------
    def _lookup(self, fullname):
        modules = self.index['modules']
        parts = fullname.split('.')
        for length in range(len(parts), 0, -1):
            name = '.'.join(parts[:length])
            if name in modules:
                return 'module', name, modules[name]
        space = self.index['namespaces'].get(fullname)
        if space:
            return 'namespace', fullname, space
        return None, None, None

    def find_spec(self, fullname, path=None, target=None):
        """Unpack what `fullname` needs, then let the path finder decide.

        This finder sits IN FRONT of the path finder and never answers
        itself. Answering last would be wrong in a compiled Titan:
        PyInstaller leaves ``_internal/wx/`` holding only wx's .pyd files,
        ``_internal`` is first on python.exe's path, and a folder with no
        ``__init__`` is a namespace package - so the path finder would
        "find" an empty wx and never ask anyone else. Unpacked first, the
        real package is a regular one, which wins over any namespace
        portion wherever it is on the path; and the order of sys.path still
        decides between two regular ones, so an application's own copy of a
        library still wins.
        """
        kind, _name, entry = self._lookup(fullname)
        if not kind:
            return None
        if kind == 'namespace' and entry.get('children'):
            folder = os.path.join(self.root_dir(entry['root']),
                                  *fullname.split('.'))
            if not os.path.isdir(folder):
                os.makedirs(folder, exist_ok=True)
                import importlib
                importlib.invalidate_caches()
            return None
        self.ensure(entry['units'])
        return None

    def find_distributions(self, context=None):
        """Unpack a distribution asked for by name; the path finder (after
        this one) then finds its dist-info like any other."""
        name = getattr(context, 'name', None)
        if name:
            dist = self.index['dists'].get(normalize(name))
            if dist:
                self.ensure([dist['unit']])
        return []

    def invalidate_caches(self):
        pass


_FINDER = None


def default_path():
    """TInterpreter.TDL beside this interpreter (``_internal/``)."""
    here = os.path.dirname(os.path.abspath(sys.executable))
    return os.path.join(here, FILE_NAME)


def install(path=None, cache=None):
    """Make the TDL's libraries importable. Safe to call twice; never raises."""
    global _FINDER
    if _FINDER is not None:
        return _FINDER
    try:
        path = path or os.environ.get('TITAN_TDL') or default_path()
        if not os.path.isfile(path):
            return None
        tdl = TDL(path)
        index = tdl.index
        if index.get('tag') and index['tag'] != sys.implementation.cache_tag:
            sys.stderr.write(f"[TDL] {path} was built for {index['tag']}, "
                             f"not {sys.implementation.cache_tag}; not used\n")
            return None
        cache = cache or os.path.join(cache_root(), index['build'])
        finder = TDLFinder(tdl, cache)
        os.makedirs(finder.site, exist_ok=True)
        for root in index['roots']:
            folder = finder.root_dir(root)
            if folder not in sys.path:
                sys.path.append(folder)
        from importlib.machinery import PathFinder
        at = next((i for i, f in enumerate(sys.meta_path) if f is PathFinder),
                  len(sys.meta_path))
        sys.meta_path.insert(at, finder)
        _FINDER = finder
        for unit in sorted(finder._done):
            info = index['units'].get(unit)
            if info and (info.get('dll') or info.get('pth')):
                finder._activate(unit)
        _prune_old_builds(index['build'])
        return finder
    except Exception as error:      # noqa: BLE001
        try:
            sys.stderr.write(f"[TDL] not installed: {error}\n")
        except Exception:
            pass
        return None


#: What nearly every TCE application imports; `warm` unpacks these ahead.
WARM_NAMES = ('wx', 'accessible_output3', 'pygame', 'requests', 'numpy')


def warm(names=WARM_NAMES):
    """Unpack what `names` need without importing any of it.

    The first application after an install or an interpreter update would
    otherwise wait - silently, which for somebody who cannot see the
    screen is a program that did not start - while wx is unpacked. Titan
    runs this on a low-priority process shortly after it starts.
    """
    finder = install()
    if finder is None:
        return False
    for name in names:
        kind, _name, entry = finder._lookup(name)
        if kind == 'module':
            finder.ensure(entry['units'])
    return True


def _prune_old_builds(current):
    """Throw away caches of other builds; a folder still in use is kept."""
    root = cache_root()
    try:
        names = [n for n in os.listdir(root) if n != current]
    except OSError:
        return
    if not names:
        return

    import threading

    def work():
        import shutil
        for name in names:
            shutil.rmtree(os.path.join(root, name), ignore_errors=True)
    threading.Thread(target=work, daemon=True, name='TDLPrune').start()


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def _main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Build or inspect a TDL.")
    sub = parser.add_subparsers(dest='command', required=True)
    make = sub.add_parser('build', help="pack site-packages folders")
    make.add_argument('sources', nargs='+')
    make.add_argument('-o', '--output', default=FILE_NAME)
    make.add_argument('--exclude-dist', action='append', default=[])
    make.add_argument('--keep-dist', action='append', default=[],
                      help="ship a distribution excluded by default")
    make.add_argument('--fast', action='store_true',
                      help="LZMA preset 6 instead of 9e (a test build)")
    for name in ('list', 'check'):
        one = sub.add_parser(name)
        one.add_argument('tdl')
    args = parser.parse_args(argv)
    if args.command == 'build':
        keep = {normalize(d) for d in args.keep_dist}
        excluded = [d for d in DEFAULT_EXCLUDED_DISTS if normalize(d) not in keep]
        excluded += args.exclude_dist
        import lzma
        preset = 6 if args.fast else 9 | lzma.PRESET_EXTREME
        index = build(args.sources, args.output, excluded, preset=preset)
        size = os.path.getsize(args.output) / 1048576
        print(f"Written {args.output}: {len(index['units'])} units, "
              f"{len(index['modules'])} importable names, {size:.1f} MB "
              f"(build {index['build']})")
        return 0
    tdl = TDL(args.tdl)
    if args.command == 'list':
        index = tdl.index
        print(f"build {index['build']} for {index['tag']} ({index['platform']})")
        print(f"roots: {index['roots']}")
        for unit, info in sorted(index['units'].items()):
            usize = sum(p[2] for p in info['parts']) / 1048576
            csize = sum(p[1] for p in info['parts']) / 1048576
            print(f"  {unit:40s} {info['count']:6d} files {usize:8.1f} MB "
                  f"-> {csize:7.1f} MB")
        return 0
    bad = tdl.check()
    for unit, error in bad:
        print(f"  {unit}: {error}")
    print("OK" if not bad else f"{len(bad)} broken unit(s)")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_main())
