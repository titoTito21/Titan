# -*- coding: utf-8 -*-
"""
Launcher Manager for TCE Launcher.
Manages loading and running third-party launcher interfaces from data/launchers/.
Only one launcher can run at a time.
"""

import os
import sys
import gettext as _gettext
import configparser
import importlib.util
import threading
import types
from src.platform_utils import get_base_path as _get_base_path, is_frozen as _is_frozen


class LauncherConfig:
    """Parsed launcher configuration from __launcher__.TCE"""

    def __init__(self, path, folder_name):
        self.path = path
        self.folder_name = folder_name
        self.name = folder_name
        self.description = ''
        self.author = ''
        self.version = '1.0'
        self.status = 1  # 1=disabled, 0=enabled (matches component convention)
        self.features = {}
        self.libs = []  # library paths relative to launcher dir
        self._parse_config()

    def _parse_config(self):
        """Parse the __launcher__.TCE config file."""
        config_path = os.path.join(self.path, '__launcher__.TCE')
        if not os.path.exists(config_path):
            return

        config = configparser.ConfigParser()
        config.read(config_path, encoding='utf-8')

        if config.has_section('launcher'):
            self.name = config.get('launcher', 'name', fallback=self.folder_name)
            self.description = config.get('launcher', 'description', fallback='')
            self.author = config.get('launcher', 'author', fallback='')
            self.version = config.get('launcher', 'version', fallback='1.0')
            try:
                self.status = int(config.get('launcher', 'status', fallback='1'))
            except ValueError:
                self.status = 1

            libs_str = config.get('launcher', 'libs', fallback='')
            if libs_str.strip():
                self.libs = [d.strip() for d in libs_str.split(',') if d.strip()]

        # Parse [features] section - all default to True if section missing
        default_features = {
            'applications': True,
            'games': True,
            'titan_im': True,
            'help': True,
            'components': True,
            'system_hooks': True,
            'notifications': True,
            'sound': True,
            'invisible_ui': False,
        }

        if config.has_section('features'):
            for feature, default in default_features.items():
                value = config.get('features', feature, fallback=str(default))
                self.features[feature] = value.lower() in ['true', '1', 'yes']
        else:
            self.features = dict(default_features)

    @property
    def enabled(self):
        return self.status == 0


class _LauncherTrayIcon:
    """
    System tray icon shown when a launcher is minimized.
    Uses the same TCE Titan icon as the main GUI tray icon.
    Created/destroyed on the wx main thread.
    """

    def __init__(self, api):
        self._api = api
        self._tray_icon = None

    def show(self):
        """Create and show the tray icon. Must be called via wx.CallAfter."""
        try:
            import wx
            import wx.adv

            icon_path = self._find_icon_path()

            icon = None
            if icon_path and os.path.exists(icon_path):
                try:
                    icon = wx.Icon(icon_path)
                    if not icon.IsOk():
                        icon = None
                except Exception:
                    icon = None

            if icon is None:
                try:
                    icon = wx.Icon(wx.ArtProvider.GetBitmap(wx.ART_QUESTION, wx.ART_OTHER, (16, 16)))
                except Exception:
                    try:
                        icon = wx.Icon()
                    except Exception:
                        icon = None

            self._tray_icon = wx.adv.TaskBarIcon()
            if icon:
                _ = self._api._
                self._tray_icon.SetIcon(icon, _("Titan v{}").format(self._api.version))

            self._tray_icon.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self._on_dclick)
            self._tray_icon.Bind(wx.adv.EVT_TASKBAR_RIGHT_UP, self._on_right_click)

            print("[LauncherTray] Tray icon shown")
        except Exception as e:
            print(f"[LauncherTray] Error creating tray icon: {e}")

    def hide(self):
        """Destroy the tray icon. Must be called via wx.CallAfter."""
        try:
            if self._tray_icon:
                self._tray_icon.RemoveIcon()
                self._tray_icon.Destroy()
                self._tray_icon = None
                print("[LauncherTray] Tray icon hidden")
        except Exception as e:
            print(f"[LauncherTray] Error destroying tray icon: {e}")

    def _on_dclick(self, event):
        """Double-click on tray icon restores the launcher."""
        self._api.restore_launcher()

    def _on_right_click(self, event):
        """Right-click shows context menu."""
        try:
            import wx
            _ = self._api._
            menu = wx.Menu()
            restore_item = menu.Append(wx.ID_ANY, _("Back to Titan"))
            self._tray_icon.Bind(wx.EVT_MENU, lambda e: self._api.restore_launcher(), restore_item)
            self._tray_icon.PopupMenu(menu)
            menu.Destroy()
        except Exception as e:
            print(f"[LauncherTray] Error showing context menu: {e}")

    def _find_icon_path(self):
        """Find the taskbar icon path from the current skin settings."""
        try:
            base = _get_base_path()
            settings = self._api.load_settings()
            skin_name = settings.get('interface', {}).get('skin', '')

            if not skin_name:
                skin_name = 'dark_theme'

            skin_path = os.path.join(base, 'skins', skin_name)
            skin_ini = os.path.join(skin_path, 'skin.ini')

            if os.path.exists(skin_ini):
                config = configparser.ConfigParser()
                config.read(skin_ini, encoding='utf-8')
                if config.has_option('Icons', 'taskbar_icon'):
                    icon_rel = config.get('Icons', 'taskbar_icon')
                    icon_full = os.path.join(skin_path, icon_rel)
                    if os.path.exists(icon_full):
                        return icon_full

            # Fallback: try any skin that has the icon
            skins_dir = os.path.join(base, 'skins')
            if os.path.exists(skins_dir):
                for folder in os.listdir(skins_dir):
                    candidate = os.path.join(skins_dir, folder, 'icons', 'titan.png')
                    if os.path.exists(candidate):
                        return candidate
        except Exception as e:
            print(f"[LauncherTray] Error finding icon: {e}")
        return None


