# -*- coding: utf-8 -*-
"""Titan's own window, walked instead of shown.

:mod:`titanWindow` puts Titan up as a `wx.Dialog` with five tabbed pages,
and that window is worth keeping: it is a real dialog with real controls,
which the platform announces itself, and somebody who wants a form gets
one.

**But it is a dialog**, and a dialog is the one interaction on this
desktop that is not like the others. It takes the foreground away from
the program the user was in, it has to be closed before anything else can
be done, and every answer inside it is said once - so a long one is cut
off by the next thing that speaks, which is the fault this add-on has now
fixed in three separate places.

So this is the same Titan, walked: the pages are a list, what is on a
page is a list, and Enter does the one obvious thing to a row - start
that application, open that widget, press that setting. Escape steps back
one level and then closes, the way every other list here behaves.

**It asks Titan exactly what the window asks it** (`titan.applications`,
`titan.widgets`, `titan.settings` ...), so the two can never offer
different things: there is one set of calls and two ways of showing what
comes back.

Nothing here waits on the reader's own thread. Every list is a round trip
to another process, so it is fetched on a worker and the walker is filled
when the answer arrives - a reader that stopped while Titan thought would
be the thing this whole add-on is careful not to be.
"""

import threading

from . import i18n
from . import titan

_ = i18n.install(globals())

_LOCK = threading.RLock()

_counted = {'opened': 0, 'pages': 0, 'ran': 0, 'failed': 0, 'why': ''}


def report():
    with _LOCK:
        return dict(_counted)


def forget():
    with _LOCK:
        for key in _counted:
            _counted[key] = 0 if key != 'why' else ''


def _text(value):
    return str(value or '').strip()


def _label_of(row, *names):
    """The first of those fields the row really has."""
    if not isinstance(row, dict):
        return _text(row)
    for name in names:
        found = _text(row.get(name))
        if found:
            return found
    return ''


def _say(text):
    from . import dialogs
    dialogs.report(str(text or ''))


def _failed(why):
    with _LOCK:
        _counted['failed'] += 1
        _counted['why'] = _text(why)
    _say(why)


# --------------------------------------------------------------------------- #
# The pages
# --------------------------------------------------------------------------- #
def open_it():
    """Titan as a list of its pages. ``(ok, said)``."""
    from . import palette
    if not titan.LINK.connected():
        # Translators: said when Titan is not running.
        _failed(_('Titan is not running.'))
        return False, ''
    rows = []
    for key, name in PAGES:
        rows.append({
            'label': name(),
            # Translators: what a row of Titan's own window is.
            'role': _('page'),
            'icon': 'open-object',
            'run': (lambda which=key: _open_page(which)),
        })
    with _LOCK:
        _counted['opened'] += 1
    # Translators: the title of Titan's own window.
    return palette.show(rows, _('Titan'))


def _open_page(which):
    """Fill one page, on a worker, and walk it when it arrives."""
    with _LOCK:
        _counted['pages'] += 1
    page = _PAGES.get(which)
    if page is None:
        return False, ''
    # Said now, because the answer is a round trip and silence in
    # between reads as a key that did nothing.
    _say(page['name']())

    def work():
        try:
            ok, rows = page['fetch']()
        except Exception as error:                   # noqa: BLE001
            ok, rows = False, '%s: %s' % (type(error).__name__, error)
        _on_the_readers_thread(lambda: _page_arrived(page, ok, rows))
    threading.Thread(target=work, name='TitanWalk', daemon=True).start()
    return True, ''


def _on_the_readers_thread(work):
    """Everything that speaks or moves the cursor happens there."""
    from . import compat
    if compat.queueHandler is None:
        work()
        return
    compat.queueHandler.queueFunction(compat.queueHandler.eventQueue, work)


