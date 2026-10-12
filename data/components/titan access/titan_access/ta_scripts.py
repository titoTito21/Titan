# -*- coding: utf-8 -*-
"""TA scripts: the user's own reader scripts, written in Titan Script.

A Titan Access script is a ``.tas`` file in the user's own folder
(``accessibility/scripts/`` beside every other store the reader keeps). It
is **Titan Script** - the language of Titan's macros, every statement of it,
every Titan action by name - with a few lines at the top that say WHEN the
reader runs it:

    when key "insert+j"                    the reader modifier and J
    when key "ctrl+shift+f12"              any key without the modifier
    when focus program="notepad" role="edit"
    when window program="explorer" title contains "Downloads"
    when notification text contains "battery"
    when change name="Total"               a control's text changed
    when every 5m / when time "07:30"
    when reader starts

with the reader's own short statements (``beep``, ``read focus``,
``jump heading``, ``press "Save"``, ``pass``, ``setting "rate" = 60``...),
each one line of Titan Script calling a Titan Access action, and with
JAWS-like control rules. What it knows at that moment is handed in as
variables (:data:`VARIABLES`). The whole language is :func:`language_text`,
built from the tables in this module, so the README beside the scripts
and what Titan's AI is told cannot fall behind the reader.

`say` in a TA script is the READER speaking - its voice, its queue - and
every Titan Access action is there to call (`titan_access.read_focused`,
`titan_access.say`, `titan_access.click_element`...) beside the rest of
Titan's. A script runs on a thread of its own, so a dialog it opens or a
`wait` it does never holds the reader.

The language itself is the Macro Manager's (`data/components/macros`),
reached in place rather than copied: one language, one checker, one set of
error messages, and a script that is valid as a macro is valid here.
"""

import importlib.util
import os
import re
import sys
import threading

_LOCK = threading.RLock()

EXTENSION = '.tas'

#: The shortest repeat a `when every` may ask for: a script is run on a
#: thread of its own and a second is plenty of reader time to give away.
MIN_EVERY = 2

#: The reader's own triggers - the lines Titan Script itself does not know.
_TRIGGER = re.compile(r'^\s*when\s+(key|focus|window|reader|every|time|'
                      r'notification|change)\b(.*)$', re.IGNORECASE)
#: `for program "name"` - the script is about ONE program, the way a JAWS
#: script file is: its triggers and its rules apply only while that
#: program is in front.
_FOR = re.compile(r'^\s*for\s+program\s+"([^"]+)"\s*$', re.IGNORECASE)
#: `control <selectors> <change>` - what JAWS does with a window-class
#: reassignment, a label and a custom announcement: how one KIND of
#: control is read.
_CONTROL = re.compile(r'^\s*control\b(.*)$', re.IGNORECASE)
#: The changes a rule can make, after its selectors.
_CHANGE = re.compile(r'\b(as)\s+(\w+)|\b(name|describe|say|prefix|suffix|'
                     r'sound)\s+"([^"]*)"|\b(silent)\b', re.IGNORECASE)
#: One condition: `name="x"`, `name != "x"`, `title contains "x"`,
#: `name not contains "x"`, `name starts "x"`, `id matches "^btn\d+"`.
_ARG = re.compile(r'(\w+)\s*(?:(not\s+)?(contains|matches|starts)'
                  r'(?:\s+with)?\s*=?|(!=|=)?)\s*"([^"]*)"', re.IGNORECASE)


def _conditions(text):
    """``[(name, op, value)]``. ``op`` is False for "is", True for
    "contains" (the two shapes every older caller knows), or a word:
    'not', 'not contains', 'starts', 'not starts', 'matches',
    'not matches'. A pattern keeps its case; everything else is
    compared in lower case."""
    found = []
    for name, negate, word, equals, value in _ARG.findall(str(text or '')):
        word = word.lower()
        if equals == '!=':
            op = 'not'
        elif not word:
            op = False
        elif word == 'contains' and not negate:
            op = True
        else:
            op = ('not ' if negate else '') + word
        value = value.strip()
        if 'matches' not in str(op):
            value = value.lower()
        found.append((name.lower(), op, value))
    return found


def _test(op, have, wanted):
    """Whether ``have`` passes one condition."""
    have = str(have or '').lower()
    negate = isinstance(op, str) and op.startswith('not')
    word = op.replace('not', '').strip() if isinstance(op, str) else op
    if word is True or word == 'contains':
        result = wanted in have
    elif word == 'starts':
        result = have.startswith(wanted)
    elif word == 'matches':
        try:
            result = re.search(wanted, have, re.IGNORECASE) is not None
        except re.error:
            result = False
    else:
        result = have == wanted
    return not result if negate else result

_state = {'scripts': [], 'loaded_from': '', 'runs': 0, 'failed': 0,
          'last': '', 'errors': {}, 'engine': None, 'bound': []}


# --------------------------------------------------------------------------- #
# Where they live
# --------------------------------------------------------------------------- #
def folder():
    """``accessibility/scripts`` in the user's own data - made, with an
    example in it, the first time it is asked for."""
    try:
        from .portable import readerHome
        base = readerHome.folder()
    except Exception:                                # noqa: BLE001
        base = os.path.join(os.getenv('APPDATA') or os.path.expanduser('~'),
                            'titosoft', 'Titan', 'accessibility')
    where = os.path.join(base, 'scripts')
    if not os.path.isdir(where):
        try:
            os.makedirs(where, exist_ok=True)
            _write_example(where)
        except OSError:
            pass
    return where


EXAMPLE = '''# An example Titan Access script. Delete it, change it, copy it.
# Lines starting with "when" say when the reader runs the script; the rest
# is Titan Script - the language of Titan's macros.
when key "insert+shift+j"

if name is empty
    say "The control in focus has no name."
    stop
end
say "{{name}}, {{role}}, in {{program}}"
if position is not empty
    say "{{position}}"
end

# Reader statements and control rules - see README.txt beside this file:
#   beep 880 40          read focus          jump heading
#   press "Save"         pass                setting "rate" = 60
#   control class="TCustomGrid" as list
'''

#: Variables every script is handed, and what each holds.
VARIABLES = (
    ('name', 'the name of the control in focus'),
    ('role', 'its type, in your language ("przycisk")'),
    ('role_key', 'its type as the reader names it ("button")'),
    ('value', "what it holds (a field's text, a slider's value)"),
    ('description', 'its description'),
    ('states', 'its states, in your language ("zaznaczone")'),
    ('position', 'its place in its list ("3 z 9")'),
    ('index', 'that place as a number'),
    ('count', 'how many there are'),
    ('level', "a heading's or tree item's level"),
    ('class', 'its window class'),
    ('id', 'its automation id'),
    ('link', "a link's address"),
    ('x', 'the middle of it on the screen, across'),
    ('y', 'the middle of it on the screen, down'),
    ('window', 'the title of the window in front (also {{title}})'),
    ('program', 'the program in front, without .exe'),
    ('key', 'the key that started the script'),
    ('spoken', 'the last thing the reader said'),
    ('text', 'what a notification said (when notification); a control\'s '
             'new text (when change)'),
    ('old', "a control's text before it changed (when change)"),
)

