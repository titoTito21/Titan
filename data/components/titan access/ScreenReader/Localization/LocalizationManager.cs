using System.Text;
using System.Text.Json;
using ScreenReader.Settings;

namespace ScreenReader.Localization;

/// <summary>
/// Prosty menedżer lokalizacji oparty na plikach locale/{kod}.json (płaska mapa
/// klucz -> tekst). Obsługuje polski ("pl") i angielski ("en").
///
/// Polski jest zawsze ładowany jako język zapasowy: jeśli klucz nie istnieje
/// w bieżącym języku, używany jest tekst polski, a jeśli i tam go nie ma -
/// zwracany jest sam klucz (dzięki czemu brak tłumaczenia jest widoczny, a nie
/// powoduje awarii).
///
/// Pliki locale/*.json są kopiowane obok pliku exe przez ScreenReader.csproj.
/// </summary>
public static class LocalizationManager
{
    private static Dictionary<string, string> _current = new(StringComparer.Ordinal);
    private static Dictionary<string, string> _fallback = new(StringComparer.Ordinal);
    private static string _language = "pl";
    private static bool _loaded;
    private static readonly object _lock = new();

    /// <summary>Kod aktualnie załadowanego języka ("pl" lub "en").</summary>
    public static string Language => _language;

    /// <summary>
    /// Ładuje język z ustawień (SettingsManager.Language) lub podany jawnie.
    /// </summary>
    public static void Initialize(string? language = null)
    {
        language ??= SafeGetSettingsLanguage();
        Load(language);
    }

    /// <summary>
    /// Ładuje wskazany język. Polski jest dodatkowo ładowany jako fallback.
    /// </summary>
    public static void Load(string language)
    {
        lock (_lock)
        {
            _language = string.Equals(language, "en", StringComparison.OrdinalIgnoreCase) ? "en" : "pl";
            _fallback = LoadFile("pl");
            _current = _language == "pl" ? _fallback : LoadFile("en");
            _loaded = true;
            Console.WriteLine($"LocalizationManager: język = {_language}, załadowano {_current.Count} kluczy");
        }
    }

    private static string SafeGetSettingsLanguage()
    {
        try { return SettingsManager.Instance.Language; }
        catch { return "pl"; }
    }

    private static Dictionary<string, string> LoadFile(string lang)
    {
        try
        {
            string path = Path.Combine(AppContext.BaseDirectory, "locale", $"{lang}.json");
            if (!File.Exists(path))
            {
                Console.WriteLine($"LocalizationManager: brak pliku {path}");
                return new(StringComparer.Ordinal);
            }

            string json = File.ReadAllText(path, Encoding.UTF8);
            var dict = JsonSerializer.Deserialize<Dictionary<string, string>>(json);
            return dict != null
                ? new Dictionary<string, string>(dict, StringComparer.Ordinal)
                : new Dictionary<string, string>(StringComparer.Ordinal);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"LocalizationManager: błąd ładowania {lang}.json: {ex.Message}");
            return new(StringComparer.Ordinal);
        }
    }

    /// <summary>
    /// Zwraca przetłumaczony tekst dla klucza. Kolejność: bieżący język ->
    /// polski (fallback) -> sam klucz.
    /// </summary>
    public static string Get(string key)
    {
        if (!_loaded)
            Initialize();

        if (_current.TryGetValue(key, out var value))
            return value;
        if (_fallback.TryGetValue(key, out var fallback))
            return fallback;
        return key;
    }

    /// <summary>
    /// Jak <see cref="Get(string)"/>, ale stosuje string.Format z podanymi
    /// argumentami (np. "Strona {0} z {1}").
    /// </summary>
    public static string Get(string key, params object[] args)
    {
        string template = Get(key);
        if (args is not { Length: > 0 })
            return template;
        try { return string.Format(template, args); }
        catch (FormatException) { return template; }
    }
}

/// <summary>
/// Krótki alias do <see cref="LocalizationManager"/>. Użycie: L.T("klucz")
/// lub L.T("klucz", arg0, arg1).
/// </summary>
public static class L
{
    public static string T(string key) => LocalizationManager.Get(key);
    public static string T(string key, params object[] args) => LocalizationManager.Get(key, args);
}
