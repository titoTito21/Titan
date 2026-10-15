using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Automation;

namespace ScreenReader.Interop;

/// <summary>
/// Model dostępności używany przez przeglądarkę
/// </summary>
public enum AccessibilityModel
{
    /// <summary>Nieznany/niezainicjowany</summary>
    Unknown,

    /// <summary>UI Automation (preferowany w Windows 11)</summary>
    UIA,

    /// <summary>IAccessible2 (legacy, ale bardziej kompletny)</summary>
    IAccessible2,

    /// <summary>MSAA (podstawowy)</summary>
    MSAA
}

/// <summary>
/// Zarządza automatycznym przełączaniem modeli dostępności dla przeglądarek Chromium.
///
/// W Chrome 138+ UIA jest domyślnie włączone, ale IAccessible2 nadal jest dostępne.
/// Ta klasa aktywuje IAccessible2 poprzez sondowanie interfejsu, co umożliwia
/// pełniejszą obsługę wirtualnego bufora.
/// </summary>
public class AccessibilityModelManager : IDisposable
{
    private readonly Dictionary<int, AccessibilityModel> _processModels = new();
    private readonly HashSet<int> _activatedProcesses = new();
    private readonly object _lock = new();
    private bool _disposed;

    /// <summary>
    /// Aktualnie preferowany model dostępności
    /// </summary>
    public AccessibilityModel PreferredModel { get; set; } = AccessibilityModel.UIA;

    /// <summary>
    /// Czy automatycznie aktywować IAccessible2 dla przeglądarek Chromium
    /// </summary>
    public bool AutoActivateIA2 { get; set; } = true;

    /// <summary>
    /// Zdarzenie wywoływane po zmianie modelu dostępności
    /// </summary>
    public event Action<int, AccessibilityModel>? ModelChanged;

    /// <summary>
    /// Sprawdza czy proces to przeglądarka Chromium (Chrome, Edge)
    /// </summary>
    public static bool IsChromiumProcess(string processName)
    {
        var name = processName.ToLowerInvariant();
        return name is "chrome" or "msedge" or "chromium" or "brave" or "vivaldi" or "opera";
    }

    /// <summary>
    /// Sprawdza czy proces to przeglądarka Chromium
    /// </summary>
    public static bool IsChromiumProcess(int processId)
    {
        try
        {
            using var process = Process.GetProcessById(processId);
            return IsChromiumProcess(process.ProcessName);
        }
        catch
        {
            return false;
        }
    }

