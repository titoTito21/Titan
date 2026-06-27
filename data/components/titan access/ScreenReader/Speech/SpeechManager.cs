using System.IO;
using System.Speech.Synthesis;
using System.Globalization;
using Microsoft.Win32;
using NAudio.Wave;
using ScreenReader.Speech;
using ScreenReader.Settings;

namespace ScreenReader;

public enum SynthesizerType
{
    SAPI5,
    OneCore,
    BestSpeech
}

public class SpeechManager : IDisposable
{
    private readonly SpeechSynthesizer _synthesizer;
    private OneCoreEngine? _oneCoreEngine;
    private BestSpeechEngine? _bestSpeechEngine;
    private SynthesizerType _currentSynthesizer;
    private SpatialAudioRenderer? _spatialRenderer;
    private readonly SilencePlayer _silencePlayer;
    private bool _disposed;
    private bool _isWarmedUp;
    private int _pitch; // Przechowuj wartość pitch (SAPI5 nie obsługuje, tylko OneCore)
    private int _rate; // Centralna wartość rate (-10..10) dla wszystkich syntezatorów
    private int _volume = 100; // Centralna wartość volume (0..100) dla wszystkich syntezatorów

    public SpeechManager()
    {
        // Initialize SAPI5 synthesizer
        _synthesizer = new SpeechSynthesizer();
        _synthesizer.SetOutputToDefaultAudioDevice();

        // Uruchom cichy strumień w tle - zapobiega usypianiu karty dźwiękowej
        _silencePlayer = new SilencePlayer();
        _silencePlayer.Start();

        // Rozgrzej syntezator SAPI5 dla lepszej responsywności
        WarmUpSynthesizer();

        // Initialize spatial renderer for 3D TTS
        _spatialRenderer = new SpatialAudioRenderer();
        _spatialRenderer.Initialize();

        // Pobierz ustawienia
        var settings = SettingsManager.Instance;

        // Try to set Polish voice
        try
        {
            var polishVoice = _synthesizer.GetInstalledVoices()
                .FirstOrDefault(v => v.VoiceInfo.Culture.TwoLetterISOLanguageName == "pl");

            if (polishVoice != null)
            {
                _synthesizer.SelectVoice(polishVoice.VoiceInfo.Name);
                Console.WriteLine($"Używam głosu SAPI5: {polishVoice.VoiceInfo.Name}");
            }
            else
            {
                Console.WriteLine("Uwaga: Brak polskiego głosu TTS. Używam domyślnego.");
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Błąd wyboru głosu: {ex.Message}");
        }

        // Załaduj szybkość, głośność i pitch z ustawień
        int savedRate = settings.Rate;
        int savedVolume = settings.Volume;
        _pitch = settings.Pitch;

        _rate = Math.Clamp(savedRate, -10, 10);
        _volume = Math.Clamp(savedVolume, 0, 100);
        _synthesizer.Rate = _rate;
        _synthesizer.Volume = _volume;
        // SAPI5 nie obsługuje pitch bezpośrednio - wymaga SSML

        Console.WriteLine($"Załadowano ustawienia: Rate={savedRate}, Volume={savedVolume}, Pitch={_pitch} (uwaga: pitch nie jest wspierany przez SAPI5)");

        // Załaduj syntezator z ustawień
        string savedSynth = settings.Synthesizer;
        bool preferOneCore = savedSynth.Equals("OneCore", StringComparison.OrdinalIgnoreCase);
        bool preferBestSpeech = savedSynth.Equals("BestSpeech", StringComparison.OrdinalIgnoreCase);

        // Initialize OneCore if available
        if (OneCoreEngine.IsAvailable())
        {
            _oneCoreEngine = new OneCoreEngine();
            if (_oneCoreEngine.Initialize())
            {
                _currentSynthesizer = preferOneCore ? SynthesizerType.OneCore : SynthesizerType.SAPI5;
                Console.WriteLine($"Syntezator z ustawień: {(preferOneCore ? "OneCore" : "SAPI5")}");

                // Zastosuj rate/volume do OneCore
                _oneCoreEngine.SetRate(savedRate);
                _oneCoreEngine.SetVolume(savedVolume);
            }
            else
            {
                _currentSynthesizer = SynthesizerType.SAPI5;
                _oneCoreEngine?.Dispose();
                _oneCoreEngine = null;
            }
        }
        else
        {
            _currentSynthesizer = SynthesizerType.SAPI5;
            Console.WriteLine("Domyślny syntezator: SAPI5 (OneCore niedostępny)");
        }

        // Initialize BestSpeech if available
        if (BestSpeechEngine.IsAvailable())
        {
            _bestSpeechEngine = new BestSpeechEngine();
            if (_bestSpeechEngine.Initialize())
            {
                _bestSpeechEngine.SetRate(savedRate);
                Console.WriteLine("BestSpeech: Dostępny jako syntezator");
                if (preferBestSpeech)
                {
                    _currentSynthesizer = SynthesizerType.BestSpeech;
                    Console.WriteLine("Syntezator z ustawień: BestSpeech");
                }
            }
            else
            {
                Console.WriteLine("BestSpeech: Inicjalizacja nie powiodła się");
                _bestSpeechEngine?.Dispose();
                _bestSpeechEngine = null;
            }
        }
        else
        {
            Console.WriteLine("BestSpeech: Niedostępny (brak bst_bridge.exe lub DLL)");
        }

        // Załaduj głos z ustawień
        string savedVoice = settings.Voice;
        if (!string.IsNullOrEmpty(savedVoice))
        {
            try
            {
                if (_currentSynthesizer == SynthesizerType.BestSpeech && _bestSpeechEngine != null)
                {
                    _bestSpeechEngine.SetVoice(savedVoice);
                    Console.WriteLine($"Załadowano głos BestSpeech: {savedVoice}");
                }
                else if (_currentSynthesizer == SynthesizerType.OneCore && _oneCoreEngine != null)
                {
                    _oneCoreEngine.SetVoice(savedVoice);
                    Console.WriteLine($"Załadowano głos OneCore: {savedVoice}");
                }
                else
                {
                    _synthesizer.SelectVoice(savedVoice);
                    Console.WriteLine($"Załadowano głos SAPI5: {savedVoice}");
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Nie udało się załadować zapisanego głosu: {ex.Message}");
            }
        }
    }

    /// <summary>
    /// Rozgrzewa syntezator SAPI5 dla lepszej responsywności (eliminuje opóźnienie pierwszego wywołania)
    /// </summary>
    private void WarmUpSynthesizer()
    {
        if (_isWarmedUp)
            return;

        try
        {
            // Cichy prompt do rozgrzania syntezatora - eliminuje opóźnienie pierwszego wywołania
            var prompt = new PromptBuilder();
            prompt.AppendBreak(TimeSpan.FromMilliseconds(1));
            _synthesizer.SpeakAsync(prompt);
            _synthesizer.SpeakAsyncCancelAll();
            _isWarmedUp = true;
            Console.WriteLine("SAPI5: Syntezator rozgrzany");
        }
        catch (Exception ex)
        {
            Console.WriteLine($"SAPI5: Błąd rozgrzewania: {ex.Message}");
        }
    }

    /// <summary>
    /// Speaks text with optional stereo positioning (ONLY used during virtual screen exploration)
    /// For normal navigation (NumPad, keyboard), azimuth/elevation are null → normal mono output
    /// </summary>
    public void Speak(string text, bool interrupt = true, float? azimuth = null, float? elevation = null)
    {
        if (string.IsNullOrWhiteSpace(text))
            return;

        try
        {
            // Stereo speech for virtual screen exploration
            if (azimuth.HasValue)
            {
                SpeakStereo(text, azimuth.Value, interrupt);
            }
            else
            {
                // Standard mono speech for NumPad/keyboard navigation
                if (_currentSynthesizer == SynthesizerType.SAPI5)
                {
                    if (interrupt)
                    {
                        if (_isCapturingStereo)
                        {
                            // Don't interrupt stereo capture
                            return;
                        }
                        _synthesizer.SpeakAsyncCancelAll();
                    }
                    StopStereoPlayback();

                    var prompt = new PromptBuilder();
                    prompt.AppendText(text);
                    _synthesizer.SpeakAsync(prompt);
                }
                else if (_currentSynthesizer == SynthesizerType.OneCore)
                {
                    if (_oneCoreEngine != null)
                    {
                        StopStereoPlayback();
                        _oneCoreEngine.Speak(text);
                    }
                }
                else if (_currentSynthesizer == SynthesizerType.BestSpeech)
                {
                    if (_bestSpeechEngine != null)
                    {
                        StopStereoPlayback();
                        if (interrupt) _bestSpeechEngine.Stop();
                        _bestSpeechEngine.Speak(text);
                    }
                }
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Błąd mowy: {ex.Message}");
        }
    }

    // Stereo playback fields
    private WaveOutEvent? _stereoWaveOut;
    private readonly object _stereoLock = new object();
    private volatile bool _isCapturingStereo;

    /// <summary>
    /// Mowa stereo - proste panoramowanie lewo/prawo na podstawie azymutu.
    /// Azimuth: -π/2 = lewo, 0 = centrum, +π/2 = prawo.
    /// Używa NAudio WaveOutEvent - niezawodne, nie wymaga Windows Spatial Audio.
    /// </summary>
    private void SpeakStereo(string text, float azimuth, bool interrupt)
    {
        if (interrupt)
        {
            _synthesizer.SpeakAsyncCancelAll();
            StopStereoPlayback();
        }

        // Run on background thread to avoid blocking UI (TTS capture is synchronous)
        Task.Run(() =>
        {
            try
            {
                float[]? monoSamples = null;
                int sampleRate = 48000;

                if (_currentSynthesizer == SynthesizerType.SAPI5)
                {
                    using var memStream = new MemoryStream();
                    lock (_synthesizer)
                    {
                        try
                        {
                            _isCapturingStereo = true;
                            _synthesizer.SetOutputToWaveStream(memStream);
                            _synthesizer.Speak(text);
                        }
                        finally
                        {
                            _synthesizer.SetOutputToDefaultAudioDevice();
                            _isCapturingStereo = false;
                        }
                    }

                    memStream.Position = 0;
                    var result = WavDecoder.DecodeToPCM(memStream);
                    monoSamples = result.samples;
                    sampleRate = result.sampleRate;
                }
                else if (_oneCoreEngine != null)
                {
                    var stream = _oneCoreEngine.SynthesizeToStreamAsync(text).GetAwaiter().GetResult();
                    stream.Position = 0;
                    var result = WavDecoder.DecodeToPCM(stream);
                    monoSamples = result.samples;
                    sampleRate = result.sampleRate;
                }

                if (monoSamples == null || monoSamples.Length == 0)
                    return;

                // Stereo pan: azimuth → -1.0 (lewo) do +1.0 (prawo)
                float pan = Math.Clamp(azimuth / (MathF.PI / 2), -1f, 1f);
                float leftGain = Math.Min(1f, 1f - pan);
                float rightGain = Math.Min(1f, 1f + pan);

                // Mono → stereo z panoramowaniem
                float[] stereoSamples = new float[monoSamples.Length * 2];
                for (int i = 0; i < monoSamples.Length; i++)
                {
                    stereoSamples[i * 2] = monoSamples[i] * leftGain;       // Left
                    stereoSamples[i * 2 + 1] = monoSamples[i] * rightGain;  // Right
                }

                // Float → bytes
                byte[] bytes = new byte[stereoSamples.Length * sizeof(float)];
                Buffer.BlockCopy(stereoSamples, 0, bytes, 0, bytes.Length);

                var format = WaveFormat.CreateIeeeFloatWaveFormat(sampleRate, 2);
                var rawStream = new RawSourceWaveStream(new MemoryStream(bytes), format);

                var tcs = new TaskCompletionSource<bool>();
                WaveOutEvent waveOut;

                lock (_stereoLock)
                {
                    StopStereoPlaybackUnsafe();

                    waveOut = new WaveOutEvent();
                    _stereoWaveOut = waveOut;
                    waveOut.Init(rawStream);

                    waveOut.PlaybackStopped += (s, e) =>
                    {
                        tcs.TrySetResult(true);
                    };

                    waveOut.Play();
                }

                // Czekaj na zakończenie odtwarzania BEZ trzymania locka
                tcs.Task.Wait(TimeSpan.FromSeconds(30));

                lock (_stereoLock)
                {
                    waveOut.Dispose();
                    rawStream.Dispose();

                    if (_stereoWaveOut == waveOut)
                        _stereoWaveOut = null;
                }

                Console.WriteLine($"SpeakStereo: '{text}' pan={pan:F2} (L={leftGain:F2}, R={rightGain:F2})");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Błąd mowy stereo, fallback do mono: {ex.Message}");
                // Fallback to normal mono speech
                try
                {
                    if (_currentSynthesizer == SynthesizerType.SAPI5)
                    {
                        lock (_synthesizer)
                        {
                            _synthesizer.SetOutputToDefaultAudioDevice();
                            _isCapturingStereo = false;
                            var prompt = new PromptBuilder();
                            prompt.AppendText(text);
                            _synthesizer.SpeakAsync(prompt);
                        }
                    }
                    else if (_oneCoreEngine != null)
                    {
                        _oneCoreEngine.Speak(text);
                    }
                }
                catch (Exception fallbackEx)
                {
                    Console.WriteLine($"Błąd fallback mono: {fallbackEx.Message}");
                }
            }
        });
    }

    /// <summary>
    /// Zatrzymuje bieżące odtwarzanie stereo
    /// </summary>
    /// <summary>
    /// Zatrzymuje stereo - wersja wewnętrzna, MUSI być wywoływana wewnątrz lock(_stereoLock)
    /// </summary>
    private void StopStereoPlaybackUnsafe()
    {
        try
        {
            _stereoWaveOut?.Stop();
            _stereoWaveOut?.Dispose();
            _stereoWaveOut = null;
        }
        catch { }
    }

    private void StopStereoPlayback()
    {
        lock (_stereoLock)
        {
            StopStereoPlaybackUnsafe();
        }
    }

    public void Stop()
    {
        StopStereoPlayback();
        if (_currentSynthesizer == SynthesizerType.SAPI5)
        {
            _synthesizer.SpeakAsyncCancelAll();
        }
        else if (_currentSynthesizer == SynthesizerType.OneCore && _oneCoreEngine != null)
        {
            _oneCoreEngine.Stop();
        }
        else if (_currentSynthesizer == SynthesizerType.BestSpeech && _bestSpeechEngine != null)
        {
            _bestSpeechEngine.Stop();
        }
    }

    public void SetRate(int rate)
    {
        // Rate range: -10 (slow) to 10 (fast)
        _rate = Math.Clamp(rate, -10, 10);
        _synthesizer.Rate = _rate;
        _oneCoreEngine?.SetRate(_rate);
        _bestSpeechEngine?.SetRate(_rate);
    }

    public void SetVolume(int volume)
    {
        // Volume range: 0 to 100
        _volume = Math.Clamp(volume, 0, 100);
        _synthesizer.Volume = _volume;
        _oneCoreEngine?.SetVolume(_volume);
    }

    public List<string> GetAvailableVoices()
    {
        if (_currentSynthesizer == SynthesizerType.SAPI5)
        {
            // Użyj GetInstalledVoices() - zwraca prawidłowe nazwy dla SelectVoice()
            return _synthesizer.GetInstalledVoices()
                .Where(v => v.Enabled)
                .Select(v => v.VoiceInfo.Name)
                .ToList();
        }
        else if (_currentSynthesizer == SynthesizerType.BestSpeech && _bestSpeechEngine != null)
        {
            return _bestSpeechEngine.GetAvailableVoices()
                .Select(v => v.DisplayName)
                .ToList();
        }
        else
        {
            return OneCoreEngine.GetAllVoices()
                .Select(v => v.DisplayName)
                .ToList();
        }
    }

    public string GetCurrentVoice()
    {
        if (_currentSynthesizer == SynthesizerType.SAPI5)
        {
            return _synthesizer.Voice.Name;
        }
        else if (_currentSynthesizer == SynthesizerType.BestSpeech && _bestSpeechEngine != null)
        {
            return _bestSpeechEngine.GetCurrentVoice();
        }
        else if (_oneCoreEngine != null)
        {
            return _oneCoreEngine.GetCurrentVoice();
        }
        return "";
    }

    public void SelectVoice(string voiceName)
    {
        try
        {
            if (_currentSynthesizer == SynthesizerType.SAPI5)
            {
                _synthesizer.SelectVoice(voiceName);
                Console.WriteLine($"Zmieniono głos SAPI5 na: {voiceName}");
            }
            else if (_currentSynthesizer == SynthesizerType.BestSpeech && _bestSpeechEngine != null)
            {
                _bestSpeechEngine.SetVoice(voiceName);
            }
            else if (_oneCoreEngine != null)
            {
                _oneCoreEngine.SetVoice(voiceName);
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Błąd zmiany głosu: {ex.Message}");
        }
    }

    public int GetRate()
    {
        return _rate;
    }

    public int GetVolume()
    {
        return _volume;
    }

    // SAPI voice detection including 32-bit voices
    private List<string> GetAllSAPIVoices()
    {
        var voices = new HashSet<string>();

        // 64-bitowe głosy SAPI
        try
        {
            using (var key = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Speech\Voices\Tokens"))
            {
                if (key != null)
                {
                    foreach (var tokenName in key.GetSubKeyNames())
                    {
                        using (var voiceKey = key.OpenSubKey(tokenName))
                        {
                            if (voiceKey != null)
                            {
                                // Odczytaj nazwę głosu z wartości domyślnej
                                var voiceName = voiceKey.GetValue("") as string;
                                if (!string.IsNullOrEmpty(voiceName))
                                {
                                    voices.Add(voiceName);
                                }
                            }
                        }
                    }
                }
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Błąd odczytu głosów 64-bit: {ex.Message}");
        }

        // 32-bitowe głosy SAPI (Wow6432Node)
        try
        {
            using (var key = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Wow6432Node\Microsoft\Speech\Voices\Tokens"))
            {
                if (key != null)
                {
                    foreach (var tokenName in key.GetSubKeyNames())
                    {
                        using (var voiceKey = key.OpenSubKey(tokenName))
                        {
                            if (voiceKey != null)
                            {
                                // Odczytaj nazwę głosu z wartości domyślnej
                                var voiceName = voiceKey.GetValue("") as string;
                                if (!string.IsNullOrEmpty(voiceName))
                                {
                                    voices.Add(voiceName);
                                }
                            }
                        }
                    }
                }
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Błąd odczytu głosów 32-bit: {ex.Message}");
        }

        return voices.OrderBy(v => v).ToList();
    }

    // Synthesizer management
    public SynthesizerType GetCurrentSynthesizer()
    {
        return _currentSynthesizer;
    }

    public void SetSynthesizer(SynthesizerType type)
    {
        if (_currentSynthesizer == type)
            return;

        _currentSynthesizer = type;

        if (type == SynthesizerType.OneCore)
        {
            // Initialize OneCore if not already done
            if (_oneCoreEngine == null)
            {
                _oneCoreEngine = new OneCoreEngine();
                if (!_oneCoreEngine.Initialize())
                {
                    Console.WriteLine("Nie udało się zainicjalizować OneCore, powrót do SAPI5");
                    _currentSynthesizer = SynthesizerType.SAPI5;
                    _oneCoreEngine?.Dispose();
                    _oneCoreEngine = null;
                }
            }

            // Zastosuj bieżące rate/volume do OneCore
            if (_oneCoreEngine != null)
            {
                _oneCoreEngine.SetRate(_rate);
                _oneCoreEngine.SetVolume(_volume);
            }
        }
        else if (type == SynthesizerType.BestSpeech)
        {
            // Initialize BestSpeech if not already done
            if (_bestSpeechEngine == null)
            {
                _bestSpeechEngine = new BestSpeechEngine();
                if (!_bestSpeechEngine.Initialize())
                {
                    Console.WriteLine("Nie udało się zainicjalizować BestSpeech, powrót do SAPI5");
                    _currentSynthesizer = SynthesizerType.SAPI5;
                    _bestSpeechEngine?.Dispose();
                    _bestSpeechEngine = null;
                }
            }

            // Zastosuj bieżące rate do BestSpeech
            _bestSpeechEngine?.SetRate(_rate);
        }
    }

    // OneCore-specific methods
    public void SetOneCoreVoice(string voiceId)
    {
        if (_currentSynthesizer == SynthesizerType.OneCore && _oneCoreEngine != null)
        {
            _oneCoreEngine.SetVoice(voiceId);
        }
    }

    public List<OneCoreEngine.VoiceInfo> GetOneCoreVoicesInfo()
    {
        return OneCoreEngine.GetAllVoices();
    }

    // BestSpeech-specific methods
    public List<BestSpeechEngine.VoiceInfo> GetBestSpeechVoicesInfo()
    {
        return _bestSpeechEngine?.GetAvailableVoices() ?? new List<BestSpeechEngine.VoiceInfo>();
    }

    public bool IsBestSpeechAvailable()
    {
        return _bestSpeechEngine != null && _bestSpeechEngine.IsInitialized;
    }

    public void Dispose()
    {
        if (_disposed)
            return;

        StopStereoPlayback();
        _silencePlayer.Dispose();
        _synthesizer.SpeakAsyncCancelAll();
        _synthesizer.Dispose();

        _oneCoreEngine?.Dispose();
        _oneCoreEngine = null;

        _bestSpeechEngine?.Dispose();
        _bestSpeechEngine = null;

        _spatialRenderer?.Dispose();
        _spatialRenderer = null;

        _disposed = true;
    }
}
