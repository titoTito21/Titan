"""
Tests for Blackwall - the layer that recognises an attack rather than counting
one, and the guardrails on the part of it that a model drives.

No test here reaches the network. The model is replaced by a function that
returns a fixed answer, which is the only way to test that a WRONG answer is
refused: an invented address, a low-confidence verdict, an attempt to lift
somebody else's ban.

Run directly:  python test_blackwall.py
"""

import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blackwall as B  # noqa: E402
import cerberus as C  # noqa: E402


def _WithModel(wall, answer):
    """The same Blackwall, with the model replaced by a fixed answer. A
    subclass rather than a patched attribute, because ``ai_enabled`` is a
    property that asks whether the SDK is installed."""

    class Talkative(type(wall)):
        @property
        def ai_enabled(self):
            return True

    wall.__class__ = Talkative
    wall._generate = lambda prompt: answer
    return wall


def build(**kw):
    d = tempfile.mkdtemp()
    cerb = C.CerberusProtocol(log_dir=os.path.join(d, "logs"))
    wall = B.Blackwall(cerb, memory_path=os.path.join(d, "memory.json"),
                       api_key="", **kw)
    wall.transcript_path = os.path.join(d, "transcript.log")
    cerb.on_login_attempt = wall.observe_login
    cerb.on_account_event = (
        lambda kind, ip, detail, extra: wall.observe_event(kind, ip, detail, extra))
    return cerb, wall


def sweep(wall, ip, names, gap=0.0):
    for name in names:
        wall.observe_login(ip, name, source="ssh")
        if gap:
            time.sleep(gap)


class Fingerprints(unittest.TestCase):
    def test_a_script_is_told_from_a_person_by_its_rhythm(self):
        fp = B.Fingerprint("1.1.1.1")
        now = time.time()
        # A metronome: one attempt every two seconds, to the millisecond.
        for i in range(8):
            fp._times.append(now + i * 2.0)
        self.assertTrue(fp.is_machine_paced())

    def test_a_person_is_not_machine_paced(self):
        fp = B.Fingerprint("1.1.1.2")
        now = time.time()
        for gap in (3, 19, 26, 61, 95, 140):
            fp._times.append(now + gap)
        self.assertFalse(fp.is_machine_paced())

    def test_the_same_account_list_reads_as_the_same_tool(self):
        a, b = B.Fingerprint("1.1.1.3"), B.Fingerprint("1.1.1.4")
        for name in ("root", "admin", "ubuntu", "debian"):
            a.observe(username=name, source="ssh", reserved=True)
            b.observe(username=name, source="ssh", reserved=True)
        self.assertGreaterEqual(a.similarity(b), 0.8)

    def test_different_behaviour_is_not_correlated(self):
        a, b = B.Fingerprint("1.1.1.5"), B.Fingerprint("1.1.1.6")
        a.observe(username="alice")
        b.observe(username="zbigniew")
        self.assertLess(a.similarity(b), 0.3)


class Campaigns(unittest.TestCase):
    """Addresses that stay under every threshold, and are obviously one thing."""

    def test_one_operation_behind_many_addresses_is_banned_as_one(self):
        cerb, wall = build()
        names = ["postgres", "jenkins", "tomcat"]
        ips = ["45.9.1.7", "77.83.2.8", "185.4.3.9"]
        for ip in ips:
            for n in names:
                wall.observe_login(ip, n, source="ssh")
        wall.correlate()
        for ip in ips:
            self.assertTrue(cerb.is_ip_banned(ip), ip)

    def test_unrelated_sources_are_left_alone(self):
        cerb, wall = build()
        wall.observe_login("45.9.1.10", "alice")
        wall.observe_login("77.83.2.11", "bartek")
        wall.observe_login("185.4.3.12", "celina")
        wall.correlate()
        for ip in ("45.9.1.10", "77.83.2.11", "185.4.3.12"):
            self.assertFalse(cerb.is_ip_banned(ip), ip)

    def test_two_addresses_are_not_yet_a_campaign(self):
        cerb, wall = build()
        for ip in ("45.9.1.13", "77.83.2.14"):
            for n in ("postgres", "jenkins", "tomcat"):
                wall.observe_login(ip, n)
        wall.correlate()
        self.assertFalse(cerb.is_ip_banned("45.9.1.13"))

    def test_a_whitelisted_address_is_never_a_member(self):
        cerb, wall = build()
        cerb.add_whitelisted_ip("45.9.1.15")
        for ip in ("45.9.1.15", "77.83.2.16", "185.4.3.17", "91.5.6.18"):
            for n in ("postgres", "jenkins", "tomcat"):
                wall.observe_login(ip, n)
        wall.correlate()
        self.assertFalse(cerb.is_ip_banned("45.9.1.15"))


