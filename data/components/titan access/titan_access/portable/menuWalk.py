# -*- coding: utf-8 -*-
"""The Titan menu, walked - the SAME menu, not a second one.

The first version of this built a list out of `gestures.load_catalogue()`
- every Titan action there is, grouped by add-on - and that is a
different thing from the Titan menu. The menu has a shape somebody has
thought about: the assistant first, because it answers the question you
have not worked out a command for; then AI OCR, the applications, this
program, the managers, the switches. Rebuilding that as a second list is
how the two quietly stop agreeing.

So this **walks the menu that :mod:`menu` really builds**. It asks for
the real `wx.Menu`, reads its items - their labels, their submenus, which
of them are ticked, which are greyed out - and runs an item through the
builder's own map, which is the same callable the platform menu would
have fired. One definition, two renderings: a `wx.Menu` for somebody who
wants the platform's own, and this for somebody who wants it walked like
everything else here.

**The builder must outlive the walk.** It holds the callables, keyed by
the wx id of each item, and NVDA's frame holds the bindings - so it is
kept while the walk is up and released when it closes, exactly as the
menu itself does.
"""

import threading

from . import i18n

_ = i18n.install(globals())

_LOCK = threading.RLock()

_held = {'menu': None, 'builder': None}
_counted = {'opened': 0, 'levels': 0, 'ran': 0}


def report():
    with _LOCK:
        found = dict(_counted)
    found['holding'] = _held['builder'] is not None
    return found


def forget():
    with _LOCK:
        for key in _counted:
            _counted[key] = 0


def _text(value):
    return str(value or '').strip()


def _release():
    """Let go of the menu and every handler it put on NVDA's frame."""
    with _LOCK:
        builder = _held['builder']
        _held['menu'] = None
        _held['builder'] = None
    if builder is not None:
        try:
            builder.release()
        except Exception:                            # noqa: BLE001
            pass


def open_it(plugin=None):
    """The Titan menu, walked. ``(ok, said)``."""
    from . import menu as menu_module
    from . import palette
    _release()
    try:
        made, builder = menu_module.build(plugin)
    except Exception as error:                       # noqa: BLE001
        return False, str(error)
    if made is None or builder is None:
        # Translators: said when the Titan menu cannot be built.
        return False, _('The menu needs a window to put it on.')
    with _LOCK:
        _held['menu'] = made
        _held['builder'] = builder
        _counted['opened'] += 1
    # Translators: the title of the Titan menu, walked.
    return _level(made, _('Titan'), back=None)


def _level(wx_menu, title, back=None):
    """One menu as a list of its items. ``(ok, said)``."""
    from . import palette
    rows = []
    for item in _items(wx_menu):
        label = _text(item.get('label'))
        if not label:
            continue                                 # a separator
        rows.append({'label': _said_as(item), 'role': item['what'],
                     'icon': 'open-object' if item['submenu'] else '',
                     'run': (lambda one=item, name=label:
                             _chosen(one, name))})
    if not rows:
        # Translators: said when a menu has nothing on it.
        return False, _('That menu is empty')
    with _LOCK:
        _counted['levels'] += 1
    return palette.show(rows, title, back=back or _close)


def _items(wx_menu):
    """The menu's own items, as plain dictionaries.

    Read off the built menu rather than from a table of our own: a menu
    entry added tomorrow is walkable tomorrow, with nothing changed here.
    """
    found = []
    try:
        entries = list(wx_menu.GetMenuItems())
    except Exception:                                # noqa: BLE001
        return found
    for entry in entries:
        try:
            label = entry.GetItemLabelText()
        except Exception:                            # noqa: BLE001
            label = ''
        submenu = None
        try:
            submenu = entry.GetSubMenu()
        except Exception:                            # noqa: BLE001
            submenu = None
        ticked = False
        try:
            ticked = bool(entry.IsCheckable() and entry.IsChecked())
        except Exception:                            # noqa: BLE001
            ticked = False
        enabled = True
        try:
            enabled = bool(entry.IsEnabled())
        except Exception:                            # noqa: BLE001
            enabled = True
        found.append({
            'label': label, 'submenu': submenu, 'ticked': ticked,
            'enabled': enabled, 'checkable': _checkable(entry),
            'id': _id_of(entry),
            # Translators: what a row of the walked Titan menu is.
            'what': _('submenu') if submenu is not None else _('entry'),
        })
    return found


def _checkable(entry):
    try:
        return bool(entry.IsCheckable())
    except Exception:                                # noqa: BLE001
        return False


def _id_of(entry):
    try:
        return int(entry.GetId())
    except Exception:                                # noqa: BLE001
        return 0


def _said_as(item):
    """One row's words: what it is called, and its state where it has one.

    **A switch says whether it is on**, because a menu that only says
    "Announce the kind of dialog" tells somebody nothing about whether it
    is happening - and this is a list rather than a real menu, so the
    platform will not say it for us.
    """
    label = _text(item.get('label'))
    if item.get('checkable'):
        # Translators: a switch on the walked Titan menu that is on.
        # Translators: a switch on the walked Titan menu that is off.
        return '%s: %s' % (label, _('on') if item.get('ticked') else _('off'))
    if not item.get('enabled'):
        # Translators: an entry on the walked menu that cannot be used.
        return '%s (%s)' % (label, _('not available'))
    return label


def _chosen(item, label):
    """Enter on a row: into a submenu, or run the entry. ``(ok, said)``."""
    from . import palette
    if item.get('submenu') is not None:
        return _level(item['submenu'], label,
                      back=lambda: _reopen())
    if not item.get('enabled'):
        # Translators: said when an entry that cannot be used is pressed.
        return False, _('That is not available')
    with _LOCK:
        builder = _held['builder']
        _counted['ran'] += 1
    what = None
    if builder is not None:
        try:
            what = builder.doing.get(item.get('id'))
        except Exception:                            # noqa: BLE001
            what = None
    # The walk closes BEFORE the entry runs: most of them put a window up,
    # and a list still holding the arrows underneath one would swallow the
    # first thing pressed in it.
    palette.stop()
    _release()
    if what is None:
        return False, ''
    try:
        what()
    except Exception as error:                       # noqa: BLE001
        return False, str(error)
    return True, ''


def _reopen():
    """Back to the top of the menu, from a submenu."""
    with _LOCK:
        made = _held['menu']
    if made is None:
        return open_it()
    return _level(made, _('Titan'))


def _close():
    """Escape at the top: the menu goes, and its handlers with it."""
    from . import palette
    _release()
    return palette.stop()
