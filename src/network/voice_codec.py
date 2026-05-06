"""
Voice Codec Module for Titan-Net
Handles Opus encoding/decoding and binary voice packet format.

Binary packet format:
  [1 byte]  packet_type (0x01 = voice_audio)
  [4 bytes] room_id (uint32 big-endian)
  [4 bytes] user_id (uint32 big-endian)
  [4 bytes] sequence_number (uint32 big-endian)
  [N bytes] audio_data (Opus frame or raw PCM fallback)
  Total header: 13 bytes
"""

import ctypes
import os
import struct
import sys
import time

VOICE_AUDIO_TYPE = 0x01
HEADER_SIZE = 13

# Try to load Opus codec
# Patch opuslib to find libopus from data/lib/ before importing
try:
    from ctypes.util import find_library as _orig_find_library
    _opus_dll_path = None
    if sys.platform == 'win32':
        if getattr(sys, 'frozen', False):
            _base_dir = os.path.dirname(sys.executable)
        else:
            _base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        _lib_dir = os.path.join(_base_dir, 'data', 'lib')
        for _dll_name in ('libopus-0.dll', 'opus.dll', 'libopus.dll'):
            _path = os.path.join(_lib_dir, _dll_name)
            if os.path.exists(_path):
                try:
                    ctypes.CDLL(_path)
                    _opus_dll_path = _path
                    break
                except OSError:
                    continue
    if _opus_dll_path:
        import ctypes.util
        _original_find = ctypes.util.find_library
        def _patched_find_library(name):
            if name == 'opus':
                return _opus_dll_path
            return _original_find(name)
        ctypes.util.find_library = _patched_find_library
    import opuslib
    OPUS_AVAILABLE = True
    # Restore original find_library
    if _opus_dll_path:
        ctypes.util.find_library = _original_find
except (ImportError, OSError, Exception):
    OPUS_AVAILABLE = False


def pack_voice_packet(room_id: int, user_id: int, seq: int, audio_data: bytes) -> bytes:
    """Pack voice audio into a binary packet"""
    header = struct.pack('>BIII', VOICE_AUDIO_TYPE, room_id, user_id, seq)
    return header + audio_data


def unpack_voice_header(data: bytes):
    """Unpack just the header of a binary voice packet (fast path for server relay)"""
    if len(data) < HEADER_SIZE:
        return None
    packet_type, room_id, user_id, seq = struct.unpack('>BIII', data[:HEADER_SIZE])
    if packet_type != VOICE_AUDIO_TYPE:
        return None
    return room_id, user_id, seq


def unpack_voice_packet(data: bytes):
    """Unpack a complete binary voice packet"""
    header = unpack_voice_header(data)
    if header is None:
        return None
    room_id, user_id, seq = header
    audio_data = data[HEADER_SIZE:]
    return {
        'room_id': room_id,
        'user_id': user_id,
        'seq': seq,
        'audio_data': audio_data
    }


class OpusVoiceCodec:
    """Opus encoder/decoder for real-time voice chat"""

    def __init__(self, sample_rate=16000, channels=1, bitrate=24000, frame_duration_ms=20):
        if not OPUS_AVAILABLE:
            raise RuntimeError("opuslib not available")

        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_duration_ms = frame_duration_ms
        self.frame_size = int(sample_rate * frame_duration_ms / 1000)  # samples per frame
        self.pcm_frame_bytes = self.frame_size * channels * 2  # 16-bit = 2 bytes per sample

        # Encoder optimized for voice
        self.encoder = opuslib.Encoder(sample_rate, channels, opuslib.APPLICATION_VOIP)
        self.encoder.bitrate = bitrate
        self.encoder.complexity = 6

        # Enable in-band FEC for packet loss resilience
        # Encoder embeds redundant data about previous frame in current frame
        try:
            import ctypes
            OPUS_SET_INBAND_FEC_REQUEST = 4012
            OPUS_SET_PACKET_LOSS_PERC_REQUEST = 4014
            opuslib.api.encoder.encoder_ctl(self.encoder._state, OPUS_SET_INBAND_FEC_REQUEST, 1)
            opuslib.api.encoder.encoder_ctl(self.encoder._state, OPUS_SET_PACKET_LOSS_PERC_REQUEST, 10)
        except Exception:
            pass  # FEC not critical — works without it

        # Decoder with packet loss concealment
        self.decoder = opuslib.Decoder(sample_rate, channels)

    def encode(self, pcm_data: bytes) -> bytes:
        """Encode PCM 16-bit frame to Opus"""
        return self.encoder.encode(pcm_data, self.frame_size)

    def decode(self, opus_data: bytes) -> bytes:
        """Decode Opus frame to PCM 16-bit. Pass None for packet loss concealment.
        Opus PLC uses decoder state to extrapolate missing audio — much better than silence."""
        if opus_data is None:
            # True Opus PLC: pass empty data, decoder generates plausible continuation
            try:
                return self.decoder.decode(b'', self.frame_size)
            except Exception:
                # Fallback: return silence frame
                return b'\x00' * self.pcm_frame_bytes
        return self.decoder.decode(opus_data, self.frame_size)

    def encode_chunk(self, pcm_data: bytes) -> list:
        """Split a larger PCM buffer into multiple Opus frames"""
        frames = []
        offset = 0
        while offset + self.pcm_frame_bytes <= len(pcm_data):
            chunk = pcm_data[offset:offset + self.pcm_frame_bytes]
            frames.append(self.encode(chunk))
            offset += self.pcm_frame_bytes
        return frames
