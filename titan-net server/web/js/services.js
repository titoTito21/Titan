// Titan-Net web — opening the server's own screens and services.
//
// A `dialog` screen is a form, shown in a modal. A `view` screen is a
// SERVICE: a title, an optional menu bar, tabs, a status line, a list the
// user moves through, and buttons. Views nest, so a service is a tree of
// them and the back stack is what makes Escape mean "up one level" rather
// than "throw the whole thing away".
//
// The server keeps its own copy of that stack and validates every action
// against it, so this side is only ever drawing.
(function () {
  'use strict';

  const t = Titan.t;
  const ui = Titan.ui;
  const rui = Titan.remoteUI;

  const $alert = document.getElementById('svc-alert');
  const $index = document.getElementById('svc-index');
  const $indexList = document.getElementById('svc-index-list');
  const $indexStatus = document.getElementById('svc-index-status');
  const $screen = document.getElementById('svc-screen');
  const $trail = document.getElementById('svc-trail');
  const $heading = document.getElementById('svc-heading');
  const $description = document.getElementById('svc-description');
  const $menus = document.getElementById('svc-menus');
  const $status = document.getElementById('svc-status');
  const $tabs = document.getElementById('svc-tabs');
  const $tabsLabel = document.getElementById('svc-tabs-label');
  const $fields = document.getElementById('svc-fields');
  const $rows = document.getElementById('svc-rows');
  const $rowsHeading = document.getElementById('svc-rows-heading');
  const $empty = document.getElementById('svc-empty');
  const $buttons = document.getElementById('svc-buttons');
  const $back = document.getElementById('svc-back');

  const $dialog = document.getElementById('svc-dialog');
  const $dialogTitle = document.getElementById('svc-dialog-title');
  const $dialogDescription = document.getElementById('svc-dialog-description');
  const $dialogFields = document.getElementById('svc-dialog-fields');
  const $dialogButtons = document.getElementById('svc-dialog-buttons');
  const $dialogMessage = document.getElementById('svc-dialog-message');
  const $dialogForm = document.getElementById('svc-dialog-form');

  let ws = null;
  let screens = [];
  let slug = null;
  let stack = [];          // the views the user has drilled through
  let form = null;         // the field controller of the view on screen
  let dialogForm = null;   // the field controller of the modal, when open
  let dialogSlug = null;
  let refreshTimer = null;

  const user = Titan.session.requireLogin();
  if (!user) return;

  function current() { return stack.length ? stack[stack.length - 1] : null; }

  function fail(err) {
    ui.setAlert($alert, (err && err.message) || t('err.generic'), 'error');
  }

  // ---------- The index of everything on offer ----------

  async function loadIndex() {
    $indexStatus.textContent = t('common.loading');
    try {
      const resp = await ws.listRemoteScreens();
      if (!resp.success) throw new Error(resp.error);
      screens = (resp.screens || []).filter(function (s) { return s.in_menu !== 0; });
      renderIndex();
      ui.setAlert($alert, '');
    } catch (err) {
      $indexStatus.textContent = '';
      fail(err);
    }
  }

  function renderIndex() {
    ui.clear($indexList);
    if (!screens.length) {
      $indexStatus.textContent = t('svc.none');
      return;
    }
    $indexStatus.textContent = t('svc.count', screens.length);
    screens.forEach(function (entry) {
      const titleId = 'svc-entry-' + entry.slug.replace(/[^\w-]/g, '_');
      const open = ui.el('button', {
        type: 'button', class: 'link-button', text: entry.title,
        onclick: function () { openScreen(entry.slug); },
      });
      $indexList.appendChild(ui.el('li', {}, [
        ui.el('article', { class: 'card', 'aria-labelledby': titleId }, [
          ui.el('h2', { id: titleId }, [open]),
          ui.el('p', { class: 'meta', text: t('svc.provided_by', entry.handler || 'store') }),
        ]),
      ]));
    });
  }

  // ---------- Opening ----------

  async function openScreen(wanted) {
    try {
      ui.setAlert($alert, '');
      const resp = await ws.openRemoteScreen(wanted);
      if (!resp.success) throw new Error(resp.error);
      slug = wanted;
      stack = [];
      applyResult(resp.result || {}, { opening: true });
    } catch (err) {
      fail(err);
    }
  }

  // ---------- Drawing a view ----------

  function showIndex() {
    stopAutoRefresh();
    slug = null;
    stack = [];
    $screen.hidden = true;
    $index.hidden = false;
    ui.focusHeading($index.querySelector('h1'));
  }

  function renderTrail() {
    ui.clear($trail);
    stack.forEach(function (view, index) {
      const li = document.createElement('li');
      if (index === stack.length - 1) {
        li.textContent = view.title;
        li.setAttribute('aria-current', 'page');
      } else {
        li.appendChild(ui.el('button', {
          type: 'button', class: 'link-button', text: view.title,
          'aria-label': t('svc.go_back_to', view.title),
          onclick: function () { goBackTo(index); },
        }));
      }
      $trail.appendChild(li);
    });
  }

  function renderMenus(view) {
    ui.clear($menus);
    const menus = view.menus || [];
    $menus.hidden = !menus.length;
    if (!menus.length) return;
    menus.forEach(function (menu) {
      const list = ui.el('ul', { class: 'menu-list' });
      (menu.items || []).forEach(function (item) {
        if (item.separator) {
          // A real separator, said as one, not thirteen dashes read aloud.
          list.appendChild(ui.el('li', { role: 'separator', 'aria-label': t('svc.separator') }));
          return;
        }
        const btn = ui.el('button', { type: 'button', class: 'btn-secondary', text: item.label });
        btn.addEventListener('click', function () {
          if (item.confirm) {
            ui.confirmDialog(item.confirm, { title: item.label }).then(function (yes) {
              if (yes) fireMenuItem(item);
            });
            return;
          }
          fireMenuItem(item);
        });
        list.appendChild(ui.el('li', {}, [btn]));
      });
      // <details>/<summary> is the platform's own disclosure: it announces
      // "collapsed"/"expanded" from the element itself, and needs neither a
      // roving tabindex nor a word written into the label.
      $menus.appendChild(ui.el('details', { class: 'menu' }, [
        ui.el('summary', { text: menu.label }),
        list,
      ]));
    });
  }

  function rowLabel(row) {
    return row.sublabel ? row.label + ', ' + row.sublabel : row.label;
  }

  function renderRows(view, keepPosition) {
    const focusedId = keepPosition && document.activeElement
      ? document.activeElement.dataset.rowId : null;
    ui.clear($rows);
    const rows = view.items || [];
    $rowsHeading.hidden = !rows.length && !view.tabs;
    $rows.hidden = !rows.length;
    $empty.hidden = !!rows.length;
    if (!rows.length) {
      $empty.textContent = view.empty || t('common.empty');
      return;
    }
    $rowsHeading.textContent = t('svc.rows_count', rows.length);
    rows.forEach(function (row) {
      const btn = ui.el('button', {
        type: 'button',
        class: 'row-button',
        dataset: { rowId: row.id },
      }, [
        ui.el('span', { class: 'row-label', text: row.label }),
        row.sublabel ? ui.el('span', { class: 'row-sublabel', text: row.sublabel }) : null,
      ]);
      // Both halves are in the accessible name, so a reader says the detail
      // the row exists to carry rather than only its title.
      btn.setAttribute('aria-label', rowLabel(row));
      btn.addEventListener('click', function () { fireRow(row); });
      $rows.appendChild(ui.el('li', {}, [btn]));
    });
    if (focusedId) {
      const again = $rows.querySelector('[data-row-id="' + focusedId.replace(/"/g, '\\"') + '"]');
      if (again) { try { again.focus(); } catch (e) {} }
    }
  }

  function renderTabs(view) {
    const list = view.tabs || [];
    $tabs.hidden = !list.length;
    if (!list.length) { ui.clear($tabs); return; }
    const bar = ui.tabs($tabs, list.map(function (tab) {
      return { id: tab.id, label: tab.label, panel: 'svc-rows' };
    }), function (entry) {
      if (view.active_tab === entry.id) return;
      view.active_tab = entry.id;
      fire('tab', Object.assign(values(), { tab: entry.id }), 'action', true);
    });
    if (view.active_tab) bar.select(view.active_tab);
  }

  function values() {
    return form ? form.values() : {};
  }

  function renderView(view, keepPosition) {
    $index.hidden = true;
    $screen.hidden = false;
    $heading.textContent = view.title;
    document.title = view.title + ' — Titan-Net';
    $description.textContent = view.description || '';
    $description.hidden = !view.description;
    $status.textContent = view.status || '';
    $back.disabled = stack.length <= 1;

    renderTrail();
    renderMenus(view);
    renderTabs(view);

    form = Titan.remoteUI.renderFields($fields, view.fields || [], 'svc');
    renderRows(view, keepPosition);

    Titan.remoteUI.renderButtons($buttons, view.buttons || [], onViewButton);

    startAutoRefresh(view);
  }

  // ---------- Drawing a form screen ----------

  function renderDialog(view, forSlug) {
    dialogSlug = forSlug || slug;
    $dialogTitle.textContent = view.title;
    $dialogDescription.textContent = view.description || '';
    $dialogDescription.hidden = !view.description;
    $dialogMessage.textContent = '';
    dialogForm = Titan.remoteUI.renderFields($dialogFields, view.fields || [], 'svcd');
    Titan.remoteUI.renderButtons($dialogButtons, view.buttons || [], function (spec) {
      onDialogButton(spec, view);
    });
    ui.openDialog($dialog, $dialogFields.querySelector('input, select, textarea') || $dialogButtons.querySelector('button'));
  }

  function onDialogButton(spec, view) {
    if (spec.sound) Titan.remoteUI.playServerSound(spec.sound);
    if (spec.action === 'cancel') { ui.closeDialog($dialog); return; }
    if (spec.action === 'open') {
      ui.closeDialog($dialog);
      if (spec.screen) openScreen(spec.screen);
      return;
    }
    if (spec.action === 'submit' && dialogForm && !dialogForm.validate()) return;
    const payload = spec.action === 'submit' ? dialogForm.values() : {};
    ws.remoteScreenAction(dialogSlug, spec.id || spec.action, payload,
      spec.action === 'submit' ? 'submit' : 'action')
      .then(function (resp) {
        if (!resp.success) throw new Error(resp.error);
        applyResult(resp.result || {}, { inDialog: true });
      })
      .catch(fail);
  }

  $dialogForm.addEventListener('submit', function (e) { e.preventDefault(); });
  $dialog.addEventListener('cancel', function () {
    // Escape closes the form; the service underneath is untouched.
    dialogForm = null;
  });

  // ---------- Firing things ----------

  function fire(action, payload, kind, quiet) {
    return ws.remoteScreenAction(slug, action, payload || {}, kind || 'submit')
      .then(function (resp) {
        if (!resp.success) throw new Error(resp.error);
        applyResult(resp.result || {}, { quiet: quiet });
      })
      .catch(fail);
  }

  function fireRow(row) {
    if (row.sound) Titan.remoteUI.playServerSound(row.sound);
    const payload = Object.assign(values(), { item: row.id });
    fire(row.action || 'activate', payload, 'activate');
  }

  function fireMenuItem(item) {
    if (item.sound) Titan.remoteUI.playServerSound(item.sound);
    if (item.action === 'close') { showIndex(); return; }
    if (item.action === 'refresh') { fire('refresh', values(), 'action', true); return; }
    if (item.action === 'open') { if (item.screen) openScreen(item.screen); return; }
    // A menu item usually acts on the row the user is sitting on, so it is
    // sent along; a service that does not care simply ignores it.
    const payload = values();
    const focused = document.activeElement;
    const view = current();
    if (view && view.items && view.items.length) {
      const rowId = focused && focused.dataset ? focused.dataset.rowId : null;
      payload.item = rowId || view.items[0].id;
    }
    fire(item.id || item.action, payload,
      item.action === 'submit' ? 'submit' : 'action');
  }

  function onViewButton(spec) {
    if (spec.sound) Titan.remoteUI.playServerSound(spec.sound);
    if (spec.action === 'cancel') { goBack(); return; }
    if (spec.action === 'open') { if (spec.screen) openScreen(spec.screen); return; }
    if (spec.action === 'submit' && form && !form.validate()) return;
    fire(spec.id || spec.action, spec.action === 'submit' ? values() : {},
      spec.action === 'submit' ? 'submit' : 'action');
  }

  // ---------- Navigation ----------

  // Escape pops instantly and tells the server afterwards, so going back
  // stays immediate even on a slow link — the server keeps its own copy of
  // the stack and the reserved `__back__` action keeps the two in step.
  function goBack() {
    if (stack.length <= 1) { leaveService(); return; }
    stack.pop();
    renderView(current());
    ui.focusHeading($heading);
    ws.remoteScreenAction(slug, Titan.remoteUI.BACK_ACTION, {}, 'action').catch(function () {});
  }

  function goBackTo(index) {
    while (stack.length - 1 > index) {
      stack.pop();
      ws.remoteScreenAction(slug, Titan.remoteUI.BACK_ACTION, {}, 'action').catch(function () {});
    }
    renderView(current());
    ui.focusHeading($heading);
  }

  function leaveService() {
    document.title = t('svc.page_title');
    showIndex();
  }

  $back.addEventListener('click', goBack);
  document.getElementById('svc-leave').addEventListener('click', leaveService);
  document.getElementById('svc-reload').addEventListener('click', function () {
    fire('refresh', values(), 'action', true).then(function () {
      ui.announce(t('svc.refreshed'));
    });
  });
  document.getElementById('svc-index-refresh').addEventListener('click', loadIndex);

  // Escape inside the service means back — but never while a modal is open
  // (the browser gives that one Escape of its own) and never while the user
  // is typing into a field, where Escape belongs to the control.
  $screen.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || $dialog.open) return;
    const inField = document.activeElement
      && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    if (inField) return;
    e.preventDefault();
    goBack();
  });

  // ---------- Auto-refresh ----------

  function stopAutoRefresh() {
    if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null; }
  }

  function startAutoRefresh(view) {
    stopAutoRefresh();
    const seconds = Number(view.refresh_seconds || 0);
    if (!seconds) return;
    refreshTimer = setInterval(function () {
      // Never while a dialog is up, and never while somebody is typing:
      // replacing the list under them would throw away where they were.
      if ($dialog.open) return;
      const active = document.activeElement;
      if (active && /^(INPUT|TEXTAREA)$/.test(active.tagName)) return;
      fire('refresh', values(), 'action', true);
    }, seconds * 1000);
  }

  // ---------- Applying a result ----------

  function applyResult(result, opts) {
    opts = opts || {};

    if (result.sound) Titan.remoteUI.playServerSound(result.sound);

    if (result.errors && Object.keys(result.errors).length) {
      const target = opts.inDialog ? dialogForm : form;
      if (target) target.setErrors(result.errors);
      const first = Object.keys(result.errors)[0];
      ui.announce(result.errors[first], 'assertive');
      if (opts.inDialog) $dialogMessage.textContent = result.errors[first];
      return;
    }

    if (result.values && !opts.inDialog && form) {
      Object.keys(result.values).forEach(function (key) { form.setValue(key, result.values[key]); });
    } else if (result.values && opts.inDialog && dialogForm) {
      Object.keys(result.values).forEach(function (key) { dialogForm.setValue(key, result.values[key]); });
    }
    if (result.items && typeof result.items === 'object' && !Array.isArray(result.items)) {
      const target = opts.inDialog ? dialogForm : form;
      if (target) {
        Object.keys(result.items).forEach(function (key) { target.setItems(key, result.items[key]); });
      }
    }

    if (result.announce) ui.announce(result.announce);

    const follow = result.screen;
    if (follow && typeof follow === 'object') {
      if (follow.kind === 'view') {
        if (result.restored) stack[stack.length - 1] = follow;
        else stack.push(follow);
        if ($dialog.open) ui.closeDialog($dialog);
        renderView(follow);
        // A drill-down is a navigation with no page load behind it, so the
        // focus is moved to the new heading — otherwise a screen reader
        // carries on reading the list the user has just left.
        if (!opts.quiet) ui.focusHeading($heading);
      } else {
        // A form opened from a service sits on top of it and closing it
        // comes back here.
        renderDialog(follow, slug);
      }
    } else if (result.refresh) {
      const view = current();
      if (view) {
        if (Array.isArray(result.items)) view.items = result.items;
        if (result.status !== undefined && result.status !== null) view.status = result.status;
        $status.textContent = view.status || '';
        renderRows(view, true);
      }
    } else if (result.back) {
      if (stack.length > 1) {
        stack.pop();
        renderView(current());
        ui.focusHeading($heading);
      } else {
        leaveService();
      }
    }

    if (result.message) {
      if (opts.inDialog && $dialog.open) {
        $dialogMessage.textContent = result.message;
        ui.announce(result.message);
      } else {
        ui.setAlert($alert, result.message, 'success');
      }
    }

    if (result.close) {
      if (opts.inDialog) {
        ui.closeDialog($dialog);
        // Coming back from a form: the list behind it may have changed.
        if (stack.length) fire('refresh', values(), 'action', true);
      } else {
        leaveService();
      }
    }
  }

  window.onLangChanged = function () {
    if (!slug) renderIndex();
  };

  window.addEventListener('beforeunload', stopAutoRefresh);

  Titan.session.ws().then(function (socket) {
    ws = socket;

    // The server can open a screen at somebody unprompted — an
    // acknowledgement a moderator has to see now, for instance.
    ws.addEventListener('msg:remote_screen_push', function (e) {
      const detail = e.detail || {};
      if (!detail.screen) return;
      slug = detail.slug;
      stack = [];
      if (Titan.sounds) Titan.sounds.play('notification');
      ui.announce(t('svc.pushed', detail.screen.title || ''));
      applyResult({ screen: detail.screen }, {});
    });

    // Deep link: services.html?screen=<slug> opens it straight away, so a
    // service can be linked to from anywhere.
    const wanted = new URLSearchParams(location.search).get('screen');
    return loadIndex().then(function () {
      if (wanted) openScreen(wanted.toLowerCase());
    });
  }).catch(function (err) {
    if (err && err.message === 'no-credentials') { Titan.session.toLogin(); return; }
    fail(err);
  });
})();
