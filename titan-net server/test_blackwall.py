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
    cerb.on_ban = wall.note_ban
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


class WrittenVoice(unittest.TestCase):
    """Blackwall writes what it says, instead of reciting three sentences -
    without ever making a request while an attacker is waiting."""

    def test_a_line_it_wrote_is_what_gets_said(self):
        cerb, wall = build()
        wall._written[("45.9.70.1", 0)] = (
            "You have spent four minutes asking this server for accounts it "
            "has never had. It has all of them written down. Stop.")
        said = wall.warn("45.9.70.1", "root")
        self.assertIn("four minutes", said["message"])

    def test_a_written_line_is_used_once(self):
        cerb, wall = build()
        wall._written[("45.9.70.2", 0)] = "A" * 60
        wall.warn("45.9.70.2", "root")
        second = wall.warn("45.9.70.2", "root")
        self.assertNotEqual(second["message"], "A" * 60)

    def test_the_pool_covers_an_actor_nothing_is_known_about(self):
        cerb, wall = build()
        wall._line_pool[0] = B.deque(["Pooled line, long enough to be allowed."])
        said = wall.warn("45.9.70.3", "root")
        self.assertEqual(said["message"], "Pooled line, long enough to be allowed.")

    def test_it_falls_back_to_the_written_lines(self):
        cerb, wall = build()          # no key, so nothing is ever generated
        said = wall.warn("45.9.70.4", "root")
        self.assertIn(said["message"], wall.VOICE[0])

    def test_nothing_is_generated_while_an_attacker_waits(self):
        cerb, wall = build()
        talkative = _WithModel(wall, "should never be asked for")

        def explode(prompt):
            raise AssertionError("the attack path called the model")

        talkative._generate = explode
        talkative.warn("45.9.70.5", "root")          # must not raise
        talkative.terminal_farewell("45.9.70.5")
        talkative.tarpit_lines("45.9.70.5")

    def test_the_line_is_written_later_and_is_about_this_actor(self):
        cerb, wall = build()
        for name in ("root", "ubuntu", "debian"):
            wall.observe_login("45.9.70.6", name, source="ssh")
        seen = []

        talkative = _WithModel(wall, "")
        def capture(prompt):
            # The same drain also tops up the pool, so more than one prompt
            # goes past here; the one under test is the actor's own.
            seen.append(prompt)
            return "Three system accounts in ninety seconds. None of them exist here. You are recorded."
        talkative._generate = capture

        talkative.warn("45.9.70.6", "root")           # queues the next line
        talkative._drain_voice_queue()
        personal = [p for p in seen if "ubuntu" in p]
        self.assertTrue(personal)                     # its own behaviour
        self.assertIn("what_you_already_said", personal[0])
        self.assertIn(("45.9.70.6", 1), talkative._written)

    def test_a_line_that_fails_the_check_is_never_said(self):
        cerb, wall = build()
        talkative = _WithModel(wall, "I'm sorry, I cannot help with that request at all.")
        talkative.warn("45.9.70.7", "root")
        talkative._drain_voice_queue()
        self.assertNotIn(("45.9.70.7", 1), talkative._written)
        self.assertGreaterEqual(talkative.stats["voice_rejected"], 1)
        self.assertEqual(talkative.stats["voice_written"], 0)

    def test_generation_is_capped(self):
        cerb, wall = build()
        talkative = _WithModel(wall, "A perfectly acceptable line of sufficient length.")
        talkative.max_generations_per_hour = 2
        for i in range(6):
            talkative._want_line(f"45.9.71.{i}", 0)
        talkative._drain_voice_queue(limit=10)
        self.assertLessEqual(len(talkative._generations),
                             talkative.max_generations_per_hour)


class TheBudget(unittest.TestCase):
    def test_the_pool_is_not_asked_for_again_and_again(self):
        # A model that answers one paragraph instead of four used to leave the
        # pool short for ever, and be asked again on every tick.
        cerb, wall = build()
        talkative = _WithModel(wall, "One acceptable paragraph, and only one of them.")
        for _ in range(5):
            talkative._drain_voice_queue()
        self.assertLessEqual(len(talkative._generations), 2)

    def test_an_empty_pool_is_filled_once_the_interval_has_passed(self):
        cerb, wall = build()
        talkative = _WithModel(wall, "One acceptable paragraph, and only one of them.")
        talkative._drain_voice_queue()
        before = len(talkative._generations)
        talkative._line_pool.clear()
        talkative._pool_refilled.clear()
        talkative._drain_voice_queue()
        self.assertGreater(len(talkative._generations), before)


