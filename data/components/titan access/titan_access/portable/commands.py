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
        except ImportError as error:                 # noqa: BLE001
            # **A part this reader has not got, said as that.** These
            # commands are one source in two readers, and a few of them
            # reach NVDA's own speech filter, audio session or review
            # cursor - which inside Titan Access is a module that is not
            # there. "That did not work" would send somebody looking for
            # a fault instead of telling them what is true.
            dialogs.report(_('This reader has not got that: {what}')
                           .format(what=error))
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
    """An answer as something to read, however short it is.

    **A short answer is still an answer.** One line went to speech and was
    cut off by the next thing that spoke exactly as a long one was - and
    worse, because a one-line answer is usually the one somebody asked a
    direct question to get. It is the same walked page now: it says
    "Komunikat", the arrows read it, Escape closes it.

    What is NOT a page is a toggle saying which state it is in - those go
    through `dialogs.report`, are two words long and are meant to be
    heard in passing.
    """
    lines = [str(line) for line in lines if str(line or '').strip()]
    if not lines:
        return False
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
    """What each kind of thing sounds like, and in what order it is read.

    Walked, like everything else - and the form is a row on it, because
    a pitch is a slider and a list cannot be one.
    """
    from . import managerWalk
    ok, said = managerWalk.open_it(only=managerWalk.THE_CLASS_MANAGER)
    if not ok and said:
        _refused(said)


def voice_classes_as_a_form():
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
        # Terse on purpose: the long version explained the reason it
        # cannot be done, which is this add-on's business and not the
        # user's. What they need is what happened.
        _refused(_('You cannot set a name on this control'))
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


#: The control the last description was answered from memory for. Pressing
#: the key again on the SAME one is what asks for a fresh reading - which
#: is the only way to re-read a picture that has changed, and the answer to
#: an animation, whose remembered description is a moment rather than a
#: fact.
_described_from_memory = ''


def what_is_this_written_in():
    """Say what the window in front is built with, and what that means.

    The first thing anybody writing an app module works out by hand, and
    the machine will simply answer it: the libraries the process has
    loaded say what toolkit it is running on, and a program cannot run on
    one whose library it has not loaded. Worth saying out loud because it
    is also the answer to "why does this program read so badly" - a Java
    frame answers nothing until the Access Bridge is on, a Qt list
    reports no columns, a window that paints itself has nothing to walk.
    """
    from . import toolkit
    obj = _focused()
    if obj is None:
        _refused(_('NVDA is not reporting a focus.'))
        return
    said = toolkit.describe(obj)
    if not said:
        # Translators: said when the toolkit of a window cannot be told.
        _refused(_('This window will not say what it is written in - which '
                   'usually means it is running as another user.'))
        return
    dialogs.report(said) if len(said) <= _A_SENTENCE \
        else dialogs.browse(said, _('What this is written in'))


def describe_control():
    """Read the control the keyboard is on, and say what it shows.

    **Remembered, because a reading is a request.** A picture, an icon, a
    chart or an animation read with AI costs a call to the user's own
    provider and a picture of part of their screen sent to it. It is kept
    against the control's own identity, per program, in the same file as
    the labels - so the second time the key is pressed on that icon the
    answer is instant, costs nothing, and is there with Titan switched
    off, uninstalled, or on a machine that has never had it.

    Pressing the key AGAIN on the same control re-reads it. That is what
    makes a remembered answer safe to give: nothing is stuck with a
    description that has gone stale, and an animation - whose answer is
    what it showed at a moment - is one keypress from now.
    """
    global _described_from_memory
    from . import graphics
    from . import labels
    obj = _focused()
    if obj is None:
        _refused(_('NVDA is not reporting a focus.'))
        return
    key, _strong = labels.key_of(obj)
    remembered, _kind = labels.description_of(obj)
    if remembered and key and _described_from_memory != key:
        # Said as it was said before, and the key is armed: press it again
        # and it is read afresh.
        _described_from_memory = key
        dialogs.report(remembered) if len(remembered) <= _A_SENTENCE \
            else dialogs.browse(remembered, _('What this shows'))
        return
    _described_from_memory = ''
    ready, why = graphics.ai_available()
    if not ready:
        # A remembered answer is better than a refusal, and is the whole
        # point of remembering it: with Titan not running this is all
        # there is, and it is a real answer.
        if remembered:
            dialogs.report(remembered) if len(remembered) <= _A_SENTENCE \
                else dialogs.browse(remembered, _('What this shows'))
            return
        _refused(why)
        return
    dialogs.report(_('Reading this control.'))
    kind = graphics.kind_of(obj)
    question = graphics.QUESTION_PICTURE \
        if kind in ('picture', 'chart', 'animation') \
        else graphics.QUESTION

    def read():
        ok, text = graphics.read(obj, question=question)
        said = _for_a_person(text)
        if not ok or not said:
            dialogs.report(said or _('It could not be read.'))
            return
        # Kept only when it really IS a reading. Titan answers a refusal
        # as ordinary prose with the call reported as having worked, and
        # `graphics.read` is what tells the two apart - remembering a
        # refusal would answer "AI OCR is switched off" for ever as what
        # the picture shows.
        try:
            labels.remember_description(obj, said, kind)
        except Exception:                            # noqa: BLE001
            pass
        dialogs.report(said) if len(said) <= _A_SENTENCE \
            else dialogs.browse(said, _('What this shows'))
    _work(read)


