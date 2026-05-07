"""Download remote production DB(s) to local before any update.py deploy.

Saves the active titannet.db (and cerberus_bans.db if it exists) under
``titan-net server/database/`` with a timestamp suffix. Belt-and-braces on
top of update.py's server-side backup.
"""
import os
from datetime import datetime
import paramiko


def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())


_load_env()

REMOTE_HOST = os.environ.get('DEPLOY_HOST', 'titosofttitan.com')
REMOTE_USER = os.environ.get('DEPLOY_USER', 'root')
REMOTE_PASSWORD = os.environ.get('DEPLOY_PASSWORD', '')
REMOTE_PATH = os.environ.get('DEPLOY_PATH', '/opt/titan-net')
LOCAL_DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database')

REMOTE_DBS = [
    'database/titannet.db',
    'database/cerberus_bans.db',
]


def main() -> int:
    if not REMOTE_PASSWORD:
        print("[ERROR] DEPLOY_PASSWORD not set!")
        return 1

    os.makedirs(LOCAL_DB_DIR, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        print(f"Connecting to {REMOTE_USER}@{REMOTE_HOST}...")
        ssh.connect(REMOTE_HOST, username=REMOTE_USER, password=REMOTE_PASSWORD, timeout=15)
        sftp = ssh.open_sftp()

        downloaded = []
        skipped = []
        for relpath in REMOTE_DBS:
            remote_path = f"{REMOTE_PATH}/{relpath}"
            base = os.path.splitext(os.path.basename(relpath))[0]
            local_path = os.path.join(LOCAL_DB_DIR, f"{base}_local_backup_{timestamp}.db")
            try:
                sftp.stat(remote_path)
            except FileNotFoundError:
                skipped.append(relpath)
                continue
            print(f"  Downloading {remote_path} -> {local_path}")
            sftp.get(remote_path, local_path)
            downloaded.append(local_path)

        sftp.close()
        print(f"[OK] Downloaded {len(downloaded)} DB file(s); skipped {len(skipped)} missing.")
        for path in downloaded:
            size = os.path.getsize(path)
            print(f"  - {path} ({size} bytes)")
        return 0
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        ssh.close()


if __name__ == '__main__':
    raise SystemExit(main())
