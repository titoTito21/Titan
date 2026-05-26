// Titan-Net shared bootstrap — header controls, theme, live region, session
(function () {
  'use strict';

  const STORAGE_TOKEN = 'titan.session';
  const STORAGE_THEME = 'titan.theme';

  function loadSession() {
    try {
      const raw = localStorage.getItem(STORAGE_TOKEN);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (e) {
      return null;
    }
  }

  function saveSession(s) {
    if (s === null) localStorage.removeItem(STORAGE_TOKEN);
    else localStorage.setItem(STORAGE_TOKEN, JSON.stringify(s));
    window.dispatchEvent(new CustomEvent('titan:session-changed'));
  }

  function getToken() {
    const s = loadSession();
    return s && s.token ? s.token : null;
  }

  function getUser() {
    const s = loadSession();
    return s && s.user ? s.user : null;
  }

  function applyTheme() {
    const stored = localStorage.getItem(STORAGE_THEME) || 'auto';
    if (stored === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', stored);
    return stored;
  }

  function setTheme(t) {
    localStorage.setItem(STORAGE_THEME, t);
    applyTheme();
  }

  // Announce to screen readers via the page's polite live region
  function announce(text) {
    const r = document.getElementById('live-polite');
    if (!r) return;
    // Toggle text so SRs re-announce identical messages
    r.textContent = '';
    setTimeout(() => { r.textContent = text; }, 50);
  }

  function updateAuthNav() {
    const user = getUser();
    const loggedIn = document.querySelectorAll('[data-auth="in"]');
    const loggedOut = document.querySelectorAll('[data-auth="out"]');
    loggedIn.forEach((el) => { el.hidden = !user; });
    loggedOut.forEach((el) => { el.hidden = !!user; });
    const nameEl = document.querySelector('[data-bind="username"]');
    if (nameEl && user) nameEl.textContent = user.username;
  }

  function setupHeader() {
    // Mark current page in nav
    const path = location.pathname.split('/').pop() || 'index.html';
    document.querySelectorAll('.primary-nav a').forEach((a) => {
      const href = (a.getAttribute('href') || '').split('/').pop();
      if (href === path) a.setAttribute('aria-current', 'page');
    });

    // Language switcher
    const langSelect = document.getElementById('lang-select');
    if (langSelect) {
      langSelect.value = Titan.getLang();
      langSelect.addEventListener('change', () => Titan.setLang(langSelect.value));
    }

    // Theme switcher
    const themeSelect = document.getElementById('theme-select');
    if (themeSelect) {
      themeSelect.value = localStorage.getItem(STORAGE_THEME) || 'auto';
      themeSelect.addEventListener('change', () => setTheme(themeSelect.value));
    }

    // Logout button — also wipes the remember-me blob so auto-login doesn't
    // immediately log the user back in.
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
      logoutBtn.addEventListener('click', (e) => {
        e.preventDefault();
        if (window.Titan && Titan.sounds) Titan.sounds.play('logout');
        saveSession(null);
        try { localStorage.removeItem('titan.remember'); } catch (er) {}
        // Tiny delay so the bye sound has a chance to start before navigation
        setTimeout(() => { location.href = 'index.html'; }, 120);
      });
    }
  }

  function init() {
    applyTheme();
    Titan.applyTranslations();
    setupHeader();
    updateAuthNav();
    window.addEventListener('titan:lang-changed', () => {
      // Re-apply current page hook if defined
      if (typeof window.onLangChanged === 'function') window.onLangChanged();
    });
    window.addEventListener('titan:session-changed', updateAuthNav);
  }

  window.Titan = window.Titan || {};
  window.Titan.getToken = getToken;
  window.Titan.getUser = getUser;
  window.Titan.saveSession = saveSession;
  window.Titan.announce = announce;
  window.Titan.setTheme = setTheme;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
