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


class DashboardStatus(unittest.TestCase):
    def test_new_keys_present(self):
        c = fresh()
        st = c.get_account_guard_status()
        for k in ("distributed_targets", "bruteforce_subnets",
                  "reserved_account_ips", "repeat_offenders"):
            self.assertIn(k, st)

    def test_no_global_lockdown_on_distributed(self):
        # A distributed attack must NOT lock the whole server out for real users.
        c = fresh()
        for i in range(c.distributed_attack_ips):
            c.record_failed_login(f"203.0.113.{i}", "alice")
        self.assertFalse(c.is_lockdown_active())


if __name__ == "__main__":
    unittest.main(verbosity=2)
