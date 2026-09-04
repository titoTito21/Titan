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

import json
import os
import shutil
import struct
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
