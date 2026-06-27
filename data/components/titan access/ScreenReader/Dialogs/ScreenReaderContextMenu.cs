using System.Windows.Forms;
using System.Runtime.InteropServices;

namespace ScreenReader;

/// <summary>
/// Klasyczne menu kontekstowe czytnika ekranu (styl Windows klasyczny)
/// Używa ContextMenuStrip dla lepszej obsługi fokus i dostępności
/// </summary>
public class ScreenReaderContextMenu : IDisposable
{
    private readonly Action? _onSettings;
    private readonly Action? _onHelp;
    private readonly Action? _onExit;
    private ContextMenuStrip? _menuStrip;
    private Form? _helperForm;
    private bool _disposed;

    // Win32 API
    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    private static extern bool GetCursorPos(out POINT lpPoint);

    [StructLayout(LayoutKind.Sequential)]
    private struct POINT
    {
        public int X;
        public int Y;
    }

    public ScreenReaderContextMenu(Action? onSettings, Action? onHelp, Action? onExit)
    {
        _onSettings = onSettings;
        _onHelp = onHelp;
        _onExit = onExit;
    }

    /// <summary>
    /// Pokazuje menu kontekstowe na środku ekranu z fokusem
    /// </summary>
    public void ShowCentered()
    {
        var screen = Screen.PrimaryScreen;
        if (screen != null)
        {
            int x = screen.WorkingArea.Width / 2;
            int y = screen.WorkingArea.Height / 2;
            ShowAt(x, y);
        }
        else
        {
            ShowAtCursor();
        }
    }

    /// <summary>
    /// Pokazuje menu kontekstowe na pozycji kursora myszy
    /// </summary>
    public void ShowAtCursor()
    {
        GetCursorPos(out POINT pt);
        ShowAt(pt.X, pt.Y);
    }

    /// <summary>
    /// Pokazuje menu kontekstowe na podanej pozycji
    /// </summary>
    private void ShowAt(int x, int y)
    {
        // Utwórz helper form jeśli jeszcze nie istnieje
        if (_helperForm == null || _helperForm.IsDisposed)
        {
            _helperForm = new Form
            {
                Width = 0,
                Height = 0,
                FormBorderStyle = FormBorderStyle.None,
                ShowInTaskbar = false,
                StartPosition = FormStartPosition.Manual,
                Location = new System.Drawing.Point(-10000, -10000),
                TopMost = true
            };
            _helperForm.Show();
            _helperForm.Hide();
        }

        // Utwórz menu strip
        _menuStrip?.Dispose();
        _menuStrip = new ContextMenuStrip();
        _menuStrip.ShowImageMargin = false;

        // Dodaj elementy menu
        var settingsItem = new ToolStripMenuItem("&Ustawienia...\tInsert+N, U");
        settingsItem.Click += (s, e) => _onSettings?.Invoke();
        _menuStrip.Items.Add(settingsItem);

        var helpItem = new ToolStripMenuItem("&Pomoc\tInsert+F1");
        helpItem.Click += (s, e) => _onHelp?.Invoke();
        _menuStrip.Items.Add(helpItem);

        _menuStrip.Items.Add(new ToolStripSeparator());

        var exitItem = new ToolStripMenuItem("&Zamknij czytnik ekranu\tAlt+F4");
        exitItem.Click += (s, e) => _onExit?.Invoke();
        _menuStrip.Items.Add(exitItem);

        // Pokazuj i ustaw fokus
        _helperForm.Show();
        SetForegroundWindow(_helperForm.Handle);

        // Pokaż menu
        _menuStrip.Show(x, y);

        // Ustaw fokus na pierwszym elemencie
        if (_menuStrip.Items.Count > 0)
        {
            _menuStrip.Items[0].Select();
        }
    }

    public void Dispose()
    {
        if (_disposed)
            return;

        _menuStrip?.Dispose();
        _helperForm?.Dispose();
        _disposed = true;
    }
}
