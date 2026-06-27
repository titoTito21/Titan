namespace ScreenReader.BrowseMode;

/// <summary>
/// Typy elementów dla szybkiej nawigacji jednoliterowej
/// Port z NVDA browseMode.py - typy elementów
/// </summary>
public enum QuickNavType
{
    None = 0,

    // Nagłówki (H, 1-6)
    Heading,
    Heading1,
    Heading2,
    Heading3,
    Heading4,
    Heading5,
    Heading6,

    // Linki (K, L, U, V)
    Link,
    UnvisitedLink,
    VisitedLink,

    // Formularze (F, E, B, C, R, X)
    FormField,
    EditField,
    Button,
    Checkbox,
    RadioButton,
    ComboBox,

    // Listy (I, L)
    List,
    ListItem,

    // Tabele (T)
    Table,
    TableCell,

    // Grafika (G)
    Graphic,

    // Strukturalne (D, N, Q)
    Landmark,
    Frame,
    BlockQuote,

    // Separator/linia pozioma (S)
    Separator,

    // Tekst
    Text,
    Paragraph,

    // Inne
    Document,
    Group,
    ToolBar,
    Menu,
    MenuItem,
    Tab,
    TabItem,
    TreeItem,
    Annotation,

    // Nowe typy dla ARIA/UIA
    TableRow,
    Article,
    TabPanel,
    Tree,
    Alert,
    Dialog,
    ProgressBar,
    Slider
}

/// <summary>
/// Mapowanie klawiszy na typy elementów
/// </summary>
public static class QuickNavKeys
{
    private static readonly Dictionary<char, QuickNavType> _keyToType = new()
    {
        // Nagłówki
        { 'h', QuickNavType.Heading },
        { '1', QuickNavType.Heading1 },
        { '2', QuickNavType.Heading2 },
        { '3', QuickNavType.Heading3 },
        { '4', QuickNavType.Heading4 },
        { '5', QuickNavType.Heading5 },
        { '6', QuickNavType.Heading6 },

        // Linki
        { 'k', QuickNavType.Link },
        { 'l', QuickNavType.List },  // NVDA: l = lista, k = link
        { 'u', QuickNavType.UnvisitedLink },
        { 'v', QuickNavType.VisitedLink },

        // Formularze
        { 'f', QuickNavType.FormField },
        { 'e', QuickNavType.EditField },
        { 'b', QuickNavType.Button },
        { 'c', QuickNavType.ComboBox },
        { 'r', QuickNavType.RadioButton },
        { 'x', QuickNavType.Checkbox },

        // Listy
        { 'i', QuickNavType.ListItem },

        // Tabele
        { 't', QuickNavType.Table },

        // Grafika
        { 'g', QuickNavType.Graphic },

        // Strukturalne
        { 'd', QuickNavType.Landmark },
        { 'n', QuickNavType.Landmark },  // ARIA landmark/navigation
        { 'q', QuickNavType.BlockQuote },
        { 'm', QuickNavType.Frame },

        // Separator
        { 's', QuickNavType.Separator },

        // Paragraf
        { 'p', QuickNavType.Paragraph },

        // Adnotacje
        { 'a', QuickNavType.Annotation }
    };

    private static readonly Dictionary<QuickNavType, string> _typeNames = new()
    {
        { QuickNavType.Heading, "nagłówek" },
        { QuickNavType.Heading1, "nagłówek 1" },
        { QuickNavType.Heading2, "nagłówek 2" },
        { QuickNavType.Heading3, "nagłówek 3" },
        { QuickNavType.Heading4, "nagłówek 4" },
        { QuickNavType.Heading5, "nagłówek 5" },
        { QuickNavType.Heading6, "nagłówek 6" },
        { QuickNavType.Link, "link" },
        { QuickNavType.UnvisitedLink, "nieodwiedzony link" },
        { QuickNavType.VisitedLink, "odwiedzony link" },
        { QuickNavType.FormField, "pole formularza" },
        { QuickNavType.EditField, "pole edycji" },
        { QuickNavType.Button, "przycisk" },
        { QuickNavType.Checkbox, "pole wyboru" },
        { QuickNavType.RadioButton, "przycisk opcji" },
        { QuickNavType.ComboBox, "pole kombi" },
        { QuickNavType.List, "lista" },
        { QuickNavType.ListItem, "element listy" },
        { QuickNavType.Table, "tabela" },
        { QuickNavType.TableRow, "wiersz tabeli" },
        { QuickNavType.TableCell, "komórka tabeli" },
        { QuickNavType.Graphic, "grafika" },
        { QuickNavType.Landmark, "punkt orientacyjny" },
        { QuickNavType.Frame, "ramka" },
        { QuickNavType.BlockQuote, "cytat blokowy" },
        { QuickNavType.Separator, "separator" },
        { QuickNavType.Paragraph, "akapit" },
        { QuickNavType.Annotation, "adnotacja" },
        { QuickNavType.Article, "artykuł" },
        { QuickNavType.Tab, "karta" },
        { QuickNavType.TabPanel, "panel karty" },
        { QuickNavType.Tree, "drzewo" },
        { QuickNavType.TreeItem, "element drzewa" },
        { QuickNavType.Alert, "alert" },
        { QuickNavType.Dialog, "okno dialogowe" },
        { QuickNavType.ProgressBar, "pasek postępu" },
        { QuickNavType.Slider, "suwak" },
        { QuickNavType.Menu, "menu" },
        { QuickNavType.MenuItem, "element menu" }
    };

    /// <summary>
    /// Pobiera typ elementu dla danego klawisza
    /// </summary>
    public static QuickNavType GetTypeForKey(char key)
    {
        return _keyToType.TryGetValue(char.ToLowerInvariant(key), out var type) ? type : QuickNavType.None;
    }

    /// <summary>
    /// Sprawdza czy klawisz jest klawiszem szybkiej nawigacji
    /// </summary>
    public static bool IsQuickNavKey(char key)
    {
        return _keyToType.ContainsKey(char.ToLowerInvariant(key));
    }

    /// <summary>
    /// Pobiera polską nazwę typu
    /// </summary>
    public static string GetTypeName(QuickNavType type)
    {
        return _typeNames.TryGetValue(type, out var name) ? name : type.ToString();
    }

    /// <summary>
    /// Pobiera wszystkie zarejestrowane klawisze
    /// </summary>
    public static IEnumerable<char> GetAllKeys()
    {
        return _keyToType.Keys;
    }

    /// <summary>
    /// Sprawdza czy typ to nagłówek
    /// </summary>
    public static bool IsHeading(QuickNavType type)
    {
        return type is QuickNavType.Heading or
            QuickNavType.Heading1 or QuickNavType.Heading2 or
            QuickNavType.Heading3 or QuickNavType.Heading4 or
            QuickNavType.Heading5 or QuickNavType.Heading6;
    }

    /// <summary>
    /// Sprawdza czy typ to link
    /// </summary>
    public static bool IsLink(QuickNavType type)
    {
        return type is QuickNavType.Link or
            QuickNavType.UnvisitedLink or QuickNavType.VisitedLink;
    }

    /// <summary>
    /// Sprawdza czy typ to pole formularza
    /// </summary>
    public static bool IsFormField(QuickNavType type)
    {
        return type is QuickNavType.FormField or
            QuickNavType.EditField or QuickNavType.Button or
            QuickNavType.Checkbox or QuickNavType.RadioButton or
            QuickNavType.ComboBox;
    }
}
