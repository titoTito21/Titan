# -*- coding: utf-8 -*-
"""Base class for application modules.

Python port of ``ScreenReader/AppModules/AppModuleBase.cs`` (NVDA
``appModuleHandler.AppModule``). A module customises the screen reader for one
application, identified by :attr:`process_name` (lower-case, no ``.exe``).

The manager calls, in order, for each focus change inside the owning app:

    1. :meth:`on_gain_focus` once when the app first becomes active (welcome /
       one-time setup) — guarded by an internal "activated" flag.
    2. :meth:`customize_object` on every focused element, to mutate the
       :class:`~titan_access.contracts.AccessibleObject` *in place* before the
       engine announces it (e.g. append a file type or document statistics).

When the app loses foreground, :meth:`on_lose_focus` is called so the module can
reset transient state. Modules read the live UIA element through
``obj.native`` (a vendored ``uiautomation`` Control) and may use ``self.engine``
to speak or play sounds directly.
"""


class AppModuleBase:
    """Base for per-application behaviour. Subclass and set ``process_name``."""

    #: Process name this module handles (lower-case, without ``.exe``).
    process_name = ""

    def __init__(self, engine):
        self.engine = engine
        self._activated = False

    # -- identity ---------------------------------------------------------- #
    @property
    def app_name(self):
        """Friendly application name (defaults to the process name)."""
        return self.process_name

    def matches(self, process_name):
        """True if this module handles ``process_name`` (case-insensitive)."""
        return bool(process_name) and process_name.lower() == self.process_name

    # -- lifecycle hooks --------------------------------------------------- #
    def on_gain_focus(self, obj):
        """Called when the app becomes active and on each element focus.

        Subclasses that want a one-time welcome should call
        :meth:`_announce_welcome_once`. ``obj`` is the focused
        :class:`AccessibleObject` (may be ``None``).
        """
        # Default: nothing. Subclasses override.

    def on_lose_focus(self, obj):
        """Called when the application loses the foreground."""
        self._activated = False

    def customize_object(self, obj):
        """Mutate and return ``obj`` before it is announced.

        Default returns ``obj`` unchanged. Subclasses append details to
        ``obj.description`` / adjust ``obj.value`` so the standard announcer
        picks them up.
        """
        return obj

    def should_announce(self, obj):
        """Return ``False`` to SUPPRESS the standard announcement for ``obj``.

        Lets a module silence noise (e.g. a busy status pane) or take over the
        announcement itself (speak in :meth:`customize_object` / event hooks and
        suppress here). Default announces everything.
        """
        return True

    # -- optional event hooks (NVDA-style; called by the engine when wired) -- #
    def event_value_change(self, obj):
        """The focused element's value changed (e.g. a slider moved)."""

    def event_name_change(self, obj):
        """The focused element's name/label changed."""

    def event_alert(self, obj):
        """An alert / notification surfaced in the application."""

    # -- per-app gestures -------------------------------------------------- #
    def get_gestures(self):
        """Return a dict ``{key_spec: callable}`` of gestures active only while
        this application is in the foreground (e.g. ``{"control+r": self.read}``).

        ``key_spec`` uses the same syntax as the global gesture manager
        (:mod:`titan_access.gestures`). Default: no app-specific gestures.
        """
        return {}

    # -- helpers ----------------------------------------------------------- #
    def _announce_welcome_once(self, text):
        """Speak ``text`` the first time the app gains focus this session."""
        if not self._activated and text:
            self.engine.speak(text)
        self._activated = True
