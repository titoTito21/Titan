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

    // Convenience: send and wait for matching reply type (first match wins,
    // 10s timeout). A refusal from the server arrives as a bare `error`
    // frame rather than as the reply type that was asked for, so that is
    // waited on too — without it a "permission denied" is indistinguishable
    // from a server that has stopped answering.
    request(payload, replyType, timeoutMs) {
      const types = Array.isArray(replyType) ? replyType.slice() : [replyType];
      if (types.indexOf('error') === -1) types.push('error');
      return new Promise((resolve, reject) => {
        const listeners = [];
        const done = () => {
          clearTimeout(timer);
          listeners.forEach(([type, fn]) => this.removeEventListener('msg:' + type, fn));
        };
        const timer = setTimeout(() => {
          done();
          reject(new Error('Request timed out'));
        }, timeoutMs || 10000);
        types.forEach((type) => {
          const fn = (e) => {
            done();
            const detail = e.detail || {};
            if (type === 'error' && detail.error) {
              const err = new Error(detail.error);
              err.serverError = true;
              reject(err);
              return;
            }
            resolve(detail);
          };
          listeners.push([type, fn]);
          this.addEventListener('msg:' + type, fn);
        });
        const ok = this.send(payload);
        if (!ok) {
          done();
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
    register(username, password, full_name, email) {
      // The server consumes username / password / full_name and an optional
      // recovery email — matches the desktop titan_net_gui registration.
      return this.request(
        { type: 'register', username, password, full_name: full_name || '', email: email || '' },
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

    // ---------- Blocking ----------
    // A personal, symmetric "full ignore": the desktop client calls it a
    // block, and the server stops routing anything either way.
    blockUser(userId) {
      return this.request({ type: 'block_user', user_id: userId }, 'block_result');
    }
    unblockUser(userId) {
      return this.request({ type: 'unblock_user', user_id: userId }, 'block_result');
    }
    getBlockedUsers() {
      return this.request({ type: 'get_blocked_users' }, 'blocked_users');
    }

    // ---------- Feedback Hub ----------
    listFeedback(itemType) {
      const payload = { type: 'list_feedback' };
      if (itemType) payload.item_type = itemType;
      return this.request(payload, 'list_feedback_response', 20000);
    }
    getFeedback(feedbackId) {
      return this.request({ type: 'get_feedback', feedback_id: feedbackId },
        'get_feedback_response');
    }
    createFeedback(payload) {
      return this.request(Object.assign({ type: 'create_feedback' }, payload),
        'create_feedback_response', 60000);
    }
    upvoteFeedback(feedbackId) {
      return this.request({ type: 'upvote_feedback', feedback_id: feedbackId },
        'upvote_feedback_response');
    }
    setFeedbackStatus(feedbackId, status) {
      return this.request({ type: 'change_feedback_status', feedback_id: feedbackId, status },
        'change_feedback_status_response');
    }
    deleteFeedback(feedbackId) {
      return this.request({ type: 'delete_feedback', feedback_id: feedbackId },
        'delete_feedback_response', 30000);
    }
    getFeedbackAttachment(feedbackId) {
      return this.request({ type: 'get_feedback_attachment', feedback_id: feedbackId },
        'feedback_attachment_response', 60000);
    }

    // ---------- Remote UI: server-defined screens and whole services ----------
    listRemoteScreens() {
      return this.request({ type: 'list_remote_screens' }, 'list_remote_screens_response');
    }
    openRemoteScreen(slug) {
      return this.request({ type: 'open_remote_screen', slug },
        'open_remote_screen_response', 30000);
    }
    remoteScreenAction(slug, action, values, kind) {
      return this.request({
        type: 'remote_screen_action',
        slug,
        action,
        values: values || {},
        kind: kind || 'submit',
      }, 'remote_screen_action_response', 30000);
    }

    // ---------- Server sounds ----------
    listServerSounds() {
      return this.request({ type: 'list_server_sounds' }, 'list_server_sounds_response');
    }

    // ---------- Interactive games ----------
    // Creating one can carry megabytes of rule files and audio, so it is
    // given a long timeout of its own.
    createGame(payload) {
      return this.request(Object.assign({ type: 'create_game' }, payload || {}),
        'create_game_response', 300000);
    }
    listGames() {
      return this.request({ type: 'list_games' }, 'list_games_response', 20000);
    }
    getGameAttachment(attachmentId) {
      return this.request(
        { type: 'get_game_attachment', attachment_id: attachmentId },
        'game_attachment_response', 60000);
    }
    // A player speaking into a game. The chunk is 16 kHz mono PCM, base64,
    // exactly as the desktop client sends it.
    gameVoiceChunk(sessionId, audioB64) {
      this.send({ type: 'game_voice_chunk', session_id: sessionId,
                  audio_b64: audioB64 });
    }
    wipeAllGameSessions() {
      return this.request({ type: 'wipe_all_game_sessions' },
        'wipe_all_game_sessions_response', 60000);
    }
    getGame(gameId) {
      return this.request({ type: 'get_game', game_id: gameId }, 'get_game_response', 20000);
    }
    deleteGame(gameId) {
      return this.request({ type: 'delete_game', game_id: gameId },
        'delete_game_response', 20000);
    }
    listGameSessions(gameId) {
      const payload = { type: 'list_game_sessions' };
      if (gameId) payload.game_id = gameId;
      return this.request(payload, 'list_game_sessions_response', 20000);
    }
    startGameSession(gameId, opts) {
      return this.request(
        Object.assign({ type: 'start_game_session', game_id: gameId }, opts || {}),
        'start_game_session_response', 30000);
    }
    joinGameSession(sessionId) {
      return this.request({ type: 'join_game_session', session_id: sessionId },
        'join_game_session_response', 20000);
    }
    leaveGameSession(sessionId) {
      return this.request({ type: 'leave_game_session', session_id: sessionId },
        'leave_game_session_response', 20000);
    }
    getGameSession(sessionId) {
      return this.request({ type: 'get_game_session', session_id: sessionId },
        'get_game_session_response', 20000);
    }
    gamePlayerAction(sessionId, action, payload) {
      return this.request(Object.assign(
        { type: 'game_player_action', session_id: sessionId, action },
        payload || {}
      ), 'game_player_action_response', 30000);
    }
    gameAdvanceTurn(sessionId) {
      return this.request({ type: 'game_advance_turn', session_id: sessionId },
        'game_advance_turn_response', 30000);
    }
    gameEndSession(sessionId) {
      return this.request({ type: 'game_end_session', session_id: sessionId },
        'game_end_session_response', 20000);
    }

    // ---------- Moderation over the socket ----------
    // Deliberately absent: get_all_users. The desktop client reads that
    // list over REST (/api/users/all) and so does this one, through
    // Titan.API.allUsers() — which also works against a server that has
    // not yet been given the reply `type` those frames were missing.
    deleteUser(userId) {
      return this.request({ type: 'delete_user', user_id: userId },
        'delete_user_response', 20000);
    }
    hardBanUser(userId, reason) {
      return this.request({ type: 'hard_ban_user', user_id: userId, reason: reason || '' },
        'hard_ban_response', 20000);
    }
    sendBroadcast(payload) {
      return this.request(Object.assign({ type: 'send_broadcast' }, payload || {}),
        'broadcast_response', 30000);
    }
    listBroadcastFiles() {
      return this.request({ type: 'list_broadcast_files' },
        'broadcast_files_response', 20000);
    }
    getBroadcastFile(name) {
      return this.request({ type: 'get_broadcast_file', filename: name },
        'broadcast_file_response', 20000);
    }
    saveBroadcastFile(name, content) {
      return this.request({ type: 'save_broadcast_file', filename: name, content },
        'save_broadcast_file_response', 20000);
    }

    // ---------- Cerberus / Blackwall ----------
    // The reply types here are the server's own and deliberately do not all
    // end in _response — they are named after what came back, not after the
    // request.
    cerberusStatus() {
      return this.request({ type: 'cerberus_status' }, 'cerberus_status', 30000);
    }
    cerberusLogs(maxLines) {
      return this.request({ type: 'cerberus_logs', max_lines: maxLines || 200 },
        'cerberus_logs', 30000);
    }
    cerberusBanIp(ip, permanent) {
      return this.request(
        { type: 'cerberus_ban_ip', ip, permanent: permanent !== false },
        'cerberus_ban_response', 30000);
    }
    cerberusUnbanIp(ip) {
      return this.request({ type: 'cerberus_unban_ip', ip },
        'cerberus_unban_response', 30000);
    }
    cerberusWhitelist(ip, action) {
      return this.request({ type: 'cerberus_whitelist', ip, action: action || 'add' },
        'cerberus_whitelist_response', 30000);
    }
    // "Lockdown" raises the protocol's own level; "unlock" stands it down.
    cerberusLockdown(level, reason) {
      return this.request(
        { type: 'cerberus_lockdown', level: level || 'lockdown', reason: reason || '' },
        'cerberus_activate_response', 30000);
    }
    cerberusUnlock(reason) {
      return this.request({ type: 'cerberus_unlock', reason: reason || '' },
        'cerberus_deactivate_response', 30000);
    }
    cerberusClearLogs() {
      return this.request({ type: 'cerberus_clear_logs' },
        'cerberus_clear_logs_response', 30000);
    }
    cerberusAiAssessment() {
      return this.request({ type: 'cerberus_ai_assessment' },
        'cerberus_ai_assessment', 180000);
    }
    blackwallDeliberate() {
      return this.request({ type: 'blackwall_deliberate' },
        'blackwall_deliberation', 180000);
    }

    // ---------- Push to talk ----------
    pttStart(roomId) { this.send({ type: 'ptt_start', room_id: roomId }); }
    pttStop(roomId) { this.send({ type: 'ptt_stop', room_id: roomId }); }
  }

  window.Titan = window.Titan || {};
  window.Titan.WS = TitanWS;
})();
