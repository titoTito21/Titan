using System.Text;

namespace ScreenReader.Settings;

/// <summary>
/// Tryb oznajmiania (brak/dźwięk/mowa/mowa i dźwięk)
/// </summary>
public enum AnnouncementMode
{
    None,       // Brak
    Sound,      // Dźwięk
    Speech,     // Mowa
    SpeechAndSound  // Mowa i dźwięk
}

/// <summary>
/// Modyfikator czytnika ekranu
/// </summary>
public enum ScreenReaderModifier
{
    Insert,         // Tylko Insert
    CapsLock,       // Tylko CapsLock
    InsertAndCapsLock  // Insert i CapsLock
}

/// <summary>
/// Tryb echa klawiatury
/// </summary>
public enum KeyboardEchoSetting
{
    None,           // Brak
    Characters,     // Znaki
    Words,          // Słowa
    CharactersAndWords  // Znaki i słowa
}

/// <summary>
/// Zarządza ustawieniami czytnika ekranu
/// Zapisuje do: %appdata%\titosoft\titan\screenreader\screenReader.ini
/// </summary>
public class SettingsManager
{
    private static SettingsManager? _instance;
    private static readonly object _lock = new();

    private readonly string _settingsPath;
    private readonly Dictionary<string, Dictionary<string, string>> _sections = new();

    /// <summary>
    /// Singleton instance
    /// </summary>
    public static SettingsManager Instance
    {
        get
        {
            if (_instance == null)
            {
                lock (_lock)
                {
                    _instance ??= new SettingsManager();
                }
            }
            return _instance;
        }
    }

    // Sekcje konfiguracji
    private const string SECTION_SPEECH = "Speech";
    private const string SECTION_GENERAL = "General";
    private const string SECTION_VERBOSITY = "Verbosity";
    private const string SECTION_NAVIGATION = "Navigation";
    private const string SECTION_TEXT_EDITING = "TextEditing";
    private const string SECTION_DIAL = "Dial";

    // Klucze Speech
    private const string KEY_SYNTHESIZER = "Synthesizer";
    private const string KEY_VOICE = "Voice";
    private const string KEY_RATE = "Rate";
    private const string KEY_VOLUME = "Volume";
    private const string KEY_PITCH = "Pitch";

    // Klucze General
    private const string KEY_MUTE_OUTSIDE_TCE = "MuteOutsideTCE";
    private const string KEY_STARTUP_ANNOUNCEMENT = "StartupAnnouncement";
    private const string KEY_TCE_ENTRY_SOUND = "TCEEntrySound";
    private const string KEY_MODIFIER = "Modifier";
    private const string KEY_WELCOME_MESSAGE = "WelcomeMessage";
    private const string KEY_SPEAK_HINTS = "SpeakHints";
    private const string KEY_LANGUAGE = "Language";

    // Klucze Verbosity (szczegółowość)
    private const string KEY_ANNOUNCE_BASIC_CONTROLS = "AnnounceBasicControls";
    private const string KEY_ANNOUNCE_BLOCK_CONTROLS = "AnnounceBlockControls";
    private const string KEY_ANNOUNCE_LIST_POSITION = "AnnounceListPosition";
    private const string KEY_MENU_ITEM_COUNT = "MenuItemCount";
    private const string KEY_MENU_NAME = "MenuName";
    private const string KEY_MENU_SOUNDS = "MenuSounds";
    private const string KEY_ELEMENT_NAME = "ElementName";
    private const string KEY_ELEMENT_TYPE = "ElementType";
    private const string KEY_ELEMENT_STATE = "ElementState";
    private const string KEY_ELEMENT_PARAMETER = "ElementParameter";
    private const string KEY_TOGGLE_KEYS_MODE = "ToggleKeysMode";

    // Klucze Navigation
    private const string KEY_ADVANCED_NAVIGATION = "AdvancedNavigation";
    private const string KEY_ANNOUNCE_CONTROL_TYPES_NAV = "AnnounceControlTypesNavigation";
    private const string KEY_ANNOUNCE_HIERARCHY_LEVEL = "AnnounceHierarchyLevel";
    private const string KEY_WINDOW_BOUNDS_MODE = "WindowBoundsMode";
    private const string KEY_PHONETIC_IN_DIAL = "PhoneticInDial";

