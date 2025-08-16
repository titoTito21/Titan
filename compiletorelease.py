import subprocess
import sys
import os
import shutil
import glob
import ast
import re
import configparser

def scan_python_imports(file_path):
    """Skanuje plik Python w poszukiwaniu importów i zwraca listę wymaganych pakietów"""
    imports = set()
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Parsuj AST żeby znaleźć importy
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name.split('.')[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module.split('.')[0])
        except SyntaxError:
            # Jeśli parsowanie AST nie działa, użyj regex jako fallback
            import_patterns = [
                r'^\s*import\s+([a-zA-Z_][a-zA-Z0-9_]*)',
                r'^\s*from\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+import'
            ]
            
            for line in content.split('\n'):
                for pattern in import_patterns:
                    match = re.match(pattern, line)
                    if match:
                        imports.add(match.group(1))
    
    except Exception as e:
        print(f"Błąd podczas skanowania {file_path}: {e}")
    
    return imports

def scan_directory_for_dependencies(directory):
    """Skanuje katalog w poszukiwaniu wszystkich zależności Python"""
    all_imports = set()
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                imports = scan_python_imports(file_path)
                all_imports.update(imports)
    
    return all_imports

def get_components_and_widgets_dependencies():
    """Zbiera zależności ze wszystkich komponentów i widgetów"""
    all_dependencies = set()
    
    # Ścieżki do skanowania
    paths_to_scan = [
        os.path.join('data', 'components'),
        os.path.join('data', 'applets')  # applets to są widgety
    ]
    
    for path in paths_to_scan:
        if os.path.exists(path):
            print(f"Skanowanie zależności w: {path}")
            dependencies = scan_directory_for_dependencies(path)
            all_dependencies.update(dependencies)
            
            # Sprawdź requirements.txt w każdym komponencie/widgecie
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    requirements_path = os.path.join(item_path, 'requirements.txt')
                    if os.path.exists(requirements_path):
                        print(f"Znaleziono requirements.txt w: {item_path}")
                        try:
                            with open(requirements_path, 'r', encoding='utf-8') as f:
                                for line in f:
                                    line = line.strip()
                                    if line and not line.startswith('#'):
                                        # Wyciągnij nazwę pakietu (bez wersji)
                                        package_name = re.split(r'[>=<!]', line)[0].strip()
                                        all_dependencies.add(package_name)
                        except Exception as e:
                            print(f"Błąd podczas czytania {requirements_path}: {e}")
    
    # Usuń pakiety standardowe Python
    standard_modules = {
        'os', 'sys', 'subprocess', 'shutil', 'glob', 'ast', 're', 'configparser',
        'threading', 'time', 'platform', 'gettext', 'json', 'urllib', 'http',
        'email', 'socket', 'ssl', 'hashlib', 'base64', 'datetime', 'collections',
        'itertools', 'functools', 'operator', 'math', 'random', 'string',
        'pathlib', 'tempfile', 'io', 'logging', 'traceback', 'warnings',
        'ctypes', 'struct', 'pickle', 'csv', 'xml', 'sqlite3', 'zlib',
        'gzip', 'tarfile', 'zipfile', 'uuid', 'copy', 'weakref'
    }
    
    # Mapowanie nazw modułów na pakiety pip (dla niektórych przypadków gdzie się różnią)
    package_mapping = {
        'pycaw': 'pycaw',
        'psutil': 'psutil',
        'comtypes': 'comtypes',
        'alsaaudio': 'pyalsaaudio',
        'typing': None,  # wbudowane w Python 3.5+
        'typing_extensions': 'typing_extensions'
    }
    
    external_dependencies = all_dependencies - standard_modules
    
    # Zastąp nazwy modułów nazwami pakietów gdzie potrzebne
    final_dependencies = set()
    for dep in external_dependencies:
        if dep in package_mapping:
            if package_mapping[dep] is not None:
                final_dependencies.add(package_mapping[dep])
        else:
            final_dependencies.add(dep)
    
    print(f"Znalezione zewnętrzne zależności: {sorted(final_dependencies)}")
    return final_dependencies

