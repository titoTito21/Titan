"""Remove files the build put into a compiled Titan twice.

    python src/scripts/dedupe_dist.py dist/Titan            # remove them
    python src/scripts/dedupe_dist.py dist/Titan --dry-run  # only say what

compiletorelease.py runs this as its last step. It can also be run on any
existing build.

Measured on the build of 2026-10-16 (867 MB): 177 groups of byte-identical
files, and the ones the BUILD made were three kinds of binary:

- **every stdlib extension and its DLLs twice**: PyInstaller puts `_ssl.pyd`,
  `libcrypto-3.dll`, `sqlite3.dll` ... into `_internal/`, and the
  post-processing then copied Python's whole `DLLs/` folder beside them into
  `_internal/DLLs/`. `python.exe`'s `_pth` lists `.` (that is `_internal/`)
  before `DLLs`, so the second copy was never even reachable;
- **a package's own DLLs once more at the top of `_internal/`**: pygame's
  `SDL2*.dll`, `freetype.dll`, `libogg-0.dll`, `libopus-0.dll`,
  `libwebp-7.dll` are in `_internal/pygame/`, where pygame loads them from
  (it adds its own folder to the DLL search path), and PyInstaller's
  dependency analysis put a copy at the top as well;
- **an add-on's private library at the top of `_internal/`**: tMedia's
  `libvlc.dll` / `libvlccore.dll`, which tMedia loads by full path from its
  own folder, and which are useless anywhere else (VLC finds its plugins
  next to `libvlc.dll`, and there are none in `_internal/`).

A copy is removed only when another copy has the same bytes AND the copy
that goes is provably not the one anything loads: a `DLLs/` copy shadowed by
the same name in `_internal/`, or a top-of-`_internal/` copy that no program
file outside the kept copy's folder imports (the PE import tables are read)
and that no Python module in the build names. Everything else identical in
content - a sound two themes share, the `translation.py` every application
carries - is a different file owned by a different add-on at a different
path, and stays.
"""

import argparse
import hashlib
import os
import re
import shutil
import struct
import sys
from collections import defaultdict

BINARY_SUFFIXES = ('.dll', '.pyd', '.so', '.dylib')

# A file under data/ whose only loader, in a compiled build, also looks in
# _internal/ - so an identical copy there makes the data/ one a double.
ALSO_FOUND_IN_INTERNAL = {
    'data/lib/libopus-0.dll': 'src/network/voice_codec.py',
}

# A DLL that Python code names as a whole string, but not to load the copy at
# the top of _internal/ - checked by hand, each one. Without this the name
# alone keeps a double, which is the safe answer for a name nobody checked.
NAMED_BUT_NOT_LOADED_FROM_INTERNAL = {
    # recognises an SDL program in another process; loads nothing
    'sdl2.dll': 'titan access/titan_access/portable/toolkit.py',
    # loads data/titantts engines/espeak/ by full path first, which ships
    'libespeak-ng.dll': 'src/titan_core/stereo_speech.py',
    # tMedia loads both by full path from its own folder
    'libvlc.dll': 'data/applications/tMedia',
    'libvlccore.dll': 'data/applications/tMedia',
}

# Development sources that are second copies of what ships elsewhere and
# that nothing in Titan loads. The C# reader Titan Access was ported from
# carries its own TTS/ (eSpeak's dictionaries, Festival, BeSTspeech - the
# same files as data/titantts engines/), Speech/, SFX/ and, on a developer's
# machine, bin/ and obj/: 266 tracked files and ~37 MB doubled in the build.
NOT_SHIPPED = {
    'data/components/titan access/ScreenReader':
        'the C# reader Titan Access was ported from; nothing loads it',
}

# marshal's short string types (lower-cased with the rest of the .pyc):
# 'z' / 'Z' short ascii, with or without FLAG_REF (0x80).
_PYC_SHORT_STR = b'[\x7a\xfa\xda]'


def _sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _rel(path, root):
    return os.path.relpath(path, root).replace(os.sep, '/')


