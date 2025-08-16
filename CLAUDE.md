# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Installation and Setup
```bash
pip install -r requirements.txt
```

### Running the Application
```bash
python main.py
```

### Compilation to Executable
```bash
python compiletorelease.py
```
This uses Nuitka to compile the application to a standalone executable in the `output` directory.

### Translation Management
```bash
# Extract translatable strings (uses babel)
pybabel extract -o messages.pot --input-dirs=.

# Update language files
pybabel update -l pl -d languages -i messages.pot
pybabel update -l en -d languages -i messages.pot

# Compile translations
pybabel compile -d languages
```

## Project Architecture

**TCE Launcher** is an accessible desktop environment/launcher written in wxPython with a modular architecture:

### Core System
- `main.py`: Entry point, handles startup, language initialization, and command-line arguments
- `gui.py`: Main wxPython GUI with `TitanApp` class, taskbar integration, application/game lists
- `invisibleui.py`: Alternative non-visual interface for screen readers
- `menu.py`: MenuBar implementation for system menus

### Plugin System
- **Applications**: Located in `data/applications/`, each has `__app.TCE` config file defining name, description, main file
- **Components**: Located in `data/components/`, each has `__component__.TCE` config file, loaded by `ComponentManager`
- Applications use format: `name_pl=`, `name_en=`, `openfile=`, `shortname=`
- Components use INI format with `[component]` section

### Core Managers
- `app_manager.py`: Handles loading/running applications from `data/applications/`
- `game_manager.py`: Manages games directory and game launching
- `component_manager.py`: Loads and manages components, provides menu integration hooks

### System Features
- `sound.py`: Audio system with theme support, uses `accessible_output3` for TTS
- `translation.py`: i18n support using gettext, defaults to Polish (`pl`)
- `settings.py`: Configuration management with JSON settings file
- `notifications.py`: System notifications and status monitoring
- `titan_net.py`: Network functionality and server communication

### Audio Themes
Located in `sfx/` directory with multiple theme folders (`default`, `longhorn`, `ubuntu_emacspeak`, etc.)

### Titan-Net Messaging System
- `srv/titan_server.py`: HTTP (port 8000) + WebSocket (port 8001) server for real-time messaging
- `titan_net.py`: WebSocket client with async messaging capabilities
- `titan_net_gui.py`: Standalone chat GUI (optional)
- Integrated into main GUI with private messages, online users, chat history
- Audio notifications from `sfx/*/titannet/` directory
- SQLite database for users and messages

### Key Dependencies
- wxPython for GUI
- accessible_output3 for screen reader output
- pygame for audio
- Nuitka for compilation
- babel for internationalization
- websockets for real-time messaging
- requests for HTTP API calls

The system is designed for accessibility with extensive screen reader support and keyboard navigation.