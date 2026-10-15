using System.Windows.Forms;

namespace ScreenReader;

/// <summary>
/// Dialog menu czytnika ekranu - w pełni dostępny, z przyciskami zamiast menu kontekstowego
/// </summary>
public class ScreenReaderMenuDialog : Form
{
    private readonly Action? _onSettings;
    private readonly Action? _onHelp;
    private readonly Action? _onExit;

    public ScreenReaderMenuDialog(Action? onSettings, Action? onHelp, Action? onExit)
    {
        _onSettings = onSettings;
        _onHelp = onHelp;
        _onExit = onExit;

        InitializeComponents();
    }

    private void InitializeComponents()
    {
        // Właściwości okna
        Text = "Menu czytnika ekranu";
        Width = 400;
        Height = 250;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        TopMost = true;
        ShowInTaskbar = true;

        // Panel z przyciskami
        var panel = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.TopDown,
            Padding = new Padding(20),
            AutoSize = true
        };

        // Przycisk Ustawienia
        var btnSettings = new Button
        {
            Text = "&Ustawienia... (Insert+N, U)",
            Width = 340,
            Height = 40,
            Font = new System.Drawing.Font("Segoe UI", 11F),
            TabIndex = 0
        };
        btnSettings.Click += (s, e) =>
        {
            Close();
            _onSettings?.Invoke();
        };
        panel.Controls.Add(btnSettings);

        // Przycisk Pomoc
        var btnHelp = new Button
        {
            Text = "&Pomoc (Insert+F1)",
            Width = 340,
            Height = 40,
            Font = new System.Drawing.Font("Segoe UI", 11F),
            TabIndex = 1
        };
        btnHelp.Click += (s, e) =>
        {
            Close();
            _onHelp?.Invoke();
        };
        panel.Controls.Add(btnHelp);

        // Separator (pusty panel)
        var separator = new Panel
        {
            Height = 20,
            Width = 340
        };
        panel.Controls.Add(separator);

        // Przycisk Zamknij
        var btnExit = new Button
        {
            Text = "&Zamknij czytnik ekranu (Alt+F4)",
            Width = 340,
            Height = 40,
            Font = new System.Drawing.Font("Segoe UI", 11F),
            TabIndex = 2
        };
        btnExit.Click += (s, e) =>
        {
            Close();
            _onExit?.Invoke();
        };
        panel.Controls.Add(btnExit);

        // Dodaj panel do formularza
        Controls.Add(panel);

        // Obsługa Escape - zamyka dialog
        KeyPreview = true;
        KeyDown += (s, e) =>
        {
            if (e.KeyCode == Keys.Escape)
            {
                Close();
            }
        };

        // Ustaw fokus na pierwszym przycisku po pokazaniu
        Shown += (s, e) => btnSettings.Focus();
    }
}
