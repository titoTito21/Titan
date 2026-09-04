# -*- coding: utf-8 -*-
"""What an engine is, and why the engines are the emulator.

A Klango application's own logic is Lua inside an encrypted package, and Cling
neither has that Lua nor wants to run somebody else's: what it has is the
application's DATA, and for a whole class of applications the data is the game.
`std_level_07.lev` says how many fields the board has, how long a mole stays up,
how many may be up at once, how many must be hit; `5x4.top` says where every
one of those fields is in the sound field; the theme says what a mole sounds
like arriving, leaving and being hit.  There is nothing left to guess - so
Cling supplies the loop, and Mole No More runs.

An engine is therefore a *genre*, not an application, and it is deliberately a
plain state machine: it is given time rather than reading the clock, and keys
by name rather than as wx events.  That is what lets a whole game be played
through in a test in a millisecond, with no window, no mixer and no voice - and
a game nobody can test is a game whose thirteenth level is never played.
"""


class Engine(object):
    """The contract every Cling engine answers."""

    #: What the browser calls this kind of application.
    LABEL = 'application'

    def __init__(self, host):
        self.host = host
        self.running = False
        self.finished_reason = ''

    # ------------------------------------------------------------ lifetime
    def start(self):
        """Begin. Anything spoken here is the first thing the user hears."""
        self.running = True

    def stop(self):
        """Give everything back. Called however the application is left."""
        self.running = False
        try:
            self.host.close()
        except Exception:
            pass

    # -------------------------------------------------------------- the run
    def tick(self, now=None):
        """Advance to `now` (seconds, monotonic). Called often; must be cheap."""

    def key(self, name, modifiers=()):
        """A key by name: 'up', 'space', 'escape', 'a'. True when consumed."""
        return False

    def key_down(self, name, modifiers=()):
        """A key that is being HELD, until `key_up` says otherwise.

        Most engines do not care - Cling's own are turn-taking, and a press is
        the whole of what they need - so the default is one press. An emulated
        Klango application does care: its platform polls the keyboard every
        frame, and holding an arrow to walk, or Alt to open a menu, is only
        possible when the two halves are told apart.
        """
        return self.key(name, modifiers)

    def key_up(self, name, modifiers=()):
        return False

    # ------------------------------------------------------------- reading
    def status(self):
        """One line for the surface's status bar and for `read_status`."""
        return ''

    def rows(self):
        """The rows a list-shaped engine shows, or ()."""
        return ()

    def help_text(self):
        """What the keys do - the application's own `help.txt` where it has one."""
        return self.host.text('help')