    // Klucze Dial (pokrętło)
    private const string KEY_DIAL_CHARACTERS = "DialCharacters";
    private const string KEY_DIAL_WORDS = "DialWords";
    private const string KEY_DIAL_BUTTONS = "DialButtons";
    private const string KEY_DIAL_HEADINGS = "DialHeadings";
    private const string KEY_DIAL_VOLUME = "DialVolume";
    private const string KEY_DIAL_SPEED = "DialSpeed";
    private const string KEY_DIAL_VOICE = "DialVoice";
    private const string KEY_DIAL_SYNTHESIZER = "DialSynthesizer";
    private const string KEY_DIAL_IMPORTANT_PLACES = "DialImportantPlaces";

    // Klucze TextEditing
    private const string KEY_PHONETIC_LETTERS = "PhoneticLetters";
    private const string KEY_KEYBOARD_ECHO = "KeyboardEcho";
    private const string KEY_ANNOUNCE_TEXT_BOUNDS = "AnnounceTextBounds";

    private SettingsManager()
    {
        // Ścieżka: %appdata%\titosoft\titan\screenreader\screenReader.ini
        string appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        string settingsDir = Path.Combine(appData, "titosoft", "titan", "screenreader");
        _settingsPath = Path.Combine(settingsDir, "screenReader.ini");

        // Upewnij się, że katalog istnieje
        EnsureDirectoryExists(settingsDir);

        // Załaduj ustawienia
        Load();
    }

    /// <summary>
    /// Ścieżka do pliku ustawień
    /// </summary>
    public string SettingsPath => _settingsPath;

    /// <summary>
    /// Tworzy katalog jeśli nie istnieje
    /// </summary>
    private void EnsureDirectoryExists(string path)
    {
        try
        {
            if (!Directory.Exists(path))
            {
                Directory.CreateDirectory(path);
                Console.WriteLine($"SettingsManager: Utworzono katalog ustawień: {path}");
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"SettingsManager: Błąd tworzenia katalogu: {ex.Message}");
        }
    }

    /// <summary>
    /// Ładuje ustawienia z pliku INI
    /// </summary>
    public void Load()
    {
        _sections.Clear();

        if (!File.Exists(_settingsPath))
        {
            Console.WriteLine($"SettingsManager: Plik ustawień nie istnieje, używam domyślnych: {_settingsPath}");
            SetDefaults();
            return;
        }

        try
        {
            string currentSection = "";
            foreach (var line in File.ReadAllLines(_settingsPath, Encoding.UTF8))
            {
                string trimmedLine = line.Trim();

                // Pomiń puste linie i komentarze
                if (string.IsNullOrEmpty(trimmedLine) || trimmedLine.StartsWith(";") || trimmedLine.StartsWith("#"))
                    continue;

                // Sekcja
                if (trimmedLine.StartsWith("[") && trimmedLine.EndsWith("]"))
                {
                    currentSection = trimmedLine[1..^1];
                    if (!_sections.ContainsKey(currentSection))
                    {
                        _sections[currentSection] = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                    }
                    continue;
                }

                // Klucz=Wartość
                int equalsIndex = trimmedLine.IndexOf('=');
                if (equalsIndex > 0 && !string.IsNullOrEmpty(currentSection))
                {
                    string key = trimmedLine[..equalsIndex].Trim();
                    string value = trimmedLine[(equalsIndex + 1)..].Trim();

                    if (!_sections.ContainsKey(currentSection))
                    {
                        _sections[currentSection] = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                    }
                    _sections[currentSection][key] = value;
                }
            }

            Console.WriteLine($"SettingsManager: Załadowano ustawienia z {_settingsPath}");
        }
        catch (Exception ex)
        {
            Console.WriteLine($"SettingsManager: Błąd ładowania ustawień: {ex.Message}");
            SetDefaults();
        }
    }

