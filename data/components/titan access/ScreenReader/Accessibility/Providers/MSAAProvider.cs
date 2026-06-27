using System.Runtime.InteropServices;
using System.Windows.Automation;
using Accessibility;

namespace ScreenReader.Accessibility;

/// <summary>
/// Provider dla Microsoft Active Accessibility (MSAA)
/// Obsługuje: starsze aplikacje Win32
/// Port z NVDA IAccessibleHandler
/// </summary>
public class MSAAProvider : IAccessibilityProvider
{
    private bool _isActive;
    private bool _disposed;
    private IntPtr _eventHook;
    private bool _isListening;

    public AccessibilityAPI ApiType => AccessibilityAPI.MSAA;
    public bool IsActive => _isActive;
    public bool IsAvailable => true; // MSAA jest dostępne we wszystkich wersjach Windows

#pragma warning disable CS0067 // Events required by IAccessibilityProvider interface
    public event EventHandler<AccessibleObject>? FocusChanged;
    public event EventHandler<AccessiblePropertyChangedEventArgs>? PropertyChanged;
    public event EventHandler<AccessibleStructureChangedEventArgs>? StructureChanged;
#pragma warning restore CS0067

    // MSAA Constants
    private const uint EVENT_OBJECT_FOCUS = 0x8005;
    private const uint EVENT_OBJECT_STATECHANGE = 0x800A;
    private const uint EVENT_OBJECT_NAMECHANGE = 0x800C;
    private const uint EVENT_OBJECT_VALUECHANGE = 0x800E;
    private const uint WINEVENT_OUTOFCONTEXT = 0x0000;
    private const int CHILDID_SELF = 0;

    private delegate void WinEventDelegate(IntPtr hWinEventHook, uint eventType,
        IntPtr hwnd, int idObject, int idChild, uint dwEventThread, uint dwmsEventTime);

    // WAŻNE: Delegat musi być przechowywany jako pole klasy aby uniknąć GC
    private readonly WinEventDelegate _eventDelegate;

    public MSAAProvider()
    {
        // Tworzymy delegat w konstruktorze, żeby GC go nie zebrał
        _eventDelegate = OnWinEvent;
    }

    [DllImport("user32.dll")]
    private static extern IntPtr SetWinEventHook(uint eventMin, uint eventMax, IntPtr hmodWinEventProc,
        WinEventDelegate lpfnWinEventProc, uint idProcess, uint idThread, uint dwFlags);

    [DllImport("user32.dll")]
    private static extern bool UnhookWinEvent(IntPtr hWinEventHook);

    [DllImport("oleacc.dll")]
    private static extern int AccessibleObjectFromWindow(IntPtr hwnd, uint dwId,
        ref Guid riid, [MarshalAs(UnmanagedType.IUnknown)] out object ppvObject);

    [DllImport("oleacc.dll")]
    private static extern int AccessibleObjectFromPoint(System.Drawing.Point pt,
        [MarshalAs(UnmanagedType.IUnknown)] out object ppacc, out object pvarChild);

    [DllImport("oleacc.dll")]
    private static extern int AccessibleObjectFromEvent(IntPtr hwnd, int dwObjectId, int dwChildId,
        [MarshalAs(UnmanagedType.IUnknown)] out object ppacc, out object pvarChild);

    private static Guid IID_IAccessible = new Guid("618736E0-3C3D-11CF-810C-00AA00389B71");

