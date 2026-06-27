using System.Reflection;
using NAudio.Wave;
using NAudio.Vorbis;

namespace ScreenReader.Speech;

/// <summary>
/// Menedżer dźwięków UI - ORYGINALNA implementacja z Titan ScreenReader
/// Prosta, szybka, bez spatial audio
/// </summary>
public class SoundManager : IDisposable
{
    private readonly Assembly _assembly;
    private bool _globalSoundsEnabled = true;
    private bool _disposed;

    /// <summary>Globalna flaga włączenia/wyłączenia dźwięków</summary>
    public static bool GlobalSoundsEnabled { get; set; } = true;

    public SoundManager()
    {
        _assembly = Assembly.GetExecutingAssembly();
        Console.WriteLine("SoundManager: Initialized (embedded resources, original implementation)");
    }

    public SoundManager(string soundsDirectory) : this()
    {
        // Konstruktor dla kompatybilności - ignorujemy soundsDirectory, używamy embedded resources
    }

    /// <summary>
    /// Odtwarza dźwięk asynchronicznie z embedded resource
    /// </summary>
    private void PlaySound(string soundFileName, float azimuth = 0f, float elevation = 0f, float pitch = 1.0f)
    {
        if (!GlobalSoundsEnabled || !_globalSoundsEnabled)
            return;

        // Fire-and-forget async playback to avoid blocking
        _ = Task.Run(() => PlaySoundAsync(soundFileName, azimuth, elevation, pitch))
            .ContinueWith(t =>
            {
                if (t.Exception != null)
                    Console.WriteLine($"Błąd odtwarzania dźwięku w tle: {t.Exception.InnerException?.Message}");
            }, TaskContinuationOptions.OnlyOnFaulted);
    }

    /// <summary>
    /// Asynchroniczne odtwarzanie dźwięku - nie blokuje wątku wywołującego
    /// </summary>
    private async Task PlaySoundAsync(string soundFileName, float azimuth, float elevation, float pitch)
    {
        try
        {
            var resourceName = $"ScreenReader.SFX.{soundFileName}";
            var stream = _assembly.GetManifestResourceStream(resourceName);

            if (stream == null)
            {
                Console.WriteLine($"Brak zasobu dźwiękowego: {resourceName}");
                return;
            }

            // Don't stop previous sounds - allow overlap with TTS
            var waveOut = new WaveOutEvent();

            var vorbisReader = new VorbisWaveReader(stream);

            // Apply pitch shifting if needed
            ISampleProvider sampleProvider = vorbisReader.ToSampleProvider();
            if (Math.Abs(pitch - 1.0f) > 0.01f)
            {
                sampleProvider = new PitchShiftingSampleProvider(sampleProvider, pitch);
            }

            // Apply stereo panning based on azimuth
            if (Math.Abs(azimuth) > 0.01f)
            {
                sampleProvider = new StereoPanningSampleProvider(sampleProvider, azimuth);
            }

            waveOut.Init(sampleProvider);

            // Create TaskCompletionSource to await playback completion
            var tcs = new TaskCompletionSource<bool>();

            // Dispose after playback finishes
            waveOut.PlaybackStopped += (s, e) =>
            {
                waveOut.Dispose();
                vorbisReader.Dispose();
                stream.Dispose();
                tcs.TrySetResult(true);
            };

            waveOut.Play();

            // Wait for playback to complete
            await tcs.Task;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Błąd odtwarzania dźwięku: {ex.Message}");
        }
    }

    // ===== DŹWIĘKI UI =====

    public void PlayClicked(float azimuth = 0f, float elevation = 0f)
        => PlaySound("clicked.ogg");

    public void PlayCursor(float azimuth = 0f, float elevation = 0f)
        => PlaySound("cursor.ogg");

    public void PlayCursorStatic(float azimuth = 0f, float elevation = 0f)
        => PlaySound("cursor_static.ogg");

    public void PlayZoomIn(float azimuth = 0f, float elevation = 0f)
        => PlaySound("zoomin.ogg");

    public void PlayZoomOut(float azimuth = 0f, float elevation = 0f)
        => PlaySound("zoomout.ogg");

    public void PlayEdge(float azimuth = 0f, float elevation = 0f)
        => PlaySound("edge.ogg");

    public void PlayListItem(float position, float azimuth = 0f, float elevation = 0f)
    {
        // Position: 0.0 = top (higher pitch), 1.0 = bottom (lower pitch)
        // Map to pitch range: 1.5 (high) to 0.7 (low)
        float pitch = 1.5f - (position * 0.8f);
        PlaySound("listitem.ogg", azimuth, elevation, pitch);
    }

    public void PlayWindow(float azimuth = 0f, float elevation = 0f)
        => PlaySound("window.ogg");

