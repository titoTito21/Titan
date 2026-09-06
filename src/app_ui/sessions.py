# -*- coding: utf-8 -*-
"""Which applications are open in described form, and for whom.

**This is deliberately not Elten's.** The Elten bridge is one external
client of Titan and the first to want this, but nothing here knows that:
an application's interface is described as data, and a program that can
reach Titan's Action Bus can render it however it renders anything - in
Elten, in a launcher, on a console, in a script, in Titan's own Invisible
UI. Building it for Elten and generalising later would have been the
mistake `src/settings/ui_model.py` already avoided once, for the same
reason and with the same result: one description, every interface.

A session is a number. A client opens an application, is given one, and
uses it until it closes the application or Titan goes.
"""

import os
import threading

from src.app_ui import host, model

#: More than one client may be showing more than one application, and an
#: application left open by a client that has gone must not be forgotten
#: about - it is a process.
MAX_SESSIONS = 12

_LOCK = threading.RLock()
_OPEN = {}
_NEXT = [0]


class Session(object):
    def __init__(self, token, application, owner=''):
        self.token = token
        self.application = application
        self.owner = str(owner or '')

    def alive(self):
        return not self.application.ended.is_set()


def applications(language='en'):
    """Every TCE application that can be opened this way.

    Read from `app_manager`, so it is the same list Titan's own window
    shows and an application installed a minute ago is on it.
    """
    from src.titan_core import app_manager
    found = []
    for info in app_manager.get_applications() or []:
        entry = _entry_of(info)
        if not entry:
            continue
        found.append({'name': _named(info, language),
                      'id': str(info.get('shortname') or
                                os.path.basename(info.get('path', ''))),
                      'path': info.get('path', ''),
                      'entry': entry,
                      'names': _every_name(info),
                      'describable': True})
    return found


def _every_name(info):
    """Every spelling this application answers to.

    **Whatever language the list was read in, that is the name the user
    pressed.** A client shows the applications in the user's own language
    and then asks for the one they chose - "Notatki" - and looking for
    that under a single language answered "there is no TCE application
    called 'Notatki'" about the application sitting in the list they had
    just pressed. `bridge_api._open_app` has always known this; this did
    not.
    """
    names = set()
    for key in ('name', 'name_en', 'name_pl', 'shortname'):
        value = str(info.get(key) or '').strip().strip('"')
        if value:
            names.add(value.lower())
    path = info.get('path') or ''
    if path:
        names.add(os.path.basename(path).lower())
        # Any language Titan has, not only the two written above: an
        # application is free to carry `name_de` and a German Titan will
        # show it.
        try:
            from src.titan_core import app_manager
            for language in _languages():
                other = app_manager.read_app_info(path, language) or {}
                for key in ('name', 'name_%s' % language):
                    value = str(other.get(key) or '').strip().strip('"')
                    if value:
                        names.add(value.lower())
        except Exception:
            pass
    return sorted(names)


def _languages():
    try:
        from src.titan_core.translation import get_available_languages
        return list(get_available_languages() or ())
    except Exception:
        return ['en', 'pl']


def _named(info, language):
    for key in ('name_%s' % (language or 'en'), 'name_en', 'name_pl', 'name'):
        value = str(info.get(key) or '').strip().strip('"')
        if value:
            return value
    return os.path.basename(info.get('path', ''))


def _entry_of(info):
    folder = info.get('path') or ''
    opens = str(info.get('openfile') or '').strip().strip('"')
    if not folder or not opens:
        return ''
    entry = os.path.join(folder, opens)
    return entry if os.path.isfile(entry) else ''


def find(name, language='en'):
    """One application by any name it answers to.

    Exactly by one of its spellings first, then by a spelling containing
    what was asked for - so "notes" finds the Notes application without
    "no" finding it by accident.
    """
    wanted = str(name or '').strip().lower()
    if not wanted:
        return None
    listing = applications(language)
    for entry in listing:
        if wanted in entry.get('names') or []:
            return entry
    for entry in listing:
        if any(wanted in one for one in entry.get('names') or []):
            return entry
    return None


