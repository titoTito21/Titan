using System.Windows.Automation;
using System.Collections.Concurrent;
using System.Text.RegularExpressions;

namespace ScreenReader.Menu;

/// <summary>
/// Wykrywa i oznajmia nazwy komend z menu gdy użytkownik używa skrótów klawiszowych
/// Podobne do funkcji Window-Eyes
/// </summary>
public class MenuShortcutAnnouncer
{
    // Cache mapowań skrót -> nazwa dla każdego okna (przez window handle)
    private readonly ConcurrentDictionary<IntPtr, Dictionary<string, string>> _menuShortcutCache = new();
    private readonly TimeSpan _cacheExpiration = TimeSpan.FromMinutes(5);
    private readonly Dictionary<IntPtr, DateTime> _cacheTimestamps = new();

    /// <summary>
    /// Próbuje znaleźć i zwrócić nazwę komendy menu dla danego skrótu
    /// </summary>
    /// <param name="window">Okno aplikacji</param>
    /// <param name="shortcut">Skrót klawiszowy np "Ctrl+O", "Alt+F4"</param>
    /// <returns>Nazwa komendy menu lub null jeśli nie znaleziono</returns>
    public string? GetMenuCommandName(AutomationElement? window, string shortcut)
    {
        if (window == null || string.IsNullOrEmpty(shortcut))
            return null;

        try
        {
            IntPtr windowHandle = new IntPtr(window.Current.NativeWindowHandle);

            // Sprawdź cache
            if (_menuShortcutCache.TryGetValue(windowHandle, out var cachedMap))
            {
                // Sprawdź czy cache nie wygasł
                if (_cacheTimestamps.TryGetValue(windowHandle, out var timestamp))
                {
                    if (DateTime.Now - timestamp > _cacheExpiration)
                    {
                        // Cache wygasł, usuń
                        _menuShortcutCache.TryRemove(windowHandle, out _);
                        _cacheTimestamps.Remove(windowHandle);
                    }
                    else if (cachedMap.TryGetValue(shortcut, out var commandName))
                    {
                        return commandName;
                    }
                }
            }

            // Zbuduj nowy cache dla tego okna
            var menuMap = BuildMenuShortcutMap(window);
            if (menuMap != null && menuMap.Count > 0)
            {
                _menuShortcutCache[windowHandle] = menuMap;
                _cacheTimestamps[windowHandle] = DateTime.Now;

                if (menuMap.TryGetValue(shortcut, out var commandName))
                {
                    return commandName;
                }
            }

            return null;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"MenuShortcutAnnouncer Error: {ex.Message}");
            return null;
        }
    }

    /// <summary>
    /// Czyści cache dla danego okna (np. gdy okno zostało zamknięte)
    /// </summary>
    public void ClearCache(IntPtr windowHandle)
    {
        _menuShortcutCache.TryRemove(windowHandle, out _);
        _cacheTimestamps.Remove(windowHandle);
    }

    /// <summary>
    /// Czyści cały cache
    /// </summary>
    public void ClearAllCache()
    {
        _menuShortcutCache.Clear();
        _cacheTimestamps.Clear();
    }

    /// <summary>
    /// Buduje mapę skrótów -> nazw komend dla okna
    /// </summary>
    private Dictionary<string, string>? BuildMenuShortcutMap(AutomationElement window)
    {
        try
        {
            var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

            // Znajdź menu bar
            var menuBar = window.FindFirst(TreeScope.Descendants,
                new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.MenuBar));

            if (menuBar == null)
                return null;

            // Iteruj przez wszystkie top-level menu (Plik, Edycja, etc.)
            var topMenuItems = menuBar.FindAll(TreeScope.Children,
                new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.MenuItem));

            foreach (AutomationElement topMenu in topMenuItems)
            {
                try
                {
                    // Rozwiń menu aby zobaczyć podmenu
                    if (topMenu.TryGetCurrentPattern(ExpandCollapsePattern.Pattern, out object? pattern))
                    {
                        var expandPattern = (ExpandCollapsePattern)pattern;
                        if (expandPattern.Current.ExpandCollapseState == ExpandCollapseState.Collapsed)
                        {
                            expandPattern.Expand();
                            System.Threading.Thread.Sleep(50); // Daj czas na rozwinięcie
                        }
                    }

                    // Rekurencyjnie przetwarzaj podmenu
                    ProcessMenuItems(topMenu, map);

                    // Zwiń menu
                    if (topMenu.TryGetCurrentPattern(ExpandCollapsePattern.Pattern, out object? collapsePattern))
                    {
                        var expandPattern = (ExpandCollapsePattern)collapsePattern;
                        if (expandPattern.Current.ExpandCollapseState == ExpandCollapseState.Expanded)
                        {
                            expandPattern.Collapse();
                        }
                    }
                }
                catch
                {
                    // Ignoruj błędy pojedynczych menu
                }
            }

            Console.WriteLine($"MenuShortcutAnnouncer: Zbudowano mapę {map.Count} skrótów dla okna");
            return map;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"MenuShortcutAnnouncer BuildMap Error: {ex.Message}");
            return null;
        }
    }

    /// <summary>
    /// Rekurencyjnie przetwarza elementy menu
    /// </summary>
    private void ProcessMenuItems(AutomationElement menuItem, Dictionary<string, string> map)
    {
        try
        {
            // Pobierz nazwę elementu menu
            string name = menuItem.Current.Name;
            if (string.IsNullOrEmpty(name))
                return;

            // Pobierz accelerator key (skrót klawiszowy)
            string acceleratorKey = "";
            try
            {
                object accelObj = menuItem.GetCurrentPropertyValue(AutomationElement.AcceleratorKeyProperty);
                if (accelObj != null && accelObj != AutomationElement.NotSupported)
                {
                    acceleratorKey = accelObj.ToString() ?? "";
                }
            }
            catch
            {
                // Niektóre elementy nie mają AcceleratorKey
            }

            // Jeśli element ma skrót, dodaj do mapy
            if (!string.IsNullOrEmpty(acceleratorKey))
            {
                // Normalizuj skrót (usuń spacje, ujednolic format)
                string normalizedShortcut = NormalizeShortcut(acceleratorKey);

                // Wyczyść nazwę (usuń "..." i skrót na końcu)
                string cleanName = CleanMenuName(name);

                if (!string.IsNullOrEmpty(normalizedShortcut) && !string.IsNullOrEmpty(cleanName))
                {
                    if (!map.ContainsKey(normalizedShortcut))
                    {
                        map[normalizedShortcut] = cleanName;
                        Console.WriteLine($"  {normalizedShortcut} -> {cleanName}");
                    }
                }
            }

            // Sprawdź czy element ma podmenu
            var subMenuItems = menuItem.FindAll(TreeScope.Children,
                new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.MenuItem));

            foreach (AutomationElement subMenuItem in subMenuItems)
            {
                ProcessMenuItems(subMenuItem, map);
            }
        }
        catch
        {
            // Ignoruj błędy pojedynczych elementów
        }
    }

    /// <summary>
    /// Normalizuje skrót klawiszowy do standardowego formatu
    /// </summary>
    private string NormalizeShortcut(string shortcut)
    {
        if (string.IsNullOrEmpty(shortcut))
            return "";

        // Usuń spacje
        shortcut = shortcut.Replace(" ", "");

        // Windows UI Automation zwraca różne formaty:
        // - "Ctrl+O"
        // - "Control+O"
        // - "Alt+F4"
        // Ujednolić do Ctrl, Alt, Shift

        shortcut = shortcut.Replace("Control", "Ctrl", StringComparison.OrdinalIgnoreCase);

        return shortcut;
    }

    /// <summary>
    /// Czyści nazwę menu (usuwa "...", tabulatory, skróty na końcu)
    /// </summary>
    private string CleanMenuName(string name)
    {
        if (string.IsNullOrEmpty(name))
            return "";

        // Usuń "..." na końcu
        name = name.Replace("...", "");

        // Usuń skrót klawiszowy w nawiasie na końcu np "Otwórz (Ctrl+O)"
        name = Regex.Replace(name, @"\s*\([^)]*\)\s*$", "");

        // Usuń tabulatory i skrót po tabulatorze np "Otwórz\tCtrl+O"
        int tabIndex = name.IndexOf('\t');
        if (tabIndex >= 0)
        {
            name = name.Substring(0, tabIndex);
        }

        // Usuń "&" używane dla podkreśleń w menu
        name = name.Replace("&", "");

        return name.Trim();
    }

    /// <summary>
    /// Konwertuje skrót z Keys enum na string format
    /// </summary>
    public static string KeysToShortcutString(System.Windows.Forms.Keys keys, bool ctrl, bool alt, bool shift)
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
}
