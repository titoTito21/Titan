# -*- coding: utf-8 -*-
"""Everything Titan is, from inside NVDA.

:mod:`link` is the doorway - one action, `titan.bridge`, carrying typed
JSON - and this is the **map**. Measured when it was written: Titan's
bridge answers 57 calls and this add-on reached 15 of them, so most of a
whole desktop was there, documented, working, and unreachable from the
reader the user reads it with.

**Why a map rather than more actions.** Every Titan action is already a
bindable NVDA script (:mod:`gestures`) and already on the Titan menu, and
that is the right answer for "run the macro that files my downloads". It
is the wrong answer for a *subsystem*: a list of applications, the
settings, what arrived while a window was shut, the widgets - those are
screens, not commands, and offering them as a flat list of actions whose
arguments are typed in as text is offering them in the shape that is
hardest to use. So the calls that ARE screens are gathered here, in the
shapes a window can be built out of, and :mod:`titanWindow` builds it.

**Everything answers ``(ok, value)`` and nothing raises.** Titan may not be
running, may be older than this add-on, or may not have been told this
add-on can control it - three different things, each with a different
thing to do about it, and :mod:`link` already tells them apart. A refusal
travels as the sentence Titan itself wrote, in the user's own language.

**Reading is never the same question as acting.** Titan serves what only
reads to any client; anything that DOES something waits on the user's own
yes. That is Titan's rule, not ours, and it is not worked around here -
:data:`ACTS` is only so a window can say which entry will ask.
"""

from . import i18n
from .link import LINK

_ = i18n.install(globals())

#: The calls that make Titan do something rather than say something. Titan
#: decides this itself (its `capabilities` answers `consent.needed_for`);
#: this is what a window shows BEFORE the first refusal, so an entry that
#: is going to ask can be marked rather than surprising somebody.
ACTS = frozenset({
    'addons.run', 'ai.ask', 'ai.forget', 'app.close', 'app.key', 'app.open',
    'app.press', 'app.set', 'apps.open', 'games.open', 'im.open', 'menu.run',
    'notifications.clear', 'ocr.overlay_close', 'ocr.overlay_refresh',
    'ocr.overlay_show', 'settings.cancel', 'settings.press', 'settings.save',
    'settings.set', 'sounds.play', 'sounds.theme', 'speech.rate',
    'speech.say', 'speech.stop', 'widgets.move', 'widgets.press',
})


def _rows(call, key, **args):
    """A list of dicts out of a bridge call, or ``(False, sentence)``.

    One place that knows Titan answers a list under a named key, because
    every one of these had to be read off a live Titan and a key nothing
    writes is a working-looking empty list - the fault this repository has
    already paid for twice.
    """
    ok, data = LINK.bridge(call, **args)
    if not ok:
        return False, str(data)
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get(key)
    else:
        rows = None
    if not isinstance(rows, list):
        return False, _('Titan answered nothing that could be listed.')
    return True, [row for row in rows if isinstance(row, dict)]


def _did(call, **args):
    """A call that DOES something. ``(ok, sentence)``."""
    ok, data = LINK.bridge(call, **args)
    if not ok:
        return False, str(data)
    if isinstance(data, dict):
        said = data.get('said') or data.get('text') or data.get('message')
        if said:
            return True, str(said)
    return True, ''


# --------------------------------------------------------------------------- #
# What Titan can start
# --------------------------------------------------------------------------- #
def applications():
    return _rows('apps.list', 'applications')


def open_application(name, render=False):
    if render:
        return _did('apps.open', name=name, render=True)
    return _did('apps.open', name=name)


def games():
    return _rows('games.list', 'games')


def open_game(name):
    return _did('games.open', name=name)


def cling_applications():
    return _rows('cling.list', 'applications')


def open_cling(name):
    """A Klango application, run inside Titan's Cling.

    Cling has no `open` of its own on the bridge - it is an add-on, so it
    is reached the way every add-on is, which is also what makes this work
    on a Titan whose Cling is newer than this add-on.
    """
    return LINK.run_action('cling', 'run', name=name)


def im_modules():
    return _rows('im.modules', 'modules')


def open_im(module):
    return _did('im.open', id=module)


def menu_groups():
    """Titan's own menu bar: `[{'label':…, 'entries':[{'id','label'}]}]`."""
    return _rows('menu.list', 'groups')


def run_menu(entry):
    return _did('menu.run', entry=entry)


def macros():
    """The user's own macros. `[{'name', 'shortcut', 'kind'}]`."""
    return _rows('macros.list', 'macros')


def run_macro(name):
    """Run one of them. Titan answers what it did."""
    return LINK.run_action('macros', 'run_macro', name=name)


