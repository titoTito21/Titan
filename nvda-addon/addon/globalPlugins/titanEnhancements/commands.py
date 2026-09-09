# -*- coding: utf-8 -*-
"""What the gestures actually do.

**Every one of these talks to Titan on a thread of its own.** A gesture
handler runs on NVDA's main thread, which is the thread that reads the
screen; a bus call made there would stop NVDA for as long as Titan took to
answer - and Titan may be asking a component, taking a picture of a window
or waiting for a model. So the shape is always the same: say something at
once so the user knows the key arrived, do the work on a worker, and come
back to the main thread to show the answer.
"""

import threading

from . import dialogs
from . import i18n
from .link import LINK

_ = i18n.install(globals())

#: A model takes longer than a component does, and the assistant is the one
#: call here that may reach one. Titan's own bridge timeout is for a call
#: that talks to the desktop; this is for a call that talks to a provider.
ASSISTANT_TIMEOUT = 90.0

#: Longer than this and the answer becomes a page with the reader's own
#: cursor on it rather than something said once.
READ_ALOUD_LIMIT = 240


def _work(function):
    """Run ``function`` off NVDA's main thread and never raise into wx."""
    def run():
        try:
            function()
        except Exception as error:                   # noqa: BLE001
            from . import compat
            if compat.log is not None:
                compat.log.error(f'Titan command failed: {error}')
            dialogs.report(_('That did not work: {error}')
                           .format(error=error))
    threading.Thread(target=run, name='TitanEnhancements', daemon=True).start()


def _refused(problem):
    dialogs.report(str(problem))


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #
def status():
    """Is Titan there, what can it send, and can the voice be moved."""
    from . import channel
    from . import focus
    from . import panner

    if not LINK.connected():
        # **Not the whole answer any more.** Most of what this add-on does
        # is now the reader's own - the modules, the context, the dialog
        # kinds, the labels, the classes, the touchpad - and none of it
        # needs Titan. Saying only "Titan is not running" would report a
        # dead add-on when almost all of it is working.
        dialogs.report(' '.join([_('Titan is not running.')]
                                + _local_lines()))
        return

    report = panner.PANNER.report()
    able = channel.CHANNEL.capabilities()
    lines = [
        _('Connected to Titan.'),
        _('Synthesizer: {name}').format(name=report['synth'] or _('unknown')),
    ]
    # **Which of the two layers can place the voice, not only the first
    # one.** eSpeak - NVDA's default - makes ONE channel, so the stream
    # layer cannot pan it and this said "the voice cannot be placed" on the
    # commonest setup there is, while `place()` was panning it perfectly
    # through NVDA's own audio session all along.
    if report['can_place']:
        from . import interject
        lines.append(_('The voice can be placed in the stereo image.')
                     if report['stream_panning'] else
                     _('The voice is placed through NVDA\'s own audio '
                       'session.'))
        lines.append(_('Controls placed where they are: {count}.')
                     .format(count=interject.placed()))
    else:
        lines.append(_('The voice cannot be placed; a tone marks the position '
                       'instead.'))
        if report['problem']:
            lines.append(report['problem'])
    if not panner.PANNER.enabled:
        lines.append(_('Positioned speech is switched off.'))
    lines.append(_('Pitch: {pitch}. Braille: {braille}.').format(
        pitch=_('yes') if able['pitch'] else _('no'),
        braille=_('yes') if able['braille'] else _('no')))
    if focus.standing_down():
        lines.append(_('Titan Access is the reader, so this add-on is silent.'))
    if getattr(LINK, 'needs_consent', False):
        lines.append(_('Titan has not been allowed to be controlled from '
                       'here yet, so its actions will refuse. Answer the '
                       'question Titan asked when NVDA connected, or allow '
                       'it in Titan\'s settings, General, under External '
                       'clients.'))
    lines.append(_('Focus reports replaced by Titan: {count}.')
                 .format(count=focus.suppressed()))
    # "It is not doing it" and "it is doing it and I cannot hear the
    # difference" are different problems, and only a count tells them apart.
    from . import elements
    if not focus.titan_coordinates():
        lines.append(_('This Titan announces through accessible_output3 '
                       'rather than through this add-on, so its controls '
                       'are read by NVDA as usual. Restart Titan to get the '
                       'three-tone reading.'))
    elif not elements.can_pitch():
        lines.append(_('This NVDA cannot change the pitch mid-sentence, so '
                       'controls are read in one tone.'))
    else:
        lines.append(_('Controls read in three tones: {count}.')
                     .format(count=focus.pitched()))
    from . import earcons
    if earcons.wanted():
        lines.append(_('Cursor sounds played: {count}.')
                     .format(count=earcons.played()))
    # Where the rest of Titan is: not in this add-on's own eight gestures
    # but in NVDA's Input Gestures dialog, which is the one place somebody
    # would look for a key to bind and the last place they would expect to
    # find another program's actions.
    from . import gestures
    count = gestures.installed()
    if count:
        lines.append(_('{count} Titan actions can be given a key in NVDA\'s '
                       'Input Gestures dialog, under Titan.')
                     .format(count=count))
    lines.extend(_local_lines())
    dialogs.report(' '.join(lines))


