# -*- coding: utf-8 -*-
"""The speech schemes, walked and EDITED with the arrows and Enter.

The other pages of the walked manager are for seeing what is there, and
the form is where things are edited. A scheme is different: every one of
its rules is a switch, a choice or a word, and all three can be walked - a
row that toggles when Enter is pressed and says its new state, a row that
opens the answers as another level, a row that asks for one line. So this
is a manager of its own, on the same palette everything else is on, and
the form (`classManager`'s "Speech schemes" page) is a row on it for
whoever prefers a form.

Levels: the schemes -> one scheme's kinds -> one kind's rule. Escape goes
back one level, and a change never closes the list: somebody changing one
part of a rule is nearly always changing the next one too.
"""

import threading

from . import i18n
from . import speechSchemes as schemes

_ = i18n.install(globals())

_LOCK = threading.RLock()
_counted = {'opened': 0, 'changed': 0}
_where = {'scheme': None, 'kind': None}


def report():
    with _LOCK:
        return dict(_counted)


def _on_off(on):
    # Translators: the state of a switch in a walked list.
    return _('on') if on else _('off')


def _kind_label(kind):
    return schemes.kind_names().get(kind, kind)


def _class_label(tag):
    try:
        from . import classes
        return classes.label_of(tag)
    except Exception:                                # noqa: BLE001
        return str(tag)


def _class_choices():
    try:
        from . import classes
        rows = [(row['id'], row['label']) for row in classes.described()
                if row['id'] not in getattr(classes, 'WHOLE', ())]
        if rows:
            return rows
    except Exception:                                # noqa: BLE001
        pass
    return [(tag, tag) for tag in ('name', 'kind', 'state', 'value',
                                   'description', 'place', 'detail',
                                   'context', 'disabled', 'alert')]


# --------------------------------------------------------------------------- #
# Level one: the schemes
# --------------------------------------------------------------------------- #
def open_it(at=0, back=None):
    """The schemes. ``(ok, said)``."""
    from . import palette
    rows = []
    now = schemes.active()
    for row in schemes.described():
        label = row['label']
        if row['active']:
            # Translators: marks the speech scheme in force.
            label = '%s (%s)' % (label, _('in use'))
        if row['changed'] and row['shipped']:
            # Translators: marks a shipped scheme the user has changed.
            label = '%s, %s' % (label, _('changed'))
        rows.append({'label': label,
                     # Translators: what a row of the scheme list is.
                     'role': _('scheme'),
                     'icon': 'open-object',
                     'run': (lambda key=row['id']: open_scheme(key))})
    # Translators: a row of the scheme list.
    rows.append({'label': _('New scheme, a copy of the one in use'),
                 'role': '', 'icon': 'new-object',
                 'run': (lambda: _new_scheme(now))})
    # Translators: a row of the scheme list.
    rows.append({'label': _('Next scheme'), 'role': '',
                 'run': _next_scheme})
    # Translators: a row that opens the real dialog.
    rows.append({'label': _('Open as a form'), 'role': '',
                 'run': _as_a_form})
    with _LOCK:
        _counted['opened'] += 1
        _where['scheme'] = None
        _where['kind'] = None
    # Translators: the title of the walked speech schemes.
    return palette.show(rows, _('Speech schemes'), back=back, at=at)


def _next_scheme():
    key, label = schemes.cycle(1)
    _changed()
    # Translators: said when the speech scheme changes. {name} is its name.
    return _reopen(open_it, _('Scheme: {name}').format(name=label))


def _new_scheme(copy_of):
    from . import dialogs

    def answer(text):
        key = schemes.create(text, copy_of=copy_of)
        if not key:
            # Translators: said when a scheme could not be made.
            _say(_('That name cannot be used, or is in use already.'))
            open_it()
            return
        _changed()
        open_scheme(key)

    # Translators: asks for the name of a new speech scheme.
    dialogs.ask_text(_('The name of the new scheme'), _('Speech schemes'),
                     on_answer=answer, on_cancel=open_it)
    return True, ''


def _as_a_form():
    from . import palette
    palette.stop()
    try:
        from . import classManager
        if classManager.show(page='schemes'):
            return True, ''
    except Exception:                                # noqa: BLE001
        pass
    # Translators: said when the form cannot be opened.
    return False, _('The speech schemes need NVDA\'s own interface.')


