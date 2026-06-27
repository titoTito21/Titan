using System.IO.Pipes;
using System.Text;
using System.Security.AccessControl;
using System.Security.Principal;

namespace ScreenReader.Interop;

/// <summary>
/// Most kompatybilności z NVDA Controller Client API
/// Nasłuchuje na named pipe \\.\pipe\NVDA_controllerClient
/// Pozwala aplikacjom i grom wspierającym NVDA wysyłać tekst do Titan Screen Reader
/// </summary>
public class NVDAControllerBridge : IDisposable
{
    private const string PipeName = "NVDA_controllerClient";
    private readonly SpeechManager _speechManager;
    private readonly CancellationTokenSource _cancellationSource;
    private readonly Task _serverTask;
    private bool _disposed;

    public NVDAControllerBridge(SpeechManager speechManager)
    {
        _speechManager = speechManager ?? throw new ArgumentNullException(nameof(speechManager));
        _cancellationSource = new CancellationTokenSource();

        // Uruchom server w tle
        _serverTask = Task.Run(() => RunServerAsync(_cancellationSource.Token));

        Console.WriteLine("NVDA Controller Bridge: Uruchomiono (named pipe: " + PipeName + ")");
    }

    private async Task RunServerAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            NamedPipeServerStream? pipeServer = null;
            try
            {
                Console.WriteLine($"NVDA Bridge: Creating named pipe server: \\\\.\\pipe\\{PipeName}");

                // Utwórz named pipe server z bezpieczeństwem pozwalającym na dostęp wszystkim
                var pipeSecurity = new System.IO.Pipes.PipeSecurity();
                pipeSecurity.AddAccessRule(
                    new System.IO.Pipes.PipeAccessRule(
                        new System.Security.Principal.SecurityIdentifier(System.Security.Principal.WellKnownSidType.WorldSid, null),
                        System.IO.Pipes.PipeAccessRights.ReadWrite,
                        System.Security.AccessControl.AccessControlType.Allow));

                pipeServer = NamedPipeServerStreamAcl.Create(
                    PipeName,
                    PipeDirection.InOut,
                    NamedPipeServerStream.MaxAllowedServerInstances,
                    PipeTransmissionMode.Byte,
                    PipeOptions.Asynchronous,
                    0, 0,
                    pipeSecurity);

                Console.WriteLine("NVDA Bridge: Waiting for client connection...");

                // Czekaj na połączenie
                await pipeServer.WaitForConnectionAsync(cancellationToken);

                // Obsłuż klienta
                await HandleClientAsync(pipeServer, cancellationToken);
            }
            catch (OperationCanceledException)
            {
                Console.WriteLine("NVDA Bridge: Shutdown requested");
                break;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"NVDA Bridge Error: {ex.Message}");
                Console.WriteLine($"NVDA Bridge Stack: {ex.StackTrace}");
                await Task.Delay(100, cancellationToken); // Czekaj przed ponowną próbą
            }
            finally
            {
                try
                {
                    pipeServer?.Dispose();
                }
                catch
                {
                    // Ignoruj błędy dispose
                }
            }
        }
    }

    private async Task HandleClientAsync(NamedPipeServerStream pipeServer, CancellationToken cancellationToken)
    {
        try
        {
            Console.WriteLine("NVDA Bridge: Client connected");

            // Czytaj Function ID (4 bajty, int32 little-endian)
            var functionIdBuffer = new byte[4];
            int bytesRead = await pipeServer.ReadAsync(functionIdBuffer, 0, 4, cancellationToken);

            if (bytesRead != 4)
            {
                Console.WriteLine("NVDA Bridge: Failed to read function ID");
                return;
            }

            int functionId = BitConverter.ToInt32(functionIdBuffer, 0);
            Console.WriteLine($"NVDA Bridge: Function ID = {functionId}");

            int result = await ProcessFunctionAsync(pipeServer, functionId, cancellationToken);

            // Wyślij odpowiedź
            await SendResponseAsync(pipeServer, result, cancellationToken);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"NVDA Bridge HandleClient Error: {ex.Message}");
        }
    }

    private async Task<int> ProcessFunctionAsync(NamedPipeServerStream pipeServer, int functionId, CancellationToken cancellationToken)
    {
        try
        {
            switch (functionId)
            {
                case 0: // testIfRunning
                    Console.WriteLine("NVDA Bridge: testIfRunning");
                    return 0; // Screen reader działa

                case 1: // speakText
                    {
                        string? text = await ReadStringParameterAsync(pipeServer, cancellationToken);
                        if (text != null)
                        {
                            Console.WriteLine($"NVDA Bridge: speakText = '{text}'");
                            _speechManager.Speak(text, interrupt: false);
                            return 0;
                        }
                        return -1;
                    }

                case 2: // cancelSpeech
                    Console.WriteLine("NVDA Bridge: cancelSpeech");
                    _speechManager.Stop();
                    return 0;

                case 3: // brailleMessage
                    {
                        string? text = await ReadStringParameterAsync(pipeServer, cancellationToken);
                        Console.WriteLine($"NVDA Bridge: brailleMessage = '{text}' (ignored)");
                        return 0; // Ignoruj brajl, ale zwróć sukces
                    }

                default:
                    Console.WriteLine($"NVDA Bridge: Unknown function ID: {functionId}");
                    return -1;
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"NVDA Bridge ProcessFunction Error: {ex.Message}");
            return -1;
        }
    }

    private async Task<string?> ReadStringParameterAsync(NamedPipeServerStream pipeServer, CancellationToken cancellationToken)
    {
        try
        {
            // Czytaj długość stringu w znakach (4 bajty, int32)
            var lengthBuffer = new byte[4];
            int bytesRead = await pipeServer.ReadAsync(lengthBuffer, 0, 4, cancellationToken);

            if (bytesRead != 4)
            {
                Console.WriteLine("NVDA Bridge: Failed to read string length");
                return null;
            }

            int stringLength = BitConverter.ToInt32(lengthBuffer, 0);
            Console.WriteLine($"NVDA Bridge: String length = {stringLength} chars");

            if (stringLength < 0 || stringLength > 10000)
            {
                Console.WriteLine($"NVDA Bridge: Invalid string length: {stringLength}");
                return null;
            }

            if (stringLength == 0)
                return string.Empty;

            // Czytaj string (UTF-16LE, 2 bajty na znak)
            int byteCount = stringLength * 2;
            var stringBuffer = new byte[byteCount];
            bytesRead = await pipeServer.ReadAsync(stringBuffer, 0, byteCount, cancellationToken);

            if (bytesRead != byteCount)
            {
                Console.WriteLine($"NVDA Bridge: Failed to read string data (expected {byteCount}, got {bytesRead})");
                return null;
            }

            string text = Encoding.Unicode.GetString(stringBuffer);
            return text;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"NVDA Bridge ReadStringParameter Error: {ex.Message}");
            return null;
        }
    }


    private async Task SendResponseAsync(NamedPipeServerStream pipeServer, int result, CancellationToken cancellationToken)
    {
        try
        {
            byte[] responseBuffer = BitConverter.GetBytes(result);
            await pipeServer.WriteAsync(responseBuffer, 0, 4, cancellationToken);
            await pipeServer.FlushAsync(cancellationToken);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"NVDA Bridge SendResponse Error: {ex.Message}");
        }
    }

    public void Dispose()
    {
        if (_disposed)
            return;

        _disposed = true;

        try
        {
            _cancellationSource.Cancel();
            _serverTask.Wait(TimeSpan.FromSeconds(2));
        }
        catch (Exception ex)
        {
            Console.WriteLine($"NVDA Bridge Dispose Error: {ex.Message}");
        }
        finally
        {
            _cancellationSource.Dispose();
        }

        Console.WriteLine("NVDA Controller Bridge: Zatrzymano");
    }
}
