# TitanTTS Engine Creation Guide

## Introduction

**TitanTTS engines** are plugins that provide text-to-speech synthesis for TCE. Each engine is a directory under `data/titantts engines/` containing the config file `__engine__.TCE` and a Python module `__engine__.py` with a `get_engine()` factory returning an instance that subclasses `TitanTTSEngine`.

Engines are managed by `EngineRegistry` (`src/tts/engine_registry.py`), which scans the engines directory at startup and exposes them to the `StereoSpeech` module.

### Engine categories

- **`titantts`** — native TitanTTS engines (plugins, ElevenLabs, Milena, BeSTspeech). They produce a `pydub.AudioSegment` that StereoSpeech then pans and pitch-shifts.
- **`platform`** — system engines (eSpeak-NG, SAPI5, macOS Speech, Linux Speech Dispatcher). Implemented inside `stereo_speech.py`, exposed in the registry via `PlatformEngineProxy`.

The plugin you write will almost always be of category **`titantts`**.

## Engine directory structure

```
data/titantts engines/my_engine/
├── __engine__.TCE       # Configuration (REQUIRED, .TCE in uppercase)
├── __engine__.py        # Engine module with get_engine() (REQUIRED)
├── languages/           # Engine-local translations (optional)
│   └── pl/LC_MESSAGES/engine.po/.mo
└── lib/                 # Bundled libraries (optional)
```

## `__engine__.TCE` file

INI format with one `[engine]` section:

```ini
[engine]
name = My TTS Engine
status = 0
libs = lib, vendor
```

| Field | Required | Description |
|-------|----------|-------------|
| name | no | Display name (defaults to folder name) |
| status | yes | **`0` = enabled, `1` = disabled** |
| libs | no | Comma-separated bundled library subdirs (default: `lib`) |

## Base class `TitanTTSEngine`

File: `src/tts/base_engine.py`. Every engine MUST subclass this class.

### Class attributes

| Attribute | Description |
|-----------|-------------|
| `engine_id` (str) | **Unique** identifier (e.g. `'elevenlabs'`, `'milena'`) — used in settings storage |
| `engine_name` (str) | Display name (e.g. `'ElevenLabs TTS'`) |
| `engine_category` (str) | Always `'titantts'` for plugins |
| `needs_lock_release` (bool) | `True` if `generate()` is slow (API/subprocess) — lets StereoSpeech release its lock during synthesis |

### Abstract methods (you MUST implement)

```python
def is_available(self) -> bool:
    """Can this engine produce speech on this platform?
    Check dependencies (imports), API key, file presence, ..."""

def generate(self, text: str, pitch_offset: int = 0) -> AudioSegment | None:
    """Synthesize text to pydub.AudioSegment or None.
    pitch_offset: semitone shift -10..+10 (typically applied via set_frame_rate)."""

def get_voices(self) -> list[dict]:
    """List of available voices: [{'id': str, 'display_name': str}, ...]
    Empty list if the engine has a single built-in voice."""

def set_voice(self, voice_id: str):
    """Set active voice by ID."""
```

### Optional methods (override if your engine supports it)

```python
def set_rate(self, rate: int):
    """Speech rate in TCE standard range -10..+10 (0 = default).
    Convert to your engine's native format."""

def set_pitch(self, pitch: int):
    """Default pitch in TCE range -10..+10."""

def set_volume(self, volume: int):
    """Volume 0..100."""

def stop(self):
    """Abort in-progress generation (e.g. kill subprocess)."""

def clear_cache(self):
    """Wipe audio cache if the engine uses one."""
```

### Configuration methods (dynamic field system)

```python
@classmethod
def get_config_fields(cls) -> list[dict]:
    """Config fields shown in TCE settings UI."""
    return [...]

def configure(self, key: str, value):
    """Apply a config field value."""

def get_config(self, key: str, default=None):
    """Read a config field's current value."""
```

## Configuration field system

`get_config_fields()` returns a list of dicts that describe the controls dynamically rendered in the TCE settings UI under your engine. Each field has:

