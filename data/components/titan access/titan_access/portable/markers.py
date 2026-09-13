# -*- coding: utf-8 -*-
"""Place markers: mark a control, come back to it with a key.

JAWS has had them for twenty years and people who use them do not give them
up. They answer the thing a reader is worst at: a program you use every day
has three places in it you actually go - the message list, the search box,
the button at the bottom of a long form - and getting to each of them is a
dozen Tabs every single time, because a screen reader can only offer you the
control you are ON and the one after it.

A marker is a name for a place, and the whole feature is that going there is
one keypress.

* **They belong to a PROGRAM.** A marker made in the mail client is offered
  in the mail client, which is what makes the list short enough to be worth
  opening and what stops the first nine markers being nine markers from nine
  different programs.
* **They are NUMBERED, and the number is the point.** JAWS' own numbered
  place markers are why the feature is used: the third thing you marked is
  always the third thing, so it becomes a key you press without reading a
  list. The list is there for the times you have forgotten.
* **Going to one moves the keyboard where it can, and the review cursor
  where it cannot.** A great many of the places worth marking - a status
  line, a heading, a pane's title - cannot take the keyboard at all, and a
  marker that refused those would be a marker for buttons only.

The anchoring is :mod:`anchors`, shared with the monitors: what will still
be true about this control the next time the program is opened.
"""

import json
import os
import threading

from . import anchors
from . import i18n

_ = i18n.install(globals())

FILENAME = 'titanMarkers.json'

#: How many of a program's markers get a number worth remembering. Past
#: this they are still there and still in the list; they are just not
#: something anybody presses a key for.
NUMBERED = 9

_LOCK = threading.RLock()
_markers = None


def path():
    try:
        import globalVars
        return os.path.join(globalVars.appArgs.configPath, FILENAME)
    except Exception:                                # noqa: BLE001
        return ''


def _load():
    global _markers
    with _LOCK:
        if _markers is not None:
            return _markers
        _markers = []
        where = path()
        if where and os.path.isfile(where):
            try:
                with open(where, encoding='utf-8') as handle:
                    data = json.load(handle)
                if isinstance(data, list):
                    _markers = [row for row in data if isinstance(row, dict)
                                and row.get('anchor')]
            except Exception:                        # noqa: BLE001
                _markers = []
        return _markers


def forget():
    global _markers
    with _LOCK:
        _markers = None


def save():
    where = path()
    if not where:
        return False
    with _LOCK:
        data = list(_load())
    try:
        with open(where, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1)
        return True
    except Exception:                                # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Making one
# --------------------------------------------------------------------------- #
def _focused():
    try:
        import api
        return api.getFocusObject()
    except Exception:                                # noqa: BLE001
        return None


def mark(obj=None, name=''):
    """Mark the control the user is on. ``(ok, sentence)``."""
    if obj is None:
        obj = _focused()
    if obj is None:
        # Translators: said when there is nothing to mark.
        return False, _('There is nothing here to mark')
    anchor = anchors.anchor_for(obj)
    if anchor is None:
        # Translators: said when a control cannot be marked.
        return False, _('You cannot mark this control')
    program = anchor.get('program') or ''
    said = str(name or anchors.describe(obj))
    with _LOCK:
        markers = _load()
        for standing in markers:
            if standing.get('anchor') == anchor:
                # Translators: said when the same control is marked twice.
                return False, _('That is already marked')
        markers.append({'name': said, 'program': program, 'anchor': anchor})
        number = len(for_program(program))
    save()
    if number <= NUMBERED:
        # Translators: said when a place marker is made. {what} is its
        # name, {n} the number it can be reached by.
        return True, _('Marked {what}, number {n}').format(what=said,
                                                           n=number)
    # Translators: said when a place marker is made. {what} is its name.
    return True, _('Marked {what}').format(what=said)


def for_program(program=None):
    """This program's markers, in the order they were made.

    The order IS the numbering, so it must not be sorted, filtered or
    otherwise rearranged: the third thing you marked has to stay the third
    thing or the numbers are worth nothing.
    """
    if program is None:
        program = anchors.program_of()
    return [row for row in _load() if (row.get('program') or '') == program]


def all_markers():
    return list(_load())


def rename(marker, name):
    said = str(name or '').strip()
    if not said:
        return False
    with _LOCK:
        for row in _load():
            if row is marker or row == marker:
                row['name'] = said
                break
        else:
            return False
    return save()


def remove(marker):
    with _LOCK:
        markers = _load()
        for at, row in enumerate(markers):
            if row is marker or row == marker:
                markers.pop(at)
                break
        else:
            return False
    return save()


def clear(program=None):
    """Forget this program's markers, or every one of them."""
    with _LOCK:
        markers = _load()
        if program is None:
            markers[:] = []
        else:
            markers[:] = [row for row in markers
                          if (row.get('program') or '') != program]
    return save()


# --------------------------------------------------------------------------- #
# Going to one
# --------------------------------------------------------------------------- #
def go(marker):
    """Go to a marker. ``(ok, sentence)``.

    The keyboard where the control will take it, the review cursor where it
    will not - because most of the places worth marking cannot be focused,
    and a marker that refused those would be a marker for buttons only.
    """
    if not marker:
        # Translators: said when there is no such place marker.
        return False, _('There is no such marker')
    obj = anchors.find(marker.get('anchor'))
    if obj is None:
        # Translators: said when a marked control is not on the screen.
        # {what} is the marker's name.
        return False, _('{what} is not here now').format(
            what=marker.get('name') or '')
    said = marker.get('name') or anchors.describe(obj)
    try:
        obj.setFocus()
        # Translators: said on arriving at a place marker. {what} is its
        # name.
        return True, _('{what}').format(what=said)
    except Exception:                                # noqa: BLE001
        pass
    try:
        import api
        api.setNavigatorObject(obj)
        # Translators: said when a marked control cannot take the keyboard,
        # so the review cursor goes there instead. {what} is its name.
        return True, _('{what}, review cursor').format(what=said)
    except Exception:                                # noqa: BLE001
        # Translators: said when a place marker cannot be reached.
        return False, _('{what} could not be reached').format(what=said)


def go_to_number(number):
    """Go to this program's Nth marker. ``(ok, sentence)``."""
    here = for_program()
    index = int(number) - 1
    if not 0 <= index < len(here):
        # Translators: said when a numbered place marker does not exist.
        # {n} is the number.
        return False, _('There is no marker {n} here').format(n=number)
    return go(here[index])
