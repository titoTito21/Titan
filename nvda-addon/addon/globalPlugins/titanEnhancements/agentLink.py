# -*- coding: utf-8 -*-
"""An agent on the OTHER side of a wall, telling the reader what it sees.

Two walls this add-on cannot see through from here, for the same reason:

* **Inside a virtual machine.** The guest's drawing happens in the guest, on
  the far side of the virtual hardware. Measured on a real VMware window:
  the display model answered `nothing of NVDA is injected into that process`
  twenty times out of twenty, and no host-side hook can do better - the host
  is handed a framebuffer, not text.
* **Inside a game engine.** Unity, Unreal and the rest draw their text as
  meshes through Direct3D; they never call a GDI text function, so the
  display model is empty and a picture is all there is. But the engine
  itself knows every string: a `TextMeshPro` component holds the words.

In both cases the words exist - just not on this side. So instead of trying
to read them from outside, something on the INSIDE says them, and this is
the ear for it: one small channel, one line of JSON per thing seen.

    {"token": "...", "kind": "pointer", "say": "Start", "rect": [0,452,60,28]}

`kind` is what the agent was doing when it saw it, and the reader treats it
the way it treats its own layers: `pointer` is what is under the pointer now,
`focus` is what the keyboard reached, `menu`/`screen` are whole readings.

**The security is the point, not a detail.** A socket that makes a screen
reader speak is a socket that lets any program on the machine say anything
in the user's ear, and a reader is trusted absolutely by the person using
it. So: off until switched on; bound to 127.0.0.1 unless the guest switch is
also on; and every line must carry a token that is generated here and never
leaves except to the agent the user installs. A line without it is counted
and dropped in silence - answering would tell a prober it had found the
port.
"""

import json
import socket
import threading
import time

from . import compat
from . import i18n

_ = i18n.install(globals())

#: The port. Deliberately fixed and high: the agent has to be told it, and a
#: port that moves cannot be written into an agent's configuration once.
PORT = 37375

#: How long the channel waits for an agent before looking at whether it has
#: been asked to stop. Short enough to stop promptly, long enough that
#: waiting costs nothing.
ACCEPT_TURN = 0.5

#: How often the guest variable is read. It costs a process, so it is slow
#: until something has really answered on it and quick afterwards: a channel
#: nobody is using must not be two processes a second for ever.
VAR_IDLE = 3.0
VAR_BUSY = 0.5

#: A line longer than this is not a thing somebody saw, it is an attempt to
#: make the reader allocate.
MAX_LINE = 8192

#: What the agent may say it was doing. Anything else is dropped: a `kind`
#: the reader does not know would be announced with no context at all.
KINDS = ('pointer', 'focus', 'menu', 'screen', 'state')

_LOCK = threading.RLock()
_state = {'listening': False, 'where': '', 'agents': 0, 'lines': 0,
          'said': 0, 'dropped': 0, 'refused': 0, 'why': '',
          'last': '', 'last_kind': '', 'from_vmware': 0, 'vmware': False,
          'starting': False}
_server = None
_stop = None
_var_stop = None


def report():
    """What the channel has really done, for the diagnostics."""
    with _LOCK:
        found = dict(_state)
    found['port'] = PORT
    found['wanted'] = wanted()
    found['guest_allowed'] = guest_allowed()
    return found


def _setting(name, default):
    try:
        from . import configSpec
        return configSpec.read().get(name, default)
    except Exception:                                # noqa: BLE001
        return default


def wanted():
    return bool(_setting('agentLink', False))


def guest_allowed():
    return bool(_setting('agentFromGuest', False))


def token():
    """The shared secret, made once and kept in NVDA's own configuration.

    Not a password the user types: a long random string the agent is given.
    Stored where NVDA stores everything else about this add-on, so it
    survives a restart and the agent does not have to be told again.
    """
    import secrets
    try:
        from . import configSpec
        found = str(configSpec.read().get('agentToken', '') or '')
        if len(found) >= 32:
            return found
        fresh = secrets.token_urlsafe(24)
        # `write` takes a DICT of the settings to change, and writes only
        # names that are in the spec.
        configSpec.write({'agentToken': fresh})
        return fresh
    except Exception:                                # noqa: BLE001
        # Without somewhere to keep it, one per session is still better than
        # no token at all - the agent is told it by the settings page.
        global _session_token
        try:
            return _session_token
        except NameError:
            _session_token = secrets.token_urlsafe(24)
            return _session_token


def _host_now():
    """Every interface only when the user has said an agent may come from
    outside this machine. That is the difference between a channel for a
    guest and a port anything on the network can speak into."""
    return '0.0.0.0' if guest_allowed() else '127.0.0.1'


def _where_it_should_be():
    return '%s:%d' % (_host_now(), PORT)


