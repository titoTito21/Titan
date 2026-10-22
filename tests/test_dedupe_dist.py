# -*- coding: utf-8 -*-
"""
No file twice in a compiled Titan.

Run it directly:  python tests/test_dedupe_dist.py

The build of 2026-10-16 shipped 35 binaries twice (19.6 MB): every stdlib
extension in both _internal/ and _internal/DLLs/, pygame's SDL DLLs at the top
of _internal/ beside its own folder, tMedia's libvlc in _internal/ although
tMedia loads it by full path from its own folder. `src/scripts/dedupe_dist.py`
removes the copy that nothing reaches; these build a small fake compiled tree
- with real PE import tables, because who imports a DLL is what decides which
copy is dead - and check that it removes the right one and nothing else.
"""

import os
import shutil
import struct
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'src', 'scripts'))

import dedupe_dist  # noqa: E402


def pe(imports=(), filler=b''):
    """A minimal PE32+ file whose import table names `imports`."""
    sect_rva, sect_raw = 0x1000, 0x200
    body = bytearray()
    desc_size = 20 * (len(imports) + 1)
    names = bytearray()
    offsets = []
    for name in imports:
        offsets.append(desc_size + len(names))
        names += name.encode() + b'\0'
    for off in offsets:
        body += struct.pack('<IIIII', 0, 0, 0, sect_rva + off, 0)
    body += b'\0' * 20 + names + filler
    opt_size = 240
    head = bytearray(sect_raw)
    head[0:2] = b'MZ'
    struct.pack_into('<I', head, 0x3C, 0x40)
    head[0x40:0x44] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', head, 0x44, 0x8664, 1, 0, 0, 0, opt_size, 0x22)
    opt = 0x58
    struct.pack_into('<H', head, opt, 0x20B)
    struct.pack_into('<II', head, opt + 112 + 8, sect_rva if imports else 0,
                     len(body))
    sec = opt + opt_size
    head[sec:sec + 8] = b'.idata\0\0'
    struct.pack_into('<IIII', head, sec + 8, len(body), sect_rva, len(body),
                     sect_raw)
    return bytes(head + body)


