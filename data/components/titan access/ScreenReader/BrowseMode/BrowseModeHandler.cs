using System.Windows.Automation;
using ScreenReader.VirtualBuffers;

namespace ScreenReader.BrowseMode;

/// <summary>
/// Obsługuje tryb przeglądania (browse mode) dla dokumentów webowych
/// Używa VirtualBuffer dla przeglądarek Chromium, TreeWalker jako fallback
/// </summary>
public class BrowseModeHandler : IDisposable
{
    private AutomationElement? _currentElement;
    private AutomationElement? _rootDocument;
    private bool _passThrough;
    private bool _disposed;

    // Nawigacja po tekście dokumentu (fallback)
    private string _documentText = "";
    private int _charPosition;
    private int _linePosition;
    private string[] _lines = Array.Empty<string>();

    // Virtual Buffer (dla przeglądarek)
    private VirtualBuffer? _virtualBuffer;
    private bool _useVirtualBuffer;

    private static readonly TreeWalker Walker = TreeWalker.ControlViewWalker;

    /// <summary>Event wywoływany gdy należy ogłosić element</summary>
    public event Action<string>? Announce;

    /// <summary>Event wywoływany przy zmianie trybu</summary>
    public event Action<bool>? ModeChanged;

    /// <summary>Czy tryb pass-through (focus mode) jest aktywny</summary>
    public bool PassThrough
    {
        get => _passThrough;
        private set
        {
            if (_passThrough != value)
            {
                _passThrough = value;
                ModeChanged?.Invoke(value);
            }
        }
    }

    /// <summary>Czy browse mode jest aktywny (zawsze true gdy w przeglądarce)</summary>
    public bool IsActive => _rootDocument != null;

    /// <summary>Bieżący nawigowany element</summary>
    public AutomationElement? CurrentElement => _currentElement;

    /// <summary>
    /// Aktywuje browse mode dla dokumentu (synchronicznie)
    /// </summary>
    public void Activate(AutomationElement document)
    {
        _rootDocument = document;
        _currentElement = document;
        _passThrough = false;

        // Sprawdź czy to przeglądarka - użyj Virtual Buffer
        _useVirtualBuffer = IsBrowserDocument(document);

        if (_useVirtualBuffer)
        {
            try
            {
                // Użyj VirtualBuffer dla lepszej wydajności i funkcjonalności
                _virtualBuffer?.Dispose();
                _virtualBuffer = new VirtualBuffer();
                _virtualBuffer.LoadDocument(document);

                // Retry: jeśli bufor ma 0 węzłów, poczekaj i spróbuj ponownie
                // (strona mogła jeszcze nie załadować drzewa dostępności)
                if (_virtualBuffer.NodeCount == 0)
                {
                    Console.WriteLine("VirtualBuffer: 0 węzłów, retry po 500ms...");
                    Thread.Sleep(500);
                    _virtualBuffer.Dispose();
                    _virtualBuffer = new VirtualBuffer();
                    _virtualBuffer.LoadDocument(document);
                }

                // Drugi retry z dłuższym czasem
                if (_virtualBuffer.NodeCount == 0)
                {
                    Console.WriteLine("VirtualBuffer: nadal 0 węzłów, retry po 1000ms...");
                    Thread.Sleep(1000);
                    _virtualBuffer.Dispose();
                    _virtualBuffer = new VirtualBuffer();
                    _virtualBuffer.LoadDocument(document);
                }

                Console.WriteLine($"Virtual Buffer loaded: {_virtualBuffer.Length} chars, {_virtualBuffer.NodeCount} nodes");

                // Zbuduj _lines/_documentText z bufora wirtualnego (dla fallbacku nawigacji)
                PopulateLinesFromVirtualBuffer();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Failed to load Virtual Buffer: {ex.Message}");
                _useVirtualBuffer = false;
                _virtualBuffer?.Dispose();
                _virtualBuffer = null;
            }
        }

        // Fallback lub gdy VirtualBuffer się nie powiódł
        if (!_useVirtualBuffer)
        {
            // Znajdź pierwszy interaktywny element
            var firstChild = Walker.GetFirstChild(document);
            if (firstChild != null)
            {
                _currentElement = firstChild;
            }

            // Zbuduj tekst dokumentu dla nawigacji po liniach i znakach
            BuildDocumentText();
        }

        Announce?.Invoke("Tryb przeglądania");
    }

