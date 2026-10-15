using System.Runtime.InteropServices;
using System.Text;

namespace ScreenReader.Terminal;

/// <summary>
/// Monitoruje wyjście konsoli Windows (cmd, PowerShell, conhost)
/// Używa Console API do czytania bufora ekranu
/// </summary>
public class ConsoleOutputMonitor : IDisposable
{
    private IntPtr _consoleHandle = IntPtr.Zero;
    private IntPtr _targetHwnd = IntPtr.Zero;
    private string _lastContent = "";
    private int _lastCursorRow = 0;
    private int _lastCursorCol = 0;
    private System.Threading.Timer? _pollTimer;
    private bool _disposed;
    private bool _isMonitoring;
    private readonly object _lock = new();

    /// <summary>
    /// Event wywoływany gdy pojawi sie nowa linia w konsoli
    /// </summary>
    public event Action<string>? NewLineOutput;

    /// <summary>
    /// Event wywoływany gdy zmieni sie pozycja kursora (dla nawigacji)
    /// </summary>
    public event Action<int, int, string>? CursorMoved;

    /// <summary>
    /// Event wywoływany dla dowolnej zmiany tekstu
    /// </summary>
    public event Action<string, bool>? TextChanged;

    // Win32 Console API
    private const int STD_OUTPUT_HANDLE = -11;
    private const uint GENERIC_READ = 0x80000000;
    private const uint GENERIC_WRITE = 0x40000000;
    private const uint FILE_SHARE_READ = 0x00000001;
    private const uint FILE_SHARE_WRITE = 0x00000002;
    private const uint OPEN_EXISTING = 3;

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr GetStdHandle(int nStdHandle);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetConsoleScreenBufferInfo(IntPtr hConsoleOutput, out CONSOLE_SCREEN_BUFFER_INFO lpConsoleScreenBufferInfo);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool ReadConsoleOutputCharacter(IntPtr hConsoleOutput, StringBuilder lpCharacter, uint nLength, COORD dwReadCoord, out uint lpNumberOfCharsRead);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AttachConsole(uint dwProcessId);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool FreeConsole();

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AllocConsole();

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Auto)]
    private static extern IntPtr CreateFile(
        string lpFileName,
        uint dwDesiredAccess,
        uint dwShareMode,
        IntPtr lpSecurityAttributes,
        uint dwCreationDisposition,
        uint dwFlagsAndAttributes,
        IntPtr hTemplateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr hObject);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    [StructLayout(LayoutKind.Sequential)]
    private struct COORD
    {
        public short X;
        public short Y;

        public COORD(short x, short y)
        {
            X = x;
            Y = y;
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct SMALL_RECT
    {
        public short Left;
        public short Top;
        public short Right;
        public short Bottom;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct CONSOLE_SCREEN_BUFFER_INFO
    {
        public COORD dwSize;
        public COORD dwCursorPosition;
        public short wAttributes;
        public SMALL_RECT srWindow;
        public COORD dwMaximumWindowSize;
    }

    /// <summary>
    /// Rozpoczyna monitorowanie konsoli dla okna
    /// </summary>
    public bool StartMonitoring(IntPtr hwnd)
    {
        lock (_lock)
        {
            if (_isMonitoring)
                StopMonitoring();

            _targetHwnd = hwnd;

            // Pobierz PID procesu
            GetWindowThreadProcessId(hwnd, out uint processId);

            if (processId == 0)
            {
                Console.WriteLine("ConsoleOutputMonitor: Nie mozna pobrac PID procesu");
                return false;
            }

            try
            {
                // Polacz sie z konsola procesu
                if (!AttachConsole(processId))
                {
                    int error = Marshal.GetLastWin32Error();
                    // Blad 5 = Access denied (juz jest konsola), 6 = Invalid handle
                    if (error != 5 && error != 6)
                    {
                        Console.WriteLine($"ConsoleOutputMonitor: AttachConsole failed, error: {error}");
                        return false;
                    }
                }

                // Otworz uchwyt do CONOUT$
                _consoleHandle = CreateFile(
                    "CONOUT$",
                    GENERIC_READ | GENERIC_WRITE,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    IntPtr.Zero,
                    OPEN_EXISTING,
                    0,
                    IntPtr.Zero);

                if (_consoleHandle == IntPtr.Zero || _consoleHandle == new IntPtr(-1))
                {
                    Console.WriteLine("ConsoleOutputMonitor: Nie mozna otworzyc CONOUT$");
                    FreeConsole();
                    return false;
                }

                // Pobierz poczatkowy stan
                _lastContent = ReadCurrentScreen();
                if (GetConsoleScreenBufferInfo(_consoleHandle, out var info))
                {
                    _lastCursorRow = info.dwCursorPosition.Y;
                    _lastCursorCol = info.dwCursorPosition.X;
                }

                // Rozpocznij polling (co 100ms)
                _pollTimer = new System.Threading.Timer(PollConsole, null, 100, 100);
                _isMonitoring = true;

                Console.WriteLine($"ConsoleOutputMonitor: Rozpoczeto monitorowanie konsoli (PID: {processId})");
                return true;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"ConsoleOutputMonitor: Blad: {ex.Message}");
                return false;
            }
        }
    }

    /// <summary>
    /// Zatrzymuje monitorowanie
    /// </summary>
    public void StopMonitoring()
    {
        lock (_lock)
        {
            _isMonitoring = false;

            _pollTimer?.Dispose();
            _pollTimer = null;

            if (_consoleHandle != IntPtr.Zero && _consoleHandle != new IntPtr(-1))
            {
                CloseHandle(_consoleHandle);
                _consoleHandle = IntPtr.Zero;
            }

            FreeConsole();
            _targetHwnd = IntPtr.Zero;

            Console.WriteLine("ConsoleOutputMonitor: Zatrzymano monitorowanie");
        }
    }

    /// <summary>
    /// Callback pollingu konsoli
    /// </summary>
    private void PollConsole(object? state)
    {
        if (!_isMonitoring || _consoleHandle == IntPtr.Zero)
            return;

        try
        {
            if (!GetConsoleScreenBufferInfo(_consoleHandle, out var info))
                return;

            int cursorRow = info.dwCursorPosition.Y;
            int cursorCol = info.dwCursorPosition.X;

            // Sprawdz czy kursor sie ruszyl
            if (cursorRow != _lastCursorRow || cursorCol != _lastCursorCol)
            {
                string currentLine = ReadLine(cursorRow);
                CursorMoved?.Invoke(cursorRow, cursorCol, currentLine);
                _lastCursorRow = cursorRow;
                _lastCursorCol = cursorCol;
            }

            // Sprawdz nowe linie (jesli kursor przeskoczyl w dol)
            if (cursorRow > _lastCursorRow)
            {
                // Odczytaj nowe linie
                for (int row = _lastCursorRow; row < cursorRow; row++)
                {
                    string line = ReadLine(row);
                    if (!string.IsNullOrWhiteSpace(line))
                    {
                        NewLineOutput?.Invoke(line.TrimEnd());
                    }
                }
            }

            // Sprawdz zmiany w calym buforze
            string currentContent = ReadVisibleArea(info);
            if (currentContent != _lastContent)
            {
                // Znajdz co sie zmienilo
                string diff = GetDifference(_lastContent, currentContent);
                if (!string.IsNullOrWhiteSpace(diff))
                {
                    TextChanged?.Invoke(diff, false);
                }
                _lastContent = currentContent;
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"ConsoleOutputMonitor: Blad pollingu: {ex.Message}");
        }
    }

    /// <summary>
    /// Czyta pojedyncza linie z bufora
    /// </summary>
    private string ReadLine(int row)
    {
        if (_consoleHandle == IntPtr.Zero)
            return "";

        try
        {
            if (!GetConsoleScreenBufferInfo(_consoleHandle, out var info))
                return "";

            int width = info.dwSize.X;
            var sb = new StringBuilder(width);
            var coord = new COORD(0, (short)row);

            if (ReadConsoleOutputCharacter(_consoleHandle, sb, (uint)width, coord, out _))
            {
                return sb.ToString().TrimEnd();
            }
        }
        catch { }

        return "";
    }

    /// <summary>
    /// Czyta caly widoczny obszar konsoli
    /// </summary>
    private string ReadVisibleArea(CONSOLE_SCREEN_BUFFER_INFO info)
    {
        if (_consoleHandle == IntPtr.Zero)
            return "";

        try
        {
            var lines = new StringBuilder();
            int startRow = info.srWindow.Top;
            int endRow = info.srWindow.Bottom;
            int width = info.dwSize.X;

            for (int row = startRow; row <= endRow; row++)
            {
                var sb = new StringBuilder(width);
                var coord = new COORD(0, (short)row);

                if (ReadConsoleOutputCharacter(_consoleHandle, sb, (uint)width, coord, out _))
                {
                    lines.AppendLine(sb.ToString().TrimEnd());
                }
            }

            return lines.ToString();
        }
        catch
        {
            return "";
        }
    }

    /// <summary>
    /// Czyta caly ekran konsoli
    /// </summary>
    private string ReadCurrentScreen()
    {
        if (_consoleHandle == IntPtr.Zero)
            return "";

        try
        {
            if (!GetConsoleScreenBufferInfo(_consoleHandle, out var info))
                return "";

            return ReadVisibleArea(info);
        }
        catch
        {
            return "";
        }
    }

    /// <summary>
    /// Znajduje roznice miedzy dwoma tekstami
    /// </summary>
    private static string GetDifference(string oldText, string newText)
    {
        if (string.IsNullOrEmpty(oldText))
            return newText;

        if (string.IsNullOrEmpty(newText))
            return "";

        // Prosta heurystyka: znajdz nowe linie na koncu
        var oldLines = oldText.Split('\n', StringSplitOptions.RemoveEmptyEntries);
        var newLines = newText.Split('\n', StringSplitOptions.RemoveEmptyEntries);

        if (newLines.Length > oldLines.Length)
        {
            // Zwroc nowe linie
            var diff = new StringBuilder();
            for (int i = oldLines.Length; i < newLines.Length; i++)
            {
                var line = newLines[i].Trim();
                if (!string.IsNullOrWhiteSpace(line))
                {
                    diff.AppendLine(line);
                }
            }
            return diff.ToString().Trim();
        }

        // Sprawdz zmiane w ostatniej linii
        if (newLines.Length > 0 && oldLines.Length > 0)
        {
            var newLast = newLines[newLines.Length - 1].Trim();
            var oldLast = oldLines[oldLines.Length - 1].Trim();

            if (newLast != oldLast && newLast.Length > oldLast.Length)
            {
                // Zwroc tylko nowa czesc
                if (newLast.StartsWith(oldLast))
                {
                    return newLast.Substring(oldLast.Length).Trim();
                }
            }
        }

        return "";
    }

    /// <summary>
    /// Czyta biezaca linie pod kursorem
    /// </summary>
    public string ReadCurrentLine()
    {
        lock (_lock)
        {
            if (_consoleHandle == IntPtr.Zero)
                return "";

            if (!GetConsoleScreenBufferInfo(_consoleHandle, out var info))
                return "";

            return ReadLine(info.dwCursorPosition.Y);
        }
    }

    /// <summary>
    /// Pobiera pozycje kursora
    /// </summary>
    public (int Row, int Col) GetCursorPosition()
    {
        lock (_lock)
        {
            if (_consoleHandle == IntPtr.Zero)
                return (0, 0);

            if (GetConsoleScreenBufferInfo(_consoleHandle, out var info))
            {
                return (info.dwCursorPosition.Y, info.dwCursorPosition.X);
            }

            return (0, 0);
        }
    }

    public void Dispose()
    {
        if (_disposed)
            return;

        StopMonitoring();
        _disposed = true;
    }
}