def _note(why):
    with _LOCK:
        _state['why'] = str(why)


def _announce(kind, said):
    """Hand it to the reader's own live channel, which de-duplicates."""
    from . import live
    prefix = ''
    if kind == 'pointer':
        # Translators: said before what an agent reports under the pointer.
        prefix = _('pointer')
    elif kind == 'menu':
        # Translators: said before a menu an agent reports.
        prefix = _('menu')
    politeness = 'assertive' if kind == 'state' else 'polite'
    return live.announce(said, politeness=politeness, prefix=prefix)


def _handle(line):
    """One line from an agent. True when it was said."""
    with _LOCK:
        _state['lines'] += 1
    try:
        message = json.loads(line)
    except Exception:                                # noqa: BLE001
        with _LOCK:
            _state['dropped'] += 1
        return False
    if not isinstance(message, dict):
        with _LOCK:
            _state['dropped'] += 1
        return False
    if str(message.get('token') or '') != token():
        # Never answered and never explained: a prober learns nothing.
        with _LOCK:
            _state['refused'] += 1
        return False
    kind = str(message.get('kind') or 'screen')
    if kind not in KINDS:
        with _LOCK:
            _state['dropped'] += 1
        return False
    said = str(message.get('say') or '').strip()
    if not said:
        with _LOCK:
            _state['dropped'] += 1
        return False
    with _LOCK:
        _state['last'] = said[:200]
        _state['last_kind'] = kind
    if _announce(kind, said):
        with _LOCK:
            _state['said'] += 1
        return True
    with _LOCK:
        _state['dropped'] += 1
    return False


def _serve(server, stop_event):
    with _LOCK:
        _state['listening'] = True
    # **Waiting is done in short turns, on purpose.** Something else in
    # this process has called `socket.setdefaulttimeout`, which applies to
    # every socket made afterwards - so `accept()` raised `timed out` a few
    # seconds after the channel opened, the loop treated that as the socket
    # being gone, and the reader reported the channel shut while the port
    # was still listening. Measured with netstat against the report; no
    # amount of reading the code showed it, and the only reason it was
    # findable at all is that the loop now says why it stopped.
    try:
        server.settimeout(ACCEPT_TURN)
    except OSError:                                  # pragma: no cover
        pass
    while not stop_event.is_set():
        try:
            client, _where = server.accept()
        except socket.timeout:
            # Nobody yet. That is the ordinary case, not a failure.
            continue
        except OSError as error:
            _note('the channel stopped waiting: %s' % error)
            break
        with _LOCK:
            _state['agents'] += 1
        threading.Thread(target=_talk, args=(client, stop_event),
                         name='TitanAgent', daemon=True).start()
    with _LOCK:
        # Only about the socket this thread was given: a thread that has
        # been replaced must not report the live one as shut.
        if _server is server or _server is None:
            _state['listening'] = False


def _talk(client, stop_event):
    """Read whole lines from one agent until it goes away."""
    buffered = b''
    try:
        client.settimeout(1.0)
        while not stop_event.is_set():
            try:
                block = client.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not block:
                break
            buffered += block
            if len(buffered) > MAX_LINE * 4:
                buffered = b''
                continue
            while b'\n' in buffered:
                raw, buffered = buffered.split(b'\n', 1)
                if len(raw) > MAX_LINE:
                    continue
                text = raw.decode('utf-8', 'replace').strip()
                if text:
                    _handle(text)
    finally:
        try:
            client.close()
        except OSError:
            pass


def start():
    """Listen, if the user has asked for it. ``(ok, why)``.

    **Two traps here, both found by reading `netstat` rather than the
    report.**

    The claim is taken under the lock and held until the socket is really
    listening. `keep_running` is called from the plugin AND from
    `configSpec.apply`, and both ran during start-up: each passed a check
    that only looked at `_server`, each bound a socket, the second replaced
    the first, and the first - collected and closed - came out of `accept`
    with an error and wrote `listening: False` over a channel that was in
    fact open. The port was listening and the reader said it was not.

    And **`SO_REUSEADDR` is not what it is on Unix.** On Windows it lets a
    SECOND process bind a port that is already bound, and then connections
    are handed to whichever - so any program on the machine could take over
    a socket whose whole purpose is to make a screen reader speak. Windows'
    answer is `SO_EXCLUSIVEADDRUSE`, which refuses exactly that; a port
    already in use is then an honest failure with a reason, which is what
    the user should be told.
    """
    global _server, _stop
    if not wanted():
        return False, _('The agent channel is switched off.')
    with _LOCK:
        if _server is not None or _state['starting']:
            return True, ''
        _state['starting'] = True
    host = _host_now()
    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.setsockopt(socket.SOL_SOCKET,
                              socket.SO_EXCLUSIVEADDRUSE, 1)
        except (AttributeError, OSError):
            # Not Windows, where the flag does not exist and the Unix
            # meaning of SO_REUSEADDR is the right one.
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, PORT))
        server.listen(4)
    except OSError as error:
        with _LOCK:
            _state['starting'] = False
        _note('the port could not be opened: %s' % error)
        return False, str(error)
    stop_event = threading.Event()
    with _LOCK:
        _server, _stop = server, stop_event
        _state['where'] = '%s:%d' % (host, PORT)
        _state['why'] = ''
        _state['starting'] = False
    threading.Thread(target=_serve, args=(server, stop_event),
                     name='TitanAgentLink', daemon=True).start()
    return True, ''


