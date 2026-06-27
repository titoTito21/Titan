using System.Runtime.InteropServices;
using System.Windows.Automation;

namespace ScreenReader.Accessibility;

/// <summary>
/// Provider dla IAccessible2
/// Obsługuje: Firefox, LibreOffice, aplikacje GTK+
/// Port z NVDA IAccessible2Handler
/// </summary>
public class IAccessible2Provider : IAccessibilityProvider
{
    private bool _isActive;
    private bool _disposed;
    private bool _isAvailable;

    public AccessibilityAPI ApiType => AccessibilityAPI.IAccessible2;
    public bool IsActive => _isActive;
    public bool IsAvailable => _isAvailable;

#pragma warning disable CS0067 // Events required by IAccessibilityProvider interface
    public event EventHandler<AccessibleObject>? FocusChanged;
    public event EventHandler<AccessiblePropertyChangedEventArgs>? PropertyChanged;
    public event EventHandler<AccessibleStructureChangedEventArgs>? StructureChanged;
#pragma warning restore CS0067

    // IAccessible2 interface ID
    private static readonly Guid IID_IAccessible2 = new Guid("E89F726E-C4F4-4c19-BB19-B647D7FA8478");

    public IAccessible2Provider()
    {
        // Sprawdź dostępność IAccessible2
        _isAvailable = CheckIA2Availability();
    }

    private bool CheckIA2Availability()
    {
        try
        {
            // IAccessible2 jest dostępne gdy Firefox lub LibreOffice są zainstalowane
            // Lub gdy jest zarejestrowana biblioteka IA2

            // Sprawdź czy klucz rejestru istnieje
            using var key = Microsoft.Win32.Registry.ClassesRoot.OpenSubKey("Interface\\{E89F726E-C4F4-4c19-BB19-B647D7FA8478}");
            if (key != null)
            {
                Console.WriteLine("IAccessible2Provider: IAccessible2 wykryto w rejestrze");
                return true;
            }

            // Sprawdź znane aplikacje używające IA2
            var firefoxProcesses = System.Diagnostics.Process.GetProcessesByName("firefox");
            var libreOfficeProcesses = System.Diagnostics.Process.GetProcessesByName("soffice");

            if (firefoxProcesses.Length > 0 || libreOfficeProcesses.Length > 0)
            {
                Console.WriteLine("IAccessible2Provider: Znaleziono aplikację używającą IAccessible2");
                return true;
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"IAccessible2Provider: Błąd sprawdzania dostępności: {ex.Message}");
        }

        return false;
    }

