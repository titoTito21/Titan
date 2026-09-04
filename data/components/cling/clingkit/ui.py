# -*- coding: utf-8 -*-
"""Cling on the screen: the browser, and the window an application runs in.

Two windows, and both are Titan's own shapes rather than shapes invented here.

The **browser** is `TabbedListFrame` - the class Titan IM, the Feedback Hub and
the Titan-Net services already are - so row 0 is the tab bar, Left and Right
cycle the categories, Enter opens, Escape leaves, and the stereo focus cues are
the ones the user already knows.  A subsystem that felt like a different
program would be a second interface to learn.

The **surface** is where an application runs, and it is deliberately plain: a
read-only text control that carries everything the application has said, a
status line, and the keyboard.  A Klango application is heard rather than seen,
so what the window is really for is (a) owning the keyboard, (b) giving a
screen reader a real control with real text in it, so the transcript can be
read back, reviewed and copied, and (c) driving the engine's clock.  There is
no drawn board, because there was never a board to draw.
"""

import time

import wx

from . import catalog, runner

try:
    from src.network.im_ui_common import TabbedListFrame, apply_skin_tree, pan_for
except Exception:                                        # Titan not importable
    TabbedListFrame = wx.Frame
    pan_for = None

    def apply_skin_tree(_window):
        pass

try:
    from src.titan_core.sound import play_sound
except Exception:
    def play_sound(*_args, **_kwargs):
        return False

try:
    from src.titan_core.stereo_speech import speak_stereo
except Exception:
    def speak_stereo(text, position=0.0, pitch_offset=0, async_mode=True,
                     elevation=0.0):
        return False


#: wx key codes that have a name an engine understands. Everything else that
#: produces a character is passed as that character, so a typing course sees
#: what was typed and a game sees 'space'.
_NAMED_KEYS = {
    wx.WXK_UP: 'up', wx.WXK_DOWN: 'down', wx.WXK_LEFT: 'left',
    wx.WXK_RIGHT: 'right', wx.WXK_SPACE: 'space', wx.WXK_RETURN: 'enter',
    wx.WXK_NUMPAD_ENTER: 'enter', wx.WXK_ESCAPE: 'escape', wx.WXK_TAB: 'tab',
    wx.WXK_BACK: 'backspace', wx.WXK_DELETE: 'delete', wx.WXK_HOME: 'home',
    wx.WXK_END: 'end', wx.WXK_PAGEUP: 'pageup', wx.WXK_PAGEDOWN: 'pagedown',
    wx.WXK_INSERT: 'insert',
    # The modifiers are keys in their own right here. **Alt is how a Klango
    # application's menu is opened** - the platform watches for the Alt key
    # coming back UP with nothing pressed in between - so a surface that
    # swallowed it, as this one did, left an emulated application with no
    # menu at all and no way to reach one.
    wx.WXK_ALT: 'alt', wx.WXK_CONTROL: 'ctrl', wx.WXK_SHIFT: 'shift',
    wx.WXK_RAW_CONTROL: 'ctrl',
}
for _number in range(1, 13):
    _NAMED_KEYS[getattr(wx, 'WXK_F%d' % _number)] = 'f%d' % _number

#: Keys the surface keeps for itself, whatever the application wants.
SURFACE_KEYS = ('f2', 'f3')

#: The keys that are held rather than pressed - see `ClingSurface._on_key`.
_MODIFIER_KEYS = ('shift', 'ctrl', 'alt')


def key_name(event):
    """The name an engine is given for a key press, or '' when there is none."""
    code = event.GetKeyCode()
    if code in _NAMED_KEYS:
        return _NAMED_KEYS[code]
    unicode_key = event.GetUnicodeKey()
    if unicode_key and unicode_key >= 32:
        return chr(unicode_key).lower()
    return ''


def modifier_names(event):
    out = []
    if event.ControlDown():
        out.append('ctrl')
    if event.AltDown():
        out.append('alt')
    if event.ShiftDown():
        out.append('shift')
    return tuple(out)


