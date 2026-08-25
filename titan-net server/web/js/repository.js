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
      // Only hint the filename here when we know the real extension; otherwise
      // an empty `download` attribute lets the server's Content-Disposition
      // (which appends the original extension) decide the saved filename.
      const ext = ((app.file_name || app.filename || '').match(/\.[A-Za-z0-9]+$/) || [''])[0];
      if (ext) {
        const safeName = (app.name || 'download').replace(/[\\/:*?"<>|\r\n]+/g, '_').trim();
        dl.setAttribute('download', safeName.toLowerCase().endsWith(ext.toLowerCase())
          ? safeName
          : safeName + ext);
      } else {
        dl.setAttribute('download', '');
      }
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

  // ---------- Uploading ----------
  // The file is streamed as multipart rather than turned into a base64
  // string first: a package can be hundreds of megabytes, and reading one
  // into memory to encode it is how a browser tab dies.
  const $upload = document.getElementById('repo-upload-form');
  if ($upload) {
    const ui = Titan.ui;
    const $alert = document.getElementById('repo-upload-alert');
    const $progressWrap = document.getElementById('up-progress-wrap');
    const $progress = document.getElementById('up-progress');
    const $progressText = document.getElementById('up-progress-text');
    const $submit = document.getElementById('up-submit');

    function showUpload() {
      const section = document.getElementById('repo-upload-section');
      if (section) section.hidden = !Titan.getUser();
    }
    showUpload();
    window.addEventListener('titan:session-changed', showUpload);

    $upload.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fields = {
        name: document.getElementById('up-name'),
        description: document.getElementById('up-description'),
        version: document.getElementById('up-version'),
      };
      const file = document.getElementById('up-file').files[0];
      let bad = null;
      Object.keys(fields).forEach((key) => {
        const value = fields[key].value.trim();
        ui.fieldError(fields[key].id, value ? '' : t('err.required'));
        if (!value && !bad) bad = fields[key];
      });
      ui.fieldError('up-file', file ? '' : t('err.required'));
      if (!file && !bad) bad = document.getElementById('up-file');
      if (bad) { bad.focus(); return; }

      const metadata = {
        name: fields.name.value.trim(),
        description: fields.description.value.trim(),
        category: document.getElementById('up-category').value,
        version: fields.version.value.trim(),
      };

      $submit.disabled = true;
      ui.setAlert($alert, '');
      $progressWrap.hidden = false;
      $progress.value = 0;
      $progressText.textContent = t('repo.up.starting');

      let announced = -1;
      try {
        const result = await Titan.API.uploadPackage(file, metadata, (loaded, total) => {
          const percent = Math.round((loaded / total) * 100);
          $progress.value = percent;
          // Announcing every percent would talk over everything else, so
          // the reader is told every tenth.
          const tenth = Math.floor(percent / 10);
          if (tenth !== announced) {
            announced = tenth;
            $progressText.textContent = t('repo.up.percent', percent);
          }
        });
        $progress.value = 100;
        $progressText.textContent = '';
        $progressWrap.hidden = true;
        ui.setAlert($alert, result.message || t('repo.up.sent', metadata.name), 'success');
        if (Titan.sounds) Titan.sounds.play('titannet_success');
        $upload.reset();
        document.getElementById('up-version').value = '1.0';
      } catch (err) {
        $progressWrap.hidden = true;
        $progressText.textContent = '';
        ui.setAlert($alert, (err && err.message) || t('err.generic'), 'error');
      } finally {
        $submit.disabled = false;
      }
    });
  }

  window.onLangChanged = load;
  document.addEventListener('DOMContentLoaded', load);
  if (document.readyState !== 'loading') load();
})();
