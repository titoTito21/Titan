# -*- coding: utf-8 -*-
"""NVDA's modules, as an NVDA add-on running in Titan Access sees them.

Each file here stands in for one of NVDA's own modules (`config`,
`synthDriverHandler`, `nvwave`, `ui`, `api`...) and is written for Titan
Access - nothing is copied from NVDA. They are served ONLY to code loaded
from an NVDA add-on (`nvda_host.importer`): the rest of Titan, and Titan
Access's own shared modules, never see them, because a module called
`api` or `config` in the ordinary path would make Titan Access's shared
code believe it was running inside NVDA.
"""

#: The NVDA module names this package answers, top-level name -> file.
NAMES = (
    'addonAPIVersion', 'addonHandler', 'api', 'appModuleHandler',
    'autoSettingsUtils', 'baseObject', 'braille', 'buildVersion',
    'config', 'controlTypes', 'core', 'driverHandler', 'eventHandler',
    'extensionPoints', 'globalCommands', 'globalPluginHandler',
    'globalVars', 'gui', 'inputCore', 'keyboardHandler', 'languageHandler',
    'logHandler', 'NVDAObjects', 'nvwave', 'queueHandler', 'scriptHandler',
    'speech', 'speechXml', 'synthDriverHandler', 'systemUtils',
    'textInfos', 'tones', 'ui', 'versionInfo', 'winKernel', 'winUser',
)


#: Every NVDA name an add-on asked for that no stand-in has - reported by
#: `nvda_host.report()`, so "the add-on does not work" has a reason.
missing = set()


def _missing_class(module, name):
    """A stand-in for something of NVDA's this host has not written: a
    class (so it can be subclassed) whose instances answer every attribute
    and every call with nothing. An add-on that touches it carries on with
    that one thing missing, instead of failing to load at all."""

    class _Nothing(object):
        def __init__(self, *args, **kwargs):
            pass

        def __call__(self, *args, **kwargs):
            return None

        def __getattr__(self, attr):
            if attr.startswith('__'):
                raise AttributeError(attr)
            return _Nothing()

        def __bool__(self):
            return False

        def __iter__(self):
            return iter(())

    _Nothing.__name__ = name
    _Nothing.__qualname__ = name
    _Nothing.__module__ = module
    missing.add('%s.%s' % (module.rsplit('.', 1)[-1], name))
    return _Nothing


def permissive(module_globals):
    """Give a stand-in module a fallback for names it does not have."""
    name = module_globals.get('__name__', '')

    def __getattr__(attr):
        if attr.startswith('__'):
            raise AttributeError(attr)
        found = _missing_class(name, attr)
        module_globals[attr] = found
        return found
    module_globals['__getattr__'] = __getattr__
