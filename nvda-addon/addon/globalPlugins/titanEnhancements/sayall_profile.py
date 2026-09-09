# -*- coding: utf-8 -*-
"""A different synthesizer for reading text - through NVDA's own machinery.

Asked for as "RHVoice for reading text", and it is the one thing in the
voice table that this add-on must not implement itself.

**Why not.** Everything else a class can ask for is either a speech command
inside the utterance (pitch, rate, volume) or a whole message this add-on
speaks with a driver of its own (:func:`speaking.speak_with`). Say all is
neither. NVDA reads continuously by feeding itself: each utterance carries
`CallbackCommand`s - "say-all:lineReached", "say-all:next", "say-all:turnPage"
- and the next line is queued when the synth reports reaching them. Take the
words away to speak them somewhere else and those callbacks never fire: the
reading stops after one line. And `setSynth` mid-read cancels speech, which
ends the read.

**What NVDA already has.** `speech.sayAll.SayAllProfileTrigger` is a
`config.ProfileTrigger` whose spec is ``'sayAll'``, and NVDA's speech manager
handles a profile switch at an utterance boundary on purpose - its own
comment says it waits because "we don't want to start speaking too early
with a different synth". So the switching is written, tested and already
happening; the profile it switches to is simply empty. All this does is put
a synthesizer in it.

**The footprint is deliberately tiny.** The profile's file is written
DIRECTLY - a plain ini in NVDA's own `profiles/` folder - rather than by
activating the profile and setting values on the live configuration. That is
the difference between touching a file nobody is reading and briefly making
somebody else's settings the active ones while their reader is running: one
of those can scramble the voice they are listening with, and it is not the
one written here. The only live call is the trigger map
(`triggersToProfiles` + `saveProfileTriggers`), which is the documented way
to say which profile a trigger uses and touches nothing else.

**It is ours and it says so.** The profile is called :data:`PROFILE`, so a
user who finds it in NVDA's own Configuration Profiles dialog knows where it
came from, can see exactly what is in it, and can delete it. Nothing here
ever writes to a profile it did not create.
"""

import io
import os

from . import i18n

_ = i18n.install(globals())

#: The trigger NVDA fires while it is reading continuously.
TRIGGER = 'sayAll'

#: What the profile is called. Named, not generated: a profile somebody
#: finds in NVDA's own dialog has to be traceable to the thing that made it.
PROFILE = 'Titan: reading text'

#: The one line that says the profile is this add-on's to rewrite and to
#: remove. A profile without it is the user's own and is never touched.
MARK = '# Written by the Titan enhancements add-on (voice for reading text).'


def _config():
    try:
        import config
        return config
    except Exception:                                # noqa: BLE001
        return None


def folder():
    """Where NVDA keeps its profiles, or ''."""
    config = _config()
    if config is None:
        return ''
    for asked in ('getUserDefaultConfigPath', 'getUserConfigPath'):
        getter = getattr(config, asked, None)
        if not callable(getter):
            continue
        try:
            return os.path.join(getter(), 'profiles')
        except Exception:                            # noqa: BLE001
            continue
    return ''


def path():
    where = folder()
    return os.path.join(where, PROFILE + '.ini') if where else ''


def ours():
    """Whether the profile on disk is one we wrote. '' when there is none."""
    where = path()
    if not where or not os.path.isfile(where):
        return None
    try:
        with io.open(where, encoding='utf-8') as handle:
            return MARK in handle.read()
    except Exception:                                # noqa: BLE001
        return False


def current():
    """The synthesizer reading text is set to use, or ''."""
    where = path()
    if not where or not os.path.isfile(where):
        return ''
    try:
        with io.open(where, encoding='utf-8') as handle:
            for line in handle:
                name, _sep, value = line.partition('=')
                if name.strip() == 'synth':
                    return value.strip().strip('"')
    except Exception:                                # noqa: BLE001
        return ''
    return ''


def _write(synth, voice='', variant='', rate=None):
    """The profile, as the ini NVDA reads. Only what was asked for.

    A profile carries only the settings that differ from the base one, which
    is what makes it safe: everything not written here is whatever the user
    has, so choosing a synthesizer for reading text changes the synthesizer
    and nothing else about how they read.
    """
    where = path()
    if not where:
        return False
    lines = [MARK, '[speech]', 'synth = %s' % synth]
    settings = [('voice', voice), ('variant', variant)]
    if rate is not None:
        settings.append(('rate', str(rate)))
    inner = [(name, value) for name, value in settings if value]
    if inner:
        lines.append('\t[[%s]]' % synth)
        for name, value in inner:
            lines.append('\t%s = %s' % (name, value))
    try:
        os.makedirs(os.path.dirname(where), exist_ok=True)
        with io.open(where, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(lines) + '\n')
        return True
    except Exception:                                # noqa: BLE001
        return False


def _bind(on):
    """Say which profile the say-all trigger uses. The one live call."""
    config = _config()
    if config is None:
        return False
    try:
        conf = config.conf
        triggers = conf.triggersToProfiles
        if on:
            triggers[TRIGGER] = PROFILE
        elif triggers.get(TRIGGER) == PROFILE:
            # Only ever OUR binding. A user who has pointed say-all at a
            # profile of their own keeps it.
            triggers.pop(TRIGGER, None)
        conf.saveProfileTriggers()
        return True
    except Exception:                                # noqa: BLE001
        return False


def set_synth(synth, voice='', variant='', rate=None):
    """Read text with this synthesizer. ``(ok, sentence)``.

    An empty name takes the arrangement away again, which is what choosing
    "the one NVDA is using" means.
    """
    name = str(synth or '').strip()
    if not name:
        return clear()
    if not path():
        return False, _('NVDA has no configuration folder, so a voice for '
                        'reading text cannot be kept.')
    if ours() is False:
        return False, _('There is already a profile called "{name}" that '
                        'this add-on did not write, so it has been left '
                        'alone.').format(name=PROFILE)
    if not _write(name, voice, variant, rate):
        return False, _('The profile could not be written.')
    if not _bind(True):
        return False, _('The profile was written but NVDA would not be told '
                        'to use it for reading text.')
    return True, _('Text will be read with {synth}. NVDA does the switching '
                   'itself, through a configuration profile called "{name}" '
                   'that you can see and remove in its own Configuration '
                   'Profiles dialog.').format(synth=name, name=PROFILE)


def clear():
    """Read text with the reader's own synthesizer again."""
    _bind(False)
    where = path()
    if where and ours() and os.path.isfile(where):
        # Only a profile we wrote, and only once nothing is pointed at it.
        try:
            os.remove(where)
        except OSError:
            pass
    return True, _('Text will be read with the synthesizer NVDA is using.')
