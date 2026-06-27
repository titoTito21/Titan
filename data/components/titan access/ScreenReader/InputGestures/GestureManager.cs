using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows.Forms;
using ScreenReader.Localization;

namespace ScreenReader.InputGestures;

/// <summary>
/// Zarządza gestami klawiszowymi i ich powiązaniami z akcjami (port NVDA inputCore.py)
/// </summary>
public class GestureManager
{
    private readonly List<GestureBinding> _bindings = new();
    private readonly SpeechManager _speechManager;
    private bool _inputHelpMode = false;

    /// <summary>Event dla przełączania trybu browse/focus (Insert+Space)</summary>
    public event Action? ToggleBrowseMode;
    
    public GestureManager(SpeechManager speechManager)
    {
        _speechManager = speechManager;
        RegisterDefaultGestures();
    }
    
    /// <summary>
    /// Tryb pomocy klawiatury - gdy aktywny, klawisze są ogłaszane zamiast wykonywane
    /// </summary>
    public bool InputHelpMode
    {
        get => _inputHelpMode;
        set
        {
            _inputHelpMode = value;
            _speechManager.Speak(value ? L.T("gesture.inputHelpOn") : L.T("gesture.inputHelpOff"));
        }
    }
    
    /// <summary>
    /// Rejestruje nowy gest
    /// </summary>
    public void RegisterGesture(string gestureId, Keys key, Action action, string displayName, string description = "", string? category = null)
    {
        var binding = new GestureBinding(gestureId, key, action, displayName, description, category ?? L.T("gesture.category.global"));
        _bindings.Add(binding);
        Console.WriteLine($"GestureManager: Zarejestrowano gest {gestureId} - {displayName}");
    }
    
    /// <summary>
    /// Wyrejestrowuje gest
    /// </summary>
    public void UnregisterGesture(string gestureId)
    {
        _bindings.RemoveAll(b => b.GestureId == gestureId);
    }
    
    /// <summary>
    /// Przetwarza naciśnięcie klawisza i wykonuje odpowiednią akcję
    /// </summary>
    /// <returns>True jeśli gest został obsłużony, false jeśli należy przekazać dalej</returns>
    public bool ProcessKeyPress(Keys key, bool ctrl, bool alt, bool shift, bool insert)
    {
        // Znajdź pasujący gest
        var binding = _bindings.FirstOrDefault(b => b.Matches(key, ctrl, alt, shift, insert));
        
        if (binding == null)
            return false;
        
        // W trybie pomocy klawiatury, ogłoś gest zamiast go wykonać
        if (_inputHelpMode)
        {
            string announcement = $"{binding.DisplayName}, {binding.GetReadableGesture()}";
            if (!string.IsNullOrEmpty(binding.Description))
                announcement += $", {binding.Description}";
            
            _speechManager.Speak(announcement);
            return true;
        }
        
        // Wykonaj akcję
        try
        {
            binding.Action?.Invoke();
            return true;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"GestureManager: Błąd wykonania gestu {binding.GestureId}: {ex.Message}");
            _speechManager.Speak(L.T("gesture.commandError"));
            return true;
        }
    }
    
    /// <summary>
    /// Zwraca listę wszystkich zarejestrowanych gestów
    /// </summary>
    public IReadOnlyList<GestureBinding> GetAllGestures()
    {
        return _bindings.AsReadOnly();
    }
    
    /// <summary>
    /// Zwraca gesty dla danej kategorii
    /// </summary>
    public IEnumerable<GestureBinding> GetGesturesByCategory(string category)
    {
        return _bindings.Where(b => b.Category == category);
    }
    
    /// <summary>
    /// Rejestruje domyślne gesty inspirowane NVDA
    /// </summary>
    private void RegisterDefaultGestures()
    {
        // Tryb pomocy klawiatury
        RegisterGesture("insert+1", Keys.D1,
            () => InputHelpMode = !InputHelpMode,
            L.T("gesture.toggleInputHelp.name"),
            L.T("gesture.toggleInputHelp.desc"),
            L.T("gesture.category.system"));

        // Przełączanie trybu browse/focus (Insert+Space)
        RegisterGesture("insert+space", Keys.Space,
            () => ToggleBrowseMode?.Invoke(),
            L.T("gesture.toggleBrowseMode.name"),
            L.T("gesture.toggleBrowseMode.desc"),
            L.T("gesture.category.browse"));

        // Odczyt czasu
        RegisterGesture("insert+f12", Keys.F12,
            () => _speechManager.Speak(DateTime.Now.ToString("HH:mm")),
            L.T("gesture.readTime.name"),
            L.T("gesture.readTime.desc"),
            L.T("gesture.category.info"));

        // Odczyt daty
        RegisterGesture("insert+f12+shift", Keys.F12,
            () => _speechManager.Speak(DateTime.Now.ToString("dddd, d MMMM yyyy", new System.Globalization.CultureInfo(L.T("common.culture")))),
            L.T("gesture.readDate.name"),
            L.T("gesture.readDate.desc"),
            L.T("gesture.category.info"));

        // Nazwa okna
        RegisterGesture("insert+t", Keys.T,
            () => { /* Zostanie zaimplementowane przy integracji */ },
            L.T("gesture.readWindowTitle.name"),
            L.T("gesture.readWindowTitle.desc"),
            L.T("gesture.category.navigation"));

        // Status baterii (przykład)
        RegisterGesture("insert+shift+b", Keys.B,
            () => {
                var powerStatus = SystemInformation.PowerStatus;
                string status = powerStatus.PowerLineStatus == PowerLineStatus.Online ? L.T("gesture.power.ac") : L.T("gesture.power.battery");
                string level = powerStatus.BatteryLifePercent >= 0 ? L.T("gesture.power.percent", (int)(powerStatus.BatteryLifePercent * 100)) : L.T("gesture.power.unknown");
                _speechManager.Speak(L.T("gesture.power.status", status, level));
            },
            L.T("gesture.batteryStatus.name"),
            L.T("gesture.batteryStatus.desc"),
            L.T("gesture.category.info"));
        
        Console.WriteLine($"GestureManager: Zarejestrowano {_bindings.Count} domyślnych gestów");
    }
    
    /// <summary>
    /// Zapisuje konfigurację gestów do pliku
    /// </summary>
    public void SaveConfiguration(string path)
    {
        // TODO: Implementacja zapisu do JSON/XML
    }
    
    /// <summary>
    /// Wczytuje konfigurację gestów z pliku
    /// </summary>
    public void LoadConfiguration(string path)
    {
        // TODO: Implementacja odczytu z JSON/XML
    }
}