# --------------------------------------------------------------------------- #
# A window that answers nothing
# --------------------------------------------------------------------------- #
def read_locally():
    """Read the window with WINDOWS' own OCR. No AI, no Titan, no request.

    The everyday half of reading an unreadable window. Windows has a
    recogniser built in and NVDA already wraps it, so the words of a custom
    installer, a game's menu or a program that exposes nothing are a tenth
    of a second away, on this machine, for nothing - and the result is a
    page the reader's own cursor can be moved through, which is what
    somebody wants to do with a wall of text.

    What it cannot do is understand: which of these is a button, what is
    highlighted. That is what the AI reading is for, and it is a different
    key.
    """
    from . import localOcr
    ok, why = localOcr.available()
    if not ok:
        _refused(why)
        return
    hwnd = int(_here().get('hwnd') or 0) or _foreground_window()
    if not hwnd:
        # Translators: said when there is no window to read.
        _refused(_('There is no window to read.'))
        return

    def work():
        reading = localOcr.read_window(hwnd)
        if reading is None or not reading:
            _refused(localOcr.report().get('why')
                     # Translators: said when the local recogniser found no
                     # words in a window.
                     or _('Windows read nothing in that window.'))
            return
        # The cursor as well as the words: a reading nobody can move through
        # is a wall of text, and this one knows where every line is, so Tab
        # and the arrows work and Enter clicks.
        from . import smart
        smart.take_local(hwnd, reading)
        # Translators: the title of the window showing a local OCR reading.
        dialogs.browse(reading.text, _('What Windows read here'))
    _work(work)


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


def share_names():
    """Share control names with Titan Access, both ways, now.

    It happens by itself when Titan connects; this is for the moment
    somebody has just named a dozen controls and wants the other reader to
    know before they switch to it.
    """
    from . import shared

    def work():
        ok, said = shared.sync_labels()
        dialogs.report(said if said else (
            # Translators: said when control names have been shared.
            _('Shared.') if ok else _('Nothing was shared.')))
    _work(work)


def customise_control():
    """Everything the user may decide about the control they are on.

    JAWS' customised control, which is thirty years old and still the
    thing users of every other reader ask for: a control the program got
    wrong is mended once, by the person it is wrong for, and stays mended.

    One window rather than four commands, because these are four answers
    to one question - "what should this be to me?" - and a user who has to
    remember which key sets which is a user who sets none of them.
    """
    from . import classes
    from . import labels
    obj = _focused()
    if obj is None:
        _refused(_('NVDA is not reporting a focus.'))
        return
    key, _strong = labels.key_of(obj)
    if not key:
        # Translators: said about a control that cannot be recognised again.
        _refused(_('This control has nothing stable to remember it by, so '
                   'nothing set on it would be found again.'))
        return
    custom = labels.custom_of(obj)
    label, source = labels.described(obj)
    voices = [''] + sorted(classes.labels())
    words = [_('as the reader says it')] + \
        [classes.label_of(tag) for tag in voices[1:]]

    def keep(answers):
        if answers is None:
            return
        labels.customise(
            obj,
            silent=answers.get('silent'),
            role_word=answers.get('role_word'),
            note=answers.get('note'),
            voice=voices[answers.get('voice', 0)]
            if 0 <= answers.get('voice', 0) < len(voices) else '')
        typed = str(answers.get('label') or '').strip()
        if typed != str(label or '').strip():
            if typed:
                labels.put(obj, typed, source='user')
            else:
                labels.remove(obj)
        # Translators: said when what the user decided about a control is
        # kept.
        dialogs.report(_('Kept'))

    try:
        voice_at = voices.index(str(custom.get('voice') or ''))
    except ValueError:
        voice_at = 0
    dialogs.customise(
        # Translators: the title of the window for customising one control.
        _('This control'),
        [
            # Translators: a field: the name to read instead of the
            # control's own.
            {'id': 'label', 'kind': 'text', 'label': _('Call it'),
             'value': label or ''},
            # Translators: a field: the word to say instead of the control
            # type.
            {'id': 'role_word', 'kind': 'text',
             'label': _('Say it is a'), 'value': custom.get('role_word', '')},
            # Translators: a field: something to say after the control,
            # every time.
            {'id': 'note', 'kind': 'text', 'label': _('And add'),
             'value': custom.get('note', '')},
            # Translators: a field: the voice its name is spoken in.
            {'id': 'voice', 'kind': 'choice', 'label': _('In the voice for'),
             'choices': words, 'value': voice_at},
            # Translators: a field: never announce this control at all.
            {'id': 'silent', 'kind': 'check',
             'label': _('Never announce it'),
             'value': bool(custom.get('silent'))},
        ], keep)