class Memory(unittest.TestCase):
    """A campaign only has to be earned once."""

    def test_a_returning_campaign_is_refused_on_sight(self):
        cerb, wall = build()
        names = ["oracle", "vagrant", "ftpuser"]
        for ip in ("45.9.20.1", "77.83.20.2", "185.4.20.3"):
            for n in names:
                wall.observe_login(ip, n)
        wall.correlate()
        self.assertTrue(wall.memory.entries)

        # A brand new address, three attempts, nothing else known about it.
        cerb2, wall2 = build()
        wall2.memory = wall.memory
        for n in names:
            wall2.observe_login("212.7.7.7", n)
        self.assertTrue(cerb2.is_ip_banned("212.7.7.7"))

    def test_memory_survives_being_written_and_read(self):
        cerb, wall = build()
        wall.memory.remember({"usernames": ["root", "admin"]},
                             ["1.2.3.4"], "test campaign")
        again = B.ThreatMemory(wall.memory.path)
        self.assertEqual(len(again.entries), 1)
        self.assertEqual(again.entries[0]["label"], "test campaign")

    def test_an_unrelated_source_is_not_recognised(self):
        cerb, wall = build()
        wall.memory.remember({"usernames": ["root", "admin", "ubuntu"]},
                             ["1.2.3.4"], "old campaign")
        wall.observe_login("212.7.7.8", "alice")
        wall.observe_login("212.7.7.8", "alice2")
        self.assertFalse(cerb.is_ip_banned("212.7.7.8"))


class Posture(unittest.TestCase):
    def test_thresholds_tighten_under_attack_and_are_given_back(self):
        cerb, wall = build()
        base = cerb.lockdown_failed_logins
        for i in range(wall.siege_attackers):
            for _ in range(3):
                wall.observe_login(f"45.9.30.{i}", f"user{i}")
        self.assertEqual(wall.assess_posture(), "siege")
        wall.apply_posture()
        self.assertLess(cerb.lockdown_failed_logins, base)
        # And when it is over, the users who did nothing get the old numbers.
        wall._fingerprints.clear()
        wall.apply_posture()
        self.assertEqual(cerb.lockdown_failed_logins, base)

    def test_a_quiet_server_stays_calm(self):
        cerb, wall = build()
        wall.observe_login("45.9.31.1", "alice")
        self.assertEqual(wall.assess_posture(), "calm")


class Voice(unittest.TestCase):
    """Blackwall answers an attacker - and nobody else."""

    def test_nothing_is_said_to_a_user_who_mistyped(self):
        cerb, wall = build()
        for _ in range(6):
            cerb.record_failed_login("45.9.40.1", "alice")
        self.assertIsNone(wall.warn("45.9.40.1", "alice"))

    def test_an_attacker_is_answered_and_the_tone_escalates(self):
        cerb, wall = build()
        first = wall.warn("45.9.40.2", "root")
        self.assertIsNotNone(first)
        self.assertEqual(first["stage"], 0)
        second = wall.warn("45.9.40.2", "root")
        self.assertEqual(second["stage"], 1)
        self.assertNotEqual(first["message"], second["message"])

    def test_what_was_said_is_written_down(self):
        cerb, wall = build()
        said = wall.warn("45.9.40.3", "administrator")
        entries = wall.transcript()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["ip"], "45.9.40.3")
        self.assertEqual(entries[0]["said"], said["message"])
        with open(wall.transcript_path, encoding="utf-8") as f:
            written = json.loads(f.readline())
        self.assertEqual(written["said"], said["message"])

    def test_the_transcript_can_be_read_back_per_address(self):
        cerb, wall = build()
        wall.warn("45.9.40.4", "root")
        wall.warn("45.9.40.5", "root")
        self.assertEqual(len(wall.said_to("45.9.40.4")), 1)

    def test_the_terminal_form_is_plain_ascii(self):
        cerb, wall = build()
        wall.observe_login("45.9.40.6", "root")
        text = wall.terminal_message("45.9.40.6")
        text.encode("ascii")           # raises if it is not
        self.assertIn("BLACKWALL", text.replace(" ", ""))
        self.assertIn("45.9.40.6", text)

    def test_the_tar_pit_banner_is_recorded_too(self):
        cerb, wall = build()
        lines = wall.tarpit_lines("45.9.40.7")
        self.assertTrue(lines)
        self.assertEqual(wall.transcript()[-1]["channel"], "tarpit")

    def test_a_whitelisted_address_is_never_addressed(self):
        cerb, wall = build()
        cerb.add_whitelisted_ip("45.9.40.8")
        self.assertIsNone(wall.warn("45.9.40.8", "root"))


