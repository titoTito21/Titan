using System.Reflection;
using System.Windows.Automation;
using ScreenReader.Speech;

namespace ScreenReader.AppModules;

/// <summary>
/// Menedżer modułów aplikacji (port NVDA appModuleHandler)
///
/// Automatycznie ładuje i zarządza modułami specyficznymi dla aplikacji.
/// Moduły są ładowane dynamicznie gdy wykryta zostanie odpowiednia aplikacja.
/// </summary>
public class AppModuleManager
{
    private readonly Dictionary<string, AppModuleBase> _loadedModules = new();
    private readonly Dictionary<string, Type> _availableModules = new();
    private readonly SpeechManager _speechManager;

    private AppModuleBase? _currentModule;
    private string? _currentProcessName;

    public AppModuleManager(SpeechManager speechManager)
    {
        _speechManager = speechManager;
        DiscoverAppModules();
    }

    /// <summary>
    /// Znajduje wszystkie dostępne moduły w assembly
    /// </summary>
    private void DiscoverAppModules()
    {
        var assembly = Assembly.GetExecutingAssembly();
        var moduleTypes = assembly.GetTypes()
            .Where(t => t.IsClass && !t.IsAbstract && t.IsSubclassOf(typeof(AppModuleBase)));

        foreach (var type in moduleTypes)
        {
            try
            {
                // Utwórz tymczasową instancję aby pobrać ProcessName
                var tempInstance = (AppModuleBase?)Activator.CreateInstance(type);
                if (tempInstance != null)
                {
                    string processName = tempInstance.ProcessName.ToLowerInvariant();
                    _availableModules[processName] = type;
                    Console.WriteLine($"AppModuleManager: Discovered module for '{processName}' ({type.Name})");
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"AppModuleManager: Failed to discover module {type.Name}: {ex.Message}");
            }
        }

        Console.WriteLine($"AppModuleManager: Discovered {_availableModules.Count} app modules");
    }

    /// <summary>
    /// Aktualizuje aktywny moduł na podstawie procesu
    /// </summary>
    /// <param name="processName">Nazwa procesu (bez .exe)</param>
    public void UpdateCurrentProcess(string? processName)
    {
        if (string.IsNullOrEmpty(processName))
            return;

        processName = processName.ToLowerInvariant();

        // Jeśli to ten sam proces, nic nie rób
        if (processName == _currentProcessName)
            return;

        // Dezaktywuj poprzedni moduł
        if (_currentModule != null)
        {
            _currentModule.OnAppLoseFocus();
            Console.WriteLine($"AppModuleManager: Deactivated module for '{_currentProcessName}'");
        }

        _currentProcessName = processName;
        _currentModule = null;

        // Spróbuj załadować moduł dla nowego procesu
        if (_availableModules.TryGetValue(processName, out var moduleType))
        {
            if (!_loadedModules.TryGetValue(processName, out var module))
            {
                // Załaduj nowy moduł
                try
                {
                    module = (AppModuleBase?)Activator.CreateInstance(moduleType);
                    if (module != null)
                    {
                        module.Initialize(_speechManager);
                        _loadedModules[processName] = module;
                        Console.WriteLine($"AppModuleManager: Loaded module for '{processName}' ({moduleType.Name})");
                    }
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"AppModuleManager: Failed to load module for '{processName}': {ex.Message}");
                    return;
                }
            }

            _currentModule = module;
            if (_currentModule != null)
            {
                _currentModule.OnAppGainFocus();
                Console.WriteLine($"AppModuleManager: Activated module for '{processName}'");
            }
        }
    }

    /// <summary>
    /// Pobiera aktywny moduł aplikacji
    /// </summary>
    public AppModuleBase? CurrentModule => _currentModule;

    /// <summary>
    /// Sprawdza czy istnieje moduł dla procesu
    /// </summary>
    public bool HasModuleFor(string processName)
    {
        return _availableModules.ContainsKey(processName.ToLowerInvariant());
    }

    /// <summary>
    /// Pozwala modułowi dostosować opis elementu
    /// </summary>
    public string CustomizeElementDescription(AutomationElement element, string defaultDescription)
    {
        if (_currentModule != null)
        {
            return _currentModule.CustomizeElementDescription(element, defaultDescription);
        }
        return defaultDescription;
    }

    /// <summary>
    /// Wywoływane przed ogłoszeniem elementu
    /// </summary>
    public void BeforeAnnounceElement(AutomationElement element)
    {
        _currentModule?.BeforeAnnounceElement(element);
    }

    /// <summary>
    /// Wywoływane po ogłoszeniu elementu
    /// </summary>
    public void AfterAnnounceElement(AutomationElement element)
    {
        _currentModule?.AfterAnnounceElement(element);
    }

    /// <summary>
    /// Pozwala modułowi obsłużyć niestandardowy opis elementu
    /// </summary>
    public string? OnElementFocus(AutomationElement element)
    {
        return _currentModule?.OnElementFocus(element);
    }

    /// <summary>
    /// Pozwala modułowi obsłużyć gest
    /// </summary>
    public bool HandleGesture(System.Windows.Forms.Keys keys)
    {
        return _currentModule?.HandleGesture(keys) ?? false;
    }

    /// <summary>
    /// Zwalnia wszystkie moduły
    /// </summary>
    public void Dispose()
    {
        foreach (var module in _loadedModules.Values)
        {
            module.Terminate();
        }
        _loadedModules.Clear();
        _currentModule = null;
    }
}
