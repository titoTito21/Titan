"""
SAPI Pipe Server for Titan TTS
==============================
Named-pipe server that the native SAPI voice DLL (data/lib/titantts{32,64}.dll)
connects to when SAPI asks it to speak. Runs in a background daemon thread
inside the TCE Launcher process.

Wire protocol (little-endian, matches native/sapi_voice/titantts.cpp):
    client -> server (v1):
        uint32   version   (1)
        int32    rate      (SAPI site rate, -10..+10)
        uint32   volume    (SAPI site volume, 0..100)
        uint32   text_len  (UTF-8 byte length)
        bytes    text      (UTF-8)
    client -> server (v2):
        uint32   version   (2)
        int32    rate      (SAPI site rate, -10..+10)
        int32    pitch     (SAPI fragment pitch, -10..+10, 0 = default)
        uint32   volume    (SAPI site volume, 0..100)
        uint32   text_len  (UTF-8 byte length)
        bytes    text      (UTF-8)
    server -> client:
        uint32   status    (0 = OK, nonzero = error)
        uint32   pcm_len   (bytes)
        bytes    pcm       (22050 Hz / 16-bit / mono PCM LE)

Rate and pitch are applied via the engine's native controls (set_rate / generate
pitch_offset) so that rate changes only speed and pitch changes only tone —
never tempo (which would shift both).  The server itself uses engine defaults;
the SAPI client (screen reader / application) controls rate, pitch, and volume.

Supported engines:
    - All TitanTTS engines (BestSpeech, Milena, ElevenLabs, plugins)
    - eSpeak NG (via bundled libespeak-ng.dll / synthesize_to_memory)
    - NOT sapi5/say/spd — these would cause infinite recursion or are
      unavailable; they fall back to the best available TitanTTS engine.
"""

import os
import sys
import struct
import threading
import traceback

PIPE_NAME = r'\\.\pipe\TitanTTS'
_TARGET_SAMPLE_RATE = 22050
_TARGET_CHANNELS = 1
_TARGET_SAMPLE_WIDTH = 2

_server_thread = None
_server_stop = threading.Event()


def _log(msg):
    try:
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
        log_dir = os.path.join(base, 'Titosoft', 'Titan')
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, 'sapi_pipe_server.log'), 'a', encoding='utf-8') as f:
            f.write(f'{msg}\n')
    except Exception:
        pass


# ---------------------------------------------------------------------------
# eSpeak adapter — wraps the ESpeakDLL from stereo_speech for audio generation
# ---------------------------------------------------------------------------

class _EspeakAdapter:
    """Adapter that makes the ESpeakDLL usable as a TitanTTS-like engine.
    Has the same generate/set_voice/set_rate/set_volume/configure interface
    so _EngineBridge can treat it uniformly with titantts engines."""

    engine_id = 'espeak'

    def __init__(self, espeak_dll):
        self._dll = espeak_dll

    def is_available(self):
        return self._dll is not None and self._dll.is_available()

    def generate(self, text, pitch_offset=0):
        return self._dll.synthesize_to_memory(text, pitch_offset)

    def set_voice(self, voice_id):
        if voice_id:
            self._dll.set_voice(voice_id)

    def set_rate(self, rate):
        self._dll.set_rate(rate)

    def set_volume(self, volume):
        self._dll.set_volume(volume)

    def configure(self, key, value):
        pass


# ---------------------------------------------------------------------------
# SAPI5 adapter — wraps a dedicated _SAPIWorker for audio generation
# ---------------------------------------------------------------------------

