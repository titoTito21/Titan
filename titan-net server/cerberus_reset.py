#!/usr/bin/env python3
"""
Start Cerberus again from nothing.

Wipes the ban database, the intrusion and honeypot logs, Blackwall's memory
and transcript, and - if asked - the firewall rules Cerberus put in the
kernel. What it deliberately does NOT touch:

  * ``database/cerberus_whitelist.txt`` - the addresses that must never be
    blocked. Losing that is how an operator locks themselves out.
  * ``database/titannet.db`` - the users, messages and mail. This script must
    never open it: a second connection alongside the running server corrupts
    SQLCipher (see the PID lock in models.py).
  * the SSH ACCEPT rule, and anything in the firewall that Cerberus did not
    add itself.

The ban database is copied to a timestamped backup first unless --no-backup.

Usage:
    python cerberus_reset.py --yes                 # data only
    sudo python cerberus_reset.py --yes --firewall # data and kernel rules
    python cerberus_reset.py --dry-run             # say what it would do
"""

import argparse
import glob
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
BAN_DB = os.path.join(HERE, "database", "cerberus_bans.db")
BLACKWALL_MEMORY = os.path.join(HERE, "database", "blackwall_memory.json")
LOG_DIR = os.path.join(HERE, "logs")
LOG_FILES = [
    "cerberus_intrusions.log",
    "hackback.log",
    "countermeasures.log",
    "honeypot_sessions.log",
    "blackwall_transcript.log",
]
CHAIN = "CERBERUS"
TITAN_PORTS = ["8000", "8001"]


def say(msg):
    print(msg, flush=True)


def backup_db(dry_run: bool) -> str:
    if not os.path.exists(BAN_DB):
        return ""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(HERE, "database", f"cerberus_bans_before_reset_{stamp}.db")
    if dry_run:
        say(f"  would copy {BAN_DB} -> {os.path.basename(dest)}")
        return dest
    shutil.copy2(BAN_DB, dest)
    say(f"  backed up to {os.path.basename(dest)}")
    return dest


def clear_ban_db(dry_run: bool) -> int:
    if not os.path.exists(BAN_DB):
        say("  no ban database - nothing to clear")
        return 0
    conn = sqlite3.connect(BAN_DB)
    c = conn.cursor()
    cleared = 0
    try:
        for table in ("banned_ips", "banned_subnets", "attacker_profiles"):
            try:
                c.execute(f"SELECT COUNT(*) FROM {table}")
                n = c.fetchone()[0]
            except sqlite3.OperationalError:
                continue
            cleared += n
            if dry_run:
                say(f"  would delete {n} row(s) from {table}")
                continue
            c.execute(f"DELETE FROM {table}")
            say(f"  cleared {n} row(s) from {table}")
        if not dry_run:
            conn.commit()
            c.execute("VACUUM")
    finally:
        conn.close()
    return cleared


def clear_logs(dry_run: bool) -> int:
    cleared = 0
    for name in LOG_FILES:
        path = os.path.join(LOG_DIR, name)
        # The live file plus whatever the rotator left behind.
        for target in [path] + sorted(glob.glob(path + ".*")):
            if not os.path.exists(target):
                continue
            cleared += 1
            if dry_run:
                say(f"  would clear {os.path.basename(target)}")
                continue
            if target == path:
                open(target, "w", encoding="utf-8").close()
            else:
                os.remove(target)
    if not cleared:
        say("  no logs to clear")
    else:
        say(f"  {cleared} log file(s) {'would be ' if dry_run else ''}cleared")
    return cleared


def clear_blackwall_memory(dry_run: bool) -> bool:
    if not os.path.exists(BLACKWALL_MEMORY):
        say("  no Blackwall memory - nothing to forget")
        return False
    if dry_run:
        say("  would forget every remembered campaign")
        return True
    os.remove(BLACKWALL_MEMORY)
    say("  Blackwall has forgotten every campaign it knew")
    return True


def _iptables(*args):
    return subprocess.run(["iptables", *args], capture_output=True,
                          text=True, timeout=10)


def clear_firewall(dry_run: bool) -> int:
    """Empty Cerberus' own chain, and any rule an older version left in INPUT.

    Only DROP rules whose source is a single address or a subnet, and only on
    the Titan-Net ports or with no port at all - which is precisely what
    Cerberus adds. Everything else in INPUT belongs to somebody else.
    """
    removed = 0
    try:
        result = _iptables("-S", CHAIN)
    except FileNotFoundError:
        say("  iptables is not installed here - skipping the kernel")
        return 0
    except Exception as e:
        say(f"  could not read the firewall: {e}")
        return 0

    if result.returncode == 0:
        rules = [l for l in result.stdout.splitlines() if l.startswith("-A ")]
        removed += len(rules)
        if dry_run:
            say(f"  would flush {len(rules)} rule(s) from the {CHAIN} chain")
        else:
            _iptables("-F", CHAIN)
            say(f"  flushed {len(rules)} rule(s) from the {CHAIN} chain")
    else:
        say(f"  no {CHAIN} chain in the kernel")

    # Legacy rules, from before the chain existed.
    result = _iptables("-S", "INPUT")
    if result.returncode != 0:
        return removed
    for line in result.stdout.splitlines():
        parts = line.split()
        if not line.startswith("-A INPUT") or "-j" not in parts:
            continue
        if parts[parts.index("-j") + 1] != "DROP" or "-s" not in parts:
            continue
        if "--dport" in parts and parts[parts.index("--dport") + 1] not in TITAN_PORTS:
            continue          # somebody else's rule
        removed += 1
        if dry_run:
            say(f"  would remove legacy rule:{line[9:]}")
            continue
        _iptables("-D", "INPUT", *parts[2:])
        say(f"  removed legacy rule:{line[9:]}")
    return removed


def main():
    ap = argparse.ArgumentParser(description="Reset Cerberus to a clean state.")
    ap.add_argument("--yes", action="store_true",
                    help="do it without asking (needed when there is no terminal)")
    ap.add_argument("--dry-run", action="store_true",
                    help="say what would happen and change nothing")
    ap.add_argument("--firewall", action="store_true",
                    help="also remove Cerberus' rules from the kernel (needs root)")
    ap.add_argument("--no-backup", action="store_true",
                    help="do not copy the ban database first")
    args = ap.parse_args()

    say("Cerberus reset")
    say(f"  server directory : {HERE}")
    say(f"  ban database     : {'present' if os.path.exists(BAN_DB) else 'absent'}")
    say(f"  firewall rules   : {'yes' if args.firewall else 'left alone'}")
    say("  whitelist and titannet.db are never touched")
    say("")

    if not args.dry_run and not args.yes:
        if not sys.stdin.isatty():
            say("Refusing to run unattended without --yes.")
            return 1
        if input("Wipe the bans, the logs and Blackwall's memory? [y/N] ").strip().lower() != "y":
            say("Nothing was changed.")
            return 1

    if not args.no_backup:
        say("Backup:")
        backup_db(args.dry_run)
    say("Ban database:")
    clear_ban_db(args.dry_run)
    say("Logs:")
    clear_logs(args.dry_run)
    say("Blackwall memory:")
    clear_blackwall_memory(args.dry_run)
    if args.firewall:
        say("Firewall:")
        if os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() != 0:
            say("  not running as root - the kernel rules were left alone")
        else:
            clear_firewall(args.dry_run)

    say("")
    if args.dry_run:
        say("Dry run - nothing was changed.")
    else:
        say("Done. Restart the Titan-Net service so Cerberus starts from nothing:")
        say("  systemctl restart titan-net")
    return 0


if __name__ == "__main__":
    sys.exit(main())