def command_palette(open_layer=None):
    """Open the palette: the layers, walked.

    **A list in the same shape as the virtual window, not a dialog.** A
    modal dialog takes the keyboard away from the reader, is read by NVDA
    as a dialog rather than by this add-on in the user's own voice
    classes, and plays none of the auditory icons every other list here
    plays - so the one thing somebody opens twenty times a day was the
    one thing that did not feel like the rest of the add-on. The arrows
    walk it, Enter runs what the cursor is on, and Escape goes back one
    level before it closes.

    ``open_layer`` is the old fast path - arm the layer and wait for its
    key - offered as the last row rather than being what choosing a layer
    does, because somebody who has just found the palette does not know
    the letters yet.
    """
    from . import layers
    from . import palette
    names = layers.names()
    if not names:
        return False, ''
    rows = []
    for name in names:
        rows.append({
            'label': '%s (%d)' % (layers.label(name),
                                  len(layers.keys_of(name))),
            # Translators: what a row of the palette's first list is.
            'role': _('layer'),
            'icon': 'open-object',
            'run': (lambda chosen=name: layer_commands(chosen, open_layer)),
        })
    # Translators: the title of the command palette.
    return palette.show(rows, _('Commands'))


def layer_commands(layer, open_layer=None):
    """One layer's commands, walked. Enter runs the one the cursor is on."""
    from . import layers
    from . import palette
    keys = layers.keys_of(layer)
    if not keys:
        return False, ''
    rows = []
    for key in sorted(keys):
        command, said = keys[key]
        try:
            text = said() if callable(said) else str(command)
        except Exception:                            # noqa: BLE001
            text = str(command)
        rows.append({
            # The key is named beside the command rather than instead of
            # it: this list is where somebody LEARNS the letter, and a
            # list of bare letters would teach nothing.
            'label': '%s (%s)' % (text, key),
            # Translators: what a row of a layer's command list is.
            'role': _('command'),
            'run': (lambda name=command: run_command(name)),
        })
    # **The fast path stays reachable from the slow one.** Somebody who
    # knows the letters should not have to walk a list to use them, and a
    # way in that exists and cannot be found is the failure this whole
    # palette was built to answer.
    if open_layer is not None:
        rows.append({
            # Translators: the last row of a layer's command list.
            'label': _('Press a layer key instead'),
            'role': _('command'),
            'run': (lambda: _arm_layer(open_layer, layer)),
        })
    # Escape goes back to the layers rather than out: the two lists are
    # one thing to walk, and picking the wrong layer should cost one
    # keystroke rather than the whole palette.
    return palette.show(rows, layers.label(layer),
                        back=lambda: command_palette(open_layer))


def _arm_layer(open_layer, layer):
    from . import palette
    palette.stop()
    open_layer(layer)
    return True, ''


def run_command(name):
    """Run one of this module's own commands by the name a layer gives it.

    ``(ok, why)``. The name comes from :data:`layers.LAYERS`, which is a
    table in this add-on rather than anything a caller supplies - so this
    is a lookup in one module's own globals and never a way to name an
    attribute of something else.

    **The palette is closed BEFORE the command runs**, and that is not
    tidiness: a command puts a window up, says something, or borrows keys
    of its own, and a palette still holding the arrows underneath it
    would swallow the first thing the user pressed in whatever it opened.
    """
    from . import palette
    function = globals().get(str(name or ''))
    palette.stop()
    if not callable(function):
        return False, 'there is no command called %r' % name
    function()
    return True, ''


def titan_menu_as_a_menu():
    """The Titan menu as the platform's own `wx.Menu`.

    Kept because it is worth keeping: the platform announces it as a
    menu, counts it, follows the arrows into a submenu and closes on
    Escape with none of that written here. It is no longer what the
    gesture opens, because a menu takes the foreground and says each
    entry once - but somebody who wants it should have it.
    """
    from . import menu as titan_menu_module
    titan_menu_module.show(None)


def titan_menu():
    """The Titan menu, walked - the same menu, not a second one.

    It used to build a list out of the action catalogue, and that is a
    different thing: the menu has a shape somebody thought about - the
    assistant first, then AI OCR, the applications, this program, the
    managers, the switches - and a second list beside it is how the two
    quietly stop agreeing. This walks the menu that `menu.build` really
    makes.
    """
    from . import menuWalk
    ok, said = menuWalk.open_it()
    if not ok and said:
        _refused(said)