class ClingSurface(wx.Frame):
    """The window one Cling application runs in.

    It is deliberately empty. A Klango application is HEARD - there was never
    a board to draw and there is nothing to read back - so the window is its
    title and its keyboard, and nothing else. It used to carry a multi-line
    text box holding everything the application had said, which is a control
    a screen reader offers to review, arrow through and search: a second
    interface, in the way of the one the application actually has, on top of
    a program that is already talking.

    The title is what names it: `<application> - Cling`.
    """

    def __init__(self, parent, app, language='', translate=None):
        self._ = translate or (lambda text: text)
        wx.Frame.__init__(self, parent,
                          title='%s - %s' % (app.name(language),
                                             self._('Cling')),
                          size=(520, 200))
        self.app = app
        self.session = None
        self._closing = False
        #: Which modifiers the application has been told are held.
        self._modifiers = set()
        #: The ordinary keys the application has been told are held, and when
        #: each was last seen down - see `_on_key`.
        self._held = {}

        # Something has to hold the keyboard focus, or the frame is not where
        # the keys arrive. A panel is not a control: it says nothing, offers
        # nothing to review, and is exactly the window's own keyboard.
        self.keys = wx.Panel(self)
        self.keys.SetName('%s - %s' % (app.name(language), self._('Cling')))

        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_KEY_UP, self._on_key_up)
        self.keys.Bind(wx.EVT_KEY_UP, self._on_key_up)
        self.Bind(wx.EVT_ACTIVATE, self._on_activate)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_tick, self.timer)
        apply_skin_tree(self)

    # ------------------------------------------------------------ lifetime
    def run(self):
        self.session = runner.Session(self.app, language=self._language(),
                                      surface=self, clock=runner.now)
        self.Show()
        self.keys.SetFocus()
        self.session.start()
        self.timer.Start(runner.Session.TICK_MS)
        return self

    def _language(self):
        try:
            from src.titan_core.translation import language_code
            return language_code
        except Exception:
            return ''

    def _on_tick(self, _event):
        if self._closing or self.session is None:
            return
        self.session.tick()
        self._drop_stale_keys()
        if not self.session.running and self.session.started is False:
            # The application ended by itself. Nothing is left to drive.
            self.timer.Stop()

    # ------------------------------------------------------------- display
    def show_message(self, text):
        """Called by the host: something the application said.

        There is nowhere to put it - the window is its title and its keyboard
        - and nowhere is right: the host has already SAID it, and writing a
        second copy into a control was what made this window something to
        read rather than something to play.
        """

    # ---------------------------------------------------------------- keys
    #: How long a key may go unrefreshed before this window decides its
    #: release was lost. Windows' own auto-repeat delay goes up to a second,
    #: so anything shorter would let go of a key the user is still holding.
    KEY_STALE = 1.5

    def _on_key(self, event):
        """A key going down, and HELD until it comes back up.

        Klango's `k_KeyJustPressed` is "held for exactly one frame" and its
        `k_KeyJustReleased` is "the raw buffer said up this frame", and the
        two only mean what they say if a key that is being held is held here
        too. Klango Piano is the application that proves it: a key whose
        sample is a loop starts it on the way down and stops it on the way
        up, so a key that was released a frame after it was pressed could
        never sustain a note. DirectInput's buffer carries no auto-repeat
        either, which is why a repeat here only says the key is still down
        rather than pressing it again - holding an arrow in a Klango menu
        moves one item, as it does in Klango.

        This did wait for `EVT_KEY_UP` once, was changed because a release
        can be lost - the key comes up wherever the keyboard is by then,
        which after Alt+Tab, a dialog or a focus change is somewhere else -
        and one that never arrived left the key held for ever. So there are
        three ways a key is let go now, not one: its own `EVT_KEY_UP`, this
        window losing the keyboard (`_let_go`), and `KEY_STALE` seconds
        without the auto-repeat saying it is still down.

        The MODIFIERS are the exception and are still a press, because Klango
        watches for Alt coming back UP with nothing pressed in between - that
        is how a menu opens.
        """
        name = key_name(event)
        if not name:
            event.Skip()
            return
        if name == 'f2':
            self._say_status()
            return
        if name == 'f3':
            self._say_help()
            return
        if self.session is None:
            event.Skip()
            return
        if name in _MODIFIER_KEYS:
            # Alt on its own is a key in its own right - it is how a Klango
            # application's menu is opened, and the platform watches for it
            # coming back UP with nothing pressed in between. So it is a
            # press, and it is left out of the held set: the press releases
            # it a frame later, and the next key that arrives with Alt still
            # physically down puts the hold back.
            self._modifiers_from(event, without=name)
            self.session.key(name)
            return
        self._modifiers_from(event)
        if name in self._held:
            # Auto-repeat: the key is still down, and that is all it says.
            self._held[name] = time.time()
            return
        self._held[name] = time.time()
        if self.session.key_down(name, modifier_names(event)):
            if not self.session.running and not self.session.started:
                self.Close()
            return
        if name == 'escape':
            self.Close()
            return
        event.Skip()

    def _on_key_up(self, event):
        """A key really coming up - the ordinary way one is let go."""
        name = key_name(event)
        if name and name in self._held:
            del self._held[name]
            if self.session is not None:
                self.session.key_up(name)
        event.Skip()

    def _drop_stale_keys(self):
        """Let go of a key whose release never arrived."""
        if not self._held or self.session is None:
            return
        cutoff = time.time() - self.KEY_STALE
        for name in [n for n, when in self._held.items() if when < cutoff]:
            del self._held[name]
            self.session.key_up(name)

    def _modifiers_from(self, event, without=None):
        """Hold exactly the modifiers Windows says are down.

        Asked of the EVENT rather than remembered, so a modifier let go while
        this window did not have the keyboard is let go here too.
        """
        wanted = set()
        if event.ShiftDown():
            wanted.add('shift')
        if event.ControlDown():
            wanted.add('ctrl')
        if event.AltDown():
            wanted.add('alt')
        wanted.discard(without)
        for name in wanted - self._modifiers:
            self.session.key_down(name)
        for name in self._modifiers - wanted:
            self.session.key_up(name)
        self._modifiers = wanted

    def _on_activate(self, event):
        if not event.GetActive():
            self._let_go()
        event.Skip()

    def _let_go(self):
        """The window has lost the keyboard, so nothing is held any more."""
        if self._closing or self.session is None:
            return
        for name in list(self._held):
            self.session.key_up(name)
        self._held = {}
        for name in list(self._modifiers):
            self.session.key_up(name)
        self._modifiers = set()

    def _say_status(self):
        text = self.session.status() if self.session else ''
        speak_stereo(text or self._('Nothing to report.'))

    def _say_help(self):
        text = self.session.help_text() if self.session else ''
        speak_stereo(text or self._('This application ships no help.'))

    def _on_close(self, event):
        self._closing = True
        try:
            self.timer.Stop()
        except Exception:
            pass
        if self.session is not None:
            self.session.stop()
            self.session = None
        try:
            play_sound('ui/popupclose.ogg')
        except Exception:
            pass
        event.Skip()


