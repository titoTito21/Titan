# -*- coding: utf-8 -*-
"""Shared JavaScript core injected into every Titan IM web backend.

Why a core at all
-----------------
The old integrations (``messenger_webview.py`` / ``whatsapp_webview.py``) fired
a fresh ``RunScript`` with a wall of CSS selectors every few seconds from a
``wx.Timer``. That is polling: it is late, it misses events between ticks, and
every caller re-invented its own JSON envelope and error handling.

This module is the other half of ``bridge.WebBridge``: one script, injected at
document start (so it survives reloads and SPA navigation), that provides

* ``__titanBridge.emit(type, payload)``  - push an event to Python (batched),
* ``__titanBridge.command(name, fn)``    - register a command Python can call,
* ``__titanBridge.probe(name, fn)``      - register a data-source health probe,
* ``__titanExec(envelope)``              - entry point used by ``RunScriptAsync``,
* ``__titanSelfTest()``                  - report which data sources are alive,
* ``__titanBridge.dom``                  - the DOM helpers both fallbacks need.

Kept as a Python string (exactly like ``src/network/call_detection_js.py``) so
the JavaScript can never drift out of sync with the Python that drives it and
so PyInstaller needs no extra ``datas`` entry.

Envelope contract (JSON both ways, one line each)
-------------------------------------------------
JS -> Python  ``{"v":1,"agent":"whatsapp","kind":"events","events":[{...}]}``
              ``{"v":1,"agent":"whatsapp","kind":"reply","id":7,"ok":true,"result":...}``
Python -> JS  ``__titanExec({"id":7,"cmd":"send_text","args":{...}})``

Commands may return a value or a Promise; both are answered on the same reply
channel, and a throw is reported as ``ok:false`` instead of vanishing.
"""

from __future__ import annotations

