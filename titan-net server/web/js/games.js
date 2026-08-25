// Titan-Net web — interactive games.
//
// A game here is narrated: the server's own worker writes what happens,
// speaks it, plays sound effects, and asks the players what they do next.
// So the important part of this page is not a board — it is a live region
// that reads each new line as it lands, an input that sends the next move,
// and audio that actually plays.
(function () {
  'use strict';

  const t = Titan.t;
  const ui = Titan.ui;

  const $alert = document.getElementById('games-alert');
  const $index = document.getElementById('games-index');
  const $play = document.getElementById('game-play');
  const $log = document.getElementById('play-log');
  const $turn = document.getElementById('play-turn');
  const $players = document.getElementById('play-players');
  const $state = document.getElementById('play-state');
  const $heading = document.getElementById('play-heading');
  const $input = document.getElementById('play-input');
  const $menuDialog = document.getElementById('game-menu-dialog');

  let ws = null;
  let games = [];
  let sessions = [];
  let session = null;      // the table being played
  let myTurn = false;

  const user = Titan.session.requireLogin();
  if (!user) return;

  function fail(err, node) {
    const text = (err && err.message) || t('err.generic');
    if (node) node.textContent = text;
    else ui.setAlert($alert, text, 'error');
    ui.announce(text, 'assertive');
  }

  // ---------- Audio ----------
  // Narration is base64 audio on the socket; sound effects are numbered
  // attachments fetched once and kept. Both go through one element per
  // layer so "stop the music" really stops the music.
  const layers = {};
  const attachments = {};
  let audioAllowed = true;

  function layerAudio(name) {
    const key = name || 'default';
    if (!layers[key]) {
      layers[key] = new Audio();
      layers[key].preload = 'auto';
    }
    return layers[key];
  }

  function playBase64(data, mime, layer, opts) {
    if (!audioAllowed) return;
    opts = opts || {};
    try {
      const raw = atob(data);
      const buf = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i);
      const url = URL.createObjectURL(new Blob([buf], { type: mime || 'audio/mpeg' }));
      const audio = layerAudio(layer);
      if (audio.src && audio.src.indexOf('blob:') === 0) URL.revokeObjectURL(audio.src);
      audio.src = url;
      audio.loop = !!opts.loop;
      audio.volume = opts.volume === undefined ? 1 : Math.max(0, Math.min(1, opts.volume));
      const started = audio.play();
      if (started && started.catch) started.catch(function () {});
    } catch (e) {}
  }

  async function playAttachment(attachmentId, layer, opts) {
    if (!audioAllowed || !attachmentId) return;
    try {
      let cached = attachments[attachmentId];
      if (!cached) {
        const resp = await ws.request(
          { type: 'get_game_attachment', attachment_id: attachmentId },
          'game_attachment_response', 30000);
        if (!resp.success) return;
        cached = { data: resp.data, name: resp.file_name || '' };
        attachments[attachmentId] = cached;
      }
      playBase64(cached.data, guessMime(cached.name), layer, opts);
    } catch (e) {}
  }

  function guessMime(name) {
    const ext = String(name).toLowerCase().split('.').pop();
    if (ext === 'ogg') return 'audio/ogg';
    if (ext === 'wav') return 'audio/wav';
    if (ext === 'mp3') return 'audio/mpeg';
    return 'audio/mpeg';
  }

  document.getElementById('play-audio').addEventListener('change', function (e) {
    audioAllowed = e.target.checked;
    if (!audioAllowed) {
      Object.keys(layers).forEach(function (key) {
        try { layers[key].pause(); } catch (er) {}
      });
      ui.announce(t('games.audio_off'));
    } else {
      ui.announce(t('games.audio_on'));
    }
  });

  // ---------- The catalogue ----------

  function renderGames() {
    const list = document.getElementById('games-list');
    const status = document.getElementById('games-status');
    ui.clear(list);
    if (!games.length) { status.textContent = t('games.none'); return; }
    status.textContent = t('games.count', games.length);
    games.forEach(function (game) {
      const titleId = 'game-' + game.id;
      const actions = ui.el('div', { class: 'flex card-actions' }, [
        ui.el('button', {
          type: 'button', text: t('games.start'),
          'aria-label': t('games.start_label', game.name),
          onclick: function () { startSession(game); },
        }),
      ]);
      if (Number(game.creator_id) === Number(user.id) || Titan.session.isModerator()) {
        actions.appendChild(ui.el('button', {
          type: 'button', class: 'btn-danger', text: t('common.delete'),
          'aria-label': t('games.delete_label', game.name),
          onclick: function () { removeGame(game); },
        }));
      }
      list.appendChild(ui.el('li', {}, [
        ui.el('article', { class: 'card', 'aria-labelledby': titleId }, [
          ui.el('h3', { id: titleId, text: game.name }),
          ui.el('p', { class: 'meta', text: [
            t('repo.by', game.creator_username || '?'),
            game.max_players ? t('games.max_players', game.max_players) : null,
          ].filter(Boolean).join(' · ') }),
          ui.el('p', { text: game.description || '' }),
          actions,
        ]),
      ]));
    });
  }

  function renderSessions() {
    const list = document.getElementById('sessions-list');
    const status = document.getElementById('sessions-status');
    ui.clear(list);
    if (!sessions.length) { status.textContent = t('games.no_sessions'); return; }
    status.textContent = t('games.sessions_count', sessions.length);
    sessions.forEach(function (entry) {
      const titleId = 'session-' + entry.id;
      // The listing is deliberately small — the server sends a count, not
      // the whole player list, so a busy server does not ship every table's
      // roster to everybody.
      list.appendChild(ui.el('li', {}, [
        ui.el('article', { class: 'card', 'aria-labelledby': titleId }, [
          ui.el('h3', { id: titleId, text: entry.game_name || ('#' + entry.id) }),
          ui.el('p', { class: 'meta', text: [
            t('games.hosted_by', entry.host_username || '?'),
            t('games.player_count', entry.player_count || 0),
            t('games.session_state_' + (entry.status || 'lobby')),
          ].join(' · ') }),
          ui.el('div', { class: 'flex card-actions' }, [
            ui.el('button', {
              type: 'button', text: t('games.join'),
              'aria-label': t('games.join_label', entry.game_name || ('#' + entry.id)),
              onclick: function () { joinSession(entry.id); },
            }),
          ]),
        ]),
      ]));
    });
  }

  async function loadGames() {
    const status = document.getElementById('games-status');
    status.textContent = t('common.loading');
    try {
      const resp = await ws.listGames();
      if (!resp.success) throw new Error(resp.error);
      games = resp.games || [];
      renderGames();
    } catch (err) {
      fail(err, status);
    }
  }

  async function loadSessions() {
    const status = document.getElementById('sessions-status');
    status.textContent = t('common.loading');
    try {
      const resp = await ws.listGameSessions();
      if (!resp.success) throw new Error(resp.error);
      sessions = resp.sessions || [];
      renderSessions();
    } catch (err) {
      fail(err, status);
    }
  }

  async function removeGame(game) {
    const sure = await ui.confirmDialog(t('games.delete_confirm', game.name),
      { danger: true, title: t('common.delete'), confirmLabel: t('common.delete') });
    if (!sure) return;
    try {
      const resp = await ws.deleteGame(game.id);
      if (!resp.success) throw new Error(resp.error);
      ui.setAlert($alert, t('games.deleted', game.name), 'success');
      loadGames();
    } catch (err) {
      fail(err);
    }
  }

  // ---------- Playing ----------

  async function startSession(game) {
    try {
      const resp = await ws.startGameSession(game.id);
      if (!resp.success) throw new Error(resp.error);
      await enterSession(resp.session_id);
    } catch (err) {
      fail(err);
    }
  }

  async function joinSession(sessionId) {
    try {
      const resp = await ws.joinGameSession(sessionId);
      if (!resp.success) throw new Error(resp.error);
      await enterSession(sessionId);
    } catch (err) {
      fail(err);
    }
  }

  // The session row carries the turn ORDER and the index into it, not the
  // player whose turn it is — that is derived, here and in the desktop
  // client, so both agree even when a player has just left.
  function activePlayerOf(record) {
    const order = (record && record.turn_order) || [];
    if (!order.length) return null;
    const index = Number(record.current_turn_idx || 0) % order.length;
    return order[index];
  }

  async function enterSession(sessionId) {
    const resp = await ws.getGameSession(sessionId);
    if (!resp.success) throw new Error(resp.error);
    session = resp.session || resp;
    session.id = sessionId;
    $index.hidden = true;
    $play.hidden = false;
    $heading.textContent = session.game_name || t('games.table');
    document.title = ($heading.textContent) + ' — Titan-Net';
    ui.clear($log);
    renderPlayers();
    renderSheet();
    renderState();
    updateTurn(activePlayerOf(session));
    appendLine('system', t('games.joined', $heading.textContent));
    ui.focusHeading($heading);
  }

  function leaveView() {
    speakUp();
    session = null;
    document.title = t('games.page_title');
    $play.hidden = true;
    $index.hidden = false;
    Object.keys(layers).forEach(function (key) { try { layers[key].pause(); } catch (e) {} });
    loadSessions();
    ui.focusHeading($index.querySelector('h1'));
  }

  function renderPlayers() {
    ui.clear($players);
    const list = (session && session.players) || [];
    list.filter(function (p) { return !p.left_at; }).forEach(function (player) {
      const active = Number(player.user_id) === Number(session.active_user_id);
      $players.appendChild(ui.el('li', {}, [
        ui.el('span', {
          text: player.username + (active ? ' — ' + t('games.their_turn') : ''),
        }),
      ]));
    });
  }

  // The player's own sheet — statistics, what they carry, what they wear.
  // The server keeps these in a shape it can do arithmetic on; this turns
  // that shape into words, because a screen reader reading out braces and
  // the word "value" is the same as not showing it at all.
  function mySheet() {
    const players = (session && session.players) || [];
    const mine = players.filter(function (p) {
      return Number(p.user_id) === Number(user.id);
    })[0];
    return (mine && mine.character_state) || {};
  }

  function renderSheet() {
    const sheet = mySheet();
    const $stats = document.getElementById('play-stats');
    const $pack = document.getElementById('play-inventory');
    const $worn = document.getElementById('play-equipment');
    ui.clear($stats);
    ui.clear($pack);
    ui.clear($worn);

    const stats = sheet.stats && typeof sheet.stats === 'object' ? sheet.stats : {};
    const statNames = Object.keys(stats);
    if (!statNames.length) {
      $stats.appendChild(ui.el('dt', { text: t('games.stats') }));
      $stats.appendChild(ui.el('dd', { text: t('games.nothing_yet') }));
    } else {
      statNames.forEach(function (name) {
        const entry = stats[name];
        const value = (entry && typeof entry === 'object') ? entry.value : entry;
        const ceiling = (entry && typeof entry === 'object') ? entry.max : null;
        $stats.appendChild(ui.el('dt', { text: name }));
        $stats.appendChild(ui.el('dd', {
          text: (ceiling === null || ceiling === undefined)
            ? String(value)
            : t('games.of_max', value, ceiling),
        }));
      });
    }

    const carried = Array.isArray(sheet.inventory) ? sheet.inventory : [];
    if (!carried.length) {
      $pack.appendChild(ui.el('li', { text: t('games.carrying_nothing') }));
    } else {
      carried.forEach(function (entry) {
        const name = entry && entry.item ? entry.item : String(entry);
        const quantity = entry && entry.quantity;
        let label = (quantity && quantity !== 1)
          ? t('games.item_count', name, quantity) : name;
        const properties = entry && entry.properties;
        if (properties && typeof properties === 'object') {
          const detail = Object.keys(properties).slice(0, 4).map(function (key) {
            return key + ' ' + properties[key];
          }).join(', ');
          if (detail) label = t('games.item_detail', label, detail);
        }
        $pack.appendChild(ui.el('li', { text: label }));
      });
    }

    const worn = sheet.equipment && typeof sheet.equipment === 'object'
      ? sheet.equipment : {};
    const slots = Object.keys(worn);
    if (!slots.length) {
      $worn.appendChild(ui.el('dt', { text: t('games.worn') }));
      $worn.appendChild(ui.el('dd', { text: t('games.wearing_nothing') }));
    } else {
      slots.forEach(function (slot) {
        $worn.appendChild(ui.el('dt', { text: slot }));
        $worn.appendChild(ui.el('dd', { text: String(worn[slot]) }));
      });
    }
  }

  function renderState() {
    ui.clear($state);
    const state = (session && session.state) || {};
    const keys = Object.keys(state);
    if (!keys.length) {
      $state.appendChild(ui.el('dt', { text: t('games.state') }));
      $state.appendChild(ui.el('dd', { text: t('games.state_empty') }));
      return;
    }
    keys.forEach(function (key) {
      $state.appendChild(ui.el('dt', { text: key }));
      $state.appendChild(ui.el('dd', {
        text: typeof state[key] === 'string' ? state[key] : JSON.stringify(state[key]),
      }));
    });
  }

  function updateTurn(activeUserId) {
    if (!session) return;
    session.active_user_id = activeUserId;
    myTurn = Number(activeUserId) === Number(user.id);
    const who = ((session.players || []).find(function (p) {
      return Number(p.user_id) === Number(activeUserId);
    }) || {}).username;
    $turn.textContent = myTurn
      ? t('games.your_turn')
      : (who ? t('games.turn_of', who) : t('games.no_turn'));
    renderPlayers();
  }

  // Each line is appended to a role="log" region, which is what makes a
  // screen reader read the new one and leave the rest reviewable.
  function appendLine(actor, text) {
    if (!text) return;
    const line = ui.el('p', {}, [
      ui.el('span', { class: 'log-actor', text: actorName(actor) + ': ' }),
      String(text),
    ]);
    $log.appendChild(line);
    $log.scrollTop = $log.scrollHeight;
    // Keep the log from growing without bound in a long session.
    while ($log.childElementCount > 500) $log.removeChild($log.firstChild);
  }

  function actorName(actor) {
    if (actor === 'gm' || actor === 'ai') return t('games.narrator');
    if (actor === 'system') return t('games.system');
    return actor;
  }

  document.getElementById('play-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    const text = $input.value.trim();
    if (!text || !session) return;
    $input.value = '';
    try {
      const resp = await ws.gamePlayerAction(session.id, undefined, { text: text });
      if (!resp.success) throw new Error(resp.error);
    } catch (err) {
      fail(err);
    }
  });

  document.getElementById('play-advance').addEventListener('click', async function () {
    if (!session) return;
    try {
      const resp = await ws.gameAdvanceTurn(session.id);
      if (!resp.success) throw new Error(resp.error);
    } catch (err) {
      fail(err);
    }
  });

  document.getElementById('play-leave').addEventListener('click', async function () {
    if (!session) return;
    try { await ws.leaveGameSession(session.id); } catch (err) {}
    leaveView();
  });

  document.getElementById('play-end').addEventListener('click', async function () {
    if (!session) return;
    const sure = await ui.confirmDialog(t('games.end_confirm'),
      { danger: true, title: t('games.end') });
    if (!sure) return;
    try {
      const resp = await ws.gameEndSession(session.id);
      if (!resp.success) throw new Error(resp.error);
    } catch (err) {
      fail(err);
    }
  });

  // ---------- The game asking a question ----------

  function showMenu(prompt, items) {
    document.getElementById('game-menu-prompt').textContent = prompt || t('games.choose');
    const list = document.getElementById('game-menu-items');
    ui.clear(list);
    // The prompt and every option also go into the log, so a player can
    // review the choices after picking one instead of losing them.
    appendLine('system', prompt || t('games.choose'));
    items.forEach(function (item, index) {
      appendLine('system', (index + 1) + '. ' + item.label);
      list.appendChild(ui.el('li', {}, [
        ui.el('button', {
          type: 'button', class: 'row-button', text: item.label,
          onclick: function () {
            ui.closeDialog($menuDialog);
            if (!session) return;
            ws.gamePlayerAction(session.id, undefined, { text: item.label })
              .catch(function (err) { fail(err); });
          },
        }),
      ]));
    });
    if (Titan.sounds) Titan.sounds.play('notification');
    ui.openDialog($menuDialog, list.querySelector('button'));
  }

  document.getElementById('game-menu-cancel').addEventListener('click', function () {
    ui.closeDialog($menuDialog);
  });

  // ---------- Speaking to the game ----------
  // The narrator listens as well as reads: the microphone frames go up as
  // `game_voice_chunk`, and what the player said comes back as a
  // transcription every other player at the table sees.
  let gameVoice = null;
  let speaking = false;
  const $speak = document.getElementById('play-speak');

  async function speakDown() {
    if (speaking || !session) return;
    speaking = true;
    $speak.setAttribute('aria-pressed', 'true');
    $speak.querySelector('span').textContent = t('games.speaking');
    try {
      if (!gameVoice) {
        gameVoice = new Titan.VoiceClient(ws);
        gameVoice.setUser(user.id);
        gameVoice.setSink(function (chunk) {
          if (session) ws.gameVoiceChunk(session.id, chunk);
        });
      }
      if (!gameVoice.live) await gameVoice.start();
    } catch (err) {
      speaking = false;
      $speak.setAttribute('aria-pressed', 'false');
      $speak.querySelector('span').textContent = t('games.speak');
      ui.announce((err && err.message) || t('voice.mic_denied'), 'assertive');
    }
  }

  function speakUp() {
    if (!speaking) return;
    speaking = false;
    $speak.setAttribute('aria-pressed', 'false');
    $speak.querySelector('span').textContent = t('games.speak');
    try { if (gameVoice && gameVoice.live) gameVoice.stop(); } catch (e) {}
  }

  if ($speak) {
    $speak.addEventListener('pointerdown', function (e) { e.preventDefault(); speakDown(); });
    $speak.addEventListener('pointerup', speakUp);
    $speak.addEventListener('pointercancel', speakUp);
    $speak.addEventListener('pointerleave', speakUp);
    $speak.addEventListener('keydown', function (e) {
      if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); speakDown(); }
    });
    $speak.addEventListener('keyup', function (e) {
      if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); speakUp(); }
    });
    // An open microphone the player has forgotten about is the worst
    // failure this control has, so losing the focus closes it.
    $speak.addEventListener('blur', speakUp);
    window.addEventListener('blur', speakUp);
  }

  // ---------- Writing a game ----------
  // A game is a prompt plus its files. The rules and any rule files go
  // into the game master's system instruction; the sounds are listed to it
  // by name so it plays real ones instead of inventing ids.

  const $newDialog = document.getElementById('games-new-dialog');

  function readAsBase64(file) {
    return new Promise(function (resolve, reject) {
      const reader = new FileReader();
      reader.onload = function () {
        const result = String(reader.result || '');
        resolve(result.slice(result.indexOf(',') + 1));
      };
      reader.onerror = function () { reject(new Error(t('games.file_failed', file.name))); };
      reader.readAsDataURL(file);
    });
  }

  document.getElementById('games-new').addEventListener('click', function () {
    document.getElementById('games-new-form').reset();
    document.getElementById('gn-progress').textContent = '';
    ui.openDialog($newDialog, document.getElementById('gn-name'));
  });
  document.getElementById('gn-cancel').addEventListener('click', function () {
    ui.closeDialog($newDialog);
  });

  document.getElementById('games-new-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    const $progress = document.getElementById('gn-progress');
    const $submit = document.getElementById('gn-submit');
    const name = document.getElementById('gn-name');
    const key = document.getElementById('gn-key');

    ui.fieldError('gn-name', '');
    ui.fieldError('gn-key', '');
    let bad = null;
    if (!key.value.trim()) { ui.fieldError('gn-key', t('err.required')); bad = key; }
    if (!name.value.trim()) { ui.fieldError('gn-name', t('err.required')); bad = name; }
    if (bad) { bad.focus(); return; }

    const folder = document.getElementById('gn-folder').value.trim();
    const attachments = [];
    $submit.disabled = true;
    try {
      const ruleFiles = document.getElementById('gn-rule-files').files;
      for (let i = 0; i < ruleFiles.length; i++) {
        $progress.textContent = t('games.reading_file', ruleFiles[i].name);
        attachments.push({
          type: 'prompt_txt',
          name: ruleFiles[i].name,
          folder_path: folder,
          data_b64: await readAsBase64(ruleFiles[i]),
        });
      }
      const sounds = document.getElementById('gn-sounds').files;
      for (let i = 0; i < sounds.length; i++) {
        $progress.textContent = t('games.reading_file', sounds[i].name);
        attachments.push({
          type: 'sound',
          name: sounds[i].name,
          data_b64: await readAsBase64(sounds[i]),
        });
      }

      $progress.textContent = t('games.creating');
      const resp = await ws.createGame({
        name: name.value.trim(),
        description: document.getElementById('gn-description').value.trim(),
        provider: 'gemini',
        api_key: key.value,
        rules_text: document.getElementById('gn-rules').value.trim(),
        max_players: Number(document.getElementById('gn-players').value) || 6,
        max_minutes: Number(document.getElementById('gn-minutes').value) || 120,
        max_tokens: Number(document.getElementById('gn-tokens').value) || 200000,
        attachments: attachments,
      });
      if (!resp.success) throw new Error(resp.error);
      ui.closeDialog($newDialog);
      if (Titan.sounds) Titan.sounds.play('titannet_success');
      ui.setAlert($alert, t('games.created', resp.name || name.value.trim(),
        (resp.attachments || []).length), 'success');
      await loadGames();
    } catch (err) {
      $progress.textContent = '';
      ui.setAlert($alert, (err && err.message) || t('err.generic'), 'error');
      ui.announce((err && err.message) || t('err.generic'), 'assertive');
    } finally {
      $submit.disabled = false;
    }
  });

  // ---------- Tabs ----------

  const tabBar = ui.tabs(document.getElementById('games-tabs'), [
    { id: 'games', label: t('games.available'), panel: 'games-panel-games' },
    { id: 'sessions', label: t('games.sessions'), panel: 'games-panel-sessions' },
  ], function (entry) {
    document.getElementById('games-panel-games').hidden = entry.id !== 'games';
    document.getElementById('games-panel-sessions').hidden = entry.id !== 'sessions';
    if (entry.id === 'sessions') loadSessions();
  });

  document.getElementById('games-refresh').addEventListener('click', function () {
    const which = tabBar.current();
    if (which && which.id === 'sessions') loadSessions();
    else loadGames();
  });

  window.onLangChanged = function () {
    tabBar.buttons[0].textContent = t('games.available');
    tabBar.buttons[1].textContent = t('games.sessions');
    renderGames();
    renderSessions();
  };

  // ---------- Live events ----------

  function mine(detail) {
    return session && Number(detail.session_id) === Number(session.id);
  }

  // Narration said by this browser, when the table has no shared
  // narrator. The line is already in the log, so this only speaks it -
  // and it goes through the site's own TTS module, which honours the
  // reader's voice, rate and "speak nothing" preference.
  function sayLocally(text, interrupt) {
    if (!text) return;
    if (!Titan.tts || !Titan.tts.speak) return;
    try {
      Titan.tts.speak(text, { interrupt: !!interrupt });
    } catch (err) {
      /* a browser with no speech synthesis still shows the line */
    }
  }

  Titan.session.ws().then(function (socket) {
    ws = socket;

    ws.addEventListener('msg:game_ai_text', function (e) {
      if (!mine(e.detail)) return;
      appendLine(e.detail.actor || 'gm', e.detail.text);
      // Who says it out loud. The AI is asked for TEXT now and the
      // session host's own Titan TTS narrates for the table, so
      // `spoken` true means audio is on its way and saying it here as
      // well would be the same sentence twice in two voices. False
      // means nobody is narrating centrally and this browser says it
      // at once - which is as fast as narration can possibly be. A
      // message with no `spoken` at all is an older server still
      // sending the model's own audio, and staying quiet is right.
      if (e.detail.spoken === false) sayLocally(e.detail.text);
    });
    ws.addEventListener('msg:game_ai_audio', function (e) {
      if (!mine(e.detail)) return;
      playBase64(e.detail.audio_b64, e.detail.mime_type, 'narration');
    });
    ws.addEventListener('msg:game_speak_locally', function (e) {
      // The host was asked to narrate this line and could not.
      if (!mine(e.detail)) return;
      sayLocally(e.detail.text, e.detail.interrupt);
    });
    ws.addEventListener('msg:game_player_action', function (e) {
      if (!mine(e.detail)) return;
      appendLine(e.detail.username || '?', e.detail.text);
    });
    ws.addEventListener('msg:game_player_speech', function (e) {
      if (!mine(e.detail)) return;
      if (e.detail.text) appendLine(e.detail.username || '?', e.detail.text);
    });
    ws.addEventListener('msg:game_turn_changed', function (e) {
      if (!mine(e.detail)) return;
      updateTurn(e.detail.active_user_id);
      if (Titan.sounds) Titan.sounds.play('notification');
    });
    ws.addEventListener('msg:game_player_joined', function (e) {
      if (!mine(e.detail)) return;
      appendLine('system', t('games.player_joined', e.detail.username || '?'));
      refreshSession();
    });
    ws.addEventListener('msg:game_player_left', function (e) {
      if (!mine(e.detail)) return;
      appendLine('system', t('games.player_left', e.detail.username || '?'));
      refreshSession();
    });
    ws.addEventListener('msg:game_state_changed', function (e) {
      if (!mine(e.detail)) return;
      refreshSession();
    });
    // The richer message: WHICH number or thing moved, so the player is
    // told rather than having to go and look.
    ws.addEventListener('msg:game_character_changed', function (e) {
      const detail = e.detail;
      if (!mine(detail)) return;
      refreshSession();
      if (Number(detail.user_id) !== Number(user.id)) return;
      const change = detail.change || {};
      if (change.kind === 'stat') {
        appendLine('system', change.by
          ? t('games.stat_changed', change.stat, change.by > 0 ? '+' + change.by : change.by, change.value)
          : t('games.stat_set', change.stat, change.value));
      } else if (change.kind === 'item') {
        appendLine('system', change.by > 0
          ? t('games.item_gained', change.item, change.by, change.quantity)
          : t('games.item_lost', change.item, Math.abs(change.by || 0), change.quantity));
      } else if (change.kind === 'equipment') {
        appendLine('system', change.item
          ? t('games.equipped', change.item, change.slot)
          : t('games.unequipped', change.removed || '', change.slot));
      }
    });
    ws.addEventListener('msg:game_menu', function (e) {
      const detail = e.detail;
      if (!mine(detail)) return;
      // A menu aimed at one player is only for them.
      if (detail.target_user_id && Number(detail.target_user_id) !== Number(user.id)) return;
      showMenu(detail.prompt, detail.items || []);
    });
    ws.addEventListener('msg:game_play_sound', function (e) {
      if (!mine(e.detail)) return;
      const detail = e.detail;
      if (detail.label) appendLine('system', t('games.sound', detail.label));
      playAttachment(detail.attachment_id, detail.layer, {
        loop: detail.loop, volume: detail.volume,
      });
    });
    ws.addEventListener('msg:game_stop_sound', function (e) {
      if (!mine(e.detail)) return;
      const audio = layers[e.detail.layer || 'default'];
      if (audio) { try { audio.pause(); } catch (er) {} }
    });
    ws.addEventListener('msg:game_set_volume', function (e) {
      if (!mine(e.detail)) return;
      const audio = layers[e.detail.layer || 'default'];
      if (audio) audio.volume = Math.max(0, Math.min(1, Number(e.detail.volume)));
    });
    ws.addEventListener('msg:game_token_warning', function (e) {
      if (!mine(e.detail)) return;
      appendLine('system', t('games.token_warning',
        e.detail.tokens_used, e.detail.max_tokens));
    });
    ws.addEventListener('msg:game_session_ended', function (e) {
      if (!mine(e.detail)) return;
      appendLine('system', t('games.ended', e.detail.reason || ''));
      ui.announce(t('games.ended', e.detail.reason || ''));
      setTimeout(leaveView, 1500);
    });
    ws.addEventListener('msg:game_session_started', function () {
      if (!session) loadSessions();
    });
    ws.addEventListener('msg:game_new', function () {
      if (!session) loadGames();
    });

    return loadGames();
  }).catch(function (err) {
    if (err && err.message === 'no-credentials') { Titan.session.toLogin(); return; }
    fail(err);
  });

  async function refreshSession() {
    if (!session) return;
    try {
      const resp = await ws.getGameSession(session.id);
      if (!resp.success) return;
      const fresh = resp.session || resp;
      session.players = fresh.players || session.players;
      session.state = fresh.state || session.state;
      session.turn_order = fresh.turn_order || session.turn_order;
      session.current_turn_idx = fresh.current_turn_idx;
      renderPlayers();
      renderSheet();
      renderState();
      updateTurn(activePlayerOf(fresh));
    } catch (err) {}
  }
})();
