// Titan TTS - native SAPI5 voice (InprocServer32 DLL)
//
// Implements ISpTTSEngine + ISpObjectWithToken. When SAPI calls Speak(), the
// DLL connects to the Python-side named pipe \\.\pipe\TitanTTS, sends the
// text plus site rate/volume, receives 22050Hz / 16-bit / mono PCM back, and
// writes it to pOutputSite->Write() in chunks while honoring SPVES_ABORT.
//
// Fallback chain (when pipe is not available / TCE Launcher not running):
//   1. Named pipe (all TCE engines: BestSpeech, Milena, ElevenLabs, etc.)
//   2. Built-in eSpeak NG (bundled libespeak-ng.dll in data/titantts engines/espeak/)
//   3. Other installed SAPI5 voices (COM ISpVoice, skips TitanTTS to prevent
//      recursion — enables e.g. 32-bit voices to work on 64-bit systems)
//
// Voice is read from the TCE settings file (bg5settings.ini) so fallback
// voices match the user's configuration.  Rate, pitch, and volume are
// NOT read from TCE settings — they come from the SAPI client (screen
// reader / application) and are applied natively by each engine so that
// rate changes only speed and pitch changes only tone (never tempo).
//
// Built in both x86 and x64 flavors as titantts32.dll / titantts64.dll.
// The CLSID is stable across architectures - Windows registry redirection
// routes 32-bit SAPI clients to WOW6432Node\CLSID (which points at
// titantts32.dll) and 64-bit clients to the plain CLSID hive (titantts64.dll).

#define WIN32_LEAN_AND_MEAN
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <objbase.h>
#include <olectl.h>
#include <sapi.h>
#include <sapiddk.h>
#include <sperror.h>
#include <string>
#include <vector>
#include <cstdio>
#include <cmath>

#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "advapi32.lib")
#pragma comment(lib, "sapi.lib")

// ---------------------------------------------------------------------------
// Globals
// ---------------------------------------------------------------------------

static HMODULE g_hModule = nullptr;
static LONG    g_cLocks  = 0;  // DLL lock count for DllCanUnloadNow

// CLSID must match src/tts/sapi_registration.py TITAN_TTS_CLSID.
// {A8B5D3E1-7C4F-4D89-9A2F-3B1C5D7E9F24}
static const CLSID CLSID_TitanTTS =
    { 0xA8B5D3E1, 0x7C4F, 0x4D89,
      { 0x9A, 0x2F, 0x3B, 0x1C, 0x5D, 0x7E, 0x9F, 0x24 } };

static const wchar_t* TITAN_PIPE_NAME = L"\\\\.\\pipe\\TitanTTS";

// Expected PCM format we negotiate with SAPI and receive from the pipe.
static const WORD  PCM_CHANNELS        = 1;
static const DWORD PCM_SAMPLES_PER_SEC = 22050;
static const WORD  PCM_BITS_PER_SAMPLE = 16;

// Target chunk size when writing to the SAPI site (~46ms at 22050/16/mono).
static const DWORD WRITE_CHUNK_BYTES = 4096;

// ---------------------------------------------------------------------------
// Debug log to %LOCALAPPDATA%\Titosoft\Titan\titantts_dll.log
// ---------------------------------------------------------------------------