    public bool Initialize()
    {
        if (!_isAvailable)
        {
            Console.WriteLine("IAccessible2Provider: IAccessible2 niedostępne");
            return false;
        }

        try
        {
            _isActive = true;
            Console.WriteLine("IAccessible2Provider: Zainicjalizowano pomyślnie");
            return true;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"IAccessible2Provider: Błąd inicjalizacji: {ex.Message}");
            return false;
        }
    }

    public AccessibleObject? GetFocusedObject()
    {
        if (!_isActive)
            return null;

        try
        {
            // Najpierw pobierz IAccessible przez MSAA, potem sprawdź czy wspiera IA2
            IntPtr hwnd = GetForegroundWindow();
            if (hwnd == IntPtr.Zero)
                return null;

            // Sprawdź czy okno należy do aplikacji wspierającej IA2
            if (!IsIA2Window(hwnd))
                return null;

            // Pobierz IAccessible i sprawdź IA2
            var accessible = GetAccessibleFromWindow(hwnd);
            if (accessible != null)
            {
                return CreateAccessibleObject(accessible, hwnd);
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"IAccessible2Provider: Błąd pobierania fokusu: {ex.Message}");
        }

        return null;
    }

    public AccessibleObject? GetObjectFromPoint(int x, int y)
    {
        if (!_isActive)
            return null;

        // Implementacja przez MSAA + sprawdzenie IA2
        return null;
    }

    public AccessibleObject? GetObjectFromHandle(IntPtr hwnd)
    {
        if (!_isActive)
            return null;

        try
        {
            if (IsIA2Window(hwnd))
            {
                var accessible = GetAccessibleFromWindow(hwnd);
                if (accessible != null)
                {
                    return CreateAccessibleObject(accessible, hwnd);
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
            // Sprawdź czy element jest z aplikacji IA2
            IntPtr hwnd = new IntPtr(element.Current.NativeWindowHandle);
            return IsIA2Window(hwnd);
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

        Console.WriteLine("IAccessible2Provider: Rozpoczęto nasłuchiwanie zdarzeń");
        // IA2 używa zdarzeń MSAA + rozszerzeń
    }

    public void StopEventListening()
    {
        Console.WriteLine("IAccessible2Provider: Zatrzymano nasłuchiwanie zdarzeń");
    }

    private bool IsIA2Window(IntPtr hwnd)
    {
        try
        {
            // Sprawdź nazwę procesu
            uint processId;
            GetWindowThreadProcessId(hwnd, out processId);

            using var process = System.Diagnostics.Process.GetProcessById((int)processId);
            string processName = process.ProcessName.ToLowerInvariant();

            // Znane aplikacje IA2
            return processName switch
            {
                "firefox" => true,
                "thunderbird" => true,
                "soffice" => true,      // LibreOffice
                "libreoffice" => true,
                "gimp" => true,         // GIMP
                "inkscape" => true,     // Inkscape
                _ => false
            };
        }
        catch
        {
            return false;
        }
    }

    private object? GetAccessibleFromWindow(IntPtr hwnd)
    {
        // Używamy MSAA jako bazę
        try
        {
            Guid iid = new Guid("618736E0-3C3D-11CF-810C-00AA00389B71");
            if (AccessibleObjectFromWindow(hwnd, 0, ref iid, out var acc) == 0)
            {
                return acc;
            }
        }
        catch { }
        return null;
    }

    private AccessibleObject? CreateAccessibleObject(object accessible, IntPtr hwnd)
    {
        try
        {
            var obj = new IA2AccessibleObject()
            {
                SourceApi = AccessibilityAPI.IAccessible2,
                WindowHandle = hwnd,
                NativeObject = accessible
            };

            // Pobierz właściwości przez IAccessible
            if (accessible is global::Accessibility.IAccessible iacc)
            {
                try { obj.Name = iacc.get_accName(0) ?? ""; } catch { }
                try { obj.Description = iacc.get_accDescription(0) ?? ""; } catch { }
                try { obj.Value = iacc.get_accValue(0) ?? ""; } catch { }
                try { obj.HelpText = iacc.get_accHelp(0) ?? ""; } catch { }

                // Rola
                try
                {
                    var roleObj = iacc.get_accRole(0);
                    if (roleObj is int roleInt)
                    {
                        obj.Role = MapIA2RoleToAccessibleRole(roleInt);
                    }
                }
                catch { }
            }

            // Próbuj pobrać rozszerzone właściwości IA2
            TryGetIA2Properties(accessible, obj);

            return obj;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"IAccessible2Provider: Błąd tworzenia obiektu: {ex.Message}");
            return null;
        }
    }

    private void TryGetIA2Properties(object accessible, IA2AccessibleObject obj)
    {
        // Próba pobrania interfejsu IAccessible2
        // W pełnej implementacji użylibyśmy QueryInterface dla IAccessible2
        // i pobrali rozszerzone właściwości jak:
        // - relations (relacje między elementami)
        // - attributes (atrybuty tekstowe)
        // - nActions (liczba akcji)
        // - localizedExtendedRole
        // - extendedStates
    }

    private AccessibleRole MapIA2RoleToAccessibleRole(int ia2Role)
    {
        // Mapowanie ról IA2 (rozszerzone role MSAA)
        return ia2Role switch
        {
            // Role specyficzne dla IA2
            119 => AccessibleRole.Heading,      // ROLE_HEADING
            120 => AccessibleRole.Section,      // ROLE_SECTION
            121 => AccessibleRole.Form,         // ROLE_FORM
            122 => AccessibleRole.Landmark,     // ROLE_LANDMARK
            123 => AccessibleRole.Article,      // ROLE_ARTICLE
            124 => AccessibleRole.Region,       // ROLE_REGION
            125 => AccessibleRole.Figure,       // ROLE_FIGURE
            126 => AccessibleRole.Note,         // ROLE_NOTE
            127 => AccessibleRole.Math,         // ROLE_MATH
            128 => AccessibleRole.Definition,   // ROLE_DEFINITION
            129 => AccessibleRole.Term,         // ROLE_TERM
            // Fallback do standardowych ról MSAA
            _ => (AccessibleRole)ia2Role
        };
    }

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    [DllImport("oleacc.dll")]
    private static extern int AccessibleObjectFromWindow(IntPtr hwnd, uint dwId,
        ref Guid riid, [MarshalAs(UnmanagedType.IUnknown)] out object ppvObject);

    public void Dispose()
    {
        if (_disposed)
            return;

        StopEventListening();
        _isActive = false;
        _disposed = true;
    }
}

/// <summary>
/// AccessibleObject specyficzny dla IAccessible2
/// </summary>
public class IA2AccessibleObject : AccessibleObject
{
    /// <summary>
    /// Rozszerzone atrybuty IA2
    /// </summary>
    public Dictionary<string, string> IA2Attributes { get; } = new();

    /// <summary>
    /// Relacje z innymi elementami
    /// </summary>
    public List<(string RelationType, AccessibleObject Target)> Relations { get; } = new();

    /// <summary>
    /// Rozszerzona rola (lokalizowana)
    /// </summary>
    public string LocalizedExtendedRole { get; set; } = "";

    /// <summary>
    /// ID unikalny w aplikacji
    /// </summary>
    public int UniqueId { get; set; }

    /// <summary>
    /// Indeks w rodzicu
    /// </summary>
    public int IndexInParent { get; set; }

    public override string GetAnnouncement()
    {
        var parts = new List<string>();

        if (!string.IsNullOrEmpty(Name))
            parts.Add(Name);

        // Użyj lokalizedExtendedRole jeśli dostępna
        if (!string.IsNullOrEmpty(LocalizedExtendedRole))
            parts.Add(LocalizedExtendedRole);
        else
            parts.Add(GetRoleText());

        if (!string.IsNullOrEmpty(Value) && Value != Name)
            parts.Add(Value);

        var stateText = GetStateText();
        if (!string.IsNullOrEmpty(stateText))
            parts.Add(stateText);

        // Dodaj poziom dla nagłówków
        if (Role == AccessibleRole.Heading && Level > 0)
            parts.Add($"poziom {Level}");

        return string.Join(", ", parts);
    }
}
