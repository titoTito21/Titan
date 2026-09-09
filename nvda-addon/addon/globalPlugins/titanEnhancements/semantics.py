# -*- coding: utf-8 -*-
"""What a control MEANS inside a Titan application.

NVDA reads a window. A screen reader with an app module for that program
reads the PROGRAM: JAWS has known for twenty years that the third row of
this particular list is a file and not "list item 3", and that is not a
cosmetic difference - it is the difference between a list you can use and
one you have to explore. Titan is a whole desktop with a dozen
applications of its own, every one of them written for people who cannot
see it, and NVDA knew nothing about any of them.

This is that layer, and it is deliberately built the way the rest of this
add-on is: **asked of Titan, not guessed from a window.**

* **Which application a window belongs to is asked of Titan.** A TCE
  application runs in a subprocess of its own, so from the outside tNotes
  is an unremarkable wxPython window - the same class, the same roles, the
  same everything as any other. Titan knows which process is which,
  because a TCE add-on says so when it joins the Action Bus, and
  ``addons.list`` now answers it (``pid``). Nothing here matches on a
  window title, a class name or an executable, all of which are shared,
  translated or both.
* **What a row IS comes from the list itself.** A Titan application's
  list is a real report-mode ``SysListView32`` with real column headers -
  "Name", "Type", "Date modified" - and NVDA can read both. So the row is
  read as what its own application says it is, in the user's own language,
  with no table of translated words here that would go stale the day
  somebody adds a column.
* **What is written down is only what cannot be read.** :data:`KNOWN` says
  which column of an application's list names the KIND of thing a row is,
  and what to call a row when there is no such column - three lines per
  application, read out of each one's own source. Everything else is
  discovered.

**An application nobody has written a line for still gains most of it.**
The columns, the count, the place in the list and the window's own context
are all generic; the entry in :data:`KNOWN` only sharpens the noun. That is
the whole reason this is not a table of scripts.
"""

import threading
import time

from . import compat

#: pid -> {'id', 'label', 'kind'}, from Titan's own registry.
_LOCK = threading.RLock()
_by_pid = {}
_asked = 0.0

#: How long the map may be believed. It is refreshed whenever the action
#: catalogue is swept (which happens the moment Titan connects), so this is
#: only the ceiling for an application the user started since.
MAP_SECONDS = 30.0

#: An application's list can be long, and a row read with every column is
#: already more than NVDA said. Past this many columns the rest are left to
#: the reader's own table navigation, which is what it is for.
MAX_COLUMNS = 6

#: How much of one cell is worth saying in a row. A path or a URL in a
#: column is a sentence on its own.
CELL_LIMIT = 120


# --------------------------------------------------------------------------- #
# What is written down, and why each line is here
#
# `kind_column` is the column that already NAMES what a row is - the file
# manager's "Type" column says "Folder" or "Text file", in the user's own
# language, written by the application itself. Where there is one, that word
# is what the row is called and nothing here has to know it.
#
# `noun` is what a row is when there is no such column: a note is a note, a
# download is a download. One word, and it is this add-on's to translate
# because the application never says it out loud.
#
# `context` is whether the window's own title is a PLACE - the file manager
# titles itself with the folder you are in, so the title changing is you
# having moved, which is the single thing NVDA has no way to notice.
# --------------------------------------------------------------------------- #
def _(text):
    from . import i18n
    return i18n.install({})(text)


#: **The floor under :mod:`readerModules`.** These are the same facts, and
#: they were here first; they stay because a module is data that can be
#: missing, mistyped or deleted by a user, and the applications Titan ships
#: should be understood by an add-on whose module folder is empty. A module
#: for the same application wins - it is more specific, it can be corrected
#: without rebuilding the add-on, and it can say things this shape cannot.
KNOWN = {
    # data/applications/TFM/gui.py: columns Name / Date modified / Type,
    # lists named "File list", "Left panel", "Right panel"; the frame is
    # titled with the folder it is showing.
    'tfm': {'kind_column': 2, 'noun': 'file', 'context': True},
    # data/applications/tNotes/notes.py: Note title / Date created / Date
    # modified, and a row is a note or a folder - which the columns do NOT
    # say, so the noun is the floor and the folder is recognised by having
    # no dates.
    'tnotes': {'noun': 'note', 'context': True},
    # data/applications/tDownloader/downloader.py: File name / Link.
    'tdm': {'noun': 'download', 'context': False},
    # data/applications/tReminder/reminder.py: Name / Description / Date /
    # Time / Priority.
    'reminder': {'noun': 'reminder', 'context': False},
    # data/applications/tEdit/tedit.py titles itself "<file> - TEdit", so
    # the title is which document this is.
    'tedit': {'noun': '', 'context': True},
    # data/applications/tWeb/web.py titles itself "<page> - tBrowser".
    'web': {'noun': '', 'context': True},
    'elevenlabs': {'noun': 'voice', 'context': False},
}