class DedupeTests(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, '_internal'))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def put(self, rel, data):
        path = os.path.join(self.root, *rel.split('/'))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as fh:
            fh.write(data)

    def run_it(self):
        removed = dedupe_dist.dedupe(self.root, log=lambda *_: None)
        return sorted(dedupe_dist._rel(r[0], self.root) for r in removed)

    def exists(self, rel):
        return os.path.exists(os.path.join(self.root, *rel.split('/')))

    def test_pe_imports_are_read(self):
        self.put('_internal/a.dll', pe(['SDL2.dll', 'KERNEL32.dll']))
        self.assertEqual(
            dedupe_dist.pe_imports(os.path.join(self.root, '_internal', 'a.dll')),
            {'sdl2.dll', 'kernel32.dll'})

    def test_a_dlls_copy_shadowed_by_internal_goes(self):
        self.put('_internal/_ssl.pyd', pe(['libssl-3.dll'], b'ssl'))
        self.put('_internal/DLLs/_ssl.pyd', pe(['libssl-3.dll'], b'ssl'))
        self.assertEqual(self.run_it(), ['_internal/DLLs/_ssl.pyd'])
        self.assertTrue(self.exists('_internal/_ssl.pyd'))

    def test_a_packages_dll_at_the_top_goes_and_its_dependency_after(self):
        sdl = pe([], b'sdl2')
        mixer = pe(['SDL2.dll'], b'mixer')
        for folder in ('_internal', '_internal/pygame'):
            self.put(folder + '/SDL2.dll', sdl)
            self.put(folder + '/SDL2_mixer.dll', mixer)
        self.put('_internal/pygame/mixer.pyd', pe(['SDL2_mixer.dll', 'SDL2.dll']))
        self.put('_internal/pygame/_sdl2/audio.pyd', pe(['SDL2.dll']))
        self.assertEqual(self.run_it(),
                         ['_internal/SDL2.dll', '_internal/SDL2_mixer.dll'])
        self.assertTrue(self.exists('_internal/pygame/SDL2.dll'))

    def test_a_top_dll_something_at_the_top_imports_stays(self):
        opus = pe([], b'opus')
        self.put('_internal/libopus-0.dll', opus)
        self.put('_internal/pygame/libopus-0.dll', opus)
        self.put('_internal/libopusfile-0.dll', pe(['libopus-0.dll']))
        # The top copy is the one found; the package copy goes instead.
        self.assertEqual(self.run_it(), ['_internal/pygame/libopus-0.dll'])
        self.assertTrue(self.exists('_internal/libopus-0.dll'))

    def test_an_addons_private_library_leaves_internal(self):
        vlc = pe([], b'vlc')
        self.put('_internal/libvlc.dll', vlc)
        self.put('data/applications/tMedia/libvlc.dll', vlc)
        self.put('data/applications/tMedia/player.py',
                 b"LoadLibrary(os.path.join(d, 'libvlc.dll'))")
        self.assertEqual(self.run_it(), ['_internal/libvlc.dll'])
        self.assertTrue(self.exists('data/applications/tMedia/libvlc.dll'))

    def test_a_dll_named_by_other_code_is_kept(self):
        lib = pe([], b'lib')
        self.put('_internal/libthing.dll', lib)
        self.put('data/applications/a/libthing.dll', lib)
        self.put('data/applications/other/main.py', b"ctypes.CDLL('libthing.dll')")
        self.assertEqual(self.run_it(), [])

    def test_a_dll_named_as_a_constant_in_a_pyc_is_kept(self):
        lib = pe([], b'lib')
        self.put('_internal/libthing.dll', lib)
        self.put('data/applications/a/libthing.dll', lib)
        # marshal: 'z' (short ascii), the length, the bytes
        self.put('_internal/src/x.pyc', b'\x00\xe3z\x0clibthing.dll\x00')
        self.assertEqual(self.run_it(), [])

    def test_a_word_inside_other_text_is_not_a_name(self):
        lib = pe([], b'lib')
        self.put('_internal/freetype.dll', lib)
        self.put('_internal/pygame/freetype.dll', lib)
        self.put('data/gamepad/modes/x/lib/pil/ImageFont.py',
                 b'"""uses freetype to render"""\nfeatures = "freetype2"')
        self.assertEqual(self.run_it(), ['_internal/freetype.dll'])

    def test_this_scripts_own_documentation_names_nothing(self):
        lib = pe([], b'lib')
        self.put('_internal/libthing.dll', lib)
        self.put('data/applications/a/libthing.dll', lib)
        self.put('_internal/src/scripts/dedupe_dist.pyc', b'z\x0clibthing.dll')
        self.assertEqual(self.run_it(), ['_internal/libthing.dll'])

    def test_an_importer_anywhere_in_the_same_addon_counts(self):
        gmp = pe([], b'gmp')
        ruby = 'data/components/elten_bridge/ruby'
        self.put('_internal/libgmp-10.dll', gmp)
        self.put(ruby + '/bin/ruby_builtin_dlls/libgmp-10.dll', gmp)
        self.put(ruby + '/bin/x64-ucrt-ruby400.dll', pe(['libgmp-10.dll']))
        self.assertEqual(self.run_it(), ['_internal/libgmp-10.dll'])

    def test_a_dll_two_addons_each_need_stays_twice(self):
        ffi = pe([], b'ffi')
        self.put('_internal/libffi-8.dll', ffi)
        self.put('_internal/_ctypes.pyd', pe(['libffi-8.dll']))
        self.put('data/components/elten_bridge/ruby/bin/libffi-8.dll', ffi)
        self.put('data/components/elten_bridge/ruby/bin/fiddle.so.dll',
                 pe(['libffi-8.dll']))
        self.assertEqual(self.run_it(), [])

    def test_titan_net_opus_is_found_in_internal(self):
        opus = pe([], b'opus')
        self.put('_internal/libopus-0.dll', opus)
        self.put('_internal/libopusfile-0.dll', pe(['libopus-0.dll']))
        self.put('data/lib/libopus-0.dll', opus)
        self.assertEqual(self.run_it(), ['data/lib/libopus-0.dll'])
        with open(os.path.join(ROOT, 'src', 'network', 'voice_codec.py'),
                  encoding='utf-8') as fh:
            self.assertIn('sys._MEIPASS', fh.read())

    def test_same_bytes_under_another_name_is_another_file(self):
        opus = pe([], b'opus')
        self.put('_internal/libopus-0.dll', opus)
        self.put('_internal/opus.dll', opus)
        self.assertEqual(self.run_it(), [])

    def test_identical_assets_of_different_owners_stay(self):
        self.put('sfx/default/ui/tip.ogg', b'ogg')
        self.put('sfx/longhorn/ui/tip.ogg', b'ogg')
        self.assertEqual(self.run_it(), [])

    def test_a_binary_whose_imports_cannot_be_read_is_left_alone(self):
        self.put('_internal/libSDL2.so', b'ELF sdl')
        self.put('_internal/pygame/libSDL2.so', b'ELF sdl')
        self.assertEqual(self.run_it(), [])

    def test_the_old_csharp_reader_is_not_shipped(self):
        self.put('data/components/titan access/ScreenReader/TTS/espeak/ru_dict', b'd')
        self.put('data/titantts engines/espeak/espeak-ng-data/ru_dict', b'd')
        self.put('data/components/titan access/lib/x.dll', b'keep')
        self.run_it()
        self.assertFalse(self.exists('data/components/titan access/ScreenReader'))
        self.assertTrue(self.exists('data/titantts engines/espeak/espeak-ng-data/ru_dict'))
        self.assertTrue(self.exists('data/components/titan access/lib/x.dll'))

    def test_nothing_loads_the_old_csharp_reader(self):
        import re as _re
        hits = []
        for base in ('src', 'data', 'main.py'):
            for d, _, files in os.walk(os.path.join(ROOT, base)):
                if 'ScreenReader' in d.split(os.sep):
                    continue
                for f in files:
                    if f.endswith('.py'):
                        with open(os.path.join(d, f), encoding='utf-8', errors='replace') as fh:
                            for line in fh:
                                if 'ScreenReader' in line and _re.search(
                                        r"(join|Path|open|exists|isdir)\s*\(.*['\"]ScreenReader['\"/]", line):
                                    hits.append(os.path.join(d, f))
        self.assertEqual(hits, [])

    def test_the_keyhook_is_built_into_lib_only(self):
        helper = os.path.join(ROOT, 'data', 'components', 'titan access', 'helper', 'keyhook')
        self.assertFalse(os.path.exists(os.path.join(helper, 'titan_keyhook.dll')))
        with open(os.path.join(helper, 'build.bat'), encoding='utf-8') as fh:
            self.assertIn('move /y titan_keyhook.dll', fh.read())

    def test_the_build_runs_it(self):
        with open(os.path.join(ROOT, 'compiletorelease.py'), encoding='utf-8') as fh:
            text = fh.read()
        self.assertIn('dedupe_dist.dedupe(', text)
        self.assertIn('n.lower() in already', text)

    def test_the_source_tree_ships_no_second_opus(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, 'data', 'lib', 'opus.dll')))


if __name__ == '__main__':
    unittest.main()