    public bool Initialize()
    {
        // Zabezpieczenie przed podwójnym wywołaniem
        if (_isActive)
            return true;

        try
        {
            _isActive = true;
            Console.WriteLine("MSAAProvider: Zainicjalizowano pomyślnie");
            return true;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"MSAAProvider: Błąd inicjalizacji: {ex.Message}");
            return false;
        }
    }

    public AccessibleObject? GetFocusedObject()
    {
        try
        {
            // Pobierz okno z fokusem
            IntPtr hwnd = GetForegroundWindow();
            if (hwnd == IntPtr.Zero)
                return null;

            // Pobierz IAccessible dla okna
            if (AccessibleObjectFromWindow(hwnd, 0, ref IID_IAccessible, out var acc) == 0)
            {
                if (acc is IAccessible iacc)
                {
                    return CreateAccessibleObject(iacc, hwnd, CHILDID_SELF);
                }
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"MSAAProvider: Błąd pobierania fokusu: {ex.Message}");
        }

        return null;
    }

    public AccessibleObject? GetObjectFromPoint(int x, int y)
    {
        try
        {
            var pt = new System.Drawing.Point(x, y);
            if (AccessibleObjectFromPoint(pt, out var acc, out var child) == 0)
            {
                if (acc is IAccessible iacc)
                {
                    int childId = child is int id ? id : CHILDID_SELF;
                    return CreateAccessibleObject(iacc, IntPtr.Zero, childId);
                }
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"MSAAProvider: Błąd FromPoint: {ex.Message}");
        }

        return null;
    }

    public AccessibleObject? GetObjectFromHandle(IntPtr hwnd)
    {
        try
        {
            Guid iid = IID_IAccessible;
            if (AccessibleObjectFromWindow(hwnd, 0, ref iid, out var acc) == 0)
            {
                if (acc is IAccessible iacc)
                {
                    return CreateAccessibleObject(iacc, hwnd, CHILDID_SELF);
                }
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"MSAAProvider: Błąd FromHandle: {ex.Message}");
        }

        return null;
    }

    public bool SupportsElement(AutomationElement element)
    {
        // MSAA wspiera elementy z uchwytem okna
        try
        {
            return element.Current.NativeWindowHandle != 0;
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
            if (hwnd != IntPtr.Zero)
            {
                return GetObjectFromHandle(hwnd);
            }
        }
        catch { }

        return null;
    }

    public void StartEventListening()
    {
        // Zabezpieczenie przed podwójnym wywołaniem
        if (_isListening)
            return;

        try
        {
            _eventHook = SetWinEventHook(EVENT_OBJECT_FOCUS, EVENT_OBJECT_VALUECHANGE,
                IntPtr.Zero, _eventDelegate, 0, 0, WINEVENT_OUTOFCONTEXT);

            if (_eventHook != IntPtr.Zero)
            {
                _isListening = true;
                Console.WriteLine("MSAAProvider: Rozpoczęto nasłuchiwanie zdarzeń");
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"MSAAProvider: Błąd nasłuchiwania: {ex.Message}");
        }
    }

    public void StopEventListening()
    {
        if (!_isListening)
            return;

        try
        {
            if (_eventHook != IntPtr.Zero)
            {
                UnhookWinEvent(_eventHook);
                _eventHook = IntPtr.Zero;
            }
            _isListening = false;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"MSAAProvider: Błąd zatrzymania nasłuchiwania: {ex.Message}");
        }
    }

    private void OnWinEvent(IntPtr hWinEventHook, uint eventType,
        IntPtr hwnd, int idObject, int idChild, uint dwEventThread, uint dwmsEventTime)
    {
        try
        {
            if (eventType == EVENT_OBJECT_FOCUS)
            {
                if (AccessibleObjectFromEvent(hwnd, idObject, idChild, out var acc, out _) == 0)
                {
                    if (acc is IAccessible iacc)
                    {
                        var obj = CreateAccessibleObject(iacc, hwnd, idChild);
                        if (obj != null)
                        {
                            FocusChanged?.Invoke(this, obj);
                        }
                    }
                }
            }
        }
        catch { }
    }

    private AccessibleObject? CreateAccessibleObject(IAccessible acc, IntPtr hwnd, int childId)
    {
        try
        {
            var obj = new MSAAAccessibleObject(acc, childId)
            {
                SourceApi = AccessibilityAPI.MSAA,
                WindowHandle = hwnd,
                ChildId = childId
            };

            // Pobierz właściwości
            try { obj.Name = acc.get_accName(childId) ?? ""; } catch { }
            try { obj.Description = acc.get_accDescription(childId) ?? ""; } catch { }
            try { obj.Value = acc.get_accValue(childId) ?? ""; } catch { }
            try { obj.HelpText = acc.get_accHelp(childId) ?? ""; } catch { }
            try { obj.KeyboardShortcut = acc.get_accKeyboardShortcut(childId) ?? ""; } catch { }

            // Rola
            try
            {
                var roleObj = acc.get_accRole(childId);
                if (roleObj is int roleInt)
                {
                    obj.Role = MapMSAARoleToAccessibleRole(roleInt);
                }
            }
            catch { }

            // Stany
            try
            {
                var stateObj = acc.get_accState(childId);
                if (stateObj is int stateInt)
                {
                    obj.States = MapMSAAStatesToAccessibleStates(stateInt);
                }
            }
            catch { }

            // Pozycja
            try
            {
                acc.accLocation(out int left, out int top, out int width, out int height, childId);
                obj.BoundingRectangle = new System.Drawing.Rectangle(left, top, width, height);
            }
            catch { }

            return obj;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"MSAAProvider: Błąd tworzenia obiektu: {ex.Message}");
            return null;
        }
    }

    private AccessibleRole MapMSAARoleToAccessibleRole(int msaaRole)
    {
        // Mapowanie ról MSAA na AccessibleRole
        return msaaRole switch
        {
            0x01 => AccessibleRole.TitleBar,
            0x02 => AccessibleRole.MenuBar,
            0x03 => AccessibleRole.ScrollBar,
            0x04 => AccessibleRole.Grip,
            0x05 => AccessibleRole.Sound,
            0x06 => AccessibleRole.Cursor,
            0x07 => AccessibleRole.Caret,
            0x08 => AccessibleRole.Alert,
            0x09 => AccessibleRole.Window,
            0x0A => AccessibleRole.Client,
            0x0B => AccessibleRole.MenuPopup,
            0x0C => AccessibleRole.MenuItem,
            0x0D => AccessibleRole.Tooltip,
            0x0E => AccessibleRole.Application,
            0x0F => AccessibleRole.Document,
            0x10 => AccessibleRole.Pane,
            0x11 => AccessibleRole.Chart,
            0x12 => AccessibleRole.Dialog,
            0x13 => AccessibleRole.Border,
            0x14 => AccessibleRole.Grouping,
            0x15 => AccessibleRole.Separator,
            0x16 => AccessibleRole.ToolBar,
            0x17 => AccessibleRole.StatusBar,
            0x18 => AccessibleRole.Table,
            0x19 => AccessibleRole.ColumnHeader,
            0x1A => AccessibleRole.RowHeader,
            0x1B => AccessibleRole.Column,
            0x1C => AccessibleRole.Row,
            0x1D => AccessibleRole.Cell,
            0x1E => AccessibleRole.Link,
            0x1F => AccessibleRole.HelpBalloon,
            0x20 => AccessibleRole.Character,
            0x21 => AccessibleRole.List,
            0x22 => AccessibleRole.ListItem,
            0x23 => AccessibleRole.Outline,
            0x24 => AccessibleRole.OutlineItem,
            0x25 => AccessibleRole.PageTab,
            0x26 => AccessibleRole.PropertyPage,
            0x27 => AccessibleRole.Indicator,
            0x28 => AccessibleRole.Graphic,
            0x29 => AccessibleRole.StaticText,
            0x2A => AccessibleRole.Text,
            0x2B => AccessibleRole.PushButton,
            0x2C => AccessibleRole.CheckButton,
            0x2D => AccessibleRole.RadioButton,
            0x2E => AccessibleRole.ComboBox,
            0x2F => AccessibleRole.DropList,
            0x30 => AccessibleRole.ProgressBar,
            0x31 => AccessibleRole.Dial,
            0x32 => AccessibleRole.HotkeyField,
            0x33 => AccessibleRole.Slider,
            0x34 => AccessibleRole.SpinButton,
            0x35 => AccessibleRole.Diagram,
            0x36 => AccessibleRole.Animation,
            0x37 => AccessibleRole.Equation,
            0x38 => AccessibleRole.ButtonDropDown,
            0x39 => AccessibleRole.ButtonMenu,
            0x3A => AccessibleRole.ButtonDropDownGrid,
            0x3B => AccessibleRole.WhiteSpace,
            0x3C => AccessibleRole.PageTabList,
            0x3D => AccessibleRole.Clock,
            0x3E => AccessibleRole.SplitButton,
            0x3F => AccessibleRole.IpAddress,
            0x40 => AccessibleRole.OutlineButton,
            _ => AccessibleRole.Pane
        };
    }

    private AccessibleStates MapMSAAStatesToAccessibleStates(int msaaStates)
    {
        var states = AccessibleStates.None;

        if ((msaaStates & 0x0001) != 0) states |= AccessibleStates.Unavailable;
        if ((msaaStates & 0x0002) != 0) states |= AccessibleStates.Selected;
        if ((msaaStates & 0x0004) != 0) states |= AccessibleStates.Focused;
        if ((msaaStates & 0x0008) != 0) states |= AccessibleStates.Pressed;
        if ((msaaStates & 0x0010) != 0) states |= AccessibleStates.Checked;
        if ((msaaStates & 0x0020) != 0) states |= AccessibleStates.Mixed;
        if ((msaaStates & 0x0040) != 0) states |= AccessibleStates.Indeterminate;
        if ((msaaStates & 0x0080) != 0) states |= AccessibleStates.ReadOnly;
        if ((msaaStates & 0x0100) != 0) states |= AccessibleStates.HotTracked;
        if ((msaaStates & 0x0200) != 0) states |= AccessibleStates.Default;
        if ((msaaStates & 0x0400) != 0) states |= AccessibleStates.Expanded;
        if ((msaaStates & 0x0800) != 0) states |= AccessibleStates.Collapsed;
        if ((msaaStates & 0x1000) != 0) states |= AccessibleStates.Busy;
        if ((msaaStates & 0x2000) != 0) states |= AccessibleStates.Floating;
        if ((msaaStates & 0x4000) != 0) states |= AccessibleStates.Marqueed;
        if ((msaaStates & 0x8000) != 0) states |= AccessibleStates.Animated;
        if ((msaaStates & 0x10000) != 0) states |= AccessibleStates.Invisible;
        if ((msaaStates & 0x20000) != 0) states |= AccessibleStates.Offscreen;
        if ((msaaStates & 0x40000) != 0) states |= AccessibleStates.Sizeable;
        if ((msaaStates & 0x80000) != 0) states |= AccessibleStates.Moveable;
        if ((msaaStates & 0x100000) != 0) states |= AccessibleStates.SelfVoicing;
        if ((msaaStates & 0x200000) != 0) states |= AccessibleStates.Focusable;
        if ((msaaStates & 0x400000) != 0) states |= AccessibleStates.Selectable;
        if ((msaaStates & 0x800000) != 0) states |= AccessibleStates.Linked;
        if ((msaaStates & 0x1000000) != 0) states |= AccessibleStates.Traversed;
        if ((msaaStates & 0x2000000) != 0) states |= AccessibleStates.Multiselectable;
        if ((msaaStates & 0x4000000) != 0) states |= AccessibleStates.ExtSelectable;
        if ((msaaStates & 0x10000000) != 0) states |= AccessibleStates.AlertLow;
        if ((msaaStates & 0x20000000) != 0) states |= AccessibleStates.AlertMedium;
        if ((msaaStates & 0x40000000) != 0) states |= AccessibleStates.AlertHigh;
        if ((msaaStates & unchecked((int)0x80000000)) != 0) states |= AccessibleStates.Protected;

        return states;
    }

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

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
/// AccessibleObject specyficzny dla MSAA
/// </summary>
public class MSAAAccessibleObject : AccessibleObject
{
    private readonly IAccessible _accessible;
    private readonly int _childId;

