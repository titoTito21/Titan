using System.Runtime.InteropServices;
using System.Windows.Automation;
using ScreenReader.Speech;
using ScreenReader.Localization;

namespace ScreenReader.Navigation;

/// <summary>
/// Ważne miejsce w systemie lub aplikacji
/// </summary>
public class ImportantPlace
{
    public string Name { get; set; } = "";
    public string Description { get; set; } = "";
    public string? ProcessName { get; set; } // null = globalne
    public Func<AutomationElement?>? FindElement { get; set; }
}

/// <summary>
/// Zarządza nawigacją do ważnych miejsc w systemie
/// </summary>
public class ImportantPlacesManager
{
    private readonly SpeechManager _speechManager;
    private readonly SoundManager _soundManager;
    private readonly List<ImportantPlace> _globalPlaces = new();
    private readonly Dictionary<string, List<ImportantPlace>> _appPlaces = new();

    [DllImport("user32.dll")]
    private static extern IntPtr GetDesktopWindow();

    [DllImport("user32.dll")]
    private static extern IntPtr FindWindow(string? lpClassName, string? lpWindowName);

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("shell32.dll")]
    private static extern IntPtr SHAppBarMessage(uint dwMessage, ref APPBARDATA pData);

    private const uint ABM_GETTASKBARPOS = 0x00000005;

    [StructLayout(LayoutKind.Sequential)]
    private struct APPBARDATA
    {
        public uint cbSize;
        public IntPtr hWnd;
        public uint uCallbackMessage;
        public uint uEdge;
        public RECT rc;
        public int lParam;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct RECT
    {
        public int Left, Top, Right, Bottom;
    }

    public ImportantPlacesManager(SpeechManager speechManager, SoundManager soundManager)
    {
        _speechManager = speechManager;
        _soundManager = soundManager;
        InitializeGlobalPlaces();
        InitializeTCEPlaces();
        InitializeExplorerPlaces();
        InitializeBrowserPlaces();
    }

    /// <summary>
    /// Inicjalizuje globalne ważne miejsca systemu Windows
    /// </summary>
    private void InitializeGlobalPlaces()
    {
        // Pulpit
        _globalPlaces.Add(new ImportantPlace
        {
            Name = L.T("places.desktop.name"),
            Description = L.T("places.desktop.desc"),
            FindElement = FindDesktop
        });

        // Pasek zadań
        _globalPlaces.Add(new ImportantPlace
        {
            Name = L.T("places.taskbar.name"),
            Description = L.T("places.taskbar.desc"),
            FindElement = FindTaskbar
        });

        // Menu Start
        _globalPlaces.Add(new ImportantPlace
        {
            Name = L.T("places.startMenu.name"),
            Description = L.T("places.startMenu.desc"),
            FindElement = FindStartMenu
        });

        // Zasobnik systemowy (System Tray)
        _globalPlaces.Add(new ImportantPlace
        {
            Name = L.T("places.systemTray.name"),
            Description = L.T("places.systemTray.desc"),
            FindElement = FindSystemTray
        });

        // Pasek menu aktywnej aplikacji
        _globalPlaces.Add(new ImportantPlace
        {
            Name = L.T("places.menuBar.name"),
            Description = L.T("places.menuBar.desc"),
            FindElement = FindMenuBar
        });
    }

    /// <summary>
    /// Inicjalizuje ważne miejsca dla TCE/Titan
    /// </summary>
    private void InitializeTCEPlaces()
    {
        var tcePlaces = new List<ImportantPlace>
        {
            new ImportantPlace
            {
                Name = L.T("places.tce.statusBar.name"),
                Description = L.T("places.tce.statusBar.desc"),
                FindElement = () => FindTCEElement("StatusBar")
            },
            new ImportantPlace
            {
                Name = L.T("places.tce.appList.name"),
                Description = L.T("places.tce.appList.desc"),
                FindElement = () => FindTCEElement("AppList")
            },
            new ImportantPlace
            {
                Name = L.T("places.tce.gameList.name"),
                Description = L.T("places.tce.gameList.desc"),
                FindElement = () => FindTCEElement("GameList")
            },
            new ImportantPlace
            {
                Name = L.T("places.tce.menuBar.name"),
                Description = L.T("places.tce.menuBar.desc"),
                FindElement = () => FindTCEElement("MenuBar")
            }
        };

        // Dodaj dla procesów TCE
        _appPlaces["tce"] = tcePlaces;
        _appPlaces["titan"] = tcePlaces;
        _appPlaces["titancommunicationenvironment"] = tcePlaces;
    }

    /// <summary>
    /// Inicjalizuje ważne miejsca dla Windows Explorera
    /// </summary>
    private void InitializeExplorerPlaces()
    {
        var explorerPlaces = new List<ImportantPlace>
        {
            new ImportantPlace
            {
                Name = L.T("places.explorer.addressBar.name"),
                Description = L.T("places.explorer.addressBar.desc"),
                FindElement = () => FindExplorerElement("AddressBar")
            },
            new ImportantPlace
            {
                Name = L.T("places.explorer.fileList.name"),
                Description = L.T("places.explorer.fileList.desc"),
                FindElement = () => FindExplorerElement("FileList")
            },
            new ImportantPlace
            {
                Name = L.T("places.explorer.folderTree.name"),
                Description = L.T("places.explorer.folderTree.desc"),
                FindElement = () => FindExplorerElement("FolderTree")
            },
            new ImportantPlace
            {
                Name = L.T("places.explorer.searchBox.name"),
                Description = L.T("places.explorer.searchBox.desc"),
                FindElement = () => FindExplorerElement("SearchBox")
            },
            new ImportantPlace
            {
                Name = L.T("places.explorer.detailsPane.name"),
                Description = L.T("places.explorer.detailsPane.desc"),
                FindElement = () => FindExplorerElement("DetailsPane")
            }
        };

        _appPlaces["explorer"] = explorerPlaces;
    }

    /// <summary>
    /// Inicjalizuje ważne miejsca dla przeglądarek internetowych
    /// </summary>
    private void InitializeBrowserPlaces()
    {
        var browserPlaces = new List<ImportantPlace>
        {
            new ImportantPlace
            {
                Name = L.T("places.browser.addressBar.name"),
                Description = L.T("places.browser.addressBar.desc"),
                FindElement = () => FindBrowserElement("AddressBar")
            },
            new ImportantPlace
            {
                Name = L.T("places.browser.mainContent.name"),
                Description = L.T("places.browser.mainContent.desc"),
                FindElement = () => FindBrowserElement("MainContent")
            },
            new ImportantPlace
            {
                Name = L.T("places.browser.navigation.name"),
                Description = L.T("places.browser.navigation.desc"),
                FindElement = () => FindBrowserElement("Navigation")
            },
            new ImportantPlace
            {
                Name = L.T("places.browser.search.name"),
                Description = L.T("places.browser.search.desc"),
                FindElement = () => FindBrowserElement("Search")
            }
        };

        // Dodaj dla wszystkich popularnych przeglądarek
        _appPlaces["chrome"] = browserPlaces;
        _appPlaces["msedge"] = browserPlaces;
        _appPlaces["firefox"] = browserPlaces;
        _appPlaces["brave"] = browserPlaces;
        _appPlaces["opera"] = browserPlaces;
        _appPlaces["vivaldi"] = browserPlaces;
    }

    /// <summary>
    /// Pobiera listę ważnych miejsc dla bieżącej aplikacji
    /// </summary>
    public List<ImportantPlace> GetPlacesForCurrentApp(string? processName)
    {
        var places = new List<ImportantPlace>(_globalPlaces);

        if (!string.IsNullOrEmpty(processName))
        {
            string lowerName = processName.ToLowerInvariant();
            if (_appPlaces.TryGetValue(lowerName, out var appPlaces))
            {
                places.AddRange(appPlaces);
            }
        }

        return places;
    }

    /// <summary>
    /// Nawiguje do ważnego miejsca
    /// </summary>
    public bool NavigateToPlace(ImportantPlace place)
    {
        try
        {
            var element = place.FindElement?.Invoke();
            if (element != null)
            {
                element.SetFocus();
                _speechManager.Speak(place.Name);
                return true;
            }
            else
            {
                _speechManager.Speak(L.T("places.notFound", place.Name));
                return false;
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"ImportantPlaces: Błąd nawigacji do {place.Name} - {ex.Message}");
            _speechManager.Speak(L.T("places.navError", place.Name));
            return false;
        }
    }

    /// <summary>
    /// Nawiguje do miejsca po indeksie
    /// </summary>
    public bool NavigateToPlaceByIndex(int index, string? processName)
    {
        var places = GetPlacesForCurrentApp(processName);
        if (index >= 0 && index < places.Count)
        {
            return NavigateToPlace(places[index]);
        }
        return false;
    }

    // ========== Metody wyszukiwania elementów ==========

    private AutomationElement? FindDesktop()
    {
        try
        {
            // Znajdź okno pulpitu
            var desktop = AutomationElement.RootElement.FindFirst(
                TreeScope.Children,
                new PropertyCondition(AutomationElement.ClassNameProperty, "Progman"));

            if (desktop == null)
            {
                // Alternatywna metoda - WorkerW
                desktop = AutomationElement.RootElement.FindFirst(
                    TreeScope.Children,
                    new PropertyCondition(AutomationElement.ClassNameProperty, "WorkerW"));
            }

            // Znajdź ListView wewnątrz
            if (desktop != null)
            {
                var listView = desktop.FindFirst(
                    TreeScope.Descendants,
                    new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.List));
                return listView ?? desktop;
            }

            return desktop;
        }
        catch
        {
            return null;
        }
    }

    private AutomationElement? FindTaskbar()
    {
        try
        {
            return AutomationElement.RootElement.FindFirst(
                TreeScope.Children,
                new PropertyCondition(AutomationElement.ClassNameProperty, "Shell_TrayWnd"));
        }
        catch
        {
            return null;
        }
    }

    private AutomationElement? FindStartMenu()
    {
        try
        {
            // Windows 10/11 Start Menu
            var startMenu = AutomationElement.RootElement.FindFirst(
                TreeScope.Children,
                new PropertyCondition(AutomationElement.ClassNameProperty, "Windows.UI.Core.CoreWindow"));

            if (startMenu != null)
            {
                string? name = startMenu.Current.Name?.ToLowerInvariant();
                if (name?.Contains("start") == true || name?.Contains("menu") == true)
                {
                    return startMenu;
                }
            }

            // Fallback - znajdź przycisk Start
            var taskbar = FindTaskbar();
            if (taskbar != null)
            {
                return taskbar.FindFirst(
                    TreeScope.Descendants,
                    new PropertyCondition(AutomationElement.NameProperty, "Start"));
            }

            return null;
        }
        catch
        {
            return null;
        }
    }

    private AutomationElement? FindSystemTray()
    {
        try
        {
            var taskbar = FindTaskbar();
            if (taskbar != null)
            {
                // Znajdź obszar powiadomień
                var tray = taskbar.FindFirst(
                    TreeScope.Descendants,
                    new PropertyCondition(AutomationElement.ClassNameProperty, "TrayNotifyWnd"));

                if (tray != null)
                {
                    // Znajdź przycisk rozwijania
                    var overflow = tray.FindFirst(
                        TreeScope.Descendants,
                        new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Button));
                    return overflow ?? tray;
                }

                // Windows 11 - System Tray
                tray = taskbar.FindFirst(
                    TreeScope.Descendants,
                    new PropertyCondition(AutomationElement.AutomationIdProperty, "SystemTrayIcon"));

                return tray;
            }

            return null;
        }
        catch
        {
            return null;
        }
    }

    private AutomationElement? FindMenuBar()
    {
        try
        {
            // Znajdź aktywne okno
            IntPtr foregroundHwnd = GetForegroundWindow();
            if (foregroundHwnd == IntPtr.Zero)
                return null;

            var foregroundWindow = AutomationElement.FromHandle(foregroundHwnd);
            if (foregroundWindow == null)
                return null;

            // Znajdź pasek menu
            return foregroundWindow.FindFirst(
                TreeScope.Descendants,
                new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.MenuBar));
        }
        catch
        {
            return null;
        }
    }

    private AutomationElement? FindTCEElement(string elementType)
    {
        try
        {
            IntPtr foregroundHwnd = GetForegroundWindow();
            if (foregroundHwnd == IntPtr.Zero)
                return null;

            var window = AutomationElement.FromHandle(foregroundHwnd);
            if (window == null)
                return null;

            switch (elementType)
            {
                case "StatusBar":
                    return window.FindFirst(
                        TreeScope.Descendants,
                        new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.StatusBar));

                case "MenuBar":
                    return window.FindFirst(
                        TreeScope.Descendants,
                        new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.MenuBar));

                case "AppList":
                case "GameList":
                    // Znajdź pierwszą listę w oknie
                    return window.FindFirst(
                        TreeScope.Descendants,
                        new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.List));

                default:
                    return null;
            }
        }
        catch
        {
            return null;
        }
    }

    private AutomationElement? FindExplorerElement(string elementType)
    {
        try
        {
            IntPtr foregroundHwnd = GetForegroundWindow();
            if (foregroundHwnd == IntPtr.Zero)
                return null;

            var window = AutomationElement.FromHandle(foregroundHwnd);
            if (window == null)
                return null;

            switch (elementType)
            {
                case "AddressBar":
                    // Znajdź pasek adresu (Edit lub ComboBox z nazwą zawierającą "Address" lub AutomationId)
                    var addressBar = window.FindFirst(
                        TreeScope.Descendants,
                        new AndCondition(
                            new OrCondition(
                                new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Edit),
                                new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.ComboBox)
                            ),
                            new PropertyCondition(AutomationElement.AutomationIdProperty, "41477")
                        ));

                    if (addressBar == null)
                    {
                        // Alternatywna metoda - szukaj po nazwie
                        addressBar = window.FindFirst(
                            TreeScope.Descendants,
                            new PropertyCondition(AutomationElement.NameProperty, "Adres"));
                    }
                    return addressBar;

                case "FileList":
                    // Znajdź główną listę plików (DataGrid lub List)
                    return window.FindFirst(
                        TreeScope.Descendants,
                        new OrCondition(
                            new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.DataGrid),
                            new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.List)
                        ));

                case "FolderTree":
                    // Znajdź drzewo folderów (TreeView)
                    return window.FindFirst(
                        TreeScope.Descendants,
                        new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Tree));

                case "SearchBox":
                    // Znajdź pole wyszukiwania
                    var searchBox = window.FindFirst(
                        TreeScope.Descendants,
                        new PropertyCondition(AutomationElement.AutomationIdProperty, "1001"));

                    if (searchBox == null)
                    {
                        // Alternatywna metoda
                        searchBox = window.FindFirst(
                            TreeScope.Descendants,
                            new AndCondition(
                                new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Edit),
                                new PropertyCondition(AutomationElement.NameProperty, "Szukaj")
                            ));
                    }
                    return searchBox;

                case "DetailsPane":
                    // Znajdź panel szczegółów (zwykle Pane z nazwą "Details")
                    return window.FindFirst(
                        TreeScope.Descendants,
                        new PropertyCondition(AutomationElement.NameProperty, "Details"));

                default:
                    return null;
            }
        }
        catch
        {
            return null;
        }
    }

    private AutomationElement? FindBrowserElement(string elementType)
    {
        try
        {
            IntPtr foregroundHwnd = GetForegroundWindow();
            if (foregroundHwnd == IntPtr.Zero)
                return null;

            var window = AutomationElement.FromHandle(foregroundHwnd);
            if (window == null)
                return null;

            switch (elementType)
            {
                case "AddressBar":
                    // Znajdź pasek adresu przeglądarki (zwykle ComboBox lub Edit)
                    var addressBar = window.FindFirst(
                        TreeScope.Descendants,
                        new AndCondition(
                            new OrCondition(
                                new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Edit),
                                new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.ComboBox)
                            ),
                            new PropertyCondition(AutomationElement.NameProperty, "Pasek adresu i wyszukiwania")
                        ));

                    if (addressBar == null)
                    {
                        // Alternatywna metoda - szukaj po AutomationId (Chrome/Edge)
                        addressBar = window.FindFirst(
                            TreeScope.Descendants,
                            new PropertyCondition(AutomationElement.AutomationIdProperty, "Chrome Legacy Window"));
                    }
                    return addressBar;

                case "MainContent":
                    // Znajdź główny obszar zawartości (Document z rolą main)
                    var mainContent = window.FindFirst(
                        TreeScope.Descendants,
                        new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Document));

                    // Spróbuj znaleźć element z rolą ARIA "main"
                    if (mainContent != null)
                    {
                        try
                        {
                            var mainLandmark = mainContent.FindFirst(
                                TreeScope.Descendants,
                                new PropertyCondition(AutomationElement.LocalizedControlTypeProperty, "main"));
                            return mainLandmark ?? mainContent;
                        }
                        catch { }
                    }
                    return mainContent;

                case "Navigation":
                    // Znajdź nawigację (ARIA role="navigation")
                    var document = window.FindFirst(
                        TreeScope.Descendants,
                        new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Document));

                    if (document != null)
                    {
                        return document.FindFirst(
                            TreeScope.Descendants,
                            new PropertyCondition(AutomationElement.LocalizedControlTypeProperty, "navigation"));
                    }
                    return null;

                case "Search":
                    // Znajdź pole wyszukiwania na stronie (ARIA role="search" lub searchbox)
                    var doc = window.FindFirst(
                        TreeScope.Descendants,
                        new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Document));

                    if (doc != null)
                    {
                        var searchRegion = doc.FindFirst(
                            TreeScope.Descendants,
                            new PropertyCondition(AutomationElement.LocalizedControlTypeProperty, "search"));

                        if (searchRegion != null)
                        {
                            // Znajdź pole edycji wewnątrz
                            var searchBox = searchRegion.FindFirst(
                                TreeScope.Descendants,
                                new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Edit));
                            return searchBox ?? searchRegion;
                        }
                    }
                    return null;

                default:
                    return null;
            }
        }
        catch
        {
            return null;
        }
    }
}
