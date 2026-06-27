using System.Text;
using System.Text.RegularExpressions;

namespace ScreenReader.KeyboardShortcuts;

/// <summary>
/// Zarządza plikami .KEY z opisami skrótów klawiszowych dla różnych aplikacji
/// Format pliku: [klawisz]=opis (np. [controla]=zaznacz wszystko)
/// </summary>
public class KeyFileManager
{
    private readonly string _keyFilesDirectory;
    private readonly Dictionary<string, Dictionary<string, string>> _loadedKeyFiles = new();
    private readonly object _lock = new();

    /// <summary>
    /// Konstruktor - inicjalizuje katalog key files
    /// </summary>
    public KeyFileManager()
    {
        // Katalog key files w folderze ustawień użytkownika
        string appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        string settingsDir = Path.Combine(appData, "titosoft", "titan", "screenreader");
        _keyFilesDirectory = Path.Combine(settingsDir, "key files");

        // Upewnij się że katalog istnieje
        EnsureKeyFilesDirectory();

        // Kopiuj wbudowane pliki .KEY jeśli nie istnieją
        ExtractEmbeddedKeyFiles();
    }

    /// <summary>
    /// Tworzy katalog key files jeśli nie istnieje
    /// </summary>
    private void EnsureKeyFilesDirectory()
    {
        try
        {
            if (!Directory.Exists(_keyFilesDirectory))
            {
                Directory.CreateDirectory(_keyFilesDirectory);
                Console.WriteLine($"KeyFileManager: Utworzono katalog: {_keyFilesDirectory}");
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"KeyFileManager: Błąd tworzenia katalogu: {ex.Message}");
        }
    }

