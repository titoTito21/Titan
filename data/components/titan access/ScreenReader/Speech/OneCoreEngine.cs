using Windows.Media.SpeechSynthesis;
using Windows.Media.Playback;
using Windows.Media.Core;
using System.Runtime.InteropServices;

namespace ScreenReader.Speech;

/// <summary>
/// Silnik syntezy mowy OneCore (Microsoft Mobile Voices)
/// Używa Windows.Media.SpeechSynthesis dla dostępu do głosów OneCore
/// </summary>
public class OneCoreEngine : IDisposable
{
    private SpeechSynthesizer? _synthesizer;
    private MediaPlayer? _mediaPlayer;
    private bool _disposed;
    private bool _initialized;
    private string _currentVoiceId = "";

    public bool IsInitialized => _initialized;

    public bool Initialize()
    {
        if (_initialized)
            return true;

        try
        {
            _synthesizer = new SpeechSynthesizer();
            _mediaPlayer = new MediaPlayer();

            // Znajdź polski głos OneCore
            var polishVoice = SpeechSynthesizer.AllVoices
                .FirstOrDefault(v => v.Language.StartsWith("pl"));

            if (polishVoice != null)
            {
                _synthesizer.Voice = polishVoice;
                _currentVoiceId = polishVoice.Id;
                Console.WriteLine($"OneCore: Używam głosu {polishVoice.DisplayName}");
            }
            else
            {
                Console.WriteLine("OneCore: Brak polskiego głosu, używam domyślnego");
                if (_synthesizer.Voice != null)
                {
                    _currentVoiceId = _synthesizer.Voice.Id;
                }
            }

            _initialized = true;
            return true;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"OneCore: Błąd inicjalizacji: {ex.Message}");
            return false;
        }
    }

    public async void Speak(string text)
    {
        if (!_initialized || _synthesizer == null || _mediaPlayer == null)
            return;

        if (string.IsNullOrWhiteSpace(text))
            return;

        try
        {
            // Zawsze przerywaj poprzednią mowę
            Stop();

            // Syntezuj tekst
            var stream = await _synthesizer.SynthesizeTextToStreamAsync(text);

            // Odtwórz
            _mediaPlayer.Source = MediaSource.CreateFromStream(stream, stream.ContentType);
            _mediaPlayer.Play();
        }
        catch (Exception ex)
        {
            Console.WriteLine($"OneCore: Błąd syntezy: {ex.Message}");
        }
    }

    /// <summary>
    /// Synthesizes text to stream (for spatial audio)
    /// </summary>
    public async Task<Stream> SynthesizeToStreamAsync(string text)
    {
        if (!_initialized || _synthesizer == null)
            throw new InvalidOperationException("Engine not initialized");

        if (string.IsNullOrWhiteSpace(text))
            throw new ArgumentException("Text cannot be empty");

        // Synthesize and return stream
        var stream = await _synthesizer.SynthesizeTextToStreamAsync(text);
        return stream.AsStream();
    }

    public void Stop()
    {
        if (_mediaPlayer != null)
        {
            try
            {
                _mediaPlayer.Pause();
                _mediaPlayer.Source = null;
            }
            catch { }
        }
    }

    public void SetVoice(string voiceId)
    {
        if (!_initialized || _synthesizer == null)
            return;

        try
        {
            var voice = SpeechSynthesizer.AllVoices
                .FirstOrDefault(v => v.Id == voiceId || v.DisplayName == voiceId);

            if (voice != null)
            {
                _synthesizer.Voice = voice;
                _currentVoiceId = voice.Id;
                Console.WriteLine($"OneCore: Zmieniono głos na {voice.DisplayName}");
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"OneCore: Błąd zmiany głosu: {ex.Message}");
        }
    }

    public void SetRate(int rate)
    {
        if (!_initialized || _synthesizer == null)
            return;

        // rate: -10 do 10, mapuj na 0.5 do 3.0
        double speakingRate = 1.0 + (rate * 0.1);
        speakingRate = Math.Clamp(speakingRate, 0.5, 3.0);

        _synthesizer.Options.SpeakingRate = speakingRate;
    }

    public void SetVolume(int volume)
    {
        if (_mediaPlayer == null)
            return;

        // volume: 0-100, mapuj na 0.0-1.0
        _mediaPlayer.Volume = Math.Clamp(volume / 100.0, 0.0, 1.0);
    }

    public void SetPitch(int pitch)
    {
        if (!_initialized || _synthesizer == null)
            return;

        // pitch: -10 do 10, mapuj na 0.5 do 2.0
        double audioPitch = 1.0 + (pitch * 0.05);
        audioPitch = Math.Clamp(audioPitch, 0.5, 2.0);

        _synthesizer.Options.AudioPitch = audioPitch;
    }

    public string GetCurrentVoice()
    {
        if (_synthesizer?.Voice != null)
        {
            return _synthesizer.Voice.DisplayName;
        }
        return "";
    }

    public string GetCurrentVoiceId()
    {
        return _currentVoiceId;
    }

    /// <summary>
    /// Pobiera listę dostępnych głosów OneCore
    /// </summary>
    public static List<VoiceInfo> GetAllVoices()
    {
        var voices = new List<VoiceInfo>();

        try
        {
            foreach (var voice in SpeechSynthesizer.AllVoices)
            {
                voices.Add(new VoiceInfo
                {
                    Id = voice.Id,
                    DisplayName = voice.DisplayName,
                    Language = voice.Language,
                    Gender = voice.Gender == VoiceGender.Female ? "F" :
                             voice.Gender == VoiceGender.Male ? "M" : ""
                });
            }

            // Sortuj: polskie na górze, potem alfabetycznie
            return voices
                .OrderByDescending(v => v.Language.StartsWith("pl"))
                .ThenBy(v => v.DisplayName)
                .ToList();
        }
        catch (Exception ex)
        {
            Console.WriteLine($"OneCore: Błąd pobierania głosów: {ex.Message}");
            return voices;
        }
    }

    /// <summary>
    /// Sprawdza czy OneCore jest dostępny
    /// </summary>
    public static bool IsAvailable()
    {
        try
        {
            return SpeechSynthesizer.AllVoices.Count > 0;
        }
        catch
        {
            return false;
        }
    }

    public void Dispose()
    {
        if (_disposed)
            return;

        Stop();

        _mediaPlayer?.Dispose();
        _mediaPlayer = null;

        _synthesizer?.Dispose();
        _synthesizer = null;

        _disposed = true;
        _initialized = false;
    }

    /// <summary>
    /// Informacje o głosie OneCore
    /// </summary>
    public class VoiceInfo
    {
        public string Id { get; set; } = "";
        public string DisplayName { get; set; } = "";
        public string Language { get; set; } = "";
        public string Gender { get; set; } = "";

        public override string ToString()
        {
            string genderStr = string.IsNullOrEmpty(Gender) ? "" : $" [{Gender}]";
            return $"{DisplayName} ({Language}){genderStr}";
        }
    }
}
