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


def _read_po(path):
    """A .po as {msgid: msgstr}. Enough of the format for this add-on.

    Handles what the catalogue really uses: comments, the header entry,
    and strings continued over several quoted lines. An entry with an
    empty translation is left out - an untranslated string must fall back
    to the English source, and a msgstr of "" in the catalogue would
    translate it to nothing at all.
    """
    entries, key, value, reading = {}, None, None, None
    def flush():
        if key is not None and value:
            entries[key] = value
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('msgid '):
                flush()
                key, value, reading = _po_string(line[6:]), '', 'id'
            elif line.startswith('msgstr '):
                value, reading = _po_string(line[7:]), 'str'
            elif line.startswith('"'):
                piece = _po_string(line)
                if reading == 'id':
                    key += piece
                elif reading == 'str':
                    value += piece
        flush()
    # **The empty msgid is KEPT.** It is the header, and its `Content-Type`
    # is what tells gettext the catalogue is UTF-8; without it every
    # translation carrying a Polish letter fails to decode and the whole
    # catalogue is refused - which reads as "the translation does not
    # work" rather than as a missing header.
    return entries


def _po_string(text):
    text = text.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1]
    return (text.replace('\\n', '\n').replace('\\t', '\t')
            .replace('\\"', '"').replace('\\\\', '\\'))


def _write_mo(entries, path):
    """The .mo gettext reads. Its format is small and entirely documented.

    Written here rather than shelling out to `msgfmt`, which is not on a
    Windows machine and would make building the add-on depend on somebody
    having installed gettext.
    """
    import struct
    items = sorted(entries.items())
    keys = b'\x00'.join(k.encode('utf-8') for k, _v in items) + b'\x00' \
        if items else b''
    offsets, originals, translations = [], b'', b''
    for key, value in items:
        key_bytes = key.encode('utf-8')
        value_bytes = value.encode('utf-8')
        offsets.append((len(originals), len(key_bytes),
                        len(translations), len(value_bytes)))
        originals += key_bytes + b'\x00'
        translations += value_bytes + b'\x00'
    count = len(items)
    start_originals = 7 * 4 + 16 * count
    start_translations = start_originals + len(originals)
    output = struct.pack('<Iiiiiii', 0x950412de, 0, count, 7 * 4,
                         7 * 4 + 8 * count, 0, 0)
    for key_at, key_len, value_at, value_len in offsets:
        output += struct.pack('<ii', key_len, start_originals + key_at)
    for key_at, key_len, value_at, value_len in offsets:
        output += struct.pack('<ii', value_len, start_translations + value_at)
    output += originals + translations
    with open(path, 'wb') as handle:
        handle.write(output)
    return count


def compile_translations():
    """Every .po in the add-on, as the .mo NVDA will actually read.

    The .po is what a person edits and what lives in the repository; the
    .mo is a build product. Compiling it here means a translation cannot
    be forgotten between editing it and shipping it.
    """
    made = []
    for root, directories, names in os.walk(ADDON):
        directories[:] = [d for d in directories if d not in SKIP_DIRS]
        for name in sorted(names):
            if not name.endswith('.po'):
                continue
            source = os.path.join(root, name)
            target = os.path.join(root, name[:-3] + '.mo')
            try:
                count = _write_mo(_read_po(source), target)
            except Exception as error:               # noqa: BLE001
                print('  problem: %s: %s' % (name, error))
                continue
            made.append((os.path.relpath(target, ADDON), count))
    return made


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
    # Every module the package imports from ITSELF must be there: a missing
    # one is an ImportError, and an ImportError at load means no add-on at
    # all - which is reported in NVDA's log, where nobody using it looks.
    #
    # Swept over the whole package rather than over `__init__.py` alone.
    # Most of this add-on is imported lazily, inside the function that needs
    # it, precisely so that a missing piece of NVDA costs one feature
    # instead of the add-on - and the price of that is that a module which
    # is simply not in the zip is not found until somebody presses the key.
    package = os.path.dirname(plugin)
    for root, directories, names in os.walk(package):
        directories[:] = [d for d in directories if d not in SKIP_DIRS]
        for name in sorted(names):
            if not name.endswith('.py'):
                continue
            full = os.path.join(root, name)
            with open(full, encoding='utf-8') as handle:
                source = handle.read()
            where = os.path.relpath(full, package).replace(os.sep, '/')
            for line in source.splitlines():
                line = line.strip()
                if not line.startswith('from . import '):
                    continue
                # `from . import a, b, c` is one line and three modules.
                names_on_line = line[len('from . import '):].split('#')[0]
                for module in names_on_line.split(','):
                    module = module.split(' as ')[0].strip()
                    if not module:
                        continue
                    beside = os.path.dirname(full)
                    if os.path.exists(os.path.join(beside, module + '.py')):
                        continue
                    if os.path.exists(os.path.join(beside, module,
                                                   '__init__.py')):
                        continue
                    problems.append(f"{where} imports {module}, which is "
                                    f"not there")
    return problems


def build():
    values = manifest()
    for where, count in compile_translations():
        print('%s  (%d strings)' % (where, count))
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