    /// <summary>
    /// Zapisuje ustawienia do pliku INI
    /// </summary>
    public void Save()
    {
        try
        {
            var sb = new StringBuilder();
            sb.AppendLine("; Titan Screen Reader Settings");
            sb.AppendLine($"; Generated: {DateTime.Now:yyyy-MM-dd HH:mm:ss}");
            sb.AppendLine();

            foreach (var section in _sections)
            {
                sb.AppendLine($"[{section.Key}]");
                foreach (var kvp in section.Value)
                {
                    sb.AppendLine($"{kvp.Key}={kvp.Value}");
                }
                sb.AppendLine();
            }

            // Upewnij się, że katalog istnieje
            string? dir = Path.GetDirectoryName(_settingsPath);
            if (!string.IsNullOrEmpty(dir))
            {
                EnsureDirectoryExists(dir);
            }

            File.WriteAllText(_settingsPath, sb.ToString(), Encoding.UTF8);
            Console.WriteLine($"SettingsManager: Zapisano ustawienia do {_settingsPath}");
        }
        catch (Exception ex)
        {
            Console.WriteLine($"SettingsManager: Błąd zapisywania ustawień: {ex.Message}");
        }
    }

    /// <summary>
    /// Ustawia wartości domyślne
    /// </summary>
    private void SetDefaults()
    {
        // ========== Speech ==========
        SetValue(SECTION_SPEECH, KEY_SYNTHESIZER, "SAPI5");
        SetValue(SECTION_SPEECH, KEY_VOICE, "");
        SetValue(SECTION_SPEECH, KEY_RATE, "0");
        SetValue(SECTION_SPEECH, KEY_VOLUME, "100");
        SetValue(SECTION_SPEECH, KEY_PITCH, "0");

        // ========== General ==========
        SetValue(SECTION_GENERAL, KEY_MUTE_OUTSIDE_TCE, "false");
        SetValue(SECTION_GENERAL, KEY_STARTUP_ANNOUNCEMENT, "SpeechAndSound");
        SetValue(SECTION_GENERAL, KEY_TCE_ENTRY_SOUND, "true");
        SetValue(SECTION_GENERAL, KEY_MODIFIER, "InsertAndCapsLock");
        SetValue(SECTION_GENERAL, KEY_WELCOME_MESSAGE, "Czytnik ekranu uruchomiony");
        SetValue(SECTION_GENERAL, KEY_SPEAK_HINTS, "true");
        SetValue(SECTION_GENERAL, KEY_LANGUAGE, "pl");

        // ========== Verbosity ==========
        SetValue(SECTION_VERBOSITY, KEY_ANNOUNCE_BASIC_CONTROLS, "true");
        SetValue(SECTION_VERBOSITY, KEY_ANNOUNCE_BLOCK_CONTROLS, "true");
        SetValue(SECTION_VERBOSITY, KEY_ANNOUNCE_LIST_POSITION, "true");
        SetValue(SECTION_VERBOSITY, KEY_MENU_ITEM_COUNT, "true");
        SetValue(SECTION_VERBOSITY, KEY_MENU_NAME, "true");
        SetValue(SECTION_VERBOSITY, KEY_MENU_SOUNDS, "true");
        SetValue(SECTION_VERBOSITY, KEY_ELEMENT_NAME, "true");
        SetValue(SECTION_VERBOSITY, KEY_ELEMENT_TYPE, "true");
        SetValue(SECTION_VERBOSITY, KEY_ELEMENT_STATE, "true");
        SetValue(SECTION_VERBOSITY, KEY_ELEMENT_PARAMETER, "true");
        SetValue(SECTION_VERBOSITY, KEY_TOGGLE_KEYS_MODE, "SpeechAndSound");

        // ========== Navigation ==========
        SetValue(SECTION_NAVIGATION, KEY_ADVANCED_NAVIGATION, "false");
        SetValue(SECTION_NAVIGATION, KEY_ANNOUNCE_CONTROL_TYPES_NAV, "true");
        SetValue(SECTION_NAVIGATION, KEY_ANNOUNCE_HIERARCHY_LEVEL, "true");
        SetValue(SECTION_NAVIGATION, KEY_WINDOW_BOUNDS_MODE, "SpeechAndSound");
        SetValue(SECTION_NAVIGATION, KEY_PHONETIC_IN_DIAL, "true");

        // ========== Dial ==========
        SetValue(SECTION_DIAL, KEY_DIAL_CHARACTERS, "true");
        SetValue(SECTION_DIAL, KEY_DIAL_WORDS, "true");
        SetValue(SECTION_DIAL, KEY_DIAL_BUTTONS, "true");
        SetValue(SECTION_DIAL, KEY_DIAL_HEADINGS, "true");
        SetValue(SECTION_DIAL, KEY_DIAL_VOLUME, "true");
        SetValue(SECTION_DIAL, KEY_DIAL_SPEED, "true");
        SetValue(SECTION_DIAL, KEY_DIAL_VOICE, "true");
        SetValue(SECTION_DIAL, KEY_DIAL_SYNTHESIZER, "true");
        SetValue(SECTION_DIAL, KEY_DIAL_IMPORTANT_PLACES, "true");

        // ========== TextEditing ==========
        SetValue(SECTION_TEXT_EDITING, KEY_PHONETIC_LETTERS, "true");
        SetValue(SECTION_TEXT_EDITING, KEY_KEYBOARD_ECHO, "CharactersAndWords");
        SetValue(SECTION_TEXT_EDITING, KEY_ANNOUNCE_TEXT_BOUNDS, "true");
    }

