# -*- coding: utf-8 -*-
"""VMware itself, asked about the window the reader is looking at.

An agent inside the guest is the only way to get real TEXT out of one, and
nobody is going to install one - least of all in a guest old enough to need
this most. So before asking for an agent, ask the thing that is already
installed: **VMware Workstation ships `vmrun`**, and the hypervisor knows
what the host's accessibility layer cannot.

What it will answer with nothing installed in the guest and no credentials,
measured against a live Windows 95 guest on this machine:

* `list` - which virtual machines are running, by `.vmx` path. **0.30 s.**
* `readVariable <vmx> runtimeConfig displayName` - what the machine is
  CALLED, which is what the reader should say rather than "VMware".
* `checkToolsState <vmx>` - `running` here, on a guest from 1995.
* `readVariable <vmx> guestVar <name>` - a guest variable. Answers blank
  when nothing has set one, which is the useful part: something in the guest
  that calls `vmware-rpctool "info-set guestinfo.<name> <value>"` reaches
  this reader with **no port, no socket and no network at all** - so a guest
  with no networking, or one behind a firewall nobody will touch, still has
  a channel. That is what `said()` reads.

And what it will NOT answer, which is why none of this is on a timer:

* `captureScreen` is a GUEST operation: `Anonymous guest operations are not
  allowed on this virtual machine. You must call VixVM_LoginInGuest`. So the
  guest's screen does NOT come from VMware, and does not need to - the MKS
  window's own device context gives it in 9 ms (`localOcr.from_window`),
  which is already how a guest is read here.
* `runProgramInGuest` on that guest **never answered** - killed by hand at
  120 s. An old guest's tools report `running` and take no guest operation,
  so anything needing the guest is asked ONCE, with a deadline, and
  remembered as unavailable rather than asked again.

Nothing here reads the guest's memory, changes the machine, or sends
anything anywhere. Every call is a read, on a worker thread, with a hard
timeout.
"""

import os
import subprocess
import threading
import time

#: A call that reads the host's own tables answers in about a third of a
#: second. Anything slower than this is a guest operation in disguise, and
#: waiting on one costs two minutes.
CALL_TIMEOUT = 4.0

#: The list of running machines is asked at most this often: a machine is
#: not started twice a second, and the answer costs a process.
LIST_KEPT = 5.0

#: A guest variable is read at most this often. `said()` is the channel a
#: guest reports on, so it has to be quick enough to be a channel and cheap
#: enough not to be a poll: one process per this many seconds.
VAR_KEPT = 0.4

#: The guest variable an agent inside the guest sets. Read as
#: `guestinfo.<this>` by VMware's own convention.
SAY_VAR = 'titan.say'

#: Where `vmrun` is, in the order it is looked for. The registry is asked
#: first (an installation anywhere is found); these are the defaults.
KNOWN = (
    r'C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe',
    r'C:\Program Files\VMware\VMware Workstation\vmrun.exe',
    r'C:\Program Files (x86)\VMware\VMware VIX\vmrun.exe',
    r'C:\Program Files\VMware\VMware Player\vmrun.exe',
)

_LOCK = threading.RLock()
_state = {'vmrun': None, 'calls': 0, 'failed': 0, 'slow': 0, 'why': '',
          'refused': False, 'said': 0}
_listed = {'at': 0.0, 'vms': ()}
_names = {}
_vars = {}
_windows = {}
_warming = set()


def report():
    """What has really been asked of VMware, for the diagnostics.

    **It looks for `vmrun` rather than reporting what has been looked for
    already.** Read live, this said `available: false` on a machine with
    VMware Workstation installed and a guest running - because nothing had
    asked yet, and "not found" and "never looked" came back as the same
    answer. Looking is a registry read and a file test; there is no excuse
    for a diagnostic that cannot tell those two apart.
    """
    vmrun()
    with _LOCK:
        found = dict(_state)
        found['vmrun'] = found['vmrun'] or ''
        found['running'] = list(_listed['vms'])
    found['available'] = bool(found['vmrun'])
    return found


def forget():
    """For the tests."""
    with _LOCK:
        _state.update({'vmrun': None, 'calls': 0, 'failed': 0, 'slow': 0,
                       'why': '', 'refused': False, 'said': 0})
        _listed.update({'at': 0.0, 'vms': ()})
        _names.clear()
        _vars.clear()
        _windows.clear()
        _warming.clear()


