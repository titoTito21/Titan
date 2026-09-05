"""Titan's main window as data, so another program can BE that window.

The TCE bridge running inside Elten is not a list of functions dressed up as
a menu - it is Titan's own interface, rebuilt in Elten's controls. That only
stays true if it reads what Titan's window actually contains rather than
carrying a copy of it: Titan's tab bar is the views that are registered (the
three built-in ones, plus whatever a component registered), its status bar
is whatever the applets are saying at this moment, and its Program menu is
`src/ui/program_menu.py` - the module that already exists precisely so that
every face of Titan offers the same menu.

So there is deliberately no list of views, no list of status rows and no
menu in this file. There is only the reading of Titan's own.
"""

import json

from src.titan_core.actions.inproc import run_on_gui


def _frame():
    """Titan's main window, or None when Titan has no window up."""
    try:
        import wx
    except Exception:
        return None
    try:
        app = wx.GetApp()
        top = app.GetTopWindow() if app is not None else None
    except Exception:
        return None
    return top


def _views(**_):
    """The tab bar: the views Titan is showing, in the user's own order."""
    def read():
        frame = _frame()
        views = getattr(frame, 'registered_views', None) or []
        out = []
        for view in views:
            out.append({'id': str(view.get('id') or ''),
                        'label': str(view.get('label') or ''),
                        'short_name': str(view.get('short_name')
                                          or view.get('label') or '')})
        return out
    views, error = run_on_gui(read)
    if error:
        return f"Could not read Titan's views: {error}"
    if not views:
        return "Titan has no main window open."
    return json.dumps({'views': views}, ensure_ascii=False)


def _status_bar(**_):
    """The status bar, exactly as Titan's own window shows it - the clock,
    the battery, the volume, the network, and every statusbar applet."""
    def read():
        frame = _frame()
        reader = getattr(frame, '_statusbar_items', None)
        if reader is None:
            return None
        return [{'key': str(key), 'text': str(text)} for key, text in reader()]
    items, error = run_on_gui(read)
    if error:
        return f"Could not read the status bar: {error}"
    if items is None:
        return "Titan has no main window open."
    return json.dumps({'items': items}, ensure_ascii=False)


def _menu(**_):
    """Titan's Program menu, from the module every face of Titan builds it
    from - so a new entry appears here without this file being touched."""
    def read():
        from src.ui import program_menu
        frame = _frame()
        groups = []
        entries = program_menu.program_entries(frame) or []
        if entries:
            groups.append({'id': 'program', 'label': 'Program',
                           'entries': entries})
        for group in program_menu.extra_groups(frame) or []:
            groups.append(group)
        return [{'id': str(group.get('id') or ''),
                 'label': str(group.get('label') or ''),
                 'entries': [{'id': str(entry.get('id') or ''),
                              'label': str(entry.get('label') or '')}
                             for entry in (group.get('entries') or [])]}
                for group in groups]
    groups, error = run_on_gui(read)
    if error:
        return f"Could not read Titan's menu: {error}"
    return json.dumps({'groups': groups}, ensure_ascii=False)


def _menu_run(entry='', **_):
    """Press one entry of Titan's Program menu, by its id."""
    wanted = str(entry or '').strip()
    if not wanted:
        return "Say which menu entry to open."

    def press():
        from src.ui import program_menu
        frame = _frame()
        candidates = list(program_menu.program_entries(frame) or [])
        for group in program_menu.extra_groups(frame) or []:
            candidates.extend(group.get('entries') or [])
        for candidate in candidates:
            if str(candidate.get('id') or '') != wanted:
                continue
            action = candidate.get('action')
            if not callable(action):
                return (False, candidate.get('label') or wanted)
            action()
            return (True, candidate.get('label') or wanted)
        return None
    outcome, error = run_on_gui(press)
    if error:
        return f"Could not open it: {error}"
    if outcome is None:
        return f"Titan's menu has no entry called '{wanted}'."
    opened, label = outcome
    return f"Opened {label}." if opened else f"{label} could not be opened."


def get_main_window_actions():
    """(name, summary, params, risk, run) for each, as the shell's are."""
    string = {'type': 'string'}
    return (
        ('views', "Titan's tab bar as JSON - the views its main window is "
                  "showing, including any a component registered.", {},
         'auto', _views),
        ('status_bar', "Titan's status bar as JSON - the clock, battery, "
                       "volume, network and every statusbar applet.", {},
         'auto', _status_bar),
        ('menu', "Titan's Program menu as JSON: its groups and their "
                 "entries, from the module every face of Titan builds its "
                 "menu from.", {}, 'auto', _menu),
        ('menu_run', "Press one entry of Titan's Program menu.",
         {'entry': dict(string, description="The entry's id, from menu.",
                        required=True)},
         'confirm', _menu_run),
    )