#: The nouns above, as words. Kept apart from the table so the table stays
#: a table of facts about applications and the words stay translatable.
def _noun(name):
    return {
        # Translators: what one row of a Titan application's list is.
        'file': _('file'),
        'note': _('note'),
        'download': _('download'),
        'reminder': _('reminder'),
        'voice': _('voice'),
    }.get(name, '')


# --------------------------------------------------------------------------- #
# Which application this window is
# --------------------------------------------------------------------------- #
def _rows_by_pid(rows):
    found = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        try:
            pid = int(row.get('pid') or 0)
        except (TypeError, ValueError):
            continue
        if pid <= 0:
            continue
        found[pid] = {'id': str(row.get('id') or ''),
                      'label': str(row.get('label') or ''),
                      'kind': str(row.get('kind') or '')}
    return found


def note_processes(rows):
    """Which process is which part of Titan, from ``titan.processes``.

    Authoritative, and the only source that carries the applications with
    no actions of their own - which are exactly the ones nothing else
    knows anything about. It replaces what was known rather than adding to
    it: an application that has been closed must stop being answered, or a
    pid Windows has handed to somebody else is read as tNotes.
    """
    found = _rows_by_pid(rows)
    with _LOCK:
        globals()['_by_pid'] = found
        globals()['_asked'] = time.time()
    return len(found)


def note_addons(rows):
    """The same, out of the ``addons.list`` the action catalogue is built
    from - so a sweep keeps this current at no call of its own.

    Merged rather than replacing, because that answer carries only the
    add-ons that joined the Action Bus and this may already know about an
    application that did not.
    """
    found = _rows_by_pid(rows)
    if not found:
        return 0
    with _LOCK:
        _by_pid.update(found)
        globals()['_asked'] = time.time()
    return len(found)


def known_processes():
    with _LOCK:
        return dict(_by_pid)


def forget():
    with _LOCK:
        globals()['_by_pid'] = {}
        globals()['_asked'] = 0.0


def stale():
    """Whether the map is old enough to be worth asking for again."""
    with _LOCK:
        return (time.time() - _asked) > MAP_SECONDS


_refreshing = False


def refresh(then=None):
    """Ask Titan which process each of its add-ons is, on a worker.

    **Never on the focus path.** This is reached because a window was
    focused that we do not recognise, and a bridge call there would stop
    the reader for as long as Titan took to answer. So the answer arrives
    late and the control that provoked it is read as NVDA would have read
    it - which is exactly one control, once, when an application starts.
    """
    global _refreshing
    with _LOCK:
        if _refreshing:
            return False
        _refreshing = True

    def look():
        global _refreshing
        try:
            from .link import LINK
            # `titan.processes` and not `addons.list`: the second answers
            # only the add-ons that joined the bus, and the applications
            # with no actions of their own are the ones that most need a
            # reader to know what they are.
            ok, data = LINK.bridge('titan.processes', timeout=8.0)
            if ok and isinstance(data, dict):
                note_processes(data.get('processes'))
            else:
                ok, data = LINK.bridge('addons.list', timeout=8.0)
                if ok and isinstance(data, dict):
                    note_addons(data.get('addons'))
            if ok and then is not None:
                then()
        except Exception:                            # noqa: BLE001
            pass
        finally:
            with _LOCK:
                globals()['_refreshing'] = False
                globals()['_asked'] = time.time()
    threading.Thread(target=look, name='TitanSemantics',
                     daemon=True).start()
    return True


