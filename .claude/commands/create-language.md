# Create Language Translation

Interactive wizard to create a new language translation for TCE Launcher.

## Process:

1. **Ask for Language Details:**
   - Language code (e.g., `ru` for Russian, `de` for German, `fr` for French)
   - Language name in English (e.g., "Russian", "German", "French")
   - Language name in native language (e.g., "Русский", "Deutsch", "Français")

2. **Translation Domains:**

   TCE Launcher uses modular translations organized by domain. You need to initialize ALL domains for a complete translation:

   **Core Domains:**
   - `gui` - Main GUI (src/ui/gui.py)
   - `invisibleui` - Invisible UI (src/ui/invisibleui.py)
   - `main` - Main program (main.py)
   - `menu` - Menu system (src/ui/menu.py)
   - `settings` - Settings (src/settings/settings.py, src/ui/settingsgui.py)

   **Feature Domains:**
   - `apps` - Application manager (src/titan_core/app_manager.py)
   - `games` - Game manager (src/titan_core/game_manager.py)
   - `components` - Component manager (src/titan_core/component_manager.py, src/ui/componentmanagergui.py)
   - `notifications` - Notifications (src/system/notifications.py, src/ui/notificationcenter.py)
   - `controller` - Controllers (src/controller/controller_ui.py, src/controller/controller_modes.py)
   - `help` - Help system (src/ui/help.py)
   - `sound` - Sound system (src/titan_core/sound.py)
   - `system` - System functions (src/titan_core/tce_system.py, src/system/system_monitor.py, src/system/updater.py)

   **Network Domains:**
   - `network` - Network/messengers (src/network/messenger_gui.py, src/network/telegram_gui.py, etc.)
   - `titannet` - Titan-Net (src/network/titan_net.py, src/network/titan_net_gui.py)
   - `eltenclient` - EltenLink client (src/network/elten_client.py, src/network/elten_gui.py)

   **Special Domains:**
   - `accessibility` - Accessibility messages (src/accessibility/messages.py)
   - `classicstartmenu` - Classic Start Menu (src/ui/classic_start_menu.py)
   - `exit_dialog` - Exit confirmation dialog (src/ui/shutdown_question.py)

3. **Initialize Language for All Domains:**

   For each domain, run:
   ```bash
   pybabel init -l {language_code} -d languages -i languages/{domain}.pot -D {domain}
   ```

   **Example for Russian (ru):**
   ```bash
   pybabel init -l ru -d languages -i languages/gui.pot -D gui
   pybabel init -l ru -d languages -i languages/invisibleui.pot -D invisibleui
   pybabel init -l ru -d languages -i languages/main.pot -D main
   pybabel init -l ru -d languages -i languages/menu.pot -D menu
   pybabel init -l ru -d languages -i languages/settings.pot -D settings
   pybabel init -l ru -d languages -i languages/apps.pot -D apps
   pybabel init -l ru -d languages -i languages/games.pot -D games
   pybabel init -l ru -d languages -i languages/components.pot -D components
   pybabel init -l ru -d languages -i languages/notifications.pot -D notifications
   pybabel init -l ru -d languages -i languages/network.pot -D network
   pybabel init -l ru -d languages -i languages/titannet.pot -D titannet
   pybabel init -l ru -d languages -i languages/eltenclient.pot -D eltenclient
   pybabel init -l ru -d languages -i languages/system.pot -D system
   pybabel init -l ru -d languages -i languages/controller.pot -D controller
   pybabel init -l ru -d languages -i languages/help.pot -D help
   pybabel init -l ru -d languages -i languages/sound.pot -D sound
   pybabel init -l ru -d languages -i languages/accessibility.pot -D accessibility
   pybabel init -l ru -d languages -i languages/classicstartmenu.pot -D classicstartmenu
   pybabel init -l ru -d languages -i languages/exit_dialog.pot -D exit_dialog
   ```

4. **Verify Directory Structure:**

   After initialization, the structure should be:
   ```
   languages/
   ├── {language_code}/
   │   └── LC_MESSAGES/
   │       ├── gui.po
   │       ├── invisibleui.po
   │       ├── main.po
   │       ├── menu.po
   │       ├── settings.po
   │       ├── apps.po
   │       ├── games.po
   │       ├── components.po
   │       ├── notifications.po
   │       ├── network.po
   │       ├── titannet.po
   │       ├── eltenclient.po
   │       ├── system.po
   │       ├── controller.po
   │       ├── help.po
   │       ├── sound.po
   │       ├── accessibility.po
   │       ├── classicstartmenu.po
   │       └── exit_dialog.po
   ```

5. **Translation Workflow:**

   **Step 1: Edit .po files**
   - Open each `.po` file in `languages/{language_code}/LC_MESSAGES/`
   - Translate `msgid` strings to `msgstr`
   - Use a translation editor like Poedit or edit manually

   **Example:**
   ```po
   msgid "Main Menu"
   msgstr "Главное меню"

   msgid "Settings"
   msgstr "Настройки"
   ```

   **Step 2: Compile translations**
   ```bash
   pybabel compile -d languages
   ```

   This creates `.mo` files which are used by the application.

6. **Test Translation:**
   - Launch TCE Launcher
   - Go to Settings
   - Change language to your new language
   - Restart the application
   - Verify all translated strings appear correctly

7. **Update Translation (after code changes):**
   ```bash
   # Extract new strings (run this from project root)
   python src/scripts/extract_translations.py

   # Update existing translations
   pybabel update -l {language_code} -d languages -i languages/gui.pot -D gui
   # Repeat for all domains...

   # Compile after translating new strings
   pybabel compile -d languages
   ```

## Translation Best Practices:

1. **Context matters** - Understand where the string is used
2. **Keep formatting** - Preserve `{}` placeholders, `\n` newlines
3. **Match tone** - Maintain formal/informal tone consistently
4. **Test thoroughly** - Check all menus, dialogs, and notifications
5. **Use native speakers** - Get review from native language speakers
6. **Keep it concise** - Match original string length when possible

## Quick Command Reference:

```bash
# All domains list
DOMAINS="gui invisibleui main menu settings apps games components notifications network titannet eltenclient system controller help sound accessibility classicstartmenu exit_dialog"

# Initialize ALL domains for a new language (e.g., Russian)
for domain in $DOMAINS; do
    pybabel init -l ru -d languages -i languages/${domain}.pot -D ${domain}
done

# Compile all translations
pybabel compile -d languages

# Update existing translations (after code changes)
python src/scripts/extract_translations.py
for domain in $DOMAINS; do
    pybabel update -l ru -d languages -i languages/${domain}.pot -D ${domain}
done
pybabel compile -d languages
```

## Windows Quick Command:

For Windows Command Prompt:
```cmd
for %d in (gui invisibleui main menu settings apps games components notifications network titannet eltenclient system controller help sound accessibility classicstartmenu exit_dialog) do pybabel init -l ru -d languages -i languages/%d.pot -D %d
```

For Windows PowerShell:
```powershell
@('gui','invisibleui','main','menu','settings','apps','games','components','notifications','network','titannet','eltenclient','system','controller','help','sound','accessibility','classicstartmenu','exit_dialog') | ForEach-Object { pybabel init -l ru -d languages -i languages/$_.pot -D $_ }
```

## Common Language Codes:

- `en` - English
- `pl` - Polish (default)
- `ru` - Russian
- `de` - German
- `fr` - French
- `es` - Spanish
- `it` - Italian
- `pt` - Portuguese
- `cs` - Czech
- `sk` - Slovak
- `uk` - Ukrainian

## Action:

Ask the user for the language code and create all necessary translation files using pybabel init commands.
