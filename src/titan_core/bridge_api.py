"""One typed surface onto Titan, for a program that is not Titan.

The TCE bridge in Elten was built on Titan's ACTIONS, and that turned out to
be a poor foundation for an interface. Actions are written for a model and
for macros: they answer in prose, in the user's own language, with names and
argument spellings that differ from one add-on to the next, and a Titan that
has not been restarted simply does not have the newest ones - which reaches
the user as "'Titan' has no action 'components'" rather than as anything
they can act on. Every one of those cost a live bug: a list of folder names
where launchable names were needed, `level` where the action wanted
`percent`, a shell state read out of a translated sentence.

So this is the bridge's own doorway, and the rules are the opposite ones:

* **One call, one shape.** Every answer is `{"ok": true, "data": ...}` or
  `{"ok": false, "error": "..."}`. Never prose to be parsed, never a
  sentence whose wording depends on the user's language.
* **One registration.** The whole surface arrives as a single action,
  `titan.bridge`, so a Titan that is a version behind is missing ONE thing
  and can say so exactly, with its version, instead of failing call by call.
* **Titan's own objects.** Applications come from `app_manager`, games from
  `game_manager`, components from the live `ComponentManager`, settings from
  `ui_model`, Titan-Net from the client the user is already signed in to.
  Nothing here re-implements Titan; it hands over what Titan already has.

The action layer is not replaced: `addons.*` below is that layer, kept
deliberately, because it is the only way to reach an add-on nobody has
written a screen for.
"""

import json
import time

from src.titan_core.actions.inproc import run_on_gui

# Raised by one call by name; the client compares it with its own and says
# plainly that Titan is older than the add-on rather than guessing.
API_VERSION = 2


# --------------------------------------------------------------------------- #
# Titan's own window
# --------------------------------------------------------------------------- #
def _frame():
    try:
        import wx
    except Exception:
        return None
    try:
        app = wx.GetApp()
        return app.GetTopWindow() if app is not None else None
    except Exception:
        return None


def _hello(_args):
    """Who is answering, and what this Titan is."""
    import os

    def read():
        from src.titan_core import translation
        language = getattr(translation, 'current_language', '') or ''
        frame = _frame()
        return {
            'api': API_VERSION,
            'language': str(language),
            'has_window': frame is not None,
            # Which process Titan IS. A screen reader's add-on has to know,
            # because "is this window Titan's?" is the question that decides
            # whether it behaves like Titan's own reader - and it cannot work
            # it out: Titan run from source is `python.exe`, and recognising
            # it by name would take over every Python program on the machine.
            # It used to be told this only when Titan first ANNOUNCED
            # something, which on a quiet desktop is never, so the whole
            # behaviour was switched off until Titan happened to speak.
            'pid': os.getpid(),
            'at': time.time(),
        }
    data, error = run_on_gui(read)
    if error:
        return {'api': API_VERSION, 'language': '', 'has_window': False,
                'pid': os.getpid()}
    return data


# --------------------------------------------------------------------------- #
# Applications, games, Titan IM modules - from the managers themselves
# --------------------------------------------------------------------------- #
def _language(args):
    """The two-letter language the CALLER wants, or Titan's own.

    An add-on's name is written per language in its manifest - `name_pl`,
    `name_en` - and Titan picks by the language IT is running in. A bridge
    is read by somebody sitting in another program, which may well be in
    another language, so the caller says which it wants and gets that.
    """
    wanted = str(args.get('language') or '').strip().lower()
    wanted = wanted.replace('_', '-').split('-')[0]
    if len(wanted) == 2:
        return wanted
    try:
        from src.titan_core.translation import language_code
        return str(language_code or 'en')[:2]
    except Exception:
        return 'en'


def _named(info, language):
    """The record's own name in that language, then English, then whatever
    it has - the rule `read_app_info` uses, applied to games too."""
    for key in (f'name_{language}', 'name_en', 'name'):
        value = info.get(key)
        if value:
            return str(value)
    return str(info.get('shortname') or '')


def _app_record(info, language='en'):
    return {
        'name': _named(info, language),
        'shortname': str(info.get('shortname') or ''),
        'description': str(info.get(f'description_{language}')
                           or info.get('description') or ''),
        'path': str(info.get('path') or ''),
    }


def _apps(args):
    language = _language(args)

    def read():
        from src.titan_core import app_manager
        out = []
        for info in app_manager.get_applications():
            # Read again in the language asked for: `get_applications` has
            # already chosen Titan's own.
            path = info.get('path')
            detailed = info
            if path:
                try:
                    detailed = app_manager.read_app_info(path, language) or info
                except Exception:
                    detailed = info
            out.append(_app_record(detailed, language))
        return out
    data, error = run_on_gui(read)
    if error:
        raise RuntimeError(error)
    return {'applications': data, 'language': language}


def _open_app(args):
    """Open one by its own name - the name the list gave, not a guess.

    **Where it opens is the CLIENT's choice.** By default it opens where
    it always has: a window on this machine's screen, which is what a
    person sitting at Titan wants. A client that is going to render the
    interface itself - a bridge on another machine, a launcher, a script -
    passes `render` and gets the application described instead, with a
    session to work it through. It is one argument rather than a second
    call so that the choice is discoverable: a client should not have to
    already know that `app.open` exists to find out it can do this.
    """
    wanted = str(args.get('name') or '').strip().lower()
    if not wanted:
        raise ValueError('name is required')
    if args.get('render'):
        return _app_ui_open(args)

    def start():
        from src.titan_core import app_manager
        for info in app_manager.get_applications():
            names = {str(info.get('name') or '').lower(),
                     str(info.get('shortname') or '').lower()}
            # Whatever language the list was read in, that is the name the
            # user pressed - so every spelling of it opens the same thing.
            path = info.get('path')
            if path:
                for language in ('en', 'pl'):
                    try:
                        other = app_manager.read_app_info(path, language) or {}
                    except Exception:
                        continue
                    if other.get('name'):
                        names.add(str(other['name']).lower())
            if wanted in names:
                app_manager.open_application(info)
                return str(info.get('name') or wanted)
        return None
    opened, error = run_on_gui(start)
    if error:
        raise RuntimeError(error)
    if opened is None:
        raise LookupError(f"there is no application called {args.get('name')}")
    return {'opened': opened}


