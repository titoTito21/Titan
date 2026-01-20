# -*- coding: utf-8 -*-
import os
import sys
import importlib.util
import py_compile
import shutil
import platform
import configparser


def _log_to_file(message):
    """Log to file for debugging compiled version."""
    try:
        log_path = os.path.join(os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(__file__), 'component_debug.log')
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f"{message}\n")
    except:
        pass


def _get_base_path():
    """Get base path for resources, supporting PyInstaller and Nuitka."""
    # For both PyInstaller and Nuitka, use executable directory
    # (data directories are placed next to exe for backward compatibility)
    if hasattr(sys, '_MEIPASS') or getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        # Development mode - get project root (2 levels up from src/titan_core/)
        return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def _is_frozen():
    """Check if running as compiled executable."""
    return hasattr(sys, '_MEIPASS') or getattr(sys, 'frozen', False)


class ComponentManager:
    def __init__(self, settings_frame=None, gui_app=None):
        self.components = []
        self.settings_frame = settings_frame
        self.gui_app = gui_app  # Reference to main GUI app for hooks
        self.component_menu_functions = {}
        self.component_states = {}
        self.component_friendly_names = {}
        self.component_gui_hooks = {}  # Hooks for GUI modifications
        self.component_klango_hooks = {}  # Hooks for Klango mode modifications
        self.load_components()

    def get_component_display_name(self, component_path, folder_name):
        config_path = os.path.join(component_path, '__component__.TCE')
        config = configparser.ConfigParser()
        try:
            config.read(config_path, encoding='utf-8')
            return config.get('component', 'name', fallback=folder_name)
        except Exception:
            return folder_name

    def load_components(self):
        """Loads all components from the data/components directory."""
        try:
            # Get project root directory (supports PyInstaller and Nuitka)
            project_root = _get_base_path()
            components_dir = os.path.join(project_root, 'data', 'components')

            _log_to_file(f"=== Component Loading Started ===")
            _log_to_file(f"Project root: {project_root}")
            _log_to_file(f"Components dir: {components_dir}")
            _log_to_file(f"Is frozen: {_is_frozen()}")
            _log_to_file(f"Components dir exists: {os.path.exists(components_dir)}")

            print(f"[ComponentManager] Project root: {project_root}")
            print(f"[ComponentManager] Components dir: {components_dir}")
            print(f"[ComponentManager] Is frozen: {_is_frozen()}")

            if not os.path.exists(components_dir):
                print(f"Components directory does not exist: {components_dir}")
                _log_to_file(f"ERROR: Components directory does not exist!")
                return

            # List contents
            try:
                contents = os.listdir(components_dir)
                _log_to_file(f"Components dir contents: {contents}")
            except Exception as e:
                _log_to_file(f"ERROR listing components dir: {e}")

            # Ensure components directory is in sys.path
            if components_dir not in sys.path:
                sys.path.insert(0, components_dir)

            # For frozen apps, ensure bundled modules are accessible
            if _is_frozen():
                # Add _internal directory (PyInstaller runtime files)
                internal_dir = os.path.join(os.path.dirname(sys.executable), '_internal')
                if os.path.exists(internal_dir) and internal_dir not in sys.path:
                    sys.path.insert(0, internal_dir)
                    print(f"[ComponentManager] Added _internal to sys.path: {internal_dir}")

                # Add _MEIPASS directory (PyInstaller bundled modules)
                if hasattr(sys, '_MEIPASS'):
                    meipass = sys._MEIPASS
                    if meipass not in sys.path:
                        sys.path.insert(0, meipass)
                        print(f"[ComponentManager] Added _MEIPASS to sys.path: {meipass}")

            for component_folder in os.listdir(components_dir):
                try:
                    component_path = os.path.join(components_dir, component_folder)
                    _log_to_file(f"Checking folder: {component_folder}")
                    if os.path.isdir(component_path) and component_folder != '.DS_Store':
                        try:
                            self.ensure_component_config(component_path, component_folder)
                            status = self.get_component_status(component_path)
                            self.component_states[component_folder] = status
                            _log_to_file(f"  Status: {status}")

                            friendly_name = self.get_component_display_name(component_path, component_folder)
                            self.component_friendly_names[component_folder] = friendly_name
                            _log_to_file(f"  Friendly name: {friendly_name}")

                            if status == 0:  # Load only enabled components
                                print(f"Loading component from folder: {component_folder}")
                                init_path = self.find_init_file(component_path)
                                _log_to_file(f"  Init path: {init_path}")
                                if init_path:
                                    _log_to_file(f"  Calling load_component...")
                                    self.load_component(init_path, component_folder)
                                    _log_to_file(f"  load_component returned")
                                else:
                                    print(f"No init file found in component: {component_folder}")
                                    _log_to_file(f"  ERROR: No init file found")
                            else:
                                print(f"Component {component_folder} is disabled.")
                                _log_to_file(f"  Component disabled")
                        except Exception as e:
                            print(f"Error processing component {component_folder}: {e}")
                            _log_to_file(f"  ERROR processing: {e}")
                            import traceback
                            traceback.print_exc()
                            # Continue with next component
                            continue
                except Exception as e:
                    print(f"Error accessing component folder: {e}")
                    _log_to_file(f"ERROR accessing folder: {e}")
                    continue

            _log_to_file(f"=== Component Loading Finished ===")
            _log_to_file(f"Total components loaded: {len(self.components)}")
            _log_to_file(f"Component states: {self.component_states}")
            _log_to_file(f"Friendly names: {self.component_friendly_names}")
        except Exception as e:
            print(f"Critical error in load_components: {e}")
            _log_to_file(f"CRITICAL ERROR: {e}")
            import traceback
            traceback.print_exc()

    def ensure_component_config(self, component_path, component_folder):
        config_path = os.path.join(component_path, '__component__.TCE')
        if not os.path.exists(config_path):
            config = configparser.ConfigParser()
            config['component'] = {
                'name': component_folder,
                'status': '0'
            }
            with open(config_path, 'w', encoding='utf-8') as configfile:
                config.write(configfile)

    def get_component_status(self, component_path):
        config_path = os.path.join(component_path, '__component__.TCE')
        config = configparser.ConfigParser()
        try:
            config.read(config_path)
            return int(config['component']['status'])
        except (KeyError, ValueError):
            return 1  # Default to disabled if error

    def toggle_component_status(self, component_folder):
        # Get project root directory (supports PyInstaller and Nuitka)
        project_root = _get_base_path()
        component_path = os.path.join(project_root, 'data', 'components', component_folder)
        config_path = os.path.join(component_path, '__component__.TCE')
        config = configparser.ConfigParser()
        config.read(config_path)
        
        current_status = int(config['component']['status'])
        new_status = 1 if current_status == 0 else 0
        config['component']['status'] = str(new_status)
        
        with open(config_path, 'w') as configfile:
            config.write(configfile)
            
        self.component_states[component_folder] = new_status
        return new_status

    def find_init_file(self, component_path):
        """
        Finds the init file in the component directory.
        Prefers .pyc if it's up-to-date.
        """
        py_path = os.path.join(component_path, 'init.py')
        pyc_path = os.path.join(component_path, 'init.pyc')

        py_exists = os.path.exists(py_path)
        pyc_exists = os.path.exists(pyc_path)

        if py_exists and pyc_exists:
            py_mtime = os.path.getmtime(py_path)
            pyc_mtime = os.path.getmtime(pyc_path)
            if pyc_mtime >= py_mtime:
                return pyc_path
            else:
                return py_path
        elif py_exists:
            return py_path
        elif pyc_exists:
            return pyc_path
        else:
            return None

    def load_component(self, init_path, component_name):
        """Loads a component from the given init file."""
        try:
            # For frozen apps, use exec() to load .py files directly
            # This allows access to bundled modules in sys.modules
            if _is_frozen():
                # Prefer .py file if available
                py_path = init_path
                if init_path.endswith('.pyc'):
                    py_path = init_path[:-1]  # Remove 'c' to get .py path
                    if os.path.exists(py_path):
                        init_path = py_path
                        _log_to_file(f"  Switched to .py file: {init_path}")

                # Add component's directory to sys.path
                component_dir = os.path.dirname(init_path)
                if component_dir not in sys.path:
                    sys.path.insert(0, component_dir)

                if init_path.endswith('.py'):
                    # Load .py file via exec()
                    print(f"[ComponentManager] Loading component via exec(): {component_name}")
                    _log_to_file(f"Loading via exec(): {component_name}")
                    try:
                        _log_to_file(f"  Reading file: {init_path}")
                        with open(init_path, 'r', encoding='utf-8') as f:
                            code = f.read()
                        _log_to_file(f"  File read, {len(code)} bytes")

                        # Create a module-like namespace
                        import types
                        module = types.ModuleType(component_name)
                        module.__file__ = init_path
                        module.__name__ = component_name

                        _log_to_file(f"  Executing code...")
                        # Execute the code in the module's namespace
                        exec(compile(code, init_path, 'exec'), module.__dict__)
                        _log_to_file(f"  Code executed successfully")

                        sys.modules[component_name] = module
                        self.components.append(module)
                    except Exception as e:
                        print(f"Failed to load component {component_name} via exec(): {e}")
                        _log_to_file(f"  FAILED to load: {e}")
                        import traceback
                        traceback.print_exc()
                        _log_to_file(f"  Traceback: {traceback.format_exc()}")
                        return
                else:
                    # Load .pyc file via importlib in frozen mode
                    print(f"[ComponentManager] Loading component via importlib (frozen): {component_name}")
                    _log_to_file(f"Loading via importlib (frozen): {component_name}")
                    try:
                        spec = importlib.util.spec_from_file_location(component_name, init_path)
                        if spec is None:
                            print(f"Could not create spec for component: {component_name}")
                            _log_to_file(f"  ERROR: Could not create spec")
                            return

                        module = importlib.util.module_from_spec(spec)
                        sys.modules[component_name] = module
                        spec.loader.exec_module(module)
                        self.components.append(module)
                        _log_to_file(f"  Loaded successfully via importlib")
                    except Exception as e:
                        print(f"Failed to load component {component_name} via importlib: {e}")
                        _log_to_file(f"  FAILED to load via importlib: {e}")
                        import traceback
                        traceback.print_exc()
                        _log_to_file(f"  Traceback: {traceback.format_exc()}")
                        return
            else:
                # Development mode - use importlib
                if init_path.endswith('.py'):
                    # Compile .py to .pyc if it's newer or .pyc doesn't exist
                    try:
                        pyc_path = init_path + 'c'
                        if not os.path.exists(pyc_path) or os.path.getmtime(init_path) > os.path.getmtime(pyc_path):
                            pyc_path = self.compile_to_pyc(init_path)
                            if not pyc_path:
                                print(f"Failed to compile file: {init_path}")
                                return
                        init_path = pyc_path
                    except Exception as e:
                        print(f"Error compiling component {component_name}: {e}")
                        # Try to load .py file directly
                        pass

                spec = importlib.util.spec_from_file_location(component_name, init_path)
                if spec is None:
                    print(f"Could not create spec for component: {component_name}")
                    return

                module = importlib.util.module_from_spec(spec)
                sys.modules[component_name] = module
                spec.loader.exec_module(module)
                self.components.append(module)

            print(f"Successfully loaded component: {component_name}")

            try:
                if hasattr(module, 'add_menu'):
                    print(f"Adding menu for component: {component_name}")
                    module.add_menu(self)
                else:
                    print(f"No menu to add for component: {component_name}")
            except Exception as e:
                print(f"Error adding menu for component {component_name}: {e}")

            try:
                if hasattr(module, 'add_settings'):
                    print(f"Adding settings for component: {component_name}")
                    module.add_settings(self.settings_frame)
                else:
                    print(f"No settings to add for component: {component_name}")
            except Exception as e:
                print(f"Error adding settings for component {component_name}: {e}")

            # New hook: add_settings_category for modular settings
            # Store the hook for later registration when settings_frame is available
            try:
                if hasattr(module, 'add_settings_category'):
                    print(f"Component {component_name} has settings category hook")
                else:
                    print(f"No settings category to add for component: {component_name}")
            except Exception as e:
                print(f"Error checking settings category for component {component_name}: {e}")

            # New hook: get_gui_hooks for GUI modifications
            try:
                if hasattr(module, 'get_gui_hooks'):
                    print(f"Getting GUI hooks for component: {component_name}")
                    hooks = module.get_gui_hooks()
                    if hooks:
                        self.component_gui_hooks[component_name] = hooks
                else:
                    print(f"No GUI hooks for component: {component_name}")
            except Exception as e:
                print(f"Error getting GUI hooks for component {component_name}: {e}")

            # New hook: get_klango_hooks for Klango mode modifications
            try:
                if hasattr(module, 'get_klango_hooks'):
                    print(f"Getting Klango hooks for component: {component_name}")
                    hooks = module.get_klango_hooks()
                    if hooks:
                        self.component_klango_hooks[component_name] = hooks
                else:
                    print(f"No Klango hooks for component: {component_name}")
            except Exception as e:
                print(f"Error getting Klango hooks for component {component_name}: {e}")

        except Exception as e:
            print(f"Failed to load component {component_name}: {e}")
            import traceback
            traceback.print_exc()

    def register_component_settings(self):
        """Register settings categories from all loaded components"""
        print(f"[ComponentManager] register_component_settings called")
        print(f"[ComponentManager] settings_frame: {self.settings_frame}")
        print(f"[ComponentManager] Number of components: {len(self.components)}")

        if not self.settings_frame:
            print("Warning: Cannot register component settings - settings_frame not available")
            return

        for component in self.components:
            try:
                print(f"[ComponentManager] Checking component: {component.__name__}")
                if hasattr(component, 'add_settings_category'):
                    print(f"[ComponentManager] Registering settings category for component: {component.__name__}")
                    component.add_settings_category(self)
                else:
                    print(f"[ComponentManager] Component {component.__name__} has no add_settings_category hook")
            except Exception as e:
                print(f"Error registering settings category for component {component.__name__}: {e}")
                import traceback
                traceback.print_exc()

    def get_component_menu_functions(self):
        return self.component_menu_functions
    
    def get_components(self):
        """Get list of all components with their metadata."""
        components_list = []
        for folder_name, friendly_name in self.component_friendly_names.items():
            component_data = {
                'name': friendly_name,
                'folder': folder_name,
                'enabled': self.component_states.get(folder_name, 1) == 0
            }
            components_list.append(component_data)
        return components_list

    def register_menu_function(self, name, func):
        """Registers a menu function from a component."""
        self.component_menu_functions[name] = func

    def register_settings_category(self, category_name, panel_builder, save_callback=None, load_callback=None):
        """
        Register a settings category from a component.

        Args:
            category_name: Name of the category to display in the list
            panel_builder: Function that creates and returns a wx.Panel for the category
                          Function signature: panel_builder(parent) -> wx.Panel
            save_callback: Optional function to call when saving settings
                          Function signature: save_callback(panel) -> None
            load_callback: Optional function to call when loading settings
                          Function signature: load_callback(panel) -> None
        """
        print(f"[ComponentManager] register_settings_category called for: {category_name}")
        print(f"[ComponentManager] settings_frame exists: {self.settings_frame is not None}")
        print(f"[ComponentManager] has register_category: {hasattr(self.settings_frame, 'register_category') if self.settings_frame else False}")

        if self.settings_frame and hasattr(self.settings_frame, 'register_category'):
            try:
                # Create the panel
                print(f"[ComponentManager] Creating panel for {category_name}")
                panel = panel_builder(self.settings_frame.content_panel)
                print(f"[ComponentManager] Panel created: {panel}")
                # Register it
                self.settings_frame.register_category(category_name, panel, save_callback, load_callback)
                print(f"[ComponentManager] Successfully registered settings category: {category_name}")
            except Exception as e:
                print(f"Error registering settings category {category_name}: {e}")
                import traceback
                traceback.print_exc()

    def get_gui_hooks(self):
        """Get all GUI hooks from components."""
        return self.component_gui_hooks

    def get_klango_hooks(self):
        """Get all Klango mode hooks from components."""
        return self.component_klango_hooks

    def apply_gui_hooks(self, gui_app):
        """Apply GUI hooks from all components to the GUI application."""
        for component_name, hooks in self.component_gui_hooks.items():
            try:
                if 'on_gui_init' in hooks and callable(hooks['on_gui_init']):
                    hooks['on_gui_init'](gui_app)
                    print(f"Applied GUI init hook from component: {component_name}")
            except Exception as e:
                print(f"Error applying GUI hooks from component {component_name}: {e}")
                import traceback
                traceback.print_exc()

    def apply_klango_hooks(self, klango_mode):
        """Apply Klango mode hooks from all components."""
        for component_name, hooks in self.component_klango_hooks.items():
            try:
                if 'on_klango_init' in hooks and callable(hooks['on_klango_init']):
                    hooks['on_klango_init'](klango_mode)
                    print(f"Applied Klango init hook from component: {component_name}")
            except Exception as e:
                print(f"Error applying Klango hooks from component {component_name}: {e}")
                import traceback
                traceback.print_exc()

    def compile_to_pyc(self, py_path):
        """Compiles a Python file to .pyc and returns its path."""
        try:
            pyc_path = py_path + 'c'
            py_compile.compile(py_path, cfile=pyc_path)
            print(f"Compiled {py_path} to {pyc_path}")
            return pyc_path
        except py_compile.PyCompileError as e:
            print(f"Compilation error in {py_path}: {e}")
            return None

    

    def initialize_components(self, app):
        """Initializes all loaded components."""
        for component in self.components:
            try:
                if hasattr(component, 'initialize'):
                    try:
                        component.initialize(app)
                        print(f"Initialized component: {component.__name__}")
                    except Exception as e:
                        print(f"Failed to initialize component {component.__name__}: {e}")
                        import traceback
                        traceback.print_exc()
                        # Continue with next component
                else:
                    print(f"No initialize function in component: {component.__name__}")
            except Exception as e:
                print(f"Critical error in initialize_components for component: {e}")
                import traceback
                traceback.print_exc()
                # Continue with next component
                continue

    def shutdown_components(self):
        """Shuts down all loaded components."""
        for component in self.components:
            if hasattr(component, 'shutdown'):
                try:
                    component.shutdown()
                    print(f"Shutdown component: {component.__name__}")
                except Exception as e:
                    print(f"Failed to shutdown component {component.__name__}: {e}")
            else:
                print(f"No shutdown function in component: {component.__name__}")