def _local_lines():
    """What the reader's own layers have done - with or without Titan.

    Every one of these is a count rather than a switch, for the reason the
    three-tone one was: "it is off" and "it is on and I cannot hear it"
    are different problems, and only a number tells them apart.
    """
    lines = []
    try:
        from . import readerModules
        rows = readerModules.describe()
        if rows:
            lines.append(_('Reader modules: {count}.').format(count=len(rows)))
        wrong = readerModules.problems()
        if wrong:
            lines.append(_('{count} module(s) were not loaded; press the '
                           'reader modules command to see why.')
                         .format(count=len(wrong)))
    except Exception:                                # noqa: BLE001
        pass
    try:
        from . import focus
        if focus.semantic() or focus.windows() or focus.pictures() \
                or focus.labelled():
            lines.append(_('Read as what they are: {app} in Titan\'s '
                           'applications, {other} elsewhere, {pictures} '
                           'pictures, {named} named by this add-on.')
                         .format(app=focus.semantic(), other=focus.windows(),
                                 pictures=focus.pictures(),
                                 named=focus.labelled()))
    except Exception:                                # noqa: BLE001
        pass
    try:
        from . import dialog_kind
        found = dialog_kind.report()
        if found['icon'] or found['buttons']:
            lines.append(_('Dialogs whose kind was told: {icon} by their '
                           'icon, {buttons} by their buttons.')
                         .format(icon=found['icon'],
                                 buttons=found['buttons']))
    except Exception:                                # noqa: BLE001
        pass
    try:
        from . import live
        found = live.report()
        if found['said'] or found['dropped']:
            lines.append(_('Live updates said: {said} ({dropped} dropped as '
                           'too fast or already said).')
                         .format(said=found['said'],
                                 dropped=found['dropped']))
    except Exception:                                # noqa: BLE001
        pass
    try:
        from . import states
        found = states.report()
        if found['said'] or found['attention']:
            lines.append(_('Said busy {busy} times; {attention} windows '
                           'asked for attention.')
                         .format(busy=found['said'],
                                 attention=found['attention']))
        if found['why']:
            lines.append(_('Attention is not being watched: {why}')
                         .format(why=found['why']))
    except Exception:                                # noqa: BLE001
        pass
    try:
        from . import labels
        kept = labels.count()
        if kept:
            lines.append(_('Names kept for controls: {count}.')
                         .format(count=kept))
    except Exception:                                # noqa: BLE001
        pass
    try:
        from . import surface
        found = surface.report()
        if found['watching']:
            lines.append(_('Watching a window as a picture: {reads} '
                           'readings, {changed} changes.')
                         .format(reads=found['reads'],
                                 changed=found['changed']))
    except Exception:                                # noqa: BLE001
        pass
    try:
        from . import trackpad
        found = trackpad.report()
        if found['on']:
            lines.append(_('The touchpad is a touch screen: {gestures} '
                           'gestures from {contacts} contacts.')
                         .format(gestures=found['gestures'],
                                 contacts=found['contacts']))
        elif found['why']:
            lines.append(_('The touchpad is not being read: {why}')
                         .format(why=found['why']))
    except Exception:                                # noqa: BLE001
        pass
    try:
        from . import semantics
        stopped = semantics.stood_down()
        if stopped:
            lines.append(stopped)
    except Exception:                                # noqa: BLE001
        pass
    return lines


# --------------------------------------------------------------------------- #
# Macros
# --------------------------------------------------------------------------- #
def macros():
    dialogs.report(_('Reading the macros.'))

    def read():
        ok, data = LINK.bridge('macros.list')
        if not ok:
            return _refused(data)
        rows = (data or {}).get('macros') or []
        if not rows:
            dialogs.report(_('There are no macros.'))
            return
        # The NAME is what Titan matches on and it is kept apart from
        # everything that is only there to be read - which is the whole
        # reason the bridge answers rows rather than a sentence.
        names = [str(row.get('name') or '') for row in rows]
        labels = []
        for row in rows:
            hotkey = str(row.get('hotkey') or '')
            labels.append(f"{row.get('name')} ({hotkey})" if hotkey
                          else str(row.get('name')))

        def chosen(index):
            if not 0 <= index < len(names):
                return
            _work(lambda: _run_macro(names[index]))
        dialogs.choose(labels, _('Titan macros'), _('Run which macro?'),
                       chosen)
    _work(read)


def _run_macro(name):
    ok, text = LINK.run_action('macros', 'run_macro', name=name)
    dialogs.report(text or (_('Done.') if ok else _('That did not work.')))


