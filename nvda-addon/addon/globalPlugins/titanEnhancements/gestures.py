# -*- coding: utf-8 -*-
"""Every Titan action, as a key of the user's own choosing.

The add-on ships eight gestures, and eight is not the number of things Titan
can do - it is somewhere over two hundred, across every component,
application, launcher, TTS engine and shell add-on the user has installed,
and one more the day they install another. A menu that drills down to them
(``commands.actions``) is how they are all REACHABLE; it is not how the one
you use forty times a day should be reached.

So each of them is offered to NVDA as a script of its own. That is not a
Titan invention and deliberately not a keyboard layer of our own: NVDA's
**Input Gestures** dialog lists every script every running plugin exposes,
and the user binds whichever they like to whatever they like - a key, a
touch gesture, a braille display button. Titan's AI OCR, its assistant, its
macros, its notes, its downloader, its Titan-Net mailbox are then reader
commands in the same dialog, under the same rules, remembered by NVDA in the
user's own profile.

Three things make that work rather than nearly work:

* **A script name never changes.** NVDA remembers a binding by the script's
  NAME, so ``titan_tnotes_create_note`` is derived from the add-on and the
  action and from nothing else - not from the label, which is translated,
  and not from a position in a list, which moves the moment an add-on is
  installed.
* **The scripts exist before Titan does.** NVDA usually starts first, and a
  gesture the user has bound must not be missing until the desktop comes up
  - a key that does nothing is indistinguishable from a key that is bound to
  nothing. The catalogue is cached in NVDA's own configuration and the
  scripts are built from it at startup; a bound gesture pressed with Titan
  off says Titan is not running, which is an answer.
* **An action that needs something asks for it.** Titan's action layer has
  three outcomes rather than two - done, could not, and needs to know
  something first - so a script that fires an action needing a file name
  puts the question up and runs it again with the answer. Without that,
  binding a key to "create a note" would be binding a key to a refusal.
"""

import json
import os
import re
import threading

from . import dialogs
from . import i18n
from .link import LINK

_ = i18n.install(globals())

#: Where the catalogue is kept so the scripts survive a Titan that is not
#: running yet. NVDA's own configuration directory, because that is where
#: the gesture bindings pointing at these names live too.
CATALOGUE_FILE = 'titanActions.json'

#: A whole sweep of summaries is one bridge call per add-on. It is worth
#: doing (the summary is what the Input Gestures dialog SHOWS, and a list of
#: bare action names is a list nobody can choose from) and it is worth doing
#: only when the catalogue has really changed.
SWEEP_PAUSE = 0.05

#: How many actions may become scripts. There is no technical ceiling; this
#: is here so that a Titan with something pathological installed cannot make
#: the Input Gestures dialog unusable.
MAX_SCRIPTS = 600

_LOCK = threading.RLock()
_installed = []                                      # script attribute names
_sweeping = False


# --------------------------------------------------------------------------- #
# Names
# --------------------------------------------------------------------------- #
_UNSAFE = re.compile(r'[^0-9a-zA-Z]+')

def script_name(addon, action, key=''):
    """The name NVDA remembers a binding by. Stable, or the binding is lost.

    ``key`` is what tells one row from another when the ACTION is the same.
    Every Titan macro is `macros.run_macro` with a different name, and a user
    who has bound five of them to five keys must get five scripts - one per
    macro - or the last one built would answer all five bindings.
    """
    parts = ['titan', _UNSAFE.sub('_', str(addon or '')).strip('_'),
             _UNSAFE.sub('_', str(action or '')).strip('_')]
    if key:
        parts.append(_UNSAFE.sub('_', str(key)).strip('_'))
    return '_'.join(part for part in parts if part)


def attribute_name(addon, action, key=''):
    return 'script_' + script_name(addon, action, key)


# --------------------------------------------------------------------------- #
# The catalogue
# --------------------------------------------------------------------------- #
def _catalogue_path():
    try:
        import globalVars
        directory = globalVars.appArgs.configPath
    except Exception:                                # noqa: BLE001
        directory = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(directory, CATALOGUE_FILE)


def load_catalogue():
    """What Titan could do the last time we asked. ``[]`` when we never have."""
    try:
        with open(_catalogue_path(), 'r', encoding='utf-8') as handle:
            rows = json.load(handle)
    except Exception:                                # noqa: BLE001
        return []
    return [row for row in rows if isinstance(row, dict)
            and row.get('addon') and row.get('action')]


def save_catalogue(rows):
    try:
        with open(_catalogue_path(), 'w', encoding='utf-8') as handle:
            json.dump(rows, handle, ensure_ascii=False, indent=1)
        return True
    except Exception:                                # noqa: BLE001
        return False