# --------------------------------------------------------------------------- #
# Finding it
# --------------------------------------------------------------------------- #
def _from_registry():
    """VMware's own installation path, which is where it really is."""
    try:
        import winreg
    except Exception:                                # noqa: BLE001
        return ''
    places = (
        (r'SOFTWARE\WOW6432Node\VMware, Inc.\VMware Workstation',
         'InstallPath'),
        (r'SOFTWARE\VMware, Inc.\VMware Workstation', 'InstallPath'),
        (r'SOFTWARE\WOW6432Node\VMware, Inc.\VMware VIX', 'InstallPath'),
    )
    for key, value in places:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
                where = str(winreg.QueryValueEx(handle, value)[0] or '')
        except Exception:                            # noqa: BLE001
            continue
        if not where:
            continue
        found = os.path.join(where, 'vmrun.exe')
        if os.path.isfile(found):
            return found
    return ''


def vmrun():
    """Where `vmrun.exe` is, or '' - asked once and remembered."""
    with _LOCK:
        found = _state['vmrun']
    if found is not None:
        return found
    where = _from_registry()
    if not where:
        for guess in KNOWN:
            if os.path.isfile(guess):
                where = guess
                break
    with _LOCK:
        _state['vmrun'] = where
        if not where:
            _state['why'] = 'vmrun.exe was not found'
    return where


def _call(*arguments):
    """One `vmrun` call. ``(ok, text)``, and never raises.

    The timeout is the whole point: a guest operation against an old guest
    does not fail, it waits, and a reader waiting on a subprocess is a
    reader that has stopped answering.
    """
    where = vmrun()
    if not where:
        return False, ''
    command = [where, '-T', 'ws'] + [str(part) for part in arguments]
    started = time.time()
    with _LOCK:
        _state['calls'] += 1
    try:
        done = subprocess.run(command, capture_output=True, timeout=CALL_TIMEOUT,
                              creationflags=_no_window())
    except subprocess.TimeoutExpired:
        with _LOCK:
            _state['slow'] += 1
            _state['refused'] = True
            _state['why'] = 'a call did not answer within %.0f s' % CALL_TIMEOUT
        return False, ''
    except Exception as error:                       # noqa: BLE001
        with _LOCK:
            _state['failed'] += 1
            _state['why'] = str(error)
        return False, ''
    spent = time.time() - started
    if spent > CALL_TIMEOUT / 2:
        with _LOCK:
            _state['slow'] += 1
    text = (done.stdout or b'').decode('utf-8', 'replace').strip()
    if done.returncode != 0:
        with _LOCK:
            _state['failed'] += 1
            _state['why'] = (done.stderr or b'').decode(
                'utf-8', 'replace').strip()[:200] or 'the call failed'
        return False, text
    return True, text


def _no_window():
    """Never a console window: this runs inside a screen reader."""
    try:
        return subprocess.CREATE_NO_WINDOW
    except AttributeError:
        return 0


# --------------------------------------------------------------------------- #
# What is running
# --------------------------------------------------------------------------- #
def running():
    """The `.vmx` paths of the machines that are running."""
    now = time.time()
    with _LOCK:
        if _listed['vms'] and now - _listed['at'] < LIST_KEPT:
            return list(_listed['vms'])
        asked = _listed['at']
    if now - asked < 1.0:
        with _LOCK:
            return list(_listed['vms'])
    ok, text = _call('list')
    found = []
    if ok:
        for line in text.splitlines():
            line = line.strip()
            if line.lower().endswith('.vmx'):
                found.append(line)
    with _LOCK:
        _listed['at'] = time.time()
        _listed['vms'] = tuple(found)
    return found


def name_of(vmx):
    """What the machine is CALLED - its own display name, or its file."""
    if not vmx:
        return ''
    with _LOCK:
        if vmx in _names:
            return _names[vmx]
    ok, text = _call('readVariable', vmx, 'runtimeConfig', 'displayName')
    name = text.strip() if ok else ''
    if not name:
        name = os.path.splitext(os.path.basename(vmx))[0]
    with _LOCK:
        _names[vmx] = name
    return name