#: The trigger lines, one per kind.
TRIGGERS = (
    ('when key "insert+j"', "the reader modifier and a key; the script "
                            "goes in front of the reader's own binding"),
    ('when key "ctrl+shift+f12"', "any key without the modifier - the key is "
                                  "then the script's (pass gives it back)"),
    ('when key "f5" title contains "Inbox"', "a key with conditions: the "
                                             "script runs only where they "
                                             "hold, the key stays the "
                                             "program's everywhere else"),
    ('when focus role="edit" program="notepad"', 'the focus lands on a '
                                                  'control that matches'),
    ('when window title contains "Downloads"', 'a new window comes to the '
                                               'front'),
    ('when notification text contains "battery"', 'a program says something '
                                                  'without moving the focus'),
    ('when change name="Total"', "the text of a control of the window in "
                                 "front changed ({{text}} is the new text, "
                                 "{{old}} the one before) - a JAWS frame, a "
                                 "SuperNova watch; checked once a second"),
    ('when every 5m', 'over and over: s, m or h, at least %d seconds'
                      % MIN_EVERY),
    ('when time "07:30"', 'once a day at that time'),
    ('when reader starts', 'once, when the reader starts'),
)

#: What a condition may say.
CONDITIONS = (
    ('name="Save"', 'is exactly (case does not matter)'),
    ('name != "Save"', 'is not'),
    ('title contains "Mail"', 'has it somewhere'),
    ('title not contains "Draft"', 'does not have it'),
    ('name starts with "New"', 'begins with it'),
    ('id matches "^btn\\d+$"', 'a regular expression'),
)

#: What a control rule may change.
RULE_CHANGES = (
    ('as list', 'read it as another type of control'),
    ('name "Send"', 'give it a name ({{variables}} work)'),
    ('describe "..."', 'give it a description'),
    ('prefix "..." / suffix "..."', 'add words before or after its name'),
    ('say "{{name}}, {{value}}"', 'say exactly this instead of the reading'),
    ('sound "edge"', "play one of the reader's sounds when it is focused"),
    ('silent', 'say nothing at all about it'),
)


