using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Windows.Automation;
using ScreenReader.InputGestures;
using ScreenReader.BrowseMode;
using ScreenReader.EditableText;
using ScreenReader.Keyboard;
using ScreenReader.Interop;
using ScreenReader.Terminal;
using ScreenReader.Accessibility;
using ScreenReader.Settings;
using ScreenReader.Hints;
using ScreenReader.Navigation;
using ScreenReader.VirtualScreen;
using ScreenReader.Speech;
using ScreenReader.KeyboardShortcuts;
using ScreenReader.Localization;
using KeyboardHook = ScreenReader.Keyboard.KeyboardHookManager;

namespace ScreenReader;

public class ScreenReaderEngine : IDisposable
{
    // Singleton dla dostępu z innych komponentów
    public static ScreenReaderEngine? Instance { get; private set; }

    private readonly SpeechManager _speechManager;
    private readonly SettingsManager _settings;

    /// <summary>Dostęp do menadżera mowy</summary>
    public SpeechManager SpeechManager => _speechManager;

    /// <summary>Bieżący element (współdzielony między nawigacją obiektową a virtual screen)</summary>
    public AutomationElement? CurrentElement
    {
        get => _currentElement;
        set => _currentElement = value;
    }

    /// <summary>Pozycja przestrzenna bieżącego elementu (azymut, elewacja) dla 3D audio</summary>
    public (float azimuth, float elevation) CurrentElementPosition { get; set; }

    private readonly SoundManager _soundManager;
    private readonly FocusTracker _focusTracker;
    private readonly KeyboardHook _keyboardHook;
    private readonly EditFieldNavigator _editNavigator;
    private readonly GestureManager _gestureManager;

    // Komponenty
    private readonly BrowseModeHandler _browseModeHandler;
    private readonly EditableTextHandler _editableTextHandler;
    private readonly DialManager _dialManager;
    private readonly LiveRegionMonitor _liveRegionMonitor;
    private readonly TerminalHandler _terminalHandler;
    private readonly AccessibilityProviderManager _accessibilityManager;
    private readonly HintManager _hintManager;
    private readonly ImportantPlacesManager _importantPlacesManager;
    private readonly VirtualScreenManager _virtualScreenManager;
    private readonly KeyFileManager _keyFileManager;
    private readonly AppModules.AppModuleManager _appModuleManager;

    private DialogMonitor? _dialogMonitor;
    private AutomationElement? _currentElement;
    private AutomationElement? _lastWindow;
    private AutomationElement? _currentWindow; // Bieżące okno dla ograniczonej nawigacji
    private AutomationElement? _currentListParent; // Śledzenie kontekstu listy
    private AutomationElement? _currentGroupParent; // Śledzenie kontekstu grupy
    private AutomationElement? _lastMenuParent; // Śledzenie kontekstu menu
    private AutomationElement? _lastMenuBar; // Pasek menu dla bieżącego menu
    private bool _isInMenu; // Czy aktualnie jesteśmy w menu
    private bool _isInMenuBar; // Czy aktualnie jesteśmy w pasku menu
    private bool _isInList; // Czy aktualnie jesteśmy w liście
    private int _hierarchyLevel; // Bieżący poziom hierarchii dla nawigacji obiektowej
    private bool _disposed;
    private System.Threading.Timer? _hookHealthTimer; // Timer dla sprawdzania stanu hooka

    // Stan aplikacji
    private int _currentProcessId;
    private string? _currentProcessName;
    private bool _isInBrowser;
    private bool _isInComboBox; // Czy jesteśmy w polu kombi
    private bool _isInTCEProcess; // Czy jesteśmy w procesie TCE/Titan

    // Echo klawiatury
    private KeyboardEchoMode _keyboardEchoMode;

    // Menu dialog
    private ScreenReaderMenuDialog? _menuDialog;

    // Tray icon
    private System.Windows.Forms.NotifyIcon? _trayIcon;

    // NVDA Controller Bridge
    private NVDAControllerBridge? _nvdaBridge;

    // Nazwy procesów przeglądarek
    private static readonly HashSet<string> BrowserProcessNames = new(StringComparer.OrdinalIgnoreCase)
    {
        "chrome", "msedge", "firefox", "brave", "vivaldi", "opera", "chromium", "iexplore", "waterfox", "librewolf"
    };

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    /// <summary>Aktualny tryb echa klawiatury</summary>
    public KeyboardEchoMode KeyboardEchoMode => _keyboardEchoMode;

    public ScreenReaderEngine()
    {
        Instance = this;

        // Zarejestruj program jako czytnik ekranu w systemie
        ScreenReaderFlag.Enable();

        _settings = SettingsManager.Instance;
        _speechManager = new SpeechManager();
        var soundsPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "sfx");
        _soundManager = new SoundManager(soundsPath);
        _focusTracker = new FocusTracker();
        _keyboardHook = new KeyboardHook();
        _editNavigator = new EditFieldNavigator(_speechManager);
        _gestureManager = new GestureManager(_speechManager);

        // Komponenty
        _browseModeHandler = new BrowseModeHandler();
        _editableTextHandler = new EditableTextHandler();
        _dialManager = new DialManager();
        _liveRegionMonitor = new LiveRegionMonitor();
        _terminalHandler = new TerminalHandler();
        _accessibilityManager = new AccessibilityProviderManager();
        _hintManager = new HintManager(_speechManager);
        _importantPlacesManager = new ImportantPlacesManager(_speechManager, _soundManager);
        _virtualScreenManager = new VirtualScreenManager(_speechManager, _soundManager, _dialManager);
        _keyFileManager = new KeyFileManager();
        _appModuleManager = new AppModules.AppModuleManager(_speechManager);

        // Podłącz eventy wirtualnego ekranu
        _virtualScreenManager.EnabledChanged += OnVirtualScreenEnabledChanged;
        _virtualScreenManager.ElementChanged += OnVirtualScreenElementChanged;

        // Podłącz eventy terminala
        _terminalHandler.OutputReceived += OnTerminalOutput;
        _terminalHandler.TextChanged += OnTerminalTextChanged;

        // Podłącz eventy pokrętła
        _dialManager.EnabledChanged += OnDialEnabledChanged;

        // Podłącz eventy browse mode
        _browseModeHandler.Announce += text => _speechManager.Speak(text);
        _browseModeHandler.ModeChanged += OnBrowseModeChanged;

        // Podłącz eventy edytowalnego tekstu
        _editableTextHandler.Announce += text => _speechManager.Speak(text);

        // Podłącz eventy LiveRegion
        _liveRegionMonitor.LiveRegionChanged += OnLiveRegionChanged;
        _liveRegionMonitor.TextChanged += OnDynamicTextChanged;
        _liveRegionMonitor.StructureChanged += OnStructureChanged;

        // Wire up events
        _focusTracker.FocusChanged += OnFocusChanged;
        _keyboardHook.ReadCurrentElement += OnReadCurrentElement;
        _keyboardHook.MoveToNextElement += OnMoveToNextElement;
        _keyboardHook.MoveToPreviousElement += OnMoveToPreviousElement;
        _keyboardHook.MoveToParent += OnMoveToParent;
        _keyboardHook.MoveToFirstChild += OnMoveToFirstChild;
        _keyboardHook.StopSpeaking += OnStopSpeaking;
        _keyboardHook.ClickAction += OnClickAction;
        _keyboardHook.ShowMenu += OnShowMenu;

        // Edit field navigation events
        _keyboardHook.MoveToPreviousCharacter += OnMoveToPreviousCharacter;
        _keyboardHook.MoveToNextCharacter += OnMoveToNextCharacter;
        _keyboardHook.MoveToPreviousLine += OnMoveToPreviousLine;
        _keyboardHook.MoveToNextLine += OnMoveToNextLine;
        _keyboardHook.MoveToPreviousWord += OnMoveToPreviousWord;
        _keyboardHook.MoveToNextWord += OnMoveToNextWord;
        _keyboardHook.MoveToStart += OnMoveToStart;
        _keyboardHook.MoveToEnd += OnMoveToEnd;
        _keyboardHook.ReadCurrentChar += OnReadCurrentChar;
        _keyboardHook.ReadCurrentWord += OnReadCurrentWord;
        _keyboardHook.ReadCurrentLine += OnReadCurrentLine;
        _keyboardHook.ReadPosition += OnReadPosition;

        // Connect gesture processing
        _keyboardHook.GestureProcessed += OnGestureProcessed;

        // Connect browse mode toggle gesture (Insert+Space)
        _gestureManager.ToggleBrowseMode += OnToggleBrowseMode;

        // Connect quick nav for browse mode
        _keyboardHook.QuickNavProcessed += OnQuickNavProcessed;

        // Connect arrow navigation for browse mode
        _keyboardHook.BrowseModeArrowNavigation += OnBrowseModeArrowNavigation;

        // Connect keyboard echo events
        _keyboardHook.CharTyped += OnCharTyped;
        _keyboardHook.WordTyped += OnWordTyped;

        // Connect backspace deletion events
        _keyboardHook.CharacterBeingDeleted += OnCharacterBeingDeleted;
        _keyboardHook.CharacterDeleted += OnCharacterDeleted;

        // Connect dial (pokrętło) events
        _keyboardHook.ToggleDial += OnToggleDial;
        _keyboardHook.DialPreviousCategory += OnDialPreviousCategory;
        _keyboardHook.DialNextCategory += OnDialNextCategory;
        _keyboardHook.DialPreviousItem += OnDialPreviousItem;
        _keyboardHook.DialNextItem += OnDialNextItem;
        _keyboardHook.NumpadSlashAction += OnNumpadSlashAction;

        // Connect linear navigation events
        _keyboardHook.LinearMoveToNext += OnLinearMoveToNext;
        _keyboardHook.LinearMoveToPrevious += OnLinearMoveToPrevious;
        _keyboardHook.ToggleLinearNavigation += OnToggleLinearNavigation;

        // Connect ComboBox navigation event
        _keyboardHook.ComboBoxArrowNavigation += OnComboBoxArrowNavigation;

        // Connect toggle key events (CapsLock, NumLock, ScrollLock)
        _keyboardHook.CapsLockToggled += OnCapsLockToggled;
        _keyboardHook.NumLockToggled += OnNumLockToggled;
        _keyboardHook.ScrollLockToggled += OnScrollLockToggled;

        // Connect application shortcut event (Ctrl+O, Alt+F, etc.)
        _keyboardHook.ApplicationShortcutPressed += OnApplicationShortcutPressed;

        // Register additional gestures
        RegisterCustomGestures();

        // Initialize tray icon
        InitializeTrayIcon();

        // Initialize NVDA Controller Bridge (kompatybilność z grami/aplikacjami wspierającymi NVDA)
        _nvdaBridge = new NVDAControllerBridge(_speechManager);