def _page_arrived(page, ok, rows):
    from . import palette
    if not ok:
        _failed(rows)
        return
    made = []
    for row in (rows or []):
        label = page['label'](row)
        if not label:
            continue
        made.append({'label': label, 'role': page['what'](),
                     'run': (lambda one=row: page['press'](one))})
    # A page may end with rows of its own - Save and Put them back, which
    # are about the settings rather than about any one of them. They come
    # last so that nothing Titan answered moves when one is added.
    extra = page.get('extra')
    if made and callable(extra):
        made.extend(extra() or [])
    if not made:
        # Translators: said when a page of Titan's window has nothing on it.
        _say(_('Nothing here'))
        return
    palette.show(made, page['name'](), back=open_it)


def _ran(answer):
    """What a row's own verb answered. ``(ok, said)`` for the walker."""
    from . import palette
    with _LOCK:
        _counted['ran'] += 1
    palette.stop()
    ok, said = answer if isinstance(answer, tuple) else (True, str(answer))
    if said:
        _say(said)
    return bool(ok), ''


def _on_a_thread(work):
    """A verb that reaches Titan, off the reader's thread."""
    def run():
        try:
            answer = work()
        except Exception as error:                   # noqa: BLE001
            answer = (False, '%s: %s' % (type(error).__name__, error))
        _on_the_readers_thread(lambda: _ran(answer))
    threading.Thread(target=run, name='TitanWalkDo', daemon=True).start()
    return True, ''


# --------------------------------------------------------------------------- #
# What each page is
# --------------------------------------------------------------------------- #
def _application_row(row):
    return _label_of(row, 'name', 'id')


def _widget_row(row):
    name = _label_of(row, 'name', 'id')
    kind = _label_of(row, 'type')
    return '%s (%s)' % (name, kind) if kind else name


def _notification_row(row):
    return _label_of(row, 'text', 'title', 'message')


def _statusbar_row(row):
    return _label_of(row, 'text', 'label', 'name')


def _addons_with_actions():
    """Every add-on Titan has, with what each can be told to do.

    Asked of the catalogue the reader already keeps rather than of Titan
    again: it is the same list the Titan menu is built from, so the
    window and the menu cannot offer different things.
    """
    try:
        from . import gestures
        rows = gestures.load_catalogue()
    except Exception as error:                       # noqa: BLE001
        return False, '%s: %s' % (type(error).__name__, error)
    if not rows:
        return False, _('Titan has not said what it offers yet.')
    groups = {}
    for row in rows:
        groups.setdefault(row['addon'], []).append(row)
    made = []
    for addon_id, actions in groups.items():
        made.append({'id': addon_id,
                     'label': actions[0].get('label') or addon_id,
                     'actions': sorted(actions,
                                       key=lambda one: one['action'])})
    made.sort(key=lambda one: str(one['label']).lower())
    return True, made


def _open_actions(row):
    """One add-on's actions, walked. Enter runs the one chosen."""
    from . import palette
    made = []
    for one in (row.get('actions') or []):
        made.append({'label': _action_label(one),
                     'role': _('action'),
                     'run': (lambda action=one: _run_action(action))})
    if not made:
        return False, _('Nothing here')
    return palette.show(made, _label_of(row, 'label', 'id'),
                        back=lambda: _open_page('actions'))


def _action_label(row):
    """What one action is called - the sentence its author wrote."""
    summary = _text(row.get('summary'))
    if not summary:
        return _text(row.get('action'))
    first = summary.split('. ')[0].rstrip('.')
    return first if len(first) <= 70 else _text(row.get('action'))


def _run_action(row):
    from . import gestures
    from . import palette
    palette.stop()
    return _on_a_thread(lambda: (True, gestures.run(row)))


def _open_menu_group(row):
    """One menu of Titan's own menu bar, walked."""
    from . import palette
    made = []
    for entry in (row.get('entries') or []):
        label = _label_of(entry, 'label', 'name', 'id')
        if not label:
            continue
        made.append({'label': label, 'role': _('entry'),
                     'run': (lambda one=entry: _on_a_thread(
                         lambda: titan.run_menu(
                             _label_of(one, 'id', 'label'))))})
    if not made:
        return False, _('Nothing here')
    return palette.show(made, _label_of(row, 'label', 'id'),
                        back=lambda: _open_page('menu'))


