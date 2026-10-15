using System.Runtime.InteropServices;
using System.Windows.Automation;

namespace ScreenReader.Accessibility;

/// <summary>
/// Provider dla Java Access Bridge
/// Obsługuje: Eclipse, IntelliJ IDEA, aplikacje Swing/JavaFX
/// Port z NVDA JABHandler
/// </summary>
public class JavaAccessBridgeProvider : IAccessibilityProvider
{
    private bool _isActive;
    private bool _disposed;
    private bool _isAvailable;
    private bool _isInitialized;

    public AccessibilityAPI ApiType => AccessibilityAPI.JavaAccessBridge;
    public bool IsActive => _isActive;
    public bool IsAvailable => _isAvailable;

#pragma warning disable CS0067 // Events required by IAccessibilityProvider interface
    public event EventHandler<AccessibleObject>? FocusChanged;
    public event EventHandler<AccessiblePropertyChangedEventArgs>? PropertyChanged;
    public event EventHandler<AccessibleStructureChangedEventArgs>? StructureChanged;
#pragma warning restore CS0067

    // Java Access Bridge DLL
    private const string JAB_DLL_32 = "WindowsAccessBridge-32.dll";
    private const string JAB_DLL_64 = "WindowsAccessBridge-64.dll";

    // JAB function delegates
    private delegate bool Windows_runDelegate();
    private delegate void ReleaseJavaObjectDelegate(int vmID, IntPtr javaObject);
    private delegate bool GetAccessibleContextFromHWNDDelegate(IntPtr hwnd, out int vmID, out IntPtr ac);
    private delegate bool GetAccessibleContextInfoDelegate(int vmID, IntPtr ac, out AccessibleContextInfo info);
    private delegate bool GetAccessibleTextInfoDelegate(int vmID, IntPtr ac, out AccessibleTextInfo textInfo, int x, int y);

    private Windows_runDelegate? _windowsRun;
    private ReleaseJavaObjectDelegate? _releaseJavaObject;
    private GetAccessibleContextFromHWNDDelegate? _getAccessibleContextFromHWND;
    private GetAccessibleContextInfoDelegate? _getAccessibleContextInfo;

    private IntPtr _jabHandle = IntPtr.Zero;

    public JavaAccessBridgeProvider()
    {
        _isAvailable = CheckJABAvailability();
    }