    /// <summary>
    /// Aktywuje dostępność dla procesu przeglądarki Chromium.
    /// Wywołanie tej metody "budzi" interfejsy dostępności w przeglądarce.
    /// </summary>
    public bool ActivateAccessibility(int processId)
    {
        lock (_lock)
        {
            if (_activatedProcesses.Contains(processId))
                return true;
        }

        try
        {
            using var process = Process.GetProcessById(processId);
            if (!IsChromiumProcess(process.ProcessName))
                return false;

            var hwnd = process.MainWindowHandle;
            if (hwnd == IntPtr.Zero)
                return false;

            Console.WriteLine($"AccessibilityModelManager: Aktywacja dostępności dla {process.ProcessName} (PID: {processId})");

            // Aktywuj IAccessible2 przez sondowanie interfejsu
            bool success = ActivateIAccessible2(hwnd);

            if (success)
            {
                lock (_lock)
                {
                    _activatedProcesses.Add(processId);
                    _processModels[processId] = AccessibilityModel.IAccessible2;
                }
                Console.WriteLine($"AccessibilityModelManager: IAccessible2 aktywowany dla PID {processId}");
                ModelChanged?.Invoke(processId, AccessibilityModel.IAccessible2);
            }
            else
            {
                // Próbuj ponownie - czasem potrzeba dwóch wywołań
                success = ActivateIAccessible2(hwnd);
                if (success)
                {
                    lock (_lock)
                    {
                        _activatedProcesses.Add(processId);
                        _processModels[processId] = AccessibilityModel.IAccessible2;
                    }
                    Console.WriteLine($"AccessibilityModelManager: IAccessible2 aktywowany (2. próba) dla PID {processId}");
                    ModelChanged?.Invoke(processId, AccessibilityModel.IAccessible2);
                }
                else
                {
                    lock (_lock)
                    {
                        _processModels[processId] = AccessibilityModel.UIA;
                    }
                    Console.WriteLine($"AccessibilityModelManager: Używam UIA dla PID {processId}");
                    ModelChanged?.Invoke(processId, AccessibilityModel.UIA);
                }
            }

            return success;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"AccessibilityModelManager: Błąd aktywacji: {ex.Message}");
            return false;
        }
    }

    /// <summary>
    /// Aktywuje dostępność dla elementu UI Automation
    /// </summary>
    public bool ActivateAccessibility(AutomationElement element)
    {
        try
        {
            var processId = element.Current.ProcessId;
            return ActivateAccessibility(processId);
        }
        catch
        {
            return false;
        }
    }

    /// <summary>
    /// Aktywuje IAccessible2 przez sondowanie interfejsu COM
    /// </summary>
    private bool ActivateIAccessible2(IntPtr hwnd)
    {
        IntPtr ptrAccObj = IntPtr.Zero;
        IntPtr ptrServiceProvider = IntPtr.Zero;
        IntPtr ptrAcc2 = IntPtr.Zero;

        try
        {
            // Pobierz IAccessible z okna
            int hr = NativeMethods.AccessibleObjectFromWindow(
                hwnd,
                ObjectIds.OBJID_CLIENT,
                IAccessible2Guids.IID_IAccessible.ToByteArray(),
                out ptrAccObj);

            if (hr != 0 || ptrAccObj == IntPtr.Zero)
            {
                Console.WriteLine($"AccessibilityModelManager: AccessibleObjectFromWindow zwrócił {hr}");
                return false;
            }

            // Spróbuj uzyskać IServiceProvider
            var serviceProviderGuid = IAccessible2Guids.IID_IServiceProvider;
            hr = Marshal.QueryInterface(ptrAccObj, ref serviceProviderGuid, out ptrServiceProvider);

            if (hr != 0 || ptrServiceProvider == IntPtr.Zero)
            {
                Console.WriteLine($"AccessibilityModelManager: QueryInterface dla IServiceProvider zwrócił {hr}");
                return false;
            }

            // Pobierz IServiceProvider
            var serviceProvider = (IServiceProvider)Marshal.GetTypedObjectForIUnknown(
                ptrServiceProvider, typeof(IServiceProvider));

            // Zapytaj o IAccessible2
            var iid_ia2 = IAccessible2Guids.IID_IAccessible2;
            hr = serviceProvider.QueryService(ref iid_ia2, ref iid_ia2, out ptrAcc2);

            if (hr == 0 && ptrAcc2 != IntPtr.Zero)
            {
                Console.WriteLine("AccessibilityModelManager: IAccessible2 dostępny");
                return true;
            }

            Console.WriteLine($"AccessibilityModelManager: QueryService dla IAccessible2 zwrócił {hr}");
            return false;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"AccessibilityModelManager: Wyjątek: {ex.Message}");
            return false;
        }
        finally
        {
            // Zwolnij zasoby COM
            if (ptrAcc2 != IntPtr.Zero)
                Marshal.Release(ptrAcc2);
            if (ptrServiceProvider != IntPtr.Zero)
                Marshal.Release(ptrServiceProvider);
            if (ptrAccObj != IntPtr.Zero)
                Marshal.Release(ptrAccObj);
        }
    }

    /// <summary>
    /// Pobiera aktualny model dostępności dla procesu
    /// </summary>
    public AccessibilityModel GetModelForProcess(int processId)
    {
        lock (_lock)
        {
            return _processModels.TryGetValue(processId, out var model) ? model : AccessibilityModel.Unknown;
        }
    }

    /// <summary>
    /// Sprawdza czy IAccessible2 jest dostępny dla okna
    /// </summary>
    public bool IsIAccessible2Available(IntPtr hwnd)
    {
        IntPtr ptrAccObj = IntPtr.Zero;
        IntPtr ptrServiceProvider = IntPtr.Zero;
        IntPtr ptrAcc2 = IntPtr.Zero;

        try
        {
            int hr = NativeMethods.AccessibleObjectFromWindow(
                hwnd,
                ObjectIds.OBJID_CLIENT,
                IAccessible2Guids.IID_IAccessible.ToByteArray(),
                out ptrAccObj);

            if (hr != 0 || ptrAccObj == IntPtr.Zero)
                return false;

            var serviceProviderGuid = IAccessible2Guids.IID_IServiceProvider;
            hr = Marshal.QueryInterface(ptrAccObj, ref serviceProviderGuid, out ptrServiceProvider);

            if (hr != 0 || ptrServiceProvider == IntPtr.Zero)
                return false;

            var serviceProvider = (IServiceProvider)Marshal.GetTypedObjectForIUnknown(
                ptrServiceProvider, typeof(IServiceProvider));

            var iid_ia2 = IAccessible2Guids.IID_IAccessible2;
            hr = serviceProvider.QueryService(ref iid_ia2, ref iid_ia2, out ptrAcc2);

            return hr == 0 && ptrAcc2 != IntPtr.Zero;
        }
        catch
        {
            return false;
        }
        finally
        {
            if (ptrAcc2 != IntPtr.Zero)
                Marshal.Release(ptrAcc2);
            if (ptrServiceProvider != IntPtr.Zero)
                Marshal.Release(ptrServiceProvider);
            if (ptrAccObj != IntPtr.Zero)
                Marshal.Release(ptrAccObj);
        }
    }

    /// <summary>
    /// Znajduje okno Chrome Widget w procesie Chromium
    /// (zawartość strony jest w Chrome_RenderWidgetHostHWND)
    /// </summary>
    public IntPtr FindChromeWidgetWindow(IntPtr mainWindow)
    {
        IntPtr result = IntPtr.Zero;

        NativeMethods.EnumChildWindows(mainWindow, (hwnd, lParam) =>
        {
            var className = new StringBuilder(256);
            NativeMethods.GetClassName(hwnd, className, 256);
            var name = className.ToString();

            // Chrome używa Chrome_RenderWidgetHostHWND dla treści strony
            if (name == "Chrome_RenderWidgetHostHWND")
            {
                result = hwnd;
                return false; // Zatrzymaj enumerację
            }

            // Edge używa tej samej klasy (bazuje na Chromium)
            if (name.Contains("RenderWidgetHost"))
            {
                result = hwnd;
                return false;
            }

            return true; // Kontynuuj
        }, IntPtr.Zero);

        return result;
    }

    /// <summary>
    /// Aktywuje dostępność dla okna z treścią strony
    /// </summary>
    public bool ActivateContentWindow(IntPtr mainWindow)
    {
        var contentWindow = FindChromeWidgetWindow(mainWindow);
        if (contentWindow != IntPtr.Zero)
        {
            Console.WriteLine($"AccessibilityModelManager: Znaleziono okno treści: {contentWindow}");
            return ActivateIAccessible2(contentWindow);
        }

        // Fallback - użyj głównego okna
        return ActivateIAccessible2(mainWindow);
    }

    /// <summary>
    /// Czyści informacje o zakończonym procesie
    /// </summary>
    public void ProcessExited(int processId)
    {
        lock (_lock)
        {
            _processModels.Remove(processId);
            _activatedProcesses.Remove(processId);
        }
    }

    public void Dispose()
    {
        if (_disposed)
            return;

        lock (_lock)
        {
            _processModels.Clear();
            _activatedProcesses.Clear();
        }

        _disposed = true;
    }
}