def titan_actions():
    """Every Titan action there is, one add-on at a time.

    Not the menu - the CATALOGUE, which is a different question: "what
    can this add-on be told to do" rather than "what is on the menu".
    """
    from . import gestures
    from . import palette
    rows = gestures.load_catalogue()
    if not rows:
        # Translators: said when Titan has not been asked what it offers.
        _refused(_('Titan has not said what it offers yet.'))
        return False, ''
    groups = {}
    for row in rows:
        groups.setdefault(row['addon'], []).append(row)
    ordered = sorted(groups.items(),
                     key=lambda pair: (pair[1][0].get('label')
                                       or pair[0]).lower())
    made = []
    for addon_id, actions in ordered:
        label = actions[0].get('label') or addon_id
        made.append({
            'label': '%s (%d)' % (label, len(actions)),
            # Translators: what a row of the actions list is.
            'role': _('add-on'),
            'icon': 'open-object',
            'run': (lambda a=sorted(actions, key=lambda r: r['action']),
                    name=label: _titan_actions(a, name)),
        })
    # Translators: the title of the list of everything Titan offers.
    return palette.show(made, _('Everything Titan offers'))


def _titan_actions(actions, name):
    """One add-on's actions, walked. Enter runs the one chosen."""
    from . import palette
    rows = []
    for row in actions:
        rows.append({
            'label': _action_label(row),
            # Translators: what a row of an add-on's action list is.
            'role': _('action'),
            'run': (lambda one=row: _run_titan_action(one)),
        })
    return palette.show(rows, name, back=titan_actions)


def _run_titan_action(row):
    from . import gestures
    from . import palette
    palette.stop()
    _work(lambda: gestures.run(row))
    return True, ''


def _action_label(row):
    """What one action is called, the way the menu calls it."""
    from . import menu
    try:
        return menu._label_of(row)
    except Exception:                                # noqa: BLE001
        return str(row.get('action') or '')


def local_model():
    """Say what the local recogniser is, and offer to fetch it.

    **The tier between Windows' recogniser and the AI**, and the one
    worth having: a modern OCR model running on this machine, which reads
    a game's stylised menu and a low-resolution guest that Windows cannot,
    sends nothing anywhere and spends nothing. It is a download, so it is
    asked for.
    """
    from . import titan
    found = titan.local_model()
    if not found:
        _refused(_('Titan is not answering.'))
        return
    if found.get('installed'):
        # Translators: said when the local recogniser is already here.
        # {reads} is how many readings it has made.
        dialogs.report(
            _('The local recogniser is installed. {reads} reading(s), '
              'last one {ms} ms.').format(reads=found.get('reads', 0),
                                          ms=int(found.get('ms') or 0)))
        return

    def fetch():
        # Translators: said while the recogniser is being downloaded.
        dialogs.report(
            _('Fetching the local recogniser. This takes a few minutes.'))
        from . import titan as titan_module
        ok, text = titan_module.install_local_model()
        dialogs.report(text or (_('Done.') if ok
                                else _('It could not be fetched.')))

    dialogs.confirm(
        # Translators: asked before downloading the local recogniser.
        _('The local recogniser is not installed. It is a download of a '
          'few hundred megabytes, and after it nothing leaves this '
          'machine and no reading costs anything. Fetch it now?'),
        _('Local recogniser'),
        # A download is minutes, and the thread this is called on is the
        # one reading the screen.
        on_yes=lambda: _work(fetch))


def check_module():
    """Does the module for this program actually DO anything to it?

    The one question a user has about a module that somebody - or the AI -
    wrote for them, and the one the module's own format cannot answer. A
    module can be well formed in every respect and fire not once, and from
    the outside that is exactly a module that was never written. This runs
    it against the controls that are really on the screen and names the
    rules that matched nothing.
    """
    from . import readerModules
    from . import verify
    obj = _focused()
    if obj is None:
        _refused(_('NVDA is not reporting a focus.'))
        return
    module = readerModules.for_object(obj)
    if not module:
        # Translators: said when no reader module claims this program.
        _refused(_('No reader module claims this program.'))
        return
    report = verify.check(module, obj)
    lines = [verify.sentence(report)]
    for row in report.get('rules') or []:
        lines.append('  %s: %s' % (
            row['said'],
            # Translators: how many controls a module's rule matched.
            _('{count} matched').format(count=row['matched'])
            + ((' - ' + row['example']) if row.get('example') else '')))
    _page(lines, _('Does this module work?'))


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


# --------------------------------------------------------------------------- #
# Watching an area
# --------------------------------------------------------------------------- #
def watch_this():
    """Watch the object the navigator is on, and say when it changes.

    The navigator, not the focus: a progress bar, a status line or a pane
    that fills itself in is never focused, and object navigation is how
    NVDA reaches one. The navigator follows the focus until the user moves
    it, so on the control they are working in this is that control.
    """
    from . import monitors
    _ok, said = monitors.watch_this_control()
    dialogs.report(said)


def watch_this_area():
    """Watch the area this object covers, with Windows' own recogniser.

    For a part of a window that answers nothing - a panel a program draws
    itself. Walk to it with object navigation and watch what is drawn
    there, rather than the whole window, which would read every clock and
    counter anywhere in it.
    """
    from . import monitors
    _ok, said = monitors.watch_this_area()
    dialogs.report(said)


def watch_this_window():
    """Watch this whole window as a rectangle, with Windows' own OCR.

    The one that works on a program with no accessibility at all - a game's
    score, an installer's progress - which is what JAWS Frames is for.
    """
    from . import monitors
    _ok, said = monitors.watch_this_window()
    dialogs.report(said)


