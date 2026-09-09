# -*- coding: utf-8 -*-
"""Bring a translation catalogue back in step with the add-on's own sources.

    python nvda-addon/update_catalogue.py            # every language
    python nvda-addon/update_catalogue.py pl         # one

**Why this exists rather than xgettext.** The add-on has to build and be
tested on a machine with nothing installed - that is the property that makes
it degrade on an NVDA missing a feature instead of failing to load - and a
build step that needs gettext's tools is a build step somebody cannot run.
The .po format is small and entirely documented; `build.py` already writes
the .mo for the same reason.

What it does, and the order matters:

* **Reads the SOURCE, by parsing it.** A string is what is passed to `_()`,
  found with `ast` rather than by matching text, so a call written across
  several lines counts once and a word in a comment counts not at all.
* **Keeps every translation that is already there.** A string somebody has
  translated is never touched, never reordered away and never dropped
  because this run could not find where it is used any more.
* **Leaves a new string EMPTY rather than guessing.** An empty msgstr is
  what gettext falls back to the English for, so a catalogue that has fallen
  behind is a partial translation and not a broken one.
* **Says what has no translation**, which is the list somebody works
  through - and it is exactly what `test_every_string_the_addon_can_say_is_
  translated` fails on, so the test names a job this script finishes.

A msgid this run cannot find in the source any more is kept and marked
obsolete rather than deleted: a string is often only away for one commit,
and a translation thrown out is somebody's work thrown out.
"""

import ast
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, 'addon', 'globalPlugins', 'titanEnhancements')
LOCALE = os.path.join(HERE, 'addon', 'locale')

#: The language the strings are WRITTEN in. Its msgid is its translation.
SOURCE_LANGUAGE = 'en'


# --------------------------------------------------------------------------- #
# What the add-on can say
# --------------------------------------------------------------------------- #
def strings():
    """``[(file, line, note, msgid)]`` in source order, each msgid once.

    ``note`` is the `# Translators:` comment above the call. It is lifted
    from the source rather than written here: a comment kept in two places
    is a comment that goes out of step with the string it explains.
    """
    found, seen = [], set()
    for base, _dirs, names in os.walk(SOURCE):
        if '__pycache__' in base:
            continue
        for name in sorted(names):
            if not name.endswith('.py'):
                continue
            path = os.path.join(base, name)
            with io.open(path, encoding='utf-8') as handle:
                text = handle.read()
            lines = text.splitlines()
            try:
                tree = ast.parse(text)
            except SyntaxError as error:
                print('  !! %s: %s' % (name, error))
                continue
            where = os.path.relpath(path, SOURCE).replace('\\', '/')
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                called = getattr(node.func, 'id', None) \
                    or getattr(node.func, 'attr', None)
                if called != '_':
                    continue
                first = node.args[0]
                if not isinstance(first, ast.Constant) or \
                        not isinstance(first.value, str):
                    continue
                if first.value in seen:
                    continue
                seen.add(first.value)
                found.append((where, node.lineno,
                              _note_above(lines, node.lineno), first.value))
    return found


def _note_above(lines, line):
    out = []
    index = line - 2
    while index >= 0 and lines[index].strip().startswith('#'):
        out.insert(0, lines[index].strip().lstrip('#').strip())
        index -= 1
    return out if out and out[0].lower().startswith('translators') else []


# --------------------------------------------------------------------------- #
# The catalogue
# --------------------------------------------------------------------------- #
def _unquote(block):
    """The text of one or more adjacent quoted strings, as gettext joins
    them."""
    out, index, inside, escaped = [], 0, False, False
    for character in block:
        if escaped:
            out.append({'n': '\n', 't': '\t', '"': '"',
                        '\\': '\\'}.get(character, character))
            escaped = False
        elif character == '\\' and inside:
            escaped = True
        elif character == '"':
            inside = not inside
        elif inside:
            out.append(character)
    return ''.join(out)


