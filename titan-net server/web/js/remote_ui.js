// Titan-Net web — the generic renderer for server-defined screens.
//
// The server describes a screen as declarative JSON and every client draws
// it with one renderer, so a service written today opens in a browser that
// was built months ago. Nothing executable crosses the wire: this reads
// data and skips what it does not recognise, which is exactly what keeps
// an older client working.
//
// The field types are the ones `titan-net server/remote_ui.py` validates —
// text, multiline, number, choice, checkbox, radio, list, static,
// separator — and each is rendered as the native control for it, never as
// a div with a label bolted on.
(function () {
  'use strict';

  const ui = Titan.ui;
  const t = function (key) { return Titan.t(key); };

  // ---------- Server sounds ----------
  // The server names a sound it has registered; the browser fetches it
  // from /api/sounds/<name> and plays it. A sound is never the only way
  // anything is said — every one of them accompanies text.
  const soundCache = {};
  function playServerSound(name) {
    if (!name) return;
    try {
      let audio = soundCache[name];
      if (!audio) {
        audio = new Audio(Titan.API.soundUrl(name));
        audio.preload = 'auto';
        soundCache[name] = audio;
      }
      audio.currentTime = 0;
      const played = audio.play();
      if (played && played.catch) played.catch(function () {});
    } catch (e) {}
  }

  // ---------- Fields ----------

  function fieldId(prefix, field) {
    return prefix + '-f-' + String(field.id || Math.random().toString(36).slice(2))
      .replace(/[^\w-]/g, '_');
  }

  function describedBy(input, ids) {
    const list = ids.filter(Boolean);
    if (list.length) input.setAttribute('aria-describedby', list.join(' '));
  }

  // Build the controls for one screen's fields. Returns a small object the
  // caller uses to read the values back, show per-field errors and put the
  // focus on the first thing that is wrong.
  function renderFields(container, fields, prefix) {
    ui.clear(container);
    prefix = prefix || 'rui';
    const controls = {};

    (fields || []).forEach(function (field) {
      const type = field.type;

      if (type === 'separator') {
        container.appendChild(ui.el('hr'));
        return;
      }

      if (type === 'static') {
        // Read-only prose. It is given a heading only if it has a label,
        // so a screen of plain text does not become a wall of headings.
        if (field.label) container.appendChild(ui.el('h3', { text: field.label }));
        String(field.text || '').split(/\n{2,}/).forEach(function (para) {
          container.appendChild(ui.el('p', { text: para }));
        });
        return;
      }

      const id = fieldId(prefix, field);
      const hintId = field.hint ? id + '-hint' : null;
      const errId = id + '-err';
      const label = field.label || field.id;
      let input = null;
      let wrapper = null;

      if (type === 'text' || type === 'multiline') {
        input = type === 'multiline'
          ? ui.el('textarea', { id: id, rows: '6' })
          : ui.el('input', { id: id, type: field.password ? 'password' : 'text' });
        input.value = field.default || '';
        if (field.required) input.required = true;
        if (field.readonly) input.readOnly = true;
        if (field.max_length) input.setAttribute('maxlength', String(field.max_length));
      } else if (type === 'number') {
        input = ui.el('input', {
          id: id, type: 'number',
          min: String(field.min), max: String(field.max), step: String(field.step || 1),
        });
        input.value = String(field.default === undefined ? field.min : field.default);
      } else if (type === 'checkbox') {
        input = ui.el('input', { id: id, type: 'checkbox' });
        input.checked = !!field.default;
        wrapper = ui.el('div', { class: 'field-inline' }, [
          input, ui.el('label', { for: id, text: label }),
        ]);
      } else if (type === 'choice' || type === 'list') {
        input = ui.el('select', { id: id });
        if (type === 'list' || field.style === 'list') {
          input.size = Math.min(10, Math.max(4, (field.items || []).length));
        }
        if (!field.required) {
          input.appendChild(ui.el('option', { value: '', text: t('svc.no_choice') }));
        }
        (field.items || []).forEach(function (item) {
          const option = ui.el('option', { value: String(item.value), text: item.label });
          if (field.default !== undefined && String(field.default) === String(item.value)) {
            option.selected = true;
          }
          input.appendChild(option);
        });
        if (field.required) input.required = true;
      } else if (type === 'radio') {
        // A real radio GROUP: a fieldset with a legend, which is how the
        // platform names the set for a screen reader, and one input per
        // option so the arrows move between them.
        const group = ui.el('fieldset', {}, [ui.el('legend', { text: label })]);
        (field.items || []).forEach(function (item, index) {
          const optionId = id + '-' + index;
          const radio = ui.el('input', {
            id: optionId, type: 'radio', name: id, value: String(item.value),
          });
          if (field.default !== undefined && String(field.default) === String(item.value)) {
            radio.checked = true;
          }
          group.appendChild(ui.el('div', { class: 'field-inline' }, [
            radio, ui.el('label', { for: optionId, text: item.label }),
          ]));
        });
        if (field.hint) group.appendChild(ui.el('p', { class: 'help', id: hintId, text: field.hint }));
        group.appendChild(ui.el('p', { class: 'field-error', id: errId, hidden: true }));
        container.appendChild(group);
        controls[field.id] = { type: type, node: group, name: id, label: label, errId: errId };
        return;
      } else {
        return;   // a type this client does not know: skipped, never guessed at
      }

      const hint = field.hint ? ui.el('p', { class: 'help', id: hintId, text: field.hint }) : null;
      const error = ui.el('p', { class: 'field-error', id: errId, hidden: true });
      describedBy(input, [hintId, errId]);

      if (!wrapper) {
        wrapper = ui.el('div', { class: 'field' }, [
          ui.el('label', { for: id, text: label }),
          input, hint, error,
        ]);
      } else {
        if (hint) wrapper.appendChild(hint);
        wrapper.appendChild(error);
      }
      container.appendChild(wrapper);
      controls[field.id] = { type: type, node: input, label: label, errId: errId };
    });

    function values() {
      const out = {};
      Object.keys(controls).forEach(function (key) {
        const control = controls[key];
        if (control.type === 'checkbox') out[key] = !!control.node.checked;
        else if (control.type === 'number') out[key] = Number(control.node.value);
        else if (control.type === 'radio') {
          const picked = control.node.querySelector('input:checked');
          out[key] = picked ? picked.value : null;
        } else if (control.type === 'choice' || control.type === 'list') {
          out[key] = control.node.value === '' ? null : control.node.value;
        } else out[key] = control.node.value;
      });
      return out;
    }

    function setValue(key, value) {
      const control = controls[key];
      if (!control) return;
      if (control.type === 'checkbox') control.node.checked = !!value;
      else if (control.type === 'radio') {
        const wanted = control.node.querySelector('input[value="' + String(value).replace(/"/g, '\\"') + '"]');
        if (wanted) wanted.checked = true;
      } else control.node.value = value === null || value === undefined ? '' : String(value);
    }

    // Replace a choice/list field's options — the `update` result's `items`.
    function setItems(key, items) {
      const control = controls[key];
      if (!control || (control.type !== 'choice' && control.type !== 'list')) return;
      const previous = control.node.value;
      ui.clear(control.node);
      (items || []).forEach(function (item) {
        control.node.appendChild(ui.el('option', { value: String(item.value), text: item.label }));
      });
      control.node.value = previous;
    }

    function clearErrors() {
      Object.keys(controls).forEach(function (key) {
        const control = controls[key];
        const error = document.getElementById(control.errId);
        if (error) { error.textContent = ''; error.hidden = true; }
        if (control.type === 'radio') {
          control.node.removeAttribute('aria-invalid');
        } else {
          control.node.removeAttribute('aria-invalid');
        }
      });
    }

    // The server's copy of the definition is the one that decides, so its
    // errors are shown against the same fields the client validated — and
    // the focus goes to the first of them, which is the whole point of
    // reporting an error at all (WCAG 3.3.1, 3.3.3).
    function setErrors(errors) {
      clearErrors();
      let first = null;
      Object.keys(errors || {}).forEach(function (key) {
        const control = controls[key];
        if (!control) return;
        const error = document.getElementById(control.errId);
        if (error) { error.textContent = errors[key]; error.hidden = false; }
        control.node.setAttribute('aria-invalid', 'true');
        if (!first) {
          first = control.type === 'radio'
            ? control.node.querySelector('input')
            : control.node;
        }
      });
      if (first) { try { first.focus(); } catch (e) {} }
      return first;
    }

    // What the client can check before asking the server: required text and
    // a number outside its range. A fast, spoken "this is required" beats a
    // round trip, and the server checks the same things again anyway.
    function validate() {
      clearErrors();
      let first = null;
      (fields || []).forEach(function (field) {
        const control = controls[field.id];
        if (!control) return;
        let problem = null;
        if (field.required) {
          if (control.type === 'radio') {
            if (!control.node.querySelector('input:checked')) problem = t('err.required');
          } else if (!String(control.node.value || '').trim()) {
            problem = t('err.required');
          }
        }
        if (!problem && control.type === 'number') {
          const number = Number(control.node.value);
          if (isNaN(number) || number < field.min || number > field.max) {
            problem = Titan.t('svc.number_range', field.min, field.max);
          }
        }
        if (problem) {
          const error = document.getElementById(control.errId);
          if (error) { error.textContent = problem; error.hidden = false; }
          control.node.setAttribute('aria-invalid', 'true');
          if (!first) {
            first = control.type === 'radio' ? control.node.querySelector('input') : control.node;
          }
        }
      });
      if (first) { try { first.focus(); } catch (e) {} }
      return !first;
    }

    return {
      values: values,
      setValue: setValue,
      setItems: setItems,
      setErrors: setErrors,
      clearErrors: clearErrors,
      validate: validate,
      controls: controls,
    };
  }

  // ---------- Buttons ----------
  // A button carries the action it fires. `confirm` means the user is asked
  // first, through the site's own dialog rather than window.confirm.
  function renderButtons(container, buttons, onPress) {
    ui.clear(container);
    (buttons || []).forEach(function (spec) {
      const btn = ui.el('button', {
        type: spec.action === 'submit' ? 'submit' : 'button',
        class: spec.default ? '' : 'btn-secondary',
        text: spec.label,
      });
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        if (spec.confirm) {
          ui.confirmDialog(spec.confirm, { title: spec.label }).then(function (yes) {
            if (yes) onPress(spec, btn);
          });
          return;
        }
        onPress(spec, btn);
      });
      container.appendChild(btn);
    });
  }

  window.Titan = window.Titan || {};
  window.Titan.remoteUI = {
    renderFields: renderFields,
    renderButtons: renderButtons,
    playServerSound: playServerSound,
    BACK_ACTION: '__back__',
  };
})();