def _macro_row(row):
    """A macro, as Titan really answers it.

    **`hotkey`, not `shortcut`** - asked of the running Titan over the
    bus rather than guessed: `macros.list` answers
    `{"macros": [{"name", "hotkey", "type"}]}`. A key nothing writes is a
    working-looking empty string, and this add-on has shipped that bug
    before.
    """
    name = _label_of(row, 'name', 'label', 'id')
    key = _label_of(row, 'hotkey', 'shortcut', 'keys')
    return '%s (%s)' % (name, key) if key else name


#: Where a row keeps the things INSIDE it. Titan answers a different
#: field per kind and this reader cannot be rebuilt every time one is
#: added, so the row is asked for any of them - and a row that carries
#: none is simply a row.
INSIDE = ('items', 'entries', 'rows', 'elements', 'children', 'contents',
          # A buffer category answers `{"id", "name", "live", "buffers"}` -
          # read off the running Titan, not guessed.
          'buffers')


def _things_inside(row):
    """What is inside that row, whatever Titan called it. ``[]`` for none."""
    if not isinstance(row, dict):
        return []
    for name in INSIDE:
        found = row.get(name)
        if isinstance(found, (list, tuple)) and found:
            return list(found)
    return []


def _open_view(row):
    """A view's own rows, walked - or the view said, when it has none."""
    from . import palette
    inside = _things_inside(row)
    label = _label_of(row, 'short_name', 'label', 'name', 'id')
    if not inside:
        return True, label
    made = []
    for one in inside:
        said = _label_of(one, 'label', 'name', 'text', 'id') \
            if isinstance(one, dict) else _text(one)
        if said:
            made.append({'label': said, 'role': _('row'),
                         'run': (lambda text=said: (True, text))})
    if not made:
        return True, label
    return palette.show(made, label, back=lambda: _open_page('views'))


def _walk_a_widget(row):
    """Enter on a widget opens it - the widget MODE, not a press.

    What somebody arriving at a widget wants is the widget, walked with
    the arrow keys the way everything else on this desktop is walked.
    That is the same answer the Titan window's own list now gives.
    """
    from . import palette
    from . import widgetReview
    palette.stop()
    which = _label_of(row, 'id', 'name')
    ok, said = widgetReview.start(which)
    if said:
        _say(said)
    return bool(ok), ''


# --------------------------------------------------------------------------- #
# Titan's settings, which are a window inside a window
# --------------------------------------------------------------------------- #
#: **A category is not a setting.** `settings.screen` answers
#: `{'categories': [{'name': ..., 'items': [...]}]}` - the same shape
#: Titan's own settings window has, a list of categories down one side and
#: the controls of the chosen one beside it (`src/ui/settingsgui.py`) - and
#: this page read a category AS a control. It was announced as "General,
#: setting", and Enter sent `_label_of(row, 'id', 'label')` of a dict that
#: carries neither, so Titan was asked to press a control called nothing
#: and answered **"Say which control to press."** for every category there
#: is. The whole page was one level short.
#:
#: So a category is a category, it is walked INTO, and what is inside it
#: are the controls - each of which Enter does the one obvious thing to.
_settings_open = {'category': '', 'rows': [], 'items': [], 'at': 0}

#: Whether a change is waiting to be kept. Titan's own answer to setting
#: one is "Nothing is written until you save", so a walker with no save was
#: a window in which every answer the user gave was thrown away when they
#: left it.
_unsaved = {'on': False}


def _switched_on(name, unless=True):
    """One of the add-on's own switches. Works with no NVDA under it."""
    try:
        from . import configSpec
        return bool(configSpec.read().get(name, unless))
    except Exception:                                # noqa: BLE001
        return unless


