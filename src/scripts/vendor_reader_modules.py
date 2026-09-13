#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One source, two readers: copy the shared modules into Titan Access.

    python src/scripts/vendor_reader_modules.py          # copy
    python src/scripts/vendor_reader_modules.py --check  # only say if they differ

Somebody reading this desktop uses Titan Access, or NVDA with Titan's
add-on, or both, and what they accumulate is the same thing either way: a
control they named, a window they asked what it is written in, a virtual
machine they are reading as a picture. Two implementations of that is two
things to keep right and one of them quietly falling behind.

**So there is one source and it is the add-on's**, and these files are
copied - byte for byte - into
``data/components/titan access/titan_access/portable/``. Copied rather
than imported because the two ship separately: the add-on is a
``.nvda-addon`` installed into NVDA and Titan Access is a Titan component,
and neither may depend on the other being on the machine.

Each of them was made portable rather than being forked to fit: they ask
for NVDA's own names directly and answer honestly when there is no NVDA
(``windowKind._control_types``), and the one place their answers really
must differ - which folder this reader keeps its own copy in - is asked in
one function that gives the right answer in both (``labels._folder``).

``--check`` is what a test runs, so a change made on one side and not
vendored fails rather than shipping as two readers that disagree.
"""

import filecmp
import io
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))

SOURCE = os.path.join(ROOT, 'nvda-addon', 'addon', 'globalPlugins',
                      'titanEnhancements')
TARGET = os.path.join(ROOT, 'data', 'components', 'titan access',
                      'titan_access', 'portable')

#: What is shared, and why each one is worth sharing rather than being
#: written twice.
SHARED = (
    # The names, descriptions and per-control decisions the user has
    # accumulated. Losing half of them by switching readers is the whole
    # reason any of this exists.
    'labels.py',
    # The merge that makes one store out of two readers' copies.
    'shared.py',
    # What a window is WRITTEN IN, read off the libraries its process
    # loaded - which is neither reader's business to decide differently.
    'toolkit.py',
    # MSAA for a window that has none: a virtual machine, a program on a
    # toolkit nobody wired up.
    'virtualInput.py',
    # What a picture of a window IS - the menu bar, the columns, the
    # status line and what is highlighted - worked out from geometry, so
    # it is the same in every language and costs nothing.
    'sceneModel.py',
    # Windows' own recogniser, and the local model tier under it. Both
    # readers ask Titan for the model, so this is one file.
    'localOcr.py',
    # What kind of window you have arrived in, and what its icon is.
    'windowKind.py',
    # The semantic classes - what each kind of thing sounds like, and in
    # what order its parts are read. A user who set that up in one reader
    # should not have to set it up again in the other.
    'classes.py',
    # A sound instead of a word, for what you already know.
    'schemes.py',
    # A place in a program, remembered and gone back to.
    'anchors.py',
    # Recorded procedures - by CONTROL, not by key, which is why they
    # mean the same thing in either reader.
    'procedures.py',
    # An area of the screen, watched, and said when it changes.
    'monitors.py',
    # The switches a program answers for itself rather than taking the
    # general setting.
    'perProgram.py',
    # Finding the control that DOES a thing, by what is written on it.
    'findControl.py',
    # What a control offers and the two things any control allows.
    'windowsAndActions.py',
    # Whether a reader module actually does anything to a window.
    'verify.py',
    # What kind of dialog has appeared - a question, a warning, an error
    # - read off its ICON by comparing pictures, which is the same in
    # both readers because Windows draws the same icons for both.
    'dialog_kind.py',
    # And what an icon SHOWS, named the same way: a folder, a printer,
    # the warning triangle. No model, no key, nothing sent anywhere.
    'iconNames.py',
    # A field's own text as something to WALK - the edit-field mode, and
    # the one place that knows what Backspace and Control with an arrow
    # mean in a field, so the two readers and both their modes cannot
    # drift apart about it.
    'textField.py',
    # Layered commands: one key opens a layer, the next chooses in it.
    'layers.py',
    # And the palette that walks them - a list in the same shape as every
    # other list either reader walks, rather than a modal dialog.
    'palette.py',
    # The trackpad in every walked list - the table of what each gesture
    # does, and the finger exploration the lists answer.
    'touchWalk.py',
    # Titan's own typed doorway, asked the same way in both readers. It is
    # built entirely on one call, so the add-on's pipe and Titan Access's
    # direct call are the same file with two `link` shims under it.
    'titan.py',
    # Auditory icons - a sound for what the cursor has landed on.
    'icons.py',
    # A Titan application described rather than drawn, walked as a window.
    'appScreen.py',
    'appReview.py',
    # Any window, as a virtual window.
    'virtualWindow.py',
    # A Titan widget, reviewed.
    'widgetReview.py',
    # Titan's own window: its applications, settings, buffers, statusbar.
    'titanWindow.py',
    # And the same Titan WALKED - the pages as a list, what is on a page
    # as a list, Enter doing the one obvious thing to a row.
    'titanWalk.py',
    # What the user has MADE, walked: the markers, the programs, the
    # procedures, the names, the watched areas, the icons, the scheme and
    # the voice classes. The forms stay where editing happens.
    'managerWalk.py',
    # A window that exposes nothing, read as a picture - a game's menu, a
    # virtual machine.
    'surface.py',
    # Writing a reader module for a program, from what was observed.
    'draft.py',
    # The few windows either reader puts up - and, first, the walked page
    # that has replaced most of them. `compat.gui` is what differs: NVDA's
    # own frame there, Titan's own window here.
    'dialogs.py',
    # What Titan could do the last time we asked, kept beside everything
    # else this reader accumulates. Its script-name half is NVDA's Input
    # Gestures and simply goes unused on the other side.
    'gestures.py',
    # THE Titan menu - one definition, two renderings. The `wx.Menu` is for
    # somebody who wants the platform's own; `menuWalk` walks that same
    # menu as a list. Rebuilding it as a second list is how the two quietly
    # stop agreeing, which is exactly what this file exists to prevent.
    'menu.py',
    'menuWalk.py',
    # And what each entry of it does. Most of these are Titan's own and
    # work in either reader; the handful that reach NVDA's speech filter,
    # its audio session or its review cursor say so out loud rather than
    # failing silently.
    'commands.py',
    # A place in a program, marked and gone back to.
    'markers.py',
    # What was said, kept, so "what was that?" has an answer.
    'journal.py',
    # The laptop's touchpad as a touch screen. Its pad-reading half is
    # ctypes and portable; where the contacts GO is NVDA's own touch
    # machinery, and in Titan Access it says so rather than pretending.
    'trackpad.py',
)

#: Whole PACKAGES shared the same way. `readerModules` is the reader
#: modules a user (or the AI) writes for one program, plus the schema that
#: refuses an invented key - all of it plain Python over JSON, and the
#: same knowledge in either reader.
SHARED_PACKAGES = ('readerModules',)

#: Beside them in the target, and NOT copied: the shims that answer for
#: this reader - `_` through its own catalogue, NVDA's services through
#: its own, and Titan directly rather than over a pipe, because Titan
#: Access is not on the other side of anything.
SHIMS = ('__init__.py', 'i18n.py', 'compat.py', 'link.py')


def _pairs():
    for name in SHARED:
        yield os.path.join(SOURCE, name), os.path.join(TARGET, name)
    for package in SHARED_PACKAGES:
        source = os.path.join(SOURCE, package)
        if not os.path.isdir(source):
            continue
        for name in sorted(os.listdir(source)):
            if name.endswith('.py'):
                yield (os.path.join(source, name),
                       os.path.join(TARGET, package, name))


def check():
    """(same, [what is wrong]) - what a test asks."""
    wrong = []
    if not os.path.isdir(TARGET):
        return False, ['%s does not exist' % TARGET]
    for source, target in _pairs():
        if not os.path.exists(source):
            wrong.append('%s is not in the add-on any more'
                         % os.path.basename(source))
            continue
        if not os.path.exists(target):
            wrong.append('%s has never been vendored'
                         % os.path.basename(source))
            continue
        if not filecmp.cmp(source, target, shallow=False):
            wrong.append('%s differs - run vendor_reader_modules.py'
                         % os.path.basename(source))
    for name in SHIMS:
        if not os.path.exists(os.path.join(TARGET, name)):
            wrong.append('the %s shim is missing' % name)
    return (not wrong), wrong


def copy():
    os.makedirs(TARGET, exist_ok=True)
    for package in SHARED_PACKAGES:
        os.makedirs(os.path.join(TARGET, package), exist_ok=True)
    copied = []
    for source, target in _pairs():
        if not os.path.exists(source):
            print('  missing: %s' % source)
            continue
        shutil.copy2(source, target)
        copied.append(os.path.basename(target))
    return copied


# --------------------------------------------------------------------------- #
# The Polish travels with the modules
# --------------------------------------------------------------------------- #
# A shared module says `_('Top left')` with the English sentence as the
# key. In NVDA that is answered out of the add-on's own `.po`; in Titan
# Access it is answered out of `locale/pl.json`, keyed by the sentence
# itself - and until this step existed nothing put the sentences there, so
# a Polish Titan Access walked its lists in English (704 sentences, on the
# day it was measured). The translation is written ONCE, in the add-on's
# catalogue, and carried across here with the code.
ADDON_PO = os.path.join(ROOT, 'nvda-addon', 'addon', 'locale', 'pl',
                        'LC_MESSAGES', 'nvda.po')
ACCESS_PL = os.path.join(ROOT, 'data', 'components', 'titan access',
                         'locale', 'pl.json')


def shared_sentences():
    """Every string a vendored module passes to ``_()``."""
    import ast
    found = set()
    for name in SHARED:
        path = os.path.join(SOURCE, name)
        try:
            tree = ast.parse(io.open(path, encoding='utf-8').read())
        except Exception:                            # noqa: BLE001
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == '_' and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                found.add(node.args[0].value)
    return found


def addon_polish():
    """``{msgid: msgstr}`` out of the add-on's Polish catalogue."""
    import re
    try:
        text = io.open(ADDON_PO, encoding='utf-8').read()
    except Exception:                                # noqa: BLE001
        return {}

    def unquote(chunk):
        parts = re.findall(r'"((?:[^"\\]|\\.)*)"', chunk)
        raw = ''.join(parts)
        return (raw.encode('utf-8').decode('unicode_escape')
                .encode('latin-1').decode('utf-8'))
    out = {}
    pattern = (r'(?ms)^msgid\s+((?:"(?:[^"\\]|\\.)*"\s*)+)'
               r'^msgstr\s+((?:"(?:[^"\\]|\\.)*"\s*)+)')
    for match in re.finditer(pattern, text):
        try:
            key, value = unquote(match.group(1)), unquote(match.group(2))
        except Exception:                            # noqa: BLE001
            continue
        if key and value:
            out[key] = value
    return out


