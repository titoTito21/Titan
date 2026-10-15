using ScreenReader.Settings;

namespace ScreenReader.InputGestures;

/// <summary>
/// Kategoria pokrętła (dial)
/// </summary>
public enum DialCategory
{
    /// <summary>Nawigacja po znakach</summary>
    Characters,

    /// <summary>Nawigacja po słowach</summary>
    Words,

    /// <summary>Nawigacja po przyciskach</summary>
    Buttons,

    /// <summary>Nawigacja po nagłówkach</summary>
    Headings,

    /// <summary>Ustawienie głosu</summary>
    Voice,

    /// <summary>Ustawienie szybkości mowy</summary>
    Speed,

    /// <summary>Ustawienie głośności</summary>
    Volume,

    /// <summary>Wybór syntezatora</summary>
    Synthesizer,

    /// <summary>Ważne miejsca</summary>
    ImportantPlaces
}

/// <summary>
/// Zarządza pokrętłem (dial) do szybkiej nawigacji i ustawień.
/// Włączane przez Num Minus, nawigacja przez Num 4/6.
/// Filtruje kategorie na podstawie ustawień użytkownika.
/// </summary>
public class DialManager
{
    private static readonly DialCategory[] _allCategories =
    {
        DialCategory.Characters,
        DialCategory.Words,
        DialCategory.Buttons,
        DialCategory.Headings,
        DialCategory.Voice,
        DialCategory.Speed,
        DialCategory.Volume,
        DialCategory.Synthesizer,
        DialCategory.ImportantPlaces
    };

    private List<DialCategory> _enabledCategories = new();
    private int _currentCategoryIndex;
    private bool _isEnabled;

    /// <summary>Czy pokrętło jest włączone</summary>
    public bool IsEnabled
    {
        get => _isEnabled;
        private set => _isEnabled = value;
    }

    /// <summary>Aktualna kategoria</summary>
    public DialCategory CurrentCategory => _enabledCategories.Count > 0
        ? _enabledCategories[_currentCategoryIndex]
        : DialCategory.Characters;

    /// <summary>Event wywoływany przy zmianie kategorii</summary>
    public event Action<DialCategory>? CategoryChanged;

    /// <summary>Event wywoływany przy włączeniu/wyłączeniu pokrętła</summary>
    public event Action<bool>? EnabledChanged;

    /// <summary>
    /// Konstruktor - inicjalizuje listę włączonych kategorii z ustawień
    /// </summary>
    public DialManager()
    {
        RefreshEnabledCategories();
    }

    /// <summary>
    /// Odświeża listę włączonych kategorii na podstawie ustawień
    /// </summary>
    public void RefreshEnabledCategories()
    {
        var settings = SettingsManager.Instance;
        _enabledCategories.Clear();

        // Sprawdź każdą kategorię i dodaj tylko włączone
        if (settings.DialCharacters)
            _enabledCategories.Add(DialCategory.Characters);
        if (settings.DialWords)
            _enabledCategories.Add(DialCategory.Words);
        if (settings.DialButtons)
            _enabledCategories.Add(DialCategory.Buttons);
        if (settings.DialHeadings)
            _enabledCategories.Add(DialCategory.Headings);
        if (settings.DialVolume)
            _enabledCategories.Add(DialCategory.Volume);
        if (settings.DialSpeed)
            _enabledCategories.Add(DialCategory.Speed);
        if (settings.DialVoice)
            _enabledCategories.Add(DialCategory.Voice);
        if (settings.DialSynthesizer)
            _enabledCategories.Add(DialCategory.Synthesizer);
        if (settings.DialImportantPlaces)
            _enabledCategories.Add(DialCategory.ImportantPlaces);

        // Jeśli żadna kategoria nie jest włączona, włącz wszystkie domyślnie
        if (_enabledCategories.Count == 0)
        {
            _enabledCategories.AddRange(_allCategories);
        }

        // Upewnij się, że indeks jest w granicach
        if (_currentCategoryIndex >= _enabledCategories.Count)
        {
            _currentCategoryIndex = 0;
        }

        Console.WriteLine($"DialManager: Włączono {_enabledCategories.Count} kategorii pokrętła");
    }