# --------------------------------------------------------------------------- #
# Level two: one scheme
# --------------------------------------------------------------------------- #
def open_scheme(key, at=0):
    from . import palette
    if key not in schemes.all_schemes():
        return open_it()
    rows = []
    label = schemes.label_of(key)
    in_use = schemes.active() == key
    rows.append({
        # Translators: a row of one speech scheme.
        'label': _('In use') if in_use else _('Use this scheme'),
        'role': '', 'icon': 'select-object',
        'run': (lambda: _use(key))})
    # The pause between the parts - shortened or lengthened here, which is
    # what makes one scheme read briskly and another deliberately.
    rows.append({
        # Translators: a row of a scheme: the pause between the parts.
        'label': _('Pause between parts: {ms} ms').format(
            ms=schemes.active_pause() if schemes.active() == key
            else _scheme_pause(key)),
        'role': '', 'icon': 'edit-object',
        'run': (lambda: _cycle_pause(key))})
    # The earcon KIT the whole scheme uses, switched here.
    rows.append({
        # Translators: a row of a scheme: its earcon kit.
        'label': _('Earcon kit: {kit}').format(kit=_kit_label(
            schemes.scheme_earcons(key))),
        'role': '', 'icon': 'open-object',
        'run': (lambda: _cycle_earcons(key))})
    # Sound and speech, speech only, or sound only.
    rows.append({
        # Translators: a row of a scheme: what it uses to announce.
        'label': _('Announce with: {what}').format(
            what=_output_label(schemes.scheme_output(key))),
        'role': '', 'icon': 'open-object',
        'run': (lambda: _cycle_output(key))})
    for kind in schemes.KIND_KEYS:
        rows.append({'label': '%s: %s' % (_kind_label(kind),
                                          schemes.rule_sentence(kind, key)),
                     # Translators: what a row of a scheme is.
                     'role': _('kind of control'),
                     'icon': 'open-object',
                     'run': (lambda one=kind: open_kind(key, one))})
    if schemes.is_shipped(key):
        if schemes.is_changed(key):
            # Translators: a row of a shipped scheme the user changed.
            rows.append({'label': _('Put it back as shipped'), 'role': '',
                         'run': (lambda: _delete(key))})
    else:
        # Translators: a row of the user's own scheme.
        rows.append({'label': _('Rename'), 'role': '',
                     'run': (lambda: _rename(key))})
        # Translators: a row of the user's own scheme.
        rows.append({'label': _('Delete this scheme'), 'role': '',
                     'run': (lambda: _delete(key))})
    with _LOCK:
        _where['scheme'] = key
        _where['kind'] = None
    return palette.show(rows, label, back=open_it, at=at)


#: The pause values the row steps through, shortest to longest.
_PAUSES = (0, 30, 60, 90, 130, 200, 350)


def _scheme_pause(key):
    scheme = schemes.all_schemes().get(key) or {}
    try:
        return int((scheme.get('default') or {}).get('pause') or 0)
    except (TypeError, ValueError):
        return 0


def _cycle_pause(key):
    now = _scheme_pause(key)
    nxt = next((p for p in _PAUSES if p > now), _PAUSES[0])
    schemes.set_pause(key, nxt)
    _changed()
    at = 1  # the pause row
    ok, _first = open_scheme(key, at=at)
    # Translators: said when the pause changes. {ms} is the milliseconds.
    return ok, _('Pause: {ms} ms').format(ms=nxt)


def _kit_label(kit):
    for value, label in schemes.earcon_kit_choices():
        if value == kit:
            return label
    return kit or _('the reader\'s own')


def _output_label(mode):
    return {
        # Translators: the sound-and-speech option.
        'both': _('sound and speech'),
        # Translators: the speech-only option.
        'speech': _('speech only'),
        # Translators: the sound-only option.
        'sound': _('sound only'),
    }.get(mode, mode)


