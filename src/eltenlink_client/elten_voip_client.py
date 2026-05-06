"""
EltenLink VOIP Client - TCP+UDP client for Elten conference/voice call server.
Based on Ruby Elten's Conference class and elten_voip.rb server.

Protocol:
- TCP (SSL) on elten-net.eu:8133 for control messages (JSON line-delimited)
- UDP on elten-net.eu:8133 for audio packets (binary)
- Commands: login, create, join, leave, update, list, close
- Audio: 9-byte header (userid 2B, stamp 3B, index 3B, type 1B) + opus payload
"""

import json
import socket
import ssl
import struct
import threading
import time
import base64

from src.titan_core.translation import set_language
from src.settings.settings import get_setting

_ = set_language(get_setting('language', 'pl'))

VOIP_HOST = "elten-net.eu"
VOIP_PORT = 8133

# Audio defaults matching Ruby Elten
DEFAULT_BITRATE = 56
DEFAULT_FRAMESIZE = 40
DEFAULT_CHANNELS = 2
DEFAULT_SAMPLE_RATE = 48000

# Message types from server
MSG_TYPE_AUDIO = 1
MSG_TYPE_TEXT = 2


class VoipChannel:
    """Represents a conference channel."""

    def __init__(self, channel_id=0, name="", bitrate=DEFAULT_BITRATE,
                 framesize=DEFAULT_FRAMESIZE, password=None):
        self.id = channel_id
        self.name = name
        self.bitrate = bitrate
        self.framesize = framesize
        self.password = password
        self.users = []  # list of {'id': int, 'name': str}
        self.secret = None
        self.stamp = 0


