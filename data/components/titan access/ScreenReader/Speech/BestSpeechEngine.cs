using System.Diagnostics;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using NAudio.Wave;

namespace ScreenReader.Speech;

/// <summary>
/// Silnik BeSTspeech - wielojęzyczny syntezator mowy (12 języków).
/// Komunikuje się z 32-bitowym procesem bst_bridge.exe przez JSON/stdin/stdout.
/// Bridge hookuje waveOut IAT w DLLkach BeSTspeech i przechwytuje audio do pliku WAV.
///
/// Architektura: ScreenReader (64-bit) -> bst_bridge.exe (32-bit) -> dll_pol.dll (32-bit BeSTspeech)
///
/// Polecenia bridge:
///   init/switch: ładuje DLL języka
///   say: syntezuje tekst, zwraca ścieżkę do WAV
///   quit: zamyka bridge
/// </summary>
public class BestSpeechEngine : IDisposable
{
    private Process? _bridgeProcess;
    private readonly object _lock = new();
    private bool _disposed;
    private bool _initialized;
    private string _currentVoiceId = "pl";
    private string? _currentDllPath;
    private readonly string _engineDir;
    private readonly string _bridgeExePath;
    private WaveOutEvent? _waveOut;
    private readonly object _playbackLock = new();
    private int _rate; // -10 (najwolniej) do +10 (najszybciej), 0 = domyślnie

    // Opcje JSON - nie escapuj polskich znaków (ą,ę,ć,ś,ź,ż,ó,ł,ń) jako \uXXXX
    private static readonly JsonSerializerOptions _jsonOptions = new()
    {
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping
    };

    // Mapa języków -> pliki DLL
    private static readonly Dictionary<string, (string DllName, string DisplayName)> LanguageMap = new()
    {
        ["en"] = ("dll_eng.dll", "BeSTspeech English"),
        ["es"] = ("dll_spa.dll", "BeSTspeech Spanish"),
        ["fr"] = ("dll_fre.dll", "BeSTspeech French"),
        ["de"] = ("dll_ger.dll", "BeSTspeech German"),
        ["it"] = ("dll_ita.dll", "BeSTspeech Italian"),
        ["nl"] = ("dll_dut.dll", "BeSTspeech Dutch"),
        ["el"] = ("dll_gre.dll", "BeSTspeech Greek"),
        ["he"] = ("dll_heb.dll", "BeSTspeech Hebrew"),
        ["ja"] = ("dll_jpn.dll", "BeSTspeech Japanese"),
        ["pl"] = ("dll_pol.dll", "BeSTspeech Polish"),
        ["pt"] = ("dll_por.dll", "BeSTspeech Portuguese"),
        ["ru"] = ("dll_rus.dll", "BeSTspeech Russian"),
    };

    // Dostępne głosy (wykryte DLLki)
    private readonly List<VoiceInfo> _availableVoices = new();

    public bool IsInitialized => _initialized;

    public BestSpeechEngine()
    {
        _engineDir = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Speech", "bestspeech");

        // Fallback: szukaj w katalogu aplikacji
        if (!Directory.Exists(_engineDir))
        {
            _engineDir = Path.Combine(AppContext.BaseDirectory, "Speech", "bestspeech");
        }

        _bridgeExePath = Path.Combine(_engineDir, "bst_bridge.exe");
        DiscoverVoices();
    }

    /// <summary>
    /// Wykrywa dostępne głosy na podstawie obecnych plików DLL
    /// </summary>
    private void DiscoverVoices()
    {
        _availableVoices.Clear();

        foreach (var (langCode, (dllName, displayName)) in LanguageMap)
        {
            var dllPath = Path.Combine(_engineDir, dllName);
            if (File.Exists(dllPath))
            {
                _availableVoices.Add(new VoiceInfo
                {
                    Id = langCode,
                    DisplayName = displayName,
                    DllPath = dllPath
                });
            }
        }

        Console.WriteLine($"BestSpeech: Znaleziono {_availableVoices.Count} języków");
    }

