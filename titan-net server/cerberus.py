"""
Cerberus Protocol - Titan-Net Intrusion Detection & Lockdown System

Threat levels (PER-IP, not global):
  0 - NORMAL:   No threats detected
  1 - ALERT:    Suspicious activity - log only, no action on legitimate users
  2 - LOCKDOWN: Attacker IP banned - only THAT IP is blocked, others unaffected
  3 - CERBERUS: Maximum threat - IP permabanned + infrastructure countermeasures against attacker's server

Global lockdown only activates for:
  - Distributed DDoS (many IPs attacking simultaneously)
  - Manual admin activation

Detection triggers:
  - Brute force login attempts (multiple failed logins from same IP)
  - DDoS detection (connection flood from single/multiple IPs)
  - SSH honeypot triggered (someone connected to fake SSH)
  - Manual admin activation
"""

import logging
import logging.handlers
import os
import time
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Set, Callable, Any

logger = logging.getLogger('CerberusProtocol')

# Threat levels
THREAT_NORMAL = 0
THREAT_ALERT = 1
THREAT_LOCKDOWN = 2
THREAT_CERBERUS = 3

THREAT_NAMES = {
    THREAT_NORMAL: "NORMAL",
    THREAT_ALERT: "ALERT",
    THREAT_LOCKDOWN: "LOCKDOWN",
    THREAT_CERBERUS: "CERBERUS",
}


