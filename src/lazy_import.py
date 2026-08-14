# -*- coding: utf-8 -*-
"""
Modules Titan imports because it MIGHT need them, imported when it does.

Starting Titan imported the whole of Telegram, Messenger and WhatsApp before
the window appeared - telethon, pytgcalls, aiohttp, requests and everything
under them - whether or not the user has ever signed in to any of them.
Measured on this machine: `import main` cost 2.83 seconds, of which
`src.network.telegram_client` was 723 ms and `src.network.messenger_client`
another 762 ms.  That is most of a second and a half spent on the way to a
window, for a feature the user may never open.

They cannot simply be deleted from the top of `gui.py`: they are used from
about thirty places, always as `telegram_client.something`, and rewriting
every one of those into a local import is thirty chances to get it wrong.

So the NAME is bound at once and the module is imported the first time
anything is read off it.  `LazyModule` is a real `types.ModuleType`, so
`isinstance(x, ModuleType)` still holds, and the first attribute read makes it
*become* the module it stands for - after that there is no indirection left at
all, only a dictionary that was filled a little later than it used to be.

The one thing it keeps besides the attributes is the falsehood of a module
that is not there.  The old code wrote

    try:
        from src.network import telegram_client
    except ImportError:
        telegram_client = None
    ...
    if telegram_client:

and an object that were merely truthy would have turned "Telegram is not
installed" into a crash at the first call.  So `__bool__` answers whether the
module is THERE (`importlib.util.find_spec`, which finds the file without
running it) rather than importing to find out - because the Invisible UI asks
exactly that question while building its menu, on every startup - and a module
that cannot be imported raises `AttributeError` for everything, which is what
`None` did.

**A module reached this way must be in the build's hidden imports.**  Nothing
static points at it any more, so PyInstaller cannot see it: every name passed
to `lazy_import` here is already listed in `compiletorelease.py` and in
`Titan.spec`, and a new one has to be added to both.
"""

import importlib
import types


class LazyModule(types.ModuleType):
    """A module that imports itself the first time it is read."""

    def __init__(self, name):
        super().__init__(name)
        # Written straight into `__dict__` so `__getattr__` is never asked
        # about them - it is only called for attributes that are missing.
        self.__dict__['_lazy_name'] = name
        self.__dict__['_lazy_failed'] = False

    def _lazy_load(self):
        """Import for real, and become what was imported.

        Returns the module, or None when it cannot be imported at all - the
        second call does not try again, because a missing dependency does not
        appear halfway through a session and re-raising the same ImportError
        on every keystroke would be a fast way to make the program unusable.
        """
        if self.__dict__.get('_lazy_failed'):
            return None
        name = self.__dict__['_lazy_name']
        try:
            module = importlib.import_module(name)
        except Exception as error:
            self.__dict__['_lazy_failed'] = True
            print(f"[STARTUP] {name} is not available: {error}")
            return None
        # Become it: from here on every attribute is found in `__dict__` and
        # `__getattr__` is never consulted again.
        self.__dict__.update(module.__dict__)
        self.__dict__['_lazy_name'] = name
        self.__dict__['_lazy_failed'] = False
        return module

    def __getattr__(self, attribute):
        # Only reached for something not in `__dict__` - so either the module
        # has not been loaded yet, or it really has no such attribute.
        if attribute.startswith('_lazy'):
            raise AttributeError(attribute)
        module = self._lazy_load()
        if module is None:
            raise AttributeError(
                "{} is not available".format(self.__dict__['_lazy_name']))
        return getattr(module, attribute)

    def available(self):
        """Is the module there to be imported - without importing it.

        `importlib.util.find_spec` looks for the file (importing only the
        PACKAGE it lives in, which is an empty `__init__.py` here) and never
        runs the module itself.
        """
        if '__file__' in self.__dict__:
            return True
        if self.__dict__.get('_lazy_failed'):
            return False
        try:
            return importlib.util.find_spec(
                self.__dict__['_lazy_name']) is not None
        except Exception:
            return False

    def __bool__(self):
        """`if telegram_client:` - which asks whether Titan HAS Telegram.

        Deliberately `available()` and not the import: the Invisible UI asks
        this while it builds its menu, in `InvisibleUI.__init__`, on every
        startup - and answering it by importing would have put the whole of
        telethon back on the way to the window, which is the one thing this
        module exists to keep off it.

        The difference this makes: a module that is INSTALLED but cannot be
        imported (a dependency of its own missing) used to be absent from
        the menu and is now an entry that reports the failure when it is
        pressed.  That is the better of the two, for a program whose users
        cannot see a menu entry quietly not being there.
        """
        return self.available()

    def __repr__(self):
        state = 'loaded' if '__file__' in self.__dict__ else 'not loaded yet'
        return "<lazy module {} ({})>".format(self.__dict__['_lazy_name'],
                                              state)


def lazy_import(name):
    """`import <name>`, done when something actually reads from it."""
    return LazyModule(name)