def read_po(path):
    """``{msgid: msgstr}``, including the obsolete entries."""
    if not os.path.isfile(path):
        return {}
    entries, key, buffer, reading = {}, None, [], None
    with io.open(path, encoding='utf-8') as handle:
        for line in handle:
            stripped = line.strip()
            if stripped.startswith('#~'):
                stripped = stripped[2:].strip()
            if stripped.startswith('msgid '):
                if key is not None:
                    entries[key] = _unquote(''.join(buffer))
                key, buffer, reading = _unquote(stripped[6:]), [], 'id'
                continue
            if stripped.startswith('msgstr '):
                buffer, reading = [stripped[7:]], 'str'
                continue
            if stripped.startswith('"') and reading:
                if reading == 'id':
                    key += _unquote(stripped)
                else:
                    buffer.append(stripped)
                continue
            if not stripped and key is not None and reading == 'str':
                entries[key] = _unquote(''.join(buffer))
                key, buffer, reading = None, [], None
    if key is not None and reading == 'str':
        entries[key] = _unquote(''.join(buffer))
    entries.pop('', None)
    return entries


def escape(value):
    return (value.replace('\\', '\\\\').replace('"', '\\"')
            .replace('\n', '\\n').replace('\t', '\\t'))


HEADER = '''# Titan enhancements - {language}.
#
# Written from the add-on's own sources by update_catalogue.py: every string
# it can say has an entry. gettext falls back to the English source for an
# empty one, so a catalogue that has fallen behind the code is a partial
# translation rather than a broken one.
msgid ""
msgstr ""
"Project-Id-Version: titanEnhancements\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Language: {code}\\n"
{plural}'''

PLURALS = {
    'pl': '"Plural-Forms: nplurals=3; plural=(n==1 ? 0 : n%10>=2 && n%10<=4 '
          '&& (n%100<10 || n%100>=20) ? 1 : 2);\\n"\n',
}


def write(code, rows, known):
    path = os.path.join(LOCALE, code, 'LC_MESSAGES', 'nvda.po')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out = [HEADER.format(language=code.upper(), code=code,
                         plural=PLURALS.get(code, ''))]
    live, missing = set(), []
    for where, line, note, msgid in rows:
        live.add(msgid)
        said = known.get(msgid, '')
        if not said:
            missing.append('%s:%d %r' % (where, line, msgid[:60]))
        out.append('')
        for word in note:
            out.append('#. ' + word)
        out.append('#: %s:%d' % (where, line))
        out.append('msgid "%s"' % escape(msgid))
        out.append('msgstr "%s"' % escape(said))
    # A string that has gone from the source is kept, commented out. It is
    # usually away for one commit, and a translation thrown away is
    # somebody's work thrown away.
    gone = sorted(key for key, value in known.items()
                  if key not in live and value)
    if gone:
        out.append('')
        out.append('# No longer in the source. Kept in case it comes back.')
        for msgid in gone:
            out.append('')
            out.append('#~ msgid "%s"' % escape(msgid))
            out.append('#~ msgstr "%s"' % escape(known[msgid]))
    with io.open(path, 'w', encoding='utf-8') as handle:
        handle.write('\n'.join(out) + '\n')
    return missing, len(gone)


def main(argv):
    rows = strings()
    print('%d strings in the add-on' % len(rows))
    # English is the source: its msgid IS the translation, so a catalogue
    # for it would be 391 empty entries and a build product nobody reads.
    wanted = argv[1:] or sorted(
        name for name in os.listdir(LOCALE)
        if name != SOURCE_LANGUAGE
        and os.path.isdir(os.path.join(LOCALE, name, 'LC_MESSAGES')))
    problems = 0
    for code in wanted:
        path = os.path.join(LOCALE, code, 'LC_MESSAGES', 'nvda.po')
        missing, gone = write(code, rows, read_po(path))
        print('%s: %d translated, %d missing, %d kept as obsolete'
              % (code, len(rows) - len(missing), len(missing), gone))
        for line in missing[:40]:
            print('   ' + line)
        if len(missing) > 40:
            print('   ... and %d more' % (len(missing) - 40))
        problems += len(missing)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
