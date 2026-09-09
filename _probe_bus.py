import sys, os, json, time
sys.path.insert(0, os.getcwd())
from src.titan_core import titan_actions as ta
ta.connect(id='diag_probe', label='Diagnostics')
for _ in range(40):
    if ta.is_connected(): break
    time.sleep(0.25)
out = open('_probe_out.txt', 'w', encoding='utf-8')
def w(*a): out.write(' '.join(str(x) for x in a) + '\n')
def dump(tag):
    r = ta.call('nvda', 'settings', timeout=10.0)
    try: d = json.loads(str(r))
    except Exception: d = {}
    rd = d.get('reading', {})
    w(f"=== {tag} === three_tones={rd.get('three_tones')} replaced={rd.get('replaced')}")
    w(" heard:")
    for h in rd.get('heard', [])[-5:]:
        w("   ", round(h.get('ago',0),2), repr(h.get('text')))
    w(" spoken:")
    for s in rd.get('spoken', [])[-8:]:
        w("   ", round(s.get('ago',0),2), s.get('by'), repr(s.get('said')))

ta.call('desktop', 'focus_window', timeout=10.0, title='Pakiet aplikacji Titan')
time.sleep(1.0)
ta.call('desktop', 'press_keys', timeout=10.0, keys='down')
time.sleep(1.2)
dump('after down')
ta.call('desktop', 'press_keys', timeout=10.0, keys='home')
time.sleep(1.2)
dump('after home (tab bar row)')
ta.call('desktop', 'press_keys', timeout=10.0, keys='right')
time.sleep(1.2)
dump('after right (switch view)')
out.close()
