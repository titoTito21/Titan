// Titan-Net repository browser
//
// Every package is a card: what it is, its rating, and underneath what
// can be done with it - download it, read and write reviews, and for
// whoever shared it (or a moderator) update it in place or delete it.
// Reviews and the update form are <dialog>s, so the browser owns the
// focus trap and Escape, and the focus goes back to the button that
// opened them (ui.openDialog does that half).
(function () {
  'use strict';
  const t = Titan.t;
  const ui = Titan.ui;

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

  function ratingText(app) {
    if (!app.rating_count) return t('repo.no_rating');
    return t('repo.rating', app.rating_average, app.rating_count);
  }

  function dateText(iso) {
    if (!iso) return '';
    return String(iso).replace('T', ' ').slice(0, 16);
  }

  // The user, as far as this tab knows. Who may manage a package is
  // decided again by the server on every call; this only decides what is
  // OFFERED, so a moderator sees Update and Delete on every card and
  // everybody else on their own.
  function currentUser() {
    return (Titan.getUser && Titan.getUser()) || null;
  }
  function isStaff(user) {
    if (!user) return false;
    const role = user.role || (user.is_admin ? 'admin' : 'user');
    return role === 'moderator' || role === 'developer' || role === 'admin';
  }
  // Only the author updates a package; the author and the moderators may
  // delete one. The server decides again on every call.
  function isAuthor(app) {
    const user = currentUser();
    if (!user) return false;
    const author = app.uploader_username || app.author_username;
    return !!author && author === user.username;
  }
  function mayManage(app) {
    const user = currentUser();
    if (!user) return false;
    if (isStaff(user)) return true;
    return isAuthor(app);
  }

  function actionButton(label, ariaLabel, onClick, cls) {
    return ui.el('button', {
      type: 'button', class: cls || 'btn-secondary', 'aria-label': ariaLabel, onclick: onClick,
    }, [label]);
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
      parts.push(ratingText(app));
      if (app.updated_at) parts.push(t('repo.updated', dateText(app.updated_at)));
      meta.textContent = parts.join(' · ');
      article.appendChild(meta);

      // An update waiting for review is news for whoever shared the
      // package and for the moderators; to everybody else the package is
      // simply the version that is listed.
      if (app.pending_update && mayManage(app)) {
        article.appendChild(ui.el('p', { class: 'muted', text: t('repo.pending_update', app.update_version || '?') }));
      }

      const desc = document.createElement('p');
      desc.textContent = app.description || '';
      article.appendChild(desc);

      const actions = ui.el('div', { class: 'flex card-actions' });

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
      actions.appendChild(dl);

      actions.appendChild(actionButton(t('repo.reviews'), t('repo.reviews_label', app.name), function () {
        openReviews(app);
      }));

      if (isAuthor(app)) {
        actions.appendChild(actionButton(t('repo.update'), t('repo.update_label', app.name), function () {
          openUpdate(app);
        }));
      }
      if (mayManage(app)) {
        actions.appendChild(actionButton(t('repo.delete'), t('repo.delete_label', app.name), async function () {
          const yes = await ui.confirmDialog(t('repo.delete_confirm', app.name), { danger: true });
          if (!yes) return;
          try {
            await Titan.API.deleteApp(app.id);
            ui.announce(t('repo.deleted', app.name));
            load();
          } catch (err) {
            ui.announce((err && err.message) || t('err.generic'), 'error');
          }
        }, 'btn-danger'));
      }

      article.appendChild(actions);
      li.appendChild(article);
      frag.appendChild(li);
    });
    $results.appendChild(frag);
  }

  // ---------- Reviews and ratings ----------
  // One dialog: the summary, every review, and the form to add one. The
  // form is ALWAYS there: hidden while this user could not rate - their
  // own package, or one they had rated already - it was, to somebody who
  // cannot see the page, a form that did not exist, and on a small server
  // where every package is one's own "where do I write a review" had no
  // answer. So it stays, says WHY a rating would be refused (the server
  // names the reason in `review_refusal`), and refuses in those words
  // rather than sending what the server has already said no to.
  function reviewRefusalText(reason) {
    const known = { not_signed_in: 1, not_approved: 1, own_package: 1, already_reviewed: 1 };
    return t('repo.rate_refused.' + (known[reason] ? reason : 'unknown'));
  }

  function openReviews(app) {
    const base = ui.uid('reviews');
    const title = ui.el('h2', { id: base + '-title', text: t('repo.reviews_label', app.name) });
    const summary = ui.el('p', { id: base + '-summary', class: 'meta', text: t('common.loading') });
    const list = ui.el('ul', { class: 'list-plain', 'aria-labelledby': base + '-title' });
    const formHost = ui.el('div');
    const alert = ui.el('div', { class: 'alert', hidden: true });
    const close = ui.el('button', { type: 'button', text: t('common.close') });
    const dialog = ui.el('dialog', {
      class: 'titan-dialog wide', 'aria-labelledby': base + '-title',
    }, [title, summary, alert, list, formHost, ui.el('div', { class: 'flex dialog-actions' }, [close])]);
    document.body.appendChild(dialog);

    function finish() {
      ui.closeDialog(dialog);
      setTimeout(function () { if (dialog.isConnected) dialog.remove(); }, 400);
    }
    close.addEventListener('click', finish);
    dialog.addEventListener('cancel', function (e) { e.preventDefault(); finish(); });

    async function fill() {
      ui.setBusy(list, true);
      try {
        const data = await Titan.API.appReviews(app.id);
        app.rating_average = data.rating_average;
        app.rating_count = data.rating_count;
        summary.textContent = ratingText(app)
          + (data.my_review ? ' · ' + t('repo.your_rating', data.my_review.rating) : '');
        ui.clear(list);
        const reviews = data.reviews || [];
        if (!reviews.length) {
          list.appendChild(ui.el('li', { text: t('repo.reviews_empty') }));
        }
        const user = currentUser();
        reviews.forEach(function (review) {
          const head = [t('repo.review_row', review.username, review.rating)];
          // About a release since replaced: the words still stand, but for
          // the version they were written about.
          if (review.current === 0 && review.version) head.push(t('repo.review_version', review.version));
          const when = dateText(review.created_at);
          if (when) head.push(when);
          if (!(review.review || '').trim()) head.push(t('repo.review_rating_only'));
          const item = ui.el('li', {}, [
            ui.el('p', { class: 'meta' }, [ui.el('strong', { text: head.join(', ') })]),
          ]);
          if ((review.review || '').trim()) {
            item.appendChild(ui.el('p', { class: 'clamp', text: review.review }));
          }
          const own = user && review.username === user.username;
          if (own || isStaff(user)) {
            item.appendChild(actionButton(t('repo.review_delete'),
              t('repo.review_delete_label', review.username), async function () {
                const yes = await ui.confirmDialog(t('repo.review_delete_confirm', review.username), { danger: true });
                if (!yes) return;
                try {
                  await Titan.API.deleteAppReview(review.id);
                  ui.announce(t('repo.review_deleted'));
                  fill();
                } catch (err) {
                  ui.setAlert(alert, (err && err.message) || t('err.generic'), 'error');
                }
              }, 'btn-danger'));
          }
          list.appendChild(item);
        });
        ui.clear(formHost);
        formHost.appendChild(rateForm(data));
      } catch (err) {
        summary.textContent = '';
        ui.setAlert(alert, (err && err.message) || t('err.generic'), 'error');
      } finally {
        ui.setBusy(list, false);
      }
    }

    // The rating is a slider, 1 to 5: one number on a short scale, moved
    // with the arrows. `aria-valuetext` carries the WORD for the number
    // ("3 - Average"), so a reader says that rather than a bare digit, and
    // the <output> beside the slider shows the same word - silent, since
    // the reader already has it from the slider.
    function ratingSlider(id) {
      const output = ui.el('output', { for: id, 'aria-live': 'off', class: 'rating-word' });
      const slider = ui.el('input', {
        type: 'range', id: id, min: 1, max: 5, step: 1, value: 5, class: 'rating-slider',
        'aria-valuemin': 1, 'aria-valuemax': 5,
      });
      function show() {
        const word = t('repo.rate.' + slider.value);
        slider.setAttribute('aria-valuenow', slider.value);
        slider.setAttribute('aria-valuetext', word);
        output.textContent = word;
      }
      slider.addEventListener('input', show);
      show();
      return { slider: slider, output: output };
    }

    function rateForm(data) {
      const ratingId = base + '-rating';
      const reviewId = base + '-review';
      const rating = ratingSlider(ratingId);
      const textarea = ui.el('textarea', { id: reviewId, rows: 4, maxlength: 4000 });
      const send = ui.el('button', { type: 'submit', text: t('repo.rate_send') });
      const refused = data.can_review ? null : reviewRefusalText(data.review_refusal);
      const form = ui.el('form', { novalidate: true, 'aria-labelledby': base + '-rate-title' }, [
        ui.el('h3', { id: base + '-rate-title', text: t('repo.rate') }),
        refused ? ui.el('p', { class: 'alert alert-info', role: 'note', text: refused }) : null,
        ui.el('p', { class: 'help', text: t('repo.rate_once') + ' ' + t('repo.rate_once_per_release') }),
        ui.el('div', { class: 'field' }, [
          ui.el('label', { for: ratingId, text: t('repo.rate_rating') }), rating.slider, rating.output,
        ]),
        ui.el('div', { class: 'field' }, [
          ui.el('label', { for: reviewId, text: t('repo.rate_review') }), textarea,
        ]),
        ui.el('p', {}, [send]),
      ]);
      form.addEventListener('submit', async function (e) {
        e.preventDefault();
        if (refused) {
          ui.setAlert(alert, refused, 'error');
          return;
        }
        send.disabled = true;
        try {
          await Titan.API.addAppReview(app.id, parseInt(rating.slider.value, 10), textarea.value.trim());
          ui.announce(t('repo.rate_sent'));
          if (Titan.sounds) Titan.sounds.play('titannet_success');
          await fill();
          load();
        } catch (err) {
          ui.setAlert(alert, (err && err.message) || t('err.generic'), 'error');
        } finally {
          send.disabled = false;
        }
      });
      return form;
    }

    ui.openDialog(dialog, close);
    fill();
  }

  // ---------- Updating ----------
  // The same shape as the upload form with the current values filled in
  // and the file optional: a package is updated rather than deleted and
  // shared again, so it keeps its id, its downloads and its reviews.
  function openUpdate(app) {
    const base = ui.uid('update');
    const ids = { name: base + '-name', description: base + '-description', version: base + '-version', file: base + '-file' };
    const name = ui.el('input', { type: 'text', id: ids.name, required: true, maxlength: 120, value: app.name || '' });
    const description = ui.el('textarea', { id: ids.description, rows: 4, required: true });
    description.value = app.description || '';
    const version = ui.el('input', { type: 'text', id: ids.version, required: true, maxlength: 32, value: app.version || '' });
    const file = ui.el('input', { type: 'file', id: ids.file, accept: '.tca,.tcd,.zip,.7z,.tcepackage', 'aria-describedby': ids.file + '-help' });
    const submit = ui.el('button', { type: 'submit', text: t('repo.update_submit') });
    const cancel = ui.el('button', { type: 'button', text: t('common.cancel') });
    const alert = ui.el('div', { class: 'alert', hidden: true });
    const progress = ui.el('progress', { id: base + '-progress', max: 100, value: 0 });
    const progressText = ui.el('p', { role: 'status', 'aria-live': 'polite' });
    const progressWrap = ui.el('div', { hidden: true }, [
      ui.el('label', { for: base + '-progress', text: t('repo.up.progress') }), progress, progressText,
    ]);
    const form = ui.el('form', { novalidate: true }, [
      ui.el('p', { text: t('repo.update_lead') }),
      alert,
      ui.el('div', { class: 'field' }, [ui.el('label', { for: ids.name, text: t('repo.up.name') }), name]),
      ui.el('div', { class: 'field' }, [ui.el('label', { for: ids.description, text: t('repo.up.description') }), description]),
      ui.el('div', { class: 'field' }, [ui.el('label', { for: ids.version, text: t('repo.up.version') }), version]),
      ui.el('div', { class: 'field' }, [
        ui.el('label', { for: ids.file, text: t('repo.update_file') }), file,
        ui.el('p', { class: 'help', id: ids.file + '-help', text: t('repo.up.file_help') }),
      ]),
      progressWrap,
      ui.el('div', { class: 'flex dialog-actions' }, [submit, cancel]),
    ]);
    const dialog = ui.el('dialog', {
      class: 'titan-dialog wide', 'aria-labelledby': base + '-title',
    }, [ui.el('h2', { id: base + '-title', text: t('repo.update_heading', app.name) }), form]);
    document.body.appendChild(dialog);

    function finish() {
      ui.closeDialog(dialog);
      setTimeout(function () { if (dialog.isConnected) dialog.remove(); }, 400);
    }
    cancel.addEventListener('click', finish);
    dialog.addEventListener('cancel', function (e) { e.preventDefault(); finish(); });

    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      let bad = null;
      [name, description, version].forEach(function (input) {
        const value = input.value.trim();
        ui.fieldError(input.id, value ? '' : t('err.required'));
        if (!value && !bad) bad = input;
      });
      if (bad) { bad.focus(); return; }

      const metadata = {
        name: name.value.trim(),
        description: description.value.trim(),
        version: version.value.trim(),
      };
      const chosen = file.files[0] || null;
      submit.disabled = true;
      ui.setAlert(alert, '');
      if (chosen) {
        progressWrap.hidden = false;
        progress.value = 0;
        progressText.textContent = t('repo.up.starting');
      }
      let announced = -1;
      try {
        const result = await Titan.API.updatePackage(app.id, chosen, metadata, function (loaded, total) {
          const percent = Math.round((loaded / total) * 100);
          progress.value = percent;
          const tenth = Math.floor(percent / 10);
          if (tenth !== announced) {
            announced = tenth;
            progressText.textContent = t('repo.up.percent', percent);
          }
        });
        progressWrap.hidden = true;
        progressText.textContent = '';
        ui.announce(result.pending_update ? t('repo.update_staged') : t('repo.update_saved'));
        if (Titan.sounds) Titan.sounds.play('titannet_success');
        finish();
        load();
      } catch (err) {
        progressWrap.hidden = true;
        progressText.textContent = '';
        ui.setAlert(alert, (err && err.message) || t('err.generic'), 'error');
      } finally {
        submit.disabled = false;
      }
    });

    ui.openDialog(dialog, name);
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
  // Signing in or out changes which buttons a card offers.
  window.addEventListener('titan:session-changed', load);

  // ---------- Uploading ----------
  // The file is streamed as multipart rather than turned into a base64
  // string first: a package can be hundreds of megabytes, and reading one
  // into memory to encode it is how a browser tab dies.
  const $upload = document.getElementById('repo-upload-form');
  if ($upload) {
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
