#!/usr/bin/env python
"""
Script to extract translations from source files into modular .pot files.
Each domain has its own .pot file with translations from specific source files.
"""

import subprocess
import os
import sys

# Mapping of translation domains to their source files
DOMAIN_FILES = {
    'gui': ['src/ui/gui.py'],
    'invisibleui': ['src/ui/invisibleui.py'],
    'settings': ['src/settings/settings.py', 'src/ui/settingsgui.py', 'src/settings/configvizard.py'],
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
        'src/settings/titan_im_config.py', 'src/network/run_messenger.py',
        # Titan IM web-as-backend layer: accessible clients + shared UI
        'src/network/im_ui_common.py', 'src/network/im_client_base.py',
        'src/network/im_conversation.py', 'src/network/im_call_ui.py',
        'src/network/whatsapp_titan_gui.py', 'src/network/messenger_titan_gui.py',
        'src/network/im_web/base.py',
    ],
    'titannet': [
        'src/network/titan_net.py', 'src/network/titan_net_gui.py', 'src/network/titan_net_forum_gui.py', 'src/network/titan_net_mod_components.py', 'src/network/feedback_hub.py', 'src/network/remote_ui.py', 'src/network/server_sounds.py', 'src/network/server_sounds_gui.py', 'src/system/klangomode.py',
        # Mail: the mailbox/reader/composer and the rich-body renderer
        'src/network/mail_gui.py', 'src/network/mail_format.py'
    ],
    'system': ['src/titan_core/tce_system.py', 'src/titan_core/tce_system_net.py', 'src/system/system_monitor.py', 'src/system/updater.py', 'src/system/lockscreen_monitor_improved.py', 'src/ui/shutdown_question.py', 'src/system/mic_permission.py',
               # The notification area: the reader and the list over it
               'src/system/tray_icons.py', 'src/system/system_tray_list.py'],
    'controller': ['src/controller/controller_ui.py', 'src/controller/controller_modes.py', 'src/controller/controller_vibrations.py'],
    'help': ['src/ui/help.py'],
    'sound': ['src/titan_core/sound.py', 'src/titan_core/tsounds.py', 'src/titan_core/stereo_speech.py'],
    'accessibility': ['src/accessibility/messages.py'],
    'classicstartmenu': ['src/ui/classic_start_menu.py'],
    'eltenclient': ['src/eltenlink_client/elten_client.py', 'src/eltenlink_client/elten_gui.py', 'src/eltenlink_client/elten_voip_client.py', 'src/eltenlink_client/accountmanagement.py'],
    'window_switcher': ['src/ui/window_switcher.py'],
    'shell': ['src/shell/a11y.py', 'src/shell/controls.py',
              'src/shell/taskbar.py', 'src/shell/desktop.py',
              'src/shell/start_menu.py', 'src/shell/shell_manager.py',
              'src/shell/shell_actions.py', 'src/shell/run_dialog.py', 'src/shell/quick_launch.py',
              'src/shell/shutdown_dialog.py',
              'src/shell/taskbar_properties.py',
              # The file browser: My Computer, drives and folders
              'src/shell/explorer.py', 'src/shell/fileops.py'],
    'interactive_games': ['src/network/interactive_games.py', 'src/network/interactive_game_session.py'],
    'buffers_system': ['src/buffers/buffer_announcer.py', 'src/buffers/buffer_system.py', 'src/buffers/tts_buffer.py', 'src/buffers/ai_buffer.py'],
    'ai': ['src/ai/ai_provider.py', 'src/ai/ai_creation_kit.py', 'src/ai/ai_agent.py', 'src/ai/agent_tools.py', 'src/ai/titan_tools.py', 'src/ai/action_tools.py', 'src/ai/ai_agent_gui.py', 'src/ai/assistant/personas.py', 'src/ai/assistant/voice_io.py', 'src/ai/assistant/voice_assistant.py', 'src/ai/assistant/assistant_gui.py', 'src/ai/assistant/hotkeys.py', 'src/ai/assistant/headless.py', 'src/ai/assistant/reminder_watcher.py', 'src/ai/ocr/mimic.py', 'src/ai/ocr/form_view.py', 'src/ai/ocr/controls.py', 'src/ai/ocr/overlay.py'],
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


def check_translations():
    """Report entries that now say the wrong thing.

    ``pybabel update`` never leaves a new string empty - it fills it with the
    nearest old translation and marks it fuzzy. Left unread, that guess ships:
    "Notifications" once displayed as "Kod weryfikacyjny". This step is here so
    the guesses are visible the moment they are made, not months later.
    """
    print("\nChecking the catalogs...")
    try:
        from src.scripts.check_translations import run as check_run
    except ImportError:
        # Also runnable as a loose script, without the package on sys.path.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        try:
            from check_translations import run as check_run
        except ImportError as exc:
            print(f"  [ERROR] Could not load the checker: {exc}")
            return True

    return check_run(quiet=True) == 0


def main():
    """Main extraction process."""
    print("=" * 60)
    print("Modular Translation Extraction")
    print("=" * 60)

    # Create languages directory if it doesn't exist
    os.makedirs('languages', exist_ok=True)

    # Extract all domains
    print("\n[1/4] Extracting translatable strings...")
    for domain, files in DOMAIN_FILES.items():
        extract_domain(domain, files)

    # Update .po files
    print("\n[2/4] Updating .po files...")
    for domain in DOMAIN_FILES.keys():
        update_po_files(domain)

    # Compile translations
    print("\n[3/4] Compiling translations...")
    compile_translations()

    # Check what the update just guessed
    print("\n[4/4] Checking for wrong translations...")
    clean = check_translations()

    print("\n" + "=" * 60)
    print("Translation extraction complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Edit .po files in languages/*/LC_MESSAGES/")
    print("2. Run 'python extract_translations.py' to recompile")
    print("   or 'pybabel compile -d languages' to just compile")
    if not clean:
        print("\n3. Fix the entries listed above - they are text a user will")
        print("   read that says something other than what the code meant.")
        print("   Details: python src/scripts/check_translations.py")
    return 0 if clean else 1

if __name__ == '__main__':
    sys.exit(main())