def _what_a_setting_is(kind):
    """What a control IS, in the one word a row has room for."""
    return {
        # Translators: what a settings control is - a check box.
        'bool': _('tick box'),
        # Translators: what a settings control is - one of several answers.
        'choice': _('choice'),
        # Translators: what a settings control is - a list to choose from.
        'list': _('list'),
        # Translators: what a settings control is - a number.
        'number': _('number'),
        # Translators: what a settings control is - a line of text.
        'text': _('text'),
        # Translators: what a settings control is - a password or a key.
        'secret': _('key'),
        # Translators: what a settings control is - a button to press.
        'command': _('button'),
        # Translators: what a settings control is - something to read.
        'info': _('information'),
        # Translators: what a settings control is - several answers at once.
        'multi': _('tick list'),
        # Translators: what a settings control is, when Titan has not said.
    }.get(str(kind or ''), _('setting'))


def _setting_name(item):
    """What one control is called, with no value on the end of it."""
    return _label_of(item, 'label', 'id')


def _setting_label(item):
    """One control as a row: what it is called, and what it holds.

    Reused from the window rather than written again - the two faces of
    Titan must not describe one setting differently, and "on" and "off"
    are translated in exactly one place.
    """
    if not _switched_on('titanValues'):
        return _setting_name(item)
    from .titanWindow import _setting_line
    return _setting_line(item)


def _setting_icon(item):
    """The auditory icon a row plays - what it is, before a word of it."""
    kind = str(item.get('kind') or '')
    if kind == 'bool':
        from .titanWindow import _truthy
        return 'on' if _truthy(item.get('value')) else 'off'
    if kind == 'command':
        return 'button'
    if kind == 'info':
        return 'section'
    return ''


def _how_many(row):
    """`Sound (9)` - how much is behind a row, where somebody wants it."""
    name = _label_of(row, 'name', 'label', 'id')
    if not _switched_on('titanCounts'):
        return name
    count = len(row.get('items') or [])
    return '%s (%d)' % (name, count) if count else name


def _mark_unsaved():
    """Remember that something is waiting for the Save row."""
    if _switched_on('titanAutoSave', False):
        return False
    with _LOCK:
        first = not _unsaved['on']
        _unsaved['on'] = True
    return first


def _remember_where():
    """Which row the cursor is on, so that coming back lands on it."""
    from . import palette
    try:
        at = int(palette.report().get('at') or 0)
    except Exception:                                # noqa: BLE001
        at = 0
    with _LOCK:
        _settings_open['at'] = at


def _open_settings_category(row):
    """One category of Titan's settings, walked - the controls in it."""
    from . import palette
    name = _label_of(row, 'name', 'label', 'id')
    made = []
    kept = []
    for item in (row.get('items') or []):
        if not isinstance(item, dict):
            continue
        built = _control_row(item, name)
        if built is None:
            continue
        made.append(built)
        kept.append(item)
    if not made:
        # Translators: said when a settings category has nothing in it.
        return False, _('Nothing here')
    with _LOCK:
        _settings_open.update({'category': name, 'rows': made,
                               'items': kept, 'at': 0})
    return palette.show(made, name, back=lambda: _open_page('settings'))


def _back_to_category(category):
    """The category, put back with the cursor where it was left."""
    from . import dialogs
    from . import palette
    with _LOCK:
        known = dict(_settings_open)
    if known.get('category') != category or not known.get('rows'):
        return _open_page('settings')
    answer = palette.show(known['rows'], category,
                          back=lambda: _open_page('settings'),
                          at=known.get('at', 0))
    # A modal box may be what took the arrow keys away, and nothing else
    # would tell the walker that a list is up again.
    dialogs._keep_keys_right()
    return answer


def _control_row(item, category):
    """One control as a row of the walker, or None when it is not one."""
    label = _setting_label(item)
    if not str(label or '').strip():
        return None
    row = {'label': label, 'role': _what_a_setting_is(item.get('kind')),
           'icon': _setting_icon(item)}
    row['run'] = (lambda one=item, where=row:
                  _change_setting(where, one, category))
    return row