def views():
    """The lists Titan's own window is showing."""
    return _rows('views.list', 'views')


# --------------------------------------------------------------------------- #
# Titan's settings, as data
# --------------------------------------------------------------------------- #
def settings(category=''):
    """Every category and every control in Titan's settings window.

    Titan reads this off the window itself (`src/settings/ui_model.py`), so
    a setting added to Titan is here the same day with no table on this
    side to fall out of step - which is the whole reason it is worth
    rendering rather than re-listing.

    ``category`` asks for one of them by name, which is what re-reading a
    page after a setting was changed wants: the whole window is a hundred
    and fifty controls to build a list nobody is looking at.
    """
    if category:
        return _rows('settings.screen', 'categories', category=category)
    return _rows('settings.screen', 'categories')


def set_setting(control, value):
    # **`item`, not `id`.** Read out of Titan's own `bridge_api._settings_set`
    # rather than guessed from the shape of the answer, which carries `id`.
    # A nearly-right argument name is the one bug this bridge keeps
    # producing, and it fails as "nothing happened".
    return _did('settings.set', item=control, value=value)


def press_setting(control):
    return _did('settings.press', item=control)


def save_settings():
    return _did('settings.save')


def cancel_settings():
    return _did('settings.cancel')


# --------------------------------------------------------------------------- #
# What Titan has to say
# --------------------------------------------------------------------------- #
def notifications():
    return _rows('notifications.list', 'notifications')


def clear_notifications():
    return _did('notifications.clear')


def buffers():
    """The buffer CATEGORIES, each carrying its own buffers.

    `categories`, not `buffers` - read off a live Titan. A key nothing
    writes is a working-looking empty list, and this add-on has already
    shipped that bug once (`ai.history`, where every conversation read as
    "nothing has been asked yet").
    """
    return _rows('buffers.list', 'categories')


def read_buffer(name):
    ok, data = LINK.bridge('buffers.read', buffer=name)
    if not ok:
        return False, str(data)
    if isinstance(data, dict):
        rows = data.get('entries') or data.get('lines') or []
        if isinstance(rows, list):
            return True, rows
    return True, []


def statusbar():
    """Titan's status bar, as `[{'key','text'}]`.

    A LIST of applets - the clock, the battery, the volume, the network -
    not one string. Reading it as one is how the whole bar becomes a
    single unreadable line.
    """
    return _rows('statusbar.read', 'items')


def window_state():
    ok, data = LINK.bridge('window.state')
    if not ok:
        return False, str(data)
    return True, data if isinstance(data, dict) else {}


# --------------------------------------------------------------------------- #
# The widgets
# --------------------------------------------------------------------------- #
def widgets():
    return _rows('widgets.list', 'widgets')


#: What Titan calls the thing under a widget's cursor. Read off a live
#: Titan: `widgets.read` and `widgets.move` both answer `{'element': ...}`
#: and nothing else. Looking for `text` or `said` here found neither, so
#: reading a widget came back as the words "element: Top-Left" and MOVING
#: one came back empty - which in the review is a cursor that moves and
#: says nothing at all.
ELEMENT = ('element', 'text', 'said', 'value')


def _element(data):
    if isinstance(data, dict):
        for key in ELEMENT:
            if data.get(key):
                return str(data[key])
        return _summarise(data)
    return str(data or '')


def read_widget(widget):
    ok, data = LINK.bridge('widgets.read', widget=widget)
    if not ok:
        return False, str(data)
    return True, _element(data)


def press_widget(widget):
    return _did('widgets.press', widget=widget)


def move_widget(widget, direction):
    """Move the widget's own cursor. Answers what is under it now.

    The four words Titan's applets really test for are `up`, `down`,
    `left` and `right` - anything else falls through their `navigate()`
    and moves nothing, silently. `next` was what this was written with
    first, and it did exactly that.
    """
    ok, data = LINK.bridge('widgets.move', widget=widget,
                           direction=direction)
    if not ok:
        return False, str(data)
    return True, _element(data)


def _summarise(data):
    """A dict as one readable line, for an answer with no obvious text.

    A widget is somebody else's data structure and this add-on must not
    have an opinion about its shape - what it must not do is show the user
    a JSON document, which is what happens when a renderer meets a key it
    was not expecting.
    """
    parts = []
    for name, value in sorted(data.items()):
        if isinstance(value, (str, int, float)) and str(value):
            parts.append('%s: %s' % (name, value))
    return ', '.join(parts)


