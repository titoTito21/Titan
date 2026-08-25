// Titan-Net groups -> forums -> threads -> topic (Elten-style)
(function () {
  'use strict';
  const t = Titan.t;
  const API = Titan.API;

  const views = {
    groups: document.getElementById('groups-view'),
    group: document.getElementById('group-view'),
    threads: document.getElementById('threads-view'),
    topic: document.getElementById('topic-view'),
    search: document.getElementById('search-view'),
  };

  // Groups list
  const $groupsStatus = document.getElementById('groups-status');
  const $groupsList = document.getElementById('groups-list');
  const $newGroupBtn = document.getElementById('new-group-btn');

  // Group (forums)
  const $groupTitle = document.getElementById('group-title');
  const $groupStatus = document.getElementById('group-status');
  const $forumsList = document.getElementById('forums-list');
  const $groupBack = document.getElementById('group-back');
  const $newForumBtn = document.getElementById('new-forum-btn');
  const $pendingBtn = document.getElementById('pending-members-btn');
  const $manageBtn = document.getElementById('manage-members-btn');

  // Threads
  const $threadsTitle = document.getElementById('threads-title');
  const $threadsStatus = document.getElementById('threads-status');
  const $threadsList = document.getElementById('threads-list');
  const $threadsBack = document.getElementById('threads-back');
  const $newThreadBtn = document.getElementById('new-thread-btn');

  // Search across every forum in every group
  const $searchForm = document.getElementById('forum-search');
  const $searchQ = document.getElementById('forum-q');
  const $searchHeading = document.getElementById('search-h1');
  const $searchStatus = document.getElementById('search-status');
  const $searchResults = document.getElementById('search-results');
  const $searchBack = document.getElementById('search-back');

  // Topic
  const $topicTitle = document.getElementById('topic-title');
  const $topicMeta = document.getElementById('topic-meta');
  const $topicBody = document.getElementById('topic-body');
  const $topicReplies = document.getElementById('topic-replies');
  const $topicBack = document.getElementById('topic-back');
  const $replyForm = document.getElementById('reply-form');
  const $replyContent = document.getElementById('reply-content');

  let currentGroup = null;
  let currentForum = null;
  let currentTopicId = null;
  // 'forum' (the usual drill-down) or 'search'. A topic reached from the
  // results list must not send the user back to a forum they never opened.
  let topicCameFrom = 'forum';

  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function showView(name) {
    Object.keys(views).forEach((k) => { views[k].hidden = (k !== name); });
  }

  function dialogOpen(dlg, focusEl) {
    if (typeof dlg.showModal === 'function') dlg.showModal();
    else dlg.setAttribute('open', '');
    if (focusEl) focusEl.focus();
  }
  function dialogClose(dlg) {
    if (dlg.close) dlg.close(); else dlg.removeAttribute('open');
  }

  function isMod(group) {
    return group && (group.my_role === 'owner' || group.my_role === 'moderator');
  }
  function isActiveMember(group) {
    return group && group.my_status === 'active';
  }

  // ---------- Groups list ----------
  function visibilityLabel(v) { return t('groups.visibility.' + v) || v; }
  function statusLabel(g) {
    if (g.my_status === 'active') {
      if (g.my_role === 'owner') return t('groups.status.owner');
      if (g.my_role === 'moderator') return t('groups.status.moderator');
      return t('groups.status.member');
    }
    if (g.my_status === 'pending') return t('groups.status.pending');
    return t('groups.status.none');
  }

  async function loadGroups() {
    showView('groups');
    $groupsStatus.textContent = t('groups.loading');
    $groupsList.innerHTML = '';
    try {
      const data = await API.listGroups();
      renderGroups(data.groups || []);
    } catch (e) {
      $groupsStatus.textContent = e.message || t('err.generic');
    }
  }

  function renderGroups(groups) {
    $groupsList.innerHTML = '';
    if (!groups.length) { $groupsStatus.textContent = t('groups.empty'); return; }
    $groupsStatus.textContent = '';
    const frag = document.createDocumentFragment();
    groups.forEach((g) => {
      const li = document.createElement('li');
      const card = document.createElement('article');
      card.className = 'card';
      card.setAttribute('aria-labelledby', 'group-' + g.id);
      const h3 = document.createElement('h3');
      h3.id = 'group-' + g.id;
      const a = document.createElement('a');
      a.href = '#';
      a.textContent = g.name;
      a.addEventListener('click', (e) => { e.preventDefault(); openGroup(g); });
      h3.appendChild(a);
      card.appendChild(h3);
      const meta = document.createElement('p');
      meta.className = 'meta';
      meta.textContent = [visibilityLabel(g.visibility), t('groups.members', g.member_count || 0), statusLabel(g)].join(' · ');
      card.appendChild(meta);
      if (g.description) {
        const d = document.createElement('p');
        d.textContent = g.description;
        card.appendChild(d);
      }
      const actions = document.createElement('p');
      const openBtn = document.createElement('button');
      openBtn.textContent = t('groups.open');
      openBtn.addEventListener('click', () => openGroup(g));
      actions.appendChild(openBtn);
      if (Titan.getUser()) {
        if (g.my_status === 'active' && g.my_role !== 'owner') {
          const leaveBtn = document.createElement('button');
          leaveBtn.className = 'btn btn-secondary';
          leaveBtn.textContent = t('groups.leave');
          leaveBtn.style.marginLeft = '.5rem';
          leaveBtn.addEventListener('click', () => doLeave(g));
          actions.appendChild(leaveBtn);
        } else if (!g.my_status && g.visibility !== 'hidden') {
          const joinBtn = document.createElement('button');
          joinBtn.textContent = t('groups.join');
          joinBtn.style.marginLeft = '.5rem';
          joinBtn.addEventListener('click', () => doJoin(g));
          actions.appendChild(joinBtn);
        }
      }
      card.appendChild(actions);
      li.appendChild(card);
      frag.appendChild(li);
    });
    $groupsList.appendChild(frag);
  }

  async function doJoin(g) {
    try {
      const resp = await API.joinGroup(g.id);
      if (resp.success) {
        if (resp.status === 'pending') Titan.announce(t('groups.pending_sent'));
        loadGroups();
      } else { Titan.announce(resp.error || t('err.generic')); }
    } catch (e) { Titan.announce(e.message || t('err.generic')); }
  }
  async function doLeave(g) {
    try {
      const resp = await API.leaveGroup(g.id);
      if (resp.success) loadGroups();
      else Titan.announce(resp.error || t('err.generic'));
    } catch (e) { Titan.announce(e.message || t('err.generic')); }
  }

  // ---------- Group (forums) ----------
  async function openGroup(group) {
    currentGroup = group;
    showView('group');
    $groupTitle.textContent = group.name;
    $newForumBtn.hidden = !isMod(group);
    $pendingBtn.hidden = !isMod(group);
    $manageBtn.hidden = !isMod(group);
    await loadForums();
  }

  async function loadForums() {
    if (!currentGroup) return;
    $groupStatus.textContent = t('groups.loading');
    $forumsList.innerHTML = '';
    try {
      const data = await API.listGroupForums(currentGroup.id);
      renderForums(data.forums || []);
    } catch (e) {
      $groupStatus.textContent = e.message || t('err.generic');
    }
  }

  function renderForums(forums) {
    $forumsList.innerHTML = '';
    if (!forums.length) { $groupStatus.textContent = t('groups.forums_empty'); return; }
    $groupStatus.textContent = '';
    const frag = document.createDocumentFragment();
    forums.forEach((f) => {
      const li = document.createElement('li');
      const card = document.createElement('article');
      card.className = 'card';
      card.setAttribute('aria-labelledby', 'forum-' + f.id);
      const h3 = document.createElement('h3');
      h3.id = 'forum-' + f.id;
      const a = document.createElement('a');
      a.href = '#';
      a.textContent = f.name;
      a.addEventListener('click', (e) => { e.preventDefault(); openForum(f); });
      h3.appendChild(a);
      card.appendChild(h3);
      const meta = document.createElement('p');
      meta.className = 'meta';
      meta.textContent = t('groups.forum.threads', f.topic_count || 0);
      card.appendChild(meta);
      if (f.description) {
        const d = document.createElement('p');
        d.textContent = f.description;
        card.appendChild(d);
      }
      if (isMod(currentGroup)) {
        const del = document.createElement('button');
        del.className = 'btn btn-secondary';
        del.textContent = t('groups.forum_delete');
        del.addEventListener('click', () => deleteForum(f));
        card.appendChild(del);
      }
      li.appendChild(card);
      frag.appendChild(li);
    });
    $forumsList.appendChild(frag);
  }

  async function deleteForum(f) {
    if (!window.confirm(t('groups.forum_delete.confirm'))) return;
    try {
      const resp = await API.deleteGroupForum(f.id);
      if (resp.success) loadForums();
      else Titan.announce(resp.error || t('err.generic'));
    } catch (e) { Titan.announce(e.message || t('err.generic')); }
  }

  // ---------- Threads ----------
  async function openForum(forum) {
    currentForum = forum;
    showView('threads');
    $threadsTitle.textContent = forum.name;
    $newThreadBtn.hidden = !(Titan.getUser() && isActiveMember(currentGroup));
    await loadThreads();
  }

  async function loadThreads() {
    if (!currentForum) return;
    $threadsStatus.textContent = t('repo.loading');
    $threadsList.innerHTML = '';
    try {
      const data = await API.listTopics(null, 100, currentForum.id);
      renderThreads(data.topics || []);
    } catch (e) {
      $threadsStatus.textContent = e.message || t('err.generic');
    }
  }

  function renderThreads(topics) {
    $threadsList.innerHTML = '';
    if (!topics.length) { $threadsStatus.textContent = t('forum.empty'); return; }
    $threadsStatus.textContent = '';
    const frag = document.createDocumentFragment();
    topics.forEach((topic) => {
      const li = document.createElement('li');
      const card = document.createElement('article');
      card.className = 'card';
      card.setAttribute('aria-labelledby', 'thread-' + topic.id);
      const h3 = document.createElement('h3');
      h3.id = 'thread-' + topic.id;
      const a = document.createElement('a');
      a.href = '#';
      a.textContent = topic.title;
      a.addEventListener('click', (e) => { e.preventDefault(); openTopic(topic.id); });
      h3.appendChild(a);
      if (topic.is_pinned) { const b = document.createElement('span'); b.className = 'badge'; b.textContent = t('forum.pinned'); h3.appendChild(document.createTextNode(' ')); h3.appendChild(b); }
      if (topic.is_locked) { const b = document.createElement('span'); b.className = 'badge'; b.textContent = t('forum.locked'); h3.appendChild(document.createTextNode(' ')); h3.appendChild(b); }
      card.appendChild(h3);
      const meta = document.createElement('p');
      meta.className = 'meta';
      const parts = [];
      if (topic.author_username) parts.push(t('forum.posted_by', topic.author_username));
      if (topic.reply_count != null) parts.push(t('forum.replies', topic.reply_count));
      meta.textContent = parts.join(' · ');
      card.appendChild(meta);
      li.appendChild(card);
      frag.appendChild(li);
    });
    $threadsList.appendChild(frag);
  }

  // ---------- Topic ----------
  async function openTopic(topicId, from) {
    currentTopicId = topicId;
    topicCameFrom = from || 'forum';
    showView('topic');
    $topicTitle.textContent = '…';
    $topicMeta.textContent = '';
    $topicBody.textContent = '';
    $topicReplies.innerHTML = '';
    try {
      const [topicResp, replyResp] = await Promise.all([
        API.getTopic(topicId),
        API.listReplies(topicId, 200),
      ]);
      const topic = topicResp.topic;
      $topicTitle.textContent = topic.title;
      const metaParts = [];
      if (topic.author_username) metaParts.push(t('forum.posted_by', topic.author_username));
      $topicMeta.textContent = metaParts.join(' · ');
      $topicBody.innerHTML = escapeHtml(topic.content).replace(/\n/g, '<br>');
      const replies = replyResp.replies || [];
      replies.forEach((r, idx) => {
        const li = document.createElement('li');
        const card = document.createElement('article');
        card.className = 'card';
        const headingId = 'reply-' + (r.id != null ? r.id : ('idx-' + idx));
        card.setAttribute('aria-labelledby', headingId);
        const h3 = document.createElement('h3');
        h3.id = headingId;
        h3.className = 'reply-heading';
        h3.textContent = t('forum.reply_heading', idx + 1, r.author_username || '?');
        card.appendChild(h3);
        const m = document.createElement('p');
        m.className = 'meta';
        m.textContent = r.created_at || '';
        card.appendChild(m);
        const c = document.createElement('div');
        c.innerHTML = escapeHtml(r.content || '').replace(/\n/g, '<br>');
        card.appendChild(c);
        // A moderator can edit or remove any reply; everyone else sees
        // the reply and nothing else.
        if (isStaff()) {
          const actions = document.createElement('p');
          actions.className = 'toolbar-row';
          actions.appendChild(replyButton(t('common.edit'),
            t('forum.mod.edit_reply_label', idx + 1), 'btn-secondary',
            () => editReply(r, c)));
          actions.appendChild(replyButton(t('common.delete'),
            t('forum.mod.delete_reply_label', idx + 1), 'btn-danger',
            () => removeReply(r, li)));
          card.appendChild(actions);
        }
        li.appendChild(card);
        $topicReplies.appendChild(li);
      });
      renderTopicModeration(topic);
      $topicTitle.focus();
    } catch (e) {
      $topicBody.textContent = e.message || t('err.generic');
    }
  }

  // ---------- Moderating a topic ----------
  //
  // Carried over from the old flat forum page, which was the only place
  // these existed - so a moderator using the groups tree (which is what
  // the desktop client has always used) could not pin, lock, move or
  // delete anything. The buttons are hidden for everybody else AND every
  // call is refused server-side, so the hiding is a courtesy, not a guard.

  function isStaff() {
    return !!(Titan.session && Titan.session.isModerator());
  }

  function replyButton(label, ariaLabel, cls, onClick) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = cls;
    btn.textContent = label;
    btn.setAttribute('aria-label', ariaLabel);
    btn.addEventListener('click', onClick);
    return btn;
  }

  async function editReply(reply, container) {
    const text = await Titan.ui.promptDialog(t('forum.mod.edit_reply'), {
      multiline: true,
      value: reply.content || '',
      required: true,
      title: t('common.edit'),
    });
    if (text === null) return;
    try {
      const resp = await API.editReply(reply.id, text);
      if (resp && resp.success === false) throw new Error(resp.error);
      reply.content = text;
      container.innerHTML = escapeHtml(text).replace(/\n/g, '<br>');
      Titan.announce(t('forum.mod.reply_edited'));
    } catch (err) {
      Titan.announce((err && err.message) || t('err.generic'), 'assertive');
    }
  }

  async function removeReply(reply, node) {
    const sure = await Titan.ui.confirmDialog(t('forum.mod.delete_reply_confirm'),
      { danger: true, title: t('common.delete'), confirmLabel: t('common.delete') });
    if (!sure) return;
    try {
      const resp = await API.deleteReply(reply.id);
      if (resp && resp.success === false) throw new Error(resp.error);
      node.remove();
      Titan.announce(t('forum.mod.reply_deleted'));
      // The focus was on a button that no longer exists.
      $topicTitle.focus();
    } catch (err) {
      Titan.announce((err && err.message) || t('err.generic'), 'assertive');
    }
  }

  function renderTopicModeration(topic) {
    const bar = document.getElementById('topic-mod');
    if (!bar) return;
    bar.hidden = !isStaff();
    if (bar.hidden) return;

    const pin = document.getElementById('topic-pin');
    const lock = document.getElementById('topic-lock');
    // aria-pressed carries the state, so a screen reader says "pinned,
    // pressed" rather than leaving the button meaning two things.
    pin.setAttribute('aria-pressed', topic.is_pinned ? 'true' : 'false');
    lock.setAttribute('aria-pressed', topic.is_locked ? 'true' : 'false');
    pin.textContent = topic.is_pinned ? t('forum.mod.unpin') : t('forum.mod.pin');
    lock.textContent = topic.is_locked ? t('forum.mod.unlock') : t('forum.mod.lock');

    pin.onclick = async () => {
      try {
        const wanted = !topic.is_pinned;
        const resp = await API.pinTopic(topic.id, wanted);
        if (resp && resp.success === false) throw new Error(resp.error);
        topic.is_pinned = wanted;
        renderTopicModeration(topic);
        Titan.announce(t(wanted ? 'forum.mod.pinned' : 'forum.mod.unpinned'));
      } catch (err) {
        Titan.announce((err && err.message) || t('err.generic'), 'assertive');
      }
    };
    lock.onclick = async () => {
      try {
        const wanted = !topic.is_locked;
        const resp = await API.lockTopic(topic.id, wanted);
        if (resp && resp.success === false) throw new Error(resp.error);
        topic.is_locked = wanted;
        renderTopicModeration(topic);
        Titan.announce(t(wanted ? 'forum.mod.locked' : 'forum.mod.unlocked'));
      } catch (err) {
        Titan.announce((err && err.message) || t('err.generic'), 'assertive');
      }
    };
    document.getElementById('topic-move').onclick = () => moveTopic(topic);
    document.getElementById('topic-delete').onclick = async () => {
      const sure = await Titan.ui.confirmDialog(
        t('forum.mod.delete_confirm', topic.title),
        { danger: true, title: t('common.delete'), confirmLabel: t('common.delete') });
      if (!sure) return;
      try {
        const resp = await API.deleteTopic(topic.id);
        if (resp && resp.success === false) throw new Error(resp.error);
        Titan.announce(t('forum.mod.deleted', topic.title));
        topicBack();
      } catch (err) {
        Titan.announce((err && err.message) || t('err.generic'), 'assertive');
      }
    };
  }

  // Moving a thread is part of why the two pages had to become one. On
  // the old flat forum the destination was typed in as a bare number,
  // because the forums were only ever listed on the groups page - so a
  // moderator had to go to the other page, read an id off it and carry it
  // back. Here the forums are already known, so it is CHOSEN from them.
  async function moveTopic(topic) {
    let options = [];
    try {
      const groups = (await API.listGroups()).groups || [];
      const lists = await Promise.all(groups.map(async (g) => {
        try {
          const resp = await API.listGroupForums(g.id);
          return (resp.forums || []).map((f) => ({
            value: String(f.id),
            label: t('forum.found_in', f.name, g.name),
          }));
        } catch (e) { return []; }
      }));
      lists.forEach((l) => { options = options.concat(l); });
    } catch (e) { options = []; }

    let forumId;
    if (options.length) {
      forumId = await Titan.ui.promptDialog(t('forum.mod.move_where'), {
        title: t('forum.mod.move'),
        required: true,
        options: options,
      });
    } else {
      // Nothing could be listed (offline, or a member of no group that
      // has forums) - ask for the number rather than refuse the action.
      forumId = await Titan.ui.promptDialog(t('forum.mod.move_where'), {
        required: true,
        help: t('forum.mod.move_help'),
        title: t('forum.mod.move'),
      });
    }
    if (forumId === null || forumId === undefined || forumId === '') return;
    try {
      const resp = await API.moveTopicToForum(topic.id, Number(forumId));
      if (resp && resp.success === false) throw new Error(resp.error);
      Titan.announce(resp && resp.pending
        ? t('forum.mod.move_requested') : t('forum.mod.moved'));
    } catch (err) {
      Titan.announce((err && err.message) || t('err.generic'), 'assertive');
    }
  }

  // ---------- Search across every forum in every group ----------
  async function runSearch() {
    const q = ($searchQ.value || '').trim();
    if (!q) {
      Titan.announce(t('forum.search_empty_query'), 'assertive');
      $searchQ.focus();
      return;
    }
    showView('search');
    $searchResults.innerHTML = '';
    $searchStatus.textContent = t('groups.loading');
    if (Titan.ui && Titan.ui.focusHeading) Titan.ui.focusHeading($searchHeading);
    else $searchHeading.focus();
    try {
      const data = await API.searchForum(q);
      renderResults((data && data.topics) || []);
    } catch (e) {
      $searchStatus.textContent = e.message || t('err.generic');
    }
  }

  function renderResults(topics) {
    $searchResults.innerHTML = '';
    if (!topics.length) {
      $searchStatus.textContent = t('forum.results_none');
      return;
    }
    // The count goes into the status line, which is a live region, so it
    // is said once rather than being counted row by row.
    $searchStatus.textContent = t('forum.results_count', topics.length);
    const frag = document.createDocumentFragment();
    topics.forEach((topic) => {
      const li = document.createElement('li');
      const card = document.createElement('article');
      card.className = 'card';
      const headingId = 'result-' + topic.id;
      card.setAttribute('aria-labelledby', headingId);
      const h3 = document.createElement('h3');
      h3.id = headingId;
      const a = document.createElement('a');
      a.href = '#';
      a.textContent = topic.title;
      a.addEventListener('click', (e) => { e.preventDefault(); openTopic(topic.id, 'search'); });
      h3.appendChild(a);
      card.appendChild(h3);
      const meta = document.createElement('p');
      meta.className = 'meta';
      // Where it was found - the whole point of one merged page. Said
      // only when the server told us: a server that has not been
      // restarted since this shipped sends no forum name, and inventing
      // "in a forum that no longer exists" for every hit would be worse
      // than saying nothing.
      const bits = [];
      if (topic.forum_name) {
        bits.push(t('forum.found_in', topic.forum_name, topic.group_name || '?'));
      }
      if (topic.author_username) bits.push(t('forum.posted_by', topic.author_username));
      bits.push(t('forum.replies', topic.reply_count || 0));
      meta.textContent = bits.join(' \u00b7 ');
      card.appendChild(meta);
      li.appendChild(card);
      frag.appendChild(li);
    });
    $searchResults.appendChild(frag);
  }

  // ---------- Navigation back links ----------
  //
  // Back from a topic goes where the topic was OPENED from: the forum in
  // the usual drill-down, but the results list when the topic was found
  // by searching - a search hit can live in a forum the user never
  // opened, and sending them "back" into it would be a place they have
  // not been.
  function topicBack() {
    if (topicCameFrom === 'search') {
      showView('search');
      if (Titan.ui && Titan.ui.focusHeading) Titan.ui.focusHeading($searchHeading);
      else $searchHeading.focus();
      return;
    }
    if (currentForum) openForum(currentForum);
    else loadGroups();
  }

  $groupBack.addEventListener('click', (e) => { e.preventDefault(); loadGroups(); });
  $threadsBack.addEventListener('click', (e) => { e.preventDefault(); openGroup(currentGroup); });
  $topicBack.addEventListener('click', (e) => { e.preventDefault(); topicBack(); });
  $searchBack.addEventListener('click', (e) => { e.preventDefault(); loadGroups(); });
  $searchForm.addEventListener('submit', (e) => { e.preventDefault(); runSearch(); });

  // ---------- New group ----------
  const $ngDialog = document.getElementById('new-group-dialog');
  const $ngForm = document.getElementById('new-group-form');
  document.getElementById('ng-cancel').addEventListener('click', () => dialogClose($ngDialog));
  if ($newGroupBtn) {
    $newGroupBtn.addEventListener('click', () => {
      if (!Titan.getUser()) { Titan.announce(t('err.login_first')); return; }
      dialogOpen($ngDialog, document.getElementById('ng-name'));
    });
  }
  $ngForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('ng-name').value.trim();
    if (!name) return;
    const description = document.getElementById('ng-desc').value.trim();
    const visibility = document.getElementById('ng-visibility').value;
    const limit = parseInt(document.getElementById('ng-limit').value, 10) || 0;
    try {
      const resp = await API.createGroup(name, description, visibility, limit);
      if (resp.success) {
        Titan.announce(t('groups.created'));
        dialogClose($ngDialog);
        $ngForm.reset();
        loadGroups();
      } else { Titan.announce(resp.error || t('err.generic')); }
    } catch (e) { Titan.announce(e.message || t('err.generic')); }
  });

  // ---------- New forum ----------
  const $nfDialog = document.getElementById('new-forum-dialog');
  const $nfForm = document.getElementById('new-forum-form');
  document.getElementById('nf-cancel').addEventListener('click', () => dialogClose($nfDialog));
  $newForumBtn.addEventListener('click', () => {
    if (!currentGroup) return;
    dialogOpen($nfDialog, document.getElementById('nf-name'));
  });
  $nfForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!currentGroup) return;
    const name = document.getElementById('nf-name').value.trim();
    if (!name) return;
    const description = document.getElementById('nf-desc').value.trim();
    try {
      const resp = await API.createGroupForum(currentGroup.id, name, description);
      if (resp.success) {
        Titan.announce(t('groups.forum_created'));
        dialogClose($nfDialog);
        $nfForm.reset();
        loadForums();
      } else { Titan.announce(resp.error || t('err.generic')); }
    } catch (e) { Titan.announce(e.message || t('err.generic')); }
  });

  // ---------- New thread ----------
  const $ntDialog = document.getElementById('new-thread-dialog');
  const $ntForm = document.getElementById('new-thread-form');
  document.getElementById('nt-cancel').addEventListener('click', () => dialogClose($ntDialog));
  $newThreadBtn.addEventListener('click', () => {
    if (!Titan.getUser()) { Titan.announce(t('err.login_first')); return; }
    if (!isActiveMember(currentGroup)) { Titan.announce(t('groups.join_to_post')); return; }
    dialogOpen($ntDialog, document.getElementById('nt-title-input'));
  });
  $ntForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!currentForum) return;
    const title = document.getElementById('nt-title-input').value.trim();
    const content = document.getElementById('nt-content').value.trim();
    if (!title || !content) return;
    try {
      const resp = await API.createTopic(title, content, 'general', currentForum.id);
      if (resp.success) {
        Titan.announce(t('ok.posted'));
        dialogClose($ntDialog);
        $ntForm.reset();
        loadThreads();
      } else { Titan.announce(resp.error || t('err.generic')); }
    } catch (e) { Titan.announce(e.message || t('err.generic')); }
  });

  // ---------- Reply ----------
  if ($replyForm) {
    $replyForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!currentTopicId) return;
      const txt = $replyContent.value.trim();
      if (!txt) return;
      try {
        const resp = await API.addReply(currentTopicId, txt);
        if (resp.success) { $replyContent.value = ''; openTopic(currentTopicId); }
      } catch (e) { Titan.announce(e.message || t('err.generic')); }
    });
  }

  // ---------- Pending members ----------
  const $pendingDialog = document.getElementById('pending-dialog');
  const $pendingStatus = document.getElementById('pending-status');
  const $pendingList = document.getElementById('pending-list');
  document.getElementById('pm-close').addEventListener('click', () => dialogClose($pendingDialog));
  $pendingBtn.addEventListener('click', () => {
    if (!currentGroup) return;
    dialogOpen($pendingDialog);
    loadPending();
  });

  async function loadPending() {
    $pendingStatus.textContent = t('groups.loading');
    $pendingList.innerHTML = '';
    try {
      const data = await API.groupMembers(currentGroup.id, 'pending');
      renderPending(data.members || []);
    } catch (e) {
      $pendingStatus.textContent = e.message || t('err.generic');
    }
  }

  function renderPending(members) {
    $pendingList.innerHTML = '';
    if (!members.length) { $pendingStatus.textContent = t('groups.no_pending'); return; }
    $pendingStatus.textContent = '';
    members.forEach((m) => {
      const li = document.createElement('li');
      const card = document.createElement('article');
      card.className = 'card';
      const name = document.createElement('span');
      name.textContent = m.username + (m.titan_number ? ' (#' + m.titan_number + ')' : '');
      card.appendChild(name);
      const approve = document.createElement('button');
      approve.textContent = t('groups.approve');
      approve.style.marginLeft = '.5rem';
      approve.addEventListener('click', () => actMember(m.user_id, true));
      card.appendChild(approve);
      const reject = document.createElement('button');
      reject.className = 'btn btn-secondary';
      reject.textContent = t('groups.reject');
      reject.style.marginLeft = '.5rem';
      reject.addEventListener('click', () => actMember(m.user_id, false));
      card.appendChild(reject);
      li.appendChild(card);
      $pendingList.appendChild(li);
    });
  }

  async function actMember(userId, approve) {
    try {
      const resp = approve
        ? await API.approveMember(currentGroup.id, userId)
        : await API.rejectMember(currentGroup.id, userId);
      if (resp.success) loadPending();
      else Titan.announce(resp.error || t('err.generic'));
    } catch (e) { Titan.announce(e.message || t('err.generic')); }
  }

  // ---------- Manage active members ----------
  const $manageDialog = document.getElementById('manage-dialog');
  const $manageStatus = document.getElementById('manage-status');
  const $manageList = document.getElementById('manage-list');
  document.getElementById('mm-close').addEventListener('click', () => dialogClose($manageDialog));
  const $renameForm = document.getElementById('mm-rename-form');
  const $renameInput = document.getElementById('mm-rename-input');
  $manageBtn.addEventListener('click', () => {
    if (!currentGroup) return;
    $renameInput.value = currentGroup.name || '';
    dialogOpen($manageDialog);
    loadManage();
  });
  $renameForm.addEventListener('submit', (e) => {
    e.preventDefault();
    if (!currentGroup) return;
    const name = $renameInput.value.trim();
    if (!name) return;
    manageAct(() => API.renameGroup(currentGroup.id, name), true);
  });

  async function loadManage() {
    $manageStatus.textContent = t('groups.loading');
    $manageList.innerHTML = '';
    try {
      const data = await API.groupMembers(currentGroup.id, 'active');
      renderManage(data.members || []);
    } catch (e) {
      $manageStatus.textContent = e.message || t('err.generic');
    }
  }

  function roleLabel(role) {
    if (role === 'owner') return t('groups.status.owner');
    if (role === 'moderator') return t('groups.status.moderator');
    return t('groups.status.member');
  }

  function renderManage(members) {
    $manageList.innerHTML = '';
    if (!members.length) { $manageStatus.textContent = t('groups.no_members'); return; }
    $manageStatus.textContent = '';
    const isOwner = currentGroup.my_role === 'owner';
    members.forEach((m) => {
      const li = document.createElement('li');
      const card = document.createElement('article');
      card.className = 'card';
      const name = document.createElement('span');
      name.textContent = m.username + (m.titan_number ? ' (#' + m.titan_number + ')' : '') + ' — ' + roleLabel(m.role);
      card.appendChild(name);
      if (m.role !== 'owner') {
        if (isOwner) {
          const modBtn = document.createElement('button');
          modBtn.style.marginLeft = '.5rem';
          modBtn.textContent = m.role === 'moderator' ? t('groups.remove_moderator') : t('groups.make_moderator');
          modBtn.addEventListener('click', () => manageAct(() => API.setGroupModerator(currentGroup.id, m.user_id, m.role !== 'moderator')));
          card.appendChild(modBtn);
          const transferBtn = document.createElement('button');
          transferBtn.className = 'btn btn-secondary';
          transferBtn.style.marginLeft = '.5rem';
          transferBtn.textContent = t('groups.transfer_ownership');
          transferBtn.addEventListener('click', () => {
            if (!window.confirm(t('groups.transfer_confirm'))) return;
            manageAct(() => API.transferGroupOwnership(currentGroup.id, m.user_id), true);
          });
          card.appendChild(transferBtn);
        }
        const banBtn = document.createElement('button');
        banBtn.className = 'btn btn-secondary';
        banBtn.style.marginLeft = '.5rem';
        banBtn.textContent = t('groups.ban');
        banBtn.addEventListener('click', () => manageAct(() => API.banFromGroup(currentGroup.id, m.user_id)));
        card.appendChild(banBtn);
      }
      li.appendChild(card);
      $manageList.appendChild(li);
    });
  }

  async function manageAct(fn, reloadGroup) {
    try {
      const resp = await fn();
      if (resp.success) {
        Titan.announce(t('groups.done'));
        if (reloadGroup) {
          // Ownership changed hands — refresh the group so roles/menus update.
          dialogClose($manageDialog);
          loadGroups();
        } else {
          loadManage();
        }
      } else {
        Titan.announce(resp.error || t('err.generic'));
      }
    } catch (e) { Titan.announce(e.message || t('err.generic')); }
  }

  // ---------- Init ----------
  window.onLangChanged = function () {
    // Re-render whatever view is active.
    if (!views.groups.hidden) loadGroups();
    else if (!views.group.hidden && currentGroup) openGroup(currentGroup);
    else if (!views.threads.hidden && currentForum) loadThreads();
    else if (!views.search.hidden) runSearch();
    else if (!views.topic.hidden && currentTopicId) openTopic(currentTopicId, topicCameFrom);
  };

  document.addEventListener('DOMContentLoaded', loadGroups);
  if (document.readyState !== 'loading') loadGroups();
})();
