# -*- coding: utf-8 -*-
"""Elten API applications, running inside Titan.

Copyright (C) 2026 titosoft.

This component is free software: you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any
later version. See `LICENSE` beside this file. The rest of Titan is not
covered by that licence; this component is, because it is built against
Elten's own GPL-3.0 platform and shares its terms deliberately.

--------------------------------------------------------------------------

EltenLink is a social network for blind people with a desktop client of its
own, and applications are written FOR that client - games, a file manager, a
media catalogue, a podcast player - each shipped as one signed `.eltenapp`.
They are Ruby, and they expect a platform underneath them that speaks, plays
sounds, draws lists and forms, keeps their files and translates their
strings.

This is that platform, inside Titan:

* **The applications are found where Elten put them.** The user installs
  through Elten - its repository, its updates, its account - and runs here.
  `%APPDATA%/elten/apps/src/*.eltenapp` is read exactly as Elten leaves it,
  and an application installed five minutes ago is in the list when the
  window is next opened. Nothing is imported and nothing is copied.
* **Their saved games are the same files.** `data_path` is Elten's own
  `apps/data/<app>/`, so somebody who plays in Elten and then opens the same
  application here finds their game where they left it.
* **The interface is Titan's.** An application's `ListBox`, `EditBox`,
  `Button`, `CheckBox` and `Form` are real wx widgets in a real Titan
  window, which a screen reader already knows how to read - not a
  re-creation of Elten's own self-voicing loop.
* **The voice is Titan's**, at the user's rate, in their engine, positioned
  where the application asked - and through their screen reader when they
  have one, because that is where the rest of this desktop's speech goes.
* **The sound is Titan's mixer**, with their theme volume and their stereo
  or HRTF preference.
* **The Ruby is carried.** `ruby/` is CRuby 4.0.6, so the bridge works on a
  machine that has never had Ruby and never had Elten.
"""

import configparser
import gettext
import os
import sys

COMPONENT_DIR = os.path.dirname(os.path.abspath(__file__))
if COMPONENT_DIR not in sys.path:
    sys.path.insert(0, COMPONENT_DIR)

# The package is `eltenkit`, not `elten_bridge`: the component manager
# registers this module as `sys.modules['<folder name>']` BEFORE it runs it,
# so a package sharing the folder's name is shadowed by a half-built module
# and every import out of it fails. Cling learned this the same way.
from eltenkit import catalogue, host, launcher, package, runtime  # noqa: E402

#: What the list is called, everywhere a person can see it.
TITLE = 'Aplikacje Elten API'

_wx_module = None
_gui_app = None
_listbox = None
_running = []
# Applications started for their widgets and background ticks rather than
# opened - see `_start_widget_apps`.
_background = []


def _wx():
    global _wx_module
    if _wx_module is None:
        import wx
        _wx_module = wx
    return _wx_module


def _parent_window():
    """The window an application's own window belongs to.

    `TitanApp` IS a `wx.Frame` - it does not HAVE one - and asking it for
    `.frame` raised `'TitanApp' object has no attribute 'frame'` inside the
    view's activate handler, where the GUI caught it and nothing opened. A
    parent that cannot be found is None, which is a top-level window: worse
    than being owned by Titan, but not a failure to open.
    """
    if _gui_app is None:
        return None
    wx = _wx()
    if isinstance(_gui_app, wx.Window):
        return _gui_app
    for name in ('frame', 'main_frame', 'window'):
        candidate = getattr(_gui_app, name, None)
        if isinstance(candidate, wx.Window):
            return candidate
    return None


# ---------------------------------------------------------------------------
# Translations
# ---------------------------------------------------------------------------
LANGUAGES_DIR = os.path.join(COMPONENT_DIR, 'languages')


def _setup_translations():
    try:
        from src.titan_core.translation import language_code
        language = language_code
    except Exception:
        language = 'pl'
    try:
        return gettext.translation('elten_bridge', LANGUAGES_DIR,
                                   languages=[language], fallback=True).gettext
    except Exception:
        return lambda text: text


_ = _setup_translations()


def language():
    try:
        from src.titan_core.translation import language_code
        return language_code or 'en'
    except Exception:
        return 'en'


