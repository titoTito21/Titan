using NVorbis;

namespace ScreenReader.Speech;

/// <summary>
/// Dekoder OGG Vorbis do formatu PCM float array
/// </summary>
public static class OggDecoder
{
    /// <summary>
    /// Dekoduje plik OGG Vorbis do tablicy PCM (float samples)
    /// </summary>
    /// <param name="oggStream">Strumień OGG Vorbis do zdekodowania</param>
    /// <returns>Tablica próbek PCM (float)</returns>
    public static float[] DecodeToPCM(Stream oggStream)
    {
        using var vorbis = new VorbisReader(oggStream, false);

        // Odczytaj wszystkie próbki
        var samples = new List<float>();
        var buffer = new float[4096];
        int count;

        while ((count = vorbis.ReadSamples(buffer, 0, buffer.Length)) > 0)
        {
            for (int i = 0; i < count; i++)
                samples.Add(buffer[i]);
        }

        Console.WriteLine($"OggDecoder: Zdekodowano {samples.Count} próbek ({samples.Count / (float)vorbis.SampleRate:F2}s @ {vorbis.SampleRate}Hz)");
        return samples.ToArray();
    }

    /// <summary>
    /// Dekoduje OGG Vorbis z przesunięciem wysokości tonu (pitch)
    /// </summary>
    /// <param name="oggStream">Strumień OGG Vorbis</param>
    /// <param name="pitchFactor">Współczynnik pitch (1.0 = normalna, >1.0 = wyższy, <1.0 = niższy)</param>
    /// <returns>Tablica próbek PCM ze zmienionym pitch</returns>
    public static float[] DecodeWithPitch(Stream oggStream, float pitchFactor)
    {
        var samples = DecodeToPCM(oggStream);
        return PitchShifter.Shift(samples, pitchFactor);
    }
}
