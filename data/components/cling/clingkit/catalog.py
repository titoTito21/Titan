# -*- coding: utf-8 -*-
"""What a Cling application IS, and how Cling finds the ones installed.

A Cling application is a directory in `data/cling/` - bundled beside Titan or,
much more usually, in the user's own overlay - and it is deliberately the same
directory a Klango application already is:

    mole/
      kni.txt                     appid, appname, summary, version
      lang/default                the locale the rest falls back to
      lang/en-us/default/*.txt    everything it says
      skin/default/levels/*.lev   the levels, and the topologies they name
      skin/default/themes/*/*.ogg the sounds

Nothing there is Cling's invention, and that is the point: an application
somebody wrote for Klango is copied in and runs.  Cling adds two optional
things on top - `__cling__.TCE`, so an application written FOR Cling can say
which engine it wants and be named in two languages the way every other Titan
add-on is, and `main.py` / `main.lua` for one that brings its own logic.

Discovery is `platform_utils.discover_data_entries`, so a packaged `.TCD` is
found exactly like a directory, and a user's copy of an application overrides
the bundled one under the same name - the eleven add-on kinds already work
this way and a twelfth answer to the same question would be one too many.
"""

import configparser
import os

from . import resources

#: The subdirectory of `data/` Cling applications live in.
DATA_SUBDIR = 'cling'
#: Klango's own manifest.  Read first, because an imported application has it.
KNI = 'kni.txt'
#: Cling's manifest, for an application written for Titan.
#: Packages that are the platform's own library rather than an application.
#: `llib` is what every Klango application is built on; listing it as something
#: to play would be listing the runtime.
LIBRARY_PACKAGES = frozenset(('llib', 'core', 'klango'))

MANIFEST = '__cling__.TCE'
MANIFEST_SECTION = 'cling app'

#: The engines Cling can drive an application with. `catalog.detect_engine`
#: works one out from what the directory holds when the manifest is silent.
ENGINE_KLANGO = 'klango'
ENGINE_SCRIPT = 'script'
ENGINE_GRID_HUNT = 'grid_hunt'
ENGINE_SOUNDSCAPE = 'soundscape'
ENGINE_INSTRUMENT = 'instrument'
ENGINE_TYPING = 'typing'
ENGINE_READER = 'reader'
ENGINES = (ENGINE_KLANGO, ENGINE_SCRIPT, ENGINE_GRID_HUNT, ENGINE_SOUNDSCAPE,
           ENGINE_INSTRUMENT, ENGINE_TYPING, ENGINE_READER)

#: The categories the browser groups applications under. They are Klango's own
#: top-level folders, which is what an imported application will name.
CATEGORIES = ('games', 'edu', 'soundscape', 'network', 'tools', 'other')
_CATEGORY_ALIASES = {
    'simplegames': 'games', 'game': 'games', 'gry': 'games',
    'education': 'edu', 'nauka': 'edu',
    'extservices': 'network', 'net': 'network', 'internet': 'network',
    'soundscapes': 'soundscape', 'ambience': 'soundscape',
    'narzedzia': 'tools', 'utilities': 'tools', 'tool': 'tools',
}

#: The keys `kni.txt` is allowed to carry.  Anything else is kept but reported,
#: because a key nobody reads is how an application ends up silently ignoring
#: half of what its author wrote.
KNI_KEYS = ('appid', 'appname', 'summary', 'version', 'minklango', 'platform',
            'category', 'engine', 'entry', 'author', 'homepage')


def _read_kni(path):
    values = {}
    unknown = []
    from . import textio
    content = textio.read_or_none(path)
    if content is None:
        return values, unknown
    for line in content.replace('\r\n', '\n').split('\n'):
        line = line.strip()
        if not line or line.startswith(('#', ';', '--')) or '=' not in line:
            continue
        key, _sep, value = line.partition('=')
        key = key.strip().lower()
        values[key] = value.strip()
        if key not in KNI_KEYS:
            unknown.append(key)
    return values, unknown


