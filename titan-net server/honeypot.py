"""
Titan-Net SSH Honeypot - Fake SSH Server (Decoy Environment)

Presents a convincing fake Ubuntu server shell to attackers.
All commands are logged and analyzed. Triggers Cerberus Protocol on intrusion.

Runs on a decoy port (default 2222) while real SSH runs on a non-standard port.
"""

import logging
import os
import socket
import threading
import time
from datetime import datetime
from typing import Optional, Callable

logger = logging.getLogger('Honeypot')

# Fake system info
FAKE_HOSTNAME = "titan-prod-01"
FAKE_OS = "Ubuntu 22.04.3 LTS"
FAKE_KERNEL = "5.15.0-91-generic"
FAKE_USER = "admin"

# Fake MOTD (Message of the Day)
FAKE_MOTD = f"""Welcome to {FAKE_OS} (GNU/Linux {FAKE_KERNEL} x86_64)

 * Documentation:  https://help.ubuntu.com
 * Management:     https://landscape.canonical.com
 * Support:        https://ubuntu.com/advantage

  System information as of {{date}}

  System load:  0.42              Processes:             187
  Usage of /:   34.2% of 49.09GB  Users logged in:      1
  Memory usage: 62%               IPv4 address for eth0: 10.0.0.15
  Swap usage:   3%                IPv6 address for eth0: fe80::1

 * Titan-Net Server v2.5.1 is running on port 8001
 * Database size: 142MB (titannet.db)

Last login: {{last_login}} from {{last_ip}}
"""

# Fake filesystem structure
FAKE_FILESYSTEM = {
    "/": ["bin", "boot", "dev", "etc", "home", "lib", "media", "mnt",
          "opt", "proc", "root", "run", "sbin", "srv", "sys", "tmp",
          "usr", "var"],
    "/home": ["admin", "titan"],
    "/home/admin": [".bash_history", ".bashrc", ".profile", ".ssh", "scripts"],
    "/home/admin/.ssh": ["authorized_keys", "id_rsa", "id_rsa.pub", "known_hosts"],
    "/home/admin/scripts": ["backup.sh", "monitor.sh", "deploy.sh"],
    "/opt": ["titan-net"],
    "/opt/titan-net": ["server.py", "config.py", "models.py", "http_server.py",
                       "main.py", "requirements.txt", "database", "logs",
                       "uploads", "broadcasts"],
    "/opt/titan-net/database": ["titannet.db", "titannet.db.bak"],
    "/opt/titan-net/logs": ["server.log", "http_server.log", "main.log"],
    "/etc": ["passwd", "shadow", "hosts", "hostname", "resolv.conf",
             "ssh", "systemd", "nginx", "ufw"],
    "/etc/ssh": ["sshd_config", "ssh_host_rsa_key", "ssh_host_rsa_key.pub"],
    "/root": [".bash_history", ".bashrc", ".profile", ".ssh"],
    "/var/log": ["syslog", "auth.log", "kern.log", "ufw.log"],
}

