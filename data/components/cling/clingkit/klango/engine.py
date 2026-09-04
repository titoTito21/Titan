# -*- coding: utf-8 -*-
"""The native engine Klango's Lua sits on: sound, keys, voice, folders, screen.

Counted across a whole Klango installation, an application's Lua stands on 197
native functions, in named families. This is what Cling supplies for each:

    _Gfx_   53   the screen. Cling does not draw, and this is the one family
                 where doing nothing is not a shortcut: Klango is an audio
                 platform, its applications are used with the monitor off, and
                 the graphics are decoration over a game that is entirely in
                 sound. They answer plausibly and paint nothing.
    _Sys_   51   the process, the files, the clock          (natives.py)
    _Snd_   17   the mixer                                  -> Cling's own
    _Inp_   16   the keyboard                               -> the surface's
    _Voice_ 13   speech                                     -> Titan's TTS
    _Dir_    7   folders

The families that are really the platform - sound, keys and voice - go to the
same places every other part of Cling uses, so an emulated application is heard
in the user's own voice, through the user's own sound theme, positioned the way
Cling positions everything.
"""

import math
import os

from . import sounds, textedit
from ..lua.runtime import LuaTable


def install(runtime, host, filesystem, keys, frames=None):
    """Put the engine families into a runtime. `keys` is the live key queue.

    `frames` is the application's own clock: a Klango sequence schedules its
    sounds ahead of time, so somebody has to start them when their moment
    comes, and the frame is where the platform already yields.
    """
    give = runtime.set_global
    table = runtime.table

    speaking = Speaking(host)
    _install_dir(give, table, filesystem)
    bank = _install_sound(give, table, host, speaking, filesystem)
    writers = textedit.Editors()
    host.klango_editors = writers
    _install_input(give, table, keys, writers)
    _install_voice(give, table, host, speaking)
    _install_resources(give, table)
    _install_graphics(give, table, writers)
    if frames is not None:
        frames.on_frame(bank.pump)
    return bank


# ---------------------------------------------------------------- folders
def _install_dir(give, table, filesystem):
    def read_all(path=None, *_rest):
        listing = table({})
        base = '/' + str(path or '').replace('\\', '/').strip('/')
        for index, leaf in enumerate(filesystem.listdir(path), start=1):
            child = (base.rstrip('/') + '/' + leaf) if base != '/' else '/' + leaf
            entry = table({})
            entry.raw_set('name', leaf)
            entry.raw_set('path', child)
            entry.raw_set('dir', filesystem.is_directory(child))
            entry.raw_set('ext', os.path.splitext(leaf)[1][1:].lower())
            listing.raw_set(index, entry)
        return listing

    # Klango walks a folder with a cursor: `ReadFirst(root)` then `ReadNext()`
    # with no argument at all, each answering FOUR values - name, whether it is
    # a directory, its size and its time. One walker, because that is what an
    # argument-less `ReadNext` means.
    walker = {'entries': [], 'position': 0}

    def entries_of(path):
        base = '/' + str(path or '').replace('\\', '/').strip('/')
        out = []
        for leaf in filesystem.listdir(path):
            child = (base.rstrip('/') + '/' + leaf) if base != '/' else '/' + leaf
            is_dir = filesystem.is_directory(child)
            real = filesystem.resolve(child)
            out.append((leaf, is_dir,
                        0 if is_dir or not real else os.path.getsize(real),
                        int(os.path.getmtime(real)) if real else 0))
        return out

    def read_first(path=None, *_rest):
        walker['entries'] = entries_of(path)
        walker['position'] = 0
        return read_next()

    def read_next(*_rest):
        if walker['position'] >= len(walker['entries']):
            return ('', False, 0, 0)
        entry = walker['entries'][walker['position']]
        walker['position'] += 1
        return entry

    def stat(path=None, *_rest):
        """`k_FileStat` - size, time and whether it is read-only.

        The library's directory listing asks for one per entry. It answers nil
        for something that is not there, which the library already handles -
        its own comment says `na /mnt stat==nil`.
        """
        real = filesystem.resolve(path)
        if not real:
            return None
        try:
            info = os.stat(real)
        except OSError:
            return None
        out = table({})
        out.raw_set('size', 0 if os.path.isdir(real) else info.st_size)
        # A time here is a TABLE, not a number: the library formats one with
        # `1900 + tab.year`, which is C's `struct tm`. Handing it a number
        # makes it index a number and stop.
        out.raw_set('modificationTime', _time_table(table, info.st_mtime))
        out.raw_set('creationTime', _time_table(table, info.st_ctime))
        out.raw_set('accessTime', _time_table(table, info.st_atime))
        out.raw_set('readonly', not os.access(real, os.W_OK))
        out.raw_set('dir', os.path.isdir(real))
        return out

    give('k_FileStat', stat)
    give('_Sys_FileStat', stat)
    give('_Dir_ReadAll', read_all)
    give('_Dir_ReadFirst', read_first)
    give('_Dir_ReadNext', read_next)
    # The library aliases these, but an application may reach for either.
    give('k_DirectoryReadFirst', read_first)
    give('k_DirectoryReadNext', read_next)
    give('_Dir_GetCurrent', lambda *_a: '/')
    give('_Dir_SetCurrent', lambda *_a: True)
    give('_Dir_AddContext', lambda *_a: True)
    give('_Dir_Create', lambda path=None, *_a: _make(filesystem, path))


def _make(filesystem, path):
    real = filesystem.resolve(path, for_writing=True)
    if not real:
        return False
    try:
        os.makedirs(real, exist_ok=True)
        return True
    except OSError:
        return False


