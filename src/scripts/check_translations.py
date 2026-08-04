#!/usr/bin/env python
"""
Check the translation catalogs for entries that say the wrong thing.

Why this exists
---------------
``pybabel update`` never leaves a new string empty: it fills it with the
translation of whatever old string looked closest and marks the entry
``#, fuzzy``. Nobody goes back over those, so a guess ships. Real examples
found in this repo:

* ``"Notifications"`` displayed as "Kod weryfikacyjny" (verification code)
* ``"{name} declined the call"`` displayed as "Konczenie polaczenia"
* the file-dialog wildcard in ``menu`` silently lost ``*.TCEPACKAGE``, so
  those files were invisible in the picker
* ``"Extraction complete"`` and ``"Extracting files... {}%"`` sharing one
  translation, so the progress meter never changed and never said it finished

Three checks, because each catches what the others cannot
---------------------------------------------------------
1. ``fuzzy``        - the entry is a guess and nobody confirmed it.
2. ``placeholders`` - msgid and msgstr do not carry the same ``{tokens}``.
                      A translation pasted from another string usually shows
                      up here first.
3. ``shared``       - one translation serving two different msgids in the same
                      catalog. This is what a paste error looks like when the
                      placeholders happen to line up, and checks 1 and 2 are
                      both blind to it. Six live bugs were found only by this.

English is the source language, so a fourth check reports English entries
whose msgstr says something other than the msgid. ``--fix-english`` applies
the only correct answer for those - the msgid itself.

Some msgids in this repo are written in Polish, and the English catalog
translates *those* for real; overwriting them with the msgid would be the very
damage this script exists to undo. Spelling cannot decide it ("Zapisz" is
Polish and pure ASCII), so the Polish catalog is used as the oracle: a msgid
whose Polish translation simply repeats it was Polish to begin with, and is
left alone. The one case that slips through is a Polish, accent-free msgid
that is *also* untranslated in the Polish catalog - rare enough to live with,
and it only ever costs a report, since ``--fix-english`` is never automatic.

Usage
-----
    python src/scripts/check_translations.py            # report everything
    python src/scripts/check_translations.py -D network # one domain
    python src/scripts/check_translations.py --fix-english
    python src/scripts/check_translations.py --quiet    # only the summary

Exits non-zero when anything is reported, so it can gate a release.
"""

import argparse
import glob
import io
import os
import re
import sys
from collections import defaultdict

try:
    from babel.messages.pofile import read_po, write_po
except ImportError:
    print("[ERROR] babel not found. Install it with: pip install babel")
    sys.exit(2)

LANGUAGES_DIR = 'languages'
SOURCE_LANGUAGE = 'en'

# ``{name}``, ``{}``, ``%s``, ``%d``, ``%(name)s`` - everything the codebase
# formats with. A missing or renamed one is either a crash or a wrong message.
PLACEHOLDER = re.compile(r'\{[^{}]*\}|%[sd]|%\([^)]*\)[sd]')

# Below this length a shared translation is usually honest: "OK", "Nazwa" and
# "Anuluj" really do translate several different labels.
SHARED_MIN_LENGTH = 18

# Pairs that legitimately share one translation - a difference that exists in
# English but not in the target language. Each entry is the set of msgids that
# are allowed to collide; add to this list rather than weakening the check.
ALLOWED_SHARED = [
    {'Online Users', 'Users online'},
    {'Invisible Interface', 'Invisible interface'},
    {'Voice Call', 'Voice call'},
    {'Confirm Delete', 'Confirm Deletion'},
    {'List All Moderators', 'List of all moderators'},
    {'Tracked Attackers', 'Tracked attackers'},
    {'Failed to load sessions', 'Failed to load session'},
    {'Incorrect password', 'Invalid password'},
    {'Connection failed', 'Call failed'},
    {'Send failed', 'Upload failed'},
    # Some msgids in this repo are already Polish; the Polish catalog then
    # repeats them, which collides with the translation of the English twin.
    {'Połączenie nawiązane', 'Call connected'},
]


