"""Titan's idle background work costs what it has to and no more.

Two monitors run for the life of the program, and both were measured
doing far more than their job needed:

* the volume monitor asked Windows for the default device, activated its
  volume interface and read it - 13 ms of COM - on a NEW thread, five
  times a second. Now one cached interface, read in 0.02 ms, with Windows'
  own change notification waking the loop and a slow safety poll;
* the process-sound monitor built a psutil.Process per pid (0.78 ms
  against 0.03 ms for the bare pid list) and walked every window ten
  times a second whether or not any new process was still expected to put
  one up.

Run directly: ``python tests/test_background_monitors.py``. Nothing here
touches the real audio endpoint or plays a sound.
"""
import os
import sys
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.system import system_monitor  # noqa: E402
from src.titan_core import tsounds  # noqa: E402


class _FakeEndpoint:
    def __init__(self, store):
        self.store = store
        self.registered = []
        self.reads = 0

    def GetMasterVolumeLevelScalar(self):
        self.reads += 1
        if self.store.get('broken'):
            raise OSError('the device went away')
        return self.store['level']

    def RegisterControlChangeNotify(self, callback):
        self.registered.append(callback)

    def UnregisterControlChangeNotify(self, callback):
        self.registered.remove(callback)


class _FakeDevice:
    def __init__(self, endpoint):
        self.EndpointVolume = endpoint


class _FakeAudioUtilities:
    def __init__(self, store):
        self.store = store
        self.enumerations = 0
        self.endpoints = []

    def GetSpeakers(self):
        self.enumerations += 1
        endpoint = _FakeEndpoint(self.store)
        self.endpoints.append(endpoint)
        return _FakeDevice(endpoint)


class TheVolumeMonitorReadsACachedEndpoint(unittest.TestCase):

    def setUp(self):
        self.store = {'level': 0.5}
        self.fake = _FakeAudioUtilities(self.store)
        self._saved = (getattr(system_monitor, 'AudioUtilities', None),
                       system_monitor.PYCAW_AVAILABLE)
        system_monitor.AudioUtilities = self.fake
        system_monitor.PYCAW_AVAILABLE = True
        self.monitor = system_monitor.AudioMonitor('none')
        self.monitor.com_initialized = True
        self.monitor._wake = threading.Event()
        self.monitor._endpoint = None
        self.monitor._endpoint_polls = 0
        self.monitor._callback = None
        self.announced = []
        self.monitor.announce_volume_change = self.announced.append

    def tearDown(self):
        system_monitor.AudioUtilities, system_monitor.PYCAW_AVAILABLE = self._saved

    def _poll(self, times=1):
        for _ in range(times):
            self.monitor.check_count += 1
            value = self.monitor.get_volume_percentage_safe()
            if value != -1:
                if self.monitor.previous_volume == -1:
                    self.monitor.previous_volume = value
                elif value != self.monitor.previous_volume:
                    self.monitor.announce_volume_change(value)
                    self.monitor.previous_volume = value
            yield value

    def test_the_device_is_enumerated_once_per_many_reads(self):
        values = list(self._poll(10))
        self.assertEqual(values, [50] * 10)
        self.assertEqual(self.fake.enumerations, 1)
        self.assertEqual(self.fake.endpoints[0].reads, 10)

    def test_the_default_device_is_asked_for_again_eventually(self):
        list(self._poll(system_monitor.AudioMonitor.REACQUIRE_EVERY + 2))
        self.assertEqual(self.fake.enumerations, 2)
        # The old endpoint's callback was taken off it before it was dropped.
        self.assertEqual(self.fake.endpoints[0].registered, [])

    def test_a_change_is_announced_from_the_cached_read(self):
        list(self._poll(2))
        self.store['level'] = 0.7
        list(self._poll(1))
        self.assertEqual(self.announced, [70])

    def test_a_device_that_went_away_is_forgotten_and_found_again(self):
        list(self._poll(2))
        self.store['broken'] = True
        self.assertEqual(list(self._poll(1)), [-1])
        self.assertIsNone(self.monitor._endpoint)
        self.store['broken'] = False
        self.assertEqual(list(self._poll(1)), [50])
        self.assertEqual(self.fake.enumerations, 2)

    def test_no_thread_is_started_per_read(self):
        before = threading.active_count()
        list(self._poll(20))
        self.assertEqual(threading.active_count(), before)

    def test_stop_wakes_the_loop(self):
        started = time.perf_counter()
        self.monitor.running = True

        def loop():
            self.monitor._wake.wait(5.0)

        worker = threading.Thread(target=loop, daemon=True)
        worker.start()
        self.monitor.stop()
        worker.join(2.0)
        self.assertFalse(worker.is_alive())
        self.assertLess(time.perf_counter() - started, 1.0)

    def test_the_safety_poll_is_slow(self):
        self.assertGreaterEqual(system_monitor.AudioMonitor.POLL_SECONDS, 0.5)


class TheProcessMonitorWalksWindowsOnlyWhenItMust(unittest.TestCase):

    def setUp(self):
        self.monitor = tsounds.SystemAudioFeedback.__new__(
            tsounds.SystemAudioFeedback)
        self.monitor.process_info = {}

    def test_nothing_watched_means_no_walk(self):
        self.assertFalse(self.monitor._waiting_for_a_window())

    def test_a_new_process_is_waited_for(self):
        self.monitor.process_info[1] = {
            'had_window': False, 'seen': time.time()}
        self.assertTrue(self.monitor._waiting_for_a_window())

    def test_a_process_with_its_window_is_not(self):
        self.monitor.process_info[1] = {
            'had_window': True, 'seen': time.time()}
        self.assertFalse(self.monitor._waiting_for_a_window())

    def test_a_background_process_is_given_up_on(self):
        self.monitor.process_info[1] = {
            'had_window': False,
            'seen': time.time() - tsounds.SystemAudioFeedback.WINDOW_WAIT - 1}
        self.assertFalse(self.monitor._waiting_for_a_window())
        self.assertTrue(self.monitor.process_info[1]['gave_up'])

    def test_the_pid_list_is_the_bare_one(self):
        import inspect
        source = inspect.getsource(tsounds.SystemAudioFeedback._get_current_pids)
        code = '\n'.join(line for line in source.splitlines()
                         if not line.strip().startswith('#'))
        self.assertIn('psutil.pids()', code)
        self.assertNotIn('process_iter', code)


if __name__ == '__main__':
    unittest.main(verbosity=2)