def _change_setting(row, item, category):
    """Enter on a control - the one obvious thing to do to that kind."""
    kind = str(item.get('kind') or '')
    control = _label_of(item, 'id')
    label = _setting_name(item)
    if kind == 'info':
        # Not a control: reading it again is what Enter means on a line of
        # text everywhere else here.
        return True, _text(item.get('value')) or label
    if not control:
        # Translators: said about a settings control Titan gave no id for.
        return False, _('Titan did not say what this control is called.')
    if kind == 'command':
        return _without_closing(
            lambda: titan.press_setting(control),
            lambda answer: _setting_changed(row, item, category, answer))
    if kind == 'bool':
        from .titanWindow import _truthy
        wanted = not _truthy(item.get('value'))
        return _without_closing(
            lambda: _set_it(control, wanted),
            lambda answer: _setting_changed(row, item, category, answer,
                                            picked=wanted))
    if kind in ('choice', 'list'):
        return _choose_an_answer(row, item, category)
    if kind == 'multi':
        return _tick_some_of_them(row, item, category)
    if kind in ('text', 'number', 'secret'):
        return _ask_for_a_value(row, item, category)
    # **A kind this add-on has not been taught is not silently dropped.**
    # Saying so is an answer; a row that did nothing would not be.
    # Translators: said about a setting this reader cannot change itself.
    return False, _('{what} is set in Titan\'s own settings window').format(
        what=label)


def _set_it(control, value):
    """Set one setting - and keep it, where the user asked for that.

    Saving is Titan's own `OnSave` with everything that hangs off it - the
    SAPI registration, the system monitor, the shell, the menu bar - so it
    is a real cost, and that is why it is a switch rather than a decision
    made for somebody. With it off the change waits for the Save row,
    which is what Titan's own "Nothing is written until you save" means.
    """
    ok, said = titan.set_setting(control, value)
    if ok and _switched_on('titanAutoSave', False):
        kept, why = titan.save_settings()
        if not kept:
            return False, why
    return ok, said


def _setting_changed(row, item, category, answer, picked=None, back=False):
    """What a change answered, said once - and the row made true again."""
    from . import icons
    ok, said = answer if isinstance(answer, tuple) else (True, str(answer))
    with _LOCK:
        _counted['ran'] += 1
    if ok and picked is not None:
        # Known before Titan is asked again, so the row is already right
        # when it is re-read; the re-read below only ever corrects it.
        item['value'] = picked
        row['label'] = _setting_label(item)
        row['icon'] = _setting_icon(item)
    if not ok:
        icons.play('warn-user')
        # A refusal is Titan's own sentence, in the user's own language,
        # and it names the one thing that changes the answer.
        # Translators: said when Titan would not change a setting.
        _say(said or _('Titan would not change that.'))
        if back:
            _back_to_category(category)
        return False, ''
    first = _mark_unsaved()
    if back:
        # The row is re-read on the way back in, holding the new value -
        # so it IS the confirmation, and a sentence here as well would be
        # an announcement wiped by the one after it.
        _back_to_category(category)
    else:
        # Translators: said when a settings control was pressed.
        line = row['label'] if picked is not None else (said or _('Done'))
        if first:
            # Said once, and JOINED to the line rather than said after
            # it: two announcements about one keystroke is how one of
            # them goes missing.
            # Translators: said the first time a setting is changed.
            line = '%s. %s' % (line, _('Not saved yet - Save is at the end '
                                       'of the categories.'))
        _say(line)
    _read_the_category_again(category)
    return True, ''


def _read_the_category_again(category):
    """Ask Titan what the category holds NOW, and say nothing about it.

    One setting can move another - a switch that enables half a page - so
    the rows have to follow. **Silently**: the announcement has already
    happened, and a row re-read on top of it would erase it.
    """
    def work():
        try:
            ok, rows = titan.settings(category=category)
        except Exception:                            # noqa: BLE001
            return
        if ok:
            _on_the_readers_thread(lambda: _relabel(category, rows))
    threading.Thread(target=work, name='TitanWalkRead', daemon=True).start()


