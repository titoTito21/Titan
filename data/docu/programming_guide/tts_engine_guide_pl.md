# Przewodnik tworzenia silników TTS (TitanTTS)

## Wprowadzenie

**Silniki TitanTTS** to wtyczki dostarczające syntezę mowy dla TCE. Każdy silnik to katalog w `data/titantts engines/` zawierający plik konfiguracyjny `__engine__.TCE` i moduł Pythona `__engine__.py` z fabryką `get_engine()` zwracającą instancję dziedziczącą po `TitanTTSEngine`.

System silników jest zarządzany przez `EngineRegistry` (`src/tts/engine_registry.py`), który skanuje katalog silników przy starcie i udostępnia je modułowi `StereoSpeech`.

### Kategorie silników

- **`titantts`** — natywne silniki TitanTTS (wtyczki, ElevenLabs, Milena, BeSTspeech). Generują `pydub.AudioSegment` przekazywany do StereoSpeech, który stosuje panoramę i pitch.
- **`platform`** — silniki systemowe (eSpeak-NG, SAPI5, macOS Speech, Linux Speech Dispatcher). Implementowane wewnątrz `stereo_speech.py`, w rejestrze widoczne jako `PlatformEngineProxy`.

Wtyczka, którą napiszesz, to praktycznie zawsze silnik kategorii **`titantts`**.

## Struktura katalogu silnika

```
data/titantts engines/moj_silnik/
├── __engine__.TCE       # Konfiguracja (WYMAGANE, .TCE wielkimi literami)
├── __engine__.py        # Moduł silnika z get_engine() (WYMAGANE)
├── languages/           # Tłumaczenia własne (opcjonalne)
│   └── pl/LC_MESSAGES/engine.po/.mo
└── lib/                 # Biblioteki dołączone (opcjonalne)
```

## Plik `__engine__.TCE`

Format INI z sekcją `[engine]`:

```ini
[engine]
name = Mój silnik TTS
status = 0
libs = lib, vendor
```

| Pole | Wymagane | Opis |
|------|----------|------|
| name | nie | Nazwa wyświetlana (domyślnie nazwa folderu) |
| status | tak | **`0` = włączony, `1` = wyłączony** |
| libs | nie | Lista podkatalogów z bibliotekami (domyślnie `lib`) |

## Klasa bazowa `TitanTTSEngine`

Plik: `src/tts/base_engine.py`. Każdy silnik MUSI dziedziczyć po tej klasie.

### Atrybuty klasy

| Atrybut | Opis |
|---------|------|
| `engine_id` (str) | **Unikalny** identyfikator (np. `'elevenlabs'`, `'milena'`) — używany w ustawieniach |
| `engine_name` (str) | Nazwa wyświetlana (np. `'ElevenLabs TTS'`) |
| `engine_category` (str) | Zawsze `'titantts'` dla wtyczek |
| `needs_lock_release` (bool) | `True` jeśli `generate()` jest powolny (API/subprocess) — pozwala StereoSpeech zwolnić blokadę podczas syntezy |

### Metody abstrakcyjne (MUSISZ zaimplementować)

```python
def is_available(self) -> bool:
    """Czy silnik może działać na tej platformie?
    Sprawdź zależności (importy), klucz API, obecność plików, ..."""

def generate(self, text: str, pitch_offset: int = 0) -> AudioSegment | None:
    """Syntezuj tekst do pydub.AudioSegment lub None.
    pitch_offset: przesunięcie półtonów -10..+10 (zwykle stosowane przez set_frame_rate)."""

def get_voices(self) -> list[dict]:
    """Lista dostępnych głosów: [{'id': str, 'display_name': str}, ...]
    Pusta lista jeśli silnik ma jeden głos wbudowany."""

def set_voice(self, voice_id: str):
    """Ustaw aktywny głos po ID."""
```

### Metody opcjonalne (nadpisuj jeśli silnik to wspiera)

