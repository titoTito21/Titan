"""Make the compiled Titan's interpreter small: the standard library in one
zip, site-packages in one TInterpreter.TDL, and nothing shipped that cannot
run.

    python src/scripts/build_interpreter.py dist/Titan              # all of it
    python src/scripts/build_interpreter.py dist/Titan --slim-only  # just prune
    python src/scripts/build_interpreter.py dist/Titan --dry-run

What it does to ``<dist>/_internal``:

1. **Prunes** what is there for another platform or an unreachable feature
   (and ``data/bin/ffprobe.exe``, see `DIST_PRUNE`)
   (`tdl.prune_rules`): speech_recognition's Linux and macOS flac binaries
   and its pocketsphinx models (Titan ships no pocketsphinx), selenium's
   Linux and macOS selenium-manager. Applied to the frozen tree and to the
   TDL alike.
2. **site-packages -> TInterpreter.TDL** (`src/titan_core/tdl.py`): one
   compressed file, unpacked per distribution the first time an application
   imports from it. ``Lib/site-packages`` is left holding one ``.pth`` that
   installs the finder, and ``Lib/titan_tdl.py`` is the finder itself.
3. **The standard library -> python3XX.zip**, compiled, the way Python's own
   embeddable distribution ships it, listed first in ``python3XX._pth``.
   ``idlelib``, ``turtledemo``, ``ensurepip`` and ``venv`` are left out:
   they need files on disk and nobody runs them inside Titan.

Every step is idempotent and leaves a working interpreter if it stops half
way: the zip is written before the folders it replaces are removed, and the
TDL is written before the site-packages folder is emptied.
"""

import argparse
import os
import py_compile
import shutil
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'titan_core'))
import tdl  # noqa: E402

#: Standard-library entries that are not put in the zip, nor kept.
STDLIB_DROPPED = ('idlelib', 'turtledemo', 'ensurepip', 'venv', 'test',
                  'tests', '__pycache__', 'site-packages', '__phello__')

PTH_NAME = 'titan_tdl.pth'
PTH_LINE = 'import titan_tdl; titan_tdl.install()\n'


def _size(path):
    total = 0
    if os.path.isfile(path):
        return os.path.getsize(path)
    for folder, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(folder, name))
            except OSError:
                pass
    return total


def _mb(n):
    return f"{n / 1048576:.1f} MB"


#: Paths of the compiled folder (not of _internal) nothing in Titan needs.
#: ffprobe was only ever asked for a duration, which `ffmpeg -i` says too
#: (`elten_player._ffmpeg_duration`) - 99 MB for one number.
DIST_PRUNE = ('data/bin/ffprobe.exe',)


def slim(internal, dry_run=False, log=print):
    """Remove `tdl.prune_rules()` paths from a frozen ``_internal``, and
    `DIST_PRUNE` from the folder around it."""
    freed = 0
    dist = os.path.dirname(os.path.abspath(internal))
    targets = [(internal, rule) for rule in tdl.prune_rules()
               if rule != '__pycache__']
    targets += [(dist, rule) for rule in DIST_PRUNE]
    for base, rule in targets:
        path = os.path.join(base, rule.replace('/', os.sep))
        if not os.path.exists(path):
            continue
        size = _size(path)
        freed += size
        log(f"  {'would remove' if dry_run else 'removed'}: {rule} ({_mb(size)})")
        if not dry_run:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
    log(f"  pruned {_mb(freed)}")
    return freed


def python_tag():
    return f"{sys.version_info.major}{sys.version_info.minor}"


