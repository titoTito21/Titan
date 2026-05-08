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
        conn.commit()
        conn.close()

    def add_ban(self, ip: str, reason: str, threat_level: int,
                permanent: bool = True, fingerprint: str = "") -> bool:
        """Add IP to persistent ban database. Returns True if new ban."""
        subnet = str(ipaddress.ip_network(f"{ip}/24", strict=False))
        now = datetime.now().isoformat()
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('''INSERT INTO banned_ips
                (ip, subnet, reason, threat_level, banned_at, permanent,
                 attacker_fingerprint, total_attempts, last_attempt)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(ip) DO UPDATE SET
                    reason = excluded.reason,
                    threat_level = MAX(threat_level, excluded.threat_level),
                    permanent = MAX(permanent, excluded.permanent),
                    total_attempts = total_attempts + 1,
                    last_attempt = excluded.last_attempt
            ''', (ip, subnet, reason, threat_level, now, int(permanent),
                  fingerprint, now))
            conn.commit()
            return c.rowcount > 0
        finally:
            conn.close()

    def add_subnet_ban(self, subnet: str, reason: str, trigger_ips: List[str]) -> bool:
        """Ban an entire subnet"""
        now = datetime.now().isoformat()
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('''INSERT INTO banned_subnets
                (subnet, reason, ip_count, banned_at, trigger_ips)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(subnet) DO UPDATE SET
                    reason = excluded.reason,
                    ip_count = excluded.ip_count
            ''', (subnet, reason, len(trigger_ips), now,
                  json.dumps(trigger_ips)))
            conn.commit()
            return True
        finally:
            conn.close()

    def is_banned(self, ip: str) -> bool:
        """Check if IP or its subnet is banned"""
        subnet = str(ipaddress.ip_network(f"{ip}/24", strict=False))
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('SELECT 1 FROM banned_ips WHERE ip = ?', (ip,))
            if c.fetchone():
                return True
            c.execute('SELECT 1 FROM banned_subnets WHERE subnet = ?', (subnet,))
            return c.fetchone() is not None
        finally:
            conn.close()

    def get_all_banned_ips(self) -> List[str]:
        """Get all banned IPs"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('SELECT ip FROM banned_ips')
            return [row[0] for row in c.fetchall()]
        finally:
            conn.close()

    def get_all_banned_subnets(self) -> List[str]:
        """Get all banned subnets"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('SELECT subnet FROM banned_subnets')
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

    SAFETY: Only blocks Titan-Net ports (8000, 8001). SSH (port 22) is
    NEVER blocked — a permanent ACCEPT rule is inserted at position 1
    on startup to guarantee remote access even if other rules go wrong.
    """

    # Ports that Cerberus is allowed to block (Titan-Net only)
    BLOCKED_PORTS = [8000, 8001]

    # Ports that must NEVER be blocked (critical for server access)
    PROTECTED_PORTS = [22]

    def __init__(self):
        self._blocked_ips: Set[str] = set()
        self._blocked_subnets: Set[str] = set()
        self._ssh_protected = False

    def protect_ssh(self):
        """Insert permanent iptables ACCEPT rule for SSH before any DROP rules.
        Called once on startup to guarantee SSH access cannot be blocked."""
        if self._ssh_protected:
            return
        try:
            for port in self.PROTECTED_PORTS:
                subprocess.run(
                    ['iptables', '-I', 'INPUT', '1', '-p', 'tcp',
                     '--dport', str(port), '-j', 'ACCEPT'],
                    capture_output=True, timeout=5
                )
            self._ssh_protected = True
            logger.info("[FIREWALL] SSH port protected - ACCEPT rule at position 1")
        except FileNotFoundError:
            logger.warning("[FIREWALL] iptables not found, firewall features disabled.")
            self._ssh_protected = True
        except Exception as e:
            logger.error(f"[FIREWALL] Failed to protect SSH: {e}")

    def block_ip(self, ip: str) -> bool:
        """Block IP on Titan-Net ports only (never blocks SSH)"""
        if ip in self._blocked_ips:
            return True
        # Always ensure SSH is protected before adding any DROP rules
        self.protect_ssh()
        try:
            for port in self.BLOCKED_PORTS:
                subprocess.run(
                    ['iptables', '-A', 'INPUT', '-s', ip, '-p', 'tcp',
                     '--dport', str(port), '-j', 'DROP'],
                    capture_output=True, timeout=5
                )
            # ufw: block only Titan-Net ports
            for port in self.BLOCKED_PORTS:
                subprocess.run(
                    ['ufw', 'deny', 'from', ip, 'to', 'any', 'port', str(port)],
                    capture_output=True, timeout=5
                )
            self._blocked_ips.add(ip)
            logger.info(f"[FIREWALL] Blocked IP on ports {self.BLOCKED_PORTS}: {ip}")
            return True
        except Exception as e:
            logger.error(f"[FIREWALL] Failed to block {ip}: {e}")
            return False

    def block_subnet(self, subnet: str) -> bool:
        """Block entire /24 subnet on Titan-Net ports only (never blocks SSH)"""
        if subnet in self._blocked_subnets:
            return True
        # Always ensure SSH is protected before adding any DROP rules
        self.protect_ssh()
        try:
            for port in self.BLOCKED_PORTS:
                subprocess.run(
                    ['iptables', '-A', 'INPUT', '-s', subnet, '-p', 'tcp',
                     '--dport', str(port), '-j', 'DROP'],
                    capture_output=True, timeout=5
                )
            for port in self.BLOCKED_PORTS:
                subprocess.run(
                    ['ufw', 'deny', 'from', subnet, 'to', 'any', 'port', str(port)],
                    capture_output=True, timeout=5
                )
            self._blocked_subnets.add(subnet)
            logger.warning(f"[FIREWALL] Blocked SUBNET on ports {self.BLOCKED_PORTS}: {subnet}")
            return True
        except Exception as e:
            logger.error(f"[FIREWALL] Failed to block subnet {subnet}: {e}")
            return False

    def unblock_ip(self, ip: str) -> bool:
        """Remove firewall block for IP"""
        try:
            for port in self.BLOCKED_PORTS:
                subprocess.run(
                    ['iptables', '-D', 'INPUT', '-s', ip, '-p', 'tcp',
                     '--dport', str(port), '-j', 'DROP'],
                    capture_output=True, timeout=5
                )
                subprocess.run(
                    ['ufw', 'delete', 'deny', 'from', ip, 'to', 'any',
                     'port', str(port)],
                    input=b'y\n', capture_output=True, timeout=5
                )
            self._blocked_ips.discard(ip)
            return True
        except Exception as e:
            logger.error(f"[FIREWALL] Failed to unblock {ip}: {e}")
            return False

    def sync_from_kernel(self):
        """Populate _blocked_ips/_blocked_subnets from current iptables rules.
        Avoids re-adding rules that already exist after a restart."""
        try:
            result = subprocess.run(
                ['iptables', '-S', 'INPUT'],
                capture_output=True, timeout=10, text=True
            )
            if result.returncode != 0:
                return 0
            found = 0
            for line in result.stdout.splitlines():
                # -A INPUT -s 1.2.3.4/32 -p tcp -m tcp --dport 8001 -j DROP
                if '-j DROP' not in line or '-s ' not in line:
                    continue
                parts = line.split()
                try:
                    src = parts[parts.index('-s') + 1]
                except (ValueError, IndexError):
                    continue
                if '/32' in src:
                    ip = src.replace('/32', '')
                    if ip not in self._blocked_ips:
                        self._blocked_ips.add(ip)
                        found += 1
                elif '/' in src:
                    if src not in self._blocked_subnets:
                        self._blocked_subnets.add(src)
                        found += 1
            logger.info(f"[FIREWALL] Synced {found} existing bans from kernel")
            return found
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"[FIREWALL] Failed to sync from kernel: {e}")
            return 0

    def restore_bans(self, ips: List[str], subnets: List[str]):
        """Restore all persistent bans to firewall on startup.
        Only adds rules that don't already exist in the kernel."""
        # CRITICAL: protect SSH FIRST, before any DROP rules
        self.protect_ssh()
        # Pre-populate from kernel to avoid duplicate rules
        self.sync_from_kernel()
        restored = 0
        skipped = 0
        for ip in ips:
            if ip in self._blocked_ips:
                skipped += 1
                continue
            if self.block_ip(ip):
                restored += 1
        for subnet in subnets:
            if subnet in self._blocked_subnets:
                skipped += 1
                continue
            if self.block_subnet(subnet):
                restored += 1
        logger.info(
            f"[FIREWALL] Restored {restored} bans, skipped {skipped} already in kernel"
        )


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

        # CRITICAL: protect SSH before restoring any bans
        if self.auto_firewall:
            self.firewall.protect_ssh()

        # Load persistent whitelist BEFORE restoring bans
        # (so whitelisted IPs that were accidentally banned get purged)
        self._load_persistent_whitelist()

        # Restore persistent bans on startup
        self._restore_persistent_bans()

    def _load_persistent_whitelist(self):
        """Load whitelist from cerberus_whitelist.txt (one IP per line).
        Also purges whitelisted IPs from ban DB and attacker profiles."""
        try:
            if not os.path.exists(self._whitelist_file):
                return
            loaded = []
            with open(self._whitelist_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    self._whitelisted_ips.add(line)
                    loaded.append(line)

            if not loaded:
                return

            # Purge whitelisted IPs from ban DB and profiles
            conn = sqlite3.connect(self.ban_db.db_path)
            c = conn.cursor()
            try:
                for ip in loaded:
                    c.execute('DELETE FROM banned_ips WHERE ip = ?', (ip,))
                    c.execute('DELETE FROM attacker_profiles WHERE ip = ?', (ip,))
                conn.commit()
            finally:
                conn.close()

            logger.info(
                f"[DANGEROUS CERBERUS] Loaded {len(loaded)} persistent "
                f"whitelist entries, purged them from ban DB"
            )
        except Exception as e:
            logger.error(f"Failed to load persistent whitelist: {e}")

        logger.warning(
            "[DANGEROUS CERBERUS] Initialized - "
            "auto_firewall=ON, subnet_intelligence=ON, persistent_bans=ON, "
            "ssh_protected=ON"
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
            self.firewall.restore_bans(banned_ips, banned_subnets)
        except Exception as e:
            logger.error(f"[DANGEROUS CERBERUS] Background firewall restore failed: {e}")

    def _set_ip_threat(self, ip: str, level: int, reason: str):
        """Override: add firewall blocking + persistent bans + subnet analysis"""
        # Call parent implementation
        super()._set_ip_threat(ip, level, reason)

        # --- Dangerous Mode Extensions ---

        if level >= THREAT_LOCKDOWN:
            # Auto-firewall block
            if self.auto_firewall:
                self.firewall.block_ip(ip)

            # Persist to database
            if self.persistent_bans:
                self.ban_db.add_ban(
                    ip, reason, level,
                    permanent=(level >= THREAT_CERBERUS)
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
                    self.ban_db.add_subnet_ban(subnet, reason, all_ips)

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
        # Profile the attacker
        self.ban_db.update_profile(
            ip,
            attack_type="honeypot_ssh",
            username=username,
            user_agent=username  # SSH client ID comes as username in honeypot
        )
        # Call parent
        super().honeypot_triggered(ip, username, password)

    def record_failed_login(self, ip: str, username: str = "unknown") -> bool:
        """Override: profile attacker on failed Titan-Net logins"""
        # CRITICAL: skip whitelisted IPs - don't profile or track them
        if self.is_whitelisted(ip):
            return False
        self.ban_db.update_profile(
            ip,
            attack_type="brute_force",
            username=username
        )
        return super().record_failed_login(ip, username)

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