# --------------------------------------------------------------------------- #
# Any action of any add-on
# --------------------------------------------------------------------------- #
def actions():
    dialogs.report(_('Reading what Titan can do.'))

    def read():
        ok, data = LINK.bridge('addons.list')
        if not ok:
            return _refused(data)
        rows = (data or {}).get('addons') or []
        if not rows:
            dialogs.report(_('Titan offered nothing.'))
            return
        ids, labels = [], []
        for row in rows:
            if isinstance(row, dict):
                ids.append(str(row.get('id') or ''))
                labels.append(str(row.get('label') or row.get('id') or ''))
            else:
                ids.append(str(row))
                labels.append(str(row))

        def chosen(index):
            if 0 <= index < len(ids):
                _work(lambda: _actions_of(ids[index], labels[index]))
        dialogs.choose(labels, _('Titan'), _('Which part of Titan?'), chosen)
    _work(read)


def _actions_of(addon, label):
    ok, data = LINK.bridge('addons.actions', addon=addon)
    if not ok:
        return _refused(data)
    rows = (data or {}).get('actions') if isinstance(data, dict) else None
    rows = rows or []
    if not rows:
        dialogs.report(_('{label} offers nothing that can be run from here.')
                       .format(label=label))
        return
    names, labels = [], []
    for row in rows:
        if isinstance(row, dict):
            names.append(str(row.get('name') or ''))
            summary = str(row.get('summary') or '')
            labels.append(f"{row.get('name')} - {summary}" if summary
                          else str(row.get('name')))
        else:
            names.append(str(row))
            labels.append(str(row))

    def chosen(index):
        if 0 <= index < len(names):
            _work(lambda: _run(addon, names[index]))
    dialogs.choose(labels, label, _('Do what?'), chosen)


def _run(addon, action):
    ok, text = LINK.run_action(addon, action)
    dialogs.report(text or (_('Done.') if ok else _('That did not work.')))


# --------------------------------------------------------------------------- #
# AI OCR - a window nothing else can read
# --------------------------------------------------------------------------- #
def _foreground_window():
    """Whatever Windows says is in front. The floor under :func:`_here`.

    Asked only when NVDA could not say, which should not happen - but a
    command that answers "there is no window to read" while the user is
    plainly looking at one is the worst possible way to find out that it
    did.
    """
    try:
        import ctypes
        ctypes.windll.user32.GetForegroundWindow.restype = ctypes.c_void_p
        return int(ctypes.windll.user32.GetForegroundWindow() or 0)
    except Exception:                                # noqa: BLE001
        return 0


def _here():
    """The window NVDA is in, as arguments for a Titan action.

    Not "the foreground window": on a machine being read, those two differ
    constantly - a menu is up, a tooltip has the foreground, the user is in
    a dialog NVDA has followed them into. NVDA knows which window it is
    reading and Titan cannot work that out for itself, so it is told, and
    AI OCR reads the window the user is actually in.
    """
    from . import context
    where = context.window()
    hwnd = int(where.get('hwnd') or 0)
    # **Nothing rather than a guess.** An empty answer means NVDA could not
    # say which window, and Titan reads that as "whatever is in front" -
    # which is the right thing for a reading and the wrong thing to invent
    # here. A caller that needs a concrete handle asks for one itself.
    return {'hwnd': hwnd} if hwnd else {}


#: The last line of a reading is written for a MODEL - "Act on this with
#: ocr_press, ocr_type..." - and this shows the reading to a person. It is
#: not an error that it is there: the same action answers Titan's own agent,
#: which needs exactly that sentence. It is simply not for the reader.
_FOR_THE_MODEL = ('act on this with', 'ocr_press', 'ocr_read_window',
                  'use ocr_read_window')


def _for_a_person(text):
    """A reading with the sentence aimed at the model taken off the end."""
    lines = str(text or '').split('\n')
    while lines:
        last = lines[-1].strip().lower()
        if not last or any(mark in last for mark in _FOR_THE_MODEL):
            lines.pop()
            continue
        break
    return '\n'.join(lines).strip()


#: An answer shorter than this is a sentence - a refusal, "there is no key",
#: "AI OCR is switched off" - and putting a window up for one sentence is a
#: window to close afterwards. A reading is far longer than this.
_A_SENTENCE = 200


def _ocr_answer(ok, text, title=None):
    """Say what came back, as the kind of thing it is.

    **A refusal is not a reading.** Every one of these actions answers with
    prose whether it worked or not - "AI OCR is switched off. Turn it on in
    Settings", "the vision provider has no key" - and showing that in a
    page titled AI OCR reads as though the window had been read and had
    that in it. A sentence is said; a reading is a page with the reader's
    own cursor on it, which is what somebody wants from a screen that has
    just been read to them.
    """
    said = _for_a_person(text)
    if not said:
        dialogs.report(_('Nothing was read.'))
        return
    if not ok or len(said) <= _A_SENTENCE and '\n' not in said:
        dialogs.report(said)
        return
    dialogs.browse(said, title or _('AI OCR'))