def _read_manifest(path):
    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding='utf-8')
    except (configparser.Error, OSError):
        return {}
    for section in (MANIFEST_SECTION, 'cling', 'app', 'component'):
        if parser.has_section(section):
            return {key.lower(): value for key, value in parser.items(section)}
    return {}


class ClingApp(object):
    """One installed application: what it is called, and what runs it."""

    def __init__(self, app_id, path):
        self.id = app_id
        self.path = path
        self.problems = []

        kni, unknown = _read_kni(os.path.join(path, KNI))
        manifest = _read_manifest(os.path.join(path, MANIFEST))
        for key in unknown:
            self.problems.append("kni.txt: '%s' is not a key Cling reads" % key)

        self.kni = kni
        self.manifest = manifest
        self.appid = kni.get('appid', '')
        self.version = manifest.get('version') or kni.get('version') or ''
        self.author = manifest.get('author') or kni.get('author') or ''
        self.status = _status_of(manifest)

        self._names = {'': manifest.get('name') or kni.get('appname') or app_id}
        for key, value in manifest.items():
            if key.startswith('name_') and value:
                self._names[key[5:].lower()] = value
        self._summaries = {'': manifest.get('description')
                           or kni.get('summary') or ''}
        for key, value in manifest.items():
            if key.startswith('description_') and value:
                self._summaries[key[12:].lower()] = value

        self.category = _category_of(manifest.get('category')
                                     or kni.get('category') or '', path)
        self.entry = manifest.get('entry') or kni.get('entry') or ''
        self.engine = (manifest.get('engine') or kni.get('engine') or '').strip().lower()
        if self.engine and self.engine not in ENGINES:
            self.problems.append("'%s' is not an engine Cling has" % self.engine)
            self.engine = ''
        if not self.engine:
            self.engine = detect_engine(path)

        #: Whether the manifest named the engine itself. An application that
        #: says what it wants keeps it; everything else is worked out, and can
        #: be worked out again once its package is known.
        self.engine_declared = bool((manifest.get('engine')
                                     or kni.get('engine') or '').strip())
        self.texts = None
        self.skin = None
        #: The original Klango `.pag` this application shipped as, when one is
        #: sitting beside it. Cling cannot open a concealed one yet, but it can
        #: say it is there - which is the difference between "this application
        #: has no more to give" and "its own code is right here, locked".
        self.package = ''
        self.locked = False

    # ----------------------------------------------------------- names
    def locked_reason(self):
        """Why a locked application will not start, in one sentence."""
        if not self.locked:
            return ''
        from . import pag
        return ('%s is here as a Klango package only. Its contents are '
                'concealed and Cling has no keystream for it, so there is no '
                'data folder to read. See %s.'
                % (os.path.basename(self.package), pag.keys_dir()))

    def name(self, language=''):
        """What to call it, in the user's language where the author gave one.

        A Klango application says its own name in `lang/<locale>/default/
        klangomenu.txt` - already translated, by its author - so that is
        preferred over anything a manifest repeats in English.
        """
        menu = self.texts.text('klangomenu') if self.texts else ''
        if menu:
            return menu.split('\n')[0].strip()
        return self._pick(self._names, language)

    def summary(self, language=''):
        appinfo = self.texts.text('appinfo_summary') if self.texts else ''
        return appinfo or self._pick(self._summaries, language)

    @staticmethod
    def _pick(table, language):
        code = (language or '').split('-')[0].lower()
        return table.get(code) or table.get('') or ''

    # ----------------------------------------------------------- loading
    def open(self, language=''):
        """Read the texts and the skin. Cheap, and only done when needed."""
        if self.locked:
            return self
        if self.texts is None:
            self.texts = resources.TextCatalogue(self.path, language)
        if self.skin is None:
            info = self.texts.info()
            self.skin = resources.Skin(self.path,
                                       info.get('skin', 'default') or 'default',
                                       info.get('theme', 'default') or 'default')
        return self

    @property
    def enabled(self):
        return self.status == 0

    @property
    def hidden(self):
        """`appinfo.txt`'s `hideinmenu` - an application that is a library."""
        if self.texts is None:
            return False
        return self.texts.info().get('hideinmenu', 'no').lower() in ('yes', 'true', '1')

    def reconsider_engine(self):
        """Decide again, now that the application's package is known.

        The code is in the package and the data may be in a folder beside it,
        and the folder is what wins for reading. So whether an application can
        be EMULATED - whether it brings its own Klango code - cannot be known
        until the package has been found, which happens after the manifest is
        read.
        """
        if self.engine_declared or self.locked:
            return self.engine
        root = ''
        if self.package:
            try:
                from . import pag
                root = pag.mount(self.package)
            except Exception:
                root = ''
        for candidate in (root, self.path):
            if candidate and has_klango_code(candidate,
                                             self.kni.get('appname') or self.id) \
                    and klango_library_installed():
                self.engine = ENGINE_KLANGO
                return self.engine
        return self.engine

    @property
    def playable(self):
        """Can Cling actually run this, or only say what it is?"""
        return not self.locked

    def entry_path(self):
        """The script that runs it: the application's own, or Cling's for it.

        A Klango application's own logic is Lua inside an encrypted package
        that Cling has no key for, so the application on the disk is its data
        and nothing else.  Cling therefore ships logic OF ITS OWN for the
        applications whose rules are known - `logic/<appname>/main.lua` beside
        this component - and an installed application with no script of its own
        is run by it, against its own texts, its own sounds and its own skin.

        The application's folder is never touched.  It is the user's copy of
        somebody else's work; a subsystem that wrote a file into it would be
        modifying an installation it does not own, and the file would be gone
        the next time they reinstalled.
        """
        if self.entry:
            candidate = os.path.join(self.path, self.entry)
            if os.path.isfile(candidate):
                return candidate
        for leaf in ('main.py', 'main.lua'):
            candidate = os.path.join(self.path, leaf)
            if os.path.isfile(candidate):
                return candidate
        return bundled_logic(self.kni.get('appname') or self.id, self.appid)

    def __repr__(self):                                  # pragma: no cover
        return '<ClingApp %s engine=%s>' % (self.id, self.engine)