def _games(args):
    language = _language(args)

    def read():
        from src.titan_core import game_manager
        out = []
        for info in game_manager.get_games():
            out.append({'name': _named(info, language),
                        'platform': str(info.get('platform') or ''),
                        'path': str(info.get('path') or '')})
        return out
    data, error = run_on_gui(read)
    if error:
        raise RuntimeError(error)
    return {'games': data, 'language': language}


def _open_game(args):
    wanted = str(args.get('name') or '').strip().lower()
    if not wanted:
        raise ValueError('name is required')

    def start():
        from src.titan_core import game_manager
        for info in game_manager.get_games():
            names = {str(info.get('name') or '').lower()}
            for key in ('name_en', 'name_pl'):
                if info.get(key):
                    names.add(str(info[key]).lower())
            if wanted in names:
                game_manager.open_game(info)
                return str(info.get('name'))
        return None
    opened, error = run_on_gui(start)
    if error:
        raise RuntimeError(error)
    if opened is None:
        raise LookupError(f"there is no game called {args.get('name')}")
    return {'opened': opened}


def _im_modules(_args):
    def read():
        try:
            from src.network.im_module_manager import im_module_manager
        except Exception:
            return []
        out = []
        for info in getattr(im_module_manager, 'modules', []) or []:
            out.append({'id': str(info.get('id') or ''),
                        'name': str(info.get('name') or info.get('id') or '')})
        return out
    data, error = run_on_gui(read)
    if error:
        raise RuntimeError(error)
    return {'modules': data}


def _open_im_module(args):
    wanted = str(args.get('id') or args.get('name') or '').strip().lower()
    if not wanted:
        raise ValueError('id is required')

    def start():
        from src.network.im_module_manager import im_module_manager
        for info in getattr(im_module_manager, 'modules', []) or []:
            names = {str(info.get('id') or '').lower(),
                     str(info.get('name') or '').lower()}
            if wanted in names:
                im_module_manager.open_module(str(info.get('id') or wanted),
                                              _frame())
                return str(info.get('name') or wanted)
        return None
    opened, error = run_on_gui(start)
    if error:
        raise RuntimeError(error)
    if opened is None:
        raise LookupError(f"there is no Titan IM module called {wanted}")
    return {'opened': opened}


# --------------------------------------------------------------------------- #
# What the older helpers already read out of Titan, as data rather than prose
# --------------------------------------------------------------------------- #
def _from_json(text, what):
    """A helper that answers JSON on success and a sentence on failure."""
    text = str(text or '')
    if text.startswith('{') or text.startswith('['):
        try:
            return json.loads(text)
        except ValueError:
            pass
    raise RuntimeError(text or f'{what} could not be read')


def _views(_args):
    from src.ui.main_window_actions import _views as read
    return _from_json(read(), 'the views')


def _status_bar(_args):
    from src.ui.main_window_actions import _status_bar as read
    return _from_json(read(), 'the status bar')


def _menu(_args):
    from src.ui.main_window_actions import _menu as read
    return _from_json(read(), "Titan's menu")


def _menu_run(args):
    from src.ui.main_window_actions import _menu_run as run
    return {'said': run(entry=args.get('entry', ''))}


def _components(_args):
    from src.ui.main_window_actions import _components as read
    return _from_json(read(), 'the components')


def _widgets(_args):
    from src.ui.main_window_actions import _widgets as read
    return _from_json(read(), 'the widgets')


def _widget_read(args):
    from src.ui.main_window_actions import _widget_read as read
    return {'element': read(widget=args.get('widget', ''))}


def _widget_move(args):
    from src.ui.main_window_actions import _widget_move as move
    return {'element': move(widget=args.get('widget', ''),
                            direction=args.get('direction', 'next'))}


def _widget_press(args):
    from src.ui.main_window_actions import _activate_widget as press
    return {'said': press(widget=args.get('widget', ''))}


def _buffers(_args):
    from src.ui.main_window_actions import _buffers as read
    return _from_json(read(), 'the buffers')


def _buffer(args):
    from src.ui.main_window_actions import _buffer as read
    return _from_json(read(category=args.get('category', ''),
                           buffer=args.get('buffer', ''),
                           limit=args.get('limit', 100)), 'the buffer')


def _notifications(_args):
    from src.ui.main_window_actions import _notifications as read
    return _from_json(read(), 'the notifications')


def _settings_screen(args):
    from src.settings.settings_actions import _screen as read
    return _from_json(read(category=args.get('category', '')), 'the settings')


def _settings_set(args):
    from src.settings.settings_actions import _set_value as write
    return {'said': write(item=args.get('item', ''), value=args.get('value', ''))}


def _settings_press(args):
    from src.settings.settings_actions import _press as press
    return {'said': press(item=args.get('item', ''))}


def _settings_save(_args):
    from src.settings.settings_actions import _save as save
    return {'said': save()}


def _settings_cancel(_args):
    from src.settings.settings_actions import _cancel as cancel
    return {'said': cancel()}


