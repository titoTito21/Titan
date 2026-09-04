# -*- coding: utf-8 -*-
"""The primitives Klango's Lua stands on, implemented over Cling's host.

Everything here is a function the platform library calls and cannot write for
itself: the file system it is allowed to see, the clock, the random source, the
sound, the keyboard.  Nothing here is a guess about what Klango meant - each
one was found by reading the extracted library, and one that has not been
written yet is recorded in `MISSING` when it is called rather than silently
answering nil, because an application that half-runs is worse than one that
says what it needs.

The file system is the application's own folder and `llib`, and nothing else:
this is somebody else's code, run on a blind user's desktop.
"""

import hashlib
import os
import random
import time

#: Names an application asked for that Cling has not implemented. A set rather
#: than a failure: the point is to finish the run and report the whole list.
MISSING = {}

#: 'this path has never been looked for', which is not the same as ''.
_UNKNOWN = object()


def _textio():
    from .. import textio
    return textio


def _write_lua(value, seen, depth=0):
    """A Lua value as the text Lua would write for it."""
    from ..lua.runtime import LuaTable

    if value is None:
        return 'nil'
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if isinstance(value, (int, float)):
        text = repr(value)
        return text[:-2] if text.endswith('.0') else text
    if isinstance(value, str):
        return '"%s"' % value.replace('\\', '\\\\').replace('"', '\\"') \
            .replace('\n', '\\n').replace('\r', '\\r')
    if isinstance(value, LuaTable):
        if id(value) in seen or depth > 30:
            return 'nil'          # a table that contains itself is not a file
        seen = seen | {id(value)}
        pieces = []
        length = value.length()
        for index in range(1, length + 1):
            pieces.append(_write_lua(value.raw_get(index), seen, depth + 1))
        for key in value.keys():
            if isinstance(key, int) and 1 <= key <= length:
                continue
            written = _write_lua(value.raw_get(key), seen, depth + 1)
            if isinstance(key, str) and key.isidentifier():
                pieces.append('%s=%s' % (key, written))
            else:
                pieces.append('[%s]=%s' % (_write_lua(key, seen, depth + 1),
                                           written))
        return '{' + ','.join(pieces) + '}'
    return 'nil'


def _mkdir(filesystem, path):
    real = filesystem.resolve(path, for_writing=True)
    if not real:
        return False
    try:
        os.makedirs(real, exist_ok=True)
        return True
    except OSError:
        return False


def _sound_name(spec):
    """A sound is named directly, or by a table the application built."""
    if isinstance(spec, str):
        return spec
    if hasattr(spec, 'raw_get'):
        for key in ('name', 'file', '___name', 1):
            value = spec.raw_get(key)
            if isinstance(value, str):
                return value
    return str(spec or '')


def _record(name):
    MISSING[name] = MISSING.get(name, 0) + 1
    return None


class Filesystem(object):
    """Klango's virtual file system: mount points, not a search path.

    This is not a detail. Klango gives its platform library its own mediaset
    rooted at **`/llib`** (`llib.lua` line 1071) and the application one rooted
    at the current directory, and both then read `lang/` and `skin/` beneath
    themselves. With a search path - try the application, then the library -
    the library asks for its own texts and is handed the application's, and
    every application dies in the same place with `_txt.___txt` nil.

    So paths resolve through a mount table, longest prefix first:

        /llib   the platform library, read-only
        /user   the application's own writable folder
        /       the application

    Anything outside every mount does not exist. A package came from wherever
    the user found it, and this is the one place that is decided.

    **A mount can be more than one real folder**, tried in order and listed
    together. An application is not always in one place: Typing Lessons ships
    its code, its texts and its skin in `ktypist.pag` and its *lessons* in the
    folder beside it, so an emulator that mounted only the package answered
    "the collection is empty" and the application had nothing to teach. Klango
    sees one tree; so does this.
    """

    def __init__(self, app_root, lib_root, writable):
        self.mounts = []
        #: Paths already looked for. See `resolve`.
        self._known = {}
        self.writable = os.path.abspath(writable)
        os.makedirs(self.writable, exist_ok=True)
        self.mount('/user', self.writable, writable=True)
        if lib_root:
            self.mount('/llib', lib_root)
        self.mount('/', app_root)
        roots = self._roots(app_root)
        self.app_root = roots[0] if roots else ''
        self.lib_root = os.path.abspath(lib_root) if lib_root else ''

    @staticmethod
    def _roots(real):
        """One folder or several, as a list of real paths that exist."""
        if isinstance(real, (list, tuple)):
            wanted = list(real)
        else:
            wanted = [real]
        out = []
        for path in wanted:
            if not path:
                continue
            full = os.path.abspath(path)
            if full not in out:
                out.append(full)
        return out

    def mount(self, point, real, writable=False):
        """Put a real folder - or several - at a virtual path.

        Longest prefix wins between mounts; within one mount the roots are
        tried in the order they were given, so the first that has the file is
        the one that answers.
        """
        cleaned = '/' + str(point or '').strip('/')
        roots = self._roots(real)
        if not roots:
            return False
        self.mounts.append((cleaned, roots, writable))
        self.mounts.sort(key=lambda entry: -len(entry[0]))
        return True

    def _split(self, path):
        cleaned = '/' + str(path or '').replace('\\', '/').strip('/')
        while '//' in cleaned:
            cleaned = cleaned.replace('//', '/')
        for point, roots, writable in self.mounts:
            if point == '/':
                return roots, cleaned.lstrip('/'), writable
            if cleaned == point or cleaned.startswith(point + '/'):
                return roots, cleaned[len(point):].lstrip('/'), writable
        return [], '', False

    def resolve(self, path, for_writing=False):
        """A Klango path as a real one, or '' when it is nowhere it may be.

        The answer is remembered. Klango's mediaset resolves a name by asking
        whether it exists with each of five extensions in each of two
        directories, and `_k_Background_Run` does that once a FRAME - which
        on a real file system is sixty round trips a second for an answer
        that cannot have changed. Writing clears what was remembered, which
        is the only way it can change.
        """
        if not for_writing:
            key = str(path or '')
            found = self._known.get(key, _UNKNOWN)
            if found is not _UNKNOWN:
                return found
        roots, relative, mount_is_writable = self._split(path)
        if not roots:
            return ''
        if for_writing and not mount_is_writable:
            # Writing always lands in the application's own folder, whatever
            # the path says: the library and the application's package are the
            # user's copies of somebody else's work.
            roots, relative = [self.writable], self._flatten(path)
        answer = ''
        for root in roots:
            candidate = os.path.abspath(os.path.join(root, relative)) \
                if relative else os.path.abspath(root)
            try:
                inside = os.path.commonpath([root, candidate]) == root
            except ValueError:
                inside = False
            if not inside:
                continue
            if for_writing or os.path.exists(candidate):
                answer = candidate
                break
        if for_writing:
            # Something is about to appear where there was nothing, so what
            # was remembered about that path - and about the folder holding
            # it - is no longer true.
            self._known.clear()
        else:
            self._known[str(path or '')] = answer
        return answer

    def listdir(self, path):
        """What is in a virtual folder: the real files, plus any mount below it.

        A mount point has to appear in its parent's listing or nothing can walk
        to it - Klango finds its applications by walking `/apps`, and an
        application mounted there that the walk cannot see is an application
        that does not exist.
        """
        names = []
        roots, relative, _writable = self._split(path)
        for root in roots:
            real = os.path.abspath(os.path.join(root, relative)) if relative \
                else os.path.abspath(root)
            if not os.path.isdir(real):
                continue
            try:
                for name in os.listdir(real):
                    if name not in names:
                        names.append(name)
            except OSError:
                continue
        prefix = '/' + str(path or '').replace('\\', '/').strip('/')
        prefix = '/' if prefix == '/' else prefix
        for point, _roots, _writable in self.mounts:
            if point == '/' or not point.startswith(prefix):
                continue
            rest = point[len(prefix):].lstrip('/')
            if not rest:
                continue
            head = rest.split('/')[0]
            if head and head not in names:
                names.append(head)
        return sorted(names)

    def is_directory(self, path):
        real = self.resolve(path)
        if real and os.path.isdir(real):
            return True
        prefix = '/' + str(path or '').replace('\\', '/').strip('/')
        return any(point == prefix or point.startswith(prefix + '/')
                   for point, _r, _w in self.mounts if point != '/')

    @staticmethod
    def _flatten(path):
        return '/'.join(part for part in
                        str(path or '').replace('\\', '/').split('/')
                        if part and part not in ('.', '..'))


