// Titan-Net repository browser
(function () {
  'use strict';
  const t = Titan.t;

  const $q = document.getElementById('repo-q');
  const $cat = document.getElementById('repo-cat');
  const $status = document.getElementById('repo-status');
  const $results = document.getElementById('repo-results');
  const $form = document.getElementById('repo-search');

  function formatBytes(n) {
    if (!n || isNaN(n)) return '';
    const u = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return n.toFixed(n < 10 ? 1 : 0) + ' ' + u[i];
  }

  function renderApps(apps) {
    $results.innerHTML = '';
    if (!apps || apps.length === 0) {
      $status.textContent = t('repo.empty');
      return;
    }
    $status.textContent = '';
    const frag = document.createDocumentFragment();
    apps.forEach((app) => {
      const li = document.createElement('li');
      const article = document.createElement('article');
      article.className = 'card';
      article.setAttribute('aria-labelledby', 'app-' + app.id);

      const h3 = document.createElement('h3');
      h3.id = 'app-' + app.id;
      h3.textContent = app.name;
      article.appendChild(h3);

      const meta = document.createElement('p');
      meta.className = 'meta';
      const parts = [];
      if (app.uploader_username || app.author_username) {
        parts.push(t('repo.by', app.uploader_username || app.author_username));
      }
      if (app.version) parts.push(t('repo.version', app.version));
      if (app.downloads != null) parts.push(t('repo.downloads', app.downloads));
      if (app.file_size) parts.push(formatBytes(app.file_size));
      meta.textContent = parts.join(' · ');
      article.appendChild(meta);

      const desc = document.createElement('p');
      desc.textContent = app.description || '';
      article.appendChild(desc);

      const dl = document.createElement('a');
      dl.className = 'btn';
      dl.href = Titan.API.appDownloadUrl(app.id);
      dl.setAttribute('download', '');
      dl.textContent = t('repo.download');
      dl.setAttribute('aria-label', t('repo.download') + ' — ' + app.name);
      article.appendChild(dl);

      li.appendChild(article);
      frag.appendChild(li);
    });
    $results.appendChild(frag);
  }

  async function load() {
    $status.textContent = t('repo.loading');
    $results.innerHTML = '';
    const query = ($q.value || '').trim();
    const cat = $cat.value || '';
    try {
      let data;
      if (query) data = await Titan.API.searchApps(query, cat || null);
      else data = await Titan.API.listApps({ status: 'approved', category: cat || null, limit: 200 });
      renderApps(data.apps || []);
    } catch (e) {
      $status.textContent = e.message || t('err.generic');
    }
  }

  $form.addEventListener('submit', (e) => { e.preventDefault(); load(); });
  $cat.addEventListener('change', load);
  window.onLangChanged = load;
  document.addEventListener('DOMContentLoaded', load);
  if (document.readyState !== 'loading') load();
})();