# --------------------------------------------------------------------------- #
# Speech and the AI - the reader's own path, without going through an action
# --------------------------------------------------------------------------- #
def _speak(args):
    from src.titan_core.reader_actions import _reader_speak as speak
    return {'said': speak(text=args.get('text', ''),
                          interrupt=args.get('interrupt', True),
                          pitch=args.get('pitch', 0),
                          position=args.get('position', 0),
                          spelling=args.get('spelling', False))}


def _stop_speech(_args):
    from src.ai.titan_tools import titan_stop_speech
    return {'said': titan_stop_speech()}


def _speaking(_args):
    from src.ai.titan_tools import titan_speaking
    return {'speaking': titan_speaking()}


def _speech_rate(args):
    from src.titan_core.reader_actions import _set_rate, _get_rate
    if args.get('rate') in (None, ''):
        return {'rate': _get_rate()}
    return {'was': _set_rate(rate=args.get('rate'))}


def _ai_available(_args):
    from src.titan_core.reader_actions import _ai_enabled
    return {'available': bool(_ai_enabled())}


def _ai_ask(args):
    from src.titan_core.reader_actions import _ask_ai
    return {'answer': _ask_ai(question=args.get('question', ''),
                              act=args.get('act', False))}


def _ai_history(args):
    from src.titan_core.reader_actions import _ai_history as read
    return _from_json(read(limit=args.get('limit', 20)), 'the conversation')


def _ai_forget(_args):
    from src.titan_core.reader_actions import _ai_forget_conversation as forget
    return {'said': forget()}


# --------------------------------------------------------------------------- #
# The action layer, kept on purpose
# --------------------------------------------------------------------------- #
def _addons(args):
    """Every add-on Titan can drive. The only way to reach one nobody has
    written a screen for, which is why the action layer stays."""
    from src.titan_core.actions import dispatch
    return {'addons': dispatch.list_addons(str(args.get('kind') or ''))}


def _addon_actions(args):
    from src.titan_core.actions.builtin import _addon_actions_json
    return _from_json(_addon_actions_json(addon=args.get('addon', '')),
                      "the add-on's actions")


def _addon_run(args):
    from src.titan_core.actions import dispatch
    result = dispatch.run(str(args.get('addon') or ''),
                          str(args.get('action') or ''),
                          **(args.get('args') or {}))
    answer = {'ok': bool(result.ok), 'text': str(result.text or '')}
    if result.pending and result.question is not None:
        answer['question'] = result.question.to_dict()
    return answer


# --------------------------------------------------------------------------- #
# The two components with a list of THINGS in them
#
# The macros and the Cling applications are lists whose rows are acted on by
# NAME, and both were being read out of the prose their actions answer with:
# "3 macros:\n- Voice demo (ctrl+alt+v) [tcs]", "Cling applications:\n- Mole
# No More (mole, grid_hunt): ...". A client that splits those lines up hands
# the name back with the count, the shortcut, the identifier, the engine and
# the summary still attached to it - and Titan answers "There is no macro
# called '- Voice demo (ctrl+alt+v) [tcs]'". Both of the bugs reported
# against the Elten bridge were exactly that, in two different components,
# which is what a shape rather than a sentence is for.
#
# So the rows come from the components' own objects, with the name a caller
# must hand back kept apart from everything that is only there to be read.
# --------------------------------------------------------------------------- #
def _component_module(folder):
    """One loaded component's module, or None.

    `ComponentManager` registers a component as `sys.modules['<folder>']`
    before it executes it, which is the same handle `actions.inproc` resolves
    a component's own handlers against - so this reaches the LIVE component,
    with the user's own macros in it, rather than importing a second copy.
    """
    import sys
    module = sys.modules.get(folder)
    return module if module is not None and hasattr(module, '__file__') else None


def _macros(_args):
    """The user's macros: the name to act on, and what to show beside it."""
    def read():
        module = _component_module('macros')
        if module is None:
            return None
        manager = getattr(module, '_action_manager', None)
        manager = manager() if callable(manager) else None
        rows = []
        for macro in (getattr(manager, 'macros', None) or []):
            rows.append({'name': str(macro.get('name') or ''),
                         'hotkey': str(macro.get('hotkey') or ''),
                         'type': str(macro.get('type') or '')})
        return rows
    rows, error = run_on_gui(read)
    if error:
        raise RuntimeError(error)
    if rows is None:
        raise RuntimeError('the Macro Manager component is not loaded')
    return {'macros': rows}


def _cling(_args):
    """The Klango applications Cling has found.

    `id` is what every one of Cling's own actions matches first, so it is
    what a caller hands back - a display name is translated and a summary is
    a sentence, and neither is an identifier.
    """
    def read():
        module = _component_module('cling')
        if module is None:
            return None
        language = getattr(module, '_language', None)
        language = language() if callable(language) else 'en'
        rows = []
        for app in (module.applications() or []):
            try:
                rows.append({'id': str(app.id),
                             'name': str(app.name(language)),
                             'engine': str(getattr(app, 'engine', '') or ''),
                             'category': str(getattr(app, 'category', '') or ''),
                             'summary': str(app.summary(language) or ''),
                             'locked': bool(getattr(app, 'locked', False)),
                             'why': (app.locked_reason()
                                     if getattr(app, 'locked', False) else '')})
            except Exception as error:                 # noqa: BLE001
                rows.append({'id': str(getattr(app, 'id', '?')),
                             'name': str(getattr(app, 'id', '?')),
                             'engine': '', 'category': '', 'summary': '',
                             'locked': True, 'why': str(error)})
        return rows
    rows, error = run_on_gui(read)
    if error:
        raise RuntimeError(error)
    if rows is None:
        raise RuntimeError('the Cling component is not loaded')
    return {'applications': rows}