    /// <summary>
    /// Ekstraktuje wbudowane pliki .KEY z zasobów do katalogu użytkownika
    /// </summary>
    private void ExtractEmbeddedKeyFiles()
    {
        try
        {
            var assembly = System.Reflection.Assembly.GetExecutingAssembly();
            var resourceNames = assembly.GetManifestResourceNames()
                .Where(name => name.Contains(".key_files.") && name.EndsWith(".KEY", StringComparison.OrdinalIgnoreCase))
                .ToList();

            Console.WriteLine($"KeyFileManager: Znaleziono {resourceNames.Count} wbudowanych plików .KEY");

            foreach (var resourceName in resourceNames)
            {
                try
                {
                    // Wyciągnij nazwę pliku z resource name
                    // np. "ScreenReader.key_files.NOTEPAD.KEY" -> "NOTEPAD.KEY"
                    // Znajdź ostatnie wystąpienie ".key_files."
                    int keyFilesIndex = resourceName.IndexOf(".key_files.", StringComparison.OrdinalIgnoreCase);
                    if (keyFilesIndex < 0)
                    {
                        Console.WriteLine($"KeyFileManager: Nieprawidłowa nazwa zasobu: {resourceName}");
                        continue;
                    }

                    // Wyciągnij nazwę pliku po ".key_files."
                    string fileName = resourceName.Substring(keyFilesIndex + ".key_files.".Length);

                    string targetPath = Path.Combine(_keyFilesDirectory, fileName);

                    // Kopiuj tylko jeśli plik nie istnieje (pozwól użytkownikowi modyfikować)
                    if (!File.Exists(targetPath))
                    {
                        using var resourceStream = assembly.GetManifestResourceStream(resourceName);
                        if (resourceStream != null)
                        {
                            using var fileStream = File.Create(targetPath);
                            resourceStream.CopyTo(fileStream);
                            Console.WriteLine($"KeyFileManager: Wyodrębniono {fileName}");
                        }
                    }
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"KeyFileManager: Błąd wyodrębniania {resourceName}: {ex.Message}");
                }
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"KeyFileManager: Błąd ekstrakcji plików: {ex.Message}");
        }
    }

    /// <summary>
    /// Pobiera opis skrótu klawiszowego dla danej aplikacji
    /// </summary>
    /// <param name="processName">Nazwa procesu aplikacji (bez .exe)</param>
    /// <param name="shortcut">Skrót klawiszowy w formacie "Ctrl+O", "Alt+F4" itp.</param>
    /// <returns>Opis skrótu lub null jeśli nie znaleziono</returns>
    public string? GetShortcutDescription(string processName, string shortcut)
    {
        if (string.IsNullOrEmpty(processName) || string.IsNullOrEmpty(shortcut))
            return null;

        lock (_lock)
        {
            // Usuń .exe z nazwy procesu
            processName = processName.Replace(".exe", "", StringComparison.OrdinalIgnoreCase);

            // Załaduj plik .KEY dla tej aplikacji jeśli jeszcze nie jest załadowany
            if (!_loadedKeyFiles.ContainsKey(processName))
            {
                LoadKeyFile(processName);
            }

            // Sprawdź czy mamy mapowanie dla tej aplikacji
            if (_loadedKeyFiles.TryGetValue(processName, out var keyMap))
            {
                // Normalizuj skrót do formatu używanego w plikach .KEY
                string normalizedShortcut = NormalizeShortcutToKeyFileFormat(shortcut);

                if (keyMap.TryGetValue(normalizedShortcut, out var description))
                {
                    return description;
                }
            }

            return null;
        }
    }

    /// <summary>
    /// Ładuje plik .KEY dla danej aplikacji
    /// </summary>
    private void LoadKeyFile(string processName)
    {
        try
        {
            // Szukaj pliku .KEY (wielkość liter nie ma znaczenia)
            string keyFilePath = Path.Combine(_keyFilesDirectory, $"{processName}.KEY");

            if (!File.Exists(keyFilePath))
            {
                // Spróbuj z różnymi wariantami wielkości liter
                var files = Directory.GetFiles(_keyFilesDirectory, "*.KEY", SearchOption.TopDirectoryOnly);
                keyFilePath = files.FirstOrDefault(f =>
                    Path.GetFileNameWithoutExtension(f).Equals(processName, StringComparison.OrdinalIgnoreCase)) ?? "";
            }

            if (File.Exists(keyFilePath))
            {
                var keyMap = ParseKeyFile(keyFilePath);
                _loadedKeyFiles[processName] = keyMap;
                Console.WriteLine($"KeyFileManager: Załadowano {keyMap.Count} skrótów z {Path.GetFileName(keyFilePath)}");
            }
            else
            {
                // Dodaj pusty mapowanie żeby nie próbować ładować ponownie
                _loadedKeyFiles[processName] = new Dictionary<string, string>();
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"KeyFileManager: Błąd ładowania pliku dla {processName}: {ex.Message}");
            _loadedKeyFiles[processName] = new Dictionary<string, string>();
        }
    }

    /// <summary>
    /// Parsuje plik .KEY i zwraca mapowanie skrótów
    /// </summary>
    private Dictionary<string, string> ParseKeyFile(string filePath)
    {
        var keyMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        try
        {
            // Wykryj kodowanie pliku
            Encoding encoding = DetectEncoding(filePath);

            // Wczytaj plik z wykrytym kodowaniem
            string[] lines = File.ReadAllLines(filePath, encoding);

            foreach (string line in lines)
            {
                if (string.IsNullOrWhiteSpace(line))
                    continue;

                // Format: [klawisz]=opis
                // Przykłady:
                // [ c o n t r o l a ] = z a z n a c z   w s z y s t k o
                // [bks]=cofnij
                // [controla]=zaznacz wszystko

                int equalsIndex = line.IndexOf('=');
                if (equalsIndex <= 0)
                    continue;

                string keyPart = line.Substring(0, equalsIndex).Trim();
                string valuePart = line.Substring(equalsIndex + 1).Trim();

                // Usuń nawiasy kwadratowe
                keyPart = keyPart.Trim('[', ']');

                // Usuń spacje między literami jeśli występują
                // "c o n t r o l a" -> "controla"
                keyPart = RemoveSpacesBetweenLetters(keyPart);

                // Usuń spacje między literami w wartości jeśli występują
                valuePart = RemoveSpacesBetweenLetters(valuePart);

                if (!string.IsNullOrEmpty(keyPart) && !string.IsNullOrEmpty(valuePart))
                {
                    keyMap[keyPart] = valuePart;
                }
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"KeyFileManager: Błąd parsowania {filePath}: {ex.Message}");
        }

        return keyMap;
    }

    /// <summary>
    /// Usuwa spacje między pojedynczymi literami/słowami
    /// "c o n t r o l a" -> "controla"
    /// "z a z n a c z   w s z y s t k o" -> "zaznacz wszystko"
    /// </summary>
    private string RemoveSpacesBetweenLetters(string text)
    {
        if (string.IsNullOrEmpty(text))
            return text;

        // Sprawdź czy to format ze spacjami między literami
        // (więcej niż 50% znaków to spacje i litery są pojedyncze)
        int spaceCount = text.Count(c => c == ' ');
        int letterCount = text.Count(c => char.IsLetterOrDigit(c));

        if (spaceCount > 0 && letterCount > 0)
        {
            // Sprawdź czy to format "l i t e r a   p o   l i t e r z e"
            var parts = text.Split(' ', StringSplitOptions.RemoveEmptyEntries);
            bool singleLetterFormat = parts.All(p => p.Length == 1 || p.Length == 2);

            if (singleLetterFormat)
            {
                // Usuń wszystkie spacje
                return text.Replace(" ", "");
            }
            else
            {
                // Zachowaj podwójne spacje jako pojedyncze (do zachowania odstępów między słowami)
                return Regex.Replace(text, @" +", " ");
            }
        }

        return text;
    }

    /// <summary>
    /// Normalizuje skrót klawiszowy do formatu używanego w plikach .KEY
    /// "Ctrl+A" -> "controla"
    /// "Alt+F4" -> "altf4"
    /// "F5" -> "f5"
    /// </summary>
    private string NormalizeShortcutToKeyFileFormat(string shortcut)
    {
        // Usuń spacje, zamień na małe litery
        shortcut = shortcut.Replace(" ", "").ToLowerInvariant();

        // Usuń znaki + (np. "ctrl+a" -> "controla")
        shortcut = shortcut.Replace("+", "");

        // Pliki .KEY używają pełnej nazwy "control", nie "ctrl"
        shortcut = shortcut.Replace("ctrl", "control");

        // Specjalne mapowania klawiszy
        shortcut = shortcut.Replace("backspace", "bks");
        shortcut = shortcut.Replace("pageup", "pageup");
        shortcut = shortcut.Replace("pagedown", "pagedown");
        shortcut = shortcut.Replace("delete", "delete");
        shortcut = shortcut.Replace("insert", "insert");
        shortcut = shortcut.Replace("home", "home");
        shortcut = shortcut.Replace("end", "end");
        shortcut = shortcut.Replace("escape", "escape");
        shortcut = shortcut.Replace("tab", "tab");
        shortcut = shortcut.Replace("enter", "enter");

        // Strzałki
        shortcut = shortcut.Replace("leftarrow", "leftarrow");
        shortcut = shortcut.Replace("rightarrow", "rightarrow");
        shortcut = shortcut.Replace("uparrow", "uparrow");
        shortcut = shortcut.Replace("downarrow", "downarrow");
        shortcut = shortcut.Replace("left", "leftarrow");
        shortcut = shortcut.Replace("right", "rightarrow");
        shortcut = shortcut.Replace("up", "uparrow");
        shortcut = shortcut.Replace("down", "downarrow");

        // NumPad
        if (shortcut.Contains("numpad"))
        {
            // np. "numpad4" -> "numpad4" (bez zmian)
        }

        return shortcut;
    }

    /// <summary>
    /// Przeładowuje wszystkie pliki .KEY (użyteczne gdy użytkownik edytuje pliki)
    /// </summary>
    public void ReloadKeyFiles()
    {
        lock (_lock)
        {
            _loadedKeyFiles.Clear();
            Console.WriteLine("KeyFileManager: Przeładowano wszystkie pliki .KEY");
        }
    }

    /// <summary>
    /// Wykrywa kodowanie pliku na podstawie BOM lub zawartości
    /// </summary>
    private Encoding DetectEncoding(string filePath)
    {
        // Przeczytaj pierwsze bajty aby sprawdzić BOM
        byte[] buffer = new byte[4];
        using (FileStream file = new FileStream(filePath, FileMode.Open, FileAccess.Read))
        {
            file.Read(buffer, 0, 4);
        }

        // UTF-16 LE BOM: FF FE
        if (buffer[0] == 0xFF && buffer[1] == 0xFE)
        {
            return Encoding.Unicode; // UTF-16 LE
        }

        // UTF-16 BE BOM: FE FF
        if (buffer[0] == 0xFE && buffer[1] == 0xFF)
        {
            return Encoding.BigEndianUnicode; // UTF-16 BE
        }

        // UTF-8 BOM: EF BB BF
        if (buffer[0] == 0xEF && buffer[1] == 0xBB && buffer[2] == 0xBF)
        {
            return Encoding.UTF8;
        }

        // Brak BOM - prawdopodobnie Windows-1250 (polskie kodowanie) lub ASCII
        // Dla polskich znaków używamy Windows-1250 (code page 1250)
        try
        {
            return Encoding.GetEncoding(1250); // Windows-1250 (Central European)
        }
        catch
        {
            // Fallback do domyślnego kodowania systemu
            return Encoding.Default;
        }
    }

    /// <summary>
    /// Zwraca ścieżkę do katalogu z plikami .KEY
    /// </summary>
    public string KeyFilesDirectory => _keyFilesDirectory;
}
