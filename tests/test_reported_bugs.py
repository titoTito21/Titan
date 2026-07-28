# -*- coding: utf-8 -*-
"""
Regression tests for the batch of user-reported bugs.

Each test names the symptom it locks down:

1. Deleting feedback/ideas did nothing - the confirmation result was compared
   against ``wx.YES`` (2) while the skinned dialog returns ``wx.ID_YES`` (5103),
   so every confirmation was read as a refusal.
2. Telegram calls posted ``[TCE:CALL:...]`` markers into the recipient's chat,
   which looked like a hijacked account.
3. Telegram reported a call as connected before it was answered.
4. Voice Activation silently switched itself off when ``webrtcvad`` had no wheel
   for the running Python, leaving a permanently open microphone.
5. A voice-room listener without Opus played compressed frames as raw PCM.
"""

import os
import re
import sys
import threading
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# 1. Confirmation dialogs
# ---------------------------------------------------------------------------

class ConfirmDialogResultTest(unittest.TestCase):
    """wx.MessageDialog.ShowModal() never returns wx.YES."""

    def test_wx_yes_and_id_yes_are_different(self):
        import wx
        self.assertNotEqual(wx.YES, wx.ID_YES)

    def test_no_skinned_confirmation_compares_against_wx_yes(self):
        """Any `== wx.YES` left in src/ must come from a real wx.MessageBox."""
        offenders = []
        pattern = re.compile(r'(==|!=)\s*wx\.(YES|NO)\b')
        for root, _dirs, files in os.walk(os.path.join(REPO, 'src')):
            for name in files:
                if not name.endswith('.py'):
                    continue
                path = os.path.join(root, name)
                with open(path, encoding='utf-8', errors='replace') as fh:
                    lines = fh.readlines()
                for idx, line in enumerate(lines):
                    if not pattern.search(line):
                        continue
                    # Walk back a few lines to find where the value came from.
                    context = ''.join(lines[max(0, idx - 8):idx + 1])
                    if 'wx.MessageBox' in context:
                        continue  # MessageBox really does return wx.YES
                    offenders.append(f"{os.path.relpath(path, REPO)}:{idx + 1}")
        self.assertEqual(offenders, [], "compared against wx.YES but the value "
                                        "came from a ShowModal()-based helper")

    def test_confirmed_delete_reaches_the_client(self):
        """Confirming the dialog must actually call delete_feedback()."""
        import wx
        from src.network import feedback_hub

        calls = []

        class FakeClient:
            user_id = 7
            is_admin = False
            user_role = 'user'

            def delete_feedback(self, feedback_id):
                calls.append(feedback_id)
                return {'success': True}

        original = feedback_hub._show_skinned_message
        feedback_hub._show_skinned_message = lambda *a, **kw: wx.ID_YES
        try:
            stub = types.SimpleNamespace(
                item={'title': 'Multi media, Youtube in Particular', 'author_id': 7},
                feedback_id=37,
                titan_client=FakeClient(),
                _on_delete_result=lambda *a, **kw: None,
            )
            feedback_hub.FeedbackDetailDialog._on_delete(stub, None)
            # _on_delete dispatches on a worker thread.
            for thread in threading.enumerate():
                if thread is not threading.current_thread() and thread.daemon:
                    thread.join(timeout=5)
        finally:
            feedback_hub._show_skinned_message = original

        self.assertEqual(calls, [37], "delete_feedback was never called")

    def test_declined_delete_does_not_reach_the_client(self):
        import wx
        from src.network import feedback_hub

        calls = []

        class FakeClient:
            def delete_feedback(self, feedback_id):
                calls.append(feedback_id)
                return {'success': True}

        original = feedback_hub._show_skinned_message
        feedback_hub._show_skinned_message = lambda *a, **kw: wx.ID_NO
        try:
            stub = types.SimpleNamespace(
                item={'title': 'x', 'author_id': 7},
                feedback_id=37,
                titan_client=FakeClient(),
                _on_delete_result=lambda *a, **kw: None,
            )
            feedback_hub.FeedbackDetailDialog._on_delete(stub, None)
        finally:
            feedback_hub._show_skinned_message = original

        self.assertEqual(calls, [], "a declined confirmation still deleted")


