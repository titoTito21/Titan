# -*- coding: utf-8 -*-
"""Pack a Cling application into one `.pag` file, or look inside one.

A Klango application ships as a single `.pag`, so a Cling application does too:
one file to copy, to send to somebody, or to drop into the user's own
`data/cling/`. The folder stays exactly as it was - packing never moves or
deletes anything.

    python src/scripts/pack_cling.py "data/components/cling/apps/clingdemo" -o clingdemo.pag
    python src/scripts/pack_cling.py --unpack clingdemo.pag -o /tmp/look
    python src/scripts/pack_cling.py --inspect some.pag

`--inspect` works on Klango's own packages as well, and says plainly what can
and cannot be done with one.
"""

import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
COMPONENT = os.path.join(ROOT, 'data', 'components', 'cling')
for path in (ROOT, COMPONENT):
    if path not in sys.path:
        sys.path.insert(0, path)

from clingkit import catalog, pag                                   # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('path', help='the application folder, or a .pag file')
    parser.add_argument('-o', '--out', default='',
                        help='where to write (a .pag, or a folder to unpack into)')
    parser.add_argument('--unpack', action='store_true',
                        help='unpack a package instead of building one')
    parser.add_argument('--inspect', action='store_true',
                        help='say what a package is, and open nothing')
    arguments = parser.parse_args(argv)

    source = os.path.abspath(arguments.path)

    if arguments.inspect:
        print(pag.inspect(source))
        return 0

    if arguments.unpack:
        target = arguments.out or os.path.splitext(source)[0]
        written = pag.extract(source, target)
        print('%d file(s) into %s' % (len(written), target))
        return 0

    if not os.path.isdir(source):
        parser.error('%s is not a folder' % source)
    if not catalog.looks_like_app(source):
        print('Warning: %s has no kni.txt or __cling__.TCE, so Cling will not '
              'find it as an application.' % source, file=sys.stderr)
    target = arguments.out or (source.rstrip(os.sep) + '.pag')
    pag.build(source, target)
    print('%s (%d bytes)' % (target, os.path.getsize(target)))
    print(pag.inspect(target))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except pag.PagError as error:
        print('Error: %s' % error, file=sys.stderr)
        sys.exit(1)
