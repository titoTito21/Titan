// Titan-Net REST API client (forum, repository, moderation)
// All URLs are relative — Apache reverse-proxies /api/ to the aiohttp server on :8000.
(function () {
  'use strict';

  const BASE = '/api';

  // A 401 is recoverable, and used not to be.
  //
  // The token these calls carry is minted by a WebSocket login and stored
  // in localStorage, so it outlives the socket that produced it - and it
  // goes stale on its own: a signed token expires after thirty days, and a
  // session stored before the server minted signed tokens at all still
  // holds the old base64("id:username") form, which the server now honours
  // only while its owner ALSO has a live WebSocket session from the same
  // address. Pages made only of REST calls (Mail, Account) open no socket,
  // so for them that token was simply refused, for ever: "Authentication
  // required" on a user who was perfectly well logged in, curable only by
  // logging out and back in - and every refusal was reported to Cerberus
  // as a forged token, scoring the user's own address as an attacker.
  //
  // So one 401 is answered by asking session.js for the tab's logged-in
  // socket, which logs in again and writes the fresh token, and the
  // request is made once more. Only once: a second 401 is a real one.
  async function request(path, opts, retried) {
    opts = opts || {};
    const headers = Object.assign({}, opts.headers || {});
    const token = Titan.getToken();
    if (token && !headers.Authorization) headers.Authorization = 'Bearer ' + token;
    if (opts.body && !(opts.body instanceof FormData) && typeof opts.body !== 'string') {
      opts.body = JSON.stringify(opts.body);
      opts.__json = true;
    }
    // Re-sent on a retry too: the body was serialised in place the first
    // time round, so by then it is a string and would otherwise go back
    // without the header that says what it is.
    if (opts.__json) headers['Content-Type'] = 'application/json';
    let resp;
    try {
      resp = await fetch(BASE + path, Object.assign({}, opts, { headers }));
    } catch (e) {
      throw new Error(Titan.t('err.network'));
    }
    let data = null;
    const ct = resp.headers.get('content-type') || '';
    if (ct.indexOf('application/json') !== -1) {
      try { data = await resp.json(); } catch (e) { data = null; }
    }
    if (resp.status === 401 && !retried && await reauthenticate()) {
      // A body that has already been serialised is a string, and a
      // FormData is replayable, so the same opts can be sent again.
      return request(path, opts, true);
    }
    if (resp.status === 401 && Titan.getUser()) {
      // Logged in as far as this browser knows, and the server disagrees
      // after a fresh login was tried: the session really is gone (the
      // password changed, the account was renamed, the credentials this
      // tab held were never stored). Send them to the login page, which
      // remembers where they were going.
      sessionDead();
    }
    if (!resp.ok) {
      const msg = (data && (data.error || data.message)) || ('HTTP ' + resp.status);
      const err = new Error(msg);
      err.status = resp.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  // Once per page: several calls failing together must not race each other
  // to the login form.
  let leaving = false;
  function sessionDead() {
    if (leaving) return;
    leaving = true;
    if (window.Titan && Titan.session && Titan.session.toLogin) Titan.session.toLogin();
  }

  // Log in again over WebSocket, which mints a fresh token and stores it.
  //
  // Worth retrying on ANY successful login, not only on a token that came
  // back different: a login also gives this address a live WebSocket
  // session, and that on its own is what makes the server accept a legacy
  // token it had just refused. One wasted request is the whole cost of
  // being wrong; `retried` is what stops it happening twice.
  //
  // Shared, so a page whose calls all 401 together produces one login
  // rather than one per call.
  let reauth = null;
  function reauthenticate() {
    if (!window.Titan || !Titan.session || !Titan.session.ws) return Promise.resolve(false);
    if (reauth) return reauth;
    reauth = Titan.session.ws()
      .then(function () { reauth = null; return true; })
      .catch(function () { reauth = null; return false; });
    return reauth;
  }

  const API = {
    // Repository
    listApps(opts) {
      opts = opts || {};
      const q = new URLSearchParams();
      if (opts.status) q.set('status', opts.status);
      if (opts.category) q.set('category', opts.category);
      if (opts.limit) q.set('limit', opts.limit);
      const qs = q.toString();
      return request('/repository/apps' + (qs ? '?' + qs : ''));
    },
    searchApps(query, category) {
      const q = new URLSearchParams({ q: query });
      if (category) q.set('category', category);
      return request('/search?' + q.toString());
    },
    appDownloadUrl(appId) { return BASE + '/download/' + encodeURIComponent(appId); },
    stats() { return request('/stats'); },

    // Forum
    listTopics(category, limit, forumId) {
      const q = new URLSearchParams();
      if (forumId != null) q.set('forum_id', forumId);
      else if (category) q.set('category', category);
      if (limit) q.set('limit', limit);
      const qs = q.toString();
      return request('/forum/topics' + (qs ? '?' + qs : ''));
    },
    getTopic(topicId) {
      return request('/forum/topics/' + encodeURIComponent(topicId));
    },
    listReplies(topicId, limit) {
      const q = new URLSearchParams();
      if (limit) q.set('limit', limit);
      const qs = q.toString();
      return request('/forum/topics/' + encodeURIComponent(topicId) + '/replies' + (qs ? '?' + qs : ''));
    },
    createTopic(title, content, category, forumId) {
      const body = { title, content, category: category || 'general' };
      if (forumId != null) body.forum_id = forumId;
      return request('/forum/topics', { method: 'POST', body });
    },
    addReply(topicId, content) {
      return request('/forum/topics/' + encodeURIComponent(topicId) + '/replies', {
        method: 'POST',
        body: { content },
      });
    },
    searchForum(query, category) {
      const q = new URLSearchParams({ q: query });
      if (category) q.set('category', category);
      return request('/forum/search?' + q.toString());
    },
    myTopics() { return request('/forum/my_topics'); },
    markTopicRead(topicId) {
      return request('/forum/topics/' + encodeURIComponent(topicId) + '/mark_read',
        { method: 'POST' });
    },
    // Moderation of one topic. Each of these is checked again on the
    // server against the caller's role and the forum they moderate.
    pinTopic(topicId, pinned) {
      return request('/forum/topics/' + encodeURIComponent(topicId)
        + (pinned === false ? '/unpin' : '/pin'), { method: 'POST' });
    },
    lockTopic(topicId, locked) {
      return request('/forum/topics/' + encodeURIComponent(topicId)
        + (locked === false ? '/unlock' : '/lock'), { method: 'POST' });
    },
    deleteTopic(topicId) {
      return request('/forum/topics/' + encodeURIComponent(topicId),
        { method: 'DELETE' });
    },
    editReply(replyId, content) {
      return request('/forum/replies/' + encodeURIComponent(replyId),
        { method: 'PUT', body: { content } });
    },
    deleteReply(replyId) {
      return request('/forum/replies/' + encodeURIComponent(replyId),
        { method: 'DELETE' });
    },

    // Groups -> Forums (Elten-style)
    listGroups() { return request('/groups'); },
    getGroup(groupId) { return request('/groups/' + encodeURIComponent(groupId)); },
    createGroup(name, description, visibility, memberLimit) {
      return request('/groups', {
        method: 'POST',
        body: { name, description, visibility: visibility || 'public', member_limit: memberLimit },
      });
    },
    updateGroup(groupId, fields) {
      return request('/groups/' + encodeURIComponent(groupId), { method: 'PUT', body: fields || {} });
    },
    renameGroup(groupId, name) {
      return request('/groups/' + encodeURIComponent(groupId) + '/rename', { method: 'POST', body: { name } });
    },
    deleteGroup(groupId) {
      return request('/groups/' + encodeURIComponent(groupId), { method: 'DELETE' });
    },
    joinGroup(groupId) {
      return request('/groups/' + encodeURIComponent(groupId) + '/join', { method: 'POST' });
    },
    leaveGroup(groupId) {
      return request('/groups/' + encodeURIComponent(groupId) + '/leave', { method: 'POST' });
    },
    groupMembers(groupId, status) {
      const q = new URLSearchParams();
      if (status) q.set('status', status);
      const qs = q.toString();
      return request('/groups/' + encodeURIComponent(groupId) + '/members' + (qs ? '?' + qs : ''));
    },
    approveMember(groupId, userId) {
      return request('/groups/' + encodeURIComponent(groupId) + '/members/' + encodeURIComponent(userId) + '/approve', { method: 'POST' });
    },
    rejectMember(groupId, userId) {
      return request('/groups/' + encodeURIComponent(groupId) + '/members/' + encodeURIComponent(userId) + '/reject', { method: 'POST' });
    },
    setGroupModerator(groupId, userId, makeModerator) {
      return request('/groups/' + encodeURIComponent(groupId) + '/moderators/' + encodeURIComponent(userId), {
        method: 'POST', body: { make_moderator: makeModerator !== false },
      });
    },
    transferGroupOwnership(groupId, userId) {
      return request('/groups/' + encodeURIComponent(groupId) + '/transfer/' + encodeURIComponent(userId), { method: 'POST' });
    },
    banFromGroup(groupId, userId, reason) {
      return request('/groups/' + encodeURIComponent(groupId) + '/ban/' + encodeURIComponent(userId), {
        method: 'POST', body: { reason: reason || null },
      });
    },
    unbanFromGroup(groupId, userId) {
      return request('/groups/' + encodeURIComponent(groupId) + '/unban/' + encodeURIComponent(userId), { method: 'POST' });
    },

    // Account email + password recovery
    getAccountEmail() { return request('/account/email'); },
    setAccountEmail(email) { return request('/account/email', { method: 'POST', body: { email } }); },
    verifyEmail(token) { return request('/account/verify_email', { method: 'POST', body: { token } }); },
    forgotPassword(identifier) { return request('/auth/forgot_password', { method: 'POST', body: { identifier } }); },
    resetPassword(token, newPassword) {
      return request('/auth/reset_password', { method: 'POST', body: { token, new_password: newPassword } });
    },

    // User mailbox
    mailbox(folder) { return request('/mail/' + (folder === 'sent' ? 'sent' : 'inbox')); },
    getMail(mailId) { return request('/mail/' + encodeURIComponent(mailId)); },
    deleteMail(mailId) { return request('/mail/' + encodeURIComponent(mailId), { method: 'DELETE' }); },
    // `body` is always the readable plain text; `bodyHtml` is the formatted
    // alternative sent beside it (multipart/alternative on the way out).
    sendMail(to, subject, body, bodyHtml, contentType) {
      const payload = { to, subject, body, content_type: contentType || 'text/plain' };
      if (bodyHtml) payload.body_html = bodyHtml;
      return request('/mail/send', { method: 'POST', body: payload });
    },
    listGroupForums(groupId) {
      return request('/groups/' + encodeURIComponent(groupId) + '/forums');
    },
    createGroupForum(groupId, name, description) {
      return request('/groups/' + encodeURIComponent(groupId) + '/forums', {
        method: 'POST', body: { name, description },
      });
    },
    deleteGroupForum(forumId) {
      return request('/forums/' + encodeURIComponent(forumId), { method: 'DELETE' });
    },
    moveTopicToForum(topicId, forumId) {
      return request('/forum/topics/' + encodeURIComponent(topicId) + '/move', {
        method: 'POST', body: { forum_id: forumId },
      });
    },
    listMoveRequests() { return request('/forum/move_requests'); },
    approveMoveRequest(requestId) {
      return request('/forum/move_requests/' + encodeURIComponent(requestId) + '/approve', { method: 'POST' });
    },
    rejectMoveRequest(requestId) {
      return request('/forum/move_requests/' + encodeURIComponent(requestId) + '/reject', { method: 'POST' });
    },

    // Extensions (moderator add-ons + two-person approval)
    listExtensions(status) {
      const q = new URLSearchParams();
      if (status) q.set('status', status);
      const qs = q.toString();
      return request('/extensions' + (qs ? '?' + qs : ''));
    },
    getExtension(extId) { return request('/extensions/' + encodeURIComponent(extId)); },
    submitExtension(slug, name, clientCode, description, version) {
      return request('/extensions', {
        method: 'POST',
        body: { slug, name, client_code: clientCode, description, version: version || '1.0' },
      });
    },
    approveExtension(extId, note) {
      return request('/extensions/' + encodeURIComponent(extId) + '/approve', { method: 'POST', body: { note } });
    },
    rejectExtension(extId, note) {
      return request('/extensions/' + encodeURIComponent(extId) + '/reject', { method: 'POST', body: { note } });
    },

    // Account
    getRole() { return request('/users/role'); },
    whatsNew() { return request('/whats_new'); },

    // ---------- Repository: uploading ----------
    // Multipart, so the browser streams the file rather than turning a
    // 200 MB package into a base64 string in memory first. `onProgress` is
    // given (loaded, total) so the page can drive a real progress bar with
    // an accessible value, not a spinner that says nothing.
    uploadPackage(file, metadata, onProgress) {
      return new Promise(function (resolve, reject) {
        const form = new FormData();
        form.append('metadata', JSON.stringify(metadata));
        form.append('file', file, file.name);
        const xhr = new XMLHttpRequest();
        xhr.open('POST', BASE + '/repository/upload');
        const token = Titan.getToken();
        if (token) xhr.setRequestHeader('Authorization', 'Bearer ' + token);
        if (onProgress && xhr.upload) {
          xhr.upload.addEventListener('progress', function (e) {
            if (e.lengthComputable) onProgress(e.loaded, e.total);
          });
        }
        xhr.addEventListener('load', function () {
          let data = null;
          try { data = JSON.parse(xhr.responseText); } catch (e) {}
          if (xhr.status >= 200 && xhr.status < 300 && data && data.success !== false) {
            resolve(data);
          } else {
            const err = new Error((data && data.error) || ('HTTP ' + xhr.status));
            err.status = xhr.status;
            reject(err);
          }
        });
        xhr.addEventListener('error', function () { reject(new Error(Titan.t('err.network'))); });
        xhr.addEventListener('abort', function () { reject(new Error(Titan.t('err.network'))); });
        xhr.send(form);
      });
    },
    pendingApps() { return request('/repository/apps/pending'); },
    approveApp(appId) {
      return request('/repository/apps/' + encodeURIComponent(appId) + '/approve', { method: 'POST' });
    },
    rejectApp(appId, reason) {
      return request('/repository/apps/' + encodeURIComponent(appId) + '/reject', {
        method: 'POST', body: { reason: reason || '' },
      });
    },
    deleteApp(appId) {
      return request('/delete/' + encodeURIComponent(appId), { method: 'DELETE' });
    },

    // ---------- Moderation ----------
    allUsers() { return request('/users/all'); },
    moderators() { return request('/moderation/moderators'); },
    banCheck(userId) { return request('/moderation/ban/check/' + encodeURIComponent(userId)); },
    promote(username, title) {
      return request('/moderation/promote', { method: 'POST', body: { username, title: title || 'Moderator' } });
    },
    demote(username) {
      return request('/moderation/demote', { method: 'POST', body: { username } });
    },
    adminChangePassword(username, newPassword) {
      return request('/moderation/change_password', {
        method: 'POST', body: { username, new_password: newPassword },
      });
    },
    jail(userId, minutes, reason) {
      return request('/moderation/jail', {
        method: 'POST', body: { user_id: userId, minutes: minutes || 0, reason: reason || '' },
      });
    },
    release(userId) {
      return request('/moderation/release', { method: 'POST', body: { user_id: userId } });
    },
    banGlobal(userId, opts) {
      opts = opts || {};
      return request('/moderation/ban/global', {
        method: 'POST',
        body: {
          user_id: userId,
          ban_type: opts.banType || 'permanent',
          duration_hours: opts.durationHours || null,
          reason: opts.reason || '',
        },
      });
    },
    unbanGlobal(userId) {
      return request('/moderation/unban/global', { method: 'POST', body: { user_id: userId } });
    },
    banForum(userId, opts) {
      opts = opts || {};
      return request('/moderation/ban/forum', {
        method: 'POST',
        body: {
          user_id: userId,
          ban_type: opts.banType || 'permanent',
          duration_hours: opts.durationHours || null,
          reason: opts.reason || '',
        },
      });
    },
    unbanForum(userId) {
      return request('/moderation/unban/forum', { method: 'POST', body: { user_id: userId } });
    },
    banRoom(roomId, userId, opts) {
      opts = opts || {};
      return request('/moderation/ban/room', {
        method: 'POST',
        body: {
          room_id: roomId,
          user_id: userId,
          ban_type: opts.banType || 'permanent',
          duration_hours: opts.durationHours || null,
          reason: opts.reason || '',
        },
      });
    },
    unbanRoom(roomId, userId) {
      return request('/moderation/unban/room', {
        method: 'POST', body: { room_id: roomId, user_id: userId },
      });
    },
    banHard(userId, reason) {
      return request('/moderation/ban/hard', {
        method: 'POST', body: { user_id: userId, reason: reason },
      });
    },
    kickFromRoom(roomId, username) {
      return request('/rooms/' + encodeURIComponent(roomId) + '/kick', {
        method: 'POST', body: { username },
      });
    },
    deleteRoomMessage(messageId) {
      return request('/rooms/messages/' + encodeURIComponent(messageId), { method: 'DELETE' });
    },
    moderateDeleteRoom(roomId) {
      return request('/rooms/' + encodeURIComponent(roomId) + '/moderate', { method: 'DELETE' });
    },

    // ---------- Server sounds ----------
    listSounds() { return request('/sounds'); },
    soundUrl(name) { return BASE + '/sounds/' + encodeURIComponent(name); },
    uploadSound(name, filename, base64Content, description) {
      return request('/sounds', {
        method: 'POST',
        body: { name, filename, content: base64Content, description: description || '' },
      });
    },
    playSound(name, target, opts) {
      opts = opts || {};
      return request('/sounds/' + encodeURIComponent(name) + '/play', {
        method: 'POST',
        body: {
          target: target || { type: 'all' },
          volume: opts.volume === undefined ? 1.0 : opts.volume,
          loop: !!opts.loop,
          announce: opts.announce || null,
        },
      });
    },
    deleteSound(name) {
      return request('/sounds/' + encodeURIComponent(name), { method: 'DELETE' });
    },

    // ---------- Remote screens (administration over REST) ----------
    listRemoteScreens() { return request('/remote-screens'); },
    getRemoteScreen(slug) { return request('/remote-screens/' + encodeURIComponent(slug)); },
    pushRemoteScreen(slug, target) {
      return request('/remote-screens/' + encodeURIComponent(slug) + '/push', {
        method: 'POST', body: { target: target || { type: 'all' } },
      });
    },
    // What people have sent through a form screen. A `view` screen keeps
    // nothing — only a form has answers to keep.
    remoteScreenSubmissions(slug) {
      return request('/remote-screens/' + encodeURIComponent(slug) + '/submissions');
    },

    // ---------- Extensions: enabling and disabling an active one ----------
    enableExtension(extId) {
      return request('/extensions/' + encodeURIComponent(extId) + '/enable', { method: 'POST' });
    },
    disableExtension(extId) {
      return request('/extensions/' + encodeURIComponent(extId) + '/disable', { method: 'POST' });
    },
    deleteExtension(extId) {
      return request('/extensions/' + encodeURIComponent(extId), { method: 'DELETE' });
    },
    // An extension's own files — sounds, voices, language data — which the
    // server streams to the clients running it.
    listExtensionAssets(slug) {
      return request('/extensions/' + encodeURIComponent(slug) + '/assets');
    },
    getExtensionAsset(slug, kind, name) {
      return request('/extensions/' + encodeURIComponent(slug)
        + '/asset/' + encodeURIComponent(kind) + '/' + encodeURIComponent(name));
    },
    addExtensionAsset(extId, kind, name, base64Content, mime) {
      return request('/extensions/' + encodeURIComponent(extId) + '/assets', {
        method: 'POST',
        body: { kind, name, content: base64Content, mime: mime || null },
      });
    },
  };

  window.Titan = window.Titan || {};
  window.Titan.API = API;
})();
