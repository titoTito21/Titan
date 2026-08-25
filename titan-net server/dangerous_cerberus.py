"""
Dangerous Cerberus Protocol - Advanced Intrusion Response System

Extends the base Cerberus Protocol with:
  - Auto-firewall integration (iptables/ufw bans at kernel level)
  - Subnet intelligence (auto-ban entire /24 on coordinated attacks)
  - Persistent ban database (survives restarts)
  - Attacker fingerprinting and profiling
  - Escalation engine with configurable aggression levels

Threat levels (inherited from Cerberus):
  0 - NORMAL:   No threats
  1 - ALERT:    Suspicious activity - logged
  2 - LOCKDOWN: IP banned at application + firewall level
  3 - CERBERUS: Permaban + client shutdown + infrastructure countermeasures + firewall block

Dangerous Mode additions:
  4 - ANNIHILATE: Full subnet ban + firewall + persistent + OS-level block
"""

import logging
import os
import json
import sqlite3
import subprocess
import time
import ipaddress
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from cerberus import CerberusProtocol, THREAT_CERBERUS, THREAT_LOCKDOWN, THREAT_ALERT, THREAT_NORMAL, THREAT_NAMES

logger = logging.getLogger('DangerousCerberus')

# Extended threat level
THREAT_ANNIHILATE = 4
THREAT_NAMES[THREAT_ANNIHILATE] = "ANNIHILATE"


