# -*- coding: utf-8 -*-
"""Titan, as a program in another language reaches it.

One table of calls (`TitanAPI.CALLS`) is the whole surface, and it is the
security boundary as well: a guest names a call or it does not exist. The
same object answers a Lua program running in this process and a Ruby,
JavaScript, PowerShell or C# program speaking the line protocol, so a call
behaves identically in every language.

Two things the API never does itself:

* **speak or play** - that is Titan's: ``titan.speak`` and
  ``titan.play_sound`` are asked for (over the Action Bus from the host
  process, directly inside Titan's), so a program in any language talks in
  the user's own voice and plays through the user's own mixer and theme
  volume;
* **draw anything that is not native** - every dialog is a real wx dialog and
  the game window a real focusable window, so a screen reader reads them with
  nothing written here.
"""

import inspect
import json
import os
import queue
import threading
import time

from .i18n import _
from . import runtimes


class ApiError(Exception):
    """A refusal the guest is told about, in a sentence."""


def _json_safe(value):
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


# ----------------------------------------------------------------------- keys
def _key_names():
    import wx
    names = {
        wx.WXK_LEFT: 'left', wx.WXK_RIGHT: 'right', wx.WXK_UP: 'up',
        wx.WXK_DOWN: 'down', wx.WXK_HOME: 'home', wx.WXK_END: 'end',
        wx.WXK_PAGEUP: 'pageup', wx.WXK_PAGEDOWN: 'pagedown',
        wx.WXK_RETURN: 'enter', wx.WXK_NUMPAD_ENTER: 'enter',
        wx.WXK_ESCAPE: 'escape', wx.WXK_SPACE: 'space', wx.WXK_TAB: 'tab',
        wx.WXK_BACK: 'backspace', wx.WXK_DELETE: 'delete',
        wx.WXK_INSERT: 'insert', wx.WXK_SHIFT: 'shift',
        wx.WXK_CONTROL: 'ctrl', wx.WXK_ALT: 'alt',
    }
    for number in range(1, 13):
        names[getattr(wx, 'WXK_F%d' % number)] = 'f%d' % number
    for number in range(10):
        names[getattr(wx, 'WXK_NUMPAD%d' % number)] = 'numpad%d' % number
    return names


def key_name(code):
    """What a key is called in an event: 'left', 'a', '5', 'f1'..."""
    try:
        name = _key_names().get(code)
    except Exception:
        name = None
    if name:
        return name
    if 32 < code < 127:
        return chr(code).lower()
    return 'key%d' % code


class _KeyWindow(object):
    """The window a game holds the keyboard with.

    Almost empty on purpose - a game is heard, not read - but a real window
    with a real name, whose one control takes the keyboard, so a screen reader
    says the game's title on arrival and every key reaches the game.
    """

    def __init__(self, api, title):
        import wx
        self.api = api
        self.held = set()
        self.frame = wx.Frame(None, title=title, size=(480, 320))
        self.panel = wx.Panel(self.frame, style=wx.WANTS_CHARS)
        self.panel.SetName(title)
        self.panel.Bind(wx.EVT_KEY_DOWN, self._down)
        self.panel.Bind(wx.EVT_KEY_UP, self._up)
        self.panel.Bind(wx.EVT_CHAR, self._char)
        self.frame.Bind(wx.EVT_CLOSE, self._close)
        self.frame.Bind(wx.EVT_ACTIVATE, self._activate)
        self.frame.Show()
        self.frame.Raise()
        self.panel.SetFocus()

    def _modifiers(self, event):
        return {'shift': bool(event.ShiftDown()),
                'ctrl': bool(event.ControlDown()),
                'alt': bool(event.AltDown())}

    def _down(self, event):
        name = key_name(event.GetKeyCode())
        info = {'type': 'key', 'key': name, 'down': True,
                'repeat': name in self.held}
        info.update(self._modifiers(event))
        self.held.add(name)
        self.api.post(info)
        event.Skip()            # so EVT_CHAR still arrives for typed letters

    def _up(self, event):
        name = key_name(event.GetKeyCode())
        self.held.discard(name)
        info = {'type': 'key', 'key': name, 'down': False, 'repeat': False}
        info.update(self._modifiers(event))
        self.api.post(info)

    def _char(self, event):
        code = event.GetUnicodeKey()
        if code and code >= 32 and code != 127:
            self.api.post({'type': 'char', 'char': chr(code)})

    def _activate(self, event):
        active = bool(event.GetActive())
        if active:
            try:
                self.panel.SetFocus()
            except Exception:
                pass
        else:
            # A release lost to another window would leave a key held for
            # ever; say every held key came up.
            for name in sorted(self.held):
                self.api.post({'type': 'key', 'key': name, 'down': False,
                               'repeat': False, 'shift': False,
                               'ctrl': False, 'alt': False})
            self.held.clear()
        self.api.post({'type': 'focus', 'active': active})
        event.Skip()

    def _close(self, event):
        self.api.post({'type': 'close'})
        self.api.window = None
        self.frame.Destroy()

    def destroy(self):
        try:
            self.frame.Destroy()
        except Exception:
            pass


