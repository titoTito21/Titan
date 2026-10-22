# Filename: componentmanagergui.py
"""The Component Manager: every part of Titan that can be switched off.

It is shaped like Titan's main window, because that is the interaction a
Titan user already has in their fingers: row 0 of the list is the tab bar
(Left/Right and Ctrl+Tab move between the kinds - Components, Titan
services, Applications, Games, Titan IM modules, TTS engines...), every move
plays the panned focus cue, running off the list plays the end-of-list
sound, Space switches the row on or off, Enter and the Applications key open
what can be done with it, F5 reads everything again and Escape closes.

What a module IS, and whether it is on, is ``src/titan_core/modules.py``;
this window only shows it. A change that only takes effect when Titan
starts again is said so, on its row and when the window closes, where Titan
offers to restart.
"""
import os
import sys
import configparser

import wx

from src.accessibility.lazy_speaker import LazySpeaker
from src.titan_core.sound import play_sound, play_focus_sound, play_endoflist_sound
from src.titan_core.translation import set_language
from src.settings.settings import get_setting, load_settings
from src.titan_core.skin_manager import apply_skin_to_window

# Get the translation function
_ = set_language(get_setting('language', 'pl'))

TAB_BAR_MARKER = {'type': 'tab_bar'}

# The order of the tab bar. The window is the COMPONENT manager, so
# components come first; the kinds that have nothing installed are left out.
TAB_ORDER = ('component', 'service', 'app', 'game', 'im_module', 'tts_engine',
             'gamepad_mode', 'widget', 'statusbar_applet', 'shell_addon',
             'settings_interface', 'launcher', 'macro')

# Standard actions the window already offers itself (Space switches).
_HIDDEN_ACTIONS = {'enable', 'disable'}


def _show_skinned_message(message, caption, style=wx.OK | wx.ICON_INFORMATION, parent=None):
    dlg = wx.MessageDialog(parent, message, caption, style)
    try:
        apply_skin_to_window(dlg)
    except Exception:
        pass
    result = dlg.ShowModal()
    dlg.Destroy()
    return result


def _get_base_path():
    """Get base path for resources, supporting PyInstaller and Nuitka."""
    if hasattr(sys, '_MEIPASS') or getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def _pan_for(index, count):
    """Stereo pan of real row ``index`` of ``count``: 0.0 left, 1.0 right."""
    if count <= 1:
        return 0.5
    return max(0.0, min(1.0, index / float(count - 1)))


def _modules():
    from src.titan_core import modules
    return modules