# ---------------------------------------------------------------------------
# What is installed
# ---------------------------------------------------------------------------
def applications(openable_only=True):
    """The applications to offer, the user's own winning.

    Only the ones a person can actually OPEN by default - Elten's own rule,
    out of the manifest's `menu` block. `ffmpeg` and `mcp` are plug-ins that
    register encoders and servers for other applications to use; offering
    them would be offering a row that opens and closes again.
    """
    try:
        return catalogue.discover(language(), openable_only=openable_only)
    except Exception as error:
        print('[elten] the applications could not be listed: %s' % error)
        return []


def status():
    """One sentence about whether this can run anything at all."""
    reason = runtime.unavailable_reason()
    if reason:
        return reason
    root = catalogue.elten_root()
    if not root:
        return _('Elten is not installed, so there are no applications to '
                 'run yet. Install Elten and its applications appear here.')
    found = applications()
    return _('%(count)d Elten applications, on Ruby %(ruby)s.') % {
        'count': len(found), 'ruby': runtime.find().pretty_version}


# ---------------------------------------------------------------------------
# Running one
# ---------------------------------------------------------------------------
def run_application(entry, parent=None):
    """Open an application in a window of its own. Never raises."""
    from eltenkit import ui as ui_module
    wx = _wx()
    try:
        gui = ui_module.WxUI(parent, entry.name or entry.stem)
    except Exception as error:
        wx.MessageBox(_('The application window could not be built: %s')
                      % error, TITLE, wx.OK | wx.ICON_ERROR)
        return None
    application = launcher.run(entry, ui=gui, language=language())
    if application.status == 'failed':
        try:
            gui.close()
        except Exception:
            pass
        wx.MessageBox(application.detail or
                      _('The application could not be started.'),
                      entry.name or TITLE, wx.OK | wx.ICON_ERROR)
        return application
    _running.append((entry, application, gui))
    application.on_widgets = _on_widgets_changed
    _watch(application, gui)
    _on_widgets_changed(application)
    return application


def _watch(application, gui):
    """Take the window away when the application ends, whichever way it did.

    An application that finished, failed or was closed under Titan must not
    leave its window behind: an empty frame that answers nothing is worse
    than no frame, and for somebody navigating by keyboard it is a place the
    focus can go and not come back from.
    """
    import threading
    wx = _wx()

    def wait():
        application.ended.wait()
        wx.CallAfter(_finish, application, gui)

    threading.Thread(target=wait, name='elten-watch', daemon=True).start()


def _finish(application, gui):
    _remember_log(application)
    try:
        application.stop()
    except Exception:
        pass
    try:
        gui.close()
    except Exception:
        pass
    for held in list(_running):
        if held[1] is application:
            _running.remove(held)


#: The log of the application that ran most recently, kept after it has
#: gone. An application that stopped, or that quietly did nothing, has
#: already said why - `boot.rb` records the exception and its message, and
#: every `puts` an application makes lands here too - but until now that
#: went with the window, so the one moment it could be read was the moment
#: nobody was looking. `(name, [(level, line), ...])`.
_last_log = ('', [])


def _remember_log(application):
    global _last_log
    try:
        entry = getattr(application, 'entry', None)
        name = (getattr(entry, 'name', '') or getattr(entry, 'stem', '')
                or _last_log[0])
        lines = list(getattr(application, 'log', []) or [])
    except Exception:
        return
    if lines:
        _last_log = (name, lines)


def stop_all():
    """Close every running application - Titan is going."""
    for _entry, application, gui in list(_running):
        _finish(application, gui)
    for _entry, application, gui in list(_background):
        try:
            application.stop()
        except Exception:
            pass
        try:
            gui.close()
        except Exception:
            pass
    del _background[:]
    try:
        from src.buffers import defaults as buffer_defaults
        buffer_defaults.remove_elten_api()
    except Exception:
        pass


# ------------------------------------------------------------------ widgets
# An Elten extension's `main_tab` is a section of Elten's main screen -
# the Weather application's forecast is one. Here each is a WIDGET in
# Titan's main window, in a view of its own placed just before the status
# bar: one header row per widget (its label and the application's name),
# then the widget's own rows, and Enter on a row is `select` on the very
# control the application built, so its own handler runs. The rows arrive
# from the application (`widgets` on the wire) whenever they change.

