# -*- coding: utf-8 -*-
"""Gesture manager for Titan Access.

Python port of the C# ``InputGestures/GestureManager.cs`` + ``GestureBinding.cs``.
Maps normalized key combinations (the "key specs" the engine registers) to
handler callables, and dispatches a pressed key against them.

A *key spec* is a ``+``-separated combo of optional modifiers and a single base
key, e.g. ``"space"``, ``"t"``, ``"numpad5"``, ``"shift+f12"``, ``"control"``,
``"v"``. The recognised modifier tokens are ``ctrl``/``control``, ``alt``,
``shift`` and ``insert``/``nvda`` (the reader modifier). Everything else is the
base key (normalized exactly like :mod:`titan_access.keyboard_hook` produces it).

The keyboard hook only calls :meth:`dispatch` once it has already decided a key
is a screen-reader gesture (reader modifier held, or a NumPad object-nav key),
so matching ignores the reader-modifier flag and keys on base key + Ctrl/Alt/
Shift. Each binding keeps localized metadata (name / description / category from
the ``gesture.*`` locale keys) for a future help list, exposed via
:meth:`list_bindings`.
"""

from titan_access.localization import L

# Modifier tokens recognised inside a key spec.
_CTRL_TOKENS = {"ctrl", "control"}
_ALT_TOKENS = {"alt"}
_SHIFT_TOKENS = {"shift"}
_INSERT_TOKENS = {"insert", "nvda"}


class GestureBinding:
    """One key-spec -> handler binding (port of ``GestureBinding.cs``)."""

    def __init__(self, action_id, key_spec, handler):
        self.action_id = action_id
        self.key_spec = key_spec
        self.handler = handler

        self.ctrl = False
        self.alt = False
        self.shift = False
        self.insert = False
        self.base = ""
        self._parse(key_spec)

        # Localized metadata for a help dialog. Keys may be absent for internal
        # actions (e.g. objnav_*); L() falls back to the key name itself.
        self.name = L(f"gesture.{action_id}.name")
        self.description = L(f"gesture.{action_id}.desc")
        self.category = L("gesture.category.global")

    def _parse(self, key_spec):
        parts = [p.strip().lower() for p in (key_spec or "").split("+") if p.strip()]
        for part in parts:
            if part in _CTRL_TOKENS:
                self.ctrl = True
            elif part in _ALT_TOKENS:
                self.alt = True
            elif part in _SHIFT_TOKENS:
                self.shift = True
            elif part in _INSERT_TOKENS:
                self.insert = True
            else:
                self.base = part

    def matches(self, key_name, ctrl, alt, shift):
        """Match against a pressed key.

        The reader-modifier flag is intentionally ignored: the hook has already
        gated dispatch on the modifier (or NumPad nav), so a spec like ``"t"``
        (meant as Insert+T) matches when T is pressed with no Ctrl/Alt/Shift.
        """
        return (self.base == (key_name or "").lower()
                and self.ctrl == ctrl
                and self.alt == alt
                and self.shift == shift)

    def readable(self):
        parts = []
        if self.insert:
            parts.append("Insert")
        if self.ctrl:
            parts.append("Ctrl")
        if self.alt:
            parts.append("Alt")
        if self.shift:
            parts.append("Shift")
        if self.base:
            parts.append(self.base)
        return "+".join(parts)


class GestureManager:
    """Registers and dispatches keyboard gestures."""

    def __init__(self, engine):
        self.engine = engine
        self._bindings = []

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #
    def register(self, action_id, key_spec, handler):
        """Bind *handler* to *key_spec*. Later bindings can shadow earlier ones
        only if they share base+modifiers; :meth:`dispatch` returns the first
        match in registration order."""
        binding = GestureBinding(action_id, key_spec, handler)
        self._bindings.append(binding)
        return binding

    def unregister(self, action_id):
        self._bindings = [b for b in self._bindings if b.action_id != action_id]

    # ------------------------------------------------------------------ #
    # Dispatch
    # ------------------------------------------------------------------ #
    def dispatch(self, key_name, vk, ctrl, alt, shift):
        """Run the first binding matching the pressed key. Returns True if a
        binding handled the key (so the hook swallows it)."""
        for binding in self._bindings:
            if binding.matches(key_name, ctrl, alt, shift):
                try:
                    binding.handler()
                except Exception as e:
                    print(f"[TitanAccess] gesture '{binding.action_id}' error: {e}")
                    try:
                        self.engine.speak(L("gesture.commandError"))
                    except Exception:
                        pass
                return True
        return False

    # ------------------------------------------------------------------ #
    # Help support
    # ------------------------------------------------------------------ #
    def list_bindings(self):
        """Return binding metadata for a help dialog: list of dicts with
        ``action_id``, ``name``, ``description``, ``category`` and ``gesture``
        (human-readable key combination)."""
        out = []
        for b in self._bindings:
            out.append({
                "action_id": b.action_id,
                "name": b.name,
                "description": b.description,
                "category": b.category,
                "gesture": b.readable(),
            })
        return out