class Finding:
    """One problem, in one entry, of one catalog."""

    def __init__(self, kind, path, msgid, msgstr, detail=''):
        self.kind = kind
        self.path = path
        self.msgid = msgid
        self.msgstr = msgstr
        self.detail = detail

    def report(self):
        lines = [f"  [{self.kind}] {shorten(self.msgid)}",
                 f"      says: {shorten(self.msgstr) if self.msgstr else '(empty)'}"]
        if self.detail:
            lines.append(f"      {self.detail}")
        return '\n'.join(lines)


def shorten(text, limit=72):
    text = (text or '').replace('\n', '\\n')
    return repr(text if len(text) <= limit else text[:limit] + '...')


def is_ascii(text):
    """A msgid with no accented characters is (in this repo) English."""
    try:
        text.encode('ascii')
        return True
    except UnicodeEncodeError:
        return False


def translatable(message):
    """Real entries only - not the header, not plural forms."""
    return bool(message.id) and isinstance(message.id, str)


def catalog_paths(languages=None, domains=None):
    """Every catalog as ``(path, language, domain)``.

    The language is read from the directory two levels up rather than from a
    fixed position in the string, so this works whatever ``LANGUAGES_DIR`` is
    set to - an absolute path included.
    """
    paths = []
    for path in sorted(glob.glob(os.path.join(
            LANGUAGES_DIR, '*', 'LC_MESSAGES', '*.po'))):
        language = os.path.basename(os.path.dirname(os.path.dirname(path)))
        domain = os.path.splitext(os.path.basename(path))[0]
        if languages and language not in languages:
            continue
        if domains and domain not in domains:
            continue
        paths.append((path, language, domain))
    return paths


def native_msgids(domain):
    """msgids that are already written in a target language, not in English.

    Some strings in this codebase were written in Polish, so the *English*
    catalog is where they get a real translation - one that must never be
    overwritten with the msgid. The tell is the Polish catalog: when its
    translation simply repeats the msgid, the msgid was Polish to begin with.
    Spelling alone cannot decide this ("Zapisz" is Polish and pure ASCII).
    """
    native = set()
    for path, language, _domain in catalog_paths(domains=[domain]):
        if language == SOURCE_LANGUAGE:
            continue
        try:
            with io.open(path, encoding='utf-8') as handle:
                catalog = read_po(handle)
        except Exception:
            continue
        for message in catalog:
            if translatable(message) and message.string == message.id:
                native.add(message.id)
    return native


# --------------------------------------------------------------------- checks
def check_fuzzy(catalog, path):
    return [Finding('fuzzy', path, m.id, m.string,
                    'pybabel guessed this from another string - confirm or replace it')
            for m in catalog if translatable(m) and 'fuzzy' in m.flags]


def check_placeholders(catalog, path):
    findings = []
    for message in catalog:
        if not translatable(message) or not message.string:
            continue
        wanted = sorted(PLACEHOLDER.findall(message.id))
        got = sorted(PLACEHOLDER.findall(message.string))
        if wanted != got:
            findings.append(Finding(
                'placeholders', path, message.id, message.string,
                f'msgid has {wanted or "none"}, msgstr has {got or "none"}'))
    return findings


def check_shared(catalog, path):
    """One translation used for two different msgids in the same catalog."""
    by_translation = defaultdict(list)
    for message in catalog:
        if not translatable(message) or not message.string:
            continue
        if len(message.string) < SHARED_MIN_LENGTH:
            continue
        by_translation[message.string].append(message.id)

    findings = []
    for translation, msgids in by_translation.items():
        if len(msgids) < 2:
            continue
        if any(set(msgids) <= allowed for allowed in ALLOWED_SHARED):
            continue
        findings.append(Finding(
            'shared', path, msgids[0], translation,
            'also used for: ' + ', '.join(shorten(other, 48)
                                          for other in msgids[1:])))
    return findings


def is_english_msgid(message, native):
    """Whether this msgid is English, and so may only repeat itself."""
    return is_ascii(message.id) and message.id not in native