def watched_areas():
    """Everything being watched, and a way to stop watching one."""
    from . import monitors
    rows = monitors.all_monitors()
    if not rows:
        # Translators: said when nothing is being watched.
        _refused(_('Nothing is being watched. Use the command for watching '
                   'this control, its area or this window to mark one.'))
        return
    kinds = {
        # Translators: a kind of watched area.
        monitors.BY_CONTROL: _('a control'),
        # Translators: a kind of watched area.
        monitors.BY_POINT: _('a place in the window'),
        # Translators: a kind of watched area.
        monitors.BY_AREA: _('an area of the screen'),
    }
    choices = ['%s (%s%s)' % (
        row.get('name') or '', kinds.get(row.get('kind'), ''),
        (', ' + row['program']) if row.get('program') else '')
        for row in rows]

    def chosen(index):
        if index is None or not 0 <= index < len(rows):
            return
        # Translators: asked before a watched area is forgotten. {what} is
        # its name.
        dialogs.confirm(
            _('Stop watching {what}?').format(what=rows[index].get('name')
                                              or ''),
            # Translators: the title of that question.
            _('Watched areas'),
            lambda: _forget_monitor(index))
    # Translators: the title of the list of watched areas.
    dialogs.choose(choices, _('Watched areas'), on_chosen=chosen)


def _forget_monitor(index):
    from . import monitors
    monitors.remove(index)
    # Translators: said when a watched area is forgotten.
    dialogs.report(_('No longer watching'))


# --------------------------------------------------------------------------- #
# Titan, whole
# --------------------------------------------------------------------------- #
def titan_window():
    """Everything Titan is, WALKED - the pages as a list, and what is on
    a page as a list.

    **This used to put up a `wx.Dialog` and that was the wrong default.**
    A dialog takes the foreground away from the program the user was in,
    has to be closed before anything else can be done, and says every
    answer once - so a long one is cut off by the next thing that speaks.
    Every other list in this add-on is walked; Titan's own window was the
    one that was not.

    The dialog is still there and still worth having - it is a real form
    with real controls that the platform announces itself - and
    :func:`titan_window_as_a_form` is what opens it now. This is what the
    menu entry, the gesture and the palette all reach.
    """
    from . import titanWalk
    ok, _said = titanWalk.open_it()
    if not ok:
        # It said why itself; nothing to add.
        return


def titan_window_as_a_form():
    """Everything Titan is, in a window of NVDA's own.

    The other way of showing the same thing: a real dialog with real
    controls, for somebody who would rather have a form than a list.
    """
    from . import titanWindow
    if not titanWindow.show():
        # Translators: said when a window of this add-on cannot be opened.
        _refused(_('That window could not be opened'))


def titan_applications():
    """Choose one of Titan's applications and walk it with the arrows."""
    from . import appReview
    from . import titan

    def chosen(index):
        if index is None or not 0 <= index < len(rows):
            return
        name = str(rows[index].get('name') or rows[index].get('id') or '')
        _ok, said = appReview.start(name)
        dialogs.report(said)

    ok, rows = titan.describable_applications()
    if not ok:
        _refused(str(rows))
        return
    if not rows:
        # Translators: said when Titan has no application to describe.
        _refused(_('Titan has no applications to show'))
        return
    choices = []
    for row in rows:
        name = str(row.get('name') or row.get('id') or '')
        # An application whose interface cannot be described is read off
        # its own window instead, which says less - so it says so here,
        # before it is opened rather than after.
        choices.append(name if row.get('describable') else
                       # Translators: how an application that can only be
                       # read off its own window is listed.
                       _('{name} (read off its window)').format(name=name))
    # Translators: the title of the list of Titan's applications. TCE is
    # what Titan's own applications have always been called.
    dialogs.choose(choices, _('TCE applications'), on_chosen=chosen)


def application_review_off():
    from . import appReview
    _on, said = appReview.stop()
    dialogs.report(said)


def close_application():
    from . import appReview
    _on, said = appReview.close_application()
    dialogs.report(said)


def application_as_a_window():
    """The application being reviewed, as real controls instead.

    The same screen, the other way round - the pair Titan's own AI OCR
    already offers (a reading to walk, or the controls rebuilt), for the
    same reason: a list is better for reading and real controls are better
    for filling in.
    """
    from . import appReview
    from . import appScreen
    if not appReview.reviewing():
        # Translators: said when no application is being reviewed.
        _refused(_('No application is being reviewed'))
        return
    session = appReview.session()
    name = appReview.report().get('application') or ''
    ok, screen = _screen_of(session)
    if not ok:
        _refused(str(screen))
        return
    appReview.stop()
    built = appScreen.build()
    if built is None:
        _refused(_('That window could not be opened'))
        return
    try:
        import gui
        import wx
        wx.CallAfter(lambda: built(gui.mainFrame, session,
                                   screen.get('screen'), name).Show())
    except Exception:                                # noqa: BLE001
        _refused(_('That window could not be opened'))


