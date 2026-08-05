"""The Titan Action API - how any part of Titan calls into any add-on.

This is a titan-core capability, not an AI one. Titan's AI agent and voice
assistant are simply its first consumers; a component, a widget, a macro, a
gamepad mode, a launcher or another application uses exactly the same calls::

    from src.titan_core import actions

    actions.list_addons()                       # what is installed and reachable
    actions.list_actions('tedit')               # what it can do
    actions.run('tedit', 'open_file', path=...) # do it

Before this existed, the only way to make an add-on do something from outside
was to write code *about* it (Titan's tMedia integration is ~1100 lines of
exactly that: it reads tMedia's private data files and drives it through a
startup argument). That does not scale and it breaks the moment the add-on
changes. Here the add-on declares what it can do and Titan discovers it:

    data/applications/tEdit/__actions.json     <- the declaration
    data/applications/tEdit/tedit_actions.py   <- the handlers

All nine add-on kinds use the same file, and because discovery goes through
``platform_utils.discover_data_entries()``, a packaged ``.TCA``/``.TCD`` add-on
is picked up exactly like a directory. An in-process add-on may skip the JSON
and declare ``TITAN_ACTIONS`` in Python with real callables.

Two transports, because Titan's add-ons live in two different places:

- ``inproc``  - components, widgets, statusbar applets, TTS engines, gamepad
  modes, launchers and Titan IM modules already run inside Titan, so an action
  is a direct call, marshalled onto the GUI thread (``inproc.py``).
- ``process`` - applications and games are separate processes. A *headless*
  action runs in a short-lived subprocess that prints JSON; a *live* action is
  delivered to the running instance over the Action Bus (``bus.py``), which is
  what makes "save the document I have open" possible.

An add-on joins the bus with one call to ``src.titan_core.titan_actions.serve``
- a deliberately standalone, standard-library-only module, because the add-on
importing it may be a wx app, a Tk launcher or a console script.
"""

from src.titan_core.actions.manifest import (      # noqa: F401
    ActionSpec, AddonActions, parse_manifest, read_manifest, MANIFEST_NAMES,
)
from src.titan_core.actions.kinds import (         # noqa: F401
    ADDON_KINDS, ACTIONABLE_KINDS, kind_label,
)
from src.titan_core.actions.registry import (      # noqa: F401
    get_registry, invalidate, find_addon, find_action, all_actions,
)
from src.titan_core.actions.dispatch import (      # noqa: F401
    run, run_qualified, list_addons, list_actions, describe_addon, is_available,
    start, ActionResult, ActionError,
)
from src.titan_core.actions.interaction import (   # noqa: F401
    Question, Failure, needs, fails, is_question, is_failure, run_interactive,
    wx_ask,
)
from src.titan_core.actions.sequence import (      # noqa: F401
    run_sequence, SequenceResult, StepResult,
)

__all__ = [
    'run', 'run_qualified', 'run_sequence', 'run_interactive', 'needs', 'fails',
    'list_addons', 'list_actions', 'describe_addon', 'is_available', 'start',
    'get_registry', 'invalidate', 'find_addon', 'find_action', 'all_actions',
    'ActionResult', 'ActionError', 'Question', 'Failure', 'is_question',
    'is_failure', 'wx_ask',
    'SequenceResult', 'StepResult', 'ActionSpec', 'AddonActions',
    'ADDON_KINDS', 'ACTIONABLE_KINDS', 'kind_label', 'parse_manifest',
    'read_manifest', 'MANIFEST_NAMES',
]