#: The reference in Polish: every sentence of the English one, by its
#: English text, so a line added to a table and not here is still shown -
#: in English - rather than lost.
_PL = {
    "Titan Access scripts (.tas)": "Skrypty Titan Access (.tas)",
    "A .tas file in the scripts folder is a reader script. It is Titan "
    "Script - the language of Titan's macros, every statement and every "
    "Titan action by name (see the Macro Manager's Titan Script tab, or the "
    "action macros.macro_language) - plus the lines below, which only the "
    "reader understands.":
        "Plik .tas w folderze skryptów to skrypt czytnika. Jest napisany w "
        "Titan Script - języku makr Titana, z każdą jego instrukcją i każdą "
        "akcją Titana po nazwie (zobacz kartę Titan Script w Menedżerze "
        "makr albo akcję macros.macro_language) - oraz liniami opisanymi "
        "niżej, które rozumie tylko czytnik.",
    "When it runs (one or more lines, anywhere in the file):":
        "Kiedy się uruchamia (jedna lub więcej linii, w dowolnym miejscu "
        "pliku):",
    "the reader modifier and a key; the script goes in front of the "
    "reader's own binding":
        "klawisz czytnika i klawisz; skrypt ma pierwszeństwo przed własnym "
        "skrótem czytnika",
    "any key without the modifier - the key is then the script's (pass "
    "gives it back)":
        "dowolny klawisz bez klawisza czytnika - klawisz należy wtedy do "
        "skryptu (pass oddaje go programowi)",
    "the focus lands on a control that matches":
        "fokus trafia na pasującą kontrolkę",
    "a new window comes to the front": "na wierzch wychodzi nowe okno",
    "a program says something without moving the focus":
        "program coś ogłasza bez przesuwania fokusu",
    "once, when the reader starts": "raz, gdy czytnik startuje",
    "once a day at that time": "raz dziennie o tej godzinie",
    "  for program \"notepad\"   - everything in the file is about that "
    "program only, the way a JAWS script file is.":
        "  for program \"notepad\"   - cały plik dotyczy tylko tego programu, "
        "jak plik skryptów JAWS.",
    "Conditions (on when focus / window / notification, and in control "
    "rules):":
        "Warunki (w when focus / window / notification i w regułach "
        "kontrolek):",
    "is exactly (case does not matter)":
        "jest dokładnie (wielkość liter bez znaczenia)",
    "is not": "nie jest",
    "has it somewhere": "zawiera",
    "does not have it": "nie zawiera",
    "begins with it": "zaczyna się od",
    "a regular expression": "wyrażenie regularne",
    "Variables, written {{name}}:": "Zmienne, zapisywane jako {{nazwa}}:",
    "the name of the control in focus": "nazwa kontrolki z fokusem",
    'its type, in your language ("przycisk")':
        'jej typ, w Twoim języku ("przycisk")',
    'its type as the reader names it ("button")':
        'jej typ tak, jak nazywa go czytnik ("button")',
    "what it holds (a field's text, a slider's value)":
        "jej zawartość (tekst pola, wartość suwaka)",
    "its description": "jej opis",
    'its states, in your language ("zaznaczone")':
        'jej stany, w Twoim języku ("zaznaczone")',
    'its place in its list ("3 z 9")': 'jej miejsce na liście ("3 z 9")',
    "that place as a number": "to miejsce jako liczba",
    "how many there are": "ile ich jest",
    "a heading's or tree item's level": "poziom nagłówka lub gałęzi drzewa",
    "its window class": "klasa jej okna",
    "its automation id": "jej identyfikator automatyzacji",
    "a link's address": "adres łącza",
    "the middle of it on the screen, across":
        "jej środek na ekranie, w poziomie",
    "the middle of it on the screen, down": "jej środek na ekranie, w pionie",
    "the title of the window in front (also {{title}})":
        "tytuł okna na wierzchu (także {{title}})",
    "the program in front, without .exe": "program na wierzchu, bez .exe",
    "the key that started the script": "klawisz, który uruchomił skrypt",
    "the last thing the reader said": "ostatnia wypowiedź czytnika",
    "what a notification said (when notification); a control's new text "
    "(when change)":
        "treść powiadomienia (when notification); nowy tekst kontrolki "
        "(when change)",
    "a control's text before it changed (when change)":
        "tekst kontrolki przed zmianą (when change)",
    "a key with conditions: the script runs only where they hold, the key "
    "stays the program's everywhere else":
        "klawisz z warunkami: skrypt działa tylko tam, gdzie są spełnione, "
        "a wszędzie indziej klawisz należy do programu",
    "the text of a control of the window in front changed ({{text}} is the "
    "new text, {{old}} the one before) - a JAWS frame, a SuperNova watch; "
    "checked once a second":
        "zmienił się tekst kontrolki okna na wierzchu ({{text}} to nowy "
        "tekst, {{old}} poprzedni) - jak ramka w JAWS czy obserwacja w "
        "SuperNovej; sprawdzane raz na sekundę",
    "focus \"Save\" / focus button \"Save\" - put the keyboard on a control "
    "of the window in front, by what it says":
        "focus \"Zapisz\" / focus button \"Zapisz\" - przenieś fokus na "
        "kontrolkę okna na wierzchu, po jej tekście",
    "read control \"Total\" / read control statusbar - say a control "
    "without moving to it":
        "read control \"Suma\" / read control statusbar - przeczytaj "
        "kontrolkę bez przechodzenia do niej",
    "read region 10 40 300 20 - read part of the window (x y width height "
    "from its top left corner) with the reader's own OCR":
        "read region 10 40 300 20 - odczytaj fragment okna (x y szerokość "
        "wysokość od jego lewego górnego rogu) własnym OCR czytnika",
    "click 120 300 / click right 120 300 / click double 120 300 - a hot "
    "spot: pixels from the window's top left corner; the mouse is put back":
        "click 120 300 / click right 120 300 / click double 120 300 - "
        "gorący punkt: piksele od lewego górnego rogu okna; mysz wraca na "
        "swoje miejsce",
    "wait for window \"Save as\" 10s / wait for control \"OK\" 5s - wait "
    "until it is there; the script stops when it never comes":
        "wait for window \"Zapisz jako\" 10s / wait for control \"OK\" 5s "
        "- czekaj, aż się pojawi; skrypt kończy się, gdy się nie pojawi",
    "The reader's own statements (each is one Titan Access action, so a "
    "script may also call the action itself):":
        "Własne instrukcje czytnika (każda to jedna akcja Titan Access, "
        "więc skrypt może też wywołać samą akcję):",
    "`say` speaks in the reader's own voice. A script runs on a thread of "
    "its own, so a dialog or a `wait` never holds the reader.":
        "`say` mówi głosem czytnika. Skrypt działa we własnym wątku, więc "
        "okno dialogowe ani `wait` nigdy nie wstrzymują czytnika.",
    "Control rules - how one kind of control is READ, without running "
    "anything:":
        "Reguły kontrolek - jak CZYTAĆ jeden rodzaj kontrolki, bez "
        "uruchamiania czegokolwiek:",
    "What a rule may change:": "Co reguła może zmienić:",
    "read it as another type of control": "czytaj ją jako inny typ kontrolki",
    "give it a name ({{variables}} work)": "nadaj jej nazwę (działają "
                                           "{{zmienne}})",
    "give it a description": "nadaj jej opis",
    "add words before or after its name": "dodaj słowa przed nazwą lub po "
                                          "niej",
    "say exactly this instead of the reading":
        "mów dokładnie to zamiast zwykłego odczytu",
    "play one of the reader's sounds when it is focused":
        "zagraj jeden z dźwięków czytnika, gdy dostaje fokus",
    "say nothing at all about it": "nie mów o niej nic",
    "Actions: titan_access.list_scripts, write_script, read_script, "
    "delete_script, check_script, run_script, reload_scripts, "
    "script_language. Reload after editing a file by hand, or restart the "
    "reader.":
        "Akcje: titan_access.list_scripts, write_script, read_script, "
        "delete_script, check_script, run_script, reload_scripts, "
        "script_language. Po ręcznej edycji pliku przeładuj skrypty albo "
        "uruchom czytnik ponownie.",
    "beep 880 40 - a tone: frequency in Hz, length in ms":
        "beep 880 40 - ton: częstotliwość w Hz, długość w ms",
    "cue \"edge\" - one of the reader's own sounds, by name":
        "cue \"edge\" - jeden z dźwięków czytnika, po nazwie",
    "braille \"text\" - show text on the braille display":
        "braille \"tekst\" - pokaż tekst na monitorze brajlowskim",
    "press \"Save\" - press a control of the window in front by its name":
        "press \"Zapisz\" - naciśnij kontrolkę okna na wierzchu po nazwie",
    "jump heading / jump previous link - quick navigation in a document":
        "jump heading / jump previous link - szybka nawigacja w dokumencie",
    "read focus | title | value | last | screen | position | selection | "
    "status | time | date - say it in the reader's voice":
        "read focus | title | value | last | screen | position | selection "
        "| status | time | date - powiedz to głosem czytnika",
    "scan on | off | toggle - scan mode":
        "scan on | off | toggle - tryb skanowania",
    "setting \"rate\" = 60 - change a reader setting (as list_settings "
    "names it)":
        "setting \"rate\" = 60 - zmień ustawienie czytnika (nazwa jak w "
        "list_settings)",
    "label \"Send\" - give the control in focus a name of its own (\"\" "
    "takes it away)":
        "label \"Wyślij\" - nadaj kontrolce z fokusem własną nazwę (\"\" ją "
        "usuwa)",
    "pass - let the key that started the script reach the program too":
        "pass - przepuść do programu klawisz, który uruchomił skrypt",
    "silence - stop the reader speaking": "silence - ucisz czytnik",
    "command \"sayAll\" - run one of the reader's own commands, as its key "
    "would (list_shortcuts names them)":
        "command \"sayAll\" - wykonaj polecenie czytnika tak jak jego "
        "skrót (nazwy podaje list_shortcuts)",
    "script \"other\" - run another of your reader scripts":
        "script \"inny\" - uruchom inny Twój skrypt czytnika",
}


def _pl_every(text):
    import re as _re
    found = _re.match(r'over and over: s, m or h, at least (\d+) seconds$',
                      text)
    if found:
        return ('wielokrotnie: s, m albo h, co najmniej %s sekundy'
                % found.group(1))
    return None


def _in_polish(text):
    if text in _PL:
        return _PL[text]
    return _pl_every(text) or text


def _language():
    try:
        from titan_access import localization
        code = getattr(localization, 'current_language', None)
        code = code() if callable(code) else code
        if code:
            return str(code).lower()
    except Exception:                                # noqa: BLE001
        pass
    try:
        from src.settings.settings import get_setting
        return str(get_setting('language', 'pl') or 'pl').lower()
    except Exception:                                # noqa: BLE001
        return 'en'


