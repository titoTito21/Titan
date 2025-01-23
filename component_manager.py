# -*- coding: utf-8 -*-
import os
import sys
import importlib.util
import py_compile
import shutil
import platform

class ComponentManager:
    def __init__(self, menubar, settings_frame):
        self.components = []
        self.menubar = menubar
        self.settings_frame = settings_frame
        self.load_components()

    def load_components(self):
        """Loads all components from the data/components directory."""
        components_dir = os.path.join(os.path.dirname(__file__), 'data', 'components')
        if not os.path.exists(components_dir):
            print(f"Components directory does not exist: {components_dir}")
            return

        # Add the components directory to sys.path
        sys.path.insert(0, components_dir)

        for component_folder in os.listdir(components_dir):
            component_path = os.path.join(components_dir, component_folder)
            if os.path.isdir(component_path) and component_folder != '.DS_Store':  # Ignore .DS_Store
                print(f"Loading component from folder: {component_folder}")
                init_path = self.find_init_file(component_path)
                if init_path:
                    self.load_component(init_path, component_folder)
                else:
                    print(f"No init file found in component: {component_folder}")

    def find_init_file(self, component_path):
        """Finds the init.py or init.pyc file in the component directory."""
        for ext in ['.py', '.pyc']:
            init_path = os.path.join(component_path, 'init' + ext)
            if os.path.exists(init_path):
                return init_path
        return None

    def load_component(self, init_path, component_name):
        """Loads a component from the given init file."""
        try:
            if init_path.endswith('.py'):
                pyc_path = self.compile_to_pyc(init_path)
                if pyc_path:
                    init_path = pyc_path
                else:
                    print(f"Failed to compile file: {init_path}")
                    return

            spec = importlib.util.spec_from_file_location(component_name, init_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[component_name] = module
            spec.loader.exec_module(module)
            self.components.append(module)

            print(f"Successfully loaded component: {component_name}")

            if hasattr(module, 'add_menu'):
                print(f"Adding menu for component: {component_name}")
                module.add_menu(self.menubar)
            else:
                print(f"No menu to add for component: {component_name}")

            if hasattr(module, 'add_settings'):
                print(f"Adding settings for component: {component_name}")
                module.add_settings(self.settings_frame)
            else:
                print(f"No settings to add for component: {component_name}")

        except Exception as e:
            print(f"Failed to load component {component_name}: {e}")

    def compile_to_pyc(self, py_path):
        """Compiles a Python file to .pyc and returns its path."""
        try:
            pyc_path = py_path + 'c'
            py_compile.compile(py_path, cfile=pyc_path)
            self.import_missing_modules(py_path)
            print(f"Compiled {py_path} to {pyc_path}")
            return pyc_path
        except py_compile.PyCompileError as e:
            print(f"Compilation error in {py_path}: {e}")
            return None

    def import_missing_modules(self, py_file):
        """Imports missing modules if they are required by components."""
        with open(py_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            for line in lines:
                if line.startswith('import ') or line.startswith('from '):
                    module_name = line.split()[1].split('.')[0]
                    try:
                        if importlib.util.find_spec(module_name) is None:
                            __import__(module_name)
                    except ImportError:
                        print(f"Module {module_name} was not found and cannot be imported.")

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
