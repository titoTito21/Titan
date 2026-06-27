using System.Windows.Automation;

namespace ScreenReader.Accessibility;

/// <summary>
/// Uniwersalna reprezentacja obiektu dostępnościowego
/// Port z NVDA NVDAObjects - abstrahuje różne API dostępnościowe
/// </summary>
public class AccessibleObject
{
    /// <summary>
    /// API źródłowe dla tego obiektu
    /// </summary>
    public AccessibilityAPI SourceApi { get; set; }

    /// <summary>
    /// Element UI Automation (jeśli dostępny)
    /// </summary>
    public AutomationElement? UIAElement { get; set; }

    /// <summary>
    /// Uchwyt okna
    /// </summary>
    public IntPtr WindowHandle { get; set; }

    /// <summary>
    /// Identyfikator dziecka (dla MSAA)
    /// </summary>
    public int ChildId { get; set; }

    /// <summary>
    /// Nazwa obiektu
    /// </summary>
    public string Name { get; set; } = "";

    /// <summary>
    /// Opis obiektu
    /// </summary>
    public string Description { get; set; } = "";

    /// <summary>
    /// Wartość obiektu (np. tekst w polu edycji)
    /// </summary>
    public string Value { get; set; } = "";

    /// <summary>
    /// Rola obiektu
    /// </summary>
    public AccessibleRole Role { get; set; }

    /// <summary>
    /// Stany obiektu (flagi)
    /// </summary>
    public AccessibleStates States { get; set; }

    /// <summary>
    /// Pozycja i rozmiar na ekranie
    /// </summary>
    public System.Drawing.Rectangle BoundingRectangle { get; set; }

    /// <summary>
    /// Tekst pomocy
    /// </summary>
    public string HelpText { get; set; } = "";

    /// <summary>
    /// Skrót klawiszowy
    /// </summary>
    public string KeyboardShortcut { get; set; } = "";

    /// <summary>
    /// Pozycja w grupie (np. 3 z 10)
    /// </summary>
    public int PositionInGroup { get; set; }

    /// <summary>
    /// Rozmiar grupy
    /// </summary>
    public int GroupSize { get; set; }

    /// <summary>
    /// Poziom w hierarchii (dla nagłówków, drzew)
    /// </summary>
    public int Level { get; set; }

    /// <summary>
    /// Atrybuty ARIA (dla web)
    /// </summary>
    public Dictionary<string, string> AriaAttributes { get; } = new();

    /// <summary>
    /// ID procesu
    /// </summary>
    public int ProcessId { get; set; }

    /// <summary>
    /// Dodatkowe dane specyficzne dla API
    /// </summary>
    public object? NativeObject { get; set; }

    /// <summary>
    /// Pobiera rodzica
    /// </summary>
    public virtual AccessibleObject? GetParent() => null;

    /// <summary>
    /// Pobiera dzieci
    /// </summary>
    public virtual IEnumerable<AccessibleObject> GetChildren() => Enumerable.Empty<AccessibleObject>();

    /// <summary>
    /// Pobiera następne rodzeństwo
    /// </summary>
    public virtual AccessibleObject? GetNextSibling() => null;

    /// <summary>
    /// Pobiera poprzednie rodzeństwo
    /// </summary>
    public virtual AccessibleObject? GetPreviousSibling() => null;

    /// <summary>
    /// Ustawia fokus na obiekt
    /// </summary>
    public virtual bool SetFocus()
    {
        try
        {
            UIAElement?.SetFocus();
            return true;
        }
        catch
        {
            return false;
        }
    }

    /// <summary>
    /// Wykonuje domyślną akcję
    /// </summary>
    public virtual bool DoDefaultAction()
    {
        try
        {
            if (UIAElement?.TryGetCurrentPattern(InvokePattern.Pattern, out var pattern) == true)
            {
                ((InvokePattern)pattern).Invoke();
                return true;
            }
        }
        catch { }
        return false;
    }

    /// <summary>
    /// Pobiera tekst (dla pól edycji)
    /// </summary>
    public virtual string GetText()
    {
        try
        {
            if (UIAElement?.TryGetCurrentPattern(TextPattern.Pattern, out var pattern) == true)
            {
                return ((TextPattern)pattern).DocumentRange.GetText(-1);
            }
        }
        catch { }
        return Value;
    }

    /// <summary>
    /// Ustawia tekst (dla pól edycji)
    /// </summary>
    public virtual bool SetText(string text)
    {
        try
        {
            if (UIAElement?.TryGetCurrentPattern(ValuePattern.Pattern, out var pattern) == true)
            {
                ((ValuePattern)pattern).SetValue(text);
                return true;
            }
        }
        catch { }
        return false;
    }