    /// <summary>
    /// Przełącza pokrętło (włącza/wyłącza)
    /// </summary>
    /// <returns>Komunikat do ogłoszenia</returns>
    public string Toggle()
    {
        _isEnabled = !_isEnabled;
        EnabledChanged?.Invoke(_isEnabled);

        if (_isEnabled)
        {
            // Odśwież kategorie przy włączeniu
            RefreshEnabledCategories();
            return $"TPad, {GetCategoryName(CurrentCategory)}";
        }
        else
        {
            return "Nawigacja obiektowa";
        }
    }

    /// <summary>
    /// Przechodzi do następnej kategorii
    /// </summary>
    /// <returns>Komunikat do ogłoszenia</returns>
    public string NextCategory()
    {
        if (_enabledCategories.Count == 0)
            return "Brak kategorii";

        _currentCategoryIndex = (_currentCategoryIndex + 1) % _enabledCategories.Count;
        var category = CurrentCategory;
        CategoryChanged?.Invoke(category);
        return GetCategoryName(category);
    }

    /// <summary>
    /// Przechodzi do poprzedniej kategorii
    /// </summary>
    /// <returns>Komunikat do ogłoszenia</returns>
    public string PreviousCategory()
    {
        if (_enabledCategories.Count == 0)
            return "Brak kategorii";

        _currentCategoryIndex--;
        if (_currentCategoryIndex < 0)
            _currentCategoryIndex = _enabledCategories.Count - 1;

        var category = CurrentCategory;
        CategoryChanged?.Invoke(category);
        return GetCategoryName(category);
    }

    /// <summary>
    /// Pobiera polską nazwę kategorii
    /// </summary>
    public static string GetCategoryName(DialCategory category)
    {
        return category switch
        {
            DialCategory.Characters => "Znaki",
            DialCategory.Words => "Słowa",
            DialCategory.Buttons => "Przyciski",
            DialCategory.Headings => "Nagłówki",
            DialCategory.Voice => "Głos",
            DialCategory.Speed => "Szybkość",
            DialCategory.Volume => "Głośność",
            DialCategory.Synthesizer => "Syntezator",
            DialCategory.ImportantPlaces => "Ważne miejsca",
            _ => category.ToString()
        };
    }

    /// <summary>
    /// Indeks aktualnego elementu w każdej kategorii
    /// </summary>
    private readonly Dictionary<DialCategory, int> _categoryItemIndex = new();

    /// <summary>
    /// Pobiera lub ustawia indeks elementu dla kategorii
    /// </summary>
    private int GetCategoryIndex(DialCategory category)
    {
        return _categoryItemIndex.TryGetValue(category, out var index) ? index : 0;
    }

    private void SetCategoryIndex(DialCategory category, int index)
    {
        _categoryItemIndex[category] = index;
    }

    /// <summary>
    /// Zmienia element w bieżącej kategorii (NumPad 2/8)
    /// </summary>
    /// <param name="next">True = następny, False = poprzedni</param>
    /// <param name="speechManager">Manager mowy do zmiany ustawień</param>
    /// <returns>Komunikat do ogłoszenia</returns>
    public string? ExecuteItemChange(bool next, SpeechManager? speechManager)
    {
        if (speechManager == null)
            return null;

        switch (CurrentCategory)
        {
            case DialCategory.Speed:
                int currentRate = speechManager.GetRate();
                int newRate = next ? Math.Min(currentRate + 1, 10) : Math.Max(currentRate - 1, -10);
                speechManager.SetRate(newRate);
                // Zapisz do ustawień
                SettingsManager.Instance.Rate = newRate;
                // Konwersja: rate -10=0%, 0=50%, 10=100% (krok 5%)
                int percent = (newRate + 10) * 5;
                return $"Szybkość {percent} procent";

            case DialCategory.Volume:
                int currentVolume = speechManager.GetVolume();
                int newVolume = next ? Math.Min(currentVolume + 10, 100) : Math.Max(currentVolume - 10, 0);
                speechManager.SetVolume(newVolume);
                // Zapisz do ustawień
                SettingsManager.Instance.Volume = newVolume;
                return $"Głośność {newVolume} procent";

            case DialCategory.Voice:
                return ChangeVoice(next, speechManager);

            case DialCategory.Synthesizer:
                return ChangeSynthesizer(next, speechManager);

            case DialCategory.Characters:
                // Nawigacja po znakach - obsługiwane w ScreenReaderEngine
                return null;

            case DialCategory.Words:
                // Nawigacja po słowach - obsługiwane w ScreenReaderEngine
                return null;

            case DialCategory.Buttons:
                // Nawigacja po przyciskach - obsługiwane w ScreenReaderEngine
                return null;

            case DialCategory.Headings:
                // Nawigacja po nagłówkach - obsługiwane w ScreenReaderEngine
                return null;

            case DialCategory.ImportantPlaces:
                // Nawigacja po ważnych miejscach - obsługiwane w ScreenReaderEngine
                return null;

            default:
                return null;
        }
    }