def language_text(language=''):
    """The whole Titan Access script language - built from the tables
    above and from :data:`STATEMENTS`, so it can never describe a
    statement the reader no longer has or miss one it has gained.
    ``language`` 'en' or 'pl'; Titan's own when left out. What Titan's AI
    is given is the English one."""
    wanted = str(language or _language()).lower()
    text = _language_lines()
    if not wanted.startswith('pl'):
        return text
    out = []
    for line in text.split("\n"):
        if line in _PL:
            out.append(_PL[line])
        elif line.startswith("  ") and "  " in line.strip():
            head, _gap, tail = line.strip().partition("  ")
            width = len(line) - len(line.lstrip()) + len(head)
            rest = line[width:]
            pad = len(rest) - len(rest.lstrip())
            out.append(line[:width] + " " * pad + _in_polish(rest.strip()))
        elif line.startswith("  ") and " - " in line:
            out.append("  " + _in_polish(line.strip()))
        elif set(line) == {"="}:
            out.append("=" * len(_in_polish("Titan Access scripts (.tas)")))
        else:
            out.append(_in_polish(line))
    return "\n".join(out)


def _language_lines():
    out = ["Titan Access scripts (.tas)",
           "===========================",
           "",
           "A .tas file in the scripts folder is a reader script. It is "
           "Titan Script - the language of Titan's macros, every statement "
           "and every Titan action by name (see the Macro Manager's Titan "
           "Script tab, or the action macros.macro_language) - plus the "
           "lines below, which only the reader understands.",
           "",
           "When it runs (one or more lines, anywhere in the file):"]
    out += ["  %-46s %s" % pair for pair in TRIGGERS]
    out += ["",
            '  for program "notepad"   - everything in the file is about '
            "that program only, the way a JAWS script file is.",
            "",
            "Conditions (on when focus / window / notification, and in "
            "control rules):"]
    out += ["  %-30s %s" % pair for pair in CONDITIONS]
    out += ["", "Variables, written {{name}}:"]
    out += ["  %-12s %s" % pair for pair in VARIABLES]
    out += ["", "The reader's own statements (each is one Titan Access "
                "action, so a script may also call the action itself):"]
    out += ["  " + what for _pattern, _template, what in STATEMENTS]
    out += ["",
            "`say` speaks in the reader's own voice. A script runs on a "
            "thread of its own, so a dialog or a `wait` never holds the "
            "reader.",
            "",
            "Control rules - how one kind of control is READ, without "
            "running anything:",
            '  control class="TCustomGrid" as list',
            '  control id="btnSend" name "Send"',
            '  control role="image" name contains "spacer" silent',
            "What a rule may change:"]
    out += ["  %-30s %s" % pair for pair in RULE_CHANGES]
    out += ["",
            "Actions: titan_access.list_scripts, write_script, read_script, "
            "delete_script, check_script, run_script, reload_scripts, "
            "script_language. Reload after editing a file by hand, or "
            "restart the reader.",
            ""]
    return "\n".join(out)


#: The first line of the README this reader writes; a README that no
#: longer begins with it is the user's own and is left alone.
README_HEAD = 'Titan Access scripts (.tas)'


def _write_example(where):
    path = os.path.join(where, 'example' + EXTENSION)
    if not os.path.exists(path):
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(EXAMPLE)
    write_readme(where)