def walk_a_widget():
    """Choose one of Titan's widgets and walk it with the arrows."""
    from . import titan
    from . import widgetReview
    ok, rows = titan.widgets()
    if not ok:
        _refused(str(rows))
        return
    if not rows:
        # Translators: said when Titan has no widgets.
        _refused(_('Titan has no widgets'))
        return

    def chosen(index):
        if index is None or not 0 <= index < len(rows):
            return
        name = str(rows[index].get('id') or rows[index].get('name') or '')
        label = str(rows[index].get('name') or name)
        _ok, said = widgetReview.start(name, label)
        dialogs.report(said)

    # Translators: the title of the list of Titan's widgets.
    dialogs.choose([str(row.get('name') or row.get('id') or '')
                    for row in rows], _('Widgets'), on_chosen=chosen)


def virtual_window():
    """Walk this window as a virtual window of all its controls."""
    from . import virtualWindow
    _on, said = virtualWindow.toggle()
    dialogs.report(said)


def virtual_window_help():
    """Which letter jumps to what, as a page to read."""
    from . import virtualWindow
    words = virtualWindow.quick_names()
    lines = ['%s - %s' % (letter, words.get(letter, ''))
             for letter in sorted(virtualWindow.QUICK)]
    # Translators: the title of the page listing the quick navigation keys.
    dialogs.browse('\n'.join(lines), _('Quick navigation in the virtual '
                                        'window'))


def application_log():
    """Why the application said nothing - its own log, read here.

    A TCE application reports a failure the way Titan's own do: it
    rescues, says one sentence and carries on. "It did nothing" is a
    report with no reason in it, and the reason is always there - in a
    window the user cannot see, because the application has no window on
    this machine at all.
    """
    from . import appReview
    from . import titan
    if not appReview.reviewing():
        # Translators: said when no application is being reviewed.
        _refused(_('No application is being reviewed'))
        return
    ok, lines = titan.application_log(appReview.session())
    if not ok:
        _refused(str(lines))
        return
    if not lines:
        # Translators: said when an application has said nothing.
        dialogs.report(_('The application has said nothing'))
        return
    # Translators: the title of the page showing an application's log.
    dialogs.browse('\n'.join(lines), _('What the application said'))


def _screen_of(session):
    from . import titan
    return titan.described_screen(session)


# --------------------------------------------------------------------------- #
# Windows and actions
# --------------------------------------------------------------------------- #
def windows_and_actions():
    """Window-Eyes' own idea: the windows, their controls, and what each
    control will actually DO.

    Three lists, one after another, because that is the shape of the
    question - which window, which control, which of the things it offers -
    and because each of them is a plain choice a reader already knows how to
    read.
    """
    from . import windowsAndActions as wa
    found = wa.windows()
    if not found:
        # Translators: said when no windows could be listed.
        _refused(_('No windows could be listed.'))
        return
    here = wa.foreground()
    labels = [label for label, _obj in found]

    def chosen(index):
        if index is None or not 0 <= index < len(found):
            return
        _controls_of(found[index][1])
    # The window the user is in is offered first, because it is what they
    # almost always mean - but every window is there, which is the point.
    if here is not None:
        for at, (_label, obj) in enumerate(found):
            if obj == here:
                found.insert(0, found.pop(at))
                labels = [label for label, _o in found]
                break
    # Translators: the title of the list of windows.
    dialogs.choose(labels, _('Windows'), on_chosen=chosen)


def _controls_of(window):
    from . import windowsAndActions as wa

    def work():
        found = wa.controls(window)
        if not found:
            # Translators: said when a window has no controls to list.
            _refused(_('Nothing in that window could be listed.'))
            return
        labels = []
        for row in found:
            verbs = ', '.join(name for _index, name in row['actions'])
            labels.append('%s%s' % (row['label'],
                                    (' - ' + verbs) if verbs else ''))

        def chosen(index):
            if index is None or not 0 <= index < len(found):
                return
            _control_actions_of(found[index])
        # Translators: the title of the list of controls in a window.
        dialogs.choose(labels, _('Controls'), on_chosen=chosen)
    _work(work)


def _control_actions_of(row):
    """What this control offers, plus the two things any control allows.

    Focus and the review cursor are not the control's own actions and are
    listed apart from them - a control that declares nothing can still be
    moved to, which is half of what a list like this is for.
    """
    from . import windowsAndActions as wa
    verbs = list(row['actions'])
    labels = [name for _index, name in verbs]
    # Translators: an entry in the list of what can be done with a control.
    labels.append(_('Move the keyboard here'))
    # Translators: an entry in the list of what can be done with a control.
    labels.append(_('Move the review cursor here'))

    def chosen(index):
        if index is None or index < 0:
            return
        if index < len(verbs):
            _ok, said = wa.do(row['obj'], verbs[index][0])
        elif index == len(verbs):
            _ok, said = wa.focus(row['obj'])
        else:
            _ok, said = wa.review(row['obj'])
        dialogs.report(said)
    # Translators: the title of the list of what a control can do. {what}
    # is the control.
    dialogs.choose(labels, _('{what}: what it can do').format(
        what=row['label']), on_chosen=chosen)


