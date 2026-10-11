# -*- coding: utf-8 -*-
"""A new row at the end of a list in the app in front is read by itself.

A message arriving in the chat that is open in Unigram, a download added to
the Store's list, a new mail at the bottom of a folder: the row appears and
nothing moves the focus, so a reader that only speaks about the focus says
nothing. UWP apps announce it with no notification and no live region
(measured on Unigram) - the one signal there is, is UI Automation's
StructureChanged ChildAdded on the list.

What is said, and what is not:

* only in the window IN FRONT - the handler is registered on that window
  alone, and moved when the user changes window (a desktop-wide one would
  hear every browser's every repaint);
* only XAML (UWP / WinUI) lists, and only a ListItem / DataItem;
* only a row that lands at the END of its list and was not seen before -
  scrolling realises rows too, at either end, but those are rows seen
  once already or rows the user scrolled to;
* never within ``QUIET_AFTER_INPUT`` of the user's own key or mouse input:
  the rows that appear then are the ones they scrolled to, or the message
  they just sent;
* not while the handler is newly registered (``SETTLE_S``) - opening a
  window realises its rows.

The registration runs on a thread of its own (MTA, its own CUIAutomation8
client): UI Automation forbids adding or removing handlers from inside an
event callback, which is where a focus change is learnt about.
"""

import ctypes
import queue
import sys
import threading
import time

IS_WINDOWS = sys.platform.startswith('win')

STRUCTURE_CHANGED = 20002
CHILD_ADDED = 0
TREESCOPE_SUBTREE = 7
LIST_ITEM = 50007
DATA_ITEM = 50029
QUIET_AFTER_INPUT = 1.5
SETTLE_S = 1.0
XAML = ('XAML', 'DirectUI', 'WinUI', 'Microsoft.UI.Xaml')
CLSID_CUIAUTOMATION8 = '{e22ad333-b25f-460c-83d0-0581107395c9}'


def _last_input_age():
    """Seconds since the user last pressed a key or moved/used the mouse."""
    if not IS_WINDOWS:
        return 1e9

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [('cbSize', ctypes.c_uint), ('dwTime', ctypes.c_uint)]
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    try:
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 1e9
        now = ctypes.windll.kernel32.GetTickCount()
        return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:                                # noqa: BLE001
        return 1e9


class Decider(object):
    """The rules, apart from COM, so they can be tested."""

    def __init__(self, input_age=_last_input_age, clock=time.time,
                 frameworks=XAML):
        self.input_age = input_age
        self.frameworks = frameworks
        self.clock = clock
        self.since = clock()
        self.seen = set()
        self.last_text = ('', 0.0)
        self.counts = {'events': 0, 'said': 0, 'input': 0, 'settling': 0,
                       'not_last': 0, 'seen': 0, 'not_row': 0, 'repeat': 0}

    def reset(self):
        self.since = self.clock()
        self.seen.clear()

    def decide(self, key, control_type, framework, is_last, text):
        """The words to say for a row that appeared, or ''."""
        self.counts['events'] += 1
        if control_type not in (LIST_ITEM, DATA_ITEM) or framework not in self.frameworks:
            self.counts['not_row'] += 1
            return ''
        first_time = key not in self.seen
        self.seen.add(key)
        if len(self.seen) > 5000:
            self.seen.clear()
        if self.clock() - self.since < SETTLE_S:
            self.counts['settling'] += 1
            return ''
        if not first_time:
            self.counts['seen'] += 1
            return ''
        if self.input_age() < QUIET_AFTER_INPUT:
            self.counts['input'] += 1
            return ''
        if not is_last:
            self.counts['not_last'] += 1
            return ''
        from titan_access import uwp
        text = uwp.clean((text or '').strip())
        if not text:
            return ''
        now = self.clock()
        if text == self.last_text[0] and now - self.last_text[1] < 2.0:
            self.counts['repeat'] += 1
            return ''
        self.last_text = (text, now)
        self.counts['said'] += 1
        return text


