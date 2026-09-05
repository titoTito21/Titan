"""Every method the bridge calls on an Elten control must exist in Elten.

A stub is more forgiving than the real thing, and that is not a small
difference: the stub had `text=` on an edit box, Elten has `set_text`, and
the tests passed while the add-on crashed in front of the user with
`undefined method 'text=' for an instance of EltenAPI::Controls::EditBox`.

So this checks the bridge against ELTEN'S OWN SOURCES - pulled from the
running client through its MCP server, or from a checkout - rather than
against anything written here.

    python tests/check_elten_api.py [path-to-elten-sources]

The sources it needs are the control files plus form.rb; each is read for
`def`, `attr_accessor`, `attr_reader` and `attr_writer`.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.dirname(HERE)

# Which Elten file defines which class the bridge constructs.
CLASSES = {
    'EditBox': 'edit_box.rb',
    'ListBox': 'list_box.rb',
    'Button': 'button.rb',
    'CheckBox': 'check_box.rb',
    'ChoiceListBox': 'choice_list_box.rb',
    'Static': 'static.rb',
    'Form': 'form.rb',
}
# Every control inherits FormBase (`on`, `trigger`, `focus`, ...), which
# lives in form.rb, plus the mixins in form_field.rb.
BASE_FILES = ('form_field.rb',)
BASE_CLASSES = (('form.rb', 'FormBase'),)

# Ruby's own, and things every object answers to.
RUBY = {
    'to_s', 'to_i', 'to_f', 'to_a', 'inspect', 'nil?', 'is_a?', 'kind_of?',
    'respond_to?', 'class', 'send', 'freeze', 'dup', 'clone', 'hash', 'tap',
    'instance_variable_get', 'instance_variable_set', 'each', 'map', 'size',
    'length', 'empty?', 'include?', 'push', 'first', 'last', 'find', 'select',
    'reject', 'join', 'strip', 'split', 'sub', 'gsub', 'start_with?',
    'end_with?', 'call', 'index',
}


def defined_methods(path):
    """Every method name a Ruby file defines."""
    names = set()
    text = open(path, encoding='utf-8', errors='replace').read()
    for match in re.finditer(r'^\s*def\s+(?:self\.)?([a-zA-Z_][\w]*[?!=]?)', text, re.M):
        names.add(match.group(1))
    for match in re.finditer(r'attr_(accessor|reader|writer)\s+(.+)', text):
        kind, rest = match.group(1), match.group(2)
        for symbol in re.findall(r':([a-zA-Z_][\w]*)', rest):
            names.add(symbol)
            if kind in ('accessor', 'writer'):
                names.add(symbol + '=')
    return names


def class_block(path, name):
    """The lines of one class, by indentation - so FormBase's methods are
    not confused with Form's."""
    text = open(path, encoding='utf-8', errors='replace').read().split('\n')
    start = None
    indent = 0
    for number, line in enumerate(text):
        match = re.match(r'(\s*)class\s+' + re.escape(name) + r'\b', line)
        if match:
            start = number
            indent = len(match.group(1))
            break
    if start is None:
        return ''
    out = []
    for line in text[start + 1:]:
        stripped = line.strip()
        if stripped.startswith(('class ', 'module ')) and \
           len(line) - len(line.lstrip()) <= indent:
            break
        out.append(line)
    return '\n'.join(out)


def methods_in(text):
    names = set()
    for match in re.finditer(r'^\s*def\s+(?:self\.)?([a-zA-Z_][\w]*[?!=]?)', text, re.M):
        names.add(match.group(1))
    for match in re.finditer(r'attr_(accessor|reader|writer)\s+(.+)', text):
        kind, rest = match.group(1), match.group(2)
        for symbol in re.findall(r':([a-zA-Z_][\w]*)', rest):
            names.add(symbol)
            if kind in ('accessor', 'writer'):
                names.add(symbol + '=')
    return names


def bridge_files():
    for name in sorted(os.listdir(BRIDGE)):
        if name.endswith('.rb') and name != 'install.rb':
            yield os.path.join(BRIDGE, name)


def calls_by_variable(text):
    """{variable -> class} for locals and ivars built from a known control,
    then every `variable.method` used on them."""
    built = {}
    pattern = r'(@?\w+)\s*=\s*(' + '|'.join(CLASSES) + r')\.new'
    for match in re.finditer(pattern, text):
        built[match.group(1)] = match.group(2)
    uses = []
    for variable, klass in built.items():
        for match in re.finditer(re.escape(variable) + r'\.([a-zA-Z_][\w]*[?!]?)(\s*=(?!=))?',
                                 text):
            method = match.group(1) + ('=' if match.group(2) else '')
            uses.append((variable, klass, method))
    return uses


def main():
    sources = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.environ.get('TEMP', '/tmp'), 'titan_elten_probe', 'elten_src')
    if not os.path.isdir(sources):
        print(f"Elten's sources are not at {sources}.")
        print("Read them from the running client (MCP elten_source_read) or "
              "point this at a checkout.")
        return 2

    base = set()
    for name in BASE_FILES:
        path = os.path.join(sources, name)
        if os.path.isfile(path):
            base |= defined_methods(path)
    for filename, klass in BASE_CLASSES:
        path = os.path.join(sources, filename)
        if os.path.isfile(path):
            base |= methods_in(class_block(path, klass))

    known = {}
    for klass, filename in CLASSES.items():
        path = os.path.join(sources, filename)
        if not os.path.isfile(path):
            print(f"missing source for {klass}: {filename}")
            continue
        known[klass] = defined_methods(path) | base | RUBY

    problems = []
    for path in bridge_files():
        text = open(path, encoding='utf-8', errors='replace').read()
        for variable, klass, method in calls_by_variable(text):
            if klass not in known:
                continue
            if method in known[klass]:
                continue
            problems.append((os.path.basename(path), variable, klass, method))

    if not problems:
        print("every control method the bridge calls exists in Elten")
        return 0
    print("methods Elten does not have:")
    for filename, variable, klass, method in sorted(set(problems)):
        print(f"  {filename}: {variable} ({klass}) . {method}")
    return 1


if __name__ == '__main__':
    sys.exit(main())