def _cycle_earcons(key):
    kits = [v for v, _l in schemes.earcon_kit_choices()]
    now = schemes.scheme_earcons(key)
    nxt = kits[(kits.index(now) + 1) % len(kits)] if now in kits else kits[0]
    schemes.set_earcons(key, nxt)
    _changed()
    ok, _first = open_scheme(key, at=2)
    return ok, _('Earcon kit: {kit}').format(kit=_kit_label(nxt))


def _cycle_output(key):
    order = ['both', 'speech', 'sound']
    now = schemes.scheme_output(key)
    nxt = order[(order.index(now) + 1) % len(order)] if now in order \
        else 'both'
    schemes.set_output(key, nxt)
    _changed()
    ok, _first = open_scheme(key, at=3)
    return ok, _('Announce with: {what}').format(what=_output_label(nxt))


def _use(key):
    schemes.use(key)
    _changed()
    return _reopen(lambda: open_scheme(key),
                   _('Scheme: {name}').format(name=schemes.label_of(key)))


def _rename(key):
    from . import dialogs

    def answer(text):
        if schemes.rename(key, text):
            _changed()
        open_scheme(key)

    dialogs.ask_text(_('The new name of the scheme'), schemes.label_of(key),
                     on_answer=answer, default=schemes.label_of(key),
                     on_cancel=lambda: open_scheme(key))
    return True, ''


def _delete(key):
    shipped = schemes.is_shipped(key)
    schemes.delete(key)
    _changed()
    if shipped:
        # Translators: said when a shipped scheme is put back.
        return _reopen(lambda: open_scheme(key), _('Put back as shipped'))
    # Translators: said when a scheme is deleted.
    return _reopen(open_it, _('Deleted'))


# --------------------------------------------------------------------------- #
# Level three: one kind's rule
# --------------------------------------------------------------------------- #
def _part_rows(key, kind):
    words = schemes.part_names()
    parts = schemes.parts_for(kind, key)
    rows = []
    for part in schemes.PARTS:
        on = part in parts
        rows.append({'label': '%s: %s' % (words.get(part, part), _on_off(on)),
                     # Translators: what a part row of a rule is.
                     'role': _('switch'),
                     'icon': 'on' if on else 'off',
                     'part': part,
                     'run': (lambda one=part: _toggle_part(key, kind, one))})
    return rows


def open_kind(key, kind, at=0):
    from . import palette
    rows = []
    # Translators: a row of a kind's rule: the order the parts are said in.
    rows.append({'label': _('Order of the parts: {order}').format(
        order=', '.join(schemes.short_part_names().get(one, one)
                        for one in schemes.parts_for(kind, key))),
        'role': '', 'icon': 'open-object',
        'run': (lambda: open_order(key, kind))})
    rows.extend(_part_rows(key, kind))
    word = schemes.kind_word_for(kind, key)
    rows.append({
        # Translators: a row of a kind's rule: the word said for its type.
        'label': _('Type word: {word}').format(
            # Translators: the reader's own word for a control type.
            word=word or _('the reader\'s own')),
        'role': '', 'icon': 'edit-object',
        'run': (lambda: _ask_kind_word(key, kind))})
    rule = schemes.rule_for(kind, key)
    rows.append({
        # Translators: a row of a kind's rule: its sound.
        'label': _('Sound: {sound}').format(
            sound=schemes.sound_label(rule.get('sound'))),
        'role': '', 'icon': 'open-object',
        'run': (lambda: open_sound(key, kind))})
    rows.append({
        # Translators: a row of a kind's rule.
        'label': _('The sound stands for the type word: {state}').format(
            state=_on_off(bool(rule.get('sound_only')))),
        'role': _('switch'),
        'run': (lambda: _toggle_sound_only(key, kind))})
    for part in schemes.parts_for(kind, key):
        rows.append({
            # Translators: a row of a kind's rule: the voice of one part.
            'label': _('Voice of the {part}: {voice}').format(
                part=schemes.short_part_names().get(part, part),
                voice=_class_label(schemes.voice_for(kind, part, key))),
            'role': '', 'icon': 'open-object',
            'run': (lambda one=part: open_voice(key, kind, one))})
    braille = schemes.braille_for(kind, key)
    abbreviation = braille.get('kind')
    rows.append({
        # Translators: a row of a kind's rule: braille.
        'label': _('In braille, the type is shown as: {word}').format(
            word=(_('the reader\'s own') if abbreviation is None
                  # Translators: the type is not shown in braille.
                  else (abbreviation or _('nothing')))),
        'role': '', 'icon': 'edit-object',
        'run': (lambda: _ask_braille_kind(key, kind))})
    for part in schemes.PARTS:
        on = part in braille['parts']
        rows.append({
            # Translators: a row of a kind's rule: a part shown in braille.
            'label': _('In braille, the {part}: {state}').format(
                part=schemes.short_part_names().get(part, part),
                state=_on_off(on)),
            'role': _('switch'), 'icon': 'on' if on else 'off',
            'run': (lambda one=part: _toggle_braille_part(key, kind, one))})
    # Translators: a row of a kind's rule.
    rows.append({'label': _('Put this kind back to the scheme\'s default'),
                 'role': '',
                 'run': (lambda: _reset_kind(key, kind))})
    with _LOCK:
        _where['scheme'] = key
        _where['kind'] = kind
    return palette.show(rows, '%s - %s' % (schemes.label_of(key),
                                           _kind_label(kind)),
                        back=lambda: open_scheme(key), at=at)