    /// <summary>
    /// Buduje _lines i _documentText z tekstu VirtualBuffer
    /// </summary>
    private void PopulateLinesFromVirtualBuffer()
    {
        if (_virtualBuffer == null || _virtualBuffer.Length == 0)
            return;

        _documentText = _virtualBuffer.Text;
        _lines = _documentText.Split(new[] { '\n' }, StringSplitOptions.None);
        _charPosition = 0;
        _linePosition = 0;
    }

    /// <summary>
    /// Sprawdza czy dokument pochodzi z przeglądarki
    /// </summary>
    private static bool IsBrowserDocument(AutomationElement document)
    {
        try
        {
            var processId = document.Current.ProcessId;
            using var process = System.Diagnostics.Process.GetProcessById(processId);
            var processName = process.ProcessName.ToLowerInvariant();

            return processName is "chrome" or "msedge" or "firefox" or "brave" or
                   "vivaldi" or "opera" or "chromium" or "waterfox" or "librewolf";
        }
        catch
        {
            return false;
        }
    }

    /// <summary>
    /// Buduje tekstową reprezentację dokumentu dla nawigacji
    /// </summary>
    private void BuildDocumentText()
    {
        var sb = new System.Text.StringBuilder();
        BuildTextFromElement(_rootDocument, sb);
        _documentText = sb.ToString();
        _lines = _documentText.Split(new[] { '\n' }, StringSplitOptions.None);
        _charPosition = 0;
        _linePosition = 0;
    }

    /// <summary>
    /// Rekurencyjnie pobiera tekst z elementów
    /// </summary>
    private void BuildTextFromElement(AutomationElement? element, System.Text.StringBuilder sb)
    {
        if (element == null)
            return;

        try
        {
            var name = element.Current.Name;
            var controlType = element.Current.ControlType;

            // Dodaj tekst elementu
            if (!string.IsNullOrWhiteSpace(name))
            {
                sb.Append(name);

                // Nagłówki i paragrafy kończą się nową linią
                if (controlType == ControlType.Text ||
                    element.Current.LocalizedControlType?.ToLower().Contains("heading") == true ||
                    element.Current.LocalizedControlType?.ToLower().Contains("nagłówek") == true)
                {
                    sb.AppendLine();
                }
                else
                {
                    sb.Append(' ');
                }
            }

            // Przejdź przez dzieci
            var child = Walker.GetFirstChild(element);
            while (child != null)
            {
                BuildTextFromElement(child, sb);
                child = Walker.GetNextSibling(child);
            }
        }
        catch { }
    }

    /// <summary>
    /// Aktywuje browse mode dla dokumentu (asynchronicznie - dla kompatybilności)
    /// </summary>
    public Task ActivateAsync(AutomationElement document)
    {
        Activate(document);
        return Task.CompletedTask;
    }

    /// <summary>
    /// Dezaktywuje browse mode
    /// </summary>
    public void Deactivate()
    {
        _rootDocument = null;
        _currentElement = null;
        _passThrough = false;
        _useVirtualBuffer = false;

        _virtualBuffer?.Dispose();
        _virtualBuffer = null;
    }

    /// <summary>
    /// Przełącza między browse mode a focus mode
    /// </summary>
    public void TogglePassThrough()
    {
        PassThrough = !PassThrough;

        string modeName = PassThrough ? "Tryb formularza" : "Tryb przeglądania";
        Announce?.Invoke(modeName);
    }

