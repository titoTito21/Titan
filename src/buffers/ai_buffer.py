# -*- coding: utf-8 -*-
"""
Titan Buffer System - the AI category and the live AI settings category.

**"AI"** is ONE review category holding everything the AI does, in its buffers
([ ] moves between them, , . between elements):

    Conversation   "You: ..." / "Perun: ..." - every request and reply of the
                   voice assistant and of the AI Agent window
    Actions        what the agent actually ran (describe_action) + its result
    Notifications  reminder announcements and creation-kit milestones

**"AI settings"** is a separate INTERACTIVE (live) category, in the style of
:mod:`src.buffers.tts_buffer` - the review levels change meaning there, which is
why it cannot be a buffer of the category above:

    [  ]   switch parameter (persona, voice, confirmations, reminders, ...)
    {  }   first / last parameter
    ,  .   change the current parameter's value
    <  >   jump to the first / last value

Every change is written to settings immediately (the same keys the Settings GUI
uses), so the two can never drift apart.

Both are registered CONTEXTUALLY on the first AI activity of the session (like
Titan-Net registers on login). Producers only need the push_* helpers; each of
them registers on first use, so nothing has to be bootstrapped at startup.
"""

from src.buffers import buffer_bus

CATEGORY_ID = 'ai'
SETTINGS_CATEGORY_ID = 'ai_settings'

BUF_CONVERSATION = 'conversation'
BUF_ACTIONS = 'actions'
BUF_NOTIFICATIONS = 'notifications'

# Element kinds. Deliberately NOT 'message'/'private': those make the announcer
# say "Message from X", while a conversation reads better as "You: ..." /
# "Perun: ..." (see buffer_announcer._element_text).
KIND_MESSAGE = 'ai_message'
KIND_ACTION = 'ai_action'
KIND_NOTIFICATION = 'notification'

# Tool results can be long; keep the reviewable line short (same cap as the
# agent window's transcript).
MAX_RESULT_CHARS = 300

_registered = False


def _t():
    try:
        from src.titan_core.translation import set_language
        from src.settings.settings import get_setting
        return set_language(get_setting('language', 'pl'))
    except Exception:
        return lambda s: s


def _language():
    try:
        from src.settings.settings import get_setting
        return (get_setting('language', 'pl') or 'pl').split('_')[0]
    except Exception:
        return 'pl'


# --------------------------------------------------------------------------- #
#  Registration (contextual: on first AI activity)
# --------------------------------------------------------------------------- #
def register():
    """Create the AI review category, its buffers and the live AI settings
    category. Idempotent and best effort."""
    global _registered
    if _registered:
        return
    _registered = True
    _ = _t()
    try:
        buffer_bus.register_category(CATEGORY_ID, _("AI"))
        buffer_bus.ensure_buffer(CATEGORY_ID, BUF_CONVERSATION,
                                 _("Conversation"), kind=KIND_MESSAGE)
        buffer_bus.ensure_buffer(CATEGORY_ID, BUF_ACTIONS, _("Actions"),
                                 kind=KIND_ACTION)
        buffer_bus.ensure_buffer(CATEGORY_ID, BUF_NOTIFICATIONS,
                                 _("Notifications"), kind=KIND_NOTIFICATION)
    except Exception as e:
        print(f"[AIBuffer] register error: {e}")
    # The live category cannot go through buffer_bus (it needs a handler),
    # exactly like tts_buffer.register().
    try:
        from src.buffers.buffer_system import get_buffer_manager
        get_buffer_manager().register_live_category(
            SETTINGS_CATEGORY_ID, _("AI settings"), AISettingsHandler())
    except Exception as e:
        print(f"[AIBuffer] live category error: {e}")


def remove():
    """Remove both AI categories (not used in normal operation; the review
    record is kept for the whole session)."""
    global _registered
    _registered = False
    try:
        buffer_bus.remove_category(CATEGORY_ID)
        buffer_bus.remove_category(SETTINGS_CATEGORY_ID)
    except Exception as e:
        print(f"[AIBuffer] remove error: {e}")