def tools_state(vmx):
    """`running`, `installed`, `notInstalled`, or '' when it cannot be asked.

    A guest whose tools are not running can take no guest operation at all,
    which is what decides whether offering to deploy an agent is honest.
    """
    if not vmx:
        return ''
    ok, text = _call('checkToolsState', vmx)
    return text.strip() if ok else ''


def _titles(hwnd):
    """The window's own title and its root's, for matching a machine."""
    import ctypes
    user32 = ctypes.windll.user32
    found = []
    for handle in (hwnd, user32.GetAncestor(int(hwnd), 2)):
        if not handle:
            continue
        buffer = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(int(handle), buffer, 512)
        text = str(buffer.value or '').strip()
        if text and text not in found:
            found.append(text)
    return found


def vm_for_window(hwnd):
    """Which running machine this window is showing, by `.vmx`, or ''.

    The window's title carries the machine's own name - that is how VMware
    titles it - so a name from `list` that appears in the title is the
    machine. With exactly one machine running, that one is the answer
    whatever the window is called: a guest window belongs to the only guest
    there is.
    """
    machines = running()
    if not machines:
        return ''
    if len(machines) == 1:
        return machines[0]
    try:
        titles = _titles(hwnd)
    except Exception:                                # noqa: BLE001
        titles = []
    for vmx in machines:
        name = name_of(vmx)
        if name and any(name.lower() in title.lower() for title in titles):
            return vmx
    return ''


def describe(hwnd):
    """The machine this window shows, as a name, or '' - for the sentence."""
    name = name_of(vm_for_window(hwnd))
    if name:
        with _LOCK:
            _windows[int(hwnd)] = name
    return name


# --------------------------------------------------------------------------- #
# ...without ever waiting for it
# --------------------------------------------------------------------------- #
# Asking VMware costs a PROCESS - measured 0.29 s for `list` and 0.31 s for a
# variable, on a warm machine that answered perfectly. That is nothing on a
# worker and ruinous on the path that reads a control: the layer that says
# where the keyboard has moved stands down at 50 ms, and this is twenty times
# that. So the reading path asks only what is already known, and the asking
# happens beside it.
def name_now(hwnd):
    """The machine's name if it is known already - no call, no wait."""
    with _LOCK:
        return _windows.get(int(hwnd or 0), '')


def warm(hwnd):
    """Find out on a thread, so the NEXT reading can say the name.

    One at a time per window: arriving in a guest fires more than once (the
    foreground change, then the focus), and each would otherwise be its own
    process.
    """
    handle = int(hwnd or 0)
    if not handle or not vmrun():
        return False
    with _LOCK:
        if handle in _windows or handle in _warming:
            return False
        _warming.add(handle)

    def ask():
        try:
            describe(handle)
        finally:
            with _LOCK:
                _warming.discard(handle)

    threading.Thread(target=ask, name='TitanVMware', daemon=True).start()
    return True


# --------------------------------------------------------------------------- #
# The channel that needs no network
# --------------------------------------------------------------------------- #
def said(vmx, name=SAY_VAR):
    """What the guest has put in its variable, once per change, or ''.

    An agent in the guest sets it with VMware Tools' own
    `vmware-rpctool "info-set guestinfo.titan.say <text>"`. Reading it
    needs no login, no port and no network - which is what makes it worth
    having beside the socket in `agentLink`.

    The same value read twice is not said twice: a variable holds what it
    was last set to for ever, and a reader repeating it on every poll would
    be unusable. A guest that means to say the same thing again puts a
    counter in front of it (`3|Start`), which is what VMware's own examples
    do and what the agent here writes.
    """
    if not vmx:
        return ''
    now = time.time()
    key = (vmx, name)
    with _LOCK:
        held = _vars.get(key)
        if held and now - held[0] < VAR_KEPT:
            return ''
    ok, text = _call('readVariable', vmx, 'guestVar', name)
    text = text.strip() if ok else ''
    with _LOCK:
        last = (_vars.get(key) or (0.0, None))[1]
        _vars[key] = (time.time(), text)
        if not text or text == last:
            return ''
        _state['said'] += 1
    # A counter in front is how a guest repeats itself; it is not words.
    if '|' in text:
        head, rest = text.split('|', 1)
        if head.strip().isdigit():
            text = rest
    return text.strip()