def _relabel(category, rows):
    """Put what Titan now holds into the rows already on the screen."""
    with _LOCK:
        known = dict(_settings_open)
    if known.get('category') != category:
        return
    fresh = {}
    for one in (rows or []):
        for item in (one.get('items') or []):
            if isinstance(item, dict) and item.get('id'):
                fresh[str(item['id'])] = item
    for row, item in zip(known.get('rows') or [], known.get('items') or []):
        now = fresh.get(str(item.get('id') or ''))
        if now is None:
            continue
        # The same dict the row's own verb closed over, so the next press
        # acts on what the setting really holds.
        item.update(now)
        row['label'] = _setting_label(item)
        row['icon'] = _setting_icon(item)


def _choose_an_answer(row, item, category):
    """A choice, walked - its answers are a list like everything else."""
    from . import palette
    options = [str(one) for one in (item.get('options') or [])]
    if not options:
        # Translators: said when a setting offers nothing to choose from.
        return False, _('There is nothing to choose here')
    _remember_where()
    now = _text(item.get('value'))
    made = []
    for option in options:
        made.append({
            'label': option,
            # Translators: marks the answer a setting is set to now.
            'role': _('now') if option == now else '',
            'icon': 'on' if option == now else '',
            'run': (lambda pick=option: _without_closing(
                lambda: _set_it(_label_of(item, 'id'), pick),
                lambda answer: _setting_changed(row, item, category, answer,
                                                picked=pick, back=True))),
        })
    return palette.show(made, _setting_name(item),
                        back=lambda: _back_to_category(category))


def _mark_tick(row, ticked):
    """What a row of a tick list says about itself."""
    # Translators: a row of a tick list that is ticked.
    # Translators: a row of a tick list that is not ticked.
    row['role'] = _('ticked') if ticked else _('not ticked')
    row['icon'] = 'on' if ticked else 'off'


def _tick_some_of_them(row, item, category):
    """A tick list - several answers at once, each ticked where it is."""
    from . import palette
    options = [str(one) for one in (item.get('options') or [])]
    if not options:
        return False, _('There is nothing to choose here')
    _remember_where()
    ticked = {str(one) for one in (item.get('value') or [])}
    made = []
    for option in options:
        one = {'label': option}
        _mark_tick(one, option in ticked)
        one['run'] = (lambda pick=option, where=one:
                      _tick_it(row, item, category, options, pick, where))
        made.append(one)
    return palette.show(made, _setting_name(item),
                        back=lambda: _back_to_category(category))


def _tick_it(row, item, category, options, option, where):
    """Tick or untick one row, and leave the cursor exactly where it is.

    The level is NOT put up again: re-showing it would say the title and
    then the row, which is two announcements for one keystroke. The row
    the user is on is the one that changed, so saying that row again is
    the whole of what needs to happen.
    """
    import json
    from . import icons
    from . import palette
    ticked = {str(one) for one in (item.get('value') or [])}
    if option in ticked:
        ticked.discard(option)
    else:
        ticked.add(option)
    # In the order the control has them, which is the order the user
    # hears - a list re-ordered by when each row was ticked would read
    # differently every time.
    wanted = [one for one in options if one in ticked]

    def done(answer):
        ok, said = answer if isinstance(answer, tuple) else (True, str(answer))
        if not ok:
            icons.play('warn-user')
            _say(said or _('Titan would not change that.'))
            return
        item['value'] = wanted
        row['label'] = _setting_label(item)
        _mark_tick(where, option in set(wanted))
        _mark_unsaved()
        if palette.here() is where:
            palette.say_here()
        else:
            _say('%s, %s' % (where['label'], where['role']))
        _read_the_category_again(category)
    # **A tick list crosses as JSON TEXT, not as a list.** Titan's own
    # `_set_value` stringifies whatever arrives before it parses it, so a
    # real JSON array comes back through `str()` in Python's own spelling
    # - single quotes - which is not JSON and does not parse.
    return _without_closing(
        lambda: _set_it(_label_of(item, 'id'),
                        json.dumps(wanted, ensure_ascii=False)),
        done)


