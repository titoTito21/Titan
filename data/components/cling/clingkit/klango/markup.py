# -*- coding: utf-8 -*-
"""Klango's XML, parsed the way its own library expects to get it back.

`k_XMLParsePS` is native in Klango and the library leans on it for two very
different jobs: reading real XML (the typing course's lessons are KTouch files)
and taking the markup out of its own texts, which are written with `<b>`, `<u>`
and `<br>` in them. So the parser has to be tolerant - an unclosed `<br>`, a
stray `&`, a fragment that is not a document - because a help text that fails to
parse is a screen that never appears.

A node is what the library reads: `t.name` the tag, `t.attr` its attributes and
the array part its children, each either a string or another node.
"""

import re

_TAG = re.compile(r'<\s*(/?)\s*([A-Za-z_][\w:.-]*)((?:\s+[\w:.-]+\s*=\s*'
                  r'(?:"[^"]*"|\'[^\']*\'|[^\s>]*))*)\s*(/?)\s*>')
_ATTR = re.compile(r'([\w:.-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]*))')
_ENTITIES = {'amp': '&', 'lt': '<', 'gt': '>', 'quot': '"', 'apos': "'",
             'nbsp': ' '}
#: Tags that never have an end tag. `br` is the one Klango's own texts use.
VOID = frozenset(('br', 'sp', 'tab', 'img', 'hr', 'meta', 'link'))


def unescape(text):
    def one(match):
        name = match.group(1)
        if name.startswith('#'):
            try:
                return chr(int(name[2:], 16) if name[1:2].lower() == 'x'
                           else int(name[1:]))
            except ValueError:
                return match.group(0)
        return _ENTITIES.get(name.lower(), match.group(0))
    return re.sub(r'&([#\w]+);', one, text)


def parse(text, make_table):
    """Parse markup into Klango's node shape. Returns the root node, or None."""
    text = str(text or '')
    if not text.strip():
        return None
    root = {'name': '', 'attr': {}, 'children': []}
    stack = [root]
    position = 0
    for match in _TAG.finditer(text):
        before = text[position:match.start()]
        if before:
            stack[-1]['children'].append(unescape(before))
        position = match.end()
        closing, name, attributes, empty = match.groups()
        lowered = name.lower()
        if closing:
            # An end tag closes the nearest matching start; one that matches
            # nothing is ignored rather than throwing the rest away.
            for depth in range(len(stack) - 1, 0, -1):
                if stack[depth]['name'] == lowered:
                    del stack[depth:]
                    break
            continue
        node = {'name': lowered, 'attr': _attributes(attributes),
                'children': []}
        stack[-1]['children'].append(node)
        if not empty and lowered not in VOID:
            stack.append(node)
    tail = text[position:]
    if tail:
        stack[-1]['children'].append(unescape(tail))
    return _to_lua(root, make_table)


def _attributes(text):
    out = {}
    for match in _ATTR.finditer(text or ''):
        name = match.group(1)
        value = match.group(2) or match.group(3) or match.group(4) or ''
        out[name.lower()] = unescape(value)
    return out


def _to_lua(node, make_table, depth=0):
    table = make_table({})
    table.raw_set('name', node['name'] or None)
    attributes = make_table({})
    for key, value in node['attr'].items():
        attributes.raw_set(key, value)
    table.raw_set('attr', attributes)
    if depth > 60:
        return table
    for index, child in enumerate(node['children'], start=1):
        table.raw_set(index, child if isinstance(child, str)
                      else _to_lua(child, make_table, depth + 1))
    return table
