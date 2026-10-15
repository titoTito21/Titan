using System.Windows.Forms;

namespace ScreenReader;

public class ScreenReaderMenu : Form
{
    private readonly Action _onSettings;
    private readonly Action _onExit;

    public ScreenReaderMenu(Action onSettings, Action onExit)
    {
        _onSettings = onSettings;
        _onExit = onExit;
        
        InitializeComponents();
    }

    private void InitializeComponents()
    {
        Text = "Menu Czytnika Ekranu";
        Width = 300;
        Height = 150;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        TopMost = true;

        var btnSettings = new Button
        {
            Text = "Ustawienia czytnika ekranu",
            Width = 250,
            Height = 30,
            Left = 20,
            Top = 20
        };
        btnSettings.Click += (s, e) =>
        {
            _onSettings();
            Close();
        };

        var btnExit = new Button
        {
            Text = "Zamknij czytnik ekranu",
            Width = 250,
            Height = 30,
            Left = 20,
            Top = 60
        };
        btnExit.Click += (s, e) =>
        {
            _onExit();
            Close();
        };

        Controls.Add(btnSettings);
        Controls.Add(btnExit);

        // Focus first button
        btnSettings.Select();
    }
}