def ocr_read():
    dialogs.report(_('Reading the window.'))

    def read():
        ok, text = LINK.run_action('ocr', 'read_window', scope='window',
                                   **_here())
        _ocr_answer(ok, text)
    _work(read)


def ocr_ask():
    def asked(question):
        if not str(question or '').strip():
            return
        dialogs.report(_('Asking.'))

        def read():
            ok, text = LINK.run_action('ocr', 'ask', question=question,
                                       scope='window', **_here())
            _ocr_answer(ok, text)
        _work(read)
    dialogs.ask_text(_('What would you like to know about this window?'),
                     _('AI OCR'), asked)


def ocr_again():
    """The last reading again, with no picture taken and nothing spent.

    A reading is a request to the user's own AI provider, and reading the
    same screen twice because the page was closed is paying for it twice.
    """
    def read():
        ok, text = LINK.run_action('ocr', 'last_reading')
        _ocr_answer(ok, text)
    _work(read)


def ocr_press():
    """Press something AI OCR read, by its name.

    The half of AI OCR that is not reading: on a window that exposes
    nothing, this is the only way to press anything in it at all. It is
    guarded on Titan's side - only into the window that was really read,
    only with the user's own "Let AI OCR press controls" left on.
    """
    def asked(name):
        if not str(name or '').strip():
            return
        dialogs.report(_('Pressing.'))

        def press():
            ok, text = LINK.run_action('ocr', 'press', name=name)
            _ocr_answer(ok, text)
        _work(press)
    dialogs.ask_text(_('Which control, as AI OCR read its name?'),
                     _('AI OCR'), asked)


def ocr_key():
    """Send a whole key to the window AI OCR read.

    Needs no coordinates, so it works even where the reading could not
    place a single control - which on a window that draws itself is the
    ordinary case.
    """
    def asked(key):
        if not str(key or '').strip():
            return

        def send():
            ok, text = LINK.run_action('ocr', 'send_key', key=key)
            _ocr_answer(ok, text)
        _work(send)
    dialogs.ask_text(_('Which key? For example escape, enter, down.'),
                     _('AI OCR'), asked)


def ocr_overlay():
    """Hand the window to Titan's own overlay - real controls over the real
    window, which is more than a reading can be."""
    dialogs.report(_('Opening the Titan overlay.'))

    def show():
        ok, text = LINK.run_action('ocr', 'show_overlay')
        if not ok or str(text or '').strip():
            _ocr_answer(ok, text)
    _work(show)


# --------------------------------------------------------------------------- #
# The assistant - Titan's AI, asked from wherever the user is
# --------------------------------------------------------------------------- #
def assistant(act=False):
    """Ask Titan's assistant a question and read the answer back.

    ``act`` is the difference between the two gestures and it is the whole
    difference between an assistant and an agent: asked, it answers out of
    what it knows about this desktop; told to act, it is allowed to RUN the
    actions its answer implies. Two gestures rather than one switch, because
    which of the two the user wants is decided per question, not once in a
    settings dialog.
    """
    if not LINK.connected():
        dialogs.report(_('Titan is not running.'))
        return

    def asked(question):
        if not str(question or '').strip():
            return
        dialogs.report(_('Asking Titan.') if not act
                       else _('Asking Titan to do it.'))

        def work():
            # What the user is looking at, in the question itself. Titan's
            # assistant is not the reader and has no other way to know that
            # "this button" is the Send button of a mail window - and
            # "what is this?" is the question somebody actually asks.
            asked_about = question
            try:
                from . import context
                where = context.sentence()
            except Exception:                        # noqa: BLE001
                where = ''
            if where:
                asked_about = '{}\n\n({})'.format(question, where)
            ok, data = LINK.bridge('ai.ask', timeout=ASSISTANT_TIMEOUT,
                                   question=asked_about, act=bool(act))
            if not ok:
                return _refused(data)
            answer = (data or {}).get('answer') if isinstance(data, dict) \
                else data
            answer = str(answer or '').strip()
            if not answer:
                dialogs.report(_('The assistant said nothing.'))
                return
            # A long answer goes into a page with the reader's own cursor on
            # it; a short one is just said, because putting a window up for
            # one sentence is a window to close afterwards.
            if len(answer) > READ_ALOUD_LIMIT or '\n' in answer:
                dialogs.browse(answer, _('Titan assistant'))
            else:
                dialogs.report(answer)
        _work(work)

    dialogs.ask_text(_('What would you like Titan to do?') if act
                     else _('What would you like to ask Titan?'),
                     _('Titan assistant'), asked)


#: What Titan really answers `ai.history` with, and it is not what this
#: read for its first year: `{"enabled": bool, "exchanges": [{"role",
#: "text", "source", "at"}]}` - one row per TURN, said by 'user' or by
#: 'assistant', not one row per question-and-answer pair. Reading a key
#: nothing writes is a working-looking empty list, so the conversation was
#: reported as "Nothing has been asked yet" however much of it there was.
#: The Elten bridge reads the same call and has always read it correctly,
#: which is what settled the spelling.
HISTORY_KEY = 'exchanges'