def _status_of(manifest):
    raw = str(manifest.get('status', '0')).strip().lower()
    if raw in ('1', 'off', 'disabled', 'false', 'no'):
        return 1
    return 0


def _category_of(declared, path):
    name = (declared or '').strip().lower()
    if not name:
        # An application imported with its Klango folder above it names its
        # category by where it was: `apps/simplegames/mole`.
        parent = os.path.basename(os.path.dirname(path)).lower()
        name = parent
    name = _CATEGORY_ALIASES.get(name, name)
    return name if name in CATEGORIES else 'other'


def logic_dir():
    """`data/components/cling/logic/` - the logic Cling ships for applications
    whose own code it cannot have."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'logic'))


def bundled_logic(appname, appid=''):
    """Cling's own logic for an application, matched by name then by id.

    It ships as a `.pag` - one file per application, the way a Klango
    application ships - and is unpacked into the runtime cache the first time
    it is wanted.  A plain folder is accepted too, because that is what an
    author works in before it is packed.
    """
    root = logic_dir()
    for name in (str(appname or '').strip().lower(), str(appid or '').strip()):
        if not name:
            continue
        package = os.path.join(root, name + '.pag')
        if os.path.isfile(package):
            try:
                from . import pag
                folder = pag.mount(package)
                candidate = os.path.join(folder, 'main.lua')
                if os.path.isfile(candidate):
                    return candidate
            except Exception as error:
                print("[cling] logic package '%s' could not be opened: %s"
                      % (name, error))
        candidate = os.path.join(root, name, 'main.lua')
        if os.path.isfile(candidate):
            return candidate
    return ''


def has_bundled_logic(appname, appid=''):
    return bool(bundled_logic(appname, appid))


def has_klango_code(path, appname=''):
    """Does this application bring its OWN Klango code?

    A Klango application's entry file is named after the application and sits
    at its root, beside `lang/` and `skin/`. That is the file `main()` is in,
    and its presence is what makes emulation possible rather than a
    re-creation from data.
    """
    try:
        leaves = os.listdir(path)
    except OSError:
        return False
    scripts = [leaf for leaf in leaves if leaf.lower().endswith('.lua')]
    if not scripts:
        return False
    # A Klango application is Lua beside `lang/` - that pairing is what says
    # this is one. Matching the file NAME against the application's is not
    # enough: Long Jump's own entry is `lj.lua` while it calls itself
    # `longjump`, and Klango finds it by looking, not by guessing.
    return os.path.isdir(os.path.join(path, 'lang'))


def klango_library_installed():
    """Is Klango's platform library there for an application to run on?"""
    try:
        from .klango.session import find_library
        return bool(find_library())
    except Exception:
        return False