# --------------------------------------------------------------------------- #
# Place markers
# --------------------------------------------------------------------------- #
def mark_this():
    """Mark the control the user is on, so a key comes back to it."""
    from . import markers
    _ok, said = markers.mark()
    dialogs.report(said)


def go_to_marker():
    """This program's markers, and go to the one chosen."""
    from . import markers
    here = markers.for_program()
    if not here:
        # Translators: said when a program has no place markers.
        _refused(_('Nothing is marked in this program. Use the command for '
                   'marking this control to mark one.'))
        return
    labels = ['%d. %s' % (at + 1, row.get('name') or '')
              for at, row in enumerate(here)]

    def chosen(index):
        if index is None or not 0 <= index < len(here):
            return
        _ok, said = markers.go(here[index])
        dialogs.report(said)
    # Translators: the title of the list of place markers.
    dialogs.choose(labels, _('Place markers'), on_chosen=chosen)


def marker_number(number):
    """Go straight to this program's Nth marker - what the numbers are for."""
    from . import markers
    _ok, said = markers.go_to_number(number)
    dialogs.report(said)


def forget_marker():
    """Take one of this program's markers away."""
    from . import markers
    here = markers.for_program()
    if not here:
        # Translators: said when a program has no place markers.
        _refused(_('Nothing is marked in this program.'))
        return
    labels = ['%d. %s' % (at + 1, row.get('name') or '')
              for at, row in enumerate(here)]

    def chosen(index):
        if index is None or not 0 <= index < len(here):
            return
        markers.remove(here[index])
        # Translators: said when a place marker is forgotten.
        dialogs.report(_('Marker forgotten'))
    # Translators: the title of the list of place markers to forget.
    dialogs.choose(labels, _('Forget a marker'), on_chosen=chosen)


# --------------------------------------------------------------------------- #
# The sound scheme
# --------------------------------------------------------------------------- #
def sound_scheme():
    """Which states are answered with a sound instead of the word."""
    from . import schemes
    rows = schemes.described()
    ways = schemes.way_names()
    labels = ['%s - %s' % (row['label'], ways.get(row['way'], ''))
              for row in rows]

    def chosen(index):
        if index is None or not 0 <= index < len(rows):
            return
        _how_to_say(rows[index])
    # Translators: the title of the sound scheme manager.
    dialogs.choose(labels, _('Sound scheme'), on_chosen=chosen)


def _how_to_say(row):
    from . import schemes
    ways = schemes.way_names()
    order = [schemes.AS_WORD, schemes.AS_SOUND, schemes.AS_BOTH]
    labels = [ways[way] for way in order]
    # Translators: an entry in the sound scheme manager - hear the sound.
    labels.append(_('Hear the sound'))

    def chosen(index):
        if index is None or index < 0:
            return
        if index < len(order):
            schemes.set_way(row['state'], order[index])
            # Translators: said when a state's answer is changed. {what} is
            # the state, {how} how it will be answered.
            dialogs.report(_('{what}: {how}').format(
                what=row['label'], how=ways[order[index]]))
            return
        schemes.try_it(row['state'])
    # Translators: the title of the list of ways a state can be answered.
    # {what} is the state.
    dialogs.choose(labels, _('{what}: how to say it').format(
        what=row['label']), on_chosen=chosen)


def manager():
    """What the user has made, WALKED: markers, monitors, sounds, names.

    The dialog is still there and is still where things are EDITED - a
    voice's pitch is a slider and recording a procedure is a sequence of
    presses, and a list can be neither. What a list is good for is the
    other half, and it is the half people do far more often: seeing what
    is there. Every level carries a row that opens the form.
    """
    from . import managerWalk
    ok, said = managerWalk.open_it()
    if not ok and said:
        _refused(said)


def manager_as_a_form():
    """The one window for what the user has made, as a real dialog."""
    from . import managerGui
    if not managerGui.show():
        # Translators: said when the manager window cannot be opened.
        _refused(_('The manager needs NVDA\'s own interface.'))


# --------------------------------------------------------------------------- #
# The journal
# --------------------------------------------------------------------------- #
def read_journal():
    """Everything the reader said, newest first, and the way back to it."""
    from . import journal
    rows = journal.lines()
    if not rows:
        # Translators: said when the journal is empty.
        _refused(_('Nothing has been said yet.'))
        return
    labels = [journal.label(row) for row in rows]

    def chosen(index):
        if index is None or not 0 <= index < len(rows):
            return
        _ok, said = journal.go(rows[index])
        dialogs.report(said)
    # Translators: the title of the list of what the reader has said.
    dialogs.choose(labels, _('What was said'), on_chosen=chosen)


