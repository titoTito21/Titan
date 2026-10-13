# Run: python tests/check_titan_access_worker_stalls.py before|after (Windows).
# The REAL reader engine: 200 container focus events go through the worker's
# own _announce_focus while four busy threads compete for the GIL; the worker
# is timed per event. "before" puts back the old line (a threading.Timer per
# event); "after" is the shared scheduler. Speech is replaced by a recorder,
# the keyboard hook is not installed, the store is a temporary copy.
import sys, os, time, threading, tempfile
os.environ['APPDATA'] = tempfile.mkdtemp(); os.environ['SDL_AUDIODRIVER'] = 'dummy'
sys.path.insert(0, os.getcwd()); sys.path.insert(0, os.path.join(os.getcwd(), 'data', 'components', 'titan access'))
import titan_access.keyboard_hook as hook
hook.KeyboardHook.start = lambda self: self
from titan_access import engine as eng_mod, later
from titan_access.contracts import AccessibleObject
mode = sys.argv[1]
if mode == 'before':
    eng_mod.later = type('Old', (), {'call_later': staticmethod(
        lambda d, f: threading.Timer(d, f).start())})
e = eng_mod.TitanAccessEngine(); e.start()
deadline = time.time() + 30
while getattr(e, 'provider', None) is None and time.time() < deadline:
    time.sleep(0.1)
e.announce_object = lambda *a, **k: None          # say nothing
stop = False
def busy():
    x = 0
    while not stop:
        for i in range(20000): x += i
for _ in range(4): threading.Thread(target=busy, daemon=True).start()
took = []
done = threading.Event()
def one(n):
    obj = AccessibleObject(name='Panel %d' % n, role='pane', bounds=(n, 0, n + 10, 10))
    t = time.perf_counter(); e._announce_focus(obj); took.append(time.perf_counter() - t)
    if n == 199: done.set()
for n in range(200):
    e.post_to_worker(lambda n=n: one(n)); time.sleep(0.01)
done.wait(120); stop = True
took.sort()
print('%-6s worker per focus event: median %.2f ms, 95th %.1f ms, worst %.1f ms, over 100 ms: %d of %d'
      % (mode, took[len(took)//2]*1000, took[int(len(took)*.95)]*1000, took[-1]*1000,
         sum(1 for x in took if x > 0.1), len(took)))
e.stop()
