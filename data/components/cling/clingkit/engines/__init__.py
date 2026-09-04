# -*- coding: utf-8 -*-
"""The engines Cling drives an application with, and how one is chosen.

An engine is a GENRE, not an application, and the set of them is deliberately
open.  Three ways a new application is supported, in the order they cost
nothing, little and something:

1. **It is one of the genres already here.**  A Klango application copied into
   `data/cling/` is looked at - its levels, its `spec.txt`, its sample folder,
   its lesson files - and the engine that can drive that data is chosen.  No
   file is edited and nothing is written.
2. **It brings its own logic.**  An application that ships `main.lua` (or
   `main.py`) is a program, run against the whole Cling host by the
   interpreter this component carries.  This is the general answer: an
   application of any shape whatever runs this way, and an existing Klango
   application whose rules Cling cannot infer becomes runnable by having one
   file added BESIDE its unchanged data.
3. **A new genre is registered.**  `engines.register('darts', factory)` from a
   component, a shell add-on or an application's own `engine.py` adds a genre
   to Cling from outside it, so a family of applications that share rules is
   supported once rather than once each.
"""

from .base import Engine

#: name -> callable(host) -> Engine. Added to by `register`.
_REGISTRY = {}


def register(name, factory):
    """Add a genre to Cling from outside Cling. Returns the name registered."""
    name = str(name or '').strip().lower()
    if not name or not callable(factory):
        raise ValueError('an engine needs a name and a callable')
    _REGISTRY[name] = factory
    return name


def names():
    """Every genre Cling can drive, built in and registered."""
    from .. import catalog
    return sorted(set(catalog.ENGINES) | set(_REGISTRY))


def _builtin(name):
    from .. import catalog
    if name == catalog.ENGINE_KLANGO:
        from .klango_app import KlangoEngine
        return KlangoEngine
    if name == catalog.ENGINE_SCRIPT:
        from .script import ScriptEngine
        return ScriptEngine
    if name == catalog.ENGINE_GRID_HUNT:
        from .grid_hunt import GridHuntEngine
        return GridHuntEngine
    if name == catalog.ENGINE_SOUNDSCAPE:
        from .soundscape import SoundscapeEngine
        return SoundscapeEngine
    if name == catalog.ENGINE_INSTRUMENT:
        from .instrument import InstrumentEngine
        return InstrumentEngine
    if name == catalog.ENGINE_TYPING:
        from .typing import TypingEngine
        return TypingEngine
    return None


def build(host):
    """The engine for this application.

    An application whose manifest names an engine gets that one; everything
    else was worked out by `catalog.detect_engine` from what the directory
    holds.  A name nobody has registered falls back to the reader, which shows
    what the application says rather than nothing at all.
    """
    from .. import catalog
    from .reader import ReaderEngine

    name = (getattr(host.app, 'engine', '') or '').strip().lower()
    factory = _REGISTRY.get(name) or _builtin(name)
    if factory is None:
        return ReaderEngine(host)
    try:
        return factory(host)
    except Exception as error:
        print("[cling] engine '%s' could not be built: %s" % (name, error))
        return ReaderEngine(host)


__all__ = ['Engine', 'build', 'register', 'names']
