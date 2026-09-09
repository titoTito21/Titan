# -*- coding: utf-8 -*-
"""What a control means because it is in TITAN, read as Titan Access reads it.

Titan Access is Titan's own reader, and it has a handful of behaviours that
belong to the desktop rather than to any one application: a slot of Titan's
status bar is a **status bar item** and not "list item 3"; arriving in Titan
and leaving it are each a cue and a word, so somebody who has just come back
from Notepad knows where they are before a control is announced. NVDA knew
none of it, so a user reading Titan with NVDA got a strictly poorer reading
of the same desktop - which is the thing this whole add-on exists to end.

Everything here is ported from `data/components/titan access/titan_access/`
and each piece says which file it came from, because the point is that the
two readers agree: a user who moves between them must not have to learn two
vocabularies for one desktop.

**It is asked of Titan, never guessed from a window.** Which process is
Titan's is `semantics`' question and it is answered by Titan's own registry;
every wxPython program shares a window class and every title is written in
the user's own language, so neither is evidence.
"""

import threading

from . import i18n

_ = i18n.install(globals())


# --------------------------------------------------------------------------- #
# A slot of the status bar
# --------------------------------------------------------------------------- #
#: What a control has to BE before it can be a status bar item. Titan's
#: status bar is built out of a list, so its slots arrive as list items -
#: which is exactly why they need re-labelling. From
#: `context_presenter._compute`: `obj.role in ("listitem", "treeitem")`.
ITEM_ROLES = frozenset({'LISTITEM', 'TREEVIEWITEM', 'TREEITEM'})

#: What marks the container as a status bar. A real status bar role first,
#: and then the NAME - Titan's own status bar is a list or a pane that is
#: CALLED one, and the name follows the application's language, so both
#: spellings are here. From `context_presenter._status_bar_names`.
BAR_ROLES = frozenset({'STATUSBAR'})
BAR_CONTAINERS = frozenset({'LIST', 'PANE', 'TOOLBAR', 'PROPERTYPAGE'})
BAR_NAMES = frozenset({'status bar', 'statusbar', 'pasek stanu',
                       'pasek statusu'})


def _role_of(obj):
    try:
        return str(getattr(getattr(obj, 'role', None), 'name', '') or '').upper()
    except Exception:                                # noqa: BLE001
        return ''


def _name_of(obj):
    try:
        return str(getattr(obj, 'name', '') or '').strip().rstrip(':').strip()
    except Exception:                                # noqa: BLE001
        return ''


def _is_the_bar(obj):
    role = _role_of(obj)
    if role in BAR_ROLES:
        return True
    return role in BAR_CONTAINERS and _name_of(obj).casefold() in BAR_NAMES


def role_word(obj, application, said):
    """What this control is CALLED, when Titan calls it something else.

    ``said`` is what NVDA would have said - the answer when there is nothing
    to add, which is nearly always. Only inside Titan, because the reason a
    list item is a status bar slot is that this desktop builds its status
    bar out of a list, and saying it about somebody else's list would be
    inventing a fact about their program.

    The ancestry is the one NVDA has ALREADY built (`ancestry._chain` reads
    `api.getFocusAncestors()`), because this runs on the focus path and
    `obj.parent` is a call into another process, not a field. The first
    version of the semantic layer walked eight of those per focus event and
    froze a real NVDA ten times in one session; there is no reason to learn
    that twice.
    """
    if application is None or _role_of(obj) not in ITEM_ROLES:
        return said
    try:
        from . import semantics
        for step in semantics._ancestors(obj):
            if _is_the_bar(step):
                # Translators: what a slot of Titan's status bar is called.
                return _('status bar item')
    except Exception:                                # noqa: BLE001
        pass
    return said


# --------------------------------------------------------------------------- #
# Arriving in Titan, and leaving it
# --------------------------------------------------------------------------- #
#: Titan Access's own two, in `sfx/<theme>/SRE/` where every one of this
#: add-on's sounds lives - so a theme can replace them and a user without
#: Titan Access still has them. From `sound_manager.play_enter_tce` /
#: `play_leave_tce`.
SOUND_ENTER = 'enter_TCE.ogg'
SOUND_LEAVE = 'leave_TCE.ogg'

#: What Titan Access says on the way in. Deliberately the product's name and
#: not a sentence: it is said on every arrival, and a sentence said that
#: often is a sentence the user learns to talk over.
NAME = 'Titan'

_LOCK = threading.RLock()
_state = {'inside': False, 'started': False, 'entered': 0, 'left': 0}


def report():
    with _LOCK:
        return dict(_state)


def forget():
    with _LOCK:
        _state.update({'inside': False, 'started': False,
                       'entered': 0, 'left': 0})


def wanted():
    """The same switch as everything else this layer does inside Titan."""
    from . import configSpec
    return bool(configSpec.read().get('appSemantics', True))


def crossing(obj, application=None):
    """The focus has moved. Say so when it has moved INTO or OUT OF Titan.

    Returns what happened - 'entered', 'left' or '' - which is what the
    diagnostics command reads: "it does not announce Titan any more" is a
    report with no evidence in it, and whether the crossing was seen at all
    is the first thing to know.

    **The first focus of a session establishes the baseline and says
    nothing.** Titan Access is explicit about this (`engine._had_focus`) and
    it matters: NVDA starting while Titan is in front would otherwise open
    with an announcement about a window the user has been sitting in.
    """
    if not wanted():
        return ''
    if application is None:
        try:
            from . import semantics
            application = semantics.application_of(obj)
        except Exception:                            # noqa: BLE001
            application = None
    inside = application is not None
    with _LOCK:
        was = _state['inside']
        started = _state['started']
        _state['inside'] = inside
        _state['started'] = True
        if started and inside and not was:
            _state['entered'] += 1
        elif started and was and not inside:
            _state['left'] += 1
    if not started or inside == was:
        return ''
    if inside:
        _say(SOUND_ENTER, NAME)
        return 'entered'
    _say(SOUND_LEAVE, '')
    return 'left'


def _say(sound, words):
    """The cue, and then the word - queued behind NVDA's own report.

    Not `interrupt`: the user has just changed window and NVDA is about to
    say what they arrived on, which is the more urgent of the two. Titan
    Access queues it for the same reason (`speak(..., interrupt=False)`).

    Nothing is said on the way OUT. Titan Access says its "unsupported
    application" line there because it IS the reader and has just stopped
    being able to read anything; NVDA has not stopped, and announcing that
    the user has left Titan every time they alt-tab is noise about
    something they did on purpose. The sound says it.
    """
    try:
        from . import earcons
        earcons.play_named(sound)
    except Exception:                                # noqa: BLE001
        pass
    if not words:
        return
    try:
        from . import compat
        if compat.queueHandler is None or compat.ui is None:
            return

        def speak():
            try:
                compat.ui.message(words)
            except Exception:                        # noqa: BLE001
                pass
        compat.queueHandler.queueFunction(compat.queueHandler.eventQueue,
                                          speak)
    except Exception:                                # noqa: BLE001
        pass