# ------------------------------------------------------------------ sound
def _install_sound(give, table, host, speaking, filesystem=None):
    """`_Snd_*` over Cling's mixer. The engine itself is `sounds.SoundBank`.

    Klango's model is a named sample, a sound made from one (with a place, a
    pitch, a repeat count and a DELAY), a group of such sounds, and
    `_Snd_Action` to change or stop one while it plays. All of that lives in
    `sounds.py`; this is the Lua surface over it.
    """
    #: The extensions Klango's own names leave off. A sample is named
    #: `//skin/default/themes/default/t_move` and the file is `t_move.ogg`.
    #: `.txt` is last and is not a sound at all - see `sounds.Sample`.
    SOUND_EXTENSIONS = ('', '.ogg', '.wav', '.spx', '.mp3', '.txt')

    def resolve(name):
        """Where a sample really is.

        **The application's own file system comes first**, and that is most of
        it: an emulated application names its sounds the way Klango does -
        `//skin/default/themes/default/t_move`, a path inside its own package,
        with the extension left off - and asking Cling's skin reader about a
        path like that could only ever answer nothing. Every sound Mole No
        More has was found this way and none of them was played;
        `_Snd_Create` answered 0 nine times in a row and the board was silent.

        The exception is the PLATFORM's own cues - see `_titan_cue`.

        **A RELATIVE name is a path too.** Klango resolves one against the
        application's own root, and its applications rely on that: the piano
        builds every key's sample as `sounds/<model>/<key>` - out of
        `k_DirectoryRead`, whose `name` field is the file name with the
        EXTENSION TAKEN OFF (`k_SplitFileName`, `llib_files.lua`) - so a name
        with no leading slash and no extension is the ordinary case rather
        than the odd one. Asking only about absolute names is why every key
        of Klango Piano was silent.

        `host.sound_path` stays as the last answer, so an application that
        names a sound the way Cling's own engines do still gets the user's
        theme.
        """
        wanted = str(name or '')
        if not wanted:
            return ''
        cue = _titan_cue(host, wanted)
        if cue:
            return cue
        if filesystem is not None:
            for extension in SOUND_EXTENSIONS:
                real = filesystem.resolve(wanted + extension)
                if real and os.path.isfile(real):
                    return real
        return host.sound_path(wanted)

    bank = sounds.SoundBank(host, filesystem, speaking, resolve)
    host.klango_sounds = bank

    give('_Snd_Load', lambda name=None, source=None, options=None, *_a:
         bank.load(name, source, options))
    give('_Snd_Create', lambda name=None, options=None, when=None, *_a:
         bank.create(name, options, when))
    give('_Snd_Play', lambda name=None, options=None, when=None, *_a:
         bank.create(name, options, when))
    give('_Snd_Action', lambda target=None, what=None, when=None, *_a:
         bank.action(target, what, when))
    give('_Snd_Unload', lambda name=None, *_a: bank.unload(name))
    give('_Snd_UnLoadAllMySounds', lambda *_a: bank.stop_all())
    give('_Snd_IsLoaded', lambda name=None, *_a: bank.is_loaded(name))
    give('_Snd_IsPlaying', lambda target=None, *_a: bank.is_playing(target))
    give('_Snd_GetProperty', lambda name=None, what=None, *_a:
         bank.property_of(name, what))
    give('_Snd_Say', lambda text=None, *_a: host.say(str(text or '')))
    give('_Snd_MemStat', lambda *_a: 0)
    give('_Snd_GroupCreate', lambda size=None, *_a: bank.group_create(size))
    give('_Snd_GroupDestroy', lambda group=None, *_a: bank.group_destroy(group))
    give('_Snd_GroupSetActive',
         lambda group=None, *_a: bank.group_set_active(group))
    # Recording and saving are the two things a downloaded package must not do
    # unasked: one turns on the microphone, the other writes files of its own.
    for name in ('Rec_Start', 'Rec_Stop', 'Save', 'SaveOgg', 'SaveSPX'):
        give('_Snd_' + name, lambda *_a: False)
    return bank


# ------------------------------------------------------------------- keys
def _install_input(give, table, keys, editors=None):
    """`_Inp_*` - the keyboard, answered out of `keyboard.Keyboard`.

    Klango polls in four shapes at once and they are different numbers for the
    same key - a DirectInput scan code in the raw buffer and the held set, a
    Windows virtual key in the messages. `keyboard.py` is the one table that
    knows both; everything here is that object read out in Lua's shapes.

    The order matters and is Klango's own: `_k_CheckRawInput` calls `Refresh`
    first and then asks the five questions below, so `Refresh` is where a frame
    of input is taken and the rest of the frame reads a snapshot that cannot
    change underneath it.
    """
    def as_table(values):
        out = table({})
        for index, value in enumerate(values, start=1):
            out.raw_set(index, value)
        return out

    def message_table(message):
        out = table({})
        for index, value in enumerate(message, start=1):
            out.raw_set(index, value)
        return out

    def held(*_a):
        """`_Inp_KeySys_GetKeys` - scan code -> 1 held / 0 not, which the
        library counts frames off. It is a MAP, not a list
        (`for k,v in pairs(keys)`), and the zeroes are not optional: they are
        where the library clears its own count."""
        out = table({})
        for scan, state in sorted(keys.states().items()):
            out.raw_set(scan, state)
        return out

    def refresh(*_a):
        """Take a frame of input - and let the focused text control have it.

        This is where Klango's own frame reads the keyboard, and by the time
        it does, Windows has already given those keys to whichever rich edit
        had the focus. Cling has no such control, so the same thing happens
        here: `Editors.apply` types into the buffer, and the messages carry on
        to the application unchanged, because the application is told about
        every key either way.
        """
        answer = keys.refresh()
        if editors is not None:
            editors.apply(keys)
        return answer

    give('_Inp_KeySys_Refresh', refresh)
    give('_Inp_KeySys_GetKeys', held)
    give('_Inp_KeySys_GetKeyDowns', lambda *_a: as_table(keys.wmdown))
    give('_Inp_KeySys_GetKeyUps', lambda *_a: as_table(keys.wmup))
    give('_Inp_KeySys_GetSysKeyDowns', lambda *_a: as_table(keys.wmsysdown))
    give('_Inp_KeySys_GetSysKeyUps', lambda *_a: as_table(keys.wmsysup))
    give('_Inp_KeySys_GetChars', lambda *_a: as_table(keys.chars))
    give('_Inp_KeySys_GetSysChars', lambda *_a: as_table(keys.syschars))
    give('_Inp_KeySys_GetKeyMssages',
         lambda *_a: as_table([message_table(m) for m in keys.messages]))
    give('_Inp_KeySys_BuffGetCnt', lambda *_a: keys.count())
    give('_Inp_KeySys_BuffGet', lambda index=None, *_a: keys.at(index))
    give('_Inp_KeySys_SysState', lambda *_a: 0)
    give('_Inp_ReadMouse', lambda *_a: table({}))
    give('_Inp_MouseWasTouched', lambda *_a: False)
    give('_Inp_ReadGameController', lambda *_a: table({}))
    give('_Inp_GameDevWasTouched', lambda *_a: False)


