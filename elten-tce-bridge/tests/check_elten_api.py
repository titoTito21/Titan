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


#: Where each class is defined, for reading its CONSTRUCTOR.
BUILT = dict(CLASSES, TableBox='table_box.rb', FormTimer='form.rb',
             FilesTree='files_tree.rb')


def constructor(path, klass):
    """{keywords, positional} for a class's own `initialize`, or None.

    **Read from the whole file, and chosen by shape.** Elten's control
    files are not consistently indented - in `list_box.rb` the nested
    `class Flags` sits at column 0 while the `class ListBox` that holds it
    is at column 4 - so neither indentation nor counting `end`s (every
    `def`, `if` and `do` closes with one) identifies which `initialize`
    belongs to the control. What does is the SHAPE: a control's
    constructor is the one carrying the options, and a helper struct's is
    positional. Checked against all nine of the classes the bridge builds.
    """
    text = open(path, encoding='utf-8', errors='replace').read()
    here = re.search(r'class\s+' + re.escape(klass) + r'\b', text)
    if not here:
        return None
    # A file may hold two classes this cares about - `form.rb` has both
    # `Form` and `FormTimer` - so it is cut where ANOTHER of them begins,
    # and nowhere else: cutting at every `class` would take `ListBox`'s
    # own constructor away, since two helper classes are declared before
    # it.
    end = len(text)
    for other in BUILT:
        if other == klass:
            continue
        match = re.search(r'class\s+' + re.escape(other) + r'\b',
                          text[here.end():])
        if match:
            end = min(end, here.end() + match.start())
    text = text[here.start():end]
    best = None
    for match in re.finditer(r'def\s+initialize\s*\((.*)\)', text):
        shape = _parameters(match.group(1))
        if best is None or len(shape['keywords']) > len(best['keywords']):
            best = shape
    return best


def _parameters(inside):
    keywords, positional = set(), 0
    depth, piece, pieces = 0, '', []
    for char in inside + ',':
        if char in '([{':
            depth += 1
        elif char in ')]}':
            depth -= 1
        if char == ',' and depth == 0:
            pieces.append(piece.strip())
            piece = ''
        else:
            piece += char
    for one in pieces:
        if not one or one.startswith('&'):
            continue
        name = one.split('=')[0].split(':')[0].strip().lstrip('*')
        if re.match(r'^[a-zA-Z_]\w*\s*:', one):
            keywords.add(name)
        else:
            positional += 1
    return {'keywords': keywords, 'positional': positional}


def events_of(path, klass):
    """Every event a class really fires, from its own `trigger(:name)`.

    **A method that exists says nothing about the name passed to it.** A
    control's `on` is inherited from `FormBase`, so `on(:changed)` checks
    out perfectly - and Elten fires `:change` on a check box and an edit
    box, `:move` and `:select` on a list, and only `:move` on a table. Not
    one tick box, field, option or row selection ever reached the
    application.
    """
    text = open(path, encoding='utf-8', errors='replace').read()
    here = re.search(r'class\s+' + re.escape(klass) + r'\b', text)
    if not here:
        return set()
    return set(re.findall(r'trigger\(\s*:([a-z_]\w*)', text[here.start():]))


def bindings(text):
    """Every `variable.on(:name)` in the bridge, with its class."""
    built = {}
    pattern = r'(@?\w+)\s*=\s*(' + '|'.join(BUILT) + r')\.new'
    for match in re.finditer(pattern, text):
        built[match.group(1)] = match.group(2)
    # `bound.each do |described, widget| ... widget.on(:move)` - the
    # variable is not assigned from a constructor, so what it holds is
    # read from the one function that builds them.
    found = []
    for variable, klass in built.items():
        for match in re.finditer(re.escape(variable) +
                                 r'\.on\(\s*:([a-z_]\w*)', text):
            found.append((klass, match.group(1),
                          text[:match.start()].count('\n') + 1))
    return found


def constructions(text):
    """Every `Klass.new(...)` in the bridge, with the keywords it passes."""
    found = []
    pattern = r'\b(' + '|'.join(BUILT) + r')\.new\s*\('
    for match in re.finditer(pattern, text):
        index, depth = match.end() - 1, 0
        while index < len(text):
            char = text[index]
            if char in '([{':
                depth += 1
            elif char in ')]}':
                depth -= 1
                if depth == 0:
                    break
            index += 1
        inside = text[match.end():index]
        keywords = set(re.findall(r':([a-zA-Z_]\w*)\s*=>', inside))
        # A keyword only ever begins an argument, so it follows the
        # opening bracket or a comma. Without that, the `:` of a ternary
        # is read as one - `Static.new(x == "" ? y.to_s : label)` was
        # reported as passing a `to_s:` keyword.
        keywords |= set(re.findall(r'(?:^|[(,])\s*([a-zA-Z_]\w*)\s*:(?!:)',
                                   inside))
        found.append((match.group(1), keywords,
                      text[:match.start()].count('\n') + 1))
    return found


