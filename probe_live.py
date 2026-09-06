# -*- coding: utf-8 -*-
"""What a press and a keystroke really do, measured on a live Titan."""
import io, json, os, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.abspath('.'))
from src.titan_core import titan_actions as ta
ta.connect(id='live_probe', label='Live probe', kind='app')
for _ in range(40):
    if ta.is_connected(): break
    time.sleep(0.25)

def bridge(call, **args):
    answer = ta.call('titan', 'bridge', timeout=90,
                     request=json.dumps({'call': call, 'args': args}, ensure_ascii=False))
    text = getattr(answer, 'text', '') or ''
    if not getattr(answer, 'ok', False):
        return {'ok': False, 'error': text}
    try:
        return json.loads(text)
    except ValueError:
        return {'ok': False, 'error': text[:300]}

def fingerprint(screen):
    """The renderer's own, in Python."""
    if not isinstance(screen, dict):
        return ''
    return json.dumps([screen.get('id'), screen.get('kind'), screen.get('title'),
                       [[c.get('id'), c.get('kind'), c.get('label'), c.get('value'),
                         c.get('items'), c.get('options'), c.get('columns'),
                         c.get('checked'), c.get('enabled')]
                        for c in (screen.get('controls') or [])],
                       [m.get('label') for m in (screen.get('menus') or [])]],
                      ensure_ascii=False, sort_keys=True)

listed = bridge('app.list', language='pl')
for entry in listed['data']:
    name = entry['name']
    opened = bridge('app.open', name=name, client='elten', language='pl')
    if not opened.get('ok'):
        continue
    data = opened['data']
    session, first = data['session'], data['screen']
    print('=== %s' % name)

    def look(screen, where):
        # every button on this screen
        for c in (screen.get('controls') or []):
            if c['kind'] != 'button':
                continue
            before = fingerprint(screen)
            got = bridge('app.press', session=session, control=c['id'])
            if not got.get('ok'):
                print('   %-22s %-18s PRESS FAILED %s' % (where, c['label'][:18], str(got.get('error'))[:50]))
                continue
            after = (got.get('data') or {}).get('screen') or {}
            moved = fingerprint(after) != before
            print('   %-22s %-18s %s' % (where, c['label'][:18],
                                         'screen changed -> %r' % str(after.get('title'))[:24]
                                         if moved else 'NOTHING CHANGED'))
            if moved:
                bridge('app.key', session=session, key='escape')
        # typing into the first text field
        for c in (screen.get('controls') or []):
            if c['kind'] != 'text':
                continue
            before = fingerprint(screen)
            got = bridge('app.set', session=session, control=c['id'], value='ab')
            after = (got.get('data') or {}).get('screen') or {}
            only = [d for d in (after.get('controls') or []) if d['id'] == c['id']]
            others_same = fingerprint({**after, 'controls': [
                dict(d, value=None) if d['id'] == c['id'] else d
                for d in (after.get('controls') or [])]}) == fingerprint({**screen, 'controls': [
                dict(d, value=None) if d['id'] == c['id'] else d
                for d in (screen.get('controls') or [])]})
            print('   %-22s typing into %-14s value=%r  rest of the screen %s' % (
                where, c['label'][:14], only[0].get('value') if only else None,
                'unchanged' if others_same else 'ALSO CHANGED'))
            break
        return

    look(first, 'first screen')
    for menu in (first.get('menus') or []):
        for item in (menu.get('items') or []):
            label = str(item.get('label') or '')
            if item.get('separator') or not label:
                continue
            if any(w in label.lower() for w in ('usu', 'delet', 'zamknij', 'wyjd', 'zako')):
                continue
            got = bridge('app.press', session=session, control=item['id'])
            screen = (got.get('data') or {}).get('screen') or {}
            if got.get('ok') and screen.get('id') != first.get('id') and screen.get('controls'):
                look(screen, label[:22])
                bridge('app.key', session=session, key='escape')
    bridge('app.close', session=session)
