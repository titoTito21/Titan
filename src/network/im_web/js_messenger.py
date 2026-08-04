# -*- coding: utf-8 -*-
"""Facebook Messenger page agent: rendered thread first, own traffic second.

Messenger has no readable store the way WhatsApp Web does - its data arrives as
Lightspeed payloads over an MQTT-ish WebSocket - so the two sources here are

1. **The rendered page.** Messenger keeps the real thread id in the row link
   (``/t/<thread_id>/``), which means the DOM path addresses conversations by
   their true id rather than by display name, and ``MutationObserver`` on the
   conversation grid and on the open thread gives immediate, push-based updates.
2. **The page's own traffic.** ``fetch`` / ``XMLHttpRequest`` / ``WebSocket`` are
   wrapped at document start. We do not attempt to decode Meta's payloads;
   the traffic is used as a *hint* that something changed, which collapses the
   window between "the server told the page" and "we re-read the thread" to a
   single animation frame. Anything the hint cannot explain still shows up via
   the observer.

Both paths feed one deduplicating emitter (message id, or content+time when a
row has no id), so a message seen twice is announced once.

Calls reuse ``src/network/call_detection_js.py`` - the same tested state machine
as WhatsApp, with Messenger's own control labels already covered there.
"""

from __future__ import annotations

from src.network.call_detection_js import build_monitor_script

