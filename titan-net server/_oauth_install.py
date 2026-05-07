"""One-shot helper: install OAuth env on production via SSH.
Reads DEPLOY_* from local .env, writes /opt/titan-net/.env + systemd unit
with EnvironmentFile, restarts service, smoke-tests."""
import os, paramiko, time

with open('.env') as f:
    for line in f:
        if '=' in line and not line.startswith('#'):
            k, v = line.strip().split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(os.environ['DEPLOY_HOST'], username=os.environ['DEPLOY_USER'],
            password=os.environ['DEPLOY_PASSWORD'], timeout=10)

env_body = (
    "# Titan-Net runtime environment (loaded by systemd EnvironmentFile=)\n"
    "# Add SPOTIFY_CLIENT_ID/SECRET and ALLEGRO_CLIENT_ID/SECRET here when ready.\n"
    "\n"
    "OAUTH_PUBLIC_URL=https://titosofttitan.com\n"
    "TITAN_OAUTH_KEY=KuCW1U4NnW4lXZ2GSoQzj9HivTDNSJYPttRrg_PwW4Q=\n"
)

unit_body = (
    "[Unit]\n"
    "Description=Titan-Net Server\n"
    "After=network.target\n"
    "\n"
    "[Service]\n"
    "Type=simple\n"
    "WorkingDirectory=/opt/titan-net\n"
    "EnvironmentFile=-/opt/titan-net/.env\n"
    "ExecStart=/opt/titan-net/venv/bin/python3 /opt/titan-net/main.py\n"
    "Restart=always\n"
    "RestartSec=5\n"
    "StandardOutput=journal\n"
    "StandardError=journal\n"
    "\n"
    "[Install]\n"
    "WantedBy=multi-user.target\n"
)

sftp = ssh.open_sftp()
with sftp.open('/opt/titan-net/.env', 'w') as f:
    f.write(env_body)
sftp.chmod('/opt/titan-net/.env', 0o600)
print('[OK] wrote /opt/titan-net/.env (chmod 600)')
with sftp.open('/etc/systemd/system/titan-net.service', 'w') as f:
    f.write(unit_body)
print('[OK] wrote titan-net.service unit')
sftp.close()


def run(cmd):
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode(errors='replace')
    err = stderr.read().decode(errors='replace')
    rc = stdout.channel.recv_exit_status()
    print(f'>>> {cmd}\n[rc={rc}] {out}{err}')


run('systemctl daemon-reload')
run('systemctl restart titan-net')
time.sleep(3)
run('systemctl is-active titan-net')
run("python3 -c \"import os; pid=int(open('/run/titan-net.pid').read()) if os.path.exists('/run/titan-net.pid') else None; print(pid)\" 2>/dev/null || true")
run("ps -ef | grep -E 'main.py' | grep -v grep | head -1")
run("for p in $(pgrep -f 'main.py'); do echo --- PID $p ---; tr '\\0' '\\n' < /proc/$p/environ | grep -E '^(TITAN_OAUTH_KEY|OAUTH_PUBLIC_URL)'; done")
run('curl -sk https://titosofttitan.com/api/oauth/spotify/status')
run('curl -sk -o /dev/null -w "%{http_code}\\n" https://titosofttitan.com/oauth/spotify/start')
ssh.close()