# Fake file contents
FAKE_FILES = {
    "/etc/hostname": FAKE_HOSTNAME,
    "/etc/hosts": (
        "127.0.0.1 localhost\n"
        f"127.0.1.1 {FAKE_HOSTNAME}\n"
        "10.0.0.15 titan-prod-01\n"
        "10.0.0.20 titan-db-01\n"
    ),
    "/etc/passwd": (
        "root:x:0:0:root:/root:/bin/bash\n"
        "daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n"
        "bin:x:2:2:bin:/bin:/usr/sbin/nologin\n"
        "sys:x:3:3:sys:/dev:/usr/sbin/nologin\n"
        "sshd:x:106:65534::/run/sshd:/usr/sbin/nologin\n"
        "admin:x:1000:1000:Titan Admin:/home/admin:/bin/bash\n"
        "titan:x:1001:1001:Titan Service:/home/titan:/usr/sbin/nologin\n"
        "mysql:x:110:117:MySQL Server:/nonexistent:/bin/false\n"
    ),
    "/etc/shadow": "cat: /etc/shadow: Permission denied",
    "/home/admin/.bash_history": (
        "cd /opt/titan-net\n"
        "python3 server.py\n"
        "systemctl restart titan-net\n"
        "tail -f logs/server.log\n"
        "df -h\n"
        "free -m\n"
        "htop\n"
        "ufw status\n"
        "git pull\n"
        "pip3 install -r requirements.txt\n"
        "sqlite3 database/titannet.db\n"
        "cat config.py\n"
    ),
    "/opt/titan-net/config.py": (
        '"""\nTitan-Net Server Configuration\n"""\n\n'
        'import os\n\n\n'
        'class Config:\n'
        '    WEBSOCKET_HOST = "0.0.0.0"\n'
        '    WEBSOCKET_PORT = 8001\n'
        '    HTTP_PORT = 8000\n'
        '    DATABASE_PATH = "database/titannet.db"\n'
        '    SECRET_KEY = os.getenv("SECRET_KEY", "production-key-here")\n'
        '    DATABASE_KEY = os.getenv("DATABASE_KEY")\n'
        '    LOG_LEVEL = "INFO"\n'
    ),
    "/home/admin/scripts/backup.sh": (
        "#!/bin/bash\n"
        "# Daily backup script\n"
        "DATE=$(date +%Y%m%d)\n"
        "cp /opt/titan-net/database/titannet.db /backup/titannet_$DATE.db\n"
        "echo 'Backup completed'\n"
    ),
    "/home/admin/.ssh/authorized_keys": (
        "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQ... admin@titan-prod\n"
    ),
    "/home/admin/.ssh/id_rsa": (
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "ERROR: Permission denied. Key protected by passphrase.\n"
        "-----END OPENSSH PRIVATE KEY-----\n"
    ),
}


