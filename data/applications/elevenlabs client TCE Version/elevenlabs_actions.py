"""The ElevenLabs client's Titan actions - turning text into speech.

**None of this needs the client's window open.** Generating speech is a
capability the user has paid for, not a feature of one window: "write me a
note, then read it out in my ElevenLabs voice" must not mean opening two
applications first. A headless run finds the API key, calls the API and plays
the result.

**The key is looked for wherever the user actually put it** - this client's own
ini, or Settings -> speech -> ElevenLabs, which is where Titan's ElevenLabs
speech engine keeps it (encrypted). Reading only one of the two is how a user
looking at their key on screen gets told there is no key. A key saved *by*
these actions goes to the encrypted place.

The window is still used when it happens to be open, because then the
generation lands in the app's history and cache exactly as if the user had
typed it. That is why ``mode`` is ``any`` rather than ``live``: the open
instance when there is one, a short-lived process when there is not.

Playback is handed to a detached process on purpose. A headless action returns
as soon as it has something to say, and audio that stopped the instant the
action finished would be useless.
"""

import configparser
import os
import subprocess
import sys
import tempfile

# Titan tells us where it is (a packaged add-on runs from an extraction
# cache, so '../../..' from this file would point nowhere near Titan). The
# relative guess is the fallback for running this module by hand.
_TITAN_ROOT = os.environ.get('TITAN_ROOT') or os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if _TITAN_ROOT not in sys.path:
    sys.path.insert(0, _TITAN_ROOT)

from src.titan_core.titan_actions import fails, needs

_frame = None

SETTINGS_PATH = os.path.expandvars(
    r'%appdata%\Titosoft\Titan\Additional apps\elevenlabsclient.ini')


# --------------------------------------------------------------------------- #
# Headless: the API directly
# --------------------------------------------------------------------------- #
def _key_from_ini():
    config = configparser.ConfigParser()
    try:
        config.read(SETTINGS_PATH, encoding='utf-8')
        return (config.get('Settings', 'api_key', fallback='') or '').strip()
    except Exception:
        return ''


def _key_from_titan():
    """The key the user gave Titan's ElevenLabs *speech engine*.

    There are two honest places to put an ElevenLabs key - this client's own
    settings, and Settings -> speech -> ElevenLabs - and a user who filled in
    one of them has configured ElevenLabs. Reading only the client's ini is how
    "there is no API key" gets said to somebody looking at the key on screen.
    """
    try:
        from src.settings.settings import get_setting
        from src.titan_core.secret_store import load_value
    except Exception:
        return ''
    for key in ('engine.elevenlabs.api_key', 'elevenlabs_api_key'):
        try:
            value = str(load_value(
                get_setting(key, '', section='stereo_speech') or '')).strip()
        except Exception:
            value = ''
        if value:
            return value
    return ''


def _api_key():
    return _key_from_ini() or _key_from_titan()


def _api_client():
    """(client, error) - an ElevenLabs client from the key already configured."""
    key = _api_key()
    if not key:
        return None, ("No ElevenLabs API key is set, in the ElevenLabs "
                      "client's own settings (File, Client Settings) or in "
                      "Titan's ElevenLabs speech engine. Either fill one in, "
                      "or set it without opening anything by running the "
                      "action elevenlabs_tts_engine.set_setting with "
                      "key 'api_key'.")
    try:
        from elevenlabs import ElevenLabs
    except Exception as e:
        return None, f"The ElevenLabs library is not available: {e}"
    try:
        return ElevenLabs(api_key=key), ''
    except Exception as e:
        return None, f"Could not reach ElevenLabs: {_why(e)}"


def _why(error):
    """The readable part of an SDK exception.

    The ElevenLabs client puts the whole HTTP response - every header - in the
    exception text, which buries the one sentence that matters ("Invalid API
    key") in noise a user should never be read out.
    """
    text = str(error)
    for marker in ("'message': '", '"message": "'):
        if marker in text:
            rest = text.split(marker, 1)[1]
            return rest.split(marker[-1], 1)[0]
    return text if len(text) <= 200 else text[:200].rstrip() + '...'


def _api_voices(client):
    response = client.voices.get_all()
    voices = getattr(response, 'voices', None)
    if voices is None:
        voices = response if isinstance(response, list) else []
    return [{'name': v.name, 'id': v.voice_id} for v in voices]


