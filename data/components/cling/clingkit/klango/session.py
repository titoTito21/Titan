# -*- coding: utf-8 -*-
"""One run of a Klango application's own code.

The bootstrap is Klango's own, read out of its library: an application's entry
file defines `main()`, `main` builds an app object with `k_NewApp()` - which is
`k_SUINewApp`, and is itself Lua, in `llib_suiapp.lua` - and then calls
`app:loop()`.  So there is nothing to invent here: load the library, load the
application, call `main`, and supply the primitives underneath.
"""

import os
import sys
import time
import traceback

from . import engine, environment, frames, keyboard, natives, titan_bridge
from .. import textio

#: Where Klango's platform library is unpacked to, when the user has it.
LIB_PACKAGE = 'llib'

#: A tree-walking interpreter spends several Python frames on every Lua one, and
#: Klango's library walks its application tree recursively - so Python's default
#: limit is reached while Lua is still only a few dozen calls deep. Raised for
#: the length of a run and put back afterwards, because it is not this
#: component's business to change it for the rest of Titan.
RECURSION_LIMIT = 20000

#: How deep Lua itself may go. Cling's own default is deliberately shallow - a
#: macro that recurses for ever must not take the desktop with it - but Klango's
#: library is a real program with a real call chain, and 190 frames is not
#: enough to get through its own startup.
LUA_DEPTH = 2000


