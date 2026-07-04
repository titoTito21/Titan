// Titan-Net auth page logic — login and register via WebSocket
(function () {
  'use strict';

  const t = Titan.t;
  const REMEMBER_KEY = 'titan.remember';

  function loadRemember() {
    try {
      const raw = localStorage.getItem(REMEMBER_KEY);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (e) { return null; }
  }
  function saveRemember(username, password) {
    // Light obfuscation only — true protection of a long-lived password
    // in the browser is not possible without OS-level keychain access.
    // The "Remember me" checkbox warns the user before this is stored.
    const blob = btoa(unescape(encodeURIComponent(JSON.stringify({ username, password }))));
    localStorage.setItem(REMEMBER_KEY, JSON.stringify({ b: blob }));
  }
  function clearRemember() { localStorage.removeItem(REMEMBER_KEY); }
  function readRemember() {
    const r = loadRemember();
    if (!r || !r.b) return null;
    try {
      const json = decodeURIComponent(escape(atob(r.b)));
      return JSON.parse(json);
    } catch (e) { return null; }
  }
  // Expose so the logout flow can wipe it
  window.Titan = window.Titan || {};
  window.Titan.clearRemember = clearRemember;

  function showAlert(msg, type) {
    const el = document.getElementById('form-alert');
    if (!el) return;
    el.className = 'alert ' + (type === 'success' ? 'alert-success' : 'alert-error');
    el.textContent = msg;
    el.hidden = false;
    Titan.announce(msg);
  }

  function setFieldError(inputId, errId, msg) {
    const input = document.getElementById(inputId);
    const err = document.getElementById(errId);
    if (!input || !err) return;
    if (msg) {
      input.setAttribute('aria-invalid', 'true');
      err.textContent = msg;
      err.hidden = false;
    } else {
      input.removeAttribute('aria-invalid');
      err.hidden = true;
      err.textContent = '';
    }
  }

  function clearErrors(ids) {
    ids.forEach(([i, e]) => setFieldError(i, e, ''));
  }

  // ---- Login page ----
  const loginForm = document.getElementById('login-form');

  // Shared sign-in routine — used by both manual submit and auto-login.
  async function doLogin(u, p, remember) {
    if (window.Titan && Titan.sounds) Titan.sounds.play('connecting');
    const ws = new Titan.WS();
    await new Promise((res, rej) => {
      ws.addEventListener('open', () => {
        if (window.Titan && Titan.sounds) Titan.sounds.play('connected');
        res();
      }, { once: true });
      ws.addEventListener('ws-error', () => rej(new Error(t('err.network'))), { once: true });
      ws.connect();
      setTimeout(() => rej(new Error(t('err.network'))), 10000);
    });
    const resp = await ws.login(u, p);
    if (!resp.success) {
      ws.disconnect();
      const err = new Error(resp.error || t('err.auth'));
      err.kind = 'auth';
      throw err;
    }
    if (window.Titan && Titan.sounds) Titan.sounds.play('login_welcome');
    const userData = resp.user;
    // Prefer the server-minted HMAC-signed token; fall back to the legacy
    // format only for an older server that doesn't issue one.
    const token = resp.http_token || btoa(userData.id + ':' + userData.username);
    Titan.saveSession({
      token,
      user: {
        id: userData.id,
        username: userData.username,
        titan_number: userData.titan_number,
      },
      motd: resp.motd || null,
    });
    if (remember) saveRemember(u, p);
    // One-shot password hand-off to chat.html (cleared after one use)
    sessionStorage.setItem('titan.once_login', JSON.stringify({ username: u, password: p }));
    ws.disconnect();
    return userData;
  }

  // Auto-login on page load when credentials are stored
  if (loginForm) {
    const stored = readRemember();
    if (stored && stored.username && stored.password) {
      // Prefill so the user sees what's happening
      document.getElementById('login-username').value = stored.username;
      document.getElementById('login-password').value = stored.password;
      document.getElementById('login-remember').checked = true;
      const submit = document.getElementById('login-submit');
      submit.disabled = true;
      Titan.announce(t('login.auto_in'));
      doLogin(stored.username, stored.password, true)
        .then(() => { location.href = 'chat.html'; })
        .catch((err) => {
          submit.disabled = false;
          // Bad stored creds — wipe so we don't loop on a stale password
          if (err && err.kind === 'auth') clearRemember();
          showAlert(err.message || t('err.generic'), 'error');
        });
    }
  }

  if (loginForm) {
    loginForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      clearErrors([['login-username', 'login-username-err'], ['login-password', 'login-password-err']]);
      const u = document.getElementById('login-username').value.trim();
      const p = document.getElementById('login-password').value;
      const remember = document.getElementById('login-remember') && document.getElementById('login-remember').checked;
      let bad = false;
      if (!u) { setFieldError('login-username', 'login-username-err', t('err.required')); bad = true; }
      if (!p) { setFieldError('login-password', 'login-password-err', t('err.required')); bad = true; }
      if (bad) {
        document.getElementById('login-username').focus();
        return;
      }
      const submit = document.getElementById('login-submit');
      submit.disabled = true;
      Titan.announce(t('login.connecting'));
      try {
        if (!remember) clearRemember();
        const userData = await doLogin(u, p, remember);
        Titan.announce(t('login.welcome', userData.username));
        location.href = 'chat.html';
      } catch (err) {
        showAlert(err.message || t('err.generic'), 'error');
        submit.disabled = false;
      }
    });
  }

  // ---- Register page ----
  const regForm = document.getElementById('register-form');
  if (regForm) {
    regForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      clearErrors([
        ['reg-username', 'reg-username-err'],
        ['reg-password', 'reg-password-err'],
        ['reg-password2', 'reg-password2-err'],
        ['reg-firstname', 'reg-firstname-err'],
        ['reg-lastname', 'reg-lastname-err'],
      ]);
      const u = document.getElementById('reg-username').value.trim();
      const p = document.getElementById('reg-password').value;
      const p2 = document.getElementById('reg-password2').value;
      const firstname = document.getElementById('reg-firstname').value.trim();
      const lastname = document.getElementById('reg-lastname').value.trim();
      const emailEl = document.getElementById('reg-email');
      const email = emailEl ? emailEl.value.trim() : '';
      const fullName = [firstname, lastname].filter(Boolean).join(' ');
      let bad = false;
      if (!u || u.length < 3) { setFieldError('reg-username', 'reg-username-err', t('err.required')); bad = true; }
      if (!p || p.length < 8) { setFieldError('reg-password', 'reg-password-err', t('err.required')); bad = true; }
      if (p !== p2) { setFieldError('reg-password2', 'reg-password2-err', t('register.pwd_mismatch')); bad = true; }
      if (bad) return;
      const submit = document.getElementById('reg-submit');
      submit.disabled = true;
      try {
        const ws = new Titan.WS();
        await new Promise((res, rej) => {
          ws.addEventListener('open', res, { once: true });
          ws.addEventListener('ws-error', () => rej(new Error(t('err.network'))), { once: true });
          ws.connect();
          setTimeout(() => rej(new Error(t('err.network'))), 10000);
        });
        const resp = await ws.register(u, p, fullName, email);
        if (!resp.success) {
          showAlert(resp.error || t('err.generic'), 'error');
          submit.disabled = false;
          ws.disconnect();
          return;
        }
        // Auto-login after register
        const loginResp = await ws.login(u, p);
        ws.disconnect();
        if (loginResp.success) {
          if (window.Titan && Titan.sounds) Titan.sounds.play('login_welcome');
          const userData = loginResp.user;
          const token = loginResp.http_token || btoa(userData.id + ':' + userData.username);
          Titan.saveSession({
            token,
            user: {
              id: userData.id,
              username: userData.username,
              titan_number: userData.titan_number,
            },
            motd: loginResp.motd || null,
          });
          sessionStorage.setItem('titan.once_login', JSON.stringify({ username: u, password: p }));
          location.href = 'chat.html';
        } else {
          location.href = 'login.html';
        }
      } catch (err) {
        showAlert(err.message || t('err.generic'), 'error');
        submit.disabled = false;
      }
    });
  }
})();
