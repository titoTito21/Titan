"""The network is read from Windows' own APIs, and watched rather than polled.

``netsh wlan show interfaces`` - a console process, measured at 159 ms -
was run every five seconds for the status bar and every SECOND by the
network monitor, beside two psutil walks (33 ms); and its English words
were parsed, so a Windows in another language read "Unknown" for ever.
``src/system/wlan.py`` asks wlanapi (16 ms, no process, no language),
``src/system/net_events.py`` is told about address changes, and the
monitor sleeps until one of them wakes it.

Run directly: ``python tests/test_network_readers.py``.
"""
import os
import re
import subprocess
import sys
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.system import wlan, net_events  # noqa: E402
from src.system import notifications, system_monitor  # noqa: E402

IS_WINDOWS = sys.platform == 'win32'


def _netsh():
    """(state, ssid, signal) as netsh reports them, or None."""
    try:
        out = subprocess.check_output('netsh wlan show interfaces', shell=True,
                                      stderr=subprocess.DEVNULL)
    except Exception:
        return None
    text = out.decode('utf-8', errors='replace')
    state = ssid = signal = None
    for line in text.splitlines():
        if ':' not in line:
            continue
        key, _, value = line.partition(':')
        key, value = key.strip().lower(), value.strip()
        if key == 'state':
            state = value.lower()
        elif key == 'ssid':
            ssid = value
        elif key == 'signal':
            match = re.search(r'(\d+)%', value)
            signal = int(match.group(1)) if match else None
    return state, ssid, signal


@unittest.skipUnless(IS_WINDOWS, 'wlanapi is Windows')
class TheWlanApiAgreesWithNetsh(unittest.TestCase):

    def test_the_connection_is_the_one_netsh_reports(self):
        expected = _netsh()
        info = wlan.current_connection()
        if expected is None or expected[0] is None:
            self.skipTest('netsh reports no wireless interface here')
        self.assertIsNotNone(info, wlan.why_unavailable())
        self.assertEqual(info['state'], expected[0])
        if expected[0] == 'connected':
            self.assertEqual(info['ssid'], expected[1])
            self.assertIsNotNone(info['signal'])
            self.assertLessEqual(abs(info['signal'] - expected[2]), 15)

    def test_a_read_is_far_cheaper_than_a_process(self):
        if wlan.current_connection() is None:
            self.skipTest('no wireless interface here')
        started = time.perf_counter()
        for _ in range(10):
            wlan.current_connection()
        per_call = (time.perf_counter() - started) / 10
        self.assertLess(per_call, 0.08)

    def test_watching_registers_and_unregisters(self):
        if wlan.interfaces() is None:
            self.skipTest('no WLAN service here')
        wake = threading.Event()
        self.assertTrue(wlan.watch(wake.set))
        self.assertIsNotNone(wlan._watch_callback)
        wlan.unwatch()
        self.assertIsNone(wlan._watch_callback)

    def test_address_changes_can_be_waited_for(self):
        wake = threading.Event()
        watcher = net_events.AddressChange(wake)
        try:
            self.assertTrue(watcher.available)
        finally:
            watcher.close()
        self.assertFalse(watcher._thread.is_alive())


