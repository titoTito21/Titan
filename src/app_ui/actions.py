# -*- coding: utf-8 -*-
"""A TCE application, as something any part of Titan can drive.

`app_ui.*` on the Action API, so a macro, a component, an add-on or an
external client on the Action Bus can open a Titan application and work
it - without the application being modified and without a window ever
appearing.

The prose here is for a person and for a model. **A program rebuilding
the interface should use `titan.bridge`'s `app.*` instead**, which
answers JSON in one shape: this repository has already paid for the
difference once, when the Elten bridge read a macro's name out of a
sentence and got the whole line.
"""

import json

from src.app_ui import model, sessions


def app_ui_list(**_arguments):
    """Every TCE application that can be opened this way."""
    found = sessions.applications()
    if not found:
        return "There are no TCE applications installed."
    return '\n'.join('%s (%s)' % (entry['name'], entry['id'])
                     for entry in found)


def app_ui_open(name='', mirror='', **_arguments):
    """Open one, and say what is on its first screen."""
    wanted = None
    if str(mirror).strip().lower() in ('1', 'true', 'yes', 'tak'):
        wanted = True
    elif str(mirror).strip().lower() in ('0', 'false', 'no', 'nie'):
        wanted = False
    session, problem = sessions.open_application(name, owner='action',
                                                 mirror=wanted)
    if session is None:
        return problem
    lines = ['%s is open, session %d.'
             % (session.application.name, session.token)]
    if getattr(session.application, 'mirrored', False):
        lines.append("It cannot describe its own interface, so this is "
                     "what Windows can see of its window instead.")
    lines.extend(sessions.spoken(session.application.screen))
    if session.application.refused:
        lines.append('It asked for something this cannot be: %s'
                     % ', '.join(entry['what']
                                 for entry in session.application.refused))
    return '\n'.join(lines)


def app_ui_screen(session='', **_arguments):
    """What the application is showing now."""
    held = sessions.get(session)
    if held is None:
        return "There is no application open with that session."
    screen = held.application.screen or {}
    lines = sessions.spoken(screen)
    controls = screen.get('controls') or []
    if controls:
        lines.append('')
        lines.extend('%s: %s' % (control['id'], model.readable(control))
                     for control in controls)
    for menu in screen.get('menus') or []:
        lines.append('menu %s: %s' % (menu.get('label', ''), ', '.join(
            item.get('label', '') for item in menu.get('items') or []
            if item.get('label'))))
    return '\n'.join(lines) or "It is showing nothing."


def app_ui_press(session='', control='', **_arguments):
    """Press a button, open a row, choose a menu item - by its number."""
    held = sessions.get(session)
    if held is None:
        return "There is no application open with that session."
    held.application.tell('press', control=_number(control))
    return app_ui_screen(session=session)


def app_ui_set(session='', control='', value='', **_arguments):
    """Type into a field, tick a box, choose an option - by its number."""
    held = sessions.get(session)
    if held is None:
        return "There is no application open with that session."
    held.application.tell('set', control=_number(control), value=value)
    return app_ui_screen(session=session)


def app_ui_key(session='', key='', **_arguments):
    """Press a key the application itself listens for - F5, Escape, Ctrl+S."""
    held = sessions.get(session)
    if held is None:
        return "There is no application open with that session."
    held.application.tell('key', key=str(key or ''))
    return app_ui_screen(session=session)


def app_ui_close(session='', **_arguments):
    """Close it."""
    if sessions.close(session):
        return "Closed."
    return "There is no application open with that session."


def app_ui_open_sessions(**_arguments):
    """Which applications are open this way, and for whom."""
    open_now = sessions.open_sessions()
    if not open_now:
        return "No TCE application is open in described form."
    return '\n'.join(
        '%(token)s: %(application)s%(where)s'
        % dict(entry, where=(' - %s' % entry['title']) if entry['title'] else '')
        for entry in open_now)


def app_ui_log(session='', **_arguments):
    """What the application said, including what it stopped on.

    The same answer `elten.log` gives for an Elten application, and for
    the same reason: an application that does nothing and says nothing is
    a report with no reason in it, and the reason was always there.
    """
    held = sessions.get(session)
    if held is None:
        return "There is no application open with that session."
    log = held.application.log
    if not log:
        return "%s has logged nothing." % held.application.name
    return '\n'.join('%s: %s' % (level, text) for level, text in log[-60:])


def _number(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


#: Declared the way a component declares its own - name, label, summary,
#: params, and a real callable.
TITAN_ACTIONS = [
    {'name': 'list', 'label': 'TCE applications that can be described',
     'summary': ('Every TCE application that can be opened with its '
                 'interface described as data rather than drawn.'),
     'run': app_ui_list, 'params': {}},
    {'name': 'open', 'label': 'Open a TCE application, described',
     'summary': ('Start a TCE application with no window: its interface '
                 'is described, so any interface can render it. Answers '
                 'with the session number to use afterwards.'),
     'run': app_ui_open,
     'params': {'name': {'type': 'string', 'required': True,
                         'description': 'The application, by name or short name.'},
                'mirror': {'type': 'string',
                           'description': ('Force reading its real window '
                                           'instead of asking it to '
                                           'describe itself. Left out, it '
                                           'describes itself where it can '
                                           'and is read where it cannot.')}}},
    {'name': 'screen', 'label': 'What it is showing',
     'summary': "The application's interface right now, control by control.",
     'run': app_ui_screen,
     'params': {'session': {'type': 'string', 'required': True,
                            'description': 'The session number.'}}},
    {'name': 'press', 'label': 'Press something in it',
     'summary': 'Press a control by the number the screen gave it.',
     'run': app_ui_press,
     'params': {'session': {'type': 'string', 'required': True,
                            'description': 'The session number.'},
                'control': {'type': 'string', 'required': True,
                            'description': "The control's number."}}},
    {'name': 'set', 'label': 'Change a value in it',
     'summary': 'Type into a field, tick a box, choose a row or an option.',
     'run': app_ui_set,
     'params': {'session': {'type': 'string', 'required': True,
                            'description': 'The session number.'},
                'control': {'type': 'string', 'required': True,
                            'description': "The control's number."},
                'value': {'type': 'string',
                          'description': ('The text, or the number of the '
                                          'row or option.')}}},
    {'name': 'key', 'label': 'Press a key in it',
     'summary': ("A key the application itself listens for - F5, Escape, "
                 "Ctrl+S - rather than one a control would take."),
     'run': app_ui_key,
     'params': {'session': {'type': 'string', 'required': True,
                            'description': 'The session number.'},
                'key': {'type': 'string', 'required': True,
                        'description': "The key, like 'f5' or 'ctrl+s'."}}},
    {'name': 'close', 'label': 'Close it',
     'summary': 'Close a described application.',
     'run': app_ui_close,
     'params': {'session': {'type': 'string', 'required': True,
                            'description': 'The session number.'}}},
    {'name': 'sessions', 'label': 'What is open',
     'summary': 'Which TCE applications are open in described form.',
     'run': app_ui_open_sessions, 'params': {}},
    {'name': 'log', 'label': 'What it said',
     'summary': ("The application's own log, including the exception it "
                 "stopped on. Read this when it does nothing and says "
                 "nothing."),
     'run': app_ui_log,
     'params': {'session': {'type': 'string', 'required': True,
                            'description': 'The session number.'}}},
]