# --------------------------------------------------------------------------- #
# Titan's own voice and sounds
# --------------------------------------------------------------------------- #
def say(text, position=None, pitch=None, interrupt=None):
    """Say something in TITAN's voice, not the reader's.

    Worth having beside NVDA's own speech precisely because it is a
    different voice: it is how somebody keeps "the desktop said this"
    apart from "the reader said this", which on a machine where both talk
    is the difference between two sentences and one muddle.
    """
    args = {'text': text}
    if position is not None:
        args['position'] = position
    if pitch is not None:
        args['pitch'] = pitch
    if interrupt is not None:
        args['interrupt'] = interrupt
    return _did('speech.say', **args)


def speech_rate(rate=None):
    """Titan's own speaking rate. Reading it is not a call Titan has."""
    return _did('speech.rate', rate=rate)


def stop_speaking():
    return _did('speech.stop')


#: What Titan says for no, in the one place that has to know. It answers
#: `speech.speaking` with the WORD "no" - and `bool('no')` is True, so a
#: caller reading it as a boolean is told Titan is speaking for ever.
NO = ('no', 'false', '0', '', 'nie')


def speaking():
    ok, data = LINK.bridge('speech.speaking')
    if not ok:
        return False, str(data)
    said = data.get('speaking') if isinstance(data, dict) else data
    if isinstance(said, str):
        return True, said.strip().lower() not in NO
    return True, bool(said)


def sound_theme(name=''):
    """The theme, or the themes there are when nothing is named."""
    if name:
        return _did('sounds.theme', name=name)
    ok, data = LINK.bridge('sounds.theme')
    if not ok:
        return False, str(data)
    if isinstance(data, dict):
        return True, str(data.get('theme') or '')
    return True, ''


def play(sound, pan=None, pitch=None):
    # `name`, `pan`, `pitch` - Titan's own spelling.
    args = {'name': sound}
    if pan is not None:
        args['pan'] = pan
    if pitch is not None:
        args['pitch'] = pitch
    return _did('sounds.play', **args)


def read_buffer_category(name, category='', limit=0):
    args = {'buffer': name}
    if category:
        args['category'] = category
    if limit:
        args['limit'] = limit
    ok, data = LINK.bridge('buffers.read', **args)
    if not ok:
        return False, str(data)
    if isinstance(data, dict):
        rows = data.get('entries') or data.get('lines') or []
        if isinstance(rows, list):
            return True, rows
    return True, []


# --------------------------------------------------------------------------- #
# A Titan application, described rather than drawn
# --------------------------------------------------------------------------- #
# This is the deepest of them, and the one that makes "all of Titan" true
# rather than nearly true. Titan's applications are wxPython programs in
# subprocesses of their own; `src/app_ui` runs one against a shim `wx` that
# DESCRIBES its interface instead of drawing it, and an application whose
# interface cannot be described (a browser is a web view) is read off its
# own window instead and says so. So a reader can build the application's
# screen out of its own native controls, which is a better interface than
# the application's own for somebody who cannot see one.


def describable_applications():
    ok, data = LINK.bridge('app.list')
    if not ok:
        return False, str(data)
    if isinstance(data, list):
        return True, [row for row in data if isinstance(row, dict)]
    return True, []


#: The name this add-on opens applications under, so its own sessions can
#: be told from anybody else's.
OWNER = 'nvda'


def open_described(name, mirror=None):
    """Open a TCE application, or come back to the one already open.

    **Reusing is the whole of it.** Leaving the review does NOT close the
    application - a key that both leaves and quits is a key nobody can use
    safely - so without this, walking away and coming back opened a SECOND
    copy, and a morning's work left five subprocesses of Titan's running
    with nobody rendering any of them. Measured live: three left behind by
    three probes. Coming back to the one that is there is also what the
    user means by opening it again: it is where they left it.
    """
    standing = _ours(name)
    if standing:
        ok, screen = described_screen(standing)
        if ok and screen:
            answer = dict(screen)
            answer.setdefault('session', standing)
            answer.setdefault('application', name)
            return True, answer
    args = {'name': name, 'client': OWNER}
    if mirror is not None:
        args['mirror'] = bool(mirror)
    ok, data = LINK.bridge('app.open', timeout=45, **args)
    if not ok:
        return False, str(data)
    return True, data if isinstance(data, dict) else {}


def _ours(name):
    """The session we already have open for this application, or ''.

    Matched on the application's own name as Titan reports it, and only
    among sessions this add-on opened - somebody else's client rendering
    the same application is not ours to take over.
    """
    ok, rows = described_sessions()
    if not ok:
        return ''
    wanted = str(name or '').strip().lower()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get('owner') or '') != OWNER:
            continue
        for key in ('application', 'title'):
            if str(row.get(key) or '').strip().lower() == wanted:
                return str(row.get('token') or '')
    return ''