MESSENGER_AGENT = r"""
(function () {
  'use strict';
  var B = window.__titanBridge;
  if (!B || window.__titanMessenger) { return; }
  window.__titanMessenger = true;

  var D = B.dom;
  var announced = {};
  var announcedOrder = [];
  var lastTyping = {};
  var lastAuthJson = '';
  var pendingRescan = null;

  var OWN_RE = /^(you sent|you replied|wys(ł|l)a(ł|l)|ty:)/i;
  var TYPING_RE = /(is typing|typing|pisze|schreibt|escribiendo)/i;
  var ACTIVE_RE = /(active now|aktywn)/i;
  var UNREAD_RE = /(unread|nieprzeczytan)/i;

  function seen(id) {
    if (!id) { return false; }
    if (announced[id]) { return true; }
    announced[id] = true;
    announcedOrder.push(id);
    if (announcedOrder.length > 800) { delete announced[announcedOrder.shift()]; }
    return false;
  }

  // ------------------------------------------------------------------ selectors
  // Candidates for the inbox rail. Matching on the word "conversation" is a
  // trap: Messenger labels the *thread* grid "Messages in conversation with X"
  // ("Wiadomości w rozmowie z X"), so a selector looking for it happily
  // returned the open conversation's messages as if they were the chat list.
  // The candidates are therefore deliberately loose and ``conversationRows``
  // decides what actually is a rail row.
  function ROWS_CONVERSATIONS() {
    return [
      'div[role="grid"][aria-label*="Chats" i] div[role="row"]',
      'div[role="grid"][aria-label*="Czaty" i] div[role="row"]',
      'div[role="navigation"] div[role="row"]',
      'div[role="grid"] div[role="row"]',
      'div[role="row"]',
      'div[role="listitem"]'
    ];
  }

  function conversationRows() {
    var candidates = D.qaAll(ROWS_CONVERSATIONS());
    var out = [];
    for (var i = 0; i < candidates.length; i++) {
      if (isListRow(candidates[i])) { out.push(candidates[i]); }
    }
    return dropNested(out);
  }

  // The open conversation's region. messenger.com normally puts the thread in
  // ``role="main"`` and the inbox rail in ``role="navigation"``, but that split
  // is not something Meta guarantees - so the rail is excluded explicitly below
  // rather than by trusting the region alone, and ``document.body`` is a legal
  // last resort.
  function threadRoot() {
    return D.q(['div[role="grid"][aria-label*="Messages" i]',
                'div[role="grid"][aria-label*="Wiadomo" i]',
                'div[role="main"]',
                'div[role="application"]']) || document.body;
  }

  // Is this a row of the conversation *list* rather than a message? Rows in
  // the rail link to a thread, which is the one thing about them that has
  // never moved. The order of the tests matters: the thread's own grid is
  // ruled out first, because a message that happens to quote a messenger.com
  // link would otherwise look exactly like a rail row.
  function isListRow(el) {
    if (!el) { return false; }
    try {
      var grid = el.closest('div[role="grid"], div[role="listbox"]');
      var label = grid ? (grid.getAttribute('aria-label') || '') : '';
      // "Messages in conversation with X" / "Wiadomości w rozmowie z X" is the
      // thread, so the word "conversation" alone may not decide this.
      if (/message|wiadomo/i.test(label)) { return false; }
      if (el.closest('div[role="navigation"]')) { return true; }
      if (/conversation|rozmow|chats|czaty/i.test(label)) { return true; }
      if (el.querySelector('a[href*="/t/"]')) { return true; }
    } catch (e) { /* an unreadable element is not a list row */ }
    return false;
  }

  // Keep only the outermost of any nested candidates, so one message cannot be
  // reported once as a row and again as the cell inside it.
  function dropNested(list) {
    var out = [];
    for (var i = 0; i < list.length; i++) {
      var nested = false;
      for (var j = 0; j < list.length; j++) {
        if (i === j) { continue; }
        try {
          if (list[j].contains(list[i])) { nested = true; break; }
        } catch (e) { /* detached */ }
      }
      if (!nested) { out.push(list[i]); }
    }
    return out;
  }

  // Last resort when nothing on the page is marked up semantically any more:
  // the deepest block whose children each carry text is the message list.
  function repeatedTextList(root) {
    var best = null;
    var bestScore = 0;
    var nodes = root.querySelectorAll('div');
    var limit = Math.min(nodes.length, 4000);
    for (var i = 0; i < limit; i++) {
      var el = nodes[i];
      var kids = el.children;
      if (!kids || kids.length < 3) { continue; }
      var withText = 0;
      for (var j = 0; j < kids.length; j++) {
        var value = D.text(kids[j]);
        if (value && value.length > 1) { withText++; }
      }
      // ``>=`` on purpose: querySelectorAll is in document order, so a
      // descendant that scores the same as its ancestor wins - which is the
      // list itself rather than the wrapper around it.
      if (withText >= 3 && withText >= bestScore) { bestScore = withText; best = el; }
    }
    return best;
  }

  // Which strategy last produced the thread. Reported by the diagnostics
  // command so a future Meta redesign can be identified without guessing.
  var lastThreadStrategy = 'none';

  function threadRows() {
    var root = threadRoot();

    function take(list, strategy) {
      var kept = [];
      for (var i = 0; i < list.length; i++) {
        if (isListRow(list[i])) { continue; }
        kept.push(list[i]);
      }
      if (kept.length) { lastThreadStrategy = strategy; }
      return kept;
    }

    // 1. The accessible structure Messenger normally exposes.
    var rows = take(D.qaAll(['div[role="row"]', '[role="row"]'], root), 'row');
    if (rows.length) { return dropNested(rows); }

    // 2. Builds that only mark the cells (this is what the old visible-window
    //    integration read, and it is still what some experiments ship).
    rows = take(D.qaAll(['div[role="gridcell"]', '[role="listitem"]',
                         '[data-scope="messages_table"] > div'], root), 'gridcell');
    if (rows.length) { return dropNested(rows); }

    // 3. Nothing semantic left at all - read the rendered blocks. This is what
    //    keeps the client working through a redesign instead of showing the
    //    user an empty conversation.
    var list = repeatedTextList(root);
    if (list) {
      rows = take(Array.prototype.slice.call(list.children), 'heuristic');
      if (rows.length) { return rows; }
    }

    lastThreadStrategy = 'none';
    return [];
  }

  // The element the thread scrolls in - needed to pull older messages in.
  function threadScroller() {
    var root = threadRoot();
    var nodes = root.querySelectorAll('div');
    var limit = Math.min(nodes.length, 4000);
    for (var i = 0; i < limit; i++) {
      var el = nodes[i];
      try {
        var style = window.getComputedStyle(el);
        if ((style.overflowY === 'auto' || style.overflowY === 'scroll') &&
            el.scrollHeight > el.clientHeight + 40) { return el; }
      } catch (e) { /* keep looking */ }
    }
    return root;
  }

  function COMPOSER() {
    return [
      'div[role="textbox"][contenteditable="true"][aria-label*="Message" i]',
      'div[role="textbox"][contenteditable="true"][aria-label*="Wiadomo" i]',
      'div[role="textbox"][contenteditable="true"]',
      'div[contenteditable="true"][data-lexical-editor="true"]'
    ];
  }

  // --------------------------------------------------------------------- model
  function threadIdFromRow(row) {
    var link = row.querySelector('a[href*="/t/"]');
    if (!link) { return ''; }
    var href = link.getAttribute('href') || '';
    var match = href.match(/\/t\/([^\/?#]+)/);
    return match ? match[1] : '';
  }

  function currentThreadId() {
    var match = String(location.pathname || '').match(/\/t\/([^\/?#]+)/);
    return match ? match[1] : '';
  }

  function chatFromRow(row, index) {
    var id = threadIdFromRow(row);
    var label = row.getAttribute('aria-label') || '';
    var spans = D.qa(['span[dir="auto"]'], row);
    var texts = [];
    for (var i = 0; i < spans.length; i++) {
      var value = D.text(spans[i]);
      if (value && texts.indexOf(value) === -1) { texts.push(value); }
    }
    var name = texts[0] || label || '';
    if (!name) { return null; }

    var preview = '';
    for (var j = 1; j < texts.length; j++) {
      // Skip the trailing timestamp column ("2 h", "12:31", "wt").
      if (/^([0-9]{1,2}:[0-9]{2}|[0-9]+\s*(m|h|d|min|godz|dni)|[a-z]{2,3})$/i.test(texts[j])) {
        continue;
      }
      preview = texts[j];
      break;
    }

    var unread = 0;
    if (UNREAD_RE.test(label)) { unread = 1; }
    if (!unread && D.q(['[aria-label*="unread" i]', '[aria-label*="nieprzeczytan" i]'], row)) {
      unread = 1;
    }

    var online = false;
    if (ACTIVE_RE.test(label)) { online = true; }
    if (!online && D.q(['[aria-label*="Active now" i]', '[aria-label*="Aktywn" i]'], row)) {
      online = true;
    }

    var isGroup = false;
    // A group row shows a stacked avatar: two images instead of one.
    if (D.qa(['img'], row).length > 1) { isGroup = true; }

    return {
      id: id || ('dom:' + name),
      name: name,
      is_group: isGroup,
      kind: isGroup ? 'group' : 'chat',
      unread: unread,
      last_message: preview,
      last_message_at: 0,
      online: online,
      dom_index: index,
      dom_only: !id
    };
  }

  // Messenger nests ``dir="auto"`` several deep on every bubble and puts the
  // timestamp, the sender and the delivery state in siblings of the body. The
  // longest distinct block is the message; a row with no marked-up text at all
  // (a redesign, a system notice) still yields its rendered text.
  function rowText(row) {
    var nodes = D.qaAll(['div[dir="auto"]', 'span[dir="auto"]'], row);
    var best = '';
    for (var i = 0; i < nodes.length; i++) {
      var value = D.text(nodes[i]);
      if (value.length > best.length) { best = value; }
    }
    if (!best) { best = D.text(row); }
    return best;
  }

  function messageFromRow(row) {
    var label = row.getAttribute('aria-label') || '';
    var text = rowText(row);

    var outgoing = OWN_RE.test(label);
    if (!outgoing) {
      // No usable label: Messenger right-aligns your own bubbles, and the
      // offscreen host still lays the page out, so this is readable.
      try {
        var cell = row.querySelector('div[role="gridcell"]') || row;
        var style = window.getComputedStyle(cell);
        outgoing = (style && (style.justifyContent === 'flex-end' ||
                              style.alignItems === 'flex-end'));
      } catch (e) { outgoing = false; }
    }

    var author = '';
    var match = label.match(/^(.*?)\s+(sent|replied|wys(?:ł|l)a)/i);
    if (match) { author = match[1]; }
    if (!author) {
      var avatar = row.querySelector('img[alt]');
      if (avatar) { author = avatar.getAttribute('alt') || ''; }
    }

    var kind = 'text';
    if (row.querySelector('[aria-label*="voice message" i], [aria-label*="Wiadomość głosowa" i], audio')) {
      kind = 'voice';
    } else if (row.querySelector('img[src*="scontent"], [aria-label*="photo" i], [aria-label*="Zdj" i]')) {
      kind = 'image';
    } else if (row.querySelector('video, [aria-label*="video" i]')) {
      kind = 'video';
    } else if (row.querySelector('a[href*="attachment"], [aria-label*="file" i], [aria-label*="Plik" i]')) {
      kind = 'document';
    } else if (row.querySelector('[aria-label*="sticker" i], [aria-label*="Naklejk" i]')) {
      kind = 'sticker';
    }

    var reactions = [];
    var reactionEl = D.q(['[aria-label*="reaction" i]', '[aria-label*="Reakcj" i]'], row);
    if (reactionEl) {
      reactions.push({ emoji: D.text(reactionEl) || '?', count: 1 });
    }

    // No stable id in Messenger's DOM: derive one from author+text so the same
    // rendered row is not announced twice.
    var id = row.getAttribute('data-testid') || '';
    if (!id) {
      id = 'msg:' + currentThreadId() + ':' + (author || (outgoing ? 'me' : '?')) +
           ':' + text.slice(0, 64);
    }

    return {
      id: id,
      chat_id: aliasOf(currentThreadId()),
      text: text,
      author: outgoing ? '' : author,
      timestamp: 0,
      outgoing: outgoing,
      kind: kind,
      reactions: reactions,
      dom_only: true
    };
  }

  // ------------------------------------------------------------------ reading
  // Last good read per scope. Messenger unmounts the conversation grid while
  // it re-renders (and when a thread takes over the view), and a read taken at
  // that moment returns nothing - which used to wipe the whole list in Titan.
  var lastChats = {};

  function listChats(scope) {
    var rows = conversationRows();
    var out = [];
    var seenIds = {};
    for (var i = 0; i < rows.length; i++) {
      var chat = chatFromRow(rows[i], i);
      if (!chat || seenIds[chat.id]) { continue; }
      seenIds[chat.id] = true;
      if (scope === 'unread' && chat.unread <= 0) { continue; }
      if (scope === 'groups' && !chat.is_group) { continue; }
      if (scope === 'active' && !chat.online) { continue; }
      out.push(chat);
    }

    if (!rows.length) {
      // No rows at all means the list is not on the page right now, not that
      // the user has no conversations. An empty scope (no unread, say) still
      // has rows and is reported honestly.
      var cached = lastChats[scope];
      if (cached && cached.length) { return cached; }
    }
    if (out.length) { lastChats[scope] = out; }
    return out;
  }

  function readThread(limit) {
    var rows = threadRows();
    var out = [];
    var used = {};
    for (var i = 0; i < rows.length; i++) {
      var msg = messageFromRow(rows[i]);
      if (!msg.text && msg.kind === 'text') { continue; }
      // Two rows really can carry the same author and text ("ok" twice). The
      // derived id would then collide, and the client - which keys on it -
      // would drop the second one.
      if (used[msg.id]) {
        used[msg.id] += 1;
        msg.id = msg.id + '#' + used[msg.id];
      } else {
        used[msg.id] = 1;
      }
      out.push(msg);
    }
    if (limit && out.length > limit) { out = out.slice(out.length - limit); }
    return out;
  }

  // The client addresses a conversation by the id it was given in the list,
  // which is not always the id in the address bar (a row with no link becomes
  // ``dom:<name>``). Everything read out of the open thread is reported under
  // the id the client knows, so its "is this my conversation?" checks hold.
  var chatAlias = {};

  function aliasOf(threadId) {
    return chatAlias[threadId] || threadId;
  }

  function bindAlias(chatId) {
    var current = currentThreadId();
    if (current && chatId) { chatAlias[current] = String(chatId); }
  }

  function openThread(chatId) {
    var raw = String(chatId || '');
    var domOnly = raw.indexOf('dom:') === 0;
    var wanted = domOnly ? raw.slice(4) : raw;
    if (!wanted) { throw new Error('no conversation given'); }

    if (!domOnly && currentThreadId() === wanted) {
      bindAlias(raw);
      return { opened: true, via: 'current' };
    }

    var rows = conversationRows();
    for (var i = 0; i < rows.length; i++) {
      var id = threadIdFromRow(rows[i]);
      var name = '';
      var nameEl = D.q(['span[dir="auto"]'], rows[i]);
      if (nameEl) { name = D.text(nameEl); }
      if ((id && id === wanted) || (domOnly && name && name === wanted)) {
        var link = rows[i].querySelector('a[href*="/t/"]') || rows[i];
        var before = currentThreadId();
        D.click(link);
        return D.waitFor(function () {
          var now = currentThreadId();
          // With a known id, wait for exactly that thread. Without one, any
          // change of thread is the confirmation - the old predicate compared
          // the address with itself and so was always instantly true, which is
          // how a read could land on the previous conversation.
          return id ? (now === id) : !!(now && now !== before);
        }, 8000, 150).then(function () {
          bindAlias(raw);
          return { opened: true, via: 'dom' };
        }, function () {
          bindAlias(raw);
          return { opened: true, via: 'dom', unconfirmed: true };
        });
      }
    }

    // Not rendered (the list is virtualised, so an older conversation simply
    // is not there): a real navigation is the only way in. The agent is
    // injected at document start, so it survives the reload - but this document
    // does not, so nothing may be awaited afterwards. The caller gets
    // ``navigating`` and Titan re-asks once the new page is up.
    if (!domOnly) {
      location.assign('https://www.messenger.com/t/' +
                      encodeURIComponent(wanted) + '/');
      return { opened: false, navigating: true, via: 'navigate' };
    }
    throw new Error('conversation not found: ' + chatId);
  }

  // ------------------------------------------------------------------ sending
  function sendText(chatId, text) {
    return Promise.resolve(openThread(chatId)).then(function () {
      return D.waitFor(function () { return D.q(COMPOSER()); }, 10000);
    }).then(function (box) {
      if (!D.typeInto(box, text)) { throw new Error('could not type into the composer'); }
      return new Promise(function (resolve) { setTimeout(resolve, 120); });
    }).then(function () {
      var box = D.q(COMPOSER());
      var before = readThread(0).length;
      D.pressEnter(box);
      // Messenger's composer is the only send path that works reliably, so we
      // confirm by watching the thread grow instead of assuming success.
      return D.waitFor(function () {
        return readThread(0).length > before || D.text(box) === '';
      }, 6000, 200).then(function () {
        return { sent: true, via: 'dom' };
      }, function () {
        throw new Error('the message was typed but Messenger did not send it');
      });
    });
  }

  // ------------------------------------------------------------------- events
  function emitChats(scope) {
    try {
      B.emit('chats', { chats: listChats(scope || 'all'), via: 'dom' });
    } catch (e) { B.fail('emit.chats', e); }
  }

  function scanThread() {
    try {
      var rows = threadRows();
      for (var i = Math.max(0, rows.length - 8); i < rows.length; i++) {
        var msg = messageFromRow(rows[i]);
        if (!msg.text && msg.kind === 'text') { continue; }
        if (seen(msg.id)) { continue; }
        B.emit('message_new', { message: msg });
      }
    } catch (e) { B.fail('scan.thread', e); }
  }

  function scanTyping() {
    try {
      var chatId = currentThreadId();
      if (!chatId) { return; }
      // Only the other side counts. A generic loading spinner used to match
      // here, which made Titan announce "typing" while *we* were sending.
      var indicator = D.q(['[aria-label*="is typing" i]', '[aria-label*="pisze" i]',
                           '[aria-label*="typing" i]']);
      var typing = !!(indicator && !OWN_RE.test(indicator.getAttribute('aria-label') || ''));
      if (!typing) {
        var rows = threadRows();
        var last = rows.length ? rows[rows.length - 1] : null;
        var label = last ? (last.getAttribute('aria-label') || '') : '';
        typing = !!(label && TYPING_RE.test(label) && !OWN_RE.test(label));
      }
      var now = Date.now();
      if (typing && lastTyping[chatId] && (now - lastTyping[chatId]) < 4000) { return; }
      if (!typing && !lastTyping[chatId]) { return; }
      lastTyping[chatId] = typing ? now : 0;
      B.emit('typing', { chat_id: chatId, name: '', typing: typing });
    } catch (e) { /* indicator markup changed - not fatal */ }
  }

  function scanPresence() {
    try {
      var rows = conversationRows();
      for (var i = 0; i < rows.length; i++) {
        var chat = chatFromRow(rows[i], i);
        if (!chat || !chat.online) { continue; }
        B.emit('presence', { contact: { id: chat.id, name: chat.name, online: true } });
      }
    } catch (e) { /* nothing to report */ }
  }

  // The traffic hint: any of the page's own requests may carry new messages, so
  // it just schedules a re-read. We deliberately do not parse Meta's payloads.
  function nudge() {
    if (pendingRescan) { return; }
    pendingRescan = setTimeout(function () {
      pendingRescan = null;
      scanThread();
      scanTyping();
      emitChats('all');
    }, 350);
  }

  function interceptTraffic() {
    try {
      var originalFetch = window.fetch;
      if (originalFetch && !originalFetch.__titanWrapped) {
        var wrappedFetch = function (input, init) {
          var url = (typeof input === 'string') ? input : (input && input.url) || '';
          return originalFetch.apply(this, arguments).then(function (response) {
            if (/graphql|messaging|lightspeed/i.test(url)) { nudge(); }
            return response;
          });
        };
        wrappedFetch.__titanWrapped = true;
        window.fetch = wrappedFetch;
      }
    } catch (e) { B.fail('intercept.fetch', e); }

    try {
      var XHR = window.XMLHttpRequest;
      if (XHR && !XHR.prototype.__titanWrapped) {
        var originalOpen = XHR.prototype.open;
        XHR.prototype.open = function (method, url) {
          this.__titanUrl = url;
          return originalOpen.apply(this, arguments);
        };
        var originalSend = XHR.prototype.send;
        XHR.prototype.send = function () {
          var self = this;
          this.addEventListener('load', function () {
            if (/graphql|messaging|lightspeed/i.test(self.__titanUrl || '')) { nudge(); }
          });
          return originalSend.apply(this, arguments);
        };
        XHR.prototype.__titanWrapped = true;
      }
    } catch (e) { B.fail('intercept.xhr', e); }

    try {
      var OriginalWS = window.WebSocket;
      if (OriginalWS && !OriginalWS.__titanWrapped) {
        var WrappedWS = function (url, protocols) {
          var socket = protocols === undefined ? new OriginalWS(url)
                                               : new OriginalWS(url, protocols);
          try {
            socket.addEventListener('message', function () { nudge(); });
          } catch (e) { /* older engines */ }
          return socket;
        };
        WrappedWS.__titanWrapped = true;
        try {
          Object.setPrototypeOf(WrappedWS, OriginalWS);
          WrappedWS.prototype = OriginalWS.prototype;
          window.WebSocket = WrappedWS;
        } catch (e) { /* keep the original if we cannot mirror it */ }
      }
    } catch (e) { B.fail('intercept.ws', e); }
  }

  function watchDom() {
    var grid = D.q(['div[role="grid"]', 'div[role="navigation"]']);
    if (grid && !grid.__titanWatched) {
      grid.__titanWatched = true;
      new MutationObserver(throttle(function () {
        emitChats('all');
        scanPresence();
      }, 1200)).observe(grid, { childList: true, subtree: true, characterData: true });
    }

    var main = D.q(['div[role="main"]']);
    if (main && !main.__titanWatched) {
      main.__titanWatched = true;
      new MutationObserver(throttle(function () {
        scanThread();
        scanTyping();
      }, 350)).observe(main, { childList: true, subtree: true, characterData: true });
    }
  }

  function throttle(fn, ms) {
    var last = 0;
    var pending = null;
    return function () {
      var now = Date.now();
      if (now - last >= ms) { last = now; fn(); return; }
      if (pending) { return; }
      pending = setTimeout(function () {
        pending = null; last = Date.now(); fn();
      }, ms - (now - last));
    };
  }

  // -------------------------------------------------------------------- auth
  // Meta reshuffles this markup constantly, so no single selector may decide
  // the login state: the session cookie, the address and several independent
  // pieces of the logged-in UI all get a vote. Missing one of them must never
  // be enough to tell an actually-logged-in user that they are logged out.
  function sessionUserId() {
    try {
      var match = /(?:^|;\s*)c_user=(\d+)/.exec(document.cookie || '');
      return match ? match[1] : '';
    } catch (e) { return ''; }
  }

  function loginFormVisible() {
    var box = D.q(['input[name="pass"]', 'input[id="pass"]',
                   'form[action*="login" i] input[type="password"]']);
    if (!box) { return false; }
    // A hidden/detached form left over from a completed login does not count.
    try {
      if (!box.offsetParent && !box.getClientRects().length) { return false; }
    } catch (e) { /* treat an unreadable box as visible */ }
    return true;
  }

  function loggedInMarkers() {
    return !!D.q(['div[role="grid"][aria-label*="Conversation" i]',
                  'div[role="grid"][aria-label*="Rozmow" i]',
                  'div[role="grid"][aria-label*="Chat" i]',
                  'div[role="grid"][aria-label*="Czat" i]',
                  'a[href*="messenger.com/t/"]',
                  'div[role="navigation"] a[href*="/t/"]',
                  'div[role="grid"] a[href*="/t/"]',
                  'div[role="main"] div[role="textbox"][contenteditable="true"]',
                  '[aria-label*="New message" i]',
                  '[aria-label*="Nowa wiadomo" i]']);
  }

  function detectAuth() {
    var url = String(location.href || '');
    var host = String(location.hostname || '');
    var challenge = /checkpoint|two_factor|two-step|recover|confirmemail/i.test(url) ||
                    !!D.q(['input[name="approvals_code"]',
                           'input[autocomplete="one-time-code"]']);
    if (challenge) { return { state: 'challenge', reason: 'two_factor' }; }

    var hasSession = !!sessionUserId();

    // Logging in on the visible page often finishes on facebook.com. The
    // session is shared, so the honest answer is "logged in" - and the agent
    // walks the view back to Messenger by itself.
    if (hasSession && !/messenger\.com$/i.test(host) && /facebook\.com$/i.test(host)) {
      if (!loginFormVisible()) {
        goHome();
        return { state: 'loading', reason: 'returning_to_messenger' };
      }
    }

    if (loggedInMarkers()) { sawChatsOnce = true; return { state: 'logged_in' }; }
    if (/messenger\.com\/(t|e2ee|requests|marketplace)\//i.test(url) && hasSession) {
      sawChatsOnce = true;
      return { state: 'logged_in' };
    }
    // ``c_user`` may be http-only depending on how Meta sets it, so a loaded
    // messenger.com that is not showing a login form counts as well: the
    // logged-out landing page always has that form.
    var settled = (document.readyState === 'complete') &&
                  /messenger\.com$/i.test(host);
    if ((hasSession || settled) && !loginFormVisible()) {
      // The cookie says the session is live and no login form is asking for
      // anything, so the chat list is merely still rendering. Give it a few
      // seconds, then trust the cookie: a markup change on Meta's side must
      // not tell a logged-in user that they are logged out.
      if (sawChatsOnce) { return { state: 'logged_in' }; }
      if (!sessionSeenAt) { sessionSeenAt = Date.now(); }
      if (Date.now() - sessionSeenAt > 8000) {
        sawChatsOnce = true;
        return { state: 'logged_in' };
      }
      return { state: 'loading' };
    }
    sessionSeenAt = 0;
    if (loginFormVisible()) { return { state: 'logged_out' }; }

    // Nothing recognisable on the page. If this session was logged in a moment
    // ago it still is - Messenger re-renders itself constantly, and reporting
    // "connecting" here made the client throw the loaded chat list away.
    if (sawChatsOnce) { return { state: 'logged_in' }; }
    return { state: 'loading' };
  }

  // Messenger takes its time before the grid exists; once it has been seen the
  // cookie alone is trusted, so a re-render can never flip the client back to
  // "not logged in" mid-session.
  var sawChatsOnce = false;
  var sessionSeenAt = 0;
  var homeSentAt = 0;
  var HOME_URL = 'https://www.messenger.com/';
  var REQUESTS_URL = 'https://www.messenger.com/requests/';

  function atRequests() {
    return /message_requests|\/requests/i.test(String(location.href || ''));
  }

  function atThread() {
    return /messenger\.com\/(t|e2ee)\//i.test(String(location.href || ''));
  }

  function goHome(force) {
    var now = Date.now();
    if (!force && now - homeSentAt < 15000) { return; }
    homeSentAt = now;
    try { location.assign(HOME_URL); } catch (e) { /* blocked */ }
  }

  // The engine can end up stranded on a page that simply has no conversation
  // list (message requests, marketplace, a settings screen someone opened).
  // Every read there is empty, which is what emptied the client's list after a
  // while. If that lasts, walk back to the inbox.
  var lastScopeAsked = 'all';
  var lastScopeAskedAt = 0;
  var gridSeenAt = 0;

  function watchdog() {
    if (!sawChatsOnce) { return; }
    var now = Date.now();
    if (conversationRows().length) { gridSeenAt = now; return; }
    if (!gridSeenAt) { gridSeenAt = now; return; }
    if (now - gridSeenAt < 25000) { return; }
    // A thread and the requests page are places the user asked to be in - but
    // only while they are still there. A client window closed on the requests
    // tab must not leave the engine parked there, blind to everything else.
    if (atThread()) { return; }
    if (atRequests() && lastScopeAsked === 'requests' &&
        now - lastScopeAskedAt < 120000) { return; }
    gridSeenAt = now;
    goHome();
  }

  function pushAuth(force) {
    var next = detectAuth();
    var json = JSON.stringify(next);
    if (!force && json === lastAuthJson) { return next; }
    lastAuthJson = json;
    B.emit('auth_state', next);
    return next;
  }

  function loginWithCredentials(email, password) {
    var emailBox = D.q(['input[name="email"]', 'input[type="email"]',
                        'input[id="email"]']);
    var passBox = D.q(['input[name="pass"]', 'input[type="password"]',
                       'input[id="pass"]']);
    if (!emailBox || !passBox) { throw new Error('the login form is not on this page'); }

    D.typeInto(emailBox, email || '');
    D.typeInto(passBox, password || '');

    var button = D.q(['button[name="login"]', 'button[type="submit"]',
                      'div[role="button"][tabindex="0"]']);
    if (button) { D.click(button.closest('button') || button); }
    else { D.pressEnter(passBox); }

    return D.waitFor(function () {
      var state = detectAuth().state;
      return (state === 'logged_in' || state === 'challenge') ? state : false;
    }, 30000, 500).then(function (state) {
      pushAuth(true);
      // A checkpoint cannot be answered blind - the client will offer the page.
      return { state: state, needs_page: state === 'challenge' };
    }, function () {
      pushAuth(true);
      return { state: detectAuth().state, needs_page: true };
    });
  }

  // -------------------------------------------------------------------- calls
  function armCallMonitor() {
    try { %%CALL_MONITOR%% } catch (e) { B.fail('call_monitor', e); }
  }

  function callPeerName() {
    var el = D.q(['div[role="main"] h1', 'div[role="main"] span[dir="auto"]',
                  '[aria-label*="call" i] span[dir="auto"]']);
    return el ? D.text(el) : '';
  }

  function drainCallEvents() {
    var state = window.__titanCallState;
    if (!state || !state.events || !state.events.length) { return; }
    var events = state.events.splice(0, state.events.length);
    for (var i = 0; i < events.length; i++) {
      var mapped = { incoming: 'ringing_in', outgoing: 'ringing_out',
                     connected: 'connected', ended: 'ended' }[events[i]];
      if (!mapped) { continue; }
      B.emit('call', { state: mapped, peer: callPeerName(),
                       video: !!D.q(['video']), started_at: state.startedAt || 0 });
    }
  }

  // The conversation header first, so we never press another thread's button.
  function callRoots() {
    return [D.q(['div[role="main"] div[role="banner"]',
                 'div[role="main"] header']),
            D.q(['div[role="main"]']), document];
  }

  function callInProgress() {
    var state = window.__titanCallState;
    if (state && state.active) { return true; }
    if (/\/call\/|\/videocall\/|\/groupcall\//.test(location.pathname)) { return true; }
    // Until the monitor is armed the page itself is the only source of truth.
    // Only hang-up controls count - "Odrzuć"/"Reject" also lives on a consent
    // banner, and reading that as a live call would refuse every call for the
    // first seconds after the page loads.
    if (state) { return false; }
    return !!D.findLabelled(D.words.hangup, null, [document]);
  }

  function callButton(video) {
    var wanted = video ? D.words.video : D.words.voice;
    var avoid = D.words.notACall.concat(video ? [] : D.words.video);
    return D.findLabelled(wanted, avoid, callRoots());
  }

  function callControl(kind) {
    var words = (kind === 'accept') ? D.words.accept : D.words.end;
    var avoid = (kind === 'accept') ? D.words.end : null;
    var button = D.findLabelled(words, avoid, [document]);
    if (!button) { throw new Error('call_control_not_found:' + kind); }
    D.click(D.pressable(button));
    return { done: true };
  }

  // ----------------------------------------------------------------- commands
  B.command('auth_state', function () { return pushAuth(true); });

  B.command('login_start', function (args) {
    if (args.email || args.password) {
      return loginWithCredentials(args.email, args.password);
    }
    var state = pushAuth(true);
    return { state: state.state, needs_page: state.state !== 'logged_in' };
  });

  B.command('logout', function () {
    location.assign('https://www.messenger.com/logout.php');
    return { done: true };
  });

  B.command('list_chats', function (args) {
    var scope = args.scope || 'all';
    lastScopeAsked = scope;
    lastScopeAskedAt = Date.now();
    if (scope === 'requests') {
      // Message requests live on their own page.
      if (!atRequests()) {
        location.assign(REQUESTS_URL);
        return { chats: [], navigating: true };
      }
    } else if (atRequests()) {
      // Leaving the requests page again. Without this the engine stayed on
      // /requests/ for good, where the conversation grid does not exist - so
      // every later read came back empty and the whole list vanished.
      goHome(true);
      return { chats: lastChats[scope] || [], navigating: true };
    }
    return { chats: listChats(scope), via: 'dom' };
  });

  B.command('open_chat', function (args) { return openThread(args.chat_id); });

  B.command('load_history', function (args) {
    var limit = args.limit || 50;
    return Promise.resolve(openThread(args.chat_id)).then(function (opened) {
      if (opened && opened.navigating) {
        // This document is on its way out - awaiting anything here would time
        // out. Titan asks again as soon as the new page's agent is ready.
        return { navigating: true };
      }
      return D.waitFor(function () { return threadRows().length > 0; }, 12000, 200)
        .then(function () {
          // The rows exist, but Messenger fills a freshly opened thread in two
          // paints. Reading on the first one is how the client used to end up
          // with a few placeholder rows - or with the tail of the conversation
          // that was open before this one.
          return new Promise(function (resolve) { setTimeout(resolve, 400); });
        }, function () { return null; });
    }).then(function (state) {
      if (state && state.navigating) { return state; }
      if (args.before_id) {
        // Older messages: Messenger loads them when the thread is scrolled up.
        var scroller = threadScroller();
        if (scroller) { scroller.scrollTop = 0; }
        return new Promise(function (resolve) { setTimeout(resolve, 900); });
      }
      return null;
    }).then(function (state) {
      if (state && state.navigating) { return state; }
      bindAlias(args.chat_id);
      var messages = readThread(limit);
      messages.forEach(function (m) { seen(m.id); });
      return { messages: messages, has_more: true, via: lastThreadStrategy,
               thread_id: currentThreadId(), href: location.href };
    });
  });

  B.command('send_text', function (args) { return sendText(args.chat_id, args.text); });

  B.command('reply_to', function (args) {
    // Quote the row first when its context menu is reachable, then send.
    return Promise.resolve(openThread(args.chat_id)).then(function () {
      var button = D.q(['[aria-label*="Reply" i]', '[aria-label*="Odpowied" i]']);
      if (button) { D.click(button.closest('div[role="button"]') || button); }
      return sendText(args.chat_id, args.text);
    });
  });

  B.command('react', function (args) {
    var rows = threadRows();
    var target = null;
    for (var i = rows.length - 1; i >= 0; i--) {
      if (messageFromRow(rows[i]).id === args.msg_id) { target = rows[i]; break; }
    }
    if (!target) { throw new Error('message not found in the open conversation'); }

    var trigger = D.q(['[aria-label*="React" i]', '[aria-label*="Reakcj" i]'], target);
    if (!trigger) { throw new Error('the reaction control is not available here'); }
    D.click(trigger.closest('div[role="button"]') || trigger);

    return D.waitFor(function () {
      return D.q(['div[role="dialog"] [aria-label*="' + (args.emoji || '') + '"]',
                  'div[role="menu"] [role="button"]']);
    }, 5000).then(function (option) {
      D.click(option.closest('div[role="button"]') || option);
      return { done: true };
    });
  });

  B.command('delete_message', function (args) {
    var rows = threadRows();
    var target = null;
    for (var i = rows.length - 1; i >= 0; i--) {
      if (messageFromRow(rows[i]).id === args.msg_id) { target = rows[i]; break; }
    }
    if (!target) { throw new Error('message not found in the open conversation'); }
    var more = D.q(['[aria-label*="More" i]', '[aria-label*="Więcej" i]'], target);
    if (!more) { throw new Error('the message menu is not available here'); }
    D.click(more.closest('div[role="button"]') || more);
    return D.waitFor(function () {
      var items = D.qa(['div[role="menuitem"]', 'div[role="menu"] div[role="button"]']);
      for (var i = 0; i < items.length; i++) {
        if (/remove|usu(ń|n)|delete/i.test(D.text(items[i]))) { return items[i]; }
      }
      return null;
    }, 5000).then(function (item) {
      D.click(item);
      return { done: true, confirm_needed: true };
    });
  });

  B.command('mark_read', function (args) {
    // Deliberately never navigates. The conversation window marks a chat read
    // and then immediately asks for its history, and two ``openThread`` calls
    // racing each other tore the document down under the second one - which is
    // exactly the case where the messages never arrived. Opening the thread
    // (which ``load_history`` does anyway) is what marks it read on Meta's side.
    var raw = String(args.chat_id || '');
    var wanted = raw.indexOf('dom:') === 0 ? raw.slice(4) : raw;
    if (wanted && currentThreadId() === wanted) {
      bindAlias(raw);
      return { done: true, via: 'current' };
    }
    return { done: false, via: 'skipped' };
  });

  B.command('set_typing', function () { return { done: false }; });
  B.command('set_presence', function () { return { done: false }; });

  B.command('search', function (args) {
    var query = String(args.query || '').toLowerCase();
    if (!query) { return { chats: [], messages: [] }; }
    var chats = listChats('all').filter(function (chat) {
      return chat.name.toLowerCase().indexOf(query) > -1;
    });
    var messages = readThread(0).filter(function (msg) {
      return msg.text.toLowerCase().indexOf(query) > -1;
    });
    return { chats: chats, messages: messages };
  });

  B.command('list_participants', function (args) {
    return Promise.resolve(openThread(args.chat_id)).then(function () {
      var out = [];
      var names = {};
      var rows = threadRows();
      for (var i = 0; i < rows.length; i++) {
        var msg = messageFromRow(rows[i]);
        if (msg.author && !names[msg.author]) {
          names[msg.author] = true;
          out.push({ id: 'name:' + msg.author, name: msg.author, online: false });
        }
      }
      return { contacts: out };
    });
  });

  B.command('list_contacts', function () {
    var out = [];
    var rows = conversationRows();
    for (var i = 0; i < rows.length; i++) {
      var chat = chatFromRow(rows[i], i);
      if (chat && !chat.is_group) {
        out.push({ id: chat.id, name: chat.name, online: chat.online });
      }
    }
    return { contacts: out };
  });

  B.command('send_attachment', function (args) {
    var slot = B.blobs[args.blob_id];
    if (!slot || !slot.file) { throw new Error('attachment not uploaded'); }
    return Promise.resolve(openThread(args.chat_id)).then(function () {
      return D.waitFor(function () { return D.q(['input[type="file"]']); }, 10000);
    }).then(function (input) {
      var transfer = new DataTransfer();
      transfer.items.add(slot.file);
      input.files = transfer.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      return new Promise(function (resolve) { setTimeout(resolve, 1200); });
    }).then(function () {
      var box = D.q(COMPOSER());
      if (args.caption && box) { D.typeInto(box, args.caption); }
      if (box) { D.pressEnter(box); }
      return { sent: true, via: 'dom' };
    });
  });

  B.command('download_media', function (args) {
    var rows = threadRows();
    var target = null;
    for (var i = rows.length - 1; i >= 0; i--) {
      if (messageFromRow(rows[i]).id === args.msg_id) { target = rows[i]; break; }
    }
    if (!target) { throw new Error('message not found in the open conversation'); }

    var source = target.querySelector('img[src^="http"], video[src^="http"], ' +
                                      'audio[src^="http"], a[href*="attachment"]');
    if (!source) { throw new Error('this message has nothing to download'); }
    var url = source.getAttribute('src') || source.getAttribute('href');
    var name = source.getAttribute('download') ||
               (String(url).split('?')[0].split('/').pop() || ('media_' + Date.now()));

    // Try to hand over the bytes; if the CDN refuses a cross-origin read, give
    // Python the URL and let it fetch the (already signed) link itself.
    return fetch(url).then(function (response) {
      if (!response.ok) { throw new Error('http ' + response.status); }
      return response.blob();
    }).then(function (blob) {
      return D.toBase64(blob).then(function (b64) {
        return B.putBlob(args.msg_id, b64, name, blob.type || '');
      });
    }).catch(function () {
      return { url: url, name: name };
    });
  });

  B.command('start_call', function (args) {
    if (callInProgress()) { throw new Error('call_already_running'); }

    return Promise.resolve(openThread(args.chat_id)).then(null, function () {
      throw new Error('chat_not_found');
    }).then(function (opened) {
      // ``openThread`` answers ``navigating`` when the conversation is not in
      // the (virtualised) list and only a real page load can reach it. This
      // document is about to be destroyed, so nothing may be awaited in it -
      // waiting anyway is how pressing call used to end in a bare timeout.
      // Titan re-asks once the new page has its agent up.
      if (opened && opened.navigating) { throw new Error('chat_opening'); }
      return D.waitFor(function () { return callButton(args.video); }, 10000, 200)
        .then(null, function () { throw new Error('call_button_not_found'); });
    }).then(function (button) {
      D.click(D.pressable(button));
      // Messenger opens the call in a window of its own, so this document may
      // show nothing at all afterwards. Not finding a call here is therefore
      // not a failure - Titan's call window reports what the call itself does.
      return D.waitFor(callInProgress, 6000, 250).then(
        function () { return { started: true, confirmed: true }; },
        function () { return { started: true, confirmed: false }; });
    });
  });

  B.command('accept_call', function () { return callControl('accept'); });
  B.command('end_call', function () { return callControl('end'); });

  // What the agent can actually see right now. Reading a conversation depends
  // on markup Meta rewrites without warning, so this reports which strategy
  // found the thread and what the last rows look like - enough to tell "not
  // logged in" from "the thread is empty" from "the page changed shape".
  B.command('dom_report', function () {
    var rows = threadRows();
    var sample = [];
    for (var i = Math.max(0, rows.length - 5); i < rows.length; i++) {
      sample.push(D.text(rows[i]).slice(0, 120));
    }
    return {
      href: location.href,
      thread_id: currentThreadId(),
      thread_alias: aliasOf(currentThreadId()),
      conversation_rows: conversationRows().length,
      thread_rows: rows.length,
      thread_strategy: lastThreadStrategy,
      thread_root: (threadRoot().getAttribute('role') || 'body'),
      composer: !!D.q(COMPOSER()),
      sample: sample
    };
  });

  // ------------------------------------------------------------------- probes
  B.probe('dom.conversations', function () { return conversationRows().length > 0; });
  B.probe('dom.thread', function () { return threadRows().length > 0; });
  B.probe('dom.composer', function () { return !!D.q(COMPOSER()); });
  B.probe('traffic.fetch', function () { return !!(window.fetch && window.fetch.__titanWrapped); });
  B.probe('traffic.xhr', function () {
    return !!(window.XMLHttpRequest && window.XMLHttpRequest.prototype.__titanWrapped);
  });
  B.probe('call_monitor', function () { return !!window.__titanCallState; });

  // --------------------------------------------------------------------- boot
  var booted = false;

  function boot() {
    interceptTraffic();
    watchDom();

    if (!booted) {
      booted = true;
      armCallMonitor();
      B.ready(['attachments', 'search', 'archive', 'voice_call', 'video_call',
               'presence', 'participants', 'message_requests', 'reactions',
               'delete', 'voice_notes']);
    }

    pushAuth(false);
    watchdog();
    drainCallEvents();
  }

  function start() {
    boot();
    setInterval(boot, 2000);
    setInterval(drainCallEvents, 500);
  }

  // Traffic wrapping has to happen before Messenger's own code runs, so it is
  // the one thing that cannot wait for DOMContentLoaded.
  interceptTraffic();

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
"""


def build_messenger_agent() -> str:
    """Return the Messenger agent with the shared call monitor inlined."""
    return MESSENGER_AGENT.replace('%%CALL_MONITOR%%',
                                   build_monitor_script('Messenger'))