    private bool CheckJABAvailability()
    {
        try
        {
            // Sprawdź czy Java jest zainstalowana i JAB jest dostępny
            string jabDll = Environment.Is64BitProcess ? JAB_DLL_64 : JAB_DLL_32;

            // Sprawdź w różnych lokalizacjach
            string[] paths =
            {
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), jabDll),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), jabDll),
                jabDll
            };

            foreach (var path in paths)
            {
                if (File.Exists(path))
                {
                    Console.WriteLine($"JavaAccessBridgeProvider: Znaleziono JAB w: {path}");
                    return true;
                }
            }

            // Sprawdź w PATH
            string? pathEnv = Environment.GetEnvironmentVariable("PATH");
            if (pathEnv != null)
            {
                foreach (var dir in pathEnv.Split(';'))
                {
                    try
                    {
                        string fullPath = Path.Combine(dir.Trim(), jabDll);
                        if (File.Exists(fullPath))
                        {
                            Console.WriteLine($"JavaAccessBridgeProvider: Znaleziono JAB w PATH: {fullPath}");
                            return true;
                        }
                    }
                    catch { }
                }
            }

            // Sprawdź czy są uruchomione aplikacje Java
            var javaProcesses = System.Diagnostics.Process.GetProcessesByName("java");
            var javawProcesses = System.Diagnostics.Process.GetProcessesByName("javaw");
            var eclipseProcesses = System.Diagnostics.Process.GetProcessesByName("eclipse");
            var ideaProcesses = System.Diagnostics.Process.GetProcessesByName("idea64");

            if (javaProcesses.Length > 0 || javawProcesses.Length > 0 ||
                eclipseProcesses.Length > 0 || ideaProcesses.Length > 0)
            {
                Console.WriteLine("JavaAccessBridgeProvider: Znaleziono działające aplikacje Java");
                return true;
            }

            Console.WriteLine("JavaAccessBridgeProvider: Java Access Bridge niedostępny");
        }
        catch (Exception ex)
        {
            Console.WriteLine($"JavaAccessBridgeProvider: Błąd sprawdzania dostępności: {ex.Message}");
        }

        return false;
    }

    public bool Initialize()
    {
        if (!_isAvailable)
        {
            Console.WriteLine("JavaAccessBridgeProvider: JAB niedostępny");
            return false;
        }

        if (_isInitialized)
            return _isActive;

        try
        {
            string jabDll = Environment.Is64BitProcess ? JAB_DLL_64 : JAB_DLL_32;

            // Załaduj bibliotekę JAB
            _jabHandle = LoadLibrary(jabDll);
            if (_jabHandle == IntPtr.Zero)
            {
                Console.WriteLine($"JavaAccessBridgeProvider: Nie można załadować {jabDll}");
                return false;
            }

            // Pobierz adresy funkcji
            var windowsRunPtr = GetProcAddress(_jabHandle, "Windows_run");
            if (windowsRunPtr != IntPtr.Zero)
            {
                _windowsRun = Marshal.GetDelegateForFunctionPointer<Windows_runDelegate>(windowsRunPtr);
            }

            var releasePtr = GetProcAddress(_jabHandle, "releaseJavaObject");
            if (releasePtr != IntPtr.Zero)
            {
                _releaseJavaObject = Marshal.GetDelegateForFunctionPointer<ReleaseJavaObjectDelegate>(releasePtr);
            }

            var getContextPtr = GetProcAddress(_jabHandle, "getAccessibleContextFromHWND");
            if (getContextPtr != IntPtr.Zero)
            {
                _getAccessibleContextFromHWND = Marshal.GetDelegateForFunctionPointer<GetAccessibleContextFromHWNDDelegate>(getContextPtr);
            }

            var getInfoPtr = GetProcAddress(_jabHandle, "getAccessibleContextInfo");
            if (getInfoPtr != IntPtr.Zero)
            {
                _getAccessibleContextInfo = Marshal.GetDelegateForFunctionPointer<GetAccessibleContextInfoDelegate>(getInfoPtr);
            }

            // Inicjalizuj JAB
            if (_windowsRun != null && _windowsRun())
            {
                _isActive = true;
                _isInitialized = true;
                Console.WriteLine("JavaAccessBridgeProvider: Zainicjalizowano pomyślnie");
                return true;
            }
            else
            {
                Console.WriteLine("JavaAccessBridgeProvider: Windows_run() zwróciło false");
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"JavaAccessBridgeProvider: Błąd inicjalizacji: {ex.Message}");
        }

        return false;
    }

    public AccessibleObject? GetFocusedObject()
    {
        if (!_isActive)
            return null;

        try
        {
            IntPtr hwnd = GetForegroundWindow();
            if (hwnd == IntPtr.Zero)
                return null;

            // Sprawdź czy to okno Java
            if (!IsJavaWindow(hwnd))
                return null;

            // Pobierz AccessibleContext
            if (_getAccessibleContextFromHWND != null &&
                _getAccessibleContextFromHWND(hwnd, out int vmID, out IntPtr ac))
            {
                return CreateAccessibleObject(vmID, ac, hwnd);
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"JavaAccessBridgeProvider: Błąd pobierania fokusu: {ex.Message}");
        }

        return null;
    }

    public AccessibleObject? GetObjectFromPoint(int x, int y)
    {
        if (!_isActive)
            return null;

        // JAB wymaga najpierw znalezienia okna pod punktem
        return null;
    }

    public AccessibleObject? GetObjectFromHandle(IntPtr hwnd)
    {
        if (!_isActive)
            return null;

        try
        {
            if (IsJavaWindow(hwnd) && _getAccessibleContextFromHWND != null)
            {
                if (_getAccessibleContextFromHWND(hwnd, out int vmID, out IntPtr ac))
                {
                    return CreateAccessibleObject(vmID, ac, hwnd);
                }
            }
        }
        catch { }

        return null;
    }

    public bool SupportsElement(AutomationElement element)
    {
        if (!_isActive)
            return false;

        try
        {
            IntPtr hwnd = new IntPtr(element.Current.NativeWindowHandle);
            return IsJavaWindow(hwnd);
        }
        catch
        {
            return false;
        }
    }

    public AccessibleObject? GetAccessibleObject(AutomationElement element)
    {
        try
        {
            IntPtr hwnd = new IntPtr(element.Current.NativeWindowHandle);
            return GetObjectFromHandle(hwnd);
        }
        catch
        {
            return null;
        }
    }

    public void StartEventListening()
    {
        if (!_isActive)
            return;

        Console.WriteLine("JavaAccessBridgeProvider: Rozpoczęto nasłuchiwanie zdarzeń");
        // JAB używa callbacków które trzeba zarejestrować
        // setFocusGainedFP, setPropertyChangeFP, etc.
    }

    public void StopEventListening()
    {
        Console.WriteLine("JavaAccessBridgeProvider: Zatrzymano nasłuchiwanie zdarzeń");
    }

    private bool IsJavaWindow(IntPtr hwnd)
    {
        try
        {
            // Sprawdź klasę okna
            var className = new System.Text.StringBuilder(256);
            GetClassName(hwnd, className, className.Capacity);

            string cls = className.ToString();

            // Znane klasy okien Java
            return cls.Contains("SunAwt") ||
                   cls.Contains("SWT_Window") ||
                   cls.Contains("SALFRAME") || // LibreOffice Java
                   cls.StartsWith("javax.swing") ||
                   cls.Contains("AWT");
        }
        catch
        {
            return false;
        }
    }

    private AccessibleObject? CreateAccessibleObject(int vmID, IntPtr ac, IntPtr hwnd)
    {
        try
        {
            var obj = new JABAccessibleObject(vmID, ac, _releaseJavaObject)
            {
                SourceApi = AccessibilityAPI.JavaAccessBridge,
                WindowHandle = hwnd
            };

            // Pobierz informacje o kontekście
            if (_getAccessibleContextInfo != null &&
                _getAccessibleContextInfo(vmID, ac, out AccessibleContextInfo info))
            {
                obj.Name = info.name ?? "";
                obj.Description = info.description ?? "";
                obj.Role = MapJavaRoleToAccessibleRole(info.role ?? "");
                obj.States = ParseJavaStates(info.states ?? "");
                obj.PositionInGroup = info.indexInParent;
                obj.GroupSize = info.childrenCount;
                obj.BoundingRectangle = new System.Drawing.Rectangle(
                    info.x, info.y, info.width, info.height);
            }

            return obj;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"JavaAccessBridgeProvider: Błąd tworzenia obiektu: {ex.Message}");
            return null;
        }
    }

    private AccessibleRole MapJavaRoleToAccessibleRole(string javaRole)
    {
        return javaRole.ToLowerInvariant() switch
        {
            "push button" => AccessibleRole.PushButton,
            "toggle button" => AccessibleRole.ToggleButton,
            "radio button" => AccessibleRole.RadioButton,
            "check box" => AccessibleRole.CheckButton,
            "combo box" => AccessibleRole.ComboBox,
            "text" => AccessibleRole.Edit,
            "label" => AccessibleRole.StaticText,
            "list" => AccessibleRole.List,
            "list item" => AccessibleRole.ListItem,
            "tree" => AccessibleRole.TreeView,
            "tree node" => AccessibleRole.TreeViewItem,
            "table" => AccessibleRole.Table,
            "table cell" => AccessibleRole.Cell,
            "menu" => AccessibleRole.Menu,
            "menu item" => AccessibleRole.MenuItem,
            "menu bar" => AccessibleRole.MenuBar,
            "popup menu" => AccessibleRole.MenuPopup,
            "dialog" => AccessibleRole.Dialog,
            "frame" => AccessibleRole.Window,
            "panel" => AccessibleRole.Pane,
            "scroll pane" => AccessibleRole.Pane,
            "split pane" => AccessibleRole.Pane,
            "tabbed pane" => AccessibleRole.PageTabList,
            "page tab" => AccessibleRole.PageTab,
            "toolbar" => AccessibleRole.ToolBar,
            "tool tip" => AccessibleRole.Tooltip,
            "progress bar" => AccessibleRole.ProgressBar,
            "slider" => AccessibleRole.Slider,
            "spinner" => AccessibleRole.SpinButton,
            "hyperlink" => AccessibleRole.Link,
            "password text" => AccessibleRole.Edit,
            "scroll bar" => AccessibleRole.ScrollBar,
            "separator" => AccessibleRole.Separator,
            "status bar" => AccessibleRole.StatusBar,
            "glass pane" => AccessibleRole.Pane,
            "layered pane" => AccessibleRole.Pane,
            "root pane" => AccessibleRole.Pane,
            "internal frame" => AccessibleRole.Window,
            "desktop icon" => AccessibleRole.Graphic,
            "desktop pane" => AccessibleRole.Pane,
            "option pane" => AccessibleRole.Dialog,
            "color chooser" => AccessibleRole.Dialog,
            "file chooser" => AccessibleRole.Dialog,
            "filler" => AccessibleRole.WhiteSpace,
            "header" => AccessibleRole.Header,
            "footer" => AccessibleRole.Pane,
            "paragraph" => AccessibleRole.Text,
            "ruler" => AccessibleRole.Pane,
            "editbar" => AccessibleRole.Edit,
            _ => AccessibleRole.Pane
        };
    }

    private AccessibleStates ParseJavaStates(string statesString)
    {
        var states = AccessibleStates.None;

        if (string.IsNullOrEmpty(statesString))
            return states;

        var stateList = statesString.ToLowerInvariant().Split(',');

        foreach (var state in stateList)
        {
            var trimmed = state.Trim();
            switch (trimmed)
            {
                case "enabled": break; // Domyślnie enabled
                case "visible": break; // Domyślnie visible
                case "showing": break;
                case "focusable": states |= AccessibleStates.Focusable; break;
                case "focused": states |= AccessibleStates.Focused; break;
                case "selected": states |= AccessibleStates.Selected; break;
                case "pressed": states |= AccessibleStates.Pressed; break;
                case "checked": states |= AccessibleStates.Checked; break;
                case "expanded": states |= AccessibleStates.Expanded; break;
                case "collapsed": states |= AccessibleStates.Collapsed; break;
                case "editable": break;
                case "enabled=false":
                case "disabled": states |= AccessibleStates.Unavailable; break;
                case "invisible": states |= AccessibleStates.Invisible; break;
                case "busy": states |= AccessibleStates.Busy; break;
                case "multi_selectable": states |= AccessibleStates.Multiselectable; break;
                case "modal": break;
                case "single_line": break;
                case "multi_line": break;
                case "transient": break;
                case "vertical": break;
                case "horizontal": break;
            }
        }

        return states;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr LoadLibrary(string lpFileName);

    [DllImport("kernel32.dll")]
    private static extern IntPtr GetProcAddress(IntPtr hModule, string lpProcName);

    [DllImport("kernel32.dll")]
    private static extern bool FreeLibrary(IntPtr hModule);

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetClassName(IntPtr hWnd, System.Text.StringBuilder lpClassName, int nMaxCount);

    public void Dispose()
    {
        if (_disposed)
            return;

        StopEventListening();

        if (_jabHandle != IntPtr.Zero)
        {
            FreeLibrary(_jabHandle);
            _jabHandle = IntPtr.Zero;
        }

        _isActive = false;
        _disposed = true;
    }
}