# --------------------------------------------------------------------------- #
# The rest of Titan's own interface: the categories its non-visual face has
# that its tab bar does not - the widgets, the components' own menu, the
# buffers and the notifications. `src/ui/invisibleui.py` is the authority for
# what "everything a Titan user can reach without a screen" means, and these
# are read the same way it reads them.
# --------------------------------------------------------------------------- #
def _components(**_):
    """The components, and the entries they put in Titan's Components menu."""
    def read():
        from src.ai.titan_tools import _component_manager
        manager = _component_manager()
        if manager is None:
            return None
        components = []
        try:
            for entry in manager.get_components() or []:
                components.append({'name': entry.get('name') or '',
                                   'folder': entry.get('folder') or '',
                                   'enabled': bool(entry.get('enabled'))})
        except Exception:
            pass
        try:
            menu = list((manager.get_component_menu_functions() or {}).keys())
        except Exception:
            menu = []
        return {'components': components, 'menu_actions': menu}
    data, error = run_on_gui(read)
    if error:
        return f"Could not read the components: {error}"
    if data is None:
        return "The component manager is not available."
    return json.dumps(data, ensure_ascii=False)


def _widget_modules():
    """(name, module, info) for every widget Titan has.

    A widget ships one of two ways and both end at the same two functions:
    the older `init.py`, and `applet.json` + `main.py`. Reading only the
    first missed three of the five installed here - including the real ones,
    the quick settings, the system desktop and the taskbar.
    """
    import importlib.util
    import json as _json
    import os
    import sys

    try:
        from src.platform_utils import discover_data_entries
        entries = discover_data_entries('applets')
    except Exception:
        entries = {}
    found = []
    for name, folder in (entries or {}).items():
        module = None
        init = os.path.join(folder, 'init.py')
        main = os.path.join(folder, 'main.py')
        manifest = os.path.join(folder, 'applet.json')
        try:
            if os.path.isfile(init):
                spec = importlib.util.spec_from_file_location(name, init)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            elif os.path.isfile(manifest) and os.path.isfile(main):
                spec = importlib.util.spec_from_file_location(
                    f"applets.{name}.main", main)
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
            else:
                continue
            info = module.get_widget_info()
        except Exception as error:
            found.append((name, None, {'name': name, 'type': '',
                                       'error': f"{type(error).__name__}: {error}"}))
            continue
        found.append((name, module, info or {}))
    return found


def _widgets(**_):
    """The widgets, as Titan's own non-visual interface lists them."""
    def read():
        out = []
        for name, _module, info in _widget_modules():
            entry = {'id': name, 'name': str(info.get('name') or name),
                     'type': str(info.get('type') or '')}
            if info.get('error'):
                entry['error'] = info['error']
            out.append(entry)
        return out
    widgets, error = run_on_gui(read)
    if error:
        return f"Could not read the widgets: {error}"
    return json.dumps({'widgets': widgets}, ensure_ascii=False)


# A widget is a live thing with a cursor in it, so the instance is kept
# between calls - reading it, moving in it and pressing it are three calls
# about the SAME widget, and a fresh instance each time would start over.
_widget_instances = {}


def _widget_instance(wanted):
    """(instance, said, label) for a widget, made if it is not already made.

    Whatever the widget SAYS is captured rather than spoken: it is being
    used from another program, and its words belong to that program's voice.
    """
    said = []

    def capture(text, interrupt=True, position=0.0, pitch_offset=0,
                elevation=0.0, *_more, **_options):
        """What the widget says, kept instead of spoken.

        **It has to take everything a widget passes.** A widget is a thing
        with a cursor in it and it places what it says - `self.speak(text,
        position=position, pitch_offset=pitch_offset)` is the quick
        settings' own line, and the grid widgets do the same - because
        Titan's non-visual interface hands them `InvisibleUI.speak`, whose
        signature that is. A one-argument stand-in therefore raised
        `TypeError: got an unexpected keyword argument 'position'` the
        moment the cursor moved in a grid, which reached the user as
        "Could not activate it" on every widget but the two flat ones.
        The extras are accepted and dropped: this is being read to somebody
        in another program, in that program's own voice.
        """
        said.append(str(text))

    for name, module, info in _widget_modules():
        label = str(info.get('name') or name)
        if label.lower() != wanted and name.lower() != wanted:
            continue
        if module is None:
            return None, said, label
        instance = _widget_instances.get(name)
        if instance is None:
            instance = module.get_widget_instance(capture)
            _widget_instances[name] = instance
        else:
            # The instance keeps the speak function it was made with, so the
            # list it appends to is swapped rather than the instance rebuilt.
            try:
                instance.speak = capture
            except Exception:
                pass
        return instance, said, label
    return None, said, ''


