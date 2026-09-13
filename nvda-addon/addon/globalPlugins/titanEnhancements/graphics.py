# -*- coding: utf-8 -*-
"""A picture is not "graphic", and a control is not "button".

Two complaints with one shape behind them.

**"Graphic".** A reader that lands on an image says the word "graphic" and,
where the program bothered to name it, the name. It does not say whether
this is a 16-pixel icon on a toolbar, a photograph filling the window, or an
animation that is still moving - and those are three different things to a
person deciding whether to look further. The size and the role say which,
and both are already known: no request, no picture, no AI.

**"Button".** A control's TYPE is not its description. A toolbar of eleven
unnamed buttons is eleven buttons, and the caption printed on each one is
right there in the pixels - unreachable to accessibility, trivial to READ.
That is what Titan's AI OCR is for, and this is where a reader asks it.

The division is deliberate and it is the same one the rest of this add-on
draws:

* **What can be known is said always, and costs nothing.** Icon, picture,
  animation, and the size for something large enough that its size is worth
  knowing.
* **What must be worked out is asked for.** Reading a control with AI sends
  a picture of part of the user's screen to their provider, so it happens
  when the user presses the key, or - with the switch on - once for a
  control that has NO name at all, whose answer is then remembered as a
  label and never asked again.

Needs Titan running for the AI half (Titan owns the provider and the key),
and needs no Titan at all for everything above it. Titan Access is not
involved in either.
"""

from . import compat
from . import i18n

_ = i18n.install(globals())

#: A picture no bigger than this on either side is an ICON: something
#: standing for a command or a state, rather than a thing to look at.
#: Windows' own large icon is 48 and its jumbo is 256; 64 keeps the ones
#: that behave like icons and lets a small photograph be a picture.
ICON_MAX = 64

#: Roles that are a picture of some kind at all.
PICTORIAL = frozenset({'GRAPHIC', 'ICON', 'ANIMATION', 'DIAGRAM', 'CHART'})

#: Window classes that draw something moving. A control that is animating
#: is worth telling apart from one that is not: "still working" and
#: "finished but showing a picture" look identical to a reader otherwise.
ANIMATED_CLASSES = frozenset({'SysAnimate32', 'msctls_progress32'})


def _text(value):
    return str(value or '').strip()


def _role(obj):
    return _text(getattr(getattr(obj, 'role', None), 'name', '')).upper()


def _size(obj):
    try:
        location = obj.location
    except Exception:                                # noqa: BLE001
        return 0, 0
    if not location:
        return 0, 0
    try:
        return int(location[2]), int(location[3])
    except (TypeError, ValueError, IndexError):
        return 0, 0


def is_pictorial(obj):
    return _role(obj) in PICTORIAL


def kind_of(obj):
    """'icon', 'picture', 'animation', 'chart' - or '' for anything else.

    Read off what is already known. The one judgement in it is the size,
    and it is a judgement about how the thing is USED: a small square image
    on a toolbar is a command, and a large one is content.
    """
    role = _role(obj)
    if role not in PICTORIAL:
        return ''
    if role == 'ANIMATION' or _text(getattr(obj, 'windowClassName', '')) \
            in ANIMATED_CLASSES:
        return 'animation'
    if role in ('DIAGRAM', 'CHART'):
        return 'chart'
    if role == 'ICON':
        return 'icon'
    width, height = _size(obj)
    if width and height and width <= ICON_MAX and height <= ICON_MAX:
        return 'icon'
    return 'picture'


def word(kind):
    return {
        # Translators: a small picture standing for a command or a state.
        'icon': _('icon'),
        # Translators: a picture that is content rather than a command.
        'picture': _('picture'),
        # Translators: a picture that is moving.
        'animation': _('animation'),
        # Translators: a graph or a diagram.
        'chart': _('chart'),
    }.get(kind, '')


