"""The add-on's Polish catalogue, checked against what it actually says.

Elten reads an unpacked application's catalogue straight off its folder, so
`locale/pl.mo` ships as a compiled file with no `.po` beside it. Two things
can go wrong with one, and only one of them is visible without looking:

* **An entry with an EMPTY translation.** gettext then answers the empty
  string for that message - a label that is not merely English but absent,
  which for a screen reader is a control with no name. (Titan's own `_` is
  worse off still: it returns the first answer that DIFFERS from the message,
  so one empty entry in one domain empties that message program-wide. That is
  how the settings window's Cancel button lost its label.)
* **A string the code says and the catalogue has not got.** That one is only
  English, which is a degradation rather than a fault - so it is COUNTED and
  named, not failed on. The exceptions are the strings below, which are
  either the words a user was promised or the ones a wrong translation would
  make dangerous.

    python tests/check_translations.py
"""

import gettext
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.dirname(HERE)
CATALOGUE = os.path.join(BRIDGE, 'locale', 'pl.mo')

#: These must be in the catalogue. The consent question above all: it is the
#: sentence the user is answering, and one that arrives in English on a
#: Polish Elten is one they cannot be said to have agreed to.
REQUIRED = (
    "The AI assistant will use data stored on the Elten portal. Do you agree "
    "to share the necessary data with TCE?",
    "Share Elten's data with TCE",
    "TCE settings...",
    "Show Elten's notifications in Titan too",
    "Minimize",
    "Bring Titan back",
)

#: `_("...")` and `_('...')`, single-line, which is how every one of them is
#: written here - a message split across two literals is looked up as the
#: joined text and would never be found anyway.
SAID = re.compile(r'\b_\(\s*"((?:[^"\\]|\\.)*)"\s*[,)]')


def said_in_the_add_on():
    found = {}
    for name in sorted(os.listdir(BRIDGE)):
        if not name.endswith('.rb'):
            continue
        text = open(os.path.join(BRIDGE, name), encoding='utf-8',
                    errors='replace').read()
        for message in SAID.findall(text):
            found.setdefault(message.replace('\\"', '"').replace('\\n', '\n'),
                             []).append(name)
    return found


def main():
    if not os.path.isfile(CATALOGUE):
        print("locale/pl.mo is missing")
        return 1
    with open(CATALOGUE, 'rb') as handle:
        catalogue = gettext.GNUTranslations(handle)._catalog

    problems = 0
    empty = [message for message, translation in catalogue.items()
             if message != '' and isinstance(translation, str)
             and translation == '']
    if empty:
        problems += 1
        print(f"{len(empty)} entry(ies) compiled with an EMPTY translation: "
              f"{empty[:10]}")

    for message in REQUIRED:
        if not catalogue.get(message):
            problems += 1
            print(f"not translated, and must be: {message!r}")

    said = said_in_the_add_on()
    untranslated = sorted(m for m in said if not catalogue.get(m))
    print(f"{len(said)} string(s) said, {len(said) - len(untranslated)} "
          f"translated, {len(untranslated)} English only")
    for message in untranslated[:15]:
        print(f"  - {message!r} ({', '.join(sorted(set(said[message])))})")
    if len(untranslated) > 15:
        print(f"  ... and {len(untranslated) - 15} more")
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
