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
API_VERSION = 1


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
    def read():
        from src.titan_core import translation
        language = getattr(translation, 'current_language', '') or ''
        frame = _frame()
        return {
            'api': API_VERSION,
            'language': str(language),
            'has_window': frame is not None,
            'at': time.time(),
        }
    data, error = run_on_gui(read)
    if error:
        return {'api': API_VERSION, 'language': '', 'has_window': False}
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
    """Open one by its own name - the name the list gave, not a guess."""
    wanted = str(args.get('name') or '').strip().lower()
    if not wanted:
        raise ValueError('name is required')

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

    def play():
        from src.titan_core import sound
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


CALLS = {
    'hello': _hello,
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
