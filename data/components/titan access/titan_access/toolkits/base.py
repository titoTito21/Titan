# -*- coding: utf-8 -*-
"""One toolkit: how its edit fields are read and written.

A toolkit module says three things, and nothing else needs to know which
toolkit a window is written in:

* ``PLAN`` - the ways to write a field, best first. ``'keys'`` means the
  field is written by passing the user's own keys on to the real control,
  which works in every program there is and is the only way in where the
  toolkit exposes nothing (Tk before 9.1, GTK on Windows, a game).
* ``read_text(obj)`` - the field's whole text, for the copy that is
  walked; ``None`` when the toolkit cannot say.
* ``NOTE`` - what is true of the toolkit, in one paragraph, with where it
  was found out. A plan nobody can check is a guess.
"""

from . import providers


class Toolkit(object):
    #: The names `portable.toolkit` gives the frameworks this covers.
    FRAMEWORKS = ()
    #: What it is called, for a person.
    NAME = ''
    #: The ways to write a field, best first.
    PLAN = ('uia', 'msaa', 'keys')
    #: The order to READ a field's text in.
    READ = ('win32', 'uia', 'jab', 'atspi', 'msaa')
    NOTE = ''

    def mode(self, obj):
        """The first way in the plan that can write THIS control."""
        for method in self.PLAN:
            if method == 'keys':
                return 'keys'
            try:
                if providers.can(method, obj):
                    return method
            except Exception:                        # noqa: BLE001
                continue
        return 'keys'

    def set_text(self, obj, text, method):
        if method == 'keys':
            return False
        setter = providers.SETTERS.get(method)
        if setter is None:
            return False
        try:
            return bool(setter(obj, text))
        except Exception:                            # noqa: BLE001
            return False

    def read_text(self, obj):
        for method in self.READ:
            getter = providers.GETTERS.get(method)
            if getter is None:
                continue
            try:
                found = getter(obj)
            except Exception:                        # noqa: BLE001
                found = None
            if found is not None:
                return found
        return None

    def describe(self):
        return {'name': self.NAME, 'frameworks': list(self.FRAMEWORKS),
                'plan': list(self.PLAN), 'note': self.NOTE}
