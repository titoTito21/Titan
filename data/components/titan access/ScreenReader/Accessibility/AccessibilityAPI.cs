namespace ScreenReader.Accessibility;

/// <summary>
/// Typy API dostępnościowych wspieranych przez czytnik ekranu
/// Port z NVDA - różne technologie dostępnościowe
/// </summary>
[Flags]
public enum AccessibilityAPI
{
    None = 0,

    /// <summary>
    /// Microsoft UI Automation - nowoczesne API Windows
    /// Używane przez: UWP, WPF, nowoczesne aplikacje Win32
    /// </summary>
    UIAutomation = 1,

    /// <summary>
    /// Microsoft Active Accessibility - starsze API
    /// Używane przez: starsze aplikacje Win32
    /// </summary>
    MSAA = 2,

    /// <summary>
    /// IAccessible2 - rozszerzenie MSAA
    /// Używane przez: Firefox, LibreOffice, aplikacje GTK+
    /// </summary>
    IAccessible2 = 4,

    /// <summary>
    /// Java Access Bridge - dla aplikacji Java
    /// Używane przez: Eclipse, IntelliJ IDEA, aplikacje Swing/JavaFX
    /// </summary>
    JavaAccessBridge = 8,

    /// <summary>
    /// Wszystkie dostępne API
    /// </summary>
    All = UIAutomation | MSAA | IAccessible2 | JavaAccessBridge
}

/// <summary>
/// Extension methods dla AccessibilityAPI
/// </summary>
public static class AccessibilityAPIExtensions
{
    /// <summary>
    /// Zwraca polską nazwę API
    /// </summary>
    public static string GetPolishName(this AccessibilityAPI api) => api switch
    {
        AccessibilityAPI.UIAutomation => "UI Automation",
        AccessibilityAPI.MSAA => "MSAA (Active Accessibility)",
        AccessibilityAPI.IAccessible2 => "IAccessible2",
        AccessibilityAPI.JavaAccessBridge => "Java Access Bridge",
        AccessibilityAPI.All => "Wszystkie",
        AccessibilityAPI.None => "Brak",
        _ => "Nieznane"
    };

    /// <summary>
    /// Zwraca krótką nazwę API
    /// </summary>
    public static string GetShortName(this AccessibilityAPI api) => api switch
    {
        AccessibilityAPI.UIAutomation => "UIA",
        AccessibilityAPI.MSAA => "MSAA",
        AccessibilityAPI.IAccessible2 => "IA2",
        AccessibilityAPI.JavaAccessBridge => "JAB",
        _ => "?"
    };

    /// <summary>
    /// Sprawdza czy API jest włączone
    /// </summary>
    public static bool IsEnabled(this AccessibilityAPI enabledApis, AccessibilityAPI api)
    {
        return (enabledApis & api) == api;
    }
}