def write_readme(where=None):
    """The README beside the scripts is the language reference, written
    again whenever the reader's language has grown - unless the user has
    made it their own. The README of an older reader (its first line
    "Titan Access scripts" alone) is ours too."""
    where = where or folder()
    path = os.path.join(where, 'README.txt')
    text = language_text()
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as handle:
                have = handle.read()
            ours = have.startswith(README_HEAD) or \
                have.startswith(_PL[README_HEAD]) or \
                have.startswith('Titan Access scripts\n====')
            if have == text or not ours:
                return False
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# The language - the Macro Manager's
# --------------------------------------------------------------------------- #
def _macros():
    """The Macro Manager's module, already loaded or loaded from its file."""
    for name in ('macros', 'data.components.macros'):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, 'run_tcs_text'):
            return module
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(os.path.dirname(here), 'macros', 'init.py')
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location('macros', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['macros'] = module
    try:
        spec.loader.exec_module(module)
    except Exception:                                # noqa: BLE001
        sys.modules.pop('macros', None)
        return None
    return module


# --------------------------------------------------------------------------- #
# Reading a script
# --------------------------------------------------------------------------- #
def parse(text):
    """``(triggers, body, problems)``. The reader's trigger lines are taken
    out - replaced by blank lines, so Titan Script's line numbers stay the
    file's own - and everything else is Titan Script."""
    triggers, problems, lines = [], [], []
    rules, program = [], ''
    for number, raw in enumerate(str(text or '').splitlines(), start=1):
        scoped = _FOR.match(raw)
        if scoped:
            program = scoped.group(1).strip().lower()
            if program.endswith('.exe'):
                program = program[:-4]
            lines.append('')
            continue
        ruled = _CONTROL.match(raw)
        if ruled:
            lines.append('')
            rule, why = _rule(number, ruled.group(1))
            if rule is None:
                problems.append(why)
            else:
                rules.append(rule)
            continue
        found = _TRIGGER.match(raw)
        if not found:
            said, why = translate(raw, number)
            if why:
                problems.append(why)
            lines.append(raw if said is None else said)
            continue
        lines.append('')
        kind, rest = found.group(1).lower(), found.group(2).strip()
        trigger = {'kind': kind, 'line': number}
        if kind == 'key':
            spec = re.match(r'"([^"]+)"', rest)
            if not spec:
                problems.append('line %d: "when key" wants a key in quotes, '
                                'like when key "insert+j"' % number)
                continue
            trigger['spec'] = spec.group(1).strip().lower()
            trigger['conditions'] = _conditions(rest[spec.end():])
        elif kind == 'change':
            trigger['conditions'] = _conditions(rest)
            if not trigger['conditions']:
                problems.append('line %d: "when change" says which control, '
                                'like when change name="Total"' % number)
                continue
        elif kind == 'reader':
            if not rest.lower().startswith('start'):
                problems.append('line %d: the reader trigger is '
                                '"when reader starts"' % number)
                continue
        elif kind == 'every':
            seconds = _seconds(rest)
            if seconds is None:
                problems.append('line %d: "when every" wants a time, like '
                                'when every 30s, 5m or 1h (at least %ds)'
                                % (number, MIN_EVERY))
                continue
            trigger['seconds'] = seconds
        elif kind == 'time':
            at = re.match(r'"?(\d{1,2}):(\d{2})"?\s*$', rest)
            if not at or int(at.group(1)) > 23 or int(at.group(2)) > 59:
                problems.append('line %d: "when time" wants an hour, like '
                                'when time "07:30"' % number)
                continue
            trigger['at'] = '%02d:%02d' % (int(at.group(1)), int(at.group(2)))
        else:
            trigger['conditions'] = _conditions(rest)
        triggers.append(trigger)
    for one in triggers + rules:
        one['program'] = program
    PARSED_RULES[0] = rules
    return triggers, '\n'.join(lines), problems


# --------------------------------------------------------------------------- #
# The reader's own statements - short words for what a reader script does
# all the time, each one line of Titan Script calling a Titan Access action
# --------------------------------------------------------------------------- #
_Q = r'("(?:[^"\\]|\\.)*")'
#: ``(pattern, template, what it means)``. A template is the Titan Script
#: line the statement becomes, so the Macro Manager's checker, its error
#: messages and its line numbers apply to it unchanged.
def _kind_arg(word):
    return ' kind="%s"' % word.lower() if word else ''


STATEMENTS = (
    (r'focus\s+(?:(\w+)\s+)?' + _Q,
     lambda m: 'titan_access.focus_element text=%s%s'
               % (m.group(2), _kind_arg(m.group(1))),
     'focus "Save" / focus button "Save" - put the keyboard on a control of '
     'the window in front, by what it says'),
    (r'read\s+control\s+(?:(\w+)\s*)?' + _Q + '?',
     lambda m: 'titan_access.read_control text=%s%s'
               % (m.group(2) or '""', _kind_arg(m.group(1))),
     'read control "Total" / read control statusbar - say a control '
     'without moving to it'),
    (r'read\s+region\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)',
     lambda m: 'titan_access.read_region x=%s y=%s width=%s height=%s'
               % m.groups(),
     'read region 10 40 300 20 - read part of the window (x y width height '
     'from its top left corner) with the reader\'s own OCR'),
    (r'click\s+(?:(left|right|middle|double)\s+)?(-?\d+)\s+(-?\d+)',
     lambda m: 'titan_access.click_at x=%s y=%s button="%s" clicks=%s'
               % (m.group(2), m.group(3),
                  'left' if (m.group(1) or 'left').lower() == 'double'
                  else (m.group(1) or 'left').lower(),
                  '2' if (m.group(1) or '').lower() == 'double' else '1'),
     'click 120 300 / click right 120 300 / click double 120 300 - a hot '
     'spot: pixels from the window\'s top left corner; the mouse is put '
     'back'),
    (r'wait\s+for\s+(window|control)\s+' + _Q +
     r'(?:\s+(\d+(?:\.\d+)?)\s*s?)?',
     lambda m: 'titan_access.wait_for %s=%s seconds=%s'
               % ('window_title' if m.group(1).lower() == 'window' else 'text',
                  m.group(2), m.group(3) or '10'),
     'wait for window "Save as" 10s / wait for control "OK" 5s - wait until '
     'it is there; the script stops when it never comes'),
    (r'beep\s+(\d+)(?:\s+(\d+))?',
     lambda m: 'titan_access.beep frequency=%s duration=%s'
               % (m.group(1), m.group(2) or '60'),
     'beep 880 40 - a tone: frequency in Hz, length in ms'),
    (r'cue\s+' + _Q,
     lambda m: 'titan_access.play_cue name=' + m.group(1),
     'cue "edge" - one of the reader\'s own sounds, by name'),
    (r'braille\s+' + _Q,
     lambda m: 'titan_access.braille text=' + m.group(1),
     'braille "text" - show text on the braille display'),
    (r'press\s+' + _Q,
     lambda m: 'titan_access.click_element text=' + m.group(1),
     'press "Save" - press a control of the window in front by its name'),
    (r'jump\s+(?:(next|previous)\s+)?(\w+)',
     lambda m: 'titan_access.go_to kind="%s" backward=%s'
               % (m.group(2).lower(),
                  'true' if (m.group(1) or '').lower() == 'previous'
                  else 'false'),
     'jump heading / jump previous link - quick navigation in a document'),
    (r'read\s+(focus|title|value|last|screen|position|selection|status|'
     r'time|date)',
     lambda m: 'titan_access.read_aloud what="%s"' % m.group(1).lower(),
     'read focus | title | value | last | screen | position | selection | '
     'status | time | date - say it in the reader\'s voice'),
    (r'scan\s+(on|off|toggle)',
     lambda m: 'titan_access.scan_mode state="%s"' % m.group(1).lower(),
     'scan on | off | toggle - scan mode'),
    (r'setting\s+' + _Q + r'\s*=\s*(' + _Q[1:-1] + r'|\S+)',
     lambda m: 'titan_access.set_setting name=%s value=%s' % (
         m.group(1), m.group(2) if m.group(2).startswith('"')
         else '"%s"' % m.group(2)),
     'setting "rate" = 60 - change a reader setting (as list_settings '
     'names it)'),
    (r'label\s+' + _Q,
     lambda m: 'titan_access.label_control label=' + m.group(1),
     'label "Send" - give the control in focus a name of its own ("" '
     'takes it away)'),
    (r'pass',
     lambda m: 'titan_access.pass_key key="{{key}}"',
     'pass - let the key that started the script reach the program too'),
    (r'silence',
     lambda m: 'titan_access.stop_speech',
     'silence - stop the reader speaking'),
    (r'command\s+' + _Q,
     lambda m: 'titan_access.run_command name=' + m.group(1),
     'command "sayAll" - run one of the reader\'s own commands, as its key '
     'would (list_shortcuts names them)'),
    (r'script\s+' + _Q,
     lambda m: 'titan_access.run_script name=' + m.group(1),
     'script "other" - run another of your reader scripts'),
)
_COMPILED = [(re.compile(r'^(\s*)' + pattern + r'\s*$', re.IGNORECASE),
              template) for pattern, template, _what in STATEMENTS]


def translate(raw, number=0):
    """``(line, problem)``: a reader statement as the Titan Script line it
    stands for, or ``(None, '')`` when the line is not one."""
    for pattern, template in _COMPILED:
        found = pattern.match(raw)
        if found:
            try:
                inner = re.match(pattern.pattern[len(r'^(\s*)'):],
                                 raw.strip(), re.IGNORECASE)
                return found.group(1) + template(inner), ''
            except Exception as error:               # noqa: BLE001
                return None, 'line %d: %s' % (number, error)
    return None, ''


def _seconds(text):
    found = re.match(r'"?\s*(\d+(?:\.\d+)?)\s*(s|sec|second|seconds|m|min|'
                     r'minute|minutes|h|hour|hours)?\s*"?\s*$',
                     str(text or '').strip(), re.IGNORECASE)
    if not found:
        return None
    value = float(found.group(1))
    unit = (found.group(2) or 's').lower()[0]
    value *= {'s': 1, 'm': 60, 'h': 3600}[unit]
    return value if value >= MIN_EVERY else None


#: The rules of the script `parse` read last (a side door, so `parse`'s
#: three answers stay what every caller already unpacks).
PARSED_RULES = [[]]

#: The role keys a rule may give a control (`as list`) - the reader's own.
def _known_roles():
    try:
        from titan_access import nvda_shape
        return set(nvda_shape.ROLE_NAMES)
    except Exception:                                # noqa: BLE001
        return set()


def _rule(number, rest):
    """``(rule, why)`` for the text after `control`."""
    changes = list(_CHANGE.finditer(rest))
    if not changes:
        return None, ('line %d: a control rule says what to change - '
                      'as <role>, name "...", describe "...", say "...", '
                      'prefix "...", suffix "...", sound "..." or silent'
                      % number)
    selectors_text = rest[:changes[0].start()]
    selectors = _conditions(selectors_text)
    if not selectors:
        return None, ('line %d: a control rule says WHICH controls - '
                      'class="...", id="...", name="..." or role="..."'
                      % number)
    rule = {'line': number, 'selectors': selectors}
    for change in changes:
        if change.group(1):
            role = change.group(2).lower()
            if _known_roles() and role not in _known_roles():
                return None, ('line %d: "%s" is not a role the reader knows '
                              '(%s)' % (number, role,
                                        ', '.join(sorted(_known_roles()))))
            rule['as'] = role
        elif change.group(3):
            rule[change.group(3).lower()] = change.group(4)
        elif change.group(5):
            rule['silent'] = True
    return rule, ''


def check(text):
    """Every problem in a script: its triggers, and Titan Script's own
    check of the rest."""
    triggers, body, problems = parse(text)
    if not triggers and not PARSED_RULES[0]:
        problems.append('the script has no "when" line and no control rule, '
                        'so the reader never uses it')
    macros = _macros()
    if macros is not None:
        try:
            problems.extend(one for one in macros.check_tcs(body)
                            if not _own_action_unknown(one))
        except Exception as error:                   # noqa: BLE001
            problems.append('Titan Script could not check it: %s' % error)
    else:
        problems.append('Titan Script is not here: the Macro Manager '
                        'component is missing')
    return problems


_OWN_UNKNOWN = re.compile(r"'titan_access' has no action '(\w+)'")


def own_actions():
    """The names of this reader's own actions, read from its declaration."""
    try:
        return {str(one['name'])
                for one in _actions_module().TITAN_ACTIONS}
    except Exception:                                # noqa: BLE001
        return set()


def _own_action_unknown(problem):
    """A problem that only says Titan does not (yet) list one of this
    reader's own actions - which happens when the action registry was
    built before the reader declared them, or outside Titan."""
    found = _OWN_UNKNOWN.search(str(problem))
    return bool(found) and found.group(1) in own_actions()


def load():
    """Read every script in the folder. ``[script]``, each a dict with its
    name, path, triggers, body and problems."""
    where = folder()
    write_readme(where)
    found = []
    try:
        names = sorted(os.listdir(where))
    except OSError:
        names = []
    for name in names:
        if not name.lower().endswith(EXTENSION):
            continue
        path = os.path.join(where, name)
        try:
            with open(path, 'r', encoding='utf-8-sig') as handle:
                text = handle.read()
        except OSError as error:
            found.append({'name': name, 'path': path, 'triggers': [],
                          'body': '', 'problems': [str(error)]})
            continue
        triggers, body, problems = parse(text)
        found.append({'name': name[:-len(EXTENSION)], 'path': path,
                      'triggers': triggers, 'body': body,
                      'rules': list(PARSED_RULES[0]),
                      'problems': problems, 'dir': where})
    with _LOCK:
        _state['scripts'] = found
        _state['loaded_from'] = where
    return found


def scripts():
    with _LOCK:
        return list(_state['scripts'])


# --------------------------------------------------------------------------- #
# Running one
# --------------------------------------------------------------------------- #
def _context(engine, obj=None, key=''):
    """What a script is told about the moment it runs."""
    if obj is None and engine is not None:
        obj = getattr(engine, 'current_object', None)
    found = {'name': '', 'role': '', 'value': '', 'description': '',
             'window': '', 'program': '', 'key': str(key or ''),
             'class': '', 'id': ''}
    if obj is not None:
        found['name'] = str(getattr(obj, 'name', '') or '')
        found['value'] = str(getattr(obj, 'value', '') or '')
        found['description'] = str(getattr(obj, 'description', '') or '')
        role = getattr(obj, 'role', '')
        try:
            from titan_access import localization
            found['role'] = localization.role_label(str(role)) or str(role)
        except Exception:                            # noqa: BLE001
            found['role'] = str(role or '')
        found['role_key'] = str(role or '')
        found['class'] = str(getattr(obj, 'class_name', '') or '')
        found['id'] = str(getattr(obj, 'automation_id', '') or '')
        found.update(_more_about(obj))
    found['window'], found['program'] = _window_and_program()
    found['title'] = found['window']
    found['spoken'] = _last_spoken()
    return found


def _more_about(obj):
    """The variables beyond the name and the role: states, the place in
    its list, the level, where it is on the screen."""
    more = {'states': '', 'position': '', 'index': '', 'count': '',
            'level': '', 'x': '', 'y': '', 'link': ''}
    states = sorted(str(one) for one in (getattr(obj, 'states', None) or ()))
    if states:
        try:
            from titan_access import localization
            words = [localization.state_label(one) or one for one in states]
        except Exception:                            # noqa: BLE001
            words = states
        more['states'] = ', '.join(words)
        more['states_key'] = ' '.join(states)
    index = int(getattr(obj, 'pos_in_set', 0) or 0)
    count = int(getattr(obj, 'size_of_set', 0) or 0)
    if index:
        more['index'] = str(index)
    if count:
        more['count'] = str(count)
    if index and count:
        try:
            from titan_access.localization import L
            more['position'] = L('element.positionOf', index, count)
            if more['position'] == 'element.positionOf':
                raise KeyError
        except Exception:                            # noqa: BLE001
            more['position'] = '%d / %d' % (index, count)
    level = int(getattr(obj, 'level', 0) or 0)
    if level:
        more['level'] = str(level)
    bounds = getattr(obj, 'bounds', None)
    try:
        left, top, right, bottom = bounds
        if right > left and bottom > top:
            more['x'] = str(int((left + right) / 2))
            more['y'] = str(int((top + bottom) / 2))
    except Exception:                                # noqa: BLE001
        pass
    more['link'] = str(getattr(obj, 'parameter', '') or '')
    return more


def _last_spoken():
    try:
        from titan_access import speech_adapter
        said = speech_adapter.spoken()
        return str(said[-1]) if said else ''
    except Exception:                                # noqa: BLE001
        return ''


def _window_and_program():
    try:
        from .portable import readerApi
        window = readerApi.foreground()
        title = str(getattr(window, 'name', '') or '')
        program = str(getattr(getattr(window, 'appModule', None), 'appName',
                              '') or '')
    except Exception:                                # noqa: BLE001
        title, program = '', ''
    if not program:
        program = _foreground_process()
    return title, program


def _foreground_process():
    if not sys.platform.startswith('win'):
        return ''
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(user32.GetForegroundWindow(),
                                        ctypes.byref(pid))
        try:
            from titan_access import uwp
            pid = wintypes.DWORD(uwp.foreground_pid() or pid.value)
        except Exception:                            # noqa: BLE001
            pass
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return ''
        try:
            size = wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(1024)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer,
                                                   ctypes.byref(size)):
                name = os.path.basename(buffer.value)
                return name[:-4] if name.lower().endswith('.exe') else name
        finally:
            kernel32.CloseHandle(handle)
    except Exception:                                # noqa: BLE001
        pass
    return ''


