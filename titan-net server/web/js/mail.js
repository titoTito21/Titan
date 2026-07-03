// Titan-Net web Mail client — inbox/sent + read + compose.
(function () {
  'use strict';
  const t = Titan.t;
  const API = Titan.API;

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

  function dOpen(d) { if (d.showModal) d.showModal(); else d.setAttribute('open', ''); }
  function dClose(d) { if (d.close) d.close(); else d.removeAttribute('open'); }

  function folder() { return $folder.value === 'sent' ? 'sent' : 'inbox'; }

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
      meta.textContent = who + ' · ' + (m.received_at || '').slice(0, 16).replace('T', ' ');
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

  async function openMail(id) {
    try {
      const data = await API.getMail(id);
      if (!data || !data.success) { Titan.announce(t('err.generic')); return; }
      const m = data.message || {};
      document.getElementById('read-subject').textContent = m.subject || t('mail.no_subject');
      document.getElementById('read-meta').textContent =
        t('mail.from') + ': ' + (m.from_addr || '') + '  —  ' + t('mail.to') + ': ' + (m.to_addr || '');
      document.getElementById('read-body').textContent = m.body || '';
      const replyBtn = document.getElementById('read-reply');
      replyBtn.onclick = () => { dClose(readDialog); reply(m); };
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

  function reply(m) {
    let subject = m.subject || '';
    if (subject && subject.toLowerCase().indexOf('re:') !== 0) subject = 'Re: ' + subject;
    const quoted = '\n\n> ' + (m.body || '').replace(/\n/g, '\n> ');
    openCompose(m.from_addr || '', subject, quoted);
  }

  const composeAlert = document.getElementById('compose-alert');
  function openCompose(to, subject, body) {
    composeAlert.hidden = true;
    document.getElementById('compose-to').value = to || '';
    document.getElementById('compose-subject').value = subject || '';
    document.getElementById('compose-body').value = body || '';
    dOpen(composeDialog);
  }

  document.getElementById('mail-compose').addEventListener('click', () => openCompose('', '', ''));
  document.getElementById('compose-cancel').addEventListener('click', () => dClose(composeDialog));
  document.getElementById('read-close').addEventListener('click', () => dClose(readDialog));
  $folder.addEventListener('change', load);

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
      const r = await API.sendMail(to, subject, body);
      if (r && r.success) { dClose(composeDialog); Titan.announce(t('mail.sent')); load(); }
      else { composeAlert.hidden = false; composeAlert.className = 'alert alert-error'; composeAlert.textContent = (r && r.error) || t('err.generic'); }
    } catch (err) {
      composeAlert.hidden = false; composeAlert.className = 'alert alert-error'; composeAlert.textContent = err.message || t('err.generic');
    }
    btn.disabled = false;
  });

  window.onLangChanged = load;
  load();
})();
