// Titan-Net web — one logged-in WebSocket for the whole tab.
//
// The server only knows who you are inside a WebSocket session, and a
// session belongs to one socket: every page that talks to it has to log in
// again. Chat used to consume a one-shot credential stashed by the login
// page, which meant the SECOND page to open (feedback, a service, the
// moderation panel) found nothing there and bounced the user back to the
// login form.
//
// So the credentials live in sessionStorage for as long as the tab does —
// the same lifetime the socket has — and `Titan.session.ws()` hands every
// page the same connected, logged-in socket. It is a promise, so twenty
// callers on one page still produce one login.
(function () {
  'use strict';

  const CREDS_KEY = 'titan.creds';
  const ONCE_KEY = 'titan.once_login';
  const REMEMBER_KEY = 'titan.remember';

  let socket = null;
  let pending = null;
  let loginData = null;

  function readOnce() {
    // login.html leaves the credentials here for exactly one page. Promote
    // them into the tab's own store rather than burning them, or only the
    // first page in the tab can reach the server.
    const raw = sessionStorage.getItem(ONCE_KEY);
    if (!raw) return null;
    sessionStorage.removeItem(ONCE_KEY);
    try { return JSON.parse(raw); } catch (e) { return null; }
  }

  function readRemember() {
    try {
      const raw = localStorage.getItem(REMEMBER_KEY);
      if (!raw) return null;
      const blob = JSON.parse(raw);
      if (!blob || !blob.b) return null;
      return JSON.parse(decodeURIComponent(escape(atob(blob.b))));
    } catch (e) { return null; }
  }

  function credentials() {
    let creds = null;
    try {
      const raw = sessionStorage.getItem(CREDS_KEY);
      if (raw) creds = JSON.parse(raw);
    } catch (e) { creds = null; }
    if (!creds || !creds.username) {
      creds = readOnce();
      if (creds && creds.username) saveCredentials(creds.username, creds.password);
    }
    if (!creds || !creds.username) creds = readRemember();
    return (creds && creds.username) ? creds : null;
  }

  function saveCredentials(username, password) {
    try {
      sessionStorage.setItem(CREDS_KEY, JSON.stringify({ username: username, password: password }));
    } catch (e) {}
  }

  function forget() {
    try { sessionStorage.removeItem(CREDS_KEY); } catch (e) {}
    try { sessionStorage.removeItem(ONCE_KEY); } catch (e) {}
    if (socket) { try { socket.disconnect(); } catch (e) {} }
    socket = null;
    pending = null;
    loginData = null;
  }

  // Send the user to the login page, remembering where they were going so
  // they come back to it rather than being dropped on the chat.
  function toLogin() {
    const page = (location.pathname.split('/').pop() || 'index.html');
    location.href = 'login.html?return=' + encodeURIComponent(page);
  }

  function requireLogin() {
    const user = Titan.getUser();
    if (!user) { toLogin(); return null; }
    return user;
  }

  // The logged-in socket. Every caller on the page shares one.
  function ws() {
    if (socket && socket.connected && loginData) return Promise.resolve(socket);
    if (pending) return pending;

    const creds = credentials();
    if (!creds) {
      pending = null;
      return Promise.reject(new Error('no-credentials'));
    }

    pending = new Promise(function (resolve, reject) {
      const sock = new Titan.WS();
      let settled = false;
      const giveUp = setTimeout(function () {
        if (settled) return;
        settled = true;
        pending = null;
        try { sock.disconnect(); } catch (e) {}
        reject(new Error(Titan.t('err.network')));
      }, 20000);

      sock.addEventListener('open', function () {
        sock.login(creds.username, creds.password).then(function (resp) {
          if (settled) return;
          if (!resp || !resp.success) {
            settled = true;
            clearTimeout(giveUp);
            pending = null;
            try { sock.disconnect(); } catch (e) {}
            reject(new Error(resp && resp.error ? resp.error : Titan.t('err.auth')));
            return;
          }
          settled = true;
          clearTimeout(giveUp);
          socket = sock;
          loginData = resp;
          rememberRole(resp.user);
          freshToken(resp);
          // A sound the server plays at somebody should reach them
          // wherever they are on the site, not only in the chat — wired
          // here so every page that asks for the socket has it.
          if (window.Titan && Titan.sounds && Titan.sounds.listenForServerSounds) {
            Titan.sounds.listenForServerSounds(sock);
          }
          sock.dispatchEvent(new CustomEvent('titan:logged-in', { detail: resp }));
          resolve(sock);
        }).catch(function (err) {
          if (settled) return;
          settled = true;
          clearTimeout(giveUp);
          pending = null;
          try { sock.disconnect(); } catch (e) {}
          reject(err);
        });
      }, { once: true });

      sock.addEventListener('ws-error', function () {
        if (settled) return;
        settled = true;
        clearTimeout(giveUp);
        pending = null;
        reject(new Error(Titan.t('err.network')));
      }, { once: true });

      // A dropped connection reconnects by itself (ws.js), but the server
      // has forgotten the session — so log in again on the new socket, or
      // every request after a hiccup comes back "Not authenticated".
      sock.addEventListener('open', function () {
        if (!settled) return;
        sock.login(creds.username, creds.password).then(function (resp) {
          if (resp && resp.success) {
            loginData = resp;
            rememberRole(resp.user);
            freshToken(resp);
            sock.dispatchEvent(new CustomEvent('titan:logged-in', { detail: resp }));
          }
        }).catch(function () {});
      });

      sock.connect();
    });

    return pending;
  }

  // Every login mints a new signed HTTP token, and it is the ONLY thing
  // the REST calls are authenticated by. Taking it here is what keeps the
  // two halves of the session together: before this, the token was written
  // once by the login page and kept until the user logged out, so a session
  // carrying the old base64("id:username") form - or a signed one past its
  // thirty days - went on presenting it to every REST call for ever, and
  // the pages made only of REST calls (Mail, Account) answered
  // "Authentication required" with no way back.
  function freshToken(resp) {
    if (resp && resp.http_token && window.Titan && Titan.saveToken) {
      Titan.saveToken(resp.http_token);
    }
  }

  // The role decides which parts of the site are offered. It is only ever
  // a convenience: every gated call is checked again on the server, so a
  // user who edits their own localStorage gains nothing but a menu entry
  // that answers "permission denied".
  function rememberRole(user) {
    if (!user) return;
    let session = null;
    try { session = JSON.parse(localStorage.getItem('titan.session') || 'null'); } catch (e) {}
    if (!session || !session.user) return;
    const role = user.role || (user.is_admin ? 'admin' : 'user');
    if (session.user.role === role && session.user.is_admin === !!user.is_admin) return;
    session.user.role = role;
    session.user.is_admin = !!user.is_admin;
    localStorage.setItem('titan.session', JSON.stringify(session));
    window.dispatchEvent(new CustomEvent('titan:session-changed'));
  }

  function role() {
    const user = Titan.getUser();
    if (!user) return null;
    return user.role || (user.is_admin ? 'admin' : 'user');
  }

  function isModerator() {
    const r = role();
    return r === 'moderator' || r === 'admin' || r === 'developer' || r === 'owner';
  }

  function isAdmin() {
    const r = role();
    return r === 'admin' || r === 'owner';
  }

  function login() { return loginData; }

  window.Titan = window.Titan || {};
  window.Titan.session = {
    ws: ws,
    credentials: credentials,
    saveCredentials: saveCredentials,
    forget: forget,
    requireLogin: requireLogin,
    toLogin: toLogin,
    role: role,
    isModerator: isModerator,
    isAdmin: isAdmin,
    loginResponse: login,
  };
})();
