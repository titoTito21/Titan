# -*- coding: utf-8 -*-
"""Pack the add-on into a .nvda-addon, and check it before it goes.

An NVDA add-on is a zip with a manifest at the top of it, so building one is
three lines. The checks around them are the point: an add-on that installs
and then does not load reports it in NVDA's log, where nobody using it is
looking, and the two ways to get there are a manifest NVDA cannot read and a
file the zip is missing.

    python nvda-addon/build.py
"""

import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(HERE, 'addon')

#: Nothing here belongs in a shipped add-on.
SKIP_DIRS = {'__pycache__', '.git'}
SKIP_SUFFIX = ('.pyc', '.pyo', '.orig', '.rej')

#: The manifest fields NVDA refuses to install without.
REQUIRED = ('name', 'summary', 'author', 'version')


def manifest():
    """The manifest as a dict, read the way NVDA reads it: key = value."""
    path = os.path.join(ADDON, 'manifest.ini')
    values, key, buffer = {}, None, []
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            if buffer:
                if line.rstrip('\r\n').endswith('"""'):
                    values[key] = '\n'.join(buffer)
                    buffer, key = [], None
                else:
                    buffer.append(line.rstrip('\r\n'))
                continue
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or '=' not in stripped:
                continue
            key, _, value = stripped.partition('=')
            key, value = key.strip(), value.strip()
            if value.startswith('"""') and not value.endswith('"""'):
                buffer = [value[3:]]
                continue
            values[key] = value.strip('"')
            key = None
    return values


def files():
    for root, directories, names in os.walk(ADDON):
        directories[:] = [d for d in directories if d not in SKIP_DIRS]
        for name in sorted(names):
            if name.endswith(SKIP_SUFFIX):
                continue
            full = os.path.join(root, name)
            yield full, os.path.relpath(full, ADDON).replace(os.sep, '/')


def check(values):
    """Everything that would make the add-on absent rather than broken."""
    problems = []
    for field in REQUIRED:
        if not values.get(field):
            problems.append(f"the manifest has no {field}")
    plugin = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                          '__init__.py')
    if not os.path.exists(plugin):
        problems.append('globalPlugins/titanEnhancements/__init__.py is missing')
    doc = values.get('docFileName')
    if doc and not any(name.endswith('/' + doc) for _f, name in files()):
        problems.append(f"the manifest names {doc}, which is not in the add-on")
    # Every module the plugin imports from its own package must be there: a
    # missing one is an ImportError at load, which means no add-on at all.
    package = os.path.dirname(plugin)
    with open(plugin, encoding='utf-8') as handle:
        source = handle.read()
    for line in source.splitlines():
        line = line.strip()
        if not line.startswith('from . import '):
            continue
        module = line[len('from . import '):]
        module = module.split('#')[0].split(' as ')[0].strip()
        if not os.path.exists(os.path.join(package, module + '.py')):
            problems.append(f"__init__.py imports {module}, which is not there")
    return problems


def build():
    values = manifest()
    problems = check(values)
    if problems:
        for problem in problems:
            print('  problem:', problem)
        return 1
    name = values.get('name', 'addon')
    version = values.get('version', '0.0.0')
    target = os.path.join(HERE, f'{name}-{version}.nvda-addon')
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as package:
        count = 0
        for full, relative in files():
            package.write(full, relative)
            count += 1
    print(f'{target}  ({count} files)')
    return 0


if __name__ == '__main__':
    sys.exit(build())