#: The key a `_Voice_SpeakToStream` note carries its words in. It is what
#: makes a sample speech rather than a file - see `speak_to_stream`.
SPEECH_STREAM = '__cling_speech'


# ------------------------------------------------------------------ speech
class Speaking(object):
    """How long Titan's voice will still be saying what it was given.

    Klango asks this constantly and in two different words, and until now the
    two did not agree - `_Snd_IsPlaying` estimated a length while
    `_Voice_GetStatus` answered "still speaking" for ever, which is why every
    emulated application froze on its first spoken line: a sequence steps on
    when the thing it is playing has finished, and a voice that never finishes
    is a sequence that never reaches its second element.  The welcome splash
    was as far as Mole No More ever got.

    Titan's speech has no "am I still talking" of its own to ask - the engines
    are fire-and-forget - so the length is estimated, with the heuristic Titan
    already uses everywhere else for exactly this (`titan_access`'s speech
    adapter, `titan_talk`): `0.28 + characters / 16`.  One estimator, so a
    line is the same length whichever question is asked about it.
    """

    def __init__(self, host):
        self.host = host
        self.until = {}

    @staticmethod
    def seconds(text):
        return 0.28 + len(str(text or '')) / 16.0

    def started(self, key, text):
        self.until[key] = self.host.now() + self.seconds(text)
        return self.until[key]

    def busy(self, key):
        finish = self.until.get(key)
        return bool(finish and self.host.now() < finish)

    def finished(self, key):
        self.until.pop(key, None)

    def silence(self):
        self.until.clear()


