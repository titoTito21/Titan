# -*- coding: utf-8 -*-
"""NVDA's `addonHandler`: the add-ons installed in Titan Access, and each
add-on's own translations."""

import gettext
import inspect
import os


class AddonError(Exception):
    pass


class Addon(object):
    def __init__(self, record):
        self._record = record
        self.name = record['name']
        self.path = record['path']
        self.manifest = dict(record.get('manifest') or {})
        self.version = self.manifest.get('version', '')
        self.isRunning = bool(record.get('enabled', True))
        self.isEnabled = self.isRunning
        self.isDisabled = not self.isRunning
        self.isPendingRemove = False
        self.isPendingInstall = False

    def getDocFilePath(self, fileName=None):
        doc = os.path.join(self.path, 'doc')
        return doc if os.path.isdir(doc) else None

    def __repr__(self):
        return 'Addon(%r)' % self.name


def _records():
    from titan_access import nvda_host
    return nvda_host.installed()


def getAvailableAddons(refresh=False, filterFunc=None):
    for record in _records():
        addon = Addon(record)
        if filterFunc is None or filterFunc(addon):
            yield addon


def getRunningAddons():
    return getAvailableAddons(filterFunc=lambda one: one.isRunning)


def getCodeAddon(obj=None, frameDist=1):
    """The add-on a piece of code belongs to, by where its file is."""
    path = None
    if obj is not None:
        path = getattr(inspect.getmodule(obj), '__file__', None)
    if path is None:
        frame = inspect.stack()[frameDist + 1] if len(inspect.stack()) > \
            frameDist + 1 else inspect.stack()[-1]
        path = frame.filename
    path = os.path.normcase(os.path.abspath(str(path or '')))
    for record in _records():
        root = os.path.normcase(os.path.abspath(record['path']))
        if path.startswith(root + os.sep):
            return Addon(record)
    raise AddonError('the code is not part of an add-on')


def initTranslation():
    """Put the add-on's own `_` (and ngettext, pgettext) into the CALLER's
    globals, from its locale folder, in Titan's language."""
    frame = inspect.currentframe().f_back
    try:
        addon = getCodeAddon(frameDist=1)
        from .languageHandler import getLanguage
        lang = getLanguage()
        translations = gettext.translation(
            'nvda', localedir=os.path.join(addon.path, 'locale'),
            languages=[lang, lang.split('_')[0]], fallback=True)
    except Exception:                                # noqa: BLE001
        translations = gettext.NullTranslations()
    frame.f_globals['_'] = translations.gettext
    frame.f_globals['ngettext'] = translations.ngettext
    frame.f_globals['pgettext'] = translations.pgettext
    frame.f_globals['npgettext'] = translations.npgettext
    del frame


class AddonManifest(dict):
    pass


def isCLIParamKnown(arg):
    return False


class state(object):
    pass


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