class KlangoSession(object):
    """A Klango application, loaded on Cling's interpreter."""

    def __init__(self, host, lib_root=None, profile_root=''):
        from ..lua import LuaRuntime

        self.host = host
        #: Everywhere the application is, in the order it is looked in.
        #:
        #: An application is not always in ONE place. Its code arrives in its
        #: `.pag`; its folder in `data/cling/` may be an unpacked copy of the
        #: DATA only - which is exactly what the German distribution ships -
        #: and may have things the package has not: Typing Lessons keeps its
        #: code, texts and skin in `ktypist.pag` and its *lessons* in the
        #: folder beside it. Mounting one of the two answered "the collection
        #: is empty" and the application had nothing to teach. Klango sees one
        #: tree, and so does Cling: the package first, because that is where
        #: the code is, then the folder.
        self.app_roots = _code_roots(host.app)
        self.app_root = self.app_roots[0] if self.app_roots else host.app.path
        # `None` means "go and find it"; an empty string means "there is
        # none", which a caller who does not want 23 000 files unpacked
        # into a cache needs to be able to say.
        self.lib_root = find_library() if lib_root is None else lib_root
        self.loaded = []
        #: Files being run right now - `k_Run` is `dofile`, so the only thing
        #: it refuses is a file that is already running, which is a cycle.
        self.running = []
        self.problems = []
        #: The virtual directory of the file being run, so a bare `k_Run`
        #: finds the module beside its caller - which is how every one of
        #: Klango's own files asks for the next.
        self.where = ['/']
        #: Set by whoever is driving the session; `frames.Frames` raises
        #: `frames.Stopped` out of the next frame call when it is true.
        self.stopping = False
        #: True once the application really left, having been asked to.
        self.stopped = False
        self.traceback = ''
        self.runtime = LuaRuntime(self.app_root)
        self.filesystem = natives.Filesystem(
            self.app_roots, self.lib_root,
            profile_root or os.path.join(_state_root(), host.app.id))
        #: The keyboard the application polls. The driver - a window, an
        #: action, a test - presses keys on it from its own thread; the
        #: application takes a frame of them at the top of each of its own.
        self.keys = keyboard.Keyboard()
        host.klango_keys = self.keys
        # Klango finds applications by walking `/apps/<category>/<app>`, and
        # every category folder carries a `klangomenu_<lang>.txt` saying what
        # the category is called - the walk reads it and splits it, so a
        # category without one stops the whole tree. Cling has one category, so
        # it is made here, once, in the writable area.
        self.category_root = os.path.join(_state_root(), 'apps', 'cling')
        _write_category(self.category_root, host)
        self.filesystem.mount('/apps/cling', self.category_root)
        # `/common` is Klango's shared area: `/common/extras/<app>/` is where a
        # user's own replacement texts and skins go, and `/common/myklango/`
        # is what a branded installer leaves behind. Without the mount the
        # library reads a path that is nowhere, and its own handling of that
        # is not always right - `_k_GetMyKlangoOptions` compares
        # `k_TableSize(nil) > 0` and stops the application. So the folder is
        # real, in Cling's own writable area, and the configuration file is
        # there and EMPTY, which is what "no branded installer" is.
        self.common_root = os.path.join(_state_root(), 'common')
        _make_common(self.common_root)
        self.filesystem.mount('/common', self.common_root, writable=True)
        self.app_path = '/apps/cling/%s' % host.app.id
        self.filesystem.mount(self.app_path, self.app_roots)
        #: The clock the application's own loop runs on, and the one place
        #: `stopping` is acted on: `frames.Frames` raises out of `EndFrame`,
        #: which is inside `k_LoopWithRawInput` and outside every `pcall` the
        #: library uses.
        self.frames = frames.Frames(lambda: self.stopping,
                                    self.runtime.interpreter)
        natives.install(self.runtime, host, self.filesystem, self.run_file,
                        app_name=self.app_path.lstrip('/'),
                        frames=self.frames)
        engine.install(self.runtime, host, self.filesystem, self.keys,
                       frames=self.frames)
        self.runtime.set_global('_cling_trace', _trace)
        environment.install(self.runtime, self.run_file, self.problems.append)

    # ------------------------------------------------------------- loading
    def run_file(self, name=None, *_rest):
        """`k_Run` - run another Lua file. It is Klango's `_Sys_DoFile`.

        Klango's own files ask for each other by bare name (`k_Run("llib_files")`,
        `k_Run("level")`), so a name is looked for where the file asking for it
        lives FIRST, then beside the application, then in the library. Without
        the first of those the platform library cannot load its own modules,
        because every one of them is named without a path.

        Two things it is NOT, both of which stopped Mole No More the moment a
        game really started:

        - **it is not `require`.** `k_Run` is `dofile`: it runs the file again
          every time it is asked to, and it has to, because that is how an
          application loads its next level - `level.LoadFromFile` runs a `.lev`
          which sets a global `Level`, and a second level asked for once and
          answered "already loaded" is the first level played thirteen times.
          What is guarded against is a file running ITSELF, which is a loop
          Klango would not survive either.
        - **it is not only for `.lua`.** A `.lev` and a `.top` are Lua too, and
          appending `.lua` to a name that already has an extension is how
          `skin/default/levels/std_level_01.lev` came back "is not there".
        """
        wanted = str(name or '').replace('\\', '/')
        names = [wanted]
        if not wanted.lower().endswith('.lua'):
            names.append(wanted + '.lua')

        here = self.where[-1] if self.where else '/'
        candidates = []
        for shape in names:
            if not shape.startswith('/'):
                candidates.append(here.rstrip('/') + '/' + shape)
                candidates.append('/' + shape)
                candidates.append('/llib/' + shape)
            else:
                candidates.append(shape)
                candidates.append('/llib' + shape)

        real = ''
        virtual = ''
        for candidate in candidates:
            found = self.filesystem.resolve(candidate)
            if found and os.path.isfile(found):
                real, virtual = found, candidate
                break
        if not real:
            self.problems.append("k_Run: '%s' is not there" % name)
            return None
        if real in self.running:
            return True
        if real not in self.loaded:
            self.loaded.append(real)
        self.running.append(real)
        self.where.append(virtual.rsplit('/', 1)[0] or '/')
        try:
            self.run_source(real)
        except Exception as error:
            self.problems.append('%s: %s' % (os.path.basename(real), error))
            return None
        finally:
            self.where.pop()
            self.running.pop()
        return True

    def run_source(self, real):
        """Run a Lua file, with Cling's epilogue where one is wanted."""
        # Not every one of Klango's own files is UTF-8: eleven of the
        # library's 104 are Windows-1250, and a replacement character in the
        # SOURCE is a character the lexer refuses - `p_radiopresets.lua` does
        # not load at all that way. See `textio`.
        source = textio.read(real)
        if os.path.basename(real).lower() == 'llib.lua':
            source += '\n' + self.LIBRARY_EPILOGUE
        self.runtime.run(source, os.path.basename(real))

    def load_library(self):
        """Klango's own platform library, if the user has `llib`."""
        if not self.lib_root:
            self.problems.append(
                "Klango's platform library (llib) is not installed, so the "
                "application's own code has nothing to stand on")
            return False
        entry = os.path.join(self.lib_root, 'llib.lua')
        if not os.path.isfile(entry):
            self.problems.append('%s has no llib.lua' % self.lib_root)
            return False
        return bool(self.run_file('/llib/llib.lua'))

    #: Klango's own startup, in the order `___Klango_Main___` does it. The
    #: whole of that function also puts up Klango's shell - its application
    #: tree, its menus, its loop - which is the program Cling replaces; what
    #: is wanted is the part that makes the PLATFORM exist, and this is it.
    #: Appended to `llib.lua` as it is loaded - not written to the file.
    #:
    #: `_KlangoLang` and `_KlangoLang0` are locals of that file, assigned in
    #: exactly one place: a local function inside `___Klango_Main___`, which is
    #: Klango's whole shell. Cling wants the two lines, not the shell. A chunk's
    #: locals are visible to anything in the same chunk, so a function appended
    #: to it can set them - which is the smallest possible way to get the hook
    #: the library does not export.
    LIBRARY_EPILOGUE = """
        function _cling_set_klango_language( ms )
            if not ms then return false end
            _KlangoLang = ms.effectivelang
            if not _KlangoLang then return false end
            _KlangoLang0 = k_SplitStringBySep( _KlangoLang, "/" )[1]
            if _Sys_SetKlangoLanguage then
                _Sys_SetKlangoLanguage( _KlangoLang0 )
            end
            return true
        end
        function _cling_apps_tree() return _AppsTree end
        function _cling_klango_language() return _KlangoLang end

        --- The library's own mediaset, registered as THE one.
        ---
        --- `_k_GetGlobalMediaSet()` answers a file-local of `llib.lua` that
        --- only `___Klango_Main___` - Klango's whole shell - ever assigns.
        --- Every mediaset made after it reads that local to decide two
        --- things: whether it is the library's own, and where to copy
        --- `globalsnd` from. Left nil, an application's mediaset believes it
        --- IS the library, registers nothing, and `app.mediaset.globalsnd`
        --- is empty - so the first widget that reaches for one of the
        --- platform's own sounds indexes a nil and the application stops.
        --- (`app.mediaset.globalsnd.form.form_godown`, which is what the
        --- Wikipedia browser does the moment a search result is opened.)
        function _cling_set_global_mediaset( ms )
            _mediaset = ms
            return _mediaset ~= nil
        end

        --- Klango's tracing, made as cheap as what receives it.
        ---
        --- `llib_debug.lua` defines `pr` and `tpr` as
        --- `FormatElement(value, name, depth)` handed to `_DBG0` /
        --- `_Sys_TransientLog` - and in Cling both of those DISCARD what they
        --- are given, because there is no debug console and no crash-report
        --- buffer here. The formatting is not discarded, though: it is a
        --- recursive walk of whatever it was passed, written in Lua, run on
        --- Cling's interpreter. `mediaset:speech` calls `tpr(self.usetabs,
        --- ..., 33)` on every speech file it cannot find, and a Polish
        --- application misses 32 of the library's own - measured at **19.6
        --- seconds** of Dice Poker's startup, spent building strings that
        --- nothing then reads. `_cling_trace` is Cling's own, and it only
        --- looks at its argument when somebody has asked for the tracing.
        function k_Print( elem, name ) _cling_trace( elem, name ) end
        function k_Print0( elem, name ) _cling_trace( elem, name ) end
        function k_TPrint() end
        function k_TPrint0() end
        pr = k_Print
        pr0 = k_Print0
        tpr = k_TPrint
        tpr0 = k_TPrint0
    """

    PLATFORM = """
        __cling_platform_problems = {}
        local function step(name, fn, ...)
            if not fn then
                table.insert(__cling_platform_problems, name .. ": not there")
                return
            end
            local ok, err = pcall(fn, ...)
            if not ok then
                table.insert(__cling_platform_problems,
                             name .. ": " .. tostring(err))
            end
        end
        step("_k_SndINIT", _k_SndINIT)
        __cling_mediaset = k_MediaSetNew( nil, "/llib" )
        if _cling_set_klango_language then
            if not _cling_set_klango_language( __cling_mediaset ) then
                table.insert(__cling_platform_problems,
                             "the platform has no language")
            end
        end
        -- The widgets register their own sounds into it, and only then is it
        -- THE mediaset - an application's own copies `globalsnd` off it at
        -- the moment it is made, so registering it any earlier would hand
        -- out an empty one.
        step("_k_suiinit", _k_suiinit, __cling_mediaset)
        if _cling_set_global_mediaset then
            if not _cling_set_global_mediaset( __cling_mediaset ) then
                table.insert(__cling_platform_problems,
                             "the platform's own mediaset was not registered")
            end
        end
        step("_k_BuildAppsTree", _k_BuildAppsTree, __cling_mediaset)
        step("LLib_Time_Run", LLib_Time_Run)
        __cling_platform_ready = __cling_mediaset ~= nil
    """

    def start_platform(self):
        """Bring the platform up, the way Klango brings it up for an application.

        Without this the library has no mediaset of its own, so its own texts
        are never loaded and the first screen an application builds reads a nil
        - which is where every application stopped before this existed.
        """
        if not self.lib_root:
            return False
        try:
            self.runtime.run(self.PLATFORM, 'cling: klango platform')
        except Exception as error:
            self.problems.append('the platform did not start: %s' % error)
            return False
        found = self.runtime.get_global('__cling_platform_problems')
        if found is not None and hasattr(found, 'array'):
            for line in found.array():
                self.problems.append('platform: %s' % line)
        ready = self.runtime.get_global('__cling_platform_ready')
        if not ready:
            self.problems.append('the platform started without a mediaset')
        return bool(ready)

    def load_application(self):
        """The application's entry file - the one named after the application."""
        wanted = ['%s.lua' % self.host.app.id,
                  '%s.lua' % (self.host.app.kni.get('appname') or ''),
                  'main.lua', 'game.lua']
        for candidate in wanted:
            if candidate == '.lua':
                continue
            if self.filesystem.resolve('/' + candidate):
                return bool(self.run_file('/' + candidate))
        # Klango applications do not all name their entry after themselves -
        # Long Jump's is `lj.lua`. When there is exactly one script at the
        # root, that is the application; more than one and Cling says so
        # rather than picking.
        scripts = [name for name in self.filesystem.listdir('/')
                   if name.lower().endswith('.lua')]
        if len(scripts) == 1:
            return bool(self.run_file('/' + scripts[0]))
        if scripts:
            self.problems.append('several scripts at the root and none named '
                                 'after the application: %s' % ', '.join(scripts))
        else:
            self.problems.append('no entry file: expected %s.lua'
                                 % self.host.app.id)
        return False

    def start(self):
        """Load everything and call `main()`. Returns True when it ran."""
        previous = sys.getrecursionlimit()
        sys.setrecursionlimit(max(previous, RECURSION_LIMIT))
        if self.runtime.interpreter is not None:
            self.runtime.interpreter.max_depth = LUA_DEPTH
        try:
            if self.load_library():
                # Klango's own Settings and Help are Titan's here - see
                # `titan_bridge.py`. It is installed once the library has
                # defined `k_NewApp` and before any application has called it.
                titan_bridge.install(self.runtime, self.host)
            self.start_platform()
            if not self.load_application():
                return False
            if not self.runtime.has_global('main'):
                self.problems.append("the application defines no main()")
                return False
            try:
                self.runtime.call_global('main')
                return True
            except frames.Stopped:
                # The window was closed, or Titan is going away. The
                # application did not fail; it was stopped, which is what
                # leaving a game means.
                self.stopped = True
                return True
            except Exception as error:
                self.problems.append('main(): %s' % error)
                self.traceback = traceback.format_exc()
                return False
        finally:
            sys.setrecursionlimit(previous)

    # -------------------------------------------------------------- input
    def press(self, name):
        """Give the running application a key: down now, up next frame."""
        return self.keys.press(name)

    def key_down(self, name):
        return self.keys.down(name)

    def key_up(self, name):
        return self.keys.up(name)

    # ------------------------------------------------------------ reading

    def report(self):
        """What happened, in the order it would be useful to read."""
        lines = list(self.problems)
        if natives.MISSING:
            lines.append('primitives an application asked for and Cling has '
                         'not written: ' +
                         ', '.join('%s (%d)' % (name, count) for name, count
                                   in sorted(natives.MISSING.items())))
        return lines