    /// <summary>
    /// Pobiera wartość z sekcji
    /// </summary>
    public string GetValue(string section, string key, string defaultValue = "")
    {
        if (_sections.TryGetValue(section, out var sectionDict))
        {
            if (sectionDict.TryGetValue(key, out var value))
            {
                return value;
            }
        }
        return defaultValue;
    }

    /// <summary>
    /// Ustawia wartość w sekcji
    /// </summary>
    public void SetValue(string section, string key, string value)
    {
        if (!_sections.ContainsKey(section))
        {
            _sections[section] = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        }
        _sections[section][key] = value;
    }

    /// <summary>
    /// Pobiera wartość int
    /// </summary>
    public int GetInt(string section, string key, int defaultValue = 0)
    {
        string value = GetValue(section, key);
        return int.TryParse(value, out int result) ? result : defaultValue;
    }

    /// <summary>
    /// Pobiera wartość bool
    /// </summary>
    public bool GetBool(string section, string key, bool defaultValue = false)
    {
        string value = GetValue(section, key).ToLowerInvariant();
        return value switch
        {
            "true" or "1" or "yes" or "tak" => true,
            "false" or "0" or "no" or "nie" => false,
            _ => defaultValue
        };
    }

    /// <summary>
    /// Pobiera wartość enum AnnouncementMode
    /// </summary>
    public AnnouncementMode GetAnnouncementMode(string section, string key, AnnouncementMode defaultValue = AnnouncementMode.SpeechAndSound)
    {
        string value = GetValue(section, key);
        return value.ToLowerInvariant() switch
        {
            "none" or "brak" => AnnouncementMode.None,
            "sound" or "dźwięk" => AnnouncementMode.Sound,
            "speech" or "mowa" => AnnouncementMode.Speech,
            "speechandsound" or "mowa i dźwięk" => AnnouncementMode.SpeechAndSound,
            _ => defaultValue
        };
    }

    /// <summary>
    /// Ustawia wartość enum AnnouncementMode
    /// </summary>
    public void SetAnnouncementMode(string section, string key, AnnouncementMode mode)
    {
        string value = mode switch
        {
            AnnouncementMode.None => "None",
            AnnouncementMode.Sound => "Sound",
            AnnouncementMode.Speech => "Speech",
            AnnouncementMode.SpeechAndSound => "SpeechAndSound",
            _ => "SpeechAndSound"
        };
        SetValue(section, key, value);
    }

    // ================== Właściwości Speech ==================

