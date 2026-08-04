// Titan-Net web Mail client - inbox/sent, reading, composing.
//
// Reading matches the desktop client (src/network/mail_gui.py): an HTML message
// is shown as the page it is, inside a sandboxed frame that cannot fetch or run
// anything, with its links listed separately so the reader follows them
// deliberately; a Markdown or plain message is shown as text. Composing offers
// the same three formats and always sends a readable plain body with the
// formatted alternative beside it.
(function () {
  'use strict';
  const t = Titan.t;
  const API = Titan.API;
  const MF = Titan.MailFormat;

  const notLogged = document.getElementById('mail-not-logged-in');
  const app = document.getElementById('mail-app');
  if (!Titan.getUser()) { notLogged.hidden = false; return; }
  app.hidden = false;

  const $status = document.getElementById('mail-status');
  const $list = document.getElementById('mail-list');
  const $folder = document.getElementById('mail-folder');
  const $address = document.getElementById('mail-address');

  const readDialog = document.getElementById('read-dialog');
  const composeDialog = document.getElementById('compose-dialog');
  const $readBody = document.getElementById('read-body');
  const $readFrame = document.getElementById('read-frame');
  const $readFormat = document.getElementById('read-format');
  const $readLinksBox = document.getElementById('read-links-box');
  const $readLinks = document.getElementById('read-links');
  const $textToggle = document.getElementById('read-text-toggle');

  function dOpen(d) { if (d.showModal) d.showModal(); else d.setAttribute('open', ''); }
  function dClose(d) { if (d.close) d.close(); else d.removeAttribute('open'); }

  function folder() { return $folder.value === 'sent' ? 'sent' : 'inbox'; }

  function formatLabel(format) {
    if (format === 'html') return 'HTML';
    if (format === 'markdown') return 'Markdown';
    return t('mail.format_plain');
  }

  async function load() {
    $status.textContent = t('mail.loading');
    $list.innerHTML = '';
    try {
      const data = await API.mailbox(folder());
      if (!data || !data.success) { $status.textContent = t('err.generic'); return; }
      $address.textContent = t('mail.your_address').replace('{address}', data.address || '');
      render(data.messages || []);
    } catch (e) { $status.textContent = e.message || t('err.generic'); }
  }

  function render(messages) {
    $list.innerHTML = '';
    if (!messages.length) { $status.textContent = t('mail.empty'); return; }
    $status.textContent = '';
    const inbox = folder() === 'inbox';
    messages.forEach((m) => {
      const li = document.createElement('li');
      const card = document.createElement('article');
      card.className = 'card';
      const who = inbox ? (m.from_addr || '') : (m.to_addr || '');
      let subject = m.subject || t('mail.no_subject');
      if (inbox && !m.read) subject = '• ' + subject;
      const title = document.createElement('strong');
      title.textContent = subject;
      const meta = document.createElement('div');
      meta.className = 'muted';
      // The list carries content_type, so a row can say what kind of message it
      // is without the body being fetched.
      const format = MF.detect('', m.content_type || '', '');
      let metaText = who + ' · ' + (m.received_at || '').slice(0, 16).replace('T', ' ');
      if (format !== 'plain') metaText += ' · ' + formatLabel(format);
      meta.textContent = metaText;
      card.appendChild(title);
      card.appendChild(meta);
      const openBtn = document.createElement('button');
      openBtn.textContent = t('mail.read');
      openBtn.style.marginRight = '.5rem';
      openBtn.addEventListener('click', () => openMail(m.id));
      const delBtn = document.createElement('button');
      delBtn.className = 'btn btn-secondary';
      delBtn.textContent = t('mail.delete');
      delBtn.addEventListener('click', () => delMail(m.id));
      const actions = document.createElement('p');
      actions.appendChild(openBtn);
      actions.appendChild(delBtn);
      card.appendChild(actions);
      li.appendChild(card);
      $list.appendChild(li);
    });
  }

  // Show one body. `asText` forces the text view for an HTML message.
  function showBody(message, format, asText) {
    const html = message.body_html || message.body || '';
    const subject = message.subject || t('mail.no_subject');
    const isPage = format === 'html' && !asText;

    $readFrame.hidden = !isPage;
    $readBody.hidden = isPage;
    if (isPage) {
      // srcdoc + an empty sandbox attribute: no scripts, no forms, no
      // same-origin access. The content policy inside the document is what
      // stops remote images and fonts from ever being requested.
      $readFrame.srcdoc = MF.sealDocument(html, subject);
    } else {
      $readFrame.removeAttribute('srcdoc');
      $readBody.textContent = format === 'html'
        ? MF.htmlToText(html)
        : (message.body || '');
    }

    $textToggle.hidden = format !== 'html';
    $textToggle.textContent = asText ? t('mail.show_page') : t('mail.show_text');
    $textToggle.onclick = () => showBody(message, format, !asText);
  }

  function showLinks(message, format) {
    const links = MF.extractLinks(message.body || '', message.body_html || '', format);
    $readLinks.innerHTML = '';
    $readLinksBox.hidden = !links.length;
    links.forEach((link) => {
      const li = document.createElement('li');
      const anchor = document.createElement('a');
      anchor.href = link.url;
      anchor.target = '_blank';
      anchor.rel = 'noopener noreferrer nofollow';
      anchor.textContent = link.label === link.url
        ? link.url : (link.label + ' — ' + link.url);
      li.appendChild(anchor);
      $readLinks.appendChild(li);
    });
  }

  async function openMail(id) {
    try {
      const data = await API.getMail(id);
      if (!data || !data.success) { Titan.announce(t('err.generic')); return; }
      const m = data.message || {};
      const format = MF.detect(m.body || '', m.content_type || '', m.body_html || '');
      document.getElementById('read-subject').textContent = m.subject || t('mail.no_subject');
      document.getElementById('read-meta').textContent =
        t('mail.from') + ': ' + (m.from_addr || '') + '  —  ' + t('mail.to') + ': ' + (m.to_addr || '');
      $readFormat.textContent = t('mail.format') + ': ' + formatLabel(format);
      showBody(m, format, false);
      showLinks(m, format);
      const replyBtn = document.getElementById('read-reply');
      replyBtn.onclick = () => { dClose(readDialog); reply(m, format); };
      dOpen(readDialog);
      load(); // read marker clears
    } catch (e) { Titan.announce(e.message || t('err.generic')); }
  }

  async function delMail(id) {
    try {
      const r = await API.deleteMail(id);
      if (r && r.success) load();
    } catch (e) { Titan.announce(e.message || t('err.generic')); }
  }

  function reply(m, format) {
    let subject = m.subject || '';
    if (subject && subject.toLowerCase().indexOf('re:') !== 0) subject = 'Re: ' + subject;
    // Quote the readable text, never the markup.
    const text = format === 'html'
      ? MF.htmlToText(m.body_html || m.body || '')
      : (m.body || '');
    const quoted = '\n\n> ' + text.replace(/\n/g, '\n> ');
    // A quoted body is Markdown-shaped, and Markdown keeps it a quote for the
    // recipient too.
    openCompose(m.from_addr || '', subject, quoted, 'markdown');
  }

  const composeAlert = document.getElementById('compose-alert');
  const $composeFormat = document.getElementById('compose-format');
  const $composeHint = document.getElementById('compose-hint');

  function composeFormat() { return $composeFormat.value || 'plain'; }

  function updateHint() {
    $composeHint.textContent = t('mail.hint_' + composeFormat());
  }

  function openCompose(to, subject, body, format) {
    composeAlert.hidden = true;
    document.getElementById('compose-to').value = to || '';
    document.getElementById('compose-subject').value = subject || '';
    document.getElementById('compose-body').value = body || '';
    $composeFormat.value = format || localStorage.getItem('titan.mail.format') || 'plain';
    updateHint();
    dOpen(composeDialog);
  }

  document.getElementById('mail-compose').addEventListener('click', () => openCompose('', '', '', ''));
  document.getElementById('compose-cancel').addEventListener('click', () => dClose(composeDialog));
  document.getElementById('read-close').addEventListener('click', () => dClose(readDialog));
  $folder.addEventListener('change', load);
  $composeFormat.addEventListener('change', () => {
    localStorage.setItem('titan.mail.format', composeFormat());
    updateHint();
  });

  // Preview shows the message exactly as the recipient's client will render it.
  document.getElementById('compose-preview').addEventListener('click', () => {
    const body = document.getElementById('compose-body').value;
    if (!body.trim()) { Titan.announce(t('mail.nothing_to_preview')); return; }
    const outgoing = MF.buildOutgoing(body, composeFormat());
    dClose(composeDialog);
    const preview = {
      subject: document.getElementById('compose-subject').value.trim(),
      from_addr: t('mail.preview'),
      to_addr: document.getElementById('compose-to').value.trim(),
      body: outgoing.body,
      body_html: outgoing.body_html,
      content_type: outgoing.content_type
    };
    const format = MF.detect(preview.body, preview.content_type, preview.body_html);
    document.getElementById('read-subject').textContent =
      t('mail.preview') + ': ' + (preview.subject || t('mail.no_subject'));
    document.getElementById('read-meta').textContent =
      t('mail.to') + ': ' + (preview.to_addr || '');
    $readFormat.textContent = t('mail.format') + ': ' + formatLabel(format);
    showBody(preview, format, false);
    showLinks(preview, format);
    document.getElementById('read-reply').onclick = () => {
      dClose(readDialog);
      dOpen(composeDialog);
    };
    dOpen(readDialog);
  });

  document.getElementById('compose-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const to = document.getElementById('compose-to').value.trim();
    const subject = document.getElementById('compose-subject').value.trim();
    const body = document.getElementById('compose-body').value;
    if (!to) {
      composeAlert.hidden = false; composeAlert.className = 'alert alert-error';
      composeAlert.textContent = t('err.required'); return;
    }
    const btn = document.getElementById('compose-send');
    btn.disabled = true;
    try {
      const outgoing = MF.buildOutgoing(body, composeFormat());
      const r = await API.sendMail(to, subject, outgoing.body, outgoing.body_html,
                                   outgoing.content_type);
      if (r && r.success) { dClose(composeDialog); Titan.announce(t('mail.sent')); load(); }
      else { composeAlert.hidden = false; composeAlert.className = 'alert alert-error'; composeAlert.textContent = (r && r.error) || t('err.generic'); }
    } catch (err) {
      composeAlert.hidden = false; composeAlert.className = 'alert alert-error'; composeAlert.textContent = err.message || t('err.generic');
    }
    btn.disabled = false;
  });

  window.onLangChanged = function () { updateHint(); load(); };
  load();
})();