def find_library(roots=None):
    """Where Klango's `llib` is unpacked, or ''.

    It arrives the same way an application does - as `llib.pag` - and is
    mounted rather than listed, because it is the runtime and not something
    to play.

    **Cling ships it**, in the component's own `apps/`, which is the last
    place looked in. Everything else about Cling lives inside the component
    already; the library did not, so the whole emulator - seventeen of the
    twenty-one installed applications - worked only on a machine that
    happened to have a Klango installation, and on this one it worked only
    because a copy had been unpacked into a build directory. A subsystem
    whose central claim is "your Klango applications run here" cannot depend
    on the user having Klango.

    The user's own `data/cling/` is still looked in FIRST, so somebody with
    a newer or a patched library keeps theirs.
    """
    from .. import catalog, pag

    if roots is None:
        try:
            from src.platform_utils import iter_data_roots
            roots = list(iter_data_roots(catalog.DATA_SUBDIR))
        except Exception:
            roots = [catalog.user_apps_dir()]
        roots = list(roots) + [catalog.component_apps_dir()]
    for root in roots:
        folder = os.path.join(root, LIB_PACKAGE)
        if os.path.isfile(os.path.join(folder, 'llib.lua')):
            return folder
        package = os.path.join(root, LIB_PACKAGE + '.pag')
        if os.path.isfile(package):
            try:
                return pag.mount(package)
            except Exception as error:
                print('[cling/klango] %s could not be opened: %s'
                      % (package, error))
    return ''