def refresh_if_stale():
    """A window we do not know may be an application that has just started.

    Asked at most every :data:`MAP_SECONDS`, and only while Titan is
    there, so a machine full of other people's programs costs one flag
    read per focus event.
    """
    if not stale():
        return False
    try:
        from .link import LINK
        if not LINK.connected():
            return False
    except Exception:                                # noqa: BLE001
        return False
    return refresh()


def application_of(obj):
    """The Titan add-on whose window this is, or None.

    Matched on the PROCESS, which is the only thing that is really true:
    every wxPython program shares a window class, and a title is written by
    the application in the user's own language.
    """
    if obj is None:
        return None
    try:
        pid = int(getattr(obj, 'processID', 0) or 0)
    except (TypeError, ValueError):
        return None
    if not pid:
        return None
    with _LOCK:
        known = _by_pid.get(pid)
    if known is None:
        # It may be an application the user started since we last asked.
        refresh_if_stale()
    return known


def wanted():
    from . import configSpec
    return bool(configSpec.read().get('appSemantics', True))


def modules_wanted():
    from . import configSpec
    return bool(configSpec.read().get('readerModules', True))


def module_for(obj, application=None):
    """The reader module for this window, or None. One lookup, cached."""
    if not modules_wanted():
        return None
    try:
        from . import readerModules
        return readerModules.for_object(obj, application)
    except Exception:                                # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# Reading a row as what it is
# --------------------------------------------------------------------------- #
def _list_of(obj):
    """The list a row belongs to, or None."""
    try:
        parent = obj.parent
    except Exception:                                # noqa: BLE001
        return None
    return parent


def columns_of(obj):
    """``[(header, cell)]`` for a row of a report-mode list.

    NVDA reads the header and the cell out of the list control itself
    (``sysListView32.ListItem``), so the words are the application's own,
    already translated, and a column added tomorrow is read tomorrow. An
    NVDA - or a control - that cannot answer gives nothing, which is the
    row read exactly as it was before.
    """
    content = getattr(obj, '_getColumnContent', None)
    if not callable(content):
        return []
    header = getattr(obj, '_getColumnHeader', None)
    count = 0
    parent = _list_of(obj)
    for source in (parent, obj):
        try:
            count = int(getattr(source, 'columnCount', 0) or 0)
        except (TypeError, ValueError):
            count = 0
        if count:
            break
    if count <= 1:
        return []
    out = []
    # One based, as NVDA's own comment says: "the column as presented to
    # the user".
    for index in range(1, min(count, MAX_COLUMNS) + 1):
        try:
            cell = content(index)
        except Exception:                            # noqa: BLE001
            continue
        cell = str(cell or '').strip()
        if not cell:
            continue
        title = ''
        if callable(header):
            try:
                title = str(header(index) or '').strip()
            except Exception:                        # noqa: BLE001
                title = ''
        out.append((title, cell[:CELL_LIMIT]))
    return out


def _is_row(obj):
    from . import earcons
    role = str(getattr(getattr(obj, 'role', None), 'name', '') or '').upper()
    return role in earcons.LIST_ITEM


def _rule_for(obj, application, module, cells):
    """The list rule in force: the module's, or the built-in floor.

    Answered as one shape whichever it came from, so everything below has
    one thing to read. ``kind_column`` is a HEADING in a module and was an
    INDEX in the built-in table - a module names the column because that is
    what its author hears, and an index is what somebody counting columns
    in the source wrote. Both end up as an index here.
    """
    headings = [title for title, _cell in cells]
    if module is not None:
        try:
            found = module.list_rule(obj, application, headings)
        except Exception:                            # noqa: BLE001
            found = None
        if found is not None:
            wanted = found.get('kind_column')
            index = None
            if isinstance(wanted, int):
                index = wanted
            elif wanted:
                lowered = [title.lower() for title in headings]
                if str(wanted).lower() in lowered:
                    index = lowered.index(str(wanted).lower())
            quiet = {str(one).lower() for one in (found.get('quiet') or ())}
            return {'kind_column': index, 'noun': found.get('noun', ''),
                    'quiet': quiet, 'replace': bool(found.get('replace'))}
    known = KNOWN.get(str((application or {}).get('id') or ''), {})
    at = known.get('kind_column')
    return {'kind_column': at if isinstance(at, int) else None,
            'noun': known.get('noun', ''), 'quiet': set(), 'replace': False}