class EltenVoipClient:
    """TCP+UDP VOIP client for Elten conference server.

    Flow for a voice call:
    1. connect() - TCP SSL connection + login
    2. create_channel() - create private channel with password
    3. join_channel() - join the created channel
    4. start_audio() - begin audio capture and playback
    5. disconnect() - leave and close
    """

    def __init__(self, username):
        self.username = username
        self.user_id = 0
        self.user_secret = None  # 256 bytes from server on login

        # Connection state
        self._tcp_socket = None
        self._udp_socket = None
        self._connected = False
        self._channel = None  # current VoipChannel

        # Threading
        self._update_thread = None
        self._audio_recv_thread = None
        self._audio_send_thread = None
        self._stop_event = threading.Event()
        self._tcp_lock = threading.Lock()

        # Audio state
        self._audio_active = False
        self._muted = False
        self._audio_index = 0

        # Opus encoder/decoder
        self._encoder = None
        self._decoder = None

        # Audio device streams
        self._input_stream = None
        self._output_stream = None

        # Callbacks
        self.on_channel_update = None  # called with VoipChannel when users change
        self.on_user_joined = None  # called with username
        self.on_user_left = None  # called with username
        self.on_text_received = None  # called with (username, text)
        self.on_disconnected = None  # called on connection loss
        self.on_error = None  # called with error message

    @property
    def connected(self):
        return self._connected

    @property
    def channel(self):
        return self._channel

    @property
    def muted(self):
        return self._muted

    @muted.setter
    def muted(self, value):
        self._muted = bool(value)

    # ---- TCP Control ----

    def connect(self):
        """Connect to VOIP server via SSL TCP and login."""
        try:
            # TCP connection with SSL
            raw_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            raw_socket.settimeout(10)

            # SSL context - allow self-signed certs like Ruby client
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            self._tcp_socket = ctx.wrap_socket(raw_socket, server_hostname=VOIP_HOST)
            self._tcp_socket.connect((VOIP_HOST, VOIP_PORT))

            # Login
            response = self._send_command({
                ':command': 'login',
                'login': self.username
            })

            if response and response.get('status') == 'success':
                self.user_id = response.get('id', 0)
                secret_b64 = response.get('secret', '')
                self.user_secret = base64.b64decode(secret_b64) if secret_b64 else None
                self._connected = True

                # Setup UDP
                self._udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self._udp_socket.settimeout(0.5)

                # Send secret via UDP to register our UDP address on server
                if self.user_secret:
                    self._udp_socket.sendto(self.user_secret, (VOIP_HOST, VOIP_PORT))

                # Start update polling thread
                self._stop_event.clear()
                self._update_thread = threading.Thread(
                    target=self._update_loop, daemon=True)
                self._update_thread.start()

                return True
            else:
                self._cleanup_sockets()
                return False

        except Exception as e:
            print(f"[VoIP] Connection error: {e}")
            self._cleanup_sockets()
            if self.on_error:
                self.on_error(str(e))
            return False

    def disconnect(self):
        """Disconnect from VOIP server."""
        self.stop_audio()
        self._stop_event.set()

        if self._connected:
            try:
                self._send_command({':command': 'close'})
            except Exception:
                pass

        self._connected = False
        self._channel = None
        self._cleanup_sockets()

    def create_channel(self, name=None, password=None, bitrate=DEFAULT_BITRATE,
                       framesize=DEFAULT_FRAMESIZE):
        """Create a new channel on the server. Returns channel id or None."""
        if not self._connected:
            return None

        if name is None:
            name = f"VoiceCall_{self.username}"

        response = self._send_command({
            ':command': 'create',
            'name': name,
            'public': False,
            'bitrate': bitrate,
            'framesize': framesize,
            'password': password,
        })

        if response and response.get('status') == 'success':
            ch = VoipChannel(
                channel_id=response.get('id', 0),
                name=response.get('name', name),
                bitrate=response.get('bitrate', bitrate),
                framesize=response.get('framesize', framesize),
                password=response.get('password', password),
            )
            return ch
        return None

    def join_channel(self, channel_id, password=None):
        """Join an existing channel."""
        if not self._connected:
            return False

        response = self._send_command({
            ':command': 'join',
            'channel': channel_id,
            'password': password,
        })

        if response and response.get('status') == 'success':
            self._channel = VoipChannel(channel_id=channel_id, password=password)
            return True
        return False

    def leave_channel(self):
        """Leave current channel."""
        if not self._connected:
            return

        self.stop_audio()
        self._send_command({':command': 'leave'})
        self._channel = None

    def list_channels(self):
        """List all public channels."""
        if not self._connected:
            return []

        response = self._send_command({':command': 'list'})
        if response and response.get('status') == 'success':
            return response.get('channels', [])
        return []

    # ---- Audio ----

    def start_audio(self):
        """Start audio capture and playback."""
        if self._audio_active or not self._connected:
            return

        try:
            self._init_opus()
        except Exception as e:
            print(f"[VoIP] Opus init error: {e}")
            if self.on_error:
                self.on_error(_("Audio codec initialization failed"))
            return

        self._audio_active = True
        self._audio_index = 0

        # Start audio receive thread
        self._audio_recv_thread = threading.Thread(
            target=self._audio_receive_loop, daemon=True)
        self._audio_recv_thread.start()

        # Start audio send thread
        self._audio_send_thread = threading.Thread(
            target=self._audio_send_loop, daemon=True)
        self._audio_send_thread.start()

    def stop_audio(self):
        """Stop audio capture and playback."""
        self._audio_active = False

        if self._input_stream:
            try:
                self._input_stream.stop()
                self._input_stream.close()
            except Exception:
                pass
            self._input_stream = None

        if self._output_stream:
            try:
                self._output_stream.stop()
                self._output_stream.close()
            except Exception:
                pass
            self._output_stream = None

        if self._encoder:
            try:
                self._encoder = None
            except Exception:
                pass

        if self._decoder:
            try:
                self._decoder = None
            except Exception:
                pass

    # ---- Internal ----

    def _send_command(self, command):
        """Send JSON command via TCP and read response."""
        if not self._tcp_socket:
            return None

        with self._tcp_lock:
            try:
                data = json.dumps(command) + "\n"
                self._tcp_socket.sendall(data.encode('utf-8'))

                # Read response line
                response_data = b""
                while True:
                    chunk = self._tcp_socket.recv(4096)
                    if not chunk:
                        return None
                    response_data += chunk
                    if b"\n" in response_data:
                        break

                line = response_data.split(b"\n")[0]
                return json.loads(line.decode('utf-8'))

            except Exception as e:
                print(f"[VoIP] TCP command error: {e}")
                return None

    def _update_loop(self):
        """Poll server for channel updates (user joins/leaves)."""
        while not self._stop_event.is_set():
            if not self._connected:
                break

            try:
                response = self._send_command({':command': 'update'})
                if response and response.get('status') == 'success':
                    if response.get('updated'):
                        channel_id = response.get('channel', 0)
                        secret_b64 = response.get('channel_secret', '')
                        stamp = response.get('channel_stamp', 0)
                        users = response.get('channel_users', [])

                        if self._channel:
                            old_users = {u['name'] for u in self._channel.users}
                            new_users = {u['name'] for u in users}

                            self._channel.id = channel_id
                            self._channel.users = users
                            self._channel.stamp = stamp
                            if secret_b64:
                                self._channel.secret = base64.b64decode(secret_b64)

                            # Notify about user changes
                            for name in new_users - old_users:
                                if name != self.username and self.on_user_joined:
                                    self.on_user_joined(name)

                            for name in old_users - new_users:
                                if name != self.username and self.on_user_left:
                                    self.on_user_left(name)

                            if self.on_channel_update:
                                self.on_channel_update(self._channel)

                elif response and response.get('status') == 'error':
                    pass  # Server returned error, keep polling

            except Exception as e:
                print(f"[VoIP] Update error: {e}")
                if not self._connected:
                    break

            # Poll every 500ms
            self._stop_event.wait(0.5)

        # Connection lost
        if self._connected:
            self._connected = False
            if self.on_disconnected:
                self.on_disconnected()

    def _init_opus(self):
        """Initialize Opus encoder/decoder."""
        try:
            import opuslib
            framesize_samples = int(DEFAULT_SAMPLE_RATE * DEFAULT_FRAMESIZE / 1000)
            self._encoder = opuslib.Encoder(
                DEFAULT_SAMPLE_RATE, DEFAULT_CHANNELS,
                opuslib.APPLICATION_VOIP)
            self._encoder.bitrate = DEFAULT_BITRATE * 1000
            self._encoder.inband_fec = True

            self._decoder = opuslib.Decoder(
                DEFAULT_SAMPLE_RATE, DEFAULT_CHANNELS)
            self._opus_frame_samples = framesize_samples
            return
        except ImportError:
            pass

        # Fallback: try pyogg
        try:
            from pyogg import OpusEncoder, OpusDecoder
            self._encoder = OpusEncoder()
            self._encoder.set_application("voip")
            self._encoder.set_sampling_frequency(DEFAULT_SAMPLE_RATE)
            self._encoder.set_channels(DEFAULT_CHANNELS)

            self._decoder = OpusDecoder()
            self._decoder.set_sampling_frequency(DEFAULT_SAMPLE_RATE)
            self._decoder.set_channels(DEFAULT_CHANNELS)
            self._opus_frame_samples = int(DEFAULT_SAMPLE_RATE * DEFAULT_FRAMESIZE / 1000)
            self._opus_lib = 'pyogg'
            return
        except ImportError:
            pass

        raise ImportError(_("Opus codec not available. Install opuslib or pyogg."))

    def _build_audio_packet(self, opus_data):
        """Build audio packet with 9-byte header.

        Header format (from elten_voip.rb extract()):
        - bytes 0-1: user_id (uint16 LE)
        - bytes 2-4: stamp (uint24 LE)
        - bytes 5-7: index (uint24 LE)
        - byte 8: type (1=audio, 2=text)
        """
        self._audio_index += 1
        stamp = self._channel.stamp if self._channel else 0

        header = struct.pack('<H', self.user_id & 0xFFFF)  # userid 2 bytes LE
        header += struct.pack('<I', stamp & 0xFFFFFF)[:3]  # stamp 3 bytes LE
        header += struct.pack('<I', self._audio_index & 0xFFFFFF)[:3]  # index 3 bytes LE
        header += struct.pack('B', MSG_TYPE_AUDIO)  # type 1 byte

        return header + opus_data

    def _audio_send_loop(self):
        """Capture audio from microphone, encode with Opus, send via UDP."""
        try:
            import sounddevice as sd
            import numpy as np
        except ImportError:
            print("[VoIP] sounddevice not available")
            if self.on_error:
                self.on_error(_("Audio device not available"))
            return

        frame_duration_ms = DEFAULT_FRAMESIZE
        frame_size = int(DEFAULT_SAMPLE_RATE * frame_duration_ms / 1000)
        blocksize = frame_size * DEFAULT_CHANNELS

        try:
            self._input_stream = sd.InputStream(
                samplerate=DEFAULT_SAMPLE_RATE,
                channels=DEFAULT_CHANNELS,
                dtype='int16',
                blocksize=frame_size,
            )
            self._input_stream.start()
        except Exception as e:
            print(f"[VoIP] Mic open error: {e}")
            if self.on_error:
                self.on_error(_("Microphone not available"))
            return

        while self._audio_active and not self._stop_event.is_set():
            try:
                if self._muted:
                    time.sleep(frame_duration_ms / 1000)
                    continue

                data, overflowed = self._input_stream.read(frame_size)
                pcm_bytes = data.tobytes()

                # Encode with Opus
                try:
                    if hasattr(self._encoder, 'encode'):
                        opus_data = self._encoder.encode(pcm_bytes, frame_size)
                    else:
                        opus_data = self._encoder.encode(
                            memoryview(bytearray(pcm_bytes)))
                except Exception:
                    continue

                if opus_data and self._udp_socket and self._channel:
                    packet = self._build_audio_packet(opus_data)
                    self._udp_socket.sendto(packet, (VOIP_HOST, VOIP_PORT))

            except Exception as e:
                if self._audio_active:
                    print(f"[VoIP] Audio send error: {e}")
                break

    def _audio_receive_loop(self):
        """Receive audio packets via UDP, decode with Opus, play."""
        try:
            import sounddevice as sd
            import numpy as np
        except ImportError:
            return

        try:
            self._output_stream = sd.OutputStream(
                samplerate=DEFAULT_SAMPLE_RATE,
                channels=DEFAULT_CHANNELS,
                dtype='int16',
            )
            self._output_stream.start()
        except Exception as e:
            print(f"[VoIP] Speaker open error: {e}")
            return

        frame_size = int(DEFAULT_SAMPLE_RATE * DEFAULT_FRAMESIZE / 1000)

        while self._audio_active and not self._stop_event.is_set():
            try:
                data, addr = self._udp_socket.recvfrom(65536)
                if len(data) < 9:
                    continue

                # Parse header
                sender_id = struct.unpack('<H', data[0:2])[0]
                msg_type = data[8]

                # Skip our own audio
                if sender_id == self.user_id:
                    continue

                if msg_type == MSG_TYPE_AUDIO:
                    opus_payload = data[9:]
                    try:
                        if hasattr(self._decoder, 'decode'):
                            pcm = self._decoder.decode(opus_payload, frame_size)
                        else:
                            pcm = self._decoder.decode(
                                memoryview(bytearray(opus_payload)))

                        if pcm and self._output_stream:
                            import numpy as np
                            audio_array = np.frombuffer(pcm, dtype='int16')
                            expected = frame_size * DEFAULT_CHANNELS
                            if len(audio_array) >= expected:
                                audio_array = audio_array[:expected].reshape(-1, DEFAULT_CHANNELS)
                                self._output_stream.write(audio_array)
                    except Exception:
                        pass

                elif msg_type == MSG_TYPE_TEXT:
                    try:
                        text = data[9:].decode('utf-8')
                        if self.on_text_received:
                            self.on_text_received(sender_id, text)
                    except Exception:
                        pass

            except socket.timeout:
                continue
            except Exception as e:
                if self._audio_active:
                    print(f"[VoIP] Audio recv error: {e}")
                break

    def _cleanup_sockets(self):
        """Close all sockets."""
        if self._tcp_socket:
            try:
                self._tcp_socket.close()
            except Exception:
                pass
            self._tcp_socket = None

        if self._udp_socket:
            try:
                self._udp_socket.close()
            except Exception:
                pass
            self._udp_socket = None
