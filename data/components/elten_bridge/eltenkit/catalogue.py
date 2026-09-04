# -*- coding: utf-8 -*-
"""Every Elten application on this machine, found where Elten put it.

**The user installs through Elten and runs through Titan.** That is the whole
shape of this: Elten has an application repository, an installer, updates and
an account behind them, and none of that is Titan's to re-do. So there is no
"import" step and nothing is copied anywhere - the bridge reads
`%APPDATA%/elten/apps/`, which is Elten's own directory, exactly as Elten
leaves it, and an application installed in Elten five minutes ago is in
Titan's list when the window is next opened.

What is in there:

    apps/apps.json          what Elten believes is installed: name -> uuid,
                            when it was installed and last updated
    apps/src/<name>.eltenapp        the application itself
    apps/src/<folder>/<name>.eltenapp   some arrive inside a folder of their
                                        own, with a readme beside them
    apps/data/<name>/       the application's own saved state
    apps/cache/             what it can afford to lose

`apps/data/` is deliberately shared rather than copied. An application's saves
are the user's, not the launcher's: somebody who plays Solitaire in Elten and
then opens it here should find their game where they left it, and a bridge
that kept a second copy would be a bridge that quietly loses whichever half
was written to last.

Titan's own roots are looked in as well - `data/eltenapps/` bundled and in the
user overlay, and the component's own `apps/` - so an application that did not
come from Elten's repository still has somewhere to live. Elten's own
directory is looked in LAST, which is what makes it win: it is the user's
installation, and if the same application is in two places theirs is the one
that is really installed.
"""

import json
import os

from . import package as package_module

#: `data/<subdir>/` for applications that did not come from Elten's own
#: repository - Titan's bundled copy and the user's overlay.
DATA_SUBDIR = 'eltenapps'

#: What the list is called, everywhere a person can see it.
TITLE = 'Elten API applications'

#: How deep to look inside Elten's `src/`. One level down is where an
#: application that ships a readme beside itself lives (`MileByMile-0.4.8/`,
#: `ffmpeg/`); deeper than that is somebody's own folder of downloads and not
#: something to walk.
SEARCH_DEPTH = 1


class Application(object):
    """One Elten application, as far as its package says."""

    __slots__ = ('id', 'path', 'manifest', 'signature', 'name', 'version',
                 'author', 'api_version', 'main_class', 'description',
                 'languages', 'source', 'problem')

    def __init__(self, path='', manifest=None, signature=None, source=''):
        self.path = path
        self.manifest = manifest or {}
        self.signature = signature or package_module.Signature()
        self.source = source
        self.problem = ''
        self.id = str(self.manifest.get('id') or '')
        self.version = str(self.manifest.get('version') or '')
        self.author = str(self.manifest.get('author') or '')
        self.api_version = str(self.manifest.get('EltenAPIVersion') or '')
        self.main_class = str(self.manifest.get('main_class') or '')
        self.name = ''
        self.description = ''
        self.languages = []

    # ------------------------------------------------------------- reading
    @property
    def key(self):
        """What this application is called in a list and on disk.

        The UUID is the identity - Elten says so, and two builds of one
        application share it - but a file name is what a person recognises and
        what `apps.json` is keyed on, so it is the fallback when a package has
        no id at all.
        """
        return self.id or self.stem

    @property
    def stem(self):
        return os.path.splitext(os.path.basename(self.path))[0]

    @property
    def installed_by_elten(self):
        return self.source == 'elten'

    @property
    def hidden(self):
        """True for an application that is not something to open.

        Elten's own rule, out of the manifest's `menu` block: `ffmpeg`
        registers five audio encoders and returns, `mcp` is a server. They
        are plug-ins - they give every OTHER application something - and
        Elten does not put them in its menu, so neither does this. Listing
        them would offer the user a row that opens, does its work in a
        fraction of a second and closes again, which reads as an
        application that is broken.
        """
        menu = self.manifest.get('menu')
        if isinstance(menu, dict):
            return bool(menu.get('hidden'))
        return False

    @property
    def openable(self):
        """Something a person can actually open and use."""
        return not self.hidden and not self.problem

    @property
    def runnable(self):
        return not self.problem

    def localise(self, language=''):
        """Fill in the name and description in the user's language."""
        self.name = package_module._localised(self.manifest, 'name', language) \
            or self.stem
        self.description = package_module._localised(
            self.manifest, 'description', language)
        return self


# --------------------------------------------------------------- where they are
def elten_root():
    """Elten's own directory, or ''.

    `ELTEN_HOME` is honoured first so a portable Elten, or a second one, can
    be pointed at; otherwise it is where Elten itself keeps it.
    """
    named = os.environ.get('ELTEN_HOME', '').strip()
    if named and os.path.isdir(named):
        return named
    base = os.environ.get('APPDATA', '')
    if not base:
        home = os.path.expanduser('~')
        for candidate in (os.path.join(home, '.elten'),
                          os.path.join(home, 'Library', 'Application Support',
                                       'elten')):
            if os.path.isdir(candidate):
                return candidate
        return ''
    candidate = os.path.join(base, 'elten')
    return candidate if os.path.isdir(candidate) else ''


def elten_apps_dir():
    root = elten_root()
    return os.path.join(root, 'apps') if root else ''


def elten_source_dir():
    apps = elten_apps_dir()
    return os.path.join(apps, 'src') if apps else ''


def elten_data_dir():
    """Where an application's own saved state lives - Elten's, shared."""
    apps = elten_apps_dir()
    return os.path.join(apps, 'data') if apps else ''


