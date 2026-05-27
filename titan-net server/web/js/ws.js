// Titan-Net WebSocket client (browser)
// Connects to wss://<host>:8001 (cert terminated by server.py itself).
(function () {
  'use strict';

  function defaultWsUrl() {
    const host = location.hostname || 'titosofttitan.com';
    const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return scheme + '//' + host + ':8001';
  }

  class TitanWS extends EventTarget {
    constructor(url) {
      super();
      this.url = url || defaultWsUrl();
      this.ws = null;
      this.connected = false;
      this.reconnectDelay = 1000;
      this.reconnectMax = 15000;
      this.shouldReconnect = true;
      this.pingTimer = null;
    }

    connect() {
      this.shouldReconnect = true;
      this._open();
    }

    disconnect() {
      this.shouldReconnect = false;
      if (this.pingTimer) { clearInterval(this.pingTimer); this.pingTimer = null; }
      if (this.ws) try { this.ws.close(); } catch (e) {}
      this.ws = null;
      this.connected = false;
    }

    _open() {
      try {
        this.ws = new WebSocket(this.url);
      } catch (e) {
        this._scheduleReconnect();
        return;
      }
      this.ws.addEventListener('open', () => {
        this.connected = true;
        this.reconnectDelay = 1000;
        this.dispatchEvent(new CustomEvent('open'));
        this.pingTimer = setInterval(() => {
          if (this.connected) this.send({ type: 'ping' });
        }, 30000);
      });
      this.ws.addEventListener('message', (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch (e) { return; }
        // Dispatch typed event so listeners can filter by type
        this.dispatchEvent(new CustomEvent('message', { detail: msg }));
        if (msg && msg.type) {
          this.dispatchEvent(new CustomEvent('msg:' + msg.type, { detail: msg }));
        }
      });
      this.ws.addEventListener('close', () => {
        this.connected = false;
        if (this.pingTimer) { clearInterval(this.pingTimer); this.pingTimer = null; }
        this.dispatchEvent(new CustomEvent('close'));
        if (this.shouldReconnect) this._scheduleReconnect();
      });
      this.ws.addEventListener('error', () => {
        this.dispatchEvent(new CustomEvent('ws-error'));
      });
    }

    _scheduleReconnect() {
      const d = this.reconnectDelay;
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.reconnectMax);
      setTimeout(() => { if (this.shouldReconnect) this._open(); }, d);
    }

    send(obj) {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
      try {
        this.ws.send(JSON.stringify(obj));
        return true;
      } catch (e) {
        return false;
      }
    }

    // Convenience: send and wait for matching reply type (first match wins, 10s timeout)
    request(payload, replyType, timeoutMs) {
      return new Promise((resolve, reject) => {
        const t = setTimeout(() => {
          this.removeEventListener('msg:' + replyType, onReply);
          reject(new Error('Request timed out'));
        }, timeoutMs || 10000);
        const onReply = (e) => {
          clearTimeout(t);
          this.removeEventListener('msg:' + replyType, onReply);
          resolve(e.detail);
        };
        this.addEventListener('msg:' + replyType, onReply);
        const ok = this.send(payload);
        if (!ok) {
          clearTimeout(t);
          this.removeEventListener('msg:' + replyType, onReply);
          reject(new Error('Not connected'));
        }
      });
    }

    // High-level helpers
    login(username, password) {
      return this.request(
        { type: 'login', username, password, language: Titan.getLang() },
        'login_response',
        15000,
      );
    }
    register(username, password, full_name) {
      // The server only consumes username / password / full_name — matches
      // the desktop titan_net_gui registration (no email field).
      return this.request(
        { type: 'register', username, password, full_name: full_name || '' },
        'register_response',
        15000,
      );
    }
    getRooms() { return this.request({ type: 'get_rooms' }, 'rooms_list'); }
    getOnlineUsers() { return this.request({ type: 'get_online_users' }, 'online_users'); }
    getRoomMessages(roomId, limit) {
      return this.request(
        { type: 'get_room_messages', room_id: roomId, limit: limit || 50 },
        'room_messages',
      );
    }
    joinRoom(roomId, password) {
      const payload = { type: 'join_room', room_id: roomId };
      if (password) payload.password = password;
      this.send(payload);
    }
    leaveRoom(roomId) { this.send({ type: 'leave_room', room_id: roomId }); }
    createRoom(name, description, roomType, password) {
      const payload = {
        type: 'create_room',
        name: name,
        description: description || '',
        room_type: roomType || 'text',
      };
      if (password) payload.password = password;
      return this.request(payload, 'room_created', 15000);
    }
    deleteRoom(roomId) {
      return this.request(
        { type: 'delete_room', room_id: roomId },
        'room_deleted',
        10000,
      );
    }
    sendRoomMessage(roomId, message) {
      this.send({ type: 'room_message', room_id: roomId, message });
    }
    sendPrivateMessage(recipientId, message) {
      this.send({ type: 'private_message', recipient_id: recipientId, message });
    }
    getPrivateMessages(otherUserId, limit) {
      return this.request(
        { type: 'get_messages', user_id: otherUserId, limit: limit || 100 },
        'private_messages',
      );
    }
    markMessagesRead(senderUserId) {
      return this.request(
        { type: 'mark_messages_read', sender_user_id: senderUserId },
        'mark_messages_read_response',
      );
    }
  }

  window.Titan = window.Titan || {};
  window.Titan.WS = TitanWS;
})();
