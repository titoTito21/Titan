# -*- coding: utf-8 -*-
"""A reader module for the program you are in, written for you.

Writing an app module has always been the expensive part. JAWS's are code,
in a language of its own, and the reason almost every program on earth has
none is not that nobody wanted one - it is that writing one begins with
finding out what the program's controls are actually called, which is the
same work as using the program blind in the first place.

The reader has already done that work. It has walked the window; it knows
the lists, their column headings, the panes nobody named and whether the
whole thing answers nothing at all. So the starting point of a module is
not a blank file: it is what the reader can see, written down in the
module format, ready to be corrected.

Two levels, and the difference between them is exactly whether a model is
involved:

* **Observed** - no AI, no Titan, no network. Everything in the draft was
  really read off the window: the executable, the window class, each list
  with its own headings, each unnamed pane. It is dull and it is TRUE,
  which is the right property for something the reader will act on.
* **Written** - with Titan and AI features on, the observation is handed to
  a model along with the module format, and what comes back is checked
  against :func:`schema.problems` before it is offered. A model that
  invents a rule key produces a module that loads and quietly does nothing,
  which is the exact failure this format exists to prevent - so an invented
  key is a rejection, not a warning.

Nothing is ever written without being asked for, and nothing overwrites a
module that exists. A draft goes into the user's own module folder, which
is where their own modules live and where one shipped with the add-on can
never be silently replaced.
"""

import json
import os
import re

from . import compat
from . import i18n
from .readerModules import schema

_ = i18n.install(globals())

#: How much of a window is walked. This is a window that has just been
#: looked at on purpose, so it can afford more than the focus path - but a
#: tree with four thousand nodes in it is a program whose module wants
#: writing by hand anyway.
MAX_NODES = 400
MAX_DEPTH = 6

#: A model takes longer than a component does, and writing a module is one
#: of the longer things one is asked for here.
AI_TIMEOUT = 120.0


def _text(value):
    return str(value or '').strip()


def _role(obj):
    return _text(getattr(getattr(obj, 'role', None), 'name', '')).upper()


def _safe_name(text):
    plain = re.sub(r'[^A-Za-z0-9_.\- ]+', '', _text(text)).strip()
    return (plain or 'module').replace(' ', '_').lower()[:40]


# --------------------------------------------------------------------------- #
# What is really there
# --------------------------------------------------------------------------- #
def observe(obj):
    """Everything about this window a module could be written from.

    Read, never guessed. A field this could not fill in is absent rather
    than invented, because the whole value of the observed draft is that
    somebody can trust every line of it.
    """
    if obj is None:
        return {}
    top = _top_of(obj)
    found = {
        'executable': _text(getattr(getattr(top, 'appModule', None),
                                    'appName', '')),
        'class': _text(getattr(top, 'windowClassName', '')),
        'title': _text(getattr(top, 'name', '')),
        'lists': [],
        'unnamed': [],
        'regions': [],
        'drawn': False,
        'nodes': 0,
    }
    try:
        from . import semantics
        application = semantics.application_of(obj)
    except Exception:                                # noqa: BLE001
        application = None
    if application:
        found['titan'] = _text(application.get('id'))
        found['label'] = _text(application.get('label'))
    seen = 0
    for node, depth in _walk(top):
        seen += 1
        role = _role(node)
        name = _text(getattr(node, 'name', ''))
        if role in ('LIST', 'TABLE', 'DATAGRID', 'TREEVIEW'):
            found['lists'].append({'name': name,
                                   'role': role,
                                   'columns': _columns_of(node)})
        elif role in ('PANE', 'GROUPING', 'PROPERTYPAGE') and not name:
            found['unnamed'].append({'role': role, 'depth': depth,
                                     'class': _text(getattr(
                                         node, 'windowClassName', ''))})
        elif role in ('TOOLBAR', 'STATUSBAR', 'MENUBAR', 'TABCONTROL'):
            found['regions'].append({'role': role, 'name': name})
    found['nodes'] = seen
    try:
        from . import surface
        found['drawn'] = bool(surface.looks_drawn(top))
    except Exception:                                # noqa: BLE001
        pass
    try:
        # **What it is WRITTEN IN**, which is where every app module ever
        # written begins - and which decides what is even worth trying:
        # a Java frame answers nothing until the Access Bridge is on, a
        # Qt list reports no columns, a Unity window has nothing to walk
        # at all. Read from the libraries the process really loaded, so
        # it is evidence rather than a guess.
        from . import toolkit
        framework, how, evidence = toolkit.of(top)
        if framework:
            found['framework'] = framework
            found['framework_word'] = toolkit.word(framework)
            found['framework_how'] = how
            found['framework_evidence'] = evidence
            said = toolkit.note(framework)
            if said:
                found['framework_note'] = said
    except Exception:                                # noqa: BLE001
        pass
    return found


