#!/usr/bin/env python3
"""
Run the Cerberus reset on the production server.

Reuses update.py's connection (the same .env credentials and the same retry
behaviour), stops the service, runs ``cerberus_reset.py`` there, and starts it
again. The service is stopped for the reset on purpose: Cerberus holds the ban
list in memory and writes it back, so wiping the database underneath a running
process would leave the old bans in RAM and put them straight back.

Usage:
    python remote_cerberus_reset.py            # bans, logs, memory, firewall
    python remote_cerberus_reset.py --no-firewall
"""

import sys

import update as deploy


def run(state, cmd, label=""):
    """exec_with_retry answers (exit code, stdout bytes, stderr bytes)."""
    print(f"$ {cmd}")
    rc, out, err = deploy.exec_with_retry(state, cmd)
    for stream in (out, err):
        text = stream.decode("utf-8", "replace").rstrip() if stream else ""
        if text:
            print(text)
    return rc



def main():
    firewall = "--no-firewall" not in sys.argv
    print("=== Cerberus reset on production ===\n")
    state = {}
    state['ssh'] = deploy.connect()
    state['sftp'] = state['ssh'].open_sftp()
    print("[OK] Connected\n")

    path = deploy.REMOTE_PATH
    try:
        run(state, "systemctl stop titan-net 2>/dev/null; true")
        print("[OK] Service stopped\n")
        flags = "--yes" + (" --firewall" if firewall else "")
        run(state, f"cd {path} && python3 cerberus_reset.py {flags}")
    finally:
        print("\nStarting the service again...")
        run(state, "systemctl start titan-net")
        run(state, "systemctl is-active titan-net || true")
        try:
            state['sftp'].close()
            state['ssh'].close()
        except Exception:
            pass
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
