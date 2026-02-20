"""
StatusbarAppletManager - manages statusbar applets

This module provides functionality to load and manage statusbar applets from the
data/statusbar_applets/ directory. Applets can provide dynamic status information
that appears in the status bar across all interface modes (GUI, IUI, Klango).
"""

import os
import sys
import json
import gettext as _gettext
import importlib.util
import threading
import time
from typing import Dict, List, Optional, Any
from src.platform_utils import get_base_path as get_project_root


class StatusbarAppletManager:
    """
    Manager for statusbar applets.

    Loads applets from data/statusbar_applets/ directory and provides
    thread-safe access to applet text and activation functions.
    """

    # Built-in statusbar item keys
    BUILTIN_ITEMS = ['time', 'battery', 'volume', 'network']

    def __init__(self):
        """Initialize the StatusbarAppletManager."""
        self.applets: Dict[str, Dict[str, Any]] = {}
        self.cache_lock = threading.Lock()
        self._auto_update_running = False
        self._auto_update_thread = None
        # Built-in status cache (Clock, Battery, Volume, Network)
        self._builtin_cache: Dict[str, str] = {
            'time': '',
            'battery': '',
            'volume': '',
            'network': '',
        }
        self._update_builtin_cache()
        self.load_applets()

    def load_applets(self):
        """
        Load all applets from data/statusbar_applets/ directory.

        Each applet should be in its own subdirectory with:
        - applet.json: metadata file
        - main.py: implementation file with required functions
        """
        try:
            project_root = get_project_root()
            applets_dir = os.path.join(project_root, 'data', 'statusbar_applets')

            # Create directory if it doesn't exist
            if not os.path.exists(applets_dir):
                os.makedirs(applets_dir)
                print(f"Created statusbar applets directory: {applets_dir}")
                return

            # Scan for applets
            for applet_name in os.listdir(applets_dir):
                applet_dir = os.path.join(applets_dir, applet_name)

                # Skip if not a directory
                if not os.path.isdir(applet_dir):
                    continue

                # Try to load applet
                try:
                    self._load_single_applet(applet_name, applet_dir)
                except Exception as e:
                    print(f"Error loading statusbar applet '{applet_name}': {e}")
                    import traceback
                    traceback.print_exc()

            print(f"Loaded {len(self.applets)} statusbar applet(s): {list(self.applets.keys())}")

        except Exception as e:
            print(f"Error loading statusbar applets: {e}")
            import traceback
            traceback.print_exc()

    def _load_single_applet(self, applet_name: str, applet_dir: str):
        """
        Load a single applet from its directory.

        Args:
            applet_name: Name of the applet (directory name)
            applet_dir: Full path to applet directory
        """
        # Check for required files
        json_path = os.path.join(applet_dir, 'applet.json')
        main_py_path = os.path.join(applet_dir, 'main.py')

        if not os.path.exists(json_path):
            print(f"Skipping applet '{applet_name}': missing applet.json")
            return

        if not os.path.exists(main_py_path):
            print(f"Skipping applet '{applet_name}': missing main.py")
            return

        # Load metadata from applet.json
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
        except Exception as e:
            print(f"Error reading applet.json for '{applet_name}': {e}")
            return

        # Load Python module
        try:
            spec = importlib.util.spec_from_file_location(
                f"statusbar_applets.{applet_name}.main",
                main_py_path
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module

            # Inject local translations from applet's own languages/ dir
            applet_locale_dir = os.path.join(applet_dir, 'languages')
            if os.path.isdir(applet_locale_dir):
                try:
                    from src.settings.settings import get_setting
                    lang = get_setting('language', 'pl')
                    trans = _gettext.translation(applet_name, applet_locale_dir, languages=[lang], fallback=True)
                    module._ = trans.gettext
                except Exception:
                    module._ = lambda x: x
            else:
                module._ = lambda x: x

            spec.loader.exec_module(module)
        except Exception as e:
            print(f"Error loading main.py for '{applet_name}': {e}")
            import traceback
            traceback.print_exc()
            return

        # Verify required functions exist
        if not hasattr(module, 'get_statusbar_item_info'):
            print(f"Applet '{applet_name}' missing get_statusbar_item_info() function")
            return

        if not hasattr(module, 'get_statusbar_item_text'):
            print(f"Applet '{applet_name}' missing get_statusbar_item_text() function")
            return

        # Get applet info
        try:
            applet_info = module.get_statusbar_item_info()
        except Exception as e:
            print(f"Error calling get_statusbar_item_info() for '{applet_name}': {e}")
            return

        # Get display name from various sources
        display_name = applet_info.get('name')
        if not display_name:
            # Try metadata
            from src.settings.settings import get_setting
            language = get_setting('language', 'pl')
            display_name = metadata.get(f'name_{language}', metadata.get('name', applet_name))

        # Get update interval (default 5 seconds)
        update_interval = applet_info.get('update_interval', metadata.get('update_interval', 5))

        # Store applet data
        self.applets[applet_name] = {
            'module': module,
            'metadata': metadata,
            'info': {
                'name': display_name,
                'update_interval': update_interval
            },
            'cache': {
                'text': 'Loading...',
                'error': False
            }
        }

        # Initialize cache with first text
        self.update_applet_cache(applet_name)

        print(f"Loaded statusbar applet: {applet_name} ('{display_name}')")

    def get_applet_names(self) -> List[str]:
        """
        Get list of loaded applet names.

        Returns:
            List of applet names (directory names)
        """
        return list(self.applets.keys())

    def get_applet_text(self, name: str) -> str:
        """
        Get cached text for an applet (thread-safe).

        Args:
            name: Applet name

        Returns:
            Cached text string for the applet
        """
        if name not in self.applets:
            return f"Applet '{name}' not found"

        with self.cache_lock:
            return self.applets[name]['cache']['text']

    def update_applet_cache(self, name: str):
        """
        Update cached text for an applet by calling its get_statusbar_item_text().

        This method is thread-safe and includes timeout protection.

        Args:
            name: Applet name
        """
        if name not in self.applets:
            return

        applet = self.applets[name]
        module = applet['module']

        try:
            # Call get_statusbar_item_text() with timeout protection
            text = self._call_with_timeout(
                module.get_statusbar_item_text,
                timeout=2.0,
                default="Error: Timeout"
            )

            # Update cache
            with self.cache_lock:
                applet['cache']['text'] = text
                applet['cache']['error'] = False

        except Exception as e:
            print(f"Error updating cache for applet '{name}': {e}")
            with self.cache_lock:
                applet['cache']['text'] = f"{applet['info']['name']}: Error"
                applet['cache']['error'] = True

    def activate_applet(self, name: str, parent_frame=None):
        """
        Activate an applet by calling its on_statusbar_item_activate() function.

        Args:
            name: Applet name
            parent_frame: Parent wx.Frame for GUI dialogs (None for console mode)
        """
        if name not in self.applets:
            print(f"Cannot activate applet '{name}': not found")
            return

        applet = self.applets[name]
        module = applet['module']

        # Check if activation function exists
        if not hasattr(module, 'on_statusbar_item_activate'):
            print(f"Applet '{name}' has no activation function")
            return

        try:
            # Call activation function
            module.on_statusbar_item_activate(parent_frame)
        except Exception as e:
            print(f"Error activating applet '{name}': {e}")
            import traceback
            traceback.print_exc()

    def get_applet_update_interval(self, name: str) -> int:
        """
        Get update interval for an applet.

        Args:
            name: Applet name

        Returns:
            Update interval in seconds (default 5)
        """
        if name not in self.applets:
            return 5

        return self.applets[name]['info']['update_interval']

    def _update_builtin_cache(self):
        """Update built-in statusbar items (Clock, Battery, Volume, Network)."""
        try:
            from src.system.notifications import (
                get_current_time, get_battery_status,
                get_volume_level, get_network_status
            )
            with self.cache_lock:
                self._builtin_cache['time'] = get_current_time()
                self._builtin_cache['battery'] = get_battery_status()
                self._builtin_cache['volume'] = get_volume_level()
                self._builtin_cache['network'] = get_network_status()
        except Exception as e:
            print(f"[StatusbarAppletManager] Error updating built-in cache: {e}")

    def get_builtin_items(self) -> Dict[str, str]:
        """Get built-in statusbar items as a dict (thread-safe).

        Returns:
            Dict with keys: 'time', 'battery', 'volume', 'network'
        """
        with self.cache_lock:
            return dict(self._builtin_cache)

    def get_statusbar_items(self) -> List[str]:
        """Get all statusbar items as a formatted list (built-in + applets).

        Returns a list like the main GUI statusbar:
        [Clock, Battery, Volume, Network, applet1_text, applet2_text, ...]
        """
        from src.titan_core.translation import get_translation_function
        _ = get_translation_function()

        with self.cache_lock:
            items = [
                _("Clock: {}").format(self._builtin_cache.get('time', '')),
                _("Battery level: {}").format(self._builtin_cache.get('battery', '')),
                _("Volume: {}").format(self._builtin_cache.get('volume', '')),
                self._builtin_cache.get('network', ''),
            ]

        # Add applet texts
        for name in self.get_applet_names():
            items.append(self.get_applet_text(name))

        return items

    def get_all_applet_texts(self) -> Dict[str, str]:
        """
        Get all applet texts as a dict.

        Returns:
            Dict mapping applet name to its cached text
        """
        return {name: self.get_applet_text(name) for name in self.get_applet_names()}

    def start_auto_update(self):
        """Start background thread to auto-update applet caches.
        Useful for launchers that don't have their own update loop."""
        if self._auto_update_running:
            return
        self._auto_update_running = True
        self._auto_update_thread = threading.Thread(target=self._auto_update_loop, daemon=True)
        self._auto_update_thread.start()
        print("[StatusbarAppletManager] Auto-update started")

    def stop_auto_update(self):
        """Stop the auto-update background thread."""
        self._auto_update_running = False
        if self._auto_update_thread:
            self._auto_update_thread = None
        print("[StatusbarAppletManager] Auto-update stopped")

    def _auto_update_loop(self):
        """Background loop updating built-in items and applets at configured intervals."""
        last_update: Dict[str, float] = {}
        last_builtin_update = 0.0
        while self._auto_update_running:
            now = time.time()

            # Update built-in items every 5 seconds
            if now - last_builtin_update >= 5:
                try:
                    self._update_builtin_cache()
                except Exception as e:
                    print(f"[StatusbarAppletManager] Built-in update error: {e}")
                last_builtin_update = now

            # Update applets at their own intervals
            for name in self.get_applet_names():
                interval = self.get_applet_update_interval(name)
                last = last_update.get(name, 0)
                if now - last >= interval:
                    try:
                        self.update_applet_cache(name)
                    except Exception as e:
                        print(f"[StatusbarAppletManager] Auto-update error for '{name}': {e}")
                    last_update[name] = now
            time.sleep(1)

    def _call_with_timeout(self, func, timeout: float = 2.0, default: str = "Timeout"):
        """
        Call a function with timeout protection.

        Args:
            func: Function to call
            timeout: Timeout in seconds
            default: Default return value on timeout

        Returns:
            Function result or default on timeout
        """
        result = [default]
        exception = [None]

        def target():
            try:
                result[0] = func()
            except Exception as e:
                exception[0] = e

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(timeout)

        if thread.is_alive():
            print(f"Warning: Function call timed out after {timeout}s")
            return default

        if exception[0]:
            raise exception[0]

        return result[0]
