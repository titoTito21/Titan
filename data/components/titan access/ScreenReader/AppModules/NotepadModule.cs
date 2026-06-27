using System.Windows.Automation;
using ScreenReader.Localization;

namespace ScreenReader.AppModules;

/// <summary>
/// Moduł dla Notatnika (notepad.exe)
/// Ulepsza doświadczenie dla prostego edytora tekstu
/// </summary>
public class NotepadModule : AppModuleBase
{
    public override string ProcessName => "notepad";
    public override string AppName => L.T("notepad.appName");

    private bool _hasAnnouncedWelcome;

    public override void OnAppGainFocus()
    {
        base.OnAppGainFocus();

        if (!_hasAnnouncedWelcome)
        {
            Speech?.Speak(L.T("notepad.welcome"));
            _hasAnnouncedWelcome = true;
        }
    }

    public override string CustomizeElementDescription(AutomationElement element, string defaultDescription)
    {
        try
        {
            var controlType = element.Current.ControlType;

            // Dla pola edycji, dodaj informację o liczbie znaków jeśli to główny dokument
            if (controlType == ControlType.Edit || controlType == ControlType.Document)
            {
                var className = element.Current.ClassName;
                if (className == "Edit")
                {
                    // Główne pole edycji Notatnika
                    if (element.TryGetCurrentPattern(TextPattern.Pattern, out var textPattern))
                    {
                        var text = ((TextPattern)textPattern).DocumentRange.GetText(-1);
                        int charCount = text.Length;
                        int lineCount = text.Split('\n').Length;

                        if (charCount > 0)
                        {
                            return L.T("notepad.docStats", defaultDescription, lineCount, charCount);
                        }
                        else
                        {
                            return L.T("notepad.emptyDoc", defaultDescription);
                        }
                    }
                }
            }
        }
        catch
        {
            // Ignoruj błędy, użyj domyślnego opisu
        }

        return defaultDescription;
    }

    public override void Terminate()
    {
        _hasAnnouncedWelcome = false;
        base.Terminate();
    }
}
