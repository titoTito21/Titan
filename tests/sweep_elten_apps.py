"""Open every installed Elten application in the port, headless, with a
scripted UI double and a recording mixer, and report what each stopped on.

    C:\\Python314\\python.exe sweep_elten_apps.py [name-fragment ...]
"""
import os, sys, time, threading, json, re

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'data', 'components', 'elten_bridge'))
os.chdir(ROOT)

from eltenkit import catalogue, launcher, host, bridge, runtime, package as package_module

SECONDS = float(os.environ.get('SWEEP_SECONDS', '30'))


class RecordingSpeaker(host.Speaker):
    def _speech_module(self):
        return None

    def _messenger(self):
        return None


class FakeMixer(host.Mixer):
    """Records every sound instead of playing it. A handle is a dict."""

    def __init__(self):
        super().__init__()
        self.events = []
        self._n = 0

    def _sound_module(self):
        return None

    def _spatial_module(self):
        return None

    def _pygame_mixer(self):
        return None

    def _mode(self):
        return 'stereo'

    def start(self, path, pan=0.0, gain=1.0, loop=False, elevation=0.0, hold=False):
        self._n += 1
        handle = {'id': self._n, 'path': os.path.basename(str(path)), 'pan': pan, 'gain': gain,
                  'loop': bool(loop), 't': time.time(), 'paused': False, 'stopped': False}
        self.events.append(('start', handle['path'], round(pan, 2), round(gain, 2), bool(loop)))
        return handle

    def set_gain(self, handle, pan=0.0, gain=1.0, elevation=0.0):
        if not isinstance(handle, dict):
            return False
        handle['pan'], handle['gain'] = pan, gain
        self.events.append(('gain', handle['path'], round(pan, 2), round(gain, 2)))
        return True

    def pause(self, handle, paused=True):
        if not isinstance(handle, dict):
            return False
        handle['paused'] = bool(paused)
        self.events.append(('pause' if paused else 'resume', handle['path']))
        return True

    def frequency_of(self, path):
        return 44100

    def length_of(self, path):
        return 2.0

    def position_of(self, handle):
        if not isinstance(handle, dict):
            return 0.0
        return min(2.0, time.time() - handle['t'])

    def set_pitch(self, handle, ratio):
        if not isinstance(handle, dict):
            return False
        self.events.append(('pitch', handle['path'], round(ratio, 3)))
        return True

    def stop(self, handle):
        if not isinstance(handle, dict):
            return False
        handle['stopped'] = True
        self.events.append(('stop', handle['path']))
        return True

    def busy(self, handle):
        if not isinstance(handle, dict) or handle['stopped']:
            return False
        if handle['loop']:
            return True
        return (time.time() - handle['t']) < 2.0

    def cue(self, name, pan=0.0):
        self.events.append(('cue', name, round(pan, 2)))
        return True

    def close(self):
        self.closed = True


