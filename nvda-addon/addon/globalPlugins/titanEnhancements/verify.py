# -*- coding: utf-8 -*-
"""Does this reader module actually DO anything to this window?

:mod:`readerModules.schema` answers whether a module is well formed - every
key is one that is read, every rule has a match block, nothing is invented.
That is necessary and it is not the question a user has.

**A module can be perfectly well formed and completely dead.** Its match
block names a class that is spelled slightly differently, a column heading
that the program calls something else, a role that Windows reports as
something adjacent - and it loads, it is listed, it can be switched on, and
not one of its rules ever fires. From the outside that is exactly the same
as a module that was never written, and for somebody who cannot see the
screen it is indistinguishable from a reader that has stopped working. It
is the failure this whole file exists to prevent, and it is the one the
schema cannot see.

So this runs the module against the window it was written for, inside the
NVDA that is really running, and counts. A rule that matched nothing is
named; a module where NOTHING matched is refused rather than saved.

**It reads and it changes nothing.** No control is pressed, nothing is
typed, no store is written, and the module being checked is never
installed to check it - it is applied by hand, here, to objects that are
already on the screen.
"""

import threading

from . import i18n

_ = i18n.install(globals())

#: How many controls of a window to walk. A window with three thousand
#: controls in it is a window this must not spend a second on: the sample
#: answers the question ("does anything match?") long before the end.
LIMIT = 400

#: The sections of a module that carry rules, in the order a person would
#: read them.
SECTIONS = ('lists', 'regions', 'controls', 'live')

_LOCK = threading.RLock()


def _text(value):
    return str(value or '').strip()


def _walk(root, limit=LIMIT):
    """Every control of this window, breadth first, bounded.

    Breadth first on purpose: a window's own toolbars, lists and panes are
    near the top, and a depth-first walk of a document spends the whole
    budget inside the first paragraph.
    """
    seen = 0
    queue = [root]
    while queue and seen < limit:
        node = queue.pop(0)
        if node is None:
            continue
        seen += 1
        yield node
        try:
            children = list(node.children or [])
        except Exception:                            # noqa: BLE001
            children = []
        queue.extend(children)


def _top_of(obj):
    node = obj
    for _step in range(32):
        parent = getattr(node, 'parent', None)
        if parent is None:
            break
        try:
            if getattr(parent, 'windowHandle', 0) == 0:
                break
        except Exception:                            # noqa: BLE001
            break
        node = parent
    return node


def _describe_rule(section, index, rule):
    """One line naming the rule, so a report can be read aloud."""
    match = rule.get('match') if isinstance(rule, dict) else None
    said = []
    if isinstance(match, dict):
        for key in ('role', 'class', 'name', 'automation_id', 'id',
                    'columns', 'title', 'unnamed'):
            if key in match:
                said.append('%s=%s' % (key, match[key]))
    return '%s %d%s' % (section, index + 1,
                        (' (' + ', '.join(said[:3]) + ')') if said else '')


def check(module, obj, limit=LIMIT):
    """``{...}`` - what this module really does to the window ``obj`` is in.

    Every key is a fact that was counted, never an opinion:

    ``controls``   how many controls were looked at
    ``rules``      one row per rule: section, index, how many it matched,
                   and an example of what it matched
    ``dead``       the rules that matched nothing - the whole point
    ``alive``      how many rules matched at least one control
    ``works``      whether ANY rule fired, which is what decides whether
                   the module is worth keeping at all
    """
    from .readerModules import schema
    report = {'controls': 0, 'rules': [], 'dead': [], 'alive': 0,
              'works': False, 'why': ''}
    if not isinstance(module, dict) or obj is None:
        report['why'] = _('There is nothing to check.')
        return report
    top = _top_of(obj)
    application = ''
    try:
        application = _text(getattr(getattr(top, 'appModule', None),
                                    'appName', ''))
    except Exception:                                # noqa: BLE001
        application = ''

    # The window's own match block first: a module whose `match` does not
    # match this window would never be consulted here at all, and every
    # rule below it would then be reported dead for the wrong reason.
    fits = True
    try:
        fits = bool(schema.matches(module.get('match') or {}, top,
                                   application=application))
    except Exception:                                # noqa: BLE001
        fits = True
    report['matches_this_window'] = fits
    if not fits:
        report['why'] = _('This module does not claim this window at all, '
                          'so none of its rules would ever be asked.')
        return report

    nodes = []
    for node in _walk(top, limit):
        nodes.append(node)
    report['controls'] = len(nodes)
    if not nodes:
        report['why'] = _('This window answered with no controls, so there '
                          'is nothing for a rule to match.')
        return report

    headers = {}
    for section in SECTIONS:
        rules = module.get(section) or []
        if not isinstance(rules, list):
            continue
        for index, rule in enumerate(rules):
            if not isinstance(rule, dict):
                continue
            matched = 0
            example = ''
            for node in nodes:
                try:
                    if id(node) not in headers:
                        headers[id(node)] = schema.headers_of(node)
                    if schema.matches(rule.get('match') or {}, node,
                                      application=application,
                                      headers=headers[id(node)]):
                        matched += 1
                        if not example:
                            example = _text(getattr(node, 'name', '')) \
                                or _text(getattr(getattr(node, 'role', None),
                                                 'name', ''))
                except Exception:                    # noqa: BLE001
                    continue
            row = {'section': section, 'index': index, 'matched': matched,
                   'example': example,
                   'said': _describe_rule(section, index, rule)}
            report['rules'].append(row)
            if matched:
                report['alive'] += 1
            else:
                report['dead'].append(row['said'])
    report['works'] = report['alive'] > 0
    if not report['rules']:
        report['why'] = _('This module has no rules at all, so there is '
                          'nothing for it to do.')
    elif not report['works']:
        report['why'] = _('Not one of its {count} rule(s) matched anything '
                          'in this window.').format(count=len(report['rules']))
    return report


def sentence(report):
    """The check as one thing a person can be told."""
    if not isinstance(report, dict):
        return ''
    if report.get('why') and not report.get('works'):
        return report['why']
    alive = int(report.get('alive') or 0)
    rules = len(report.get('rules') or [])
    dead = report.get('dead') or []
    said = _('{alive} of {rules} rule(s) matched something in this window, '
             'out of {controls} control(s) looked at.').format(
        alive=alive, rules=rules, controls=report.get('controls') or 0)
    if dead:
        said += ' ' + _('These matched nothing: {what}.').format(
            what='; '.join(dead[:4]))
    return said


def complaint(report):
    """What to tell the MODEL about it, or '' when there is nothing wrong.

    Deliberately not the sentence above: a person is told what happened,
    and a model is told what to change. Naming the rules that matched
    nothing is the whole of it - a model handed "it does not work" writes
    a different module rather than mending this one.
    """
    if not isinstance(report, dict):
        return ''
    if not report.get('matches_this_window', True):
        return ('The module\'s own match block does not match this window. '
                'Use the one from the observed draft, unchanged.')
    dead = report.get('dead') or []
    if not report.get('rules'):
        return ('The module has no rules, so it does nothing. Write rules '
                'for what the observation actually shows.')
    if not report.get('works'):
        return ('Not one rule matched anything in the real window. Every '
                'rule below matched nothing - the match blocks name '
                'something that is not there: %s. Use only the roles, '
                'classes, names and column headings that appear in the '
                'observation, spelled exactly as they appear.'
                % '; '.join(dead[:6]))
    if dead:
        return ('These rules matched nothing in the real window and would '
                'never fire: %s. Correct their match blocks to name what '
                'the observation really shows, or take them out.'
                % '; '.join(dead[:6]))
    return ''
