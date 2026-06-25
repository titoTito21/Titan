// Titan-Net extensions (moderator add-ons + two-person approval)
(function () {
  'use strict';
  const t = Titan.t;
  const API = Titan.API;

  const $status = document.getElementById('ext-status');
  const $pendingH = document.getElementById('ext-pending-h');
  const $pending = document.getElementById('ext-pending');
  const $active = document.getElementById('ext-active');
  const $newBtn = document.getElementById('new-ext-btn');

  const $newDialog = document.getElementById('new-ext-dialog');
  const $newForm = document.getElementById('new-ext-form');
  const $neCancel = document.getElementById('ne-cancel');

  const $codeDialog = document.getElementById('ext-code-dialog');
  const $codePre = document.getElementById('ext-code-pre');
  document.getElementById('ec-close').addEventListener('click', () => dialogClose($codeDialog));

  let isStaff = false;

  function dialogOpen(dlg, focusEl) {
    if (typeof dlg.showModal === 'function') dlg.showModal();
    else dlg.setAttribute('open', '');
    if (focusEl) focusEl.focus();
  }
  function dialogClose(dlg) { if (dlg.close) dlg.close(); else dlg.removeAttribute('open'); }

  function extCard(ext, pending) {
    const li = document.createElement('li');
    const card = document.createElement('article');
    card.className = 'card';
    card.setAttribute('aria-labelledby', 'ext-' + ext.id);
    const h3 = document.createElement('h3');
    h3.id = 'ext-' + ext.id;
    h3.textContent = ext.name;
    card.appendChild(h3);
    const meta = document.createElement('p');
    meta.className = 'meta';
    const parts = [];
    if (ext.author_username) parts.push(t('ext.by', ext.author_username));
    if (ext.version) parts.push(t('ext.version', ext.version));
    meta.textContent = parts.join(' · ');
    card.appendChild(meta);
    if (ext.description) {
      const d = document.createElement('p');
      d.textContent = ext.description;
      card.appendChild(d);
    }
    const actions = document.createElement('p');
    const viewBtn = document.createElement('button');
    viewBtn.className = 'btn btn-secondary';
    viewBtn.textContent = t('ext.view_code');
    viewBtn.addEventListener('click', () => viewCode(ext.id));
    actions.appendChild(viewBtn);
    if (pending && isStaff) {
      const approve = document.createElement('button');
      approve.textContent = t('ext.approve');
      approve.style.marginLeft = '.5rem';
      approve.addEventListener('click', () => review(ext.id, true));
      actions.appendChild(approve);
      const reject = document.createElement('button');
      reject.className = 'btn btn-secondary';
      reject.textContent = t('ext.reject');
      reject.style.marginLeft = '.5rem';
      reject.addEventListener('click', () => review(ext.id, false));
      actions.appendChild(reject);
    }
    card.appendChild(actions);
    li.appendChild(card);
    return li;
  }

  async function viewCode(extId) {
    try {
      const resp = await API.getExtension(extId);
      if (!resp.success) { Titan.announce(resp.error || t('err.generic')); return; }
      $codePre.textContent = (resp.extension && resp.extension.client_code) || '';
      dialogOpen($codeDialog);
    } catch (e) { Titan.announce(e.message || t('err.generic')); }
  }

  async function review(extId, approve) {
    try {
      const resp = approve ? await API.approveExtension(extId) : await API.rejectExtension(extId);
      if (resp.success) {
        Titan.announce(approve ? t('ext.approved') : t('ext.rejected'));
        load();
      } else { Titan.announce(resp.error || t('err.generic')); }
    } catch (e) { Titan.announce(e.message || t('err.generic')); }
  }

  async function load() {
    $status.textContent = t('ext.loading');
    $pending.innerHTML = '';
    $active.innerHTML = '';
    // Is the current user staff? getRole returns developer/moderator/user.
    isStaff = false;
    if (Titan.getUser()) {
      try {
        const role = await API.getRole();
        const r = (role && (role.role || role)) || '';
        isStaff = (r === 'moderator' || r === 'developer');
      } catch (e) { /* ignore */ }
    }
    try {
      const data = await API.listExtensions();
      const exts = data.extensions || [];
      const pending = exts.filter((e) => e.status === 'pending');
      const active = exts.filter((e) => e.status === 'active');
      $pendingH.hidden = !(isStaff && pending.length);
      pending.forEach((e) => { if (isStaff) $pending.appendChild(extCard(e, true)); });
      active.forEach((e) => $active.appendChild(extCard(e, false)));
      $status.textContent = (active.length || pending.length) ? '' : t('ext.empty');
    } catch (e) {
      $status.textContent = e.message || t('err.generic');
    }
  }

  if ($newBtn) {
    $newBtn.addEventListener('click', () => {
      if (!Titan.getUser()) { Titan.announce(t('err.login_first')); return; }
      dialogOpen($newDialog, document.getElementById('ne-name'));
    });
  }
  $neCancel.addEventListener('click', () => dialogClose($newDialog));
  $newForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('ne-name').value.trim();
    const slug = document.getElementById('ne-slug').value.trim();
    const code = document.getElementById('ne-code').value;
    const desc = document.getElementById('ne-desc').value.trim();
    if (!name || !slug || !code.trim()) return;
    try {
      const resp = await API.submitExtension(slug, name, code, desc);
      if (resp.success) {
        Titan.announce(t('ext.submitted'));
        dialogClose($newDialog);
        $newForm.reset();
        load();
      } else { Titan.announce(resp.error || t('err.generic')); }
    } catch (e) { Titan.announce(e.message || t('err.generic')); }
  });

  window.onLangChanged = load;
  document.addEventListener('DOMContentLoaded', load);
  if (document.readyState !== 'loading') load();
})();
