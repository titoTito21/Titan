using System.Windows.Automation;
using ScreenReader.Settings;
using ScreenReader.Localization;

namespace ScreenReader.Hints;

/// <summary>
/// Zarządza podpowiedziami dla kontrolek.
/// Podpowiedzi są odczytywane 2 sekundy po zatrzymaniu się na kontrolce.
/// </summary>
public class HintManager : IDisposable
{
    private readonly SpeechManager _speechManager;
    private readonly SettingsManager _settings;
    private System.Threading.Timer? _hintTimer;
    private AutomationElement? _currentElement;
    private ControlType? _currentControlType;
    private bool _disposed;
    private const int HINT_DELAY_MS = 2000; // 2 sekundy

    // Słownik kluczy lokalizacji podpowiedzi dla różnych typów kontrolek.
    // Wartości to klucze do locale/*.json, rozwijane przez L.T() w czasie odczytu.
    private static readonly Dictionary<string, string> ControlHintKeys = new()
    {
        // Podstawowe kontrolki
        { "Button", "hint.button" },
        { "CheckBox", "hint.checkBox" },
        { "RadioButton", "hint.radioButton" },
        { "Edit", "hint.edit" },
        { "Document", "hint.edit" },
        { "Text", "hint.text" },

        // Listy i drzewa
        { "List", "hint.list" },
        { "ListItem", "hint.listItem" },
        { "Tree", "hint.tree" },
        { "TreeItem", "hint.treeItem" },

        // Combo i menu
        { "ComboBox", "hint.comboBox" },
        { "Menu", "hint.menu" },
        { "MenuItem", "hint.menuItem" },
        { "MenuBar", "hint.menuBar" },

        // Zakładki
        { "Tab", "hint.tab" },
        { "TabItem", "hint.tabItem" },

        // Paski narzędzi i statusu
        { "ToolBar", "hint.toolBar" },
        { "StatusBar", "hint.statusBar" },

        // Suwaki i spinboxy
        { "Slider", "hint.slider" },
        { "Spinner", "hint.spinner" },

        // Linki i obrazy
        { "Hyperlink", "hint.hyperlink" },
        { "Image", "hint.image" },

        // Tabele
        { "Table", "hint.table" },
        { "DataGrid", "hint.dataGrid" },

        // Okna i panele
        { "Window", "hint.window" },
        { "Pane", "hint.pane" },
        { "Group", "hint.group" },

        // Paski przewijania
        { "ScrollBar", "hint.scrollBar" },

        // Nagłówki
        { "Header", "hint.header" },
        { "HeaderItem", "hint.headerItem" },

        // Postęp
        { "ProgressBar", "hint.progressBar" },

        // Separatory
        { "Separator", "hint.separator" },

        // Miniaturki
        { "Thumb", "hint.thumb" },

        // Kalendarze
        { "Calendar", "hint.calendar" },

        // Niestandardowe
        { "Custom", "hint.custom" },
    };

    // Klucze lokalizacji podpowiedzi specyficznych dla TCE/Titan
    private static readonly Dictionary<string, string> TCEHintKeys = new()
    {
        { "AppList", "hint.tce.appList" },
        { "GameList", "hint.tce.appList" },
        { "StatusBar", "hint.tce.statusBar" },
    };

    public HintManager(SpeechManager speechManager)
    {
        _speechManager = speechManager;
        _settings = SettingsManager.Instance;
    }

    /// <summary>
    /// Ustawia bieżący element i resetuje timer podpowiedzi
    /// </summary>
    public void SetCurrentElement(AutomationElement? element, bool isTCEProcess = false)
    {
        // Zatrzymaj poprzedni timer
        _hintTimer?.Dispose();
        _hintTimer = null;

        _currentElement = element;

        if (element == null || !_settings.SpeakHints)
            return;

        try
        {
            _currentControlType = element.Current.ControlType;

            // Uruchom timer podpowiedzi
            _hintTimer = new System.Threading.Timer(
                OnHintTimerElapsed,
                isTCEProcess,
                HINT_DELAY_MS,
                Timeout.Infinite);
        }
        catch (ElementNotAvailableException)
        {
            // Element już niedostępny
        }
    }

    /// <summary>
    /// Anuluje oczekującą podpowiedź
    /// </summary>
    public void CancelHint()
    {
        _hintTimer?.Dispose();
        _hintTimer = null;
    }

    /// <summary>
    /// Callback timera - odczytuje podpowiedź
    /// </summary>
    private void OnHintTimerElapsed(object? state)
    {
        if (_currentElement == null || !_settings.SpeakHints)
            return;

        bool isTCE = state is bool b && b;

        try
        {
            string? hint = GetHintForElement(_currentElement, isTCE);

            if (!string.IsNullOrEmpty(hint))
            {
                // Odczytaj podpowiedź (nie przerywaj bieżącej mowy)
                _speechManager.Speak(hint, interrupt: false);
            }
        }
        catch (ElementNotAvailableException)
        {
            // Element już niedostępny
        }
        catch (Exception ex)
        {
            Console.WriteLine($"HintManager: Błąd odczytu podpowiedzi - {ex.Message}");
        }
    }

    /// <summary>
    /// Pobiera podpowiedź dla danego elementu
    /// </summary>
    private string? GetHintForElement(AutomationElement element, bool isTCE)
    {
        try
        {
            var controlType = element.Current.ControlType;
            string typeName = controlType.ProgrammaticName.Replace("ControlType.", "");

            // Sprawdź specjalne podpowiedzi TCE
            if (isTCE)
            {
                string? name = element.Current.Name?.ToLowerInvariant() ?? "";
                string? className = element.Current.ClassName?.ToLowerInvariant() ?? "";

                // Lista aplikacji lub gier w TCE
                if ((name.Contains("aplikacj") || name.Contains("gier") || name.Contains("gry")) &&
                    (typeName == "List" || typeName == "ListItem"))
                {
                    return ResolveHintKey(TCEHintKeys, "AppList");
                }

                // Pasek stanu w TCE
                if (typeName == "StatusBar" || name.Contains("pasek stanu") || className.Contains("statusbar"))
                {
                    return ResolveHintKey(TCEHintKeys, "StatusBar");
                }
            }

            // Standardowe podpowiedzi
            return ResolveHintKey(ControlHintKeys, typeName);
        }
        catch
        {
            return null;
        }
    }

    /// <summary>
    /// Pobiera podpowiedź dla danego typu kontrolki (bez elementu)
    /// </summary>
    public static string? GetHintForControlType(string controlTypeName)
    {
        return ResolveHintKey(ControlHintKeys, controlTypeName);
    }

    /// <summary>
    /// Zamienia nazwę typu kontrolki na przetłumaczoną podpowiedź.
    /// Zwraca null, gdy dla danego typu nie ma podpowiedzi.
    /// </summary>
    private static string? ResolveHintKey(Dictionary<string, string> map, string typeName)
    {
        return map.TryGetValue(typeName, out var key) ? L.T(key) : null;
    }

    public void Dispose()
    {
        if (_disposed)
            return;

        _hintTimer?.Dispose();
        _hintTimer = null;
        _disposed = true;
    }
}
