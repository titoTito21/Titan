using System.Windows.Automation;
using ScreenReader.Speech;

namespace ScreenReader.AppModules;

/// <summary>
/// Klasa bazowa dla modułów specyficznych dla aplikacji (port NVDA appModuleHandler.AppModule)
///
/// AppModules pozwalają na dostosowanie zachowania screen readera dla konkretnych aplikacji.
/// Każdy moduł jest nazwany po nazwie procesu aplikacji (np. notepad.exe -> NotepadModule.cs).
///
/// Podobnie jak w NVDA, AppModule może:
/// - Przechwytywać i modyfikować zdarzenia fokusa
/// - Dostosowywać ogłaszanie elementów
/// - Dodawać niestandardowe gesty/skróty klawiszowe
/// - Implementować specyficzną logikę dla aplikacji
/// </summary>
public abstract class AppModuleBase
{
    /// <summary>Nazwa procesu obsługiwanego przez ten moduł</summary>
    public abstract string ProcessName { get; }

    /// <summary>Przyjazna nazwa aplikacji</summary>
    public virtual string AppName => ProcessName;

    /// <summary>Czy moduł jest aktualnie aktywny</summary>
    public bool IsActive { get; internal set; }

    /// <summary>Menedżer mowy do ogłaszania</summary>
    protected SpeechManager? Speech { get; private set; }

    /// <summary>
    /// Inicjalizuje moduł (wywoływane przy pierwszym uruchomieniu aplikacji)
    /// </summary>
    public virtual void Initialize(SpeechManager speechManager)
    {
        Speech = speechManager;
        IsActive = true;
    }

    /// <summary>
    /// Wywoływane gdy aplikacja otrzymuje fokus (staje się aktywna)
    /// </summary>
    public virtual void OnAppGainFocus()
    {
        // Domyślnie nic - klasy dziedziczące mogą to nadpisać
    }

    /// <summary>
    /// Wywoływane gdy aplikacja traci fokus
    /// </summary>
    public virtual void OnAppLoseFocus()
    {
        // Domyślnie nic
    }

    /// <summary>
    /// Wywoływane gdy element w aplikacji otrzymuje fokus
    /// Może zmodyfikować ogłaszanie elementu
    /// </summary>
    /// <param name="element">Element który otrzymał fokus</param>
    /// <returns>Niestandardowy opis lub null aby użyć domyślnego</returns>
    public virtual string? OnElementFocus(AutomationElement element)
    {
        // Domyślnie null - użyj standardowego ogłaszania
        return null;
    }

    /// <summary>
    /// Pozwala na dostosowanie opisu elementu przed ogłoszeniem
    /// </summary>
    /// <param name="element">Element</param>
    /// <param name="defaultDescription">Domyślny opis wygenerowany przez system</param>
    /// <returns>Zmodyfikowany opis lub oryginalny</returns>
    public virtual string CustomizeElementDescription(AutomationElement element, string defaultDescription)
    {
        return defaultDescription;
    }

    /// <summary>
    /// Wywoływane przed ogłoszeniem elementu - pozwala na dodanie dodatkowych informacji
    /// </summary>
    public virtual void BeforeAnnounceElement(AutomationElement element)
    {
        // Domyślnie nic
    }

    /// <summary>
    /// Wywoływane po ogłoszeniu elementu
    /// </summary>
    public virtual void AfterAnnounceElement(AutomationElement element)
    {
        // Domyślnie nic
    }

    /// <summary>
    /// Obsługuje gesty specyficzne dla aplikacji
    /// </summary>
    /// <param name="keys">Naciśnięte klawisze</param>
    /// <returns>True jeśli gest został obsłużony, false aby kontynuować standardową obsługę</returns>
    public virtual bool HandleGesture(System.Windows.Forms.Keys keys)
    {
        return false;
    }

    /// <summary>
    /// Czyści zasoby przy zamknięciu aplikacji
    /// </summary>
    public virtual void Terminate()
    {
        IsActive = false;
        Speech = null;
    }
}