def catalogue_from_addons(addons):
    """The rows ``addons.list`` gives, flattened one per action.

    ``addons.list`` is ONE call and carries the action names, which is all a
    script needs to exist. The summaries - which are what the user reads in
    the Input Gestures dialog - are a call per add-on and are filled in
    afterwards, so a fresh Titan is bindable a second after it connects
    rather than thirty.
    """
    rows = []
    for addon in addons or []:
        if not isinstance(addon, dict):
            continue
        addon_id = str(addon.get('id') or '')
        if not addon_id:
            continue
        label = str(addon.get('label') or addon_id)
        for action in addon.get('actions') or []:
            rows.append({'addon': addon_id, 'label': label,
                         'action': str(action), 'summary': '',
                         'risk': 'auto', 'params': [], 'needs_ai': False})
            if len(rows) >= MAX_SCRIPTS:
                return rows
    return rows


def _merge_summaries(rows, addon_id, described):
    """Put what an add-on says about its own actions onto its rows."""
    by_name = {}
    for action in described or []:
        if isinstance(action, dict) and action.get('name'):
            by_name[str(action['name'])] = action
    changed = False
    for row in rows:
        if row['addon'] != addon_id or row.get('key'):
            # A row that carries its own arguments carries its own words
            # too: every macro row is the same ACTION, so the action's
            # summary would name all of them "run a macro".
            continue
        action = by_name.get(row['action'])
        if action is None:
            continue
        summary = str(action.get('summary') or '')
        params = [p for p in (action.get('params') or [])
                  if isinstance(p, dict) and p.get('name')]
        risk = str(action.get('risk') or 'auto')
        needs_ai = bool(action.get('needs_ai'))
        if (row['summary'], row['risk'], row['needs_ai']) != \
                (summary, risk, needs_ai) or row['params'] != params:
            row.update({'summary': summary, 'params': params,
                        'risk': risk, 'needs_ai': needs_ai})
            changed = True
    return changed


# --------------------------------------------------------------------------- #
# One key, one macro
# --------------------------------------------------------------------------- #
#: **This is what a Leasey script is, on this desktop.**
#:
#: Every Titan ACTION is already a bindable NVDA script, which is most of a
#: hot-key manager - but "run a macro" is one action taking the macro's name,
#: so binding it gets the user a key that asks WHICH macro. That is not a
#: macro on a key; it is a menu on a key.
#:
#: A macro is where the user's own work lives. Titan Script is a real little
#: language whose statements are Titan's own actions - it can speak, place a
#: sound, put a form up, read a setting, drive another program - and it is
#: checked before it is saved. So the useful thing is not another scripting
#: language in the reader: it is that every script the user has ALREADY
#: written gets a key of its own, in NVDA's own Input Gestures dialog, under
#: its own name.
#:
#: The name is what the binding is remembered by, so renaming a macro loses
#: its key. That is honest and there is no way round it: NVDA remembers a
#: gesture by the script's name, and a macro has nothing else stable to be
#: named after.
MAX_MACROS = 200


def macro_rows():
    """One row per macro the user has. ``[]`` when Titan has none.

    Read through the typed doorway (`macros.list` answers JSON) rather than
    out of the prose action, because the prose one answers a LINE - "- Voice
    demo (ctrl+alt+v) [tcs]" - and this repository has already had a bridge
    read a macro's name out of one of those and get the whole line.
    """
    ok, data = LINK.bridge('macros.list')
    if not ok or not isinstance(data, dict):
        return []
    rows = []
    for macro in (data.get('macros') or [])[:MAX_MACROS]:
        if not isinstance(macro, dict):
            continue
        name = str(macro.get('name') or '').strip()
        if not name:
            continue
        summary = str(macro.get('description') or '').strip()
        shortcut = str(macro.get('shortcut') or macro.get('hotkey') or '')
        if not summary:
            summary = (_('the macro "{name}", with its own key in Titan: {key}')
                       .format(name=name, key=shortcut) if shortcut
                       else _('the macro "{name}"').format(name=name))
        rows.append({
            'addon': 'macros', 'label': _('Titan macros'),
            'action': 'run_macro', 'key': name, 'summary': summary,
            # The one parameter it would otherwise stop and ask for.
            'arguments': {'name': name},
            'risk': 'auto', 'params': [], 'needs_ai': False})
    return rows


# --------------------------------------------------------------------------- #
# Running one
# --------------------------------------------------------------------------- #
def _needed(row):
    """The parameters this action cannot run without."""
    return [p for p in (row.get('params') or []) if p.get('required')]


