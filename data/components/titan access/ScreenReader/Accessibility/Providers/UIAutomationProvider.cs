using System.Windows.Automation;

namespace ScreenReader.Accessibility;

/// <summary>
/// Provider dla Microsoft UI Automation
/// Obsługuje: UWP, WPF, nowoczesne aplikacje Win32
/// </summary>
public class UIAutomationProvider : IAccessibilityProvider
{
    private bool _isActive;
    private bool _disposed;
    private bool _isListening;
    private readonly AutomationFocusChangedEventHandler _focusHandler;

    public AccessibilityAPI ApiType => AccessibilityAPI.UIAutomation;
    public bool IsActive => _isActive;
    public bool IsAvailable => true; // UI Automation jest zawsze dostępne w Windows

    public UIAutomationProvider()
    {
        // Tworzymy handler w konstruktorze, żeby uniknąć problemów z GC i podwójnym dodawaniem
        _focusHandler = OnFocusChangedEvent;
    }

    public event EventHandler<AccessibleObject>? FocusChanged;
#pragma warning disable CS0067 // Events required by IAccessibilityProvider interface
    public event EventHandler<AccessiblePropertyChangedEventArgs>? PropertyChanged;
    public event EventHandler<AccessibleStructureChangedEventArgs>? StructureChanged;
#pragma warning restore CS0067

    public bool Initialize()
    {
        // Zabezpieczenie przed podwójnym wywołaniem
        if (_isActive)
            return true;

        try
        {
            // Sprawdź czy możemy pobrać root element
            var root = AutomationElement.RootElement;
            if (root != null)
            {
                _isActive = true;
                Console.WriteLine("UIAutomationProvider: Zainicjalizowano pomyślnie");
                return true;
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"UIAutomationProvider: Błąd inicjalizacji: {ex.Message}");
        }

        return false;
    }

    public AccessibleObject? GetFocusedObject()
    {
        try
        {
            var focused = AutomationElement.FocusedElement;
            if (focused != null)
            {
                return CreateAccessibleObject(focused);
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"UIAutomationProvider: Błąd pobierania fokusu: {ex.Message}");
        }

        return null;
    }

    public AccessibleObject? GetObjectFromPoint(int x, int y)
    {
        try
        {
            // Użyj API Win32 aby znaleźć okno pod punktem, a potem UIAutomation
            IntPtr hwnd = WindowFromPoint(new POINT { X = x, Y = y });
            if (hwnd != IntPtr.Zero)
            {
                var element = AutomationElement.FromHandle(hwnd);
                if (element != null)
                {
                    return CreateAccessibleObject(element);
                }
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"UIAutomationProvider: Błąd FromPoint: {ex.Message}");
        }

        return null;
    }

    [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
    private struct POINT { public int X; public int Y; }

    [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
    private struct RECT { public int Left; public int Top; public int Right; public int Bottom; }

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern IntPtr WindowFromPoint(POINT point);

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern bool GetWindowRect(IntPtr hwnd, out RECT rect);

    public AccessibleObject? GetObjectFromHandle(IntPtr hwnd)
    {
        try
        {
            var element = AutomationElement.FromHandle(hwnd);
            if (element != null)
            {
                return CreateAccessibleObject(element);
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"UIAutomationProvider: Błąd FromHandle: {ex.Message}");
        }

        return null;
    }

    public bool SupportsElement(AutomationElement element)
    {
        // UI Automation wspiera wszystkie elementy
        return element != null;
    }

    public AccessibleObject? GetAccessibleObject(AutomationElement element)
    {
        return CreateAccessibleObject(element);
    }

    public void StartEventListening()
    {
        // Zabezpieczenie przed podwójnym wywołaniem
        if (_isListening)
            return;

        try
        {
            Automation.AddAutomationFocusChangedEventHandler(_focusHandler);
            _isListening = true;
            Console.WriteLine("UIAutomationProvider: Rozpoczęto nasłuchiwanie zdarzeń");
        }
        catch (Exception ex)
        {
            Console.WriteLine($"UIAutomationProvider: Błąd nasłuchiwania: {ex.Message}");
        }
    }

    public void StopEventListening()
    {
        if (!_isListening)
            return;

        try
        {
            Automation.RemoveAutomationFocusChangedEventHandler(_focusHandler);
            _isListening = false;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"UIAutomationProvider: Błąd zatrzymania nasłuchiwania: {ex.Message}");
        }
    }

    private void OnFocusChangedEvent(object sender, AutomationFocusChangedEventArgs e)
    {
        try
        {
            if (sender is AutomationElement element)
            {
                var obj = CreateAccessibleObject(element);
                if (obj != null)
                {
                    FocusChanged?.Invoke(this, obj);
                }
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"UIAutomationProvider: Błąd obsługi zdarzenia: {ex.Message}");
        }
    }

    /// <summary>
    /// Tworzy AccessibleObject z elementu UI Automation
    /// </summary>
    private AccessibleObject? CreateAccessibleObject(AutomationElement element)
    {
        try
        {
            var obj = new UIAAccessibleObject(element)
            {
                SourceApi = AccessibilityAPI.UIAutomation,
                UIAElement = element,
                Name = GetSafeString(element, e => e.Current.Name),
                Description = GetSafeString(element, e => e.Current.HelpText),
                WindowHandle = new IntPtr(element.Current.NativeWindowHandle),
                ProcessId = element.Current.ProcessId,
                Role = MapControlTypeToRole(element.Current.ControlType),
                States = GetStates(element)
            };

            // Pobierz wartość
            if (element.TryGetCurrentPattern(ValuePattern.Pattern, out var valuePattern))
            {
                obj.Value = ((ValuePattern)valuePattern).Current.Value ?? "";
            }

            // Pobierz pozycję przez uchwyt okna
            try
            {
                int hwndInt = element.Current.NativeWindowHandle;
                if (hwndInt != 0)
                {
                    if (GetWindowRect(new IntPtr(hwndInt), out RECT rect))
                    {
                        obj.BoundingRectangle = new System.Drawing.Rectangle(
                            rect.Left, rect.Top, rect.Right - rect.Left, rect.Bottom - rect.Top);
                    }
                }
            }
            catch { }

            return obj;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"UIAutomationProvider: Błąd tworzenia obiektu: {ex.Message}");
            return null;
        }
    }