def _pick(voices, name):
    """(voice, problem). An empty name takes the first voice."""
    if not voices:
        return None, fails("The ElevenLabs account has no voices.")
    wanted = str(name or '').strip().lower()
    if not wanted:
        return voices[0], None
    for voice in voices:
        if str(voice['name']).lower() == wanted:
            return voice, None
    for voice in voices:
        if wanted in str(voice['name']).lower():
            return voice, None
    return None, needs('voice', f"There is no voice called '{name}'. Which "
                       f"voice should be used?",
                       options=[v['name'] for v in voices[:12]])


def _generate(text, voice=''):
    """(mp3 bytes, voice name, problem)."""
    client, error = _api_client()
    if client is None:
        return None, '', fails(error)
    try:
        voices = _api_voices(client)
    except Exception as e:
        return None, '', fails(f"Could not list the ElevenLabs voices: {_why(e)}")
    chosen, problem = _pick(voices, voice)
    if problem is not None:
        return None, '', problem
    try:
        stream = client.text_to_speech.convert(
            text=text, voice_id=chosen['id'],
            model_id='eleven_multilingual_v2',
            output_format='mp3_44100_128')
        audio = b''.join(stream)
    except Exception as e:
        return None, '', fails(f"ElevenLabs could not generate the speech: {_why(e)}")
    if not audio:
        return None, '', fails("ElevenLabs returned no audio.")
    return audio, chosen['name'], None


def _play_detached(path):
    """Play an audio file in a process that outlives this one.

    A headless action must return as soon as it has something to say. Playing
    the audio here would either block until it finished or be cut off the
    instant the action returned, and neither is what "read it to me" means.
    """
    executable = sys.executable
    windowless = os.path.join(os.path.dirname(executable), 'pythonw.exe')
    if os.path.isfile(windowless):
        executable = windowless
    code = ("import sys, time, pygame\n"
            "pygame.mixer.init()\n"
            "pygame.mixer.music.load(sys.argv[1])\n"
            "pygame.mixer.music.play()\n"
            "while pygame.mixer.music.get_busy():\n"
            "    time.sleep(0.2)\n")
    flags = 0
    if sys.platform == 'win32':
        flags = 0x00000008 | subprocess.CREATE_NO_WINDOW    # DETACHED_PROCESS
    try:
        subprocess.Popen([executable, '-c', code, path], creationflags=flags,
                         close_fds=True)
        return True
    except Exception as e:
        print(f"[ElevenLabs] Could not start playback: {e}")
        return False


def _speak_headless(text, voice=''):
    audio, name, problem = _generate(text, voice)
    if problem is not None:
        return problem
    handle = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
    try:
        handle.write(audio)
    finally:
        handle.close()
    if not _play_detached(handle.name):
        return (f"Generated {len(text)} characters in the ElevenLabs voice "
                f"{name} and saved them to {handle.name}, but playback could "
                f"not be started.")
    return (f"Speaking {len(text)} characters in the ElevenLabs voice {name}. "
            f"The audio is at {handle.name}.")


def save_speech(text, path, voice=''):
    """Generate speech and save it as an mp3, without playing it."""
    if not str(text or '').strip():
        return needs('text', "What should be said?")
    audio, name, problem = _generate(text, voice)
    if problem is not None:
        return problem
    target = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
    if not target.lower().endswith('.mp3'):
        target += '.mp3'
    try:
        folder = os.path.dirname(target)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(target, 'wb') as handle:
            handle.write(audio)
    except OSError as e:
        return fails(f"Could not write {target}: {e}")
    return f"Saved {len(text)} characters spoken by {name} to {target}."


def get_status():
    """Whether ElevenLabs is configured, and where its key came from."""
    from_ini = _key_from_ini()
    from_titan = _key_from_titan()
    if not (from_ini or from_titan):
        return ("ElevenLabs has no API key yet, neither in the client's own "
                "settings nor in Titan's ElevenLabs speech engine. Ask the "
                "user for their key and save it with set_api_key.")
    where = ("the ElevenLabs client's settings" if from_ini
             else "Titan's ElevenLabs speech engine")
    client, error = _api_client()
    if client is None:
        return f"An API key is set (in {where}), but {error[0].lower()}{error[1:]}"
    try:
        voices = _api_voices(client)
    except Exception as e:
        return (f"An API key is set (in {where}), but ElevenLabs refused it: "
                f"{_why(e)}")
    return (f"ElevenLabs is ready: a key set in {where}, {len(voices)} voices "
            f"on the account.")


