using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Windows.Automation;
using System.Windows.Automation.Text;

namespace ScreenReader.Terminal;

/// <summary>
/// Glowny handler dla terminali/konsol
/// Obsluguje: cmd.exe, PowerShell, Windows Terminal, conhost
/// </summary>
public class TerminalHandler : IDisposable
{
    private readonly ConsoleOutputMonitor _consoleMonitor;
    private bool _isInTerminal;
    private IntPtr _currentTerminalHwnd;
    private string? _currentTerminalProcess;
    private bool _disposed;

    /// <summary>
    /// Event dla nowej linii wyjscia
    /// </summary>
    public event Action<string>? OutputReceived;

    /// <summary>
    /// Event dla zmian tekstu (dynamiczne)
    /// </summary>
    public event Action<string, bool>? TextChanged;

    /// <summary>
    /// Czy aktualnie jestesmy w terminalu
    /// </summary>
    public bool IsInTerminal => _isInTerminal;

    /// <summary>
    /// Nazwy procesow terminalowych
    /// </summary>
    private static readonly HashSet<string> TerminalProcesses = new(StringComparer.OrdinalIgnoreCase)
    {
        "cmd", "powershell", "pwsh", "WindowsTerminal", "conhost",
        "wt", "mintty", "ConEmu", "ConEmu64", "cmder",
        "alacritty", "wezterm", "hyper", "terminus"
    };

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    private static extern int GetClassName(IntPtr hWnd, System.Text.StringBuilder lpClassName, int nMaxCount);

    public TerminalHandler()
    {
        _consoleMonitor = new ConsoleOutputMonitor();

        // Podlacz eventy monitora
        _consoleMonitor.NewLineOutput += OnNewLineOutput;
        _consoleMonitor.TextChanged += OnTextChanged;
        _consoleMonitor.CursorMoved += OnCursorMoved;
    }

    /// <summary>
    /// Sprawdza czy proces jest terminalem
    /// </summary>
    public static bool IsTerminalProcess(string? processName)
    {
        if (string.IsNullOrEmpty(processName))
            return false;

        return TerminalProcesses.Contains(processName);
    }