def install(runtime, host, filesystem, loader, app_name='', frames=None):
    """Put the primitives into a Lua runtime. `loader` runs another Lua file."""
    from .frames import Frames

    table = runtime.table
    give = runtime.set_global
    generator = random.Random()
    if frames is None:
        frames = Frames()
    _install_safety_net(runtime)

    # --------------------------------------------------------------- files
    def read_text(path=None, *_rest):
        """`k_ReadFile` - and it is most of what an application SAYS.

        Decoded by `textio`, because a Klango text file is UTF-8 or it is the
        code page Klango was written on, and reading the second as the first
        puts a hole where every Polish letter was.
        """
        real = filesystem.resolve(path)
        if not real or not os.path.isfile(real):
            return None
        return _textio().read_or_none(real)

    def write_text(path=None, text=None, *_rest):
        real = filesystem.resolve(path, for_writing=True)
        if not real:
            return False
        try:
            os.makedirs(os.path.dirname(real), exist_ok=True)
            with open(real, 'w', encoding='utf-8') as handle:
                handle.write('' if text is None else str(text))
            return True
        except OSError:
            return False

    def file_exists(path=None, *_rest):
        return bool(filesystem.resolve(path))

    def delete_file(path=None, *_rest):
        real = filesystem.resolve(path, for_writing=True)
        try:
            os.remove(real)
            return True
        except OSError:
            return False

    def has_ext(path=None, ext=None, *_rest):
        return str(path or '').lower().endswith('.' + str(ext or '').lower())

    def cut_ext(path=None, *_rest):
        return os.path.splitext(str(path or ''))[0]

    give('_Sys_ReadTextFile', read_text)
    give('_Sys_WriteTextFile', write_text)
    give('_Sys_FileExists', file_exists)
    give('_Sys_DeleteFile', delete_file)
    give('_Sys_FileHasExt', has_ext)
    give('_Sys_FileCutExt', cut_ext)
    give('_Sys_LoadFile', read_text)
    give('_Sys_DoFile', loader)
    give('_Sys_PathIsAtFixedDrive', lambda *_a: True)

    def mount(point=None, package=None, *_rest):
        """Put a package's contents at a virtual path.

        Called with a package, this really mounts it - a `.pag` is unpacked
        into the runtime cache and appears at that path, which is how Klango
        composes an installation out of packages. Called with only a path (the
        library does this for `/apps`), everything Cling has is already
        mounted, so there is nothing to do and saying so is the honest answer.
        """
        if not package:
            return True
        real = filesystem.resolve(package)
        if not real or not os.path.isfile(real):
            return False
        try:
            from .. import pag
            folder = pag.mount(real)
        except Exception as error:
            print('[cling/klango] %s could not be mounted: %s' % (package, error))
            return False
        return filesystem.mount(str(point or '/'), folder)

    give('_Sys_Mount', mount)
    give('k_Mount', mount)
    give('k_MountEx', mount)
    give('_Sys_Unmount', lambda *_a: True)
    give('k_Unmount', lambda *_a: True)
    give('k_UmountEx', lambda *_a: True)
    give('k_CopySoundFileToCommonFileCache', lambda name=None, *_a: name)
    give('_Sys_SetPkgPrio', lambda *_a: True)
    give('_Sys_PathOfOldKlango', lambda *_a: '')

    # ----------------------------------------------------------- the clock
    give('_Sys_GetGlobalTime', lambda *_a: host.now())
    give('_Sys_GetSystemDateTime', lambda *_a: int(time.time()))
    # `k_GetUnixTimestamp` is another of Klango's engine functions with no
    # `_Sys_` prefix - the OAuth signing and the storage expiry both use it,
    # and Shopping with Klango stops on it.
    give('k_GetUnixTimestamp', lambda *_a: int(time.time()))
    give('k_GetUnixTime', lambda *_a: int(time.time()))
    give('_Sys_GetFPS', lambda *_a: int(frames.RATE))
    def random_number(first=None, second=None, *_rest):
        """`_Sys_Random` - and `llib_math.lua` makes it `math.random` itself.

        So it takes Lua's arguments, not its own: none is a float in [0, 1),
        ONE is an integer in [1, m], and two are [a, b]. Reading one argument
        as "from m to m" - which is what this did - means `math.random(5)`
        answers 5 every single time, and a program that draws until it gets
        something it has never gets it.

        That is not a subtle wrongness. Dice Poker picks which of its
        recorded shake sounds to play with `math.random(5)` and loops until
        the one it drew exists; with only `shake5_1` and `shake5_2` on disk
        it looped for ever and the game froze on its first roll. Every other
        application is as random as this is: where a mole appears, where a
        clay pigeon flies, how a board is shuffled.
        """
        if first is None:
            return generator.random()
        low = 1 if second is None else int(_number(first))
        high = int(_number(first)) if second is None else int(_number(second))
        if low > high:
            low, high = high, low
        return generator.randint(low, high)

    give('_Sys_Random', random_number)
    give('_Sys_RandomSeed', lambda seed=None, *_a: generator.seed(
        int(_number(seed)) if seed is not None else None))

    # ---------------------------------------------------------- the frame
    # Klango draws; Cling does not. A frame is where the platform yields, so
    # these are what let its main loop run at all - they are not a stub for
    # graphics, they ARE the whole of what a frame means without a screen:
    # the pace the application runs at, and the one place it can be stopped
    # from outside. See `frames.py`.
    give('_Sys_BeginFrame', lambda *_a: frames.begin())
    give('_Sys_EndFrame', lambda *_a: frames.end())
    give('_Sys_EndFrameNoDelay', lambda *_a: frames.end(immediately=True))
    give('_Sys_IsVisible', lambda *_a: True)
    give('_Sys_ShowWin', lambda *_a: True)
    give('_Sys_ActivateAndShowWin', lambda *_a: True)
    give('_Sys_SetWindowTitle', lambda *_a: True)
    give('_Sys_SwitchToWindow', lambda *_a: True)
    give('_Sys_InternalSwitch', lambda *_a: True)
    give('_Sys_OnFirstFrameKill', lambda *_a: True)

    # --------------------------------------------------------- the account
    # Klango asked for a Klango account; the user has a Titan-Net one.
    give('_Sys_SetUser', lambda *_a: True)
    give('_Sys_ValidateKlangoID', lambda *_a: True)
    # Klango names an application by WHERE IT IS, not by its bare name: the
    # applications tree calls ours `apps/cling/mole*en-us/default`, and
    # `_k_GetAppName()` is `_Sys_GetAppName() .. "*" .. lang`. Answering just
    # `mole` therefore made the application unable to find itself in Klango's
    # own catalogue - which is what `_Sys_PrepAppLaunch` sets up in Klango.
    give('_Sys_GetAppName', lambda *_a: app_name or host.app.id)
    give('_Sys_SetKlangoVersion', lambda *_a: True)
    give('_Sys_SetKlangoLanguage', lambda *_a: True)

    # ------------------------------------------------------------- strings
    give('_Sys_Digest', lambda text=None, *_a:
         hashlib.md5(str(text or '').encode('utf-8')).hexdigest())
    give('_Sys_LocalToUtf8', lambda text=None, *_a: str(text or ''))

    # ------------------------------------------------- what a character is
    # `k_CharIs("ctrl", char)` is how the text editor tells a control
    # character from something to type, and `k_CharTo` is how it upper-cases
    # one. Both are the C runtime's, per locale; Python's own string methods
    # already know every alphabet, so they are the answer here.
    CHARACTER_TESTS = {
        'upper': lambda c: c.isupper(),
        'lower': lambda c: c.islower(),
        'digit': lambda c: c.isdigit(),
        'xdigit': lambda c: c in '0123456789abcdefABCDEF',
        'space': lambda c: c.isspace(),
        'alpha': lambda c: c.isalpha(),
        'alphanum': lambda c: c.isalnum(),
        'punct': lambda c: (not c.isalnum() and not c.isspace()
                            and c >= ' '),
        'ctrl': lambda c: c < ' ' or c == '\x7f',
    }

    def character_is(what=None, text=None, *_rest):
        test = CHARACTER_TESTS.get(str(what or '').lower())
        value = str(text or '')
        if test is None or not value:
            return False
        return all(test(character) for character in value)

    def character_to(what=None, text=None, *_rest):
        value = str(text or '')
        return value.upper() if str(what or '').lower() == 'upper' \
            else value.lower()

    give('_Sys_CharIs_', character_is)
    give('_Sys_CharTo_', character_to)

    # `urlencode` is one of Klango's engine functions that has no `_Sys_`
    # prefix: the library calls it (`llib.lua` builds a query string with it)
    # and never defines it, and so does every application that fetches a
    # page - the Wikipedia browser stops on it the moment a search is typed.
    #
    # **A space is `%20`, not `+`.** PHP's `urlencode` writes `+`, and the far
    # end of every URL Klango itself built was PHP, so `+` looked right - but
    # what an APPLICATION builds with it is a PATH, and in a path `+` is a
    # literal plus sign. The Wikipedia browser encodes the article's title
    # into `/wiki/<title>`, takes it back out again and asks for
    # `Special:Export/<title>`, escaping any `+` it finds to `%2B` on the way
    # (`downloadPage`, `object.lua`) - so with `+` for a space, every article
    # whose title is more than one word was fetched as a title with a plus
    # sign in it. Measured on `pl.wikipedia.org`: `Kot%2Bdomowy` answers 200
    # with no `<text>` element in it at all, which the browser reads as "the
    # page does not exist" and says so, having just found and offered the
    # article. `%20` is right in a query string too - it is what every server
    # PHP was talking to accepts - so this is `rawurlencode`, RFC 3986, which
    # is one answer for both places instead of one that is only ever right in
    # one of them.
    def url_encode(text=None, *_rest):
        from urllib.parse import quote
        return quote(str(text or ''), safe='', encoding='utf-8',
                     errors='replace')

    def url_decode(text=None, *_rest):
        from urllib.parse import unquote_plus
        return unquote_plus(str(text or ''), encoding='utf-8', errors='replace')

    give('urlencode', url_encode)
    give('urldecode', url_decode)
    give('k_UrlEncode', url_encode)
    give('k_UrlDecode', url_decode)
    give('_Sys_CompareString', lambda a=None, b=None, *_r:
         (str(a or '') > str(b or '')) - (str(a or '') < str(b or '')))
    give('_Sys_TransientLog', lambda *_a: True)

    # ---------------------------------------------- deliberately refused
    # Starting a program, killing the engine and talking to other Klango
    # windows are the three things a package from the internet must not do on
    # somebody else's desktop.
    for name in ('_Sys_Execute', '_Sys_ShellOpen', '_Sys_KillEngine',
                 '_Sys_PrepAppLaunch'):
        give(name, (lambda n: (lambda *_a: _record(n)))(name))

    # Klango's daemon mode put an icon in the notification area and took
    # SYSTEM-WIDE hotkeys, each carrying a string of Lua to run when it fires
    # (`k_DaemonRegHotKey(350, 8, 13, "_SSList()")` - that is Windows+Enter,
    # for the whole desktop). Titan owns the desktop's shortcuts, and a
    # package from the internet does not get to take one, still less to leave
    # a string behind to be run later. Refused - and recorded, so the report
    # says what an application asked for - but the call still ANSWERS, because
    # Zawisza Czarny registers its hotkeys before it plays a single sound and
    # a nil there ended the application on its first screen.
    for name in ('k_DaemonRegHotKey', 'k_DaemonUnregHotKey',
                 'k_DaemonSetTrayIcon', 'k_DaemonSetTrayMenu'):
        give(name, (lambda n: (lambda *_a: _record(n) or True))(name))
    give('k_DaemonHasTrayIcon', lambda *_a: False)

    # Talking to other Klango windows is refused too, but the answer has to be
    # the SHAPE the library expects - "there are no other windows" - not nil.
    # A refusal that answers nil is a refusal the caller then tries to iterate.
    give('_Sys_Ipc_GetKlangoWindows', lambda *_a: table({}))
    give('_Sys_Ipc_GetMyWindow', lambda *_a: 0)
    give('_Sys_Ipc_SendMessage', lambda *_a: False)
    give('_Sys_Ipc_EnableProcessing', lambda *_a: True)

    # -------------------------------------------------- the global store
    globals_store = {}
    # A key nobody has set answers NIL, not an empty string. In Lua every
    # string is true, including the empty one, so answering '' made the
    # library take "there is no override" for "the override is nothing" and
    # overwrite the application's language and skin with it.
    give('_Sys_GlobalString_Get',
         lambda key=None, *_a: globals_store.get(str(key or '')) or None)
    give('_Sys_GlobalString_Set',
         lambda key=None, value=None, *_a: globals_store.__setitem__(
             str(key or ''), str(value or '')))

    # ------------------------------------------------------------- sqlite
    # Klango gives an application a database; Python has the same one. Only
    # the application's own writable folder is reachable, so a package cannot
    # open a database belonging to anything else.
    def new_sqlite(path=None, *_rest):
        import sqlite3

        real = filesystem.resolve(path or 'data.sdb', for_writing=True)
        if not real:
            return None
        os.makedirs(os.path.dirname(real), exist_ok=True)
        connection = sqlite3.connect(real)
        handle = table({})

        def rows_of(cursor):
            """Klango reads a row by COLUMN NAME (`tmp[1].m`), so the rows come
            back keyed both ways - by name and by position."""
            names = [column[0] for column in (cursor.description or [])]
            rows = table({})
            for index, row in enumerate(cursor.fetchall(), start=1):
                line = table({})
                for position, value in enumerate(row, start=1):
                    line.raw_set(position, value)
                    if position <= len(names):
                        line.raw_set(names[position - 1], value)
                rows.raw_set(index, line)
            return rows

        def execute(_self=None, sql=None, *arguments):
            try:
                cursor = connection.execute(str(sql or ''),
                                            [a for a in arguments
                                             if a is not None])
                connection.commit()
            except Exception as error:
                _record('sqlite: %s' % error)
                return table({})
            return rows_of(cursor)

        def prepare(_self=None, sql=None, *_a):
            statement = table({})
            statement.raw_set('sql', str(sql or ''))
            statement.raw_set('Exec', lambda _s=None, *args: execute(
                None, str(sql or ''), *args))
            return statement

        for name in ('Exec', 'exec', 'execute'):
            handle.raw_set(name, execute)
        handle.raw_set('Prepare', prepare)
        handle.raw_set('Close', lambda *_a: connection.close())
        handle.raw_set('close', lambda *_a: connection.close())
        return handle

    give('k_NewSqlite', new_sqlite)

    # -------------------------------------------------------- the folder
    def directory_read(path=None, recursive=None, *_rest):
        """`k_DirectoryRead` - what a game reads its levels with."""
        real = filesystem.resolve(path)
        listing = table({})
        if not real or not os.path.isdir(real):
            return listing
        index = 1
        for leaf in sorted(os.listdir(real)):
            full = os.path.join(real, leaf)
            entry = table({})
            stem, extension = os.path.splitext(leaf)
            entry.raw_set('name', leaf)
            entry.raw_set('path', str(path).rstrip('/') + '/' + leaf)
            entry.raw_set('dir', os.path.isdir(full))
            entry.raw_set('ext', extension[1:].lower())
            entry.raw_set('size', 0 if os.path.isdir(full)
                          else os.path.getsize(full))
            listing.raw_set(index, entry)
            index += 1
        return listing

    give('k_DirectoryRead', directory_read)
    # The library builds paths as `k_GetCWD() .. "/" .. ...`, so an
    # answer of '/' makes every path start with two slashes.
    give('k_GetCWD', lambda *_a: '')
    give('k_MkDir', lambda path=None, *_a: _mkdir(filesystem, path))

    # ---------------------------------------------------------- the player
    # Klango asked for a Klango account; the user has a Titan-Net one, and it
    # is the same answer everywhere else in Cling.
    give('k_GetUser', lambda *_a: host.whoami().name)
    give('k_GetUserName', lambda *_a: host.whoami().display_name)
    give('k_Print', lambda *values: print('[klango] %s' % ' '.join(
        '' if v is None else str(v) for v in values)))
    give('k_Print0', lambda *values: None)
    give('k_Time', lambda *_a: host.now())
    give('k_GetLangName', lambda *_a: host.locale)

    # ------------------------------------------------------------- sound
    # This is where an emulated application meets the same mixer every other
    # part of Cling uses: the skin first, then the user's Titan sound theme,
    # placed whatever their stereo preference says.
    playing = {}
    counter = [0]

    def sound_play(name=None, *arguments):
        position = 0.0
        for value in arguments:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                position = max(-1.0, min(1.0, float(value)))
                break
        return host.play(_sound_name(name), position)

    def background_prepare(spec=None, *_a):
        counter[0] += 1
        name = _sound_name(spec)
        playing[counter[0]] = ('prepared', name)
        return counter[0]

    def background_play(handle=None, *_a):
        entry = playing.get(int(handle or 0))
        if not entry:
            return False
        started = host.loop(entry[1], 0.0, 0.5)
        playing[int(handle)] = ('playing', entry[1], started)
        return started is not None

    def background_stop(handle=None, *_a):
        entry = playing.pop(int(handle or 0), None)
        if entry and len(entry) > 2:
            host.stop_sound(entry[2])
        return True

    give('k_SoundPlay', sound_play)
    give('k_SoundPlayTheme', sound_play)
    give('k_SoundStop', lambda *_a: host.stop_sounds())
    give('k_SoundIsPlaying', lambda *_a: False)
    give('k_BackgroundPrepare', background_prepare)
    give('k_BackgroundPlay', background_play)
    give('k_BackgroundStop', background_stop)
    give('k_VoiceSpeak', lambda text=None, *_a: host.say(str(text or '')))

    # ---------------------------------------------------------- the keys
    # A key reaches an application the way Klango delivered one: it asks. The
    # queue is filled by whatever is driving the session - a window, or a test.
    keys = host.klango_keys if hasattr(host, 'klango_keys') else []

    def key_just_pressed(name=None, *_a):
        wanted = str(name or '').lower()
        for index, pressed in enumerate(keys):
            if pressed == wanted:
                keys.pop(index)
                return True
        return False

    give('k_KeyJustPressed', key_just_pressed)
    give('k_KeyIsPressed', lambda name=None, *_a: str(name or '').lower() in keys)
    give('k_Wait', lambda *_a: True)
    give('k_CollectGarbage', lambda *_a: True)

    # ------------------------------------------------------- saving a table
    # Klango stores settings and saved games as serialised Lua tables. The
    # writer produces the literal syntax Lua itself would; the reader is the
    # one Cling already has for `.lev` and `.top` files - it parses that syntax
    # as DATA and will not run it, which matters when the text came out of a
    # file the application wrote and something else may have edited.
    def serialise(value=None, *_rest):
        return _write_lua(value, set())

    def unserialise(text=None, *_rest):
        from . import lua_data
        return lua_data.read(str(text or ''), table)

    give('k_Serialize', serialise)
    give('k_Unserialize', unserialise)

    # ------------------------------------------------- Klango's own guards
    # `__PecuniaNonOlet` is Klango's anti-tamper check, deliberately given a
    # name that says nothing. It answers "this is fine": Cling is running an
    # application the user already has, on a platform whose author stopped
    # selling it years ago, and a licence server that no longer exists cannot
    # say yes.
    give('__PecuniaNonOlet', lambda *_a: True)
    give('k_SetDaemonMode', lambda *_a: True)
    give('k_KlangoShop', lambda *_a: False)
    give('k_GetInstallInfo', lambda *_a: table({}))

    # The `k_AA_*` family is the same guard one level down - Klango's
    # anti-abuse, which tied an application to the machine it was activated
    # on. `k_AA_DriveID` is the only one with an answer worth giving: it is
    # the machine's identity, sent with every session call, and the library
    # concatenates it - so it must be a real string and it must be the SAME
    # string on every run, or the server would see a new machine each time.
    def drive_id(*_arguments):
        return _drive_id()

    give('k_AA_DriveID', drive_id)
    give('k_AA_IsActivated', lambda *_a: True)
    give('k_AA_IsOnlineKey', lambda *_a: False)
    give('k_AA_TryReg', lambda *_a: None)

    # --------------------------------------------------------------- KRPC
    # klango.net, answered inside Cling - see `appsession.py`. It is one
    # server for the whole session, because a session is what it is about:
    # asking twice for the same application really is a second instance.
    from . import appsession
    session_server = appsession.AppSessionServer(host)
    host.klango_session_server = session_server

    # Klango applications call home over KRPC - high scores, chat, the shop.
    # klango.net has been gone for years, so a call cannot succeed; what it
    # must not do is answer nil, because the caller immediately asks the
    # answer whether it is `done()`. So there is a real object that says the
    # request finished and produced nothing, which is what "no server" means.
    def new_krpc(_spec=None, *_rest):
        """Klango's RPC, answered by Titan-Net where the call has a meaning here.

        Applications call home over KRPC: high scores, sessions, the shop.
        klango.net has been gone for years, so those calls cannot reach what
        they were written for - but the user has a Titan-Net account, and a
        high score is a high score. So `SendHS`/`GetHS` and their spellings go
        to Cling's own Titan-Net scoreboard, the same one its engines use, and
        everything else answers "finished, nothing" - which is what "no server"
        honestly means, and is a shape the caller can carry on from.

        Answering nil is the one thing it must not do: the caller asks the
        answer whether it is `done()` in the next line.
        """
        krpc = table({})

        #: Method names, across the applications that have them, that are
        #: really "here is a score" and "give me the scores". Every one of
        #: these is read off a real application: Mole No More and Long Jump
        #: say `SendHS`/`GetHS`, Skeet says `save_score` and four different
        #: spellings of `get_hiscores`. A name that is not recognised is not
        #: a score at all - it goes to "finished, nothing", which is what the
        #: game then tells the player ("Network Error: Score wasn't saved").
        SENDING = ('sendhs', 'sendscore', 'addscore', 'sethighscore',
                   'save_score', 'savescore', 'set_score', 'add_score',
                   'sendhiscore', 'send_hiscore', 'savehiscore')
        READING = ('geths', 'gethighscores', 'getscores', 'scores',
                   'get_hiscores', 'get_hiscores_level', 'gethiscores',
                   'get_hiscores_today', 'get_hiscores_level_today',
                   'get_scores', 'gethiscore', 'get_hiscore')

        def execute(_self=None, method=None, *arguments):
            name = str(method or '').lower()
            request = table({})
            answer = [None]
            note = ['']
            handled, payload = session_server.answer(method, arguments)
            if handled:
                # The library reads `r.result` on the line after this one, so
                # the answer is always wrapped - even when the payload is an
                # empty list, which is a real answer and not a refusal.
                wrapper = table({})
                wrapper.raw_set('result', _to_lua(payload, table))
                answer[0] = wrapper
            elif name in SENDING:
                # Klango's server knew each game's own columns; Cling does
                # not, and cannot: Skeet sends `(user, score, level)`, Mole
                # No More sends `(user, fails, normal, special, total, level,
                # version)`. So every number is KEPT on the row - nothing an
                # application sent is thrown away - and the largest is taken
                # as the score, which is Mole's `total` and Skeet's points.
                numbers = [int(value) for value in arguments
                           if isinstance(value, (int, float))
                           and not isinstance(value, bool)]
                points = max(numbers) if numbers else 0
                extra = {'values': numbers}
                if len(numbers) > 1:
                    extra['level'] = numbers[-1]
                published, note[0] = host.publish_score(points, extra)
                # The shape is the same as every other KRPC answer - a table
                # with a `result` - because that is what the caller reads:
                # `local r = ___rpc:result(); if r and r.result`. Answering a
                # bare `true` made Long Jump index a boolean and stop the
                # moment it had a score to send.
                #
                # And what Klango's server answered was the player's PLACE on
                # the table, which is what an application then says out loud.
                if published:
                    wrapper = table({})
                    wrapper.raw_set('result', _place_of(host, points))
                    answer[0] = wrapper
            elif name in READING:
                rows = host.leaderboard(20)
                if rows:
                    listing = table({})
                    for index, row in enumerate(rows, start=1):
                        line = table({})
                        line.raw_set('klangoid', row.get('name') or '?')
                        line.raw_set('total', int(row.get('points', 0) or 0))
                        line.raw_set('score', int(row.get('points', 0) or 0))
                        line.raw_set('points', int(row.get('points', 0) or 0))
                        line.raw_set('level', int(row.get('level', 0) or 0))
                        # Whatever else the game sent, in the order it sent
                        # it, so an application that reads a column by name
                        # finds something rather than nil.
                        values = row.get('values')
                        values = list(values) if isinstance(values, list) else []
                        for slot, field in enumerate(
                                ('fails', 'normal_moles', 'special_moles')):
                            line.raw_set(field, int(values[slot])
                                         if len(values) > slot else 0)
                        numbers = table({})
                        for slot, value in enumerate(values, start=1):
                            numbers.raw_set(slot, value)
                        line.raw_set('values', numbers)
                        listing.raw_set(index, line)
                    wrapper = table({})
                    wrapper.raw_set('result', listing)
                    answer[0] = wrapper
            request.raw_set('method', str(method or ''))
            request.raw_set('done', lambda *_a: True)
            request.raw_set('result', lambda *_a: answer[0])
            request.raw_set('error', lambda *_a: note[0] or None)
            request.raw_set('cancel', lambda *_a: True)
            return request

        krpc.raw_set('exec', execute)
        krpc.raw_set('Exec', execute)
        krpc.raw_set('new', lambda _self=None, *_a: new_krpc())
        krpc.raw_set('close', lambda *_a: True)
        return krpc

    # ----------------------------------------------------------- the web
    # Klango's HTTP client, really fetching - see `web.py`. Several of these
    # applications ARE the web (the Wikipedia browser is a search box and an
    # article reader; so are Mastodon, the Twitter client and the
    # translator), and an emulator that refuses the network is one on which
    # they cannot work at all. `http` and `https` only, capped, timed out,
    # and on a thread of its own so the game keeps running while it waits -
    # which is what Klango's own client did and what its progress dialog is
    # for.
    from . import web

    def new_http(spec=None, *_rest):
        context = table({})

        def new_request(_self=None, request_spec=None, *_a):
            from ..lua.runtime import LuaTable

            wanted = {}
            if isinstance(request_spec, LuaTable):
                for key in ('url', 'method', 'userpwd', 'filename'):
                    value = request_spec.raw_get(key)
                    if value is not None:
                        wanted[key] = str(value)
                fields = request_spec.raw_get('fields')
                if isinstance(fields, LuaTable):
                    wanted['fields'] = {str(key): str(fields.raw_get(key))
                                        for key in fields.keys()}
            fetch = web.Request(**wanted)
            return _http_request(table, context, fetch)

        context.raw_set('NewRequest', new_request)
        context.raw_set('SetOptions', lambda *_a: context)
        context.raw_set('Close', lambda *_a: True)
        context.raw_set('Cancel', lambda *_a: True)
        return context

    give('k_NewHttp', new_http)
    give('_Net_NewHttp', new_http)

    # An internet radio stream is a different thing again - a sound that
    # never ends - and Cling has nowhere to put one, so it answers a real
    # object that has nothing rather than a nil the caller then indexes.
    def new_icy_stream(_url=None, *_rest):
        stream = table({})
        stream.raw_set('Read', lambda *_a: None)
        stream.raw_set('ReadAll', lambda *_a: '')
        stream.raw_set('Available', lambda *_a: 0)
        stream.raw_set('Seekg', lambda *_a: 0)
        stream.raw_set('Close', lambda *_a: True)
        return stream

    give('k_NewIcyStream', new_icy_stream)

    # ------------------------------------------- the rest of the engine
    # Klango's engine exposes 52 more functions with no `_Sys_` prefix that
    # its library calls and never defines. They were nil, and a nil is not a
    # function: whichever one an application reached first ended it there.
    # Read out of the library itself rather than guessed - see
    # `tests/test_cling.py`'s `EveryEnginePrimitive`.
    def base64_encode(text=None, *_rest):
        import base64
        return base64.b64encode(
            str(text or '').encode('utf-8', 'replace')).decode('ascii')

    def base64_decode(text=None, *_rest):
        import base64
        try:
            return base64.b64decode(
                str(text or '').encode('ascii', 'replace')).decode(
                    'utf-8', 'replace')
        except Exception:
            return ''

    def hex_encode(text=None, *_rest):
        return str(text or '').encode('utf-8', 'replace').hex()

    def hmac_of(key=None, text=None, kind=None, *_rest):
        import hmac as hmac_module
        algorithm = str(kind or 'sha1').lower().replace('-', '')
        try:
            digest = hashlib.new(algorithm)
        except ValueError:
            algorithm = 'sha1'
        return hmac_module.new(str(key or '').encode('utf-8', 'replace'),
                               str(text or '').encode('utf-8', 'replace'),
                               algorithm).hexdigest()

    def split_string(text=None, *_rest):
        """`k_SplitString` - a string as a table of its characters."""
        out = table({})
        for index, character in enumerate(str(text or ''), start=1):
            out.raw_set(index, character)
        return out

    def remove_file(path=None, *_rest):
        real = filesystem.resolve(path)
        if not real or not os.path.isfile(real):
            return False
        try:
            os.remove(real)
        except OSError:
            return False
        return True

    def remove_directory(path=None, *_rest):
        real = filesystem.resolve(path)
        if not real or not os.path.isdir(real):
            return False
        import shutil
        shutil.rmtree(real, ignore_errors=True)
        return not os.path.isdir(real)

    def rename_file(old=None, new=None, *_rest):
        source = filesystem.resolve(old)
        target = filesystem.resolve(new, for_writing=True)
        if not source or not target:
            return False
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.replace(source, target)
        except OSError:
            return False
        return True

    def windows_path(path=None, *_rest):
        """`k_GetWinPath` - a Klango path as one the operating system knows.

        The text browser hands the answer straight to `LoadFile`, so it has
        to be the real path or the document is empty.
        """
        return filesystem.resolve(path) or str(path or '')

    def mime_of(path=None, *_rest):
        import mimetypes
        return mimetypes.guess_type(str(path or ''))[0] or ''

    def language_and_charset(*_rest):
        language, _sep, _country = (host.locale or 'en-us').partition('-')
        return (language, 'utf-8')

    give('k_Base64Encode', base64_encode)
    give('k_Base64Decode', base64_decode)
    give('k_HexEncode', hex_encode)
    give('k_HMAC', hmac_of)
    give('k_SplitString', split_string)
    give('k_FileRemove', remove_file)
    give('k_RmDir', remove_directory)
    give('k_FileRename', rename_file)
    give('k_GetWinPath', windows_path)
    give('k_GetWinSpecialFolder', lambda *_a: '/user')
    give('k_MIMEProbe', mime_of)
    give('k_DetectLangAndCharset', language_and_charset)
    give('k_Iconv', lambda _from=None, _to=None, text=None, *_a: str(text or ''))
    give('k_GetCommandLine', lambda *_a: '')
    give('k_GetDaemonMode', lambda *_a: False)
    give('k_GetInstalledApps', lambda *_a: table({}))
    give('k_GetProcessStatus', lambda *_a: 0)
    give('k_MediaInfo', lambda *_a: table({}))
    give('k_PrintTimestamp', lambda *_a: True)
    give('k_PrintTransientLog', lambda *_a: True)
    # Tidy is an HTML cleaner. Nothing here draws HTML, and the callers use
    # the answer as text, so the text is the answer.
    for name in ('k_Tidy', 'k_TidyQWV', 'k_TidyRaw'):
        give(name, lambda text=None, *_a: str(text or ''))

    def kni_info(path=None, *_rest):
        """`k_GetKniInfo` - what a `kni.txt` says, as a table."""
        real = filesystem.resolve(path)
        out = table({})
        if not real or not os.path.isfile(real):
            return out
        for line in (_textio().read(real) or '').split('\n'):
            key, _sep, value = line.partition('=')
            if _sep:
                out.raw_set(key.strip(), value.strip())
        return out

    give('k_GetKniInfo', kni_info)

    #: Refused, and recorded so the report says what was asked for. Running a
    #: program, installing one, taking a shortcut or an autostart entry,
    #: recording from the microphone and reading the clipboard are things a
    #: package from the internet does not get to do on somebody else's
    #: desktop. They ANSWER, though - a nil is not a function.
    for name in ('k_ShellExecute', 'k_LaunchKlango', 'k_SetAutostart',
                 'k_InstallKni', 'k_ReadStartMenu', 'k_CreateShortcut',
                 'k_Unzip', 'k_ThreadFileCopy', 'k_ThreadStreamCopy',
                 'k_SendErrorReport', 'k_ClipboardRead', 'k_ClipboardWrite',
                 'k_Encrypt', 'k_Decrypt', 'k_SndPos'):
        give(name, (lambda n: (lambda *_a: _record(n)))(name))

    def empty_stream(*_rest):
        """Something that can be ASKED ANYTHING and has nothing.

        A recorder, an audio stream, a pipe, a peer-to-peer session on a
        network that has been gone for years. Naming the methods it might be
        sent was not enough - the chat calls `k_NewP2PSession()` and then
        `session:GetState()`, and a name that is not in the list is nil,
        which is where the application stops. So every method exists: the
        few that must answer a number do, and everything else answers
        nothing, which is what "there is no network" means.
        """
        stream = table({})
        numbers = {'Available': 0, 'Size': 0, 'GetState': 0, 'GetStatus': 0,
                   'GetProgress': 0, 'GetLastError': 0, 'Count': 0}
        for name, value in numbers.items():
            stream.raw_set(name, (lambda v: (lambda *_a: v))(value))
        for name, value in (('done', True), ('Done', True),
                            ('isplaying', False), ('IsPlaying', False),
                            ('Close', True), ('Stop', True)):
            stream.raw_set(name, (lambda v: (lambda *_a: v))(value))
        meta = table({})
        meta.raw_set('__index', lambda _self=None, _name=None, *_a:
                     (lambda *_b: None))
        stream.metatable = meta
        return stream

    for name in ('k_NewSndRec', 'k_NewAVInStream', 'k_NewAVOutStream',
                 'k_NewMMSStream', 'k_NewNormalizeStream', 'k_NewPipeStream',
                 'k_NewStreamSound', 'k_NewStringStream', 'k_NewP2PSession',
                 'k_NewP2PUdpChannel'):
        give(name, (lambda n: (lambda *_a: (_record(n), empty_stream())[1]))(name))


    # `__CPUCacheCrazyKiller(app, secret, method, ...)` is not a licence check
    # despite the name - it is klango.net's general-purpose call, and the
    # method is its THIRD argument: the knowledge base, the contact list,
    # avatars, the prestige table, activation. Answering `True` to all of it
    # (which is what a reading of the name alone produced) hands the caller a
    # boolean where it expects a table, and `cat.subcats` on a boolean is
    # where Zawisza Czarny and TransTool both stopped. It goes to the same
    # server every other call goes to - `appsession.py` - and anything that
    # server has no answer for is nil, which is what every one of these
    # callers already handles: `if not ret then return end`, `... or {}`.
    def crazy_killer(_app=None, _secret=None, method=None, *arguments):
        handled, payload = session_server.answer(method, arguments)
        return _to_lua(payload, table) if handled else None

    give('__CPUCacheCrazyKiller', crazy_killer)
    give('k_NewKRPC', new_krpc)
    give('k_GetKRPC', new_krpc)
    give('_k_GetKlangoServerURL', lambda *_a: '')
    give('k_GetKlangoServerURL', lambda *_a: '')

    # ------------------------------------------------------------- streams
    def new_file_stream(path=None, mode=None, *_rest):
        """`k_NewFileStream(path, "rb")` - a file with Read/Write/Close.

        The library copies files with it (sounds into its cache, mostly), so it
        has to be real. Writing goes where every other write goes: the
        application's own folder, never the package it was unpacked from.
        """
        wanted = str(mode or 'rb')
        writing = any(letter in wanted for letter in 'wa+')
        real = filesystem.resolve(path, for_writing=writing)
        if not real:
            return None
        try:
            if writing:
                os.makedirs(os.path.dirname(real), exist_ok=True)
            handle = open(real, wanted if 'b' in wanted else wanted + 'b')
        except OSError:
            return None
        stream = table({})

        def read(_self=None, count=None, *_a):
            try:
                data = handle.read(int(count)) if count is not None \
                    else handle.read()
            except (OSError, ValueError):
                return None
            return data.decode('latin-1') if isinstance(data, bytes) else data

        def write(_self=None, data=None, *_a):
            text = '' if data is None else str(data)
            try:
                handle.write(text.encode('latin-1', 'replace'))
                return len(text)
            except (OSError, ValueError):
                return 0

        stream.raw_set('Read', read)
        stream.raw_set('Write', write)
        stream.raw_set('Close', lambda *_a: handle.close())
        stream.raw_set('Seek', lambda _s=None, where=0, *_a: handle.seek(
            int(where or 0)))
        stream.raw_set('Tell', lambda *_a: handle.tell())
        stream.raw_set('Size', lambda *_a: os.path.getsize(real))
        return stream

    give('k_NewFileStream', new_file_stream)
    give('_Sys_NewFileStream', new_file_stream)

    # ------------------------------------------------------------- markup
    def parse_markup(text=None, *_rest):
        from . import markup
        return markup.parse(text, table)

    give('k_XMLParsePS', parse_markup)
    give('k_XMLParse', parse_markup)
    give('_Sys_XMLParse', parse_markup)

    # ----------------------------------------------------------- the locale
    # Klango asks Windows which language the user is in and splits the answer
    # into ISO codes. Cling answers from the language Titan is already running
    # in, which is the one the user actually chose - and the shape of the
    # answer is the library's own: `t.langiso639[1]`, `t.countryiso3166[1]`.
    LCIDS = {'pl': 1045, 'en': 1033, 'de': 1031, 'fr': 1036, 'es': 3082,
             'it': 1040, 'cs': 1029, 'ru': 1049, 'pt': 2070, 'nl': 1043}

    def locale_pair():
        # TITAN's locale, not the application's - see `ClingHost.locale`. This
        # is what `k_GetWindowsLocale()` is built out of, and the library
        # chooses its own language from that, so an application that ships no
        # Polish must not make the platform English.
        code = host.locale or 'en-us'
        language, _sep, country = code.partition('-')
        return language.lower() or 'en', (country or language).upper()

    def user_locale_id(*_rest):
        return LCIDS.get(locale_pair()[0], 1033)

    def locale_info(identifier=None, *_rest):
        wanted = int(identifier) if isinstance(identifier, (int, float)) else 0
        language, country = locale_pair()
        for code, lcid in LCIDS.items():
            if lcid == wanted:
                language = code
                country = code.upper()
                break
        info = table({})
        for key, value in (('langiso639', language), ('countryiso3166', country),
                           ('lang', language), ('country', country),
                           ('langnative', language), ('countrynative', country)):
            pair = table({})
            pair.raw_set(1, value)
            pair.raw_set(2, key)
            info.raw_set(key, pair)
        return info

    give('k_GetUserLocaleId', user_locale_id)
    give('k_GetLocaleInfo', locale_info)
    give('k_GetCRTLocaleString', lambda *_a: '')

    # --------------------------------------------------------- the registry
    # Klango kept per-application settings in a registry of its own. Cling has
    # one already - the same store its own engines save scores in - so an
    # emulated application's settings live beside the rest of the user's, per
    # Titan-Net account, and go away with the application.
    def reg_read(key=None, default=None, *_rest):
        value = host.store.get('reg:' + str(key or ''), None)
        return default if value is None else value

    def reg_write(key=None, value=None, *_rest):
        host.store.set('reg:' + str(key or ''), value)
        return True

    def reg_delete(key=None, *_rest):
        host.store.set('reg:' + str(key or ''), None)
        return True

    # Two registry keys are read before anything has written them, and their
    # nil answers are concatenated straight into messages, so they are seeded.
    #
    # **The language is written on every run, not only the first.** The
    # library keeps the language it settled on in `/user/app/lang` and reads
    # it back at the next start - which in Cling's own store means that once
    # an application had been opened in one language it stayed in that
    # language for ever, whatever the user then chose in Titan. Cling follows
    # Titan, so Titan's locale is what that key says at the start of every
    # run; the library still falls back on its own when it has nothing in
    # that language, which is `langIsOk`'s job and not Cling's.
    host.store.set('reg:/user/app/lang', host.locale)
    host.store.set('reg:/user/app/langdefault', host.locale)
    if host.store.get('reg:/user/app/skin') is None:
        host.store.set('reg:/user/app/skin',
                       (host.skin.name if host.skin else '') or 'default')

    give('k_RegRead', reg_read)
    give('k_RegWrite', reg_write)
    give('k_RegDelete', reg_delete)
    # `S` is Klango's own "string" pair, and the multi-delete; the same store.
    give('k_RegSRead', reg_read)
    give('k_RegSWrite', reg_write)
    give('k_RegDeleteMulti', reg_delete)
    give('_Reg_GetSerial', lambda *_a: '')

    # An application object and the app registry the library keeps.
    holder = {}
    give('_Sys_SetApp', lambda value=None, *_a: holder.__setitem__('app', value))
    give('_Sys_GetApp', lambda *_a: holder.get('app'))
    return MISSING


