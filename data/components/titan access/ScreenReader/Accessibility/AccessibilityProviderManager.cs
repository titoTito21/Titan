using System.Windows.Automation;

namespace ScreenReader.Accessibility;

/// <summary>
/// Zarządza dostawcami technologii dostępnościowych
/// Port z NVDA - pozwala na przełączanie między różnymi API
/// </summary>
public class AccessibilityProviderManager : IDisposable
{
    private readonly Dictionary<AccessibilityAPI, IAccessibilityProvider> _providers = new();
    private AccessibilityAPI _enabledApis = AccessibilityAPI.UIAutomation;
    private AccessibilityAPI _preferredApi = AccessibilityAPI.UIAutomation;
    private bool _disposed;
    private bool _autoSwitchEnabled = true;
    private string? _lastProcessName;

    /// <summary>
    /// Mapowanie procesów na preferowane API
    /// </summary>
    private static readonly Dictionary<string, AccessibilityAPI> ProcessApiMap = new(StringComparer.OrdinalIgnoreCase)
    {
        // Firefox/Thunderbird - IAccessible2
        { "firefox", AccessibilityAPI.IAccessible2 },
        { "thunderbird", AccessibilityAPI.IAccessible2 },
        { "waterfox", AccessibilityAPI.IAccessible2 },
        { "librewolf", AccessibilityAPI.IAccessible2 },

        // LibreOffice - IAccessible2
        { "soffice", AccessibilityAPI.IAccessible2 },
        { "swriter", AccessibilityAPI.IAccessible2 },
        { "scalc", AccessibilityAPI.IAccessible2 },
        { "simpress", AccessibilityAPI.IAccessible2 },

        // Java aplikacje - Java Access Bridge
        { "java", AccessibilityAPI.JavaAccessBridge },
        { "javaw", AccessibilityAPI.JavaAccessBridge },
        { "eclipse", AccessibilityAPI.JavaAccessBridge },
        { "idea64", AccessibilityAPI.JavaAccessBridge },
        { "idea", AccessibilityAPI.JavaAccessBridge },
        { "studio64", AccessibilityAPI.JavaAccessBridge },
        { "netbeans64", AccessibilityAPI.JavaAccessBridge },

        // Chromium - UI Automation (nowoczesne)
        { "chrome", AccessibilityAPI.UIAutomation },
        { "msedge", AccessibilityAPI.UIAutomation },
        { "brave", AccessibilityAPI.UIAutomation },
        { "vivaldi", AccessibilityAPI.UIAutomation },
        { "opera", AccessibilityAPI.UIAutomation },

        // Terminale - UI Automation (Windows Terminal) lub MSAA (cmd)
        { "WindowsTerminal", AccessibilityAPI.UIAutomation },
        { "cmd", AccessibilityAPI.MSAA },
        { "powershell", AccessibilityAPI.MSAA },
        { "pwsh", AccessibilityAPI.UIAutomation },
        { "conhost", AccessibilityAPI.MSAA },

        // Starsze aplikacje Win32 - MSAA
        { "notepad", AccessibilityAPI.UIAutomation },
        { "mspaint", AccessibilityAPI.MSAA },
        { "wordpad", AccessibilityAPI.MSAA },
    };

    /// <summary>
    /// Czy automatyczne przełączanie API jest włączone
    /// </summary>
    public bool AutoSwitchEnabled
    {
        get => _autoSwitchEnabled;
        set
        {
            _autoSwitchEnabled = value;
            Console.WriteLine($"AccessibilityProviderManager: Automatyczne przełączanie API {(value ? "włączone" : "wyłączone")}");
        }
    }

    /// <summary>
    /// Aktualnie włączone API
    /// </summary>
    public AccessibilityAPI EnabledApis => _enabledApis;

    /// <summary>
    /// Preferowane API (używane jako pierwsze)
    /// </summary>
    public AccessibilityAPI PreferredApi
    {
        get => _preferredApi;
        set
        {
            _preferredApi = value;
            Console.WriteLine($"AccessibilityProviderManager: Preferowane API zmienione na {value.GetPolishName()}");
        }
    }

    /// <summary>
    /// Event wywoływany przy zmianie fokusu
    /// </summary>
    public event EventHandler<AccessibleObject>? FocusChanged;

    /// <summary>
    /// Event wywoływany przy zmianie API
    /// </summary>
    public event EventHandler<AccessibilityAPI>? ApiChanged;

    public AccessibilityProviderManager()
    {
        RegisterDefaultProviders();
    }

    /// <summary>
    /// Rejestruje domyślnych providerów
    /// </summary>
    private void RegisterDefaultProviders()
    {
        // UI Automation - zawsze dostępne
        RegisterProvider(new UIAutomationProvider());

        // MSAA
        RegisterProvider(new MSAAProvider());

        // IAccessible2 (dla Firefox, LibreOffice)
        RegisterProvider(new IAccessible2Provider());

        // Java Access Bridge
        RegisterProvider(new JavaAccessBridgeProvider());

        Console.WriteLine($"AccessibilityProviderManager: Zarejestrowano {_providers.Count} providerów");
    }