def parts(obj):
    """``[(text, voice)]`` describing the picture, or ``[]``.

    The kind takes the place of the word "graphic" at the control-type
    tone, which is where a control's type is said everywhere else in this
    add-on; a stored label - typed by the user or read once by AI - takes
    the place of the missing name.
    """
    kind = kind_of(obj)
    if not kind:
        return []
    from . import elements
    from . import labels
    said = []
    name = _text(getattr(obj, 'name', ''))
    if not name:
        name = labels.get(obj)
    if not name:
        # **What Windows itself drew, named for nothing.** Most of the
        # icons on Windows are the shell's own - a folder, a printer, the
        # warning triangle - and they can be recognised by comparing the
        # picture, here, in about a millisecond, with nothing sent
        # anywhere and no key needed. A picture that is somebody's own
        # artwork lands near none of them and is left to the tier that
        # can describe anything.
        try:
            from . import iconNames
            ok, shows = iconNames.describe(obj)
            if ok:
                name = shows
        except Exception:                            # noqa: BLE001
            pass
    if name:
        said.append((name, elements.NAME_PITCH))
    said.append((word(kind), elements.ROLE_PITCH))
    return said


# --------------------------------------------------------------------------- #
# What the picture actually shows
# --------------------------------------------------------------------------- #
#: What is asked about a control that has no name. Deliberately narrow: a
#: caption or a symbol, in a few words. A model asked to "describe this"
#: answers with a paragraph about a photograph of a button, and a control
#: whose name is a paragraph is a control the reader talks over.
QUESTION = ('What does this control show? Answer with the caption printed '
            'on it, or a few words naming the symbol. No sentence, no '
            'description of the picture, at most six words.')

#: What is asked about a picture the user has pressed the key on. Here a
#: sentence IS the answer: they asked what the picture is.
QUESTION_PICTURE = ('Describe what this picture shows, in one sentence.')


def ai_available():
    """Whether the AI half can be reached at all. ``(yes, why not)``."""
    from .link import LINK
    if not LINK.connected():
        return False, _('Titan is not running, so there is nothing to read '
                        'the picture with.')
    return True, ''


#: What a READING looks like, as opposed to a refusal.
#:
#: `ocr_ask` does not answer a question with a sentence: it reads the whole
#: window with the question in mind, and hands back
#: `model.elements_as_lines` - the title, then the model's answer as the
#: SUMMARY, then a blank line and `[Region]` blocks. A refusal ("AI OCR is
#: switched off...", "No API key is configured...") is one paragraph with
#: none of that.
#:
#: Telling them apart by SHAPE and not by wording, which is the rule this
#: repository already paid for once: a refusal's words are written for the
#: user and a client that matched on them broke the moment the sentence was
#: in another language.
def looks_like_a_reading(text):
    return any(line.lstrip().startswith('[')
               for line in str(text or '').splitlines())