# --------------------------------------------------------------------------- #
#  Producer API
# --------------------------------------------------------------------------- #
def persona_name(persona):
    """Display name of ``persona`` in Titan's language, or the generic
    "Assistant" label when no persona is known."""
    _ = _t()
    if not persona:
        return _("Assistant")
    key = 'name_pl' if _language() == 'pl' else 'name_en'
    return persona.get(key) or persona.get('name_en') or _("Assistant")


def _push(buffer_id, text, author, kind):
    text = (text or '').strip()
    if not text:
        return
    register()
    try:
        buffer_bus.push(CATEGORY_ID, buffer_id, text, author=author, kind=kind,
                        category_name=_t()("AI"))
    except Exception as e:
        print(f"[AIBuffer] push error: {e}")


def push_user(text):
    """What the user said / typed to the AI."""
    _push(BUF_CONVERSATION, text, _t()("You"), KIND_MESSAGE)


def push_assistant(text, persona=None, author=None):
    """What the assistant answered (``author`` overrides the persona name, e.g.
    "Agent" for the standalone AI Agent window)."""
    _push(BUF_CONVERSATION, text, author or persona_name(persona), KIND_MESSAGE)


def push_action(description):
    """One agent action, already described in plain words (describe_action)."""
    _push(BUF_ACTIONS, description, _t()("Action"), KIND_ACTION)


def push_action_result(text):
    """The result an agent action returned (trimmed to one reviewable line)."""
    short = (text or '').strip().replace('\n', ' ')
    if len(short) > MAX_RESULT_CHARS:
        short = short[:MAX_RESULT_CHARS] + '...'
    _push(BUF_ACTIONS, short, _t()("Result"), KIND_ACTION)


def push_notice(text, author=None):
    """An AI notification worth re-reading later (reminder announcement,
    creation-kit milestone)."""
    _push(BUF_NOTIFICATIONS, text, author, KIND_NOTIFICATION)


# --------------------------------------------------------------------------- #
#  Live "AI settings" category
# --------------------------------------------------------------------------- #
def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _cycle(values, current, direction, extreme):
    """Index of the next value (clamped, like every other buffer level)."""
    try:
        i = values.index(current)
    except ValueError:
        i = 0
    if extreme:
        return (len(values) - 1) if direction > 0 else 0
    return _clamp(i + direction, 0, len(values) - 1)


def _personas():
    try:
        from src.ai.assistant import personas as personas_mod
        return personas_mod.list_personas()
    except Exception as e:
        print(f"[AIBuffer] persona list error: {e}")
        return []