def assistant_history():
    """What has been asked and answered, as a page to read."""
    def read():
        ok, data = LINK.bridge('ai.history', limit=20)
        if not ok:
            return _refused(data)
        data = data if isinstance(data, dict) else {}
        rows = data.get(HISTORY_KEY) or data.get('history') or []
        if not rows:
            if data.get('enabled') is False:
                dialogs.report(_('Titan is not keeping the conversation. '
                                 'Switch it on in Titan\'s settings, AI '
                                 'features.'))
                return
            dialogs.report(_('Nothing has been asked yet.'))
            return
        lines = []
        for row in rows:
            if not isinstance(row, dict):
                lines.append(str(row))
                continue
            # A turn says WHOSE it is; the older question/answer spelling is
            # still read so a Titan that answers that way is not silent.
            text = str(row.get('text') or '').strip()
            if text:
                lines.append(_('Titan: {text}').format(text=text)
                             if str(row.get('role') or '') == 'assistant'
                             else _('You: {text}').format(text=text))
                continue
            asked = str(row.get('question') or row.get('user') or '')
            said = str(row.get('answer') or row.get('assistant') or '')
            if asked:
                lines.append(_('You: {text}').format(text=asked))
            if said:
                lines.append(_('Titan: {text}').format(text=said))
        if not lines:
            dialogs.report(_('Nothing has been asked yet.'))
            return
        dialogs.browse('\n\n'.join(lines), _('Titan assistant'))
    _work(read)


def assistant_forget():
    """Start again. Asked first, because it cannot be taken back."""
    def forget():
        def work():
            ok, data = LINK.bridge('ai.forget')
            said = (data or {}).get('said') if isinstance(data, dict) else None
            dialogs.report(str(said) if said
                           else (_('Forgotten.') if ok else str(data)))
        _work(work)
    dialogs.confirm(_('Forget the conversation with Titan\'s assistant?'),
                    _('Titan assistant'), forget)


# --------------------------------------------------------------------------- #
# The catalogue of everything else
# --------------------------------------------------------------------------- #
def refresh_actions(plugin):
    """Ask Titan what it can do now, so the Input Gestures dialog is current.

    Done by itself whenever Titan connects; this is the gesture for the case
    the user has just installed something and does not want to restart
    either program to bind a key to it.
    """
    from . import gestures
    if not LINK.connected():
        dialogs.report(_('Titan is not running.'))
        return
    dialogs.report(_('Reading what Titan can do.'))

    def done(count):
        dialogs.report(_('{count} Titan actions can be given a key in NVDA\'s '
                         'Input Gestures dialog, under Titan.')
                       .format(count=count))
    if not gestures.refresh(plugin, done):
        dialogs.report(_('Already reading.'))


# --------------------------------------------------------------------------- #
# Every other subsystem Titan has
#
# **The 475 actions are what Titan can DO; these are what it can be ASKED.**
# The action layer covers everything actionable and every one of those is
# already a script the user can bind - but a subsystem whose whole value is
# a LIST of what has happened is not something to run, it is something to
# read, and Titan answers each of them as a shape rather than as a sentence
# precisely so a client can render it. Nothing here is new machinery: it is
# the bridge calls that were already there and that this add-on was not
# asking.
#
# A subsystem that is not there answers plainly and costs nothing: a Titan
# with no Buffer System, no notification centre or no window says so.
# --------------------------------------------------------------------------- #
def _page(lines, title):
    """A list of lines as something to read, or a sentence when it is short."""
    lines = [str(line) for line in lines if str(line or '').strip()]
    if not lines:
        return False
    if len(lines) == 1:
        dialogs.report(lines[0])
        return True
    dialogs.browse('\n'.join(lines), title)
    return True


def notifications():
    """Titan's notification centre - everything that arrived while you were
    somewhere else.

    Newest first, which is the order the centre itself keeps them in and
    the order somebody catching up wants them.
    """
    def read():
        ok, data = LINK.bridge('notifications.list')
        if not ok:
            return _refused(data)
        rows = (data or {}).get('notifications') or []
        if not rows:
            dialogs.report(_('There are no notifications.'))
            return
        lines = []
        for row in rows:
            if not isinstance(row, dict):
                lines.append(str(row))
                continue
            when = ' '.join(part for part in (str(row.get('date') or ''),
                                              str(row.get('time') or ''))
                            if part)
            who = str(row.get('appname') or '')
            what = str(row.get('content') or '')
            head = ', '.join(part for part in (who, when) if part)
            lines.append('{}: {}'.format(head, what) if head else what)
        _page(lines, _('Titan notifications'))
    _work(read)