```python
def set_rate(self, rate: int):
    """Tempo mowy z zakresu TCE -10..+10 (0 = domyślne).
    Skonwertuj na natywny format silnika."""

def set_pitch(self, pitch: int):
    """Domyślny pitch z zakresu TCE -10..+10."""

def set_volume(self, volume: int):
    """Głośność 0..100."""

def stop(self):
    """Przerwij trwającą generację (np. zabij subprocess)."""

def clear_cache(self):
    """Wyczyść cache audio jeśli silnik go używa."""
```

### Metody konfiguracji (system pól dynamicznych)

```python
@classmethod
def get_config_fields(cls) -> list[dict]:
    """Pola konfiguracyjne wyświetlane w GUI ustawień TCE."""
    return [...]

def configure(self, key: str, value):
    """Zastosuj wartość pola konfiguracyjnego."""

def get_config(self, key: str, default=None):
    """Odczytaj aktualną wartość pola."""
```

## System pól konfiguracji

`get_config_fields()` zwraca listę dyktów opisujących pola wyświetlane dynamicznie w sekcji ustawień silnika. Każde pole ma:

| Klucz | Wymagany | Opis |
|-------|----------|------|
| `key` | tak | Klucz konfiguracyjny (zapisywany jako `engine.{id}.{key}` w `[stereo_speech]`) |
| `label` | tak | Etykieta wyświetlana w UI |
| `type` | tak | `'text'`, `'password'`, `'choice'`, `'slider'`, `'checkbox'` |
| `default` | tak | Wartość domyślna |
| `tooltip` | nie | Pomocniczy opis |
| `options` | tylko `choice` | Lista `(wartość, etykieta)` |
| `min` / `max` | tylko `slider` | Zakres |

### Przykłady pól

```python
# Pole tekstowe / hasło
{'key': 'api_key', 'label': 'Klucz API:', 'type': 'password', 'default': '',
 'tooltip': 'Klucz z elevenlabs.io'}

# Pole wyboru
{'key': 'model_id', 'label': 'Model:', 'type': 'choice', 'default': 'turbo_v2_5',
 'options': [('turbo_v2_5', 'Turbo v2.5 (najszybszy)'),
             ('multilingual_v2', 'Multilingual v2 (najwyższa jakość)')]}

# Suwak
{'key': 'speed', 'label': 'Prędkość:', 'type': 'slider', 'default': 50,
 'min': 0, 'max': 100}

# Checkbox
{'key': 'use_ssml', 'label': 'Użyj SSML', 'type': 'checkbox', 'default': False}
```

### Persystencja konfiguracji

TCE zapisuje wartości pól w pliku ustawień jako klucze `engine.{engine_id}.{key}` w sekcji `[stereo_speech]`. Programowo:

```python
from src.titan_core import tce_speech

tce_speech.set_engine_config('moj_silnik', 'api_key', 'sekretna_wartosc')
api_key = tce_speech.get_engine_config('moj_silnik', 'api_key')
```

`StereoSpeech` wywołuje `engine.configure(key, value)` przy ładowaniu ustawień i przy każdej zmianie wartości w GUI.

## Punkt wejścia `get_engine()`

`__engine__.py` MUSI definiować funkcję modułu `get_engine()` (lub atrybut wskazujący na tę funkcję), która zwraca instancję `TitanTTSEngine`. Zwykle używa się singletona, żeby cache i połączenia HTTP były współdzielone:

```python
import threading

_instance = None
_instance_lock = threading.Lock()


def _get_engine():
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = MojSilnikEngine()
    return _instance


# Punkt wejścia rejestru
get_engine = _get_engine
```

## Wstrzykiwanie tłumaczeń

Jeśli silnik ma katalog `languages/`, `EngineRegistry` automatycznie wstrzyknie funkcję `_()` do modułu **przed wykonaniem `exec_module`**:

```python
# W __engine__.py — _ jest dostępne jako globalna funkcja modułu:
print(_("Hello"))   # tłumaczone
```

