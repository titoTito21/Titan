// Titan-Net forum
(function () {
  'use strict';
  const t = Titan.t;

  const $listView = document.getElementById('forum-list-view');
  const $topicView = document.getElementById('forum-topic-view');
  const $status = document.getElementById('forum-status');
  const $topics = document.getElementById('forum-topics');
  const $searchForm = document.getElementById('forum-search');
  const $q = document.getElementById('forum-q');

  const $newTopicBtn = document.getElementById('new-topic-btn');
  const $newDialog = document.getElementById('new-topic-dialog');
  const $newForm = document.getElementById('new-topic-form');
  const $ntCancel = document.getElementById('nt-cancel');

  const $back = document.getElementById('forum-back');
  const $title = document.getElementById('topic-title');
  const $meta = document.getElementById('topic-meta');
  const $body = document.getElementById('topic-body');
  const $replies = document.getElementById('topic-replies');
  const $replyForm = document.getElementById('reply-form');
  const $replyContent = document.getElementById('reply-content');

  let currentTopicId = null;
  let lastListFocus = null;

  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function renderTopics(topics) {
    $topics.innerHTML = '';
    if (!topics || topics.length === 0) {
      $status.textContent = t('forum.empty');
      return;
    }
    $status.textContent = '';
    const frag = document.createDocumentFragment();
    topics.forEach((topic) => {
      const li = document.createElement('li');
      const article = document.createElement('article');
      article.className = 'card';
      article.setAttribute('aria-labelledby', 'topic-' + topic.id);
      const h3 = document.createElement('h3');
      h3.id = 'topic-' + topic.id;
      const a = document.createElement('a');
      a.href = '#';
      a.textContent = topic.title;
      a.addEventListener('click', (e) => { e.preventDefault(); openTopic(topic.id); });
      h3.appendChild(a);
      if (topic.is_pinned) {
        const pin = document.createElement('span');
        pin.className = 'badge';
        pin.textContent = t('forum.pinned');
        h3.appendChild(document.createTextNode(' '));
        h3.appendChild(pin);
      }
      if (topic.is_locked) {
        const lock = document.createElement('span');
        lock.className = 'badge';
        lock.textContent = t('forum.locked');
        h3.appendChild(document.createTextNode(' '));
        h3.appendChild(lock);
      }
      article.appendChild(h3);
      const meta = document.createElement('p');
      meta.className = 'meta';
      const parts = [];
      if (topic.author_username) parts.push(t('forum.posted_by', topic.author_username));
      if (topic.reply_count != null) parts.push(t('forum.replies', topic.reply_count));
      meta.textContent = parts.join(' · ');
      article.appendChild(meta);
      li.appendChild(article);
      frag.appendChild(li);
    });
    $topics.appendChild(frag);
  }

  async function loadTopics() {
    $status.textContent = t('repo.loading');
    $topics.innerHTML = '';
    const q = ($q.value || '').trim();
    try {
      const data = q
        ? await Titan.API.searchForum(q)
        : await Titan.API.listTopics(null, 100);
      renderTopics(data.topics || []);
    } catch (e) {
      $status.textContent = e.message || t('err.generic');
    }
  }

  async function openTopic(topicId) {
    currentTopicId = topicId;
    lastListFocus = document.activeElement;
    $listView.hidden = true;
    $topicView.hidden = false;
    $title.textContent = '…';
    $meta.textContent = '';
    $body.textContent = '';
    $replies.innerHTML = '';
    try {
      const [topicResp, replyResp] = await Promise.all([
        Titan.API.getTopic(topicId),
        Titan.API.listReplies(topicId, 200),
      ]);
      const topic = topicResp.topic;
      $title.textContent = topic.title;
      const metaParts = [];
      if (topic.author_username) metaParts.push(t('forum.posted_by', topic.author_username));
      $meta.textContent = metaParts.join(' · ');
      $body.innerHTML = escapeHtml(topic.content).replace(/\n/g, '<br>');
      const replies = replyResp.replies || [];
      replies.forEach((r, idx) => {
        const li = document.createElement('li');
        const card = document.createElement('article');
        card.className = 'card';
        // Each reply gets its own H3 so screen reader users can jump from
        // reply to reply with the heading key (H in NVDA / VoiceOver rotor).
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
        $replies.appendChild(li);
      });
      $title.focus();
    } catch (e) {
      $body.textContent = e.message || t('err.generic');
    }
  }

  function backToList() {
    $topicView.hidden = true;
    $listView.hidden = false;
    currentTopicId = null;
    if (lastListFocus && lastListFocus.focus) lastListFocus.focus();
  }

  $back.addEventListener('click', (e) => { e.preventDefault(); backToList(); });
  $searchForm.addEventListener('submit', (e) => { e.preventDefault(); loadTopics(); });

  if ($newTopicBtn) {
    $newTopicBtn.addEventListener('click', () => {
      if (!Titan.getUser()) {
        Titan.announce(t('err.login_first'));
        return;
      }
      if (typeof $newDialog.showModal === 'function') $newDialog.showModal();
      else $newDialog.setAttribute('open', '');
      document.getElementById('nt-title-input').focus();
    });
  }
  $ntCancel.addEventListener('click', () => {
    if ($newDialog.close) $newDialog.close(); else $newDialog.removeAttribute('open');
  });
  $newForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const title = document.getElementById('nt-title-input').value.trim();
    const content = document.getElementById('nt-content').value.trim();
    if (!title || !content) return;
    try {
      const resp = await Titan.API.createTopic(title, content, 'general');
      if (resp.success) {
        Titan.announce(t('ok.posted'));
        if ($newDialog.close) $newDialog.close(); else $newDialog.removeAttribute('open');
        document.getElementById('nt-title-input').value = '';
        document.getElementById('nt-content').value = '';
        loadTopics();
      }
    } catch (e) {
      Titan.announce(e.message || t('err.generic'));
    }
  });

  if ($replyForm) {
    $replyForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!currentTopicId) return;
      const txt = $replyContent.value.trim();
      if (!txt) return;
      try {
        const resp = await Titan.API.addReply(currentTopicId, txt);
        if (resp.success) {
          $replyContent.value = '';
          openTopic(currentTopicId);
        }
      } catch (e) {
        Titan.announce(e.message || t('err.generic'));
      }
    });
  }

  window.onLangChanged = loadTopics;

  // Initial load
  document.addEventListener('DOMContentLoaded', loadTopics);
  if (document.readyState !== 'loading') loadTopics();
})();
