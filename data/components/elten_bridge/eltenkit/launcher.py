# -*- coding: utf-8 -*-
"""Opening an Elten application: everything one needs, in one call.

Copyright (C) 2026 titosoft. Part of the Elten API bridge, licensed under the
GNU General Public License version 3 or later; see `LICENSE` beside this
component.

`run(entry)` is what the window, the Invisible UI, Klango mode and the action
API all go through, so an application is started one way however it was asked
for. What it does, in order:

1. **Unpacks the package into a cache keyed on its own bytes.** The
   `.eltenapp` is the application and is never written to, converted or
   deleted; the directory beside it is a working copy, re-made when the
   package changes and reused when it has not, because unpacking a two
   megabyte application on every launch is a second the user waits for
   nothing.
2. **Points the three roots where they belong** - assets at that cache,
   `data` at ELTEN's own `apps/data/<app>/` so a saved game is the same file
   in both programs, `cache` at Elten's own cache.
3. **Loads the application's own translations**, so `_("New game")` answers
   in the user's language out of the `.mo` the package carries.
4. Starts the bridge, and hands back the running `Application`.
"""

import gettext
import hashlib
import io
import os

from . import bridge as bridge_module
from . import catalogue as catalogue_module
from . import host as host_module
from . import package as package_module


def cache_root():
    """Where unpacked applications live. Purely a performance detail."""
    try:
        from src.platform_utils import get_user_resource_path
        base = get_user_resource_path(os.path.join('pkg_cache', 'eltenapps'))
    except Exception:
        base = os.path.join(os.environ.get('TEMP', '.'), 'titan-eltenapps')
    os.makedirs(base, exist_ok=True)
    return base


def unpack(entry):
    """The application as real files, and the `Package` that was read.

    Keyed on the package's size and modification time as well as its path:
    an application Elten has just updated in place keeps its name and its
    location and is a different application, and a cache that answered the
    old one would run last week's code for ever.
    """
    try:
        stamp = os.stat(entry.path)
        token = '%s|%d|%d' % (entry.path, stamp.st_size, int(stamp.st_mtime))
    except OSError as error:
        raise package_module.PackageError('%s could not be read: %s'
                                          % (os.path.basename(entry.path),
                                             error))
    digest = hashlib.sha256(token.encode('utf-8')).hexdigest()[:16]
    folder = os.path.join(cache_root(), '%s_%s' % (_safe(entry.stem), digest))
    marker = os.path.join(folder, '.unpacked')
    if os.path.isfile(marker):
        try:
            manifest, signature = package_module.read_manifest(entry.path)
            return folder, package_module.Package(entry.path, manifest, [], {},
                                                  signature)
        except package_module.PackageError:
            pass
    package = package_module.extract(entry.path, folder)
    with open(marker, 'w', encoding='utf-8') as handle:
        handle.write(token)
    return folder, package


def _safe(name):
    return ''.join(character if character.isalnum() or character in '-_'
                   else '_' for character in str(name))[:60] or 'app'


def data_root(entry):
    """Elten's own `apps/data/<name>/` - shared with Elten on purpose.

    An application's saved state belongs to the user, not to whichever
    program happened to launch it. Somebody who plays a game in Elten and
    then opens it here should find their game where they left it, and a
    bridge that kept a second copy would lose whichever half was written
    last. Falls back to a directory of Titan's own when Elten is not
    installed at all, which is the case the vendored Ruby exists for.
    """
    base = catalogue_module.elten_data_dir()
    if base:
        return os.path.join(base, entry.stem)
    try:
        from src.platform_utils import get_user_resource_path
        return get_user_resource_path(os.path.join('data', 'eltenapps_data',
                                                   entry.stem))
    except Exception:
        return os.path.join(cache_root(), 'data', entry.stem)


def cache_dir(entry):
    base = catalogue_module.elten_cache_dir()
    if base:
        return os.path.join(base, entry.stem)
    return os.path.join(cache_root(), 'cache', entry.stem)


def translator_for(folder, language):
    """The application's own `.mo`, in the user's language, or None.

    Elten packages a compiled gettext catalogue per language and Titan
    already speaks gettext, so this is one `GNUTranslations` and no parsing
    of anything. A language the application does not carry answers None, and
    `_()` then hands the string back untranslated - which is what an
    application with no catalogue at all has always done.
    """
    wanted = (language or 'en').lower().split('-')[0]
    locale = os.path.join(folder, 'locale')
    for code in (wanted, 'en'):
        path = os.path.join(locale, '%s.mo' % code)
        if os.path.isfile(path):
            try:
                with open(path, 'rb') as handle:
                    return gettext.GNUTranslations(io.BytesIO(handle.read()))
            except (OSError, ValueError):
                continue
    return None


def run(entry, ui=None, language='en', speaker=None, sounds=None):
    """Start one application. Answers the `Application`, running or failed.

    Never raises: a package that cannot be opened, an interpreter that is
    not there and an application that refuses to start all come back as an
    `Application` whose `status` is `failed` and whose `detail` is a
    sentence, because every one of those has to be something the window can
    say rather than a traceback in a console the user cannot see.
    """
    if entry.problem:
        return _failed(entry, entry.problem)
    try:
        folder, _package = unpack(entry)
    except package_module.PackageError as error:
        return _failed(entry, str(error))
    except OSError as error:
        return _failed(entry, 'the application could not be unpacked: %s' % error)

    paths = host_module.Paths(folder, data_root(entry), cache_dir(entry))
    paths.ensure('data')
    paths.ensure('cache')

    application = bridge_module.Application(
        entry, paths, speaker=speaker, sounds=sounds,
        translator=translator_for(folder, language), ui=ui, language=language)
    application.start()
    return application


def _failed(entry, reason):
    application = bridge_module.Application(
        entry, host_module.Paths('', '', ''), ui=None)
    application.status = 'failed'
    application.detail = reason
    application.ended.set()
    return application
