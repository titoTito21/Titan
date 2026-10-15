using System.Runtime.InteropServices;

namespace ScreenReader.Interop;

/// <summary>
/// Rejestruje program jako czytnik ekranu w systemie Windows.
/// To powoduje że aplikacje (np. MS Office) wysyłają specjalne komunikaty dla czytników.
/// </summary>
public static class ScreenReaderFlag
{
    private const uint SPI_SETSCREENREADER = 0x0047;
    private const uint SPI_GETSCREENREADER = 0x0046;
    private const uint SPIF_UPDATEINIFILE = 0x01;
    private const uint SPIF_SENDCHANGE = 0x02;

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool SystemParametersInfo(uint uiAction, uint uiParam, IntPtr pvParam, uint fWinIni);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool SystemParametersInfo(uint uiAction, uint uiParam, out bool pvParam, uint fWinIni);

    /// <summary>
    /// Włącza flagę screen readera w systemie
    /// </summary>
    public static bool Enable()
    {
        try
        {
            // Ustaw flagę że screen reader jest aktywny
            bool result = SystemParametersInfo(
                SPI_SETSCREENREADER,
                1, // TRUE - screen reader jest włączony
                IntPtr.Zero,
                SPIF_UPDATEINIFILE | SPIF_SENDCHANGE);

            if (result)
            {
                Console.WriteLine("ScreenReaderFlag: Zarejestrowano jako czytnik ekranu");
            }
            else
            {
                int error = Marshal.GetLastWin32Error();
                Console.WriteLine($"ScreenReaderFlag: Błąd rejestracji, kod: {error}");
            }

            return result;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"ScreenReaderFlag: Wyjątek: {ex.Message}");
            return false;
        }
    }

    /// <summary>
    /// Wyłącza flagę screen readera w systemie
    /// </summary>
    public static bool Disable()
    {
        try
        {
            bool result = SystemParametersInfo(
                SPI_SETSCREENREADER,
                0, // FALSE - screen reader jest wyłączony
                IntPtr.Zero,
                SPIF_UPDATEINIFILE | SPIF_SENDCHANGE);

            if (result)
            {
                Console.WriteLine("ScreenReaderFlag: Wyrejestrowano czytnik ekranu");
            }

            return result;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"ScreenReaderFlag: Wyjątek: {ex.Message}");
            return false;
        }
    }

    /// <summary>
    /// Sprawdza czy flaga screen readera jest włączona
    /// </summary>
    public static bool IsEnabled()
    {
        try
        {
            bool isEnabled = false;
            SystemParametersInfo(SPI_GETSCREENREADER, 0, out isEnabled, 0);
            return isEnabled;
        }
        catch
        {
            return false;
        }
    }
}
