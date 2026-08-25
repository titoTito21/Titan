// Titan-Net web — the account page.
//
// Everything about this account that belongs to the person rather than to
// a conversation: who they are, the recovery email, the people they have
// blocked, the sounds other machines play for them, and the services
// Titan-Net holds a connection to on their behalf.
(function () {
  'use strict';

  const t = Titan.t;
  const ui = Titan.ui;
  const API = Titan.API;

  // The live socket, once there is one. Several sections below need it
  // and each says so rather than failing quietly when there is none.
  let ws = null;

  const user = Titan.getUser();
  if (!user) {
    document.getElementById('acc-not-logged-in').hidden = false;
    return;
  }

  // ---------- Who you are ----------

  document.getElementById('acc-info').hidden = false;
  document.getElementById('acc-username').textContent = user.username;
  document.getElementById('acc-titan').textContent = user.titan_number || '—';
  document.getElementById('acc-role').textContent =
    user.role || (user.is_admin ? 'admin' : '—');

  API.getRole().then(function (r) {
    if (r && r.role) document.getElementById('acc-role').textContent = r.role;
  }).catch(function () { /* the dash stands in */ });

  document.getElementById('acc-logout').addEventListener('click', function () {
    if (Titan.sounds) Titan.sounds.play('logout');
    Titan.saveSession(null);
    try { localStorage.removeItem('titan.remember'); } catch (e) {}
    if (Titan.session) Titan.session.forget();
    setTimeout(function () { location.href = 'index.html'; }, 120);
  });

  // ---------- Recovery email ----------

  const emailCard = document.getElementById('acc-email-card');
  const emailStatus = document.getElementById('acc-email-status');
  const emailInput = document.getElementById('acc-email-input');
  const emailAlert = document.getElementById('acc-email-alert');
  const emailSave = document.getElementById('acc-email-save');
  emailCard.hidden = false;

  async function loadEmail() {
    try {
      const r = await API.getAccountEmail();
      if (!r || !r.success) { emailStatus.textContent = t('account.email_load_error'); return; }
      if (!r.email) {
        emailStatus.textContent = t('account.email_none');
      } else {
        emailInput.value = r.email;
        emailStatus.textContent = (r.email_verified
          ? t('account.email_verified') : t('account.email_unverified'))
          .replace('{email}', r.email);
      }
    } catch (e) {
      emailStatus.textContent = t('account.email_load_error');
    }
  }

  emailSave.addEventListener('click', async function () {
    const email = emailInput.value.trim();
    if (!email) { ui.setAlert(emailAlert, t('err.required'), 'error'); return; }
    emailSave.disabled = true;
    try {
      const r = await API.setAccountEmail(email);
      if (r && r.success) {
        ui.setAlert(emailAlert, t('account.email_saved'), 'success');
        loadEmail();
      } else {
        ui.setAlert(emailAlert, (r && r.error) || t('err.generic'), 'error');
      }
    } catch (e) {
      ui.setAlert(emailAlert, e.message || t('err.generic'), 'error');
    } finally {
      emailSave.disabled = false;
    }
  });
  loadEmail();

  // ---------- The page other people can follow you to ----------

  const blogCard = document.getElementById('acc-blog-card');
  const blogInput = document.getElementById('acc-blog-input');
  const blogStatus = document.getElementById('acc-blog-status');

  document.getElementById('acc-blog-save').addEventListener('click', async function () {
    const url = blogInput.value.trim();
    ui.fieldError('acc-blog-input', '');
    // Only http and https: a javascript: or data: address here would be
    // handed to whoever clicks it on somebody else's machine.
    if (url && !/^https?:\/\//i.test(url)) {
      ui.fieldError('acc-blog-input', t('account.blog_bad'));
      blogInput.focus();
      return;
    }
    if (!ws) { blogStatus.textContent = t('account.blocked_needs_session'); return; }
    try {
      const resp = await ws.request({ type: 'update_blog', blog_url: url },
        'blog_updated', 15000);
      if (resp && resp.success === false) throw new Error(resp.error);
      blogStatus.textContent = t('account.blog_saved');
      ui.announce(blogStatus.textContent);
    } catch (err) {
      blogStatus.textContent = (err && err.message) || t('err.generic');
      ui.announce(blogStatus.textContent, 'assertive');
    }
  });

  // ---------- People you have blocked ----------
  // A block is the server's own "full ignore": symmetric, and it hides
  // presence as well as messages. It needs a live socket, so this section
  // only appears once there is one.

  const blockedCard = document.getElementById('acc-blocked-card');
  const blockedList = document.getElementById('acc-blocked-list');
  const blockedStatus = document.getElementById('acc-blocked-status');

  function renderBlocked(users) {
    ui.clear(blockedList);
    if (!users.length) {
      blockedStatus.textContent = t('account.blocked_none');
      return;
    }
    blockedStatus.textContent = t('account.blocked_count', users.length);
    users.forEach(function (blocked) {
      const name = blocked.username || blocked.name || String(blocked);
      blockedList.appendChild(ui.el('li', { class: 'flex' }, [
        ui.el('span', { text: name }),
        ui.el('button', {
          type: 'button', class: 'btn-secondary',
          text: t('account.unblock'),
          'aria-label': t('account.unblock_label', name),
          onclick: function () { unblock(blocked, name); },
        }),
      ]));
    });
  }

  async function loadBlocked() {
    if (!ws) return;
    blockedStatus.textContent = t('common.loading');
    try {
      const resp = await ws.getBlockedUsers();
      renderBlocked(resp.users || []);
    } catch (err) {
      blockedStatus.textContent = (err && err.message) || t('err.generic');
    }
  }

  async function unblock(blocked, name) {
    const id = blocked.user_id || blocked.id;
    if (!id) return;
    try {
      const resp = await ws.unblockUser(id);
      if (!resp.success) throw new Error(resp.error);
      ui.announce(t('account.unblocked', name));
      loadBlocked();
    } catch (err) {
      ui.announce((err && err.message) || t('err.generic'), 'assertive');
    }
  }

  document.getElementById('acc-block-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    const field = document.getElementById('acc-block-name');
    const name = field.value.trim();
    if (!name || !ws) return;
    // The block API takes a user id, so the name is resolved against who
    // is online — the same list the chat blocks from.
    try {
      const online = await ws.getOnlineUsers();
      const match = (online.users || online.online_users || []).filter(function (u) {
        return String(u.username || '').toLowerCase() === name.toLowerCase();
      })[0];
      if (!match) {
        ui.fieldError('acc-block-name', t('account.block_not_found'));
        field.focus();
        return;
      }
      ui.fieldError('acc-block-name', '');
      const resp = await ws.blockUser(match.id || match.user_id);
      if (!resp.success) throw new Error(resp.error);
      field.value = '';
      ui.announce(t('account.blocked', name));
      loadBlocked();
    } catch (err) {
      ui.fieldError('acc-block-name', (err && err.message) || t('err.generic'));
    }
  });

  // ---------- The sounds other people hear for you ----------

  const soundsCard = document.getElementById('acc-sounds-card');
  const soundsAlert = document.getElementById('acc-sounds-alert');
  soundsCard.hidden = false;

  document.getElementById('acc-sound-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    const kind = document.getElementById('acc-sound-type').value;
    const file = document.getElementById('acc-sound-file').files[0];
    ui.fieldError('acc-sound-file', '');
    if (!file) { ui.fieldError('acc-sound-file', t('err.required')); return; }
    if (file.size > 5 * 1024 * 1024) {
      ui.fieldError('acc-sound-file', t('account.sound_too_big'));
      return;
    }
    const submit = document.getElementById('acc-sound-submit');
    submit.disabled = true;
    try {
      const form = new FormData();
      form.append('metadata', JSON.stringify({ sound_type: kind }));
      form.append('file', file, file.name);
      const resp = await fetch('/api/users/sounds/upload', {
        method: 'POST',
        headers: { Authorization: 'Bearer ' + Titan.getToken() },
        body: form,
      });
      const data = await resp.json().catch(function () { return null; });
      if (!resp.ok || !data || data.success === false) {
        throw new Error((data && data.error) || ('HTTP ' + resp.status));
      }
      ui.setAlert(soundsAlert, t('account.sound_saved'), 'success');
      if (Titan.sounds) Titan.sounds.play('titannet_success');
      document.getElementById('acc-sound-form').reset();
    } catch (err) {
      ui.setAlert(soundsAlert, (err && err.message) || t('err.generic'), 'error');
    } finally {
      submit.disabled = false;
    }
  });

  document.getElementById('acc-sound-play').addEventListener('click', function () {
    const kind = document.getElementById('acc-sound-type').value;
    const url = '/api/users/sounds/' + encodeURIComponent(user.username)
      + '/' + encodeURIComponent(kind);
    const audio = new Audio(url);
    audio.play().then(function () {
      ui.announce(t('account.sound_playing'));
    }).catch(function () {
      ui.setAlert(soundsAlert, t('account.sound_none'), 'warning');
    });
  });

  // ---------- Connected services ----------

  const PROVIDERS = ['spotify', 'allegro'];
  const oauthCard = document.getElementById('acc-oauth-card');
  const oauthList = document.getElementById('acc-oauth-list');
  const oauthStatus = document.getElementById('acc-oauth-status');

  async function loadConnections() {
    ui.clear(oauthList);
    let offered = 0;
    for (const provider of PROVIDERS) {
      // A provider the server has no configuration for answers 404, and
      // is simply not offered — better than a Connect button that leads
      // to an error page.
      let state = null;
      try {
        const resp = await fetch('/api/oauth/' + provider + '/status', {
          headers: { Authorization: 'Bearer ' + Titan.getToken() },
        });
        if (resp.status === 404) continue;   // the server does not offer it
        state = await resp.json();
      } catch (e) {
        continue;
      }
      if (!state) continue;
      offered++;
      const connected = !!state.connected;
      const row = ui.el('li', { class: 'flex' }, [
        ui.el('span', { text: t('account.provider_' + provider, provider) }),
        ui.el('span', {
          class: 'badge badge-status',
          text: connected ? t('account.connected') : t('account.not_connected'),
        }),
      ]);
      if (connected) {
        row.appendChild(ui.el('button', {
          type: 'button', class: 'btn-danger',
          text: t('account.disconnect'),
          'aria-label': t('account.disconnect_label', provider),
          onclick: function () { disconnect(provider); },
        }));
      } else {
        // The connect flow leaves the site, so it is a link, not a button.
        row.appendChild(ui.el('a', {
          class: 'btn btn-secondary',
          href: '/oauth/' + provider + '/start',
          text: t('account.connect'),
          'aria-label': t('account.connect_label', provider),
        }));
      }
      oauthList.appendChild(row);
    }
    oauthCard.hidden = offered === 0;
    oauthStatus.textContent = offered
      ? t('account.connected_count', offered) : '';
  }

  async function disconnect(provider) {
    const sure = await ui.confirmDialog(t('account.disconnect_confirm', provider),
      { danger: true, title: t('account.disconnect') });
    if (!sure) return;
    try {
      await fetch('/api/oauth/' + provider, {
        method: 'DELETE',
        headers: { Authorization: 'Bearer ' + Titan.getToken() },
      });
      ui.announce(t('account.disconnected', provider));
      loadConnections();
    } catch (err) {
      ui.announce((err && err.message) || t('err.generic'), 'assertive');
    }
  }

  loadConnections();

  // ---------- The socket, for what needs one ----------

  Titan.session.ws().then(function (socket) {
    ws = socket;
    blockedCard.hidden = false;
    blogCard.hidden = false;
    loadBlocked();
  }).catch(function () {
    // No live session: everything above still works, and the block list
    // says why it is not there rather than showing an empty box.
    blockedCard.hidden = false;
    blockedStatus.textContent = t('account.blocked_needs_session');
    document.getElementById('acc-block-form').hidden = true;
  });
})();
