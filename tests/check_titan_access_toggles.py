# -*- coding: utf-8 -*-
"""Reproduce "Titan hangs when the reader / touch gestures are switched".

    python tests/check_titan_access_toggles.py [hotkey] [settings] [rapid] [trackpad] [ao3]

Windows; it starts the REAL reader (its keyboard hook hears your keys while
it runs) on a copy of your stores.

A wx app shaped like Titan (frame + focused list on the main thread's
MainLoop), the real Titan Access component initialised as the component
manager does, then scenarios driven from a thread while a watchdog pings
the GUI thread and dumps every thread's stack when it stalls.
"""
import os, sys, shutil, tempfile, threading, time, traceback, importlib.util

TITAN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENT = os.path.join(TITAN, "data", "components", "titan access")
base = os.getenv("APPDATA")
src = os.path.join(base, "titosoft", "Titan")
tgt = tempfile.mkdtemp(prefix="ta_hang_")
for name in ("screenreader", "accessibility", "bg5settings.ini"):
    p = os.path.join(src, name)
    d = os.path.join(tgt, "titosoft", "Titan", name)
    if os.path.isdir(p):
        shutil.copytree(p, d, ignore=shutil.ignore_patterns("*.log", "pkg_cache", "nvda_addons"))
    elif os.path.isfile(p):
        os.makedirs(os.path.dirname(d), exist_ok=True); shutil.copy(p, d)
os.environ["APPDATA"] = tgt
os.chdir(TITAN)
sys.path.insert(0, TITAN)

import wx

SCEN = sys.argv[1:] or ["hotkey", "settings", "trackpad"]
stalls = []

def dump(tag):
    frames = sys._current_frames()
    out = ["==== STALL %s ====" % tag]
    for t in threading.enumerate():
        f = frames.get(t.ident)
        if f is None:
            continue
        out.append("-- %s" % t.name)
        out.extend(l.rstrip() for l in traceback.format_stack(f)[-14:] if t is threading.main_thread() or t.name.startswith("TitanAccess") or t.name.startswith("Titan"))
    text = "\n".join(out)
    stalls.append(text)
    print(text, flush=True)

class Watch(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True); self.stop = False; self.worst = 0
    def run(self):
        while not self.stop:
            ev = threading.Event(); t0 = time.time()
            wx.CallAfter(ev.set)
            dumped = False
            while not ev.wait(0.1):
                if not dumped and time.time() - t0 > 2.0:
                    dump("gui %.1fs" % (time.time() - t0)); dumped = True
                if time.time() - t0 > 60:
                    print("GUI DEAD"); os._exit(3)
            self.worst = max(self.worst, time.time() - t0)
            time.sleep(0.2)

