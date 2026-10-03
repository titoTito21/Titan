# -*- coding: utf-8 -*-
"""UI Automation notifications and live regions, said as they happen.

A program tells a reader that something happened without moving the
focus in two ways UI Automation defines:

* **a notification** (`UiaRaiseNotificationEvent`, `UIA_NotificationEventId`)
  - Windows 11's own "copied", "the file was moved", a chat's "new
  message", the volume flyout, an app's own status line. The event carries
  the text itself, a KIND (an item added, an action completed, ...) and
  how it wants to be treated (`NotificationProcessing`: whether it may
  interrupt what is being said, and whether an older one of the same
  activity is superseded by it);
* **a live region** (`UIA_LiveRegionChangedEventId`) - an element marked
  `aria-live` on the web, a status bar in a WinUI program - whose new
  text is the news.

Neither reaches a reader that listens only for the focus, which is where
Titan Access stood: a program could say something and nobody was told.
This module registers both with the SAME `IUIAutomation` client the focus
listener uses, on the same apartment, and hands the words to the engine's
speech queue - interrupting only when the program asked for that
(`ImportantAll`, `ImportantMostRecent`, `ImportantCurrentThenMostRecent`),
queued otherwise, and never twice for the same words inside a second.

`IUIAutomation5` is where notifications live (Windows 10 1709+); on an
older client only the live regions are registered and `report()` says so.
"""

import threading
import sys
import time

try:
    import comtypes
    import comtypes.client
    _COMTYPES_OK = True
except Exception as _e:                              # pragma: no cover
    comtypes = None
    _COMTYPES_OK = False

_S_OK = 0
_TREESCOPE_SUBTREE = 7
#: The class object that implements IUIAutomation5 (Windows 10 1709+).
CLSID_CUIAUTOMATION8 = '{E22AD333-B25F-460C-83D0-0581107395C9}'
_UIA_NAME_PROPERTY = 30005
_UIA_LIVE_REGION_CHANGED = 20024

#: The same words again inside this many seconds are the same news.
REPEAT_WINDOW = 1.0
#: One sender may have a notification spoken at most this often: a
#: console raises one per fragment of output, ten a second while a
#: spinner turns, each marked important - measured as the reader babbling
#: "?", "4", "*" with every fragment cutting off the last.
NOTIFY_MIN_GAP = 0.5
#: And may INTERRUPT at most this often, whatever it asks.
INTERRUPT_MIN_GAP = 2.0
#: Windows whose output is somebody else's business: the terminal module
#: reads a console's new text itself, properly, as lines.
TERMINAL_CLASSES = ('ConsoleWindowClass', 'CASCADIA_HOSTING_WINDOW_CLASS')
#: A live region that changes faster than this is read at most this often.
LIVE_MIN_GAP = 0.3

#: `NotificationProcessing` values that ask to interrupt.
IMPORTANT = frozenset((1, 3, 5))   # ImportantAll, ImportantMostRecent,
                                   # ImportantCurrentThenMostRecent
KINDS = {0: 'item_added', 1: 'item_removed', 2: 'action_completed',
         3: 'action_aborted', 4: 'other'}
PROCESSING = {0: 'important_all', 1: 'important_most_recent',
              2: 'important_current_then_most_recent', 3: 'all',
              4: 'most_recent', 5: 'current_then_most_recent'}
# (UIA numbers them: ImportantAll=0, ImportantMostRecent=1,
#  ImportantCurrentThenMostRecent=2, All=3, MostRecent=4,
#  CurrentThenMostRecent=5 - so the important ones are 0..2.)
IMPORTANT = frozenset((0, 1, 2))


def _text(value):
    try:
        return str(value or '').strip()
    except Exception:                                # noqa: BLE001
        return ''


def _make_handler_classes():
    """The two COM handler classes, bound to the generated interfaces.
    None when comtypes or the type library is not there."""
    if not _COMTYPES_OK:
        return None, None
    try:
        uia_mod = comtypes.client.GetModule("UIAutomationCore.dll")
    except Exception as e:                           # pragma: no cover
        print(f"[TitanAccess] uia_notifications: type library: {e}")
        return None, None

    class _NotificationHandler(comtypes.COMObject):
        _com_interfaces_ = [uia_mod.IUIAutomationNotificationEventHandler]

        def __init__(self, owner):
            super().__init__()
            self._owner = owner

        def IUIAutomationNotificationEventHandler_HandleNotificationEvent(
                self, this, sender, kind, processing, display_string,
                activity_id):
            try:
                self._owner.notification(sender, int(kind), int(processing),
                                         _text(display_string),
                                         _text(activity_id))
            except Exception as e:                   # never raise into COM
                print(f"[TitanAccess] notification event error: {e}")
            return _S_OK

    class _LiveRegionHandler(comtypes.COMObject):
        _com_interfaces_ = [uia_mod.IUIAutomationEventHandler]

        def __init__(self, owner):
            super().__init__()
            self._owner = owner

        def IUIAutomationEventHandler_HandleAutomationEvent(
                self, this, sender, event_id):
            try:
                if int(event_id) == _UIA_LIVE_REGION_CHANGED:
                    self._owner.live_region(sender)
            except Exception as e:                   # never raise into COM
                print(f"[TitanAccess] live region event error: {e}")
            return _S_OK

    return _NotificationHandler, _LiveRegionHandler


