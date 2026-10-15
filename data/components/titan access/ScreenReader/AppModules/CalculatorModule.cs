using System.Windows.Automation;

namespace ScreenReader.AppModules;

/// <summary>
/// Moduł dla Kalkulatora Windows (calc.exe / CalculatorApp.exe)
/// Ulepsza ogłaszanie operacji matematycznych
/// </summary>
public class CalculatorModule : AppModuleBase
{
    public override string ProcessName => "calculatorapp";
    public override string AppName => "Kalkulator";

    private string? _lastDisplayValue;

    public override string CustomizeElementDescription(AutomationElement element, string defaultDescription)
    {
        try
        {
            var controlType = element.Current.ControlType;
            var automationId = element.Current.AutomationId;
            var name = element.Current.Name;

            // Pole wyświetlacza - ogłoś wartość
            if (controlType == ControlType.Text && automationId.Contains("Display"))
            {
                if (!string.IsNullOrEmpty(name) && name != _lastDisplayValue)
                {
                    _lastDisplayValue = name;
                    return $"Wyświetlacz: {name}";
                }
                return name ?? "0";
            }

            // Przyciski operacji - użyj polskich nazw
            if (controlType == ControlType.Button)
            {
                return TranslateCalculatorButton(name, defaultDescription);
            }
        }
        catch
        {
            // Ignoruj błędy
        }

        return defaultDescription;
    }

    /// <summary>
    /// Tłumaczy nazwy przycisków kalkulatora na polski
    /// </summary>
    private static string TranslateCalculatorButton(string? name, string defaultDescription)
    {
        if (string.IsNullOrEmpty(name))
            return defaultDescription;

        return name switch
        {
            "Plus" or "+" => "Plus, przycisk",
            "Minus" or "-" or "−" => "Minus, przycisk",
            "Multiply by" or "×" or "*" => "Mnożenie, przycisk",
            "Divide by" or "÷" or "/" => "Dzielenie, przycisk",
            "Equals" or "=" => "Równa się, przycisk",
            "Clear" or "C" => "Wyczyść, przycisk",
            "Clear entry" or "CE" => "Wyczyść wpis, przycisk",
            "Backspace" => "Cofnij, przycisk",
            "Square root" or "√" => "Pierwiastek kwadratowy, przycisk",
            "Percent" or "%" => "Procent, przycisk",
            "Positive negative" or "±" => "Zmień znak, przycisk",
            "Decimal separator" or "." or "," => "Przecinek dziesiętny, przycisk",
            "Zero" or "0" => "Zero, przycisk",
            "One" or "1" => "Jeden, przycisk",
            "Two" or "2" => "Dwa, przycisk",
            "Three" or "3" => "Trzy, przycisk",
            "Four" or "4" => "Cztery, przycisk",
            "Five" or "5" => "Pięć, przycisk",
            "Six" or "6" => "Sześć, przycisk",
            "Seven" or "7" => "Siedem, przycisk",
            "Eight" or "8" => "Osiem, przycisk",
            "Nine" or "9" => "Dziewięć, przycisk",
            _ => defaultDescription
        };
    }

    public override void BeforeAnnounceElement(AutomationElement element)
    {
        // Odtwórz dźwięk przy naciśnięciu przycisku
        var controlType = element.Current.ControlType;
        if (controlType == ControlType.Button)
        {
            // Można tutaj dodać dźwięk kliknięcia
        }
    }

    public override void Terminate()
    {
        _lastDisplayValue = null;
        base.Terminate();
    }
}