def buffers():
    """The Titan Buffer System: every message, call and notification that
    arrived while its window was closed.

    One of the things a Titan user reaches for constantly and that nothing
    outside Titan exposes at all.
    """
    dialogs.report(_('Reading the buffers.'))

    def read():
        ok, data = LINK.bridge('buffers.list')
        if not ok:
            return _refused(data)
        categories = (data or {}).get('categories') or []
        rows, labels = [], []
        for category in categories:
            if not isinstance(category, dict):
                continue
            for buffer in category.get('buffers') or []:
                if not isinstance(buffer, dict):
                    continue
                rows.append((category.get('id') or category.get('name') or '',
                             buffer.get('id') or buffer.get('name') or ''))
                labels.append('{}: {} ({})'.format(
                    category.get('name') or category.get('id') or '',
                    buffer.get('name') or buffer.get('id') or '',
                    buffer.get('count', 0)))
        if not rows:
            dialogs.report(_('There is nothing in the buffers.'))
            return

        def chosen(index):
            if 0 <= index < len(rows):
                _work(lambda: _read_buffer(*rows[index]))
        dialogs.choose(labels, _('Titan buffers'), _('Which buffer?'), chosen)
    _work(read)


def _read_buffer(category, buffer):
    ok, data = LINK.bridge('buffers.read', category=category, buffer=buffer,
                           limit=100)
    if not ok:
        return _refused(data)
    elements = (data or {}).get('elements') or []
    lines = []
    for element in elements:
        if not isinstance(element, dict):
            lines.append(str(element))
            continue
        author = str(element.get('author') or '')
        text = str(element.get('text') or '')
        lines.append('{}: {}'.format(author, text) if author else text)
    if not _page(lines, _('Titan buffers')):
        dialogs.report(_('There is nothing in that buffer.'))


def showing():
    """What Titan is showing right now - its views, its status bar and
    whether its window is even on the screen.

    Three calls rather than one because they are three different questions,
    and the answer to "why is Titan not saying anything" is usually the
    third: the window is in the tray.
    """
    dialogs.report(_('Asking Titan what it is showing.'))

    def read():
        lines = []
        ok, state = LINK.bridge('window.state')
        if ok and isinstance(state, dict):
            if not state.get('has_window'):
                lines.append(_('Titan has no window open.'))
            elif state.get('away'):
                lines.append(_('Titan\'s window is out of the way.')
                             + (' ' + _('The Invisible UI is answering keys.')
                                if state.get('invisible_ui') else ''))
            else:
                lines.append(_('Titan\'s window is on the screen.'))
        ok, views = LINK.bridge('views.list')
        if ok and isinstance(views, dict):
            named = [str(view.get('name') or '')
                     for view in (views.get('views') or [])
                     if isinstance(view, dict)]
            current = str(views.get('current') or '')
            if named:
                lines.append(_('Views: {names}.').format(
                    names=', '.join(name for name in named if name)))
            if current:
                lines.append(_('Showing: {name}.').format(name=current))
        ok, status = LINK.bridge('statusbar.read')
        if ok and isinstance(status, dict):
            for element in (status.get('elements') or status.get('items')
                            or []):
                if isinstance(element, dict):
                    said = str(element.get('text') or element.get('name') or '')
                else:
                    said = str(element)
                if said.strip():
                    lines.append(said)
        if not lines:
            dialogs.report(_('Titan did not say what it is showing.'))
            return
        _page(lines, _('Titan'))
    _work(read)


def components():
    """Which Titan components are installed and running."""
    def read():
        ok, data = LINK.bridge('components.list')
        if not ok:
            return _refused(data)
        rows = (data or {}).get('components') or []
        lines = []
        for row in rows:
            if not isinstance(row, dict):
                lines.append(str(row))
                continue
            name = str(row.get('name') or row.get('id') or '')
            state = _('on') if row.get('enabled', True) else _('off')
            lines.append('{}, {}'.format(name, state) if name else '')
        if not _page(lines, _('Titan components')):
            dialogs.report(_('Titan has no components.'))
    _work(read)


# --------------------------------------------------------------------------- #
# Titan's sounds
# --------------------------------------------------------------------------- #
def cue(name, position=None):
    """Play one of the user's own theme sounds, through Titan's mixer.

    Asked of Titan rather than played here on purpose: Titan resolves the
    name against the theme the user chose, with their own overlay winning,
    and pans it with its own law. A copy of that in NVDA would be a second
    answer to a question Titan has already answered.
    """
    def play():
        args = {'name': name}
        if position is not None:
            args['pan'] = float(position)
        LINK.bridge('sounds.play', **args)
    _work(play)


# --------------------------------------------------------------------------- #
# Switches
# --------------------------------------------------------------------------- #
def toggle_announcements():
    from . import channel
    from . import configSpec
    channel.CHANNEL.enabled = not channel.CHANNEL.enabled
    configSpec.write({'announcements': channel.CHANNEL.enabled})
    dialogs.report(_("Titan's own announcements on")
                   if channel.CHANNEL.enabled
                   else _("Titan's own announcements off"))


