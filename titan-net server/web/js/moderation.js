// Titan-Net web — the moderation panel.
//
// Everything a moderator can do from the desktop client, in one page with
// a tab per area: users, the repository queue, extensions, forum move
// requests, broadcasts and the message of the day, server sounds, and the
// Cerberus / Blackwall dashboard.
//
// The role decides what is OFFERED here; the server decides what is
// allowed. Every call below is checked again server-side against the
// signed token, so a user who edits their own storage gets a tab that
// answers "permission denied" and nothing more.
(function () {
  'use strict';

  const t = Titan.t;
  const ui = Titan.ui;
  const API = Titan.API;

  const $alert = document.getElementById('mod-alert');
  let ws = null;
  let users = [];

  const user = Titan.session.requireLogin();
  if (!user) return;

  function fail(err, node) {
    const text = (err && err.message) || t('err.generic');
    if (node) { node.textContent = text; ui.announce(text, 'assertive'); }
    else ui.setAlert($alert, text, 'error');
  }

  function ok(text) { ui.setAlert($alert, text, 'success'); }

  // ---------- Tabs ----------

  const PANELS = [
    { id: 'users', panel: 'panel-users', key: 'mod.users', load: loadUsers },
    { id: 'repo', panel: 'panel-repo', key: 'mod.repo', load: loadRepo },
    { id: 'ext', panel: 'panel-ext', key: 'mod.ext', load: loadExtensions },
    { id: 'forum', panel: 'panel-forum', key: 'mod.forum', load: loadMoveRequests },
    { id: 'broadcast', panel: 'panel-broadcast', key: 'mod.broadcast', load: loadBroadcastFiles },
    { id: 'sounds', panel: 'panel-sounds', key: 'mod.sounds', load: loadSounds },
    { id: 'services', panel: 'panel-services', key: 'mod.services', load: loadServices },
    { id: 'cerberus', panel: 'panel-cerberus', key: 'mod.cerberus', load: loadCerberus },
  ];

  const loaded = {};

  const tabBar = ui.tabs(document.getElementById('mod-tabs'),
    PANELS.map(function (p) { return { id: p.id, label: t(p.key), panel: p.panel }; }),
    function (entry) {
      PANELS.forEach(function (p) {
        document.getElementById(p.panel).hidden = p.id !== entry.id;
      });
      const chosen = PANELS.find(function (p) { return p.id === entry.id; });
      history.replaceState(null, '', '#' + entry.id);
      if (chosen && !loaded[entry.id]) {
        loaded[entry.id] = true;
        chosen.load();
      }
    });

  // ---------- Users ----------

  function userState(record) {
    const states = [];
    if (record.is_banned || record.banned) states.push(t('mod.state_banned'));
    if (record.is_jailed || record.jailed) states.push(t('mod.state_jailed'));
    if (record.is_online || record.online) states.push(t('mod.state_online'));
    return states.length ? states.join(', ') : t('mod.state_normal');
  }

  function userRole(record) {
    return record.role || (record.is_admin ? 'admin' : 'user');
  }

  function actionButton(label, ariaLabel, handler, cls) {
    return ui.el('button', {
      type: 'button',
      class: cls || 'btn-secondary',
      text: label,
      'aria-label': ariaLabel,
      onclick: handler,
    });
  }

  function renderUsers(filter) {
    const body = document.getElementById('mod-users-body');
    const status = document.getElementById('mod-users-status');
    ui.clear(body);
    const needle = (filter || '').trim().toLowerCase();
    const shown = users.filter(function (record) {
      return !needle || String(record.username || '').toLowerCase().indexOf(needle) !== -1;
    });
    status.textContent = shown.length
      ? t('mod.users_count', shown.length)
      : t('mod.no_users');

    shown.forEach(function (record) {
      const name = record.username || '?';
      const row = document.createElement('tr');
      // The username is the row's header, so a screen reader repeats it as
      // the user moves across the cells and never loses whose row it is.
      row.appendChild(ui.el('th', { scope: 'row', text: name }));
      row.appendChild(ui.el('td', { text: t('mod.role_' + userRole(record), userRole(record)) }));
      row.appendChild(ui.el('td', { text: userState(record) }));

      const actions = ui.el('div', { class: 'flex' });
      const isStaff = ['moderator', 'admin', 'developer', 'owner']
        .indexOf(userRole(record)) !== -1;

      actions.appendChild(actionButton(
        isStaff ? t('mod.demote') : t('mod.promote'),
        t(isStaff ? 'mod.demote_label' : 'mod.promote_label', name),
        function () { isStaff ? demote(record) : promote(record); }));

      actions.appendChild(actionButton(t('mod.jail'), t('mod.jail_label', name),
        function () { jail(record); }));
      actions.appendChild(actionButton(t('mod.release'), t('mod.release_label', name),
        function () { release(record); }));
      actions.appendChild(actionButton(t('mod.ban'), t('mod.ban_label', name),
        function () { banGlobal(record); }, 'btn-danger'));
      actions.appendChild(actionButton(t('mod.unban'), t('mod.unban_label', name),
        function () { unbanGlobal(record); }));
      actions.appendChild(actionButton(t('mod.ban_forum'), t('mod.ban_forum_label', name),
        function () { banForum(record); }));
      actions.appendChild(actionButton(t('mod.password'), t('mod.password_label', name),
        function () { changePassword(record); }));
      if (Titan.session.isAdmin()) {
        actions.appendChild(actionButton(t('mod.hard_ban'), t('mod.hard_ban_label', name),
          function () { hardBan(record); }, 'btn-danger'));
        actions.appendChild(actionButton(t('common.delete'), t('mod.delete_user_label', name),
          function () { deleteUser(record); }, 'btn-danger'));
      }
      row.appendChild(ui.el('td', {}, [actions]));
      body.appendChild(row);
    });
  }

  async function loadUsers() {
    const status = document.getElementById('mod-users-status');
    status.textContent = t('common.loading');
    try {
      const data = await API.allUsers();
      users = (data && data.users) || [];
      renderUsers(document.getElementById('mod-user-q').value);
    } catch (err) {
      fail(err, status);
    }
  }

  async function run(promise, message) {
    try {
      const result = await promise;
      if (result && result.success === false) throw new Error(result.error);
      ok(message);
      if (Titan.sounds) Titan.sounds.play('moderation');
      return result;
    } catch (err) {
      fail(err);
      return null;
    }
  }

  async function promote(record) {
    const title = await ui.promptDialog(t('mod.promote_title'), {
      title: t('mod.promote_label', record.username),
      value: 'Moderator',
    });
    if (title === null) return;
    const result = await run(API.promote(record.username, title),
      t('mod.promoted', record.username));
    if (result) loadUsers();
  }

  async function demote(record) {
    const sure = await ui.confirmDialog(t('mod.demote_confirm', record.username),
      { title: t('mod.demote'), danger: true });
    if (!sure) return;
    const result = await run(API.demote(record.username), t('mod.demoted', record.username));
    if (result) loadUsers();
  }

  async function jail(record) {
    const minutes = await ui.promptDialog(t('mod.jail_minutes'), {
      title: t('mod.jail_label', record.username),
      value: '60',
      help: t('mod.jail_help'),
    });
    if (minutes === null) return;
    const reason = await ui.promptDialog(t('common.reason'), {
      title: t('mod.jail_label', record.username),
    });
    if (reason === null) return;
    const result = await run(API.jail(record.id, Number(minutes) || 0, reason),
      t('mod.jailed', record.username));
    if (result) loadUsers();
  }

  async function release(record) {
    const result = await run(API.release(record.id), t('mod.released', record.username));
    if (result) loadUsers();
  }

  async function askBanDetails(name) {
    const reason = await ui.promptDialog(t('common.reason'), {
      title: t('mod.ban_label', name),
      required: true,
      help: t('mod.ban_reason_help'),
    });
    if (reason === null) return null;
    const hours = await ui.promptDialog(t('mod.ban_hours'), {
      title: t('mod.ban_label', name),
      help: t('mod.ban_hours_help'),
      value: '',
    });
    if (hours === null) return null;
    const numeric = Number(hours);
    return {
      reason: reason,
      banType: numeric > 0 ? 'temporary' : 'permanent',
      durationHours: numeric > 0 ? numeric : null,
    };
  }

  async function banGlobal(record) {
    const details = await askBanDetails(record.username);
    if (!details) return;
    const result = await run(API.banGlobal(record.id, details),
      t('mod.banned', record.username));
    if (result) loadUsers();
  }

  async function unbanGlobal(record) {
    const result = await run(API.unbanGlobal(record.id), t('mod.unbanned', record.username));
    if (result) loadUsers();
  }

  async function banForum(record) {
    const details = await askBanDetails(record.username);
    if (!details) return;
    await run(API.banForum(record.id, details), t('mod.banned_forum', record.username));
  }

  async function changePassword(record) {
    const password = await ui.promptDialog(t('mod.new_password'), {
      title: t('mod.password_label', record.username),
      password: true,
      required: true,
      help: t('mod.new_password_help'),
    });
    if (password === null) return;
    await run(API.adminChangePassword(record.username, password),
      t('mod.password_changed', record.username));
  }

  async function hardBan(record) {
    const reason = await ui.promptDialog(t('common.reason'), {
      title: t('mod.hard_ban_label', record.username),
      required: true,
      help: t('mod.hard_ban_help'),
    });
    if (reason === null) return;
    const sure = await ui.confirmDialog(t('mod.hard_ban_confirm', record.username),
      { danger: true, title: t('mod.hard_ban') });
    if (!sure) return;
    const result = await run(API.banHard(record.id, reason),
      t('mod.hard_banned', record.username));
    if (result) loadUsers();
  }

  async function deleteUser(record) {
    const sure = await ui.confirmDialog(t('mod.delete_user_confirm', record.username),
      { danger: true, title: t('common.delete'), confirmLabel: t('common.delete') });
    if (!sure) return;
    const result = await run(ws.deleteUser(record.id), t('mod.user_deleted', record.username));
    if (result) loadUsers();
  }

  document.getElementById('mod-user-search').addEventListener('submit', function (e) {
    e.preventDefault();
    renderUsers(document.getElementById('mod-user-q').value);
  });
  document.getElementById('mod-user-q').addEventListener('input', function (e) {
    renderUsers(e.target.value);
  });
  document.getElementById('mod-users-refresh').addEventListener('click', loadUsers);

  // ---------- Repository queue ----------

  async function loadRepo() {
    const status = document.getElementById('mod-repo-status');
    const list = document.getElementById('mod-repo-list');
    status.textContent = t('common.loading');
    ui.clear(list);
    try {
      const data = await API.pendingApps();
      const apps = (data && (data.apps || data.pending)) || [];
      status.textContent = apps.length ? t('mod.repo_count', apps.length) : t('mod.repo_empty');
      apps.forEach(function (app) {
        const titleId = 'mod-app-' + app.id;
        list.appendChild(ui.el('li', {}, [
          ui.el('article', { class: 'card', 'aria-labelledby': titleId }, [
            ui.el('h3', { id: titleId, text: app.name }),
            ui.el('p', { class: 'meta', text: [
              t('repo.by', app.uploader_username || app.author_username || '?'),
              app.category, app.version, ui.bytes(app.file_size),
            ].filter(Boolean).join(' · ') }),
            ui.el('p', { text: app.description || '' }),
            ui.el('div', { class: 'flex card-actions' }, [
              actionButton(t('mod.approve'), t('mod.approve_label', app.name), function () {
                run(API.approveApp(app.id), t('mod.approved', app.name)).then(loadRepo);
              }, ''),
              actionButton(t('mod.reject'), t('mod.reject_label', app.name), async function () {
                const reason = await ui.promptDialog(t('common.reason'),
                  { title: t('mod.reject_label', app.name) });
                if (reason === null) return;
                run(API.rejectApp(app.id, reason), t('mod.rejected', app.name)).then(loadRepo);
              }, 'btn-danger'),
            ]),
          ]),
        ]));
      });
    } catch (err) {
      fail(err, status);
    }
  }

  document.getElementById('mod-repo-refresh').addEventListener('click', loadRepo);

  // ---------- Extensions ----------

  function extensionCard(ext, pending) {
    const titleId = 'mod-ext-' + ext.id;
    const actions = ui.el('div', { class: 'flex card-actions' });
    if (pending) {
      actions.appendChild(actionButton(t('mod.approve'), t('mod.approve_label', ext.name),
        async function () {
          const note = await ui.promptDialog(t('mod.review_note'),
            { title: t('mod.approve_label', ext.name) });
          if (note === null) return;
          run(API.approveExtension(ext.id, note), t('mod.approved', ext.name))
            .then(loadExtensions);
        }, ''));
      actions.appendChild(actionButton(t('mod.reject'), t('mod.reject_label', ext.name),
        async function () {
          const note = await ui.promptDialog(t('mod.review_note'),
            { title: t('mod.reject_label', ext.name) });
          if (note === null) return;
          run(API.rejectExtension(ext.id, note), t('mod.rejected', ext.name))
            .then(loadExtensions);
        }, 'btn-danger'));
    } else {
      const enabled = ext.enabled !== 0 && ext.enabled !== false;
      actions.appendChild(actionButton(
        enabled ? t('mod.disable') : t('mod.enable'),
        t(enabled ? 'mod.disable_label' : 'mod.enable_label', ext.name),
        function () {
          const call = enabled ? API.disableExtension(ext.id) : API.enableExtension(ext.id);
          run(call, t(enabled ? 'mod.disabled' : 'mod.enabled', ext.name)).then(loadExtensions);
        }));
      actions.appendChild(actionButton(t('common.delete'), t('mod.delete_ext_label', ext.name),
        async function () {
          const sure = await ui.confirmDialog(t('mod.delete_ext_confirm', ext.name),
            { danger: true, title: t('common.delete'), confirmLabel: t('common.delete') });
          if (!sure) return;
          run(API.deleteExtension(ext.id), t('mod.ext_deleted', ext.name)).then(loadExtensions);
        }, 'btn-danger'));
    }
    return ui.el('li', {}, [
      ui.el('article', { class: 'card', 'aria-labelledby': titleId }, [
        ui.el('h4', { id: titleId, text: ext.name }),
        ui.el('p', { class: 'meta', text: [ext.slug, ext.version,
          t('repo.by', ext.author_username || ext.submitted_by || '?')].filter(Boolean).join(' · ') }),
        ui.el('p', { text: ext.description || '' }),
        actions,
      ]),
    ]);
  }

  async function loadExtensions() {
    const status = document.getElementById('mod-ext-status');
    const pending = document.getElementById('mod-ext-pending');
    const active = document.getElementById('mod-ext-active');
    status.textContent = t('common.loading');
    ui.clear(pending);
    ui.clear(active);
    try {
      const waiting = await API.listExtensions('pending');
      const live = await API.listExtensions('approved');
      const waitingList = (waiting && waiting.extensions) || [];
      const liveList = (live && live.extensions) || [];
      waitingList.forEach(function (ext) { pending.appendChild(extensionCard(ext, true)); });
      liveList.forEach(function (ext) { active.appendChild(extensionCard(ext, false)); });
      status.textContent = t('mod.ext_count', waitingList.length, liveList.length);
    } catch (err) {
      fail(err, status);
    }
  }

  document.getElementById('mod-ext-refresh').addEventListener('click', loadExtensions);

  // ---------- Forum move requests ----------

  async function loadMoveRequests() {
    const status = document.getElementById('mod-forum-status');
    const list = document.getElementById('mod-forum-list');
    status.textContent = t('common.loading');
    ui.clear(list);
    try {
      const data = await API.listMoveRequests();
      const requests = (data && data.requests) || [];
      status.textContent = requests.length
        ? t('mod.forum_count', requests.length)
        : t('mod.forum_empty');
      requests.forEach(function (req) {
        const titleId = 'mod-move-' + req.id;
        list.appendChild(ui.el('li', {}, [
          ui.el('article', { class: 'card', 'aria-labelledby': titleId }, [
            ui.el('h3', { id: titleId, text: req.topic_title || ('#' + req.topic_id) }),
            ui.el('p', { class: 'meta', text: t('mod.move_into',
              req.target_forum_name || req.forum_id, req.requested_by_username || '?') }),
            ui.el('div', { class: 'flex card-actions' }, [
              actionButton(t('mod.approve'), t('mod.approve_move_label', req.topic_title || ''),
                function () {
                  run(API.approveMoveRequest(req.id), t('mod.move_approved'))
                    .then(loadMoveRequests);
                }, ''),
              actionButton(t('mod.reject'), t('mod.reject_move_label', req.topic_title || ''),
                function () {
                  run(API.rejectMoveRequest(req.id), t('mod.move_rejected'))
                    .then(loadMoveRequests);
                }, 'btn-danger'),
            ]),
          ]),
        ]));
      });
    } catch (err) {
      fail(err, status);
    }
  }

  document.getElementById('mod-forum-refresh').addEventListener('click', loadMoveRequests);

  // ---------- Broadcast and the message of the day ----------

  document.getElementById('mod-broadcast-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    const field = document.getElementById('mod-broadcast-text');
    const text = field.value.trim();
    if (!text) { ui.fieldError('mod-broadcast-text', t('err.required')); field.focus(); return; }
    ui.fieldError('mod-broadcast-text', '');
    const sure = await ui.confirmDialog(t('mod.broadcast_confirm'), { title: t('mod.broadcast') });
    if (!sure) return;
    const result = await run(ws.sendBroadcast({ text_message: text }), t('mod.broadcast_sent'));
    if (result) field.value = '';
  });

  async function loadBroadcastFiles() {
    const status = document.getElementById('mod-motd-status');
    const select = document.getElementById('mod-motd-file');
    try {
      const resp = await ws.listBroadcastFiles();
      if (resp.success === false) throw new Error(resp.error);
      ui.clear(select);
      (resp.files || []).forEach(function (file) {
        const name = typeof file === 'string' ? file : (file.filename || file.name);
        select.appendChild(ui.el('option', { value: name, text: name }));
      });
      status.textContent = t('mod.motd_files', select.options.length);
    } catch (err) {
      fail(err, status);
    }
  }

  document.getElementById('mod-motd-load').addEventListener('click', async function () {
    const status = document.getElementById('mod-motd-status');
    const name = document.getElementById('mod-motd-file').value;
    if (!name) return;
    try {
      const resp = await ws.getBroadcastFile(name);
      if (resp.success === false) throw new Error(resp.error);
      document.getElementById('mod-motd-text').value = resp.content || '';
      status.textContent = t('mod.motd_loaded', name);
      ui.announce(status.textContent);
    } catch (err) {
      fail(err, status);
    }
  });

  document.getElementById('mod-motd-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    const status = document.getElementById('mod-motd-status');
    const name = document.getElementById('mod-motd-file').value;
    if (!name) return;
    try {
      const resp = await ws.saveBroadcastFile(name,
        document.getElementById('mod-motd-text').value);
      if (resp.success === false) throw new Error(resp.error);
      status.textContent = t('mod.motd_saved', name);
      ui.announce(status.textContent);
      if (Titan.sounds) Titan.sounds.play('titannet_success');
    } catch (err) {
      fail(err, status);
    }
  });

  // ---------- Server sounds ----------

  async function loadSounds() {
    const status = document.getElementById('mod-sounds-status');
    const list = document.getElementById('mod-sounds-list');
    status.textContent = t('common.loading');
    ui.clear(list);
    try {
      const data = await API.listSounds();
      const sounds = (data && data.sounds) || [];
      status.textContent = sounds.length
        ? t('mod.sounds_count', sounds.length)
        : t('mod.sounds_empty');
      sounds.forEach(function (sound) {
        const titleId = 'mod-sound-' + String(sound.name).replace(/[^\w-]/g, '_');
        // A real <audio controls> is the platform's own player: play,
        // pause, seek and volume all reachable from the keyboard and named
        // by the browser, in the user's own language.
        const player = ui.el('audio', { controls: true, preload: 'none' });
        player.src = API.soundUrl(sound.name);
        player.setAttribute('aria-label', t('mod.sound_preview', sound.name));

        list.appendChild(ui.el('li', {}, [
          ui.el('article', { class: 'card', 'aria-labelledby': titleId }, [
            ui.el('h3', { id: titleId, text: sound.name }),
            ui.el('p', { class: 'meta', text: [sound.description,
              ui.bytes(sound.size_bytes || sound.size)].filter(Boolean).join(' · ') }),
            player,
            ui.el('div', { class: 'flex card-actions' }, [
              actionButton(t('mod.play_at'), t('mod.play_at_label', sound.name),
                function () { playSoundAt(sound); }),
              actionButton(t('common.delete'), t('mod.delete_sound_label', sound.name),
                async function () {
                  const sure = await ui.confirmDialog(t('mod.delete_sound_confirm', sound.name),
                    { danger: true, title: t('common.delete'), confirmLabel: t('common.delete') });
                  if (!sure) return;
                  run(API.deleteSound(sound.name), t('mod.sound_deleted', sound.name))
                    .then(loadSounds);
                }, 'btn-danger'),
            ]),
          ]),
        ]));
      });
    } catch (err) {
      fail(err, status);
    }
  }

  async function playSoundAt(sound) {
    const who = await ui.promptDialog(t('mod.play_target'), {
      title: t('mod.play_at_label', sound.name),
      help: t('mod.play_target_help'),
    });
    if (who === null) return;
    const wanted = who.trim();
    const target = !wanted || wanted === '*'
      ? { type: 'all' }
      : { type: 'user', username: wanted };
    await run(API.playSound(sound.name, target), t('mod.sound_played', sound.name));
  }

  document.getElementById('mod-sounds-refresh').addEventListener('click', loadSounds);

  document.getElementById('mod-sound-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    const name = document.getElementById('mod-sound-name').value.trim().toLowerCase();
    const file = document.getElementById('mod-sound-file').files[0];
    ui.fieldError('mod-sound-name', '');
    ui.fieldError('mod-sound-file', '');
    if (!name) { ui.fieldError('mod-sound-name', t('err.required')); return; }
    if (!file) { ui.fieldError('mod-sound-file', t('err.required')); return; }
    const submit = document.getElementById('mod-sound-submit');
    submit.disabled = true;
    try {
      const base64 = await new Promise(function (resolve, reject) {
        const reader = new FileReader();
        reader.onload = function () {
          const result = String(reader.result || '');
          resolve(result.slice(result.indexOf(',') + 1));
        };
        reader.onerror = function () { reject(new Error(t('fb.attachment_failed'))); };
        reader.readAsDataURL(file);
      });
      await run(API.uploadSound(name, file.name, base64,
        document.getElementById('mod-sound-desc').value), t('mod.sound_uploaded', name));
      document.getElementById('mod-sound-form').reset();
      loadSounds();
    } catch (err) {
      fail(err);
    } finally {
      submit.disabled = false;
    }
  });

  // ---------- Services, and the tables that are running ----------

  async function loadServices() {
    const status = document.getElementById('mod-services-status');
    const select = document.getElementById('mod-screen');
    status.textContent = t('common.loading');
    try {
      const data = await API.listRemoteScreens();
      ui.clear(select);
      (data.screens || []).forEach(function (screen) {
        select.appendChild(ui.el('option', {
          value: screen.slug,
          text: screen.title + ' (' + screen.slug + ')',
        }));
      });
      status.textContent = t('mod.screens_count', select.options.length);
    } catch (err) {
      fail(err, status);
    }
    loadGameSessions();
  }

  document.getElementById('mod-screen-open').addEventListener('click', function () {
    const slug = document.getElementById('mod-screen').value;
    if (!slug) return;
    // The renderer lives on the services page; opening it there means one
    // implementation rather than a second, worse one here.
    location.href = 'services.html?screen=' + encodeURIComponent(slug);
  });

  document.getElementById('mod-screen-push').addEventListener('click', async function () {
    const slug = document.getElementById('mod-screen').value;
    if (!slug) return;
    const sure = await ui.confirmDialog(t('mod.screen_push_confirm', slug),
      { title: t('mod.screen_push') });
    if (!sure) return;
    await run(API.pushRemoteScreen(slug, { type: 'all' }), t('mod.screen_pushed', slug));
  });

  document.getElementById('mod-screen-submissions').addEventListener('click', async function () {
    const slug = document.getElementById('mod-screen').value;
    const pane = document.getElementById('mod-submissions');
    const status = document.getElementById('mod-services-status');
    if (!slug) return;
    status.textContent = t('common.loading');
    ui.clear(pane);
    try {
      const data = await API.remoteScreenSubmissions(slug);
      const rows = data.submissions || [];
      if (!rows.length) {
        pane.appendChild(ui.el('p', { text: t('mod.no_submissions') }));
      } else {
        rows.forEach(function (row) {
          pane.appendChild(ui.el('p', {
            text: [ui.timeText(row.created_at), row.username || row.user_id,
                   row.action, row.values].filter(Boolean).join(' | '),
          }));
        });
      }
      status.textContent = t('mod.submissions_count', rows.length);
      ui.announce(status.textContent);
    } catch (err) {
      fail(err, status);
    }
  });

  async function loadGameSessions() {
    const status = document.getElementById('mod-sessions-status');
    const list = document.getElementById('mod-sessions-list');
    ui.clear(list);
    try {
      const resp = await ws.listGameSessions();
      if (!resp.success) throw new Error(resp.error);
      const sessions = resp.sessions || [];
      status.textContent = sessions.length
        ? t('mod.sessions_count', sessions.length) : t('mod.no_sessions');
      sessions.forEach(function (entry) {
        list.appendChild(ui.el('li', {
          text: [entry.game_name || ('#' + entry.id),
                 t('games.hosted_by', entry.host_username || '?'),
                 t('games.player_count', entry.player_count || 0),
                 t('games.session_state_' + (entry.status || 'lobby'))].join(' · '),
        }));
      });
    } catch (err) {
      fail(err, status);
    }
  }

  document.getElementById('mod-sessions-refresh')
    .addEventListener('click', loadGameSessions);

  document.getElementById('mod-sessions-wipe').addEventListener('click', async function () {
    const sure = await ui.confirmDialog(t('mod.wipe_confirm'),
      { danger: true, title: t('mod.wipe_sessions'),
        confirmLabel: t('mod.wipe_sessions') });
    if (!sure) return;
    const done = await run(ws.wipeAllGameSessions(), t('mod.wiped'));
    if (done) loadGameSessions();
  });

  // ---------- Cerberus and Blackwall ----------

  function detail(list, term, value) {
    list.appendChild(ui.el('dt', { text: term }));
    list.appendChild(ui.el('dd', { text: value === undefined || value === null ? '—' : String(value) }));
  }

  async function loadCerberus() {
    const status = document.getElementById('mod-cerb-status');
    status.textContent = t('common.loading');
    try {
      const data = await ws.cerberusStatus();
      renderCerberus(data);
      status.textContent = t('mod.cerb_read');
    } catch (err) {
      fail(err, status);
    }
  }

  function renderCerberus(data) {
    const summary = document.getElementById('mod-cerb-summary');
    ui.clear(summary);
    detail(summary, t('mod.cerb_threat'), data.threat_name || data.threat_level);
    detail(summary, t('mod.cerb_lockdown'),
      data.lockdown_active ? (data.lockdown_reason || t('common.yes')) : t('common.no'));
    detail(summary, t('mod.cerb_banned_count'), (data.banned_ips || []).length);
    detail(summary, t('mod.cerb_permanent_count'), (data.permanent_banned_ips || []).length);
    detail(summary, t('mod.cerb_whitelisted'), (data.whitelisted_ips || []).length);
    if (data.stats) {
      detail(summary, t('mod.cerb_intrusions'), data.stats.intrusions_blocked);
      detail(summary, t('mod.cerb_ddos'), data.stats.ddos_blocked);
    }
    const bw = data.blackwall;
    if (bw) {
      detail(summary, t('mod.bw_online'), bw.online ? t('common.yes') : t('common.no'));
      detail(summary, t('mod.bw_posture'), bw.posture);
      detail(summary, t('mod.bw_watching'), bw.watching);
      detail(summary, t('mod.bw_campaigns'), (bw.campaigns || []).length);
      detail(summary, t('mod.bw_own_bans'), (bw.own_bans || []).length);
      if (bw.unsaid) {
        // A number that only grows means the answering channel is reaching
        // nobody, which is the thing worth seeing on a dashboard.
        detail(summary, t('mod.bw_unsaid'),
          t('mod.bw_unsaid_value', bw.unsaid.lines || 0, bw.unsaid.actors || 0));
      }
      detail(summary, t('mod.bw_transcript'), bw.transcript);
      if (bw.ai) {
        detail(summary, t('mod.bw_ai'),
          bw.ai.enabled ? (bw.ai.autonomous ? t('mod.bw_ai_autonomous') : t('mod.bw_ai_advisory'))
                        : t('common.no'));
      }
    }

    // Bans
    const bans = document.getElementById('mod-cerb-bans');
    ui.clear(bans);
    const permanent = new Set(data.permanent_banned_ips || []);
    const threats = data.per_ip_threats || {};
    const all = Array.from(new Set([].concat(data.banned_ips || [], data.permanent_banned_ips || [])));
    document.getElementById('mod-cerb-bans-status').textContent = all.length
      ? t('mod.cerb_bans_count', all.length)
      : t('mod.cerb_no_bans');
    all.slice(0, 500).forEach(function (ip) {
      const row = document.createElement('tr');
      row.appendChild(ui.el('th', { scope: 'row', text: ip }));
      const reason = (threats[ip] && threats[ip].reason)
        || (permanent.has(ip) ? t('mod.cerb_permanent') : '');
      row.appendChild(ui.el('td', { text: reason }));
      row.appendChild(ui.el('td', {}, [
        actionButton(t('mod.cerb_unban'), t('mod.cerb_unban_label', ip), function () {
          run(ws.cerberusUnbanIp(ip), t('mod.cerb_unbanned', ip)).then(loadCerberus);
        }),
      ]));
      bans.appendChild(row);
    });

    // What was said
    const transcript = document.getElementById('mod-cerb-transcript');
    ui.clear(transcript);
    const said = data.cerberus_said || [];
    if (!said.length) {
      transcript.appendChild(ui.el('p', { text: t('mod.cerb_said_empty') }));
    } else {
      said.forEach(function (entry) {
        transcript.appendChild(ui.el('p', {
          text: '[' + (entry.ip || '?') + '] ' + (entry.said || ''),
        }));
      });
    }
  }

  document.getElementById('mod-cerb-refresh').addEventListener('click', loadCerberus);

  document.getElementById('mod-cerb-logs').addEventListener('click', async function () {
    const pane = document.getElementById('mod-cerb-log');
    const status = document.getElementById('mod-cerb-status');
    status.textContent = t('common.loading');
    try {
      const data = await ws.cerberusLogs(300);
      ui.clear(pane);
      const logs = data.logs || [];
      if (!logs.length) {
        pane.appendChild(ui.el('p', { text: t('mod.cerb_log_empty') }));
      } else {
        logs.forEach(function (entry) {
          pane.appendChild(ui.el('p', {
            text: [entry.timestamp, entry.severity, entry.message].filter(Boolean).join(' | '),
          }));
        });
      }
      status.textContent = t('mod.cerb_log_read', logs.length);
      ui.announce(status.textContent);
    } catch (err) {
      fail(err, status);
    }
  });

  function renderReport(report) {
    const pane = document.getElementById('mod-cerb-report');
    ui.clear(pane);
    if (!report) { pane.appendChild(ui.el('p', { text: t('mod.cerb_no_report') })); return; }
    if (report.error) { pane.appendChild(ui.el('p', { text: report.error })); return; }
    if (report.enabled === false) {
      pane.appendChild(ui.el('p', { text: report.error || t('mod.cerb_ai_off') }));
      return;
    }
    if (report.verdict) pane.appendChild(ui.el('p', {}, [
      ui.el('strong', { text: t('mod.cerb_verdict') + ': ' }), report.verdict,
    ]));
    if (report.severity) pane.appendChild(ui.el('p', {
      text: t('mod.cerb_severity', report.severity),
    }));
    if (report.confidence !== undefined) pane.appendChild(ui.el('p', {
      text: t('mod.cerb_confidence', report.confidence),
    }));
    if (report.summary) {
      String(report.summary).split(/\n{2,}/).forEach(function (para) {
        pane.appendChild(ui.el('p', { text: para }));
      });
    }
    ['notable_actors', 'recommended_actions', 'unknowns'].forEach(function (key) {
      const entries = report[key];
      if (!Array.isArray(entries) || !entries.length) return;
      pane.appendChild(ui.el('h4', { text: t('mod.cerb_' + key) }));
      const list = ui.el('ul');
      entries.forEach(function (entry) {
        list.appendChild(ui.el('li', {
          text: typeof entry === 'string' ? entry : JSON.stringify(entry),
        }));
      });
      pane.appendChild(list);
    });
    if (report.verdict) ui.announce(report.verdict);
  }

  document.getElementById('mod-cerb-assess').addEventListener('click', async function (e) {
    const button = e.currentTarget;
    const status = document.getElementById('mod-cerb-status');
    button.disabled = true;
    status.textContent = t('mod.cerb_asking');
    try {
      const data = await ws.cerberusAiAssessment();
      renderReport(data.assessment);
      status.textContent = t('mod.cerb_asked');
    } catch (err) {
      fail(err, status);
    } finally {
      button.disabled = false;
    }
  });

  document.getElementById('mod-cerb-deliberate').addEventListener('click', async function (e) {
    const button = e.currentTarget;
    const status = document.getElementById('mod-cerb-status');
    button.disabled = true;
    status.textContent = t('mod.bw_thinking');
    try {
      const data = await ws.blackwallDeliberate();
      renderReport(data.verdict);
      if (data.status) renderCerberus(Object.assign({ blackwall: data.status }, {}));
      status.textContent = t('mod.bw_decided');
    } catch (err) {
      fail(err, status);
    } finally {
      button.disabled = false;
      loadCerberus();
    }
  });

  function cerberusIp() {
    const field = document.getElementById('mod-cerb-ip');
    const value = field.value.trim();
    if (!value) {
      ui.fieldError('mod-cerb-ip', t('err.required'));
      field.focus();
      return null;
    }
    ui.fieldError('mod-cerb-ip', '');
    return value;
  }

  document.getElementById('mod-cerb-ban').addEventListener('click', async function () {
    const ip = cerberusIp();
    if (!ip) return;
    const sure = await ui.confirmDialog(t('mod.cerb_ban_confirm', ip),
      { danger: true, title: t('mod.cerb_ban') });
    if (!sure) return;
    run(ws.cerberusBanIp(ip, true), t('mod.cerb_banned', ip)).then(loadCerberus);
  });

  document.getElementById('mod-cerb-unban').addEventListener('click', function () {
    const ip = cerberusIp();
    if (!ip) return;
    run(ws.cerberusUnbanIp(ip), t('mod.cerb_unbanned', ip)).then(loadCerberus);
  });

  document.getElementById('mod-cerb-whitelist').addEventListener('click', function () {
    const ip = cerberusIp();
    if (!ip) return;
    run(ws.cerberusWhitelist(ip, 'add'), t('mod.cerb_whitelisted', ip)).then(loadCerberus);
  });

  document.getElementById('mod-cerb-raise').addEventListener('click', async function () {
    const level = document.getElementById('mod-cerb-level').value;
    const sure = await ui.confirmDialog(t('mod.cerb_raise_confirm', level),
      { danger: true, title: t('mod.cerb_raise') });
    if (!sure) return;
    run(ws.cerberusLockdown(level, t('mod.cerb_manual_reason', user.username)),
      t('mod.cerb_raised', level)).then(loadCerberus);
  });

  document.getElementById('mod-cerb-standdown').addEventListener('click', function () {
    run(ws.cerberusUnlock(t('mod.cerb_manual_reason', user.username)),
      t('mod.cerb_stood_down')).then(loadCerberus);
  });

  // ---------- Boot ----------

  window.onLangChanged = function () {
    tabBar.buttons.forEach(function (btn, index) {
      btn.textContent = t(PANELS[index].key);
    });
    Object.keys(loaded).forEach(function (id) {
      const panel = PANELS.find(function (p) { return p.id === id; });
      if (panel) panel.load();
    });
  };

  document.getElementById('mod-role').textContent =
    t('mod.signed_in_as', user.username, Titan.session.role() || 'user');

  Titan.session.ws().then(function (socket) {
    ws = socket;
    if (!Titan.session.isModerator()) {
      // Not a refusal — the server would refuse anyway. It is said plainly
      // so somebody who followed a link knows why the page is empty.
      ui.setAlert($alert, t('mod.not_staff'), 'warning');
    }
    const wanted = (location.hash || '').replace('#', '');
    const start = PANELS.find(function (p) { return p.id === wanted; }) || PANELS[0];
    tabBar.select(start.id);
    loaded[start.id] = true;
    start.load();
  }).catch(function (err) {
    if (err && err.message === 'no-credentials') { Titan.session.toLogin(); return; }
    fail(err);
  });
})();