_DRIVE_ID = ['']


def _drive_id():
    """A stable identifier for this machine, in Klango's own shape.

    Klango asked the operating system for the boot drive's serial and used it
    to tie an activation to a computer. Nothing here activates anything, but
    the value is still sent with every session call and concatenated into
    messages, so it has to be a string, and the same string on every run - a
    machine that looks like a new one at each start is exactly what the
    server-side check it was written for would have refused.
    """
    if not _DRIVE_ID[0]:
        import getpass
        import hashlib
        import platform
        seed = '%s|%s' % (platform.node() or '?', getpass.getuser() or '?')
        _DRIVE_ID[0] = hashlib.md5(
            seed.encode('utf-8', 'replace')).hexdigest()[:16].upper()
    return _DRIVE_ID[0]


def _to_lua(value, table):
    """A plain Python answer as the Lua the library will read it as.

    `appsession.py` answers in dicts and lists because that is what a server
    answers in; everything above it is Lua, and a dict handed straight to the
    interpreter is a value with no `[]` and no `pairs`. Lists become
    one-based arrays, which is the shape Klango's own row lists have.
    """
    if isinstance(value, dict):
        built = table({})
        for key, item in value.items():
            built.raw_set(key, _to_lua(item, table))
        return built
    if isinstance(value, (list, tuple)):
        built = table({})
        for index, item in enumerate(value, start=1):
            built.raw_set(index, _to_lua(item, table))
        return built
    return value