    /// <summary>
    /// Typ syntezatora (SAPI5, OneCore)
    /// </summary>
    public string Synthesizer
    {
        get => GetValue(SECTION_SPEECH, KEY_SYNTHESIZER, "SAPI5");
        set => SetValue(SECTION_SPEECH, KEY_SYNTHESIZER, value);
    }

    /// <summary>
    /// Nazwa głosu
    /// </summary>
    public string Voice
    {
        get => GetValue(SECTION_SPEECH, KEY_VOICE, "");
        set => SetValue(SECTION_SPEECH, KEY_VOICE, value);
    }

    /// <summary>
    /// Szybkość mowy (-10 do 10)
    /// </summary>
    public int Rate
    {
        get => GetInt(SECTION_SPEECH, KEY_RATE, 0);
        set => SetValue(SECTION_SPEECH, KEY_RATE, value.ToString());
    }

    /// <summary>
    /// Głośność (0-100)
    /// </summary>
    public int Volume
    {
        get => GetInt(SECTION_SPEECH, KEY_VOLUME, 100);
        set => SetValue(SECTION_SPEECH, KEY_VOLUME, value.ToString());
    }

    /// <summary>
    /// Wysokość dźwięku (-10 do 10)
    /// </summary>
    public int Pitch
    {
        get => GetInt(SECTION_SPEECH, KEY_PITCH, 0);
        set => SetValue(SECTION_SPEECH, KEY_PITCH, value.ToString());
    }

    // ================== Właściwości General ==================

    /// <summary>
    /// Milcz poza środowiskiem TCE
    /// </summary>
    public bool MuteOutsideTCE
    {
        get => GetBool(SECTION_GENERAL, KEY_MUTE_OUTSIDE_TCE, false);
        set => SetValue(SECTION_GENERAL, KEY_MUTE_OUTSIDE_TCE, value.ToString().ToLower());
    }

    /// <summary>
    /// Sposób oznajmiania uruchamiania/zamykania czytnika
    /// </summary>
    public AnnouncementMode StartupAnnouncement
    {
        get => GetAnnouncementMode(SECTION_GENERAL, KEY_STARTUP_ANNOUNCEMENT, AnnouncementMode.SpeechAndSound);
        set => SetAnnouncementMode(SECTION_GENERAL, KEY_STARTUP_ANNOUNCEMENT, value);
    }

    /// <summary>
    /// Oznajmiaj dźwiękiem wejście/wyjście z TCE
    /// </summary>
    public bool TCEEntrySound
    {
        get => GetBool(SECTION_GENERAL, KEY_TCE_ENTRY_SOUND, true);
        set => SetValue(SECTION_GENERAL, KEY_TCE_ENTRY_SOUND, value.ToString().ToLower());
    }

    /// <summary>
    /// Modyfikator czytnika ekranu
    /// </summary>
    public ScreenReaderModifier Modifier
    {
        get
        {
            string value = GetValue(SECTION_GENERAL, KEY_MODIFIER, "InsertAndCapsLock");
            return value.ToLowerInvariant() switch
            {
                "insert" => ScreenReaderModifier.Insert,
                "capslock" => ScreenReaderModifier.CapsLock,
                "insertandcapslock" or _ => ScreenReaderModifier.InsertAndCapsLock
            };
        }
        set
        {
            string strValue = value switch
            {
                ScreenReaderModifier.Insert => "Insert",
                ScreenReaderModifier.CapsLock => "CapsLock",
                ScreenReaderModifier.InsertAndCapsLock => "InsertAndCapsLock",
                _ => "InsertAndCapsLock"
            };
            SetValue(SECTION_GENERAL, KEY_MODIFIER, strValue);
        }
    }

    /// <summary>
    /// Komunikat powitalny
    /// </summary>
    public string WelcomeMessage
    {
        get => GetValue(SECTION_GENERAL, KEY_WELCOME_MESSAGE, "Czytnik ekranu uruchomiony");
        set => SetValue(SECTION_GENERAL, KEY_WELCOME_MESSAGE, value);
    }

    /// <summary>
    /// Mów podpowiedzi
    /// </summary>
    public bool SpeakHints
    {
        get => GetBool(SECTION_GENERAL, KEY_SPEAK_HINTS, true);
        set => SetValue(SECTION_GENERAL, KEY_SPEAK_HINTS, value.ToString().ToLower());
    }