static void DbgLog(const char* fmt, ...)
{
    char msg[1024];
    va_list args;
    va_start(args, fmt);
    _vsnprintf_s(msg, sizeof(msg), _TRUNCATE, fmt, args);
    va_end(args);

    char path[MAX_PATH];
    DWORD n = GetEnvironmentVariableA("LOCALAPPDATA", path, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return;
    strncat_s(path, MAX_PATH, "\\Titosoft\\Titan", _TRUNCATE);
    CreateDirectoryA(path, nullptr);  // Titosoft may not exist
    // Make the Titan subdir too - we can't easily check parents, just try.
    strncat_s(path, MAX_PATH, "\\titantts_dll.log", _TRUNCATE);

    HANDLE h = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                           nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return;

    SYSTEMTIME st;
    GetLocalTime(&st);
    char line[1200];
    int len = _snprintf_s(line, sizeof(line), _TRUNCATE,
                          "[%04d-%02d-%02d %02d:%02d:%02d] %s\r\n",
                          st.wYear, st.wMonth, st.wDay,
                          st.wHour, st.wMinute, st.wSecond, msg);
    if (len > 0) {
        DWORD written = 0;
        WriteFile(h, line, (DWORD)len, &written, nullptr);
    }
    CloseHandle(h);
}

// ---------------------------------------------------------------------------
// Built-in eSpeak NG fallback (when pipe server is not available)
// ---------------------------------------------------------------------------
//
// Loads the bundled libespeak-ng.dll from data/titantts engines/espeak/ and
// synthesizes directly. Reads TCE settings for voice/rate/volume so the
// fallback matches the user's configuration.

// eSpeak NG constants (matching the bundled build)
static const int ESPEAK_AUDIO_OUTPUT_RETRIEVAL = 0x2000;
static const int ESPEAK_RATE    = 1;
static const int ESPEAK_PITCH   = 4;
static const int ESPEAK_VOLUME  = 5;
static const int ESPEAK_CHARS_UTF8 = 1;

// eSpeak NG function pointer types
typedef int  (*fn_espeak_Initialize)(int, int, const char*, int);
typedef int  (*fn_espeak_SetVoiceByName)(const char*);
typedef int  (*fn_espeak_SetParameter)(int, int, int);
typedef int  (*fn_espeak_Synth)(const void*, size_t, unsigned int, int,
                                unsigned int, unsigned int, unsigned int*, void*);
typedef int  (*fn_espeak_Synchronize)(void);
typedef int  (*fn_espeak_Cancel)(void);
typedef void (*fn_espeak_SetSynthCallback)(void*);

// Callback type: int callback(short* wav, int numsamples, espeak_EVENT* events)
typedef int (*t_espeak_synth_callback)(short*, int, void*);

class EspeakFallback
{
public:
    EspeakFallback() { InitializeCriticalSection(&m_cs); }
    ~EspeakFallback()
    {
        Shutdown();
        DeleteCriticalSection(&m_cs);
    }

    bool Synthesize(const std::wstring& text, LONG siteRate, LONG sitePitch,
                    USHORT siteVolume, std::vector<BYTE>& outPcm)
    {
        outPcm.clear();
        if (!EnsureLoaded()) return false;

        EnterCriticalSection(&m_cs);

        // Re-read TCE settings for voice only (not rate/pitch — SAPI controls those)
        ApplyVoiceSettings();

        // Apply SAPI site rate natively — changes speed WITHOUT pitch.
        // Maps SAPI -10..+10 to eSpeak WPM 80..450 (default 175).
        if (m_pSetParam) {
            int espeakRate = 175 + (int)(siteRate * 27.5);
            if (espeakRate < 80) espeakRate = 80;
            if (espeakRate > 450) espeakRate = 450;
            m_pSetParam(ESPEAK_RATE, espeakRate, 0);

            // Apply SAPI site pitch natively — changes tone WITHOUT speed.
            // Maps SAPI -10..+10 to eSpeak pitch 0..99 (default 50).
            int espeakPitch = 50 + (int)(sitePitch * 5);
            if (espeakPitch < 0) espeakPitch = 0;
            if (espeakPitch > 99) espeakPitch = 99;
            m_pSetParam(ESPEAK_PITCH, espeakPitch, 0);

            // Apply SAPI site volume natively.
            int espeakVol = (siteVolume * 200) / 100;
            if (espeakVol < 0) espeakVol = 0;
            if (espeakVol > 200) espeakVol = 200;
            m_pSetParam(ESPEAK_VOLUME, espeakVol, 0);
        }

        m_audioBuffer.clear();
        s_instance = this;

        m_pSetCallback((void*)(t_espeak_synth_callback)&AudioCallback);

        // Convert text to UTF-8
        int utf8Len = WideCharToMultiByte(CP_UTF8, 0, text.c_str(), (int)text.size(),
                                          nullptr, 0, nullptr, nullptr);
        std::vector<char> utf8(utf8Len + 1, 0);
        if (utf8Len > 0) {
            WideCharToMultiByte(CP_UTF8, 0, text.c_str(), (int)text.size(),
                                utf8.data(), utf8Len, nullptr, nullptr);
        }

        int result = m_pSynth(utf8.data(), (size_t)(utf8Len + 1),
                              0, 0, 0, ESPEAK_CHARS_UTF8, nullptr, nullptr);
        m_pSync();
        m_pSetCallback(nullptr);

        if (result != 0 || m_audioBuffer.empty()) {
            DbgLog("eSpeak: synth returned %d, buffer=%zu", result, m_audioBuffer.size());
            LeaveCriticalSection(&m_cs);
            return false;
        }

        // eSpeak outputs 16-bit signed mono PCM at m_sampleRate.
        // Convert to target format (22050 Hz / 16-bit / mono).
        if (m_sampleRate == (int)PCM_SAMPLES_PER_SEC) {
            outPcm.resize(m_audioBuffer.size() * sizeof(short));
            memcpy(outPcm.data(), m_audioBuffer.data(), outPcm.size());
        } else {
            // Linear resample to 22050 Hz
            double ratio = (double)PCM_SAMPLES_PER_SEC / m_sampleRate;
            size_t outSamples = (size_t)(m_audioBuffer.size() * ratio);
            if (outSamples == 0) { LeaveCriticalSection(&m_cs); return false; }
            outPcm.resize(outSamples * sizeof(short));
            short* dst = (short*)outPcm.data();
            for (size_t i = 0; i < outSamples; i++) {
                size_t idx = (size_t)(i / ratio);
                if (idx >= m_audioBuffer.size()) idx = m_audioBuffer.size() - 1;
                dst[i] = m_audioBuffer[idx];
            }
        }

        // Rate, pitch, and volume are applied natively above — no
        // post-processing resampling needed (which would change tempo
        // instead of just speed or just pitch).

        LeaveCriticalSection(&m_cs);
        DbgLog("eSpeak: synthesized %u bytes PCM", (unsigned)outPcm.size());
        return true;
    }

    void Shutdown()
    {
        EnterCriticalSection(&m_cs);
        if (m_hLib) {
            if (m_pCancel) m_pCancel();
            FreeLibrary(m_hLib);
            m_hLib = nullptr;
        }
        m_initialized = false;
        LeaveCriticalSection(&m_cs);
    }

private:
    // --- eSpeak loading and initialization ---

    bool EnsureLoaded()
    {
        if (m_initialized) return true;

        EnterCriticalSection(&m_cs);
        if (m_initialized) { LeaveCriticalSection(&m_cs); return true; }

        // Find libespeak-ng.dll relative to our DLL:
        // DLL is at data/lib/titanttsNN.dll
        // eSpeak is at data/titantts engines/espeak/libespeak-ng.dll
        wchar_t dllPath[MAX_PATH];
        GetModuleFileNameW(g_hModule, dllPath, MAX_PATH);

        std::wstring base(dllPath);
        // Strip filename -> data/lib/
        size_t pos = base.rfind(L'\\');
        if (pos != std::wstring::npos) base = base.substr(0, pos);
        // Strip "lib" -> data/
        pos = base.rfind(L'\\');
        if (pos != std::wstring::npos) base = base.substr(0, pos);

        std::wstring espeakDir = base + L"\\titantts engines\\espeak";
        std::wstring espeakDll = espeakDir + L"\\libespeak-ng.dll";
        std::wstring espeakData = espeakDir + L"\\espeak-ng-data";

        // Add eSpeak dir to DLL search path
        AddDllDirectory(espeakDir.c_str());

        m_hLib = LoadLibraryW(espeakDll.c_str());
        if (!m_hLib) {
            DbgLog("eSpeak: LoadLibrary failed: %lu", GetLastError());
            LeaveCriticalSection(&m_cs);
            return false;
        }

        // Resolve function pointers
        m_pInit        = (fn_espeak_Initialize)     GetProcAddress(m_hLib, "espeak_Initialize");
        m_pSetVoice    = (fn_espeak_SetVoiceByName) GetProcAddress(m_hLib, "espeak_SetVoiceByName");
        m_pSetParam    = (fn_espeak_SetParameter)   GetProcAddress(m_hLib, "espeak_SetParameter");
        m_pSynth       = (fn_espeak_Synth)          GetProcAddress(m_hLib, "espeak_Synth");
        m_pSync        = (fn_espeak_Synchronize)    GetProcAddress(m_hLib, "espeak_Synchronize");
        m_pCancel      = (fn_espeak_Cancel)         GetProcAddress(m_hLib, "espeak_Cancel");
        m_pSetCallback = (fn_espeak_SetSynthCallback) GetProcAddress(m_hLib, "espeak_SetSynthCallback");

        if (!m_pInit || !m_pSynth || !m_pSync || !m_pSetCallback) {
            DbgLog("eSpeak: missing function exports");
            FreeLibrary(m_hLib); m_hLib = nullptr;
            LeaveCriticalSection(&m_cs);
            return false;
        }

        // Initialize eSpeak in retrieval mode (audio via callback, no playback)
        char dataPathUtf8[MAX_PATH * 3];
        WideCharToMultiByte(CP_UTF8, 0, espeakData.c_str(), -1,
                            dataPathUtf8, sizeof(dataPathUtf8), nullptr, nullptr);

        int sr = m_pInit(ESPEAK_AUDIO_OUTPUT_RETRIEVAL, 0, dataPathUtf8, 0);
        if (sr < 0) {
            DbgLog("eSpeak: Initialize failed: %d", sr);
            FreeLibrary(m_hLib); m_hLib = nullptr;
            LeaveCriticalSection(&m_cs);
            return false;
        }
        m_sampleRate = sr;

        // Set defaults before applying TCE settings
        if (m_pSetParam) {
            m_pSetParam(ESPEAK_RATE,   175, 0);
            m_pSetParam(ESPEAK_PITCH,   50, 0);
            m_pSetParam(ESPEAK_VOLUME, 100, 0);
        }

        m_initialized = true;
        DbgLog("eSpeak: initialized, sample_rate=%d", m_sampleRate);

        LeaveCriticalSection(&m_cs);
        return true;
    }

    // --- TCE settings reading ---

    void ApplyVoiceSettings()
    {
        // Only reads the configured voice from TCE settings.
        // Rate, pitch, and volume are NOT read here — they come from the
        // SAPI client (screen reader / app) via siteRate/sitePitch/siteVolume
        // and are applied natively in Synthesize().
        char appdata[MAX_PATH];
        DWORD n = GetEnvironmentVariableA("APPDATA", appdata, MAX_PATH);
        if (n == 0 || n >= MAX_PATH) return;

        std::string iniPath = std::string(appdata) + "\\titosoft\\Titan\\bg5settings.ini";

        FILE* f = nullptr;
        if (fopen_s(&f, iniPath.c_str(), "r") != 0 || !f) return;

        bool inSection = false;
        std::string voice;

        char line[1024];
        while (fgets(line, sizeof(line), f)) {
            char* s = line;
            while (*s == ' ' || *s == '\t') s++;
            size_t len = strlen(s);
            while (len > 0 && (s[len-1] == '\n' || s[len-1] == '\r' || s[len-1] == ' '))
                s[--len] = 0;

            if (s[0] == '[') {
                inSection = (strcmp(s, "[stereo_speech]") == 0);
                continue;
            }
            if (!inSection) continue;

            char* eq = strchr(s, '=');
            if (!eq) continue;
            *eq = 0;
            const char* key = s;
            const char* val = eq + 1;

            if (strcmp(key, "voice") == 0) voice = val;
        }
        fclose(f);

        // Apply voice (eSpeak voice names like "pl", "en", "de", etc.)
        if (!voice.empty() && m_pSetVoice) {
            m_pSetVoice(voice.c_str());
        }
    }

    // --- eSpeak synthesis callback ---

    static int __cdecl AudioCallback(short* wav, int numsamples, void* /*events*/)
    {
        if (numsamples > 0 && wav && s_instance) {
            s_instance->m_audioBuffer.insert(
                s_instance->m_audioBuffer.end(), wav, wav + numsamples);
        }
        return 0;  // 0 = continue, 1 = abort
    }

    // --- Members ---

    CRITICAL_SECTION m_cs;
    HMODULE  m_hLib        = nullptr;
    bool     m_initialized = false;
    int      m_sampleRate  = 22050;

    fn_espeak_Initialize       m_pInit        = nullptr;
    fn_espeak_SetVoiceByName   m_pSetVoice    = nullptr;
    fn_espeak_SetParameter     m_pSetParam    = nullptr;
    fn_espeak_Synth            m_pSynth       = nullptr;
    fn_espeak_Synchronize      m_pSync        = nullptr;
    fn_espeak_Cancel           m_pCancel      = nullptr;
    fn_espeak_SetSynthCallback m_pSetCallback = nullptr;

    std::vector<short> m_audioBuffer;

    static EspeakFallback* s_instance;  // for callback (protected by m_cs)
};

EspeakFallback* EspeakFallback::s_instance = nullptr;
static EspeakFallback g_espeakFallback;

// ---------------------------------------------------------------------------
// Built-in SAPI5 fallback (when pipe + eSpeak are both unavailable)
// ---------------------------------------------------------------------------
//
// Uses COM ISpVoice to synthesize through other installed SAPI5 voices.
// Skips the TitanTTS voice token to prevent infinite recursion.
// Reads the configured voice from TCE settings (engine.sapi5.voice).
// Outputs to SpMemoryStream, then converts to 22050/16/mono PCM.

class Sapi5Fallback
{
public:
    Sapi5Fallback() { InitializeCriticalSection(&m_cs); }
    ~Sapi5Fallback()
    {
        Shutdown();
        DeleteCriticalSection(&m_cs);
    }

    bool Synthesize(const std::wstring& text, LONG siteRate, LONG sitePitch,
                    USHORT siteVolume, std::vector<BYTE>& outPcm)
    {
        outPcm.clear();

        EnterCriticalSection(&m_cs);

        if (!EnsureInitialized()) {
            LeaveCriticalSection(&m_cs);
            return false;
        }

        // Re-read TCE settings for voice selection only
        ApplyVoiceSettings();

        // Apply SAPI site rate natively — changes speed WITHOUT pitch.
        // SAPI5 voice.Rate range is -10..+10 (same as our wire format).
        m_pVoice->SetRate((long)siteRate);

        // Apply SAPI site volume natively.
        USHORT sapiVol = siteVolume;
        if (sapiVol > 100) sapiVol = 100;
        m_pVoice->SetVolume(sapiVol);

        // Build text with optional SSML pitch markup.
        // Pitch changes tone WITHOUT speed — applied via SAPI's SSML support.
        std::wstring speakText = text;
        if (sitePitch != 0) {
            long clampedPitch = sitePitch;
            if (clampedPitch < -10) clampedPitch = -10;
            if (clampedPitch > 10) clampedPitch = 10;
            wchar_t pitchBuf[128];
            _snwprintf_s(pitchBuf, _countof(pitchBuf), _TRUNCATE,
                         L"<pitch absmiddle=\"%ld\">", clampedPitch);
            speakText = std::wstring(pitchBuf) + text + L"</pitch>";
        }

        // Create a memory stream for output (22050/16/mono)
        ISpStream* pStream = nullptr;
        IStream* pMemStream = nullptr;

        HRESULT hr = CreateStreamOnHGlobal(nullptr, TRUE, &pMemStream);
        if (FAILED(hr) || !pMemStream) {
            DbgLog("SAPI5 fallback: CreateStreamOnHGlobal failed: 0x%08x", hr);
            LeaveCriticalSection(&m_cs);
            return false;
        }

        WAVEFORMATEX wfx = {};
        wfx.wFormatTag      = WAVE_FORMAT_PCM;
        wfx.nChannels       = PCM_CHANNELS;
        wfx.nSamplesPerSec  = PCM_SAMPLES_PER_SEC;
        wfx.wBitsPerSample  = PCM_BITS_PER_SAMPLE;
        wfx.nBlockAlign     = (PCM_BITS_PER_SAMPLE / 8) * PCM_CHANNELS;
        wfx.nAvgBytesPerSec = PCM_SAMPLES_PER_SEC * wfx.nBlockAlign;
        wfx.cbSize          = 0;

        GUID fmtGuid = SPDFID_WaveFormatEx;
        hr = CoCreateInstance(CLSID_SpStream, nullptr, CLSCTX_ALL,
                              IID_ISpStream, (void**)&pStream);
        if (FAILED(hr) || !pStream) {
            DbgLog("SAPI5 fallback: CoCreateInstance SpStream failed: 0x%08x", hr);
            pMemStream->Release();
            LeaveCriticalSection(&m_cs);
            return false;
        }

        hr = pStream->SetBaseStream(pMemStream, fmtGuid, &wfx);
        if (FAILED(hr)) {
            DbgLog("SAPI5 fallback: SetBaseStream failed: 0x%08x", hr);
            pStream->Release();
            pMemStream->Release();
            LeaveCriticalSection(&m_cs);
            return false;
        }

        // Direct output to our memory stream
        hr = m_pVoice->SetOutput(pStream, TRUE);
        if (FAILED(hr)) {
            DbgLog("SAPI5 fallback: SetOutput failed: 0x%08x", hr);
            pStream->Release();
            pMemStream->Release();
            LeaveCriticalSection(&m_cs);
            return false;
        }

        // Speak synchronously
        hr = m_pVoice->Speak(speakText.c_str(), SPF_DEFAULT, nullptr);
        if (FAILED(hr)) {
            DbgLog("SAPI5 fallback: Speak failed: 0x%08x", hr);
            m_pVoice->SetOutput(nullptr, TRUE);
            pStream->Release();
            pMemStream->Release();
            LeaveCriticalSection(&m_cs);
            return false;
        }

        // Read PCM from the memory stream
        LARGE_INTEGER liZero = {};
        pMemStream->Seek(liZero, STREAM_SEEK_SET, nullptr);

        STATSTG stat = {};
        hr = pMemStream->Stat(&stat, STATFLAG_NONAME);
        if (FAILED(hr) || stat.cbSize.QuadPart == 0) {
            DbgLog("SAPI5 fallback: stream empty or Stat failed");
            m_pVoice->SetOutput(nullptr, TRUE);
            pStream->Release();
            pMemStream->Release();
            LeaveCriticalSection(&m_cs);
            return false;
        }

        DWORD pcmLen = (DWORD)stat.cbSize.QuadPart;
        // Reasonable cap: 30 MB
        if (pcmLen > 30u * 1024 * 1024) {
            DbgLog("SAPI5 fallback: absurd pcmLen=%u", pcmLen);
            m_pVoice->SetOutput(nullptr, TRUE);
            pStream->Release();
            pMemStream->Release();
            LeaveCriticalSection(&m_cs);
            return false;
        }

        outPcm.resize(pcmLen);
        ULONG bytesRead = 0;
        hr = pMemStream->Read(outPcm.data(), pcmLen, &bytesRead);
        if (FAILED(hr) || bytesRead == 0) {
            DbgLog("SAPI5 fallback: Read failed: 0x%08x, read=%u", hr, bytesRead);
            outPcm.clear();
            m_pVoice->SetOutput(nullptr, TRUE);
            pStream->Release();
            pMemStream->Release();
            LeaveCriticalSection(&m_cs);
            return false;
        }
        outPcm.resize(bytesRead);

        // Reset output to default
        m_pVoice->SetOutput(nullptr, TRUE);
        pStream->Release();
        pMemStream->Release();

        // Rate, pitch, and volume are all applied natively above — no
        // post-processing resampling (which would change tempo: both
        // speed and pitch together).

        LeaveCriticalSection(&m_cs);
        DbgLog("SAPI5 fallback: synthesized %u bytes PCM", (unsigned)outPcm.size());
        return true;
    }

    void Shutdown()
    {
        EnterCriticalSection(&m_cs);
        if (m_pVoice) {
            m_pVoice->Release();
            m_pVoice = nullptr;
        }
        m_initialized = false;
        LeaveCriticalSection(&m_cs);
    }

private:
    bool EnsureInitialized()
    {
        if (m_initialized && m_pVoice) return true;

        // Need COM. We use CoInitializeEx with COINIT_APARTMENTTHREADED
        // because ISpVoice needs STA or explicit MTA handling. If COM is
        // already initialized in this thread, the call succeeds or returns
        // S_FALSE / RPC_E_CHANGED_MODE (all acceptable).
        HRESULT hr = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
        if (FAILED(hr) && hr != S_FALSE && hr != RPC_E_CHANGED_MODE) {
            DbgLog("SAPI5 fallback: CoInitializeEx failed: 0x%08x", hr);
            return false;
        }
        m_comInitialized = SUCCEEDED(hr) || hr == S_FALSE;

        hr = CoCreateInstance(CLSID_SpVoice, nullptr, CLSCTX_ALL,
                              IID_ISpVoice, (void**)&m_pVoice);
        if (FAILED(hr) || !m_pVoice) {
            DbgLog("SAPI5 fallback: CoCreateInstance SpVoice failed: 0x%08x", hr);
            return false;
        }

        // Select a non-TitanTTS voice
        SelectSafeVoice();

        m_initialized = true;
        DbgLog("SAPI5 fallback: initialized");
        return true;
    }

    // Pick the first available SAPI5 voice that is NOT TitanTTS (anti-recursion).
    // If a specific voice is configured in TCE settings, prefer that one.
    void SelectSafeVoice()
    {
        if (!m_pVoice) return;

        ISpObjectTokenCategory* pCategory = nullptr;
        HRESULT hr = CoCreateInstance(CLSID_SpObjectTokenCategory, nullptr, CLSCTX_ALL,
                                      IID_ISpObjectTokenCategory, (void**)&pCategory);
        if (FAILED(hr) || !pCategory) return;

        hr = pCategory->SetId(SPCAT_VOICES, FALSE);
        if (FAILED(hr)) { pCategory->Release(); return; }

        IEnumSpObjectTokens* pEnum = nullptr;
        hr = pCategory->EnumTokens(nullptr, nullptr, &pEnum);
        if (FAILED(hr) || !pEnum) { pCategory->Release(); return; }

        ULONG count = 0;
        pEnum->GetCount(&count);

        // Collect all non-TitanTTS voice tokens
        ISpObjectToken* pFirstSafe = nullptr;
        for (ULONG i = 0; i < count; i++) {
            ISpObjectToken* pToken = nullptr;
            hr = pEnum->Item(i, &pToken);
            if (FAILED(hr) || !pToken) continue;

            // Check token ID for TitanTTS marker
            LPWSTR tokenId = nullptr;
            pToken->GetId(&tokenId);
            bool isTitan = false;
            if (tokenId) {
                isTitan = (wcsstr(tokenId, L"TitanTTS") != nullptr);
                CoTaskMemFree(tokenId);
            }

            if (!isTitan && !pFirstSafe) {
                pFirstSafe = pToken;  // Keep ref
            } else {
                pToken->Release();
            }
        }

        if (pFirstSafe) {
            m_pVoice->SetVoice(pFirstSafe);
            pFirstSafe->Release();
            DbgLog("SAPI5 fallback: selected safe voice");
        } else {
            DbgLog("SAPI5 fallback: no non-TitanTTS voice found!");
        }

        pEnum->Release();
        pCategory->Release();
    }

    void ApplyVoiceSettings()
    {
        // Only reads the configured voice from TCE settings.
        // Rate, pitch, and volume are NOT read here — they come from the
        // SAPI client via siteRate/sitePitch/siteVolume and are applied
        // natively in Synthesize().
        if (!m_pVoice) return;

        char appdata[MAX_PATH];
        DWORD n = GetEnvironmentVariableA("APPDATA", appdata, MAX_PATH);
        if (n == 0 || n >= MAX_PATH) return;

        std::string iniPath = std::string(appdata) + "\\titosoft\\Titan\\bg5settings.ini";

        FILE* f = nullptr;
        if (fopen_s(&f, iniPath.c_str(), "r") != 0 || !f) return;

        bool inSection = false;
        std::string configuredVoice;  // engine.sapi5.voice

        char line[1024];
        while (fgets(line, sizeof(line), f)) {
            char* s = line;
            while (*s == ' ' || *s == '\t') s++;
            size_t len = strlen(s);
            while (len > 0 && (s[len-1] == '\n' || s[len-1] == '\r' || s[len-1] == ' '))
                s[--len] = 0;

            if (s[0] == '[') {
                inSection = (strcmp(s, "[stereo_speech]") == 0);
                continue;
            }
            if (!inSection) continue;

            char* eq = strchr(s, '=');
            if (!eq) continue;
            *eq = 0;
            const char* key = s;
            const char* val = eq + 1;

            if (strcmp(key, "engine.sapi5.voice") == 0) configuredVoice = val;
        }
        fclose(f);

        // If a specific SAPI5 voice is configured, try to select it
        if (!configuredVoice.empty()) {
            SelectVoiceByName(configuredVoice);
        }
    }

    void SelectVoiceByName(const std::string& voiceName)
    {
        if (!m_pVoice || voiceName.empty()) return;

        // Convert voice name to wide string
        int wlen = MultiByteToWideChar(CP_UTF8, 0, voiceName.c_str(),
                                       (int)voiceName.size(), nullptr, 0);
        if (wlen <= 0) return;
        std::wstring wVoiceName(wlen, 0);
        MultiByteToWideChar(CP_UTF8, 0, voiceName.c_str(), (int)voiceName.size(),
                            &wVoiceName[0], wlen);

        // Enumerate voices and find a match (skip TitanTTS)
        ISpObjectTokenCategory* pCategory = nullptr;
        HRESULT hr = CoCreateInstance(CLSID_SpObjectTokenCategory, nullptr, CLSCTX_ALL,
                                      IID_ISpObjectTokenCategory, (void**)&pCategory);
        if (FAILED(hr) || !pCategory) return;

        hr = pCategory->SetId(SPCAT_VOICES, FALSE);
        if (FAILED(hr)) { pCategory->Release(); return; }

        IEnumSpObjectTokens* pEnum = nullptr;
        hr = pCategory->EnumTokens(nullptr, nullptr, &pEnum);
        if (FAILED(hr) || !pEnum) { pCategory->Release(); return; }

        ULONG count = 0;
        pEnum->GetCount(&count);

        for (ULONG i = 0; i < count; i++) {
            ISpObjectToken* pToken = nullptr;
            hr = pEnum->Item(i, &pToken);
            if (FAILED(hr) || !pToken) continue;

            // Skip TitanTTS
            LPWSTR tokenId = nullptr;
            pToken->GetId(&tokenId);
            bool isTitan = false;
            if (tokenId) {
                isTitan = (wcsstr(tokenId, L"TitanTTS") != nullptr);
                CoTaskMemFree(tokenId);
            }

            if (isTitan) { pToken->Release(); continue; }

            // Check the voice name attribute
            ISpDataKey* pAttrs = nullptr;
            hr = pToken->OpenKey(L"Attributes", &pAttrs);
            if (SUCCEEDED(hr) && pAttrs) {
                LPWSTR nameVal = nullptr;
                hr = pAttrs->GetStringValue(L"Name", &nameVal);
                if (SUCCEEDED(hr) && nameVal) {
                    if (_wcsicmp(nameVal, wVoiceName.c_str()) == 0) {
                        m_pVoice->SetVoice(pToken);
                        CoTaskMemFree(nameVal);
                        pAttrs->Release();
                        pToken->Release();
                        pEnum->Release();
                        pCategory->Release();
                        DbgLog("SAPI5 fallback: selected configured voice");
                        return;
                    }
                    CoTaskMemFree(nameVal);
                }
                pAttrs->Release();
            }
            pToken->Release();
        }

        pEnum->Release();
        pCategory->Release();
        // Voice not found — keep whatever was selected before
    }

    CRITICAL_SECTION m_cs;
    ISpVoice*        m_pVoice        = nullptr;
    bool             m_initialized   = false;
    bool             m_comInitialized = false;
};

static Sapi5Fallback g_sapi5Fallback;

// ---------------------------------------------------------------------------
// Named pipe client: request PCM for one text fragment
// ---------------------------------------------------------------------------
//
// Wire protocol v2 (little-endian):
//   client -> server:
//     uint32  version = 2
//     int32   rate         (-10 .. +10, SAPI site rate — speed only)
//     int32   pitch        (-10 .. +10, SAPI fragment pitch — tone only)
//     uint32  volume       (0 .. 100, SAPI site volume)
//     uint32  text_byte_len
//     bytes   text (UTF-8)
//   server -> client:
//     uint32  status       (0 = OK, !=0 = error)
//     uint32  pcm_byte_len
//     bytes   pcm (22050 Hz / 16-bit / mono PCM LE)

static bool PipeWriteAll(HANDLE h, const void* data, DWORD len)
{
    const BYTE* p = (const BYTE*)data;
    while (len > 0) {
        DWORD written = 0;
        if (!WriteFile(h, p, len, &written, nullptr) || written == 0) return false;
        p += written;
        len -= written;
    }
    return true;
}

static bool PipeReadAll(HANDLE h, void* data, DWORD len)
{
    BYTE* p = (BYTE*)data;
    while (len > 0) {
        DWORD read = 0;
        if (!ReadFile(h, p, len, &read, nullptr) || read == 0) return false;
        p += read;
        len -= read;
    }
    return true;
}

static bool RequestSynthesisViaPipe(const std::wstring& text, LONG siteRate,
                                    LONG sitePitch, USHORT siteVolume,
                                    std::vector<BYTE>& outPcm)
{
    outPcm.clear();

    // Wait up to 500ms for the pipe (reduced from 2s so fallback kicks in fast)
    if (!WaitNamedPipeW(TITAN_PIPE_NAME, 500)) {
        return false;
    }

    HANDLE h = CreateFileW(TITAN_PIPE_NAME,
                           GENERIC_READ | GENERIC_WRITE,
                           0, nullptr, OPEN_EXISTING, 0, nullptr);
    if (h == INVALID_HANDLE_VALUE) {
        return false;
    }

    DWORD mode = PIPE_READMODE_BYTE;
    SetNamedPipeHandleState(h, &mode, nullptr, nullptr);

    // Encode UTF-8.
    int utf8Len = WideCharToMultiByte(CP_UTF8, 0, text.c_str(), (int)text.size(),
                                      nullptr, 0, nullptr, nullptr);
    std::vector<char> utf8(utf8Len);
    if (utf8Len > 0) {
        WideCharToMultiByte(CP_UTF8, 0, text.c_str(), (int)text.size(),
                            utf8.data(), utf8Len, nullptr, nullptr);
    }

    // Protocol v2: version + rate + pitch + volume + text_len + text
    uint32_t version = 2;
    int32_t  rate = (int32_t)siteRate;
    int32_t  pitch = (int32_t)sitePitch;
    uint32_t volume = (uint32_t)siteVolume;
    uint32_t textLen = (uint32_t)utf8Len;

    bool ok = PipeWriteAll(h, &version, sizeof(version))
           && PipeWriteAll(h, &rate,    sizeof(rate))
           && PipeWriteAll(h, &pitch,   sizeof(pitch))
           && PipeWriteAll(h, &volume,  sizeof(volume))
           && PipeWriteAll(h, &textLen, sizeof(textLen))
           && (textLen == 0 || PipeWriteAll(h, utf8.data(), textLen));
    if (!ok) {
        DbgLog("Pipe write failed");
        CloseHandle(h);
        return false;
    }

    uint32_t status = 0, pcmLen = 0;
    ok = PipeReadAll(h, &status, sizeof(status))
      && PipeReadAll(h, &pcmLen, sizeof(pcmLen));
    if (!ok) {
        DbgLog("Pipe header read failed");
        CloseHandle(h);
        return false;
    }
    if (status != 0) {
        DbgLog("Pipe server returned status=%u", status);
        CloseHandle(h);
        return false;
    }
    if (pcmLen > 0) {
        // Reasonable cap: 30 MB (~5 minutes of audio).
        if (pcmLen > 30u * 1024 * 1024) {
            DbgLog("Pipe server returned absurd pcmLen=%u", pcmLen);
            CloseHandle(h);
            return false;
        }
        outPcm.resize(pcmLen);
        if (!PipeReadAll(h, outPcm.data(), pcmLen)) {
            DbgLog("Pipe PCM read failed");
            CloseHandle(h);
            return false;
        }
    }
    CloseHandle(h);
    return true;
}

// Unified synthesis: try pipe, then eSpeak, then SAPI5 voices
static bool RequestSynthesis(const std::wstring& text, LONG siteRate,
                             LONG sitePitch, USHORT siteVolume,
                             std::vector<BYTE>& outPcm)
{
    // 1. Try the pipe server (supports all TCE engines)
    if (RequestSynthesisViaPipe(text, siteRate, sitePitch, siteVolume, outPcm)) {
        return true;
    }

    // 2. Pipe not available — try built-in eSpeak
    DbgLog("Pipe unavailable, trying eSpeak fallback");
    if (g_espeakFallback.Synthesize(text, siteRate, sitePitch, siteVolume, outPcm)) {
        return true;
    }

    // 3. eSpeak also failed — try other installed SAPI5 voices
    DbgLog("eSpeak fallback failed, trying SAPI5 fallback");
    return g_sapi5Fallback.Synthesize(text, siteRate, sitePitch, siteVolume, outPcm);
}

// ---------------------------------------------------------------------------
// Helpers for SAPI's SPVTEXTFRAG list
// ---------------------------------------------------------------------------

static void ExtractFragmentText(const SPVTEXTFRAG* frag, std::wstring& out)
{
    out.clear();
    if (frag->pTextStart && frag->ulTextLen > 0) {
        out.assign(frag->pTextStart, frag->ulTextLen);
    }
}

static std::wstring TrimWs(const std::wstring& s)
{
    size_t a = 0, b = s.size();
    while (a < b && (s[a] == L' ' || s[a] == L'\t' || s[a] == L'\r' || s[a] == L'\n')) a++;
    while (b > a && (s[b-1] == L' ' || s[b-1] == L'\t' || s[b-1] == L'\r' || s[b-1] == L'\n')) b--;
    return s.substr(a, b - a);
}

// ---------------------------------------------------------------------------
// CTitanTTSEngine - the actual voice
// ---------------------------------------------------------------------------

class CTitanTTSEngine : public ISpTTSEngine, public ISpObjectWithToken
{
public:
    CTitanTTSEngine() : m_cRef(1), m_pToken(nullptr)
    {
        InterlockedIncrement(&g_cLocks);
    }

    virtual ~CTitanTTSEngine()
    {
        if (m_pToken) m_pToken->Release();
        InterlockedDecrement(&g_cLocks);
    }

    // --- IUnknown ---
    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override
    {
        if (!ppv) return E_POINTER;
        *ppv = nullptr;
        if (riid == IID_IUnknown || riid == IID_ISpTTSEngine) {
            *ppv = static_cast<ISpTTSEngine*>(this);
        } else if (riid == IID_ISpObjectWithToken) {
            *ppv = static_cast<ISpObjectWithToken*>(this);
        } else {
            return E_NOINTERFACE;
        }
        AddRef();
        return S_OK;
    }
    STDMETHODIMP_(ULONG) AddRef() override  { return InterlockedIncrement(&m_cRef); }
    STDMETHODIMP_(ULONG) Release() override
    {
        ULONG n = InterlockedDecrement(&m_cRef);
        if (n == 0) delete this;
        return n;
    }

    // --- ISpObjectWithToken ---
    STDMETHODIMP SetObjectToken(ISpObjectToken* pToken) override
    {
        if (pToken) pToken->AddRef();
        if (m_pToken) m_pToken->Release();
        m_pToken = pToken;
        return S_OK;
    }
    STDMETHODIMP GetObjectToken(ISpObjectToken** ppToken) override
    {
        if (!ppToken) return E_POINTER;
        *ppToken = m_pToken;
        if (m_pToken) m_pToken->AddRef();
        return S_OK;
    }

    // --- ISpTTSEngine ---
    STDMETHODIMP GetOutputFormat(const GUID* /*pTargetFmtId*/,
                                 const WAVEFORMATEX* /*pTargetWaveFormatEx*/,
                                 GUID* pDesiredFmtId,
                                 WAVEFORMATEX** ppCoMemDesiredWaveFormatEx) override
    {
        if (!pDesiredFmtId || !ppCoMemDesiredWaveFormatEx) return E_POINTER;

        *pDesiredFmtId = SPDFID_WaveFormatEx;

        WAVEFORMATEX* wfx = (WAVEFORMATEX*)CoTaskMemAlloc(sizeof(WAVEFORMATEX));
        if (!wfx) return E_OUTOFMEMORY;
        ZeroMemory(wfx, sizeof(WAVEFORMATEX));
        wfx->wFormatTag      = WAVE_FORMAT_PCM;
        wfx->nChannels       = PCM_CHANNELS;
        wfx->nSamplesPerSec  = PCM_SAMPLES_PER_SEC;
        wfx->wBitsPerSample  = PCM_BITS_PER_SAMPLE;
        wfx->nBlockAlign     = (PCM_BITS_PER_SAMPLE / 8) * PCM_CHANNELS;
        wfx->nAvgBytesPerSec = PCM_SAMPLES_PER_SEC * wfx->nBlockAlign;
        wfx->cbSize          = 0;

        *ppCoMemDesiredWaveFormatEx = wfx;
        return S_OK;
    }

    STDMETHODIMP Speak(DWORD /*dwSpeakFlags*/,
                       REFGUID /*rguidFormatId*/,
                       const WAVEFORMATEX* /*pWaveFormatEx*/,
                       const SPVTEXTFRAG* pTextFragList,
                       ISpTTSEngineSite* pOutputSite) override
    {
        if (!pOutputSite) return E_POINTER;

        // Read initial site state once - we re-read GetActions() per chunk.
        LONG   siteRate   = 0;
        USHORT siteVolume = 100;
        pOutputSite->GetRate(&siteRate);
        pOutputSite->GetVolume(&siteVolume);

        for (const SPVTEXTFRAG* frag = pTextFragList; frag; frag = frag->pNext) {
            if (pOutputSite->GetActions() & SPVES_ABORT) return S_OK;

            SPVACTIONS action = frag->State.eAction;

            if (action == SPVA_Silence) {
                // Produce site-aware silence in target PCM format.
                LONG ms = frag->State.SilenceMSecs;
                if (ms < 0) ms = 0;
                DWORD samples = (DWORD)((PCM_SAMPLES_PER_SEC * (DWORD)ms) / 1000u);
                DWORD byteLen = samples * (PCM_BITS_PER_SAMPLE / 8) * PCM_CHANNELS;
                if (byteLen > 0) {
                    std::vector<BYTE> silence(byteLen, 0);
                    if (!WriteChunks(pOutputSite, silence.data(), byteLen)) return S_OK;
                }
                continue;
            }

            if (action != SPVA_Speak && action != SPVA_SpellOut &&
                action != SPVA_Pronounce) {
                // Bookmarks, ParseUnknownTag, etc. - ignore for now.
                continue;
            }

            std::wstring text;
            ExtractFragmentText(frag, text);
            text = TrimWs(text);
            if (text.empty()) continue;

            // Stack per-fragment rate/pitch/volume on top of the site values.
            LONG   effRate   = siteRate + (LONG)frag->State.RateAdj;
            LONG   effPitch  = (LONG)frag->State.PitchAdj.MiddleAdj;
            USHORT fragVol   = (USHORT)frag->State.Volume;
            USHORT effVolume = (USHORT)(((ULONG)siteVolume * (ULONG)fragVol) / 100u);
            if (effVolume > 100) effVolume = 100;

            std::vector<BYTE> pcm;
            if (!RequestSynthesis(text, effRate, effPitch, effVolume, pcm)) {
                DbgLog("RequestSynthesis failed for fragment (len=%u)",
                       (unsigned)text.size());
                continue;  // skip this fragment, keep going
            }
            if (!pcm.empty()) {
                if (!WriteChunks(pOutputSite, pcm.data(), (DWORD)pcm.size())) return S_OK;
            }
        }
        return S_OK;
    }

private:
    bool WriteChunks(ISpTTSEngineSite* site, const BYTE* data, DWORD len)
    {
        DWORD offset = 0;
        while (offset < len) {
            if (site->GetActions() & SPVES_ABORT) return false;
            DWORD chunk = len - offset;
            if (chunk > WRITE_CHUNK_BYTES) chunk = WRITE_CHUNK_BYTES;
            ULONG written = 0;
            HRESULT hr = site->Write(data + offset, chunk, &written);
            if (FAILED(hr)) {
                DbgLog("site->Write failed: hr=0x%08x", hr);
                return false;
            }
            if (written == 0) written = chunk;
            offset += written;
        }
        return true;
    }

    LONG            m_cRef;
    ISpObjectToken* m_pToken;
};

// ---------------------------------------------------------------------------
// Class factory
// ---------------------------------------------------------------------------

class CTitanTTSFactory : public IClassFactory
{
public:
    CTitanTTSFactory() : m_cRef(1) {}

    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override
    {
        if (!ppv) return E_POINTER;
        if (riid == IID_IUnknown || riid == IID_IClassFactory) {
            *ppv = static_cast<IClassFactory*>(this);
            AddRef();
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    STDMETHODIMP_(ULONG) AddRef() override  { return InterlockedIncrement(&m_cRef); }
    STDMETHODIMP_(ULONG) Release() override
    {
        ULONG n = InterlockedDecrement(&m_cRef);
        if (n == 0) delete this;
        return n;
    }

    STDMETHODIMP CreateInstance(IUnknown* pUnkOuter, REFIID riid, void** ppv) override
    {
        if (!ppv) return E_POINTER;
        *ppv = nullptr;
        if (pUnkOuter) return CLASS_E_NOAGGREGATION;

        CTitanTTSEngine* eng = new (std::nothrow) CTitanTTSEngine();
        if (!eng) return E_OUTOFMEMORY;
        HRESULT hr = eng->QueryInterface(riid, ppv);
        eng->Release();  // QI added the ref we actually return
        return hr;
    }

    STDMETHODIMP LockServer(BOOL fLock) override
    {
        if (fLock) InterlockedIncrement(&g_cLocks);
        else       InterlockedDecrement(&g_cLocks);
        return S_OK;
    }

private:
    LONG m_cRef;
};

// ---------------------------------------------------------------------------
// DLL exports
// ---------------------------------------------------------------------------

STDAPI DllGetClassObject(REFCLSID rclsid, REFIID riid, void** ppv)
{
    if (!ppv) return E_POINTER;
    *ppv = nullptr;
    if (rclsid != CLSID_TitanTTS) return CLASS_E_CLASSNOTAVAILABLE;

    CTitanTTSFactory* f = new (std::nothrow) CTitanTTSFactory();
    if (!f) return E_OUTOFMEMORY;
    HRESULT hr = f->QueryInterface(riid, ppv);
    f->Release();
    return hr;
}

STDAPI DllCanUnloadNow()
{
    return (g_cLocks == 0) ? S_OK : S_FALSE;
}

// Registration is performed by sapi_registration.py via .reg import, but we
// still export DllRegisterServer/DllUnregisterServer so regsvr32 works as a
// fallback during development.

static bool WriteRegSz(HKEY parent, const wchar_t* subkey, const wchar_t* name,
                       const wchar_t* value)
{
    HKEY hk;
    if (RegCreateKeyExW(parent, subkey, 0, nullptr, 0, KEY_WRITE, nullptr, &hk,
                        nullptr) != ERROR_SUCCESS) {
        return false;
    }
    LONG r = RegSetValueExW(hk, name, 0, REG_SZ, (const BYTE*)value,
                            (DWORD)((wcslen(value) + 1) * sizeof(wchar_t)));
    RegCloseKey(hk);
    return r == ERROR_SUCCESS;
}

STDAPI DllRegisterServer()
{
    wchar_t modulePath[MAX_PATH];
    if (!GetModuleFileNameW(g_hModule, modulePath, MAX_PATH)) return SELFREG_E_CLASS;

    const wchar_t* clsidKey = L"SOFTWARE\\Classes\\CLSID\\"
                              L"{A8B5D3E1-7C4F-4D89-9A2F-3B1C5D7E9F24}";
    const wchar_t* inprocKey = L"SOFTWARE\\Classes\\CLSID\\"
                               L"{A8B5D3E1-7C4F-4D89-9A2F-3B1C5D7E9F24}\\InprocServer32";

    if (!WriteRegSz(HKEY_LOCAL_MACHINE, clsidKey, nullptr, L"Titan TTS SAPI5 Voice"))
        return SELFREG_E_CLASS;
    if (!WriteRegSz(HKEY_LOCAL_MACHINE, inprocKey, nullptr, modulePath))
        return SELFREG_E_CLASS;
    if (!WriteRegSz(HKEY_LOCAL_MACHINE, inprocKey, L"ThreadingModel", L"Both"))
        return SELFREG_E_CLASS;
    return S_OK;
}

STDAPI DllUnregisterServer()
{
    RegDeleteTreeW(HKEY_LOCAL_MACHINE,
        L"SOFTWARE\\Classes\\CLSID\\{A8B5D3E1-7C4F-4D89-9A2F-3B1C5D7E9F24}");
    return S_OK;
}

BOOL WINAPI DllMain(HINSTANCE hInst, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH) {
        g_hModule = hInst;
        DisableThreadLibraryCalls(hInst);
    }
    return TRUE;
}