Domena gettext to `engine`. Pliki `.po` muszą znaleźć się w `languages/<lang>/LC_MESSAGES/engine.mo`.

## Pełny przykład — silnik z cachem dyskowym

```python
"""
__engine__.py — Mój silnik TTS
"""
import os
import sys
import hashlib
import threading

try:
    from src.tts.base_engine import TitanTTSEngine
except ImportError:
    # Fallback dla testów standalone — minimalna deklaracja
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
    print("[MojSilnik] 'pydub' nie jest zainstalowany — pip install pydub")


def _get_cache_dir():
    """Wieloplatformowy katalog cache."""
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
    elif sys.platform == 'darwin':
        base = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
    else:
        base = os.environ.get('XDG_CACHE_HOME') or os.path.join(
            os.path.expanduser('~'), '.cache')
    cache_dir = os.path.join(base, 'Titosoft', 'Titan', 'tts_cache', 'moj_silnik')
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _cache_key(text, voice_id):
    """Klucz cache MD5 z (tekst, voice_id)."""
    return hashlib.md5(f"{text}\x00{voice_id}".encode('utf-8')).hexdigest()


class MojSilnikEngine(TitanTTSEngine):
    engine_id = 'moj_silnik'
    engine_name = 'Mój Silnik TTS'
    engine_category = 'titantts'
    needs_lock_release = True   # generate() wywołuje API/subprocess

    def __init__(self):
        self._api_key = ''
        self._voice_id = 'default'
        self._lock = threading.Lock()

    # --- Konfiguracja ---

    @classmethod
    def get_config_fields(cls):
        return [
            {'key': 'api_key', 'label': 'Klucz API:', 'type': 'password',
             'default': '', 'tooltip': 'Pobierz na example.com/api'},
            {'key': 'voice', 'label': 'Głos:', 'type': 'choice',
             'default': 'default',
             'options': [('default', 'Domyślny'), ('male', 'Męski'),
                         ('female', 'Żeński')]},
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

    # --- Wymagane metody ---

    def is_available(self):
        return PYDUB_AVAILABLE and bool(self._api_key)

    def get_voices(self):
        return [
            {'id': 'default', 'display_name': 'Domyślny'},
            {'id': 'male', 'display_name': 'Męski'},
            {'id': 'female', 'display_name': 'Żeński'},
        ]

    def set_voice(self, voice_id):
        self._voice_id = voice_id

    def generate(self, text, pitch_offset=0):
        if not self.is_available():
            return None
        text = text.strip()
        if not text:
            return None

        # 1. Sprawdź cache
        key = _cache_key(text, self._voice_id)
        cache_path = os.path.join(_get_cache_dir(), key + '.wav')
        if os.path.exists(cache_path):
            audio = AudioSegment.from_wav(cache_path)
        else:
            # 2. Wygeneruj audio (API, subprocess, biblioteka, ...)
            audio = self._call_synthesizer(text)
            if audio is None:
                return None
            # 3. Zapisz do cache jako WAV
            try:
                audio.export(cache_path, format='wav')
            except Exception as e:
                print(f"[MojSilnik] Cache save error: {e}")

        # 4. Zastosuj pitch (sztuczka frame-rate, bez ponownego cachowania)
        if pitch_offset != 0:
            audio = self._apply_pitch(audio, pitch_offset)

        return audio

    # --- Pomocnicze ---

    def _call_synthesizer(self, text):
        """TODO: tu wywołaj prawdziwy synthesizer (API, subprocess, biblioteka)."""
        # Przykład: cisza 1 s jako placeholder
        return AudioSegment.silent(duration=1000, frame_rate=22050)

    def _apply_pitch(self, audio, pitch_offset):
        """Zmień pitch przez manipulację frame-rate (sztuczka magnetofonowa)."""
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
            print(f"[MojSilnik] Pitch error: {e}")
            return audio

    def clear_cache(self):
        try:
            cache_dir = _get_cache_dir()
            for fname in os.listdir(cache_dir):
                if fname.endswith('.wav'):
                    os.remove(os.path.join(cache_dir, fname))
        except Exception as e:
            print(f"[MojSilnik] Clear cache error: {e}")


# --- Singleton + entry point ---

_instance = None
_instance_lock = threading.Lock()


def _get_engine():
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = MojSilnikEngine()
    return _instance


get_engine = _get_engine
```

