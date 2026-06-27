using System.IO.Pipes;
using System.Windows.Forms;
using ScreenReader.Localization;
using ScreenReader.Speech;

namespace ScreenReader;

class Program
{
    private const string MutexName = "ScreenReader_SingleInstance_Mutex";
    private const string PipeName = "ScreenReader_CommandPipe";
    private static ScreenReaderEngine? _engine;
    private static CancellationTokenSource? _pipeServerCts;

    [STAThread]
    static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);

        // Załaduj lokalizację (pl/en) z locale/*.json wg ustawień
        ScreenReader.Localization.LocalizationManager.Initialize();

        // Parsuj argumenty
        if (args.Length > 0)
        {
            if (HandleCommandLineArguments(args))
                return; // Argument został obsłużony, zakończ
        }

        // Sprawdź czy inna instancja jest uruchomiona
        using var mutex = new Mutex(true, MutexName, out bool createdNew);

        if (!createdNew)
        {
            // Inna instancja jest uruchomiona
            Console.WriteLine(L.T("app.alreadyRunning"));
            return;
        }

        // Uruchom serwer poleceń
        _pipeServerCts = new CancellationTokenSource();
        StartCommandServer(_pipeServerCts.Token);

        using var engine = new ScreenReaderEngine();
        _engine = engine;
        engine.Start();

        // Run Windows Forms message loop to keep the application alive
        Application.Run();
    }

    /// <summary>
    /// Obsługuje argumenty wiersza poleceń
    /// Zwraca true jeśli program powinien zakończyć działanie po obsłużeniu argumentu
    /// </summary>
    private static bool HandleCommandLineArguments(string[] args)
    {
        foreach (var arg in args)
        {
            switch (arg.ToLower())
            {
                case "--turnoff":
                case "-turnoff":
                    SendCommand("turnoff");
                    return true;

                case "--set-screenreader-settings":
                case "-set-screenreader-settings":
                case "--settings":
                case "-settings":
                    SendCommand("settings");
                    return true;

                case "--restart":
                case "-restart":
                    SendCommand("restart");
                    return true;

                case "--soundsoff":
                case "-soundsoff":
                    SendCommand("soundsoff");
                    return true;

                case "--soundson":
                case "-soundson":
                    SendCommand("soundson");
                    return true;

                case "--help":
                case "-help":
                case "-h":
                case "/?":
                    PrintHelp();
                    return true;

                case "--test-nvda":
                case "-test-nvda":
                    Interop.NVDAControllerTester.RunTests();
                    return true;
            }
        }
        return false;
    }

    /// <summary>
    /// Wyświetla pomoc
    /// </summary>
    private static void PrintHelp()
    {
        Console.WriteLine(L.T("help.title"));
        Console.WriteLine();
        Console.WriteLine(L.T("help.usage"));
        Console.WriteLine();
        Console.WriteLine(L.T("help.optionsHeader"));
        Console.WriteLine(L.T("help.opt.turnoff"));
        Console.WriteLine(L.T("help.opt.settings"));
        Console.WriteLine(L.T("help.opt.restart"));
        Console.WriteLine(L.T("help.opt.soundsoff"));
        Console.WriteLine(L.T("help.opt.soundson"));
        Console.WriteLine(L.T("help.opt.testnvda"));
        Console.WriteLine(L.T("help.opt.help"));
    }

    /// <summary>
    /// Wysyła polecenie do działającej instancji czytnika
    /// </summary>
    private static void SendCommand(string command)
    {
        try
        {
            using var client = new NamedPipeClientStream(".", PipeName, PipeDirection.Out);
            client.Connect(1000); // Timeout 1 sekunda

            using var writer = new StreamWriter(client);
            writer.WriteLine(command);
            writer.Flush();

            Console.WriteLine(L.T("cmd.sent", command));
        }
        catch (TimeoutException)
        {
            Console.WriteLine(L.T("cmd.cannotConnect"));
        }
        catch (Exception ex)
        {
            Console.WriteLine(L.T("cmd.sendError", ex.Message));
        }
    }

    /// <summary>
    /// Uruchamia serwer poleceń (named pipe server)
    /// </summary>
    private static void StartCommandServer(CancellationToken cancellationToken)
    {
        Task.Run(async () =>
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                try
                {
                    using var server = new NamedPipeServerStream(PipeName, PipeDirection.In);
                    await server.WaitForConnectionAsync(cancellationToken);

                    using var reader = new StreamReader(server);
                    var command = await reader.ReadLineAsync();

                    if (!string.IsNullOrEmpty(command))
                    {
                        ProcessCommand(command);
                    }
                }
                catch (OperationCanceledException)
                {
                    break;
                }
                catch (Exception ex)
                {
                    Console.WriteLine(L.T("cmd.serverError", ex.Message));
                }
            }
        }, cancellationToken);
    }

    /// <summary>
    /// Przetwarza otrzymane polecenie
    /// </summary>
    private static void ProcessCommand(string command)
    {
        Console.WriteLine(L.T("cmd.received", command));

        switch (command.ToLower())
        {
            case "turnoff":
                Console.WriteLine(L.T("cmd.closing"));
                Application.Exit();
                break;

            case "settings":
                Console.WriteLine(L.T("cmd.openingSettings"));
                if (_engine != null)
                {
                    // Wywołaj na wątku UI
                    Application.OpenForms[0]?.BeginInvoke(() =>
                    {
                        OpenSettings();
                    });
                }
                else
                {
                    OpenSettings();
                }
                break;

            case "restart":
                Console.WriteLine(L.T("cmd.restarting"));
                RestartApplication();
                break;

            case "soundsoff":
                SoundManager.GlobalSoundsEnabled = false;
                Console.WriteLine(L.T("cmd.soundsOff"));
                break;

            case "soundson":
                SoundManager.GlobalSoundsEnabled = true;
                Console.WriteLine(L.T("cmd.soundsOn"));
                break;
        }
    }

    /// <summary>
    /// Otwiera okno ustawień
    /// </summary>
    private static void OpenSettings()
    {
        var thread = new Thread(() =>
        {
            try
            {
                Application.EnableVisualStyles();
                var settingsDialog = new SettingsDialog(ScreenReaderEngine.Instance?.SpeechManager
                    ?? new SpeechManager());
                settingsDialog.TopMost = true;
                settingsDialog.StartPosition = FormStartPosition.CenterScreen;
                Application.Run(settingsDialog);
            }
            catch (Exception ex)
            {
                Console.WriteLine(L.T("cmd.settingsError", ex.Message));
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
    }

    /// <summary>
    /// Restartuje aplikację
    /// </summary>
    private static void RestartApplication()
    {
        var exePath = Environment.ProcessPath;
        if (!string.IsNullOrEmpty(exePath))
        {
            System.Diagnostics.Process.Start(exePath);
        }
        Application.Exit();
    }
}
