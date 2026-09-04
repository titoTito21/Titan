# -*- coding: utf-8 -*-
"""The Ruby the bridge runs applications on.

Elten applications are Ruby - the manifest names a `.rb` and a class, and the
code inside does `require_relative`, defines modules, mixes them in and raises
real exceptions - so something has to actually be Ruby. Cling could carry its
own Lua because Lua is a small language written in an afternoon of Python;
Ruby is not, and an interpreter of one's own would run the two simplest games
and stop at the first application that vendors a gem.

So the component carries CRuby, in `ruby/`, and that is what "portable" means
here: the bridge works on a machine that has never had Ruby and never had
Elten. It is looked for in three places, in this order:

1. `ELTEN_BRIDGE_RUBY` - an interpreter the user named, which is how somebody
   developing an application points the bridge at their own build.
2. `ruby/bin/ruby.exe` inside the component - what ships.
3. Whatever is on `PATH` - the last resort, and the one that makes the
   component still work when its `ruby/` was left out of a build.

The version matters and is checked: Elten 3 targets Ruby 4.x, and an
application written against it will fail in ways that read as the
application's fault on anything older. A refusal here says which Ruby was
found and what was wanted, because "it does not work" is not something a user
can act on.
"""

import os
import subprocess
import sys

#: Where the vendored interpreter lives inside the component.
RUBY_DIR = 'ruby'

#: The lowest Ruby an Elten 3 application can be expected to run on.
MINIMUM = (3, 1)

#: How long to wait for `ruby -e` to answer when asking what it is. An
#: interpreter that cannot say its own version in this long is not one to
#: hand an application to.
PROBE_TIMEOUT = 15.0

_found = None


class RubyMissing(Exception):
    """No usable interpreter, with a sentence saying what was looked for."""


def component_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def vendored():
    """The interpreter the component ships, or ''."""
    base = os.path.join(component_root(), RUBY_DIR, 'bin')
    for name in ('ruby.exe', 'ruby'):
        candidate = os.path.join(base, name)
        if os.path.isfile(candidate):
            return candidate
    return ''


def candidates():
    """Every interpreter to try, in the order they are tried."""
    found = []
    named = os.environ.get('ELTEN_BRIDGE_RUBY', '').strip()
    if named:
        found.append(named)
    here = vendored()
    if here:
        found.append(here)
    import shutil
    on_path = shutil.which('ruby')
    if on_path:
        found.append(on_path)
    return found


def version_of(interpreter):
    """`(major, minor, patch)` for an interpreter, or None.

    Asked with `RUBY_VERSION` rather than by reading `ruby -v`, because the
    banner carries the platform and the revision as well and a parser for it
    is one more thing to be wrong.
    """
    try:
        answer = subprocess.run(
            [interpreter, '-e', 'print RUBY_VERSION'],
            capture_output=True, timeout=PROBE_TIMEOUT,
            creationflags=_no_window())
    except (OSError, subprocess.SubprocessError):
        return None
    if answer.returncode != 0:
        return None
    text = (answer.stdout or b'').decode('ascii', 'replace').strip()
    parts = text.split('.')
    try:
        return tuple(int(part) for part in parts[:3])
    except ValueError:
        return None


def _no_window():
    """Never flash a console window at somebody using a screen reader."""
    if sys.platform != 'win32':
        return 0
    return getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)


def find(refresh=False):
    """The interpreter to run applications on. Raises `RubyMissing`.

    The answer is remembered: this walks the disk and starts a process, and
    the window asks for it once per application launched.
    """
    global _found
    if _found is not None and not refresh:
        return _found
    tried = []
    for interpreter in candidates():
        version = version_of(interpreter)
        if version is None:
            tried.append('%s (it would not run)' % interpreter)
            continue
        if version < MINIMUM:
            tried.append('%s (Ruby %s)'
                         % (interpreter, '.'.join(str(n) for n in version)))
            continue
        _found = Runtime(interpreter, version)
        return _found
    wanted = '.'.join(str(number) for number in MINIMUM)
    if not tried:
        raise RubyMissing(
            'no Ruby interpreter was found, and this build of the bridge does '
            'not carry one, so Elten applications cannot be run')
    raise RubyMissing(
        'no Ruby %s or newer was found. Tried: %s' % (wanted, '; '.join(tried)))


def available():
    """True when an application could be started right now."""
    try:
        find()
        return True
    except RubyMissing:
        return False


def unavailable_reason():
    """What to say when it is not, or ''."""
    try:
        find()
        return ''
    except RubyMissing as error:
        return str(error)


class Runtime(object):
    """One interpreter, and the environment an application runs under."""

    __slots__ = ('path', 'version')

    def __init__(self, path, version):
        self.path = path
        self.version = version

    def __repr__(self):
        return '<Ruby %s at %s>' % (self.pretty_version, self.path)

    @property
    def pretty_version(self):
        return '.'.join(str(number) for number in self.version)

    @property
    def vendored(self):
        """True when this is the one the component ships."""
        here = vendored()
        return bool(here) and os.path.normcase(here) == os.path.normcase(self.path)

    def environment(self, extra=None):
        """The environment an application's interpreter runs in.

        Two things are deliberately set:

        * **`RUBYOPT` is cleared.** Whatever the user's own Ruby installation
          wants loaded into every interpreter is not something an Elten
          application asked for, and a `-r` in there is code running inside
          somebody else's application.
        * **`GEM_HOME` / `GEM_PATH` point at the component's own**, so an
          application sees the gems that ship with the bridge and not a gem
          the machine happens to have at a different version. A machine with
          no Ruby at all has to behave the same as one with three.
        """
        environment = dict(os.environ)
        environment.pop('RUBYOPT', None)
        environment.pop('RUBYLIB', None)
        if self.vendored:
            base = os.path.join(component_root(), RUBY_DIR)
            gems = os.path.join(base, 'lib', 'ruby', 'gems',
                                '%d.%d.0' % self.version[:2])
            if os.path.isdir(gems):
                environment['GEM_HOME'] = gems
                environment['GEM_PATH'] = gems
        environment['ELTEN_BRIDGE'] = '1'
        environment.update(extra or {})
        return environment
