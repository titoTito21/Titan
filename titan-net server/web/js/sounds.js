// Titan-Net notification sounds — plays .ogg files from /titannet/sounds/
// Mirrors the desktop's play_sound() for the events the browser portal hits.
(function () {
  'use strict';

  const STORAGE_KEY = 'titan.sounds';
  // event id -> default file in /titannet/sounds/
  const EVENT_FILES = {
    chat_message: 'new_message.ogg',
    private_message: 'new_message.ogg',
    message_sent: 'message_send.ogg',
    user_online: 'online.ogg',
    user_offline: 'offline.ogg',
    account_created: 'account_created.ogg',
    motd: 'motd.ogg',
    notification: 'titannet-notification.ogg',
    new_chat: 'new_chat.ogg',
    voice_start: 'walkietalkie.ogg',
    voice_stop: 'walkietalkieend.ogg',
    moderation: 'moderation.ogg',
    success: 'titannet_success.ogg',
    forum_reply: 'newreplies.ogg',
    bye: 'bye.ogg',
    connecting: 'connecting.ogg',
    connected: 'titannet_success.ogg',
    login_welcome: 'welcome_to_im.ogg',
    logout: 'bye.ogg',
  };
  // event id -> i18n key (used by the settings UI checkboxes)
  const EVENT_LABELS = {
    chat_message: 'sounds.ev.chat_message',
    private_message: 'sounds.ev.private_message',
    message_sent: 'sounds.ev.message_sent',
    user_online: 'sounds.ev.user_online',
    user_offline: 'sounds.ev.user_offline',
    account_created: 'sounds.ev.account_created',
    motd: 'sounds.ev.motd',
    notification: 'sounds.ev.notification',
    new_chat: 'sounds.ev.new_chat',
    voice_start: 'sounds.ev.voice_start',
    voice_stop: 'sounds.ev.voice_stop',
    moderation: 'sounds.ev.moderation',
    success: 'sounds.ev.success',
    forum_reply: 'sounds.ev.forum_reply',
    connecting: 'sounds.ev.connecting',
    connected: 'sounds.ev.connected',
    login_welcome: 'sounds.ev.login_welcome',
    logout: 'sounds.ev.logout',
  };

  function defaults() {
    const ev = {};
    Object.keys(EVENT_FILES).forEach((k) => { ev[k] = true; });
    return {
      enabled: true,
      volume: 0.8,
      events: ev,
    };
  }

  function loadPrefs() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return defaults();
      const parsed = JSON.parse(raw);
      const d = defaults();
      d.enabled = !!parsed.enabled;
      if (typeof parsed.volume === 'number') d.volume = parsed.volume;
      if (parsed.events && typeof parsed.events === 'object') {
        Object.keys(d.events).forEach((k) => {
          if (typeof parsed.events[k] === 'boolean') d.events[k] = parsed.events[k];
        });
      }
      return d;
    } catch (e) {
      return defaults();
    }
  }

  function savePrefs(p) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
  }

  let prefs = loadPrefs();

  // Cross-tab sync: settings changes from settings.html propagate to other
  // open pages without requiring a refresh.
  window.addEventListener('storage', (e) => {
    if (e.key === STORAGE_KEY) prefs = loadPrefs();
  });

  // Resolve URL relative to /titannet/ regardless of current page depth
  function soundUrl(file) {
    // All portal pages live at /titannet/*.html, so a relative path is fine
    return 'sounds/' + file;
  }

  // Reuse Audio objects per file — avoids creating dozens of objects per chat
  const audioCache = {};
  function getAudio(file) {
    if (!audioCache[file]) {
      const a = new Audio(soundUrl(file));
      a.preload = 'auto';
      audioCache[file] = a;
    }
    return audioCache[file];
  }

  // Browsers block Audio.play() until the page receives a real user gesture.
  // The desktop titannet-gui has no such restriction, which is why sounds
  // worked there but the browser stayed quiet for the first incoming event
  // (motd, chat_message, user_online, …).
  //
  // We unlock on the first pointer / key / touch by playing a SEPARATE,
  // throwaway audio element muted. User activation is sticky per-document
  // in all current browsers (Chrome, Firefox, Edge, Safari 15+), so a single
  // successful play() grants permission for every subsequent .play() on any
  // other Audio element on this page — no need to touch our cached audios.
  //
  // The previous implementation primed each cached element with
  // play()+pause(), but the pause() ran from an async promise callback and
  // would fire AFTER a real play(eventId) had already started a real sound,
  // pausing it instantly. That broke playback completely; this version
  // avoids the race by only touching one disposable element.
  let audioUnlocked = false;
  let queuedEvents = [];
  function unlockAudio() {
    if (audioUnlocked) return;
    audioUnlocked = true;
    try {
      // Reuse any cached file — one user-gesture play on any element grants
      // document-level activation. message_send.ogg is the smallest file in
      // the bundle so the network cost is negligible.
      const probe = new Audio(soundUrl('message_send.ogg'));
      probe.muted = true;
      probe.volume = 0;
      const p = probe.play();
      if (p && typeof p.then === 'function') {
        p.then(() => { try { probe.pause(); } catch (e) {} })
         .catch(() => {});
      }
    } catch (e) {}
    // Flush any events that fired before the user clicked — typical case is
    // the MOTD sound on chat.html which fires during bootstrap.
    const pending = queuedEvents;
    queuedEvents = [];
    pending.forEach((id) => play(id));
    window.removeEventListener('pointerdown', unlockAudio, true);
    window.removeEventListener('keydown', unlockAudio, true);
    window.removeEventListener('touchstart', unlockAudio, true);
  }
  window.addEventListener('pointerdown', unlockAudio, true);
  window.addEventListener('keydown', unlockAudio, true);
  window.addEventListener('touchstart', unlockAudio, true);

  function play(eventId) {
    if (!prefs.enabled) return;
    if (prefs.events[eventId] === false) return;
    const file = EVENT_FILES[eventId];
    if (!file) return;
    // If the page has not yet received a user gesture, autoplay will be
    // rejected. Queue the event so we can replay it the moment the user
    // does interact (typical case: the MOTD sound fires during chat.html
    // bootstrap, before the user clicks anything on this page). Keep the
    // queue small so a flood of background events doesn't burst at once.
    if (!audioUnlocked) {
      if (queuedEvents.length < 4) queuedEvents.push(eventId);
      return;
    }
    try {
      const a = getAudio(file);
      // Restart from the beginning so rapid-fire events still play
      a.currentTime = 0;
      a.volume = Math.max(0, Math.min(1, prefs.volume));
      const p = a.play();
      if (p && typeof p.catch === 'function') {
        // Autoplay can be blocked until the user interacts with the page —
        // swallow that quietly. The next event after a click will work.
        p.catch(() => {});
      }
    } catch (e) {}
  }

  // Play an arbitrary file (used by the settings "Test" button)
  function playFile(file) {
    try {
      const a = getAudio(file);
      a.currentTime = 0;
      a.volume = Math.max(0, Math.min(1, prefs.volume));
      const p = a.play();
      if (p && typeof p.catch === 'function') p.catch(() => {});
    } catch (e) {}
  }

  function getPrefs() {
    // Return a deep-ish copy so callers can't mutate our state directly
    return {
      enabled: prefs.enabled,
      volume: prefs.volume,
      events: Object.assign({}, prefs.events),
    };
  }

  function setPrefs(patch) {
    if (!patch) return;
    if (typeof patch.enabled === 'boolean') prefs.enabled = patch.enabled;
    if (typeof patch.volume === 'number') prefs.volume = patch.volume;
    if (patch.events && typeof patch.events === 'object') {
      Object.keys(patch.events).forEach((k) => {
        if (k in prefs.events) prefs.events[k] = !!patch.events[k];
      });
    }
    savePrefs(prefs);
    window.dispatchEvent(new CustomEvent('titan:sounds-prefs'));
  }

  function listEvents() {
    return Object.keys(EVENT_FILES).map((id) => ({
      id,
      file: EVENT_FILES[id],
      labelKey: EVENT_LABELS[id] || id,
    }));
  }

  window.Titan = window.Titan || {};
  window.Titan.sounds = {
    play, playFile,
    getPrefs, setPrefs,
    listEvents,
  };
})();