def row_parts(obj, application, module=None):
    """The row, as ``[(text, pitch)]``, or ``[]`` when it is not one.

    The shape is Titan Access's own and deliberately not a new one: the
    NAME at the neutral tone, what the row IS a little lower, and
    everything else after it - so a row of a Titan application sounds like
    every other control on this desktop.
    """
    from . import elements
    cells = columns_of(obj)
    if not cells:
        return []
    rule = _rule_for(obj, application, module, cells)
    name = cells[0][1]
    parts = [(name, elements.NAME_PITCH)]

    kind_at = rule['kind_column']
    kind = ''
    if isinstance(kind_at, int) and 0 <= kind_at < len(cells):
        # The application's own word for what this row is, written by the
        # application, in the user's own language.
        kind = cells[kind_at][1]
    if not kind:
        kind = _noun(rule.get('noun', ''))
    if kind:
        parts.append((kind, elements.ROLE_PITCH))

    for index, (title, cell) in enumerate(cells):
        if index == 0 or index == kind_at:
            continue
        if title and title.lower() in rule['quiet']:
            # A column a module has quietened is still there for the
            # reader's own table navigation; it is simply not read on
            # every arrow key. A URL in the middle of a row is a sentence.
            continue
        # "Date modified: yesterday" - the column's own name, because a
        # bare date in the middle of a row is a number nobody can place.
        parts.append(('{}: {}'.format(title, cell) if title else cell,
                      elements.NAME_PITCH))
    return parts


# --------------------------------------------------------------------------- #
# Where the user now IS
# --------------------------------------------------------------------------- #
_titles = {}


def context_change(obj, application, module=None):
    """The window's own title, when it has changed since we were last here.

    The file manager titles its window with the folder it is showing, and
    the editor with the document - so opening a folder or a file changes
    nothing NVDA reports: the focus never left the list, and the user is
    told the name of a row in a place they were not told they had moved to.
    This is the same answer Titan's own shell arrived at for its file
    browser (`announce_shell_location`), applied to the applications.

    Said once per change, and only for an application whose title really is
    a place - a window called "Download Manager" says the same thing for
    ever, and announcing it would be a word before every row.
    """
    place = False
    if module is not None:
        place = bool(getattr(module, 'title_is_a_place', False))
    if not place:
        known = KNOWN.get(str((application or {}).get('id') or ''), {})
        place = bool(known.get('context'))
    if not place:
        return ''
    try:
        window = int(getattr(obj, 'windowHandle', 0) or 0)
    except (TypeError, ValueError):
        return ''
    if not window:
        return ''
    title = ''
    try:
        top = obj
        for _step in range(12):
            parent = getattr(top, 'parent', None)
            if parent is None:
                break
            top = parent
        title = str(getattr(top, 'name', '') or '').strip()
    except Exception:                                # noqa: BLE001
        title = ''
    if not title:
        try:
            title = str(obj.windowText or '').strip()
        except Exception:                            # noqa: BLE001
            title = ''
    if not title:
        return ''
    key = int(getattr(obj, 'processID', 0) or 0)
    with _LOCK:
        if _titles.get(key) == title:
            return ''
        _titles[key] = title
    return title


def forget_titles():
    with _LOCK:
        _titles.clear()


# --------------------------------------------------------------------------- #
# The same, for the rest of Windows
#
# A sighted person does not read a window - they SEE it, and three things
# arrive before a single word: what part of the window this is (a toolbar,
# a status bar, the list, the document), what kind of thing they are looking
# at, and whether it can be used at all. A reader gives you the name and the
# control type, one control at a time, and everything else has to be gone
# looking for.
#
# Titan's own interface was built to give those back - a control sounds from
# where it is, its type is a tone rather than a word, a row says how far
# down the list it is. There is no reason that stops at Titan's own windows,
# and this is the same thing applied to whatever the user is in: Explorer's
# file list read as files with their type and size, a disabled command heard
# as unusable, and the PART of the window the keyboard has moved into said
# once, when it changes.
#
# Off until it is asked for. It changes what every program on the machine
# sounds like, which is not a decision to make for somebody.
# --------------------------------------------------------------------------- #

#: **Kept for the reader modules and for :func:`region_of`.** The parts of
#: a window a person tells apart at a glance, in NVDA's own role names.
REGIONS = ('MENUBAR', 'TOOLBAR', 'STATUSBAR', 'TABCONTROL', 'TREEVIEW',
           'LIST', 'TABLE', 'DATAGRID', 'DOCUMENT', 'PROPERTYPAGE',
           'GROUPING', 'DIALOG')