# --------------------------------------------------------------------------- #
# Which face of Titan is up
#
# "Minimise" and "Bring Titan back" are not two entries a menu always has:
# they are one entry that depends on where Titan is. Titan's own window
# offers whichever applies, and a client that offers both offers one that
# does nothing - press "Bring Titan back" on a Titan that is already in
# front and nothing happens, which reads as the bridge being broken.
#
# Away means the window is hidden with a tray icon and the Invisible UI
# answering the keyboard - `TitanApp.minimize_to_tray` is those three things
# together, and `restore_from_tray` is the one way back from it.
# --------------------------------------------------------------------------- #
def _processes(_args):
    """Which process is which part of Titan.

    **The one thing a program looking at a Titan window cannot work out.**
    A TCE application runs in a subprocess of its own, and from the outside
    every one of them is an unremarkable wxPython window: the same class,
    the same roles, a title in the user's own language. So a screen reader
    - the caller this was written for - had no way to know that the list it
    is reading is the file manager's, and therefore no way to know that a
    row of it is a file with a type and a date rather than "list item 3".
    That is the whole of what an app module buys anywhere else, and it was
    unavailable here for want of one number.

    Two sources, because neither is complete on its own: an add-on that
    joined the Action Bus says its own pid, and Titan remembers the pid of
    every application and game it has STARTED - which is the only way to
    know about the ones that declare no actions at all.

    Nothing here is a guess. A pid is answered only while that process is
    really alive, because Windows reuses one the moment a process ends and
    telling a caller that somebody else's window is tNotes would be worse
    than telling it nothing.
    """
    found = {}
    try:
        from src.titan_core.app_manager import launched_processes
        for entry in launched_processes():
            found[int(entry['pid'])] = {
                'pid': int(entry['pid']), 'id': entry.get('id', ''),
                'label': entry.get('label', ''), 'kind': entry.get('kind', 'app'),
                'path': entry.get('path', ''), 'source': 'launched'}
    except Exception:                              # noqa: BLE001
        pass
    try:
        from src.titan_core.actions import bus
        for peer in bus.list_peers():
            pid = int(getattr(peer, 'pid', 0) or 0)
            if pid <= 0:
                continue
            # The bus knows the add-on's real id and label, so it wins over
            # the folder name the launcher had to guess from.
            found[pid] = {'pid': pid,
                          'id': str(getattr(peer, 'addon_id', '') or ''),
                          'label': str(getattr(peer, 'label', '') or ''),
                          'kind': str(getattr(peer, 'kind', '') or 'app'),
                          'path': str(getattr(peer, 'path', '') or ''),
                          'source': 'bus'}
    except Exception:                              # noqa: BLE001
        pass
    import os as _os
    found[_os.getpid()] = {'pid': _os.getpid(), 'id': 'titan',
                           'label': 'Titan', 'kind': 'titan', 'path': '',
                           'source': 'titan'}
    return {'processes': sorted(found.values(), key=lambda row: row['pid'])}


def _window_state(_args):
    def read():
        frame = _main_frame()
        if frame is None:
            return {'has_window': False, 'away': False, 'shown': False,
                    'in_tray': False, 'iconized': False,
                    'invisible_ui': False}
        try:
            shown = bool(frame.IsShown())
        except Exception:
            shown = False
        try:
            iconized = bool(frame.IsIconized())
        except Exception:
            iconized = False
        in_tray = getattr(frame, 'task_bar_icon', None) is not None
        invisible = bool(getattr(getattr(frame, 'invisible_ui', None),
                                 'active', False))
        return {'has_window': True, 'shown': shown, 'iconized': iconized,
                'in_tray': in_tray, 'invisible_ui': invisible,
                # The one a menu actually asks: is the window out of the way?
                'away': bool(in_tray or iconized or not shown)}
    state, error = run_on_gui(read)
    if error:
        raise RuntimeError(error)
    return state


def _main_frame():
    """Titan's own main window, or None. The same one the action layer
    reaches for, so the two cannot disagree about which window Titan is."""
    try:
        from src.ui.main_window_actions import _frame
        return _frame()
    except Exception:
        return None

# --------------------------------------------------------------------------- #
# News from the other side
#
# The bridge runs INSIDE another program - Elten - and that program has news
# of its own: a private message, a forum reply, somebody coming online.
# Titan has a notification centre, a buffer system and an AI that can be
# asked "what have I missed", and none of the three knew anything about it,
# because nothing had ever put an outside program's news into them.
#
# So a client can. It is the same doorway everything else uses, and it lands
# exactly where Titan's own notifications land - the notification centre, the
# Titan category of the buffer system, and the notification sound - so the
# user reads them where they already read the rest, and the AI finds them
# with the tools it already has.
# --------------------------------------------------------------------------- #
def _notification_add(args):
    """Put one piece of news from a client into Titan's own notification
    centre. `app` is who it is from, and it is said as such."""
    import datetime

    app = str(args.get('app') or 'Titan').strip() or 'Titan'
    title = str(args.get('title') or '').strip()
    text = str(args.get('text') or '').strip()
    if not text and not title:
        raise ValueError('text is required')
    if not text:
        text, title = title, ''
    content = f'{title}: {text}' if title else text
    announce = args.get('announce')
    announce = True if announce is None else bool(announce)

    def add():
        from src.ui.notificationcenter import add_notification
        now = datetime.datetime.now()
        add_notification(now.strftime('%Y-%m-%d'), now.strftime('%H:%M'),
                         app, content)
        if announce:
            # `show_notification` is the whole of "the user is told": the
            # sound, the reader, and the Titan category of the buffer
            # system. Reusing it is what makes a client's news behave like
            # Titan's own rather than like a line in a file.
            from src.ui.notificationcenter import show_notification
            show_notification(app, content)
        return True
    ok, error = run_on_gui(add)
    if error:
        raise RuntimeError(error)
    return {'added': bool(ok), 'app': app, 'content': content}