def pe_imports(path):
    """The DLL names a PE file imports (normal and delay-load), lower case.

    None when the file is not a PE file this can read - the caller then has
    to assume the worst about it.
    """
    try:
        with open(path, 'rb') as fh:
            data = fh.read()
    except OSError:
        return None
    if data[:2] != b'MZ' or len(data) < 0x40:
        return None
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    if data[pe:pe + 4] != b'PE\0\0':
        return None
    n_sections = struct.unpack_from('<H', data, pe + 6)[0]
    opt_size = struct.unpack_from('<H', data, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from('<H', data, opt)[0]
    dirs = opt + (96 if magic == 0x10B else 112)
    sections = []
    sec = opt + opt_size
    for i in range(n_sections):
        s = sec + i * 40
        vsize, vaddr, rsize, raddr = struct.unpack_from('<IIII', data, s + 8)
        sections.append((vaddr, max(vsize, rsize), raddr))

    def offset(rva):
        for vaddr, size, raddr in sections:
            if vaddr <= rva < vaddr + size:
                return rva - vaddr + raddr
        return None

    def name_at(rva):
        off = offset(rva)
        if off is None:
            return None
        end = data.find(b'\0', off)
        return data[off:end].decode('ascii', 'replace').lower()

    names = set()
    # 1 = import table, 13 = delay-load import table
    for index, entry_size, name_field in ((1, 20, 12), (13, 32, 4)):
        rva, size = struct.unpack_from('<II', data, dirs + index * 8)
        off = offset(rva) if rva else None
        while off is not None and off + entry_size <= len(data):
            name_rva = struct.unpack_from('<I', data, off + name_field)[0]
            if not name_rva:
                break
            name = name_at(name_rva)
            if name:
                names.add(name)
            off += entry_size
    return names


def _python_text(root):
    """(folder, is_pyc, lower-case bytes) of every Python module in the build.

    This script's own compiled copy is left out: its documentation names the
    very DLLs it removes.
    """
    for folder in ('_internal/src', 'data'):
        base = os.path.join(root, folder)
        for d, _, files in os.walk(base):
            for f in files:
                if f.endswith(('.py', '.pyc')) and not f.startswith('dedupe_dist.'):
                    try:
                        with open(os.path.join(d, f), 'rb') as fh:
                            yield (os.path.normcase(d), f.endswith('.pyc'),
                                   fh.read().lower())
                    except OSError:
                        pass


def _addon_root(folder, root):
    """The add-on or package a folder belongs to: data/<kind>/<name>, or
    _internal/<package> (normcased)."""
    parts = os.path.relpath(folder, root).split(os.sep)
    if parts[0].lower() == 'data':
        keep = 3 if len(parts) >= 3 else len(parts)
        if len(parts) >= 2 and parts[1].lower() in ('lib', 'bin'):
            keep = 2  # data/lib is one shared folder, not an add-on
    else:
        keep = 2 if len(parts) >= 2 else len(parts)
    return os.path.normcase(os.path.join(root, *parts[:keep]))


def _names(name, text, pyc):
    """Does this module name the DLL as a whole string (with or without its
    extension) - which is what a bare-name load has to look like?"""
    for word in {name, os.path.splitext(name)[0]}:
        w = word.encode()
        if pyc:
            if re.search(_PYC_SHORT_STR + re.escape(bytes([len(w)]) + w), text):
                return True
        elif re.search(b'[\'"]' + re.escape(w) + b'[\'"]', text):
            return True
    return False


def find_removals(root, gone=()):
    """[(path to remove, path kept, reason)] for one compiled Titan.

    `gone` are paths already chosen for removal, treated as absent - a
    library imported only by a copy that is itself going (libvlccore.dll by
    the top-level libvlc.dll) is a doubled file too, one round later.
    """
    gone = {os.path.normcase(p) for p in gone}
    internal = os.path.join(root, '_internal')
    by_size = defaultdict(list)
    for d, _, files in os.walk(root):
        for f in files:
            if f.lower().endswith(BINARY_SUFFIXES):
                p = os.path.join(d, f)
                if os.path.normcase(p) in gone:
                    continue
                try:
                    by_size[os.path.getsize(p)].append(p)
                except OSError:
                    pass
    groups = defaultdict(list)
    for size, paths in by_size.items():
        if len(paths) > 1 and size:
            for p in paths:
                # Same bytes under another name is another file (whoever
                # loads opus.dll is not loading libopus-0.dll).
                groups[(size, _sha1(p), os.path.basename(p).lower())].append(p)
    groups = [sorted(g) for g in groups.values() if len(g) > 1]

    # Who imports what: dll name -> folders of the PE files importing it.
    importers = defaultdict(set)
    for d, _, files in os.walk(root):
        for f in files:
            if f.lower().endswith(('.dll', '.pyd', '.exe')):
                p = os.path.join(d, f)
                if os.path.normcase(p) in gone:
                    continue
                names = pe_imports(p)
                if names is None:
                    continue
                for name in names:
                    importers[name].add(os.path.normcase(d))
    named_in_python = None  # read once, only if needed

    removals = []
    top = os.path.normcase(internal)
    dlls = os.path.normcase(os.path.join(internal, 'DLLs'))
    for group in groups:
        name = os.path.basename(group[0]).lower()
        folders = {os.path.normcase(os.path.dirname(p)): p for p in group}
        if dlls in folders and top in folders:
            # python.exe's _pth puts '.' (_internal) before DLLs.
            removals.append((folders[dlls], folders[top],
                             'shadowed by the same file in _internal/'))
            del folders[dlls]
        if top in folders and len(folders) > 1:
            if pe_imports(folders[top]) is None:
                # Not a PE file (a Linux .so, a macOS .dylib): who imports it
                # cannot be read here, so neither copy is provably dead.
                continue
            kept = {f for f in folders if f != top}

            homes = {_addon_root(k, root) for k in kept}

            def beside_kept(folder):
                # Inside the add-on (or package) that holds the kept copy:
                # pygame/_sdl2/*.pyd import SDL2.dll out of pygame/, which
                # pygame adds to the DLL search path before any subpackage is
                # imported; Ruby's bin/ loads ruby_builtin_dlls/ the same way.
                return any(folder == h or folder.startswith(h + os.sep) for h in homes)

            if not any(not beside_kept(f) for f in importers.get(name, ())):
                if named_in_python is None:
                    named_in_python = list(_python_text(root))
                if (name in NAMED_BUT_NOT_LOADED_FROM_INTERNAL
                        or not any(_names(name, text, pyc)
                                   for folder, pyc, text in named_in_python
                                   if not beside_kept(folder))):
                    keep = folders[sorted(kept)[0]]
                    removals.append((folders[top], keep, 'loaded only from %s'
                                     % _rel(os.path.dirname(keep), root)))
                    continue
            for folder in sorted(kept):
                rel = _rel(folders[folder], root).lower()
                if rel in ALSO_FOUND_IN_INTERNAL:
                    removals.append((folders[folder], folders[top],
                                     '%s also looks in _internal/'
                                     % ALSO_FOUND_IN_INTERNAL[rel]))
            # The top copy stays (libopusfile-0.dll at the top imports
            # libopus-0.dll). A copy inside a package that nothing in that
            # package imports is then never the one loaded: a bare name is
            # found in _internal/ (the application's or the DLL directory)
            # long before PATH, which is where pygame puts its own folder.
            for folder in sorted(kept):
                if not folder.startswith(top + os.sep):
                    continue  # data/: an add-on loads its own by full path
                if any(f == folder or f.startswith(folder + os.sep)
                       for f in importers.get(name, ())):
                    continue
                removals.append((folders[folder], folders[top],
                                 'the copy in _internal/ is the one found'))
    return removals


def remove_not_shipped(root, dry_run=False, log=print):
    """Take NOT_SHIPPED out of a compiled tree. Returns the bytes freed."""
    freed = 0
    for rel, why in NOT_SHIPPED.items():
        path = os.path.join(root, *rel.split('/'))
        if not os.path.isdir(path):
            continue
        size = sum(os.path.getsize(os.path.join(d, f))
                   for d, _, fs in os.walk(path) for f in fs)
        freed += size
        log('  %s %s/ (%.1f MB: %s)' % ('Would leave out' if dry_run else 'Left out',
                                       rel, size / 1e6, why))
        if not dry_run:
            shutil.rmtree(path)
    return freed


def dedupe(root, dry_run=False, log=print):
    remove_not_shipped(root, dry_run=dry_run, log=log)
    removals = []
    while True:
        found = find_removals(root, gone=[r[0] for r in removals])
        if not found:
            break
        removals.extend(found)
    freed = 0
    for path, kept, why in removals:
        size = os.path.getsize(path)
        freed += size
        log('  %s %s (kept %s: %s)' % ('Would remove' if dry_run else 'Removed',
                                       _rel(path, root), _rel(kept, root), why))
        if not dry_run:
            os.remove(path)
    log('  %d doubled file(s), %.1f MB' % (len(removals), freed / 1e6))
    return removals


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('dist', help='the compiled Titan folder, e.g. dist/Titan')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not os.path.isdir(os.path.join(args.dist, '_internal')):
        sys.exit('%s has no _internal folder - is it a compiled Titan?' % args.dist)
    dedupe(args.dist, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