    private string GetSafeString(AutomationElement element, Func<AutomationElement, string> getter)
    {
        try
        {
            return getter(element) ?? "";
        }
        catch
        {
            return "";
        }
    }

    private AccessibleRole MapControlTypeToRole(ControlType controlType)
    {
        if (controlType == ControlType.Button) return AccessibleRole.PushButton;
        if (controlType == ControlType.Calendar) return AccessibleRole.Graphic;
        if (controlType == ControlType.CheckBox) return AccessibleRole.CheckButton;
        if (controlType == ControlType.ComboBox) return AccessibleRole.ComboBox;
        if (controlType == ControlType.Custom) return AccessibleRole.Pane;
        if (controlType == ControlType.DataGrid) return AccessibleRole.Table;
        if (controlType == ControlType.DataItem) return AccessibleRole.ListItem;
        if (controlType == ControlType.Document) return AccessibleRole.Document;
        if (controlType == ControlType.Edit) return AccessibleRole.Edit;
        if (controlType == ControlType.Group) return AccessibleRole.Grouping;
        if (controlType == ControlType.Header) return AccessibleRole.Header;
        if (controlType == ControlType.HeaderItem) return AccessibleRole.HeaderItem;
        if (controlType == ControlType.Hyperlink) return AccessibleRole.Link;
        if (controlType == ControlType.Image) return AccessibleRole.Graphic;
        if (controlType == ControlType.List) return AccessibleRole.List;
        if (controlType == ControlType.ListItem) return AccessibleRole.ListItem;
        if (controlType == ControlType.Menu) return AccessibleRole.MenuPopup;
        if (controlType == ControlType.MenuBar) return AccessibleRole.MenuBar;
        if (controlType == ControlType.MenuItem) return AccessibleRole.MenuItem;
        if (controlType == ControlType.Pane) return AccessibleRole.Pane;
        if (controlType == ControlType.ProgressBar) return AccessibleRole.ProgressBar;
        if (controlType == ControlType.RadioButton) return AccessibleRole.RadioButton;
        if (controlType == ControlType.ScrollBar) return AccessibleRole.ScrollBar;
        if (controlType == ControlType.Separator) return AccessibleRole.Separator;
        if (controlType == ControlType.Slider) return AccessibleRole.Slider;
        if (controlType == ControlType.Spinner) return AccessibleRole.SpinButton;
        if (controlType == ControlType.SplitButton) return AccessibleRole.SplitButton;
        if (controlType == ControlType.StatusBar) return AccessibleRole.StatusBar;
        if (controlType == ControlType.Tab) return AccessibleRole.PageTabList;
        if (controlType == ControlType.TabItem) return AccessibleRole.PageTab;
        if (controlType == ControlType.Table) return AccessibleRole.Table;
        if (controlType == ControlType.Text) return AccessibleRole.StaticText;
        if (controlType == ControlType.Thumb) return AccessibleRole.Indicator;
        if (controlType == ControlType.TitleBar) return AccessibleRole.TitleBar;
        if (controlType == ControlType.ToolBar) return AccessibleRole.ToolBar;
        if (controlType == ControlType.ToolTip) return AccessibleRole.Tooltip;
        if (controlType == ControlType.Tree) return AccessibleRole.TreeView;
        if (controlType == ControlType.TreeItem) return AccessibleRole.TreeViewItem;
        if (controlType == ControlType.Window) return AccessibleRole.Window;

        return AccessibleRole.Pane;
    }

