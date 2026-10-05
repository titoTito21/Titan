# -*- coding: utf-8 -*-
"""Titan, reached the way a component reaches it: directly.

The shared modules ask Titan things through ``LINK.bridge('apps.list')``
and ``LINK.run_action('ocr', 'ask', ...)``, because that is how the NVDA
add-on has to: it is another program, on the other side of a named pipe,
and everything it asks is a message with a timeout on it.

**Titan Access is not on the other side of anything.** It is a Titan
component, running inside Titan's own process, and the thing the add-on's
pipe eventually reaches - ``src.titan_core.bridge_api.bridge`` - is an
ordinary function here. So this answers the same three methods by calling
it, and the difference is not cosmetic:

* **Nothing is serialised.** There is no pipe to queue behind, so a
  reading that takes a model twenty seconds does not hold up anything
  else this reader asks.
* **Nothing times out.** "Titan did not answer within 12s" is a sentence
  about a pipe. There is no pipe.
* **Nothing has to be running.** ``connected()`` is about whether Titan's
  own modules import, which inside Titan they do.

The shared modules do not know any of that, and must not have to: they ask
the same way in both readers, and this is what one of the two answers
mean.
"""

import json
import threading

_LOCK = threading.RLock()

_counted = {'calls': 0, 'failed': 0}
_last_error = ''


def _text(value):
    return str(value or '').strip()


def _own_calls():
    """What Titan Access answers ITSELF, never asking Titan.

    The reader's own features must not depend on which Titan it runs in:
    a compiled Titan freezes `bridge_api` into Titan.exe while this
    component is plain data beside it, so a newer reader asking an older
    Titan for ``ocr.read_windows`` was answered "this Titan has no bridge
    call" - and the screen review, the local reading and the picture
    fallback all went silent. Reading the screen is the reader's job, so
    the reader carries it (`titan_access.windows_ocr`,
    `titan_access.local_model`), libraries and model files in its own
    folder."""
    from titan_access import local_model, windows_ocr
    return {'ocr.windows': windows_ocr.call_windows,
            'ocr.read_windows': windows_ocr.call_read_windows,
            'ocr.model': local_model.call_model,
            'ocr.install_model': local_model.call_install,
            'ocr.read_local': local_model.call_read_local}


def _answer_own(call, args):
    """``(True, data)`` when this reader answers the call itself, else None."""
    try:
        handler = _own_calls().get(str(call or ''))
    except Exception:                                # noqa: BLE001
        return None
    if handler is None:
        return None
    try:
        return True, handler(dict(args or {}))
    except Exception as error:                       # noqa: BLE001
        return False, '%s: %s' % (type(error).__name__, error)


class Link(object):
    """The add-on's ``Link``, with Titan in the same process."""

    #: Kept for the shared modules that read it after a failure.
    last_error = ''

    def connected(self):
        """Whether Titan is reachable. Inside Titan, that is whether its
        own doorway imports - which is a real question on a half-installed
        machine and not merely a formality."""
        try:
            from src.titan_core import bridge_api        # noqa: F401
            return True
        except Exception as error:                   # noqa: BLE001
            globals()['_last_error'] = '%s: %s' % (type(error).__name__,
                                                   error)
            return False

    def introduce(self):
        """The add-on says who it is over the pipe. There is no pipe."""
        return True

    def bridge(self, call, timeout=None, **args):
        """One typed call into Titan. ``(ok, data_or_error)``.

        ``timeout`` is accepted and ignored - it is a property of a pipe,
        and there is none. Accepted rather than refused because the shared
        modules pass it, and a signature that differed between the two
        trees would stop them being one file.

        A call this reader answers ITSELF (`_own_calls`) never reaches
        Titan at all.
        """
        own = _answer_own(call, args)
        if own is not None:
            with _LOCK:
                _counted['calls'] += 1
                if not own[0]:
                    _counted['failed'] += 1
            if not own[0]:
                self.last_error = own[1]
            return own
        try:
            from src.titan_core import bridge_api
        except Exception as error:                   # noqa: BLE001
            self.last_error = '%s: %s' % (type(error).__name__, error)
            return False, 'Titan is not installed here: %s' % self.last_error
        with _LOCK:
            _counted['calls'] += 1
        try:
            answer = bridge_api.bridge(json.dumps(
                {'call': str(call or ''), 'args': dict(args or {})}))
        except Exception as error:                   # noqa: BLE001
            with _LOCK:
                _counted['failed'] += 1
            self.last_error = '%s: %s' % (type(error).__name__, error)
            return False, self.last_error
        try:
            found = json.loads(answer) if isinstance(answer, str) else answer
        except ValueError as error:
            with _LOCK:
                _counted['failed'] += 1
            self.last_error = 'Titan answered something that is not JSON: %s' \
                % error
            return False, self.last_error
        if not isinstance(found, dict):
            with _LOCK:
                _counted['failed'] += 1
            return False, 'Titan answered something that is not an object'
        if not found.get('ok'):
            with _LOCK:
                _counted['failed'] += 1
            self.last_error = _text(found.get('error')) or 'the call failed'
            return False, self.last_error
        return True, found.get('data')

    def run_action(self, addon, action, timeout=None, **args):
        """An add-on's action, through the same doorway. ``(ok, text)``."""
        ok, data = self.bridge('addons.run', addon=addon, action=action,
                               args=args)
        if not ok:
            return False, data
        if isinstance(data, dict):
            return bool(data.get('ok', True)), _text(data.get('text'))
        return True, _text(data)

    def handlers(self):
        """What the add-on serves back to Titan. Nothing does, here."""
        return {}


#: The one link, spelled as the add-on spells it.
LINK = Link()

DECLARED = []


def report():
    with _LOCK:
        found = dict(_counted)
    found.update({'connected': LINK.connected(), 'in_process': True,
                  'last_error': LINK.last_error or _last_error})
    return found


def stop():
    """The add-on closes its pipe here. There is none."""
    return True
