"""No compiled catalogue may answer with an empty string.

A `.po` carries the work still to do as `msgstr ""`, and GNU msgfmt leaves
those entries OUT of the `.mo` so gettext falls back to the message itself.
A catalogue compiled with them in is far worse in Titan than in an ordinary
program: `translation.multi_domain_gettext` asks every domain in turn and
returns the first answer that DIFFERS from the message - and "" differs from
everything, so ONE empty entry in ONE domain empties that message for the
whole program. That is how the settings window's Cancel button lost its
label, along with 95 other English strings, and an unlabelled button is a
button a screen reader cannot name.

    python tests/test_translation_catalogues.py
"""

import gettext
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
LANGUAGES = os.path.join(TITAN, 'languages')


def catalogues():
    """(language, domain, path) for every compiled catalogue Titan ships."""
    for language in sorted(os.listdir(LANGUAGES)):
        folder = os.path.join(LANGUAGES, language, 'LC_MESSAGES')
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if name.endswith('.mo'):
                yield language, name[:-3], os.path.join(folder, name)


class EveryCatalogue(unittest.TestCase):
    def test_none_of_them_answers_with_nothing(self):
        empty = []
        for language, domain, path in catalogues():
            with open(path, 'rb') as handle:
                catalog = gettext.GNUTranslations(handle)._catalog
            for message, translation in catalog.items():
                # The header is the one entry keyed by the empty string.
                if message == '' or not isinstance(translation, str):
                    continue
                if translation == '':
                    empty.append(f"{language}/{domain}: {message!r}")
        self.assertEqual(
            empty[:20], [],
            f"{len(empty)} message(s) compiled with an empty translation; "
            "msgfmt leaves those out so the message itself is used")

    def test_every_one_of_them_can_be_read(self):
        """A .mo written with the wrong offsets decodes a message in the
        middle of a letter, which is a catalogue that raises rather than one
        that is merely wrong."""
        for language, domain, path in catalogues():
            with open(path, 'rb') as handle:
                try:
                    gettext.GNUTranslations(handle)
                except Exception as error:      # noqa: BLE001 - reported
                    self.fail(f"{language}/{domain} cannot be read: {error}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