    /// <summary>
    /// Pobiera ogłoszenie dla użytkownika
    /// </summary>
    public virtual string GetAnnouncement()
    {
        var parts = new List<string>();

        if (!string.IsNullOrEmpty(Name))
            parts.Add(Name);

        parts.Add(GetRoleText());

        if (!string.IsNullOrEmpty(Value) && Value != Name)
            parts.Add(Value);

        var stateText = GetStateText();
        if (!string.IsNullOrEmpty(stateText))
            parts.Add(stateText);

        if (PositionInGroup > 0 && GroupSize > 0)
            parts.Add($"{PositionInGroup} z {GroupSize}");

        if (Level > 0)
            parts.Add($"poziom {Level}");

        return string.Join(", ", parts);
    }

    /// <summary>
    /// Pobiera tekst roli po polsku
    /// </summary>
    public virtual string GetRoleText()
    {
        return Role switch
        {
            AccessibleRole.None => "",
            AccessibleRole.TitleBar => "pasek tytułu",
            AccessibleRole.MenuBar => "pasek menu",
            AccessibleRole.ScrollBar => "pasek przewijania",
            AccessibleRole.Grip => "uchwyt",
            AccessibleRole.Sound => "dźwięk",
            AccessibleRole.Cursor => "kursor",
            AccessibleRole.Caret => "karetka",
            AccessibleRole.Alert => "alert",
            AccessibleRole.Window => "okno",
            AccessibleRole.Client => "klient",
            AccessibleRole.MenuPopup => "menu podręczne",
            AccessibleRole.MenuItem => "element menu",
            AccessibleRole.Tooltip => "podpowiedź",
            AccessibleRole.Application => "aplikacja",
            AccessibleRole.Document => "dokument",
            AccessibleRole.Pane => "panel",
            AccessibleRole.Chart => "wykres",
            AccessibleRole.Dialog => "dialog",
            AccessibleRole.Border => "obramowanie",
            AccessibleRole.Grouping => "grupa",
            AccessibleRole.Separator => "separator",
            AccessibleRole.ToolBar => "pasek narzędzi",
            AccessibleRole.StatusBar => "pasek stanu",
            AccessibleRole.Table => "tabela",
            AccessibleRole.ColumnHeader => "nagłówek kolumny",
            AccessibleRole.RowHeader => "nagłówek wiersza",
            AccessibleRole.Column => "kolumna",
            AccessibleRole.Row => "wiersz",
            AccessibleRole.Cell => "komórka",
            AccessibleRole.Link => "link",
            AccessibleRole.HelpBalloon => "dymek pomocy",
            AccessibleRole.Character => "postać",
            AccessibleRole.List => "lista",
            AccessibleRole.ListItem => "element listy",
            AccessibleRole.Outline => "kontur",
            AccessibleRole.OutlineItem => "element konturu",
            AccessibleRole.PageTab => "karta",
            AccessibleRole.PropertyPage => "strona właściwości",
            AccessibleRole.Indicator => "wskaźnik",
            AccessibleRole.Graphic => "grafika",
            AccessibleRole.StaticText => "tekst",
            AccessibleRole.Text => "tekst",
            AccessibleRole.PushButton => "przycisk",
            AccessibleRole.CheckButton => "pole wyboru",
            AccessibleRole.RadioButton => "przycisk opcji",
            AccessibleRole.ComboBox => "pole kombi",
            AccessibleRole.DropList => "lista rozwijana",
            AccessibleRole.ProgressBar => "pasek postępu",
            AccessibleRole.Dial => "pokrętło",
            AccessibleRole.HotkeyField => "pole skrótu",
            AccessibleRole.Slider => "suwak",
            AccessibleRole.SpinButton => "pokrętło",
            AccessibleRole.Diagram => "diagram",
            AccessibleRole.Animation => "animacja",
            AccessibleRole.Equation => "równanie",
            AccessibleRole.ButtonDropDown => "przycisk z menu",
            AccessibleRole.ButtonMenu => "przycisk menu",
            AccessibleRole.ButtonDropDownGrid => "przycisk z siatką",
            AccessibleRole.WhiteSpace => "puste miejsce",
            AccessibleRole.PageTabList => "lista kart",
            AccessibleRole.Clock => "zegar",
            AccessibleRole.SplitButton => "przycisk dzielony",
            AccessibleRole.IpAddress => "adres IP",
            AccessibleRole.OutlineButton => "przycisk konturu",
            AccessibleRole.Edit => "pole edycji",
            AccessibleRole.TreeView => "widok drzewa",
            AccessibleRole.TreeViewItem => "element drzewa",
            AccessibleRole.Header => "nagłówek",
            AccessibleRole.HeaderItem => "element nagłówka",
            AccessibleRole.Heading => "nagłówek",
            AccessibleRole.Landmark => "punkt orientacyjny",
            _ => Role.ToString()
        };
    }

