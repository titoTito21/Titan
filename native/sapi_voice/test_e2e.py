"""
End-to-end test for Titan TTS SAPI5 voice.

Steps:
  1. Call apply_sapi_registration(True, interactive=True) - pops a UAC prompt.
  2. Start the Python named-pipe server in this process.
  3. Drive SAPI.SpVoice -> select TitanTTS -> Speak a test phrase.
  4. Dump the DLL log + pipe server log tail.

Run from repo root:
    python native/sapi_voice/test_e2e.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.tts.sapi_registration import apply_sapi_registration, is_registered
from src.tts import sapi_pipe_server


def tail(path, n=40):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        return ''.join(lines[-n:])
    except FileNotFoundError:
        return f'(no file: {path})'


def main():
    print('=== Titan TTS SAPI5 E2E test ===')
    print(f'Already registered: {is_registered()}')
    if not is_registered():
        print('Registering (UAC prompt will appear) ...')
        if not apply_sapi_registration(True, interactive=True):
            print('Registration FAILED')
            return 1
    print(f'After register: {is_registered()}')

    print('Starting Python pipe server ...')
    sapi_pipe_server.start()
    time.sleep(0.3)

    print('Driving SAPI.SpVoice ...')
    import win32com.client
    sv = win32com.client.Dispatch('SAPI.SpVoice')
    voices = sv.GetVoices()
    titan = None
    for i in range(voices.Count):
        tok = voices.Item(i)
        name = tok.GetAttribute('Name') if tok else ''
        print(f'  voice[{i}] = {name}')
        if 'Titan TTS' in (name or ''):
            titan = tok
    if titan is None:
        print('Titan TTS voice not found in enumeration!')
        return 2
    sv.Voice = titan
    print('Calling Speak("hello from titan tts") ...')
    try:
        sv.Speak('hello from titan tts')
        print('Speak returned OK')
    except Exception as e:
        print(f'Speak FAILED: {e}')

    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    dll_log = os.path.join(base, 'Titosoft', 'Titan', 'titantts_dll.log')
    pipe_log = os.path.join(base, 'Titosoft', 'Titan', 'sapi_pipe_server.log')
    print('--- DLL log tail ---')
    print(tail(dll_log))
    print('--- Pipe server log tail ---')
    print(tail(pipe_log))
    return 0


if __name__ == '__main__':
    sys.exit(main())
