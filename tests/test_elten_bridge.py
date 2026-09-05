# -*- coding: utf-8 -*-
"""The Elten API bridge: the package format, the confinement, and the wire.

Run it directly (`python tests/test_elten_bridge.py`) - `tests/` has no
`__init__.py`.

Nothing here opens a window, plays a sound, speaks or reaches the network.
The applications under test are BUILT here, byte for byte in the real
`.eltenapp` layout, so the tests do not depend on the machine having Elten
installed - and the ones that do need the user's own applications skip
themselves rather than failing on a machine without them.

The Ruby half is exercised with the interpreter the component carries, so
"the bridge works" means the real thing really ran, not that a double
agreed with another double.
"""

import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
COMPONENT = os.path.join(ROOT, 'data', 'components', 'elten_bridge')
if COMPONENT not in sys.path:
    sys.path.insert(0, COMPONENT)

from eltenkit import (bridge, catalogue, host, launcher,   # noqa: E402
                      package, runtime)

try:
    from compression import zstd
except ImportError:                                        # pragma: no cover
    zstd = None


# --------------------------------------------------------------------------- #
# Building a real `.eltenapp`, so the tests do not need Elten installed
# --------------------------------------------------------------------------- #
def build_package(path, manifest, files=(), assets=(), catalogues=(),
                  signed=True):
    """One `.eltenapp`, in exactly the layout the real ones have."""
    body = bytearray()
    for name, text in files:
        raw = text.encode('utf-8') if isinstance(text, str) else text
        blob = zstd.compress(raw)
        body.append(package.SOURCE)
        body += struct.pack('<H', len(name.encode('utf-8')))
        body += name.encode('utf-8')
        body += struct.pack('<I', len(blob))
        body += blob
    for name, raw in assets:
        body.append(package.ASSET)
        body += struct.pack('<H', len(name.encode('utf-8')))
        body += name.encode('utf-8')
        body += struct.pack('<I', len(raw))
        body += raw
    for code, raw in catalogues:
        blob = zstd.compress(raw)
        body.append(package.CATALOGUE)
        body += code.encode('ascii')[:2].ljust(2, b'?')
        body += struct.pack('<I', len(blob))
        body += blob

    payload = json.dumps(manifest, ensure_ascii=False).encode('utf-8')
    manifest_blob = zstd.compress(payload)
    out = bytearray()
    if signed:
        certificate = b'\x30\x82\x00\x10' + b'\x0c\x05Elten' + b'\x00' * 8
        signature = b'\xAA' * 32
        out += package.SIGNATURE_MAGIC
        out += bytes([1, 1])
        out += struct.pack('<II', len(certificate), len(signature))
        out += certificate
        out += signature
    out += package.PAYLOAD_MAGIC
    out += struct.pack('<I', len(manifest_blob))
    out += manifest_blob
    out += body
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as handle:
        handle.write(bytes(out))
    return path


MANIFEST = {
    'id': '11111111-2222-3333-4444-555555555555',
    'name': 'Test application',
    'version': '1.0',
    'build_id': 20260101001,
    'EltenAPIVersion': '3.0.1',
    'author': 'the tests',
    'main': '__app.rb',
    'main_class': 'ProgramTest',
    'platforms': ['all'],
    'description': 'An application built by the tests',
}


@unittest.skipIf(zstd is None, 'this build has no zstd')
class ThePackageFormat(unittest.TestCase):
    """`.eltenapp` - worked out from the bytes, so it is tested that way."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='elten-pkg-')

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def build(self, **fields):
        path = os.path.join(self.root, 'test.eltenapp')
        return build_package(path, MANIFEST, **fields)

    def test_a_manifest_is_read_without_reading_the_sounds(self):
        """A listing wants a name, not two megabytes of audio."""
        path = self.build(files=[('__app.rb', 'x')],
                          assets=[('Audio/big.ogg', b'\x00' * 4096)])
        manifest, signature = package.read_manifest(path)
        self.assertEqual(manifest['name'], 'Test application')
        self.assertTrue(signature.signed)

    def test_source_is_compressed_and_an_asset_is_not(self):
        """The trap that made four of the eleven installed applications come
        back with no files at all: an asset is stored raw, because it is
        already an ogg or an mp3, and running zstd over it fails."""
        audio = b'OggS\x00\x02' + bytes(range(256)) * 4
        path = self.build(files=[('__app.rb', 'puts 1')],
                          assets=[('Audio/fire.ogg', audio)])
        opened = package.read(path)
        self.assertEqual(opened.file('__app.rb'), b'puts 1')
        self.assertEqual(opened.file('Audio/fire.ogg'), audio)

    def test_a_catalogue_is_named_by_two_bytes_of_language(self):
        path = self.build(files=[('__app.rb', 'x')],
                          catalogues=[('PL', b'\xde\x12\x04\x95rest')])
        opened = package.read(path)
        self.assertEqual(opened.languages(), ['pl'])
        self.assertTrue(opened.catalogues['pl'].startswith(b'\xde\x12\x04\x95'))

    def test_an_unsigned_package_still_opens(self):
        """Elten's own builder makes them (`--unsigned`), and the user may
        well be the author. Refusing to open somebody's own application over
        a signature Titan was never going to trust would be theatre."""
        path = self.build(files=[('__app.rb', 'x')], signed=False)
        opened = package.read(path)
        self.assertEqual(opened.name, 'Test application')
        self.assertFalse(opened.signature.signed)

    def test_the_signer_is_readable(self):
        path = self.build(files=[('__app.rb', 'x')])
        opened = package.read(path)
        self.assertIn('Elten', opened.signature.subject())
        self.assertEqual(len(opened.signature.fingerprint), 64)

    def test_something_that_is_not_a_package_says_so(self):
        path = os.path.join(self.root, 'not.eltenapp')
        with open(path, 'wb') as handle:
            handle.write(b'just a file')
        self.assertFalse(package.looks_like_package(path))
        with self.assertRaises(package.PackageError):
            package.read(path)

    def test_a_truncated_package_gives_back_what_it_can(self):
        """A half-finished download must not lose the whole listing."""
        path = self.build(files=[('__app.rb', 'x'), ('lib/two.rb', 'y')])
        with open(path, 'rb') as handle:
            data = handle.read()
        with open(path, 'wb') as handle:
            handle.write(data[:-10])
        opened = package.read(path)
        self.assertEqual(opened.name, 'Test application')
        self.assertEqual(opened.file('__app.rb'), b'x')

    def test_extract_writes_the_files_and_the_catalogues(self):
        path = self.build(files=[('__app.rb', 'x'), ('lib/deep/three.rb', 'z')],
                          catalogues=[('PL', b'catalogue')])
        folder = os.path.join(self.root, 'out')
        package.extract(path, folder)
        self.assertTrue(os.path.isfile(os.path.join(folder, '__app.rb')))
        self.assertTrue(os.path.isfile(os.path.join(folder, 'lib', 'deep',
                                                    'three.rb')))
        self.assertTrue(os.path.isfile(os.path.join(folder, 'locale', 'pl.mo')))

    def test_a_name_that_climbs_out_is_not_written(self):
        """A package comes from wherever the user got it. A file called
        `../../elten.ini` must land nowhere at all."""
        path = os.path.join(self.root, 'evil.eltenapp')
        build_package(path, MANIFEST,
                      files=[('../../escaped.rb', 'pwned'), ('__app.rb', 'x')])
        folder = os.path.join(self.root, 'out2')
        package.extract(path, folder)
        self.assertTrue(os.path.isfile(os.path.join(folder, '__app.rb')))
        self.assertFalse(os.path.exists(os.path.join(self.root, 'escaped.rb')))


class PathsAreConfined(unittest.TestCase):
    """An application has three directories and no way out of them.

    This is the security boundary that matters most: an `.eltenapp` is
    somebody else's code running with the user's privileges, and the one
    thing the bridge can genuinely promise is that it cannot name a file
    outside its own roots.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='elten-paths-')
        self.paths = host.Paths(os.path.join(self.root, 'asset'),
                                os.path.join(self.root, 'data'),
                                os.path.join(self.root, 'cache'))
        for kind in ('asset', 'data', 'cache'):
            self.paths.ensure(kind)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_an_ordinary_name_resolves(self):
        full = self.paths.resolve('data', 'save.json')
        self.assertTrue(full.endswith('save.json'))
        self.assertTrue(full.startswith(os.path.realpath(
            os.path.join(self.root, 'data'))))

    def test_a_nested_name_resolves(self):
        full = self.paths.resolve('data', 'games/one/save.json')
        self.assertIn('save.json', full)

    def test_climbing_out_is_refused(self):
        for name in ('../secret', '../../elten.ini', 'a/../../../out',
                     'a/b/../../../../out'):
            with self.subTest(name=name):
                with self.assertRaises(host.PathRefused):
                    self.paths.resolve('data', name)

    def test_an_absolute_path_is_refused(self):
        for name in ('/etc/passwd', r'C:\Windows\system.ini', '\\\\server\\x'):
            with self.subTest(name=name):
                with self.assertRaises(host.PathRefused):
                    self.paths.resolve('data', name)

    def test_a_kind_that_does_not_exist_is_refused(self):
        with self.assertRaises(host.PathRefused):
            self.paths.resolve('elsewhere', 'x')

    def test_a_link_out_is_refused_too(self):
        """`..` is only the obvious way out. The check is after `realpath`
        precisely so a link, a junction or a name that normalises to
        something else is caught as well."""
        outside = os.path.join(self.root, 'outside')
        os.makedirs(outside, exist_ok=True)
        link = os.path.join(self.root, 'data', 'link')
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest('this machine will not make symbolic links')
        with self.assertRaises(host.PathRefused):
            self.paths.resolve('data', 'link/secret')


class WhatReachesAWidget(unittest.TestCase):
    """Nothing an application sends is trusted to be what it claims."""

    def test_text_is_capped_and_control_characters_are_dropped(self):
        self.assertEqual(host._text('a\x00b\x07c'), 'abc')
        self.assertEqual(host._text('a\nb\tc'), 'a\nb\tc')
        self.assertEqual(len(host._text('x' * (host.MAX_TEXT + 500))),
                         host.MAX_TEXT)

    def test_a_label_is_capped_harder_than_a_sentence(self):
        self.assertEqual(len(host._label('x' * 5000)), host.MAX_LABEL)

    def test_text_survives_something_that_is_not_a_string(self):
        self.assertEqual(host._text(7), '7')
        self.assertEqual(host._text(None), '')

    def test_a_number_that_is_not_one_is_clamped(self):
        self.assertEqual(host._clamp('nonsense', 0.0, 1.0), 0.0)
        self.assertEqual(host._clamp(float('nan'), 0.0, 1.0), 0.0)
        self.assertEqual(host._clamp(50, 0.0, 1.0), 1.0)
        self.assertEqual(host._clamp(-50, 0.0, 1.0), 0.0)

    def test_a_handle_that_is_not_one_is_not_a_handle(self):
        self.assertEqual(host._handle('../../etc'), -1)
        self.assertEqual(host._handle(None), -1)
        self.assertEqual(host._handle('7'), 7)


class SoundsAreBounded(unittest.TestCase):
    """An application's leak must not become Titan's."""

    class Mixer(host.Mixer):
        def _sound_module(self):
            return None

        def _spatial_module(self):
            return None

        def _pygame_mixer(self):
            return None

        def _mode(self):
            return 'none'

        def start(self, path, pan=0.0, gain=1.0, loop=False,
                  elevation=0.0):
            self.played.append((os.path.basename(path or ''), pan, gain))
            return object()

        def busy(self, handle):
            return True

        def stop(self, handle):
            pass

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='elten-snd-')
        self.file = os.path.join(self.root, 'a.ogg')
        with open(self.file, 'wb') as handle:
            handle.write(b'x')
        self.sounds = host.Sounds(self.Mixer())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_a_handle_the_application_invented_reaches_nothing(self):
        self.assertFalse(self.sounds.play(999))
        self.assertFalse(self.sounds.stop(999))
        self.assertFalse(self.sounds.playing(999))
        self.assertFalse(self.sounds.set_volume(999, 1.0))

    def test_only_so_many_may_be_held_at_once(self):
        made = [self.sounds.create(self.file) for _ in range(host.MAX_SOUNDS + 10)]
        self.assertEqual(sum(1 for handle in made if handle is not None),
                         host.MAX_SOUNDS)

    def test_the_pool_has_a_ceiling(self):
        for _each in range(30):
            self.sounds.pool_play(self.file, max_voices=4)
        self.assertLessEqual(len(self.sounds._pool), 4)

    def test_closing_stops_everything_and_refuses_more(self):
        handle = self.sounds.create(self.file)
        self.sounds.play(handle)
        self.sounds.close()
        self.assertIsNone(self.sounds.create(self.file))
        self.assertIsNone(self.sounds.pool_play(self.file))