def _notification_clear(_args):
    from src.ui.main_window_actions import _clear_notifications as clear
    return {'said': clear()}

def _client_report(args):
    """What a client knows about the program it is inside.

    The Elten bridge reports Elten - who is signed in, what Elten's own
    notification service is holding, what has arrived - and Titan keeps the
    last report so its AI and its add-ons can ask about a program Titan is
    not in. Nothing is pushed at the user from here: this is a snapshot to
    be READ. `notifications.add` is the other call, and that one is for
    something the user should be told about now.
    """
    from src.titan_core import elten_client_actions
    state = args.get('state')
    if not isinstance(state, dict):
        raise ValueError('state must be an object')
    return elten_client_actions.report(state, args.get('source') or None)


# --------------------------------------------------------------------------- #
# Titan's own sounds
#
# A bridge that makes Titan's interface usable somewhere else should sound
# like Titan while doing it: the user chose a sound theme, and a new private
# message is `titannet/new_message.ogg` in whichever theme that is. The name
# is theme-relative, exactly as Titan's own code plays them, so nothing here
# has to know where a theme lives or which one is chosen.
# --------------------------------------------------------------------------- #
def _play_sound(args):
    name = str(args.get('name') or '').strip()
    if not name:
        raise ValueError('name is required')
    pan = args.get('pan')
    pitch = args.get('pitch')

    def play():
        from src.titan_core import sound
        # The reader's own cursor earcons - `cursor.ogg`, `listitem.ogg`,
        # `edge.ogg`. They belong to the READER rather than to a theme (the
        # user's theme may still override them), and they are the one set
        # that is played PITCHED: a list item says where in the list it is
        # by its tone. A screen reader's add-on asking for one of these
        # means the cue Titan's own reader plays for that event.
        # `reader/` is what a reader calls them and `SRE/` is the folder
        # they live in; both spellings mean the same set, because a client
        # author reading the theme folder and one reading this docstring
        # must not each find only half of it.
        if name.lower().startswith(('reader/', 'sre/')):
            return bool(sound.play_reader_sound(
                name.split('/', 1)[1],
                pan=None if pan in (None, '') else float(pan),
                pitch=1.0 if pitch in (None, '') else float(pitch)))
        # The AI's own set belongs to the FEATURE rather than to a theme, so
        # Titan plays it through `play_ai_sound` - the user's theme first,
        # the default set filling in. A client naming one of those sounds
        # means the AI event it is named after, and should hear it on every
        # theme exactly as Titan's own AI does.
        if name.lower().startswith('ai/'):
            player = getattr(sound, 'play_ai_sound', None)
            if player is not None:
                return bool(player(name))
        # **A file by its absolute path**, for a client that cannot decode
        # it itself: NVDA's own player takes wave files and nothing else,
        # and a user who chose an `.ogg` for a reader sound is asking
        # Titan's mixer, which decodes everything a theme may hold. Only a
        # real file of a sound type, so the doorway cannot be made to open
        # anything else.
        import os as _os
        if _os.path.isabs(name):
            if (_os.path.isfile(name) and _os.path.splitext(name)[1].lower()
                    in ('.wav', '.ogg', '.mp3', '.flac')):
                return bool(sound.play_sound_file(
                    name, pan=None if pan in (None, '') else float(pan)))
            raise ValueError('not a sound file: %s' % name)
        sound.play_sound(name, pan=None if pan in (None, '') else float(pan))
        return True
    played, error = run_on_gui(play)
    if error:
        raise RuntimeError(error)
    return {'played': bool(played), 'name': name}


def _sound_theme(_args):
    def read():
        from src.settings.settings import get_setting
        return str(get_setting('sound_theme', 'default') or 'default')
    theme, error = run_on_gui(read)
    if error:
        raise RuntimeError(error)
    return {'theme': theme}


# ---------------------------------------------------------------------------
# A TCE application, described rather than drawn
# ---------------------------------------------------------------------------
# **The point of these is that they are not Elten's.** The bridge in Elten
# is one external client and the first to want them, but an application's
# interface arrives here as data - controls with kinds, labels and values -
# so any program that can reach this doorway renders it however it renders
# anything. That is the rule `src/settings/ui_model.py` already established
# for the settings and it buys the same thing twice: one description, every
# interface, and an application that is never modified.
def _app_ui_list(args):
    from src.app_ui import sessions
    return sessions.applications(str(args.get('language') or 'en'))


def _app_ui_open(args):
    from src.app_ui import sessions
    wanted = args.get('mirror')
    session, problem = sessions.open_application(
        args.get('name'), owner=str(args.get('client') or ''),
        language=str(args.get('language') or 'en'),
        mirror=None if wanted is None else bool(wanted))
    if session is None:
        raise ValueError(problem)
    return {'session': session.token,
            'application': session.application.name,
            'screen': session.application.screen,
            # **Which of the two it got.** A described screen is the
            # application's own account of itself; a mirrored one is what
            # Windows can see of its window, which is a weaker thing. A
            # client that could not tell them apart would present a
            # mirror as though it were the application.
            'mirror': bool(getattr(session.application, 'mirrored', False)),
            'said': _spoken(session),
            'refused': session.application.refused}


def _app_ui_screen(args):
    held = _app_ui_session(args)
    return {'screen': held.application.screen,
            'said': _spoken(held)}


