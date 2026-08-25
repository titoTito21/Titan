// Titan-Net web — the Feedback Hub.
//
// The same thing the desktop client's feedback_hub.py is: a list of
// problems and ideas, one tab per kind, a vote per person, and a status
// only a moderator can change. Interaction is deliberately the same as the
// rest of the site — a tab bar the arrows cycle, a list of real buttons,
// and a dialog the browser traps the focus inside.
(function () {
  'use strict';

  const t = Titan.t;
  const ui = Titan.ui;

  const $alert = document.getElementById('fb-alert');
  const $list = document.getElementById('fb-list');
  const $status = document.getElementById('fb-status');
  const $heading = document.getElementById('fb-list-heading');
  const $tabs = document.getElementById('fb-tabs');
  const $sort = document.getElementById('fb-sort');

  const $readDialog = document.getElementById('fb-read');
  const $newDialog = document.getElementById('fb-new-dialog');

  // What a moderator may set an entry to. The server rejects anything
  // else, so this list is a convenience, not the rule.
  const STATUSES = {
    feedback: ['pending', 'next_version', 'considering', 'reproducing', 'resolved', 'wont_fix'],
    idea: ['pending', 'accepted', 'rejected'],
  };

  let ws = null;
  let items = [];
  let kind = 'feedback';
  let openItem = null;

  const user = Titan.session.requireLogin();
  if (!user) return;

  function statusLabel(value) {
    return t('fb.status.' + (value || 'pending'));
  }

  function isMine(item) {
    return item && Number(item.author_id) === Number(user.id);
  }

  // ---------- Rendering ----------

  function sortItems(list) {
    const mode = $sort.value;
    const copy = list.slice();
    if (mode === 'votes') {
      copy.sort(function (a, b) { return (b.upvote_count || 0) - (a.upvote_count || 0); });
    } else if (mode === 'status') {
      copy.sort(function (a, b) {
        return String(a.status || '').localeCompare(String(b.status || ''));
      });
    } else {
      copy.sort(function (a, b) {
        return String(b.updated_at || '').localeCompare(String(a.updated_at || ''));
      });
    }
    return copy;
  }

  function voteButton(item) {
    const voted = !!item.viewer_upvoted;
    const mine = isMine(item);
    const btn = ui.el('button', {
      type: 'button',
      class: 'btn-secondary',
      'aria-pressed': voted ? 'true' : 'false',
      // The count belongs in the accessible name: "Vote, 4 votes" tells a
      // screen-reader user what pressing it does AND where it stands, which
      // a bare number beside a button does not.
      'aria-label': t(voted ? 'fb.unvote_label' : 'fb.vote_label',
        item.title, item.upvote_count || 0),
      text: t('fb.votes', item.upvote_count || 0),
    });
    if (mine) {
      // The server refuses an author's vote on their own entry, so the
      // button says why rather than failing when pressed.
      btn.disabled = true;
      btn.setAttribute('aria-label', t('fb.vote_own', item.upvote_count || 0));
      btn.removeAttribute('aria-pressed');
    } else {
      btn.addEventListener('click', function () { toggleVote(item, btn); });
    }
    return btn;
  }

  function statusControl(item) {
    if (!Titan.session.isModerator()) {
      return ui.el('span', { class: 'badge badge-status', text: statusLabel(item.status) });
    }
    const id = 'fb-status-' + item.id;
    const select = ui.el('select', { id: id, 'aria-label': t('fb.status_for', item.title) });
    (STATUSES[item.item_type] || STATUSES.feedback).forEach(function (value) {
      const option = ui.el('option', { value: value, text: statusLabel(value) });
      if ((item.status || 'pending') === value) option.selected = true;
      select.appendChild(option);
    });
    select.addEventListener('change', function () { changeStatus(item, select); });
    return ui.el('span', { class: 'inline-field' }, [
      ui.el('span', { class: 'sr-only', id: id + '-label', text: t('fb.status_for', item.title) }),
      select,
    ]);
  }

  function render() {
    ui.clear($list);
    const shown = sortItems(items);
    $heading.textContent = t(kind === 'idea' ? 'fb.ideas' : 'fb.feedback');
    if (!shown.length) {
      $status.textContent = t('fb.empty');
      return;
    }
    $status.textContent = t('fb.count', shown.length);

    shown.forEach(function (item) {
      const titleId = 'fb-item-' + item.id;
      const open = ui.el('button', {
        type: 'button',
        class: 'link-button',
        text: item.title,
        onclick: function () { openEntry(item.id); },
      });
      const meta = [
        t('fb.by', item.author_username || '?'),
        ui.timeText(item.created_at),
      ];
      if (item.attachment_name) meta.push(t('fb.has_attachment'));

      const actions = ui.el('div', { class: 'flex card-actions' }, [
        voteButton(item),
        statusControl(item),
      ]);
      if (isMine(item) || Titan.session.isModerator()) {
        actions.appendChild(ui.el('button', {
          type: 'button',
          class: 'btn-danger',
          text: t('common.delete'),
          'aria-label': t('fb.delete_label', item.title),
          onclick: function () { removeEntry(item); },
        }));
      }

      const article = ui.el('article', { class: 'card', 'aria-labelledby': titleId }, [
        ui.el('h3', { id: titleId }, [open]),
        ui.el('p', { class: 'meta', text: meta.join(' · ') }),
        ui.el('p', { class: 'clamp', text: (item.content || '').slice(0, 240) }),
        actions,
      ]);
      $list.appendChild(ui.el('li', {}, [article]));
    });
  }

  // ---------- Server calls ----------

  function fail(err) {
    ui.setAlert($alert, (err && err.message) || t('err.generic'), 'error');
  }

  async function load() {
    ui.setBusy($list, true);
    $status.textContent = t('common.loading');
    try {
      const resp = await ws.listFeedback(kind);
      if (!resp.success) throw new Error(resp.error);
      items = resp.items || [];
      ui.setAlert($alert, '');
      render();
    } catch (err) {
      fail(err);
      $status.textContent = '';
    } finally {
      ui.setBusy($list, false);
    }
  }

  async function toggleVote(item, btn) {
    btn.disabled = true;
    try {
      const resp = await ws.upvoteFeedback(item.id);
      if (!resp.success) throw new Error(resp.error);
      item.upvote_count = resp.upvote_count;
      item.viewer_upvoted = resp.action === 'added';
      ui.announce(t(item.viewer_upvoted ? 'fb.voted' : 'fb.unvoted',
        item.title, item.upvote_count));
      if (Titan.sounds) Titan.sounds.play('titannet_success');
      render();
    } catch (err) {
      fail(err);
    } finally {
      btn.disabled = false;
    }
  }

  async function changeStatus(item, select) {
    const wanted = select.value;
    select.disabled = true;
    try {
      const resp = await ws.setFeedbackStatus(item.id, wanted);
      if (!resp.success) throw new Error(resp.error);
      item.status = wanted;
      ui.announce(t('fb.status_set', item.title, statusLabel(wanted)));
    } catch (err) {
      select.value = item.status || 'pending';
      fail(err);
    } finally {
      select.disabled = false;
    }
  }

  async function removeEntry(item) {
    const sure = await ui.confirmDialog(t('fb.delete_confirm', item.title), {
      danger: true,
      title: t('common.delete'),
      confirmLabel: t('common.delete'),
    });
    if (!sure) return;
    try {
      const resp = await ws.deleteFeedback(item.id);
      if (!resp.success) throw new Error(resp.error);
      items = items.filter(function (i) { return i.id !== item.id; });
      ui.announce(t('fb.deleted', item.title));
      render();
      // The list lost the row the focus was on, so put it somewhere real.
      ui.focusHeading($heading);
    } catch (err) {
      fail(err);
    }
  }

  // ---------- Reading one entry ----------

  async function openEntry(id) {
    try {
      const resp = await ws.getFeedback(id);
      if (!resp.success) throw new Error(resp.error);
      const item = resp.item;
      openItem = item;
      document.getElementById('fb-read-title').textContent = item.title;
      document.getElementById('fb-read-meta').textContent = [
        t('fb.by', item.author_username || '?'),
        ui.timeText(item.created_at),
        statusLabel(item.status),
        t('fb.votes', item.upvote_count || 0),
      ].join(' · ');

      // The body is plain text written by another user. It goes in as text
      // nodes, one paragraph per line, so nothing in it can be markup.
      const body = document.getElementById('fb-read-body');
      ui.clear(body);
      String(item.content || '').split(/\n{2,}/).forEach(function (para) {
        body.appendChild(ui.el('p', { text: para }));
      });

      const attach = document.getElementById('fb-read-attachment');
      ui.clear(attach);
      attach.hidden = !item.attachment_name;
      if (item.attachment_name) {
        attach.appendChild(ui.el('button', {
          type: 'button',
          class: 'btn-secondary',
          text: t('fb.download_attachment', item.attachment_name),
          onclick: function (e) { downloadAttachment(item, e.currentTarget); },
        }));
      }

      const vote = document.getElementById('fb-read-vote');
      const voted = !!item.viewer_upvoted;
      vote.textContent = t('fb.votes', item.upvote_count || 0);
      vote.disabled = isMine(item);
      if (!vote.disabled) {
        vote.setAttribute('aria-pressed', voted ? 'true' : 'false');
        vote.setAttribute('aria-label',
          t(voted ? 'fb.unvote_label' : 'fb.vote_label', item.title, item.upvote_count || 0));
      } else {
        vote.removeAttribute('aria-pressed');
        vote.setAttribute('aria-label', t('fb.vote_own', item.upvote_count || 0));
      }

      ui.openDialog($readDialog, body);
    } catch (err) {
      fail(err);
    }
  }

  async function downloadAttachment(item, button) {
    const original = button.textContent;
    button.disabled = true;
    button.textContent = t('common.loading');
    try {
      const resp = await ws.getFeedbackAttachment(item.id);
      if (!resp.success) throw new Error(resp.error);
      const raw = atob(resp.data);
      const buf = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i);
      const url = URL.createObjectURL(new Blob([buf]));
      const a = document.createElement('a');
      a.href = url;
      a.download = resp.attachment_name || 'attachment';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 30000);
      ui.announce(t('fb.attachment_saved', resp.attachment_name || ''));
    } catch (err) {
      fail(err);
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  }

  document.getElementById('fb-read-close').addEventListener('click', function () {
    ui.closeDialog($readDialog);
  });
  document.getElementById('fb-read-vote').addEventListener('click', function (e) {
    if (!openItem) return;
    toggleVote(openItem, e.currentTarget).then(function () {
      if (openItem) openEntry(openItem.id);
    });
  });

  // ---------- Creating an entry ----------

  document.getElementById('fb-new').addEventListener('click', function () {
    document.getElementById('fb-new-form').reset();
    document.getElementById('fb-new-progress').textContent = '';
    ui.fieldError('fb-new-title-input', '');
    ui.fieldError('fb-new-content', '');
    const wanted = kind === 'idea' ? 'fb-kind-idea' : 'fb-kind-feedback';
    document.getElementById(wanted).checked = true;
    ui.openDialog($newDialog, document.getElementById('fb-new-title-input'));
  });
  document.getElementById('fb-new-cancel').addEventListener('click', function () {
    ui.closeDialog($newDialog);
  });

  function fileToBase64(file) {
    return new Promise(function (resolve, reject) {
      const reader = new FileReader();
      reader.onload = function () {
        const result = String(reader.result || '');
        resolve(result.slice(result.indexOf(',') + 1));
      };
      reader.onerror = function () { reject(new Error(t('fb.attachment_failed'))); };
      reader.readAsDataURL(file);
    });
  }

  document.getElementById('fb-new-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    const $title = document.getElementById('fb-new-title-input');
    const $content = document.getElementById('fb-new-content');
    const $progress = document.getElementById('fb-new-progress');
    const $submit = document.getElementById('fb-new-submit');

    ui.fieldError('fb-new-title-input', '');
    ui.fieldError('fb-new-content', '');
    let bad = null;
    if (!$content.value.trim()) { ui.fieldError('fb-new-content', t('err.required')); bad = $content; }
    if (!$title.value.trim()) { ui.fieldError('fb-new-title-input', t('err.required')); bad = $title; }
    if (bad) { bad.focus(); return; }

    const chosen = document.querySelector('input[name="fb-kind"]:checked');
    const payload = {
      item_type: chosen ? chosen.value : 'feedback',
      title: $title.value.trim(),
      content: $content.value.trim(),
    };

    const file = document.getElementById('fb-new-file').files[0];
    $submit.disabled = true;
    try {
      if (file) {
        if (file.size > 12 * 1024 * 1024) throw new Error(t('fb.attachment_too_big'));
        $progress.textContent = t('fb.reading_attachment');
        payload.attachment_data = await fileToBase64(file);
        payload.attachment_name = file.name;
      }
      $progress.textContent = t('fb.sending');
      const resp = await ws.createFeedback(payload);
      if (!resp.success) throw new Error(resp.error);
      ui.closeDialog($newDialog);
      if (Titan.sounds) Titan.sounds.play('titannet_success');
      ui.setAlert($alert, t('fb.created', payload.title), 'success');
      if (payload.item_type !== kind) {
        kind = payload.item_type;
        tabBar.select(kind);
      }
      await load();
    } catch (err) {
      $progress.textContent = '';
      ui.setAlert($alert, (err && err.message) || t('err.generic'), 'error');
      ui.announce((err && err.message) || t('err.generic'), 'assertive');
    } finally {
      $submit.disabled = false;
    }
  });

  // ---------- Tabs and live updates ----------

  const tabBar = ui.tabs($tabs, [
    { id: 'feedback', label: t('fb.feedback'), panel: 'fb-panel' },
    { id: 'idea', label: t('fb.ideas'), panel: 'fb-panel' },
  ], function (entry) {
    kind = entry.id;
    load();
  });

  $sort.addEventListener('change', render);
  document.getElementById('fb-refresh').addEventListener('click', function () {
    load().then(function () { ui.announce(t('fb.refreshed')); });
  });

  window.onLangChanged = function () {
    render();
    tabBar.buttons[0].textContent = t('fb.feedback');
    tabBar.buttons[1].textContent = t('fb.ideas');
  };

  Titan.session.ws().then(function (socket) {
    ws = socket;

    // Somebody else's entry, vote or status change arrives on the socket.
    // The list is refreshed quietly — announcing every one of them would
    // talk over whatever the user is reading.
    ['feedback_new', 'feedback_upvote', 'feedback_status_changed', 'feedback_deleted']
      .forEach(function (type) {
        ws.addEventListener('msg:' + type, function () {
          if (!$newDialog.open) load();
        });
      });

    return load();
  }).catch(function (err) {
    if (err && err.message === 'no-credentials') { Titan.session.toLogin(); return; }
    fail(err);
  });
})();