# ------------------------------------------------------------------ voice
def _install_voice(give, table, host, speaking):
    """`_Voice_*` - Titan's own TTS, which is the whole point of running this
    inside Titan: an emulated application speaks in the voice the user chose."""
    voices = {}
    counter = [0]

    def create(spec=None, *_rest):
        """A voice handle. It must NOT be a number or a string.

        `k_VoiceSpeak(v, txt)` checks the type of its first argument: a number
        or a string means "somebody passed the text where the voice goes", and
        it re-calls itself with slot zero's voice. Returning a number from here
        therefore made every call recurse until the stack gave out - the
        library was right and the handle was wrong.
        """
        counter[0] += 1
        handle = table({})
        handle.raw_set('id', counter[0])
        handle.raw_set('name', 'Titan')
        handle.raw_set('regpath', 'titan')
        if isinstance(spec, LuaTable):
            for key in ('name', 'regpath', 'sapi'):
                value = spec.raw_get(key)
                if value not in (None, ''):
                    handle.raw_set(key, value)
        voices[counter[0]] = handle
        return handle

    def destroy(handle=None, *_rest):
        if isinstance(handle, LuaTable):
            return voices.pop(int(handle.raw_get('id') or 0), None) is not None
        return False

    def slot(voice):
        """Which voice is being talked about. There is only Titan's, but a
        handle can be asked about after it has been destroyed."""
        if isinstance(voice, LuaTable):
            return int(voice.raw_get('id') or 0)
        return 0

    def speak(voice=None, text=None, *_rest):
        """Say it in Titan's own voice - the point of running this in Titan.

        And remember for how long, because that is the only answer
        `_Voice_GetStatus` can give: `k_VoiceIsSpeaking` IS
        `_Voice_GetStatus(v) == 0`, and a platform that says it is still
        speaking for ever stops the application's whole sequence dead.
        """
        said = str(text or '')
        speaking.started(('voice', slot(voice)), said)
        return host.say(said)

    def status(voice=None, *_rest):
        """0 while speaking, 1 when finished. `k_VoiceIsSpeaking` reads it."""
        return 0 if speaking.busy(('voice', slot(voice))) else 1

    def stop(voice=None, *_rest):
        speaking.finished(('voice', slot(voice)))
        return host.stop_speech()

    def speak_to_stream(voice=None, text=None, *_rest):
        """Klango's own way of speaking, and the reason it can PLACE a voice.

        `k_VoiceSpeak` renders the line to a stream, loads that stream as a
        sample and plays it with `k_SoundPlay(playargs)` - so a spoken line
        goes through the whole sound path and gets the `pos3d`, `freq` and
        `vol` the caller asked for. Only when there is no stream does it fall
        through to `_Voice_Speak`, and Klango loses the position there too.

        Cling used to answer nil here, so every spoken line took the second
        path and came out dead centre: Dice Poker says each of its five dice
        at its own place on the table (`pos3d = {active - 3, 0.5, 0}`) and
        all five sounded like one.

        The "stream" is not audio. Titan's engines speak rather than handing
        back a buffer, so what is handed back is a note saying WHAT to say;
        `SoundBank.load` reads it and the sample becomes speech, which the
        sound layer already knows how to place.
        """
        said = str(text or '')
        if not said.strip():
            return None
        stream = table({})
        stream.raw_set(SPEECH_STREAM, said)
        stream.raw_set('voice', slot(voice))
        return stream

    give('_Voice_Create', create)
    give('_Voice_Destroy', destroy)
    give('_Voice_Speak', speak)
    give('_Voice_SpeakToStream', speak_to_stream)
    give('_Voice_SpeakToMem', lambda *_a: None)
    give('_Voice_Stop', stop)
    give('_Voice_Pause', stop)
    give('_Voice_Resume', lambda *_a: True)
    give('_Voice_SetRate', lambda *_a: True)
    give('_Voice_SetVolume', lambda *_a: True)
    give('_Voice_GetStatus', status)
    give('_Voice_GetRefs', lambda *_a: 0)
    def enumerate_voices(*_rest):
        """The voices Klango can see - which, inside Cling, is Titan's.

        The platform sorts this list, filters it by LANGUAGE
        (`k_VoiceEnum(lang, fulllang)` in `llib_sapi.lua`, which compares
        `v.lang`) and picks a slot from it before any application runs. An
        empty answer is not a degraded voice: `setSynth` calls
        `killklangobecauseoflang()` and the application is over.

        So Cling offers the same voice - Titan's, always - once for every
        language the platform can ask about: the one Titan is running in, the
        one the application's own texts are in, and English, which is the
        library's own fallback. Each gets a `regpath` of its own because that
        is what the platform remembers a choice by; behind all of them is the
        user's own engine, rate and voice, because that is what Cling speaks
        through whatever the text.
        """
        wanted = []
        for code in (host.locale,
                     (host.texts.locale if host.texts else ''), 'en-us'):
            language, _sep, country = str(code or '').partition('-')
            language = language.lower()
            if not language or language in [pair[0] for pair in wanted]:
                continue
            wanted.append((language, (country or language).lower()))
        out = table({})
        for index, (language, country) in enumerate(wanted, start=1):
            voice = table({})
            voice.raw_set('name', 'Titan (%s)' % language)
            voice.raw_set('vendor', 'Titan')
            voice.raw_set('regpath', 'titan:%s' % language)
            voice.raw_set('id', index)
            voice.raw_set('lang', language)
            voice.raw_set('sublang', country)
            voice.raw_set('gender', 0)
            voice.raw_set('age', 0)
            out.raw_set(index, voice)
        return out

    give('_Voice_Enum', enumerate_voices)


# --------------------------------------------------------------- the screen
#: Every `_Gfx_` name a Klango installation calls. They answer and paint
#: nothing: Klango's applications are used with the monitor off, and the
#: drawing is decoration over a game that is entirely in sound. A window that
#: is never shown is not a missing feature here - it is the platform's own
#: "no graphics" mode, which Klango itself ships (`klangonogfx.bat`).
GRAPHICS = (
    'AddRegion', 'BlockWMPAINT', 'Clear', 'FitRectToContent', 'GetFontSize',
    'GetPicSize', 'GetTextColor', 'GetWindowSize', 'HardcoreCommit', 'Load',
    'PutLine', 'PutPic', 'PutRTEdit', 'PutRTInRect', 'PutRect', 'PutText',
    'PutTextInRect', 'PutText_', 'SetBkgColor', 'SetBkgGfx', 'SetDialog',
    'SetDialogRect', 'SetFont', 'SetRegion', 'SetTextColor',
    'SetTopLevelDialog', 'TxtEdit_BlockInput', 'TxtEdit_BlockPaint',
    'TxtEdit_Clipboard', 'TxtEdit_Destroy', 'TxtEdit_Fill', 'TxtEdit_Create',
    'TxtEdit_GetText', 'TxtEdit_SetText', 'TxtEdit_Show', 'Unload',
    'GetScreenSize', 'Commit', 'Flip', 'SetMode', 'SetClip', 'ResetClip',
    'PutPicEx', 'MeasureText', 'SetAlpha', 'PushState', 'PopState',
    'CreateSurface', 'DestroySurface', 'DrawSurface', 'SetCaption',
    'ShowCursor', 'SetIcon', 'Screenshot',
)


def _sample_name(value):
    """The name of a sample, however Klango happened to pass it."""
    if isinstance(value, str):
        return value
    if isinstance(value, LuaTable):
        for key in ('name', 'file', '___name', 1):
            inner = value.raw_get(key)
            if isinstance(inner, str):
                return inner
    return '' if value is None else str(value)


def _time_table(table, when):
    """A moment as Klango reads one: C's `struct tm`, years since 1900."""
    import time as _time

    parts = _time.localtime(when)
    out = table({})
    out.raw_set('year', parts.tm_year - 1900)
    out.raw_set('mon', parts.tm_mon)
    out.raw_set('mday', parts.tm_mday)
    out.raw_set('hour', parts.tm_hour)
    out.raw_set('min', parts.tm_min)
    out.raw_set('sec', parts.tm_sec)
    out.raw_set('wday', parts.tm_wday)
    out.raw_set('yday', parts.tm_yday)
    return out