# ---------------------------------------------------------------------------
# 2 + 3. Telegram voice calls
# ---------------------------------------------------------------------------

class TelegramVoiceTest(unittest.TestCase):

    def _source(self):
        path = os.path.join(REPO, 'src', 'network', 'telegram_voice.py')
        with open(path, encoding='utf-8', errors='replace') as fh:
            return fh.read()

    def test_no_marker_message_is_ever_sent(self):
        """Nothing may post a call marker into the peer's conversation."""
        source = self._source()
        sends = re.findall(r'send_message\([^)]*\)', source)
        self.assertEqual(sends, [], f"still sending chat messages: {sends}")

    def test_marker_constants_are_not_formatted_into_outgoing_text(self):
        source = self._source()
        self.assertNotIn('{CALL_REQUEST_PREFIX}', source)
        self.assertNotIn('{CALL_END_PREFIX}', source)

    def test_ringing_state_exists_and_start_call_uses_it(self):
        """An unanswered call must not be reported as connected."""
        source = self._source()
        self.assertIn("RINGING = 'ringing'", source)
        start = source.index('async def start_call')
        end = source.index('# === MICROPHONE ===', start)
        body = source[start:end]
        self.assertIn('self.RINGING', body)
        self.assertNotIn('self.CONNECTED', body,
                         "start_call still marks the call connected directly")

    def test_connected_transition_is_guarded(self):
        source = self._source()
        start = source.index('def _mark_connected')
        body = source[start:start + 600]
        self.assertIn('if self.state != self.RINGING', body)


# ---------------------------------------------------------------------------
# 4. Voice Activation without a C extension
# ---------------------------------------------------------------------------

def _pcm(samples):
    import struct
    return struct.pack('<%dh' % len(samples), *samples)


def _tone(freq, ms=30, rate=16000, amplitude=6000):
    import math
    n = int(rate * ms / 1000)
    return _pcm([int(amplitude * math.sin(2 * math.pi * freq * i / rate))
                 for i in range(n)])


def _silence(ms=30, rate=16000):
    return _pcm([0] * int(rate * ms / 1000))


def _hiss(ms=30, rate=16000, amplitude=40):
    import random
    rng = random.Random(1234)
    n = int(rate * ms / 1000)
    return _pcm([rng.randint(-amplitude, amplitude) for _ in range(n)])


class PureVadTest(unittest.TestCase):

    def setUp(self):
        from src.network.vad_fallback import Vad
        self.Vad = Vad

    def test_silence_is_not_speech(self):
        vad = self.Vad(0)
        for _ in range(5):
            vad.is_speech(_silence(), 16000)
        self.assertFalse(vad.is_speech(_silence(), 16000))

    def test_quiet_room_hiss_is_not_speech(self):
        vad = self.Vad(1)
        results = [vad.is_speech(_hiss(), 16000) for _ in range(30)]
        self.assertFalse(any(results[10:]), "room noise was treated as speech")

    def test_voiced_tone_is_speech(self):
        vad = self.Vad(0)
        for _ in range(10):
            vad.is_speech(_hiss(), 16000)   # learn the noise floor
        self.assertTrue(vad.is_speech(_tone(220), 16000))

    def test_hangover_bridges_a_short_gap(self):
        vad = self.Vad(0)
        for _ in range(10):
            vad.is_speech(_hiss(), 16000)
        self.assertTrue(vad.is_speech(_tone(220), 16000))
        # A single silent frame mid-word must not close the gate.
        self.assertTrue(vad.is_speech(_silence(), 16000))

    def test_rejects_unsupported_sample_rate(self):
        vad = self.Vad(0)
        with self.assertRaises(ValueError):
            vad.is_speech(_silence(), 44100)

    def test_all_aggressiveness_levels_work(self):
        for level in (0, 1, 2, 3):
            vad = self.Vad(level)
            self.assertIsInstance(vad.is_speech(_silence(), 16000), bool)

    def test_get_vad_always_returns_a_detector(self):
        from src.network.vad_fallback import get_vad
        vad, backend = get_vad(0)
        self.assertIsNotNone(vad)
        self.assertIn(backend, ('webrtcvad', 'builtin'))
        self.assertIsInstance(vad.is_speech(_silence(), 16000), bool)