class HoneypotSession:
    """A single fake SSH session for one attacker"""

    def __init__(self, client_socket: socket.socket, client_ip: str,
                 on_command: Optional[Callable] = None,
                 on_login: Optional[Callable] = None):
        self.socket = client_socket
        self.ip = client_ip
        self.on_command = on_command
        self.on_login = on_login
        self.cwd = "/home/admin"
        self.user = FAKE_USER
        self.authenticated = False
        self.commands_executed = 0
        self.login_attempts = 0
        self.start_time = time.time()

    def send(self, text: str):
        """Send text to attacker"""
        try:
            self.socket.sendall(text.encode('utf-8'))
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def recv(self, size: int = 4096) -> str:
        """Receive text from attacker"""
        try:
            data = self.socket.recv(size)
            if not data:
                return ""
            return data.decode('utf-8', errors='replace').strip()
        except (ConnectionResetError, OSError, UnicodeDecodeError):
            return ""

    def handle_session(self):
        """Main session handler - fake SSH login then shell"""
        try:
            # Send SSH banner
            self.send("SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.6\r\n")

            # Simple auth simulation (not real SSH protocol, just looks like one)
            # Wait a moment then present login
            time.sleep(0.5)

            # Fake login prompt - reject 1st attempt, "accept" on 2nd
            # Each attempt notifies Cerberus (escalates: ALERT -> LOCKDOWN)
            for attempt in range(2):
                self.send(f"{FAKE_HOSTNAME} login: ")
                username = self.recv()
                if not username:
                    return

                self.send("Password: ")
                password = self.recv()
                if not password:
                    return

                self.login_attempts += 1

                # Notify Cerberus about EVERY login attempt
                if self.on_login:
                    self.on_login(self.ip, username, password)

                # 1st attempt: reject (looks realistic)
                # 2nd attempt: "accept" to trap attacker in fake shell
                if attempt < 1:
                    self.send("Login incorrect\r\n")
                    time.sleep(1.5)
                else:
                    # 2nd try - let them in to the fake shell
                    self.authenticated = True
                    self.user = username
                    break

            if not self.authenticated:
                self.send("Maximum login attempts exceeded.\r\n")
                return

            # Send fake MOTD
            now = datetime.now()
            motd = FAKE_MOTD.format(
                date=now.strftime("%a %b %d %H:%M:%S UTC %Y"),
                last_login=now.strftime("%a %b %d %H:%M:%S %Y"),
                last_ip="10.0.0.5"
            )
            self.send(motd + "\r\n")

            # Interactive shell loop
            while True:
                prompt = f"{self.user}@{FAKE_HOSTNAME}:{self.cwd}$ "
                self.send(prompt)

                command = self.recv()
                if not command:
                    break

                self.commands_executed += 1

                # Log command via Cerberus
                if self.on_command:
                    self.on_command(self.ip, command)

                # Process command
                output = self.process_command(command)
                if output is None:
                    # Exit command
                    self.send("logout\r\nConnection to server closed.\r\n")
                    break

                if output:
                    self.send(output + "\r\n")

        except Exception as e:
            logger.error(f"Honeypot session error for {self.ip}: {e}")
        finally:
            try:
                self.socket.close()
            except Exception:
                pass

    def process_command(self, command: str) -> Optional[str]:
        """Process a fake shell command. Returns None for exit."""
        parts = command.split()
        if not parts:
            return ""

        cmd = parts[0]
        args = parts[1:] if len(parts) > 1 else []

        # Exit commands
        if cmd in ('exit', 'logout', 'quit'):
            return None

        # cd
        if cmd == 'cd':
            return self._cmd_cd(args)

        # ls
        if cmd == 'ls':
            return self._cmd_ls(args)

        # cat
        if cmd == 'cat':
            return self._cmd_cat(args)

        # pwd
        if cmd == 'pwd':
            return self.cwd

        # whoami
        if cmd == 'whoami':
            return self.user

        # id
        if cmd == 'id':
            if self.user == 'root':
                return "uid=0(root) gid=0(root) groups=0(root)"
            return f"uid=1000({self.user}) gid=1000({self.user}) groups=1000({self.user}),27(sudo)"

        # hostname
        if cmd == 'hostname':
            return FAKE_HOSTNAME

        # uname
        if cmd == 'uname':
            if '-a' in args:
                return f"Linux {FAKE_HOSTNAME} {FAKE_KERNEL} #1 SMP PREEMPT_DYNAMIC x86_64 GNU/Linux"
            return "Linux"

        # uptime
        if cmd == 'uptime':
            return " 14:23:07 up 47 days,  3:12,  2 users,  load average: 0.42, 0.38, 0.31"

        # w / who
        if cmd in ('w', 'who'):
            return (
                f"{self.user}   pts/0    {self.ip}   {datetime.now().strftime('%H:%M')}\n"
                "admin    pts/1    10.0.0.5         09:15"
            )

        # ps
        if cmd == 'ps':
            return (
                "  PID TTY          TIME CMD\n"
                "    1 ?        00:05:12 systemd\n"
                "  412 ?        00:00:03 sshd\n"
                "  834 ?        00:12:45 python3 /opt/titan-net/server.py\n"
                "  835 ?        00:03:21 python3 /opt/titan-net/http_server.py\n"
                " 1205 pts/0    00:00:00 bash\n"
                f" {1300 + self.commands_executed} pts/0    00:00:00 ps"
            )

        # netstat / ss
        if cmd in ('netstat', 'ss'):
            return (
                "Proto  Local Address          Foreign Address        State\n"
                "tcp    0.0.0.0:8001           0.0.0.0:*              LISTEN\n"
                "tcp    0.0.0.0:8000           0.0.0.0:*              LISTEN\n"
                "tcp    0.0.0.0:22             0.0.0.0:*              LISTEN\n"
                "tcp    0.0.0.0:443            0.0.0.0:*              LISTEN\n"
                f"tcp    10.0.0.15:22           {self.ip}:54321    ESTABLISHED"
            )

        # df
        if cmd == 'df':
            return (
                "Filesystem     1K-blocks    Used Available Use% Mounted on\n"
                "/dev/sda1       51474528 17602432  31228696  37% /\n"
                "tmpfs            2013336        0   2013336   0% /dev/shm\n"
                "/dev/sda2       10190100  2341604   7312780  25% /boot"
            )

        # free
        if cmd == 'free':
            return (
                "              total        used        free      shared  buff/cache   available\n"
                "Mem:        4026672     2498412      312856       18932     1215404     1284560\n"
                "Swap:       2097148       62480     2034668"
            )

        # ifconfig / ip addr
        if cmd in ('ifconfig', 'ip'):
            return (
                "eth0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500\n"
                "        inet 10.0.0.15  netmask 255.255.255.0  broadcast 10.0.0.255\n"
                "        inet6 fe80::1  prefixlen 64  scopeid 0x20<link>\n"
                "        ether 52:54:00:ab:cd:ef  txqueuelen 1000  (Ethernet)\n"
                "\nlo: flags=73<UP,LOOPBACK,RUNNING>  mtu 65536\n"
                "        inet 127.0.0.1  netmask 255.0.0.0"
            )

        # systemctl
        if cmd == 'systemctl':
            if 'status' in args:
                return (
                    "titan-net.service - Titan-Net WebSocket Server\n"
                    "     Loaded: loaded (/etc/systemd/system/titan-net.service; enabled)\n"
                    "     Active: active (running) since Mon 2026-02-17 11:11:00 UTC; 47 days ago\n"
                    "   Main PID: 834 (python3)\n"
                    "      Tasks: 12 (limit: 4662)\n"
                    "     Memory: 245.3M\n"
                    "        CPU: 3h 12min 45s\n"
                    "     CGroup: /system.slice/titan-net.service\n"
                    "             834 python3 /opt/titan-net/server.py"
                )
            if 'stop' in args or 'restart' in args or 'disable' in args:
                # Pretend it works but do nothing
                time.sleep(1)
                return ""
            return "Usage: systemctl {start|stop|restart|status|enable|disable} [unit]"

        # sudo
        if cmd == 'sudo':
            if args:
                # Process the command after sudo as if it succeeded
                return self.process_command(' '.join(args))
            return "usage: sudo [-h] command"

        # wget / curl (pretend to download)
        if cmd in ('wget', 'curl'):
            time.sleep(2)  # Slow down attacker
            return f"Connecting to {''.join(args[:1])}... failed: Connection timed out."

        # rm (pretend it works)
        if cmd == 'rm':
            time.sleep(0.5)
            return ""

        # chmod/chown (pretend)
        if cmd in ('chmod', 'chown'):
            return ""

        # history
        if cmd == 'history':
            return FAKE_FILES.get("/home/admin/.bash_history", "")

        # echo
        if cmd == 'echo':
            return ' '.join(args)

        # date
        if cmd == 'date':
            return datetime.now().strftime("%a %b %d %H:%M:%S UTC %Y")

        # env
        if cmd == 'env':
            return (
                f"USER={self.user}\n"
                f"HOME=/home/{self.user}\n"
                f"HOSTNAME={FAKE_HOSTNAME}\n"
                "SHELL=/bin/bash\n"
                "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n"
                "LANG=en_US.UTF-8\n"
                "TERM=xterm-256color"
            )

        # head / tail
        if cmd in ('head', 'tail'):
            if args:
                return self._cmd_cat(args[-1:])
            return f"{cmd}: missing operand"

        # find
        if cmd == 'find':
            time.sleep(1)
            return "/opt/titan-net/database/titannet.db\n/opt/titan-net/config.py\n/opt/titan-net/server.py"

        # Default - command not found
        return f"-bash: {cmd}: command not found"

    def _cmd_cd(self, args: list) -> str:
        """Handle cd command"""
        if not args or args[0] == '~':
            self.cwd = f"/home/{self.user}"
            return ""

        target = args[0]
        if target.startswith('/'):
            new_path = target
        elif target == '..':
            new_path = '/'.join(self.cwd.rstrip('/').split('/')[:-1]) or '/'
        else:
            new_path = f"{self.cwd.rstrip('/')}/{target}"

        # Check if directory exists in fake FS
        if new_path in FAKE_FILESYSTEM or new_path.rstrip('/') in FAKE_FILESYSTEM:
            self.cwd = new_path.rstrip('/') or '/'
            return ""
        return f"-bash: cd: {target}: No such file or directory"

    def _cmd_ls(self, args: list) -> str:
        """Handle ls command"""
        target = self.cwd
        show_hidden = False

        for arg in args:
            if arg.startswith('-'):
                if 'a' in arg:
                    show_hidden = True
            else:
                target = arg if arg.startswith('/') else f"{self.cwd.rstrip('/')}/{arg}"

        entries = FAKE_FILESYSTEM.get(target, FAKE_FILESYSTEM.get(target.rstrip('/'), None))
        if entries is None:
            return f"ls: cannot access '{target}': No such file or directory"

        if show_hidden:
            entries = ['.', '..'] + list(entries)

        return '  '.join(entries)

    def _cmd_cat(self, args: list) -> str:
        """Handle cat command"""
        if not args:
            return "cat: missing operand"

        filepath = args[0]
        if not filepath.startswith('/'):
            filepath = f"{self.cwd.rstrip('/')}/{filepath}"

        content = FAKE_FILES.get(filepath)
        if content:
            return content

        # Check if it's a directory
        if filepath in FAKE_FILESYSTEM:
            return f"cat: {filepath}: Is a directory"

        return f"cat: {filepath}: No such file or directory"


