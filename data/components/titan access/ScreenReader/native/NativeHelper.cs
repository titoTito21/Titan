using System.Runtime.InteropServices;

namespace ScreenReader.Native;

/// <summary>
/// Zarządzana fasada nad ScreenReaderHelper.dll - natywnym komponentem C++,
/// który posiada całą niskopoziomową warstwę czytnika:
///   - globalne hooki klawiatury i myszy (WH_KEYBOARD_LL / WH_MOUSE_LL),
///   - hook zmiany aktywnego okna (SetWinEventHook),
///   - syntezę wejścia (SendInput),
///   - pomocnicze operacje na oknach i kursorze.
///
/// Hooki działają na dedykowanym wątku natywnym z własną pętlą komunikatów,
/// więc ich opóźnienie nie zależy od pauz GC ani od pętli WinForms.
/// Callbacki są wywoływane na tym wątku natywnym - kod zarządzany musi być
/// odporny na wielowątkowość (KeyboardHookManager i VirtualScreenManager już są).
///
/// Ta klasa musi pozostawać zsynchronizowana z native/ScreenReaderHelper/include/srhelper.h.
/// </summary>
public static class NativeHelper
{
    private const string Dll = "ScreenReaderHelper.dll";

    public enum MouseButton { Left = 0, Right = 1, Middle = 2 }

    // Publiczne typy callbacków używane przez managery (zwracają bool zamiast int).
    public delegate bool KeyboardHookCallback(int vkCode, int scanCode, int flags, bool isKeyDown);
    public delegate bool MouseHookCallback(int message, int x, int y, int mouseData);
    public delegate void WinEventHookCallback(uint eventType, IntPtr hwnd, int idObject, int idChild);

    // ---- natywne sygnatury callbacków (zgodne z srhelper.h) -----------------

    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    private delegate int NativeKeyboardCallback(int vkCode, int scanCode, int flags, int isKeyDown);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    private delegate int NativeMouseCallback(int message, int x, int y, int mouseData);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    private delegate void NativeWinEventCallback(uint eventType, IntPtr hwnd, int idObject, int idChild);

    // Trwałe referencje - bez nich GC zwolniłby delegaty, a natywny kod
    // wywołałby zwolniony wskaźnik.
    private static NativeKeyboardCallback? _kbThunk;
    private static NativeMouseCallback? _mouseThunk;
    private static KeyboardHookCallback? _kbManaged;
    private static MouseHookCallback? _mouseManaged;

    // WinEvent: można mieć wiele hooków naraz (jeden na zmiany aktywnego okna,
    // jeden na live-region itd.). Trzymamy thunki żywe pod kluczem hookId,
    // dopóki hook nie zostanie odinstalowany.
    private sealed record WinEventReg(NativeWinEventCallback Thunk, WinEventHookCallback Managed);
    private static readonly Dictionary<int, WinEventReg> _winHooks = new();

    private static bool _initialized;
    private static readonly object _lock = new();

    /// <summary>Czy natywny helper został pomyślnie zainicjalizowany.</summary>
    public static bool IsAvailable => _initialized;