def _install_resources(give, table):
    """`_Res_*` - Klango's resource slots, which the screen layer swaps between
    while it loads pictures. Cling loads no pictures, so a slot is a number."""
    active = [1]
    counter = [1]

    def free_id(*_a):
        counter[0] += 1
        return counter[0]

    def set_active(identifier=None, *_a):
        previous = active[0]
        if identifier is not None:
            active[0] = int(identifier)
        return previous

    give('_Res_GetFreeId', free_id)
    give('_Res_SetActiveId', set_active)
    give('_Res_UnLoadId', lambda *_a: True)


def _install_graphics(give, table, editors=None):
    def size(*_a):
        return 1024, 768

    for name in GRAPHICS:
        give('_Gfx_' + name, lambda *_a: True)
    _install_text_edit(give, table, editors)
    give('_Gfx_GetWindowSize', size)
    give('_Gfx_GetScreenSize', size)
    give('_Gfx_GetPicSize', lambda *_a: (0, 0))
    give('_Gfx_GetFontSize', lambda *_a: 16)
    give('_Gfx_FitRectToContent', lambda *_a: (0, 0, 0, 0))

    # The few graphics calls whose ANSWER is used rather than just made: a
    # colour is read back and shaded arithmetically, and a converted string is
    # concatenated - so `true` is not an answer to either.
    give('_Gfx_GetTextColor', lambda *_a: (255, 255, 255))
    give('_Gfx_GetBkgColor', lambda *_a: (0, 0, 0))

    def utf8_to_rtf(text=None, *_rest):
        """RTF is what Klango draws text with. Nothing is drawn here, so
        escaping the three characters that would break the markup is all of
        it - and it must come back a STRING, because it is concatenated."""
        out = str(text or '')
        out = out.replace(chr(92), chr(92) * 2)
        out = out.replace('{', chr(92) + '{').replace('}', chr(92) + '}')
        return out

    give('_Gfx_Utf8ToRTF', utf8_to_rtf)
    give('_Gfx_RTFToUtf8', lambda text=None, *_a: _rtf_to_text(text))


def _placement(options, sample=None):
    """Where Klango asked for a sound to be, in the units Titan takes.

    Klango's own words, all of them read off real applications:

    - `pos3d = {x, y, z}` is a place in FRONT of the listener, in the same
      units a topology uses - Mole No More's board runs from x -0.8 to 0.8 at
      y 0.25 to 1.1, so the angle is `atan2(x, y)` and the distance is what
      makes the far row quieter. This is what tells one hole from another,
      and it was being ignored: every sound on the board came out of the
      middle, which for a game aimed at by ear is the game not working.
    - `freq` is a pitch shift in hundredths of a semitone. Klango's boards use
      it for the ROWS (0, -100, -200 in `3x3.top`), so without it a grid is
      heard as a line.
    - `replay = -1` is Klango's "keep playing" - background music and a
      dialog's own bed. `loop` is the same thing said the other way.
    - `pan`, `vol` / `volMul` are the flat ones, for a sound that is not on a
      board at all.
    """
    place = {'pan': 0.0, 'elevation': 0.0, 'gain': 1.0, 'cents': 0.0,
             'loop': False, 'repeats': 0, 'at': None, 'to': None,
             'seconds': 0.0, 'velocity': None}
    if not isinstance(options, LuaTable):
        return place

    vector = _vector3(options.raw_get('pos3d'))
    if vector is not None:
        x, y, z = vector
        place['pan'] = _pan_of(x, y)
        place['elevation'] = _elevation_of(x, y, z)
        place['gain'] = _distance_gain(x, y, z, sample)
        place['at'] = (x, y, z)

    for key in ('pan',):
        value = options.raw_get(key)
        if value is not None:
            place['pan'] = max(-1.0, min(1.0, _number(value)))
    for key in ('vol', 'volMul'):
        value = options.raw_get(key)
        if value is not None:
            place['gain'] *= max(0.0, min(1.0, _number(value)))
    frequency = options.raw_get('freq')
    if frequency is not None:
        place['cents'] = _number(frequency)
    # `play` is how many times MORE to play it, which is exactly pygame's
    # `loops`: 0 once, -1 for ever, n for n+1 times. `k_SoundPlay` writes it
    # out of `replay`, and an application that calls `_Snd_Create` itself
    # writes `play` directly - Mole No More's board does.
    for key in ('play', 'replay'):
        value = options.raw_get(key)
        if value is None:
            continue
        count = int(_number(value))
        if count < 0:
            place['loop'] = True
        else:
            place['repeats'] = count
    if options.raw_get('loop'):
        place['loop'] = True

    # `pos3dSlide = {x1,y1,z1, x2,y2,z2, seconds}` - a sound that TRAVELS.
    # Skeet's clay pigeon is thrown from twenty units to the left and flies
    # to twenty on the right while it is in the air, and the whole game is
    # aiming at where it has got to; ignoring the slide left every disc
    # sitting still at the point it was thrown from.
    # `vel3d` is how fast it is moving, and Klango hands it over so the
    # engine can do the Doppler shift itself - Skeet works the vector out
    # explicitly (`x_d = 40/tile_f`) and gives it to the clay pigeon, so the
    # disc's pitch really rises as it comes at you and falls as it goes.
    moving = _vector3(options.raw_get('vel3d'))
    if moving is not None and any(moving):
        place['velocity'] = moving
    slide = options.raw_get('pos3dSlide')
    if isinstance(slide, LuaTable):
        numbers = [_number(slide.raw_get(index)) for index in range(1, 8)]
        if len(numbers) >= 6:
            place['at'] = tuple(numbers[0:3])
            place['to'] = tuple(numbers[3:6])
            place['seconds'] = numbers[6] if len(numbers) > 6 else 0.0
            place['pan'] = _pan_of(place['at'][0], place['at'][1])
            place['gain'] = _distance_gain(*place['at'], sample=sample)
            place['elevation'] = _elevation_of(*place['at'])
    return place


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _vector3(value):
    """A place, written either of the two ways Klango writes one.

    An application says `pos3d = {-20, 2, 0}` and the platform library says
    `pos3d = {x = -1, y = 0.5, z = 0}` - the same thing, and Klango's engine
    takes both. Reading only the array is why every menu was heard dead
    centre: `menu:recalcpositions` lays a menu's items out from -60 to +60
    degrees at a distance of 1 (`LLib_Math_AngleDist_To_3dPos`, which returns
    a NAMED table), so moving through a Klango menu moves the sound across
    the listener, and reading nothing out of it put the whole interface -
    menus, the help channel at `{x=-1, y=0.5}`, the information channel at
    `{x=0.5, y=0.5}`, a forum post at its author's place, and every ambient
    sound `k_BackgroundPrepare` scatters around the listener - in one spot in
    the middle.
    """
    if not isinstance(value, LuaTable):
        return None
    x = value.raw_get(1)
    if x is None and value.raw_get('x') is None:
        return None
    if x is None:
        return (_number(value.raw_get('x')),
                _number(value.raw_get('y')),
                _number(value.raw_get('z')))
    return (_number(x), _number(value.raw_get(2)), _number(value.raw_get(3)))


