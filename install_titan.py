#!/usr/bin/env python3
"""
TCE Launcher - Installation Script for Ubuntu/Debian
Automatyczna instalacja TCE Launcher na systemach Ubuntu/Debian
"""

import os
import sys
import subprocess
import shutil
import platform
import urllib.request
import json
from pathlib import Path

VERSION = "1.0.0"
TITAN_REPO_URL = "https://github.com/titosoft/tce-launcher.git"  # Przykładowy URL
INSTALL_DIR = os.path.expanduser("~/.local/share/tce-launcher")
DESKTOP_FILE = os.path.expanduser("~/.local/share/applications/tce-launcher.desktop")
BIN_DIR = os.path.expanduser("~/.local/bin")
BIN_FILE = os.path.join(BIN_DIR, "tce-launcher")

def print_header():
    """Wyświetla nagłówek instalatora"""
    print("=" * 60)
    print("    TCE Launcher - Instalator dla Ubuntu/Debian")
    print(f"                    Wersja {VERSION}")
    print("=" * 60)
    print()

def check_system():
    """Sprawdza czy system jest wspierany"""
    if platform.system() != "Linux":
        print("BŁĄD: Ten skrypt działa tylko na Linuxie")
        return False
    
    # Sprawdź czy to Ubuntu/Debian
    try:
        with open("/etc/os-release", "r") as f:
            content = f.read()
            if not ("ubuntu" in content.lower() or "debian" in content.lower()):
                print("OSTRZEŻENIE: Wykryto system inny niż Ubuntu/Debian")
                print("   Instalacja może nie działać poprawnie")
                choice = input("   Czy kontynuować? (t/N): ").lower()
                if choice not in ['t', 'tak', 'y', 'yes']:
                    return False
    except FileNotFoundError:
        print("Nie można zidentyfikować systemu operacyjnego")
    
    return True

def run_command(command, description, capture_output=False):
    """Uruchamia komendę z opisem"""
    print(f"[PRACA] {description}...")
    try:
        if capture_output:
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"BŁĄD: {description}")
                print(f"   Szczegóły: {result.stderr}")
                return False, result.stdout
            return True, result.stdout
        else:
            result = subprocess.run(command, shell=True)
            if result.returncode != 0:
                print(f"BŁĄD: {description}")
                return False, ""
            print(f"OK: {description} - zakończone pomyślnie")
            return True, ""
    except Exception as e:
        print(f"BŁĄD podczas: {description}")
        print(f"   Wyjątek: {str(e)}")
        return False, ""

def install_system_dependencies():
    """Instaluje zależności systemowe"""
    print("\nINSTALACJA ZALEŻNOŚCI SYSTEMOWYCH")
    
    # Lista pakietów Ubuntu/Debian - kompletne zależności dla TCE Launcher
    packages = [
        # Python i podstawowe narzędzia
        "python3",
        "python3-pip", 
        "python3-venv",
        "python3-dev",
        "python3-setuptools",
        "python3-wheel",
        
        # Kompilatory i narzędzia budowania dla numpy/scipy
        "build-essential",
        "gcc",
        "g++",
        "gfortran",
        "make",
        "cmake",
        "pkg-config",
        
        # Biblioteki BLAS/LAPACK dla numpy
        "libblas-dev",
        "liblapack-dev",
        "libatlas-base-dev",
        "libopenblas-dev",
        
        # Biblioteki dla kompilacji numpy z źródeł
        "libffi-dev",
        "libssl-dev",
        "zlib1g-dev",
        "libjpeg-dev",
        "libpng-dev",
        "libtiff-dev",
        
        # wxPython i GUI
        "python3-wxgtk4.0",
        "libwxgtk3.0-gtk3-dev",
        "libgtk-3-dev",
        "libwebkit2gtk-4.0-dev",
        "libgtk2.0-dev",
        
        # Audio i multimedia
        "libasound2-dev",
        "libportaudio2",
        "portaudio19-dev",
        "libpulse-dev",
        "pulseaudio-utils",
        "libjack-jackd2-dev",
        "libsndfile1-dev",
        "ffmpeg",
        "libavcodec-dev",
        "libavformat-dev",
        "libswscale-dev",
        
        # Accessibility i TTS
        "speech-dispatcher",
        "speech-dispatcher-dev",
        "espeak",
        "espeak-data",
        "espeak-ng",
        "festival",
        "festvox-kallpc16k",
        
        # Inne biblioteki systemowe
        "git",
        "curl",
        "wget",
        "libenchant-2-2",
        "libenchant-2-dev",
        "libxml2-dev",
        "libxslt1-dev",
        "libfreetype6-dev",
        "libharfbuzz-dev",
        "libfribidi-dev",
        
        # Biblioteki dla pygame
        "libsdl2-dev",
        "libsdl2-image-dev",
        "libsdl2-mixer-dev",
        "libsdl2-ttf-dev",
        
        # Biblioteki sieciowe
        "libcurl4-openssl-dev",
        "libssl-dev",
        
        # Biblioteki do kompresji
        "liblzma-dev",
        "libbz2-dev",
        "libreadline-dev",
        "libsqlite3-dev",
        
        # Narzędzia do debugowania
        "strace",
        "gdb"
    ]
    
    # Aktualizuj repozytoria
    success, _ = run_command("sudo apt update", "Aktualizacja repozytoriów pakietów")
    if not success:
        return False
    
    # Instaluj pakiety
    packages_str = " ".join(packages)
    success, _ = run_command(f"sudo apt install -y {packages_str}", "Instalacja pakietów systemowych")
    if not success:
        print("UWAGA: Niektóre pakiety mogły nie zostać zainstalowane")
        print("   Spróbuj zainstalować je ręcznie: sudo apt install python3-wxgtk4.0")
    
    return True