class TheWire(unittest.TestCase):
    """Framing, and the rule that every call is answered exactly once."""

    def test_lines_are_split_on_newlines(self):
        import io as _io
        stream = _io.BytesIO(b'{"a":1}\n{"b":2}\n')
        self.assertEqual(list(bridge._lines(stream)), [b'{"a":1}', b'{"b":2}'])

    def test_a_line_longer_than_the_cap_ends_it(self):
        """A runaway application must not make Titan buffer without bound."""
        import io as _io
        stream = _io.BytesIO(b'x' * (bridge.MAX_LINE + 1024))
        answers = list(bridge._lines(stream))
        self.assertIn(bridge._TOO_LONG, answers)

    def test_a_last_line_with_no_newline_still_arrives(self):
        import io as _io
        stream = _io.BytesIO(b'{"a":1}')
        self.assertEqual(list(bridge._lines(stream)), [b'{"a":1}'])


class TheDispatchTable(unittest.TestCase):
    """What is not in the table cannot be reached, and always answers."""

    class Recorder(bridge.Application):
        def __init__(self):
            entry = catalogue.Application('x.eltenapp', dict(MANIFEST), None,
                                          'test')
            entry.localise('en')
            root = tempfile.mkdtemp(prefix='elten-disp-')
            paths = host.Paths(os.path.join(root, 'a'),
                               os.path.join(root, 'd'),
                               os.path.join(root, 'c'))
            for kind in ('asset', 'data', 'cache'):
                paths.ensure(kind)
            bridge.Application.__init__(self, entry, paths,
                                        speaker=_SilentSpeaker(),
                                        sounds=host.Sounds(_NoMixer()),
                                        ui=None)
            self.written = []

        def _write(self, message):
            self.written.append(message)
            return True

    def setUp(self):
        self.app = self.Recorder()

    def test_an_operation_that_does_not_exist_is_answered_not_ignored(self):
        """An application written against a newer Elten must find out, not
        hang on a reply that is never coming."""
        self.app._handle({'id': 1, 'op': 'conference_join', 'args': {}})
        self.assertEqual(len(self.app.written), 1)
        answer = self.app.written[0]
        self.assertEqual(answer['id'], 1)
        self.assertFalse(answer['ok'])
        self.assertEqual(answer['kind'], 'unknown')
        self.assertIn('conference_join', answer['error'])

    def test_a_handler_that_raises_still_answers(self):
        def explode(app, args):
            raise RuntimeError('boom')
        bridge.OPERATIONS['__explode'] = explode
        try:
            self.app._handle({'id': 2, 'op': '__explode', 'args': {}})
        finally:
            del bridge.OPERATIONS['__explode']
        self.assertEqual(len(self.app.written), 1)
        self.assertFalse(self.app.written[0]['ok'])
        self.assertIn('boom', self.app.written[0]['error'])

    def test_a_refused_path_comes_back_as_a_refusal(self):
        self.app._handle({'id': 3, 'op': 'path',
                          'args': {'kind': 'data', 'relative': '../../out'}})
        answer = self.app.written[0]
        self.assertFalse(answer['ok'])
        self.assertEqual(answer['kind'], 'refused')

    def test_a_notification_is_not_answered(self):
        """Nothing is waiting for it, so a reply would be a stray line."""
        self.app._handle({'op': 'log', 'args': {'level': 'info', 'text': 'hi'}})
        self.assertEqual(self.app.written, [])
        self.assertEqual(self.app.log[-1], ('info', 'hi'))

    def test_arguments_that_are_not_a_table_do_not_crash_it(self):
        self.app._handle({'id': 4, 'op': 'speak', 'args': 'not a dict'})
        self.assertTrue(self.app.written[0]['ok'])

    def test_the_log_is_bounded(self):
        for index in range(bridge.MAX_LOG + 200):
            self.app._note('info', 'line %d' % index)
        self.assertLessEqual(len(self.app.log), bridge.MAX_LOG)

    def test_a_sound_outside_the_package_is_not_found(self):
        self.app._handle({'id': 5, 'op': 'sound_asset',
                          'args': {'name': '../../../windows/media/ding'}})
        self.assertIsNone(self.app.written[0]['result'])


class _SilentSpeaker(host.Speaker):
    def _speech_module(self):
        return None

    def _messenger(self):
        return None


class _NoMixer(host.Mixer):
    def _sound_module(self):
        return None

    def _spatial_module(self):
        return None

    def _pygame_mixer(self):
        return None

    def _mode(self):
        return 'none'

    def start(self, path, pan=0.0, gain=1.0, loop=False,
                  elevation=0.0):
        return None


class HowASoundIsNamed(unittest.TestCase):
    """Applications write `play_sound_from_asset("draw")` and ship
    `Audio/draw.ogg`; the extension and the folder are both implied."""

    def test_the_names_that_are_tried(self):
        names = bridge._sound_names('draw')
        self.assertIn('draw.ogg', names)
        self.assertIn('Audio/draw.ogg', names)
        self.assertIn('sounds/draw.ogg', names)

    def test_a_name_that_already_has_a_folder_is_left_alone(self):
        names = bridge._sound_names('Audio/fire.ogg')
        self.assertEqual(names, ['Audio/fire.ogg'])


class TheInterpreter(unittest.TestCase):
    """The component carries Ruby, and that is what makes it portable."""

    def test_there_is_one_and_it_is_new_enough(self):
        try:
            found = runtime.find()
        except runtime.RubyMissing as error:
            self.skipTest(str(error))
        self.assertGreaterEqual(found.version, runtime.MINIMUM)

    def test_the_one_that_ships_is_the_one_that_is_used(self):
        if not runtime.vendored():
            self.skipTest('this build does not carry Ruby')
        self.assertTrue(runtime.find().vendored)

    def test_an_applications_environment_carries_no_surprises(self):
        """Whatever the machine's own Ruby wants loaded into every
        interpreter is not something an Elten application asked for."""
        try:
            found = runtime.find()
        except runtime.RubyMissing as error:
            self.skipTest(str(error))
        environment = found.environment({'RUBYOPT': 'ignored'})
        self.assertEqual(environment.get('RUBYOPT'), 'ignored')
        plain = found.environment()
        self.assertNotIn('RUBYOPT', plain)
        self.assertNotIn('RUBYLIB', plain)


@unittest.skipIf(zstd is None, 'this build has no zstd')
class AnApplicationReallyRuns(unittest.TestCase):
    """The Ruby half, on the interpreter the component carries.

    This is the test that would have caught `alert(text, false)`: an API
    whose signatures are guessed from call sites is one that raises
    `ArgumentError` inside somebody else's application.
    """

    def setUp(self):
        try:
            runtime.find()
        except runtime.RubyMissing as error:
            self.skipTest(str(error))
        self.root = tempfile.mkdtemp(prefix='elten-run-')

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_source(self, source, manifest=None, seconds=45.0, ui=None):
        manifest = dict(manifest or MANIFEST)
        path = os.path.join(self.root, 'app.eltenapp')
        build_package(path, manifest, files=[('__app.rb', source)])
        entry = catalogue.Application(path, manifest, None, 'test')
        entry.localise('en')
        folder, _package = launcher.unpack(entry)
        paths = host.Paths(folder, os.path.join(self.root, 'data'),
                           os.path.join(self.root, 'cache'))
        paths.ensure('data')
        paths.ensure('cache')
        application = bridge.Application(
            entry, paths, speaker=_SilentSpeaker(),
            sounds=host.Sounds(_NoMixer()), ui=ui)
        application._on_gui = lambda call, default=None: call()
        application.start()
        application.ended.wait(seconds)
        application.stop()
        return application

    def test_a_program_runs_and_says_something(self):
        application = self.run_source(
            'class ProgramTest < Program\n'
            '  def program_main\n'
            '    speak("hello from Ruby")\n'
            '  end\n'
            'end\n')
        self.assertEqual(application.status, 'finished', application.detail)
        self.assertIn('hello from Ruby', application.speaker.spoken)

    def test_alert_takes_elten_s_own_second_argument(self):
        """`alert(text, wait)` - Solitaire calls it on every cursor move."""
        application = self.run_source(
            'class ProgramTest < Program\n'
            '  def program_main\n'
            '    alert("first")\n'
            '    alert("second", false)\n'
            '  end\n'
            'end\n')
        self.assertEqual(application.status, 'finished', application.detail)
        self.assertEqual(application.speaker.spoken, ['first', 'second'])

    def test_a_program_that_raises_says_so_and_does_not_hang(self):
        application = self.run_source(
            'class ProgramTest < Program\n'
            '  def program_main\n'
            '    raise "deliberate"\n'
            '  end\n'
            'end\n')
        self.assertEqual(application.status, 'failed')
        self.assertIn('deliberate', application.detail)

    def test_a_manifest_naming_a_class_that_is_not_there(self):
        manifest = dict(MANIFEST, main_class='ProgramMissing')
        application = self.run_source(
            'class ProgramTest < Program\n  def program_main; end\nend\n',
            manifest=manifest)
        self.assertEqual(application.status, 'failed')
        self.assertIn('ProgramMissing', application.detail)

    def test_the_three_roots_answer_and_are_confined(self):
        application = self.run_source(
            'class ProgramTest < Program\n'
            '  def program_main\n'
            '    write_json(data_path("save.json"), {"level" => 4})\n'
            '    speak("level " + read_json(data_path("save.json"))["level"].to_s)\n'
            '    begin\n'
            '      data_path("../../escaped")\n'
            '      speak("ESCAPED")\n'
            '    rescue EltenBridge::RemoteError => error\n'
            '      speak("refused")\n'
            '    end\n'
            '  end\n'
            'end\n')
        self.assertEqual(application.status, 'finished', application.detail)
        self.assertIn('level 4', application.speaker.spoken)
        self.assertIn('refused', application.speaker.spoken)
        self.assertNotIn('ESCAPED', application.speaker.spoken)

    def test_an_application_writing_to_stdout_does_not_break_the_wire(self):
        """An application WILL `puts`. One stray line on stdout would be a
        parse error that reads like a Titan bug, so the real stdout is taken
        away at boot and `$stdout` points at stderr."""
        application = self.run_source(
            'class ProgramTest < Program\n'
            '  def program_main\n'
            '    puts "not protocol"\n'
            '    print "nor this"\n'
            '    $stdout.puts "nor this either"\n'
            '    speak("still here")\n'
            '  end\n'
            'end\n')
        self.assertEqual(application.status, 'finished', application.detail)
        self.assertIn('still here', application.speaker.spoken)

    def test_an_unknown_operation_reaches_the_application_as_an_error(self):
        application = self.run_source(
            'class ProgramTest < Program\n'
            '  def program_main\n'
            '    begin\n'
            '      EltenBridge.call("conference_join", {})\n'
            '      speak("no")\n'
            '    rescue EltenBridge::RemoteError => error\n'
            '      speak("told: " + error.kind)\n'
            '    end\n'
            '  end\n'
            'end\n')
        self.assertEqual(application.status, 'finished', application.detail)
        self.assertIn('told: unknown', application.speaker.spoken)

    def test_the_translations_the_package_carries_are_used(self):
        """`_()` answers out of the application's own `.mo`."""
        catalogue_mo = _tiny_mo({'New game': 'Nowa gra'})
        path = os.path.join(self.root, 'translated.eltenapp')
        build_package(path, MANIFEST,
                      files=[('__app.rb',
                              'class ProgramTest < Program\n'
                              '  def program_main\n'
                              '    speak(_("New game"))\n'
                              '  end\n'
                              'end\n')],
                      catalogues=[('PL', catalogue_mo)])
        entry = catalogue.Application(path, dict(MANIFEST), None, 'test')
        entry.localise('pl')
        folder, _package = launcher.unpack(entry)
        translator = launcher.translator_for(folder, 'pl')
        self.assertIsNotNone(translator)
        paths = host.Paths(folder, os.path.join(self.root, 'd2'),
                           os.path.join(self.root, 'c2'))
        paths.ensure('data')
        paths.ensure('cache')
        application = bridge.Application(
            entry, paths, speaker=_SilentSpeaker(),
            sounds=host.Sounds(_NoMixer()), translator=translator, ui=None)
        application._on_gui = lambda call, default=None: call()
        application.start()
        application.ended.wait(45.0)
        application.stop()
        self.assertEqual(application.status, 'finished', application.detail)
        self.assertIn('Nowa gra', application.speaker.spoken)

    def test_tasks_run_hands_over_a_progress_and_a_token(self):
        """Elten's own shape is `Tasks.run(label) { |progress, token| }`.
        Yielding only the progress made every application pass nil as a
        cancellation token and stop on `raise_if_cancelled!` for nil."""
        application = self.run_source(
            'class ProgramTest < Program\n'
            '  def program_main\n'
            '    Tasks.run("work") do |progress, token|\n'
            '      speak("token " + (token != nil).to_s)\n'
            '      speak("cancelled " + token.cancelled?.to_s)\n'
            '      token.sleep(0.01)\n'
            '      speak("slept")\n'
            '    end\n'
            '  end\n'
            'end\n')
        self.assertEqual(application.status, 'finished', application.detail)
        self.assertIn('token true', application.speaker.spoken)
        self.assertIn('cancelled false', application.speaker.spoken)
        self.assertIn('slept', application.speaker.spoken,
                      'token.sleep must be PUBLIC - applications call it with '
                      'an explicit receiver')

    def test_a_runner_takes_the_keywords_a_game_gives_it(self):
        """`Runner.new(frame_interval:)` and `on_action(..., phase:,
        cooldown:)` - a keyword this build does not act on must still be
        accepted, or an application is refused for asking precisely."""
        application = self.run_source(
            'class ProgramTest < Program\n'
            '  def program_main\n'
            '    guard = Runner::Cooldown.new(0.1)\n'
            '    runner = Runner.new(frame_interval: 0.05)\n'
            '    runner.action(:go, press: [:key_enter], hold: [:key_space])\n'
            '    runner.on_action(:go, phase: :start, cooldown: guard,\n'
            '                     guard: lambda { true }) { |r, _t| r.stop(:ok) }\n'
            '    runner.on_tick { |_r, _t| nil }\n'
            '    runner.after(0.2) { |r, _t| r.stop(:timeout) }\n'
            '    speak("ended " + runner.run.to_s)\n'
            '  end\n'
            'end\n')
        self.assertEqual(application.status, 'finished', application.detail)
        self.assertTrue(any('ended' in line
                            for line in application.speaker.spoken),
                        application.speaker.spoken)

    def test_a_control_answers_a_property_it_does_not_act_on(self):
        """Elten's controls carry a long tail of properties about how much
        they say of themselves. A control missing one is an application that
        stops - over a property about announcements."""
        application = self.run_source(
            'class ProgramTest < Program\n'
            '  def program_main\n'
            '    box = ListBox.new(["a", "b"], header: "h")\n'
            '    box.silent = true\n'
            '    box.speech = false\n'
            '    box.autosayoption = false\n'
            '    box.border_sound = false\n'
            '    speak("survived " + box.silent?.to_s)\n'
            '  end\n'
            'end\n')
        self.assertEqual(application.status, 'finished', application.detail)
        self.assertIn('survived true', application.speaker.spoken)

    def test_a_plug_in_with_no_screen_is_not_a_broken_application(self):
        """`ffmpeg` registers five encoders and returns; `mcp` is a server.
        Both do their whole job in `activate`."""
        manifest = dict(MANIFEST, menu={'hidden': True})
        application = self.run_source(
            'class ProgramTest < Program\n'
            '  def self.activate\n'
            '    MediaEncoders.register(Class.new(MediaEncoder))\n'
            '  end\n'
            'end\n', manifest=manifest)
        self.assertEqual(application.status, 'finished', application.detail)

    def test_a_runner_answers_keys(self):
        """A game's own loop, and the events it is driven by."""
        source = ('class ProgramTest < Program\n'
                  '  def program_main\n'
                  '    runner = Runner.new\n'
                  '    seen = []\n'
                  '    runner.on_key(:key_down) { seen << "down" }\n'
                  '    runner.action(:go, press: [:key_enter])\n'
                  '    runner.on_action(:go) { |current| current.stop(:done) }\n'
                  '    result = runner.run\n'
                  '    speak("saw " + seen.join(",") + " ended " + result.to_s)\n'
                  '  end\n'
                  'end\n')
        manifest = dict(MANIFEST)
        path = os.path.join(self.root, 'runner.eltenapp')
        build_package(path, manifest, files=[('__app.rb', source)])
        entry = catalogue.Application(path, manifest, None, 'test')
        entry.localise('en')
        folder, _package = launcher.unpack(entry)
        paths = host.Paths(folder, os.path.join(self.root, 'd3'),
                           os.path.join(self.root, 'c3'))
        paths.ensure('data')
        paths.ensure('cache')
        application = bridge.Application(
            entry, paths, speaker=_SilentSpeaker(),
            sounds=host.Sounds(_NoMixer()), ui=None)
        application._on_gui = lambda call, default=None: call()
        application.start()
        # Wait for the loop to be up before pressing anything at it.
        for _each in range(200):
            if application._watched:
                break
            threading.Event().wait(0.05)
        application.key_down('key_down')
        threading.Event().wait(0.3)
        application.key_down('key_enter')
        application.ended.wait(30.0)
        application.stop()
        self.assertEqual(application.status, 'finished', application.detail)
        self.assertTrue(any('saw down ended done' in line
                            for line in application.speaker.spoken),
                        application.speaker.spoken)