class _Sapi5Adapter:
    """Adapter that uses a dedicated _SAPIWorker to generate SAPI5 speech.
    Creates its own worker thread with proper COM apartment so the pipe
    server can use any installed SAPI5 voice (including 32-bit voices via
    the VBScript bridge).

    Safety: refuses to use the TitanTTS voice to prevent infinite recursion
    (pipe server -> SAPI5 -> TitanTTS DLL -> pipe server -> ...).

    When _SAPIWorker fails to generate audio (e.g. 32-bit voice on 64-bit
    Python where set_voice throws a COM exception silently on the worker
    thread), the adapter falls back to its own persistent VBScript subprocess
    that runs under the opposite-bitness cscript.exe.  This handles the case
    where _SAPIWorker's internal bridge isn't triggered because set_voice
    only catches the exception without switching to subprocess mode.
    """

    engine_id = 'sapi5'
    _TITAN_TOKEN_MARKER = 'TitanTTS'

    # Persistent VBScript for fallback WAV generation via cscript.exe.
    # Handles VOICE, RATE, VOLUME, GENFILE, QUIT commands over stdin/stdout.
    _VBS_FALLBACK = r'''On Error Resume Next
Set voice = CreateObject("SAPI.SpVoice")
If Err.Number <> 0 Then
    WScript.StdOut.WriteLine "INIT_FAIL"
    WScript.Quit 1
End If
Err.Clear
WScript.StdOut.WriteLine "READY"
Do While Not WScript.StdIn.AtEndOfStream
    line = WScript.StdIn.ReadLine
    If Len(line) = 0 Then
        ' skip empty lines
    Else
        tabPos = InStr(line, vbTab)
        If tabPos > 0 Then
            cmd = Left(line, tabPos - 1)
            arg = Mid(line, tabPos + 1)
        Else
            cmd = line
            arg = ""
        End If
        Select Case cmd
            Case "VOICE"
                Err.Clear
                found = False
                ' Support both token ID (HKEY_...) and display name
                If Left(arg, 5) = "HKEY_" Then
                    Set token = CreateObject("SAPI.SpObjectToken")
                    token.SetId arg
                    If Err.Number = 0 Then
                        Set voice.Voice = token
                        If Err.Number = 0 Then found = True
                    End If
                End If
                If Not found Then
                    ' Search by display name (strip " (32-bit)" suffix)
                    Err.Clear
                    searchName = arg
                    If Right(searchName, 8) = "(32-bit)" Then
                        searchName = RTrim(Left(searchName, Len(searchName) - 8))
                    End If
                    Set tokens = voice.GetVoices()
                    For i = 0 To tokens.Count - 1
                        If tokens.Item(i).GetDescription() = searchName Then
                            Err.Clear
                            Set voice.Voice = tokens.Item(i)
                            If Err.Number = 0 Then found = True
                            Exit For
                        End If
                    Next
                End If
                If found Then
                    WScript.StdOut.WriteLine "VOICE_OK"
                Else
                    WScript.StdOut.WriteLine "VOICE_ERR"
                End If
                Err.Clear
            Case "RATE"
                voice.Rate = CInt(arg)
            Case "VOLUME"
                voice.Volume = CInt(arg)
            Case "GENFILE"
                parts = Split(arg, vbTab)
                gText = parts(0)
                gPath = parts(1)
                gPitch = 0
                If UBound(parts) >= 2 Then
                    If parts(2) <> "" And parts(2) <> "0" Then gPitch = CInt(parts(2))
                End If
                If gPitch <> 0 Then
                    gText = "<pitch absmiddle=""" & gPitch & """>" & gText & "</pitch>"
                End If
                Err.Clear
                Set stream = CreateObject("SAPI.SpFileStream")
                stream.Format.Type = 22
                stream.Open gPath, 3
                Set voice.AudioOutputStream = stream
                voice.Speak gText, 0
                stream.Close
                Set voice.AudioOutputStream = Nothing
                If Err.Number <> 0 Then
                    WScript.StdOut.WriteLine "GENFILE_ERR"
                    Err.Clear
                Else
                    WScript.StdOut.WriteLine "GENFILE_DONE"
                End If
            Case "QUIT"
                Exit Do
        End Select
    End If
Loop
'''

    def __init__(self):
        self._worker = None
        self._available = None
        self._create_attempts = 0
        self._max_create_attempts = 3
        # VBScript fallback state
        self._vbs_process = None
        self._vbs_cscript = None
        self._vbs_path = None
        self._use_vbs_fallback = False
        self._vbs_voice_set = None   # voice_id that VBS confirmed VOICE_OK
        # Track current settings for VBScript fallback
        self._voice_id = None
        self._rate = 0
        self._volume = 100

    def _resolve_voice_to_token_id(self, voice_name):
        """Resolve a SAPI voice display name to a token ID.

        Settings store the display name (e.g. 'ScanSoft Agata_Full_22kHz (32-bit)')
        but _SAPIWorker.set_voice needs a registry token ID for SetId().
        Uses the _SAPIWorker's sync mechanism to enumerate voices on
        the COM-initialized worker thread.
        """
        if not voice_name or voice_name.startswith('HKEY_'):
            return voice_name
        # Strip " (32-bit)" suffix added by StereoSpeech.get_available_voices
        clean = voice_name
        if clean.endswith(' (32-bit)'):
            clean = clean[:-9].rstrip()
        # Use worker's sync to enumerate voices on COM thread
        if self._worker:
            event = threading.Event()
            result = {}
            def _find(sapi):
                try:
                    tokens = sapi.GetVoices()
                    for i in range(tokens.Count):
                        t = tokens.Item(i)
                        if t.GetDescription() == clean:
                            return t.Id
                except Exception:
                    pass
                return None
            self._worker._cmd_queue.put(('sync', _find, event, result))
            if event.wait(5.0):
                token_id = result.get('value')
                if token_id:
                    _log(f'[Sapi5Adapter] resolved "{voice_name}" -> {token_id}')
                    return token_id
        _log(f'[Sapi5Adapter] could not resolve voice name: {voice_name}')
        return voice_name

    def _ensure_worker(self):
        if self._worker is not None:
            # Check if worker is still alive
            if self._worker.available:
                return
            # Worker died — reset for retry
            _log('[Sapi5Adapter] worker became unavailable, resetting')
            self._worker = None
            self._available = None

        if self._create_attempts >= self._max_create_attempts:
            return

        self._create_attempts += 1
        try:
            from src.titan_core.stereo_speech import _SAPIWorker
            self._worker = _SAPIWorker()
            if not self._worker.available:
                self._worker = None
                self._available = False
                _log(f'[Sapi5Adapter] _SAPIWorker not available '
                     f'(attempt {self._create_attempts}/{self._max_create_attempts})')
            else:
                self._available = True
                self._create_attempts = 0  # Reset on success
                _log('[Sapi5Adapter] _SAPIWorker ready')
        except Exception as e:
            _log(f'[Sapi5Adapter] worker creation failed '
                 f'(attempt {self._create_attempts}/{self._max_create_attempts}): {e}')
            self._worker = None
            self._available = False

    # ---- VBScript fallback for 32-bit voices ----

    def _find_vbs_cscript(self):
        """Find a working cscript.exe, preferring opposite bitness."""
        import struct as _struct
        import subprocess
        windir = os.environ.get('WINDIR', r'C:\Windows')
        python_bits = _struct.calcsize('P') * 8
        if python_bits == 64:
            candidates = [
                os.path.join(windir, 'SysWOW64', 'cscript.exe'),
                os.path.join(windir, 'System32', 'cscript.exe'),
            ]
        else:
            candidates = [
                os.path.join(windir, 'Sysnative', 'cscript.exe'),
                os.path.join(windir, 'System32', 'cscript.exe'),
            ]
        vbs_test = os.path.join(
            os.environ.get('TEMP', os.path.expanduser('~')),
            'tce_sapi_pipe_test.vbs')
        try:
            with open(vbs_test, 'w', encoding='ascii', errors='replace') as f:
                f.write('On Error Resume Next\n'
                        'Set v = CreateObject("SAPI.SpVoice")\n'
                        'If Err.Number = 0 Then WScript.Echo "OK"\n')
        except Exception as e:
            _log(f'[Sapi5Adapter] failed to write test VBS: {e}')
            return None
        for cscript in candidates:
            if not os.path.exists(cscript):
                continue
            try:
                result = subprocess.run(
                    [cscript, '//nologo', '//T:10', vbs_test],
                    capture_output=True, timeout=15,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if 'OK' in result.stdout.decode('utf-8', errors='replace'):
                    _log(f'[Sapi5Adapter] VBS fallback cscript: {cscript}')
                    try:
                        os.remove(vbs_test)
                    except Exception:
                        pass
                    return cscript
            except Exception as e:
                _log(f'[Sapi5Adapter] cscript test error ({cscript}): {e}')
        try:
            os.remove(vbs_test)
        except Exception:
            pass
        return None

    def _ensure_vbs_fallback(self):
        """Start the persistent VBScript fallback subprocess if not running."""
        if self._vbs_process is not None:
            if self._vbs_process.poll() is None:
                return True
            # Process died — clean up
            self._vbs_process = None

        if self._vbs_cscript is None:
            self._vbs_cscript = self._find_vbs_cscript()
            if self._vbs_cscript is None:
                _log('[Sapi5Adapter] no working cscript found for VBS fallback')
                return False

        import subprocess
        import locale
        encoding = locale.getpreferredencoding() or 'cp1250'
        vbs_path = os.path.join(
            os.environ.get('TEMP', os.path.expanduser('~')),
            'tce_sapi_pipe_bridge.vbs')
        try:
            with open(vbs_path, 'w', encoding=encoding, errors='replace') as f:
                f.write(self._VBS_FALLBACK)
        except Exception as e:
            _log(f'[Sapi5Adapter] failed to write VBS fallback: {e}')
            return False
        self._vbs_path = vbs_path

        try:
            self._vbs_process = subprocess.Popen(
                [self._vbs_cscript, '//nologo', vbs_path],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            ready = self._vbs_process.stdout.readline()
            if b'READY' in ready:
                _log('[Sapi5Adapter] VBS fallback subprocess ready')
                # Apply current voice/rate/volume
                if self._voice_id:
                    self._vbs_send(f'VOICE\t{self._voice_id}')
                    self._vbs_read()
                if self._rate != 0:
                    self._vbs_send(f'RATE\t{self._rate}')
                if self._volume != 100:
                    self._vbs_send(f'VOLUME\t{self._volume}')
                return True
            else:
                _log(f'[Sapi5Adapter] VBS fallback init failed: {ready}')
                self._vbs_stop()
                return False
        except Exception as e:
            _log(f'[Sapi5Adapter] VBS fallback start error: {e}')
            return False

    def _vbs_send(self, cmd):
        proc = self._vbs_process
        if not proc or proc.poll() is not None:
            return
        try:
            import locale
            encoding = locale.getpreferredencoding() or 'cp1250'
            proc.stdin.write((cmd + '\n').encode(encoding, errors='replace'))
            proc.stdin.flush()
        except Exception as e:
            _log(f'[Sapi5Adapter] VBS send error: {e}')

    def _vbs_read(self):
        """Read one response line from VBS subprocess.

        Uses direct blocking readline — no thread-with-timeout pattern,
        which would leave orphaned reader threads that consume future
        responses and cause desync.  VBS responds synchronously and
        quickly (SAPI SetId/Speak are fast), so blocking is safe here.
        """
        proc = self._vbs_process
        if not proc or proc.poll() is not None:
            return None
        try:
            import locale
            encoding = locale.getpreferredencoding() or 'cp1250'
            line = proc.stdout.readline()
            if not line:
                return None
            return line.decode(encoding, errors='replace').strip()
        except Exception as e:
            _log(f'[Sapi5Adapter] VBS read error: {e}')
            return None

    def _vbs_stop(self):
        proc = self._vbs_process
        if proc and proc.poll() is None:
            try:
                proc.stdin.write(b'QUIT\n')
                proc.stdin.flush()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        self._vbs_process = None

    def _generate_vbs(self, text, temp_path, pitch_offset):
        """Generate WAV via VBScript fallback subprocess."""
        if not self._ensure_vbs_fallback():
            return None
        text_clean = text.replace('\t', ' ').replace('\n', ' ').replace('\r', '')
        self._vbs_send(f'GENFILE\t{text_clean}\t{temp_path}\t{pitch_offset}')
        resp = self._vbs_read()
        if resp == 'GENFILE_DONE' and os.path.exists(temp_path) and os.path.getsize(temp_path) > 100:
            return temp_path
        _log(f'[Sapi5Adapter] VBS fallback generate response: {resp}')
        return None

    # ---- public interface ----

    def is_available(self):
        if self._available is None:
            self._ensure_worker()
        return self._available is True or self._use_vbs_fallback

    def _is_voice_titan_tts(self, voice_id):
        """Check if a voice token ID belongs to TitanTTS (recursion danger)."""
        return self._TITAN_TOKEN_MARKER in (voice_id or '')

    def generate(self, text, pitch_offset=0):
        import tempfile
        temp_fd, temp_path = tempfile.mkstemp(suffix='.wav', prefix='titantts_sapi_')
        os.close(temp_fd)
        try:
            if self._use_vbs_fallback:
                # VBS mode — generate via persistent cscript subprocess
                result_path = self._generate_vbs(text, temp_path, pitch_offset)
            else:
                # Worker mode — generate via _SAPIWorker COM
                self._ensure_worker()
                result_path = None
                if self._worker:
                    result_path = self._worker.generate_to_file(
                        text, temp_path, pitch_offset, timeout=15.0)
            if not result_path:
                _log('[Sapi5Adapter] generate returned None')
                return None
            from pydub import AudioSegment
            audio = AudioSegment.from_wav(result_path)
            return audio
        except Exception as e:
            _log(f'[Sapi5Adapter] generate error: {e}\n{traceback.format_exc()}')
            if self._worker and not self._worker.available:
                self._worker = None
                self._available = None
            return None
        finally:
            try:
                os.unlink(temp_path)
            except Exception:
                pass

    def set_voice(self, voice_id):
        if self._is_voice_titan_tts(voice_id):
            _log('[Sapi5Adapter] blocked TitanTTS voice to prevent recursion')
            return

        # Already tested this exact voice — skip re-testing on every request
        # (_apply_engine_config calls set_voice on every synthesize() call).
        if voice_id == self._voice_id:
            return
        self._voice_id = voice_id
        self._vbs_voice_set = None

        # Proactively test voice via VBS (opposite-bitness cscript).
        # If VBS can set it (VOICE_OK), this is a 32-bit voice that the
        # 64-bit _SAPIWorker can't handle — switch to VBS mode.
        if self._ensure_vbs_fallback():
            self._vbs_send(f'VOICE\t{voice_id}')
            resp = self._vbs_read()
            _log(f'[Sapi5Adapter] VBS VOICE test: {resp} for {voice_id}')
            if resp == 'VOICE_OK':
                self._vbs_voice_set = voice_id
                self._use_vbs_fallback = True
                self._available = True
                _log('[Sapi5Adapter] switched to VBS mode for 32-bit voice')
                return

        # VBS couldn't set the voice (64-bit voice or VBS unavailable).
        # Use the _SAPIWorker (direct COM).
        # Resolve display name → token ID (worker needs token ID for SetId).
        self._use_vbs_fallback = False
        resolved = self._resolve_voice_to_token_id(voice_id)
        self._ensure_worker()
        if self._worker:
            try:
                self._worker.set_voice(resolved)
            except Exception as e:
                _log(f'[Sapi5Adapter] set_voice error: {e}')

    def set_rate(self, rate):
        self._rate = int(rate)
        if self._use_vbs_fallback and self._vbs_process:
            self._vbs_send(f'RATE\t{self._rate}')
        if self._worker:
            try:
                self._worker.set_rate(self._rate)
            except Exception:
                pass

    def set_volume(self, volume):
        self._volume = int(volume)
        if self._use_vbs_fallback and self._vbs_process:
            self._vbs_send(f'VOLUME\t{self._volume}')
        if self._worker:
            try:
                self._worker.set_volume(self._volume)
            except Exception:
                pass

    def configure(self, key, value):
        pass


# ---------------------------------------------------------------------------
# Engine bridge — runs the currently configured Titan TTS engine
# ---------------------------------------------------------------------------

# Engines that cannot generate audio at all (proxies only)
_PROXY_ONLY_ENGINES = frozenset(('say', 'spd'))

class _EngineBridge:
    def __init__(self):
        self._lock = threading.Lock()
        self._engine = None
        self._engine_id = None
        self._espeak_adapter = None
        self._sapi5_adapter = None

    def _get_configured_engine_id(self):
        try:
            from src.settings.settings import get_setting
            return get_setting('engine', 'sapi5', section='stereo_speech')
        except Exception:
            return None

    def _get_espeak_adapter(self):
        """Get or create the eSpeak adapter (lazy, cached)."""
        if self._espeak_adapter is not None:
            return self._espeak_adapter
        try:
            from src.titan_core.stereo_speech import get_espeak_dll
            dll = get_espeak_dll()
            if dll and dll.is_available():
                self._espeak_adapter = _EspeakAdapter(dll)
                _log('[Bridge] eSpeak adapter created')
                return self._espeak_adapter
        except Exception as e:
            _log(f'[Bridge] eSpeak adapter failed: {e}')
        return None

    def _get_sapi5_adapter(self):
        """Get or create the SAPI5 adapter (lazy, cached)."""
        if self._sapi5_adapter is not None:
            return self._sapi5_adapter
        try:
            adapter = _Sapi5Adapter()
            if adapter.is_available():
                self._sapi5_adapter = adapter
                _log('[Bridge] SAPI5 adapter created')
                return self._sapi5_adapter
        except Exception as e:
            _log(f'[Bridge] SAPI5 adapter failed: {e}')
        return None

    def _get_fallback_engine(self, registry):
        """Get the first available TitanTTS engine as fallback."""
        titantts = [e for e in registry.get_all_engines()
                    if getattr(e, 'engine_category', '') == 'titantts'
                    and e.is_available()]
        if titantts:
            return titantts[0]
        # Last resort: try eSpeak
        return self._get_espeak_adapter()

    def _ensure_engine(self):
        try:
            from src.tts.engine_registry import get_engine_registry
            registry = get_engine_registry()
        except Exception as e:
            _log(f'[Bridge] registry import failed: {e}')
            self._engine = None
            return

        engine_id = self._get_configured_engine_id()
        if engine_id == self._engine_id and self._engine is not None:
            return

        engine = None

        if engine_id in ('espeak', 'espeak_dll'):
            # eSpeak — use the DLL adapter (no recursion, generates audio)
            engine = self._get_espeak_adapter()
            if engine is None:
                _log('[Bridge] eSpeak not available, falling back to titantts')
                engine = self._get_fallback_engine(registry)
        elif engine_id == 'sapi5':
            # SAPI5 — use dedicated worker (voice must NOT be TitanTTS)
            engine = self._get_sapi5_adapter()
            if engine is None:
                _log('[Bridge] SAPI5 not available, falling back')
                engine = self._get_fallback_engine(registry)
        elif engine_id in _PROXY_ONLY_ENGINES:
            # say/spd — can't generate audio, use fallback
            _log(f'[Bridge] {engine_id} has no generate(), using fallback')
            engine = self._get_fallback_engine(registry)
        else:
            # TitanTTS engines: milena, bestspeech, elevenlabs, plugins
            engine = registry.get_titantts_engine(engine_id) if engine_id else None
            if engine is None or not engine.is_available():
                _log(f'[Bridge] engine {engine_id!r} not found/available, trying fallback')
                engine = self._get_fallback_engine(registry)

        self._engine = engine
        self._engine_id = engine_id
        actual = getattr(self._engine, 'engine_id', None) if self._engine else None
        _log(f'[Bridge] configured={engine_id}, actual={actual}')

    def _load_settings(self):
        """Load the [stereo_speech] section from settings file."""
        try:
            from src.settings.settings import load_settings
            all_settings = load_settings() or {}
            return all_settings.get('stereo_speech', {}) or {}
        except Exception:
            return {}

    def _apply_engine_config(self, engine):
        """Apply engine-specific config keys and voice from TCE settings.

        Does NOT apply rate, volume, or pitch — the SAPI pipe server uses
        engine defaults for those.  The SAPI client (screen reader / app)
        controls rate, pitch, and volume through the wire protocol, and
        those are applied per-call via engine.set_rate() and generate(pitch).
        """
        stereo_section = self._load_settings()
        eid = getattr(engine, 'engine_id', '') or ''

        # 1. Apply engine-specific config keys (engine.{id}.{key})
        prefix = f'engine.{eid}.'
        for key, value in stereo_section.items():
            if key.startswith(prefix) and hasattr(engine, 'configure'):
                cfg_key = key[len(prefix):]
                try:
                    engine.configure(cfg_key, value)
                except Exception:
                    pass

        # 2. Apply voice — this is the voice selected for the current engine
        voice_id = stereo_section.get('voice', '')
        if voice_id:
            try:
                engine.set_voice(voice_id)
            except Exception:
                pass

    def synthesize(self, text, rate, pitch, volume):
        """Synthesize text to PCM bytes.

        Args:
            text: Text to speak.
            rate: SAPI site rate (-10..+10). Applied via engine.set_rate()
                  so only speed changes, not pitch.
            pitch: SAPI fragment pitch (-10..+10, 0=default). Applied via
                   engine.generate(pitch_offset) so only tone changes.
            volume: SAPI site volume (0..100). Applied as gain in post-processing.
        """
        with self._lock:
            self._ensure_engine()
            engine = self._engine
            if engine is None:
                _log('[Bridge] no engine available')
                return None
            if not engine.is_available():
                _log(f'[Bridge] engine {getattr(engine, "engine_id", "?")} no longer available')
                self._engine = None
                self._engine_id = None
                return None

            # Reapply config on every call — user may change engine settings
            # or voice in the Settings dialog while we're running.
            self._apply_engine_config(engine)

            # Apply SAPI site rate via the engine's native rate control.
            # This changes speech speed WITHOUT changing pitch — unlike
            # audio resampling which would change both (tempo).
            try:
                engine.set_rate(rate)
            except Exception as e:
                _log(f'[Bridge] set_rate({rate}) error: {e}')

            # Generate with pitch offset — changes tone WITHOUT changing speed.
            try:
                audio = engine.generate(text, pitch)
            except Exception as e:
                _log(f'[Bridge] generate() error: {e}\n{traceback.format_exc()}')
                return None
            if audio is None:
                _log('[Bridge] generate() returned None')
                return None

            # Only volume is applied as post-processing (simple gain).
            return _audio_to_pcm(audio, volume)


def _audio_to_pcm(audio, volume):
    """Convert a pydub AudioSegment to 22050/16/mono PCM with site volume.

    Rate and pitch are NOT applied here — they are handled natively by the
    engine (set_rate for speed, generate pitch_offset for tone) so that
    speed and pitch change independently.  Only volume (simple gain) is
    applied as post-processing.
    """
    try:
        if audio.frame_rate != _TARGET_SAMPLE_RATE:
            audio = audio.set_frame_rate(_TARGET_SAMPLE_RATE)
        if audio.channels != _TARGET_CHANNELS:
            audio = audio.set_channels(_TARGET_CHANNELS)
        if audio.sample_width != _TARGET_SAMPLE_WIDTH:
            audio = audio.set_sample_width(_TARGET_SAMPLE_WIDTH)

        if volume != 100:
            try:
                if volume <= 0:
                    audio = audio - 120
                else:
                    import math
                    db = 20.0 * math.log10(max(volume, 1) / 100.0)
                    audio = audio.apply_gain(db)
            except Exception as e:
                _log(f'[Bridge] volume apply error: {e}')

        return audio.raw_data
    except Exception as e:
        _log(f'[Bridge] audio conversion error: {e}')
        return None


# ---------------------------------------------------------------------------
# Win32 named pipe plumbing (ctypes)
# ---------------------------------------------------------------------------

def _run_pipe_server_win32(bridge):
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32

    PIPE_ACCESS_DUPLEX = 0x00000003
    PIPE_TYPE_BYTE = 0x00000000
    PIPE_READMODE_BYTE = 0x00000000
    PIPE_WAIT = 0x00000000
    PIPE_UNLIMITED_INSTANCES = 255
    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
    ERROR_PIPE_CONNECTED = 535

    # Default security (NULL lpSecurityAttributes). The pipe is created with
    # the default DACL from the process token, which allows same-user SAPI
    # clients (screen readers, etc.) to connect. This covers NVDA/JAWS/
    # Narrator running under the same user as the launcher.
    CreateNamedPipeW = kernel32.CreateNamedPipeW
    CreateNamedPipeW.restype = wintypes.HANDLE
    CreateNamedPipeW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    ]

    ConnectNamedPipe = kernel32.ConnectNamedPipe
    ConnectNamedPipe.restype = wintypes.BOOL
    ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p]

    DisconnectNamedPipe = kernel32.DisconnectNamedPipe
    FlushFileBuffers = kernel32.FlushFileBuffers
    CloseHandle = kernel32.CloseHandle

    ReadFile = kernel32.ReadFile
    ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                         ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    ReadFile.restype = wintypes.BOOL

    WriteFile = kernel32.WriteFile
    WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                          ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    WriteFile.restype = wintypes.BOOL

    def _read_all(h, n):
        buf = (ctypes.c_ubyte * n)()
        got = 0
        while got < n:
            read = wintypes.DWORD(0)
            if not ReadFile(h, ctypes.byref(buf, got), n - got, ctypes.byref(read), None):
                return None
            if read.value == 0:
                return None
            got += read.value
        return bytes(buf)

    def _write_all(h, data):
        n = len(data)
        buf = (ctypes.c_ubyte * n).from_buffer_copy(data)
        written = 0
        while written < n:
            w = wintypes.DWORD(0)
            if not WriteFile(h, ctypes.byref(buf, written), n - written,
                             ctypes.byref(w), None):
                return False
            if w.value == 0:
                return False
            written += w.value
        return True

    def _handle_client(h):
        try:
            # Read version first (4 bytes)
            ver_bytes = _read_all(h, 4)
            if ver_bytes is None:
                return
            version = struct.unpack('<I', ver_bytes)[0]

            if version == 1:
                # v1: rate(4) + volume(4) + text_len(4) = 12 bytes
                rest = _read_all(h, 12)
                if rest is None:
                    return
                rate, volume, text_len = struct.unpack('<iII', rest)
                pitch = 0
            elif version == 2:
                # v2: rate(4) + pitch(4) + volume(4) + text_len(4) = 16 bytes
                rest = _read_all(h, 16)
                if rest is None:
                    return
                rate, pitch, volume, text_len = struct.unpack('<iiII', rest)
            else:
                _log(f'[Pipe] bad protocol version {version}')
                _write_all(h, struct.pack('<II', 1, 0))
                return

            if text_len > 10 * 1024 * 1024:
                _log(f'[Pipe] absurd text_len {text_len}')
                _write_all(h, struct.pack('<II', 2, 0))
                return
            text_bytes = _read_all(h, text_len) if text_len else b''
            if text_bytes is None:
                return
            try:
                text = text_bytes.decode('utf-8', errors='replace')
            except Exception:
                text = ''

            _log(f'[Pipe] v{version} rate={rate} pitch={pitch} vol={volume} text={text[:80]!r}')

            pcm = bridge.synthesize(text, rate, pitch, volume) or b''
            _write_all(h, struct.pack('<II', 0, len(pcm)))
            if pcm:
                _write_all(h, pcm)
        except Exception as e:
            _log(f'[Pipe] client handler error: {e}\n{traceback.format_exc()}')

    _log('[Pipe] server thread starting')
    while not _server_stop.is_set():
        h = CreateNamedPipeW(
            PIPE_NAME,
            PIPE_ACCESS_DUPLEX,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
            PIPE_UNLIMITED_INSTANCES,
            65536, 65536, 0,
            None,
        )
        if not h or h == INVALID_HANDLE_VALUE:
            err = kernel32.GetLastError()
            _log(f'[Pipe] CreateNamedPipeW failed: {err}')
            _server_stop.wait(1.0)
            continue

        connected = ConnectNamedPipe(h, None)
        if not connected:
            err = kernel32.GetLastError()
            if err != ERROR_PIPE_CONNECTED:
                CloseHandle(h)
                if _server_stop.is_set():
                    break
                continue

        try:
            _handle_client(h)
            FlushFileBuffers(h)
        finally:
            DisconnectNamedPipe(h)
            CloseHandle(h)

    _log('[Pipe] server thread exiting')


# ---------------------------------------------------------------------------
# Public start/stop
# ---------------------------------------------------------------------------

def start():
    """Start the named pipe server in a background daemon thread (idempotent)."""
    global _server_thread
    if sys.platform != 'win32':
        return False
    if _server_thread is not None and _server_thread.is_alive():
        return True
    _server_stop.clear()
    bridge = _EngineBridge()
    _server_thread = threading.Thread(
        target=_run_pipe_server_win32, args=(bridge,),
        name='TitanTTSPipeServer', daemon=True,
    )
    _server_thread.start()
    _log('[Pipe] start() -> thread launched')
    return True


def stop():
    """Signal the server thread to stop. Does not block for long."""
    _server_stop.set()