def build_stdlib_zip(lib_dir, zip_path, log=print):
    """Compile ``lib_dir`` (without site-packages) into ``zip_path``.

    Modules are stored as ``name.pyc`` beside where ``name.py`` was - the
    sourceless layout zipimport loads, and the one python.org's embeddable
    package uses. Data files go in as they are.
    """
    tmp = zip_path + '.part'
    count = 0
    work = tempfile.mkdtemp(prefix='titan_stdlib_')
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED,
                             compresslevel=9) as archive:
            for folder, dirs, files in os.walk(lib_dir):
                rel_dir = os.path.relpath(folder, lib_dir)
                if rel_dir == '.':
                    dirs[:] = [d for d in dirs if d not in STDLIB_DROPPED]
                else:
                    dirs[:] = [d for d in dirs
                               if d not in ('__pycache__', 'test', 'tests')]
                for name in files:
                    src = os.path.join(folder, name)
                    rel = os.path.normpath(os.path.join(rel_dir, name)).replace('\\', '/')
                    if name.endswith('.pyc'):
                        continue
                    if rel == 'titan_tdl.py':
                        # stays a real file in Lib/: the zip is first on the
                        # path, and a copy in it would shadow every newer one
                        continue
                    if name.endswith('.py'):
                        cfile = os.path.join(work, 'm.pyc')
                        try:
                            py_compile.compile(
                                src, cfile=cfile, dfile=rel, doraise=True,
                                invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
                        except py_compile.PyCompileError as error:
                            log(f"  not compiled (kept as source): {rel}: {error.msg}")
                            archive.write(src, rel)
                            continue
                        archive.write(cfile, rel[:-3] + '.pyc')
                    else:
                        archive.write(src, rel)
                    count += 1
        os.replace(tmp, zip_path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return count


def write_pth(internal, zip_name):
    """python3XX._pth: the zip first, then the folders, then site."""
    pth = os.path.join(internal, f"python{python_tag()}._pth")
    lines = ["# Python path configuration for TCE Launcher",
             "# Paths are relative to the directory containing python.exe"]
    if zip_name:
        lines.append(zip_name)
    lines += ['.', 'Lib', 'Lib/site-packages', 'DLLs', '',
              '# Import site to enable .pth file processing in site-packages',
              '# (titan_tdl.pth installs the TInterpreter.TDL finder)',
              'import site', '']
    with open(pth, 'w', encoding='utf-8') as handle:
        handle.write('\n'.join(lines))
    return pth


def install_tdl_loader(internal):
    """titan_tdl.py into Lib/, titan_tdl.pth into Lib/site-packages/."""
    lib = os.path.join(internal, 'Lib')
    site_packages = os.path.join(lib, 'site-packages')
    os.makedirs(site_packages, exist_ok=True)
    shutil.copy2(os.path.join(ROOT, 'src', 'titan_core', 'tdl.py'),
                 os.path.join(lib, 'titan_tdl.py'))
    with open(os.path.join(site_packages, PTH_NAME), 'w', encoding='utf-8') as h:
        h.write(PTH_LINE)


def build(dist, sources=None, stdlib_zip=True, fast=False, dry_run=False,
          log=print):
    """Do all three steps to ``<dist>/_internal``; returns a size report."""
    internal = os.path.join(dist, '_internal')
    if not os.path.isdir(internal):
        raise SystemExit(f"{internal} does not exist")
    report = {'before': _size(internal)}

    log("Pruning what cannot run here...")
    slim(internal, dry_run=dry_run, log=log)
    if dry_run:
        return report

    lib = os.path.join(internal, 'Lib')
    site_packages = os.path.join(lib, 'site-packages')

    # 2. site-packages -> TDL
    if sources is None:
        sources = []
        if os.path.isdir(site_packages):
            entries = [e for e in os.listdir(site_packages) if e != PTH_NAME]
            if entries:
                sources = [site_packages]
    if sources:
        out = os.path.join(internal, tdl.FILE_NAME)
        log(f"Packing site-packages into {tdl.FILE_NAME} "
            f"(from {', '.join(sources)})...")
        tdl_log = (lambda *_a, **_k: None) if not fast else log
        import lzma
        preset = 6 if fast else 9 | lzma.PRESET_EXTREME
        index = tdl.build(sources, out, preset=preset, log=tdl_log)
        log(f"  {len(index['units'])} units, {len(index['modules'])} names, "
            f"{_mb(os.path.getsize(out))}")
        bad = tdl.TDL(out).check()
        if bad:
            raise SystemExit(f"The TDL just written is broken: {bad[:3]}")
        if os.path.isdir(site_packages):
            for entry in os.listdir(site_packages):
                if entry == PTH_NAME:
                    continue
                path = os.path.join(site_packages, entry)
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    os.remove(path)
    install_tdl_loader(internal)

    # 3. stdlib -> zip
    zip_name = None
    existing_zip = os.path.join(internal, f"python{python_tag()}.zip")
    if stdlib_zip and not os.path.isfile(os.path.join(lib, 'os.py')) \
            and os.path.isfile(existing_zip):
        # already done by an earlier run: Lib holds only the loader now,
        # and zipping THAT would replace the standard library with nothing
        zip_name = os.path.basename(existing_zip)
        log(f"The standard library is already in {zip_name}.")
    elif stdlib_zip and os.path.isfile(os.path.join(lib, 'os.py')):
        zip_name = f"python{python_tag()}.zip"
        zip_path = os.path.join(internal, zip_name)
        log(f"Compiling the standard library into {zip_name}...")
        count = build_stdlib_zip(lib, zip_path, log=log)
        log(f"  {count} files, {_mb(os.path.getsize(zip_path))}")
        for entry in os.listdir(lib):
            if entry == 'site-packages':
                continue
            path = os.path.join(lib, entry)
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
        # the loader stays a real file: the .pth imports it before anything
        install_tdl_loader(internal)
    if sys.platform.startswith('win'):
        write_pth(internal, zip_name)

    report['after'] = _size(internal)
    log(f"_internal: {_mb(report['before'])} -> {_mb(report['after'])}")
    return report


def verify(dist, modules=('json', 'ssl', 'sqlite3', 'ctypes', 'asyncio'),
           third_party=(), log=print):
    """Run the built python.exe and import `modules`; True when it worked."""
    import subprocess
    internal = os.path.join(dist, '_internal')
    exe = os.path.join(internal, 'python.exe' if os.name == 'nt' else 'python3')
    if not os.path.isfile(exe):
        log(f"  no interpreter at {exe}")
        return False
    names = list(modules) + list(third_party)
    code = ("import sys, importlib\n"
            f"for n in {names!r}:\n"
            "    importlib.import_module(n)\n"
            "print('OK', sys.version.split()[0], len(sys.modules))\n")
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    result = subprocess.run([exe, '-c', code], capture_output=True, text=True,
                            env=env, timeout=600)
    log((result.stdout + result.stderr).strip())
    return result.returncode == 0 and 'OK' in result.stdout


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('dist', nargs='?', default=os.path.join(ROOT, 'dist', 'Titan'))
    parser.add_argument('--source', action='append', default=None,
                        help="a site-packages folder to pack (default: the "
                             "one already copied into _internal/Lib)")
    parser.add_argument('--no-stdlib-zip', action='store_true')
    parser.add_argument('--slim-only', action='store_true')
    parser.add_argument('--fast', action='store_true',
                        help="LZMA preset 6 (a quick test build)")
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--verify', nargs='*', metavar='MODULE',
                        help="afterwards, import these with the built python")
    args = parser.parse_args(argv)
    if args.slim_only:
        slim(os.path.join(args.dist, '_internal'), dry_run=args.dry_run)
        return 0
    build(args.dist, sources=args.source, stdlib_zip=not args.no_stdlib_zip,
          fast=args.fast, dry_run=args.dry_run)
    if args.verify is not None and not args.dry_run:
        return 0 if verify(args.dist, third_party=args.verify) else 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