def stop():
    """Stop listening. True when something was stopped."""
    global _server, _stop
    with _LOCK:
        server, stop_event = _server, _stop
        _server = _stop = None
    if stop_event is not None:
        stop_event.set()
    if server is not None:
        try:
            server.close()
        except OSError:
            pass
        return True
    return False


# --------------------------------------------------------------------------- #
# The same channel, with no network at all
# --------------------------------------------------------------------------- #
# A socket is the obvious transport and the wrong one for the case this
# exists for. A guest old enough to need a reader most is a guest with no
# TCP/IP configured, behind a NAT nobody will touch, or one where opening a
# port is the part the user will not do - and on the host it means a port
# listening in a screen reader.
#
# VMware Tools already carries a channel: inside the guest,
#
#     vmware-rpctool "info-set guestinfo.titan.say 4|pointer|Start"
#
# and the host reads it with `vmrun readVariable ... guestVar titan.say`.
# That is one line of shell, on every guest VMware supports - Windows, Linux,
# macOS, Solaris - with no port, no socket, no address and nothing installed
# but the tools the guest already has. Measured end to end on this machine
# against a live Windows 95 guest: written, read back, said, and not said
# twice.
#
# There is no token here and that is deliberate rather than an omission: the
# variable can only be written from inside that machine or by VMware on this
# one. Both are already further inside the user's trust than a program that
# can open a socket to 127.0.0.1.
def _from_guest_variable(text):
    """`[kind|]words` out of a guest variable. True when it was said."""
    kind = 'pointer'
    if '|' in text:
        head, rest = text.split('|', 1)
        if head.strip() in KINDS:
            kind, text = head.strip(), rest
    said = text.strip()
    if not said:
        return False
    with _LOCK:
        _state['lines'] += 1
        _state['from_vmware'] += 1
        _state['last'] = said[:200]
        _state['last_kind'] = kind
    if _announce(kind, said):
        with _LOCK:
            _state['said'] += 1
        return True
    with _LOCK:
        _state['dropped'] += 1
    return False


def _watch_variables(stop_event):
    from . import vmware
    every = VAR_IDLE
    with _LOCK:
        _state['vmware'] = True
    try:
        while not stop_event.wait(every):
            machines = []
            try:
                machines = vmware.running()
            except Exception:                        # noqa: BLE001
                machines = []
            if not machines:
                every = VAR_IDLE
                continue
            heard = False
            for vmx in machines:
                try:
                    text = vmware.said(vmx)
                except Exception:                    # noqa: BLE001
                    text = ''
                if text:
                    heard = True
                    _from_guest_variable(text)
            every = VAR_BUSY if heard else every
    finally:
        with _LOCK:
            _state['vmware'] = False


def start_variables():
    """Watch the guest variable, if VMware is here. True when started."""
    global _var_stop
    with _LOCK:
        if _var_stop is not None:
            return True
    try:
        from . import vmware
        if not vmware.vmrun():
            return False
    except Exception:                                # noqa: BLE001
        return False
    stop_event = threading.Event()
    with _LOCK:
        _var_stop = stop_event
    threading.Thread(target=_watch_variables, args=(stop_event,),
                     name='TitanAgentVars', daemon=True).start()
    return True


def stop_variables():
    global _var_stop
    with _LOCK:
        stop_event, _var_stop = _var_stop, None
    if stop_event is None:
        return False
    stop_event.set()
    return True


def keep_running():
    """Start or stop to match the settings. Called from the plugin.

    **And rebind when the ANSWER changed, not only when it was switched
    on.** Turning "let an agent reach the reader over the network" off left
    the socket bound to 0.0.0.0 until NVDA was restarted - measured with
    netstat while the settings said it was localhost only. A permission the
    user has taken back has to be taken back now.
    """
    running = _server is not None
    if running and wanted() and _state['where'] != _where_it_should_be():
        stop()
        running = False
    if wanted() and not running:
        start()
    elif not wanted() and running:
        stop()
    if wanted():
        start_variables()
    else:
        stop_variables()
