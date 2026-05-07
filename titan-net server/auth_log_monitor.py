"""
Titan-Net Auth Log Monitor - Real SSH Failed Login Detection

Monitors SSH login attempts and feeds them into the Cerberus Protocol.

Supports two backends:
  1. journalctl (Debian 13+, systemd-based) - follows sshd journal in real-time
  2. /var/log/auth.log (Debian 12 and older) - tail-follow file approach

Auto-detects which backend to use on startup.
"""

import logging
import os
import re
import subprocess
import threading
import time
from typing import Optional

logger = logging.getLogger('AuthLogMonitor')

# Patterns for failed SSH logins
FAILED_LOGIN_PATTERNS = [
    # "Failed password for admin from 1.2.3.4 port 54321 ssh2"
    re.compile(
        r'Failed password for (?:invalid user )?(\S+) from (\S+) port (\d+)'
    ),
    # "Invalid user hacker from 1.2.3.4 port 54321"
    re.compile(
        r'Invalid user (\S+) from (\S+) port (\d+)'
    ),
    # "Connection closed by authenticating user admin 1.2.3.4 port 54321 [preauth]"
    re.compile(
        r'Connection closed by authenticating user (\S+) (\S+) port (\d+) \[preauth\]'
    ),
    # "Disconnected from authenticating user admin 1.2.3.4 port 54321 [preauth]"
    re.compile(
        r'Disconnected from authenticating user (\S+) (\S+) port (\d+) \[preauth\]'
    ),
    # "maximum authentication attempts exceeded for admin from 1.2.3.4"
    re.compile(
        r'maximum authentication attempts exceeded for (?:invalid user )?(\S+) from (\S+)'
    ),
]

# Pattern for successful SSH login
SUCCESSFUL_LOGIN_PATTERN = re.compile(
    r'Accepted (?:password|publickey) for (\S+) from (\S+) port (\d+)'
)