# ------------------------------------------------- the primitives not written
#: What a name has to begin with to be one of Klango's native primitives.
#: These are the six families the engine provides and nothing else is; an
#: ordinary global that has never been set still answers nil, which is what
#: Lua means by it.
NATIVE_PREFIXES = ('_Sys_', '_Gfx_', '_Snd_', '_Inp_', '_Voice_', '_Dir_',
                   '_Res_', '_Net_')


def _install_safety_net(runtime):
    """A primitive Cling has not written answers nothing, rather than nil.

    The difference is the whole application. A name that is nil is not a
    function, so `attempt to call a nil value '_Sys_CharIs_'` ends the run
    wherever it happens - which for the Wikipedia browser was the moment
    somebody typed into its search box, and for another application will be
    somewhere else. Answering with a function that does nothing lets the
    application carry on and be wrong about one thing instead of stopping,
    and it is what `MISSING` is for: the run finishes and the report names
    every primitive that was asked for and is not here.

    It is deliberately narrow. Only the six native families are caught, so an
    ordinary Lua global that has never been assigned is still nil - Klango's
    own code tests plenty of those and must go on getting the right answer.
    """
    interpreter = getattr(runtime, 'interpreter', None)
    if interpreter is None:                     # a native Lua is doing this
        return False
    from ..lua.runtime import LuaTable

    globals_table = interpreter.globals

    def missing(_table=None, name=None, *_rest):
        wanted = str(name or '')
        if not wanted.startswith(NATIVE_PREFIXES):
            return None
        return (lambda n: (lambda *_a: _record(n)))(wanted)

    meta = globals_table.metatable
    if meta is None:
        meta = LuaTable()
        globals_table.metatable = meta
    meta.raw_set('__index', missing)
    return True