    /// <summary>
    /// Język interfejsu i komunikatów czytnika ("pl" lub "en").
    /// Odpowiada plikom locale/{kod}.json.
    /// </summary>
    public string Language
    {
        get
        {
            string value = GetValue(SECTION_GENERAL, KEY_LANGUAGE, "pl").Trim().ToLowerInvariant();
            return value is "pl" or "en" ? value : "pl";
        }
        set => SetValue(SECTION_GENERAL, KEY_LANGUAGE, value.Trim().ToLowerInvariant() is "en" ? "en" : "pl");
    }

    // ================== Właściwości Verbosity ==================

    /// <summary>
    /// Oznajmiaj typy kontrolek podstawowych (przycisk, pole edycji, pole wyboru)
    /// </summary>
    public bool AnnounceBasicControls
    {
        get => GetBool(SECTION_VERBOSITY, KEY_ANNOUNCE_BASIC_CONTROLS, true);
        set => SetValue(SECTION_VERBOSITY, KEY_ANNOUNCE_BASIC_CONTROLS, value.ToString().ToLower());
    }

    /// <summary>
    /// Oznajmiaj typy kontrolek blokowych (element listy, element menu, etc)
    /// </summary>
    public bool AnnounceBlockControls
    {
        get => GetBool(SECTION_VERBOSITY, KEY_ANNOUNCE_BLOCK_CONTROLS, true);
        set => SetValue(SECTION_VERBOSITY, KEY_ANNOUNCE_BLOCK_CONTROLS, value.ToString().ToLower());
    }

    /// <summary>
    /// Oznajmiaj pozycję elementu listy
    /// </summary>
    public bool AnnounceListPosition
    {
        get => GetBool(SECTION_VERBOSITY, KEY_ANNOUNCE_LIST_POSITION, true);
        set => SetValue(SECTION_VERBOSITY, KEY_ANNOUNCE_LIST_POSITION, value.ToString().ToLower());
    }

    /// <summary>
    /// Informacja o menu - liczba elementów
    /// </summary>
    public bool MenuItemCount
    {
        get => GetBool(SECTION_VERBOSITY, KEY_MENU_ITEM_COUNT, true);
        set => SetValue(SECTION_VERBOSITY, KEY_MENU_ITEM_COUNT, value.ToString().ToLower());
    }

    /// <summary>
    /// Informacja o menu - nazwa menu
    /// </summary>
    public bool MenuName
    {
        get => GetBool(SECTION_VERBOSITY, KEY_MENU_NAME, true);
        set => SetValue(SECTION_VERBOSITY, KEY_MENU_NAME, value.ToString().ToLower());
    }

    /// <summary>
    /// Informacja o menu - dźwięki otwierania/zamykania
    /// </summary>
    public bool MenuSounds
    {
        get => GetBool(SECTION_VERBOSITY, KEY_MENU_SOUNDS, true);
        set => SetValue(SECTION_VERBOSITY, KEY_MENU_SOUNDS, value.ToString().ToLower());
    }

    /// <summary>
    /// Informacja o elementach - nazwa
    /// </summary>
    public bool ElementName
    {
        get => GetBool(SECTION_VERBOSITY, KEY_ELEMENT_NAME, true);
        set => SetValue(SECTION_VERBOSITY, KEY_ELEMENT_NAME, value.ToString().ToLower());
    }

    /// <summary>
    /// Informacja o elementach - typ
    /// </summary>
    public bool ElementType
    {
        get => GetBool(SECTION_VERBOSITY, KEY_ELEMENT_TYPE, true);
        set => SetValue(SECTION_VERBOSITY, KEY_ELEMENT_TYPE, value.ToString().ToLower());
    }

    /// <summary>
    /// Informacja o elementach - stan kontrolki
    /// </summary>
    public bool ElementState
    {
        get => GetBool(SECTION_VERBOSITY, KEY_ELEMENT_STATE, true);
        set => SetValue(SECTION_VERBOSITY, KEY_ELEMENT_STATE, value.ToString().ToLower());
    }