    /// <summary>
    /// Ustawia bieżący element (wywoływane przy zmianie fokusu)
    /// </summary>
    public void SetCurrentElement(AutomationElement element)
    {
        _currentElement = element;
    }

    /// <summary>
    /// Obsługuje szybką nawigację jednoliterową
    /// </summary>
    /// <param name="key">Klawisz nawigacji</param>
    /// <param name="shift">Czy Shift jest wciśnięty (nawigacja wstecz)</param>
    /// <returns>True jeśli nawigacja została obsłużona</returns>
    public bool HandleQuickNav(char key, bool shift)
    {
        if (!IsActive || PassThrough)
            return false;

        var type = QuickNavKeys.GetTypeForKey(key);
        if (type == QuickNavType.None)
            return false;

        // Użyj VirtualBuffer gdy dostępny (szybszy i dokładniejszy)
        if (_useVirtualBuffer && _virtualBuffer != null)
        {
            return HandleQuickNavVirtualBuffer(type, shift);
        }

        // Fallback: TreeWalker
        return HandleQuickNavTreeWalker(type, shift);
    }

    /// <summary>
    /// Szybka nawigacja używając VirtualBuffer (szybka, buforowana)
    /// </summary>
    private bool HandleQuickNavVirtualBuffer(QuickNavType type, bool shift)
    {
        VirtualBufferNode? found;

        if (shift)
        {
            found = _virtualBuffer!.FindPreviousByType(type, _virtualBuffer.CaretOffset);
            if (found == null)
            {
                Announce?.Invoke($"Brak poprzedniego elementu typu {QuickNavKeys.GetTypeName(type)}");
                return true;
            }
        }
        else
        {
            found = _virtualBuffer!.FindNextByType(type, _virtualBuffer.CaretOffset);
            if (found == null)
            {
                Announce?.Invoke($"Brak następnego elementu typu {QuickNavKeys.GetTypeName(type)}");
                return true;
            }
        }

        // Przesuń karetkę bufora do znalezionego węzła
        _virtualBuffer!.MoveToNode(found);

        // Ustaw bieżący element UI Automation
        if (found.Element != null)
        {
            _currentElement = found.Element;
            try
            {
                found.Element.SetFocus();
            }
            catch { }
        }

        // Ogłoś znaleziony element
        Announce?.Invoke(found.GetAnnouncement());
        return true;
    }

    /// <summary>
    /// Szybka nawigacja używając TreeWalker (fallback, wolniejsza)
    /// </summary>
    private bool HandleQuickNavTreeWalker(QuickNavType type, bool shift)
    {
        AutomationElement? found;

        if (shift)
        {
            found = FindPreviousByType(type);
            if (found == null)
            {
                Announce?.Invoke($"Brak poprzedniego elementu typu {QuickNavKeys.GetTypeName(type)}");
                return true;
            }
        }
        else
        {
            found = FindNextByType(type);
            if (found == null)
            {
                Announce?.Invoke($"Brak następnego elementu typu {QuickNavKeys.GetTypeName(type)}");
                return true;
            }
        }

        _currentElement = found;
        try
        {
            found.SetFocus();
        }
        catch { }

        AnnounceElement(found, type);
        return true;
    }

    /// <summary>
    /// Znajduje następny element danego typu (TreeWalker fallback)
    /// </summary>
    private AutomationElement? FindNextByType(QuickNavType type)
    {
        if (_currentElement == null)
            return null;

        var current = _currentElement;
        var visited = new HashSet<int>();

        while (true)
        {
            current = GetNextElement(current);
            if (current == null)
                break;

            // Zabezpieczenie przed nieskończoną pętlą
            int hash = current.GetHashCode();
            if (visited.Contains(hash))
                break;
            visited.Add(hash);

            if (visited.Count > 5000)
                break;

            if (MatchesType(current, type))
                return current;
        }

        return null;
    }