class ClingBrowser(TabbedListFrame):
    """The list of installed Cling applications, in Titan's own shape."""

    VIEW_ID = 'cling'
    CLOSE_SOUND = 'ui/popupclose.ogg'

    def __init__(self, parent, translate=None, language=''):
        self._ = translate or (lambda text: text)
        self.language = language
        self.apps = []
        self.problems = []
        TabbedListFrame.__init__(self, parent, self._('Cling'), size=(880, 620))
        self.refresh()

    # ---------------------------------------------------------------- tabs
    def build_tabs(self):
        labels = {'games': self._('Games'), 'edu': self._('Learning'),
                  'soundscape': self._('Soundscapes'),
                  'network': self._('Online'), 'tools': self._('Tools'),
                  'other': self._('Other')}
        tabs = [('all', self._('All'))]
        present = {app.category for app in self._all_apps()}
        for name in catalog.CATEGORIES:
            if name in present:
                tabs.append((name, labels.get(name, name)))
        return tabs

    def _all_apps(self):
        if not self.apps:
            self.apps = catalog.discover(language=self.language)
        return self.apps

    # ---------------------------------------------------------------- rows
    def load_items(self, tab_id, background=False):
        self.apps = catalog.discover(language=self.language)
        rows = [app for app in self._all_apps()
                if app.enabled and not app.hidden
                and (tab_id == 'all' or app.category == tab_id)]
        self.rebuild_tabs()
        self.apply_items(rows, tab_id, background=background)

    def row_key(self, item):
        return 'app:%s' % getattr(item, 'id', '')

    def format_row(self, item):
        if getattr(item, 'locked', False):
            return self._('%s - installed as a Klango package Cling cannot '
                          'open yet') % item.name(self.language)
        summary = item.summary(self.language)
        engine = _engine_label(self._, item.engine)
        if summary:
            return '%s - %s (%s)' % (item.name(self.language), summary, engine)
        return '%s (%s)' % (item.name(self.language), engine)

    def status_text(self):
        if not self.items:
            return self._('No Cling applications are installed.')
        return self._('{tab}: {n} applications').format(
            tab=self.tab_label(self.current_tab), n=len(self.items))

    # ------------------------------------------------------------- actions
    def activate(self, item):
        if item is None:
            return
        if getattr(item, 'locked', False):
            _show_text_window(self, item.name(self.language),
                              item.locked_reason())
            return
        run_app(item, parent=self, translate=self._, language=self.language)

    def context_menu_items(self, item):
        if item is None:
            return ()
        return (
            (self._('Run'), lambda: self.activate(item)),
            (self._('What it says'), lambda: self._show_texts(item)),
            (self._('High scores'), lambda: self._show_scores(item)),
            (self._('Details'), lambda: self._show_details(item)),
            (self._('Open its folder'), lambda: self._open_folder(item)),
        )

    def extra_key(self, keycode, modifiers, item):
        if keycode == wx.WXK_F5:
            self.refresh()
            return True
        return False

    # --------------------------------------------------------------- panes
    def _show_texts(self, app):
        from .engines.reader import ReaderEngine
        from . import host as host_module
        host = host_module.ClingHost(app, self.language,
                                     speaker=_QuietSpeaker(),
                                     mixer=host_module.Mixer())
        engine = ReaderEngine(host)
        engine.entries = engine._collect()
        body = '\n\n'.join('%s\n%s' % (label, text)
                           for label, text in engine.entries)
        _show_text_window(self, app.name(self.language),
                          body or self._('This application ships no text.'))

    def _show_scores(self, app):
        from . import account as account_module, store as store_module
        local = store_module.Store(app.id, account_module.profile())
        lines = ['%d. %s: %d' % (position, entry.get('name') or '-',
                                 int(entry.get('points', 0)))
                 for position, entry in enumerate(local.scores(), start=1)]
        shared = account_module.leaderboard(app.id)
        if shared:
            lines.append('')
            lines.append(self._('On Titan-Net:'))
            lines.extend('%d. %s: %d' % (position, row.get('name') or '?',
                                         int(row.get('points', 0) or 0))
                         for position, row in enumerate(shared, start=1))
        _show_text_window(self, app.name(self.language),
                          '\n'.join(lines) or self._('No scores yet.'))

    def _show_details(self, app):
        if getattr(app, 'locked', False):
            _show_text_window(self, app.name(self.language),
                              app.locked_reason())
            return
        lines = [
            '%s: %s' % (self._('Name'), app.name(self.language)),
            '%s: %s' % (self._('Identifier'), app.id),
            '%s: %s' % (self._('Version'), app.version or '-'),
            '%s: %s' % (self._('Engine'), _engine_label(self._, app.engine)),
            '%s: %s' % (self._('Category'), app.category),
            '%s: %s' % (self._('Language'),
                        app.texts.locale if app.texts else '-'),
            '%s: %s' % (self._('Folder'), app.path),
        ]
        if app.package:
            lines.append('%s: %s' % (self._('Original Klango package'),
                                     app.package))
        if app.summary(self.language):
            lines.insert(1, app.summary(self.language))
        for problem in app.problems:
            lines.append('%s: %s' % (self._('Problem'), problem))
        _show_text_window(self, app.name(self.language), '\n'.join(lines))

    def _open_folder(self, app):
        try:
            from src.platform_utils import open_file_manager
            open_file_manager(app.path)
        except Exception as error:
            wx.MessageBox(str(error), self._('Cling'), wx.OK | wx.ICON_ERROR)