class UIANotifications(object):
    """The two listeners, on one client. `say(text, interrupt)` is what
    the words go to - the engine's queue in the reader, a list in a test."""

    def __init__(self, say, muted=None, switched_on=None):
        self._say = say
        self._muted = muted
        self._switched_on = switched_on
        self._lock = threading.RLock()
        self._client = None
        self._root = None
        self._notification_handler = None
        self._live_handler = None
        self._live_request = None
        self.notifications_on = False
        self.live_on = False
        self.why_not = ''
        self._last = {}            # text -> when it was last said
        self._live_last = {}       # runtime id -> (text, when)
        self._notify_last = {}     # runtime id -> (last said, last interrupt)
        self.counts = {'notifications': 0, 'live': 0, 'said': 0,
                       'repeated': 0, 'muted': 0, 'interrupted': 0,
                       'burst': 0, 'terminal': 0}

    # ------------------------------------------------------------ lifetime
    def start(self, client):
        """Register both handlers on ``client`` (an ``IUIAutomation``), on
        the thread that owns it. True when at least one is listening."""
        if client is None or not _COMTYPES_OK:
            self.why_not = 'no UI Automation client'
            return False
        notification_cls, live_cls = _make_handler_classes()
        if notification_cls is None:
            self.why_not = 'no UIAutomationCore type library'
            return False
        with self._lock:
            self._client = client
            try:
                self._root = client.GetRootElement()
            except Exception as e:                   # noqa: BLE001
                self.why_not = 'no root element: %s' % e
                return False
            uia_mod = comtypes.client.GetModule("UIAutomationCore.dll")
            # Notifications: IUIAutomation5, which only the CUIAutomation8
            # class object implements - a client made as plain
            # CUIAutomation (the vendored library's) answers "no such
            # interface", so one of its own is made here, on this thread.
            try:
                uia5 = self._client_with_notifications(client, uia_mod)
                self._notification_root = uia5.GetRootElement()
                self._notification_handler = notification_cls(self)
                uia5.AddNotificationEventHandler(
                    self._notification_root, _TREESCOPE_SUBTREE, None,
                    self._notification_handler)
                self._uia5 = uia5
                self.notifications_on = True
            except Exception as e:                   # noqa: BLE001
                self.notifications_on = False
                self.why_not = 'notifications: %s' % e
                self._notification_handler = None
            # Live regions: any IUIAutomation, with the name cached so the
            # event arrives with its words already in it.
            try:
                request = client.CreateCacheRequest()
                request.AddProperty(_UIA_NAME_PROPERTY)
                self._live_request = request
                self._live_handler = live_cls(self)
                client.AddAutomationEventHandler(
                    _UIA_LIVE_REGION_CHANGED, self._root, _TREESCOPE_SUBTREE,
                    request, self._live_handler)
                self.live_on = True
            except Exception as e:                   # noqa: BLE001
                self.live_on = False
                self.why_not = (self.why_not + '; ' if self.why_not else '') \
                    + 'live regions: %s' % e
                self._live_handler = None
        return self.notifications_on or self.live_on

    @staticmethod
    def _client_with_notifications(client, uia_mod):
        """An ``IUIAutomation5``: the client itself when it has it, else a
        CUIAutomation8 made here."""
        try:
            return client.QueryInterface(uia_mod.IUIAutomation5)
        except Exception:                            # noqa: BLE001
            pass
        made = comtypes.client.CreateObject(
            CLSID_CUIAUTOMATION8, interface=uia_mod.IUIAutomation)
        return made.QueryInterface(uia_mod.IUIAutomation5)

    def stop(self):
        with self._lock:
            client, root = self._client, self._root
            try:
                uia5 = getattr(self, '_uia5', None)
                if uia5 is not None and self._notification_handler is not None:
                    uia5.RemoveNotificationEventHandler(
                        getattr(self, '_notification_root', root),
                        self._notification_handler)
            except Exception:                        # noqa: BLE001
                pass
            try:
                if client is not None and self._live_handler is not None:
                    client.RemoveAutomationEventHandler(
                        _UIA_LIVE_REGION_CHANGED, root, self._live_handler)
            except Exception:                        # noqa: BLE001
                pass
            self._notification_handler = None
            self._live_handler = None
            self.notifications_on = self.live_on = False

    # ------------------------------------------------------------ the news
    def _allowed(self):
        if self._switched_on is not None:
            try:
                if not self._switched_on():
                    return False
            except Exception:                        # noqa: BLE001
                pass
        if self._muted is not None:
            try:
                if self._muted():
                    self.counts['muted'] += 1
                    return False
            except Exception:                        # noqa: BLE001
                pass
        return True

    def _repeated(self, text, now):
        with self._lock:
            when = self._last.get(text, 0.0)
            self._last[text] = now
            if len(self._last) > 64:
                oldest = min(self._last, key=self._last.get)
                self._last.pop(oldest, None)
        return now - when < REPEAT_WINDOW

    def _sender_key(self, sender, text):
        try:
            return ','.join(str(x) for x in (sender.GetRuntimeId() or ()))
        except Exception:                            # noqa: BLE001
            return text

    @staticmethod
    def _from_terminal(sender):
        """Whether the sender belongs to a console or terminal.

        By the PROCESS first - a console's text element has no window
        handle of its own, so the class of its window cannot be asked of
        it (measured: 47 notifications from conhost, none recognised by
        the window) - and by the window's class where there is one.
        """
        if not sys.platform.startswith('win'):
            return False
        pid = 0
        for ask in ('CachedProcessId', 'CurrentProcessId'):
            try:
                pid = int(getattr(sender, ask) or 0)
            except Exception:                        # noqa: BLE001
                pid = 0
            if pid:
                break
        if pid:
            try:
                from titan_access import nvda_shape
                from titan_access.app_modules.terminal import TerminalModule
                if nvda_shape.executable_of(pid) in TerminalModule.process_names:
                    return True
            except Exception:                        # noqa: BLE001
                pass
        try:
            import ctypes
            hwnd = 0
            for ask in ('CachedNativeWindowHandle', 'CurrentNativeWindowHandle'):
                try:
                    hwnd = int(getattr(sender, ask) or 0)
                except Exception:                    # noqa: BLE001
                    hwnd = 0
                if hwnd:
                    break
            if not hwnd:
                return False
            root = ctypes.windll.user32.GetAncestor(hwnd, 2) or hwnd
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetClassNameW(root, buf, 256)
            return buf.value in TERMINAL_CLASSES
        except Exception:                            # noqa: BLE001
            return False

    def _burst(self, key, now, interrupt):
        """Too soon after this sender's last one: dropped, and an
        interrupt too soon after its last interrupt is demoted."""
        with self._lock:
            last_said, last_cut = self._notify_last.get(key, (0.0, 0.0))
            if now - last_said < NOTIFY_MIN_GAP:
                return True, interrupt
            if interrupt and now - last_cut < INTERRUPT_MIN_GAP:
                interrupt = False
            self._notify_last[key] = (now, now if interrupt else last_cut)
            if len(self._notify_last) > 64:
                oldest = min(self._notify_last, key=lambda k: self._notify_last[k][0])
                self._notify_last.pop(oldest, None)
        return False, interrupt

    def notification(self, sender, kind, processing, text, activity):
        """One `UIA_NotificationEventId`, from any window."""
        self.counts['notifications'] += 1
        text = ' '.join(str(text or '').split())
        if not text or not self._allowed():
            return False
        if self._from_terminal(sender):
            self.counts['terminal'] += 1
            return False
        now = time.time()
        if self._repeated(text, now):
            self.counts['repeated'] += 1
            return False
        interrupt = int(processing) in IMPORTANT
        dropped, interrupt = self._burst(self._sender_key(sender, text), now, interrupt)
        if dropped:
            self.counts['burst'] += 1
            return False
        if interrupt:
            self.counts['interrupted'] += 1
        self.counts['said'] += 1
        try:
            self._say(text, interrupt)
        except Exception as e:                       # noqa: BLE001
            print(f"[TitanAccess] notification say error: {e}")
        return True

    def live_region(self, sender):
        """One `UIA_LiveRegionChangedEventId`: the element's new text."""
        self.counts['live'] += 1
        if not self._allowed():
            return False
        if self._from_terminal(sender):
            self.counts['terminal'] += 1
            return False
        text = ''
        key = ''
        try:
            text = _text(sender.CachedName)
        except Exception:                            # noqa: BLE001
            try:
                text = _text(sender.CurrentName)
            except Exception:                        # noqa: BLE001
                text = ''
        try:
            key = ','.join(str(x) for x in (sender.GetRuntimeId() or ()))
        except Exception:                            # noqa: BLE001
            key = text
        if not text:
            return False
        now = time.time()
        with self._lock:
            was, when = self._live_last.get(key, ('', 0.0))
            if was == text or now - when < LIVE_MIN_GAP:
                self._live_last[key] = (text, when if was == text else now)
                self.counts['repeated'] += 1
                return False
            self._live_last[key] = (text, now)
            if len(self._live_last) > 64:
                oldest = min(self._live_last, key=lambda k: self._live_last[k][1])
                self._live_last.pop(oldest, None)
        self.counts['said'] += 1
        try:
            self._say(text, False)
        except Exception as e:                       # noqa: BLE001
            print(f"[TitanAccess] live region say error: {e}")
        return True

    def report(self):
        found = dict(self.counts)
        found.update({'notifications_on': self.notifications_on,
                      'live_on': self.live_on, 'why_not': self.why_not})
        return found