    /// <summary>
    /// Uruchamia natywny wątek hooków. Idempotentne. Zwraca false, jeśli DLL
    /// nie został znaleziony lub wątek się nie wystartował.
    /// </summary>
    public static bool Initialize()
    {
        lock (_lock)
        {
            if (_initialized)
                return true;
            try
            {
                if (SrhInitialize() != 0)
                {
                    _initialized = true;
                    Console.WriteLine($"NativeHelper: ScreenReaderHelper.dll v{SrhGetVersion()} zainicjalizowany");
                    return true;
                }
                Console.WriteLine("NativeHelper: SrhInitialize zwrócił 0 - wątek hooków nie wystartował");
                return false;
            }
            catch (DllNotFoundException)
            {
                Console.WriteLine($"NativeHelper: BŁĄD - nie znaleziono {Dll} obok pliku exe");
                return false;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"NativeHelper: BŁĄD inicjalizacji: {ex.Message}");
                return false;
            }
        }
    }

    public static void Shutdown()
    {
        lock (_lock)
        {
            if (!_initialized)
                return;
            try { SrhShutdown(); }
            catch (Exception ex) { Console.WriteLine($"NativeHelper.Shutdown: {ex.Message}"); }
            _kbThunk = null;
            _mouseThunk = null;
            _kbManaged = null;
            _mouseManaged = null;
            _winHooks.Clear();
            _initialized = false;
        }
    }

    // ---- hook klawiatury ---------------------------------------------------

    public static bool InstallKeyboardHook(KeyboardHookCallback callback)
    {
        if (!_initialized && !Initialize())
            return false;
        _kbManaged = callback;
        _kbThunk = (vk, scan, flags, isDown) =>
        {
            try { return _kbManaged != null && _kbManaged(vk, scan, flags, isDown != 0) ? 1 : 0; }
            catch (Exception ex) { Console.WriteLine($"NativeHelper kb callback: {ex.Message}"); return 0; }
        };
        return SrhKeyboardHookInstall(_kbThunk) != 0;
    }

    public static void UninstallKeyboardHook()
    {
        if (!_initialized) return;
        SrhKeyboardHookUninstall();
        _kbThunk = null;
        _kbManaged = null;
    }

    // ---- hook myszy --------------------------------------------------------

    public static bool InstallMouseHook(MouseHookCallback callback)
    {
        if (!_initialized && !Initialize())
            return false;
        _mouseManaged = callback;
        _mouseThunk = (msg, x, y, data) =>
        {
            try { return _mouseManaged != null && _mouseManaged(msg, x, y, data) ? 1 : 0; }
            catch (Exception ex) { Console.WriteLine($"NativeHelper mouse callback: {ex.Message}"); return 0; }
        };
        return SrhMouseHookInstall(_mouseThunk) != 0;
    }

    public static void UninstallMouseHook()
    {
        if (!_initialized) return;
        SrhMouseHookUninstall();
        _mouseThunk = null;
        _mouseManaged = null;
    }

    // ---- hooki WinEvent (zmiana okna, live-region itd.) -------------------

    /// <summary>
    /// Instaluje hook WinEvent dla zakresu zdarzeń [eventMin, eventMax].
    /// Zwraca identyfikator hooka (>= 1) lub 0 przy niepowodzeniu. Identyfikator
    /// należy przekazać do <see cref="UninstallWinEventHook"/>.
    /// </summary>
    public static int InstallWinEventHook(WinEventHookCallback callback, uint eventMin, uint eventMax)
    {
        if (!_initialized && !Initialize())
            return 0;

        NativeWinEventCallback thunk = (evt, hwnd, idObject, idChild) =>
        {
            try { callback(evt, hwnd, idObject, idChild); }
            catch (Exception ex) { Console.WriteLine($"NativeHelper winevent callback: {ex.Message}"); }
        };

        int hookId = SrhWinEventHookInstall(thunk, eventMin, eventMax);
        if (hookId != 0)
        {
            lock (_lock)
                _winHooks[hookId] = new WinEventReg(thunk, callback);
        }
        return hookId;
    }

    /// <summary>
    /// Instaluje hook WinEvent dla pojedynczego typu zdarzenia.
    /// </summary>
    public static int InstallWinEventHook(WinEventHookCallback callback, uint eventType)
        => InstallWinEventHook(callback, eventType, eventType);

    public static void UninstallWinEventHook(int hookId)
    {
        if (!_initialized || hookId == 0) return;
        SrhWinEventHookUninstall(hookId);
        lock (_lock)
            _winHooks.Remove(hookId);
    }

    // ---- model wyświetlania GDI -------------------------------------------

    /// <summary>
    /// Uruchamia model wyświetlania GDI: wstrzykuje srremote.dll do procesów
    /// graficznych, która hookuje ExtTextOutW i zapisuje tekst ekranowy do
    /// pamięci współdzielonej. Zwraca false, jeśli nie udało się uruchomić.
    /// </summary>
    public static bool StartDisplayModel()
    {
        if (!_initialized && !Initialize())
            return false;
        try { return SrhDisplayModelStart() != 0; }
        catch (Exception ex)
        {
            Console.WriteLine($"NativeHelper.StartDisplayModel: {ex.Message}");
            return false;
        }
    }

    /// <summary>Zatrzymuje model wyświetlania GDI. Idempotentne.</summary>
    public static void StopDisplayModel()
    {
        if (!_initialized) return;
        try { SrhDisplayModelStop(); }
        catch (Exception ex) { Console.WriteLine($"NativeHelper.StopDisplayModel: {ex.Message}"); }
    }

    /// <summary>
    /// Zwraca tekst ekranowy zarejestrowany dla danego okna - uporządkowany
    /// z góry na dół i z lewej do prawej, sklejony znakami nowej linii.
    /// Pusty łańcuch, jeśli dla procesu okna nic nie zarejestrowano.
    /// </summary>
    public static string GetDisplayModelText(IntPtr hwnd)
    {
        if (!_initialized || hwnd == IntPtr.Zero)
            return string.Empty;
        try
        {
            var buf = new char[8192];
            int len = SrhDisplayModelGetText(hwnd, buf, buf.Length);
            return len > 0 ? new string(buf, 0, len) : string.Empty;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"NativeHelper.GetDisplayModelText: {ex.Message}");
            return string.Empty;
        }
    }

    // ---- synteza wejścia ---------------------------------------------------

    public static void SendKey(ushort vk, bool down) => SrhSendKey(vk, down ? 1 : 0);

    public static void SendKeyCombo(params ushort[] vks)
    {
        if (vks is { Length: > 0 })
            SrhSendKeyCombo(vks, vks.Length);
    }

    public static void SendUnicode(char ch) => SrhSendUnicode(ch);

    public static void MouseMove(int x, int y) => SrhMouseMove(x, y);

    public static void MouseClick(MouseButton button, bool isDouble = false)
        => SrhMouseClick((int)button, isDouble ? 1 : 0);

    public static bool SetCursorPos(int x, int y) => SrhSetCursorPos(x, y) != 0;

    public static bool GetCursorPos(out int x, out int y)
    {
        int ok = SrhGetCursorPos(out x, out y);
        return ok != 0;
    }

    public static bool IsKeyPressed(int vk) => SrhIsKeyPressed(vk) != 0;

    // ---- okna / kursor -----------------------------------------------------

    public static IntPtr GetForegroundWindow() => SrhGetForegroundWindow();

    public static string GetWindowProcessName(IntPtr hwnd)
    {
        if (hwnd == IntPtr.Zero)
            return string.Empty;
        var buf = new char[64];
        int len = SrhGetWindowProcessName(hwnd, buf, buf.Length);
        return len > 0 ? new string(buf, 0, len) : string.Empty;
    }

    public static bool GetWindowRect(IntPtr hwnd, out int left, out int top, out int right, out int bottom)
        => SrhGetWindowRect(hwnd, out left, out top, out right, out bottom) != 0;

    public static bool IsWindowMaximized(IntPtr hwnd) => SrhIsWindowMaximized(hwnd) != 0;
    public static bool MaximizeWindow(IntPtr hwnd) => SrhMaximizeWindow(hwnd) != 0;
    public static bool RestoreWindow(IntPtr hwnd) => SrhRestoreWindow(hwnd) != 0;

    public static void ClipCursorToWindow(IntPtr hwnd) => SrhClipCursorToWindow(hwnd);
    public static void ClipCursorClear() => SrhClipCursorClear();

    // ---- P/Invoke (zgodne z srhelper.h) ------------------------------------

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern int SrhInitialize();
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern void SrhShutdown();
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern int SrhGetVersion();

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern int SrhKeyboardHookInstall(NativeKeyboardCallback cb);
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern void SrhKeyboardHookUninstall();
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern int SrhMouseHookInstall(NativeMouseCallback cb);
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern void SrhMouseHookUninstall();
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern int SrhWinEventHookInstall(NativeWinEventCallback cb, uint eventMin, uint eventMax);
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern void SrhWinEventHookUninstall(int hookId);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern void SrhSendKey(ushort vk, int down);
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern void SrhSendKeyCombo(ushort[] vks, int count);
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern void SrhSendUnicode(ushort ch);
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern void SrhMouseMove(int x, int y);
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern void SrhMouseClick(int button, int isDouble);
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern int SrhSetCursorPos(int x, int y);
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern int SrhGetCursorPos(out int x, out int y);
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern int SrhIsKeyPressed(int vk);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern IntPtr SrhGetForegroundWindow();
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, CharSet = CharSet.Unicode)]
    private static extern int SrhGetWindowProcessName(IntPtr hwnd, char[] buf, int bufLen);
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern int SrhGetWindowRect(IntPtr hwnd, out int left, out int top, out int right, out int bottom);
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern int SrhIsWindowMaximized(IntPtr hwnd);
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern int SrhMaximizeWindow(IntPtr hwnd);
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern int SrhRestoreWindow(IntPtr hwnd);
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern void SrhClipCursorToWindow(IntPtr hwnd);
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern void SrhClipCursorClear();

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern int SrhDisplayModelStart();
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)]
    private static extern void SrhDisplayModelStop();
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, CharSet = CharSet.Unicode)]
    private static extern int SrhDisplayModelGetText(IntPtr hwnd, char[] buf, int bufLen);
}