def copy_optimized_python_environment():
    """Kopiuje zoptymalizowane środowisko Python dla zewnętrznych aplikacji TCE"""
    build_dir = os.path.join(os.path.dirname(__file__), 'build')
    python_dir = os.path.join(build_dir, 'python')
    
    # Utwórz katalogi
    os.makedirs(python_dir, exist_ok=True)
    os.makedirs(os.path.join(python_dir, 'Lib'), exist_ok=True)
    
    # Znajdź lokalizacje Python
    python_exe = sys.executable
    python_base_dir = os.path.dirname(python_exe)
    site_packages_dir = os.path.join(python_base_dir, 'Lib', 'site-packages')
    
    print(f"Kopiowanie zoptymalizowanego Python.exe z: {python_exe}")
    
    try:
        # Skopiuj Python.exe i podstawowe DLLs
        shutil.copy2(python_exe, os.path.join(python_dir, 'python.exe'))
        
        # Skopiuj tylko niezbędne DLL
        essential_dlls = ['python*.dll', 'vcruntime*.dll', 'msvcp*.dll', 'api-ms-*.dll']
        for pattern in essential_dlls:
            for dll_file in glob.glob(os.path.join(python_base_dir, pattern)):
                shutil.copy2(dll_file, python_dir)
        
        # Skopiuj zoptymalizowaną bibliotekę standardową (bez testów i dokumentacji)
        stdlib_dir = os.path.join(python_base_dir, 'Lib')
        dest_lib_dir = os.path.join(python_dir, 'Lib')
        
        if os.path.exists(stdlib_dir):
            print(f"Kopiowanie zoptymalizowanej biblioteki standardowej...")
            if os.path.exists(dest_lib_dir):
                shutil.rmtree(dest_lib_dir)
            
            # Wykluczenia dla zmniejszenia rozmiaru
            def ignore_patterns(dir, files):
                ignored = set()
                for file in files:
                    # Pomiń niepotrzebne moduły i pliki
                    if any(pattern in file for pattern in [
                        '__pycache__', '.pyc', '.pyo', 
                        'test', 'tests', 'unittest',
                        'tkinter', 'turtle', 'turtledemo',
                        'idlelib', 'lib2to3',
                        'distutils', 'ensurepip'
                    ]):
                        ignored.add(file)
                    # Pomiń dokumentację i przykłady
                    elif file.endswith(('.txt', '.rst', '.md')) and file != 'LICENSE.txt':
                        ignored.add(file)
                return ignored
            
            shutil.copytree(stdlib_dir, dest_lib_dir, ignore=ignore_patterns)
        
        # Skopiuj wszystkie pakiety z site-packages dla elastyczności deweloperskiej
        def copy_all_site_packages(source_dir, dest_dir, desc):
            if os.path.exists(source_dir):
                os.makedirs(dest_dir, exist_ok=True)
                print(f"Kopiowanie wszystkich pakietów z {desc}...")
                
                for item in os.listdir(source_dir):
                    src_item = os.path.join(source_dir, item)
                    dest_item = os.path.join(dest_dir, item)
                    
                    try:
                        if os.path.isdir(src_item):
                            if not os.path.exists(dest_item):
                                shutil.copytree(src_item, dest_item, 
                                              ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo', 'test*'))
                        else:
                            if not os.path.exists(dest_item):
                                shutil.copy2(src_item, dest_item)
                    except Exception as e:
                        print(f"Ostrzeżenie: Nie można skopiować {item}: {e}")
        
        dest_site_packages = os.path.join(python_dir, 'Lib', 'site-packages')
        
        # 1. Główne site-packages
        copy_all_site_packages(site_packages_dir, dest_site_packages, "site-packages")
        
        # 2. Pakiety użytkownika (AppData\Roaming)
        user_site_packages = os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming', 'Python', f'Python{sys.version_info.major}{sys.version_info.minor}', 'site-packages')
        copy_all_site_packages(user_site_packages, dest_site_packages, "pakietów użytkownika")
        
        # 3. Program Files Python (jeśli istnieje)
        program_files_python = os.path.join(os.environ.get('PROGRAMFILES', ''), f'Python{sys.version_info.major}{sys.version_info.minor}', 'Lib', 'site-packages')
        copy_all_site_packages(program_files_python, dest_site_packages, "Program Files Python")
        
        program_files_x86_python = os.path.join(os.environ.get('PROGRAMFILES(X86)', ''), f'Python{sys.version_info.major}{sys.version_info.minor}', 'Lib', 'site-packages')
        copy_all_site_packages(program_files_x86_python, dest_site_packages, "Program Files (x86) Python")
        
        # 4. Skopiuj pip i setuptools dla instalacji pakietów
        pip_dirs = ['pip', 'pip-*', 'setuptools', 'setuptools-*', 'wheel', 'wheel-*']
        for src_dir in [site_packages_dir, user_site_packages, program_files_python, program_files_x86_python]:
            if os.path.exists(src_dir):
                for pip_pattern in pip_dirs:
                    for pip_dir in glob.glob(os.path.join(src_dir, pip_pattern)):
                        if os.path.isdir(pip_dir):
                            dest_pip = os.path.join(dest_site_packages, os.path.basename(pip_dir))
                            if not os.path.exists(dest_pip):
                                try:
                                    shutil.copytree(pip_dir, dest_pip, ignore=shutil.ignore_patterns('__pycache__'))
                                    print(f"Skopiowano {pip_pattern} z {src_dir}")
                                except Exception as e:
                                    print(f"Ostrzeżenie: Nie można skopiować {pip_pattern}: {e}")
        
        # 5. Skopiuj skrypty pip z Scripts
        scripts_dir = os.path.join(python_base_dir, 'Scripts')
        dest_scripts_dir = os.path.join(python_dir, 'Scripts')
        if os.path.exists(scripts_dir):
            print("Kopiowanie Scripts (pip, itp.)...")
            if os.path.exists(dest_scripts_dir):
                shutil.rmtree(dest_scripts_dir)
            shutil.copytree(scripts_dir, dest_scripts_dir)
        
        print(f"Zoptymalizowane środowisko Python skopiowane do: {python_dir}")
        return python_dir
        
    except Exception as e:
        print(f"Błąd podczas kopiowania środowiska Python: {e}")
        return None

def compile_with_nuitka(source_file):
    if not os.path.isfile(source_file):
        print(f"File '{source_file}' does not exist.")
        return

    print(f"Starting compilation of {source_file} with Nuitka...")
    
    # Wykryj zależności komponentów i widgetów
    component_dependencies = get_components_and_widgets_dependencies()
    
    # Kopiuj zoptymalizowane środowisko Python dla zewnętrznych aplikacji TCE
    python_env_dir = copy_optimized_python_environment()
    if not python_env_dir:
        print("Ostrzeżenie: Nie udało się skopiować środowiska Python.")
        print("Zewnętrzne aplikacje TCE mogą nie działać poprawnie.")

    command = [
        "python", "-m", "nuitka",
        "--standalone",
        "--mingw64",
        "--onefile",
        "--output-dir=output",
        # Optymalizacje rozmiaru
        "--lto=yes",  # Link Time Optimization
        "--no-pyi-file",  # Nie generuj plików .pyi
        # Selektywne dołączanie tylko używanych modułów
        "--follow-imports",
        "--nofollow-import-to=unittest,test,distutils,tkinter,email.mime,xml.sax,xml.etree",
        # Pakowanie tylko niezbędnych bibliotek
        "--include-package=wx",
        "--include-package=pygame", 
        "--include-package=accessible_output3",
        "--include-package=websockets",
        "--include-package=requests",
    ]
    
    # Dodaj wykryte zależności komponentów i widgetów
    for dependency in component_dependencies:
        command.append(f"--include-package={dependency}")
        print(f"Dodano zależność z komponentów/widgetów: {dependency}")
    
    # Kontynuuj z resztą komend
    command.extend([
        # Dane aplikacji
        "--include-data-dir=data=data",
        "--include-data-dir=sfx=sfx",
        "--include-data-dir=languages=languages",
        "--include-data-dir=build/python=python",
        "--disable-console",
        "--windows-icon-from-ico=icon.ico" if os.path.exists("icon.ico") else "",
        source_file
    ])
    
    # Usuń puste argumenty
    command = [arg for arg in command if arg]

    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        print(f"Compilation successful: {result.stdout}")
    except subprocess.CalledProcessError as e:
        print(f"Error during compilation: {e.stderr}")

    print(f"Finished compilation of {source_file}. Output can be found in the 'output' directory.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python compile_script.py <source_file.py>")
    else:
        source_file = sys.argv[1]
        compile_with_nuitka(source_file)