def _toggle_part(key, kind, part):
    on = schemes.toggle_part(key, kind, part)
    _changed()
    return _relabel_kind(key, kind, '%s: %s' % (
        schemes.part_names().get(part, part), _on_off(on)))


def _toggle_sound_only(key, kind):
    now = not schemes.rule_for(kind, key).get('sound_only')
    schemes.set_rule(key, kind, sound_only=now)
    _changed()
    return _relabel_kind(key, kind, _on_off(now))


def _toggle_braille_part(key, kind, part):
    braille = schemes.braille_for(kind, key)
    parts = list(braille['parts'])
    if part in parts:
        parts.remove(part)
        on = False
    else:
        parts.append(part)
        parts.sort(key=lambda one: schemes.PARTS.index(one))
        on = True
    kept = dict(schemes.rule_for(kind, key).get('braille') or {})
    kept['parts'] = parts
    schemes.set_rule(key, kind, braille=kept)
    _changed()
    return _relabel_kind(key, kind, _on_off(on))


def _reset_kind(key, kind):
    for field in schemes.RULE_FIELDS:
        schemes.set_rule(key, kind, **{field: None})
    _changed()
    # Translators: said when a kind's rule is put back.
    return _reopen(lambda: open_kind(key, kind), _('Put back'))


def _ask_kind_word(key, kind):
    from . import dialogs

    def answer(text):
        schemes.set_rule(key, kind, kind_word=(str(text).strip() or None))
        _changed()
        open_kind(key, kind)

    # Translators: asks what to call a kind of control.
    dialogs.ask_text(_('What to say for the type - empty for the reader\'s '
                       'own word'), _kind_label(kind), on_answer=answer,
                     default=schemes.kind_word_for(kind, key),
                     on_cancel=lambda: open_kind(key, kind))
    return True, ''


def _ask_braille_kind(key, kind):
    from . import dialogs

    def answer(text):
        kept = dict(schemes.rule_for(kind, key).get('braille') or {})
        kept['kind'] = str(text).strip()
        schemes.set_rule(key, kind, braille=kept)
        _changed()
        open_kind(key, kind)

    braille = schemes.braille_for(kind, key)
    # Translators: asks how a control type is shown in braille.
    dialogs.ask_text(_('The type in braille, such as "btn" - empty to show '
                       'nothing'), _kind_label(kind), on_answer=answer,
                     default=braille.get('kind') or '',
                     on_cancel=lambda: open_kind(key, kind))
    return True, ''


# --------------------------------------------------------------------------- #
# The choosers: the order, a sound, a voice
# --------------------------------------------------------------------------- #
def open_order(key, kind, at=0):
    """The parts in order; Enter on one moves it UP, which is enough to
    make any order - the last one pressed rises to the top."""
    from . import palette
    words = schemes.part_names()
    rows = []
    for part in schemes.parts_for(kind, key):
        rows.append({'label': words.get(part, part),
                     # Translators: what a row of the order list is.
                     'role': _('part'), 'icon': 'item',
                     'run': (lambda one=part: _move_up(key, kind, one))})
    # Translators: text explaining the order list.
    return palette.show(rows, _('Enter moves a part up'),
                        back=lambda: open_kind(key, kind), at=at)


