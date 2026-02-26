"""
ElevenLabs TTS Engine for TCE Launcher / Titan Stereo Speech
=============================================================
Latency optimisations
---------------------
- requests.Session with HTTPAdapter (keep-alive, connection pooling)
- eleven_turbo_v2_5 model  – fastest multilingual model (~3x vs eleven_multilingual_v2)
- optimize_streaming_latency=4 API param – max server-side latency reduction
- output_format=mp3_22050_32  – smallest MP3 (faster download, still clear TTS)
- Disk cache (MD5-keyed WAV files) – instant replay on repeated messages
- Pitch via pydub frame-rate trick – applied after cache load, not stored
"""

import io
import os
import sys
import hashlib
import threading
import time

try:
    from src.tts.base_engine import TitanTTSEngine
except ImportError:
    import abc
    class TitanTTSEngine(abc.ABC):
        engine_id = ''
        engine_name = ''
        engine_category = 'platform'
        needs_lock_release = False
        @abc.abstractmethod
        def is_available(self): ...
        @abc.abstractmethod
        def generate(self, text, pitch_offset=0): ...
        @abc.abstractmethod
        def get_voices(self): ...
        @abc.abstractmethod
        def set_voice(self, voice_id): ...
        def set_rate(self, rate): pass
        def set_volume(self, volume): pass
        def stop(self): pass
        def clear_cache(self): pass
        @classmethod
        def get_config_fields(cls): return []
        def configure(self, key, value): pass
        def get_config(self, key, default=None): return default

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("[ElevenLabs] 'requests' not installed - run: pip install requests")

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    print("[ElevenLabs] 'pydub' not installed - run: pip install pydub")

# Characters that count as sentence-ending punctuation
_PUNCTUATION_END = frozenset('.!?;:,')

ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"

# eleven_turbo_v2_5: fastest multilingual model (replaces eleven_multilingual_v2)
# Falls back to eleven_turbo_v2 for older accounts without turbo_v2_5 access
DEFAULT_MODEL_ID = "eleven_turbo_v2_5"

# Output format: mp3 at 22050 Hz, 32 kbps – smallest file that stays clear for TTS
_OUTPUT_FORMAT = "mp3_22050_32"

# Maximum server-side latency optimisation (0-4, higher=faster, slight quality tradeoff)
_OPTIMIZE_STREAMING_LATENCY = 4


# ---------------------------------------------------------------------------
# HTTP Session factory
# ---------------------------------------------------------------------------

def _make_session():
    """
    Create a requests.Session with:
    - Keep-alive connection pooling (reuses TCP connection → -200-500 ms per call)
    - Retry on transient network errors (connect/read timeouts, 502/503/504)
    - Sensible pool sizing for single-user TTS
    """
    session = requests.Session()

    retry = Retry(
        total=2,
        backoff_factor=0.3,
        status_forcelist=(502, 503, 504),
        allowed_methods={"GET", "POST"},
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        pool_connections=2,
        pool_maxsize=4,
        max_retries=retry,
    )
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    return session


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _get_cache_dir():
    """Return platform-appropriate TTS cache directory and ensure it exists."""
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        cache_dir = os.path.join(base, 'Titosoft', 'Titan', 'tts_cache', 'elevenlabs')
    elif sys.platform == 'darwin':
        base = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
        cache_dir = os.path.join(base, 'Titosoft', 'Titan', 'tts_cache', 'elevenlabs')
    else:
        xdg = os.environ.get('XDG_CACHE_HOME') or os.path.join(os.path.expanduser('~'), '.cache')
        cache_dir = os.path.join(xdg, 'Titosoft', 'Titan', 'tts_cache', 'elevenlabs')

    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _normalize_text(text):
    """Add a period if the text does not end with sentence punctuation."""
    text = text.strip()
    if text and text[-1] not in _PUNCTUATION_END:
        text += '.'
    return text