    private AccessibleStates GetStates(AutomationElement element)
    {
        var states = AccessibleStates.None;

        try
        {
            if (!element.Current.IsEnabled)
                states |= AccessibleStates.Unavailable;
            if (element.Current.HasKeyboardFocus)
                states |= AccessibleStates.Focused;
            if (element.Current.IsKeyboardFocusable)
                states |= AccessibleStates.Focusable;
            if (element.Current.IsOffscreen)
                states |= AccessibleStates.Offscreen;

            // Toggle state
            if (element.TryGetCurrentPattern(TogglePattern.Pattern, out var togglePattern))
            {
                var toggle = (TogglePattern)togglePattern;
                if (toggle.Current.ToggleState == ToggleState.On)
                    states |= AccessibleStates.Checked;
                else if (toggle.Current.ToggleState == ToggleState.Indeterminate)
                    states |= AccessibleStates.Mixed;
            }

            // Expand/collapse state
            if (element.TryGetCurrentPattern(ExpandCollapsePattern.Pattern, out var expandPattern))
            {
                var expand = (ExpandCollapsePattern)expandPattern;
                if (expand.Current.ExpandCollapseState == ExpandCollapseState.Expanded)
                    states |= AccessibleStates.Expanded;
                else if (expand.Current.ExpandCollapseState == ExpandCollapseState.Collapsed)
                    states |= AccessibleStates.Collapsed;
            }

            // Selection state
            if (element.TryGetCurrentPattern(SelectionItemPattern.Pattern, out var selPattern))
            {
                var sel = (SelectionItemPattern)selPattern;
                if (sel.Current.IsSelected)
                    states |= AccessibleStates.Selected;
            }
        }
        catch { }

        return states;
    }

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
/// AccessibleObject specyficzny dla UI Automation
/// </summary>
public class UIAAccessibleObject : AccessibleObject
{
    public UIAAccessibleObject(AutomationElement element)
    {
        UIAElement = element;
    }

    public override AccessibleObject? GetParent()
    {
        try
        {
            var parent = TreeWalker.ControlViewWalker.GetParent(UIAElement);
            if (parent != null)
            {
                return new UIAAccessibleObject(parent)
                {
                    SourceApi = AccessibilityAPI.UIAutomation,
                    Name = parent.Current.Name,
                    Role = MapRole(parent.Current.ControlType)
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
            var child = TreeWalker.ControlViewWalker.GetFirstChild(UIAElement);
            while (child != null)
            {
                children.Add(new UIAAccessibleObject(child)
                {
                    SourceApi = AccessibilityAPI.UIAutomation,
                    Name = child.Current.Name,
                    Role = MapRole(child.Current.ControlType)
                });
                child = TreeWalker.ControlViewWalker.GetNextSibling(child);
            }
        }
        catch { }

        return children;
    }

    public override AccessibleObject? GetNextSibling()
    {
        try
        {
            var next = TreeWalker.ControlViewWalker.GetNextSibling(UIAElement);
            if (next != null)
            {
                return new UIAAccessibleObject(next)
                {
                    SourceApi = AccessibilityAPI.UIAutomation,
                    Name = next.Current.Name,
                    Role = MapRole(next.Current.ControlType)
                };
            }
        }
        catch { }
        return null;
    }

    public override AccessibleObject? GetPreviousSibling()
    {
        try
        {
            var prev = TreeWalker.ControlViewWalker.GetPreviousSibling(UIAElement);
            if (prev != null)
            {
                return new UIAAccessibleObject(prev)
                {
                    SourceApi = AccessibilityAPI.UIAutomation,
                    Name = prev.Current.Name,
                    Role = MapRole(prev.Current.ControlType)
                };
            }
        }
        catch { }
        return null;
    }

    private AccessibleRole MapRole(ControlType controlType)
    {
        if (controlType == ControlType.Button) return AccessibleRole.PushButton;
        if (controlType == ControlType.Edit) return AccessibleRole.Edit;
        if (controlType == ControlType.List) return AccessibleRole.List;
        if (controlType == ControlType.ListItem) return AccessibleRole.ListItem;
        if (controlType == ControlType.Document) return AccessibleRole.Document;
        if (controlType == ControlType.Window) return AccessibleRole.Window;
        return AccessibleRole.Pane;
    }
}