def _confirm(row, then):
    """Ask before something that cannot be taken back.

    Only for ``always_confirm``. An action marked merely ``confirm`` is one
    the AI is made to check before it acts on its own initiative - a user who
    has deliberately bound a key to it has already said yes, and asking them
    again on every press would be Titan second-guessing a decision they made
    in the Input Gestures dialog.
    """
    if str(row.get('risk') or '') != 'always_confirm':
        then()
        return
    label = row.get('summary') or '{}.{}'.format(row['addon'], row['action'])
    dialogs.confirm(_('{what}\n\nGo ahead?').format(what=label),
                    _('Titan'), then)


def _ask_each(questions, gathered, then):
    """Ask for what is missing, one window at a time, then carry on.

    Recursive rather than a loop because every one of these is a dialog on
    NVDA's main thread that answers through a callback: a loop here would be
    a reader that has stopped reading while it waits.
    """
    if not questions:
        then(gathered)
        return
    question = questions[0]
    rest = questions[1:]

    def answered(value):
        if value is None:
            return                                   # cancelled: nothing runs
        gathered[question['name']] = value
        _ask_each(rest, gathered, then)

    prompt = str(question.get('prompt') or question.get('description')
                 or question['name'])
    options = [str(o) for o in (question.get('options') or [])]
    if options:
        dialogs.choose(options, _('Titan'), prompt,
                       lambda index: answered(options[index])
                       if 0 <= index < len(options) else None)
    else:
        dialogs.ask_text(prompt, _('Titan'), answered,
                         default=str(question.get('default') or ''))


def run(row):
    """One action, with whatever it needs asked for. Never on the main thread."""
    # What the ROW already answers. A macro's gesture is the macro add-on's
    # own run action with that macro's name filled in, so the parameter that
    # would otherwise be asked for is not missing at all - and asking "which
    # macro?" after the user has pressed the key they bound to one macro is
    # the whole point of binding it thrown away.
    fixed = dict(row.get('arguments') or {})

    def go(arguments):
        given = dict(fixed)
        given.update(arguments or {})

        def work():
            _run_and_answer(row, given, depth=0)
        threading.Thread(target=work, name='TitanAction', daemon=True).start()

    missing = [{'name': p['name'],
                'prompt': p.get('description') or p['name'],
                'options': p.get('enum') or p.get('options') or []}
               for p in _needed(row) if p['name'] not in fixed]
    _confirm(row, lambda: _ask_each(missing, {}, go))


#: An action may ask for one thing, be given it, and ask for another. This is
#: how many times round that may go before we decide something is wrong -
#: high enough for a real form, low enough that a handler with a bug cannot
#: put dialogs up for ever.
MAX_QUESTIONS = 6


def _run_and_answer(row, arguments, depth):
    """Run it, and answer what it asks for until it stops asking."""
    ok, data = LINK.bridge('addons.run', addon=row['addon'],
                           action=row['action'], args=arguments)
    if not ok:
        dialogs.report(str(data))
        return
    if not isinstance(data, dict):
        dialogs.report(str(data) or _('Done.'))
        return
    question = data.get('question')
    if question and depth < MAX_QUESTIONS:
        # Titan's third outcome: not done, not failed - it needs to know
        # something first. Ask, and come back with the answer.
        def answered(gathered):
            def work():
                merged = dict(arguments)
                merged.update(gathered)
                _run_and_answer(row, merged, depth + 1)
            threading.Thread(target=work, name='TitanAction',
                             daemon=True).start()
        _ask_each([{'name': question.get('name') or 'answer',
                    'prompt': question.get('prompt') or '',
                    'options': question.get('options') or [],
                    'default': question.get('default') or ''}], {}, answered)
        return
    text = str(data.get('text') or '')
    dialogs.report(text or (_('Done.') if data.get('ok', True)
                            else _('That did not work.')))


# --------------------------------------------------------------------------- #
# Making them scripts
# --------------------------------------------------------------------------- #
def _build_script(row):
    """One NVDA script for one Titan action.

    **It goes on the plugin\'s CLASS, so it takes ``self``.** That is not a
    style choice and it was the whole feature being broken: NVDA\'s Input
    Gestures dialog does not list what ``dir(plugin)`` shows. Its
    ``_AllGestureMappingsRetriever.addObj`` walks ``obj.__class__.__mro__``
    and reads ``cls.__dict__`` - so a script set on the INSTANCE runs
    perfectly once a gesture is bound to it and can never be FOUND to bind
    one, which is every Titan action invisible in the one dialog this whole
    module exists to put them in. Read out of the running NVDA\'s own
    ``inputCore``, not guessed.
    """
    def titan_action_script(_self, _gesture=None):
        if not LINK.connected():
            dialogs.report(_('Titan is not running.'))
            return
        run(row)

    label = row.get('label') or row['addon']
    summary = row.get('summary') or ''
    what = '{}: {}'.format(label, summary) if summary \
        else '{}: {}'.format(label, row['action'])
    if row.get('needs_ai'):
        what += ' ' + _('(needs AI features)')
    # NVDA reads the docstring for the description column of its Input
    # Gestures dialog, and `category` for the group the row sits in. One
    # group per add-on, so a user looking for "the notes" finds every one of
    # its actions together rather than two hundred rows under "Titan".
    titan_action_script.__doc__ = what
    titan_action_script.__name__ = script_name(row['addon'], row['action'],
                                               row.get('key', ''))
    titan_action_script.category = _('Titan: {label}').format(label=label)
    return titan_action_script