    /// <summary>
    /// Znajduje poprzedni element danego typu (TreeWalker fallback)
    /// </summary>
    private AutomationElement? FindPreviousByType(QuickNavType type)
    {
        if (_currentElement == null)
            return null;

        var current = _currentElement;
        var visited = new HashSet<int>();

        while (true)
        {
            current = GetPreviousElement(current);
            if (current == null)
                break;

            int hash = current.GetHashCode();
            if (visited.Contains(hash))
                break;
            visited.Add(hash);

            if (visited.Count > 5000)
                break;

            if (MatchesType(current, type))
                return current;
        }

        return null;
    }

    /// <summary>
    /// Pobiera następny element w kolejności dokumentu (depth-first)
    /// </summary>
    private AutomationElement? GetNextElement(AutomationElement element)
    {
        try
        {
            // Najpierw sprawdź dzieci
            var child = Walker.GetFirstChild(element);
            if (child != null)
                return child;

            // Następnie rodzeństwo
            var sibling = Walker.GetNextSibling(element);
            if (sibling != null)
                return sibling;

            // Wróć do rodzica i szukaj jego rodzeństwa
            var parent = Walker.GetParent(element);
            while (parent != null)
            {
                if (_rootDocument != null && Automation.Compare(parent, _rootDocument))
                    return null; // Dotarliśmy do korzenia

                sibling = Walker.GetNextSibling(parent);
                if (sibling != null)
                    return sibling;

                parent = Walker.GetParent(parent);
            }
        }
        catch { }

        return null;
    }

