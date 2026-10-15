using System;
using System.Windows.Forms;

namespace ScreenReader.InputGestures;

/// <summary>
/// Reprezentuje powiązanie gestu klawiszowego z akcją (port z NVDA inputCore.py)
/// </summary>
public class GestureBinding
{
    public string GestureId { get; set; }
    public Keys Key { get; set; }
    public bool Ctrl { get; set; }
    public bool Alt { get; set; }
    public bool Shift { get; set; }
    public bool Insert { get; set; }  // Klawisz modyfikatora NVDA (Insert lub CapsLock)
    
    public Action Action { get; set; }
    public string DisplayName { get; set; }
    public string Category { get; set; }
    public string Description { get; set; }
    
    public GestureBinding(string gestureId, Keys key, Action action, string displayName, string description = "", string category = "Globalne")
    {
        GestureId = gestureId;
        Key = key;
        Action = action;
        DisplayName = displayName;
        Description = description;
        Category = category;
        
        // Parsuj gestureId aby określić modyfikatory
        // Format: "insert+t", "ctrl+shift+a", itp.
        ParseGestureId(gestureId);
    }
    
    private void ParseGestureId(string gestureId)
    {
        var parts = gestureId.ToLower().Split('+');
        
        foreach (var part in parts)
        {
            switch (part.Trim())
            {
                case "ctrl":
                case "control":
                    Ctrl = true;
                    break;
                case "alt":
                    Alt = true;
                    break;
                case "shift":
                    Shift = true;
                    break;
                case "insert":
                case "nvda":
                    Insert = true;
                    break;
            }
        }
    }
    
    /// <summary>
    /// Sprawdza czy aktualne naciśnięcie klawisza pasuje do tego gestu
    /// </summary>
    public bool Matches(Keys key, bool ctrl, bool alt, bool shift, bool insert)
    {
        // Usuń modyfikatory z klawisza
        Keys baseKey = key & Keys.KeyCode;
        
        return baseKey == Key &&
               Ctrl == ctrl &&
               Alt == alt &&
               Shift == shift &&
               Insert == insert;
    }
    
    /// <summary>
    /// Zwraca czytelny opis gestu dla użytkownika
    /// </summary>
    public string GetReadableGesture()
    {
        var parts = new List<string>();
        
        if (Insert) parts.Add("Insert");
        if (Ctrl) parts.Add("Ctrl");
        if (Alt) parts.Add("Alt");
        if (Shift) parts.Add("Shift");
        parts.Add(Key.ToString());
        
        return string.Join("+", parts);
    }
    
    public override string ToString()
    {
        return $"{DisplayName} ({GetReadableGesture()})";
    }
}
