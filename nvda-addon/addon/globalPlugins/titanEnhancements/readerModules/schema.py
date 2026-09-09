# -*- coding: utf-8 -*-
"""What a reader module IS, and how one is matched to a window.

A JAWS app module is a script file its vendor writes for one program. That
model buys the one thing a generic reader cannot have - knowing that the
third column of THIS list is a file type and that THAT unnamed pane is the
message body - and it costs the thing that has kept it rare for thirty
years: it is code, in the reader's own language, that only somebody working
on the reader can write.

A Titan reader module is the same knowledge as **data**, and the difference
is not tidiness:

* **It is checkable.** A rule that names a column heading no list has, or a
  role that does not exist, is found by reading the module rather than by a
  user noticing a control has gone quiet.
* **It cannot crash the reader.** There is no module here that runs on the
  focus path; there are rules that are looked up. The worst a wrong module
  can do is describe a control wrongly, which the user hears and can turn
  off.
* **Anybody can write one.** A built-in module is a Python file in this
  package because that is convenient for the ones shipped here; a user's is
  the same mapping as JSON in their own NVDA folder, and neither is more
  privileged than the other.
* **It never asks the application for anything.** Every module here was
  written by READING the program - Titan's applications are in this
  repository - and not one line of any of them was changed. A reader module
  is knowledge about somebody else's program, which is what it has to be
  for the programs nobody here wrote.

**A module may only ADD, unless it says otherwise.** That is the whole
safety rule, and it is the answer to "what happens when a module is wrong":
by default the module sharpens what NVDA says - a name for an unnamed pane,
a word for what a row IS, a column NVDA never reads - and NVDA's own report
still happens. A rule that wants to stand in NVDA's place says ``replace``,
per rule, so a mistake costs one control's wording rather than the reader.
"""

import fnmatch
import re

#: Every key a module may carry. A key that is not here is a key nothing
#: reads, which in a data format is a rule the author believes they have
#: written - so it is reported rather than ignored.
KEYS = frozenset({
    'id', 'label', 'match', 'title_is_a_place', 'lists', 'regions',
    'controls', 'live', 'labels', 'surface', 'notes', 'source',
})

#: What a rule may be matched on. All of it is read off the object, and
#: none of it is asked of the application.
MATCH_KEYS = frozenset({
    'titan', 'executable', 'class', 'title', 'name', 'role', 'id',
    'automation_id', 'columns', 'unnamed',
})

RULE_KEYS = {
    'lists': frozenset({'match', 'kind_column', 'noun', 'quiet', 'replace',
                        'columns', 'say'}),
    'regions': frozenset({'match', 'say', 'replace'}),
    'controls': frozenset({'match', 'say_role', 'say', 'note', 'replace',
                           'label'}),
    'live': frozenset({'match', 'politeness', 'say', 'prefix'}),
}


def _text(value):
    return str(value or '').strip()


def _glob(pattern, value):
    """A pattern the way a person writes one: exact, or with ``*``.

    Case-insensitive on purpose. Every one of these is matched against a
    name a program wrote for a person to read, and a module that missed
    because a program capitalises "File list" differently in one release
    would be a module that silently stopped working.
    """
    pattern, value = _text(pattern), _text(value)
    if not pattern:
        return not value
    return fnmatch.fnmatch(value.lower(), pattern.lower())


def _role_of(obj):
    return _text(getattr(getattr(obj, 'role', None), 'name', '')).upper()


def _name_of(obj):
    try:
        return _text(obj.name)
    except Exception:                                # noqa: BLE001
        return ''


def headers_of(obj):
    """The column headings of the list this row is in, lower-cased.

    Read off the control, which is what makes a module portable: the
    heading is the application's own word, already in the user's language,
    so a module written against "Type" matches a Polish Titan's "Typ" only
    if the module says so - and a module that wants both says both.
    """
    out = []
    header = getattr(obj, '_getColumnHeader', None)
    if not callable(header):
        return out
    count = 0
    for source in (getattr(obj, 'parent', None), obj):
        try:
            count = int(getattr(source, 'columnCount', 0) or 0)
        except (TypeError, ValueError):
            count = 0
        if count:
            break
    for index in range(1, min(count, 16) + 1):
        try:
            out.append(_text(header(index)))
        except Exception:                            # noqa: BLE001
            out.append('')
    return out


def matches(rule_match, obj, application=None, headers=None):
    """Whether one ``match`` block is true of this object.

    Every key present must be true - a rule with two conditions means both,
    which is what somebody writing one expects and the opposite of what a
    "first key wins" reading would do.
    """
    if not rule_match:
        return True
    if not isinstance(rule_match, dict):
        return False
    for key, wanted in rule_match.items():
        if key == 'titan':
            if _text((application or {}).get('id')).lower() != _text(wanted).lower():
                return False
        elif key == 'role':
            wanted_roles = wanted if isinstance(wanted, (list, tuple)) else [wanted]
            if _role_of(obj) not in {_text(one).upper() for one in wanted_roles}:
                return False
        elif key in ('name', 'title'):
            if not _glob(wanted, _name_of(obj)):
                return False
        elif key == 'unnamed':
            if bool(wanted) != (not _name_of(obj)):
                return False
        elif key == 'executable':
            if not _glob(wanted, _executable(obj)):
                return False
        elif key == 'class':
            if not _glob(wanted, _text(getattr(obj, 'windowClassName', ''))):
                return False
        elif key == 'automation_id':
            if not _glob(wanted, _text(getattr(obj, 'UIAAutomationId', ''))):
                return False
        elif key == 'columns':
            names = [one.lower() for one in
                     (headers if headers is not None else headers_of(obj))]
            for one in (wanted if isinstance(wanted, (list, tuple)) else [wanted]):
                if _text(one).lower() not in names:
                    return False
        else:
            return False
    return True