    /// <summary>
    /// Sprawdza czy BestSpeech jest dostępny (bridge exe + przynajmniej 1 DLL)
    /// </summary>
    public static bool IsAvailable()
    {
        var engineDir = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Speech", "bestspeech");
        var bridgePath = Path.Combine(engineDir, "bst_bridge.exe");

        if (!File.Exists(bridgePath))
            return false;

        // Sprawdź czy jest przynajmniej 1 DLL
        return LanguageMap.Values.Any(v => File.Exists(Path.Combine(engineDir, v.DllName)));
    }

    /// <summary>
    /// Inicjalizuje silnik - uruchamia bridge i ładuje domyślny DLL
    /// </summary>
    public bool Initialize()
    {
        if (_initialized)
            return true;

        if (!File.Exists(_bridgeExePath))
        {
            Console.WriteLine($"BestSpeech: Brak bst_bridge.exe w {_engineDir}");
            return false;
        }

        if (!StartBridge())
            return false;

        // Załaduj domyślny DLL (polski lub pierwszy dostępny)
        var defaultVoice = _availableVoices.FirstOrDefault(v => v.Id == "pl")
                        ?? _availableVoices.FirstOrDefault();

        if (defaultVoice == null)
        {
            Console.WriteLine("BestSpeech: Brak dostępnych głosów");
            KillBridge();
            return false;
        }

        if (!SendInit(defaultVoice.DllPath))
        {
            Console.WriteLine($"BestSpeech: Nie udało się załadować DLL: {defaultVoice.DllPath}");
            KillBridge();
            return false;
        }

        _currentVoiceId = defaultVoice.Id;
        _currentDllPath = defaultVoice.DllPath;
        _initialized = true;

        Console.WriteLine($"BestSpeech: Zainicjalizowany z głosem {defaultVoice.DisplayName}");
        return true;
    }

