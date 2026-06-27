namespace ScreenReader.Speech;

/// <summary>
/// Przesunięcie wysokości tonu (pitch shifting) dla próbek PCM
/// Używa prostego algorytmu resamplingu z interpolacją liniową
/// </summary>
public static class PitchShifter
{
    /// <summary>
    /// Przesuwa wysokość tonu próbek PCM
    /// </summary>
    /// <param name="samples">Tablica próbek PCM (float)</param>
    /// <param name="pitchFactor">Współczynnik pitch:
    /// - 1.0 = normalna wysokość
    /// - >1.0 = wyższy ton (szybciej)
    /// - <1.0 = niższy ton (wolniej)
    /// Przykład: 1.5 = ton o 50% wyższy, 0.7 = ton o 30% niższy</param>
    /// <returns>Nowa tablica próbek z przesunięciem pitch</returns>
    public static float[] Shift(float[] samples, float pitchFactor)
    {
        // Jeśli pitch ~= 1.0, zwróć oryginał (bez zmian)
        if (Math.Abs(pitchFactor - 1.0f) < 0.01f)
            return samples;

        // Clamp pitch do rozsądnego zakresu
        pitchFactor = Math.Clamp(pitchFactor, 0.5f, 2.0f);

        // Oblicz nową długość
        int newLength = (int)(samples.Length / pitchFactor);
        var result = new float[newLength];

        // Resampling z interpolacją liniową
        for (int i = 0; i < newLength; i++)
        {
            float position = i * pitchFactor;
            int index = (int)position;
            float frac = position - index;

            if (index + 1 < samples.Length)
            {
                // Interpolacja liniowa między dwoma próbkami
                result[i] = samples[index] * (1 - frac) + samples[index + 1] * frac;
            }
            else if (index < samples.Length)
            {
                // Ostatnia próbka bez interpolacji
                result[i] = samples[index];
            }
        }

        return result;
    }
}