#: How far up to look for one.
REGION_DEPTH = 8


def windows_wanted():
    from . import configSpec
    return bool(configSpec.read().get('windowsSemantics', True))


def _ancestors(obj):
    """The chain above this control, WITHOUT walking it ourselves."""
    from . import ancestry
    return ancestry._chain(obj)[::-1][:REGION_DEPTH]


def region_of(obj, module=None):
    """The part of the window this control is in, as a word, or ''.

    What a sighted person gets from the layout: this is the toolbar, that
    is the status bar, the big thing in the middle is the list. Answered
    on demand - for "where am I", and for a module deciding what to call a
    pane - and deliberately NOT the thing that decides what is announced;
    :func:`region_change` is that, and the difference between them is the
    whole of the bug this pair used to have.
    """
    from . import context
    for step in _ancestors(obj):
        role = getattr(step, 'role', None)
        name = str(getattr(role, 'name', '') or '').upper()
        if name in REGIONS:
            if module is not None:
                own_name = str(getattr(step, 'name', '') or '').strip()
                given = module.region_word(step, role=name, name=own_name)
                if given:
                    return given
            said = context.role_name(role)
            own = str(getattr(step, 'name', '') or '').strip()
            return '{}, {}'.format(own, said) if own and name == 'GROUPING' \
                else said
    return ''


def region_change(obj, module=None):
    """The place the keyboard has just entered that NVDA did NOT announce.

    **Almost always nothing, and that is the fix.** This used to say the
    part of the window whenever it thought the user had moved, and it
    thought so on every control, because it remembered against the FOCUSED
    CONTROL's window handle - and in a Win32 dialog every button is its own
    window. Tabbing between two buttons therefore announced "dialog" in
    front of each of them, which is what a user reported: "dialog OK
    button, dialog Cancel button".

    Two things were wrong and the second is the larger one. The key was the
    wrong window's. And NVDA **already does this**: it fires
    ``event_focusEntered`` on every ancestor the focus has newly entered
    and speaks it, which is how anybody hears "dialog" once on arriving in
    one, or a group's name on tabbing into the group. So the old layer was
    a second copy of a feature that was already there, and the only thing
    it could add was the duplicate.

    :mod:`ancestry` computes the same difference NVDA computes, marks each
    newly entered place with whether NVDA has spoken it, and hands back
    only the ones NVDA left silent - a LIST, which NVDA enters in silence
    deliberately, and a pane a reader module has given a name the program
    never gave it. Everything else is NVDA's and is not repeated.
    """
    from . import ancestry
    if not windows_wanted():
        return ''
    steps = ancestry.entered(obj, module)
    return steps[0].word if steps else ''


def forget_regions():
    from . import ancestry
    ancestry.forget()


def windows_parts(obj, module=None):
    """What this control is, anywhere on the machine. ``[]`` for nothing.

    Deliberately only what NVDA does not already say: a place NVDA entered
    in silence, and the columns of a row. Everything else is left to NVDA,
    which knows about tables, landmarks and browse mode and is better at
    all of them than this is.
    """
    return _measured(lambda one: _windows_parts(one, module), obj) or []


def _windows_parts(obj, module=None):
    if obj is None or not windows_wanted():
        return []
    from . import elements
    parts = []
    where = region_change(obj, module)
    if where:
        parts.append((where, 'context'))
    if _is_row(obj):
        cells = columns_of(obj)
        if cells:
            rule = _rule_for(obj, None, module, cells)
            parts.append((cells[0][1], elements.NAME_PITCH))
            kind_at = rule['kind_column']
            if isinstance(kind_at, int) and 0 <= kind_at < len(cells):
                parts.append((cells[kind_at][1], 'kind'))
            for index, (title, cell) in enumerate(cells):
                if index == 0 or index == kind_at:
                    continue
                if title and title.lower() in rule['quiet']:
                    continue
                parts.append(('{}: {}'.format(title, cell) if title else cell,
                              'detail'))
            for extra in elements._position_of(obj):
                parts.append((extra, 'place'))
    # **Whether this REPLACES NVDA's report is not decided here.** It used
    # to be, by a test on whether the control was a list item - and a list
    # item is not the same thing as a reading of one: NVDA's own settings
    # dialog has a category list whose items have no columns, so the
    # reading was the LIST's name alone and it silenced NVDA's report of
    # the item. The caller asks `focus._only_context` instead, which is a
    # question about what was actually read rather than about what kind of
    # control it came from.
    return parts