def _tiny_mo(entries):
    """The smallest real `.mo` that holds the given messages."""
    keys = sorted(entries)
    originals = [key.encode('utf-8') for key in keys]
    translations = [entries[key].encode('utf-8') for key in keys]
    count = len(keys)
    start = 7 * 4 + 16 * count
    offsets = []
    blob = b''
    for text in originals + translations:
        offsets.append((len(text), start + len(blob)))
        blob += text + b'\x00'
    out = struct.pack('<Iiiiiii', 0x950412de, 0, count, 7 * 4,
                      7 * 4 + count * 8, 0, 0)
    for length, offset in offsets[:count]:
        out += struct.pack('<ii', length, offset)
    for length, offset in offsets[count:]:
        out += struct.pack('<ii', length, offset)
    return out + blob


class TheInterfaceSoundsAreTitans(unittest.TestCase):
    """Moving onto a row, choosing it, the end of a list: an Elten
    application makes the noise this desktop makes for the same thing,
    because the user chose a sound theme and this is their desktop."""

    def test_the_platforms_own_cues_are_mapped(self):
        from eltenkit import cues
        for elten, titan in (('listbox_focus', 'core/FOCUS.ogg'),
                             ('listbox_select', 'core/SELECT.ogg'),
                             ('border', 'ui/endoflist.ogg'),
                             ('menu_open', 'ui/contextmenu.ogg'),
                             ('dialog_close', 'ui/dialogclose.ogg')):
            with self.subTest(cue=elten):
                self.assertEqual(cues.titan_cue(elten), titan)

    def test_every_cue_names_a_sound_the_default_theme_really_has(self):
        """A mapping to a file that is not there is silence."""
        from eltenkit import cues
        theme = os.path.join(ROOT, 'sfx', 'default')
        if not os.path.isdir(theme):
            self.skipTest('no default sound theme in this build')
        for elten, titan in sorted(cues.CUES.items()):
            with self.subTest(cue=elten):
                self.assertTrue(
                    os.path.isfile(os.path.join(theme, *titan.split('/'))),
                    '%s -> %s is not in the default theme' % (elten, titan))

    def test_an_application_s_own_sound_is_not_mapped(self):
        """A card being dealt is the application, not the interface."""
        from eltenkit import cues
        for name in ('deal', 'bird_01', 'flight', 'win', ''):
            self.assertEqual(cues.titan_cue(name), '')


class TheWindowWearsTheSkin(unittest.TestCase):
    """Every Titan skin carries icons, and an Elten application's window is
    a Titan window - so it wears them like every other window here."""

    def test_a_button_is_given_the_picture_its_label_suggests(self):
        from eltenkit import ui as ui_module
        for label, key in (('Back', 'back'), ('Wstecz', 'back'),
                           ('Zamknij', 'close'), ('Save', 'save'),
                           ('Wyszukaj', 'search'), ('Ustawienia', 'settings')):
            with self.subTest(label=label):
                self.assertEqual(ui_module._button_icon_key(label), key)

    def test_a_label_with_no_obvious_picture_gets_none(self):
        from eltenkit import ui as ui_module
        self.assertEqual(ui_module._button_icon_key('Kot domowy'), '')
        self.assertEqual(ui_module._button_icon_key(''), '')

    def test_the_skin_helpers_survive_having_no_skin(self):
        """A skin that cannot be read must not stop a screen appearing."""
        from eltenkit import ui as ui_module
        self.assertIsNone(ui_module._icon_for('', (16, 16), None))
        marker = object()
        self.assertIs(ui_module._dress(marker, None), marker)


class WhereTheApplicationsAre(unittest.TestCase):
    """Elten's own directory, read as Elten leaves it."""

    def test_the_roots_are_looked_in_in_order(self):
        found = [source for _path, source in catalogue.roots()]
        self.assertEqual(found, sorted(set(found), key=found.index))
        if catalogue.elten_source_dir():
            self.assertEqual(found[-1], 'elten',
                             "the user's own installation must win")

    def test_the_users_installation_is_where_elten_puts_it(self):
        root = catalogue.elten_root()
        if not root:
            self.skipTest('Elten is not installed on this machine')
        self.assertTrue(catalogue.elten_source_dir().endswith(
            os.path.join('apps', 'src')))
        self.assertTrue(catalogue.elten_data_dir().endswith(
            os.path.join('apps', 'data')))

    def test_a_saved_game_is_shared_with_elten(self):
        """Not a copy: the same file, so a game played in either is one
        game."""
        root = catalogue.elten_root()
        if not root:
            self.skipTest('Elten is not installed on this machine')
        entry = catalogue.Application(
            os.path.join(catalogue.elten_source_dir(), 'solitaire.eltenapp'),
            dict(MANIFEST), None, 'elten')
        self.assertTrue(launcher.data_root(entry).startswith(
            catalogue.elten_data_dir()))

    def test_the_installed_applications_all_read(self):
        found = catalogue.discover('en')
        if not found:
            self.skipTest('no Elten applications installed')
        for entry in found:
            with self.subTest(app=entry.stem):
                self.assertTrue(entry.name, entry.path)
                self.assertTrue(entry.id or entry.stem)


class APlaceIsAPlace(unittest.TestCase):
    """`[x, y, z]` is what Elten writes and what crosses the wire; Titan's
    side is the only one that knows what Titan's mixer takes."""

    def test_a_bare_number_is_already_a_pan(self):
        self.assertEqual(host._place(-0.5)[0], -0.5)
        self.assertEqual(host._place(0.0), (0.0, 0.0, 1.0))

    def test_a_metre_to_the_side_is_hard_over(self):
        """Skeet hands over a pan it has already worked out. Dividing it
        by a fixed number - which is what converting in Ruby did - meant
        the clay target could only ever reach half the stereo image."""
        self.assertEqual(host._place([-1.0, 0.0, 0.0])[0], -1.0)
        self.assertEqual(host._place([1.0, 0.0, 0.0])[0], 1.0)

    def test_the_same_metre_ten_metres_away_is_nearly_ahead(self):
        pan = host._place([1.0, 0.0, -10.0])[0]
        self.assertLess(abs(pan), 0.2)

    def test_height_becomes_an_elevation_and_distance_a_gain(self):
        _pan, elevation, gain = host._place([0.0, 1.0, 0.0])
        self.assertEqual(elevation, 90.0)
        self.assertEqual(gain, 1.0)
        far = host._place([0.0, 0.0, -10.0])[2]
        self.assertLess(far, 0.2)

    def test_nonsense_is_the_middle_rather_than_a_crash(self):
        for value in (None, 'left', {}, [], object()):
            self.assertEqual(host._place(value)[0], 0.0)