class VoiceCaptureVadTest(unittest.TestCase):

    def test_enabling_vad_is_never_silently_refused(self):
        """use_vad = True used to flip itself back to False without webrtcvad."""
        from src.network.voice_capture import VoiceCaptureManager
        manager = VoiceCaptureManager(sample_rate=16000, chunk_duration_ms=20,
                                      use_vad=False)
        manager.use_vad = True
        self.assertTrue(manager.use_vad)
        self.assertIsNotNone(manager.vad)

    def test_vad_errors_do_not_mute_the_speaker(self):
        """A backend that cannot judge a frame must transmit, not drop it."""
        from src.network.voice_capture import VoiceCaptureManager
        manager = VoiceCaptureManager(use_vad=True)

        class Broken:
            def is_speech(self, buf, rate):
                raise RuntimeError("bad frame size")

        manager.vad = Broken()
        self.assertTrue(manager._check_vad(_silence()))


# ---------------------------------------------------------------------------
# 5. Voice-room frame decoding
# ---------------------------------------------------------------------------

class VoiceFrameDecodeTest(unittest.TestCase):
    """A compressed frame must never be played as raw PCM."""

    def _decode(self, payload, opus_available):
        from src.network import titan_net_gui, voice_codec

        original = voice_codec.OPUS_AVAILABLE
        voice_codec.OPUS_AVAILABLE = opus_available
        try:
            stub = types.SimpleNamespace(
                _OPUS_FRAME_MAX_BYTES=titan_net_gui.TitanNetMainWindow._OPUS_FRAME_MAX_BYTES,
                _opus_decoders={},
            )
            return titan_net_gui.TitanNetMainWindow._decode_and_resample_chunk(
                stub, payload, user_id=42)
        finally:
            voice_codec.OPUS_AVAILABLE = original

    def test_opus_frame_is_dropped_when_opus_is_unavailable(self):
        opus_like = bytes(range(60))
        self.assertIsNone(self._decode(opus_like, opus_available=False),
                          "compressed frame would have been played as PCM noise")

    def test_raw_pcm_frame_still_plays(self):
        pcm = _silence(20)          # 640 bytes, the normal PCM frame
        result = self._decode(pcm, opus_available=False)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 320)

    def test_empty_frame_is_ignored(self):
        self.assertIsNone(self._decode(b'', opus_available=False))


# ---------------------------------------------------------------------------
# Microphone permission
# ---------------------------------------------------------------------------

class MicPermissionTest(unittest.TestCase):

    def test_check_runs_and_reports_a_known_reason(self):
        from src.system import mic_permission
        ok, reason = mic_permission.check_microphone()
        self.assertIsInstance(ok, bool)
        self.assertIn(reason, (
            mic_permission.REASON_ALLOWED,
            mic_permission.REASON_GLOBAL_DENIED,
            mic_permission.REASON_DESKTOP_DENIED,
            mic_permission.REASON_NO_DEVICE,
            mic_permission.REASON_UNKNOWN,
        ))

    def test_every_failure_reason_has_actionable_text(self):
        from src.system import mic_permission
        for reason in (mic_permission.REASON_GLOBAL_DENIED,
                       mic_permission.REASON_DESKTOP_DENIED,
                       mic_permission.REASON_NO_DEVICE):
            text = mic_permission.explain(reason)
            self.assertTrue(text.strip())
            self.assertNotEqual(text, mic_permission.explain('nonsense'))

    def test_denied_desktop_switch_is_detected(self):
        """Simulate the switch that silently breaks desktop-app capture."""
        from src.system import mic_permission
        original = mic_permission._read_consent_value
        mic_permission._read_consent_value = (
            lambda sub: 'Deny' if sub == 'NonPackaged' else 'Allow')
        try:
            allowed, reason = mic_permission.microphone_privacy_state()
        finally:
            mic_permission._read_consent_value = original
        if sys.platform == 'win32':
            self.assertFalse(allowed)
            self.assertEqual(reason, mic_permission.REASON_DESKTOP_DENIED)


if __name__ == '__main__':
    unittest.main(verbosity=2)