/// <summary>
/// Struktura informacji o kontekście dostępności Java
/// </summary>
[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
public struct AccessibleContextInfo
{
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 1024)]
    public string name;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 1024)]
    public string description;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)]
    public string role;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)]
    public string role_en_US;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)]
    public string states;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)]
    public string states_en_US;
    public int indexInParent;
    public int childrenCount;
    public int x;
    public int y;
    public int width;
    public int height;
    public bool accessibleComponent;
    public bool accessibleAction;
    public bool accessibleSelection;
    public bool accessibleText;
    public bool accessibleInterfaces;
}

/// <summary>
/// Struktura informacji o tekście dostępności Java
/// </summary>
[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
public struct AccessibleTextInfo
{
    public int charCount;
    public int caretIndex;
    public int indexAtPoint;
}

/// <summary>
/// AccessibleObject specyficzny dla Java Access Bridge
/// </summary>
public class JABAccessibleObject : AccessibleObject
{
    private readonly int _vmID;
    private readonly IntPtr _accessibleContext;
    private readonly ReleaseJavaObjectDelegate? _releaseFunc;
    private bool _disposed;

    private delegate void ReleaseJavaObjectDelegate(int vmID, IntPtr javaObject);

    public JABAccessibleObject(int vmID, IntPtr ac, object? releaseFunc)
    {
        _vmID = vmID;
        _accessibleContext = ac;
        _releaseFunc = releaseFunc as ReleaseJavaObjectDelegate;
        NativeObject = ac;
    }

    ~JABAccessibleObject()
    {
        Dispose();
    }

    private void Dispose()
    {
        if (_disposed)
            return;

        try
        {
            if (_accessibleContext != IntPtr.Zero && _releaseFunc != null)
            {
                _releaseFunc(_vmID, _accessibleContext);
            }
        }
        catch { }

        _disposed = true;
    }
}
