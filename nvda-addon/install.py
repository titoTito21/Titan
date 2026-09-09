# -*- coding: utf-8 -*-
"""Put the built add-on into the NVDA on this machine.

    python nvda-addon/install.py          # build, then install
    python nvda-addon/install.py --to <folder>

**Why this exists.** NVDA installs an add-on from its own Add-on Store
dialog, which is right for a release and wrong for the twenty times a day an
add-on is changed: it needs a click, a confirmation and a restart, and it
puts the package in a `.pendingInstall` folder that only appears after that
restart. What a developer needs is for the files to BE there, now.

Three things it is careful about, each of them a way to break somebody's
reader:

* **It builds first.** Installing a stale package is how an afternoon goes
  into wondering why a fix did nothing - this repository has already paid
  for that once with the Elten bridge, where the repo folder is not what
  Elten runs. There is no path here that installs something that was not
  just built from the source in front of you.
* **It replaces the add-on's own folder and NOTHING else.** The user's own
  answers - their reader modules, their voice classes, the action catalogue
  - live in NVDA's configuration folder BESIDE the add-on, never inside it,
  so a clean replace cannot touch them. That is checked rather than assumed
  (:func:`_is_ours`).
* **A module that has gone, goes.** The folder is emptied rather than
  written over, because a file left behind from the last build is a module
  that still imports, still runs, and is not in the source any more - which
  is the worst kind of ghost to debug.

NVDA reads its add-ons when it starts, so it has to be restarted afterwards.
This says so rather than pretending the new code is live.
"""

import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = 'titanEnhancements'
PACKAGE = os.path.join(HERE, NAME + '-1.0.0.nvda-addon')

#: What has to be in a folder before this will empty it. An install that can
#: delete the wrong directory is one bad `--to` away from taking somebody's
#: configuration with it.
OURS = ('manifest.ini', 'globalPlugins')


def nvda_addons():
    """Where NVDA keeps its add-ons on this machine."""
    roaming = os.environ.get('APPDATA')
    if not roaming:
        home = os.path.expanduser('~')
        roaming = os.path.join(home, 'AppData', 'Roaming')
    return os.path.join(roaming, 'nvda', 'addons')


def build():
    """Build the package. False when the build failed - and then nothing is
    installed, because a half-built add-on is worse than the old one."""
    script = os.path.join(HERE, 'build.py')
    result = subprocess.run([sys.executable, script], cwd=HERE)
    return result.returncode == 0 and os.path.isfile(PACKAGE)


def _is_ours(folder):
    """Whether this folder is an install of THIS add-on, or is empty."""
    if not os.path.isdir(folder):
        return True
    if not os.listdir(folder):
        return True
    return all(os.path.exists(os.path.join(folder, name)) for name in OURS)


def _write_over(target, package):
    """Unpack over what is there, then take away what is no longer ours.

    **Never empty the folder first.** That was how it worked, and shipping
    sound files broke it: NVDA holds a `.wav` open the moment it has
    played one, so the delete failed AFTER the folder had been emptied and
    what was left on disk was a HALF-INSTALLED SCREEN READER. Measured -
    21 of 29 auditory icons gone, and the add-on in that state is what the
    user would have restarted into.

    Writing over instead means a file this add-on cannot replace keeps its
    PREVIOUS version - one file behind, which is a working reader - and
    everything else updates. What the old install had and the new one does
    not is deleted afterwards, so a module taken out of the add-on really
    goes, which is the one thing emptying the folder was for.

    Answers ``(files, could_not)``.
    """
    with zipfile.ZipFile(package) as archive:
        wanted = [name for name in archive.namelist()
                  if not name.endswith('/')]
        could_not = []
        for name in wanted:
            where = os.path.join(target, *name.split('/'))
            os.makedirs(os.path.dirname(where), exist_ok=True)
            try:
                with archive.open(name) as source, \
                        open(where, 'wb') as handle:
                    shutil.copyfileobj(source, handle)
            except OSError as error:
                could_not.append('%s (%s)' % (name, error))
    keep = {os.path.normcase(os.path.join(target, *name.split('/')))
            for name in wanted}
    for root, _directories, names in os.walk(target, topdown=False):
        for name in names:
            path = os.path.join(root, name)
            if os.path.normcase(path) in keep:
                continue
            try:
                os.remove(path)
            except OSError:
                # A leftover that will not go is a file from an older
                # version that nothing imports. It is untidy and it is not
                # a broken install, so it is not worth failing over.
                pass
        try:
            if not os.listdir(root) and os.path.normcase(root) != \
                    os.path.normcase(target):
                os.rmdir(root)
        except OSError:
            pass
    files = sum(len(names) for _b, _d, names in os.walk(target))
    return files, could_not


def install(target):
    if not os.path.isfile(PACKAGE):
        print('There is no package to install. Build it first.')
        return False
    if not _is_ours(target):
        print('%s does not look like an install of %s, so it has been left '
              'alone.' % (target, NAME))
        return False
    os.makedirs(target, exist_ok=True)
    files, could_not = _write_over(target, PACKAGE)
    print('%d files installed into %s' % (files, target))
    if could_not:
        # Said plainly and NOT treated as a failed install: everything else
        # really did update, and the add-on on disk is whole.
        print('%d file(s) NVDA is holding open kept their previous version. '
              'Restart NVDA and run this again to replace them:'
              % len(could_not))
        for name in could_not[:8]:
            print('  ' + name)
        return False
    return True


def running():
    """Whether NVDA is running, so the user can be told to restart it."""
    try:
        out = subprocess.run(['tasklist'], capture_output=True, text=True,
                             timeout=20).stdout.lower()
    except Exception:                                # noqa: BLE001
        return False
    return 'nvda.exe' in out


def main(argv):
    target = None
    if '--to' in argv:
        target = argv[argv.index('--to') + 1]
    if target is None:
        target = os.path.join(nvda_addons(), NAME)
    if '--no-build' not in argv and not build():
        print('The add-on did not build, so nothing was installed.')
        return 1
    if not install(target):
        return 1
    if running():
        print('NVDA is running. Restart it (NVDA+q, then start it again, or '
              'NVDA+control+f3 to reload plugins) to pick this up.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
