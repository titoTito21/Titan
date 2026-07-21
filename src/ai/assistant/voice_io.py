"""Voice input/output for the assistant, all over the internet (no offline
models).

- Microphone capture: :func:`record_until_silence` records from the default
  input device (``sounddevice``) and stops on a trailing silence.
- Speech-to-text: :func:`transcribe` sends the recorded audio to Gemini
  (multimodal) and returns the text -- transcription happens in the cloud.
- Text-to-speech: :func:`speak` synthesizes the reply with the persona's Gemini
  prebuilt voice and plays it. If Gemini TTS is unavailable it falls back to
  Titan TTS (``speak_stereo``), never SAPI.

Every function degrades gracefully: missing ``sounddevice`` / SDK / mic simply
raises a clear error the caller surfaces, and TTS always falls back to Titan TTS.
"""

import io
import struct
import threading
import time
import wave

# Capture format (mono 16-bit PCM; Gemini accepts wav happily).
_SR_IN = 16000
_TTS_SR = 24000  # Gemini TTS returns 24 kHz mono 16-bit PCM

_STT_MODEL = 'gemini-2.5-flash'
_TTS_MODEL = 'gemini-2.5-flash-preview-tts'


# --------------------------------------------------------------------------- #
# Gemini client (new google-genai SDK)
# --------------------------------------------------------------------------- #
def _genai():
    from google import genai
    from google.genai import types
    from src.ai import ai_provider
    key = ai_provider.get_ai_key('gemini')
    if not key:
        raise RuntimeError("No Gemini API key configured (Settings, AI features).")
    return genai.Client(api_key=key), types


# --------------------------------------------------------------------------- #
# Microphone capture
# --------------------------------------------------------------------------- #
def _pcm_to_wav(pcm_bytes, sample_rate):
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


def _rms(frame_bytes):
    if not frame_bytes:
        return 0.0
    count = len(frame_bytes) // 2
    if count == 0:
        return 0.0
    vals = struct.unpack('<' + 'h' * count, frame_bytes[:count * 2])
    return (sum(v * v for v in vals) / count) ** 0.5


def record_until_silence(max_seconds=20.0, silence_seconds=1.2,
                         start_timeout=6.0, cancel_event=None,
                         on_level=None):
    """Record from the default microphone until ~``silence_seconds`` of silence
    after speech began (or ``max_seconds`` / ``start_timeout`` elapses). Returns
    WAV bytes, or b'' if nothing was captured / cancelled. Raises RuntimeError if
    ``sounddevice`` or a microphone is unavailable."""
    try:
        import sounddevice as sd
        import numpy as np
    except Exception as e:
        raise RuntimeError(f"Microphone capture needs sounddevice/numpy: {e}")

    block = int(_SR_IN * 0.05)  # 50 ms blocks
    silence_thresh = 500.0      # RMS below this counts as silence
    frames = []
    started = False
    last_voice = time.time()
    t0 = time.time()

    try:
        with sd.InputStream(samplerate=_SR_IN, channels=1, dtype='int16',
                            blocksize=block) as stream:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    return b''
                data, _overflow = stream.read(block)
                pcm = data.tobytes()
                frames.append(pcm)
                level = _rms(pcm)
                if on_level:
                    try:
                        on_level(level)
                    except Exception:
                        pass
                now = time.time()
                if level >= silence_thresh:
                    started = True
                    last_voice = now
                if not started and (now - t0) > start_timeout:
                    return b''  # user never spoke
                if started and (now - last_voice) > silence_seconds:
                    break
                if (now - t0) > max_seconds:
                    break
    except Exception as e:
        raise RuntimeError(f"Could not record from the microphone: {e}")

    if not started:
        return b''
    return _pcm_to_wav(b''.join(frames), _SR_IN)


# --------------------------------------------------------------------------- #
# Speech-to-text (cloud)
# --------------------------------------------------------------------------- #
def transcribe(wav_bytes, language_hint='pl'):
    """Transcribe ``wav_bytes`` via Gemini. Returns the recognised text ('' if
    empty). Raises on SDK/network failure."""
    if not wav_bytes:
        return ''
    client, types = _genai()
    prompt = ("Transcribe this audio verbatim. Output ONLY the transcription "
              "text with no quotes and no commentary. The speaker's language "
              f"is likely '{language_hint}'.")
    resp = client.models.generate_content(
        model=_STT_MODEL,
        contents=[types.Part.from_bytes(data=wav_bytes, mime_type='audio/wav'),
                  prompt])
    return (getattr(resp, 'text', '') or '').strip()


# --------------------------------------------------------------------------- #
# Text-to-speech (cloud, STREAMING, with Titan TTS fallback)
# --------------------------------------------------------------------------- #
def _iter_chunk_pcm(chunk):
    """Yield PCM byte segments from one streamed Gemini TTS response chunk."""
    try:
        cands = getattr(chunk, 'candidates', None) or []
        for cand in cands:
            content = getattr(cand, 'content', None)
            for part in (getattr(content, 'parts', None) or []):
                inline = getattr(part, 'inline_data', None)
                data = getattr(inline, 'data', None) if inline else None
                if data:
                    yield data
    except Exception:
        return


def _speak_gemini_stream(text, voice_name, cancel_event=None):
    """Synthesize with Gemini TTS and play the audio as it streams in, so speech
    starts on the FIRST chunk instead of after the whole clip. Returns True once
    at least one audio chunk played; raises on setup/SDK failure before audio."""
    import sounddevice as sd
    import numpy as np
    client, types = _genai()

    stream = client.models.generate_content_stream(
        model=_TTS_MODEL,
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=['AUDIO'],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name)))))

    out = None
    played = False
    try:
        for chunk in stream:
            if cancel_event is not None and cancel_event.is_set():
                break
            for pcm in _iter_chunk_pcm(chunk):
                if out is None:
                    # Open the output device only once we have real audio, so a
                    # text-only/metadata first chunk doesn't hold the device.
                    out = sd.OutputStream(samplerate=_TTS_SR, channels=1,
                                          dtype='int16')
                    out.start()
                arr = np.frombuffer(pcm, dtype=np.int16)
                out.write(arr)  # blocks until the buffer drains -> paces playback
                played = True
                if cancel_event is not None and cancel_event.is_set():
                    break
    finally:
        if out is not None:
            try:
                out.stop()
                out.close()
            except Exception:
                pass
    if not played:
        raise RuntimeError("Gemini TTS returned no audio.")
    return True


def _titan_tts_fallback(text):
    from src.titan_core.stereo_speech import speak_stereo
    speak_stereo(text, async_mode=False)


def speak(text, persona=None, cancel_event=None):
    """Speak ``text`` aloud with the persona's Gemini voice, STREAMING the audio
    for low latency-to-first-sound. Falls back to Titan TTS. Never raises."""
    text = (text or '').strip()
    if not text:
        return
    voice = (persona or {}).get('gemini_voice') or 'Kore'
    try:
        _speak_gemini_stream(text, voice, cancel_event=cancel_event)
        return
    except Exception as e:
        print(f"[voice_io] Gemini TTS stream failed ({e}); falling back to Titan TTS.")
    try:
        _titan_tts_fallback(text)
    except Exception as e:
        print(f"[voice_io] Titan TTS fallback failed: {e}")


def stop_playback():
    try:
        import sounddevice as sd
        sd.stop()
    except Exception:
        pass
