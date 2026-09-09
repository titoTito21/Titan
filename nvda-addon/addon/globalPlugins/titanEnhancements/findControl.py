# -*- coding: utf-8 -*-
"""Find the control that DOES a thing, not the one whose label you guessed.

Every screen reader can move you to the next button. None of them can answer
"where is the thing that saves this?" - and that is the question people
actually have in a program they do not know. The reader's own answers are
first-letter navigation (which needs the word), a control list (which needs
you to read all of it) and object navigation (which needs you to know where
it is). All three assume you already know what the control is called.

Three tiers, cheapest first, and each is complete on its own:

* **The words.** Every control's name, value and description, matched on
  substring and then on the words in any order. Free, instant, and it is
  the right answer far more often than a search that goes straight to a
  model would admit.
* **The screen.** When the window exposes nothing - a drawn menu, a custom
  installer - Windows' own recogniser (:mod:`localOcr`) gives the words and
  where they are, and those become searchable rows like any other. Still
  local, still free.
* **The meaning.** Only when the first two find nothing and only when the
  user says so: the control names are handed to Titan's AI with the
  question, and it says which one. "Where do I turn off notifications" over
  a list of forty labels is a question a model answers well and a substring
  match cannot answer at all.

**It never guesses in silence.** A match says which tier found it, so
"Save, by its name" and "Preferences, by what it does" are different
answers and the user knows which they got. Going to one is the same as a
place marker: the keyboard where the control takes it, the review cursor
where it does not.
"""

from . import i18n

_ = i18n.install(globals())

#: How many controls are looked at. A browser's tree is unbounded and a
#: reader that walks all of it has stopped answering; this is the top of the
#: window, which is where its own controls are.
MAX_SEEN = 800

#: How many matches are offered. Past this the list is not something anybody
#: picks anything out of.
MAX_HITS = 40

#: What tier found a match.
BY_WORDS = 'words'
BY_SCREEN = 'screen'
BY_MEANING = 'meaning'


def _text(value):
    return str(value or '').strip()


def tier_names():
    return {
        # Translators: how a control was found - by its own words.
        BY_WORDS: _('by its name'),
        # Translators: how a control was found - read off the screen.
        BY_SCREEN: _('read off the screen'),
        # Translators: how a control was found - by what it does.
        BY_MEANING: _('by what it does'),
    }


# --------------------------------------------------------------------------- #
# Tier one: the words
# --------------------------------------------------------------------------- #
def controls(window=None):
    """``[{'label', 'obj', 'words'}]`` - what is in this window."""
    if window is None:
        try:
            import api
            window = api.getForegroundObject()
        except Exception:                            # noqa: BLE001
            return []
    if window is None:
        return []
    from . import windowsAndActions as wa
    found, seen, queue = [], 0, [window]
    while queue and seen < MAX_SEEN:
        obj = queue.pop(0)
        seen += 1
        try:
            queue.extend(list(obj.children or []))
        except Exception:                            # noqa: BLE001
            pass
        name = _text(getattr(obj, 'name', ''))
        value = _text(getattr(obj, 'value', ''))
        description = _text(getattr(obj, 'description', ''))
        if not name and not value:
            continue
        role = wa._role_said(obj)
        label = ', '.join(part for part in (name or value, role) if part)
        found.append({'label': label, 'obj': obj,
                      'words': ' '.join((name, value, description)).lower()})
    return found


def by_words(question, rows=None):
    """Matches on the words. Whole phrase first, then the words in any
    order - because "save file" should find "Save the file as..." and a
    substring match alone will not."""
    needle = _text(question).lower()
    if not needle:
        return []
    rows = controls() if rows is None else rows
    exact = [row for row in rows if needle in row['words']]
    if exact:
        return exact[:MAX_HITS]
    parts = [word for word in needle.split() if word]
    if not parts:
        return []
    return [row for row in rows
            if all(word in row['words'] for word in parts)][:MAX_HITS]


