# -*- coding: utf-8 -*-
"""Every screen of every TCE application, as the renderer really gets it.

Opens each application through `titan.bridge` on a running Titan, walks
its menu items and its buttons, and writes every distinct screen to
`screens.json` - which is what `check_renderer_builds.rb` then builds with
the real renderer and the Elten stub, needing neither Titan nor Elten.

Run it again whenever an application grows a screen.
"""
import io
import json
import os
import re
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                              errors='replace')
HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, TITAN)

from src.titan_core import titan_actions as ta

#: A menu item or button that would change the user's own disk, or end the
#: application, is not something to press to find out what it looks like.
DANGEROUS = re.compile(r'usu|delet|remov|kasuj|format|wyczy|zamknij|exit|wyjd|zako',
                       re.I)


def main():
    ta.connect(id='screen_capture', label='Screen capture', kind='app')
    for _ in range(40):
        if ta.is_connected():
            break
        time.sleep(0.25)

    def bridge(call, **args):
        answer = ta.call('titan', 'bridge', timeout=90,
                         request=json.dumps({'call': call, 'args': args},
                                            ensure_ascii=False))
        text = getattr(answer, 'text', '') or ''
        if not getattr(answer, 'ok', False):
            return {'ok': False, 'error': text}
        try:
            return json.loads(text)
        except ValueError:
            return {'ok': False, 'error': text[:300]}

    listed = bridge('app.list', language='pl')
    if not listed.get('ok'):
        print('TCE did not answer: %s' % listed.get('error'))
        return 1

    out = []
    for entry in listed['data']:
        name = entry['name']
        opened = bridge('app.open', name=name, client='elten', language='pl')
        if not opened.get('ok'):
            print('%-28s not opened (%s)' % (name, str(opened.get('error'))[:60]))
            continue
        data = opened['data']
        session = data.get('session')
        first = data.get('screen') or {}
        seen = {first.get('id')}
        out.append({'app': entry['id'], 'screen': first})

        def visit(screen):
            if not screen or screen.get('id') in seen or not screen.get('controls'):
                return False
            seen.add(screen.get('id'))
            out.append({'app': entry['id'], 'screen': screen})
            return True

        for menu in (first.get('menus') or []):
            for item in (menu.get('items') or []):
                label = str(item.get('label') or '')
                if item.get('separator') or not label or DANGEROUS.search(label):
                    continue
                got = bridge('app.press', session=session, control=item['id'])
                if got.get('ok') and visit((got.get('data') or {}).get('screen')):
                    bridge('app.key', session=session, key='escape')
        for control in list(first.get('controls') or []):
            if control['kind'] != 'button' or DANGEROUS.search(control['label']):
                continue
            got = bridge('app.press', session=session, control=control['id'])
            if got.get('ok') and visit((got.get('data') or {}).get('screen')):
                bridge('app.key', session=session, key='escape')
        bridge('app.close', session=session)
        print('%-28s %d screen(s)' % (name, len(seen)))

    path = os.path.join(HERE, 'screens.json')
    io.open(path, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(out, ensure_ascii=False, indent=1))
    print('\n%d screen(s) written to %s' % (len(out), os.path.basename(path)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