def _write_category(folder, host):
    """The category file Klango's tree walk expects beside its applications."""
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        return
    locale = (host.texts.locale if host.texts else '') or 'en-us'
    language = locale.split('-')[0]
    for name in ('klangomenu_%s.txt' % language, 'klangomenu_en.txt',
                 'klangomenu.txt'):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            continue
        try:
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write('Cling\n')
        except OSError:
            return


def _code_roots(app):
    """Everywhere the application is: its package and its folder, in order.

    The package comes first because that is where its code is, and because a
    folder in `data/cling/` is very often an unpacked copy of the DATA alone.
    The folder comes second and is not optional: it is where the user's own
    additions live, and where several applications keep whole parts of
    themselves that never went into the package.
    """
    roots = []
    package = getattr(app, 'package', '')
    if package and os.path.isfile(package):
        try:
            from .. import pag
            folder = pag.mount(package)
            for _root, _dirs, names in os.walk(folder):
                if any(n.lower().endswith('.lua') for n in names):
                    roots.append(folder)
                    break
        except Exception as error:
            print('[cling/klango] %s could not be opened: %s' % (package, error))
    if app.path and app.path not in roots and os.path.isdir(app.path):
        roots.append(app.path)
    return roots or [app.path]


def _state_root():
    try:
        from src.platform_utils import get_user_resource_path
        return get_user_resource_path(os.path.join('cling', 'klango'))
    except Exception:
        return os.path.join(os.path.expanduser('~'), '.cling', 'klango')


