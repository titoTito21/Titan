"""Every shipped TitanTTS engine must be usable, not merely importable.

There was no suite for `data/titantts engines/` at all, and that is how
DECtalk shipped with `get_config_fields()` raising
``NameError: name '_' is not defined``: the module imported perfectly, the
engine appeared in the list, and its one setting ("Shorten pauses") could not
be built by the settings panel or reached through `tts_engine.list_settings`.

An engine's configuration fields ARE its settings, so a `get_config_fields()`
that raises is an engine with no reachable settings whatever.

The convention these engines follow (eloquence wrote it first) is:

    # the launcher installs gettext's _ as a builtin; fall back to a no-op
    try:
        _
    except NameError:
        def _(s):
            return s

Titan does NOT install `_` as a builtin, so an engine that uses `_()` without
that guard raises the moment its fields are asked for.

Run directly: ``python tests/test_tts_engines.py``. Nothing here speaks,
opens a window, or plays a sound - only the class-level metadata is touched.
"""

import ast
import importlib.util
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINES = os.path.join(REPO, 'data', 'titantts engines')
if REPO not in sys.path:
    sys.path.insert(0, REPO)


def engine_dirs():
    if not os.path.isdir(ENGINES):
        return []
    out = []
    for name in sorted(os.listdir(ENGINES)):
        path = os.path.join(ENGINES, name, '__engine__.py')
        if os.path.isfile(path):
            out.append((name, path))
    return out


def load(name, path):
    mod_name = f'_tts_engine_under_test_{name}'
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return mod_name, module


def own_engine_classes(mod_name, module):
    """Only classes defined IN this module - not the imported base class,
    whose get_config_fields() answers [] and would pass for anything."""
    out = []
    for attr in dir(module):
        obj = getattr(module, attr)
        if isinstance(obj, type) \
                and getattr(obj, '__module__', '') == mod_name \
                and hasattr(obj, 'get_config_fields'):
            out.append(obj)
    return out


class EveryEngineIsThere(unittest.TestCase):
    def test_the_engines_are_found(self):
        self.assertTrue(engine_dirs(), 'no __engine__.py found at all')


class TheSettingsOfEveryEngineCanBeBuilt(unittest.TestCase):
    """The fault DECtalk shipped with, asked of all of them."""

    def test_get_config_fields_never_raises(self):
        for name, path in engine_dirs():
            with self.subTest(engine=name):
                mod_name, module = load(name, path)
                classes = own_engine_classes(mod_name, module)
                self.assertTrue(
                    classes, f'{name}: no engine class defined in its own module')
                for cls in classes:
                    try:
                        fields = cls.get_config_fields()
                    except Exception as exc:      # noqa: BLE001 - that IS the test
                        self.fail(f'{name}.{cls.__name__}.get_config_fields() '
                                  f'raised {type(exc).__name__}: {exc}')
                    self.assertIsInstance(
                        fields, (list, tuple),
                        f'{name}: get_config_fields answered '
                        f'{type(fields).__name__}, not a list')

    def test_every_field_has_a_key_and_a_label(self):
        """A field with no key cannot be set; one with no label is a control
        a screen reader has nothing to say about."""
        for name, path in engine_dirs():
            with self.subTest(engine=name):
                mod_name, module = load(name, path)
                for cls in own_engine_classes(mod_name, module):
                    for field in cls.get_config_fields() or []:
                        self.assertIsInstance(field, dict, f'{name}: {field!r}')
                        self.assertTrue(field.get('key'),
                                        f'{name}: a field with no key: {field!r}')
                        self.assertTrue(field.get('label'),
                                        f'{name}: a field with no label: {field!r}')


class AnEngineThatTranslatesGuardsIt(unittest.TestCase):
    """Read statically, so it holds for an engine this machine cannot import."""

    @staticmethod
    def uses_underscore(tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == '_':
                return True
        return False

    @staticmethod
    def binds_underscore(tree):
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name == '_':
                return True
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == '_':
                        return True
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    if (a.asname or a.name).split('.')[-1] == '_':
                        return True
        return False

    def test_an_engine_using_gettext_binds_it(self):
        for name, path in engine_dirs():
            with self.subTest(engine=name):
                tree = ast.parse(open(path, encoding='utf-8',
                                      errors='replace').read())
                if not self.uses_underscore(tree):
                    continue
                self.assertTrue(
                    self.binds_underscore(tree),
                    f"{name}/__engine__.py calls _() but never binds it, and "
                    f"Titan does not install gettext's _ as a builtin - so "
                    f"every one of those calls raises NameError. Add the "
                    f"try/except NameError fallback the other engines use.")



class SMPSaysTheWholeLabel(unittest.TestCase):
    """SMPRenderer stops dead on most punctuation and takes the rest of the
    text with it - measured by feeding it "kot <char> pies" for every
    printable character. "Ctrl+S" came out as "Ctrl", "e-mail" as "e", and
    a label with a slash, a bracket or a quotation mark lost everything
    after it. Under NVDA the symbol level had already replaced those before
    the driver saw them; Titan hands the engine the text as it is, so the
    engine does it itself: the symbols that mean something when read out
    become the Polish word for them, the rest become a space."""

    @classmethod
    def setUpClass(cls):
        found = [path for name, path in engine_dirs() if name == 'SMP']
        cls.module = load('SMP', found[0])[1] if found else None

    def normalize(self, text):
        if self.module is None:
            self.skipTest('the SMP engine is not shipped')
        return self.module._normalize_text(text)

    def test_a_dash_a_slash_and_a_bracket_do_not_swallow_the_rest(self):
        self.assertEqual(self.normalize('e-mail'), 'e mail')
        self.assertEqual(self.normalize('kot-pies-kura'), 'kot pies kura')
        self.assertEqual(self.normalize('a/b'), 'a b')
        self.assertEqual(self.normalize('(nawias) "cytat" [x]'),
                         'nawias cytat ks')
        self.assertEqual(self.normalize('dwa – trzy'), 'dwa trzy')

    def test_a_symbol_that_means_something_is_said_as_a_word(self):
        self.assertEqual(self.normalize('Ctrl+S'), 'Ctrl plus S')
        self.assertEqual(self.normalize('50%'), '50 procent')
        self.assertEqual(self.normalize('a & b'), 'a i b')

    def test_the_punctuation_the_bridge_chunks_on_is_kept(self):
        """`,:.?!;` are where the bridge splits the text for the renderer;
        taking them out would run the sentences together."""
        self.assertEqual(self.normalize('lista, 3 z 10.'), 'lista, 3 z 10.')
        self.assertEqual(self.normalize('Czy? Tak!'), 'Czy? Tak!')

    def test_every_swallowing_character_is_covered(self):
        """The measured list, so a character put back by accident fails."""
        for ch in '"#$%&\'()*+-/<=>@[\\]^_`{|}~':
            said = self.normalize('kot %s pies' % ch)
            self.assertNotIn(ch, said, ch)
            self.assertTrue(said.startswith('kot ') and said.endswith(' pies'),
                            '%r -> %r' % (ch, said))


if __name__ == '__main__':
    unittest.main(verbosity=2)