def answer_in(reading):
    """The model's answer to the question, out of a whole reading.

    The SUMMARY line - the second - because that is where
    `elements_as_lines` puts it and the first line is always the window's
    title (`read_screen` fills one in when the picture has none). Taking
    the first line is what a caller does when it has not read the other
    program's source, and here it would name every control after the
    window it sits in.
    """
    lines = [line.strip() for line in str(reading or '').splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ''
    if not looks_like_a_reading(reading):
        return ' '.join(lines)
    return lines[1] if len(lines) > 1 else ''


def read(obj, question='', timeout=30.0):
    """Ask Titan's AI OCR what this control shows. ``(ok, text)``.

    The control's OWN window handle is passed, so what is photographed is
    the control and not the window it is in - AI OCR has always taken an
    hwnd and uses it as the thing to capture.

    ``ok`` is False for a REFUSAL as well as for a failed call. Titan
    answers "AI OCR is switched off" as ordinary prose with the call
    reported as having worked, so a caller that trusted `ok` alone would
    take that sentence for what the control shows - and this one goes on to
    remember it as the control's name for ever.
    """
    ready, why = ai_available()
    if not ready:
        return False, why
    try:
        handle = int(getattr(obj, 'windowHandle', 0) or 0)
    except (TypeError, ValueError):
        handle = 0
    if not handle:
        return False, _('This control has no window of its own to read.')
    from .link import LINK
    # A picture sent to a provider and a model's answer back is not a
    # question about a window: twelve seconds is the bus's ordinary
    # patience and far too little for this one.
    ok, text = LINK.run_action('ocr', 'ask', timeout=timeout, hwnd=handle,
                               question=question or QUESTION)
    if not ok:
        return False, _text(text)
    said = _text(text)
    if not looks_like_a_reading(said):
        # A sentence, not a reading: Titan saying it will not, or cannot.
        return False, said
    return True, answer_in(said)


def label_locally(obj):
    """The caption printed ON this control, read by WINDOWS. ``(ok, text)``.

    **The free half, and the one an automatic feature may use.** Windows
    has a recogniser built in: it is local, private, costs nothing and
    answers in about a tenth of a second, where the AI is a picture of the
    user's screen sent to a provider and an answer that has been measured
    taking longer than the bus waits for it - "Titan did not answer within
    12s", in the log, from a control the reader chose to look at by
    itself.

    So this is what the automatic path asks, and the AI is what the user
    asks for by pressing a key. It reads only what is printed on the
    control, which for the thing this is for - a toolbar button with a
    word on it - is the whole answer.
    """
    from . import labels
    from . import localOcr
    # **What Windows drew is named before anything is read.** A stock
    # icon is recognised by comparison rather than recognised by a
    # recogniser: it is certain, instant, and costs nothing.
    try:
        from . import iconNames
        ok, shows = iconNames.describe(obj)
        if ok and shows:
            labels.put(obj, shows, source='icon')
            return True, shows
    except Exception:                                # noqa: BLE001
        pass
    # **Every refusal here names itself.** They were bare `''`s, and the
    # caller logs whatever comes back - so the log carried "Titan could
    # not work out a name:" with nothing after the colon, three times in
    # a row, which is the shape of message this add-on exists not to
    # produce. Each of these is a different thing to do about it.
    if not labels.needs_one(obj):
        return False, 'this control already has a name'
    stored = labels.get(obj)
    if stored:
        return True, stored
    ready, why = localOcr.available()
    if not ready:
        return False, why
    try:
        location = getattr(obj, 'location', None)
        left, top, width, height = (int(location[0]), int(location[1]),
                                    int(location[2]), int(location[3]))
    except Exception:                                # noqa: BLE001
        return False, _('This control has no place on the screen to read.')
    if width < 4 or height < 4:
        return False, ('it is %dx%d on the screen, which is too small to '
                       'have anything written on it' % (width, height))
    reading = localOcr.read(left, top, width, height)
    if reading is None:
        return False, _text(localOcr.report().get('why', ''))
    said = ' '.join(_text(word.get('text')) for line in reading.lines
                    for word in line).strip()
    first = said.strip(' .:-')
    if not first:
        return False, "Windows' recogniser read no words on it"
    if len(first) > labels.MAX_LENGTH:
        # A name is a name, not a paragraph - and a control whose reading
        # is a paragraph is one the recogniser found a whole panel in.
        return False, ('what was read is %d characters, which is a panel '
                       'rather than a name' % len(first))
    labels.put(obj, first, source='ai')
    return True, first


def label_with_ai(obj):
    """Read an unnamed control once, and remember what it said.

    Once is the whole point. A toolbar the user passes over fifty times a
    day must cost one request in its life, not fifty - so the answer goes
    into :mod:`labels` against the control's own identity, and every
    later focus reads it from there with nothing sent anywhere.
    """
    from . import labels
    if not labels.needs_one(obj):
        return False, ''
    stored = labels.get(obj)
    if stored:
        return True, stored
    ok, text = read(obj)
    if not ok or not text:
        return False, text
    first = text.strip().splitlines()[0].strip(' .:-')
    if not first or len(first) > labels.MAX_LENGTH:
        # A name is a name, not a paragraph. Something long is the model
        # describing the picture rather than reading the caption off it,
        # and a control whose name is a paragraph is one the reader talks
        # over on every arrow key.
        return False, ''
    labels.put(obj, first, source='ai')
    return True, first