def _executable(obj):
    try:
        return _text(getattr(getattr(obj, 'appModule', None), 'appName', ''))
    except Exception:                                # noqa: BLE001
        return ''


class Module:
    """One application, as far as the reader is concerned."""

    def __init__(self, data, source='built-in'):
        data = dict(data or {})
        self.data = data
        self.id = _text(data.get('id'))
        self.label = _text(data.get('label')) or self.id
        self.match = dict(data.get('match') or {})
        self.source = _text(data.get('source')) or source
        self.title_is_a_place = bool(data.get('title_is_a_place'))
        self.lists = list(data.get('lists') or [])
        self.regions = list(data.get('regions') or [])
        self.controls = list(data.get('controls') or [])
        self.live = list(data.get('live') or [])
        self.labels = dict(data.get('labels') or {})
        self.surface = dict(data.get('surface') or {})

    # ------------------------------------------------------------ matching
    def owns(self, obj, application=None):
        """Whether this module is about the window ``obj`` is in.

        The Titan add-on id is asked FIRST and is the only one that is
        really certain: Titan says which process is which, and every other
        signal about a wxPython window - the class, the title, even the
        executable when Titan is run from source - is shared with every
        other Python program on the machine.
        """
        wanted = _text(self.match.get('titan'))
        if wanted:
            return _text((application or {}).get('id')).lower() == wanted.lower()
        if not self.match:
            return False
        return matches(self.match, obj, application)

    # --------------------------------------------------------------- rules
    def _first(self, rules, obj, application, headers=None):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            if matches(rule.get('match'), obj, application, headers):
                return rule
        return None

    def list_rule(self, obj, application=None, headers=None):
        """The rule for the list this ROW belongs to, or None.

        Matched against the row's own list where the rule names one, which
        is why the list's name is looked at through the parent: a row is
        called "readme.txt" and the thing a module knows about is the list
        it is in.
        """
        parent = None
        try:
            parent = obj.parent
        except Exception:                            # noqa: BLE001
            parent = None
        for rule in self.lists:
            if not isinstance(rule, dict):
                continue
            block = rule.get('match') or {}
            against = obj
            if any(key in block for key in ('name', 'title', 'automation_id',
                                            'unnamed')) and parent is not None:
                against = parent
            if matches(block, against, application, headers):
                return rule
        return None

    def region_word(self, obj, role='', name=''):
        """A name for a place the program never named, or ''."""
        for rule in self.regions:
            if matches(rule.get('match'), obj):
                return _text(rule.get('say'))
        return ''

    def control_rule(self, obj, application=None):
        return self._first(self.controls, obj, application)

    def live_rule(self, obj, application=None):
        return self._first(self.live, obj, application)

    def label_for(self, key):
        return _text(self.labels.get(key))

    def reads_surface(self):
        """Whether this application draws its own interface and must be READ.

        A Unity game, an installer that paints its own widgets, a program
        with no accessibility at all: there is nothing to ask, so the only
        honest answer is a picture. A module says so rather than the reader
        guessing, because guessing wrong means sending a picture of
        somebody's screen to an AI provider they did not ask.
        """
        return bool(self.surface.get('ocr'))


# --------------------------------------------------------------------------- #
# Checking one, which is the whole reason for it being data
# --------------------------------------------------------------------------- #
def problems(data):
    """Everything wrong with a module, as sentences. ``[]`` when it is fine.

    A rule nothing reads is the failure this catches: a module whose author
    wrote ``kind`` where ``kind_column`` was wanted loads, matches, and
    quietly does nothing - which for somebody who cannot see the screen is
    indistinguishable from a reader that has stopped working.
    """
    found = []
    if not isinstance(data, dict):
        return ['a module is an object, not %s' % type(data).__name__]
    for key in data:
        if key not in KEYS:
            found.append("there is no module key '%s'" % key)
    if not data.get('match'):
        found.append('a module with no match block is about no window')
    for key in (data.get('match') or {}):
        if key not in MATCH_KEYS:
            found.append("there is nothing to match called '%s'" % key)
    for section, allowed in RULE_KEYS.items():
        rules = data.get(section) or []
        if not isinstance(rules, list):
            found.append("'%s' is a list of rules" % section)
            continue
        for index, rule in enumerate(rules):
            if not isinstance(rule, dict):
                found.append('%s rule %d is not an object' % (section, index + 1))
                continue
            for key in rule:
                if key not in allowed:
                    found.append("%s rule %d: there is no '%s'"
                                 % (section, index + 1, key))
            for key in (rule.get('match') or {}):
                if key not in MATCH_KEYS:
                    found.append("%s rule %d: there is nothing to match "
                                 "called '%s'" % (section, index + 1, key))
    politeness = {'polite', 'assertive', 'off'}
    for index, rule in enumerate(data.get('live') or []):
        if isinstance(rule, dict) and rule.get('politeness') \
                and rule['politeness'] not in politeness:
            found.append("live rule %d: politeness is one of %s"
                         % (index + 1, ', '.join(sorted(politeness))))
    return found


IDENTIFIER = re.compile(r'^[A-Za-z0-9_.\- ]+$')
