# -*- coding: utf-8 -*-
"""
Titan's settings on a console - the same settings, no window at all.

Titan is a wxPython program, so there is no console to write to until one is
asked for: `AllocConsole` gives this process a real one, standard input and
output are reattached to it, and the interface is then an ordinary text loop
- a numbered list of categories, a numbered list of settings, and one
question at a time.

Two things make it worth having beyond the demonstration.  It is the fastest
way to change a setting when you know its name; and it is the interface that
still works when the graphical one cannot be used at all - a machine whose
display driver has just been changed, a Titan started with the wrong skin, a
remote session over a text terminal.

**The loop runs on a thread of its own** and every touch of the settings
goes through `api.call(...)`, which runs it on the GUI thread and waits.
The settings are wx controls; reading or writing them from this thread would
be undefined behaviour rather than an error anybody would see.
"""

import ctypes
import sys
import threading

try:
    from src.titan_core.translation import _
except Exception:                                     # pragma: no cover
    def _(text):
        return text


def _open_console():
    """Give this process a console, or use the one it already has."""
    if sys.platform != 'win32':
        return sys.stdin is not None and sys.stdin.isatty()
    kernel32 = ctypes.windll.kernel32
    if not kernel32.GetConsoleWindow():
        if not kernel32.AllocConsole():
            return False
    try:
        sys.stdin = open('CONIN$', 'r', encoding='utf-8', errors='replace')
        sys.stdout = open('CONOUT$', 'w', encoding='utf-8', errors='replace',
                          buffering=1)
        sys.stderr = sys.stdout
    except OSError:
        return False
    try:
        kernel32.SetConsoleTitleW(_("Titan settings"))
    except Exception:
        pass
    return True


def _close_console():
    if sys.platform == 'win32':
        try:
            ctypes.windll.kernel32.FreeConsole()
        except Exception:
            pass


class ConsoleSettings:
    """A numbered list, one question at a time."""

    def __init__(self, api):
        self.api = api

    # -- talking ---------------------------------------------------------
    @staticmethod
    def say(text=''):
        print(text)

    @staticmethod
    def ask(prompt):
        try:
            return input(prompt)
        except (EOFError, KeyboardInterrupt):
            return None

    # -- running ---------------------------------------------------------
    def run(self):
        self.say(_("Titan settings"))
        self.say('=' * 40)
        while True:
            categories = self.api.call(self.api.categories)
            self.say()
            for number, category in enumerate(categories, 1):
                self.say(f"{number:2}. {category['name']} "
                         f"({len(category['items'])})")
            self.say()
            self.say(_("Type a number, a word to search for, "
                       "'s' to save or 'q' to leave."))
            answer = self.ask('> ')
            if answer is None or answer.strip().lower() in ('q', 'quit'):
                self.api.call(self.api.cancel)
                return
            answer = answer.strip()
            if not answer:
                continue
            if answer.lower() in ('s', 'save'):
                if self.api.call(self.api.save):
                    self.say(_("Settings have been saved."))
                return
            if answer.isdigit():
                index = int(answer) - 1
                if 0 <= index < len(categories):
                    self._category(categories[index]['name'])
                continue
            self._found(self.api.call(self.api.find, answer))

    def _category(self, name):
        while True:
            categories = self.api.call(self.api.categories)
            category = next((c for c in categories if c['name'] == name), None)
            if category is None:
                return
            self.say()
            self.say(name)
            self.say('-' * len(name))
            for number, item in enumerate(category['items'], 1):
                self.say(f"{number:2}. {self._line(item)}")
            self.say()
            self.say(_("Type a number to change one, or Enter to go back."))
            answer = self.ask('> ')
            if answer is None or not answer.strip():
                return
            if not answer.strip().isdigit():
                continue
            index = int(answer.strip()) - 1
            if 0 <= index < len(category['items']):
                self._change(category['items'][index])

    def _found(self, items):
        if not items:
            self.say(_("Nothing matches."))
            return
        for number, item in enumerate(items, 1):
            self.say(f"{number:2}. [{item['category']}] {self._line(item)}")
        self.say()
        self.say(_("Type a number to change one, or Enter to go back."))
        answer = self.ask('> ')
        if answer is None or not answer.strip().isdigit():
            return
        index = int(answer.strip()) - 1
        if 0 <= index < len(items):
            self._change(items[index])

    @staticmethod
    def _line(item):
        """One setting on one line - what it is, and what it is now."""
        value = item['value']
        if item['kind'] == 'bool':
            value = _("on") if value else _("off")
        elif item['kind'] == 'secret':
            value = _("(set)") if value else _("(not set)")
        elif item['kind'] == 'multi':
            value = ', '.join(value or [])
        elif item['kind'] == 'command':
            value = _("(press)")
        elif item['kind'] == 'info':
            value = (str(value or '').splitlines() or [''])[0]
        return f"{item['label']}: {value}"

    def _change(self, item):
        """Ask for one setting, in the way its kind wants to be asked."""
        kind = item['kind']
        identifier = item['id']
        self.say()
        self.say(item['label'])

        if kind == 'info':
            self.say(str(item['value'] or ''))
            return
        if kind == 'command':
            answer = self.ask(_("Press it? (y/n) ") + ' ')
            if answer and answer.strip().lower().startswith(('y', 't')):
                self.api.call(self.api.press, identifier)
            return
        if kind == 'bool':
            answer = self.ask(_("on or off: "))
            if answer:
                self.api.call(self.api.set, identifier, answer.strip())
            return
        if kind in ('choice', 'list'):
            for number, option in enumerate(item['options'], 1):
                mark = '*' if option == item['value'] else ' '
                self.say(f" {mark}{number:2}. {option}")
            answer = self.ask(_("Number or name: "))
            if answer and answer.strip():
                # The model takes either, and a number is one-based here
                # because that is how the list was just printed.
                self.api.call(self.api.set, identifier, answer.strip())
            return
        if kind == 'multi':
            chosen = set(item['value'] or [])
            for number, option in enumerate(item['options'], 1):
                mark = '*' if option in chosen else ' '
                self.say(f" {mark}{number:2}. {option}")
            answer = self.ask(_("Numbers to tick, separated by commas: "))
            if answer is None:
                return
            wanted = []
            for part in answer.replace(' ', '').split(','):
                if part.isdigit() and 1 <= int(part) <= len(item['options']):
                    wanted.append(item['options'][int(part) - 1])
            self.api.call(self.api.set, identifier, wanted)
            return
        if kind == 'number':
            answer = self.ask(
                _("A number between {low} and {high}: ").format(
                    low=item.get('minimum'), high=item.get('maximum')))
            if answer and answer.strip():
                self.api.call(self.api.set, identifier, answer.strip())
            return
        # text and secret
        answer = self.ask(_("New value (Enter to leave it): "))
        if answer:
            self.api.call(self.api.set, identifier, answer)


def open_settings(api):
    """What makes this folder a settings interface.

    Answers `True` rather than a window: there is no window.  The console
    loop runs on its own thread, so Titan carries on while the settings are
    being changed - which is also what makes it possible to have the
    graphical Titan and this open at once.
    """
    if not _open_console():
        api.log("could not open a console")
        return None

    def work():
        try:
            ConsoleSettings(api).run()
        except Exception as error:
            api.log(f"console settings failed: {error}")
            import traceback
            traceback.print_exc()
        finally:
            _close_console()

    thread = threading.Thread(target=work, daemon=True,
                              name='TitanConsoleSettings')
    thread.start()
    return True