def create_virtual_environment():
    """Tworzy środowisko wirtualne Python"""
    print("\nTWORZENIE ŚRODOWISKA WIRTUALNEGO")
    
    venv_dir = os.path.join(INSTALL_DIR, "venv")
    
    # Usuń stare środowisko jeśli istnieje
    if os.path.exists(venv_dir):
        print("Usuwanie starego środowiska wirtualnego...")
        shutil.rmtree(venv_dir)
    
    # Utwórz nowe środowisko
    success, _ = run_command(f"python3 -m venv {venv_dir}", "Tworzenie środowiska wirtualnego")
    if not success:
        return False
    
    # Zaktualizuj pip
    pip_path = os.path.join(venv_dir, "bin", "pip")
    success, _ = run_command(f"{pip_path} install --upgrade pip", "Aktualizacja pip")
    
    return True

def download_source_code():
    """Pobiera kod źródłowy TCE Launcher"""
    print("\nPOBIERANIE KODU ŹRÓDŁOWEGO")
    
    # Utwórz katalog instalacyjny
    os.makedirs(INSTALL_DIR, exist_ok=True)
    
    source_dir = os.path.join(INSTALL_DIR, "src")
    
    # Usuń stary kod jeśli istnieje
    if os.path.exists(source_dir):
        print("Usuwanie starego kodu źródłowego...")
        shutil.rmtree(source_dir)
    
    # Ponieważ nie mamy prawdziwego repo, skopiuj z obecnego katalogu
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    print(f"Kopiowanie z: {current_dir}")
    print(f"Do: {source_dir}")
    
    try:
        shutil.copytree(current_dir, source_dir, 
                       ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.git', 'venv', 'output'))
        print("OK: Kod źródłowy skopiowany pomyślnie")
        return True
    except Exception as e:
        print(f"BŁĄD podczas kopiowania: {str(e)}")
        return False

def install_python_dependencies():
    """Instaluje zależności Python"""
    print("\nINSTALACJA ZALEŻNOŚCI PYTHON")
    
    venv_dir = os.path.join(INSTALL_DIR, "venv")
    pip_path = os.path.join(venv_dir, "bin", "pip")
    source_dir = os.path.join(INSTALL_DIR, "src")
    requirements_file = os.path.join(source_dir, "requirements.txt")
    
    if not os.path.exists(requirements_file):
        print("BŁĄD: Nie znaleziono pliku requirements.txt")
        return False
    
    # Filtruj zależności Windows-only
    linux_requirements = []
    with open(requirements_file, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                # Pomiń zależności Windows-only
                if "platform_system == \"Windows\"" in line:
                    continue
                # Zamień problematyczne pakiety na Linux
                if line == "wxPython":
                    continue  # Już zainstalowane przez apt
                linux_requirements.append(line)
    
    # Utwórz tymczasowy plik requirements dla Linuxa
    linux_req_file = os.path.join(source_dir, "requirements_linux.txt")
    with open(linux_req_file, "w") as f:
        f.write("\n".join(linux_requirements))
    
    # Instaluj zależności
    success, _ = run_command(f"{pip_path} install -r {linux_req_file}", "Instalacja zależności Python")
    
    # Usuń tymczasowy plik
    os.remove(linux_req_file)
    
    return success

def create_launcher_script():
    """Tworzy skrypt uruchamiający"""
    print("\nTWORZENIE SKRYPTU URUCHAMIAJĄCEGO")
    
    os.makedirs(BIN_DIR, exist_ok=True)
    
    venv_python = os.path.join(INSTALL_DIR, "venv", "bin", "python")
    main_script = os.path.join(INSTALL_DIR, "src", "main.py")
    
    launcher_content = f"""#!/bin/bash
# TCE Launcher - Skrypt uruchamiający

export TCE_LAUNCHER_DIR="{INSTALL_DIR}"
export PYTHONPATH="{os.path.join(INSTALL_DIR, 'src')}:$PYTHONPATH"

cd "{os.path.join(INSTALL_DIR, 'src')}"
exec "{venv_python}" "{main_script}" "$@"
"""
    
    with open(BIN_FILE, "w") as f:
        f.write(launcher_content)
    
    # Ustaw uprawnienia wykonywania
    os.chmod(BIN_FILE, 0o755)
    print(f"OK: Skrypt uruchamiający utworzony: {BIN_FILE}")
    
    return True

def create_desktop_entry():
    """Tworzy wpis w menu aplikacji"""
    print("\nTWORZENIE WPISU W MENU")
    
    os.makedirs(os.path.dirname(DESKTOP_FILE), exist_ok=True)
    
    desktop_content = f"""[Desktop Entry]
Version=1.0
Type=Application
Name=TCE Launcher
Name[pl]=TCE Launcher
Comment=Accessible desktop environment and launcher
Comment[pl]=Dostępne środowisko pulpitu i launcher
Exec={BIN_FILE}
Icon=applications-system
Terminal=false
Categories=Accessibility;System;
Keywords=accessibility;launcher;desktop;
StartupNotify=true
"""
    
    with open(DESKTOP_FILE, "w") as f:
        f.write(desktop_content)
    
    print(f"OK: Wpis w menu utworzony: {DESKTOP_FILE}")
    return True

def configure_accessibility():
    """Konfiguruje dostępność"""
    print("\nKONFIGURACJA DOSTĘPNOŚCI")
    
    # Sprawdź czy speech-dispatcher działa
    success, output = run_command("systemctl --user status speech-dispatcher", 
                                  "Sprawdzanie speech-dispatcher", capture_output=True)
    
    if "active (running)" not in output:
        print("Uruchamianie speech-dispatcher...")
        run_command("systemctl --user enable speech-dispatcher", "Włączanie speech-dispatcher")
        run_command("systemctl --user start speech-dispatcher", "Uruchamianie speech-dispatcher")
    
    # Sprawdź dostępność pulseaudio
    success, _ = run_command("pulseaudio --check", "Sprawdzanie PulseAudio", capture_output=True)
    if not success:
        print("Uruchamianie PulseAudio...")
        run_command("pulseaudio --start", "Uruchamianie PulseAudio")
    
    return True

def update_path():
    """Aktualizuje PATH w bashrc"""
    print("\nAKTUALIZACJA PATH")
    
    bashrc_path = os.path.expanduser("~/.bashrc")
    path_line = f'export PATH="{BIN_DIR}:$PATH"'
    
    # Sprawdź czy PATH już istnieje
    if os.path.exists(bashrc_path):
        with open(bashrc_path, "r") as f:
            if BIN_DIR in f.read():
                print("OK: PATH już skonfigurowany")
                return True
    
    # Dodaj do bashrc
    with open(bashrc_path, "a") as f:
        f.write(f"\n# TCE Launcher\n{path_line}\n")
    
    print("OK: PATH dodany do ~/.bashrc")
    print("   Uruchom ponownie terminal lub wykonaj: source ~/.bashrc")
    
    return True

def post_install_info():
    """Wyświetla informacje po instalacji"""
    print("\n" + "=" * 60)
    print("INSTALACJA ZAKOŃCZONA POMYŚLNIE!")
    print("=" * 60)
    print()
    print("Lokalizacja instalacji:")
    print(f"   {INSTALL_DIR}")
    print()
    print("Sposoby uruchomienia:")
    print(f"   1. Przez terminal: {BIN_FILE}")
    print("   2. Przez menu aplikacji: TCE Launcher")
    print("   3. Przez komendę: tce-launcher (po przeładowaniu terminala)")
    print()
    print("Przydatne komendy:")
    print("   - Aktualizacja PATH: source ~/.bashrc")
    print("   - Test speech-dispatcher: spd-say 'test'")
    print("   - Sprawdzenie instalacji: tce-launcher --version")
    print()
    print("Uwagi:")
    print("   - Upewnij się, że masz uruchomiony screen reader (Orca)")
    print("   - Sprawdź ustawienia dźwięku w systemie")
    print("   - Niektóre funkcje mogą wymagać dodatkowej konfiguracji")
    print()

def uninstall():
    """Odinstalowuje TCE Launcher"""
    print("\nODINSTALOWYWANIE TCE LAUNCHER")
    
    if not os.path.exists(INSTALL_DIR):
        print("TCE Launcher nie jest zainstalowany")
        return False
    
    # Potwierdź odinstalowanie
    choice = input("Czy na pewno chcesz odinstalować TCE Launcher? (t/N): ").lower()
    if choice not in ['t', 'tak', 'y', 'yes']:
        print("Odinstalowanie anulowane")
        return False
    
    # Usuń pliki
    if os.path.exists(INSTALL_DIR):
        shutil.rmtree(INSTALL_DIR)
        print(f"OK: Usunięto katalog: {INSTALL_DIR}")
    
    if os.path.exists(BIN_FILE):
        os.remove(BIN_FILE)
        print(f"OK: Usunięto skrypt: {BIN_FILE}")
    
    if os.path.exists(DESKTOP_FILE):
        os.remove(DESKTOP_FILE)
        print(f"OK: Usunięto wpis menu: {DESKTOP_FILE}")
    
    print("OK: Odinstalowanie zakończone pomyślnie")
    print("   Uwaga: Ręcznie usuń linię PATH z ~/.bashrc jeśli nie potrzebujesz")
    
    return True

def main():
    """Główna funkcja instalatora"""
    print_header()
    
    # Sprawdź argumenty
    if len(sys.argv) > 1:
        if sys.argv[1] == "--uninstall":
            return uninstall()
        elif sys.argv[1] == "--help":
            print("Użycie:")
            print("  python3 install_titan.py          - Instaluj TCE Launcher")
            print("  python3 install_titan.py --uninstall - Odinstaluj TCE Launcher")
            print("  python3 install_titan.py --help   - Pokaż pomoc")
            return True
    
    # Sprawdź system
    if not check_system():
        return False
    
    # Sprawdź uprawnienia sudo
    print("Sprawdzanie uprawnień...")
    success, _ = run_command("sudo -v", "Sprawdzanie uprawnień sudo")
    if not success:
        print("BŁĄD: Wymagane uprawnienia sudo")
        return False
    
    try:
        # Kroki instalacji
        steps = [
            install_system_dependencies,
            create_virtual_environment,
            download_source_code,
            install_python_dependencies,
            create_launcher_script,
            create_desktop_entry,
            configure_accessibility,
            update_path
        ]
        
        for step in steps:
            if not step():
                print("\nINSTALACJA NIEUDANA")
                print("   Sprawdź błędy powyżej i spróbuj ponownie")
                return False
        
        # Informacje po instalacji
        post_install_info()
        return True
        
    except KeyboardInterrupt:
        print("\n\nInstalacja przerwana przez użytkownika")
        return False
    except Exception as e:
        print(f"\nBŁĄD KRYTYCZNY: {str(e)}")
        print("   Szczegóły:", traceback.format_exc())
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)