def _widget_sources():
    """Every running application, foreground or background."""
    return [held for held in list(_running) + list(_background)]


def _on_widgets_changed(_application=None):
    wx = _wx()
    try:
        wx.CallAfter(_fill_widgets)
    except Exception:
        pass


# One PANEL per widget - a list of its own in the main window's column,
# between the current view and the status bar, reached with Tab exactly as
# the status bar is: Elten's main screen is a column of sections, the
# Weather forecast one of them, and so is this. Not a card of the tab bar
# (that was the first shape, and the user said no): a section is always
# there, whatever view is showing. Added the moment an application's rows
# arrive, taken away when the widget goes (the application ended, or it
# withdrew the tab). `_widget_panels` is what is up: `(application key,
# tab key)` -> the panel's id and its list.
_widget_panels = {}


def _widget_panel_id(entry, tab):
    return 'elten_widget:%s:%s' % (entry.key, tab.get('key') or '')


def _fill_widgets():
    if _gui_app is None or not hasattr(_gui_app, 'add_side_panel'):
        return
    wx = _wx()
    wanted = {}
    for entry, application, _gui in _widget_sources():
        for tab in list(getattr(application, 'widgets', []) or []):
            wanted[(entry.key, str(tab.get('key') or ''))] = (entry, application, tab)
    # Widgets that have gone.
    for key in [key for key in _widget_panels if key not in wanted]:
        held = _widget_panels.pop(key)
        try:
            _gui_app.remove_side_panel(held['panel_id'])
        except Exception as error:
            print('[elten] widget panel: %s' % error)
    # Widgets that are here: a new panel for a new one, the rows for all.
    for key, (entry, application, tab) in wanted.items():
        label = str(tab.get('label') or tab.get('key') or entry.name or entry.stem)
        held = _widget_panels.get(key)
        if held is None:
            panel_id = _widget_panel_id(entry, tab)
            listbox = wx.ListBox(_gui_app.main_panel)
            held = {'panel_id': panel_id, 'listbox': listbox, 'label': label}
            try:
                _gui_app.add_side_panel(
                    panel_id, label, listbox,
                    on_activate=lambda _event=None, box=listbox: _on_widget_activate(box))
            except Exception as error:
                print('[elten] widget panel %s: %s' % (label, error))
                try:
                    listbox.Destroy()
                except Exception:
                    pass
                continue
            _widget_panels[key] = held
        elif held['label'] != label:
            held['label'] = label
            _gui_app.add_side_panel(held['panel_id'], label, held['listbox'],
                                    on_activate=lambda _event=None, box=held['listbox']: _on_widget_activate(box))
        _fill_widget_list(held, application, tab)


def _fill_widget_list(held, application, tab):
    """The widget's rows into its list, the cursor kept where it was."""
    listbox = held['listbox']
    try:
        selected = listbox.GetSelection()
        listbox.Clear()
        rows = list(tab.get('rows') or [])
        for index, text in enumerate(rows):
            listbox.Append(str(text))
            listbox.SetClientData(index, (application, str(tab.get('key') or ''), index))
        if not rows:
            listbox.Append(_('Nothing yet.'))
            listbox.SetClientData(0, None)
        count = listbox.GetCount()
        listbox.SetSelection(selected if 0 <= selected < count else 0)
    except RuntimeError:
        return


def _on_widget_activate(listbox):
    """Enter on a widget's row: `select` on the very control the
    application built, so its own handler runs."""
    wx = _wx()
    try:
        selection = listbox.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        target = listbox.GetClientData(selection)
    except (RuntimeError, TypeError):
        return
    if not target:
        return
    application, key, index = target
    try:
        application.send_event('widget', key=key, index=int(index), name='select')
    except Exception as error:
        print('[elten] widget: %s' % error)