def elten_cache_dir():
    apps = elten_apps_dir()
    return os.path.join(apps, 'cache') if apps else ''


def component_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def component_apps_dir():
    """Applications the bridge ships with itself."""
    return os.path.join(component_root(), 'apps')


def user_apps_dir():
    """Where an application the user drops in by hand goes."""
    try:
        from src.platform_utils import get_user_resource_path
        base = get_user_resource_path(os.path.join('data', DATA_SUBDIR))
    except Exception:
        import sys
        if sys.platform == 'win32':
            root = os.getenv('APPDATA', os.path.expanduser('~'))
        elif sys.platform == 'darwin':
            root = os.path.expanduser('~/Library/Application Support')
        else:
            root = os.environ.get('XDG_CONFIG_HOME',
                                  os.path.expanduser('~/.config'))
        base = os.path.join(root, 'titosoft', 'Titan', 'data', DATA_SUBDIR)
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        pass
    return base


def installed_by_elten():
    """What `apps.json` says Elten has installed: name -> the record.

    It is read for what it knows and the packages are found by looking, not
    the other way round: an application whose file is there is runnable
    whether or not Elten has finished writing its bookkeeping, and one listed
    in `apps.json` whose file has gone is not something to offer.
    """
    apps = elten_apps_dir()
    if not apps:
        return {}
    try:
        with open(os.path.join(apps, 'apps.json'), encoding='utf-8') as handle:
            listed = json.load(handle).get('apps') or {}
    except (OSError, ValueError):
        return {}
    return listed if isinstance(listed, dict) else {}


def roots():
    """Everywhere an application may be, in the order they are looked in.

    Elten's own is LAST, which is how it wins a name collision: it is the
    installation the user actually manages.
    """
    found = []
    for path in (component_apps_dir(),):
        if os.path.isdir(path):
            found.append((path, 'component'))
    try:
        from src.platform_utils import iter_data_roots
        for path in iter_data_roots(DATA_SUBDIR):
            found.append((path, 'titan'))
    except Exception:
        path = user_apps_dir()
        if os.path.isdir(path):
            found.append((path, 'titan'))
    source = elten_source_dir()
    if source and os.path.isdir(source):
        found.append((source, 'elten'))
    return found


def packages_in(root, depth=SEARCH_DEPTH):
    """Every `.eltenapp` in a folder, and one level inside its folders."""
    found = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return found
    for name in names:
        full = os.path.join(root, name)
        if os.path.isfile(full):
            if package_module.looks_like_package(full):
                found.append(full)
        elif depth > 0 and os.path.isdir(full):
            found.extend(packages_in(full, depth - 1))
    return found


# ------------------------------------------------------------------ discovery
def discover(language='', where=None, openable_only=False):
    """Every application that can be listed, the user's own winning.

    A package that cannot be opened is still LISTED, carrying the sentence
    that says why: an application the user installed and cannot see is a
    subsystem that looks broken, and one that says "this package is damaged"
    is a subsystem that told them something.
    """
    found = {}
    for root, source in (where if where is not None else roots()):
        for path in packages_in(root):
            application = _read(path, source)
            application.localise(language)
            found[application.key] = application
    entries = sorted(found.values(), key=lambda app: (app.name or '').lower())
    if openable_only:
        # A plug-in is not something to offer: see `Application.hidden`.
        entries = [entry for entry in entries if not entry.hidden]
    return entries


def find(key, language='', where=None):
    """One application by its id, or by the name of its file."""
    wanted = str(key or '').strip().lower()
    if not wanted:
        return None
    for application in discover(language, where):
        if wanted in (application.id.lower(), application.stem.lower(),
                      (application.name or '').lower()):
            return application
    return None


def _read(path, source):
    try:
        manifest, signature = package_module.read_manifest(path)
    except package_module.PackageError as error:
        application = Application(path, {}, None, source)
        application.problem = str(error)
        return application
    except Exception as error:                          # a truncated download
        application = Application(path, {}, None, source)
        application.problem = '%s could not be read: %s' % (
            os.path.basename(path), error)
        return application
    application = Application(path, manifest, signature, source)
    application.problem = _refuse(application)
    return application


def _refuse(application):
    """Why this application cannot be run here, in one sentence, or ''.

    Only things that are really true of the package. "It is not signed" is
    deliberately NOT one of them: Elten's own builder makes unsigned packages
    for development, the user may well be the author, and refusing to open
    somebody's own application because Titan cannot check a signature that
    Titan was never going to trust anyway would be theatre.
    """
    if not application.manifest:
        return 'this package has no manifest'
    if not application.main_class:
        return 'this package does not say which class to run'
    platforms = application.manifest.get('platforms') or []
    if isinstance(platforms, list) and platforms:
        wanted = {str(name).lower() for name in platforms}
        if not wanted & {'all', 'universal', '*'} and not _platform() & wanted:
            return 'this application is not built for this system'
    return ''


def _platform():
    """What this machine is, in the words a manifest uses."""
    import platform
    import sys
    system = {'win32': 'windows', 'darwin': 'osx'}.get(sys.platform, 'linux')
    machine = platform.machine().lower()
    architecture = {'amd64': 'x64', 'x86_64': 'x64', 'arm64': 'arm64',
                    'aarch64': 'arm64', 'i386': 'x86',
                    'i686': 'x86'}.get(machine, machine)
    return {system, '%s-%s' % (system, architecture)}
