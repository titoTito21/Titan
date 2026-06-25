// Titan-Net REST API client (forum, repository, moderation)
// All URLs are relative — Apache reverse-proxies /api/ to the aiohttp server on :8000.
(function () {
  'use strict';

  const BASE = '/api';

  async function request(path, opts) {
    opts = opts || {};
    const headers = Object.assign({}, opts.headers || {});
    const token = Titan.getToken();
    if (token && !headers.Authorization) headers.Authorization = 'Bearer ' + token;
    if (opts.body && !(opts.body instanceof FormData) && typeof opts.body !== 'string') {
      headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(opts.body);
    }
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
    if (!resp.ok) {
      const msg = (data && (data.error || data.message)) || ('HTTP ' + resp.status);
      const err = new Error(msg);
      err.status = resp.status;
      err.data = data;
      throw err;
    }
    return data;
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
  };

  window.Titan = window.Titan || {};
  window.Titan.API = API;
})();