def _start_widget_apps():
    """Start the applications the user named for their widgets, in the
    background: `activate` runs and their extensions tick, but nothing
    opens. Each gets a window of its own anyway, because a widget row
    pressed may open one of the application's screens."""
    from eltenkit import settings as bridge_settings
    from eltenkit import ui as ui_module
    wanted = set(bridge_settings.widget_apps())
    if not wanted:
        return
    already = {held[0].key for held in _widget_sources()}
    for entry in applications():
        if entry.key not in wanted or entry.key in already or entry.problem:
            continue
        try:
            gui = ui_module.WxUI(_parent_window(), entry.name or entry.stem)
        except Exception as error:
            print('[elten] widget window for %s: %s' % (entry.name, error))
            continue
        application = launcher.run(entry, ui=gui, language=language(), background=True)
        if application.status == 'failed':
            print('[elten] %s would not start in the background: %s'
                  % (entry.name, application.detail))
            try:
                gui.close()
            except Exception:
                pass
            continue
        application.on_widgets = _on_widgets_changed
        _background.append((entry, application, gui))
        _watch_background(application)


def _watch_background(application):
    import threading
    wx = _wx()

    def wait():
        application.ended.wait()
        for held in list(_background):
            if held[1] is application:
                _background.remove(held)
                try:
                    held[2].close()
                except Exception:
                    pass
        _remember_log(application)
        try:
            wx.CallAfter(_fill_widgets)
        except Exception:
            pass

    threading.Thread(target=wait, name='elten-widget-watch', daemon=True).start()


# ---------------------------------------------------------------------------
# Titan component hooks
# ---------------------------------------------------------------------------
def add_menu(component_manager):
    component_manager.register_menu_function(_(TITLE), _on_menu_action)
    _register_settings(component_manager)