class TitanAPI(object):
    """Everything a guest program may ask of Titan."""

    #: name -> method name. Nothing outside this table is callable.
    CALLS = ('info', 'speak', 'stop_speech', 'play', 'stop_sounds',
             'message', 'ask', 'confirm', 'choose', 'text', 'open_window',
             'close_window', 'next_event', 'wait', 'action', 'data_dir',
             'log', 'exit', 'add_menu', 'title',
             # Titan calling the program back (adapters.py): what the
             # program defines, its answers, and the objects it is handed.
             'provide', 'reply', 'host')

    def __init__(self, app_dir, title, kind='app', runtime_id='',
                 titan_call=None, on_gui=None, log=None, ident=''):
        self.app_dir = os.path.abspath(app_dir or '.')
        self._title = title or os.path.basename(self.app_dir)
        self.kind = kind
        self.runtime_id = runtime_id
        self.ident = ident or os.path.basename(self.app_dir)
        self._titan_call = titan_call
        self._on_gui = on_gui or _call_here
        self._log = log or (lambda text: None)
        self.events = queue.Queue()
        self.window = None
        self.exit_code = None
        self.menu_handler = None        # set by whoever can put entries in a menu
        self.bridge = None              # adapters.ForeignAddon, for host/reply
        self.tick = None                # called on every wait, for the Lua steps

    # -------------------------------------------------------------- plumbing
    def post(self, event):
        self.events.put(event)

    def dispatch(self, name, args=None):
        """Run one call. ``args`` is a dict (named) or a list (positional)."""
        if name not in self.CALLS:
            raise ApiError(_("There is no call named '{}'.").format(name))
        method = getattr(self, name)
        if isinstance(args, (list, tuple)):
            return _json_safe(method(*args))
        args = dict(args or {})
        accepted = inspect.signature(method).parameters
        if not any(p.kind == p.VAR_KEYWORD for p in accepted.values()):
            args = {k: v for k, v in args.items() if k in accepted}
        return _json_safe(method(**args))

    def _titan(self, addon, action, **args):
        if self._titan_call is None:
            raise ApiError(_("Titan is not running."))
        try:
            return self._titan_call(addon, action, **args)
        except ApiError:
            raise
        except Exception as error:
            self._log('%s.%s: %s' % (addon, action, error))
            raise ApiError(_("Titan is not running.")) from None

    # ------------------------------------------------------------------ calls
    def info(self):
        from .i18n import language
        return {'protocol': 1, 'title': self._title, 'kind': self.kind,
                'runtime': self.runtime_id, 'app_dir': self.app_dir,
                'data_dir': self.data_dir(), 'language': language(),
                'calls': list(self.CALLS)}

    def title(self, text=None):
        """The program's title; a new one renames its window too."""
        if text:
            self._title = str(text)
            if self.window is not None:
                window = self.window
                self._on_gui(lambda: (window.frame.SetTitle(self._title),
                                      window.panel.SetName(self._title)))
        return self._title

    def speak(self, text, interrupt=True, position=None, rate=None,
              pitch=None, wait=False):
        text = str(text if text is not None else '')
        if not text.strip():
            return False
        args = {'text': text, 'interrupt': bool(interrupt), 'wait': bool(wait)}
        for key, value in (('position', position), ('rate', rate),
                           ('pitch', pitch)):
            if value is not None:
                args[key] = value
        try:
            result = self._titan('titan', 'speak', **args)
            return bool(getattr(result, 'ok', True))
        except Exception as error:
            self._log('speak through Titan failed: %s' % error)
        return _speak_fallback(text, interrupt)

    def stop_speech(self):
        try:
            self._titan('titan', 'stop_speech')
            return True
        except Exception:
            return False

    def play(self, file, position=0.0, wait=False, to=None, duration=None):
        """A sound from the program's folder, or one of the user's theme.

        ``to`` with ``duration`` makes it travel across the stereo field
        while it plays - what an audio game aims by.
        """
        path = self._resolve(file)
        if not path:
            raise ApiError(_("There is no sound called '{}'.").format(file))
        args = {'path': path, 'position': float(position or 0.0),
                'wait': bool(wait)}
        if to is not None:
            args['to'] = float(to)
            args['duration'] = float(duration or 2.0)
        try:
            result = self._titan('titan', 'play_sound', **args)
        except ApiError:
            return False
        return bool(getattr(result, 'ok', True))

    def stop_sounds(self):
        try:
            self._titan('titan', 'stop_sounds')
            return True
        except Exception:
            return False

    def _resolve(self, name):
        name = str(name or '')
        if not name:
            return ''
        candidates = [name] if os.path.isabs(name) else [
            os.path.join(self.app_dir, name),
            os.path.join(self.app_dir, 'sounds', name),
            os.path.join(self.app_dir, 'sfx', name)]
        if not os.path.isabs(name):
            # A sound of Titan's own theme: "ui/notify.ogg", "core/SELECT".
            for folder in _theme_folders():
                candidates.append(os.path.join(folder, name))
        for candidate in candidates:
            for suffix in ('', '.ogg', '.wav', '.mp3', '.flac'):
                if os.path.isfile(candidate + suffix):
                    return os.path.abspath(candidate + suffix)
        return ''

    def _parent(self):
        return self.window.frame if self.window is not None else None

    def message(self, text, title=None):
        import wx

        def show():
            dialog = wx.MessageDialog(self._parent(), str(text),
                                      str(title or self._title),
                                      wx.OK | wx.ICON_INFORMATION)
            dialog.ShowModal()
            dialog.Destroy()
        self._on_gui(show)
        return True

    def ask(self, prompt, default='', title=None, multiline=False,
            password=False):
        import wx

        def show():
            style = wx.OK | wx.CANCEL
            if multiline:
                style |= wx.TE_MULTILINE
            if password:
                dialog = wx.PasswordEntryDialog(
                    self._parent(), str(prompt), str(title or self._title),
                    str(default or ''))
            else:
                dialog = wx.TextEntryDialog(
                    self._parent(), str(prompt), str(title or self._title),
                    str(default or ''), style=style)
            try:
                if dialog.ShowModal() == wx.ID_OK:
                    return dialog.GetValue()
                return None
            finally:
                dialog.Destroy()
        return self._on_gui(show)

    def confirm(self, text, title=None):
        import wx

        def show():
            dialog = wx.MessageDialog(self._parent(), str(text),
                                      str(title or self._title),
                                      wx.YES_NO | wx.ICON_QUESTION)
            try:
                return dialog.ShowModal() == wx.ID_YES
            finally:
                dialog.Destroy()
        return bool(self._on_gui(show))

    def choose(self, prompt, options, title=None, selected=0):
        """The index (from 0) of the option chosen, or None."""
        import wx
        options = [str(o) for o in (options or [])]
        if not options:
            raise ApiError(_("Nothing to choose from."))

        def show():
            dialog = wx.SingleChoiceDialog(self._parent(), str(prompt),
                                           str(title or self._title), options)
            try:
                index = int(selected or 0)
                if 0 <= index < len(options):
                    dialog.SetSelection(index)
                if dialog.ShowModal() == wx.ID_OK:
                    return dialog.GetSelection()
                return None
            finally:
                dialog.Destroy()
        return self._on_gui(show)

    def text(self, text, title=None):
        """A page to read: a read-only field the reader's cursor can walk."""
        import wx

        def show():
            dialog = wx.Dialog(self._parent(), title=str(title or self._title),
                               size=(640, 480),
                               style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
            field = wx.TextCtrl(dialog, value=str(text),
                                style=wx.TE_MULTILINE | wx.TE_READONLY)
            field.SetName(str(title or self._title))
            close = wx.Button(dialog, wx.ID_CANCEL, _("Close"))
            sizer = wx.BoxSizer(wx.VERTICAL)
            sizer.Add(field, 1, wx.EXPAND | wx.ALL, 8)
            sizer.Add(close, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
            dialog.SetSizer(sizer)
            field.SetFocus()
            dialog.ShowModal()
            dialog.Destroy()
        self._on_gui(show)
        return True

    def open_window(self, title=None):
        """A window that takes the keyboard and reports every key."""
        if title:
            self._title = str(title)
        if self.window is not None:
            window = self.window
            self._on_gui(lambda: (window.frame.Raise(), window.panel.SetFocus()))
            return True

        def build():
            self.window = _KeyWindow(self, self._title)
        self._on_gui(build)
        return True

    def close_window(self):
        window, self.window = self.window, None
        if window is not None:
            self._on_gui(window.destroy)
        return True

    def next_event(self, timeout=None):
        """The next key, character, menu or close event; None after timeout.

        ``timeout`` None or negative waits for ever (in short turns, so a
        guest that has gone is noticed); 0 only looks.
        """
        if self.tick:
            self.tick()
        try:
            limit = None if timeout is None else float(timeout)
        except (TypeError, ValueError):
            limit = None
        if limit is not None and limit <= 0:
            try:
                return self.events.get_nowait()
            except queue.Empty:
                return None
        end = None if limit is None or limit < 0 else time.time() + limit
        while True:
            turn = 0.25 if end is None else max(0.0, min(0.25, end - time.time()))
            try:
                return self.events.get(timeout=turn)
            except queue.Empty:
                if end is not None and time.time() >= end:
                    return None
                if self.exit_code is not None:
                    return {'type': 'close'}

    def wait(self, seconds):
        if self.tick:
            self.tick()
        time.sleep(max(0.0, min(float(seconds or 0), 3600.0)))
        return True

    def action(self, addon, action, args=None):
        """Any Titan add-on's action. Answers {ok, text}."""
        if not isinstance(args, dict):
            args = {}
        try:
            result = self._titan(str(addon), str(action), **args)
        except ApiError as error:
            return {'ok': False, 'text': str(error)}
        ok = bool(getattr(result, 'ok', True))
        return {'ok': ok, 'text': str(getattr(result, 'text', result) or '')}

    def data_dir(self):
        folder = os.path.join(runtimes.user_dir(), 'data', self.ident)
        os.makedirs(folder, exist_ok=True)
        return folder

    def log(self, text):
        self._log(str(text))
        return True

    def exit(self, code=0):
        try:
            self.exit_code = int(code or 0)
        except (TypeError, ValueError):
            self.exit_code = 0
        return True

    # ------------------------------------------------- Titan calling back
    def _need_bridge(self):
        if self.bridge is None:
            raise ApiError(_("Only an add-on Titan calls into can do this."))
        return self.bridge

    def provide(self, names=None):
        """The functions this program answers when Titan calls it."""
        if isinstance(names, str):
            names = [names]
        self._need_bridge().provided(list(names or []))
        return True

    def reply(self, id=None, value=None, error=None):
        """The answer to a {type: 'call'} event."""
        self._need_bridge().replied(id, value, error)
        return True

    def host(self, target=None, method=None, args=None):
        """Call a method of an object Titan handed the program - the API of
        a launcher, a settings interface or a shell add-on, the sounds of a
        Titan IM module, the gamepad helpers..."""
        return self._need_bridge().host(target, method, args)

    def add_menu(self, label):
        """A Components menu entry; pressing it posts {type: 'menu'}."""
        if self.menu_handler is None:
            raise ApiError(_("Only a component can add a menu entry."))
        self.menu_handler(str(label))
        return True


def _call_here(function):
    return function()


def _theme_folders():
    """``sfx/<the user's theme>`` and ``sfx/default``, overlay first."""
    theme = 'default'
    try:
        from src.settings.settings import load_settings
        theme = (load_settings().get('sound', {}) or {}).get('theme') or theme
    except Exception:
        pass
    roots = []
    try:
        from src.platform_utils import get_user_resource_path
        roots.append(get_user_resource_path('sfx'))
    except Exception:
        pass
    # Titan's own folder: the launcher says where it is (the host process
    # must not import Titan's sound system just to find a file), and inside
    # Titan the app manager is already loaded.
    root = os.environ.get('TITAN_ROOT', '')
    if not root:
        import sys
        manager = sys.modules.get('src.titan_core.app_manager')
        if manager is not None:
            root = manager.resource_path('')
    if not root:
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            runtimes.COMPONENT_DIR)))
    roots.append(os.path.join(root, 'sfx'))
    out = []
    for name in dict.fromkeys([theme, 'default']):
        for root in roots:
            out.append(os.path.join(root, name))
    return out


def gui_caller(timeout=None):
    """``on_gui`` for a process whose wx main loop runs on another thread."""
    import wx

    def on_gui(function):
        if wx.IsMainThread():
            return function()
        done = threading.Event()
        box = {}

        def run():
            try:
                box['value'] = function()
            except BaseException as error:            # noqa: B902
                box['error'] = error
            finally:
                done.set()
        wx.CallAfter(run)
        done.wait(timeout)
        if 'error' in box:
            raise box['error']
        return box.get('value')
    return on_gui


def _speak_fallback(text, interrupt):
    """Titan was not there to ask; the screen reader still is."""
    try:
        from accessible_output3.outputs.auto import Auto
        Auto().speak(text, interrupt=bool(interrupt))
        return True
    except Exception:
        return False