# --------------------------------------------------------------------------- #
# Tier two: the screen
# --------------------------------------------------------------------------- #
def by_screen(question, hwnd=0):
    """Matches read off the window with Windows' own recogniser.

    For a window that exposes nothing at all. Local, free, and the rows
    carry real screen rectangles, so what is found can be pressed.
    """
    needle = _text(question).lower()
    if not needle:
        return []
    try:
        from . import localOcr
        if not hwnd:
            import api
            hwnd = int(getattr(api.getForegroundObject(), 'windowHandle', 0)
                       or 0)
        reading = localOcr.read_window(hwnd) if hwnd else None
    except Exception:                                # noqa: BLE001
        return []
    if not reading:
        return []
    parts = [word for word in needle.split() if word]
    out = []
    for text, rect in reading.rows():
        low = text.lower()
        if needle in low or (parts and all(word in low for word in parts)):
            out.append({'label': text, 'obj': None, 'rect': rect,
                        'words': low})
    return out[:MAX_HITS]


# --------------------------------------------------------------------------- #
# Tier three: the meaning
# --------------------------------------------------------------------------- #
def by_meaning(question, rows=None):
    """Ask Titan's AI which of these controls the question is about.

    Only reached when the words found nothing, and only when the user asked
    for it: this sends the control NAMES of the window - not a picture, not
    its contents - to their AI provider, which is a small thing to send and
    still a thing to be asked about.

    ``(rows, sentence)``. An empty list with a sentence is the honest
    answer for every reason it can fail.
    """
    rows = controls() if rows is None else rows
    if not rows:
        # Translators: said when there is nothing to search.
        return [], _('There is nothing in this window to search')
    from .link import LINK
    if not LINK.connected():
        # Translators: said when Titan is needed and is not running.
        return [], _('Titan is not running, so it cannot be searched by '
                     'what things do')
    listed = '\n'.join('%d. %s' % (at + 1, row['label'])
                       for at, row in enumerate(rows[:120]))
    asked = (
        'These are the controls of a window a blind user is in. Which of '
        'them is the user asking for? Answer with the NUMBERS only, most '
        'likely first, at most three, separated by commas. Answer with '
        'nothing at all if none of them is it.\n\n'
        'The user asks: %s\n\nThe controls:\n%s' % (_text(question), listed))
    ok, said = LINK.run_action('ai', 'ask', question=asked)
    if not ok:
        return [], _text(said)
    picked = []
    for piece in _text(said).replace('.', ',').split(','):
        piece = piece.strip()
        if not piece.isdigit():
            continue
        at = int(piece) - 1
        if 0 <= at < len(rows) and rows[at] not in picked:
            picked.append(rows[at])
    if not picked:
        # Translators: said when the AI could not pick a control.
        return [], _('It could not say which one')
    return picked, ''


# --------------------------------------------------------------------------- #
# The search itself
# --------------------------------------------------------------------------- #
def find(question, use_ai=False):
    """``(tier, rows, sentence)`` - the cheapest tier that found anything."""
    rows = controls()
    hits = by_words(question, rows)
    if hits:
        return BY_WORDS, hits, ''
    hits = by_screen(question)
    if hits:
        return BY_SCREEN, hits, ''
    if not use_ai:
        # Translators: said when a search found nothing without the AI.
        return '', [], _('Nothing here is called that. Ask again with the '
                         'AI to search by what things do.')
    hits, why = by_meaning(question, rows)
    if hits:
        return BY_MEANING, hits, ''
    # Translators: said when a search found nothing at all.
    return '', [], why or _('Nothing here matches that')


def go(row):
    """Go to a match. ``(ok, sentence)``.

    The keyboard where the control takes it, the review cursor where it does
    not, and a click where the match came off the screen and has no control
    behind it at all.
    """
    obj = (row or {}).get('obj')
    if obj is None:
        rect = (row or {}).get('rect')
        if not rect:
            # Translators: said when a match cannot be reached.
            return False, _('That cannot be reached')
        from . import smart
        return smart._click(rect, row.get('label') or '')
    try:
        obj.setFocus()
        return True, _text(row.get('label'))
    except Exception:                                # noqa: BLE001
        pass
    try:
        import api
        api.setNavigatorObject(obj)
        # Translators: said when the review cursor goes to a match.
        return True, _('{what}, review cursor').format(
            what=_text(row.get('label')))
    except Exception:                                # noqa: BLE001
        # Translators: said when a match cannot be reached.
        return False, _('That cannot be reached')