def load_component():
    spec = importlib.util.spec_from_file_location("titan access", os.path.join(COMPONENT, "init.py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules["titan access"] = m
    spec.loader.exec_module(m)
    return m

def timed(label, fn, limit=12):
    t0 = time.time(); box = {}
    def run():
        try: box["r"] = fn()
        except Exception as e: box["e"] = e
    th = threading.Thread(target=run, daemon=True); th.start(); th.join(limit)
    dt = time.time() - t0
    if th.is_alive():
        dump("%s still running after %ds" % (label, limit))
        th.join(30)
    print("%-40s %.2fs %s" % (label, dt, box.get("e", "")), flush=True)
    return dt

def on_gui(fn):
    done = threading.Event(); box = {}
    def call():
        try: box["r"] = fn()
        finally: done.set()
    wx.CallAfter(call); done.wait(40)
    return box.get("r")

def driver(comp, watch):
    time.sleep(2)
    from titan_access import engine as E
    try:
        if "hotkey" in SCEN:
            for i in range(3):
                timed("hotkey toggle on #%d" % i, comp.toggle_reader); time.sleep(2)
                timed("hotkey toggle off #%d" % i, comp.toggle_reader); time.sleep(1)
        if "settings" in SCEN:
            for i in range(2):
                timed("GUI-thread start #%d" % i, lambda: on_gui(lambda: E.get_engine().start()), 45); time.sleep(2)
                timed("GUI-thread stop #%d" % i, lambda: on_gui(lambda: E.TitanAccessEngine.instance.stop()), 45); time.sleep(1)
        if "rapid" in SCEN:
            def burst():
                for i in range(5):
                    E.get_engine().start(); E.TitanAccessEngine.instance.stop()
                E.get_engine().start()
            timed("GUI burst on/off x5 then on", lambda: on_gui(burst), 45)
            time.sleep(25)
            workers = [t for t in threading.enumerate() if t.name == "TitanAccessEngine" and t.is_alive()]
            inst = E.TitanAccessEngine.instance
            print("RAPID: running=%s workers=%d hook=%s" % (E.is_running(), len(workers),
                  getattr(getattr(inst, "keyboard", None), "_installed", None)), flush=True)
            timed("hotkey off after burst", comp.toggle_reader)
            time.sleep(1)
            workers = [t for t in threading.enumerate() if t.name == "TitanAccessEngine" and t.is_alive()]
            print("RAPID after off: running=%s workers=%d" % (E.is_running(), len(workers)), flush=True)
        if "touch" in SCEN:
            timed("start for touch", comp.start_reader); time.sleep(2)
            eng = E.TitanAccessEngine.instance
            timed("trackpad on", eng.action_toggle_trackpad)
            from titan_access.portable import trackpad as _tp
            print("TOUCH: pad running=%s why=%r devices=%s" % (_tp.running(), _tp.report().get('why'), _tp.report().get('devices')), flush=True)
            ran = []
            keep = eng._handle_touch
            def spy(a, x, y):
                ran.append((a, threading.current_thread().name))
                return keep(a, x, y)
            eng._handle_touch = spy
            from titan_access.portable import touchRecognizer, trackpad
            fr = wx.GetApp().GetTopWindow().GetScreenRect()
            cx, cy = fr.x + fr.width // 2, fr.y + fr.height // 2
            def fingers():
                # what the pad's input thread hands over: hover across the
                # window, a tap, a double tap, a flick right
                for i in range(30):
                    trackpad.feed([(0, cx - 60 + i * 4, cy, True)]); time.sleep(0.02)
                trackpad.feed([]); time.sleep(0.6)
                for _ in range(2):
                    trackpad.feed([(0, cx, cy, True)]); time.sleep(0.05)
                    trackpad.feed([]); time.sleep(0.1)
                time.sleep(0.6)
                for i in range(6):
                    trackpad.feed([(0, cx + i * 60, cy, True)]); time.sleep(0.015)
                trackpad.feed([]); time.sleep(1.0)
            timed("touch sequence (pad input thread)", fingers, 30)
            time.sleep(2)
            threads = sorted({t for _a, t in ran})
            print("TOUCH: %d gestures handled, actions=%s threads=%s" % (
                len(ran), sorted({a for a, _t in ran}), threads), flush=True)
            timed("stop with trackpad on", comp.stop_reader, 4)
            print("TOUCH: pad still running after stop=%s" % trackpad.running(), flush=True)
        if "trackpad" in SCEN:
            timed("start for trackpad", comp.start_reader); time.sleep(2)
            eng = E.TitanAccessEngine.instance
            for i in range(3):
                timed("trackpad toggle #%d" % i, eng.action_toggle_trackpad); time.sleep(1)
                timed("trackpad toggle back #%d" % i, eng.action_toggle_trackpad); time.sleep(1)
            timed("stop after trackpad", comp.stop_reader)
        if "ao3" in SCEN:
            timed("start for ao3", comp.start_reader); time.sleep(2)
            def ao():
                from accessible_output3.outputs.auto import Auto
                a = Auto()
                for i in range(5):
                    a.speak("test %d" % i, interrupt=True); time.sleep(0.3)
            timed("titan's own speech (ao3 on GUI)", lambda: on_gui(ao), 30)
            timed("stop after ao3", comp.stop_reader)
    except Exception:
        traceback.print_exc()
    time.sleep(1)
    watch.stop = True
    print("WORST GUI STALL %.2fs, stalls=%d" % (watch.worst, len(stalls)), flush=True)
    wx.CallAfter(lambda: wx.GetApp().ExitMainLoop())

def main():
    app = wx.App(False)
    f = wx.Frame(None, title="Titan probe")
    lb = wx.ListBox(f, choices=["Aplikacje", "Gry", "Ustawienia"]); lb.SetName("Lista aplikacji")
    f.Show(); lb.SetFocus()
    comp = load_component()
    from titan_access.settings_store import get_settings
    st = get_settings(); st.enabled = False; st.save()

    w = Watch(); w.start()
    threading.Thread(target=driver, args=(comp, w), daemon=True).start()
    app.MainLoop()
    os._exit(0)

main()