def close_all_described():
    """Close every application this add-on left open. Answers how many.

    Called when the plugin goes away: an application nobody is rendering
    is a subprocess of Titan's doing nothing, and NVDA being restarted is
    exactly when nobody is rendering them.
    """
    ok, rows = described_sessions()
    if not ok:
        return 0
    closed = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get('owner') or '') != OWNER:
            continue
        token = str(row.get('token') or '')
        if token and close_described(token)[0]:
            closed += 1
    return closed


def described_screen(session):
    ok, data = LINK.bridge('app.screen', session=session)
    if not ok:
        return False, str(data)
    return True, data if isinstance(data, dict) else {}


def press_described(session, control):
    return _answer('app.press', session=session, control=control)


def set_described(session, control, value):
    return _answer('app.set', session=session, control=control, value=value)


def key_described(session, key, control=None):
    """One key into a described application.

    ``control`` aims it at a field rather than at the window, which is
    what the edit-field mode sends: the field holds the text, so the
    caret arithmetic belongs on that side rather than in the reader.
    """
    if control in (None, ''):
        return _answer('app.key', session=session, key=key)
    return _answer('app.key', session=session, key=key, control=control)


def close_described(session):
    return _did('app.close', session=session)


def application_log(session):
    """What a described application said on its way to saying nothing.

    An application reports a failure the way Titan's own do - it rescues,
    says one sentence and carries on - so "it did nothing" is a report
    with no reason in it, and the reason is always there. This is the one
    call that answers it, and it is worth having in a reader precisely
    because the user cannot see the window it would otherwise be in.
    """
    ok, data = LINK.bridge('app.log', session=session)
    if not ok:
        return False, str(data)
    if not isinstance(data, dict):
        return True, []
    rows = data.get('log')
    lines = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict):
            lines.append('%s: %s' % (row.get('level', ''),
                                     row.get('text', '')))
        else:
            lines.append(str(row))
    if data.get('refused'):
        lines.insert(0, str(data['refused']))
    return True, lines


def ai_available():
    """Whether Titan's AI can answer at all, and why not when it cannot."""
    ok, data = LINK.bridge('ai.available')
    if not ok:
        return False, str(data)
    if isinstance(data, dict):
        return bool(data.get('available')), str(data.get('why') or '')
    return bool(data), ''


def notify(text, title=''):
    """Put something into Titan's own notification centre.

    The reader telling the DESKTOP something, which is the direction that
    was missing: a watched area that changed while the user was in another
    program is news Titan's notification centre already knows how to keep,
    sound and put in its buffers. Titan serves this to any client without
    asking, because a client reporting about itself is not a client
    driving Titan.
    """
    args = {'text': text}
    if title:
        args['title'] = title
    return _did('notifications.add', **args)


def report_context(**what):
    """Tell Titan what NVDA is reading.

    **This is what makes Titan's own subsystems contextual.** Titan cannot
    work out which window the user is really in - on a machine being read,
    the foreground window and the window the user is working in come apart
    constantly - and NVDA can. With this, Titan's AI, its macros and its
    actions can be about the program the user is in rather than about
    whatever happens to be in front.

    It is a SELF-REPORT in Titan's own terms, so it is served without the
    user being asked to allow anything: nothing here changes Titan.
    """
    return _did('client.report', **what)


def described_sessions():
    ok, data = LINK.bridge('app.sessions')
    if not ok:
        return False, str(data)
    return True, data if isinstance(data, list) else []


def local_model():
    """What Titan's local recogniser is, and whether it is here."""
    ok, data = LINK.bridge('ocr.model', timeout=10)
    return (data if ok and isinstance(data, dict) else {})


def install_local_model(timeout=1800):
    """Fetch the local recogniser onto this machine. ``(ok, sentence)``.

    Minutes, and a download - so it is only ever reached from something
    the user pressed, never from a reading.
    """
    ok, data = LINK.bridge('ocr.install_model', timeout=timeout)
    if not ok:
        return False, str(data)
    if not isinstance(data, dict):
        return False, 'Titan answered something else'
    return bool(data.get('ok')), str(data.get('text') or '')


def _answer(call, **args):
    """A call that acts on a described application and answers a screen.

    `said` comes back FIRST and separately because it is news - what the
    application announced - and the screen behind it usually looks exactly
    as it did before. A caller handed only the screen is told nothing at
    all about what happened.
    """
    ok, data = LINK.bridge(call, timeout=30, **args)
    if not ok:
        return False, str(data)
    return True, data if isinstance(data, dict) else {}