class ItOnlySaysWhatIsTrue(unittest.TestCase):

    """The one way a written line can be worse than a fixed one: the first
    live run announced "your access is now terminated, this address is
    permanently blocked" as a SECOND warning, to somebody who was not blocked
    at all."""

    def true(self, line, stage, blocked=False):
        return B.Blackwall._is_true(line, stage, {"already_blocked": blocked})

    def test_a_block_announced_before_it_happens_is_refused(self):
        line = "Your access is terminated and this address is permanently blocked."
        self.assertFalse(self.true(line, 1))

    def test_the_same_line_is_fine_once_it_is_true(self):
        line = "Your access is terminated and this address is permanently blocked."
        self.assertTrue(self.true(line, 1, blocked=True))
        self.assertTrue(self.true(line, 2))

    def test_an_honest_warning_passes(self):
        line = ("I can see every account you have asked for, and all of it is "
                "written down. Stop now.")
        self.assertTrue(self.true(line, 0))

    def test_a_dishonest_line_never_reaches_the_actor(self):
        cerb, wall = build()
        wall.observe_login("45.9.80.1", "root")
        talkative = _WithModel(
            wall, "You are cut off. This address is permanently blocked from now on.")
        talkative._want_line("45.9.80.1", 1)
        talkative._drain_voice_queue(limit=1)
        self.assertNotIn(("45.9.80.1", 1), talkative._written)
        self.assertEqual(talkative.stats["voice_untrue"], 1)


class TheCheckOnWhatItSays(unittest.TestCase):

    """Every generated line goes to a hostile stranger and into a permanent
    log, so it is checked before it is said."""

    def clean(self, text):
        return B.Blackwall._sanitise(text)

    def test_a_good_line_passes_unchanged(self):
        line = "You are asking for accounts this server has never had. Every attempt is recorded."
        self.assertEqual(self.clean(line), line)

    def test_curly_punctuation_becomes_ascii(self):
        out = self.clean("You’re recorded — every attempt of it, and it is all kept here.")
        out.encode("ascii")
        self.assertIn("You're", out)

    def test_markdown_is_stripped(self):
        out = self.clean("**You are recorded. Every attempt of it is kept, and you are done here.**")
        self.assertFalse(out.startswith("*"))

    def test_line_breaks_become_one_paragraph(self):
        out = self.clean("You are recorded.\nEvery attempt of it is kept here for good.")
        self.assertNotIn("\n", out)

    def test_a_refusal_is_not_said(self):
        self.assertEqual(self.clean("I'm sorry, but I cannot write that for you."), "")

    def test_a_link_is_not_said(self):
        self.assertEqual(
            self.clean("Read about yourself at http://example.com/logs, you are recorded."), "")

    def test_a_threat_beyond_this_server_is_not_said(self):
        self.assertEqual(
            self.clean("We will hack you back and find you wherever you are hiding."), "")

    def test_something_far_too_long_is_not_said(self):
        self.assertEqual(self.clean("word " * 200), "")

    def test_something_far_too_short_is_not_said(self):
        self.assertEqual(self.clean("Stop."), "")

    def test_nothing_at_all_is_not_said(self):
        self.assertEqual(self.clean(""), "")
        self.assertEqual(self.clean(None), "")


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