    /// <summary>
    /// Informacja o elementach - parametr kontrolki (np. URL linku)
    /// </summary>
    public bool ElementParameter
    {
        get => GetBool(SECTION_VERBOSITY, KEY_ELEMENT_PARAMETER, true);
        set => SetValue(SECTION_VERBOSITY, KEY_ELEMENT_PARAMETER, value.ToString().ToLower());
    }

    /// <summary>
    /// Tryb oznajmiania klawiszy przełączających (CapsLock, NumLock, etc)
    /// </summary>
    public AnnouncementMode ToggleKeysMode
    {
        get => GetAnnouncementMode(SECTION_VERBOSITY, KEY_TOGGLE_KEYS_MODE, AnnouncementMode.SpeechAndSound);
        set => SetAnnouncementMode(SECTION_VERBOSITY, KEY_TOGGLE_KEYS_MODE, value);
    }

    // ================== Właściwości Navigation ==================

    /// <summary>
    /// Nawigacja zaawansowana
    /// </summary>
    public bool AdvancedNavigation
    {
        get => GetBool(SECTION_NAVIGATION, KEY_ADVANCED_NAVIGATION, true);
        set => SetValue(SECTION_NAVIGATION, KEY_ADVANCED_NAVIGATION, value.ToString().ToLower());
    }

    /// <summary>
    /// Oznajmiaj typy kontrolek w trakcie nawigacji
    /// </summary>
    public bool AnnounceControlTypesNavigation
    {
        get => GetBool(SECTION_NAVIGATION, KEY_ANNOUNCE_CONTROL_TYPES_NAV, true);
        set => SetValue(SECTION_NAVIGATION, KEY_ANNOUNCE_CONTROL_TYPES_NAV, value.ToString().ToLower());
    }

    /// <summary>
    /// Oznajmiaj poziom w hierarchii nawigacji obiektowej
    /// </summary>
    public bool AnnounceHierarchyLevel
    {
        get => GetBool(SECTION_NAVIGATION, KEY_ANNOUNCE_HIERARCHY_LEVEL, true);
        set => SetValue(SECTION_NAVIGATION, KEY_ANNOUNCE_HIERARCHY_LEVEL, value.ToString().ToLower());
    }

    /// <summary>
    /// Tryb oznajmiania początku/końca okna
    /// </summary>
    public AnnouncementMode WindowBoundsMode
    {
        get => GetAnnouncementMode(SECTION_NAVIGATION, KEY_WINDOW_BOUNDS_MODE, AnnouncementMode.SpeechAndSound);
        set => SetAnnouncementMode(SECTION_NAVIGATION, KEY_WINDOW_BOUNDS_MODE, value);
    }

    /// <summary>
    /// Ogłaszaj przykład fonetyczny w trakcie nawigacji przy pomocy pokrętła
    /// </summary>
    public bool PhoneticInDial
    {
        get => GetBool(SECTION_NAVIGATION, KEY_PHONETIC_IN_DIAL, true);
        set => SetValue(SECTION_NAVIGATION, KEY_PHONETIC_IN_DIAL, value.ToString().ToLower());
    }

    // ================== Właściwości Dial ==================

    /// <summary>
    /// Pokrętło - znaki
    /// </summary>
    public bool DialCharacters
    {
        get => GetBool(SECTION_DIAL, KEY_DIAL_CHARACTERS, true);
        set => SetValue(SECTION_DIAL, KEY_DIAL_CHARACTERS, value.ToString().ToLower());
    }

    /// <summary>
    /// Pokrętło - słowa
    /// </summary>
    public bool DialWords
    {
        get => GetBool(SECTION_DIAL, KEY_DIAL_WORDS, true);
        set => SetValue(SECTION_DIAL, KEY_DIAL_WORDS, value.ToString().ToLower());
    }

    /// <summary>
    /// Pokrętło - przyciski
    /// </summary>
    public bool DialButtons
    {
        get => GetBool(SECTION_DIAL, KEY_DIAL_BUTTONS, true);
        set => SetValue(SECTION_DIAL, KEY_DIAL_BUTTONS, value.ToString().ToLower());
    }

