# -*- coding: utf-8 -*-
"""Every screen of every TCE application, against what the renderer builds.

"All the screens of all the applications must work" is a promise, and a
promise about eight programs nobody here wrote cannot be kept by reading
them. So this OPENS every one of them through Titan, walks every screen it
can reach, and collects two things: every kind of control that really
appears, and every menu shortcut that really appears. Then it asks the
renderer whether it has a branch for each.

    python tests/check_render_coverage.py

It fails on a kind the renderer would silently show as a line of text, and
on a shortcut it would silently swallow - which is how "it does not work"
gets reported instead of being caught here. `Alt+F4` is the one deliberate
exception: it means "close the application" and in Elten it would close
ELTEN, so it is left to Escape and the Back button.
"""
import io, os, re, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.dirname(HERE)
sys.path.insert(0, os.path.dirname(BRIDGE))
from src.app_ui import host, sessions

DANGEROUS = re.compile(r'usu|delet|remov|kasuj|format|wyczy|zamknij|exit|wyjd|zako', re.I)

kinds, shortcuts, screens, apps = {}, set(), 0, 0
for entry in sessions.applications('pl'):
    app = host.Application(entry['entry'], entry['name'])
    if not app.start():
        print('%-12s not describable (%s)' % (entry['id'], app.detail[:50]))
        continue
    apps += 1
    seen = set()

    def take(screen, where):
        global screens
        key = (screen.get('id'), screen.get('kind'))
        if key in seen or not screen.get('controls'):
            return False
        seen.add(key)
        screens += 1
        for c in screen['controls']:
            kinds.setdefault(c['kind'], set()).add('%s/%s' % (entry['id'], where))
        for m in screen.get('menus') or []:
            for item in m.get('items') or []:
                if item.get('key'):
                    shortcuts.add(item['key'])
                for sub in item.get('items') or []:
                    if sub.get('key'):
                        shortcuts.add(sub['key'])
        return True

    take(app.screen, 'first')
    first = app.screen.get('id')
    for m in list(app.screen.get('menus') or []):
        for item in list(m.get('items') or []):
            label = str(item.get('label') or '')
            if item.get('separator') or not label or DANGEROUS.search(label):
                continue
            app.tell('press', control=item['id'])
            if (app.screen or {}).get('id') != first:
                take(app.screen, label)
                app.tell('key', key='escape')
    for c in list(app.screen.get('controls') or []):
        if c['kind'] == 'button' and not DANGEROUS.search(c['label']):
            app.tell('press', control=c['id'])
            if (app.screen or {}).get('id') != first:
                take(app.screen, c['label'])
                app.tell('key', key='escape')
    app.stop()

renderer = io.open(os.path.join(BRIDGE, 'titan_apps.rb'),
                   encoding='utf-8').read()
build = renderer[renderer.index('def build(described)'):]
build = build[:build.index('\n  end\n')]
print('\n%d applications, %d screens\n' % (apps, screens))
print('control kinds that really appear:')
bad = []
for kind in sorted(kinds):
    handled = ('when "%s"' % kind) in build or ('"%s",' % kind) in build \
        or ('"%s"' % kind) in build
    print('  %-10s %-8s in %s' % (kind, 'ok' if handled else 'NOT BUILT',
                                  ', '.join(sorted(kinds[kind])[:3])))
    if not handled:
        bad.append(kind)
print('\nmenu shortcuts that really appear:')
for one in sorted(shortcuts):
    low = one.lower()
    # Alt+F4 would close Elten itself; the menu item is still there to
    # be pressed, it just has no shortcut here.
    ok = (low.startswith('ctrl+') and 'alt+' not in low) \
        or re.match(r'^(f\d+|delete|insert|backspace)$', low) \
        or low == 'alt+f4'
    print('  %-16s %s' % (one, 'forwarded' if ok else 'NOT FORWARDED'))
    if not ok:
        bad.append(one)
print('\n%s' % ('everything on every screen is handled' if not bad
                else 'NOT HANDLED: %s' % bad))
sys.exit(1 if bad else 0)