def _activate_widget(widget='', **_):
    """Press a widget, the way Titan's non-visual interface presses it."""
    wanted = str(widget or '').strip().lower()
    if not wanted:
        return "Say which widget."

    def press():
        instance, said, label = _widget_instance(wanted)
        if not label:
            return None
        if instance is None:
            return (False, label, said)
        instance.activate_current_element()
        return (True, label, said)
    outcome, error = run_on_gui(press)
    if error:
        return f"Could not activate it: {error}"
    if outcome is None:
        return f"Titan has no widget called '{widget}'."
    pressed, label, said = outcome
    if not pressed:
        return f"{label} could not be loaded."
    spoken = " ".join(said).strip()
    return spoken or f"Pressed {label}."


def _widget_read(widget='', **_):
    """What the widget's cursor is on now."""
    wanted = str(widget or '').strip().lower()
    if not wanted:
        return "Say which widget."

    def read():
        instance, said, label = _widget_instance(wanted)
        if not label:
            return None
        if instance is None:
            return (False, label, '')
        current = ''
        try:
            current = str(instance.get_current_element() or '')
        except Exception as error:
            current = f"{type(error).__name__}: {error}"
        if not current and said:
            current = " ".join(said).strip()
        return (True, label, current)
    outcome, error = run_on_gui(read)
    if error:
        return f"Could not read it: {error}"
    if outcome is None:
        return f"Titan has no widget called '{widget}'."
    ok, label, current = outcome
    if not ok:
        return f"{label} could not be loaded."
    return current or label


def _widget_move(widget='', direction='next', **_):
    """Move inside a widget - a grid widget navigates, a button widget has
    only the one element and says so."""
    wanted = str(widget or '').strip().lower()
    if not wanted:
        return "Say which widget."
    where = str(direction or 'next').strip().lower()

    def move():
        instance, said, label = _widget_instance(wanted)
        if not label:
            return None
        if instance is None:
            return (False, label, '')
        mover = getattr(instance, 'navigate', None)
        if not callable(mover):
            return (True, label, '')
        try:
            mover(where)
        except Exception as error:
            return (True, label, f"{type(error).__name__}: {error}")
        current = ''
        try:
            current = str(instance.get_current_element() or '')
        except Exception:
            current = ''
        if not current and said:
            current = " ".join(said).strip()
        return (True, label, current)
    outcome, error = run_on_gui(move)
    if error:
        return f"Could not move: {error}"
    if outcome is None:
        return f"Titan has no widget called '{widget}'."
    ok, label, current = outcome
    if not ok:
        return f"{label} could not be loaded."
    return current or label


def _buffers(**_):
    """The Buffer System: the categories and the buffers inside them.

    This is one of the things a Titan user reaches for constantly and that
    nothing else exposes - every message, notification and call that arrived
    while a window was closed is in here.
    """
    def read():
        from src.buffers.buffer_system import get_buffer_manager
        manager = get_buffer_manager()
        categories = []
        for category in list(manager.categories.values()):
            categories.append({
                'id': category.id,
                'name': category.name,
                'live': category.handler is not None,
                'buffers': [{'id': buffer.id, 'name': buffer.name,
                             'kind': buffer.kind or '',
                             'count': len(buffer.elements)}
                            for buffer in category.buffers.values()],
            })
        return categories
    categories, error = run_on_gui(read)
    if error:
        return f"Could not read the buffers: {error}"
    return json.dumps({'categories': categories}, ensure_ascii=False)