## Standardy audio TCE

Wszystkie silniki TCE oczekują, że `generate()` zwróci `AudioSegment` znormalizowany do:

- **22 050 Hz**, **stereo (2 kanały)** — `audio.set_frame_rate(22050).set_channels(2)`

Jeśli twój silnik produkuje audio w innym formacie, zrób konwersję na końcu `generate()`. Pomoże StereoSpeech bezproblemowo nakładać panoramę i mikser.

## Mapowanie tempa (`set_rate`)

TCE używa standardowego zakresu **-10..+10** (0 = domyślne). Każdy silnik konwertuje na natywny format:

| Silnik | Mapowanie |
|--------|-----------|
| Milena (`milena4w.exe`) | -10 → 1.0, 0 → 0.75, +10 → 0.5 (mnożnik czasu trwania, niższy = szybszy) |
| eSpeak-NG | 80..450 słów/min (wyższe = szybsze) |
| ElevenLabs | mnożnik prędkości lub post-procesing audio |

Implementacja przykładowa (Milena):

```python
def set_rate(self, rate):
    rate = max(-10, min(10, float(rate)))
    self._rate = round(0.75 - (rate * 0.025), 3)
    self._rate = max(0.5, min(1.0, self._rate))
```

## Mapowanie pitch

`pitch_offset` w `generate(text, pitch_offset=0)` to półton z zakresu **-10..+10**. Najprostsza implementacja to sztuczka frame-rate (zmienia tempo i pitch jednocześnie, jak na taśmie magnetofonowej):

```python
factor = 2.0 ** (pitch_offset / 12.0)
new_rate = int(audio.frame_rate * factor)
shifted = audio._spawn(audio.raw_data, overrides={'frame_rate': new_rate})
return shifted.set_frame_rate(audio.frame_rate)
```

Dla głosów chmurowych zalecane jest ograniczenie do **-4..+4** półtonów — większe wartości dają robotyczne artefakty.

## Strategia cachowania

Dla silników wywołujących API lub powolny subprocess, cache dyskowy jest **kluczowy** (TCE odczytuje powtarzające się komunikaty — fokus listy, błędy, ...).

**Rekomendowany schemat:**

1. Klucz cache = MD5 z `(tekst, voice_id, model_id, format_audio)`.
2. Pliki WAV w katalogu wieloplatformowym:
   - Windows: `%APPDATA%/Titosoft/Titan/tts_cache/<engine_id>/`
   - macOS: `~/Library/Application Support/Titosoft/Titan/tts_cache/<engine_id>/`
   - Linux: `$XDG_CACHE_HOME/Titosoft/Titan/tts_cache/<engine_id>/` (lub `~/.cache/...`)
3. **Pitch NIE jest składnikiem klucza** — stosuj go po załadowaniu z cache.
4. Zaimplementuj `clear_cache()` żeby użytkownik mógł wyczyścić z poziomu ustawień.

## Wieloplatformowość

- `pydub` wymaga FFmpeg na każdej platformie. Zaznacz to w opisie silnika.
- Subprocess: użyj `subprocess.Popen` z `creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)` na Windowsie żeby nie wyskakiwało okno konsoli.
- Pliki binarne (DLL, .exe, dane słowników) trzymaj w podkatalogu silnika i znajdź je przez `os.path.dirname(os.path.abspath(__file__))`.
- Sprawdzaj `sys.platform` w `is_available()` — jeśli silnik jest tylko na Windowsie, zwracaj `False` na innych systemach.

## Pakowanie jako `.TCD` (opcjonalnie)