def _move_up(key, kind, part):
    parts = schemes.parts_for(kind, key)
    at = parts.index(part) if part in parts else 0
    if at == 0:
        # Translators: said when a part is already first.
        return True, _('Already first')
    schemes.move_part(key, kind, part, -1)
    _changed()
    return open_order(key, kind, at=at - 1)


def open_sound(key, kind, at=0):
    from . import palette
    now = str(schemes.rule_for(kind, key).get('sound') or '')
    rows = []
    for index, (value, label) in enumerate(schemes.sound_choices()):
        if value == now:
            at = index
            # Translators: marks the sound in force.
            label = '%s (%s)' % (label, _('now'))
        rows.append({'label': label, 'role': '', 'icon': 'item',
                     'run': (lambda one=value: _set_sound(key, kind, one))})
    # Translators: a row of the sound list: a file of the user's own.
    rows.append({'label': _('A sound file of your own...'), 'role': '',
                 'run': (lambda: _ask_sound_file(key, kind))})
    # Translators: the title of the sound list.
    return palette.show(rows, _('Sound'),
                        back=lambda: open_kind(key, kind), at=at)


def _set_sound(key, kind, value):
    schemes.set_rule(key, kind, sound=(value or None))
    _changed()
    try:
        if value:
            schemes.sounded(kind) if schemes.active() == key else None
    except Exception:                                # noqa: BLE001
        pass
    return open_kind(key, kind)


def _ask_sound_file(key, kind):
    from . import dialogs

    def answer(text):
        where = str(text or '').strip().strip('"')
        if where:
            schemes.set_rule(key, kind, sound=where)
            _changed()
        open_kind(key, kind)

    # Translators: asks for the path of a sound file.
    dialogs.ask_text(_('The path of the sound file (.wav or .ogg)'),
                     _kind_label(kind), on_answer=answer,
                     on_cancel=lambda: open_sound(key, kind))
    return True, ''


def open_voice(key, kind, part, at=0):
    from . import palette
    now = schemes.voice_for(kind, part, key)
    rows = []
    for index, (tag, label) in enumerate(_class_choices()):
        if tag == now:
            at = index
            label = '%s (%s)' % (label, _('now'))
        rows.append({'label': label, 'role': '', 'icon': 'item',
                     'run': (lambda one=tag: _set_voice(key, kind, part,
                                                        one))})
    return palette.show(rows, _('Voice of the {part}').format(
        part=schemes.short_part_names().get(part, part)),
        back=lambda: open_kind(key, kind), at=at)


def _set_voice(key, kind, part, tag):
    voices = dict(schemes.rule_for(kind, key).get('voices') or {})
    if tag == schemes.PART_VOICE.get(part):
        voices.pop(part, None)
    else:
        voices[part] = tag
    schemes.set_rule(key, kind, voices=(voices or None))
    _changed()
    return open_kind(key, kind)


# --------------------------------------------------------------------------- #
# Plumbing
# --------------------------------------------------------------------------- #
def _changed():
    with _LOCK:
        _counted['changed'] += 1


def _say(text):
    try:
        from . import compat
        compat.ui.message(str(text))
    except Exception:                                # noqa: BLE001
        pass


def _reopen(opener, said):
    """Open a level again, then say what happened in front of its row.

    `palette.show` reads the title and the first row by itself; the
    sentence is said after it, in one utterance with the row, so what the
    user hears is the news and then where they are.
    """
    from . import palette
    ok, _first = opener()
    if not ok:
        return ok, said
    if said:
        palette.say_here(beep=False, prefix=[(said, 'notification')])
    return True, ''


def _relabel_kind(key, kind, said):
    """Put the kind's rows back with the cursor where it was, and say the
    row - which now carries its new state - and nothing else. Putting the
    level up again would read the title on top of the answer."""
    from . import palette
    with palette._LOCK:
        at = palette._state['at']
        on = palette._state['on']
    if not on:
        return open_kind(key, kind, at=at)
    ok, _first = open_kind(key, kind, at=at)
    return ok, ''
