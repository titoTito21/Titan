# -*- coding: utf-8 -*-
"""Merge the IAccessible2 IDL files into one, the way IA2's own build does.

MIDL generates proxy/stub code only for interfaces DEFINED in the file it
is given, not for ones it imports - which is why the IA2 project ships a
merged ``ia2_api_all.idl`` and why NVDA builds its proxy from one. The
files under ``api/`` are the IA2 sources, BSD-licensed, taken from
https://github.com/LinuxA11y/IAccessible2 unchanged; this concatenates
them in dependency order, keeps the system imports once at the top, drops
the imports of each other, and appends the type library block.

    python merge_idl.py            -> ia2_api_all.idl beside this file
"""
import io
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
API = os.path.join(HERE, 'api')

ORDER = (
    'IA2CommonTypes', 'AccessibleRole', 'AccessibleStates', 'AccessibleEventID',
    'AccessibleRelation', 'AccessibleAction', 'AccessibleHyperlink',
    'AccessibleText', 'AccessibleText2', 'AccessibleHypertext',
    'AccessibleHypertext2', 'AccessibleEditableText', 'AccessibleValue',
    'AccessibleImage', 'AccessibleComponent', 'AccessibleApplication',
    'AccessibleTableCell', 'AccessibleTable', 'AccessibleTable2',
    'AccessibleDocument', 'AccessibleTextSelectionContainer',
    'Accessible2', 'Accessible2_2', 'Accessible2_3',
)
SYSTEM_IMPORTS = ('import "objidl.idl";', 'import "oaidl.idl";',
                  'import "oleacc.idl";')


def _body(name):
    text = io.open(os.path.join(API, name + '.idl'), encoding='utf-8').read()
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('import "'):
            continue                                  # every import: once, above
        kept.append(line)
    return '\n'.join(kept)


def merge():
    parts = ['// Merged from the IAccessible2 IDL files by merge_idl.py -',
             '// do not edit; edit api/*.idl.', '']
    parts.extend(SYSTEM_IMPORTS)
    parts.append('')
    for name in ORDER:
        parts.append('// ---- %s.idl ----' % name)
        parts.append(_body(name))
        parts.append('')
    parts.append(_body('IA2TypeLibrary'))
    out = os.path.join(HERE, 'ia2_api_all.idl')
    io.open(out, 'w', encoding='utf-8', newline='\n').write('\n'.join(parts) + '\n')
    return out


if __name__ == '__main__':
    print(merge())