def detect_engine(path):
    """Which engine runs the directory, worked out from what is in it.

    Most specific first, and every test is of something the directory really
    holds rather than of what it is called: an application's own script, then
    the four shapes whose data IS the rules - a board described by levels, a
    place described by `spec.txt`, an instrument described by a folder of
    samples named after keys, a course described by lesson files - and finally
    the reader, which every application with words qualifies for and which is
    honest about being a way to read what an application says rather than a
    way to play it.
    """
    kni, _unknown = _read_kni(os.path.join(path, KNI))
    # An application that brings its own Klango code is EMULATED - its own
    # `main()`, on Klango's own library - rather than re-created from its data.
    # That is the whole point of the subsystem, so it is asked first.
    if has_klango_code(path, kni.get('appname')) and klango_library_installed():
        return ENGINE_KLANGO
    for leaf in ('main.lua', 'main.py'):
        if os.path.isfile(os.path.join(path, leaf)):
            return ENGINE_SCRIPT
    if has_bundled_logic(kni.get('appname') or os.path.basename(path),
                         kni.get('appid')):
        return ENGINE_SCRIPT

    skin_root = os.path.join(path, 'skin')
    has_levels = False
    has_sounds = False
    if os.path.isdir(skin_root):
        for root, _dirs, files in os.walk(skin_root):
            for leaf in files:
                lowered = leaf.lower()
                if lowered.endswith('.lev'):
                    has_levels = True
                elif lowered.endswith(('.ogg', '.wav', '.mp3', '.flac')):
                    has_sounds = True
            if has_levels and has_sounds:
                break
    if has_levels:
        return ENGINE_GRID_HUNT

    try:
        from .engines.soundscape import has_spec
        if has_spec(path):
            return ENGINE_SOUNDSCAPE
    except Exception:
        pass
    try:
        from .engines.instrument import looks_like_instrument
        if looks_like_instrument(path):
            return ENGINE_INSTRUMENT
    except Exception:
        pass
    try:
        from .engines.typing import looks_like_course
        if looks_like_course(path):
            return ENGINE_TYPING
    except Exception:
        pass

    # A folder of sounds is only a PLACE when the application says so - a
    # `spec.txt`, or Klango's `data/` convention that a soundscape's recordings
    # live there. Guessing from a sound count instead put a calculator and a
    # chat client (six and seven sounds) in the same bucket as a game with
    # eight, which is a reading that helps nobody.
    if _has_sounds_in(os.path.join(path, 'data')):
        return ENGINE_SOUNDSCAPE
    return ENGINE_READER


def _has_sounds_in(folder):
    try:
        return any(leaf.lower().endswith(('.ogg', '.wav', '.mp3', '.flac'))
                   for leaf in os.listdir(folder))
    except OSError:
        return False


def looks_like_app(path):
    """Is this a Cling application at all - a folder, or a package?"""
    if os.path.isfile(path):
        try:
            from . import pag
            return pag.kind_of(path) == pag.CLING
        except Exception:
            return False
    return os.path.isfile(os.path.join(path, KNI)) \
        or os.path.isfile(os.path.join(path, MANIFEST))