def _top_of(obj):
    api = compat.api
    if api is not None:
        try:
            foreground = api.getForegroundObject()
            if foreground is not None:
                return foreground
        except Exception:                            # noqa: BLE001
            pass
    return obj


def _walk(root):
    """The tree, breadth first and bounded. Yields ``(object, depth)``."""
    if root is None:
        return
    queue = [(root, 0)]
    seen = 0
    while queue and seen < MAX_NODES:
        node, depth = queue.pop(0)
        seen += 1
        yield node, depth
        if depth >= MAX_DEPTH:
            continue
        try:
            children = list(node.children or [])
        except Exception:                            # noqa: BLE001
            continue
        for child in children[:40]:
            queue.append((child, depth + 1))


def _columns_of(node):
    """A list's column headings, read off the control itself."""
    headers = []
    header = getattr(node, '_getColumnHeader', None)
    if not callable(header):
        # A list control answers about its headers through its ROWS in
        # NVDA, so the first row is asked when the list itself cannot.
        try:
            first = (list(node.children or []) or [None])[0]
        except Exception:                            # noqa: BLE001
            first = None
        if first is not None:
            return schema.headers_of(first)
        return headers
    try:
        count = int(getattr(node, 'columnCount', 0) or 0)
    except (TypeError, ValueError):
        count = 0
    for index in range(1, min(count, 16) + 1):
        try:
            headers.append(_text(header(index)))
        except Exception:                            # noqa: BLE001
            headers.append('')
    return headers


# --------------------------------------------------------------------------- #
# The draft itself
# --------------------------------------------------------------------------- #
def draft_for(obj):
    """A module for this window, made of what was observed. Never raises."""
    seen = observe(obj)
    if not seen:
        return {}, seen
    match = {}
    if seen.get('titan'):
        # Titan says which process is which, and it is the only identity
        # that is certain: every wxPython program shares a window class,
        # and Titan run from source is python.exe.
        match['titan'] = seen['titan']
    else:
        if seen.get('executable'):
            match['executable'] = seen['executable']
        if seen.get('class'):
            match['class'] = seen['class']
    module = {
        'id': _safe_name(seen.get('titan') or seen.get('executable')
                         or seen.get('title')),
        'label': seen.get('label') or seen.get('title') or
                 seen.get('executable') or '',
        'match': match,
        'source': 'observed',
    }
    lists = []
    for one in seen.get('lists') or []:
        columns = [column for column in (one.get('columns') or []) if column]
        if not columns:
            continue
        rule = {'match': {'columns': columns[:1]}}
        # A column called Type, Kind or their obvious neighbours already
        # holds the application's own word for what a row IS - which is
        # the single most useful line a module can carry, and the one
        # nothing else can work out.
        for column in columns:
            if column.lower() in ('type', 'kind', 'typ', 'rodzaj'):
                rule['kind_column'] = column
                break
        lists.append(rule)
    if lists:
        module['lists'] = lists
    regions = []
    for one in seen.get('regions') or []:
        if one.get('role') == 'STATUSBAR':
            module.setdefault('live', []).append(
                {'match': {'role': 'STATUSBAR'}, 'politeness': 'polite'})
    if seen.get('drawn'):
        module['surface'] = {'ocr': True}
    if regions:
        module['regions'] = regions
    return module, seen


# --------------------------------------------------------------------------- #
# The same, written by a model
# --------------------------------------------------------------------------- #
#: What the model is told. The format is described from the schema itself
#: rather than written out here, so a key added to :mod:`schema` cannot
#: leave this prompt teaching a format that no longer exists.
def _instructions(observation, module):
    return (
        'You are writing a screen reader module for one Windows program.\n'
        'It is DATA, not code: a JSON object, nothing else in your answer.\n'
        '\n'
        'The only keys a module may have: %s\n'
        'A match block may only use: %s\n'
        'A list rule may use: %s\n'
        'A region rule may use: %s\n'
        'A control rule may use: %s\n'
        'A live rule may use: %s (politeness is polite or assertive)\n'
        '\n'
        'Rules:\n'
        '- Use only what is in the observation. Do not invent a control, a '
        'column or a pane that is not there.\n'
        '- A rule may only ADD to what the reader says. Set "replace": true '
        'only where the reader would otherwise say nothing useful at all.\n'
        '- "say" for a region is a short name for a pane the program never '
        'named. Two or three words.\n'
        '- Keep the match block that is already in the draft.\n'
        '\n'
        'What the reader observed:\n%s\n\n'
        'The observed draft to improve:\n%s\n'
        % (', '.join(sorted(schema.KEYS)),
           ', '.join(sorted(schema.MATCH_KEYS)),
           ', '.join(sorted(schema.RULE_KEYS['lists'])),
           ', '.join(sorted(schema.RULE_KEYS['regions'])),
           ', '.join(sorted(schema.RULE_KEYS['controls'])),
           ', '.join(sorted(schema.RULE_KEYS['live'])),
           json.dumps(observation, ensure_ascii=False, indent=1)[:6000],
           json.dumps(module, ensure_ascii=False, indent=1)[:2000]))


