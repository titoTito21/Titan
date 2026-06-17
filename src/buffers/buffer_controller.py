# -*- coding: utf-8 -*-
"""
Titan Buffer System - controller.

Host-agnostic glue between key input and the model + announcer. Hosts (GUI,
Klango, IUI/Titan UI) translate their key events into one of the 12 action
names below and call dispatch(); the controller mutates the shared
BufferManager and hands the result to the announcer.

There is deliberately NO global keyboard hook here - hosts wire these only
into their own focused windows / active overlay, so the buffer keys
(- = [ ] , . and the Shift variants _ + { } < >) never get suppressed
system-wide.

Action names:
    prev_category / next_category / first_category / last_category
    prev_buffer   / next_buffer   / first_buffer   / last_buffer
    prev_element  / next_element  / first_element  / last_element
"""

from src.settings.settings import get_setting
from src.buffers.buffer_system import get_buffer_manager
from src.buffers import buffer_announcer

# Literal characters -> action. The Shift variants are the characters those
# keys produce with Shift held, which is convenient for console (msvcrt) and
# wx EVT_CHAR hosts where the char already reflects the Shift state.
CHAR_ACTIONS = {
    '-': 'prev_category',  '=': 'next_category',
    '_': 'first_category', '+': 'last_category',
    '[': 'prev_buffer',    ']': 'next_buffer',
    '{': 'first_buffer',   '}': 'last_buffer',
    ',': 'prev_element',   '.': 'next_element',
    '<': 'first_element',  '>': 'last_element',
}

ALL_ACTIONS = set(CHAR_ACTIONS.values())


def is_enabled():
    """Master switch. Defaults to on; reuses the invisible_interface section."""
    try:
        return get_setting('buffer_system_enabled', 'True',
                           section='invisible_interface').lower() in ('true', '1')
    except Exception:
        return True


def action_for_char(ch):
    """Return the action name for a literal character, or None."""
    if not ch:
        return None
    return CHAR_ACTIONS.get(ch)


def dispatch(action):
    """Run an action by name: mutate the model, then announce. Returns True
    if the action was recognised and handled."""
    if not action or action not in ALL_ACTIONS:
        return False
    if not is_enabled():
        return False
    try:
        mgr = get_buffer_manager()
        nav = getattr(mgr, action)()
        buffer_announcer.announce(nav)
        return True
    except Exception as e:
        print(f"[BufferController] dispatch '{action}' error: {e}")
        return False


def handle_char(ch):
    """Convenience for char-based hosts (Klango msvcrt, wx EVT_CHAR).

    Returns True if the character mapped to a buffer action and was handled,
    so the host can swallow the key; False to let the host process it normally.
    """
    action = action_for_char(ch)
    if action is None:
        return False
    return dispatch(action)