class _QuietSpeaker(object):
    """A speaker for the panes that only READ an application, never run it."""

    spoken = ()

    def say(self, *_args, **_kwargs):
        return False

    def stop(self):
        pass


def _engine_label(translate, engine):
    return {
        catalog.ENGINE_GRID_HUNT: translate('board game'),
        catalog.ENGINE_SOUNDSCAPE: translate('soundscape'),
        catalog.ENGINE_INSTRUMENT: translate('instrument'),
        catalog.ENGINE_TYPING: translate('course'),
        catalog.ENGINE_SCRIPT: translate('application'),
        catalog.ENGINE_READER: translate('text'),
    }.get(engine, engine)


def _show_text_window(parent, title, body):
    """A read-only window a screen reader can walk with its own cursor."""
    frame = wx.Frame(parent, title=title, size=(700, 520))
    panel = wx.Panel(frame)
    sizer = wx.BoxSizer(wx.VERTICAL)
    control = wx.TextCtrl(panel, value=body,
                          style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
    sizer.Add(control, proportion=1, flag=wx.EXPAND | wx.ALL, border=8)
    panel.SetSizer(sizer)
    frame.Bind(wx.EVT_CHAR_HOOK,
               lambda event: frame.Close()
               if event.GetKeyCode() == wx.WXK_ESCAPE else event.Skip())
    apply_skin_tree(frame)
    frame.Show()
    control.SetFocus()
    return frame


#: The surfaces that are open, so an application is not started twice.
_open = {}


def run_app(app, parent=None, translate=None, language=''):
    """Open an application in its own window. Returns the surface."""
    existing = _open.get(app.id)
    if existing is not None:
        try:
            if existing and not existing.IsBeingDeleted():
                existing.Raise()
                return existing
        except RuntimeError:
            pass
        _open.pop(app.id, None)
    surface = ClingSurface(parent, app, language, translate)
    _open[app.id] = surface
    surface.Bind(wx.EVT_WINDOW_DESTROY,
                 lambda event: (_open.pop(app.id, None), event.Skip()))
    return surface.run()