    /// <summary>
    /// Pobiera tekst stanów po polsku
    /// </summary>
    public virtual string GetStateText()
    {
        var states = new List<string>();

        if (States.HasFlag(AccessibleStates.Unavailable))
            states.Add("niedostępny");
        if (States.HasFlag(AccessibleStates.Selected))
            states.Add("zaznaczony");
        if (States.HasFlag(AccessibleStates.Focused))
            states.Add("w fokusie");
        if (States.HasFlag(AccessibleStates.Pressed))
            states.Add("wciśnięty");
        if (States.HasFlag(AccessibleStates.Checked))
            states.Add("zaznaczony");
        if (States.HasFlag(AccessibleStates.Mixed))
            states.Add("mieszany");
        if (States.HasFlag(AccessibleStates.Expanded))
            states.Add("rozwinięty");
        if (States.HasFlag(AccessibleStates.Collapsed))
            states.Add("zwinięty");
        if (States.HasFlag(AccessibleStates.Busy))
            states.Add("zajęty");
        if (States.HasFlag(AccessibleStates.ReadOnly))
            states.Add("tylko do odczytu");
        if (States.HasFlag(AccessibleStates.Protected))
            states.Add("chroniony hasłem");
        if (States.HasFlag(AccessibleStates.Linked))
            states.Add("odwiedzony");
        if (States.HasFlag(AccessibleStates.HasPopup))
            states.Add("ma podmenu");
        if (States.HasFlag(AccessibleStates.Required))
            states.Add("wymagany");
        if (States.HasFlag(AccessibleStates.Invalid))
            states.Add("nieprawidłowy");

        return string.Join(", ", states);
    }

    public override string ToString()
    {
        return $"{GetRoleText()}: {Name}";
    }
}

/// <summary>
/// Role obiektów dostępnościowych (połączenie ról z różnych API)
/// </summary>
public enum AccessibleRole
{
    None = 0,
    TitleBar,
    MenuBar,
    ScrollBar,
    Grip,
    Sound,
    Cursor,
    Caret,
    Alert,
    Window,
    Client,
    MenuPopup,
    MenuItem,
    Tooltip,
    Application,
    Document,
    Pane,
    Chart,
    Dialog,
    Border,
    Grouping,
    Separator,
    ToolBar,
    StatusBar,
    Table,
    ColumnHeader,
    RowHeader,
    Column,
    Row,
    Cell,
    Link,
    HelpBalloon,
    Character,
    List,
    ListItem,
    Outline,
    OutlineItem,
    PageTab,
    PropertyPage,
    Indicator,
    Graphic,
    StaticText,
    Text,
    PushButton,
    CheckButton,
    RadioButton,
    ComboBox,
    DropList,
    ProgressBar,
    Dial,
    HotkeyField,
    Slider,
    SpinButton,
    Diagram,
    Animation,
    Equation,
    ButtonDropDown,
    ButtonMenu,
    ButtonDropDownGrid,
    WhiteSpace,
    PageTabList,
    Clock,
    SplitButton,
    IpAddress,
    OutlineButton,
    Edit,
    TreeView,
    TreeViewItem,
    Header,
    HeaderItem,
    Heading,
    Landmark,
    // Dodatkowe role z IAccessible2 i ARIA
    Article,
    Banner,
    Complementary,
    ContentInfo,
    Form,
    Main,
    Navigation,
    Region,
    Search,
    Section,
    Figure,
    Image,
    Math,
    Note,
    Timer,
    Marquee,
    Log,
    Status,
    Toolbar,
    Grid,
    TreeGrid,
    Feed,
    Definition,
    Term,
    Directory,
    ListBox,
    Menu,
    TabPanel,
    ToggleButton,
    Switch
}

/// <summary>
/// Stany obiektów dostępnościowych (flagi)
/// </summary>
[Flags]
public enum AccessibleStates
{
    None = 0,
    Unavailable = 1 << 0,
    Selected = 1 << 1,
    Focused = 1 << 2,
    Pressed = 1 << 3,
    Checked = 1 << 4,
    Mixed = 1 << 5,
    Indeterminate = 1 << 6,
    ReadOnly = 1 << 7,
    HotTracked = 1 << 8,
    Default = 1 << 9,
    Expanded = 1 << 10,
    Collapsed = 1 << 11,
    Busy = 1 << 12,
    Floating = 1 << 13,
    Marqueed = 1 << 14,
    Animated = 1 << 15,
    Invisible = 1 << 16,
    Offscreen = 1 << 17,
    Sizeable = 1 << 18,
    Moveable = 1 << 19,
    SelfVoicing = 1 << 20,
    Focusable = 1 << 21,
    Selectable = 1 << 22,
    Linked = 1 << 23,
    Traversed = 1 << 24,
    Multiselectable = 1 << 25,
    ExtSelectable = 1 << 26,
    AlertLow = 1 << 27,
    AlertMedium = 1 << 28,
    AlertHigh = 1 << 29,
    Protected = 1 << 30,
    HasPopup = 1 << 31,
    // Dodatkowe z IAccessible2
    Valid = 1 << 32,
    Invalid = 1 << 33,
    Required = 1 << 34,
    Visited = 1 << 35,
    Current = 1 << 36,
    HasAutoComplete = 1 << 37,
    Supports = 1 << 38
}
