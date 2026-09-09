

# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #
def _clean(profile):
    """One stored profile, with anything that is not a field thrown away."""
    out = {}
    for key, value in (profile or {}).items():
        name = str(key)
        if name in DIALS:
            amount = _clamp(value)
            if amount:
                out[name] = amount
        elif name in NAMES:
            word = str(value or '').strip()
            if word:
                out[name] = word
    return out


def _load():
    global _overrides, _order
    with _LOCK:
        if _overrides is not None:
            return _overrides
        _overrides = {}
        _order = None
        where = path()
        if where and os.path.isfile(where):
            try:
                with open(where, encoding='utf-8') as handle:
                    data = json.load(handle)
            except Exception:                        # noqa: BLE001
                data = None
            if isinstance(data, dict):
                # **Two shapes, because the first one shipped.** The file
                # used to be nothing but classes, so a key that is a class
                # is one; the reading order arrived later and lives under a
                # reserved name. Reading the old shape as the new one is
                # what would silently lose somebody's answers on upgrade.
                stored = data.get('classes')
                _order = data.get('order') if isinstance(
                    data.get('order'), dict) else None
                if not isinstance(stored, dict):
                    stored = {key: value for key, value in data.items()
                              if key not in ('classes', 'order')}
                for tag, profile in stored.items():
                    if isinstance(profile, dict):
                        _overrides[str(tag)] = _clean(profile)
        return _overrides


def forget():
    global _overrides, _order
    with _LOCK:
        _overrides = None
        _order = None
    try:
        from . import speaking
        speaking.forget()
    except Exception:                                # noqa: BLE001
        pass


def _clamp(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(-LIMIT, min(LIMIT, number))


def save():
    where = path()
    if not where:
        return False
    with _LOCK:
        data = {'classes': {tag: dict(profile)
                            for tag, profile in _load().items() if profile}}
        if _order:
            data['order'] = dict(_order)
    try:
        with open(where, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1,
                      sort_keys=True)
        return True
    except Exception:                                # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Reading and changing one
# --------------------------------------------------------------------------- #
def defaults():
    """Every class this add-on knows, with the voice it ships with."""
    from . import voices
    found = dict(voices.VOICES)
    for tag, profile in EXTRA.items():
        found.setdefault(tag, profile)
    return found


def voice_of(tag):
    """The profile in force for one class - the user's answer, or ours.

    This is what :func:`voices.voice_of` asks, so there is one answer to
    "what does a disabled control sound like" and the manager cannot drift
    away from what is really spoken.
    """
    name = str(tag or '')
    stored = _load().get(name)
    if stored is not None:
        return dict(stored)
    return dict(defaults().get(name, {}))


def is_whole(tag):
    """Whether this class is a whole utterance, so it may name a synth."""
    return str(tag or '') in WHOLE


def synth_of(tag):
    """The synthesizer a class asks for, or '' - and only where it may.

    A class that is part of a control's reading naming a synthesizer would
    be two programs producing one sentence, so the answer there is always
    '' whatever is stored: a table that can hold a wrong answer must not
    act on it.
    """
    if not is_whole(tag):
        return ''
    return str(voice_of(tag).get('synth') or '').strip()


def changed(tag):
    """Whether the user has an answer of their own for this class."""
    return str(tag or '') in _load()


def set_voice(tag, profile):
    """The user's own answer for one class."""
    name = str(tag or '')
    if not name:
        return False
    kept = _clean(profile)
    if not is_whole(name):
        kept.pop('synth', None)
    with _LOCK:
        _load()[name] = kept
    try:
        from . import speaking
        speaking.forget()
    except Exception:                                # noqa: BLE001
        pass
    return save()


def reset(tag=None):
    """Put one class back to the default, or all of them."""
    with _LOCK:
        store = _load()
        if tag is None:
            store.clear()
        else:
            store.pop(str(tag), None)
    return save()


def described():
    """Every class, for the manager and for the status command."""
    words = meanings()
    rows = []
    for _group, members in GROUPS:
        for tag in members:
            if tag not in defaults():
                continue
            rows.append({'id': tag,
                         'group': _group,
                         'meaning': words.get(tag, ''),
                         'whole': is_whole(tag),
                         'voice': voice_of(tag),
                         'default': dict(defaults().get(tag, {})),
                         'changed': changed(tag)})
    listed = {row['id'] for row in rows}
    for tag in sorted(defaults()):
        if tag not in listed:
            rows.append({'id': tag, 'group': group_of(tag),
                         'meaning': words.get(tag, ''),
                         'whole': is_whole(tag),
                         'voice': voice_of(tag),
                         'default': dict(defaults().get(tag, {})),
                         'changed': changed(tag)})
    return rows


# --------------------------------------------------------------------------- #
# The order the parts are read in
# --------------------------------------------------------------------------- #
def order():
    """``[(part, on)]`` - the parts of a control's reading, in order.

    Always every part, so the dialog has something to move and to untick,
    and so a part added by a later version of this add-on appears rather
    than being silently absent from somebody's stored answer.
    """
    _load()
    with _LOCK:
        stored = dict(_order or {})
    wanted = [str(name) for name in (stored.get('parts') or [])
              if str(name) in PARTS]
    for name in PARTS:
        if name not in wanted:
            wanted.append(name)
    off = {str(name) for name in (stored.get('off') or [])}
    return [(name, name not in off) for name in wanted]


def parts_read():
    """Just the parts that are on, in order. What the reader asks."""
    return [name for name, on in order() if on]


def set_order(rows):
    """``[(part, on)]`` from the dialog. Stored, and nothing else."""
    global _order
    _load()
    wanted, off = [], []
    for row in rows or []:
        try:
            name, on = str(row[0]), bool(row[1])
        except Exception:                            # noqa: BLE001
            continue
        if name not in PARTS or name in wanted:
            continue
        wanted.append(name)
        if not on:
            off.append(name)
    if not wanted:
        return False
    with _LOCK:
        _order = {'parts': wanted, 'off': off}
    return save()


def reset_order():
    global _order
    _load()
    with _LOCK:
        _order = None
    return save()


def order_changed():
    _load()
    with _LOCK:
        return bool(_order)


# --------------------------------------------------------------------------- #
# Hearing one
# --------------------------------------------------------------------------- #
#: What a class is tried on. Short, and the same for every class, so what
#: the listener is comparing is the voice and nothing else.
def sample_text(tag):
    words = meanings()
    # Translators: spoken when trying out a voice class. {what} is what the
    # class is for.
    return _('This is {what}').format(what=words.get(tag, tag))


def speak_sample(tag, profile=None):
    """Say the sample in this class's voice, right now.

    On the synthesizer the user really has, because that is the only thing
    that can answer whether a dial is audible - and on the one the class
    ASKS for when it asks for one, or the try button would be answering a
    question nobody asked.

    ``profile`` is what is on the dialog at this moment rather than what is
    stored, so a change is heard before it is kept, which is the whole
    point of the button.
    """
    from . import compat
    from . import voices
    wanted = dict(profile) if profile is not None else voice_of(tag)
    text = sample_text(tag)
    if is_whole(tag) and str(wanted.get('synth') or '').strip():
        try:
            from . import speaking
            if speaking.speak_with(wanted, text):
                return True
        except Exception:                            # noqa: BLE001
            pass
    speech = compat.speech
    if speech is None:
        return False
    sequence = voices.sequence([(text, wanted)])
    if not sequence:
        return False
    try:
        speech.speak(sequence)
        return True
    except Exception:                                # noqa: BLE001
        return False