class LauncherAPI:
    """
    Clean API object passed to launchers.
    Exposes only the services allowed by the launcher's config.
    Settings, translation, sound, version, and speaker are ALWAYS available.
    """

    def __init__(self, config, services):
        self._config = config
        self._services = services
        self._shutdown_callbacks = []
        self._minimize_handler = None
        self._restore_handler = None
        self._minimized = False
        self._tray = _LauncherTrayIcon(self)

        # === ALWAYS AVAILABLE (regardless of config) ===

        # Settings access
        self.get_setting = services['settings'].get_setting
        self.set_setting = services['settings'].set_setting
        self.load_settings = services['settings'].load_settings
        self.save_settings = services['settings'].save_settings

        # Translation
        self._ = services['translation_func']
        self.set_language = services['translation'].set_language
        self.get_available_languages = services['translation'].get_available_languages
        self.language_code = services['translation'].language_code

        # Sound - FULL access to TCE sound system
        sound = services['sound']
        self.play_sound = sound.play_sound
        self.play_startup_sound = sound.play_startup_sound
        self.play_connecting_sound = sound.play_connecting_sound
        self.play_focus_sound = sound.play_focus_sound
        self.play_select_sound = sound.play_select_sound
        self.play_statusbar_sound = sound.play_statusbar_sound
        self.play_applist_sound = sound.play_applist_sound
        self.play_endoflist_sound = sound.play_endoflist_sound
        self.play_error_sound = sound.play_error_sound
        self.play_dialog_sound = sound.play_dialog_sound
        self.play_dialogclose_sound = sound.play_dialogclose_sound
        self.play_loop_sound = sound.play_loop_sound
        self.stop_loop_sound = sound.stop_loop_sound
        self.set_sound_theme = sound.set_theme
        self.set_sound_theme_volume = sound.set_sound_theme_volume
        self.play_voice_message = sound.play_voice_message
        self.pause_voice_message = sound.pause_voice_message
        self.resume_voice_message = sound.resume_voice_message
        self.stop_voice_message = sound.stop_voice_message
        self.toggle_voice_message = sound.toggle_voice_message
        self.is_voice_message_playing = sound.is_voice_message_playing
        self.is_voice_message_paused = sound.is_voice_message_paused
        self.play_ai_tts = sound.play_ai_tts
        self.stop_ai_tts = sound.stop_ai_tts
        self.is_ai_tts_playing = sound.is_ai_tts_playing
        self.resource_path = sound.resource_path
        self.get_sfx_directory = sound.get_sfx_directory

        # Version info
        self.version = services['version']

        # Speaker (TTS)
        self.speaker = services['speaker']

        # Launcher's own directory path
        self.launcher_path = config.path

        # Reference to wx.App (needed if launcher wants to use wx dialogs)
        self.wx_app = services.get('wx_app', None)

        # Settings frame reference (for show_settings)
        self._settings_frame = services.get('settings_frame', None)

        # Hidden fallback frame for hosting IM windows when the launcher
        # does not pass its own parent window. TCE Titan-Net / Telegram /
        # EltenLink / IM modules all need a live wx parent; a launcher may
        # not use wx or may not want to expose its private window. Creating
        # the fallback lazily avoids touching wx in non-wx launchers.
        self._im_host_frame = None

        # Statusbar applet manager - full access
        self.statusbar_applet_manager = services.get('statusbar_applet_manager', None)

        # Titan IM module manager
        self.im_module_manager = services.get('im_module_manager', None)

        # Launcher-local translation helper
        self.load_translations = self._make_load_translations()

        # === CONDITIONAL: only if config allows ===

        # Applications
        if config.features.get('applications', True):
            app_mgr = services['app_manager']
            self.get_applications = app_mgr.get_applications
            self.open_application = app_mgr.open_application
            self.find_application_by_shortname = app_mgr.find_application_by_shortname
        else:
            self.get_applications = None
            self.open_application = None
            self.find_application_by_shortname = None

        # Games
        if config.features.get('games', True):
            game_mgr = services['game_manager']
            self.get_games = game_mgr.get_games
            self.get_games_by_platform = game_mgr.get_games_by_platform
            self.open_game = game_mgr.open_game
        else:
            self.get_games = None
            self.get_games_by_platform = None
            self.open_game = None

        # Titan IM (Titan-Net)
        if config.features.get('titan_im', True):
            self.titan_net_client = services.get('titan_net_client', None)
        else:
            self.titan_net_client = None

        # Help
        if config.features.get('help', True):
            self.show_help = services.get('help_func', None)
        else:
            self.show_help = None

        # Components
        if config.features.get('components', True):
            cm = services.get('component_manager')
            if cm:
                self.get_components = cm.get_components
                self.get_component_menu_functions = cm.get_component_menu_functions
            else:
                self.get_components = None
                self.get_component_menu_functions = None
        else:
            self.get_components = None
            self.get_component_menu_functions = None

        # Notifications
        if config.features.get('notifications', True):
            self.notifications = services.get('notifications', None)
        else:
            self.notifications = None

        # Invisible UI
        if config.features.get('invisible_ui', False):
            self.invisible_ui = services.get('invisible_ui', None)
        else:
            self.invisible_ui = None

        # === ADDITIONAL FEATURES (matching GUI/IUI functionality) ===

        # Controller vibrations
        try:
            from src.controller.controller_vibrations import (
                vibrate_cursor_move, vibrate_menu_open, vibrate_menu_close,
                vibrate_selection, vibrate_focus_change, vibrate_error,
                vibrate_notification, vibrate_startup,
                set_vibration_enabled, set_vibration_strength,
                get_controller_info, refresh_controllers, test_vibration
            )
            self.vibrate_cursor_move = vibrate_cursor_move
            self.vibrate_menu_open = vibrate_menu_open
            self.vibrate_menu_close = vibrate_menu_close
            self.vibrate_selection = vibrate_selection
            self.vibrate_focus_change = vibrate_focus_change
            self.vibrate_error = vibrate_error
            self.vibrate_notification = vibrate_notification
            self.vibrate_startup = vibrate_startup
            self.set_vibration_enabled = set_vibration_enabled
            self.set_vibration_strength = set_vibration_strength
            self.get_controller_info = get_controller_info
            self.refresh_controllers = refresh_controllers
            self.test_vibration = test_vibration
        except ImportError:
            self.vibrate_cursor_move = lambda: None
            self.vibrate_menu_open = lambda: None
            self.vibrate_menu_close = lambda: None
            self.vibrate_selection = lambda: None
            self.vibrate_focus_change = lambda: None
            self.vibrate_error = lambda: None
            self.vibrate_notification = lambda: None
            self.vibrate_startup = lambda: None
            self.set_vibration_enabled = lambda enabled: None
            self.set_vibration_strength = lambda strength: None
            self.get_controller_info = lambda: None
            self.refresh_controllers = lambda: None
            self.test_vibration = lambda: None

        # Stereo speech
        try:
            from src.titan_core.stereo_speech import get_stereo_speech, speak_stereo, stop_stereo_speech
            self.get_stereo_speech = get_stereo_speech
            self.speak_stereo = speak_stereo
            self.stop_stereo_speech = stop_stereo_speech
        except ImportError:
            self.get_stereo_speech = lambda: None
            self.speak_stereo = lambda text, **kw: None
            self.stop_stereo_speech = lambda: None

        # Window switcher
        try:
            from src.ui.window_switcher import show_window_switcher, register_window, unregister_window
            self.show_window_switcher = lambda parent=None: show_window_switcher(parent=parent)
            self.register_window = register_window
            self.unregister_window = unregister_window
        except ImportError:
            self.show_window_switcher = lambda parent=None: None
            self.register_window = lambda *a, **kw: None
            self.unregister_window = lambda *a, **kw: None

        # Shutdown dialog
        try:
            from src.ui.shutdown_question import show_shutdown_dialog
            self.show_shutdown_dialog = show_shutdown_dialog
        except ImportError:
            self.show_shutdown_dialog = lambda: None

        # Update checker
        try:
            from src.system.updater import check_for_updates_on_startup
            self._check_for_updates_on_startup = check_for_updates_on_startup
        except ImportError:
            self._check_for_updates_on_startup = lambda parent=None: False

    def check_for_updates(self):
        """Check for application updates. Shows update dialog if available."""
        try:
            return self._check_for_updates_on_startup()
        except Exception as e:
            print(f"[LauncherAPI] Error checking for updates: {e}")
            return False

    def start_invisible_ui(self):
        """Start the Invisible UI listener (tilde key toggle).
        Call this after the launcher window is shown."""
        if self.invisible_ui:
            try:
                self.invisible_ui.start_listening()
                print("[LauncherAPI] Invisible UI listening started")
            except Exception as e:
                print(f"[LauncherAPI] Error starting Invisible UI: {e}")

    def stop_invisible_ui(self):
        """Stop the Invisible UI listener."""
        if self.invisible_ui:
            try:
                self.invisible_ui.stop_listening()
                print("[LauncherAPI] Invisible UI listening stopped")
            except Exception as e:
                print(f"[LauncherAPI] Error stopping Invisible UI: {e}")

    def show_settings(self):
        """Show the TCE Settings window. Always available."""
        if self._settings_frame:
            try:
                import wx
                wx.CallAfter(self._settings_frame.Show)
                wx.CallAfter(self._settings_frame.Raise)
            except Exception as e:
                print(f"[LauncherAPI] Error showing settings: {e}")

    def register_shutdown_callback(self, callback):
        """Register a callback to be called when the launcher is being shut down."""
        self._shutdown_callbacks.append(callback)

    def request_exit(self):
        """Request TCE to exit. The launcher should call this when the user wants to quit."""
        try:
            import wx
            if wx.GetApp():
                wx.CallAfter(wx.GetApp().ExitMainLoop)
        except Exception as e:
            print(f"[LauncherAPI] Error requesting exit: {e}")

    def register_minimize_handler(self, callback):
        """Register a callback to minimize the launcher window.
        The launcher should provide its own minimize logic (e.g., iconify/withdraw)."""
        self._minimize_handler = callback

    def register_restore_handler(self, callback):
        """Register a callback to restore the launcher window from minimized state."""
        self._restore_handler = callback

    def minimize_launcher(self):
        """Minimize the launcher window and show a tray icon.
        Only works if the launcher registered a minimize handler."""
        if self._minimize_handler:
            try:
                self._minimize_handler()
                self._minimized = True
                # Show tray icon (must happen on wx thread)
                try:
                    import wx
                    wx.CallAfter(self._tray.show)
                except Exception as e:
                    print(f"[LauncherAPI] Error showing tray icon: {e}")
                # Play minimize sound
                self.play_sound('ui/minimalize.ogg')
                return True
            except Exception as e:
                print(f"[LauncherAPI] Error minimizing launcher: {e}")
        return False

    def restore_launcher(self):
        """Restore the launcher window and remove the tray icon."""
        if self._restore_handler:
            try:
                self._restore_handler()
                self._minimized = False
                # Hide tray icon (must happen on wx thread)
                try:
                    import wx
                    wx.CallAfter(self._tray.hide)
                except Exception as e:
                    print(f"[LauncherAPI] Error hiding tray icon: {e}")
                # Play restore sound
                self.play_sound('ui/normalize.ogg')
                return True
            except Exception as e:
                print(f"[LauncherAPI] Error restoring launcher: {e}")
        return False

    @property
    def is_minimized(self):
        """Check if the launcher is currently minimized."""
        return self._minimized

    @property
    def supports_minimize(self):
        """Check if the launcher supports minimizing."""
        return self._minimize_handler is not None

    def has_feature(self, feature_name):
        """Check if a specific feature is enabled for this launcher."""
        return self._config.features.get(feature_name, False)

    # --- Titan IM communicator openers ---

    def _get_im_parent(self):
        """Return a live wx parent window for IM dialogs.

        Priority:
          1. The TCE Settings frame (created up-front in launcher mode).
          2. Any already-visible top-level wx window (e.g. the launcher's
             own main window, if it uses wx).
          3. A lazily-created hidden host frame owned by the API.

        IM login/chat windows (Titan-Net, Telegram, EltenLink, Messenger,
        WhatsApp, third-party IM modules) all need a valid parent to host
        modal dialogs and get top-level lifecycle events. Without a parent
        wx will silently drop modal dialogs, which is what the user sees
        as "can't log in when using a launcher".
        """
        try:
            import wx
        except Exception:
            return None

        # 1. Settings frame (always created in launcher mode)
        if self._settings_frame is not None:
            try:
                if bool(self._settings_frame):
                    return self._settings_frame
            except Exception:
                pass
            # stale reference — forget it
            self._settings_frame = None

        # 2. First visible top-level window
        try:
            for w in wx.GetTopLevelWindows():
                try:
                    if w and w.IsShown() and w is not self._im_host_frame:
                        return w
                except Exception:
                    continue
        except Exception:
            pass

        # 3. Lazy hidden host frame
        if self._im_host_frame is None:
            try:
                self._im_host_frame = wx.Frame(None, title="TCE IM Host",
                                               size=(1, 1))
                self._im_host_frame.Move(-10000, -10000)
                # Hidden but realised — wx needs that for ShowModal parents.
                self._im_host_frame.Hide()
            except Exception as e:
                print(f"[LauncherAPI] Failed to create IM host frame: {e}")
                return None
        return self._im_host_frame

    def open_telegram(self):
        """Open Telegram login dialog. Requires titan_im feature.

        Works even when no main TCE GUI is running: a hidden parent is
        provided automatically if the launcher did not supply one.
        """
        if not self.has_feature('titan_im'):
            return
        try:
            import wx
            def _open():
                try:
                    from src.network.telegram_gui import show_telegram_login
                    parent = self._get_im_parent()
                    show_telegram_login(parent)
                except Exception as e:
                    print(f"[LauncherAPI] Error opening Telegram: {e}")
                    import traceback
                    traceback.print_exc()
            wx.CallAfter(_open)
        except Exception as e:
            print(f"[LauncherAPI] Error opening Telegram: {e}")

    def open_messenger(self):
        """Open Facebook Messenger window. Requires titan_im feature."""
        if not self.has_feature('titan_im'):
            return
        try:
            import wx
            def _open():
                try:
                    from src.network import messenger_webview
                    parent = self._get_im_parent()
                    messenger_webview.show_messenger_webview(parent)
                except Exception as e:
                    print(f"[LauncherAPI] Error opening Messenger: {e}")
                    import traceback
                    traceback.print_exc()
            wx.CallAfter(_open)
        except Exception as e:
            print(f"[LauncherAPI] Error opening Messenger: {e}")

    def open_whatsapp(self):
        """Open WhatsApp window. Requires titan_im feature."""
        if not self.has_feature('titan_im'):
            return
        try:
            import wx
            def _open():
                try:
                    from src.network import whatsapp_webview
                    parent = self._get_im_parent()
                    whatsapp_webview.show_whatsapp_webview(parent)
                except Exception as e:
                    print(f"[LauncherAPI] Error opening WhatsApp: {e}")
                    import traceback
                    traceback.print_exc()
            wx.CallAfter(_open)
        except Exception as e:
            print(f"[LauncherAPI] Error opening WhatsApp: {e}")

    def open_titannet(self):
        """Open Titan-Net: login dialog, then main window on success.

        Previously this only showed the login dialog — when the user
        successfully logged in from a launcher, the dialog closed and
        nothing happened. Now the main chat window is opened on success,
        matching the behaviour of the main TCE GUI.
        """
        if not self.has_feature('titan_im') or not self.titan_net_client:
            return
        try:
            import wx
            def _open():
                try:
                    from src.network.titan_net_gui import (
                        show_login_dialog,
                        show_titan_net_window,
                    )
                    parent = self._get_im_parent()
                    result = show_login_dialog(parent, self.titan_net_client)
                    logged_in = False
                    if isinstance(result, tuple) and result:
                        logged_in = bool(result[0])
                    if logged_in:
                        try:
                            show_titan_net_window(parent, self.titan_net_client)
                        except Exception as e:
                            print(f"[LauncherAPI] Error opening Titan-Net main window: {e}")
                            import traceback
                            traceback.print_exc()
                except Exception as e:
                    print(f"[LauncherAPI] Error opening Titan-Net: {e}")
                    import traceback
                    traceback.print_exc()
            wx.CallAfter(_open)
        except Exception as e:
            print(f"[LauncherAPI] Error opening Titan-Net: {e}")

    def open_eltenlink(self):
        """Open EltenLink login dialog. Requires titan_im feature."""
        if not self.has_feature('titan_im'):
            return
        try:
            import wx
            def _open():
                try:
                    from src.eltenlink_client.elten_gui import show_elten_login
                    parent = self._get_im_parent()
                    show_elten_login(parent)
                except Exception as e:
                    print(f"[LauncherAPI] Error opening EltenLink: {e}")
                    import traceback
                    traceback.print_exc()
            wx.CallAfter(_open)
        except Exception as e:
            print(f"[LauncherAPI] Error opening EltenLink: {e}")

    def open_im_module(self, name_or_id):
        """Open a third-party Titan IM module by display name or id.

        Dispatches to im_module_manager.open_module with a valid parent
        window resolved via _get_im_parent, so IM modules work from any
        launcher even when no main TCE GUI is running. Returns True if
        the module was found and open() was invoked.
        """
        if not self.has_feature('titan_im') or not self.im_module_manager:
            return False
        try:
            import wx
        except Exception:
            return False
        done = {'ok': False}
        def _open():
            try:
                parent = self._get_im_parent()
                done['ok'] = bool(
                    self.im_module_manager.open_module(name_or_id, parent)
                )
            except Exception as e:
                print(f"[LauncherAPI] Error opening IM module '{name_or_id}': {e}")
                import traceback
                traceback.print_exc()
        # open_module is synchronous but can pop dialogs, so marshal onto
        # the wx main thread like the other openers.
        wx.CallAfter(_open)
        return True

    def force_exit(self):
        """Force shutdown TCE - stops all services and calls os._exit(0).
        Use this when the user wants to quit entirely (Exit button, Alt+F4).
        Matches the shutdown behavior of GUI, IUI, and Klango mode."""
        print("[LauncherAPI] Force exit requested")

        def _shutdown():
            try:
                # Stop invisible UI
                try:
                    self.stop_invisible_ui()
                except Exception:
                    pass

                # Stop system hooks
                try:
                    from src.titan_core.tce_system import stop_system_hooks
                    stop_system_hooks()
                    print("[LauncherAPI] System hooks stopped")
                except Exception as e:
                    print(f"[LauncherAPI] Warning: Error stopping system hooks: {e}")

                print("[LauncherAPI] Application terminating now.")
                os._exit(0)
            except Exception as e:
                print(f"[LauncherAPI] Critical error during shutdown: {e}")
                os._exit(1)

        shutdown_thread = threading.Thread(target=_shutdown, daemon=True)
        shutdown_thread.start()

    def _make_load_translations(self):
        """Create a helper that loads translations from the launcher's own languages/ dir."""
        def load_translations(domain='launcher'):
            """Load translations from launcher's own languages/ directory.

            Args:
                domain: gettext domain name (default 'launcher')

            Returns:
                Translation function _() for the launcher's own strings

            Usage in launcher init.py:
                _ = api.load_translations()  # loads from languages/{lang}/LC_MESSAGES/launcher.mo
                # or with custom domain:
                _ = api.load_translations('my_launcher')
            """
            locale_dir = os.path.join(self.launcher_path, 'languages')
            try:
                lang = self.language_code
            except Exception:
                lang = 'pl'
            try:
                trans = _gettext.translation(domain, locale_dir, languages=[lang], fallback=True)
                return trans.gettext
            except Exception:
                return lambda x: x
        return load_translations


