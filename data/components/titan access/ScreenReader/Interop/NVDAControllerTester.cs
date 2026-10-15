using System.IO.Pipes;
using System.Text;

namespace ScreenReader.Interop;

/// <summary>
/// Tester NVDA Controller Client API - do testowania mostu
/// Uruchom ten tester gdy Titan Screen Reader działa
/// </summary>
public static class NVDAControllerTester
{
    private const string PipeName = "NVDA_controllerClient";

    public static void RunTests()
    {
        Console.WriteLine("=== NVDA Controller Bridge Tester ===");
        Console.WriteLine();

        // Test 1: testIfRunning
        Console.WriteLine("Test 1: testIfRunning");
        int result = TestIfRunning();
        Console.WriteLine($"Result: {result} (0 = screen reader działa)");
        Console.WriteLine();

        if (result != 0)
        {
            Console.WriteLine("BŁĄD: Screen reader nie odpowiada lub nie działa!");
            return;
        }

        // Test 2: speakText
        Console.WriteLine("Test 2: speakText");
        result = SpeakText("To jest test NVDA Controller Bridge");
        Console.WriteLine($"Result: {result} (0 = sukces)");
        Console.WriteLine();

        System.Threading.Thread.Sleep(2000);

        // Test 3: cancelSpeech
        Console.WriteLine("Test 3: cancelSpeech");
        result = CancelSpeech();
        Console.WriteLine($"Result: {result} (0 = sukces)");
        Console.WriteLine();

        // Test 4: speakText z polskimi znakami
        Console.WriteLine("Test 4: speakText (polskie znaki)");
        result = SpeakText("Cześć! To jest test z polskimi znakami: ąćęłńóśźż");
        Console.WriteLine($"Result: {result} (0 = sukces)");
        Console.WriteLine();

        Console.WriteLine("=== Testy zakończone ===");
    }

    private static int TestIfRunning()
    {
        try
        {
            using var pipe = new NamedPipeClientStream(".", PipeName, PipeDirection.InOut);
            pipe.Connect(1000); // Timeout 1s

            // Wyślij function ID = 0 (testIfRunning)
            byte[] functionId = BitConverter.GetBytes(0);
            pipe.Write(functionId, 0, 4);

            // Odbierz wynik
            byte[] result = new byte[4];
            pipe.Read(result, 0, 4);
            return BitConverter.ToInt32(result, 0);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Błąd: {ex.Message}");
            return -1;
        }
    }

    private static int SpeakText(string text)
    {
        try
        {
            using var pipe = new NamedPipeClientStream(".", PipeName, PipeDirection.InOut);
            pipe.Connect(1000); // Timeout 1s

            // Wyślij function ID = 1 (speakText)
            byte[] functionId = BitConverter.GetBytes(1);
            pipe.Write(functionId, 0, 4);

            // Wyślij długość tekstu w znakach
            byte[] length = BitConverter.GetBytes(text.Length);
            pipe.Write(length, 0, 4);

            // Wyślij tekst (UTF-16LE)
            byte[] textBytes = Encoding.Unicode.GetBytes(text);
            pipe.Write(textBytes, 0, textBytes.Length);

            // Odbierz wynik
            byte[] result = new byte[4];
            pipe.Read(result, 0, 4);
            return BitConverter.ToInt32(result, 0);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Błąd: {ex.Message}");
            return -1;
        }
    }

    private static int CancelSpeech()
    {
        try
        {
            using var pipe = new NamedPipeClientStream(".", PipeName, PipeDirection.InOut);
            pipe.Connect(1000); // Timeout 1s

            // Wyślij function ID = 2 (cancelSpeech)
            byte[] functionId = BitConverter.GetBytes(2);
            pipe.Write(functionId, 0, 4);

            // Odbierz wynik
            byte[] result = new byte[4];
            pipe.Read(result, 0, 4);
            return BitConverter.ToInt32(result, 0);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Błąd: {ex.Message}");
            return -1;
        }
    }
}
