"""Build TitanUpdater.exe - the updater a broken Titan cannot be.

    python build_updater.py [--console] [--output DIR]

The result is one self-contained file that can be handed to anyone running a
Titan that cannot update itself (every compiled build up to 0.5.7 - see the
docstring of src/scripts/titan_updater.py for why). It carries its own copy
of 7-Zip, so it works even against an installation whose ``data/bin`` is
missing or damaged.

It is deliberately NOT part of compiletorelease.py: an updater that ships
inside the thing it updates is an updater that gets replaced mid-update, and
that is exactly the class of bug it exists to work around.
"""

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(ROOT, 'src', 'scripts', 'titan_updater.py')
BIN = os.path.join(ROOT, 'data', 'bin')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--console', action='store_true',
                        help="build the console version (much smaller, no wx)")
    parser.add_argument('--output', default=os.path.join(ROOT, 'dist'),
                        help="where to put TitanUpdater.exe")
    args = parser.parse_args()

    if not os.path.exists(SOURCE):
        print("Cannot find {}".format(SOURCE))
        return 1

    work = os.path.join(ROOT, 'build', 'updater')
    command = [
        sys.executable, '-m', 'PyInstaller',
        '--onefile',
        '--name', 'TitanUpdater',
        '--distpath', args.output,
        '--workpath', work,
        '--specpath', work,
        '--noconfirm',
        '--clean',
    ]

    # 7-Zip travels with the updater: the whole point is not to depend on
    # files inside the installation being updated.
    for name in ('7z.exe', '7z.dll'):
        path = os.path.join(BIN, name)
        if os.path.exists(path):
            command += ['--add-binary', '{}{}.'.format(path, os.pathsep)]
        else:
            print("Warning: {} not found - the updater will fall back to the "
                  "7-Zip inside the installation.".format(path))

    if args.console:
        command.append('--console')
        # Nothing from wx is wanted in the small build.
        for module in ('wx', 'wx.core', 'numpy', 'PIL'):
            command += ['--exclude-module', module]
    else:
        command.append('--windowed')

    command.append(SOURCE)

    print(' '.join(command))
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    built = os.path.join(args.output, 'TitanUpdater.exe')
    if os.path.exists(built):
        print("\nBuilt {} ({:.1f} MB)".format(
            built, os.path.getsize(built) / (1024 * 1024)))
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
