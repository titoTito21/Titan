// Titan-Net browser voice chat
// Captures mic → 16 kHz mono PCM (Int16 LE) → binary WS frame with 13-byte header
// Header (big-endian): >B I I I  = type(0x01) room_id user_id seq
// Plays incoming voice_audio frames via Web Audio AudioBufferSourceNode chain.
(function () {
  'use strict';

  const VOICE_AUDIO_TYPE = 0x01;
  const VOICE_HEADER_SIZE = 13;
  const SAMPLE_RATE = 16000;
  const FRAME_SAMPLES = 480;  // 30 ms at 16 kHz — matches webrtcvad on server

  class VoiceClient {
    constructor(ws) {
      this.ws = ws;
      this.userId = 0;
      this.roomId = 0;
      this.seq = 0;
      this.live = false;

      this.audioCtx = null;
      this.micStream = null;
      this.workletNode = null;
      this.sourceNode = null;

      this.playCtx = null;
      this.nextPlayTime = 0;

      // Map user_id -> playback chain (for "X speaking" announce)
      this.activeSpeakers = new Set();

      // Listen for incoming voice frames (binary first, JSON fallback)
      // Binary path
      ws.addEventListener('message', (e) => {
        // Custom dispatch from ws.js sends parsed JSON in detail; we also
        // hook the underlying ws for binary frames.
      });
      // Hook native ws for binary messages
      this._hookBinary();

      ws.addEventListener('msg:voice_started', (e) => this._onSpeakerChange(e.detail, true));
      ws.addEventListener('msg:voice_stopped', (e) => this._onSpeakerChange(e.detail, false));
      ws.addEventListener('msg:voice_audio', (e) => {
        // JSON fallback — base64 PCM in `data`
        const d = e.detail;
        if (!d || !d.data) return;
        try {
          const raw = atob(d.data);
          const buf = new ArrayBuffer(raw.length);
          const view = new Uint8Array(buf);
          for (let i = 0; i < raw.length; i++) view[i] = raw.charCodeAt(i);
          this._playPcm(buf);
        } catch (e) {}
      });
    }

    _hookBinary() {
      // Replace the WS instance's `_open` to add binary forwarding.
      // Simpler: tap directly into the active socket.
      const tryHook = () => {
        if (this.ws.ws) {
          this.ws.ws.binaryType = 'arraybuffer';
          this.ws.ws.addEventListener('message', (ev) => {
            if (ev.data instanceof ArrayBuffer && ev.data.byteLength > VOICE_HEADER_SIZE) {
              const view = new DataView(ev.data);
              if (view.getUint8(0) === VOICE_AUDIO_TYPE) {
                this._playPcm(ev.data.slice(VOICE_HEADER_SIZE));
              }
            }
          });
        }
      };
      this.ws.addEventListener('open', tryHook);
      if (this.ws.connected) tryHook();
    }

    setUser(userId) { this.userId = userId; }
    setRoom(roomId) { this.roomId = roomId; }

    _onSpeakerChange(data, started) {
      if (!data || !data.username) return;
      if (started) {
        if (!this.activeSpeakers.has(data.user_id)) {
          this.activeSpeakers.add(data.user_id);
          Titan.announce(Titan.t('voice.speaking', data.username));
        }
      } else {
        this.activeSpeakers.delete(data.user_id);
      }
    }

    async start() {
      if (this.live) return;
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia ||
          typeof AudioContext === 'undefined') {
        throw new Error(Titan.t('voice.unsupported'));
      }
      if (!this.roomId || !this.userId) {
        throw new Error('Pick a room first');
      }
      try {
        this.micStream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
            sampleRate: SAMPLE_RATE,
          },
          video: false,
        });
      } catch (e) {
        throw new Error(Titan.t('voice.denied'));
      }

      this.audioCtx = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: SAMPLE_RATE,
      });

      // Tell server we started voice in this room
      this.ws.send({ type: 'voice_start', room_id: this.roomId });

      this.sourceNode = this.audioCtx.createMediaStreamSource(this.micStream);

      // Use ScriptProcessorNode for broad compat (AudioWorklet would be better but heavier)
      const bufferSize = 2048;
      const proc = this.audioCtx.createScriptProcessor(bufferSize, 1, 1);
      proc.onaudioprocess = (e) => this._onAudio(e);
      this.sourceNode.connect(proc);
      // Connect to destination with zero gain so the node actually runs
      const silentGain = this.audioCtx.createGain();
      silentGain.gain.value = 0;
      proc.connect(silentGain);
      silentGain.connect(this.audioCtx.destination);
      this.workletNode = proc;

      this.live = true;
      Titan.announce(Titan.t('voice.live'));
    }

    stop() {
      if (!this.live) return;
      this.live = false;
      if (this.workletNode) try { this.workletNode.disconnect(); } catch (e) {}
      if (this.sourceNode) try { this.sourceNode.disconnect(); } catch (e) {}
      if (this.micStream) {
        try { this.micStream.getTracks().forEach((t) => t.stop()); } catch (e) {}
      }
      if (this.audioCtx) try { this.audioCtx.close(); } catch (e) {}
      this.workletNode = null;
      this.sourceNode = null;
      this.micStream = null;
      this.audioCtx = null;
      this.ws.send({ type: 'voice_stop', room_id: this.roomId });
      Titan.announce(Titan.t('voice.off'));
    }

    _onAudio(event) {
      if (!this.live) return;
      const inputData = event.inputBuffer.getChannelData(0);
      // Browser already resampled to 16 kHz via AudioContext sampleRate hint
      // (most browsers honour it). Pack Float32 → Int16 LE.
      const pcm = new Int16Array(inputData.length);
      for (let i = 0; i < inputData.length; i++) {
        let s = inputData[i];
        if (s > 1) s = 1; else if (s < -1) s = -1;
        pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      }
      // Build header
      const buf = new ArrayBuffer(VOICE_HEADER_SIZE + pcm.byteLength);
      const view = new DataView(buf);
      view.setUint8(0, VOICE_AUDIO_TYPE);
      view.setUint32(1, this.roomId, false);
      view.setUint32(5, this.userId, false);
      view.setUint32(9, this.seq++ & 0xFFFFFFFF, false);
      new Uint8Array(buf, VOICE_HEADER_SIZE).set(new Uint8Array(pcm.buffer));
      if (this.ws.ws && this.ws.ws.readyState === WebSocket.OPEN) {
        try { this.ws.ws.send(buf); } catch (e) {}
      }
    }

    _ensurePlayCtx() {
      if (this.playCtx) return;
      this.playCtx = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: SAMPLE_RATE,
      });
      this.nextPlayTime = this.playCtx.currentTime;
    }

    _playPcm(arrayBuffer) {
      this._ensurePlayCtx();
      const pcm = new Int16Array(arrayBuffer);
      if (pcm.length === 0) return;
      const buf = this.playCtx.createBuffer(1, pcm.length, SAMPLE_RATE);
      const ch = buf.getChannelData(0);
      for (let i = 0; i < pcm.length; i++) {
        ch[i] = pcm[i] / 0x8000;
      }
      const src = this.playCtx.createBufferSource();
      src.buffer = buf;
      src.connect(this.playCtx.destination);
      const now = this.playCtx.currentTime;
      if (this.nextPlayTime < now + 0.05) this.nextPlayTime = now + 0.05;
      src.start(this.nextPlayTime);
      this.nextPlayTime += buf.duration;
    }
  }

  window.Titan = window.Titan || {};
  window.Titan.VoiceClient = VoiceClient;
})();