def _pan_of(x, y):
    """A place in front of the listener as a pan of -1 (left) to 1 (right)."""
    if not x and not y:
        return 0.0
    # `y` is how far away it is, `x` how far to the side; a field beside the
    # listener's ear (y at or below zero) is hard over rather than behind,
    # because two speakers cannot say "behind" and pretending otherwise puts
    # the far side of a board in the middle.
    return max(-1.0, min(1.0, math.sin(math.atan2(x, max(y, 0.05)))))


def _elevation_of(x, y, z):
    """A place in front of the listener as an elevation in degrees.

    It is its own function because a sound that TRAVELS moves in three axes,
    not two: a `pos3dSlide` is re-placed at every frame of its flight, and
    computing the pan and the gain there while leaving the height at wherever
    the sound was thrown from is the same mistake as not moving it at all,
    one axis smaller.
    """
    if not (x or y or z):
        return 0.0
    return math.degrees(math.atan2(z, math.hypot(x, y)))


#: What a sample is given when it never said. Klango prepares a placed sound
#: with `dmin = 1, dmax = 3`, and that is what the platform's own speech uses.
NEAR = 1.0
FAR = 3.0


def _distance_gain(x, y, z, sample=None):
    """OpenAL's clamped inverse-distance law, with the SAMPLE's own figures.

    `dmin` is how close a sound has to be to be at full volume and `dmax` how
    far away it stops getting quieter, and they are set when the sample is
    prepared: Skeet's clay pigeon is `1, 10` and is thrown from twenty units
    away, the platform's speech is `1, 3`. One figure for both makes a wide
    board sound flat.
    """
    near = getattr(sample, 'near', NEAR) or NEAR
    far = getattr(sample, 'far', FAR) or FAR
    distance = math.sqrt(x * x + y * y + z * z)
    distance = max(near, min(far, distance))
    return max(0.0, min(1.0, near / distance))


# ------------------------------------------------------- the platform's cues
#: What Klango's own interface sounds are, in Titan's words. Moving through a
#: menu, choosing something, reaching the end of a list, a dialog opening: an
#: emulated application makes exactly the same noises Titan makes for exactly
#: the same things, and it should make TITAN's - the user chose a sound theme
#: and this is their desktop. What is deliberately not here is anything of the
#: APPLICATION's own (`//skin/default/themes/...`): a mole's hello is the game,
#: not the interface, and Titan has nothing to say about it.
#:
#: A name Titan's theme has not got falls through to Klango's own file, so
#: nothing is ever lost by mapping one.
TITAN_CUES = {
    # moving onto something
    'menumain_norm': 'core/FOCUS.ogg',
    'menumain_sub': 'core/FOCUS.ogg',
    'menudia_norm': 'core/FOCUS.ogg',
    'menudia_sub': 'core/FOCUS.ogg',
    'coll_marker': 'core/FOCUS.ogg',
    'form_marker': 'core/FOCUS.ogg',
    'info_marker': 'core/FOCUS.ogg',
    'button_marker': 'core/FOCUS.ogg',
    'textarea_marker': 'core/FOCUS.ogg',
    'editline_marker': 'core/FOCUS.ogg',
    'prompter_marker': 'core/FOCUS.ogg',
    'filelist_marker': 'core/FOCUS.ogg',
    'filelist_filemarker': 'core/FOCUS.ogg',
    'filelist_dirmarker': 'core/FOCUS.ogg',
    # choosing it
    'button_onclick': 'core/SELECT.ogg',
    'coll_activeitem': 'core/SELECT.ogg',
    'activate_beep': 'core/SELECT.ogg',
    'filelist_direnter': 'core/SELECT.ogg',
    # the end of a list, and going wrong
    'end': 'ui/endoflist.ogg',
    'error': 'core/error.ogg',
    # windows opening and closing
    '_open_menu': 'ui/contextmenu.ogg',
    '_close_menu': 'ui/contextmenuclose.ogg',
    '_open_dialog': 'ui/dialog.ogg',
    '_close_dialog': 'ui/dialogclose.ogg',
    '_open_splash': 'ui/popup.ogg',
    '_close_splash': 'ui/popupclose.ogg',
    '_open_help': 'ui/tui_open.ogg',
    '_close_help': 'ui/tui_close.ogg',
    # a category or a channel changing
    'channel_switch': 'ui/switch_category.ogg',
    'channel_close': 'ui/uiclose.ogg',
}

