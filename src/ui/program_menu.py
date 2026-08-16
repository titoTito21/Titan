# -*- coding: utf-8 -*-
"""
The Program menu's own entries, named once for all three faces of Titan.

Titan has three interfaces and one set of things the Program menu can do.
The menu bar (`src/ui/menu.py`) had them all; the Invisible UI's **Menu**
category and Klango mode's **Program** submenu had four of them between them,
so a user who works entirely without the graphical window simply could not
reach the AI Agent, either AI Assistant, AI OCR or the creation kit - features
that need no window at all, and whose users are the least likely to be looking
at one.

So the entries live here and each face renders them its own way: the menu bar
builds `wx.MenuItem`s with skin icons, the Invisible UI a category with the
labels in it, Klango mode a submenu of `{"name": ..., "type": "action"}`
items.  Each entry is a dict:

    {'id': str, 'label': str, 'icon': str or None, 'action': callable()}

`action` takes no arguments and must be called **on the GUI thread** - the
Invisible UI's `safe_call_after` and Klango's own dispatch already do that.

**They are GROUPS, not one longer list.**  The graphical Titan has Program,
AI and Programmer, and sixteen more lines in one menu is not the same thing
however many of them are there.  `extra_groups()` hands back the menus a face
without a menu bar was missing entirely, and each face nests them where its
own groups already nest: both the Invisible UI's and Klango mode's **Menu**
card holds the menu bar's menus - Program, AI, Programmer - the Invisible UI
opening each as a **subcategory** exactly as a game platform opens inside the
Games card, and Klango as a **submenu** exactly as a platform is a submenu of
Games.  `program_entries()` is the little that merges into the
Program menu each face already has.  Availability is decided here too, so
"AI features are off" is one answer rather than three: a group with nothing
in it is not returned at all.
"""

import wx

from src.titan_core.translation import set_language
from src.settings.settings import get_setting

_ = set_language(get_setting('language', 'pl'))


def _report(message, caption=None):
    """Say what went wrong, skinned like the rest of Titan."""
    try:
        from src.ui.menu import _show_skinned_message
        _show_skinned_message(message, caption or _("Error"),
                              wx.OK | wx.ICON_ERROR)
    except Exception:
        print(f"[program menu] {message}")


def _main_frame(parent=None):
    if parent is not None:
        return parent
    try:
        app = wx.GetApp()
        return app.GetTopWindow() if app else None
    except Exception:
        return None


def _bring_titan_back(frame):
    """Titan's window in front, through its own way back.

    The AI windows are Titan's own windows, so opening one from the Invisible
    UI has to put Titan back on the screen exactly as the graphical menu
    would - tray icon destroyed, Invisible UI stood down, the sound played.
    `restore_from_tray` is the one thing that does all of that.
    """
    if frame is None:
        return
    try:
        if not frame.IsShown() or frame.IsIconized():
            restore = getattr(frame, 'restore_from_tray', None)
            if callable(restore):
                restore()
            else:
                frame.Iconize(False)
                frame.Show()
                frame.Raise()
    except Exception as e:
        print(f"[program menu] could not bring Titan back: {e}")


# ----------------------------------------------------------------------
# What the entries actually do
# ----------------------------------------------------------------------

def open_ai_agent(parent=None):
    frame = _main_frame(parent)
    _bring_titan_back(frame)
    try:
        from src.ai.ai_agent_gui import open_agent
        open_agent(frame)
    except Exception as e:
        import traceback
        traceback.print_exc()
        _report(_("Could not open the AI Agent: {error}").format(error=e))


def open_ai_assistant(parent=None, mode='turn'):
    frame = _main_frame(parent)
    _bring_titan_back(frame)
    try:
        from src.ai.assistant.assistant_gui import open_assistant
        open_assistant(frame, mode=mode)
    except Exception as e:
        import traceback
        traceback.print_exc()
        _report(_("Could not open the AI Assistant: {error}").format(error=e))


def open_ai_ocr(parent=None):
    # Deliberately does NOT bring Titan back first: the whole point is to
    # read the program the user was just in, and putting the Titan window in
    # front would make that program stop being it.
    try:
        from src.ai.ocr.mimic import show_ai_ocr
        show_ai_ocr(_main_frame(parent))
    except Exception as e:
        import traceback
        traceback.print_exc()
        _report(_("Could not open AI OCR: {error}").format(error=e))


def open_creation_wizard(parent=None, kind_id=None):
    frame = _main_frame(parent)
    _bring_titan_back(frame)
    try:
        from src.ai.ai_creation_kit import open_creation_wizard as _open
        _open(frame, kind_id)
    except Exception as e:
        import traceback
        traceback.print_exc()
        _report(_("Could not open the AI creator: {error}").format(error=e))


def open_project_browser(parent=None):
    """Every saved creation-kit project, of every kind, in one list."""
    frame = _main_frame(parent)
    _bring_titan_back(frame)
    try:
        from src.ai.ai_creation_kit import open_project_browser as _open
        _open(frame)
    except Exception as e:
        import traceback
        traceback.print_exc()
        _report(_("Could not open the AI projects: {error}").format(error=e))