def _ask_for_a_value(row, item, category):
    """A field - asked for in a real box, with the list put back after.

    The palette borrows the arrow keys while it is walking, so a text box
    opened over it would have its own arrows taken away. The walk is
    closed first and put back afterwards - on an answer AND on a cancel,
    or somebody who changed their mind is left nowhere.
    """
    from . import dialogs
    from . import palette
    kind = str(item.get('kind') or '')
    control = _label_of(item, 'id')
    if dialogs._gui() is None or dialogs._wx() is None:
        # Nowhere to ask. Closing the walk for a box that will never
        # appear would leave somebody with neither the box nor the list.
        return False, _('{what} is set in Titan\'s own settings '
                        'window').format(what=_setting_name(item))
    _remember_where()
    palette.stop()
    # A key is never shown back to anybody: it is written, not read.
    now = '' if kind == 'secret' else _text(item.get('value'))

    def answered(text):
        _without_closing(
            lambda: _set_it(control, text),
            lambda answer: _setting_changed(row, item, category, answer,
                                            picked=text, back=True))
    dialogs.ask_text(_setting_name(item),
                     # Translators: the title of the box that asks for the
                     # value of one of Titan's settings.
                     _("Titan's settings"),
                     on_answer=answered, default=now,
                     on_cancel=lambda: _back_to_category(category))
    return True, ''


def _without_closing(work, then):
    """A verb that changes something and LEAVES the list where it is.

    :func:`_on_a_thread` is right for "start that application" and wrong
    here: it stops the walker, and somebody setting one thing in a
    category is nearly always setting the next one too.
    """
    def run():
        try:
            answer = work()
        except Exception as error:                   # noqa: BLE001
            answer = (False, '%s: %s' % (type(error).__name__, error))
        _on_the_readers_thread(lambda: then(answer))
    threading.Thread(target=run, name='TitanWalkSet', daemon=True).start()
    return True, ''


def _keeping_the_settings():
    """Save and Put back, at the end of the categories.

    Rows rather than a key to learn, and HERE rather than in every
    category: they are about the settings, not about one page of them.
    """
    with _LOCK:
        waiting = bool(_unsaved['on'])
    # Translators: the row that keeps the settings that were changed.
    save = _('Save')
    if waiting:
        # Translators: marks the Save row while a change is waiting.
        save = '%s (%s)' % (save, _('not saved yet'))
    return [
        # Translators: what the Save and Put back rows are.
        {'label': save, 'role': _('button'), 'icon': 'save-object',
         'run': lambda: _on_a_thread(_keep_them)},
        # Translators: the row that undoes the changes that were made.
        {'label': _('Put them back'), 'role': _('button'),
         'icon': 'delete-object',
         'run': lambda: _on_a_thread(_put_them_back)},
    ]


def _keep_them():
    answer = titan.save_settings()
    if answer[0]:
        with _LOCK:
            _unsaved['on'] = False
    return answer


def _put_them_back():
    answer = titan.cancel_settings()
    if answer[0]:
        with _LOCK:
            _unsaved['on'] = False
    return answer