def _buffer(category='', buffer='', limit=100, **_):
    """What is in one buffer, newest last."""
    want_category = str(category or '').strip()
    want_buffer = str(buffer or '').strip()
    if not want_category:
        return "Say which category."

    def read():
        from src.buffers.buffer_system import get_buffer_manager
        manager = get_buffer_manager()
        found = None
        for entry in manager.categories.values():
            if entry.id == want_category or entry.name == want_category:
                found = entry
                break
        if found is None:
            return None
        buffers = list(found.buffers.values())
        if want_buffer:
            buffers = [b for b in buffers
                       if b.id == want_buffer or b.name == want_buffer]
        elements = []
        for entry in buffers:
            for element in list(entry.elements)[-int(limit or 100):]:
                elements.append({'buffer': entry.name, 'text': element.text,
                                 'author': element.author or '',
                                 'kind': element.kind or '',
                                 'timestamp': element.timestamp})
        return elements
    elements, error = run_on_gui(read)
    if error:
        return f"Could not read the buffer: {error}"
    if elements is None:
        return f"There is no buffer category called '{category}'."
    return json.dumps({'elements': elements}, ensure_ascii=False)


def _notifications(**_):
    """Titan's notification centre, as records."""
    def read():
        from src.ui.notificationcenter import read_notifications
        return read_notifications()
    items, error = run_on_gui(read)
    if error:
        return f"Could not read the notifications: {error}"
    return json.dumps({'notifications': items}, ensure_ascii=False, default=str)


def _clear_notifications(**_):
    """Empty Titan's notification centre."""
    def clear():
        from src.ui.notificationcenter import clear_notifications
        clear_notifications()
        return True
    ok, error = run_on_gui(clear)
    if error:
        return f"Could not clear them: {error}"
    return "Cleared the notifications." if ok else "Nothing to clear."


def _open_help(**_):
    """Open Titan's help, as its Program menu does."""
    def show():
        from src.ui.help import show_help
        frame = _frame()
        show_help(frame)
        return True
    ok, error = run_on_gui(show)
    if error:
        return f"Could not open the help: {error}"
    return "Opened Titan's help." if ok else "The help could not be opened."


def _window(action='', **_):
    """Minimise Titan, or bring it back - the Program menu's own entries."""
    wanted = str(action or '').strip().lower()
    if wanted not in ('minimize', 'minimise', 'restore', 'show'):
        return "Say minimize or restore."

    def move():
        frame = _frame()
        if frame is None:
            return None
        if wanted in ('minimize', 'minimise'):
            if hasattr(frame, 'minimize_to_tray'):
                frame.minimize_to_tray()
            else:
                frame.Iconize(True)
            return 'minimised'
        if hasattr(frame, 'restore_from_tray'):
            frame.restore_from_tray()
        else:
            frame.Iconize(False)
            frame.Raise()
        return 'restored'
    outcome, error = run_on_gui(move)
    if error:
        return f"Could not move the window: {error}"
    if outcome is None:
        return "Titan has no main window."
    return f"Titan was {outcome}."


def get_titan_face_actions():
    """(name, summary, params, risk, run) for each, as the shell's are."""
    string = {'type': 'string'}
    number = {'type': 'number'}
    return (
        ('components',
         "The components and the entries they add to Titan's Components "
         "menu, as JSON. Run one with run_component_action.", {},
         'auto', _components),
        ('widgets', "The widgets Titan has, as JSON.", {}, 'auto', _widgets),
        ('activate_widget', "Press what a widget's cursor is on, and answer "
                            "with whatever the widget said.",
         {'widget': dict(string, description="The widget's name.",
                         required=True)},
         'confirm', _activate_widget),
        ('widget_read', "What a widget's cursor is on now.",
         {'widget': dict(string, description="The widget's name.",
                         required=True)},
         'auto', _widget_read),
        ('widget_move', "Move a widget's cursor: up, down, left, right, "
                        "next or previous.",
         {'widget': dict(string, description="The widget's name.",
                         required=True),
          'direction': dict(string, description="up, down, left, right, "
                            "next or previous.")},
         'auto', _widget_move),
        ('buffers',
         "The Buffer System as JSON: every category and the buffers in it - "
         "the messages, notifications and calls that arrived while their "
         "window was closed.", {}, 'auto', _buffers),
        ('buffer', "What is in one buffer, as JSON.",
         {'category': dict(string, description="The category's id or name.",
                           required=True),
          'buffer': dict(string, description="One buffer only (default all)."),
          'limit': dict(number, description="How many (default 100).")},
         'auto', _buffer),
        ('notifications', "Titan's notification centre, as JSON.", {},
         'auto', _notifications),
        ('clear_notifications', "Empty the notification centre.", {},
         'confirm', _clear_notifications),
        ('open_help', "Open Titan's help window.", {}, 'confirm', _open_help),
        ('window', "Minimise Titan to the tray, or bring it back.",
         {'action': dict(string, description="minimize or restore.",
                         required=True)},
         'confirm', _window),
    )