def toggle_position():
    from . import configSpec
    from . import panner
    panner.PANNER.enabled = not panner.PANNER.enabled
    if not panner.PANNER.enabled:
        panner.PANNER.restore()
    configSpec.write({'position': panner.PANNER.enabled})
    dialogs.report(_('Positioned speech on') if panner.PANNER.enabled
                   else _('Positioned speech off'))


# --------------------------------------------------------------------------- #
# Where the keyboard is
# --------------------------------------------------------------------------- #
def _focused():
    """The object NVDA is on, or None. Read on NVDA's own thread by the
    caller - every one of these commands runs on it."""
    from . import compat
    api = compat.api
    if api is None:
        return None
    try:
        return api.getFocusObject()
    except Exception:                                # noqa: BLE001
        return None


def where_am_i():
    """The whole ancestry, said on demand.

    Deliberately not the thing that is announced as you move: that is a
    difference and this is the whole chain, so pressing it twice says the
    same thing twice - which is what somebody who has lost their place
    needs and what a difference cannot give them.
    """
    obj = _focused()
    if obj is None:
        _refused(_('NVDA is not reporting a focus.'))
        return
    from . import ancestry
    from . import focus as focus_mod
    said = ancestry.sentence(obj, focus_mod.module_for(obj))
    name = str(getattr(obj, 'name', '') or '').strip()
    if name:
        said = '{}: {}'.format(said, name) if said else name
    dialogs.report(said or _('There is nothing above this control.'))


# --------------------------------------------------------------------------- #
# The voice classes
# --------------------------------------------------------------------------- #
def voice_classes():
    from . import classManager
    if not classManager.show():
        _refused(_('The voice classes need NVDA\'s own interface.'))


# --------------------------------------------------------------------------- #
# Naming what the program never named
# --------------------------------------------------------------------------- #
def label_control():
    """Give the control the keyboard is on a name, and remember it."""
    from . import labels
    obj = _focused()
    if obj is None:
        _refused(_('NVDA is not reporting a focus.'))
        return
    key, strong = labels.key_of(obj)
    if not key:
        _refused(_('There is nothing about this control that would still be '
                   'true next time, so a name could not be kept for it.'))
        return
    existing, source = labels.described(obj)

    def answered(text):
        said = str(text or '').strip()
        if not said:
            if existing:
                labels.remove(obj)
                dialogs.report(_('That name has been forgotten.'))
            return
        if labels.put(obj, said, source='user'):
            dialogs.report(_('This control is now called {name}.')
                           .format(name=said))
        else:
            _refused(_('That name could not be kept.'))

    prompt = _('What should this control be called?')
    if not strong:
        prompt = _('What should this control be called? (This program does '
                   'not name its controls, so the name is kept by where '
                   'this one sits - it may move if the program changes.)')
    dialogs.ask_text(prompt, _('Name this control'), answered,
                     default=existing if source == 'user' else '')


def describe_control():
    """Read the control the keyboard is on, and say what it shows."""
    from . import graphics
    obj = _focused()
    if obj is None:
        _refused(_('NVDA is not reporting a focus.'))
        return
    ready, why = graphics.ai_available()
    if not ready:
        _refused(why)
        return
    dialogs.report(_('Reading this control.'))
    question = graphics.QUESTION_PICTURE \
        if graphics.kind_of(obj) in ('picture', 'chart', 'animation') \
        else graphics.QUESTION

    def read():
        ok, text = graphics.read(obj, question=question)
        said = _for_a_person(text)
        if not ok or not said:
            dialogs.report(said or _('It could not be read.'))
            return
        dialogs.report(said) if len(said) <= _A_SENTENCE \
            else dialogs.browse(said, _('What this shows'))
    _work(read)


# --------------------------------------------------------------------------- #
# A window that answers nothing
# --------------------------------------------------------------------------- #
def watch_surface():
    """Read the window as a picture, and follow what is highlighted."""
    from . import surface
    if surface.watching():
        surface.stop_now()
        dialogs.report(_('No longer watching.'))
        return
    # Watching needs a handle to hold on to - "whatever is in front" is
    # not something that can be watched, and a window that has gone must
    # be able to end the watch. So this one asks Windows when NVDA cannot
    # say, rather than refusing with "there is no window to read" while
    # the user is plainly looking at one.
    hwnd = int(_here().get('hwnd') or 0) or _foreground_window()
    ok, said = surface.start(hwnd)
    dialogs.report(said)
    if not ok:
        return
    if surface.report().get('mode') == surface.MODE_NATIVE:
        # The native watch does its own first reading, because it is the
        # overlay that must take the picture - only the overlay knows to make
        # itself invisible first, and a reading of a window with our own
        # controls already on it is a reading of our own controls.
        return

    def first():
        read_ok, text = surface.read(hwnd)
        if not read_ok:
            dialogs.report(text)
            return
        from . import smart
        smart.take(hwnd, text)
        found = surface.highlight_in(text)
        dialogs.report(found or _for_a_person(text)[:_A_SENTENCE]
                       or _('Nothing was read.'))
    _work(first)


