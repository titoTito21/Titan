"""
Tests for the Cerberus anti-brute-force hardening (distributed attacks,
reserved-account honeytokens, escalating repeat-offender bans).

Run directly:  python test_cerberus_hardening.py
These exercise the base CerberusProtocol logic with no DB/firewall so they run
anywhere; the DangerousCerberus subclass reuses the same code paths.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cerberus as C  # noqa: E402


def fresh(**kw):
    d = tempfile.mkdtemp()
    return C.CerberusProtocol(log_dir=os.path.join(d, "logs"), **kw)


class DistributedAccountAttack(unittest.TestCase):
    def test_many_ips_one_account_all_banned(self):
        c = fresh()
        ips = [f"203.0.113.{i}" for i in range(1, 1 + c.distributed_attack_ips)]
        for ip in ips:
            c.record_failed_login(ip, "alice")
        self.assertTrue(all(c.is_ip_banned(ip) for ip in ips))

    def test_targeted_account_protected(self):
        c = fresh()
        for i in range(c.distributed_attack_ips):
            c.record_failed_login(f"203.0.113.{i}", "alice")
        self.assertTrue(c.is_account_locked("alice"))

    def test_below_threshold_not_banned(self):
        c = fresh()
        n = c.distributed_attack_ips - 1
        # Spread across distinct /24s so ONLY the per-account detector is
        # under test (4 IPs in one /24 would legitimately trip the subnet rule).
        ips = [f"203.0.{i}.9" for i in range(n)]
        for ip in ips:
            c.record_failed_login(ip, "alice")
        self.assertFalse(any(c.is_ip_banned(ip) for ip in ips))

    def test_owner_success_drops_residue(self):
        c = fresh()
        c.record_failed_login("8.8.8.8", "bob")
        c.note_successful_login("8.8.8.8", "bob")
        self.assertNotIn("bob", c._account_source_ips)


class DistributedSubnetAttack(unittest.TestCase):
    def test_many_ips_one_subnet_all_banned(self):
        c = fresh()
        ips = [f"45.155.205.{i}" for i in range(1, 1 + c.subnet_bruteforce_ips)]
        for i, ip in enumerate(ips):
            c.record_failed_login(ip, f"user{i}")  # distinct real names
        self.assertTrue(all(c.is_ip_banned(ip) for ip in ips))

    def test_different_subnets_dont_aggregate(self):
        c = fresh()
        for i in range(c.subnet_bruteforce_ips):
            c.record_failed_login(f"10.{i}.0.1", f"user{i}")
        self.assertFalse(any(c.is_ip_banned(f"10.{i}.0.1")
                             for i in range(c.subnet_bruteforce_ips)))


class ReservedUsernames(unittest.TestCase):
    def test_reserved_name_bans_fast(self):
        c = fresh()
        for name in ("root", "admin", "administrator"):
            c.record_failed_login("66.66.66.66", name)
        self.assertTrue(c.is_ip_banned("66.66.66.66"))

    def test_single_hit_only_alerts(self):
        c = fresh()
        c.record_failed_login("66.66.66.67", "root")
        self.assertFalse(c.is_ip_banned("66.66.66.67"))

    def test_real_account_exempt(self):
        c = fresh()
        c.is_real_account = lambda u: u.lower() == "admin"
        for _ in range(5):
            c.record_failed_login("7.7.7.7", "admin")
        self.assertFalse(c.is_ip_banned("7.7.7.7"))

    def test_ordinary_name_not_reserved(self):
        c = fresh()
        # A normal username failing a couple of times is not a honeytoken hit.
        c.record_failed_login("9.1.1.1", "charlie")
        c.record_failed_login("9.1.1.1", "charlie")
        self.assertFalse(c.is_ip_banned("9.1.1.1"))


class RepeatOffender(unittest.TestCase):
    def test_second_ban_is_permaban(self):
        c = fresh()
        c._set_ip_threat("5.5.5.5", C.THREAT_LOCKDOWN, "first")
        self.assertNotIn("5.5.5.5", c._permanent_banned_ips)
        c.unban_ip("5.5.5.5")
        c._set_ip_threat("5.5.5.5", C.THREAT_LOCKDOWN, "second")
        self.assertIn("5.5.5.5", c._permanent_banned_ips)

    def test_first_ban_not_permaban(self):
        c = fresh()
        c._set_ip_threat("5.5.5.6", C.THREAT_LOCKDOWN, "first")
        self.assertTrue(c.is_ip_banned("5.5.5.6"))
        self.assertNotIn("5.5.5.6", c._permanent_banned_ips)

    def test_whitelisted_never_counted(self):
        c = fresh()
        c.add_whitelisted_ip("1.1.1.1")
        c._set_ip_threat("1.1.1.1", C.THREAT_LOCKDOWN, "x")
        self.assertNotIn("1.1.1.1", c._offense_history)


class DefaultAccountSweep(unittest.TestCase):
    """Several DIFFERENT system accounts from one source is a list being
    walked - certain long before the per-name count would say so."""

    def test_two_distinct_reserved_names_ban(self):
        c = fresh()
        c.record_failed_login("144.48.8.86", "ubuntu")
        self.assertFalse(c.is_ip_banned("144.48.8.86"))
        c.record_failed_login("144.48.8.86", "debian")
        self.assertTrue(c.is_ip_banned("144.48.8.86"))

    def test_soft_name_alone_is_never_an_attack(self):
        # 'user' is a name a real person could have chosen; on its own it must
        # do nothing at all, however many times it is tried.
        c = fresh()
        for _ in range(4):
            c.record_failed_login("9.8.7.6", "user")
        self.assertFalse(c.is_ip_banned("9.8.7.6"))

    def test_soft_name_counts_after_a_certain_one(self):
        c = fresh()
        c.record_failed_login("9.8.7.7", "root")     # certain
        c.record_failed_login("9.8.7.7", "user")     # now it counts
        self.assertTrue(c.is_ip_banned("9.8.7.7"))

    def test_real_account_named_like_one_is_exempt(self):
        c = fresh()
        c.is_real_account = lambda u: u.lower() in ("user", "admin")
        for name in ("user", "admin"):
            c.record_failed_login("9.8.7.8", name)
        self.assertFalse(c.is_ip_banned("9.8.7.8"))


class LockoutAbuse(unittest.TestCase):
    """The protective lock defends the account. On its own it does nothing to
    the attacker - and used to hide them completely."""

    def test_honeytoken_account_is_never_locked(self):
        # Locking 'root' protects nobody (there is no owner) and would put the
        # attacker into the invisible path below.
        c = fresh()
        for _ in range(c.account_lock_failures + 2):
            c.record_failed_login("5.4.3.2", "root")
        self.assertFalse(c.is_account_locked("root"))

    def test_causing_lockouts_bans_the_source(self):
        c = fresh()
        for user in ("alice", "bob"):
            for _ in range(c.account_lock_failures):
                c.record_failed_login("6.6.6.1", user)
        self.assertTrue(c.is_account_locked("alice"))
        self.assertTrue(c.is_ip_banned("6.6.6.1"))

    def test_one_lockout_is_not_enough(self):
        c = fresh()
        for _ in range(c.account_lock_failures):
            c.record_failed_login("6.6.6.2", "alice")
        self.assertTrue(c.is_account_locked("alice"))
        self.assertFalse(c.is_ip_banned("6.6.6.2"))

    def test_attempts_on_a_locked_account_are_counted(self):
        c = fresh()
        for _ in range(c.locked_attempt_lockdown - 1):
            self.assertFalse(c.record_locked_account_attempt("7.7.7.1", "alice"))
        self.assertTrue(c.record_locked_account_attempt("7.7.7.1", "alice"))
        self.assertTrue(c.is_ip_banned("7.7.7.1"))

    def test_whitelisted_source_never_counted(self):
        c = fresh()
        c.add_whitelisted_ip("1.2.3.4")
        for _ in range(10):
            self.assertFalse(c.record_locked_account_attempt("1.2.3.4", "alice"))
        self.assertFalse(c.is_ip_banned("1.2.3.4"))


class BanEvasion(unittest.TestCase):
    """Traffic from a banned address means the ban is not being enforced."""

    def test_activity_while_banned_asks_for_re_enforcement(self):
        c = fresh()
        asked = []
        c.on_reenforce_ban = lambda ip, reason="": asked.append(ip)
        c._set_ip_threat("8.8.4.4", C.THREAT_LOCKDOWN, "test")
        c.record_failed_login("8.8.4.4", "alice")
        self.assertEqual(asked, ["8.8.4.4"])

    def test_persisting_while_banned_is_a_permaban(self):
        c = fresh()
        c._set_ip_threat("8.8.4.5", C.THREAT_LOCKDOWN, "test")
        self.assertNotIn("8.8.4.5", c._permanent_banned_ips)
        for _ in range(c.banned_activity_permaban):
            c.note_banned_activity("8.8.4.5", "still trying")
        self.assertIn("8.8.4.5", c._permanent_banned_ips)

    def test_the_attempt_that_earns_the_ban_is_not_evasion(self):
        # Being banned ON this attempt must not also count as talking through
        # a ban - that would permaban everything on its first offence.
        c = fresh()
        c.record_failed_login("8.8.4.6", "root")
        c.record_failed_login("8.8.4.6", "ubuntu")   # bans here
        self.assertTrue(c.is_ip_banned("8.8.4.6"))
        self.assertNotIn("8.8.4.6", c._permanent_banned_ips)

    def test_re_enforcement_is_rate_limited(self):
        c = fresh()
        asked = []
        c.on_reenforce_ban = lambda ip, reason="": asked.append(ip)
        c._set_ip_threat("8.8.4.7", C.THREAT_LOCKDOWN, "test")
        for _ in range(5):
            c.note_banned_activity("8.8.4.7", "flood")
        self.assertEqual(len(asked), 1)


class BanRoutedThroughEnforcement(unittest.TestCase):
    """ban_ip used to be two set memberships, so a manual ban and the risk
    engine's own escalation never reached the firewall or the ban database."""

    def test_ban_ip_goes_through_set_ip_threat(self):
        seen = []

        class Recording(C.CerberusProtocol):
            def _set_ip_threat(self, ip, level, reason):
                seen.append((ip, level))
                super()._set_ip_threat(ip, level, reason)

        d = tempfile.mkdtemp()
        c = Recording(log_dir=os.path.join(d, "logs"))
        c.ban_ip("3.3.3.3", permanent=False, reason="manual")
        self.assertEqual(seen, [("3.3.3.3", C.THREAT_LOCKDOWN)])
        self.assertTrue(c.is_ip_banned("3.3.3.3"))

    def test_permanent_ban_is_recorded_even_when_already_banned(self):
        c = fresh()
        c._set_ip_threat("3.3.3.4", C.THREAT_LOCKDOWN, "first")
        c.ban_ip("3.3.3.4", permanent=True, reason="risk score climbing")
        self.assertIn("3.3.3.4", c._permanent_banned_ips)


class DashboardStatus(unittest.TestCase):

    def test_new_keys_present(self):
        c = fresh()
        st = c.get_account_guard_status()
        for k in ("distributed_targets", "bruteforce_subnets",
                  "reserved_account_ips", "repeat_offenders",
                  "reserved_names_tried", "lockout_sources",
                  "lockout_evasion_ips", "active_while_banned"):
            self.assertIn(k, st)


    def test_no_global_lockdown_on_distributed(self):
        # A distributed attack must NOT lock the whole server out for real users.
        c = fresh()
        for i in range(c.distributed_attack_ips):
            c.record_failed_login(f"203.0.113.{i}", "alice")
        self.assertFalse(c.is_lockdown_active())


if __name__ == "__main__":
    unittest.main(verbosity=2)