class ScriptedUI(object):
    """Answers every question the bridge asks the interface, and DRIVES
    what it opened: chooses rows, presses keys, escapes."""

    def __init__(self, app_name):
        self.name = app_name
        self.forms = []            # (form_id, header, specs)
        self.selects = []
        self.texts = []
        self.inputs = 0
        self.keyboards = 0
        self.menus = []
        self._next = 0
        self.application = None
        self.threads = []
        self.select_budget = 14
        self.form_budget = 14

    # -- questions -------------------------------------------------------
    def say_on_screen(self, text):
        self.texts.append(('say', text))

    def confirm(self, text, title=''):
        self.texts.append(('confirm', text))
        return True

    def select(self, rows, header='', start=None):
        self.selects.append((header, [r[1] for r in rows][:12]))
        if self.select_budget <= 0 or not rows:
            return None
        self.select_budget -= 1
        # walk the rows: first the first, then the second... a menu that
        # loops back is left by the budget running out
        index = (len(self.selects) - 1) % len(rows)
        return rows[index][0]

    def choose_path(self, *args, **kwargs):
        return None

    def display_text(self, text, header=''):
        self.texts.append(('display', (text or '')[:80]))
        return None

    def input_text(self, prompt, default='', multiline=False, password=False):
        # **Never answer a prompt.** The sweep runs against the user's own
        # applications and their own folders: a name typed into the file
        # manager's "new folder" prompt is a folder on their Desktop, and
        # text typed into its editor is saved into the file that was open.
        self.inputs += 1
        return None

    def popup_menu(self, form, control, items):
        self.menus.append([str(i.get('label', i) if isinstance(i, dict) else i)[:40] for i in (items or [])][:10])
        return None

    def focus_control(self, form, index):
        return True

    def progress(self, text):
        return None

    def set_control(self, form_id, index, changes):
        return True

    def close_form(self, form_id):
        return True

    # -- what it opened, driven --------------------------------------------
    def open_keyboard(self, application, title):
        self.keyboards += 1
        self.application = application
        self._later(0.8, self._play_keys)
        return True

    def open_form(self, application, specs, cancel=None, accept=None, header=''):
        self.application = application
        self._next += 1
        form_id = self._next
        self.forms.append((form_id, header, [(s.get('kind'), (s.get('label') or s.get('header') or '')[:30]) for s in specs]))
        if self.form_budget <= 0:
            self._later(0.3, lambda: application.send_event('control', form=form_id, control=None, name='escape'))
            return form_id
        self.form_budget -= 1
        self._later(0.6, lambda: self._drive_form(application, form_id, specs))
        return form_id

    def _drive_form(self, application, form_id, specs):
        for index, spec in enumerate(specs):
            kind = spec.get('kind')
            if kind in ('list', 'table', 'choice', 'tree', 'files'):
                application.send_event('control', form=form_id, control=index, name='changed', index=0)
                time.sleep(0.2)
                application.send_event('control', form=form_id, control=index, name='select', index=0)
                break
            if kind == 'grid':
                for key in ('key_right', 'key_down', 'key_enter', 'key_left', 'key_up', 'key_enter'):
                    application.send_event('control', form=form_id, control=index, name=key, shift=False)
                    time.sleep(0.2)
                break
            if kind == 'button':
                application.send_event('control', form=form_id, control=index, name='press')
                break
        time.sleep(2.0)
        application.send_event('control', form=form_id, control=None, name='escape')

    def _play_keys(self):
        app = self.application
        script = os.environ.get('SWEEP_KEYS')
        if script:
            for step in script.split(','):
                name, _sep, hold = step.partition(':')
                hold = float(hold or 0.2)
                if app.ended.is_set():
                    return
                if name == 'wait':
                    time.sleep(hold); continue
                app.key_down(name); time.sleep(hold); app.key_up(name); time.sleep(0.2)
            return
        for key in ('key_right', 'key_right', 'key_space', 'key_left', 'key_enter', 'a', 'd', 'key_up', 'key_down'):
            if app.ended.is_set():
                return
            app.key_down(key)
            time.sleep(0.25)
            app.key_up(key)
            time.sleep(0.25)
        time.sleep(1.5)
        for key in ('key_escape', 'key_escape', 'key_escape'):
            if app.ended.is_set():
                return
            app.key_down(key); time.sleep(0.2); app.key_up(key); time.sleep(0.6)

    def _later(self, delay, function):
        def run():
            time.sleep(delay)
            try:
                function()
            except Exception as error:
                self.texts.append(('driver-error', repr(error)))
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.threads.append(thread)


def run_one(entry):
    ui = ScriptedUI(entry.name)
    mixer = FakeMixer()
    speaker = RecordingSpeaker()
    if entry.problem:
        return {'name': entry.name, 'status': 'refused', 'detail': entry.problem}
    folder, _package = launcher.unpack(entry)
    paths = host.Paths(folder, launcher.data_root(entry), launcher.cache_dir(entry))
    paths.ensure('data'); paths.ensure('cache')
    application = bridge.Application(entry, paths, speaker=speaker, sounds=host.Sounds(mixer),
                                     translator=launcher.translator_for(folder, 'en'), ui=ui, language='en')
    application._on_gui = lambda call, default=None: call()
    started = time.time()
    application.start()
    application.ended.wait(SECONDS)
    alive = not application.ended.is_set()
    application.stop()
    log = list(application.log)
    errors = [text for level, text in log if level in ('stderr', 'bridge') and re.search(r'Error|error|raised|failed|undefined|uninitialized|wrong number|unknown', text)]
    return {
        'name': entry.name, 'status': application.status, 'detail': (application.detail or '')[:300],
        'ran_for': round(time.time() - started, 1), 'still_running': alive,
        'spoken': list(getattr(speaker, 'spoken', []))[:25],
        'forms': ui.forms[:12], 'selects': ui.selects[:8], 'keyboards': ui.keyboards,
        'menus': ui.menus[:5], 'texts': ui.texts[:10],
        'sounds': mixer.events[:40], 'sound_count': len(mixer.events),
        'errors': errors[:25], 'log_tail': [t for _l, t in log][-80:],
    }


def main():
    wanted = [w.lower() for w in sys.argv[1:]]
    entries = catalogue.discover('en', openable_only=True)
    entries = [e for e in entries if not wanted or any(w in (e.name or '').lower() or w in (e.stem or '').lower() for w in wanted)]
    out = []
    for entry in entries:
        print('==', entry.name, '(', entry.stem, ')', flush=True)
        try:
            result = run_one(entry)
        except Exception as error:
            result = {'name': entry.name, 'status': 'harness-error', 'detail': repr(error)}
        out.append(result)
        print(json.dumps(result, ensure_ascii=True, indent=1, default=str), flush=True)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sweep_results.json'), 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    main()