class LiveLists(object):
    """Follows the window in front and says new rows of its lists."""

    def __init__(self, say, switched_on=None, muted=None):
        self._say = say
        self._switched_on = switched_on
        self._muted = muted
        self.decider = Decider()
        self._requests = queue.Queue()
        self._thread = None
        self._window = 0
        self.why_not = ''

    def report(self):
        out = dict(self.decider.counts)
        out['window'] = self._window
        out['why'] = self.why_not
        return out

    def start(self):
        if not IS_WINDOWS or self._thread is not None:
            return False
        try:
            # Importing comtypes is itself a CoInitializeEx into an STA - on
            # the thread that imports it first. Done here, so the listening
            # thread can still ask for the multi-threaded apartment (the
            # trap audio_devices.py documents).
            import comtypes                          # noqa: F401
            import comtypes.client                   # noqa: F401
        except Exception as e:                       # noqa: BLE001
            self.why_not = 'comtypes: %s' % e
            return False
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name='TitanAccessLiveLists')
        self._thread.start()
        return True

    def stop(self):
        self._requests.put(None)

    def follow(self, hwnd):
        """The focus is in ``hwnd``: listen to its top-level window."""
        if not IS_WINDOWS or not hwnd:
            return
        try:
            top = int(ctypes.windll.user32.GetAncestor(ctypes.c_void_p(hwnd), 2) or hwnd)
        except Exception:                            # noqa: BLE001
            top = hwnd
        if top != self._window:
            self._window = top
            self._requests.put(top)

    # -- the thread ------------------------------------------------------ #
    def _run(self):
        try:
            import comtypes
            import comtypes.client
            try:
                comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            except OSError:
                pass                                 # already initialised
            mod = comtypes.client.GetModule('UIAutomationCore.dll')
            client = comtypes.client.CreateObject(CLSID_CUIAUTOMATION8,
                                                  interface=mod.IUIAutomation)
            try:
                from titan_access import uwp
                uwp.limit_timeouts(client)
            except Exception:                        # noqa: BLE001
                pass
        except Exception as e:                       # noqa: BLE001
            self.why_not = 'no UI Automation client: %s' % e
            return
        handler_cls = self._handler_class(mod)
        request = client.CreateCacheRequest()
        for prop in (30005, 30003, 30024):           # name, control type, framework
            request.AddProperty(prop)
        current = None
        handler = None
        while True:
            hwnd = self._requests.get()
            while not self._requests.empty():        # only the latest window
                hwnd = self._requests.get()
            if current is not None and handler is not None:
                try:
                    client.RemoveStructureChangedEventHandler(current, handler)
                except Exception:                    # noqa: BLE001
                    pass
                current = handler = None
            if hwnd is None:
                return
            try:
                element = client.ElementFromHandle(hwnd)
                handler = handler_cls(self, client)
                client.AddStructureChangedEventHandler(
                    element, TREESCOPE_SUBTREE, request, handler)
                current = element
                self.decider.reset()
                self.why_not = ''
            except Exception as e:                   # noqa: BLE001
                self.why_not = 'cannot listen to window %s: %s' % (hwnd, e)
                current = handler = None

    def _handler_class(self, mod):
        import comtypes

        class _Handler(comtypes.COMObject):
            _com_interfaces_ = [mod.IUIAutomationStructureChangedEventHandler]

            def __init__(self, owner, client):
                super().__init__()
                self._owner = owner
                self._client = client

            def IUIAutomationStructureChangedEventHandler_HandleStructureChangedEvent(
                    self, this, sender, change, runtime_id):
                try:
                    if int(change) == CHILD_ADDED:
                        self._owner._added(self._client, sender)
                except Exception as e:               # never raise into COM
                    print(f"[TitanAccess] live list event: {e}")
                return 0
        return _Handler

    def _allowed(self):
        for ask, wanted in ((self._switched_on, True), (self._muted, False)):
            if ask is None:
                continue
            try:
                if bool(ask()) != wanted:
                    return False
            except Exception:                        # noqa: BLE001
                pass
        return True

    def _added(self, client, sender):
        if sender is None or not self._allowed():
            return
        try:
            ctype = int(sender.CachedControlType)
        except Exception:                            # noqa: BLE001
            ctype = 0
        if ctype not in (LIST_ITEM, DATA_ITEM):
            self.decider.counts['not_row'] += 1
            return
        try:
            framework = sender.CachedFrameworkId or ''
            name = sender.CachedName or ''
            key = tuple(sender.GetRuntimeId())
        except Exception:                            # noqa: BLE001
            return
        is_last = False
        try:
            walker = client.ControlViewWalker
            parent = walker.GetParentElement(sender)
            last = walker.GetLastChildElement(parent) if parent else None
            is_last = bool(last) and bool(client.CompareElements(last, sender))
        except Exception:                            # noqa: BLE001
            pass
        text = self.decider.decide(key, ctype, framework, is_last, name)
        if text:
            try:
                self._say(text)
            except Exception:                        # noqa: BLE001
                pass
