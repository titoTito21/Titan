# -*- coding: utf-8 -*-
"""`import wx.adv`, `import wx.html2`, `from wx.lib.newevent import ...`.

A module-level `__getattr__` cannot answer these: `import wx.adv` is an
IMPORT, and Python looks for a real submodule. Three of Titan's eight
applications failed at their first line for want of one - the organiser
wants `wx.adv` for its calendar, the download manager wants
`wx.lib.newevent`, the browser wants `wx.html2` - and an application that
cannot be imported cannot be told anything.

So a finder answers any `wx.<anything>` with a module built on the spot,
permissive in the same way the shim itself is: an unknown name is a
recording no-op, not an ImportError. Two of them are given real answers
because a no-op is measurably wrong there:

- **`wx.lib.newevent.NewEvent()` returns a PAIR** which the caller
  immediately unpacks, so a no-op returning None is `TypeError` on the
  next line.
- **`wx.html2` and `wx.media` are refused out loud.** A web view or a
  media player cannot be a list of controls and pretending otherwise
  would be worse than saying so: the application still imports, still
  runs, and the interface is told plainly which part of it cannot be
  shown here. That is the same answer Cling gives for Klango's daemon
  mode and the Elten port for a protected leaderboard.
"""

import sys
import types


def install(shim):
    """Answer every `wx.*` submodule. Idempotent."""
    for finder in sys.meta_path:
        if getattr(finder, '_titan_wx', False):
            return
    sys.meta_path.insert(0, _Finder(shim))


class _Finder(object):
    _titan_wx = True

    def __init__(self, shim):
        self.shim = shim

    def find_module(self, name, path=None):
        return self if self._ours(name) else None

    def load_module(self, name):
        if name in sys.modules:
            return sys.modules[name]
        module = _build(name, self.shim)
        sys.modules[name] = module
        return module

    # The modern half of the same thing.
    def find_spec(self, name, path=None, target=None):
        if not self._ours(name):
            return None
        import importlib.machinery
        return importlib.machinery.ModuleSpec(name, _Loader(self.shim))

    @staticmethod
    def _ours(name):
        return name == 'wx' or name.startswith('wx.')


class _Loader(object):
    def __init__(self, shim):
        self.shim = shim

    def create_module(self, spec):
        if spec.name == 'wx':
            return None
        return _build(spec.name, self.shim)

    def exec_module(self, module):
        return None


#: What each of these is FOR, said in the words an interface can pass on.
REFUSED = {
    'wx.html2': 'a web view cannot be shown by an interface made of controls',
    'wx.media': 'a media player cannot be shown by an interface made of controls',
    'wx.glcanvas': 'a drawing surface cannot be shown as controls',
}


def _build(name, shim):
    module = types.ModuleType(name)
    module.__path__ = []
    module.__package__ = name
    refusal = REFUSED.get(name)
    if refusal:
        shim.RUNTIME.refuse(name, refusal)
    if name == 'wx.lib.newevent':
        module.NewEvent = _new_event
        module.NewCommandEvent = _new_event
    module.__getattr__ = _asking(name, shim)
    return module


def _asking(name, shim):
    def answer(what):
        if what.startswith('__'):
            raise AttributeError(what)
        shim.RUNTIME.note_unknown('%s.%s' % (name, what))
        # Everything the shim itself has, it has here too: an application
        # writing `wx.adv.Panel` means the panel.
        found = getattr(shim, what, None)
        if found is not None and not isinstance(found, shim._Silence):
            return found
        if what.isupper() or what.startswith(('ID_', 'EVT_', 'WXK_')):
            if what.startswith('EVT_'):
                return shim._EventKind(what[4:])
            return shim._Unknown(0)
        if what[:1].isupper():
            return shim._UnknownClass
        return shim._Silence(what)
    return answer


def _new_event():
    """`Event, EVT_THING = NewEvent()` - a pair, which the caller unpacks
    on the same line."""
    from . import _EventKind, Event
    return Event, _EventKind('CUSTOM')
