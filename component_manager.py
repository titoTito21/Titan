# -*- coding: utf-8 -*-
import os
import sys
import importlib.util
import py_compile
import shutil
import platform
import configparser

class ComponentManager:
    def __init__(self, settings_frame):
        self.components = []
        self.settings_frame = settings_frame
        self.component_menu_functions = {}
        self.component_states = {}  # Zmieniono z self.component_statuses
        self.component_friendly_names = {
            "TTerm": "Terminal",
            "Tips": "Porady",
            "titan_help": "Pomoc Titana (F1)",
            "charging_sound": "Monitor systemowy Titana"
        }
        self.load_components()

    def get_component_display_name(self, folder_name):
        return self.component_friendly_names.get(folder_name, folder_name)

    def load_components(self):
        """Loads all components from the data/components directory."""
        components_dir = os.path.join(os.path.dirname(__file__), 'data', 'components')
        if not os.path.exists(components_dir):
            print(f"Components directory does not exist: {components_dir}")
            return

        sys.path.insert(0, components_dir)

        for component_folder in os.listdir(components_dir):
            component_path = os.path.join(components_dir, component_folder)
            if os.path.isdir(component_path) and component_folder != '.DS_Store':
                self.ensure_component_config(component_path, component_folder)
                status = self.get_component_status(component_path)
                self.component_states[component_folder] = status

                if status == 0:  # Load only enabled components
                    print(f"Loading component from folder: {component_folder}")
                    init_path = self.find_init_file(component_path)
                    if init_path:
                        self.load_component(init_path, component_folder)
                    else:
                        print(f"No init file found in component: {component_folder}")
                else:
                    print(f"Component {component_folder} is disabled.")

    def ensure_component_config(self, component_path, component_folder):
        config_path = os.path.join(component_path, '__component__.TCE')
        if not os.path.exists(config_path):
            config = configparser.ConfigParser()
            config['component'] = {
                'name': self.get_component_display_name(component_folder),
                'status': '0'
            }
            with open(config_path, 'w') as configfile:
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
        component_path = os.path.join(os.path.dirname(__file__), 'data', 'components', component_folder)
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
            if init_path.endswith('.py'):
                # Compile .py to .pyc if it's newer or .pyc doesn't exist
                pyc_path = init_path + 'c'
                if not os.path.exists(pyc_path) or os.path.getmtime(init_path) > os.path.getmtime(pyc_path):
                    pyc_path = self.compile_to_pyc(init_path)
                    if not pyc_path:
                        print(f"Failed to compile file: {init_path}")
                        return
                init_path = pyc_path

            spec = importlib.util.spec_from_file_location(component_name, init_path)
            if spec is None:
                print(f"Could not create spec for component: {component_name}")
                return
            
            module = importlib.util.module_from_spec(spec)
            sys.modules[component_name] = module
            spec.loader.exec_module(module)
            self.components.append(module)

            print(f"Successfully loaded component: {component_name}")

            if hasattr(module, 'add_menu'):
                print(f"Adding menu for component: {component_name}")
                module.add_menu(self)
            else:
                print(f"No menu to add for component: {component_name}")

            if hasattr(module, 'add_settings'):
                print(f"Adding settings for component: {component_name}")
                module.add_settings(self.settings_frame)
            else:
                print(f"No settings to add for component: {component_name}")

        except Exception as e:
            print(f"Failed to load component {component_name}: {e}")

    def get_component_menu_functions(self):
        return self.component_menu_functions

    def register_menu_function(self, name, func):
        """Registers a menu function from a component."""
        self.component_menu_functions[name] = func

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
            if hasattr(component, 'initialize'):
                try:
                    component.initialize(app)
                    print(f"Initialized component: {component.__name__}")
                except Exception as e:
                    print(f"Failed to initialize component {component.__name__}: {e}")
            else:
                print(f"No initialize function in component: {component.__name__}")

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