def _reader_voice(engine):
    """`say` for a TA script: the reader's own voice."""
    def speak(text, interrupt=False, wait=False, position=None, pitch=None):
        if engine is None:
            raise RuntimeError('no reader')
        engine.speak(str(text), interrupt=bool(interrupt))
    return speak


def run(script, obj=None, key='', engine=None, wait=False, extra=None):
    """Run one script on a thread of its own. ``(started, why)``.
    ``extra`` are variables beyond what the moment says (a notification's
    ``text``)."""
    engine = engine or _state.get('engine')
    macros = _macros()
    if macros is None:
        return False, 'Titan Script is not here'
    if script.get('problems'):
        return False, '; '.join(script['problems'])
    variables = _context(engine, obj, key)
    variables.update(extra or {})

    def work():
        try:
            ok, transcript = macros.run_tcs_text(
                script.get('body', ''), announce=True,
                base_dir=script.get('dir', ''),
                title=script.get('name', ''), variables=variables,
                speak=_reader_voice(engine))
        except Exception as error:                   # noqa: BLE001
            ok, transcript = False, ['%s: %s' % (type(error).__name__, error)]
        with _LOCK:
            _state['runs'] += 1
            _state['last'] = script.get('name', '')
            if not ok:
                _state['failed'] += 1
                _state['errors'][script.get('name', '')] = \
                    '; '.join(str(one) for one in transcript[-3:])

    thread = threading.Thread(target=work, daemon=True,
                              name='TitanAccessScript')
    thread.start()
    if wait:
        thread.join(30)
    return True, ''