def component_root():
    """The Cling component's own folder - `data/components/cling/`.

    Everything Cling ships is under here and nowhere else, so the component
    can be copied to another Titan, or packaged as a `.TCD`, and still be
    whole. Its applications live in `apps/` and its written-here logic in
    `logic/`; `data/cling/` is the USER's - the applications they installed,
    and Klango's own library if they have it.
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def component_apps_dir():
    """The applications Cling ships with itself."""
    return os.path.join(component_root(), 'apps')


def user_apps_dir():
    """Where an application the user installs goes. Created on demand."""
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
            root = os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
        base = os.path.join(root, 'titosoft', 'Titan', 'data', DATA_SUBDIR)
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        pass
    return base


def discover(roots=None, language=''):
    """Every installed application, bundled and the user's own.

    `roots` is for the tests and for importing from somewhere else; left out,
    it is Titan's own discovery, which is also what makes a packaged `.TCD`
    application appear here exactly like a directory.
    """
    found = {}
    if roots is None:
        try:
            from src.platform_utils import discover_data_entries, iter_data_roots
            found = discover_data_entries(DATA_SUBDIR,
                                          lambda name, full: looks_like_app(full))
            roots_to_scan = list(iter_data_roots(DATA_SUBDIR))
        except Exception as error:
            print('[cling] discovery through Titan failed: %s' % error)
            found, roots_to_scan = {}, []
        # The component's own applications come LAST, so a user who has
        # installed one of the same name keeps theirs - the overlay rule the
        # other eleven add-on kinds already follow.
        roots_to_scan.append(component_apps_dir())
    else:
        roots_to_scan = list(roots)
    for root in roots_to_scan:
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for name in names:
            full = os.path.join(root, name)
            if name in found:
                continue          # an earlier root already answered for it
            if os.path.isdir(full) and looks_like_app(full):
                found[name] = full

    # A `.pag` beside the folders is a whole application in one file - which is
    # how a Klango application ships, and therefore how a Cling one does. It is
    # unpacked into the runtime cache and used from there; the file itself is
    # never touched, and a folder of the same name wins, so an application
    # somebody is working on overrides the package they shipped.
    klango_packages = {}
    for root in roots_to_scan:
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for name in names:
            if not name.lower().endswith('.pag'):
                continue
            full = os.path.join(root, name)
            if not os.path.isfile(full):
                continue
            entry_name = os.path.splitext(name)[0]
            if entry_name.lower() in LIBRARY_PACKAGES:
                continue          # `llib` is the runtime, not something to play
            try:
                from . import pag
                kind = pag.kind_of(full)
            except Exception as error:
                print("[cling] '%s' could not be read: %s" % (name, error))
                continue
            if not kind:
                continue
            # A Klango package is the application ITSELF - its texts, its
            # sounds, its levels and its own code - so it is unpacked into the
            # runtime cache and used exactly like a folder. It is also
            # remembered against the application, because a folder of the same
            # name wins and the package is then the original beside it.
            klango_packages[entry_name] = full
            if entry_name in found:
                continue
            try:
                found[entry_name] = pag.mount(full)
            except Exception as error:
                print("[cling] '%s' could not be opened: %s" % (name, error))

    apps = []
    for app_id, path in found.items():
        try:
            app = ClingApp(app_id, path).open(language)
        except Exception as error:
            print("[cling] '%s' could not be read: %s" % (app_id, error))
            continue
        app.package = klango_packages.pop(app_id, '')
        app.reconsider_engine()
        apps.append(app)

    # A package Cling could not open at all: still listed, and honest about it.
    for app_id, package in klango_packages.items():
        if app_id.lower() in LIBRARY_PACKAGES:
            continue
        app = ClingApp.__new__(ClingApp)
        app.id = app_id
        app.path = os.path.dirname(package)
        app.problems = []
        app.kni = {}
        app.manifest = {}
        app.appid = ''
        app.version = ''
        app.author = ''
        app.status = 0
        app._names = {'': app_id}
        app._summaries = {'': ''}
        app.category = 'other'
        app.entry = ''
        app.engine = ENGINE_READER
        app.texts = None
        app.skin = None
        app.package = package
        app.locked = True
        apps.append(app)
    apps.sort(key=lambda app: (app.category, app.name(language).lower()))
    return apps
