# -*- coding: utf-8 -*-
"""Titan Access reads the screen by itself.

Its OCR used to be asked of TITAN (``ocr.read_windows`` on the typed
doorway), and a compiled Titan freezes that doorway while this component
is data beside it - so a newer reader in an older Titan answered every
"read this window" with "this Titan has no bridge call". Nothing here
may depend on Titan's own OCR modules, NVDA or the NVDA add-on.

Run directly: ``python tests/test_titan_access_own_ocr.py``.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENT = os.path.join(ROOT, 'data', 'components', 'titan access')
for path in (ROOT, COMPONENT):
    if path not in sys.path:
        sys.path.insert(0, path)

from titan_access import local_model, windows_ocr          # noqa: E402
from titan_access.portable import link as link_module      # noqa: E402
from titan_access.portable import readerApi                # noqa: E402


class TheReaderAnswersItsOwnOcrCalls(unittest.TestCase):

    def setUp(self):
        self.keep = (windows_ocr.call_read_windows, windows_ocr.call_windows,
                     local_model.call_read_local, local_model.call_model,
                     local_model.call_install)
        self.bridged = []
        import src.titan_core.bridge_api as bridge_api
        self.bridge_api = bridge_api
        self.keep_bridge = bridge_api.bridge
        bridge_api.bridge = lambda *a, **k: self.bridged.append(a) or \
            '{"ok": false, "error": "this Titan has no bridge call"}'

    def tearDown(self):
        (windows_ocr.call_read_windows, windows_ocr.call_windows,
         local_model.call_read_local, local_model.call_model,
         local_model.call_install) = self.keep
        self.bridge_api.bridge = self.keep_bridge

    def test_every_ocr_call_is_answered_without_titan(self):
        windows_ocr.call_read_windows = lambda args: {'ok': True,
                                                      'lines': [], 'h': args}
        windows_ocr.call_windows = lambda args: {'ok': True}
        local_model.call_read_local = lambda args: {'ok': True, 'lines': []}
        local_model.call_model = lambda args: {'installed': True}
        local_model.call_install = lambda args: {'ok': True}
        for call in ('ocr.read_windows', 'ocr.windows', 'ocr.read_local',
                     'ocr.model', 'ocr.install_model'):
            ok, data = link_module.LINK.bridge(call, hwnd=5)
            self.assertTrue(ok, call)
            self.assertIsInstance(data, dict)
        self.assertEqual(self.bridged, [])

    def test_a_failure_says_why_rather_than_raising(self):
        def boom(args):
            raise RuntimeError('no PowerShell')
        windows_ocr.call_read_windows = boom
        ok, why = link_module.LINK.bridge('ocr.read_windows', hwnd=5)
        self.assertFalse(ok)
        self.assertIn('no PowerShell', why)
        self.assertEqual(self.bridged, [])

    def test_other_calls_still_go_to_titan(self):
        link_module.LINK.bridge('apps.list')
        self.assertEqual(len(self.bridged), 1)


class TheModulesNeedNothingOfTitansOcr(unittest.TestCase):

    def test_no_import_of_titans_ocr_or_the_addon(self):
        for name in ('windows_ocr.py', 'local_model.py', 'ocr_assist.py'):
            with open(os.path.join(COMPONENT, 'titan_access', name),
                      encoding='utf-8') as handle:
                source = handle.read()
            # Linux keeps Titan's capture as a LAST resort (a Wayland
            # screenshot tool); nothing else may reach Titan's OCR.
            if name == 'ocr_assist.py':
                # The AI tier is Titan's AI on purpose; the LOCAL tier is
                # the reader's own.
                source = source[source.index('def local_lines('):
                                source.index('def local_nodes(')]
            if name == 'local_model.py':
                source = source.replace(source[source.index(
                    '    if picture is None:\n        try:'):source.index(
                    'def _x_picture(')], '')
            self.assertNotIn('from src.ai.ocr', source, name)
            self.assertNotIn('import contentRecog', source, name)

    def test_the_png_is_a_png(self):
        import struct
        import zlib
        data = windows_ocr.encode_png(2, 1, bytes([0, 0, 255, 255,
                                                   255, 0, 0, 255]))
        self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))
        width, height = struct.unpack('>II', data[16:24])
        self.assertEqual((width, height), (2, 1))
        start = data.index(b'IDAT') + 4
        length = struct.unpack('>I', data[start - 8:start - 4])[0]
        raw = zlib.decompress(data[start:start + length])
        # filter byte, then red, then blue: BGRA turned into RGB.
        self.assertEqual(raw, b'\x00' + bytes([255, 0, 0, 0, 0, 255]))

    def test_a_flat_picture_is_flat_and_a_mostly_flat_one_is_not(self):
        flat = bytes([10, 20, 30, 255]) * 5000
        self.assertTrue(windows_ocr._flat(flat))
        mostly = bytearray(flat)
        mostly[4 * 4000:4 * 4000 + 3] = b'\xff\xff\xff'
        self.assertFalse(windows_ocr._flat(bytes(mostly)))

    def test_the_libraries_live_in_the_component(self):
        self.assertTrue(local_model.library_folder().startswith(COMPONENT))
        self.assertIn('cp%d%d' % sys.version_info[:2],
                      local_model.library_folder())

    def test_a_model_that_is_not_installed_says_so(self):
        keep = local_model.available
        local_model.available = lambda: (False, 'not installed')
        try:
            found = local_model.read_window(0)
        finally:
            local_model.available = keep
        self.assertFalse(found['ok'])
        self.assertEqual(found['text'], 'not installed')


class TheSharedModulesDoNotNeedNvda(unittest.TestCase):
    """What used to answer 'this NVDA has no ...' in Titan Access."""

    def test_the_seam_lists_windows_without_nvda(self):
        keep = readerApi.hooks
        readerApi.hooks = type('H', (), {
            'top_windows': lambda self: ['a', 'b']})()
        try:
            self.assertEqual(readerApi.top_windows(), ['a', 'b'])
        finally:
            readerApi.hooks = keep

    def test_a_click_has_a_pointer_without_winuser(self):
        from titan_access.portable import virtualWindow
        found = virtualWindow._win_user()
        for name in ('getCursorPos', 'setCursorPos', 'mouse_event',
                     'MOUSEEVENTF_LEFTDOWN', 'MOUSEEVENTF_LEFTUP'):
            self.assertTrue(hasattr(found, name), name)

    def test_a_window_picture_does_not_ask_for_screenbitmap(self):
        path = os.path.join(COMPONENT, 'titan_access', 'portable',
                            'localOcr.py')
        with open(path, encoding='utf-8') as handle:
            source = handle.read()
        body = source[source.index('def from_window('):
                      source.index('def _inside_window(')]
        self.assertNotIn('import screenBitmap', body)

    def test_no_shared_module_imports_nvdas_api_where_the_seam_answers(self):
        folder = os.path.join(COMPONENT, 'titan_access', 'portable')
        for name in ('findControl.py', 'journal.py', 'surface.py',
                     'windowsAndActions.py'):
            with open(os.path.join(folder, name), encoding='utf-8') as handle:
                self.assertNotIn('import api\n', handle.read(), name)


if __name__ == '__main__':
    unittest.main()
