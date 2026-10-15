using System.Runtime.InteropServices;
using NAudio.CoreAudioApi;

namespace ScreenReader.Speech;

/// <summary>
/// Renderer audio 3D używający Windows Spatial Audio API (ISpatialAudioClient)
/// Wymaga Windows 10 1903+ dla pełnego wsparcia ISpatialAudioClient2
/// </summary>
public class SpatialAudioRenderer : IDisposable
{
    private ISpatialAudioClient? _client;
    private ISpatialAudioObjectRenderStream? _stream;
    private MMDevice? _device;
    private bool _isInitialized;
    private readonly object _lock = new object();
    private bool _disposed;

    public bool IsInitialized => _isInitialized;

    public SpatialAudioRenderer()
    {
        // Inicjalizacja odłożona - wywołaj Initialize() explicite
    }

    /// <summary>
    /// Inicjalizuje Windows Spatial Audio API
    /// </summary>
    public void Initialize()
    {
        if (_isInitialized)
        {
            Console.WriteLine("SpatialAudioRenderer: Już zainicjalizowany");
            return;
        }

        try
        {
            Console.WriteLine("SpatialAudioRenderer: Inicjalizacja Windows Spatial Audio...");

            // 1. Inicjalizacja COM
            int hr = SpatialAudioNative.CoInitializeEx(IntPtr.Zero, SpatialAudioNative.COINIT_MULTITHREADED);
            if (hr < 0 && hr != 1) // 1 = S_FALSE (już zainicjalizowany)
            {
                Console.WriteLine($"SpatialAudioRenderer: CoInitializeEx zwrócił HRESULT=0x{hr:X8}");
            }

            // 2. Pobierz domyślne urządzenie audio
            var enumerator = new MMDeviceEnumerator();
            _device = enumerator.GetDefaultAudioEndpoint(DataFlow.Render, Role.Multimedia);
            Console.WriteLine($"SpatialAudioRenderer: Urządzenie: {_device.FriendlyName}");

            // 3. Aktywuj ISpatialAudioClient przez IMMDevice COM interface
            var iid = typeof(ISpatialAudioClient).GUID;
            IntPtr pUnk = Marshal.GetIUnknownForObject(_device);
            IMMDevice immDevice;
            try
            {
                immDevice = (IMMDevice)Marshal.GetObjectForIUnknown(pUnk);
            }
            finally
            {
                Marshal.Release(pUnk);
            }
            hr = immDevice.Activate(iid, CLSCTX.CLSCTX_ALL, IntPtr.Zero, out object clientObj);
            if (hr != SpatialAudioNative.S_OK)
            {
                Console.WriteLine($"SpatialAudioRenderer: IMMDevice.Activate failed (HRESULT=0x{hr:X8})");
                _isInitialized = false;
                return;
            }
            _client = (ISpatialAudioClient)clientObj;
            Console.WriteLine("SpatialAudioRenderer: ISpatialAudioClient aktywowany");

            // 4. Konfiguruj format audio (48kHz, mono, 32-bit float)
            var format = new WaveFormatEx
            {
                wFormatTag = 3,           // WAVE_FORMAT_IEEE_FLOAT
                nChannels = 1,            // Mono dla obiektów przestrzennych
                nSamplesPerSec = 48000,   // 48 kHz
                wBitsPerSample = 32,      // 32-bit float
                nBlockAlign = 4,          // 1 channel * 4 bytes
                nAvgBytesPerSec = 192000, // 48000 * 4
                cbSize = 0
            };

            // 5. Sprawdź czy format jest wspierany
            hr = _client.IsAudioObjectFormatSupported(ref format);
            if (hr != SpatialAudioNative.S_OK)
            {
                Console.WriteLine($"SpatialAudioRenderer: Format audio nie jest wspierany (HRESULT=0x{hr:X8})");
                _isInitialized = false;
                return;
            }

            // 6. Konfiguruj parametry aktywacji strumienia
            var activationParams = new SpatialAudioObjectRenderStreamActivationParams
            {
                ObjectFormat = format,
                StaticObjectTypeMask = 0, // Używamy tylko dynamicznych obiektów
                MinDynamicObjectCount = 4,  // Minimum 4 jednoczesne dźwięki
                MaxDynamicObjectCount = 16, // Maksimum 16 jednoczesnych dźwięków
                Category = SpatialAudioNative.AudioCategory_Speech,
                EventHandle = IntPtr.Zero,
                NotifyObject = IntPtr.Zero
            };

            // 7. Aktywuj strumień renderowania
            var streamIID = typeof(ISpatialAudioObjectRenderStream).GUID;
            hr = _client.ActivateSpatialAudioStream(
                ref activationParams,
                ref streamIID,
                out object streamObj);

            if (hr != SpatialAudioNative.S_OK)
            {
                Console.WriteLine($"SpatialAudioRenderer: ActivateSpatialAudioStream failed (HRESULT=0x{hr:X8})");
                _isInitialized = false;
                return;
            }

            _stream = (ISpatialAudioObjectRenderStream)streamObj;

            _isInitialized = true;
            Console.WriteLine("SpatialAudioRenderer: ✅ Inicjalizacja zakończona sukcesem!");
        }
        catch (Exception ex)
        {
            Console.WriteLine($"SpatialAudioRenderer: ❌ Błąd inicjalizacji: {ex.Message}");
            Console.WriteLine($"  Stack trace: {ex.StackTrace}");
            _isInitialized = false;
        }
    }