class ModelGuardrails(unittest.TestCase):
    """The model advises. These are the things it cannot do."""

    def telemetry(self, wall, ips):
        for ip in ips:
            wall.observe_login(ip, "root")
        return wall._telemetry()

    def test_an_invented_address_is_discarded(self):
        cerb, wall = build()
        tel = self.telemetry(wall, ["45.9.50.1"])
        wall._apply({"verdicts": [
            {"ip": "8.8.8.8", "action": "permaban", "confidence": 1.0,
             "reason": "invented"}]}, tel)
        self.assertFalse(cerb.is_ip_banned("8.8.8.8"))
        self.assertEqual(wall.stats["hallucinated_targets"], 1)

    def test_a_low_confidence_verdict_is_only_noted(self):
        cerb, wall = build()
        tel = self.telemetry(wall, ["45.9.50.2"])
        done = wall._apply({"verdicts": [
            {"ip": "45.9.50.2", "action": "ban", "confidence": 0.4,
             "reason": "a hunch"}]}, tel)
        self.assertEqual(done[0]["done"], "noted")
        self.assertFalse(cerb.is_ip_banned("45.9.50.2"))

    def test_a_confident_verdict_is_carried_out(self):
        cerb, wall = build()
        tel = self.telemetry(wall, ["45.9.50.3"])
        done = wall._apply({"verdicts": [
            {"ip": "45.9.50.3", "action": "ban", "confidence": 0.95,
             "reason": "walking system accounts"}]}, tel)
        self.assertEqual(done[0]["done"], "applied")
        self.assertTrue(cerb.is_ip_banned("45.9.50.3"))

    def test_a_whitelisted_address_is_untouchable(self):
        cerb, wall = build()
        cerb.add_whitelisted_ip("45.9.50.4")
        tel = self.telemetry(wall, ["45.9.50.4"])
        wall._apply({"verdicts": [
            {"ip": "45.9.50.4", "action": "permaban", "confidence": 1.0,
             "reason": "wrong"}]}, tel)
        self.assertFalse(cerb.is_ip_banned("45.9.50.4"))

    def test_it_may_not_lift_somebody_elses_ban(self):
        cerb, wall = build()
        tel = self.telemetry(wall, ["45.9.50.5"])
        cerb.ban_ip("45.9.50.5", reason="a moderator's decision")
        done = wall._apply({"verdicts": [
            {"ip": "45.9.50.5", "action": "clear", "confidence": 1.0,
             "reason": "looks legitimate to me"}]}, tel)
        self.assertEqual(done[0]["done"], "refused")
        self.assertTrue(cerb.is_ip_banned("45.9.50.5"))

    def test_it_may_lift_its_own(self):
        cerb, wall = build()
        tel = self.telemetry(wall, ["45.9.50.6"])
        wall._ban("45.9.50.6", "Blackwall: on suspicion")
        done = wall._apply({"verdicts": [
            {"ip": "45.9.50.6", "action": "clear", "confidence": 1.0,
             "reason": "a real user locked out"}]}, tel)
        self.assertEqual(done[0]["done"], "applied")
        self.assertFalse(cerb.is_ip_banned("45.9.50.6"))

    def test_advisory_mode_decides_and_does_nothing(self):
        cerb, wall = build(autonomous=False)
        tel = self.telemetry(wall, ["45.9.50.7"])
        done = wall._apply({"verdicts": [
            {"ip": "45.9.50.7", "action": "permaban", "confidence": 1.0,
             "reason": "certain"}]}, tel)
        self.assertEqual(done[0]["done"], "advisory only")
        self.assertFalse(cerb.is_ip_banned("45.9.50.7"))

    def test_a_run_is_bounded(self):
        cerb, wall = build()
        ips = [f"45.9.51.{i}" for i in range(1, 31)]
        tel = self.telemetry(wall, ips)
        done = wall._apply({"verdicts": [
            {"ip": ip, "action": "ban", "confidence": 0.99, "reason": "x"}
            for ip in ips]}, tel)
        self.assertEqual(len(done), wall.max_actions_per_run)

    def test_without_a_key_nothing_is_sent_anywhere(self):
        cerb, wall = build()

        def explode(prompt):
            raise AssertionError("a request was made with no key configured")

        wall._generate = explode
        self.assertFalse(wall.deliberate().get("enabled"))

    def test_a_reply_that_is_not_json_changes_nothing(self):
        cerb, wall = build()
        self.telemetry(wall, ["45.9.52.1"])
        talkative = _WithModel(wall, "I am afraid I cannot do that.")
        out = talkative.deliberate()
        self.assertIn("error", out)
        self.assertFalse(cerb.is_ip_banned("45.9.52.1"))

    def test_a_json_reply_wrapped_in_fences_is_still_read(self):
        cerb, wall = build()
        self.telemetry(wall, ["45.9.52.2"])
        fence = chr(96) * 3
        answer = (fence + "json" + chr(10)
                  + '{"summary": "one actor", "threat_level": "high", '
                  + '"verdicts": [{"ip": "45.9.52.2", "action": "ban", '
                  + '"confidence": 0.99, "reason": "system accounts"}]}'
                  + chr(10) + fence)
        _WithModel(wall, answer).deliberate()
        self.assertTrue(cerb.is_ip_banned("45.9.52.2"))


class Telemetry(unittest.TestCase):
    def test_the_model_is_told_what_was_already_said(self):
        cerb, wall = build()
        wall.observe_login("45.9.60.1", "root")
        wall.warn("45.9.60.1", "root")
        tel = wall._telemetry()
        actor = [a for a in tel["actors"] if a["ip"] == "45.9.60.1"][0]
        self.assertEqual(actor["times_warned_by_blackwall"], 1)
        self.assertTrue(actor["blackwall_said"])
        self.assertTrue(tel["blackwall_transcript"])

    def test_status_is_serialisable(self):
        cerb, wall = build()
        wall.observe_login("45.9.60.2", "root")
        json.dumps(wall.status(), default=str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