    public MSAAAccessibleObject(IAccessible accessible, int childId)
    {
        _accessible = accessible;
        _childId = childId;
        NativeObject = accessible;
    }

    public override AccessibleObject? GetParent()
    {
        try
        {
            var parent = _accessible.accParent as IAccessible;
            if (parent != null)
            {
                return new MSAAAccessibleObject(parent, 0)
                {
                    SourceApi = AccessibilityAPI.MSAA
                };
            }
        }
        catch { }
        return null;
    }

    public override IEnumerable<AccessibleObject> GetChildren()
    {
        var children = new List<AccessibleObject>();

        try
        {
            int childCount = _accessible.accChildCount;
            if (childCount > 0)
            {
                // Pobierz dzieci przez accNavigate lub iterację
                for (int i = 1; i <= childCount; i++)
                {
                    try
                    {
                        var child = _accessible.get_accChild(i);
                        if (child is IAccessible childAcc)
                        {
                            children.Add(new MSAAAccessibleObject(childAcc, 0)
                            {
                                SourceApi = AccessibilityAPI.MSAA
                            });
                        }
                    }
                    catch { }
                }
            }
        }
        catch { }

        return children;
    }

    public override bool DoDefaultAction()
    {
        try
        {
            _accessible.accDoDefaultAction(_childId);
            return true;
        }
        catch
        {
            return false;
        }
    }
}