Zamiast katalogu, silnik TTS można rozpowszechniać jako pojedynczy plik
`.tcd` — z całą zawartością, łącznie z ewentualnymi natywnymi mostkami
DLL/EXE. W pełni opcjonalne i dodatkowe.

```bash
python src/scripts/pack_addon.py "data/titantts engines/moj_silnik" --kind tts_engine -o moj_silnik.tcd
```

- `.tcd` to własny skompresowany kontener (nagłówek magiczny + strumień
  LZMA), celowo nie jest to prawdziwy zip/7z — 7-Zip i Eksplorator Windows
  odmawiają otwarcia go jako archiwum.
- Nie są potrzebne zmiany w kodzie: zawartość jest identyczna bajt-w-bajt z
  katalogiem, więc `__engine__.py`/`__engine__.TCE` i ewentualny natywny
  mostek (DLL, bridge .exe) nadal działają tak samo po rozpakowaniu, bo
  wpis do `sys.path` dla katalogów `libs=` jest liczony na podstawie
  rozpakowanej ścieżki.
- Plik `.tcd` wystarczy umieścić w `data/titantts engines/` (wbudowanym
  lub w nakładce użytkownika) — zostanie wykryty dokładnie tak samo jak
  silnik oparty na katalogu.

Zobacz `src/titan_core/titan_package.py` po implementację formatu.

## Testowanie silnika

1. Skopiuj katalog do `data/titantts engines/`.
2. Uruchom TCE — w konsoli powinno pojawić się:
   `[EngineRegistry] Loaded engine: NAZWA (engine_id) from folder/`
3. Otwórz Ustawienia TCE → Mowa stereo (Stereo Speech) → wybierz swój silnik.
4. Pola konfiguracji powinny pojawić się dynamicznie pod listą silników.
5. Wpisz wartości pól (np. klucz API), naciśnij Zapisz.
6. Wybierz głos z listy (jeśli silnik ma `get_voices()`).
7. Naciśnij Test — powinieneś usłyszeć próbkę.
8. Sprawdź `engine_registry_debug.log` w katalogu głównym jeśli silnik się nie ładuje.

## Najczęstsze błędy

- **`engine_id` koliduje z istniejącym** — drugie wystąpienie jest pomijane. Wybierz unikalne ID.
- **Brak `get_engine` jako atrybutu modułu** — `EngineRegistry` szuka dokładnie `get_engine`, nie `get_my_engine`.
- **Klasa nie dziedziczy po `TitanTTSEngine`** — fallback z `try/except ImportError` jest WYMAGANY jeśli silnik ma działać też standalone.
- **`is_available()` zwraca `True` przy braku zależności** — TCE pokaże silnik na liście, ale `generate()` rzuci wyjątek.
- **Format audio inny niż 22050 Hz stereo** — StereoSpeech zacznie chrupać przy łączeniu z innymi dźwiękami.
- **Brak `needs_lock_release = True`** dla wolnego silnika — blokuje cały StereoSpeech podczas API call.
- **Cache klucz zawiera pitch** — niepotrzebne mnożenie plików, każda wartość pitch ma osobny WAV.

## Najważniejsze wskazówki

1. **Unikalny `engine_id`** — sprawdź `data/titantts engines/*/` zanim wybierzesz nazwę.
2. **`status = 0` w `__engine__.TCE`** — inaczej silnik będzie wyłączony.
3. **Singleton w `get_engine()`** — cache, sesje HTTP, subprocesy współdzielone.
4. **Cache dyskowy** dla silników z opóźnieniem (API, subprocess).
5. **Normalizacja audio** do 22050 Hz stereo na końcu `generate()`.
6. **`clear_cache()` zaimplementowane** — użytkownik musi mieć jak posprzątać.
7. **Try/except przy imporcie zależności** — silnik nie powinien wywalić TCE.
8. **Przykłady wbudowane**: `data/titantts engines/elevenlabs/`, `milena/`, `bestspeech/`.