class AISettingsHandler:
    """Drives the interactive "AI settings" category.

    Every parameter is an enumeration, so `,`/`.` and `<`/`>` behave like the
    other buffer levels: they move within the list of values and stop at its
    edges. The new value is applied through the normal ai_provider setters, i.e.
    written to settings straight away - the Settings dialog and this category can
    never disagree.
    """

    # -- parameter definitions ------------------------------------------- #
    def _persona_value(self):
        from src.ai import ai_provider
        ids = [p['id'] for p in _personas()]
        current = ai_provider.get_assistant_model()
        return current if current in ids else (ids[0] if ids else '')

    def _enum_params(self):
        """[(param_id, label, [(value, display)], current_value)] for every
        parameter except the persona (which reads its list from disk)."""
        _ = _t()
        from src.ai import ai_provider
        tts_opts = [(v, _("Automatic") if v == 'auto' else l)
                    for v, l in ai_provider.assistant_tts_options()]
        on_off = [(True, _("On")), (False, _("Off"))]
        return [
            ('tts', _("Assistant voice"), tts_opts, ai_provider.get_assistant_tts()),
            ('confirm', _("Confirmations"),
             [('tiered', _("Risky actions")), ('all', _("Every action")),
              ('none', _("Autonomous"))],
             ai_provider.get_agent_confirm()),
            ('reminders', _("Reminder announcements"),
             [('voice', _("Spoken")), ('text', _("Text")), ('off', _("Off"))],
             ai_provider.get_reminder_announce()),
            ('reminder_ai', _("AI wording of reminders"), on_off,
             ai_provider.get_reminder_ai_phrasing()),
            ('dictation', _("Dictation into text fields"), on_off,
             ai_provider.get_assistant_dictation()),
        ]

    def _display(self, options, value):
        for val, disp in options:
            if val == value:
                return str(disp)
        return str(value)

    def _tts_display(self, disp, value):
        """Append the engine "Automatic" currently resolves to, so the user
        hears which voice will actually speak."""
        if value != 'auto':
            return disp
        try:
            from src.ai import ai_provider
            return "{} ({})".format(disp, ai_provider.resolve_assistant_tts())
        except Exception:
            return disp

    # -- live-category contract ------------------------------------------ #
    def list_params(self):
        _ = _t()
        params = []
        personas = _personas()
        if personas:
            current = self._persona_value()
            name = next((persona_name(p) for p in personas
                         if p['id'] == current), _("None"))
        else:
            name = _("None")
        params.append(('persona', "{}: {}".format(_("Assistant persona"), name)))

        for pid, label, options, value in self._enum_params():
            disp = self._display(options, value)
            if pid == 'tts':
                disp = self._tts_display(disp, value)
            params.append((pid, "{}: {}".format(label, disp)))
        return params

    def adjust(self, param_id, direction, extreme=False):
        try:
            if param_id == 'persona':
                return self._adjust_persona(direction, extreme)
            return self._adjust_enum(param_id, direction, extreme)
        except Exception as e:
            print(f"[AIBuffer] adjust '{param_id}' error: {e}")
            return ""

    def _adjust_persona(self, direction, extreme):
        _ = _t()
        from src.ai import ai_provider
        personas = _personas()
        if not personas:
            return _("None")
        ids = [p['id'] for p in personas]
        i = _cycle(ids, self._persona_value(), direction, extreme)
        ai_provider.set_assistant_model(ids[i])
        return persona_name(personas[i])

    def _adjust_enum(self, param_id, direction, extreme):
        from src.ai import ai_provider
        entry = next((e for e in self._enum_params() if e[0] == param_id), None)
        if entry is None:
            return ""
        _pid, _label, options, value = entry
        values = [v for v, _d in options]
        i = _cycle(values, value, direction, extreme)
        new = values[i]

        if param_id == 'tts':
            ai_provider.set_assistant_tts(new)
        elif param_id == 'confirm':
            ai_provider.set_agent_confirm(new)
        elif param_id == 'reminders':
            ai_provider.set_reminder_announce(new)
            # Start/stop the announcer so the change takes effect at once.
            try:
                from src.ai.assistant import reminder_watcher
                reminder_watcher.refresh()
            except Exception as e:
                print(f"[AIBuffer] reminder refresh error: {e}")
        elif param_id == 'reminder_ai':
            ai_provider.set_reminder_ai_phrasing(new)
        elif param_id == 'dictation':
            ai_provider.set_assistant_dictation(new)
        else:
            return ""

        disp = str(options[i][1])
        return self._tts_display(disp, new) if param_id == 'tts' else disp


def refresh_settings():
    """Re-sync the live AI settings category after the Settings dialog saved.

    The parameter list itself is read live on every announcement, so this only
    has to make sure the category exists and the current parameter is still
    valid (personas can be added or removed while Titan runs).
    """
    if not _registered:
        return
    try:
        from src.buffers.buffer_system import get_buffer_manager
        mgr = get_buffer_manager()
        cat = mgr.categories.get(SETTINGS_CATEGORY_ID)
        if cat is None:
            mgr.register_live_category(SETTINGS_CATEGORY_ID, _t()("AI settings"),
                                       AISettingsHandler())
            return
        params = AISettingsHandler().list_params()
        ids = [pid for pid, _label in params]
        if cat.current_buffer_id not in ids:
            cat.current_buffer_id = ids[0] if ids else None
    except Exception as e:
        print(f"[AIBuffer] settings refresh error: {e}")