| Key | Required | Description |
|-----|----------|-------------|
| `key` | yes | Config key (stored as `engine.{id}.{key}` in `[stereo_speech]`) |
| `label` | yes | Label shown in the UI |
| `type` | yes | `'text'`, `'password'`, `'choice'`, `'slider'`, `'checkbox'` |
| `default` | yes | Default value |
| `tooltip` | no | Hint text |
| `options` | only `choice` | List of `(value, display)` tuples |
| `min` / `max` | only `slider` | Range |

### Field examples

```python
# Text / password field
{'key': 'api_key', 'label': 'API Key:', 'type': 'password', 'default': '',
 'tooltip': 'Get your key from elevenlabs.io'}

# Choice field
{'key': 'model_id', 'label': 'Model:', 'type': 'choice', 'default': 'turbo_v2_5',
 'options': [('turbo_v2_5', 'Turbo v2.5 (fastest)'),
             ('multilingual_v2', 'Multilingual v2 (highest quality)')]}

# Slider
{'key': 'speed', 'label': 'Speed:', 'type': 'slider', 'default': 50,
 'min': 0, 'max': 100}

# Checkbox
{'key': 'use_ssml', 'label': 'Use SSML', 'type': 'checkbox', 'default': False}
```

### Persistence

TCE stores field values in the settings file as `engine.{engine_id}.{key}` under the `[stereo_speech]` section. Programmatically:

```python
from src.titan_core import tce_speech

tce_speech.set_engine_config('my_engine', 'api_key', 'secret_value')
api_key = tce_speech.get_engine_config('my_engine', 'api_key')
```

`StereoSpeech` calls `engine.configure(key, value)` when settings are loaded and whenever a value changes in the UI.

## Entry point `get_engine()`

`__engine__.py` MUST define a module-level function `get_engine` (or assign that name to your factory) that returns a `TitanTTSEngine` instance. A singleton pattern is typical so the cache and HTTP sessions are shared:

```python
import threading

_instance = None
_instance_lock = threading.Lock()


def _get_engine():
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = MyEngine()
    return _instance


# Registry entry point
get_engine = _get_engine
```

## Translation injection

If your engine has a `languages/` directory, `EngineRegistry` automatically injects a `_()` function into your module **before `exec_module()` runs**:

```python
# In __engine__.py — _ is available as a module-level function:
print(_("Hello"))   # translated
```

The gettext domain is `engine`. Place `.po` files at `languages/<lang>/LC_MESSAGES/engine.mo`.

## Full example — engine with disk cache