class TheRubySideAnswersEltensOwnShapes(unittest.TestCase):
    """Signatures read out of Elten's own source, checked against ours.

    Each of these was an application that stopped: a wrong `input_text`
    ended the media catalogue on the screen it was opening, a missing
    `closed?` silenced Skeet's clay target one frame after every throw.
    """

    def setUp(self):
        try:
            self.ruby = runtime.find()
        except runtime.RubyMissing as error:
            self.skipTest(str(error))

    def ask(self, source):
        """Run a snippet against the real platform, on the real Ruby."""
        preamble = """
$LOAD_PATH.unshift(%s)
module EltenBridge
  class Closed < StandardError; end
  def self.call(*_a); nil; end
  def self.notify(*_a); nil; end
  def self.now; Time.now.to_f; end
  def self.next_event(*_a); :timeout; end
end
module Log
  def self.warning(*_a); end
  def self.error(*_a); end
  def self.debug(*_a); end
end
require 'loop'
require 'eapi'
require 'program'
require 'controls'
""" % repr(os.path.join(COMPONENT, 'eapi')).replace("'", '"')
        path = os.path.join(tempfile.mkdtemp(prefix='elten-ask-'), 'ask.rb')
        io.open(path, 'w', encoding='utf-8').write(preamble + source)
        answer = subprocess.run([self.ruby.path, path], capture_output=True,
                                timeout=60, env=self.ruby.environment())
        self.assertEqual(answer.returncode, 0,
                         answer.stderr.decode('utf-8', 'replace'))
        return answer.stdout.decode('utf-8', 'replace').strip()

    def test_a_sound_answers_everything_a_game_asks_before_using_it(self):
        """Skeet asks `closed?` on every frame of every throw, inside its
        own `rescue Exception`. A missing method is not a degraded sound,
        it is `stop_flight`."""
        wanted = ('closed? spatial_position spatial_position= spatialize '
                  'spatial_position_slide spatial_position_sliding? '
                  'cancel_spatial_position_slide despatialize pause resume '
                  'effects_latency_ms effect_playback_seconds_at pan volume '
                  'finished? stopped? opened?').split()
        source = ('s = EltenSound.new(1, "x")\n'
                  'puts %s.select { |m| !s.respond_to?(m) }.inspect\n'
                  % repr(wanted).replace("'", '"'))
        self.assertEqual(self.ask(source), '[]')

    def test_input_text_takes_eltens_own_keywords(self):
        """`display_text` is BUILT on `input_text` (read-only plus
        multiline), so a signature taking `default:`/`multiline:` answered
        `unknown keywords: :escapable, :text`."""
        source = ('begin\n'
                  '  input_text("Header", flags: 3, text: "hello", '
                  'escapable: true)\n'
                  '  puts "accepted"\n'
                  'rescue ArgumentError => e\n'
                  '  puts "refused: #{e.message}"\n'
                  'end\n')
        self.assertEqual(self.ask(source), 'accepted')

    def test_set_texts_second_argument_is_positional(self):
        source = ('b = EditBox.new("h")\n'
                  'b.set_text("one", false)\n'
                  'puts b.text\n')
        self.assertEqual(self.ask(source), 'one')

    def test_a_board_reports_which_wall_it_walked_into(self):
        """AudioMemory reads `pos[2]` off a `:border` to play a sound at
        the edge that was hit."""
        source = ('g = GridBox.new(3, 3)\n'
                  'args = g.event_args(:border, {"direction" => "left", '
                  '"dx" => -1, "dy" => 0})\n'
                  'puts args.first[2].inspect\n')
        self.assertEqual(self.ask(source), ':left')

    def test_a_control_that_says_it_is_silent_says_so_to_titan(self):
        """AudioMemory's board is silent because the game already sounds
        every square; cueing over that is two sounds for one move."""
        source = ('g = GridBox.new(3, 3)\n'
                  'g.silent = true\n'
                  'g.border_sound = false\n'
                  'puts [g.to_spec[:silent], g.to_spec[:border_sound]].inspect\n')
        self.assertEqual(self.ask(source), '[true, false]')

    def test_a_choice_row_starts_where_it_was_left(self):
        """MileByMile writes `[label, choices, index]` so its settings
        form opens on the game the player set up last time. Dropping the
        third element silently reset every one of them."""
        source = ('c = ChoiceListBox.new([["", %s, 2]])\n'
                  'puts [c.value(0), c.choice_rows.first[:index]].inspect\n'
                  % '["a", "b", "c"]')
        self.assertEqual(self.ask(source), '["c", 2]')

    def test_hide_means_hide_a_control_not_the_window(self):
        """Elten's `Form#show(index)` unhides a control. Titan's own "put
        this window up" had the same name and had to move aside."""
        source = ('b = Button.new("Ok")\n'
                  'f = Form.new([b])\n'
                  'b.control_id = 0\n'
                  'f.hide(b)\n'
                  'first = f.hidden_controls\n'
                  'f.show(b)\n'
                  'puts [first, f.hidden_controls].inspect\n')
        self.assertEqual(self.ask(source), '[[0], []]')

    def test_the_frame_is_defined_once(self):
        """A zero-arity `loop_update` anywhere shadows the real one for
        the Runner, every Program and every control."""
        source = ('puts method(:loop_update).arity.inspect\n')
        self.assertEqual(self.ask(source), '-1')

    def test_a_control_answers_the_platforms_whole_surface(self):
        """A method that is merely missing does not degrade - it raises,
        inside somebody else's application."""
        wanted = ('set_text text_str text_len select_all copy cut paste '
                  'get_lines').split()
        source = ('b = EditBox.new("h")\n'
                  'puts %s.select { |m| !b.respond_to?(m) }.inspect\n'
                  % repr(wanted).replace("'", '"'))
        self.assertEqual(self.ask(source), '[]')


class TheBridgeSpeaksTheUsersLanguage(unittest.TestCase):
    """The few words Titan builds rather than the application."""

    def test_its_own_catalogue_is_there_and_compiled(self):
        import gettext
        folder = os.path.join(COMPONENT, 'languages')
        if not os.path.isdir(folder):
            self.skipTest('no catalogue in this build')
        polish = gettext.translation('elten_bridge', folder, languages=['pl'],
                                     fallback=True)
        self.assertNotEqual(polish.gettext('Play'), 'Play')
        self.assertNotEqual(polish.gettext('Delete'), 'Delete')


class _RubyAsk(unittest.TestCase):
    """A snippet run against the REAL platform on the REAL interpreter.

    The same harness `TheRubySideAnswersEltensOwnShapes` uses, with the
    whole platform loaded rather than half of it - the settings, the
    class-level API and the file tree all reach for `paths` and each
    other, and a preamble that loads only some of them tests a program
    that does not exist.
    """

    PREAMBLE = """
$LOAD_PATH.unshift(%s)
module EltenBridge
  class Closed < StandardError; end
  def self.call(op, args = {})
    $calls ||= []
    $calls << [op, args]
    case op
    when 'dirs' then {"user"=>Dir.home, "documents"=>Dir.home, "desktop"=>Dir.home, "music"=>Dir.home}
    when 'path' then File.join(Dir.tmpdir, "elten-test", args["relative"].to_s)
    when 'app_name' then "Test"
    when 'form_open' then 1
    when 'elten_app' then ($elten_app || nil)
    else nil
    end
  end
  def self.notify(op, args = {}); ($notices ||= []) << [op, args]; nil; end
  def self.now; Time.now.to_f; end
  def self.next_event(*_a); :timeout; end
end
module Log
  def self.warning(*_a); end
  def self.error(*_a); end
  def self.debug(*_a); end
  def self.info(*_a); end
end
require 'tmpdir'
require 'loop'
require 'eapi'
require 'program'
require 'controls'
require 'server'
require 'paths'
require 'program_api'
require 'settings'
require 'audio'
require 'media'
require 'childproc'
require 'eltenlink'
require 'eltenapi'
require 'network'
"""

    def setUp(self):
        try:
            self.ruby = runtime.find()
        except runtime.RubyMissing as error:
            self.skipTest(str(error))

    def ask(self, source):
        preamble = self.PREAMBLE % repr(
            os.path.join(COMPONENT, 'eapi')).replace("'", '"')
        path = os.path.join(tempfile.mkdtemp(prefix='elten-ask-'), 'ask.rb')
        io.open(path, 'w', encoding='utf-8').write(preamble + source)
        answer = subprocess.run([self.ruby.path, path], capture_output=True,
                                timeout=120, env=self.ruby.environment())
        self.assertEqual(answer.returncode, 0,
                         answer.stderr.decode('utf-8', 'replace'))
        return answer.stdout.decode('utf-8', 'replace').strip()


class AnEventReachesTheBlockTheWayEltenSendsIt(_RubyAsk):
    """`e[4].call(a)` - ONE argument, the whole parameter list.

    Elten's `FormBase#trigger` hands a block the array and lets Ruby's own
    auto-splat sort it out, so `on(:move) { |pos| pos[0] }` gets the pair
    and `on(:action) { |name, source, x, y| }` gets them apart. Splatting
    instead gave the first shape the first number on its own - and
    `pos[0]` on an Integer is a BIT of it, so AudioMemory read a column
    out of a number that was the column.
    """

    def test_one_parameter_receives_the_whole_list(self):
        source = ('g = GridBox.new(3, 3)\n'
                  'seen = nil\n'
                  'g.on(:move) { |pos| seen = pos }\n'
                  'g.key_pressed("key_right"); g.update\n'
                  'puts seen.inspect\n')
        self.assertEqual(self.ask(source), '[1, 0]')

    def test_several_parameters_still_come_apart(self):
        source = ('g = GridBox.new(3, 3)\n'
                  'g.bind_action(:flag, key: :f)\n'
                  'seen = nil\n'
                  'g.on(:action) { |name, _source, x, y| seen = [name, x, y] }\n'
                  'g.key_pressed("key_f"); g.update\n'
                  'puts seen.inspect\n')
        self.assertEqual(self.ask(source), '[:flag, 0, 0]')


class ABoardIsEltensBoard(_RubyAsk):
    """`GridBox`, method for method against `ui/controls/grid_box.rb`.

    A grid is the one control an application drives from its own loop -
    `runner.on_tick { grid.update }` - so `update` has to be where it
    moves, where the edge is reported and where a bound key fires.
    """

    def test_it_answers_everything_eltens_own_does(self):
        wanted = ('labels set_cell set_cells replace_cells update_cells '
                  'cell_label coordinate_label resize value lpos focus '
                  'update move_by border_direction key_processed '
                  'bind_action unbind_action reset_action_bindings '
                  'action_bindings header x y width height').split()
        source = ('g = GridBox.new(2, 2)\n'
                  'puts %s.reject { |m| g.respond_to?(m) }.inspect\n'
                  % repr(wanted).replace("'", '"'))
        self.assertEqual(self.ask(source), '[]')

    def test_a_value_is_where_the_cursor_is_not_what_is_under_it(self):
        """Elten's `value` is `[x, y]`. Answering the cell instead is a
        game reading a label where it asked for a position."""
        source = ('g = GridBox.new(3, 3)\n'
                  'g.replace_cells([%w[a b c], %w[d e f], %w[g h i]])\n'
                  'g.set_position(2, 1)\n'
                  'puts [g.value, g.cell_label, g.coordinate_label].inspect\n')
        self.assertEqual(self.ask(source), '[[2, 1], "f", "C2"]')

    def test_a_wall_is_reported_with_the_way_it_was_walked_into(self):
        """AudioMemory reads `pos[2]` and sounds the edge that was hit."""
        source = ('g = GridBox.new(3, 3)\n'
                  'seen = nil\n'
                  'g.on(:border) { |pos| seen = pos }\n'
                  'g.key_pressed("key_left"); g.update\n'
                  'puts seen.inspect\n')
        self.assertEqual(self.ask(source), '[0, 0, :left, -1, 0]')

    def test_a_board_that_grows_tells_titan_its_new_shape(self):
        """AudioMemory deals a bigger board every round. A grid whose
        window keeps the old shape has squares the player cannot reach."""
        source = ('g = GridBox.new(2, 2)\n'
                  'Form.new([g]).present\n'
                  '$notices = []\n'
                  'g.replace_cells(Array.new(4) { Array.new(4, "x") }, resize: true)\n'
                  'change = $notices.map { |op, args| args }.last\n'
                  'puts [g.width, g.height, change[:width], change[:height]].inspect\n')
        self.assertEqual(self.ask(source), '[4, 4, 4, 4]')

    def test_setting_a_position_moves_the_cursor_on_the_screen(self):
        """`grid.x = 0` between rounds. A plain writer left Ruby and the
        window disagreeing about where the cursor was."""
        source = ('g = GridBox.new(3, 3)\n'
                  'Form.new([g]).present\n'
                  'g.set_position(2, 2)\n'
                  '$notices = []\n'
                  'g.x = 0\n'
                  'g.y = 0\n'
                  'puts $notices.map { |_op, args| [args[:x], args[:y]] }.inspect\n')
        self.assertEqual(self.ask(source), '[[0, nil], [nil, 0]]')

    def test_the_arrows_cannot_be_bound_to_anything_else(self):
        source = ('g = GridBox.new(2, 2)\n'
                  'begin\n'
                  '  g.bind_action(:x, key: :left)\n'
                  '  puts "allowed"\n'
                  'rescue ArgumentError\n'
                  '  puts "refused"\n'
                  'end\n')
        self.assertEqual(self.ask(source), 'refused')


