using System.Runtime.InteropServices;

namespace ScreenReader.Interop;

/// <summary>
/// Definicje COM dla IAccessible2
/// Używane do aktywacji trybu dostępności w przeglądarkach Chromium (Chrome, Edge)
/// </summary>

// GUIDs dla interfejsów
internal static class IAccessible2Guids
{
    // IAccessible (MSAA)
    public static readonly Guid IID_IAccessible = new("618736e0-3c3d-11cf-810c-00aa00389b71");

    // IServiceProvider
    public static readonly Guid IID_IServiceProvider = new("6d5140c1-7436-11ce-8034-00aa006009fa");

    // IAccessible2
    public static readonly Guid IID_IAccessible2 = new("E89F726E-C4F4-4c19-BB19-B647D7FA8478");

    // IAccessible2_2
    public static readonly Guid IID_IAccessible2_2 = new("6C9430E9-299D-4E6F-BD01-A82A1E88D3FF");

    // UIA Unique ID Property (dla konwersji IA2 <-> UIA)
    public static readonly Guid UIA_UniqueIdPropertyId = new("cc7eeb32-4b62-4f4c-aff6-1c2e5752ad8e");
}

/// <summary>
/// IServiceProvider - używany do pobierania IAccessible2
/// </summary>
[ComImport]
[Guid("6d5140c1-7436-11ce-8034-00aa006009fa")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IServiceProvider
{
    [PreserveSig]
    int QueryService(
        ref Guid guidService,
        ref Guid riid,
        out IntPtr ppvObject);
}

/// <summary>
/// IAccessible2 - rozszerzony interfejs dostępności
/// </summary>
[ComImport]
[Guid("E89F726E-C4F4-4c19-BB19-B647D7FA8478")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IAccessible2
{
    // Metody odziedziczone z IAccessible (MSAA) - muszą być tutaj
    void SkipIAccessibleMethods(); // Placeholder - w praktyce trzeba zadeklarować wszystkie metody

    // IAccessible2 specific methods
    [PreserveSig]
    int get_nRelations(out int nRelations);

    [PreserveSig]
    int get_relation(int relationIndex, out IntPtr relation);

    [PreserveSig]
    int get_relations(int maxRelations, [MarshalAs(UnmanagedType.LPArray)] IntPtr[] relations, out int nRelations);

    [PreserveSig]
    int role(out int role);

    [PreserveSig]
    int scrollTo(int scrollType);

    [PreserveSig]
    int scrollToPoint(int coordinateType, int x, int y);

    [PreserveSig]
    int get_groupPosition(out int groupLevel, out int similarItemsInGroup, out int positionInGroup);

    [PreserveSig]
    int get_states(out int states);

    [PreserveSig]
    int get_extendedRole([MarshalAs(UnmanagedType.BStr)] out string extendedRole);

    [PreserveSig]
    int get_localizedExtendedRole([MarshalAs(UnmanagedType.BStr)] out string localizedExtendedRole);

    [PreserveSig]
    int get_nExtendedStates(out int nExtendedStates);

    [PreserveSig]
    int get_extendedStates(int maxExtendedStates, [MarshalAs(UnmanagedType.LPArray)] IntPtr[] extendedStates, out int nExtendedStates);

    [PreserveSig]
    int get_localizedExtendedStates(int maxLocalizedExtendedStates, [MarshalAs(UnmanagedType.LPArray)] IntPtr[] localizedExtendedStates, out int nLocalizedExtendedStates);

    [PreserveSig]
    int get_uniqueID(out int uniqueID);

    [PreserveSig]
    int get_windowHandle(out IntPtr windowHandle);

    [PreserveSig]
    int get_indexInParent(out int indexInParent);

    [PreserveSig]
    int get_locale(out IntPtr locale);

    [PreserveSig]
    int get_attributes([MarshalAs(UnmanagedType.BStr)] out string attributes);
}

/// <summary>
/// Stałe dla OBJECT_ID
/// </summary>
internal static class ObjectIds
{
    public const int OBJID_CLIENT = unchecked((int)0xFFFFFFFC);
    public const int OBJID_WINDOW = 0;
    public const int OBJID_SYSMENU = unchecked((int)0xFFFFFFFF);
    public const int OBJID_TITLEBAR = unchecked((int)0xFFFFFFFE);
    public const int OBJID_MENU = unchecked((int)0xFFFFFFFD);
}

/// <summary>
/// Natywne funkcje Windows
/// </summary>
internal static class NativeMethods
{
    [DllImport("oleacc.dll")]
    public static extern int AccessibleObjectFromWindow(
        IntPtr hwnd,
        int dwObjectId,
        [In] byte[] riid,
        out IntPtr ppvObject);

    [DllImport("oleacc.dll")]
    public static extern int AccessibleObjectFromEvent(
        IntPtr hwnd,
        int dwObjectId,
        int dwChildId,
        out IntPtr ppacc,
        out object pvarChild);

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    public static extern int GetWindowThreadProcessId(IntPtr hwnd, out int processId);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr FindWindowEx(
        IntPtr hwndParent,
        IntPtr hwndChildAfter,
        string lpszClass,
        string? lpszWindow);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetClassName(IntPtr hwnd, System.Text.StringBuilder lpClassName, int nMaxCount);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool EnumChildWindows(
        IntPtr hwndParent,
        EnumWindowsProc lpEnumFunc,
        IntPtr lParam);

    public delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);
}