class LauncherManager:
    """
    Manages loading and running third-party launcher interfaces.
    Only one launcher can run at a time.
    """

    def __init__(self):
        self.launchers = {}          # folder_name -> LauncherConfig
        self.active_launcher = None  # folder_name of running launcher
        self.active_module = None
        self.active_api = None
        self._scan_launchers()

    def _scan_launchers(self):
        """Scan data/launchers/ directory for available launchers."""
        project_root = _get_base_path()
        launchers_dir = os.path.join(project_root, 'data', 'launchers')

        if not os.path.exists(launchers_dir):
            print("[LauncherManager] No data/launchers/ directory found")
            return

        for folder_name in os.listdir(launchers_dir):
            launcher_path = os.path.join(launchers_dir, folder_name)
            if os.path.isdir(launcher_path) and folder_name != '.DS_Store':
                config_path = os.path.join(launcher_path, '__launcher__.TCE')
                if os.path.exists(config_path):
                    config = LauncherConfig(launcher_path, folder_name)
                    self.launchers[folder_name] = config
                    print(f"[LauncherManager] Found launcher: {config.name} ({folder_name}) "
                          f"[{'enabled' if config.enabled else 'disabled'}]")
                else:
                    print(f"[LauncherManager] Skipping {folder_name}: no __launcher__.TCE")

    def get_available_launchers(self):
        """Get list of all discovered launchers."""
        return list(self.launchers.values())

    def get_enabled_launchers(self):
        """Get list of enabled launchers."""
        return [lc for lc in self.launchers.values() if lc.enabled]

    def get_launcher_by_name(self, folder_name):
        """Get a launcher config by its folder name."""
        return self.launchers.get(folder_name, None)

    def is_launcher_running(self):
        """Check if a launcher is currently running."""
        return self.active_launcher is not None

    def start_launcher(self, folder_name, services):
        """
        Start a launcher by folder name.

        Args:
            folder_name: The launcher's directory name under data/launchers/
            services: Dict of services to expose via LauncherAPI

        Returns:
            True if launcher started successfully, False otherwise.
        """
        if self.active_launcher is not None:
            print(f"[LauncherManager] Cannot start '{folder_name}': "
                  f"launcher '{self.active_launcher}' is already running")
            return False

        config = self.launchers.get(folder_name)
        if config is None:
            print(f"[LauncherManager] Launcher '{folder_name}' not found")
            return False

        if not config.enabled:
            print(f"[LauncherManager] Launcher '{folder_name}' is disabled")
            return False

        # Find init file
        init_path = self._find_init_file(config.path)
        if init_path is None:
            print(f"[LauncherManager] No init.py/init.pyc found in {config.path}")
            return False

        # Load the launcher module
        module = self._load_module(init_path, folder_name)
        if module is None:
            print(f"[LauncherManager] Failed to load launcher module: {folder_name}")
            return False

        # Verify entry point exists
        if not hasattr(module, 'start'):
            print(f"[LauncherManager] Launcher '{folder_name}' has no start() function")
            return False

        # Create the API object
        api = LauncherAPI(config, services)

        # Store state
        self.active_launcher = folder_name
        self.active_module = module
        self.active_api = api

        # Call start(api)
        try:
            print(f"[LauncherManager] Starting launcher: {config.name}")
            module.start(api)
            print(f"[LauncherManager] Launcher '{config.name}' start() returned")
            return True
        except Exception as e:
            print(f"[LauncherManager] Error starting launcher '{folder_name}': {e}")
            import traceback
            traceback.print_exc()
            self.active_launcher = None
            self.active_module = None
            self.active_api = None
            return False

    def stop_launcher(self):
        """Stop the currently running launcher."""
        if self.active_launcher is None:
            return

        folder_name = self.active_launcher
        print(f"[LauncherManager] Stopping launcher: {folder_name}")

        # Call shutdown callbacks registered via API
        if self.active_api:
            for callback in self.active_api._shutdown_callbacks:
                try:
                    callback()
                except Exception as e:
                    print(f"[LauncherManager] Error in shutdown callback: {e}")

        # Call module's shutdown() if it exists
        if self.active_module and hasattr(self.active_module, 'shutdown'):
            try:
                self.active_module.shutdown()
            except Exception as e:
                print(f"[LauncherManager] Error in launcher shutdown(): {e}")

        self.active_launcher = None
        self.active_module = None
        self.active_api = None
        print(f"[LauncherManager] Launcher '{folder_name}' stopped")

    def _find_init_file(self, launcher_path):
        """Find the init file in the launcher directory."""
        py_path = os.path.join(launcher_path, 'init.py')
        pyc_path = os.path.join(launcher_path, 'init.pyc')

        py_exists = os.path.exists(py_path)
        pyc_exists = os.path.exists(pyc_path)

        if py_exists and pyc_exists:
            if os.path.getmtime(pyc_path) >= os.path.getmtime(py_path):
                return pyc_path
            else:
                return py_path
        elif py_exists:
            return py_path
        elif pyc_exists:
            return pyc_path
        return None

    def _load_module(self, init_path, launcher_name):
        """Load a launcher module from file."""
        try:
            launcher_dir = os.path.dirname(init_path)
            if launcher_dir not in sys.path:
                sys.path.insert(0, launcher_dir)

            # In compiled mode, add _internal/Lib/site-packages to sys.path
            # so launchers can import any installed packages (PyQt5, etc.)
            if _is_frozen():
                base = _get_base_path()
                for subdir in ['_internal/Lib/site-packages', '_internal/Lib', '_internal']:
                    sp = os.path.join(base, subdir)
                    if os.path.isdir(sp) and sp not in sys.path:
                        sys.path.insert(0, sp)

            # Add launcher's library paths for bundled dependencies
            # Config: libs = lib, vendor in [launcher] section of __launcher__.TCE
            # Default: lib/ if exists
            _lib_dirs = ["lib"]
            _config_path = os.path.join(launcher_dir, '__launcher__.TCE')
            if os.path.isfile(_config_path):
                _cfg = configparser.ConfigParser()
                try:
                    _cfg.read(_config_path, encoding='utf-8')
                    _libs_str = _cfg.get('launcher', 'libs', fallback='')
                    if _libs_str.strip():
                        _lib_dirs = [d.strip() for d in _libs_str.split(',') if d.strip()]
                except Exception:
                    pass
            for _ld in _lib_dirs:
                _full_lib = os.path.join(launcher_dir, _ld)
                if os.path.isdir(_full_lib) and _full_lib not in sys.path:
                    sys.path.insert(0, _full_lib)

            module_name = f'launcher_{launcher_name}'

            if _is_frozen() and init_path.endswith('.py'):
                # Frozen mode: use exec()
                with open(init_path, 'r', encoding='utf-8') as f:
                    code = f.read()

                module = types.ModuleType(module_name)
                module.__file__ = init_path
                module.__name__ = module_name
                exec(compile(code, init_path, 'exec'), module.__dict__)
                sys.modules[module_name] = module
                return module
            else:
                # Dev mode or .pyc: use importlib
                spec = importlib.util.spec_from_file_location(module_name, init_path)
                if spec is None:
                    return None
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                return module

        except Exception as e:
            print(f"[LauncherManager] Failed to load module {launcher_name}: {e}")
            import traceback
            traceback.print_exc()
            return None
