// Titan-Net chat — rooms, online users, messages, MOTD modal, voice
(function () {
  'use strict';
  const t = Titan.t;

  const $status = document.getElementById('conn-status');
  const $rooms = document.getElementById('rooms-list');
  const $users = document.getElementById('users-list');
  const $log = document.getElementById('chat-log');
  const $form = document.getElementById('chat-form');
  const $input = document.getElementById('chat-input');
  const $headerH2 = document.getElementById('chat-area-heading');
  const $voiceControls = document.getElementById('voice-controls');
  const $voiceToggle = document.getElementById('voice-toggle');
  const $voiceStatus = document.getElementById('voice-status');

  const $motdDialog = document.getElementById('motd-dialog');
  const $motdText = document.getElementById('motd-text');
  const $motdOk = document.getElementById('motd-ok');

  const SEEN_MOTD_KEY = 'titan.motd_hash';

  let ws = null;
  let voice = null;
  let currentRoomId = null;
  let currentRoom = null;
  let rooms = [];
  let userId = 0;

  // Require login
  const user = Titan.getUser();
  const session = JSON.parse(localStorage.getItem('titan.session') || 'null');
  if (!user) {
    location.href = 'login.html';
    return;
  }
  userId = user.id;

  function showMotdIfNew(motd) {
    if (!motd || !motd.text) return;
    const seen = localStorage.getItem(SEEN_MOTD_KEY);
    if (seen && motd.hash && seen === motd.hash) return;
    $motdText.value = motd.text;
    if (motd.hash) localStorage.setItem(SEEN_MOTD_KEY, motd.hash);
    if (typeof $motdDialog.showModal === 'function') {
      $motdDialog.showModal();
    } else {
      $motdDialog.setAttribute('open', '');
    }
    if (window.Titan && Titan.sounds) Titan.sounds.play('motd');
    setTimeout(() => { try { $motdOk.focus(); } catch (e) {} }, 50);
  }

  function setStatus(key) {
    $status.textContent = t(key);
  }

  function isRoomLocked(room) {
    // Server returns chat_rooms.password_hash verbatim — non-empty means
    // the room is password-protected. Cover a couple of plausible alias
    // names too in case the API ever renames the field.
    return !!(room && (room.password_hash || room.password_protected || room.has_password));
  }

  function renderRooms() {
    $rooms.innerHTML = '';
    rooms.forEach((room) => {
      const li = document.createElement('li');
      const btn = document.createElement('button');
      btn.type = 'button';
      const locked = isRoomLocked(room);
      btn.textContent = locked ? (room.name + ' 🔒') : room.name;
      if (locked) {
        // Screen readers should still get a clean, translatable label.
        btn.setAttribute('aria-label', t('rooms.locked_label', room.name));
      }
      btn.setAttribute('aria-pressed', currentRoomId === room.id ? 'true' : 'false');
      btn.addEventListener('click', () => selectRoom(room.id));
      li.appendChild(btn);
      $rooms.appendChild(li);
    });
  }

  function renderUsers(users) {
    users = users || [];
    $users.innerHTML = '';
    // Update the section heading + list label so screen readers hear the
    // current online count instead of just "Online users".
    const $usersHeading = document.getElementById('users-heading');
    if ($usersHeading) {
      $usersHeading.textContent = t('chat.users.count', users.length);
    }
    $users.setAttribute('aria-label', t('chat.users.count', users.length));
    users.forEach((u, idx) => {
      const li = document.createElement('li');
      const name = u.username || u.name || '?';
      const uid = u.id || u.user_id || null;
      // Use a button so the entry is reachable by Tab, activatable with
      // Enter/Space, and announced as a control by screen readers.
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'user-item';
      btn.setAttribute('aria-label',
        t('chat.users.item', name, idx + 1, users.length));
      // Title doubles as a tooltip + redundant action hint
      btn.title = t('pm.start_with', name);
      const dot = document.createElement('span');
      dot.className = 'status-dot';
      dot.setAttribute('aria-hidden', 'true');
      btn.appendChild(dot);
      btn.appendChild(document.createTextNode(name));
      if (uid && uid !== userId) {
        btn.addEventListener('click', () => openPmDialog(uid, name));
      } else {
        btn.disabled = true;
      }
      li.appendChild(btn);
      $users.appendChild(li);
    });
  }

  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function appendMessage(msg, opts) {
    opts = opts || {};
    const div = document.createElement('div');
    div.className = 'chat-msg' + (opts.own ? ' own' : '') + (opts.system ? ' system' : '');
    const meta = document.createElement('p');
    meta.className = 'msg-meta';
    const author = document.createElement('span');
    author.className = 'msg-author';
    author.textContent = msg.username || (opts.system ? t('chat.system') : '?');
    meta.appendChild(author);
    if (msg.sent_at) {
      const time = document.createElement('time');
      time.textContent = ' · ' + (new Date(msg.sent_at)).toLocaleTimeString();
      time.setAttribute('datetime', msg.sent_at);
      meta.appendChild(time);
    }
    div.appendChild(meta);
    const body = document.createElement('div');
    body.innerHTML = escapeHtml(msg.message || msg.content || '').replace(/\n/g, '<br>');
    div.appendChild(body);
    $log.appendChild(div);
    $log.scrollTop = $log.scrollHeight;
  }

  function clearLog() {
    $log.innerHTML = '';
  }

  // Cache passwords the user entered this session so switching back into a
  // protected room doesn't re-prompt every time. Per-tab only — never
  // persisted to localStorage.
  const roomPasswords = {};

  async function selectRoom(roomId) {
    if (currentRoomId === roomId) return;
    const room = rooms.find((r) => r.id === roomId);
    // Password-protected rooms — ask before we even leave the current one,
    // so a cancel keeps the user where they were.
    if (room && isRoomLocked(room) && !roomPasswords[roomId]) {
      const pwd = await promptRoomPassword(room);
      if (pwd === null) return; // user cancelled
      roomPasswords[roomId] = pwd;
    }
    if (currentRoomId !== null) {
      try { ws.leaveRoom(currentRoomId); } catch (e) {}
      // Stop voice when switching rooms
      if (voice && voice.live) voice.stop();
    }
    currentRoomId = roomId;
    currentRoom = room;
    renderRooms();
    clearLog();
    if (currentRoom) {
      $headerH2.textContent = currentRoom.name;
      $headerH2.classList.remove('muted');
    }
    $form.hidden = false;
    $voiceControls.hidden = false;
    if (voice) {
      voice.setRoom(roomId);
      $voiceStatus.textContent = '';
      $voiceToggle.setAttribute('aria-pressed', 'false');
      $voiceToggle.querySelector('span').textContent = t('voice.start');
    }
    ws.joinRoom(roomId, roomPasswords[roomId]);
    try {
      const resp = await ws.getRoomMessages(roomId, 50);
      (resp.messages || []).forEach((m) => appendMessage(m, { own: m.user_id === userId }));
    } catch (e) { /* ignore */ }
    $input.focus();
  }

  // ---- Room password dialog ----
  const $rpDialog = document.getElementById('room-password-dialog');
  const $rpForm = document.getElementById('room-password-form');
  const $rpPwd = document.getElementById('rp-password');
  const $rpName = document.getElementById('rp-room-name');
  const $rpError = document.getElementById('rp-error');
  const $rpCancel = document.getElementById('rp-cancel');

  let rpResolve = null;
  function promptRoomPassword(room, errorMessage) {
    return new Promise((resolve) => {
      rpResolve = resolve;
      $rpName.textContent = room.name || '';
      $rpPwd.value = '';
      if (errorMessage) {
        $rpError.textContent = errorMessage;
        $rpError.hidden = false;
      } else {
        $rpError.hidden = true;
        $rpError.textContent = '';
      }
      if (typeof $rpDialog.showModal === 'function') $rpDialog.showModal();
      else $rpDialog.setAttribute('open', '');
      setTimeout(() => { try { $rpPwd.focus(); } catch (e) {} }, 50);
    });
  }
  function closeRoomPasswordDialog(value) {
    if ($rpDialog.close) $rpDialog.close();
    else $rpDialog.removeAttribute('open');
    if (rpResolve) {
      const r = rpResolve;
      rpResolve = null;
      r(value);
    }
  }
  if ($rpForm) {
    $rpForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const v = $rpPwd.value;
      if (!v) {
        $rpError.textContent = t('err.required');
        $rpError.hidden = false;
        return;
      }
      closeRoomPasswordDialog(v);
    });
  }
  if ($rpCancel) {
    $rpCancel.addEventListener('click', () => closeRoomPasswordDialog(null));
  }

  function connect() {
    ws = new Titan.WS();
    voice = new Titan.VoiceClient(ws);
    voice.setUser(userId);

    // NOTE: do NOT fetch rooms/users on `open` — the server doesn't know
    // who we are until WS login finishes. bootstrap() does the fetch after
    // a successful login (and on every reconnect-after-login).
    ws.addEventListener('open', () => setStatus('chat.connected'));
    ws.addEventListener('close', () => setStatus('chat.disconnected'));
    ws.addEventListener('ws-error', () => setStatus('chat.disconnected'));

    ws.addEventListener('msg:room_message', (e) => {
      const m = e.detail;
      if (m.room_id === currentRoomId) {
        appendMessage(m, { own: m.user_id === userId });
        // Speak everyone else's messages in the current room
        if (m.user_id !== userId) {
          Titan.sounds && Titan.sounds.play('chat_message');
          Titan.tts.announceMessage(m.username || '?', m.message || '');
        }
      } else {
        // Background notification — name of the room with new traffic
        const roomName = (rooms.find((r) => r.id === m.room_id) || {}).name || '';
        Titan.announce(t('chat.new_message_from', roomName));
        if (m.user_id !== userId) {
          Titan.sounds && Titan.sounds.play('chat_message');
          Titan.tts.announceMessage(m.username || '?', m.message || '');
        }
      }
    });

    ws.addEventListener('msg:private_message', (e) => {
      const m = e.detail;
      Titan.sounds && Titan.sounds.play('private_message');
      Titan.tts.announcePrivate(m.username || m.from_username || '?', m.message || '');
    });

    ws.addEventListener('msg:online_users', (e) => {
      renderUsers(e.detail.users || e.detail.online_users || []);
    });
    ws.addEventListener('msg:user_online', (e) => {
      if (e.detail && e.detail.username) {
        Titan.sounds && Titan.sounds.play('user_online');
        Titan.tts.announceUserOnline(e.detail.username);
      }
      ws.getOnlineUsers().catch(() => {});
    });
    ws.addEventListener('msg:user_offline', (e) => {
      if (e.detail && e.detail.username) {
        Titan.sounds && Titan.sounds.play('user_offline');
        Titan.tts.announceUserOffline(e.detail.username);
      }
      ws.getOnlineUsers().catch(() => {});
    });
    ws.addEventListener('msg:voice_started', (e) => {
      if (e.detail && e.detail.username && e.detail.user_id !== userId) {
        Titan.sounds && Titan.sounds.play('voice_start');
        Titan.tts.announceVoiceStart(e.detail.username);
      }
    });
    ws.addEventListener('msg:rooms_list', (e) => {
      rooms = e.detail.rooms || [];
      renderRooms();
    });
    // Server replies to every join_room with a room_joined frame. On
    // success we already have a working session; on failure (bad/missing
    // room password, ban, etc.) we have to undo the optimistic "I'm in
    // the room now" state we set in selectRoom and, for password errors,
    // re-prompt the user. The "Already a member" case is harmless — it
    // means the user is rejoining a room they never left.
    ws.addEventListener('msg:room_joined', async (e) => {
      const detail = e.detail || {};
      if (detail.success || detail.error === 'Already a member') return;
      const rid = detail.room_id;
      const errMsg = detail.error || '';
      const isPwdError = /password/i.test(errMsg);
      if (rid != null) {
        // Forget the cached password so we re-prompt next time
        if (isPwdError) delete roomPasswords[rid];
      }
      // Roll back the optimistic UI from selectRoom
      currentRoomId = null;
      currentRoom = null;
      renderRooms();
      $headerH2.textContent = t('chat.no_room');
      $headerH2.classList.add('muted');
      $form.hidden = true;
      $voiceControls.hidden = true;
      clearLog();

      if (isPwdError && rid != null) {
        const room = rooms.find((r) => r.id === rid);
        if (room) {
          const pwd = await promptRoomPassword(room, t('rooms.password.bad'));
          if (pwd !== null) {
            roomPasswords[rid] = pwd;
            // Retry — selectRoom will pick the cached password up
            selectRoom(rid);
          }
          return;
        }
      }
      Titan.announce(errMsg || t('err.generic'));
    });

    setStatus('chat.connecting');
    ws.connect();
  }

  // The desktop client keeps the WS open after login; the browser does too,
  // so this page expects to land here directly from login.html where the
  // session was just established. We persist a one-shot relogin by stashing
  // the password ONLY in sessionStorage (not localStorage) and clearing it
  // immediately after use.
  // For initial deployment we simply require browser users to log in once
  // per page-load. The chat session lives as long as this tab is open.
  async function refreshRooms() {
    const $roomsStatus = document.getElementById('rooms-status');
    try {
      const list = await ws.getRooms();
      rooms = list.rooms || [];
      renderRooms();
      if ($roomsStatus) {
        $roomsStatus.textContent = rooms.length ? '' : t('rooms.empty');
      }
    } catch (e) {
      if ($roomsStatus) $roomsStatus.textContent = e.message || t('err.generic');
    }
  }

  async function refreshUsers() {
    try {
      const online = await ws.getOnlineUsers();
      renderUsers(online.users || online.online_users || []);
    } catch (e) { /* ignore */ }
  }

  async function bootstrap() {
    // chat.html needs a fresh server-side WS session. login.html stashed
    // the one-shot credentials in sessionStorage (per-tab only). We use
    // them once to re-login and immediately discard them. As a fallback,
    // if the user ticked "Remember me" we can also re-login from the
    // remember-me blob so refreshing chat.html doesn't bounce them back
    // to the login page.
    let credentials = null;
    const onceLogin = sessionStorage.getItem('titan.once_login');
    if (onceLogin) {
      sessionStorage.removeItem('titan.once_login');
      try { credentials = JSON.parse(onceLogin); } catch (e) {}
    }
    if (!credentials) {
      try {
        const rememberRaw = localStorage.getItem('titan.remember');
        if (rememberRaw) {
          const r = JSON.parse(rememberRaw);
          if (r && r.b) {
            credentials = JSON.parse(decodeURIComponent(escape(atob(r.b))));
          }
        }
      } catch (e) {}
    }
    if (!credentials || !credentials.username) {
      location.href = 'login.html?return=chat';
      return;
    }
    const { username, password } = credentials;
    connect();
    ws.addEventListener('open', async () => {
      try {
        const resp = await ws.login(username, password);
        if (!resp.success) {
          location.href = 'login.html';
          return;
        }
        if (resp.motd) showMotdIfNew(resp.motd);
        await refreshRooms();
        await refreshUsers();
      } catch (e) {
        location.href = 'login.html';
      }
    }, { once: true });
  }

  $form.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = $input.value.trim();
    if (!text || currentRoomId == null) return;
    ws.sendRoomMessage(currentRoomId, text);
    Titan.sounds && Titan.sounds.play('message_sent');
    $input.value = '';
  });

  $voiceToggle.addEventListener('click', async () => {
    if (!voice) return;
    try {
      if (voice.live) {
        voice.stop();
        $voiceToggle.setAttribute('aria-pressed', 'false');
        $voiceToggle.querySelector('span').textContent = t('voice.start');
        $voiceStatus.textContent = t('voice.off');
      } else {
        $voiceStatus.textContent = t('voice.connecting');
        await voice.start();
        $voiceToggle.setAttribute('aria-pressed', 'true');
        $voiceToggle.querySelector('span').textContent = t('voice.stop');
        $voiceStatus.textContent = t('voice.live');
      }
    } catch (e) {
      $voiceStatus.textContent = e.message || t('err.generic');
      Titan.announce($voiceStatus.textContent);
    }
  });

  $motdOk.addEventListener('click', (e) => {
    e.preventDefault();
    if ($motdDialog.close) $motdDialog.close(); else $motdDialog.removeAttribute('open');
  });

  // Sound and TTS preferences are managed exclusively on settings.html.
  // sounds.js / tts.js read from localStorage on every page load, and the
  // 'storage' listeners inside those modules pick up cross-tab changes
  // automatically — no per-page UI controls needed here.

  // ---- Create room ----
  const $newRoomBtn = document.getElementById('new-room-btn');
  const $newRoomDlg = document.getElementById('new-room-dialog');
  const $newRoomForm = document.getElementById('new-room-form');
  const $nrCancel = document.getElementById('nr-cancel');
  const $nrName = document.getElementById('nr-name');
  const $nrDesc = document.getElementById('nr-desc');
  const $nrPassword = document.getElementById('nr-password');
  const $nrError = document.getElementById('nr-error');
  const $nrSubmit = document.getElementById('nr-submit');

  function openNewRoomDialog() {
    $nrError.hidden = true;
    $nrName.value = '';
    $nrDesc.value = '';
    $nrPassword.value = '';
    const textRadio = document.querySelector('input[name="nr-type"][value="text"]');
    if (textRadio) textRadio.checked = true;
    if (typeof $newRoomDlg.showModal === 'function') $newRoomDlg.showModal();
    else $newRoomDlg.setAttribute('open', '');
    setTimeout(() => { try { $nrName.focus(); } catch (e) {} }, 50);
  }
  function closeNewRoomDialog() {
    if ($newRoomDlg.close) $newRoomDlg.close();
    else $newRoomDlg.removeAttribute('open');
  }

  $newRoomBtn.addEventListener('click', openNewRoomDialog);
  $nrCancel.addEventListener('click', closeNewRoomDialog);
  $newRoomForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = $nrName.value.trim();
    const desc = $nrDesc.value.trim();
    const password = $nrPassword.value;  // do not trim — leading/trailing space allowed
    const typeRadio = document.querySelector('input[name="nr-type"]:checked');
    const roomType = typeRadio ? typeRadio.value : 'text';
    if (!name) {
      $nrError.textContent = t('err.required');
      $nrError.hidden = false;
      $nrName.focus();
      return;
    }
    $nrSubmit.disabled = true;
    try {
      const resp = await ws.createRoom(name, desc, roomType, password || '');
      if (resp && resp.success) {
        closeNewRoomDialog();
        Titan.sounds && Titan.sounds.play('success');
        Titan.announce(t('rooms.created'));
        Titan.tts.announceSystem(t('rooms.created'));
        await refreshRooms();
        // Auto-select the newly created room
        if (resp.room_id != null) {
          selectRoom(resp.room_id);
        }
      } else {
        const err = (resp && (resp.error || resp.message)) || t('rooms.create_failed');
        $nrError.textContent = err;
        $nrError.hidden = false;
      }
    } catch (err) {
      $nrError.textContent = err.message || t('rooms.create_failed');
      $nrError.hidden = false;
    } finally {
      $nrSubmit.disabled = false;
    }
  });

  // The server broadcasts `room_created` to everyone on the WS so other
  // browsers see new rooms appear without a manual refresh.
  // (Our request() handler already consumes the first `room_created`; a
  // duplicate broadcast just triggers a free refresh.)
  // For belt-and-braces also refresh when we see a room_deleted.
  // (Listeners registered on `ws` are added after connect() in bootstrap.)
  window.addEventListener('titan:session-changed', () => { /* noop */ });

  // ============== Private message dialog ==============
  const $pmDialog = document.getElementById('pm-dialog');
  const $pmWith = document.getElementById('pm-with');
  const $pmLog = document.getElementById('pm-log');
  const $pmInput = document.getElementById('pm-input');
  const $pmSend = document.getElementById('pm-send');
  const $pmClose = document.getElementById('pm-close');
  let pmPartnerId = null;
  let pmPartnerName = null;

  function pmAppend(authorName, body, own) {
    const div = document.createElement('div');
    div.className = 'chat-msg' + (own ? ' own' : '');
    const meta = document.createElement('p');
    meta.className = 'msg-meta';
    const author = document.createElement('span');
    author.className = 'msg-author';
    author.textContent = authorName || '?';
    meta.appendChild(author);
    div.appendChild(meta);
    const txt = document.createElement('div');
    txt.innerHTML = escapeHtml(body || '').replace(/\n/g, '<br>');
    div.appendChild(txt);
    $pmLog.appendChild(div);
    $pmLog.scrollTop = $pmLog.scrollHeight;
  }

  async function openPmDialog(otherUserId, otherUsername) {
    pmPartnerId = otherUserId;
    pmPartnerName = otherUsername;
    $pmWith.textContent = otherUsername;
    $pmLog.innerHTML = '';
    Titan.sounds && Titan.sounds.play('new_chat');
    if (typeof $pmDialog.showModal === 'function') $pmDialog.showModal();
    else $pmDialog.setAttribute('open', '');
    try {
      const resp = await ws.getPrivateMessages(otherUserId, 100);
      (resp.messages || []).forEach((m) => {
        const own = (m.sender_id === userId);
        const author = own ? (Titan.getUser().username || t('chat.system'))
                           : (m.sender_username || otherUsername);
        pmAppend(author, m.message || m.content || '', own);
      });
      // Mark this thread as read on the server
      try { await ws.markMessagesRead(otherUserId); } catch (e) {}
    } catch (e) { /* ignore — show empty conversation */ }
    setTimeout(() => { try { $pmInput.focus(); } catch (e) {} }, 50);
  }

  function closePmDialog() {
    if ($pmDialog.close) $pmDialog.close(); else $pmDialog.removeAttribute('open');
    pmPartnerId = null;
    pmPartnerName = null;
  }

  $pmClose.addEventListener('click', closePmDialog);
  $pmSend.addEventListener('click', () => {
    const text = $pmInput.value.trim();
    if (!text || !pmPartnerId) return;
    ws.sendPrivateMessage(pmPartnerId, text);
    pmAppend(Titan.getUser().username || t('chat.system'), text, true);
    Titan.sounds && Titan.sounds.play('message_sent');
    $pmInput.value = '';
    $pmInput.focus();
  });
  $pmInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      $pmSend.click();
    }
  });

  // When a new PM arrives while the dialog is open with that partner,
  // append it live; otherwise the global TTS + sound + notification flow
  // already alerts the user.
  // (Listener registered after WS is connected — see attachBroadcastListeners.)

  // ============== What's new dialog ==============
  const $wnBtn = document.getElementById('whatsnew-btn');
  const $wnDialog = document.getElementById('whatsnew-dialog');
  const $wnBody = document.getElementById('wn-body');
  const $wnEmpty = document.getElementById('wn-empty');

  function wnSection(titleKey, items, renderItem) {
    if (!items || items.length === 0) return null;
    const sec = document.createElement('section');
    sec.style.marginBottom = '.75rem';
    const h3 = document.createElement('h3');
    h3.textContent = t(titleKey) + ' (' + items.length + ')';
    h3.style.margin = '0 0 .25rem 0';
    sec.appendChild(h3);
    const ul = document.createElement('ul');
    ul.className = 'list-box';
    items.forEach((it) => {
      const li = document.createElement('li');
      renderItem(li, it);
      ul.appendChild(li);
    });
    sec.appendChild(ul);
    return sec;
  }

  async function openWhatsNewDialog() {
    $wnBody.innerHTML = '';
    $wnEmpty.hidden = true;
    const loading = document.createElement('p');
    loading.className = 'muted';
    loading.textContent = t('whatsnew.loading');
    $wnBody.appendChild(loading);
    if (typeof $wnDialog.showModal === 'function') $wnDialog.showModal();
    else $wnDialog.setAttribute('open', '');
    try {
      const data = await Titan.API.whatsNew();
      $wnBody.innerHTML = '';
      const sections = [];
      const pmItems = (data.unread_messages_items || []).map((m) => ({
        label: t('whatsnew.from_user', m.sender, m.count),
        sender_id: m.sender_id, sender: m.sender,
      }));
      const pmSec = wnSection('whatsnew.section.messages', pmItems, (li, it) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-secondary';
        btn.textContent = it.label;
        btn.addEventListener('click', () => {
          closeWhatsNewDialog();
          openPmDialog(it.sender_id, it.sender);
        });
        li.appendChild(btn);
      });
      if (pmSec) sections.push(pmSec);

      const topicItems = (data.unread_forum_topics_items || []).map((t) => ({
        label: window.Titan.t('whatsnew.topic_replies', t.title, t.new_replies),
        id: t.id,
      }));
      const topicSec = wnSection('whatsnew.section.forum', topicItems, (li, it) => {
        const a = document.createElement('a');
        a.href = 'forum.html#topic-' + it.id;
        a.textContent = it.label;
        li.appendChild(a);
      });
      if (topicSec) sections.push(topicSec);

      const newAppItems = (data.new_apps_items || []).map((a) => ({
        label: t('whatsnew.app_line', a.name, a.version, a.author),
        id: a.id,
      }));
      const newAppSec = wnSection('whatsnew.section.new_apps', newAppItems, (li, it) => {
        const a = document.createElement('a');
        a.href = 'repository.html';
        a.textContent = it.label;
        li.appendChild(a);
      });
      if (newAppSec) sections.push(newAppSec);

      const updItems = (data.app_updates_items || []).map((a) => ({
        label: t('whatsnew.app_line', a.name, a.version, a.author),
        id: a.id,
      }));
      const updSec = wnSection('whatsnew.section.app_updates', updItems, (li, it) => {
        const a = document.createElement('a');
        a.href = 'repository.html';
        a.textContent = it.label;
        li.appendChild(a);
      });
      if (updSec) sections.push(updSec);

      if (sections.length === 0) {
        $wnEmpty.hidden = false;
      } else {
        sections.forEach((s) => $wnBody.appendChild(s));
      }
    } catch (e) {
      $wnBody.innerHTML = '';
      const err = document.createElement('p');
      err.className = 'field-error';
      err.textContent = e.message || t('err.generic');
      $wnBody.appendChild(err);
    }
  }
  function closeWhatsNewDialog() {
    if ($wnDialog.close) $wnDialog.close(); else $wnDialog.removeAttribute('open');
  }
  if ($wnBtn) $wnBtn.addEventListener('click', openWhatsNewDialog);

  bootstrap();
  // After connect() creates `ws`, attach broadcast listeners.
  function attachBroadcastListeners() {
    if (!ws) { setTimeout(attachBroadcastListeners, 100); return; }
    ws.addEventListener('msg:room_created', () => refreshRooms().catch(() => {}));
    ws.addEventListener('msg:room_deleted', () => refreshRooms().catch(() => {}));
    // Live-append incoming PMs when the dialog is open with the same sender
    ws.addEventListener('msg:private_message', (e) => {
      const m = e.detail || {};
      const senderId = m.sender_id || m.from_user_id || m.user_id;
      if (pmPartnerId && senderId === pmPartnerId) {
        pmAppend(m.username || m.from_username || pmPartnerName || '?',
                 m.message || m.content || '', false);
        // Don't double-mark as read on every message - the next dialog open
        // does the bulk mark. But mark this one to keep counts current.
        try { ws.markMessagesRead(senderId); } catch (err) {}
      }
    });
  }
  attachBroadcastListeners();
})();
