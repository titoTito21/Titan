using System.Windows.Automation;

namespace ScreenReader.Accessibility;

/// <summary>
/// Interfejs dla dostawców technologii dostępnościowych
/// Port z NVDA - pozwala na ujednolicony dostęp do różnych API
/// </summary>
public interface IAccessibilityProvider : IDisposable
{
    /// <summary>
    /// Typ API obsługiwany przez tego providera
    /// </summary>
    AccessibilityAPI ApiType { get; }

    /// <summary>
    /// Czy provider jest aktualnie aktywny
    /// </summary>
    bool IsActive { get; }

    /// <summary>
    /// Czy provider jest dostępny w systemie
    /// </summary>
    bool IsAvailable { get; }

    /// <summary>
    /// Inicjalizuje providera
    /// </summary>
    bool Initialize();

    /// <summary>
    /// Pobiera element z fokusem
    /// </summary>
    AccessibleObject? GetFocusedObject();

    /// <summary>
    /// Pobiera element pod punktem ekranu
    /// </summary>
    AccessibleObject? GetObjectFromPoint(int x, int y);

    /// <summary>
    /// Pobiera obiekt dla danego uchwytu okna
    /// </summary>
    AccessibleObject? GetObjectFromHandle(IntPtr hwnd);

    /// <summary>
    /// Sprawdza czy provider obsługuje dany element
    /// </summary>
    bool SupportsElement(AutomationElement element);

    /// <summary>
    /// Pobiera rozszerzony obiekt dla elementu UIA
    /// </summary>
    AccessibleObject? GetAccessibleObject(AutomationElement element);

    /// <summary>
    /// Rozpoczyna nasłuchiwanie zdarzeń
    /// </summary>
    void StartEventListening();

    /// <summary>
    /// Zatrzymuje nasłuchiwanie zdarzeń
    /// </summary>
    void StopEventListening();

    /// <summary>
    /// Event wywoływany przy zmianie fokusu
    /// </summary>
    event EventHandler<AccessibleObject>? FocusChanged;

    /// <summary>
    /// Event wywoływany przy zmianie właściwości obiektu
    /// </summary>
    event EventHandler<AccessiblePropertyChangedEventArgs>? PropertyChanged;

    /// <summary>
    /// Event wywoływany przy zmianie struktury (dodanie/usunięcie dzieci)
    /// </summary>
    event EventHandler<AccessibleStructureChangedEventArgs>? StructureChanged;
}

/// <summary>
/// Argumenty zdarzenia zmiany właściwości
/// </summary>
public class AccessiblePropertyChangedEventArgs : EventArgs
{
    public AccessibleObject Object { get; }
    public string PropertyName { get; }
    public object? OldValue { get; }
    public object? NewValue { get; }

    public AccessiblePropertyChangedEventArgs(AccessibleObject obj, string propertyName, object? oldValue, object? newValue)
    {
        Object = obj;
        PropertyName = propertyName;
        OldValue = oldValue;
        NewValue = newValue;
    }
}

/// <summary>
/// Argumenty zdarzenia zmiany struktury
/// </summary>
public class AccessibleStructureChangedEventArgs : EventArgs
{
    public AccessibleObject Parent { get; }
    public StructureChangeType ChangeType { get; }
    public int[] ChildIds { get; }

    public AccessibleStructureChangedEventArgs(AccessibleObject parent, StructureChangeType changeType, int[] childIds)
    {
        Parent = parent;
        ChangeType = changeType;
        ChildIds = childIds;
    }
}

/// <summary>
/// Typ zmiany struktury
/// </summary>
public enum StructureChangeType
{
    ChildAdded,
    ChildRemoved,
    ChildrenInvalidated,
    ChildrenBulkAdded,
    ChildrenBulkRemoved,
    ChildrenReordered
}
