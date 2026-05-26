// Titan-Net TTS notifications (Web Speech API)
// Mirrors the desktop's speak_notification() — every chat / presence /
// voice event gets spoken when TTS is enabled.
(function () {
  'use strict';

  const STORAGE_KEY = 'titan.tts';

  function loadPrefs() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return defaults();
      return Object.assign(defaults(), JSON.parse(raw));
    } catch (e) {
      return defaults();
    }
  }
  function defaults() {
    return {
      enabled: true,
      rate: 1.0,
      pitch: 1.0,
      volume: 1.0,
      voice: '',     // empty = browser default for current lang
      announceMessages: true,
      announcePresence: true,
      announceVoice: true,
      announcePrivate: true,
    };
  }
  function savePrefs(p) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
  }

  let prefs = loadPrefs();
  let voicesCache = null;

  // Cross-tab sync: when settings.html updates prefs, other open pages
  // (chat.html, forum.html, etc.) pick up the change without a refresh.
  window.addEventListener('storage', (e) => {
    if (e.key === STORAGE_KEY) prefs = loadPrefs();
  });

  function refreshVoices() {
    if (typeof speechSynthesis === 'undefined') return [];
    voicesCache = speechSynthesis.getVoices() || [];
    return voicesCache;
  }
  if (typeof speechSynthesis !== 'undefined') {
    refreshVoices();
    if (speechSynthesis.onvoiceschanged !== undefined) {
      speechSynthesis.onvoiceschanged = refreshVoices;
    }
  }

  function pickVoice(lang) {
    if (!voicesCache) refreshVoices();
    if (!voicesCache || voicesCache.length === 0) return null;
    // Honor explicit user choice
    if (prefs.voice) {
      const v = voicesCache.find((vv) => vv.name === prefs.voice);
      if (v) return v;
    }
    const want = (lang || 'en').toLowerCase();
    // Match `pl` to pl-PL, `en` to en-US/en-GB/etc.
    const exact = voicesCache.find((vv) => vv.lang && vv.lang.toLowerCase() === want);
    if (exact) return exact;
    const partial = voicesCache.find((vv) => vv.lang && vv.lang.toLowerCase().startsWith(want));
    if (partial) return partial;
    return null;
  }

  function speak(text, opts) {
    if (!prefs.enabled || !text) return;
    if (typeof speechSynthesis === 'undefined') return;
    opts = opts || {};
    if (opts.interrupt) {
      try { speechSynthesis.cancel(); } catch (e) {}
    }
    const u = new SpeechSynthesisUtterance(String(text));
    const lang = opts.lang || Titan.getLang();
    u.lang = lang === 'pl' ? 'pl-PL' : 'en-US';
    const v = pickVoice(u.lang);
    if (v) u.voice = v;
    u.rate = opts.rate != null ? opts.rate : prefs.rate;
    u.pitch = opts.pitch != null ? opts.pitch : prefs.pitch;
    u.volume = opts.volume != null ? opts.volume : prefs.volume;
    try { speechSynthesis.speak(u); } catch (e) {}
  }

  function stop() {
    if (typeof speechSynthesis !== 'undefined') {
      try { speechSynthesis.cancel(); } catch (e) {}
    }
  }

  function getPrefs() { return Object.assign({}, prefs); }
  function setPrefs(patch) {
    prefs = Object.assign(prefs, patch || {});
    savePrefs(prefs);
    window.dispatchEvent(new CustomEvent('titan:tts-prefs'));
  }

  function listVoices() {
    if (!voicesCache) refreshVoices();
    return (voicesCache || []).slice().sort((a, b) => a.lang.localeCompare(b.lang));
  }

  // High-level helpers mirroring desktop speak_notification categories
  function announceMessage(author, text) {
    if (!prefs.announceMessages) return;
    const t = Titan.t('tts.msg_from', author) + '. ' + text;
    speak(t);
  }
  function announcePrivate(author, text) {
    if (!prefs.announcePrivate) return;
    speak(Titan.t('tts.private_from', author) + '. ' + text, { interrupt: true });
  }
  function announceUserOnline(username) {
    if (!prefs.announcePresence) return;
    speak(Titan.t('tts.user_online', username));
  }
  function announceUserOffline(username) {
    if (!prefs.announcePresence) return;
    speak(Titan.t('tts.user_offline', username));
  }
  function announceVoiceStart(username) {
    if (!prefs.announceVoice) return;
    speak(Titan.t('voice.speaking', username));
  }
  function announceSystem(text) {
    speak(text, { interrupt: true });
  }

  window.Titan = window.Titan || {};
  window.Titan.tts = {
    speak, stop,
    getPrefs, setPrefs, listVoices,
    announceMessage, announcePrivate,
    announceUserOnline, announceUserOffline,
    announceVoiceStart, announceSystem,
  };
})();