def install_data_package(parent=None):
    """The Install data package flow, wherever it was asked for.

    The unpacking itself is the menu bar's (`MenuBar.extract_package`), which
    is where it has always been and where its progress dialog lives; this is
    only the way in for a face of Titan that has no menu bar.
    """
    frame = _main_frame(parent)
    _bring_titan_back(frame)
    try:
        bar = frame.GetMenuBar() if frame is not None else None
    except Exception:
        bar = None
    if bar is not None and hasattr(bar, 'on_install_data_package'):
        bar.on_install_data_package(None)
        return
    # Klango mode and a Titan started minimised have no menu bar at all, so
    # one is made for its handler and thrown away - it is not attached to a
    # window and never appears.
    try:
        from src.ui.menu import MenuBar
        MenuBar(frame).on_install_data_package(None)
    except Exception as e:
        import traceback
        traceback.print_exc()
        _report(_("Could not install the data package: {error}").format(error=e))


# ----------------------------------------------------------------------
# The lists
# ----------------------------------------------------------------------

def _ai_enabled():
    try:
        from src.ai.ai_provider import is_ai_enabled
        return bool(is_ai_enabled())
    except Exception:
        return False


def _ocr_enabled():
    try:
        from src.ai.ai_provider import get_ocr_enabled
        return bool(get_ocr_enabled())
    except Exception:
        return False


def _developer_tools_enabled():
    try:
        return str(get_setting('developer_tools', 'False', 'general')).lower() in ('true', '1')
    except Exception:
        return False


def ai_entries(parent=None):
    """The AI windows, when Settings, AI features says they may be offered."""
    if not _ai_enabled():
        return []
    entries = [
        {'id': 'ai_agent',
         'label': _("AI Agent..."),
         'icon': None,
         'action': lambda: open_ai_agent(parent)},
        {'id': 'ai_assistant',
         'label': _("AI Assistant..."),
         'icon': None,
         'action': lambda: open_ai_assistant(parent, 'turn')},
        {'id': 'ai_assistant_live',
         'label': _("AI Assistant (Live mode)..."),
         'icon': None,
         'action': lambda: open_ai_assistant(parent, 'live')},
    ]
    # AI OCR has a switch of its own, because a scan sends a picture of the
    # screen to the provider.
    if _ocr_enabled():
        entries.append({
            'id': 'ai_ocr',
            'label': _("AI OCR (read this screen)..."),
            'icon': None,
            'action': lambda: open_ai_ocr(parent)})
    return entries


def creation_kit_entries(parent=None):
    """Programmer, AI - one entry per add-on kind the creation kit can write.

    Empty unless developer tools AND AI features are both on, which is what
    the menu bar has always asked.
    """
    if not _developer_tools_enabled() or not _ai_enabled():
        return []
    try:
        from src.ai.ai_creation_kit import KINDS
    except Exception as e:
        print(f"[program menu] AI creation kit unavailable: {e}")
        return []
    entries = []
    for kind in KINDS or []:
        kind_id = kind['id']
        entries.append({
            'id': f'create_{kind_id}',
            'label': _("Create {kind}...").format(kind=kind['label']),
            'icon': None,
            'action': (lambda kid=kind_id: open_creation_wizard(parent, kid))})
    # Anything bigger than one sitting is a project, and this is the way back
    # into one - the wizard's own Open lists only its own kind.
    entries.append({
        'id': 'ai_projects',
        'label': _("Projects (continue building)..."),
        'icon': None,
        'action': (lambda: open_project_browser(parent))})
    return entries


def program_entries(parent=None):
    """What belongs in the **Program** menu and no face of Titan had of its own.

    Component Manager, Program settings, Help and Exit are deliberately not
    here: the Invisible UI and Klango mode each already have their own, which
    know things this module does not (standing Titan UI down for a modal
    dialog, Klango's own exit).  They merge this in beside them.
    """
    return [{'id': 'install_package',
             'label': _("Install data package..."),
             'icon': 'folder_icon',
             'action': lambda: install_data_package(parent)}]


def extra_groups(parent=None):
    """The menu bar's other menus, for the faces of Titan that have no bar.

    The graphical Titan groups these - the AI windows in the Program menu,
    the creation kit under Programmer, AI - and "the same as the GUI" means
    the same GROUPS, not sixteen more lines in one list.  Each face nests one
    where its own kind of group goes: a **subcategory of the Invisible UI's
    Menu card**, opened the way a game platform opens inside Games, and a
    **submenu of Klango's Menu card**, the way a platform is a submenu of
    Games.  Each is `{'id', 'label', 'entries'}`; a group with nothing
    in it is not returned at all, which is what makes AI features being off,
    or developer tools, one answer rather than three.
    """
    groups = []
    ai = ai_entries(parent)
    if ai:
        groups.append({'id': 'ai', 'label': _("AI"), 'entries': ai})
    kit = creation_kit_entries(parent)
    if kit:
        groups.append({'id': 'programmer', 'label': _("Programmer"),
                       'entries': kit})
    return groups


# The name this had while these groups were cards on the Invisible UI's tab
# bar.  Kept so an add-on that already calls it does not break; new code says
# `extra_groups`.
extra_categories = extra_groups
