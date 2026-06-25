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

  // Threads
  const $threadsTitle = document.getElementById('threads-title');
  const $threadsStatus = document.getElementById('threads-status');
  const $threadsList = document.getElementById('threads-list');
  const $threadsBack = document.getElementById('threads-back');
  const $newThreadBtn = document.getElementById('new-thread-btn');

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
  async function openTopic(topicId) {
    currentTopicId = topicId;
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
        li.appendChild(card);
        $topicReplies.appendChild(li);
      });
      $topicTitle.focus();
    } catch (e) {
      $topicBody.textContent = e.message || t('err.generic');
    }
  }

  // ---------- Navigation back links ----------
  $groupBack.addEventListener('click', (e) => { e.preventDefault(); loadGroups(); });
  $threadsBack.addEventListener('click', (e) => { e.preventDefault(); openGroup(currentGroup); });
  $topicBack.addEventListener('click', (e) => { e.preventDefault(); openForum(currentForum); });

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

  // ---------- Init ----------
  window.onLangChanged = function () {
    // Re-render whatever view is active.
    if (!views.groups.hidden) loadGroups();
    else if (!views.group.hidden && currentGroup) openGroup(currentGroup);
    else if (!views.threads.hidden && currentForum) loadThreads();
  };

  document.addEventListener('DOMContentLoaded', loadGroups);
  if (document.readyState !== 'loading') loadGroups();
})();