#: Where in the virtual file system the platform's own sounds live. Only
#: these are answered with Titan's; an application's own are its own.
LIBRARY_SKIN = '/llib/skin/'


def _titan_cue(host, wanted):
    """Titan's own sound for one of Klango's interface cues, or ''."""
    if not wanted.startswith(LIBRARY_SKIN):
        return ''
    leaf = wanted.rsplit('/', 1)[-1]
    leaf = leaf.rsplit('.', 1)[0] if '.' in leaf else leaf
    titan = TITAN_CUES.get(leaf)
    if not titan:
        return ''
    try:
        return host.sound_path(titan)
    except Exception:
        return ''


# --------------------------------------------------------- the text control
def _install_text_edit(give, table, editors):
    """`_Gfx_TxtEdit_*` - see `textedit.py`.

    The one part of `_Gfx_` that is not decoration: it is where a search
    term, a message or a name is typed. Answering nothing here is how the
    Wikipedia browser, the chat and every application with a field ended -
    `attempt to call a nil value '_Gfx_TxtEdit_Init'`.
    """
    from . import textedit

    if editors is None:
        editors = textedit.Editors()

    def initialise(options=None, *_rest):
        spec = {}
        if isinstance(options, LuaTable):
            for key, into in (('multiline', 'multiline'), ('rich', 'rich'),
                              ('readonly', 'readonly'),
                              ('password', 'password')):
                spec[into] = bool(options.raw_get(key))
            for key, into in (('fontsize', 'fontsize'), ('maxlen', 'maxlen')):
                value = options.raw_get(key)
                if value is not None:
                    try:
                        spec[into] = int(value)
                    except (TypeError, ValueError):
                        pass
        return editors.create(**spec).id

    def with_editor(action, answer=None):
        def call(handle=None, *arguments):
            editor = editors.get(handle)
            if editor is None:
                return answer
            return action(editor, *arguments)
        return call

    def current_pos(editor):
        # TWO values: the library reads `sel[2]-sel[1]` to find out whether
        # anything is selected.
        start, end = editor.selection
        return (start, end)

    def set_current_pos(editor, start=None, end=None, *_rest):
        editor.set_range(start if start is not None else 0, end)
        return True

    def find(editor, needle=None, start=None, forward=True, *_rest):
        found = editor.find(needle, start, bool(forward) if forward is not None
                            else True)
        return found

    give('_Gfx_TxtEdit_Init', initialise)
    give('_Gfx_TxtEdit_Destroy', lambda handle=None, *_a: editors.destroy(handle))
    def set_focus(handle=None, take=None, *_rest):
        # Klango's second argument: 1 takes the keyboard, 0 gives it up. A
        # call with no flag at all is "take it", which is what one reads as.
        return editors.focus(handle, True if take is None else bool(take))

    give('_Gfx_TxtEdit_SetFocus', set_focus)
    give('_Gfx_TxtEdit_HasFocus',
         with_editor(lambda editor, *_a: bool(editor.focused), False))
    give('_Gfx_TxtEdit_GetText',
         with_editor(lambda editor, mode=None, *_a: editor.get_text(
             4 if mode is None else mode), ''))
    give('_Gfx_TxtEdit_SetText',
         with_editor(lambda editor, text=None, *_a: editor.set_text(text),
                     False))
    def set_rich_text(editor, text=None, *_rest):
        """`SetText2` is the RICH one: what it is handed is RTF.

        Klango's control renders the markup and `GetText` then answers the
        words; Cling's is a buffer, so the markup is turned into words here.
        Storing it as it arrives is what made a text browser read
        `rtf1 ansi ansicpg1252 colortbl red255 green255 blue255` aloud before
        a word of the article.
        """
        return editor.set_text(_rtf_to_text(text))

    give('_Gfx_TxtEdit_SetText2', with_editor(set_rich_text, False))
    give('_Gfx_TxtEdit_GetTextRange',
         with_editor(lambda editor, start=0, end=0, *_a:
                     editor.text_range(start, end), ''))
    give('_Gfx_TxtEdit_GetCurrentPos', with_editor(current_pos, (0, 0)))
    give('_Gfx_TxtEdit_SetCurrentPos', with_editor(set_current_pos, False))
    give('_Gfx_TxtEdit_GetCaretPos',
         with_editor(lambda editor, *_a: editor.caret, 0))
    def current_line(editor, position=None, from_caret=False, *_rest):
        """TWO values: the line's text, and WHICH line it is, from zero.

        `_playline` reads the first (`local txt = ...`); the textarea's Up and
        Down read the second (`local _, l = ...`) to find out whether the
        caret has reached the top or the bottom, and buzz when it has.
        Answering one value left `l` nil, so a multiline field never said it
        had stopped.

        The caller is usually `GetCurrentLine(handle, GetCurrentPos(handle))`,
        and `GetCurrentPos` answers a PAIR - so `from_caret` arrives holding
        the end of the selection rather than a flag. That is Klango's own
        shape and it is why `position` is what the line is looked up by.
        """
        where = editor.caret if position is None else position
        return (editor.current_line(position, bool(from_caret)),
                editor.line_index(where))

    give('_Gfx_TxtEdit_GetCurrentLine', with_editor(current_line, ('', 0)))
    give('_Gfx_TxtEdit_GetLength',
         with_editor(lambda editor, *_a: len(editor.text), 0))
    give('_Gfx_TxtEdit_GetNumberOfLines',
         with_editor(lambda editor, *_a: editor.lines(), 0))
    give('_Gfx_TxtEdit_Find', with_editor(find, None))
    give('_Gfx_TxtEdit_ReplaceSel',
         with_editor(lambda editor, text=None, *_a:
                     editor.replace_selection(text), False))
    give('_Gfx_TxtEdit_SetLimit',
         with_editor(lambda editor, limit=-1, *_a: (
             setattr(editor, 'limit', int(limit or -1)), True)[-1], False))
    give('_Gfx_TxtEdit_GetDelZnak',
         with_editor(lambda editor, *_a: editor.deleted, ''))
    give('_Gfx_TxtEdit_attheendofline',
         with_editor(lambda editor, *_a: editor.at_end_of_line(), True))
    give('_Gfx_TxtEdit_GetFontSize',
         with_editor(lambda editor, *_a: editor.fontsize, 16))
    give('_Gfx_TxtEdit_BlockInput',
         with_editor(lambda editor, blocked=True, *_a: (
             setattr(editor, 'blocked', bool(blocked)), True)[-1], False))
    # Painting, key filtering and the clipboard are the parts of a rich edit
    # that belong to a screen and a desktop, and Cling has neither: the
    # control is a buffer, every key it is given it acts on, and nothing is
    # drawn. They answer so the library carries on.
    give('_Gfx_TxtEdit_BlockPaint', lambda *_a: True)
    give('_Gfx_TxtEdit_FilterKeys', lambda *_a: True)
    give('_Gfx_TxtEdit_Clipboard', lambda *_a: True)
    give('_Gfx_TxtEdit_GetMaxTexts', lambda *_a: 0)

    def load_file(handle=None, path=None, _kind=None, *_rest):
        """`LoadFile` is how a text browser is filled - the file is the
        document. It is answered by the caller's own file system, which the
        library has already turned into a real path."""
        editor = editors.get(handle)
        if editor is None or not path:
            return False
        try:
            with open(str(path), 'rb') as handle_file:
                loaded = handle_file.read().decode('utf-8', 'replace')
        except OSError:
            return False
        # Klango's second argument says which: 1 is plain text, 2 is RTF.
        # `set_text` is what puts the control's own line separator in.
        return editor.set_text(_rtf_to_text(loaded) if str(_kind) == '2'
                               else loaded)

    give('_Gfx_TxtEdit_LoadFile', load_file)


