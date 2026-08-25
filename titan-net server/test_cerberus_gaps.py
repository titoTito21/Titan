"""
Round 2 of the false-positive audit (2026-08-24): four gaps found by asking
why 217 of the 224 permanent bans on production all carried the SAME sentence,
"SSH honeypot: 2nd login attempt as 'tar_pit_connection'".

They are all the same shape of mistake - a punishment applied on evidence the
system produced itself, or applied for ever because nothing could take it back.

Run directly:  python test_cerberus_gaps.py
Shares its helpers with test_cerberus_false_positives.py.
"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cerberus as C  # noqa: E402
from test_cerberus_false_positives import fresh, _NoFirewall, D  # noqa: E402


@unittest.skipIf(D is None, "dangerous_cerberus not importable")
class TheAnswerChannelIsNotEvidence(unittest.TestCase):
    """The loop that quietly undid ban expiry as fast as it was applied.

    Cerberus bans an address, opens a tar-pit redirect in front of its port 22
    so Blackwall has somewhere to speak to it, the bot retries SSH twice
    (seconds, for a bot), and each retry was reported as a fresh honeypot hit:
    "2nd login attempt - confirmed attacker", which is THREAT_CERBERUS, a
    permanent all-ports ban plus infrastructure countermeasures.

    The attacker never chose to touch a honeypot port. We moved the door and
    then convicted them of walking through it. Measured on production: 217 of
    224 permanent bans read exactly that, and the permanent count rose from
    194 to 224 in the two hours after ban expiry was introduced - the loop was
    manufacturing permanent bans faster than expiry could retire them.
    """

    def make(self, answered=()):
        d = tempfile.mkdtemp()
        c = D.DangerousCerberus(log_dir=os.path.join(d, "logs"),
                                db_dir=os.path.join(d, "db"))
        c.firewall = _NoFirewall()
        held = set(answered)
        c.firewall.answered_ips = lambda: sorted(held)
        c.auto_firewall = True
        c.auto_subnet_ban = False
        return c

    def test_a_redirected_retry_never_becomes_a_permanent_ban(self):
        c = self.make(answered={"198.51.100.20"})
        for _ in range(6):
            c.honeypot_triggered("198.51.100.20", "tar_pit_connection")
        self.assertNotIn("198.51.100.20", c._permanent_banned_ips)

    def test_a_real_honeypot_hit_still_escalates(self):
        """Nobody legitimate connects to a fake SSH they were not sent to, so
        a chosen hit is still the strongest signal Cerberus has."""
        c = self.make(answered=set())
        c.honeypot_triggered("198.51.100.21", "root")
        c.honeypot_triggered("198.51.100.21", "root")
        self.assertTrue(c.is_ip_banned("198.51.100.21"))

    def test_a_redirected_retry_is_recorded_but_punishes_nothing(self):
        """Not evidence is not the same as ignored: it is written to the
        intrusion log and the attacker profile, and nothing else happens."""
        c = self.make(answered={"198.51.100.22"})
        c._banned_ips.add("198.51.100.22")
        said = []
        c._log_intrusion = lambda level, ip, details: said.append(level)
        for _ in range(c.banned_activity_permaban + 2):
            c.honeypot_triggered("198.51.100.22", "tar_pit_connection")
        self.assertIn("ANSWER_CHANNEL", said)
        self.assertNotIn("198.51.100.22", c._permanent_banned_ips)

    def test_an_answered_address_is_not_read_as_a_leaking_ban(self):
        """The base class permabans an address whose traffic keeps arriving,
        on the reasoning that the block must be missing. With the channel open
        there IS deliberately an ACCEPT - that is how the packet reaches the
        tar pit - so the one thing it treats as proof of failure is the design
        working."""
        c = self.make(answered={"198.51.100.24"})
        c._banned_ips.add("198.51.100.24")
        reverified = []
        c.on_reenforce_ban = lambda ip, reason: reverified.append(ip)
        for _ in range(c.banned_activity_permaban + 3):
            c.note_banned_activity("198.51.100.24", "retry")
        self.assertEqual([], reverified)
        self.assertNotIn("198.51.100.24", c._permanent_banned_ips)

    def test_an_unanswered_banned_address_still_is(self):
        """The check must keep working where it was right: no channel open
        means the traffic really should not be arriving."""
        c = self.make(answered=set())
        c._banned_ips.add("198.51.100.25")
        reverified = []
        c.on_reenforce_ban = lambda ip, reason: reverified.append(ip)
        for _ in range(c.banned_activity_permaban + 1):
            c.note_banned_activity("198.51.100.25", "retry")
        self.assertTrue(reverified)

    def test_it_fails_towards_not_manufacturing_evidence(self):
        """If we cannot tell whether we redirected them, we must not permaban
        them for it."""
        c = self.make()

        def boom():
            raise RuntimeError("iptables is gone")

        c.firewall.answered_ips = boom
        for _ in range(4):
            c.honeypot_triggered("198.51.100.23", "tar_pit_connection")
        self.assertNotIn("198.51.100.23", c._permanent_banned_ips)


class HoneypotAttemptsAreCountedInAWindow(unittest.TestCase):
    """"A second attempt means they came back deliberately" is only true of a
    second attempt SOON after the first. ``_tracked_attackers`` was never
    pruned, so two knocks a month apart read as a confirmed attacker and
    earned a permanent all-ports ban - and the dictionary grew one entry per
    address that ever touched this server, for the life of the process."""

    def test_two_knocks_far_apart_are_not_a_confirmed_attacker(self):
        c = fresh()
        c.honeypot_triggered("198.51.100.30", "root")
        hits = c._tracked_attackers["198.51.100.30"]["honeypot_hits"]
        c._tracked_attackers["198.51.100.30"]["honeypot_hits"] = [
            t - c.honeypot_window - 60 for t in hits]
        c.honeypot_triggered("198.51.100.30", "root")
        self.assertNotIn("198.51.100.30", c._permanent_banned_ips)

    def test_two_knocks_together_still_are(self):
        c = fresh()
        c.honeypot_triggered("198.51.100.31", "root")
        c.honeypot_triggered("198.51.100.31", "root")
        self.assertIn("198.51.100.31", c._permanent_banned_ips)

    def test_a_quiet_address_is_forgotten(self):
        c = fresh()
        c.record_failed_login("198.51.100.32", "alice", source="app")
        self.assertIn("198.51.100.32", c._tracked_attackers)
        c._tracked_attackers["198.51.100.32"]["last_seen"] = \
            time.time() - c.tracked_attacker_ttl - 60
        c._last_attacker_sweep = 0
        c._sweep_tracked_attackers(time.time())
        self.assertNotIn("198.51.100.32", c._tracked_attackers)

    def test_a_banned_address_is_never_forgotten(self):
        c = fresh()
        c._banned_ips.add("198.51.100.33")
        c._tracked_attackers["198.51.100.33"] = {
            "threat_score": 1, "first_seen": 0.0, "last_seen": 0.0, "type": "x"}
        c._last_attacker_sweep = 0
        c._sweep_tracked_attackers(time.time())
        self.assertIn("198.51.100.33", c._tracked_attackers)


class TheWhitelistUnderstandsRanges(unittest.TestCase):
    """Exact string matching was all there was, so an operator on a dynamic
    address, an office range or a monitoring provider could not be protected -
    you cannot list every address a DHCP lease might hand you. The whitelist's
    whole promise is that the machine cannot lock its owner out, and that was
    only keepable for a static address."""

    def test_a_cidr_range_covers_its_addresses(self):
        c = fresh()
        c.add_whitelisted_ip("203.0.113.0/24")
        self.assertTrue(c.is_whitelisted("203.0.113.77"))
        self.assertFalse(c.is_whitelisted("203.0.114.77"))

    def test_an_exact_address_still_works(self):
        c = fresh()
        c.add_whitelisted_ip("198.51.100.40")
        self.assertTrue(c.is_whitelisted("198.51.100.40"))
        self.assertFalse(c.is_whitelisted("198.51.100.41"))

    def test_a_whitelisted_range_is_never_banned(self):
        c = fresh()
        c.add_whitelisted_ip("203.0.113.0/24")
        for _ in range(c.cerberus_failed_logins + 5):
            c.record_failed_login("203.0.113.9", "root", source="ssh")
        self.assertFalse(c.is_ip_banned("203.0.113.9"))

    def test_rubbish_is_refused_not_crashed_on(self):
        c = fresh()
        self.assertFalse(c._register_whitelist_entry("not-an-address/24"))
        self.assertFalse(c.is_whitelisted("198.51.100.42"))

    def test_a_range_can_be_taken_back_out(self):
        c = fresh()
        c.add_whitelisted_ip("203.0.113.0/24")
        c.remove_whitelisted_ip("203.0.113.0/24")
        self.assertFalse(c.is_whitelisted("203.0.113.77"))

    def test_a_v6_range_does_not_break_a_v4_lookup(self):
        c = fresh()
        c.add_whitelisted_ip("2001:db8::/32")
        self.assertFalse(c.is_whitelisted("198.51.100.43"))
        self.assertTrue(c.is_whitelisted("2001:db8::1"))


@unittest.skipIf(D is None, "dangerous_cerberus not importable")
class SubnetBansRunOutToo(unittest.TestCase):
    """Banning a /24 blocks 254 addresses on the evidence of a handful, and
    behind a CGNAT range that is a neighbourhood of subscribers. It was the
    widest block Cerberus could impose, it had no expiry column at all, and
    FirewallManager had no ``unblock_subnet`` - so no code path anywhere took
    a /24 rule back out of the kernel."""

    def make(self):
        d = tempfile.mkdtemp()
        c = D.DangerousCerberus(log_dir=os.path.join(d, "logs"),
                                db_dir=os.path.join(d, "db"))
        c.firewall = _NoFirewall()
        c.auto_firewall = True
        return c

    def test_a_live_subnet_ban_still_applies(self):
        c = self.make()
        c.ban_db.add_subnet_ban("203.0.113.0/24", "sweep", ["203.0.113.1"],
                                expires_at=time.time() + 600)
        self.assertIn("203.0.113.0/24", c.ban_db.get_all_banned_subnets())
        self.assertTrue(c.ban_db.is_banned("203.0.113.9"))

    def test_an_expired_subnet_ban_stops_applying(self):
        c = self.make()
        c.ban_db.add_subnet_ban("203.0.113.0/24", "sweep", ["203.0.113.1"],
                                expires_at=time.time() - 5)
        self.assertNotIn("203.0.113.0/24", c.ban_db.get_all_banned_subnets())
        self.assertFalse(c.ban_db.is_banned("203.0.113.9"))

    def test_the_sweep_lifts_it_from_the_kernel(self):
        c = self.make()
        c.firewall.unblock_subnet = \
            lambda s: (c.firewall.unblocked.append(s), True)[1]
        c.ban_db.add_subnet_ban("203.0.113.0/24", "sweep", ["203.0.113.1"],
                                expires_at=time.time() - 5)
        c.release_expired_bans()
        self.assertIn("203.0.113.0/24", c.firewall.unblocked)

    def test_a_subnet_term_is_shorter_than_the_longest_ip_term(self):
        c = self.make()
        self.assertLess(c.SUBNET_BAN_TERM, max(c.BAN_TERMS))

    def test_the_firewall_can_undo_a_subnet_ban_at_all(self):
        self.assertTrue(hasattr(D.FirewallManager, "unblock_subnet"))


try:
    import blackwall as B
except Exception:                                   # pragma: no cover
    B = None


@unittest.skipIf(B is None, "blackwall not importable")
class TheWallDoesNotClaimPermanenceItDoesNotHave(unittest.TestCase):
    """Bans have terms now, so "permanently" became a claim that has to be
    checked like any other.

    Caught live: with the terms applied, Blackwall was still saying "This
    address is finished here - permanently." to addresses whose ban was due to
    lapse. It is the same fault _is_true was written for - the first live run
    announced a block to somebody who was not blocked - one level further in.
    """

    def test_a_permanence_claim_is_refused_when_the_ban_has_a_term(self):
        brief = {"already_blocked": True, "blocked_for_good": False}
        self.assertFalse(B.Blackwall._is_true(
            "You are blocked here permanently.", 3, brief))

    def test_it_is_allowed_when_the_ban_really_is_permanent(self):
        brief = {"already_blocked": True, "blocked_for_good": True}
        self.assertTrue(B.Blackwall._is_true(
            "You are blocked here permanently.", 3, brief))

    def test_an_ordinary_stage_3_line_still_passes(self):
        brief = {"already_blocked": True, "blocked_for_good": False}
        self.assertTrue(B.Blackwall._is_true(
            "You were already refused and you came back anyway. Everything "
            "you send now goes into a wall and into a log.", 3, brief))

    def test_the_written_floor_lines_claim_no_permanence(self):
        """The floor is said WITHOUT going through _is_true, so a claim there
        cannot be caught at all - it has to be true as written."""
        for stage, lines in B.Blackwall.VOICE.items():
            for line in lines:
                low = line.lower()
                for claim in B.Blackwall._CLAIMS_PERMANENT:
                    self.assertNotIn(
                        claim, low,
                        f"stage {stage} floor line claims permanence: {line}")

    def test_claiming_a_block_before_there_is_one_is_still_refused(self):
        brief = {"already_blocked": False, "blocked_for_good": False}
        self.assertFalse(B.Blackwall._is_true(
            "Your address is blocked.", 0, brief))


if __name__ == "__main__":
    unittest.main(verbosity=2)