# --------------------------------------------------------------------------- #
# The reader modules
# --------------------------------------------------------------------------- #
def reader_modules():
    """What is installed and what each one knows."""
    from . import readerModules
    rows = readerModules.describe()
    lines = []
    for row in rows:
        lines.append('{} ({})'.format(row['label'] or row['id'], row['id']))
        lines.append(_('    {lists} list rules, {regions} places, '
                       '{controls} controls, {live} live, {labels} names')
                     .format(lists=row['lists'], regions=row['regions'],
                             controls=row['controls'], live=row['live'],
                             labels=row['labels']))
        lines.append('    ' + row['source'])
    wrong = readerModules.problems()
    if wrong:
        lines.append('')
        lines.append(_('Modules that were not loaded:'))
        lines.extend('    ' + one for one in wrong)
    where = readerModules.user_folder()
    if where:
        lines.append('')
        lines.append(_('Your own modules go in {where}').format(where=where))
    if not lines:
        _refused(_('There are no reader modules.'))
        return
    _page(lines, _('Reader modules'))


def draft_module():
    """Write a reader module for the program the user is in."""
    from . import draft
    obj = _focused()
    if obj is None:
        _refused(_('NVDA is not reporting a focus.'))
        return
    dialogs.report(_('Looking at this program.'))

    def write():
        module, why = draft.with_ai(obj)
        if not module:
            dialogs.report(why or _('There was nothing to write.'))
            return
        where, problem = draft.save(module)
        if problem:
            dialogs.report(problem)
            return
        dialogs.report(_('A module for this program has been written to '
                         '{where}. {note}')
                       .format(where=where,
                               note=why or _('Open it and correct it.')))
    _work(write)


# --------------------------------------------------------------------------- #
# The touchpad
# --------------------------------------------------------------------------- #
def toggle_trackpad():
    from . import configSpec
    from . import trackpad
    on, said = trackpad.toggle()
    values = configSpec.read()
    values['trackpad'] = bool(trackpad.running())
    configSpec.write(values)
    dialogs.report(said)


# --------------------------------------------------------------------------- #
# The switches that apply HERE
# --------------------------------------------------------------------------- #
def toggle_here(name):
    """Turn one per-program switch on or off for the program in front."""
    from . import perProgram
    program = perProgram.application_of()
    if not program:
        _refused(_('There is no program in front to set this for.'))
        return
    now = not perProgram.value(name)
    perProgram.set_value(name, program, now)
    words = {
        'autoLabel': _('Working out names for unnamed controls'),
        'surfaceReading': _('Reading this window as a picture'),
        'graphicKinds': _('Saying what pictures are'),
    }
    dialogs.report(_('{what} in {program}: {state}').format(
        what=words.get(name, name), program=perProgram.label_of(),
        state=_('on') if now else _('off')))


def forget_here():
    """Let the general settings decide in this program again."""
    from . import perProgram
    program = perProgram.application_of()
    if not program:
        _refused(_('There is no program in front.'))
        return
    changed = [name for name in perProgram.PER_PROGRAM
               if perProgram.clear(name, program)]
    dialogs.report(_('{program} now follows the general settings.')
                   .format(program=perProgram.label_of()) if changed
                   else _('{program} already follows the general settings.')
                   .format(program=perProgram.label_of()))


# --------------------------------------------------------------------------- #
# A window that is being read as a picture
# --------------------------------------------------------------------------- #
def smart_press():
    """Press the control the cursor is on in a window read as a picture."""
    from . import smart
    ok, said = smart.press()
    if not ok:
        _refused(said)
        return
    if said:
        dialogs.report(_for_a_person(said)[:_A_SENTENCE])


def surface_mode():
    """Swap between reading a window as a GAME and wearing it as controls.

    The two are different problems. A game already has a keyboard model - its
    menu answers the arrows - and what the player cannot do is see which item
    is highlighted, so the reader follows the highlight and leaves the keys
    alone. An inaccessible application has no keyboard model that reaches the
    user at all, and there the right answer is not a cursor of ours over a
    reading: it is the window given REAL controls, which is what an app module
    written by hand would have produced.

    Which a program is cannot always be told from its window, so the user can
    say, and it is remembered for that program.
    """
    from . import perProgram
    from . import surface
    program = perProgram.application_of()
    if not program:
        _refused(_('There is no program in front.'))
        return
    now = surface.report().get('mode')
    game = (now != surface.MODE_GAME)
    perProgram.set_value('surfaceGame', program, game)
    dialogs.report(
        _('{program} will be read as a game: what is highlighted is '
          'announced, and the keys stay the game\'s.').format(
              program=perProgram.label_of()) if game else
        _('{program} will be given controls of its own: what was read is '
          'put on the window as real controls you can Tab through.').format(
              program=perProgram.label_of()))
    if surface.watching():
        surface.stop_now()