class AKeyIsAlsoItsNumber(_RubyAsk):
    """`key_held?(0x11)` is Control.

    Elten's own code asks that way and so do applications - the file
    manager's Ctrl+D is `runner.on_key(0x44)` guarded by
    `key_held?(0x11)`. Comparing a Windows virtual key code as a string
    against a table of names matched nothing, so every shortcut written
    that way did nothing at all.
    """

    def test_a_virtual_key_code_finds_the_key_by_name(self):
        source = ('EltenLoop.instance_variable_set(:@held,\n'
                  '  {"key_control" => true, "key_d" => true})\n'
                  'puts [EltenLoop.key_held?(0x11), EltenLoop.key_held?(0x44),\n'
                  '      EltenLoop.key_held?(0x45)].inspect\n')
        self.assertEqual(self.ask(source), '[true, true, false]')

    def test_the_letters_and_the_function_keys_are_there_too(self):
        source = ('puts [EltenLoop::VIRTUAL_KEYS[0x09], '
                  'EltenLoop::VIRTUAL_KEYS[0x41], '
                  'EltenLoop::VIRTUAL_KEYS[0x70]].inspect\n')
        self.assertEqual(self.ask(source), '["key_tab", "key_a", "key_f1"]')

    def test_a_mouse_click_can_be_a_key(self):
        """A double click in the file tree is Enter, because that is what
        the application bound - `runner.on_key(:key_enter)`."""
        source = ('EltenLoop.inject("key_enter")\n'
                  'puts EltenLoop.key_pressed?(:key_enter).inspect\n')
        self.assertEqual(self.ask(source), 'true')


class TheFileTreeIsEltensFileTree(_RubyAsk):
    """`FilesTree`, against `ui/controls/files_tree.rb`.

    The file manager opens with `path: ""`, which in Elten is the top of
    the MACHINE - every drive, then Desktop, Documents and Music.
    Answering it with the home folder is a file manager that can never
    reach another drive, because Left from a drive root had nowhere to
    go.
    """

    def test_an_empty_path_is_the_list_of_drives(self):
        source = ('t = FilesTree.new("FileManager", path: "")\n'
                  'puts [t.root?, t.entries.first, t.entries.size >= 2].inspect\n')
        answer = self.ask(source)
        self.assertTrue(answer.startswith('[true, "'), answer)
        self.assertTrue(answer.endswith('true]'), answer)

    def test_right_goes_in_and_left_comes_back_out_to_the_drives(self):
        source = ('t = FilesTree.new("FileManager", path: "")\n'
                  't.key_pressed("key_right"); t.update\n'
                  'inside = t.path\n'
                  't.key_pressed("key_left"); t.update\n'
                  'puts [inside != "", t.root?].inspect\n')
        self.assertEqual(self.ask(source), '[true, true]')

    def test_it_carries_the_three_menus_elten_gives_it(self):
        """`bind_filesmenu`, `bind_editmenu` and `bind_createmenu` are
        separate bindings and become separate submenus - File, Edit and
        Create - each with the tree's own commands already in it."""
        source = ('t = FilesTree.new("FileManager", path: "")\n'
                  't.bind_filesmenu { |m| m.option("Open with") {} }\n'
                  't.bind_createmenu { |m| m.option("New text file") {} }\n'
                  'menu = Menu.new("x")\n'
                  't.context(menu, false)\n'
                  'puts menu.options.map { |o| o[:label] }.inspect\n')
        self.assertEqual(self.ask(source), '["File", "Edit", "Create"]')

    def test_a_folder_is_read_on_the_frame_and_not_before_it(self):
        """Elten's `refresh` marks the tree and the re-read happens on the
        next `update`, so an application refreshing several times in one
        operation reads the folder once."""
        source = ('t = FilesTree.new("t", path: Dir.tmpdir)\n'
                  't.refresh\n'
                  'marked = t.instance_variable_get(:@refresh)\n'
                  't.update\n'
                  'puts [marked, t.instance_variable_get(:@refresh)].inspect\n')
        self.assertEqual(self.ask(source), '[true, false]')


class AListHasEltensOwnFlags(_RubyAsk):
    """`MultiSelection` is 1.

    `AnyDir = 1` was wrong in the way that hurts: every application
    asking for a list of things to tick got one that could not be ticked,
    and one that believed it had been asked for something else.
    """

    def test_the_numbers_are_eltens(self):
        source = ('puts [ListBox::Flags::MultiSelection, '
                  'ListBox::Flags::LeftRight, ListBox::Flags::Silent, '
                  'ListBox::Flags::AnyDir, ListBox::Flags::Circular, '
                  'ListBox::Flags::HotKeys, ListBox::Flags::Tagged].inspect\n')
        self.assertEqual(self.ask(source), '[1, 2, 4, 8, 16, 32, 64]')

    def test_a_multi_selection_list_can_be_ticked_before_it_is_shown(self):
        source = ('l = ListBox.new(%w[a b c], flags: ListBox::Flags::MultiSelection)\n'
                  'l.selected[0] = true\n'
                  'l.selected[2] = true\n'
                  'puts [l.multi?, l.multiselections].inspect\n')
        self.assertEqual(self.ask(source), '[true, [0, 2]]')


class AnApplicationsOwnSettings(_RubyAsk):
    """`show_settings` - Elten's `program_settings.rb`, as a Titan form."""

    def test_every_kind_of_field_becomes_the_control_it_should(self):
        source = ('store = Programs::ProgramSettings::Store.new(Program)\n'
                  'collector = Programs::ProgramSettings::Collector.new\n'
                  'inner = Programs::ProgramSettings::SettingsBuilder.new(collector)\n'
                  'b = Programs::ProgramSettings::Builder.new(inner, store)\n'
                  'b.boolean(:a, label: "A", default: true)\n'
                  'b.integer(:b, label: "B", range: 0..10, default: 3)\n'
                  'b.text(:c, label: "C", default: "x")\n'
                  'b.choice(:d, label: "D", choices: {"One" => 1, "Two" => 2}, default: 2)\n'
                  'd = Programs::ProgramSettings::Dialog.new("T", collector.entries, store)\n'
                  'puts collector.entries.map { |e| d.send(:control_for, e).class.to_s }.inspect\n')
        self.assertEqual(self.ask(source),
                         '["CheckBox", "EditBox", "EditBox", "ListBox"]')

    def test_a_choice_offers_the_labels_and_answers_the_value(self):
        source = ('store = Programs::ProgramSettings::Store.new(Program)\n'
                  'collector = Programs::ProgramSettings::Collector.new\n'
                  'inner = Programs::ProgramSettings::SettingsBuilder.new(collector)\n'
                  'b = Programs::ProgramSettings::Builder.new(inner, store)\n'
                  'b.choice(:d, label: "D", choices: {"One" => "one", "Two" => "two"}, default: "two")\n'
                  'entry = collector.entries[0]\n'
                  'd = Programs::ProgramSettings::Dialog.new("T", collector.entries, store)\n'
                  'control = d.send(:control_for, entry)\n'
                  'puts [control.options, control.index,\n'
                  '      d.send(:value_of, entry, control)].inspect\n')
        self.assertEqual(self.ask(source),
                         '[["One", "Two"], 1, "two"]')

    def test_saving_does_not_deadlock_and_the_value_comes_back(self):
        """`transaction` holds the lock and the setters it calls take it
        again: with a plain Mutex an Apply that saved anything at all
        hung the application."""
        source = ('store = Programs::ProgramSettings::Store.new(Program)\n'
                  'collector = Programs::ProgramSettings::Collector.new\n'
                  'inner = Programs::ProgramSettings::SettingsBuilder.new(collector)\n'
                  'b = Programs::ProgramSettings::Builder.new(inner, store)\n'
                  'b.integer(:volume, label: "V", range: 0..100, default: 80)\n'
                  'store.transaction { collector.entries[0].setter.call(42) }\n'
                  'puts Programs::ProgramSettings::Store.new(Program).get(:volume, 0).inspect\n')
        self.assertEqual(self.ask(source), '42')


class AnExtensionReallyTicks(_RubyAsk):
    """`service.tick(interval:)` is the file manager's background
    playlist. With nothing calling it the playlist advanced to its next
    track and stopped there for good."""

    def test_a_tick_runs_on_the_frame_and_stops_when_it_is_told_to(self):
        source = ('$count = 0\n'
                  'class Ticker < Program\n'
                  '  extension(:demo) do |service|\n'
                  '    service.tick(interval: 0.0) { $count += 1 }\n'
                  '  end\n'
                  'end\n'
                  'EltenLoop.run_frame_hooks\n'
                  'EltenLoop.run_frame_hooks\n'
                  'ran = $count\n'
                  'Ticker.stop_extensions\n'
                  'EltenLoop.run_frame_hooks\n'
                  'puts [ran, $count].inspect\n')
        self.assertEqual(self.ask(source), '[2, 2]')

    def test_what_an_extension_declares_can_be_shown_as_settings(self):
        source = ('class Settable < Program\n'
                  '  extension(:demo) do |service|\n'
                  '    service.settings do |s|\n'
                  '      s.category("Playlists")\n'
                  '      s.boolean(:show, label: "Show", get: proc { true },\n'
                  '                       set: proc { |_v| true })\n'
                  '    end\n'
                  '  end\n'
                  'end\n'
                  'collector = Programs::ProgramSettings::Collector.new\n'
                  'inner = Programs::ProgramSettings::SettingsBuilder.new(collector)\n'
                  'builder = Programs::ProgramSettings::Builder.new(inner,\n'
                  '  Programs::ProgramSettings::Store.new(Settable))\n'
                  'Settable.extensions.each_value do |recorder|\n'
                  '  recorder.blocks_for("settings").each { |_a, b| b.call(builder) }\n'
                  'end\n'
                  'puts [collector.category_label,\n'
                  '      collector.entries.map(&:label)].inspect\n')
        self.assertEqual(self.ask(source), '["Playlists", ["Show"]]')


