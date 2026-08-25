"""
Tests for the false-positive work on Cerberus (2026-08-24).

Every case here is one that really happened on production, or one the audit
that followed showed could happen next:

  * 'crypto', 'docker' and 'root' were driven into a protective account lock by
    an SSH brute force, on a server where none of the three is an account;
  * 'root' was locked at all, although the rule has always been that a reserved
    name is never locked - the single-account path honoured it and the
    distributed path did not;
  * of the addresses that ended up permanently banned, 194 had made exactly one
    failed login and 94 had made two: they were banned for CONVERGING on a
    username, and the username was 'root', which every scanner on the internet
    tries against every host it finds;
  * and no ban ever expired, because the ``permanent`` column was written from
    the beginning and never once read back, so a wrong ban was for ever.

Run directly:  python test_cerberus_false_positives.py
No root, no firewall, no network - the DangerousCerberus cases use a fake
iptables and a temporary database.
"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cerberus as C  # noqa: E402


def fresh(**kw):
    d = tempfile.mkdtemp()
    return C.CerberusProtocol(log_dir=os.path.join(d, "logs"), **kw)


def spread(n, start=1):
    """n addresses in DIFFERENT /24s, so the subnet detector stays out of it.

    Without this every 'distributed attack' test is really a subnet test: five
    addresses in 203.0.113.x trip ``subnet_bruteforce_ips`` on their own and
    are banned for that, whatever the account correlator decided.
    """
    return [f"198.51.{start + i}.7" for i in range(n)]


class SshFailuresDoNotLockTitanNetAccounts(unittest.TestCase):
    """The lock is on the Titan-Net account namespace. sshd's usernames are
    UNIX accounts that merely spell the same, and conflating the two lets
    anyone on the internet take a Titan-Net user offline without ever
    connecting to Titan-Net."""

    def test_ssh_failures_never_lock(self):
        c = fresh()
        for _ in range(c.account_lock_failures * 3):
            c.record_failed_login("198.51.100.9", "alice", source="ssh")
        self.assertFalse(c.is_account_locked("alice"))

    def test_app_failures_still_lock(self):
        c = fresh()
        for _ in range(c.account_lock_failures):
            c.record_failed_login("198.51.100.9", "alice", source="app")
        self.assertTrue(c.is_account_locked("alice"))

    def test_ssh_brute_force_still_bans_the_address(self):
        """Refusing to lock the account must not mean ignoring the attacker."""
        c = fresh()
        blocked = False
        for _ in range(c.lockdown_failed_logins + 1):
            blocked = c.record_failed_login("198.51.100.9", "alice", source="ssh") or blocked
        self.assertTrue(blocked)
        self.assertTrue(c.is_ip_banned("198.51.100.9"))

    def test_a_real_users_own_name_survives_an_ssh_sweep(self):
        """The concrete danger: a Titan-Net user called 'support' taken offline
        in fifteen-minute slices by an SSH sweep they have nothing to do with."""
        c = fresh()
        c.is_real_account = lambda u: u.lower() == "support"
        for i in range(c.account_lock_failures * 2):
            c.record_failed_login(f"198.51.{i}.4", "support", source="ssh")
        self.assertFalse(c.is_account_locked("support"))


class ReservedNamesAreNeverLocked(unittest.TestCase):
    def test_root_not_locked_by_the_distributed_path(self):
        """The bug: this path locked unconditionally, so 'root' was locked on
        production on 2026-08-24 despite the reserved-name rule."""
        c = fresh()
        for ip in spread(c.distributed_attack_ips + 2):
            for _ in range(c.distributed_attack_min_failures):
                c.record_failed_login(ip, "root", source="app")
        self.assertFalse(c.is_account_locked("root"))

    def test_root_not_locked_by_the_single_account_path(self):
        c = fresh()
        for _ in range(c.account_lock_failures * 2):
            c.record_failed_login("198.51.100.9", "root", source="app")
        self.assertFalse(c.is_account_locked("root"))

    def test_crypto_and_docker_are_reserved_now(self):
        """Both drove a real protective lock on production; neither was on any
        reserved list, so a service-account sweep read as an attack on an
        ordinary user."""
        c = fresh()
        for name in ("crypto", "docker"):
            self.assertIn(name, c._reserved_usernames, name)

    def test_a_registered_account_keeps_its_protection(self):
        """A reserved name that IS registered has an owner to protect."""
        c = fresh()
        c.is_real_account = lambda u: u.lower() == "admin"
        for _ in range(c.account_lock_failures):
            c.record_failed_login("198.51.100.9", "admin", source="app")
        self.assertTrue(c.is_account_locked("admin"))


class CorrelationNeedsASpecificTarget(unittest.TestCase):
    """Converging on 'root' identifies nobody: it is the base rate of the
    internet, not a campaign."""

    def test_no_campaign_is_declared_over_root(self):
        """These addresses ARE still banned - by the honeytoken detector, on
        the strength of their OWN three attempts at a name that does not
        exist. That is the right reason. What must not happen is the campaign
        verdict, which bans on somebody else's behaviour and drags in whoever
        merely tried the same name once."""
        c = fresh()
        ips = spread(c.distributed_attack_ips + 3)
        for ip in ips:
            for _ in range(c.distributed_attack_min_failures):
                c.record_failed_login(ip, "root", source="ssh")
        self.assertNotIn("root", c._account_source_ips)
        self.assertEqual({}, c.get_account_guard_status()["distributed_targets"])

    def test_no_campaign_over_a_soft_reserved_name_either(self):
        c = fresh()
        ips = spread(c.distributed_attack_ips + 3, start=40)
        for ip in ips:
            for _ in range(c.distributed_attack_min_failures):
                c.record_failed_login(ip, "guest", source="ssh")
        self.assertNotIn("guest", c._account_source_ips)

    def test_a_campaign_on_a_real_account_is_still_caught(self):
        c = fresh()
        ips = spread(c.distributed_attack_ips, start=80)
        for ip in ips:
            for _ in range(c.distributed_attack_min_failures):
                c.record_failed_login(ip, "alice", source="app")
        self.assertTrue(all(c.is_ip_banned(ip) for ip in ips))
        self.assertTrue(c.is_account_locked("alice"))

    def test_a_registered_account_named_root_is_correlated_on(self):
        c = fresh()
        c.is_real_account = lambda u: u.lower() == "root"
        ips = spread(c.distributed_attack_ips, start=120)
        for ip in ips:
            for _ in range(c.distributed_attack_min_failures):
                c.record_failed_login(ip, "root", source="app")
        self.assertTrue(all(c.is_ip_banned(ip) for ip in ips))


class SharingATargetIsNotSharingAnOperator(unittest.TestCase):
    """A single attempt is what an internet-wide scanner makes against every
    host it walks past. It must not be a permanent, all-ports ban just because
    four other addresses tried the same name in the same quarter of an hour."""

    def test_passers_by_are_not_banned(self):
        c = fresh()
        ips = spread(c.distributed_attack_ips + 2, start=160)
        for ip in ips:
            c.record_failed_login(ip, "alice", source="app")   # one each
        self.assertEqual([], [ip for ip in ips if c.is_ip_banned(ip)])

    def test_the_account_is_still_protected_from_them(self):
        """The lock is cheap, short and undone by one correct password, so
        converging on the account at all is enough to earn it. Only the BAN
        needs proof."""
        c = fresh()
        for ip in spread(c.distributed_attack_ips, start=200):
            c.record_failed_login(ip, "alice", source="app")
        self.assertTrue(c.is_account_locked("alice"))

    def test_proven_participants_are_banned_and_passers_by_are_not(self):
        c = fresh()
        real = spread(c.distributed_attack_ips, start=30)
        passer = "203.0.55.9"
        for ip in real:
            for _ in range(c.distributed_attack_min_failures):
                c.record_failed_login(ip, "alice", source="app")
        c.record_failed_login(passer, "alice", source="app")
        self.assertTrue(all(c.is_ip_banned(ip) for ip in real))
        self.assertFalse(c.is_ip_banned(passer))

    def test_a_passer_by_is_still_visible_as_an_alert(self):
        """Not banned is not the same as not noticed - it stays correlated
        with anything else it does."""
        c = fresh()
        for ip in spread(c.distributed_attack_ips, start=90):
            for _ in range(c.distributed_attack_min_failures):
                c.record_failed_login(ip, "alice", source="app")
        passer = "203.0.77.9"
        c.record_failed_login(passer, "alice", source="app")
        self.assertGreaterEqual(
            c._ip_threat.get(passer, {}).get("level", 0), C.THREAT_ALERT)
        self.assertFalse(c.is_ip_banned(passer))


class IntrusionLogKeepsItsHistory(unittest.TestCase):
    def test_retention_is_long_enough_to_answer_a_threat_report(self):
        """It used to rotate every 2 days keeping 1 backup - about four days,
        which cannot answer 'has this address been here before'."""
        self.assertGreaterEqual(C.INTRUSION_LOG_DAYS, 30)

    def test_the_handler_rotates_rather_than_truncates(self):
        c = fresh()
        handler = c._intrusion_logger.handlers[0]
        self.assertEqual(handler.backupCount, C.INTRUSION_LOG_DAYS)
        self.assertEqual(handler.when, 'MIDNIGHT')

    def test_the_server_no_longer_clears_logs_on_a_timer(self):
        """clear_logs stays as a moderator command; nothing schedules it."""
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "server.py"), encoding="utf-8") as f:
            body = f.read()
        loop = body.split("async def _cerberus_log_cleanup_loop", 1)[1]
        loop = loop.split("\n    async def ", 1)[0]
        self.assertNotIn("clear_logs()", loop)


# --------------------------------------------------------------------------
# Ban expiry - needs the DangerousCerberus subclass, its database and a fake
# iptables. Skipped rather than failed if the subclass cannot be imported.
# --------------------------------------------------------------------------

try:
    import dangerous_cerberus as D
except Exception:                                   # pragma: no cover
    D = None


class _NoFirewall:
    """Stands in for FirewallManager: records, touches no kernel."""

    def __init__(self):
        self.blocked = set()
        self.unblocked = []

    def block_ip(self, ip, all_ports=False):
        self.blocked.add(ip)
        return True

    def unblock_ip(self, ip):
        self.blocked.discard(ip)
        self.unblocked.append(ip)
        return True

    def block_subnet(self, subnet, all_ports=False):
        return True

    def verify_ban(self, ip):
        return False

    def reconcile(self, ips, subnets):
        return 0

    def open_answer_channel(self, ip):
        return False

    def close_answer_channel(self, ip):
        return False

    def protect_ssh(self):
        return True

    def may_block_all_ports(self, ip):
        return True

    def active_ssh_peers(self):
        return set()

    def sync_from_kernel(self):
        return None

    def restore_bans(self, ips, subnets, all_port_ips=()):
        return 0


@unittest.skipIf(D is None, "dangerous_cerberus not importable")
class BansRunOut(unittest.TestCase):
    """No ban ever expired: ``permanent`` was written and never read, so the
    295 addresses in production's ban database were all there for ever - and a
    false positive among them had no way out but somebody noticing by hand."""

    def make(self):
        d = tempfile.mkdtemp()
        c = D.DangerousCerberus(log_dir=os.path.join(d, "logs"),
                                db_dir=os.path.join(d, "db"))
        c.firewall = _NoFirewall()
        c.auto_firewall = True
        c.auto_subnet_ban = False
        return c

    def test_a_lockdown_ban_is_given_a_term(self):
        c = self.make()
        c._set_ip_threat("198.51.100.5", D.THREAT_LOCKDOWN, "brute force")
        rows = self._rows(c, "198.51.100.5")
        self.assertEqual(0, rows["permanent"])
        self.assertGreater(rows["expires_at"], time.time())

    def test_a_cerberus_ban_is_permanent(self):
        c = self.make()
        c._set_ip_threat("198.51.100.6", D.THREAT_CERBERUS, "massive brute force")
        rows = self._rows(c, "198.51.100.6")
        self.assertEqual(1, rows["permanent"])
        self.assertEqual(0, rows["expires_at"])

    def test_the_term_grows_with_each_offence(self):
        c = self.make()
        first = c._ban_expiry("198.51.100.7")
        c._offense_history["198.51.100.7"] = 2
        third = c._ban_expiry("198.51.100.7")
        self.assertGreater(third, first)

    def test_a_persistent_attacker_stops_being_let_out(self):
        c = self.make()
        c._offense_history["198.51.100.8"] = len(c.BAN_TERMS) + 1
        self.assertEqual(0.0, c._ban_expiry("198.51.100.8"))

    def test_an_expired_ban_is_lifted_everywhere(self):
        c = self.make()
        ip = "198.51.100.10"
        c._set_ip_threat(ip, D.THREAT_LOCKDOWN, "brute force")
        self.assertTrue(c.is_ip_banned(ip))
        self._expire(c, ip)
        self.assertEqual(1, c.release_expired_bans())
        self.assertFalse(c.is_ip_banned(ip))
        self.assertIn(ip, c.firewall.unblocked)
        self.assertNotIn(ip, c.firewall.blocked)

    def test_a_permanent_ban_is_never_lifted(self):
        c = self.make()
        ip = "198.51.100.11"
        c._set_ip_threat(ip, D.THREAT_CERBERUS, "massive brute force")
        self.assertEqual(0, c.release_expired_bans())
        self.assertTrue(c.is_ip_banned(ip))

    def test_an_expired_ban_is_not_restored_at_the_next_start(self):
        """The restore path is what made every ban permanent in practice."""
        c = self.make()
        ip = "198.51.100.12"
        c._set_ip_threat(ip, D.THREAT_LOCKDOWN, "brute force")
        self._expire(c, ip)
        self.assertNotIn(ip, c.ban_db.get_all_banned_ips())
        self.assertFalse(c.ban_db.is_banned(ip))

    def test_re_offending_extends_a_term_and_never_shortens_it(self):
        c = self.make()
        ip = "198.51.100.13"
        c.ban_db.add_ban(ip, "later", D.THREAT_LOCKDOWN, permanent=False,
                         expires_at=time.time() + 90000)
        c.ban_db.add_ban(ip, "sooner", D.THREAT_LOCKDOWN, permanent=False,
                         expires_at=time.time() + 60)
        self.assertGreater(self._rows(c, ip)["expires_at"], time.time() + 1000)

    def test_a_permanent_ban_overrides_a_term(self):
        c = self.make()
        ip = "198.51.100.14"
        c.ban_db.add_ban(ip, "temporary", D.THREAT_LOCKDOWN, permanent=False,
                         expires_at=time.time() + 60)
        c.ban_db.add_ban(ip, "for good", D.THREAT_CERBERUS, permanent=True)
        row = self._rows(c, ip)
        self.assertEqual(1, row["permanent"])
        self.assertEqual(0, row["expires_at"])

    # -- helpers ---------------------------------------------------------
    def _rows(self, c, ip):
        import sqlite3
        conn = sqlite3.connect(c.ban_db.db_path)
        conn.row_factory = sqlite3.Row
        try:
            r = conn.execute("SELECT * FROM banned_ips WHERE ip = ?", (ip,)).fetchone()
            self.assertIsNotNone(r, f"{ip} was never written to the ban database")
            return dict(r)
        finally:
            conn.close()

    def _expire(self, c, ip):
        import sqlite3
        conn = sqlite3.connect(c.ban_db.db_path)
        try:
            conn.execute("UPDATE banned_ips SET expires_at = ? WHERE ip = ?",
                         (time.time() - 5, ip))
            conn.commit()
        finally:
            conn.close()


@unittest.skipIf(D is None, "dangerous_cerberus not importable")
class TheOperatorIsToldAboutTheWhitelist(unittest.TestCase):
    def test_initialisation_is_logged_even_with_no_whitelist_file(self):
        """Both early returns used to skip the 'Initialized' line, so the
        server with no whitelist - which is what production had - started its
        most aggressive subsystem silently."""
        d = tempfile.mkdtemp()
        c = D.DangerousCerberus(log_dir=os.path.join(d, "logs"),
                                db_dir=os.path.join(d, "db"))
        c.firewall = _NoFirewall()
        c._whitelist_file = os.path.join(d, "does_not_exist.txt")
        with self.assertLogs("DangerousCerberus", level="WARNING") as caught:
            c._load_persistent_whitelist()
        joined = "\n".join(caught.output)
        self.assertIn("Initialized", joined)
        self.assertIn("does not exist", joined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