    /// <summary>
    /// Pokrętło - nagłówki
    /// </summary>
    public bool DialHeadings
    {
        get => GetBool(SECTION_DIAL, KEY_DIAL_HEADINGS, true);
        set => SetValue(SECTION_DIAL, KEY_DIAL_HEADINGS, value.ToString().ToLower());
    }

    /// <summary>
    /// Pokrętło - głośność
    /// </summary>
    public bool DialVolume
    {
        get => GetBool(SECTION_DIAL, KEY_DIAL_VOLUME, true);
        set => SetValue(SECTION_DIAL, KEY_DIAL_VOLUME, value.ToString().ToLower());
    }

    /// <summary>
    /// Pokrętło - szybkość
    /// </summary>
    public bool DialSpeed
    {
        get => GetBool(SECTION_DIAL, KEY_DIAL_SPEED, true);
        set => SetValue(SECTION_DIAL, KEY_DIAL_SPEED, value.ToString().ToLower());
    }

    /// <summary>
    /// Pokrętło - głos
    /// </summary>
    public bool DialVoice
    {
        get => GetBool(SECTION_DIAL, KEY_DIAL_VOICE, true);
        set => SetValue(SECTION_DIAL, KEY_DIAL_VOICE, value.ToString().ToLower());
    }

    /// <summary>
    /// Pokrętło - syntezator
    /// </summary>
    public bool DialSynthesizer
    {
        get => GetBool(SECTION_DIAL, KEY_DIAL_SYNTHESIZER, true);
        set => SetValue(SECTION_DIAL, KEY_DIAL_SYNTHESIZER, value.ToString().ToLower());
    }

    /// <summary>
    /// Pokrętło - ważne miejsca
    /// </summary>
    public bool DialImportantPlaces
    {
        get => GetBool(SECTION_DIAL, KEY_DIAL_IMPORTANT_PLACES, true);
        set => SetValue(SECTION_DIAL, KEY_DIAL_IMPORTANT_PLACES, value.ToString().ToLower());
    }

    // ================== Właściwości TextEditing ==================

    /// <summary>
    /// Oznajmiaj litery fonetycznie
    /// </summary>
    public bool PhoneticLetters
    {
        get => GetBool(SECTION_TEXT_EDITING, KEY_PHONETIC_LETTERS, true);
        set => SetValue(SECTION_TEXT_EDITING, KEY_PHONETIC_LETTERS, value.ToString().ToLower());
    }

    /// <summary>
    /// Tryb echa klawiatury
    /// </summary>
    public KeyboardEchoSetting KeyboardEcho
    {
        get
        {
            string value = GetValue(SECTION_TEXT_EDITING, KEY_KEYBOARD_ECHO, "CharactersAndWords");
            return value.ToLowerInvariant() switch
            {
                "none" or "brak" => KeyboardEchoSetting.None,
                "characters" or "znaki" => KeyboardEchoSetting.Characters,
                "words" or "słowa" => KeyboardEchoSetting.Words,
                "charactersandwords" or "znaki i słowa" or _ => KeyboardEchoSetting.CharactersAndWords
            };
        }
        set
        {
            string strValue = value switch
            {
                KeyboardEchoSetting.None => "None",
                KeyboardEchoSetting.Characters => "Characters",
                KeyboardEchoSetting.Words => "Words",
                KeyboardEchoSetting.CharactersAndWords => "CharactersAndWords",
                _ => "CharactersAndWords"
            };
            SetValue(SECTION_TEXT_EDITING, KEY_KEYBOARD_ECHO, strValue);
        }
    }

    /// <summary>
    /// Oznajmiaj początek i koniec tekstu
    /// </summary>
    public bool AnnounceTextBounds
    {
        get => GetBool(SECTION_TEXT_EDITING, KEY_ANNOUNCE_TEXT_BOUNDS, true);
        set => SetValue(SECTION_TEXT_EDITING, KEY_ANNOUNCE_TEXT_BOUNDS, value.ToString().ToLower());
    }
}
