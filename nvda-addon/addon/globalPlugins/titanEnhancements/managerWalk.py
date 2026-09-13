# -*- coding: utf-8 -*-
"""What the user has made, walked instead of shown.

:mod:`managerGui` and :mod:`classManager` put these up as tabbed
`wx.Dialog`s, and those windows are worth keeping: **editing wants a
form**. Setting a voice's pitch is a slider, recording a procedure is a
sequence of presses, and pretending a list can do either would be worse
than the dialog.

What a list IS good for is the other half, and it is the half people do
far more often: seeing what is there. Which markers exist, which programs
have their own answers, what a control was renamed to, which states have
a sound instead of a word. That is a question asked twenty times for
every time something is edited, and asking it should not mean a modal
window that takes the foreground and says each answer once.

So every page here is a list, Enter says a row in full, and each level
carries **one row that opens the real form** - which is where anything
that must be edited is edited. The two are the same data: these read the
very modules the dialogs read (:mod:`markers`, :mod:`perProgram`,
:mod:`procedures`, :mod:`labels`, :mod:`monitors`, :mod:`icons`,
:mod:`schemes`, :mod:`classes`), so neither can show something the other
has not got.
"""

import threading

from . import i18n

_ = i18n.install(globals())

_LOCK = threading.RLock()

_counted = {'opened': 0, 'pages': 0, 'rows': 0}


def report():
    with _LOCK:
        return dict(_counted)


def forget():
    with _LOCK:
        for key in _counted:
            _counted[key] = 0


def _text(value):
    return str(value or '').strip()


def _rows_of(work):
    """One page's rows, never raising. ``[]`` when the module cannot say."""
    try:
        found = work()
    except Exception:                                # noqa: BLE001
        return []
    if isinstance(found, dict):
        return ['%s: %s' % (key, found[key]) for key in sorted(found)]
    made = []
    for one in (found or []):
        if isinstance(one, dict):
            said = ', '.join('%s: %s' % (key, one[key])
                             for key in sorted(one) if one[key] not in
                             (None, '', [], {}))
        elif isinstance(one, (list, tuple)):
            said = ', '.join(str(part) for part in one if part)
        else:
            said = str(one)
        said = _text(said)
        if said:
            made.append(said)
    return made


# --------------------------------------------------------------------------- #
# What is on each page
# --------------------------------------------------------------------------- #
def _markers():
    from . import markers
    return _rows_of(markers.all_markers)


def _programs():
    from . import perProgram
    return _rows_of(perProgram.all_programs)


def _procedures():
    from . import procedures
    return _rows_of(procedures.all_procedures)


def _names():
    from . import labels
    return _rows_of(labels.everything)


def _monitors():
    from . import monitors
    return _rows_of(monitors.all_monitors)


def _icons():
    """Each icon: what it marks, whether it plays, where its sound is
    from - in words, because a walked row is READ."""
    from . import icons
    made = []
    try:
        sources = icons.source_names()
        for row in icons.described():
            made.append('%s: %s, %s, %s' % (
                row['id'], row['meaning'],
                # Translators: whether an auditory icon plays.
                _('on') if row['on'] else _('off'),
                sources.get(row['source'], row['source'])))
    except Exception:                                # noqa: BLE001
        return []
    return made


def _scheme():
    """Each state: how it is answered and where its sound comes from."""
    from . import schemes
    made = []
    try:
        ways = schemes.way_names()
        sources = schemes.source_names()
        for row in schemes.described():
            made.append('%s: %s, %s' % (
                row['label'], ways.get(row['way'], row['way']),
                sources.get(row['source'], row['source'])))
    except Exception:                                # noqa: BLE001
        return []
    return made


def _voices():
    from . import classes
    made = []
    try:
        for tag in sorted(classes.meanings()):
            made.append('%s: %s' % (classes.label_of(tag),
                                    classes.meanings().get(tag, '')))
    except Exception:                                # noqa: BLE001
        return []
    return made


def _reading_order():
    from . import classes
    return _rows_of(classes.part_names)


#: Every page of both dialogs, and where its rows come from. The names are
#: the dialogs' own tab labels, so somebody who knows one knows the other.
PAGES = (
    ('markers', lambda: _('Place markers'), _markers),
    ('programs', lambda: _('Programs'), _programs),
    ('procedures', lambda: _('Scripts'), _procedures),
    ('names', lambda: _('Control names'), _names),
    ('monitors', lambda: _('Watched areas'), _monitors),
    ('icons', lambda: _('Auditory icons'), _icons),
    ('scheme', lambda: _('Sound scheme'), _scheme),
    ('voices', lambda: _('Voices'), _voices),
    ('order', lambda: _('Reading order'), _reading_order),
)


# --------------------------------------------------------------------------- #
# Walking it
# --------------------------------------------------------------------------- #
#: Which pages belong to which dialog, so "open as a form" opens the one
#: that really edits them - the voices and the reading order live in the
#: class manager, everything else in the manager.
THE_CLASS_MANAGER = ('voices', 'order')


def open_it(only=()):
    """The pages, as a list. ``(ok, said)``.

    ``only`` narrows it to some of them, which is what the voice-classes
    command opens: the same walker, showing its own two pages.
    """
    from . import palette
    rows = []
    for key, name, _fetch in PAGES:
        if only and key not in only:
            continue
        rows.append({'label': name(),
                     # Translators: what a row of the manager window is.
                     'role': _('page'),
                     'icon': 'open-object',
                     'run': (lambda which=key: _open_page(which))})
    # **The form is a row, not a button.** Anything that must be EDITED is
    # edited there; this list is for seeing what is there, which is the
    # question asked far more often.
    which = 'classes' if only and set(only) <= set(THE_CLASS_MANAGER) \
        else 'manager'
    rows.append({'label': _('Open as a form'), 'role': _('page'),
                 'run': (lambda one=which: _as_a_form(one))})
    with _LOCK:
        _counted['opened'] += 1
    # Translators: the title of the manager, walked.
    return palette.show(rows, _('What you have made'))


def _open_page(which):
    from . import palette
    for key, name, fetch in PAGES:
        if key != which:
            continue
        with _LOCK:
            _counted['pages'] += 1
        lines = fetch()
        with _LOCK:
            _counted['rows'] += len(lines)
        if not lines:
            # Translators: said when a page of the manager is empty.
            return False, _('Nothing here yet')
        rows = [{'label': one, 'role': '',
                 'run': (lambda said=one: (True, said))} for one in lines]
        which = 'classes' if key in THE_CLASS_MANAGER else 'manager'
        rows.append({'label': _('Open as a form'), 'role': '',
                     'run': (lambda one=which: _as_a_form(one))})
        return palette.show(rows, name(), back=open_it)
    return False, ''


def _as_a_form(which='manager'):
    """The real dialog, where things are edited."""
    from . import palette
    palette.stop()
    try:
        if which == 'classes':
            from . import classManager
            if classManager.show():
                return True, ''
            # Translators: said when the voice classes cannot be opened.
            return False, _('The voice classes need NVDA\'s own interface.')
        from . import managerGui
        if managerGui.show():
            return True, ''
    except Exception:                                # noqa: BLE001
        pass
    # Translators: said when the manager window cannot be opened.
    return False, _('The manager needs NVDA\'s own interface.')