    /// <summary>
    /// Syntezuje i odtwarza tekst
    /// </summary>
    public void Speak(string text)
    {
        if (!_initialized || string.IsNullOrWhiteSpace(text))
            return;

        try
        {
            Stop();

            // Syntezuj do WAV
            string? wavPath = SynthesizeToWav(text);
            if (wavPath == null)
            {
                Console.WriteLine("BestSpeech: Synteza nie powiodła się");
                return;
            }

            // Odtwórz WAV
            PlayWavFile(wavPath, deleteAfter: true);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"BestSpeech: Błąd Speak: {ex.Message}");
        }
    }

    /// <summary>
    /// Syntezuje tekst i zwraca ścieżkę do pliku WAV
    /// </summary>
    public string? SynthesizeToWav(string text)
    {
        lock (_lock)
        {
            if (!EnsureBridge())
                return null;

            try
            {
                var cmd = JsonSerializer.Serialize(new { cmd = "say", text }, _jsonOptions);
                var response = SendCommand(cmd);

                if (response == null)
                    return null;

                using var doc = JsonDocument.Parse(response);
                var root = doc.RootElement;

                if (root.TryGetProperty("ok", out var ok) && ok.GetBoolean() &&
                    root.TryGetProperty("wav", out var wav))
                {
                    var wavPath = wav.GetString();
                    if (!string.IsNullOrEmpty(wavPath) && File.Exists(wavPath))
                        return wavPath;
                }

                if (root.TryGetProperty("error", out var error))
                    Console.WriteLine($"BestSpeech: Bridge error: {error.GetString()}");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"BestSpeech: Błąd syntezy: {ex.Message}");
            }

            return null;
        }
    }

    /// <summary>
    /// Syntezuje tekst do strumienia (dla spatial audio)
    /// </summary>
    public Stream? SynthesizeToStream(string text)
    {
        var wavPath = SynthesizeToWav(text);
        if (wavPath == null)
            return null;

        try
        {
            // Wczytaj WAV do pamięci i usuń plik tymczasowy
            var bytes = File.ReadAllBytes(wavPath);
            try { File.Delete(wavPath); } catch { }
            return new MemoryStream(bytes);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"BestSpeech: Błąd odczytu WAV: {ex.Message}");
            return null;
        }
    }

    /// <summary>
    /// Odtwarza plik WAV przez NAudio
    /// </summary>
    /// <summary>
    /// Oblicza współczynnik prędkości z wartości rate (-10..+10).
    /// Identyczne mapowanie jak port pythonowy (__engine__.py _apply_rate):
    ///   rate > 0: factor = 1.0 + (rate * 0.15) → max 2.5x
    ///   rate &lt; 0: factor = 1.0 + (rate * 0.05) → min 0.5x
    /// </summary>
    private float GetRateFactor()
    {
        if (_rate == 0) return 1.0f;
        float factor = _rate > 0
            ? 1.0f + (_rate * 0.15f)
            : 1.0f + (_rate * 0.05f);
        return Math.Clamp(factor, 0.5f, 2.5f);
    }

    /// <summary>
    /// Zmienia tempo audio bez zmiany pitch (time-stretch).
    /// Algorytm WSOLA (Waveform Similarity Overlap-Add) - ten sam algorytm
    /// którego używa ffmpeg atempo (libavfilter/af_atempo.c).
    ///
    /// Kluczowa różnica vs prosty OLA: przed każdym overlap szukamy
    /// optymalnego przesunięcia przez cross-correlation, dzięki czemu
    /// przejścia między segmentami są gładkie (brak chrypki/artefaktów).
    ///
    /// Parametry dobrane pod mowę:
    ///   - okno 50ms (typowy zakres pitch mowy 80-300Hz)
    ///   - overlap 50% (synthesis hop = window/2)
    ///   - zakres szukania ±8ms (±176 próbek przy 22050Hz)
    ///
    /// factor > 1.0 = szybciej, factor &lt; 1.0 = wolniej.
    /// Obsługuje 16-bit PCM, mono i stereo.
    /// </summary>
    private static byte[] ApplyTempoWSOLA(byte[] pcmData, int dataLen, int channels, int sampleRate, float factor)
    {
        int frameSize = 2 * channels; // 16-bit PCM
        int totalFrames = dataLen / frameSize;

        // Konwersja 16-bit PCM → float (tylko kanał 0 do korelacji, wszystkie do output)
        float[] mono = new float[totalFrames]; // kanał 0 lub średnia - do korelacji
        float[][] allCh = new float[channels][];
        for (int ch = 0; ch < channels; ch++)
            allCh[ch] = new float[totalFrames];

        for (int f = 0; f < totalFrames; f++)
        {
            float sum = 0;
            int baseOff = f * frameSize;
            for (int ch = 0; ch < channels; ch++)
            {
                float val = BitConverter.ToInt16(pcmData, baseOff + ch * 2) / 32768f;
                allCh[ch][f] = val;
                sum += val;
            }
            mono[f] = sum / channels;
        }

        // Parametry WSOLA
        int windowFrames = Math.Max(128, (int)(sampleRate * 0.050)); // 50ms
        int overlapFrames = windowFrames / 2;                        // 50% overlap
        int searchRange = Math.Max(32, (int)(sampleRate * 0.008));   // ±8ms

        // Analysis hop = ile przeskakujemy w źródle (zależy od factor)
        // Synthesis hop = overlapFrames (stały - ile przeskakujemy w wyjściu)
        int synthesisHop = overlapFrames;
        int analysisHop = (int)(synthesisHop * factor);
        if (analysisHop < 1) analysisHop = 1;

        // Crossfade: liniowy fade-in / fade-out w strefie overlap
        float[] fadeIn = new float[overlapFrames];
        float[] fadeOut = new float[overlapFrames];
        for (int i = 0; i < overlapFrames; i++)
        {
            fadeIn[i] = (float)i / overlapFrames;
            fadeOut[i] = 1.0f - fadeIn[i];
        }

        // Bufor wyjściowy
        int outCapacity = (int)(totalFrames / factor) + windowFrames * 4;
        float[][] outCh = new float[channels][];
        for (int ch = 0; ch < channels; ch++)
            outCh[ch] = new float[outCapacity];

        // Pierwszy segment: kopiuj wprost
        int inPos = 0;
        int outPos = 0;
        int segLen = Math.Min(windowFrames, totalFrames);
        for (int i = 0; i < segLen; i++)
            for (int ch = 0; ch < channels; ch++)
                outCh[ch][i] = allCh[ch][i];

        outPos = segLen - overlapFrames; // następny zapis zaczyna się w strefie overlap
        inPos = analysisHop;

        while (inPos + windowFrames <= totalFrames && outPos + windowFrames < outCapacity)
        {
            // --- WSOLA: szukaj najlepszego przesunięcia przez cross-correlation ---
            // Porównujemy strefę overlap w wyjściu (outPos..outPos+overlapFrames)
            // z kandydatem w źródle (inPos+delta...) dla delta ∈ [-searchRange, +searchRange]
            int bestDelta = 0;
            float bestCorr = float.MinValue;

            int searchLo = Math.Max(-searchRange, -inPos);
            int searchHi = Math.Min(searchRange, totalFrames - inPos - windowFrames);

            for (int delta = searchLo; delta <= searchHi; delta++)
            {
                float corr = 0f;
                float normA = 0f;
                float normB = 0f;
                int srcStart = inPos + delta;

                // Korelacja w strefie overlap (mono)
                for (int i = 0; i < overlapFrames; i++)
                {
                    float a = outCh[0][outPos + i]; // to co już jest w wyjściu (ch0)
                    float b = mono[srcStart + i];    // kandydat ze źródła
                    corr += a * b;
                    normA += a * a;
                    normB += b * b;
                }

                // Znormalizowana korelacja (zapobiega preferowaniu głośnych fragmentów)
                float denom = MathF.Sqrt(normA * normB);
                if (denom > 1e-8f)
                    corr /= denom;

                if (corr > bestCorr)
                {
                    bestCorr = corr;
                    bestDelta = delta;
                }
            }

            int bestSrc = inPos + bestDelta;

            // --- Crossfade w strefie overlap ---
            for (int i = 0; i < overlapFrames; i++)
            {
                for (int ch = 0; ch < channels; ch++)
                    outCh[ch][outPos + i] = outCh[ch][outPos + i] * fadeOut[i]
                                           + allCh[ch][bestSrc + i] * fadeIn[i];
            }

            // --- Kopiuj resztę segmentu (po strefie overlap) ---
            int copyLen = Math.Min(windowFrames - overlapFrames, outCapacity - outPos - overlapFrames);
            copyLen = Math.Min(copyLen, totalFrames - bestSrc - overlapFrames);
            for (int i = 0; i < copyLen; i++)
            {
                for (int ch = 0; ch < channels; ch++)
                    outCh[ch][outPos + overlapFrames + i] = allCh[ch][bestSrc + overlapFrames + i];
            }

            outPos += synthesisHop;
            inPos += analysisHop;
        }

        // Końcowa długość
        int outEnd = Math.Min(outPos + overlapFrames, outCapacity);

        // Konwersja float → 16-bit PCM
        byte[] result = new byte[outEnd * frameSize];
        for (int f = 0; f < outEnd; f++)
        {
            for (int ch = 0; ch < channels; ch++)
            {
                float val = Math.Clamp(outCh[ch][f], -1f, 1f);
                short s = (short)(val * 32767f);
                int off = f * frameSize + ch * 2;
                result[off] = (byte)(s & 0xFF);
                result[off + 1] = (byte)((s >> 8) & 0xFF);
            }
        }

        return result;
    }

    private void PlayWavFile(string wavPath, bool deleteAfter)
    {
        lock (_playbackLock)
        {
            StopPlayback();

            try
            {
                var reader = new WaveFileReader(wavPath);
                IWaveProvider provider = reader;
                MemoryStream? stretchedStream = null;

                // Time-stretch bez zmiany pitch (jak ffmpeg atempo w porcie pythonowym)
                float factor = GetRateFactor();
                if (Math.Abs(factor - 1.0f) > 0.01f && reader.WaveFormat.BitsPerSample == 16)
                {
                    var format = reader.WaveFormat;
                    var rawBytes = new byte[reader.Length];
                    int bytesRead = reader.Read(rawBytes, 0, rawBytes.Length);
                    reader.Dispose();

                    var stretched = ApplyTempoWSOLA(rawBytes, bytesRead, format.Channels, format.SampleRate, factor);
                    stretchedStream = new MemoryStream(stretched);
                    provider = new RawSourceWaveStream(stretchedStream, format);
                }

                var waveOut = new WaveOutEvent();
                _waveOut = waveOut;

                waveOut.Init(provider);

                waveOut.PlaybackStopped += (s, e) =>
                {
                    try
                    {
                        waveOut.Dispose();
                        if (stretchedStream != null)
                            stretchedStream.Dispose();
                        else
                            reader.Dispose();
                        if (deleteAfter)
                        {
                            try { File.Delete(wavPath); } catch { }
                        }
                    }
                    catch { }
                };

                waveOut.Play();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"BestSpeech: Błąd odtwarzania: {ex.Message}");
                if (deleteAfter)
                {
                    try { File.Delete(wavPath); } catch { }
                }
            }
        }
    }

    /// <summary>
    /// Zatrzymuje odtwarzanie
    /// </summary>
    public void Stop()
    {
        StopPlayback();
    }

    private void StopPlayback()
    {
        lock (_playbackLock)
        {
            try
            {
                if (_waveOut != null)
                {
                    _waveOut.Stop();
                    _waveOut.Dispose();
                    _waveOut = null;
                }
            }
            catch { }
        }
    }

    /// <summary>
    /// Zmienia głos (język)
    /// </summary>
    public void SetVoice(string voiceId)
    {
        if (voiceId == _currentVoiceId)
            return;

        var voice = _availableVoices.FirstOrDefault(v => v.Id == voiceId || v.DisplayName == voiceId);
        if (voice == null)
            return;

        lock (_lock)
        {
            if (!EnsureBridge())
                return;

            var cmd = JsonSerializer.Serialize(new { cmd = "switch", dll = voice.DllPath }, _jsonOptions);
            var response = SendCommand(cmd);

            if (response != null)
            {
                try
                {
                    using var doc = JsonDocument.Parse(response);
                    if (doc.RootElement.TryGetProperty("ok", out var ok) && ok.GetBoolean())
                    {
                        _currentVoiceId = voice.Id;
                        _currentDllPath = voice.DllPath;
                        Console.WriteLine($"BestSpeech: Zmieniono głos na {voice.DisplayName}");
                    }
                }
                catch { }
            }
        }
    }

    public string GetCurrentVoice()
    {
        var voice = _availableVoices.FirstOrDefault(v => v.Id == _currentVoiceId);
        return voice?.DisplayName ?? "";
    }

    public List<VoiceInfo> GetAvailableVoices() => new(_availableVoices);

    /// <summary>
    /// Ustawia tempo mowy. -10 (najwolniej) do +10 (najszybciej), 0 = domyślnie.
    /// Mapowanie na współczynnik prędkości:
    ///   -10 -> 0.5x, 0 -> 1.0x, +10 -> 2.5x
    /// </summary>
    public void SetRate(int rate)
    {
        _rate = Math.Clamp(rate, -10, 10);
    }

    public int GetRate() => _rate;

    // ======================== Bridge Process Management ========================

    private bool StartBridge()
    {
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = _bridgeExePath,
                WorkingDirectory = _engineDir,
                UseShellExecute = false,
                RedirectStandardInput = true,
                RedirectStandardOutput = true,
                RedirectStandardError = false,
                CreateNoWindow = true,
                StandardInputEncoding = Encoding.UTF8,
                StandardOutputEncoding = Encoding.UTF8,
            };

            _bridgeProcess = Process.Start(psi);
            if (_bridgeProcess == null)
                return false;

            // Czekaj na {"ready":true}
            var response = ReadResponse(timeout: 10000);
            if (response != null && response.Contains("\"ready\""))
            {
                Console.WriteLine("BestSpeech: Bridge uruchomiony");
                return true;
            }

            KillBridge();
            return false;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"BestSpeech: Błąd uruchamiania bridge: {ex.Message}");
            return false;
        }
    }

    private bool EnsureBridge()
    {
        if (_bridgeProcess != null && !_bridgeProcess.HasExited)
            return true;

        // Restart bridge
        if (!StartBridge())
            return false;

        // Przeładuj DLL
        if (_currentDllPath != null)
            return SendInit(_currentDllPath);

        var defaultVoice = _availableVoices.FirstOrDefault(v => v.Id == _currentVoiceId)
                        ?? _availableVoices.FirstOrDefault();

        if (defaultVoice != null)
        {
            _currentDllPath = defaultVoice.DllPath;
            return SendInit(defaultVoice.DllPath);
        }

        return false;
    }

    private bool SendInit(string dllPath)
    {
        var cmd = JsonSerializer.Serialize(new { cmd = "init", dll = dllPath }, _jsonOptions);
        var response = SendCommand(cmd);

        if (response != null)
        {
            try
            {
                using var doc = JsonDocument.Parse(response);
                return doc.RootElement.TryGetProperty("ok", out var ok) && ok.GetBoolean();
            }
            catch { }
        }

        return false;
    }

    private string? SendCommand(string json)
    {
        if (_bridgeProcess == null || _bridgeProcess.HasExited)
            return null;

        try
        {
            _bridgeProcess.StandardInput.WriteLine(json);
            _bridgeProcess.StandardInput.Flush();
            return ReadResponse(timeout: 30000);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"BestSpeech: Błąd komunikacji z bridge: {ex.Message}");
            return null;
        }
    }

    private string? ReadResponse(int timeout)
    {
        if (_bridgeProcess == null || _bridgeProcess.HasExited)
            return null;

        string? result = null;
        var thread = new Thread(() =>
        {
            try
            {
                result = _bridgeProcess.StandardOutput.ReadLine();
            }
            catch { }
        });

        thread.IsBackground = true;
        thread.Start();

        if (!thread.Join(timeout))
        {
            Console.WriteLine("BestSpeech: Timeout odpowiedzi z bridge");
            return null;
        }

        return result;
    }

    private void KillBridge()
    {
        if (_bridgeProcess != null)
        {
            try
            {
                if (!_bridgeProcess.HasExited)
                    _bridgeProcess.Kill();
            }
            catch { }

            try
            {
                _bridgeProcess.WaitForExit(2000);
            }
            catch { }

            _bridgeProcess.Dispose();
            _bridgeProcess = null;
        }
    }

    public void Dispose()
    {
        if (_disposed)
            return;

        _disposed = true;
        StopPlayback();

        // Graceful shutdown
        lock (_lock)
        {
            if (_bridgeProcess != null && !_bridgeProcess.HasExited)
            {
                try
                {
                    _bridgeProcess.StandardInput.WriteLine("{\"cmd\":\"quit\"}");
                    _bridgeProcess.StandardInput.Flush();
                    _bridgeProcess.WaitForExit(3000);
                }
                catch { }
            }

            KillBridge();
        }

        _initialized = false;
    }

    /// <summary>
    /// Informacje o głosie BestSpeech
    /// </summary>
    public class VoiceInfo
    {
        public string Id { get; set; } = "";
        public string DisplayName { get; set; } = "";
        public string DllPath { get; set; } = "";

        public override string ToString() => DisplayName;
    }
}
