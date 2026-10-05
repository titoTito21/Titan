# -*- coding: utf-8 -*-
"""Read a real web page the way Titan Access's browse mode reads it.

    python tests/check_titan_access_web.py <url> [seconds to wait]

A SEPARATE Edge (its own temporary profile, app mode, off-screen, opened
without the foreground, Chromium's occlusion tracking off so an off-screen
window is still rendered) loads the page; the reader's own code picks the
page's document and builds the buffer. Prints the path the reader takes
(FULLPATH), and writes every line to %TEMP%/probe_web_nodes.txt as
role|level|name|region|link|pos/size. Nothing of the user's is touched -
neither their browser profile nor their foreground. Sites behind
Cloudflare may answer a fresh profile with the challenge page only.
"""
import os, sys, tempfile, time, subprocess, ctypes, json
os.environ['APPDATA'] = tempfile.mkdtemp()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(ROOT, 'data', 'components', 'titan access', 'lib'), os.path.join(ROOT, 'data', 'components', 'titan access'), ROOT):
    sys.path.insert(0, p)
from ctypes import wintypes
import psutil
url = sys.argv[1]
wait = float(sys.argv[2]) if len(sys.argv) > 2 else 12
profile = tempfile.mkdtemp(prefix='edge_probe_')
exe = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
si = subprocess.STARTUPINFO(); si.dwFlags = 1; si.wShowWindow = 4  # SW_SHOWNOACTIVATE
proc = subprocess.Popen([exe, '--user-data-dir=' + profile, '--no-first-run', '--no-default-browser-check',
                         '--force-renderer-accessibility', '--window-position=-3000,0', '--window-size=1280,1000', '--disable-sync', '--disable-features=msEdgeWelcomePage,EdgeSyncFRE,CalculateNativeWinOcclusion', '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding', '--app=' + url], startupinfo=si)
time.sleep(wait)
pids = set()
for pr in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        if pr.info['name'] == 'msedge.exe' and any(profile in (a or '') for a in pr.info['cmdline'] or []):
            pids.add(pr.info['pid'])
    except Exception:
        pass
user32 = ctypes.windll.user32
found = []
@ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
def cb(h, _):
    pid = wintypes.DWORD(); user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    buf = ctypes.create_unicode_buffer(256); user32.GetClassNameW(h, buf, 256)
    if pid.value in pids and user32.IsWindowVisible(h) and buf.value == 'Chrome_WidgetWin_1':
        found.append(h)
    return True
user32.EnumWindows(cb, 0)
try:
    from titan_access import browse_mode, virtual_buffer as vbuf
    import uiautomation as auto
    win = auto.ControlFromHandle(found[0])
    h = browse_mode.BrowseModeHandler.__new__(browse_mode.BrowseModeHandler)
    doc = h._find_main_document(win)
    browse_mode._foreground_hwnd = lambda: found[0]
    bh = browse_mode.BrowseModeHandler.__new__(browse_mode.BrowseModeHandler)
    bh._root_cache = None
    bh._last_content_doc = None
    full = bh._build_web_document()
    print('FULLPATH', full.source, len(full.nodes), [ (n.role, n.name[:30]) for n in full.nodes[:4]])
    print('WINDOW', win.Name, 'DOC', doc and doc.Name, 'content?', browse_mode.BrowseModeHandler._is_content_document(doc))
    if doc is not None:
        t = time.time()
        nodes = vbuf.build_uia(doc, deadline=time.time() + vbuf.BUILD_BUDGET_S, web=True)
        print('NODES', len(nodes), '%.2fs' % (time.time() - t))
        out = os.path.join(tempfile.gettempdir(), 'probe_web_nodes.txt')
        with open(out, 'w', encoding='utf-8') as f:
            for n in nodes:
                f.write('%s|%s|%s|%s|link=%s|%s/%s\n' % (n.role, n.level, (n.name or '')[:90], n.landmark or '', n.link, n.pos_in_set, n.size_of_set))
        print('OUT', out)
finally:
    for pid in pids:
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], capture_output=True)