def _spoken(held):
    """What the application announced, on its way to whoever renders it.

    **An application's own speech is not something Titan should be
    saying.** Every TCE application announces what it has just done -
    "Note saved!", "Folder created!" - and when its interface is
    somewhere else, so is the person being told. The shim puts those
    sentences on the wire instead of building a TTS engine inside the
    application's subprocess, and this is where they leave Titan: a
    client renders them in its own voice, where the user is.

    Delivered once. An announcement is an event and not part of the
    screen, so leaving it in the screen would have it read out again on
    every refresh.
    """
    try:
        return held.application.take_spoken()
    except AttributeError:               # a mirrored window says nothing
        return []


#: Said when the application has not answered in time. Silence and "the
#: screen did not change" look identical to a renderer and mean opposite
#: things - the second is a button that quietly did its work, the first
#: is an application still busy, or stuck, with the interface showing a
#: screen that is no longer true.
def _app_ui_answer(held, answered):
    return {'screen': held.application.screen, 'answered': bool(answered),
            'said': _spoken(held)}


def _app_ui_press(args):
    held = _app_ui_session(args)
    return _app_ui_answer(held, held.application.tell(
        'press', control=_whole(args.get('control'))))


def _app_ui_set(args):
    held = _app_ui_session(args)
    return _app_ui_answer(held, held.application.tell(
        'set', control=_whole(args.get('control')), value=args.get('value')))


def _app_ui_key(args):
    """One key into a described application.

    ``control`` aims it at a field rather than at the window, which is
    what an interface offering an edit mode needs: without it the only
    way to change a field was `app.set` with the whole value, so there
    was no caret, no Backspace and no moving by character or word - a
    field that could be replaced but not typed into.
    """
    held = _app_ui_session(args)
    aimed = args.get('control')
    rest = {'key': str(args.get('key') or '')}
    if aimed not in (None, ''):
        rest['control'] = int(aimed)
    return _app_ui_answer(held, held.application.tell('key', **rest))


def _app_ui_close(args):
    from src.app_ui import sessions
    return {'closed': bool(sessions.close(args.get('session')))}


def _app_ui_sessions(_args):
    from src.app_ui import sessions
    return sessions.open_sessions()


def _app_ui_log(args):
    held = _app_ui_session(args)
    return {'log': [{'level': level, 'text': text}
                    for level, text in held.application.log[-120:]],
            'refused': held.application.refused}


def _app_ui_session(args):
    from src.app_ui import sessions
    held = sessions.get(args.get('session'))
    if held is None:
        raise ValueError('there is no application open with that session')
    return held


