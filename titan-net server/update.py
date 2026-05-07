#!/usr/bin/env python3
"""
Quick update script for Titan-Net Server
Only uploads changed files and restarts the service
Auto-backs up production database before every update
"""
import os
import paramiko
from datetime import datetime

# Configuration - reads from environment variables or .env file
def _load_env():
    """Load .env file if it exists"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())

_load_env()

REMOTE_HOST = os.environ.get('DEPLOY_HOST', 'titosofttitan.com')
REMOTE_USER = os.environ.get('DEPLOY_USER', 'root')
REMOTE_PASSWORD = os.environ.get('DEPLOY_PASSWORD', '')
REMOTE_PATH = os.environ.get('DEPLOY_PATH', '/opt/titan-net')
LOCAL_PATH = os.path.dirname(os.path.abspath(__file__))

if not REMOTE_PASSWORD:
    print("[ERROR] DEPLOY_PASSWORD not set!")
    print("Set it via environment variable or create a .env file:")
    print("  DEPLOY_PASSWORD=your_password")
    exit(1)

# Directories and files to NEVER upload (protect production data)
EXCLUDE_DIRS = {'__pycache__', '.git', 'database', 'logs', 'uploads'}
EXCLUDE_FILES = {'.env', 'deploy.py', 'update.py'}
EXCLUDE_EXTENSIONS = {'.pyc', '.db', '.log', '.bak'}

def should_exclude(name, is_dir=False):
    """Check if a file or directory should be excluded from upload"""
    if is_dir:
        return name in EXCLUDE_DIRS
    if name in EXCLUDE_FILES:
        return True
    _, ext = os.path.splitext(name)
    if ext in EXCLUDE_EXTENSIONS:
        return True
    return False

def upload_directory(sftp, local_dir, remote_dir):
    """Upload directory (skips protected dirs like database, logs, uploads)"""
    dir_name = os.path.basename(local_dir)
    print(f"Uploading {dir_name}...")

    try:
        sftp.stat(remote_dir)
    except FileNotFoundError:
        sftp.mkdir(remote_dir)

    for item in os.listdir(local_dir):
        local_path = os.path.join(local_dir, item)

        if os.path.isdir(local_path):
            if should_exclude(item, is_dir=True):
                print(f"  [SKIP DIR] {item}/")
                continue
            remote_path = os.path.join(remote_dir, item).replace('\\', '/')
            upload_directory(sftp, local_path, remote_path)
        elif os.path.isfile(local_path):
            if should_exclude(item, is_dir=False):
                print(f"  [SKIP] {item}")
                continue
            remote_path = os.path.join(remote_dir, item).replace('\\', '/')
            print(f"  {item}")
            sftp.put(local_path, remote_path)

def main():
    print("=== Titan-Net Quick Update ===\n")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        print("Connecting...")
        ssh.connect(REMOTE_HOST, username=REMOTE_USER, password=REMOTE_PASSWORD, timeout=10)
        print("[OK] Connected\n")

        sftp = ssh.open_sftp()

        # Stop the service BEFORE taking the backup. main.py's stop_servers()
        # runs a TRUNCATE WAL checkpoint on shutdown, so once the process is
        # gone the on-disk DB file is a consistent committed state — no
        # uncheckpointed WAL frames floating around. Backing up while the
        # service is live (the old behaviour) captured a torn snapshot
        # because cp(1) reads only the main file, not -wal/-shm, and any
        # transactions still in WAL would be missing from the backup. The
        # missing-transactions backup then made auto-recovery from that
        # backup lossier than necessary on the next HMAC-drift incident.
        print("Stopping services to take a clean backup...")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = f"{REMOTE_PATH}/database/backups"
        # titan-net-http is a legacy unit kept around for backward compat;
        # main.py owns both ports now, so stopping titan-net is enough.
        stdin, stdout, stderr = ssh.exec_command(
            "systemctl stop titan-net-http 2>/dev/null; systemctl stop titan-net 2>/dev/null"
        )
        stdout.channel.recv_exit_status()
        # systemctl stop returns when the unit is inactive, which already
        # waits on main.py's stop_servers() to drain. The extra sleep gives
        # the kernel a beat to release file handles before we cp the DB.
        import time
        time.sleep(1)
        print("[OK] Service stopped\n")

        # Backup the now-quiescent production database.
        print("Backing up production database...")
        ssh.exec_command(f"mkdir -p {backup_dir}")
        backup_cmd = f"cp {REMOTE_PATH}/database/titannet.db {backup_dir}/titannet_{timestamp}.db"
        stdin, stdout, stderr = ssh.exec_command(backup_cmd)
        stdout.channel.recv_exit_status()
        # Drop any leftover WAL/SHM sidecars from the prior run — once the
        # service is stopped these should already be empty (TRUNCATE
        # checkpoint ran), but stale sidecars on the next start can confuse
        # SQLCipher and we just got a clean main file backup so we don't
        # need them.
        ssh.exec_command(
            f"rm -f {REMOTE_PATH}/database/titannet.db-wal "
            f"{REMOTE_PATH}/database/titannet.db-shm 2>/dev/null"
        )
        # Keep only last 10 backups to save disk space.
        cleanup_cmd = f"ls -t {backup_dir}/titannet_*.db 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null"
        ssh.exec_command(cleanup_cmd)
        print(f"[OK] Backup: database/backups/titannet_{timestamp}.db (keeping last 10)\n")

        print("Uploading files...")
        upload_directory(sftp, LOCAL_PATH, REMOTE_PATH)

        print("\nRestarting services...")
        stdin, stdout, stderr = ssh.exec_command("systemctl start titan-net")
        stdout.channel.recv_exit_status()
        print("[OK] Titan-Net server started (WebSocket :8001 + HTTP :8000)")

        print("\n=== Update Complete! ===")
        print("Server updated at ws://titosofttitan.com:8001")

        sftp.close()

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        ssh.close()

    return 0

if __name__ == '__main__':
    exit(main())
