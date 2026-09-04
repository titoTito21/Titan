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
    _watch(application, gui)
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


def stop_all():
    """Close every running application - Titan is going."""
    for _entry, application, gui in list(_running):
        _finish(application, gui)


# ---------------------------------------------------------------------------
# Titan component hooks
# ---------------------------------------------------------------------------
def add_menu(component_manager):
    component_manager.register_menu_function(_(TITLE), _on_menu_action)


def _on_menu_action(_event=None):
    open_browser()


def get_gui_hooks():
    return {'on_gui_init': _on_gui_init}


def _on_gui_init(gui_app):
    """An Elten view in the main window, beside applications and games."""
    global _gui_app, _listbox
    wx = _wx()
    _gui_app = gui_app
    _listbox = wx.ListBox(gui_app.main_panel)
    _fill_listbox()
    gui_app.component_manager.register_view(
        view_id='elten_apps', label=_(TITLE) + ':', control=_listbox,
        on_show=_fill_listbox, on_activate=_on_view_activate,
        position='after_network')


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


TITAN_ACTIONS = [
    {'id': 'list_applications', 'label': 'List Elten applications',
     'summary': 'Every Elten API application installed on this machine.',
     'handler': _action_list, 'params': {}},
    {'id': 'details', 'label': 'Elten application details',
     'summary': 'What one application is, who signed it and where it lives.',
     'handler': _action_details,
     'params': {'name': {'type': 'string', 'required': True,
                         'description': 'The application, by name or id.'}}},
    {'id': 'run', 'label': 'Run an Elten application',
     'summary': 'Open an Elten API application in Titan.',
     'handler': _action_run,
     'params': {'name': {'type': 'string', 'required': True,
                         'description': 'The application, by name or id.'}}},
    {'id': 'status', 'label': 'Elten bridge status',
     'summary': 'Whether the bridge can run anything, and on which Ruby.',
     'handler': _action_status, 'params': {}},
]
