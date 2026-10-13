# Run: PYTHONIOENCODING=utf-8 python tests/check_titan_access_live_reader.py [seconds] [before|after] (Windows).
# The REAL Titan Access reader, live, beside the user's own Titan: a
# temporary store set to eSpeak Polish, silent audio (SDL dummy), no
# keyboard hook. It follows the desktop's real focus for DURATION seconds;
# its worker is pinged every half second the way the supervisor does.
import sys, os, time, threading, tempfile, collections
os.environ['APPDATA'] = tempfile.mkdtemp(); os.environ['SDL_AUDIODRIVER'] = 'dummy'
REPO = os.getcwd()
sys.path.insert(0, REPO); sys.path.insert(0, os.path.join(REPO, 'data', 'components', 'titan access'))
DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 90
MODE = sys.argv[2] if len(sys.argv) > 2 else 'after'
from titan_access.settings_store import get_settings
st = get_settings()
st.set_bool('Speech', 'OwnVoice', True); st.set('Speech', 'Synthesizer', 'espeak')
st.set('Speech', 'Voice', 'pl'); st.set('Speech', 'Variant', '')
st.set_bool('General', 'MuteOutsideTCE', False); st.save()
import titan_access.keyboard_hook as hook
hook.KeyboardHook.start = lambda self: self
from src.titan_core import stereo_speech
dll = stereo_speech.get_espeak_dll()
voices_used = collections.Counter()
PHASE = ['reader alone']
real_synth = dll.synthesize_to_memory
if MODE == 'before':
    # The old library: one voice for the whole process, whoever set it last.
    stereo_speech.ESpeakDLL._apply_caller = lambda self, caller: self.pitch
def synth(text, pitch_offset=0, caller=None):
    out = real_synth(text, pitch_offset, caller=caller)
    voices_used[(PHASE[0], dll._loaded_voice or dll.voice)] += 1  # what eSpeak HAD loaded
    return out
dll.synthesize_to_memory = synth
from titan_access.engine import TitanAccessEngine
from titan_access import speech_adapter
t0 = time.time(); e = TitanAccessEngine(); e.start()
while getattr(e, 'provider', None) is None and time.time() - t0 < 60: time.sleep(0.1)
print('reader up in %.1f s; speaking with engine=%s voice=%s' % (
    time.time() - t0, getattr(e.speech._engine, 'engine', '?'),
    getattr(e.speech._engine, 'espeak_voice', '?')), flush=True)
# Titan's own speech, as it starts: its own eSpeak voice, set AFTER the
# reader chose Polish - the moment the user's Polish stopped working.
titan = stereo_speech.StereoSpeech(); titan.set_engine('espeak')
titan.set_voice([i for i, v in enumerate(titan.get_available_voices())
                 if v['id'] == 'en'][0])
print('mode %s: Titan set its own eSpeak voice to en' % MODE, flush=True)
PHASE[0] = 'after Titan set en'
e.speak('Zażółć gęślą jaźń. Czytnik ekranu mówi po polsku.')
pings = []; late = 0
end = time.time() + DURATION
while time.time() < end:
    done = threading.Event(); t = time.perf_counter()
    e.post_to_worker(done.set)
    ok = done.wait(4.0)
    pings.append(time.perf_counter() - t if ok else 4.0)
    late += (not ok)
    time.sleep(0.5)
said = speech_adapter.spoken()
pings.sort()
print('worker pings: %d, median %.1f ms, 99th %.1f ms, worst %.1f ms, unanswered in 4 s: %d' % (
    len(pings), pings[len(pings)//2]*1000, pings[int(len(pings)*.99)]*1000, pings[-1]*1000, late))
print('eSpeak syntheses by voice:', dict(voices_used))
print('utterances spoken:', len(said)); print('first/last said:', said[:1], said[-3:])
sup = e.supervisor.report() if getattr(e, 'supervisor', None) else {}
print('supervisor:', sup)
print('slow keys:', e.keyboard.slow_keys() if e.keyboard else None)
e.stop()