    public void PlayDialItem(float azimuth = 0f, float elevation = 0f)
        => PlaySound("srcursor_item.ogg");

    public void PlayMenuExpanded(float azimuth = 0f, float elevation = 0f)
        => PlaySound("menu_expanded.ogg");

    public void PlayMenuClosed(float azimuth = 0f, float elevation = 0f)
        => PlaySound("menu_closed.ogg");

    public void PlayCanInteract(float azimuth = 0f, float elevation = 0f)
        => PlaySound("caninteract.ogg");

    public void PlayKeyOn(float azimuth = 0f, float elevation = 0f)
        => PlaySound("keyon.ogg");

    public void PlayKeyOff(float azimuth = 0f, float elevation = 0f)
        => PlaySound("keyoff.ogg");

    public void PlayEnterTCE(float azimuth = 0f, float elevation = 0f)
        => PlaySound("enter_TCE.ogg");

    public void PlayLeaveTCE(float azimuth = 0f, float elevation = 0f)
        => PlaySound("leave_TCE.ogg");

    public void PlaySROn(float azimuth = 0f, float elevation = 0f)
        => PlaySound("sron.ogg");

    public void PlaySROff(float azimuth = 0f, float elevation = 0f)
        => PlaySound("sroff.ogg");

    public void PlayVirtualScreenOn(float azimuth = 0f, float elevation = 0f)
        => PlaySound("vscreenOn.ogg");

    public void PlayVirtualScreenOff(float azimuth = 0f, float elevation = 0f)
        => PlaySound("vscreenOff.ogg");

    public void PlayDoubleClick(float azimuth = 0f, float elevation = 0f)
        => PlaySound("doubletab.ogg");

    public void PlaySystemItem(float azimuth = 0f, float elevation = 0f)
        => PlaySound("system_item.ogg");

    public void PlayNotification(float azimuth = 0f, float elevation = 0f)
        => PlaySound("notification.ogg");

    public void PlayError(float azimuth = 0f, float elevation = 0f)
        => PlaySound("error.ogg");

    public void Stop()
    {
        // With overlapping sounds, Stop() doesn't need to do anything
        // Each sound will dispose itself when finished
    }

    public void Dispose()
    {
        if (_disposed)
            return;

        _disposed = true;
        Console.WriteLine("SoundManager: Disposed");
    }
}

/// <summary>
/// Simple pitch shifting by changing playback rate (ORYGINALNY kod z Titan)
/// </summary>
public class PitchShiftingSampleProvider : ISampleProvider
{
    private readonly ISampleProvider _source;
    private readonly float _pitchFactor;

    public PitchShiftingSampleProvider(ISampleProvider source, float pitchFactor)
    {
        _source = source;
        _pitchFactor = pitchFactor;
        WaveFormat = WaveFormat.CreateIeeeFloatWaveFormat(
            (int)(source.WaveFormat.SampleRate * pitchFactor),
            source.WaveFormat.Channels);
    }

    public WaveFormat WaveFormat { get; }

    public int Read(float[] buffer, int offset, int count)
    {
        return _source.Read(buffer, offset, count);
    }
}

/// <summary>
/// Stereo panning provider - converts mono to stereo with left/right panning based on azimuth.
/// Azimuth is in radians: negative = left, positive = right.
/// </summary>
public class StereoPanningSampleProvider : ISampleProvider
{
    private readonly ISampleProvider _source;
    private readonly float _leftGain;
    private readonly float _rightGain;

    public StereoPanningSampleProvider(ISampleProvider source, float azimuth)
    {
        _source = source;

        // Map azimuth (radians) to pan value in [-1, 1]
        float pan = Math.Clamp(azimuth / (MathF.PI / 2), -1f, 1f);
        _leftGain = Math.Min(1f, 1f - pan);
        _rightGain = Math.Min(1f, 1f + pan);

        // Output is always stereo at the same sample rate as source
        WaveFormat = WaveFormat.CreateIeeeFloatWaveFormat(
            source.WaveFormat.SampleRate, 2);
    }

    public WaveFormat WaveFormat { get; }

    public int Read(float[] buffer, int offset, int count)
    {
        // count is in stereo samples (pairs), so we need half as many mono samples
        int monoSamplesNeeded = count / 2;
        float[] monoBuffer = new float[monoSamplesNeeded];
        int monoSamplesRead = _source.Read(monoBuffer, 0, monoSamplesNeeded);

        // Write interleaved stereo samples with panning applied
        for (int i = 0; i < monoSamplesRead; i++)
        {
            buffer[offset + i * 2] = monoBuffer[i] * _leftGain;
            buffer[offset + i * 2 + 1] = monoBuffer[i] * _rightGain;
        }

        return monoSamplesRead * 2;
    }
}
