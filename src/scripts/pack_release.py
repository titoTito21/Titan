"""Pack a compiled Titan into the update archive the updater can really open.

    python src/scripts/pack_release.py [dist/Titan] [-o titan.main.7z] [--level 9]
    python src/scripts/pack_release.py --check titan.main.7z

The archive on the server is unpacked by the Titan ALREADY INSTALLED on the
user's machine - and that one unpacks in-process with py7zr, which has no
decoder for 7-Zip's ARM64 branch filter. 7-Zip 23+ picks that filter by
itself for an ARM64 executable, and the tree carries two (sounddevice's
``libportaudioarm64*.dll``), so an archive made with 7-Zip's defaults put
them in a block py7zr answers with UnsupportedCompressionMethodError - after
most of the install had been written. Measured on the archive of
2026-10-02: every compiled update failed on a machine with no 7-Zip of its
own on PATH.

So this packs with ``-mf=BCJ`` (the x86 branch filter for every executable,
which py7zr decodes), and then reads the finished archive's header back the
way the updater does, block by block, refusing to call the archive ready if
py7zr could not decode any of it. ``--check`` does only the second half, for
an archive made some other way.
"""

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUNDLED_7Z = os.path.join(ROOT, 'data', 'bin', '7z.exe')

#: Files a build leaves in the tree that have no place in an update.
STRAY = ('component_debug.log', 'engine_registry_debug.log',
         'app_manager_debug.log', 'titan_update.7z', 'titan_interpreter.7z')

#: What the published titan.main.7z leaves out, read off the archive of
#: 2026-10-02: the TTS engines and the three big components are shipped as
#: packages of their own, not inside the program update. Relative to the
#: compiled folder; ``--include-all`` ships everything, ``--exclude`` adds.
DEFAULT_EXCLUDES = (
    'data/titantts engines',
    'data/components/cling',
    'data/components/elten_bridge',
    'data/components/titan access',
)


def seven_zip():
    if os.path.exists(BUNDLED_7Z):
        return BUNDLED_7Z
    found = shutil.which('7z')
    if not found:
        sys.exit("7-Zip was not found (data/bin/7z.exe or 7z on PATH).")
    return found


def method_names():
    try:
        from src.system.updater import _METHOD_NAMES
        return _METHOD_NAMES
    except Exception:
        return {'21': 'LZMA2', '03030103': 'BCJ', '0a': 'ARM64', '03': 'Delta'}


def blocks_py7zr_cannot_decode(archive):
    """[(index, methods, error)] for every block py7zr has no decoder for."""
    import py7zr
    from py7zr.compressor import SevenZipDecompressor
    names = method_names()
    bad = []
    with py7zr.SevenZipFile(archive, 'r') as handle:
        folders = handle.header.main_streams.unpackinfo.folders
        for index, folder in enumerate(folders):
            methods = ' '.join(names.get(bytes(c['method']).hex(),
                                         bytes(c['method']).hex())
                               for c in folder.coders)
            try:
                SevenZipDecompressor(folder.coders, 1,
                                     list(folder.unpacksizes), 0, None)
            except Exception as error:      # noqa: BLE001
                bad.append((index, methods, str(error)))
            else:
                print(f"  block {index}: {methods} - py7zr can decode it")
    return bad


def check(archive):
    print(f"Checking {archive}")
    try:
        import py7zr  # noqa: F401
    except ImportError:
        print("py7zr is not installed here; the updater's in-process path "
              "cannot be checked. pip install py7zr")
        return 2
    bad = blocks_py7zr_cannot_decode(archive)
    for index, methods, error in bad:
        print(f"  block {index}: {methods} - py7zr CANNOT decode it: {error}")
    if bad:
        print("NOT READY: an installed Titan without a 7-Zip on PATH could "
              "not apply this archive. Pack it with this script (-mf=BCJ).")
        return 1
    print("Ready: every block can be unpacked by the installed Titan itself.")
    return 0


def pack(source, output, level, excludes):
    source = os.path.abspath(source)
    if not os.path.isfile(os.path.join(source, 'Titan.exe')):
        sys.exit(f"{source} does not hold a compiled Titan (no Titan.exe).")
    for root_dir, _dirs, files in os.walk(source):
        for name in files:
            if name.endswith('.old') or name in STRAY[3:]:
                print(f"Warning: {os.path.join(root_dir, name)} is in the tree "
                      "and would be shipped.")
    output = os.path.abspath(output)
    if os.path.exists(output):
        os.remove(output)
    command = [seven_zip(), 'a', '-t7z', f'-mx={level}', '-mf=BCJ',
               '-sccUTF-8']
    # Debug logs a dev run left under src/ go into every build (--add-data
    # src); they are nobody's business in an update.
    command += ['-xr!*_debug*.log', '-xr!*.old',
                '-x!titan_update.7z', '-x!titan_interpreter.7z']
    for rel in excludes:
        rel = rel.replace('/', os.sep).rstrip(os.sep)
        if os.path.exists(os.path.join(source, rel)):
            command.append(f'-x!{rel}')
            print(f"Leaving out: {rel}")
        else:
            print(f"(not in this build, nothing to leave out: {rel})")
    command += [output, '*']
    print(' '.join(command))
    print(f"(in {source})")
    result = subprocess.run(command, cwd=source)
    if result.returncode != 0:
        sys.exit(f"7-Zip exited with code {result.returncode}")
    size = os.path.getsize(output) / (1024 * 1024)
    print(f"Written: {output} ({size:.1f} MB)")
    return check(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('source', nargs='?',
                        default=os.path.join(ROOT, 'dist', 'Titan'),
                        help="the compiled Titan folder (default dist/Titan)")
    parser.add_argument('-o', '--output', default=None,
                        help="the archive to write (default titan.main.7z "
                             "beside the source folder)")
    parser.add_argument('--level', type=int, default=9,
                        help="7-Zip compression level, 1-9 (default 9)")
    parser.add_argument('--check', metavar='ARCHIVE', default=None,
                        help="only check whether an existing archive can be "
                             "unpacked by the installed Titan")
    parser.add_argument('--exclude', action='append', default=[],
                        metavar='RELPATH',
                        help="a folder or file (relative to the compiled "
                             "folder) to leave out, besides the defaults: "
                             + ', '.join(DEFAULT_EXCLUDES))
    parser.add_argument('--include-all', action='store_true',
                        help="ship the TTS engines and the big components "
                             "too (no default exclusions)")
    args = parser.parse_args(argv)
    if args.check:
        return check(args.check)
    output = args.output or os.path.join(os.path.dirname(args.source.rstrip('\\/')),
                                         'titan.main.7z')
    excludes = list(args.exclude)
    if not args.include_all:
        excludes = list(DEFAULT_EXCLUDES) + excludes
    return pack(args.source, output, args.level, excludes)


if __name__ == '__main__':
    sys.exit(main())
