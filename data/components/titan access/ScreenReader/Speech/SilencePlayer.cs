using NAudio.Wave;

namespace ScreenReader.Speech;

/// <summary>
/// Odtwarza ciągły strumień niemal niesłyszalnej ciszy w tle,
/// aby zapobiec usypianiu/wyciszaniu karty dźwiękowej.
///
/// Niektóre karty dźwiękowe (szczególnie USB, Bluetooth i zintegrowane)
/// wyłączają wyjście audio po kilku sekundach ciszy, co powoduje:
/// - Opóźnienie (~200-500ms) przed pierwszym dźwiękiem mowy
/// - Trzaski/kliknięcia przy starcie odtwarzania
/// - Ucięcie początku wypowiedzi
///
/// Technika stosowana przez NVDA (nvwave.py), JAWS i inne czytniki ekranu.
/// Strumień ciszy jest na poziomie ~-96dB (1 LSB dla 16-bit) - niesłyszalny,
/// ale wystarczający żeby karta dźwiękowa nie przeszła w tryb oszczędzania energii.
/// </summary>
public class SilencePlayer : IDisposable
{
    private WaveOutEvent? _waveOut;
    private SilenceWaveProvider? _silenceProvider;
    private bool _disposed;
    private bool _isRunning;
    private readonly object _lock = new();

    /// <summary>Czy silence jest aktywne</summary>
    public bool IsRunning => _isRunning;

    /// <summary>
    /// Uruchamia odtwarzanie ciszy w tle
    /// </summary>
    public void Start()
    {
        lock (_lock)
        {
            if (_isRunning || _disposed)
                return;

            try
            {
                _silenceProvider = new SilenceWaveProvider();
                _waveOut = new WaveOutEvent
                {
                    // Duży bufor = mniejsze obciążenie CPU
                    DesiredLatency = 200,
                    NumberOfBuffers = 3
                };

                _waveOut.Init(_silenceProvider);
                _waveOut.Play();
                _isRunning = true;
                Console.WriteLine("SilencePlayer: Uruchomiono - karta dźwiękowa utrzymywana aktywna");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"SilencePlayer: Nie udało się uruchomić: {ex.Message}");
                _waveOut?.Dispose();
                _waveOut = null;
                _silenceProvider = null;
            }
        }
    }

    /// <summary>
    /// Zatrzymuje odtwarzanie ciszy
    /// </summary>
    public void Stop()
    {
        lock (_lock)
        {
            if (!_isRunning)
                return;

            _isRunning = false;

            try
            {
                _waveOut?.Stop();
                _waveOut?.Dispose();
                _waveOut = null;
                _silenceProvider = null;
                Console.WriteLine("SilencePlayer: Zatrzymano");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"SilencePlayer: Błąd zatrzymywania: {ex.Message}");
            }
        }
    }

    public void Dispose()
    {
        if (_disposed)
            return;

        _disposed = true;
        Stop();
    }

    /// <summary>
    /// WaveProvider generujący niemal niesłyszalną ciszę.
    /// Generuje sygnał na poziomie 1 LSB (least significant bit) dla PCM 16-bit,
    /// co odpowiada ~-96dB - poniżej progu słyszalności, ale wystarczające
    /// żeby DAC karty dźwiękowej nie przeszedł w standby.
    /// </summary>
    private class SilenceWaveProvider : IWaveProvider
    {
        // 16-bit PCM, mono, 44.1kHz - minimalny format
        public WaveFormat WaveFormat { get; } = new WaveFormat(44100, 16, 1);

        // Licznik próbek - co N-tą próbkę wstawiamy 1 LSB zamiast zera,
        // żeby DAC nie mógł wykryć "prawdziwej ciszy" i się wyłączyć
        private int _sampleCounter;

        public int Read(byte[] buffer, int offset, int count)
        {
            // Wypełnij bufor (prawie) zerami
            for (int i = 0; i < count; i += 2) // 2 bajty na próbkę (16-bit)
            {
                _sampleCounter++;

                // Co 441 próbek (co ~10ms) wstaw minimalny sygnał (1 LSB = -96dB)
                // Jest to niesłyszalne ale utrzymuje DAC aktywny
                if (_sampleCounter % 441 == 0)
                {
                    buffer[offset + i] = 1;     // LSB = 1
                    buffer[offset + i + 1] = 0;  // MSB = 0 → wartość próbki = 1 (z 32768 max)
                }
                else
                {
                    buffer[offset + i] = 0;
                    buffer[offset + i + 1] = 0;
                }
            }

            return count;
        }
    }
}
