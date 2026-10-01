"""The translation table survives being reloaded from another thread.

Some thirty modules call ``set_language()`` at import time, and several of
them are imported lazily on worker threads - the Titan-Net window imports
``remote_ui`` on a thread of its own while the GUI thread is still building
the window. ``set_language`` used to empty the shared table and refill it
one .mo file at a time, so an ``_()`` on any other thread during that refill
raised ``KeyError`` for a domain that was not back yet. That was the first
opening of Titan-Net ending in "Titan-Net could not open: KeyError: 'menu'"
and the second opening working.

Run directly: ``python tests/test_translation_threads.py``.
"""
import contextlib
import os
import sys
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.titan_core import translation  # noqa: E402


@contextlib.contextmanager
def slow_catalogues(delay=0.0005):
    """Make every .mo load take a moment, with the GIL released.

    The first load of a catalogue really is a disk read - on this machine a
    OneDrive one - and that is the window the bug lived in. gettext caches
    a catalogue it has loaded once, so without this the reload is over
    before the other thread gets the interpreter back and the race cannot
    be seen.
    """
    original = translation._load_translation_for_domain

    def slow(domain, lang):
        time.sleep(delay)
        return original(domain, lang)

    translation._load_translation_for_domain = slow
    try:
        yield
    finally:
        translation._load_translation_for_domain = original


@contextlib.contextmanager
def reloading_for_ever():
    """A thread that keeps switching the language, as a lazy import does."""
    stop = threading.Event()

    def reload():
        langs = ['en', 'pl']
        i = 0
        while not stop.is_set():
            translation.set_language(langs[i % 2])
            i += 1

    worker = threading.Thread(target=reload, daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=5)
        translation.set_language('pl')


class TheTableIsNeverHalfFilled(unittest.TestCase):

    def setUp(self):
        translation.set_language('pl')

    def test_a_lookup_never_raises_while_another_thread_reloads(self):
        problems = []
        deadline = time.monotonic() + 1.5
        with slow_catalogues(), reloading_for_ever():
            while time.monotonic() < deadline:
                try:
                    text = translation._("Titan-Net - Main Menu")
                except Exception as e:  # pragma: no cover - the bug itself
                    problems.append(repr(e))
                    break
                self.assertIsInstance(text, str)
                self.assertTrue(text)
        self.assertEqual(problems, [])

    def test_every_domain_is_in_the_table_whenever_it_is_read(self):
        short = []
        deadline = time.monotonic() + 1.5
        with slow_catalogues(), reloading_for_ever():
            while time.monotonic() < deadline:
                table = translation._translations
                if len(table) != len(translation.TRANSLATION_DOMAINS):
                    short.append(len(table))
                    break
        self.assertEqual(short, [])


class TheSameLanguageIsLoadedOnce(unittest.TestCase):

    def test_a_second_call_for_the_loaded_language_reads_no_file(self):
        translation.set_language('pl')
        calls = []
        original = translation._load_translation_for_domain
        translation._load_translation_for_domain = (
            lambda domain, lang: calls.append(domain) or original(domain, lang))
        try:
            fn = translation.set_language('pl')
        finally:
            translation._load_translation_for_domain = original
        self.assertEqual(calls, [])
        self.assertIs(fn, translation._)
        self.assertEqual(translation.language_code, 'pl')

    def test_a_different_language_is_really_loaded(self):
        translation.set_language('pl')
        polish = translation._("Titan-Net - Main Menu")
        translation.set_language('en')
        try:
            self.assertEqual(translation.language_code, 'en')
            self.assertEqual(translation._loaded_language, 'en')
            english = translation._("Titan-Net - Main Menu")
            # Both catalogues answer; the Polish one is not the English one.
            self.assertNotEqual(polish, english)
        finally:
            translation.set_language('pl')

    def test_every_module_gets_the_one_function(self):
        a = translation.set_language('pl')
        b = translation.set_language('pl')
        self.assertIs(a, b)
        self.assertIs(a, translation.multi_domain_gettext)


if __name__ == '__main__':
    unittest.main(verbosity=2)