def check_english(catalog, path, native=frozenset()):
    """In the source language a translation may only repeat its msgid."""
    findings = []
    for message in catalog:
        if not translatable(message) or not message.string:
            continue
        if message.string == message.id or not is_english_msgid(message, native):
            continue
        findings.append(Finding(
            'english', path, message.id, message.string,
            'English is the source language - this must repeat the msgid'))
    return findings


def fix_english(path, catalog, native=frozenset()):
    """Set every wrong English entry to its own msgid. Returns how many."""
    fixed = 0
    for message in catalog:
        if not translatable(message) or not is_english_msgid(message, native):
            continue
        wrong = message.string and message.string != message.id
        if not wrong and 'fuzzy' not in message.flags:
            continue
        if wrong:
            message.string = message.id
            fixed += 1
        message.flags.discard('fuzzy')
    if fixed:
        with io.open(path, 'wb') as handle:
            write_po(handle, catalog)
    return fixed


# ----------------------------------------------------------------------- main
def run(languages=None, domains=None, quiet=False, fix_en=False):
    paths = catalog_paths(languages, domains)
    if not paths:
        print("[ERROR] No catalogs matched. Run this from the project root.")
        return 2

    all_findings = []
    repaired = 0
    native_cache = {}

    for path, language, domain in paths:
        with io.open(path, encoding='utf-8') as handle:
            catalog = read_po(handle)

        native = frozenset()
        if language == SOURCE_LANGUAGE:
            if domain not in native_cache:
                native_cache[domain] = native_msgids(domain)
            native = native_cache[domain]

        if fix_en and language == SOURCE_LANGUAGE:
            count = fix_english(path, catalog, native)
            repaired += count
            if count and not quiet:
                print(f"[FIXED] {path}: {count} entr"
                      f"{'y' if count == 1 else 'ies'} set to the msgid")
            with io.open(path, encoding='utf-8') as handle:
                catalog = read_po(handle)

        findings = (check_fuzzy(catalog, path) +
                    check_placeholders(catalog, path) +
                    check_shared(catalog, path))
        if language == SOURCE_LANGUAGE:
            findings += check_english(catalog, path, native)

        # One entry can trip several checks; report it once, worst kind first.
        seen = {}
        for finding in findings:
            seen.setdefault((finding.msgid, finding.kind), finding)
        findings = list(seen.values())

        if findings and not quiet:
            print(f"\n{path}  ({len(findings)})")
            for finding in findings:
                print(finding.report())
        all_findings += findings

    print("\n" + "=" * 60)
    if fix_en:
        print(f"Repaired {repaired} English entr"
              f"{'y' if repaired == 1 else 'ies'}")
    if not all_findings:
        print(f"[OK] {len(paths)} catalogs checked, nothing to fix")
        print("=" * 60)
        return 0

    by_kind = defaultdict(int)
    for finding in all_findings:
        by_kind[finding.kind] += 1
    print(f"[PROBLEM] {len(all_findings)} entries in {len(paths)} catalogs:")
    for kind, count in sorted(by_kind.items()):
        print(f"    {kind:<13} {count}")
    print()
    print("A 'fuzzy' or 'shared' entry is text a user will read that says")
    print("something other than what the code meant. Fix the .po file and")
    print("recompile with: pybabel compile -d languages -D <domain>")
    if by_kind.get('english') and not fix_en:
        print("Run again with --fix-english to repair the English ones.")
    print("=" * 60)
    return 1


def main():
    parser = argparse.ArgumentParser(
        description="Find translations that say the wrong thing.")
    parser.add_argument('-D', '--domain', action='append', dest='domains',
                        help="only this domain (repeatable)")
    parser.add_argument('-l', '--language', action='append', dest='languages',
                        help="only this language (repeatable)")
    parser.add_argument('--fix-english', action='store_true',
                        help="set wrong English entries to their own msgid")
    parser.add_argument('-q', '--quiet', action='store_true',
                        help="print only the summary")
    args = parser.parse_args()

    return run(languages=args.languages, domains=args.domains,
               quiet=args.quiet, fix_en=args.fix_english)


if __name__ == '__main__':
    sys.exit(main())
