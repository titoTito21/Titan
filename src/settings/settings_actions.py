"""Titan's settings window, as actions - so another program can be one.

`data/settings interfaces/` already answers "I would rather have the settings
in a window of my own", and `ui_model.py` is what makes that possible: it
reads the description out of Titan's OWN settings window, so a setting added
to `settingsgui.py` appears in every interface with nobody editing a second
table. Everything there, though, is in Titan's process - an interface is a
Python module Titan imports.

The TCE bridge running inside Elten is not. It is somebody else's program,
on the other end of a named pipe, and the only thing that crosses is JSON.
So the model is offered as actions: `screen` hands over the categories and
their controls as data, `set_value` sets one, and `save` is Titan's own save
with everything that hangs off it - the SAPI registration, the system
monitor, the shell hooks, the menu bar. An interface that wrote the ini file
itself would set the value and change nothing.

They are written here rather than adapted from a tool table because this is
not an AI subsystem: a program asking "what settings are there" should not
have to go near a model, and a JSON document of a hundred and fifty settings
is not something to hand a language model on every turn.
"""

import json

from src.titan_core.actions.inproc import run_on_gui

_model = None


def _build():
    """The live model, on the GUI thread. The window is Titan's own."""
    from src.settings.interfaces import settings_frame, ensure_component_categories
    from src.settings.ui_model import SettingsModel
    window = settings_frame()
    if window is None:
        return None
    # A Titan started into Klango mode or a launcher may have a settings
    # window the components have never registered into; an interface must
    # show exactly what the classic window shows. Asked for ONCE, and only
    # when they are missing: registering them again builds a second panel
    # per component, and a second panel is one that is drawn over every
    # category. Reading the settings must not change the window it reads.
    try:
        registered = getattr(window, 'categories', None)
        known = set(registered.keys()) if isinstance(registered, dict) else set()
        manager = getattr(window, 'component_manager', None)
        expected = set()
        if manager is not None:
            try:
                expected = {str(entry.get('name') or '')
                            for entry in (manager.get_components() or [])}
            except Exception:
                expected = set()
        if manager is None or not (expected and expected <= known):
            ensure_component_categories(window)
    except Exception:
        pass
    return SettingsModel(window)


def _get_model(fresh=False):
    """The model, kept between calls - `set` then `save` must be one model."""
    global _model
    if fresh or _model is None:
        model, error = run_on_gui(_build)
        if error:
            return None, error
        _model = model
    if _model is None:
        return None, "Titan has no settings window to read."
    return _model, None


def _screen(category='', **_):
    """Every category and every setting in it, as JSON."""
    model, error = _get_model()
    if error:
        return error
    wanted = (category or '').strip().lower()

    def read():
        categories = model.categories()
        if wanted:
            categories = [c for c in categories
                          if (c.get('name') or '').lower() == wanted]
        return categories

    categories, error = run_on_gui(read)
    if error:
        return f"Could not read the settings: {error}"
    return json.dumps({'categories': categories}, ensure_ascii=False)


def _set_value(item='', value='', **_):
    """Set one setting, the way pressing it in Titan's own window would."""
    identifier = str(item or '').strip()
    if not identifier:
        return "Say which setting to set."
    model, error = _get_model()
    if error:
        return error

    def write():
        entry = model.item(identifier)
        if entry is None:
            return None
        wanted = value
        # A tick list holds SEVERAL values, and an action argument is one
        # string, so it arrives as a JSON array. Anything else is passed
        # through untouched: a setting whose value happens to start with a
        # bracket is not a list.
        if entry.kind == 'multi':
            import json as _json
            text = str(value or '').strip()
            try:
                parsed = _json.loads(text) if text.startswith('[') else None
            except ValueError:
                parsed = None
            wanted = parsed if isinstance(parsed, list) else (
                [part.strip() for part in text.split('|') if part.strip()])
        # The control's own event is what applies a setting live, and
        # `SettingsItem.set` fires it. Writing the ini instead would set the
        # value and change nothing until Titan was restarted.
        ok = model.set(identifier, wanted)
        return (ok, entry.label, entry.value())

    outcome, error = run_on_gui(write)
    if error:
        return f"Could not set it: {error}"
    if outcome is None:
        return f"There is no setting called {identifier}."
    ok, label, now = outcome
    if not ok:
        return f"{label} would not take that value."
    return f"{label} is now {now}. Nothing is written until you save."


def _press(item='', **_):
    """Press a settings control that does something rather than holding a
    value - a Browse button, a Test button, a Forget button."""
    identifier = str(item or '').strip()
    if not identifier:
        return "Say which control to press."
    model, error = _get_model()
    if error:
        return error
    ok, error = run_on_gui(lambda: model.press(identifier))
    if error:
        return f"Could not press it: {error}"
    return "Pressed it." if ok else f"There is no control called {identifier}."


def _save(**_):
    """Titan's own save - the SAPI registration, the system monitor, the
    shell, the menu bar, everything that hangs off `OnSave`."""
    model, error = _get_model()
    if error:
        return error
    ok, error = run_on_gui(model.save)
    if error:
        return f"Could not save: {error}"
    # The window is rebuilt by the save, so the next read must be a fresh one.
    globals()['_model'] = None
    return "Saved." if ok else "Titan could not save the settings."


def _cancel(**_):
    """Put back what was there, exactly as the settings window's Cancel."""
    model, error = _get_model()
    if error:
        return error
    ok, error = run_on_gui(model.cancel)
    globals()['_model'] = None
    if error:
        return f"Could not cancel: {error}"
    return "Put the settings back." if ok else "Nothing to put back."


def _refresh(**_):
    """Read the window again - after a component registered a category."""
    model, error = _get_model(fresh=True)
    if error:
        return error
    count, error = run_on_gui(lambda: len(model.items()))
    if error:
        return f"Could not read the settings: {error}"
    return f"Read {count} settings."


def _find(text='', **_):
    """The settings whose label or category matches what somebody typed."""
    model, error = _get_model()
    if error:
        return error
    found, error = run_on_gui(
        lambda: [item.describe() for item in model.find(text)])
    if error:
        return f"Could not search the settings: {error}"
    return json.dumps({'items': found}, ensure_ascii=False)


def get_settings_ui_actions():
    """(name, summary, params, risk, run) for each, as the shell's are."""
    string = {'type': 'string'}
    return (
        ('screen',
         "Every settings category and the controls in it, as JSON: id, "
         "label, kind (bool, choice, number, text, secret, command, list, "
         "multi, info), value, options and whether it is enabled. This is "
         "what Titan's own settings window shows, read out of that window.",
         {'category': dict(string, description="Only this category "
                           "(default: all of them).")},
         'auto', _screen),
        ('set_value',
         "Set one setting to a value, firing the control's own event so it "
         "applies live. Nothing reaches the disk until you save.",
         {'item': dict(string, description="The setting's id, from screen.",
                       required=True),
          'value': dict(string, description="The value to set.",
                        required=True)},
         'auto', _set_value),
        ('press',
         "Press a settings control that does something instead of holding a "
         "value - Browse, Test, Forget.",
         {'item': dict(string, description="The control's id, from screen.",
                       required=True)},
         'confirm', _press),
        ('save', "Save the settings, with everything Titan does on a save.",
         {}, 'confirm', _save),
        ('cancel', "Put the settings back the way they were.", {},
         'confirm', _cancel),
        ('refresh', "Read Titan's settings window again.", {}, 'auto',
         _refresh),
        ('find', "The settings whose label or category matches some words.",
         {'text': dict(string, description="What to look for.",
                       required=True)},
         'auto', _find),
    )