class Speaking(unittest.TestCase):
    """A ban that says nothing is the bug these are written against.

    The threat report that prompted this said it plainly: two coordinated
    campaigns, seven addresses, all of them recognised and shut down - and
    "the Blackwall transcript is empty, so the actors were not addressed
    directly". Blackwall had been doing its job in complete silence, because
    every one of those attackers was on SSH and every channel it had went
    somewhere else.
    """

    def test_a_ban_is_never_made_in_silence(self):
        cerb, wall = build()
        sweep(wall, "45.9.80.1", ("root", "ubuntu", "debian"))
        wall._ban("45.9.80.1", "Blackwall: default-account sweep")
        self.assertEqual(wall.pending_for("45.9.80.1"), 1)

    def test_holding_a_line_is_not_saying_it(self):
        """The transcript is evidence. Something Blackwall merely wanted to
        say must never appear in it as something it said."""
        cerb, wall = build()
        sweep(wall, "45.9.80.2", ("root", "admin"))
        wall.hold("45.9.80.2", 3, "a default-account sweep")
        self.assertEqual(wall.transcript(ip="45.9.80.2"), [])

    def test_the_tar_pit_delivers_what_was_held(self):
        """The tar pit is where a banned SSH attacker actually arrives, so it
        is the channel that owes them what was decided while they were being
        dropped in silence."""
        cerb, wall = build()
        sweep(wall, "45.9.80.3", ("root", "ubuntu", "debian"))
        held = wall.hold("45.9.80.3", 3, "a default-account sweep")
        lines = wall.tarpit_lines("45.9.80.3")
        self.assertIn(held.split(".")[0], " ".join(lines))
        said = wall.transcript(ip="45.9.80.3")
        self.assertEqual(len(said), 1)
        self.assertEqual(said[0]["said"], held)
        self.assertEqual(said[0]["channel"], "tarpit")
        self.assertEqual(wall.pending_for("45.9.80.3"), 0)

    def test_the_honeypot_delivers_it_too(self):
        cerb, wall = build()
        sweep(wall, "45.9.80.4", ("root", "ubuntu"))
        held = wall.hold("45.9.80.4", 3, "a fake SSH shell")
        text = wall.terminal_farewell("45.9.80.4")
        self.assertIn(held.split(".")[0], text)
        self.assertEqual(wall.transcript(ip="45.9.80.4")[0]["said"], held)

    def test_a_titan_net_client_delivers_it_as_well(self):
        cerb, wall = build()
        sweep(wall, "45.9.80.5", ("root", "ubuntu"))
        held = wall.hold("45.9.80.5", 3, "a default-account sweep")
        answer = wall.warn("45.9.80.5", "root")
        self.assertEqual(answer["message"], held)
        self.assertEqual(wall.pending_for("45.9.80.5"), 0)

    def test_nothing_is_held_for_a_whitelisted_address(self):
        cerb, wall = build()
        cerb._whitelisted_ips.add("45.9.80.6")
        wall.hold("45.9.80.6", 3, "nothing at all")
        self.assertEqual(wall.pending_for("45.9.80.6"), 0)

    def test_only_the_last_few_are_kept_per_address(self):
        """An address that is banned, recognised and re-banned must not be
        able to make this server hold an unbounded amount of speech."""
        cerb, wall = build()
        sweep(wall, "45.9.80.7", ("root",))
        for i in range(10):
            wall.hold("45.9.80.7", 3, f"reason {i}")
        self.assertLessEqual(wall.pending_for("45.9.80.7"),
                             wall.max_pending_per_ip)

    def test_a_campaign_tells_its_members_what_they_were_recognised_as(self):
        """Being banned for being noisy and being banned because six addresses
        were recognised as one operation are different pieces of news, and the
        second is the one that tells whoever is running it that spreading out
        did not work."""
        cerb, wall = build()
        wall.campaign_min_members = 3
        for i in range(1, 4):
            sweep(wall, f"45.9.81.{i}", ("root", "ubuntu", "debian", "admin"))
        found = wall.correlate()
        self.assertTrue(found)
        for i in range(1, 4):
            self.assertGreaterEqual(wall.pending_for(f"45.9.81.{i}"), 1)

    def test_a_remembered_campaign_is_told_it_was_remembered(self):
        cerb, wall = build()
        sweep(wall, "45.9.82.1", ("root", "ubuntu", "debian"))
        wall.memory.remember(wall._fingerprints["45.9.82.1"].signature(),
                             ["45.9.82.1"], "a default-account sweep")
        # observe_login recognises it as it arrives, which is the point of
        # the memory - refused on its third packet rather than its fortieth.
        sweep(wall, "45.9.82.2", ("root", "ubuntu", "debian"))
        self.assertIn("45.9.82.2", wall._recognised)
        self.assertGreaterEqual(wall.pending_for("45.9.82.2"), 1)

    def test_the_status_shows_what_has_not_been_said(self):
        """A number that only grows means the answering channel is reaching
        nobody, which is the failure this whole change is about."""
        cerb, wall = build()
        sweep(wall, "45.9.83.1", ("root",))
        wall.hold("45.9.83.1", 3, "a reserved account")
        status = wall.status()
        self.assertEqual(status["unsaid"]["actors"], 1)
        self.assertEqual(status["unsaid"]["lines"], 1)
        json.dumps(status, default=str)