class TheWholeProgramApiIsThere(_RubyAsk):
    """Every name Elten's own `Program` defines, at both levels.

    The list is read out of `src/eapi/program.rb` in Elten's repository.
    It matters because of what a MISSING method does in somebody else's
    program: `NoMethodError`, usually inside their own `rescue
    Exception`, where it becomes a feature quietly not working rather
    than an error anybody sees.
    """

    CLASS_METHODS = (
        'activate app_file app_uuid asset_path author box? build_id '
        'cache_path close_managed_resources close_sound_pool '
        'create_sound_from_asset create_spatial_sound_from_asset data_path '
        'delete_server_app description description_languages '
        'elten_api_version execution_backend extension get_configuration '
        'hidden? init leaderboard main_language manage managed_resources '
        'map_notification menu_label missing_required_assets name_languages '
        'native_box? notification_received on play_app_sound '
        'play_sound_from_asset raw_description raw_name read_binary '
        'read_json read_text register_quickaction register_server_app '
        'register_server_app! release required_assets '
        'required_assets_available? send_notification server_app '
        'server_app_definition server_app_uuid server_resources server_table '
        'set_configuration show_settings sound_asset sound_asset_data '
        'sound_asset_path sound_pool supported_languages update_json '
        'update_server_app update_server_schema! user_menu_options '
        'validate_required_assets! version write_binary write_json write_text'
    ).split()

    INSTANCE_METHODS = (
        'app app_cache app_file app_uuid appsignature asset_path author box? '
        'build_id cache_path close close_managed_resources close_sound_pool '
        'communication create_sound_from_asset '
        'create_spatial_sound_from_asset data_path delete_server_app '
        'description description_languages elten_api_version '
        'execution_backend exit finalize finish hidden? leaderboard '
        'live_sessions main_language manage managed_resources manifest '
        'menu_label missing_required_assets name_languages native_box? '
        'notification_action on play_app_sound play_sound_from_asset '
        'raw_description raw_name read_binary read_json read_text '
        'register_quickaction release required_assets '
        'required_assets_available? send_notification server_app_definition '
        'server_app_uuid server_resources server_table show_settings signal '
        'signaled sound_asset sound_asset_data sound_asset_path sound_pool '
        'supported_languages update_json user_menu_options '
        'validate_required_assets! version write_binary write_json write_text'
    ).split()

    def test_the_class_answers_all_of_it(self):
        source = ('class Sample < Program; end\n'
                  'puts %s.reject { |m| Sample.respond_to?(m) }.inspect\n'
                  % repr(self.CLASS_METHODS).replace("'", '"'))
        self.assertEqual(self.ask(source), '[]')

    def test_an_instance_answers_all_of_it(self):
        source = ('class Sample < Program; end\n'
                  'puts %s.reject { |m| Sample.new.respond_to?(m) }.inspect\n'
                  % repr(self.INSTANCE_METHODS).replace("'", '"'))
        self.assertEqual(self.ask(source), '[]')

    def test_a_required_asset_that_is_absent_is_reported(self):
        source = ('class Needy < Program; end\n'
                  'Needy.manifest = {"required_assets" => {"sounds" => ["nope"]}}\n'
                  'puts [Needy.required_assets_available?,\n'
                  '      Needy.missing_required_assets].inspect\n')
        self.assertEqual(self.ask(source),
                         '[false, {"sounds" => ["nope"]}]')

    def test_a_hidden_application_says_so(self):
        """`ffmpeg` and `mcp` declare `menu: {hidden: true}` - they are
        plug-ins, and listing them offers a row that opens and closes."""
        source = ('class Plugin < Program; end\n'
                  'Plugin.manifest = {"name" => "P", "menu" => {"hidden" => true}}\n'
                  'puts [Plugin.hidden?, Plugin.menu_label].inspect\n')
        self.assertEqual(self.ask(source), '[true, "Test"]')


class AServerTableIsOnTheServer(_RubyAsk):
    """A game's best scores are everybody's.

    `server_table` and `leaderboard` were a JSON file beside the
    application, so "Best scores" was a scoreboard with one player on it.
    They are rows on EltenLink now, written as whoever is signed in to
    Titan IM - with this machine's own copy underneath, so a score is
    never lost to a server that is not there.
    """

    def test_a_row_is_kept_locally_even_when_the_server_refuses(self):
        source = ('class Scored < Program; end\n'
                  'Scored.manifest = {"id" => "x"}\n'
                  'Scored.server_app(uuid: "u", tables: {})\n'
                  'table = Scored.server_table("scores")\n'
                  'table.local.delete\n'
                  'table.insert("points" => 7)\n'
                  'puts table.local.all.map { |r| r["points"] }.inspect\n')
        self.assertEqual(self.ask(source), '[7]')

    def test_reading_falls_back_to_this_machines_own_rows(self):
        source = ('class Scored2 < Program; end\n'
                  'Scored2.manifest = {"id" => "y"}\n'
                  'Scored2.server_app(uuid: "u", tables: {})\n'
                  'table = Scored2.server_table("s2")\n'
                  'table.local.delete\n'
                  'table.insert("points" => 3)\n'
                  'puts table.all.map { |r| r["points"] }.inspect\n')
        self.assertEqual(self.ask(source), '[3]')

    def test_a_table_with_no_uuid_is_honestly_unavailable(self):
        source = ('class Scored3 < Program; end\n'
                  'puts Scored3.server_table("s3").available?.inspect\n')
        self.assertEqual(self.ask(source), 'false')


class AChangeToAWindowReallyArrives(unittest.TestCase):
    """`control_set` and `form_close` are sent with no id.

    A message with no id is looked up in `NOTIFICATIONS` and nowhere
    else, so for as long as these were only in `OPERATIONS` every one of
    them was read off the wire and dropped. What that meant is
    everything an application does to a window it has already put up: a
    list whose rows are replaced, a board dealt again, a header that
    should follow the folder. The file manager listed its first folder
    and then showed that folder for ever; AudioMemory's board stayed the
    empty one it was built with.
    """

    def test_the_notifications_an_application_really_sends_are_handled(self):
        import re
        source = io.open(os.path.join(COMPONENT, 'eapi', 'controls.rb'),
                         encoding='utf-8').read()
        source += io.open(os.path.join(COMPONENT, 'eapi', 'boot.rb'),
                          encoding='utf-8').read()
        source += io.open(os.path.join(COMPONENT, 'eapi', 'bridge.rb'),
                          encoding='utf-8').read()
        sent = set(re.findall(r"EltenBridge\.notify\(\s*'([a-z_]+)'", source))
        self.assertTrue(sent, 'no notifications found at all')
        missing = sorted(sent - set(bridge.NOTIFICATIONS))
        self.assertEqual(missing, [],
                         'sent with no id and answered by nobody: %s' % missing)

    def test_a_control_change_reaches_the_widget(self):
        recorder = TheDispatchTable.Recorder()
        seen = []

        class UI(object):
            def set_control(self, form_id, index, changes):
                seen.append((form_id, index, dict(changes)))
                return True

        recorder.ui = UI()
        recorder._on_gui = lambda call, default=None: call()
        recorder._handle({'op': 'control_set',
                          'args': {'form': 1, 'control': 0,
                                   'options': ['a', 'b']}})
        self.assertEqual(len(seen), 1, 'the change was dropped')
        self.assertEqual(seen[0][0], 1)


class ASoundAnswersWhatAGameAsks(_RubyAsk):
    """Purrposterous reads `basefrequency` when a cat is born and pitches
    against it as the cat gets hungrier. Missing, it ended the game on
    the first cat - inside the game's own rescue, so what the user saw
    was a game that started and stopped."""

    def test_the_pitch_and_the_clock_are_all_there(self):
        wanted = ('basefrequency frequency frequency= pitch pitch= tempo '
                  'tempo= length position pause resume paused? stopped? '
                  'opened? closed? status title artist album wait '
                  'volume volume= pan pan= play stop playing? '
                  'finished? close').split()
        source = ('s = EltenSound.new(1, "x")\n'
                  'puts %s.reject { |m| s.respond_to?(m) }.inspect\n'
                  % repr(wanted).replace("'", '"'))
        self.assertEqual(self.ask(source), '[]')

    def test_a_pool_plays_a_sound_and_keeps_a_ceiling(self):
        """`sound_pool(max_voices:)` answered `self` - the Program - so
        `pool.play(sound)` reached a method of the application's that
        took no arguments, and every one-shot Purrposterous plays ended
        in `ArgumentError` inside its own rescue: a game that walked in
        silence."""
        source = ('class Noisy < Program; end\n'
                  'pool = Noisy.new.sound_pool(max_voices: 2)\n'
                  'three = (1..3).map { |n| EltenSound.new(n, "s#{n}") }\n'
                  'three.each { |sound| pool.play(sound) }\n'
                  'puts [pool.class.to_s, pool.size, pool.max_voices,\n'
                  '      three[0].closed?].inspect\n')
        self.assertEqual(self.ask(source), '["SoundPool", 2, 2, true]')


class AFieldHasEltensOwnFlags(_RubyAsk):
    """`MultiLine` is 1 and `ReadOnly` is 2, and they were the other way
    round - so an application asking for a box to write a message in got
    a read-only single line, and one asking for a page to READ got an
    editable field."""

    def test_the_numbers_are_eltens(self):
        source = ('puts [EditBox::Flags::MultiLine, EditBox::Flags::ReadOnly,\n'
                  '      EditBox::Flags::Password, EditBox::Flags::Numbers,\n'
                  '      EditBox::Flags::MarkDown, EditBox::Flags::HTML].inspect\n')
        self.assertEqual(self.ask(source), '[1, 2, 4, 8, 32, 64]')

    def test_a_multiline_box_is_built_as_one(self):
        source = ('b = EditBox.new("H", type: EditBox::Flags::MultiLine)\n'
                  'spec = b.to_spec\n'
                  'puts [spec[:multiline], spec[:readonly]].inspect\n')
        self.assertEqual(self.ask(source), '[true, false]')


class WhatAControlIsWhenTheWindowIsBuilt(_RubyAsk):
    """A change made before the window exists is still a change.

    AudioMemory deals the board and only then calls `grid.focus`, so a
    spec that was the constructor's snapshot arrived on the screen empty
    and stayed empty.
    """

    def test_the_spec_is_what_the_control_is_now(self):
        source = ('g = GridBox.new(2, 2)\n'
                  'g.replace_cells([%w[a b], %w[c d]])\n'
                  'l = ListBox.new(%w[one two])\n'
                  'l.options = %w[three four]\n'
                  'puts [g.to_spec[:cells], l.to_spec[:options]].inspect\n')
        self.assertEqual(
            self.ask(source),
            '[[["a", "b"], ["c", "d"]], ["three", "four"]]')

    def test_a_property_a_control_really_keeps_is_kept_in_step(self):
        """`grid.border_sound = false` was remembered, answered, and
        ignored by the one piece of code that acts on it."""
        source = ('g = GridBox.new(2, 2)\n'
                  'g.border_sound = false\n'
                  'g.speech = false\n'
                  'puts [g.instance_variable_get(:@border_sound),\n'
                  '      g.to_spec[:speech]].inspect\n')
        self.assertEqual(self.ask(source), '[false, false]')


class TheRowTheUserIsOnComesBack(_RubyAsk):
    """The file tree is not a `ListBox`, so the selected row went
    nowhere and the file manager acted on the top of the folder
    whichever row was really selected."""

    def test_every_control_answers_for_its_own_state(self):
        source = ('t = FilesTree.new("t", path: Dir.tmpdir)\n'
                  'before = t.file\n'
                  't.apply_wire_change("index" => 1)\n'
                  'l = ListBox.new(%w[a b c])\n'
                  'l.apply_wire_change("index" => 2)\n'
                  'c = CheckBox.new("x")\n'
                  'c.apply_wire_change("checked" => true)\n'
                  'e = EditBox.new("x")\n'
                  'e.apply_wire_change("text" => "typed")\n'
                  'puts [t.file != before || t.entries.size < 2, l.index,\n'
                  '      c.checked?, e.text].inspect\n')
        self.assertEqual(self.ask(source), '[true, 2, true, "typed"]')


class TheNetworkIsEltensNetwork(_RubyAsk):
    """`read_url` is what an application calls before it has a screen -
    the YouTube client asks for its update manifests from `activate`, and
    a missing one is `NoMethodError` at class level."""

    def test_the_network_functions_are_there_at_every_level(self):
        source = ('class Netty < Program; end\n'
                  'wanted = %w[read_url download_file html_decode html_encode]\n'
                  'puts [wanted.reject { |m| Netty.respond_to?(m) },\n'
                  '      wanted.reject { |m| Netty.new.respond_to?(m) }].inspect\n')
        self.assertEqual(self.ask(source), '[[], []]')

    def test_html_is_decoded_the_way_elten_decodes_it(self):
        source = ('puts html_decode(%s).inspect\n'
                  % repr('a &lt;b&gt; &amp; c').replace("'", '"'))
        self.assertEqual(self.ask(source), '"a <b> & c"')


class TheAccountCanComeFromEltenItself(unittest.TestCase):
    """A user who has Elten installed and logged in has an EltenLink
    account here without doing anything.

    `login.dat` is Elten's own format and its auto-login key is
    DPAPI-protected, so it can be read back only by this Windows account
    on this machine - which is the right property and the same one
    Titan's own secret store relies on. A key protected with a PIN is
    deliberately NOT used: the PIN is not on the disk, and asking for one
    because a game wanted a scoreboard is not something to do unprompted.
    """

    def setUp(self):
        from eltenkit import elten_account
        self.module = elten_account

    def test_a_file_that_is_not_eltens_is_no_account(self):
        folder = tempfile.mkdtemp(prefix='elten-login-')
        path = os.path.join(folder, 'login.dat')
        io.open(path, 'wb').write(b'not an elten file at all')
        self.assertEqual(self.module.read_login_dat(path), ('', ''))

    def test_an_unencrypted_key_is_read(self):
        folder = tempfile.mkdtemp(prefix='elten-login-')
        path = os.path.join(folder, 'login.dat')
        name, token = b'somebody', b'a-token'
        raw = (self.module.MAGIC + bytes([3])
               + struct.pack('<I', len(name)) + name
               + struct.pack('<I', len(token)) + token
               + struct.pack('<b', 0))
        io.open(path, 'wb').write(raw)
        self.assertEqual(self.module.read_login_dat(path),
                         ('somebody', 'a-token'))

    def test_a_key_behind_a_pin_is_left_alone(self):
        folder = tempfile.mkdtemp(prefix='elten-login-')
        path = os.path.join(folder, 'login.dat')
        name, token = b'somebody', b'ciphertext'
        raw = (self.module.MAGIC + bytes([3])
               + struct.pack('<I', len(name)) + name
               + struct.pack('<I', len(token)) + token
               + struct.pack('<b', 2))
        io.open(path, 'wb').write(raw)
        self.assertEqual(self.module.read_login_dat(path), ('', ''))

    def test_a_truncated_file_is_no_account_rather_than_a_crash(self):
        folder = tempfile.mkdtemp(prefix='elten-login-')
        path = os.path.join(folder, 'login.dat')
        io.open(path, 'wb').write(self.module.MAGIC + b'\x03\x08')
        self.assertEqual(self.module.read_login_dat(path), ('', ''))


