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

  // Replace just the HTTP token, keeping the rest of the session.
  //
  // The token is what every REST call carries, and it was written once at
  // login and never touched again - so a session stored before the server
  // minted signed tokens kept presenting the old base64("id:username")
  // form for ever. The server now honours one of those only while its
  // owner also holds a live WebSocket session from the same address, and
  // the pages that are pure REST (Mail, Account) open no socket at all, so
  // every request came back "Authentication required" and the only cure
  // was logging out and in. session.js therefore calls this with the fresh
  // token from EVERY WebSocket login.
  function saveToken(token) {
    if (!token) return;
    const s = loadSession();
    if (!s || s.token === token) return;
    s.token = token;
    localStorage.setItem(STORAGE_TOKEN, JSON.stringify(s));
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

  // The navigation is one list, written once. Fifteen pages each carrying
  // their own copy is how a page ends up missing an entry — and a link a
  // keyboard user cannot reach from where they are is a page that does not
  // exist for them. The static markup in each file stays as the no-script
  // fallback; this replaces it when the scripts run.
  const NAV = [
    { href: 'index.html', key: 'nav.home' },
    { href: 'chat.html', key: 'nav.chat' },
    { href: 'repository.html', key: 'nav.repository' },
    // Forum and groups are one thing: every topic lives in a forum
    // inside a group (the flat forum was migrated into them long ago),
    // so two entries were two names for the same data - and the flat one
    // was the poorer half, with no idea which forum a topic was in. The
    // desktop client has always had exactly this: one "Forum" entry
    // opening the groups tree.
    { href: 'groups.html', key: 'nav.forum' },
    { href: 'mail.html', key: 'nav.mail', auth: 'in' },
    { href: 'feedback.html', key: 'nav.feedback' },
    { href: 'games.html', key: 'nav.games', auth: 'in' },
    { href: 'services.html', key: 'nav.services', auth: 'in' },
    { href: 'extensions.html', key: 'nav.extensions' },
    { href: 'moderation.html', key: 'nav.moderation', auth: 'in', staff: true },
    { href: 'settings.html', key: 'nav.settings' },
    { href: 'account.html', key: 'nav.account', auth: 'in' },
  ];

  function isStaff() {
    const user = getUser();
    if (!user) return false;
    const role = user.role || (user.is_admin ? 'admin' : 'user');
    return ['moderator', 'admin', 'developer', 'owner'].indexOf(role) !== -1;
  }

  function buildNav() {
    const nav = document.querySelector('.primary-nav ul');
    if (!nav) return;
    const user = getUser();
    const path = location.pathname.split('/').pop() || 'index.html';
    nav.textContent = '';
    NAV.forEach((entry) => {
      if (entry.auth === 'in' && !user) return;
      if (entry.auth === 'out' && user) return;
      if (entry.staff && !isStaff()) return;
      const li = document.createElement('li');
      const a = document.createElement('a');
      a.href = entry.href;
      a.textContent = Titan.t(entry.key);
      // aria-current tells a screen reader which entry is the page it is
      // already on, which is the only thing distinguishing it once the
      // colour is gone (WCAG 1.4.1, 2.4.8).
      if (entry.href === path) a.setAttribute('aria-current', 'page');
      li.appendChild(a);
      nav.appendChild(li);
    });
    if (!user) {
      ['login', 'register'].forEach((which) => {
        const li = document.createElement('li');
        const a = document.createElement('a');
        a.href = which + '.html';
        a.textContent = Titan.t('nav.' + which);
        if (a.href.split('/').pop() === path) a.setAttribute('aria-current', 'page');
        li.appendChild(a);
        nav.appendChild(li);
      });
    } else {
      const li = document.createElement('li');
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.id = 'logout-btn';
      btn.className = 'btn btn-secondary';
      btn.textContent = Titan.t('nav.logout');
      btn.addEventListener('click', doLogout);
      li.appendChild(btn);
      nav.appendChild(li);
    }
  }

  function doLogout(e) {
    if (e) e.preventDefault();
    if (window.Titan && Titan.sounds) Titan.sounds.play('logout');
    saveSession(null);
    try { localStorage.removeItem('titan.remember'); } catch (er) {}
    // The tab's live credentials go too, or the next page reconnects as
    // somebody who has just logged out.
    if (window.Titan && Titan.session) Titan.session.forget();
    try { sessionStorage.removeItem('titan.creds'); } catch (er) {}
    try { sessionStorage.removeItem('titan.once_login'); } catch (er) {}
    setTimeout(() => { location.href = 'index.html'; }, 120);
  }

  function setupHeader() {
    buildNav();
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
    // immediately log the user back in. buildNav() wires the one it makes;
    // this covers a page still carrying the static markup.
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn && !logoutBtn._titanBound) {
      logoutBtn._titanBound = true;
      logoutBtn.addEventListener('click', doLogout);
    }
  }

  function init() {
    applyTheme();
    Titan.applyTranslations();
    setupHeader();
    updateAuthNav();
    window.addEventListener('titan:lang-changed', () => {
      buildNav();
      updateAuthNav();
      // Re-apply current page hook if defined
      if (typeof window.onLangChanged === 'function') window.onLangChanged();
    });
    window.addEventListener('titan:session-changed', () => {
      buildNav();
      updateAuthNav();
    });
  }

  window.Titan = window.Titan || {};
  window.Titan.getToken = getToken;
  window.Titan.saveToken = saveToken;
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
