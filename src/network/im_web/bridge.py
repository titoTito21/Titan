# -*- coding: utf-8 -*-
"""Offscreen WebView2 host: the transport between a web service and Titan.

``WebBridge`` owns one ``wx.html2.WebView`` living in a frame parked far
offscreen. The page is the engine; the user never has to touch it. Two things
make that work reliably:

* **Push instead of polling.** ``AddScriptMessageHandler`` + the injected agent
  (see ``js_bridge``) deliver events the moment the page produces them. The old
  webview integrations re-ran a selector soup from a ``wx.Timer`` every few
  seconds, which is why messages arrived late and calls were mis-detected.
* **Injection at document start.** ``AddUserScript`` with
  ``WEBVIEW_INJECT_AT_DOCUMENT_START`` means the agent is in place before the
  service's own code runs, and it comes back automatically after a reload or an
  in-app navigation - no re-injection bookkeeping.

The frame can be brought on screen on demand (``show_page()``) for the few
cases the accessible client cannot handle by itself: a Messenger login
checkpoint, a captcha, or troubleshooting. Closing it parks it offscreen again
rather than tearing the session down.

Threading: every public method is safe to call from any thread; work is
marshalled onto the GUI thread with ``wx.CallAfter``, and callbacks always run
on the GUI thread.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import wx
import wx.html2

from src.network.im_web.js_bridge import build_bridge_core

# Where the host frame parks when it is not wanted on screen. Far enough out
# that no monitor arrangement can show it, still a legal window position.
OFFSCREEN_POS = (-32000, -32000)

# A realistic viewport matters: the DOM fallback paths read layout, and both
# services render a narrow "mobile" chat list below ~900px.
HOST_SIZE = (1280, 900)

DEFAULT_TIMEOUT = 20.0          # seconds before a command is answered with an error
_SWEEP_INTERVAL_MS = 2000       # how often pending commands are checked for timeout


class WebBridgeUnavailable(RuntimeError):
    """Raised when the Edge (WebView2) backend is missing on this machine."""


def is_available() -> bool:
    """True when WebView2 is installed, i.e. when a bridge can be started."""
    try:
        return wx.html2.WebView.IsBackendAvailable(wx.html2.WebViewBackendEdge)
    except Exception:
        return False


# Flags that keep an offscreen page fully alive. Chromium otherwise treats a
# window it believes to be occluded as background work: frozen timers, throttled
# renderer, paused rendering - which would stall the engine we depend on.
_KEEPALIVE_ARGS = (
    '--disable-features=CalculateNativeWinOcclusion',
    '--disable-backgrounding-occluded-windows',
    '--disable-renderer-backgrounding',
    '--disable-background-timer-throttling',
    '--disable-ipc-flooding-protection',
)

_env_configured = False


def engine_profile_dir() -> str:
    """Where WebView2 keeps cookies, storage and the logged-in session.

    Inside the per-user Titan data directory (``%APPDATA%/titosoft/Titan`` on
    Windows) - never next to the executable, so a shared or read-only install
    still works and every user keeps their own accounts. One shared profile for
    both services is correct: cookies are per-origin, and whatsapp.com and
    messenger.com cannot see each other's.
    """
    from src.platform_utils import get_user_data_dir
    path = os.path.join(get_user_data_dir(), 'IM COOKIES', 'WebView2')
    os.makedirs(path, exist_ok=True)
    return path


def ensure_webview2_environment() -> None:
    """Point WebView2 at the Titan user profile and keep offscreen pages alive.

    Must run before the first WebView2 in the process is created - the loader
    reads these variables once, when it builds the environment. The browser
    arguments are *merged*, because
    ``messenger_webview.configure_webview2_environment()`` may already have put
    its media flags there.
    """
    global _env_configured
    if _env_configured:
        return
    _env_configured = True

    key = 'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'
    current = os.environ.get(key, '')
    present = current.split()
    missing = [flag for flag in _KEEPALIVE_ARGS if flag not in present]
    if missing:
        os.environ[key] = (current + ' ' + ' '.join(missing)).strip()

    try:
        os.environ.setdefault('WEBVIEW2_USER_DATA_FOLDER', engine_profile_dir())
    except Exception as exc:
        print(f"[IMBridge] could not set the WebView2 profile directory: {exc}")


class _HostFrame(wx.Frame):
    """The window the WebView lives in. Normally parked offscreen."""

    def __init__(self, title: str, on_user_close: Callable[[], None]):
        super().__init__(None, title=title, size=HOST_SIZE,
                         style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_NO_TASKBAR)
        self._on_user_close = on_user_close
        self.Bind(wx.EVT_CLOSE, self._on_close)

    def _on_close(self, event: wx.CloseEvent):
        # The user closing the visible page must not kill the engine - park it.
        if event.CanVeto():
            event.Veto()
            self._on_user_close()
            return
        event.Skip()


class WebBridge:
    """One web service, hosted offscreen, driven by commands and events."""

    def __init__(self, service: str, url: str, agent_js: str,
                 title: Optional[str] = None,
                 handler_name: str = 'titan'):
        self.service = service
        self.url = url
        self.agent_js = agent_js
        self.handler_name = handler_name
        self.title = title or f"Titan IM engine ({service})"

        self.frame: Optional[_HostFrame] = None
        self.webview: Optional[wx.html2.WebView] = None

        self._listeners: List[Callable[[str, Any], None]] = []
        self._pending: Dict[int, Dict[str, Any]] = {}
        self._queued: List[Dict[str, Any]] = []
        self._next_id = 1
        self._lock = threading.RLock()

        self._installed = False       # handler + user script registered
        self._bridge_loaded = False   # core injected and talking
        self._agent_ready = False     # agent registered its commands
        self._page_visible = False
        self._stopped = False
        self._sweeper: Optional[wx.Timer] = None

    # ------------------------------------------------------------------ start
    def start(self) -> None:
        """Create the host window and load the service. Idempotent."""
        if self.frame is not None:
            return
        if not is_available():
            raise WebBridgeUnavailable(
                "WebView2 (Edge) backend is not available on this system")

        ensure_webview2_environment()

        self.frame = _HostFrame(self.title, self.hide_page)
        self.frame.SetPosition(OFFSCREEN_POS)

        self.webview = wx.html2.WebView.New(
            self.frame, url='about:blank',
            backend=wx.html2.WebViewBackendEdge)

        self.webview.Bind(wx.html2.EVT_WEBVIEW_LOADED, self._on_loaded)
        self.webview.Bind(wx.html2.EVT_WEBVIEW_ERROR, self._on_error)
        self.webview.Bind(wx.html2.EVT_WEBVIEW_NEWWINDOW, self._on_new_window)
        self.webview.Bind(wx.html2.EVT_WEBVIEW_SCRIPT_MESSAGE_RECEIVED,
                          self._on_script_message)

        # ShowWithoutActivating: the engine must never steal focus from whatever
        # the user is doing when a client connects at startup.
        self.frame.ShowWithoutActivating()

        self._sweeper = wx.Timer(self.frame)
        self.frame.Bind(wx.EVT_TIMER, self._sweep_pending, self._sweeper)
        self._sweeper.Start(_SWEEP_INTERVAL_MS)

    def _install_agent(self) -> bool:
        """Register the message handler and inject the agent. Once per bridge.

        Deferred until the first ``about:blank`` load completes: the Edge
        backend creates its controller asynchronously and both calls fail while
        it is still coming up.
        """
        if self._installed or self.webview is None:
            return self._installed

        try:
            if not self.webview.AddScriptMessageHandler(self.handler_name):
                print(f"[IMBridge:{self.service}] AddScriptMessageHandler failed")
                return False
        except Exception as exc:
            print(f"[IMBridge:{self.service}] AddScriptMessageHandler error: {exc}")
            return False

        script = build_bridge_core(self.handler_name, self.service) + '\n' + self.agent_js
        try:
            if not self.webview.AddUserScript(
                    script, wx.html2.WEBVIEW_INJECT_AT_DOCUMENT_START):
                print(f"[IMBridge:{self.service}] AddUserScript failed")
                return False
        except Exception as exc:
            print(f"[IMBridge:{self.service}] AddUserScript error: {exc}")
            return False

        self._installed = True
        return True

    # ------------------------------------------------------------------- stop
    def stop(self) -> None:
        """Tear the engine down and fail everything still in flight."""
        self._stopped = True
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
            self._queued.clear()
        for entry in pending:
            self._deliver(entry, False, 'bridge stopped')

        def _destroy():
            if self._sweeper is not None:
                self._sweeper.Stop()
                self._sweeper = None
            if self.frame is not None:
                self.frame.Destroy()
            self.frame = None
            self.webview = None
            self._installed = False
            self._bridge_loaded = False
            self._agent_ready = False

        wx.CallAfter(_destroy)

    # --------------------------------------------------------------- visibility
    def show_page(self) -> None:
        """Bring the raw service page on screen (login checkpoint, diagnostics)."""
        def _show():
            if self.frame is None:
                return
            self._page_visible = True
            self.frame.SetSize(HOST_SIZE)
            self.frame.Centre()
            self.frame.Show()
            self.frame.Raise()
            try:
                self.frame.SetFocus()
            except Exception:
                pass
        wx.CallAfter(_show)

    def hide_page(self) -> None:
        """Park the page offscreen again without touching the session."""
        def _hide():
            if self.frame is None:
                return
            self._page_visible = False
            self.frame.SetPosition(OFFSCREEN_POS)
        wx.CallAfter(_hide)

    @property
    def page_visible(self) -> bool:
        return self._page_visible

    @property
    def ready(self) -> bool:
        return self._agent_ready

    # ------------------------------------------------------------------ events
    def add_listener(self, callback: Callable[[str, Any], None]) -> None:
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[str, Any], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _fire(self, event_type: str, payload: Any) -> None:
        for callback in list(self._listeners):
            try:
                callback(event_type, payload)
            except Exception as exc:
                print(f"[IMBridge:{self.service}] listener error on "
                      f"'{event_type}': {exc}")

    # ---------------------------------------------------------------- commands
    def call(self, cmd: str, args: Optional[Dict[str, Any]] = None,
             callback: Optional[Callable[[bool, Any], None]] = None,
             timeout: float = DEFAULT_TIMEOUT) -> int:
        """Run ``cmd`` in the page. ``callback(ok, result_or_error)`` on the GUI thread.

        Commands issued before the agent has registered itself are queued, not
        dropped - a client that opens while the service is still loading still
        gets its chat list.
        """
        if self._stopped:
            if callback:
                wx.CallAfter(callback, False, 'bridge stopped')
            return -1

        with self._lock:
            call_id = self._next_id
            self._next_id += 1
            entry = {
                'id': call_id, 'cmd': cmd, 'args': args or {},
                'callback': callback, 'deadline': time.time() + timeout,
                'sent': False,
            }
            self._pending[call_id] = entry
            internal = cmd.startswith('__')
            can_send = self._bridge_loaded if internal else self._agent_ready
            if not can_send:
                self._queued.append(entry)
                return call_id

        self._dispatch(entry)
        return call_id

    def _dispatch(self, entry: Dict[str, Any]) -> None:
        envelope = json.dumps({'id': entry['id'], 'cmd': entry['cmd'],
                               'args': entry['args']}, ensure_ascii=False)
        # Hand the envelope over as a JS *string* and let the agent parse it:
        # no amount of quoting inside the payload can then break the statement.
        code = f"window.__titanExec({json.dumps(envelope)});"

        def _run():
            if self.webview is None:
                return
            entry['sent'] = True
            try:
                self.webview.RunScriptAsync(code)
            except Exception as exc:
                self._finish(entry['id'], False, f"RunScriptAsync failed: {exc}")

        if wx.IsMainThread():
            _run()
        else:
            wx.CallAfter(_run)

    def _flush_queued(self, internal_only: bool = False) -> None:
        with self._lock:
            still_waiting = []
            ready_now = []
            for entry in self._queued:
                internal = entry['cmd'].startswith('__')
                if internal or not internal_only:
                    ready_now.append(entry)
                else:
                    still_waiting.append(entry)
            self._queued = still_waiting
        for entry in ready_now:
            self._dispatch(entry)

    def _finish(self, call_id: int, ok: bool, data: Any) -> None:
        with self._lock:
            entry = self._pending.pop(call_id, None)
            if entry in self._queued:
                self._queued.remove(entry)
        if entry is None:
            return
        self._deliver(entry, ok, data)

    def _deliver(self, entry: Dict[str, Any], ok: bool, data: Any) -> None:
        callback = entry.get('callback')
        if callback is None:
            if not ok:
                print(f"[IMBridge:{self.service}] '{entry['cmd']}' failed: {data}")
            return
        wx.CallAfter(callback, ok, data)

    def _sweep_pending(self, event) -> None:
        now = time.time()
        expired = []
        with self._lock:
            for call_id, entry in list(self._pending.items()):
                if entry['deadline'] <= now:
                    expired.append(self._pending.pop(call_id))
                    if entry in self._queued:
                        self._queued.remove(entry)
        for entry in expired:
            self._deliver(entry, False, f"timeout waiting for '{entry['cmd']}'")

    # ------------------------------------------------------- webview callbacks
    def _on_loaded(self, event) -> None:
        if not self._installed:
            # First ``about:blank`` load: the controller exists now, so the
            # handler and the user script can finally be registered - and only
            # then is it safe to navigate to the real service.
            if self._install_agent():
                wx.CallAfter(self._load_service)
            else:
                self._fire('error', {'where': 'install_agent',
                                     'message': 'could not install the page agent'})
            return
        event.Skip()

    def _load_service(self) -> None:
        if self.webview is None:
            return
        try:
            self.webview.LoadURL(self.url)
        except Exception as exc:
            self._fire('error', {'where': 'load', 'message': str(exc)})

    def _on_error(self, event) -> None:
        try:
            message = event.GetString()
        except Exception:
            message = 'navigation error'
        self._fire('error', {'where': 'navigation', 'message': message})

    def _on_new_window(self, event) -> None:
        # Login checkpoints and OAuth flows open popups. Keeping them in the
        # same view means the session, the agent and "show page" all still apply.
        try:
            target = event.GetURL()
        except Exception:
            target = ''
        if target and self.webview is not None:
            self.webview.LoadURL(target)
        self._fire('popup', {'url': target})

    def _on_script_message(self, event) -> None:
        try:
            if event.GetMessageHandler() != self.handler_name:
                event.Skip()
                return
            raw = event.GetString()
        except Exception:
            return

        try:
            envelope = json.loads(raw)
        except Exception:
            print(f"[IMBridge:{self.service}] unparsable message: {raw[:200]}")
            return

        kind = envelope.get('kind')
        if kind == 'reply':
            self._finish(int(envelope.get('id', -1)),
                         bool(envelope.get('ok')),
                         envelope.get('result') if envelope.get('ok')
                         else envelope.get('error'))
            return

        if kind != 'events':
            return

        for item in envelope.get('events') or []:
            event_type = item.get('type')
            payload = item.get('payload')
            if event_type == 'bridge_loaded':
                self._bridge_loaded = True
                self._agent_ready = False
                self._flush_queued(internal_only=True)
            elif event_type == 'ready':
                self._bridge_loaded = True
                self._agent_ready = True
                self._flush_queued()
            self._fire(event_type, payload)


# --------------------------------------------------------------------------- #
#  Per-service registry - one engine per service, shared by every client window
# --------------------------------------------------------------------------- #
_bridges: Dict[str, WebBridge] = {}


def get_bridge(service: str) -> Optional[WebBridge]:
    return _bridges.get(service)


def register_bridge(service: str, bridge: WebBridge) -> None:
    _bridges[service] = bridge


def drop_bridge(service: str) -> None:
    _bridges.pop(service, None)


# The profile and keep-alive settings have to be in place before *any* WebView2
# is created in this process - including the legacy visible windows, which are
# imported by src/ui/gui.py at startup. Doing it at import time is the only
# ordering that holds for every entry point (GUI, Klango mode, launcher).
ensure_webview2_environment()