class EveryWidgetReallyBuilds(unittest.TestCase):
    """One of each control, built for real - and never shown.

    The Ruby half can be right about every control and the window still
    fail to appear, because what a spec asks for has to be something wx
    will build: `wx.TextValidator` is a C++ class wxPython does not wrap,
    and asking for one turned a settings form with a number in it into a
    screen that did not open. Nothing here is shown, so running the tests
    puts no window in front of anybody.
    """

    SPECS = [
        {'kind': 'button', 'label': 'Go'},
        {'kind': 'checkbox', 'label': 'Tick', 'checked': True},
        {'kind': 'editbox', 'header': 'Name', 'text': 'x'},
        {'kind': 'editbox', 'header': 'Volume', 'text': '10',
         'numbers': True},
        {'kind': 'editbox', 'header': 'Body', 'text': '', 'multiline': True},
        {'kind': 'listbox', 'header': 'List', 'options': ['a', 'b']},
        {'kind': 'listbox', 'header': 'Ticks', 'options': ['a', 'b'],
         'multi': True, 'checked': [1]},
        {'kind': 'gridbox', 'header': 'Board', 'width': 3, 'height': 3,
         'cells': [['a', 'b', 'c'], ['d', 'e', 'f'], ['g', 'h', 'i']],
         'x': 1, 'y': 1},
        {'kind': 'tablebox', 'header': 'T', 'columns': ['a', 'b'],
         'rows': [['1', '2']]},
        {'kind': 'choicelist', 'header': 'C',
         'rows': [{'label': 'r', 'options': ['x', 'y'], 'index': 1}]},
        {'kind': 'static', 'label': 'Hello'},
        {'kind': 'player', 'label': 'A station', 'status': 'playing',
         'duration': 100, 'position': 10, 'playing': True},
    ]

    @classmethod
    def setUpClass(cls):
        try:
            import wx
        except Exception as error:                     # pragma: no cover
            raise unittest.SkipTest('no wx here: %s' % error)
        cls.wx = wx
        cls.app = wx.App(False) if wx.GetApp() is None else wx.GetApp()
        cls.frame = wx.Frame(None)                     # never shown
        cls.panel = wx.Panel(cls.frame)
        from eltenkit import ui as ui_module
        cls.ui = ui_module

    @classmethod
    def tearDownClass(cls):
        try:
            cls.frame.Destroy()
        except Exception:
            pass

    def build(self, spec):
        return self.ui._build_control(self.panel, spec,
                                      lambda *a, **k: None, None)

    def test_one_of_each_kind_builds(self):
        for spec in self.SPECS:
            with self.subTest(kind=spec['kind'], header=spec.get('header')):
                self.assertIsNotNone(self.build(spec))

    def test_a_board_that_grows_really_grows_on_the_screen(self):
        """AudioMemory deals a bigger board every round, and a
        `wx.grid.Grid` keeps whatever shape it was created with - so the
        extra squares existed in Ruby and nowhere the player could reach."""
        widget = self.build(self.SPECS[7])
        widget.apply({'width': 5, 'height': 4,
                      'cells': [['x'] * 5 for _ in range(4)], 'x': 4, 'y': 3})
        self.assertEqual((widget.grid.GetNumberCols(),
                          widget.grid.GetNumberRows()), (5, 4))
        self.assertEqual((widget.grid.GetGridCursorCol(),
                          widget.grid.GetGridCursorRow()), (4, 3))

    def test_a_list_of_things_to_tick_is_titans_own_tick_list(self):
        """`wx.CheckListBox` is owner-drawn, so MSAA reports a list item
        and says nothing about whether it is ticked. Titan already has
        the control for this."""
        widget = self.build(self.SPECS[6])
        self.assertEqual(type(widget.listbox).__name__, 'CheckList')
        self.assertTrue(widget.listbox.IsChecked(1))


