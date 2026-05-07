"""Install SQLCipher on the remote titan-net server."""
import os
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
    # Strip anything the Windows console can't render
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode('ascii', errors='replace').decode('ascii'))


def run(cmd, timeout=900):
    _safe_print(f'\n$ {cmd}')
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout, get_pty=False)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    rc = stdout.channel.recv_exit_status()
    if out:
        lines = out.splitlines()
        if len(lines) > 40:
            _safe_print('\n'.join(lines[:10]))
            _safe_print(f'... ({len(lines) - 30} lines omitted) ...')
            _safe_print('\n'.join(lines[-20:]))
        else:
            _safe_print(out.rstrip())
    if err:
        err_lines = err.splitlines()
        if len(err_lines) > 20:
            _safe_print('STDERR: ' + '\n'.join(err_lines[:10]))
            _safe_print(f'... ({len(err_lines) - 15} lines omitted) ...')
            _safe_print('STDERR: ' + '\n'.join(err_lines[-5:]))
        else:
            _safe_print('STDERR: ' + err.rstrip())
    _safe_print(f'[exit={rc}]')
    return rc, out, err


try:
    # Discover available package names on this distro
    run('cat /etc/os-release | head -5')
    run('apt-cache search sqlcipher')
    run('apt-get update -qq')
    # Try the actual package names
    rc, _, _ = run('DEBIAN_FRONTEND=noninteractive apt-get install -y libsqlcipher-dev sqlcipher build-essential python3-dev')
    if rc != 0:
        print('[INFO] trying alternate package set')
        run('DEBIAN_FRONTEND=noninteractive apt-get install -y libsqlcipher-dev build-essential python3-dev')

    # Try the pre-built wheel first (no compile needed, bundles its own libsqlcipher)
    rc, out, _ = run('/opt/titan-net/venv/bin/pip install --upgrade sqlcipher3-binary')
    if rc != 0 or 'Successfully installed' not in out:
        print('[INFO] sqlcipher3-binary unavailable, falling back to source build')
        run('/opt/titan-net/venv/bin/pip install sqlcipher3')

    run('/opt/titan-net/venv/bin/python -c "import sqlcipher3; print(\'sqlcipher3 OK:\', sqlcipher3.version, sqlcipher3.sqlite_version)"')
finally:
    ssh.close()