_PAGES = {
    'applications': {
        'name': lambda: _('Applications'),
        'what': lambda: _('application'),
        'fetch': lambda: titan.applications(),
        'label': _application_row,
        'press': lambda row: _on_a_thread(
            lambda: titan.open_application(_label_of(row, 'name', 'id'))),
    },
    'games': {
        'name': lambda: _('Games'),
        'what': lambda: _('game'),
        'fetch': lambda: titan.games(),
        'label': _application_row,
        'press': lambda row: _on_a_thread(
            lambda: titan.open_game(_label_of(row, 'name', 'id'))),
    },
    'widgets': {
        'name': lambda: _('Widgets'),
        'what': lambda: _('widget'),
        'fetch': lambda: titan.widgets(),
        'label': _widget_row,
        'press': _walk_a_widget,
    },
    'settings': {
        'name': lambda: _("Titan's settings"),
        # **A category, because that is what Titan answers.** It used to
        # say 'setting' about a row that is a whole page of them.
        'what': lambda: _('category'),
        'fetch': lambda: titan.settings(),
        'label': _how_many,
        'press': _open_settings_category,
        # Saving is what makes the page worth having: Titan writes
        # nothing until it is told to.
        'extra': _keeping_the_settings,
    },
    'arrived': {
        'name': lambda: _('What arrived'),
        'what': lambda: _('notification'),
        'fetch': lambda: titan.notifications(),
        'label': _notification_row,
        # A notification is news, not a control: pressing one says it
        # again rather than doing something nobody asked for.
        'press': lambda row: (True, _notification_row(row)),
    },
    'actions': {
        'name': lambda: _('Actions'),
        'what': lambda: _('add-on'),
        'fetch': _addons_with_actions,
        'label': lambda row: '%s (%d)' % (row.get('label') or row.get('id'),
                                          len(row.get('actions') or [])),
        # An add-on opens onto ITS actions: the list of everything Titan
        # can be told to do is hundreds of rows long, and a list nobody
        # can find anything in is a list nobody uses.
        'press': lambda row: _open_actions(row),
    },
    'views': {
        'name': lambda: _('Views'),
        'what': lambda: _('view'),
        'fetch': lambda: titan.views(),
        # `views.list` answers `{"id", "label", "short_name"}` and the
        # LABEL is the window's heading - "Lista aplikacji:", colon and
        # all. The short name is what a person calls it.
        'label': lambda row: _label_of(row, 'short_name', 'label', 'id'),
        # **A view is READ, because Titan serves no verb for one.**
        # `views.list` is the whole of what it offers, so a view that
        # carries its own rows is walked into and one that does not says
        # itself. Inventing `views.open` would be an entry that answers
        # "no such call", which is worse than being honest about what a
        # list is.
        'press': lambda row: _open_view(row),
    },
    'macros': {
        'name': lambda: _('Macros'),
        'what': lambda: _('macro'),
        'fetch': lambda: titan.macros(),
        'label': _macro_row,
        'press': lambda row: _on_a_thread(
            lambda: titan.run_macro(_label_of(row, 'name', 'id'))),
    },
    'menu': {
        'name': lambda: _("Titan's menu"),
        'what': lambda: _('menu'),
        'fetch': lambda: titan.menu_groups(),
        'label': lambda row: _label_of(row, 'label', 'name', 'id'),
        'press': lambda row: _open_menu_group(row),
    },
    'buffers': {
        'name': lambda: _('Buffers'),
        'what': lambda: _('category'),
        'fetch': lambda: titan.buffers(),
        'label': lambda row: _label_of(row, 'label', 'name', 'id'),
        'press': lambda row: _open_view(row),
    },
    'cling': {
        'name': lambda: _('Klango applications'),
        'what': lambda: _('application'),
        'fetch': lambda: titan.cling_applications(),
        'label': _application_row,
        'press': lambda row: _on_a_thread(
            lambda: titan.open_cling(_label_of(row, 'name', 'id'))),
    },
    'im': {
        'name': lambda: _('Titan IM'),
        'what': lambda: _('module'),
        'fetch': lambda: titan.im_modules(),
        'label': lambda row: _label_of(row, 'label', 'name', 'id'),
        'press': lambda row: _on_a_thread(
            lambda: titan.open_im(_label_of(row, 'id', 'name'))),
    },
    'statusbar': {
        'name': lambda: _('Status bar'),
        'what': lambda: _('status'),
        'fetch': lambda: titan.statusbar(),
        'label': _statusbar_row,
        'press': lambda row: (True, _statusbar_row(row)),
    },
}

#: The order they are met in, which is the order the window's own tabs
#: are in - somebody who knows one should not have to learn the other.
PAGES = tuple((key, _PAGES[key]['name']) for key in (
    'applications', 'games', 'cling', 'im', 'macros', 'widgets', 'views',
    'menu', 'actions', 'settings', 'buffers', 'arrived', 'statusbar',
))