    /// <summary>
    /// Odtwarza próbki PCM z pozycjonowaniem 3D
    /// </summary>
    /// <param name="pcmSamples">Tablica próbek PCM (mono, 48kHz, float)</param>
    /// <param name="azimuth">Kąt azymutalny w radianach (-π/2 lewo, 0 centrum, +π/2 prawo)</param>
    /// <param name="elevation">Kąt elewacji w radianach (-π/4 dół, 0 poziom, +π/4 góra)</param>
    /// <param name="distance">Odległość od słuchacza (domyślnie 1.0)</param>
    public void PlaySpatial(float[] pcmSamples, float azimuth, float elevation, float distance = 1.0f)
    {
        if (!_isInitialized || _stream == null)
        {
            Console.WriteLine("SpatialAudioRenderer: Nie zainicjalizowany, pomijam odtwarzanie");
            return;
        }

        if (pcmSamples == null || pcmSamples.Length == 0)
        {
            Console.WriteLine("SpatialAudioRenderer: Pusta tablica próbek");
            return;
        }

        lock (_lock)
        {
            try
            {
                // 1. Rozpocznij aktualizację obiektów audio
                int hr = _stream.BeginUpdatingAudioObjects(out uint availableCount, out uint frameCount);
                if (hr != SpatialAudioNative.S_OK)
                {
                    Console.WriteLine($"SpatialAudioRenderer: BeginUpdatingAudioObjects failed (HRESULT=0x{hr:X8})");
                    return;
                }

                if (availableCount == 0)
                {
                    Console.WriteLine("SpatialAudioRenderer: Brak dostępnych obiektów dynamicznych");
                    _stream.EndUpdatingAudioObjects();
                    return;
                }

                // 2. Aktywuj dynamiczny obiekt audio
                hr = _stream.ActivateSpatialAudioObject(
                    SpatialAudioNative.AudioObjectType_Dynamic,
                    out ISpatialAudioObject audioObject);

                if (hr != SpatialAudioNative.S_OK || audioObject == null)
                {
                    Console.WriteLine($"SpatialAudioRenderer: ActivateSpatialAudioObject failed (HRESULT=0x{hr:X8})");
                    _stream.EndUpdatingAudioObjects();
                    return;
                }

                // 3. Konwertuj współrzędne sferyczne → kartezjańskie
                // Azimuth: 0 = przód, +π/2 = prawo, -π/2 = lewo
                // Elevation: 0 = poziom, +π/4 = góra, -π/4 = dół
                float x = distance * MathF.Sin(azimuth) * MathF.Cos(elevation);
                float y = distance * MathF.Sin(elevation);
                float z = distance * MathF.Cos(azimuth) * MathF.Cos(elevation);

                // 4. Ustaw pozycję 3D
                hr = audioObject.SetPosition(x, y, z);
                if (hr != SpatialAudioNative.S_OK)
                {
                    Console.WriteLine($"SpatialAudioRenderer: SetPosition({x:F2}, {y:F2}, {z:F2}) failed (HRESULT=0x{hr:X8})");
                }

                // 5. Ustaw głośność
                hr = audioObject.SetVolume(1.0f);
                if (hr != SpatialAudioNative.S_OK)
                {
                    Console.WriteLine($"SpatialAudioRenderer: SetVolume failed (HRESULT=0x{hr:X8})");
                }

                // 6. Pobierz bufor i zapisz próbki
                hr = audioObject.GetBuffer(out IntPtr bufferPtr, out uint bufferLength);
                if (hr != SpatialAudioNative.S_OK)
                {
                    Console.WriteLine($"SpatialAudioRenderer: GetBuffer failed (HRESULT=0x{hr:X8})");
                    _stream.EndUpdatingAudioObjects();
                    return;
                }

                // Oblicz ile próbek można zapisać
                int maxSamples = (int)(bufferLength / sizeof(float));
                int sampleCount = Math.Min(pcmSamples.Length, maxSamples);

                // Skopiuj próbki do bufora
                Marshal.Copy(pcmSamples, 0, bufferPtr, sampleCount);

                // 7. Oznacz koniec strumienia
                hr = audioObject.SetEndOfStream((uint)sampleCount);
                if (hr != SpatialAudioNative.S_OK)
                {
                    Console.WriteLine($"SpatialAudioRenderer: SetEndOfStream failed (HRESULT=0x{hr:X8})");
                }

                // 8. Zakończ aktualizację obiektów
                hr = _stream.EndUpdatingAudioObjects();
                if (hr != SpatialAudioNative.S_OK)
                {
                    Console.WriteLine($"SpatialAudioRenderer: EndUpdatingAudioObjects failed (HRESULT=0x{hr:X8})");
                }

                Console.WriteLine($"SpatialAudioRenderer: ✅ Odtwarzanie {sampleCount} próbek @ ({x:F2}, {y:F2}, {z:F2}) [azimuth={azimuth * 180 / MathF.PI:F0}°, elevation={elevation * 180 / MathF.PI:F0}°]");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"SpatialAudioRenderer: ❌ Błąd odtwarzania: {ex.Message}");
                try
                {
                    _stream.EndUpdatingAudioObjects();
                }
                catch { }
            }
        }
    }

    public void Dispose()
    {
        if (_disposed)
            return;

        _disposed = true;

        Console.WriteLine("SpatialAudioRenderer: Disposing...");

        // Zwolnij COM objects
        if (_stream != null)
        {
            try
            {
                Marshal.ReleaseComObject(_stream);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"SpatialAudioRenderer: Error releasing stream: {ex.Message}");
            }
            _stream = null;
        }

        if (_client != null)
        {
            try
            {
                Marshal.ReleaseComObject(_client);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"SpatialAudioRenderer: Error releasing client: {ex.Message}");
            }
            _client = null;
        }

        _device?.Dispose();
        _device = null;

        // Deinicjalizacja COM
        try
        {
            SpatialAudioNative.CoUninitialize();
        }
        catch { }

        _isInitialized = false;
        Console.WriteLine("SpatialAudioRenderer: Disposed");
    }
}
