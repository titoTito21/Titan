"""Restart titan-net and verify SQLCipher migration happened."""
import os
import time
import paramiko


def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())


_load_env()
HOST = os.environ.get('DEPLOY_HOST', 'titosofttitan.com')
USER = os.environ.get('DEPLOY_USER', 'root')
PASSWORD = os.environ.get('DEPLOY_PASSWORD', '')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASSWORD, timeout=15)


def _safe_print(s):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode('ascii', errors='replace').decode('ascii'))


def run(cmd, timeout=300):
    _safe_print(f'\n$ {cmd}')
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    rc = stdout.channel.recv_exit_status()
    if out:
        _safe_print(out.rstrip())
    if err:
        _safe_print('STDERR: ' + err.rstrip())
    _safe_print(f'[exit={rc}]')
    return rc, out, err


try:
    # Backup current main DB on remote (separate from deploy's auto-backup)
    run('cp /opt/titan-net/database/titannet.db /opt/titan-net/database/titannet.pre_sqlcipher.db')

    # Restart so models.py picks up sqlcipher3 and auto-migrates
    run('systemctl restart titan-net')
    time.sleep(3)
    run('systemctl is-active titan-net')

    # Wait for startup + migration
    time.sleep(5)

    # Check the DB file - should NOT be readable as plain sqlite anymore
    run('file /opt/titan-net/database/titannet.db')
    run('ls -la /opt/titan-net/database/')
    run('journalctl -u titan-net -n 80 --no-pager | grep -iE "sqlcipher|encrypt|migrat" | tail -20')
    # Confirm the service is still healthy (no crash loop)
    run('systemctl status titan-net --no-pager -l | head -15')
finally:
    ssh.close()