def open_application(name, owner='', language='en', mirror=None):
    """Start one and hand back its session. (session, problem).

    **Described first, mirrored only when it cannot be.** An application
    whose interface IS a web view or a media surface has nothing to
    describe - the shim refuses it by name - and refusing on Titan's side
    too would leave the user with nothing at all. So that application is
    launched in its own real window instead and READ off it, which is a
    weaker thing and says so.

    `mirror` forces the choice: True reads the window even for an
    application that could describe itself, False refuses rather than
    falling back.
    """
    entry = find(name, language)
    if entry is None:
        return None, "There is no TCE application called %r." % name
    with _LOCK:
        _reap()
        if len(_OPEN) >= MAX_SESSIONS:
            return None, "Too many applications are open this way already."
    if mirror is True:
        application = _mirror(entry)
    else:
        application = host.Application(entry['entry'], entry['name'])
        if not application.start():
            if mirror is False or not _can_be_mirrored(application):
                return None, (application.detail
                              or "%s could not be started." % entry['name'])
            described = application.detail
            application = _mirror(entry)
            if application is not None and application.status == 'failed':
                # Say BOTH: why it could not describe itself and why the
                # window could not be read either. One without the other
                # is half an answer.
                return None, '%s %s' % (described, application.detail)
    if application is None:
        return None, ("%s cannot be described, and this machine cannot "
                      "read another program's window." % entry['name'])
    if application.status == 'failed':
        return None, (application.detail
                      or "%s could not be started." % entry['name'])
    with _LOCK:
        _NEXT[0] += 1
        session = Session(_NEXT[0], application, owner)
        _OPEN[session.token] = session
    return session, ''


#: What the shim refuses that a window can still show. A timer is not one
#: of these - plenty of applications ask for one and describe themselves
#: perfectly well without it.
MIRRORABLE = ('wx.html2', 'wx.media', 'wx.glcanvas')


def _can_be_mirrored(application):
    """Is this an application that has nothing to DESCRIBE, rather than one
    that is simply broken?

    An application that fails on its own first line - a missing library, a
    syntax error - would fail in a window too, and putting one up to prove
    it wastes the user's time and leaves a process behind.
    """
    return any(entry.get('what') in MIRRORABLE
               for entry in getattr(application, 'refused', []) or [])


def _mirror(entry):
    try:
        from src.app_ui import mirror as mirror_module
    except Exception:
        return None
    if not mirror_module.available():
        return None
    application = mirror_module.Mirror(entry['entry'], entry['name'])
    application.start()
    return application


def get(token):
    with _LOCK:
        session = _OPEN.get(_number(token))
    if session is None:
        return None
    if not session.alive():
        close(token)
        return None
    return session


def close(token):
    with _LOCK:
        session = _OPEN.pop(_number(token), None)
    if session is None:
        return False
    try:
        session.application.stop()
    except Exception:
        pass
    return True


def close_all():
    """Titan is going. Every described application goes with it - each one
    is a process of its own and would otherwise outlive the desktop that
    started it."""
    with _LOCK:
        tokens = list(_OPEN)
    for token in tokens:
        close(token)


def open_sessions():
    with _LOCK:
        _reap()
        return [{'token': session.token,
                 'application': session.application.name,
                 'owner': session.owner,
                 'mirror': bool(getattr(session.application, 'mirrored', False)),
                 'title': (session.application.screen or {}).get('title', '')}
                for session in _OPEN.values()]


def _reap():
    for token, session in list(_OPEN.items()):
        if not session.alive():
            _OPEN.pop(token, None)


def _number(token):
    try:
        return int(token)
    except (TypeError, ValueError):
        return -1


def spoken(screen):
    """A whole screen as sentences - the floor under every renderer.

    A client that cannot build controls can still say what is there, and
    something said is better than an interface silently missing. It is
    also what the Invisible UI and a Titan Script want, since neither has
    anything to draw with.
    """
    if not screen:
        return []
    lines = [screen.get('title') or '']
    for control in screen.get('controls') or []:
        said = model.readable(control)
        if said:
            lines.append(said)
    return [line for line in lines if line]