def _host(plugin):
    """Where a script has to live to be BINDABLE, not merely runnable.

    NVDA finds a script to RUN with ``getattr(obj, 'script_<name>')``, which
    an instance attribute answers - and it finds a script to OFFER in the
    Input Gestures dialog by walking ``obj.__class__.__mro__`` and reading
    each ``cls.__dict__``, which an instance attribute does not appear in at
    all. Both have to be true, so the class is the only place that works.

    A plugin handed in as an instance therefore contributes its class; a
    class handed in directly (which is what a test does) is used as it is.
    """
    return plugin if isinstance(plugin, type) else type(plugin)


def install(plugin, rows=None):
    """Put a script on ``plugin``'s class for every action in the catalogue.

    Called again whenever the catalogue changes; anything that has gone is
    removed, so an add-on the user uninstalled does not leave a gesture that
    reaches a Titan action nobody has any more.
    """
    global _installed
    rows = load_catalogue() if rows is None else rows
    host = _host(plugin)
    wanted = {}
    for row in rows[:MAX_SCRIPTS]:
        try:
            wanted[attribute_name(row['addon'], row['action'],
                                  row.get('key', ''))] = row
        except Exception:                            # noqa: BLE001
            continue
    with _LOCK:
        for stale in _installed:
            if stale not in wanted:
                # Only ever what this module put there: `_installed` is the
                # record, and the add-on's own dozen scripts are written on
                # the class by hand and must survive every sweep.
                try:
                    delattr(host, stale)
                except Exception:                    # noqa: BLE001
                    pass
        for name, row in wanted.items():
            try:
                setattr(host, name, _build_script(row))
            except Exception:                        # noqa: BLE001
                pass
        _installed = list(wanted)
    return len(wanted)


def bindable(plugin):
    """Every Titan action NVDA would really OFFER in Input Gestures.

    Asked the way NVDA asks it - the class chain, each class's own
    ``__dict__`` - because "the attribute is there" and "the dialog lists
    it" turned out to be different questions, and only the second one is
    what the user experiences.
    """
    found = set()
    for cls in getattr(_host(plugin), '__mro__', ()):
        for name in vars(cls):
            if name.startswith('script_titan_'):
                found.add(name)
    return sorted(found)


def refresh(plugin, on_done=None):
    """Ask Titan what it can do now, and rebuild the scripts from the answer.

    On a worker: this is a bridge call per add-on and it happens the moment
    Titan connects, which is not a moment to stop the reader in.
    """
    global _sweeping
    with _LOCK:
        if _sweeping:
            return False
        _sweeping = True

    def work():
        global _sweeping
        try:
            _sweep(plugin, on_done)
        except Exception as error:                   # noqa: BLE001
            from . import compat
            if compat.log is not None:
                compat.log.error(f'Titan action catalogue: {error}')
        finally:
            with _LOCK:
                _sweeping = False
    threading.Thread(target=work, name='TitanCatalogue', daemon=True).start()
    return True


def _sweep(plugin, on_done=None):
    import time

    ok, data = LINK.bridge('addons.list')
    if not ok:
        return
    # The same answer says which PROCESS each add-on is, which is how a
    # window is recognised as a Titan application's. It costs no call of
    # its own, and it is refreshed exactly when the catalogue is.
    try:
        from . import semantics
        semantics.note_addons((data or {}).get('addons'))
    except Exception:                                # noqa: BLE001
        pass
    rows = catalogue_from_addons((data or {}).get('addons'))
    rows += macro_rows()
    if not rows:
        return
    # The scripts exist as soon as the names are known: a summary is worth
    # waiting for in the dialog, not worth waiting for before a key works.
    install(plugin, rows)
    for addon_id in sorted({row['addon'] for row in rows}):
        ok, described = LINK.bridge('addons.actions', addon=addon_id)
        if ok and isinstance(described, dict):
            _merge_summaries(rows, addon_id, described.get('actions'))
        time.sleep(SWEEP_PAUSE)
    install(plugin, rows)
    save_catalogue(rows)
    if on_done is not None:
        try:
            on_done(len(rows))
        except Exception:                            # noqa: BLE001
            pass


def installed():
    """How many Titan actions are bindable right now."""
    with _LOCK:
        return len(_installed)