# --------------------------------------------------------------------- RTF
#: Groups whose CONTENT is not text at all - the colour table, the fonts, the
#: generator's name - and which are dropped whole rather than read out.
RTF_SILENT_GROUPS = ('fonttbl', 'colortbl', 'stylesheet', 'info', 'generator',
                     'pict', 'themedata', 'datastore', '*')


def _rtf_to_text(value=None):
    """`_Gfx_RTFToUtf8` - the words in an RTF document.

    Klango composes its formatted text as RTF and asks the engine for the
    plain text back to SPEAK. Answering the RTF unchanged, which is what
    `str(text)` did, reads the markup out loud: a screen reader user hears
    `rtf1 ansi ansicpg1252 colortbl red255 green255 blue255` before a word of
    the article. This is the small reader that turns one back into words -
    enough of RTF to read what Klango writes with it, and no more.
    """
    text = str(value or '')
    if '\\rtf' not in text[:64]:
        return text                          # not RTF at all; leave it alone
    out = []
    index, length, depth = 0, len(text), 0
    #: The depth at which a silent group started, or None.
    silent = None
    while index < length:
        character = text[index]
        if character == '{':
            depth += 1
            index += 1
            continue
        if character == '}':
            if silent is not None and depth <= silent:
                silent = None
            depth -= 1
            index += 1
            continue
        if character == '\\':
            index, word, parameter = _rtf_word(text, index)
            if silent is not None:
                continue
            if word in RTF_SILENT_GROUPS:
                silent = depth
                continue
            if word in ('par', 'line', 'sect'):
                out.append('\n')
            elif word == 'tab':
                out.append('\t')
            elif word == 'u' and parameter is not None:
                out.append(chr(parameter % 65536))
                # `\uN` is followed by a replacement character to skip.
                if index < length and text[index] not in '\\{}':
                    index += 1
            elif word == "'" and parameter is not None:
                out.append(chr(parameter))
            continue
        if silent is None and character not in '\r\n':
            out.append(character)
        index += 1
    return ''.join(out).strip()


def _rtf_word(text, index):
    """One `\\control` word, its optional number, and where it ended."""
    index += 1                                            # past the backslash
    if index >= len(text):
        return index, '', None
    character = text[index]
    if character == "'":
        digits = text[index + 1:index + 3]
        try:
            return index + 3, "'", int(digits, 16)
        except ValueError:
            return index + 1, "'", None
    if not character.isalpha():
        # An escaped brace or backslash is the character itself.
        return index + 1, '', None
    start = index
    while index < len(text) and text[index].isalpha():
        index += 1
    word = text[start:index]
    number = ''
    if index < len(text) and (text[index] == '-' or text[index].isdigit()):
        start = index
        index += 1
        while index < len(text) and text[index].isdigit():
            index += 1
        number = text[start:index]
    if index < len(text) and text[index] == ' ':
        index += 1                          # the space that ends a control word
    try:
        return index, word, int(number) if number else None
    except ValueError:
        return index, word, None