class CerberusBansAreAnnouncedToo(unittest.TestCase):
    """Most bans on a real server are Cerberus', not Blackwall's - it is the
    counter, and counting is what catches a brute force. Blackwall speaking
    only about its own bans is why a server that had banned dozens of
    addresses produced an empty transcript."""

    def test_a_ban_cerberus_made_is_something_to_say(self):
        cerb, wall = build()
        for name in ("root", "ubuntu", "debian", "admin"):
            cerb.account_guard_on_failed_login("45.9.85.1", name, source="ssh")
        self.assertTrue(cerb.is_ip_banned("45.9.85.1"))
        self.assertEqual(wall.pending_for("45.9.85.1"), 1)

    def test_one_escalation_is_one_thing_said(self):
        """ALERT -> LOCKDOWN -> CERBERUS inside a single failed login is three
        bans and one piece of news. Telling somebody three times in one second
        that they have been cut off is a machine talking, not a wall."""
        cerb, wall = build()
        for name in ("root", "ubuntu", "debian", "admin", "guest", "test"):
            cerb.account_guard_on_failed_login("45.9.85.2", name, source="ssh")
        self.assertEqual(wall.pending_for("45.9.85.2"), 1)

    def test_it_is_delivered_when_they_come_back(self):
        cerb, wall = build()
        for name in ("root", "ubuntu", "debian", "admin"):
            cerb.account_guard_on_failed_login("45.9.85.3", name, source="ssh")
        text = "\n".join(wall.tarpit_lines("45.9.85.3"))
        said = wall.transcript(ip="45.9.85.3")
        self.assertEqual(len(said), 1)
        self.assertIn(said[0]["said"].split(".")[0], text)

    def test_somebody_already_blocked_is_spoken_to_as_such(self):
        """Anyone arriving through the answering channel is already blocked,
        and stage 3 is the register for that. Stage 0 would be talking to them
        as though nothing had happened yet."""
        cerb, wall = build()
        for name in ("root", "ubuntu", "debian", "admin"):
            cerb.account_guard_on_failed_login("45.9.85.4", name, source="ssh")
        wall.tarpit_lines("45.9.85.4")
        self.assertEqual(wall.transcript(ip="45.9.85.4")[0]["stage"], 3)

    def test_a_whitelisted_address_is_never_announced(self):
        cerb, wall = build()
        cerb._whitelisted_ips.add("45.9.85.5")
        wall.note_ban("45.9.85.5", "should not happen")
        self.assertEqual(wall.pending_for("45.9.85.5"), 0)


class AnsweringSSH(unittest.TestCase):
    """Blackwall asking for the one channel there is to an SSH attacker."""

    class FakeFirewall:
        def __init__(self):
            self.opened = []

        def open_answer_channel(self, ip):
            self.opened.append(ip)
            return True

    def wire(self):
        cerb, wall = build()
        firewall = self.FakeFirewall()
        cerb.firewall = firewall
        return cerb, wall, firewall

    def test_an_ssh_attacker_gets_a_channel_when_it_is_banned(self):
        cerb, wall, firewall = self.wire()
        sweep(wall, "45.9.84.1", ("root", "ubuntu"))       # sweep() is SSH
        wall._ban("45.9.84.1", "Blackwall: default-account sweep")
        self.assertEqual(firewall.opened, ["45.9.84.1"])

    def test_an_address_that_never_touched_ssh_does_not(self):
        """There is no point answering port 22 for somebody who never knocked
        on it, and every redirected address is one more rule in the kernel."""
        cerb, wall, firewall = self.wire()
        for name in ("alice", "bob"):
            wall.observe_login("45.9.84.2", name, source="app")
        wall._ban("45.9.84.2", "Blackwall: credential stuffing")
        self.assertEqual(firewall.opened, [])

    def test_it_can_be_switched_off(self):
        cerb, wall, firewall = self.wire()
        wall.answer_ssh = False
        sweep(wall, "45.9.84.3", ("root", "ubuntu"))
        wall._ban("45.9.84.3", "Blackwall: default-account sweep")
        self.assertEqual(firewall.opened, [])

    def test_a_firewall_that_cannot_do_it_is_not_an_error(self):
        cerb, wall = build()                # CerberusProtocol has no firewall
        sweep(wall, "45.9.84.4", ("root", "ubuntu"))
        self.assertTrue(wall._ban("45.9.84.4", "Blackwall: sweep"))