        // Załaduj ustawienia echa klawiatury
        LoadKeyboardEchoSettings();
    }

    /// <summary>
    /// Ładuje ustawienia echa klawiatury z konfiguracji
    /// </summary>
    private void LoadKeyboardEchoSettings()
    {
        var setting = _settings.KeyboardEcho;
        _keyboardEchoMode = setting switch
        {
            Settings.KeyboardEchoSetting.None => KeyboardEchoMode.None,
            Settings.KeyboardEchoSetting.Characters => KeyboardEchoMode.Characters,
            Settings.KeyboardEchoSetting.Words => KeyboardEchoMode.Words,
            Settings.KeyboardEchoSetting.CharactersAndWords => KeyboardEchoMode.WordsAndChars,
            _ => KeyboardEchoMode.Characters
        };

        Console.WriteLine($"Echo klawiatury: {_keyboardEchoMode.GetPolishName()}");
    }

    /// <summary>
    /// Obsługa zmiany stanu CapsLock
    /// </summary>
    private void OnCapsLockToggled(bool isOn)
    {
        var mode = _settings.ToggleKeysMode;

        if (mode == AnnouncementMode.Sound || mode == AnnouncementMode.SpeechAndSound)
        {
            if (isOn)
                _soundManager.PlayKeyOn();
            else
                _soundManager.PlayKeyOff();
        }

        if (mode == AnnouncementMode.Speech || mode == AnnouncementMode.SpeechAndSound)
        {
            if (isOn)
                _speechManager.Speak(L.T("toggle.capsLockOn"));
            else
                _speechManager.Speak(L.T("toggle.capsLockOff"));
        }
    }

    /// <summary>
    /// Obsługa zmiany stanu NumLock
    /// </summary>
    private void OnNumLockToggled(bool isOn)
    {
        var mode = _settings.ToggleKeysMode;

        if (mode == AnnouncementMode.Sound || mode == AnnouncementMode.SpeechAndSound)
        {
            if (isOn)
                _soundManager.PlayKeyOn();
            else
                _soundManager.PlayKeyOff();
        }

        if (mode == AnnouncementMode.Speech || mode == AnnouncementMode.SpeechAndSound)
        {
            if (isOn)
                _speechManager.Speak(L.T("toggle.numpadNumeric"));
            else
                _speechManager.Speak(L.T("toggle.numpadTceCursor"));
        }
    }

    /// <summary>
    /// Obsługa zmiany stanu ScrollLock
    /// </summary>
    private void OnScrollLockToggled(bool isOn)
    {
        var mode = _settings.ToggleKeysMode;

        if (mode == AnnouncementMode.Sound || mode == AnnouncementMode.SpeechAndSound)
        {
            if (isOn)
                _soundManager.PlayKeyOn();
            else
                _soundManager.PlayKeyOff();
        }

        if (mode == AnnouncementMode.Speech || mode == AnnouncementMode.SpeechAndSound)
        {
            if (isOn)
                _speechManager.Speak(L.T("toggle.scrollLockOn"));
            else
                _speechManager.Speak(L.T("toggle.scrollLockOff"));
        }
    }

    /// <summary>
    /// Obsługa skrótów aplikacji (Ctrl+O, Alt+F, etc.)
    /// Oznajmia nazwę komendy z pliku .KEY
    /// </summary>
    private void OnApplicationShortcutPressed(System.Windows.Forms.Keys key, bool ctrl, bool alt, bool shift)
    {
        try
        {
            // Zbuduj string skrótu
            string shortcut = KeysToShortcutString(key, ctrl, alt, shift);
            Console.WriteLine($"ApplicationShortcut: {shortcut}");

            // Sprawdź plik .KEY dla bieżącej aplikacji
            if (!string.IsNullOrEmpty(_currentProcessName))
            {
                string? commandName = _keyFileManager.GetShortcutDescription(_currentProcessName, shortcut);
                if (!string.IsNullOrEmpty(commandName))
                {
                    Console.WriteLine($"KeyFile command: {commandName}");
                    _speechManager.Speak(commandName, interrupt: true);
                }
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"OnApplicationShortcutPressed Error: {ex.Message}");
        }
    }

    /// <summary>
    /// Konwertuje skrót z Keys enum na string format
    /// </summary>
    private static string KeysToShortcutString(System.Windows.Forms.Keys keys, bool ctrl, bool alt, bool shift)
    {
        List<string> parts = new();

        if (ctrl) parts.Add("Ctrl");
        if (alt) parts.Add("Alt");
        if (shift) parts.Add("Shift");

        // Usuń modyfikatory z keys
        var keyCode = keys & ~System.Windows.Forms.Keys.Modifiers;

        // Konwertuj key code na string
        string keyName = keyCode.ToString();

        // Specjalne przypadki
        keyName = keyName switch
        {
            "D0" => "0",
            "D1" => "1",
            "D2" => "2",
            "D3" => "3",
            "D4" => "4",
            "D5" => "5",
            "D6" => "6",
            "D7" => "7",
            "D8" => "8",
            "D9" => "9",
            "Oemcomma" => ",",
            "OemPeriod" => ".",
            "OemQuestion" => "/",
            "OemSemicolon" => ";",
            "OemQuotes" => "'",
            "OemOpenBrackets" => "[",
            "OemCloseBrackets" => "]",
            "OemPipe" => "\\",
            "OemMinus" => "-",
            "Oemplus" => "+",
            _ => keyName
        };

        parts.Add(keyName);

        return string.Join("+", parts);
    }

    /// <summary>
    /// Inicjalizacja ikony w tray (zasobnik systemowy)
    /// </summary>
    private void InitializeTrayIcon()
    {
        if (!System.Windows.Forms.Application.MessageLoop)
            return;

        _trayIcon = new System.Windows.Forms.NotifyIcon
        {
            Text = L.T("tray.title"),
            Visible = true,
            Icon = System.Drawing.SystemIcons.Application // Tymczasowa ikona systemowa
        };

        // Utwórz menu kontekstowe
        var contextMenu = new System.Windows.Forms.ContextMenuStrip();

        var settingsItem = new System.Windows.Forms.ToolStripMenuItem(L.T("tray.settings"));
        settingsItem.Click += (s, e) => ShowSettings();
        contextMenu.Items.Add(settingsItem);

        var helpItem = new System.Windows.Forms.ToolStripMenuItem(L.T("tray.help"));
        helpItem.Click += (s, e) => ShowHelp();
        contextMenu.Items.Add(helpItem);

        contextMenu.Items.Add(new System.Windows.Forms.ToolStripSeparator());

        var exitItem = new System.Windows.Forms.ToolStripMenuItem(L.T("tray.exit"));
        exitItem.Click += (s, e) =>
        {
            Console.WriteLine("Zamykanie czytnika ekranu...");
            _speechManager.Speak(L.T("engine.closing"));
            System.Windows.Forms.Application.Exit();
        };
        contextMenu.Items.Add(exitItem);

        _trayIcon.ContextMenuStrip = contextMenu;

        // Podwójne kliknięcie otwiera ustawienia
        _trayIcon.DoubleClick += (s, e) => ShowSettings();
    }

    /// <summary>
    /// Obsługa zmiany LiveRegion (komunikaty dostępności)
    /// </summary>
    private void OnLiveRegionChanged(string text, bool isAssertive)
    {
        if (string.IsNullOrWhiteSpace(text))
            return;

        Console.WriteLine($"LiveRegion: {text} (assertive: {isAssertive})");
        _speechManager.Speak(text, interrupt: isAssertive);
    }

    /// <summary>
    /// Obsługa dynamicznej zmiany tekstu
    /// </summary>
    private void OnDynamicTextChanged(string text, TextChangeType changeType)
    {
        if (string.IsNullOrWhiteSpace(text))
            return;

        // W terminalu ogłaszaj wszystkie zmiany
        if (_terminalHandler.IsInTerminal)
        {
            Console.WriteLine($"Terminal TextChange ({changeType}): {text}");
            _speechManager.Speak(text, interrupt: false);
            return;
        }

        // Dla innych aplikacji - tylko niektóre typy zmian
        switch (changeType)
        {
            case TextChangeType.SystemAlert:
                Console.WriteLine($"SystemAlert: {text}");
                _speechManager.Speak(text, interrupt: true);
                break;

            case TextChangeType.ContentChanged:
                // Ogłaszaj tylko jeśli to krótki tekst (prawdopodobnie status)
                if (text.Length < 100)
                {
                    Console.WriteLine($"ContentChanged: {text}");
                    _speechManager.Speak(text, interrupt: false);
                }
                break;
        }
    }

    /// <summary>
    /// Obsługa zmiany struktury (nowe elementy)
    /// </summary>
    private void OnStructureChanged(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return;

        Console.WriteLine($"StructureChanged: {text}");
        // Ogłaszaj tylko jeśli to terminal lub przeglądarka
        if (_terminalHandler.IsInTerminal || _isInBrowser)
        {
            _speechManager.Speak(text, interrupt: false);
        }
    }

    /// <summary>
    /// Obsługa wyjścia terminala
    /// </summary>
    private void OnTerminalOutput(string line)
    {
        if (string.IsNullOrWhiteSpace(line))
            return;

        Console.WriteLine($"Terminal output: {line}");
        _speechManager.Speak(line, interrupt: false);
    }

    /// <summary>
    /// Obsługa zmiany tekstu w terminalu
    /// </summary>
    private void OnTerminalTextChanged(string text, bool isAssertive)
    {
        if (string.IsNullOrWhiteSpace(text))
            return;

        Console.WriteLine($"Terminal text: {text}");
        _speechManager.Speak(text, interrupt: isAssertive);
    }

    /// <summary>
    /// Obsługa wpisanego znaku (echo klawiatury)
    /// </summary>
    private void OnCharTyped(char ch)
    {
        if (!_keyboardEchoMode.IncludesCharacters())
            return;

        string announcement = GetCharacterAnnouncement(ch, _settings.PhoneticLetters);
        if (!string.IsNullOrEmpty(announcement))
        {
            _speechManager.Speak(announcement);
        }
    }

    /// <summary>
    /// Obsługa wpisanego słowa (echo klawiatury)
    /// </summary>
    private void OnWordTyped(string word)
    {
        if (!_keyboardEchoMode.IncludesWords())
            return;

        if (!string.IsNullOrWhiteSpace(word))
        {
            _speechManager.Speak(word);
        }
    }

    /// <summary>
    /// Zwraca znak przed kursorem (dla Backspace)
    /// </summary>
    private char? OnCharacterBeingDeleted()
    {
        return _editableTextHandler.GetCharacterBeforeCaret();
    }

    /// <summary>
    /// Obsługa usunięcia znaku przez Backspace
    /// </summary>
    private void OnCharacterDeleted(char ch)
    {
        string announcement = EditableText.EditableTextHandler.GetAnnouncementForCharacter(ch);
        _speechManager.Speak(announcement);
    }

    // Nazwy znaków specjalnych dla obu języków. Wybór wg LocalizationManager.Language.
    private static readonly Dictionary<char, string> SpecialCharsPl = new()
    {
        {' ', "spacja"}, {'\n', "nowa linia"}, {'\r', ""}, {'\t', "tabulator"}, {'\b', ""},
        {'.', "kropka"}, {',', "przecinek"}, {';', "średnik"}, {':', "dwukropek"},
        {'!', "wykrzyknik"}, {'?', "pytajnik"}, {'-', "minus"}, {'_', "podkreślenie"},
        {'=', "równa się"}, {'+', "plus"}, {'*', "gwiazdka"}, {'/', "ukośnik"},
        {'\\', "odwrotny ukośnik"}, {'@', "małpa"}, {'#', "hash"}, {'$', "dolar"},
        {'%', "procent"}, {'^', "daszek"}, {'&', "ampersand"},
        {'(', "nawias otwierający"}, {')', "nawias zamykający"},
        {'[', "nawias kwadratowy otwierający"}, {']', "nawias kwadratowy zamykający"},
        {'{', "nawias klamrowy otwierający"}, {'}', "nawias klamrowy zamykający"},
        {'<', "mniejszy niż"}, {'>', "większy niż"}, {'\'', "apostrof"}, {'"', "cudzysłów"},
        {'`', "grawis"}, {'~', "tylda"}, {'|', "kreska pionowa"}
    };

    private static readonly Dictionary<char, string> SpecialCharsEn = new()
    {
        {' ', "space"}, {'\n', "new line"}, {'\r', ""}, {'\t', "tab"}, {'\b', ""},
        {'.', "dot"}, {',', "comma"}, {';', "semicolon"}, {':', "colon"},
        {'!', "exclamation mark"}, {'?', "question mark"}, {'-', "minus"}, {'_', "underscore"},
        {'=', "equals"}, {'+', "plus"}, {'*', "asterisk"}, {'/', "slash"},
        {'\\', "backslash"}, {'@', "at"}, {'#', "hash"}, {'$', "dollar"},
        {'%', "percent"}, {'^', "caret"}, {'&', "ampersand"},
        {'(', "left parenthesis"}, {')', "right parenthesis"},
        {'[', "left bracket"}, {']', "right bracket"},
        {'{', "left brace"}, {'}', "right brace"},
        {'<', "less than"}, {'>', "greater than"}, {'\'', "apostrophe"}, {'"', "quote"},
        {'`', "grave"}, {'~', "tilde"}, {'|', "vertical bar"}
    };

    // Alfabet fonetyczny dla obu języków. Litery z polskimi znakami diakrytycznymi
    // pozostają z nazwami polskimi również w wariancie angielskim.
    private static readonly Dictionary<char, string> PhoneticPl = new()
    {
        {'a', "Adam"}, {'ą', "Aniela"}, {'b', "Barbara"}, {'c', "Cezary"}, {'ć', "Celina"},
        {'d', "Dorota"}, {'e', "Edward"}, {'ę', "Ewa"}, {'f', "Franciszek"}, {'g', "Genowefa"},
        {'h', "Henryk"}, {'i', "Irena"}, {'j', "Jadwiga"}, {'k', "Karol"}, {'l', "Leon"},
        {'ł', "Łucja"}, {'m', "Maria"}, {'n', "Natalia"}, {'ń', "Nikodem"}, {'o', "Olga"},
        {'ó', "Oskar"}, {'p', "Paweł"}, {'q', "Québec"}, {'r', "Roman"}, {'s', "Sylwia"},
        {'ś', "Śpiewak"}, {'t', "Tomasz"}, {'u', "Urszula"}, {'v', "Violetta"},
        {'w', "Władysław"}, {'x', "Ksawery"}, {'y', "Yxilon"}, {'z', "Zofia"},
        {'ź', "Źrebię"}, {'ż', "Żaba"}
    };

    private static readonly Dictionary<char, string> PhoneticEn = new()
    {
        {'a', "Alpha"}, {'ą', "Aniela"}, {'b', "Bravo"}, {'c', "Charlie"}, {'ć', "Celina"},
        {'d', "Delta"}, {'e', "Echo"}, {'ę', "Ewa"}, {'f', "Foxtrot"}, {'g', "Golf"},
        {'h', "Hotel"}, {'i', "India"}, {'j', "Juliet"}, {'k', "Kilo"}, {'l', "Lima"},
        {'ł', "Łucja"}, {'m', "Mike"}, {'n', "November"}, {'ń', "Nikodem"}, {'o', "Oscar"},
        {'ó', "Oskar"}, {'p', "Papa"}, {'q', "Quebec"}, {'r', "Romeo"}, {'s', "Sierra"},
        {'ś', "Śpiewak"}, {'t', "Tango"}, {'u', "Uniform"}, {'v', "Victor"},
        {'w', "Whiskey"}, {'x', "X-ray"}, {'y', "Yankee"}, {'z', "Zulu"},
        {'ź', "Źrebię"}, {'ż', "Żaba"}
    };

    private static Dictionary<char, string> SpecialChars
        => LocalizationManager.Language == "en" ? SpecialCharsEn : SpecialCharsPl;
    private static Dictionary<char, string> Phonetic
        => LocalizationManager.Language == "en" ? PhoneticEn : PhoneticPl;

    /// <summary>
    /// Zwraca ogłoszenie dla znaku (z alfabetem fonetycznym bieżącego języka)
    /// </summary>
    private static string GetCharacterAnnouncement(char ch, bool usePhonetic)
    {
        // Znaki specjalne
        if (SpecialChars.TryGetValue(ch, out var specialChar))
            return specialChar;

        // Litery - z fonetyką jeśli włączone
        if (usePhonetic && char.IsLetter(ch))
        {
            return GetPhoneticLetter(ch);
        }

        // Bez fonetyki - zwykły opis
        return ch switch
        {
            >= 'A' and <= 'Z' => L.T("char.upper", ch),
            _ => ch.ToString()
        };
    }

    /// <summary>
    /// Zwraca alfabet fonetyczny bieżącego języka dla litery
    /// </summary>
    private static string GetPhoneticLetter(char ch)
    {
        char lower = char.ToLower(ch);
        bool isUpper = char.IsUpper(ch);

        if (!Phonetic.TryGetValue(lower, out var phonetic))
            phonetic = ch.ToString();

        return isUpper ? L.T("char.upperPhonetic", phonetic) : phonetic;
    }

    /// <summary>
    /// Obsługa gestów (Insert+...)
    /// </summary>
    private bool OnGestureProcessed(int vkCode, int flags, bool ctrl, bool alt, bool shift, bool nvdaModifier)
    {
        if (!nvdaModifier)
            return false;

        var key = (System.Windows.Forms.Keys)vkCode;
        return _gestureManager.ProcessKeyPress(key, ctrl, alt, shift, nvdaModifier);
    }

    /// <summary>
    /// Obsługa szybkiej nawigacji (browse mode)
    /// </summary>
    private bool OnQuickNavProcessed(char key, bool shift)
    {
        if (_browseModeHandler.IsActive)
        {
            return _browseModeHandler.HandleQuickNav(key, shift);
        }
        return false;
    }

    /// <summary>
    /// Obsługa nawigacji strzałkami w browse mode
    /// </summary>
    private bool OnBrowseModeArrowNavigation(int vkCode, bool ctrl)
    {
        if (_browseModeHandler.IsActive)
        {
            return _browseModeHandler.HandleArrowNavigation(vkCode, ctrl);
        }
        return false;
    }

    /// <summary>
    /// Obsługa zmiany trybu browse/focus
    /// </summary>
    private void OnBrowseModeChanged(bool passThrough)
    {
        if (passThrough)
        {
            _soundManager.PlayClicked();
        }
        else
        {
            _soundManager.PlayCursor();
        }

        _keyboardHook.IsInBrowseMode = _browseModeHandler.IsActive && !passThrough;
    }

    /// <summary>
    /// Przełącza tryb browse/focus (Insert+Space)
    /// </summary>
    private void OnToggleBrowseMode()
    {
        if (_browseModeHandler.IsActive)
        {
            _browseModeHandler.TogglePassThrough();
        }
        else
        {
            _speechManager.Speak(L.T("browse.unavailable"));
        }
    }

    /// <summary>
    /// Aktywuje browse mode dla dokumentu (async)
    /// </summary>
    public async Task ActivateBrowseModeAsync(AutomationElement document)
    {
        await _browseModeHandler.ActivateAsync(document);
    }

    public void Start()
    {
        Console.WriteLine("Uruchamianie Czytnika Ekranu...");

        // Uruchom natywny helper (ScreenReaderHelper.dll) - dedykowany wątek hooków
        ScreenReader.Native.NativeHelper.Initialize();

        // Oznajmij uruchomienie zgodnie z ustawieniami
        var startupMode = _settings.StartupAnnouncement;
        if (startupMode == AnnouncementMode.Sound || startupMode == AnnouncementMode.SpeechAndSound)
        {
            _soundManager.PlaySROn();
        }
        if (startupMode == AnnouncementMode.Speech || startupMode == AnnouncementMode.SpeechAndSound)
        {
            string welcomeMessage = _settings.WelcomeMessage;
            if (string.IsNullOrWhiteSpace(welcomeMessage))
                welcomeMessage = ScreenReader.Localization.L.T("app.welcome");
            _speechManager.Speak(welcomeMessage);
        }

        // Załaduj ustawienia nawigacji i modyfikatora
        ApplyNavigationSettings();

        // Inicjalizuj menedżera dostępności z włączonymi API
        _accessibilityManager.SetApiEnabled(AccessibilityAPI.UIAutomation, true);
        _accessibilityManager.SetApiEnabled(AccessibilityAPI.MSAA, true);
        _accessibilityManager.Initialize();
        _accessibilityManager.StartEventListening();

        _focusTracker.Start();
        _keyboardHook.Start();

        // Start dialog monitor
        _dialogMonitor = new DialogMonitor(_speechManager);
        _dialogMonitor.StartMonitoring();

        // Start live region monitor z rozszerzonym monitorowaniem
        _liveRegionMonitor.MonitorAllChanges = true;
        // _liveRegionMonitor.OnlyActiveWindow = true; // Wyłączone - powodowało problemy
        _liveRegionMonitor.Start();

        // Timer sprawdzający hook wyłączony - powodował problemy
        // _hookHealthTimer = new System.Threading.Timer(
        //     CheckKeyboardHookHealth,
        //     null,
        //     TimeSpan.FromSeconds(5),
        //     TimeSpan.FromSeconds(5));

        // Read the currently focused element on startup
        _currentElement = UIAutomationHelper.GetFocusedElement();
        if (_currentElement != null)
        {
            AnnounceElement(_currentElement, false);
        }

        Console.WriteLine("Czytnik Ekranu działa. Naciśnij Ctrl+C aby zakończyć.");
        Console.WriteLine("Skróty klawiszowe (NumPad przy wyłączonym NumLock lub CapsLock+strzałki):");
        Console.WriteLine("  NumPad 5 / CapsLock+5: Odczytaj bieżący element");
        Console.WriteLine("  NumPad 6 / CapsLock+Right: Następny element");
        Console.WriteLine("  NumPad 4 / CapsLock+Left: Poprzedni element");
        Console.WriteLine("  NumPad 2 / CapsLock+Down: Pierwszy potomek");
        Console.WriteLine("  NumPad 8 / CapsLock+Up: Element nadrzędny");
        Console.WriteLine("  NumPad / / CapsLock+Space: Aktywuj element");
        Console.WriteLine("  NumPad - / CapsLock+': Przełącz pokrętło");
        Console.WriteLine("  NumPad + / CapsLock+;: Przełącz nawigację liniową/zaawansowaną");
        Console.WriteLine("  Ctrl+Alt+S: Zatrzymaj mowę");
        Console.WriteLine("  Ctrl+Shift+\\: Menu czytnika");
    }

    /// <summary>
    /// Stosuje ustawienia nawigacji z SettingsManager
    /// </summary>
    private void ApplyNavigationSettings()
    {
        _keyboardHook.IsLinearNavigationMode = !_settings.AdvancedNavigation;
        _keyboardHook.NVDAModifierConfig = ConvertModifierSetting(_settings.Modifier);
        Console.WriteLine($"Zastosowano ustawienia nawigacji: AdvancedNavigation={_settings.AdvancedNavigation}, Modifier={_settings.Modifier}");
    }

    /// <summary>
    /// Konwertuje ScreenReaderModifier na NVDAModifierConfig
    /// </summary>
    private NVDAModifierConfig ConvertModifierSetting(ScreenReaderModifier modifier)
    {
        return modifier switch
        {
            ScreenReaderModifier.Insert => NVDAModifierConfig.NumpadInsert | NVDAModifierConfig.ExtendedInsert,
            ScreenReaderModifier.CapsLock => NVDAModifierConfig.CapsLock,
            ScreenReaderModifier.InsertAndCapsLock => NVDAModifierConfig.Default,
            _ => NVDAModifierConfig.Default
        };
    }

    /// <summary>
    /// Przeładowuje wszystkie ustawienia z SettingsManager i stosuje je
    /// </summary>
    public void ReloadSettings()
    {
        Console.WriteLine("Przeładowywanie ustawień...");

        // Przeładuj ustawienia z pliku
        _settings.Load();

        // Zastosuj ustawienia nawigacji i modyfikatora
        ApplyNavigationSettings();

        // Zastosuj echo klawiatury
        var setting = _settings.KeyboardEcho;
        _keyboardEchoMode = setting switch
        {
            KeyboardEchoSetting.None => KeyboardEchoMode.None,
            KeyboardEchoSetting.Characters => KeyboardEchoMode.Characters,
            KeyboardEchoSetting.Words => KeyboardEchoMode.Words,
            KeyboardEchoSetting.CharactersAndWords => KeyboardEchoMode.WordsAndChars,
            _ => KeyboardEchoMode.WordsAndChars
        };

        Console.WriteLine("Ustawienia przeładowane i zastosowane");
    }

    private async void OnFocusChanged(AutomationElement element)
    {
        try
        {
            // Sprawdź czy element jest dostępny
            int processId;
            try
            {
                processId = element.Current.ProcessId;
            }
            catch (ElementNotAvailableException)
            {
                return;
            }

            _currentElement = element;

            // Pobierz uchwyt okna pierwszego planu
            var foregroundHwnd = GetForegroundWindow();

            // Sprawdź zmianę procesu
            if (processId != _currentProcessId)
            {
                _currentProcessId = processId;
                _currentProcessName = GetProcessName(processId);
                _isInBrowser = IsBrowserProcess(_currentProcessName);

                // Aktualizuj moduł aplikacji
                _appModuleManager.UpdateCurrentProcess(_currentProcessName);

                // Sprawdź czy to proces TCE/Titan
                bool wasInTCE = _isInTCEProcess;
                _isInTCEProcess = IsTCEProcess(_currentProcessName);

                // Obsłuż wejście/wyjście z TCE
                if (_isInTCEProcess && !wasInTCE)
                {
                    // Wchodzimy do aplikacji TCE/Titan
                    if (_settings.TCEEntrySound)
                    {
                        _soundManager.PlayEnterTCE();
                    }
                    _speechManager.Speak("Titan", interrupt: false);
                    Console.WriteLine($"Wejście do TCE/Titan: {_currentProcessName}");
                }
                else if (!_isInTCEProcess && wasInTCE)
                {
                    // Wychodzimy z aplikacji TCE/Titan
                    if (_settings.TCEEntrySound)
                    {
                        _soundManager.PlayLeaveTCE();
                    }
                    if (!_settings.MuteOutsideTCE)
                    {
                        _speechManager.Speak(L.T("engine.unsupportedApp"), interrupt: false);
                    }
                    Console.WriteLine($"Wyjście z TCE/Titan do: {_currentProcessName}");
                }

                Console.WriteLine($"Zmiana procesu: {_currentProcessName} (PID: {processId}, Browser: {_isInBrowser}, TCE: {_isInTCEProcess})");

                // Automatyczne przełączanie API na podstawie aplikacji
                try
                {
                    AutoSelectBestApi(_currentProcessName, element);
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"AutoSelectBestApi: Błąd - {ex.Message}");
                }

                // Jeśli to przeglądarka, włącz rozszerzone monitorowanie LiveRegion
                if (_isInBrowser)
                {
                    _liveRegionMonitor.MonitorAllChanges = true;
                }

                // Sprawdź czy to terminal
                bool isTerminal = TerminalHandler.IsTerminalProcess(_currentProcessName);
                if (isTerminal)
                {
                    _terminalHandler.ActivateForWindow(foregroundHwnd, _currentProcessName);
                    _liveRegionMonitor.MonitorAllChanges = true;
                }
                else if (_terminalHandler.IsInTerminal)
                {
                    _terminalHandler.Deactivate();
                }
            }

            // Aktywuj browse mode dla dokumentów webowych w przeglądarkach
            bool shouldActivateBrowseMode = false;
            var controlType = element.Current.ControlType;

            if (_isInBrowser && controlType == ControlType.Document)
            {
                // Sprawdź czy to rzeczywiście dokument webowy (nie pole edycji)
                if (!EditableTextHandler.IsEditField(element))
                {
                    shouldActivateBrowseMode = true;
                }
            }

            if (shouldActivateBrowseMode && !_browseModeHandler.IsActive)
            {
                // Aktywuj browse mode
                try
                {
                    _browseModeHandler.Activate(element);
                    _keyboardHook.IsInBrowseMode = true;
                    Console.WriteLine("Browse mode activated");
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"Failed to activate browse mode: {ex.Message}");
                    _browseModeHandler.Deactivate();
                    _keyboardHook.IsInBrowseMode = false;
                }
            }
            else if (!shouldActivateBrowseMode && _browseModeHandler.IsActive)
            {
                // Dezaktywuj browse mode
                _browseModeHandler.Deactivate();
                _keyboardHook.IsInBrowseMode = false;
                Console.WriteLine("Browse mode deactivated");
            }

            // Sprawdź czy to pole edycji
            bool isEditField = EditableTextHandler.IsEditField(element);
            _keyboardHook.IsInEditField = isEditField;

            if (isEditField)
            {
                _editNavigator.SetCurrentEdit(element);
                _editableTextHandler.SetElement(element);
            }
            else
            {
                _editNavigator.SetCurrentEdit(null);
                _editableTextHandler.SetElement(null);
            }

            // Sprawdź czy to pole kombi (ComboBox)
            _isInComboBox = IsComboBoxElement(element);
            _keyboardHook.IsInComboBox = _isInComboBox;

            // Sprawdź zmianę okna
            var window = GetContainingWindow(element);
            if (window != null && _lastWindow != null)
            {
                try
                {
                    if (!Automation.Compare(window, _lastWindow))
                    {
                        _lastWindow = window;
                        _currentWindow = window; // Ustaw bieżące okno dla nawigacji
                        _soundManager.PlayWindow();
                        var title = GetWindowTitle(window);
                        Console.WriteLine($"Nowe okno: {title}");
                        _speechManager.Speak(L.T("engine.windowNamed", title));
                    }
                }
                catch
                {
                    // Ignore comparison errors
                }
            }
            else if (window != null && _lastWindow == null)
            {
                _lastWindow = window;
                _currentWindow = window; // Ustaw bieżące okno dla nawigacji
            }

            // Sprawdź obsługę menu - jeśli zwraca true, ogłoszenie już zostało obsłużone
            bool menuHandled = HandleMenuFocusChange(element);

            if (!menuHandled)
            {
                AnnounceElement(element, false);
            }

            // Uruchom timer podpowiedzi
            _hintManager.SetCurrentElement(element, _isInTCEProcess);
        }
        catch (ElementNotAvailableException)
        {
            // Element zniknął podczas przetwarzania
            _hintManager.CancelHint();
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Błąd w OnFocusChanged: {ex.Message}");
        }
    }

    /// <summary>
    /// Obsługuje zmianę fokusa związaną z menu (rozwijanie/zamykanie)
    /// Zwraca true jeśli ogłoszenie zostało już obsłużone (nie należy ogłaszać ponownie)
    /// </summary>
    private bool HandleMenuFocusChange(AutomationElement element)
    {
        try
        {
            bool isNowInMenu = IsMenuElement(element);
            var controlType = element.Current.ControlType;

            // Sprawdź czy weszliśmy do paska menu (MenuItem w MenuBar)
            bool isNowInMenuBar = controlType == ControlType.MenuItem && IsInMenuBar(element);

            if (isNowInMenuBar && !_isInMenuBar)
            {
                // Właśnie weszliśmy do paska menu - ogłoś prefiks i pełny opis elementu
                _isInMenuBar = true;
                var description = UIAutomationHelper.GetElementDescription(element);
                string announcement = $"Pasek menu: {description}";
                _speechManager.Speak(announcement);
                return true; // Ogłoszenie obsłużone
            }
            else if (!isNowInMenuBar && _isInMenuBar && !isNowInMenu)
            {
                // Wyszliśmy z paska menu (nie do rozwiniętego menu)
                _isInMenuBar = false;
            }

            // Wykryj rozwinięcie menu
            if (isNowInMenu && !_isInMenu)
            {
                // Weszliśmy do menu - odtwórz dźwięk rozwinięcia i ogłoś z liczbą elementów
                _isInMenuBar = false; // Resetuj flagę paska menu
                var menuParent = GetMenuParent(element);
                if (menuParent != null || controlType == ControlType.Menu)
                {
                    if (_settings.MenuSounds)
                    {
                        _soundManager.PlayMenuExpanded();
                    }

                    _lastMenuParent = menuParent ?? element;
                    _lastMenuBar = GetMenuBar(element); // Zapamiętaj pasek menu

                    // Ogłoś: "{nazwa menu}, menu, {x} elementów, {pierwszy element}"
                    var parts = new List<string>();

                    if (_settings.MenuName)
                    {
                        var menuName = _lastMenuParent.Current.Name ?? "";
                        if (!string.IsNullOrEmpty(menuName))
                        {
                            parts.Add(menuName);
                        }
                    }

                    parts.Add(L.T("menu.menu"));

                    if (_settings.MenuItemCount)
                    {
                        int menuItemCount = CountMenuItems(_lastMenuParent);
                        if (menuItemCount > 0)
                        {
                            parts.Add(L.T("menu.itemCount", menuItemCount));
                        }
                    }

                    var firstItemDesc = UIAutomationHelper.GetElementDescription(element);
                    parts.Add(firstItemDesc);

                    string announcement = string.Join(", ", parts);
                    _speechManager.Speak(announcement);
                }
                _isInMenu = true;
                return true; // Obsłużone - nie wywołuj AnnounceElement
            }
            else if (!isNowInMenu && _isInMenu)
            {
                // Wyszliśmy z menu
                _lastMenuParent = null;
                _lastMenuBar = null;
                _isInMenu = false;

                // Jeśli wróciliśmy do paska menu - bez dźwięku zamknięcia
                if (isNowInMenuBar)
                {
                    _isInMenuBar = true;
                    // Nie odtwarzaj dźwięku zamknięcia - zostajemy w pasku menu
                    return false; // Pozwól AnnounceElement ogłosić element paska menu
                }

                // Wyszliśmy całkowicie z menu i paska menu - odtwórz dźwięk zamknięcia
                if (_settings.MenuSounds)
                {
                    _soundManager.PlayMenuClosed();
                }
                _speechManager.Speak(L.T("menu.closed"));
                _isInMenuBar = false;

                return false;
            }
            else if (isNowInMenu)
            {
                // Nadal jesteśmy w menu - sprawdź czy to nowe podmenu
                var currentMenuParent = GetMenuParent(element);
                if (currentMenuParent != null && _lastMenuParent != null)
                {
                    try
                    {
                        if (!Automation.Compare(currentMenuParent, _lastMenuParent))
                        {
                            // To jest nowe podmenu - ogłoś z liczbą elementów i pierwszym elementem
                            if (_settings.MenuSounds)
                            {
                                _soundManager.PlayMenuExpanded();
                            }

                            _lastMenuParent = currentMenuParent;

                            var parts = new List<string>();

                            if (_settings.MenuName)
                            {
                                var menuName = _lastMenuParent.Current.Name ?? "";
                                if (!string.IsNullOrEmpty(menuName))
                                {
                                    parts.Add(menuName);
                                }
                            }

                            parts.Add(L.T("menu.menu"));

                            if (_settings.MenuItemCount)
                            {
                                int menuItemCount = CountMenuItems(_lastMenuParent);
                                if (menuItemCount > 0)
                                {
                                    parts.Add(L.T("menu.itemCount", menuItemCount));
                                }
                            }

                            var firstItemDesc = UIAutomationHelper.GetElementDescription(element);
                            parts.Add(firstItemDesc);

                            string announcement = string.Join(", ", parts);
                            _speechManager.Speak(announcement);
                            return true; // Obsłużone - nie wywołuj AnnounceElement
                        }
                    }
                    catch { }
                }
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"HandleMenuFocusChange: {ex.Message}");
        }

        return false;
    }

    /// <summary>
    /// Sprawdza czy element jest bezpośrednio w pasku menu (MenuBar)
    /// </summary>
    private static bool IsInMenuBar(AutomationElement? element)
    {
        if (element == null)
            return false;

        try
        {
            var walker = TreeWalker.ControlViewWalker;
            var parent = walker.GetParent(element);

            if (parent != null && parent.Current.ControlType == ControlType.MenuBar)
                return true;
        }
        catch { }

        return false;
    }

    /// <summary>
    /// Pobiera pasek menu (MenuBar) dla elementu menu
    /// </summary>
    private static AutomationElement? GetMenuBar(AutomationElement? element)
    {
        if (element == null)
            return null;

        try
        {
            var walker = TreeWalker.ControlViewWalker;
            var current = element;

            while (current != null)
            {
                var controlType = current.Current.ControlType;

                if (controlType == ControlType.MenuBar)
                    return current;

                if (controlType == ControlType.Window)
                    break;

                current = walker.GetParent(current);
            }
        }
        catch { }

        return null;
    }

    /// <summary>
    /// Sprawdza czy powinniśmy aktywować browse mode dla elementu
    /// </summary>
    private bool ShouldActivateBrowseMode(AutomationElement element)
    {
        if (!_isInBrowser)
            return false;

        try
        {
            var controlType = element.Current.ControlType;
            var className = element.Current.ClassName ?? "";
            var automationId = element.Current.AutomationId ?? "";
            var name = element.Current.Name ?? "";

            Console.WriteLine($"ShouldActivateBrowseMode: ControlType={controlType.ProgrammaticName}, ClassName={className}, AutomationId={automationId}");

            // Aktywuj dla dokumentów w przeglądarkach
            if (controlType == ControlType.Document)
            {
                Console.WriteLine("ShouldActivateBrowseMode: Znaleziono Document - TAK");
                return true;
            }

            // Chromium/Edge - sprawdź czy to element webowy
            // Chrome/Edge używają różnych klas dla treści webowej
            if (className.Contains("Chrome_RenderWidgetHostHWND") ||
                className.Contains("Chrome_WidgetWin") ||
                className.Contains("Intermediate D3D Window") ||
                automationId.Contains("webview") ||
                automationId.Contains("RootWebArea"))
            {
                Console.WriteLine($"ShouldActivateBrowseMode: Znaleziono element webowy ({className}) - TAK");
                return true;
            }

            // Edge może używać LocalizedControlType "document", "strona", "kontrolka niestandardowa" itp.
            var localizedType = element.Current.LocalizedControlType?.ToLowerInvariant() ?? "";
            if (localizedType.Contains("document") || localizedType.Contains("strona") ||
                localizedType.Contains("dokument") || localizedType.Contains("web") ||
                localizedType.Contains("niestandardow") || localizedType.Contains("custom"))
            {
                Console.WriteLine($"ShouldActivateBrowseMode: Znaleziono przez LocalizedControlType ({localizedType}) - TAK");
                return true;
            }

            // Sprawdź czy to główne okno przeglądarki z zawartością
            if (controlType == ControlType.Pane || controlType == ControlType.Custom ||
                controlType == ControlType.Group || controlType == ControlType.Text)
            {
                // Szukaj dokumentu w dzieciach (maksymalnie 5 poziomów)
                var document = FindDocumentInChildren(element, 5);
                if (document != null)
                {
                    Console.WriteLine("ShouldActivateBrowseMode: Znaleziono dokument w dzieciach - TAK");
                    return true;
                }
            }

            // Sprawdź rodzica - może to jest element wewnątrz dokumentu
            var walker = TreeWalker.ControlViewWalker;
            var parent = walker.GetParent(element);
            int maxDepth = 5;

            while (parent != null && maxDepth > 0)
            {
                try
                {
                    if (parent.Current.ControlType == ControlType.Document)
                    {
                        Console.WriteLine("ShouldActivateBrowseMode: Rodzic jest dokumentem - TAK");
                        return true;
                    }

                    var parentClass = parent.Current.ClassName ?? "";
                    if (parentClass.Contains("Chrome_RenderWidgetHostHWND"))
                    {
                        Console.WriteLine("ShouldActivateBrowseMode: Rodzic to Chrome render widget - TAK");
                        return true;
                    }
                }
                catch { }

                parent = walker.GetParent(parent);
                maxDepth--;
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"ShouldActivateBrowseMode: Błąd - {ex.Message}");
        }

        Console.WriteLine("ShouldActivateBrowseMode: NIE");
        return false;
    }

    /// <summary>
    /// Rekurencyjnie szuka dokumentu w dzieciach elementu
    /// </summary>
    private AutomationElement? FindDocumentInChildren(AutomationElement element, int maxDepth)
    {
        if (maxDepth <= 0)
            return null;

        try
        {
            var walker = TreeWalker.ControlViewWalker;
            var child = walker.GetFirstChild(element);

            while (child != null)
            {
                try
                {
                    if (child.Current.ControlType == ControlType.Document)
                        return child;

                    // Rekurencja
                    var found = FindDocumentInChildren(child, maxDepth - 1);
                    if (found != null)
                        return found;
                }
                catch { }

                child = walker.GetNextSibling(child);
            }
        }
        catch { }

        return null;
    }

    /// <summary>
    /// Znajduje element dokumentu do aktywacji browse mode
    /// </summary>
    private AutomationElement? FindBrowseModeDocument(AutomationElement element)
    {
        try
        {
            // Jeśli to już dokument, użyj go
            if (element.Current.ControlType == ControlType.Document)
                return element;

            // Szukaj dokumentu w dzieciach
            var document = FindDocumentInChildren(element, 5);
            if (document != null)
                return document;

            // Szukaj dokumentu w rodzicach
            var walker = TreeWalker.ControlViewWalker;
            var parent = walker.GetParent(element);
            int maxParentDepth = 5;

            while (parent != null && maxParentDepth > 0)
            {
                try
                {
                    if (parent.Current.ControlType == ControlType.Document)
                        return parent;

                    // Szukaj dokumentu wśród rodzeństwa rodzica
                    var sibling = walker.GetFirstChild(parent);
                    while (sibling != null)
                    {
                        try
                        {
                            if (sibling.Current.ControlType == ControlType.Document)
                                return sibling;
                        }
                        catch { }
                        sibling = walker.GetNextSibling(sibling);
                    }
                }
                catch { }

                parent = walker.GetParent(parent);
                maxParentDepth--;
            }

            // Jeśli nie znaleziono dokumentu, użyj elementu startowego
            // (może być to element Chrome z zawartością)
            return element;
        }
        catch
        {
            return element;
        }
    }

    /// <summary>
    /// Automatycznie wybiera najlepsze API dostępności na podstawie procesu
    /// </summary>
    private void AutoSelectBestApi(string? processName, AutomationElement? element)
    {
        // Przełącz API na podstawie nazwy procesu
        if (_accessibilityManager.AutoSelectApiForProcess(processName))
        {
            var currentApi = _accessibilityManager.PreferredApi;
            Console.WriteLine($"Przełączono API na: {currentApi.GetPolishName()} (na podstawie procesu)");
        }

        // Opcjonalna ocena jakości - wyłączona bo powodowała problemy
        // Można włączyć w przyszłości po ustabilizowaniu
        /*
        if (element != null)
        {
            var quality = EvaluateApiQuality(element);
            if (quality < AccessibilityQuality.Good)
            {
                // Próba alternatywnych API...
            }
        }
        */
    }

    /// <summary>
    /// Poziomy jakości dostępności
    /// </summary>
    private enum AccessibilityQuality
    {
        None = 0,       // Brak danych
        Poor = 1,       // Słaba jakość (tylko podstawowe info)
        Fair = 2,       // Dostateczna (nazwa lub wartość)
        Good = 3,       // Dobra (nazwa + typ + stan)
        Excellent = 4   // Doskonała (wszystkie wzorce)
    }

    /// <summary>
    /// Ocenia jakość dostępności dla bieżącego API
    /// </summary>
    private AccessibilityQuality EvaluateApiQuality(AutomationElement element)
    {
        try
        {
            int score = 0;

            // Sprawdź nazwę
            var name = element.Current.Name;
            if (!string.IsNullOrWhiteSpace(name))
                score++;

            // Sprawdź typ kontrolki
            var controlType = element.Current.ControlType;
            if (controlType != null && controlType != ControlType.Custom)
                score++;

            // Sprawdź czy jest dostępna dla klawiatury
            if (element.Current.IsKeyboardFocusable)
                score++;

            // Sprawdź dostępne wzorce
            var patterns = element.GetSupportedPatterns();
            if (patterns.Length > 0)
                score++;

            return score switch
            {
                0 => AccessibilityQuality.None,
                1 => AccessibilityQuality.Poor,
                2 => AccessibilityQuality.Fair,
                3 => AccessibilityQuality.Good,
                _ => AccessibilityQuality.Excellent
            };
        }
        catch
        {
            return AccessibilityQuality.None;
        }
    }

    /// <summary>
    /// Ocenia jakość dostępności dla konkretnego providera
    /// </summary>
    private AccessibilityQuality EvaluateApiQualityWithProvider(AutomationElement element, Accessibility.IAccessibilityProvider provider)
    {
        try
        {
            if (!provider.SupportsElement(element))
                return AccessibilityQuality.None;

            var obj = provider.GetAccessibleObject(element);
            if (obj == null)
                return AccessibilityQuality.None;

            int score = 0;

            if (!string.IsNullOrWhiteSpace(obj.Name))
                score++;
            if (obj.Role != Accessibility.AccessibleRole.None)
                score++;
            if (!string.IsNullOrWhiteSpace(obj.Value))
                score++;
            if (obj.States != Accessibility.AccessibleStates.None)
                score++;

            return score switch
            {
                0 => AccessibilityQuality.None,
                1 => AccessibilityQuality.Poor,
                2 => AccessibilityQuality.Fair,
                3 => AccessibilityQuality.Good,
                _ => AccessibilityQuality.Excellent
            };
        }
        catch
        {
            return AccessibilityQuality.None;
        }
    }

    /// <summary>
    /// Pobiera nazwę procesu
    /// </summary>
    private static string? GetProcessName(int processId)
    {
        try
        {
            using var process = Process.GetProcessById(processId);
            return process.ProcessName;
        }
        catch
        {
            return null;
        }
    }

    /// <summary>
    /// Sprawdza czy proces to przeglądarka
    /// </summary>
    private static bool IsBrowserProcess(string? processName)
    {
        if (string.IsNullOrEmpty(processName))
            return false;

        return BrowserProcessNames.Contains(processName);
    }

    /// <summary>
    /// Sprawdza czy proces to aplikacja TCE/Titan
    /// Pasuje do: titan.exe, python.exe, tce*.exe, titan*.exe
    /// </summary>
    private static bool IsTCEProcess(string? processName)
    {
        if (string.IsNullOrEmpty(processName))
            return false;

        var nameLower = processName.ToLowerInvariant();

        // Dokładne dopasowania
        if (nameLower == "titan" || nameLower == "python" || nameLower == "pythonw")
            return true;

        // Wzorce z wildcard: tce* i titan*
        if (nameLower.StartsWith("tce") || nameLower.StartsWith("titan"))
            return true;

        return false;
    }

    private void OnReadCurrentElement()
    {
        // Jeśli pokrętło jest włączone i jesteśmy w kategorii ImportantPlaces, aktywuj wybrane miejsce
        if (_dialManager.IsEnabled && _dialManager.CurrentCategory == DialCategory.ImportantPlaces)
        {
            ActivateCurrentImportantPlace();
            return;
        }

        if (_currentElement != null)
        {
            if (UIAutomationHelper.IsButton(_currentElement))
            {
                _soundManager.PlayClicked();
            }

            AnnounceElement(_currentElement, false);
        }
        else
        {
            _speechManager.Speak(L.T("engine.noCurrentElement"));
            Console.WriteLine("Brak bieżącego elementu");
        }
    }

    private void OnMoveToNextElement()
    {
        // Natychmiast przerwij mowę dla responsywności
        _speechManager.Stop();

        var next = UIAutomationHelper.GetNextSibling(_currentElement);
        // Nawigacja globalna - działa wszędzie (pulpit, wszystkie okna)
        if (next != null && !IsWindowBoundary(next))
        {
            _currentElement = next;
            // Użyj odpowiedniego dźwięku w zależności od typu elementu
            if (IsInteractiveElement(next))
            {
                _soundManager.PlayCursor();
            }
            else
            {
                _soundManager.PlayCursorStatic();
            }
            AnnounceElement(next, true, skipCursorSound: true, fromNavigation: true);
        }
        else
        {
            // Koniec drzewa - dźwięk i komunikat według ustawień
            AnnounceWindowBounds(L.T("engine.windowEnd"), true);
        }
    }

    private void OnMoveToPreviousElement()
    {
        // Natychmiast przerwij mowę dla responsywności
        _speechManager.Stop();

        var previous = UIAutomationHelper.GetPreviousSibling(_currentElement);
        // Nawigacja globalna - działa wszędzie (pulpit, wszystkie okna)
        if (previous != null && !IsWindowBoundary(previous))
        {
            _currentElement = previous;
            // Użyj odpowiedniego dźwięku w zależności od typu elementu
            if (IsInteractiveElement(previous))
            {
                _soundManager.PlayCursor();
            }
            else
            {
                _soundManager.PlayCursorStatic();
            }
            AnnounceElement(previous, true, skipCursorSound: true, fromNavigation: true);
        }
        else
        {
            // Początek drzewa - dźwięk i komunikat według ustawień
            AnnounceWindowBounds(L.T("engine.windowStart"), false);
        }
    }

    private void OnMoveToParent()
    {
        // Natychmiast przerwij mowę dla responsywności
        _speechManager.Stop();

        var parent = UIAutomationHelper.GetParent(_currentElement);
        // Nawigacja globalna - działa wszędzie, ale zatrzymaj się przed rootem
        if (parent != null && !IsWindowBoundary(parent))
        {
            _currentElement = parent;
            _hierarchyLevel--; // Zmniejsz poziom hierarchii przy przejściu do rodzica
            _soundManager.PlayZoomOut();
            AnnounceElement(parent, false, skipCursorSound: true, fromNavigation: true);

            // Ogłoś poziom hierarchii jeśli włączone w ustawieniach
            if (_settings.AnnounceHierarchyLevel && _hierarchyLevel >= 0)
            {
                _speechManager.Speak(L.T("engine.hierarchyLevel", _hierarchyLevel));
            }
        }
        else
        {
            // Granica drzewa (góra) - tylko dźwięk edge.ogg, bez komunikatu
            _soundManager.PlayEdge();
        }
    }

    private void OnMoveToFirstChild()
    {
        // Natychmiast przerwij mowę dla responsywności
        _speechManager.Stop();

        var child = UIAutomationHelper.GetFirstChild(_currentElement);
        // Nawigacja globalna - działa wszędzie (pulpit, wszystkie okna)
        if (child != null && !IsWindowBoundary(child))
        {
            _currentElement = child;
            _hierarchyLevel++; // Zwiększ poziom hierarchii przy przejściu do dziecka
            _soundManager.PlayZoomIn();
            AnnounceElement(child, false, skipCursorSound: true, fromNavigation: true);

            // Ogłoś poziom hierarchii jeśli włączone w ustawieniach
            if (_settings.AnnounceHierarchyLevel)
            {
                _speechManager.Speak(L.T("engine.hierarchyLevel", _hierarchyLevel));
            }
        }
        else
        {
            // Brak potomków - tylko dźwięk edge.ogg, bez komunikatu
            _soundManager.PlayEdge();
        }
    }

    /// <summary>
    /// Nawigacja liniowa do następnego elementu (wszystkie elementy globalnie)
    /// </summary>
    private void OnLinearMoveToNext()
    {
        // Natychmiast przerwij mowę dla responsywności
        _speechManager.Stop();

        var next = GetNextElementLinear(_currentElement);
        // Nawigacja globalna - działa wszędzie (pulpit, wszystkie okna)
        if (next != null && !IsWindowBoundary(next))
        {
            _currentElement = next;
            if (IsInteractiveElement(next))
            {
                _soundManager.PlayCursor();
            }
            else
            {
                _soundManager.PlayCursorStatic();
            }
            AnnounceElement(next, true, skipCursorSound: true, fromNavigation: true);
        }
        else
        {
            // Koniec drzewa - tylko dźwięk edge.ogg, bez komunikatu
            _soundManager.PlayEdge();
        }
    }

    /// <summary>
    /// Nawigacja liniowa do poprzedniego elementu (wszystkie elementy globalnie)
    /// </summary>
    private void OnLinearMoveToPrevious()
    {
        // Natychmiast przerwij mowę dla responsywności
        _speechManager.Stop();

        var prev = GetPreviousElementLinear(_currentElement);
        // Nawigacja globalna - działa wszędzie (pulpit, wszystkie okna)
        if (prev != null && !IsWindowBoundary(prev))
        {
            _currentElement = prev;
            if (IsInteractiveElement(prev))
            {
                _soundManager.PlayCursor();
            }
            else
            {
                _soundManager.PlayCursorStatic();
            }
            AnnounceElement(prev, true, skipCursorSound: true, fromNavigation: true);
        }
        else
        {
            // Początek drzewa - tylko dźwięk edge.ogg, bez komunikatu
            _soundManager.PlayEdge();
        }
    }

    /// <summary>
    /// Przełącza tryb nawigacji liniowej/zaawansowanej
    /// </summary>
    private void OnToggleLinearNavigation()
    {
        _keyboardHook.IsLinearNavigationMode = !_keyboardHook.IsLinearNavigationMode;

        string message = _keyboardHook.IsLinearNavigationMode
            ? L.T("engine.advancedNavOff")
            : L.T("engine.advancedNavOn");

        _soundManager.PlayDialItem();
        _speechManager.Speak(message);
    }

    /// <summary>
    /// Obsługa nawigacji strzałkami w ComboBox - odczytuje wybrany element
    /// </summary>
    private void OnComboBoxArrowNavigation(int vkCode)
    {
        // Poczekaj chwilę, aż system zmieni wybór
        Task.Run(async () =>
        {
            await Task.Delay(50);

            // Pobierz aktualnie zaznaczony element
            var focusedElement = UIAutomationHelper.GetFocusedElement();
            if (focusedElement != null)
            {
                try
                {
                    var controlType = focusedElement.Current.ControlType;
                    var name = focusedElement.Current.Name ?? "";

                    // Jeśli fokus jest na elemencie listy, ogłoś go
                    if (controlType == ControlType.ListItem)
                    {
                        var positionInfo = UIAutomationHelper.GetListItemPositionInfo(focusedElement);
                        string announcement = string.IsNullOrEmpty(positionInfo)
                            ? name
                            : $"{name}, {positionInfo}";
                        _speechManager.Speak(announcement);
                    }
                    // Jeśli fokus jest na ComboBox, spróbuj pobrać wartość
                    else if (controlType == ControlType.ComboBox)
                    {
                        if (focusedElement.TryGetCurrentPattern(ValuePattern.Pattern, out var valuePattern))
                        {
                            var value = ((ValuePattern)valuePattern).Current.Value;
                            if (!string.IsNullOrEmpty(value))
                            {
                                _speechManager.Speak(value);
                            }
                        }
                        else if (focusedElement.TryGetCurrentPattern(SelectionPattern.Pattern, out var selPattern))
                        {
                            var selection = ((SelectionPattern)selPattern).Current.GetSelection();
                            if (selection.Length > 0)
                            {
                                var selectedItem = selection[0];
                                var selectedName = selectedItem.Current.Name ?? "";
                                if (!string.IsNullOrEmpty(selectedName))
                                {
                                    _speechManager.Speak(selectedName);
                                }
                            }
                        }
                    }
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"OnComboBoxArrowNavigation: {ex.Message}");
                }
            }
        });
    }

    /// <summary>
    /// Pobiera następny element w kolejności liniowej (depth-first)
    /// </summary>
    private AutomationElement? GetNextElementLinear(AutomationElement? element)
    {
        if (element == null)
            return null;

        var walker = TreeWalker.ControlViewWalker;

        try
        {
            // Najpierw sprawdź dzieci
            var child = walker.GetFirstChild(element);
            if (child != null)
                return child;

            // Następnie rodzeństwo
            var sibling = walker.GetNextSibling(element);
            if (sibling != null)
                return sibling;

            // Wróć do rodzica i szukaj jego rodzeństwa
            var parent = walker.GetParent(element);
            while (parent != null)
            {
                sibling = walker.GetNextSibling(parent);
                if (sibling != null)
                    return sibling;

                parent = walker.GetParent(parent);
            }
        }
        catch { }

        return null;
    }

    /// <summary>
    /// Pobiera poprzedni element w kolejności liniowej
    /// </summary>
    private AutomationElement? GetPreviousElementLinear(AutomationElement? element)
    {
        if (element == null)
            return null;

        var walker = TreeWalker.ControlViewWalker;

        try
        {
            // Sprawdź poprzednie rodzeństwo
            var sibling = walker.GetPreviousSibling(element);
            if (sibling != null)
            {
                // Idź do ostatniego potomka tego rodzeństwa
                return GetLastDescendant(sibling) ?? sibling;
            }

            // Wróć do rodzica
            var parent = walker.GetParent(element);
            if (parent != null)
            {
                return parent;
            }
        }
        catch { }

        return null;
    }

    /// <summary>
    /// Pobiera ostatniego potomka elementu
    /// </summary>
    private AutomationElement? GetLastDescendant(AutomationElement element)
    {
        var walker = TreeWalker.ControlViewWalker;

        try
        {
            var last = walker.GetLastChild(element);
            if (last == null)
                return null;

            // Rekurencyjnie szukaj ostatniego potomka
            var deeper = GetLastDescendant(last);
            return deeper ?? last;
        }
        catch
        {
            return null;
        }
    }

    /// <summary>
    /// Aktywuje bieżący element (NumPad / lub double-click virtual screen)
    /// </summary>
    public void OnClickAction()
    {
        if (_currentElement == null)
        {
            _speechManager.Speak(L.T("engine.noCurrentElement"));
            return;
        }

        try
        {
            if (_currentElement.TryGetCurrentPattern(InvokePattern.Pattern, out var invokePattern))
            {
                _soundManager.PlayClicked();
                ((InvokePattern)invokePattern).Invoke();
                Console.WriteLine("Akcja: Aktywowano element");
                return;
            }

            if (_currentElement.TryGetCurrentPattern(TogglePattern.Pattern, out var togglePattern))
            {
                _soundManager.PlayClicked();
                var toggle = (TogglePattern)togglePattern;
                toggle.Toggle();
                var state = toggle.Current.ToggleState == ToggleState.On
                    ? L.T("state.checked")
                    : L.T("state.unchecked");
                _speechManager.Speak(state);
                Console.WriteLine($"Akcja: Toggle - {state}");
                return;
            }

            if (_currentElement.TryGetCurrentPattern(SelectionItemPattern.Pattern, out var selectionPattern))
            {
                _soundManager.PlayClicked();
                ((SelectionItemPattern)selectionPattern).Select();
                Console.WriteLine("Akcja: Wybrano element");
                return;
            }

            if (_currentElement.TryGetCurrentPattern(ExpandCollapsePattern.Pattern, out var expandPattern))
            {
                _soundManager.PlayClicked();
                var expand = (ExpandCollapsePattern)expandPattern;
                if (expand.Current.ExpandCollapseState == ExpandCollapseState.Expanded)
                {
                    expand.Collapse();
                    _speechManager.Speak(L.T("state.collapsedAdj"));
                }
                else
                {
                    expand.Expand();
                    _speechManager.Speak(L.T("state.expandedAdj"));
                }
                Console.WriteLine("Akcja: Rozwiń/zwiń");
                return;
            }

            _currentElement.SetFocus();
            _soundManager.PlayClicked();
            Console.WriteLine("Akcja: Ustawiono fokus");
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Błąd aktywacji elementu: {ex.Message}");
            _speechManager.Speak(L.T("engine.cannotActivate"));
        }
    }

    private void OnShowMenu()
    {
        Console.WriteLine("Menu czytnika ekranu");
        _speechManager.Speak(L.T("menu.readerMenu"));

        if (System.Windows.Forms.Application.MessageLoop)
        {
            // Zamknij poprzednie menu jeśli było otwarte
            if (_menuDialog != null && !_menuDialog.IsDisposed)
            {
                _menuDialog.Close();
                _menuDialog.Dispose();
            }

            // Utwórz nowy dialog menu
            _menuDialog = new ScreenReaderMenuDialog(
                onSettings: ShowSettings,
                onHelp: ShowHelp,
                onExit: () =>
                {
                    Console.WriteLine("Zamykanie czytnika ekranu...");
                    _speechManager.Speak(L.T("engine.closing"));
                    System.Windows.Forms.Application.Exit();
                }
            );

            // Pokaż dialog
            _menuDialog.Show();
            _menuDialog.Activate();
        }
    }

    private void ShowHelp()
    {
        Console.WriteLine("Otwieranie pomocy...");
        _speechManager.Speak(L.T("engine.help"));
    }

    private void ShowSettings()
    {
        Console.WriteLine("Otwieranie ustawień...");

        var thread = new System.Threading.Thread(() =>
        {
            try
            {
                System.Windows.Forms.Application.EnableVisualStyles();
                var settingsDialog = new SettingsDialog(_speechManager);
                settingsDialog.TopMost = true;
                settingsDialog.StartPosition = System.Windows.Forms.FormStartPosition.CenterScreen;
                System.Windows.Forms.Application.Run(settingsDialog);

                // Przeładuj ustawienia po zamknięciu dialogu
                ReloadSettings();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Błąd otwierania ustawień: {ex.Message}");
            }
        });
        thread.SetApartmentState(System.Threading.ApartmentState.STA);
        thread.Start();
    }

    private void OnStopSpeaking()
    {
        _speechManager.Stop();
        _soundManager.Stop();
        Console.WriteLine("Dźwięk zatrzymany");
    }

    // Edit field navigation handlers
    private void OnMoveToPreviousCharacter()
    {
        // Natychmiast przerwij mowę dla responsywności
        _speechManager.Stop();
        // Małe opóźnienie (20ms) aby kursor zdążył się przesunąć w aplikacji
        Task.Run(async () =>
        {
            await Task.Delay(20);
            _editableTextHandler.ReadCurrentCharacter();
        });
    }

    private void OnMoveToNextCharacter()
    {
        // Natychmiast przerwij mowę dla responsywności
        _speechManager.Stop();
        // Małe opóźnienie (20ms) aby kursor zdążył się przesunąć w aplikacji
        Task.Run(async () =>
        {
            await Task.Delay(20);
            _editableTextHandler.ReadCurrentCharacter();
        });
    }

    private void OnMoveToPreviousLine()
    {
        // Natychmiast przerwij mowę dla responsywności
        _speechManager.Stop();
        // Małe opóźnienie (20ms) aby kursor zdążył się przesunąć w aplikacji
        Task.Run(async () =>
        {
            await Task.Delay(20);
            _editableTextHandler.ReadCurrentLine();
        });
    }

    private void OnMoveToNextLine()
    {
        // Natychmiast przerwij mowę dla responsywności
        _speechManager.Stop();
        // Małe opóźnienie (20ms) aby kursor zdążył się przesunąć w aplikacji
        Task.Run(async () =>
        {
            await Task.Delay(20);
            _editableTextHandler.ReadCurrentLine();
        });
    }

    private void OnMoveToPreviousWord()
    {
        // Natychmiast przerwij mowę dla responsywności
        _speechManager.Stop();
        Task.Run(async () =>
        {
            // Małe opóźnienie (20ms) aby kursor zdążył się przesunąć
            await Task.Delay(20);
            await Task.Delay(50);
            _editableTextHandler.ReadCurrentWord();
        });
    }

    private void OnMoveToNextWord()
    {
        // Natychmiast przerwij mowę dla responsywności
        _speechManager.Stop();
        Task.Run(async () =>
        {
            // Małe opóźnienie (20ms) aby kursor zdążył się przesunąć
            await Task.Delay(20);
            _editableTextHandler.ReadCurrentWord();
        });
    }

    private void OnMoveToStart()
    {
        _speechManager.Speak(L.T("edit.start"), interrupt: true);
    }

    private void OnMoveToEnd()
    {
        _speechManager.Speak(L.T("edit.end"), interrupt: true);
    }

    private void OnReadCurrentChar()
    {
        _editableTextHandler.ReadCurrentCharacter();
    }

    private void OnReadCurrentWord()
    {
        _editableTextHandler.ReadCurrentWord();
    }

    private void OnReadCurrentLine()
    {
        _editableTextHandler.ReadCurrentLine();
    }

    private void OnReadPosition()
    {
        _editableTextHandler.ReadPosition();
    }

    /// <summary>
    /// Ogłasza granice okna według WindowBoundsMode
    /// </summary>
    private void AnnounceWindowBounds(string message, bool isEnd)
    {
        var mode = _settings.WindowBoundsMode;

        switch (mode)
        {
            case Settings.AnnouncementMode.None:
                // Brak oznajmiania
                break;

            case Settings.AnnouncementMode.Sound:
                // Tylko dźwięk
                _soundManager.PlayEdge();
                break;

            case Settings.AnnouncementMode.Speech:
                // Tylko mowa
                _speechManager.Speak(message);
                break;

            case Settings.AnnouncementMode.SpeechAndSound:
                // Mowa i dźwięk
                _soundManager.PlayEdge();
                _speechManager.Speak(message);
                break;
        }
    }

    private void AnnounceElement(AutomationElement element, bool checkEdges, bool skipCursorSound = false, bool fromNavigation = false)
    {
        // Sprawdź kontekst listy i grupy
        bool enteredNewList = false;
        bool enteredNewGroup = false;
        AutomationElement? listParent = null;
        AutomationElement? groupParent = null;

        var controlType = element.Current.ControlType;
        var elementName = element.Current.Name;
        Console.WriteLine($"[AnnounceElement] Element: '{elementName}', Type: {controlType.ProgrammaticName}");

        if (UIAutomationHelper.IsListItem(element))
        {
            Console.WriteLine($"[AnnounceElement] Element jest elementem listy");
            listParent = UIAutomationHelper.GetListParent(element);
            if (listParent != null)
            {
                var listLabel = UIAutomationHelper.GetListLabel(listParent);
                Console.WriteLine($"[AnnounceElement] Lista znaleziona: '{listLabel}', Type: {listParent.Current.ControlType.ProgrammaticName}");

                // Sprawdź czy to nowa lista (inna niż poprzednia)
                if (_currentListParent == null)
                {
                    enteredNewList = true;
                    _isInList = false; // Resetuj przy wejściu do nowej listy
                    Console.WriteLine($"[AnnounceElement] Wchodzimy do nowej listy (poprzednio brak kontekstu)");
                }
                else
                {
                    try
                    {
                        enteredNewList = !Automation.Compare(listParent, _currentListParent);
                        if (enteredNewList)
                        {
                            _isInList = false; // Resetuj przy wejściu do INNEJ listy
                            Console.WriteLine($"[AnnounceElement] Wchodzimy do INNEJ listy");
                        }
                        else
                        {
                            Console.WriteLine($"[AnnounceElement] Jesteśmy w TEJ SAMEJ liście");
                        }
                    }
                    catch
                    {
                        enteredNewList = true;
                        _isInList = false; // Resetuj przy błędzie
                        Console.WriteLine($"[AnnounceElement] Błąd porównania list - traktujemy jako nową listę");
                    }
                }
                _currentListParent = listParent;
            }
            else
            {
                Console.WriteLine($"[AnnounceElement] Element jest elementem listy, ale nie znaleziono rodzica listy");
            }
        }
        else if (_currentListParent != null)
        {
            Console.WriteLine($"[AnnounceElement] Element NIE jest elementem listy, ale mamy kontekst listy - sprawdzam hierarchię");
            // Element nie jest elementem listy - sprawdź czy nadal jesteśmy w kontekście listy
            // Sprawdź hierarchię do góry, czy aktualna lista jest gdzieś w rodzicach
            try
            {
                bool stillInList = false;
                var currentParent = TreeWalker.ControlViewWalker.GetParent(element);
                int depth = 0;

                while (currentParent != null && depth < 10) // Ogranicz głębokość do 10 poziomów
                {
                    try
                    {
                        if (Automation.Compare(currentParent, _currentListParent))
                        {
                            stillInList = true;
                            Console.WriteLine($"[AnnounceElement] Element jest potomkiem aktualnej listy (głębokość: {depth})");
                            break;
                        }
                    }
                    catch
                    {
                        break;
                    }

                    currentParent = TreeWalker.ControlViewWalker.GetParent(currentParent);
                    depth++;
                }

                // Jeśli nie jesteśmy już w kontekście listy, zresetuj
                if (!stillInList)
                {
                    Console.WriteLine($"[AnnounceElement] Element NIE jest potomkiem aktualnej listy - resetuję kontekst");
                    _currentListParent = null;
                    _isInList = false;
                }
            }
            catch (Exception ex)
            {
                // W razie błędu, zresetuj kontekst listy
                Console.WriteLine($"[AnnounceElement] Błąd sprawdzania hierarchii: {ex.Message} - resetuję kontekst");
                _currentListParent = null;
                _isInList = false;
            }
        }
        else
        {
            Console.WriteLine($"[AnnounceElement] Element NIE jest elementem listy i brak kontekstu listy");
            if (_isInList)
            {
                _isInList = false;
            }
        }

        // Sprawdź czy wchod zimy do grupy (ale nie z nawigacji obiektowej)
        if (!fromNavigation && controlType == ControlType.Group)
        {
            // Wchodzimy bezpośrednio do grupy (przez Tab)
            if (_currentGroupParent == null || !Automation.Compare(element, _currentGroupParent))
            {
                enteredNewGroup = true;
                _currentGroupParent = element;
            }
        }
        else if (controlType != ControlType.Group && _currentGroupParent != null)
        {
            // Sprawdź czy element jest dzieckiem grupy - jeśli tak, to właśnie weszliśmy do grupy
            try
            {
                var parent = TreeWalker.ControlViewWalker.GetParent(element);
                if (parent != null && parent.Current.ControlType == ControlType.Group)
                {
                    if (_currentGroupParent == null || !Automation.Compare(parent, _currentGroupParent))
                    {
                        enteredNewGroup = true;
                        groupParent = parent;
                        _currentGroupParent = parent;
                    }
                }
                else
                {
                    // Wyszliśmy z grupy
                    _currentGroupParent = null;
                }
            }
            catch
            {
                _currentGroupParent = null;
            }
        }

        // Jeśli weszliśmy do nowej grupy, ogłoś tylko grupę i zakończ
        if (enteredNewGroup && _settings.AnnounceBlockControls)
        {
            var groupElement = groupParent ?? element;
            var groupName = groupElement.Current.Name;

            if (!string.IsNullOrEmpty(groupName))
            {
                _speechManager.Speak(L.T("engine.namedGroup", groupName), interrupt: true);
            }
            else
            {
                _speechManager.Speak(L.T("ctrlType.group"), interrupt: true);
            }

            _soundManager.PlayCursor();
            return; // Nie ogłaszaj dziecka grupy
        }

        // Pobierz informacje o elemencie i sformatuj zgodnie z ustawieniami
        var elementInfo = UIAutomationHelper.GetElementInfo(element);
        var description = UIAutomationHelper.FormatElementDescription(elementInfo, _settings);

        // Jeśli opis jest pusty (wszystko wyłączone w ustawieniach), użyj przynajmniej nazwy
        if (string.IsNullOrWhiteSpace(description))
        {
            description = !string.IsNullOrWhiteSpace(elementInfo.Name) ? elementInfo.Name : elementInfo.ControlTypePolish;
        }

        // Jeśli to nawigacja obiektowa i ustawienie AnnounceControlTypesNavigation jest włączone,
        // upewnij się że typ kontrolki jest w opisie
        if (fromNavigation && _settings.AnnounceControlTypesNavigation)
        {
            // Sprawdź czy typ kontrolki jest już w opisie
            if (!string.IsNullOrWhiteSpace(elementInfo.ControlTypePolish) &&
                !description.Contains(elementInfo.ControlTypePolish, StringComparison.OrdinalIgnoreCase))
            {
                // Dodaj typ kontrolki do opisu
                if (!string.IsNullOrWhiteSpace(description))
                {
                    description = $"{description}, {elementInfo.ControlTypePolish}";
                }
                else
                {
                    description = elementInfo.ControlTypePolish;
                }
            }
        }

        // Diagnostyka dla list
        Console.WriteLine($"[AnnounceElement] Diagnostyka list: enteredNewList={enteredNewList}, listParent={(listParent != null ? "NOT NULL" : "NULL")}, _isInList={_isInList}, AnnounceBlockControls={_settings.AnnounceBlockControls}");

        // Jeśli weszliśmy do nowej listy, ogłoś TYLKO nazwę listy (bez elementu)
        // Dopiero przy kolejnym elemencie ogłaszaj normalnie
        if (enteredNewList && listParent != null && _settings.AnnounceBlockControls)
        {
            var listLabel = UIAutomationHelper.GetListLabel(listParent);
            Console.WriteLine($"[AnnounceElement] listLabel='{listLabel}'");

            // Jeśli to pierwszy kontakt z listą (!_isInList), ogłoś TYLKO listę
            if (!_isInList)
            {
                _isInList = true;

                if (!string.IsNullOrEmpty(listLabel))
                {
                    // Format: "{nazwa listy}, lista"
                    _speechManager.Speak(L.T("engine.namedList", listLabel), interrupt: true);
                    Console.WriteLine($"[AnnounceElement] ✓ Pierwsze wejście do listy: '{listLabel}, lista'");
                }
                else
                {
                    // Format: "lista"
                    _speechManager.Speak(L.T("ctrlType.list"), interrupt: true);
                    Console.WriteLine($"[AnnounceElement] ✓ Pierwsze wejście do listy (bez etykiety): 'Lista'");
                }

                _soundManager.PlayCursor();
                Console.WriteLine($"[AnnounceElement] ✓ RETURN - nie ogłaszam elementu");
                return; // Nie ogłaszaj elementu w tym momencie
            }
            // Jeśli już jesteśmy w liście (_isInList), ogłaszaj normalnie element
            // (nie zmieniamy description, zostanie ogłoszony standardowo poniżej)
            Console.WriteLine($"[AnnounceElement] Kolejny element w tej samej liście - ogłaszam normalnie (_isInList=true)");
        }
        else
        {
            if (enteredNewList && listParent != null && !_settings.AnnounceBlockControls)
            {
                Console.WriteLine($"[AnnounceElement] ✗ Weszliśmy do nowej listy, ale AnnounceBlockControls jest WYŁĄCZONE");
            }
            else if (enteredNewList && listParent == null)
            {
                Console.WriteLine($"[AnnounceElement] ✗ enteredNewList=true ale listParent=null");
            }
            else if (!enteredNewList && listParent != null)
            {
                Console.WriteLine($"[AnnounceElement] ✗ listParent nie null ale enteredNewList=false (jesteśmy już w liście)");
            }
            else
            {
                Console.WriteLine($"[AnnounceElement] ✗ Warunek nie spełniony - ogłaszam normalnie");
            }
        }

        // Jeśli wyszliśmy z listy, zresetuj flagę
        if (!UIAutomationHelper.IsListItem(element) && _isInList)
        {
            _isInList = false;
            Console.WriteLine($"[AnnounceElement] Wyszliśmy z listy - resetuję flagę _isInList");
        }

        // Jeśli to element menu, dodaj skrót klawiszowy jeśli istnieje
        if (_isInMenu && controlType == ControlType.MenuItem)
        {
            string? shortcut = GetMenuItemShortcut(element);
            if (!string.IsNullOrEmpty(shortcut))
            {
                description = $"{description}, {shortcut}";
            }
        }

        // Pozwól modułowi aplikacji dostosować opis
        description = _appModuleManager.CustomizeElementDescription(element, description);

        Console.WriteLine($"Element: {description}");

        // Sprawdź czy element ma potomków (dla nawigacji numpadem)
        bool hasChildren = fromNavigation && HasChildren(element);

        // Jeśli to panel/grupa z potomkami - odtwórz caninteract.ogg zamiast nazwy typu
        if (hasChildren && (controlType == ControlType.Pane || controlType == ControlType.Group || controlType == ControlType.Custom))
        {
            // Ogłoś tylko nazwę, bez typu "panel", i odtwórz dźwięk caninteract
            var name = element.Current.Name;
            if (!string.IsNullOrWhiteSpace(name))
            {
                _speechManager.Speak(name, interrupt: true);
            }
            _soundManager.PlayCanInteract();
            return;
        }

        // Powiadom moduł przed ogłoszeniem
        _appModuleManager.BeforeAnnounceElement(element);

        // Użyj interrupt:true dla responsywności nawigacji
        _speechManager.Speak(description, interrupt: true);

        if (UIAutomationHelper.IsListItem(element))
        {
            float position = UIAutomationHelper.GetListItemPosition(element);
            _soundManager.PlayListItem(position);
            Console.WriteLine($"  Pozycja na liście: {position:P0}");

            bool isAtStart = UIAutomationHelper.IsAtEdge(element, false);
            bool isAtEnd = UIAutomationHelper.IsAtEdge(element, true);

            if (isAtStart || isAtEnd)
            {
                _soundManager.PlayEdge();
            }
        }
        else if (UIAutomationHelper.IsButton(element))
        {
            Console.WriteLine("  [Przycisk]");
            if (!skipCursorSound && !checkEdges)
                _soundManager.PlayCursor();
        }
        else
        {
            if (!skipCursorSound && !checkEdges)
            {
                // Odtwórz odpowiedni dźwięk w zależności od typu elementu
                if (IsInteractiveElement(element))
                {
                    _soundManager.PlayCursor();
                }
                else
                {
                    _soundManager.PlayCursorStatic();
                }
            }
        }

        // Powiadom moduł po ogłoszeniu
        _appModuleManager.AfterAnnounceElement(element);
    }

    /// <summary>
    /// Sprawdza czy element jest interaktywny (kontrolka, nie tekst statyczny)
    /// </summary>
    private static bool IsInteractiveElement(AutomationElement element)
    {
        try
        {
            var controlType = element.Current.ControlType;

            // Elementy interaktywne
            if (controlType == ControlType.Button ||
                controlType == ControlType.Edit ||
                controlType == ControlType.Hyperlink ||
                controlType == ControlType.CheckBox ||
                controlType == ControlType.RadioButton ||
                controlType == ControlType.ComboBox ||
                controlType == ControlType.ListItem ||
                controlType == ControlType.MenuItem ||
                controlType == ControlType.TabItem ||
                controlType == ControlType.TreeItem ||
                controlType == ControlType.Slider ||
                controlType == ControlType.Spinner ||
                controlType == ControlType.SplitButton ||
                controlType == ControlType.MenuBar ||
                controlType == ControlType.Menu)
            {
                return true;
            }

            // Sprawdź czy element obsługuje wzorce interakcji
            if (element.TryGetCurrentPattern(InvokePattern.Pattern, out _) ||
                element.TryGetCurrentPattern(TogglePattern.Pattern, out _) ||
                element.TryGetCurrentPattern(SelectionItemPattern.Pattern, out _) ||
                element.TryGetCurrentPattern(ExpandCollapsePattern.Pattern, out _) ||
                element.TryGetCurrentPattern(ValuePattern.Pattern, out _))
            {
                return true;
            }
        }
        catch { }

        return false;
    }

    /// <summary>
    /// Sprawdza czy element ma potomków w nawigacji obiektowej
    /// </summary>
    private static bool HasChildren(AutomationElement? element)
    {
        if (element == null)
            return false;

        try
        {
            var walker = TreeWalker.ControlViewWalker;
            var child = walker.GetFirstChild(element);
            return child != null;
        }
        catch
        {
            return false;
        }
    }

    /// <summary>
    /// Sprawdza czy element to element rozwiniętego menu (nie paska menu)
    /// </summary>
    private static bool IsMenuElement(AutomationElement? element)
    {
        if (element == null)
            return false;

        try
        {
            var controlType = element.Current.ControlType;

            // Menu rozwinięte
            if (controlType == ControlType.Menu)
                return true;

            // Element menu - sprawdź czy jest w rozwiniętym menu (nie w pasku menu)
            if (controlType == ControlType.MenuItem)
            {
                // Jeśli bezpośredni rodzic to MenuBar - to element paska menu, nie rozwiniętego menu
                if (IsInMenuBar(element))
                    return false;

                // W przeciwnym razie to element rozwiniętego menu
                return true;
            }

            return false;
        }
        catch
        {
            return false;
        }
    }

    /// <summary>
    /// Pobiera menu nadrzędne dla elementu menu
    /// </summary>
    private static AutomationElement? GetMenuParent(AutomationElement? element)
    {
        if (element == null)
            return null;

        try
        {
            var walker = TreeWalker.ControlViewWalker;
            var parent = walker.GetParent(element);

            while (parent != null)
            {
                var parentType = parent.Current.ControlType;
                if (parentType == ControlType.Menu || parentType == ControlType.MenuBar)
                    return parent;

                if (parentType == ControlType.Window)
                    break;

                parent = walker.GetParent(parent);
            }
        }
        catch { }

        return null;
    }

    /// <summary>
    /// Liczy elementy w menu
    /// </summary>
    private static int CountMenuItems(AutomationElement? menu)
    {
        if (menu == null)
            return 0;

        try
        {
            int count = 0;
            var walker = TreeWalker.ControlViewWalker;
            var child = walker.GetFirstChild(menu);

            while (child != null)
            {
                var childType = child.Current.ControlType;
                if (childType == ControlType.MenuItem)
                    count++;

                child = walker.GetNextSibling(child);
            }

            return count;
        }
        catch
        {
            return 0;
        }
    }

    /// <summary>
    /// Pobiera skrót klawiszowy elementu menu (AcceleratorKey)
    /// </summary>
    private static string? GetMenuItemShortcut(AutomationElement? menuItem)
    {
        if (menuItem == null)
            return null;

        try
        {
            // Pobierz AcceleratorKey property
            object accelObj = menuItem.GetCurrentPropertyValue(AutomationElement.AcceleratorKeyProperty);
            if (accelObj != null && accelObj != AutomationElement.NotSupported)
            {
                string accelerator = accelObj.ToString() ?? "";
                if (!string.IsNullOrEmpty(accelerator))
                {
                    // Normalizuj format (usuń spacje, zamień "Control" na "Ctrl")
                    accelerator = accelerator.Replace(" ", "");
                    accelerator = accelerator.Replace("Control", "Ctrl", StringComparison.OrdinalIgnoreCase);
                    return accelerator;
                }
            }
        }
        catch
        {
            // Niektóre elementy menu nie mają AcceleratorKey
        }

        return null;
    }

    private AutomationElement? GetContainingWindow(AutomationElement? element)
    {
        var current = element;
        while (current != null)
        {
            if (UIAutomationHelper.IsWindow(current))
                return current;
            current = UIAutomationHelper.GetParent(current);
        }
        return null;
    }

    private string GetWindowTitle(AutomationElement? window)
    {
        if (window == null)
            return "Nieznane okno";

        try
        {
            return window.Current.Name;
        }
        catch
        {
            return "Nieznane okno";
        }
    }

    /// <summary>
    /// Sprawdza czy element należy do bieżącego okna
    /// </summary>
    private bool IsElementInCurrentWindow(AutomationElement? element)
    {
        if (element == null || _currentWindow == null)
            return true; // Brak ograniczeń jeśli nie ma okna

        try
        {
            var elementWindow = GetContainingWindow(element);
            if (elementWindow == null)
                return false;

            return Automation.Compare(elementWindow, _currentWindow);
        }
        catch
        {
            return true; // W razie błędu pozwól na nawigację
        }
    }

    /// <summary>
    /// Sprawdza czy element to okno lub jego pasek tytułu (granica okna)
    /// </summary>
    private bool IsWindowBoundary(AutomationElement? element)
    {
        if (element == null)
            return true;

        try
        {
            var controlType = element.Current.ControlType;
            return controlType == ControlType.Window ||
                   controlType == ControlType.TitleBar;
        }
        catch
        {
            return false;
        }
    }

    /// <summary>
    /// Sprawdza czy element to ComboBox lub jest w ComboBox
    /// </summary>
    private static bool IsComboBoxElement(AutomationElement? element)
    {
        if (element == null)
            return false;

        try
        {
            var controlType = element.Current.ControlType;

            // Bezpośrednio ComboBox
            if (controlType == ControlType.ComboBox)
                return true;

            // Element listy wewnątrz ComboBox
            if (controlType == ControlType.ListItem)
            {
                var parent = UIAutomationHelper.GetParent(element);
                while (parent != null)
                {
                    if (parent.Current.ControlType == ControlType.ComboBox)
                        return true;
                    if (parent.Current.ControlType == ControlType.Window)
                        break;
                    parent = UIAutomationHelper.GetParent(parent);
                }
            }

            // Sprawdź rodzica
            var directParent = UIAutomationHelper.GetParent(element);
            if (directParent != null && directParent.Current.ControlType == ControlType.ComboBox)
                return true;
        }
        catch { }

        return false;
    }

    /// <summary>
    /// Przełącza echo klawiatury i zwraca komunikat
    /// </summary>
    public string CycleKeyboardEcho()
    {
        _keyboardEchoMode = _keyboardEchoMode.Next();

        // Zapisz do ustawień
        var setting = _keyboardEchoMode switch
        {
            KeyboardEchoMode.None => Settings.KeyboardEchoSetting.None,
            KeyboardEchoMode.Characters => Settings.KeyboardEchoSetting.Characters,
            KeyboardEchoMode.Words => Settings.KeyboardEchoSetting.Words,
            KeyboardEchoMode.WordsAndChars => Settings.KeyboardEchoSetting.CharactersAndWords,
            _ => Settings.KeyboardEchoSetting.Characters
        };
        _settings.KeyboardEcho = setting;
        _settings.Save();

        return L.T("engine.keyEcho", _keyboardEchoMode.GetLocalizedName());
    }

    /// <summary>
    /// Obsługa włączenia/wyłączenia pokrętła
    /// </summary>
    private void OnDialEnabledChanged(bool enabled)
    {
        _keyboardHook.IsDialEnabled = enabled;
    }

    /// <summary>
    /// Obsługa włączenia/wyłączenia wirtualnego ekranu
    /// </summary>
    private void OnVirtualScreenEnabledChanged(bool enabled)
    {
        Console.WriteLine($"Wirtualny ekran: {(enabled ? "włączony" : "wyłączony")}");
    }

    /// <summary>
    /// Obsługa zmiany elementu w wirtualnym ekranie
    /// </summary>
    private void OnVirtualScreenElementChanged(AutomationElement? element, float stereoPan)
    {
        if (element != null)
        {
            _currentElement = element;
        }
    }

    /// <summary>
    /// Przełącza wirtualny ekran (Insert+Alt+Space)
    /// </summary>
    public void ToggleVirtualScreen()
    {
        _virtualScreenManager.Toggle();
    }

    /// <summary>
    /// Sprawdza czy wirtualny ekran jest włączony
    /// </summary>
    public bool IsVirtualScreenEnabled => _virtualScreenManager.IsEnabled;

    /// <summary>
    /// Przełącza pokrętło (Num Minus)
    /// </summary>
    private void OnToggleDial()
    {
        _soundManager.PlayDialItem();
        string message = _dialManager.Toggle();
        _speechManager.Speak(message);
    }

    /// <summary>
    /// Poprzednia kategoria pokrętła (Num 4)
    /// </summary>
    private void OnDialPreviousCategory()
    {
        _soundManager.PlayDialItem();
        string message = _dialManager.PreviousCategory();
        _speechManager.Speak(message);
    }

    /// <summary>
    /// Następna kategoria pokrętła (Num 6)
    /// </summary>
    private void OnDialNextCategory()
    {
        _soundManager.PlayDialItem();
        string message = _dialManager.NextCategory();
        _speechManager.Speak(message);
    }

    /// <summary>
    /// Poprzedni element w kategorii (Num 8)
    /// </summary>
    private void OnDialPreviousItem()
    {
        var category = _dialManager.CurrentCategory;

        switch (category)
        {
            case DialCategory.Characters:
                _soundManager.PlayDialItem();
                NavigateCharacter(false);
                return;

            case DialCategory.Words:
                _soundManager.PlayDialItem();
                NavigateWord(false);
                return;

            case DialCategory.Buttons:
                _soundManager.PlayDialItem();
                NavigateByType(BrowseMode.QuickNavType.Button, false);
                return;

            case DialCategory.Headings:
                _soundManager.PlayDialItem();
                NavigateByType(BrowseMode.QuickNavType.Heading, false);
                return;

            case DialCategory.ImportantPlaces:
                _soundManager.PlayDialItem();
                NavigateImportantPlace(false);
                return;

            default:
                _soundManager.PlayDialItem();
                string? message = _dialManager.ExecuteItemChange(false, _speechManager);
                if (!string.IsNullOrEmpty(message))
                {
                    _speechManager.Speak(message);
                }
                return;
        }
    }

    /// <summary>
    /// Następny element w kategorii (Num 2)
    /// </summary>
    private void OnDialNextItem()
    {
        var category = _dialManager.CurrentCategory;

        switch (category)
        {
            case DialCategory.Characters:
                _soundManager.PlayDialItem();
                NavigateCharacter(true);
                return;

            case DialCategory.Words:
                _soundManager.PlayDialItem();
                NavigateWord(true);
                return;

            case DialCategory.Buttons:
                _soundManager.PlayDialItem();
                NavigateByType(BrowseMode.QuickNavType.Button, true);
                return;

            case DialCategory.Headings:
                _soundManager.PlayDialItem();
                NavigateByType(BrowseMode.QuickNavType.Heading, true);
                return;

            case DialCategory.ImportantPlaces:
                _soundManager.PlayDialItem();
                NavigateImportantPlace(true);
                return;

            default:
                _soundManager.PlayDialItem();
                string? message = _dialManager.ExecuteItemChange(true, _speechManager);
                if (!string.IsNullOrEmpty(message))
                {
                    _speechManager.Speak(message);
                }
                return;
        }
    }

    /// <summary>
    /// Nawigacja po znakach bieżącego elementu
    /// </summary>
    private void NavigateCharacter(bool next)
    {
        if (_currentElement == null)
        {
            _speechManager.Speak(L.T("element.none"));
            return;
        }

        try
        {
            string text = GetElementText(_currentElement);
            if (string.IsNullOrEmpty(text))
            {
                _speechManager.Speak(L.T("engine.empty"));
                return;
            }

            int currentIndex = _dialCharIndex;

            if (next)
            {
                currentIndex++;
                if (currentIndex >= text.Length)
                {
                    currentIndex = text.Length - 1;
                    _soundManager.PlayEdge();
                }
            }
            else
            {
                currentIndex--;
                if (currentIndex < 0)
                {
                    currentIndex = 0;
                    _soundManager.PlayEdge();
                }
            }

            _dialCharIndex = currentIndex;

            char c = text[currentIndex];

            // Użyj fonetyki jeśli włączone w ustawieniach
            string charName;
            if (_settings.PhoneticInDial)
            {
                charName = GetCharacterAnnouncement(c, true); // Zawsze z fonetyką w dial
            }
            else
            {
                charName = _editNavigator.GetCharacterDescription(c);
            }

            _speechManager.Speak(charName);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"NavigateCharacter: {ex.Message}");
        }
    }

    /// <summary>
    /// Nawigacja po słowach bieżącego elementu
    /// </summary>
    private void NavigateWord(bool next)
    {
        if (_currentElement == null)
        {
            _speechManager.Speak(L.T("element.none"));
            return;
        }

        try
        {
            string text = GetElementText(_currentElement);
            if (string.IsNullOrEmpty(text))
            {
                _speechManager.Speak(L.T("engine.empty"));
                return;
            }

            var words = text.Split(new[] { ' ', '\t', '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
            if (words.Length == 0)
            {
                _speechManager.Speak(L.T("engine.noWords"));
                return;
            }

            int currentIndex = _dialWordIndex;

            if (next)
            {
                currentIndex++;
                if (currentIndex >= words.Length)
                {
                    currentIndex = words.Length - 1;
                    _soundManager.PlayEdge();
                }
            }
            else
            {
                currentIndex--;
                if (currentIndex < 0)
                {
                    currentIndex = 0;
                    _soundManager.PlayEdge();
                }
            }

            _dialWordIndex = currentIndex;
            _speechManager.Speak(words[currentIndex]);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"NavigateWord: {ex.Message}");
        }
    }

    /// <summary>
    /// Nawigacja po elementach określonego typu (przyciski, nagłówki)
    /// </summary>
    private void NavigateByType(BrowseMode.QuickNavType type, bool next)
    {
        if (_browseModeHandler.IsActive)
        {
            _browseModeHandler.HandleQuickNav(
                type == BrowseMode.QuickNavType.Button ? 'b' : 'h',
                !next);
        }
        else
        {
            _speechManager.Speak(L.T("browse.inactive"));
        }
    }

    /// <summary>
    /// Nawigacja po ważnych miejscach
    /// </summary>
    private void NavigateImportantPlace(bool next)
    {
        try
        {
            var places = _importantPlacesManager.GetPlacesForCurrentApp(_currentProcessName);
            if (places.Count == 0)
            {
                _speechManager.Speak(L.T("places.none"));
                return;
            }

            int currentIndex = _dialImportantPlaceIndex;

            if (next)
            {
                currentIndex++;
                if (currentIndex >= places.Count)
                {
                    currentIndex = places.Count - 1;
                    _soundManager.PlayEdge();
                }
            }
            else
            {
                currentIndex--;
                if (currentIndex < 0)
                {
                    currentIndex = 0;
                    _soundManager.PlayEdge();
                }
            }

            _dialImportantPlaceIndex = currentIndex;

            var place = places[currentIndex];
            _speechManager.Speak(L.T("places.nameWithIndex", place.Name, currentIndex + 1, places.Count));
        }
        catch (Exception ex)
        {
            Console.WriteLine($"NavigateImportantPlace: {ex.Message}");
            _speechManager.Speak(L.T("engine.navError"));
        }
    }

    /// <summary>
    /// Aktywuje wybrane ważne miejsce (NumPad 5 w kategorii ImportantPlaces)
    /// </summary>
    private void ActivateCurrentImportantPlace()
    {
        try
        {
            var places = _importantPlacesManager.GetPlacesForCurrentApp(_currentProcessName);
            if (places.Count == 0)
            {
                _speechManager.Speak(L.T("places.none"));
                return;
            }

            if (_dialImportantPlaceIndex >= 0 && _dialImportantPlaceIndex < places.Count)
            {
                var place = places[_dialImportantPlaceIndex];
                bool success = _importantPlacesManager.NavigateToPlace(place);
                if (success)
                {
                    _soundManager.PlayClicked();
                }
            }
            else
            {
                _speechManager.Speak(L.T("places.invalidIndex"));
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"ActivateCurrentImportantPlace: {ex.Message}");
            _speechManager.Speak(L.T("places.activationError"));
        }
    }

    /// <summary>
    /// Pobiera tekst z elementu
    /// </summary>
    private string GetElementText(AutomationElement element)
    {
        try
        {
            if (element.TryGetCurrentPattern(ValuePattern.Pattern, out var valuePattern))
            {
                return ((ValuePattern)valuePattern).Current.Value;
            }

            if (element.TryGetCurrentPattern(TextPattern.Pattern, out var textPattern))
            {
                var range = ((TextPattern)textPattern).DocumentRange;
                return range.GetText(-1);
            }

            return element.Current.Name ?? "";
        }
        catch
        {
            return "";
        }
    }

    // Indeksy dla nawigacji po znakach i słowach
    private int _dialCharIndex = 0;
    private int _dialWordIndex = 0;
    private int _dialImportantPlaceIndex = 0;

    /// <summary>
    /// Obsługa NumPad Slash (/) - aktywuje nawigowany element
    /// </summary>
    private void OnNumpadSlashAction()
    {
        if (_browseModeHandler.IsActive)
        {
            bool activated = _browseModeHandler.ActivateCurrentElement();
            if (activated)
            {
                _soundManager.PlayClicked();
                return;
            }
        }

        if (_currentElement != null)
        {
            OnClickAction();
        }
        else
        {
            _speechManager.Speak(L.T("engine.noNavigatedElement"));
        }
    }

    private void RegisterCustomGestures()
    {
        // Insert+Ctrl+Space - Toggle virtual cursor (TCE)
        _gestureManager.RegisterGesture("insert+ctrl+space", System.Windows.Forms.Keys.Space,
            () =>
            {
                string message = _browseModeHandler.ToggleVirtualCursor();
                _speechManager.Speak(message);
            },
            L.T("gesture.toggleTceCursor.name"),
            L.T("gesture.toggleTceCursor.desc"),
            L.T("gesture.category.navigation"));

        // Insert+2 - Cycle keyboard echo
        _gestureManager.RegisterGesture("insert+2", System.Windows.Forms.Keys.D2,
            () =>
            {
                string message = CycleKeyboardEcho();
                _speechManager.Speak(message);
            },
            L.T("gesture.cycleKeyEcho.name"),
            L.T("gesture.cycleKeyEcho.desc"),
            L.T("gesture.category.speech"));

        // Insert+N - Show screen reader menu
        _gestureManager.RegisterGesture("insert+n", System.Windows.Forms.Keys.N,
            () => OnShowMenu(),
            L.T("gesture.readerMenu.name"),
            L.T("gesture.readerMenu.desc"),
            L.T("gesture.category.system"));

        // Insert+T - Read window title
        _gestureManager.RegisterGesture("insert+t", System.Windows.Forms.Keys.T,
            () =>
            {
                var window = GetContainingWindow(_currentElement);
                if (window != null)
                {
                    var title = GetWindowTitle(window);
                    _speechManager.Speak(L.T("dialog.window", title));
                }
                else
                {
                    _speechManager.Speak(L.T("engine.windowNotFound"));
                }
            },
            L.T("gesture.readWindowTitle.name"),
            L.T("gesture.readWindowTitle.desc"),
            L.T("gesture.category.navigation"));

        // Insert+Ctrl+T - Read current element type
        _gestureManager.RegisterGesture("insert+ctrl+t", System.Windows.Forms.Keys.T,
            () =>
            {
                if (_currentElement != null)
                {
                    var controlType = UIAutomationHelper.GetPolishControlType(_currentElement.Current.ControlType);
                    _speechManager.Speak(L.T("engine.elementType", controlType));
                }
            },
            L.T("gesture.readElementType.name"),
            L.T("gesture.readElementType.desc"),
            L.T("gesture.category.info"));

        // Insert+Alt+Space - Toggle virtual screen (rewolucyjna funkcja!)
        _gestureManager.RegisterGesture("insert+alt+space", System.Windows.Forms.Keys.Space,
            () =>
            {
                ToggleVirtualScreen();
            },
            L.T("gesture.toggleVirtualScreen.name"),
            L.T("gesture.toggleVirtualScreen.desc"),
            L.T("gesture.category.navigation"));

        Console.WriteLine("ScreenReaderEngine: Zarejestrowano niestandardowe gesty");
    }

    /// <summary>
    /// Sprawdza stan hooka klawiatury i reinstaluje w razie potrzeby
    /// </summary>
    private void CheckKeyboardHookHealth(object? state)
    {
        try
        {
            if (!_keyboardHook.IsHookActive && !_disposed)
            {
                Console.WriteLine("ScreenReaderEngine: Hook klawiatury nieaktywny, próba reinstalacji...");
                _keyboardHook.ReinstallHook();
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"ScreenReaderEngine: Błąd sprawdzania hooka: {ex.Message}");
        }
    }

    public void Stop()
    {
        Console.WriteLine("Zatrzymywanie Czytnika Ekranu...");
        _soundManager.PlaySROff();

        // Zatrzymaj timer sprawdzający hook
        _hookHealthTimer?.Dispose();
        _hookHealthTimer = null;

        _focusTracker.Stop();
        _keyboardHook.Stop();
        _soundManager.Stop();
        _liveRegionMonitor.Stop();
        _terminalHandler.Deactivate();
        _accessibilityManager.StopEventListening();
    }

    public void Dispose()
    {
        if (_disposed)
            return;

        _disposed = true;

        Stop();

        // Wyrejestruj flagę czytnika ekranu
        ScreenReaderFlag.Disable();

        // Dispose komponentów
        _browseModeHandler.Dispose();
        _editableTextHandler.Dispose();
        _liveRegionMonitor.Dispose();
        _terminalHandler.Dispose();
        _accessibilityManager.Dispose();
        _hintManager.Dispose();
        _virtualScreenManager.Dispose();
        _appModuleManager.Dispose();

        _soundManager.Dispose();
        _focusTracker.Dispose();
        _keyboardHook.Dispose();
        _speechManager.Dispose();
        _dialogMonitor?.Dispose();
        _trayIcon?.Dispose();
        _menuDialog?.Dispose();
        _nvdaBridge?.Dispose();

        // Zatrzymaj natywny wątek hooków
        ScreenReader.Native.NativeHelper.Shutdown();

        Instance = null;
    }
}