def _register_settings(component_manager):
    """A settings category for the bridge - one switch so far, whether it
    uses Titan's own sounds (see `eltenkit/settings.py`)."""
    if not hasattr(component_manager, 'register_settings_category'):
        return
    wx = _wx()
    if wx is None:
        return
    from eltenkit import settings as bridge_settings

    def build_panel(parent):
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)
        panel.tce_sounds = wx.CheckBox(
            panel, label=_("Use TCE (Titan) sounds in the bridge"))
        panel.tce_sounds.SetToolTip(_(
            "Play Titan's own interface sounds for Elten applications, and "
            "fall back to a Titan sound when an application asks for one it "
            "did not ship. Turn this off to hear each application exactly as "
            "its author shipped it."))
        sizer.Add(panel.tce_sounds, 0, wx.ALL, 8)
        # Which applications run in the background for their widgets - a
        # tick list a screen reader reads as tick boxes (`src/ui/check_list`).
        label = wx.StaticText(panel, label=_(
            "Applications started in the background for their widgets "
            "(the Weather forecast, for one):"))
        sizer.Add(label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        try:
            from src.ui.check_list import CheckList
            panel.widget_apps = CheckList(panel, name=_("Widget applications"))
        except Exception:
            panel.widget_apps = wx.CheckListBox(panel)
        panel.widget_entries = []
        sizer.Add(panel.widget_apps, 1, wx.ALL | wx.EXPAND, 8)
        panel.SetSizer(sizer)
        return panel

    def load_panel(panel):
        panel.tce_sounds.SetValue(bridge_settings.use_titan_sounds())
        panel.widget_entries = [entry for entry in applications() if not entry.problem]
        chosen = set(bridge_settings.widget_apps())
        try:
            panel.widget_apps.Set([entry.name or entry.stem for entry in panel.widget_entries])
            for index, entry in enumerate(panel.widget_entries):
                panel.widget_apps.Check(index, entry.key in chosen)
        except Exception as error:
            print(f"[elten bridge] widget list: {error}")

    def save_panel(panel):
        bridge_settings.set_use_titan_sounds(panel.tce_sounds.GetValue())
        keys = []
        for index, entry in enumerate(panel.widget_entries):
            try:
                if panel.widget_apps.IsChecked(index):
                    keys.append(entry.key)
            except Exception:
                pass
        bridge_settings.set_widget_apps(keys)
        try:
            wx.CallAfter(_start_widget_apps)
        except Exception:
            pass

    try:
        component_manager.register_settings_category(
            _(TITLE), build_panel, save_panel, load_panel)
    except Exception as error:
        print(f"[elten bridge] settings category failed: {error}")


def _on_menu_action(_event=None):
    open_browser()


def get_gui_hooks():
    return {'on_gui_init': _on_gui_init}


def _on_gui_init(gui_app):
    """An Elten view in the main window, beside applications and games -
    and the widgets view, just before the status bar."""
    global _gui_app, _listbox
    wx = _wx()
    _gui_app = gui_app
    _listbox = wx.ListBox(gui_app.main_panel)
    _fill_listbox()
    gui_app.component_manager.register_view(
        view_id='elten_apps', label=_(TITLE) + ':', control=_listbox,
        on_show=_fill_listbox, on_activate=_on_view_activate,
        position='after_network')
    try:
        from src.buffers import defaults as buffer_defaults
        buffer_defaults.register_elten_api()
    except Exception as error:
        print('[elten] buffer category: %s' % error)
    _fill_widgets()
    # The background applications start once Titan's window is up: each
    # is a Ruby process, and none of them is what the user is waiting for.
    try:
        wx.CallLater(4000, _start_widget_apps)
    except Exception:
        pass


def _fill_listbox():
    if _listbox is None:
        return
    try:
        _listbox.Clear()
    except RuntimeError:
        return
    found = applications()
    if not found:
        # A row that is a sentence, not an application - and it carries no
        # client data, which is what stops it being "opened".
        _listbox.Append(status())
        _listbox.SetClientData(0, None)
        return
    for index, entry in enumerate(found):
        label = entry.name or entry.stem
        if entry.version:
            label = '%s %s' % (label, entry.version)
        if entry.problem:
            label = '%s - %s' % (label, entry.problem)
        _listbox.Append(label)
        # The application itself, on the row. Matching by INDEX against a
        # freshly-read list is how the wrong application gets opened when
        # the list has changed underneath - or a status row is treated as
        # one.
        _listbox.SetClientData(index, entry)


def _on_view_activate(_event=None):
    """A row was activated. Never trust the argument.

    Titan's view system calls this with whatever it has - a `wx.KeyEvent`
    for Enter, nothing at all elsewhere - and reading it as an index is what
    made opening an application raise
    `'<=' not supported between instances of 'int' and 'KeyEvent'`, which the
    GUI swallowed and reported, so nothing opened and nothing said why. What
    is selected is a question for the list.
    """
    if _listbox is None:
        return
    wx = _wx()
    selection = _listbox.GetSelection()
    if selection == wx.NOT_FOUND:
        return
    try:
        entry = _listbox.GetClientData(selection)
    except (RuntimeError, TypeError):
        entry = None
    if entry is None:
        return
    if entry.problem:
        wx.MessageBox(entry.problem, entry.name or TITLE,
                      wx.OK | wx.ICON_ERROR)
        return
    run_application(entry, _parent_window())


def open_browser(parent=None):
    """The list, as a window of its own."""
    wx = _wx()
    found = applications()
    if not found:
        wx.MessageBox(status(), TITLE, wx.OK | wx.ICON_INFORMATION)
        return None
    labels = []
    for entry in found:
        label = entry.name or entry.stem
        if entry.version:
            label = '%s %s' % (label, entry.version)
        if entry.author:
            label = '%s - %s' % (label, entry.author)
        if entry.problem:
            label = '%s (%s)' % (label, entry.problem)
        labels.append(label)
    parent = parent or _parent_window()
    dialog = wx.SingleChoiceDialog(parent, status(), TITLE, labels)
    try:
        if dialog.ShowModal() != wx.ID_OK:
            return None
        entry = found[dialog.GetSelection()]
    finally:
        dialog.Destroy()
    if entry.problem:
        wx.MessageBox(entry.problem, entry.name or TITLE,
                      wx.OK | wx.ICON_ERROR)
        return None
    return run_application(entry, parent)


# ---------------------------------------------------------------------------
# The Action API - the same seven things, for a macro, the AI or another
# add-on. Nothing here needs a window.
# ---------------------------------------------------------------------------
def _action_list(**_arguments):
    found = applications()
    if not found:
        return status()
    lines = []
    for entry in found:
        line = '%s %s' % (entry.name or entry.stem, entry.version)
        if entry.author:
            line += ' by %s' % entry.author
        if entry.problem:
            line += ' [%s]' % entry.problem
        lines.append(line.strip())
    return '\n'.join(lines)


def _action_details(name='', **_arguments):
    entry = catalogue.find(name, language())
    if entry is None:
        return 'There is no Elten application called %s.' % name
    parts = ['%s %s' % (entry.name or entry.stem, entry.version),
             'author: %s' % (entry.author or 'unknown'),
             'API: %s' % (entry.api_version or 'unknown'),
             'id: %s' % entry.id,
             'file: %s' % entry.path]
    if entry.description:
        parts.insert(1, entry.description)
    if entry.signature.signed:
        parts.append('signed by %s' % entry.signature.subject())
    else:
        parts.append('not signed')
    if entry.problem:
        parts.append('cannot run: %s' % entry.problem)
    return '\n'.join(parts)


def _action_run(name='', **_arguments):
    entry = catalogue.find(name, language())
    if entry is None:
        return 'There is no Elten application called %s.' % name
    if entry.problem:
        return entry.problem
    wx = _wx()
    wx.CallAfter(run_application, entry, _parent_window())
    return 'Opening %s.' % (entry.name or entry.stem)


def _action_status(**_arguments):
    return status()


def _action_log(name='', lines=60, **_arguments):
    """What the application said - including what it stopped on.

    An Elten application reports a failure the way Elten's own do: it
    rescues, tells the user one sentence ("The operation could not be
    completed"), and carries on. The reason is in the log, `boot.rb` puts
    the exception class and message there, and until this there was no way
    to read it once the window had gone - so "it still does not work" could
    only be answered by guessing. This is the answer instead.
    """
    wanted = str(name or '').strip().lower()
    held = None
    for entry, application, _gui in list(_running):
        if not wanted or wanted in (entry.name or '').lower() \
                or wanted in (entry.stem or '').lower():
            held = (entry.name or entry.stem, list(application.log or []))
            break
    if held is None:
        held = _last_log
    label, log = held
    if not log:
        return _('Nothing has been logged. No Elten application has run '
                 'in this session.') if not label else \
            _('%s logged nothing.') % label
    try:
        limit = max(1, min(500, int(lines)))
    except (TypeError, ValueError):
        limit = 60
    tail = log[-limit:]
    said = [_('%(name)s said (%(count)d of %(total)d lines):')
            % {'name': label, 'count': len(tail), 'total': len(log)}]
    said.extend('  %s: %s' % (level, text) for level, text in tail)
    return '\n'.join(said)


# **`name`, not `id`.** `actions/manifest.py`'s `_parse_action` reads
# `raw['name']` and drops an entry that has none - "an action has no usable
# 'name'; ignored" - so all four of these were declared and none of them
# existed: `elten_bridge` offered Titan the three generic component actions
# and nothing of its own. `run` is the callable, which is what the
# component convention is (`data/components/cling` and every other one).
TITAN_ACTIONS = [
    {'name': 'list_applications', 'label': 'List Elten applications',
     'summary': 'Every Elten API application installed on this machine.',
     'run': _action_list, 'params': {}},
    {'name': 'details', 'label': 'Elten application details',
     'summary': 'What one application is, who signed it and where it lives.',
     'run': _action_details,
     'params': {'name': {'type': 'string', 'required': True,
                         'description': 'The application, by name or id.'}}},
    {'name': 'run', 'label': 'Run an Elten application',
     'summary': 'Open an Elten API application in Titan.',
     'run': _action_run,
     'params': {'name': {'type': 'string', 'required': True,
                         'description': 'The application, by name or id.'}}},
    {'name': 'status', 'label': 'Elten bridge status',
     'summary': 'Whether the bridge can run anything, and on which Ruby.',
     'run': _action_status, 'params': {}},
    {'name': 'log', 'label': 'What an Elten application said',
     'summary': ('The log of a running Elten application, or of the last '
                 'one that ran - including the exception it stopped on. '
                 'This is what to read when an application does nothing '
                 'and says nothing.'),
     'run': _action_log,
     'params': {'name': {'type': 'string',
                         'description': 'The application. Left out, '
                                        'whichever ran last.'},
                'lines': {'type': 'integer',
                          'description': 'How many of the last lines. 60 '
                                         'by default.'}}},
]