def search_journal():
    """Find a line in the journal, and go back to what said it."""
    from . import journal

    def asked(text):
        if not text:
            return
        rows = journal.lines(containing=text)
        if not rows:
            # Translators: said when nothing in the journal matches.
            _refused(_('Nothing said that.'))
            return
        labels = [journal.label(row) for row in rows]

        def chosen(index):
            if index is None or not 0 <= index < len(rows):
                return
            _ok, said = journal.go(rows[index])
            dialogs.report(said)
        # Translators: the title of the list of matching journal lines.
        dialogs.choose(labels, _('What was said'), on_chosen=chosen)
    # Translators: asked when searching what the reader has said.
    dialogs.ask_text(_('What was said?'), _('Search what was said'), asked)


def journal_page():
    """The journal as a page to read with the reader's own cursor."""
    from . import journal
    text = journal.as_text()
    if not text:
        # Translators: said when the journal is empty.
        _refused(_('Nothing has been said yet.'))
        return
    # Translators: the title of the page of what the reader has said.
    dialogs.browse(text, _('What was said'))


# --------------------------------------------------------------------------- #
# Procedures
# --------------------------------------------------------------------------- #
def record_procedure():
    """Start recording what the user does, or keep what was recorded."""
    from . import procedures
    if not procedures.recording():
        _ok, said = procedures.start_recording()
        dialogs.report(said)
        return

    def asked(name):
        _ok, kept = procedures.stop_recording(name or '')
        dialogs.report(kept)
    # Translators: asked when a recorded procedure is being kept.
    dialogs.ask_text(_('What should it be called?'),
                     # Translators: the title of that box.
                     _('Keep the procedure'), asked)


def cancel_procedure():
    from . import procedures
    was, said = procedures.cancel_recording()
    if not was:
        # Translators: said when nothing is being recorded.
        _refused(_('Nothing is being recorded'))
        return
    dialogs.report(said)


def run_procedure():
    """This program's procedures, and do the one chosen."""
    from . import procedures
    here = procedures.for_program()
    if not here:
        # Translators: said when a program has no recorded procedures.
        _refused(_('Nothing is recorded for this program. Use the command '
                   'for recording a procedure to make one.'))
        return
    labels = ['%s (%d)' % (row.get('name') or '', len(row.get('steps') or []))
              for row in here]

    def chosen(index):
        if index is None or not 0 <= index < len(here):
            return

        def work():
            _ok, said = procedures.run(here[index], say=dialogs.report)
            dialogs.report(said)
        _work(work)
    # Translators: the title of the list of procedures.
    dialogs.choose(labels, _('Procedures'), on_chosen=chosen)


def read_procedure():
    """Read a procedure's steps - which is what makes one checkable."""
    from . import procedures
    here = procedures.for_program()
    if not here:
        # Translators: said when a program has no recorded procedures.
        _refused(_('Nothing is recorded for this program.'))
        return
    labels = [row.get('name') or '' for row in here]

    def chosen(index):
        if index is None or not 0 <= index < len(here):
            return
        dialogs.browse(procedures.as_text(here[index]),
                       here[index].get('name') or '')
    # Translators: the title of the list of procedures to read.
    dialogs.choose(labels, _('Procedures'), on_chosen=chosen)


# --------------------------------------------------------------------------- #
# Finding a control
# --------------------------------------------------------------------------- #
def find_control(use_ai=False):
    """Find the control that DOES a thing, not the one you can name."""
    from . import findControl

    def asked(question):
        if not question:
            return

        def work():
            tier, rows, why = findControl.find(question, use_ai=use_ai)
            if not rows:
                _refused(why)
                return
            tiers = findControl.tier_names()
            labels = ['%s - %s' % (row['label'], tiers.get(tier, ''))
                      for row in rows]

            def chosen(index):
                if index is None or not 0 <= index < len(rows):
                    return
                _ok, said = findControl.go(rows[index])
                dialogs.report(said)
            if len(rows) == 1:
                _ok, said = findControl.go(rows[0])
                dialogs.report(said)
                return
            # Translators: the title of the list of controls found.
            dialogs.choose(labels, _('Found'), on_chosen=chosen)
        _work(work)
    # Translators: asked when searching for a control.
    dialogs.ask_text(_('What are you looking for?'),
                     # Translators: the title of that box.
                     _('Find a control'), asked)


def find_control_with_ai():
    find_control(use_ai=True)


def ocr_review():
    """Read this window and walk it with the arrow keys; Enter clicks."""
    from . import ocrReview

    def work():
        _on, said = ocrReview.toggle()
        dialogs.report(said)
    _work(work)


def self_test():
    """Run the add-on's own features here, in this NVDA, and say what
    happened.

    Not a substitute for the suite: it is the other kind of check. The suite
    asks whether a function returns the right thing; this asks whether the
    thing really works on this machine, with this NVDA, in the window in
    front - which is where the fault that started it lived.
    """
    from . import selftest

    def work():
        answer = selftest.run()
        # Translators: the title of the page of self-test results.
        dialogs.browse(selftest.as_text(answer), _('Does it all work?'))
    _work(work)