```python
"""
__engine__.py — My TTS Engine
"""
import os
import sys
import hashlib
import threading

try:
    from src.tts.base_engine import TitanTTSEngine
except ImportError:
    # Fallback for standalone testing — minimal stub
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
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    print("[MyEngine] 'pydub' not installed — pip install pydub")


def _get_cache_dir():
    """Cross-platform cache directory."""
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
    elif sys.platform == 'darwin':
        base = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
    else:
        base = os.environ.get('XDG_CACHE_HOME') or os.path.join(
            os.path.expanduser('~'), '.cache')
    cache_dir = os.path.join(base, 'Titosoft', 'Titan', 'tts_cache', 'my_engine')
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _cache_key(text, voice_id):
    """MD5 cache key from (text, voice_id)."""
    return hashlib.md5(f"{text}\x00{voice_id}".encode('utf-8')).hexdigest()


class MyEngine(TitanTTSEngine):
    engine_id = 'my_engine'
    engine_name = 'My TTS Engine'
    engine_category = 'titantts'
    needs_lock_release = True   # generate() calls API/subprocess

    def __init__(self):
        self._api_key = ''
        self._voice_id = 'default'
        self._lock = threading.Lock()

    # --- Configuration ---

    @classmethod
    def get_config_fields(cls):
        return [
            {'key': 'api_key', 'label': 'API Key:', 'type': 'password',
             'default': '', 'tooltip': 'Get yours at example.com/api'},
            {'key': 'voice', 'label': 'Voice:', 'type': 'choice',
             'default': 'default',
             'options': [('default', 'Default'), ('male', 'Male'),
                         ('female', 'Female')]},
        ]

    def configure(self, key, value):
        if key == 'api_key':
            self._api_key = str(value).strip()
        elif key == 'voice':
            self._voice_id = str(value)

    def get_config(self, key, default=None):
        if key == 'api_key':
            return self._api_key
        elif key == 'voice':
            return self._voice_id
        return default

    # --- Required methods ---

    def is_available(self):
        return PYDUB_AVAILABLE and bool(self._api_key)

    def get_voices(self):
        return [
            {'id': 'default', 'display_name': 'Default'},
            {'id': 'male', 'display_name': 'Male'},
            {'id': 'female', 'display_name': 'Female'},
        ]

    def set_voice(self, voice_id):
        self._voice_id = voice_id

    def generate(self, text, pitch_offset=0):
        if not self.is_available():
            return None
        text = text.strip()
        if not text:
            return None

        # 1. Check cache
        key = _cache_key(text, self._voice_id)
        cache_path = os.path.join(_get_cache_dir(), key + '.wav')
        if os.path.exists(cache_path):
            audio = AudioSegment.from_wav(cache_path)
        else:
            # 2. Synthesize (API call, subprocess, library, ...)
            audio = self._call_synthesizer(text)
            if audio is None:
                return None
            # 3. Persist as WAV
            try:
                audio.export(cache_path, format='wav')
            except Exception as e:
                print(f"[MyEngine] Cache save error: {e}")

        # 4. Apply pitch (frame-rate trick, no re-cache)
        if pitch_offset != 0:
            audio = self._apply_pitch(audio, pitch_offset)

        return audio

    # --- Helpers ---

    def _call_synthesizer(self, text):
        """TODO: call your real synthesizer here (API, subprocess, library)."""
        # Placeholder: 1 s of silence
        return AudioSegment.silent(duration=1000, frame_rate=22050)

    def _apply_pitch(self, audio, pitch_offset):
        """Shift pitch via frame-rate manipulation (tape-speed trick)."""
        try:
            pitch_offset = max(-4, min(4, pitch_offset))
            if pitch_offset == 0:
                return audio
            factor = 2.0 ** (pitch_offset / 12.0)
            new_rate = int(audio.frame_rate * factor)
            if new_rate <= 0:
                return audio
            shifted = audio._spawn(
                audio.raw_data, overrides={'frame_rate': new_rate})
            return shifted.set_frame_rate(audio.frame_rate)
        except Exception as e:
            print(f"[MyEngine] Pitch error: {e}")
            return audio

    def clear_cache(self):
        try:
            cache_dir = _get_cache_dir()
            for fname in os.listdir(cache_dir):
                if fname.endswith('.wav'):
                    os.remove(os.path.join(cache_dir, fname))
        except Exception as e:
            print(f"[MyEngine] Clear cache error: {e}")


# --- Singleton + entry point ---

_instance = None
_instance_lock = threading.Lock()


def _get_engine():
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = MyEngine()
    return _instance


get_engine = _get_engine
```

## TCE audio standards

Every TCE engine is expected to return an `AudioSegment` from `generate()` normalized to:

- **22 050 Hz**, **stereo (2 channels)** — `audio.set_frame_rate(22050).set_channels(2)`

If your engine produces audio in a different format, normalize it at the end of `generate()`. This lets StereoSpeech panning and mixing work cleanly with other sounds.

## Rate mapping (`set_rate`)

TCE uses a standard range of **-10..+10** (0 = default). Each engine converts to its native format:

| Engine | Mapping |
|--------|---------|
| Milena (`milena4w.exe`) | -10 → 1.0, 0 → 0.75, +10 → 0.5 (duration multiplier, lower = faster) |
| eSpeak-NG | 80..450 wpm (higher = faster) |
| ElevenLabs | speed multiplier or post-processing |

Sample implementation (Milena):

```python
def set_rate(self, rate):
    rate = max(-10, min(10, float(rate)))
    self._rate = round(0.75 - (rate * 0.025), 3)
    self._rate = max(0.5, min(1.0, self._rate))
```

## Pitch mapping

`pitch_offset` in `generate(text, pitch_offset=0)` is a semitone in the **-10..+10** range. The simplest implementation is the frame-rate trick (changes tempo and pitch together, like a tape recorder):

```python
factor = 2.0 ** (pitch_offset / 12.0)
new_rate = int(audio.frame_rate * factor)
shifted = audio._spawn(audio.raw_data, overrides={'frame_rate': new_rate})
return shifted.set_frame_rate(audio.frame_rate)
```

For cloud voices clamp to **-4..+4** semitones — larger shifts produce robotic artifacts.