BRIDGE_CORE = r"""
(function () {
  'use strict';
  if (window.__titanBridge) { return; }

  var HANDLER = '%%HANDLER%%';
  var AGENT   = '%%AGENT%%';

  var MAX_QUEUE = 300;     // hard cap, oldest events are dropped first
  var FLUSH_MS  = 60;      // batching window - keeps a burst from flooding wx

  // ---------------------------------------------------------------- transport
  function rawPost(obj) {
    try {
      var h = window[HANDLER];
      if (h && typeof h.postMessage === 'function') {
        h.postMessage(JSON.stringify(obj));
        return true;
      }
    } catch (e) { /* handler not installed yet, or page blocked it */ }
    return false;
  }

  var queue = [];
  var flushTimer = null;

  function schedule(ms) {
    if (flushTimer !== null) { return; }
    flushTimer = setTimeout(flush, (ms === undefined) ? FLUSH_MS : ms);
  }

  function flush() {
    flushTimer = null;
    if (!queue.length) { return; }
    var batch = queue.splice(0, queue.length);
    if (!rawPost({ v: 1, agent: AGENT, kind: 'events', events: batch })) {
      // The script message handler is not up yet. Put the batch back (newest
      // wins if we are over the cap) and try again shortly - losing the
      // ``ready`` event here would strand the client on a blank list.
      queue = batch.concat(queue).slice(-MAX_QUEUE);
      schedule(250);
    }
  }

  function emit(type, payload) {
    queue.push({ type: type, payload: (payload === undefined) ? null : payload, t: Date.now() });
    if (queue.length > MAX_QUEUE) { queue.splice(0, queue.length - MAX_QUEUE); }
    schedule();
  }

  function log(msg) { emit('log', { message: String(msg) }); }

  function fail(where, err) {
    emit('error', { where: where, message: (err && err.message) ? err.message : String(err) });
  }

  // ----------------------------------------------------------------- commands
  var commands = {};

  function command(name, fn) { commands[name] = fn; }

  function reply(id, ok, data) {
    rawPost({
      v: 1, agent: AGENT, kind: 'reply', id: id, ok: !!ok,
      result: ok ? ((data === undefined) ? null : data) : null,
      error: ok ? null : ((data && data.message) ? data.message : String(data))
    });
  }

  function exec(envelope) {
    var env;
    try { env = (typeof envelope === 'string') ? JSON.parse(envelope) : envelope; }
    catch (e) { fail('exec.parse', e); return; }
    if (!env || typeof env.id === 'undefined') { return; }

    var fn = commands[env.cmd];
    if (!fn) { reply(env.id, false, 'unknown command: ' + env.cmd); return; }

    var out;
    try { out = fn(env.args || {}); }
    catch (e) { reply(env.id, false, e); return; }

    if (out && typeof out.then === 'function') {
      out.then(function (r) { reply(env.id, true, r); },
               function (e) { reply(env.id, false, e); });
    } else {
      reply(env.id, true, out);
    }
  }

  // ------------------------------------------------------------------- probes
  var probes = {};

  function probe(name, fn) { probes[name] = fn; }

  function selfTest() {
    var out = {
      agent: AGENT,
      href: location.href,
      agent_ready: !!window.__titanAgentReady,
      queued: queue.length,
      sources: {}
    };
    for (var k in probes) {
      if (!probes.hasOwnProperty(k)) { continue; }
      try { out.sources[k] = probes[k]() ? 'ok' : 'missing'; }
      catch (e) { out.sources[k] = 'error: ' + ((e && e.message) ? e.message : e); }
    }
    return out;
  }

  // --------------------------------------------------------------- DOM helpers
  // Shared by both DOM fallback paths, so the two agents cannot drift apart on
  // "is this element really usable".
  function visible(el) {
    if (!el) { return false; }
    if (el.offsetWidth > 0 || el.offsetHeight > 0) { return true; }
    try {
      var r = el.getClientRects();
      return !!(r && r.length);
    } catch (e) { return false; }
  }

  function q(selectors, root) {
    var list = (typeof selectors === 'string') ? [selectors] : (selectors || []);
    var scope = root || document;
    for (var i = 0; i < list.length; i++) {
      try {
        var el = scope.querySelector(list[i]);
        if (el) { return el; }
      } catch (e) { /* invalid selector on this page version */ }
    }
    return null;
  }

  function qa(selectors, root) {
    var list = (typeof selectors === 'string') ? [selectors] : (selectors || []);
    var scope = root || document;
    for (var i = 0; i < list.length; i++) {
      try {
        var found = scope.querySelectorAll(list[i]);
        if (found && found.length) { return Array.prototype.slice.call(found); }
      } catch (e) { /* keep trying the next candidate */ }
    }
    return [];
  }

  function text(el) {
    if (!el) { return ''; }
    return (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  }

  function click(el) {
    if (!el) { return false; }
    try {
      ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(function (type) {
        var ev;
        try {
          ev = new MouseEvent(type, { bubbles: true, cancelable: true, view: window });
        } catch (e) {
          ev = document.createEvent('MouseEvents');
          ev.initEvent(type, true, true);
        }
        el.dispatchEvent(ev);
      });
      return true;
    } catch (e) { return false; }
  }

  // Type into a React-controlled contenteditable / input without losing the
  // framework's internal state. Paste beats keystroke synthesis here: both
  // WhatsApp and Messenger honour a real ClipboardEvent with a DataTransfer.
  function typeInto(el, value) {
    if (!el) { return false; }
    try {
      el.focus();
      if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
        var setter = Object.getOwnPropertyDescriptor(el.constructor.prototype, 'value');
        if (setter && setter.set) { setter.set.call(el, value); } else { el.value = value; }
        el.dispatchEvent(new Event('input', { bubbles: true }));
        return true;
      }
      // 1) A real paste event with a DataTransfer: what both services' editors
      //    actually listen for, and it keeps their internal state consistent.
      try {
        if (typeof DataTransfer === 'function' && typeof ClipboardEvent === 'function') {
          var dt = new DataTransfer();
          dt.setData('text/plain', value);
          var notCancelled = el.dispatchEvent(new ClipboardEvent('paste', {
            bubbles: true, cancelable: true, clipboardData: dt
          }));
          if (notCancelled === false) { return true; }   // handler consumed it
        }
      } catch (e) { /* no clipboard constructors here - keep going */ }

      // 2) The editing command, for builds that ignore synthetic paste.
      try {
        if (document.execCommand && document.execCommand('insertText', false, value)) {
          return true;
        }
      } catch (e) { /* not supported */ }

      // 3) Last resort: write it and tell the framework something changed.
      el.textContent = value;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    } catch (e) { fail('typeInto', e); return false; }
  }

  function pressEnter(el) {
    if (!el) { return false; }
    var opts = { bubbles: true, cancelable: true, key: 'Enter', code: 'Enter',
                 keyCode: 13, which: 13, charCode: 13 };
    try {
      el.focus();
      el.dispatchEvent(new KeyboardEvent('keydown', opts));
      el.dispatchEvent(new KeyboardEvent('keypress', opts));
      el.dispatchEvent(new KeyboardEvent('keyup', opts));
      return true;
    } catch (e) { fail('pressEnter', e); return false; }
  }

  // Poll a predicate until it is truthy. Returned as a Promise so agents can
  // ``await`` page transitions instead of guessing with fixed delays.
  function waitFor(test, timeout, interval) {
    var limit = (typeof timeout === 'number') ? timeout : 10000;
    var step = (typeof interval === 'number') ? interval : 150;
    return new Promise(function (resolve, reject) {
      var started = Date.now();
      (function tick() {
        var value;
        try { value = test(); }
        catch (e) { reject(e); return; }
        if (value) { resolve(value); return; }
        if (Date.now() - started >= limit) { reject(new Error('timeout')); return; }
        setTimeout(tick, step);
      })();
    });
  }

  // Turn a Blob/File/ArrayBuffer into base64 for the trip to Python.
  function toBase64(blob) {
    return new Promise(function (resolve, reject) {
      try {
        var reader = new FileReader();
        reader.onload = function () {
          var s = String(reader.result || '');
          var comma = s.indexOf(',');
          resolve(comma >= 0 ? s.slice(comma + 1) : s);
        };
        reader.onerror = function () { reject(new Error('read failed')); };
        reader.readAsDataURL(blob);
      } catch (e) { reject(e); }
    });
  }

  // The reverse trip: Python hands us base64 and we rebuild a real File so the
  // page's own upload path can take it.
  function toFile(b64, name, mime) {
    var bin = atob(b64 || '');
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) { bytes[i] = bin.charCodeAt(i); }
    var type = mime || 'application/octet-stream';
    try { return new File([bytes], name || 'file', { type: type }); }
    catch (e) { return new Blob([bytes], { type: type }); }
  }

  // ------------------------------------------------------- anti-throttling
  // The host window lives offscreen so the user never sees the service's own
  // UI. Chromium would normally mark such a page hidden and both WhatsApp and
  // Messenger then slow their sync down. We are the engine, so we always
  // report "visible" and swallow visibilitychange.
  function stayVisible() {
    try {
      Object.defineProperty(document, 'hidden', {
        get: function () { return false; }, configurable: true
      });
      Object.defineProperty(document, 'visibilityState', {
        get: function () { return 'visible'; }, configurable: true
      });
      Object.defineProperty(document, 'webkitHidden', {
        get: function () { return false; }, configurable: true
      });
      document.addEventListener('visibilitychange', function (e) {
        e.stopImmediatePropagation();
      }, true);
      window.addEventListener('blur', function (e) {
        e.stopImmediatePropagation();
      }, true);
    } catch (e) { /* not fatal - only affects sync latency */ }
  }
  stayVisible();

  // -------------------------------------------------------------- blob slots
  // Attachments travel as base64 in bounded chunks rather than one giant
  // string: a 5 MB voice note would otherwise mean a 7 MB JSON message in a
  // single ``RunScriptAsync`` / ``postMessage`` call.
  //
  //   Python -> page (sending):   __blob_begin, __blob_chunk*, __blob_end
  //                               then the agent uses blobs[id].file
  //   page -> Python (receiving): the agent calls putBlob(), Python pulls with
  //                               __blob_read* and releases with __blob_drop
  var blobs = {};

  function putBlob(id, base64, name, mime) {
    blobs[id] = { name: name || 'file', mime: mime || 'application/octet-stream',
                  parts: [], data: base64 || '', file: null };
    return { blob_id: id, length: blobs[id].data.length,
             name: blobs[id].name, mime: blobs[id].mime };
  }

  command('__blob_begin', function (a) {
    blobs[a.id] = { name: a.name || 'file', mime: a.mime || 'application/octet-stream',
                    parts: [], data: '', file: null };
    return true;
  });

  command('__blob_chunk', function (a) {
    var b = blobs[a.id];
    if (!b) { throw new Error('no such blob: ' + a.id); }
    b.parts.push(a.data || '');
    return b.parts.length;
  });

  command('__blob_end', function (a) {
    var b = blobs[a.id];
    if (!b) { throw new Error('no such blob: ' + a.id); }
    b.data = b.parts.join('');
    b.parts = [];
    b.file = toFile(b.data, b.name, b.mime);
    return { length: b.data.length };
  });

  command('__blob_read', function (a) {
    var b = blobs[a.id];
    if (!b) { throw new Error('no such blob: ' + a.id); }
    var offset = a.offset || 0;
    var length = a.length || 262144;
    return { data: b.data.substr(offset, length), total: b.data.length };
  });

  command('__blob_drop', function (a) { delete blobs[a.id]; return true; });

  // ------------------------------------------------------------------ exports
  command('__ping', function () { return { pong: Date.now(), href: location.href }; });
  command('__self_test', function () { return selfTest(); });
  command('__eval', function (args) {
    // Diagnostics only - used by the client's troubleshooting window.
    return (new Function('return (' + String(args.code || 'null') + ')'))();
  });

  window.__titanBridge = {
    agent: AGENT,
    emit: emit,
    log: log,
    fail: fail,
    command: command,
    probe: probe,
    exec: exec,
    selfTest: selfTest,
    ready: function (capabilities) {
      window.__titanAgentReady = true;
      emit('ready', { capabilities: capabilities || [], href: location.href });
    },
    blobs: blobs,
    putBlob: putBlob,
    dom: {
      q: q, qa: qa, text: text, visible: visible, click: click,
      typeInto: typeInto, pressEnter: pressEnter, waitFor: waitFor,
      toBase64: toBase64, toFile: toFile
    }
  };
  window.__titanExec = exec;
  window.__titanSelfTest = selfTest;

  emit('bridge_loaded', { href: location.href });
})();
"""


def build_bridge_core(handler_name: str, agent_name: str) -> str:
    """Return the bridge core bound to one script message handler and agent."""
    return (BRIDGE_CORE
            .replace('%%HANDLER%%', handler_name)
            .replace('%%AGENT%%', agent_name))
