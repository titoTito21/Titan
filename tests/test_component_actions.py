"""Every action a component DECLARES is one Titan can actually run.

`actions/manifest.py`'s `_parse_action` reads `raw['name']` and drops an
entry that has none - "an action has no usable 'name'; ignored" - and the
Elten API bridge wrote `id`, so all four of its actions were declared and
none of them existed: it offered Titan the three generic component actions
and nothing of its own. Nothing said so; the entries were simply gone.

This reads every component's `TITAN_ACTIONS` through the REAL parser and
fails on anything it would drop or silently rename.

    python tests/test_component_actions.py
"""

import ast
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TITAN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENTS = os.path.join(TITAN, 'data', 'components')


def declared_in(path):
    """The `TITAN_ACTIONS` entries of one component, read statically - the
    component itself is not imported, because most of them want wx."""
    source = io.open(path, encoding='utf-8', errors='replace').read()
    if 'TITAN_ACTIONS' not in source:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError as error:                       # pragma: no cover
        raise AssertionError(f"{path}: {error}")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(getattr(target, 'id', '') == 'TITAN_ACTIONS'
                   for target in node.targets):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            return []
        entries = []
        for element in node.value.elts:
            if not isinstance(element, ast.Dict):
                continue
            entry = {}
            for key, value in zip(element.keys, element.values):
                if not isinstance(key, ast.Constant):
                    continue
                entry[key.value] = (value.value
                                    if isinstance(value, ast.Constant)
                                    else '<expression>')
            entries.append(entry)
        return entries
    return []


class EveryDeclaredActionIsReal(unittest.TestCase):
    def components(self):
        for name in sorted(os.listdir(COMPONENTS)):
            init = os.path.join(COMPONENTS, name, 'init.py')
            if os.path.isfile(init):
                yield name, init

    def test_every_entry_has_the_name_the_parser_reads(self):
        """`_parse_action`'s first line is `name = slug(raw.get('name', ''))`
        and an entry with none is dropped with a warning nobody reads. That
        is the whole failure: the Elten bridge wrote `id`."""
        from src.titan_core.actions.manifest import slug

        dropped = []
        checked = 0
        for name, init in self.components():
            for entry in declared_in(init) or []:
                checked += 1
                if not slug(entry.get('name', '')):
                    dropped.append(f"{name}: {entry!r} has no usable 'name'")
        self.assertEqual(dropped, [],
                         f"{len(dropped)} of {checked} declared action(s) "
                         "would be dropped before Titan ever saw them")
        self.assertGreater(checked, 10, 'no declarations were found at all')

    def test_the_handler_is_something_that_can_be_called(self):
        """`run` is the callable and `handler` is a method NAME. A callable
        under `handler` is accepted by `resolve_callable` but ignored by the
        parser, so the two must not be confused."""
        wrong = []
        for name, init in self.components():
            for entry in declared_in(init) or []:
                if 'handler' in entry and entry['handler'] == '<expression>':
                    wrong.append(f"{name}: '{entry.get('name')}' passes a "
                                 "callable as 'handler'; it belongs in 'run'")
        self.assertEqual(wrong, [])

    def test_the_elten_bridge_offers_its_own(self):
        entries = declared_in(os.path.join(COMPONENTS, 'elten_bridge',
                                           'init.py'))
        self.assertEqual([entry.get('name') for entry in entries],
                         ['list_applications', 'details', 'run', 'status',
                          'log'])

    def test_cling_offers_its_own(self):
        entries = declared_in(os.path.join(COMPONENTS, 'cling', 'init.py'))
        names = [entry.get('name') for entry in entries]
        for wanted in ('list_applications', 'run', 'details', 'scores',
                       'install', 'account', 'status'):
            self.assertIn(wanted, names)


if __name__ == '__main__':
    unittest.main(verbosity=2)