class PersistentBanDB:
    """SQLite database for persistent IP bans that survive server restarts"""

    def __init__(self, db_path: str = "database/cerberus_bans.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS banned_ips (
            ip TEXT PRIMARY KEY,
            subnet TEXT,
            reason TEXT NOT NULL,
            threat_level INTEGER NOT NULL,
            banned_at TEXT NOT NULL,
            permanent INTEGER DEFAULT 1,
            firewall_blocked INTEGER DEFAULT 0,
            attacker_fingerprint TEXT,
            total_attempts INTEGER DEFAULT 1,
            last_attempt TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS banned_subnets (
            subnet TEXT PRIMARY KEY,
            reason TEXT NOT NULL,
            ip_count INTEGER DEFAULT 1,
            banned_at TEXT NOT NULL,
            trigger_ips TEXT,
            firewall_blocked INTEGER DEFAULT 0
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS attacker_profiles (
            ip TEXT PRIMARY KEY,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            total_attempts INTEGER DEFAULT 0,
            attack_types TEXT,
            user_agents TEXT,
            usernames_tried TEXT,
            threat_score INTEGER DEFAULT 0,
            subnet TEXT,
            country TEXT,
            notes TEXT
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_banned_subnet ON banned_ips(subnet)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_banned_level ON banned_ips(threat_level)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_profile_subnet ON attacker_profiles(subnet)')
        # How far the block goes. An SSH brute-forcer is blocked on every port,
        # not just Titan-Net's, and that has to survive a restart or the
        # restored ban is narrower than the one that was imposed. Added by
        # migration so an existing database is upgraded in place.
        try:
            c.execute('ALTER TABLE banned_ips ADD COLUMN all_ports INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass  # column already there
        # When this ban stops applying (unix seconds; 0 = never). The
        # ``permanent`` column was written from the start and never read back,
        # so a LOCKDOWN ban the code called temporary was restored on every
        # boot and enforced for ever: 295 addresses had accumulated here, and
        # a wrong one among them had no way out but a moderator noticing it by
        # hand. A term that runs out is what makes a false positive survivable.
        try:
            c.execute('ALTER TABLE banned_ips ADD COLUMN expires_at REAL DEFAULT 0')
        except sqlite3.OperationalError:
            pass  # column already there
        c.execute('CREATE INDEX IF NOT EXISTS idx_banned_expiry ON banned_ips(expires_at)')
        # A /24 ban is the highest-collateral thing Cerberus does - it blocks
        # 254 addresses on the evidence of a handful, and behind a CGNAT range
        # that is an entire neighbourhood of subscribers. It had no expiry
        # column at all, so it was the one action that was always permanent
        # and the one that should least have been. Terms are deliberately
        # SHORTER than an individual ban's for the same reason.
        try:
            c.execute('ALTER TABLE banned_subnets ADD COLUMN expires_at REAL DEFAULT 0')
        except sqlite3.OperationalError:
            pass  # column already there
        conn.commit()
        conn.close()

    def add_ban(self, ip: str, reason: str, threat_level: int,
                permanent: bool = True, fingerprint: str = "",
                all_ports: bool = False, expires_at: float = 0.0) -> bool:
        """Add IP to persistent ban database. Returns True if new ban.

        ``expires_at`` is when the ban stops applying (unix seconds); 0 means
        never. A permanent ban always wins over a temporary one, and between
        two temporary ones the later expiry wins - re-offending extends a
        term, it never shortens it.
        """
        subnet = str(ipaddress.ip_network(f"{ip}/24", strict=False))
        now = datetime.now().isoformat()
        if permanent:
            expires_at = 0.0
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('''INSERT INTO banned_ips
                (ip, subnet, reason, threat_level, banned_at, permanent,
                 attacker_fingerprint, total_attempts, last_attempt, all_ports,
                 expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(ip) DO UPDATE SET
                    reason = excluded.reason,
                    threat_level = MAX(threat_level, excluded.threat_level),
                    permanent = MAX(permanent, excluded.permanent),
                    total_attempts = total_attempts + 1,
                    last_attempt = excluded.last_attempt,
                    all_ports = MAX(all_ports, excluded.all_ports),
                    expires_at = CASE
                        WHEN MAX(permanent, excluded.permanent) = 1 THEN 0
                        WHEN expires_at = 0 OR excluded.expires_at = 0 THEN 0
                        ELSE MAX(expires_at, excluded.expires_at)
                    END
            ''', (ip, subnet, reason, threat_level, now, int(permanent),
                  fingerprint, now, int(all_ports), float(expires_at or 0.0)))
            conn.commit()
            return c.rowcount > 0
        finally:
            conn.close()

    def purge_expired(self) -> List[str]:
        """Delete every ban whose term has run out. Returns the IPs freed, so
        the caller can take their firewall rules down too."""
        now = time.time()
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('SELECT ip FROM banned_ips '
                      'WHERE permanent = 0 AND expires_at > 0 AND expires_at <= ?',
                      (now,))
            freed = [row[0] for row in c.fetchall()]
            if freed:
                c.execute('DELETE FROM banned_ips '
                          'WHERE permanent = 0 AND expires_at > 0 AND expires_at <= ?',
                          (now,))
                conn.commit()
            return freed
        finally:
            conn.close()

    def get_all_port_ips(self) -> List[str]:
        """IPs whose ban covers every port, not just the Titan-Net ones."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('SELECT ip FROM banned_ips WHERE all_ports = 1 AND '
                      '(permanent = 1 OR expires_at = 0 OR expires_at > ?)', (time.time(),))
            return [row[0] for row in c.fetchall()]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    def get_ban_counts(self) -> Dict[str, int]:
        """{ip: how many times it has been banned}. Seeds the repeat-offender
        escalation, which otherwise starts from zero at every restart - so an
        attacker only had to outlast one service restart to get a soft ban
        again instead of the permaban their history had earned."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('SELECT ip, total_attempts FROM banned_ips')
            return {row[0]: int(row[1] or 1) for row in c.fetchall()}
        except sqlite3.OperationalError:
            return {}
        finally:
            conn.close()


    def add_subnet_ban(self, subnet: str, reason: str, trigger_ips: List[str],
                       expires_at: float = 0.0) -> bool:
        """Ban an entire subnet until ``expires_at`` (0 = never)."""
        now = datetime.now().isoformat()
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('''INSERT INTO banned_subnets
                (subnet, reason, ip_count, banned_at, trigger_ips, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(subnet) DO UPDATE SET
                    reason = excluded.reason,
                    ip_count = excluded.ip_count,
                    expires_at = CASE
                        WHEN expires_at = 0 OR excluded.expires_at = 0 THEN 0
                        ELSE MAX(expires_at, excluded.expires_at)
                    END
            ''', (subnet, reason, len(trigger_ips), now,
                  json.dumps(trigger_ips), float(expires_at or 0.0)))
            conn.commit()
            return True
        finally:
            conn.close()

    def purge_expired_subnets(self) -> List[str]:
        """Delete every subnet ban whose term has run out; return them."""
        now = time.time()
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('SELECT subnet FROM banned_subnets '
                      'WHERE expires_at > 0 AND expires_at <= ?', (now,))
            freed = [row[0] for row in c.fetchall()]
            if freed:
                c.execute('DELETE FROM banned_subnets '
                          'WHERE expires_at > 0 AND expires_at <= ?', (now,))
                conn.commit()
            return freed
        finally:
            conn.close()

    def is_banned(self, ip: str) -> bool:
        """Check if IP or its subnet is banned"""
        subnet = str(ipaddress.ip_network(f"{ip}/24", strict=False))
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('SELECT 1 FROM banned_ips WHERE ip = ? AND '
                      '(permanent = 1 OR expires_at = 0 OR expires_at > ?)', (ip, time.time()))
            if c.fetchone():
                return True
            c.execute('SELECT 1 FROM banned_subnets WHERE subnet = ? AND '
                      '(expires_at = 0 OR expires_at > ?)', (subnet, time.time()))
            return c.fetchone() is not None
        finally:
            conn.close()

    def get_all_banned_ips(self) -> List[str]:
        """Get all banned IPs"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('SELECT ip FROM banned_ips WHERE '
                      '(permanent = 1 OR expires_at = 0 OR expires_at > ?)', (time.time(),))
            return [row[0] for row in c.fetchall()]
        finally:
            conn.close()

    def get_all_banned_subnets(self) -> List[str]:
        """Get all banned subnets"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('SELECT subnet FROM banned_subnets WHERE '
                      '(expires_at = 0 OR expires_at > ?)', (time.time(),))
            return [row[0] for row in c.fetchall()]
        finally:
            conn.close()

    def get_subnet_attack_count(self, ip: str) -> int:
        """Count how many unique IPs from the same /24 have attacked"""
        subnet = str(ipaddress.ip_network(f"{ip}/24", strict=False))
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('SELECT COUNT(*) FROM banned_ips WHERE subnet = ?', (subnet,))
            return c.fetchone()[0]
        finally:
            conn.close()

    def get_subnet_attacker_ips(self, ip: str) -> List[str]:
        """Get all attacker IPs from the same /24"""
        subnet = str(ipaddress.ip_network(f"{ip}/24", strict=False))
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('SELECT ip FROM banned_ips WHERE subnet = ?', (subnet,))
            return [row[0] for row in c.fetchall()]
        finally:
            conn.close()

    def unban_ip(self, ip: str):
        """Remove IP ban"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM banned_ips WHERE ip = ?', (ip,))
            conn.commit()
        finally:
            conn.close()

    def unban_subnet(self, subnet: str):
        """Remove subnet ban"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM banned_subnets WHERE subnet = ?', (subnet,))
            conn.commit()
        finally:
            conn.close()

    def update_profile(self, ip: str, attack_type: str = "",
                       username: str = "", user_agent: str = ""):
        """Update or create attacker profile"""
        subnet = str(ipaddress.ip_network(f"{ip}/24", strict=False))
        now = datetime.now().isoformat()
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('SELECT * FROM attacker_profiles WHERE ip = ?', (ip,))
            row = c.fetchone()
            if row:
                # Update existing
                attack_types = set(json.loads(row[4] or '[]'))
                usernames = set(json.loads(row[6] or '[]'))
                user_agents = set(json.loads(row[5] or '[]'))
                if attack_type:
                    attack_types.add(attack_type)
                if username:
                    usernames.add(username)
                if user_agent:
                    user_agents.add(user_agent)
                c.execute('''UPDATE attacker_profiles SET
                    last_seen = ?, total_attempts = total_attempts + 1,
                    attack_types = ?, usernames_tried = ?, user_agents = ?,
                    threat_score = threat_score + 10
                    WHERE ip = ?
                ''', (now, json.dumps(list(attack_types)),
                      json.dumps(list(usernames)),
                      json.dumps(list(user_agents)), ip))
            else:
                # Create new
                c.execute('''INSERT INTO attacker_profiles
                    (ip, first_seen, last_seen, total_attempts, attack_types,
                     usernames_tried, user_agents, threat_score, subnet)
                    VALUES (?, ?, ?, 1, ?, ?, ?, 10, ?)
                ''', (ip, now, now,
                      json.dumps([attack_type] if attack_type else []),
                      json.dumps([username] if username else []),
                      json.dumps([user_agent] if user_agent else []),
                      subnet))
            conn.commit()
        finally:
            conn.close()

    def get_stats(self) -> Dict:
        """Get ban database statistics"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('SELECT COUNT(*) FROM banned_ips')
            total_ips = c.fetchone()[0]
            c.execute('SELECT COUNT(*) FROM banned_subnets')
            total_subnets = c.fetchone()[0]
            c.execute('SELECT COUNT(*) FROM attacker_profiles')
            total_profiles = c.fetchone()[0]
            c.execute('SELECT COUNT(DISTINCT subnet) FROM banned_ips')
            unique_subnets = c.fetchone()[0]
            c.execute('SELECT SUM(total_attempts) FROM attacker_profiles')
            total_attempts = c.fetchone()[0] or 0
            return {
                "banned_ips": total_ips,
                "banned_subnets": total_subnets,
                "attacker_profiles": total_profiles,
                "unique_attacker_subnets": unique_subnets,
                "total_attack_attempts": total_attempts,
            }
        finally:
            conn.close()


class FirewallManager:
    """Manages iptables/ufw rules for kernel-level IP blocking.

    Every Cerberus rule lives in a dedicated ``CERBERUS`` chain that INPUT
    jumps to as its FIRST rule, and that placement is the whole point. SSH is
    protected by a blanket ``--dport 22 -j ACCEPT`` rule at the top of INPUT,
    so a per-attacker DROP appended to INPUT after it is never reached: an SSH
    brute-forcer could sit on the ban list, be "blocked", and carry on
    attacking untouched. Rules in a chain evaluated BEFORE that ACCEPT can
    actually stop them.

    SAFETY, in the order it is enforced:
      - the blanket SSH ACCEPT stays exactly where it is, so the rest of the
        world's SSH is unaffected; only a named attacker is dropped
      - an address with a live, logged-in SSH session is never dropped on port
        22, so the operator cannot lock themselves out with their own ban
      - loopback and private addresses are never blocked beyond the Titan-Net
        ports
      - the kernel is asked before every rule is added (``iptables -C``), so a
        rule is never duplicated - and never merely assumed to be there
    """

    # Ports Cerberus blocks for an ordinary Titan-Net attacker.
    BLOCKED_PORTS = [8000, 8001]

    # Ports that must never be blocked for the world at large.
    PROTECTED_PORTS = [22]

    # Cerberus' own chain, evaluated before INPUT's SSH ACCEPT.
    CHAIN = 'CERBERUS'

    # Where a banned SSH attacker's port 22 is answered instead of dropped.
    # A DROP is silence, and silence is what left Blackwall's transcript empty
    # on a server that had been under attack for a fortnight: every attacker
    # was on SSH, and being banned meant their packets stopped existing rather
    # than being answered. Their port 22 is redirected into the tar pit, which
    # is Blackwall's one channel to somebody sitting at a terminal - the ban
    # still holds (nothing of this server is reachable through it, and the
    # DROP below it stays exactly as it was), but the door they are knocking
    # on now says something back, and wastes their time while it does.
    ANSWER_PORT = int(os.environ.get('TAR_PIT_PORT', 2223))

    def __init__(self):
        self._blocked_ips: Set[str] = set()
        self._blocked_subnets: Set[str] = set()
        # IPs blocked on EVERY port (SSH attackers, permabans) rather than
        # just the Titan-Net ones.
        self._all_port_ips: Set[str] = set()
        self._ssh_protected = False
        self._chain_ready = False
        # False once iptables turns out not to be installed (dev machines).
        self.available = True
        self._ssh_peers: Set[str] = set()
        self._ssh_peers_ts = 0.0
        self.repairs = 0
        # Addresses whose SSH is answered rather than dropped.
        self._answered: Set[str] = set()
        self.answer_ssh = os.environ.get('BLACKWALL_ANSWER_SSH', '1') == '1'

    # ----------------------------------------------------------------
    # LOW LEVEL
    # ----------------------------------------------------------------

    def _run(self, args: List[str], timeout: int = 5, **kw):
        """Run one firewall command. Returns the CompletedProcess, or None if
        the command could not run at all."""
        if not self.available:
            return None
        try:
            return subprocess.run(args, capture_output=True, timeout=timeout, **kw)
        except FileNotFoundError:
            if args and args[0] == 'iptables':
                logger.warning("[FIREWALL] iptables not found, firewall features disabled.")
                self.available = False
            return None
        except Exception as e:
            logger.error(f"[FIREWALL] {' '.join(args)} failed: {e}")
            return None

    def _rule_exists(self, chain: str, rule: List[str],
                     table: str = '') -> bool:
        head = ['iptables'] + (['-t', table] if table else [])
        r = self._run(head + ['-C', chain] + rule)
        return bool(r) and r.returncode == 0

    def _ensure_rule(self, chain: str, rule: List[str], first: bool = False,
                     table: str = '') -> bool:
        """Add a rule only if the kernel does not already carry it.
        Returns True if it had to be added.

        ``first`` inserts at the top of the chain instead of appending, which
        matters for any ACCEPT: appended below this address's own DROP it
        would never be reached.
        """
        if self._rule_exists(chain, rule, table=table):
            return False
        head = ['iptables'] + (['-t', table] if table else [])
        args = (head + ['-I', chain, '1'] + rule) if first else \
               (head + ['-A', chain] + rule)
        r = self._run(args)
        return bool(r) and r.returncode == 0

    def _drop_rules(self, source: str, all_ports: bool) -> List[List[str]]:
        """The rules that constitute a block of ``source``."""
        if all_ports:
            return [['-s', source, '-j', 'DROP']]
        return [
            ['-s', source, '-p', 'tcp', '--dport', str(port), '-j', 'DROP']
            for port in self.BLOCKED_PORTS
        ]

    # ----------------------------------------------------------------
    # THE CHAIN
    # ----------------------------------------------------------------

    def _chain_is_first(self) -> bool:
        """True if INPUT's very first rule is the jump into our chain."""
        r = self._run(['iptables', '-S', 'INPUT'], timeout=10, text=True)
        if not r or r.returncode != 0:
            return False
        for line in (r.stdout or '').splitlines():
            if not line.startswith('-A INPUT'):
                continue  # the -P INPUT policy line
            return line.split() == ['-A', 'INPUT', '-j', self.CHAIN]
        return False

    def _ensure_chain(self):
        """Create the CERBERUS chain and make INPUT enter it first of all."""
        if self._chain_ready:
            return
        # -N fails harmlessly when the chain already exists.
        self._run(['iptables', '-N', self.CHAIN])
        if not self._chain_is_first():
            # A jump further down INPUT is worse than useless - the SSH ACCEPT
            # above it shadows every port-22 DROP inside. Take it out and put
            # it back at the top.
            for _ in range(4):
                if not self._rule_exists('INPUT', ['-j', self.CHAIN]):
                    break
                r = self._run(['iptables', '-D', 'INPUT', '-j', self.CHAIN])
                if not r or r.returncode != 0:
                    break
            self._run(['iptables', '-I', 'INPUT', '1', '-j', self.CHAIN])
            logger.info(f"[FIREWALL] {self.CHAIN} chain installed as INPUT rule 1")
        self._chain_ready = self.available

    def protect_ssh(self):
        """Insert permanent iptables ACCEPT rule for SSH before any DROP rules.
        Called once on startup to guarantee SSH access cannot be blocked."""
        if self._ssh_protected:
            return
        for port in self.PROTECTED_PORTS:
            # Idempotent: only insert the ACCEPT rule if the kernel does not
            # already carry it. Without this check every process start (and
            # every restore_bans / block_ip call before the flag was set)
            # inserted another identical rule at the top of INPUT - the
            # production chain had accumulated 144 duplicate SSH-ACCEPT rules
            # this way, one per restart, that netfilter walks on every packet.
            if self._rule_exists('INPUT', ['-p', 'tcp', '--dport', str(port),
                                           '-j', 'ACCEPT']):
                continue
            self._run(['iptables', '-I', 'INPUT', '1', '-p', 'tcp',
                       '--dport', str(port), '-j', 'ACCEPT'])
        self._ssh_protected = True
        if self.available:
            logger.info("[FIREWALL] SSH port protected - ACCEPT rule in INPUT")
        # Our chain has to sit ABOVE that ACCEPT, so (re)install it after.
        self._chain_ready = False
        self._ensure_chain()

    # ----------------------------------------------------------------
    # WHAT MAY BE BLOCKED, AND HOW FAR
    # ----------------------------------------------------------------

    def active_ssh_peers(self) -> Set[str]:
        """Addresses with a live, logged-in SSH session on this machine.

        These are the one thing a firewall must never drop on port 22: they
        are how the operator is holding the box. Cached for a minute, since it
        is read on the ban path."""
        now = time.time()
        if self._ssh_peers_ts and now - self._ssh_peers_ts < 60:
            return self._ssh_peers
        self._ssh_peers_ts = now
        peers: Set[str] = set()
        for var in ('SSH_CLIENT', 'SSH_CONNECTION'):
            val = os.environ.get(var, '')
            if val:
                peers.add(val.split()[0])
        r = self._run(['who'])
        if r and r.returncode == 0:
            out = r.stdout
            if isinstance(out, bytes):
                out = out.decode('utf-8', 'replace')
            for line in (out or '').splitlines():
                if '(' not in line or ')' not in line:
                    continue
                host = line[line.rfind('(') + 1:line.rfind(')')].strip()
                try:
                    ipaddress.ip_address(host)
                except ValueError:
                    continue
                peers.add(host)
        self._ssh_peers = peers
        return peers

    def may_block_all_ports(self, ip: str) -> bool:
        """Whether ``ip`` may be dropped on every port, SSH included."""
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if (addr.is_loopback or addr.is_private or addr.is_link_local
                or addr.is_unspecified):
            logger.info(
                f"[FIREWALL] {ip} is a local address - Titan-Net ports only")
            return False
        if ip in self.active_ssh_peers():
            logger.warning(
                f"[FIREWALL] {ip} holds a live SSH session - refusing to block "
                f"port 22 for it (Titan-Net ports only)")
            return False
        return True

    # ----------------------------------------------------------------
    # ANSWERING RATHER THAN DROPPING
    # ----------------------------------------------------------------

    def _answer_rules(self, ip: str):
        """(the nat redirect, the ACCEPT that lets the redirected packet
        through this address's own DROP)."""
        redirect = ['-p', 'tcp', '-s', ip, '--dport', '22',
                    '-j', 'REDIRECT', '--to-ports', str(self.ANSWER_PORT)]
        allow = ['-s', ip, '-p', 'tcp', '--dport', str(self.ANSWER_PORT),
                 '-j', 'ACCEPT']
        return redirect, allow

    def open_answer_channel(self, ip: str) -> bool:
        """Answer this address on SSH instead of dropping it.

        Refused for exactly the addresses a DROP is refused for, and for one
        more besides: an address holding a live SSH session on this machine is
        never redirected, because that is the operator, and sending their next
        login into a tar pit is how somebody loses their own server.
        """
        if not self.available or not self.answer_ssh or not ip:
            return False
        if ip in self._answered:
            return True
        if not self.may_block_all_ports(ip):
            return False
        self.protect_ssh()
        self._ensure_chain()
        redirect, allow = self._answer_rules(ip)
        # The redirect goes in first, and nothing else happens if it cannot:
        # on a box with no nat table (a container without one, an
        # nftables-only host) an ACCEPT added here would be a hole punched
        # through the ban for a channel that does not exist. A ban that is
        # merely silent is what it was before any of this, and is correct.
        added = self._ensure_rule('PREROUTING', redirect, table='nat')
        if not added and not self._rule_exists('PREROUTING', redirect,
                                               table='nat'):
            logger.info(f"[FIREWALL] cannot answer {ip} on SSH - no nat table")
            return False
        # Then the ACCEPT, at the TOP of the chain: the packet reaches the
        # filter table already rewritten to the answer port, where this
        # address's own blanket DROP would otherwise eat it.
        self._ensure_rule(self.CHAIN, allow, first=True)
        self._answered.add(ip)
        logger.warning(
            f"[FIREWALL] {ip} is banned; its SSH is answered on port "
            f"{self.ANSWER_PORT} rather than dropped in silence")
        return True

    def close_answer_channel(self, ip: str) -> bool:
        """Stop answering, and go back to nothing at all."""
        if not self.available or not ip:
            return False
        redirect, allow = self._answer_rules(ip)
        self._run(['iptables', '-t', 'nat', '-D', 'PREROUTING'] + redirect)
        self._run(['iptables', '-D', self.CHAIN] + allow)
        self._answered.discard(ip)
        return True

    def answered_ips(self) -> List[str]:
        return sorted(self._answered)

    # ----------------------------------------------------------------
    # BLOCKING
    # ----------------------------------------------------------------

    def block_ip(self, ip: str, all_ports: bool = False) -> bool:
        """Block an IP. ``all_ports`` extends the block past the Titan-Net
        ports to everything the attacker can reach, which is what an SSH brute
        force needs - a Titan-Net-ports-only ban leaves it attacking."""
        # Always ensure SSH is protected (and the chain is on top) first.
        self.protect_ssh()
        self._ensure_chain()
        if all_ports and not self.may_block_all_ports(ip):
            all_ports = False
        added = 0
        for rule in self._drop_rules(ip, all_ports):
            if self._ensure_rule(self.CHAIN, rule):
                added += 1
        if all_ports:
            self._all_port_ips.add(ip)
            self._run(['ufw', 'deny', 'from', ip], timeout=10)
        else:
            for port in self.BLOCKED_PORTS:
                self._run(['ufw', 'deny', 'from', ip, 'to', 'any',
                           'port', str(port)], timeout=10)
        self._blocked_ips.add(ip)
        if added:
            logger.info(
                f"[FIREWALL] Blocked IP {ip} "
                f"({'all ports' if all_ports else self.BLOCKED_PORTS})")
        return True

    def block_subnet(self, subnet: str, all_ports: bool = False) -> bool:
        """Block an entire /24 (Titan-Net ports unless told otherwise)."""
        self.protect_ssh()
        self._ensure_chain()
        for rule in self._drop_rules(subnet, all_ports):
            self._ensure_rule(self.CHAIN, rule)
        if all_ports:
            self._run(['ufw', 'deny', 'from', subnet], timeout=10)
        else:
            for port in self.BLOCKED_PORTS:
                self._run(['ufw', 'deny', 'from', subnet, 'to', 'any',
                           'port', str(port)], timeout=10)
        self._blocked_subnets.add(subnet)
        logger.warning(f"[FIREWALL] Blocked SUBNET: {subnet}")
        return True

    def unblock_subnet(self, subnet: str) -> bool:
        """Remove every firewall block for a whole /24.

        The counterpart of ``block_subnet``, which had none - so before subnet
        bans were given a term there was no code path anywhere that took a
        /24 rule back out of the kernel. The widest-reaching block Cerberus
        can impose was also the only one with no way to undo it.
        """
        for chain in (self.CHAIN, 'INPUT'):
            for all_ports in (True, False):
                for rule in self._drop_rules(subnet, all_ports):
                    for _ in range(8):
                        if not self._rule_exists(chain, rule):
                            break
                        r = self._run(['iptables', '-D', chain] + rule)
                        if not r or r.returncode != 0:
                            break
        self._run(['ufw', 'delete', 'deny', 'from', subnet], input=b'y\n', timeout=10)
        for port in self.BLOCKED_PORTS:
            self._run(['ufw', 'delete', 'deny', 'from', subnet, 'to', 'any',
                       'port', str(port)], input=b'y\n', timeout=10)
        self._blocked_subnets.discard(subnet)
        logger.warning(f"[FIREWALL] Lifted SUBNET ban: {subnet}")
        return True

    def verify_ban(self, ip: str) -> bool:
        """Prove this ban is really in the kernel, and repair it if it is not.

        A ban list records an intention; only the kernel knows whether the
        packets are being dropped. A rule can go missing (a flush, a firewall
        reload, a reboot before the restore ran) or be shadowed (the jump into
        our chain pushed below the SSH ACCEPT), and the symptom is exactly the
        one the threat report describes: an address that is on the ban list and
        still attacking. Returns True if something had to be repaired.
        """
        if not self.available:
            return False
        all_ports = ip in self._all_port_ips
        missing = [rule for rule in self._drop_rules(ip, all_ports)
                   if not self._rule_exists(self.CHAIN, rule)]
        chain_ok = self._chain_is_first()
        if not missing and chain_ok:
            return False
        self.repairs += 1
        logger.warning(
            f"[FIREWALL] Ban on {ip} was NOT in force "
            f"({len(missing)} rule(s) missing"
            f"{'' if chain_ok else ', chain not first'}) - repairing")
        self._chain_ready = False
        self._ensure_chain()
        for rule in missing:
            self._ensure_rule(self.CHAIN, rule)
        # The answering channel is a rule like any other and goes the same way
        # a ban does - flushed by a reload, lost across a reboot. An address
        # that is being answered and silently stops being answered is the old
        # bug wearing a new hat.
        if ip in self._answered:
            self._answered.discard(ip)
            self.open_answer_channel(ip)
        return True

    def reconcile(self, ips: List[str], subnets: List[str]) -> int:
        """Walk every ban and make sure the kernel really carries it.
        Returns the number of bans that had to be repaired."""
        if not self.available:
            return 0
        repaired = 0
        self._chain_ready = False
        self._ensure_chain()
        for ip in ips:
            if self.verify_ban(ip):
                repaired += 1
        for subnet in subnets:
            rules = self._drop_rules(subnet, subnet in self._all_port_ips)
            if any(not self._rule_exists(self.CHAIN, r) for r in rules):
                self.block_subnet(subnet)
                repaired += 1
        if repaired:
            logger.warning(f"[FIREWALL] Reconciliation repaired {repaired} ban(s)")
        return repaired

    def unblock_ip(self, ip: str) -> bool:
        """Remove every firewall block for an IP - the chain's rules, any
        legacy rule an older version left in INPUT, and ufw's."""
        # An address that is being let back in must stop being answered too,
        # or its SSH stays redirected into the tar pit after the ban is gone.
        self.close_answer_channel(ip)
        for chain in (self.CHAIN, 'INPUT'):
            for all_ports in (True, False):
                for rule in self._drop_rules(ip, all_ports):
                    for _ in range(8):
                        if not self._rule_exists(chain, rule):
                            break
                        r = self._run(['iptables', '-D', chain] + rule)
                        if not r or r.returncode != 0:
                            break
        self._run(['ufw', 'delete', 'deny', 'from', ip], input=b'y\n', timeout=10)
        for port in self.BLOCKED_PORTS:
            self._run(['ufw', 'delete', 'deny', 'from', ip, 'to', 'any',
                       'port', str(port)], input=b'y\n', timeout=10)
        self._blocked_ips.discard(ip)
        self._all_port_ips.discard(ip)
        return True

    def sync_from_kernel(self):
        """Populate _blocked_ips/_blocked_subnets from the rules the kernel
        already carries, in our chain and in INPUT (where older versions put
        them). Avoids re-adding rules that already exist after a restart."""
        found = 0
        for chain in (self.CHAIN, 'INPUT'):
            r = self._run(['iptables', '-S', chain], timeout=10, text=True)
            if not r or r.returncode != 0:
                continue
            for line in (r.stdout or '').splitlines():
                if '-j DROP' not in line or '-s ' not in line:
                    continue
                parts = line.split()
                try:
                    src = parts[parts.index('-s') + 1]
                except (ValueError, IndexError):
                    continue
                all_ports = '--dport' not in parts
                if '/32' in src:
                    ip = src.replace('/32', '')
                    if ip not in self._blocked_ips:
                        self._blocked_ips.add(ip)
                        found += 1
                    if all_ports:
                        self._all_port_ips.add(ip)
                elif '/' in src:
                    if src not in self._blocked_subnets:
                        self._blocked_subnets.add(src)
                        found += 1
        if found:
            logger.info(f"[FIREWALL] Synced {found} existing bans from kernel")
        return found

    def restore_bans(self, ips: List[str], subnets: List[str],
                     all_port_ips: Optional[Set[str]] = None):
        """Restore all persistent bans to the firewall on startup.

        An all-ports ban is precisely the case where port 22 is dropped, so
        those are precisely the addresses whose ban is silent on the service
        they were attacking - they get their answering channel back with the
        rest of the ban rather than staying mute until they are re-detected.
        """
        # CRITICAL: protect SSH FIRST, before any DROP rules
        self.protect_ssh()
        # Pre-populate from the kernel so nothing is added twice
        self.sync_from_kernel()
        if all_port_ips:
            self._all_port_ips.update(all_port_ips)
        restored = 0
        answered = 0
        for ip in ips:
            all_ports = ip in self._all_port_ips
            if self.block_ip(ip, all_ports=all_ports):
                restored += 1
            if all_ports and self.open_answer_channel(ip):
                answered += 1
        for subnet in subnets:
            if self.block_subnet(subnet):
                restored += 1
        logger.info(f"[FIREWALL] Restored {restored} bans into the kernel"
                    + (f", answering {answered} of them on SSH" if answered else ""))


class DangerousCerberus(CerberusProtocol):
    """
    Extended Cerberus with auto-firewall, subnet intelligence,
    persistent bans, and attacker profiling.
    """

    def __init__(self, log_dir: str = "logs", db_dir: str = "database"):
        super().__init__(log_dir=log_dir)

        # Persistent ban database
        self.ban_db = PersistentBanDB(
            db_path=os.path.join(db_dir, "cerberus_bans.db")
        )

        # Persistent whitelist file (one IP per line, # for comments)
        self._whitelist_file = os.path.join(db_dir, "cerberus_whitelist.txt")

        # Firewall manager
        self.firewall = FirewallManager()

        # Subnet intelligence
        self._subnet_attack_threshold = 3  # IPs from same /24 before subnet ban
        self._subnet_tracker: Dict[str, Set[str]] = defaultdict(set)  # subnet -> {ips}

        # Dangerous mode settings
        self.dangerous_mode = True  # Enable aggressive responses
        self.auto_firewall = True   # Auto-add to iptables/ufw
        self.auto_subnet_ban = True # Auto-ban subnets on coordinated attacks
        self.persistent_bans = True # Save bans to database
        # Block an SSH brute-forcer on EVERY port. A ban that covers only the
        # Titan-Net ports leaves the attack it was imposed for running - which
        # is what "the IP is on the ban list but the activity persists" means.
        self.block_ssh_attackers = True
        # How often the kernel is re-checked against the ban list.
        self.reconcile_interval = 300

        # IPs whose offence was against the machine's own SSH (read out of the
        # auth log) or the SSH honeypot. Their ban has to cover port 22.
        self._ssh_offenders: Set[str] = set()

        # A ban that is being talked through is a ban that is not in force:
        # prove it in the kernel rather than trusting the list.
        self.on_reenforce_ban = self._reenforce_ban

        # CRITICAL: protect SSH before restoring any bans
        if self.auto_firewall:
            self.firewall.protect_ssh()


        # Load persistent whitelist BEFORE restoring bans
        # (so whitelisted IPs that were accidentally banned get purged)
        self._load_persistent_whitelist()

        # Restore persistent bans on startup
        self._restore_persistent_bans()

        # Seed the repeat-offender history from the ban database, so an
        # attacker cannot get a fresh, soft ban simply by outlasting a restart.
        self._seed_offense_history()

    def _seed_offense_history(self):
        """Carry each IP's ban count across restarts."""
        try:
            for ip, times in self.ban_db.get_ban_counts().items():
                if times > 0 and not self.is_whitelisted(ip):
                    self._offense_history[ip] = max(
                        self._offense_history.get(ip, 0), times)
        except Exception as e:
            logger.error(f"Failed to seed offense history: {e}")

    def _reenforce_ban(self, ip: str, reason: str = ""):
        """Cerberus saw traffic from an IP it has banned. Ask the kernel
        whether the block is really there and repair it if it is not."""
        if not self.auto_firewall:
            return
        try:
            if self.firewall.verify_ban(ip):
                self._log_intrusion(
                    "BAN_NOT_ENFORCED", ip,
                    f"firewall rule was missing and has been restored | {reason}")
                if self.on_admin_notify:
                    try:
                        self.on_admin_notify(
                            f"Cerberus: ban on {ip} was not in force",
                            f"{ip} is banned and was still active. The firewall "
                            f"rule was missing and has been restored.",
                            THREAT_LOCKDOWN,
                        )
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"[DANGEROUS CERBERUS] re-enforce failed for {ip}: {e}")

    def _reconcile_worker(self):
        """Periodically prove every ban is really in the kernel.

        Rules disappear for reasons Cerberus never sees - a firewall reload, a
        `ufw reload`, an iptables flush by another tool, a reboot. Nothing used
        to notice: the ban list still said 'banned' and the attacker carried on.
        """
        while True:
            try:
                time.sleep(self.reconcile_interval)
                if not self.auto_firewall:
                    continue
                ips = sorted(self._banned_ips | self._permanent_banned_ips)
                subnets = self.ban_db.get_all_banned_subnets()
                repaired = self.firewall.reconcile(ips, subnets)
                if repaired:
                    self._log_intrusion(
                        "FIREWALL_RECONCILE", "-",
                        f"{repaired} ban(s) were missing from the kernel and "
                        f"have been restored")
            except Exception as e:
                logger.error(f"[DANGEROUS CERBERUS] reconcile worker: {e}")


    def _load_persistent_whitelist(self):
        """Load whitelist from cerberus_whitelist.txt (one IP per line).
        Also purges whitelisted IPs from ban DB and attacker profiles.

        The two early returns here used to skip the "Initialized" line at the
        end of the function, so a server with no whitelist file - which is
        what production actually had - started its most aggressive subsystem
        without saying so in the log.
        """
        try:
            self._apply_persistent_whitelist()
        except Exception as e:
            logger.error(f"Failed to load persistent whitelist: {e}")

        logger.warning(
            "[DANGEROUS CERBERUS] Initialized - "
            "auto_firewall=ON, subnet_intelligence=ON, persistent_bans=ON, "
            "ssh_protected=ON, "
            f"whitelisted={len(self._whitelisted_ips)}"
        )

    def _apply_persistent_whitelist(self):
        """Read the whitelist file and clear its addresses out of the ban DB."""
        if not os.path.exists(self._whitelist_file):
            # Worth saying out loud: with no file, only loopback is exempt, so
            # nothing stands between the operator's own address and a ban.
            logger.warning(
                f"[DANGEROUS CERBERUS] {self._whitelist_file} does not exist - "
                f"only loopback is exempt from banning. Put one address per "
                f"line in that file (your own address, any monitoring or "
                f"backup host) so this server cannot lock you out of it."
            )
            return
        loaded = []
        with open(self._whitelist_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # Accepts '203.0.113.4' and '203.0.113.0/24' alike.
                if self._register_whitelist_entry(line):
                    loaded.append(line)

        if not loaded:
            return

        # Which BANNED addresses does the whitelist now cover? A CIDR entry
        # has to be expanded against the rows that exist rather than deleted
        # by name, or listing your office range would leave every already
        # banned address inside it banned - a whitelist that does not free
        # what it covers is a whitelist that does not work.
        conn = sqlite3.connect(self.ban_db.db_path)
        c = conn.cursor()
        freed = []
        try:
            known = [r[0] for r in c.execute('SELECT ip FROM banned_ips')]
            freed = [ip for ip in known if self.is_whitelisted(ip)]
            for ip in set(freed) | {e for e in loaded if '/' not in e}:
                c.execute('DELETE FROM banned_ips WHERE ip = ?', (ip,))
                c.execute('DELETE FROM attacker_profiles WHERE ip = ?', (ip,))
            for subnet in [r[0] for r in c.execute('SELECT subnet FROM banned_subnets')]:
                head = subnet.split('/')[0]
                if self.is_whitelisted(head):
                    c.execute('DELETE FROM banned_subnets WHERE subnet = ?', (subnet,))
                    if self.auto_firewall:
                        try:
                            self.firewall.unblock_subnet(subnet)
                        except Exception:
                            pass
            conn.commit()
        finally:
            conn.close()

        # And out of the kernel, in case one was banned before it was listed.
        if self.auto_firewall:
            for ip in set(freed) | {e for e in loaded if '/' not in e}:
                try:
                    self.firewall.unblock_ip(ip)
                    self._banned_ips.discard(ip)
                    self._permanent_banned_ips.discard(ip)
                except Exception:
                    pass

        logger.info(
            f"[DANGEROUS CERBERUS] Loaded {len(loaded)} persistent "
            f"whitelist entries, purged them from ban DB"
        )

    def _restore_persistent_bans(self):
        """Restore bans from database on startup. In-memory sets are populated
        synchronously (fast); firewall sync runs in a background thread so it
        never blocks server startup and WebSocket accept()."""
        try:
            banned_ips = self.ban_db.get_all_banned_ips()
            banned_subnets = self.ban_db.get_all_banned_subnets()

            # In-memory (fast - just set adds)
            for ip in banned_ips:
                self._banned_ips.add(ip)
                self._permanent_banned_ips.add(ip)

            logger.info(
                f"[DANGEROUS CERBERUS] Loaded {len(banned_ips)} IP bans, "
                f"{len(banned_subnets)} subnet bans into memory"
            )

            # Firewall sync in background - each ufw/iptables call is slow
            # (hundreds of ms) and there can be hundreds of bans. Doing this
            # synchronously would block the event loop for minutes and
            # prevent the WebSocket server from accepting connections.
            if self.auto_firewall:
                import threading
                t = threading.Thread(
                    target=self._firewall_restore_worker,
                    args=(banned_ips, banned_subnets),
                    daemon=True,
                    name='CerberusFirewallRestore',
                )
                t.start()
        except Exception as e:
            logger.error(f"Failed to restore persistent bans: {e}")

    def _firewall_restore_worker(self, banned_ips, banned_subnets):
        """Background worker: reconciles firewall rules with the ban DB.
        Runs off the main thread so the event loop can start serving."""
        try:
            # Small delay so the event loop gets to start first
            time.sleep(2)
            all_ports = set(self.ban_db.get_all_port_ips())
            self._ssh_offenders.update(all_ports)
            self.firewall.restore_bans(banned_ips, banned_subnets,
                                       all_port_ips=all_ports)
        except Exception as e:
            logger.error(f"[DANGEROUS CERBERUS] Background firewall restore failed: {e}")
        # From here on, keep proving the bans are really in the kernel.
        try:
            import threading
            threading.Thread(target=self._reconcile_worker, daemon=True,
                             name='CerberusFirewallReconcile').start()
        except Exception as e:
            logger.error(f"[DANGEROUS CERBERUS] reconcile thread failed to start: {e}")

    def _blocks_all_ports(self, ip: str, level: int, reason: str) -> bool:
        """Whether this ban must cover every port rather than Titan-Net's two.

        Two cases: the offence was against the machine's own SSH (blocking
        8000/8001 does nothing to an SSH brute force), and a CERBERUS-level
        permaban, where the point is that this address gets nothing at all.
        """
        if not self.block_ssh_attackers:
            return False
        if level >= THREAT_CERBERUS:
            return True
        if ip in self._ssh_offenders:
            return True
        low = (reason or "").lower()
        return 'ssh' in low or 'honeypot' in low

    # How long a LOCKDOWN ban lasts, by how many times this address has been
    # banned before. Progressive rather than flat: an occasional hit is gone
    # in a day, a returning one is held for a week, and an address that keeps
    # coming back stops being let out at all. Overridable per deployment.
    # A /24 ban is lifted sooner than an individual one however many
    # offences are behind it: the addresses it blocks are mostly not the
    # attacker, and behind a CGNAT range they are somebody's neighbours.
    SUBNET_BAN_TERM = 7 * 24 * 3600

    BAN_TERMS = (
        24 * 3600,        # first offence   - one day
        3 * 24 * 3600,    # second          - three days
        7 * 24 * 3600,    # third           - a week
        30 * 24 * 3600,   # fourth          - a month
    )

    def note_banned_activity(self, ip: str, detail: str = "") -> bool:
        """Override: an answered address talking to us is not a leaking ban.

        The base class reads traffic from a banned address as proof the block
        is not in force - "a firewall rule that was flushed, never added, or
        shadowed by an earlier ACCEPT" - and permabans an address that keeps
        coming through one. But when the answer channel is open there IS
        deliberately an ACCEPT, because that is how the packet reaches the tar
        pit for Blackwall to speak into. So the one thing the check treats as
        proof of failure is, for these addresses, the design working. Left
        alone it re-verified a healthy ban over and over and then permabanned
        the address for the retries the channel exists to receive.
        """
        if self._came_through_answer_channel(ip):
            return False
        return super().note_banned_activity(ip, detail)

    def _came_through_answer_channel(self, ip: str) -> bool:
        """True if this address's port 22 is currently being redirected into
        the tar pit, so a 'honeypot' hit from it is our own doing.

        Asked of the firewall rather than remembered here, because the channel
        is opened, restored and removed by the firewall and a second copy of
        that state would drift out of step with the kernel.
        """
        if not self.auto_firewall:
            return False
        try:
            return ip in set(self.firewall.answered_ips())
        except Exception as e:
            logger.error(f"[DANGEROUS CERBERUS] answer-channel check failed: {e}")
            # Fail towards NOT manufacturing evidence: if we cannot tell
            # whether we redirected them, we must not permaban them for it.
            return True

    def _ban_expiry(self, ip: str) -> float:
        """When a LOCKDOWN ban on ``ip`` should lapse. 0 = never."""
        offences = self._offense_history.get(ip, 0)
        if offences >= len(self.BAN_TERMS):
            return 0.0          # persistent attacker - the term stops running out
        return time.time() + self.BAN_TERMS[offences]

    def release_expired_bans(self) -> int:
        """Lift every ban whose term has run out - database, memory, kernel.

        Called hourly by the server. Without it the expiry columns would be
        bookkeeping nobody acts on, which is what the ``permanent`` flag was
        for years.
        """
        try:
            freed = self.ban_db.purge_expired()
        except Exception as e:
            logger.error(f"[DANGEROUS CERBERUS] ban expiry query failed: {e}")
            return 0
        released = 0
        try:
            for subnet in self.ban_db.purge_expired_subnets():
                if self.auto_firewall:
                    try:
                        self.firewall.unblock_subnet(subnet)
                    except Exception as e:
                        logger.error(
                            f"[DANGEROUS CERBERUS] could not lift {subnet}: {e}")
                        continue
                self._subnet_tracker.pop(subnet, None)
                released += 1
                self._log_intrusion(
                    "SUBNET_BAN_EXPIRED", subnet,
                    "the subnet ban's term ran out - the range is free again")
        except Exception as e:
            logger.error(f"[DANGEROUS CERBERUS] subnet expiry failed: {e}")
        for ip in freed:
            # A permanent ban imposed since the row was read wins; ask again.
            try:
                if self.ban_db.is_banned(ip):
                    continue
            except Exception:
                pass
            self._banned_ips.discard(ip)
            self._ip_threat.pop(ip, None)
            if self.auto_firewall:
                try:
                    self.firewall.unblock_ip(ip)
                except Exception as e:
                    logger.error(
                        f"[DANGEROUS CERBERUS] could not lift the rule for {ip}: {e}")
                    continue
            released += 1
            self._log_intrusion(
                "BAN_EXPIRED", ip,
                f"ban term ran out after {self._offense_history.get(ip, 0)} "
                f"recorded offence(s) - the address is free again")
        return released

    def _set_ip_threat(self, ip: str, level: int, reason: str):
        """Override: add firewall blocking + persistent bans + subnet analysis"""
        # A whitelisted address is never blocked, never persisted and never
        # profiled - the base class tracks it, the kernel must not.
        if self.is_whitelisted(ip):
            super()._set_ip_threat(ip, level, reason)
            return

        # Call parent implementation
        super()._set_ip_threat(ip, level, reason)

        # --- Dangerous Mode Extensions ---

        if level >= THREAT_LOCKDOWN:
            all_ports = self._blocks_all_ports(ip, level, reason)

            # Auto-firewall block
            if self.auto_firewall:
                self.firewall.block_ip(ip, all_ports=all_ports)

            # Persist to database, with a TERM. A ban that never runs out
            # makes every false positive permanent, and the ones this system
            # gets wrong are exactly the ones nobody is watching for - an
            # address that scanned once from a range somebody else is now
            # renting, or a shared/CGNAT address behind which one infected
            # machine sits among many innocent subscribers. A repeat offender
            # earns a longer term each time and eventually a permanent one, so
            # nothing is lost against an attacker who really is persistent.
            if self.persistent_bans:
                permanent = (level >= THREAT_CERBERUS)
                self.ban_db.add_ban(
                    ip, reason, level,
                    permanent=permanent,
                    all_ports=all_ports,
                    expires_at=0.0 if permanent else self._ban_expiry(ip),
                )

            # Subnet intelligence
            if self.auto_subnet_ban:
                self._analyze_subnet(ip, reason)

        # Update attacker profile
        self.ban_db.update_profile(ip, attack_type=reason)


    def _analyze_subnet(self, ip: str, reason: str):
        """Check if this IP's subnet has too many attackers -> ban whole subnet"""
        try:
            subnet = str(ipaddress.ip_network(f"{ip}/24", strict=False))
            self._subnet_tracker[subnet].add(ip)

            # Also check database for historical attacks
            db_count = self.ban_db.get_subnet_attack_count(ip)
            memory_count = len(self._subnet_tracker[subnet])
            total_unique = max(db_count, memory_count)

            if total_unique >= self._subnet_attack_threshold:
                # This subnet is a coordinated attack source
                trigger_ips = list(self._subnet_tracker[subnet])
                db_ips = self.ban_db.get_subnet_attacker_ips(ip)
                all_ips = list(set(trigger_ips + db_ips))

                logger.critical(
                    f"[DANGEROUS CERBERUS] SUBNET BAN: {subnet} - "
                    f"{total_unique} unique attacker IPs detected: "
                    f"{', '.join(all_ips[:10])}"
                )

                # Ban the entire subnet
                if self.auto_firewall:
                    self.firewall.block_subnet(subnet)

                if self.persistent_bans:
                    # A term, for the same reason an IP ban has one - more so:
                    # this blocks 254 addresses on the evidence of a handful.
                    self.ban_db.add_subnet_ban(
                        subnet, reason, all_ips,
                        expires_at=time.time() + self.SUBNET_BAN_TERM)

                self._log_intrusion(
                    "SUBNET_BAN", ip,
                    f"Banned subnet {subnet} - {total_unique} attackers: "
                    f"{', '.join(all_ips[:10])}"
                )

                # Notify admins
                if self.on_admin_notify:
                    try:
                        self.on_admin_notify(
                            f"Cerberus: Subnet {subnet} BANNED",
                            f"Coordinated attack from {total_unique} IPs in "
                            f"{subnet}. Entire subnet blocked.",
                            THREAT_ANNIHILATE
                        )
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Subnet analysis error: {e}")

    def is_ip_banned(self, ip: str) -> bool:
        """Override: check persistent database + in-memory + subnet bans"""
        if self.is_whitelisted(ip):
            return False
        # In-memory check (fast path)
        if ip in self._banned_ips or ip in self._permanent_banned_ips:
            return True
        # Persistent database check (catches bans from previous sessions)
        if self.persistent_bans and self.ban_db.is_banned(ip):
            # Re-add to memory for faster future checks
            self._banned_ips.add(ip)
            return True
        return False

    def honeypot_triggered(self, ip: str, username: str = "unknown",
                           password: str = "***"):
        """Override: enhanced profiling on honeypot triggers"""
        # CRITICAL: skip whitelisted IPs - don't profile or log them
        if self.is_whitelisted(ip):
            return

        # A connection that arrived through the ANSWER CHANNEL is not evidence.
        #
        # The channel is a `nat PREROUTING REDIRECT --to-ports 2223` we put in
        # front of a banned address's port 22 so Blackwall has somewhere to
        # speak to them. The attacker did not choose to touch a honeypot port -
        # they knocked on SSH exactly as before, and we moved the door. Feeding
        # that back in as a fresh honeypot hit closed a loop that manufactured
        # its own evidence: ban -> redirect -> bot retries twice (seconds, for
        # a bot) -> "2nd login attempt, confirmed attacker" -> PERMANENT
        # all-ports ban plus countermeasures. Measured on production: 217 of
        # the 224 permanent bans read exactly that, and the permanent count
        # rose from 194 to 224 in the two hours after ban expiry was
        # introduced - the loop was quietly undoing it as fast as it was
        # applied.
        #
        # Traffic from an address we have banned is still worth noticing, so
        # it goes where that belongs: note_banned_activity, which re-verifies
        # the block is really in the kernel and escalates on a counted
        # threshold instead of on two retries.
        if self._came_through_answer_channel(ip):
            self._log_intrusion(
                "ANSWER_CHANNEL", ip,
                "SSH retry delivered into the tar pit by our own redirect - "
                "recorded, not counted as an attack")
            self.ban_db.update_profile(ip, attack_type="answer_channel_retry")
            return

        # Whoever knocks on a fake SSH is attacking SSH: their ban covers
        # every port, port 22 above all.
        self._ssh_offenders.add(ip)

        # Profile the attacker
        self.ban_db.update_profile(
            ip,
            attack_type="honeypot_ssh",
            username=username,
            user_agent=username  # SSH client ID comes as username in honeypot
        )
        # Call parent
        super().honeypot_triggered(ip, username, password)

    def record_failed_login(self, ip: str, username: str = "unknown",
                            source: str = "app") -> bool:
        """Override: profile attacker on failed Titan-Net logins"""
        # CRITICAL: skip whitelisted IPs - don't profile or track them
        if self.is_whitelisted(ip):
            return False
        if source == "ssh":
            # The attack is on the machine's own SSH; a ban limited to the
            # Titan-Net ports would not touch it.
            self._ssh_offenders.add(ip)
        self.ban_db.update_profile(
            ip,
            attack_type=f"brute_force_{source}" if source != "app" else "brute_force",
            username=username
        )
        return super().record_failed_login(ip, username, source=source)


    def unban_ip(self, ip: str):
        """Override: also remove from firewall + database"""
        super().unban_ip(ip)
        if self.auto_firewall:
            self.firewall.unblock_ip(ip)
        if self.persistent_bans:
            self.ban_db.unban_ip(ip)

    def get_status(self) -> Dict:
        """Override: include dangerous mode stats"""
        status = super().get_status()
        status["dangerous_mode"] = {
            "enabled": self.dangerous_mode,
            "auto_firewall": self.auto_firewall,
            "auto_subnet_ban": self.auto_subnet_ban,
            "persistent_bans": self.persistent_bans,
            "subnet_threshold": self._subnet_attack_threshold,
            "tracked_subnets": {
                subnet: list(ips)
                for subnet, ips in self._subnet_tracker.items()
            },
            "database_stats": self.ban_db.get_stats(),
        }
        return status

    def get_attacker_intel(self, ip: str) -> Optional[Dict]:
        """Get full intelligence report on an attacker"""
        conn = sqlite3.connect(self.ban_db.db_path)
        c = conn.cursor()
        try:
            c.execute('SELECT * FROM attacker_profiles WHERE ip = ?', (ip,))
            row = c.fetchone()
            if not row:
                return None
            return {
                "ip": row[0],
                "first_seen": row[1],
                "last_seen": row[2],
                "total_attempts": row[3],
                "attack_types": json.loads(row[4] or '[]'),
                "user_agents": json.loads(row[5] or '[]'),
                "usernames_tried": json.loads(row[6] or '[]'),
                "threat_score": row[7],
                "subnet": row[8],
            }
        finally:
            conn.close()

    def get_all_attacker_intel(self, limit: int = 50) -> List[Dict]:
        """Get intelligence on all tracked attackers, sorted by threat score"""
        conn = sqlite3.connect(self.ban_db.db_path)
        c = conn.cursor()
        try:
            c.execute(
                'SELECT * FROM attacker_profiles ORDER BY threat_score DESC LIMIT ?',
                (limit,)
            )
            results = []
            for row in c.fetchall():
                results.append({
                    "ip": row[0],
                    "first_seen": row[1],
                    "last_seen": row[2],
                    "total_attempts": row[3],
                    "attack_types": json.loads(row[4] or '[]'),
                    "threat_score": row[7],
                    "subnet": row[8],
                })
            return results
        finally:
            conn.close()