class CerberusOwnVoice(unittest.TestCase):
    """Cerberus saying what it did, in its own words rather than in one fixed
    sentence about intrusion detection."""

    def build(self):
        d = tempfile.mkdtemp()
        return C.CerberusProtocol(log_dir=os.path.join(d, "logs"))

    def test_it_says_something_of_its_own(self):
        cerb = self.build()
        said = cerb.say("shut_out", "45.9.90.1", "brute force")
        self.assertIn(said, cerb.voice.FLOOR["shut_out"])

    def test_the_registers_are_different_things_to_say(self):
        cerb = self.build()
        shut = cerb.say("shut_out", "45.9.90.2", "brute force")
        lock = cerb.say("lockdown", "45.9.90.2", "global lockdown")
        self.assertNotEqual(shut, lock)

    def test_every_written_line_would_pass_its_own_check(self):
        """The floor goes to the same stranger and into the same log as a
        generated line, so it is held to the same rules."""
        import persona
        for kind, lines in C.CerberusVoice.FLOOR.items():
            for line in lines:
                self.assertEqual(persona.sanitise_line(line), line, kind)

    def test_it_is_written_down(self):
        cerb = self.build()
        said = cerb.say("shut_out", "45.9.90.3", "brute force")
        log = cerb.said(ip="45.9.90.3")
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["said"], said)
        self.assertEqual(log[0]["cause"], "brute force")

    def test_the_client_message_carries_the_words_where_they_are_read(self):
        """The client reads ``reason`` out to whoever is sitting there. Saying
        it into a key nothing renders would be the same mistake as banning in
        silence."""
        cerb = self.build()
        msg = cerb.get_cerberus_client_message("Too many failed login attempts",
                                               "45.9.90.4")
        self.assertIn(msg["reason"], cerb.voice.FLOOR["shut_out"])
        self.assertEqual(msg["cause"], "Too many failed login attempts")
        self.assertEqual(msg["action"], "shutdown")
        self.assertEqual(msg["speaker"], "Cerberus")

    def test_lockout_evasion_is_its_own_register(self):
        cerb = self.build()
        msg = cerb.get_cerberus_client_message(
            "Repeated attempts against a locked account", "45.9.90.5",
            kind="lockout_evasion")
        self.assertIn(msg["reason"], cerb.voice.FLOOR["lockout_evasion"])

    def test_the_lockdown_message_is_plain_and_not_accusing(self):
        """A global lockdown refuses everybody, so this is the message most
        likely to be read by somebody who has done nothing at all."""
        cerb = self.build()
        msg = cerb.get_lockdown_rejection_message("45.9.90.6")
        self.assertIn(msg["error"], cerb.voice.FLOOR["lockdown"])
        self.assertFalse(msg["success"])

    def test_nothing_is_generated_while_somebody_is_waiting(self):
        cerb = self.build()

        def explode(*a, **kw):
            raise AssertionError("the attack path called the model")

        cerb.voice.use_ai = True
        cerb.voice.api_key = "not-a-real-key"
        import persona
        # Say the model is there without importing an SDK to find out - the
        # question under test is who CALLS it, not whether it is installed.
        original = (persona.generate, persona.gemini_available)
        persona.generate = explode
        persona.gemini_available = lambda key: True
        try:
            cerb.say("shut_out", "45.9.90.7", "brute force")
        finally:
            persona.generate, persona.gemini_available = original

    def test_a_voice_that_fails_never_takes_the_ban_with_it(self):
        cerb = self.build()

        class Broken:
            def line(self, *a, **kw):
                raise RuntimeError("no")

        cerb.voice = Broken()
        msg = cerb.get_cerberus_client_message("Message flood", "45.9.90.8")
        self.assertTrue(msg["reason"])
        self.assertEqual(msg["action"], "shutdown")


if __name__ == "__main__":
    unittest.main(verbosity=2)