    /// <summary>
    /// Zmienia głos
    /// </summary>
    private string? ChangeVoice(bool next, SpeechManager speechManager)
    {
        var voices = speechManager.GetAvailableVoices();
        if (voices.Count == 0)
            return "Brak głosów";

        int currentIndex = GetCategoryIndex(DialCategory.Voice);

        // Znajdź aktualny głos
        string currentVoice = speechManager.GetCurrentVoice();
        for (int i = 0; i < voices.Count; i++)
        {
            if (voices[i].Contains(currentVoice) || currentVoice.Contains(voices[i]))
            {
                currentIndex = i;
                break;
            }
        }

        // Zmień na następny/poprzedni
        if (next)
        {
            currentIndex = (currentIndex + 1) % voices.Count;
        }
        else
        {
            currentIndex--;
            if (currentIndex < 0) currentIndex = voices.Count - 1;
        }

        SetCategoryIndex(DialCategory.Voice, currentIndex);

        string newVoice = voices[currentIndex];
        speechManager.SelectVoice(newVoice);

        // Zapisz do ustawień
        SettingsManager.Instance.Voice = newVoice;

        // Skróć nazwę do ogłoszenia
        string shortName = newVoice.Split('(')[0].Trim();
        return shortName;
    }

    /// <summary>
    /// Zmienia syntezator (cyklicznie: SAPI5 → OneCore → BestSpeech → SAPI5...)
    /// </summary>
    private string? ChangeSynthesizer(bool next, SpeechManager speechManager)
    {
        // Zbuduj listę dostępnych syntezatorów
        var available = new List<SynthesizerType> { SynthesizerType.SAPI5 };

        // OneCore jest zawsze dostępny na Windows 10+
        available.Add(SynthesizerType.OneCore);

        // BestSpeech tylko gdy bridge + DLLki są obecne
        if (speechManager.IsBestSpeechAvailable())
        {
            available.Add(SynthesizerType.BestSpeech);
        }

        var currentSynth = speechManager.GetCurrentSynthesizer();
        int currentIndex = available.IndexOf(currentSynth);
        if (currentIndex < 0) currentIndex = 0;

        // Cykliczna nawigacja
        if (next)
        {
            currentIndex = (currentIndex + 1) % available.Count;
        }
        else
        {
            currentIndex--;
            if (currentIndex < 0) currentIndex = available.Count - 1;
        }

        var newSynth = available[currentIndex];
        speechManager.SetSynthesizer(newSynth);

        // Zapisz do ustawień
        string synthName = newSynth switch
        {
            SynthesizerType.SAPI5 => "SAPI5",
            SynthesizerType.OneCore => "OneCore",
            SynthesizerType.BestSpeech => "BestSpeech",
            _ => "SAPI5"
        };
        SettingsManager.Instance.Synthesizer = synthName;

        // Zwróć nazwę do ogłoszenia
        return newSynth switch
        {
            SynthesizerType.SAPI5 => "SAPI 5",
            SynthesizerType.OneCore => "OneCore",
            SynthesizerType.BestSpeech => "BestSpeech",
            _ => synthName
        };
    }
}