    /// <summary>
    /// Wykrywa terminal na podstawie okna
    /// </summary>
    public static bool IsTerminalWindow(IntPtr hwnd)
    {
        if (hwnd == IntPtr.Zero)
            return false;

        try
        {
            // Sprawdz klase okna
            var className = new System.Text.StringBuilder(256);
            GetClassName(hwnd, className, 256);
            string cls = className.ToString();

            // Typowe klasy okien terminali
            if (cls.Contains("ConsoleWindowClass", StringComparison.OrdinalIgnoreCase) ||
                cls.Contains("CASCADIA_HOSTING_WINDOW_CLASS", StringComparison.OrdinalIgnoreCase) ||
                cls.Contains("mintty", StringComparison.OrdinalIgnoreCase) ||
                cls.Contains("VirtualConsoleClass", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }

            // Sprawdz proces
            GetWindowThreadProcessId(hwnd, out uint pid);
            if (pid > 0)
            {
                try
                {
                    using var process = Process.GetProcessById((int)pid);
                    return IsTerminalProcess(process.ProcessName);
                }
                catch { }
            }
        }
        catch { }

        return false;
    }

    /// <summary>
    /// Aktywuje obsluge terminala dla okna
    /// </summary>
    public bool ActivateForWindow(IntPtr hwnd, string? processName)
    {
        if (hwnd == IntPtr.Zero)
            return false;

        // Sprawdz czy to terminal
        if (!IsTerminalProcess(processName) && !IsTerminalWindow(hwnd))
        {
            if (_isInTerminal)
            {
                Deactivate();
            }
            return false;
        }

        // Juz monitorujemy to okno
        if (_isInTerminal && _currentTerminalHwnd == hwnd)
            return true;

        // Zatrzymaj poprzednie monitorowanie
        if (_isInTerminal)
        {
            _consoleMonitor.StopMonitoring();
        }

        _currentTerminalHwnd = hwnd;
        _currentTerminalProcess = processName;

        // Rozpocznij monitorowanie konsoli
        bool started = _consoleMonitor.StartMonitoring(hwnd);

        if (started)
        {
            _isInTerminal = true;
            Console.WriteLine($"TerminalHandler: Aktywowano dla {processName}");
            return true;
        }
        else
        {
            // Jesli nie udalo sie podlaczyc do konsoli,
            // nadal oznacz jako terminal dla podstawowej obslugi UIA
            _isInTerminal = true;
            Console.WriteLine($"TerminalHandler: Tryb podstawowy dla {processName} (brak dostepu do konsoli)");
            return true;
        }
    }

    /// <summary>
    /// Dezaktywuje obsluge terminala
    /// </summary>
    public void Deactivate()
    {
        if (!_isInTerminal)
            return;

        _consoleMonitor.StopMonitoring();
        _isInTerminal = false;
        _currentTerminalHwnd = IntPtr.Zero;
        _currentTerminalProcess = null;

        Console.WriteLine("TerminalHandler: Dezaktywowano");
    }

    /// <summary>
    /// Odczytuje biezaca linie terminala
    /// </summary>
    public string ReadCurrentLine()
    {
        if (!_isInTerminal)
            return "";

        // Sprobuj przez Console API
        string line = _consoleMonitor.ReadCurrentLine();
        if (!string.IsNullOrWhiteSpace(line))
            return line;

        // Fallback: sprobuj przez UIA
        try
        {
            var focused = AutomationElement.FocusedElement;
            if (focused != null)
            {
                // Windows Terminal uzywa TextPattern
                if (focused.TryGetCurrentPattern(TextPattern.Pattern, out var textPattern))
                {
                    var range = ((TextPattern)textPattern).GetSelection();
                    if (range.Length > 0)
                    {
                        // Rozszerz do calej linii
                        var lineRange = range[0].Clone();
                        lineRange.ExpandToEnclosingUnit(TextUnit.Line);
                        return lineRange.GetText(-1).Trim();
                    }
                }

                // Sprobuj ValuePattern
                if (focused.TryGetCurrentPattern(ValuePattern.Pattern, out var valuePattern))
                {
                    var value = ((ValuePattern)valuePattern).Current.Value;
                    // Zwroc ostatnia linie
                    var lines = value.Split('\n');
                    if (lines.Length > 0)
                        return lines[lines.Length - 1].Trim();
                }

                return focused.Current.Name ?? "";
            }
        }
        catch { }

        return "";
    }

    /// <summary>
    /// Pobiera caly widoczny tekst terminala
    /// </summary>
    public string ReadVisibleContent()
    {
        if (!_isInTerminal)
            return "";

        try
        {
            var focused = AutomationElement.FocusedElement;
            if (focused != null)
            {
                if (focused.TryGetCurrentPattern(TextPattern.Pattern, out var textPattern))
                {
                    var range = ((TextPattern)textPattern).DocumentRange;
                    return range.GetText(-1);
                }

                if (focused.TryGetCurrentPattern(ValuePattern.Pattern, out var valuePattern))
                {
                    return ((ValuePattern)valuePattern).Current.Value;
                }
            }
        }
        catch { }

        return "";
    }

    /// <summary>
    /// Callback dla nowej linii wyjscia
    /// </summary>
    private void OnNewLineOutput(string line)
    {
        if (!string.IsNullOrWhiteSpace(line))
        {
            Console.WriteLine($"Terminal output: {line}");
            OutputReceived?.Invoke(line);
        }
    }

    /// <summary>
    /// Callback dla zmiany tekstu
    /// </summary>
    private void OnTextChanged(string text, bool isAssertive)
    {
        if (!string.IsNullOrWhiteSpace(text))
        {
            TextChanged?.Invoke(text, isAssertive);
        }
    }

    /// <summary>
    /// Callback dla ruchu kursora
    /// </summary>
    private void OnCursorMoved(int row, int col, string currentLine)
    {
        // Mozna rozszerzyc o oglaszanie pozycji
    }

    public void Dispose()
    {
        if (_disposed)
            return;

        Deactivate();
        _consoleMonitor.Dispose();
        _disposed = true;
    }
}