def once_only(sources):
    """The extension callbacks Elten allows exactly one of.

    `extension.tick`, `start`, `stop` and `settings` each go through
    `single_callback!`, and a second one RAISES - which does not mean two
    ticks and does not mean one, it means the whole extension declaration
    is abandoned and NOTHING ticks. Read from Elten rather than written
    down, so a fifth one added there is checked here without anybody
    remembering.
    """
    # The controls live in `ui/controls`, so the API is two levels up -
    # and the check is usually pointed at the controls, because that is
    # what everything else here reads.
    for name in ('extensions.rb', os.path.join('eapi', 'extensions.rb'),
                 os.path.join('..', 'eapi', 'extensions.rb'),
                 os.path.join('..', '..', 'eapi', 'extensions.rb'),
                 os.path.join('..', '..', '..', 'eapi', 'extensions.rb')):
        path = os.path.join(sources, name)
        if os.path.isfile(path):
            text = open(path, encoding='utf-8', errors='replace').read()
            return set(re.findall(r'single_callback!\(\s*:(\w+)', text))
    return set()


def base_events(sources):
    """What every control fires, wherever it is defined."""
    found = set()
    for name in ('form.rb', 'form_field.rb'):
        path = os.path.join(sources, name)
        if os.path.isfile(path):
            text = open(path, encoding='utf-8', errors='replace').read()
            found |= set(re.findall(r'trigger\(\s*:([a-z_]\w*)', text))
    return found


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

    # **And the CONSTRUCTORS.** Checking that a method exists says nothing
    # about the arguments it is called with, and that is where this went
    # wrong in front of the user: Elten's `EditBox.new` takes its header
    # POSITIONALLY and its flags as `type:`, while `ListBox` and
    # `TableBox` really do take `header:` - so a renderer written by
    # analogy raised `unknown keyword` on every field. `Form.new` takes no
    # `header:` at all, which meant every screen.
    built, unread = {}, []
    for klass, filename in BUILT.items():
        path = os.path.join(sources, filename)
        if not os.path.isfile(path):
            continue
        shape = constructor(path, klass)
        if shape:
            built[klass] = shape
        else:
            # Said, not skipped: a check that quietly gives up on a class
            # is a check that passes for the wrong reason.
            unread.append(klass)
    for klass in unread:
        print("could not read %s's constructor - its calls are unchecked"
              % klass)

    every_event = base_events(sources)
    for name in os.listdir(sources):
        if name.endswith('.rb'):
            every_event |= set(re.findall(
                r'trigger\(\s*:([a-z_]\w*)',
                open(os.path.join(sources, name), encoding='utf-8',
                     errors='replace').read()))

    fires = {}
    for klass, filename in BUILT.items():
        path = os.path.join(sources, filename)
        if os.path.isfile(path):
            found = events_of(path, klass)
            if found:
                fires[klass] = found | base_events(sources)

    problems = []
    # **Declared twice is declared none.** A second `extension.tick`
    # raises inside the declaration and the extension never starts: the
    # marshaller stopped being drained, every question that needs Elten's
    # own thread waited out its timeout, and the bus dropped the
    # connection. Nothing about that says "you declared two ticks".
    single = once_only(sources)
    for path in bridge_files():
        text = open(path, encoding='utf-8', errors='replace').read()
        for name in sorted(single):
            found = re.findall(r'\bextension\.%s\s*[({]' % name, text)
            if len(found) > 1:
                problems.append((
                    os.path.basename(path), '%d times' % len(found),
                    'extension', '%s can be declared once; a second one '
                    'raises and the extension never starts' % name))

    for path in bridge_files():
        text = open(path, encoding='utf-8', errors='replace').read()
        for klass, event, line in bindings(text):
            known_events = fires.get(klass)
            if known_events and event not in known_events:
                problems.append((os.path.basename(path), 'line %d' % line,
                                 klass, 'on(:%s) - it fires %s' % (
                                     event, ', '.join(sorted(known_events)))))
        # **And every other `on(:...)`, against every event that exists.**
        # A control usually arrives from a block rather than from a
        # constructor - `bound.each do |described, widget|` - so which
        # class it is cannot be read, and the precise check above sees
        # nothing at all. A name no control anywhere fires is wrong
        # whichever control it was meant for, which is the whole of this
        # bug: `:changed` is fired by nothing in Elten.
        if every_event:
            for match in re.finditer(r'\.on\(\s*:([a-z_]\w*)', text):
                event = match.group(1)
                if event in every_event:
                    continue
                problems.append((
                    os.path.basename(path),
                    'line %d' % (text[:match.start()].count('\n') + 1),
                    'a control', 'on(:%s) - nothing in Elten fires that'
                    % event))
        for klass, keywords, line in constructions(text):
            shape = built.get(klass)
            if shape is None:
                continue
            for keyword in sorted(keywords - shape['keywords']):
                problems.append((os.path.basename(path), 'line %d' % line,
                                 klass, 'new(%s:) - it takes %s' % (
                                     keyword,
                                     ', '.join(sorted(shape['keywords']))
                                     or 'no keywords')))
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
