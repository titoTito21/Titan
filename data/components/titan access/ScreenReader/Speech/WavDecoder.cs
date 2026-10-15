using NAudio.Wave;

namespace ScreenReader.Speech;

/// <summary>
/// Dekoder WAV do formatu PCM dla Windows Spatial Audio
/// Używane do przechwytywania i konwersji outputu z SAPI5/OneCore TTS
/// </summary>
public static class WavDecoder
{
    /// <summary>
    /// Dekoduje strumień WAV do tablicy PCM float (mono, 48kHz jeśli resampling się powiedzie)
    /// </summary>
    /// <param name="wavStream">Strumień WAV (z SAPI5 lub OneCore)</param>
    /// <returns>Krotka (samples, sampleRate) - próbki PCM i rzeczywisty sample rate</returns>
    public static (float[] samples, int sampleRate) DecodeToPCM(Stream wavStream)
    {
        using var reader = new WaveFileReader(wavStream);
        var samples = new List<float>();
        var buffer = new float[4096];
        int count;
        int actualSampleRate;

        // Konwertuj do ISampleProvider
        var provider = reader.ToSampleProvider();

        // Konwertuj stereo → mono jeśli potrzebne
        if (provider.WaveFormat.Channels > 1)
        {
            provider = provider.ToMono();
            Console.WriteLine("WavDecoder: Konwersja stereo → mono");
        }

        // Resample do 48kHz jeśli potrzebne (wymagane przez Spatial Audio)
        if (provider.WaveFormat.SampleRate != 48000)
        {
            Console.WriteLine($"WavDecoder: Resampling {provider.WaveFormat.SampleRate}Hz → 48000Hz");
            try
            {
                var targetFormat = WaveFormat.CreateIeeeFloatWaveFormat(48000, provider.WaveFormat.Channels);
                var resampler = new MediaFoundationResampler(provider.ToWaveProvider(), targetFormat);
                provider = resampler.ToSampleProvider();
                actualSampleRate = 48000;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"WavDecoder: Resampling nie powiódł się, używam oryginalnego sample rate: {ex.Message}");
                actualSampleRate = provider.WaveFormat.SampleRate;
            }
        }
        else
        {
            actualSampleRate = 48000;
        }

        // Odczytaj wszystkie próbki
        while ((count = provider.Read(buffer, 0, buffer.Length)) > 0)
        {
            for (int i = 0; i < count; i++)
                samples.Add(buffer[i]);
        }

        Console.WriteLine($"WavDecoder: Zdekodowano {samples.Count} próbek ({samples.Count / (float)actualSampleRate:F2}s @ {actualSampleRate}Hz)");
        return (samples.ToArray(), actualSampleRate);
    }
}