def polish_missing():
    """The shared sentences the add-on has Polish for and Titan Access
    has not - what `carry_polish` would add."""
    import json
    try:
        have = json.load(io.open(ACCESS_PL, encoding='utf-8'))
    except Exception:                                # noqa: BLE001
        have = {}
    known = addon_polish()
    return sorted(key for key in shared_sentences()
                  if key not in have and key in known)


def carry_polish():
    """Put the add-on's Polish for every shared sentence into pl.json."""
    import json
    missing = polish_missing()
    if not missing:
        return []
    have = json.load(io.open(ACCESS_PL, encoding='utf-8'))
    known = addon_polish()
    for key in missing:
        have[key] = known[key]
    io.open(ACCESS_PL, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(have, ensure_ascii=False, indent=2) + '\n')
    return missing


def main(argv):
    if '--check' in argv:
        same, wrong = check()
        missing = polish_missing()
        if same and not missing:
            print('The shared reader modules are identical in both trees.')
            return 0
        if not same:
            print('They have drifted apart:')
            for one in wrong:
                print('  - %s' % one)
        if missing:
            print('%d shared sentence(s) have Polish in the add-on and not '
                  'in Titan Access - run the script without --check.'
                  % len(missing))
        return 1
    copied = copy()
    print('Vendored %d module(s) into %s:' % (len(copied), TARGET))
    for name in copied:
        print('  %s' % name)
    carried = carry_polish()
    if carried:
        print('Carried the Polish for %d shared sentence(s) into pl.json.'
              % len(carried))
    same, wrong = check()
    if not same:
        for one in wrong:
            print('  still wrong: %s' % one)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
