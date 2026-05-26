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
    listTopics(category, limit) {
      const q = new URLSearchParams();
      if (category) q.set('category', category);
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
    createTopic(title, content, category) {
      return request('/forum/topics', {
        method: 'POST',
        body: { title, content, category: category || 'general' },
      });
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

    // Account
    getRole() { return request('/users/role'); },
    whatsNew() { return request('/whats_new'); },
  };

  window.Titan = window.Titan || {};
  window.Titan.API = API;
})();