class CerberusProtocol:
    """Core intrusion detection and lockdown engine"""

    def __init__(self, log_dir: str = "logs"):
        # Global threat level (only elevated for distributed attacks / manual)
        self.threat_level = THREAT_NORMAL

        # Logging
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self._intrusion_log = os.path.join(log_dir, "cerberus_intrusions.log")
        self._setup_intrusion_logger()

        # --- IP Whitelist (never blocked, never triggers alerts) ---
        self._whitelisted_ips: Set[str] = {
            "127.0.0.1",        # localhost
            "::1",              # localhost IPv6
        }

        # --- Per-IP threat tracking ---
        # {ip: {"level": int, "last_activity": float, "reason": str}}
        self._ip_threat: Dict[str, Dict] = {}

        # --- Brute Force Detection ---
        # {ip: [timestamp, timestamp, ...]} - failed login timestamps
        # Only COUNTS as an intrusion when the LOCKDOWN threshold is actually reached.
        self._failed_logins: Dict[str, List[float]] = defaultdict(list)
        self.max_failed_logins = 20         # Internal ALERT tracking (no log, no notify)
        self.failed_login_window = 300      # 5 minutes window
        self.lockdown_failed_logins = 40    # Confirmed brute force -> ban IP + log
        self.cerberus_failed_logins = 80    # Massive brute force -> permaban + countermeasures

        # --- DDoS Detection ---
        # {ip: [timestamp, timestamp, ...]} - connection timestamps
        self._connections: Dict[str, List[float]] = defaultdict(list)
        self.max_connections_per_ip = 120   # Internal ALERT tracking only
        self.connection_window = 10         # Seconds window for counting
        self.ddos_connections_per_ip = 250  # Confirmed flood -> ban IP
        self.ddos_total_connections = 1000  # Distributed DDoS threshold
        self.cerberus_connections = 500     # Per-IP CERBERUS threshold
        self._total_connections_window: List[float] = []

        # --- WebSocket Message Flood Detection ---
        # {ip: [timestamp, ...]} - message timestamps
        self._message_rates: Dict[str, List[float]] = defaultdict(list)
        self.max_messages_per_second = 250  # Internal ALERT tracking only
        self.message_window = 5             # Seconds window

        # --- Banned IPs (auto-banned by Cerberus) ---
        self._banned_ips: Set[str] = set()
        self._permanent_banned_ips: Set[str] = set()

        # --- Tracked attackers (for countermeasures) ---
        # {ip: {"threat_score": int, "first_seen": float, "type": str}}
        self._tracked_attackers: Dict[str, Dict] = {}

        # --- Global lockdown state (only for distributed DDoS / manual) ---
        self._lockdown_active = False
        self._lockdown_start: Optional[float] = None
        self._lockdown_reason: str = ""
        self._lockdown_auto_release_seconds = 300  # 5 min auto-release

        # --- Auto-cooldown ---
        self._alert_cooldown_seconds = 120  # ALERT auto-clears after 2 min of no activity
        self._last_incident_time: float = 0

        # --- Callbacks (set by server.py) ---
        self.on_threat_level_change: Optional[Callable] = None
        self.on_admin_notify: Optional[Callable] = None
        self.on_shutdown_attacker: Optional[Callable] = None
        self.on_ban_ip: Optional[Callable] = None
        self.on_disconnect_ip: Optional[Callable] = None

        # --- Stats ---
        self._total_intrusions_blocked = 0
        self._total_ddos_blocked = 0

        logger.info("Cerberus Protocol initialized - threat level: NORMAL")

    def _setup_intrusion_logger(self):
        """Setup dedicated intrusion log file with auto-rotation every 2 days.

        Old rotated logs are pruned after 1 backup so Cerberus never keeps more
        than ~4 days of history.
        """
        self._intrusion_logger = logging.getLogger('CerberusIntrusions')
        self._intrusion_logger.setLevel(logging.WARNING)
        # Drop any previously attached handlers (e.g. after reload) so we don't
        # end up double-logging to an old path.
        for h in list(self._intrusion_logger.handlers):
            self._intrusion_logger.removeHandler(h)
        handler = logging.handlers.TimedRotatingFileHandler(
            self._intrusion_log,
            when='D',
            interval=2,
            backupCount=1,
            encoding='utf-8',
            utc=False,
        )
        handler.setFormatter(logging.Formatter(
            '%(asctime)s | %(levelname)s | %(message)s'
        ))
        self._intrusion_logger.addHandler(handler)
        self._intrusion_logger.propagate = False

    def _log_intrusion(self, level: str, ip: str, details: str):
        """Log intrusion event (only for confirmed threats, never for ALERT-level noise)."""
        self._intrusion_logger.warning(
            f"[{level}] IP={ip} | {details}"
        )

    def clear_logs(self) -> int:
        """Truncate the intrusion log and drop all rotated backups.

        Returns the number of files cleared. Called manually by a moderator
        via ``cerberus_clear_logs`` and on a 2-day schedule from server.py.
        """
        cleared = 0
        try:
            # Truncate the live log
            if os.path.exists(self._intrusion_log):
                open(self._intrusion_log, 'w', encoding='utf-8').close()
                cleared += 1
            # Remove any rotated backups (cerberus_intrusions.log.2026-04-12 etc.)
            log_dir = os.path.dirname(self._intrusion_log) or '.'
            base = os.path.basename(self._intrusion_log)
            for name in os.listdir(log_dir):
                if name.startswith(base + '.'):
                    try:
                        os.remove(os.path.join(log_dir, name))
                        cleared += 1
                    except OSError:
                        pass
            logger.info(f"CERBERUS: intrusion log cleared ({cleared} files)")
        except Exception as e:
            logger.error(f"CERBERUS: failed to clear intrusion log: {e}")
        return cleared

    # ================================================================
    # WHITELIST
    # ================================================================

    def add_whitelisted_ip(self, ip: str):
        """Add IP to whitelist - will never be blocked"""
        self._whitelisted_ips.add(ip)
        # Remove from bans if was accidentally banned
        self._banned_ips.discard(ip)
        self._permanent_banned_ips.discard(ip)
        logger.info(f"[CERBERUS] IP whitelisted: {ip}")

    def remove_whitelisted_ip(self, ip: str):
        """Remove IP from whitelist"""
        self._whitelisted_ips.discard(ip)

    def is_whitelisted(self, ip: str) -> bool:
        """Check if IP is whitelisted"""
        return ip in self._whitelisted_ips

    # ================================================================
    # PER-IP THREAT MANAGEMENT (not global)
    # ================================================================

    def _set_ip_threat(self, ip: str, level: int, reason: str):
        """Set threat level for a SPECIFIC IP only"""
        old = self._ip_threat.get(ip, {}).get("level", THREAT_NORMAL)
        if level <= old:
            return

        self._ip_threat[ip] = {
            "level": level,
            "last_activity": time.time(),
            "reason": reason
        }
        self._last_incident_time = time.time()

        level_name = THREAT_NAMES.get(level, "UNKNOWN")
        logger.warning(
            f"CERBERUS: IP {ip} threat -> {level_name} | Reason: {reason}"
        )
        # Only persist confirmed intrusions - ALERT is internal tracking only.
        if level >= THREAT_LOCKDOWN:
            self._log_intrusion(level_name, ip, reason)

        # Notify moderators ONLY for confirmed intrusions (LOCKDOWN+).
        # Regular users never get Cerberus alerts.
        if self.on_admin_notify and level >= THREAT_LOCKDOWN:
            try:
                self.on_admin_notify(
                    f"Cerberus: {level_name} - {ip}",
                    f"IP {ip} escalated to {level_name}. Reason: {reason}",
                    level
                )
            except Exception as e:
                logger.error(f"Admin notify callback error: {e}")

        # LOCKDOWN = ban this specific IP
        if level >= THREAT_LOCKDOWN:
            self._banned_ips.add(ip)
            self._total_intrusions_blocked += 1
            if self.on_disconnect_ip:
                try:
                    self.on_disconnect_ip(ip)
                except Exception as e:
                    logger.error(f"Disconnect IP callback error: {e}")

        # CERBERUS = permaban + infrastructure countermeasures
        if level >= THREAT_CERBERUS:
            self._permanent_banned_ips.add(ip)
            logger.critical(
                f"CERBERUS ENGAGED on {ip}: permaban + countermeasures | Reason: {reason}"
            )
            if self.on_shutdown_attacker:
                try:
                    self.on_shutdown_attacker(ip, reason)
                except Exception as e:
                    logger.error(f"Shutdown attacker callback error: {e}")
            if self.on_ban_ip:
                try:
                    self.on_ban_ip(ip, reason, permanent=True)
                except Exception as e:
                    logger.error(f"Ban IP callback error: {e}")

        # Fire threat level change callback
        if self.on_threat_level_change:
            try:
                self.on_threat_level_change(level, reason, ip)
            except Exception as e:
                logger.error(f"Threat level callback error: {e}")

    def _set_global_threat(self, level: int, reason: str, attacker_ip: str = "unknown"):
        """Set GLOBAL threat level (only for distributed attacks / manual)"""
        old_level = self.threat_level
        if level <= old_level:
            return

        self.threat_level = level
        self._last_incident_time = time.time()
        level_name = THREAT_NAMES.get(level, "UNKNOWN")

        logger.warning(
            f"CERBERUS GLOBAL: {THREAT_NAMES.get(old_level, '?')} -> {level_name} | "
            f"Reason: {reason}"
        )
        self._log_intrusion(f"GLOBAL_{level_name}", attacker_ip, reason)

        if level >= THREAT_LOCKDOWN:
            self._lockdown_active = True
            self._lockdown_start = time.time()
            self._lockdown_reason = reason
            logger.critical(f"GLOBAL LOCKDOWN ACTIVATED: {reason}")

        if self.on_admin_notify:
            try:
                self.on_admin_notify(
                    f"Cerberus GLOBAL: {level_name}",
                    f"Global threat {level_name}. Reason: {reason}",
                    level
                )
            except Exception as e:
                logger.error(f"Admin notify callback error: {e}")

        if self.on_threat_level_change:
            try:
                self.on_threat_level_change(level, reason, attacker_ip)
            except Exception as e:
                logger.error(f"Threat level callback error: {e}")

    # ================================================================
    # LOCKDOWN & COOLDOWN
    # ================================================================

    def is_lockdown_active(self) -> bool:
        """Check if GLOBAL lockdown is active (only from distributed DDoS or manual)"""
        if not self._lockdown_active:
            return False

        # Auto-release after timeout
        if self._lockdown_start:
            elapsed = time.time() - self._lockdown_start
            if elapsed > self._lockdown_auto_release_seconds:
                self.deactivate_lockdown("Auto-release after timeout")
                return False

        return True

    def is_ip_banned(self, ip: str) -> bool:
        """Check if IP is banned by Cerberus"""
        if self.is_whitelisted(ip):
            return False
        return ip in self._banned_ips or ip in self._permanent_banned_ips

    def _check_cooldown(self):
        """Auto-reset global threat level after cooldown period with no activity"""
        if self.threat_level == THREAT_NORMAL:
            return
        if self._last_incident_time == 0:
            return
        elapsed = time.time() - self._last_incident_time
        if elapsed > self._alert_cooldown_seconds and self.threat_level <= THREAT_ALERT:
            self.threat_level = THREAT_NORMAL
            logger.info("CERBERUS: Global threat auto-reset to NORMAL (cooldown)")

    # ================================================================
    # BRUTE FORCE DETECTION
    # ================================================================

    def record_failed_login(self, ip: str, username: str = "unknown") -> bool:
        """
        Record a failed login attempt.
        Returns True if IP should be blocked NOW.
        Only affects THIS IP - other users are NOT impacted.
        """
        if self.is_whitelisted(ip):
            return False

        now = time.time()
        self._check_cooldown()

        # Clean old entries
        cutoff = now - self.failed_login_window
        self._failed_logins[ip] = [t for t in self._failed_logins[ip] if t > cutoff]
        self._failed_logins[ip].append(now)
        count = len(self._failed_logins[ip])

        # Track attacker
        if ip not in self._tracked_attackers:
            self._tracked_attackers[ip] = {
                "threat_score": 0,
                "first_seen": now,
                "type": "brute_force"
            }
        self._tracked_attackers[ip]["threat_score"] += 1

        # Escalation: per-IP only (no global lockdown for brute force)
        if count >= self.cerberus_failed_logins:
            self._set_ip_threat(
                ip, THREAT_CERBERUS,
                f"Massive brute force: {count} failed logins in {self.failed_login_window}s"
            )
            return True

        if count >= self.lockdown_failed_logins:
            self._set_ip_threat(
                ip, THREAT_LOCKDOWN,
                f"Brute force attack: {count} failed logins in {self.failed_login_window}s"
            )
            return True

        if count >= self.max_failed_logins:
            self._set_ip_threat(
                ip, THREAT_ALERT,
                f"Suspicious logins: {count} failed in {self.failed_login_window}s"
            )
            # ALERT = log only, don't block yet
            return False

        return False

    def record_successful_login(self, ip: str):
        """Record a successful login - clear failed attempts for this IP"""
        if ip in self._failed_logins:
            del self._failed_logins[ip]

    # ================================================================
    # DDoS DETECTION
    # ================================================================

    def record_connection(self, ip: str) -> bool:
        """
        Record a new connection attempt.
        Returns True if connection should be REJECTED.
        Single-IP flood = ban that IP only. Multi-IP flood = global lockdown.
        """
        if self.is_whitelisted(ip):
            return False

        # Already banned?
        if self.is_ip_banned(ip):
            self._total_ddos_blocked += 1
            return True

        now = time.time()
        self._check_cooldown()

        # Clean old entries
        cutoff = now - self.connection_window
        self._connections[ip] = [t for t in self._connections[ip] if t > cutoff]
        self._total_connections_window = [t for t in self._total_connections_window if t > cutoff]

        self._connections[ip].append(now)
        self._total_connections_window.append(now)

        ip_count = len(self._connections[ip])
        total_count = len(self._total_connections_window)

        # --- Per-IP flood (ban only this IP, others unaffected) ---

        if ip_count >= self.cerberus_connections:
            self._total_ddos_blocked += 1
            self._set_ip_threat(
                ip, THREAT_CERBERUS,
                f"Extreme flood: {ip_count} connections in {self.connection_window}s"
            )
            return True

        if ip_count >= self.ddos_connections_per_ip:
            self._total_ddos_blocked += 1
            self._set_ip_threat(
                ip, THREAT_LOCKDOWN,
                f"DDoS from IP: {ip_count} connections in {self.connection_window}s"
            )
            return True

        if ip_count >= self.max_connections_per_ip:
            self._set_ip_threat(
                ip, THREAT_ALERT,
                f"High connection rate: {ip_count} in {self.connection_window}s"
            )
            # ALERT = log only, don't reject (could be reconnect bug)
            return False

        # --- Distributed DDoS (GLOBAL lockdown - affects everyone) ---
        if total_count >= self.ddos_total_connections:
            self._total_ddos_blocked += 1
            self._set_global_threat(
                THREAT_LOCKDOWN,
                f"Distributed DDoS: {total_count} connections in {self.connection_window}s",
                ip
            )
            # Ban the triggering IP at least
            self._banned_ips.add(ip)
            return True

        return False

    # ================================================================
    # MESSAGE FLOOD DETECTION (WebSocket)
    # ================================================================

    def record_message(self, ip: str) -> bool:
        """
        Record a WebSocket message from IP.
        Returns True if message should be DROPPED and connection closed.
        Only bans the flooding IP, not others.
        """
        if self.is_whitelisted(ip):
            return False

        now = time.time()
        cutoff = now - self.message_window
        self._message_rates[ip] = [t for t in self._message_rates[ip] if t > cutoff]
        self._message_rates[ip].append(now)

        rate = len(self._message_rates[ip]) / self.message_window

        if rate > self.max_messages_per_second * 3:
            self._set_ip_threat(
                ip, THREAT_CERBERUS,
                f"Extreme message flood: {rate:.0f} msg/s"
            )
            return True

        if rate > self.max_messages_per_second * 2:
            self._set_ip_threat(
                ip, THREAT_LOCKDOWN,
                f"Message flood: {rate:.0f} msg/s"
            )
            return True

        if rate > self.max_messages_per_second:
            self._set_ip_threat(
                ip, THREAT_ALERT,
                f"High message rate: {rate:.0f} msg/s"
            )
            # ALERT = log only, don't drop
            return False

        return False

    # ================================================================
    # HONEYPOT INTEGRATION
    # ================================================================

    def honeypot_triggered(self, ip: str, username: str = "unknown", password: str = "***"):
        """
        Called on EACH SSH honeypot login attempt. Escalates with each try:
          1st attempt -> ALERT (log + admin notification + ban IP from Titan-Net)
          2nd attempt -> CERBERUS (permaban + infrastructure countermeasures)
        Honeypot lets attacker in on 2nd attempt to trap them in fake shell.
        """
        if self.is_whitelisted(ip):
            logger.info(f"[CERBERUS] Honeypot: whitelisted IP {ip} ignored")
            return

        self._log_intrusion(
            "HONEYPOT", ip,
            f"SSH honeypot login attempt: user={username}"
        )

        # Track attacker and count attempts
        if ip not in self._tracked_attackers:
            self._tracked_attackers[ip] = {
                "threat_score": 0,
                "first_seen": time.time(),
                "type": "honeypot_ssh",
                "honeypot_attempts": 0
            }
        self._tracked_attackers[ip]["threat_score"] += 25
        self._tracked_attackers[ip]["honeypot_attempts"] = \
            self._tracked_attackers[ip].get("honeypot_attempts", 0) + 1

        attempts = self._tracked_attackers[ip]["honeypot_attempts"]

        # Escalate based on attempt count
        if attempts >= 2:
            # 2nd attempt = CERBERUS: permaban + countermeasures
            self._set_ip_threat(
                ip, THREAT_CERBERUS,
                f"SSH honeypot: 2nd login attempt as '{username}' - confirmed attacker, shutting down"
            )
        else:
            # 1st attempt = ALERT + ban IP from Titan-Net
            self._set_ip_threat(
                ip, THREAT_ALERT,
                f"SSH honeypot: login attempt as '{username}'"
            )
            # Ban from Titan-Net immediately even at ALERT level
            self._banned_ips.add(ip)

    def honeypot_command_executed(self, ip: str, command: str):
        """Called when attacker executes a command in honeypot"""
        if self.is_whitelisted(ip):
            return

        self._log_intrusion("HONEYPOT_CMD", ip, f"Command: {command}")

        # Dangerous commands = keep at LOCKDOWN (IP already banned)
        dangerous_commands = [
            'rm ', 'dd ', 'wget ', 'curl ', 'chmod ', 'chown ',
            'passwd', 'useradd', 'usermod', 'cat /etc/shadow',
            'cat /etc/passwd', 'iptables', 'systemctl', 'service ',
            'kill ', 'pkill', 'nc ', 'ncat ', 'nmap', 'python',
            'perl', 'ruby', 'bash -i', 'sh -i', '/dev/tcp',
            'base64', 'eval ', 'exec ', 'crontab', 'ssh ',
            'scp ', 'rsync', 'tar ', 'zip ', 'mysql', 'sqlite',
            'mongo', 'redis', 'apt ', 'yum ', 'pip ', 'npm '
        ]

        # Critical commands = escalate to CERBERUS (permaban + countermeasures)
        critical_commands = [
            '/etc/shadow', 'authorized_keys', 'id_rsa', 'crontab -e',
            'reverse shell', '/dev/tcp', 'base64 -d',
            'rm -rf', 'dd if=', 'mkfs', '> /dev/sd'
        ]

        if any(cmd in command.lower() for cmd in critical_commands):
            self._set_ip_threat(
                ip, THREAT_CERBERUS,
                f"Critical attack command in honeypot: {command[:100]}"
            )
        elif any(cmd in command.lower() for cmd in dangerous_commands):
            self._set_ip_threat(
                ip, THREAT_LOCKDOWN,
                f"Dangerous command in honeypot: {command[:100]}"
            )

    # ================================================================
    # ADMIN CONTROLS
    # ================================================================

    def activate_cerberus(self, reason: str = "Manual activation", admin_ip: str = "admin"):
        """Manually activate full GLOBAL Cerberus Protocol"""
        self._set_global_threat(THREAT_CERBERUS, reason, admin_ip)

    def activate_lockdown(self, reason: str = "Manual lockdown", admin_ip: str = "admin"):
        """Manually activate GLOBAL lockdown"""
        self._set_global_threat(THREAT_LOCKDOWN, reason, admin_ip)

    def deactivate_lockdown(self, reason: str = "Manual deactivation"):
        """Deactivate GLOBAL lockdown and reset to NORMAL"""
        self._lockdown_active = False
        self._lockdown_start = None
        self._lockdown_reason = ""
        self.threat_level = THREAT_NORMAL
        logger.info(f"LOCKDOWN DEACTIVATED: {reason}")

    def ban_ip(self, ip: str, permanent: bool = False):
        """Manually ban an IP"""
        self._banned_ips.add(ip)
        if permanent:
            self._permanent_banned_ips.add(ip)
        self._log_intrusion("MANUAL_BAN", ip, f"permanent={permanent}")

    def unban_ip(self, ip: str):
        """Remove IP ban"""
        self._banned_ips.discard(ip)
        self._permanent_banned_ips.discard(ip)
        if ip in self._ip_threat:
            del self._ip_threat[ip]

    # ================================================================
    # STATUS & REPORTING
    # ================================================================

    def get_status(self) -> Dict[str, Any]:
        """Get current Cerberus status"""
        self._check_cooldown()
        return {
            "threat_level": self.threat_level,
            "threat_name": THREAT_NAMES.get(self.threat_level, "UNKNOWN"),
            "lockdown_active": self._lockdown_active,
            "lockdown_reason": self._lockdown_reason,
            "lockdown_duration": (
                time.time() - self._lockdown_start
                if self._lockdown_start else 0
            ),
            "banned_ips": list(self._banned_ips),
            "permanent_banned_ips": list(self._permanent_banned_ips),
            "whitelisted_ips": list(self._whitelisted_ips),
            "per_ip_threats": {
                ip: {
                    "level": THREAT_NAMES.get(data["level"], "?"),
                    "reason": data["reason"],
                }
                for ip, data in self._ip_threat.items()
                if data["level"] > THREAT_NORMAL
            },
            "tracked_attackers": {
                ip: {
                    "threat_score": data["threat_score"],
                    "type": data["type"],
                    "first_seen": datetime.fromtimestamp(data["first_seen"]).isoformat()
                }
                for ip, data in self._tracked_attackers.items()
            },
            "stats": {
                "intrusions_blocked": self._total_intrusions_blocked,
                "ddos_blocked": self._total_ddos_blocked,
            }
        }

    def get_logs(self, max_lines: int = 100) -> List[Dict[str, str]]:
        """Read recent intrusion log entries from cerberus_intrusions.log"""
        logs = []
        try:
            if not os.path.exists(self._intrusion_log):
                return logs
            with open(self._intrusion_log, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            # Take last max_lines
            for line in lines[-max_lines:]:
                line = line.strip()
                if not line:
                    continue
                # Format: "2026-04-06 12:00:00,123 | WARNING | [LEVEL] IP=x.x.x.x | details"
                parts = line.split(' | ', 2)
                if len(parts) >= 3:
                    logs.append({
                        "timestamp": parts[0].strip(),
                        "severity": parts[1].strip(),
                        "message": parts[2].strip()
                    })
                else:
                    logs.append({
                        "timestamp": "",
                        "severity": "",
                        "message": line
                    })
        except Exception as e:
            logger.error(f"Error reading intrusion log: {e}")
        return logs

    def get_cerberus_client_message(self, reason: str) -> Dict:
        """Build the cerberus_shutdown message to send to attacker's client"""
        return {
            "type": "cerberus_shutdown",
            "reason": reason,
            "threat_level": THREAT_NAMES.get(self.threat_level, "CERBERUS"),
            "message": "Cerberus Protocol activated. Intrusion attempt detected. "
                       "Your session has been terminated and your system will be shut down.",
            "action": "shutdown",
            "timestamp": datetime.now().isoformat()
        }

    def get_lockdown_rejection_message(self) -> Dict:
        """Build rejection message for login attempts during GLOBAL lockdown"""
        return {
            "type": "login_response",
            "success": False,
            "error": "Server is in lockdown mode. No new connections are allowed.",
            "cerberus_active": True,
            "threat_level": THREAT_NAMES.get(self.threat_level, "LOCKDOWN")
        }

    def get_admin_alert_message(self, reason: str, attacker_ip: str) -> Dict:
        """Build admin notification message"""
        return {
            "type": "cerberus_alert",
            "threat_level": self.threat_level,
            "threat_name": THREAT_NAMES.get(self.threat_level, "UNKNOWN"),
            "reason": reason,
            "attacker_ip": attacker_ip,
            "lockdown_active": self._lockdown_active,
            "status": self.get_status(),
            "timestamp": datetime.now().isoformat()
        }