def set_api_key(key):
    """Save the user's ElevenLabs API key, encrypted.

    It goes into Titan's own settings rather than this client's ini, because
    Titan encrypts it there (DPAPI, so only this Windows account can read it)
    and the ini format is plain text. Speech generated through these actions
    reads it back from either place, so nothing is lost by preferring the safe
    one.
    """
    key = str(key or '').strip()
    if not key:
        return needs('key', "What is the ElevenLabs API key?")
    try:
        from src.settings.settings import set_setting
        from src.titan_core.secret_store import store_value
        set_setting('engine.elevenlabs.api_key',
                    store_value('api_key', key, 'password'),
                    section='stereo_speech')
    except Exception as e:
        return fails(f"Could not save the API key: {e}")
    client, error = _api_client()
    if client is None:
        return (f"The API key was saved, but it could not be used yet: "
                f"{error}")
    return ("The ElevenLabs API key is saved, encrypted so that only this "
            "Windows account can read it, and it works.")


def list_voices():
    """List the voices available in the user's ElevenLabs account."""
    if _frame is not None and getattr(_frame, 'voices', None):
        selected = _frame.voice_choice.GetSelection()
        lines = [f"- {v.get('name', '?')}"
                 + (' [selected]' if index == selected else '')
                 for index, v in enumerate(_frame.voices)]
        return f"{len(_frame.voices)} voices:\n" + "\n".join(lines)
    client, error = _api_client()
    if client is None:
        return fails(error)
    try:
        voices = _api_voices(client)
    except Exception as e:
        return fails(f"Could not list the ElevenLabs voices: {_why(e)}")
    if not voices:
        return "The ElevenLabs account has no voices."
    return (f"{len(voices)} voices:\n"
            + "\n".join(f"- {v['name']}" for v in voices))


# --------------------------------------------------------------------------- #
# The open window, when there is one
# --------------------------------------------------------------------------- #
def _select_voice(frame, name):
    wanted = str(name or '').strip().lower()
    if not wanted:
        return True, None
    for index, voice in enumerate(frame.voices or []):
        if str(voice.get('name', '')).lower() == wanted:
            frame.voice_choice.SetSelection(index)
            return True, None
    for index, voice in enumerate(frame.voices or []):
        if wanted in str(voice.get('name', '')).lower():
            frame.voice_choice.SetSelection(index)
            return True, None
    available = [v.get('name', '?') for v in (frame.voices or [])]
    return False, needs('voice', f"There is no voice called '{name}'. Which "
                        f"voice should be used?", options=available[:12])


def set_voice(name):
    """Choose which ElevenLabs voice the open client speaks with."""
    if _frame is None:
        return fails("The ElevenLabs client is not open, so there is no "
                     "selection to change. Pass 'voice' to speak instead.")
    ok, problem = _select_voice(_frame, name)
    if not ok:
        return problem
    chosen = _frame.voices[_frame.voice_choice.GetSelection()]
    return f"The ElevenLabs voice is now {chosen.get('name')}."


def speak(text, voice=''):
    """Say text in an ElevenLabs voice.

    Uses the open client when there is one, so the generation joins its history
    and cache; otherwise generates and plays it without opening anything.
    """
    if not str(text or '').strip():
        return needs('text', "What should be said?")
    if _frame is None or not getattr(_frame, 'voices', None):
        return _speak_headless(text, voice)
    ok, problem = _select_voice(_frame, voice)
    if not ok:
        return problem
    if _frame.voice_choice.GetSelection() == -1:
        _frame.voice_choice.SetSelection(0)
    _frame.text_ctrl.SetValue(text)
    _frame.Raise()
    _frame.generator.OnGenerate(None)
    chosen = _frame.voices[_frame.voice_choice.GetSelection()]
    return (f"Generating {len(text)} characters with the ElevenLabs voice "
            f"{chosen.get('name')}.")


HANDLERS = {
    'get_status': get_status,
    'set_api_key': set_api_key,
    'speak': speak,
    'save_speech': save_speech,
    'list_voices': list_voices,
    'set_voice': set_voice,
}


def attach(frame):
    """Called by main.py once the window exists."""
    global _frame
    _frame = frame
    try:
        from src.titan_core.titan_actions import serve
    except Exception as e:
        print(f"[ElevenLabs] Titan actions unavailable: {e}")
        return False
    return serve(HANDLERS, id='elevenlabs', label='ElevenLabs Client',
                 kind='app')


if __name__ == '__main__':
    from src.titan_core.titan_actions import run_cli
    sys.exit(run_cli(HANDLERS))
