#!/usr/bin/env python
"""
Script to extract translations from source files into modular .pot files.
Each domain has its own .pot file with translations from specific source files.
"""

import subprocess
import os

# Mapping of translation domains to their source files
DOMAIN_FILES = {
    'gui': ['src/ui/gui.py'],
    'invisibleui': ['src/ui/invisibleui.py'],
    'settings': ['src/settings/settings.py', 'src/ui/settingsgui.py'],
    'menu': ['src/ui/menu.py'],
    'main': ['main.py'],
    'apps': ['src/titan_core/app_manager.py'],
    'games': ['src/titan_core/game_manager.py'],
    'components': ['src/titan_core/component_manager.py', 'src/ui/componentmanagergui.py'],
    'notifications': ['src/system/notifications.py', 'src/ui/notificationcenter.py'],
    'network': [
        'src/network/messenger_client.py', 'src/network/messenger_gui.py', 'src/network/messenger_webview.py',
        'src/network/telegram_client.py', 'src/network/telegram_gui.py', 'src/network/telegram_voice.py', 'src/network/telegram_windows.py',
        'src/network/whatsapp_client.py', 'src/network/whatsapp_webview.py',
        'src/settings/titan_im_config.py', 'src/network/run_messenger.py'
    ],
    'titannet': [
        'src/network/titan_net.py', 'src/network/titan_net_gui.py'
    ],
    'system': ['src/titan_core/tce_system.py', 'src/titan_core/tce_system_net.py', 'src/system/system_monitor.py', 'src/system/updater.py', 'src/system/lockscreen_monitor_improved.py', 'src/ui/shutdown_question.py'],
    'controller': ['src/controller/controller_ui.py', 'src/controller/controller_modes.py', 'src/controller/controller_vibrations.py'],
    'help': ['src/ui/help.py'],
    'sound': ['src/titan_core/sound.py', 'src/titan_core/tsounds.py', 'src/titan_core/stereo_speech.py'],
}

def extract_domain(domain, files):
    """Extract translations for a specific domain."""
    # Filter files that exist
    existing_files = [f for f in files if os.path.exists(f)]

    if not existing_files:
        print(f"Skipping {domain}: no source files found")
        return

    output_file = f'languages/{domain}.pot'

    # Build pybabel extract command
    cmd = [
        'pybabel', 'extract',
        '-o', output_file,
        '--no-default-keywords',
        '--keyword=_',
    ]

    # Add each file
    cmd.extend(existing_files)

    print(f"Extracting {domain} from {len(existing_files)} file(s)...")
    try:
        subprocess.run(cmd, check=True)
        print(f"  [OK] Created {output_file}")
    except subprocess.CalledProcessError as e:
        print(f"  [ERROR] Error extracting {domain}: {e}")
    except FileNotFoundError:
        print(f"  [ERROR] pybabel not found. Install it with: pip install babel")
        return False

    return True

def update_po_files(domain, languages=['pl', 'en']):
    """Update .po files for a domain in all languages."""
    pot_file = f'languages/{domain}.pot'

    if not os.path.exists(pot_file):
        print(f"Skipping update for {domain}: {pot_file} not found")
        return

    for lang in languages:
        po_dir = f'languages/{lang}/LC_MESSAGES'
        po_file = f'{po_dir}/{domain}.po'

        # Create directory if it doesn't exist
        os.makedirs(po_dir, exist_ok=True)

        # Check if .po file exists
        if os.path.exists(po_file):
            # Update existing .po file
            cmd = ['pybabel', 'update', '-l', lang, '-d', 'languages', '-i', pot_file, '-D', domain]
            print(f"Updating {lang}/{domain}.po...")
        else:
            # Initialize new .po file
            cmd = ['pybabel', 'init', '-l', lang, '-d', 'languages', '-i', pot_file, '-D', domain]
            print(f"Initializing {lang}/{domain}.po...")

        try:
            subprocess.run(cmd, check=True)
            print(f"  [OK] {lang}/{domain}.po updated")
        except subprocess.CalledProcessError as e:
            print(f"  [ERROR] Error updating {lang}/{domain}.po: {e}")

def compile_translations(languages=['pl', 'en']):
    """Compile all .po files to .mo files."""
    print("\nCompiling translations...")

    # Compile each domain separately
    for domain in DOMAIN_FILES.keys():
        cmd = ['pybabel', 'compile', '-d', 'languages', '-D', domain]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            print(f"  [OK] Compiled {domain}")
        except subprocess.CalledProcessError as e:
            print(f"  [ERROR] Error compiling {domain}: {e}")


def main():
    """Main extraction process."""
    print("=" * 60)
    print("Modular Translation Extraction")
    print("=" * 60)

    # Create languages directory if it doesn't exist
    os.makedirs('languages', exist_ok=True)

    # Extract all domains
    print("\n[1/3] Extracting translatable strings...")
    for domain, files in DOMAIN_FILES.items():
        extract_domain(domain, files)

    # Update .po files
    print("\n[2/3] Updating .po files...")
    for domain in DOMAIN_FILES.keys():
        update_po_files(domain)

    # Compile translations
    print("\n[3/3] Compiling translations...")
    compile_translations()

    print("\n" + "=" * 60)
    print("Translation extraction complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Edit .po files in languages/*/LC_MESSAGES/")
    print("2. Run 'python extract_translations.py' to recompile")
    print("   or 'pybabel compile -d languages' to just compile")

if __name__ == '__main__':
    main()