def by_name(name):
    wanted = str(name or '').strip().lower()
    for script in scripts():
        if script['name'].lower() == wanted:
            return script
    return None


# --------------------------------------------------------------------------- #
# Triggers - asked by the engine
# --------------------------------------------------------------------------- #
def _matches(conditions, values):
    for name, op, wanted in conditions:
        have = str(values.get(name, values.get(name + '_key', '')) or '')
        if _test(op, have, wanted):
            continue
        # A role may be named in the user's language or by its key.
        if name == 'role' and _test(op, values.get('role_key', ''), wanted):
            continue
        return False
    return True


def on_focus(obj, engine=None):
    """The focus moved: run every script whose `when focus` matches."""
    _on_event('focus', obj, engine)


def on_window(obj, engine=None):
    """The window in front changed: run every `when window` script."""
    _on_event('window', obj, engine)


def _on_event(kind, obj, engine):
    candidates = [(script, trigger) for script in scripts()
                  for trigger in script['triggers']
                  if trigger['kind'] == kind and not script['problems']]
    if not candidates:
        return
    engine = engine or _state.get('engine')
    values = _context(engine, obj)
    values['title'] = values['window']
    for script, trigger in candidates:
        if _in_program(trigger, values) and \
                _matches(trigger.get('conditions') or [], values):
            run(script, obj=obj, engine=engine)


def _in_program(one, values):
    wanted = one.get('program') or ''
    return not wanted or str(values.get('program', '')).lower() == wanted


def on_notification(text, program='', engine=None):
    """A program said something without moving the focus (a UI Automation
    notification or a live region): run every `when notification` script
    whose conditions match. ``{{text}}`` is what it said."""
    candidates = [(script, trigger) for script in scripts()
                  for trigger in script['triggers']
                  if trigger['kind'] == 'notification'
                  and not script['problems']]
    if not candidates:
        return 0
    engine = engine or _state.get('engine')
    values = {'text': str(text or ''), 'program': str(program or '')}
    if not values['program']:
        values['program'] = _foreground_process()
    started = 0
    for script, trigger in candidates:
        if _in_program(trigger, values) and \
                _matches(trigger.get('conditions') or [], values):
            run(script, engine=engine, extra={'text': values['text']})
            started += 1
    return started


# --------------------------------------------------------------------------- #
# `when every` and `when time` - one slow thread, only while a script asks
# --------------------------------------------------------------------------- #
_clock = {'thread': None, 'generation': 0, 'due': {}, 'fired': {},
          'seen': {}}


