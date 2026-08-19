"""
Tests for the part of Cerberus that has to be true in the KERNEL rather than
in a Python set: the firewall enforcement layer.

The bug these are written against is the one the threat report described - an
address on the ban list whose attack carried on regardless. Three separate
causes, all of them here:

  * the ban only ever covered the Titan-Net ports, so an SSH brute force was
    untouched by being "banned";
  * a blanket SSH ACCEPT sat above every DROP rule in INPUT, so a port-22 drop
    would not have been reached even if one had been added;
  * a rule was assumed to exist because this process remembered adding it,
    which says nothing about whether the kernel still carries it.

They run against a fake iptables (below) rather than the real one, so they can
run anywhere, need no root, and can put the kernel into states that would be
difficult to arrange on purpose.

Run directly:  python test_cerberus_enforcement.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dangerous_cerberus as D  # noqa: E402
import cerberus as C  # noqa: E402


class Result:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


class FakeIptables:
    """Enough of iptables to be wrong in the same ways the real one can be."""

    def __init__(self, who_output="", nat=True):
        self.chains = {"INPUT": []}     # chain -> [rule as tuple]
        # The nat table, where the answering redirect lives. ``nat=False`` is
        # a host that has not got one - a container, an nftables-only box -
        # where the ban has to stay silent rather than grow a hole.
        self.nat = {"PREROUTING": []} if nat else None
        self.who_output = who_output
        self.calls = []

    # -- the parts under test poke at this directly ---------------------

    def rules(self, chain):
        return list(self.chains.get(chain, []))

    def nat_rules(self, chain="PREROUTING"):
        return list((self.nat or {}).get(chain, []))

    def flush(self, chain):
        self.chains[chain] = []

    def demote_chain_jump(self):
        """Push the jump into CERBERUS below the SSH ACCEPT, which is the
        state in which a port-22 DROP is never reached."""
        rules = self.chains["INPUT"]
        jump = ("-j", "CERBERUS")
        if jump in rules:
            rules.remove(jump)
            rules.append(jump)

    # -- the fake command ------------------------------------------------

    def run(self, args, **kw):
        self.calls.append(list(args))
        cmd = args[0]
        if cmd == "who":
            return Result(0, self.who_output)
        if cmd == "ufw":
            return Result(0, "")
        if cmd != "iptables":
            return Result(1, "")

        args = list(args)
        table = self.chains
        if args[1] == "-t":
            if args[2] != "nat" or self.nat is None:
                return Result(1, "")
            table = self.nat
            del args[1:3]
        op = args[1]
        chains = table
        if op == "-N":
            chain = args[2]
            if chain in chains:
                return Result(1, "")
            chains[chain] = []
            return Result(0, "")
        if op == "-S":
            chain = args[2]
            if chain not in chains:
                return Result(1, "")
            out = [f"-P {chain} ACCEPT"] if chain == "INPUT" else []
            out += [f"-A {chain} " + " ".join(r) for r in chains[chain]]
            return Result(0, "\n".join(out) + "\n")
        if op == "-C":
            chain, rule = args[2], tuple(args[3:])
            return Result(0 if rule in chains.get(chain, []) else 1, "")
        if op == "-A":
            chain, rule = args[2], tuple(args[3:])
            chains.setdefault(chain, []).append(rule)
            return Result(0, "")
        if op == "-I":
            chain = args[2]
            rest = list(args[3:])
            pos = 1
            if rest and rest[0].isdigit():
                pos = int(rest.pop(0))
            chains.setdefault(chain, []).insert(pos - 1, tuple(rest))
            return Result(0, "")
        if op == "-D":
            chain, rule = args[2], tuple(args[3:])
            if rule in chains.get(chain, []):
                chains[chain].remove(rule)
                return Result(0, "")
            return Result(1, "")
        return Result(1, "")


def firewall(who_output="", nat=True):
    fake = FakeIptables(who_output, nat=nat)
    fw = D.FirewallManager()
    D.subprocess.run = fake.run          # the only seam that matters
    return fw, fake


class ChainPlacement(unittest.TestCase):
    def test_chain_is_installed_above_the_ssh_accept(self):
        fw, fake = firewall()
        fw.protect_ssh()
        self.assertEqual(fake.chains["INPUT"][0], ("-j", "CERBERUS"))
        self.assertIn(("-p", "tcp", "--dport", "22", "-j", "ACCEPT"),
                      fake.chains["INPUT"])

    def test_ssh_accept_is_inserted_once(self):
        fw, fake = firewall()
        fw.protect_ssh()
        fw._ssh_protected = False        # as a second process start would
        fw.protect_ssh()
        accepts = [r for r in fake.chains["INPUT"] if r[-1] == "ACCEPT"]
        self.assertEqual(len(accepts), 1)

    def test_a_demoted_jump_is_put_back_on_top(self):
        fw, fake = firewall()
        fw.protect_ssh()
        fake.demote_chain_jump()
        self.assertNotEqual(fake.chains["INPUT"][0], ("-j", "CERBERUS"))
        fw._chain_ready = False
        fw._ensure_chain()
        self.assertEqual(fake.chains["INPUT"][0], ("-j", "CERBERUS"))
        self.assertEqual(
            len([r for r in fake.chains["INPUT"] if r == ("-j", "CERBERUS")]), 1)


class Blocking(unittest.TestCase):
    # The addresses here are public on purpose: Python counts the
    # documentation ranges (203.0.113.0/24 and friends) as private, and a
    # private address is deliberately never dropped on port 22.
    def test_titan_net_ports_by_default(self):
        fw, fake = firewall()
        fw.block_ip("203.0.113.5")
        rules = fake.rules("CERBERUS")
        self.assertEqual(len(rules), 2)
        for rule in rules:
            self.assertIn("--dport", rule)

    def test_ssh_attacker_is_blocked_on_every_port(self):
        fw, fake = firewall()
        fw.block_ip("144.48.8.86", all_ports=True)
        self.assertEqual(fake.rules("CERBERUS"),
                         [("-s", "144.48.8.86", "-j", "DROP")])

    def test_blocking_twice_does_not_duplicate_rules(self):
        fw, fake = firewall()
        fw.block_ip("203.0.113.7")
        fw.block_ip("203.0.113.7")
        self.assertEqual(len(fake.rules("CERBERUS")), 2)

    def test_a_private_address_is_never_blocked_on_ssh(self):
        fw, fake = firewall()
        fw.block_ip("192.168.1.50", all_ports=True)
        for rule in fake.rules("CERBERUS"):
            self.assertIn("--dport", rule)

    def test_a_live_ssh_session_is_never_locked_out(self):
        # The operator is holding the box from 93.184.216.34 - whatever else
        # happens, their port 22 must not be dropped.
        fw, fake = firewall(who_output="root pts/0 2026-08-19 10:00 (93.184.216.34)\n")
        self.assertFalse(fw.may_block_all_ports("93.184.216.34"))
        fw.block_ip("93.184.216.34", all_ports=True)
        for rule in fake.rules("CERBERUS"):
            self.assertIn("--dport", rule)

    def test_an_ordinary_attacker_may_be_blocked_everywhere(self):
        fw, _ = firewall(who_output="root pts/0 2026-08-19 10:00 (93.184.216.34)\n")
        self.assertTrue(fw.may_block_all_ports("144.48.8.86"))

    def test_unblocking_removes_every_form_of_the_rule(self):
        fw, fake = firewall()
        fw.block_ip("144.48.8.87", all_ports=True)
        fw.unblock_ip("144.48.8.87")
        self.assertEqual(fake.rules("CERBERUS"), [])


class Verification(unittest.TestCase):
    """A ban list records an intention; only the kernel knows what is dropped."""

    def test_a_flushed_rule_is_noticed_and_restored(self):
        fw, fake = firewall()
        fw.block_ip("203.0.113.9")
        fake.flush("CERBERUS")
        self.assertTrue(fw.verify_ban("203.0.113.9"))
        self.assertEqual(len(fake.rules("CERBERUS")), 2)

    def test_a_ban_in_force_reports_nothing_to_repair(self):
        fw, _ = firewall()
        fw.block_ip("203.0.113.10")
        self.assertFalse(fw.verify_ban("203.0.113.10"))

    def test_a_shadowed_chain_counts_as_not_in_force(self):
        fw, fake = firewall()
        fw.block_ip("144.48.8.88", all_ports=True)
        fake.demote_chain_jump()
        self.assertTrue(fw.verify_ban("144.48.8.88"))
        self.assertEqual(fake.chains["INPUT"][0], ("-j", "CERBERUS"))

    def test_reconcile_repairs_every_ban(self):
        fw, fake = firewall()
        for i in range(3):
            fw.block_ip(f"203.0.113.{20 + i}")
        fake.flush("CERBERUS")
        self.assertEqual(fw.reconcile([f"203.0.113.{20 + i}" for i in range(3)], []), 3)

    def test_the_scope_of_a_ban_survives_a_restart(self):
        fw, fake = firewall()
        fw.restore_bans(["144.48.8.86"], [], all_port_ips={"144.48.8.86"})
        self.assertIn(("-s", "144.48.8.86", "-j", "DROP"),
                      fake.rules("CERBERUS"))

    def test_a_restored_all_ports_ban_is_answered_again(self):
        """An all-ports ban is exactly the case where port 22 is dropped, so
        it is exactly the case that is silent on the service being attacked.
        The answering channel has to come back with the ban, or every address
        banned before the last restart goes mute."""
        fw, fake = firewall()
        fw.restore_bans(["144.48.8.86"], [], all_port_ips={"144.48.8.86"})
        self.assertIn("144.48.8.86", fw.answered_ips())
        self.assertIn(("-p", "tcp", "-s", "144.48.8.86", "--dport", "22",
                       "-j", "REDIRECT", "--to-ports", str(fw.ANSWER_PORT)),
                      fake.nat_rules())


class Answering(unittest.TestCase):
    """A ban that says something rather than dropping the attacker into
    silence. This is what left the Blackwall transcript empty: every attacker
    was on SSH, and a DROP has nothing to say."""

    def test_the_redirect_and_the_way_through_are_both_installed(self):
        fw, fake = firewall()
        fw.block_ip("185.246.130.20", all_ports=True)
        self.assertTrue(fw.open_answer_channel("185.246.130.20"))
        self.assertIn(("-p", "tcp", "-s", "185.246.130.20", "--dport", "22",
                       "-j", "REDIRECT", "--to-ports", str(fw.ANSWER_PORT)),
                      fake.nat_rules())
        self.assertIn(("-s", "185.246.130.20", "-p", "tcp",
                       "--dport", str(fw.ANSWER_PORT), "-j", "ACCEPT"),
                      fake.rules("CERBERUS"))

    def test_the_way_through_sits_above_this_address_own_drop(self):
        """Appended below the DROP it would never be reached, and the
        redirected packet would be eaten by the very ban that redirected it."""
        fw, fake = firewall()
        fw.block_ip("185.246.130.21", all_ports=True)
        fw.open_answer_channel("185.246.130.21")
        rules = fake.rules("CERBERUS")
        accept = rules.index(("-s", "185.246.130.21", "-p", "tcp",
                              "--dport", str(fw.ANSWER_PORT), "-j", "ACCEPT"))
        drop = rules.index(("-s", "185.246.130.21", "-j", "DROP"))
        self.assertLess(accept, drop)

    def test_the_ban_itself_is_untouched(self):
        fw, fake = firewall()
        fw.block_ip("185.246.130.22", all_ports=True)
        fw.open_answer_channel("185.246.130.22")
        self.assertIn(("-s", "185.246.130.22", "-j", "DROP"),
                      fake.rules("CERBERUS"))

    def test_the_operator_own_ssh_session_is_never_redirected(self):
        """Sending the operator's next login into a tar pit is how somebody
        loses their own server."""
        fw, fake = firewall(who_output="root pts/0 2026-08-19 (203.0.113.55)")
        self.assertFalse(fw.open_answer_channel("203.0.113.55"))
        self.assertEqual(fake.nat_rules(), [])

    def test_a_private_address_is_never_redirected(self):
        fw, fake = firewall()
        self.assertFalse(fw.open_answer_channel("192.168.1.40"))
        self.assertEqual(fake.nat_rules(), [])

    def test_no_nat_table_means_a_silent_ban_and_no_hole(self):
        """With nowhere to redirect to, the ACCEPT would be a hole punched
        through the ban for a channel that does not exist."""
        fw, fake = firewall(nat=False)
        fw.block_ip("185.246.130.23", all_ports=True)
        self.assertFalse(fw.open_answer_channel("185.246.130.23"))
        self.assertEqual(fake.rules("CERBERUS"),
                         [("-s", "185.246.130.23", "-j", "DROP")])
        self.assertNotIn("185.246.130.23", fw.answered_ips())

    def test_lifting_the_ban_stops_the_answering(self):
        fw, fake = firewall()
        fw.block_ip("185.246.130.24", all_ports=True)
        fw.open_answer_channel("185.246.130.24")
        fw.unblock_ip("185.246.130.24")
        self.assertEqual(fake.nat_rules(), [])
        self.assertEqual(fw.answered_ips(), [])

    def test_a_flushed_channel_is_repaired_with_the_ban(self):
        fw, fake = firewall()
        fw.block_ip("185.246.130.25", all_ports=True)
        fw.open_answer_channel("185.246.130.25")
        fake.flush("CERBERUS")
        fake.nat["PREROUTING"] = []
        self.assertTrue(fw.verify_ban("185.246.130.25"))
        self.assertIn(("-p", "tcp", "-s", "185.246.130.25", "--dport", "22",
                       "-j", "REDIRECT", "--to-ports", str(fw.ANSWER_PORT)),
                      fake.nat_rules())

    def test_it_can_be_switched_off_entirely(self):
        fw, fake = firewall()
        fw.answer_ssh = False
        self.assertFalse(fw.open_answer_channel("185.246.130.26"))
        self.assertEqual(fake.nat_rules(), [])


class ThroughCerberus(unittest.TestCase):
    """The same, driven from Cerberus rather than called directly."""

    def make(self):
        d = tempfile.mkdtemp()
        fake = FakeIptables()
        D.subprocess.run = fake.run
        c = D.DangerousCerberus(log_dir=os.path.join(d, "logs"),
                                db_dir=os.path.join(d, "db"))
        return c, fake

    def test_an_ssh_brute_force_is_blocked_on_port_22(self):
        c, fake = self.make()
        # Two system accounts read out of the machine's own auth log.
        c.record_failed_login("144.48.8.86", "ubuntu", source="ssh")
        c.record_failed_login("144.48.8.86", "debian", source="ssh")
        self.assertTrue(c.is_ip_banned("144.48.8.86"))
        self.assertIn(("-s", "144.48.8.86", "-j", "DROP"), fake.rules("CERBERUS"))

    def test_a_titan_net_attacker_keeps_the_narrow_ban(self):
        c, fake = self.make()
        c._set_ip_threat("203.0.113.30", C.THREAT_LOCKDOWN, "brute force")
        for rule in fake.rules("CERBERUS"):
            self.assertIn("--dport", rule)

    def test_a_manual_ban_reaches_the_kernel(self):
        # ban_ip used to be a set membership and nothing else.
        c, fake = self.make()
        c.ban_ip("203.0.113.31", permanent=False, reason="moderator")
        self.assertTrue(any(r[1] == "203.0.113.31" for r in fake.rules("CERBERUS")))

    def test_a_permaban_covers_everything(self):
        c, fake = self.make()
        c.ban_ip("144.48.8.89", permanent=True, reason="risk score climbing")
        self.assertIn(("-s", "144.48.8.89", "-j", "DROP"), fake.rules("CERBERUS"))

    def test_a_whitelisted_address_never_reaches_the_kernel(self):
        c, fake = self.make()
        c.add_whitelisted_ip("144.48.8.90")
        c._set_ip_threat("144.48.8.90", C.THREAT_CERBERUS, "mistake")
        self.assertEqual(fake.rules("CERBERUS"), [])

    def test_traffic_from_a_banned_address_repairs_the_rule(self):
        c, fake = self.make()
        c._set_ip_threat("203.0.113.33", C.THREAT_LOCKDOWN, "brute force")
        fake.flush("CERBERUS")
        c.record_failed_login("203.0.113.33", "alice")
        self.assertEqual(len(fake.rules("CERBERUS")), 2)

    def test_the_ban_count_survives_a_restart(self):
        d = tempfile.mkdtemp()
        fake = FakeIptables()
        D.subprocess.run = fake.run
        first = D.DangerousCerberus(log_dir=os.path.join(d, "logs"),
                                    db_dir=os.path.join(d, "db"))
        first._set_ip_threat("203.0.113.34", C.THREAT_LOCKDOWN, "brute force")
        second = D.DangerousCerberus(log_dir=os.path.join(d, "logs"),
                                     db_dir=os.path.join(d, "db"))
        # It has been banned before, so the next ban is not a soft one.
        self.assertGreaterEqual(second._offense_history.get("203.0.113.34", 0), 1)
        second._set_ip_threat("203.0.113.34", C.THREAT_LOCKDOWN, "again")
        self.assertIn("203.0.113.34", second._permanent_banned_ips)


if __name__ == "__main__":
    unittest.main(verbosity=2)