    /// <summary>
    /// Rejestruje providera
    /// </summary>
    public void RegisterProvider(IAccessibilityProvider provider)
    {
        if (!_providers.ContainsKey(provider.ApiType))
        {
            _providers[provider.ApiType] = provider;

            // Podłącz eventy
            provider.FocusChanged += OnProviderFocusChanged;

            Console.WriteLine($"AccessibilityProviderManager: Zarejestrowano provider {provider.ApiType.GetPolishName()}");
        }
    }

    /// <summary>
    /// Inicjalizuje wszystkich włączonych providerów
    /// </summary>
    public void Initialize()
    {
        foreach (var kvp in _providers)
        {
            if (_enabledApis.HasFlag(kvp.Key))
            {
                try
                {
                    if (kvp.Value.IsAvailable && kvp.Value.Initialize())
                    {
                        Console.WriteLine($"AccessibilityProviderManager: Zainicjalizowano {kvp.Key.GetPolishName()}");
                    }
                    else
                    {
                        Console.WriteLine($"AccessibilityProviderManager: {kvp.Key.GetPolishName()} niedostępny");
                    }
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"AccessibilityProviderManager: Błąd inicjalizacji {kvp.Key.GetPolishName()}: {ex.Message}");
                }
            }
        }
    }

    /// <summary>
    /// Włącza/wyłącza API
    /// </summary>
    public void SetApiEnabled(AccessibilityAPI api, bool enabled)
    {
        if (enabled)
        {
            _enabledApis |= api;
            if (_providers.TryGetValue(api, out var provider) && provider.IsAvailable)
            {
                provider.Initialize();
                provider.StartEventListening();
            }
        }
        else
        {
            _enabledApis &= ~api;
            if (_providers.TryGetValue(api, out var provider))
            {
                provider.StopEventListening();
            }
        }

        Console.WriteLine($"AccessibilityProviderManager: {api.GetPolishName()} {(enabled ? "włączone" : "wyłączone")}");
        ApiChanged?.Invoke(this, _enabledApis);
    }

    /// <summary>
    /// Przełącza API na następne dostępne
    /// </summary>
    public string CyclePreferredApi()
    {
        var apis = new[] { AccessibilityAPI.UIAutomation, AccessibilityAPI.MSAA, AccessibilityAPI.IAccessible2, AccessibilityAPI.JavaAccessBridge };
        int currentIndex = Array.IndexOf(apis, _preferredApi);
        int nextIndex = (currentIndex + 1) % apis.Length;

        // Znajdź następne dostępne API
        for (int i = 0; i < apis.Length; i++)
        {
            int idx = (nextIndex + i) % apis.Length;
            if (_providers.TryGetValue(apis[idx], out var provider) && provider.IsAvailable)
            {
                PreferredApi = apis[idx];
                return $"Preferowane API: {PreferredApi.GetPolishName()}";
            }
        }

        return "Brak dostępnych API";
    }

    /// <summary>
    /// Automatycznie wybiera najlepsze API dla procesu
    /// </summary>
    /// <param name="processName">Nazwa procesu</param>
    /// <returns>True jeśli API zostało zmienione</returns>
    public bool AutoSelectApiForProcess(string? processName)
    {
        if (!_autoSwitchEnabled || string.IsNullOrEmpty(processName))
            return false;

        // Unikaj ponownego przełączania dla tego samego procesu
        if (string.Equals(_lastProcessName, processName, StringComparison.OrdinalIgnoreCase))
            return false;

        _lastProcessName = processName;

        // Znajdź preferowane API dla procesu
        AccessibilityAPI targetApi = AccessibilityAPI.UIAutomation; // domyślne

        if (ProcessApiMap.TryGetValue(processName, out var mappedApi))
        {
            targetApi = mappedApi;
        }
        else
        {
            // Spróbuj dopasować częściowo (np. "eclipse" w "eclipse.exe")
            foreach (var kvp in ProcessApiMap)
            {
                if (processName.Contains(kvp.Key, StringComparison.OrdinalIgnoreCase))
                {
                    targetApi = kvp.Value;
                    break;
                }
            }
        }

        // Sprawdź czy API jest dostępne
        if (_providers.TryGetValue(targetApi, out var provider) && provider.IsAvailable)
        {
            if (_preferredApi != targetApi)
            {
                var oldApi = _preferredApi;
                PreferredApi = targetApi;

                // Włącz API jeśli nie jest włączone
                if (!_enabledApis.HasFlag(targetApi))
                {
                    SetApiEnabled(targetApi, true);
                }

                Console.WriteLine($"AccessibilityProviderManager: Automatycznie przełączono z {oldApi.GetPolishName()} na {targetApi.GetPolishName()} dla procesu {processName}");
                return true;
            }
        }
        else
        {
            // Fallback do UIAutomation jeśli preferowane API niedostępne
            if (_preferredApi != AccessibilityAPI.UIAutomation)
            {
                PreferredApi = AccessibilityAPI.UIAutomation;
                Console.WriteLine($"AccessibilityProviderManager: Fallback do UI Automation dla procesu {processName}");
                return true;
            }
        }

        return false;
    }

    /// <summary>
    /// Pobiera sugerowane API dla procesu (bez przełączania)
    /// </summary>
    public AccessibilityAPI GetSuggestedApiForProcess(string? processName)
    {
        if (string.IsNullOrEmpty(processName))
            return AccessibilityAPI.UIAutomation;

        if (ProcessApiMap.TryGetValue(processName, out var api))
            return api;

        foreach (var kvp in ProcessApiMap)
        {
            if (processName.Contains(kvp.Key, StringComparison.OrdinalIgnoreCase))
                return kvp.Value;
        }

        return AccessibilityAPI.UIAutomation;
    }

    /// <summary>
    /// Rejestruje niestandardowe mapowanie procesu na API
    /// </summary>
    public void RegisterProcessApiMapping(string processName, AccessibilityAPI api)
    {
        ProcessApiMap[processName] = api;
        Console.WriteLine($"AccessibilityProviderManager: Zarejestrowano {processName} -> {api.GetPolishName()}");
    }

    /// <summary>
    /// Pobiera obiekt z fokusem używając najlepszego dostępnego API
    /// </summary>
    public AccessibleObject? GetFocusedObject()
    {
        // Spróbuj najpierw preferowanego API
        if (_providers.TryGetValue(_preferredApi, out var preferredProvider) && preferredProvider.IsActive)
        {
            var obj = preferredProvider.GetFocusedObject();
            if (obj != null)
                return obj;
        }

        // Spróbuj innych włączonych API
        foreach (var kvp in _providers)
        {
            if (kvp.Key != _preferredApi && _enabledApis.HasFlag(kvp.Key) && kvp.Value.IsActive)
            {
                var obj = kvp.Value.GetFocusedObject();
                if (obj != null)
                    return obj;
            }
        }

        return null;
    }

    /// <summary>
    /// Pobiera obiekt pod punktem ekranu
    /// </summary>
    public AccessibleObject? GetObjectFromPoint(int x, int y)
    {
        // Preferowane API pierwsze
        if (_providers.TryGetValue(_preferredApi, out var preferredProvider) && preferredProvider.IsActive)
        {
            var obj = preferredProvider.GetObjectFromPoint(x, y);
            if (obj != null)
                return obj;
        }

        // Inne API
        foreach (var kvp in _providers)
        {
            if (kvp.Key != _preferredApi && _enabledApis.HasFlag(kvp.Key) && kvp.Value.IsActive)
            {
                var obj = kvp.Value.GetObjectFromPoint(x, y);
                if (obj != null)
                    return obj;
            }
        }

        return null;
    }

    /// <summary>
    /// Pobiera najlepszy obiekt dla elementu UIA
    /// </summary>
    public AccessibleObject? GetAccessibleObject(AutomationElement element)
    {
        // Sprawdź każde API w kolejności preferencji
        if (_providers.TryGetValue(_preferredApi, out var preferredProvider) && preferredProvider.IsActive)
        {
            if (preferredProvider.SupportsElement(element))
            {
                var obj = preferredProvider.GetAccessibleObject(element);
                if (obj != null)
                    return obj;
            }
        }

        // Spróbuj innych API
        foreach (var kvp in _providers)
        {
            if (kvp.Key != _preferredApi && _enabledApis.HasFlag(kvp.Key) && kvp.Value.IsActive)
            {
                if (kvp.Value.SupportsElement(element))
                {
                    var obj = kvp.Value.GetAccessibleObject(element);
                    if (obj != null)
                        return obj;
                }
            }
        }

        return null;
    }

    /// <summary>
    /// Pobiera provider dla danego API
    /// </summary>
    public IAccessibilityProvider? GetProvider(AccessibilityAPI api)
    {
        return _providers.TryGetValue(api, out var provider) ? provider : null;
    }

    /// <summary>
    /// Pobiera listę dostępnych API
    /// </summary>
    public IEnumerable<(AccessibilityAPI Api, bool IsAvailable, bool IsEnabled)> GetAvailableApis()
    {
        foreach (var kvp in _providers)
        {
            yield return (kvp.Key, kvp.Value.IsAvailable, _enabledApis.HasFlag(kvp.Key));
        }
    }

    /// <summary>
    /// Rozpoczyna nasłuchiwanie zdarzeń wszystkich włączonych providerów
    /// </summary>
    public void StartEventListening()
    {
        foreach (var kvp in _providers)
        {
            if (_enabledApis.HasFlag(kvp.Key) && kvp.Value.IsActive)
            {
                kvp.Value.StartEventListening();
            }
        }
    }

    /// <summary>
    /// Zatrzymuje nasłuchiwanie zdarzeń
    /// </summary>
    public void StopEventListening()
    {
        foreach (var provider in _providers.Values)
        {
            provider.StopEventListening();
        }
    }

    private void OnProviderFocusChanged(object? sender, AccessibleObject obj)
    {
        FocusChanged?.Invoke(this, obj);
    }

    public void Dispose()
    {
        if (_disposed)
            return;

        StopEventListening();

        foreach (var provider in _providers.Values)
        {
            provider.Dispose();
        }

        _providers.Clear();
        _disposed = true;
    }
}