def boot(host, lib_root=None):
    """Load and start an application's own Klango code. Never raises."""
    session = KlangoSession(host, lib_root)
    started = session.start()
    return session, started


#: Set `CLING_TRACE=1` to see what an emulated application's own `pr(...)`
#: says. Off, it costs one comparison per call; on, it is the only window
#: there is into somebody else's Lua.
TRACING = bool(os.environ.get('CLING_TRACE'))


def _trace(value=None, name=None, *_rest):
    if not TRACING:
        return None
    try:
        print('[cling/klango] %s%s' % ('%s = ' % name if name else '', value))
    except Exception:
        pass
    return None


def _make_common(folder):
    """Klango's `/common`, with the one file the library reads before it exists.

    `_k_GetMyKlangoOptions` reads `/common/myklango/myklango.cfg` and then
    asks `k_TableSize(...) > 0` about the answer - which is nil when the file
    is not there, and comparing nil with a number ends the application. An
    empty file is the honest answer: there is no branded installer here.
    """
    try:
        os.makedirs(os.path.join(folder, 'myklango'), exist_ok=True)
        os.makedirs(os.path.join(folder, 'extras'), exist_ok=True)
    except OSError:
        return
    config = os.path.join(folder, 'myklango', 'myklango.cfg')
    if not os.path.isfile(config):
        try:
            with open(config, 'w', encoding='utf-8') as handle:
                handle.write('')
        except OSError:
            pass