class TheStatusBarSpawnsNoProcess(unittest.TestCase):

    def setUp(self):
        self._saved = (notifications.subprocess.check_output,
                       wlan.current_connection, wlan.interfaces)

    def tearDown(self):
        (notifications.subprocess.check_output,
         wlan.current_connection, wlan.interfaces) = self._saved

    def _no_process(self, *args, **kwargs):
        raise AssertionError('a process was spawned')

    @unittest.skipUnless(IS_WINDOWS, 'the Windows branch')
    def test_a_connected_network_is_read_natively(self):
        notifications.subprocess.check_output = self._no_process
        wlan.current_connection = lambda: {
            'interface': 'x', 'state': 'connected', 'ssid': 'Home',
            'signal': 77, 'profile': 'Home'}
        text = notifications.get_network_status()
        self.assertIn('Home', text)
        self.assertIn('77%', text)

    @unittest.skipUnless(IS_WINDOWS, 'the Windows branch')
    def test_no_wireless_interface_is_said_natively(self):
        notifications.subprocess.check_output = self._no_process
        wlan.current_connection = lambda: None
        wlan.interfaces = lambda: []
        text = notifications.get_network_status()
        self.assertTrue(text)
        self.assertNotIn('Unknown', text)

    @unittest.skipUnless(IS_WINDOWS, 'the Windows branch')
    def test_netsh_is_still_the_floor(self):
        wlan.current_connection = lambda: None
        wlan.interfaces = lambda: None
        calls = []

        def fake_netsh(*args, **kwargs):
            calls.append(args)
            return b'    State                  : connected\n    SSID                   : Old\n    Signal                 : 50%\n'

        notifications.subprocess.check_output = fake_netsh
        text = notifications.get_network_status()
        self.assertEqual(len(calls), 1)
        self.assertIn('Old', text)


class TheNetworkMonitorIsWokenNotPolled(unittest.TestCase):

    def _monitor(self, wifi, ethernet):
        monitor = system_monitor.NetworkMonitor.__new__(system_monitor.NetworkMonitor)
        monitor.running = True
        monitor.previous_ssid = None
        monitor.previous_wifi_state = None
        monitor.previous_interfaces = set()
        monitor._get_wifi_status = lambda: wifi[0]
        monitor._get_active_ethernet = lambda: set(ethernet[0])
        monitor.events = []
        monitor.on_connecting = lambda: monitor.events.append('connecting')
        monitor.on_connected = lambda name: monitor.events.append(('connected', name))
        monitor.on_disconnected = lambda name: monitor.events.append(('disconnected', name))
        return monitor

    def test_a_connection_is_announced_once(self):
        wifi, eth = [('disconnected', None)], [set()]
        monitor = self._monitor(wifi, eth)
        monitor._check_once()
        wifi[0] = ('associating', None)
        monitor._check_once()
        wifi[0] = ('authenticating', None)
        monitor._check_once()
        wifi[0] = ('connected', 'Home')
        monitor._check_once()
        monitor._check_once()
        self.assertEqual(monitor.events, ['connecting', ('connected', 'Home')])

    def test_a_disconnection_names_the_old_network(self):
        wifi, eth = [('connected', 'Home')], [set()]
        monitor = self._monitor(wifi, eth)
        monitor.previous_ssid = 'Home'
        monitor.previous_wifi_state = 'connected'
        wifi[0] = ('disconnected', None)
        monitor._check_once()
        self.assertEqual(monitor.events, [('disconnected', 'Home')])

    def test_a_cable_is_an_interface_coming_and_going(self):
        wifi, eth = [(None, None)], [set()]
        monitor = self._monitor(wifi, eth)
        eth[0] = {'Ethernet'}
        monitor._check_once()
        eth[0] = set()
        monitor._check_once()
        self.assertEqual(monitor.events,
                         [('connected', 'Ethernet'), ('disconnected', 'Ethernet')])

    def test_a_reader_that_raises_does_not_end_the_monitor(self):
        monitor = self._monitor([('connected', 'Home')], [set()])
        monitor._get_active_ethernet = lambda: (_ for _ in ()).throw(RuntimeError('x'))
        monitor._check_once()  # must not raise

    def test_the_watched_poll_is_slow_and_stop_wakes_it(self):
        self.assertGreaterEqual(system_monitor.NetworkMonitor.WATCHED_POLL, 5.0)
        monitor = self._monitor([('connected', 'Home')], [set()])
        monitor._wake = threading.Event()
        started = time.perf_counter()
        worker = threading.Thread(target=lambda: monitor._wake.wait(5.0), daemon=True)
        worker.start()
        monitor.stop()
        worker.join(2.0)
        self.assertFalse(worker.is_alive())
        self.assertLess(time.perf_counter() - started, 1.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