class ComponentManagerDialog(wx.Dialog):
    """Modal, so the three faces that open it (the menu bar, the Invisible
    UI, Klango mode) keep standing their keyboard down around ShowModal."""

    def __init__(self, parent, title, component_manager=None):
        super().__init__(parent, title=title, size=(720, 560),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        self.component_manager = component_manager
        # Shared and built on first use: an Auto() here was imported by the
        # menu bar at startup, with speech_recognition (8.7 MB) behind it.
        self.tts = LazySpeaker()

        self.tabs = []
        self.current_tab = ''
        self.items = []
        self._cache = {}
        self._last_focus_idx = 0

        panel = wx.Panel(self)
        self.panel = panel
        vbox = wx.BoxSizer(wx.VERTICAL)

        lbl = wx.StaticText(panel, label=_("Modules of Titan:"))
        vbox.Add(lbl, 0, wx.ALL | wx.EXPAND, 5)

        self.component_listbox = wx.ListBox(panel, wx.ID_ANY, style=wx.LB_SINGLE)
        self.component_listbox.SetName(_("Modules of Titan"))
        vbox.Add(self.component_listbox, 1, wx.ALL | wx.EXPAND, 5)

        details_label = wx.StaticText(panel, label=_("Details:"))
        vbox.Add(details_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.details = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
            size=(-1, 110))
        self.details.SetName(_("Details"))
        vbox.Add(self.details, 0, wx.ALL | wx.EXPAND, 5)

        self.summary = wx.StaticText(panel, label='')
        vbox.Add(self.summary, 0, wx.ALL | wx.EXPAND, 5)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.toggle_button = wx.Button(panel, label=_("&Switch off"))
        self.actions_button = wx.Button(panel, label=_("&Actions"))
        self.restart_button = wx.Button(panel, label=_("&Restart Titan"))
        self.close_button = wx.Button(panel, wx.ID_CLOSE, label=_("&Close"))
        for button in (self.toggle_button, self.actions_button,
                       self.restart_button, self.close_button):
            buttons.Add(button, 0, wx.ALL, 5)
        vbox.Add(buttons, 0, wx.ALIGN_CENTER)

        panel.SetSizer(vbox)

        self.component_listbox.Bind(wx.EVT_LISTBOX, self.on_selection_change)
        self.component_listbox.Bind(wx.EVT_LISTBOX_DCLICK,
                                    lambda event: self.on_actions_button_press(event))
        self.component_listbox.Bind(wx.EVT_CONTEXT_MENU,
                                    lambda event: self.on_actions_button_press(event))
        self.toggle_button.Bind(wx.EVT_BUTTON, lambda event: self.toggle_selected())
        self.actions_button.Bind(wx.EVT_BUTTON, self.on_actions_button_press)
        self.restart_button.Bind(wx.EVT_BUTTON, lambda event: self.offer_restart(ask=False))
        self.close_button.Bind(wx.EVT_BUTTON, lambda event: self.Close())
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.SetEscapeId(wx.ID_NONE)

        self.tabs = self.build_tabs()
        if self.tabs:
            self.current_tab = self.tabs[0][0]
        self.populate_component_list()

        self.apply_skin_settings()
        self.Centre()
        self.component_listbox.SetFocus()

    # ------------------------------------------------------------- the model
    def build_tabs(self):
        """[(kind, label)] for every kind with at least one module."""
        modules = _modules()
        tabs = []
        for kind in TAB_ORDER:
            try:
                found = modules.modules(kind)
            except Exception as error:
                print(f"[ComponentManager] {kind}: {error}")
                found = []
            self._cache[kind] = found
            if found:
                tabs.append((kind, modules.kind_label(kind)))
        return tabs

    def tab_label(self, kind):
        for candidate, label in self.tabs:
            if candidate == kind:
                return label
        return kind

    def tab_index(self, kind):
        for index, (candidate, _label) in enumerate(self.tabs):
            if candidate == kind:
                return index
        return 0

    def tab_bar_text(self):
        if not self.tabs:
            return _("Tab bar")
        return _("{}, {} of {}").format(self.tab_label(self.current_tab),
                                        self.tab_index(self.current_tab) + 1,
                                        len(self.tabs))

    def row_text(self, module):
        modules = _modules()
        state = _("Enabled") if module.enabled else _("Disabled")
        text = f"{module.name}, {state}"
        if modules.waits_for_restart(module):
            text += ", " + _("after restart")
        return text

    # ----------------------------------------------------------------- rows
    def populate_component_list(self, keep_key=None):
        listbox = self.component_listbox
        listbox.Freeze()
        try:
            listbox.Clear()
            if not self.tabs:
                listbox.Append(_("Nothing to manage."))
                self.items = []
                return
            listbox.Append(self.tab_bar_text(), dict(TAB_BAR_MARKER))
            self.items = list(self._cache.get(self.current_tab) or [])
            for module in self.items:
                listbox.Append(self.row_text(module), module)
        finally:
            listbox.Thaw()
        target = 0
        if keep_key:
            for position, module in enumerate(self.items):
                if module.key == keep_key:
                    target = position + 1
                    break
        listbox.SetSelection(target)
        self._last_focus_idx = target
        self.update_details()
        self.update_summary()

    def refresh(self):
        selected = self.selected_module()
        self._cache = {}
        self.tabs = self.build_tabs()
        if self.current_tab not in [kind for kind, _label in self.tabs]:
            self.current_tab = self.tabs[0][0] if self.tabs else ''
        self.populate_component_list(selected.key if selected else None)
        self.tts.output(_("Refreshed"))

    def selected_module(self):
        index = self.component_listbox.GetSelection()
        if index <= 0:
            return None
        position = index - 1
        if 0 <= position < len(self.items):
            return self.items[position]
        return None

    def is_tab_bar_row(self, index):
        if index != 0 or self.component_listbox.GetCount() == 0:
            return False
        data = self.component_listbox.GetClientData(0)
        return isinstance(data, dict) and data.get('type') == 'tab_bar'

    def update_details(self):
        module = self.selected_module()
        modules = _modules()
        self.toggle_button.Enable(module is not None)
        self.actions_button.Enable(module is not None)
        self.restart_button.Enable(bool(modules.pending_restart()))
        if module is None:
            self.toggle_button.SetLabel(_("&Switch off"))
            self.details.SetValue(_("{}: {} modules").format(
                self.tab_label(self.current_tab), len(self.items)))
            return
        self.toggle_button.SetLabel(_("&Switch off") if module.enabled
                                    else _("&Switch on"))
        self.details.SetValue(self.details_text(module))

    def details_text(self, module):
        modules = _modules()
        lines = [module.name,
                 _("Kind: {}").format(modules.kind_label(module.kind)),
                 _("State: {}").format(_("Enabled") if module.enabled
                                       else _("Disabled"))]
        if modules.waits_for_restart(module):
            lines.append(_("The change takes effect after Titan restarts."))
        if module.description:
            lines.append(_("Description: {}").format(module.description))
        if module.kind != 'service':
            lines.append(_("Identifier: {}").format(module.id))
        if module.packaged:
            lines.append(_("Installed as a package."))
        if module.path:
            lines.append(_("Folder: {}").format(module.path))
        return "\n".join(lines)

    def update_summary(self):
        if not self.items:
            self.summary.SetLabel('')
            return
        on = sum(1 for module in self.items if module.enabled)
        self.summary.SetLabel(_("{} of {} switched on").format(on, len(self.items)))

    # ------------------------------------------------------------- feedback
    def emit_focus_feedback(self, index):
        if self.is_tab_bar_row(index):
            try:
                from src.accessibility.messages import announce_tab_bar
                announce_tab_bar(self.tab_label(self.current_tab),
                                 self.tab_index(self.current_tab) + 1,
                                 len(self.tabs))
            except Exception:
                try:
                    play_sound('ui/tapbar.ogg')
                except Exception:
                    pass
        else:
            real_count = max(0, self.component_listbox.GetCount() - 1)
            try:
                play_focus_sound(pan=_pan_for(index - 1, real_count))
            except Exception:
                pass
        self._last_focus_idx = index
        self.update_details()

    def on_selection_change(self, event):
        index = self.component_listbox.GetSelection()
        if index >= 0 and index != self._last_focus_idx:
            self.emit_focus_feedback(index)
        else:
            self.update_details()
        if event:
            event.Skip()

    def cycle_tab(self, direction):
        index = self.tab_index(self.current_tab) + direction
        if index < 0 or index >= len(self.tabs):
            try:
                play_sound('ui/endoftapbar.ogg')
            except Exception:
                pass
            return
        self.current_tab = self.tabs[index][0]
        self.populate_component_list()
        self.component_listbox.SetFocus()
        try:
            from src.accessibility.messages import announce_view_switched
            announce_view_switched(self.tab_label(self.current_tab), index,
                                   len(self.tabs))
        except Exception:
            try:
                play_sound('ui/switch_list.ogg')
            except Exception:
                pass

    # ----------------------------------------------------------------- keys
    def on_char_hook(self, event):
        keycode = event.GetKeyCode()
        modifiers = event.GetModifiers()
        focus = self.FindFocus()

        if keycode == wx.WXK_ESCAPE and modifiers == wx.MOD_NONE:
            self.Close()
            return
        if keycode == wx.WXK_F5 and modifiers == wx.MOD_NONE:
            self.refresh()
            return
        if keycode == wx.WXK_TAB and modifiers == wx.MOD_CONTROL:
            self.cycle_tab(+1)
            return
        if keycode == wx.WXK_TAB and modifiers == (wx.MOD_CONTROL | wx.MOD_SHIFT):
            self.cycle_tab(-1)
            return

        if focus is not self.component_listbox:
            event.Skip()
            return

        listbox = self.component_listbox
        index = listbox.GetSelection()
        count = listbox.GetCount()

        if keycode in (wx.WXK_LEFT, wx.WXK_RIGHT) and modifiers == wx.MOD_NONE:
            if self.is_tab_bar_row(index):
                self.cycle_tab(-1 if keycode == wx.WXK_LEFT else +1)
            return
        if keycode == wx.WXK_SPACE and modifiers == wx.MOD_NONE:
            self.toggle_selected()
            return
        if keycode in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and modifiers == wx.MOD_NONE:
            self.on_actions_button_press(None)
            return
        if keycode in (wx.WXK_WINDOWS_MENU, wx.WXK_MENU) or \
                (keycode == wx.WXK_F10 and modifiers == wx.MOD_SHIFT):
            self.on_actions_button_press(None)
            return

        new_index = index
        if keycode == wx.WXK_UP:
            new_index = index - 1
        elif keycode == wx.WXK_DOWN:
            new_index = index + 1
        elif keycode == wx.WXK_HOME:
            new_index = 0
        elif keycode == wx.WXK_END:
            new_index = count - 1
        else:
            event.Skip()
            return
        if modifiers != wx.MOD_NONE:
            event.Skip()
            return
        if 0 <= new_index < count and new_index != index:
            listbox.SetSelection(new_index)
            self.emit_focus_feedback(new_index)
        else:
            try:
                play_endoflist_sound()
            except Exception:
                pass

    # ------------------------------------------------------------- toggling
    def toggle_selected(self):
        module = self.selected_module()
        if module is None:
            return
        self.set_module_enabled(module, not module.enabled)

    def set_module_enabled(self, module, enabled):
        modules = _modules()
        change = modules.set_enabled(module, enabled)
        if not change.ok:
            try:
                play_sound('core/error.ogg')
            except Exception:
                pass
            _show_skinned_message(
                change.message or _("The change could not be made."),
                _("Component Manager"), wx.OK | wx.ICON_ERROR, self)
            return
        try:
            play_sound('core/SELECT.ogg')
        except Exception:
            pass
        index = self.component_listbox.GetSelection()
        if index > 0:
            self.component_listbox.SetString(index, self.row_text(module))
        state = _("switched on") if module.enabled else _("switched off")
        message = _("{} {}").format(module.name, state)
        if change.needs_restart and modules.waits_for_restart(module):
            message += ". " + _("Takes effect after Titan restarts.")
        self.tts.output(message)
        self.update_details()
        self.update_summary()

    # --------------------------------------------------------------- actions
    def on_actions_button_press(self, event):
        module = self.selected_module()
        if module is None:
            return
        self.show_context_menu(module)

    def on_menu_close(self, event):
        play_sound('ui/contextmenuclose.ogg')
        if event:
            event.Skip()

    def menu_entries(self, module):
        """[(label, callable)] for the selected module."""
        entries = [(_("Switch off") if module.enabled else _("Switch on"),
                    lambda: self.set_module_enabled(module, not module.enabled))]
        if module.enabled:
            entries.extend(self._open_entries(module))
        entries.extend(self._action_entries(module))
        entries.append((_("Details"), lambda: self.show_details(module)))
        if module.path and os.path.isdir(module.path) and not module.packaged:
            entries.append((_("Open folder"), lambda: self.open_folder(module)))
        if _modules().pending_restart():
            entries.append((_("Restart Titan now"),
                            lambda: self.offer_restart(ask=False)))
        return entries

    def _component_module(self, folder):
        manager = self.component_manager
        if manager is None:
            return None
        return next((c for c in getattr(manager, 'components', [])
                     if getattr(c, '__name__', '') == folder), None)

    def _open_entries(self, module):
        entries = []
        kind = module.kind
        if kind == 'component':
            component = self._component_module(module.id)
            if component is not None:
                if self._component_run_function(module.id):
                    entries.append((_("Run"), lambda: self.on_run_action(module.id)))
                if hasattr(component, 'show_settings_dialog'):
                    entries.append((_("Settings"),
                                    lambda: self.on_settings_action(module.id)))
        elif kind == 'app':
            entries.append((_("Open"), lambda: self.open_application(module)))
        elif kind == 'game':
            entries.append((_("Play"), lambda: self.open_game(module)))
        elif kind == 'im_module':
            entries.append((_("Open"), lambda: self.open_im_module(module)))
        return entries

    def _action_entries(self, module):
        """What the add-on itself declares through the Action API."""
        if module.kind == 'service' or not module.enabled:
            return []
        try:
            from src.titan_core import actions
            registry = actions.get_registry()
        except Exception:
            return []
        entries = []
        for addon in getattr(registry, 'addons', []):
            if addon.kind != module.kind or addon.name != module.id:
                continue
            for action in addon.actions:
                if action.name in _HIDDEN_ACTIONS:
                    continue
                label = action.name.replace('_', ' ').capitalize()
                entries.append((_("Action: {}").format(label),
                                lambda a=addon, s=action: self.run_addon_action(a, s)))
        return entries

    def show_context_menu(self, module):
        entries = self.menu_entries(module)
        menu = wx.Menu()
        handlers = {}
        for label, handler in entries:
            item = menu.Append(wx.ID_ANY, label)
            handlers[item.GetId()] = handler
        play_sound('ui/contextmenu.ogg')

        def dispatch(event):
            handler = handlers.get(event.GetId())
            if handler:
                wx.CallAfter(handler)

        menu.Bind(wx.EVT_MENU, dispatch)
        self.component_listbox.PopupMenu(menu)
        menu.Destroy()
        self.on_menu_close(None)

    def _component_run_function(self, folder):
        manager = self.component_manager
        if manager is None:
            return None
        menu_funcs = manager.get_component_menu_functions() or {}
        display = (manager.component_friendly_names.get(folder, folder)
                   if hasattr(manager, 'component_friendly_names') else folder)
        for name, func in menu_funcs.items():
            low = name.lower()
            if folder.lower() in low or display.lower() in low:
                return func
        return None

    def on_run_action(self, component_folder):
        func = self._component_run_function(component_folder)
        if not func:
            return
        try:
            func(self)
        except TypeError:
            try:
                func(None)
            except Exception as e:
                _show_skinned_message(_("Error running component '{}':\n{}").format(component_folder, e),
                                      _("Error"), wx.OK | wx.ICON_ERROR, self)
        except Exception as e:
            _show_skinned_message(_("Error running component '{}':\n{}").format(component_folder, e),
                                  _("Error"), wx.OK | wx.ICON_ERROR, self)

    def on_settings_action(self, component_folder):
        component = self._component_module(component_folder)
        if component is not None and hasattr(component, 'show_settings_dialog'):
            try:
                component.show_settings_dialog(self)
            except Exception as e:
                _show_skinned_message(_("Error opening settings for '{}':\n{}").format(component_folder, e),
                                      _("Error"), wx.OK | wx.ICON_ERROR, self)

    def open_application(self, module):
        try:
            from src.titan_core import app_manager
            info = app_manager.read_app_info(module.path, get_setting('language', 'pl'))
            if info:
                app_manager.open_application(info)
        except Exception as e:
            _show_skinned_message(str(e), _("Error"), wx.OK | wx.ICON_ERROR, self)

    def open_game(self, module):
        try:
            from src.titan_core import game_manager
            info = game_manager.read_game_info(module.path)
            if info:
                game_manager.open_game(info)
        except Exception as e:
            _show_skinned_message(str(e), _("Error"), wx.OK | wx.ICON_ERROR, self)

    def open_im_module(self, module):
        try:
            from src.network.im_module_manager import im_module_manager
            im_module_manager.open_module(module.id, self.GetParent() or self)
        except Exception as e:
            _show_skinned_message(str(e), _("Error"), wx.OK | wx.ICON_ERROR, self)

    def run_addon_action(self, addon, action):
        from src.titan_core import actions
        if action.risk in ('confirm', 'always_confirm'):
            answer = _show_skinned_message(
                _("Run '{}' of {}?").format(action.name.replace('_', ' '), addon.label),
                _("Component Manager"), wx.YES_NO | wx.ICON_QUESTION, self)
            if answer != wx.ID_YES:
                return
        try:
            result = actions.run_interactive(addon.addon_id, action.name, parent=self)
            text = getattr(result, 'text', '') or ''
        except Exception as error:
            text = str(error)
        if text:
            self.tts.output(text)
            if len(text) > 160:
                _show_skinned_message(text, addon.label, wx.OK | wx.ICON_INFORMATION, self)

    def show_details(self, module):
        _show_skinned_message(self.details_text(module), module.name,
                              wx.OK | wx.ICON_INFORMATION, self)

    def open_folder(self, module):
        try:
            from src.platform_utils import open_file_manager
            open_file_manager(module.path)
        except Exception as e:
            _show_skinned_message(str(e), _("Error"), wx.OK | wx.ICON_ERROR, self)

    # --------------------------------------------------------------- closing
    def offer_restart(self, ask=True):
        """True when Titan is being restarted."""
        modules = _modules()
        if ask:
            pending = modules.pending_restart()
            if not pending:
                return False
            answer = _show_skinned_message(
                _("{} changes take effect only after Titan restarts. "
                  "Restart Titan now?").format(len(pending)),
                _("Component Manager"), wx.YES_NO | wx.ICON_QUESTION, self)
            if answer != wx.ID_YES:
                return False
        if modules.restart_titan():
            return True
        _show_skinned_message(_("Titan could not be restarted."),
                              _("Error"), wx.OK | wx.ICON_ERROR, self)
        return False

    def on_close(self, event):
        if not getattr(self, '_asked_restart', False):
            self._asked_restart = True
            self.offer_restart(ask=True)
        if self.IsModal():
            self.EndModal(wx.ID_CLOSE)
        else:
            self.Destroy()

    # ----------------------------------------------------------------- skin
    def apply_skin_settings(self):
        """Apply current skin settings to component manager"""
        try:
            apply_skin_to_window(self)
        except Exception:
            pass
        try:
            settings = load_settings()
            skin_name = settings.get('interface', {}).get('skin', 'default')

            skin_path = os.path.join(_get_base_path(), "skins", skin_name, "skin.ini")
            if not os.path.exists(skin_path):
                return

            config = configparser.ConfigParser()
            config.read(skin_path, encoding='utf-8')

            colors = dict(config.items('Colors')) if config.has_section('Colors') else {}
            fonts = dict(config.items('Fonts')) if config.has_section('Fonts') else {}

            if colors:
                def hex_to_wx_colour(hex_color):
                    hex_color = hex_color.lstrip('#')
                    return wx.Colour(int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))

                frame_bg = colors.get('frame_background_color', '#C0C0C0')
                listbox_bg = colors.get('listbox_background_color', '#FFFFFF')
                self.SetBackgroundColour(hex_to_wx_colour(frame_bg))
                self.component_listbox.SetBackgroundColour(hex_to_wx_colour(listbox_bg))

            if fonts:
                default_size = int(fonts.get('default_font_size', 9))
                listbox_face = fonts.get('listbox_font_face', 'MS Sans Serif')
                listbox_font = wx.Font(default_size, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL,
                                       wx.FONTWEIGHT_NORMAL, faceName=listbox_face)
                self.component_listbox.SetFont(listbox_font)
                self.SetFont(listbox_font)

            self.Refresh()
        except Exception as e:
            print(f"Error applying skin to component manager: {e}")


def show_component_manager(parent=None, component_manager=None):
    """Open the Component Manager modally. The one way in for code that has
    no reason to build the dialog itself (actions, the Start menu)."""
    dialog = ComponentManagerDialog(parent, _("Component Manager"),
                                    component_manager=component_manager)
    try:
        dialog.ShowModal()
    finally:
        if dialog:
            try:
                dialog.Destroy()
            except Exception:
                pass