# --------------------------------------------------------------------------- #
# The budget: a reader that has stopped answering is not a better reader
#
# Everything in this module runs inside `event_gainFocus`, on the thread
# that reads the screen, and everything it asks is a call into another
# process. That is affordable exactly as long as it is FAST, and whether it
# is fast depends on the program the user is in - which is not something
# that can be decided here or measured once.
#
# So it measures itself. The first version of this walked eight parents per
# focus event and froze NVDA ten times in one session (the session before it
# existed: zero). The walk is gone, but the lesson is not the walk: it is
# that a layer on this path must be able to notice it is too expensive and
# stand down, rather than needing somebody to work out from a frozen reader
# which add-on to blame.
# --------------------------------------------------------------------------- #

#: One pass may take this long. A focus event is answered in milliseconds;
#: anything near a tenth of a second is heard as the reader hesitating.
SLOW_ONCE = 0.05

#: How many slow ones before this stands down. Not one: a machine that was
#: paging, or a window that had just opened, is not a reason to lose the
#: feature for the rest of the session.
SLOW_ENOUGH = 5

_timing = {'calls': 0, 'total': 0.0, 'worst': 0.0, 'slow': 0, 'stopped': ''}


def timing():
    """What this layer has really cost, for the status command."""
    kept = dict(_timing)
    kept['average'] = (kept['total'] / kept['calls']) if kept['calls'] else 0.0
    return kept


def stood_down():
    return _timing['stopped']


def resume():
    """Try again - after a settings change, or when the user asks."""
    _timing.update({'slow': 0, 'stopped': ''})


def _measured(function, obj):
    """Run one pass, and stand down for good if it keeps being slow."""
    if _timing['stopped']:
        return None
    began = time.time()
    try:
        return function(obj)
    finally:
        took = time.time() - began
        _timing['calls'] += 1
        _timing['total'] += took
        if took > _timing['worst']:
            _timing['worst'] = took
        if took > SLOW_ONCE:
            _timing['slow'] += 1
            if _timing['slow'] >= SLOW_ENOUGH:
                _timing['stopped'] = (
                    'reading Titan\'s applications took %d ms on this '
                    'machine, which the reader is heard hesitating over, so '
                    'it has stopped' % int(took * 1000))


# --------------------------------------------------------------------------- #
# The whole of it
# --------------------------------------------------------------------------- #
def describe(obj):
    """``([(text, pitch)], application)`` - or ``([], None)``.

    Answers nothing at all for a window that is not a Titan application's,
    which is most of the machine, and it costs one dictionary lookup to
    find that out.
    """
    return _measured(_describe, obj) or ([], None)


def _describe(obj):
    if obj is None or not wanted():
        return [], None
    application = application_of(obj)
    if application is None:
        return [], None
    if application.get('kind') not in ('app', 'game', '', None):
        # **Not everything Titan knows the pid of is an application.** A
        # component, a widget or a TTS engine has no window of its own; a
        # CLIENT is another program entirely - the reader itself is one of
        # them, so its own dialogs are in this map - and Titan's own pid is
        # handled long before here. Answering `application` for any of
        # those would make the caller believe it had read the control and
        # stop, which inside NVDA's own windows means its cursor sounds
        # and its ordinary reporting both quietly stop happening.
        return [], None
    from . import elements
    from . import readerModules
    module = readerModules.for_object(obj, application) \
        if modules_wanted() else None
    parts = []
    where = context_change(obj, application, module)
    if where:
        parts.append((where, 'context'))
    entered = region_change(obj, module)
    if entered:
        parts.append((entered, 'context'))
    if _is_row(obj):
        parts.extend(row_parts(obj, application, module))
    if not parts:
        return [], application
    # Where in the list, said as it is everywhere else in this add-on.
    if _is_row(obj):
        for extra in elements._position_of(obj):
            parts.append((extra, elements.NAME_PITCH))
    return parts, application
