import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.titan_core.titan_actions import connect, call, is_connected
connect(id='vmcheck', label='VM check')
for _ in range(40):
    time.sleep(0.25)
    if is_connected():
        break
with open('.ask.out', 'w', encoding='utf-8') as out:
    for spec in sys.argv[1:]:
        name, _, raw = spec.partition('=')
        args = json.loads(raw) if raw else {}
        r = call('nvda', name, timeout=60.0, **args)
        out.write('=== %s ok=%s ===\n' % (name, getattr(r, 'ok', '?')))
        text = getattr(r, 'text', None) or str(r)
        try:
            out.write(json.dumps(json.loads(text), indent=1, ensure_ascii=False))
        except Exception:
            out.write(text)
        out.write('\n')
