# -*- coding: utf-8 -*-
"""NVDA's module names, for NVDA add-on code ONLY.

An add-on says ``import config``, ``import ui``, ``from speech.commands
import IndexCommand``. Those names must reach Titan Access's stand-ins
(`nvda_host.shims`) - and must reach NOTHING for the rest of the process:
Titan Access's own shared modules ask ``import api`` to find out whether
they are running inside NVDA, and a stand-in found on the ordinary path
would make them believe they were.

So the decision is made per import, by WHO is importing: code whose module
lives under an add-on package (`synthDrivers`, `globalPlugins`,
`appModules`...) or whose file is inside the add-ons folder. Everyone else
is handed the ordinary import, unchanged. The hook is one wrapper round
``builtins.__import__`` and costs a dictionary lookup per import.
"""

import builtins
import importlib
import os
import threading

from . import shims

SHIM_PACKAGE = __name__.rsplit('.', 1)[0] + '.shims'
NAMES = frozenset(shims.NAMES)
#: The top-level packages an NVDA add-on's code lives in.
ADDON_PACKAGES = frozenset({'synthDrivers', 'globalPlugins', 'appModules',
                            'brailleDisplayDrivers',
                            'visionEnhancementProviders'})

_LOCK = threading.RLock()
_state = {'original': None, 'roots': (), 'served': 0}


def _from_addon(globals_):
    name = str(globals_.get('__name__', '') or '')
    if name.split('.', 1)[0] in ADDON_PACKAGES:
        return True
    path = globals_.get('__file__')
    if not path:
        return False
    path = os.path.normcase(os.path.abspath(str(path)))
    return any(path.startswith(root) for root in _state['roots'])


def _import(name, globals=None, locals=None, fromlist=(), level=0):
    original = _state['original']
    if level == 0 and name and globals is not None:
        top = name.split('.', 1)[0]
        if top in NAMES and _from_addon(globals):
            module = importlib.import_module(SHIM_PACKAGE + '.' + name)
            with _LOCK:
                _state['served'] += 1
            if fromlist:
                return module
            return importlib.import_module(SHIM_PACKAGE + '.' + top)
    return original(name, globals, locals, fromlist, level)


def install(roots):
    """Serve NVDA's names to code under ``roots`` (the add-ons folder)."""
    with _LOCK:
        _state['roots'] = tuple(os.path.normcase(os.path.abspath(str(root)))
                                + os.sep for root in roots)
        if _state['original'] is None:
            _state['original'] = builtins.__import__
            builtins.__import__ = _import


def uninstall():
    with _LOCK:
        if _state['original'] is not None:
            builtins.__import__ = _state['original']
            _state['original'] = None


def report():
    with _LOCK:
        return {'installed': _state['original'] is not None,
                'served': _state['served'], 'roots': list(_state['roots'])}
