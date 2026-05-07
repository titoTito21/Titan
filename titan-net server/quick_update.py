#!/usr/bin/env python3
"""
Quick update - upload modified server.py and restart service
"""
import paramiko
import os

# Load credentials from .env
def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())

_load_env()

HOST = os.environ.get('DEPLOY_HOST', 'titosofttitan.com')
USER = os.environ.get('DEPLOY_USER', 'root')
PASSWORD = os.environ.get('DEPLOY_PASSWORD', '')
REMOTE_DIR = os.environ.get('DEPLOY_PATH', '/opt/titan-net')

if not PASSWORD:
    print("[ERROR] DEPLOY_PASSWORD not set! Create a .env file with DEPLOY_PASSWORD=...")
    exit(1)

print("=" * 60)
print("QUICK SERVER UPDATE")
print("=" * 60)

# Connect to server
print(f"\n1. Connecting to {HOST}...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASSWORD)
print("[OK] Connected!")

# Upload server.py
print("\n2. Uploading server.py...")
sftp = ssh.open_sftp()
local_file = "server.py"
remote_file = f"{REMOTE_DIR}/server.py"
sftp.put(local_file, remote_file)
print(f"[OK] Uploaded {local_file}")

# Upload check_server.py
print("\n3. Uploading check_server.py...")
local_file = "check_server.py"
remote_file = f"{REMOTE_DIR}/check_server.py"
sftp.put(local_file, remote_file)
print(f"[OK] Uploaded {local_file}")

sftp.close()

# Restart service
print("\n4. Restarting titan-net service...")
stdin, stdout, stderr = ssh.exec_command("systemctl restart titan-net")
exit_code = stdout.channel.recv_exit_status()
if exit_code == 0:
    print("[OK] Service restarted successfully")
else:
    print(f"[ERROR] Service restart failed (exit code: {exit_code})")
    error_output = stderr.read().decode()
    if error_output:
        print(f"Error: {error_output}")

# Check service status
print("\n5. Checking service status...")
stdin, stdout, stderr = ssh.exec_command("systemctl status titan-net")
status_output = stdout.read().decode()
if "active (running)" in status_output:
    print("[OK] Service is running")
else:
    print("[WARN] Service may not be running")
    print(status_output)

# Show recent logs
print("\n6. Recent server logs:")
print("-" * 60)
stdin, stdout, stderr = ssh.exec_command(f"tail -20 {REMOTE_DIR}/logs/server.log")
log_output = stdout.read().decode()
print(log_output)
print("-" * 60)

ssh.close()
print("\n[SUCCESS] Update complete!")
print("=" * 60)