class HoneypotServer:
    """TCP server that simulates SSH for honeypot purposes"""

    def __init__(self, host: str = '0.0.0.0', port: int = 2222,
                 cerberus=None, log_dir: str = "logs"):
        self.host = host
        self.port = port
        self.cerberus = cerberus
        self.running = False
        self.server_socket = None
        self.thread = None

        # Logging
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self._session_log = os.path.join(log_dir, "honeypot_sessions.log")
        self._setup_session_logger()

        # Stats
        self.total_connections = 0
        self.total_commands = 0

    def _setup_session_logger(self):
        """Setup dedicated session logger"""
        self._session_logger = logging.getLogger('HoneypotSessions')
        self._session_logger.setLevel(logging.INFO)
        if not self._session_logger.handlers:
            handler = logging.FileHandler(self._session_log)
            handler.setFormatter(logging.Formatter(
                '%(asctime)s | %(message)s'
            ))
            self._session_logger.addHandler(handler)

    def _on_login(self, ip: str, username: str, password: str):
        """Called when attacker tries to login"""
        self._session_logger.info(
            f"LOGIN_ATTEMPT | IP={ip} | user={username} | pass={password}"
        )
        if self.cerberus:
            self.cerberus.honeypot_triggered(ip, username, password)

    def _on_command(self, ip: str, command: str):
        """Called when attacker executes a command"""
        self.total_commands += 1
        self._session_logger.info(f"COMMAND | IP={ip} | cmd={command}")
        if self.cerberus:
            self.cerberus.honeypot_command_executed(ip, command)

    def _handle_client(self, client_socket: socket.socket, client_addr):
        """Handle a single honeypot client in a thread"""
        ip = client_addr[0]
        self.total_connections += 1

        logger.warning(f"Honeypot connection from {ip}:{client_addr[1]}")
        self._session_logger.info(f"CONNECTION | IP={ip} | port={client_addr[1]}")

        session = HoneypotSession(
            client_socket, ip,
            on_command=self._on_command,
            on_login=self._on_login
        )
        session.handle_session()

        duration = time.time() - session.start_time
        self._session_logger.info(
            f"DISCONNECT | IP={ip} | duration={duration:.1f}s | "
            f"commands={session.commands_executed} | "
            f"login_attempts={session.login_attempts}"
        )

    def start(self):
        """Start the honeypot server in a background thread"""
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info(f"Honeypot SSH server started on {self.host}:{self.port}")

    def _run(self):
        """Main server loop"""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.settimeout(1.0)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)

            logger.info(f"Honeypot listening on {self.host}:{self.port}")

            while self.running:
                try:
                    client_socket, client_addr = self.server_socket.accept()
                    # Handle each client in a new thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client_socket, client_addr),
                        daemon=True
                    )
                    client_thread.start()
                except socket.timeout:
                    continue
                except OSError:
                    if self.running:
                        logger.error("Honeypot socket error")
                    break

        except Exception as e:
            logger.error(f"Honeypot server error: {e}")
        finally:
            if self.server_socket:
                try:
                    self.server_socket.close()
                except Exception:
                    pass

    def stop(self):
        """Stop the honeypot server"""
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
        if self.thread:
            self.thread.join(timeout=3)
        logger.info("Honeypot server stopped")

    def get_stats(self) -> dict:
        """Get honeypot statistics"""
        return {
            "running": self.running,
            "port": self.port,
            "total_connections": self.total_connections,
            "total_commands": self.total_commands,
        }
