"""
Voice Capture Manager with Voice Activity Detection
Handles microphone capture, VAD, and audio streaming for Titan-Net voice chat
"""

import sounddevice as sd
import numpy as np
import queue
import threading
import time
from typing import Optional, Callable

# VAD backend. webrtcvad is a C extension with no wheels for current Python
# versions, so src.network.vad_fallback provides an equivalent pure-Python
# detector. get_vad() returns whichever works, and never None - Voice
# Activation must not silently degrade into a permanently open microphone.
from src.network.vad_fallback import get_vad as _get_vad


class VoiceCaptureManager:
    """Manages microphone capture with Voice Activity Detection"""

    def __init__(self, sample_rate=16000, chunk_duration_ms=30, use_vad=False):
        """
        Initialize Voice Capture Manager

        Args:
            sample_rate: Audio sample rate in Hz (16000 recommended for webrtcvad)
            chunk_duration_ms: Duration of each audio chunk in milliseconds (10, 20, or 30)
            use_vad: Enable Voice Activity Detection (False = continuous transmission, no cutting)
        """
        self.sample_rate = sample_rate
        self.chunk_duration_ms = chunk_duration_ms
        self.chunk_size = int(sample_rate * chunk_duration_ms / 1000)
        self._use_vad = use_vad

        # VAD setup (aggressiveness 0-3, 0=least aggressive, most tolerant)
        self.vad = None
        self.vad_backend = None
        if use_vad:
            self.vad, self.vad_backend = _get_vad(0)
            print(f"VAD enabled (backend: {self.vad_backend})")

        # Audio processing
        self.audio_queue = queue.Queue(maxsize=50)  # 50 chunks = 1500ms buffer (handles processing delays on remote servers)
        self.is_recording = False
        self.is_speaking = False
        self.stream = None
        self.dropped_chunks = 0  # Track dropped chunks for debugging

        # VAD state tracking
        self.speech_frames = 0
        self.silence_frames = 0
        self.frames_for_speech_start = 2   # Consecutive voiced frames to start (60ms with 30ms chunks - fast response)
        self.frames_for_speech_stop = 60   # Consecutive silent frames to stop (1800ms with 30ms chunks - extremely tolerant)

        # Processing thread
        self.process_thread = None
        self.stop_processing = False

        # Callbacks
        self.on_speech_start: Optional[Callable] = None
        self.on_audio_chunk: Optional[Callable[[bytes], None]] = None
        self.on_speech_stop: Optional[Callable] = None
        self.on_error: Optional[Callable[[str], None]] = None

    @property
    def use_vad(self):
        return self._use_vad

    @use_vad.setter
    def use_vad(self, value):
        self._use_vad = bool(value)
        if value and self.vad is None:
            self.vad, self.vad_backend = _get_vad(0)
            print(f"VAD enabled (backend: {self.vad_backend})")

    def start_capture(self):
        """Start capturing from microphone"""
        if self.is_recording:
            return

        try:
            self.is_recording = True
            self.is_speaking = False
            self.speech_frames = 0
            self.silence_frames = 0
            self.stop_processing = False
            self.dropped_chunks = 0

            # Get system default input device
            default_input = sd.default.device[0]  # [0] is input, [1] is output
            print(f"[VOICE DEBUG] Using default input device: {default_input}")

            # List available input devices
            devices = sd.query_devices()
            print(f"[VOICE DEBUG] Available input devices:")
            for i, dev in enumerate(devices):
                if dev['max_input_channels'] > 0:
                    default_marker = " (SYSTEM DEFAULT)" if i == default_input else ""
                    print(f"[VOICE DEBUG]   [{i}] {dev['name']} - {dev['max_input_channels']} ch{default_marker}")

            # Start audio stream with explicit default device
            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,  # Mono
                dtype='int16',
                blocksize=self.chunk_size,
                device=default_input,  # Explicitly use system default
                callback=self._audio_callback
            )
            self.stream.start()

            # Start processing thread
            self.process_thread = threading.Thread(target=self._process_audio, daemon=True)
            self.process_thread.start()

            device_name = devices[default_input]['name']
            print(f"[VOICE DEBUG] Voice capture started on: {device_name}")
            print(f"[VOICE DEBUG] Sample rate: {self.sample_rate}Hz, chunk: {self.chunk_duration_ms}ms")

        except Exception as e:
            self.is_recording = False
            error_msg = f"Failed to start audio capture: {e}"
            print(error_msg)
            if self.on_error:
                self.on_error(error_msg)

    def stop_capture(self):
        """Stop microphone capture"""
        if not self.is_recording:
            return

        self.is_recording = False
        self.stop_processing = True

        # Stop stream
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        # Stop speaking if active (important for continuous mode)
        if self.is_speaking:
            self.is_speaking = False
            if self.on_speech_stop:
                self.on_speech_stop()

        # Wait for processing thread to finish
        if self.process_thread and self.process_thread.is_alive():
            self.process_thread.join(timeout=1.0)

        mode = "continuous" if not self.use_vad else "VAD"
        print(f"Voice capture stopped ({mode} mode)")

    def _audio_callback(self, indata, frames, time_info, status):
        """Callback for sounddevice stream - receives raw audio"""
        if status:
            print(f"Audio callback status: {status}")

        if not self.is_recording:
            return

        # Convert numpy array to bytes
        audio_bytes = indata.tobytes()

        # Queue for VAD processing (non-blocking to prevent audio glitches)
        try:
            self.audio_queue.put_nowait(audio_bytes)
        except queue.Full:
            # Queue full - drop this chunk to prevent blocking callback
            self.dropped_chunks += 1
            if self.dropped_chunks % 10 == 1:  # Log every 10th drop
                print(f"[VOICE WARNING] Audio queue full, dropped {self.dropped_chunks} chunks (processing too slow)")

    def _process_audio(self):
        """Background thread to process VAD and trigger callbacks"""
        while not self.stop_processing:
            try:
                # Get audio chunk with timeout
                audio_chunk = self.audio_queue.get(timeout=0.1)

                # CONTINUOUS MODE: No VAD, always transmit
                if not self.use_vad:
                    # Mark as speaking if not already (for first chunk)
                    if not self.is_speaking:
                        self.is_speaking = True
                        if self.on_speech_start:
                            self.on_speech_start()

                    # Always send audio chunk in continuous mode
                    if self.on_audio_chunk:
                        self.on_audio_chunk(audio_chunk)
                    continue

                # VAD MODE: Use voice activity detection
                # Run VAD on chunk
                is_speech = self._check_vad(audio_chunk)

                # Update speech state
                if is_speech:
                    self.speech_frames += 1
                    self.silence_frames = 0

                    # Check if speech just started
                    if not self.is_speaking and self.speech_frames >= self.frames_for_speech_start:
                        self.is_speaking = True
                        if self.on_speech_start:
                            self.on_speech_start()

                else:  # Silence detected
                    self.silence_frames += 1
                    # Only reset speech frames if we're NOT currently speaking
                    # This prevents cutting during brief pauses in speech
                    if not self.is_speaking:
                        self.speech_frames = 0

                    # Check if speech just stopped
                    if self.is_speaking and self.silence_frames >= self.frames_for_speech_stop:
                        self.is_speaking = False
                        self.speech_frames = 0  # Reset only when actually stopping
                        if self.on_speech_stop:
                            self.on_speech_stop()

                # Send audio chunk if speaking (including during brief silences)
                if self.is_speaking and self.on_audio_chunk:
                    self.on_audio_chunk(audio_chunk)

            except queue.Empty:
                continue
            except Exception as e:
                print(f"Audio processing error: {e}")
                if self.on_error:
                    self.on_error(str(e))

    def _check_vad(self, audio_bytes: bytes) -> bool:
        """Check whether an audio chunk contains speech."""
        # If VAD is disabled, always return True (continuous mode)
        if not self.vad:
            return True

        try:
            # Both backends want exact frames: 10, 20 or 30 ms at 8/16/32/48 kHz.
            return self.vad.is_speech(audio_bytes, self.sample_rate)
        except Exception as e:
            # A backend that cannot judge this frame must not mute the user.
            # Report once, then transmit - a stuck-open mic is recoverable,
            # a caller nobody can hear is not.
            if not hasattr(self, '_vad_error_logged'):
                self._vad_error_logged = True
                expected_size = int(self.sample_rate * self.chunk_duration_ms / 1000) * 2  # *2 for int16
                actual_size = len(audio_bytes)
                print(f"VAD error ({self.vad_backend}): {e}")
                print(f"  Expected chunk size: {expected_size} bytes ({self.chunk_duration_ms}ms at {self.sample_rate}Hz)")
                print(f"  Actual chunk size: {actual_size} bytes")
                print(f"  Supported frames: 10ms, 20ms or 30ms")
                print(f"  Falling back to continuous transmission for this session")
            return True

    def set_vad_aggressiveness(self, level: int):
        """
        Set VAD aggressiveness level

        Args:
            level: 0-3 (0=least aggressive, 3=most aggressive)
                   Higher values filter out more non-speech
        """
        if 0 <= level <= 3:
            if self.vad is None:
                self.vad, self.vad_backend = _get_vad(level)
            else:
                self.vad.set_mode(level)
            print(f"VAD aggressiveness set to {level} ({self.vad_backend})")

    def get_available_devices(self) -> list:
        """Get list of available input audio devices"""
        try:
            devices = sd.query_devices()
            input_devices = []
            for i, device in enumerate(devices):
                if device['max_input_channels'] > 0:
                    input_devices.append({
                        'index': i,
                        'name': device['name'],
                        'channels': device['max_input_channels'],
                        'sample_rate': device['default_samplerate']
                    })
            return input_devices
        except Exception as e:
            print(f"Error querying audio devices: {e}")
            return []

    def set_device(self, device_index: int):
        """
        Set input device for recording

        Args:
            device_index: Device index from get_available_devices()
        """
        sd.default.device[0] = device_index  # Set input device
        print(f"Audio input device set to index {device_index}")


# Test/demo code
if __name__ == "__main__":
    print("Voice Capture Manager Test")
    print("=" * 40)

    # Create manager
    manager = VoiceCaptureManager()

    # Print available devices
    print("\nAvailable input devices:")
    devices = manager.get_available_devices()
    for device in devices:
        print(f"  [{device['index']}] {device['name']} ({device['channels']} ch, {device['sample_rate']} Hz)")

    # Setup callbacks
    def on_start():
        print("\n>>> Speech started!")

    def on_chunk(data):
        print(f"    Audio chunk: {len(data)} bytes")

    def on_stop():
        print("<<< Speech stopped!\n")

    manager.on_speech_start = on_start
    manager.on_audio_chunk = on_chunk
    manager.on_speech_stop = on_stop

    # Start capture
    print("\nStarting capture... Speak to test VAD!")
    print("Press Ctrl+C to stop.\n")
    manager.start_capture()

    try:
        # Keep running
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\nStopping...")
        manager.stop_capture()
        print("Done!")