## Caching strategy

For engines that call APIs or slow subprocesses, a disk cache is **essential** (TCE replays the same prompts often — list focus, errors, ...).

**Recommended scheme:**

1. Cache key = MD5 of `(text, voice_id, model_id, audio_format)`.
2. WAV files in a cross-platform directory:
   - Windows: `%APPDATA%/Titosoft/Titan/tts_cache/<engine_id>/`
   - macOS: `~/Library/Application Support/Titosoft/Titan/tts_cache/<engine_id>/`
   - Linux: `$XDG_CACHE_HOME/Titosoft/Titan/tts_cache/<engine_id>/` (or `~/.cache/...`)
3. **Pitch is NOT part of the key** — apply it after loading from cache.
4. Implement `clear_cache()` so the user can wipe storage from settings.

## Multiplatform

- `pydub` requires FFmpeg on every platform. Mention it in your engine description.
- Subprocess: use `subprocess.Popen` with `creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)` on Windows so a console window does not flash.
- Bundle binaries (DLLs, .exe, dictionary data) in a subdirectory of the engine and locate them via `os.path.dirname(os.path.abspath(__file__))`.
- Check `sys.platform` in `is_available()` — if your engine is Windows-only, return `False` elsewhere.

## Packaging as `.TCD` (Optional)

Instead of shipping a directory, a TTS engine can be distributed as a
single `.tcd` file — same content, including any bundled native
DLL/EXE bridge binaries. Purely optional and additive.

```bash
python src/scripts/pack_addon.py "data/titantts engines/my_engine" --kind tts_engine -o my_engine.tcd
```

- `.tcd` is a custom compressed container (magic header + LZMA payload),
  deliberately not a real zip/7z — 7-Zip and Windows Explorer refuse to
  open it as an archive.
- No code changes needed: the payload is byte-identical to the directory,
  so `__engine__.py`/`__engine__.TCE` and any bundled native bridge (DLL,
  bridge .exe) still work the same way once extracted, since `sys.path`
  insertion for `libs=` dirs is computed from the extracted path.
- Drop the `.tcd` into `data/titantts engines/` (bundled or per-user
  overlay) and it's discovered identically to a directory-based engine.

See `src/titan_core/titan_package.py` for the format implementation.

## Testing your engine

1. Drop the directory into `data/titantts engines/`.
2. Start TCE — the console should show:
   `[EngineRegistry] Loaded engine: NAME (engine_id) from folder/`
3. Open TCE Settings → Stereo Speech → pick your engine.
4. The configuration fields should appear dynamically below the engine list.
5. Fill in field values (e.g. API key) and Save.
6. Pick a voice from the list (if `get_voices()` returns options).
7. Hit Test — you should hear a sample.
8. Inspect `engine_registry_debug.log` in the project root if the engine fails to load.

## Common mistakes

- **`engine_id` collides with an existing one** — the second one is skipped. Pick a unique ID.
- **No `get_engine` module attribute** — the registry looks for the exact name `get_engine`, not `get_my_engine`.
- **Class doesn't subclass `TitanTTSEngine`** — the `try/except ImportError` fallback is REQUIRED if you also want the engine to work standalone.
- **`is_available()` returns `True` without dependencies** — TCE will list it, but `generate()` will throw.
- **Audio not 22050 Hz stereo** — StereoSpeech will glitch when mixing with other sounds.
- **Missing `needs_lock_release = True`** for a slow engine — blocks all of StereoSpeech during the API call.
- **Cache key includes pitch** — pointless duplication, every pitch value gets its own WAV.

## Key tips

1. **Unique `engine_id`** — check `data/titantts engines/*/` before picking a name.
2. **`status = 0` in `__engine__.TCE`** — otherwise the engine is disabled.
3. **Singleton in `get_engine()`** — share the cache, HTTP sessions, subprocesses.
4. **Disk cache** for slow engines (API, subprocess).
5. **Audio normalization** to 22050 Hz stereo at the end of `generate()`.
6. **`clear_cache()` implemented** — the user must have a way to clean up.
7. **Try/except dependency imports** — your engine should never crash TCE.
8. **Built-in examples**: `data/titantts engines/elevenlabs/`, `milena/`, `bestspeech/`.