class AuthLogMonitor:
    """
    Monitors SSH login attempts and reports to Cerberus.

    Auto-detects backend:
      - journalctl (Debian 13+ / systemd) - preferred
      - /var/log/auth.log (legacy) - fallback
    """

    def __init__(self, cerberus, auth_log_path: str = "/var/log/auth.log",
                 poll_interval: float = 1.0):
        self.cerberus = cerberus
        self.auth_log_path = auth_log_path
        self.poll_interval = poll_interval
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self._file_position = 0
        self._backend = None  # 'journalctl' or 'file'
        self._journal_process: Optional[subprocess.Popen] = None

        # Stats
        self.total_failed_logins = 0
        self.total_successful_logins = 0
        self.unique_attacker_ips = set()

    def _detect_backend(self) -> Optional[str]:
        """Detect which backend to use for SSH log monitoring"""
        # Try journalctl first (Debian 13+, systemd-based)
        try:
            result = subprocess.run(
                ['journalctl', '-u', 'ssh.service', '-n', '1', '--no-pager'],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                logger.info("Detected journalctl backend (systemd)")
                return 'journalctl'
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Also try sshd.service (some systems use this name)
        try:
            result = subprocess.run(
                ['journalctl', '-u', 'sshd.service', '-n', '1', '--no-pager'],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                logger.info("Detected journalctl backend (systemd, sshd.service)")
                return 'journalctl'
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Fallback to auth.log file
        if os.path.exists(self.auth_log_path) and os.access(self.auth_log_path, os.R_OK):
            logger.info(f"Detected file backend: {self.auth_log_path}")
            return 'file'

        return None

    def _get_journalctl_unit(self) -> str:
        """Determine the correct systemd unit name for SSH"""
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', 'ssh.service'],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                return 'ssh.service'
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return 'sshd.service'

    def start(self):
        """Start monitoring SSH logs in a background thread"""
        self._backend = self._detect_backend()

        if not self._backend:
            logger.warning(
                "No SSH log source found (no journalctl, no auth.log) - "
                "SSH login monitoring disabled"
            )
            return False

        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info(
            f"Auth log monitor started: backend={self._backend} "
            f"(polling every {self.poll_interval}s)"
        )
        return True

    def stop(self):
        """Stop monitoring"""
        self.running = False
        if self._journal_process:
            try:
                self._journal_process.terminate()
                self._journal_process.wait(timeout=3)
            except Exception:
                try:
                    self._journal_process.kill()
                except Exception:
                    pass
            self._journal_process = None
        if self.thread:
            self.thread.join(timeout=3)
        logger.info("Auth log monitor stopped")

    def _monitor_loop(self):
        """Main monitoring loop - dispatches to correct backend"""
        if self._backend == 'journalctl':
            self._monitor_journalctl()
        elif self._backend == 'file':
            self._monitor_file()

    def _monitor_journalctl(self):
        """Monitor SSH via journalctl --follow (Debian 13+)"""
        unit = self._get_journalctl_unit()
        logger.info(f"Starting journalctl follow for {unit}")

        while self.running:
            try:
                # Start journalctl following new entries only
                self._journal_process = subprocess.Popen(
                    ['journalctl', '-u', unit, '-f', '-n', '0',
                     '--no-pager', '-o', 'cat'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1  # Line-buffered
                )

                for line in self._journal_process.stdout:
                    if not self.running:
                        break
                    line = line.strip()
                    if line:
                        self._process_line(line)

                # Process exited - restart if still running
                if self.running:
                    logger.warning("journalctl process exited, restarting in 5s...")
                    time.sleep(5)

            except Exception as e:
                logger.error(f"journalctl monitor error: {e}")
                if self.running:
                    time.sleep(5)

    def _monitor_file(self):
        """Monitor SSH via /var/log/auth.log (legacy Debian)"""
        # Start from end of file (only monitor NEW entries)
        try:
            self._file_position = os.path.getsize(self.auth_log_path)
        except OSError:
            self._file_position = 0

        while self.running:
            try:
                self._check_for_new_lines()
            except Exception as e:
                logger.error(f"Auth log monitor error: {e}")
            time.sleep(self.poll_interval)

    def _check_for_new_lines(self):
        """Read new lines from auth.log since last position"""
        try:
            current_size = os.path.getsize(self.auth_log_path)
        except OSError:
            return

        # File was rotated (logrotate) - size decreased
        if current_size < self._file_position:
            logger.info("Auth log rotated, resetting position")
            self._file_position = 0

        # No new data
        if current_size <= self._file_position:
            return

        try:
            with open(self.auth_log_path, 'r', encoding='utf-8', errors='replace') as f:
                f.seek(self._file_position)
                new_lines = f.readlines()
                self._file_position = f.tell()
        except (OSError, PermissionError) as e:
            logger.error(f"Cannot read auth.log: {e}")
            return

        for line in new_lines:
            line = line.strip()
            if not line:
                continue
            # Only process SSH-related lines
            if 'sshd' not in line:
                continue
            self._process_line(line)

    def _process_line(self, line: str):
        """Process a single log line"""
        # Check for failed login
        for pattern in FAILED_LOGIN_PATTERNS:
            match = pattern.search(line)
            if match:
                groups = match.groups()
                username = groups[0]
                ip = groups[1]
                self._handle_failed_login(ip, username)
                return

        # Check for successful login
        match = SUCCESSFUL_LOGIN_PATTERN.search(line)
        if match:
            username, ip = match.group(1), match.group(2)
            self._handle_successful_login(ip, username)

    def _handle_failed_login(self, ip: str, username: str):
        """Report failed SSH login to Cerberus"""
        self.total_failed_logins += 1
        self.unique_attacker_ips.add(ip)

        logger.warning(
            f"[AUTH] Failed SSH login: user={username} from {ip}"
        )

        # Report to Cerberus as failed login (brute force detection)
        if self.cerberus:
            blocked = self.cerberus.record_failed_login(ip, username)
            if blocked:
                logger.warning(
                    f"[AUTH] Cerberus blocked IP {ip} after SSH brute force"
                )

    def _handle_successful_login(self, ip: str, username: str):
        """Report successful SSH login to Cerberus (clears failed counter)"""
        self.total_successful_logins += 1

        logger.info(f"[AUTH] Successful SSH login: user={username} from {ip}")

        # Clear failed login counter for this IP
        if self.cerberus:
            self.cerberus.record_successful_login(ip)

    def get_stats(self) -> dict:
        """Get monitoring statistics"""
        return {
            "running": self.running,
            "backend": self._backend,
            "auth_log_path": self.auth_log_path,
            "total_failed_logins": self.total_failed_logins,
            "total_successful_logins": self.total_successful_logins,
            "unique_attacker_ips": len(self.unique_attacker_ips),
            "file_position": self._file_position,
        }
