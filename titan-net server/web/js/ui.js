// Titan-Net web — shared accessible UI primitives.
//
// Every widget here answers the same rule the desktop client follows: a
// control is accessible because it IS the right element, not because a
// label was bolted onto a div. Dialogs are <dialog> (the browser owns the
// focus trap, Escape and inertness), tabs are real buttons in a tablist,
// lists of actions are <ul> of <button>, and anything that changes away
// from the keyboard is announced through a live region.
(function () {
  'use strict';

  // ---------- Live announcements ----------
  // Two channels: polite for ordinary updates, assertive for errors the
  // user must hear before they carry on typing.
  function liveRegion(kind) {
    const id = kind === 'assertive' ? 'live-assertive' : 'live-polite';
    let node = document.getElementById(id);
    if (!node) {
      node = document.createElement('div');
      node.id = id;
      node.className = 'sr-only';
      node.setAttribute('role', kind === 'assertive' ? 'alert' : 'status');
      node.setAttribute('aria-live', kind === 'assertive' ? 'assertive' : 'polite');
      node.setAttribute('aria-atomic', 'true');
      document.body.appendChild(node);
    }
    return node;
  }

  function announce(text, kind) {
    const node = liveRegion(kind);
    node.textContent = '';
    setTimeout(function () { node.textContent = String(text); }, 50);
  }

  // ---------- Element building ----------
  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        const v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === 'text') node.textContent = String(v);
        else if (k === 'class') node.className = v;
        else if (k === 'dataset') Object.assign(node.dataset, v);
        else if (k.slice(0, 2) === 'on' && typeof v === 'function') {
          node.addEventListener(k.slice(2).toLowerCase(), v);
        } else if (v === true) node.setAttribute(k, '');
        else node.setAttribute(k, String(v));
      });
    }
    (children || []).forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return node;
  }

  function clear(node) {
    while (node && node.firstChild) node.removeChild(node.firstChild);
  }

  // Format an ISO timestamp for reading. A screen reader says a bare
  // "2026-08-25T11:04:00" one character at a time, so it is turned into
  // the reader's own locale text and the machine form kept in <time>.
  function timeNode(iso, opts) {
    const node = document.createElement('time');
    if (!iso) return node;
    const d = new Date(iso);
    if (isNaN(d.getTime())) { node.textContent = String(iso); return node; }
    node.dateTime = d.toISOString();
    node.textContent = d.toLocaleString(
      Titan.getLang() === 'pl' ? 'pl-PL' : 'en-GB',
      opts || { dateStyle: 'medium', timeStyle: 'short' }
    );
    return node;
  }

  function timeText(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return d.toLocaleString(Titan.getLang() === 'pl' ? 'pl-PL' : 'en-GB',
      { dateStyle: 'medium', timeStyle: 'short' });
  }

  function bytes(n) {
    n = Number(n);
    if (!n || isNaN(n)) return '';
    const units = ['B', 'kB', 'MB', 'GB'];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return n.toFixed(n < 10 && i > 0 ? 1 : 0) + ' ' + units[i];
  }

  // ---------- Dialogs ----------
  // A <dialog> opened with showModal() gets the focus trap, the Escape key,
  // aria-modal and the inert background from the browser itself. What is
  // added here is what the browser does NOT do: the focus is put on
  // something meaningful, and it is given back to whatever opened the
  // dialog, which is WCAG 2.4.3 and the thing a hand-rolled modal loses.
  function openDialog(dialog, focusTarget) {
    if (!dialog) return;
    dialog._titanOpener = document.activeElement;
    if (typeof dialog.showModal === 'function') {
      if (!dialog.open) dialog.showModal();
    } else {
      dialog.setAttribute('open', '');
    }
    const target = typeof focusTarget === 'string'
      ? dialog.querySelector(focusTarget)
      : (focusTarget
          || dialog.querySelector('[autofocus]')
          || dialog.querySelector('input, select, textarea, button'));
    setTimeout(function () { try { if (target) target.focus(); } catch (e) {} }, 50);
    if (!dialog._titanCloseBound) {
      dialog._titanCloseBound = true;
      dialog.addEventListener('close', function () {
        const opener = dialog._titanOpener;
        if (opener && document.contains(opener)) {
          try { opener.focus(); } catch (e) {}
        }
      });
    }
  }

  function closeDialog(dialog) {
    if (!dialog) return;
    if (typeof dialog.close === 'function' && dialog.open) dialog.close();
    else dialog.removeAttribute('open');
  }

  function uid(prefix) {
    return (prefix || 'x') + '-' + Math.random().toString(36).slice(2, 9);
  }

  // A confirmation the keyboard and a screen reader can both use. Never
  // window.confirm(): that one cannot be translated, styled, or told what
  // it is about beyond one line of text.
  function confirmDialog(question, opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      const base = uid('confirm');
      const yes = el('button', {
        type: 'button',
        class: opts.danger ? 'btn-danger' : '',
        text: opts.confirmLabel || Titan.t('common.confirm'),
      });
      const no = el('button', {
        type: 'button', class: 'btn-secondary',
        text: opts.cancelLabel || Titan.t('common.cancel'),
      });
      const dialog = el('dialog', {
        class: 'titan-dialog',
        'aria-labelledby': base + '-title',
        'aria-describedby': base + '-body',
      }, [
        el('h2', { id: base + '-title', text: opts.title || Titan.t('common.confirm_title') }),
        el('p', { id: base + '-body', text: question }),
        el('div', { class: 'flex dialog-actions' }, [yes, no]),
      ]);
      document.body.appendChild(dialog);
      function finish(value) {
        closeDialog(dialog);
        setTimeout(function () { if (dialog.isConnected) dialog.remove(); }, 400);
        resolve(value);
      }
      yes.addEventListener('click', function () { finish(true); });
      no.addEventListener('click', function () { finish(false); });
      dialog.addEventListener('cancel', function (e) { e.preventDefault(); finish(false); });
      // The destructive choice is never what the focus lands on.
      openDialog(dialog, opts.danger ? no : yes);
    });
  }

  // A prompt for one value, same contract as confirmDialog.
  //
  // `opts.options` - a list of {value, label} - asks for one of a known
  // set instead of free text, and it is a real <select>, so the browser
  // gives it the listbox role, first-letter jumping and the count, and a
  // screen reader says which of how many is chosen. Asking somebody to
  // TYPE an id they have to go and look up on another page is what this
  // replaced.
  function promptDialog(label, opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      const base = uid('prompt');
      const choices = Array.isArray(opts.options) ? opts.options : null;
      const input = choices
        ? el('select', { id: base + '-input' })
        : (opts.multiline
          ? el('textarea', { id: base + '-input', rows: '5' })
          : el('input', { id: base + '-input', type: opts.password ? 'password' : 'text' }));
      if (choices) {
        choices.forEach(function (choice) {
          const option = el('option', { value: String(choice.value) });
          option.textContent = choice.label != null ? String(choice.label) : String(choice.value);
          input.appendChild(option);
        });
      }
      if (opts.value) input.value = opts.value;
      if (opts.required && !choices) input.required = true;
      const ok = el('button', { type: 'submit', text: opts.confirmLabel || Titan.t('common.ok') });
      const cancel = el('button', {
        type: 'button', class: 'btn-secondary', text: Titan.t('common.cancel'),
      });
      const help = opts.help ? el('p', { class: 'help', id: base + '-help', text: opts.help }) : null;
      if (help) input.setAttribute('aria-describedby', base + '-help');
      const form = el('form', {}, [
        el('div', { class: 'field' }, [
          el('label', { for: base + '-input', text: label }),
          input,
          help,
        ]),
        el('div', { class: 'flex dialog-actions' }, [ok, cancel]),
      ]);
      const dialog = el('dialog', {
        class: 'titan-dialog', 'aria-labelledby': base + '-title',
      }, [
        el('h2', { id: base + '-title', text: opts.title || label }),
        form,
      ]);
      document.body.appendChild(dialog);
      function finish(value) {
        closeDialog(dialog);
        setTimeout(function () { if (dialog.isConnected) dialog.remove(); }, 400);
        resolve(value);
      }
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        // A <select> always carries one of its own options, so there is
        // nothing to be empty; only free text can be.
        if (opts.required && !choices && !input.value.trim()) {
          fieldErrorFor(input, base, Titan.t('err.required'));
          input.focus();
          return;
        }
        finish(input.value);
      });
      cancel.addEventListener('click', function () { finish(null); });
      dialog.addEventListener('cancel', function (e) { e.preventDefault(); finish(null); });
      openDialog(dialog, input);
    });
  }

  // ---------- Tabs ----------
  // The desktop clients put the tab bar on row 0 of the list and cycle it
  // with Left/Right. The native web equivalent is a real tablist: arrows
  // move, Home/End jump, and only the active tab is in the Tab order, so a
  // twelve-tab service is one Tab stop rather than twelve.
  function tabs(container, entries, onSelect) {
    clear(container);
    container.setAttribute('role', 'tablist');
    const buttons = entries.map(function (entry, index) {
      const btn = el('button', {
        type: 'button',
        role: 'tab',
        id: (container.id || 'tabs') + '-tab-' + String(entry.id).replace(/[^\w-]/g, ''),
        class: 'tab',
        'aria-selected': index === 0 ? 'true' : 'false',
        tabindex: index === 0 ? '0' : '-1',
        text: entry.label,
      });
      if (entry.panel) btn.setAttribute('aria-controls', entry.panel);
      container.appendChild(btn);
      return btn;
    });

    function select(index, focus) {
      buttons.forEach(function (b, i) {
        b.setAttribute('aria-selected', i === index ? 'true' : 'false');
        b.tabIndex = i === index ? 0 : -1;
      });
      if (focus !== false) { try { buttons[index].focus(); } catch (e) {} }
      if (onSelect) onSelect(entries[index], index);
    }

    buttons.forEach(function (btn, index) {
      btn.addEventListener('click', function () { select(index); });
      btn.addEventListener('keydown', function (e) {
        let next = null;
        if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (index + 1) % buttons.length;
        else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (index - 1 + buttons.length) % buttons.length;
        else if (e.key === 'Home') next = 0;
        else if (e.key === 'End') next = buttons.length - 1;
        if (next !== null) { e.preventDefault(); select(next); }
      });
    });

    return {
      select: function (id) {
        const index = entries.findIndex(function (entry) { return entry.id === id; });
        if (index >= 0) select(index, false);
      },
      selectIndex: function (index, focus) { select(index, focus); },
      current: function () {
        const i = buttons.findIndex(function (b) { return b.getAttribute('aria-selected') === 'true'; });
        return entries[i];
      },
      buttons: buttons,
    };
  }

  // ---------- Status / error surfaces ----------
  // An error is assertive; anything else is polite, because interrupting
  // somebody mid-word to say "saved" is worse than telling them a moment
  // later.
  function setAlert(node, text, kind) {
    if (!node) return;
    if (!text) {
      node.hidden = true;
      node.textContent = '';
      node.className = 'alert';
      return;
    }
    kind = kind || 'error';
    node.className = 'alert alert-' + kind;
    node.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    node.textContent = text;
    node.hidden = false;
    announce(text, kind === 'error' ? 'assertive' : 'polite');
  }

  // A region whose content is being replaced says so, so a reader is not
  // left on a stale list wondering whether anything happened.
  function setBusy(node, busy) {
    if (!node) return;
    if (busy) node.setAttribute('aria-busy', 'true');
    else node.removeAttribute('aria-busy');
  }

  // ---------- Field errors ----------
  function fieldErrorFor(input, base, message) {
    if (!input) return;
    const errId = (input.id || base) + '-err';
    let err = document.getElementById(errId);
    if (!err) {
      err = el('p', { id: errId, class: 'field-error' });
      input.insertAdjacentElement('afterend', err);
    }
    if (message) {
      input.setAttribute('aria-invalid', 'true');
      const described = (input.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
      if (described.indexOf(errId) === -1) described.push(errId);
      input.setAttribute('aria-describedby', described.join(' '));
      err.textContent = message;
      err.hidden = false;
    } else {
      input.removeAttribute('aria-invalid');
      err.textContent = '';
      err.hidden = true;
    }
  }

  function fieldError(inputId, message) {
    fieldErrorFor(document.getElementById(inputId), inputId, message);
  }

  // ---------- Disclosure ----------
  function toggleRegion(button, region) {
    const open = region.hidden;
    region.hidden = !open;
    button.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) {
      const first = region.querySelector('h2, h3, input, select, textarea, button');
      if (first) {
        if (/^H[23]$/.test(first.tagName) && !first.hasAttribute('tabindex')) first.tabIndex = -1;
        try { first.focus(); } catch (e) {}
      }
    }
    return open;
  }

  // ---------- Focusing a region after a navigation ----------
  // Drilling into a topic, a service view or a game replaces the main
  // region without a page load, so nothing moves the focus and a screen
  // reader keeps reading where it was. Moving it to the new heading is
  // what a real page navigation would have done.
  function focusHeading(node) {
    if (!node) return;
    if (!node.hasAttribute('tabindex')) node.tabIndex = -1;
    try { node.focus(); } catch (e) {}
  }

  window.Titan = window.Titan || {};
  window.Titan.ui = {
    el: el,
    clear: clear,
    uid: uid,
    timeNode: timeNode,
    timeText: timeText,
    bytes: bytes,
    announce: announce,
    openDialog: openDialog,
    closeDialog: closeDialog,
    confirmDialog: confirmDialog,
    promptDialog: promptDialog,
    tabs: tabs,
    setAlert: setAlert,
    setBusy: setBusy,
    fieldError: fieldError,
    toggleRegion: toggleRegion,
    focusHeading: focusHeading,
  };
  window.Titan.announce = announce;
})();
