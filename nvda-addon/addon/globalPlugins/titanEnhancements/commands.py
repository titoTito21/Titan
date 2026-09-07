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
        dialogs.report(_('Titan is not running.'))
        return

    report = panner.PANNER.report()
    able = channel.CHANNEL.capabilities()
    lines = [
        _('Connected to Titan.'),
        _('Synthesizer: {name}').format(name=report['synth'] or _('unknown')),
    ]
    if report['stream_panning']:
        lines.append(_('The voice can be placed in the stereo image.'))
    else:
        lines.append(_('The voice cannot be placed; a tone marks the position '
                       'instead.'))
        if report['problem']:
            lines.append(report['problem'])
    lines.append(_('Pitch: {pitch}. Braille: {braille}.').format(
        pitch=_('yes') if able['pitch'] else _('no'),
        braille=_('yes') if able['braille'] else _('no')))
    if focus.standing_down():
        lines.append(_('Titan Access is the reader, so this add-on is silent.'))
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
    dialogs.report(' '.join(lines))


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
    return {'hwnd': hwnd} if hwnd else {}


def ocr_read():
    dialogs.report(_('Reading the window.'))

    def read():
        ok, text = LINK.run_action('ocr', 'read_window', scope='window',
                                   **_here())
        if not ok:
            return _refused(text)
        dialogs.browse(text or _('Nothing was read.'), _('AI OCR'))
    _work(read)


def ocr_ask():
    def asked(question):
        if not str(question or '').strip():
            return
        dialogs.report(_('Asking.'))

        def read():
            ok, text = LINK.run_action('ocr', 'ask', question=question,
                                       scope='window', **_here())
            dialogs.browse(text if ok else str(text), _('AI OCR'))
        _work(read)
    dialogs.ask_text(_('What would you like to know about this window?'),
                     _('AI OCR'), asked)


def ocr_overlay():
    """Hand the window to Titan's own overlay - real controls over the real
    window, which is more than a reading can be."""
    dialogs.report(_('Opening the Titan overlay.'))
    _work(lambda: _run('ocr', 'show_overlay'))


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


def assistant_history():
    """What has been asked and answered, as a page to read."""
    def read():
        ok, data = LINK.bridge('ai.history', limit=20)
        if not ok:
            return _refused(data)
        rows = (data or {}).get('history') if isinstance(data, dict) else None
        if not rows:
            dialogs.report(_('Nothing has been asked yet.'))
            return
        lines = []
        for row in rows:
            if not isinstance(row, dict):
                lines.append(str(row))
                continue
            asked = str(row.get('question') or row.get('user') or '')
            said = str(row.get('answer') or row.get('assistant') or '')
            if asked:
                lines.append(_('You: {text}').format(text=asked))
            if said:
                lines.append(_('Titan: {text}').format(text=said))
        dialogs.browse('\n'.join(lines), _('Titan assistant'))
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