def _http_request(table, context, fetch):
    """One request and its response, in the shape Klango's library reads.

    Klango's client answers the same object for both - `req:GetResponse()`
    starts it and hands back something the caller then polls - so this is one
    table wearing both hats, which is what the library does with it.
    """
    from . import web

    request = table({})
    stream_holder = {}

    def response(*_a):
        if fetch._thread is None and not fetch.done():
            fetch.start()
        return request

    def get_stream(*_a):
        if not fetch.done() or fetch.status in (web.NO_CONNECTION,
                                                web.CANCELLED):
            return None
        if 'stream' not in stream_holder:
            reader = web.Stream(fetch)
            piece = table({})
            piece.raw_set('Read', lambda _self=None, count=None, *_b:
                          reader.read(count))
            piece.raw_set('ReadAll', lambda *_b: reader.read_all())
            piece.raw_set('Available', lambda *_b: reader.available())
            piece.raw_set('Seekg', lambda _self=None, where=0, *_b:
                          setattr(reader, 'position', int(where or 0)))
            piece.raw_set('Size', lambda *_b: len(fetch.body))
            piece.raw_set('Close', lambda *_b: True)
            stream_holder['stream'] = piece
        return stream_holder['stream']

    def progress(*_a):
        out = table({})
        for key, value in fetch.progress().items():
            out.raw_set(key, value)
        return out

    request.raw_set('GetResponse', response)
    request.raw_set('GetContext', lambda *_a: context)
    request.raw_set('GetStatusCode', lambda *_a: fetch.status)
    request.raw_set('GetEffectiveUrl', lambda *_a: fetch.effective_url)
    # TWO values: `local le, letxt = resp:GetLastError()`.
    request.raw_set('GetLastError', lambda *_a: (fetch.error, fetch.error_text))
    request.raw_set('GetStream', get_stream)
    request.raw_set('GetProgress', progress)
    request.raw_set('SetOptions', lambda *_a: request)
    request.raw_set('Cancel', lambda *_a: fetch.cancel())
    request.raw_set('cancel', lambda *_a: fetch.cancel())
    request.raw_set('Done', lambda *_a: fetch.done())
    request.raw_set('done', lambda *_a: fetch.done())
    request.raw_set('result', lambda *_a: None)
    return request


def _place_of(host, points):
    """Where a score of `points` stands on the shared table, from 1.

    Klango's server answered a high-score submission with the position, and
    an application reads it back to the player. Cling's table is Titan-Net's,
    so the place is worked out from it - and when it cannot be reached, 1 is
    the honest answer for a score that was published and has nothing to be
    behind.
    """
    try:
        rows = host.leaderboard(50)
    except Exception:
        return 1
    better = sum(1 for row in rows
                 if int(row.get('points', 0) or 0) > int(points))
    return better + 1


def _number(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