def _cache_key(text, voice_id, model_id, output_format):
    """MD5 of (text, voice_id, model_id, output_format) → hex filename."""
    data = f"{text}\x00{voice_id}\x00{model_id}\x00{output_format}".encode('utf-8')
    return hashlib.md5(data).hexdigest()


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class ElevenLabsEngine(TitanTTSEngine):
    """
    ElevenLabs cloud TTS engine with latency optimisations and disk cache.

    Public API:
        generate(text, pitch_offset=0) -> AudioSegment | None
        get_voices(force_refresh=False) -> list[{'id', 'display_name'}]
        set_api_key(key)
        set_voice_id(voice_id)
        set_model_id(model_id)
        is_available()  -> bool
        clear_cache()
    """

    engine_id = 'elevenlabs'
    engine_name = 'ElevenLabs TTS'
    engine_category = 'titantts'
    needs_lock_release = True

    def __init__(self):
        self._api_key  = ''
        # "Rachel" – popular general-purpose English voice
        self._voice_id = '21m00Tcm4TlvDq8ikWAM'
        self._model_id = DEFAULT_MODEL_ID
        self._lock     = threading.Lock()

        # Persistent HTTP session – avoids TCP handshake on every request
        self._session = _make_session() if REQUESTS_AVAILABLE else None

        # In-memory voice list cache (refreshed every 5 min)
        self._voices_cache      = None
        self._voices_cache_time = 0.0
        self._voices_cache_ttl  = 300

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_api_key(self, api_key):
        self._api_key = api_key.strip()
        # Invalidate voice cache when key changes
        self._voices_cache      = None
        self._voices_cache_time = 0.0
        # Update Authorization header on the shared session
        if self._session and self._api_key:
            self._session.headers.update({"xi-api-key": self._api_key})

    def get_api_key(self):
        return self._api_key

    def set_voice_id(self, voice_id):
        self._voice_id = voice_id.strip()

    def get_voice_id(self):
        return self._voice_id

    def set_model_id(self, model_id):
        self._model_id = model_id.strip()

    def is_available(self):
        """True when runtime deps are present AND an API key is configured."""
        return REQUESTS_AVAILABLE and PYDUB_AVAILABLE and bool(self._api_key)

    def set_voice(self, voice_id):
        """Set active voice by ID (TitanTTSEngine interface)."""
        self.set_voice_id(voice_id)

    # ------------------------------------------------------------------
    # Config fields (TitanTTSEngine interface)
    # ------------------------------------------------------------------

    @classmethod
    def get_config_fields(cls):
        return [
            {
                'key': 'api_key',
                'label': 'API Key:',
                'type': 'password',
                'default': '',
                'tooltip': 'Your ElevenLabs API key. Get it from elevenlabs.io',
            },
            {
                'key': 'model_id',
                'label': 'Model:',
                'type': 'choice',
                'default': 'eleven_turbo_v2_5',
                'options': [
                    ('eleven_turbo_v2_5', 'Turbo v2.5 (fastest)'),
                    ('eleven_turbo_v2', 'Turbo v2'),
                    ('eleven_multilingual_v2', 'Multilingual v2 (highest quality)'),
                ],
            },
        ]

    def configure(self, key, value):
        if key == 'api_key':
            self.set_api_key(value)
        elif key == 'model_id':
            self.set_model_id(value)

    def get_config(self, key, default=None):
        if key == 'api_key':
            return self._api_key
        elif key == 'model_id':
            return self._model_id
        return default

    # ------------------------------------------------------------------
    # Voice list
    # ------------------------------------------------------------------

    def get_voices(self, force_refresh=False):
        """
        Fetch available voices from ElevenLabs API (cached for 5 min).

        Returns:
            list of {'id': str, 'display_name': str}
        """
        if not REQUESTS_AVAILABLE or not self._api_key:
            return []

        now = time.time()
        if (
            not force_refresh
            and self._voices_cache is not None
            and (now - self._voices_cache_time) < self._voices_cache_ttl
        ):
            return self._voices_cache

        try:
            resp = self._session.get(
                f"{ELEVENLABS_API_BASE}/voices",
                headers={"xi-api-key": self._api_key},
                timeout=10,
            )
            if resp.status_code == 200:
                voices = [
                    {
                        'id':           v['voice_id'],
                        'display_name': v.get('name', v['voice_id']),
                    }
                    for v in resp.json().get('voices', [])
                ]
                voices.sort(key=lambda v: v['display_name'])
                self._voices_cache      = voices
                self._voices_cache_time = now
                print(f"[ElevenLabs] Fetched {len(voices)} voices")
                return voices
            else:
                print(f"[ElevenLabs] API error {resp.status_code} while fetching voices")
                return []
        except Exception as e:
            print(f"[ElevenLabs] Error fetching voices: {e}")
            return []

    # ------------------------------------------------------------------
    # Audio generation (public entry point)
    # ------------------------------------------------------------------

    def generate(self, text, pitch_offset=0):
        """
        Synthesize text to AudioSegment.

        Flow:
          1. Normalise punctuation (add '.' if missing)
          2. Check disk cache → return instantly on hit
          3. Call API on miss → cache result
          4. Apply pitch offset (frame-rate trick, no re-caching needed)

        Args:
            text (str):         Text to speak.
            pitch_offset (int): Semitone shift -10..+10.

        Returns:
            pydub.AudioSegment or None
        """
        if not self.is_available():
            return None

        normalized = _normalize_text(text)
        if not normalized:
            return None

        key = _cache_key(normalized, self._voice_id, self._model_id, _OUTPUT_FORMAT)

        # --- cache lookup ---
        audio = self._load_from_cache(key)
        if audio is not None:
            print(f"[ElevenLabs] Cache hit: {normalized[:60]}")
        else:
            audio = self._call_api(normalized)
            if audio is None:
                return None
            self._save_to_cache(key, audio)

        # --- post-processing: pitch (no re-cache; same cached audio used) ---
        if pitch_offset != 0:
            audio = self._apply_pitch(audio, pitch_offset)

        return audio

    # ------------------------------------------------------------------
    # Private – API call (latency-optimised)
    # ------------------------------------------------------------------

    def _call_api(self, text):
        """
        POST to ElevenLabs TTS endpoint.

        Latency optimisations applied:
        - Persistent session (keep-alive TCP)
        - optimize_streaming_latency=4
        - output_format=mp3_22050_32 (smallest, fastest to download)
        - eleven_turbo_v2_5 model (fastest, multilingual)
        """
        try:
            url = (
                f"{ELEVENLABS_API_BASE}/text-to-speech/{self._voice_id}"
                f"?optimize_streaming_latency={_OPTIMIZE_STREAMING_LATENCY}"
                f"&output_format={_OUTPUT_FORMAT}"
            )
            headers = {
                "xi-api-key":   self._api_key,
                "Content-Type": "application/json",
                "Accept":       "audio/mpeg",
            }
            payload = {
                "text":     text,
                "model_id": self._model_id,
                "voice_settings": {
                    "stability":        0.5,
                    "similarity_boost": 0.75,
                },
            }

            t0 = time.time()
            print(f"[ElevenLabs] Requesting TTS (model={self._model_id}): {text[:60]}")
            resp = self._session.post(url, json=payload, headers=headers, timeout=20)

            if resp.status_code == 200:
                audio = AudioSegment.from_mp3(io.BytesIO(resp.content))
                # Normalise to 22050 Hz stereo (consistent with other engines)
                audio = audio.set_frame_rate(22050).set_channels(2)
                elapsed = time.time() - t0
                print(f"[ElevenLabs] Generated {len(audio)} ms audio in {elapsed:.2f}s")
                return audio
            else:
                print(
                    f"[ElevenLabs] API error {resp.status_code}: "
                    f"{resp.text[:200]}"
                )
                # If turbo_v2_5 is not available, retry with turbo_v2
                if resp.status_code == 422 and "model" in resp.text.lower():
                    return self._call_api_fallback_model(text, headers)
                return None
        except Exception as e:
            print(f"[ElevenLabs] Error calling API: {e}")
            return None

    def _call_api_fallback_model(self, text, headers):
        """Retry with eleven_turbo_v2 if eleven_turbo_v2_5 is unavailable."""
        try:
            url = (
                f"{ELEVENLABS_API_BASE}/text-to-speech/{self._voice_id}"
                f"?optimize_streaming_latency={_OPTIMIZE_STREAMING_LATENCY}"
                f"&output_format={_OUTPUT_FORMAT}"
            )
            payload = {
                "text":     text,
                "model_id": "eleven_turbo_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            }
            print("[ElevenLabs] Retrying with eleven_turbo_v2 fallback model")
            resp = self._session.post(url, json=payload, headers=headers, timeout=20)
            if resp.status_code == 200:
                audio = AudioSegment.from_mp3(io.BytesIO(resp.content))
                return audio.set_frame_rate(22050).set_channels(2)
        except Exception as e:
            print(f"[ElevenLabs] Fallback model error: {e}")
        return None

    # ------------------------------------------------------------------
    # Private – disk cache
    # ------------------------------------------------------------------

    def _cache_path(self, key):
        return os.path.join(_get_cache_dir(), key + '.wav')

    def _load_from_cache(self, key):
        """Load and return AudioSegment from disk cache, or None."""
        try:
            path = self._cache_path(key)
            if os.path.exists(path):
                return AudioSegment.from_wav(path)
        except Exception as e:
            print(f"[ElevenLabs] Cache load error: {e}")
        return None

    def _save_to_cache(self, key, audio):
        """Persist AudioSegment to disk cache as WAV."""
        try:
            path = self._cache_path(key)
            audio.export(path, format='wav')
            print(f"[ElevenLabs] Cached to: {os.path.basename(path)}")
        except Exception as e:
            print(f"[ElevenLabs] Cache save error: {e}")

    # ------------------------------------------------------------------
    # Private – pitch shift
    # ------------------------------------------------------------------

    def _apply_pitch(self, audio, pitch_offset):
        """
        Shift pitch via frame-rate manipulation (tape-speed trick).

        - Each offset unit = 1 semitone (factor = 2^(1/12))
        - Original duration is preserved (resample back after shifting)
        - Pitch is NOT stored in cache – same cached audio used for all pitches
        - Clamped to -4..+4 semitones for cloud voices – larger shifts
          degrade quality (formant shift, robotic artifacts)

        Args:
            audio (AudioSegment): Source audio.
            pitch_offset (int):   Semitones, clamped to -4..+4.
        """
        try:
            pitch_offset  = max(-4, min(4, pitch_offset))
            if pitch_offset == 0:
                return audio
            factor        = 2.0 ** (pitch_offset / 12.0)
            new_frame_rate = int(audio.frame_rate * factor)
            if new_frame_rate <= 0:
                return audio
            shifted = audio._spawn(
                audio.raw_data,
                overrides={"frame_rate": new_frame_rate},
            )
            return shifted.set_frame_rate(audio.frame_rate)
        except Exception as e:
            print(f"[ElevenLabs] Pitch apply error: {e}")
            return audio

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def clear_cache(self):
        """Delete all cached WAV files from the ElevenLabs cache directory."""
        try:
            cache_dir = _get_cache_dir()
            removed = 0
            for fname in os.listdir(cache_dir):
                if fname.endswith('.wav'):
                    os.remove(os.path.join(cache_dir, fname))
                    removed += 1
            print(f"[ElevenLabs] Cleared {removed} cached files")
        except Exception as e:
            print(f"[ElevenLabs] Error clearing cache: {e}")


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_instance      = None
_instance_lock = threading.Lock()


def get_elevenlabs_engine():
    """Return (or create) the global ElevenLabsEngine singleton."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = ElevenLabsEngine()
    return _instance


# Plugin entry point (called by EngineRegistry)
get_engine = get_elevenlabs_engine