class SpacePressesAButton(unittest.TestCase):
    """A focused button answers Space, not just Enter and the mouse.

    The form's char hook was intercepting Space (a navigation key) and
    sending it to the application as a keystroke, so a wx button never
    fired and a screen of buttons could be reached and not pressed with
    the space bar.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import wx
        except Exception as error:                     # pragma: no cover
            raise unittest.SkipTest('no wx here: %s' % error)
        cls.wx = wx
        cls.app = wx.App(False) if wx.GetApp() is None else wx.GetApp()
        from eltenkit import ui as ui_module
        cls.ui_module = ui_module

    def press(self, code):
        wx = self.wx
        recorder = TheDispatchTable.Recorder()
        recorder._on_gui = lambda call, default=None: call()
        gui = self.ui_module.WxUI(None, 'test')
        recorder.ui = gui
        form_id = gui.open_form(recorder, [{'kind': 'button', 'label': 'Go'}])
        widget = gui._forms[form_id].widgets[0]
        widget.window.SetFocus()
        event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
        event.SetKeyCode(code)
        event.SetEventObject(widget.window)
        gui._forms[form_id].panel.GetEventHandler().ProcessEvent(event)
        presses = [m for m in recorder.written
                   if m.get('event') == 'control' and m.get('name') == 'press']
        gui.close()
        return len(presses)

    def test_space_presses_a_button(self):
        self.assertEqual(self.press(self.wx.WXK_SPACE), 1)

    def test_enter_presses_a_button(self):
        self.assertEqual(self.press(self.wx.WXK_RETURN), 1)


class ChildProcSpeaksEltensOwnMethods(_RubyAsk):
    """`running?`, `avail`, `avail_err`, `terminate` - the YouTube
    client's whole search loop is built on them, and a method that is
    merely absent is a `NoMethodError` inside the application: the search
    ended before yt-dlp had said a word."""

    def test_the_process_answers_the_loop_the_apps_use(self):
        wanted = 'running? avail avail_err terminate read read_err write close pid'.split()
        source = ('p = ChildProc.new("cmd /c echo hi", nil)\n'
                  'sleep 0.2\n'
                  'puts %s.reject { |m| p.respond_to?(m) }.inspect\n'
                  % repr(wanted).replace("'", '"'))
        self.assertEqual(self.ask('require "childproc"\n' + source), '[]')

    def test_output_is_read_the_way_an_app_reads_it(self):
        source = ('require "childproc"\n'
                  'p = ChildProc.new("cmd /c echo hello", nil)\n'
                  'out = +"".b\n'
                  '100.times do\n'
                  '  out << p.read.to_s.b if p.avail.to_i > 0\n'
                  '  break unless p.running?\n'
                  '  sleep 0.03\n'
                  'end\n'
                  'out << p.read.to_s.b if p.avail.to_i > 0\n'
                  'p.close\n'
                  'puts out.strip.inspect\n')
        self.assertEqual(self.ask(source), '"hello"')


class AFormCarriesItsHeader(_RubyAsk):
    """`Form#header=` - Elten's `FormBase` has `attr_accessor :header` and
    applications set it after building the form (the media catalogue's
    Options screen does `form.header = _("Options")`). Missing, it ended
    the application on the screen it was opening."""

    def test_a_form_takes_a_header(self):
        source = ('f = Form.new([Button.new("x")])\n'
                  'f.header = "Options"\n'
                  'puts f.header.inspect\n')
        self.assertEqual(self.ask(source), '"Options"')


class AFormTicksItsTimers(_RubyAsk):
    """`FormTimer` and `Form#add_timer` - the Game Room refreshes its
    lobby with `form.add_timer(FormTimer.new(t, repeat: true) { ... })`,
    and a missing `FormTimer` stopped it before its screen was up."""

    def test_a_form_timer_fires_after_its_time(self):
        source = ('t = FormTimer.new(0.05, repeat: false) { $fired = true }\n'
                  'sleep 0.1\n'
                  't.update\n'
                  'puts ($fired == true).inspect\n')
        self.assertEqual(self.ask(source), 'true')

    def test_a_form_holds_a_timer(self):
        source = ('f = Form.new([Button.new("x")])\n'
                  'f.add_timer(FormTimer.new(0.0, repeat: true) { })\n'
                  'puts f.respond_to?(:add_timer).inspect\n')
        self.assertEqual(self.ask(source), 'true')


class EveryAppsMenuIsFlat(_RubyAsk):
    """No oddities in any application's menu.

    Elten's `context` takes a `submenu` flag - true wraps each binding
    under a heading (for a menu BAR), false pours the options straight in
    (a context menu). Titan opened it as a menu bar for Alt and flat for
    the Applications key, and these applications have no menu bar - so the
    menu-bar path only ever added an oddity: an unnamed menu became a
    literal "Context menu" entry you had to open to reach anything. Now
    every gesture opens the same flat menu.
    """

    def test_a_bound_menu_has_no_context_menu_wrapper(self):
        source = ('l = ListBox.new(%w[a b c])\n'
                  'l.bind_context { |m| m.option("Add") {}; m.option("Remove") {} }\n'
                  'Form.new([l]).present\n'
                  'menu = Menu.new("", :context)\n'
                  'l.context(menu, false)\n'
                  'puts menu._menu_items.map { |i| i["label"] }.inspect\n')
        self.assertEqual(self.ask(source), '["Add", "Remove"]')

    def test_opening_it_any_way_gives_the_same_flat_menu(self):
        """`open_context_menu` builds flat whether Alt or the Applications
        key asked - the `as_menu_bar` flag is ignored, so there is no
        second, odder shape of the same menu."""
        source = ('captured = nil\n'
                  'l = ListBox.new(%w[a])\n'
                  'l.bind_context { |m| m.option("Only") {} }\n'
                  'form = Form.new([l])\n'
                  'def form.popup_menu(_c, items); $seen = items; nil; end\n'
                  'form.present\n'
                  'l.open_context_menu(false)\n'
                  'flat = $seen.map { |i| i["label"] }\n'
                  'l.open_context_menu(true)\n'
                  'bar = $seen.map { |i| i["label"] }\n'
                  'puts [flat, bar].inspect\n')
        self.assertEqual(self.ask(source), '[["Only"], ["Only"]]')


class AProtectedTableFallsBackToTitanNet(_RubyAsk):
    """A game whose EltenLink leaderboard is a PROTECTED table - one only
    Elten's own signed launcher may write - gets a real, shared
    scoreboard that is Titan's, on Titan-Net. Titan does not mint the
    launcher stamp: that would be writing Titan-played scores onto
    somebody else's global leaderboard through the check that exists to
    stop exactly that."""

    PREAMBLE = _RubyAsk.PREAMBLE

    def ask_with_stub(self, source):
        # A bridge whose 'elten_app' refuses inserts as PROTECTED and
        # keeps the shared board in memory, so the fallback can be tested
        # with no network at all.
        stub = '''
module EltenBridge
  class Closed < StandardError; end
  @shared = []
  def self.call(op, args = {})
    return nil unless op == 'elten_app'
    case args['do']
    when 'signed_in' then false
    when 'shared_available' then true
    when 'insert' then raise 'this application keeps its rows in a PROTECTED table'
    when 'select' then raise 'this application keeps its rows in a PROTECTED table'
    when 'shared_insert' then (@shared << args['values']; args['values'])
    when 'shared_select' then @shared.dup
    else nil
    end
  end
  def self.notify(*_a); nil; end
  def self.now; Time.now.to_f; end
  def self.next_event(*_a); :timeout; end
end
module Log
  def self.warning(*_a); end
  def self.error(*_a); end
  def self.debug(*_a); end
  def self.info(*_a); end
end
$LOAD_PATH.unshift(%s)
require 'loop'
require 'eapi'
require 'program'
require 'controls'
require 'server'
require 'paths'
require 'program_api'
require 'settings'
require 'audio'
require 'eltenlink'
require 'eltenapi'
require 'network'
''' % repr(os.path.join(COMPONENT, 'eapi')).replace("'", '"')
        path = os.path.join(tempfile.mkdtemp(prefix='elten-ask-'), 'ask.rb')
        io.open(path, 'w', encoding='utf-8').write(stub + source)
        answer = subprocess.run([self.ruby.path, path], capture_output=True,
                                timeout=120, env=self.ruby.environment())
        self.assertEqual(answer.returncode, 0,
                         answer.stderr.decode('utf-8', 'replace'))
        return answer.stdout.decode('utf-8', 'replace').strip()

    def test_a_refused_score_goes_to_the_shared_board_and_reads_back(self):
        source = ('class Prot < Program; end\n'
                  'Prot.manifest = {"id" => "u"}\n'
                  'Prot.server_app(uuid: "u", tables: {}, protected: true)\n'
                  'table = Prot.server_table("scores")\n'
                  'table.insert("points" => 9)\n'
                  'rows = table.all(order: ["points", "desc"])\n'
                  'puts [table.shared?, rows.map { |r| r["points"] }].inspect\n')
        self.assertEqual(self.ask_with_stub(source), '[true, [9]]')

    def test_the_game_still_offers_to_share_after_a_refusal(self):
        source = ('class Prot2 < Program; end\n'
                  'Prot2.manifest = {"id" => "u"}\n'
                  'Prot2.server_app(uuid: "u", tables: {}, protected: true)\n'
                  'table = Prot2.server_table("scores")\n'
                  'table.insert("points" => 1)\n'
                  'puts table.available?.inspect\n')
        self.assertEqual(self.ask_with_stub(source), 'true')


class TheRealWidgetsReportThroughTheRealSendEvent(unittest.TestCase):
    """The widget -> form -> `send_event` path, in real wx.

    This is the test that catches a bug the scripted double cannot: a
    widget reporting a field whose name collides with one `send_event`
    already binds. The grid did exactly that - it reported `control=` (the
    Control modifier) and `send_event` already binds `control` (which
    control it is), so every arrow key raised `TypeError` inside the wx
    handler and the board could not be moved at all. Nothing here shows a
    window; everything is a real wx control fired with real wx events.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import wx
        except Exception as error:                     # pragma: no cover
            raise unittest.SkipTest('no wx here: %s' % error)
        cls.wx = wx
        cls.app = wx.App(False) if wx.GetApp() is None else wx.GetApp()
        from eltenkit import ui as ui_module
        cls.ui_module = ui_module

    def make(self):
        """A real `WxUI` and a real `Application` that captures the wire."""
        wx = self.wx
        recorder = TheDispatchTable.Recorder()
        recorder._on_gui = lambda call, default=None: call()
        gui = self.ui_module.WxUI(None, 'test')
        recorder.ui = gui
        return recorder, gui

    def messages(self, recorder, name):
        return [m for m in recorder.written
                if m.get('event') == 'control' and m.get('name') == name]

    def fire_char(self, window, code, **mods):
        wx = self.wx
        event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
        event.SetKeyCode(code)
        event.SetEventObject(window)
        window.GetEventHandler().ProcessEvent(event)

    def widget_of(self, gui, form_id, index):
        return gui._forms[form_id].widgets[index]

    def test_a_grid_arrow_reports_without_raising(self):
        wx = self.wx
        recorder, gui = self.make()
        form_id = gui.open_form(recorder, [
            {'kind': 'gridbox', 'header': 'B', 'width': 3, 'height': 3,
             'cells': [['a', 'b', 'c'], ['d', 'e', 'f'], ['g', 'h', 'i']]}])
        widget = self.widget_of(gui, form_id, 0)
        self.fire_char(widget.grid, wx.WXK_RIGHT)
        moved = self.messages(recorder, 'key_right')
        self.assertEqual(len(moved), 1,
                         'the arrow did not reach the application: %r'
                         % recorder.written[-3:])
        # The control INDEX is still there, and the modifier is `ctrl`,
        # not `control` - the collision that broke the board.
        self.assertEqual(moved[0].get('control'), 0)
        self.assertIn('ctrl', moved[0])
        gui.close()

    def test_a_grid_choose_key_reports(self):
        wx = self.wx
        recorder, gui = self.make()
        form_id = gui.open_form(recorder, [
            {'kind': 'gridbox', 'header': 'B', 'width': 2, 'height': 2,
             'cells': [['a', 'b'], ['c', 'd']]}])
        widget = self.widget_of(gui, form_id, 0)
        self.fire_char(widget.grid, wx.WXK_RETURN)
        self.assertEqual(len(self.messages(recorder, 'key_enter')), 1)
        gui.close()

    def test_space_on_a_listbox_reaches_the_application(self):
        """The file manager's Space, which reads or plays the file the
        cursor is on. The widget must forward it - not swallow it as a
        list selection."""
        wx = self.wx
        recorder, gui = self.make()
        form_id = gui.open_form(recorder, [
            {'kind': 'listbox', 'header': 'Files', 'options': ['a.txt',
                                                               'b.ogg']}])
        widget = self.widget_of(gui, form_id, 0)
        self.fire_char(widget.listbox, wx.WXK_SPACE)
        # It may arrive as a control event, on the key stream, or both -
        # what matters is that the application heard the space.
        control = self.messages(recorder, 'key_space')
        stream = [m for m in recorder.written
                  if m.get('event') == 'key' and m.get('name') == 'key_space']
        self.assertTrue(control or stream,
                        'space never reached the application: %r'
                        % recorder.written[-4:])
        gui.close()

    def test_a_listbox_move_reports_the_new_index(self):
        wx = self.wx
        recorder, gui = self.make()
        form_id = gui.open_form(recorder, [
            {'kind': 'listbox', 'header': 'L', 'options': ['a', 'b', 'c']}])
        widget = self.widget_of(gui, form_id, 0)
        # The native selection move an arrow key makes.
        widget.listbox.SetSelection(2)
        event = wx.CommandEvent(wx.wxEVT_LISTBOX, widget.listbox.GetId())
        event.SetEventObject(widget.listbox)
        widget.listbox.GetEventHandler().ProcessEvent(event)
        changed = self.messages(recorder, 'changed')
        self.assertTrue(changed, 'the move was not reported')
        self.assertEqual(changed[-1].get('index'), 2)
        gui.close()

    def test_escape_reaches_both_the_form_and_a_runner(self):
        """Escape on a form-hosted control must do TWO things: the form's
        own back/cancel, AND land on the key stream so a `Runner` that
        binds `key_escape` hears it. AudioMemory shows its board on a form
        and asks "abort the game?" from `runner.on_key(:key_escape)`;
        without the key on the stream, Escape on the board did nothing and
        the game could not be left except by closing the window."""
        wx = self.wx
        recorder, gui = self.make()
        form_id = gui.open_form(recorder, [
            {'kind': 'gridbox', 'header': 'B', 'width': 2, 'height': 2,
             'cells': [['a', 'b'], ['c', 'd']]}])
        widget = self.widget_of(gui, form_id, 0)
        self.fire_char(widget.grid, wx.WXK_ESCAPE)
        escape = self.messages(recorder, 'escape')
        stream = [m for m in recorder.written
                  if m.get('event') == 'key' and m.get('name') == 'key_escape']
        self.assertTrue(escape, 'the form was not told to back out')
        self.assertTrue(stream, 'a Runner would never hear the Escape')
        gui.close()

    def test_the_player_keys_are_eltens(self):
        """Elten's whole player keymap, in real wx: Space, the arrows, the
        Shift and Ctrl families, Backspace, Home/End, the page keys - and
        each reports the action the mixer really carries out."""
        wx = self.wx
        recorder, gui = self.make()
        form_id = gui.open_form(recorder, [
            {'kind': 'player', 'label': 'S', 'status': 'playing',
             'duration': 100, 'position': 5, 'playing': True}])
        widget = self.widget_of(gui, form_id, 0)

        def player_do(code, shift=False, control=False):
            event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
            event.SetKeyCode(code)
            if shift:
                event.SetShiftDown(True) if hasattr(event, 'SetShiftDown') \
                    else None
            event.SetEventObject(widget.state)
            # wx.KeyEvent modifiers are read-only on some builds; drive the
            # handler with a tiny shim that reports the modifier state.
            widget.state.GetEventHandler().ProcessEvent(event)
            for m in reversed(recorder.written):
                if m.get('event') == 'control' and m.get('name') == 'player':
                    return m.get('do')
            return None

        # Plain keys are unambiguous without faking modifier state.
        self.assertEqual(player_do(wx.WXK_SPACE), 'toggle')
        self.assertEqual(player_do(wx.WXK_LEFT), 'back')
        self.assertEqual(player_do(wx.WXK_RIGHT), 'forward')
        self.assertEqual(player_do(wx.WXK_UP), 'louder')
        self.assertEqual(player_do(wx.WXK_DOWN), 'quieter')
        self.assertEqual(player_do(wx.WXK_HOME), 'start')
        self.assertEqual(player_do(wx.WXK_END), 'end')
        self.assertEqual(player_do(wx.WXK_PAGEUP), 'chapter_prev')
        self.assertEqual(player_do(wx.WXK_PAGEDOWN), 'chapter_next')
        self.assertEqual(player_do(wx.WXK_BACK), 'reset')
        gui.close()

    def test_the_seek_bar_seeks_where_it_is_dragged(self):
        """The mouse - a real draggable seek bar, which Elten (all ear)
        has no equivalent of and this desktop should."""
        wx = self.wx
        recorder, gui = self.make()
        form_id = gui.open_form(recorder, [
            {'kind': 'player', 'label': 'S', 'duration': 200, 'playing': True}])
        widget = self.widget_of(gui, form_id, 0)
        widget.seek.SetValue(500)                      # halfway
        event = wx.ScrollEvent(wx.wxEVT_SCROLL_CHANGED, widget.seek.GetId())
        event.SetEventObject(widget.seek)
        widget.seek.GetEventHandler().ProcessEvent(event)
        seeks = [m for m in recorder.written
                 if m.get('name') == 'player' and m.get('do') == 'seek_to']
        self.assertTrue(seeks, 'dragging the bar did not seek')
        self.assertAlmostEqual(seeks[-1].get('value'), 100.0, delta=1.0)
        gui.close()

    def test_a_right_click_opens_the_player_menu(self):
        wx = self.wx
        recorder, gui = self.make()
        form_id = gui.open_form(recorder, [
            {'kind': 'player', 'label': 'S', 'duration': 100}])
        widget = self.widget_of(gui, form_id, 0)
        event = wx.ContextMenuEvent(wx.wxEVT_CONTEXT_MENU, widget.state.GetId())
        event.SetEventObject(widget.state)
        widget.state.GetEventHandler().ProcessEvent(event)
        self.assertTrue(self.messages(recorder, 'context'),
                        'the right click did not open the menu')
        gui.close()

    def test_a_button_press_reports(self):
        wx = self.wx
        recorder, gui = self.make()
        form_id = gui.open_form(recorder, [{'kind': 'button', 'label': 'Go'}])
        widget = self.widget_of(gui, form_id, 0)
        event = wx.CommandEvent(wx.wxEVT_BUTTON, widget.window.GetId())
        event.SetEventObject(widget.window)
        widget.window.GetEventHandler().ProcessEvent(event)
        self.assertTrue(self.messages(recorder, 'press'))
        gui.close()

    def test_a_tick_reports_which_row_and_its_state(self):
        wx = self.wx
        recorder, gui = self.make()
        form_id = gui.open_form(recorder, [
            {'kind': 'listbox', 'header': 'T', 'options': ['a', 'b'],
             'multi': True}])
        widget = self.widget_of(gui, form_id, 0)
        widget.listbox.Check(1, True)
        event = wx.CommandEvent(wx.wxEVT_CHECKLISTBOX, widget.listbox.GetId())
        event.SetInt(1)
        event.SetEventObject(widget.listbox)
        widget.listbox.GetEventHandler().ProcessEvent(event)
        ticked = self.messages(recorder, 'ticked')
        self.assertTrue(ticked, 'the tick was not reported')
        self.assertEqual(ticked[-1].get('index'), 1)
        self.assertTrue(ticked[-1].get('checked'))
        gui.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
