#!/usr/bin/env python3
"""
Deploy Titan-Net Server to remote host
"""
import os
import paramiko
from stat import S_ISDIR

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

# Files to exclude from upload
EXCLUDE_PATTERNS = [
    '__pycache__',
    '*.pyc',
    '.git',
    'database/*.db',
    'logs/*.log',
    'uploads/*',
    '.env',
    'deploy.py'
]

def should_exclude(path):
    """Check if path should be excluded"""
    for pattern in EXCLUDE_PATTERNS:
        if pattern in path:
            return True
    return False

def upload_directory(sftp, local_dir, remote_dir):
    """Recursively upload directory"""
    print(f"Uploading {local_dir} -> {remote_dir}")

    # Create remote directory
    try:
        sftp.stat(remote_dir)
    except FileNotFoundError:
        print(f"Creating directory: {remote_dir}")
        sftp.mkdir(remote_dir)

    # Upload files
    for item in os.listdir(local_dir):
        local_path = os.path.join(local_dir, item)
        remote_path = os.path.join(remote_dir, item).replace('\\', '/')

        if should_exclude(local_path):
            print(f"Skipping: {local_path}")
            continue

        if os.path.isfile(local_path):
            print(f"Uploading: {item}")
            sftp.put(local_path, remote_path)
        elif os.path.isdir(local_path):
            upload_directory(sftp, local_path, remote_path)

def main():
    print("=== Titan-Net Server Deployment ===")
    print(f"Remote: {REMOTE_USER}@{REMOTE_HOST}:{REMOTE_PATH}")
    print(f"Local: {LOCAL_PATH}")
    print()

    # Connect to remote server
    print("Connecting to remote server...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(
            REMOTE_HOST,
            username=REMOTE_USER,
            password=REMOTE_PASSWORD,
            timeout=10
        )
        print("[OK] Connected successfully!")

        # Create SFTP client
        sftp = ssh.open_sftp()

        # Create remote directory
        print(f"\nCreating remote directory: {REMOTE_PATH}")
        stdin, stdout, stderr = ssh.exec_command(f"mkdir -p {REMOTE_PATH}")
        stdout.channel.recv_exit_status()

        # Upload files
        print("\nUploading files...")
        upload_directory(sftp, LOCAL_PATH, REMOTE_PATH)

        # Create required directories on remote
        print("\nCreating required directories...")
        for dir_name in ['database', 'logs', 'uploads', 'uploads/pending', 'uploads/approved']:
            remote_dir = f"{REMOTE_PATH}/{dir_name}"
            stdin, stdout, stderr = ssh.exec_command(f"mkdir -p {remote_dir}")
            stdout.channel.recv_exit_status()
            print(f"[OK] Created: {remote_dir}")

        # Install Python requirements
        print("\nInstalling Python requirements...")
        stdin, stdout, stderr = ssh.exec_command(
            f"cd {REMOTE_PATH} && python3 -m pip install -r requirements.txt"
        )
        exit_status = stdout.channel.recv_exit_status()
        output = stdout.read().decode()
        error = stderr.read().decode()

        if exit_status == 0:
            print("[OK] Requirements installed successfully!")
        else:
            print(f"[WARN] Installation output:\n{output}")
            if error:
                print(f"[WARN] Errors:\n{error}")

        # Configure UFW firewall
        print("\nConfiguring UFW firewall...")

        # Allow SSH (port 22)
        stdin, stdout, stderr = ssh.exec_command("ufw allow 22/tcp")
        stdout.channel.recv_exit_status()
        print("[OK] Allowed SSH (port 22)")

        # Allow Titan-Net WebSocket (port 8001)
        stdin, stdout, stderr = ssh.exec_command("ufw allow 8001/tcp")
        stdout.channel.recv_exit_status()
        print("[OK] Allowed Titan-Net WebSocket (port 8001)")

        # Allow Titan-Net HTTP (port 8000)
        stdin, stdout, stderr = ssh.exec_command("ufw allow 8000/tcp")
        stdout.channel.recv_exit_status()
        print("[OK] Allowed Titan-Net HTTP (port 8000)")

        # Enable UFW if not enabled
        stdin, stdout, stderr = ssh.exec_command("echo 'y' | ufw enable")
        stdout.channel.recv_exit_status()
        print("[OK] UFW firewall enabled")

        # Show UFW status
        stdin, stdout, stderr = ssh.exec_command("ufw status")
        stdout.channel.recv_exit_status()
        status = stdout.read().decode()
        print(f"\nFirewall status:\n{status}")

        # Create systemd service file
        print("\nCreating systemd service...")
        service_content = f"""[Unit]
Description=Titan-Net WebSocket Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={REMOTE_PATH}
ExecStart=/usr/bin/python3 {REMOTE_PATH}/server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""

        # Upload service file
        stdin, stdout, stderr = ssh.exec_command(
            f"cat > /etc/systemd/system/titan-net.service << 'EOF'\n{service_content}\nEOF"
        )
        stdout.channel.recv_exit_status()
        print("[OK] Service file created")

        # Reload systemd
        stdin, stdout, stderr = ssh.exec_command("systemctl daemon-reload")
        stdout.channel.recv_exit_status()
        print("[OK] Systemd reloaded")

        # Enable and start service
        stdin, stdout, stderr = ssh.exec_command("systemctl enable titan-net")
        stdout.channel.recv_exit_status()
        print("[OK] Service enabled (will start on boot)")

        stdin, stdout, stderr = ssh.exec_command("systemctl start titan-net")
        exit_status = stdout.channel.recv_exit_status()

        if exit_status == 0:
            print("[OK] Service started successfully!")
        else:
            print("[WARN] Service start may have failed, checking status...")

        # Check service status
        stdin, stdout, stderr = ssh.exec_command("systemctl status titan-net --no-pager")
        stdout.channel.recv_exit_status()
        status = stdout.read().decode()
        print(f"\nService status:\n{status}")

        print("\n=== Deployment Complete! ===")
        print(f"\nServer is running at:")
        print(f"  WebSocket: ws://{REMOTE_HOST}:8001")
        print(f"  HTTP API: http://{REMOTE_HOST}:8000")
        print(f"\nUseful commands:")
        print(f"  Check status: systemctl status titan-net")
        print(f"  View logs: journalctl -u titan-net -f")
        print(f"  Restart: systemctl restart titan-net")
        print(f"  Stop: systemctl stop titan-net")

        sftp.close()

    except Exception as e:
        print(f"[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        ssh.close()

    return 0

if __name__ == '__main__':
    exit(main())
