# -*- coding: utf-8 -*-
"""WhatsApp Web page agent: store first, DOM second.

Two sources, one contract
-------------------------
1. **The page's own store.** WhatsApp Web is a webpack bundle whose module
   registry can be read (``window.require('__debug').modulesMap``, or the
   classic chunk-push trick on older builds). That gives the real collections -
   ``ChatCollection``, ``MsgCollection`` - and the real actions
   (``sendTextMsgToChat``, ``sendSeen``, ``sendReactionToMsg``). Real message
   ids, full history, delivery acks, reactions: everything the DOM cannot say.
2. **The DOM.** When a bundle reshuffle hides a piece of the store, the same
   command falls back to the rendered page: ``#pane-side`` for the chat list,
   ``div[data-id]`` rows for messages (WhatsApp helpfully keeps the real message
   id in that attribute), the composer for sending.

Both paths produce the same shapes as ``base.Chat`` / ``base.Message``, and
``__titanSelfTest()`` reports which one is live. Whatever is missing is simply
left out of the reported capabilities, so the client hides those tabs and menu
items instead of failing at runtime.

Call detection reuses ``src/network/call_detection_js.py`` unchanged - its
state machine is the one that fixed the phantom "incoming call" bug - and only
adds draining its event queue into the bridge, so no wx timer polls the page.
"""

from __future__ import annotations

from src.network.call_detection_js import build_monitor_script