def _actions_module():
    """``titan_access_actions`` - the reader's own actions, beside this
    package."""
    module = sys.modules.get('titan_access_actions')
    if module is None:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            'titan_access_actions',
            os.path.join(here, 'titan_access_actions.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules['titan_access_actions'] = module
    return module


def _control_text(conditions):
    """The text of the first control in front that meets ``conditions``,
    or None. `when change` asks it once a second."""
    try:
        return _actions_module().control_text(conditions)
    except Exception:                                # noqa: BLE001
        return None


def _timed():
    return [(script, trigger) for script in scripts()
            for trigger in script['triggers']
            if trigger['kind'] in ('every', 'time', 'change')
            and not script['problems']]


def _start_clock():
    with _LOCK:
        _clock['generation'] += 1
        generation = _clock['generation']
        _clock['due'] = {}
        _clock['seen'] = {}
        if not _timed():
            _clock['thread'] = None
            return False
        thread = threading.Thread(target=_tick_loop, args=(generation,),
                                  daemon=True, name='TitanAccessScriptClock')
        _clock['thread'] = thread
    thread.start()
    return True


def _tick_loop(generation):
    import time as _time
    while True:
        with _LOCK:
            if _clock['generation'] != generation:
                return
        tick(_time.time())
        _time.sleep(1.0)


def tick(now):
    """Run whatever is due at ``now`` (seconds since the epoch). Called by
    the clock thread once a second; a test calls it with a time of its own."""
    import time as _time
    started = 0
    for script, trigger in _timed():
        if not _in_program(trigger, {'program': _foreground_process()
                                     if trigger.get('program') else ''}):
            continue
        key = (script['name'], trigger['line'])
        if trigger['kind'] == 'change':
            text = _control_text(trigger.get('conditions') or [])
            with _LOCK:
                seen = _clock['seen']
                old = seen.get(key)
                seen[key] = text
            # The first reading is where the watch starts, and a control
            # that is not on the screen is not a change.
            if old is None or text is None or text == old:
                continue
            run(script, engine=_state.get('engine'),
                extra={'text': text, 'old': old})
            started += 1
            continue
        if trigger['kind'] == 'every':
            with _LOCK:
                due = _clock['due'].setdefault(key, now + trigger['seconds'])
                if now < due:
                    continue
                _clock['due'][key] = now + trigger['seconds']
        else:
            stamp = _time.strftime('%H:%M', _time.localtime(now))
            day = _time.strftime('%Y-%m-%d', _time.localtime(now))
            with _LOCK:
                if stamp != trigger['at'] or _clock['fired'].get(key) == day:
                    continue
                _clock['fired'][key] = day
        run(script, engine=_state.get('engine'))
        started += 1
    return started


def stop_clock():
    with _LOCK:
        _clock['generation'] += 1
        _clock['thread'] = None


def plain_key(name, ctrl, alt, shift, engine=None):
    """A key WITHOUT the reader modifier. True when a script took it."""
    pressed = _spec(name, ctrl, alt, shift, False)
    program = None
    for script in scripts():
        for trigger in script['triggers']:
            if trigger['kind'] == 'key' and not script['problems'] \
                    and _normalise(trigger['spec']) == pressed:
                if trigger.get('program'):
                    if program is None:
                        program = _foreground_process().lower()
                    if program != trigger['program']:
                        continue
                if not _key_conditions_hold(trigger):
                    continue
                run(script, key=trigger['spec'], engine=engine)
                return True
    return False


def _key_conditions_hold(trigger):
    """`when key "f5" title contains "Inbox"`: the window in front is
    asked only when the trigger has conditions."""
    conditions = trigger.get('conditions') or []
    if not conditions:
        return True
    title, program = _window_and_program()
    return _matches(conditions, {'title': title, 'window': title,
                                 'program': program})


def _normalise(spec):
    parts = [part.strip().lower() for part in str(spec or '').split('+')
             if part.strip()]
    aliases = {'control': 'ctrl', 'nvda': 'insert', 'ta': 'insert',
               'enter': 'return'}
    parts = [aliases.get(part, part) for part in parts]
    order = ('insert', 'ctrl', 'alt', 'shift')
    mods = [one for one in order if one in parts]
    base = [part for part in parts if part not in order]
    return '+'.join(mods + base)


def _spec(name, ctrl, alt, shift, insert):
    parts = []
    if insert:
        parts.append('insert')
    if ctrl:
        parts.append('ctrl')
    if alt:
        parts.append('alt')
    if shift:
        parts.append('shift')
    parts.append(str(name or '').lower())
    return _normalise('+'.join(parts))


def bind(engine):
    """Load the scripts and give the ones with the reader modifier their
    keys, in FRONT of the reader's own - a user's script is a deliberate
    choice to change what a key does. Fires `when reader starts`."""
    with _LOCK:
        _state['engine'] = engine
    gestures = getattr(engine, 'gestures', None)
    with _LOCK:
        for action_id in _state['bound']:
            try:
                gestures.unregister(action_id)
            except Exception:                        # noqa: BLE001
                pass
        _state['bound'] = []
    found = load()
    for script in found:
        if script['problems']:
            continue
        for trigger in script['triggers']:
            if trigger['kind'] != 'key':
                continue
            spec = _normalise(trigger['spec'])
            if not spec.startswith('insert+') or gestures is None:
                continue
            action_id = 'script:%s:%s' % (script['name'], spec)
            try:
                binding = gestures.register(
                    action_id, spec,
                    lambda one=script, key=spec, scope=trigger.get('program'),
                    when=trigger: _run_scoped(one, key, scope, when))
                gestures._bindings.remove(binding)
                gestures._bindings.insert(0, binding)
                binding.name = script['name']
                binding.description = 'Titan Access script'
                with _LOCK:
                    _state['bound'].append(action_id)
            except Exception:                        # noqa: BLE001
                continue
    for script in found:
        if any(trigger['kind'] == 'reader' for trigger in script['triggers']) \
                and not script['problems']:
            run(script, engine=engine)
    _start_clock()
    return found


def _run_scoped(script, key, program, trigger=None):
    """A modifier key of a program's script: that script's in that program
    (and where its conditions hold), the reader's own everywhere else."""
    if program and _foreground_process().lower() != program:
        return _fall_through(key)
    if trigger is not None and not _key_conditions_hold(trigger):
        return _fall_through(key)
    return run(script, key=key)


def _fall_through(key):
    """The reader's own binding for a key a scoped script did not take."""
    engine = _state.get('engine')
    gestures = getattr(engine, 'gestures', None)
    if gestures is None:
        return False
    for binding in gestures._bindings:
        if binding.action_id.startswith('script:'):
            continue
        spec = _normalise(binding.key_spec if binding.insert or
                          'insert' in binding.key_spec.lower()
                          else 'insert+' + binding.key_spec)
        if spec == key:
            binding.handler()
            return True
    return False


# --------------------------------------------------------------------------- #
# Control rules - how one KIND of control is read (JAWS's reclassing,
# labels and custom announcements)
# --------------------------------------------------------------------------- #
def _rule_matches(rule, values):
    if not _in_program(rule, values):
        return False
    for name, op, wanted in rule['selectors']:
        if name == 'role':
            have = values.get('role_key', '')
        else:
            have = values.get(name, '')
        if not _test(op, have, wanted):
            return False
    return True


def adjust(obj):
    """``(obj, say)`` - the control as the user's rules say it is read.

    ``obj`` is a COPY with the role, name or description the rules gave it
    (the reader's own object is never changed); ``say`` is the user's own
    announcement for it - '' for none, None when a rule made it silent."""
    rules = [rule for script in scripts() for rule in script.get('rules', ())
             if not script['problems']]
    if not rules or obj is None:
        return obj, ''
    values = None
    say = ''
    changed = None
    for rule in rules:
        if values is None:
            values = _context(None, obj)
        if not _rule_matches(rule, values):
            continue
        if changed is None:
            try:
                import copy
                changed = copy.copy(obj)
            except Exception:                        # noqa: BLE001
                return obj, ''
        if rule.get('as'):
            changed.role = rule['as']
        if 'name' in rule:
            changed.name = _fill(rule['name'], values)
        if 'prefix' in rule or 'suffix' in rule:
            changed.name = (_fill(rule.get('prefix', ''), values)
                            + str(getattr(changed, 'name', '') or '')
                            + _fill(rule.get('suffix', ''), values))
        if rule.get('sound'):
            _cue(rule['sound'], obj)
        if 'describe' in rule:
            changed.description = _fill(rule['describe'], values)
        if rule.get('silent'):
            say = None
        elif 'say' in rule:
            say = _fill(rule['say'], values)
        with _LOCK:
            _state['adjusted'] = _state.get('adjusted', 0) + 1
    return (changed if changed is not None else obj), say


def _cue(name, obj=None):
    """One of the reader's own sounds, where the control is."""
    engine = _state.get('engine')
    try:
        if engine is not None and hasattr(engine, 'play'):
            engine.play(str(name), obj)
            with _LOCK:
                _state['cues'] = _state.get('cues', 0) + 1
    except Exception:                                # noqa: BLE001
        pass


def _fill(template, values):
    return re.sub(r'\{\{\s*(\w+)\s*\}\}',
                  lambda found: str(values.get(found.group(1), '')),
                  str(template or ''))


def report():
    with _LOCK:
        found = {key: value for key, value in _state.items()
                 if key not in ('engine', 'scripts')}
        found['clock'] = _clock['thread'] is not None
        found['scripts'] = [{'name': one['name'],
                             'triggers': [t['kind'] for t in one['triggers']],
                             'rules': len(one.get('rules', [])),
                             'problems': one['problems']}
                            for one in _state['scripts']]
    return found
