# -*- coding: utf-8 -*-
"""Titan Access's NVDA controller bridge, on the real helper DLL.

Reported as "it detects in 64-bit applications and not in 32-bit ones". The
RPC endpoint was never the fault - a 32-bit nvdaControllerClient32.dll reaches
it fine. Tolk (what audio games ship) does FindWindowW("wxWindowClassNR",
"NVDA") before it asks the controller anything, and Titan Access had no such
window, so the game said "no screen reader" and never called. These tests use
the real helper and the real probes, and skip when another screen reader
already owns the endpoint (they would test that reader, not this one).

Run directly with the Windows Python.
"""
import ctypes
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENT = os.path.join(ROOT, "data", "components", "titan access")
sys.path.insert(0, COMPONENT)

if sys.platform.startswith("win"):
    from titan_access import nvda_controller_server as ncs
else:  # pragma: no cover
    ncs = None


class _Settings:
    def get_bool(self, section, key, default=False):
        return default


class _Engine:
    def __init__(self):
        self.settings = _Settings()
        self.speech = None
        self.spoken = []

    def speak(self, text, interrupt=True):
        self.spoken.append(text)


def _find_nvda_window():
    return ctypes.windll.user32.FindWindowW("wxWindowClassNR", "NVDA")


@unittest.skipUnless(ncs is not None, "Windows only")
class TheBridgeAnswersBothBitnesses(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if _find_nvda_window():
            raise unittest.SkipTest("another screen reader is running")
        cls.engine = _Engine()
        cls.server = ncs.NvdaControllerServer(cls.engine).start()
        if not cls.server.owns_endpoint:
            cls.server.stop()
            raise unittest.SkipTest("the controller endpoint is owned elsewhere")

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def test_the_nvda_window_tolk_looks_for_is_there(self):
        self.assertTrue(self.server.has_nvda_window())
        hwnd = _find_nvda_window()
        self.assertTrue(hwnd)
        self.assertFalse(ctypes.windll.user32.IsWindowVisible(hwnd))

    def test_a_32_bit_and_a_64_bit_client_reach_titan_access(self):
        results = self.server.self_test()
        self.assertEqual(sorted(b for b, ok, _d in results if ok), [32, 64],
                         results)

    def test_a_braille_message_is_not_spoken_again(self):
        before = list(self.engine.spoken)
        self.server._on_braille("only for the display")
        self.assertEqual(self.engine.spoken, before)


@unittest.skipUnless(ncs is not None, "Windows only")
class TheWindowGoesWithTheBridge(unittest.TestCase):

    def test_stopping_takes_the_window_away(self):
        for _ in range(20):     # an earlier bridge's window closes a moment late
            if not _find_nvda_window():
                break
            time.sleep(0.05)
        if _find_nvda_window():
            self.skipTest("another screen reader is running")
        server = ncs.NvdaControllerServer(_Engine()).start()
        if not server.owns_endpoint:
            server.stop()
            self.skipTest("the controller endpoint is owned elsewhere")
        self.assertTrue(_find_nvda_window())
        server.stop()
        for _ in range(20):
            if not _find_nvda_window():
                break
            time.sleep(0.05)
        self.assertFalse(_find_nvda_window())


if __name__ == "__main__":
    unittest.main()