def _whole(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1

# --------------------------------------------------------------------------- #
# A window that told a reader nothing, as real controls
# --------------------------------------------------------------------------- #
# AI OCR's overlay is the one thing on this desktop that turns a picture of a
# window into an INTERFACE: every control it read becomes a real wx control, at
# the coordinates of the real one, parented into the target's own window - so a
# screen reader reads them the way it reads any program's, with Tab, the arrows
# and Enter, and nothing in the reader has to know about any of it. That is
# what somebody means by "as if a scripter had scripted the application".
#
# The actions (`ocr.show_overlay` and the rest) answer PROSE, because they also
# answer a model. A client rebuilding an interface must not read a sentence to
# find out whether the overlay went up - this repository has paid for that
# mistake in every direction it can be made - so the same thing is here in one
# shape, with real booleans and real numbers.
def _ocr_model_status(_args):
    """Whether the local recogniser is here, and what it has done.

    Read-only, and answered whether or not anything is installed: "it is
    not there" is the ordinary state and a caller has to be able to tell
    it from "it failed".
    """
    from src.ai.ocr import local_model
    return local_model.report()


def _ocr_install_model(args):
    """Fetch the local recogniser. Minutes, and a download, so it is
    asked for - never done by itself."""
    from src.ai.ocr import local_model
    ok, said = local_model.install(
        timeout=float(args.get('timeout') or 1800.0))
    local_model.forget()
    return {'ok': bool(ok), 'text': said,
            'installed': local_model.installed()}


def _ocr_read_local(args):
    """Read one window with the LOCAL model. Nothing leaves the machine.

    Answers lines in SCREEN coordinates, because that is the only shape a
    reader can act on: `Capture` alone knows what it photographed and
    where, so the conversion happens here rather than being handed to the
    caller as arithmetic it cannot check.
    """
    from src.ai.ocr import capture as capture_module
    from src.ai.ocr import local_model
    ok, why = local_model.available()
    if not ok:
        return {'ok': False, 'text': why, 'lines': [], 'installed': False}
    hwnd = int(args.get('hwnd') or 0)
    shot = (capture_module.capture_window(hwnd) if hwnd
            else capture_module.capture_screen())
    if shot is None or getattr(shot, 'blank', False):
        return {'ok': False, 'lines': [],
                'text': 'that window could not be photographed'}
    picture = _picture_of(shot)
    if picture is None:
        return {'ok': False, 'lines': [],
                'text': 'the picture could not be read back'}
    ok, found = local_model.read_array(picture)
    if not ok:
        return {'ok': False, 'lines': [], 'text': str(found)}
    lines = []
    for one in found:
        left, top, width, height = one['box']
        # The capture knows its own scale and origin; nothing else does.
        where = shot.rect_to_screen([left, top, width, height]) \
            if hasattr(shot, 'rect_to_screen') else (left, top, width, height)
        lines.append({'text': one['text'], 'score': one.get('score', 0.0),
                      'left': int(where[0]), 'top': int(where[1]),
                      'width': int(where[2]), 'height': int(where[3])})
    return {'ok': True, 'lines': lines, 'installed': True,
            'ms': local_model.report().get('ms', 0.0)}


def _picture_of(shot):
    """The capture's PNG back as an ``(h, w, 3)`` array.

    Titan encodes what it captured and keeps the bytes; the model wants
    the pixels. Decoded with zlib and numpy rather than with an imaging
    library, because Titan deliberately has none - `_encode_png` is
    written the same way and this is its mirror.
    """
    try:
        import struct
        import zlib
        import numpy as np
    except Exception:                                # noqa: BLE001
        return None
    data = getattr(shot, 'png', None)
    if not data:
        return None
    try:
        at = 8
        width = height = 0
        pixels = b''
        while at < len(data):
            length = struct.unpack('>I', data[at:at + 4])[0]
            kind = data[at + 4:at + 8]
            body = data[at + 8:at + 8 + length]
            if kind == b'IHDR':
                width, height = struct.unpack('>II', body[:8])
            elif kind == b'IDAT':
                pixels += body
            elif kind == b'IEND':
                break
            at += 12 + length
        if not width or not height:
            return None
        raw = np.frombuffer(zlib.decompress(pixels), dtype=np.uint8)
        raw = raw.reshape(height, 1 + width * 3)
        return raw[:, 1:].reshape(height, width, 3).copy()
    except Exception:                                # noqa: BLE001
        return None


def _ocr_overlay(_args):
    """What is on the window: `{open, window, title, controls, surfaces,
    hidden}`. `open` false is the honest answer for every reason at once."""
    try:
        from src.ai.ocr import overlay
    except Exception as error:
        raise ValueError(f'AI OCR is not available: {error}')
    current = overlay.get_overlay()
    if current is None:
        return {'open': False}
    screen = getattr(current, 'screen', None)
    return {
        'open': True,
        'window': _whole(getattr(current, 'target_hwnd', 0)),
        'title': str(getattr(current, 'target_title', '') or ''),
        'controls': len(getattr(screen, 'elements', []) or []),
        'surfaces': len(getattr(current, 'surfaces', []) or []),
        'hidden': bool(getattr(current, 'hidden', False)),
    }


def _ocr_overlay_show(args):
    """Put the last reading on its window as real controls.

    `read` (default true) takes a fresh reading first, which is nearly always
    what a caller wants: an overlay built from a reading taken some time ago
    is a set of controls that were true then. `hwnd` says which window, for a
    caller that knows - a screen reader does.
    """
    from src.titan_core import actions
    if args.get('read', True):
        result = actions.run('ocr', 'read_window',
                             hwnd=str(_whole(args.get('hwnd', 0))))
        if not result.ok:
            raise ValueError(result.text)
        # A refusal arrives as a success with prose in it, so the reading is
        # checked by SHAPE - `elements_as_lines` writes `[Region]` headings and
        # a refusal is one paragraph with none.
        if not any(line.lstrip().startswith('[')
                   for line in str(result.text or '').splitlines()):
            raise ValueError(str(result.text or '').strip() or
                             'the window could not be read')
    result = actions.run('ocr', 'show_overlay')
    if not result.ok:
        raise ValueError(result.text)
    state = _ocr_overlay({})
    if not state.get('open'):
        # Every reason ends here: nothing could be placed where it really is
        # (a reading with no rectangles), or the surface could not be adopted
        # by that window. The sentence Titan wrote is the one that says which.
        raise ValueError(str(result.text or '').strip() or
                         'the overlay could not be put on that window')
    state['said'] = str(result.text or '').strip()
    return state


def _ocr_overlay_refresh(_args):
    """Look at the window again; rebuild the controls only if it has changed.

    Costs nothing at a provider when the picture is the same, which is what
    makes this safe to call on a timer - and it is the overlay that reads,
    because only the overlay makes itself invisible while the picture is
    taken.
    """
    from src.titan_core import actions
    result = actions.run('ocr', 'refresh_overlay')
    if not result.ok:
        raise ValueError(result.text)
    state = _ocr_overlay({})
    state['said'] = str(result.text or '').strip()
    return state


def _ocr_overlay_close(_args):
    from src.titan_core import actions
    result = actions.run('ocr', 'close_overlay')
    if not result.ok:
        raise ValueError(result.text)
    return {'open': False, 'said': str(result.text or '').strip()}



#: **What a client may do without being allowed to.** Reading is one
#: permission and driving is another, and the line is the one this
#: repository already drew for the TCE bridge's own `press_key`: reading
#: tells somebody what is there, and Enter in a messenger sends the
#: message. Everything here only READS - what is installed, what a screen
#: holds, what a setting is, what the AI remembers - so a client that has
#: not been allowed to control Titan can still show it whole, which is
#: what a bridge is for.
#:
#: A call that is not on this list changes something and needs the user's
#: yes, asked once when the client arrives (`src/titan_core/
#: client_consent.py`). `app.open` is deliberately NOT here: it starts a
#: process. Neither is `speech.say`: it takes the user's own voice.
READ_ONLY = frozenset((
    'hello', 'capabilities',
    'apps.list', 'games.list', 'im.modules', 'views.list',
    'statusbar.read', 'menu.list', 'components.list',
    'widgets.list', 'widgets.read',
    'buffers.list', 'buffers.read',
    'notifications.list',
    'settings.screen',
    'speech.speaking',
    'ai.available', 'ai.history',
    'addons.list', 'addons.actions',
    'macros.list', 'cling.list',
    'window.state', 'titan.processes',
    'app.list', 'app.screen', 'app.sessions', 'app.log',
    'ocr.overlay',
    # Reading a window with the model on this machine sends nothing
    # anywhere and costs nothing, so it is served like any other reading.
    # Installing it is a download and deliberately is NOT here.
    'ocr.model', 'ocr.read_local',
))


#: **A client telling Titan about ITSELF is not a client driving Titan.**
#: These two are the whole of what the bridge in Elten does unprompted: a
#: message arrived over there, and here is what that client currently is.
#: They reach `show_notification`, so a message from Elten behaves exactly
#: like one of Titan's own or one of tReminder's - the sound, the reader,
#: the Titan category of the buffer system - which is the point of having
#: a bridge at all.
#:
#: Putting them behind the drive consent would mean the most useful thing
#: the bridge does stops until a dialog is answered, and it would be
#: answering the wrong question: what the user is asked about is another
#: program taking hold of Titan, and news about that program is not that.
#: It is a nuisance vector - a client can put text in the notification
#: centre and have it read out - which is why the client's ARRIVAL is
#: announced out loud, why the notification says which program it came
#: from, and why Elten's own end has its own switch for it.
SELF_REPORT = frozenset(('notifications.add', 'client.report'))


def drives(call):
    """Whether this call would CHANGE Titan rather than read it."""
    name = str(call or '')
    return name not in READ_ONLY and name not in SELF_REPORT


def _capabilities(_args):
    """Everything a client may ask for, so it need not find out by failing.

    **A doorway nobody can enumerate is a doorway a client guesses at**,
    and every guess this bridge has cost was of that shape - a call name
    that was nearly right, an argument spelled the way another add-on
    spells it. So the surface says what it is: which calls exist, which
    of them only read, and where the two permissions part.
    """
    from src.titan_core import client_consent
    return {
        'api': API_VERSION,
        'calls': sorted(CALLS),
        'read_only': sorted(READ_ONLY),
        'self_report': sorted(SELF_REPORT),
        'consent': {
            'needed_for': sorted(name for name in CALLS if drives(name)),
            'clients': client_consent.clients(),
        },
    }


CALLS = {
    'hello': _hello,
    'capabilities': _capabilities,
    'apps.list': _apps,
    'apps.open': _open_app,
    'games.list': _games,
    'games.open': _open_game,
    'im.modules': _im_modules,
    'im.open': _open_im_module,
    'views.list': _views,
    'statusbar.read': _status_bar,
    'menu.list': _menu,
    'menu.run': _menu_run,
    'components.list': _components,
    'widgets.list': _widgets,
    'widgets.read': _widget_read,
    'widgets.move': _widget_move,
    'widgets.press': _widget_press,
    'buffers.list': _buffers,
    'buffers.read': _buffer,
    'notifications.list': _notifications,
    'settings.screen': _settings_screen,
    'settings.set': _settings_set,
    'settings.press': _settings_press,
    'settings.save': _settings_save,
    'settings.cancel': _settings_cancel,
    'speech.say': _speak,
    'speech.stop': _stop_speech,
    'speech.speaking': _speaking,
    'speech.rate': _speech_rate,
    'ai.available': _ai_available,
    'ai.ask': _ai_ask,
    'ai.history': _ai_history,
    'ai.forget': _ai_forget,
    'sounds.play': _play_sound,
    'sounds.theme': _sound_theme,
    'addons.list': _addons,
    'addons.actions': _addon_actions,
    'addons.run': _addon_run,
    'macros.list': _macros,
    'cling.list': _cling,
    'window.state': _window_state,
    'titan.processes': _processes,
    'notifications.add': _notification_add,
    'notifications.clear': _notification_clear,
    'client.report': _client_report,
    'app.list': _app_ui_list,
    'app.open': _app_ui_open,
    'app.screen': _app_ui_screen,
    'app.press': _app_ui_press,
    'app.set': _app_ui_set,
    'app.key': _app_ui_key,
    'app.close': _app_ui_close,
    'app.sessions': _app_ui_sessions,
    'app.log': _app_ui_log,
    'ocr.model': _ocr_model_status,
    'ocr.install_model': _ocr_install_model,
    'ocr.read_local': _ocr_read_local,
    'ocr.overlay': _ocr_overlay,
    'ocr.overlay_show': _ocr_overlay_show,
    'ocr.overlay_refresh': _ocr_overlay_refresh,
    'ocr.overlay_close': _ocr_overlay_close,
}


def bridge(request='', **_):
    """The one action. `request` is JSON: {"call": "...", "args": {...}}."""
    try:
        payload = json.loads(request) if isinstance(request, str) else (request or {})
    except ValueError as error:
        return json.dumps({'ok': False, 'api': API_VERSION,
                           'error': f'the request is not JSON: {error}'})
    if not isinstance(payload, dict):
        return json.dumps({'ok': False, 'api': API_VERSION,
                           'error': 'the request must be an object'})
    name = str(payload.get('call') or '').strip()
    handler = CALLS.get(name)
    if handler is None:
        return json.dumps({'ok': False, 'api': API_VERSION,
                           'error': f'this Titan has no bridge call {name!r}',
                           'calls': sorted(CALLS)}, ensure_ascii=False)
    try:
        data = handler(payload.get('args') or {})
    except Exception as error:                     # noqa: BLE001 - relayed
        return json.dumps({'ok': False, 'api': API_VERSION,
                           'error': f'{type(error).__name__}: {error}'},
                          ensure_ascii=False)
    return json.dumps({'ok': True, 'api': API_VERSION, 'data': data},
                      ensure_ascii=False, default=str)


def get_bridge_actions():
    """(name, summary, params, risk, run) - one action for the whole surface."""
    return (
        ('bridge',
         "One typed doorway into Titan for a program that is not Titan: "
         "JSON in, JSON out. Send {\"call\": \"apps.list\"} and so on; "
         "{\"call\": \"hello\"} answers with the version this Titan speaks.",
         {'request': {'type': 'string', 'required': True,
                      'description': 'JSON: {"call": "...", "args": {...}}'}},
         'auto', bridge),
    )
