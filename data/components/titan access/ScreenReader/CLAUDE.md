# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build Commands

```bash
dotnet restore    # Restore NuGet packages
dotnet build      # Build the project
dotnet run        # Build and run the application
```

## Project Overview

This is a **Polish-language Screen Reader** for Windows, designed to provide accessibility for visually impaired users. It uses Windows UI Automation API to navigate and announce UI elements with speech and audio cues.

Architecture is inspired by NVDA screen reader with modular design including AppModules, VirtualBuffers, and BrowseMode.

## Architecture

```
Program.cs                    → Entry point, Windows Forms message loop
    ↓
ScreenReaderEngine.cs         → Central orchestrator (singleton)
    ↓
┌─────────────────────────────────────────────────────────────────────┐
│  AppModules/                → Application-specific modules          │
│    AppModuleManager.cs      → Manages active modules per process   │
│    ExplorerModule.cs        → Windows Explorer support             │
│    ChromiumBase.cs          → Chrome/Edge browser support          │
│                                                                     │
│  VirtualBuffers/            → Web content virtualization           │
│    VirtualBuffer.cs         → Flat text representation of docs     │
│    VirtualBufferNode.cs     → Individual element in buffer         │
│                                                                     │
│  BrowseMode/                → Browse mode for web navigation       │
│    BrowseModeHandler.cs     → Toggle browse/focus mode             │
│    QuickNavTypes.cs         → Single-letter navigation (H,L,B...)  │
│                                                                     │
│  Keyboard/                  → Input handling                       │
│    KeyboardHookManager.cs   → WH_KEYBOARD_LL hook with LLKHF flags │
│    InsertKeyHandler.cs      → Extended vs NumPad Insert detection  │
│                                                                     │
│  EditableText/              → Text field navigation                │
│    EditableTextHandler.cs   → Character/word/line reading          │
│                                                                     │
│  InputGestures/             → Gesture system (Insert+...)          │
│  Speech/                    → TTS (SAPI5 + eSpeak)                 │
│  UIAutomation/              → UI Automation helpers                │
└─────────────────────────────────────────────────────────────────────┘
```

## Key Subsystems

### AppModules (AppModules/)
Port of NVDA's appModuleHandler - per-application behavior customization:
- `AppModuleBase.cs` - Base class with hooks for OnGainFocus, OnLoseFocus, CustomizeElement
- `ExplorerModule.cs` - Windows Explorer: file announcements, tree navigation, properties
- `ChromiumBase.cs` - Shared base for Chrome/Edge with virtual buffer activation

### VirtualBuffer (VirtualBuffers/)
Port of NVDA's virtualBuffers - flat text representation of web documents:
- `VirtualBuffer.cs` - Builds buffer from UI Automation tree, manages caret position
- `VirtualBufferNode.cs` - Node with offset mapping, role, state, ARIA attributes
- Enables browse mode navigation independent of actual focus

### BrowseMode (BrowseMode/)
Port of NVDA's browseMode - web navigation:
- `BrowseModeHandler.cs` - Toggle pass-through, quick navigation, line reading
- `QuickNavTypes.cs` - Maps keys to element types (H→heading, L→link, B→button, etc.)

### Keyboard (Keyboard/)
Enhanced keyboard hook with Insert key detection and NumPad navigation:
- `KeyboardHookManager.cs` - Uses `LLKHF_EXTENDED` flag to distinguish Insert/NumPad
- `InsertKeyHandler.cs` - `GetInsertKeyType()` returns ExtendedInsert or NumpadInsert
- `NVDAModifierConfig` enum - Configurable modifier keys (default: both Insert keys)

**NumPad Object Navigation** (works with NumLock OFF):
- `NumPad 4` - Previous sibling element (left)
- `NumPad 6` - Next sibling element (right)
- `NumPad 8` - Parent element (up)
- `NumPad 2` - First child element (down)
- `NumPad 5` - Read current element
- `NumPad Enter` - Activate current element

### EditableText (EditableText/)
- `EditableTextHandler.cs` - TextPattern-based navigation with Polish phonetic alphabet

### Speech System (Speech/)
- `SpeechManager.cs` - Dual synthesizer: Windows SAPI5 + eSpeak-ng
- `ESpeakEngine.cs` - Dynamic DLL loading with proper voice detection
- `SoundManager.cs` - OGG Vorbis playback for UI sounds

**eSpeak Voice Detection:**
- Uses dynamic LoadLibrary/GetProcAddress for proper DLL loading
- Sets DLL directory for MinGW dependencies (libgcc, libwinpthread)
- Retrieves voice list via espeak_ListVoices() API
- Fallback to file scanning if API fails

### Input System (InputGestures/)
- `GestureManager.cs` - Maps Insert+key combinations to actions
- `GestureBinding.cs` - Individual gesture definition with metadata

## Key Dependencies

- **NAudio** / **NAudio.Vorbis** - Audio playback
- **System.Speech** - SAPI5 text-to-speech
- **UIAutomationClient** / **UIAutomationTypes** - Windows UI Automation

## Insert Key Detection

The `InsertKeyHandler` distinguishes between keyboard Insert keys using `LLKHF_EXTENDED` flag:
- **Extended Insert** (above Home/End): `flags & 0x01 != 0`
- **NumPad Insert** (Num0 with NumLock off): `flags & 0x01 == 0`

Both are enabled as NVDA modifier by default (`NVDAModifierConfig.Default`).

## Browse Mode Quick Navigation

In browse mode (web documents), single letters navigate by element type:
- `H` - Headings (1-6 for specific levels)
- `K` - Links
- `B` - Buttons
- `E` - Edit fields
- `T` - Tables
- `L` - Lists
- `I` - List items
- `G` - Graphics

Shift+key moves backwards.

## Platform Requirements

- Windows OS only (Windows Forms, UI Automation API, global keyboard hooks)
- .NET 8.0 runtime
- Polish TTS voice recommended for SAPI5

## Language Note

All user-facing text uses Polish. Element type announcements use Polish translations (e.g., "Pole edycji" for edit fields, "Lista" for lists). Polish phonetic alphabet is used for character spelling.