def _json_in(text):
    """The JSON object in a model's answer, whatever it wrapped it in."""
    plain = str(text or '').strip()
    if not plain:
        return None
    start, end = plain.find('{'), plain.rfind('}')
    if start < 0 or end <= start:
        return None
    try:
        found = json.loads(plain[start:end + 1])
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def with_ai(obj, tries=3):
    """Have Titan's AI write the module. ``(module, sentence)``.

    The answer is checked TWICE, and the second check is the one that
    matters.

    **The schema asks whether it is well formed** - every key one that is
    read, every rule with a match block, nothing invented. Necessary, and
    not the question a user has.

    **The window itself asks whether it DOES anything** (:mod:`verify`).
    A module can pass the schema completely and be entirely dead: its
    match blocks name a class spelled slightly differently, a column the
    program calls something else, a role Windows reports as something
    adjacent. It loads, it is listed, it can be switched on, and not one
    rule ever fires - which from the outside is exactly a module that was
    never written. So it is run against the real controls of the real
    window, and the rules that matched nothing are named BACK TO THE
    MODEL, which is what lets it mend this module rather than write a
    different one.
    """
    module, observation = draft_for(obj)
    if not module:
        return {}, _('There is no window to write a module for.')
    from .link import LINK
    if not LINK.connected():
        return module, _('Titan is not running, so the observed draft is '
                         'all there is.')
    last = ''
    for _attempt in range(max(1, int(tries))):
        # **The typed doorway, not the action.** `ai.ask` answers
        # `{"answer": ...}` in one shape; the action layer answers prose in
        # the user's own language, and every live bug the other bridge in
        # this repository hit came from a client splitting up a sentence
        # written for a person.
        ok, data = LINK.bridge('ai.ask', timeout=AI_TIMEOUT,
                               question=_instructions(observation, module),
                               act=False)
        if not ok:
            return module, _text(data) or _('Titan\'s AI did not answer.')
        answer = (data or {}).get('answer') if isinstance(data, dict) else data
        written = _json_in(answer)
        if written is None:
            last = _('The AI did not answer with a module.')
            continue
        written.setdefault('match', module.get('match') or {})
        written.setdefault('id', module.get('id') or '')
        written['source'] = 'written'
        wrong = schema.problems(written)
        if wrong:
            last = _('The AI wrote a module with {count} problem(s): {what}') \
                .format(count=len(wrong), what='; '.join(wrong[:3]))
            module = written
            continue
        # Well formed. Now: does it do anything to the window it was
        # written for?
        try:
            from . import verify
            report = verify.check(written, obj)
        except Exception:                            # noqa: BLE001
            return written, ''
        complaint = ''
        try:
            complaint = verify.complaint(report)
        except Exception:                            # noqa: BLE001
            complaint = ''
        if not complaint:
            return written, ''
        # Every rule dead is a module worth nothing; some rules dead is a
        # module worth keeping if the next attempt cannot better it.
        last = verify.sentence(report)
        module = written
        if _attempt + 1 < max(1, int(tries)):
            observation = dict(observation)
            observation['what_went_wrong_last_time'] = complaint
            continue
        if report.get('works'):
            # Some of it fires. Kept, and the user is told which parts
            # would never have.
            return written, last
    return module, last


# --------------------------------------------------------------------------- #
# Keeping it
# --------------------------------------------------------------------------- #
def save(module, name='', overwrite=False):
    """Write a module into the user's own folder. ``(path, sentence)``."""
    from . import readerModules
    folder = readerModules.user_folder()
    if not folder:
        return '', _('There is nowhere to write it: NVDA has no '
                     'configuration folder.')
    wrong = schema.problems(module)
    if wrong:
        return '', _('That is not a module: {what}').format(
            what='; '.join(wrong[:3]))
    filename = _safe_name(name or module.get('id') or 'module') + '.json'
    where = os.path.join(folder, filename)
    if os.path.exists(where) and not overwrite:
        return '', _('There is already a module called {name}. It has not '
                     'been touched.').format(name=filename)
    try:
        with open(where, 'w', encoding='utf-8') as handle:
            json.dump(module, handle, ensure_ascii=False, indent=1,
                      sort_keys=True)
    except Exception as error:                       # noqa: BLE001
        return '', _('It could not be written: {why}').format(why=error)
    readerModules.reload()
    return where, ''