    /// <summary>
    /// Pobiera poprzedni element w kolejności dokumentu
    /// </summary>
    private AutomationElement? GetPreviousElement(AutomationElement element)
    {
        try
        {
            // Sprawdź poprzednie rodzeństwo
            var sibling = Walker.GetPreviousSibling(element);
            if (sibling != null)
            {
                // Idź do ostatniego potomka tego rodzeństwa
                return GetLastDescendant(sibling) ?? sibling;
            }

            // Wróć do rodzica
            var parent = Walker.GetParent(element);
            if (parent != null && _rootDocument != null && !Automation.Compare(parent, _rootDocument))
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
        try
        {
            var last = Walker.GetLastChild(element);
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
    /// Sprawdza czy element pasuje do typu szybkiej nawigacji
    /// </summary>
    private static bool MatchesType(AutomationElement element, QuickNavType type)
    {
        try
        {
            var controlType = element.Current.ControlType;
            var className = element.Current.ClassName ?? "";
            var ariaRole = GetAriaRole(element);

            return type switch
            {
                QuickNavType.Heading or QuickNavType.Heading1 or QuickNavType.Heading2 or
                QuickNavType.Heading3 or QuickNavType.Heading4 or QuickNavType.Heading5 or
                QuickNavType.Heading6 => IsHeading(element, type),

                QuickNavType.Link or QuickNavType.UnvisitedLink or QuickNavType.VisitedLink =>
                    controlType == ControlType.Hyperlink || ariaRole == "link",

                QuickNavType.Button =>
                    controlType == ControlType.Button || ariaRole == "button",

                QuickNavType.EditField =>
                    controlType == ControlType.Edit || controlType == ControlType.Document ||
                    ariaRole == "textbox" || ariaRole == "searchbox",

                QuickNavType.ComboBox =>
                    controlType == ControlType.ComboBox || ariaRole == "combobox" || ariaRole == "listbox",

                QuickNavType.Checkbox =>
                    controlType == ControlType.CheckBox || ariaRole == "checkbox",

                QuickNavType.RadioButton =>
                    controlType == ControlType.RadioButton || ariaRole == "radio",

                QuickNavType.List =>
                    controlType == ControlType.List || ariaRole == "list",

                QuickNavType.ListItem =>
                    controlType == ControlType.ListItem || ariaRole == "listitem",

                QuickNavType.Table =>
                    controlType == ControlType.Table || controlType == ControlType.DataGrid ||
                    ariaRole == "table" || ariaRole == "grid",

                QuickNavType.Graphic =>
                    controlType == ControlType.Image || ariaRole == "img" || ariaRole == "image",

                QuickNavType.Landmark =>
                    ariaRole == "navigation" || ariaRole == "main" || ariaRole == "banner" ||
                    ariaRole == "contentinfo" || ariaRole == "complementary" || ariaRole == "search" ||
                    ariaRole == "region" || ariaRole == "form",

                QuickNavType.FormField =>
                    controlType == ControlType.Edit || controlType == ControlType.ComboBox ||
                    controlType == ControlType.CheckBox || controlType == ControlType.RadioButton ||
                    controlType == ControlType.Button,

                QuickNavType.BlockQuote =>
                    ariaRole == "blockquote",

                QuickNavType.Separator =>
                    controlType == ControlType.Separator || ariaRole == "separator",

                QuickNavType.Paragraph =>
                    ariaRole == "paragraph" || (controlType == ControlType.Text && !string.IsNullOrEmpty(element.Current.Name)),

                QuickNavType.Frame =>
                    ariaRole == "document" || className.Contains("frame", StringComparison.OrdinalIgnoreCase),

                _ => false
            };
        }
        catch
        {
            return false;
        }
    }

    /// <summary>
    /// Sprawdza czy element to nagłówek określonego poziomu
    /// </summary>
    private static bool IsHeading(AutomationElement element, QuickNavType type)
    {
        try
        {
            var ariaRole = GetAriaRole(element);
            var ariaLevel = GetAriaLevel(element);
            var controlType = element.Current.ControlType;

            // Sprawdź po roli ARIA
            if (ariaRole == "heading")
            {
                if (type == QuickNavType.Heading)
                    return true;

                int expectedLevel = type switch
                {
                    QuickNavType.Heading1 => 1,
                    QuickNavType.Heading2 => 2,
                    QuickNavType.Heading3 => 3,
                    QuickNavType.Heading4 => 4,
                    QuickNavType.Heading5 => 5,
                    QuickNavType.Heading6 => 6,
                    _ => 0
                };

                return expectedLevel == 0 || ariaLevel == expectedLevel;
            }

            // Sprawdź po ControlType (dla niektórych przeglądarek)
            if (controlType.ProgrammaticName.Contains("Heading", StringComparison.OrdinalIgnoreCase))
            {
                return type == QuickNavType.Heading || ariaLevel > 0;
            }

            return false;
        }
        catch
        {
            return false;
        }
    }

    /// <summary>
    /// Pobiera rolę ARIA z elementu
    /// </summary>
    private static string GetAriaRole(AutomationElement element)
    {
        try
        {
            // Sprawdź LocalizedControlType dla przeglądarek (najbardziej wiarygodne źródło)
            var localizedType = element.Current.LocalizedControlType?.ToLowerInvariant() ?? "";

            if (localizedType.Contains("heading") || localizedType.Contains("nagłówek"))
                return "heading";
            if (localizedType.Contains("link") || localizedType.Contains("łącze"))
                return "link";
            if (localizedType.Contains("button") || localizedType.Contains("przycisk"))
                return "button";
            if (localizedType.Contains("edit") || localizedType.Contains("pole edycji") ||
                localizedType.Contains("text") || localizedType.Contains("tekstowe"))
                return "textbox";
            if (localizedType.Contains("combo") || localizedType.Contains("kombi"))
                return "combobox";
            if (localizedType.Contains("check") || localizedType.Contains("wyboru"))
                return "checkbox";
            if (localizedType.Contains("radio") || localizedType.Contains("opcji"))
                return "radio";
            if (localizedType.Contains("list item") || localizedType.Contains("element listy"))
                return "listitem";
            if (localizedType.Contains("list") || localizedType.Contains("lista"))
                return "list";
            if (localizedType.Contains("table") || localizedType.Contains("tabela"))
                return "table";
            if (localizedType.Contains("image") || localizedType.Contains("obraz") || localizedType.Contains("grafika"))
                return "img";
            if (localizedType.Contains("separator"))
                return "separator";
            if (localizedType.Contains("navigation") || localizedType.Contains("nawigacja"))
                return "navigation";
            if (localizedType.Contains("main") || localizedType.Contains("główna"))
                return "main";
            if (localizedType.Contains("banner"))
                return "banner";
            if (localizedType.Contains("search") || localizedType.Contains("szukaj") || localizedType.Contains("wyszukiwanie"))
                return "search";
            if (localizedType.Contains("region"))
                return "region";
            if (localizedType.Contains("form") || localizedType.Contains("formularz"))
                return "form";

            // Sprawdź ItemStatus który czasem zawiera rolę ARIA
            var itemStatus = element.Current.ItemStatus ?? "";
            if (!string.IsNullOrEmpty(itemStatus))
            {
                return itemStatus.ToLowerInvariant();
            }

            // Sprawdź ClassName dla przeglądarek Chromium
            var className = element.Current.ClassName ?? "";
            if (className.Contains("heading", StringComparison.OrdinalIgnoreCase))
                return "heading";
        }
        catch { }

        return "";
    }

    /// <summary>
    /// Pobiera poziom ARIA z elementu
    /// </summary>
    private static int GetAriaLevel(AutomationElement element)
    {
        try
        {
            // Próbuj pobrać poziom z różnych źródeł
            var name = element.Current.Name ?? "";
            var localizedType = element.Current.LocalizedControlType ?? "";

            // Sprawdź czy w nazwie typu jest poziom (np. "heading level 2")
            for (int i = 1; i <= 6; i++)
            {
                if (localizedType.Contains($"{i}") || localizedType.Contains($"level {i}"))
                    return i;
            }

            // Sprawdź AutomationId
            var automationId = element.Current.AutomationId ?? "";
            if (automationId.StartsWith("H") && automationId.Length == 2 &&
                char.IsDigit(automationId[1]))
            {
                return automationId[1] - '0';
            }
        }
        catch { }

        return 0;
    }

    /// <summary>
    /// Ogłasza element (TreeWalker path)
    /// </summary>
    private void AnnounceElement(AutomationElement element, QuickNavType foundType)
    {
        try
        {
            var name = element.Current.Name ?? "";
            var typeName = QuickNavKeys.GetTypeName(foundType);

            // Dla nagłówków dodaj poziom
            if (QuickNavKeys.IsHeading(foundType))
            {
                int level = GetAriaLevel(element);
                if (level > 0)
                {
                    typeName = $"nagłówek poziom {level}";
                }
            }

            string announcement = string.IsNullOrEmpty(name)
                ? typeName
                : $"{name}, {typeName}";

            Announce?.Invoke(announcement);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"BrowseModeHandler: Błąd ogłaszania: {ex.Message}");
        }
    }

    /// <summary>
    /// Obsługuje nawigację strzałkami w browse mode
    /// Góra/Dół = poprzednia/następna linia
    /// Lewo/Prawo = poprzedni/następny znak
    /// </summary>
    public bool HandleArrowNavigation(int vkCode, bool ctrl)
    {
        if (!IsActive || PassThrough)
            return false;

        const int VK_LEFT = 0x25;
        const int VK_UP = 0x26;
        const int VK_RIGHT = 0x27;
        const int VK_DOWN = 0x28;

        // Użyj VirtualBuffer gdy dostępny
        if (_useVirtualBuffer && _virtualBuffer != null)
        {
            return HandleArrowVirtualBuffer(vkCode);
        }

        // Fallback: nawigacja po _lines
        switch (vkCode)
        {
            case VK_UP:
                return MoveToPreviousLine();
            case VK_DOWN:
                return MoveToNextLine();
            case VK_LEFT:
                return MoveToPreviousChar();
            case VK_RIGHT:
                return MoveToNextChar();
        }

        return false;
    }

    /// <summary>
    /// Nawigacja strzałkami używając VirtualBuffer
    /// </summary>
    private bool HandleArrowVirtualBuffer(int vkCode)
    {
        const int VK_LEFT = 0x25;
        const int VK_UP = 0x26;
        const int VK_RIGHT = 0x27;
        const int VK_DOWN = 0x28;

        string result;

        switch (vkCode)
        {
            case VK_UP:
                result = _virtualBuffer!.MoveToPreviousLine();
                break;
            case VK_DOWN:
                result = _virtualBuffer!.MoveToNextLine();
                break;
            case VK_LEFT:
                result = _virtualBuffer!.MoveToPreviousCharacter();
                break;
            case VK_RIGHT:
                result = _virtualBuffer!.MoveToNextCharacter();
                break;
            default:
                return false;
        }

        if (!string.IsNullOrEmpty(result))
        {
            Announce?.Invoke(result);

            // Zaktualizuj _currentElement na węzeł pod karetką
            var node = _virtualBuffer!.GetNodeAtOffset(_virtualBuffer.CaretOffset);
            if (node?.Element != null)
            {
                _currentElement = node.Element;
            }
        }

        return true;
    }

    /// <summary>
    /// Przechodzi do poprzedniej linii i ją odczytuje (fallback)
    /// </summary>
    private bool MoveToPreviousLine()
    {
        if (_lines.Length == 0)
            return true;

        if (_linePosition > 0)
        {
            _linePosition--;
            _charPosition = 0;
            ReadCurrentLine();
        }
        else
        {
            Announce?.Invoke("Początek dokumentu");
        }
        return true;
    }

    /// <summary>
    /// Przechodzi do następnej linii i ją odczytuje (fallback)
    /// </summary>
    private bool MoveToNextLine()
    {
        if (_lines.Length == 0)
            return true;

        if (_linePosition < _lines.Length - 1)
        {
            _linePosition++;
            _charPosition = 0;
            ReadCurrentLine();
        }
        else
        {
            Announce?.Invoke("Koniec dokumentu");
        }
        return true;
    }

    /// <summary>
    /// Przechodzi do poprzedniego znaku i go odczytuje (fallback)
    /// </summary>
    private bool MoveToPreviousChar()
    {
        if (_lines.Length == 0)
            return true;

        string currentLine = _lines[_linePosition];

        if (_charPosition > 0)
        {
            _charPosition--;
            ReadCurrentChar();
        }
        else if (_linePosition > 0)
        {
            // Przejdź do końca poprzedniej linii
            _linePosition--;
            currentLine = _lines[_linePosition];
            _charPosition = Math.Max(0, currentLine.Length - 1);
            ReadCurrentChar();
        }
        else
        {
            Announce?.Invoke("Początek dokumentu");
        }
        return true;
    }

    /// <summary>
    /// Przechodzi do następnego znaku i go odczytuje (fallback)
    /// </summary>
    private bool MoveToNextChar()
    {
        if (_lines.Length == 0)
            return true;

        string currentLine = _lines[_linePosition];

        if (_charPosition < currentLine.Length - 1)
        {
            _charPosition++;
            ReadCurrentChar();
        }
        else if (_linePosition < _lines.Length - 1)
        {
            // Przejdź do początku następnej linii
            _linePosition++;
            _charPosition = 0;
            ReadCurrentChar();
        }
        else
        {
            Announce?.Invoke("Koniec dokumentu");
        }
        return true;
    }

    /// <summary>
    /// Odczytuje bieżącą linię
    /// </summary>
    private void ReadCurrentLine()
    {
        if (_linePosition >= 0 && _linePosition < _lines.Length)
        {
            string line = _lines[_linePosition];
            if (string.IsNullOrWhiteSpace(line))
            {
                Announce?.Invoke("Pusta linia");
            }
            else
            {
                Announce?.Invoke(line);
            }
        }
    }

    /// <summary>
    /// Odczytuje bieżący znak
    /// </summary>
    private void ReadCurrentChar()
    {
        if (_linePosition >= 0 && _linePosition < _lines.Length)
        {
            string line = _lines[_linePosition];
            if (_charPosition >= 0 && _charPosition < line.Length)
            {
                char c = line[_charPosition];
                string charName = GetCharacterName(c);
                Announce?.Invoke(charName);
            }
            else if (line.Length == 0)
            {
                Announce?.Invoke("Pusta linia");
            }
        }
    }

    /// <summary>
    /// Zwraca nazwę znaku do ogłoszenia
    /// </summary>
    private static string GetCharacterName(char c)
    {
        return c switch
        {
            ' ' => "spacja",
            '\t' => "tabulator",
            '\r' => "powrót karetki",
            '\n' => "nowa linia",
            '.' => "kropka",
            ',' => "przecinek",
            ';' => "średnik",
            ':' => "dwukropek",
            '!' => "wykrzyknik",
            '?' => "pytajnik",
            '-' => "minus",
            '_' => "podkreślenie",
            '=' => "równa się",
            '+' => "plus",
            '*' => "gwiazdka",
            '/' => "ukośnik",
            '\\' => "odwrotny ukośnik",
            '@' => "małpa",
            '#' => "hash",
            '$' => "dolar",
            '%' => "procent",
            '^' => "daszek",
            '&' => "ampersand",
            '(' => "nawias otwierający",
            ')' => "nawias zamykający",
            '[' => "nawias kwadratowy otwierający",
            ']' => "nawias kwadratowy zamykający",
            '{' => "nawias klamrowy otwierający",
            '}' => "nawias klamrowy zamykający",
            '<' => "mniejszy niż",
            '>' => "większy niż",
            '\'' => "apostrof",
            '"' => "cudzysłów",
            '`' => "grawis",
            '~' => "tylda",
            '|' => "kreska pionowa",
            >= 'A' and <= 'Z' => $"duże {c}",
            _ => c.ToString()
        };
    }

    /// <summary>
    /// Aktywuje bieżący element (Enter/Space/NumPad /)
    /// </summary>
    public bool ActivateCurrentElement()
    {
        if (_currentElement == null)
            return false;

        try
        {
            // Spróbuj kliknąć
            if (_currentElement.TryGetCurrentPattern(InvokePattern.Pattern, out var invokePattern))
            {
                ((InvokePattern)invokePattern).Invoke();
                return true;
            }

            // Dla pól edycyjnych ustaw fokus i włącz tryb formularza
            var controlType = _currentElement.Current.ControlType;
            if (controlType == ControlType.Edit || controlType == ControlType.ComboBox)
            {
                PassThrough = true;
                _currentElement.SetFocus();
                Announce?.Invoke("Tryb formularza");
                return true;
            }

            // Spróbuj ustawić fokus
            _currentElement.SetFocus();
            return true;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"BrowseModeHandler: Błąd aktywacji: {ex.Message}");
        }

        return false;
    }

    /// <summary>
    /// Wirtualny bufor (dla dostępu zewnętrznego)
    /// </summary>
    public VirtualBuffer? Buffer => _virtualBuffer;

    /// <summary>
    /// Przełącza wirtualny kursor (TCE) - dla kompatybilności
    /// </summary>
    public string ToggleVirtualCursor()
    {
        // Przełączamy pass-through zamiast wirtualnego kursora
        TogglePassThrough();
        return PassThrough ? "Tryb formularza" : "Tryb przeglądania";
    }

    public void Dispose()
    {
        if (_disposed)
            return;

        _virtualBuffer?.Dispose();
        _virtualBuffer = null;
        _rootDocument = null;
        _currentElement = null;
        _disposed = true;
    }
}