WHATSAPP_AGENT = r"""
(function () {
  'use strict';
  var B = window.__titanBridge;
  if (!B || window.__titanWhatsApp) { return; }
  window.__titanWhatsApp = true;

  var D = B.dom;
  var S = {};                     // whatever we managed to find in the store
  var caps = {};                  // capability -> true
  var auth = { state: 'loading' };
  var lastTyping = {};            // chat id -> timestamp, so we do not spam
  var announced = {};             // message id -> true, cross-source dedupe
  var announcedOrder = [];

  // ------------------------------------------------------------------ helpers
  function serialized(id) {
    if (!id) { return ''; }
    if (typeof id === 'string') { return id; }
    return id._serialized || (id.toString ? id.toString() : '');
  }

  function seen(id) {
    if (!id) { return false; }
    if (announced[id]) { return true; }
    announced[id] = true;
    announcedOrder.push(id);
    if (announcedOrder.length > 800) {
      delete announced[announcedOrder.shift()];
    }
    return false;
  }

  function DOM_CHAT_ITEMS() {
    return [
      '#pane-side div[role="listitem"]',
      'div[aria-label*="Chat list" i] div[role="listitem"]',
      'div[aria-label*="Lista czat" i] div[role="listitem"]',
      '#pane-side [data-testid="cell-frame-container"]'
    ];
  }

  function DOM_COMPOSER() {
    return [
      'footer div[contenteditable="true"][data-tab="10"]',
      'footer div[contenteditable="true"]',
      'div[contenteditable="true"][data-tab="10"]',
      '#main div[contenteditable="true"]'
    ];
  }

  function DOM_SEARCH_BOX() {
    return [
      'div[contenteditable="true"][data-tab="3"]',
      'div[aria-label*="Search" i][contenteditable="true"]',
      'div[aria-label*="Szukaj" i][contenteditable="true"]'
    ];
  }

  // ------------------------------------------------------- store discovery
  function requireModule(names) {
    if (typeof window.require !== 'function') { return null; }
    for (var i = 0; i < names.length; i++) {
      try {
        var mod = window.require(names[i]);
        if (mod) { return mod; }
      } catch (e) { /* not in this build */ }
    }
    return null;
  }

  function debugModules() {
    var out = [];
    try {
      var dbg = window.require && window.require('__debug');
      var map = dbg && dbg.modulesMap;
      if (!map) { return out; }
      for (var key in map) {
        if (!map.hasOwnProperty(key)) { continue; }
        var entry = map[key];
        if (!entry) { continue; }
        // Builds differ: some hand back the exports, some a wrapper.
        var exports = entry;
        if (entry.defaultExport !== undefined) { exports = entry.defaultExport; }
        else if (entry.exports !== undefined) { exports = entry.exports; }
        if (exports) { out.push(exports); }
        if (exports !== entry) { out.push(entry); }
      }
    } catch (e) { /* pre-__debug build */ }
    return out;
  }

  // The classic moduleRaid trick for bundles without __debug: push a fake chunk
  // and let webpack hand us its own require, then enumerate every module.
  function chunkModules() {
    var out = [];
    try {
      var chunkKey = null;
      for (var key in window) {
        if (/^webpackChunk/.test(key) && window[key] && window[key].push) {
          chunkKey = key;
          break;
        }
      }
      if (!chunkKey) { return out; }
      var marker = 'titan_' + Date.now();
      window[chunkKey].push([[marker], {}, function (req) {
        var registry = req.m || {};
        for (var id in registry) {
          if (!registry.hasOwnProperty(id)) { continue; }
          try {
            var mod = req(id);
            if (mod) { out.push(mod); }
          } catch (e) { /* module refused to initialise */ }
        }
      }]);
    } catch (e) { /* not a webpack build we understand */ }
    return out;
  }

  function pick(modules, test) {
    for (var i = 0; i < modules.length; i++) {
      try {
        var value = test(modules[i]);
        if (value) { return value; }
      } catch (e) { /* wrong shape */ }
    }
    return null;
  }

  function discoverStore() {
    var collections = requireModule(['WAWebCollections', 'WAWebChatCollection']);
    if (collections) {
      S.Chat = S.Chat || collections.ChatCollection;
      S.Msg = S.Msg || collections.MsgCollection;
      S.Contact = S.Contact || collections.ContactCollection;
      S.GroupMetadata = S.GroupMetadata || collections.GroupMetadataCollection;
      S.Presence = S.Presence || collections.PresenceCollection;
      S.Newsletter = S.Newsletter || collections.NewsletterCollection;
    }

    var modules = debugModules();
    if (!S.Chat || !S.Msg) {
      modules = modules.concat(chunkModules());
    }
    if (!modules.length) { return; }

    // Collections - by name where the build still uses readable names, then by
    // shape (a Backbone-ish collection of models with the right constructor).
    S.Chat = S.Chat || pick(modules, function (m) { return m.ChatCollection; });
    S.Msg = S.Msg || pick(modules, function (m) { return m.MsgCollection; });
    S.Contact = S.Contact || pick(modules, function (m) { return m.ContactCollection; });
    S.GroupMetadata = S.GroupMetadata || pick(modules, function (m) { return m.GroupMetadataCollection; });
    S.Presence = S.Presence || pick(modules, function (m) { return m.PresenceCollection; });
    S.Newsletter = S.Newsletter || pick(modules, function (m) { return m.NewsletterCollection; });

    S.Chat = S.Chat || pick(modules, function (m) {
      return (m.getModelsArray && m.modelClass &&
              m.modelClass.name === 'Chat') ? m : null;
    });
    S.Msg = S.Msg || pick(modules, function (m) {
      return (m.getModelsArray && m.modelClass &&
              m.modelClass.name === 'Msg') ? m : null;
    });

    // Actions - all optional, each one is a capability.
    S.sendText = pick(modules, function (m) {
      return typeof m.sendTextMsgToChat === 'function' ? m.sendTextMsgToChat : null;
    });
    S.sendSeen = pick(modules, function (m) {
      return typeof m.sendSeen === 'function' ? m.sendSeen : null;
    });
    S.sendReaction = pick(modules, function (m) {
      return typeof m.sendReactionToMsg === 'function' ? m.sendReactionToMsg : null;
    });
    S.sendRevoke = pick(modules, function (m) {
      return typeof m.sendRevokeMsgs === 'function' ? m.sendRevokeMsgs : null;
    });
    S.sendEdit = pick(modules, function (m) {
      return typeof m.sendMsgEdit === 'function' ? m.sendMsgEdit : null;
    });
    S.loadEarlier = pick(modules, function (m) {
      return typeof m.loadEarlierMsgs === 'function' ? m.loadEarlierMsgs : null;
    });
    S.download = pick(modules, function (m) {
      return typeof m.downloadAndMaybeDecrypt === 'function'
        ? m.downloadAndMaybeDecrypt : null;
    });
    S.chatState = pick(modules, function (m) {
      return typeof m.sendChatStateComposing === 'function' ? m : null;
    });
    S.requestPairing = pick(modules, function (m) {
      return typeof m.requestPairingCode === 'function' ? m.requestPairingCode : null;
    });
    S.logout = pick(modules, function (m) {
      return typeof m.logout === 'function' ? m.logout : null;
    });
    S.Cmd = pick(modules, function (m) {
      return (m.Cmd && typeof m.Cmd.openChatAt === 'function') ? m.Cmd : null;
    });
    S.Wid = pick(modules, function (m) {
      return typeof m.createWid === 'function' ? m : null;
    });
    S.Stream = pick(modules, function (m) {
      return (m.Stream && (('mode' in m.Stream) || ('state' in m.Stream)))
        ? m.Stream : null;
    });
    S.Conn = pick(modules, function (m) {
      return (m.Conn && ('wid' in m.Conn)) ? m.Conn : null;
    });
  }

  function reportCapabilities() {
    caps = {};
    // Always available - the DOM fallback covers these.
    caps.attachments = true;
    caps.search = true;
    caps.archive = true;
    caps.voice_call = true;
    caps.video_call = true;
    caps.presence = true;
    caps.voice_notes = true;
    caps.participants = !!(S.GroupMetadata || true);
    caps.reactions = !!S.sendReaction;
    caps.edit = !!S.sendEdit;
    caps.delete = !!S.sendRevoke;
    caps.channels = !!S.Newsletter;
    caps.status_updates = !!S.Msg;      // status is a chat in the store, not in the DOM
    caps.communities = !!S.GroupMetadata;
    var list = [];
    for (var key in caps) { if (caps[key]) { list.push(key); } }
    return list;
  }

  function storeMode() { return !!(S.Chat && S.Msg); }

  // ------------------------------------------------------------ normalisation
  var TYPE_MAP = {
    chat: 'text', text: 'text', image: 'image', video: 'video', ptt: 'voice',
    audio: 'audio', document: 'document', sticker: 'sticker',
    location: 'location', vcard: 'document', 'multi_vcard': 'document',
    revoked: 'system', notification_template: 'system', gp2: 'system',
    e2e_notification: 'system', call_log: 'call', protocol: 'system'
  };

  function chatFromModel(c) {
    var id = serialized(c.id);
    var isGroup = !!c.isGroup || id.indexOf('@g.us') > -1;
    var kind = 'chat';
    if (id.indexOf('@newsletter') > -1) { kind = 'channel'; }
    else if (id.indexOf('status@broadcast') > -1) { kind = 'status'; }
    else if (isGroup) { kind = 'group'; }

    var lastText = '';
    var lastAuthor = '';
    try {
      var last = c.msgs && c.msgs.last && c.msgs.last();
      if (last) {
        lastText = last.body || last.caption || '';
        lastAuthor = last.senderObj ? (last.senderObj.formattedName ||
                                       last.senderObj.pushname || '') : '';
      }
    } catch (e) { /* no cached messages yet */ }

    return {
      id: id,
      name: c.formattedTitle || c.name ||
            (c.contact && (c.contact.formattedName || c.contact.pushname)) || id,
      is_group: isGroup,
      kind: kind,
      unread: Math.max(0, c.unreadCount || 0),
      last_message: lastText,
      last_message_at: (c.t || 0) * 1000,
      last_author: lastAuthor,
      archived: !!c.archive,
      pinned: !!c.pin,
      muted: !!(c.mute && (c.mute.isMuted || c.mute.expiration)),
      online: !!(c.presence && c.presence.isOnline)
    };
  }

  function msgFromModel(m) {
    var id = serialized(m.id);
    var chatId = '';
    try {
      chatId = serialized(m.id && m.id.remote) ||
               serialized(m.chat && m.chat.id) || '';
    } catch (e) { chatId = ''; }

    var kind = TYPE_MAP[m.type] || (m.type ? 'system' : 'text');
    var media = null;
    if (kind === 'image' || kind === 'video' || kind === 'audio' ||
        kind === 'voice' || kind === 'document' || kind === 'sticker') {
      media = {
        name: m.filename || (m.mimetype ? ('media.' + String(m.mimetype).split('/')[1]) : 'media'),
        mime: m.mimetype || '',
        size: m.size || 0,
        duration: m.duration || 0
      };
    }

    var author = '';
    try {
      if (m.id && m.id.fromMe) { author = ''; }
      else if (m.senderObj) {
        author = m.senderObj.formattedName || m.senderObj.pushname ||
                 serialized(m.senderObj.id);
      } else {
        author = serialized(m.author) || serialized(m.from);
      }
    } catch (e) { /* leave blank, the client falls back to the chat name */ }

    var quoted = null;
    try {
      if (m.quotedMsg) {
        quoted = {
          id: serialized(m.quotedStanzaID || (m.quotedMsg.id)),
          text: m.quotedMsg.body || m.quotedMsg.caption || '',
          author: m.quotedParticipant ? serialized(m.quotedParticipant) : ''
        };
      }
    } catch (e) { /* not quoting anything */ }

    var reactions = [];
    try {
      var raw = m.reactions || (m.latestEditMsgKey ? null : null);
      if (raw && raw.length) {
        for (var i = 0; i < raw.length; i++) {
          reactions.push({ emoji: raw[i].aggregateEmoji || raw[i].text || '',
                           count: raw[i].senders ? raw[i].senders.length : 1 });
        }
      }
    } catch (e) { /* reactions not cached */ }

    var ack = (typeof m.ack === 'number') ? m.ack : null;
    var status = '';
    if (ack !== null) {
      status = ack < 0 ? 'failed' : (ack === 0 ? 'pending' :
               (ack === 1 ? 'sent' : (ack === 2 ? 'delivered' : 'read')));
    }

    return {
      id: id,
      chat_id: chatId,
      text: m.body || m.caption || '',
      author: author,
      author_id: serialized(m.author) || serialized(m.from),
      timestamp: (m.t || 0) * 1000,
      outgoing: !!(m.id && m.id.fromMe),
      kind: kind,
      status: status,
      edited: !!(m.latestEditMsgKey || m.isEdited),
      deleted: m.type === 'revoked' || !!m.isRevoked,
      quoted: quoted,
      reactions: reactions,
      media: media
    };
  }

  // ---- DOM equivalents ----------------------------------------------------
  function chatFromDom(el, index) {
    var nameEl = D.q(['span[title]', 'div[role="gridcell"] span[dir="auto"]',
                      'span[dir="auto"][aria-label]'], el);
    var name = nameEl ? (nameEl.getAttribute('title') || D.text(nameEl)) : '';
    if (!name) { return null; }

    var previewEl = D.q(['div[role="gridcell"] span[dir="ltr"]',
                         'span[dir="ltr"]', 'span[dir="auto"]:not([title])'], el);
    var preview = previewEl ? D.text(previewEl) : '';
    if (preview === name) { preview = ''; }

    var unread = 0;
    var badge = D.q(['span[aria-label*="unread" i]', 'span[aria-label*="nieprzeczyt" i]',
                     '[data-testid="icon-unread-count"]'], el);
    if (badge) {
      var digits = (D.text(badge).match(/\d+/) || [])[0];
      unread = digits ? parseInt(digits, 10) : 1;
    }

    // The DOM has no chat id, so we key on the display name. Marked in extra so
    // callers know this row cannot be addressed by a real WhatsApp id.
    return {
      id: 'dom:' + name,
      name: name,
      is_group: false,
      kind: 'chat',
      unread: unread,
      last_message: preview,
      last_message_at: 0,
      dom_index: index,
      dom_only: true
    };
  }

  function msgFromDom(row) {
    var id = row.getAttribute('data-id') || '';
    var outgoing = /message-out/.test(row.className) ||
                   !!row.querySelector('.message-out');
    var textEl = D.q(['span.selectable-text span', 'span.selectable-text',
                      'div[data-pre-plain-text] span'], row);
    var text = textEl ? D.text(textEl) : '';

    var author = '';
    var meta = D.q(['div[data-pre-plain-text]'], row);
    var stamp = 0;
    if (meta) {
      var pre = meta.getAttribute('data-pre-plain-text') || '';
      // "[12:34, 5.06.2025] Name: "
      var match = pre.match(/^\[(.+?)\]\s*(.*?):\s*$/);
      if (match) {
        author = match[2] || '';
        var parsed = Date.parse(match[1]);
        if (!isNaN(parsed)) { stamp = parsed; }
      }
    }

    var kind = 'text';
    if (row.querySelector('[data-icon="audio-play"], audio')) { kind = 'voice'; }
    else if (row.querySelector('img[src^="blob:"], img[data-testid="image-thumb"]')) { kind = 'image'; }
    else if (row.querySelector('[data-icon="video-call"], video')) { kind = 'video'; }
    else if (row.querySelector('[data-icon="document"]')) { kind = 'document'; }
    else if (row.querySelector('[data-icon="sticker"]')) { kind = 'sticker'; }

    return {
      id: id || ('dom:' + (stamp || Date.now()) + ':' + text.slice(0, 24)),
      chat_id: currentDomChatId(),
      text: text,
      author: author,
      timestamp: stamp,
      outgoing: outgoing,
      kind: kind,
      dom_only: true
    };
  }

  function currentDomChatId() {
    var header = D.q(['#main header span[title]', 'header span[title]']);
    return header ? ('dom:' + (header.getAttribute('title') || D.text(header))) : '';
  }

  // ----------------------------------------------------------------- chat list
  function listChatsFromStore(scope) {
    var models = [];
    try { models = S.Chat.getModelsArray ? S.Chat.getModelsArray() : (S.Chat.models || []); }
    catch (e) { models = []; }

    var out = [];
    for (var i = 0; i < models.length; i++) {
      var chat = chatFromModel(models[i]);
      if (!chat.id) { continue; }
      if (scope === 'unread' && chat.unread <= 0) { continue; }
      if (scope === 'groups' && !chat.is_group) { continue; }
      if (scope === 'channels' && chat.kind !== 'channel') { continue; }
      if (scope === 'status' && chat.kind !== 'status') { continue; }
      if (scope === 'archived' && !chat.archived) { continue; }
      if ((scope === 'all' || scope === 'chats') && chat.archived) { continue; }
      if (scope === 'chats' && chat.kind !== 'chat' && chat.kind !== 'group') { continue; }
      out.push(chat);
    }
    out.sort(function (a, b) { return (b.last_message_at || 0) - (a.last_message_at || 0); });
    return out;
  }

  function listChatsFromDom(scope) {
    var items = D.qa(DOM_CHAT_ITEMS());
    var out = [];
    for (var i = 0; i < items.length; i++) {
      var chat = chatFromDom(items[i], i);
      if (!chat) { continue; }
      if (scope === 'unread' && chat.unread <= 0) { continue; }
      out.push(chat);
    }
    return out;
  }

  // ------------------------------------------------------------- chat lookup
  function findChatModel(chatId) {
    if (!S.Chat) { return null; }
    try {
      if (S.Chat.get) {
        var direct = S.Chat.get(chatId);
        if (direct) { return direct; }
      }
      var models = S.Chat.getModelsArray ? S.Chat.getModelsArray() : (S.Chat.models || []);
      for (var i = 0; i < models.length; i++) {
        if (serialized(models[i].id) === chatId) { return models[i]; }
      }
      // Allow addressing by display name - that is all the DOM path knows.
      var wanted = String(chatId).replace(/^dom:/, '');
      for (var j = 0; j < models.length; j++) {
        var chat = chatFromModel(models[j]);
        if (chat.name === wanted) { return models[j]; }
      }
    } catch (e) { /* fall through to null */ }
    return null;
  }

  function findDomChatItem(chatId) {
    var wanted = String(chatId).replace(/^dom:/, '');
    var items = D.qa(DOM_CHAT_ITEMS());
    for (var i = 0; i < items.length; i++) {
      var nameEl = D.q(['span[title]'], items[i]);
      var name = nameEl ? (nameEl.getAttribute('title') || D.text(nameEl)) : '';
      if (name && (name === wanted || name.indexOf(wanted) === 0)) { return items[i]; }
    }
    return null;
  }

  function openChat(chatId) {
    var model = findChatModel(chatId);
    if (model && S.Cmd) {
      try {
        S.Cmd.openChatAt(model);
        return { opened: true, via: 'store' };
      } catch (e) { /* fall back to the DOM */ }
    }
    var item = findDomChatItem(chatId);
    if (item) {
      D.click(item);
      return { opened: true, via: 'dom' };
    }
    throw new Error('chat not found: ' + chatId);
  }

  // -------------------------------------------------------------- history
  function historyFromStore(chatId, beforeId, limit) {
    var model = findChatModel(chatId);
    if (!model) { throw new Error('chat not found: ' + chatId); }

    function collect() {
      var msgs = [];
      try {
        var models = model.msgs && (model.msgs.getModelsArray
          ? model.msgs.getModelsArray() : model.msgs.models) || [];
        for (var i = 0; i < models.length; i++) { msgs.push(msgFromModel(models[i])); }
      } catch (e) { /* nothing cached */ }
      msgs.sort(function (a, b) { return (a.timestamp || 0) - (b.timestamp || 0); });
      if (beforeId) {
        for (var j = 0; j < msgs.length; j++) {
          if (msgs[j].id === beforeId) { msgs = msgs.slice(0, j); break; }
        }
      }
      if (limit && msgs.length > limit) { msgs = msgs.slice(msgs.length - limit); }
      return msgs;
    }

    var have = collect();
    if (have.length >= Math.min(limit || 50, 15) || !S.loadEarlier) {
      return { messages: have, has_more: true, via: 'store' };
    }
    // Too little cached - ask the app to pull an older page first.
    return Promise.resolve(S.loadEarlier(model)).then(function () {
      return { messages: collect(), has_more: true, via: 'store' };
    }, function () {
      return { messages: have, has_more: false, via: 'store' };
    });
  }

  function historyFromDom(limit) {
    var rows = D.qa(['#main div[role="row"]', 'div[role="application"] div[role="row"]']);
    var out = [];
    for (var i = 0; i < rows.length; i++) {
      var msg = msgFromDom(rows[i]);
      if (msg.text || msg.kind !== 'text') { out.push(msg); }
    }
    if (limit && out.length > limit) { out = out.slice(out.length - limit); }
    return { messages: out, has_more: rows.length > 0, via: 'dom' };
  }

  // ------------------------------------------------------------------ sending
  function sendViaStore(chatId, text, quotedId) {
    var model = findChatModel(chatId);
    if (!model || !S.sendText) { return null; }
    var options = {};
    if (quotedId && S.Msg && S.Msg.get) {
      try {
        var quoted = S.Msg.get(quotedId);
        if (quoted) { options.quotedMsg = quoted; }
      } catch (e) { /* send it unquoted rather than not at all */ }
    }
    return Promise.resolve(S.sendText(model, text, options))
      .then(function () { return { sent: true, via: 'store' }; });
  }

  function sendViaDom(chatId, text) {
    return Promise.resolve(openChat(chatId)).then(function () {
      return D.waitFor(function () { return D.q(DOM_COMPOSER()); }, 8000);
    }).then(function (box) {
      if (!D.typeInto(box, text)) { throw new Error('could not type into the composer'); }
      return D.waitFor(function () { return D.text(box).length > 0; }, 3000, 100)
        .catch(function () { return true; });
    }).then(function () {
      var box = D.q(DOM_COMPOSER());
      var button = D.q(['button[aria-label*="Send" i]', 'button[aria-label*="Wyślij" i]',
                        'span[data-icon="send"]', '[data-testid="send"]']);
      if (button) { D.click(button.closest('button') || button); }
      else { D.pressEnter(box); }
      return { sent: true, via: 'dom' };
    });
  }

  // ------------------------------------------------------------------- events
  function emitMessage(type, model, note) {
    var msg = msgFromModel(model);
    if (!msg.id) { return; }
    if (type === 'message_new' && seen(msg.id)) { return; }
    B.emit(type, { message: msg, note: note || '' });
  }

  function hookStoreEvents() {
    try {
      S.Msg.on('add', function (model) {
        try {
          if (model && model.isNewMsg === false) { return; }
          emitMessage('message_new', model);
        } catch (e) { B.fail('msg.add', e); }
      });
      S.Msg.on('change:ack', function (model) {
        try { emitMessage('message_updated', model); } catch (e) { /* noisy path */ }
      });
      S.Msg.on('change:reactions', function (model) {
        try { emitMessage('message_updated', model, 'reaction'); } catch (e) { }
      });
      S.Msg.on('remove', function (model) {
        try { emitMessage('message_updated', model, 'deleted'); } catch (e) { }
      });
    } catch (e) { B.fail('hook.msg', e); }

    try {
      var onChat = function (model) {
        try { B.emit('chat_updated', { chat: chatFromModel(model) }); }
        catch (e) { /* ignore a single bad model */ }
      };
      S.Chat.on('change:unreadCount', onChat);
      S.Chat.on('change:t', onChat);
      S.Chat.on('add', onChat);
    } catch (e) { B.fail('hook.chat', e); }

    if (S.Presence) {
      try {
        S.Presence.on('change:chatstate', function (model) {
          try { emitTyping(serialized(model.id), !!(model.chatstate &&
                 String(model.chatstate.type || '').indexOf('composing') > -1)); }
          catch (e) { }
        });
        S.Presence.on('change:isOnline', function (model) {
          B.emit('presence', { contact: { id: serialized(model.id),
                                          online: !!model.isOnline,
                                          last_seen: (model.t || 0) * 1000 } });
        });
      } catch (e) { /* presence shape differs - the DOM watcher covers it */ }
    }
  }

  function emitTyping(chatId, typing) {
    var now = Date.now();
    if (typing && lastTyping[chatId] && (now - lastTyping[chatId]) < 4000) { return; }
    lastTyping[chatId] = typing ? now : 0;
    var chat = null;
    try {
      var model = findChatModel(chatId);
      chat = model ? chatFromModel(model) : null;
    } catch (e) { chat = null; }
    B.emit('typing', {
      chat_id: chatId,
      name: chat ? chat.name : String(chatId).replace(/^dom:/, ''),
      typing: !!typing
    });
  }

  // ---- DOM watchers (always on: they are the second opinion) --------------
  var TYPING_RE = /(typing|pisze|schreibt|escribiendo|en train|digitando|recording|nagrywa)/i;

  function watchDom() {
    var pane = D.q(['#pane-side']);
    if (pane && !pane.__titanWatched) {
      pane.__titanWatched = true;
      new MutationObserver(throttle(function () {
        try {
          B.emit('chats', { chats: storeMode() ? listChatsFromStore('all')
                                               : listChatsFromDom('all'),
                            partial: false, via: storeMode() ? 'store' : 'dom' });
        } catch (e) { B.fail('watch.pane', e); }
      }, 1200)).observe(pane, { childList: true, subtree: true,
                                characterData: true });
    }

    var main = D.q(['#main']);
    if (main && !main.__titanWatched) {
      main.__titanWatched = true;
      new MutationObserver(throttle(function () {
        try {
          // Typing indicator: the header subtitle changes to "typing…".
          var subtitle = D.q(['#main header span[title]:last-of-type',
                              '#main header div[role="button"] span',
                              '#main header span[dir="auto"]']);
          var text = subtitle ? D.text(subtitle) : '';
          emitTypingFromDom(TYPING_RE.test(text));

          if (!storeMode()) {
            // Without the store, new rendered rows are the only signal we have.
            var rows = D.qa(['#main div[role="row"]']);
            for (var i = Math.max(0, rows.length - 6); i < rows.length; i++) {
              var msg = msgFromDom(rows[i]);
              if (!msg.text && msg.kind === 'text') { continue; }
              if (seen(msg.id)) { continue; }
              B.emit('message_new', { message: msg });
            }
          }
        } catch (e) { B.fail('watch.main', e); }
      }, 400)).observe(main, { childList: true, subtree: true, characterData: true });
    }
  }

  var domTypingChat = '';
  function emitTypingFromDom(typing) {
    var chatId = currentDomChatId();
    if (!chatId) { return; }
    if (typing) {
      domTypingChat = chatId;
      emitTyping(chatId, true);
    } else if (domTypingChat) {
      var previous = domTypingChat;
      domTypingChat = '';
      emitTyping(previous, false);
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
  function detectAuth() {
    // Store first: Stream.mode/state is authoritative and language independent.
    if (S.Stream) {
      var mode = S.Stream.mode || S.Stream.state || '';
      if (mode === 'MAIN' || mode === 'CONNECTED') { return { state: 'logged_in' }; }
      if (mode === 'QR' || mode === 'OPENING') {
        return pairingVisible() ? { state: 'pairing' } : { state: 'qr' };
      }
      if (mode === 'SYNCING' || mode === 'RESUMING') { return { state: 'loading' }; }
    }

    if (D.q(['#pane-side'])) { return { state: 'logged_in' }; }

    var code = readPairingCode();
    if (code) { return { state: 'pairing', pairing_code: code }; }

    if (D.q(['canvas[aria-label*="scan" i]', '[data-testid="qrcode"]',
             'canvas[role="img"]', 'div[data-testid="qrcode"]'])) {
      return { state: 'qr' };
    }
    return { state: 'loading' };
  }

  function pairingVisible() { return !!readPairingCode(); }

  function readPairingCode() {
    // The pairing screen renders the 8 characters as separate cells.
    var wrap = D.q(['[data-testid="link-device-phone-number-code-screen"]',
                    'div[aria-details*="pairing" i]',
                    'div[role="main"] div[aria-label*="code" i]']);
    var cells = wrap ? D.qa(['span', 'div'], wrap) : [];
    var chars = [];
    for (var i = 0; i < cells.length; i++) {
      var value = D.text(cells[i]);
      if (value.length === 1 && /[A-Z0-9]/i.test(value)) { chars.push(value); }
    }
    if (chars.length >= 8) { return chars.slice(0, 8).join(''); }
    return '';
  }

  var lastAuthJson = '';
  function pushAuth(force) {
    var next = detectAuth();
    var json = JSON.stringify(next);
    if (!force && json === lastAuthJson) { return next; }
    lastAuthJson = json;
    auth = next;
    B.emit('auth_state', next);
    return next;
  }

  // Ask WhatsApp for a pairing code for ``phone`` instead of making a blind
  // user deal with a QR image. The store path is preferred; the DOM path walks
  // the same wizard a sighted user would.
  function startPairing(phone) {
    if (S.requestPairing && phone) {
      return Promise.resolve(S.requestPairing(String(phone).replace(/[^\d]/g, '')))
        .then(function (result) {
          var code = (result && (result.code || result.pairingCode)) || readPairingCode();
          pushAuth(true);
          return { method: 'pairing', pairing_code: code || '', via: 'store' };
        });
    }

    var link = D.q(['[data-testid="link-device-phone-number-entry-screen"]',
                    'div[role="button"][tabindex]']);
    var byText = null;
    var buttons = D.qa(['div[role="button"]', 'button', 'a']);
    for (var i = 0; i < buttons.length; i++) {
      if (/phone number|numer telefonu/i.test(D.text(buttons[i]))) {
        byText = buttons[i];
        break;
      }
    }
    var target = byText || link;
    if (!target) { throw new Error('pairing entry point not found'); }
    D.click(target);

    return D.waitFor(function () {
      return D.q(['input[aria-label*="phone" i]', 'input[type="text"]']);
    }, 8000).then(function (input) {
      if (phone) {
        D.typeInto(input, String(phone));
        var next = null;
        var candidates = D.qa(['div[role="button"]', 'button']);
        for (var i = 0; i < candidates.length; i++) {
          if (/next|dalej|continue|kontynuuj/i.test(D.text(candidates[i]))) {
            next = candidates[i];
            break;
          }
        }
        if (next) { D.click(next); }
      }
      return D.waitFor(readPairingCode, 20000, 500);
    }).then(function (code) {
      pushAuth(true);
      return { method: 'pairing', pairing_code: code, via: 'dom' };
    });
  }

  // -------------------------------------------------------------------- calls
  function armCallMonitor() {
    try { %%CALL_MONITOR%% } catch (e) { B.fail('call_monitor', e); }
  }

  function callPeerName() {
    var el = D.q(['[data-testid="call-header-title"]', 'div[data-testid*="call"] span[title]',
                  '#main header span[title]']);
    return el ? (el.getAttribute('title') || D.text(el)) : '';
  }

  function drainCallEvents() {
    var state = window.__titanCallState;
    if (!state || !state.events || !state.events.length) { return; }
    var events = state.events.splice(0, state.events.length);
    for (var i = 0; i < events.length; i++) {
      var mapped = { incoming: 'ringing_in', outgoing: 'ringing_out',
                     connected: 'connected', ended: 'ended' }[events[i]];
      if (!mapped) { continue; }
      B.emit('call', {
        state: mapped,
        peer: callPeerName(),
        video: !!D.q(['[aria-label*="Video call" i][aria-pressed="true"]', 'video']),
        started_at: state.startedAt || 0
      });
    }
  }

  function callControl(kind) {
    var patterns = {
      accept: ['[aria-label*="Accept" i]', '[aria-label*="Answer" i]',
               '[data-testid*="accept-call" i]', '[aria-label*="Odbierz" i]'],
      end: ['[aria-label*="End call" i]', '[aria-label*="Hang up" i]',
            '[aria-label*="Leave call" i]', '[data-testid*="end-call" i]',
            '[aria-label*="Zako" i]', '[aria-label*="Decline" i]']
    }[kind] || [];
    var button = D.q(patterns);
    if (!button) { throw new Error('call control not available: ' + kind); }
    D.click(button.closest('button') || button);
    return { done: true };
  }

  // ----------------------------------------------------------------- commands
  B.command('auth_state', function () { return pushAuth(true); });

  B.command('login_start', function (args) {
    if (args.method === 'pairing' || args.phone) { return startPairing(args.phone); }
    var state = pushAuth(true);
    return { method: 'qr', state: state.state };
  });

  B.command('logout', function () {
    if (S.logout) { return Promise.resolve(S.logout()).then(function () { return { done: true }; }); }
    var menu = D.q(['[data-testid="menu"]', 'div[aria-label*="Menu" i]']);
    if (menu) { D.click(menu); }
    return { done: false, needs_page: true };
  });

  B.command('list_chats', function (args) {
    var scope = args.scope || 'all';
    var chats = storeMode() ? listChatsFromStore(scope) : listChatsFromDom(scope);
    return { chats: chats, via: storeMode() ? 'store' : 'dom' };
  });

  B.command('open_chat', function (args) { return openChat(args.chat_id); });

  B.command('load_history', function (args) {
    var limit = args.limit || 50;
    if (storeMode()) {
      try { return historyFromStore(args.chat_id, args.before_id || '', limit); }
      catch (e) { /* chat not in the store - use what is rendered */ }
    }
    return Promise.resolve(openChat(args.chat_id)).then(function () {
      return D.waitFor(function () {
        return D.qa(['#main div[role="row"]']).length > 0;
      }, 8000).catch(function () { return true; });
    }).then(function () { return historyFromDom(limit); });
  });

  B.command('send_text', function (args) {
    var viaStore = null;
    try { viaStore = sendViaStore(args.chat_id, args.text, ''); } catch (e) { viaStore = null; }
    if (viaStore) {
      return viaStore.catch(function () { return sendViaDom(args.chat_id, args.text); });
    }
    return sendViaDom(args.chat_id, args.text);
  });

  B.command('reply_to', function (args) {
    var viaStore = null;
    try { viaStore = sendViaStore(args.chat_id, args.text, args.msg_id); }
    catch (e) { viaStore = null; }
    if (viaStore) { return viaStore; }
    // DOM path: quoting needs the row context menu, so fall back to a plain
    // send rather than silently dropping the message.
    return sendViaDom(args.chat_id, args.text);
  });

  B.command('react', function (args) {
    if (!S.sendReaction || !S.Msg || !S.Msg.get) {
      throw new Error('reactions are not available in this build');
    }
    var msg = S.Msg.get(args.msg_id);
    if (!msg) { throw new Error('message not found'); }
    return Promise.resolve(S.sendReaction(msg, args.emoji || ''))
      .then(function () { return { done: true }; });
  });

  B.command('edit_message', function (args) {
    if (!S.sendEdit || !S.Msg || !S.Msg.get) {
      throw new Error('editing is not available in this build');
    }
    var msg = S.Msg.get(args.msg_id);
    if (!msg) { throw new Error('message not found'); }
    return Promise.resolve(S.sendEdit(msg, args.text, {}))
      .then(function () { return { done: true }; });
  });

  B.command('delete_message', function (args) {
    if (!S.sendRevoke || !S.Msg || !S.Msg.get) {
      throw new Error('deleting is not available in this build');
    }
    var msg = S.Msg.get(args.msg_id);
    if (!msg) { throw new Error('message not found'); }
    var chat = findChatModel(args.chat_id);
    return Promise.resolve(S.sendRevoke(chat, [msg], !!args.everyone))
      .then(function () { return { done: true }; });
  });

  B.command('mark_read', function (args) {
    var model = findChatModel(args.chat_id);
    if (model && S.sendSeen) {
      return Promise.resolve(S.sendSeen(model, false))
        .then(function () { return { done: true, via: 'store' }; });
    }
    // Opening a chat is what marks it read in the UI.
    return Promise.resolve(openChat(args.chat_id)).then(function () {
      return { done: true, via: 'dom' };
    });
  });

  B.command('set_typing', function (args) {
    if (!S.chatState) { return { done: false }; }
    var model = findChatModel(args.chat_id);
    if (!model) { return { done: false }; }
    var fn = args.typing ? S.chatState.sendChatStateComposing
                         : S.chatState.sendChatStatePaused;
    return Promise.resolve(fn.call(S.chatState, model.id))
      .then(function () { return { done: true }; }, function () { return { done: false }; });
  });

  B.command('set_presence', function (args) {
    var fn = args.online ? (S.chatState && S.chatState.sendPresenceAvailable)
                         : (S.chatState && S.chatState.sendPresenceUnavailable);
    if (!fn) { return { done: false }; }
    return Promise.resolve(fn.call(S.chatState)).then(function () { return { done: true }; });
  });

  B.command('search', function (args) {
    var query = String(args.query || '').toLowerCase();
    if (!query) { return { chats: [], messages: [] }; }

    var chats = (storeMode() ? listChatsFromStore('all') : listChatsFromDom('all'))
      .filter(function (chat) { return chat.name.toLowerCase().indexOf(query) > -1; });

    var messages = [];
    if (storeMode() && S.Msg) {
      try {
        var models = S.Msg.getModelsArray ? S.Msg.getModelsArray() : (S.Msg.models || []);
        for (var i = 0; i < models.length && messages.length < 200; i++) {
          var msg = msgFromModel(models[i]);
          if (args.chat_id && msg.chat_id !== args.chat_id) { continue; }
          if (msg.text && msg.text.toLowerCase().indexOf(query) > -1) { messages.push(msg); }
        }
      } catch (e) { /* return whatever matched */ }
    }
    return { chats: chats, messages: messages };
  });

  B.command('list_participants', function (args) {
    var model = findChatModel(args.chat_id);
    var out = [];
    try {
      var group = model && model.groupMetadata;
      if (!group && S.GroupMetadata && S.GroupMetadata.get && model) {
        group = S.GroupMetadata.get(model.id);
      }
      var participants = group && (group.participants &&
        (group.participants.getModelsArray ? group.participants.getModelsArray()
                                           : group.participants.models ||
                                             group.participants)) || [];
      for (var i = 0; i < participants.length; i++) {
        var participant = participants[i];
        var id = serialized(participant.id);
        var contact = null;
        try { contact = S.Contact && S.Contact.get && S.Contact.get(participant.id); }
        catch (e) { contact = null; }
        out.push({
          id: id,
          name: contact ? (contact.formattedName || contact.pushname || id) : id,
          online: false,
          is_admin: !!(participant.isAdmin || participant.isSuperAdmin)
        });
      }
    } catch (e) { /* not a group, or metadata not synced */ }
    return { contacts: out };
  });

  B.command('list_contacts', function () {
    var out = [];
    try {
      var models = S.Contact && (S.Contact.getModelsArray
        ? S.Contact.getModelsArray() : S.Contact.models) || [];
      for (var i = 0; i < models.length; i++) {
        var contact = models[i];
        if (contact.isMe || (!contact.isMyContact && !contact.isWAContact)) { continue; }
        out.push({
          id: serialized(contact.id),
          name: contact.formattedName || contact.pushname || serialized(contact.id),
          online: false
        });
      }
    } catch (e) { /* no contact collection in this build */ }
    return { contacts: out };
  });

  B.command('send_attachment', function (args) {
    var slot = B.blobs[args.blob_id];
    if (!slot || !slot.file) { throw new Error('attachment not uploaded'); }

    return Promise.resolve(openChat(args.chat_id)).then(function () {
      return D.waitFor(function () {
        return D.q(['input[type="file"]']) || D.q(DOM_COMPOSER());
      }, 8000);
    }).then(function () {
      // The reliable route is the page's own file input: it runs WhatsApp's
      // encryption and upload code, which we cannot reimplement.
      var input = D.q(['input[type="file"][accept*="image"]', 'input[type="file"]']);
      if (!input) { throw new Error('file input not found'); }
      var transfer = new DataTransfer();
      transfer.items.add(slot.file);
      input.files = transfer.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      return D.waitFor(function () {
        return D.q(['div[aria-label*="Send" i]', 'span[data-icon="send"]',
                    '[data-testid="send"]']);
      }, 15000);
    }).then(function (button) {
      if (args.caption) {
        var caption = D.q(['div[contenteditable="true"][data-tab="10"]',
                           'div[contenteditable="true"]']);
        if (caption) { D.typeInto(caption, args.caption); }
      }
      D.click(button.closest('button') || button);
      return { sent: true, via: 'dom' };
    });
  });

  B.command('download_media', function (args) {
    if (!S.Msg || !S.Msg.get) { throw new Error('media download needs the store'); }
    var msg = S.Msg.get(args.msg_id);
    if (!msg) { throw new Error('message not found'); }

    function finish(blob, name, mime) {
      return D.toBase64(blob).then(function (b64) {
        return B.putBlob(args.msg_id, b64, name, mime || (blob && blob.type) || '');
      });
    }

    var name = msg.filename ||
               ('media_' + (msg.t || Date.now()) +
                (msg.mimetype ? '.' + String(msg.mimetype).split('/')[1].split(';')[0] : '.bin'));

    // downloadAndMaybeDecrypt is the store's own path and handles E2E media.
    if (S.download && msg.directPath && msg.mediaKey) {
      return Promise.resolve(S.download({
        directPath: msg.directPath, encFilehash: msg.encFilehash,
        filehash: msg.filehash, mediaKey: msg.mediaKey,
        mediaKeyTimestamp: msg.mediaKeyTimestamp,
        type: msg.type, signal: (new AbortController()).signal
      })).then(function (blob) { return finish(blob, name, msg.mimetype); });
    }

    // Fall back to whatever the model already downloaded for rendering.
    return Promise.resolve(msg.downloadMedia ? msg.downloadMedia() : null)
      .then(function () {
        var url = msg.mediaData && (msg.mediaData.mediaBlob || msg.mediaData.filehash);
        if (url && url.forceToBlob) { return url.forceToBlob(); }
        if (msg.mediaData && msg.mediaData.mediaBlob) { return msg.mediaData.mediaBlob; }
        throw new Error('media is not available yet - open the message once');
      }).then(function (blob) { return finish(blob, name, msg.mimetype); });
  });

  B.command('start_call', function (args) {
    return Promise.resolve(openChat(args.chat_id)).then(function () {
      var patterns = args.video
        ? ['[aria-label*="Video call" i]', '[aria-label*="Rozmowa wideo" i]',
           '[data-testid="video-call-btn"]']
        : ['[aria-label*="Voice call" i]', '[aria-label*="Połączenie" i]',
           '[data-testid="audio-call-btn"]'];
      return D.waitFor(function () { return D.q(patterns); }, 8000);
    }).then(function (button) {
      D.click(button.closest('button') || button);
      return { started: true };
    });
  });

  B.command('accept_call', function () { return callControl('accept'); });
  B.command('end_call', function () { return callControl('end'); });

  // ------------------------------------------------------------------- probes
  B.probe('store.chats', function () { return !!S.Chat; });
  B.probe('store.messages', function () { return !!S.Msg; });
  B.probe('store.send', function () { return !!S.sendText; });
  B.probe('store.reactions', function () { return !!S.sendReaction; });
  B.probe('store.download', function () { return !!S.download; });
  B.probe('dom.chat_list', function () { return !!D.q(['#pane-side']); });
  B.probe('dom.composer', function () { return !!D.q(DOM_COMPOSER()); });
  B.probe('call_monitor', function () { return !!window.__titanCallState; });

  // -------------------------------------------------------------------- boot
  var booted = false;
  var attempts = 0;
  var lastCaps = '';

  function boot() {
    attempts++;
    try { discoverStore(); } catch (e) { B.fail('discover', e); }

    if (booted) {
      // The store can appear minutes after the page settles. When it does, the
      // set of things we can offer grows, so tell the client again - that is
      // what makes the extra tabs and menu items show up without a restart.
      var caps = reportCapabilities();
      var signature = caps.slice(0).sort().join(',');
      if (signature !== lastCaps) {
        lastCaps = signature;
        if (storeMode() && !window.__titanStoreHooked) {
          window.__titanStoreHooked = true;
          try { hookStoreEvents(); } catch (e) { B.fail('hook.late', e); }
        }
        B.ready(caps);
      }
    }

    if (!booted) {
      var haveStore = storeMode();
      var haveDom = !!D.q(['#pane-side']) || !!D.q(['canvas[role="img"]']);
      if (haveStore || haveDom || attempts > 20) {
        booted = true;
        if (haveStore) {
          window.__titanStoreHooked = true;
          try { hookStoreEvents(); } catch (e) { B.fail('hook', e); }
        }
        armCallMonitor();
        var initialCaps = reportCapabilities();
        lastCaps = initialCaps.slice(0).sort().join(',');
        B.ready(initialCaps);
        pushAuth(true);
      }
    }

    watchDom();
    pushAuth(false);
    drainCallEvents();
    // Re-discovery keeps running on the interval below: WhatsApp loads its store
    // lazily, and a store that shows up after boot silently upgrades us out of
    // DOM mode - including the capabilities we report.
  }

  function start() {
    boot();
    setInterval(boot, 2000);
    setInterval(drainCallEvents, 500);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
"""


def build_whatsapp_agent() -> str:
    """Return the WhatsApp agent with the shared call monitor inlined."""
    return WHATSAPP_AGENT.replace('%%CALL_MONITOR%%',
                                  build_monitor_script('WhatsApp'))
